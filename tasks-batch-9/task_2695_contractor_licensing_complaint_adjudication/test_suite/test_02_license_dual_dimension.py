"""The licensure and compliance dimensions of a licence move independently.

A licence carries two state machines at once. These tests walk the compliance
dimension across three writes while the licensure dimension holds still, and then
drive the one event that moves both at once: a carrier cancelling the bond.
"""

from test_helpers import (
    LICENSING_ANALYST_HEADERS,
    AssignmentStatus,
    CompliancePosture,
    CoverageStatus,
    CoverageType,
    LicenseStatus,
    SuspensionReason,
    assert_dual_dimension,
    assert_fields,
    assert_posture,
    assert_qualification_count,
    assert_suspension,
    constants as K,
    fixtures as FX,
    validate_success,
)

BOND_PERIOD = {"effective_date": "2026-08-01", "expiration_date": "2027-08-01"}


def _licence_with_unverified_instruments(api):
    """A freshly minted licence with a bond and a liability policy merely filed."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = FX.mint_active_license(api)
    bond = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.BOND,
        carrier_name="Surety One",
        policy_number="BND-4401",
        amount_cents=K.C10["required_bond_amount_cents"],
        **BOND_PERIOD,
    )
    liability = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.GENERAL_LIABILITY,
        carrier_name="Mutual Trades",
        policy_number="GL-9902",
        amount_cents=100000,
        **BOND_PERIOD,
    )
    return ctx, bond, liability


def test_01_verifying_the_bond_lifts_the_posture_without_touching_status(api):
    """The bond clears the NON_COMPLIANT clause and leaves CONDITIONAL behind.

    PRD: "Otherwise, the licence is `CONDITIONAL` if **any** of the following is
    true: its unpaid penalty exposure is greater than zero; it has no live general
    liability; or probation holds."

    Design: Difficulty/non_linear_state_machine/license_posture_dimension_moves_three_times_while_status_stays_active
    """
    ctx, bond, _liability = _licence_with_unverified_instruments(api)
    assert_dual_dimension(
        ctx.license, LicenseStatus.ACTIVE, CompliancePosture.NON_COMPLIANT
    )

    FX.verify_coverage(api, bond["id"])

    after_bond = FX.read_license(api, ctx.license_id)
    assert_dual_dimension(
        after_bond, LicenseStatus.ACTIVE, CompliancePosture.CONDITIONAL
    )


def test_02_verifying_general_liability_completes_the_climb_to_compliant(api):
    """With bond and liability both live the licence is fully COMPLIANT.

    PRD: "Otherwise the licence is `COMPLIANT`. Because the `NON_COMPLIANT` clause
    is evaluated first, a `CONDITIONAL` trigger can never soften a licence that
    independently qualifies as `NON_COMPLIANT`."

    Design: Difficulty/non_linear_state_machine/license_posture_dimension_moves_three_times_while_status_stays_active
    """
    ctx, bond, liability = _licence_with_unverified_instruments(api)
    FX.verify_coverage(api, bond["id"])

    FX.verify_coverage(api, liability["id"])

    after_liability = FX.read_license(api, ctx.license_id)
    assert_dual_dimension(
        after_liability, LicenseStatus.ACTIVE, CompliancePosture.COMPLIANT
    )
    assert_suspension(after_liability, None, None)


def test_03_withdrawing_the_only_qualifier_drops_the_posture_but_not_the_status(api):
    """Losing the qualifier of record is a compliance event, not a licensure one.

    PRD: "Worth internalising: a freshly minted licence has no verified bond yet
    and is therefore `NON_COMPLIANT` from birth, even though its `status` is
    `ACTIVE`; and withdrawing a licence's only qualifier drops it straight to
    `NON_COMPLIANT` without touching `status` at all."

    Design: Difficulty/non_linear_state_machine/license_posture_dimension_moves_three_times_while_status_stays_active
    """
    ctx, bond, liability = _licence_with_unverified_instruments(api)
    FX.verify_coverage(api, bond["id"])
    FX.verify_coverage(api, liability["id"])
    assignment = FX.find_assignment_for_license(api, ctx.license_id)

    withdrawn = validate_success(
        api.withdraw_qualifier_assignment(
            assignment["id"], {"withdrawn_on": "2026-08-01"}, LICENSING_ANALYST_HEADERS
        )
    )

    assert_fields(
        withdrawn,
        {"status": AssignmentStatus.WITHDRAWN, "effective_to": "2026-08-01"},
    )
    after_withdrawal = FX.read_license(api, ctx.license_id)
    assert_dual_dimension(
        after_withdrawal, LicenseStatus.ACTIVE, CompliancePosture.NON_COMPLIANT
    )
    assert_fields(after_withdrawal, {"qualifying_individual_id": None})
    assert_suspension(after_withdrawal, None, None)
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(
                ctx.individual_id, LICENSING_ANALYST_HEADERS
            )
        ),
        0,
    )


def _bonded_licence_at_october(api):
    """A licence carrying one verified bond, with the clock moved into the term."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = FX.mint_active_license(api)
    bond = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.BOND,
        carrier_name="Surety One",
        policy_number="BND-4401",
        amount_cents=K.C10["required_bond_amount_cents"],
        **BOND_PERIOD,
    )
    FX.verify_coverage(api, bond["id"])
    assert_posture(
        FX.read_license(api, ctx.license_id), CompliancePosture.CONDITIONAL
    )
    FX.set_clock(api, "2026-10-01T00:00:00Z")
    return ctx, bond


def test_04_cancellation_truncates_the_bond_period_and_suspends_the_licence(api):
    """The rewritten expiration leaves today uncovered, so the licence is suspended.

    PRD: "**First**, `cancellation_date` is stored and the record's
    `expiration_date` is rewritten to that same date, so — the period being
    half-open — the record no longer covers `cancellation_date` or any date after
    it, and the record's `status` becomes `CANCELLED`."

    Design: Difficulty/transitive_cascade/bond_cancellation_cascade_lapses_coverage_suspends_license_and_drops_count
    """
    ctx, bond = _bonded_licence_at_october(api)

    cancelled = validate_success(
        api.cancel_coverage_record(
            bond["id"],
            {"cancellation_date": "2026-10-01"},
            LICENSING_ANALYST_HEADERS,
        )
    )

    assert_fields(
        cancelled,
        {
            "status": CoverageStatus.CANCELLED,
            "cancellation_date": "2026-10-01",
            "expiration_date": "2026-10-01",
        },
    )
    after = FX.read_license(api, ctx.license_id)
    assert_dual_dimension(
        after, LicenseStatus.SUSPENDED, CompliancePosture.NON_COMPLIANT
    )
    assert_suspension(after, SuspensionReason.BOND_LAPSE, None)


def test_05_bond_lapse_suspension_cascades_into_designation_and_qualifier_count(api):
    """Suspension suspends the designation, which drops the qualifier's count.

    PRD: "**Third**, *because* the licence has entered `SUSPENDED`, every
    designation on it in `ACTIVE` moves to `SUSPENDED_BY_LICENSE`. **Fourth**,
    *because* those designations have left `ACTIVE`, each affected qualifying
    individual's `active_qualification_count` falls by one."

    Design: Difficulty/transitive_cascade/bond_cancellation_cascade_lapses_coverage_suspends_license_and_drops_count
    """
    ctx, bond = _bonded_licence_at_october(api)
    assignment = FX.find_assignment_for_license(api, ctx.license_id)
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(
                ctx.individual_id, LICENSING_ANALYST_HEADERS
            )
        ),
        1,
    )

    validate_success(
        api.cancel_coverage_record(
            bond["id"],
            {"cancellation_date": "2026-10-01"},
            LICENSING_ANALYST_HEADERS,
        )
    )

    assert_fields(
        validate_success(
            api.get_qualifier_assignment(
                assignment["id"], LICENSING_ANALYST_HEADERS
            )
        ),
        {"status": AssignmentStatus.SUSPENDED_BY_LICENSE},
    )
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(
                ctx.individual_id, LICENSING_ANALYST_HEADERS
            )
        ),
        0,
    )
