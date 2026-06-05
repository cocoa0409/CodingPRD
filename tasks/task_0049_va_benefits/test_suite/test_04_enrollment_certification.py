"""Enrollment certification, term overlap, Yellow Ribbon conservation.

Difficulty queue: resource_temporal_overlap, compensating_invariant (YR slot
pool), boundary_precision (rop floor at 50). Corner queue: enrollment state-machine
and YR validation instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_veteran_headers,
    create_veteran,
    create_school,
    submit_enrollment,
    certify_enrollment,
)
from test_helpers import api_client  # noqa: F401

ADMIN = TEST_USERS["claims_admin_headers"]
SCO = TEST_USERS["school_official_headers"]


# ─── resource_temporal_overlap / enrollment_overlap_strict_interior_overlap ─

def test_certify_overlapping_term_rejected(api):
    """PRD §3.12: "There must be no scheduling collision: no other `CERTIFIED`
    enrollment for the same veteran may have a term interval that overlaps this
    one, failing otherwise with `ERR_ENROLLMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/enrollment_overlap_strict_interior_overlap
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(monthly_housing_rate_cents=200000)
    enr1 = submit_enrollment(
        vet["id"], school["id"],
        term_start="2026-08-20T00:00:00Z", term_end="2026-12-15T00:00:00Z",
        credit_hours=12, full_time_credit_hours=12,
    )
    certify_enrollment(enr1)
    enr2 = submit_enrollment(
        vet["id"], school["id"],
        term_start="2026-10-01T00:00:00Z", term_end="2027-02-01T00:00:00Z",
        credit_hours=12, full_time_credit_hours=12,
    )
    res = api.certify_enrollment(
        enr2["id"], {"expected_enrollment_version": enr2["version"]}, SCO
    )
    validate_error(res, "ERR_ENROLLMENT_OVERLAP", 409)


def test_certify_overlap_leaves_second_submitted(api):
    """PRD §3.12: "an overlap exists only when the intervals genuinely share
    interior time."
    PRD §3.12: "The enrollment must be in `SUBMITTED` status, or the request is
    rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/resource_temporal_overlap/enrollment_overlap_strict_interior_overlap
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(monthly_housing_rate_cents=200000)
    enr1 = submit_enrollment(
        vet["id"], school["id"],
        term_start="2026-08-20T00:00:00Z", term_end="2026-12-15T00:00:00Z",
        credit_hours=12, full_time_credit_hours=12,
    )
    certify_enrollment(enr1)
    enr2 = submit_enrollment(
        vet["id"], school["id"],
        term_start="2026-10-01T00:00:00Z", term_end="2027-02-01T00:00:00Z",
        credit_hours=12, full_time_credit_hours=12,
    )
    api.certify_enrollment(
        enr2["id"], {"expected_enrollment_version": enr2["version"]}, SCO
    )
    still = validate_success(api.get_enrollment(enr2["id"], ADMIN), 200)
    assert still["status"] == "SUBMITTED", (
        f"rejected overlap leaves enrollment SUBMITTED, got {still['status']}"
    )


# ─── resource_temporal_overlap / enrollment_touching_endpoints_no_overlap ──

def test_certify_touching_terms_succeeds(api):
    """PRD §3.12: "Term overlap is judged on half-open intervals. The term spans
    from `term_start` inclusive to `term_end` exclusive, so two terms that merely
    touch — one ending exactly when the next begins — do not overlap and do not
    collide; an overlap exists only when the intervals genuinely share interior
    time."

    Design: Difficulty/resource_temporal_overlap/enrollment_touching_endpoints_no_overlap
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(monthly_housing_rate_cents=200000)
    enr1 = submit_enrollment(
        vet["id"], school["id"],
        term_start="2026-01-10T00:00:00Z", term_end="2026-05-10T00:00:00Z",
        credit_hours=12, full_time_credit_hours=12,
    )
    certify_enrollment(enr1)
    enr2 = submit_enrollment(
        vet["id"], school["id"],
        term_start="2026-05-10T00:00:00Z", term_end="2026-08-10T00:00:00Z",
        credit_hours=12, full_time_credit_hours=12,
    )
    certified = validate_success(
        api.certify_enrollment(
            enr2["id"], {"expected_enrollment_version": enr2["version"]}, SCO
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED", (
        f"touching endpoints (gap=0) do not overlap, got {certified['status']}"
    )


def test_touching_terms_distinct_from_overlap(api):
    """PRD §3.12: "two terms that merely touch — one ending exactly when the next
    begins — do not overlap and do not collide".

    Design: Difficulty/resource_temporal_overlap/enrollment_touching_endpoints_no_overlap
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(monthly_housing_rate_cents=200000)
    enr1 = submit_enrollment(
        vet["id"], school["id"],
        term_start="2026-01-10T00:00:00Z", term_end="2026-05-10T00:00:00Z",
        credit_hours=12, full_time_credit_hours=12,
    )
    certify_enrollment(enr1)
    enr2 = submit_enrollment(
        vet["id"], school["id"],
        term_start="2026-05-10T00:00:00Z", term_end="2026-08-10T00:00:00Z",
        credit_hours=12, full_time_credit_hours=12,
    )
    res = api.certify_enrollment(
        enr2["id"], {"expected_enrollment_version": enr2["version"]}, SCO
    )
    assert res.status_code == 200, (
        f"adjacent term certifies; expected 200, got {res.status_code}"
    )


# ─── compensating_invariant / enrollment_cancel_restores_yellow_ribbon_slots ─

def test_yellow_ribbon_slot_consumed_on_certify(api):
    """PRD §3.12: "If a Yellow Ribbon slot was granted, the enrollment's
    `yellow_ribbon_match_cents` is computed via the Yellow Ribbon match
    calculation and the school's `yellow_ribbon_slots_used` is increased by one."
    PRD §3.12: "the VA matches the school's contribution dollar-for-dollar, so the
    `yellow_ribbon_match_cents` stored on the enrollment equals that rounded
    school contribution."

    Design: Difficulty/compensating_invariant/enrollment_cancel_restores_yellow_ribbon_slots
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(
        is_public=False, monthly_housing_rate_cents=200000,
        yellow_ribbon_participant=True,
        yellow_ribbon_max_contribution_cents=300000,
        yellow_ribbon_slots_total=1,
    )
    enr = submit_enrollment(
        vet["id"], school["id"],
        credit_hours=12, full_time_credit_hours=12,
        tuition_charged_cents=400000, requests_yellow_ribbon=True,
    )
    certified = certify_enrollment(enr)
    school_after = validate_success(api.get_school(school["id"], ADMIN), 200)
    assert school_after["yellow_ribbon_slots_used"] == 1, (
        f"slots_used should be 1 after certify, got {school_after['yellow_ribbon_slots_used']}"
    )
    # half of 400000 = 200000 < cap 300000 -> match 200000.
    assert certified["yellow_ribbon_match_cents"] == 200000, (
        f"YR match should be 200000, got {certified['yellow_ribbon_match_cents']}"
    )


def test_cancel_restores_yellow_ribbon_slot(api):
    """PRD §3.13: "Cancelling from `CERTIFIED` is a compensating action: the
    enrollment moves to `CANCELLED`, its `monthly_housing_allowance_cents` is
    reset to 0, and — if a Yellow Ribbon slot had been consumed, meaning its
    `yellow_ribbon_match_cents` is greater than 0 — the school's
    `yellow_ribbon_slots_used` is decreased by one and the enrollment's
    `yellow_ribbon_match_cents` is reset to 0, restoring the conserved slot to the
    school's pool."

    Design: Difficulty/compensating_invariant/enrollment_cancel_restores_yellow_ribbon_slots
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(
        is_public=False, monthly_housing_rate_cents=200000,
        yellow_ribbon_participant=True,
        yellow_ribbon_max_contribution_cents=300000,
        yellow_ribbon_slots_total=1,
    )
    enr = submit_enrollment(
        vet["id"], school["id"],
        credit_hours=12, full_time_credit_hours=12,
        tuition_charged_cents=400000, requests_yellow_ribbon=True,
    )
    certify_enrollment(enr)
    get_success_data(api.cancel_enrollment(enr["id"], make_veteran_headers(vet["id"])))
    school_after = validate_success(api.get_school(school["id"], ADMIN), 200)
    assert school_after["yellow_ribbon_slots_used"] == 0, (
        f"slot restored to 0 after cancel, got {school_after['yellow_ribbon_slots_used']}"
    )
    enr_after = validate_success(api.get_enrollment(enr["id"], ADMIN), 200)
    assert enr_after["yellow_ribbon_match_cents"] == 0, (
        f"YR match zeroed on cancel, got {enr_after['yellow_ribbon_match_cents']}"
    )


# ─── boundary_precision_check / rate_of_pursuit_floor_exactly_50_pays_zero ──

def test_rate_of_pursuit_exactly_50_pays_zero(api):
    """PRD §3.11: "The housing allowance is paid only when the rate of pursuit is
    strictly greater than fifty percent; at exactly fifty or below, the allowance
    is zero."

    Design: Difficulty/boundary_precision_check/rate_of_pursuit_floor_exactly_50_pays_zero
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=6, full_time_credit_hours=12
    )
    certified = validate_success(
        api.certify_enrollment(
            enr["id"], {"expected_enrollment_version": enr["version"]}, SCO
        ),
        200,
    )
    assert certified["rate_of_pursuit_pct"] == 50, (
        f"6/12 -> rop 50, got {certified['rate_of_pursuit_pct']}"
    )
    assert certified["monthly_housing_allowance_cents"] == 0, (
        f"rop exactly 50 pays 0, got {certified['monthly_housing_allowance_cents']}"
    )


def test_rate_of_pursuit_floor_is_strict(api):
    """PRD §3.11: "The housing allowance is paid only when the rate of pursuit is
    strictly greater than fifty percent; at exactly fifty or below, the allowance
    is zero."

    Design: Difficulty/boundary_precision_check/rate_of_pursuit_floor_exactly_50_pays_zero
    """
    vet = create_veteran(total_active_duty_days=1200)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=6, full_time_credit_hours=12
    )
    certified = certify_enrollment(enr)
    assert certified["monthly_housing_allowance_cents"] == 0


# ─── Corner / state_machines (Enrollment) ─────────────────────────────────

def test_cancel_submitted_enrollment_no_side_effects(api):
    """PRD §3.13: "Cancelling from `SUBMITTED` simply moves it to `CANCELLED`
    with no compensation effects."

    Design: Corner/state_machines/enrollment_cancel_from_submitted_no_side_effects
    """
    vet = create_veteran(total_active_duty_days=1095)
    school = create_school(monthly_housing_rate_cents=200000)
    enr = submit_enrollment(
        vet["id"], school["id"], credit_hours=12, full_time_credit_hours=12
    )
    cancelled = validate_success(
        api.cancel_enrollment(enr["id"], make_veteran_headers(vet["id"])), 200
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["monthly_housing_allowance_cents"] == 0


# ─── Corner / validations (Yellow Ribbon) ─────────────────────────────────

def test_yellow_ribbon_unavailable_nonparticipating_school(api):
    """PRD §3.12: "If this enrollment `requests_yellow_ribbon`, the school must be
    a Yellow Ribbon participant and must still have an open slot — its
    `yellow_ribbon_slots_used` strictly below its `yellow_ribbon_slots_total` —
    failing otherwise with `ERR_YELLOW_RIBBON_UNAVAILABLE`."

    Design: Corner/validations/yellow_ribbon_unavailable_nonparticipating_school
    """
    vet = create_veteran(total_active_duty_days=1095)
    school = create_school(monthly_housing_rate_cents=200000)  # not YR participant
    enr = submit_enrollment(
        vet["id"], school["id"],
        credit_hours=12, full_time_credit_hours=12,
        tuition_charged_cents=400000, requests_yellow_ribbon=True,
    )
    res = api.certify_enrollment(
        enr["id"], {"expected_enrollment_version": enr["version"]}, SCO
    )
    validate_error(res, "ERR_YELLOW_RIBBON_UNAVAILABLE", 409)
