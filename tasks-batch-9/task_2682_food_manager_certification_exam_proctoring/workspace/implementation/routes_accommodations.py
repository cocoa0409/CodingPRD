"""Accommodation requests and the two-hop review fork."""
from flask import Blueprint

import authz
import calc
import cascade
import validation as V
from authz import require, find, deny_scope
from envelope import ok
from errors import ApiError
from helpers import paged, scoped_filter, match
from store import store

accommodations_bp = Blueprint("accommodations", __name__)


def _accommodation_scope(accommodation, user_id, role):
    if role == authz.PROVIDER_ADMIN \
            and authz.provider_of_accommodation(accommodation) != user_id:
        deny_scope()
    if role == authz.CANDIDATE and accommodation["candidate_id"] != user_id:
        deny_scope()


@accommodations_bp.post("/accommodation-requests")
def create_accommodation():
    user_id, role = require(authz.PROVIDER_ADMIN, authz.CANDIDATE)
    body = V.get_body()
    candidate_id = V.req_id(body, "candidate_id")
    accommodation_type = V.req_enum(body, "accommodation_type",
                                    V.ACCOMMODATION_TYPES)
    multiplier = V.req_decimal(body, "requested_multiplier", 1.0, 2.0, 2)
    documentation_ref = V.req_str(body, "documentation_ref", 1)
    requested_language = V.opt_enum(body, "requested_language", V.LANGUAGES,
                                    None)
    if role == authz.CANDIDATE and candidate_id != user_id:
        deny_scope("a candidate may only file for itself")
    candidate = find("candidate", candidate_id)
    if role == authz.PROVIDER_ADMIN \
            and candidate["training_provider_id"] != user_id:
        deny_scope()
    row = store.base()
    row.update({
        "candidate_id": candidate_id,
        "accommodation_type": accommodation_type,
        "requested_multiplier": multiplier,
        "documentation_ref": documentation_ref,
        "requested_language": requested_language,
        "status": "REQUESTED",
        "approved_multiplier": None,
        "decision_reason": None,
        "reviewed_by_user_id": None,
    })
    store.accommodations[row["id"]] = row
    return ok(row, 201)


@accommodations_bp.get("/accommodation-requests/<accommodation_id>")
def read_accommodation(accommodation_id):
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN,
                            authz.CANDIDATE)
    accommodation = find("accommodation", accommodation_id)
    _accommodation_scope(accommodation, user_id, role)
    return ok(accommodation)


@accommodations_bp.get("/accommodation-requests")
def list_accommodations():
    user_id, role = require(authz.PLATFORM_ADMIN, authz.PROVIDER_ADMIN)
    candidate_filter = V.query_id("candidate_id")
    status = V.query_enum("status", V.ACCOMMODATION_STATUS)
    rows = [r for r in store.accommodations.values()
            if match(r, "candidate_id", candidate_filter)
            and match(r, "status", status)]
    if role == authz.PROVIDER_ADMIN:
        rows = [r for r in rows
                if authz.provider_of_accommodation(r) == user_id]
    return paged(rows)


@accommodations_bp.post("/accommodation-requests/<accommodation_id>/review-open")
def accommodation_review_open(accommodation_id):
    user_id, role = require(authz.PLATFORM_ADMIN)
    accommodation = find("accommodation", accommodation_id)
    V.get_body()
    if accommodation["status"] != "REQUESTED":
        raise ApiError("ERR_ACCOMMODATION_STATE_INVALID",
                       "the request is not REQUESTED")
    accommodation["status"] = "UNDER_REVIEW"
    accommodation["reviewed_by_user_id"] = user_id
    store.touch(accommodation)
    return ok(accommodation)


def _linked_scheduled_sessions(accommodation_id):
    return store.ordered([s for s in store.sessions.values()
                          if s["accommodation_request_id"] == accommodation_id
                          and s["session_status"] == "SCHEDULED"])


@accommodations_bp.post("/accommodation-requests/<accommodation_id>/review")
def accommodation_review(accommodation_id):
    user_id, role = require(authz.PLATFORM_ADMIN)
    accommodation = find("accommodation", accommodation_id)
    body = V.get_body()
    decision = V.req_enum(body, "decision", ["APPROVE", "DENY"])
    granted = V.opt_decimal(body, "approved_multiplier", 1.0, 2.0, 2, None)
    decision_reason = V.opt_str(body, "decision_reason", 1, None, None)
    if accommodation["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_ACCOMMODATION_STATE_INVALID",
                       "the request is not UNDER_REVIEW")
    if decision == "DENY":
        accommodation["status"] = "DENIED"
        accommodation["decision_reason"] = decision_reason
        store.touch(accommodation)
        return ok(accommodation)

    for other in store.accommodations.values():
        if other["id"] == accommodation["id"]:
            continue
        if other["candidate_id"] != accommodation["candidate_id"]:
            continue
        if other["status"] == "APPROVED":
            raise ApiError("ERR_DUPLICATE_APPROVED_ACCOMMODATION",
                           "the candidate already holds an approved "
                           "accommodation")
    if granted is None:
        granted = accommodation["requested_multiplier"]
    elif granted > accommodation["requested_multiplier"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "approved_multiplier may not exceed requested_multiplier")

    probe = dict(accommodation)
    probe["status"] = "APPROVED"
    probe["approved_multiplier"] = granted
    sessions = _linked_scheduled_sessions(accommodation["id"])
    plans = []
    for session in sessions:
        form = store.exam_forms.get(session["exam_form_id"])
        minutes, end_at = cascade.new_interval(session, form, probe)
        calc.check_occupancy(session["proctor_id"], session["testing_site_id"],
                             session["scheduled_start_at"], end_at,
                             session["id"])
        plans.append((session, minutes, end_at))

    accommodation["status"] = "APPROVED"
    accommodation["approved_multiplier"] = granted
    accommodation["decision_reason"] = decision_reason
    store.touch(accommodation)
    for session, minutes, end_at in plans:
        cascade.apply_retime(session, minutes, end_at)
    return ok(accommodation)
