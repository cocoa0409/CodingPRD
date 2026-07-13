"""Contact-tier billing: the peak-vs-current contact count, block rounding and the epoch."""
from test_helpers import (
    PLATFORM,
    add_subscriber,
    advance_epoch_to,
    assert_billing_cycle,
    billing_cycles_of,
    create_audience,
    ops_run,
    provision_tenant,
    read_audience,
    run_import,
    set_clock,
    validate_success,
)

PERIOD_END = "2026-05-31T00:00:00Z"


class TestPeakVersusCurrentContactCount:
    def test_rollback_collapses_the_current_billable_contact_count(self, api):
        """PRD §3.11: "The account's `billable_contact_count` itself is the sum, across all of the
        account's audiences, of each audience's `subscriber_count` — that is, of the contacts whose
        `consent_state` is `PENDING`, `CONFIRMED` or `UNSUBSCRIBED`."
        PRD §3.3: "Because those contacts have left the counted set, the audience's
        `subscriber_count` is recomputed from its formula, and because that changed, the account's
        `billable_contact_count` is recomputed from its formula in turn — restoring the pre-import
        contact count."

        Design: Difficulty/dual_variant_calc/billable_contacts_current_vs_peak_cycle
        """
        tenant = provision_tenant(plan_tier="ESSENTIALS")
        audience = create_audience(tenant, double_optin_required=False)
        job = run_import(
            audience["id"], ["a1@x.com", "a2@x.com", "a3@x.com"], tenant.author_headers
        )
        advance_epoch_to("2026-05-10T00:00:00Z")

        rolled = validate_success(api.rollback_import_job(job["id"], tenant.author_headers))

        assert rolled["status"] == "ROLLED_BACK"
        assert rolled["accepted_count"] == 3
        assert read_audience(audience["id"])["subscriber_count"] == 0
        assert tenant.refresh()["billable_contact_count"] == 0

    def test_the_cycle_peak_is_monotone_and_survives_the_rollback(self, api):
        """PRD §3.11: "The fourth phase of every operations epoch samples the account's current
        `billable_contact_count` into its `OPEN` billing cycle, keeping the larger of the sample and
        the cycle's existing `peak_contact_count`. That count is monotone within a cycle: a list that
        swelled to 13 contacts and then collapsed to 0 is still invoiced on 13."
        PRD §3.11: "Billing is driven by the *peak* number of contacts an account carried inside a
        period, not by the number that happen to survive to its end."

        Design: Difficulty/dual_variant_calc/billable_contacts_current_vs_peak_cycle
        """
        tenant = provision_tenant(plan_tier="ESSENTIALS")
        audience = create_audience(tenant, double_optin_required=False)
        job = run_import(
            audience["id"], ["a1@x.com", "a2@x.com", "a3@x.com"], tenant.author_headers
        )
        advance_epoch_to("2026-05-10T00:00:00Z")  # phase 4 samples the peak at 3

        validate_success(api.rollback_import_job(job["id"], tenant.author_headers))

        cycles = billing_cycles_of(tenant.id)
        assert_billing_cycle(cycles[0])
        assert cycles[0]["status"] == "OPEN"
        assert cycles[0]["peak_contact_count"] == 3, "the peak never falls inside a cycle"
        assert tenant.refresh()["billable_contact_count"] == 0, "while the current count did"


class TestTieredContactBilling:
    def test_overage_rounds_each_block_before_summing(self, api):
        """PRD §3.11: "Subtract the tier's included contacts from the cycle's `peak_contact_count`
        and floor the result at zero to get the overage contacts. Those contacts are then charged in
        **blocks of 5**, counting from the first block: divide the overage contacts by 5 and round
        *up* to a whole number to learn how many blocks there are, where the last block may be partly
        filled and is charged only for the contacts it actually holds. The first and second blocks are
        charged at 27.0 cents per contact; the third, fourth and fifth blocks at 19.0 cents per
        contact; every block from the sixth onward at 13.0 cents per contact."
        PRD §3.11: "**The rounding order is pinned: each block's amount — its contact count, times
        its rate, times one minus the tier's discount — is rounded half up to whole cents on its own,
        and only then are the block amounts summed into `overage_cents`.** Summing the raw block
        amounts and rounding once at the end is the wrong reading and produces a different invoice."

        Design: Difficulty/combinatorial_formula/tiered_contact_billing_round_per_block_then_sum
        """
        tenant = provision_tenant(plan_tier="ESSENTIALS", initial_send_credits=0)
        audience = create_audience(tenant, double_optin_required=False)
        job = run_import(
            audience["id"],
            [f"c{i:02d}@x.com" for i in range(1, 14)],
            tenant.author_headers,
        )
        assert job["status"] == "COMPLETED"
        assert job["accepted_count"] == 13

        set_clock(PERIOD_END)
        summary = ops_run()
        assert summary["billing_cycles_closed"] == 1

        closed = billing_cycles_of(tenant.id)[0]
        assert closed["status"] == "CLOSED"
        assert closed["peak_contact_count"] == 13
        assert closed["tier_applied"] == "ESSENTIALS"
        assert closed["base_fee_cents"] == 1300
        # blocks of 5 and 3 contacts at 27.0 cents with a 10% discount:
        # round_half_up(5 * 27.0 * 0.9) = round_half_up(121.5) = 122
        # round_half_up(3 * 27.0 * 0.9) = round_half_up(72.9)  = 73  ->  195
        # (summing raw first would give round_half_up(194.4) = 194 — the wrong reading)
        assert closed["overage_cents"] == 195
        assert closed["total_cents"] == 1495

    def test_closing_a_cycle_freezes_the_tier_and_rolls_a_fresh_open_cycle(self, api):
        """PRD §3.11: "The fifth phase closes. Every `OPEN` cycle whose `period_end` is at or before
        the clock moves `OPEN → CLOSED`: `tier_applied` freezes the account's `plan_tier` as it
        stands at that instant, `closed_at` is stamped with the clock, and the invoice is computed. A
        fresh cycle is then opened whose `period_start` is the closed cycle's `period_end`, whose
        `period_end` is 30 days after that, and whose `peak_contact_count` starts at the account's
        billable contact count at close time."
        PRD §3.11: "`total_cents` is `base_fee_cents` plus `overage_cents`. The only input to the
        overage is the cycle's `peak_contact_count`; the account's `billable_contact_count` at close
        time is never used for it."

        Design: Difficulty/combinatorial_formula/tiered_contact_billing_round_per_block_then_sum
        """
        tenant = provision_tenant(plan_tier="ESSENTIALS", initial_send_credits=0)
        audience = create_audience(tenant, double_optin_required=False)
        run_import(
            audience["id"],
            [f"c{i:02d}@x.com" for i in range(1, 14)],
            tenant.author_headers,
        )

        set_clock(PERIOD_END)
        summary = ops_run()
        assert summary["billing_cycles_closed"] == 1

        cycles = billing_cycles_of(tenant.id)
        assert len(cycles) == 2
        assert cycles[0]["status"] == "CLOSED"
        assert cycles[0]["tier_applied"] == "ESSENTIALS"
        assert cycles[0]["closed_at"] == "2026-05-31T00:00:00.000Z"
        assert cycles[1]["status"] == "OPEN", "a fresh cycle is rolled forward"
        assert cycles[1]["period_start"] == cycles[0]["period_end"]

    def test_a_peak_at_the_included_boundary_yields_no_overage(self, api):
        """PRD §3.11: "Each tier includes a number of contacts — 2 on `FREE`, 5 on `ESSENTIALS`, 10
        on `STANDARD` and 25 on `PREMIUM` — and grants a discount on every overage charge: none on
        `FREE`, 10 percent on `ESSENTIALS`, 20 percent on `STANDARD` and 30 percent on `PREMIUM`."
        PRD §3.11: "`base_fee_cents` is the flat fee of the frozen tier: 0 cents on `FREE`, 1300
        cents on `ESSENTIALS`, 2000 cents on `STANDARD`, and 29900 cents on `PREMIUM`."
        PRD §3.11: "Subtract the tier's included contacts from the cycle's `peak_contact_count` and
        floor the result at zero to get the overage contacts."

        Design: Corner/calculations/billing_free_tier_at_included_boundary_yields_zero_overage
        """
        tenant = provision_tenant(
            plan_tier="FREE", initial_send_credits=0, with_author=False, with_approver=False
        )
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        add_subscriber(audience["id"], "s1@x.com", PLATFORM)
        add_subscriber(audience["id"], "s2@x.com", PLATFORM)

        set_clock(PERIOD_END)
        summary = ops_run()
        assert summary["billing_cycles_closed"] == 1

        closed = billing_cycles_of(tenant.id)[0]
        assert closed["peak_contact_count"] == 2
        assert closed["tier_applied"] == "FREE"
        assert closed["base_fee_cents"] == 0
        assert closed["overage_cents"] == 0, "a peak exactly at the included count owes nothing"
        assert closed["total_cents"] == 0
        assert closed["status"] == "CLOSED"


class TestOperationsEpochSummary:
    def test_an_empty_epoch_reports_five_zero_counters_but_still_snapshots(self, api):
        """PRD §2.11: "The epoch reports what it did: `subscribers_archived`, `campaigns_dispatched`,
        `sends_created`, `enrollments_advanced` and `billing_cycles_closed`."
        PRD §3.11: "The fourth phase of every operations epoch samples the account's current
        `billable_contact_count` into its `OPEN` billing cycle, keeping the larger of the sample and
        the cycle's existing `peak_contact_count`."

        Design: Corner/endpoints/ops_run_returns_zeroed_counter_summary_on_empty_epoch
        """
        tenant = provision_tenant(
            initial_send_credits=0, with_author=False, with_approver=False
        )
        audience = create_audience(tenant, double_optin_required=False, headers=PLATFORM)
        add_subscriber(audience["id"], "s1@x.com", PLATFORM)
        set_clock("2026-05-02T00:00:00Z")  # well before period_end

        summary = ops_run()

        assert summary["subscribers_archived"] == 0
        assert summary["campaigns_dispatched"] == 0
        assert summary["sends_created"] == 0
        assert summary["enrollments_advanced"] == 0
        assert summary["billing_cycles_closed"] == 0

        cycles = billing_cycles_of(tenant.id)
        assert cycles[0]["status"] == "OPEN"
        assert cycles[0]["peak_contact_count"] == 1, "the phase-4 snapshot still ran"
