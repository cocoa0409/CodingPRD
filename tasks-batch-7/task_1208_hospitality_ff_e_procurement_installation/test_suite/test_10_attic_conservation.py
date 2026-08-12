"""Queue A (depth) — compensating invariant: physical units per PO line are
conserved across an attic IN / OUT pair of transfers.

Setup: line 50 x 10000c (cube 10) received 50 with 10 damaged, so
qty_installable 40, qty_damaged_unresolved 10, qty_installed 0, qty_attic 0.
"""
from test_helpers import (
    api_client, validate_success,
    run_pipeline, get_po_line, current_po_line_version,
    assert_po_line_pool_invariant,
    TEST_USERS,
)

WR = TEST_USERS["warehouse_receiver_headers"]


def _damaged_received_line():
    return run_pipeline(
        name="P-CI1", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Dresser", "brand_standard_ref": "MS-DR",
            "quantity_per_room": 1, "room_count": 50,
            "unit_budget_cents": 10000, "unit_price_cents": 10000,
            "lead_time_days": 7,
            "quantity_ordered": 50, "declared_cube_m3": 10,
            "spec_overrides": {"attic_min_qty": 10, "attic_max_qty": 40},
        }],
        receipts=[[(0, 50, 10)]],
    )


def test_attic_transfer_in_conserves_physical_units(api):
    """PRD §3.4: "and `qty_installable` — the units available for installation or
    attic transfer — is what remains: `qty_received` less
    `qty_damaged_unresolved`, less `qty_damaged_credited`, less `qty_installed`,
    less `qty_attic`."
    PRD §3.8: "Each accepted movement appends an immutable attic stock movement
    row that records `resulting_installable` and `resulting_attic` — the line's
    two pools immediately after the move — and bumps the line's `version`."
    IN 5 moves five units installable -> attic: 35 + 5 + 0 + 10 + 0 still equals
    the 50 received units.

    Design: Difficulty/compensating_invariant/attic_units_conservation_in_out_pair
    """
    scenario = _damaged_received_line()
    line_id = scenario["lines"][0]["id"]

    movement = validate_success(
        api_client.create_attic_transfer(
            line_id,
            {"direction": "IN", "quantity": 5,
             "expected_po_line_version": current_po_line_version(line_id)},
            WR,
        ),
        201,
    )
    assert movement["resulting_installable"] == 35
    assert movement["resulting_attic"] == 5

    line = get_po_line(line_id)
    assert_po_line_pool_invariant(line)
    assert (
        line["qty_installable"] + line["qty_attic"] + line["qty_installed"]
        + line["qty_damaged_unresolved"] + line["qty_damaged_credited"]
        == line["qty_received"] == 50
    )


def test_attic_transfer_out_after_in_still_conserves_units(api):
    """PRD §3.4: "and `qty_installable` — the units available for installation or
    attic transfer — is what remains: `qty_received` less
    `qty_damaged_unresolved`, less `qty_damaged_credited`, less `qty_installed`,
    less `qty_attic`."
    PRD §3.8: "Each movement carries a `direction` — `IN` moves units from
    installable to attic, `OUT` returns them from attic to installable,
    `WRITE_OFF` destroys attic units"
    The IN 5 / OUT 2 pair lands at installable 37, attic 3, and
    37 + 3 + 0 + 10 + 0 == 50 == qty_received at every step.

    Design: Difficulty/compensating_invariant/attic_units_conservation_in_out_pair
    """
    scenario = _damaged_received_line()
    line_id = scenario["lines"][0]["id"]

    validate_success(
        api_client.create_attic_transfer(
            line_id,
            {"direction": "IN", "quantity": 5,
             "expected_po_line_version": current_po_line_version(line_id)},
            WR,
        ),
        201,
    )
    movement = validate_success(
        api_client.create_attic_transfer(
            line_id,
            {"direction": "OUT", "quantity": 2,
             "expected_po_line_version": current_po_line_version(line_id)},
            WR,
        ),
        201,
    )
    assert movement["resulting_installable"] == 37
    assert movement["resulting_attic"] == 3

    line = get_po_line(line_id)
    assert_po_line_pool_invariant(line)
    assert line["qty_installable"] == 37
    assert line["qty_attic"] == 3
    assert line["qty_installed"] == 0
    assert line["qty_damaged_unresolved"] == 10
    assert line["qty_received"] == 50
