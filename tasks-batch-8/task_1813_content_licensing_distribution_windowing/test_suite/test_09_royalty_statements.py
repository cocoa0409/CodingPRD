"""Royalty statements: attribution modes, per-report rounding order, snapshot
finalization, period overlap, and finalize/mark-paid state guards."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_slot,
    advance_clock,
    assert_royalty_statement,
    book_report,
    create_direct_license,
    create_rights_holder,
    create_statement,
    finalize_statement,
    get_success_data,
    make_finance_analyst_headers,
    make_finance_controller_headers,
    setup_catalog,
    validate_error,
)

RM = TEST_USERS["rights_manager_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]


def _revenue_share_license(workspace, revenue_share_pct=50):
    slot = add_slot(workspace)
    return create_direct_license(
        slot["id"], workspace["platform"]["id"],
        license_start="2026-08-01T00:00:00Z",
        license_end="2027-08-01T00:00:00Z",
        fee_model="REVENUE_SHARE",
        revenue_share_pct=revenue_share_pct,
    )


def _two_september_reports(api, workspace):
    """R1 (usage August, submitted 2026-09-02) and R2 (usage mid-Aug to mid-Sep,
    submitted 2026-09-20); logical clock parked at 2026-09-30 afterwards."""
    license_agreement = _revenue_share_license(workspace)
    buyer = workspace["buyer_headers"]
    lid = license_agreement["id"]

    advance_clock("2026-09-02T00:00:00Z")
    r1 = book_report(lid, buyer, "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z", 1000)
    advance_clock("2026-09-20T00:00:00Z")
    r2 = book_report(lid, buyer, "2026-08-15T00:00:00Z", "2026-09-15T00:00:00Z", 3000)
    advance_clock("2026-09-30T00:00:00Z")
    return r1, r2


class TestAttributionModes:
    def test_by_report_date_includes_both_september_submissions(self, api):
        """PRD §3.9: "Under `BY_REPORT_DATE`, a report is included when its `submitted_at` falls inside the closed interval from `period_start` to `period_end`, both ends inclusive."
        PRD §3.9: "`gross_revenue_cents` is the sum of `gross_revenue_cents` over included reports. `studio_net_royalty_cents` is the sum of `payable_cents` over included reports — the per-report values were already rounded to integer cents at submission, and the statement sums those integers, never recomputing from summed gross. `holder_royalty_due_cents` is the studio net royalty multiplied by the holder's `royalty_share_pct` and divided by 100, rounded half up to integer cents — holder-level rounding applied exactly once, at the end."

        Design: Difficulty/dual_variant_calc/statement_attribution_mode_divergence
        """
        workspace = setup_catalog()
        r1, r2 = _two_september_reports(api, workspace)

        statement = create_statement(
            workspace["holder"]["id"],
            "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z",
            attribution_mode="BY_REPORT_DATE",
        )
        assert_royalty_statement(statement)
        assert sorted(statement["included_report_ids"]) == sorted([r1["id"], r2["id"]]), (
            "both reports were submitted inside the closed September interval"
        )
        assert statement["gross_revenue_cents"] == 4000
        assert statement["studio_net_royalty_cents"] == 2000
        assert statement["holder_royalty_due_cents"] == 2000

        finalize_statement(statement["id"], user_id="fin-ana-1")
        paid = get_success_data(api.mark_statement_paid(
            statement["id"], make_finance_controller_headers("fin-ctl-1"),
        ))
        assert paid["statement_status"] == "PAID"

    def test_by_usage_period_excludes_august_only_report(self, api):
        """PRD §3.9: "Under `BY_USAGE_PERIOD`, a report is included when its usage period intersects the statement period — the report's `period_start` at or before the statement's `period_end` and the report's `period_end` at or after the statement's `period_start`."
        PRD §3.9: "the period — treated as a closed interval, both ends inclusive — must not overlap any other `DRAFT` or `FINALIZED` statement of the same holder; `PAID` statements do not block."

        Design: Difficulty/dual_variant_calc/statement_attribution_mode_divergence
        """
        workspace = setup_catalog()
        r1, r2 = _two_september_reports(api, workspace)
        holder_id = workspace["holder"]["id"]

        statement_a = create_statement(
            holder_id, "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z",
            attribution_mode="BY_REPORT_DATE",
        )
        finalize_statement(statement_a["id"], user_id="fin-ana-1")
        get_success_data(api.mark_statement_paid(
            statement_a["id"], make_finance_controller_headers("fin-ctl-1"),
        ))

        statement_b = create_statement(
            holder_id, "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z",
            attribution_mode="BY_USAGE_PERIOD",
        )
        assert_royalty_statement(statement_b)
        assert statement_b["included_report_ids"] == [r2["id"]], (
            "R1's usage period [08-01, 08-31] does not intersect September; "
            "only R2's [08-15, 09-15] does"
        )
        assert statement_b["gross_revenue_cents"] == 3000
        assert statement_b["studio_net_royalty_cents"] == 1500
        assert statement_b["holder_royalty_due_cents"] == 1500

        final_a = get_success_data(api.get_royalty_statement(statement_a["id"], FA))
        assert final_a["statement_status"] == "PAID", (
            "the PAID first statement did not block the overlapping second one"
        )


class TestPerReportRoundingOrder:
    def test_accrual_rounds_half_up_per_report(self, api):
        """PRD §3.8: "The accrued royalty is the gross multiplied by `revenue_share_pct` and divided by 100, rounded half up to integer cents, and stored as `royalty_accrued_cents`."

        Design: Difficulty/combinatorial_formula/statement_per_report_rounding_order
        """
        workspace = setup_catalog()
        license_agreement = _revenue_share_license(workspace)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        r1 = book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", 1)
        r2 = book_report(lid, buyer, "2026-07-15T00:00:00Z", "2026-07-31T00:00:00Z", 1)
        assert r1["royalty_accrued_cents"] == 1, (
            "round half up of half a cent is one cent, applied at submission"
        )
        assert r2["royalty_accrued_cents"] == 1

    def test_statement_sums_per_report_rounded_values(self, api):
        """PRD §3.9: "`studio_net_royalty_cents` is the sum of `payable_cents` over included reports — the per-report values were already rounded to integer cents at submission, and the statement sums those integers, never recomputing from summed gross."
        PRD §3.9: "Under `BY_REPORT_DATE`, a report is included when its `submitted_at` falls inside the closed interval from `period_start` to `period_end`, both ends inclusive."

        Design: Difficulty/combinatorial_formula/statement_per_report_rounding_order
        """
        workspace = setup_catalog()
        license_agreement = _revenue_share_license(workspace)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", 1)
        book_report(lid, buyer, "2026-07-15T00:00:00Z", "2026-07-31T00:00:00Z", 1)

        statement = create_statement(
            workspace["holder"]["id"],
            "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
            attribution_mode="BY_REPORT_DATE",
        )
        assert len(statement["included_report_ids"]) == 2, (
            "both reports submitted at the default clock equal to period_end are "
            "inside the closed interval"
        )
        assert statement["studio_net_royalty_cents"] == 2, (
            "1 + 1 summed per report; recomputing from summed gross would give 1"
        )
        assert statement["holder_royalty_due_cents"] == 2


class TestStatementLifecycle:
    def test_statement_finalize_twice_returns_409(self, api):
        """PRD §3.9: "Finalization is a `FinanceAnalyst` action on a `DRAFT` statement — any other state is rejected with `ERR_STATEMENT_NOT_DRAFT` (409)."

        Design: Corner/state_machines/statement_finalize_twice_returns_409
        """
        holder = create_rights_holder()
        statement = create_statement(
            holder["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
        )
        finalize_statement(statement["id"])

        resp = api.finalize_statement(statement["id"], FA)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_DRAFT, 409)

    def test_statement_mark_paid_from_draft_returns_409(self, api):
        """PRD §3.9: "Marking paid requires the statement to be `FINALIZED`, otherwise `ERR_STATEMENT_NOT_FINALIZED` (409), and enforces segregation of duties: the caller's `X-User-ID` must differ from `finalized_by_user_id` — the same individual who finalized a statement may not mark it paid, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/state_machines/statement_mark_paid_from_draft_returns_409
        """
        holder = create_rights_holder()
        statement = create_statement(
            holder["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
        )

        resp = api.mark_statement_paid(statement["id"], FC)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_FINALIZED, 409)

    def test_statement_finalize_snapshots_totals(self, api):
        """PRD §3.9: "Finalizing recomputes the totals as a fresh snapshot, stamps `finalized_by_user_id` with the caller's `X-User-ID`, and makes the statement immutable: reports booked later do not change a `FINALIZED` or `PAID` statement."

        Design: Corner/state_machines/statement_finalize_snapshots_totals
        """
        workspace = setup_catalog()
        license_agreement = _revenue_share_license(workspace)
        buyer = workspace["buyer_headers"]
        lid = license_agreement["id"]

        book_report(lid, buyer, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", 1000)
        statement = create_statement(
            workspace["holder"]["id"],
            "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
            attribution_mode="BY_REPORT_DATE",
        )
        finalized = finalize_statement(statement["id"], user_id="fin-ana-1")
        assert finalized["finalized_by_user_id"] == "fin-ana-1"
        assert finalized["holder_royalty_due_cents"] == 500

        book_report(lid, buyer, "2026-07-15T00:00:00Z", "2026-07-31T00:00:00Z", 2000)

        current = get_success_data(api.get_royalty_statement(statement["id"], FA))
        assert current["statement_status"] == "FINALIZED"
        assert current["holder_royalty_due_cents"] == 500, (
            "a report booked after finalization must not change the snapshot"
        )

    def test_statement_period_overlap_rejected(self, api):
        """PRD §3.9: "The period end must be strictly after the period start, and the period — treated as a closed interval, both ends inclusive — must not overlap any other `DRAFT` or `FINALIZED` statement of the same holder; `PAID` statements do not block. An overlap is rejected with `ERR_STATEMENT_PERIOD_OVERLAP` (409)."

        Design: Corner/validations/statement_period_overlap_rejected
        """
        holder = create_rights_holder()
        create_statement(
            holder["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
            attribution_mode="BY_REPORT_DATE",
        )

        resp = api.create_royalty_statement(
            {
                "rights_holder_id": holder["id"],
                "period_start": "2026-07-15T00:00:00Z",
                "period_end": "2026-08-15T00:00:00Z",
                "attribution_mode": "BY_USAGE_PERIOD",
            },
            make_finance_analyst_headers("fin-ana-1"),
        )
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP, 409)
