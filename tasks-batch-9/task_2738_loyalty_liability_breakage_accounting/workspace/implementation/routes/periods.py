"""AccountingPeriod endpoints, the rollforward and the expiry sweep (PRD §3.2, §3.7, §3.8)."""
from flask import Blueprint

import calc
import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT, ROLE_PROGRAM_ADMIN,
                  authorize)
from errors import ApiError
from response import created, ok, paginate
from util import clock, rhu
from validate import field_datetime, field_ref, field_string, json_body

bp = Blueprint("periods", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)

ROLLFORWARD_PERSISTED = (
    "opening_liability_cents",
    "pre_catchup_liability_cents",
    "required_liability_cents",
    "catch_up_adjustment_cents",
    "closing_liability_cents",
    "breakage_recognized_cents",
    "approved_estimate_rate_bp",
)


@bp.route("/accounting-periods", methods=["POST"])
def create_period():
    authorize(ROLE_CONTROLLER)
    body = json_body()
    program_id = field_ref(body, "program_id")
    period_code = field_string(body, "period_code", max_length=16)
    start_at = field_datetime(body, "start_at")
    end_at = field_datetime(body, "end_at")
    lookup.program(program_id)
    if not end_at > start_at:
        raise ApiError("ERR_INVALID_WINDOW", 409)
    siblings = db.program_periods(program_id)
    for sibling in siblings:
        if start_at < sibling["end_at"] and sibling["start_at"] < end_at:
            raise ApiError("ERR_PERIOD_OVERLAP", 409)
    for sibling in siblings:
        if sibling["period_code"] == period_code:
            raise ApiError("ERR_DUPLICATE_CODE", 409)
    rec = db.new_record(db.store.periods, {
        "program_id": program_id,
        "period_code": period_code,
        "start_at": start_at,
        "end_at": end_at,
        "state": "OPEN",
        "opening_liability_cents": 0,
        "issuance_deferred_cents": 0,
        "redemption_recognized_cents": 0,
        "remeasurement_delta_cents": 0,
        "expiry_released_cents": 0,
        "escheat_accrual_cents": 0,
        "pre_catchup_liability_cents": 0,
        "required_liability_cents": 0,
        "catch_up_adjustment_cents": 0,
        "breakage_recognized_cents": 0,
        "closing_liability_cents": 0,
        "approved_estimate_rate_bp": 0,
        "soft_closed_at": None,
        "reopen_count": 0,
    })
    return created(serialize.period(rec))


@bp.route("/accounting-periods", methods=["GET"])
def list_periods():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.periods),
                           "program_id", "state", "period_code")
    return paginate(rows, serialize.period)


@bp.route("/accounting-periods/<period_id>", methods=["GET"])
def read_period(period_id):
    authorize(*READ_ROLES)
    return ok(serialize.period(lookup.period(period_id)))


@bp.route("/accounting-periods/<period_id>/liability-rollforward", methods=["GET"])
def preview_rollforward(period_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)
    period = lookup.period(period_id)
    return ok(calc.rollforward(period))


@bp.route("/accounting-periods/<period_id>/soft-close", methods=["POST"])
def soft_close_period(period_id):
    authorize(ROLE_CONTROLLER)
    period = lookup.period(period_id)
    if period["state"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if calc.approved_estimate_for_period(period_id) is None:
        raise ApiError("ERR_ESTIMATE_NOT_APPROVED", 409)
    for event in db.store.redemption_events.values():
        if event["period_id"] == period_id and event["state"] == "REQUESTED":
            raise ApiError("ERR_UNALLOCATED_REDEMPTIONS", 409)
    if clock.now() < period["end_at"]:
        raise ApiError("ERR_PERIOD_NOT_ENDED", 409)
    figures = calc.rollforward(period)
    for name in ROLLFORWARD_PERSISTED:
        period[name] = figures[name]
    period["state"] = "SOFT_CLOSED"
    period["soft_closed_at"] = clock.now()
    db.touch(period)
    return ok(serialize.period(period))


def compensate_close(period):
    """Full compensation of a soft close, shared by manual and forced reopen."""
    for name in ROLLFORWARD_PERSISTED:
        period[name] = 0
    period["state"] = "OPEN"
    period["soft_closed_at"] = None
    period["reopen_count"] = period["reopen_count"] + 1
    db.touch(period)


@bp.route("/accounting-periods/<period_id>/reopen", methods=["POST"])
def reopen_period(period_id):
    authorize(ROLE_CONTROLLER)
    period = lookup.period(period_id)
    if period["state"] != "SOFT_CLOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if period["reopen_count"] >= 2:
        raise ApiError("ERR_REOPEN_LIMIT_EXCEEDED", 409)
    compensate_close(period)
    return ok(serialize.period(period))


@bp.route("/accounting-periods/<period_id>/hard-close", methods=["POST"])
def hard_close_period(period_id):
    authorize(ROLE_CONTROLLER)
    period = lookup.period(period_id)
    if period["state"] != "SOFT_CLOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    estimate = calc.approved_estimate_for_period(period_id)
    if estimate is None or not estimate["memo_narrative"]:
        raise ApiError("ERR_MEMO_NARRATIVE_REQUIRED", 409)
    for statement in db.store.settlement_statements.values():
        if statement["period_id"] != period_id:
            continue
        if statement["state"] not in ("PAID", "WRITTEN_OFF", "SUPERSEDED"):
            raise ApiError("ERR_UNSETTLED_STATEMENTS", 409)
    period["state"] = "HARD_CLOSED"
    db.touch(period)
    return ok(serialize.period(period))


def governing_rule(program_id, state_code):
    for rule in db.rows(db.store.state_expiry_rules):
        if rule["program_id"] == program_id and rule["state_code"] == state_code:
            return rule
    return None


@bp.route("/accounting-periods/<period_id>/expiry-sweep", methods=["POST"])
def expiry_sweep(period_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    period = lookup.period(period_id)
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    program = lookup.program(period["program_id"])
    now = clock.now()
    candidates = db.issuance_order([
        lot for lot in db.program_lots(program["id"])
        if calc.is_outstanding(lot) and lot["expires_at"] <= now
    ])
    touched_members = {}
    for lot in candidates:
        member = db.store.members.get(lot["member_id"])
        if member is None:
            continue
        rule = governing_rule(program["id"], member["state_code"])
        if rule is None or not rule["expiry_permitted"]:
            continue
        if calc.member_dormancy_days(member) < rule["min_dormancy_days"]:
            continue
        expired_gross = calc.lot_remaining_gross_ssp_cents(lot)
        released = calc.lot_remaining_deferred_cents(lot)
        lot["expired_gross_ssp_cents"] = expired_gross
        lot["points_remaining"] = 0
        lot["lifecycle_state"] = "EXPIRED"
        period["expiry_released_cents"] = period["expiry_released_cents"] + released
        if rule["escheatment_required"]:
            escheated = rhu(expired_gross * rule["escheat_rate_bp"], 10000)
            lot["escheated_cents"] = escheated
            lot["lifecycle_state"] = "ESCHEATED"
            period["escheat_accrual_cents"] = period["escheat_accrual_cents"] + escheated
            program["total_escheat_accrual_cents"] = (
                program["total_escheat_accrual_cents"] + escheated
            )
            if (program["total_escheat_accrual_cents"]
                    >= program["escheat_disclosure_threshold_cents"]):
                program["escheat_disclosure_required"] = True
        db.touch(lot)
        touched_members[member["id"]] = member
    for member in db.creation_order(list(touched_members.values())):
        if (member["status"] == "ACTIVE"
                and calc.member_point_balance(member["id"]) == 0
                and calc.member_dormancy_days(member)
                >= calc.DORMANCY_DAYS_FOR_MEMBER_FLAG):
            member["status"] = "DORMANT"
            db.touch(member)
    db.touch(program)
    db.touch(period)
    return ok(serialize.period(period))
