"""State-machine corner cases: initial states, invalid transitions, terminal
lockdown, precondition enforcement, side effects, idempotency, revision loop
(breadth queue B — state_machines section).
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_property, create_tenant, create_lease, create_active_lease,
    setup_lease_with_ti_allowance, request_ti_draw,
    setup_issued_estoppel, create_pool, add_line_item,
    create_reconciliation, submit_reconciliation,
    make_tenant_headers, make_property_manager_headers, make_accountant_headers,
    PM_HEADERS, ACCT_HEADERS,
)


def test_new_lease_starts_in_draft(api):
    """PRD §3.3: "A new lease begins in status DRAFT with outstanding_balance_cents
    and ti_drawn_cents both at 0."

    Design: Corner/state_machines/lease_initial_state_is_draft
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_lease(prop["id"], tenant["id"], leased_sqft=1000, base_rent_cents_annual=0)
    assert lease["status"] == "DRAFT"


def test_activate_already_active_lease_rejected(api):
    """PRD §3.3: "Activation, available to a PropertyManager, advances a lease from
    DRAFT to ACTIVE. It is permitted only when the lease is DRAFT"
    PRD §2.9: "the state guard fires if the target is not in a state that permits
    the transition (ERR_INVALID_STATE)"

    Design: Corner/state_machines/activate_already_active_lease_returns_invalid_state
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=0)
    res = api.activate_lease(lease["id"], PM_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["status"] == "ACTIVE"


def test_terminate_terminated_lease_locked_down(api):
    """PRD §3.3: "Termination advances a lease from ACTIVE or HOLDOVER to
    TERMINATED."
    PRD §2.9: "the state guard fires if the target is not in a state that permits
    the transition (ERR_INVALID_STATE)"

    Design: Corner/state_machines/terminate_terminal_lease_locked_down
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=2500,
                                base_rent_cents_annual=0)
    validate_success(api.terminate_lease(lease["id"], PM_HEADERS), 200)
    res = api.terminate_lease(lease["id"], PM_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    prop_after = validate_success(api.get_property(prop["id"], PM_HEADERS), 200)
    assert prop_after["occupied_sqft"] == 0


def test_ti_draw_approve_requires_active_lease(api):
    """PRD §3.6: "Approval is permitted when the draw is REQUESTED, the referenced
    lease is ACTIVE or HOLDOVER, and the remaining allowance covers it"

    Design: Corner/state_machines/ti_draw_approve_precondition_lease_active
    """
    prop, tenant, lease = setup_lease_with_ti_allowance(
        ti_allowance_cents=1000000, activate=False)  # lease stays DRAFT
    draw = request_ti_draw(lease["id"], 500000)
    res = api.approve_ti_draw(draw["id"], ACCT_HEADERS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_ti_draw(draw["id"], ACCT_HEADERS), 200)
    assert after["status"] == "REQUESTED"


def test_ti_draw_approve_side_effects(api):
    """PRD §3.6: "On approval the draw becomes APPROVED, the lease's ti_drawn_cents
    is recomputed to include this draw (advancing the lease's version), and a
    TI_DRAW ledger entry of minus the draw's amount_cents is posted as a
    landlord-funded credit to the tenant, refreshing outstanding_balance_cents."

    Design: Corner/state_machines/ti_draw_approve_side_effect_drawn_and_ledger
    """
    prop, tenant, lease = setup_lease_with_ti_allowance(
        ti_allowance_cents=1000000, base_rent_cents_annual=0, activate=True)
    draw = request_ti_draw(lease["id"], 500000)
    approved = validate_success(api.approve_ti_draw(draw["id"], ACCT_HEADERS), 200)
    assert approved["status"] == "APPROVED"
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["ti_drawn_cents"] == 500000
    assert after["outstanding_balance_cents"] == -500000


def test_estoppel_respond_twice_rejected(api):
    """PRD §3.10: "Only the owning Tenant may respond, and only to an ISSUED
    certificate."
    PRD §3.10: "Both CONFIRMED and DISPUTED are terminal."

    Design: Corner/state_machines/estoppel_respond_twice_idempotency_guard
    """
    prop, tenant, lease, est = setup_issued_estoppel(asserted_balance_cents=0)
    th = make_tenant_headers(tenant["id"])
    confirmed = validate_success(api.respond_estoppel(
        est["id"], {"tenant_response": "CONFIRMED"}, th), 200)
    assert confirmed["status"] == "CONFIRMED"
    res = api.respond_estoppel(est["id"], {"tenant_response": "CONFIRMED"}, th)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_recon_return_revision_loop_bumps_version(api):
    """PRD §3.7: "An Accountant may return an IN_REVIEW reconciliation to DRAFT for
    correction; this revision step sets the status back to DRAFT and advances the
    reconciliation's version by one"
    PRD §2.1: an integer "version that starts at 1 and increases by exactly one on
    every mutation" — submission (DRAFT -> IN_REVIEW) is itself a mutation.
    PRD §2.7: through the revision loop "the reconciliation's version advances each
    step." So create=1, submit=2, return=3.

    Design: Corner/state_machines/recon_return_revision_loop_bumps_version
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=1000)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 1000, "RECOVERABLE", is_variable=False)
    recon = create_reconciliation(lease["id"], pool["id"], 2025)
    assert recon["version"] == 1
    submit_reconciliation(recon["id"], "pm-001")
    returned = validate_success(
        api.return_reconciliation(recon["id"], make_accountant_headers("acct-001")), 200)
    assert returned["status"] == "DRAFT"
    assert returned["version"] == 3
