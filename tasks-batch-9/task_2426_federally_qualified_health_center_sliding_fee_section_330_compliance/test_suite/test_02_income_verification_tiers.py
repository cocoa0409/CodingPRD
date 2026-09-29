"""The two federal-poverty-guideline percentages and the half-open band ladder."""

import pytest

from test_helpers import (
    VERIFIER,
    api_client,
    refresh_patient,
    same_instant,
    setup_boot_fs,
    setup_grantee_with_adopted_schedule,
    setup_income_verification,
    setup_patient,
    validate_success,
    verify_income_verification_payload,
)


def _verify(income_verification_id):
    return validate_success(
        api_client.verify_income_verification(
            income_verification_id, verify_income_verification_payload("VERIFY"), VERIFIER
        )
    )


def _lakeside_with_a_2025_year_schedule():
    """A grantee whose adopted 2026 period was built from the 2025 guideline year."""
    ctx = setup_grantee_with_adopted_schedule(
        legal_name="Lakeside Family Health",
        grant_number="H80CS00427",
        site_name="Lakeside Main",
        fpg_year=2025,
    )
    patient = setup_patient(mrn="MRN-101", full_name="Cora Diaz", household_size=2)
    verification = setup_income_verification(
        patient,
        declared_annual_income_cents=2150000,
        household_size=2,
        documentation_type="TAX_RETURN",
        effective_date="2026-03-01T00:00:00Z",
    )
    ctx.update({"patient": patient, "verification": verification})
    return ctx


def test_schedule_year_percentage_drives_the_tier_from_the_schedules_own_fpg_year():
    """The money-bearing percentage reads the adopted schedule's fpg_year, not the visit year.

    PRD 3.4: "The **schedule-year** variant is the one that drives money. Its year
    is the `fpg_year` of the adopted fee schedule that covers the verification's
    `effective_date` for that patient's grantee — that is, the year the adopted
    sliding fee schedule's bands were actually built from, *not* the calendar year
    of the visit." PRD 3.4 also states: "Its result is written to `fpg_percent` and
    the year it used is recorded in `guideline_year_used`."

    Design: Difficulty/dual_variant_calc/fpg_percent_schedule_year_vs_intake_year_divergence
    """
    ctx = _lakeside_with_a_2025_year_schedule()

    verified = _verify(ctx["verification"]["id"])

    assert verified["status"] == "VERIFIED"
    assert verified["guideline_year_used"] == 2025, (
        "the schedule-year variant reads the adopted schedule's fpg_year of 2025, "
        f"got {verified['guideline_year_used']}"
    )
    assert verified["fpg_percent"] == pytest.approx(101.90, abs=0.01), (
        "2150000 against the 2025 guideline amount for a household of two is "
        f"101.90 percent, got {verified['fpg_percent']}"
    )
    assert verified["assigned_tier_label"] == "PARTIAL_A", (
        "101.90 percent lands in the band that starts at 100, got "
        f"{verified['assigned_tier_label']}"
    )
    assert (
        verified["assigned_discount_tier_id"] == ctx["tiers_by_label"]["PARTIAL_A"]["id"]
    ), "the assigned tier belongs to the adopted schedule that covers effective_date"


def test_intake_year_percentage_reads_the_calendar_year_and_diverges_from_the_money_variant():
    """The reporting percentage reads the visit's calendar year on the same row.

    PRD 3.4: "The **intake-year** variant is the one that drives reporting. Its
    year is simply the UTC calendar year of the verification's `effective_date`."
    PRD 3.4 continues: "Because an adopted schedule commonly lags the calendar
    year, the same verification often yields one percentage for tier assignment and
    a different percentage for the annual report"

    Design: Difficulty/dual_variant_calc/fpg_percent_schedule_year_vs_intake_year_divergence
    """
    ctx = _lakeside_with_a_2025_year_schedule()

    verified = _verify(ctx["verification"]["id"])

    assert verified["uds_guideline_year_used"] == 2026, (
        "the intake-year variant reads the calendar year of effective_date, got "
        f"{verified['uds_guideline_year_used']}"
    )
    assert verified["uds_fpg_percent"] == pytest.approx(98.17, abs=0.01), (
        "2150000 against the 2026 guideline amount for a household of two is "
        f"98.17 percent, got {verified['uds_fpg_percent']}"
    )
    assert verified["uds_fpg_percent"] != verified["fpg_percent"], (
        "the two variants run over the same row and differ only in the guideline "
        "year they read, so they disagree here"
    )


def _two_patients_awaiting_adjudication():
    """One income exactly at the guideline amount, one a hair below it."""
    ctx = setup_boot_fs()
    at_edge = setup_patient(mrn="MRN-001", full_name="Ada Rivera", household_size=2)
    at_edge_verification = setup_income_verification(
        at_edge,
        declared_annual_income_cents=2190000,
        household_size=2,
        documentation_type="TAX_RETURN",
        effective_date="2026-02-01T00:00:00Z",
    )
    below_edge = setup_patient(mrn="MRN-002", full_name="Bo Nkemi", household_size=2)
    below_edge_verification = setup_income_verification(
        below_edge,
        declared_annual_income_cents=2188000,
        household_size=2,
        documentation_type="PAY_STUBS",
        effective_date="2026-02-01T00:00:00Z",
    )
    ctx.update(
        {
            "at_edge": at_edge,
            "at_edge_verification": at_edge_verification,
            "below_edge": below_edge,
            "below_edge_verification": below_edge_verification,
        }
    )
    return ctx


def test_fpg_percent_of_exactly_100_lands_in_the_band_that_starts_at_100():
    """The half-open band rule sends the edge value upward, never downward.

    PRD 3.4: "The half-open band convention has a consequence that must not be
    smoothed over: a `fpg_percent` of exactly 100.00 lands in the band that
    *starts* at 100 — the partial-discount band of a typical ladder — and never in
    the full-discount band that ends there."

    Design: Difficulty/boundary_precision_check/fpg_percent_exactly_at_band_edge_assigns_the_upper_tier
    """
    ctx = _two_patients_awaiting_adjudication()

    verified = _verify(ctx["at_edge_verification"]["id"])

    assert verified["fpg_percent"] == pytest.approx(100.00, abs=0.01), (
        "an income equal to the guideline amount is exactly 100.00 percent, got "
        f"{verified['fpg_percent']}"
    )
    assert verified["assigned_tier_label"] == "PARTIAL_A", (
        "exactly 100.00 belongs to the band starting at 100, got "
        f"{verified['assigned_tier_label']}"
    )
    assert (
        verified["assigned_discount_tier_id"] == ctx["tiers_by_label"]["PARTIAL_A"]["id"]
    )
    assert verified["uds_fpg_percent"] == pytest.approx(100.00, abs=0.01)
    assert refresh_patient(ctx["at_edge"]["id"])["sliding_fee_status"] == "VERIFIED"


def test_fpg_percent_just_below_the_edge_stays_in_the_nominal_band_and_expires_after_365_days():
    """A hair below the edge keeps the deepest discount, and the window is closed.

    PRD 3.4: "It takes the adopted fee schedule covering `effective_date` and finds
    the single tier of *that* schedule whose `fpg_min_pct` is less than or equal to
    `fpg_percent` and whose `fpg_max_pct` is either null or strictly greater than
    `fpg_percent`." PRD 3.4 also fixes the window: "its `expires_at` is set to
    exactly 365 days after `effective_date` — making the verification's closed
    window run from `effective_date` through `expires_at` inclusive".

    Design: Difficulty/boundary_precision_check/fpg_percent_exactly_at_band_edge_assigns_the_upper_tier
    """
    ctx = _two_patients_awaiting_adjudication()

    verified = _verify(ctx["below_edge_verification"]["id"])

    assert verified["fpg_percent"] == pytest.approx(99.91, abs=0.01), (
        "2188000 against a guideline amount of 2190000 rounds half up to 99.91, "
        f"got {verified['fpg_percent']}"
    )
    assert verified["assigned_tier_label"] == "NOMINAL_FULL", (
        "99.91 is strictly below 100 and so stays in the deepest band, got "
        f"{verified['assigned_tier_label']}"
    )
    assert (
        verified["assigned_discount_tier_id"]
        == ctx["tiers_by_label"]["NOMINAL_FULL"]["id"]
    )
    assert same_instant(verified["expires_at"]) == "2027-02-01T00:00:00Z", (
        "expires_at is exactly 365 days after an effective_date of 2026-02-01, got "
        f"{verified['expires_at']}"
    )
    assert refresh_patient(ctx["below_edge"]["id"])["sliding_fee_status"] == "VERIFIED"
