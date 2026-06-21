"""Tests covering temporal-overlap semantics:
- EligibilityDetermination uses half-open windows; adjacency allowed.
- ReimbursementClaim uses closed intervals with a 1-day gap; adjacency rejected.
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    create_household,
    create_direct_cert_eligibility,
    create_reimbursement_claim,
    api_client,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Difficulty rule 8 / instance 1 — eligibility half-open windows.
# ---------------------------------------------------------------------

def test_eligibility_determination_interior_overlap_returns_overlap_error(api):
    """PRD §3.4: "No two `EligibilityDetermination` rows for the same
    `household_id` may have overlapping windows; because the windows are
    half-open at `valid_to_utc`, two windows that touch at exactly one
    instant (the earlier's `valid_to_utc` equals the later's
    `valid_from_utc`) are adjacent and allowed. A creation that would produce
    an overlap is rejected with `ERR_ELIGIBILITY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/eligibility_determinations_half_open_no_adjacency_buffer
    """
    set_clock("2026-01-05T00:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-03-01T00:00:00.000Z",
    )
    # Attempt B with interior overlap [02-15, 04-01) overlaps [01-01, 03-01).
    res = api.create_eligibility_determination(
        {
            "household_id": hh["id"],
            "source": "DIRECT_CERTIFICATION",
            "tier": "FREE",
            "valid_from_utc": "2026-02-15T00:00:00.000Z",
            "valid_to_utc": "2026-04-01T00:00:00.000Z",
        },
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_ELIGIBILITY_OVERLAP", expected_status=409)


def test_eligibility_determination_adjacent_at_exact_boundary_is_allowed(api):
    """PRD §3.4: "because the windows are half-open at `valid_to_utc`, two
    windows that touch at exactly one instant (the earlier's `valid_to_utc`
    equals the later's `valid_from_utc`) are adjacent and allowed."
    PRD §2.7: "Validity windows on an `EligibilityDetermination` are
    half-open: the window is inclusive at `valid_from_utc` and exclusive at
    `valid_to_utc`. Two consecutive determinations for the same household
    whose windows touch at a single instant (one ends at exactly the instant
    the next begins) are considered adjacent, not overlapping."

    Design: Difficulty/resource_temporal_overlap/eligibility_determinations_half_open_no_adjacency_buffer
    """
    set_clock("2026-01-05T00:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-03-01T00:00:00.000Z",
    )
    # B starts at the EXACT instant A ends — adjacency MUST be allowed.
    res = api.create_eligibility_determination(
        {
            "household_id": hh["id"],
            "source": "DIRECT_CERTIFICATION",
            "tier": "FREE",
            "valid_from_utc": "2026-03-01T00:00:00.000Z",
            "valid_to_utc": "2026-06-01T00:00:00.000Z",
        },
        TEST_USERS["school_staff_headers"],
    )
    validate_success(res, 201)


# ---------------------------------------------------------------------
# Difficulty rule 8 / instance 2 — reimbursement claim closed intervals with
# 1-day gap; adjacency at boundary rejected.
# ---------------------------------------------------------------------

def test_reimbursement_claim_adjacent_without_one_day_gap_returns_overlap_error(api):
    """PRD §3.7: "Two claims for the same `school_code` may not overlap in
    time, and consecutive claim periods must be separated by a gap of at
    least one calendar day — that is, the new claim's `period_start_utc`
    must be at or after the prior claim's `period_end_utc` plus one day. A
    creation that would overlap or close the gap is rejected with
    `ERR_CLAIM_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/reimbursement_claims_closed_intervals_with_one_day_gap_buffer
    """
    set_clock("2026-02-15T00:00:00.000Z")
    create_reimbursement_claim(
        "ELEM-101",
        "2026-01-01T00:00:00.000Z",
        "2026-01-31T23:59:59.000Z",
        accounting_basis="CASH",
    )
    # B starts 2026-02-01 — less than 1 calendar day after the prior end.
    res = api.create_reimbursement_claim(
        {
            "school_code": "ELEM-101",
            "period_start_utc": "2026-02-01T00:00:00.000Z",
            "period_end_utc": "2026-02-28T23:59:59.000Z",
            "accounting_basis": "CASH",
        },
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_CLAIM_PERIOD_OVERLAP", expected_status=409)


def test_reimbursement_claim_interior_overlap_returns_overlap_error(api):
    """PRD §3.7: "Two claims for the same `school_code` may not overlap in
    time".

    Design: Difficulty/resource_temporal_overlap/reimbursement_claims_closed_intervals_with_one_day_gap_buffer
    """
    set_clock("2026-02-15T00:00:00.000Z")
    create_reimbursement_claim(
        "ELEM-101",
        "2026-01-01T00:00:00.000Z",
        "2026-01-31T23:59:59.000Z",
        accounting_basis="CASH",
    )
    # B starts inside the prior period — overlap interior.
    res = api.create_reimbursement_claim(
        {
            "school_code": "ELEM-101",
            "period_start_utc": "2026-01-15T00:00:00.000Z",
            "period_end_utc": "2026-02-15T23:59:59.000Z",
            "accounting_basis": "CASH",
        },
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_CLAIM_PERIOD_OVERLAP", expected_status=409)
