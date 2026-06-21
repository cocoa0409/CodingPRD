"""Transitive cascades: a depth-3 dispose destruction down the genealogy, and the
depth-2 CCP-excursion auto-hold cascade.

Queue A — Difficulty/transitive_cascade.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated,
    setup_three_hop_genealogy, issue_hold, resolve_hold,
    setup_released_lot_for_readings, post_reading,
    TEST_USERS,
)

QM = TEST_USERS["quality_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/dispose_cascade_three_hop_genealogy
# ---------------------------------------------------------------------------

def test_hold_covered_set_counts_full_downstream_genealogy():
    """PRD 3.6: "The covered set is the target lot together with every finished lot
    transitively downstream of the target through finalized consumed-lot edges — the
    one-down closure of the genealogy."
    PRD 3.6: "The hold records the number of distinct lots in the covered set as
    `held_lot_count`, a snapshot taken at issue time, and its `status` is set to
    `ACTIVE`."

    Design: Difficulty/transitive_cascade/dispose_cascade_three_hop_genealogy
    """
    facility, ingredient, lotR, f1_lot, f2_lot = setup_three_hop_genealogy()
    hold = issue_hold(facility["id"], lotR, reason="RECALL")
    # covered_set = { R, F1, F2 } -> 3 distinct lots.
    assert hold["held_lot_count"] == 3


def test_dispose_destroys_full_downstream_chain():
    """PRD 3.7: "Because the covered set already contains every finished lot
    transitively downstream of the target, this single pass destroys the directly held
    lot and all of its downstream descendants together — the transitive genealogy is
    destroyed as one unit."

    Design: Difficulty/transitive_cascade/dispose_cascade_three_hop_genealogy
    """
    facility, ingredient, lotR, f1_lot, f2_lot = setup_three_hop_genealogy()
    hold = issue_hold(facility["id"], lotR, reason="RECALL")
    resolve_hold(hold["id"], "DISPOSE", hold["version"])

    # F2 is two hops downstream of R (R -> F1 -> F2) and must be DESTROYED.
    f2 = validate_success(api_client.get_lot(f2_lot, QM), 200)
    assert f2["status"] == "DESTROYED"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/ccp_excursion_auto_hold_cascade
# ---------------------------------------------------------------------------

def test_excursion_breach_sets_lot_held():
    """PRD 3.5: "Once a lot's `cumulative_excursion_minutes` strictly exceeds 120
    minutes, the system automatically issues a hold order against that lot with reason
    `TEMPERATURE_EXCURSION`."
    PRD 3.6: "A lot's `hold_status` is `HELD` whenever any active hold order covers it,
    directly or through genealogy, and `FREE` otherwise."

    Design: Difficulty/transitive_cascade/ccp_excursion_auto_hold_cascade
    """
    facility, ingredient, lot_id = setup_released_lot_for_readings(
        target_c=4, tolerance_c=2, clock_utc="2026-01-02T05:00:00Z",
        shelf_life_days=30, declared_allergen_codes=["FISH"])
    post_reading(lot_id, 8, "2026-01-02T00:00:00Z")              # DEVIATION, 0 min
    r2 = post_reading(lot_id, 8, "2026-01-02T02:10:00Z")         # +130 min DEVIATION
    assert r2["excursion_minutes"] == 130

    lot = validate_success(api_client.get_lot(lot_id, QM), 200)
    assert lot["cumulative_excursion_minutes"] == 130   # > 120
    assert lot["hold_status"] == "HELD"


def test_excursion_breach_auto_hold_carries_temperature_reason():
    """PRD 3.5: "Once a lot's `cumulative_excursion_minutes` strictly exceeds 120
    minutes, the system automatically issues a hold order against that lot with reason
    `TEMPERATURE_EXCURSION`."

    Design: Difficulty/transitive_cascade/ccp_excursion_auto_hold_cascade
    """
    facility, ingredient, lot_id = setup_released_lot_for_readings(
        target_c=4, tolerance_c=2, clock_utc="2026-01-02T05:00:00Z",
        shelf_life_days=30, declared_allergen_codes=["FISH"])
    post_reading(lot_id, 8, "2026-01-02T00:00:00Z")
    post_reading(lot_id, 8, "2026-01-02T02:10:00Z")              # cumulative 130 > 120

    data, meta = validate_paginated(
        api_client.list_hold_orders(QM, params={"target_lot_id": lot_id}))
    assert len(data) >= 1, "an automatic hold must exist for the breached lot"
    assert data[0]["reason"] == "TEMPERATURE_EXCURSION"
