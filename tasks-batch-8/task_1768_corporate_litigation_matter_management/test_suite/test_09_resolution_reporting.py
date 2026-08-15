"""Resolution, reopening, closure, clock sweeps, and the oversight read models."""
from test_helpers import (
    TEST_USERS,
    add_hold,
    add_vendor,
    create_and_authorize_work_order,
    create_matter,
    create_posted_accrual,
    create_staff_user,
    get_success_data,
    make_counsel_headers,
    make_dgc_headers,
    make_gc_headers,
    setup_active_matter,
    setup_disbursed_payment,
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId, CustodianStatus, DeadlineStatus, HoldStatus, MatterStatus,
    Posture, WorkOrderStatus,
)

OPS = TEST_USERS["ops_headers"]


class TestMatterClosure:
    def test_matter_terminal_close_lockdown(self, api):
        """PRD §3.9: "An early-exit branch covers mistaken intake: a matter still in
        `INTAKE` may be closed directly when no engagement, hold, work order,
        settlement request, or payment request exists for it, again with
        `close_checklist_ack` true. `CLOSED` is terminal in both directions."
        PRD §2.11 lists "(5) whether the invoked transition exists from the target
        resource's current state (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/matter_terminal_close_lockdown
        """
        counsel = create_staff_user("Casey Counsel", "casey@corp.example", "LEGAL")
        matter = create_matter(counsel["id"], with_exposure=False,
                               title="Mistaken intake")
        closed = validate_success(
            api.close_matter(matter["id"], True, OPS))
        assert closed["status"] == MatterStatus.CLOSED.value

        resp = api.resolve_matter(matter["id"], "DISMISSAL",
                                  make_counsel_headers(counsel["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(
            api.get_matter(matter["id"], make_counsel_headers(counsel["id"])))
        assert current["status"] == MatterStatus.CLOSED.value


class TestDirectResolution:
    def test_error_open_limitation_exposure_blocks_resolve(self, api):
        """PRD §3.9: "Direct resolution is refused with `ERR_OPEN_LIMITATION_EXPOSURE`
        while any `LIMITATION_EXPIRY` deadline of the matter is still `SCHEDULED`:
        open limitation exposure must be vacated first."

        Design: Corner/errors/error_open_limitation_exposure_blocks_resolve
        """
        ctx = setup_active_matter(deadline_type="LIMITATION_EXPIRY",
                                  deadline_due_at="2027-01-01T00:00:00Z")
        resp = api.resolve_matter(ctx["matter_id"], "DISMISSAL", ctx["counsel"])
        validate_error(resp, ApiErrorId.ERR_OPEN_LIMITATION_EXPOSURE)

        get_success_data(api.vacate_deadline(ctx["deadline"]["id"], ctx["counsel"]))
        resolved = validate_success(
            api.resolve_matter(ctx["matter_id"], "DISMISSAL", ctx["counsel"]))
        assert resolved["status"] == MatterStatus.RESOLVED.value
        assert resolved["resolution_type"] == "DISMISSAL"

    def test_immediate_consistency_cascade_visible_in_same_read(self, api):
        """PRD §3.9: "Whichever door is taken, resolution stamps `resolved_at` and runs
        the same cascade in a pinned order. First, every work order of the matter in
        `DRAFT`, `AUTHORIZED`, or `IN_PROGRESS` moves to `CANCELLED`, each releasing
        its vendor-capacity debit and — by cancelling the orders that pinned them —
        unpinning the holds. Second, every litigation hold in `DRAFT`, `ISSUED`, or
        `ACKNOWLEDGED` moves to `RELEASED` with `release_reason` `MATTER_RESOLVED`;
        because the work orders cancelled first, the release-time pin check is vacuous
        during this system-driven flow. Third, every custodian under those holds in
        `NOTICED`, `ACKNOWLEDGED`, or `ESCALATED` moves to `RELEASED`. Fourth — on the
        direct-resolve path — every still-`SCHEDULED` deadline moves to `VACATED`."

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_read
        """
        ctx = setup_active_matter()
        hold, custodian = add_hold(ctx, issue=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        wo = create_and_authorize_work_order(ctx, vendor["id"], hold["id"],
                                             estimated_gb=100)

        get_success_data(api.resolve_matter(ctx["matter_id"], "DISMISSAL",
                                            ctx["counsel"]))
        hold_after = get_success_data(api.get_hold(hold["id"], ctx["counsel"]))
        assert hold_after["status"] == HoldStatus.RELEASED.value
        assert hold_after["release_reason"] == "MATTER_RESOLVED"
        custodian_after = get_success_data(
            api.get_custodian(custodian["id"], ctx["counsel"]))
        assert custodian_after["status"] == CustodianStatus.RELEASED.value
        wo_after = get_success_data(api.get_work_order(wo["id"], OPS))
        assert wo_after["status"] == WorkOrderStatus.CANCELLED.value
        deadline_after = get_success_data(
            api.get_deadline(ctx["deadline"]["id"], ctx["counsel"]))
        assert deadline_after["status"] == DeadlineStatus.VACATED.value


class TestReopen:
    def test_error_reopen_blocked_by_confirmed_payment(self, api):
        """PRD §3.9: "A `DeputyGeneralCounsel` may reopen a `RESOLVED` matter by
        supplying a non-empty `reopen_reason` (missing or empty, the call is
        `ERR_INVALID_REQUEST`) — but only while no payment request of the matter
        stands `DISBURSED` with its rail `CONFIRMED`; money confirmed in the
        recipient's hands makes reopening impossible and yields
        `ERR_REOPEN_BLOCKED_BY_CONFIRMED_PAYMENT`."

        Design: Corner/errors/error_reopen_blocked_by_confirmed_payment
        """
        ctx, payment = setup_disbursed_payment()
        get_success_data(api.confirm_receipt_payment(payment["id"], ctx["fin"]))

        resp = api.reopen_matter(ctx["matter_id"], "Appeal", ctx["dgc"])
        validate_error(resp, ApiErrorId.ERR_REOPEN_BLOCKED_BY_CONFIRMED_PAYMENT)
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["status"] == MatterStatus.RESOLVED.value


class TestClockSweepFreezes:
    def test_clock_sweep_misses_deadline_and_freezes_matter(self, api):
        """PRD §2.6: "First, every Deadline still `SCHEDULED` whose `due_at` is earlier
        than the new clock time transitions to `MISSED`."
        PRD §2.6: "Each transition a sweep fires reapplies that transition's full side
        effects — most significantly, a jurisdictional deadline swept into `MISSED`
        freezes its matter's posture exactly as a manual miss would."
        PRD §2.9: "If any deadline of the matter has `is_jurisdictional` true and
        status `MISSED`, the posture is `FROZEN` — the jurisdictional freeze beats
        everything else."
        PRD §3.7: "Vacating the deadline whose miss froze the matter re-runs the
        posture ladder and may unfreeze it."

        Design: Corner/cross_cutting_layers/clock_sweep_misses_deadline_and_freezes_matter
        """
        ctx = setup_active_matter(deadline_type="COURT_DEADLINE",
                                  deadline_due_at="2026-08-05T00:00:00Z",
                                  deadline_is_jurisdictional=True)

        get_success_data(api.set_clock("2026-08-06T00:00:00Z", OPS))
        deadline = get_success_data(
            api.get_deadline(ctx["deadline"]["id"], ctx["counsel"]))
        assert deadline["status"] == DeadlineStatus.MISSED.value
        frozen = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert frozen["posture"] == Posture.FROZEN.value, \
            "a jurisdictional miss must freeze the matter's posture"

        get_success_data(api.vacate_deadline(
            ctx["deadline"]["id"], make_dgc_headers(ctx["dgc_id"]),
            court_order_reference="ORDER-2026-118"))
        unfrozen = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert unfrozen["posture"] == Posture.OPEN.value, \
            "vacating the causal miss must unfreeze the matter"


class TestOversightReadModels:
    def test_matter_summary_computed_read(self, api):
        """PRD §3.9: "The matter summary returns the matter's `reserve_amount_cents`
        and `accrued_to_date_cents` as they stand on the matter row; `utilization_pct`
        mirroring the `APPROVED` budget (zero when none exists); `open_deadline_count`,
        the count of its deadlines still `SCHEDULED`; `active_hold_count`, the count
        of its holds in `DRAFT`, `ISSUED`, or `ACKNOWLEDGED`; and
        `committed_vendor_estimate_cents`, the sum of `estimated_cost_cents` over its
        work orders in `AUTHORIZED` or `IN_PROGRESS`."

        Design: Corner/endpoints/matter_summary_computed_read
        """
        ctx = setup_active_matter(fy_budget_cents=1_000_000)
        create_posted_accrual(ctx, period="2026-08", amount_cents=100_000)
        hold, _custodian = add_hold(ctx, issue=True)
        vendor = add_vendor(ctx, capacity_gb=1000)
        create_and_authorize_work_order(ctx, vendor["id"], hold["id"],
                                        estimated_gb=100, rate_per_gb_cents=1000)

        summary = validate_success(
            api.get_matter_summary(ctx["matter_id"], ctx["counsel"]))
        assert summary["accrued_to_date_cents"] == 100_000
        assert summary["utilization_pct"] == 10  # floor(100,000*100/1,000,000)
        assert summary["open_deadline_count"] == 1
        assert summary["active_hold_count"] == 1
        # 100 GB @ 1000 cents: all in tier A -> 100,000
        assert summary["committed_vendor_estimate_cents"] == 100_000
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert summary["reserve_amount_cents"] == matter["reserve_amount_cents"], \
            "summary reserve must mirror the matter row"

    def test_portfolio_analytics_empty_cohort_returns_zeros(self, api):
        """PRD §3.9: "`outcome_favorability_pct`, the floored percentage of resolved
        matters whose `resolution_type` is `DISMISSAL` or `SUMMARY_JUDGMENT`, which
        reads zero for a cohort with no resolutions."
        PRD §3.9: "Alongside the `cohorts` array the report carries
        `open_exposure_cents` — the sum of `exposure_high_cents` over every matter in
        `STAFFING`, `ACTIVE`, `REOPENED`, or `SETTLEMENT_PENDING` — and
        `total_matters`. Empty cohorts report zeros, never nulls."

        Design: Corner/calculations/portfolio_analytics_empty_cohort_returns_zeros
        """
        gc = create_staff_user("Gena Counsel", "gena@corp.example", "EXECUTIVE")
        counsel = create_staff_user("Casey Counsel", "casey@corp.example", "LEGAL")
        create_matter(counsel["id"], with_exposure=False)

        report = validate_success(
            api.get_portfolio_report(make_gc_headers(gc["id"])))
        assert report["total_matters"] == 1
        assert isinstance(report["cohorts"], list)
        for cohort in report["cohorts"]:
            assert cohort["resolved_count"] == 0
            assert cohort["outcome_favorability_pct"] == 0
            assert cohort["resolved_count"] is not None
            assert cohort["outcome_favorability_pct"] is not None
