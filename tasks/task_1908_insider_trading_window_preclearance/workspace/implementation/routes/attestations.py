"""Attestation endpoints: assign, complete."""
from flask import Blueprint, request

from db import STORE
from errors import err, ERR_INVALID_STATE
from middleware import require_roles, insider_owns
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created, get_or_404,
                           apply_flags, ATTESTATION_KINDS)
from util import Body, fmt_ts

bp = Blueprint("attestations", __name__)

READ_ROLES = ("Insider", "ComplianceOfficer", "LegalAdmin")


@bp.post("/attestations")
def create_attestation():
    require_roles("LegalAdmin")
    body = Body()
    person_id = body.get_str("covered_person_id")
    kind = body.get_enum("kind", ATTESTATION_KINDS)
    period_year = body.get_int("period_year")
    due = body.get_dt("due_date")
    if person_id is not None:
        get_or_404("covered_persons", person_id, "covered person")
    body.flush()
    a = new_entity()
    a.update({
        "covered_person_id": person_id,
        "kind": kind,
        "period_year": period_year,
        "due_date": fmt_ts(due),
        "status": "ASSIGNED",
        "completed_at": None,
        "_due_dt": due,
        "_completed_dt": None,
    })
    STORE.attestations[a["id"]] = a
    return success(serialize(a), 201)


@bp.get("/attestations/<aid>")
def get_attestation(aid):
    require_roles(*READ_ROLES)
    a = get_or_404("attestations", aid, "attestation")
    insider_owns(a["covered_person_id"])
    return success(serialize(a))


@bp.get("/attestations")
def list_attestations():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.attestations.values())
    person_id = request.args.get("covered_person_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if person_id is not None:
        items = [a for a in items if a["covered_person_id"] == person_id]
    if kind is not None:
        items = [a for a in items if a["kind"] == kind]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate([serialize(a) for a in items])


@bp.post("/attestations/<aid>/complete")
def complete_attestation(aid):
    require_roles("Insider")
    a = get_or_404("attestations", aid, "attestation")
    insider_owns(a["covered_person_id"])
    if a["status"] not in ("ASSIGNED", "OVERDUE"):
        raise err(ERR_INVALID_STATE, "only an ASSIGNED or OVERDUE attestation can be completed")
    now = STORE.clock
    a["status"] = "COMPLETED"
    a["completed_at"] = fmt_ts(now)
    a["_completed_dt"] = now
    touch(a)
    # Completion recomputes the person's currency flags and increments the
    # person's version (PRD 2.5 / 3.1).
    person = STORE.covered_persons.get(a["covered_person_id"])
    if person is not None:
        apply_flags(person, force_touch=True)
    return success(serialize(a))
