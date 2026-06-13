"""Non-linear state machines and transitive cascades.

Translates difficulty queue (A) instances under rules non_linear_state_machine
and transitive_cascade.
"""
from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    setup_active_order,
    setup_order_with_principal,
    setup_rejected_modification,
    setup_approved_modification,
    setup_order_with_proposed_enforcement,
    setup_order_with_certified_enforcement,
    create_modification,
    propose_enforcement,
    order_version,
    create_remittance,
)

CW = TEST_USERS["case_worker_headers"]
FO = TEST_USERS["finance_officer_headers"]
SUP = TEST_USERS["supervisor_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / modification_cyclic_rejected_back_to_draft
# ---------------------------------------------------------------------------
def test_rejected_modification_revises_back_to_draft(api):
    """PRD §3.9: "A rejected modification is not dead: a `CaseWorker` revises it, permitted
    only while `status` is `REJECTED` (otherwise `ERR_INVALID_STATE`), which cycles the
    `status` back to `DRAFT` for re-submission."

    Design: Difficulty/non_linear_state_machine/modification_cyclic_rejected_back_to_draft
    """
    cp, ncp, emp, order, mod = setup_rejected_modification()
    revised = validate_success(api.revise_modification(mod["id"], CW))
    assert revised["status"] == "DRAFT"


def test_modification_cycle_resubmits_after_revise(api):
    """PRD §3.9: "A `CaseWorker` submits a draft, permitted only while `status` is `DRAFT`
    (otherwise `ERR_INVALID_STATE`) and only when `proposed_current_support_cents` is greater
    than zero (otherwise `ERR_INVALID_AMOUNT`); submission moves the `status` to `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/modification_cyclic_rejected_back_to_draft
    """
    cp, ncp, emp, order, mod = setup_rejected_modification()
    validate_success(api.revise_modification(mod["id"], CW))
    resubmitted = validate_success(api.submit_modification(mod["id"], CW))
    assert resubmitted["status"] == "SUBMITTED", (
        "the same modification row cycles REJECTED->DRAFT->SUBMITTED")


# ---------------------------------------------------------------------------
# non_linear_state_machine / support_order_parallel_obligation_and_enforcement
# ---------------------------------------------------------------------------
def test_suspend_does_not_disturb_enforcement_dimension(api):
    """PRD §2.5: "A `SupportOrder` carries two independent status dimensions that evolve
    separately."

    Design: Difficulty/non_linear_state_machine/support_order_parallel_obligation_and_enforcement
    """
    cp, ncp, emp, order, enf = setup_order_with_proposed_enforcement(
        current_support_cents=50000, action_type="TAX_INTERCEPT")
    assert order["enforcement_status"] == "INTERCEPT_PENDING"
    suspended = validate_success(api.suspend_support_order(order["id"], CW))
    assert suspended["obligation_status"] == "SUSPENDED"
    assert suspended["enforcement_status"] == "INTERCEPT_PENDING", (
        "suspending the obligation dimension must not move the enforcement dimension")


def test_enforcement_propose_does_not_disturb_obligation_dimension(api):
    """PRD §2.5: "The two dimensions never share a value and are advanced by different
    triggers; an order can be `ACTIVE` while simultaneously `INTERCEPT_ACTIVE`."

    Design: Difficulty/non_linear_state_machine/support_order_parallel_obligation_and_enforcement
    """
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=50000)
    assert order["obligation_status"] == "ACTIVE"
    enf = propose_enforcement(order["id"], action_type="TAX_INTERCEPT")
    after = validate_success(api.get_support_order(order["id"], CW))
    assert after["enforcement_status"] == "INTERCEPT_PENDING"
    assert after["obligation_status"] == "ACTIVE", (
        "proposing enforcement advances only the enforcement dimension")


# ---------------------------------------------------------------------------
# transitive_cascade / modification_apply_cascade_depth3
# ---------------------------------------------------------------------------
def test_modification_apply_updates_order_amount_and_status(api):
    """PRD §3.9: "On success the modification moves to the terminal `APPLIED`; the linked
    order's `current_support_cents` is set to the modification's `proposed_current_support_cents`;
    the order's `obligation_status` moves from `ACTIVE` to `MODIFIED` as a cross-entity transition"

    Design: Difficulty/transitive_cascade/modification_apply_cascade_depth3
    """
    cp, ncp, emp, order, mod = setup_approved_modification(
        current_support_cents=40000, proposed=60000)
    ver = order_version(order["id"])
    validate_success(api.apply_modification(mod["id"], {"expected_support_order_version": ver}, CW))
    after = validate_success(api.get_support_order(order["id"], CW))
    assert after["current_support_cents"] == 60000
    assert after["obligation_status"] == "MODIFIED"


def test_modification_apply_recomputes_obligor_total(api):
    """PRD §3.9: "the obligor's `total_current_support_cents` is recomputed as a transitive
    cascade"

    Design: Difficulty/transitive_cascade/modification_apply_cascade_depth3
    """
    cp, ncp, emp, order, mod = setup_approved_modification(
        current_support_cents=40000, proposed=60000)
    before = validate_success(api.get_noncustodial_party(ncp["id"], CW))
    assert before["total_current_support_cents"] == 40000
    ver = order_version(order["id"])
    validate_success(api.apply_modification(mod["id"], {"expected_support_order_version": ver}, CW))
    after = validate_success(api.get_noncustodial_party(ncp["id"], CW))
    # Order is now MODIFIED (still counted in ACTIVE/MODIFIED set) at the new amount.
    assert after["total_current_support_cents"] == 60000


# ---------------------------------------------------------------------------
# transitive_cascade / allocation_clears_arrears_cascade_to_enforcement_lifted
# ---------------------------------------------------------------------------
def test_allocation_clearing_arrears_satisfies_enforcement(api):
    """PRD §3.8: "when a remittance allocation drives the order's `arrears_principal_cents`
    and `interest_balance_cents` both to zero, the system moves the action's `status` to the
    terminal `SATISFIED`"

    Design: Difficulty/transitive_cascade/allocation_clears_arrears_cascade_to_enforcement_lifted
    """
    cp, ncp, emp, order, enf = setup_order_with_certified_enforcement(
        current_support_cents=50000, action_type="LICENSE_SUSPENSION")
    # order: due 50000, principal 50000, interest 0; enforcement INTERCEPT_ACTIVE.
    rem = create_remittance(emp["id"], ncp["id"],
                            disposable_earnings_cents=300000, gross_remitted_cents=100000)
    validate_success(api.allocate_remittance(rem["id"], FO))
    enf_after = validate_success(api.get_enforcement_action(enf["id"], CW))
    assert enf_after["status"] == "SATISFIED"


def test_allocation_clearing_arrears_lifts_enforcement_status(api):
    """PRD §3.8: "and, as a transitive cascade, advances the order's `enforcement_status`
    from `INTERCEPT_ACTIVE` to `LIFTED`."

    Design: Difficulty/transitive_cascade/allocation_clears_arrears_cascade_to_enforcement_lifted
    """
    cp, ncp, emp, order, enf = setup_order_with_certified_enforcement(
        current_support_cents=50000, action_type="LICENSE_SUSPENSION")
    rem = create_remittance(emp["id"], ncp["id"],
                            disposable_earnings_cents=300000, gross_remitted_cents=100000)
    validate_success(api.allocate_remittance(rem["id"], FO))
    after = validate_success(api.get_support_order(order["id"], CW))
    assert after["arrears_principal_cents"] == 0
    assert after["interest_balance_cents"] == 0
    assert after["enforcement_status"] == "LIFTED"
