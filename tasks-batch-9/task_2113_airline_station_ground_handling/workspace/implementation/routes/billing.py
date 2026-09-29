from flask import Blueprint

import constants as C
import validators as V
from auth import authorize, authorize_action, current_user
from billing import compute_charge, projected_finalization_penalties, rollup_period
from domain import apply_changes, incidents_of_station, lines_of_period, serialize_billing_line, serialize_billing_period
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import as_dt, db, new_record, ordered, require

bp = Blueprint("billing", __name__)

PERIOD_ENDPOINT_ROLES = [C.ROLE_BILLING_CONTROLLER, C.ROLE_CONTRACT_AUDITOR]
PERIOD_ACTION_ROLES = {
    "FINALIZE": [C.ROLE_BILLING_CONTROLLER],
    "APPROVE": [C.ROLE_CONTRACT_AUDITOR],
    "REJECT": [C.ROLE_CONTRACT_AUDITOR],
}


# --------------------------------------------------------------- periods
@bp.post("/billing-periods")
def create_billing_period():
    authorize([C.ROLE_BILLING_CONTROLLER])
    payload = V.body()

    station_id = V.req_string(payload, "station_id")
    period_code = V.req_string(payload, "period_code")
    window_start = V.req_datetime(payload, "window_start")
    window_end = V.req_datetime(payload, "window_end")
    if as_dt(window_end) <= as_dt(window_start):
        raise ApiError("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")

    station = require(db.stations, station_id, "Station")

    for existing in db.billing_periods.values():
        if existing["station_id"] == station["id"] and existing["period_code"] == period_code:
            raise ApiError("ERR_DUPLICATE_CODE", "period_code already exists at this station.")

    period = new_record("BillingPeriod", {
        "station_id": station["id"],
        "period_code": period_code,
        "window_start": window_start,
        "window_end": window_end,
        "status": "OPEN",
        "line_count": 0,
        "accrued_cents": 0,
        "gross_total_cents": 0,
        "otp_penalty_cents": 0,
        "damage_penalty_cents": 0,
        "rebate_tier": "NONE",
        "rebate_cents": 0,
        "net_total_cents": 0,
        "finalized_by_user_id": None,
        "approved_by_user_id": None,
        "reject_count": 0,
    })
    db.billing_periods[period["id"]] = period
    return respond_object(serialize_billing_period(period), 201)


@bp.get("/billing-periods/<billing_period_id>")
def read_billing_period(billing_period_id):
    authorize(C.ALL_ROLES)
    period = require(db.billing_periods, billing_period_id, "BillingPeriod")
    return respond_object(serialize_billing_period(period))


@bp.get("/billing-periods")
def list_billing_periods():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.billing_periods.values(), {
        "station_id": "station_id",
        "status": "status",
    })
    return paginate(ordered(records), serialize_billing_period)


@bp.post("/billing-periods/<billing_period_id>/transitions")
def billing_period_transition(billing_period_id):
    payload = V.body()
    authorize_action(PERIOD_ENDPOINT_ROLES, PERIOD_ACTION_ROLES, payload.get("action"))
    period = require(db.billing_periods, billing_period_id, "BillingPeriod")
    action = V.req_enum(payload, "action", C.PERIOD_ACTIONS)
    V.opt_string(payload, "note")

    actor = current_user()
    station = db.stations[period["station_id"]]

    # ---- step 9: segregation of duties -----------------------------------
    if action == "APPROVE" and period["finalized_by_user_id"] is not None \
            and actor == period["finalized_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if action == "FINALIZE":
        if period["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        live_lines = [l for l in lines_of_period(period["id"]) if l["status"] != "VOID"]
        if len(live_lines) < 1:
            raise ApiError("ERR_INVALID_STATE", "The period holds no billable line.")
        for line in live_lines:
            turn = db.turns.get(line["turn_id"])
            if turn is None or turn["status"] not in ("COMPLETED", "CANCELLED"):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "Every charged turnaround must be COMPLETED or CANCELLED.",
                )
        open_critical = any(
            i["severity"] == "CRITICAL" and i["status"] != "CLOSED"
            for i in incidents_of_station(station["id"])
        )
        if open_critical:
            raise ApiError("ERR_OPEN_CRITICAL_INCIDENT")
        otp_total, damage_total = projected_finalization_penalties(period)
        if otp_total + damage_total > station["penalty_cap_cents"]:
            raise ApiError("ERR_PENALTY_CAP_BREACHED")

        for line in ordered(live_lines):
            apply_changes(line, {"status": "FINAL"})
        rollup_period(period)
        apply_changes(period, {
            "status": "PENDING_APPROVAL",
            "finalized_by_user_id": actor,
        })
    elif action == "APPROVE":
        if period["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(period, {"status": "APPROVED", "approved_by_user_id": actor})
    else:  # REJECT
        if period["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE")
        for line in ordered(lines_of_period(period["id"])):
            if line["status"] == "FINAL":
                apply_changes(line, {"status": "PROVISIONAL"})
        rollup_period(period)
        apply_changes(period, {
            "status": "OPEN",
            "finalized_by_user_id": None,
            "reject_count": period["reject_count"] + 1,
        })

    return respond_object(serialize_billing_period(period))


# ----------------------------------------------------------------- lines
@bp.post("/billing-lines")
def create_billing_line():
    authorize([C.ROLE_BILLING_CONTROLLER])
    payload = V.body()

    billing_period_id = V.req_string(payload, "billing_period_id")
    turn_id = V.req_string(payload, "turn_id")
    expected_version = V.req_int(payload, "expected_billing_period_version")

    period = require(db.billing_periods, billing_period_id, "BillingPeriod")
    turn = require(db.turns, turn_id, "Turn")

    if turn["station_id"] != period["station_id"]:
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")

    if expected_version != period["version"]:
        raise ApiError("ERR_STALE_PERIOD_VERSION")

    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN")
    if turn["status"] in ("CANCELLED", "DISRUPTED"):
        raise ApiError("ERR_TURN_NOT_BILLABLE")

    for existing in db.billing_lines.values():
        if existing["turn_id"] == turn["id"] and existing["status"] in ("PROVISIONAL", "FINAL"):
            raise ApiError("ERR_DUPLICATE_BILLING_LINE")

    draft = {
        "turn_id": turn["id"],
        "turn_type_snapshot": turn["turn_type"],
        "status": "PROVISIONAL",
    }
    charge = compute_charge(draft, "PROVISIONAL")

    line = new_record("BillingLine", {
        "billing_period_id": period["id"],
        "turn_id": turn["id"],
        "turn_type_snapshot": turn["turn_type"],
        "status": "PROVISIONAL",
        "base_rate_cents": charge["base_rate_cents"],
        "charged_ground_minutes": charge["charged_ground_minutes"],
        "excess_minutes": charge["excess_minutes"],
        "ground_time_tier": charge["ground_time_tier"],
        "gross_amount_cents": charge["gross_amount_cents"],
        "otp_penalty_cents": 0,
        "damage_penalty_cents": 0,
        "rebate_alloc_cents": 0,
        "net_amount_cents": charge["gross_amount_cents"],
        "void_reason": None,
    })
    db.billing_lines[line["id"]] = line

    apply_changes(turn, {"billed": True})
    rollup_period(period)

    return respond_object(serialize_billing_line(line), 201)


@bp.get("/billing-lines/<billing_line_id>")
def read_billing_line(billing_line_id):
    authorize(C.ALL_ROLES)
    line = require(db.billing_lines, billing_line_id, "BillingLine")
    return respond_object(serialize_billing_line(line))


@bp.get("/billing-lines")
def list_billing_lines():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.billing_lines.values(), {
        "billing_period_id": "billing_period_id",
        "turn_id": "turn_id",
        "status": "status",
    })
    return paginate(ordered(records), serialize_billing_line)


@bp.post("/billing-lines/<billing_line_id>/void")
def void_billing_line(billing_line_id):
    authorize([C.ROLE_BILLING_CONTROLLER])
    line = require(db.billing_lines, billing_line_id, "BillingLine")
    payload = V.body()
    reason = V.req_string(payload, "reason")

    period = db.billing_periods[line["billing_period_id"]]
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN")
    if line["status"] == "VOID":
        raise ApiError("ERR_INVALID_STATE")

    apply_changes(line, {"status": "VOID", "void_reason": reason})

    turn = db.turns.get(line["turn_id"])
    if turn is not None:
        still_billed = any(
            l["turn_id"] == turn["id"] and l["status"] in ("PROVISIONAL", "FINAL")
            for l in db.billing_lines.values()
        )
        apply_changes(turn, {"billed": still_billed})

    rollup_period(period)
    return respond_object(serialize_billing_line(line))
