"""Registration routes: create, get, list, confirm, cancel, check-in,
plus AXIS-2 scoring transitions and FK sub-resource GETs.
"""
from flask import Blueprint, request

from db import store, stamp_create, touch
from errors import (err, ERR_INVALID_REQUEST, ERR_STALE_SESSION_VERSION,
                    ERR_SESSION_CLOSED, ERR_SESSION_FULL, ERR_INVALID_STATE,
                    ERR_ID_VERIFICATION_FAILED, ERR_REFUND_WINDOW_CLOSED)
from middleware import require_roles
from response import object_response, array_response
from services import lookups, serializers
from services.common import (get_json_body, require_fields, parse_pagination,
                             paginate, sort_by_created_at, D)
from services import calculations as calc
from services import engine

bp = Blueprint("registrations", __name__)


# ---------------------------------------------------------------------------
# POST /registrations  (reserve a seat)
# ---------------------------------------------------------------------------
@bp.route("/registrations", methods=["POST"])
@require_roles("Candidate")
def create_registration():
    body = get_json_body()
    require_fields(body, ["test_session_id", "candidate_id",
                          "expected_test_session_version"])

    # Existence: FK left-to-right (session first, then candidate) per §2.5.
    session = lookups.test_session(body["test_session_id"])
    candidate = lookups.candidate(body["candidate_id"])

    # Well-formedness.
    expected_version = body["expected_test_session_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_test_session_version must be an integer")

    fee_reduction_pct = body.get("fee_reduction_pct", 0.0)
    if fee_reduction_pct is None:
        fee_reduction_pct = 0.0
    if isinstance(fee_reduction_pct, bool) or not isinstance(fee_reduction_pct, (int, float)):
        raise err(ERR_INVALID_REQUEST, "fee_reduction_pct must be a number")
    if fee_reduction_pct < 0 or fee_reduction_pct > 1:
        raise err(ERR_INVALID_REQUEST, "fee_reduction_pct must be between 0 and 1")

    # OCC (priority 5) — before state/business checks.
    if expected_version != session["version"]:
        raise err(ERR_STALE_SESSION_VERSION,
                  "expected_test_session_version does not match current session version")

    # Session closed (priority 12, evaluated ahead of capacity per §2.6).
    if session["registration_status"] == "CLOSED":
        raise err(ERR_SESSION_CLOSED, "Cannot register on a closed session")

    # Standard-pool capacity (priority 13).
    center = lookups.test_center(session["test_center_id"])
    if session["standard_seats_reserved"] >= center["room_capacity_standard"]:
        raise err(ERR_SESSION_FULL, "Standard pool is full; join standby")

    # Fee settlement (single line item unless AP bundle; here one seat = one line).
    amount_paid = calc.ap_fee_settlement([session["base_fee_cents"]], fee_reduction_pct)

    reg = {
        "test_session_id": session["id"],
        "candidate_id": candidate["id"],
        "accommodation_request_id": None,
        "seat_kind": "STANDARD",
        "allotted_minutes": calc.allotted_minutes(session["exam_type"], None),
        "amount_paid_cents": amount_paid,
        "amount_refunded_cents": 0,
        "refund_tier": None,
        "lifecycle_status": "RESERVED",
        "score_status": "PENDING",
        "is_standby_origin": False,
    }
    stamp_create(reg)
    store.registrations[reg["id"]] = reg

    # Seat + money settlement.
    engine.add_standard_seat(session)            # standard_seats_reserved += 1; version bump
    center["net_revenue_cents"] += amount_paid
    touch(center)

    return object_response(serializers.registration(reg), 201)


# ---------------------------------------------------------------------------
# GET /registrations/{id}
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>", methods=["GET"])
@require_roles("Candidate", "TestCenterAdmin", "ScoreOps", "AccommodationReviewer")
def get_registration(rid):
    reg = lookups.registration(rid)
    return object_response(serializers.registration(reg), 200)


# ---------------------------------------------------------------------------
# GET /registrations  (filter by FK)
# ---------------------------------------------------------------------------
@bp.route("/registrations", methods=["GET"])
@require_roles("Candidate", "TestCenterAdmin", "ScoreOps", "AccommodationReviewer")
def list_registrations():
    limit, offset = parse_pagination()
    test_session_id = request.args.get("test_session_id")
    candidate_id = request.args.get("candidate_id")
    accommodation_request_id = request.args.get("accommodation_request_id")

    items = list(store.registrations.values())
    if test_session_id is not None:
        items = [r for r in items if r["test_session_id"] == test_session_id]
    if candidate_id is not None:
        items = [r for r in items if r["candidate_id"] == candidate_id]
    if accommodation_request_id is not None:
        items = [r for r in items if r["accommodation_request_id"] == accommodation_request_id]

    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serializers.registration(r) for r in page],
                          limit, offset, total, 200)


# ---------------------------------------------------------------------------
# POST /registrations/{id}/confirm   RESERVED -> CONFIRMED
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>/confirm", methods=["POST"])
@require_roles("Candidate")
def confirm_registration(rid):
    reg = lookups.registration(rid)
    session = lookups.test_session(reg["test_session_id"])

    if reg["lifecycle_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Registration is not RESERVED")
    if session["registration_status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Session is not OPEN")

    reg["lifecycle_status"] = "CONFIRMED"
    touch(reg)
    return object_response(serializers.registration(reg), 200)


# ---------------------------------------------------------------------------
# POST /registrations/{id}/cancel  -> CANCELLED (tiered refund + cascade)
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>/cancel", methods=["POST"])
@require_roles("Candidate")
def cancel_registration(rid):
    reg = lookups.registration(rid)
    session = lookups.test_session(reg["test_session_id"])
    center = lookups.test_center(session["test_center_id"])

    if reg["lifecycle_status"] not in ("RESERVED", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Registration cannot be cancelled from its current state")

    clock_now = store.get_clock_now()
    tier, refund_amount = calc.tiered_refund(
        reg["amount_paid_cents"], session["test_date"], clock_now)

    # Move to CANCELLED.
    reg["lifecycle_status"] = "CANCELLED"
    reg["amount_refunded_cents"] += refund_amount
    reg["refund_tier"] = tier
    touch(reg)

    # Money conservation.
    center["net_revenue_cents"] -= refund_amount
    touch(center)

    # Seat release on the matching pool + version bump.
    if reg["seat_kind"] == "STANDARD":
        engine.remove_standard_seat(session)
        # CASCADE: freed STANDARD seat -> promote top WAITING standby (depth-3).
        engine.promote_top_standby(session)
    else:
        engine.remove_accommodated_seat(session)
        engine.bump_session_version(session)

    return object_response(serializers.registration(reg), 200)


# ---------------------------------------------------------------------------
# POST /registrations/{id}/check-in  CONFIRMED -> CHECKED_IN
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>/check-in", methods=["POST"])
@require_roles("TestCenterAdmin")
def check_in_registration(rid):
    reg = lookups.registration(rid)

    # State validity first (priority 6).
    if reg["lifecycle_status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Registration is not CONFIRMED")

    # ID-verification gate (priority 8): need a MATCH IDVerification on file.
    has_match = any(
        v["registration_id"] == reg["id"] and v["outcome"] == "MATCH"
        for v in store.id_verifications.values()
    )
    if not has_match:
        raise err(ERR_ID_VERIFICATION_FAILED,
                  "No passing ID verification on file for this registration")

    # Accommodated seat requires its bound accommodation APPROVED.
    if reg["seat_kind"] == "ACCOMMODATED":
        acc_id = reg.get("accommodation_request_id")
        acc = store.accommodation_requests.get(acc_id) if acc_id else None
        if acc is None or acc["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE,
                      "Accommodated registration requires an APPROVED accommodation")

    reg["lifecycle_status"] = "CHECKED_IN"
    touch(reg)
    return object_response(serializers.registration(reg), 200)


# ---------------------------------------------------------------------------
# AXIS 2: POST /registrations/{id}/score-reports   PENDING -> SCORED
# ---------------------------------------------------------------------------
SECTIONED_EXAMS = {"SAT", "ACT"}
SAT_REQUIRED = {"READING_WRITING", "MATH"}
ACT_REQUIRED = {"ENGLISH", "MATH", "READING", "SCIENCE"}


@bp.route("/registrations/<rid>/score-reports", methods=["POST"])
@require_roles("ScoreOps")
def create_score_report(rid):
    reg = lookups.registration(rid)
    body = get_json_body()
    require_fields(body, ["exam_type", "section_scores"])

    exam_type = body["exam_type"]
    if exam_type not in SECTIONED_EXAMS:
        raise err(ERR_INVALID_REQUEST, "exam_type must be SAT or ACT for a score report")

    section_scores = body["section_scores"]
    if not isinstance(section_scores, dict):
        raise err(ERR_INVALID_REQUEST, "section_scores must be an object")

    required = SAT_REQUIRED if exam_type == "SAT" else ACT_REQUIRED
    for sec in required:
        if sec not in section_scores or section_scores[sec] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing section score: {sec}")
        val = section_scores[sec]
        if not isinstance(val, int) or isinstance(val, bool):
            raise err(ERR_INVALID_REQUEST, f"Section score {sec} must be an integer")

    # State: score_status must be PENDING and lifecycle must be CHECKED_IN.
    if reg["score_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Registration score_status is not PENDING")
    if reg["lifecycle_status"] != "CHECKED_IN":
        raise err(ERR_INVALID_STATE, "Registration must be CHECKED_IN before scoring")

    # Keep only the canonical sections for the exam.
    clean_sections = {sec: section_scores[sec] for sec in required}

    sr = {
        "registration_id": reg["id"],
        "candidate_id": reg["candidate_id"],
        "exam_type": exam_type,
        "section_scores": clean_sections,
        "sitting_composite": calc.sitting_composite(exam_type, clean_sections),
        "super_composite": None,
    }
    stamp_create(sr)
    store.score_reports[sr["id"]] = sr

    reg["score_status"] = "SCORED"
    touch(reg)

    return object_response(serializers.score_report(sr), 201)


# ---------------------------------------------------------------------------
# POST /registrations/{id}/release-score   SCORED -> RELEASED
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>/release-score", methods=["POST"])
@require_roles("ScoreOps")
def release_score(rid):
    reg = lookups.registration(rid)
    if reg["score_status"] != "SCORED":
        raise err(ERR_INVALID_STATE, "Registration score_status is not SCORED")

    reg["score_status"] = "RELEASED"
    touch(reg)

    # Recompute super score across candidate's released sittings of same exam_type.
    sr = _score_report_for_reg(reg["id"])
    if sr is not None:
        engine.recompute_super_scores(reg["candidate_id"], sr["exam_type"])

    return object_response(serializers.registration(reg), 200)


# ---------------------------------------------------------------------------
# POST /registrations/{id}/cancel-score   SCORED|RELEASED -> CANCELLED_SCORE
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>/cancel-score", methods=["POST"])
@require_roles("Candidate")
def cancel_score(rid):
    reg = lookups.registration(rid)
    if reg["score_status"] not in ("SCORED", "RELEASED"):
        raise err(ERR_INVALID_STATE, "Score cannot be cancelled from its current state")

    reg["score_status"] = "CANCELLED_SCORE"
    touch(reg)

    # Recompute super score for remaining released sittings.
    sr = _score_report_for_reg(reg["id"])
    if sr is not None:
        engine.recompute_super_scores(reg["candidate_id"], sr["exam_type"])

    return object_response(serializers.registration(reg), 200)


def _score_report_for_reg(registration_id):
    for sr in store.score_reports.values():
        if sr["registration_id"] == registration_id:
            return sr
    return None


# ---------------------------------------------------------------------------
# GET /registrations/{id}/id-verifications
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>/id-verifications", methods=["GET"])
@require_roles("TestCenterAdmin", "Candidate")
def list_reg_id_verifications(rid):
    lookups.registration(rid)  # path existence
    limit, offset = parse_pagination()
    items = [v for v in store.id_verifications.values()
             if v["registration_id"] == rid]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serializers.id_verification(v) for v in page],
                          limit, offset, total, 200)


# ---------------------------------------------------------------------------
# GET /registrations/{id}/score-sends
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>/score-sends", methods=["GET"])
@require_roles("Candidate", "ScoreOps")
def list_reg_score_sends(rid):
    lookups.registration(rid)  # path existence
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [s for s in store.score_sends.values()
             if s["registration_id"] == rid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serializers.score_send(s) for s in page],
                          limit, offset, total, 200)


# ---------------------------------------------------------------------------
# POST /registrations/{id}/id-verifications  (record an ID verification)
# ---------------------------------------------------------------------------
@bp.route("/registrations/<rid>/id-verifications", methods=["POST"])
@require_roles("TestCenterAdmin")
def create_id_verification(rid):
    reg = lookups.registration(rid)
    body = get_json_body()
    require_fields(body, ["presented_first_name", "presented_last_name",
                          "presented_id_state_code"])
    for f in ["presented_first_name", "presented_last_name", "presented_id_state_code"]:
        if not isinstance(body[f], str):
            raise err(ERR_INVALID_REQUEST, f"{f} must be a string")

    session = store.test_sessions[reg["test_session_id"]]
    center = store.test_centers[session["test_center_id"]]
    candidate = store.candidates[reg["candidate_id"]]

    cross_state, outcome = calc.id_verification(
        body["presented_first_name"], body["presented_last_name"],
        body["presented_id_state_code"], center["state_code"],
        candidate["legal_first_name"], candidate["legal_last_name"])

    v = {
        "registration_id": reg["id"],
        "presented_first_name": body["presented_first_name"],
        "presented_last_name": body["presented_last_name"],
        "presented_id_state_code": body["presented_id_state_code"],
        "cross_state": cross_state,
        "outcome": outcome,
    }
    stamp_create(v)
    store.id_verifications[v["id"]] = v
    return object_response(serializers.id_verification(v), 201)
