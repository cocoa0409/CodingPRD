"""Departure dispatch cascade and demurrage charge calculation."""
from test_helpers import (
    CLOCK_STARTUP_DEFAULT,
    assert_money,
    assert_timestamp_instant,
    assign_booking,
    close_flight,
    create_build_up_plan,
    depart_flight,
    get_booking,
    get_flight,
    get_uld_charge,
    make_accepted_booking,
    make_open_flight,
    make_uld_type_and_unit,
    return_uld,
    seal_plan,
    set_clock,
    setup_departed_scenario,
    setup_two_plan_departure,
)


class TestDepartureCascade:
    def test_departure_dispatch_cascade_plan_uld_charge(
        self, api, capacity_controller_headers
    ):
        """PRD §3.8: "First, every `SEALED` build-up plan on the flight moves
        to `DEPARTED`. Second, each departed plan's unit moves `ASSIGNED →
        DISPATCHED`, its `dispatched_at` stamped from the logical clock. Third,
        each newly dispatched unit immediately accrues a demurrage charge: a
        `ULDCharge` of `charge_type` `DEMURRAGE` is created in `PROVISIONAL`
        status, priced by the provisional variant below with the end instant set
        to the flight's `scheduled_arrival`."

        Design: Difficulty/transitive_cascade/departure_dispatch_cascade
        """
        scenario = setup_departed_scenario(
            flight_overrides={
                "flight_number": "CA210",
                "scheduled_departure": "2026-08-10T08:00:00Z",
                "scheduled_arrival": "2026-08-14T08:00:00Z",
            },
            booking_overrides={"shipper_ref": "SHP-F1"},
            uld_code="AKE00007CA",
            depart_clock="2026-08-10T08:00:00Z",
        )
        assert scenario["plan"]["status"] == "DEPARTED"
        assert scenario["uld"]["status"] == "DISPATCHED"
        assert_timestamp_instant(
            scenario["uld"]["dispatched_at"], "2026-08-10T08:00:00Z"
        )
        charge = scenario["charge"]
        assert charge["charge_type"] == "DEMURRAGE"
        assert charge["status"] == "PROVISIONAL"
        # 4 whole days to scheduled_arrival, 3 free: 1 chargeable day at 50.00
        assert_money(charge["amount"], 50.00)
        assert charge["tier1_days"] == 1 and charge["tier2_days"] == 0

    def test_departure_dispatch_cascade_bookings(self, api, capacity_controller_headers):
        """PRD §3.8: "Fourth, every booking `BUILT_UP` on a departed plan moves
        to `LOADED` — cargo that made the aircraft. Fifth, every `ACCEPTED`
        booking that was never built into a plan is left behind: it moves to
        `OFFLOADED`, its weight and volume are released from the flight's
        allocation counters, and it enters the rebookable pool of §3.2."

        Design: Difficulty/transitive_cascade/departure_dispatch_cascade
        """
        flight = make_open_flight(
            flight_number="CA210",
            scheduled_departure="2026-08-10T08:00:00Z",
            scheduled_arrival="2026-08-14T08:00:00Z",
        )
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00007CA")
        built = make_accepted_booking(
            flight["id"], shipper_ref="SHP-F1", gross_weight_kg=100, volume_m3=1
        )
        unbuilt = make_accepted_booking(
            flight["id"], shipper_ref="SHP-F2", gross_weight_kg=150, volume_m3=1
        )
        plan = create_build_up_plan(flight["id"], uld["id"])
        assign_booking(plan["id"], built["id"])
        seal_plan(plan["id"])
        set_clock("2026-08-10T08:00:00Z")
        close_flight(flight["id"])
        depart_flight(flight["id"])
        assert get_booking(built["id"])["status"] == "LOADED", (
            "A built booking flies with the departed plan"
        )
        assert get_booking(unbuilt["id"])["status"] == "OFFLOADED", (
            "An unbuilt ACCEPTED booking misses the departure"
        )
        assert get_flight(flight["id"])["status"] == "DEPARTED"


class TestDemurrageVariants:
    def test_demurrage_provisional_charge_at_dispatch(self, api, ramp_operator_headers):
        """PRD §3.8: "The provisional variant runs at dispatch with the end
        instant set to the flight's `scheduled_arrival` and stores the
        resulting `amount`, `tier1_days`, and `tier2_days` on a `PROVISIONAL`
        charge row"
        PRD §3.8: "Chargeable days are the days in use minus a free allowance
        of three days, never falling below zero, so a unit returned within the
        allowance accrues nothing. The first four chargeable days are billed as
        `tier1_days` at 50.00 per unit per day; any remaining chargeable days
        are billed as `tier2_days` at 120.00 per unit per day."

        Design: Difficulty/dual_variant_calc/demurrage_provisional_vs_final_diverge
        """
        scenario = setup_departed_scenario(
            flight_overrides={
                "flight_number": "CA201",
                "scheduled_departure": "2026-08-10T08:00:00Z",
                "scheduled_arrival": "2026-08-14T08:00:00Z",
            },
            booking_overrides={
                "shipper_ref": "SHP-D1", "pieces": 4,
                "gross_weight_kg": 200, "volume_m3": 2,
            },
            uld_code="AKE00001CA",
            depart_clock="2026-08-10T08:00:00Z",
        )
        charge = get_uld_charge(scenario["charge"]["id"])
        assert charge["status"] == "PROVISIONAL"
        # dispatched 08-10 08:00, provisional end = arrival 08-14 08:00:
        # 4 days in use, 3 free -> 1 tier-1 day -> 50.00
        assert_money(charge["amount"], 50.00)
        assert charge["tier1_days"] == 1
        assert charge["tier2_days"] == 0

    def test_demurrage_final_recompute_on_return(self, api, ramp_operator_headers):
        """PRD §3.8: "the final variant runs when the unit comes back,
        recomputing the same charge row with the end instant set to the unit's
        actual `returned_at` and moving the charge `PROVISIONAL → FINALIZED`."
        PRD §3.8: "The first four chargeable days are billed as `tier1_days` at
        50.00 per unit per day; any remaining chargeable days are billed as
        `tier2_days` at 120.00 per unit per day."

        Design: Difficulty/dual_variant_calc/demurrage_provisional_vs_final_diverge
        """
        scenario = setup_departed_scenario(
            flight_overrides={
                "flight_number": "CA201",
                "scheduled_departure": "2026-08-10T08:00:00Z",
                "scheduled_arrival": "2026-08-14T08:00:00Z",
            },
            booking_overrides={
                "shipper_ref": "SHP-D1", "pieces": 4,
                "gross_weight_kg": 200, "volume_m3": 2,
            },
            uld_code="AKE00001CA",
            depart_clock="2026-08-10T08:00:00Z",
        )
        charge_id = scenario["charge"]["id"]
        assert_money(get_uld_charge(charge_id)["amount"], 50.00)
        set_clock("2026-08-20T08:00:00Z")
        return_uld(scenario["uld"]["id"])
        final = get_uld_charge(charge_id)
        assert final["status"] == "FINALIZED", (
            "The same charge row is recomputed and finalized at return"
        )
        # 10 days in use, 3 free -> 7 chargeable: 4 @ 50.00 + 3 @ 120.00
        assert final["tier1_days"] == 4
        assert final["tier2_days"] == 3
        assert_money(final["amount"], 560.00)


class TestDemurrageTierStraddling:
    def test_demurrage_tier_straddling_amount(self, api, ramp_operator_headers):
        """PRD §3.8: "Chargeable days are the days in use minus a free
        allowance of three days, never falling below zero, so a unit returned
        within the allowance accrues nothing. The first four chargeable days
        are billed as `tier1_days` at 50.00 per unit per day; any remaining
        chargeable days are billed as `tier2_days` at 120.00 per unit per day.
        The charge `amount` is the sum of the two tier charges, rounded half-up
        to two decimal places."

        Design: Difficulty/combinatorial_formula/demurrage_tier_straddling_formula
        """
        scenario = setup_departed_scenario(
            flight_overrides={
                "flight_number": "CA203",
                "scheduled_departure": "2026-08-10T08:00:00Z",
                "scheduled_arrival": "2026-08-14T08:00:00Z",
            },
            booking_overrides={
                "shipper_ref": "SHP-D2", "pieces": 4,
                "gross_weight_kg": 200, "volume_m3": 2,
            },
            uld_code="AKE00003CA",
            depart_clock="2026-08-10T08:00:00Z",
        )
        set_clock("2026-08-22T08:00:00Z")
        return_uld(scenario["uld"]["id"])
        charge = get_uld_charge(scenario["charge"]["id"])
        assert charge["status"] == "FINALIZED"
        # 12 days in use -> 9 chargeable -> 4*50.00 + 5*120.00 = 800.00
        assert_money(charge["amount"], 800.00)

    def test_demurrage_tier_straddling_day_split(self, api, ramp_operator_headers):
        """PRD §3.8: "The first four chargeable days are billed as `tier1_days`
        at 50.00 per unit per day; any remaining chargeable days are billed as
        `tier2_days` at 120.00 per unit per day."

        Design: Difficulty/combinatorial_formula/demurrage_tier_straddling_formula
        """
        scenario = setup_departed_scenario(
            flight_overrides={
                "flight_number": "CA203",
                "scheduled_departure": "2026-08-10T08:00:00Z",
                "scheduled_arrival": "2026-08-14T08:00:00Z",
            },
            booking_overrides={
                "shipper_ref": "SHP-D2", "pieces": 4,
                "gross_weight_kg": 200, "volume_m3": 2,
            },
            uld_code="AKE00003CA",
            depart_clock="2026-08-10T08:00:00Z",
        )
        set_clock("2026-08-22T08:00:00Z")
        return_uld(scenario["uld"]["id"])
        charge = get_uld_charge(scenario["charge"]["id"])
        assert charge["tier1_days"] == 4, "chargeable 9 = min(9, 4) tier-1 days"
        assert charge["tier2_days"] == 5, "the remainder of 5 falls into tier 2"


class TestDemurrageFreeDayBoundary:
    def test_demurrage_free_allowance_day_three_zero(self, api, ramp_operator_headers):
        """PRD §3.8: "Chargeable days are the days in use minus a free
        allowance of three days, never falling below zero, so a unit returned
        within the allowance accrues nothing."

        Design: Difficulty/boundary_precision_check/demurrage_free_day_boundary
        """
        scenario = setup_two_plan_departure()
        set_clock("2026-08-13T08:00:00Z")  # exactly 3 whole days after dispatch
        return_uld(scenario["uld1"]["id"])
        charge = get_uld_charge(scenario["charge1"]["id"])
        assert charge["status"] == "FINALIZED"
        assert charge["tier1_days"] == 0
        assert_money(charge["amount"], 0.00)

    def test_demurrage_first_chargeable_day_four(self, api, ramp_operator_headers):
        """PRD §3.8: "Chargeable days are the days in use minus a free
        allowance of three days, never falling below zero, so a unit returned
        within the allowance accrues nothing. The first four chargeable days
        are billed as `tier1_days` at 50.00 per unit per day"

        Design: Difficulty/boundary_precision_check/demurrage_free_day_boundary
        """
        scenario = setup_two_plan_departure()
        set_clock("2026-08-14T08:00:00Z")  # exactly 4 whole days after dispatch
        return_uld(scenario["uld2"]["id"])
        charge = get_uld_charge(scenario["charge2"]["id"])
        assert charge["status"] == "FINALIZED"
        assert charge["tier1_days"] == 1
        assert_money(charge["amount"], 50.00)


class TestLogicalClockDefault:
    def test_clock_default_applies_without_set(self, api, ramp_operator_headers):
        """PRD §2.5: "Before any client has set it, the logical clock reads
        exactly `2026-08-01T00:00:00Z` — this is the server startup default,
        and the server never falls back to wall-clock time behind it."
        PRD §3.8: "each departed plan's unit moves `ASSIGNED → DISPATCHED`, its
        `dispatched_at` stamped from the logical clock."

        Design: Corner/endpoints/clock_default_applies_without_set
        """
        scenario = setup_departed_scenario(
            flight_overrides={"flight_number": "CA330", "max_payload_kg": 5000},
            booking_overrides={"shipper_ref": "SHP-CK"},
            uld_code="AKE00115CA",
            depart_clock=None,
        )
        assert_timestamp_instant(
            scenario["uld"]["dispatched_at"], CLOCK_STARTUP_DEFAULT
        )
