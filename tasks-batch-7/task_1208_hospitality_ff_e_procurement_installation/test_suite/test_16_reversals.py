"""Queue B (breadth) — receiving-event reversal: blocked by resolved-track
claims, blocked by consumed pools, and exact restoration of prior state.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    run_pipeline, create_claim, transition_claim,
    get_po_line, get_budget_line, get_project,
    setup_received_pipeline_with_window,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]
WR = TEST_USERS["warehouse_receiver_headers"]

_LINE_10 = {
    "description": "Lamp", "brand_standard_ref": "MS-L",
    "quantity_per_room": 1, "room_count": 10,
    "unit_budget_cents": 10000, "unit_price_cents": 10000,
    "lead_time_days": 7,
    "quantity_ordered": 10, "declared_cube_m3": 5,
}


def test_receiving_reverse_blocked_by_submitted_claim(api):
    """PRD §3.5: "No claim on any covered line may be in `SUBMITTED`, `DISPUTED`,
    `RESOLVED_CREDIT`, `RESOLVED_REPLACEMENT`, or `DENIED` — such a claim blocks
    the reversal outright with `ERR_CLAIMS_BLOCK_REVERSAL` — while claims still
    `OPEN` are voided to `VOID` instead."
    A SUBMITTED claim on the covered line freezes the event at POSTED.

    Design: Corner/errors/receiving_reverse_blocked_by_submitted_claim
    """
    scenario = run_pipeline(
        name="P-R4", budgeted_cents=8_000_000,
        line_specs=[_LINE_10], seal=True, depart=True,
        receipts=[[(0, 10, 2)]],
    )
    line_id = scenario["lines"][0]["id"]
    event_id = scenario["events"][0]["id"]
    claim = create_claim(line_id, claim_type="DAMAGE", quantity=1,
                         claimed_credit_cents=5000)
    transition_claim(claim["id"], "SUBMITTED")

    res = api_client.transition_receiving_event(
        event_id, {"to_status": "REVERSED"}, WR
    )
    validate_error(res, ApiErrorId.ERR_CLAIMS_BLOCK_REVERSAL,
                   expected_status=409)

    event = validate_success(api_client.get_receiving_event(event_id, WR))
    assert event["status"] == "POSTED"
    claim_after = validate_success(api_client.get_damage_claim(claim["id"], PA))
    assert claim_after["status"] == "SUBMITTED"
    line = get_po_line(line_id)
    assert line["qty_received"] == 10
    assert line["qty_damaged_unresolved"] == 2


def test_receiving_reverse_restores_exact_priors(api):
    """PRD §3.5: "The reversal then decrements `qty_received` and
    `qty_damaged_unresolved` by the event's quantities, decrements
    `qty_installable` by the net, recomputes the line status (a fully-received
    line falls back to `PARTIALLY_RECEIVED`, or to `OPEN` when nothing remains),
    bumps the line's `version`, and recomputes the budget and project actuals and
    posture; the event's `version` bumps."
    PRD §3.5: "while claims still `OPEN` are voided to `VOID` instead"
    PRD §3.5: "An event transition that is not legal from its current state —
    re-posting, or reversing from `DRAFT` — fails with
    `ERR_INVALID_EVENT_TRANSITION`."
    The posted event (10 received / 2 damaged, LTL freight 5 x 9000 = 45000c)
    lands 145000c of actual; reversing it voids the OPEN claim, returns every
    pool to zero, reopens the line, and zeroes the budget actual — immediately
    visible on the same reads.

    Design: Corner/consistency_model/receiving_reverse_restores_exact_priors
    """
    scenario = run_pipeline(
        name="P-M1", budgeted_cents=8_000_000,
        line_specs=[_LINE_10], seal=True, depart=True,
        receipts=[[(0, 10, 2)]],
    )
    line_id = scenario["lines"][0]["id"]
    event_id = scenario["events"][0]["id"]
    claim = create_claim(line_id, claim_type="DAMAGE", quantity=1,
                         claimed_credit_cents=5000)

    budget_before = get_budget_line(scenario["budget_line"]["id"])
    assert budget_before["actual_cents"] == 145000, (
        "10 x 10000c goods + 45000c LTL provisional freight"
    )

    reversed_event = validate_success(
        api_client.transition_receiving_event(
            event_id, {"to_status": "REVERSED"}, WR
        ),
        200,
    )
    assert reversed_event["status"] == "REVERSED"

    claim_after = validate_success(api_client.get_damage_claim(claim["id"], PA))
    assert claim_after["status"] == "VOID"

    line = get_po_line(line_id)
    assert line["qty_received"] == 0
    assert line["qty_damaged_unresolved"] == 0
    assert line["qty_installable"] == 0
    assert line["status"] == "OPEN", (
        "reversing the only receipt returns the line to OPEN"
    )

    budget_after = get_budget_line(scenario["budget_line"]["id"])
    assert budget_after["actual_cents"] == 0
    project = get_project(scenario["project"]["id"])
    assert project["actual_spend_cents"] == 0

    res = api_client.transition_receiving_event(
        event_id, {"to_status": "REVERSED"}, WR
    )
    validate_error(res, ApiErrorId.ERR_INVALID_EVENT_TRANSITION,
                   expected_status=409)


def test_reversal_pool_shortfall_guard(api):
    """PRD §3.5: "And the pools must survive the subtraction: for each entry,
    `qty_installable` minus the entry's net receipt (its received minus its
    damaged) must remain at least zero given units already installed or moved to
    attic, else `ERR_REVERSAL_POOL_SHORTFALL`."
    Six of the ten received units are already installed, so backing out the
    receipt would drive qty_installable to 4 - 10 < 0.

    Design: Corner/errors/reversal_pool_shortfall_guard
    """
    scenario = setup_received_pipeline_with_window(
        line_qty=10, line_unit_price=10000, cube=5, received=10,
        floor_number=8, room_number="R-801", room_type="SUITE",
        start_date="2026-08-05", end_date="2026-08-07", crew_count=1,
        task_quantities=(6,), start_window=True, complete_tasks=True,
    )
    line_id = scenario["lines"][0]["id"]
    event_id = scenario["events"][0]["id"]

    line_before = get_po_line(line_id)
    assert line_before["qty_installable"] == 4
    assert line_before["qty_installed"] == 6

    res = api_client.transition_receiving_event(
        event_id, {"to_status": "REVERSED"}, WR
    )
    validate_error(res, ApiErrorId.ERR_REVERSAL_POOL_SHORTFALL,
                   expected_status=409)

    event = validate_success(api_client.get_receiving_event(event_id, WR))
    assert event["status"] == "POSTED"
    line_after = get_po_line(line_id)
    assert line_after["qty_installable"] == 4
    assert line_after["qty_installed"] == 6
