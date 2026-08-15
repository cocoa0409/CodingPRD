"""Royalty runs, statements, waterfall, recoupment: the money lifecycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_revenue_report,
    add_track,
    approve_tour_expense,
    create_and_start_project,
    create_artist,
    create_distributor,
    create_label,
    create_release,
    deliver_release,
    disburse_advance,
    finalize_run,
    get_recoupment_account,
    get_run_statement,
    get_success_data,
    go_live_release,
    list_run_statements,
    make_artist_portal_headers,
    make_finance_headers,
    make_label_admin_headers,
    open_close_calculate_run,
    schedule_release,
    assemble_and_lock_release,
    setup_advanced_tour_support,
    setup_live_single_release,
    sign_artist_via_memo,
    submit_tour_expense,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_promo_campaign_payload, create_royalty_run_payload
from test_helpers.fixtures import ADMIN, ANR, FIN, MKT, set_clock


# ===========================================================================
# Queue A — dual_variant_calc/provisional_vs_final_net_payable
# ===========================================================================


def _setup_provisional_statement(label_name, artist_name, track_isrc, advance_cents=100_000):
    """Full pipeline to a PROVISIONAL statement. Returns (world, run, stmt).

    Numbers (with defaults): 1 STREAMING report gross 1_000_000, units 10_000;
    base rate 2000 bps; MASTER_ONLY; advance bucket = advance_cents (disbursed
    when > 0)."""
    world = setup_live_single_release(
        label_name=label_name, artist_name=artist_name, track_isrc=track_isrc,
        advance_cents=advance_cents,
        memo_overrides={"base_royalty_rate_bps": 2_000, "recoupment_scope": "MASTER_ONLY",
                        "promo_costs_recoupable": False},
        release_date="2026-09-01",
        go_live_clock="2026-09-01T00:00:00Z",
    )
    add_revenue_report(world["label"]["id"], world["distributor"]["id"],
                       world["release"]["id"], period="2026-Q3", channel="STREAMING",
                       units=10_000, gross_revenue_cents=1_000_000)
    run = open_close_calculate_run(world["label"]["id"], "2026-Q3")
    stmt = get_run_statement(run["id"], world["contract"]["id"])
    return world, run, stmt


class TestProvisionalVsFinalNetPayable:
    def test_provisional_statement_holds_reserve(self):
        """PRD §3.8: "the remainder is `royalty_earned_cents` minus
        `projected_recoupment_cents`; the reserve is that remainder multiplied by
        the label's `reserve_rate_bps` and divided by 10,000, rounded half up to
        whole cents, and stored as `reserve_held_cents`; and `net_payable_cents` is
        the remainder minus the reserve plus `adjustment_cents`, which starts at
        zero."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_net_payable
        """
        world, run, stmt = _setup_provisional_statement("Label C", "Artist C",
                                                        "USRC10000001")
        assert stmt["status"] == "PROVISIONAL"
        # Net = round(1_000_000 * 7000/10000) = 700_000. Royalty = round(700_000 * 0.20) = 140_000.
        assert stmt["royalty_earned_cents"] == 140_000
        assert stmt["projected_recoupment_cents"] == 100_000
        # reserve = round((140000-100000) * 1000/10000) = 4000
        assert stmt["reserve_held_cents"] == 4_000
        # net = 140000 - 100000 - 4000 + 0
        assert stmt["net_payable_cents"] == 36_000

    def test_finalize_releases_reserve_and_recomputes(self):
        """PRD §3.8: "every statement of the run moves from `PROVISIONAL` to `FINAL`:
        its `reserve_held_cents` is released to zero, its recoupment switches from
        projection to actual with `recoupment_applied_cents` set from the waterfall
        result, and its `net_payable_cents` is recomputed under the final variant —
        `royalty_earned_cents` minus `recoupment_applied_cents` plus
        `adjustment_cents`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_net_payable
        """
        world, run, stmt = _setup_provisional_statement("Label C2", "Artist C2",
                                                        "USRC10000002")
        finalize_run(run["id"])
        stmt_final = get_success_data(api_client.get_royalty_statement(stmt["id"], FIN))
        assert stmt_final["status"] == "FINAL"
        assert stmt_final["recoupment_applied_cents"] == 100_000
        assert stmt_final["reserve_held_cents"] == 0
        # final net = 140000 - 100000 + 0 = 40000; delta over provisional = 4000 (the released reserve)
        assert stmt_final["net_payable_cents"] == 40_000
        assert stmt_final["net_payable_cents"] - stmt["net_payable_cents"] == 4_000


# ===========================================================================
# Queue A — dual_variant_calc/master_only_vs_cross_collateralized_waterfall
# ===========================================================================


def _setup_tour_bucket_contract(label, artist_name, track_isrc, scope, distributor):
    """Sign artist with scope, set up tour bucket of 30000, LIVE release + 5000-unit STREAMING report."""
    artist = create_artist(label["id"], artist_name)
    memo, contract = sign_artist_via_memo(
        artist["id"], advance_cents=0, base_royalty_rate_bps=2_000,
        recoupment_scope=scope, promo_costs_recoupable=False)
    # Tour: approved 60000, advanced 30000, one TRAVEL expense 30000 approved (cap floor(0.5*60000)=30000).
    ts = setup_advanced_tour_support(
        contract["id"], artist["id"], tour_name=f"Tour {artist_name}",
        requested_amount_cents=60_000, approved_budget_cents=60_000,
        advance_amount_cents=30_000)
    exp = submit_tour_expense(ts["id"], artist["id"], category="TRAVEL",
                              amount_cents=30_000, expense_date="2026-09-15")
    approve_tour_expense(exp["id"])
    # Release LIVE.
    project = create_and_start_project(contract["id"], title=f"P-{artist_name}")
    track = add_track(project["id"], isrc=track_isrc, advance_to="CLEARED")
    release = create_release(contract["id"], project["id"], [track["id"]],
                             release_date="2026-09-01")
    assemble_and_lock_release(release["id"])
    schedule_release(release["id"])
    deliver_release(release["id"], [distributor["id"]])
    go_live_release(release["id"], "2026-09-01T00:00:00Z")
    add_revenue_report(label["id"], distributor["id"], release["id"],
                       period="2026-Q3", channel="STREAMING", units=5_000,
                       gross_revenue_cents=500_000)
    return {"artist": artist, "contract": contract, "release": release}


class TestMasterOnlyVsCrossCollateralized:
    def test_master_only_ignores_tour_bucket(self):
        """PRD §3.8: "under `MASTER_ONLY` only the recording and advance buckets are
        visible to the waterfall, so the applied amount can be zero even while tour
        and promo balances stand positive".

        Design: Difficulty/dual_variant_calc/master_only_vs_cross_collateralized_waterfall
        """
        label = create_label("Label D")
        distributor = create_distributor(label["id"], name="DSP-D")
        ctx_m = _setup_tour_bucket_contract(label, "Artist M", "USRC10000011",
                                            "MASTER_ONLY", distributor)
        run = open_close_calculate_run(label["id"], "2026-Q3")
        finalize_run(run["id"])
        stmt = get_run_statement(run["id"], ctx_m["contract"]["id"])
        # Earned: net = round(500000*0.7)=350000, royalty = round(350000*0.20)=70000.
        assert stmt["royalty_earned_cents"] == 70_000
        assert stmt["recoupment_applied_cents"] == 0
        assert stmt["net_payable_cents"] == 70_000
        account = get_recoupment_account(ctx_m["contract"]["id"])
        assert account["tour_support_balance_cents"] == 30_000

    def test_cross_collateralized_drains_tour_bucket(self):
        """PRD §3.8: "under `CROSS_COLLATERALIZED` all four buckets are eligible, so
        identical earnings recoup strictly more whenever tour or promo balances are
        positive and the upstream buckets have been exhausted."

        Design: Difficulty/dual_variant_calc/master_only_vs_cross_collateralized_waterfall
        """
        label = create_label("Label D2")
        distributor = create_distributor(label["id"], name="DSP-D2")
        ctx_x = _setup_tour_bucket_contract(label, "Artist X", "USRC10000012",
                                            "CROSS_COLLATERALIZED", distributor)
        run = open_close_calculate_run(label["id"], "2026-Q3")
        finalize_run(run["id"])
        stmt = get_run_statement(run["id"], ctx_x["contract"]["id"])
        assert stmt["royalty_earned_cents"] == 70_000
        assert stmt["recoupment_applied_cents"] == 30_000
        assert stmt["net_payable_cents"] == 40_000
        account = get_recoupment_account(ctx_x["contract"]["id"])
        assert account["tour_support_balance_cents"] == 0


# ===========================================================================
# Queue A — combinatorial_formula/tiered_rate_with_option_escalation_straddle
# ===========================================================================


def _setup_tiered_straddle(label_name, artist_name, track_isrc):
    """Signed contract with option; prior Q2 cumulative 499999; option exercised
    (effective 1950); 3 DOWNLOAD lines in Q3 (1 unit each, gross 100)."""
    label = create_label(label_name)
    artist = create_artist(label["id"], artist_name)
    memo, contract = sign_artist_via_memo(
        artist["id"], advance_cents=0, base_royalty_rate_bps=1_800,
        recoupment_scope="MASTER_ONLY", options_total=1, option_escalation_bps=150,
        term_months=12, valid_until_date="2028-06-01")
    project = create_and_start_project(contract["id"], title=f"P-{label_name}")
    track = add_track(project["id"], isrc=track_isrc, advance_to="CLEARED")
    release = create_release(contract["id"], project["id"], [track["id"]],
                             release_date="2026-09-01")
    assemble_and_lock_release(release["id"])
    schedule_release(release["id"])
    distributor = create_distributor(label["id"], name=f"DSP-{label_name}")
    deliver_release(release["id"], [distributor["id"]])
    go_live_release(release["id"], "2026-09-01T00:00:00Z")
    # Prior period 2026-Q2: 499999 units. The Q2 report is deliberately left
    # uncounted — no 2026-Q2 run is ever opened — so per PRD §3.8 ("a report
    # joins the earliest run whose period is on or after the report's period")
    # it is picked up by the 2026-Q3 run, where its units feed the tier walk's
    # prior cumulative ("the sum of `units` over the contract's eligible reports
    # whose periods are strictly earlier than the run's period"). Pinning the
    # prior cumulative through an uncounted report keeps the expected totals
    # identical under either reading of "eligible" for already-counted reports.
    add_revenue_report(label["id"], distributor["id"], release["id"],
                       period="2026-Q2", channel="STREAMING", units=499_999,
                       gross_revenue_cents=100_000)
    # Advance clock into option window and exercise.
    set_clock("2027-05-15T00:00:00Z")
    get_success_data(api_client.sweep_label(label["id"], ADMIN))
    contract_after = get_success_data(api_client.exercise_option(contract["id"], ADMIN))
    # Q3 current-period lines: 3 DOWNLOAD reports 1 unit each gross 100.
    # PRD §3.8 uniqueness is per (label, distributor, release, period, channel),
    # so three same-period same-channel lines need three distinct distributors.
    q3_distributors = [
        create_distributor(label["id"], name=f"DSP-{label_name}-q3-{i}")
        for i in range(3)
    ]
    for dist in q3_distributors:
        add_revenue_report(label["id"], dist["id"], release["id"],
                           period="2026-Q3", channel="DOWNLOAD", units=1,
                           gross_revenue_cents=100)
    run_q3 = open_close_calculate_run(label["id"], "2026-Q3")
    stmt = get_run_statement(run_q3["id"], contract_after["id"])
    return label, artist, contract_after, release, distributor, run_q3, stmt


class TestTieredRateWithOptionEscalation:
    def test_marginal_rate_straddles_threshold(self):
        """PRD §3.8: "The walk maintains a running cumulative unit count that starts
        at the prior cumulative: the sum of `units` over the contract's eligible
        reports whose periods are strictly earlier than the run's period. Each
        line's own `units` are added to the running cumulative before its tier is
        selected, and the line's tier is the last threshold in the label's
        `tier_thresholds` whose unit mark is strictly less than the running
        cumulative."

        Design: Difficulty/combinatorial_formula/tiered_rate_with_option_escalation_straddle
        """
        label, artist, contract, release, distributor, run_q3, stmt = _setup_tiered_straddle(
            "Label A", "Artist A", "USRC10000021")
        # effective rate = min(1800 + 1*150, 3000) = 1950
        assert contract["effective_base_rate_bps"] == 1_950
        # Prior cumulative 499999; line1 -> cum 500000 (tier 1, rate 1950): round(85*0.195)=17.
        # line2 -> cum 500001 (tier 2, rate 2150): round(85*0.215)=18. line3 same: 18. Total 53.
        assert stmt["royalty_earned_cents"] == 53
        # reserve = round(53 * 1000/10000) = 5; net = 53 - 0 - 5 + 0 = 48
        assert stmt["net_payable_cents"] == 48
        # Distinguish from naive all-tier-1 (51) or all-tier-2 (54) computations.
        assert stmt["royalty_earned_cents"] != 51
        assert stmt["royalty_earned_cents"] != 54

    def test_effective_rate_recomputed_after_option(self):
        """PRD §3.3: "Exercising increments `options_exercised` by one, pushes
        `current_term_end_date` out by `option_term_months` calendar months,
        recomputes the contract's `effective_base_rate_bps` ...".

        Design: Difficulty/combinatorial_formula/tiered_rate_with_option_escalation_straddle
        """
        label, artist, contract, release, distributor, run_q3, stmt = _setup_tiered_straddle(
            "Label A2", "Artist A2", "USRC10000022")
        assert contract["options_exercised"] == 1
        assert contract["effective_base_rate_bps"] == 1_950


# ===========================================================================
# Queue A — combinatorial_formula/per_line_rounding_then_sum_pinned
# ===========================================================================


class TestPerLineRoundingThenSum:
    def test_three_lines_round_individually(self):
        """PRD §2.6: "Royalty computations obey a pinned rounding order: every
        revenue line is rounded individually, and statement totals are sums of
        those already-rounded line values; the system never sums unrounded values
        and rounds once at the end."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_pinned
        """
        world = setup_live_single_release(
            label_name="Label B", artist_name="Artist B", track_isrc="USRC10000023",
            advance_cents=0,
            memo_overrides={"base_royalty_rate_bps": 1_800, "recoupment_scope": "MASTER_ONLY"},
        )
        # PRD §3.8 uniqueness is per (label, distributor, release, period,
        # channel), so three identical lines need three distinct distributors.
        dists = [world["distributor"]] + [
            create_distributor(world["label"]["id"], name=f"DSP-B-x{i}")
            for i in range(2)
        ]
        for dist in dists:
            add_revenue_report(world["label"]["id"], dist["id"],
                               world["release"]["id"], period="2026-Q3",
                               channel="STREAMING", units=10, gross_revenue_cents=35)
        run = open_close_calculate_run(world["label"]["id"], "2026-Q3")
        stmt = get_run_statement(run["id"], world["contract"]["id"])
        # Per line: net = round(35 * 0.7) = 25 (half-up). royalty = round(25 * 0.18) = 5. Total 15.
        assert stmt["gross_revenue_cents"] == 105
        assert stmt["net_revenue_cents"] == 75
        assert stmt["royalty_earned_cents"] == 15
        # Forbidden sum-then-round would give round(75 * 0.18) = 14.
        assert stmt["royalty_earned_cents"] != 14

    def test_round_half_up_per_line(self):
        """PRD §2.6: "Where a computation produces a fraction, the result is rounded
        half up to the nearest whole cent."
        PRD §3.8: "each line's royalty is that net multiplied by the line rate and
        divided by ten thousand, again rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_pinned
        """
        # A single line: gross 35 STREAMING -> net round(24.5) = 25 (half-up of .5).
        world = setup_live_single_release(
            label_name="Label B2", artist_name="Artist B2", track_isrc="USRC10000024",
            advance_cents=0,
            memo_overrides={"base_royalty_rate_bps": 1_800, "recoupment_scope": "MASTER_ONLY"},
        )
        add_revenue_report(world["label"]["id"], world["distributor"]["id"],
                           world["release"]["id"], period="2026-Q3",
                           channel="STREAMING", units=10, gross_revenue_cents=35)
        run = open_close_calculate_run(world["label"]["id"], "2026-Q3")
        stmt = get_run_statement(run["id"], world["contract"]["id"])
        assert stmt["net_revenue_cents"] == 25  # 24.5 rounds half-up
        assert stmt["royalty_earned_cents"] == 5  # round(25 * 0.18) = round(4.5) = 5


# ===========================================================================
# Queue A — combinatorial_formula/reserve_then_adjust_evaluation_order
# ===========================================================================


class TestReserveThenAdjustEvaluationOrder:
    def test_adjustment_after_reserve(self):
        """PRD §3.8: "Adjustments always enter after the reserve is computed — an
        adjustment never changes `reserve_held_cents` — so with a positive reserve
        rate and a positive remainder, a provisional statement always shows a lower
        payable than its final counterpart."

        Design: Difficulty/combinatorial_formula/reserve_then_adjust_evaluation_order
        """
        world, run, stmt = _setup_provisional_statement("Label E", "Artist E",
                                                        "USRC10000023")
        adjusted = get_success_data(api_client.adjust_royalty_statement(
            stmt["id"],
            {"expected_royalty_statement_version": stmt["version"],
             "adjustment_delta_cents": 2_500},
            FIN))
        assert adjusted["adjustment_cents"] == 2_500
        # Reserve unchanged: still 4000.
        assert adjusted["reserve_held_cents"] == 4_000
        # Net = 140000 - 100000 - 4000 + 2500 = 38500 (not (40000+2500)*0.9 = 38250).
        assert adjusted["net_payable_cents"] == 38_500
        assert adjusted["net_payable_cents"] != 38_250

    def test_reserve_unchanged_by_adjustment(self):
        """PRD §3.8: "Adjustments always enter after the reserve is computed — an
        adjustment never changes `reserve_held_cents` — so with a positive reserve
        rate and a positive remainder, a provisional statement always shows a lower
        payable than its final counterpart."

        Design: Difficulty/combinatorial_formula/reserve_then_adjust_evaluation_order
        """
        world, run, stmt = _setup_provisional_statement("Label E2", "Artist E2",
                                                        "USRC10000025")
        reserve_before = stmt["reserve_held_cents"]
        adjusted = get_success_data(api_client.adjust_royalty_statement(
            stmt["id"],
            {"expected_royalty_statement_version": stmt["version"],
             "adjustment_delta_cents": 1_000},
            FIN))
        assert adjusted["reserve_held_cents"] == reserve_before


# ===========================================================================
# Queue A — transitive_cascade/royalty_finalize_cascades_statement_waterfall_payout_flip
# ===========================================================================


class TestRoyaltyFinalizeCascade:
    def test_finalize_flips_payout_status(self):
        """PRD §3.8: "Finalization moves the run from `CALCULATED` to `FINALIZED` in
        a three-link cascade. First, every statement of the run moves from
        `PROVISIONAL` to `FINAL` ... Second, each finalized statement applies the
        waterfall to its contract's recoupment account: the eligible bucket
        balances are reduced in the pinned priority order, and the account's
        `total_recouped_cents` grows by the applied amount. Third, any account
        whose `total_unrecouped_cents` has reached zero flips its `payout_status`
        from `RECOUPING` to `EARNING`."

        Design: Difficulty/transitive_cascade/royalty_finalize_cascades_statement_waterfall_payout_flip
        """
        world, run, stmt = _setup_provisional_statement("Label T2", "Artist T2",
                                                        "USRC10000042")
        assert world["account"]["payout_status"] == "RECOUPING"
        run_after = finalize_run(run["id"])
        assert run_after["status"] == "FINALIZED"
        # Link 1: statement FINAL, applied 100000.
        stmt_after = get_success_data(api_client.get_royalty_statement(stmt["id"], FIN))
        assert stmt_after["status"] == "FINAL"
        assert stmt_after["recoupment_applied_cents"] == 100_000
        # Link 2: advance bucket drained.
        account = get_recoupment_account(world["contract"]["id"])
        assert account["advance_balance_cents"] == 0
        assert account["total_recouped_cents"] == 100_000
        # Link 3: total_unrecouped hits zero -> EARNING.
        assert account["total_unrecouped_cents"] == 0
        assert account["payout_status"] == "EARNING"

    def test_run_status_finalized(self):
        """PRD §3.8: "Finalization moves the run from `CALCULATED` to `FINALIZED`".

        Design: Difficulty/transitive_cascade/royalty_finalize_cascades_statement_waterfall_payout_flip
        """
        world, run, stmt = _setup_provisional_statement("Label T2b", "Artist T2b",
                                                        "USRC10000043")
        assert run["status"] == "CALCULATED"
        run_after = finalize_run(run["id"])
        assert run_after["status"] == "FINALIZED"


# ===========================================================================
# Queue A — boundary_precision_check/tier_boundary_unit_at_exact_threshold
# ===========================================================================


class TestTierBoundaryUnitAtExactThreshold:
    def test_unit_at_threshold_stays_in_tier1(self):
        """PRD §3.8: "the line's tier is the last threshold in the label's
        `tier_thresholds` whose unit mark is strictly less than the running
        cumulative."
        PRD §3.1: "a unit at a position strictly greater than a threshold earns
        that threshold's delta".

        Design: Difficulty/boundary_precision_check/tier_boundary_unit_at_exact_threshold
        """
        # Identical to straddle but only ONE Q3 DOWNLOAD line (1 unit, gross 100).
        label = create_label("Label B1")
        artist = create_artist(label["id"], "Artist B1")
        memo, contract = sign_artist_via_memo(
            artist["id"], advance_cents=0, base_royalty_rate_bps=1_800,
            recoupment_scope="MASTER_ONLY", options_total=1, option_escalation_bps=150,
            term_months=12, valid_until_date="2028-06-01")
        project = create_and_start_project(contract["id"], title="P-B1")
        track = add_track(project["id"], isrc="USRC10000061", advance_to="CLEARED")
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2026-09-01")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        distributor = create_distributor(label["id"], name="DSP-B1")
        deliver_release(release["id"], [distributor["id"]])
        go_live_release(release["id"], "2026-09-01T00:00:00Z")
        add_revenue_report(label["id"], distributor["id"], release["id"],
                           period="2026-Q2", channel="STREAMING", units=499_999,
                           gross_revenue_cents=100_000)
        run_q2 = open_close_calculate_run(label["id"], "2026-Q2")
        finalize_run(run_q2["id"])
        set_clock("2027-05-15T00:00:00Z")
        get_success_data(api_client.sweep_label(label["id"], ADMIN))
        get_success_data(api_client.exercise_option(contract["id"], ADMIN))
        # Single Q3 DOWNLOAD line, 1 unit -> cumulative reaches exactly 500000.
        add_revenue_report(label["id"], distributor["id"], release["id"],
                           period="2026-Q3", channel="DOWNLOAD", units=1,
                           gross_revenue_cents=100)
        run_q3 = open_close_calculate_run(label["id"], "2026-Q3")
        stmt = get_run_statement(run_q3["id"], contract["id"])
        # Cum 500000 is NOT strictly greater than threshold 500000 -> tier 1 (delta 0),
        # rate 1950. Net round(100*0.85)=85. Royalty round(85*0.195)=round(16.575)=17.
        assert stmt["royalty_earned_cents"] == 17
        assert stmt["royalty_earned_cents"] != 18

    def test_unit_one_past_threshold_moves_to_tier2(self):
        """PRD §3.1: "a unit at a position strictly greater than a threshold earns
        that threshold's delta".

        Design: Difficulty/boundary_precision_check/tier_boundary_unit_at_exact_threshold
        """
        # Set up cumulative 500000 exactly via Q2 (499999) + first Q3 line already
        # counted? No — instead put TWO lines in Q3: line1 cum 500000 (tier1),
        # line2 cum 500001 (tier2). Together 17+18=35.
        label = create_label("Label B1b")
        artist = create_artist(label["id"], "Artist B1b")
        memo, contract = sign_artist_via_memo(
            artist["id"], advance_cents=0, base_royalty_rate_bps=1_800,
            recoupment_scope="MASTER_ONLY", options_total=1, option_escalation_bps=150,
            term_months=12, valid_until_date="2028-06-01")
        project = create_and_start_project(contract["id"], title="P-B1b")
        track = add_track(project["id"], isrc="USRC10000062", advance_to="CLEARED")
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2026-09-01")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        distributor = create_distributor(label["id"], name="DSP-B1b")
        deliver_release(release["id"], [distributor["id"]])
        go_live_release(release["id"], "2026-09-01T00:00:00Z")
        add_revenue_report(label["id"], distributor["id"], release["id"],
                           period="2026-Q2", channel="STREAMING", units=499_999,
                           gross_revenue_cents=100_000)
        # The Q2 report is deliberately left uncounted (no 2026-Q2 run is
        # opened), so it joins the 2026-Q3 run per PRD §3.8 and feeds the tier
        # walk's prior cumulative under either reading of "eligible".
        set_clock("2027-05-15T00:00:00Z")
        get_success_data(api_client.sweep_label(label["id"], ADMIN))
        get_success_data(api_client.exercise_option(contract["id"], ADMIN))
        # PRD §3.8 uniqueness is per (label, distributor, release, period,
        # channel) — two same-period same-channel lines need two distributors.
        q3_distributors = [
            create_distributor(label["id"], name=f"DSP-B1b-q3-{i}")
            for i in range(2)
        ]
        for dist in q3_distributors:
            add_revenue_report(label["id"], dist["id"], release["id"],
                               period="2026-Q3", channel="DOWNLOAD", units=1,
                               gross_revenue_cents=100)
        run_q3 = open_close_calculate_run(label["id"], "2026-Q3")
        stmt = get_run_statement(run_q3["id"], contract["id"])
        # line1: cum 500000 -> tier1 -> 17; line2: cum 500001 -> tier2 (2150) -> 18.
        assert stmt["royalty_earned_cents"] == 35


# ===========================================================================
# Queue A — compensating_invariant/statement_adjust_roundtrip_conserves_net_payable
# ===========================================================================


class TestStatementAdjustRoundtrip:
    def test_plus_then_minus_restores_net(self):
        """PRD §3.8: "The delta is added into `adjustment_cents`, `net_payable_cents`
        is recomputed within the statement's current variant, and the statement's
        `version` increments."

        Design: Difficulty/compensating_invariant/statement_adjust_roundtrip_conserves_net_payable
        """
        world, run, stmt = _setup_provisional_statement("Label I2", "Artist I2",
                                                        "USRC10000091")
        assert stmt["net_payable_cents"] == 36_000
        v1 = stmt["version"]
        a1 = get_success_data(api_client.adjust_royalty_statement(
            stmt["id"], {"expected_royalty_statement_version": v1,
                         "adjustment_delta_cents": 2_500}, FIN))
        assert a1["net_payable_cents"] == 38_500
        assert a1["adjustment_cents"] == 2_500
        a2 = get_success_data(api_client.adjust_royalty_statement(
            stmt["id"], {"expected_royalty_statement_version": a1["version"],
                         "adjustment_delta_cents": -2_500}, FIN))
        assert a2["net_payable_cents"] == 36_000
        assert a2["adjustment_cents"] == 0
        assert a2["version"] == v1 + 2

    def test_version_increments_by_one_per_adjust(self):
        """PRD §2.5: "The `version` is a system-managed integer that increments by
        one on every mutation".
        PRD §3.8: "the statement's `version` increments".

        Design: Difficulty/compensating_invariant/statement_adjust_roundtrip_conserves_net_payable
        """
        world, run, stmt = _setup_provisional_statement("Label I2b", "Artist I2b",
                                                        "USRC10000092")
        v1 = stmt["version"]
        a1 = get_success_data(api_client.adjust_royalty_statement(
            stmt["id"], {"expected_royalty_statement_version": v1,
                         "adjustment_delta_cents": 100}, FIN))
        assert a1["version"] == v1 + 1
        a2 = get_success_data(api_client.adjust_royalty_statement(
            stmt["id"], {"expected_royalty_statement_version": a1["version"],
                         "adjustment_delta_cents": -100}, FIN))
        assert a2["version"] == v1 + 2


# ===========================================================================
# Queue B — royalty adjacent corners
# ===========================================================================


class TestLabelConfigDefaults:
    def test_defaults_materialize(self):
        """PRD §3.1: "`advance_cap_cents` (default 5,000,000) ... `reserve_rate_bps`
        (default 1,000 basis points) ... `sign_threshold_score` (default 40.0) ...
        `option_window_days` (default 90) ... `release_lead_days` (default 21) ...
        `beat_pre_release_days` (default 42) and `beat_post_release_days` (default
        30) ... `campaign_gap_days` (default 7)."

        Design: Corner/entities/label_creation_applies_config_defaults
        """
        label = create_label("Label E2")
        assert label["advance_cap_cents"] == 5_000_000
        assert label["reserve_rate_bps"] == 1_000
        assert label["sign_threshold_score"] == pytest.approx(40.0)
        assert label["release_lead_days"] == 21
        assert label["beat_pre_release_days"] == 42
        assert label["beat_post_release_days"] == 30
        assert label["campaign_gap_days"] == 7
        assert label["option_window_days"] == 90
        # tier_thresholds default: [{units:0,delta_bps:0},{units:500000,delta_bps:200},{units:2000000,delta_bps:300}]
        assert label["tier_thresholds"] == [
            {"units": 0, "delta_bps": 0},
            {"units": 500_000, "delta_bps": 200},
            {"units": 2_000_000, "delta_bps": 300},
        ]


class TestArtistScoutingScore:
    def test_score_computed_on_create(self):
        """PRD §3.1: "At creation the server computes the artist's `scouting_score`.
        ... The raw score is then multiplied by the label's genre multiplier for
        the artist's genre, the product is rounded half up to one decimal place,
        and the result is clamped so it never falls below 0 or above 100."

        Design: Corner/entities/artist_creation_computes_scouting_score
        """
        label = create_label("Label E1")
        artist = create_artist(label["id"], "Artist E1", genre="POP")
        # raw = 100*(0.30*0.6 + 0.20*0.4 + 0.25*0.5 + 0.25*0.5) = 51.0; POP 1.10 -> 56.1
        assert artist["scouting_score"] == pytest.approx(56.1, abs=1e-9)
        assert artist["status"] == "SCOUTED"
        assert artist["version"] == 1

    def test_genre_multiplier_applied(self):
        """PRD §3.1: "`genre_multipliers` (defaulting to 1.10 for `POP`, 1.05 for
        `HIPHOP`, 1.00 for `ROCK`, 0.95 for `ELECTRONIC`, and 0.90 for `OTHER`)
        scales scouting scores per genre."

        Design: Corner/calculations/scouting_score_genre_multiplier_applied
        """
        label = create_label("Label C1")
        pop = create_artist(label["id"], "Pop Act", genre="POP")
        rock = create_artist(label["id"], "Rock Act", genre="ROCK")
        # Same raw inputs; POP gets *1.10, ROCK gets *1.00.
        assert pop["scouting_score"] == pytest.approx(56.1, abs=1e-9)
        assert rock["scouting_score"] == pytest.approx(51.0, abs=1e-9)


class TestRevenueReportImmutability:
    def test_no_version_or_updated_at(self):
        """PRD §2.5: "A revenue report is an append-only ingest record: once created
        it is never modified, so it carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it."

        Design: Corner/entities/revenue_report_immutable_no_version_field
        """
        world = setup_live_single_release(
            label_name="Label E5", artist_name="Artist E5", track_isrc="USRC20000001")
        rep = add_revenue_report(world["label"]["id"], world["distributor"]["id"],
                                 world["release"]["id"], period="2026-Q3",
                                 channel="STREAMING", units=100, gross_revenue_cents=9_900)
        assert "id" in rep and "created_at" in rep
        assert "version" not in rep
        assert "updated_at" not in rep
        assert rep["gross_revenue_cents"] == 9_900
        assert rep["units"] == 100
        # Read back
        fetched = get_success_data(api_client.get_revenue_report(rep["id"], FIN))
        assert "version" not in fetched
        assert "updated_at" not in fetched


class TestSyncLineFlatShare:
    def test_sync_ignores_tiers_and_base_rate(self):
        """PRD §3.8: "`SYNC` lines ignore tiers entirely and earn a flat half of the
        line's net."
        PRD §3.1: "`channel_deduction_bps` (defaulting to ... 0 for `SYNC`)".

        Design: Corner/calculations/sync_line_flat_share_ignores_tiers
        """
        world = setup_live_single_release(
            label_name="Label C2", artist_name="Artist C2", track_isrc="USRC20000021",
            advance_cents=0,
            memo_overrides={"base_royalty_rate_bps": 1_800, "recoupment_scope": "MASTER_ONLY"},
        )
        # SYNC line with huge units; deduction is 0 -> net = gross = 200000; royalty = round(200000*0.5)=100000.
        add_revenue_report(world["label"]["id"], world["distributor"]["id"],
                           world["release"]["id"], period="2026-Q3", channel="SYNC",
                           units=9_999_999, gross_revenue_cents=200_000)
        run = open_close_calculate_run(world["label"]["id"], "2026-Q3")
        stmt = get_run_statement(run["id"], world["contract"]["id"])
        assert stmt["royalty_earned_cents"] == 100_000


class TestWaterfallPriority:
    def test_recording_drains_before_advance(self):
        """PRD §2.7: "When royalties are applied, buckets are drained in a pinned
        priority order — recording first, then advance, then tour support, then
        promo".
        PRD §3.8: "the buckets are walked in the pinned priority order —
        `recording_balance_cents`, then `advance_balance_cents`, then
        `tour_support_balance_cents`, then `promo_balance_cents`".

        Design: Corner/calculations/waterfall_priority_recording_before_advance
        """
        world = setup_live_single_release(
            label_name="Label C3", artist_name="Artist C3", track_isrc="USRC20000022",
            advance_cents=100_000,
            memo_overrides={"base_royalty_rate_bps": 2_000, "recoupment_scope": "MASTER_ONLY"},
        )
        # Add a milestone 50000 PAID so recording bucket has 50000 before the run.
        from test_helpers import add_milestone, submit_and_approve_milestone, pay_milestone
        m = add_milestone(world["project"]["id"], name="M1", sequence=1,
                          due_date="2026-08-15", payment_cents=50_000)
        submit_and_approve_milestone(m["id"])
        pay_milestone(m["id"])
        add_revenue_report(world["label"]["id"], world["distributor"]["id"],
                           world["release"]["id"], period="2026-Q3",
                           channel="STREAMING", units=10_000,
                           gross_revenue_cents=1_000_000)
        run = open_close_calculate_run(world["label"]["id"], "2026-Q3")
        finalize_run(run["id"])
        account = get_recoupment_account(world["contract"]["id"])
        # earned 140000; distributable min(140000, 50000+100000)=140000.
        # recording drains first 50000 -> 0; advance takes remaining 90000 -> 10000.
        assert account["recording_balance_cents"] == 0
        assert account["advance_balance_cents"] == 10_000
        stmt = get_run_statement(run["id"], world["contract"]["id"])
        assert stmt["recoupment_applied_cents"] == 140_000
        assert stmt["net_payable_cents"] == 0
        # total_unrecouped = 10000 > 0 -> still RECOUPING.
        assert account["total_unrecouped_cents"] == 10_000
        assert account["payout_status"] == "RECOUPING"


class TestPromoSpendVariant:
    def test_recoupable_flag_on_debits_bucket(self):
        """PRD §3.6: "An accepted spend adds the amount to `spend_cents`, and when
        the release's contract has `promo_costs_recoupable` set, the same amount is
        added to the recoupment account's `promo_balance_cents` with
        `total_unrecouped_cents` recomputed".

        Design: Corner/calculations/promo_spend_debits_bucket_when_recoupable
        """
        label = create_label("Label C6")
        artist = create_artist(label["id"], "Artist C6")
        memo, contract = sign_artist_via_memo(
            artist["id"], advance_cents=0, recoupment_scope="CROSS_COLLATERALIZED",
            promo_costs_recoupable=True)
        project = create_and_start_project(contract["id"], title="P-C6")
        track = add_track(project["id"], isrc="USRC20000023", advance_to="CLEARED")
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2026-09-01")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        camp = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        get_success_data(api_client.activate_promo_campaign(camp["id"], MKT))
        spent = get_success_data(api_client.spend_promo_campaign(
            camp["id"], {"amount_cents": 20_000}, MKT))
        assert spent["spend_cents"] == 20_000
        account = get_recoupment_account(contract["id"])
        assert account["promo_balance_cents"] == 20_000

    def test_recoupable_flag_off_skips_bucket(self):
        """PRD §3.6: "when the flag is not set, promo spend is a pure marketing cost
        and never touches the ledger."

        Design: Corner/calculations/promo_spend_skips_bucket_when_not_recoupable
        """
        label = create_label("Label C7")
        artist = create_artist(label["id"], "Artist C7")
        memo, contract = sign_artist_via_memo(
            artist["id"], advance_cents=0, recoupment_scope="MASTER_ONLY",
            promo_costs_recoupable=False)
        project = create_and_start_project(contract["id"], title="P-C7")
        track = add_track(project["id"], isrc="USRC20000024", advance_to="CLEARED")
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2026-09-01")
        assemble_and_lock_release(release["id"])
        schedule_release(release["id"])
        camp = get_success_data(api_client.create_promo_campaign(
            release["id"], create_promo_campaign_payload(
                channel="PLAYLIST", start_date="2026-08-05", end_date="2026-08-10",
                spend_cap_cents=50_000), MKT))
        get_success_data(api_client.activate_promo_campaign(camp["id"], MKT))
        spent = get_success_data(api_client.spend_promo_campaign(
            camp["id"], {"amount_cents": 20_000}, MKT))
        assert spent["spend_cents"] == 20_000
        account = get_recoupment_account(contract["id"])
        assert account["promo_balance_cents"] == 0


class TestRunPeriodConflict:
    def test_duplicate_period_rejected(self):
        """PRD §3.8: "the period must be unique per label, otherwise
        `ERR_RUN_PERIOD_CONFLICT`".

        Design: Corner/validations/run_period_conflict_rejected
        """
        label = create_label("Label Vb26")
        get_success_data(api_client.create_royalty_run(
            create_royalty_run_payload(label["id"], period="2026-Q3"), FIN))
        r = api_client.create_royalty_run(
            create_royalty_run_payload(label["id"], period="2026-Q3"), FIN)
        validate_error(r, ApiErrorId.ERR_RUN_PERIOD_CONFLICT)


class TestNegativePayable:
    def test_negative_net_cannot_be_paid(self):
        """PRD §3.8: "Paying moves the statement to `PAID`, terminal. ... requires
        `net_payable_cents` to be zero or positive — a negative payable is rejected
        with `ERR_NEGATIVE_PAYABLE`."

        Design: Corner/validations/negative_payable_rejected
        """
        world, run, stmt = _setup_provisional_statement("Label Vb14", "Artist Vb14",
                                                        "USRC20000042")
        # Adjust -50000 while PROVISIONAL: adjustment enters after reserve.
        get_success_data(api_client.adjust_royalty_statement(
            stmt["id"], {"expected_royalty_statement_version": stmt["version"],
                         "adjustment_delta_cents": -50_000}, FIN))
        finalize_run(run["id"])
        final_stmt = get_success_data(api_client.get_royalty_statement(stmt["id"], FIN))
        # Final variant: 140000 - 100000 + (-50000) = -10000.
        assert final_stmt["net_payable_cents"] == -10_000
        r = api_client.pay_royalty_statement(stmt["id"], FIN)
        validate_error(r, ApiErrorId.ERR_NEGATIVE_PAYABLE)
        after = get_success_data(api_client.get_royalty_statement(stmt["id"], FIN))
        assert after["status"] == "FINAL"


class TestStatementPaidTerminalLockdown:
    def test_dispute_and_pay_on_paid_rejected(self):
        """PRD §3.8: "Paying moves the statement to `PAID`, terminal."
        PRD §2.9: "Seventh, the attempted state transition must be declared from the
        resource's current status — attempts from terminal states included
        (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/statement_paid_terminal_lockdown
        """
        world, run, stmt = _setup_provisional_statement("Label S5", "Artist S5",
                                                        "USRC20000012")
        finalize_run(run["id"])
        paid = get_success_data(api_client.pay_royalty_statement(stmt["id"], FIN))
        assert paid["status"] == "PAID"

        r1 = api_client.dispute_royalty_statement(
            stmt["id"], {"dispute_note": "too late"},
            make_artist_portal_headers(world["artist"]["id"]))
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE)
        r2 = api_client.pay_royalty_statement(stmt["id"], FIN)
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api_client.get_royalty_statement(stmt["id"], FIN))
        assert after["status"] == "PAID"


class TestReleaseNotLiveRevenueReport:
    def test_planned_release_rejects_report(self):
        """PRD §3.8: "the release's `distribution_status` must be `DELIVERED`,
        `LIVE`, or `TAKEN_DOWN`, otherwise `ERR_RELEASE_NOT_LIVE`."

        Design: Corner/validations/release_not_live_report_rejected
        """
        label = create_label("Label Vb15")
        artist = create_artist(label["id"], "Artist Vb15")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=0)
        project = create_and_start_project(contract["id"], title="P-Vb15")
        track = add_track(project["id"], isrc="USRC20000043", advance_to="CLEARED")
        release = create_release(contract["id"], project["id"], [track["id"]],
                                 release_date="2026-09-01")
        distributor = create_distributor(label["id"], name="DSP-Vb15")
        # Release is PLANNED (never assembled/scheduled).
        r = api_client.create_revenue_report({
            "label_id": label["id"], "distributor_id": distributor["id"],
            "release_id": release["id"], "period": "2026-Q3", "channel": "STREAMING",
            "units": 10, "gross_revenue_cents": 1_000,
        }, FIN)
        validate_error(r, ApiErrorId.ERR_RELEASE_NOT_LIVE)


class TestDuplicateRevenueReport:
    def test_same_tuple_rejected_other_channel_accepted(self):
        """PRD §3.8: "the report must be unique per label, distributor, release,
        period, and channel — a duplicate is rejected with
        `ERR_DUPLICATE_REVENUE_REPORT`".

        Design: Corner/validations/duplicate_revenue_report_rejected
        """
        world = setup_live_single_release(
            label_name="Label Vb25", artist_name="Artist Vb25",
            track_isrc="USRC20000052")
        add_revenue_report(world["label"]["id"], world["distributor"]["id"],
                           world["release"]["id"], period="2026-Q3",
                           channel="STREAMING", units=10, gross_revenue_cents=1_000)
        r = api_client.create_revenue_report({
            "label_id": world["label"]["id"],
            "distributor_id": world["distributor"]["id"],
            "release_id": world["release"]["id"],
            "period": "2026-Q3", "channel": "STREAMING",
            "units": 5, "gross_revenue_cents": 500,
        }, FIN)
        validate_error(r, ApiErrorId.ERR_DUPLICATE_REVENUE_REPORT)
        # Different channel: accepted.
        ok = add_revenue_report(world["label"]["id"], world["distributor"]["id"],
                                world["release"]["id"], period="2026-Q3",
                                channel="DOWNLOAD", units=5, gross_revenue_cents=500)
        assert ok["channel"] == "DOWNLOAD"


class TestArtistPortalOwnershipOnStatement:
    def test_other_artist_rejected_owning_artist_reads(self):
        """PRD §2.1: "When `X-User-Role` is `ArtistPortal`, `X-User-ID` is the `id`
        of the acting Artist; ownership checks on any resource that belongs to an
        artist — a deal memo, a contract, a recoupment account, a royalty
        statement, or a tour support reached through its contract — compare the
        resource's owning-artist chain to `X-User-ID`, and a mismatch is rejected
        with `ERR_ARTIST_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/artist_portal_cannot_read_other_artist_statement
        """
        world, run, stmt = _setup_provisional_statement("Label R4", "Artist A",
                                                        "USRC20000071")
        finalize_run(run["id"])
        # A second artist on the same label.
        artist_b = create_artist(world["label"]["id"], "Artist B", genre="ROCK",
                                 birth_date="1990-01-01")
        r = api_client.get_royalty_statement(
            stmt["id"], make_artist_portal_headers(artist_b["id"]))
        validate_error(r, ApiErrorId.ERR_ARTIST_OWNERSHIP_MISMATCH)
        ok = get_success_data(api_client.get_royalty_statement(
            stmt["id"], make_artist_portal_headers(world["artist"]["id"])))
        assert ok["net_payable_cents"] == 40_000


class TestOccStatementAdjustStaleVersion:
    def test_stale_adjust_rejected(self):
        """PRD §2.8: "Adjusting a royalty statement requires
        `expected_royalty_statement_version` to match the statement's current
        `version`; ... a mismatch is `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_statement_adjust_stale_version
        """
        world, run, stmt = _setup_provisional_statement("Label L3", "Artist L3",
                                                        "USRC20000081")
        v = stmt["version"]
        a1 = get_success_data(api_client.adjust_royalty_statement(
            stmt["id"], {"expected_royalty_statement_version": v,
                         "adjustment_delta_cents": 100}, FIN))
        assert a1["adjustment_cents"] == 100
        # Stale: same pre-adjust version again.
        r = api_client.adjust_royalty_statement(
            stmt["id"], {"expected_royalty_statement_version": v,
                         "adjustment_delta_cents": 200}, FIN)
        validate_error(r, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api_client.get_royalty_statement(stmt["id"], FIN))
        assert after["adjustment_cents"] == 100
