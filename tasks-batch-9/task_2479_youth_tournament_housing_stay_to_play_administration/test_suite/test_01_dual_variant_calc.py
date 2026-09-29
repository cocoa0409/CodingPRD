"""Quantities the PRD derives twice from one set of inputs.

A registration turns one roster into a bookable ceiling and a compliance floor;
an invoice turns one set of block figures into a billed shortfall and a
reported-only shortfall. In both pairs the two numbers legitimately differ, and
only one of the two governs.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    NegotiationAction,
    RoomType,
    assertions,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS


def _two_block_attrition_env(api) -> fx.Env:
    """One contract, two equal blocks, one over-performing and one starving.

    Both blocks hold four rooms over the same three nights, so each carries the
    same attrition threshold; one is actualized above it and the other far
    below, which is the only shape in which the two clamping conventions can
    disagree.
    """
    env = fx.draft_contract_env(api, contract_overrides={"attrition_threshold_pct": 0.8})
    block_a = fx.add_block(env, block_size_rooms=4)
    block_b = fx.add_block(
        env, block_size_rooms=4, room_type=RoomType.KING.value
    )
    get_success_data(
        api.negotiate_contract(
            env.contract_id, f.negotiation_payload(NegotiationAction.SUBMIT.value), HM
        )
    )
    env.contract = get_success_data(
        api.negotiate_contract(
            env.contract_id,
            f.negotiation_payload(NegotiationAction.COUNTERSIGN.value),
            env.hotel_headers,
        )
    )

    fx.add_team(env)
    fx.add_registration(env)
    booking_a = fx.add_booking(env, block=block_a, rooms_requested=4)

    team_b = fx.create_team(
        api, name="Alpha SC 14U", org_contact_email="alpha14@example.com"
    )
    registration_b = fx.add_registration(
        env, team=team_b, roster_player_count=4, roster_staff_count=0
    )
    booking_b = fx.add_booking(
        env, registration=registration_b, block=block_b, rooms_requested=1
    )

    fx.submit_rooming_list(env, booking=booking_a)
    fx.submit_rooming_list(env, booking=booking_b)
    fx.confirm_booking(env, booking=booking_a)
    fx.confirm_booking(env, booking=booking_b)
    fx.close_booking_window(env)

    fx.actualize(env, 12, booking=booking_a)
    fx.actualize(env, 3, booking=booking_b)

    env.block = block_a
    env.blocks = [block_a, block_b]
    return env


class TestRosterRoomRequirementVariants:
    """One roster, two occupancy conventions, two different room counts."""

    def test_thirteen_players_and_three_staff_need_six_rooms_but_only_four(self, api):
        """The segregated bucket rounding is paid twice and the pooled rounding
        once, so the same roster yields a ceiling of 6 and a floor of 4.

        PRD §3.3: "Players and staff are housed in separate rooms with different
        capacities: players share at most four to a room, staff at most two to a
        room."

        PRD §3.3: "A roster of 13 players and 3 staff yields four player rooms
        plus two staff rooms, so `required_rooms_registered` is 6, while the
        pooled computation divides 16 by four and yields
        `minimum_rooms_for_compliance` of 4 — six rooms bookable at most, four
        rooms required at least, from identical inputs."

        Design: Difficulty/dual_variant_calc/roster_room_requirement_segregated_vs_pooled_occupancy
        """
        tournament = fx.create_tournament(api)
        team = fx.create_team(api)

        registration = validate_success(
            api.create_team_registration(
                f.team_registration_payload(tournament["id"], team["id"]), HM
            ),
            expected_status=201,
        )

        assert registration["roster_player_count"] == 13
        assert registration["roster_staff_count"] == 3
        assert registration["required_rooms_registered"] == 6
        assert registration["minimum_rooms_for_compliance"] == 4
        assert (
            registration["required_rooms_registered"]
            > registration["minimum_rooms_for_compliance"]
        )

    def test_room_nights_scale_the_segregated_count_and_the_floor_seeds_the_requirement(
        self, api
    ):
        """`required_room_nights` multiplies the segregated count by the event's
        three nights, while it is the pooled floor that seeds
        `effective_required_rooms`.

        PRD §3.1: "When both hold, the server computes `night_count` as the
        number of whole days from `start_date` up to but not including
        `end_date` — the event window is half-open, so the night that begins on
        `end_date` is not part of the event."

        PRD §3.3: "The registration also stores `required_room_nights`, which is
        `required_rooms_registered` multiplied by the tournament's
        `night_count`."

        PRD §3.3: "The rest of the registration record is initialised to
        `exempt_rooms_granted` of 0, `effective_required_rooms` equal to
        `minimum_rooms_for_compliance`, `committed_rooms` of 0 and `status`
        `PENDING_HOUSING`."

        Design: Difficulty/dual_variant_calc/roster_room_requirement_segregated_vs_pooled_occupancy
        """
        tournament = fx.create_tournament(api)
        assert tournament["night_count"] == 3
        team = fx.create_team(api)

        registration = validate_success(
            api.create_team_registration(
                f.team_registration_payload(tournament["id"], team["id"]), HM
            ),
            expected_status=201,
        )

        assert registration["required_room_nights"] == 18
        assert registration["exempt_rooms_granted"] == 0
        assert registration["effective_required_rooms"] == 4
        assert registration["committed_rooms"] == 0
        assert registration["local_team_flag"] is False
        assert registration["status"] == "PENDING_HOUSING"
        assertions.assert_versioned_record(registration, expected_version=1)


class TestAttritionShortfallVariants:
    """Per-block clamping is billed; the contract-wide clamp is only reported."""

    def test_the_billed_shortfall_clamps_each_block_before_summing(self, api):
        """Thresholds of 10 and 10 against actuals of 12 and 3 bill 7 room
        nights, because the over-performing block cannot offset the starved one.

        PRD §3.2: "The server also stamps `threshold_room_nights`, the block's
        attrition floor: multiply `block_size_rooms` by the number of whole
        nights in the block window, multiply by the contract's
        `attrition_threshold_pct`, and round the product **up** to the next
        whole room night."

        PRD §3.8: "The **billed** variant, stored as
        `attrition_shortfall_room_nights_per_block`, clamps each block
        independently: for each block take its threshold nights less its actual
        nights, floor that difference at 0, and sum the clamped per-block
        results."

        PRD §3.8: "Because each block is clamped on its own, a block that
        over-performed cannot offset a block that under-performed."

        PRD §3.8: "`attrition_penalty_cents` is
        `attrition_shortfall_room_nights_per_block` multiplied by the contract's
        `attrition_penalty_rate_cents_per_room_night`."

        Design: Difficulty/dual_variant_calc/attrition_shortfall_per_block_vs_contract_aggregate
        """
        env = _two_block_attrition_env(api)
        block_a, block_b = env.blocks
        assert env.refresh_block(block_a)["threshold_room_nights"] == 10
        assert env.refresh_block(block_b)["threshold_room_nights"] == 10

        invoice = validate_success(
            api.create_rebate_invoice(f.rebate_invoice_payload(env.contract_id), HM),
            expected_status=201,
        )

        assert invoice["attrition_shortfall_room_nights_per_block"] == 7
        assert invoice["attrition_penalty_cents"] == 6300

    def test_the_aggregate_shortfall_is_reported_but_never_billed(self, api):
        """The same inputs read 5 room nights short when clamped once over the
        contract totals, and that softer figure is not the one netted off.

        PRD §3.8: "The **reported-only** variant, stored as
        `attrition_shortfall_room_nights_aggregate`, clamps once over the
        contract totals: sum every block's threshold nights, sum every block's
        actual nights, subtract the second total from the first, and floor that
        single difference at 0."

        PRD §3.8: "Two blocks with thresholds of 10 and 10 and actuals of 12 and
        3 give a per-block shortfall of 7 and an aggregate shortfall of 5 from
        identical inputs."

        PRD §3.8: "The aggregate figure exists purely so that a hotel disputing
        the bill can see the more favourable reading; it is never billed."

        PRD §3.8: "`total_due_cents` is `invoiced_rebate_cents` less
        `attrition_penalty_cents`, floored at 0 — a penalty larger than the
        rebate zeroes the claim rather than turning it into a debt owed by the
        event."

        Design: Difficulty/dual_variant_calc/attrition_shortfall_per_block_vs_contract_aggregate
        """
        env = _two_block_attrition_env(api)

        invoice = validate_success(
            api.create_rebate_invoice(f.rebate_invoice_payload(env.contract_id), HM),
            expected_status=201,
        )

        assert invoice["attrition_shortfall_room_nights_aggregate"] == 5
        assert invoice["attrition_shortfall_room_nights_per_block"] == 7
        assert invoice["invoiced_room_nights"] == 15
        assert invoice["invoiced_rebate_cents"] == 13500
        # 13500 less the per-block penalty of 6300, not the aggregate 4500.
        assert invoice["total_due_cents"] == 7200
        assert invoice["outstanding_cents"] == 7200
        assertions.assert_rebate_ledger_conserved(invoice)
