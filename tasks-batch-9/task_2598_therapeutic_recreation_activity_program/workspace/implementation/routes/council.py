"""Resident council input and the adoption cascade (PRD 3.9)."""
from flask import Blueprint

import serializers
from db import store
from errors import ApiError
from helpers import ctx, load, new_entity, paginate, resolve_fk
from middleware import (
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_COUNCIL_REPRESENTATIVE,
    ROLE_RECREATION_THERAPIST,
    authorize,
    deny,
    filter_arg,
    pagination,
)
from response import list_response, object_response
from services import constants as C
from services import plans as plan_svc
from validation import read_body, validate

bp = Blueprint("council", __name__)

READ_ROLES = (
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_RECREATION_THERAPIST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_COUNCIL_REPRESENTATIVE,
)

CREATE_SPEC = {
    "resident_id": {"type": "id", "required": True},
    "requested_domain": {"type": "enum", "values": C.DOMAINS, "required": True},
    "requested_program_id": {"type": "id"},
    "vote_count": {"type": "int", "min": 0, "max": 40, "required": True},
    "note": {"type": "text"},
}

REVIEW_SPEC = {
    "decision": {
        "type": "enum",
        "values": ["ADOPTED", "DECLINED", "DEFERRED"],
        "required": True,
    },
    "decision_note": {"type": "text"},
}

REVIEW_SOURCES = {
    "ADOPTED": ("SUBMITTED", "DEFERRED"),
    "DECLINED": ("SUBMITTED", "DEFERRED"),
    "DEFERRED": ("SUBMITTED",),
}


@bp.post("/council-requests")
def create_request():
    actor = authorize(ROLE_COUNCIL_REPRESENTATIVE)
    body = read_body()
    # Rank 2: the CouncilRepresentative role is backed by a Resident row, so the
    # named resident must be the caller themselves. A mismatch is a 403.
    claimed = body.get("resident_id")
    if isinstance(claimed, str) and claimed != actor.user_id:
        deny()
    resident = resolve_fk(body, "resident_id", "resident")
    program = resolve_fk(body, "requested_program_id", "program")
    values = validate(body, CREATE_SPEC)
    if resident["id"] != actor.user_id:
        deny()

    request_row = new_entity(
        {
            "resident_id": resident["id"],
            "requested_domain": values["requested_domain"],
            "requested_program_id": program["id"] if program is not None else None,
            "vote_count": values["vote_count"],
            "note": values["note"],
            "status": "SUBMITTED",
            "decision_note": None,
            "reviewed_by_user_id": None,
        }
    )
    store.council_requests[request_row["id"]] = request_row
    return object_response(serializers.council_request(request_row), 201)


def _adoption_cascade(request_row, context):
    domain = request_row["requested_domain"]
    program_id = request_row.get("requested_program_id")
    if program_id:
        program = store.programs.get(program_id)
        if program is not None:
            program["council_preference_weight"] = (
                program.get("council_preference_weight", 0) + 1
            )
            context.bump(program)
    for plan in list(store.plans.values()):
        if plan["status"] != "ACTIVE":
            continue
        resident = store.residents.get(plan["resident_id"])
        if resident is None:
            continue
        if domain not in (resident.get("interest_domains") or []):
            continue
        targets = plan.get("domain_frequency_targets") or {}
        if targets.get(domain) != 0:
            continue
        plan["status"] = "UNDER_REVISION"
        plan["review_reason"] = "COUNCIL_INPUT"
        context.bump(plan)
        plan_svc.raise_gate(resident, context)
        context.bump(resident)


@bp.post("/council-requests/<request_id>/review")
def review_request(request_id):
    actor = authorize(ROLE_ACTIVITY_DIRECTOR)
    body = read_body()
    request_row = load("council_request", request_id)
    values = validate(body, REVIEW_SPEC)
    decision = values["decision"]

    # Rank 17: the disposition must be declared for the current status.
    if request_row["status"] not in REVIEW_SOURCES[decision]:
        raise ApiError("ERR_COUNCIL_REQUEST_INVALID_STATE")
    # Rank 44: adoption alone carries the quorum requirement.
    if decision == "ADOPTED" and request_row["vote_count"] < C.COUNCIL_QUORUM:
        raise ApiError("ERR_COUNCIL_QUORUM_NOT_MET")

    context = ctx()
    request_row["status"] = decision
    request_row["decision_note"] = values["decision_note"]
    request_row["reviewed_by_user_id"] = actor.user_id
    context.bump(request_row)
    if decision == "ADOPTED":
        _adoption_cascade(request_row, context)
    return object_response(serializers.council_request(request_row), 200)


@bp.get("/council-requests/<request_id>")
def get_request(request_id):
    actor = authorize(*READ_ROLES)
    request_row = load("council_request", request_id)
    if (
        actor.role == ROLE_COUNCIL_REPRESENTATIVE
        and request_row["resident_id"] != actor.user_id
    ):
        deny()
    return object_response(serializers.council_request(request_row), 200)


@bp.get("/council-requests")
def list_requests():
    actor = authorize(*READ_ROLES)
    limit, offset = pagination()
    resident_id = filter_arg("resident_id")
    program_id = filter_arg("requested_program_id")
    domain = filter_arg("requested_domain")
    status = filter_arg("status")
    rows = list(store.council_requests.values())
    if actor.role == ROLE_COUNCIL_REPRESENTATIVE:
        rows = [r for r in rows if r["resident_id"] == actor.user_id]
    if resident_id:
        rows = [r for r in rows if r["resident_id"] == resident_id]
    if program_id:
        rows = [r for r in rows if r["requested_program_id"] == program_id]
    if domain:
        rows = [r for r in rows if r["requested_domain"] == domain]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.council_request(r) for r in page], limit, offset, total
    )
