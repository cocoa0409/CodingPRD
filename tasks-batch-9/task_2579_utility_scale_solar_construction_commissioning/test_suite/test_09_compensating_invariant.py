"""Round trips that must land back on exactly the value they started from.

Cancelling a pallet reservation and voiding a payroll line are both compensating
writes rather than rollbacks: each advances its parent's version a second time
while returning every counter to its pre-write value, with no drift and no stale
derived figure left behind. Once the compensation is in, the freed capacity is
genuinely free again.
"""

from test_helpers.assertions import (
    assert_hour_conservation,
    assert_pallet_conservation,
    assert_ratio,
    assert_week_totals,
    assert_zone_occupancy,
)
from test_helpers.fixtures import (
    cancel_delivery,
    create_payroll_week,
    create_project,
    create_yard_zone,
    post_labor_entry,
    read_labor_entry,
    read_payroll_week,
    read_project,
    read_yard_zone,
    reserve_delivery,
    void_labor_entry,
    yard_zone_version,
)

SIXTY_PALLETS = {
    "component_type": "MODULE",
    "unit_qty": 600,
    "pallets": 60,
    "planned_arrival_at": "2026-08-03T09:00:00Z",
    "laydown_window_start": "2026-08-03T00:00:00Z",
    "laydown_window_end": "2026-08-07T00:00:00Z",
}
# The replacement shipment covers the identical window and fills the zone.
HUNDRED_PALLETS = dict(
    SIXTY_PALLETS,
    unit_qty=1000,
    pallets=100,
    planned_arrival_at="2026-08-04T09:00:00Z",
)


def _empty_zone(api):
    """A hundred-position laydown zone with nothing reserved in it yet."""
    project = create_project(api, name="Mesquite Wash")
    zone = create_yard_zone(api, project["id"], zone_code="Y1", pallet_capacity=100)
    return project, zone


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/cancelling_a_reservation_restores_yard_pallet_positions_exactly
# ---------------------------------------------------------------------------
def test_a_fresh_zone_starts_with_every_position_available(api):
    """Nothing is reserved, so all hundred positions are available.

    PRD 3.3: "A new zone starts with `reserved_pallets` at 0 and therefore
    `available_pallets` equal to its `pallet_capacity`; creating a zone changes
    nothing at project level and leaves the project's `version` alone."

    Design: Difficulty/compensating_invariant/cancelling_a_reservation_restores_yard_pallet_positions_exactly
    """
    _project, zone = _empty_zone(api)

    assert_zone_occupancy(zone, reserved_pallets=0, available_pallets=100)


def test_the_reservation_moves_sixty_positions_and_conservation_holds_mid_flight(api):
    """Sixty reserved against forty available still sums to the zone's capacity.

    PRD 3.3: "Pallet positions behave as a conserved quantity. At every instant, a
    zone's `pallet_capacity` equals its `reserved_pallets` plus its
    `available_pallets`."

    Design: Difficulty/compensating_invariant/cancelling_a_reservation_restores_yard_pallet_positions_exactly
    """
    project, zone = _empty_zone(api)

    reserved = reserve_delivery(api, project["id"], zone["id"], **SIXTY_PALLETS)

    assert reserved["status"] == "RESERVED"
    mid_flight = read_yard_zone(api, zone["id"])
    assert_zone_occupancy(mid_flight, reserved_pallets=60, available_pallets=40)
    assert_pallet_conservation(mid_flight)


def test_the_cancellation_returns_both_counters_with_no_pallet_drift(api):
    """After the round trip the zone reads exactly as it did before the reservation.

    PRD 3.3: "The conservation property is strict rather than approximate: if a
    coordinator reserves a shipment and then cancels that same reservation, the
    zone's `reserved_pallets` returns to exactly the value it held before the
    reservation, with no pallet drift, while the zone's `version` has advanced by
    exactly 2 — once for the reservation and once for the release."

    Design: Difficulty/compensating_invariant/cancelling_a_reservation_restores_yard_pallet_positions_exactly
    """
    project, zone = _empty_zone(api)
    before = yard_zone_version(api, zone["id"])
    delivery = reserve_delivery(api, project["id"], zone["id"], **SIXTY_PALLETS)

    released = cancel_delivery(api, delivery["id"], cancel_reason="supplier slipped the ship date")

    assert released["status"] == "CANCELLED"
    after = read_yard_zone(api, zone["id"])
    assert_zone_occupancy(after, reserved_pallets=0, available_pallets=100)
    assert after["version"] == before + 2


def test_the_freed_positions_are_genuinely_free_for_a_larger_shipment(api):
    """A hundred-pallet shipment fits the identical window the cancelled one held.

    PRD 3.3: "`reserved_pallets` is the sum of `pallets` across every delivery
    pointing at that zone whose `status` is `RESERVED`, `ARRIVED` or `ACCEPTED`;
    deliveries that ended as `CANCELLED` or `REJECTED` are excluded and contribute
    nothing."

    Design: Difficulty/compensating_invariant/cancelling_a_reservation_restores_yard_pallet_positions_exactly
    """
    project, zone = _empty_zone(api)
    delivery = reserve_delivery(api, project["id"], zone["id"], **SIXTY_PALLETS)
    cancel_delivery(api, delivery["id"])

    replacement = reserve_delivery(api, project["id"], zone["id"], **HUNDRED_PALLETS)

    assert replacement["status"] == "RESERVED"
    assert_zone_occupancy(
        read_yard_zone(api, zone["id"]), reserved_pallets=100, available_pallets=0
    )


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/voiding_a_labor_entry_restores_certified_payroll_hours_exactly
# ---------------------------------------------------------------------------
AT_SCALE = {"paid_rate_cents": 4500, "fringe_rate_cents": 500, "prevailing_rate_cents": 5000}


def _week_with_one_apprentice(api):
    """An open week whose only line is eight apprentice hours."""
    project = create_project(
        api,
        name="Palo Verde Flats",
        prevailing_wage_election="REMEDIABLE",
        apprenticeship_basis="PROJECT_AGGREGATE",
        apprenticeship_min_pct=15.00,
    )
    week = create_payroll_week(api, project["id"], week_start_date="2026-08-03")
    post_labor_entry(
        api,
        week["id"],
        worker_ref="W-501",
        classification="ELECTRICIAN",
        is_apprentice=True,
        hours=8.00,
        work_date="2026-08-03",
        **AT_SCALE,
    )
    return project, week


def _add_ten_journeyworker_hours(api, week_id):
    """The line that will later be voided again."""
    return post_labor_entry(
        api,
        week_id,
        worker_ref="W-502",
        classification="OPERATOR",
        is_apprentice=False,
        hours=10.00,
        work_date="2026-08-04",
        **AT_SCALE,
    )


def test_a_single_apprentice_line_makes_the_week_wholly_apprentice(api):
    """Eight of eight hours is a hundred percent, on a one-line week.

    PRD 3.8: "`apprentice_pct` is `apprentice_hours` divided by `total_hours`,
    multiplied by 100 and rounded half up to two decimal places, and is 0 whenever
    `total_hours` is 0."

    Design: Difficulty/compensating_invariant/voiding_a_labor_entry_restores_certified_payroll_hours_exactly
    """
    _project, week = _week_with_one_apprentice(api)

    baseline = read_payroll_week(api, week["id"])

    assert_week_totals(
        baseline,
        total_hours=8.00,
        journeyworker_hours=0.00,
        apprentice_hours=8.00,
        apprentice_pct=100.00,
    )
    assert baseline["entry_count"] == 1
    assert_hour_conservation(baseline)


def test_the_second_line_dilutes_the_share_and_lifts_both_project_rollups(api):
    """Ten journeyworker hours take the week to eighteen and the share to 44.44.

    PRD 3.8: "The week's `version` increments by 1, and the project's
    `total_labor_hours` and `apprentice_labor_hours` — the sums of the
    corresponding week figures across every week of the project, each rounded half
    up to two decimal places — are recomputed with the project's `version`
    incremented by 1."

    Design: Difficulty/compensating_invariant/voiding_a_labor_entry_restores_certified_payroll_hours_exactly
    """
    project, week = _week_with_one_apprentice(api)

    _add_ten_journeyworker_hours(api, week["id"])

    # 8 / 18 * 100 == 44.444..., which rounds half up to 44.44.
    diluted = read_payroll_week(api, week["id"])
    assert_week_totals(
        diluted,
        total_hours=18.00,
        journeyworker_hours=10.00,
        apprentice_hours=8.00,
        apprentice_pct=44.44,
    )
    assert diluted["entry_count"] == 2
    rolled_up = read_project(api, project["id"])
    assert_ratio(rolled_up["total_labor_hours"], 18.00, "total_labor_hours")
    assert_ratio(rolled_up["apprentice_labor_hours"], 8.00, "apprentice_labor_hours")


def test_the_void_restores_every_week_counter_to_its_pre_post_value(api):
    """The week is back to eight hours in one entry, and the invariant still holds.

    PRD 3.8: "The exactness matters: after a line is posted and then voided, all
    six of those ledger figures equal precisely the values they held before the
    post."

    Design: Difficulty/compensating_invariant/voiding_a_labor_entry_restores_certified_payroll_hours_exactly
    """
    _project, week = _week_with_one_apprentice(api)
    journeyworker = _add_ten_journeyworker_hours(api, week["id"])

    voided = void_labor_entry(
        api, journeyworker["id"], void_reason="hours booked to the wrong project"
    )

    assert voided["status"] == "VOIDED"
    assert read_labor_entry(api, journeyworker["id"])["status"] == "VOIDED"
    restored = read_payroll_week(api, week["id"])
    assert_week_totals(
        restored, total_hours=8.00, journeyworker_hours=0.00, apprentice_hours=8.00
    )
    assert restored["entry_count"] == 1
    assert_hour_conservation(restored)


def test_the_derived_share_is_recomputed_rather_than_left_stale(api):
    """The share returns to 100.00; the compensating write does not keep 44.44.

    PRD 3.8: "The week's `total_hours`, `apprentice_hours`, `journeyworker_hours`,
    `apprentice_pct` and `entry_count` are recomputed with the week's `version`
    incremented by 1, and the project's `total_labor_hours` and
    `apprentice_labor_hours` are recomputed with the project's `version`
    incremented by 1; the line's own `version` also increments by 1."

    Design: Difficulty/compensating_invariant/voiding_a_labor_entry_restores_certified_payroll_hours_exactly
    """
    _project, week = _week_with_one_apprentice(api)
    journeyworker = _add_ten_journeyworker_hours(api, week["id"])
    assert_ratio(read_payroll_week(api, week["id"])["apprentice_pct"], 44.44, "apprentice_pct")

    void_labor_entry(api, journeyworker["id"], void_reason="hours booked to the wrong project")

    recomputed = read_payroll_week(api, week["id"])
    assert_ratio(recomputed["apprentice_pct"], 100.00, "apprentice_pct")
    assert recomputed["apprentice_pct"] != 44.44


def test_no_hours_are_left_stranded_one_level_up(api):
    """The project's two rollups come back to eight hours as well.

    PRD 3.8: "Voided lines leave the ledger entirely and contribute nothing to any
    later computation."

    Design: Difficulty/compensating_invariant/voiding_a_labor_entry_restores_certified_payroll_hours_exactly
    """
    project, week = _week_with_one_apprentice(api)
    journeyworker = _add_ten_journeyworker_hours(api, week["id"])

    void_labor_entry(api, journeyworker["id"], void_reason="hours booked to the wrong project")

    reconciled = read_project(api, project["id"])
    assert_ratio(reconciled["total_labor_hours"], 8.00, "total_labor_hours")
    assert_ratio(reconciled["apprentice_labor_hours"], 8.00, "apprentice_labor_hours")
