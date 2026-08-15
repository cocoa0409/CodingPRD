"""Decision point: approval precondition ordering, segregation of duties,
income/cap fiscal ceilings with exact boundaries, award amount determination,
appeals, and waitlisting."""
from test_helpers import (
    ApiErrorId,
    approve_application,
    create_active_policy,
    create_application,
    create_funding_source,
    create_household,
    create_vendor,
    deny_application,
    drive_application_to_approved,
    drive_application_to_pending_decision,
    get_application,
    make_program_manager_headers,
    open_verification,
    get_application_version,
    resolve_duplication_check,
    set_clock,
    setup_approved,
    setup_pending_decision,
    setup_submitted_application,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    waitlist_application,
)

CW1 = TEST_USERS["caseworker_headers"]
PM1 = TEST_USERS["program_manager_headers"]


class TestApproveStateAndSegregation:
    def test_approve_from_intake_returns_invalid_state(self, api):
        """PRD §3.5: "The preconditions evaluate in the program's fixed order:
        the application must actually be in `PENDING_DECISION`
        (`ERR_INVALID_APPLICATION_STATE`); segregation of duties must hold against
        both the `intake_caseworker_id` and the `verifier_id` of the latest
        `PASSED` verification (`ERR_SEGREGATION_OF_DUTIES`); the duplication gates
        of the previous section must pass; and then the fiscal ceilings apply."

        Design: Corner/state_machines/approve_from_intake_returns_invalid_state
        """
        ctx = setup_submitted_application(requested_amount_cents=5000)
        # Back to INTAKE state check: use a fresh application that never submitted.
        application = create_application(
            ctx["household"]["id"], ctx["vendor"]["id"],
            requested_amount_cents=5000, service_month="2026-10",
        )
        resp = api.approve_application(application["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)
        awards, meta = validate_paginated(
            api.list_awards(PM1, params={"application_id": application["id"]})
        )
        assert meta["total_count"] == 0, "no award may be created by a failed approve"

    def test_sod_approver_cannot_be_intake_or_verifier(self, api):
        """PRD §2.8: "the `ProgramManager` who approves must differ both from
        `intake_caseworker_id` and from the `verifier_id` of the application's
        latest `PASSED` verification"
        PRD §2.8: "Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 409)."

        Design: Corner/validations/sod_approver_cannot_be_intake_or_verifier
        """
        ctx = setup_pending_decision(requested_amount_cents=5000)
        app_id = ctx["application"]["id"]
        resp1 = api.approve_application(app_id, make_program_manager_headers("cw-1"))
        validate_error(resp1, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        resp2 = api.approve_application(app_id, make_program_manager_headers("cw-2"))
        validate_error(resp2, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_application(app_id)["status"] == "PENDING_DECISION"
        # Control: a third, segregation-clean manager approves successfully.
        approved = approve_application(app_id)
        assert approved["status"] == "APPROVED"


class TestIncomeBoundary:
    def test_income_exactly_at_limit_is_eligible_for_waitlist(self, api):
        """PRD §3.5: "The income screen is inclusive at the boundary: a household
        whose `annual_income_cents` is less than or equal to the pinned policy's
        `income_limit_cents` is eligible, while income even one cent above the
        limit is rejected with `ERR_INCOME_LIMIT_EXCEEDED`."
        PRD §3.5: "Waitlisting enforces the same segregation, duplication, income,
        and cap preconditions as approval — but deliberately does not check funds
        availability."

        Design: Difficulty/boundary_precision_check/income_limit_inclusive_boundary
        """
        ctx = setup_pending_decision(
            requested_amount_cents=5000,
            household_overrides={"annual_income_cents": 5000000},
        )
        waitlisted = waitlist_application(ctx["application"]["id"])
        assert waitlisted["status"] == "WAITLISTED", (
            "income exactly equal to income_limit_cents is eligible"
        )

    def test_income_one_cent_over_limit_rejected_on_waitlist(self, api):
        """PRD §3.5: "The income screen is inclusive at the boundary: a household
        whose `annual_income_cents` is less than or equal to the pinned policy's
        `income_limit_cents` is eligible, while income even one cent above the
        limit is rejected with `ERR_INCOME_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/income_limit_inclusive_boundary
        """
        ctx = setup_pending_decision(
            requested_amount_cents=5000,
            household_overrides={"annual_income_cents": 5000001},
        )
        resp = api.waitlist_application(ctx["application"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_INCOME_LIMIT_EXCEEDED)
        assert get_application(ctx["application"]["id"])["status"] == "PENDING_DECISION"


class TestCapBoundaries:
    def _policy_and_source(self):
        create_active_policy(
            name="P1", max_annual_benefit_cents=10000, rent_cap_cents=20000,
            utility_cap_cents=20000, income_limit_cents=5000000,
        )
        vendor = create_vendor("LANDLORD")
        source = create_funding_source(total_budget_cents=50000)
        return vendor, source

    def test_annual_cap_exactly_zero_remaining_rejected(self, api):
        """PRD §3.5: "When the remaining annual cap is exactly zero, approval
        fails with `ERR_ANNUAL_CAP_EXCEEDED`; when the remaining category cap is
        exactly zero, it fails with `ERR_CATEGORY_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/annual_cap_zero_vs_exact_fit
        """
        vendor, _ = self._policy_and_source()
        household_a = create_household(
            head_of_household_name="Pat Fox", annual_income_cents=1000000
        )
        drive_application_to_approved(
            household_a["id"], vendor["id"], requested_amount_cents=10000,
            service_month="2026-08",
        )
        second = drive_application_to_pending_decision(
            household_a["id"], vendor["id"], requested_amount_cents=500,
            service_month="2026-09",
        )
        resp = api.approve_application(second["application"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED)
        assert (
            get_application(second["application"]["id"])["status"] == "PENDING_DECISION"
        )

    def test_annual_cap_exact_fit_approved_landing_on_zero(self, api):
        """PRD §3.5: "The remaining annual cap is the pinned policy's
        `max_annual_benefit_cents` minus the year-to-date exposure, and the
        remaining category cap is `rent_cap_cents` or `utility_cap_cents` minus
        the matching category figure."
        PRD §3.5: "When the remaining annual cap is exactly zero, approval fails
        with `ERR_ANNUAL_CAP_EXCEEDED`; when the remaining category cap is
        exactly zero, it fails with `ERR_CATEGORY_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/annual_cap_zero_vs_exact_fit
        """
        vendor, _ = self._policy_and_source()
        household_b = create_household(
            head_of_household_name="Quinn Day", annual_income_cents=1000000
        )
        drive_application_to_approved(
            household_b["id"], vendor["id"], requested_amount_cents=9900,
            service_month="2026-08",
        )
        second = drive_application_to_pending_decision(
            household_b["id"], vendor["id"], requested_amount_cents=100,
            service_month="2026-09",
        )
        approved = approve_application(second["application"]["id"])
        award = validate_success(api.get_award(approved["active_award_id"], PM1), 200)
        assert award["awarded_amount_cents"] == 100, (
            "exact fit: 9900 + 100 == 10000 == max_annual_benefit_cents"
        )
        summary = validate_success(api.get_benefit_summary(household_b["id"], PM1), 200)
        assert summary["remaining_annual_cap_cents"] == 0, (
            "zero remaining is a legal outcome of an exact-fit approval"
        )

    def test_category_cap_zero_remaining_rejected(self, api):
        """PRD §3.5: "When the remaining annual cap is exactly zero, approval
        fails with `ERR_ANNUAL_CAP_EXCEEDED`; when the remaining category cap is
        exactly zero, it fails with `ERR_CATEGORY_CAP_EXCEEDED`."

        Design: Corner/validations/category_cap_zero_remaining_rejected
        """
        create_active_policy(
            name="P1", max_annual_benefit_cents=100000, rent_cap_cents=50000,
            utility_cap_cents=30000, income_limit_cents=5000000,
        )
        vendor = create_vendor(vendor_type="UTILITY", name="City Power & Light")
        create_funding_source(total_budget_cents=200000)
        household = create_household()
        drive_application_to_approved(
            household["id"], vendor["id"], category="UTILITY",
            requested_amount_cents=30000, service_month="2026-08",
        )
        second = drive_application_to_pending_decision(
            household["id"], vendor["id"], category="UTILITY",
            requested_amount_cents=5000, service_month="2026-09",
        )
        resp = api.approve_application(second["application"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_CAP_EXCEEDED)


class TestPrecedencePairs:
    def test_state_beats_fiscal_on_approve(self, api):
        """PRD §3.5: "The preconditions evaluate in the program's fixed order:
        the application must actually be in `PENDING_DECISION`
        (`ERR_INVALID_APPLICATION_STATE`); segregation of duties must hold against
        both the `intake_caseworker_id` and the `verifier_id` of the latest
        `PASSED` verification (`ERR_SEGREGATION_OF_DUTIES`); the duplication gates
        of the previous section must pass; and then the fiscal ceilings apply."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_approve
        """
        ctx = setup_submitted_application(
            requested_amount_cents=20000,
            household_overrides={"annual_income_cents": 6000000},  # over the limit
        )
        app_id = ctx["application"]["id"]
        open_verification(app_id, get_application_version(app_id))  # left PENDING
        assert get_application(app_id)["status"] == "UNDER_VERIFICATION"
        resp = api.approve_application(app_id, PM1)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)
        awards, meta = validate_paginated(
            api.list_awards(PM1, params={"application_id": app_id})
        )
        assert meta["total_count"] == 0, "no award may be created by a failed approve"

    def test_fiscal_income_error_surfaces_once_state_passes(self, api):
        """PRD §3.5: "The preconditions evaluate in the program's fixed order:
        the application must actually be in `PENDING_DECISION`
        (`ERR_INVALID_APPLICATION_STATE`); segregation of duties must hold against
        both the `intake_caseworker_id` and the `verifier_id` of the latest
        `PASSED` verification (`ERR_SEGREGATION_OF_DUTIES`); the duplication gates
        of the previous section must pass; and then the fiscal ceilings apply."
        PRD §3.5: "The income screen is inclusive at the boundary: a household
        whose `annual_income_cents` is less than or equal to the pinned policy's
        `income_limit_cents` is eligible, while income even one cent above the
        limit is rejected with `ERR_INCOME_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_approve
        """
        # Same over-limit household, but now state and safety gates all pass, so
        # the fiscal ceiling is the one that fires — proving the earlier test's
        # ERR_INVALID_APPLICATION_STATE masked an equally-failing fiscal check.
        ctx = setup_pending_decision(
            requested_amount_cents=20000,
            household_overrides={"annual_income_cents": 6000000},
        )
        resp = api.approve_application(ctx["application"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_INCOME_LIMIT_EXCEEDED)

    def test_safety_beats_fiscal_on_approve(self, api):
        """PRD §3.5: "The preconditions evaluate in the program's fixed order:
        the application must actually be in `PENDING_DECISION`
        (`ERR_INVALID_APPLICATION_STATE`); segregation of duties must hold against
        both the `intake_caseworker_id` and the `verifier_id` of the latest
        `PASSED` verification (`ERR_SEGREGATION_OF_DUTIES`); the duplication gates
        of the previous section must pass; and then the fiscal ceilings apply."
        PRD §3.4: "Approving or waitlisting an application that has no duplication
        check recorded at all is rejected with `ERR_DUPLICATION_CHECK_REQUIRED`,
        and the same actions are rejected with `ERR_DUPLICATION_UNRESOLVED` while
        any of the application's checks remains `PENDING` or `FLAGGED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_approve
        """
        ctx = setup_pending_decision(
            requested_amount_cents=20000,
            household_overrides={"annual_income_cents": 6000000},  # over the limit
            resolve_check=None,  # duplication check left PENDING
        )
        resp = api.approve_application(ctx["application"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATION_UNRESOLVED)
        assert (
            get_application(ctx["application"]["id"])["status"] == "PENDING_DECISION"
        )

    def test_fiscal_income_error_surfaces_once_duplication_clears(self, api):
        """PRD §3.5: "The preconditions evaluate in the program's fixed order:
        the application must actually be in `PENDING_DECISION`
        (`ERR_INVALID_APPLICATION_STATE`); segregation of duties must hold against
        both the `intake_caseworker_id` and the `verifier_id` of the latest
        `PASSED` verification (`ERR_SEGREGATION_OF_DUTIES`); the duplication gates
        of the previous section must pass; and then the fiscal ceilings apply."
        PRD §3.5: "The income screen is inclusive at the boundary: a household
        whose `annual_income_cents` is less than or equal to the pinned policy's
        `income_limit_cents` is eligible, while income even one cent above the
        limit is rejected with `ERR_INCOME_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_approve
        """
        ctx = setup_pending_decision(
            requested_amount_cents=20000,
            household_overrides={"annual_income_cents": 6000000},
            resolve_check=None,
        )
        resolve_duplication_check(ctx["check"]["id"], "CLEARED")
        resp = api.approve_application(ctx["application"]["id"], PM1)
        validate_error(resp, ApiErrorId.ERR_INCOME_LIMIT_EXCEEDED)


class TestAwardAmountDetermination:
    def test_vendor_confirmed_amount_truncates_request(self, api):
        """PRD §3.5: "The approved amount is the smallest of four figures: the
        application's `requested_amount_cents`, the latest `PASSED` verification's
        `confirmed_amount_cents`, the remaining annual cap, and the remaining
        category cap for the application's category."

        Design: Corner/calculations/vendor_confirmed_amount_truncates_request
        """
        ctx = setup_pending_decision(
            requested_amount_cents=50000, confirmed_amount_cents=40000,
            policy_overrides={"rent_cap_cents": 60000},
        )
        approved = approve_application(ctx["application"]["id"])
        award = validate_success(api.get_award(approved["active_award_id"], PM1), 200)
        assert award["awarded_amount_cents"] == 40000, (
            "confirmed < requested: the confirmed amount binds"
        )

    def test_nested_min_category_cap_binds_award_amount(self, api):
        """PRD §3.5: "The approved amount is the smallest of four figures: the
        application's `requested_amount_cents`, the latest `PASSED` verification's
        `confirmed_amount_cents`, the remaining annual cap, and the remaining
        category cap for the application's category."

        Design: Difficulty/combinatorial_formula/award_amount_nested_min_category_cap_binds
        """
        create_active_policy(
            name="P1", max_annual_benefit_cents=100000, rent_cap_cents=50000,
            utility_cap_cents=40000, income_limit_cents=5000000,
        )
        vendor = create_vendor("LANDLORD")
        source = create_funding_source(total_budget_cents=200000)
        household = create_household(annual_income_cents=1200000)
        drive_application_to_approved(
            household["id"], vendor["id"], requested_amount_cents=35000,
            service_month="2026-08",
        )
        second = drive_application_to_pending_decision(
            household["id"], vendor["id"], requested_amount_cents=80000,
            confirmed_amount_cents=65000, service_month="2026-09",
        )
        approved = approve_application(second["application"]["id"])
        award = validate_success(api.get_award(approved["active_award_id"], PM1), 200)
        # min(requested 80000, confirmed 65000, remaining annual 65000,
        #     remaining rent 15000) — the rent-category cap binds.
        assert award["awarded_amount_cents"] == min(80000, 65000, 65000, 15000)
        source_after = validate_success(api.get_funding_source(source["id"], PM1), 200)
        assert source_after["reserved_cents"] == 50000  # 35000 + 15000

    def test_nested_min_category_cap_binds_benefit_summary_side(self, api):
        """PRD §3.5: "The year-to-date exposure is the sum of those awards'
        `awarded_amount_cents`, counted in full even when approved-but-unpaid;
        category year-to-date figures restrict the same sum to awards whose
        application category is `RENT` or `UTILITY` respectively."
        PRD §3.9: "A household's benefit summary answers with the current
        `benefit_year`, the household's `ytd_exposure_cents` and
        `ytd_committed_cents`, the `remaining_annual_cap_cents`, the per-category
        `rent_ytd_cents` and `utility_ytd_cents`, and the
        `remaining_rent_cap_cents` and `remaining_utility_cap_cents`, all
        evaluated against the currently `ACTIVE` policy."

        Design: Difficulty/combinatorial_formula/award_amount_nested_min_category_cap_binds
        """
        create_active_policy(
            name="P1", max_annual_benefit_cents=100000, rent_cap_cents=50000,
            utility_cap_cents=40000, income_limit_cents=5000000,
        )
        vendor = create_vendor("LANDLORD")
        create_funding_source(total_budget_cents=200000)
        household = create_household(annual_income_cents=1200000)
        drive_application_to_approved(
            household["id"], vendor["id"], requested_amount_cents=35000,
            service_month="2026-08",
        )
        second = drive_application_to_pending_decision(
            household["id"], vendor["id"], requested_amount_cents=80000,
            confirmed_amount_cents=65000, service_month="2026-09",
        )
        approve_application(second["application"]["id"])
        summary = validate_success(api.get_benefit_summary(household["id"], PM1), 200)
        assert summary["ytd_exposure_cents"] == 50000  # 35000 + 15000
        assert summary["rent_ytd_cents"] == 50000
        assert summary["remaining_annual_cap_cents"] == 50000
        assert summary["remaining_rent_cap_cents"] == 0


class TestAppealWindow:
    def _denied_application(self):
        ctx = setup_pending_decision(requested_amount_cents=5000)
        denied = deny_application(ctx["application"]["id"], "PROGRAM_DIRECTED")
        assert denied["status"] == "DENIED"
        return ctx

    def test_appeal_reopens_denied_within_window(self, api):
        """PRD §3.5: "The window is measured against the application's pinned
        policy: the deadline is `denied_at` plus the policy's `appeal_window_days`,
        and the boundary is inclusive — an appeal arriving exactly at the deadline
        succeeds, while one a single second past it is rejected with
        `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/state_machines/appeal_reopens_denied_within_window
        """
        ctx = self._denied_application()  # denied at 2026-08-01T00:00:00Z
        set_clock("2026-08-31T00:00:00Z")  # exactly denied_at + 30 days
        resp = api.appeal_application(
            ctx["application"]["id"],
            {"appeal_reason": "new eviction documentation obtained"},
            CW1,
        )
        appealed = validate_success(resp, 200)
        assert appealed["status"] == "PENDING_DECISION"

    def test_appeal_after_window_returns_window_closed(self, api):
        """PRD §3.5: "The window is measured against the application's pinned
        policy: the deadline is `denied_at` plus the policy's `appeal_window_days`,
        and the boundary is inclusive — an appeal arriving exactly at the deadline
        succeeds, while one a single second past it is rejected with
        `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/state_machines/appeal_after_window_returns_window_closed
        """
        ctx = self._denied_application()  # denied at 2026-08-01T00:00:00Z
        set_clock("2026-08-31T00:00:01Z")  # one second past the deadline
        resp = api.appeal_application(
            ctx["application"]["id"], {"appeal_reason": "too late"}, CW1
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
        assert get_application(ctx["application"]["id"])["status"] == "DENIED"
