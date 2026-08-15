"""Reopening endpoints (PRD section 3.8)."""

from datetime import timedelta

from flask import Blueprint

import calc
import db
import errors
from auth import require_roles
from envelope import success_object
from serializers import reopening_out
from services import (append_event, get_or_404, guard_entity_status)
from validate import get_body, req_enum, req_str

bp = Blueprint("reopenings", __name__)

REOPEN_REASONS = {"NEW_EVIDENCE", "CLERICAL_ERROR", "FRAUD_OR_SIMILAR_FAULT"}
REOPENING_TERMINAL = ("GRANTED", "DENIED")


def _check_reopen_window(source_case, requested_at):
    """NEW_EVIDENCE / CLERICAL_ERROR within 180 days of closed_at; FRAUD exempt."""
    delta = requested_at - source_case["closed_at"]
    if delta > timedelta(days=calc.REOPEN_WINDOW_DAYS):
        raise errors.reopen_window_missed()


@bp.route("/appeals/reopenings", methods=["POST"])
@require_roles({"ComplianceOfficer", "MemberServicesRep"})
def request_reopening(_user_id, _role):
    body = get_body()
    case_id = req_str(body, "case_id")
    request_reason = req_enum(body, "request_reason", REOPEN_REASONS)
    source = db.cases.get(case_id)
    if source is None:
        raise errors.reference_not_found(f"case not found: {case_id}")
    # Reopenings may only target CLOSED cases; WITHDRAWN stays locked.
    if source["status"] == "WITHDRAWN":
        raise errors.already_terminal("cannot reopen a WITHDRAWN case")
    if source["status"] != "CLOSED":
        raise errors.invalid_state("only CLOSED cases may be reopened")
    now = db.clock_now()
    if request_reason != "FRAUD_OR_SIMILAR_FAULT":
        _check_reopen_window(source, now)
    r = db.make_common()
    r.update({
        "case_id": case_id,
        "request_reason": request_reason,
        "status": "REQUESTED",
        "requested_at": now,
        "decided_at": None,
        "spawned_case_id": None,
    })
    db.reopenings[r["id"]] = r
    append_event(source, "REOPEN_REQUESTED", _role, _user_id,
                 bump_case_version=True)
    return success_object(reopening_out(r), status=201)


@bp.route("/appeals/reopenings/<rid>", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer"})
def get_reopening(rid, _user_id, _role):
    return success_object(reopening_out(
        get_or_404(db.reopenings, rid, "reopening")))


@bp.route("/appeals/reopenings/<rid>/begin-review", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def begin_reopening_review(rid, _user_id, _role):
    r = get_or_404(db.reopenings, rid, "reopening")
    guard_entity_status(r, ("REQUESTED",), REOPENING_TERMINAL, "reopening")
    r["status"] = "UNDER_REVIEW"
    db.touch(r)
    return success_object(reopening_out(r))


@bp.route("/appeals/reopenings/<rid>/grant", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def grant_reopening(rid, _user_id, _role):
    r = get_or_404(db.reopenings, rid, "reopening")
    guard_entity_status(r, ("UNDER_REVIEW",), REOPENING_TERMINAL, "reopening")
    body = get_body()
    expected = body.get("expected_case_version")
    if expected is None:
        raise errors.validation("missing required field: expected_case_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.validation("expected_case_version must be an integer")
    source = db.cases[r["case_id"]]
    if source["status"] != "CLOSED":
        raise errors.invalid_state("source case is no longer CLOSED")
    # Window re-verified between source closed_at and requested_at
    if r["request_reason"] != "FRAUD_OR_SIMILAR_FAULT":
        _check_reopen_window(source, r["requested_at"])
    for other in db.reopenings.values():
        if (other["id"] != r["id"] and other["case_id"] == source["id"]
                and other["status"] == "GRANTED"):
            raise errors.invalid_state(
                "another reopening for this case is already GRANTED")
    # OCC (PRD section 2.7.2)
    if expected != source["version"]:
        raise errors.stale_version()
    now = db.clock_now()
    # Spawn the replacement case; source moves CLOSED -> REOPENED as a marker
    spawned = db.make_common()
    spawned.update({
        "member_id": source["member_id"],
        "provider_id": source["provider_id"],
        "case_kind": source["case_kind"],
        "priority_track": source["priority_track"],
        "expedited_requested": False,
        "expedited_justification": None,
        "status": "RECEIVED",
        "decision_outcome": None,
        "received_at": now,
        "acknowledged_at": None,
        "decided_at": None,
        "notified_at": None,
        "closed_at": None,
        "extension_applied": False,
        "resolution_due_at": None,
        "effectuation_due_at": None,
        "ctm_linked": False,
        "reopened_from_case_id": source["id"],
        "_triaged_by": None,
    })
    db.cases[spawned["id"]] = spawned
    r["decided_at"] = now
    r["spawned_case_id"] = spawned["id"]
    r["status"] = "GRANTED"
    db.touch(r)
    source["status"] = "REOPENED"
    append_event(source, "REOPEN_GRANTED", _role, _user_id)
    db.touch(source)
    # Any DETERMINED clinical review on the source case is superseded
    for review in db.reviews.values():
        if review["case_id"] == source["id"] and review["status"] == "DETERMINED":
            review["status"] = "SUPERSEDED"
            db.touch(review)
    return success_object(reopening_out(r))


@bp.route("/appeals/reopenings/<rid>/deny", methods=["POST"])
@require_roles({"ComplianceOfficer"})
def deny_reopening(rid, _user_id, _role):
    r = get_or_404(db.reopenings, rid, "reopening")
    guard_entity_status(r, ("UNDER_REVIEW",), REOPENING_TERMINAL, "reopening")
    r["status"] = "DENIED"
    r["decided_at"] = db.clock_now()
    db.touch(r)
    source = db.cases.get(r["case_id"])
    if source is not None:
        append_event(source, "REOPEN_DENIED", _role, _user_id,
                     bump_case_version=True)
    return success_object(reopening_out(r))
