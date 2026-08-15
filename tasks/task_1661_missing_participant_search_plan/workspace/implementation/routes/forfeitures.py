"""Forfeiture endpoints (PRD section 3.4): the last-resort disposition."""

import db
import gates
import services
from errors import (
    ApiError,
    ERR_FORFEITURE_ALREADY_RECORDED,
    ERR_ZERO_BALANCE_TRANSFER,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import public_forfeiture
from util import (
    body_fk,
    body_json,
    check_shape,
    paginate,
    pagination_params,
    path_entity,
)

bp = make_blueprint("forfeitures")


@bp.post("/forfeitures")
def create_forfeiture():
    user_id, _role = authenticate(["IndependentFiduciary"])
    body = body_json()
    check_shape(body, {
        "participant_id": {"type": "string", "required": True},
        "rationale": {"type": "string", "required": True},
    })
    participant = body_fk(body, "participant_id", "participants", "participant")
    _case, search_case = gates.case_and_missing_gates(participant)
    gates.sod_and_doc_gates(search_case, user_id)
    # Priority 9: no second non-RESTORED forfeiture. (A participant with a
    # RECORDED forfeiture is FORFEITED, so this singularity check runs ahead
    # of the distribution-state gate to report the more specific error.)
    if any(
        f["status"] == "RECORDED"
        for f in services.participant_forfeitures(participant["id"])
    ):
        raise ApiError(
            ERR_FORFEITURE_ALREADY_RECORDED, 409,
            "a RECORDED forfeiture already exists for the participant",
        )
    gates.distribution_gate(participant)
    # Priority 11: the search protocol must be exhausted.
    gates.require_exhausted(search_case)
    # Priority 12: money rules.
    amount = services.net_distributable(participant)
    if amount == 0:
        raise ApiError(
            ERR_ZERO_BALANCE_TRANSFER, 422,
            "a zero balance cannot be forfeited",
        )
    forfeiture = db.new_entity("forfeitures", {
        "participant_id": participant["id"],
        "rationale": body["rationale"],
        "forfeited_amount_cents": amount,
        "status": "RECORDED",
        "restoration_amount_cents": None,
        "restored_at": None,
    })
    participant["distribution_status"] = "FORFEITED"
    db.touch(participant)
    return success_obj(public_forfeiture(forfeiture), 201)


@bp.get("/participants/<participant_id>/forfeitures")
def list_participant_forfeitures(participant_id):
    authenticate(ALL_ROLES)
    participant = path_entity("participants", participant_id, "participant")
    limit, offset = pagination_params()
    items = services.participant_forfeitures(participant["id"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list(
        [public_forfeiture(f) for f in page], limit, offset, total, has_more
    )
