"""Hiring-freeze posture, the freeze/lift cascades, half-open freeze-window
arithmetic, and committed-FTE conservation across a freeze cycle.

Queue A (Difficulty): transitive_cascade, resource_temporal_overlap (freeze
window), compensating_invariant (FTE).
Queue B (Corner): calculations (posture boundaries), validations (window
overlap), cross_cutting_complexity_layers (cascade-suspend).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, fixtures, factories,
)


# ===========================================================================
# Depth-3 lift cascade: lift -> posture OPEN -> positions FUNDED -> reqs OPEN
# ===========================================================================
def test_lift_cascades_unfreeze_position_and_requisition(api, finance_headers):
    """PRD §3.5: "each FROZEN position returns to FUNDED, and the un-freezing of
    each position re-opens the requisitions it had suspended, so every SUSPENDED
    requisition on those positions returns to OPEN."

    Design: Difficulty/transitive_cascade/tc_freeze_lift_depth3_unfreeze
    """
    fixtures.set_clock("2026-02-01T00:00:00Z")
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    pos = fixtures.create_funded_position(cc["id"], grade["id"], title="Engineer", fte=0.5)
    rq = fixtures.open_requisition(pos["id"], req_type="BACKFILL", justification="ramp")
    f = fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")

    resp = api.lift_freeze_order(f["id"], finance_headers)
    validate_success(resp, 200)

    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["posture"] == "OPEN", f"Expected posture OPEN after lift, got {cost_center['posture']}"
    position = fixtures.get_position(pos["id"])
    assert position["lifecycle_status"] == "FUNDED", \
        f"Position must return to FUNDED, got {position['lifecycle_status']}"
    requisition = get_success_data(api.get_requisition(rq["id"], finance_headers))
    assert requisition["status"] == "OPEN", \
        f"Requisition must return to OPEN, got {requisition['status']}"


def test_freeze_then_lift_position_returns_to_funded(api, finance_headers):
    """PRD §3.5: "a compensating cascade un-freezes its workforce: each FROZEN
    position returns to FUNDED".

    Design: Difficulty/transitive_cascade/tc_freeze_lift_depth3_unfreeze
    """
    grade, cc, pos, f = fixtures.setup_frozen_cost_center_with_funded_position()
    # While frozen, the position is FROZEN.
    frozen = fixtures.get_position(pos["id"])
    assert frozen["lifecycle_status"] == "FROZEN", \
        f"Expected FROZEN under active order, got {frozen['lifecycle_status']}"

    fixtures.lift_freeze_order(f["id"])
    position = fixtures.get_position(pos["id"])
    assert position["lifecycle_status"] == "FUNDED", \
        f"Position must un-freeze to FUNDED, got {position['lifecycle_status']}"


# ===========================================================================
# Depth-2 abolish cascade: abolish -> incumbent VACATED -> employee AVAILABLE
# ===========================================================================
def test_abolish_filled_position_vacates_incumbent_and_frees_employee(api, director_headers):
    """PRD §3.8: "If the position was FILLED, its active incumbent is moved to
    VACATED, the position's occupancy_status returns to VACANT, and the occupied
    employee's status returns to AVAILABLE."

    Design: Difficulty/transitive_cascade/tc_abolish_depth2_vacate_incumbent
    """
    grade, cc, pos, emp, inc = fixtures.setup_filled_position(employee_salary_cents=13000000)

    resp = api.position_lifecycle(pos["id"], factories.lifecycle_payload("ABOLISH"), director_headers)
    validate_success(resp, 200)

    position = fixtures.get_position(pos["id"])
    assert position["lifecycle_status"] == "ABOLISHED", \
        f"Expected ABOLISHED, got {position['lifecycle_status']}"
    assert position["occupancy_status"] == "VACANT", \
        f"Expected VACANT after abolish, got {position['occupancy_status']}"
    incumbent = get_success_data(api.get_incumbent(inc["id"], director_headers))
    assert incumbent["status"] == "VACATED", \
        f"Expected incumbent VACATED, got {incumbent['status']}"
    employee = get_success_data(api.get_employee(emp["id"], director_headers))
    assert employee["status"] == "AVAILABLE", \
        f"Expected employee AVAILABLE, got {employee['status']}"


def test_abolish_filled_position_occupancy_returns_to_vacant(api, director_headers):
    """PRD §3.8: "the position's occupancy_status returns to VACANT".

    Design: Difficulty/transitive_cascade/tc_abolish_depth2_vacate_incumbent
    """
    grade, cc, pos, emp, inc = fixtures.setup_filled_position(employee_salary_cents=13000000)
    api.position_lifecycle(pos["id"], factories.lifecycle_payload("ABOLISH"), director_headers)
    position = fixtures.get_position(pos["id"])
    assert position["occupancy_status"] == "VACANT"


# ===========================================================================
# Freeze window — half-open adjacency allowed
# ===========================================================================
def test_adjacent_freeze_windows_do_not_overlap(api, finance_headers):
    """PRD §3.5: "because windows are half-open, two windows that merely touch at
    a shared boundary instant do not overlap, but any genuine overlap is rejected
    with ERR_FREEZE_WINDOW_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_freeze_window_halfopen_adjacency_allowed
    """
    fixtures.set_clock("2026-05-01T00:00:00Z")
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", reason="q1")

    # F2 starts exactly where F1 ends -> no overlap, accepted (201).
    resp = api.create_freeze_order(
        cc["id"],
        factories.create_freeze_order_payload("2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z", "q2"),
        finance_headers,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE", f"Expected ACTIVE freeze order, got {data['status']}"

    # Clock 2026-05-01 is inside [2026-04-01, 2026-07-01) -> posture FROZEN.
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["posture"] == "FROZEN", \
        f"Expected posture FROZEN under F2, got {cost_center['posture']}"


def test_freeze_window_ending_at_another_start_accepted(api, finance_headers):
    """PRD §3.5: "because windows are half-open, two windows that merely touch at
    a shared boundary instant do not overlap".

    Design: Difficulty/resource_temporal_overlap/rto_freeze_window_halfopen_adjacency_allowed
    """
    fixtures.set_clock("2026-05-01T00:00:00Z")
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    # F1 occupies the later window; F2 ends exactly at F1's start -> no overlap.
    fixtures.open_freeze_order(cc["id"], "2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z", reason="late")

    resp = api.create_freeze_order(
        cc["id"],
        factories.create_freeze_order_payload("2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", "early"),
        finance_headers,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE", f"Adjacent earlier window must be accepted, got {data['status']}"


# ===========================================================================
# Compensating invariant — committed_fte conserved across freeze+lift
# ===========================================================================
def test_freeze_then_lift_conserves_committed_fte(api, finance_headers):
    """PRD §3.5: "A frozen position retains its contribution to committed_fte and
    committed_cost_cents — freezing conserves the commitment rather than releasing
    it."

    Design: Difficulty/compensating_invariant/ci_freeze_then_lift_conserves_committed_fte
    """
    grade, cc, pos, f = fixtures.setup_frozen_cost_center_with_funded_position()
    # Frozen position still counts toward committed_fte.
    frozen_cc = fixtures.get_cost_center(cc["id"])
    assert frozen_cc["committed_fte"] == 0.5, \
        f"committed_fte must stay 0.5 while FROZEN, got {frozen_cc['committed_fte']}"

    fixtures.lift_freeze_order(f["id"])
    position = fixtures.get_position(pos["id"])
    assert position["lifecycle_status"] == "FUNDED", \
        f"Position must un-freeze to FUNDED, got {position['lifecycle_status']}"
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_fte"] == 0.5, \
        f"committed_fte must remain 0.5 across freeze+lift, got {cost_center['committed_fte']}"
    assert cost_center["posture"] == "OPEN", \
        f"Expected posture OPEN after lift, got {cost_center['posture']}"


def test_frozen_position_retains_committed_cost(api):
    """PRD §3.5: "A frozen position retains its contribution to committed_fte and
    committed_cost_cents — freezing conserves the commitment rather than releasing
    it."

    Design: Difficulty/compensating_invariant/ci_freeze_then_lift_conserves_committed_fte
    """
    grade, cc, pos, f = fixtures.setup_frozen_cost_center_with_funded_position()
    # G07 mid 12000000 * 0.5 = 6000000 planned; frozen position still contributes.
    frozen_cc = fixtures.get_cost_center(cc["id"])
    assert frozen_cc["committed_cost_cents"] == 6000000, \
        f"Frozen position must retain committed_cost 6000000, got {frozen_cc['committed_cost_cents']}"

    fixtures.lift_freeze_order(f["id"])
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["committed_cost_cents"] == 6000000, \
        f"committed_cost must remain 6000000 across freeze+lift, got {cost_center['committed_cost_cents']}"


# ===========================================================================
# Posture half-open boundaries (Corner)
# ===========================================================================
def test_posture_frozen_at_lower_inclusive_boundary(api):
    """PRD §2.9: "an order covers an instant when its effective_from is at or
    before the instant and its effective_to is strictly after it".

    Design: Corner/calculations/calc_posture_halfopen_lower_inclusive_boundary
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")
    # Clock exactly at effective_from is inside [from, to) -> FROZEN.
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["posture"] == "FROZEN", \
        f"Clock at effective_from must be FROZEN, got {cost_center['posture']}"


def test_posture_open_at_upper_exclusive_boundary(api):
    """PRD §2.9: "so an order whose effective_to equals the current instant does
    not freeze."

    Design: Corner/calculations/calc_posture_halfopen_upper_exclusive_boundary
    """
    fixtures.set_clock("2026-04-01T00:00:00Z")
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")
    # Clock exactly at effective_to is outside [from, to) -> OPEN.
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["posture"] == "OPEN", \
        f"Clock at effective_to must be OPEN, got {cost_center['posture']}"


# ===========================================================================
# Freeze window overlap rejected (Corner)
# ===========================================================================
def test_overlapping_freeze_window_rejected(api, finance_headers):
    """PRD §3.5: "it must not overlap any other still-active freeze order on the
    same cost center ... but any genuine overlap is rejected with
    ERR_FREEZE_WINDOW_OVERLAP (HTTP 409)."

    Design: Corner/validations/val_freeze_window_overlap_rejected
    """
    fixtures.set_clock("2026-05-01T00:00:00Z")
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z", reason="f1")

    # [2026-03-31, 2026-05-01) genuinely overlaps [2026-01-01, 2026-04-01).
    resp = api.create_freeze_order(
        cc["id"],
        factories.create_freeze_order_payload("2026-03-31T00:00:00Z", "2026-05-01T00:00:00Z", "f2"),
        finance_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FREEZE_WINDOW_OVERLAP.value)


# ===========================================================================
# Freeze open cascade suspends OPEN requisition (Corner)
# ===========================================================================
def test_freeze_suspends_open_requisition(api, finance_headers):
    """PRD §3.5: "each such freeze in turn suspends that position's open
    requisitions: every requisition in OPEN status on a frozen position moves to
    SUSPENDED."

    Design: Corner/cross_cutting_complexity_layers/cascade_freeze_suspends_open_requisition
    """
    fixtures.set_clock("2026-02-01T00:00:00Z")
    grade = fixtures.create_grade_g07()
    cc = fixtures.create_cost_center(name="Eng", annual_budget_cents=100000000, fte_cap=5.0)
    pos = fixtures.create_funded_position(cc["id"], grade["id"], title="P1", fte=0.5)
    rq = fixtures.open_requisition(pos["id"], req_type="NEW_HIRE", justification="hire")

    # Opening a freeze covering now cascades position -> FROZEN, requisition -> SUSPENDED.
    fixtures.open_freeze_order(cc["id"], "2026-01-01T00:00:00Z", "2026-04-01T00:00:00Z")

    position = fixtures.get_position(pos["id"])
    assert position["lifecycle_status"] == "FROZEN", \
        f"Position must be FROZEN, got {position['lifecycle_status']}"
    requisition = get_success_data(api.get_requisition(rq["id"], finance_headers))
    assert requisition["status"] == "SUSPENDED", \
        f"Requisition must be SUSPENDED, got {requisition['status']}"
    cost_center = fixtures.get_cost_center(cc["id"])
    assert cost_center["posture"] == "FROZEN", \
        f"Expected posture FROZEN, got {cost_center['posture']}"
