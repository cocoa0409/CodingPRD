"""The allocation waterfall: source compatibility filter, ranking order,
per-household room caps, and the payment gate on RESERVED allocations."""
from test_helpers import (
    ApiErrorId,
    approve_application,
    attach_document,
    create_active_policy,
    create_application,
    create_funding_source,
    create_household,
    create_vendor,
    drive_application_to_pending_decision,
    get_application,
    issue_payment,
    list_award_allocations,
    open_cleared_duplication_check,
    get_application_version,
    pass_verification,
    set_clock,
    setup_approved,
    submit_application,
    TEST_USERS,
    validate_error,
    validate_success,
)

CW1 = TEST_USERS["caseworker_headers"]
PM1 = TEST_USERS["program_manager_headers"]
FIN1 = TEST_USERS["finance_officer_headers"]


class TestWaterfallRankingAndFiltering:
    def test_waterfall_tie_break_period_end_then_created_at(self, api):
        """PRD §3.5: "Compatible sources are ranked with the most restricted
        source first — a shorter `allowed_categories` list ranks ahead of a longer
        one — then by earliest `period_end`, then by earliest `created_at`; each
        allocation records its position in this ranking as `rank_order`, starting
        at 0 for the first-drawn source."

        Design: Corner/calculations/waterfall_tie_break_period_end_then_created_at
        """
        # The logical clock stamps created_at, so Y and Z are created under
        # distinct clock readings — the created_at tie-break between them is
        # real and deterministic.
        set_clock("2026-03-01T00:00:00Z")
        create_active_policy()
        vendor = create_vendor("LANDLORD")
        household = create_household()
        sx = create_funding_source(
            name="X", funder_name="Funder X",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-12-31T00:00:00Z", total_budget_cents=10000,
        )["id"]
        sy = create_funding_source(
            name="Y", funder_name="Funder Y",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-06-30T00:00:00Z", total_budget_cents=10000,
        )["id"]
        set_clock("2026-03-02T00:00:00Z")  # Z is created strictly after Y
        sz = create_funding_source(
            name="Z", funder_name="Funder Z",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-06-30T00:00:00Z", total_budget_cents=10000,
        )["id"]
        pending = drive_application_to_pending_decision(
            household["id"], vendor["id"],
            requested_amount_cents=25000, service_month="2026-03",
        )
        approved = approve_application(pending["application"]["id"])
        allocations = list_award_allocations(approved["active_award_id"])
        assert len(allocations) == 3
        # Earliest period_end first; the tie between Y and Z breaks by created_at.
        assert allocations[0]["funding_source_id"] == sy
        assert allocations[0]["allocated_cents"] == 10000
        assert allocations[0]["rank_order"] == 0
        assert allocations[1]["funding_source_id"] == sz
        assert allocations[1]["allocated_cents"] == 10000
        assert allocations[1]["rank_order"] == 1
        assert allocations[2]["funding_source_id"] == sx
        assert allocations[2]["allocated_cents"] == 5000
        assert allocations[2]["rank_order"] == 2
        for drained in (sy, sz):
            source = validate_success(api.get_funding_source(drained, PM1), 200)
            assert source["status"] == "EXHAUSTED"

    def test_source_per_household_cap_binds_waterfall_take(self, api):
        """PRD §3.5: "The sweep then walks the ranked sources, taking from each
        the smallest of the remaining need, the source's `available_cents`, and
        its per-household room; each take creates a FundingAllocation in
        `RESERVED` status with `consumed_cents` at zero, adds the take to the
        source's `reserved_cents`, and flips the source `ACTIVE → EXHAUSTED` if
        its availability thereby reaches zero."
        PRD §3.5: "when the source still has per-household room: its
        `max_per_household_cents` minus the sum of `allocated_cents` across that
        source's allocations attached to this household's non-`VOIDED` awards of
        the current benefit year."

        Design: Corner/calculations/source_per_household_cap_binds_waterfall_take
        """
        ctx = setup_approved(
            requested_amount_cents=50000,
            policy_overrides={"rent_cap_cents": 60000},
            sources=[
                # M is strictly more restricted (RENT-only), so it ranks ahead
                # of N deterministically even with the frozen logical clock.
                dict(name="M", funder_name="Funder M", source_type="GRANT_RESTRICTED",
                     allowed_categories=["RENT"], total_budget_cents=100000,
                     max_per_household_cents=10000),
                dict(name="N", funder_name="Funder N", total_budget_cents=100000,
                     max_per_household_cents=1000000),
            ],
        )
        sm, sn = (s["id"] for s in ctx["sources"])
        allocations = ctx["allocations"]
        assert len(allocations) == 2
        assert allocations[0]["funding_source_id"] == sm
        assert allocations[0]["allocated_cents"] == 10000, (
            "the per-household cap binds the take even though available could cover all"
        )
        assert allocations[1]["funding_source_id"] == sn
        assert allocations[1]["allocated_cents"] == 40000
        assert ctx["award"]["awarded_amount_cents"] == 50000

    def test_incompatible_sources_excluded_from_waterfall(self, api):
        """PRD §3.5: "A funding source is compatible with the application when
        the source is `ACTIVE`, when the application's `category` appears in the
        source's `allowed_categories`, when the logical clock sits at or after
        `period_start` and strictly before `period_end`, when the source's
        `available_cents` is above zero, and when the source still has
        per-household room: its `max_per_household_cents` minus the sum of
        `allocated_cents` across that source's allocations attached to this
        household's non-`VOIDED` awards of the current benefit year."

        Design: Corner/calculations/incompatible_sources_excluded_from_waterfall
        """
        create_active_policy()
        vendor = create_vendor("LANDLORD")
        household = create_household()
        old = create_funding_source(  # ended before the clock reads 2026-08-01
            name="OLD", funder_name="Funder O", source_type="GRANT_RESTRICTED",
            allowed_categories=["RENT"],
            period_start="2026-01-01T00:00:00Z", period_end="2026-06-01T00:00:00Z",
            total_budget_cents=90000,
        )
        util = create_funding_source(  # wrong category for a RENT application
            name="UTIL", funder_name="Funder U", source_type="GRANT_RESTRICTED",
            allowed_categories=["UTILITY"], total_budget_cents=90000,
        )
        shut = create_funding_source(  # closed before the application
            name="SHUT", funder_name="Funder S", total_budget_cents=90000,
        )
        validate_success(api.close_funding_source(shut["id"], PM1), 200)
        ok = create_funding_source(
            name="OK", funder_name="Funder OK", allowed_categories=["RENT"],
            total_budget_cents=30000,
        )
        pending = drive_application_to_pending_decision(
            household["id"], vendor["id"], requested_amount_cents=30000
        )
        approved = approve_application(pending["application"]["id"])
        allocations = list_award_allocations(approved["active_award_id"])
        assert len(allocations) == 1, "incompatible sources are invisible to the waterfall"
        assert allocations[0]["funding_source_id"] == ok["id"]
        assert allocations[0]["allocated_cents"] == 30000
        ok_after = validate_success(api.get_funding_source(ok["id"], PM1), 200)
        assert ok_after["status"] == "EXHAUSTED"
        for untouched in (old["id"], util["id"], shut["id"]):
            source = validate_success(api.get_funding_source(untouched, PM1), 200)
            assert source["reserved_cents"] == 0


class TestPaymentReservedAllocationGate:
    def _three_source_award(self):
        ctx = setup_approved(
            requested_amount_cents=40000,
            policy_overrides={"rent_cap_cents": 60000},
            sources=[
                dict(name="J", funder_name="Funder J", source_type="GRANT_RESTRICTED",
                     allowed_categories=["RENT"], total_budget_cents=25000),
                # K's earlier period_end breaks the K/L ranking tie (frozen
                # clock makes created_at identical), so K is drawn second and
                # L is never reached.
                dict(name="K", funder_name="Funder K", total_budget_cents=40000,
                     period_end="2026-10-01T00:00:00Z"),
                dict(name="L", funder_name="Funder L", total_budget_cents=90000,
                     period_end="2026-12-01T00:00:00Z"),
            ],
        )
        return ctx

    def test_payment_on_source_without_reserved_allocation_rejected(self, api):
        """PRD §3.7: "The named source must hold a `RESERVED` allocation on this
        award, else `ERR_NO_RESERVED_ALLOCATION`."

        Design: Difficulty/cross_entity_state_dependency/payment_gated_by_reserved_allocation_on_that_source
        """
        ctx = self._three_source_award()
        sl = ctx["sources"][2]["id"]  # ACTIVE and category-compatible, but untouched
        resp = api.create_payment(
            ctx["award"]["id"],
            {
                "vendor_id": ctx["vendor"]["id"],
                "funding_source_id": sl,
                "amount_cents": 5000,
                "payment_date": "2026-08-02T00:00:00Z",
            },
            FIN1,
        )
        validate_error(resp, ApiErrorId.ERR_NO_RESERVED_ALLOCATION)

    def test_allocation_layout_and_payment_on_reserved_source_succeeds(self, api):
        """PRD §3.5: "Compatible sources are ranked with the most restricted
        source first — a shorter `allowed_categories` list ranks ahead of a longer
        one — then by earliest `period_end`, then by earliest `created_at`; each
        allocation records its position in this ranking as `rank_order`, starting
        at 0 for the first-drawn source."
        PRD §3.7: "A valid payment is born `ISSUED` with the acting officer
        recorded as `issued_by`."

        Design: Difficulty/cross_entity_state_dependency/payment_gated_by_reserved_allocation_on_that_source
        """
        ctx = self._three_source_award()
        sj, sk, sl = (s["id"] for s in ctx["sources"])
        allocations = ctx["allocations"]
        assert [(a["funding_source_id"], a["allocated_cents"], a["rank_order"])
                for a in allocations] == [(sj, 25000, 0), (sk, 15000, 1)], (
            "the most restricted source is drawn first; L is never reached"
        )
        payment = issue_payment(
            ctx["award"]["id"], ctx["vendor"]["id"], sj, 5000
        )
        assert payment["status"] == "ISSUED"
        assert payment["issued_by"] == "fin-1"
