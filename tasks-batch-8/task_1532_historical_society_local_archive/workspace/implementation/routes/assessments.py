"""ConservationAssessment routes (PRD §3.4)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.calc import conservation_score
from util import get_json_body, as_int, as_enum, paginate, parse_pagination, public_view

bp = Blueprint("assessments", __name__)

CONDITION_GRADES = {"EXCELLENT", "GOOD", "FAIR", "POOR", "FRAGILE"}
OPEN_REQUEST_STATES = ("SUBMITTED", "IN_REVIEW", "APPROVED")


def serialize_assessment(a: dict) -> dict:
    return public_view(a)


def _get_assessment(aid: str) -> dict:
    a = db.assessments.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"ConservationAssessment not found: {aid}")
    return a


def _open_request_count(item_id: str) -> int:
    return sum(
        1 for r in db.requests.values()
        if r["status"] in OPEN_REQUEST_STATES and item_id in r["item_ids"]
    )


@bp.route("/items/<item_id>/conservation-assessments", methods=["POST"])
@require_roles("Archivist")
def create_assessment(item_id: str, _user_id: str, _role: str):
    body = get_json_body()
    expected_item_version = as_int(body, "expected_item_version", required=True)
    condition_grade_observed = as_enum(body, "condition_grade_observed", CONDITION_GRADES, required=True)
    urgency_score = as_int(body, "urgency_score", required=True, minimum=0, maximum=100)
    treatment_estimate_hours = as_int(body, "treatment_estimate_hours", required=True, minimum=1)

    item = db.items.get(item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, f"Item not found: {item_id}")

    # priority 5: item state gate (blocked while IN_TREATMENT)
    if item["status"] not in ("AVAILABLE", "FLAGGED_CONSERVATION"):
        raise_err(ERR_INVALID_STATE, "Assessment creation requires the item to be AVAILABLE or FLAGGED_CONSERVATION")

    # priority 6: OCC on Item.version
    if expected_item_version != item["version"]:
        raise_err(ERR_STALE_VERSION, "expected_item_version does not match the item's current version")

    snapshot = _open_request_count(item_id)
    preliminary = conservation_score(
        urgency_score, condition_grade_observed, snapshot,
        item["appraised_value_cents"], confirmed=False,
    )

    # supersede the item's prior DRAFT/APPROVED assessments
    for a in db.assessments.values():
        if a["item_id"] == item_id and a["status"] in ("DRAFT", "APPROVED"):
            a["status"] = "SUPERSEDED"
            db.touch(a)

    assessment = {
        **db.make_common_fields(),
        "item_id": item_id,
        "condition_grade_observed": condition_grade_observed,
        "urgency_score": urgency_score,
        "treatment_estimate_hours": treatment_estimate_hours,
        "open_request_count_snapshot": snapshot,
        "preliminary_priority_score": preliminary,
        "confirmed_priority_score": None,
        "status": "DRAFT",
    }
    db.assessments[assessment["id"]] = assessment

    # item mutation: version +1; current_assessment_id moves to the new record.
    # Pinned: a superseded APPROVED assessment's confirmed score STAYS on the
    # item until the newer assessment is itself approved.
    item["current_assessment_id"] = assessment["id"]
    db.touch(item)
    return success_object(serialize_assessment(assessment), 201)


@bp.route("/items/<item_id>/conservation-assessments", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_assessments(item_id: str, _user_id: str, _role: str):
    parse_pagination()  # priority 3 precedes path-id existence (priority 4)
    if item_id not in db.items:
        raise_err(ERR_NOT_FOUND, f"Item not found: {item_id}")
    rows = [a for a in db.assessments.values() if a["item_id"] == item_id]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_assessment(a) for a in page], limit, offset, total)


@bp.route("/conservation-assessments/<aid>/approve", methods=["POST"])
@require_roles("Archivist")
def approve_assessment(aid: str, _user_id: str, _role: str):
    a = _get_assessment(aid)
    if a["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT assessment may be approved")

    item = db.items.get(a["item_id"])
    if item is None:
        raise_err(ERR_NOT_FOUND, f"Item not found: {a['item_id']}")

    confirmed = conservation_score(
        a["urgency_score"], a["condition_grade_observed"],
        a["open_request_count_snapshot"], item["appraised_value_cents"],
        confirmed=True,
    )
    a["confirmed_priority_score"] = confirmed
    a["status"] = "APPROVED"
    db.touch(a)

    item["conservation_priority_score"] = confirmed
    item["current_assessment_id"] = a["id"]
    db.touch(item)
    return success_object(serialize_assessment(a))


@bp.route("/conservation-assessments/<aid>/begin-treatment", methods=["POST"])
@require_roles("Archivist")
def begin_treatment(aid: str, _user_id: str, _role: str):
    a = _get_assessment(aid)
    if a["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Only an APPROVED assessment may begin treatment")
    item = db.items.get(a["item_id"])
    if item is None:
        raise_err(ERR_NOT_FOUND, f"Item not found: {a['item_id']}")
    if item["status"] != "FLAGGED_CONSERVATION":
        raise_err(ERR_INVALID_STATE, "Treatment requires the item to be FLAGGED_CONSERVATION")

    a["status"] = "IN_TREATMENT"
    db.touch(a)
    item["status"] = "IN_TREATMENT"
    db.touch(item)
    return success_object(serialize_assessment(a))


@bp.route("/conservation-assessments/<aid>/complete-treatment", methods=["POST"])
@require_roles("Archivist")
def complete_treatment(aid: str, _user_id: str, _role: str):
    body = get_json_body()
    new_condition_grade = as_enum(body, "new_condition_grade", CONDITION_GRADES, required=True)

    a = _get_assessment(aid)
    if a["status"] != "IN_TREATMENT":
        raise_err(ERR_INVALID_STATE, "Only an IN_TREATMENT assessment may be completed")
    item = db.items.get(a["item_id"])
    if item is None:
        raise_err(ERR_NOT_FOUND, f"Item not found: {a['item_id']}")
    if item["status"] != "IN_TREATMENT":
        raise_err(ERR_INVALID_STATE, "Completion requires the item to be IN_TREATMENT")

    a["status"] = "COMPLETED"
    db.touch(a)
    item["status"] = "AVAILABLE"
    item["condition_grade"] = new_condition_grade
    item["conservation_priority_score"] = None
    item["current_assessment_id"] = None
    db.touch(item)
    return success_object(serialize_assessment(a))
