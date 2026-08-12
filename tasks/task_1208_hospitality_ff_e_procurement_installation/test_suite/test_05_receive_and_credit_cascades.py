"""Queue A (depth) — transitive cascades: the five-link shipment-receipt chain
and the three-link damage-credit chain.
"""
from test_helpers import (
    api_client, validate_success,
    run_pipeline, transition_shipment, get_po, get_po_line, get_budget_line,
    get_project, create_claim, transition_claim,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]

# ── rule: transitive_cascade (shipment RECEIVED) ───────────

_TC1_RECIPE = [
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


def _receive_with_shortfall():
    """FCL shipment (cube 70, freight 480000c), IN_TRANSIT, one POSTED event:
    line A 100 good of 100, line B 50 good of 60 (10 undelivered)."""
    return run_pipeline(
        name="P-TC1", budgeted_cents=8_000_000,
        unallocated_contingency_cents=100_000,
        line_specs=_TC1_RECIPE, seal=True, depart=True,
        receipts=[[(0, 100, 0), (1, 50, 0)]],
    )


def test_receive_link1_delivers_pos_and_link2_finalizes_shortfall(api):
    """PRD §3.5: "Link 1: every attached PO in `CONSOLIDATED` moves to `DELIVERED`,
    bumping each PO's `version`. Link 2: each delivered PO finalizes its lines —
    `qty_short` becomes `quantity_ordered` minus `qty_received`, and a line whose
    shortfall is zero moves to `FULLY_RECEIVED` while one with a shortfall stays
    `PARTIALLY_RECEIVED`."
    Line A (100 of 100) reaches FULLY_RECEIVED with qty_short 0; line B (50 of
    60) stays PARTIALLY_RECEIVED with qty_short finalized to 10.

    Design: Difficulty/transitive_cascade/shipment_receive_five_link_cascade
    """
    scenario = _receive_with_shortfall()
    shipment = transition_shipment(scenario["shipment"]["id"], "RECEIVED")
    assert shipment["status"] == "RECEIVED"

    po = get_po(scenario["po"]["id"])
    assert po["fulfillment_status"] == "DELIVERED"

    line_a = get_po_line(scenario["lines"][0]["id"])
    line_b = get_po_line(scenario["lines"][1]["id"])
    assert line_a["status"] == "FULLY_RECEIVED"
    assert line_a["qty_short"] == 0
    assert line_b["status"] == "PARTIALLY_RECEIVED"
    assert line_b["qty_short"] == 10


def test_receive_links_3_to_5_recompute_freight_actuals_and_project(api):
    """PRD §3.5: "Link 3: the final freight allocation is recomputed on the
    received-units basis and each line's `freight_alloc_final_cents` is set. Link
    4: each mutated line's `actual_landed_cents` is recomputed, and `actual_cents`
    plus both variances are recomputed for the affected budget categories. Link 5:
    the project's `actual_spend_cents` and `procurement_posture` are recomputed."
    PRD §2.10: "A line's `actual_landed_cents` is its `qty_received` multiplied by
    its `unit_price_cents`, plus its freight allocation — the final allocation
    `freight_alloc_final_cents` once it has been assigned, otherwise the
    provisional `freight_alloc_provisional_cents` — minus its
    `damage_credit_cents`."
    PRD §2.10: "Purchase orders that have reached `DELIVERED` or `CLOSED` drop out
    of the committed view; cancelled lines never count."
    Received-units shares 100:50 of 480000c are 320000c / 160000c; landed costs
    are 420000c and 260000c; the budget line actual is 680000c; the project
    actual spend is 680000c and the committed total collapses to 0.

    Design: Difficulty/transitive_cascade/shipment_receive_five_link_cascade
    """
    scenario = _receive_with_shortfall()
    transition_shipment(scenario["shipment"]["id"], "RECEIVED")

    line_a = get_po_line(scenario["lines"][0]["id"])
    line_b = get_po_line(scenario["lines"][1]["id"])
    assert line_a["freight_alloc_final_cents"] == 320000
    assert line_b["freight_alloc_final_cents"] == 160000
    assert line_a["actual_landed_cents"] == 100 * 1000 + 320000
    assert line_b["actual_landed_cents"] == 50 * 2000 + 160000

    budget_line = get_budget_line(scenario["budget_line"]["id"])
    assert budget_line["actual_cents"] == 680000

    project = get_project(scenario["project"]["id"])
    assert project["actual_spend_cents"] == 680000
    assert project["committed_cents"] == 0, (
        "a DELIVERED purchase order drops out of the committed view"
    )
    assert project["procurement_posture"] == "OPEN"


# ── rule: transitive_cascade (damage credit) ───────────────

def _received_with_damage_and_claim():
    """LTL shipment (cube 10, freight 10 x 9000 = 90000c) fully received with
    40 received / 10 damaged; a DAMAGE claim for 10 units claimed 100000c is
    SUBMITTED before resolution."""
    scenario = run_pipeline(
        name="P-TC2", budgeted_cents=8_000_000,
        unallocated_contingency_cents=100_000,
        line_specs=[{
            "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
            "quantity_per_room": 2, "room_count": 20,
            "unit_budget_cents": 15000, "unit_price_cents": 15000,
            "lead_time_days": 14,
            "quantity_ordered": 40, "declared_cube_m3": 10,
            "spec_overrides": {"required_lead_days": 21},
        }],
        seal=True, depart=True,
        receipts=[[(0, 40, 10)]], receive_shipment=True,
    )
    claim = create_claim(
        scenario["lines"][0]["id"], claim_type="DAMAGE", quantity=10,
        claimed_credit_cents=100000,
    )
    transition_claim(claim["id"], "SUBMITTED")
    scenario["claim"] = claim
    return scenario


def test_damage_credit_link1_mutates_line_pools_and_landed_cost(api):
    """PRD §3.6: "Resolution for credit runs a three-link cascade. The approved
    amount is recorded on the claim; the line's `damage_credit_cents` grows by it;
    and when the claim is a damage claim, `qty_damaged_unresolved` falls by the
    claim's `quantity` while `qty_damaged_credited` rises by the same amount."
    Before resolution the line lands at 600000 + 90000 = 690000c (40 received,
    10 damaged, LTL freight 90000c); resolving the 10-unit claim for 80000c moves
    the damaged pool to credited and drops landed cost to 610000c.

    Design: Difficulty/transitive_cascade/damage_credit_three_link_cascade
    """
    scenario = _received_with_damage_and_claim()
    budget_before = get_budget_line(scenario["budget_line"]["id"])
    assert budget_before["actual_cents"] == 690000

    resolved = transition_claim(
        scenario["claim"]["id"], "RESOLVED_CREDIT", approved_credit_cents=80000
    )
    assert resolved["status"] == "RESOLVED_CREDIT"
    assert resolved["approved_credit_cents"] == 80000

    line = get_po_line(scenario["lines"][0]["id"])
    assert line["damage_credit_cents"] == 80000
    assert line["qty_damaged_unresolved"] == 0
    assert line["qty_damaged_credited"] == 10
    assert line["actual_landed_cents"] == 610000


def test_damage_credit_links_2_and_3_recompute_budget_and_project(api):
    """PRD §3.6: "The line's `actual_landed_cents` is then recomputed, the
    category's `actual_cents` and both variances follow, and the project's
    `actual_spend_cents` and posture follow them; the claim's `version` bumps."
    After the 80000c credit, the FURNITURE actual drops from 690000c to 610000c
    and the project actual spend follows to 610000c with posture still OPEN.

    Design: Difficulty/transitive_cascade/damage_credit_three_link_cascade
    """
    scenario = _received_with_damage_and_claim()
    transition_claim(
        scenario["claim"]["id"], "RESOLVED_CREDIT", approved_credit_cents=80000
    )

    budget_line = get_budget_line(scenario["budget_line"]["id"])
    assert budget_line["actual_cents"] == 610000, (
        f"category actual must follow the line credit; got "
        f"{budget_line['actual_cents']}"
    )

    project = get_project(scenario["project"]["id"])
    assert project["actual_spend_cents"] == 610000
    assert project["procurement_posture"] == "OPEN"

    claim = validate_success(
        api_client.get_damage_claim(scenario["claim"]["id"], PA)
    )
    assert claim["status"] == "RESOLVED_CREDIT"
    assert claim["approved_credit_cents"] == 80000
