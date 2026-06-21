"""CommissionStatement endpoints (PRD §3.10) and its state machine."""
from flask import Blueprint, request

import clock
import serialize
from db import store, new_common, touch
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_INVALID_DATE_RANGE,
    ERR_NOTHING_PAYABLE,
    ERR_TRUST_MINIMUM_BREACH,
    ERR_VALIDATION_PERIOD_NOT_ENDED,
)
from middleware import auth, get_json_body, lookup, check_version, paginate
from response import object_response, array_response
from services import trust
from services.calculations import compute_statement_figures
from util import require_str, parse_dt

bp = Blueprint("commission_statements", __name__)

READ_ROLES = {"AgencyAdmin", "Producer", "TrustAccountant"}


@bp.post("/commission-statements")
def create_statement():
    auth({"TrustAccountant"})
    body = get_json_body()
    producer_id = require_str(body, "producer_id")
    with store.lock:
        lookup(store.producers, producer_id)  # existence
        ps = parse_dt(require_str(body, "period_start"), "period_start")
        pe = parse_dt(require_str(body, "period_end"), "period_end")
        if not (ps < pe):
            raise err(ERR_INVALID_DATE_RANGE, "period_start must be before period_end")
        rec = new_common()
        rec.update(
            producer_id=producer_id,
            period_start=body["period_start"],
            period_end=body["period_end"],
            gross_commission_cents=0,
            chargeback_cents=0,
            net_payable_cents=0,
            status="OPEN",
        )
        store.commission_statements[rec["id"]] = rec
        return object_response(serialize.commission_statement(rec), 201)


@bp.get("/commission-statements/<sid>")
def get_statement(sid):
    auth(READ_ROLES)
    rec = lookup(store.commission_statements, sid)
    return object_response(serialize.commission_statement(rec))


@bp.get("/commission-statements")
def list_statements():
    auth(READ_ROLES)
    producer_id = request.args.get("producer_id")
    status = request.args.get("status")
    recs = [
        s
        for s in store.commission_statements.values()
        if (producer_id is None or s["producer_id"] == producer_id)
        and (status is None or s["status"] == status)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.commission_statement(s) for s in page], limit, offset, total)


@bp.post("/commission-statements/<sid>/finalize")
def finalize_statement(sid):
    auth({"TrustAccountant"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.commission_statements, sid)
        if rec["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "only an OPEN statement may be finalized")
        check_version(rec, body.get("expected_commissionstatement_version"),
                      "expected_commissionstatement_version")
        # business: period must have ended (period_end <= server-now).
        pe = parse_dt(rec["period_end"], "period_end")
        if not (pe <= clock.now()):
            raise err(ERR_VALIDATION_PERIOD_NOT_ENDED, "period has not ended yet")
        # freeze the figures at currently computed values.
        gross, chargeback, net = compute_statement_figures(rec)
        rec["gross_commission_cents"] = gross
        rec["chargeback_cents"] = chargeback
        rec["net_payable_cents"] = net
        rec["status"] = "FINALIZED"
        touch(rec)
        return object_response(serialize.commission_statement(rec))


@bp.post("/commission-statements/<sid>/reopen")
def reopen_statement(sid):
    auth({"TrustAccountant"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.commission_statements, sid)
        if rec["status"] != "FINALIZED":
            raise err(ERR_INVALID_STATE, "only a FINALIZED (unpaid) statement may be reopened")
        check_version(rec, body.get("expected_commissionstatement_version"),
                      "expected_commissionstatement_version")
        rec["status"] = "OPEN"  # figures recompute live on next read.
        touch(rec)
        return object_response(serialize.commission_statement(rec))


@bp.post("/commission-statements/<sid>/pay")
def pay_statement(sid):
    auth({"TrustAccountant"})
    body = get_json_body()
    trust_account_id = require_str(body, "trust_account_id")
    with store.lock:
        rec = lookup(store.commission_statements, sid)
        ta = lookup(store.trust_accounts, trust_account_id)  # existence
        if rec["status"] != "FINALIZED":
            raise err(ERR_INVALID_STATE, "only a FINALIZED statement may be paid")
        check_version(rec, body.get("expected_commissionstatement_version"),
                      "expected_commissionstatement_version")
        # business: nothing payable when net <= 0.
        net = rec["net_payable_cents"]
        if net <= 0:
            raise err(ERR_NOTHING_PAYABLE, "statement net_payable_cents is not positive")
        # fiscal: disbursement must not breach the trust minimum floor.
        projected = trust.balance(trust_account_id) - net
        if projected < ta["minimum_balance_cents"]:
            raise err(ERR_TRUST_MINIMUM_BREACH, "disbursement would breach minimum balance")
        # post COMMISSION_DISBURSEMENT of -net to the trust account.
        trust.post_entry(trust_account_id, "COMMISSION_DISBURSEMENT", -net, policy_id=None)
        touch(ta)
        rec["status"] = "PAID"
        touch(rec)
        return object_response(serialize.commission_statement(rec))
