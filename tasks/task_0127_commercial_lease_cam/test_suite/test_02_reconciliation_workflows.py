"""Reconciliation/estoppel state-machine cycles, cascades, and compensating
invariants (depth queue A).

Covers the POSTED->DISPUTED->POSTED cycle, the estoppel ISSUED->DISPUTED branch,
the depth-3 post cascade, the depth-2 activate cascade, the void balance
invariant, and the activate/terminate occupancy invariant.
"""
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    setup_example_b_reconciliation, setup_example_b_posted, setup_example_b_disputed,
    post_reconciliation, setup_issued_estoppel,
    create_property, create_tenant, create_lease, create_active_lease,
    make_tenant_headers, make_accountant_headers,
    PM_HEADERS, ACCT_HEADERS, ACCT_ID,
)


# ─── Rule 3: non_linear_state_machine / reconciliation_dispute_cycle ────────

def test_dispute_cycle_returns_to_posted(api):
    """PRD §3.8: "Resolving a dispute re-affirms the posting, returning the
    reconciliation from DISPUTED straight back to POSTED with no ledger change —
    the cyclic POSTED → DISPUTED → POSTED path."

    Design: Difficulty/non_linear_state_machine/reconciliation_dispute_cycle_posted_disputed_posted
    """
    ctx = setup_example_b_disputed()
    recon_id = ctx["recon"]["id"]
    resolved = validate_success(api.resolve_dispute(recon_id, ACCT_HEADERS), 200)
    assert resolved["status"] == "POSTED"


def test_dispute_then_resolve_keeps_balance_unchanged(api):
    """PRD §3.8: "Resolving a dispute re-affirms the posting, returning the
    reconciliation from DISPUTED straight back to POSTED with no ledger change"

    Design: Difficulty/non_linear_state_machine/reconciliation_dispute_cycle_posted_disputed_posted
    """
    ctx = setup_example_b_posted()
    recon_id = ctx["recon"]["id"]
    lease_id = ctx["subject_lease"]["id"]
    tenant_id = ctx["subject_tenant"]["id"]
    # balance after post is the +70000 true-up
    after_post = validate_success(api.get_lease(lease_id, ACCT_HEADERS), 200)
    assert after_post["outstanding_balance_cents"] == 70000
    get_success_data(api.dispute_reconciliation(recon_id, make_tenant_headers(tenant_id)))
    validate_success(api.resolve_dispute(recon_id, ACCT_HEADERS), 200)
    after_resolve = validate_success(api.get_lease(lease_id, ACCT_HEADERS), 200)
    assert after_resolve["outstanding_balance_cents"] == 70000


# ─── Rule 3: non_linear_state_machine / estoppel_branching ─────────────────

def test_estoppel_dispute_branch_reaches_disputed_with_note(api):
    """PRD §3.10: "A valid dispute sets tenant_response to DISPUTED, stores the
    supplied dispute_note, and moves the certificate status to DISPUTED."

    Design: Difficulty/non_linear_state_machine/estoppel_branching_issued_to_confirmed_or_disputed
    """
    prop, tenant, lease, est = setup_issued_estoppel(asserted_balance_cents=999999)
    responded = validate_success(api.respond_estoppel(
        est["id"], {"tenant_response": "DISPUTED", "dispute_note": "Balance overstated."},
        make_tenant_headers(tenant["id"])), 200)
    assert responded["status"] == "DISPUTED"
    assert responded["dispute_note"] == "Balance overstated."


def test_estoppel_dispute_branch_is_terminal(api):
    """PRD §3.10: "Both CONFIRMED and DISPUTED are terminal."

    Design: Difficulty/non_linear_state_machine/estoppel_branching_issued_to_confirmed_or_disputed
    """
    prop, tenant, lease, est = setup_issued_estoppel(asserted_balance_cents=999999)
    th = make_tenant_headers(tenant["id"])
    validate_success(api.respond_estoppel(
        est["id"], {"tenant_response": "DISPUTED", "dispute_note": "Overstated."}, th), 200)
    # A second response to a terminal DISPUTED certificate is rejected.
    res = api.respond_estoppel(
        est["id"], {"tenant_response": "DISPUTED", "dispute_note": "Again."}, th)
    assert res.status_code == 409


# ─── Rule 4: transitive_cascade / post_cascade_recon_to_ledger_to_balance ──

def test_post_cascade_updates_lease_balance_and_locks_pool(api):
    """PRD §3.7: "a CAM_TRUEUP ledger entry of the signed true_up_cents is posted
    with its source_reconciliation_id set to this reconciliation's id, after which
    the lease's outstanding_balance_cents is recomputed"
    PRD §3.7: "The pool's status is set to LOCKED, its total_recoverable_cents is
    recomputed, and its version advances by one."

    Design: Difficulty/transitive_cascade/post_cascade_recon_to_ledger_to_balance_depth3
    """
    ctx = setup_example_b_reconciliation()
    post_reconciliation(ctx["recon"]["id"], ctx["recon_version"])
    lease = validate_success(api.get_lease(ctx["subject_lease"]["id"], ACCT_HEADERS), 200)
    assert lease["outstanding_balance_cents"] == 70000
    pool = validate_success(api.get_expense_pool(ctx["pool"]["id"], ACCT_HEADERS), 200)
    assert pool["status"] == "LOCKED"


def test_post_cascade_creates_cam_trueup_ledger_entry(api):
    """PRD §3.9: "The source_reconciliation_id is set only on a CAM_TRUEUP entry
    and on the reversing CREDIT_ADJUSTMENT from a void, linking the entry back to
    the reconciliation that produced it"

    Design: Difficulty/transitive_cascade/post_cascade_recon_to_ledger_to_balance_depth3
    """
    ctx = setup_example_b_reconciliation()
    recon_id = ctx["recon"]["id"]
    post_reconciliation(recon_id, ctx["recon_version"])
    entries, meta = validate_paginated(
        api.list_reconciliation_ledger_entries(recon_id, ACCT_HEADERS))
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "CAM_TRUEUP"
    assert entries[0]["amount_cents"] == 70000


# ─── Rule 4: transitive_cascade / activate_cascade_lease_to_property ────────

def test_activate_cascade_increments_property_occupancy(api):
    """PRD §3.3: "the property's occupied_sqft is increased by leased_sqft
    (recomputed, advancing the property's version by one)"

    Design: Difficulty/transitive_cascade/activate_cascade_lease_to_property_occupancy_depth2
    """
    prop = create_property(total_rentable_sqft=10000, name="OccProp")
    tenant = create_tenant("OccTen", "ot@x.com")
    lease = create_lease(prop["id"], tenant["id"], leased_sqft=2500, base_rent_cents_annual=0)
    activated = validate_success(api.activate_lease(lease["id"], PM_HEADERS), 200)
    assert activated["status"] == "ACTIVE"
    prop_after = validate_success(api.get_property(prop["id"], PM_HEADERS), 200)
    assert prop_after["occupied_sqft"] == 2500


def test_activate_cascade_advances_property_version(api):
    """PRD §3.3: "the property's occupied_sqft is increased by leased_sqft
    (recomputed, advancing the property's version by one)"

    Design: Difficulty/transitive_cascade/activate_cascade_lease_to_property_occupancy_depth2
    """
    prop = create_property(total_rentable_sqft=10000, name="OccProp2")
    tenant = create_tenant("OccTen2", "ot2@x.com")
    assert prop["version"] == 1
    lease = create_lease(prop["id"], tenant["id"], leased_sqft=2500, base_rent_cents_annual=0)
    validate_success(api.activate_lease(lease["id"], PM_HEADERS), 200)
    prop_after = validate_success(api.get_property(prop["id"], PM_HEADERS), 200)
    assert prop_after["version"] == 2


# ─── Rule 9: compensating_invariant / void_reverses_true_up_balance ────────

def test_void_reverses_true_up_to_zero_balance(api):
    """PRD §3.8: "A void is a compensation that exactly reverses the original
    posting: it posts a CREDIT_ADJUSTMENT ledger entry of minus the same
    true_up_cents (the exact reversal of the CAM_TRUEUP entry)"

    Design: Difficulty/compensating_invariant/void_reverses_true_up_balance_invariant
    """
    ctx = setup_example_b_disputed()
    recon_id = ctx["recon"]["id"]
    voided = validate_success(api.void_reconciliation(recon_id, ACCT_HEADERS), 200)
    assert voided["status"] == "VOID"
    lease = validate_success(api.get_lease(ctx["subject_lease"]["id"], ACCT_HEADERS), 200)
    assert lease["outstanding_balance_cents"] == 0


def test_void_reopens_pool(api):
    """PRD §3.8: "it also reopens the pool, setting its status back to OPEN,
    recomputing total_recoverable_cents, and advancing the pool's version."

    Design: Difficulty/compensating_invariant/void_reverses_true_up_balance_invariant
    """
    ctx = setup_example_b_disputed()
    recon_id = ctx["recon"]["id"]
    validate_success(api.void_reconciliation(recon_id, ACCT_HEADERS), 200)
    pool = validate_success(api.get_expense_pool(ctx["pool"]["id"], ACCT_HEADERS), 200)
    assert pool["status"] == "OPEN"


# ─── Rule 9: compensating_invariant / activate_terminate_occupancy ─────────

def test_terminate_restores_occupancy_to_pre_activation(api):
    """PRD §3.3: "On termination the lease becomes TERMINATED and the property's
    occupied_sqft is decreased by the lease's leased_sqft (recomputed, advancing
    the property's version by one)."

    Design: Difficulty/compensating_invariant/activate_terminate_occupancy_invariant
    """
    prop = create_property(total_rentable_sqft=10000, name="InvProp")
    tenant = create_tenant("InvTen", "i@x.com")
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=2500,
                                base_rent_cents_annual=0)
    terminated = validate_success(api.terminate_lease(lease["id"], PM_HEADERS), 200)
    assert terminated["status"] == "TERMINATED"
    prop_after = validate_success(api.get_property(prop["id"], PM_HEADERS), 200)
    assert prop_after["occupied_sqft"] == 0


def test_terminate_after_activate_round_trips_occupancy(api):
    """PRD §3.3: "the property's occupied_sqft is increased by leased_sqft"
    PRD §3.3: "the property's occupied_sqft is decreased by the lease's
    leased_sqft"

    Design: Difficulty/compensating_invariant/activate_terminate_occupancy_invariant
    """
    prop = create_property(total_rentable_sqft=10000, name="InvProp2")
    tenant = create_tenant("InvTen2", "i2@x.com")
    lease = create_lease(prop["id"], tenant["id"], leased_sqft=2500, base_rent_cents_annual=0)
    validate_success(api.activate_lease(lease["id"], PM_HEADERS), 200)
    mid = validate_success(api.get_property(prop["id"], PM_HEADERS), 200)
    assert mid["occupied_sqft"] == 2500
    validate_success(api.terminate_lease(lease["id"], PM_HEADERS), 200)
    end = validate_success(api.get_property(prop["id"], PM_HEADERS), 200)
    assert end["occupied_sqft"] == 0
