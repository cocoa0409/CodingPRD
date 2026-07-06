"""Response capture preconditions and the fraud-score calculation, including the
fraud_score >= threshold boundary.

Translates queue-A combinatorial_formula (fraud-score leg) and
boundary_precision_check (fraud-threshold leg); and queue-B validation instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    make_enumerator_headers,
    TEST_USERS,
    create_response_payload,
    assert_response,
    setup_assigned_case,
    setup_case_with_contact_made,
    log_attempt,
)

ADMIN = TEST_USERS["survey_admin_headers"]


# ── combinatorial_formula: fraud_score_nonlinear_multi_input ──────────────────

def test_fraud_score_combines_flags_gps_and_duration(api):
    """PRD §3.7: "It begins from a base of 12 points for each flagged answer. A GPS
    component applies only to in-person captures: when `mode` is `IN_PERSON`, take
    the response's `gps_variance_meters`, subtract a tolerance of 50 meters, divide
    the remainder by 10, round up to the next whole number, and take the greater of
    that and zero, then multiply by 5 points per step; when `mode` is `PHONE`, the
    GPS component is zero. A short-duration penalty of 25 points applies when
    `duration_minutes` is below 8, and is zero otherwise. The raw score is the sum
    of the flagged-answer base, the GPS component, and the short-duration penalty,
    and the final `fraud_score` is that raw sum clamped into the range 0 through
    100 — never below 0 and never above 100."
    PRD §3.7: "The response's `needs_reinterview` flag is set true when its
    `fraud_score` is at or above the project's `fraud_score_threshold`, and false
    otherwise."

    IN_PERSON, flagged 3 (36) + gps 90 (ceil((90-50)/10)*5 = 20) + duration 5 (25)
    = 81; threshold 60 -> needs_reinterview true.

    Design: Difficulty/combinatorial_formula/fraud_score_nonlinear_multi_input
    """
    ctx = setup_case_with_contact_made(fraud_score_threshold=60)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_response(
        ctx["case"]["id"],
        create_response_payload(mode="IN_PERSON", language_used="EN", duration_minutes=5,
                                flagged_answer_count=3, gps_variance_meters=90),
        en_headers)
    resp = validate_success(res, 201)
    assert resp["fraud_score"] == 81
    assert resp["needs_reinterview"] is True
    assert_response(resp)


def test_fraud_score_phone_capture_drops_gps_component(api):
    """PRD §3.7: "A GPS component applies only to in-person captures: when `mode`
    is `IN_PERSON`, take the response's `gps_variance_meters`, subtract a tolerance
    of 50 meters, divide the remainder by 10, round up to the next whole number,
    and take the greater of that and zero, then multiply by 5 points per step; when
    `mode` is `PHONE`, the GPS component is zero. A short-duration penalty of 25
    points applies when `duration_minutes` is below 8, and is zero otherwise."

    PHONE with the same inputs (flagged 3, duration 5, gps 90): 36 + 0 + 25 = 61
    because the GPS geometry is dropped for phone captures.

    Design: Difficulty/combinatorial_formula/fraud_score_nonlinear_multi_input
    """
    ctx = setup_case_with_contact_made(fraud_score_threshold=60)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_response(
        ctx["case"]["id"],
        create_response_payload(mode="PHONE", language_used="EN", duration_minutes=5,
                                flagged_answer_count=3, gps_variance_meters=90),
        en_headers)
    resp = validate_success(res, 201)
    assert resp["fraud_score"] == 61


# ── boundary_precision_check: fraud_threshold_exact_ge ────────────────────────

def test_fraud_score_exactly_at_threshold_flags_reinterview(api):
    """PRD §3.7: "The response's `needs_reinterview` flag is set true when its
    `fraud_score` is at or above the project's `fraud_score_threshold`, and false
    otherwise."

    PHONE, flagged 5 -> score exactly 60 == threshold 60 -> needs_reinterview true
    (the >= boundary).

    Design: Difficulty/boundary_precision_check/fraud_threshold_exact_ge
    """
    ctx = setup_case_with_contact_made(fraud_score_threshold=60)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_response(
        ctx["case"]["id"],
        create_response_payload(mode="PHONE", language_used="EN", duration_minutes=20,
                                flagged_answer_count=5, gps_variance_meters=0),
        en_headers)
    resp = validate_success(res, 201)
    assert resp["fraud_score"] == 60
    assert resp["needs_reinterview"] is True


def test_fraud_score_below_threshold_does_not_flag(api):
    """PRD §3.7: "The response's `needs_reinterview` flag is set true when its
    `fraud_score` is at or above the project's `fraud_score_threshold`, and false
    otherwise."

    PHONE, flagged 4 -> score 48 < threshold 60 -> needs_reinterview false (the
    boundary neighbour just below the threshold).

    Design: Difficulty/boundary_precision_check/fraud_threshold_exact_ge
    """
    ctx = setup_case_with_contact_made(fraud_score_threshold=60)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_response(
        ctx["case"]["id"],
        create_response_payload(mode="PHONE", language_used="EN", duration_minutes=20,
                                flagged_answer_count=4, gps_variance_meters=0),
        en_headers)
    resp = validate_success(res, 201)
    assert resp["fraud_score"] == 48
    assert resp["needs_reinterview"] is False


# ── queue-B: response preconditions ───────────────────────────────────────────

def test_response_without_contact_made_rejected(api):
    """PRD §3.7: "only when the case already has at least one LOGGED attempt whose
    disposition is `CONTACT_MADE` (otherwise `ERR_NO_CONTACT_MADE`), and only when
    `language_used` is one of the capturing enumerator's `languages` (otherwise
    `ERR_LANGUAGE_NOT_SUPPORTED`)."

    Design: Corner/validations/response_without_contact_made_returns_error
    """
    # A case whose only LOGGED attempt is NO_ONE_HOME — no CONTACT_MADE exists.
    ctx = setup_assigned_case()
    en_id = ctx["enumerator"]["id"]
    log_attempt(ctx["case"]["id"], en_id, mode="PHONE",
                window_start="2026-03-01T10:00:00Z", window_end="2026-03-01T10:30:00Z",
                disposition="NO_ONE_HOME")
    res = api.create_response(
        ctx["case"]["id"],
        create_response_payload(mode="PHONE", language_used="EN", duration_minutes=20,
                                flagged_answer_count=0, gps_variance_meters=0),
        make_enumerator_headers(en_id))
    validate_error(res, "ERR_NO_CONTACT_MADE", expected_status=409)


def test_response_language_not_in_enumerator_languages_rejected(api):
    """PRD §3.7: "only when `language_used` is one of the capturing enumerator's
    `languages` (otherwise `ERR_LANGUAGE_NOT_SUPPORTED`)."

    Design: Corner/validations/response_language_not_in_enumerator_languages_returns_error
    """
    ctx = setup_case_with_contact_made(supported_languages=("EN", "ES"), enum_languages=("EN",))
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_response(
        ctx["case"]["id"],
        create_response_payload(mode="IN_PERSON", language_used="ES", duration_minutes=20,
                                flagged_answer_count=0, gps_variance_meters=0),
        en_headers)
    validate_error(res, "ERR_LANGUAGE_NOT_SUPPORTED", expected_status=422)
