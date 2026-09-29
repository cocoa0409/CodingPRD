"""Discharge frees a bed through three hops and deliberately stops short of an offer.

Losing an occupant moves a bed count, which moves the free-bed count, which moves
the unit's posture. The chain stops there: the waiting applicant is offered the
bed by the next nightly run, not by the discharge itself.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx


def _single_bed_unit_with_someone_waiting(api):
    """One occupied single-bed unit, one applicant queued behind the occupant."""
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=1
    )
    second = fx.queue_second_applicant(
        api,
        scenario,
        application_received_date="2026-08-02",
        service_days=700,
        service_connected_disability_pct=30,
        state_residency_years=9,
    )
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    return scenario, second["entry"]


def test_a_unit_with_no_free_bed_is_restricted_before_the_discharge(api):
    """A full unit is restricted at exactly zero free beds.

    Per the PRD: "Otherwise, if `available_bed_count` is zero or less, the posture
    is `RESTRICTED`; note the boundary, which keys on "zero or fewer", so a unit
    with exactly zero free beds is already restricted."

    Design: Difficulty/transitive_cascade/discharge_cascade_bed_posture_then_waitlist_offer
    """
    scenario, _entry = _single_bed_unit_with_someone_waiting(api)

    unit = fx.read_unit(api, scenario.unit_id)
    assert unit["available_bed_count"] == 0
    assert unit["operational_posture"] == "RESTRICTED"


def test_discharge_frees_the_bed_and_recomputes_the_posture_to_open(api):
    """Releasing the occupant walks the count, the free-bed figure and the posture in order.

    Per the PRD: "The unit-side cascade then runs three hops: whichever count the
    resident occupied falls by 1 — `occupied_bed_count` when the resident was
    `ADMITTED`, `held_bed_count` when the resident was `HOSPITALIZED` — and the
    unit's `version` increments; because that count fell, `available_bed_count`
    rises by 1; and because `available_bed_count` is now at least 1, the unit's
    `operational_posture` is recomputed toward `OPEN`, which it reaches when the
    unit's `certification_status` is `CERTIFIED`."

    Design: Difficulty/transitive_cascade/discharge_cascade_bed_posture_then_waitlist_offer
    """
    scenario, _entry = _single_bed_unit_with_someone_waiting(api)

    resident = validate_success(
        fx.discharge(api, scenario.resident_id, "2026-08-10", "VOLUNTARY"), 200
    )

    assert resident["occupancy_status"] == "DISCHARGED"
    assert resident["billing_status"] == "CLOSED"
    assert resident["discharge_reason"] == "VOLUNTARY"

    unit = fx.read_unit(api, scenario.unit_id)
    assert unit["occupied_bed_count"] == 0
    assert unit["held_bed_count"] == 0
    assert unit["available_bed_count"] == 1
    assert unit["operational_posture"] == "OPEN"
    assert fx.read_home(api, scenario.home_id)["active_resident_count"] == 0


def test_discharge_itself_offers_the_freed_bed_to_nobody(api):
    """The applicant waiting behind the discharged resident is still merely active.

    Per the PRD: "Crucially, discharge itself makes **no** bed offer: the freed bed
    is offered only by the offer step of the next nightly checkpoint, which is
    precisely why the posture recomputation to `OPEN` matters — an offer requires
    an `OPEN` unit."

    Design: Difficulty/transitive_cascade/discharge_cascade_bed_posture_then_waitlist_offer
    """
    scenario, entry = _single_bed_unit_with_someone_waiting(api)

    validate_success(fx.discharge(api, scenario.resident_id, "2026-08-10", "VOLUNTARY"), 200)

    rows = {row["id"]: row for row in fx.read_waitlist_entries_for_unit(api, scenario.unit_id)}
    assert rows[entry["id"]]["status"] == "ACTIVE"
    assert rows[entry["id"]]["offer_expires_at"] is None


def test_the_next_nightly_run_offers_the_freed_bed_with_a_seven_day_window(api):
    """Once the unit is open, the checkpoint hands the bed to the head of the queue.

    Per the PRD: "An `ACTIVE` entry moves to `OFFERED` when four conditions all
    hold: its unit's `operational_posture` is `OPEN`, that unit has at least one
    free bed in `available_bed_count`, the entry itself sits at `queue_position` 1
    on that unit, and no other entry on that unit is already `OFFERED`."

    Design: Difficulty/transitive_cascade/discharge_cascade_bed_posture_then_waitlist_offer
    """
    scenario, entry = _single_bed_unit_with_someone_waiting(api)
    validate_success(fx.discharge(api, scenario.resident_id, "2026-08-10", "VOLUNTARY"), 200)

    fx.census_run(api, "2026-08-10", scenario.home_id)

    rows = {row["id"]: row for row in fx.read_waitlist_entries_for_unit(api, scenario.unit_id)}
    offered = rows[entry["id"]]
    assert offered["status"] == "OFFERED"
    assert offered["offer_expires_at"].startswith("2026-08-17T00:00:00"), (
        f"expected the offer window to close 2026-08-17, got {offered['offer_expires_at']!r}"
    )
    assert offered["queue_position"] == 1
