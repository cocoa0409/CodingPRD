"""Rejection paths across the draft order, the pick market and the money rules.

The cases here cover the lottery draw that cannot fill its slots, club-code
uniqueness inside a cycle, selections blocked by an unreviewed prospect or by a
missing out-of-order authorization, the timeout inventory, the trade guards for
self-dealing, pick ownership, suspended negotiating capital and chart balance,
the cycle-cohesion rule on a compensatory claim, and the undrafted signing pool.
Every case builds its own state through published endpoints.
"""

from test_helpers import (
    ADMIN,
    DRAFT_START_AT,
    ERR_CLUB_CODE_DUPLICATE,
    ERR_CROSS_CYCLE_REFERENCE,
    ERR_LOTTERY_SEQUENCE_INVALID,
    ERR_NO_TIMEOUTS_REMAINING,
    ERR_OUT_OF_ORDER_NOT_AUTHORIZED,
    ERR_PICK_NOT_OWNED_BY_CLUB,
    ERR_PROSPECT_NOT_SELECTABLE,
    ERR_SELF_TRADE_FORBIDDEN,
    ERR_TRADE_AUTHORIZATION_SUSPENDED,
    ERR_TRADE_VALUE_IMBALANCED,
    ERR_UDFA_POOL_EXHAUSTED,
    advance_clock,
    assert_cents_equal,
    assert_chart_points,
    assert_imbalance_ratio,
    build_combine_week,
    build_cycle_with_clubs,
    build_declaration_open,
    build_draft_live_on_clock,
    build_order_final,
    build_order_pending,
    build_udfa_window,
    clock_action_payload,
    club_payload,
    compensatory_claim_payload,
    create_cycle,
    finalize_order,
    get_success_data,
    list_picks,
    lottery_payload,
    make_club_gm_headers,
    move_phase,
    pick_index,
    pick_trade_payload,
    player_contract_payload,
    propose_trade,
    read_club,
    read_cycle,
    read_pick,
    read_prospect,
    read_trade,
    register_club,
    run_lottery,
    selection_payload,
    set_clock,
    validate_error,
    validate_success,
)


def _draft_live_with_an_unreviewed_prospect(api):
    """DRAFT_LIVE with overall one on the clock and the prospect never reviewed.

    The declared prospect carries the cycle from DECLARATION_OPEN into
    COMBINE_WEEK, and the committee never rules on her, so she is still
    UNREVIEWED once the clock starts.
    """
    state = build_combine_week(api)
    cycle_id = state["cycle"]["id"]
    state["cycle"] = move_phase(api, cycle_id, "ORDER_PENDING")
    state["cycle"] = run_lottery(api, cycle_id)
    state["finalize"] = finalize_order(api, cycle_id)
    state["picks"] = list_picks(api, cycle_id)
    state["pick"] = pick_index(state["picks"])
    set_clock(api, DRAFT_START_AT)
    state["cycle"] = move_phase(api, cycle_id, "DRAFT_LIVE")
    state["advance"] = advance_clock(api, cycle_id)
    state["cycle"] = read_cycle(api, cycle_id)
    return state


class TestDraftOrderConstruction:
    """The lottery draw and club registration inside one cycle."""

    def test_single_value_draw_cannot_fill_both_lottery_slots(self, api):
        """Two non-playoff clubs mean two slots to fill, so a one-value draw is
        refused and no club leaves the call with a draft order index.

        PRD: "Every value in that list must lie between 1 and the total number
        of combinations assigned across the eligible pool, inclusive, and the
        list must name enough distinct clubs to fill every lottery slot; a value
        out of range or a sequence that cannot fill the slots is refused with
        `ERR_LOTTERY_SEQUENCE_INVALID`."

        Design: Corner/errors/lottery_sequence_too_short_to_fill_every_slot_is_rejected
        """
        state = build_order_pending(api)

        response = api.run_lottery(
            state["cycle"]["id"], lottery_payload([200]), ADMIN
        )
        validate_error(response, ERR_LOTTERY_SEQUENCE_INVALID, expected_status=422)

        cycle = read_cycle(api, state["cycle"]["id"])
        assert cycle["lottery_completed"] is False
        assert cycle["status"] == "ORDER_PENDING"
        for code in ("ELM", "HAR"):
            club = read_club(api, state["clubs"][code]["id"])
            assert club["draft_order_index"] == 0

    def test_registering_the_same_club_code_twice_in_one_cycle_is_refused(self, api):
        """The second ELM registration is refused, the cycle still counts one
        club and the original club row is left exactly as it was registered.

        PRD: "Club code uniqueness — `club_code` is unique among the clubs
        sharing a `draft_cycle_id`, else `ERR_CLUB_CODE_DUPLICATE` (409)."

        Design: Corner/errors/duplicate_club_code_in_the_same_cycle_is_rejected
        """
        state = build_cycle_with_clubs(api, club_codes=["ELM"])
        elm = state["clubs"]["ELM"]

        response = api.create_club(
            club_payload(
                state["cycle"]["id"],
                "ELM",
                market_name="Elmwood Reserves",
                prior_season_win_pct=0.625,
                strength_of_schedule=0.450,
                head_to_head_rank=7,
                rookie_pool_total_cents=400000000,
                lottery_combinations=20,
            ),
            ADMIN,
        )
        validate_error(response, ERR_CLUB_CODE_DUPLICATE, expected_status=409)

        cycle = read_cycle(api, state["cycle"]["id"])
        assert cycle["club_count"] == 1
        survivor = read_club(api, elm["id"])
        assert survivor["market_name"] == "Elmwood"
        assert survivor["version"] == 1


class TestSelectionRefusals:
    """Guards that stand between a club and the prospect it wants to take."""

    def test_declared_but_unreviewed_prospect_cannot_be_selected(self, api):
        """A prospect the committee never ruled on is still UNREVIEWED, so the
        selection is refused and the clock keeps running on the same pick.

        PRD: "Selectability — the prospect being selected has `eligibility_status`
        `ELIGIBLE`, a `medical_clearance_status` that is not `FAILED`,
        `declaration_status` `DECLARED`, and `drafted_pick_overall_number` equal
        to 0, else `ERR_PROSPECT_NOT_SELECTABLE` (422)."

        Design: Corner/errors/unreviewed_prospect_cannot_be_selected
        """
        state = _draft_live_with_an_unreviewed_prospect(api)
        elm = state["clubs"]["ELM"]
        on_clock = state["pick"]["r1p1"]

        response = api.create_selection(
            on_clock["id"],
            selection_payload(state["prospect"]["id"]),
            make_club_gm_headers(elm["id"]),
        )
        validate_error(response, ERR_PROSPECT_NOT_SELECTABLE, expected_status=422)

        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["eligibility_status"] == "UNREVIEWED"
        assert prospect["drafted_pick_overall_number"] == 0
        pick = read_pick(api, on_clock["id"])
        assert pick["status"] == "ON_CLOCK"
        assert pick["deadline_at"] == "2027-04-22T18:10:00.000Z"

    def test_acknowledgement_alone_does_not_unlock_a_later_pick(self, api):
        """Without the league's authorization step a PENDING round-two pick may
        not be used while overall one holds the clock, however the club
        acknowledges it.

        PRD: "This requires the cycle to be `DRAFT_LIVE`, the pick's
        `out_of_order_authorized` to be true, another pick to currently hold the
        clock, and the request to carry `out_of_order_ack` true; a `PENDING`
        pick used while another pick holds the clock without both the league
        authorization and the acknowledgement is refused with
        `ERR_OUT_OF_ORDER_NOT_AUTHORIZED`."

        Design: Corner/errors/unauthorized_out_of_order_selection_is_rejected
        """
        state = build_draft_live_on_clock(api)
        elm = state["clubs"]["ELM"]
        later_pick = state["pick"]["r2p1"]

        response = api.create_selection(
            later_pick["id"],
            selection_payload(state["prospect"]["id"], out_of_order_ack=True),
            make_club_gm_headers(elm["id"]),
        )
        validate_error(
            response, ERR_OUT_OF_ORDER_NOT_AUTHORIZED, expected_status=409
        )

        blocked = read_pick(api, later_pick["id"])
        assert blocked["status"] == "PENDING"
        assert blocked["out_of_order_authorized"] is False
        assert read_pick(api, state["pick"]["r1p1"]["id"])["status"] == "ON_CLOCK"
        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["drafted_pick_overall_number"] == 0


class TestSelectionClockTimeouts:
    """Every club carries two selection-clock timeouts for the whole cycle."""

    def test_third_timeout_on_the_same_pick_is_refused(self, api):
        """Two timeouts push the round-one deadline from 18:10 to 18:14 and
        exhaust the club's inventory, so the third is refused and the deadline
        does not move again.

        PRD: "It requires the cycle to be `DRAFT_LIVE`, the current logical
        instant to be strictly before `deadline_at`, and the owning club's
        `timeouts_remaining` to be greater than zero, else
        `ERR_NO_TIMEOUTS_REMAINING`."

        Design: Corner/errors/third_timeout_on_the_same_pick_is_rejected
        """
        state = build_draft_live_on_clock(api)
        elm = state["clubs"]["ELM"]
        elm_headers = make_club_gm_headers(elm["id"])
        on_clock = state["pick"]["r1p1"]
        for _ in range(2):
            get_success_data(
                api.act_on_pick_clock(
                    on_clock["id"], clock_action_payload("TIMEOUT"), elm_headers
                )
            )

        response = api.act_on_pick_clock(
            on_clock["id"], clock_action_payload("TIMEOUT"), elm_headers
        )
        validate_error(response, ERR_NO_TIMEOUTS_REMAINING, expected_status=409)

        pick = read_pick(api, on_clock["id"])
        assert pick["timeouts_used"] == 2
        assert pick["deadline_at"] == "2027-04-22T18:14:00.000Z"
        assert pick["status"] == "ON_CLOCK"
        assert read_club(api, elm["id"])["timeouts_remaining"] == 0


class TestPickTradeRefusals:
    """Party, ownership, capital and balance guards on the pick market."""

    def test_club_cannot_trade_with_itself(self, api):
        """Naming the same club on both sides of the proposal is refused even
        though that club really does own both picks.

        PRD: "The two clubs must differ and the acting club must be a party to
        the trade, else `ERR_SELF_TRADE_FORBIDDEN`."

        Design: Corner/errors/trade_between_a_club_and_itself_is_rejected
        """
        state = build_order_final(api)
        elm = state["clubs"]["ELM"]
        first, third = state["pick"]["r1p1"], state["pick"]["r2p1"]

        response = api.create_pick_trade(
            pick_trade_payload(
                state["cycle"]["id"],
                elm["id"],
                elm["id"],
                [first["id"]],
                [third["id"]],
            ),
            make_club_gm_headers(elm["id"]),
        )
        validate_error(response, ERR_SELF_TRADE_FORBIDDEN, expected_status=422)

        assert read_pick(api, first["id"])["owning_club_id"] == elm["id"]
        assert read_pick(api, third["id"])["owning_club_id"] == elm["id"]
        assert_chart_points(read_club(api, elm["id"])["draft_capital_points"], 1420.0)

    def test_club_cannot_offer_a_pick_owned_by_the_counterparty(self, api):
        """Offering the other club's overall two is refused before any balance
        arithmetic runs, and both ownership ledgers stay put.

        PRD: "Every pick in `offered_pick_ids` must currently be owned by
        `proposing_club_id`, every pick in `requested_pick_ids` must currently be
        owned by `receiving_club_id`, and all of them must be `PENDING`; a pick
        that is `FORFEITED`, `USED`, `PASSED`, `LAPSED` or on the clock may not
        appear on either side, and any violation is refused with
        `ERR_PICK_NOT_OWNED_BY_CLUB`."

        Design: Corner/errors/club_cannot_offer_a_pick_it_does_not_own
        """
        state = build_order_final(api)
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]
        second, fourth = state["pick"]["r1p2"], state["pick"]["r2p2"]

        response = api.create_pick_trade(
            pick_trade_payload(
                state["cycle"]["id"],
                elm["id"],
                har["id"],
                [second["id"]],
                [fourth["id"]],
            ),
            make_club_gm_headers(elm["id"]),
        )
        validate_error(response, ERR_PICK_NOT_OWNED_BY_CLUB, expected_status=422)

        misoffered = read_pick(api, second["id"])
        assert misoffered["owning_club_id"] == har["id"]
        assert misoffered["status"] == "PENDING"
        assert_chart_points(read_club(api, elm["id"])["draft_capital_points"], 1420.0)
        assert_chart_points(read_club(api, har["id"])["draft_capital_points"], 1334.8)

    def test_club_whose_capital_collapsed_after_a_forfeit_cannot_propose(self, api):
        """Forfeiting overall two drops the club's negotiating capital to 394.8,
        below the limited tier floor, so its fresh proposal is refused.

        PRD: "A club at `SUSPENDED` is out of the market: proposing, countering
        or accepting with either party in that tier is refused with
        `ERR_TRADE_AUTHORIZATION_SUSPENDED`."

        Design: Corner/errors/suspended_club_cannot_propose_a_trade
        """
        state = build_order_final(api)
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]
        second = state["pick"]["r1p2"]
        get_success_data(
            api.act_on_pick_clock(
                second["id"], clock_action_payload("FORFEIT"), ADMIN
            )
        )

        response = api.create_pick_trade(
            pick_trade_payload(
                state["cycle"]["id"],
                har["id"],
                elm["id"],
                [state["pick"]["r2p2"]["id"]],
                [state["pick"]["r2p1"]["id"]],
            ),
            make_club_gm_headers(har["id"]),
        )
        validate_error(
            response, ERR_TRADE_AUTHORIZATION_SUSPENDED, expected_status=403
        )

        suspended = read_club(api, har["id"])
        assert_chart_points(suspended["draft_capital_points"], 394.8)
        assert suspended["trade_authorization_tier"] == "SUSPENDED"
        forfeited = read_pick(api, second["id"])
        assert forfeited["status"] == "FORFEITED"
        assert_chart_points(forfeited["chart_value_points"], 0.0)
        cycle = read_cycle(api, state["cycle"]["id"])
        assert_chart_points(cycle["pick_inventory_chart_points"], 1814.8)

    def test_lopsided_package_is_accepted_as_a_proposal(self, api):
        """Proposing is never gated on balance: the deliberately lopsided offer
        is created and published with its chart balance and imbalance ratio.

        PRD: "The `imbalance_ratio` is the absolute value of
        `chart_balance_points` divided by the largest of the incoming total, the
        outgoing total and 1.0, rounded half up to four decimal places; the 1.0
        floor keeps the ratio well defined when both sides are worthless."

        Design: Corner/errors/accepting_an_imbalanced_trade_is_rejected
        """
        state = build_order_final(api)
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]

        response = api.create_pick_trade(
            pick_trade_payload(
                state["cycle"]["id"],
                elm["id"],
                har["id"],
                [state["pick"]["r2p1"]["id"]],
                [state["pick"]["r1p2"]["id"]],
            ),
            make_club_gm_headers(elm["id"]),
        )
        trade = validate_success(response, expected_status=201)
        assert trade["status"] == "PROPOSED"
        assert_chart_points(trade["chart_balance_points"], 520.0)
        assert_imbalance_ratio(trade["imbalance_ratio"], 0.5532)

    def test_accepting_a_lopsided_package_is_refused(self, api):
        """An imbalance ratio of 0.5532 is far past the 0.15 tolerance, so the
        counterparty's acceptance fails and both ownership ledgers stay put.

        PRD: "Acceptance is allowed only when `imbalance_ratio` is at most 0.15,
        inclusive at that boundary; a wider gap is refused with
        `ERR_TRADE_VALUE_IMBALANCED`."

        Design: Corner/errors/accepting_an_imbalanced_trade_is_rejected
        """
        state = build_order_final(api)
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]
        second, third = state["pick"]["r1p2"], state["pick"]["r2p1"]
        trade = propose_trade(
            api, state["cycle"], elm, har, [third], [second]
        )

        response = api.accept_pick_trade(
            trade["id"], None, make_club_gm_headers(har["id"])
        )
        validate_error(response, ERR_TRADE_VALUE_IMBALANCED, expected_status=422)

        after = read_trade(api, trade["id"])
        assert after["status"] == "PROPOSED"
        assert_chart_points(after["chart_balance_points"], 520.0)
        assert_imbalance_ratio(after["imbalance_ratio"], 0.5532)
        assert read_pick(api, second["id"])["owning_club_id"] == har["id"]
        assert read_pick(api, third["id"])["owning_club_id"] == elm["id"]


class TestCycleCohesionOnClaims:
    """A compensatory claim may not bridge two cycles."""

    def test_claim_for_a_club_registered_in_another_cycle_is_refused(self, api):
        """The claiming club belongs to the following season's cycle, so filing
        its claim against this cycle is refused and neither roster changes.

        PRD: "A trade that names a pick from another cycle, a share whose club
        belongs to another cycle, a booking whose prospect belongs to another
        cycle, a contract whose pick belongs to another cycle, or a compensatory
        claim whose club belongs to another cycle is rejected with
        `ERR_CROSS_CYCLE_REFERENCE` (HTTP 422)."

        Design: Corner/errors/claim_filed_for_a_club_from_another_cycle_is_rejected
        """
        state = build_declaration_open(api)
        next_cycle = create_cycle(
            api,
            season_year=2028,
            declaration_deadline_at="2028-01-15T23:59:59.000Z",
            combine_week_start_at="2028-02-22T08:00:00.000Z",
            combine_week_end_at="2028-02-28T20:00:00.000Z",
            draft_start_at="2028-04-22T18:00:00.000Z",
            rounds_count=2,
        )
        fox = register_club(
            api,
            next_cycle["id"],
            "FOX",
            market_name="Foxbridge",
            prior_season_win_pct=0.375,
            strength_of_schedule=0.500,
            head_to_head_rank=3,
            rookie_pool_total_cents=500000000,
            lottery_combinations=100,
        )

        response = api.create_compensatory_claim(
            compensatory_claim_payload(state["cycle"]["id"], fox["id"]),
            make_club_gm_headers(fox["id"]),
        )
        validate_error(response, ERR_CROSS_CYCLE_REFERENCE, expected_status=422)

        assert read_club(api, fox["id"])["draft_cycle_id"] == next_cycle["id"]
        assert read_cycle(api, state["cycle"]["id"])["club_count"] == 2
        assert read_cycle(api, next_cycle["id"])["club_count"] == 1


class TestUndraftedSigningPool:
    """The frozen undrafted budget caps every bonus a club may offer."""

    def test_bonus_one_cent_over_the_frozen_pool_is_refused(self, api):
        """Every pick lapsed, so the club's undrafted pool freezes at
        214508256 cents and a bonus of one cent more is refused.

        PRD: "Starting from `udfa_pool_total_cents`, each such contract's
        `signing_bonus_cents` is subtracted in turn; if a contract's bonus
        exceeds what remains at its turn, the offer is refused with
        `ERR_UDFA_POOL_EXHAUSTED`."

        Design: Corner/errors/udfa_bonus_one_cent_over_the_pool_is_rejected
        """
        state = build_udfa_window(api)
        elm, har = state["clubs"]["ELM"], state["clubs"]["HAR"]
        prospect = read_prospect(api, state["prospect"]["id"])

        response = api.create_player_contract(
            player_contract_payload(
                prospect["id"],
                elm["id"],
                "UDFA",
                prospect["version"],
                udfa_signing_bonus_cents=214508257,
            ),
            make_club_gm_headers(elm["id"]),
        )
        validate_error(response, ERR_UDFA_POOL_EXHAUSTED, expected_status=422)

        elm_after = read_club(api, elm["id"])
        assert_cents_equal(elm_after["udfa_pool_total_cents"], 214508256)
        assert_cents_equal(elm_after["udfa_pool_remaining_cents"], 214508256)
        assert_cents_equal(
            read_club(api, har["id"])["udfa_pool_total_cents"], 223969910
        )
        assert read_prospect(api, prospect["id"])["signing_status"] == "UNSIGNED"
