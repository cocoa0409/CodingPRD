"""Monthly sales reporting: filing guards, review actions, the dispute/resubmit
revision loop, cross-entity active-lease gating, listing, and tenant RBAC."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_sales_report,
    create_draft_lease,
    create_sales_report_payload,
    create_tenant,
    file_and_accept_report,
    file_sales_report,
    make_tenant_headers,
    setup_active_lease,
    submit_sales_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestReportFiling:
    def test_sales_report_initial_state_is_draft(self, api):
        """PRD §3.3: "A new report is born in `DRAFT`."
        PRD §3.3: "Each submission stamps `submitted_at` with the logical clock —
        null until the first submission, refreshed on every resubmission — and
        increments the report's `version`."

        Design: Corner/state_machines/sales_report_initial_state_is_draft
        """
        sc = setup_active_lease()
        report = file_sales_report(sc["lease"], sc["tenant"], "2026-01", 100_000)
        assert_sales_report(report)
        assert report["status"] == "DRAFT"
        assert report["submitted_at"] is None

    def test_duplicate_report_period_returns_report_period_duplicate(self, api):
        """PRD §3.3: "Three guards apply at filing, in pipeline order (§2.8): only one
        report per lease and month may exist among the statuses `DRAFT`, `SUBMITTED`,
        `ACCEPTED`, and `ADJUSTED`, with a duplicate rejected as
        `ERR_REPORT_PERIOD_DUPLICATE`; then the period must not be after the logical
        clock's current month, else `ERR_REPORT_PERIOD_FUTURE`; then the sign rule on
        the gross figure."

        Design: Corner/validations/duplicate_report_period_returns_report_period_duplicate
        """
        sc = setup_active_lease()
        file_sales_report(sc["lease"], sc["tenant"], "2026-01", 100_000)
        res = api.create_sales_report(
            create_sales_report_payload(
                sc["lease"]["id"], period_month="2026-01", gross_sales_cents=200_000
            ),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REPORT_PERIOD_DUPLICATE)

    def test_future_report_period_returns_report_period_future(self, api):
        """PRD §3.3: "Three guards apply at filing, in pipeline order (§2.8): only one
        report per lease and month may exist among the statuses `DRAFT`, `SUBMITTED`,
        `ACCEPTED`, and `ADJUSTED`, with a duplicate rejected as
        `ERR_REPORT_PERIOD_DUPLICATE`; then the period must not be after the logical
        clock's current month, else `ERR_REPORT_PERIOD_FUTURE`; then the sign rule on
        the gross figure."
        PRD §2.4: "On startup the clock holds exactly `2026-08-01T00:00:00Z`, and it
        never falls back to the host's wall clock."

        Design: Corner/validations/future_report_period_returns_report_period_future
        """
        sc = setup_active_lease()
        res = api.create_sales_report(
            create_sales_report_payload(
                sc["lease"]["id"], period_month="2026-09", gross_sales_cents=100_000
            ),
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REPORT_PERIOD_FUTURE)


class TestReviewActions:
    def test_accept_draft_report_returns_report_not_reviewable(
        self, api, analyst_headers
    ):
        """PRD §3.3: "Acceptance, an `action` of `ACCEPT`, moves `SUBMITTED →
        ACCEPTED`; disputing, an `action` of `DISPUTE`, moves `SUBMITTED → DISPUTED`;
        either action attempted on a report that is not `SUBMITTED` is rejected with
        `ERR_REPORT_NOT_REVIEWABLE`."

        Design: Corner/state_machines/accept_draft_report_returns_report_not_reviewable
        """
        sc = setup_active_lease()
        report = file_sales_report(sc["lease"], sc["tenant"], "2026-01", 100_000)
        res = api.transition_sales_report(
            report["id"], {"action": "ACCEPT"}, analyst_headers
        )
        validate_error(res, ApiErrorId.ERR_REPORT_NOT_REVIEWABLE)


class TestDisputeResubmitCycle:
    def _setup_submitted_report(self):
        sc = setup_active_lease()
        report = file_sales_report(sc["lease"], sc["tenant"], "2026-03", 500_000)
        report = submit_sales_report(report, sc["tenant"])
        return sc, report

    def test_disputed_report_patch_revises_gross_in_place(self, api, analyst_headers):
        """PRD §3.3: "While a report is in `DRAFT` or `DISPUTED`, the owning tenant
        may revise its `gross_sales_cents`; each revision increments the report's
        `version`."
        PRD §3.3: "A dispute simply increments the report's `version`, opening the
        `SUBMITTED → DISPUTED → SUBMITTED` revision loop."

        Design: Difficulty/non_linear_state_machine/sales_report_dispute_resubmit_cycle
        """
        sc, report = self._setup_submitted_report()
        disputed = validate_success(
            api.transition_sales_report(
                report["id"], {"action": "DISPUTE"}, analyst_headers
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"

        revised = validate_success(
            api.patch_sales_report(
                report["id"],
                {"gross_sales_cents": 550_000},
                make_tenant_headers(sc["tenant"]["id"]),
            ),
            200,
        )
        assert revised["gross_sales_cents"] == 550_000
        assert revised["status"] == "DISPUTED", (
            "PATCH revises the report in place; it must not change the status"
        )

    def test_disputed_report_resubmit_closes_loop(self, api, analyst_headers):
        """PRD §3.3: "Submission — a transition request with an `action` of `SUBMIT` —
        moves the report to `SUBMITTED`. It is valid from `DRAFT` and, after analyst
        pushback, from `DISPUTED`; from any other status the submission is rejected
        with `ERR_REPORT_NOT_SUBMITTABLE`."

        Design: Difficulty/non_linear_state_machine/sales_report_dispute_resubmit_cycle
        """
        sc, report = self._setup_submitted_report()
        validate_success(
            api.transition_sales_report(
                report["id"], {"action": "DISPUTE"}, analyst_headers
            ),
            200,
        )
        validate_success(
            api.patch_sales_report(
                report["id"],
                {"gross_sales_cents": 550_000},
                make_tenant_headers(sc["tenant"]["id"]),
            ),
            200,
        )
        resubmitted = validate_success(
            api.transition_sales_report(
                report["id"],
                {"action": "SUBMIT"},
                make_tenant_headers(sc["tenant"]["id"]),
            ),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["gross_sales_cents"] == 550_000


class TestCrossEntityActiveLeaseGate:
    def test_submit_on_draft_lease_returns_lease_not_active(self, api):
        """PRD §3.3: "Submission re-checks that the lease is `ACTIVE` and that the
        acting tenant is the lease's concessionaire, and — following the pipeline of
        §2.8 — the lease-active check precedes the report-state check, so a submission
        against a non-active lease surfaces `ERR_LEASE_NOT_ACTIVE` regardless of the
        report's own status."
        PRD §3.3: "Filing itself does not gate on the lease's lifecycle status; the
        cross-entity active-lease gate, `ERR_LEASE_NOT_ACTIVE`, applies to exactly
        four operations in the system — report submission, buildout-draw creation,
        violation recording, and waiver creation — and each is covered in its own
        subsection."

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_active_lease
        """
        tenant = create_tenant()
        lease = create_draft_lease(tenant)  # never activated
        report = file_sales_report(lease, tenant, "2026-03", 100_000)
        res = api.transition_sales_report(
            report["id"], {"action": "SUBMIT"}, make_tenant_headers(tenant["id"])
        )
        validate_error(res, ApiErrorId.ERR_LEASE_NOT_ACTIVE)

    def test_submit_on_terminated_lease_returns_lease_not_active(
        self, api, admin_headers
    ):
        """PRD §3.3: "Submission re-checks that the lease is `ACTIVE` and that the
        acting tenant is the lease's concessionaire, and — following the pipeline of
        §2.8 — the lease-active check precedes the report-state check, so a submission
        against a non-active lease surfaces `ERR_LEASE_NOT_ACTIVE` regardless of the
        report's own status."

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_active_lease
        """
        sc = setup_active_lease()
        report = file_sales_report(sc["lease"], sc["tenant"], "2026-03", 100_000)
        validate_success(
            api.transition_lease(
                sc["lease"]["id"], {"action": "TERMINATE"}, admin_headers
            ),
            200,
        )
        res = api.transition_sales_report(
            report["id"],
            {"action": "SUBMIT"},
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LEASE_NOT_ACTIVE)


class TestPatchValidationPriority:
    def test_patch_submitted_report_negative_gross_state_error_wins(self, api):
        """PRD §2.8: "Every request is validated in a fixed pipeline, and a request
        that violates several checks surfaces the error from the earliest stage."
        PRD §2.8: "State-machine legality — the requested action is valid from the
        resource's current status, producing the relevant 409 state error (for example
        `ERR_LEASE_STATE_FORBIDS`, `ERR_REPORT_NOT_SUBMITTABLE`, or
        `ERR_DRAW_STATE_FORBIDS`)."
        PRD §3.3: "A revision attempted on a report in any other status is rejected
        with `ERR_REPORT_NOT_EDITABLE`."

        Design: Difficulty/priority_pair_validation_conflict/report_patch_state_beats_fiscal
        """
        sc = setup_active_lease()
        report = file_sales_report(sc["lease"], sc["tenant"], "2026-03", 500_000)
        report = submit_sales_report(report, sc["tenant"])
        # Both the editability rule (SUBMITTED report) and the sign rule
        # (gross_sales_cents -1) are violated; the state error is earlier in the
        # pipeline.
        res = api.patch_sales_report(
            report["id"],
            {"gross_sales_cents": -1},
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REPORT_NOT_EDITABLE)

    def test_patch_accepted_report_negative_gross_state_error_wins(self, api):
        """PRD §2.8: "Every request is validated in a fixed pipeline, and a request
        that violates several checks surfaces the error from the earliest stage."
        PRD §2.8: "Fiscal amount rules — sign and positivity rules, payment caps,
        allowance caps, and cure sufficiency."
        PRD §3.3: "A revision attempted on a report in any other status is rejected
        with `ERR_REPORT_NOT_EDITABLE`."

        Design: Difficulty/priority_pair_validation_conflict/report_patch_state_beats_fiscal
        """
        sc = setup_active_lease()
        report = file_and_accept_report(sc["lease"], sc["tenant"], "2026-03", 500_000)
        # ACCEPTED report + negative gross: state error (stage 6) precedes the
        # fiscal sign rule (stage 9).
        res = api.patch_sales_report(
            report["id"],
            {"gross_sales_cents": -1},
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REPORT_NOT_EDITABLE)


class TestListingAndFilters:
    def test_sales_report_listing_paginates_with_envelope(self, api, analyst_headers):
        """PRD §2.3: "Paginated list responses carry four fields in the `meta` object
        of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "`limit` caps the number of items returned; when omitted it
        defaults to 10, and it is bounded below by 1 and above by 100."

        Design: Corner/entities/sales_report_listing_paginates_with_envelope
        """
        sc = setup_active_lease()
        file_sales_report(sc["lease"], sc["tenant"], "2026-01", 100_000)
        file_sales_report(sc["lease"], sc["tenant"], "2026-02", 200_000)

        res = api.list_sales_reports(
            analyst_headers,
            params={"lease_id": sc["lease"]["id"], "limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert res.json()["response_type"] == "array"

    def test_fk_reverse_reachability_filtered_lists(self, api, analyst_headers):
        """PRD §4: "List endpoints accept `limit` and `offset` (§2.3) plus optional
        filter query parameters matching the resource's natural keys — `tenant_id`,
        `premises_code`, `status`, `lease_id`, `period_month`, or `kind`, depending
        on the collection."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        t1 = create_tenant()
        t2 = create_tenant(legal_name="DutyFree Inc", contact_email="ops@dutyfree.com")
        sc1 = {"tenant": t1}
        l1 = create_draft_lease(t1, premises_code="A1")
        validate_success(
            api.transition_lease(l1["id"], {"action": "ACTIVATE"},
                                 ADMIN),
            200,
        )
        l2 = create_draft_lease(
            t2,
            premises_code="D4",
            category="RETAIL",
            mag_annual_cents=900_000,
            pct_rate_below_bp=700,
            pct_breakpoint_cents=400_000,
            pct_rate_above_bp=900,
            acdbe_goal_bp=2500,
            ti_allowance_cents=200_000,
            min_spe_cents=900,
        )
        validate_success(
            api.transition_lease(l2["id"], {"action": "ACTIVATE"}, ADMIN),
            200,
        )
        file_sales_report(l1, t1, "2026-01", 100_000)

        leases_t1, meta_l1 = validate_paginated(
            api.list_leases(analyst_headers, params={"tenant_id": t1["id"]})
        )
        assert [l["id"] for l in leases_t1] == [l1["id"]]
        assert meta_l1["total_count"] == 1

        _, meta_r1 = validate_paginated(
            api.list_sales_reports(analyst_headers, params={"lease_id": l1["id"]})
        )
        assert meta_r1["total_count"] == 1

        _, meta_r2 = validate_paginated(
            api.list_sales_reports(analyst_headers, params={"lease_id": l2["id"]})
        )
        assert meta_r2["total_count"] == 0


class TestTenantRbac:
    def test_tenant_cannot_accept_report_returns_forbidden(self, api):
        """PRD §2.1: "Once authenticated, the acting role must appear in the
        endpoint's authorized role list as given in §4; otherwise the request is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.3: "Review belongs to the `ConcessionAnalyst`."

        Design: Corner/rbac/tenant_cannot_accept_report_returns_forbidden
        """
        sc = setup_active_lease()
        report = file_sales_report(sc["lease"], sc["tenant"], "2026-01", 100_000)
        submit_sales_report(report, sc["tenant"])
        res = api.transition_sales_report(
            report["id"],
            {"action": "ACCEPT"},
            make_tenant_headers(sc["tenant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_tenant_cannot_submit_others_report_returns_forbidden(self, api):
        """PRD §2.1: "A `Tenant` may read its own tenant record, its own leases, and
        the children of those leases, and may perform tenant-scoped writes — filing
        and revising sales reports, submitting them, posting payments, requesting and
        cancelling buildout draws, requesting closure waivers, and submitting ACDBE
        cure evidence — only where the owning lease's `tenant_id` equals `X-User-ID`;
        acting on another tenant's records is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/tenant_cannot_submit_others_report_returns_forbidden
        """
        sc = setup_active_lease()
        other_tenant = create_tenant(
            legal_name="DutyFree Inc", contact_email="ops@dutyfree.com"
        )
        report = file_sales_report(sc["lease"], sc["tenant"], "2026-01", 100_000)
        res = api.transition_sales_report(
            report["id"],
            {"action": "SUBMIT"},
            make_tenant_headers(other_tenant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

