"""Rate development: line ordering, break-even waiver flow, the rate cap,
the review/reject loop, activation gating, and projected-vs-actual divergence
(PRD §3.5, §3.13)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_rate_line_payload,
    make_finance_headers,
    create_instrument, open_fiscal_year, create_draft_rate_set,
    create_effective_rate_set, create_maintenance_contract,
    setup_canonical_stack, create_approved_booking, open_batch,
    finalize_batch, run_session_to_completed, create_and_validate_usage_log,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
STAFF2 = TEST_USERS["staff2_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestRateLineOrdering:
    def test_rate_order_invalid_line(self, api):
        """PRD §3.5: "Every rate line, at both creation and edit time, must
        satisfy `external_rate_cents_per_hour` at least equal to
        `internal_rate_cents_per_hour`; a violation is
        `ERR_RATE_ORDER_INVALID`."

        Design: Corner/validations/rate_order_invalid_line
        """
        i1 = create_instrument()
        open_fiscal_year(2027)
        res = api.create_rate_set(
            {
                "fiscal_year": 2027,
                "effective_from": "2027-01-01T00:00:00Z",
                "lines": [create_rate_line_payload(
                    i1["id"], internal_rate_cents_per_hour=12000,
                    external_rate_cents_per_hour=11000,
                )],
            },
            ADMIN,
        )
        validate_error(res, "ERR_RATE_ORDER_INVALID", expected_status=422)


class TestBreakEvenWaiverFlow:
    def test_break_even_waiver_flow(self, api):
        """PRD §3.5: "The verdict per line, recorded in `line_verdicts` as
        `break_even_verdict`, is `PASS` when projected revenue is at least
        projected cost, and `DEFICIT` otherwise" and "every line whose verdict
        is `DEFICIT` must carry a non-null `break_even_waiver_reason`
        (`ERR_BREAK_EVEN_WAIVER_REQUIRED` otherwise), and each waived line is
        then recorded as `WAIVED`". PRD §3.5: "Rejection instead returns the
        set from `UNDER_REVIEW` to `DRAFT`, optionally carrying a `reason`."

        Design: Corner/validations/break_even_waiver_flow
        """
        i1 = create_instrument()
        open_fiscal_year(2027)
        rs27 = create_draft_rate_set(
            i1["id"], fiscal_year=2027, effective_from="2027-01-01T00:00:00Z",
            line_overrides={"internal_rate_cents_per_hour": 12500,
                            "external_rate_cents_per_hour": 19000,
                            "projected_billable_hours": 5},
        )
        validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)
        # DEFICIT: 12500 x 5 = 62500 < 120000 overhead (no contracts on i1).
        blocked = api.approve_rate_set(rs27["id"], FINANCE)
        validate_error(blocked, "ERR_BREAK_EVEN_WAIVER_REQUIRED",
                       expected_status=422)

        rejected = validate_success(
            api.reject_rate_set(rs27["id"], FINANCE,
                                payload={"reason": "needs waiver"}),
            200,
        )
        edited = validate_success(
            api.edit_rate_set(
                rs27["id"],
                {"expected_rate_set_version": rejected["version"],
                 "lines": [create_rate_line_payload(
                     i1["id"], internal_rate_cents_per_hour=12500,
                     external_rate_cents_per_hour=19000,
                     projected_billable_hours=5,
                     break_even_waiver_reason="strategic instrument, deficit accepted",
                 )]},
                ADMIN,
            ),
            200,
        )
        validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)
        approved = validate_success(api.approve_rate_set(rs27["id"], FINANCE), 200)
        assert approved["status"] == "APPROVED"
        verdicts = approved["line_verdicts"]
        assert verdicts[0]["break_even_verdict"] == "WAIVED", (
            "a waived DEFICIT line is recorded as WAIVED"
        )


class TestRateCapBoundary:
    def _setup(self, api):
        """FY2026 EFFECTIVE at internal 12000; FY2027 OPEN; two DRAFT sets for
        2027 at 13200 (exactly 110%) and 13201 (one cent over)."""
        i1 = create_instrument()
        open_fiscal_year(2026)
        open_fiscal_year(2027)
        create_effective_rate_set(i1["id"], fiscal_year=2026)
        rs27a = create_draft_rate_set(
            i1["id"], fiscal_year=2027, effective_from="2027-01-01T00:00:00Z",
            line_overrides={"internal_rate_cents_per_hour": 13200,
                            "external_rate_cents_per_hour": 19000},
        )
        rs27b = create_draft_rate_set(
            i1["id"], fiscal_year=2027, effective_from="2027-01-01T00:00:00Z",
            line_overrides={"internal_rate_cents_per_hour": 13201,
                            "external_rate_cents_per_hour": 19000},
        )
        return i1, rs27a, rs27b

    def test_rate_exactly_at_cap_allowed(self, api):
        """PRD §3.5: "the new rate must be less than or equal to the prior rate
        multiplied by 1.10 — unless the submitter supplies an
        `override_justification`. A line exactly at the cap is allowed; a line
        beyond it without justification is rejected with
        `ERR_RATE_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/rate_cap_exact_boundary_at_submit
        """
        i1, rs27a, rs27b = self._setup(api)
        submitted = validate_success(api.submit_rate_set(rs27a["id"], ADMIN), 200)
        assert submitted["status"] == "UNDER_REVIEW", (
            "13200 == 12000 x 1.10 exactly: allowed (<= semantics)"
        )

    def test_one_cent_over_cap_rejected(self, api):
        """PRD §3.5: "the new rate must be less than or equal to the prior rate
        multiplied by 1.10 — unless the submitter supplies an
        `override_justification`. A line exactly at the cap is allowed; a line
        beyond it without justification is rejected with
        `ERR_RATE_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/rate_cap_exact_boundary_at_submit
        """
        i1, rs27a, rs27b = self._setup(api)
        res = api.submit_rate_set(rs27b["id"], ADMIN)
        validate_error(res, "ERR_RATE_CAP_EXCEEDED", expected_status=422)
        after = validate_success(api.get_rate_set(rs27b["id"], ADMIN), 200)
        assert after["status"] == "DRAFT", "a rejected submit must not transition"


class TestReviewRejectLoop:
    def _setup(self, api):
        """Instrument + FY2027 + DRAFT rs27 developed by admin-1."""
        i1 = create_instrument()
        open_fiscal_year(2027)
        rs27 = create_draft_rate_set(
            i1["id"], fiscal_year=2027, effective_from="2027-01-01T00:00:00Z",
            line_overrides={"internal_rate_cents_per_hour": 12500,
                            "external_rate_cents_per_hour": 18000},
        )
        return i1, rs27

    def test_review_loop_statuses_and_version_increments(self, api):
        """PRD §3.5: "Rejection instead returns the set from `UNDER_REVIEW` to
        `DRAFT`, optionally carrying a `reason`." PRD §2.6: "`version` is a
        system-managed integer that increments by 1 on every mutation,
        including mutations driven by system cascades".

        Design: Difficulty/non_linear_state_machine/rate_set_review_reject_loop
        """
        i1, rs27 = self._setup(api)
        v_create = rs27["version"]
        under_review = validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)
        assert under_review["status"] == "UNDER_REVIEW"
        assert under_review["version"] == v_create + 1
        back_to_draft = validate_success(
            api.reject_rate_set(rs27["id"], FINANCE,
                                payload={"reason": "revise external rate"}),
            200,
        )
        assert back_to_draft["status"] == "DRAFT"
        assert back_to_draft["version"] == v_create + 2
        edited = validate_success(
            api.edit_rate_set(
                rs27["id"],
                {"expected_rate_set_version": back_to_draft["version"],
                 "lines": [create_rate_line_payload(
                     i1["id"], internal_rate_cents_per_hour=12500,
                     external_rate_cents_per_hour=19000,
                 )]},
                ADMIN,
            ),
            200,
        )
        assert edited["version"] == v_create + 3
        resubmitted = validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["version"] == v_create + 4
        approved = validate_success(api.approve_rate_set(rs27["id"], FINANCE), 200)
        assert approved["status"] == "APPROVED"
        assert approved["version"] == v_create + 5

    def test_loop_records_actors_and_recomputes_verdicts(self, api):
        """PRD §3.5: "The creating operator's `X-User-ID` is recorded as
        `developed_by`." and "Approval stamps `approved_by` with the approver's
        operator id." and "Submitting the set moves `DRAFT → UNDER_REVIEW` and
        triggers the projected break-even review."

        Design: Difficulty/non_linear_state_machine/rate_set_review_reject_loop
        """
        i1, rs27 = self._setup(api)
        assert rs27["developed_by"] == "admin-1"
        validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)
        rejected = validate_success(api.reject_rate_set(rs27["id"], FINANCE), 200)
        validate_success(
            api.edit_rate_set(
                rs27["id"],
                {"expected_rate_set_version": rejected["version"],
                 "lines": [create_rate_line_payload(
                     i1["id"], internal_rate_cents_per_hour=12500,
                     external_rate_cents_per_hour=19000,
                 )]},
                ADMIN,
            ),
            200,
        )
        resubmitted = validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)
        # Recomputed verdicts: 12500 x 500 = 6250000 >= 120000 overhead.
        assert resubmitted["line_verdicts"][0]["break_even_verdict"] == "PASS"
        approved = validate_success(api.approve_rate_set(rs27["id"], FINANCE), 200)
        assert approved["approved_by"] == "fin-1"
        assert approved["developed_by"] == "admin-1"


class TestActivationGatedByFiscalYear:
    def _setup(self, api):
        """FY2027 period; rs27 (effective_from already in the past) APPROVED
        while FY2027 is OPEN; then FY2027 is closed (no batches)."""
        i1 = create_instrument()
        fy27 = open_fiscal_year(2027)
        rs27 = create_draft_rate_set(
            i1["id"], fiscal_year=2027, effective_from="2026-07-01T00:00:00Z",
            line_overrides={"internal_rate_cents_per_hour": 12500,
                            "external_rate_cents_per_hour": 19000},
        )
        validate_success(api.submit_rate_set(rs27["id"], ADMIN), 200)
        approved = validate_success(api.approve_rate_set(rs27["id"], FINANCE), 200)
        return i1, fy27, rs27, approved

    def test_approve_while_open_then_activate_after_close_fails(self, api):
        """PRD §3.5: "Activation moves `APPROVED → EFFECTIVE`, gated on the
        current logical time being at or after `effective_from` and the fiscal
        year period still being `OPEN` (`ERR_FY_CLOSED`)."

        Design: Difficulty/cross_entity_state_dependency/rate_activation_gated_by_fiscal_year_state
        """
        i1, fy27, rs27, approved = self._setup(api)
        assert approved["status"] == "APPROVED", (
            "approval succeeded while the fiscal year was OPEN"
        )
        validate_success(api.close_fiscal_year(fy27["id"], FINANCE), 200)
        res = api.activate_rate_set(rs27["id"], FINANCE)
        validate_error(res, "ERR_FY_CLOSED", expected_status=409)

    def test_failed_activation_leaves_set_approved(self, api):
        """PRD §3.5: "Activation moves `APPROVED → EFFECTIVE`, gated on the
        current logical time being at or after `effective_from` and the fiscal
        year period still being `OPEN` (`ERR_FY_CLOSED`)."

        Design: Difficulty/cross_entity_state_dependency/rate_activation_gated_by_fiscal_year_state
        """
        i1, fy27, rs27, approved = self._setup(api)
        validate_success(api.close_fiscal_year(fy27["id"], FINANCE), 200)
        validate_error(
            api.activate_rate_set(rs27["id"], FINANCE), "ERR_FY_CLOSED"
        )
        after = validate_success(api.get_rate_set(rs27["id"], FINANCE), 200)
        assert after["status"] == "APPROVED", (
            "effective_from in the past does not rescue activation once CLOSED"
        )


class TestProjectedVsActualBreakEven:
    def _setup(self, api):
        """Canonical stack plus a 50000-cent/year contract on i1; one 74-minute
        validated session (entry net 15000) in a finalized 2026-09 batch."""
        stack = setup_canonical_stack(with_contract=True)
        diagnostic = validate_success(
            api.get_rate_set_break_even(stack["rs"]["id"], FINANCE), 200
        )
        b1 = create_approved_booking(stack)
        batch = open_batch(2026, 9)
        completed = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        create_and_validate_usage_log(
            completed, "2026-09-01T09:00:00Z", "2026-09-01T10:14:00Z"
        )
        finalize_batch(batch["id"])
        return stack, diagnostic

    def test_projected_variant_passes(self, api):
        """PRD §3.5: "The verdict per line, recorded in `line_verdicts` as
        `break_even_verdict`, is `PASS` when projected revenue is at least
        projected cost, and `DEFICIT` otherwise" and "The per-line break-even
        computation is also exposed as a read-only diagnostic returning the
        `fiscal_year`, an `overall_verdict`, and the per-line verdict array."

        Design: Difficulty/dual_variant_calc/break_even_projected_vs_actual_on_rate_set
        """
        stack, diagnostic = self._setup(api)
        # Projected: 12000 cents/h x 500 h = 6000000 >= 50000 + 120000 cost.
        assert diagnostic["fiscal_year"] == 2026
        assert diagnostic["overall_verdict"] == "PASS"
        assert diagnostic["lines"][0]["break_even_verdict"] == "PASS"

    def test_actual_variant_shows_deficit_at_close(self, api):
        """PRD §3.13: "`cost_cents` is the sum of `annual_cost_cents` over
        every maintenance contract whose coverage window intersects the fiscal
        year — full cost, no proration — plus 120,000 cents of operating
        overhead for each instrument that has at least one counted revenue
        entry in the year. `surplus_deficit_cents` is revenue minus cost,
        signed; `carryforward_out_cents` equals it".

        Design: Difficulty/dual_variant_calc/break_even_projected_vs_actual_on_rate_set
        """
        stack, diagnostic = self._setup(api)
        assert diagnostic["overall_verdict"] == "PASS", "projected PASS"
        closed = validate_success(
            api.close_fiscal_year(stack["fy"]["id"], FINANCE), 200
        )
        # Actual: revenue 15000 - cost (50000 + 120000) = -155000.
        assert closed["revenue_cents"] == 15000
        assert closed["cost_cents"] == 170000
        assert closed["surplus_deficit_cents"] == -155000, (
            "the actual variant diverges from the projected PASS"
        )
