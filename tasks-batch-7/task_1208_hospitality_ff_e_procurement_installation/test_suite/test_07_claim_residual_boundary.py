"""Queue A (depth) — boundary precision on the damage-claim residual:
cumulative claimed units may reach the damaged residual exactly, never exceed it.

Setup: line 40 x 15000c received 40 with 10 damaged (damaged residual 10).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, run_pipeline, create_claim,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]


def _damaged_line_scenario():
    """40 received, 10 damaged -> DAMAGE residual 10; no claims yet."""
    return run_pipeline(
        name="P-BP2", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
            "quantity_per_room": 2, "room_count": 20,
            "unit_budget_cents": 15000, "unit_price_cents": 15000,
            "lead_time_days": 14,
            "quantity_ordered": 40, "declared_cube_m3": 10,
        }],
        seal=True, depart=True, receipts=[[(0, 40, 10)]],
    )


def test_claim_cumulative_quantity_may_equal_residual(api):
    """PRD §3.6: "For `DAMAGE`, the residual is the line's `qty_damaged_unresolved`
    minus the summed quantities of its non-terminal damage claims — those in
    `OPEN`, `SUBMITTED`, or `DISPUTED`."
    PRD §3.6: "A claim whose quantity is at most the residual is accepted —
    equality with the residual is allowed — while exceeding it is rejected with
    `ERR_CLAIM_QTY_EXCEEDS_RESIDUAL` (422)."
    Claims of 6 then 4 against a damaged residual of 10 both land (cumulative
    10 == residual).

    Design: Difficulty/boundary_precision_check/claim_residual_equality_boundary
    """
    scenario = _damaged_line_scenario()
    line_id = scenario["lines"][0]["id"]

    claim_1 = create_claim(line_id, claim_type="DAMAGE", quantity=6,
                           claimed_credit_cents=60000)
    assert claim_1["status"] == "OPEN"
    claim_2 = create_claim(line_id, claim_type="DAMAGE", quantity=4,
                           claimed_credit_cents=40000)
    assert claim_2["status"] == "OPEN", (
        "cumulative 6 + 4 == 10 equals the residual; equality must be accepted"
    )

    claims, meta = validate_paginated(
        api_client.list_po_line_damage_claims(line_id, PA)
    )
    assert meta["total_count"] == 2
    assert {c["id"] for c in claims} == {claim_1["id"], claim_2["id"]}


def test_claim_one_unit_beyond_residual_rejected(api):
    """PRD §3.6: "A claim whose quantity is at most the residual is accepted —
    equality with the residual is allowed — while exceeding it is rejected with
    `ERR_CLAIM_QTY_EXCEEDS_RESIDUAL` (422)."
    After claims of 6 and 4 consume the residual of 10 exactly, a further claim
    of 1 (cumulative 11 > 10) is rejected and persists nothing.

    Design: Difficulty/boundary_precision_check/claim_residual_equality_boundary
    """
    scenario = _damaged_line_scenario()
    line_id = scenario["lines"][0]["id"]

    create_claim(line_id, claim_type="DAMAGE", quantity=6,
                 claimed_credit_cents=60000)
    create_claim(line_id, claim_type="DAMAGE", quantity=4,
                 claimed_credit_cents=40000)

    res = api_client.create_damage_claim(
        {"po_line_id": line_id, "claim_type": "DAMAGE", "quantity": 1,
         "claimed_credit_cents": 10000},
        PA,
    )
    validate_error(res, ApiErrorId.ERR_CLAIM_QTY_EXCEEDS_RESIDUAL,
                   expected_status=422)

    claims, meta = validate_paginated(
        api_client.list_po_line_damage_claims(line_id, PA)
    )
    assert meta["total_count"] == 2, (
        "the rejected third claim must not be persisted"
    )
    assert all(c["status"] == "OPEN" for c in claims)
