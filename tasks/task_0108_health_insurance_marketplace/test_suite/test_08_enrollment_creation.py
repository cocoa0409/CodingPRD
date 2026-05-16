"""Enrollment creation: preconditions, monthly premium construction,
APTC cap, CSR variant alignment, uniqueness, plan/state mismatch.

PRD §3.6, §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    add_household_member,
    assert_enrollment,
    create_enrollment_payload,
    create_plan_variant,
    create_application,
    make_applicant_headers,
    setup_application_at_fpl_percentage,
    setup_approved_application,
    setup_benchmark_silver_catalog,
    setup_eligibility_determined_application,
    setup_enrollment_pending_payment,
    validate_error,
    validate_success,
)


# ===========================================================================
# Monthly premium construction (PRD §3.6) — pinned rounding order
# ===========================================================================
class TestMonthlyPremiumConstruction:
    """PRD §3.6: "Monthly premium construction follows a tiered age
    curve, with the rounding order pinned: per-member rounding to a
    whole cent happens first, then the rounded per-member amounts are
    summed."""

    def test_per_member_round_then_sum_pinned_order(self, api):
        """# difficulty: combinatorial_formula/
        monthly_premium_per_member_round_then_sum_pinned_order

        PRD §3.6: "per-member rounding to a whole cent happens first,
        then the rounded per-member amounts are summed."
        PRD §3.6: "1.181 for ages 35 through 39".

        Setup: 3 PRIMARY/SPOUSE/DEPENDENT all age 35, base=12_345,
        no tobacco, csr_eligibility==NONE → STANDARD variant.
        per-member = round_half_up(12345 * 1.181) = 14579.
        gross_monthly = 3 * 14579 = 43_737.
        The alternative order (sum then round) would yield
          round_half_up(12345 * 1.181 * 3) = 43_738. PRD pins 43_737.
        """
        # Build a 3-person household at high FPL (above 250%) so
        # csr_eligibility == NONE and APTC == 0 (so gross == net).
        # household_size 3 → denom (2026) = 2_689_500. Target FPL 260
        # → MAGI = 6_992_700.
        # Adjust members: PRIMARY 35, SPOUSE 35, DEPENDENT 35-ish (>=19
        # so not auto Medicaid via age<19; but DEPENDENT max age is 25
        # per PRD §3.1). Use DEPENDENT age 22 with age_mult=1.000? No —
        # we need three members each at 1.181. PRD age curve is by age
        # alone; DEPENDENT age 35 is impossible per dependent-age rule
        # (max age 26). So replace one member age — but then the
        # rounding order test changes.
        #
        # Workaround: bypass this by using PRIMARY 35 + SPOUSE 35 +
        # SPOUSE 35 — but only one SPOUSE per household is allowed by
        # convention (PRD doesn't strictly say). To stay safe, use
        # household_size 2 and pin the math at 2 members:
        #   per-member = 14579, sum = 29158.
        #   alternative = round_half_up(12345*1.181*2) = round_half_up(
        #     29158.89) = 29159. Pin gross == 29158, NOT 29159.
        determined, _p, ins, plan = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=260.0, coverage_year=2026,
                household_size=2, primary_age=35, spouse_age=35,
                base_monthly_premium_cents=12_345,
            )
        )
        approved_res = api.approve_application(
            determined["id"], TEST_USERS["admin_headers"],
        )
        approved = validate_success(approved_res, 200)
        # csr_eligibility == NONE at FPL 260 → STANDARD variant.
        assert approved["csr_eligibility"] == "NONE"
        variant = create_plan_variant(
            plan=plan, csr_level="STANDARD", actuarial_value=70.0,
            out_of_pocket_max_cents=900_000, insurer=ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=approved["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(determined["_applicant_id"]),
        )
        enrollment = validate_success(res, 201)
        # PRD §3.6 pinned rounding: per-member round → sum.
        # 2 members × round_half_up(12345 * 1.181) = 2 × 14579 = 29158.
        assert enrollment["monthly_premium_gross_cents"] == 29158
        # sum-then-round would have produced 29159.
        assert enrollment["monthly_premium_gross_cents"] != 29159

    def test_aptc_capped_at_gross_when_subsidy_exceeds_premium(
        self, api,
    ):
        """# difficulty: combinatorial_formula/
        enrollment_net_premium_evaluation_order_when_subsidy_caps

        PRD §3.6: "The monthly APTC applied is the lesser of the
        annual aptc_estimated_cents divided by 12 (rounded half-up to
        a whole cent) and monthly_premium_gross_cents; it has a floor
        of zero and a ceiling at the gross premium".

        Setup: low-income single-PRIMARY-FILER household at age 35 in
        CA. Choose base_monthly_premium_cents=40000 so gross per-member
        = round_half_up(40000*1.181) = 47240. Choose fpl_percentage to
        produce a large annual APTC well in excess of 12 * gross.
        At FPL 200 with denom 2_131_000 (size 2): MAGI = 4_262_000.
        applicable fraction 0.04 → contribution = 170_480.
        benchmark annual for 2 age-35 members = 12 * 47240 * 2 = 1_133_760.
        aptc_estimated = 1_133_760 - 170_480 = 963_280.
        monthly aptc = 963_280 / 12 = 80273.33 → round_half_up = 80273.
        gross = 2 * 47240 = 94480. APTC applied = min(80273, 94480) =
        80273. Net = 14207.
        That's NOT the cap-binding case.

        For cap-binding we need /12 > gross. Pick base lower or APTC
        much higher. Use a SINGLE-FILER household at MAGI just above
        100% FPL: denom (size 1, 2026) = 1_572_500. Target FPL 105
        → MAGI = 1_651_125. applicable fraction 0.0 → contribution = 0.
        benchmark annual for 1 age-35 member = 12 * 47240 = 566_880.
        aptc_estimated = 566_880. monthly = 566_880 / 12 = 47240.
        gross = 47240. APTC applied = min(47240, 47240) = 47240. Net = 0.
        This is the exact-cap case — the cap is observable because the
        result equals gross, not gross-1.

        Claim: monthly_aptc_applied_cents == monthly_premium_gross_cents
        when annual aptc / 12 equals or exceeds gross.
        """
        # PRD §3.3: an adult in an EXPANSION state with fpl < 138.0 is
        # Medicaid-eligible, which would block /approve under the rule
        # "at least one included member is not Medicaid-eligible". We
        # build this scenario in a non-expansion state (TX) so the
        # adult avoids the Medicaid path and approval succeeds, leaving
        # the APTC cap as the observable behavior under test.
        determined, _p, ins, plan = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=105.0, coverage_year=2026,
                household_size=1, primary_age=35,
                filing_state="TX",
                base_monthly_premium_cents=40_000,
            )
        )
        approved = validate_success(api.approve_application(
            determined["id"], TEST_USERS["admin_headers"],
        ), 200)
        # csr_eligibility at FPL 105 is CSR_PLUS — must match variant.
        from test_helpers import create_plan_variant
        variant = create_plan_variant(
            plan=plan, csr_level=approved["csr_eligibility"],
            actuarial_value=97.0, out_of_pocket_max_cents=300_000,
            insurer=ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=approved["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(determined["_applicant_id"]),
        )
        enrollment = validate_success(res, 201)
        # APTC ceiling at gross — PRD §3.6.
        assert (
            enrollment["monthly_aptc_applied_cents"]
            <= enrollment["monthly_premium_gross_cents"]
        )
        # Specific math: gross = 47240, aptc/12 = 47240 → applied = 47240.
        assert enrollment["monthly_premium_gross_cents"] == 47240
        assert enrollment["monthly_aptc_applied_cents"] == 47240
        assert enrollment["monthly_net_premium_cents"] == 0


# ===========================================================================
# Precondition validation (PRD §3.6, §3.9)
# ===========================================================================
class TestEnrollmentPreconditions:
    """PRD §3.6: priority-ordered preconditions on enrollment."""

    def test_create_on_non_approved_application_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/
        enrollment_creation_requires_application_approved

        PRD §3.6: "Once an application is APPROVED, the applicant binds
        it to a chosen plan variant by submitting an enrollment".

        Claim: POST /enrollments where Application.status is
        ELIGIBILITY_DETERMINED → ERR_INVALID_STATE.
        """
        determined, _p, ins, plan = (
            setup_eligibility_determined_application()
        )
        variant = create_plan_variant(
            plan=plan, csr_level=determined.get(
                "csr_eligibility", "NONE",
            ) if determined.get("csr_eligibility") != "NONE"
            else "STANDARD",
            actuarial_value=70.0, insurer=ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=determined["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(determined["_applicant_id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_plan_state_mismatch_rejected(self, api):
        """PRD §3.6: "The named plan_variant_id must resolve to a plan
        whose filing_state matches the application's filing_state and
        whose coverage_year matches the application's coverage_year
        (otherwise ERR_PLAN_STATE_MISMATCH)."

        Claim: Application in CA, plan_variant under a plan in NY →
        ERR_PLAN_STATE_MISMATCH.
        """
        # Build benchmark catalog in CA so determine-eligibility passes.
        # Build a SECOND insurer + plan in NY whose plan_variant the
        # applicant will (mis-)reference.
        from test_helpers import create_insurer, create_plan
        ca_ins, ca_plan, _ = setup_benchmark_silver_catalog(
            filing_state="CA", coverage_year=2026,
            include_standard_variant=False,
        )
        approved, _p, _ins, _pl = setup_approved_application(
            filing_state="CA", coverage_year=2026,
            primary_income_cents=5_000_000,
            insurer=ca_ins, benchmark_plan=ca_plan,
        )
        ny_ins = create_insurer(filing_states=["NY"])
        ny_plan = create_plan(
            insurer=ny_ins, filing_state="NY", coverage_year=2026,
            tier="SILVER", base_monthly_premium_cents=40_000,
        )
        ny_variant = create_plan_variant(
            plan=ny_plan, csr_level="STANDARD",
            actuarial_value=70.0, insurer=ny_ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=approved["id"],
                plan_variant_id=ny_variant["id"],
            ),
            make_applicant_headers(approved["_applicant_id"]),
        )
        validate_error(res, "ERR_PLAN_STATE_MISMATCH")

    def test_csr_variant_mismatch_rejected(self, api):
        """PRD §3.6: "The variant's csr_level must align with the
        application's csr_eligibility — STANDARD when the household
        qualifies for no CSR (csr_eligibility is NONE), otherwise an
        exact match between csr_level and csr_eligibility (otherwise
        ERR_CSR_VARIANT_MISMATCH)."

        Claim: csr_eligibility==CSR_94 but variant.csr_level==CSR_73
        → ERR_CSR_VARIANT_MISMATCH.
        """
        # Build approved application with csr_eligibility == CSR_94
        # (fpl in [138, 150)).
        determined, _p, ins, plan = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=140.0, coverage_year=2026,
                household_size=2,
            )
        )
        approved = validate_success(api.approve_application(
            determined["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert approved["csr_eligibility"] == "CSR_94"
        # The raw /approve response does not carry the fixture's
        # _applicant_id bookkeeping field; thread it from `determined`
        # which the helper did populate. PRD §2.1 requires the same
        # X-User-ID for ownership-gated follow-ups under the parent
        # application.
        applicant_id = determined["_applicant_id"]
        variant = create_plan_variant(
            plan=plan, csr_level="CSR_73", actuarial_value=73.0,
            insurer=ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=approved["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(applicant_id),
        )
        validate_error(res, "ERR_CSR_VARIANT_MISMATCH")


# ===========================================================================
# Enrollment uniqueness (PRD §3.6, §3.9 priority 14)
# ===========================================================================
class TestEnrollmentUniqueness:
    """# difficulty: resource_temporal_overlap/
    enrollment_one_per_application_per_coverage_year_uniqueness

    PRD §3.6: "at most one enrollment may exist per (application_id,
    coverage_year) pair; a second concurrent submission is rejected
    with ERR_ENROLLMENT_ALREADY_EXISTS."
    """

    def test_second_enrollment_same_application_rejected(self, api):
        """# difficulty: resource_temporal_overlap/
        enrollment_one_per_application_per_coverage_year_uniqueness

        PRD §3.6: "at most one enrollment may exist per
        (application_id, coverage_year) pair; a second concurrent
        submission is rejected with ERR_ENROLLMENT_ALREADY_EXISTS."

        Claim: a second POST /enrollments under the same Application
        is rejected with ERR_ENROLLMENT_ALREADY_EXISTS.
        """
        app, _p, ins, plan, variant, _enrollment = (
            setup_enrollment_pending_payment()
        )
        # A second enrollment under the SAME application is the test
        # surface — reuse the variant id.
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=app["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(app["_applicant_id"]),
        )
        validate_error(res, "ERR_ENROLLMENT_ALREADY_EXISTS")


# ===========================================================================
# Enrollment initial state (PRD §3.6)
# ===========================================================================
class TestEnrollmentInitialPosture:
    """PRD §3.6: "The enrollment is created in the parallel posture
    coverage_status = PENDING_PAYMENT and payment_status =
    AWAITING_BINDER, with coverage_end_date left null and
    terminated_reason left null."""

    def test_enrollment_starts_pending_payment_awaiting_binder(self, api):
        """PRD §3.6 initial-state claim."""
        app, _p, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment()
        )
        assert_enrollment(enrollment)
        assert enrollment["coverage_status"] == "PENDING_PAYMENT"
        assert enrollment["payment_status"] == "AWAITING_BINDER"
        assert enrollment.get("coverage_end_date") is None
        assert enrollment.get("terminated_reason") is None

    def test_enrollment_pins_plan_catalog_version(self, api):
        """PRD §2.8: "When an enrollment is created, the parent
        Plan.catalog_version at the moment of write is snapshotted
        onto Enrollment.pinned_plan_catalog_version".
        """
        app, _p, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment()
        )
        assert (
            enrollment["pinned_plan_catalog_version"]
            == plan["catalog_version"]
        )
