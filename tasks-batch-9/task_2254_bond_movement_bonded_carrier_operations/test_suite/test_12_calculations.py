"""The arithmetic the domain runs on: the obligation floor, the overdue-day
measure, the sanction throttle and its decay buckets, the mitigation waterfall,
the general-order pass, and the bond selector."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_deadline,
    assert_field,
    assert_ledger_entry,
    assert_money,
    assert_movement_state,
    assert_points,
)
from test_helpers.fixtures import (
    M1_DEADLINE,
    M1_OBLIGATION,
    M1_SEAL,
    LATE_ARRIVAL_ASSESSED,
    LATE_ARRIVAL_CLOCK,
    build_carrier_without_bond,
    build_departed_movement,
    build_overdue_movement,
    build_registered_world,
    build_two_departed_movements,
)

TRIVIAL_CONSIGNMENT = {
    "cargo_value": 500.00,
    "gross_weight_kg": 50.00,
    "package_count": 1,
}


class TestObligationFloor:
    """A trivial consignment still carries the statutory minimum."""

    def test_the_floor_lifts_a_subtotal_below_the_minimum_to_25(self, client):
        """500.00 of cargo, 50 kg and one package sum to 17.01 of exposure, so the
        stored obligation and the charge against the bond are both 25.00.

        PRD: "Finally, `obligation_amount` is the greater of that subtotal and a floor of 25.00, so that even a trivial shipment carries a minimum obligation of twenty-five dollars."

        Design: Corner/calculations/obligation_floor_binds_when_the_three_components_sum_below_the_minimum
        """
        world = build_registered_world(client)

        movement = validate_success(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0050",
                    bond_id=world.bond_id,
                    **TRIVIAL_CONSIGNMENT,
                ),
                world.carrier,
            ),
            201,
        )
        assert_money(movement["obligation_amount"], 25.00, "obligation_amount")

        assert_bond_amounts(
            world.read_bond(), obligated=25.00, available=49975.00, status="ACTIVE"
        )
        entries = world.ledger_entries(movement_id=movement["id"])
        assert len(entries) == 1, (
            f"the filing should write one obligation entry but the audit trail holds "
            f"{len(entries)}"
        )
        assert_ledger_entry(entries[0], amount=25.00, balance_after=25.00)


class TestOverdueMeasureBoundary:
    """The deadline instant itself is not late; one second past it is a whole
    overdue day."""

    def test_the_deadline_instant_is_not_overdue_but_one_second_later_is(self, client):
        """A sweep at exactly 2026-09-05T00:00:00Z leaves the movement IN_TRANSIT
        with no overdue days, and a sweep one second later marks it OVERDUE with a
        single day counted.

        PRD: "First, every movement whose `transit_status` is `IN_TRANSIT` and whose `transit_deadline_utc` now lies strictly before the clock moves `IN_TRANSIT → OVERDUE`."

        PRD: "Otherwise the measure is the number of seconds from the deadline to the reference instant divided by 86,400 and rounded **up** to the next whole number, so any fraction of a day counts as a full overdue day and an interval of exactly seven days measures 7."

        Design: Corner/calculations/overdue_measure_is_zero_at_the_deadline_and_one_a_second_later
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        world.set_clock(M1_DEADLINE)
        at_deadline = world.run_sweep("boundary sweep at the deadline instant")
        assert_field(at_deadline, "overdue_marked_count", 0, "sweep")

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="IN_TRANSIT")
        assert_field(movement, "overdue_days", 0, "movement")

        world.set_clock("2026-09-05T00:00:01Z")
        past_deadline = world.run_sweep("boundary sweep one second past the deadline")
        assert_field(past_deadline, "overdue_marked_count", 1, "sweep")

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="OVERDUE")
        assert_field(movement, "overdue_days", 1, "movement")

        carrier = world.read_carrier()
        assert_field(carrier, "overdue_movement_count", 1, "carrier")
        assert_points(carrier["sanction_points"], 0.0)
        assert_bond_amounts(world.read_bond(), obligated=M1_OBLIGATION)


class TestSanctionThrottle:
    """Six points is the threshold at which the next filing earns half its
    window."""

    def test_six_points_halve_the_transit_allowance_of_the_next_filing(self, client):
        """A single NON_ARRIVAL claim puts the carrier at exactly 6.0 points, so the
        next interport IT filing earns 17 days rather than 35 — while its custodial
        privileges stay intact, since suspension needs 10.0.

        PRD: "Next comes the **sanction throttle**: if the carrier's `sanction_points`, valued as of this request and after any recomputation performed within it, stands at 6.0 or higher, the running allowance is replaced by the greater of 5 days and the running allowance halved and rounded down to a whole number — a poorly performing carrier gets roughly half the window, but never fewer than five days."

        Design: Corner/calculations/sanction_throttle_halves_the_transit_window_of_the_next_filing
        """
        world = build_overdue_movement(client)
        claim = world.issue_claim(
            world.movements["MAN-0001"], "NON_ARRIVAL", "NEVER_ARRIVED"
        )
        assert_field(claim, "overdue_days_at_issue", 1, "claim")
        assert_money(claim["assessed_amount"], 1000.00, "claim assessed_amount")

        carrier = world.read_carrier()
        assert_points(carrier["sanction_points"], 6.0)
        assert_field(carrier, "custodial_status", "ACTIVE", "carrier")

        throttled = validate_success(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0002",
                    bond_id=world.bond_id,
                ),
                world.carrier,
            ),
            201,
        )
        assert_deadline(
            throttled,
            anchor="2026-09-06T00:00:00Z",
            deadline="2026-09-23T00:00:00Z",
            transit_days_allowed=17,
        )
        assert_money(throttled["obligation_amount"], M1_OBLIGATION, "obligation_amount")

        assert_bond_amounts(
            world.read_bond(), obligated=1083.50, available=48916.50, status="ACTIVE"
        )


class TestSanctionDecayBuckets:
    """One claim's contribution steps down through every decay bucket as the
    clock moves."""

    def test_a_six_point_claim_decays_through_each_bucket_in_turn(self, client):
        """At 90 days the claim counts in full, at 91 days three quarters, at 181
        days a half, and past 365 days nothing at all — and the last sweep, run past
        the bond's expiry, also expires the bond.

        PRD: "A claim aged 90 days or fewer decays not at all and counts at full weight; one aged more than 90 but no more than 180 days counts at three quarters of its weight; one aged more than 180 but no more than 365 days counts at half; and one aged more than 365 days counts for nothing at all."

        PRD: "Second, every bond whose `expiry_date` now lies strictly before the clock moves to `EXPIRED`, from `ACTIVE`, `SATURATED`, or `SUSPENDED` alike, and the sweep's `bonds_expired_count` is increased by one for each."

        Design: Corner/calculations/sanction_points_step_down_through_every_decay_bucket
        """
        world = build_overdue_movement(client)
        claim = world.issue_claim(
            world.movements["MAN-0001"], "NON_ARRIVAL", "NEVER_ARRIVED"
        )

        for clock, expected_points, note in (
            ("2026-12-05T00:00:00Z", 6.0, "age 90 days - still fresh"),
            ("2026-12-06T00:00:00Z", 4.5, "age 91 days - recent bucket"),
            ("2027-03-06T00:00:00Z", 3.0, "age 181 days - stale bucket"),
            ("2027-09-07T00:00:00Z", 0.0, "age 366 days - expired bucket"),
        ):
            world.set_clock(clock)
            sweep = world.run_sweep(note)
            carrier = world.read_carrier()
            assert carrier["sanction_points"] == expected_points, (
                f"at {clock} the six-point claim should score {expected_points} but "
                f"the carrier scores {carrier['sanction_points']}"
            )
            assert_field(carrier, "custodial_status", "ACTIVE", "carrier")

        assert_field(sweep, "bonds_expired_count", 1, "sweep")
        assert_field(world.read_bond(), "status", "EXPIRED", "bond")

        settled = world.read_claim(claim["id"])
        assert_field(settled, "status", "ISSUED", "claim")
        assert_money(settled["assessed_amount"], 1000.00, "claim assessed_amount")


class TestMitigationWaterfall:
    """A prior violation eats most of the credit, and the fee pushes the raw
    offer above the gross, where it is clamped."""

    def test_a_prior_violation_debits_the_credit_and_the_offer_clamps_to_the_gross(
        self, client
    ):
        """One prior claim on another movement debits the single 0.10 factor down to
        0.05, so the 1,172.87 net plus the 100.00 flat fee exceeds the 1,234.60
        assessed and the offer is clamped to the gross — the petition earns nothing.

        PRD: "Step two debits prior offences: the accumulated credit is reduced by five hundredths for each prior violation counted in `prior_violation_count`, and the result is floored at zero so the debit can never turn negative."

        PRD: "Step six sets `offer_amount` to the lesser of the claim's `assessed_amount` and the sum of `net_before_fee` and `processing_fee`, rounded half-up to two decimal places, so an offer can never exceed the gross it mitigates."

        Design: Corner/calculations/petition_waterfall_debits_prior_violations_and_clamps_the_offer_to_gross
        """
        world = build_two_departed_movements(client)
        first = world.movements["MAN-0001"]
        second = world.movements["MAN-0002"]
        world.set_clock(LATE_ARRIVAL_CLOCK)
        world.report_arrival(first)
        world.report_arrival(second)

        prior = world.issue_claim(first, "LATE_ARRIVAL", "OVERDUE_ARRIVAL")
        claim = world.issue_claim(second, "LATE_ARRIVAL", "OVERDUE_ARRIVAL")

        petition = validate_success(
            client.file_petition(
                factories.petition_payload(
                    claim["id"],
                    claim["version"],
                    ["PROMPT_ARRIVAL_REPORT"],
                    "PET-0077",
                ),
                world.carrier,
            ),
            201,
        )
        assert_field(petition, "round", 1, "petition")
        assert_field(petition, "prior_violation_count", 1, "petition")
        assert petition["mitigation_pct"] == 0.05, (
            f"0.10 of credit less one 0.05 debit should leave a mitigation_pct of "
            f"0.05 but the petition carries {petition['mitigation_pct']}"
        )
        assert_money(petition["net_before_fee"], 1172.87, "net_before_fee")
        assert_money(petition["processing_fee"], 100.00, "processing_fee")
        assert_money(petition["offer_amount"], LATE_ARRIVAL_ASSESSED, "offer_amount")
        assert_field(petition, "status", "SUBMITTED", "petition")

        petitioned = world.read_claim(claim["id"])
        assert_field(petitioned, "status", "PETITIONED", "claim")
        assert_money(
            petitioned["assessed_amount"], LATE_ARRIVAL_ASSESSED, "assessed_amount"
        )
        assert_field(world.read_claim(prior["id"]), "status", "ISSUED", "claim")

        assert_points(world.read_carrier()["sanction_points"], 4.0)
        assert_bond_amounts(
            world.read_bond(), obligated=2552.70, available=47447.30, status="ACTIVE"
        )


class TestGeneralOrderPass:
    """The general-order pass reaches only movements whose destination port has a
    warehouse to send them to."""

    def test_the_sweep_sends_only_the_movement_with_a_go_warehouse_to_general_order(
        self, client
    ):
        """Both movements sit past the same 2026-08-25 general-order deadline, but
        only the one destined for a port with a warehouse goes to GENERAL_ORDER —
        and neither obligation is released.

        PRD: "Third, every movement whose `transit_status` is `ARRIVED`, whose `go_deadline_utc` now lies at or before the clock, and whose destination port has `go_warehouse_available` true has its `custody_status` driven to `GENERAL_ORDER` — from `BONDED` or from `EXAM_HOLD` alike — and the sweep's `general_order_count` is increased by one for each."

        PRD: "Going to general order does **not** release the bond obligation: the merchandise remains under bond in the general-order warehouse."

        Design: Corner/calculations/general_order_sweep_skips_ports_without_a_general_order_warehouse
        """
        world = build_registered_world(client, port_aliases=["ny", "chicago", "la"])
        with_warehouse = world.file_movement("MAN-0001")
        without_warehouse = world.file_movement("MAN-0003", destination="la")
        world.depart(with_warehouse, M1_SEAL)
        world.depart(without_warehouse, "SEAL-300")

        world.set_clock("2026-08-10T00:00:00Z")
        world.report_arrival(with_warehouse, port="chicago")
        world.report_arrival(without_warehouse, port="la")

        world.set_clock("2026-08-26T00:00:00Z")
        sweep = world.run_sweep("general order sweep")
        assert_field(sweep, "general_order_count", 1, "sweep")
        assert_field(sweep, "overdue_marked_count", 0, "sweep")

        sent = world.read_movement(with_warehouse)
        assert_movement_state(
            sent, transit_status="ARRIVED", custody_status="GENERAL_ORDER"
        )
        assert_field(sent, "go_deadline_utc", "2026-08-25T00:00:00Z", "movement")

        spared = world.read_movement(without_warehouse)
        assert_movement_state(
            spared, transit_status="ARRIVED", custody_status="BONDED"
        )
        assert_field(spared, "go_deadline_utc", "2026-08-25T00:00:00Z", "movement")

        assert_bond_amounts(
            world.read_bond(), obligated=83.50, open_movement_count=2
        )


class TestBondSelector:
    """Type outranks size: a continuous bond wins over a larger single-transaction
    bond."""

    def test_the_continuous_bond_wins_over_a_larger_single_transaction_bond(
        self, client
    ):
        """A filing that names no bond attaches the 50,000.00 continuous bond and
        leaves the 90,000.00 single-transaction bond entirely untouched.

        PRD: "The surviving candidates are then ranked, and the first row wins: `CONTINUOUS` bonds rank ahead of `SINGLE_TRANSACTION` bonds; among bonds of equal type, larger `available_amount` ranks ahead of smaller; and remaining ties are broken by earlier `created_at`."

        Design: Corner/calculations/bond_selector_prefers_continuous_over_a_larger_single_transaction_bond
        """
        world = build_carrier_without_bond(client)
        continuous_id = world.underwrite_bond(
            factories.continuous_bond_payload(world.carrier_id)
        )
        single_transaction_id = world.underwrite_bond(
            factories.single_transaction_bond_payload(
                world.carrier_id, limit_amount=90000.00, surety_code="SUR-200"
            )
        )

        movement = validate_success(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0004",
                ),
                world.carrier,
            ),
            201,
        )
        assert movement["bond_id"] == continuous_id, (
            "the continuous bond should underwrite the filing but the movement "
            f"named {movement['bond_id']}"
        )
        assert_money(movement["obligation_amount"], M1_OBLIGATION, "obligation_amount")

        assert_bond_amounts(
            world.read_bond(continuous_id),
            obligated=M1_OBLIGATION,
            available=49958.25,
            open_movement_count=1,
        )
        assert_bond_amounts(
            world.read_bond(single_transaction_id),
            obligated=0.00,
            available=90000.00,
            open_movement_count=0,
        )

        _rows, meta = world.ledger_page(bond_id=single_transaction_id)
        assert meta["total_count"] == 0, (
            f"the unselected bond should carry no ledger entries but its audit "
            f"trail holds {meta['total_count']}"
        )
