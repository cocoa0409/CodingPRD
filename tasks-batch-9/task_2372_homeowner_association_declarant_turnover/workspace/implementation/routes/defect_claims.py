"""Construction defect claims: opening, reads and the action dispatcher."""
from flask import Blueprint

import auth
import calc
import cascades
import clock
import constants
import response
import util
import validation as v
from db import db, new_record, ordered, serialize, serialize_list, touch
from errors import ApiError
from routes import common

bp = Blueprint("defect_claims", __name__)


@bp.get("/hoa/defect-claims/<claim_id>")
def read_claim(claim_id):
    auth.require_roles(*constants.ALL_ROLES)
    claim = common.defect_claim_or_404(claim_id, scoped=True)
    return response.object_response(serialize(claim))


@bp.get("/hoa/defect-claims")
def list_claims():
    auth.require_roles(*constants.ALL_ROLES)
    records = ordered(list(db.defect_claims.values()))
    for field in ("association_id", "component_id", "status"):
        value = v.query_filter(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.post("/hoa/defect-claims")
def create_claim():
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")
    component = common.body_component_or_404(
        v.get_fk(body, "component_id"), association["id"]
    )
    if component is None:
        raise ApiError("ERR_INVALID_REQUEST", "component_id is required.")

    defect_summary = v.get_str(body, "defect_summary", min_len=1, max_len=400)
    repair_cost = v.get_int(body, "repair_cost_estimate_cents", minimum=1)
    diminution = v.get_int(body, "diminution_value_cents", minimum=1)

    cascades.require_not_settled_locked(association["id"])

    claim = new_record({
        "association_id": association["id"],
        "component_id": component["id"],
        "defect_summary": defect_summary,
        "repair_cost_estimate_cents": repair_cost,
        "diminution_value_cents": diminution,
        "repose_deadline": calc.repose_deadline(component, association),
        "status": "INVESTIGATING",
        "negotiation_round": 0,
        "valuation_basis": None,
        "reserve_subtotal_cents": 0,
        "litigation_admin_fee_cents": 0,
        "reserved_amount_cents": 0,
        "settlement_amount_cents": None,
    })
    db.defect_claims[claim["id"]] = claim
    return response.object_response(serialize(claim), 201)


@bp.post("/hoa/defect-claims/<claim_id>/actions")
def claim_action(claim_id):
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE, constants.ROLE_DECLARANT)
    body = v.body()
    auth.require_discriminator_role(body.get("action"), constants.CLAIM_ACTION_ROLES)

    claim = common.defect_claim_or_404(claim_id, scoped=True)
    action = v.get_enum(body, "action", constants.CLAIM_ACTIONS)
    valuation_basis = None
    settlement_amount = None
    if action == "RESERVE":
        valuation_basis = v.get_enum(
            body, "valuation_basis", constants.VALUATION_BASES
        )
    if action == "ACCEPT":
        settlement_amount = v.get_int(body, "settlement_amount_cents", minimum=0)

    cascades.require_not_settled_locked(claim["association_id"])

    association = db.associations[claim["association_id"]]

    if action == "NOTICE":
        if claim["status"] != "INVESTIGATING":
            raise ApiError("ERR_CLAIM_STATE_INVALID")
        component = db.components.get(claim["component_id"])
        if component is None or component["conveyance_status"] != "CONVEYED":
            raise ApiError("ERR_COMPONENT_NOT_CONVEYED")
        deadline = util.parse_dt(claim["repose_deadline"]) if claim["repose_deadline"] else None
        if deadline is None or clock.now() > deadline:
            raise ApiError("ERR_REPOSE_PERIOD_EXPIRED")
        claim["status"] = "NOTICED"

    elif action == "REJECT":
        if claim["status"] != "NOTICED":
            raise ApiError("ERR_CLAIM_STATE_INVALID")
        claim["status"] = "REJECTED_BY_DEVELOPER"

    elif action == "REINVESTIGATE":
        if claim["status"] != "REJECTED_BY_DEVELOPER":
            raise ApiError("ERR_CLAIM_STATE_INVALID")
        if claim["negotiation_round"] >= constants.MAX_NEGOTIATION_ROUNDS:
            raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")
        claim["status"] = "INVESTIGATING"
        claim["negotiation_round"] += 1

    elif action == "RESERVE":
        if claim["status"] not in ("NOTICED", "REJECTED_BY_DEVELOPER"):
            raise ApiError("ERR_CLAIM_STATE_INVALID")
        subtotal, fee, total = calc.claim_reserve_amounts(claim, valuation_basis)
        if total > association["reserve_claim_available_cents"]:
            raise ApiError("ERR_CLAIM_RESERVE_INSUFFICIENT")
        claim["status"] = "RESERVED"
        claim["valuation_basis"] = valuation_basis
        claim["reserve_subtotal_cents"] = subtotal
        claim["litigation_admin_fee_cents"] = fee
        claim["reserved_amount_cents"] = total
        touch(claim)
        calc.apply_claim_pool(association)
        touch(association)
        return response.object_response(serialize(claim))

    elif action == "ACCEPT":
        if claim["status"] not in ("NOTICED", "RESERVED"):
            raise ApiError("ERR_CLAIM_STATE_INVALID")
        released = claim["status"] == "RESERVED"
        claim["status"] = "SETTLED"
        claim["settlement_amount_cents"] = settlement_amount
        if released:
            claim["reserved_amount_cents"] = 0
            touch(claim)
            calc.apply_claim_pool(association)
            touch(association)
            return response.object_response(serialize(claim))

    else:  # WITHDRAW
        if claim["status"] not in (
            "INVESTIGATING", "NOTICED", "REJECTED_BY_DEVELOPER", "RESERVED",
        ):
            raise ApiError("ERR_CLAIM_STATE_INVALID")
        released = claim["status"] == "RESERVED"
        claim["status"] = "WITHDRAWN"
        if released:
            claim["reserved_amount_cents"] = 0
            touch(claim)
            calc.apply_claim_pool(association)
            touch(association)
            return response.object_response(serialize(claim))

    touch(claim)
    return response.object_response(serialize(claim))
