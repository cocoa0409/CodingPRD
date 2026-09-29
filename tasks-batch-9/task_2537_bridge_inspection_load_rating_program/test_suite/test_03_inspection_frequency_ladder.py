"""
Inspection frequency: a base tier chosen first, then floors applied as minima.

PRD §2.11: "The routine inspection cycle, `inspection_interval_months`, is a
nested ladder over four independent regulatory drivers, evaluated in a pinned
order: a base tier is selected first, then each floor is applied as a minimum in
the order written."
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import program_admin_headers


def _ridge_viaduct(client):
    """
    A modern, well-rated, low-traffic fracture-critical viaduct: every extension
    test passes on exposure and build date, so only the fracture-critical floor
    can bring the cycle back down.
    """
    payload = f.bridge_payload(
        "STR-000002",
        name="Ridge Viaduct",
        year_built=2005,
        adt=4000,
        fracture_critical=True,
        initial_deck_rating=8,
        initial_superstructure_rating=8,
        initial_substructure_rating=8,
    )
    return fx.create_bridge(client, payload)


def _patch(client, bridge_id, payload):
    """Revise one editable inventory attribute."""
    return validate_success(
        client.patch_bridge(bridge_id, payload, program_admin_headers()), 200
    )


def test_fracture_critical_floor_overrides_the_forty_eight_month_extension(
    client, roster
):
    """
    The structure earns the 48-month extension on condition, build date and
    traffic, and the fracture-critical floor then caps it at 12 months.

    PRD §2.11: "if the structure satisfies all three extension tests at once —
    `min_nbi_rating` of at least 7, `year_built` of 1990 or later, and `adt` of at
    most 5000 — the base extends to 48 months, four years between routine
    inspections."
    PRD §2.11: "A structure with `fracture_critical` set to true is capped at 12
    months."
    PRD §2.11: "`next_inspection_due_date` is `last_routine_inspection_date`
    advanced by `inspection_interval_months`; before the first routine acceptance
    the base date is the structure's creation date."

    Design: Difficulty/combinatorial_formula/inspection_interval_nested_min_max_fracture_critical_extended
    """
    structure = _ridge_viaduct(client)

    assert structure["min_nbi_rating"] == 8
    assert structure["fracture_critical"] is True
    assert structure["inspection_interval_months"] == c.INTERVAL_FLOOR_FRACTURE_CRITICAL
    assert structure["inspection_interval_months"] == 12
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2027-09-01", "next_inspection_due_date"
    )


def test_clearing_the_fracture_critical_flag_releases_the_full_extension(
    client, roster
):
    """
    Once the floor is removed the base tier alone governs, so the cycle jumps
    from one year to four and the due date moves out by three further years.

    PRD §2.11: "Three floors then tighten the base, each applied as a minimum
    against the running interval."
    PRD §3.1: "Each such edit is a real mutation: it re-evaluates
    `inspection_interval_months`, `underwater_interval_months`,
    `next_inspection_due_date` and `next_underwater_due_date`, and increments the
    structure's `version` by one."

    Design: Difficulty/combinatorial_formula/inspection_interval_nested_min_max_fracture_critical_extended
    """
    structure = _ridge_viaduct(client)

    revised = _patch(client, structure["id"], {"fracture_critical": False})

    assert revised["fracture_critical"] is False
    assert revised["inspection_interval_months"] == c.INTERVAL_EXTENDED_MONTHS
    assert revised["inspection_interval_months"] == 48
    a.assert_date_equals(
        revised["next_inspection_due_date"], "2030-09-01", "next_inspection_due_date"
    )
    a.assert_version_advanced_by(
        revised["version"], structure["version"], 1, "bridge"
    )


def test_one_extra_vehicle_a_day_costs_the_extension_and_halves_the_cycle(
    client, roster
):
    """
    The extension is all-or-nothing: with the fracture-critical floor gone, an
    average daily traffic count of 5001 fails the exposure test and the base
    falls back to the standard two-year cycle.

    PRD §2.11: "The extension is all-or-nothing on exposure: a structure with
    excellent ratings and a modern build date but an average daily traffic count
    of 5001 falls back to the standard two-year cycle."
    PRD §2.11: "Failing either the poor-condition test or the extension test, the
    base is the standard 24 months."

    Design: Difficulty/combinatorial_formula/inspection_interval_nested_min_max_fracture_critical_extended
    """
    structure = _ridge_viaduct(client)
    _patch(client, structure["id"], {"fracture_critical": False})

    revised = _patch(client, structure["id"], {"adt": 5001})

    assert revised["adt"] == 5001
    assert revised["inspection_interval_months"] == c.INTERVAL_STANDARD_MONTHS
    assert revised["inspection_interval_months"] == 24
    a.assert_date_equals(
        revised["next_inspection_due_date"], "2028-09-01", "next_inspection_due_date"
    )
    a.assert_version_advanced_by(
        revised["version"], structure["version"], 2, "bridge"
    )


def test_the_underwater_track_stays_absent_through_every_routine_change(
    client, roster
):
    """
    The underwater cycle is computed on its own inputs, so a structure without
    submerged elements keeps a null underwater interval and a null underwater due
    date no matter how the routine ladder moves.

    PRD §2.11: "The underwater track is computed independently rather than
    derived from the routine interval. A structure with `underwater_elements`
    false has no underwater cycle at all and its `underwater_interval_months` is
    null."
    PRD §2.11: "`next_underwater_due_date` is `last_underwater_inspection_date`
    advanced by `underwater_interval_months`, again falling back to the creation
    date before the first underwater acceptance, and null whenever
    `underwater_interval_months` is null."

    Design: Difficulty/combinatorial_formula/inspection_interval_nested_min_max_fracture_critical_extended
    """
    structure = _ridge_viaduct(client)
    assert structure["underwater_elements"] is False
    assert structure["underwater_interval_months"] is None
    assert structure["next_underwater_due_date"] is None

    after_flag = _patch(client, structure["id"], {"fracture_critical": False})
    assert after_flag["underwater_interval_months"] is None
    assert after_flag["next_underwater_due_date"] is None

    after_traffic = _patch(client, structure["id"], {"adt": 5001})
    assert after_traffic["underwater_interval_months"] is None
    assert after_traffic["next_underwater_due_date"] is None
