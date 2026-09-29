"""The white space power ledger: reserve tiers, conservation and the chargeable
roll-up, plus the ordering between phase gates and capacity gates."""
import pytest

from test_helpers import (
    api_client,
    assert_hall_power_ledger_balances,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    EC,
    FP,
    advance_phase,
    create_cage,
    create_rack,
    create_tenant,
    install_rack,
    read_busway,
    read_feed,
    read_hall,
    read_rack,
    release_feed,
    reserve_feed,
    setup_fit_out_hall,
    setup_planning_hall,
)


def _tenant_read(tenant_id):
    return validate_success(api_client.get_tenant(tenant_id, FP))


class TestReserveTierEvaluationOrder:
    """The reserve tier is looked up from the freshly computed committed load and
    from nothing else, so a small reservation can erase a large slice of spare."""

    def _hall_at_one_hundred_kw_committed(self):
        ctx = setup_fit_out_hall("HE1", design_kw_capacity=400.00)
        big = create_rack(
            ctx["hall_id"], ctx["zone_id"], "A", 1, design_kw=100.00
        )
        ctx["rack_big"] = big
        ctx["feed_a"] = reserve_feed(big["id"], ctx["bw_a"]["id"], "A", 50.00, 100)
        ctx["feed_b"] = reserve_feed(big["id"], ctx["bw_b"]["id"], "B", 50.00, 100)
        ctx["rack_small"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            2,
            design_kw=5.00,
            required_feed_count=1,
        )
        return ctx

    def test_five_kilowatts_of_load_erases_thirty_kilowatts_of_spare(self):
        """A hall sitting at exactly 100.00 kW committed holds the first-tier reserve;
        one further 5.00 kW reservation steps the tier to 50.00 kW, so spare falls by
        30.00 kW for 5.00 kW of load.

        PRD: "a reservation that pushes committed load from 99.00 kW to 101.00 kW
        consumes 2.00 kW of load *and* a further 25.00 kW of reserve, so 27.00 kW of
        spare capacity disappears at once."

        Design: Difficulty/combinatorial_formula/hall_reserve_tier_keyed_on_committed_kw_evaluation_order
        """
        ctx = self._hall_at_one_hundred_kw_committed()
        before = read_hall(ctx["hall_id"])
        assert before["committed_kw"] == pytest.approx(100.00, abs=0.005)
        assert before["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005), (
            "a hall at exactly 100.00 kW committed stays in the first tier"
        )
        assert before["spare_kw"] == pytest.approx(275.00, abs=0.005)

        feed = reserve_feed(
            ctx["rack_small"]["id"], ctx["bw_a"]["id"], "A", 5.00, 32
        )
        assert feed["status"] == "RESERVED"
        assert feed["allocated_kw"] == pytest.approx(5.000, abs=0.0005)

        after = read_hall(ctx["hall_id"])
        assert after["committed_kw"] == pytest.approx(105.00, abs=0.005)
        assert after["commissioning_reserve_kw"] == pytest.approx(50.00, abs=0.005)
        assert after["spare_kw"] == pytest.approx(245.00, abs=0.005)
        assert before["spare_kw"] - after["spare_kw"] == pytest.approx(30.00, abs=0.005), (
            "5.00 kW of load plus a 25.00 kW tier step is a 30.00 kW loss of spare"
        )
        assert_hall_power_ledger_balances(after)

    def test_tier_is_keyed_on_committed_load_alone_and_the_runs_carry_their_share(self):
        """The three ledger figures are produced in one fixed order — committed load,
        then the tier, then spare — and each run reports only the feeds landed on it.

        PRD: "`commissioning_reserve_kw` is then looked up from a three-step tier
        table keyed **only** on the `committed_kw` just computed."

        Design: Difficulty/combinatorial_formula/hall_reserve_tier_keyed_on_committed_kw_evaluation_order
        """
        ctx = self._hall_at_one_hundred_kw_committed()
        reserve_feed(ctx["rack_small"]["id"], ctx["bw_a"]["id"], "A", 5.00, 32)

        hall = read_hall(ctx["hall_id"])
        bw_a = read_busway(ctx["bw_a"]["id"])
        bw_b = read_busway(ctx["bw_b"]["id"])

        assert bw_a["committed_kw"] == pytest.approx(55.000, abs=0.0005)
        assert bw_a["feed_count"] == 2
        assert bw_b["committed_kw"] == pytest.approx(50.000, abs=0.0005)
        assert bw_b["feed_count"] == 1
        assert bw_a["committed_kw"] + bw_b["committed_kw"] == pytest.approx(
            hall["committed_kw"], abs=0.005
        ), "the hall's committed load is the sum over every live feed of the hall"
        assert hall["commissioning_reserve_kw"] == pytest.approx(50.00, abs=0.005), (
            "the tier follows committed load, never the other way round"
        )
        assert hall["spare_kw"] == pytest.approx(
            hall["design_kw_capacity"]
            - hall["committed_kw"]
            - hall["commissioning_reserve_kw"],
            abs=0.005,
        )


class TestFeedReleaseConservesTheLedger:
    """Reserving and then releasing the same feed returns every ledger figure to its
    pre-reservation value, tier step included."""

    def _hall_with_a_releasable_feed(self):
        ctx = setup_fit_out_hall("HS1", design_kw_capacity=400.00)
        big = create_rack(ctx["hall_id"], ctx["zone_id"], "A", 1, design_kw=100.00)
        ctx["rack_big"] = big
        reserve_feed(big["id"], ctx["bw_a"]["id"], "A", 50.00, 100)
        reserve_feed(big["id"], ctx["bw_b"]["id"], "B", 50.00, 100)
        small = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            2,
            design_kw=5.00,
            required_feed_count=1,
        )
        ctx["rack_small"] = small
        ctx["feed_c"] = reserve_feed(small["id"], ctx["bw_a"]["id"], "A", 5.00, 32)
        return ctx

    def test_release_restores_committed_load_tier_and_spare_exactly(self):
        """Releasing the 5.00 kW feed drops committed load back to 100.00 kW, steps the
        reserve tier back down to 25.00 kW and restores spare to 275.00 kW.

        PRD: "the hall power ledger is re-derived so that committed load falls, the
        reserve tier steps back down and spare capacity is restored to its
        pre-reservation value, and the hall's `version` increments."

        Design: Difficulty/compensating_invariant/feed_reserve_then_delete_conserves_hall_power_ledger
        """
        ctx = self._hall_with_a_releasable_feed()
        released = release_feed(ctx["feed_c"]["id"])
        assert released["status"] == "RELEASED"
        assert released["released_at"] is not None, (
            "release stamps the logical clock's current instant"
        )
        assert released["allocated_kw"] == pytest.approx(5.000, abs=0.0005), (
            "the released row keeps the allocation it recorded"
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["committed_kw"] == pytest.approx(100.00, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(275.00, abs=0.005)
        assert_hall_power_ledger_balances(hall)

        bw_a = read_busway(ctx["bw_a"]["id"])
        assert bw_a["committed_kw"] == pytest.approx(50.000, abs=0.0005)
        assert bw_a["feed_count"] == 1
        small = read_rack(ctx["rack_small"]["id"])
        assert small["connected_kw"] == pytest.approx(0.000, abs=0.0005)
        assert small["status"] == "PLANNED"

    def test_released_row_survives_and_is_revealed_on_request(self):
        """A release is a soft delete: the feed list of that rack is empty by default
        and returns the released row when include_released is asked for.

        PRD: "feed lists hide released rows by default and reveal them when
        `include_released` is requested, and a released feed is still addressable by
        its identifier."

        Design: Difficulty/compensating_invariant/feed_reserve_then_delete_conserves_hall_power_ledger
        """
        ctx = self._hall_with_a_releasable_feed()
        release_feed(ctx["feed_c"]["id"])

        hidden, hidden_meta = validate_paginated(
            api_client.list_rack_feeds(EC, {"rack_id": ctx["rack_small"]["id"]})
        )
        assert hidden_meta["total_count"] == 0, "released rows are hidden by default"
        assert hidden == []

        revealed, revealed_meta = validate_paginated(
            api_client.list_rack_feeds(
                EC,
                {"rack_id": ctx["rack_small"]["id"], "include_released": "true"},
            )
        )
        assert revealed_meta["total_count"] == 1
        assert revealed[0]["id"] == ctx["feed_c"]["id"]
        assert read_feed(ctx["feed_c"]["id"])["status"] == "RELEASED", (
            "the released feed is still addressable by its identifier"
        )


class TestChargeableRollUp:
    """Each rack's uplifted density is rounded first and only then summed, which is a
    different number from rounding the sum."""

    def _hall_with_three_tenant_positions(self):
        tenant = create_tenant("TN-D1", contracted_kw=200.00)
        ctx = setup_fit_out_hall("HD1", design_kw_capacity=400.00)
        ctx["tenant"] = tenant
        cage = create_cage(ctx["hall_id"], tenant["id"], "CG-1")
        ctx["cage"] = cage
        for index in (1, 2, 3):
            ctx[f"rack_{index}"] = create_rack(
                ctx["hall_id"],
                ctx["zone_id"],
                "A",
                index,
                design_kw=7.50,
                cage_id=cage["id"],
                tenant_id=tenant["id"],
            )
        install_rack(ctx["rack_1"]["id"], "AT-0001")
        install_rack(ctx["rack_2"]["id"], "AT-0002")
        return ctx

    def test_three_uplifted_positions_sum_to_the_rounded_per_rack_total(self):
        """Three 7.50 kW positions each publish 7.84 kW and the hall publishes 23.52 kW,
        not the 23.51 kW that rounding a single unrounded sum would give.

        PRD: "Each rack's own `chargeable_kw` is computed first, individually, as its
        designed density multiplied by 1.045 and rounded half up to two decimal places.
        Only then are those per-rack figures summed."

        Design: Difficulty/combinatorial_formula/hall_chargeable_kw_round_then_sum
        """
        ctx = self._hall_with_three_tenant_positions()
        third = install_rack(ctx["rack_3"]["id"], "AT-0003")
        assert third["status"] == "INSTALLED"
        assert third["chargeable_kw"] == pytest.approx(7.84, abs=0.005), (
            "7.50 kW at the 1.045 overhead factor rounds half up to 7.84"
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["chargeable_kw"] == pytest.approx(23.52, abs=0.005), (
            "three per-rack figures of 7.84 sum to 23.52"
        )
        assert hall["chargeable_kw"] != pytest.approx(23.51, abs=0.005), (
            "23.51 is what summing the unrounded products would have produced"
        )
        assert hall["rack_total_count"] == 3
        assert hall["custody_fitout_count"] == 3
        assert hall["custody_ops_count"] == 0
        assert hall["committed_kw"] == pytest.approx(0.00, abs=0.005), (
            "no feed has been reserved, so nothing is committed against the room"
        )
        assert _tenant_read(ctx["tenant"]["id"])["allocated_kw"] == pytest.approx(
            22.50, abs=0.005
        ), "the tenant books the designed density of all three installed positions"

    def test_planned_positions_publish_their_own_figure_but_never_roll_up(self):
        """The third position already carries its own 7.84 kW while PLANNED, yet the
        hall's roll-up counts only the two installed positions.

        PRD: "`PLANNED` positions never contribute. Summing the unrounded products and
        rounding once at the end produces a different number and is wrong."

        Design: Difficulty/combinatorial_formula/hall_chargeable_kw_round_then_sum
        """
        ctx = self._hall_with_three_tenant_positions()
        planned = read_rack(ctx["rack_3"]["id"])
        assert planned["status"] == "PLANNED"
        assert planned["chargeable_kw"] == pytest.approx(7.84, abs=0.005), (
            "the per-rack figure is fixed at placement, not at installation"
        )

        hall = read_hall(ctx["hall_id"])
        assert hall["chargeable_kw"] == pytest.approx(15.68, abs=0.005), (
            "two installed positions at 7.84 each"
        )
        assert hall["rack_total_count"] == 3, (
            "the planned position still occupies floor space"
        )
        assert _tenant_read(ctx["tenant"]["id"])["allocated_kw"] == pytest.approx(
            15.00, abs=0.005
        ), "a planned position reserves floor space but books no entitlement"


class TestPhaseGateBeatsCapacityGates:
    """A reservation that is both out of phase and over every pool reports the phase
    problem first, and only then the highest capacity gate."""

    def _planning_hall_with_an_oversized_position(self):
        ctx = setup_planning_hall("HK1", design_kw_capacity=400.00)
        ctx["rack_1"] = create_rack(
            ctx["hall_id"],
            ctx["zone_id"],
            "A",
            1,
            design_kw=500.00,
            required_feed_count=1,
        )
        return ctx

    def _oversized_feed_request(self, ctx):
        return api_client.create_rack_feed(
            {
                "rack_id": ctx["rack_1"]["id"],
                "busway_id": ctx["bw_a"]["id"],
                "feed_side": "A",
                "requested_kw": 500.00,
                "breaker_amps": 1200,
            },
            EC,
        )

    def test_hall_phase_is_reported_before_any_capacity_breach(self):
        """The same 500.00 kW request is refused on the hall phase while the hall is in
        PLANNING and on the run ceiling once the hall reaches FIT_OUT.

        PRD: "The hall must be in `FIT_OUT` or `COMMISSIONING` — reservations are a
        fit-out and commissioning activity, and attempting one in `PLANNING` or in a
        live hall is refused with `ERR_HALL_PHASE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/feed_reserve_hall_phase_state_beats_capacity_fiscal
        """
        ctx = self._planning_hall_with_an_oversized_position()
        validate_error(
            self._oversized_feed_request(ctx),
            ApiErrorId.ERR_HALL_PHASE_INVALID.value,
            409,
        )

        hall = advance_phase(ctx["hall_id"], "FIT_OUT")
        assert hall["status"] == "FIT_OUT"

        validate_error(
            self._oversized_feed_request(ctx),
            ApiErrorId.ERR_BUSWAY_CAPACITY_EXCEEDED.value,
            422,
        )
        after = read_hall(ctx["hall_id"])
        assert after["status"] == "FIT_OUT"
        assert after["committed_kw"] == pytest.approx(0.00, abs=0.005)
        assert after["spare_kw"] == pytest.approx(375.00, abs=0.005)
        assert read_busway(ctx["bw_a"]["id"])["committed_kw"] == pytest.approx(
            0.000, abs=0.0005
        ), "neither refusal reserved anything"

    def test_run_ceiling_is_reported_before_the_room_and_the_breaker(self):
        """In FIT_OUT the 500.00 kW request breaches the 196.66 kW run ceiling and the
        375.00 kW room spare at once, and the run ceiling is what reports; the 1200 A
        breaker admits 655.53 kW, so no breaker breach exists to report.

        PRD: "A feed reservation that would breach both the busway ceiling and the
        hall's spare capacity reports the busway breach (level 44) first, and the
        branch breaker derate (level 48) is reported only after both pool checks have
        passed."

        Design: Difficulty/priority_pair_validation_conflict/feed_reserve_hall_phase_state_beats_capacity_fiscal
        """
        ctx = self._planning_hall_with_an_oversized_position()
        advance_phase(ctx["hall_id"], "FIT_OUT")

        validate_error(
            self._oversized_feed_request(ctx),
            ApiErrorId.ERR_BUSWAY_CAPACITY_EXCEEDED.value,
            422,
        )

        rows, meta = validate_paginated(
            api_client.list_rack_feeds(EC, {"rack_id": ctx["rack_1"]["id"]})
        )
        assert meta["total_count"] == 0, "the refused request left no feed row behind"
        assert rows == []
        assert read_rack(ctx["rack_1"]["id"])["connected_kw"] == pytest.approx(
            0.000, abs=0.0005
        )
