"""Compensating actions that must return the books to where they started.

A premium unit ships out of the fulfilment room and comes back on a refund, and a
weekday window is taken away by a compliance restriction and handed back by a
reinstatement. In both cases the invariant is not merely that the final figure is
plausible but that it is exactly the opening figure again.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import (
    DIRECTOR_HEADERS,
    api_client,
    assertions,
    fixtures,
)

CLOCK = "2026-08-01T00:00:00Z"
INCIDENT_AT = "2026-07-28T20:30:00Z"


def _paid_pledge_holding_the_only_mug_reserved():
    """One premium with two units received, one of them reserved against a paid
    pledge, so every later movement can be checked against the opening count."""
    fixtures.set_clock(CLOCK)
    mug = fixtures.create_premium(
        sku="MUG-01",
        name="Station Mug",
        tier_threshold_cents=10000,
        fair_market_value_cents=1500,
        units_received_qty=2,
    )
    drive = fixtures.create_active_drive(
        name="Fall Drive",
        goal_cents=5_000_000,
        start_at="2026-08-01T00:00:00Z",
        end_at="2026-08-14T23:59:00Z",
        phone_line_count=4,
    )
    pledge = fixtures.create_pledge(
        drive["id"], donor_name="Marisol Vega", amount_cents=12000, wants_premium=True
    )
    assert pledge["premium_item_id"] == mug["id"]
    assert pledge["premium_status"] == "RESERVED"
    return {"drive_id": drive["id"], "mug_id": mug["id"], "pledge_id": pledge["id"]}


def _restricted_show_that_lost_its_window():
    """A grid carrying two confirmed occupations, one of them preempted away by a
    single critical charge, with the opening minute figures recorded first."""
    base = fixtures.station()
    grid = fixtures.quota_ready_grid(base["host_id"], base["members"], publish=False)
    opening = fixtures.read_grid(grid["grid_id"])
    assert opening["total_assigned_minutes"] == 150
    assertions.assert_two_decimals_equal(
        opening["public_affairs_minutes_pct"], 20.00, "public_affairs_minutes_pct"
    )
    incident = fixtures.create_incident(
        "POLITICAL_CONTENT",
        "CRITICAL",
        INCIDENT_AT,
        complainant_note="Unbalanced candidate advocacy through a whole hour.",
        program_id=grid["music_program_id"],
    )
    return {
        "grid_id": grid["grid_id"],
        "music_program_id": grid["music_program_id"],
        "music_slot_id": grid["music_slot_id"],
        "news_slot_id": grid["news_slot_id"],
        "incident_id": incident["id"],
        "opening_version": opening["version"],
        "opening_minutes": opening["total_assigned_minutes"],
        "opening_pct": opening["public_affairs_minutes_pct"],
    }


class TestPremiumUnitConservation:
    def test_shipping_a_unit_moves_it_without_losing_it(self):
        """The unit leaves the room and the two counters still add up.

        "At registration `on_hand_qty` is initialised to exactly
        `units_received_qty`, with `reserved_qty` and `shipped_qty` both 0." A ship
        then "lowers the premium's `reserved_qty` by 1, lowers its `on_hand_qty` by 1
        and raises its `shipped_qty` by 1 — the unit leaves the room and the
        conservation invariant still balances." The premium stays `AVAILABLE`
        throughout, because that reads from "`on_hand_qty` minus `reserved_qty`".

        Design: Difficulty/compensating_invariant/premium_units_conserved_across_ship_and_refund
        """
        setup = _paid_pledge_holding_the_only_mug_reserved()

        opening = fixtures.read_premium(setup["mug_id"])
        assert opening["units_received_qty"] == 2
        assert opening["on_hand_qty"] == 2
        assert opening["reserved_qty"] == 1
        assert opening["shipped_qty"] == 0
        assert opening["status"] == "AVAILABLE"
        assertions.assert_premium_unit_conservation(opening)

        paid = fixtures.settle_pledge(setup["pledge_id"], outcome="PAID")
        assert paid["payment_status"] == "PAID"
        assert paid["premium_status"] == "RESERVED"

        shipped = fixtures.fulfill_premium(setup["pledge_id"], action="SHIP")
        assert shipped["premium_status"] == "SHIPPED"

        after = fixtures.read_premium(setup["mug_id"])
        assert after["units_received_qty"] == 2
        assert after["on_hand_qty"] == 1
        assert after["reserved_qty"] == 0
        assert after["shipped_qty"] == 1
        assert after["status"] == "AVAILABLE"
        assertions.assert_premium_unit_conservation(after)

    def test_the_refund_returns_the_unit_and_moves_the_money_across(self):
        """The compensating action puts the counters back to the opening figures.

        "a pledge whose `premium_status` is `SHIPPED` moves to `RETURNED`, lowering
        the premium's `shipped_qty` by 1 and raising its `on_hand_qty` by 1 as the
        item comes back to the fulfilment room ... because the amount moves out of
        `fulfilled_total_cents` and into `refunded_total_cents` rather than
        disappearing, and because the unit returns to `on_hand_qty` rather than
        vanishing, both conservation invariants of §2.11 hold after a refund exactly
        as they did before the payment." The allocation itself "is never re-run", so
        the deductible and the chosen gift survive the whole round trip.

        Design: Difficulty/compensating_invariant/premium_units_conserved_across_ship_and_refund
        """
        setup = _paid_pledge_holding_the_only_mug_reserved()
        fixtures.settle_pledge(setup["pledge_id"], outcome="PAID")
        fixtures.fulfill_premium(setup["pledge_id"], action="SHIP")

        refunded = fixtures.refund_pledge(setup["pledge_id"])
        assert refunded["payment_status"] == "REFUNDED"
        assert refunded["premium_status"] == "RETURNED"

        restored = fixtures.read_premium(setup["mug_id"])
        assert restored["units_received_qty"] == 2
        assert restored["on_hand_qty"] == 2
        assert restored["reserved_qty"] == 0
        assert restored["shipped_qty"] == 0
        assertions.assert_premium_unit_conservation(restored)

        pledge = fixtures.read_pledge(setup["pledge_id"])
        assert pledge["premium_item_id"] == setup["mug_id"]
        assert pledge["tax_deductible_cents"] == 10500

        drive = fixtures.read_drive(setup["drive_id"])
        assert drive["refunded_total_cents"] == 12000
        assert drive["fulfilled_total_cents"] == 0
        assertions.assert_drive_money_partition(drive)


class TestGridAirtimeRestoration:
    def test_the_restriction_takes_the_minutes_and_remediation_alone_leaves_them_gone(self):
        """Refunding the points does not hand the window back.

        Each preemption "recomputes the owning grid's `total_assigned_minutes` and
        `public_affairs_minutes_pct` and advances that grid's `version`". Remediation
        "subtracts exactly the incident's `penalty_points` from the show's
        `compliance_penalty_points` and recomputes `compliance_standing` from the new
        total", but "Occupations that were moved to `PREEMPTED` by the restriction
        stay preempted: recovering the air position requires the director to
        explicitly reinstate each one".

        Design: Difficulty/compensating_invariant/grid_airtime_minutes_restored_by_preempt_then_reinstate
        """
        setup = _restricted_show_that_lost_its_window()

        charged = fixtures.adjudicate_incident(setup["incident_id"], finding="SUBSTANTIATED")
        assert charged["penalty_points"] == 6

        restricted = fixtures.read_program(setup["music_program_id"])
        assert restricted["compliance_penalty_points"] == 6
        assert restricted["compliance_standing"] == "RESTRICTED"

        stripped = fixtures.read_grid(setup["grid_id"])
        assert stripped["total_assigned_minutes"] == 30
        assertions.assert_two_decimals_equal(
            stripped["public_affairs_minutes_pct"], 100.00, "public_affairs_minutes_pct"
        )
        assert fixtures.read_slot(setup["music_slot_id"])["status"] == "PREEMPTED"

        fixtures.remediate_incident(
            setup["incident_id"],
            remediation_note="Balancing hour aired and the host retrained on political content.",
        )

        cleared = fixtures.read_program(setup["music_program_id"])
        assert cleared["compliance_penalty_points"] == 0
        assert cleared["compliance_standing"] == "CLEAR"

        assert fixtures.read_slot(setup["music_slot_id"])["status"] == "PREEMPTED"
        assert fixtures.read_grid(setup["grid_id"])["total_assigned_minutes"] == 30

    def test_reinstatement_restores_the_exact_opening_minute_figures(self):
        """The window comes back and the derived figures land on their old values.

        "A successful reinstatement clears `preempted_by_program_id` back to null
        and returns the grid's `total_assigned_minutes` and
        `public_affairs_minutes_pct` to their pre-preemption values." The version
        does not rewind with them, because every occupation event on a grid advances
        it.

        Design: Difficulty/compensating_invariant/grid_airtime_minutes_restored_by_preempt_then_reinstate
        """
        setup = _restricted_show_that_lost_its_window()
        fixtures.adjudicate_incident(setup["incident_id"], finding="SUBSTANTIATED")
        fixtures.remediate_incident(
            setup["incident_id"],
            remediation_note="Balancing hour aired and the host retrained on political content.",
        )

        reinstated = validate_success(
            api_client.reinstate_slot_assignment(setup["music_slot_id"], DIRECTOR_HEADERS), 200
        )
        assert reinstated["status"] == "CONFIRMED"
        assert reinstated["preempted_by_program_id"] is None

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["total_assigned_minutes"] == setup["opening_minutes"]
        assertions.assert_two_decimals_equal(
            grid["public_affairs_minutes_pct"], setup["opening_pct"],
            "public_affairs_minutes_pct",
        )
        assert grid["version"] > setup["opening_version"]

        live_slots, confirmed_meta = validate_paginated(
            api_client.list_slot_assignments(
                DIRECTOR_HEADERS, params={"grid_id": setup["grid_id"], "status": "CONFIRMED"}
            )
        )
        assert confirmed_meta["total_count"] == 2
        assertions.assert_grid_airtime(grid, live_slots)

        _, preempted_meta = validate_paginated(
            api_client.list_slot_assignments(
                DIRECTOR_HEADERS, params={"grid_id": setup["grid_id"], "status": "PREEMPTED"}
            )
        )
        assert preempted_meta["total_count"] == 0

        assert fixtures.read_slot(setup["news_slot_id"])["status"] == "CONFIRMED"
