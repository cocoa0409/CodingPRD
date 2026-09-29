"""RedemptionEvent endpoints: request, allocate, fulfill, reverse (PRD §3.4)."""
from flask import Blueprint

import calc
import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT, ROLE_MEMBER,
                  ROLE_PROGRAM_ADMIN, authorize, not_owner,
                  require_member_owns)
from errors import ApiError
from response import created, ok, paginate
from util import clock, rhu
from validate import (bad, field_enum, field_int, field_ref, field_string,
                      json_body)

bp = Blueprint("redemption_events", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)
REDEMPTION_TYPES = ("CATALOG", "PARTNER", "CASH_BACK")


def event_allocation_rows(event_id, entry_type=None):
    rows = [a for a in db.store.allocations.values()
            if a["redemption_event_id"] == event_id
            and (entry_type is None or a["entry_type"] == entry_type)]
    return db.allocation_order(rows)


@bp.route("/redemption-events", methods=["POST"])
def create_redemption_event():
    user_id, role = authorize(ROLE_LOYALTY_ACCOUNTANT, ROLE_MEMBER)
    body = json_body()
    if role == ROLE_MEMBER and body.get("member_id") != user_id:
        raise not_owner()
    member_id = field_ref(body, "member_id")
    period_id = field_ref(body, "period_id")
    agreement_id = field_ref(body, "partner_agreement_id", required=False)
    points_requested = field_int(body, "points_requested", minimum=1)
    redemption_type = field_enum(body, "redemption_type", REDEMPTION_TYPES)
    if redemption_type == "PARTNER" and not agreement_id:
        raise bad("redemption_type PARTNER requires partner_agreement_id.")
    member = lookup.member(member_id)
    period = lookup.period(period_id)
    agreement = lookup.partner_agreement(agreement_id) if agreement_id else None
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    program = lookup.program(member["program_id"])
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409)
    if period["program_id"] != member["program_id"]:
        raise ApiError("ERR_PERIOD_PROGRAM_MISMATCH", 409)
    if agreement is not None and agreement["program_id"] != member["program_id"]:
        raise ApiError("ERR_AGREEMENT_PROGRAM_MISMATCH", 409)
    rec = db.new_record(db.store.redemption_events, {
        "member_id": member_id,
        "period_id": period_id,
        "partner_agreement_id": agreement_id if agreement_id else None,
        "points_requested": points_requested,
        "redemption_type": redemption_type,
        "state": "REQUESTED",
        "provisional_release_cents": 0,
        "final_release_cents": 0,
        "remeasurement_delta_cents": 0,
        "partner_cost_cents": 0,
        "requested_at": clock.now(),
        "allocated_at": None,
        "reversal_reason": None,
    })
    return created(serialize.redemption_event(rec))


@bp.route("/redemption-events", methods=["GET"])
def list_redemption_events():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.redemption_events), "member_id",
                           "period_id", "partner_agreement_id", "state",
                           "redemption_type")
    return paginate(rows, serialize.redemption_event)


@bp.route("/redemption-events/<event_id>", methods=["GET"])
def read_redemption_event(event_id):
    user_id, role = authorize(*READ_ROLES, ROLE_MEMBER)
    event = lookup.redemption_event(event_id)
    require_member_owns(user_id, role, event["member_id"])
    return ok(serialize.redemption_event(event))


@bp.route("/redemption-events/<event_id>/allocations", methods=["GET"])
def list_event_allocations(event_id):
    authorize(*READ_ROLES)
    event = lookup.redemption_event(event_id)
    rows = lookup.filtered(event_allocation_rows(event["id"]), "entry_type")
    return paginate(db.allocation_order(rows), serialize.allocation)


@bp.route("/redemption-events/<event_id>/allocate", methods=["POST"])
def allocate_redemption_event(event_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    event = lookup.redemption_event(event_id)
    period = lookup.period(event["period_id"])
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    member = lookup.member(event["member_id"])
    program = lookup.program(member["program_id"])
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409)
    if event["state"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if calc.member_point_balance(member["id"]) < event["points_requested"]:
        raise ApiError("ERR_INSUFFICIENT_POINT_BALANCE", 409)
    candidates = db.issuance_order([
        lot for lot in db.member_lots(member["id"])
        if calc.is_outstanding(lot) and lot["points_remaining"] > 0
    ])
    remaining_need = event["points_requested"]
    seq = 0
    provisional_total = 0
    for lot in candidates:
        if remaining_need <= 0:
            break
        take = min(remaining_need, lot["points_remaining"])
        line_gross = rhu(take * lot["ssp_millicents_per_point_at_issue"], 1000)
        provisional = line_gross - rhu(
            line_gross * lot["breakage_rate_bp_at_issue"], 10000
        )
        seq += 1
        db.new_allocation({
            "redemption_event_id": event["id"],
            "point_lot_id": lot["id"],
            "entry_type": "ALLOCATION",
            "allocation_seq": seq,
            "points_allocated": take,
            "provisional_release_cents": provisional,
            "final_release_cents": None,
            "line_gross_ssp_cents": line_gross,
        })
        lot["points_remaining"] = lot["points_remaining"] - take
        lot["lifecycle_state"] = (
            "FULLY_REDEEMED" if lot["points_remaining"] == 0 else "PARTIALLY_REDEEMED"
        )
        db.touch(lot)
        provisional_total += provisional
        remaining_need -= take
    agreement = None
    if event["partner_agreement_id"]:
        agreement = db.store.partner_agreements.get(event["partner_agreement_id"])
    if agreement is not None:
        partner_cost = rhu(
            event["points_requested"]
            * agreement["redemption_rate_millicents_per_point"], 1000
        )
    else:
        partner_cost = 0
    event["provisional_release_cents"] = provisional_total
    event["partner_cost_cents"] = partner_cost
    event["allocated_at"] = clock.now()
    event["state"] = "ALLOCATED"
    period["redemption_recognized_cents"] = (
        period["redemption_recognized_cents"] + provisional_total
    )
    if agreement is not None:
        db.touch(agreement)
    db.touch(event)
    return ok(serialize.redemption_event(event))


@bp.route("/redemption-events/<event_id>/fulfill", methods=["POST"])
def fulfill_redemption_event(event_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    event = lookup.redemption_event(event_id)
    period = lookup.period(event["period_id"])
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    if event["state"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if calc.approved_estimate_for_period(period["id"]) is None:
        raise ApiError("ERR_ESTIMATE_NOT_APPROVED", 409)
    member = lookup.member(event["member_id"])
    program = lookup.program(member["program_id"])
    rate = program["current_breakage_rate_bp"]
    final_total = 0
    for row in event_allocation_rows(event["id"], "ALLOCATION"):
        line_gross = row["line_gross_ssp_cents"]
        final = line_gross - rhu(line_gross * rate, 10000)
        row["final_release_cents"] = final
        final_total += final
    delta = final_total - event["provisional_release_cents"]
    event["final_release_cents"] = final_total
    event["remeasurement_delta_cents"] = delta
    event["state"] = "FULFILLED"
    period["remeasurement_delta_cents"] = period["remeasurement_delta_cents"] + delta
    db.touch(event)
    return ok(serialize.redemption_event(event))


@bp.route("/redemption-events/<event_id>/reverse", methods=["POST"])
def reverse_redemption_event(event_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    body = json_body()
    reversal_reason = field_string(body, "reversal_reason", max_length=500)
    event = lookup.redemption_event(event_id)
    period = lookup.period(event["period_id"])
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    if event["state"] not in ("ALLOCATED", "FULFILLED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    was_fulfilled = event["state"] == "FULFILLED"
    for row in event_allocation_rows(event["id"], "ALLOCATION"):
        final = row["final_release_cents"]
        db.new_allocation({
            "redemption_event_id": event["id"],
            "point_lot_id": row["point_lot_id"],
            "entry_type": "REVERSAL",
            "allocation_seq": row["allocation_seq"],
            "points_allocated": -row["points_allocated"],
            "provisional_release_cents": -row["provisional_release_cents"],
            "final_release_cents": None if final is None else -final,
            "line_gross_ssp_cents": -row["line_gross_ssp_cents"],
        })
        lot = db.store.point_lots.get(row["point_lot_id"])
        if lot is None:
            continue
        lot["points_remaining"] = lot["points_remaining"] + row["points_allocated"]
        lot["lifecycle_state"] = (
            "OUTSTANDING" if lot["points_remaining"] >= lot["points_issued"]
            else "PARTIALLY_REDEEMED"
        )
        db.touch(lot)
    period["redemption_recognized_cents"] = (
        period["redemption_recognized_cents"] - event["provisional_release_cents"]
    )
    if was_fulfilled:
        period["remeasurement_delta_cents"] = (
            period["remeasurement_delta_cents"] - event["remeasurement_delta_cents"]
        )
    event["reversal_reason"] = reversal_reason
    event["state"] = "REVERSED"
    db.touch(event)
    return ok(serialize.redemption_event(event))
