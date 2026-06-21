"""Transaction lifecycle endpoints (PRD §3.5-§3.7)."""

import datetime

from flask import Blueprint, request

from calculations import compute_repair_credit, compute_revised_avm
from constants import (
    INSPECTION_LEAD_DAYS,
    MAX_CLOSE_WINDOW_DAYS,
    MAX_LEASEBACK_DAYS,
    MIN_CLOSE_LEAD_DAYS,
    REPAIR_CREDIT_CAP_PCT,
    RETRADE_CAP_PCT,
)
from db import store
from errors import err
from helpers import (
    get_transaction_or_404,
    pagination_params,
    paginate,
    parse_datetime_field,
    require_property_owner,
)
from middleware import authenticate, require_role
from models import serialize, touch
from money import D, round2
from response import array_response, object_response
from tx_compute import recompute_transaction_financials
from validators import as_int, as_number, get_body, require

bp = Blueprint("transactions", __name__)


def _finalized_assessment_for_offer(offer_id):
    for a in store.assessments.values():
        if a["offer_id"] == offer_id:
            return a
    return None


@bp.route("/transactions", methods=["GET"])
def list_transactions():
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    records = list(store.transactions.values())
    offer_filter = request.args.get("offer_id")
    property_filter = request.args.get("property_id")
    status_filter = request.args.get("status")
    if offer_filter is not None:
        records = [r for r in records if r["offer_id"] == offer_filter]
    if property_filter is not None:
        records = [r for r in records if r["property_id"] == property_filter]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    limit, offset = pagination_params()
    page, total = paginate(records, limit, offset)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/transactions/<tx_id>", methods=["GET"])
def get_transaction(tx_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    rec = get_transaction_or_404(tx_id)
    return object_response(serialize(rec), 200)


@bp.route("/transactions/<tx_id>/schedule-close", methods=["POST"])
def schedule_close(tx_id):
    uid, role = authenticate()
    require_role(role, {"Seller"})
    tx = get_transaction_or_404(tx_id)
    prop = store.properties[tx["property_id"]]
    require_property_owner(prop, role, uid)

    # State (priority 5): must be PENDING_ASSESSMENT
    if tx["status"] != "PENDING_ASSESSMENT":
        raise err("ERR_INVALID_STATE", "Transaction is not PENDING_ASSESSMENT")

    body = get_body(request)
    close_date_raw = require(body, "close_date")
    close_date = parse_datetime_field(close_date_raw, "close_date")

    leaseback_days = 0
    if body.get("leaseback_days") is not None:
        # validate type/int but defer the >MAX check to the ordered precondition below
        leaseback_days = as_int(body["leaseback_days"], "leaseback_days", minimum=0)

    final_concession = 0.0
    if body.get("final_concession") is not None:
        final_concession = as_number(body["final_concession"], "final_concession", minimum=0)

    offer = store.offers[tx["offer_id"]]
    assessment = _finalized_assessment_for_offer(tx["offer_id"])

    # Priority 7: linked assessment must be FINALIZED
    if assessment is None or assessment["status"] != "FINALIZED":
        raise err("ERR_ASSESSMENT_NOT_FINALIZED", "Linked assessment is not FINALIZED")

    # Priority 9: close_date within [now+MIN_CLOSE_LEAD_DAYS, now+MAX_CLOSE_WINDOW_DAYS]
    now = store.now()
    earliest = now + datetime.timedelta(days=MIN_CLOSE_LEAD_DAYS)
    latest = now + datetime.timedelta(days=MAX_CLOSE_WINDOW_DAYS)
    if close_date < earliest or close_date > latest:
        raise err("ERR_CLOSE_DATE_OUT_OF_WINDOW", "close_date outside permitted window")

    # Priority 10: leaseback_days within [0, MAX_LEASEBACK_DAYS]
    if leaseback_days > MAX_LEASEBACK_DAYS:
        raise err("ERR_LEASEBACK_EXCEEDS_MAX", "leaseback_days exceeds maximum")

    # Compute repair credit (round-per-line then sum) from the FINALIZED assessment.
    repair_credit = compute_repair_credit(assessment["id"])

    # Priority 13: repair_credit <= avm_value_snapshot * REPAIR_CREDIT_CAP_PCT
    cap = round2(D(offer["avm_value_snapshot"]) * D(REPAIR_CREDIT_CAP_PCT))
    if D(repair_credit) > D(cap):
        raise err("ERR_REPAIR_CREDIT_EXCEEDS_CAP", "repair_credit exceeds cap")

    # Commit
    tx["repair_credit"] = repair_credit
    tx["close_date"] = close_date
    tx["leaseback_days"] = leaseback_days
    tx["final_concession"] = final_concession
    recompute_transaction_financials(tx)
    tx["status"] = "SCHEDULED"
    touch(tx)
    return object_response(serialize(tx), 200)


@bp.route("/transactions/<tx_id>/start-inspection", methods=["POST"])
def start_inspection(tx_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin"})
    tx = get_transaction_or_404(tx_id)

    # State (priority 5): must be SCHEDULED
    if tx["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Transaction is not SCHEDULED")

    # Inspection window opens close_date - INSPECTION_LEAD_DAYS
    window_open = tx["close_date"] - datetime.timedelta(days=INSPECTION_LEAD_DAYS)
    if store.now() < window_open:
        raise err("ERR_INVALID_STATE", "Inspection window not yet open")

    tx["status"] = "INSPECTION"
    touch(tx)
    return object_response(serialize(tx), 200)


@bp.route("/transactions/<tx_id>/retrade", methods=["POST"])
def retrade(tx_id):
    _uid, role = authenticate()
    require_role(role, {"PricingAnalyst"})
    tx = get_transaction_or_404(tx_id)

    # State (priority 5): must be INSPECTION
    if tx["status"] != "INSPECTION":
        raise err("ERR_INVALID_STATE", "Transaction is not in INSPECTION")

    body = get_body(request)
    retrade_amount = as_number(require(body, "retrade_amount"), "retrade_amount", minimum=0)

    offer = store.offers[tx["offer_id"]]
    prop = store.properties[tx["property_id"]]

    # Priority 11: retrade_amount <= avm_value_snapshot * RETRADE_CAP_PCT
    cap = round2(D(offer["avm_value_snapshot"]) * D(RETRADE_CAP_PCT))
    if D(retrade_amount) > D(cap):
        raise err("ERR_RETRADE_EXCEEDS_CAP", "retrade_amount exceeds cap")

    # Priority 12: at most one re-trade (retrade_amount already nonzero)
    if D(tx["retrade_amount"]) != D(0):
        raise err("ERR_RETRADE_ALREADY_APPLIED", "A re-trade has already been applied")

    # Apply cascade
    tx["retrade_amount"] = retrade_amount
    prop["revised_avm_value"] = compute_revised_avm(offer["avm_value_snapshot"], retrade_amount)
    touch(prop)

    recompute_transaction_financials(tx)
    touch(tx)
    return object_response(serialize(tx), 200)


@bp.route("/transactions/<tx_id>/close", methods=["POST"])
def close_transaction(tx_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin"})
    tx = get_transaction_or_404(tx_id)

    # State (priority 5): only from INSPECTION
    if tx["status"] != "INSPECTION":
        raise err("ERR_INVALID_STATE", "Transaction is not in INSPECTION")

    recompute_transaction_financials(tx)
    tx["status"] = "CLOSED"
    touch(tx)

    prop = store.properties[tx["property_id"]]
    prop["status"] = "SOLD"
    touch(prop)
    # Offer remains ACCEPTED.
    return object_response(serialize(tx), 200)


@bp.route("/transactions/<tx_id>/cancel", methods=["POST"])
def cancel_transaction(tx_id):
    uid, role = authenticate()
    require_role(role, {"Seller"})
    tx = get_transaction_or_404(tx_id)
    prop = store.properties[tx["property_id"]]
    require_property_owner(prop, role, uid)

    # State (priority 5): cancellable from PENDING_ASSESSMENT / SCHEDULED / INSPECTION
    if tx["status"] not in ("PENDING_ASSESSMENT", "SCHEDULED", "INSPECTION"):
        raise err("ERR_INVALID_STATE", "Transaction cannot be cancelled from its current state")

    # consume optional cancel_reason (recorded for the record; no state impact)
    get_body(request)

    # Compensation: if a re-trade was applied, revert revised AVM to null.
    if D(tx["retrade_amount"]) != D(0):
        prop["revised_avm_value"] = None
        touch(prop)

    tx["status"] = "CANCELLED"
    touch(tx)

    offer = store.offers[tx["offer_id"]]
    offer["status"] = "DECLINED"
    touch(offer)

    prop["status"] = "VALUED"
    prop["active_offer_id"] = None
    touch(prop)

    return object_response(serialize(tx), 200)
