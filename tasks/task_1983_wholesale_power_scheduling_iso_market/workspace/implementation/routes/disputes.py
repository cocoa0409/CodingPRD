from flask import Blueprint, request

from auth import parse_auth, require_role, check_ownership
from db import store
from envelope import ok, paginate
from errors import (not_found, invalid_request, conflict, ERR_INVALID_STATE,
                    ERR_DISPUTE_ALREADY_OPEN, ERR_STATEMENT_NOT_FINAL,
                    ERR_DISPUTE_WINDOW_CLOSED)
from routes.statements import get_statement
from util import (get_body, check_unknown, req_enum, new_record, serialize,
                  sort_key, touch)
from services import settlement
from services.credit import refresh_credit

bp = Blueprint("disputes", __name__)

REASONS = ("PRICE_ERROR", "METER_DATA_ERROR", "CALCULATION_ERROR",
           "MISSING_ANCILLARY_CREDIT")
ERR_LINE_NOT_IN_STATEMENT = "ERR_LINE_NOT_IN_STATEMENT"


def get_dispute(did):
    d = store.disputes.get(did)
    if d is None:
        raise not_found("dispute not found")
    return d


@bp.post("/market/statements/<statementId>/disputes")
def create_dispute(statementId):
    auth = parse_auth()
    require_role(auth, ["SettlementAnalyst"])
    body = get_body()
    check_unknown(body, {"dispute_reason", "disputed_line_ids"})
    reason = req_enum(body, "dispute_reason", REASONS)
    line_ids = body.get("disputed_line_ids")
    if (not isinstance(line_ids, list) or len(line_ids) == 0
            or any(not isinstance(x, str) for x in line_ids)):
        raise invalid_request("disputed_line_ids must be a non-empty list of line ids")

    stmt = get_statement(statementId)
    check_ownership(auth, stmt["market_participant_id"])
    # 7: path-target state machine, including the single-open-dispute rule
    if stmt["status"] == "UNDER_DISPUTE":
        raise conflict(ERR_DISPUTE_ALREADY_OPEN,
                       "a dispute of this statement is already open")
    if stmt["status"] != "ISSUED":
        raise conflict(ERR_INVALID_STATE,
                       "only an ISSUED statement can be disputed")
    # 8: statement finality
    if stmt["run_type"] not in ("FINAL", "RESETTLEMENT"):
        raise conflict(ERR_STATEMENT_NOT_FINAL,
                       "only FINAL or RESETTLEMENT statements can be disputed")
    # 9: every disputed line must belong to this statement
    for lid in line_ids:
        line = store.lines.get(lid)
        if line is None or line["settlement_statement_id"] != stmt["id"]:
            raise conflict(ERR_LINE_NOT_IN_STATEMENT,
                           "disputed line %s does not belong to the statement" % lid)
    # 10: dispute window (exactly at window end is accepted)
    if stmt["dispute_window_ends_at"] is not None and store.clock_now > stmt["dispute_window_ends_at"]:
        raise conflict(ERR_DISPUTE_WINDOW_CLOSED, "the dispute window has closed")

    rec = new_record()
    rec.update({
        "settlement_statement_id": stmt["id"],
        "market_participant_id": stmt["market_participant_id"],
        "dispute_reason": reason,
        "disputed_line_ids": list(line_ids),
        "status": "FILED",
    })
    store.disputes[rec["id"]] = rec
    stmt["status"] = "UNDER_DISPUTE"
    touch(stmt)
    return ok(serialize(rec), status=201)


@bp.get("/market/disputes/<disputeId>")
def get_one(disputeId):
    parse_auth()
    return ok(serialize(get_dispute(disputeId)))


@bp.get("/market/disputes")
def list_disputes():
    parse_auth()
    rows = sorted(store.disputes.values(), key=sort_key)
    sid = request.args.get("settlement_statement_id")
    pid = request.args.get("market_participant_id")
    status = request.args.get("status")
    if sid is not None:
        rows = [r for r in rows if r["settlement_statement_id"] == sid]
    if pid is not None:
        rows = [r for r in rows if r["market_participant_id"] == pid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])


@bp.post("/market/disputes/<disputeId>/start-review")
def start_review(disputeId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    dispute = get_dispute(disputeId)
    if dispute["status"] != "FILED":
        raise conflict(ERR_INVALID_STATE, "only a FILED dispute can enter review")
    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return ok(serialize(dispute))


@bp.post("/market/disputes/<disputeId>/resolve")
def resolve(disputeId):
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    body = get_body()
    check_unknown(body, {"outcome"})
    outcome = req_enum(body, "outcome", ("UPHELD", "REJECTED"))
    dispute = get_dispute(disputeId)
    if dispute["status"] != "UNDER_REVIEW":
        raise conflict(ERR_INVALID_STATE, "only an UNDER_REVIEW dispute can be resolved")
    stmt = store.statements[dispute["settlement_statement_id"]]
    if outcome == "REJECTED":
        dispute["status"] = "REJECTED"
        touch(dispute)
        stmt["status"] = "ISSUED"
        touch(stmt)
    else:
        dispute["status"] = "UPHELD"
        touch(dispute)
        stmt["status"] = "SUPERSEDED"
        touch(stmt)
        settlement.resettlement_recompute(stmt, dispute)
        refresh_credit(store.participants[stmt["market_participant_id"]])
    return ok(serialize(dispute))


@bp.post("/market/disputes/<disputeId>/withdraw")
def withdraw(disputeId):
    auth = parse_auth()
    require_role(auth, ["SettlementAnalyst"])
    dispute = get_dispute(disputeId)
    check_ownership(auth, dispute["market_participant_id"])
    if dispute["status"] != "FILED":
        raise conflict(ERR_INVALID_STATE, "only a FILED dispute can be withdrawn")
    dispute["status"] = "WITHDRAWN"
    touch(dispute)
    stmt = store.statements[dispute["settlement_statement_id"]]
    stmt["status"] = "ISSUED"
    touch(stmt)
    return ok(serialize(dispute))
