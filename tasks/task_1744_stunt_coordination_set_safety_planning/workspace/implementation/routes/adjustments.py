"""PayAdjustment: hazard-bump negotiation (create, counter, agree, withdraw)."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    get_performer,
    get_adjustment,
    gate_posture_setup_or_active,
    performer_effective_status,
    bump_in_bounds,
    budget_authority_ok,
    provisional_estimate_cents,
    final_amount_cents_of,
    serialize_adjustment,
    stamp_new,
    stamp_mutable,
    touch,
    ADJUSTMENT_TYPES,
    MAX_NEGOTIATION_ROUNDS,
    default_sort_key,
)
from errors import (
    err,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEQUENCE_INVALID_STATE,
    ERR_PERFORMER_NOT_QUALIFIED,
    ERR_ADJUSTMENT_INVALID_STATE,
    ERR_NOT_YOUR_TURN,
    ERR_NEGOTIATION_EXHAUSTED,
    ERR_NEGOTIATION_ALREADY_OPEN,
    ERR_CROSS_PRODUCTION_REFERENCE,
    ERR_BUMP_OUT_OF_RANGE,
    ERR_BUDGET_EXCEEDED,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_pos_int,
    v_number,
    v_enum,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("adjustments", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
NEGOTIATORS = ["Performer", "StuntCoordinator"]
OPEN_STATES = ("PROPOSED", "COUNTERED")
TERMINAL_SEQUENCE_STATES = ("EXECUTED", "REVIEWED", "CANCELLED")


def _caller_side(role):
    return "PERFORMER" if role == "Performer" else "COORDINATOR"


def _ownership_check(adj, role, user_id):
    if role == "Performer" and adj["performer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "A Performer may only act on their own adjustments", 403)


@bp.post("/api/pay-adjustments")
def create_adjustment():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "sequence_id": (v_string, True, None),
            "performer_id": (v_string, True, None),
            "adjustment_type": (v_enum(ADJUSTMENT_TYPES), True, None),
            "base_amount_cents": (v_pos_int, True, None),
            "requested_pct": (v_number, True, None),
        },
    )
    user_id, role = auth()
    require_role(role, NEGOTIATORS)
    # Performer-role ownership (tier 2)
    if role == "Performer" and data["performer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER,
                  "A Performer may only negotiate their own adjustments", 403)

    get_production(data["production_id"])
    seq = get_sequence(data["sequence_id"])
    performer = get_performer(data["performer_id"])

    prod = get_production(seq["production_id"])
    gate_posture_setup_or_active(prod)

    # entity state (tier 6): performer qualification, then sequence state
    if performer_effective_status(performer) != "QUALIFIED":
        raise err(ERR_PERFORMER_NOT_QUALIFIED,
                  "The performer must be QUALIFIED to open a negotiation", 409)
    if seq["status"] in TERMINAL_SEQUENCE_STATES:
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "The sequence no longer accepts new negotiations", 409)

    # one open negotiation per (sequence, performer) pair (tier 10)
    for other in store.adjustments.values():
        if (
            other["sequence_id"] == seq["id"]
            and other["performer_id"] == performer["id"]
            and other["status"] in OPEN_STATES
        ):
            raise err(ERR_NEGOTIATION_ALREADY_OPEN,
                      "An open negotiation already exists for this sequence and "
                      "performer", 409)

    # cross-production integrity (tier 11)
    if seq["production_id"] != data["production_id"] or \
            performer["production_id"] != data["production_id"]:
        raise err(ERR_CROSS_PRODUCTION_REFERENCE,
                  "All references must belong to the same production", 422)

    # hazard-bump bounds (tier 13)
    if not bump_in_bounds(data["base_amount_cents"], data["requested_pct"],
                          performer, seq):
        raise err(ERR_BUMP_OUT_OF_RANGE,
                  "The requested bump falls outside the permitted floor/cap", 422)

    side = _caller_side(role)
    adj = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": data["production_id"],
                "sequence_id": seq["id"],
                "performer_id": performer["id"],
                "adjustment_type": data["adjustment_type"],
                "base_amount_cents": data["base_amount_cents"],
                "requested_pct": data["requested_pct"],
                "current_pct": data["requested_pct"],
                "proposer_by": side,
                "last_offer_by": side,
                "round_count": 0,
                "status": "PROPOSED",
                "provisional_estimate_cents": provisional_estimate_cents(
                    data["base_amount_cents"], data["requested_pct"]
                ),
                "final_amount_cents": None,
                "payable_amount_cents": None,
            }
        )
    )
    store.adjustments[adj["id"]] = adj
    return ok(serialize_adjustment(adj), 201)


@bp.get("/api/pay-adjustments")
def list_adjustments():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    sequence_id = request.args.get("sequence_id")
    performer_id = request.args.get("performer_id")
    status = request.args.get("status")
    items = []
    for a in store.adjustments.values():
        if production_id is not None and a["production_id"] != production_id:
            continue
        if sequence_id is not None and a["sequence_id"] != sequence_id:
            continue
        if performer_id is not None and a["performer_id"] != performer_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(a)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_adjustment(a) for a in page], total, limit, offset)


@bp.get("/api/pay-adjustments/<aid>")
def get_one_adjustment(aid):
    _, role = auth()
    require_role(role, READ_ROLES)
    adj = get_adjustment(aid)
    return ok(serialize_adjustment(adj), 200)


@bp.post("/api/pay-adjustments/<aid>/counter")
def counter_adjustment(aid):
    body = get_body()
    data = validate_payload(body, {"counter_pct": (v_number, True, None)})
    user_id, role = auth()
    require_role(role, NEGOTIATORS)
    adj = get_adjustment(aid)
    _ownership_check(adj, role, user_id)
    side = _caller_side(role)

    prod = get_production(adj["production_id"])
    gate_posture_setup_or_active(prod)

    if adj["status"] not in OPEN_STATES:
        raise err(ERR_ADJUSTMENT_INVALID_STATE,
                  "counter requires status PROPOSED or COUNTERED", 409)
    if side == adj["last_offer_by"]:
        raise err(ERR_NOT_YOUR_TURN,
                  "The side that made the last offer may not counter it", 409)
    if adj["round_count"] >= MAX_NEGOTIATION_ROUNDS:
        # the failed counter attempt itself exhausts the negotiation
        adj["status"] = "EXPIRED"
        touch(adj)
        raise err(ERR_NEGOTIATION_EXHAUSTED,
                  "The negotiation has reached the six-round cap", 409)

    seq = get_sequence(adj["sequence_id"])
    performer = get_performer(adj["performer_id"])
    if not bump_in_bounds(adj["base_amount_cents"], data["counter_pct"],
                          performer, seq):
        raise err(ERR_BUMP_OUT_OF_RANGE,
                  "The countered bump falls outside the permitted floor/cap", 422)

    adj["current_pct"] = data["counter_pct"]
    adj["round_count"] += 1
    adj["last_offer_by"] = side
    adj["status"] = "COUNTERED"
    touch(adj)
    return ok(serialize_adjustment(adj), 200)


@bp.post("/api/pay-adjustments/<aid>/agree")
def agree_adjustment(aid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, NEGOTIATORS)
    adj = get_adjustment(aid)
    _ownership_check(adj, role, user_id)
    side = _caller_side(role)

    prod = get_production(adj["production_id"])
    gate_posture_setup_or_active(prod)

    if adj["status"] not in OPEN_STATES:
        raise err(ERR_ADJUSTMENT_INVALID_STATE,
                  "agree requires status PROPOSED or COUNTERED", 409)
    if side == adj["last_offer_by"]:
        raise err(ERR_NOT_YOUR_TURN,
                  "The side that made the last offer may not accept it", 409)
    performer = get_performer(adj["performer_id"])
    if performer_effective_status(performer) != "QUALIFIED":
        raise err(ERR_PERFORMER_NOT_QUALIFIED,
                  "The performer must be QUALIFIED at agreement", 409)
    seq = get_sequence(adj["sequence_id"])
    if seq["status"] in TERMINAL_SEQUENCE_STATES:
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "The sequence no longer accepts agreements", 409)

    # budget authority check (tier 14)
    if not budget_authority_ok(prod, adj):
        raise err(ERR_BUDGET_EXCEEDED,
                  "The agreed line would exceed the available budget after the "
                  "reserve", 402)

    final = final_amount_cents_of(adj["base_amount_cents"], adj["current_pct"])
    adj["final_amount_cents"] = final
    adj["payable_amount_cents"] = final  # zero completed takes so far
    adj["status"] = "AGREED"
    touch(adj)
    prod["committed_pay_cents"] += final  # invariant I1
    touch(prod)
    return ok(serialize_adjustment(adj), 200)


@bp.post("/api/pay-adjustments/<aid>/withdraw")
def withdraw_adjustment(aid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, NEGOTIATORS)
    adj = get_adjustment(aid)
    _ownership_check(adj, role, user_id)
    side = _caller_side(role)

    prod = get_production(adj["production_id"])
    gate_posture_setup_or_active(prod)

    if adj["status"] not in OPEN_STATES:
        raise err(ERR_ADJUSTMENT_INVALID_STATE,
                  "withdraw requires status PROPOSED or COUNTERED", 409)
    if side != adj["proposer_by"]:
        raise err(ERR_NOT_YOUR_TURN,
                  "Only the proposer side may withdraw the negotiation", 409)
    adj["status"] = "WITHDRAWN"
    touch(adj)
    return ok(serialize_adjustment(adj), 200)
