"""Retirement applications: estimates, tiers, review cycle, gates, OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    approve_retirement_app,
    assert_benefit,
    assert_retirement_application,
    create_member,
    create_report,
    create_retirement_app,
    current_application_version,
    five_year_line_specs,
    list_payments_sorted,
    make_approver_headers,
    make_member_headers,
    pay_installment,
    reconcile_member_history,
    review_retirement_app,
    setup_fund_and_employer,
    setup_plan_active_purchase,
    setup_vested_member,
    submit_report,
    submit_retirement_app,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, APPROVER


class TestBenefitEstimateVariants:
    def _setup_estimate_member(self, api):
        """Six RECONCILED years FY2018-2023 plus one PENDING FY2024 line at
        6,500,000 in a second, still-SUBMITTED report."""
        ctx = setup_vested_member(full_name="Estimate Erin")
        employer, member = ctx["employer"], ctx["member"]
        report = create_report(employer["id"], "2024-01-01", "2025-01-01",
                               520_000)
        add_line(report["id"], employer["id"], member["id"], 2024,
                 6_500_000, 520_000)
        submit_report(report["id"], employer["id"])
        return member

    def test_final_variant_counts_accepted_lines_only(self, api):
        """PRD §3.5: "The PROVISIONAL variant includes `PENDING` contribution
        lines — salary and service months — projecting not-yet-reconciled
        service into the totals; the FINAL variant counts only `ACCEPTED`
        lines, so identical data with one unreviewed pending line yields a
        lower estimate under FINAL than under PROVISIONAL."

        Design: Difficulty/dual_variant_calc/benefit_estimate_provisional_vs_final
        """
        member = self._setup_estimate_member(api)
        estimate = validate_success(api.get_benefit_estimate(
            member["id"], ANALYST, params={"variant": "FINAL"}), 200)
        assert estimate["fas_cents"] == 5_500_000
        assert estimate["service_years"] == pytest.approx(6.0)
        assert estimate["multiplier"] == pytest.approx(0.017)
        assert estimate["monthly_single_life_cents"] == 46_750

    def test_provisional_variant_includes_pending_lines(self, api):
        """PRD §3.5: "The PROVISIONAL variant includes `PENDING` contribution
        lines — salary and service months — projecting not-yet-reconciled
        service into the totals; the FINAL variant counts only `ACCEPTED`
        lines, so identical data with one unreviewed pending line yields a
        lower estimate under FINAL than under PROVISIONAL."
        PRD §3.5: "The base monthly amount is `fas_annual_cents` times the
        multiplier times service years divided by twelve, computed with no
        intermediate rounding."

        Design: Difficulty/dual_variant_calc/benefit_estimate_provisional_vs_final
        """
        member = self._setup_estimate_member(api)
        provisional = validate_success(api.get_benefit_estimate(
            member["id"], ANALYST, params={"variant": "PROVISIONAL"}), 200)
        assert provisional["fas_cents"] == 6_000_000, (
            "PROVISIONAL averages FY2022-2024 including the PENDING line")
        assert provisional["service_years"] == pytest.approx(7.0)
        assert provisional["monthly_single_life_cents"] == 59_500
        final = validate_success(api.get_benefit_estimate(
            member["id"], ANALYST, params={"variant": "FINAL"}), 200)
        assert provisional["monthly_single_life_cents"] - \
            final["monthly_single_life_cents"] == 12_750


class TestTieredMultiplierAndOptionFactor:
    def _setup_tiered_member(self, api):
        return setup_vested_member(full_name="Tiered Terry")["member"]

    def test_single_life_and_joint_50_near_factors(self, api):
        """PRD §3.5: "For `SINGLE_LIFE` the factor is 1.00. For `JOINT_50` and
        `JOINT_100` the factor depends on `age_diff`, the completed years
        between the member's `date_of_birth` and the
        `beneficiary_date_of_birth`: `JOINT_50` uses 0.95 when `age_diff` is
        at most 10 years and 0.90 otherwise; `JOINT_100` uses 0.90 when
        `age_diff` is at most 10 and 0.82 otherwise."

        Design: Difficulty/combinatorial_formula/monthly_benefit_tiered_multiplier_and_conditional_option_factor
        """
        member = self._setup_tiered_member(api)
        app_single = create_retirement_app(member["id"], "SINGLE_LIFE")
        submitted = submit_retirement_app(app_single["id"], member["id"])
        assert submitted["provisional_monthly_cents"] == 46_750, (
            f"5,500,000 * 0.017 * 6 / 12 * 1.00 = 46,750, "
            f"got {submitted['provisional_monthly_cents']}")
        validate_success(api.cancel_retirement_application(
            app_single["id"], make_member_headers(member["id"])), 200)

        app_j50 = create_retirement_app(
            member["id"], "JOINT_50", beneficiary_name="Pat Partner",
            beneficiary_date_of_birth="1970-01-01")
        submitted = submit_retirement_app(app_j50["id"], member["id"])
        assert submitted["provisional_monthly_cents"] == 44_413, (
            f"46,750 * 0.95 = 44,412.5 rounds half-up to 44,413, "
            f"got {submitted['provisional_monthly_cents']}")
        validate_success(api.cancel_retirement_application(
            app_j50["id"], make_member_headers(member["id"])), 200)

    def test_joint_100_far_age_difference_factor(self, api):
        """PRD §3.5: "`JOINT_100` uses 0.90 when `age_diff` is at most 10 and
        0.82 otherwise."
        PRD §3.5: "The final `monthly_cents` is the base monthly times the
        option factor, rounded half-up once — a single final rounding."

        Design: Difficulty/combinatorial_formula/monthly_benefit_tiered_multiplier_and_conditional_option_factor
        """
        member = self._setup_tiered_member(api)
        app_j100 = create_retirement_app(
            member["id"], "JOINT_100", beneficiary_name="Old Olympia",
            beneficiary_date_of_birth="1950-01-01")
        submitted = submit_retirement_app(app_j100["id"], member["id"])
        # age_diff 16 > 10 -> factor 0.82 -> 46,750 * 0.82 = 38,335.0
        assert submitted["provisional_monthly_cents"] == 38_335


class TestReviewReturnCycle:
    def _setup_submitted_app(self, api):
        ctx = setup_vested_member(full_name="Cycle Carl")
        member = ctx["member"]
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        submit_retirement_app(app["id"], member["id"])
        return ctx, app

    def test_return_then_review_ok_cycle_repeats(self, api):
        """PRD §3.5: "The review cycle is unbounded: a returned application
        can come back to `UNDER_REVIEW` via another `REVIEW_OK`, each time
        refreshing `reviewed_by_user_id`, and either `SUBMITTED` or
        `RETURNED_FOR_CORRECTION` is a valid from-state for that transition."

        Design: Difficulty/non_linear_state_machine/retirement_review_return_cycle
        """
        _ctx, app = self._setup_submitted_app(api)
        returned = review_retirement_app(app["id"], "RETURN", "analyst-1",
                                         "missing DD-214")
        assert returned["status"] == "RETURNED_FOR_CORRECTION"
        under = review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
        assert under["status"] == "UNDER_REVIEW"
        returned2 = review_retirement_app(app["id"], "RETURN", "analyst-1",
                                          "salary mismatch")
        assert returned2["status"] == "RETURNED_FOR_CORRECTION"
        under2 = review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
        assert under2["status"] == "UNDER_REVIEW"
        assert under2["reviewed_by_user_id"] == "analyst-1"

    def test_cycled_application_approves_and_creates_benefit(self, api):
        """PRD §3.5: "The FINAL benefit estimate runs and is stored as
        `final_monthly_cents`."
        PRD §3.5: "A Benefit is created with `benefit_kind` `SERVICE`,
        `monthly_amount_cents` equal to the final amount, `status` `ACTIVE`,
        and `effective_date` set to the first day of the month containing the
        approval date on the logical clock. The member moves to `RETIRED`."

        Design: Difficulty/non_linear_state_machine/retirement_review_return_cycle
        """
        ctx, app = self._setup_submitted_app(api)
        member_id = ctx["member"]["id"]
        review_retirement_app(app["id"], "RETURN", "analyst-1", "recheck")
        review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
        version = current_application_version(app["id"])
        approved = approve_retirement_app(app["id"], version, "approver-1")
        assert approved["status"] == "APPROVED"
        assert approved["final_monthly_cents"] == 46_750
        benefits, meta = validate_paginated(
            api.list_member_benefits(member_id, ANALYST))
        assert meta["total_count"] == 1
        assert_benefit(benefits[0])
        assert benefits[0]["monthly_amount_cents"] == 46_750
        assert benefits[0]["status"] == "ACTIVE"
        assert benefits[0]["benefit_kind"] == "SERVICE"
        member = validate_success(api.get_member(member_id, ANALYST), 200)
        assert member["status"] == "RETIRED"


class TestApproveRequiresMemberActive:
    def _setup_under_review_then_inactive(self, api):
        ctx = setup_vested_member(full_name="Gate Gina")
        member = ctx["member"]
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        submit_retirement_app(app["id"], member["id"])
        review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
        validate_success(api.update_member(member["id"],
                                           {"status": "INACTIVE"}, ANALYST),
                         200)
        return member, app

    def test_approve_with_inactive_member_rejected(self, api):
        """PRD §3.5: "The remaining gates fire in the §2.8 order: the member
        must still be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`); no service purchase
        of the member may stand in `PLAN_ACTIVE` (`ERR_OUTSTANDING_BALANCE` —
        HTTP 422 — because the fund will not retire a member who still owes on
        a purchase); and the approver's `X-User-ID` must differ from the
        application's `reviewed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`,
        HTTP 403 — the reviewer may not approve their own review)."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_member_active
        """
        member, app = self._setup_under_review_then_inactive(api)
        version = current_application_version(app["id"])
        res = api.approve_retirement_application(
            app["id"], {"expected_application_version": version}, APPROVER)
        validate_error(res, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)
        after = validate_success(api.get_retirement_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "UNDER_REVIEW"

    def test_reactivated_member_can_then_be_approved(self, api):
        """PRD §3.1: "An analyst may move a member between `ACTIVE` and
        `INACTIVE` — in either direction — by patching the `status`."
        PRD §3.5: "The remaining gates fire in the §2.8 order: the member must
        still be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/approve_requires_member_active
        """
        member, app = self._setup_under_review_then_inactive(api)
        benefits, meta = validate_paginated(
            api.list_member_benefits(member["id"], ANALYST))
        assert meta["total_count"] == 0
        validate_success(api.update_member(member["id"], {"status": "ACTIVE"},
                                           ANALYST), 200)
        version = current_application_version(app["id"])
        approved = approve_retirement_app(app["id"], version, "approver-1")
        assert approved["status"] == "APPROVED"


class TestApproveValidationOrder:
    def _setup_cancelled_app_with_plan(self, api):
        ctx = setup_vested_member(full_name="Conflict Cora")
        member = ctx["member"]
        setup_plan_active_purchase(member["id"])  # outstanding balance exists
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        submit_retirement_app(app["id"], member["id"])
        validate_success(api.cancel_retirement_application(
            app["id"], make_member_headers(member["id"])), 200)
        return member, app

    def test_approve_cancelled_with_balance_returns_invalid_state(self, api):
        """PRD §2.8: "6. **State gates** — generic invalid from-state
        (`ERR_INVALID_STATE`), member lifecycle gates (`ERR_MEMBER_NOT_ACTIVE`,
        `ERR_MEMBER_DECEASED`), and resource-specific status gates
        (`ERR_PLAN_NOT_ACTIVE`, `ERR_BENEFIT_NOT_ACTIVE`,
        `ERR_BENEFIT_NOT_TERMINATED`)."
        PRD §2.8: "11. **Eligibility and fiscal gates** — vesting, retirement
        age, outstanding purchase balances, and reconciliation outcomes
        (`ERR_NOT_VESTED`, `ERR_MEMBER_UNDER_RETIREMENT_AGE`,
        `ERR_OUTSTANDING_BALANCE`, `ERR_LINES_PENDING`,
        `ERR_RECONCILIATION_VARIANCE`)."

        Design: Difficulty/priority_pair_validation_conflict/approve_cancelled_application_with_outstanding_balance_state_wins
        """
        member, app = self._setup_cancelled_app_with_plan(api)
        version = current_application_version(app["id"])
        res = api.approve_retirement_application(
            app["id"], {"expected_application_version": version}, APPROVER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_approve_has_no_side_effects(self, api):
        """PRD §2.6: "if the value does not match the entity's current
        `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)
        and nothing changes."
        PRD §3.5: "`APPROVED` and `CANCELLED` are the terminal states;
        cancelling an application directly is available to the member or an
        analyst from any non-terminal state."

        Design: Difficulty/priority_pair_validation_conflict/approve_cancelled_application_with_outstanding_balance_state_wins
        """
        member, app = self._setup_cancelled_app_with_plan(api)
        version = current_application_version(app["id"])
        res = api.approve_retirement_application(
            app["id"], {"expected_application_version": version}, APPROVER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_retirement_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "CANCELLED"
        assert after.get("final_monthly_cents") is None
        _benefits, meta = validate_paginated(
            api.list_member_benefits(member["id"], ANALYST))
        assert meta["total_count"] == 0


class TestVestingBoundary:
    def _setup_two_members_at_boundary(self, api):
        """V5: 60 accepted months (5.0 years); V4: 59 accepted months
        (4.92 years); both DOB 1966-01-01 hired 2016-01-01."""
        fund, employer = setup_fund_and_employer()
        v5 = create_member(employer["id"], full_name="Vested Vera")
        v4 = create_member(employer["id"], full_name="Short Victor")
        specs = [{"member_id": v5["id"], "fiscal_year": fy,
                  "salary_cents": 5_000_000} for fy in range(2019, 2024)]
        specs += [{"member_id": v4["id"], "fiscal_year": fy,
                   "salary_cents": 5_000_000} for fy in range(2019, 2023)]
        specs.append({"member_id": v4["id"], "fiscal_year": 2023,
                      "salary_cents": 5_000_000, "service_months": 11})
        reconcile_member_history(employer["id"], specs)
        return v5, v4

    def test_exactly_five_years_qualifies(self, api):
        """PRD §3.5: "the member's `total_service_years` must be at least 5 —
        the vesting threshold (`ERR_NOT_VESTED` otherwise)"

        Design: Difficulty/boundary_precision_check/vesting_exactly_five_years_qualifies
        """
        v5, _v4 = self._setup_two_members_at_boundary(api)
        member = validate_success(api.get_member(v5["id"], ANALYST), 200)
        assert member["total_service_years"] == pytest.approx(5.0)
        app = create_retirement_app(v5["id"], "SINGLE_LIFE")
        submitted = submit_retirement_app(app["id"], v5["id"])
        assert submitted["status"] == "SUBMITTED"

    def test_fifty_nine_months_rejected_not_vested(self, api):
        """PRD §3.5: "the member's `total_service_years` must be at least 5 —
        the vesting threshold (`ERR_NOT_VESTED` otherwise)"
        PRD §3.2: "The fund measures service in years to two decimal places,
        rounded half-up, and derives it from exactly two sources."

        Design: Difficulty/boundary_precision_check/vesting_exactly_five_years_qualifies
        """
        _v5, v4 = self._setup_two_members_at_boundary(api)
        member = validate_success(api.get_member(v4["id"], ANALYST), 200)
        assert member["total_service_years"] == pytest.approx(4.92)
        app = create_retirement_app(v4["id"], "SINGLE_LIFE")
        res = api.submit_retirement_application(
            app["id"], make_member_headers(v4["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_VESTED)


class TestApplicationStateGates:
    def test_approve_draft_application_returns_invalid_state(self, api):
        """PRD §2.8: "6. **State gates** — generic invalid from-state
        (`ERR_INVALID_STATE`), member lifecycle gates (`ERR_MEMBER_NOT_ACTIVE`,
        `ERR_MEMBER_DECEASED`), and resource-specific status gates
        (`ERR_PLAN_NOT_ACTIVE`, `ERR_BENEFIT_NOT_ACTIVE`,
        `ERR_BENEFIT_NOT_TERMINATED`)."
        PRD §3.5: "A retirement application is created in `DRAFT`"

        Design: Corner/state_machines/approve_draft_application_returns_invalid_state
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Draft Dan")
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        res = api.approve_retirement_application(
            app["id"], {"expected_application_version": app["version"]},
            APPROVER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_retirement_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "DRAFT"
        _benefits, meta = validate_paginated(
            api.list_member_benefits(member["id"], ANALYST))
        assert meta["total_count"] == 0

    def test_cancel_cancelled_application_returns_invalid_state(self, api):
        """PRD §3.5: "`APPROVED` and `CANCELLED` are the terminal states;
        cancelling an application directly is available to the member or an
        analyst from any non-terminal state."

        Design: Corner/state_machines/cancel_cancelled_application_returns_invalid_state
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Terminal Tina")
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        cancelled = validate_success(api.cancel_retirement_application(
            app["id"], make_member_headers(member["id"])), 200)
        assert cancelled["status"] == "CANCELLED"
        res = api.cancel_retirement_application(
            app["id"], make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_retirement_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "CANCELLED"

    def test_submit_requires_member_active(self, api):
        """PRD §3.5: "Three gates guard submission, and they are evaluated
        only after the generic checks of §2.8: the member must be `ACTIVE`
        (`ERR_MEMBER_NOT_ACTIVE` otherwise), the member's
        `total_service_years` must be at least 5 — the vesting threshold
        (`ERR_NOT_VESTED` otherwise) — and the member's age at the
        logical-clock date must be at least 60 completed years
        (`ERR_MEMBER_UNDER_RETIREMENT_AGE` otherwise)."

        Design: Corner/state_machines/submit_requires_member_active_guarded_transition
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Inactive Ivan")
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        validate_success(api.update_member(member["id"],
                                           {"status": "INACTIVE"}, ANALYST),
                         200)
        res = api.submit_retirement_application(
            app["id"], make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)
        after = validate_success(api.get_retirement_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "DRAFT"
        assert after.get("provisional_monthly_cents") is None

    def test_submit_under_retirement_age_returns_error(self, api):
        """PRD §3.5: "the member's age at the logical-clock date must be at
        least 60 completed years (`ERR_MEMBER_UNDER_RETIREMENT_AGE`
        otherwise)"

        Design: Corner/validations/submit_under_retirement_age_returns_error
        """
        ctx = setup_vested_member(full_name="Young Yara",
                                  date_of_birth="1967-01-01",
                                  line_specs_fn=five_year_line_specs)
        member = ctx["member"]
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        res = api.submit_retirement_application(
            app["id"], make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_MEMBER_UNDER_RETIREMENT_AGE)

    def test_second_active_application_returns_conflict(self, api):
        """PRD §3.5: "A member may hold at most one non-terminal retirement
        application and at most one non-terminal disability application at any
        time; a second create of the same type is rejected with
        `ERR_ACTIVE_APPLICATION_EXISTS` (HTTP 409)."

        Design: Corner/validations/second_active_application_returns_conflict
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Double Dora")
        create_retirement_app(member["id"], "SINGLE_LIFE")
        res = api.create_retirement_application(
            member["id"],
            {"option_election": "JOINT_50", "beneficiary_name": "B",
             "beneficiary_date_of_birth": "1970-01-01"},
            make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_ACTIVE_APPLICATION_EXISTS)
        _apps, meta = validate_paginated(
            api.list_member_retirement_applications(member["id"], ANALYST))
        assert meta["total_count"] == 1


class TestSegregationAndFiscalGates:
    def test_approve_by_reviewing_user_returns_segregation_error(self, api):
        """PRD §3.5: "the approver's `X-User-ID` must differ from the
        application's `reviewed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`,
        HTTP 403 — the reviewer may not approve their own review)."

        Design: Corner/validations/retirement_approve_same_user_as_reviewer_returns_segregation
        """
        ctx = setup_vested_member(full_name="Segregation Sid",
                                  line_specs_fn=five_year_line_specs)
        member = ctx["member"]
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        submit_retirement_app(app["id"], member["id"])
        review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
        version = current_application_version(app["id"])
        res = api.approve_retirement_application(
            app["id"], {"expected_application_version": version},
            make_approver_headers("analyst-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_retirement_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "UNDER_REVIEW"
        _benefits, meta = validate_paginated(
            api.list_member_benefits(member["id"], ANALYST))
        assert meta["total_count"] == 0

    def test_approve_with_plan_active_purchase_returns_outstanding_balance(
            self, api):
        """PRD §3.5: "no service purchase of the member may stand in
        `PLAN_ACTIVE` (`ERR_OUTSTANDING_BALANCE` — HTTP 422 — because the fund
        will not retire a member who still owes on a purchase)"

        Design: Corner/validations/approve_with_plan_active_purchase_returns_outstanding_balance
        """
        ctx = setup_vested_member(full_name="Balance Barb",
                                  line_specs_fn=five_year_line_specs)
        member = ctx["member"]
        setup_plan_active_purchase(member["id"])
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        submit_retirement_app(app["id"], member["id"])
        review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
        version = current_application_version(app["id"])
        res = api.approve_retirement_application(
            app["id"], {"expected_application_version": version}, APPROVER)
        validate_error(res, ApiErrorId.ERR_OUTSTANDING_BALANCE)
        after = validate_success(api.get_retirement_application(app["id"],
                                                                ANALYST), 200)
        assert after["status"] == "UNDER_REVIEW"
        _benefits, meta = validate_paginated(
            api.list_member_benefits(member["id"], ANALYST))
        assert meta["total_count"] == 0


class TestOptimisticConcurrency:
    def test_stale_application_version_returns_412_then_fresh_succeeds(
            self, api):
        """PRD §2.6: "Final approval of a retirement application requires
        `expected_application_version`, matching the current `version` of the
        application itself. If another writer — a review cycle, or any cascade
        — has advanced the application's version since the approver last read
        it, the approval is rejected, forcing the approver to re-read the
        application before re-issuing."
        PRD §3.5: "Finally, the application's own `version` increments by 1."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_retirement_approve_returns_412
        """
        ctx = setup_vested_member(full_name="Stale Stella",
                                  line_specs_fn=five_year_line_specs)
        member = ctx["member"]
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        submit_retirement_app(app["id"], member["id"])
        review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
        seen = validate_success(api.get_retirement_application(app["id"],
                                                               APPROVER), 200)
        ver_seen = seen["version"]
        review_retirement_app(app["id"], "RETURN", "analyst-1",
                              "recheck salary")
        review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")

        res = api.approve_retirement_application(
            app["id"], {"expected_application_version": ver_seen - 1},
            APPROVER)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.get_retirement_application(app["id"],
                                                                APPROVER), 200)
        approved = approve_retirement_app(app["id"], fresh["version"],
                                          "approver-1")
        assert approved["status"] == "APPROVED"
        assert approved["final_monthly_cents"] == 35_417
        assert approved["version"] == fresh["version"] + 1

    def test_stale_purchase_version_on_payment_returns_412(self, api):
        """PRD §2.6: "Applying an installment payment requires
        `expected_purchase_version`, matching the current `version` of the
        parent service purchase. Because each successful payment itself
        increments the purchase's `version`, a payer who has not re-read the
        purchase since the prior payment will be rejected, preventing a
        payment from being booked against a balance the payer never
        observed."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_purchase_payment_returns_412
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Stale Steve",
                               date_of_birth="1980-01-01",
                               hire_date="2024-06-01")
        reconcile_member_history(employer["id"], [{
            "member_id": member["id"], "fiscal_year": 2023,
            "salary_cents": 5_000_005, "contribution_cents": 400_000}])
        ctx = setup_plan_active_purchase(member["id"])
        purchase, payments = ctx["purchase"], ctx["payments"]
        pv0 = purchase["version"]
        purchase = pay_installment(purchase["id"], payments[0]["id"], pv0,
                                   member["id"])
        res = api.apply_payment(
            purchase["id"],
            {"payment_id": payments[1]["id"],
             "expected_purchase_version": pv0},
            make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_service_purchase(purchase["id"],
                                                          ANALYST), 200)
        assert after["balance_due_cents"] == 916_668
        assert list_payments_sorted(purchase["id"])[1]["status"] == "PENDING"


class TestImmediateConsistency:
    def test_approve_response_and_benefit_list_immediately_consistent(
            self, api):
        """PRD §3.5: "The FINAL benefit estimate runs and is stored as
        `final_monthly_cents`. A Benefit is created with `benefit_kind`
        `SERVICE`, `monthly_amount_cents` equal to the final amount, `status`
        `ACTIVE`, and `effective_date` set to the first day of the month
        containing the approval date on the logical clock. The member moves to
        `RETIRED`."

        Design: Corner/consistency_model/approve_response_and_benefit_list_immediately_consistent
        """
        ctx = setup_vested_member(full_name="Immediate Ida",
                                  line_specs_fn=five_year_line_specs)
        member = ctx["member"]
        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        submit_retirement_app(app["id"], member["id"])
        review_retirement_app(app["id"], "REVIEW_OK", "analyst-1")
        version = current_application_version(app["id"])
        approved = approve_retirement_app(app["id"], version, "approver-1")
        assert_retirement_application(approved)
        assert approved["status"] == "APPROVED"
        assert approved["final_monthly_cents"] == 35_417

        benefits, meta = validate_paginated(
            api.list_member_benefits(member["id"], ANALYST))
        assert meta["total_count"] == 1
        assert benefits[0]["status"] == "ACTIVE"
        assert benefits[0]["monthly_amount_cents"] == 35_417
        assert benefits[0]["effective_date"] == "2026-08-01"
        member_after = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert member_after["status"] == "RETIRED"
