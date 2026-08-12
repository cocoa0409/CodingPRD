"""CollectiveAgreement endpoints."""

from flask import Blueprint, request

import calc
import clock
from db import db
from errors import (
    ERR_EXTENSION_NOT_FORWARD,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_UNION_DECERTIFIED,
    ERR_UNION_TRUSTEED,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, optional_body, page,
    parse_pagination, req_datetime, req_int, req_string, serialize, sort_items, touch,
    recompute_posture,
)
from response import success_list, success_object
from services import supersede_incumbents

bp = Blueprint("agreements", __name__)


def _get_union_or_404(union_id):
    return lookup(db.unions, union_id, "Union")


@bp.post("/labor-relations/agreements")
def create_agreement():
    authenticate(["LRAdmin"])
    body = get_body()
    union_id = req_string(body, "union_id")
    title = req_string(body, "title")
    effective_date = req_datetime(body, "effective_date")
    expiration_date = req_datetime(body, "expiration_date")
    headcount_baseline = req_int(body, "headcount_baseline")
    fte_projected = req_int(body, "fte_projected")
    avg_loaded_wage_cents = req_int(body, "avg_loaded_wage_cents")
    costing_envelope_cents = req_int(body, "costing_envelope_cents")
    deadline_mode = body.get("deadline_mode")
    if deadline_mode is None:
        deadline_mode = "BUSINESS"
    elif deadline_mode not in ("BUSINESS", "CALENDAR"):
        raise_err(ERR_INVALID_REQUEST, "deadline_mode must be BUSINESS or CALENDAR")

    _get_union_or_404(union_id)

    if expiration_date <= effective_date:
        raise_err(ERR_INVALID_REQUEST, "expiration_date must be strictly later than effective_date")

    agreement = new_entity()
    agreement.update({
        "union_id": union_id,
        "title": title,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "headcount_baseline": headcount_baseline,
        "fte_projected": fte_projected,
        "avg_loaded_wage_cents": avg_loaded_wage_cents,
        "costing_envelope_cents": costing_envelope_cents,
        "envelope_committed_cents": 0,
        "deadline_mode": deadline_mode,
        "status": "DRAFT",
        "posture": "NEGOTIATING",
        "extension_count": 0,
    })
    db.agreements[agreement["id"]] = agreement
    return success_object(serialize(agreement), status=201)


@bp.get("/labor-relations/agreements")
def list_agreements():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    union_id = request.args.get("union_id")
    status = request.args.get("status")
    posture = request.args.get("posture")
    items = list(db.agreements.values())
    if union_id is not None:
        items = [a for a in items if a["union_id"] == union_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if posture is not None:
        items = [a for a in items if a["posture"] == posture]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(a) for a in slice_], limit, offset, total)


@bp.get("/labor-relations/agreements/<agreement_id>")
def get_agreement(agreement_id):
    authenticate(ALL_ROLES)
    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    return success_object(serialize(agreement))


@bp.post("/labor-relations/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate(["LRAdmin"])
    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    optional_body()  # body optional; must be an object when present

    if agreement["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT agreement can be activated")
    if agreement["expiration_date"] <= clock.now():
        raise_err(ERR_INVALID_STATE, "expiration_date is not in the future")
    union = _get_union_or_404(agreement["union_id"])
    if union["status"] == "TRUSTEED":
        raise_err(ERR_UNION_TRUSTEED, "Union is TRUSTEED")
    if union["status"] == "DECERTIFIED":
        raise_err(ERR_UNION_DECERTIFIED, "Union is DECERTIFIED")

    agreement["status"] = "ACTIVE"
    recompute_posture(agreement)
    touch(agreement)
    supersede_incumbents(agreement)
    return success_object(serialize(agreement))


@bp.post("/labor-relations/agreements/<agreement_id>/extend")
def extend_agreement(agreement_id):
    authenticate(["ChiefNegotiator"])
    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    body = get_body()
    new_expiration_date = req_datetime(body, "new_expiration_date")
    expected_version = req_int(body, "expected_agreement_version")

    if agreement["status"] not in ("ACTIVE", "EXPIRED", "EXTENDED"):
        raise_err(ERR_INVALID_STATE, "Only ACTIVE, EXPIRED, or EXTENDED agreements can be extended")
    if expected_version != agreement["version"]:
        raise_err(ERR_STALE_AGREEMENT_VERSION, "expected_agreement_version does not match the agreement version")
    if new_expiration_date <= agreement["expiration_date"]:
        raise_err(ERR_EXTENSION_NOT_FORWARD, "new_expiration_date must be strictly later than the current expiration_date")

    agreement["expiration_date"] = new_expiration_date
    agreement["status"] = "EXTENDED"
    agreement["extension_count"] += 1
    recompute_posture(agreement)
    touch(agreement)

    # Cascade: recompute due dates of non-terminal tasks; newly past tasks become MISSED
    now = clock.now()
    for task in db.tasks.values():
        if task["agreement_id"] == agreement["id"] and task["status"] in ("PENDING", "IN_PROGRESS"):
            task["due_date"] = calc.task_due_date(new_expiration_date, task["due_offset_days"])
            if task["due_date"] < now:
                task["status"] = "MISSED"
            touch(task)

    return success_object(serialize(agreement))


@bp.post("/labor-relations/agreements/<agreement_id>/archive")
def archive_agreement(agreement_id):
    authenticate(["LRAdmin"])
    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    optional_body()

    if agreement["status"] not in ("EXPIRED", "REPLACED"):
        raise_err(ERR_INVALID_STATE, "Only EXPIRED or REPLACED agreements can be archived")
    agreement["status"] = "ARCHIVED"
    agreement["posture"] = "CLOSED"
    touch(agreement)
    return success_object(serialize(agreement))
