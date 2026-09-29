"""The two deep cascades: usage-report acceptance and agreement termination.

Both are chains where each link exists only because the previous one fired. The
tests below drive each trigger once from a freshly built world and then read the
rows each step is supposed to have touched, step by step.
"""

from test_helpers import (
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    Deal,
    Work,
    accept_usage_report,
    assert_allocation,
    assert_cents_equal,
    assert_composer_money,
    assert_composition_axes,
    assert_created,
    assert_credit_exposure,
    assert_credits_equal,
    assert_ok,
    assert_pool_conserves_cents,
    assert_same_instant,
    assert_single_ledger_entry,
    assert_status,
    ledger_entries,
    new_active_agreement,
    new_active_blanket,
    new_composer,
    new_licensee,
    new_registered_cue_sheet,
    new_tier,
    open_usage_report,
    quote_sync_request,
    read_blanket_agreement,
    read_composer,
    read_composition,
    read_licensee,
    read_usage_report,
    review_sync_request,
    submit_sync_request,
    submit_usage_report,
)
from test_helpers import factories as build


def _cataloged_work_under(api, composer, agreement, **composition_overrides) -> Work:
    """One more work governed by an agreement that is already ACTIVE."""
    composition = assert_created(
        api.create_composition(
            build.composition_payload(composer["id"], agreement["id"], **composition_overrides),
            CATALOG_ADMIN,
        )
    )
    composition = assert_ok(api.catalog_composition(composition["id"], None, CATALOG_ADMIN))
    return Work(composer, agreement, composition)


# ---------------------------------------------------------------------------
# Ground for the usage-report acceptance chain
# ---------------------------------------------------------------------------


def _submitted_blanket_period(api):
    """Two composers on different writer shares, one submitted blanket period.

    The period carries a single REGISTERED cue sheet on a NETWORK transmission
    crediting three cues of work A and one cue of work B, so the sheet holds
    165 seconds and 3.66 credits split 3.01 / 0.65 between the two works. The
    blanket agreement sells 3 included minutes a term for an annual fee of
    4800000 cents at a 25.00 percent pool share on a MONTHLY cadence.
    """
    composer_one = new_composer(api, display_name="Anders Vik", pro_affiliation="ASCAP")
    agreement_one = new_active_agreement(
        api,
        composer_one["id"],
        writer_share_pct=50.00,
        publisher_share_pct=50.00,
        blanket_opt_in=True,
    )
    composer_two = new_composer(api, display_name="Mei Tanaka", pro_affiliation="BMI")
    agreement_two = new_active_agreement(
        api,
        composer_two["id"],
        writer_share_pct=70.00,
        publisher_share_pct=30.00,
        blanket_opt_in=True,
    )

    work_a = _cataloged_work_under(
        api,
        composer_one,
        agreement_one,
        title="Tidewater Theme",
        duration_sec=180,
        tempo_bpm=108,
        genre="CINEMATIC",
        mood_tags=["EPIC"],
        instrumentation=["STRINGS", "BRASS"],
    )
    work_b = _cataloged_work_under(
        api,
        composer_two,
        agreement_two,
        title="Paper Lantern",
        duration_sec=120,
        tempo_bpm=92,
        genre="JAZZ",
        mood_tags=["CALM"],
        instrumentation=["PIANO"],
    )

    licensee = new_licensee(
        api,
        legal_name="Harborview Broadcasting",
        licensee_type="BROADCASTER",
        credit_limit_cents=10000000,
    )
    blanket = new_active_blanket(
        api,
        licensee=licensee,
        coverage_start="2026-08-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        annual_fee_cents=4800000,
        reporting_cadence="MONTHLY",
        usage_cap_minutes=3,
        pool_share_pct=25.00,
    )
    open_usage_report(
        api,
        blanket,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
    )
    sheet = new_registered_cue_sheet(
        api,
        [
            build.cue(work_a.composition_id, "THEME", 45),
            build.cue(work_a.composition_id, "FEATURE", 45),
            build.cue(work_a.composition_id, "BACKGROUND", 45),
            build.cue(work_b.composition_id, "FEATURE", 30),
        ],
        usage_report_id=blanket.usage_report_id,
        production_title="Tidewater Weekly Ep 1",
        broadcast_date="2026-08-05T00:00:00Z",
        market_tier="NETWORK",
        society_reference="ASCAP-BLK-0001",
    )
    submit_usage_report(api, blanket)
    return {
        "blanket": blanket,
        "work_a": work_a,
        "work_b": work_b,
        "cue_sheet": sheet,
    }


class TestUsageReportAcceptancePoolCascade:
    def test_acceptance_freezes_the_period_minutes_with_one_ceiling_per_report(
        self, api, clock_origin
    ):
        """PRD §3.6: "`reported_minutes_total` is the sum of those sheets' `total_seconds`
        divided by 60 and rounded **up** to a whole minute; because the ceiling is applied
        once per report, partial minutes never carry from one period into the next."

        Design: Difficulty/transitive_cascade/usage_report_acceptance_five_step_pool_cascade
        """
        ground = _submitted_blanket_period(api)
        blanket = accept_usage_report(api, ground["blanket"])

        report = blanket.usage_report
        assert_status(report, "ACCEPTED")
        assert report["reported_minutes_total"] == 3, (
            "165 seconds of reported cue time is three whole minutes once ceiled"
        )
        assert_credits_equal(report["reported_credits_total"], 3.66, "reported_credits_total")
        assert_same_instant(report["accepted_at"], clock_origin)

    def test_year_to_date_minutes_are_recomputed_from_the_accepted_report(self, api):
        """PRD §3.6: "**Step two**: because this report is now `ACCEPTED`, the agreement's
        `reported_minutes_ytd` is recomputed as the sum of `reported_minutes_total` over all
        of its accepted reports."

        Design: Difficulty/transitive_cascade/usage_report_acceptance_five_step_pool_cascade
        """
        ground = _submitted_blanket_period(api)
        blanket = ground["blanket"]

        before = read_blanket_agreement(api, blanket.agreement_id)
        assert before["reported_minutes_ytd"] == 0, (
            "no report of this agreement is accepted yet"
        )

        accept_usage_report(api, blanket)
        after = read_blanket_agreement(api, blanket.agreement_id)
        assert after["reported_minutes_ytd"] == 3

    def test_usage_landing_exactly_on_the_cap_derives_no_overage(self, api):
        """PRD §3.6: "**Step three**: because year-to-date minutes changed,
        `overage_minutes` is recomputed as `reported_minutes_ytd` less `usage_cap_minutes`,
        floored at 0 — usage exactly at the cap is not over it — and `overage_cents` as
        `overage_minutes` multiplied by the overage rate of 4.50 dollars per minute, that is
        450 cents per reported minute."

        Design: Difficulty/transitive_cascade/usage_report_acceptance_five_step_pool_cascade
        """
        ground = _submitted_blanket_period(api)
        blanket = accept_usage_report(api, ground["blanket"])

        agreement = read_blanket_agreement(api, blanket.agreement_id)
        assert agreement["reported_minutes_ytd"] == agreement["usage_cap_minutes"] == 3
        assert agreement["overage_minutes"] == 0
        assert_cents_equal(agreement["overage_cents"], 0, "overage_cents")

    def test_pool_money_is_the_annual_fee_share_for_one_cadence_period(self, api):
        """PRD §3.6: "`pool_cents` is the sum of two separately rounded terms: the
        agreement's `annual_fee_cents` multiplied by `pool_share_pct`, divided by 100,
        multiplied by the cadence fraction, rounded half up; plus the overage increment
        multiplied by `pool_share_pct` divided by 100, rounded half up."

        Design: Difficulty/transitive_cascade/usage_report_acceptance_five_step_pool_cascade
        """
        ground = _submitted_blanket_period(api)
        blanket = accept_usage_report(api, ground["blanket"])

        report = read_usage_report(api, blanket.usage_report_id)
        # 4800000 * 25.00 / 100 * one twelfth, plus nothing for a nil overage increment.
        assert_cents_equal(report["pool_cents"], 100000, "pool_cents")
        assert_pool_conserves_cents(report)

    def test_admin_retention_is_withheld_before_the_pool_is_distributed(self, api):
        """PRD §3.6: "`pool_admin_fee_cents` is `pool_cents` multiplied by the
        administration retention of 15.00 percent divided by 100, rounded half up."

        Design: Difficulty/transitive_cascade/usage_report_acceptance_five_step_pool_cascade
        """
        ground = _submitted_blanket_period(api)
        blanket = accept_usage_report(api, ground["blanket"])

        report = read_usage_report(api, blanket.usage_report_id)
        assert_cents_equal(report["pool_admin_fee_cents"], 15000, "pool_admin_fee_cents")
        assert_cents_equal(
            report["pool_distributable_cents"], 85000, "pool_distributable_cents"
        )
        assert_pool_conserves_cents(report)

    def test_largest_remainder_hands_the_odd_cent_to_the_higher_credit_work(self, api):
        """PRD §3.6: "The remainder is `pool_distributable_cents` less the sum of the floor
        shares, and exactly that many works — taken in order of credits descending, then
        `created_at` ascending, then `id` ascending — each receive exactly one additional
        cent."

        Design: Difficulty/transitive_cascade/usage_report_acceptance_five_step_pool_cascade
        """
        ground = _submitted_blanket_period(api)
        blanket = accept_usage_report(api, ground["blanket"])

        report = read_usage_report(api, blanket.usage_report_id)
        assert len(report["pool_allocations"]) == 2
        # Floor shares are 69904 and 15095, so one cent is left over and goes to the
        # 3.01-credit work rather than to the 0.65-credit one.
        assert_allocation(report, ground["work_a"].composition_id, 3.01, 69905)
        assert_allocation(report, ground["work_b"].composition_id, 0.65, 15095)
        assert_pool_conserves_cents(report)

    def test_one_blanket_pool_entry_per_allocation_moves_each_composer_position(
        self, api, clock_origin
    ):
        """PRD §3.6: "**Step five**: because allocations exist, one ledger entry with the
        blanket-pool origin is appended per allocation, for the composer of that
        allocation's work, whose amount is the allocation multiplied by the governing
        agreement's `writer_share_pct` divided by 100 and rounded half up, pointing at this
        report, with both its accrual and cash instants set to the clock; each append raises
        that composer's `accrued_unpaid_cents`, and the entries are appended in
        `pool_allocations` order."

        Design: Difficulty/transitive_cascade/usage_report_acceptance_five_step_pool_cascade
        """
        ground = _submitted_blanket_period(api)
        blanket = accept_usage_report(api, ground["blanket"])
        report_id = blanket.usage_report_id

        composer_one_id = ground["work_a"].composer_id
        composer_two_id = ground["work_b"].composer_id

        # 69905 at a 50.00 writer share and 15095 at a 70.00 writer share.
        entry_one = assert_single_ledger_entry(
            ledger_entries(api, composer_one_id), "BLANKET_POOL", 34953, source_ref_id=report_id
        )
        entry_two = assert_single_ledger_entry(
            ledger_entries(api, composer_two_id), "BLANKET_POOL", 10567, source_ref_id=report_id
        )
        for entry in (entry_one, entry_two):
            assert_same_instant(entry["accrual_recognized_at"], clock_origin)
            assert_same_instant(entry["cash_recognized_at"], clock_origin)

        # Each composer already carried the writer's performance amount from the
        # registration of the same sheet: 1882 for the first, 569 for the second.
        assert_composer_money(
            read_composer(api, composer_one_id), accrued_unpaid_cents=36835
        )
        assert_composer_money(
            read_composer(api, composer_two_id), accrued_unpaid_cents=11136
        )

    def test_the_agreement_accumulates_the_period_pool_totals(self, api):
        """PRD §3.6: "The agreement carries two running totals over its accepted reports:
        `pool_distributed_cents`, the sum of their `pool_distributable_cents`, and
        `pool_admin_fee_cents`, the sum of their `pool_admin_fee_cents` — the same name
        appearing on both the report and the agreement, per-period on the one and cumulative
        on the other."

        Design: Difficulty/transitive_cascade/usage_report_acceptance_five_step_pool_cascade
        """
        ground = _submitted_blanket_period(api)
        blanket = accept_usage_report(api, ground["blanket"])

        report = read_usage_report(api, blanket.usage_report_id)
        agreement = read_blanket_agreement(api, blanket.agreement_id)
        assert_cents_equal(
            agreement["pool_distributed_cents"], 85000, "pool_distributed_cents"
        )
        assert_cents_equal(
            agreement["pool_admin_fee_cents"], 15000, "cumulative pool_admin_fee_cents"
        )
        assert_cents_equal(
            agreement["pool_distributed_cents"],
            report["pool_distributable_cents"],
            "one accepted period sums to that period's distributable pool",
        )


# ---------------------------------------------------------------------------
# Ground for the agreement termination chain
# ---------------------------------------------------------------------------


def _two_quoted_requests_on_one_agreement(api):
    """One agreement governing two catalogued works, each quoted for one buyer.

    Both requests are priced from the same BROADCAST_TV tier at a base rate of
    300000 cents over a NATIONAL, 12-month, non-exclusive term, so each quote is
    390000 cents and the licensee reserves 780000 cents in total. No licence is
    issued, so committed spend stays at 0.
    """
    composer = new_composer(api, display_name="Yusuf Adeyemi", pro_affiliation="ASCAP")
    agreement = new_active_agreement(api, composer["id"])
    work_a = _cataloged_work_under(
        api,
        composer,
        agreement,
        title="Lagos Pulse",
        duration_sec=175,
        tempo_bpm=120,
        genre="HIPHOP",
        mood_tags=["UPLIFTING"],
        instrumentation=["PERCUSSION", "SYNTH"],
    )
    work_b = _cataloged_work_under(
        api,
        composer,
        agreement,
        title="Lagos Pulse Reprise",
        duration_sec=95,
        tempo_bpm=120,
        genre="HIPHOP",
        mood_tags=["UPLIFTING"],
        instrumentation=["PERCUSSION"],
    )

    tier = new_tier(
        api,
        code=f"BTV-STD-{build.next_suffix()}",
        media_type="BROADCAST_TV",
        allowed_scales=["LOCAL", "NATIONAL", "WORLDWIDE"],
        base_rate_cents=300000,
        min_term_months=1,
        max_term_months=120,
    )
    licensee = new_licensee(
        api,
        legal_name="Silverline Studios",
        licensee_type="PRODUCTION_COMPANY",
        credit_limit_cents=10000000,
    )

    deals = []
    for work in (work_a, work_b):
        deal = Deal(work, tier, licensee)
        submit_sync_request(
            api,
            deal,
            media_type="BROADCAST_TV",
            distribution_scale="NATIONAL",
            requested_term_start="2026-09-01T00:00:00Z",
            requested_term_months=12,
            exclusive_requested=False,
            rush_requested=False,
        )
        review_sync_request(api, deal)
        quote_sync_request(api, deal, quote_valid_days=14)
        assert_cents_equal(deal.sync_request["quoted_fee_cents"], 390000, "quoted_fee_cents")
        deals.append(deal)

    return {
        "composer": composer,
        "agreement": agreement,
        "work_a": work_a,
        "work_b": work_b,
        "licensee": licensee,
        "deal_a": deals[0],
        "deal_b": deals[1],
    }


def _terminate(api, agreement_id):
    return assert_ok(
        api.terminate_agreement(agreement_id, {"reason": "composer exit"}, RIGHTS_MANAGER)
    )


class TestAgreementTerminationWithdrawalCascade:
    def test_termination_records_the_exit_on_the_agreement(self, api, clock_origin):
        """PRD §3.1: "The agreement moves to `TERMINATED` and records `terminated_at`."

        Design: Difficulty/transitive_cascade/agreement_termination_withdraw_decline_credit_release_cascade
        """
        ground = _two_quoted_requests_on_one_agreement(api)
        terminated = _terminate(api, ground["agreement"]["id"])

        assert_status(terminated, "TERMINATED")
        assert_same_instant(terminated["terminated_at"], clock_origin)
        assert terminated["amendment_round"] == 0, (
            "no amendment was ever opened on this agreement"
        )
        assert terminated["pending_writer_share_pct"] is None
        assert terminated["pending_publisher_share_pct"] is None
        assert terminated["pending_sync_fee_share_pct"] is None
        assert terminated["pending_holdback_days"] is None

    def test_every_governed_work_is_withdrawn_on_the_rights_axis_alone(self, api):
        """PRD §3.1: "Because the agreement is now terminated, every composition it governs
        whose `availability_status` is `AVAILABLE` or `RESTRICTED` moves to `WITHDRAWN`,
        processed in `created_at` ascending order."

        Design: Difficulty/transitive_cascade/agreement_termination_withdraw_decline_credit_release_cascade
        """
        ground = _two_quoted_requests_on_one_agreement(api)
        for work in (ground["work_a"], ground["work_b"]):
            assert_composition_axes(
                read_composition(api, work.composition_id), "CATALOGED", "AVAILABLE"
            )

        _terminate(api, ground["agreement"]["id"])

        for work in (ground["work_a"], ground["work_b"]):
            assert_composition_axes(
                read_composition(api, work.composition_id), "CATALOGED", "WITHDRAWN"
            )

    def test_open_quoted_requests_are_declined_as_catalog_withdrawn(self, api):
        """PRD §3.1: "Because those works are now withdrawn, every sync request citing one
        of them whose `status` is `SUBMITTED`, `UNDER_REVIEW`, `QUOTED` or
        `REVISION_REQUESTED` moves to `DECLINED` with `decline_reason` set to the literal
        string `CATALOG_WITHDRAWN`, again in `created_at` ascending order."

        Design: Difficulty/transitive_cascade/agreement_termination_withdraw_decline_credit_release_cascade
        """
        ground = _two_quoted_requests_on_one_agreement(api)
        _terminate(api, ground["agreement"]["id"])

        for deal in (ground["deal_a"], ground["deal_b"]):
            request = assert_ok(api.get_sync_request(deal.sync_request_id, LICENSING_AGENT))
            assert_status(request, "DECLINED")
            assert request["decline_reason"] == "CATALOG_WITHDRAWN"

    def test_the_licensee_reservation_is_released_and_versioned_once(self, api):
        """PRD §3.1: "Because those sync requests have left the reserving states, each
        affected licensee's `reserved_spend_cents` and `credit_available_cents` are
        recomputed and that licensee's `version` increments exactly once, however many of its
        requests were declined."

        Design: Difficulty/transitive_cascade/agreement_termination_withdraw_decline_credit_release_cascade
        """
        ground = _two_quoted_requests_on_one_agreement(api)
        licensee_id = ground["licensee"]["id"]

        before = read_licensee(api, licensee_id)
        assert_credit_exposure(before, 0, 780000, 9220000)

        _terminate(api, ground["agreement"]["id"])

        after = read_licensee(api, licensee_id)
        assert_credit_exposure(after, 0, 0, 10000000)
        assert after["version"] == before["version"] + 1, (
            "two declined requests still advance the licensee version only once"
        )

    def test_the_withdrawal_cascade_moves_no_money_into_the_composer_ledger(self, api):
        """PRD §3.1: "`accrued_unpaid_cents` is the sum of the signed amounts of every
        ledger entry belonging to this composer that has not yet been swept into a statement
        and whose economic origin is neither an advance nor an advance recoupment."

        Design: Difficulty/transitive_cascade/agreement_termination_withdraw_decline_credit_release_cascade
        """
        ground = _two_quoted_requests_on_one_agreement(api)
        composer_id = ground["composer"]["id"]

        _terminate(api, ground["agreement"]["id"])

        assert ledger_entries(api, composer_id) == [], (
            "declining a quote appends no ledger entry, so the sum is over an empty set"
        )
        assert_composer_money(read_composer(api, composer_id), accrued_unpaid_cents=0)
