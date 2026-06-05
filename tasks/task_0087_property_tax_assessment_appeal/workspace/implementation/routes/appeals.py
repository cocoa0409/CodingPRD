"""Appeal endpoints: file, accept, negotiation cycle, decisions, withdraw.

Implements PRD §3.6 including the OCC guard (§2.7), segregation of duties
(§2.1), the cyclic UNDER_REVIEW <-> EVIDENCE_REQUESTED loop, and the cascade
that drives the parent assessment back to NOTICED on resolution.
"""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles, get_identity
from response import object_response, array_response
from services.common import (
    get_body, require_fields, lookup, parse_pagination, paginate, is_number,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("appeals", __name__)

OPEN_STATES = {"FILED", "UNDER_REVIEW", "EVIDENCE_REQUESTED"}


def _cascade_value_change(assessment, determined_value):
    """SETTLED/GRANTED branch: lower the value and release the hold."""
    assessment["appealed_value"] = determined_value
    assessment["final_taxable_value"] = determined_value
    assessment["status"] = "NOTICED"
    db.touch(assessment)


def _cascade_no_change(assessment):
    """DENIED/WITHDRAWN branch: release the hold, no value change."""
    # appealed_value stays null; final_taxable_value stays = taxable_value
    assessment["status"] = "NOTICED"
    db.touch(assessment)


@bp.post("/appeals")
def file_appeal():
    require_roles(["Taxpayer"])
    body = get_body()
    require_fields(body, ["assessment_id", "filed_by_owner_id",
                          "requested_taxable_value", "expected_assessment_version"])
    assessment_id = body["assessment_id"]
    filed_by_owner_id = body["filed_by_owner_id"]
    requested = body["requested_taxable_value"]
    expected_version = body["expected_assessment_version"]

    # FK string-ness and the OCC field's integer-ness are needed up front to do
    # existence + the OCC comparison; the requested_taxable_value range check is
    # deferred to the end per §2.8 (request-schema validation is last).
    if not isinstance(assessment_id, str) or not isinstance(filed_by_owner_id, str):
        raise err("ERR_INVALID_REQUEST", "assessment_id/filed_by_owner_id must be strings")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err("ERR_INVALID_REQUEST", "expected_assessment_version must be an integer")

    with db.LOCK:
        # Existence (priority 4): assessment then owner, left-to-right.
        a = lookup(db.assessments, assessment_id)
        lookup(db.owners, filed_by_owner_id)

        # NOTE: PRD §2.1 lists the taxpayer ownership check (ERR_NOT_RESOURCE_OWNER)
        # only for submit-evidence, withdraw, and deferral payments — NOT for
        # filing. So filing does not compare X-User-ID to filed_by_owner_id.

        # OCC (priority 6) — BEFORE any state check.
        if expected_version != a["version"]:
            raise err("ERR_STALE_VERSION", "Assessment version has advanced")

        # State (priority 7): assessment must be NOTICED to admit an appeal.
        if a["status"] != "NOTICED":
            raise err("ERR_INVALID_STATE", "Assessment is not NOTICED")

        # Request-schema validation (priority 20, last).
        if not is_number(requested) or requested < 0:
            raise err("ERR_INVALID_REQUEST", "requested_taxable_value must be >= 0")

        appeal = {
            "assessment_id": assessment_id,
            "filed_by_owner_id": filed_by_owner_id,
            "requested_taxable_value": requested,
            "opinion_of_value": requested,
            "round_no": 1,
            "determined_taxable_value": None,
            "status": "FILED",
        }
        db.init_common(appeal)
        db.appeals[appeal["id"]] = appeal

        # Drive the assessment NOTICED -> UNDER_APPEAL, advancing its version.
        a["status"] = "UNDER_APPEAL"
        db.touch(a)
    return object_response(serialize(appeal), 201)


@bp.get("/appeals")
def list_appeals():
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    limit, offset = parse_pagination()
    assessment_id = request.args.get("assessment_id")
    filed_by_owner_id = request.args.get("filed_by_owner_id")
    items = list(db.appeals.values())
    if assessment_id is not None:
        items = [ap for ap in items if ap["assessment_id"] == assessment_id]
    if filed_by_owner_id is not None:
        items = [ap for ap in items if ap["filed_by_owner_id"] == filed_by_owner_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


@bp.get("/appeals/<appeal_id>")
def get_appeal(appeal_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    return object_response(serialize(lookup(db.appeals, appeal_id)), 200)


@bp.post("/appeals/<appeal_id>/accept")
def accept_appeal(appeal_id):
    user_id, _role = require_roles(["HearingOfficer"])
    with db.LOCK:
        ap = lookup(db.appeals, appeal_id)
        a = db.assessments[ap["assessment_id"]]

        # Segregation of duties (priority 3) is checked before state per §2.8.
        if user_id == a.get("noticed_by_user_id"):
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Hearing officer may not adjudicate an assessment they noticed")

        if ap["status"] != "FILED" or a["status"] != "UNDER_APPEAL":
            raise err("ERR_INVALID_STATE", "Appeal not in a FILED/UNDER_APPEAL state")

        ap["status"] = "UNDER_REVIEW"
        db.touch(ap)
    return object_response(serialize(ap), 200)


@bp.post("/appeals/<appeal_id>/request-evidence")
def request_evidence(appeal_id):
    require_roles(["HearingOfficer"])
    body = get_body()
    require_fields(body, ["counter_value"])
    counter_value = body["counter_value"]
    if not is_number(counter_value) or counter_value < 0:
        raise err("ERR_INVALID_REQUEST", "counter_value must be >= 0")

    with db.LOCK:
        ap = lookup(db.appeals, appeal_id)
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Appeal is not UNDER_REVIEW")
        if ap["round_no"] >= 3:
            raise err("ERR_MAX_ROUNDS_REACHED", "Maximum negotiation rounds reached")
        ap["opinion_of_value"] = counter_value
        ap["status"] = "EVIDENCE_REQUESTED"
        db.touch(ap)
    return object_response(serialize(ap), 200)


@bp.post("/appeals/<appeal_id>/submit-evidence")
def submit_evidence(appeal_id):
    user_id, _role = require_roles(["Taxpayer"])
    with db.LOCK:
        ap = lookup(db.appeals, appeal_id)
        if user_id != ap["filed_by_owner_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the petitioner may submit evidence")
        if ap["status"] != "EVIDENCE_REQUESTED":
            raise err("ERR_INVALID_STATE", "Appeal is not EVIDENCE_REQUESTED")
        ap["round_no"] += 1
        ap["status"] = "UNDER_REVIEW"
        db.touch(ap)
    return object_response(serialize(ap), 200)


@bp.post("/appeals/<appeal_id>/settle")
def settle_appeal(appeal_id):
    require_roles(["HearingOfficer"])
    body = get_body()
    require_fields(body, ["settled_value"])
    settled_value = body["settled_value"]
    if not is_number(settled_value) or settled_value < 0:
        raise err("ERR_INVALID_REQUEST", "settled_value must be >= 0")

    with db.LOCK:
        ap = lookup(db.appeals, appeal_id)
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Appeal is not UNDER_REVIEW")
        a = db.assessments[ap["assessment_id"]]
        low = ap["requested_taxable_value"]
        high = a["taxable_value"]
        if not (low <= settled_value <= high):
            raise err("ERR_SETTLEMENT_OUT_OF_RANGE",
                      "settled_value outside [requested_taxable_value, taxable_value]")
        ap["determined_taxable_value"] = settled_value
        ap["status"] = "SETTLED"
        db.touch(ap)
        _cascade_value_change(a, settled_value)
    return object_response(serialize(ap), 200)


@bp.post("/appeals/<appeal_id>/grant")
def grant_appeal(appeal_id):
    require_roles(["HearingOfficer"])
    with db.LOCK:
        ap = lookup(db.appeals, appeal_id)
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Appeal is not UNDER_REVIEW")
        held = any(h["appeal_id"] == appeal_id and h["status"] == "HELD"
                   for h in db.hearings.values())
        if not held:
            raise err("ERR_NO_HELD_HEARING", "No HELD hearing on this appeal")
        a = db.assessments[ap["assessment_id"]]
        determined = ap["requested_taxable_value"]
        ap["determined_taxable_value"] = determined
        ap["status"] = "GRANTED"
        db.touch(ap)
        _cascade_value_change(a, determined)
    return object_response(serialize(ap), 200)


@bp.post("/appeals/<appeal_id>/deny")
def deny_appeal(appeal_id):
    require_roles(["HearingOfficer"])
    with db.LOCK:
        ap = lookup(db.appeals, appeal_id)
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Appeal is not UNDER_REVIEW")
        held = any(h["appeal_id"] == appeal_id and h["status"] == "HELD"
                   for h in db.hearings.values())
        if not held:
            raise err("ERR_NO_HELD_HEARING", "No HELD hearing on this appeal")
        a = db.assessments[ap["assessment_id"]]
        # determined_taxable_value stays null
        ap["status"] = "DENIED"
        db.touch(ap)
        _cascade_no_change(a)
    return object_response(serialize(ap), 200)


@bp.post("/appeals/<appeal_id>/withdraw")
def withdraw_appeal(appeal_id):
    user_id, _role = require_roles(["Taxpayer"])
    with db.LOCK:
        ap = lookup(db.appeals, appeal_id)
        if user_id != ap["filed_by_owner_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the petitioner may withdraw")
        if ap["status"] not in ("FILED", "UNDER_REVIEW"):
            raise err("ERR_INVALID_STATE", "Appeal cannot be withdrawn from its state")
        a = db.assessments[ap["assessment_id"]]
        ap["status"] = "WITHDRAWN"
        db.touch(ap)
        _cascade_no_change(a)
    return object_response(serialize(ap), 200)


@bp.get("/appeals/<appeal_id>/hearings")
def list_appeal_hearings(appeal_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    lookup(db.appeals, appeal_id)
    limit, offset = parse_pagination()
    items = [h for h in db.hearings.values() if h["appeal_id"] == appeal_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)
