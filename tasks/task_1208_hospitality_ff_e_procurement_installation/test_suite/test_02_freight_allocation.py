"""Queue A (depth) — freight mode thresholds and per-line allocation math.

- Provisional (at seal) allocates by declared-cube share; final (at receipt)
  allocates by received-units share; the two variants diverge on one shipment.
- The rounding contract rounds each line half-up first, then reconciles the
  signed residual to the largest raw share.
- The FCL/LTL mode boundary sits at exactly 67 m3 of consolidated cube.
"""
from test_helpers import (
    api_client, validate_success,
    run_pipeline, setup_two_pos_consolidating,
    transition_shipment, get_po_line,
    THRESHOLDS, TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]

# ── rule: dual_variant_calc ────────────────────────────────

_TWO_SPEC_RECIPE = [
    {
        "description": "Chair A", "brand_standard_ref": "MS-A",
        "quantity_per_room": 5, "room_count": 20,
        "unit_budget_cents": 1000, "unit_price_cents": 1000,
        "lead_time_days": 10,
        "quantity_ordered": 100, "declared_cube_m3": 30,
    },
    {
        "description": "Lamp B", "brand_standard_ref": "MS-B",
        "quantity_per_room": 3, "room_count": 20,
        "unit_budget_cents": 2000, "unit_price_cents": 2000,
        "lead_time_days": 10,
        "quantity_ordered": 60, "declared_cube_m3": 40,
    },
]


def test_provisional_freight_allocates_by_declared_cube_share(api):
    """PRD §2.11: "The **provisional allocation** distributes `freight_total_cents`
    across every non-cancelled PO line of every attached purchase order in
    proportion to declared cube: each line's raw share is the total freight
    multiplied by the line's `declared_cube_m3` divided by the sum of
    `declared_cube_m3` over all lines in the allocation set."
    PRD §2.11: "At seal, the shipment's `freight_mode` is `FCL` when its
    `total_cube_m3` — the sum of the `total_cube_m3` of its attached purchase
    orders — is at least 67 cubic meters; below that threshold the mode is `LTL`."
    Cube shares 30/70 and 40/70 of the flat 480000c FCL freight yield
    205714c and 274286c after half-up rounding (residual 0).

    Design: Difficulty/dual_variant_calc/freight_allocation_provisional_cube_vs_final_units
    """
    scenario = run_pipeline(
        name="P-DV2", budgeted_cents=8_000_000,
        line_specs=_TWO_SPEC_RECIPE, seal=True, depart=False,
    )
    shipment = scenario["shipment"]
    assert shipment["status"] == "SEALED"
    assert shipment["total_cube_m3"] == 70
    assert shipment["freight_mode"] == "FCL"
    assert shipment["freight_total_cents"] == 480000

    line_a, line_b = scenario["lines"]
    assert line_a["freight_alloc_provisional_cents"] == 205714
    assert line_b["freight_alloc_provisional_cents"] == 274286
    assert (
        line_a["freight_alloc_provisional_cents"]
        + line_b["freight_alloc_provisional_cents"]
        == 480000
    )


def test_final_freight_allocates_by_received_units_share(api):
    """PRD §2.11: "The **final allocation** runs at receipt with the identical
    procedure, except the basis is received units: each line's raw share uses its
    `qty_received` divided by the sum of `qty_received` over the allocation set,
    and the result is stored as `freight_alloc_final_cents`."
    PRD §2.11: "The same shipment yields different per-line freight under the two
    variants whenever declared cube proportions differ from received-unit
    proportions; at receipt, `actual_landed_cents` and each budget line's
    `actual_cents` switch to the final basis."
    Received-units shares 100/160 and 60/160 of the same 480000c yield 300000c
    and 180000c — different from the provisional cube-based split.

    Design: Difficulty/dual_variant_calc/freight_allocation_provisional_cube_vs_final_units
    """
    scenario = run_pipeline(
        name="P-DV2", budgeted_cents=8_000_000,
        line_specs=_TWO_SPEC_RECIPE, seal=True, depart=True,
        receipts=[[(0, 100, 0), (1, 60, 0)]],
    )
    transition_shipment(scenario["shipment"]["id"], "RECEIVED")

    line_a = get_po_line(scenario["lines"][0]["id"])
    line_b = get_po_line(scenario["lines"][1]["id"])
    assert line_a["freight_alloc_final_cents"] == 300000
    assert line_b["freight_alloc_final_cents"] == 180000
    assert (
        line_a["freight_alloc_final_cents"] + line_b["freight_alloc_final_cents"]
        == 480000
    )
    assert line_a["freight_alloc_provisional_cents"] == 205714
    assert line_b["freight_alloc_provisional_cents"] == 274286
    assert (
        line_a["freight_alloc_provisional_cents"]
        != line_a["freight_alloc_final_cents"]
    )
    assert (
        line_b["freight_alloc_provisional_cents"]
        != line_b["freight_alloc_final_cents"]
    )


# ── rule: combinatorial_formula ────────────────────────────

_THREE_SPEC_RECIPE = [
    {
        "description": "C1", "brand_standard_ref": "MS-C1",
        "quantity_per_room": 1, "room_count": 3,
        "unit_budget_cents": 1000, "unit_price_cents": 1000,
        "lead_time_days": 10,
        "quantity_ordered": 3, "declared_cube_m3": 3,
    },
    {
        "description": "C2", "brand_standard_ref": "MS-C2",
        "quantity_per_room": 2, "room_count": 13,
        "unit_budget_cents": 1000, "unit_price_cents": 1000,
        "lead_time_days": 10,
        "quantity_ordered": 26, "declared_cube_m3": 26,
    },
    {
        "description": "C3", "brand_standard_ref": "MS-C3",
        "quantity_per_room": 2, "room_count": 19,
        "unit_budget_cents": 1000, "unit_price_cents": 1000,
        "lead_time_days": 10,
        "quantity_ordered": 38, "declared_cube_m3": 38,
    },
]


def _sealed_three_line_shipment():
    scenario = run_pipeline(
        name="P-CF1", budgeted_cents=8_000_000,
        line_specs=_THREE_SPEC_RECIPE,
        attach=True, seal=False, depart=False,
    )
    shipment = transition_shipment(scenario["shipment"]["id"], "SEALED")
    lines = [get_po_line(l["id"]) for l in scenario["lines"]]
    return shipment, lines


def test_freight_rounding_rounds_each_line_half_up_first(api):
    """PRD §2.11: "Each line's share is rounded half-up to whole cents **first**;
    the signed residual — the total freight minus the sum of the rounded shares —
    is then added to the line with the largest raw (unrounded) share, with ties
    broken by the earliest line `created_at`."
    Cube shares 3/67, 26/67, 38/67 of 480000c give raw 21492.54 / 186268.66 /
    272238.81; the pinned round-each-first yields 21493 / 186269 / 272239 before
    residual reconciliation.

    Design: Difficulty/combinatorial_formula/freight_rounding_residual_to_largest_share
    """
    shipment, lines = _sealed_three_line_shipment()
    assert shipment["total_cube_m3"] == THRESHOLDS["FCL_CUBE_THRESHOLD_M3"]
    assert shipment["freight_mode"] == "FCL"
    assert shipment["freight_total_cents"] == 480000
    assert lines[0]["freight_alloc_provisional_cents"] == 21493
    assert lines[1]["freight_alloc_provisional_cents"] == 186269


def test_freight_residual_reconciled_to_largest_raw_share(api):
    """PRD §2.11: "the signed residual — the total freight minus the sum of the
    rounded shares — is then added to the line with the largest raw (unrounded)
    share, with ties broken by the earliest line `created_at`. Rounding each line
    before reconciling the residual is the pinned order; summing first and
    rounding once is not the contract and yields different cents."
    Rounded shares 21493 + 186269 + 272239 sum to 480001, so the residual -1
    lands on the largest raw share (line C3, raw 272238.81): 272238.

    Design: Difficulty/combinatorial_formula/freight_rounding_residual_to_largest_share
    """
    shipment, lines = _sealed_three_line_shipment()
    assert shipment["freight_total_cents"] == 480000
    assert lines[2]["freight_alloc_provisional_cents"] == 272238, (
        "largest raw share must absorb the -1 residual after round-each-first"
    )
    total = sum(l["freight_alloc_provisional_cents"] for l in lines)
    assert total == 480000, (
        f"provisional allocations must sum to the freight total; got {total}"
    )


# ── rule: boundary_precision_check ─────────────────────────

def _two_shipments_boundary_setup():
    return setup_two_pos_consolidating(
        po_specs=[
            {
                "description": "Bulk chairs", "brand_standard_ref": "MS-BC",
                "quantity_per_room": 5, "room_count": 20,
                "unit_budget_cents": 1000, "unit_price_cents": 1000,
                "quantity_ordered": 100, "declared_cube_m3": 67,
            },
            {
                "description": "Bulk lamps", "brand_standard_ref": "MS-BL",
                "quantity_per_room": 3, "room_count": 20,
                "unit_budget_cents": 1000, "unit_price_cents": 1000,
                "quantity_ordered": 60, "declared_cube_m3": 66,
            },
        ],
    )


def test_seal_at_exactly_67_cube_selects_fcl(api):
    """PRD §2.11: "At seal, the shipment's `freight_mode` is `FCL` when its
    `total_cube_m3` — the sum of the `total_cube_m3` of its attached purchase
    orders — is at least 67 cubic meters; below that threshold the mode is `LTL`.
    The `freight_total_cents` is a flat 480000 cents for `FCL`; for `LTL` it is
    9000 cents per cubic meter multiplied by `total_cube_m3`."
    A consolidated cube of exactly 67 m3 satisfies the >= threshold: FCL flat.

    Design: Difficulty/boundary_precision_check/seal_cube_threshold_fcl_vs_ltl
    """
    scenario = _two_shipments_boundary_setup()
    shipment_a = transition_shipment(scenario["shipments"][0]["id"], "SEALED")
    assert shipment_a["total_cube_m3"] == 67
    assert shipment_a["freight_mode"] == "FCL"
    assert shipment_a["freight_total_cents"] == 480000


def test_seal_one_cube_below_threshold_selects_ltl(api):
    """PRD §2.11: "At seal, the shipment's `freight_mode` is `FCL` when its
    `total_cube_m3` — the sum of the `total_cube_m3` of its attached purchase
    orders — is at least 67 cubic meters; below that threshold the mode is `LTL`.
    The `freight_total_cents` is a flat 480000 cents for `FCL`; for `LTL` it is
    9000 cents per cubic meter multiplied by `total_cube_m3`."
    At 66 m3 — one cubic meter under the threshold — the mode is LTL and the
    freight total is 66 x 9000 = 594000c, not the FCL flat 480000c.

    Design: Difficulty/boundary_precision_check/seal_cube_threshold_fcl_vs_ltl
    """
    scenario = _two_shipments_boundary_setup()
    shipment_b = transition_shipment(scenario["shipments"][1]["id"], "SEALED")
    assert shipment_b["total_cube_m3"] == 66
    assert shipment_b["freight_mode"] == "LTL"
    assert shipment_b["freight_total_cents"] == 66 * 9000
    assert shipment_b["freight_total_cents"] == 594000
