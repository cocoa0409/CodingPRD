"""Grantee reporting and the standing cascade, cycle closeout gates, the
membership retention loop, and the residual-pool rollover waterfall
(PRD §2.4, §3.2, §3.8).
"""
from test_helpers import (
    INTERIM_OVERDUE_CLOCK_ISO,
    TEST_USERS,
    ApiErrorId,
    advance_cycle,
    create_nomination_payload,
    create_rollover_decision_payload,
    get_ledger,
    get_success_data,
    make_grantee_headers,
    make_member_headers,
    nominate_in_cycle,
    reject_report_payload,
    set_clock,
    setup_award,
    setup_reporting,
    setup_second_cycle_nomination,
    submit_report_payload,
    try_advance_cycle,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestReportReviewCycle:
    def test_report_reject_resubmit_cycle(self, api):
        """PRD §3.8: "Rejecting a `SUBMITTED` report moves it to `REJECTED` and
        requires a `reject_reason`, which is recorded for the grantee to answer
        on resubmission."
        PRD §3.8: "Submission is allowed from `DUE`, `OVERDUE`, or `REJECTED` —
        any other state is `ERR_INVALID_STATE` — and carries the `narrative`
        and the reported `expenditure_cents`; each submission moves the report
        to `SUBMITTED` and stamps `submitted_at` from the logical clock, and a
        resubmission after rejection also clears the prior `reject_reason`."

        Design: Corner/state_machines/report_reject_resubmit_cycle
        """
        ctx = setup_award("Circle SM6", num_members=1)
        interim = ctx["reports"][0]
        grantee = make_grantee_headers(ctx["award"]["nonprofit_id"])
        validate_success(
            api.submit_report(interim["id"], submit_report_payload("v1", 10000), grantee)
        )
        rejected = validate_success(
            api.reject_report(
                interim["id"], reject_report_payload("incomplete budget detail"), ADMIN
            )
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["reject_reason"] == "incomplete budget detail"

        resubmitted = validate_success(
            api.submit_report(
                interim["id"], submit_report_payload("v2 with detail", 12000), grantee
            )
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert not resubmitted.get("reject_reason"), (
            "resubmission clears the prior reject_reason"
        )


class TestOverdueCascade:
    def _setup_suspension_scenario(self, api, name):
        """Cycle 1 at AWARD with an unsubmitted INTERIM report; cycle 2 of the
        same circle in NOMINATION with a SUBMITTED nomination of the same
        nonprofit. Clock then moves past the INTERIM deadline."""
        ctx = setup_award(name, num_members=1)
        cycle2 = setup_second_cycle_nomination(ctx)
        second_nomination = nominate_in_cycle(ctx, cycle2["id"], 0, 0, "s2")
        nonprofit_id = ctx["nonprofits"][0]["id"]
        standing_before = get_success_data(api.get_nonprofit(nonprofit_id, ADMIN))
        assert standing_before["standing"] == "GOOD"
        set_clock(INTERIM_OVERDUE_CLOCK_ISO)  # past INTERIM due (2026-09-16)
        return ctx, cycle2, second_nomination, nonprofit_id

    def test_overdue_report_suspends_nonprofit(self, api):
        """PRD §3.8: "The logical clock enforces the deadlines: when a clock
        advance — supplied through `to_iso8601` per §2.4 — moves time past a
        report's `due_at` while the report is still `DUE`, the report flips to
        `OVERDUE` and the cascade fires in two hops. First, the nonprofit
        behind the award has its `standing` set to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/overdue_report_suspends_nonprofit_rejects_nomination
        """
        ctx, _cycle2, _n2, nonprofit_id = self._setup_suspension_scenario(api, "Circle TC1")
        interim = ctx["reports"][0]
        report = get_success_data(api.get_report(interim["id"], ADMIN))
        assert report["status"] == "OVERDUE", "hop 1: the clock flips the report to OVERDUE"
        nonprofit = get_success_data(api.get_nonprofit(nonprofit_id, ADMIN))
        assert nonprofit["standing"] == "SUSPENDED", (
            "hop 2: the overdue report suspends the nonprofit"
        )

    def test_overdue_cascade_rejects_inflight_nomination(self, api):
        """PRD §3.8: "Second, every nomination of that nonprofit still in
        `SUBMITTED`, `VETTING`, or `NEEDS_INFO` whose cycle is in the
        `NOMINATION` or `VETTING` phase is rejected automatically to
        `REJECTED`. A suspension therefore propagates into other circles' live
        pipelines, and it blocks the two standing-gated operations of §3.4 —
        creating a nomination and advancing to finalist — with
        `ERR_NONPROFIT_SUSPENDED` until the nonprofit recovers."

        Design: Difficulty/transitive_cascade/overdue_report_suspends_nonprofit_rejects_nomination
        """
        ctx, _cycle2, second_nomination, _np = self._setup_suspension_scenario(
            api, "Circle TC1B"
        )
        cascaded = get_success_data(api.get_nomination(second_nomination["id"], ADMIN))
        assert cascaded["status"] == "REJECTED", (
            "hop 3: the SUBMITTED nomination in the NOMINATION-phase cycle is rejected"
        )
        winner = get_success_data(api.get_nomination(ctx["nominations"][0]["id"], ADMIN))
        assert winner["status"] == "AWARDED", "terminal states are untouched by the cascade"

    def test_nomination_with_suspended_nonprofit_rejected(self, api):
        """PRD §3.8: "A suspension therefore propagates into other circles'
        live pipelines, and it blocks the two standing-gated operations of
        §3.4 — creating a nomination and advancing to finalist — with
        `ERR_NONPROFIT_SUSPENDED` until the nonprofit recovers."

        Design: Corner/errors/nomination_with_suspended_nonprofit_rejected
        """
        ctx = setup_award("Circle ER13", num_members=1)
        cycle2 = setup_second_cycle_nomination(ctx)
        nonprofit_id = ctx["nonprofits"][0]["id"]
        set_clock(INTERIM_OVERDUE_CLOCK_ISO)
        nonprofit = get_success_data(api.get_nonprofit(nonprofit_id, ADMIN))
        assert nonprofit["standing"] == "SUSPENDED", "precondition: standing flipped"

        resp = api.create_nomination(
            create_nomination_payload(cycle2["id"], nonprofit_id, "again"),
            make_member_headers(ctx["members"][0]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NONPROFIT_SUSPENDED)


class TestCloseout:
    def test_close_with_residual_without_rollover_rejected(self, api):
        """PRD §3.8: "Moving `REPORTING` → `CLOSED` is the strictest gate in
        the system: every payout of the cycle's award must be `RELEASED` and
        every report `ACCEPTED` — either shortfall fails with
        `ERR_INVALID_STATE` — and the pool must be empty, meaning
        `pooled_balance_cents` is exactly zero or an `EXECUTED` rollover
        decision sourced from this cycle exists, failing with
        `ERR_ROLLOVER_REQUIRED` otherwise."

        All payouts released and reports accepted, but a residual 66500 sits in
        the pool with no rollover decision.

        Design: Corner/errors/close_with_residual_without_rollover_rejected
        """
        ctx = setup_reporting(
            "Circle ER14",
            num_members=2,
            funding=((0, 100000, True), (1, 100000, True)),
            num_finalists=2,
            ballot_points=[(0, [60, 40]), (1, [70, 30])],
        )
        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["pooled_balance_cents"] == 66500
        resp = try_advance_cycle(ctx["cycle"]["id"])
        validate_error(resp, ApiErrorId.ERR_ROLLOVER_REQUIRED)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ADMIN))
        assert cycle["phase"] == "REPORTING"

    def test_membership_renewal_after_cycle_close(self, api):
        """PRD §3.2: "When a cycle closes (§3.8), every membership of the
        circle still in `ACTIVE` flips automatically to `RENEWAL_DUE`, opening
        the retention window. The member renews their own membership — again
        an ownership check against `member_id`, and only from `RENEWAL_DUE`
        (otherwise `ERR_INVALID_STATE`) — which returns it to `ACTIVE`, adds
        one to its `renewal_count`, and recomputes both `active_member_count`
        and the circle's `renewed_member_count`, the running sum of
        `renewal_count` across the circle's memberships."

        Award 95000 fully disbursed (T1 66500 + T2 28500) against 100000
        received less fee 5000 leaves pooled 0, so the close gate passes.

        Design: Corner/state_machines/membership_renewal_after_cycle_close
        """
        ctx = setup_reporting("Circle SM8", num_members=1)
        closed = advance_cycle(ctx["cycle"]["id"])  # REPORTING -> CLOSED
        assert closed["phase"] == "CLOSED"

        membership = ctx["memberships"][0]
        member = ctx["members"][0]
        due = get_success_data(api.get_membership(membership["id"], ADMIN))
        assert due["status"] == "RENEWAL_DUE", "close flips ACTIVE memberships to RENEWAL_DUE"

        renewed = validate_success(
            api.renew_membership(membership["id"], make_member_headers(member["id"]))
        )
        assert renewed["status"] == "ACTIVE"
        assert renewed["renewal_count"] == 1

        circle = get_success_data(api.get_circle(ctx["circle"]["id"], ADMIN))
        assert circle["renewed_member_count"] == 1


class TestRolloverWaterfall:
    def test_rollover_pro_rata_waterfall_distribution(self, api):
        """PRD §3.8: "Execution captures the source cycle's
        `pooled_balance_cents` at that instant as the decision's `amount_cents`
        and runs the waterfall for the chosen mode."
        PRD §3.8: "Under `RETURN_PRO_RATA`, the residual is distributed to the
        memberships of the source circle in `ACTIVE` or `RENEWAL_DUE`, taken in
        `created_at` ascending order — ties break on creation time only, never
        on `id` — where each membership's weight is its own total of `RECEIVED`
        contributions in the source cycle; each membership's credit is the
        residual multiplied by its weight and divided by the combined weights,
        rounded down to whole cents, and the cents left over after every
        membership is floored go to the host organization rather than to any
        member."

        Residual 66500 split 100000/200000 to each member: exactly 33250 each,
        no leftover.

        Design: Corner/calculations/rollover_pro_rata_waterfall_distribution
        """
        ctx = setup_reporting(
            "Circle CA3",
            num_members=2,
            funding=((0, 100000, True), (1, 100000, True)),
            num_finalists=2,
            ballot_points=[(0, [60, 40]), (1, [70, 30])],
        )
        decision = validate_success(
            api.create_rollover_decision(
                create_rollover_decision_payload(ctx["cycle"]["id"], "RETURN_PRO_RATA"),
                ADMIN,
            ),
            expected_status=201,
        )
        assert decision["status"] == "PROPOSED"
        validate_success(api.approve_rollover(decision["id"], ADMIN))
        executed = validate_success(api.execute_rollover(decision["id"], ADMIN))
        assert executed["status"] == "EXECUTED"
        assert executed["amount_cents"] == 66500, (
            f"the residual pool is captured as amount_cents, got {executed['amount_cents']}"
        )

        ms1 = get_success_data(api.get_membership(ctx["memberships"][0]["id"], ADMIN))
        ms2 = get_success_data(api.get_membership(ctx["memberships"][1]["id"], ADMIN))
        assert ms1["credit_balance_cents"] == 33250
        assert ms2["credit_balance_cents"] == 33250

        ledger = get_ledger(ctx["cycle"]["id"])
        assert ledger["pooled_balance_cents"] == 0, "the waterfall drains the source pool"
        assert ledger["rollover_out_cents"] == 66500
