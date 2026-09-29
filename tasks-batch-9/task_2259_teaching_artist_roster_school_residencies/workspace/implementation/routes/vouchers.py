"""Payment vouchers and the two-track (fiscal / program) review fork-join."""
from flask import Blueprint, request

import db
import middleware as mw
import response
from enums import REVIEW_TRACK_DECISIONS, REVIEW_TRACKS, VOUCHER_STATUSES
from errors import ApiError
from routes.artists import find_artist
from routes.residencies import find_residency
from routes.sessions import find_session
from services import calc, derive
from validators import Payload, bad

bp = Blueprint("vouchers", __name__)

TRACK_ROLE = {"FISCAL": "FiscalOfficer", "PROGRAM": "ProgramDirector"}
TRACK_FIELD = {"FISCAL": "fiscal_review_status", "PROGRAM": "program_review_status"}
TRACK_REVIEWER = {"FISCAL": "fiscal_reviewed_by", "PROGRAM": "program_reviewed_by"}
OTHER_TRACK = {"FISCAL": "PROGRAM", "PROGRAM": "FISCAL"}


def find_voucher(voucher_id):
    voucher = db.payment_vouchers.get(voucher_id)
    if voucher is None:
        raise ApiError("ERR_VOUCHER_NOT_FOUND", "payment voucher %s not found" % voucher_id)
    return voucher


def invalid_transition(message="the requested transition is not declared from the current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


def has_rubric_evidence(session_id):
    for record in calc.evaluations_of_session(session_id):
        if record["evaluation_type"] != "OBSERVATION_RUBRIC":
            continue
        if (record["rubric_engagement_score"] is not None
                and record["rubric_craft_score"] is not None
                and record["rubric_standards_evidence_score"] is not None):
            return True
    return False


def claimed_sessions(voucher):
    return [db.sessions[sid] for sid in voucher["session_ids"] if sid in db.sessions]


def _check_evaluations(sessions):
    for session in sessions:
        if not has_rubric_evidence(session["id"]):
            raise ApiError("ERR_EVALUATION_MISSING",
                           "session %s carries no complete observation rubric" % session["id"])


def _check_period(sessions, period_start, period_end):
    for session in sessions:
        if not (period_start <= session["session_date"] <= period_end):
            raise ApiError("ERR_VOUCHER_PERIOD_MISMATCH",
                           "session %s falls outside the pay period" % session["id"])


# --- opening a voucher ------------------------------------------------------
@bp.post("/payment-vouchers")
def create_voucher():
    user_id, role = mw.auth("TeachingArtist", "RosterCoordinator")
    body = Payload(request.get_json(silent=True))
    teaching_artist_id = body.string("teaching_artist_id", required=True)
    residency_id = body.string("residency_id", required=True)
    session_ids = body.array("session_ids", required=True)
    period_start = body.date("period_start", required=True)
    period_end = body.date("period_end", required=True)
    if period_end < period_start:
        bad("period_end must not be earlier than period_start")

    artist = find_artist(teaching_artist_id)                      # 5
    residency = find_residency(residency_id)
    sessions = [find_session(sid) for sid in session_ids]

    if role == "TeachingArtist" and user_id != artist["id"]:      # 6
        raise ApiError("ERR_ACTOR_NOT_RESOURCE_OWNER",
                       "an artist may only open a voucher naming themselves as payee")

    for session in sessions:
        if (session["residency_id"] != residency["id"]
                or session["assigned_artist_id"] != artist["id"]):
            bad("session %s does not belong to the named residency and artist" % session["id"])

    for session in sessions:                                      # 14
        if session["payment_voucher_id"] is not None:
            raise ApiError("ERR_SESSION_ALREADY_VOUCHERED",
                           "session %s is already claimed by a voucher" % session["id"])
    _check_evaluations(sessions)
    _check_period(sessions, period_start, period_end)             # 22

    row = db.base_row()
    row.update({
        "teaching_artist_id": artist["id"],
        "residency_id": residency["id"],
        "session_ids": list(session_ids),
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "fiscal_review_status": "PENDING",
        "program_review_status": "PENDING",
        "fiscal_reviewed_by": None,
        "program_reviewed_by": None,
        "void_reason": None,
    })
    db.payment_vouchers[row["id"]] = row
    for session in sessions:
        session["payment_voucher_id"] = row["id"]
        db.touch(session)
    return response.ok(derive.voucher_view(row), 201)


@bp.get("/payment-vouchers/<voucher_id>")
def read_voucher(voucher_id):
    mw.auth()
    return response.ok(derive.voucher_view(find_voucher(voucher_id)))


@bp.get("/payment-vouchers")
def list_vouchers():
    mw.auth()
    limit, offset = mw.pagination()
    teaching_artist_id = mw.q_str("teaching_artist_id")
    residency_id = mw.q_str("residency_id")
    session_ids = mw.q_str("session_ids")
    status = mw.q_enum("status", VOUCHER_STATUSES)

    rows = db.ordered(list(db.payment_vouchers.values()))
    if teaching_artist_id:
        rows = [v for v in rows if v["teaching_artist_id"] == teaching_artist_id]
    if residency_id:
        rows = [v for v in rows if v["residency_id"] == residency_id]
    if session_ids:
        wanted = [part for part in session_ids.split(",") if part]
        rows = [v for v in rows if all(sid in v["session_ids"] for sid in wanted)]
    if status:
        rows = [v for v in rows if v["status"] == status]
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.voucher_view(v) for v in page], limit, offset, total)


# --- submission -------------------------------------------------------------
@bp.post("/payment-vouchers/<voucher_id>/submit")
def submit_voucher(voucher_id):
    user_id, role = mw.auth("TeachingArtist", "RosterCoordinator")
    voucher = find_voucher(voucher_id)
    if role == "TeachingArtist" and user_id != voucher["teaching_artist_id"]:       # 6
        raise ApiError("ERR_ACTOR_NOT_RESOURCE_OWNER",
                       "only the payee artist may submit this voucher")

    current = voucher["status"]
    if current not in ("DRAFT", "REJECTED"):                      # 8
        raise invalid_transition()
    sessions = claimed_sessions(voucher)
    for session in sessions:
        if session["status"] != "DELIVERED":
            raise invalid_transition("session %s is not DELIVERED" % session["id"])

    _check_evaluations(sessions)                                  # 14
    if current == "REJECTED":
        for session in sessions:
            if session["payment_voucher_id"] not in (None, voucher["id"]):
                raise ApiError("ERR_SESSION_ALREADY_VOUCHERED",
                               "session %s is already claimed by another voucher" % session["id"])
    _check_period(sessions, voucher["period_start"], voucher["period_end"])         # 22

    residency = find_residency(voucher["residency_id"])
    total = calc.voucher_total(voucher)["total_cents"]
    if total > calc.budget_ledger(residency)["encumbered_cents"]:                   # 27
        raise ApiError("ERR_RESIDENCY_BUDGET_EXCEEDED",
                       "the voucher total exceeds the residency's encumbered funds")

    voucher["status"] = "SUBMITTED"
    voucher["fiscal_review_status"] = "PENDING"
    voucher["program_review_status"] = "PENDING"
    if current == "REJECTED":
        voucher["fiscal_reviewed_by"] = None
        voucher["program_reviewed_by"] = None
        for session in sessions:
            if session["payment_voucher_id"] != voucher["id"]:
                session["payment_voucher_id"] = voucher["id"]
                db.touch(session)
    db.touch(voucher)
    return response.ok(derive.voucher_view(voucher))


# --- two-track review -------------------------------------------------------
@bp.post("/payment-vouchers/<voucher_id>/review")
def review_voucher(voucher_id):
    user_id, role = mw.auth("FiscalOfficer", "ProgramDirector")
    raw = request.get_json(silent=True)
    if isinstance(raw, dict):
        declared = raw.get("review_track")
        if declared in REVIEW_TRACKS and role != TRACK_ROLE[declared]:
            raise ApiError("ERR_UNAUTHORIZED",
                           "role %s may not close the %s track" % (role, declared))

    voucher = find_voucher(voucher_id)
    body = Payload(raw)
    track = body.enum("review_track", REVIEW_TRACKS, required=True)
    decision = body.enum("decision", REVIEW_TRACK_DECISIONS, required=True)
    body.string("note", default=None, min_len=0)
    expected_version = body.integer("expected_payment_voucher_version", required=True, minimum=0)

    if expected_version != voucher["version"]:                    # 7
        raise ApiError("ERR_STALE_VOUCHER_VERSION",
                       "the voucher has moved on to version %d" % voucher["version"])
    if voucher["status"] != "SUBMITTED":                          # 8
        raise invalid_transition()
    if voucher[TRACK_FIELD[track]] != "PENDING":
        raise invalid_transition("the %s track is already closed" % track)

    other = OTHER_TRACK[track]                                    # 16
    if (voucher[TRACK_FIELD[other]] != "PENDING"
            and voucher[TRACK_REVIEWER[other]] == user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the other review track was closed by the same operator")

    voucher[TRACK_REVIEWER[track]] = user_id
    if decision == "PASS":
        voucher[TRACK_FIELD[track]] = "PASSED"
        if (voucher["fiscal_review_status"] == "PASSED"
                and voucher["program_review_status"] == "PASSED"):
            _approve(voucher)
    else:
        voucher[TRACK_FIELD[track]] = "FAILED"
        voucher["status"] = "REJECTED"
        for session in claimed_sessions(voucher):
            if session["payment_voucher_id"] is not None:
                session["payment_voucher_id"] = None
                db.touch(session)
    db.touch(voucher)
    return response.ok(derive.voucher_view(voucher))


def _approve(voucher):
    """The join: both tracks passed, so the money moves from encumbered to disbursed."""
    voucher["status"] = "APPROVED"
    for session in claimed_sessions(voucher):
        if session["encumbered_cents"]:
            session["encumbered_cents"] = 0
            db.touch(session)
    db.touch(db.residencies.get(voucher["residency_id"]))


# --- voiding ----------------------------------------------------------------
@bp.post("/payment-vouchers/<voucher_id>/void")
def void_voucher(voucher_id):
    mw.auth("FiscalOfficer")
    voucher = find_voucher(voucher_id)
    body = Payload(request.get_json(silent=True))
    void_reason = body.string("void_reason", required=True)

    current = voucher["status"]
    if current not in ("APPROVED", "REJECTED"):                   # 8
        raise invalid_transition()
    residency = db.residencies.get(voucher["residency_id"])
    if current == "APPROVED":
        if residency is not None and residency["status"] == "CLOSED":
            raise invalid_transition("the residency is CLOSED")

    voucher["status"] = "VOIDED"
    voucher["void_reason"] = void_reason
    if current == "APPROVED":
        for session in claimed_sessions(voucher):
            session["encumbered_cents"] = session["payable_cents"] or 0
            session["payment_voucher_id"] = None
            db.touch(session)
        db.touch(residency)
    db.touch(voucher)
    return response.ok(derive.voucher_view(voucher))
