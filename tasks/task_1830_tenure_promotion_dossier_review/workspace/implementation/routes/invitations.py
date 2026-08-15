"""ReviewerInvitation endpoints (PRD §3.4) — solicitation, lazy expiry,
responses, letters, withdrawal, and the candidate confidentiality seal."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_REVIEWER_NOT_FOUND,
    ERR_INVITATION_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_CASE_STAGE_FORBIDDEN,
    ERR_STALE_VERSION,
    ERR_ARMS_LENGTH_VIOLATION,
    ERR_DUPLICATE_INVITATION,
    ERR_INVALID_INTERVAL,
    ERR_REVIEWER_CAPACITY_EXCEEDED,
    ERR_REVIEW_WINDOW_CLOSED,
    ERR_INVALID_INVITATION_STATE,
    ERR_INVITATION_EXPIRED,
)
from middleware import authorized, ALL_READ_ROLES
from response import success_object
from routes.helpers import public, get_one, list_sealed, check_seal_single
from services import calculations as calc
from services.core import new_record, touch, lazy_expire_invitation, case_of_invitation
from util import CLOCK, fmt_dt, parse_dt, is_valid_dt
from validate import (
    get_body, req_str, req_bool, req_int, req_datetime_str, require_path,
    raw_str, raw_int, raw_bool,
)

bp = Blueprint("invitations", __name__)

# Statuses that block a second invitation for the same (case, reviewer).
NON_TERMINAL = {"SOLICITED", "ACCEPTED", "LETTER_RECEIVED"}


@bp.post("/invitations")
def create_invitation():
    authorized(["ProvostOfficer"])
    body = get_body()
    # Priority 4: body FK existence.
    case = None
    case_id_raw = raw_str(body, "case_id")
    if case_id_raw is not None:
        case = db["cases"].get(case_id_raw)
        if case is None:
            raise_error(ERR_CASE_NOT_FOUND, "case_id does not resolve")
    reviewer = None
    reviewer_id_raw = raw_str(body, "reviewer_id")
    if reviewer_id_raw is not None:
        reviewer = db["reviewers"].get(reviewer_id_raw)
        if reviewer is None:
            raise_error(ERR_REVIEWER_NOT_FOUND, "reviewer_id does not resolve")
    # Priority 6: stage gate + OCC on the parent case.
    if case is not None and case["stage"] != "EXTERNAL_REVIEW":
        raise_error(ERR_CASE_STAGE_FORBIDDEN, "solicitation requires EXTERNAL_REVIEW")
    expected = raw_int(body, "expected_case_version")
    if case is not None and expected is not None and expected != case["version"]:
        raise_error(ERR_STALE_VERSION, "expected_case_version does not match the case version")
    # Priority 8: arm's-length certification.
    is_arm_length = raw_bool(body, "is_arm_length")
    declared_coauthor = raw_bool(body, "declared_coauthor")
    if is_arm_length is False or declared_coauthor is True:
        raise_error(ERR_ARMS_LENGTH_VIOLATION,
                    "is_arm_length must be true and declared_coauthor must be false")
    # Priority 9, listed order: duplicate invitation -> interval sanity ->
    # reviewer capacity -> malformed request.
    if case is not None and reviewer is not None:
        for inv in db["invitations"].values():
            if (inv["case_id"] == case["id"] and inv["reviewer_id"] == reviewer["id"]
                    and inv["status"] in NON_TERMINAL):
                raise_error(ERR_DUPLICATE_INVITATION,
                            "a non-terminal invitation already exists for this (case, reviewer)")
    ws_raw = raw_str(body, "review_window_start")
    we_raw = raw_str(body, "review_window_end")
    window_start = window_end = None
    if ws_raw is not None and we_raw is not None and is_valid_dt(ws_raw) and is_valid_dt(we_raw):
        window_start = parse_dt(ws_raw)
        window_end = parse_dt(we_raw)
        if not (window_start < window_end):
            raise_error(ERR_INVALID_INTERVAL, "review_window_start must be before review_window_end")
        if reviewer is not None and not calc.reviewer_capacity_ok(reviewer["id"], window_start, window_end):
            raise_error(ERR_REVIEWER_CAPACITY_EXCEEDED,
                        "reviewer already holds 2 overlapping active assignments")
    # shape
    case_id = req_str(body, "case_id")
    reviewer_id = req_str(body, "reviewer_id")
    review_window_start = req_datetime_str(body, "review_window_start")
    review_window_end = req_datetime_str(body, "review_window_end")
    req_bool(body, "is_arm_length")
    req_bool(body, "declared_coauthor")
    req_int(body, "expected_case_version")  # non-optional OCC field (PRD §2.11)
    # Priority 10: the window's end must still be in the future.
    if not (window_end > CLOCK.now()):
        raise_error(ERR_REVIEW_WINDOW_CLOSED, "review_window_end is not in the future")
    now = CLOCK.now()
    rec = new_record("invitations", {
        "case_id": case_id,
        "reviewer_id": reviewer_id,
        "invited_at": fmt_dt(now),
        "response_deadline": fmt_dt(now + timedelta(days=calc.RESPONSE_DEADLINE_DAYS)),
        "review_window_start": review_window_start,
        "review_window_end": review_window_end,
        "is_arm_length": is_arm_length,
        "declared_coauthor": declared_coauthor,
        "letter_received_at": None,
        "letter_text": None,
        "status": "SOLICITED",
    })
    touch(case)  # invitation creation increments TenureCase.version by 1 (PRD §2.6)
    return success_object(public(rec), status=201)


@bp.get("/invitations")
def list_invitations():
    return list_sealed("invitations", {
        "case_id": request.args.get("case_id"),
        "reviewer_id": request.args.get("reviewer_id"),
        "status": request.args.get("status"),
    }, case_id_of=lambda inv: inv["case_id"])


@bp.get("/invitations/<rid>")
def get_invitation(rid):
    from middleware import get_caller, check_role_allowed
    caller = get_caller()
    check_role_allowed(caller, ALL_READ_ROLES)
    inv = require_path("invitations", rid, ERR_INVITATION_NOT_FOUND)
    lazy_expire_invitation(inv)  # targeting by path id applies lazy expiry
    check_seal_single(caller, case_of_invitation(inv))
    return success_object(public(inv))


def _respond(rid, target_status):
    """accept / decline shared flow."""
    caller = authorized(["ExternalReviewer"])
    inv = require_path("invitations", rid, ERR_INVITATION_NOT_FOUND)
    just_expired = lazy_expire_invitation(inv)
    # Priority 5: the acting reviewer must be the invited reviewer.
    if caller.user_id != inv["reviewer_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting reviewer is not the invited reviewer")
    if just_expired:
        raise_error(ERR_INVITATION_EXPIRED, "the response deadline has passed")
    if inv["status"] != "SOLICITED":
        raise_error(ERR_INVALID_INVITATION_STATE,
                    f"cannot respond to an invitation in status {inv['status']}")
    inv["status"] = target_status
    touch(inv)
    return success_object(public(inv))


@bp.post("/invitations/<rid>/accept")
def accept_invitation(rid):
    return _respond(rid, "ACCEPTED")


@bp.post("/invitations/<rid>/decline")
def decline_invitation(rid):
    return _respond(rid, "DECLINED")


@bp.post("/invitations/<rid>/submit-letter")
def submit_letter(rid):
    caller = authorized(["ExternalReviewer"])
    inv = require_path("invitations", rid, ERR_INVITATION_NOT_FOUND)
    lazy_expire_invitation(inv)
    if caller.user_id != inv["reviewer_id"]:
        raise_error(ERR_OWNERSHIP_MISMATCH, "acting reviewer is not the invited reviewer")
    if inv["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_INVITATION_STATE,
                    f"cannot submit a letter for an invitation in status {inv['status']}")
    body = get_body()
    letter_text = req_str(body, "letter_text")
    if CLOCK.now() > parse_dt(inv["review_window_end"]):
        raise_error(ERR_REVIEW_WINDOW_CLOSED, "the review window has closed")
    inv["letter_text"] = letter_text
    inv["letter_received_at"] = CLOCK.now_iso()
    inv["status"] = "LETTER_RECEIVED"
    touch(inv)
    return success_object(public(inv))


@bp.post("/invitations/<rid>/withdraw")
def withdraw_invitation(rid):
    authorized(["ProvostOfficer"])
    inv = require_path("invitations", rid, ERR_INVITATION_NOT_FOUND)
    lazy_expire_invitation(inv)
    if inv["status"] not in ("SOLICITED", "ACCEPTED"):
        raise_error(ERR_INVALID_INVITATION_STATE,
                    f"cannot withdraw an invitation in status {inv['status']}")
    inv["status"] = "WITHDRAWN"
    touch(inv)
    return success_object(public(inv))
