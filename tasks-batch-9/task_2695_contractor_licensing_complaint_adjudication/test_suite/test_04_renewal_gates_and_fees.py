"""Renewal: the four ordered gates and the three-stage fee assembly.

The renewal endpoint is where continuing education, bond history and the calendar
all meet. These tests drive the delinquent fee composition, the last day of the
delinquency grace band, and the precedence between two gates that fail together.
"""

from test_helpers import (
    ApiErrorId,
    CompliancePosture,
    CoverageType,
    LicenseStatus,
    assert_fields,
    assert_money_is_integer,
    assert_unchanged_version,
    constants as K,
    fixtures as FX,
    validate_error,
    validate_success,
)


def _bonded_licence(api, **mint_overrides):
    """A C-10 licence issued 2026-08-01 with a bond running past its first term."""
    ctx = FX.mint_active_license(api, **mint_overrides)
    bond = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.BOND,
        carrier_name="Surety One",
        policy_number="BND-4401",
        amount_cents=K.C10["required_bond_amount_cents"],
        effective_date="2026-08-01",
        expiration_date="2028-11-01",
    )
    FX.verify_coverage(api, bond["id"])
    return ctx


def test_01_delinquent_renewal_fee_is_assembled_in_three_ordered_stages(api):
    """Four shortfall hours, a delinquency surcharge and a ten percent assessment.

    PRD: "To make the composition concrete: a base fee of 45,000 cents against an
    eight-hour requirement with four hours banked, renewed thirty-two days after
    expiry, gives a stage one of 45,000 plus four times 5,000, or 65,000; a stage
    two of 65,000 plus half of 65,000, or 97,500; a rate of ten percent because
    97,500 falls below 100,000; and a fee of 97,500 plus 9,750, or 107,250."

    Design: Difficulty/combinatorial_formula/delinquent_renewal_fee_staged_ce_surcharge_then_tiered_assessment
    """
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = _bonded_licence(api)
    FX.set_clock(api, "2028-09-01T00:00:00Z")
    FX.bank_ce_hours(api, ctx, 4, "2028-08-15")

    renewed = validate_success(
        api.renew_license(ctx.license_id, ctx.licensee_headers)
    )

    assert_money_is_integer(renewed, "last_renewal_fee_cents")
    assert_fields(renewed, {"last_renewal_fee_cents": 107250})


def test_02_a_delinquent_renewal_dates_the_new_term_from_the_clock(api):
    """The delinquent branch anchors on the clock and empties the CE bank.

    PRD: "When the renewal is delinquent — the clock date strictly past
    `expires_on` — the new `expires_on` is the clock date advanced by twenty-four
    months and the surcharge is assessed."

    Design: Difficulty/combinatorial_formula/delinquent_renewal_fee_staged_ce_surcharge_then_tiered_assessment
    """
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = _bonded_licence(api)
    FX.set_clock(api, "2028-09-01T00:00:00Z")
    FX.bank_ce_hours(api, ctx, 4, "2028-08-15")

    validate_success(api.renew_license(ctx.license_id, ctx.licensee_headers))

    stored = FX.read_license(api, ctx.license_id)
    assert_fields(
        stored,
        {
            "expires_on": "2030-09-01",
            "last_renewed_on": "2028-09-01",
            "renewal_count": 1,
            "ce_hours_completed": 0,
            "status": LicenseStatus.ACTIVE,
            "compliance_posture": CompliancePosture.CONDITIONAL,
        },
    )


def test_03_renewal_on_the_ninetieth_grace_day_still_succeeds(api):
    """Exactly ninety days past expiry the window is still open, at a 74250 fee.

    PRD: "Third, the renewal window: the clock date must be no later than the
    licence's `expires_on` advanced by ninety days of delinquent grace, so the
    ninetieth day still renews and the ninety-first does not, drawing
    `ERR_RENEWAL_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/renewal_on_grace_day_ninety_succeeds_and_day_ninety_one_is_refused
    """
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = _bonded_licence(
        api,
        legal_name="Day90 Electric LLC",
        contact_email="d90@x.test",
        full_name="Nine Zero",
    )
    FX.set_clock(api, "2028-10-30T00:00:00Z")
    FX.bank_ce_hours(api, ctx, K.C10["required_ce_hours"], "2028-08-15")

    renewed = validate_success(
        api.renew_license(ctx.license_id, ctx.licensee_headers)
    )

    assert_fields(
        renewed,
        {
            "last_renewal_fee_cents": 74250,
            "expires_on": "2030-10-30",
            "last_renewed_on": "2028-10-30",
            "renewal_count": 1,
            "ce_hours_completed": 0,
            "status": LicenseStatus.ACTIVE,
        },
    )


def test_04_renewal_on_the_ninety_first_day_is_refused(api):
    """One day beyond the grace band the window has closed for good.

    PRD: "Third, the renewal window: the clock date must be no later than the
    licence's `expires_on` advanced by ninety days of delinquent grace, so the
    ninetieth day still renews and the ninety-first does not, drawing
    `ERR_RENEWAL_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/renewal_on_grace_day_ninety_succeeds_and_day_ninety_one_is_refused
    """
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = _bonded_licence(
        api,
        legal_name="Day91 Electric LLC",
        contact_email="d91@x.test",
        full_name="Nine One",
    )
    FX.set_clock(api, "2028-10-31T00:00:00Z")
    FX.bank_ce_hours(api, ctx, K.C10["required_ce_hours"], "2028-08-15")

    validate_error(
        api.renew_license(ctx.license_id, ctx.licensee_headers),
        ApiErrorId.RENEWAL_WINDOW_CLOSED,
    )

    stored = FX.read_license(api, ctx.license_id)
    assert_fields(
        stored,
        {
            "renewal_count": 0,
            "expires_on": "2028-08-01",
            "ce_hours_completed": K.C10["required_ce_hours"],
            "last_renewal_fee_cents": None,
        },
    )


def _licence_with_a_one_day_bond_gap(api):
    """Two verified bonds that leave 2027-08-01 uncovered, and no CE banked."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = FX.mint_active_license(api)
    for policy_number, effective_date, expiration_date in (
        ("BND-4401", "2026-08-01", "2027-08-01"),
        ("BND-4402", "2027-08-02", "2028-11-01"),
    ):
        record = FX.file_coverage(
            api,
            ctx.license_id,
            coverage_type=CoverageType.BOND,
            carrier_name="Surety One",
            policy_number=policy_number,
            amount_cents=K.C10["required_bond_amount_cents"],
            effective_date=effective_date,
            expiration_date=expiration_date,
        )
        FX.verify_coverage(api, record["id"])
    FX.set_clock(api, "2028-07-01T00:00:00Z")
    return ctx


def test_05_a_bond_continuity_gap_outranks_a_continuing_education_shortfall(api):
    """Both the first and the fourth gate fail; only the first is reported.

    PRD: "First, bond continuity: the uncovered-day measurement of §3.5 must come
    to zero over the expiring term, and any gap at all refuses the renewal with
    `ERR_COVERAGE_CONTINUITY_GAP`."

    Design: Difficulty/priority_pair_validation_conflict/renewal_bond_continuity_error_outranks_ce_shortfall_error
    """
    ctx = _licence_with_a_one_day_bond_gap(api)

    reported = validate_error(
        api.renew_license(ctx.license_id, ctx.licensee_headers),
        ApiErrorId.COVERAGE_CONTINUITY_GAP,
    )

    assert reported["error_id"] != ApiErrorId.CE_HOURS_INSUFFICIENT.value, (
        "the continuing-education shortfall must not mask the coverage gap"
    )


def test_06_the_refused_renewal_leaves_every_term_counter_untouched(api):
    """A renewal rejected at the first gate performs none of the later stages.

    PRD: "Either way, `last_renewed_on` is set to the clock date, `renewal_count`
    rises by one, and `ce_hours_completed` is reset to zero for the fresh term."

    Design: Difficulty/priority_pair_validation_conflict/renewal_bond_continuity_error_outranks_ce_shortfall_error
    """
    ctx = _licence_with_a_one_day_bond_gap(api)
    before = FX.read_license(api, ctx.license_id)

    validate_error(
        api.renew_license(ctx.license_id, ctx.licensee_headers),
        ApiErrorId.COVERAGE_CONTINUITY_GAP,
    )

    after = FX.read_license(api, ctx.license_id)
    assert_fields(
        after,
        {
            "renewal_count": 0,
            "expires_on": "2028-08-01",
            "ce_hours_completed": 0,
            "last_renewal_fee_cents": None,
            "last_renewed_on": None,
            "status": LicenseStatus.ACTIVE,
        },
    )
    assert_unchanged_version(before, after)
