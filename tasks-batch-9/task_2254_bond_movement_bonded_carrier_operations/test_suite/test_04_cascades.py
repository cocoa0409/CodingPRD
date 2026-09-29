"""One write can set off a chain: a claim that crosses the suspension threshold
cancels unmoved freight and releases its bond, and an unexplained seal break
manufactures its own examination hold."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_ledger_entry,
    assert_money,
    assert_movement_state,
    assert_points,
)
from test_helpers.fixtures import (
    M1_OBLIGATION,
    M1_SEAL,
    build_departed_movement,
    build_suspension_cascade_world,
)


class TestNonArrivalClaimCascade:
    """A second claim takes the carrier to 10.0 points, which suspends it and
    cancels every movement that has not yet departed."""

    def test_second_claim_crosses_the_threshold_and_suspends_the_carrier(self, client):
        """A 4.0-point seal violation plus a 6.0-point non-arrival sum to exactly
        10.0, which drives the carrier ACTIVE to SUSPENDED.

        PRD: "At 10.0 or above, the carrier's `custodial_status` is automatically driven `ACTIVE → SUSPENDED` with `suspension_reason` recorded as `SANCTION_POINTS_THRESHOLD`."

        Design: Difficulty/transitive_cascade/non_arrival_claim_cascades_to_suspension_cancellation_and_bond_release
        """
        world, _seal_claim = build_suspension_cascade_world(client)
        movement_id = world.movements["MAN-0001"]

        claim = validate_success(
            client.issue_claim(
                factories.claim_payload(movement_id, "NON_ARRIVAL", "NEVER_ARRIVED"),
                world.officer,
            ),
            201,
        )

        assert_field(claim, "overdue_days_at_issue", 1, "claim")
        assert_money(claim["assessed_amount"], 1000.00, "claim assessed_amount")
        assert_field(claim, "status", "ISSUED", "claim")

        carrier = world.read_carrier()
        assert_points(carrier["sanction_points"], 10.0)
        assert_field(carrier, "custodial_status", "SUSPENDED", "carrier")
        assert_field(
            carrier, "suspension_reason", "SANCTION_POINTS_THRESHOLD", "carrier"
        )

    def test_suspension_cancels_only_the_undeparted_movement_and_releases_its_bond(
        self, client
    ):
        """The still-FILED movement is cancelled with CARRIER_SUSPENSION_CASCADE and
        its 41.75 released, while the movement already in flight is untouched.

        PRD: "Movements already at `IN_TRANSIT`, `OVERDUE`, `ARRIVED`, or `EXPORTED` are left entirely untouched — the cascade reaches only freight that has not yet moved."

        Design: Difficulty/transitive_cascade/non_arrival_claim_cascades_to_suspension_cancellation_and_bond_release
        """
        world, _seal_claim = build_suspension_cascade_world(client)
        moving_id = world.movements["MAN-0001"]
        parked_id = world.movements["MAN-0003"]

        world.issue_claim(moving_id, "NON_ARRIVAL", "NEVER_ARRIVED")

        parked = world.read_movement(parked_id)
        assert_movement_state(parked, transit_status="CANCELLED")
        assert_field(
            parked, "cancellation_reason", "CARRIER_SUSPENSION_CASCADE", "movement"
        )

        moving = world.read_movement(moving_id)
        assert_movement_state(moving, transit_status="OVERDUE")
        assert_field(moving, "overdue_days", 1, "movement")
        assert_field(moving, "cancellation_reason", None, "movement")

        assert_bond_amounts(
            world.read_bond(),
            obligated=2041.75,
            available=47958.25,
            status="ACTIVE",
            open_movement_count=1,
        )

        entries = world.ledger_entries(bond_id=world.bond_id)
        assert len(entries) == 5, (
            f"two filings, two claims and one cascade cancellation should leave five "
            f"ledger entries but the audit trail holds {len(entries)}"
        )
        assert_ledger_entry(
            entries[-1],
            entry_type="RELEASE",
            amount=-M1_OBLIGATION,
            balance_after=2041.75,
            reason_code="CARRIER_SUSPENSION_CASCADE",
        )


class TestBrokenSealCascade:
    """An unauthorized break sets integrity false and manufactures a system hold
    that drives custody and the port's hold count."""

    def test_unauthorized_break_creates_a_system_hold_and_takes_custody(self, client):
        """The break sets seal_intact false and opens a SEAL_DISCREPANCY hold nobody
        asked for, moving custody to EXAM_HOLD while transit stays ARRIVED.

        PRD: "The system automatically creates an examination hold of type `SEAL_DISCREPANCY` against the movement with `created_by_system` true and `placed_by_user_id` recorded as the literal string `SYSTEM`, which drives `custody_status` to `EXAM_HOLD`, recomputes `open_hold_count` for the port whose `port_code` matches the seal event, and — when the movement is at `ARRIVED` and has not yet consumed its one-time general-order grace — extends the general-order deadline as described in §3.6."

        Design: Difficulty/transitive_cascade/broken_seal_event_cascades_to_system_hold_port_count_and_go_grace
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        world.set_clock("2026-08-10T00:00:00Z")
        report = world.report_arrival(movement_id)
        assert_field(report, "status", "ACCEPTED", "report")

        event = validate_success(
            client.record_seal_event(
                factories.seal_event_payload(
                    movement_id,
                    "BROKEN_UNAUTHORIZED",
                    M1_SEAL,
                    factories.PORT_CHICAGO_CODE,
                ),
                world.carrier,
            ),
            201,
        )
        assert_field(event, "resulting_seal_intact", False, "seal event")
        assert_field(event, "port_code", factories.PORT_CHICAGO_CODE, "seal event")

        movement = world.read_movement(movement_id)
        assert_field(movement, "seal_intact", False, "movement")
        assert_movement_state(
            movement, transit_status="ARRIVED", custody_status="EXAM_HOLD"
        )

        holds = world.holds(movement_id=movement_id)
        assert len(holds) == 1, (
            f"the break should manufacture exactly one hold but the movement carries "
            f"{len(holds)}"
        )
        assert_field(holds[0], "hold_type", "SEAL_DISCREPANCY", "hold")
        assert_field(holds[0], "status", "OPEN", "hold")
        assert_field(holds[0], "created_by_system", True, "hold")
        assert_field(holds[0], "placed_by_user_id", "SYSTEM", "hold")
        assert_field(holds[0], "scheduled_start", None, "hold")

        assert_bond_amounts(world.read_bond(), obligated=M1_OBLIGATION)

    def test_the_system_hold_consumes_the_general_order_grace(self, client):
        """Because the hold opens while the movement is ARRIVED with its grace
        unused, the general-order deadline moves from 2026-08-25 to 2026-08-30 and
        the port's open hold count rises to one.

        PRD: "The first time an examination hold opens against the movement while its `transit_status` is `ARRIVED` and `go_grace_applied` is still false — whether the hold was placed by an officer or auto-created from an unauthorized seal break — `go_deadline_utc` is pushed out by a further 5 days and `go_grace_applied` becomes true."

        Design: Difficulty/transitive_cascade/broken_seal_event_cascades_to_system_hold_port_count_and_go_grace
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]
        world.set_clock("2026-08-10T00:00:00Z")
        world.report_arrival(movement_id)

        before = world.read_movement(movement_id)
        assert_field(before, "go_deadline_utc", "2026-08-25T00:00:00Z", "movement")
        assert_field(before, "go_grace_applied", False, "movement")

        world.record_seal_event(
            movement_id, "BROKEN_UNAUTHORIZED", M1_SEAL, factories.PORT_CHICAGO_CODE
        )

        after = world.read_movement(movement_id)
        assert_field(after, "go_deadline_utc", "2026-08-30T00:00:00Z", "movement")
        assert_field(after, "go_grace_applied", True, "movement")
        assert_field(world.read_port("chicago"), "open_hold_count", 1, "port")

        events = world.seal_events(movement_id)
        assert len(events) == 2, (
            f"the departure seal and the break should leave two events but the chain "
            f"holds {len(events)}"
        )
        assert_field(events[-1], "event_type", "BROKEN_UNAUTHORIZED", "seal event")
        assert_field(events[-1], "resulting_seal_intact", False, "seal event")
