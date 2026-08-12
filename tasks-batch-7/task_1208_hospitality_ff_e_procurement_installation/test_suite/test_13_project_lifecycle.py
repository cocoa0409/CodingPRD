"""Queue B (breadth) — project lifecycle gates: budget-line precondition,
completion blockers, cancellation blockers, terminal lockdown, and the
spec-locking cascade on completion.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    create_project, add_budget_line, advance_project_lifecycle,
    create_approved_spec, create_window, run_pipeline, create_claim,
    create_po, add_po_line, create_awarded_spec,
    advance_po_to_ready_to_ship, get_po,
    TEST_USERS,
)

PA = TEST_USERS["purchasing_agent_headers"]


def test_lifecycle_skip_and_budget_gate(api):
    """PRD §3.1: "From `PLANNING`, the project may advance to `PROCUREMENT`, which
    requires at least one budget line to exist — otherwise `ERR_NO_BUDGET_LINES` —
    and recomputes the posture."
    PRD §3.1: "Any `to_status` that is not a legal next state from the project's
    current state — including every transition out of the terminal `COMPLETED` or
    `CANCELLED` states, and skips such as `PLANNING` directly to `INSTALLATION` —
    is rejected with `ERR_INVALID_LIFECYCLE_TRANSITION` (409)."
    P1 has no budget line (precondition failure); P2 has one but cannot skip
    PROCUREMENT (illegal jump).

    Design: Corner/state_machines/lifecycle_skip_and_budget_gate
    """
    p1 = create_project(name="P-S8a", hotel_name="H",
                        brand_program="MARQUEE_SELECT",
                        total_budget_cents=5_000_000)
    p2 = create_project(name="P-S8b", hotel_name="H",
                        brand_program="MARQUEE_SELECT",
                        total_budget_cents=5_000_000)
    add_budget_line(p2["id"], "FURNITURE", 1_000_000)

    res = api_client.transition_project_lifecycle(
        p1["id"], {"to_status": "PROCUREMENT"}, PA
    )
    validate_error(res, ApiErrorId.ERR_NO_BUDGET_LINES, expected_status=409)

    res = api_client.transition_project_lifecycle(
        p2["id"], {"to_status": "INSTALLATION"}, PA
    )
    validate_error(res, ApiErrorId.ERR_INVALID_LIFECYCLE_TRANSITION,
                   expected_status=409)

    assert validate_success(api_client.get_project(p1["id"], PA))["status"] == (
        "PLANNING"
    )
    assert validate_success(api_client.get_project(p2["id"], PA))["status"] == (
        "PLANNING"
    )


def test_project_completion_blocked_by_open_windows(api):
    """PRD §3.1: "From `INSTALLATION` it may reach `COMPLETED` only when no
    installation window remains in `PLANNED`, `RELEASED`, or `IN_PROGRESS`
    (otherwise `ERR_WINDOWS_OUTSTANDING`) and no damage claim remains in `OPEN`,
    `SUBMITTED`, or `DISPUTED` (otherwise `ERR_OPEN_CLAIMS_REMAIN`); on
    completion, every spec item still `BRAND_APPROVED` is locked to `LOCKED`."
    A PLANNED window blocks completion.

    Design: Corner/state_machines/project_completion_blocked_by_open_windows
    """
    project = create_project(name="P-S10", hotel_name="H",
                             brand_program="MARQUEE_SELECT",
                             total_budget_cents=5_000_000)
    add_budget_line(project["id"], "FURNITURE", 1_000_000)
    advance_project_lifecycle(project["id"], "PROCUREMENT")
    advance_project_lifecycle(project["id"], "INSTALLATION")
    create_window(project["id"], floor_number=1, start_date="2026-09-01",
                  end_date="2026-09-03", crew_count=1)

    res = api_client.transition_project_lifecycle(
        project["id"], {"to_status": "COMPLETED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_WINDOWS_OUTSTANDING, expected_status=409)

    after = validate_success(api_client.get_project(project["id"], PA))
    assert after["status"] == "INSTALLATION"


def test_project_cancel_blocked_by_active_pos(api):
    """PRD §3.1: "Cancellation is available from `PLANNING` or `PROCUREMENT`, and
    only while no purchase order of the project sits in `READY_TO_SHIP`,
    `CONSOLIDATED`, `DELIVERED`, or `CLOSED` (otherwise `ERR_ACTIVE_POS_EXIST`)"
    A purchase order already at READY_TO_SHIP blocks cancellation.

    Design: Corner/state_machines/project_cancel_blocked_by_active_pos
    """
    base_project = create_project(name="P-S11", hotel_name="H",
                                  brand_program="MARQUEE_SELECT",
                                  total_budget_cents=10_000_000)
    add_budget_line(base_project["id"], "FURNITURE", 8_000_000)
    advance_project_lifecycle(base_project["id"], "PROCUREMENT")
    spec, _bid = create_awarded_spec(
        base_project["id"], category="FURNITURE", description="Guest chair",
        brand_standard_ref="MS-GR-01", quantity_per_room=2, room_count=20,
        unit_budget_cents=15000, unit_price_cents=15000, lead_time_days=14,
    )
    po = create_po(base_project["id"], "VENDA")
    add_po_line(po["id"], spec["id"], 40, 10)
    advance_po_to_ready_to_ship(po["id"])

    res = api_client.transition_project_lifecycle(
        base_project["id"], {"to_status": "CANCELLED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_ACTIVE_POS_EXIST, expected_status=409)

    after = validate_success(api_client.get_project(base_project["id"], PA))
    assert after["status"] == "PROCUREMENT"
    assert get_po(po["id"])["fulfillment_status"] == "READY_TO_SHIP"


def test_lifecycle_cancel_happy_path_and_terminal_lockdown(api):
    """PRD §3.1: "Cancellation is available from `PLANNING` or `PROCUREMENT`, and
    only while no purchase order of the project sits in `READY_TO_SHIP`,
    `CONSOLIDATED`, `DELIVERED`, or `CLOSED` (otherwise `ERR_ACTIVE_POS_EXIST`)"
    PRD §3.1: "Any `to_status` that is not a legal next state from the project's
    current state — including every transition out of the terminal `COMPLETED` or
    `CANCELLED` states, and skips such as `PLANNING` directly to `INSTALLATION` —
    is rejected with `ERR_INVALID_LIFECYCLE_TRANSITION` (409)."
    A PLANNING project with no purchase orders cancels cleanly, and every further
    lifecycle call out of CANCELLED is rejected.

    Design: Corner/state_machines/lifecycle_cancel_happy_path_and_terminal_lockdown
    """
    project = create_project(name="P-S17", hotel_name="H",
                             brand_program="MARQUEE_LUXE",
                             total_budget_cents=5_000_000)

    cancelled = validate_success(
        api_client.transition_project_lifecycle(
            project["id"], {"to_status": "CANCELLED"}, PA
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"

    res = api_client.transition_project_lifecycle(
        project["id"], {"to_status": "PROCUREMENT"}, PA
    )
    validate_error(res, ApiErrorId.ERR_INVALID_LIFECYCLE_TRANSITION,
                   expected_status=409)


def test_project_completion_locks_specs(api):
    """PRD §3.2: "When the owning project finally reaches `COMPLETED`, the system
    automatically moves every spec still `BRAND_APPROVED` to the terminal `LOCKED`
    state."
    PRD §3.1: "on completion, every spec item still `BRAND_APPROVED` is locked to
    `LOCKED`."
    With no outstanding windows or claims, INSTALLATION -> COMPLETED succeeds and
    locks the approved spec.

    Design: Corner/state_machines/project_completion_locks_specs
    """
    project = create_project(name="P-S18", hotel_name="H",
                             brand_program="MARQUEE_LUXE",
                             total_budget_cents=5_000_000)
    add_budget_line(project["id"], "DECOR", 500000)
    spec = create_approved_spec(
        project["id"], category="DECOR", description="Lobby art",
        brand_standard_ref="ML-A", quantity_per_room=1, room_count=2,
        unit_budget_cents=40000,
    )
    advance_project_lifecycle(project["id"], "PROCUREMENT")
    advance_project_lifecycle(project["id"], "INSTALLATION")

    completed = validate_success(
        api_client.transition_project_lifecycle(
            project["id"], {"to_status": "COMPLETED"}, PA
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"

    spec_after = validate_success(api_client.get_spec_item(spec["id"], PA))
    assert spec_after["status"] == "LOCKED"


def test_completion_blocked_by_open_claims(api):
    """PRD §3.1: "From `INSTALLATION` it may reach `COMPLETED` only when no
    installation window remains in `PLANNED`, `RELEASED`, or `IN_PROGRESS`
    (otherwise `ERR_WINDOWS_OUTSTANDING`) and no damage claim remains in `OPEN`,
    `SUBMITTED`, or `DISPUTED` (otherwise `ERR_OPEN_CLAIMS_REMAIN`); on
    completion, every spec item still `BRAND_APPROVED` is locked to `LOCKED`."
    An OPEN damage claim blocks completion and is not force-resolved by the
    attempt.

    Design: Corner/state_machines/completion_blocked_by_open_claims
    """
    scenario = run_pipeline(
        name="P-S15", budgeted_cents=8_000_000,
        line_specs=[{
            "description": "Guest chair", "brand_standard_ref": "MS-GR-01",
            "quantity_per_room": 2, "room_count": 20,
            "unit_budget_cents": 15000, "unit_price_cents": 15000,
            "lead_time_days": 14,
            "quantity_ordered": 40, "declared_cube_m3": 10,
        }],
        receipts=[[(0, 40, 2)]], receive_shipment=True,
    )
    claim = create_claim(
        scenario["lines"][0]["id"], claim_type="DAMAGE", quantity=1,
        claimed_credit_cents=5000,
    )
    advance_project_lifecycle(scenario["project"]["id"], "INSTALLATION")

    res = api_client.transition_project_lifecycle(
        scenario["project"]["id"], {"to_status": "COMPLETED"}, PA
    )
    validate_error(res, ApiErrorId.ERR_OPEN_CLAIMS_REMAIN, expected_status=409)

    after = validate_success(
        api_client.get_project(scenario["project"]["id"], PA)
    )
    assert after["status"] == "INSTALLATION"
    claim_after = validate_success(api_client.get_damage_claim(claim["id"], PA))
    assert claim_after["status"] == "OPEN", (
        "the completion guard must not force-resolve claims"
    )
