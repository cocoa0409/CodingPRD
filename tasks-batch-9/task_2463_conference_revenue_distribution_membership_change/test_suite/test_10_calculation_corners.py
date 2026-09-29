"""Calculation corners: reimbursement caps and bands, window-filtered valuations, loss-making
settlements, the posture-driven sweep rate and the travel-partner penalty."""

from test_helpers import (
    assert_compliance_breakdown,
    assert_fields_equal,
    assert_posture,
    assert_reimbursement,
    assert_valuation,
    award_championship_event,
    create_revenue_pool,
    create_schedule_game,
    host_championship_event,
    make_commissioner_headers,
    make_finance_officer_headers,
    make_member_update_payload,
    make_schedule_coordinator_headers,
    read_conference,
    read_member,
    read_revenue_pool,
    read_run_lines,
    setup_approved_bowl_appearance,
    setup_charter_roster,
    setup_computed_fy2026_final_run,
    setup_operating_conference_with_reserve,
    settle_championship_event,
    submit_bowl_appearance,
    begin_bowl_review,
    approve_bowl_appearance,
    validate_success,
)


def _read_compliance(api, member_id):
    return validate_success(
        api.get_schedule_compliance(member_id, headers=make_schedule_coordinator_headers())
    )


def _valuation(api, member_id):
    return validate_success(
        api.get_postseason_unit_valuation(member_id, headers=make_finance_officer_headers())
    )


def _read_event(api, event_id):
    return validate_success(
        api.get_championship_event(event_id, headers=make_schedule_coordinator_headers())
    )


def test_a_payout_of_exactly_ten_million_selects_the_lower_band(api):
    """PRD §3.6: "First, `allowable_expense_cents` is the smaller of the claimed
    `submitted_expense_cents` and the allowable-expense cap of 8,000,000 cents (80,000
    dollars)."
    PRD §3.6: "Third, the reimbursement band is selected by the payout alone — `event_tier` is
    descriptive and plays no part in the arithmetic: a `payout_cents` of at least 10,000,000
    cents (100,000 dollars) selects the high-payout band of 6000 basis points, and anything
    below that selects the low-payout band of 8500 basis points."
    PRD §3.6: "The `reimbursement_ceiling_cents` is `payout_cents` multiplied by the selected
    band and divided by 10000, rounded up to the next whole cent."
    PRD §3.6: "Then `reimbursed_cents` is the smaller of the sum of `allowable_expense_cents`
    and `travel_allowance_cents` and that ceiling, and `residual_to_pool_cents` is
    `payout_cents` minus `reimbursed_cents`."
    PRD §3.6: "Because the band steps down as the payout rises past the threshold, a larger
    payout can actually lower the reimbursement — a deliberate property of the policy, not an
    artefact."

    Design: Corner/calculations/corner_bowl_reimbursement_band_boundary_at_ten_million
    """
    ctx = setup_charter_roster(api)
    ids = ctx["member_ids"]

    high = setup_approved_bowl_appearance(
        api,
        ids["north"],
        event_name="Boundary Bowl",
        event_tier="BOWL",
        payout_cents=10_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=0,
        units_claimed=1,
    )
    low = setup_approved_bowl_appearance(
        api,
        ids["south"],
        event_name="Boundary Bowl",
        event_tier="TOURNAMENT",
        payout_cents=9_999_999,
        submitted_expense_cents=9_500_000,
        travel_miles=0,
        units_claimed=1,
    )

    # The threshold is inclusive, so the larger payout is reimbursed the smaller amount.
    assert_reimbursement(
        high,
        allowable_expense_cents=8_000_000,
        travel_allowance_cents=0,
        reimbursement_ceiling_cents=6_000_000,
        reimbursed_cents=6_000_000,
        residual_to_pool_cents=4_000_000,
    )
    assert_reimbursement(
        low,
        allowable_expense_cents=8_000_000,
        travel_allowance_cents=0,
        reimbursement_ceiling_cents=8_500_000,
        reimbursed_cents=8_000_000,
        residual_to_pool_cents=1_999_999,
    )
    assert high["status"] == "APPROVED" and low["status"] == "APPROVED"
    assert_fields_equal(
        read_conference(api),
        escrow_balance_cents=5_999_999,
        validated_postseason_unit_count=2,
    )


def test_the_travel_allowance_is_clamped_and_then_clamped_again_by_the_ceiling(api):
    """PRD §3.6: "Second, `travel_allowance_cents` is the smaller of `travel_miles` multiplied
    by the travel rate of 95 cents per mile and the travel-allowance cap of 2,500,000 cents
    (25,000 dollars)."
    PRD §3.6: "First, `allowable_expense_cents` is the smaller of the claimed
    `submitted_expense_cents` and the allowable-expense cap of 8,000,000 cents (80,000
    dollars)."
    PRD §3.6: "The `reimbursement_ceiling_cents` is `payout_cents` multiplied by the selected
    band and divided by 10000, rounded up to the next whole cent."
    PRD §3.6: "Then `reimbursed_cents` is the smaller of the sum of `allowable_expense_cents`
    and `travel_allowance_cents` and that ceiling, and `residual_to_pool_cents` is
    `payout_cents` minus `reimbursed_cents`."
    PRD §3.6: "Approving therefore moves the appearance `UNDER_REVIEW` → `APPROVED`, writes
    `allowable_expense_cents`, `travel_allowance_cents`, `reimbursement_ceiling_cents`,
    `reimbursed_cents` and `residual_to_pool_cents`, adds `residual_to_pool_cents` to the
    conference's `escrow_balance_cents`, transitions every postseason unit of the appearance
    `PROVISIONAL` → `VALIDATED`, advances the conference's `validated_postseason_unit_count` by
    `units_claimed`, and increments the conference's `version` by 1."

    Design: Corner/calculations/corner_travel_allowance_capped_at_two_point_five_million
    """
    ctx = setup_charter_roster(api)
    ids = ctx["member_ids"]

    far = setup_approved_bowl_appearance(
        api,
        ids["north"],
        event_name="Antipodean Invitational",
        event_tier="TOURNAMENT",
        payout_cents=12_000_000,
        submitted_expense_cents=9_500_000,
        travel_miles=30_000,
        units_claimed=2,
    )
    near = setup_approved_bowl_appearance(
        api,
        ids["south"],
        event_name="Valley Bowl",
        event_tier="BOWL",
        payout_cents=6_000_000,
        submitted_expense_cents=4_200_000,
        travel_miles=900,
        units_claimed=1,
    )

    # 30,000 miles at 95 cents raw is 2,850,000, clamped to the cap and then dropped
    # again by the independent ceiling: two caps in series.
    assert_reimbursement(
        far,
        allowable_expense_cents=8_000_000,
        travel_allowance_cents=2_500_000,
        reimbursement_ceiling_cents=7_200_000,
        reimbursed_cents=7_200_000,
        residual_to_pool_cents=4_800_000,
    )
    assert_reimbursement(
        near,
        allowable_expense_cents=4_200_000,
        travel_allowance_cents=85_500,
        reimbursement_ceiling_cents=5_100_000,
        reimbursed_cents=4_285_500,
        residual_to_pool_cents=1_714_500,
    )
    assert_fields_equal(
        read_conference(api),
        escrow_balance_cents=6_514_500,
        validated_postseason_unit_count=3,
    )


def test_the_valuation_counts_only_validated_units_inside_the_rolling_window(api):
    """PRD §3.6: "For a member in `ADMITTED_PHASING`, `FULL_SHARE` or `DEPARTED` the
    `ROLLING_SIX_YEAR` variant applies: the window covers the six fiscal years ending at the
    conference's `current_fiscal_year`, so `window_start_fiscal_year` is `current_fiscal_year`
    minus 5 and `window_end_fiscal_year` is `current_fiscal_year`."
    PRD §3.6: "Within the window, `validated_unit_count` is the number of that member's
    postseason units in status `VALIDATED` whose `fiscal_year` falls inside the window —
    provisional and voided units never count — and `valuation_cents` is that count multiplied
    by the conference's `unit_value_cents`, an exact multiplication with no rounding."
    PRD §3.6: "Approving therefore moves the appearance `UNDER_REVIEW` → `APPROVED`, writes
    `allowable_expense_cents`, `travel_allowance_cents`, `reimbursement_ceiling_cents`,
    `reimbursed_cents` and `residual_to_pool_cents`, adds `residual_to_pool_cents` to the
    conference's `escrow_balance_cents`, transitions every postseason unit of the appearance
    `PROVISIONAL` → `VALIDATED`, advances the conference's `validated_postseason_unit_count` by
    `units_claimed`, and increments the conference's `version` by 1."
    PRD §3.6: "The valuation response names the `member_id`, the `variant` applied, both window
    bounds, the count and the valuation."

    Design: Corner/calculations/corner_postseason_unit_valuation_input_set_filters_by_status_and_window
    """
    ctx = setup_charter_roster(api)
    member_id = ctx["member_ids"]["north"]
    current = submit_bowl_appearance(api, member_id, units_claimed=2)
    legacy = submit_bowl_appearance(
        api,
        member_id,
        fiscal_year=2021,
        event_name="Legacy Classic",
        event_tier="BOWL",
        payout_cents=5_000_000,
        submitted_expense_cents=1_000_000,
        travel_miles=0,
        units_claimed=3,
    )
    begin_bowl_review(api, current["id"])
    begin_bowl_review(api, legacy["id"])

    before = _valuation(api, member_id)
    approve_bowl_appearance(api, current["id"])
    approve_bowl_appearance(api, legacy["id"])
    after = _valuation(api, member_id)

    # Provisional units contribute nothing at all.
    assert_valuation(
        before,
        variant="ROLLING_SIX_YEAR",
        window_start_fiscal_year=2022,
        window_end_fiscal_year=2027,
        validated_unit_count=0,
        valuation_cents=0,
    )
    # The FY2021 units are VALIDATED yet fall outside the window.
    assert_valuation(
        after,
        variant="ROLLING_SIX_YEAR",
        window_start_fiscal_year=2022,
        window_end_fiscal_year=2027,
        validated_unit_count=2,
        valuation_cents=68_000_000,
    )
    assert before["member_id"] == member_id
    assert after["member_id"] == member_id
    # The conference counter is unfiltered where the member valuation is window-filtered.
    assert read_conference(api)["validated_postseason_unit_count"] == 5


def test_a_loss_making_championship_pays_no_host_share_and_reduces_the_pool(api):
    """PRD §3.5: "From them the system derives `net_event_revenue_cents` as ticket receipts plus
    sponsorship receipts minus event expense."
    PRD §3.5: "The `host_share_cents` is that net figure multiplied by the host share of 2000
    basis points and divided by 10000, rounded up to the next whole cent — but only when the
    net figure is strictly positive; when the net is zero or negative the host share is 0."
    PRD §3.5: "The `participant_pool_cents` is then `net_event_revenue_cents` minus
    `host_share_cents`, which means that a loss-making event passes its entire negative net
    through to the participant pool while the host is shielded from it."
    PRD §3.5: "The `participant_pool_cents` is added to the linked revenue pool's
    `gross_revenue_cents`."
    PRD §3.5: "A successful award creates the event in `SCHEDULED` and snapshots the host's
    score at that moment as `host_compliance_score_at_award`."

    Design: Corner/calculations/corner_championship_settlement_loss_and_zero_cases
    """
    ctx = setup_charter_roster(api)
    pool = create_revenue_pool(api, ctx["conference_id"])
    event = award_championship_event(
        api,
        ctx["conference_id"],
        ctx["venue_east"]["id"],
        ctx["member_ids"]["south"],
        pool["id"],
        "2027-03-01T00:00:00Z",
        "2027-03-05T00:00:00Z",
        sport="WRESTLING",
    )
    host_championship_event(api, event["id"])

    settled = settle_championship_event(
        api,
        event["id"],
        ticket_revenue_cents=9_000_000,
        sponsorship_revenue_cents=1_000_000,
        event_expense_cents=15_000_000,
    )

    # A negative net does not produce a negative host share.
    assert_fields_equal(
        settled,
        status="SETTLED",
        net_event_revenue_cents=-5_000_000,
        host_share_cents=0,
        participant_pool_cents=-5_000_000,
        host_compliance_score_at_award=100,
    )
    assert_fields_equal(
        read_revenue_pool(api, pool["id"]),
        gross_revenue_cents=495_000_000,
        status="DRAFT",
        version=pool["version"] + 1,
    )


def test_a_break_even_championship_writes_three_zeros_and_moves_the_pool_nowhere(api):
    """PRD §3.5: "The `host_share_cents` is that net figure multiplied by the host share of 2000
    basis points and divided by 10000, rounded up to the next whole cent — but only when the net
    figure is strictly positive; when the net is zero or negative the host share is 0."
    PRD §3.5: "The event moves `HOSTED` → `SETTLED` and its `version` advances."
    PRD §3.5: "Because that gross figure has now been restated, a pool sitting in `OPEN` or
    `BOOKS_CLOSED` is driven back to `DRAFT`, and if it was `BOOKS_CLOSED` its
    `audited_expense_cents` is cleared to null — the audited figure was an assertion about a
    gross that no longer holds."
    PRD §3.5: "The pool's `version` advances by 1, which is what makes any client holding an
    older `expected_pool_version` fail its next attempt to compute a run."

    Design: Corner/calculations/corner_championship_settlement_loss_and_zero_cases
    """
    ctx = setup_charter_roster(api)
    pool = create_revenue_pool(api, ctx["conference_id"])
    events = []
    for sport, window in (
        ("WRESTLING", ("2027-03-01T00:00:00Z", "2027-03-05T00:00:00Z")),
        ("GYMNASTICS", ("2027-03-10T00:00:00Z", "2027-03-14T00:00:00Z")),
    ):
        event = award_championship_event(
            api,
            ctx["conference_id"],
            ctx["venue_east"]["id"],
            ctx["member_ids"]["south"],
            pool["id"],
            window[0],
            window[1],
            sport=sport,
        )
        events.append(host_championship_event(api, event["id"]))

    settle_championship_event(
        api,
        events[0]["id"],
        ticket_revenue_cents=9_000_000,
        sponsorship_revenue_cents=1_000_000,
        event_expense_cents=15_000_000,
    )
    zero = settle_championship_event(
        api,
        events[1]["id"],
        ticket_revenue_cents=15_000_000,
        sponsorship_revenue_cents=0,
        event_expense_cents=15_000_000,
    )

    # "No net at all" is distinct from "no positive net": both pay the host nothing,
    # but only the loss moves the pool's gross.
    assert_fields_equal(
        zero,
        status="SETTLED",
        net_event_revenue_cents=0,
        host_share_cents=0,
        participant_pool_cents=0,
        host_compliance_score_at_award=100,
    )
    assert_fields_equal(
        read_revenue_pool(api, pool["id"]),
        gross_revenue_cents=495_000_000,
        status="DRAFT",
        version=pool["version"] + 2,
    )
    assert _read_event(api, events[0]["id"])["participant_pool_cents"] == -5_000_000


def test_a_restricted_posture_triples_the_sweep_rate_before_the_shortfall_clamp(api):
    """PRD §2.10: "The funded ratio, `funded_ratio_bps`, is 10000 when the target is 0;
    otherwise it is `reserve_balance_cents` multiplied by 10000 and divided by
    `reserve_target_cents`, rounded down to a whole basis point."
    PRD §2.10: "Both boundaries fall on the better-funded side: a reserve funded to exactly 6000
    basis points of target is `OPEN`, and one funded to exactly 2500 basis points is
    `RESERVE_RESTRICTED`, not `FROZEN`."
    PRD §3.7: "The sweep rate is 1500 basis points while the conference's `reserve_posture` is
    `RESERVE_RESTRICTED` and 500 basis points otherwise."
    PRD §3.7: "The reserve shortfall is `reserve_target_cents` minus `reserve_balance_cents`,
    treated as 0 when the balance already meets or exceeds the target."
    PRD §3.7: "The `reserve_draw_cents` is the smaller of `net_pool_cents` multiplied by the
    sweep rate divided by 10000 and rounded up to the next whole cent, and that shortfall — so a
    fully funded reserve draws nothing at all no matter what the rate says."
    PRD §3.7: "The `distributable_cents` is `net_pool_cents` minus `reserve_draw_cents`."
    PRD §3.7: "The draw is computed here but does not touch `reserve_balance_cents` until the
    run is posted."

    Design: Corner/calculations/corner_reserve_sweep_rate_switches_with_restricted_posture
    """
    ctx = setup_operating_conference_with_reserve(api, reserve_cents=4_500_000)
    conference = read_conference(api)
    assert conference["reserve_target_cents"] == 18_000_000
    # Exactly on the frozen boundary, which falls on the better-funded side.
    assert_posture(conference, "RESERVE_RESTRICTED", 2500)

    run = setup_computed_fy2026_final_run(api, ctx)

    assert_fields_equal(
        run,
        net_pool_cents=596_000_000,
        reserve_draw_cents=13_500_000,
        distributable_cents=582_500_000,
        total_weight_bps=40000,
    )
    # The uncapped 1500 basis point sweep would have drawn 89,400,000 cents.
    assert run["reserve_draw_cents"] == 18_000_000 - 4_500_000
    assert read_conference(api)["reserve_balance_cents"] == 4_500_000


def test_the_restricted_sweep_leaves_every_line_short_by_the_extra_draw(api):
    """PRD §3.7: "Under `EQUAL_SHARE` the raw weight is the base weight of 10000 basis points
    for everyone."
    PRD §3.7: "Each line's `gross_share_cents` is first `distributable_cents` multiplied by that
    line's `weight_bps` and divided by `total_weight_bps`, rounded down."
    PRD §3.7: "The leftover, `distributable_cents` minus the sum of those floored shares, is
    then handed out one cent at a time."
    PRD §3.7: "The `withheld_cents` is `gross_share_cents` multiplied by the provisional
    withholding of 1000 basis points and divided by 10000, rounded up, on a `PROVISIONAL` run,
    and exactly 0 on a `FINAL_AUDITED` run."
    PRD §3.7: "The `governance_fee_cents` is the flat governance and compliance service fee of
    1,250,000 cents (12,500 dollars), charged identically on every line regardless of its size,
    which means a small line can be driven negative by it."

    Design: Corner/calculations/corner_reserve_sweep_rate_switches_with_restricted_posture
    """
    ctx = setup_operating_conference_with_reserve(api, reserve_cents=4_500_000)
    run = setup_computed_fy2026_final_run(api, ctx)

    lines = read_run_lines(api, run["id"])

    assert len(lines) == 4
    for line in lines:
        # 145,625,000 rather than the 147,500,000 an OPEN-posture sweep would leave.
        assert_fields_equal(
            line,
            weight_bps=10000,
            gross_share_cents=145_625_000,
            withheld_cents=0,
            governance_fee_cents=1_250_000,
            net_payable_cents=144_375_000,
            remainder_cent_awarded=0,
        )


def test_the_travel_partner_gap_is_counted_per_unpaired_away_game(api):
    """PRD §3.4: "The second is 8 points for each **travel-partner gap**."
    PRD §3.4: "If the member's `travel_partner_member_id` is null the gap count is 0 outright;
    otherwise it is the number of the member's own away games in the current fiscal year
    (status `SCHEDULED` or `PLAYED`) for which no away game of its travel partner exists at the
    same `venue_id` in the same fiscal year, in status `SCHEDULED` or `PLAYED`, whose
    `game_date` is within three days of the member's game in either direction — a separation of
    exactly three days still counts as paired."
    PRD §3.4: "The third is 5 points for each unit of **home-schedule imbalance**, measured as
    the member's `home_game_count` minus its `away_game_count` minus 1, treated as 0 when that
    difference is negative or zero; both counts cover the current fiscal year in status
    `SCHEDULED` or `PLAYED`."
    PRD §3.1: "Only the supplied fields are rewritten; omitted fields are left exactly as they
    were, and the member's `version` advances by 1."

    Design: Corner/calculations/corner_travel_partner_gap_penalty_applies_per_unpaired_away_game
    """
    ctx = setup_charter_roster(api)
    ids = ctx["member_ids"]
    east = read_member(api, ids["east"])
    paired = validate_success(
        api.update_member(
            ids["east"],
            make_member_update_payload(
                east["version"], travel_partner_member_id=ids["west"]
            ),
            headers=make_commissioner_headers(),
        )
    )
    create_schedule_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["east"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
    )

    unpaired_read = _read_compliance(api, ids["east"])
    create_schedule_game(
        api,
        ctx["conference_id"],
        ids["south"],
        ids["west"],
        ctx["venue_north"]["id"],
        "2026-09-07T19:00:00Z",
        media_designated=False,
    )

    assert_fields_equal(
        paired, version=east["version"] + 1, travel_partner_member_id=ids["west"]
    )
    assert_compliance_breakdown(
        unpaired_read,
        unmet_rivalry_count=0,
        travel_partner_gap_count=1,
        home_game_count=0,
        away_game_count=1,
        schedule_compliance_score=92,
    )
    # West's away game shares the venue and falls two days later, so the gap closes.
    assert_compliance_breakdown(
        _read_compliance(api, ids["east"]),
        unmet_rivalry_count=0,
        travel_partner_gap_count=0,
        home_game_count=0,
        away_game_count=1,
        schedule_compliance_score=100,
    )
    # West names no partner of its own, so the gap count short-circuits to 0.
    assert_compliance_breakdown(
        _read_compliance(api, ids["west"]),
        unmet_rivalry_count=0,
        travel_partner_gap_count=0,
        home_game_count=0,
        away_game_count=1,
        schedule_compliance_score=100,
    )
