"""Allocation ledger conservation, basis ceiling, excluded-terminal guard, reverse listing.

Translates queue A (compensating allocation invariant) and queue B (basis ceiling,
allocate-from-excluded, reverse FK listing) instances.
"""
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS, fixtures

SM = TEST_USERS["study_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/allocation_ledger_conserved_on_allocate_then_exclude
# ---------------------------------------------------------------------------
def test_allocate_then_exclude_conserves_allocation_total(api):
    """PRD §2.10: "allocating a component adds its cost, and excluding a component that had
    been allocated subtracts the same cost as a compensating reversal."

    Allocate A (3000000) and B (5000000); excluding B removes exactly 5000000, leaving the
    study total at A's 3000000.

    Design: Difficulty/compensating_invariant/allocation_ledger_conserved_on_allocate_then_exclude
    """
    ctx = fixtures.setup_cost_seg_engineering(api)
    comps = fixtures.add_allocated_components(api, ctx, [
        ("A", "FIVE_YEAR", 3000000),
        ("B", "FIVE_YEAR", 5000000),
    ])
    get_success_data(api.exclude_component(comps[1]["id"], ctx["eng_headers"]))
    study = validate_success(api.get_study(ctx["study_id"], SM), 200)
    assert study["total_allocated_cost_cents"] == 3000000


def test_exclude_proposed_component_has_no_ledger_effect(api):
    """PRD §3.3: "a component excluded from PROPOSED has no ledger effect, whereas a component
    excluded after it was ALLOCATED subtracts its allocated_cost_cents back out of the study's
    total_allocated_cost_cents as a compensating reversal."

    Excluding a never-allocated (PROPOSED) component leaves the allocation total unchanged.

    Design: Difficulty/compensating_invariant/allocation_ledger_conserved_on_allocate_then_exclude
    """
    ctx = fixtures.setup_cost_seg_engineering(api)
    fixtures.add_allocated_components(api, ctx, [("A", "FIVE_YEAR", 3000000)])
    proposed = fixtures.add_component(api, ctx, "C", "FIVE_YEAR", 5000000, allocate=False)
    get_success_data(api.exclude_component(proposed["id"], ctx["eng_headers"]))
    study = validate_success(api.get_study(ctx["study_id"], SM), 200)
    assert study["total_allocated_cost_cents"] == 3000000


# ---------------------------------------------------------------------------
# Corner/validations/allocation_exceeds_basis_rejected
# ---------------------------------------------------------------------------
def test_allocation_exceeding_basis_rejected(api):
    """PRD §3.3: "Allocation must not push the study's running total_allocated_cost_cents above
    the property's depreciable_basis_cents; if the component's cost added to the current
    allocated total would exceed the basis, the request is rejected with
    ERR_ALLOCATION_EXCEEDS_BASIS."

    A single component of 100000001 exceeds the 100000000 basis.

    Design: Corner/validations/allocation_exceeds_basis_rejected
    """
    ctx = fixtures.setup_cost_seg_engineering(api)  # basis 120000000-20000000 = 100000000
    comp = fixtures.add_component(api, ctx, "big", "THIRTY_NINE_YEAR", 100000001, allocate=False)
    resp = api.allocate_component(comp["id"], ctx["eng_headers"])
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_BASIS.value)


# ---------------------------------------------------------------------------
# Corner/state_machines/allocate_from_excluded_component_returns_invalid_state
# ---------------------------------------------------------------------------
def test_allocate_excluded_component_rejected(api):
    """PRD §3.3: "An engineer may instead exclude a component, moving it to the terminal
    EXCLUDED state."
    PRD §2.1: "then whether the target resource is in a state from which the requested
    transition is legal (ERR_INVALID_STATE)."

    Allocating a component already in terminal EXCLUDED is an illegal transition.

    Design: Corner/state_machines/allocate_from_excluded_component_returns_invalid_state
    """
    ctx = fixtures.setup_cost_seg_engineering(api)
    comp = fixtures.add_component(api, ctx, "c", "FIVE_YEAR", 1000000, allocate=False)
    get_success_data(api.exclude_component(comp["id"], ctx["eng_headers"]))
    resp = api.allocate_component(comp["id"], ctx["eng_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner/endpoints/fk_reverse_asset_components_listable
# ---------------------------------------------------------------------------
def test_study_asset_components_listable(api):
    """PRD §3.3: "its assigned Engineer builds up the reclassification detail as AssetComponent
    records. Each component belongs to its parent study through a study_id."
    PRD §4: "GET /studies/{id}/asset-components | List a study's asset components".

    Design: Corner/endpoints/fk_reverse_asset_components_listable
    """
    ctx = fixtures.setup_cost_seg_engineering(api)
    comp = fixtures.add_component(api, ctx, "one", "SEVEN_YEAR", 5000000, allocate=False)
    body = api.list_asset_components(ctx["study_id"], SM).json()
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == comp["id"]
