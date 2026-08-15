"""Amendment request endpoints."""
from flask import Blueprint, g, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("amendments", __name__)


def get_amendment_or_404(amendment_id):
    r = db.amendment_requests.get(amendment_id)
    if r is None:
        raise ApiError("ERR_AMENDMENT_REQUEST_NOT_FOUND", "AmendmentRequest id does not exist.", 404)
    return r


def _validate_changes(e, b):
    """Payload shape rules for create/resubmit (ERR_INVALID_REQUEST)."""
    changes = b.get("requested_changes")
    acreage = b.get("affected_acreage")
    if not isinstance(changes, list) or len(changes) == 0:
        raise ApiError("ERR_INVALID_REQUEST", "requested_changes must be a non-empty array.", 400)
    matrix = e["permitted_use_matrix"]
    for ch in changes:
        if not isinstance(ch, dict) or not isinstance(ch.get("use_type"), str):
            raise ApiError("ERR_INVALID_REQUEST", "Each change must pair a use_type with a new_level.", 400)
        if ch["use_type"] not in matrix:
            raise ApiError("ERR_INVALID_REQUEST", "Every use_type must exist in the current matrix.", 400)
        if ch.get("new_level") not in domain.LEVELS:
            raise ApiError("ERR_INVALID_REQUEST", "new_level must be PERMITTED | DISCRETIONARY | PROHIBITED.", 400)
        if ch["new_level"] == matrix[ch["use_type"]]:
            raise ApiError("ERR_INVALID_REQUEST", "new_level must differ from the current cell.", 400)
    if not utils.is_int(acreage) or acreage < 1 or acreage > e["parcel_acreage"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", "affected_acreage must be an integer in 1..parcel_acreage.", 400
        )
    cleaned = [{"use_type": ch["use_type"], "new_level": ch["new_level"]} for ch in changes]
    return cleaned, acreage


@bp.route("/stewardship/amendment-requests", methods=["POST"])
@require_roles("StewardshipCoordinator")
def create_amendment():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    e = db.easements.get(easement_id)
    if e is not None and e["status"] != "RECORDED":
        raise ApiError("ERR_EASEMENT_NOT_RECORDED", "Child operational create requires a RECORDED easement.", 409)
    # OCC (priority 6): compare only when the field is present and well-typed.
    expected = b.get("expected_easement_version")
    if e is not None and utils.is_int(expected) and expected != e["version"]:
        raise ApiError("ERR_STALE_EASEMENT_VERSION", "expected_easement_version does not match the easement version.", 412)
    # Uniqueness (priority 8): one in-flight amendment per easement.
    if e is not None and any(
        a["easement_id"] == easement_id and a["status"] in domain.IN_FLIGHT_AMENDMENT_STATES
        for a in db.amendment_requests.values()
    ):
        raise ApiError("ERR_AMENDMENT_ALREADY_IN_FLIGHT", "Another amendment of this easement is in flight.", 409)
    if e is None or not utils.is_int(expected) or not isinstance(b.get("submitted_by_user_id"), str):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "easement_id, expected_easement_version and submitted_by_user_id are required.",
            400,
        )
    changes, acreage = _validate_changes(e, b)
    score, path = domain.materiality(e["parcel_acreage"], e["permitted_use_matrix"], changes, acreage)
    now = utils.now_iso()
    r = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "submitted_by_user_id": b["submitted_by_user_id"],
        "requested_changes": changes,
        "affected_acreage": acreage,
        "materiality_score": score,
        "review_path": path,
        "revision_notes": None,
        "decided_by_user_id": None,
        "status": "SUBMITTED",
    }
    db.amendment_requests[r["id"]] = r
    domain.bump(e)
    return ok(domain.amendment_json(r), 201)


@bp.route("/stewardship/amendment-requests", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_amendments():
    filters = {}
    for key in ("easement_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.amendment_requests.values()), domain.amendment_json, filters)


@bp.route("/stewardship/amendment-requests/<amendmentRequestId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_amendment(amendmentRequestId):
    return ok(domain.amendment_json(get_amendment_or_404(amendmentRequestId)))


def _transition(amendment_id, from_states, to_state):
    r = get_amendment_or_404(amendment_id)
    if r["status"] not in from_states:
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE",
            "Transition is not defined from state %s." % r["status"],
            409,
        )
    r["status"] = to_state
    domain.bump(r)
    return r


@bp.route("/stewardship/amendment-requests/<amendmentRequestId>/start-review", methods=["POST"])
@require_roles("StewardshipCoordinator")
def start_review(amendmentRequestId):
    return ok(domain.amendment_json(_transition(amendmentRequestId, ("SUBMITTED",), "STAFF_REVIEW")))


@bp.route("/stewardship/amendment-requests/<amendmentRequestId>/request-revision", methods=["POST"])
@require_roles("StewardshipCoordinator")
def request_revision(amendmentRequestId):
    r = get_amendment_or_404(amendmentRequestId)
    if r["status"] != "STAFF_REVIEW":
        raise ApiError("ERR_INVALID_AMENDMENT_STATE", "Request-revision requires STAFF_REVIEW.", 409)
    b = body()
    notes = b.get("revision_notes")
    if not isinstance(notes, str):
        raise ApiError("ERR_INVALID_REQUEST", "revision_notes is required.", 400)
    r["revision_notes"] = notes
    r["status"] = "REVISION_REQUESTED"
    domain.bump(r)
    return ok(domain.amendment_json(r))


@bp.route("/stewardship/amendment-requests/<amendmentRequestId>/resubmit", methods=["POST"])
@require_roles("StewardshipCoordinator")
def resubmit(amendmentRequestId):
    r = get_amendment_or_404(amendmentRequestId)
    if r["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_AMENDMENT_STATE", "Resubmit requires REVISION_REQUESTED.", 409)
    b = body()
    e = db.easements[r["easement_id"]]
    changes, acreage = _validate_changes(e, b)
    r["requested_changes"] = changes
    r["affected_acreage"] = acreage
    score, path = domain.materiality(e["parcel_acreage"], e["permitted_use_matrix"], changes, acreage)
    r["materiality_score"] = score
    r["review_path"] = path
    r["status"] = "SUBMITTED"
    domain.bump(r)
    return ok(domain.amendment_json(r))


@bp.route("/stewardship/amendment-requests/<amendmentRequestId>/escalate-board", methods=["POST"])
@require_roles("StewardshipCoordinator")
def escalate_board(amendmentRequestId):
    return ok(domain.amendment_json(_transition(amendmentRequestId, ("STAFF_REVIEW",), "BOARD_REVIEW")))


def _approve_cascade(r):
    e = db.easements[r["easement_id"]]
    changed_types = {ch["use_type"] for ch in r["requested_changes"]}
    # Link 1: matrix mutation (+ amendment_count derived from APPROVED rows).
    for ch in r["requested_changes"]:
        e["permitted_use_matrix"][ch["use_type"]] = ch["new_level"]
    domain.bump(e)
    # Link 2: freeze mirror — REQUESTED authorizations on changed cells are auto-denied.
    for a in db.use_authorizations.values():
        if (
            a["easement_id"] == r["easement_id"]
            and a["status"] == "REQUESTED"
            and a["use_type"] in changed_types
        ):
            a["status"] = "DENIED"
            a["decision"] = "DENIED"
            a["decision_reason"] = "AMENDMENT_SUPERSEDES"
            domain.bump(a)


@bp.route("/stewardship/amendment-requests/<amendmentRequestId>/approve", methods=["POST"])
@require_roles("StewardshipCoordinator", "TrustBoardReviewer")
def approve(amendmentRequestId):
    r = get_amendment_or_404(amendmentRequestId)
    role = g.user_role
    # Lanes are role-bound: staff approve from STAFF_REVIEW, board from BOARD_REVIEW.
    if r["status"] == "STAFF_REVIEW" and role == "StewardshipCoordinator":
        if g.user_id == r["submitted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The submitter may not approve the amendment.", 403)
        if r["materiality_score"] >= domain.BOARD_THRESHOLD:
            raise ApiError("ERR_MATERIALITY_REQUIRES_BOARD", "materiality_score >= 70 requires board approval.", 403)
    elif r["status"] == "BOARD_REVIEW" and role == "TrustBoardReviewer":
        if g.user_id == r["submitted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The submitter may not approve the amendment.", 403)
    else:
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE",
            "Approve is not defined from state %s for role %s." % (r["status"], role),
            409,
        )
    r["status"] = "APPROVED"
    r["decided_by_user_id"] = g.user_id
    domain.bump(r)
    _approve_cascade(r)
    return ok(domain.amendment_json(r))


@bp.route("/stewardship/amendment-requests/<amendmentRequestId>/reject", methods=["POST"])
@require_roles("StewardshipCoordinator", "TrustBoardReviewer")
def reject(amendmentRequestId):
    r = get_amendment_or_404(amendmentRequestId)
    role = g.user_role
    if r["status"] == "STAFF_REVIEW" and role == "StewardshipCoordinator":
        pass
    elif r["status"] == "BOARD_REVIEW" and role == "TrustBoardReviewer":
        pass
    else:
        raise ApiError(
            "ERR_INVALID_AMENDMENT_STATE",
            "Reject is not defined from state %s for role %s." % (r["status"], role),
            409,
        )
    r["status"] = "REJECTED"
    r["decided_by_user_id"] = g.user_id
    domain.bump(r)
    return ok(domain.amendment_json(r))


@bp.route("/stewardship/amendment-requests/<amendmentRequestId>/withdraw", methods=["POST"])
@require_roles("StewardshipCoordinator")
def withdraw(amendmentRequestId):
    return ok(
        domain.amendment_json(
            _transition(
                amendmentRequestId,
                ("SUBMITTED", "STAFF_REVIEW", "REVISION_REQUESTED", "BOARD_REVIEW"),
                "WITHDRAWN",
            )
        )
    )
