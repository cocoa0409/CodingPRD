"""When two refusals both apply, the earlier band wins: bond activity outranks
bond sufficiency, and seal integrity outranks timeliness."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import assert_bond_amounts, assert_deadline, assert_field
from test_helpers.fixtures import (
    M1_SEAL,
    M1_TRANSIT_DAYS,
    build_carrier_without_bond,
    build_departed_movement,
)

TINY_BOND = {"limit_amount": 30.00, "surety_code": "SUR-200"}


class TestBondActivityOutranksBondSufficiency:
    """A bond that is both suspended and too small fails on activity, never on
    arithmetic."""

    def test_suspended_bond_fails_on_activity_not_on_headroom(self, client):
        """A 30.00 bond cannot cover the 41.75 obligation, but because the surety
        has suspended it the filing is refused as inactive rather than
        insufficient.

        PRD: "On a filing, the bond's activity check (`ERR_BOND_NOT_ACTIVE`, band 10) is evaluated strictly **before** the bond's sufficiency check (`ERR_BOND_INSUFFICIENT`, band 14): a `SATURATED`, `SUSPENDED`, or `EXPIRED` bond fails on activity and never reaches the arithmetic."

        Design: Difficulty/priority_pair_validation_conflict/suspended_bond_beats_insufficient_bond_on_filing_rejected
        """
        world = build_carrier_without_bond(client)
        bond_id = world.underwrite_bond(
            factories.continuous_bond_payload(world.carrier_id, **TINY_BOND)
        )
        validate_success(
            client.patch_bond(
                bond_id, {"status": "SUSPENDED"}, world.surety_headers(bond_id)
            ),
            200,
        )

        response = client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0009",
                bond_id=bond_id,
            ),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_BOND_NOT_ACTIVE)

        suspended = world.read_bond(bond_id)
        assert_field(suspended, "status", "SUSPENDED", "bond")
        assert_bond_amounts(suspended, obligated=0.00, available=30.00)

        _rows, meta = world.movement_list(carrier_id=world.carrier_id)
        assert meta["total_count"] == 0, (
            "a refused filing must not leave a movement behind"
        )

    def test_the_same_filing_fails_on_headroom_once_the_bond_is_active(self, client):
        """With the suspension lifted the identical filing reaches the fiscal gate
        and is refused for insufficient headroom, which is the refusal the activity
        check was masking.

        PRD: "Exceeding the headroom is `ERR_BOND_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_bond_beats_insufficient_bond_on_filing_rejected
        """
        world = build_carrier_without_bond(client)
        bond_id = world.underwrite_bond(
            factories.continuous_bond_payload(world.carrier_id, **TINY_BOND)
        )

        response = client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0009",
                bond_id=bond_id,
            ),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_BOND_INSUFFICIENT)

        assert_bond_amounts(
            world.read_bond(bond_id), obligated=0.00, available=30.00, status="ACTIVE"
        )


class TestSealIntegrityOutranksTimeliness:
    """An amendment submitted late on a movement with a broken seal is refused for
    the seal, not for the calendar."""

    def test_broken_seal_beats_the_closed_extension_window(self, client):
        """At 2026-09-09 the extension window has already closed on the 2026-09-05
        deadline, yet the unresolved break is what the API reports.

        PRD: "All four are refused with `ERR_SEAL_INTEGRITY_UNRESOLVED`, and that refusal is evaluated before any timeliness or routing check, so a compromised container is stopped even when the filing is perfectly punctual."

        Design: Difficulty/priority_pair_validation_conflict/broken_seal_beats_expired_extension_window_on_amendment_rejected
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        world.set_clock("2026-08-10T00:00:00Z")
        world.record_seal_event(
            movement_id, "BROKEN_UNAUTHORIZED", M1_SEAL, factories.PORT_CHICAGO_CODE
        )
        world.set_clock("2026-09-09T00:00:00Z")

        version = world.read_movement(movement_id)["version"]
        response = client.submit_amendment(
            factories.extension_payload(movement_id, version, 5),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_SEAL_INTEGRITY_UNRESOLVED)

        movement = world.read_movement(movement_id)
        assert_deadline(
            movement,
            deadline="2026-09-05T00:00:00Z",
            transit_days_allowed=M1_TRANSIT_DAYS,
            extension_days_granted=0,
        )

        _rows, meta = world.amendments(movement_id)
        assert meta["total_count"] == 0, (
            "a refused submission must not leave an amendment request behind"
        )

    def test_the_closed_window_surfaces_once_the_seal_is_replaced(self, client):
        """A REPLACED event restores integrity, and the same late submission is then
        refused for standing past the deadline plus its two-day grace.

        PRD: "Timing: an `EXTENSION` may be submitted only while the logical clock stands at or before the movement's `transit_deadline_utc` advanced by a two-day late grace, so the extension window closes two days after the deadline and a later request is `ERR_TRANSIT_DEADLINE_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/broken_seal_beats_expired_extension_window_on_amendment_rejected
        """
        world = build_departed_movement(client)
        movement_id = world.movements["MAN-0001"]

        world.set_clock("2026-08-10T00:00:00Z")
        world.record_seal_event(
            movement_id, "BROKEN_UNAUTHORIZED", M1_SEAL, factories.PORT_CHICAGO_CODE
        )
        world.record_seal_event(
            movement_id, "REPLACED", "SEAL-101", factories.PORT_CHICAGO_CODE
        )
        assert_field(world.read_movement(movement_id), "seal_intact", True, "movement")

        world.set_clock("2026-09-09T00:00:00Z")
        version = world.read_movement(movement_id)["version"]
        response = client.submit_amendment(
            factories.extension_payload(movement_id, version, 5),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_TRANSIT_DEADLINE_PASSED)

        _rows, meta = world.amendments(movement_id)
        assert meta["total_count"] == 0, (
            "a refused submission must not leave an amendment request behind"
        )
