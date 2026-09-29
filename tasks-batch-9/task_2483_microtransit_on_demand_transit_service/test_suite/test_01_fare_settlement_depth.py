"""Depth tests for the eight-step fare rule and its settlement side effects.

Four behaviours are pinned here, each translated from one recipe:

  * the same trip row priced twice — a provisional quote off the offer's
    `baseline_direct_minutes` and a settled charge off the measured
    `ride_minutes` (PRD §3.7);
  * the pinned operand order inside the fare rule, where the guaranteed-transfer
    waiver is decided before any money exists and the transfer credit is clamped
    only after the fare-category multiplier has been applied (PRD §3.7);
  * the three-hop settlement cascade that pushes a rider onto the daily fare cap
    and zeroes a sibling trip's outstanding quote (PRD §3.6, §3.7);
  * the compensating REFUND row that drives the trip's ledger back to a net of
    zero without mutating the rows already written (PRD §3.7).

Every test builds its own world through the shared builders: the server is
restarted and the database emptied before each one, and the logical clock is
moved explicitly wherever a rule reads "now" (PRD §2.5).
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    accept_assignment,
    board_assignment,
    complete_assignment,
    create_connection,
    create_trip,
    dispatch_trip,
    ledger_for_trip,
    refresh_assignment,
    refresh_block,
    refresh_rider,
    refresh_trip,
    refresh_zone,
    set_clock,
    setup_capped_zone_ready,
    setup_completed_trip,
    setup_dispatch_ready,
    setup_offered_trip,
    setup_two_open_blocks,
)
from test_helpers.test_users import DISPATCHER_HEADERS

# The service day every recipe below replays. 2026-08-03 is a Monday, so the UTC
# service date and the Monday-anchored ISO week start coincide.
SERVICE_DAY = "2026-08-03"
PICKUP_UTC = "2026-08-03T07:00:00Z"
DROPOFF_LONG_UTC = "2026-08-03T07:22:00Z"
DROPOFF_MEDIUM_UTC = "2026-08-03T07:12:00Z"


# ─── The same trip priced twice: quote band vs settled band ────────────────


class TestProvisionalQuoteVersusSettledCharge:
    """One unmodified trip row, two minute bases, two distance bands."""

    def test_settled_charge_uses_measured_ride_minutes_not_the_quoted_baseline(self):
        """A 12-minute baseline quotes in MEDIUM while a 22-minute ride settles in LONG.

        PRD: "A basis of 10 minutes or less puts the trip in the `SHORT` band; more than 10 but no more than 20 minutes puts it in the `MEDIUM` band; anything above 20 minutes is `LONG`."

        Design: Difficulty/dual_variant_calc/trip_fare_provisional_quote_vs_settled_charge_band_shift
        """
        # Zone RBM (base 250, daily cap 600, weekly cap 2500), stops S0 and S4,
        # V1 (6 seats / 2 securement positions), D1, rider R1 (FULL), block B1
        # OPEN over 06:00-10:00Z, and trip T1 S0 -> S4 requested for 07:00Z
        # manually dispatched onto B1.
        state = setup_offered_trip(manual=True, origin_index=0, destination_index=4)
        trip = state["trip"]

        # Step 1 basis for the provisional quote is the offer's direct ride:
        # 3 minutes x 4 index steps = 12 minutes, the MEDIUM band.
        assertions.assert_fields(
            trip,
            baseline_direct_minutes=12,
            fare_status="QUOTED",
            quoted_fare_cents=325,  # 250 base + 75 MEDIUM surcharge, FULL x1.00
        )

        # The ride is then driven slowly: boarded exactly when the rider asked,
        # dropped off 22 minutes later.
        set_clock(PICKUP_UTC)
        accept_assignment(state["assignment"]["id"], state["driver"]["id"])
        board_assignment(state["assignment"]["id"], state["driver"]["id"])
        set_clock(DROPOFF_LONG_UTC)
        complete_assignment(state["assignment"]["id"], state["driver"]["id"])

        settled = refresh_trip(trip["id"])
        assertions.assert_trip_state(settled, "COMPLETED", "CHARGED")
        assertions.assert_fields(
            settled,
            wait_minutes=0,
            ride_minutes=22,
            baseline_direct_minutes=12,
            quoted_fare_cents=325,
            charged_fare_cents=400,  # 250 base + 150 LONG surcharge, FULL x1.00
            applied_cap="NONE",  # 400 <= 600 daily headroom and <= 2500 weekly
        )
        assertions.assert_instant_equals(settled["actual_pickup_utc"], PICKUP_UTC)
        assertions.assert_instant_equals(
            settled["actual_dropoff_utc"], DROPOFF_LONG_UTC
        )
        assert settled["charged_fare_cents"] - settled["quoted_fare_cents"] == 75

    def test_band_shifted_settlement_writes_one_charge_row_and_moves_the_counter(self):
        """The settled 400-cent charge is the sole ledger row and the whole daily counter.

        PRD: "Completing a ride appends a `CHARGE` row for the full post-multiplier fare from step 4, then a `TRANSFER_CREDIT` row for the negative of the transfer credit **only when that credit is greater than zero**, then a `CAP_REBATE` row for the negative of the cap rebate **only when that rebate is greater than zero**."

        Design: Difficulty/dual_variant_calc/trip_fare_provisional_quote_vs_settled_charge_band_shift
        """
        state = setup_offered_trip(manual=True, origin_index=0, destination_index=4)
        trip = state["trip"]

        set_clock(PICKUP_UTC)
        accept_assignment(state["assignment"]["id"], state["driver"]["id"])
        board_assignment(state["assignment"]["id"], state["driver"]["id"])
        set_clock(DROPOFF_LONG_UTC)
        complete_assignment(state["assignment"]["id"], state["driver"]["id"])

        # No connection means no transfer credit, and 400 cents sits inside both
        # headrooms, so neither the credit row nor the rebate row is appended.
        rows = ledger_for_trip(trip["id"])
        assertions.assert_row_count(rows, 1)
        assertions.assert_ledger_kinds(rows, ["CHARGE"])
        assertions.assert_ledger_nets_to(rows, 400)
        assertions.assert_fields(
            rows[0],
            kind="CHARGE",
            amount_cents=400,
            service_date=SERVICE_DAY,
            applied_cap="NONE",
            trip_request_id=trip["id"],
            rider_id=state["rider"]["id"],
        )
        assertions.assert_ledger_row_shape(rows[0])

        rider = refresh_rider(state["rider"]["id"])
        assertions.assert_fields(
            rider,
            daily_fare_paid_cents=400,
            weekly_fare_paid_cents=400,
            fare_counter_date=SERVICE_DAY,
            fare_counter_week_start=SERVICE_DAY,
        )


# ─── Waiver first, multiplier second, credit clamp third ───────────────────


class TestTransferCreditAndMultiplierOrder:
    """The fare rule's operand order, isolated by a single discriminating cent
    figure: 45."""

    def test_credit_is_clamped_by_the_post_multiplier_fare_after_the_waiver(self):
        """A REDUCED rider making a guaranteed rail transfer is quoted 45 cents.

        PRD: "If it does, the credit is the smaller of the connection's `transfer_credit_cents` and the post-multiplier fare from step 4, so a credit can never exceed the fare it offsets and can never make a fare negative."

        Design: Difficulty/combinatorial_formula/transfer_credit_waiver_and_multiplier_order_pinned
        """
        # Zone RBM ACTIVE with base_fare_cents 250; rider R2 is REDUCED.
        state = setup_dispatch_ready(
            rider_overrides={"rider_code": "R2", "fare_category": "REDUCED"}
        )
        # Connection C1 anchored at S4: RAIL GL-1 departing 07:05Z, a 10-minute
        # guaranteed transfer buffer and an 80-cent transfer credit.
        connection = create_connection(
            state["zone"]["id"],
            state["stops"][4]["id"],
            mode="RAIL",
            route_code="GL-1",
            scheduled_departure_utc="2026-08-03T07:05:00Z",
            guaranteed_transfer_buffer_minutes=10,
            transfer_credit_cents=80,
        )
        # T1: R2, S0 -> S4, requested 07:00Z, timed to C1. The pickup is 5
        # minutes from the departure, inside the 10-minute buffer.
        trip = create_trip(
            state["zone"]["id"],
            state["rider"]["id"],
            state["stops"][0]["id"],
            state["stops"][4]["id"],
            requested_pickup_utc=PICKUP_UTC,
            party_size=1,
            connection_id=connection["id"],
        )

        dispatch_trip(trip["id"], state["block"]["id"])

        quoted = refresh_trip(trip["id"])
        # Step 1: basis 12 minutes, which alone would be MEDIUM with a 75-cent
        # surcharge. Step 2: the waiver applies, so step 3 adds no surcharge and
        # the gross stays at 250. Step 4: round_half_up(250 x 0.50) = 125.
        # Step 5: min(80, 125) = 80. Step 6: 125 - 80 = 45. Step 7 leaves it
        # alone because both headrooms are far larger.
        assertions.assert_fields(
            quoted,
            baseline_direct_minutes=12,
            fare_status="QUOTED",
            quoted_fare_cents=45,
            connection_id=connection["id"],
        )
        # Crediting before the multiplier would give (250 - 80) x 0.50 = 85;
        # skipping the waiver would surcharge and drop the credit, giving
        # round_half_up(325 x 0.50) = 163.
        assert quoted["quoted_fare_cents"] != 85
        assert quoted["quoted_fare_cents"] != 163

    def test_manual_dispatch_of_the_credited_trip_offers_without_a_match_score(self):
        """Manual dispatch quotes the trip and records a null match score.

        PRD: "The resulting offer carries `offer_origin` of `MANUAL_DISPATCH` and, because no ranking took place, a `match_score` of null; everything else about the resulting offer and the resulting trip state is identical to an automatic win, including the `UNPRICED → QUOTED` fare move and the block's capacity and version updates."

        Design: Difficulty/combinatorial_formula/transfer_credit_waiver_and_multiplier_order_pinned
        """
        state = setup_dispatch_ready(
            rider_overrides={"rider_code": "R2", "fare_category": "REDUCED"}
        )
        connection = create_connection(
            state["zone"]["id"],
            state["stops"][4]["id"],
            mode="RAIL",
            route_code="GL-1",
            scheduled_departure_utc="2026-08-03T07:05:00Z",
            guaranteed_transfer_buffer_minutes=10,
            transfer_credit_cents=80,
        )
        trip = create_trip(
            state["zone"]["id"],
            state["rider"]["id"],
            state["stops"][0]["id"],
            state["stops"][4]["id"],
            requested_pickup_utc=PICKUP_UTC,
            party_size=1,
            connection_id=connection["id"],
        )
        assertions.assert_trip_state(trip, "RECEIVED", "UNPRICED")

        assignment = dispatch_trip(trip["id"], state["block"]["id"])

        assertions.assert_assignment_state(assignment, "OFFERED")
        assertions.assert_fields(
            assignment,
            offer_origin="MANUAL_DISPATCH",
            match_score=None,
            seats_held=1,
            wav_positions_held=0,
            baseline_direct_minutes=12,
            projected_detour_minutes=0,
            block_id=state["block"]["id"],
            trip_request_id=trip["id"],
        )

        offered = refresh_trip(trip["id"])
        assertions.assert_trip_state(offered, "OFFERED", "QUOTED")
        assertions.assert_fields(
            offered,
            assigned_block_id=state["block"]["id"],
            quoted_fare_cents=45,
        )

        # The block's capacity and version advance exactly as they would after
        # an automatic win.
        block = refresh_block(state["block"]["id"])
        assertions.assert_block_commitments(
            block,
            seats_committed=1,
            wav_positions_committed=0,
            committed_index_min=0,
            committed_index_max=4,
        )
        assertions.assert_version_advanced(state["block"], block)


# ─── Settlement, the daily cap, and the sibling quote it zeroes ────────────


class TestSettlementCascadeOntoASiblingQuote:
    """Completion settles one trip, saturates the rider's daily cap and caps the
    rider's other outstanding quote."""

    @staticmethod
    def _two_quoted_trips_of_one_rider():
        """Zone RBM-CAP (daily cap 300) with blocks B1 and B2 both OPEN, and the
        same rider holding two quoted trips from two different origin stops."""
        state = setup_two_open_blocks(
            zone_overrides={
                "name": "Riverbend Capped",
                "zone_code": "RBM-CAP",
                "fare_cap_cents_daily": 300,
            }
        )
        # T1 S0 -> S4 offered on B1; T2 S6 -> S10 offered on B2. Both baselines
        # are 3 x 4 = 12 minutes and both quotes are computed while the daily
        # counter is still 0, so each reads min(325, 300, 2500) = 300.
        trip_one = create_trip(
            state["zone"]["id"],
            state["rider"]["id"],
            state["stops"][0]["id"],
            state["stops"][4]["id"],
            requested_pickup_utc=PICKUP_UTC,
            party_size=1,
        )
        state["assignment_one"] = dispatch_trip(
            trip_one["id"], state["block_a"]["id"]
        )
        trip_two = create_trip(
            state["zone"]["id"],
            state["rider"]["id"],
            state["stops"][6]["id"],
            state["stops"][10]["id"],
            requested_pickup_utc=PICKUP_UTC,
            party_size=1,
        )
        state["assignment_two"] = dispatch_trip(
            trip_two["id"], state["block_b"]["id"]
        )
        state["trip_one"] = refresh_trip(trip_one["id"])
        state["trip_two"] = refresh_trip(trip_two["id"])

        # Walk the clock to boarding and then to drop-off twelve minutes later.
        set_clock(PICKUP_UTC)
        accept_assignment(state["assignment_one"]["id"], state["driver_a"]["id"])
        board_assignment(state["assignment_one"]["id"], state["driver_a"]["id"])
        set_clock(DROPOFF_MEDIUM_UTC)
        return state

    def test_completion_settles_the_charge_at_the_daily_ceiling_with_a_rebate_row(self):
        """A 325-cent net fare is trimmed to the 300-cent daily headroom and rebated.

        PRD: "The amount actually charged is the smallest of three numbers: the net fare before capping, the daily headroom and the weekly headroom."

        Design: Difficulty/transitive_cascade/settlement_cascade_caps_a_second_quoted_trip_of_the_same_rider
        """
        state = self._two_quoted_trips_of_one_rider()
        assertions.assert_fields(state["trip_one"], quoted_fare_cents=300)

        assignment = complete_assignment(
            state["assignment_one"]["id"], state["driver_a"]["id"]
        )

        assertions.assert_assignment_state(assignment, "COMPLETED")
        settled = refresh_trip(state["trip_one"]["id"])
        assertions.assert_trip_state(settled, "COMPLETED", "CHARGED")
        assertions.assert_fields(
            settled,
            wait_minutes=0,
            ride_minutes=12,
            charged_fare_cents=300,  # min(325 net, 300 daily, 2500 weekly)
            applied_cap="DAILY",  # 300 daily headroom <= 2500 weekly headroom
        )

        # The CHARGE row carries the full post-multiplier fare and the rebate row
        # the 25-cent difference the ceiling withheld.
        rows = ledger_for_trip(settled["id"])
        assertions.assert_row_count(rows, 2)
        assertions.assert_ledger_kinds(rows, ["CHARGE", "CAP_REBATE"])
        assertions.assert_ledger_nets_to(rows, 300)
        charge = assertions.ledger_rows_of_kind(rows, "CHARGE")[0]
        rebate = assertions.ledger_rows_of_kind(rows, "CAP_REBATE")[0]
        assert charge["amount_cents"] == 325
        assert rebate["amount_cents"] == -25
        for row in rows:
            assertions.assert_fields(
                row,
                service_date=SERVICE_DAY,
                applied_cap="DAILY",
                rider_id=state["rider"]["id"],
                trip_request_id=settled["id"],
            )

        rider = refresh_rider(state["rider"]["id"])
        assertions.assert_fields(
            rider,
            daily_fare_paid_cents=300,
            weekly_fare_paid_cents=300,
            fare_counter_date=SERVICE_DAY,
            fare_counter_week_start=SERVICE_DAY,
        )

    def test_hitting_the_daily_cap_zeroes_the_riders_other_outstanding_quote(self):
        """The sibling trip's quote drops to 0 and CAPPED while its offer stands.

        PRD: "The third hop, caused by the second, propagates the daily fare cap sideways: if after settlement the rider's `daily_fare_paid_cents` has reached or passed the zone's `fare_cap_cents_daily`, then every **other** trip request belonging to that same rider whose `fare_status` is `QUOTED` has its `quoted_fare_cents` set to 0 and its `fare_status` moved to `CAPPED`, processed in trip `created_at` ascending order."

        Design: Difficulty/transitive_cascade/settlement_cascade_caps_a_second_quoted_trip_of_the_same_rider
        """
        state = self._two_quoted_trips_of_one_rider()
        assertions.assert_trip_state(state["trip_two"], "OFFERED", "QUOTED")
        assertions.assert_fields(state["trip_two"], quoted_fare_cents=300)

        complete_assignment(state["assignment_one"]["id"], state["driver_a"]["id"])

        # The sibling trip is re-priced on the fare axis only: its fulfilment
        # axis and its offer are left exactly where they were.
        sibling = refresh_trip(state["trip_two"]["id"])
        assertions.assert_trip_state(sibling, "OFFERED", "CAPPED")
        assertions.assert_fields(
            sibling,
            quoted_fare_cents=0,
            charged_fare_cents=None,
            assigned_block_id=state["block_b"]["id"],
        )
        assertions.assert_assignment_state(
            refresh_assignment(state["assignment_two"]["id"]), "OFFERED"
        )
        # Capping a quote appends nothing to the ledger.
        assertions.assert_row_count(ledger_for_trip(sibling["id"]), 0)

        # The scorecard counts the one completed ride only.
        zone = refresh_zone(state["zone"]["id"])
        assertions.assert_fields(zone, completed_trip_count=1)
        assert zone["avg_wait_minutes"] == pytest.approx(0.00, abs=0.01)
        assert zone["avg_ride_minutes"] == pytest.approx(12.00, abs=0.01)


# ─── The refund that drives one trip's ledger back to zero ─────────────────


class TestRefundCompensatesACappedCharge:
    """A refund of a capped settlement is a compensating append, not an erasure."""

    @staticmethod
    def _capped_settled_trip():
        """Zone RBM-CAP (daily cap 300): T1 S0 -> S4 offered, accepted, boarded
        at exactly 07:00Z and dropped at 07:12Z, so settlement writes
        CHARGE +325 and CAP_REBATE -25 for a charge of 300."""
        return setup_completed_trip(
            state=setup_capped_zone_ready(),
            manual=True,
            origin_index=0,
            destination_index=4,
            board_at=PICKUP_UTC,
            complete_at=DROPOFF_MEDIUM_UTC,
        )

    def test_refund_appends_a_reversing_row_that_nets_the_trip_ledger_to_zero(self):
        """CHARGE +325, CAP_REBATE -25 and REFUND -300 sum to exactly zero.

        PRD: "The reversal appends one ledger row of `kind` `REFUND` whose `amount_cents` is the negative of the net cents previously settled for this trip, sets `charged_fare_cents` to 0, recomputes the rider's `daily_fare_paid_cents` and `weekly_fare_paid_cents` so their cap counters return to their pre-charge values, and advances the trip's `version` by 1."

        Design: Difficulty/compensating_invariant/fare_ledger_nets_to_zero_after_capped_charge_is_refunded
        """
        state = self._capped_settled_trip()
        settled = state["trip"]
        assertions.assert_trip_state(settled, "COMPLETED", "CHARGED")
        assertions.assert_fields(
            settled, charged_fare_cents=300, applied_cap="DAILY", ride_minutes=12
        )

        response = api_client.refund_trip_request(
            settled["id"],
            {"reason": "service failure, fare returned"},
            DISPATCHER_HEADERS,
        )
        refunded = validate_success(response, 200)

        assertions.assert_trip_state(refunded, "COMPLETED", "REFUNDED")
        assertions.assert_fields(
            refunded,
            charged_fare_cents=0,
            applied_cap="DAILY",  # the settlement record survives the reversal
            ride_minutes=12,
            wait_minutes=0,
        )
        assertions.assert_version_advanced(settled, refunded)

        rows = ledger_for_trip(settled["id"])
        assertions.assert_row_count(rows, 3)
        assert [row["kind"] for row in rows] == ["CHARGE", "CAP_REBATE", "REFUND"]
        assertions.assert_ledger_nets_to(rows, 0)
        # Nothing already written was mutated or removed.
        assert rows[0]["amount_cents"] == 325
        assert rows[1]["amount_cents"] == -25
        assert rows[2]["amount_cents"] == -300
        assertions.assert_fields(rows[2], service_date=SERVICE_DAY, kind="REFUND")
        for row in rows:
            assertions.assert_ledger_row_shape(row)

        rider = refresh_rider(state["rider"]["id"])
        assertions.assert_fields(
            rider,
            daily_fare_paid_cents=0,
            weekly_fare_paid_cents=0,
            fare_counter_date=SERVICE_DAY,
            fare_counter_week_start=SERVICE_DAY,
        )

    def test_refund_leaves_the_zone_scorecard_and_block_bookkeeping_alone(self):
        """The completed ride still counts and the block keeps its boarding.

        PRD: "The zone's performance metrics are deliberately left untouched by a refund: the ride still happened, and revenue for reporting purposes is read from the ledger at report-submission time rather than from any stored zone total."

        Design: Difficulty/compensating_invariant/fare_ledger_nets_to_zero_after_capped_charge_is_refunded
        """
        state = self._capped_settled_trip()

        validate_success(
            api_client.refund_trip_request(
                state["trip"]["id"],
                {"reason": "service failure, fare returned"},
                DISPATCHER_HEADERS,
            ),
            200,
        )

        zone = refresh_zone(state["zone"]["id"])
        assertions.assert_fields(
            zone, completed_trip_count=1, unserved_trip_count=0
        )
        assert zone["avg_wait_minutes"] == pytest.approx(0.00, abs=0.01)
        assert zone["avg_ride_minutes"] == pytest.approx(12.00, abs=0.01)

        block = refresh_block(state["block"]["id"])
        assertions.assert_block_commitments(
            block,
            seats_committed=0,
            wav_positions_committed=0,
            committed_index_min=None,
            committed_index_max=None,
        )
        assertions.assert_fields(block, boardings_count=1)

    def test_a_second_refund_is_refused_and_appends_no_further_row(self):
        """The fare axis is terminal at REFUNDED, so the trip cannot compensate twice.

        PRD: "It moves the fare axis `CHARGED → REFUNDED`, and a trip whose `fare_status` is anything other than `CHARGED` is rejected with `ERR_TRIP_NOT_CHARGED`."

        Design: Difficulty/compensating_invariant/fare_ledger_nets_to_zero_after_capped_charge_is_refunded
        """
        state = self._capped_settled_trip()
        validate_success(
            api_client.refund_trip_request(
                state["trip"]["id"],
                {"reason": "service failure, fare returned"},
                DISPATCHER_HEADERS,
            ),
            200,
        )

        second = api_client.refund_trip_request(
            state["trip"]["id"],
            {"reason": "duplicate refund attempt"},
            DISPATCHER_HEADERS,
        )
        validate_error(second, ApiErrorId.ERR_TRIP_NOT_CHARGED.value)

        rows = ledger_for_trip(state["trip"]["id"])
        assertions.assert_row_count(rows, 3)
        assertions.assert_ledger_nets_to(rows, 0)
        still_refunded = refresh_trip(state["trip"]["id"])
        assertions.assert_trip_state(still_refunded, "COMPLETED", "REFUNDED")
        assertions.assert_fields(still_refunded, charged_fare_cents=0)
