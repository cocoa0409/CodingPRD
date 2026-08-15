"""Regulatory compensation: provisional vs final variants, the 180-minute
arrival-delay boundary, distance tiers, and refund/credit rounding order."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, add_passenger, add_flight, add_event, add_booking,
    event_to_assessing, cancel_flight_under_event, delay_flight_to, fly_flight,
    get_booking, setup_committed_case, elect,
)

AGENT = TEST_USERS["agent_headers"]


class TestCompensationProvisionalVsFinal:
    """Same booking, same itinerary: projected delay 200 min at commit halves
    the tier base; actual delay 250 min at arrival restores it in full."""

    def _setup_committed(self):
        return setup_committed_case(
            event_code="MECH-1", event_state="RECOVERY",
            passenger_overrides={"full_name": "Ann A", "contact_email": "ann@x.com",
                                 "loyalty_tier": "GOLD"},
            flight_overrides={"flight_number": "OC100",
                              "sched_dep_utc": "2026-08-10T10:00:00Z",
                              "sched_arr_utc": "2026-08-10T12:00:00Z",
                              "distance_km": 3200},
            booking_overrides={"fare_cents": 50000},
            extra_flights=[{"flight_number": "OC200",
                            "sched_dep_utc": "2026-08-10T14:00:00Z",
                            "sched_arr_utc": "2026-08-10T15:20:00Z",
                            "distance_km": 3200}])

    def test_commit_sets_provisional_half_reduction(self, api):
        """PRD §3.7: "The provisional variant runs at commit time and uses the
        committed option's `projected_arrival_delay_minutes`, setting
        `compensation_basis` to `PROVISIONAL`".
        PRD §3.7: "In either variant, when the booking reached `REBOOKED`
        through an own-metal option and the applicable delay is under 240
        minutes, the amount is reduced to one half of the tier base, rounded
        half up; otherwise the amount is the full tier base."
        PRD §3.7: "forty thousand cents when it is at most 3500 kilometers".

        Design: Difficulty/dual_variant_calc/compensation_provisional_vs_final
        """
        ctx = self._setup_committed()
        booking = get_booking(ctx["booking"]["id"])
        # 3200 km -> tier base 40000; projected delay 200 min (15:20 vs 12:00)
        # < 240 with own-metal rebooking -> 20000.
        assert booking["compensation_amount_cents"] == 20000
        assert booking["compensation_basis"] == "PROVISIONAL"

    def test_record_actuals_overwrites_with_final_full_tier(self, api):
        """PRD §3.7: "the final variant runs at record-actuals for every booking
        whose money axis is `ELIGIBLE_PENDING`, `ELECTED_REFUND`, or
        `ELECTED_CREDIT` and whose current itinerary ends on the arriving
        flight, recomputing from the actual arrival — the arriving flight's
        `act_arr_utc` minus that original final scheduled arrival — and setting
        `compensation_basis` to `FINAL`, overwriting the provisional figure when
        actuals diverge from the projection."
        PRD §3.7: "In either variant, when the booking reached `REBOOKED`
        through an own-metal option and the applicable delay is under 240
        minutes, the amount is reduced to one half of the tier base, rounded
        half up; otherwise the amount is the full tier base."

        Design: Difficulty/dual_variant_calc/compensation_provisional_vs_final
        """
        ctx = self._setup_committed()
        recovery = ctx["extra_flights"][0]
        booking_mid = get_booking(ctx["booking"]["id"])
        assert booking_mid["compensation_amount_cents"] == 20000

        fly_flight(recovery["id"], "2026-08-10T14:10:00Z", "2026-08-10T16:10:00Z")
        booking = get_booking(ctx["booking"]["id"])
        # Actual delay 250 min (16:10 vs original final arrival 12:00) >= 240
        # -> no reduction: full 40000.
        assert booking["compensation_amount_cents"] == 40000
        assert booking["compensation_basis"] == "FINAL"


class TestCompensationBoundary180Minutes:
    def _setup_pair(self):
        set_clock("2026-08-10T06:00:00Z")
        p1 = add_passenger(full_name="Hal H", contact_email="hal@x.com")
        p2 = add_passenger(full_name="Ida I", contact_email="ida@x.com")
        j1 = add_flight(flight_number="OC41",
                        sched_dep_utc="2026-08-10T10:00:00Z",
                        sched_arr_utc="2026-08-10T12:00:00Z", distance_km=1200,
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
        j2 = add_flight(flight_number="OC42",
                        sched_dep_utc="2026-08-10T10:00:00Z",
                        sched_arr_utc="2026-08-10T12:00:00Z", distance_km=1200,
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
        event = add_event(event_code="MECH-13", cost_cap_cents=1_000_000)
        event_to_assessing(event["id"])
        b1 = add_booking(p1["id"], j1["id"])
        b2 = add_booking(p2["id"], j2["id"])
        # Link both flights to the controllable event via the initial delay.
        delay_flight_to(j1["id"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z",
                        event_id=event["id"], expected_version=j1["version"])
        delay_flight_to(j2["id"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z",
                        event_id=event["id"], expected_version=j2["version"])
        return j1, j2, b1, b2

    def test_arrival_delay_exactly_180_grants_eligibility(self, api):
        """PRD §3.7: "Separately, when a flight linked to a controllable event
        arrives with an actual arrival delay of at least 180 minutes — measured
        as its `act_arr_utc` against its own `orig_sched_arr_utc` — the
        record-actuals sweep grants every booking that held a `CONFIRMED`
        segment on that flight `ELIGIBLE_PENDING` with `eligible_at` stamped now
        and the amount set to the distance-tier base with basis `FINAL`."
        PRD §3.7: "twenty-five thousand cents when the itinerary's total
        distance is at most 1500 kilometers".

        Design: Difficulty/boundary_precision_check/compensation_boundary_180_minutes
        """
        j1, j2, b1, b2 = self._setup_pair()
        fly_flight(j1["id"], "2026-08-10T11:05:00Z", "2026-08-10T15:00:00Z")
        booking = get_booking(b1["id"])
        assert booking["compensation_status"] == "ELIGIBLE_PENDING", (
            "180 >= 180: the threshold is inclusive")
        assert booking["compensation_amount_cents"] == 25000, (
            "1200 km is within the <=1500 km tier")
        assert booking["compensation_basis"] == "FINAL"

    def test_arrival_delay_179_grants_nothing(self, api):
        """PRD §3.7: "Separately, when a flight linked to a controllable event
        arrives with an actual arrival delay of at least 180 minutes — measured
        as its `act_arr_utc` against its own `orig_sched_arr_utc` — the
        record-actuals sweep grants every booking that held a `CONFIRMED`
        segment on that flight `ELIGIBLE_PENDING` with `eligible_at` stamped now
        and the amount set to the distance-tier base with basis `FINAL`."
        PRD §3.7: "Until eligibility first arises, `eligible_at`,
        `election_deadline`, and `compensation_basis` remain empty and
        `compensation_amount_cents` is zero."

        Design: Difficulty/boundary_precision_check/compensation_boundary_180_minutes
        """
        j1, j2, b1, b2 = self._setup_pair()
        fly_flight(j2["id"], "2026-08-10T11:05:00Z", "2026-08-10T14:59:00Z")
        booking = get_booking(b2["id"])
        assert booking["compensation_status"] == "NONE", (
            "179 < 180: one minute short of the threshold grants nothing")
        assert booking["compensation_amount_cents"] == 0


def test_distance_tier_boundary_1500_vs_1501_km(api):
    """PRD §3.7: "The compensation amount itself is a flat per-booking figure
    covering the whole party, tiered by itinerary distance: twenty-five thousand
    cents when the itinerary's total distance is at most 1500 kilometers, forty
    thousand cents when it is at most 3500 kilometers, and sixty thousand cents
    beyond that, where the itinerary distance is the sum of `distance_km` over
    the booking's original segments."
    PRD §3.7: "the record-actuals sweep grants every booking that held a
    `CONFIRMED` segment on that flight `ELIGIBLE_PENDING` with `eligible_at`
    stamped now and the amount set to the distance-tier base with basis `FINAL`."

    Design: Corner/calculations/compensation_tier_distance_boundary
    """
    set_clock("2026-08-10T06:00:00Z")
    p1 = add_passenger(full_name="Ali A", contact_email="ali@x.com")
    p2 = add_passenger(full_name="Bea B", contact_email="bea@x.com")
    t1 = add_flight(flight_number="OC31", distance_km=1500,
                    sched_dep_utc="2026-08-10T10:00:00Z",
                    sched_arr_utc="2026-08-10T12:00:00Z",
                    cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    t2 = add_flight(flight_number="OC32", distance_km=1501,
                    sched_dep_utc="2026-08-10T10:00:00Z",
                    sched_arr_utc="2026-08-10T12:00:00Z",
                    cabins=[{"cabin": "ECONOMY", "capacity": 50}])
    event = add_event(event_code="MECH-C8", cost_cap_cents=1_000_000)
    event_to_assessing(event["id"])
    b1 = add_booking(p1["id"], t1["id"])
    b2 = add_booking(p2["id"], t2["id"])
    delay_flight_to(t1["id"], "2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z",
                    event_id=event["id"], expected_version=t1["version"])
    delay_flight_to(t2["id"], "2026-08-10T11:00:00Z", "2026-08-10T13:00:00Z",
                    event_id=event["id"], expected_version=t2["version"])
    fly_flight(t1["id"], "2026-08-10T11:05:00Z", "2026-08-10T16:20:00Z")
    fly_flight(t2["id"], "2026-08-10T11:05:00Z", "2026-08-10T16:20:00Z")

    booking1 = get_booking(b1["id"])
    assert booking1["compensation_amount_cents"] == 25000, (
        "1500 km is inside the <=1500 km tier (boundary included)")
    assert booking1["compensation_basis"] == "FINAL"

    booking2 = get_booking(b2["id"])
    assert booking2["compensation_amount_cents"] == 40000, (
        "1501 km crosses into the <=3500 km tier")
    assert booking2["compensation_basis"] == "FINAL"


class TestRefundCreditNestedRounding:
    def _setup_election(self):
        set_clock("2026-08-09T00:00:00Z")
        pax = add_passenger(full_name="Ron R", contact_email="ron@x.com")
        g1 = add_flight(flight_number="OC11", origin="AAA", destination="BBB",
                        sched_dep_utc="2026-08-09T06:00:00Z",
                        sched_arr_utc="2026-08-09T07:00:00Z", distance_km=1000,
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
        g2 = add_flight(flight_number="OC12", origin="BBB", destination="CCC",
                        sched_dep_utc="2026-08-09T08:00:00Z",
                        sched_arr_utc="2026-08-09T09:00:00Z", distance_km=1000,
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
        g3 = add_flight(flight_number="OC13", origin="CCC", destination="DDD",
                        sched_dep_utc="2026-08-09T10:00:00Z",
                        sched_arr_utc="2026-08-09T11:00:00Z", distance_km=1000,
                        cabins=[{"cabin": "ECONOMY", "capacity": 50}])
        booking = add_booking(pax["id"], segments=[
            {"flight_id": g1["id"], "seq_no": 1},
            {"flight_id": g2["id"], "seq_no": 2},
            {"flight_id": g3["id"], "seq_no": 3},
        ], fare_cents=10000)
        fly_flight(g1["id"], "2026-08-09T06:05:00Z", "2026-08-09T07:05:00Z")
        event = add_event(event_code="MECH-4", hub="BBB", cost_cap_cents=1_000_000)
        event_to_assessing(event["id"])
        cancel_flight_under_event(g2["id"], event["id"], expected_version=g2["version"])
        cancel_flight_under_event(g3["id"], event["id"], expected_version=g3["version"])
        return booking

    def test_refund_rounds_each_flown_segment_before_subtracting(self, api):
        """PRD §3.7: "The booking's `refund_amount_cents` is the `fare_cents`
        minus the sum of per-segment allocations for the segments already
        `FLOWN`, where each segment's allocation is the fare multiplied by that
        segment's `distance_km`, divided by the total distance of all original
        segments — flown or not — and rounded half up per segment before the sum
        is taken and subtracted. Rounding each flown allocation first, rather
        than summing allocations of the unflown remainder, is deliberate and
        changes outcomes by a cent on some itineraries."

        Design: Difficulty/combinatorial_formula/refund_credit_nested_rounding
        """
        booking = self._setup_election()
        election = elect(booking["id"], "CREDIT")
        # round_half_up(10000 * 1000 / 3000) = 3333 for the one FLOWN leg;
        # refund = 10000 - 3333 = 6667 (not the 3333+3333=6666 unflown order).
        assert election["refund_amount_cents"] == 6667

    def test_credit_uplift_rounds_once_after_multiplication(self, api):
        """PRD §3.7: "The `credit_amount_cents` is the `refund_amount_cents`
        increased by ten percent, rounded half up exactly once after the
        multiplication, and it is recomputed whenever the refund figure is."

        Design: Difficulty/combinatorial_formula/refund_credit_nested_rounding
        """
        booking = self._setup_election()
        election = elect(booking["id"], "CREDIT")
        assert election["refund_amount_cents"] == 6667
        # round_half_up(6667 * 1.10) = round_half_up(7333.7) = 7334
        assert election["credit_amount_cents"] == 7334
