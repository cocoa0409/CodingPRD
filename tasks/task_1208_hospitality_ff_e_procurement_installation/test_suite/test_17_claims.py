"""Queue B (breadth) — damage/shortage claim lifecycle: the dispute negotiation
cycle, the three terminal outcomes, and the reconcile guard chain.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    run_pipeline, create_claim, transition_claim, get_po_line,
    create_and_post_receiving_event, advance_po_to_ready_to_ship,
    create_consolidating_shipment_with_po, transition_shipment,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
VEN = TEST_USERS["vendor_headers"]

_LINE_40 = {
    "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
    "quantity_per_room": 2, "room_count": 20,
    "unit_budget_cents": 15000, "unit_price_cents": 15000,
    "lead_time_days": 14,
    "quantity_ordered": 40, "declared_cube_m3": 10,
}

_LINE_10 = {
    "description": "Lamp", "brand_standard_ref": "MS-L",
    "quantity_per_room": 1, "room_count": 10,
    "unit_budget_cents": 10000, "unit_price_cents": 10000,
    "lead_time_days": 7,
    "quantity_ordered": 10, "declared_cube_m3": 5,
}


def test_claim_dispute_resubmit_cycle_with_invalid_resolve(api):
    """PRD §3.6: "The claim lifecycle is a negotiation. The `PurchasingAgent`
    submits an `OPEN` claim, moving it to `SUBMITTED`; the `Vendor` disputes a
    `SUBMITTED` claim, moving it to `DISPUTED`; and the `PurchasingAgent` may
    submit again from `DISPUTED` — the `SUBMITTED`–`DISPUTED` cycle is unbounded."
    PRD §3.6: "Three resolutions exist, all from `SUBMITTED` and all by the
    `PurchasingAgent`: resolution for credit, which requires
    `approved_credit_cents` to be provided and at least 0 (a missing value fails
    with `ERR_INVALID_REQUEST`); resolution by replacement; and denial. Any move
    not legal from the claim's current state — resolving from `OPEN`, disputing
    from `DISPUTED`, or anything out of a terminal state — fails with
    `ERR_INVALID_CLAIM_TRANSITION`."
    Resolving from DISPUTED is rejected; resubmitting closes the cycle and the
    credit resolution then succeeds.

    Design: Corner/state_machines/claim_dispute_resubmit_cycle_with_invalid_resolve
    """
    scenario = run_pipeline(
        name="P-S6", budgeted_cents=8_000_000,
        line_specs=[_LINE_40], seal=True, depart=True,
        receipts=[[(0, 40, 10)]],
    )
    line_id = scenario["lines"][0]["id"]
    claim = create_claim(line_id, claim_type="DAMAGE", quantity=5,
                         claimed_credit_cents=50000)
    transition_claim(claim["id"], "SUBMITTED")
    transition_claim(claim["id"], "DISPUTED", headers=VEN)

    res = api_client.transition_damage_claim(
        claim["id"],
        {"to_status": "RESOLVED_CREDIT", "approved_credit_cents": 40000},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_CLAIM_TRANSITION,
                   expected_status=409)

    back = transition_claim(claim["id"], "SUBMITTED")
    assert back["status"] == "SUBMITTED"

    resolved = transition_claim(
        claim["id"], "RESOLVED_CREDIT", approved_credit_cents=40000
    )
    assert resolved["status"] == "RESOLVED_CREDIT"
    assert resolved["approved_credit_cents"] == 40000

    line = get_po_line(line_id)
    assert line["damage_credit_cents"] == 40000
    assert line["qty_damaged_credited"] == 5
    assert line["qty_damaged_unresolved"] == 5


def test_claim_terminal_outcomes(api):
    """PRD §3.6: "Resolution by replacement applies the same pool shift for damage
    claims — unresolved falls, credited rises — but changes no credit amounts, and
    bumps the claim's `version`. Denial changes no pools and no credits: the units
    remain damaged and uncredited, and only the claim's `version` bumps."
    PRD §3.6: "For `SHORTAGE`, the residual is the line's `qty_short` minus the
    summed quantities of its non-terminal shortage claims."
    A line with 35 received / 4 damaged / qty_short finalized to 5 carries two
    DAMAGE claims and one SHORTAGE claim to three different terminal outcomes.

    Design: Corner/errors/claim_terminal_outcomes
    """
    scenario = run_pipeline(
        name="P-R11", budgeted_cents=8_000_000,
        line_specs=[_LINE_40], seal=True, depart=True,
        receipts=[[(0, 35, 4)]], receive_shipment=True,
    )
    line_id = scenario["lines"][0]["id"]

    d1 = create_claim(line_id, claim_type="DAMAGE", quantity=2,
                      claimed_credit_cents=20000)
    transition_claim(d1["id"], "SUBMITTED")
    d2 = create_claim(line_id, claim_type="DAMAGE", quantity=2,
                      claimed_credit_cents=20000)
    transition_claim(d2["id"], "SUBMITTED")
    s1 = create_claim(line_id, claim_type="SHORTAGE", quantity=5,
                      claimed_credit_cents=50000)
    transition_claim(s1["id"], "SUBMITTED")

    denied = transition_claim(d1["id"], "DENIED")
    assert denied["status"] == "DENIED"

    replaced = transition_claim(d2["id"], "RESOLVED_REPLACEMENT")
    assert replaced["status"] == "RESOLVED_REPLACEMENT"

    shortage_replaced = transition_claim(s1["id"], "RESOLVED_REPLACEMENT")
    assert shortage_replaced["status"] == "RESOLVED_REPLACEMENT"

    line = get_po_line(line_id)
    assert line["qty_received"] == 35
    assert line["qty_short"] == 5
    assert line["damage_credit_cents"] == 0, (
        "neither denial nor replacement moves money"
    )
    assert line["qty_damaged_unresolved"] == 2, (
        "only the 2-unit replacement moves the damaged pool"
    )
    assert line["qty_damaged_credited"] == 2


def test_reconcile_guards(api):
    """PRD §3.6: "A `PurchasingAgent` may reconcile a line in `FULLY_RECEIVED` or
    `PARTIALLY_RECEIVED` — from any other state the attempt fails with
    `ERR_LINE_NOT_RECEIVED`. A `PARTIALLY_RECEIVED` line may reconcile only once
    its shipment has reached `RECEIVED`, so its shortfall is final; otherwise
    `ERR_LINE_SHORTFALL_OPEN`. And no claim on the line may remain in `OPEN`,
    `SUBMITTED`, or `DISPUTED`, else `ERR_CLAIMS_OPEN`."
    The three guards are exercised in sequence: nothing received; partially
    received with the shipment still in transit; fully received with an OPEN
    claim.

    Design: Corner/errors/reconcile_guards
    """
    scenario = run_pipeline(
        name="P-R3", budgeted_cents=8_000_000,
        line_specs=[_LINE_10], attach=False, seal=False, depart=False,
    )
    project_id = scenario["project"]["id"]
    po_id = scenario["po"]["id"]
    line_id = scenario["lines"][0]["id"]

    res = api_client.reconcile_po_line(line_id, PA)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_RECEIVED, expected_status=409)

    advance_po_to_ready_to_ship(po_id)
    shipment = create_consolidating_shipment_with_po(project_id, po_id, "CARR")
    transition_shipment(shipment["id"], "SEALED")
    transition_shipment(shipment["id"], "IN_TRANSIT")
    create_and_post_receiving_event(
        shipment["id"],
        [{"po_line_id": line_id, "qty_received": 5, "qty_damaged": 1}],
    )

    line = get_po_line(line_id)
    assert line["status"] == "PARTIALLY_RECEIVED"
    res = api_client.reconcile_po_line(line_id, PA)
    validate_error(res, ApiErrorId.ERR_LINE_SHORTFALL_OPEN, expected_status=409)

    create_and_post_receiving_event(
        shipment["id"],
        [{"po_line_id": line_id, "qty_received": 5, "qty_damaged": 0}],
    )
    line = get_po_line(line_id)
    assert line["status"] == "FULLY_RECEIVED"

    create_claim(line_id, claim_type="DAMAGE", quantity=1,
                 claimed_credit_cents=5000)
    res = api_client.reconcile_po_line(line_id, PA)
    validate_error(res, ApiErrorId.ERR_CLAIMS_OPEN, expected_status=409)

    line = get_po_line(line_id)
    assert line["status"] == "FULLY_RECEIVED"
