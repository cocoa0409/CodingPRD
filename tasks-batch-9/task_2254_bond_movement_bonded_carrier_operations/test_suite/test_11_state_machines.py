"""The transitions each lifecycle admits, and the ones it refuses: departure,
withdrawal, arrival, hold release, cargo release, and petition mitigation."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_ledger_entry,
    assert_ledger_stream,
    assert_money,
    assert_movement_state,
    assert_points,
)
from test_helpers.fixtures import (
    LATE_ARRIVAL_ASSESSED,
    M1_OBLIGATION,
    M1_SEAL,
    build_arrived_movement,
    build_departed_movement,
    build_filed_movement,
    build_four_factor_petition,
)


class TestDeparture:
    """Departure is the one transition out of FILED that keeps the movement
    alive, and it happens exactly once."""

    def test_departure_advances_to_in_transit_and_applies_the_seal(self, client):
        """The sealed departure moves the movement to IN_TRANSIT, writes SEAL-100
        onto it, opens its seal history with an APPLIED event at the origin port,
        and bumps the version — without touching the money.

        PRD: "A departure meeting all of those conditions advances `transit_status` `FILED → IN_TRANSIT`, appends a seal event of type `APPLIED` recording the supplied `seal_number` at the origin port's `port_code`, writes that `seal_number` onto the movement, sets `seal_intact` to true, and increments the movement's `version`."

        Design: Corner/state_machines/departure_moves_filed_to_in_transit_and_applies_the_seal
        """
        world = build_filed_movement(client)
        movement_id = world.movements["MAN-0001"]

        departed = validate_success(
            client.depart_movement(
                movement_id, factories.departure_payload(M1_SEAL), world.carrier
            ),
            200,
        )
        assert_movement_state(
            departed, transit_status="IN_TRANSIT", custody_status="BONDED"
        )
        assert_field(departed, "seal_number", M1_SEAL, "movement")
        assert_field(departed, "seal_intact", True, "movement")
        assert_field(departed, "version", 2, "movement")

        events = world.seal_events(movement_id)
        assert len(events) == 1, (
            f"the departure should open the seal history with one event but the "
            f"movement carries {len(events)}"
        )
        assert_field(events[0], "event_type", "APPLIED", "seal event")
        assert_field(events[0], "seal_number", M1_SEAL, "seal event")
        assert_field(events[0], "port_code", factories.PORT_NY_CODE, "seal event")

        entries = world.ledger_entries(movement_id=movement_id)
        assert len(entries) == 1, (
            f"departure moves no money, so the filing's single entry should stand "
            f"alone but the audit trail holds {len(entries)}"
        )
        assert_bond_amounts(world.read_bond(), obligated=M1_OBLIGATION)

    def test_a_second_departure_on_the_same_movement_is_refused(self, client):
        """Once the container is on the road it cannot be sealed and departed
        again, and the refused attempt leaves the original seal in place.

        PRD: "Departing a movement that has already departed is `ERR_MOVEMENT_INVALID_STATE`; departing under a suspended carrier is `ERR_CARRIER_NOT_ACTIVE`; departing on a bond that is no longer `ACTIVE` is `ERR_BOND_NOT_ACTIVE`."

        Design: Corner/state_machines/second_departure_on_the_same_movement_rejected
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        response = client.depart_movement(
            movement_id, factories.departure_payload("SEAL-999"), world.carrier
        )
        validate_error(response, api_errors.ERR_MOVEMENT_INVALID_STATE)

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="IN_TRANSIT")
        assert_field(movement, "seal_number", M1_SEAL, "movement")
        assert_field(movement, "version", 2, "movement")

        events = world.seal_events(movement_id)
        assert len(events) == 1, (
            f"the refused departure must not append a seal event, but the movement "
            f"carries {len(events)}"
        )


class TestWithdrawal:
    """CANCELLED is terminal: nothing departs from it and it cannot be entered
    twice."""

    def test_a_cancelled_movement_can_neither_depart_nor_be_cancelled_again(
        self, client
    ):
        """Withdrawal releases the obligation and closes the movement for good, so
        both a departure and a second withdrawal are refused as invalid state.

        PRD: "Withdrawal is possible only from `FILED`; attempting it once the movement has departed is `ERR_MOVEMENT_INVALID_STATE`."

        PRD: "The withdrawal appends a `RELEASE` ledger entry for the negative of `obligation_amount` with `reason_code` `MOVEMENT_CANCELLED`, recomputes the bond's `obligated_amount`, `available_amount`, and `open_movement_count`, and returns a `SATURATED` bond to `ACTIVE` when headroom reappears above 0.00."

        Design: Corner/state_machines/cancelled_movement_cannot_depart_or_be_cancelled_again
        """
        world = build_filed_movement(client)
        movement_id = world.movements["MAN-0001"]
        world.cancel(movement_id, "SHIPPER_WITHDREW")

        validate_error(
            client.depart_movement(
                movement_id, factories.departure_payload(M1_SEAL), world.carrier
            ),
            api_errors.ERR_MOVEMENT_INVALID_STATE,
        )
        validate_error(
            client.cancel_movement(
                movement_id,
                factories.cancellation_payload("SHIPPER_WITHDREW"),
                world.carrier,
            ),
            api_errors.ERR_MOVEMENT_INVALID_STATE,
        )

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="CANCELLED")
        assert_field(movement, "cancellation_reason", "SHIPPER_WITHDREW", "movement")
        assert_field(movement, "seal_number", None, "movement")

        assert_bond_amounts(
            world.read_bond(),
            obligated=0.00,
            available=50000.00,
            status="ACTIVE",
            open_movement_count=0,
        )
        assert_ledger_stream(
            world.ledger_entries(movement_id=movement_id),
            [
                {
                    "entry_type": "OBLIGATE",
                    "amount": M1_OBLIGATION,
                    "balance_after": M1_OBLIGATION,
                },
                {
                    "entry_type": "RELEASE",
                    "amount": -M1_OBLIGATION,
                    "balance_after": 0.00,
                    "reason_code": "MOVEMENT_CANCELLED",
                },
            ],
        )


class TestArrivalAndCargoRelease:
    """Arrival opens the general-order clock; release is what finally closes an
    IT movement — and only once nothing detains it."""

    def test_the_arrival_report_records_the_discrepancy_and_the_go_deadline(
        self, client
    ):
        """Two of the three packages are reported, so the discrepancy is one piece
        short, and the accepted arrival dates the general-order deadline fifteen
        days out from the arrival instant.

        PRD: "The system stamps `reported_at` from the logical clock and computes `package_discrepancy` as the movement's `package_count` minus `packages_reported` as of filing time."

        PRD: "An accepted arrival sets `arrival_port_id` to the reporting port, sets `arrival_reported_at` to the current logical clock, sets `diversion_flag` to true whenever the reporting port differs from `destination_port_id` (and leaves it false otherwise), computes `go_deadline_utc`, and marks the report `ACCEPTED` with its `package_discrepancy` computed."

        Design: Corner/state_machines/arrival_report_records_port_discrepancy_and_go_deadline
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        world.set_clock("2026-08-10T00:00:00Z")

        report = validate_success(
            client.file_report(
                factories.arrival_report_payload(
                    movement_id, world.ports["chicago"], 2
                ),
                world.carrier,
            ),
            201,
        )
        assert_field(report, "report_type", "ARRIVAL", "report")
        assert_field(report, "status", "ACCEPTED", "report")
        assert_field(report, "reported_at", "2026-08-10T00:00:00Z", "report")
        assert_field(report, "package_discrepancy", 1, "report")

        movement = world.read_movement(movement_id)
        assert_movement_state(
            movement, transit_status="ARRIVED", custody_status="BONDED"
        )
        assert_field(movement, "arrival_port_id", world.ports["chicago"], "movement")
        assert_field(
            movement, "arrival_reported_at", "2026-08-10T00:00:00Z", "movement"
        )
        assert_field(movement, "go_deadline_utc", "2026-08-25T00:00:00Z", "movement")
        assert_field(movement, "go_grace_applied", False, "movement")
        assert_field(movement, "diversion_flag", False, "movement")
        assert_field(movement, "overdue_days", 0, "movement")

    def test_cargo_release_is_refused_while_an_examination_hold_is_open(self, client):
        """The documentary hold both blocks the release and buys the carrier the
        one-time five-day extension of the general-order deadline.

        PRD: "Release requires that the movement's `transit_status` be `ARRIVED` or `EXPORTED`, that no examination hold on the movement remain `OPEN` — otherwise `ERR_HOLD_OPEN` — that `seal_intact` be true, and that `custody_status` not already be `GENERAL_ORDER`."

        PRD: "The first time an examination hold opens against the movement while its `transit_status` is `ARRIVED` and `go_grace_applied` is still false — whether the hold was placed by an officer or auto-created from an unauthorized seal break — `go_deadline_utc` is pushed out by a further 5 days and `go_grace_applied` becomes true."

        Design: Corner/state_machines/cargo_release_with_open_hold_rejected
        """
        world = build_arrived_movement(client)
        movement_id = world.movements["MAN-0001"]
        hold = world.place_unscheduled_hold(movement_id)

        response = client.release_cargo(
            movement_id, factories.cargo_release_payload("ENTRY_FILED"), world.officer
        )
        validate_error(response, api_errors.ERR_HOLD_OPEN)

        movement = world.read_movement(movement_id)
        assert_movement_state(
            movement, transit_status="ARRIVED", custody_status="EXAM_HOLD"
        )
        assert_field(movement, "go_deadline_utc", "2026-08-30T00:00:00Z", "movement")
        assert_field(movement, "go_grace_applied", True, "movement")

        assert_field(world.read_hold(hold["id"]), "status", "OPEN", "hold")
        assert_bond_amounts(world.read_bond(), obligated=M1_OBLIGATION)
        assert len(world.ledger_entries(movement_id=movement_id)) == 1, (
            "a refused release must not release the obligation"
        )

    def test_releasing_one_of_two_holds_keeps_custody_in_exam_hold(self, client):
        """Custody leaves EXAM_HOLD only when the last hold closes, so the first
        release changes the port's count and nothing else.

        PRD: "A second and any later concurrent hold leaves custody at `EXAM_HOLD` — a self-loop — and again recomputes `open_hold_count`."

        PRD: "When the released hold was the **last** open hold on the movement, custody reverts `EXAM_HOLD → BONDED` — never straight to `RELEASED` — and, if the movement had already reached `EXPORTED`, it now auto-closes `EXPORTED → CLOSED` with its `RELEASE` ledger entry and the bond recomputation that entry entails."

        Design: Corner/state_machines/releasing_one_of_two_holds_keeps_custody_in_exam_hold
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        first = world.place_unscheduled_hold(
            movement_id, hold_type="DOCUMENT", reason_code="MANIFEST_REVIEW"
        )
        second = world.place_unscheduled_hold(
            movement_id, hold_type="PGA", reason_code="FDA_REVIEW"
        )
        assert_field(world.read_port("chicago"), "open_hold_count", 2, "port")

        world.release_hold(first["id"], "CLEAR")
        assert_field(world.read_hold(first["id"]), "status", "RELEASED", "hold")
        assert_movement_state(
            world.read_movement(movement_id), custody_status="EXAM_HOLD"
        )
        assert_field(world.read_port("chicago"), "open_hold_count", 1, "port")

        world.release_hold(second["id"], "DISCREPANCY", 1)
        released = world.read_hold(second["id"])
        assert_field(released, "status", "RELEASED", "hold")
        assert_field(released, "findings_code", "DISCREPANCY", "hold")
        assert_field(released, "discrepancy_pieces", 1, "hold")

        assert_field(
            world.read_hold(first["id"]), "discrepancy_pieces", 0, "hold"
        )
        assert_movement_state(
            world.read_movement(movement_id),
            transit_status="IN_TRANSIT",
            custody_status="BONDED",
        )
        assert_field(world.read_port("chicago"), "open_hold_count", 0, "port")
        assert_bond_amounts(world.read_bond(), obligated=M1_OBLIGATION)

    def test_cargo_release_closes_an_it_movement_and_frees_the_bond(self, client):
        """With nothing detaining it, the release both hands the cargo over and
        completes the journey, returning all 41.75 to the bond.

        PRD: "A release drives `custody_status` `BONDED → RELEASED`."

        PRD: "For an `IT` movement standing at `ARRIVED`, the release also completes the journey: `transit_status` advances `ARRIVED → CLOSED` in the same request, appending a `RELEASE` ledger entry for the negative of `obligation_amount` with `reason_code` `CARGO_RELEASED` and re-deriving the bond exactly as above."

        Design: Corner/state_machines/cargo_release_closes_an_it_movement_and_frees_the_bond
        """
        world = build_arrived_movement(client)
        movement_id = world.movements["MAN-0001"]

        released = validate_success(
            client.release_cargo(
                movement_id,
                factories.cargo_release_payload("ENTRY_FILED"),
                world.officer,
            ),
            200,
        )
        assert_movement_state(
            released, transit_status="CLOSED", custody_status="RELEASED"
        )

        assert_bond_amounts(
            world.read_bond(),
            obligated=0.00,
            available=50000.00,
            status="ACTIVE",
            open_movement_count=0,
        )
        assert_ledger_stream(
            world.ledger_entries(movement_id=movement_id),
            [
                {
                    "entry_type": "OBLIGATE",
                    "amount": M1_OBLIGATION,
                    "balance_after": M1_OBLIGATION,
                    "reason_code": "MOVEMENT_FILED",
                },
                {
                    "entry_type": "RELEASE",
                    "amount": -M1_OBLIGATION,
                    "balance_after": 0.00,
                    "reason_code": "CARGO_RELEASED",
                },
            ],
        )


class TestPetitionGrant:
    """A granted petition mitigates the claim and credits the bond, but the
    violation still counts against the carrier."""

    def test_granting_the_petition_mitigates_the_claim_and_credits_the_bond(
        self, client
    ):
        """The round-one offer of 717.30 becomes the claim's mitigated amount, and
        the MITIGATE entry releases the 517.30 difference — while the carrier keeps
        the two points the late arrival earned.

        PRD: "`GRANT` moves the petition `SUBMITTED → GRANTED` and the claim `PETITIONED → MITIGATED`, setting the claim's `mitigated_amount` to the petition's `offer_amount`."

        PRD: "Both `GRANT` and `PARTIAL_GRANT` append a `MITIGATE` ledger entry whose `amount` is the negative of the difference between the claim's `assessed_amount` and its newly set `mitigated_amount`, with `reason_code` `PETITION_GRANTED`, and both then recompute the bond's `obligated_amount` and `available_amount` and re-derive its `status`."

        PRD: "Mitigation does **not** change the carrier's `sanction_points`: the violation happened, and reducing what is payable does not un-happen it."

        Design: Corner/state_machines/granting_a_petition_mitigates_the_claim_and_credits_the_bond
        """
        world, claim, petition = build_four_factor_petition(client, "PET-0041")
        assert_money(petition["offer_amount"], 717.30, "petition offer_amount")

        granted = validate_success(
            client.decide_petition(
                petition["id"],
                factories.petition_decision_payload(
                    "GRANT", "MITIGATION_WARRANTED"
                ),
                world.fpf_officer,
            ),
            200,
        )
        assert_field(granted, "status", "GRANTED", "petition")
        assert_money(granted["offer_amount"], 717.30, "petition offer_amount")

        mitigated = world.read_claim(claim["id"])
        assert_field(mitigated, "status", "MITIGATED", "claim")
        assert_money(mitigated["mitigated_amount"], 717.30, "claim mitigated_amount")
        assert_money(mitigated["assessed_amount"], LATE_ARRIVAL_ASSESSED, "claim assessed_amount")

        assert_bond_amounts(
            world.read_bond(),
            obligated=759.05,
            available=49240.95,
            status="ACTIVE",
        )
        entries = world.ledger_entries(claim_id=claim["id"])
        assert_ledger_stream(
            entries,
            [
                {
                    "entry_type": "INCREASE_LD",
                    "amount": LATE_ARRIVAL_ASSESSED,
                    "balance_after": 1276.35,
                    "reason_code": "CLAIM_ISSUED",
                },
                {
                    "entry_type": "MITIGATE",
                    "amount": -517.30,
                    "balance_after": 759.05,
                    "reason_code": "PETITION_GRANTED",
                },
            ],
        )
        assert_ledger_entry(entries[1], entry_type="MITIGATE", amount=-517.30)

        assert_points(world.read_carrier()["sanction_points"], 2.0)
