"""Two boundaries that are exactly one unit wide: an obligation equal to the
last cent of headroom, and an examination window that touches at one second."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_ledger_entry,
    assert_money,
    assert_movement_state,
)
from test_helpers.fixtures import (
    M1_OBLIGATION,
    M1_SEAL,
    M2_SEAL,
    build_carrier_without_bond,
    build_registered_world,
)

EXACT_BOND = {"limit_amount": 41.75, "surety_code": "SUR-300"}
HEAVY_CONSIGNMENT = {
    "cargo_value": 3900.00,
    "gross_weight_kg": 100.00,
    "package_count": 4,
}


class TestObligationEqualToHeadroom:
    """An obligation equal to the available amount is admitted, and the resulting
    zero headroom saturates the bond."""

    def test_obligation_equal_to_the_available_amount_is_admitted(self, client):
        """A 41.75 obligation against 41.75 of headroom leaves 0.00 available and
        moves the bond to SATURATED, which is the ordinary way it gets there.

        PRD: "Equality is permitted and is the ordinary way a bond arrives at `SATURATED`."

        Design: Difficulty/boundary_precision_check/obligation_exactly_equal_to_available_saturates_the_bond
        """
        world = build_carrier_without_bond(client)
        bond_id = world.underwrite_bond(
            factories.continuous_bond_payload(world.carrier_id, **EXACT_BOND)
        )

        movement = validate_success(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0011",
                    bond_id=bond_id,
                ),
                world.carrier,
            ),
            201,
        )
        assert_movement_state(movement, transit_status="FILED")
        assert_money(movement["obligation_amount"], M1_OBLIGATION, "obligation_amount")

        assert_bond_amounts(
            world.read_bond(bond_id),
            obligated=M1_OBLIGATION,
            available=0.00,
            status="SATURATED",
            open_movement_count=1,
        )

        entries = world.ledger_entries(bond_id=bond_id)
        assert len(entries) == 1, (
            f"one filing should write one ledger entry but the audit trail holds "
            f"{len(entries)}"
        )
        assert_ledger_entry(
            entries[0], amount=M1_OBLIGATION, balance_after=M1_OBLIGATION
        )

    def test_the_saturated_bond_refuses_the_next_filing_on_activity(self, client):
        """A second identical filing on the now-saturated bond is refused as
        inactive, because a SATURATED bond never reaches the arithmetic.

        PRD: "Before the filing is accepted, the carrier's `custodial_status` must be `ACTIVE` — a `SUSPENDED` or `REVOKED` carrier may neither file nor depart, and the refusal is `ERR_CARRIER_NOT_ACTIVE` — and the resolved bond's `status` must be `ACTIVE`, with `SATURATED`, `SUSPENDED`, and `EXPIRED` all refused as `ERR_BOND_NOT_ACTIVE`."

        Design: Difficulty/boundary_precision_check/obligation_exactly_equal_to_available_saturates_the_bond
        """
        world = build_carrier_without_bond(client)
        bond_id = world.underwrite_bond(
            factories.continuous_bond_payload(world.carrier_id, **EXACT_BOND)
        )
        world.file_movement("MAN-0011", bond_id=bond_id)

        response = client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0012",
                bond_id=bond_id,
            ),
            world.carrier,
        )
        validate_error(response, api_errors.ERR_BOND_NOT_ACTIVE)

        assert_bond_amounts(
            world.read_bond(bond_id),
            obligated=M1_OBLIGATION,
            available=0.00,
            status="SATURATED",
            open_movement_count=1,
        )
        assert len(world.ledger_entries(bond_id=bond_id)) == 1, (
            "a refused filing must not write a ledger entry"
        )


class TestExamWindowOverlapBoundary:
    """Two open windows fill a two-bay port for one second longer than a naive
    inclusive comparison would suggest."""

    def _two_movements_with_scheduled_holds(self, client):
        world = build_registered_world(client)
        first = world.file_movement("MAN-0001")
        second = world.file_movement("MAN-0002", **HEAVY_CONSIGNMENT)
        world.depart(first, M1_SEAL)
        world.depart(second, M2_SEAL)
        world.set_clock("2026-08-03T00:00:00Z")
        hold_a = world.place_scheduled_hold(
            first,
            "2026-08-05T08:00:00Z",
            "2026-08-05T12:00:00Z",
            hold_type="EXAM_NII",
            reason_code="RANDOM_SELECTION",
        )
        hold_b = world.place_scheduled_hold(
            second,
            "2026-08-05T10:00:00Z",
            "2026-08-05T14:00:00Z",
            hold_type="EXAM_NII",
            reason_code="RANDOM_SELECTION",
        )
        return world, first, hold_a, hold_b

    def test_candidate_starting_one_second_before_the_first_window_ends_is_refused(
        self, client
    ):
        """A candidate starting at 11:59:59 still overlaps the 08:00-12:00 window as
        well as the 10:00-14:00 window, so both of the port's two bays are taken.

        PRD: "When the overlapping open count has reached `exam_capacity_slots`, the hold is refused with `ERR_EXAM_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/exam_window_overlap_boundary_is_one_second_wide
        """
        world, movement_id, hold_a, hold_b = self._two_movements_with_scheduled_holds(
            client
        )

        response = client.place_hold(
            factories.scheduled_hold_payload(
                movement_id,
                world.ports["chicago"],
                "2026-08-05T11:59:59Z",
                "2026-08-05T16:00:00Z",
            ),
            world.officer,
        )
        validate_error(response, api_errors.ERR_EXAM_CAPACITY_EXCEEDED)

        assert_field(world.read_hold(hold_a["id"]), "status", "OPEN", "hold")
        assert_field(world.read_hold(hold_b["id"]), "status", "OPEN", "hold")
        assert_field(world.read_port("chicago"), "open_hold_count", 2, "port")

    def test_candidate_starting_exactly_when_the_last_window_ends_is_admitted(
        self, client
    ):
        """One second later, at 14:00:00, the candidate merely touches the
        10:00-14:00 window's exclusive end and touches nothing else, so it is
        admitted and the port carries three open holds.

        PRD: "Windows are **half-open** — an existing hold overlaps the candidate exactly when the existing start falls strictly before the candidate's end **and** the candidate's start falls strictly before the existing end — so two windows that merely touch at a single endpoint do **not** conflict and do not consume the same slot."

        Design: Difficulty/boundary_precision_check/exam_window_overlap_boundary_is_one_second_wide
        """
        world, movement_id, hold_a, hold_b = self._two_movements_with_scheduled_holds(
            client
        )

        hold = validate_success(
            client.place_hold(
                factories.scheduled_hold_payload(
                    movement_id,
                    world.ports["chicago"],
                    "2026-08-05T14:00:00Z",
                    "2026-08-05T16:00:00Z",
                ),
                world.officer,
            ),
            201,
        )
        assert_field(hold, "status", "OPEN", "hold")
        assert_field(hold, "hold_type", "EXAM_PHYSICAL", "hold")
        assert_field(hold, "scheduled_start", "2026-08-05T14:00:00Z", "hold")

        assert_field(world.read_hold(hold_a["id"]), "status", "OPEN", "hold")
        assert_field(world.read_hold(hold_b["id"]), "status", "OPEN", "hold")
        assert_field(world.read_port("chicago"), "open_hold_count", 3, "port")

        movement = world.read_movement(movement_id)
        assert_movement_state(
            movement, transit_status="IN_TRANSIT", custody_status="EXAM_HOLD"
        )
