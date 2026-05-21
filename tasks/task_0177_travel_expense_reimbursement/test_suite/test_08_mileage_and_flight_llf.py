"""Mileage and flight LLF calculations — including boundary precision
and per-leg rounding.

Covers PRD §3.9 (mileage + personal-car overlap), §3.11 (flight LLF),
and the difficulty-design instances:
  - combinatorial_formula.mileage_rental_overlap_three_input_nonlinear
  - combinatorial_formula.mileage_per_leg_rounding_order_pinned
  - boundary_precision_check.llf_variance_tolerance_inclusive_boundary
  - dual_variant_calc.flight_llf_forward_looking_vs_chronological
  - resource_temporal_overlap.per_diem_rate_effective_window_half_open
"""
from __future__ import annotations

import pytest

from test_helpers import (
    IRS_BUSINESS_RATE_CENTS,
    LLF_VARIANCE_TOLERANCE_CENTS,
    MILEAGE_OVERLAP_THRESHOLD,
    MILEAGE_PERSONAL_OVERLAP_RATE_CENTS,
    add_flight_line,
    add_mileage_line,
    approve_report,
    claim_report,
    create_expense_report,
    get_line,
    make_traveler_headers,
    seed_per_diem_rate,
    setup_approved_trip,
    setup_report_with_flight_line,
    setup_report_with_rental_then_mileage,
    setup_report_with_standalone_mileage,
    submit_report,
    upload_receipt,
    validate_error,
    validate_success,
)


# ===========================================================================
# Mileage standalone (no rental overlap) — PRD §3.9
# ===========================================================================
def test_mileage_standalone_uses_business_rate(api):
    """PRD §3.9: "When `miles_driven` is at most 30 — or when there is
    no same-date rental line — the full mileage is at 67 cents per mile,
    rounded half-up."

    10 miles * 67 = 670 cents.
    """
    cast = setup_report_with_standalone_mileage(miles_driven=10.0)
    assert cast["line"]["amount_reimbursable_cents"] == 670


def test_mileage_per_leg_round_half_up_at_half_cent_boundary(api):
    """PRD §3.9: "The IRS standard business rate baked into this
    calculation is 67 cents per mile. The calculation uses a
    per-leg-round-then-sum convention: each leg's cents value is
    computed (miles times rate), rounded half-up to integer cents".

    30.5 mi * 67c = 2043.5 → round_half_up → 2044, not 2043.
    # difficulty: combinatorial_formula/mileage_per_leg_rounding_order_pinned
    """
    cast = setup_report_with_standalone_mileage(miles_driven=30.5)
    assert cast["line"]["amount_reimbursable_cents"] == 2044


# ===========================================================================
# Mileage with rental overlap — three-input non-linear
# difficulty: combinatorial_formula/mileage_rental_overlap_three_input_nonlinear
# ===========================================================================
def test_mileage_with_same_date_rental_applies_personal_overlap_rate(api):
    """PRD §3.9: "when overlap applies and `miles_driven` is strictly
    greater than 30, the reimbursable amount is (the 30-mile threshold
    multiplied by 67 cents per mile, rounded half-up) plus
    ((`miles_driven` minus 30) multiplied by 21 cents per mile, rounded
    half-up)."

    80 mi with same-date rental: base = round(30*67) = 2010;
    excess = round(50*21) = 1050; total = 3060.
    # difficulty: combinatorial_formula/mileage_rental_overlap_three_input_nonlinear
    """
    cast = setup_report_with_rental_then_mileage(
        miles_driven=80.0, rental_amount_cents=5000, rental_days=1,
    )
    assert cast["mileage_line"]["amount_reimbursable_cents"] == 3060


def test_mileage_overlap_at_30_mile_boundary_no_excess(api):
    """PRD §3.9: "The first 30 round-trip miles are reimbursed at the
    standard business rate of 67 cents per mile; every mile beyond the
    30-mile threshold is reimbursed at the deeply discounted personal-
    overlap rate of 21 cents per mile". At exactly 30 miles, no excess
    fires.

    miles_driven = 30.0 → 30*67 = 2010, no excess.
    # difficulty: combinatorial_formula/mileage_rental_overlap_three_input_nonlinear
    """
    cast = setup_report_with_rental_then_mileage(
        miles_driven=30.0, rental_amount_cents=5000, rental_days=1,
    )
    assert cast["mileage_line"]["amount_reimbursable_cents"] == 2010


# ===========================================================================
# Flight LLF variance — boundary precision (inclusive)
# difficulty: boundary_precision_check/llf_variance_tolerance_inclusive_boundary
# ===========================================================================
def test_flight_variance_at_tolerance_is_in_policy(api):
    """PRD §3.11: "When the variance is at most 10000 cents (one hundred
    dollars), the line is `IN_POLICY` and `amount_reimbursable_cents`
    equals `amount_claimed_cents` — the traveler is reimbursed the full
    claim."

    Boston LLF = 28800 + 8000 = 36800. variance == 10000 exactly:
    claim = 46800. The PRD threshold is "at most 10000" — inclusive.
    # difficulty: boundary_precision_check/llf_variance_tolerance_inclusive_boundary
    """
    cast = setup_report_with_flight_line(amount_claimed_cents=46800)
    assert cast["line"]["policy_status"] == "IN_POLICY"
    assert cast["line"]["amount_reimbursable_cents"] == 46800


def test_flight_variance_one_above_tolerance_is_out_of_policy(api):
    """PRD §3.11: "When the variance is strictly greater than 10000
    cents, the line is `OUT_OF_POLICY` and `amount_reimbursable_cents`
    is capped at the LLF (the lodging plus M&IE cap sum), pending OOP
    approval".

    claim = 46801, variance = 10001 → OUT_OF_POLICY, capped at 36800.
    # difficulty: boundary_precision_check/llf_variance_tolerance_inclusive_boundary
    """
    cast = setup_report_with_flight_line(amount_claimed_cents=46801)
    assert cast["line"]["policy_status"] == "OUT_OF_POLICY"
    assert cast["line"]["amount_reimbursable_cents"] == 36800


def test_flight_well_below_llf_is_in_policy_full_reimbursement(api):
    """PRD §3.11: "the traveler is reimbursed the full claim" when
    variance is at most 10000 cents."""
    cast = setup_report_with_flight_line(amount_claimed_cents=20000)
    assert cast["line"]["policy_status"] == "IN_POLICY"
    assert cast["line"]["amount_reimbursable_cents"] == 20000


# ===========================================================================
# Flight LLF — forward-looking vs chronological (provisional vs final)
# difficulty: dual_variant_calc/flight_llf_forward_looking_vs_chronological
# ===========================================================================
def test_flight_llf_forward_looking_vs_chronological_diverges_after_approval(
    api,
):
    """PRD §3.11: "The forward-looking variant fires during line creation
    and edit, pinning the variance against the `PerDiemRate` that is
    live at the flight's `expense_date`; it is never updated by later
    rate edits. The chronological variant fires at report approval and
    replays the variance against `Trip.pinned_per_diem_rate_id`, which
    was frozen at trip approval — and not at the flight line's
    `expense_date`. The two variants diverge whenever the line's
    `expense_date` falls in a different rate window than the trip's
    `start_date`".

    Setup: two adjacent rate rows for Boston MA, trip spans both
    windows; flight line's expense_date sits in the second window.
    # difficulty: dual_variant_calc/flight_llf_forward_looking_vs_chronological
    """
    # Cheaper R1 for the trip's start; richer R2 for the flight date.
    seed_per_diem_rate(
        city="Boston", state="MA",
        effective_from="2025-06-01T00:00:00.000Z",
        effective_to="2025-07-01T00:00:00.000Z",
        lodging_cap_cents=28800, mie_cap_cents=8000,
    )
    seed_per_diem_rate(
        city="Boston", state="MA",
        effective_from="2025-07-01T00:00:00.000Z",
        effective_to="2025-08-01T00:00:00.000Z",
        lodging_cap_cents=40000, mie_cap_cents=10000,
    )
    cast = setup_approved_trip(
        start_date="2025-06-29T00:00:00.000Z",
        end_date="2025-07-03T00:00:00.000Z",
        extra_rate_kwargs=None,
    )
    # Pinned rate at trip approval was R1 (rate live at start_date).
    # The flight's expense_date falls inside R2's window where LLF=50000.
    # Claim 55000 → forward-looking variance = 55000-50000 = 5000 ≤ tol
    # → IN_POLICY at create time.
    rpt = create_expense_report(
        trip=cast["trip"], traveler=cast["traveler"],
    )
    receipt = upload_receipt(
        uploader=cast["traveler"], merchant_total_cents=55000,
        ocr_extracted_date="2025-07-02T00:00:00.000Z",
    )
    line = add_flight_line(
        report=rpt, traveler=cast["traveler"],
        expense_date="2025-07-02T00:00:00.000Z",
        amount_claimed_cents=55000, receipt_id=receipt["id"],
    )
    assert line["policy_status"] == "IN_POLICY"
    assert line["amount_reimbursable_cents"] == 55000

    submit_report(report=rpt, traveler=cast["traveler"])
    rpt = claim_report(report=rpt, finance=cast["finance"])
    rpt = approve_report(report=rpt, finance=cast["finance"])

    # After approval, the chronological variant replays against R1
    # (lodging 28800 + mie 8000 = 36800). variance = 55000 - 36800 =
    # 18200 > 10000 → OUT_OF_POLICY, reimbursable capped at 36800.
    line_after = get_line(line["id"], viewer=cast["finance"])
    assert line_after["policy_status"] == "OUT_OF_POLICY"
    assert line_after["amount_reimbursable_cents"] == 36800


# ===========================================================================
# Half-open per-diem effective window
# difficulty: resource_temporal_overlap/per_diem_rate_effective_window_half_open
# ===========================================================================
def test_per_diem_window_includes_effective_from(api):
    """PRD §3.1: "the window is inclusive on the left of `effective_from`
    and exclusive on the right of `effective_to`."

    Trip starts EXACTLY at effective_from → submit succeeds.
    # difficulty: resource_temporal_overlap/per_diem_rate_effective_window_half_open
    """
    import uuid
    from test_helpers import (
        create_draft_trip, seed_standard_cast, submit_trip,
    )
    city = f"WindowCity-{uuid.uuid4().hex[:6]}"
    cast = seed_standard_cast(seed_rate=False)
    rate = seed_per_diem_rate(
        city=city, state="MA",
        effective_from="2025-06-01T00:00:00.000Z",
        effective_to="2025-07-01T00:00:00.000Z",
        lodging_cap_cents=28800, mie_cap_cents=8000,
    )
    trip = create_draft_trip(
        traveler=cast["traveler"],
        destination_city=city, destination_state="MA",
        start_date="2025-06-01T00:00:00.000Z",
        end_date="2025-06-03T00:00:00.000Z",
    )
    submitted = submit_trip(trip, cast["traveler"])
    assert submitted["status"] == "SUBMITTED"


def test_per_diem_window_excludes_effective_to(api):
    """PRD §3.1: "exclusive on the right of `effective_to`. If no such
    rate row exists, submission fails with `ERR_PER_DIEM_UNAVAILABLE`."

    Trip starts EXACTLY at effective_to → no rate covers that instant
    → ERR_PER_DIEM_UNAVAILABLE.
    # difficulty: resource_temporal_overlap/per_diem_rate_effective_window_half_open
    """
    import uuid
    from test_helpers import (
        create_draft_trip, seed_standard_cast,
    )
    # Use a unique destination city so previously-seeded Boston rates
    # from other tests in the suite can't accidentally cover the gap
    # this test is probing.
    city = f"WindowCity-{uuid.uuid4().hex[:6]}"
    cast = seed_standard_cast(seed_rate=False)
    seed_per_diem_rate(
        city=city, state="MA",
        effective_from="2025-06-01T00:00:00.000Z",
        effective_to="2025-07-01T00:00:00.000Z",
        lodging_cap_cents=28800, mie_cap_cents=8000,
    )
    trip = create_draft_trip(
        traveler=cast["traveler"],
        destination_city=city, destination_state="MA",
        start_date="2025-07-01T00:00:00.000Z",
        end_date="2025-07-03T00:00:00.000Z",
    )
    res = api.submit_trip(
        trip["id"], make_traveler_headers(cast["traveler"]["id"]),
    )
    validate_error(res, "ERR_PER_DIEM_UNAVAILABLE")
