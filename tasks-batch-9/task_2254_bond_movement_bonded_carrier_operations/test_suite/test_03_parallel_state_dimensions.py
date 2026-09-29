"""A movement carries two independent state dimensions, and an overdue movement
can be brought back into transit by an approved extension."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import (
    assert_deadline,
    assert_field,
    assert_movement_state,
)
from test_helpers.fixtures import M1_TRANSIT_DAYS, build_departed_movement


class TestCustodyAndTransitAdvanceIndependently:
    """Placing a hold moves custody without moving transit; arriving moves
    transit without moving custody; releasing the hold moves custody back."""

    def test_arrival_advances_transit_while_custody_stays_in_exam_hold(self, client):
        """A document hold opened in transit leaves transit_status IN_TRANSIT, and
        the later arrival advances transit to ARRIVED while custody remains
        EXAM_HOLD.

        PRD: "Placement drives `custody_status` `BONDED → EXAM_HOLD` and recomputes the port's `open_hold_count`."

        Design: Difficulty/non_linear_state_machine/custody_and_transit_dimensions_advance_independently
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        world.set_clock("2026-08-05T00:00:00Z")
        world.place_unscheduled_hold(movement_id)

        held = world.read_movement(movement_id)
        assert_movement_state(held, transit_status="IN_TRANSIT", custody_status="EXAM_HOLD")
        assert_field(world.read_port("chicago"), "open_hold_count", 1, "port")

        world.set_clock("2026-08-10T00:00:00Z")
        report = validate_success(
            client.file_report(
                factories.arrival_report_payload(movement_id, world.ports["chicago"]),
                world.carrier,
            ),
            201,
        )
        assert_field(report, "status", "ACCEPTED", "report")

        arrived = world.read_movement(movement_id)
        assert_movement_state(
            arrived, transit_status="ARRIVED", custody_status="EXAM_HOLD"
        )
        assert_field(
            arrived, "arrival_reported_at", "2026-08-10T00:00:00Z", "movement"
        )

    def test_releasing_the_hold_returns_custody_without_touching_transit(self, client):
        """Releasing the only open hold takes custody back to BONDED and leaves
        transit_status at ARRIVED, with the general-order clock still running from
        the arrival instant because the hold opened before the movement arrived.

        PRD: "When the released hold was the **last** open hold on the movement, custody reverts `EXAM_HOLD → BONDED` — never straight to `RELEASED` — and, if the movement had already reached `EXPORTED`, it now auto-closes `EXPORTED → CLOSED` with its `RELEASE` ledger entry and the bond recomputation that entry entails."

        Design: Difficulty/non_linear_state_machine/custody_and_transit_dimensions_advance_independently
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        world.set_clock("2026-08-05T00:00:00Z")
        hold = world.place_unscheduled_hold(movement_id)
        world.set_clock("2026-08-10T00:00:00Z")
        world.report_arrival(movement_id)

        released = validate_success(
            client.release_hold(
                hold["id"],
                factories.hold_release_payload("CLEAR"),
                world.second_officer,
            ),
            200,
        )
        assert_field(released, "status", "RELEASED", "hold")
        assert_field(released, "findings_code", "CLEAR", "hold")

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="ARRIVED", custody_status="BONDED")
        assert_field(movement, "go_deadline_utc", "2026-08-25T00:00:00Z", "movement")
        assert_field(movement, "go_grace_applied", False, "movement")
        assert_field(world.read_port("chicago"), "open_hold_count", 0, "port")


class TestOverdueRevival:
    """A movement that has gone overdue by no more than two days returns to
    IN_TRANSIT when an approved extension pushes its deadline into the future."""

    def test_sweep_marks_the_movement_overdue_one_day_past_the_deadline(self, client):
        """A sweep run one day after the 2026-09-05 deadline moves the movement
        IN_TRANSIT to OVERDUE, counts it once, and measures one overdue day.

        PRD: "First, every movement whose `transit_status` is `IN_TRANSIT` and whose `transit_deadline_utc` now lies strictly before the clock moves `IN_TRANSIT → OVERDUE`."

        Design: Difficulty/non_linear_state_machine/overdue_movement_revives_to_in_transit_after_extension
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        world.set_clock("2026-09-06T00:00:00Z")
        sweep = validate_success(
            client.run_sweep(
                factories.sweep_payload("daily overdue sweep"), world.officer
            ),
            201,
        )
        assert_field(sweep, "overdue_marked_count", 1, "sweep")
        assert sweep["overdue_movement_ids"] == [movement_id], (
            "the sweep should list exactly the movement it marked overdue"
        )

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="OVERDUE")
        assert_field(movement, "overdue_days", 1, "movement")
        assert_field(world.read_carrier(), "overdue_movement_count", 1, "carrier")

    def test_approved_extension_revives_the_overdue_movement(self, client):
        """Ten granted days move the deadline to 2026-09-15, which is strictly
        after the 2026-09-06 clock, so the movement returns to IN_TRANSIT with its
        overdue count cleared.

        PRD: "When the movement stands at `OVERDUE`, its `overdue_days` is no greater than 2 — the same two-day late grace that governs extension submission — and the freshly recomputed `transit_deadline_utc` now lies strictly after the current logical clock, the movement transitions `OVERDUE → IN_TRANSIT`, its `overdue_days` resets to 0, and the carrier's `overdue_movement_count` is recomputed."

        Design: Difficulty/non_linear_state_machine/overdue_movement_revives_to_in_transit_after_extension
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        world.set_clock("2026-09-06T00:00:00Z")
        world.run_sweep("daily overdue sweep")
        amendment = world.submit_extension(movement_id, requested_days=10)

        decided = validate_success(
            client.decide_amendment(
                amendment["id"],
                factories.amendment_approval_payload("CONGESTION_VERIFIED", 10),
                world.officer,
            ),
            200,
        )
        assert_field(decided, "status", "APPROVED", "amendment")
        assert_field(decided, "granted_days", 10, "amendment")
        assert_field(
            decided, "resulting_deadline_utc", "2026-09-15T00:00:00Z", "amendment"
        )

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, transit_status="IN_TRANSIT")
        assert_field(movement, "overdue_days", 0, "movement")
        assert_deadline(
            movement,
            anchor="2026-08-01T00:00:00Z",
            deadline="2026-09-15T00:00:00Z",
            transit_days_allowed=M1_TRANSIT_DAYS + 10,
            extension_days_granted=10,
        )
        assert_field(world.read_carrier(), "overdue_movement_count", 0, "carrier")
