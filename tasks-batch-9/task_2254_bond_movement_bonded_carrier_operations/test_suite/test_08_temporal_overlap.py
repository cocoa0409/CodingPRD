"""Two overlap resources with deliberately opposite interval conventions:
examination bays are half-open, single-transaction bond windows are closed."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_deadline,
    assert_field,
    assert_ledger_stream,
    assert_money,
    assert_movement_state,
)
from test_helpers.fixtures import (
    M1_OBLIGATION,
    M1_TRANSIT_DAYS,
    build_carrier_without_bond,
    build_registered_world,
)


class TestExamBayWindowsAreHalfOpen:
    """A one-bay port refuses a genuinely overlapping window and accepts one that
    merely abuts the occupied window's end."""

    def _one_bay_port_with_an_open_window(self, client):
        world = build_registered_world(client, port_aliases=["ny", "la"])
        movement_id = world.file_movement("MAN-0004", destination="la")
        world.depart(movement_id, "SEAL-400")
        world.set_clock("2026-08-03T00:00:00Z")
        occupied = world.place_scheduled_hold(
            movement_id,
            "2026-08-05T08:00:00Z",
            "2026-08-05T12:00:00Z",
            port="la",
            hold_type="EXAM_NII",
            reason_code="RANDOM_SELECTION",
        )
        return world, movement_id, occupied

    def test_a_window_that_genuinely_overlaps_the_single_bay_is_refused(self, client):
        """The 11:00-13:00 candidate starts before the occupied 08:00-12:00 window
        ends, so the port's only bay is already taken.

        PRD: "Occupancy is measured against the candidate window: the system counts the examination holds at the candidate's port whose `status` is `OPEN` and whose `hold_type` is `EXAM_NII` or `EXAM_PHYSICAL`, keeping those whose window overlaps the candidate's."

        Design: Difficulty/resource_temporal_overlap/exam_bay_windows_are_half_open_so_touching_windows_share_no_slot
        """
        world, movement_id, occupied = self._one_bay_port_with_an_open_window(client)

        response = client.place_hold(
            factories.scheduled_hold_payload(
                movement_id,
                world.ports["la"],
                "2026-08-05T11:00:00Z",
                "2026-08-05T13:00:00Z",
            ),
            world.officer,
        )
        validate_error(response, api_errors.ERR_EXAM_CAPACITY_EXCEEDED)

        assert_field(world.read_hold(occupied["id"]), "status", "OPEN", "hold")
        assert_field(world.read_port("la"), "open_hold_count", 1, "port")

    def test_a_window_that_only_touches_the_occupied_end_is_admitted(self, client):
        """The 12:00-16:00 candidate begins exactly where the occupied window ends,
        which is no overlap at all, so the single bay hosts it and the port carries
        two open holds.

        PRD: "Windows are **half-open** — an existing hold overlaps the candidate exactly when the existing start falls strictly before the candidate's end **and** the candidate's start falls strictly before the existing end — so two windows that merely touch at a single endpoint do **not** conflict and do not consume the same slot."

        Design: Difficulty/resource_temporal_overlap/exam_bay_windows_are_half_open_so_touching_windows_share_no_slot
        """
        world, movement_id, occupied = self._one_bay_port_with_an_open_window(client)

        hold = validate_success(
            client.place_hold(
                factories.scheduled_hold_payload(
                    movement_id,
                    world.ports["la"],
                    "2026-08-05T12:00:00Z",
                    "2026-08-05T16:00:00Z",
                ),
                world.officer,
            ),
            201,
        )
        assert_field(hold, "status", "OPEN", "hold")
        assert_field(hold, "scheduled_start", "2026-08-05T12:00:00Z", "hold")
        assert_field(hold, "scheduled_end", "2026-08-05T16:00:00Z", "hold")

        assert_field(world.read_hold(occupied["id"]), "status", "OPEN", "hold")
        assert_field(world.read_port("la"), "open_hold_count", 2, "port")

        movement = world.read_movement(movement_id)
        assert_movement_state(movement, custody_status="EXAM_HOLD")
        assert_deadline(movement, deadline="2026-09-05T00:00:00Z")


class TestSingleTransactionWindowsAreClosed:
    """A single-transaction bond's window includes both endpoints, so a filing at
    the instant the first window ends collides — until the first is cancelled."""

    def _stb_bond_with_one_open_window(self, client):
        world = build_carrier_without_bond(client)
        bond_id = world.underwrite_bond(
            factories.single_transaction_bond_payload(
                world.carrier_id, surety_code="SUR-400"
            )
        )
        first = world.file_movement("MAN-0005", bond_id=bond_id)
        world.set_clock("2026-09-05T00:00:00Z")
        return world, bond_id, first

    def _second_filing(self, world, bond_id):
        return world.client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0006",
                bond_id=bond_id,
            ),
            world.carrier,
        )

    def test_a_window_starting_at_the_first_windows_last_instant_collides(self, client):
        """At 2026-09-05, exactly the end of the first movement's closed window, the
        second filing on the same single-transaction bond is refused.

        PRD: "Because the interval is closed, two windows that merely touch at a single endpoint **do** collide — a distinction that matters, because the examination-window rule of §3.6 uses the opposite convention."

        Design: Difficulty/resource_temporal_overlap/single_transaction_bond_windows_are_closed_and_free_up_on_cancellation
        """
        world, bond_id, first = self._stb_bond_with_one_open_window(client)

        validate_error(
            self._second_filing(world, bond_id), api_errors.ERR_STB_WINDOW_CONFLICT
        )

        assert_movement_state(world.read_movement(first), transit_status="FILED")
        assert_bond_amounts(
            world.read_bond(bond_id),
            obligated=M1_OBLIGATION,
            available=49958.25,
            open_movement_count=1,
        )

    def test_cancelling_the_first_movement_frees_the_window_for_the_retry(self, client):
        """A CANCELLED movement is not one of the statuses a window can collide
        with, so the identical retry is accepted and earns its own 35 days from the
        2026-09-05 filing instant.

        PRD: "Its window is the **closed** interval from `filed_at` through `transit_deadline_utc` inclusive at both ends, and a new filing is refused when that interval collides with the window of another movement on the same bond whose `transit_status` is `FILED`, `IN_TRANSIT`, `OVERDUE`, `ARRIVED`, or `EXPORTED`."

        Design: Difficulty/resource_temporal_overlap/single_transaction_bond_windows_are_closed_and_free_up_on_cancellation
        """
        world, bond_id, first = self._stb_bond_with_one_open_window(client)
        self._second_filing(world, bond_id)

        cancelled = world.cancel(first, "SHIPPER_WITHDREW")
        assert_movement_state(cancelled, transit_status="CANCELLED")
        assert_field(cancelled, "cancellation_reason", "SHIPPER_WITHDREW", "movement")

        retry = validate_success(self._second_filing(world, bond_id), 201)
        assert_movement_state(retry, transit_status="FILED")
        assert_field(retry, "filed_at", "2026-09-05T00:00:00Z", "movement")
        assert_deadline(
            retry,
            deadline="2026-10-10T00:00:00Z",
            transit_days_allowed=M1_TRANSIT_DAYS,
        )
        assert_money(retry["obligation_amount"], M1_OBLIGATION, "obligation_amount")

        assert_bond_amounts(
            world.read_bond(bond_id),
            obligated=M1_OBLIGATION,
            available=49958.25,
            status="ACTIVE",
            open_movement_count=1,
        )
        assert_ledger_stream(
            world.ledger_entries(bond_id=bond_id),
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
                {
                    "entry_type": "OBLIGATE",
                    "amount": M1_OBLIGATION,
                    "balance_after": M1_OBLIGATION,
                    "reason_code": "MOVEMENT_FILED",
                },
            ],
        )
