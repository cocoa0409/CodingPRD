"""Non-linear state machines, transitive cascades, and conserved-quantity
invariants.

Covers the contract reopen cycle, the permit reject/reapply loop, the depth-4
cancel cascade, the depth-2 interment cascade, and the trust/plot conservation
invariants.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_funeral_home, create_gpl_item, create_venue, create_plot,
    create_disclosed_case, create_case, add_line, create_contract,
    setup_arranged_case, post_principal, submit_for_funding,
    reserve_plot, setup_reserved_plot, setup_case_interment_ready,
    apply_permit, issue_permit, schedule_chapel,
)

ADMIN = TEST_USERS["admin_headers"]
ARRANGER = TEST_USERS["arranger_headers"]
TRUST = TEST_USERS["trust_officer_headers"]
CLERK = TEST_USERS["cemetery_clerk_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ==========================================================================
# non_linear_state_machine / contract_pending_funding_revert_to_draft_cycle
# ==========================================================================
def test_reopen_preneed_contract_returns_to_draft(api):
    """PRD §3.6: "An Arranger may reopen a contract, bouncing it from
    PENDING_FUNDING back to DRAFT so the statement can be amended and then
    resubmitted — a deliberate cyclic loop."

    Design: Difficulty/non_linear_state_machine/contract_pending_funding_revert_to_draft_cycle
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="PRENEED_TRUST", case_mode="PRENEED", svc_price=200000)
    submit_for_funding(contract["id"])

    reopened = validate_success(api.reopen_contract(contract["id"], ARRANGER))
    assert reopened["status"] == "DRAFT"


def test_reopened_contract_can_be_resubmitted(api):
    """PRD §3.6: "An Arranger may reopen a contract, bouncing it from
    PENDING_FUNDING back to DRAFT so the statement can be amended and then
    resubmitted — a deliberate cyclic loop."
    PRD §3.6: "Once the GFS is issued, the Arranger submits the contract for
    funding, moving it from DRAFT to PENDING_FUNDING."

    After a reopen back to DRAFT the contract can be submitted again, completing
    the cycle.

    Design: Difficulty/non_linear_state_machine/contract_pending_funding_revert_to_draft_cycle
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="PRENEED_TRUST", case_mode="PRENEED", svc_price=200000)
    submit_for_funding(contract["id"])
    get_success_data(api.reopen_contract(contract["id"], ARRANGER))

    resubmitted = validate_success(api.submit_for_funding(contract["id"], ARRANGER))
    assert resubmitted["status"] == "PENDING_FUNDING"


# ==========================================================================
# non_linear_state_machine / permit_applied_branch_reject_then_reapply_loop
# ==========================================================================
def test_rejected_permit_reapplies_back_to_applied(api):
    """PRD §3.7: "Re-applying a REJECTED permit moves it back to APPLIED so it
    can be re-evaluated, and increments its version".

    Design: Difficulty/non_linear_state_machine/permit_applied_branch_reject_then_reapply_loop
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    dc = apply_permit(case["id"], "DEATH_CERTIFICATE")
    get_success_data(api.reject_permit(dc["id"], REGISTRAR))

    reapplied = validate_success(api.reapply_permit(dc["id"], REGISTRAR))
    assert reapplied["status"] == "APPLIED"


def test_reapplied_permit_can_then_be_issued(api):
    """PRD §3.7: "Issuing a permit supplies the reference_number to record and is
    allowed only when the permit is APPLIED".

    After the REJECTED -> APPLIED reapply, the permit re-enters the issue branch
    and can be ISSUED.

    Design: Difficulty/non_linear_state_machine/permit_applied_branch_reject_then_reapply_loop
    """
    home = create_funeral_home()
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    dc = apply_permit(case["id"], "DEATH_CERTIFICATE")
    get_success_data(api.reject_permit(dc["id"], REGISTRAR))
    get_success_data(api.reapply_permit(dc["id"], REGISTRAR))

    issued = validate_success(api.issue_permit(dc["id"], {"reference_number": "DC-1001"}, REGISTRAR))
    assert issued["status"] == "ISSUED"


# ==========================================================================
# transitive_cascade / case_cancel_void_refund_release_plot_cancel_events_depth4
# ==========================================================================
def test_cancel_case_drives_depth4_void_release_cascade(api):
    """PRD §3.11: "As the first link, if a contract exists for the case and it is
    neither VOID nor SETTLED, the contract's status becomes VOID."
    PRD §3.11: "for every posted principal or earnings deposit on the contract
    the system creates a compensating REFUND trust deposit of equal amount and
    marks the original deposit REFUNDED, so the contract's trust_principal_cents
    returns to 0"
    PRD §3.11: "if a plot has this case as its reserved_case_id and is RESERVED,
    the plot is released — its status returns to AVAILABLE, its reserved_case_id
    is cleared to null, and its locked_price_cents is cleared to null"
    PRD §3.11: "every SCHEDULED event of the case is moved to CANCELLED."

    Design: Difficulty/transitive_cascade/case_cancel_void_refund_release_plot_cancel_events_depth4
    """
    home = create_funeral_home(name="Rose Hill", sales_tax_pct=0.08,
                               state_trust_pct=0.90, chapel_buffer_minutes=30)
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          preneed_trustable=True, unit_price_cents=200000)
    venue = create_venue(home["id"], name="Main Chapel", capacity=120)
    plot = create_plot(home["id"], section="A", plot_code="A-12", current_price_cents=80000)
    case = create_disclosed_case(home["id"], case_mode="PRENEED", date_of_death=None)
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "PRENEED_TRUST")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 360000)
    reserve_plot(plot["id"], case["id"], plot["version"])
    event = schedule_chapel(case["id"], venue["id"],
                            "2026-06-10T15:00:00.000Z", "2026-06-10T16:00:00.000Z")

    cancelled = validate_success(api.cancel_case(case["id"], ARRANGER))
    assert cancelled["arrangement_status"] == "CANCELLED"

    contract_after = validate_success(api.get_contract(contract["id"], TRUST))
    assert contract_after["status"] == "VOID"
    assert contract_after["trust_principal_cents"] == 0

    plot_after = validate_success(api.get_plot(plot["id"], CLERK))
    assert plot_after["status"] == "AVAILABLE"
    assert plot_after["reserved_case_id"] is None

    event_after = validate_success(api.get_event(event["id"], ARRANGER))
    assert event_after["status"] == "CANCELLED"


def test_cancel_releases_verified_insurance_assignment(api):
    """PRD §3.11: "every VERIFIED insurance assignment on the contract is moved
    to RELEASED."
    PRD §3.5: "An assignment is moved to RELEASED only as part of the
    contract-void cascade; releasing recomputes the contract's
    funded_amount_cents so it drops the assigned value".

    Design: Difficulty/transitive_cascade/case_cancel_void_refund_release_plot_cancel_events_depth4
    """
    home, case, svc, contract = setup_arranged_case(
        funding_type="INSURANCE_ASSIGNMENT", case_mode="AT_NEED", svc_price=100000)
    assign = get_success_data(api.attach_insurance_assignment(
        contract["id"], {"policy_number": "P-1", "carrier": "Acme Life",
                         "assigned_value_cents": 100000}, TRUST))
    get_success_data(api.verify_insurance_assignment(assign["id"], TRUST))

    get_success_data(api.cancel_case(case["id"], ARRANGER))

    contract_after = validate_success(api.get_contract(contract["id"], TRUST))
    assert contract_after["status"] == "VOID"
    assign_after = validate_success(api.get_insurance_assignment(assign["id"], TRUST))
    assert assign_after["status"] == "RELEASED"


# ==========================================================================
# transitive_cascade / permit_issue_makes_case_ready_then_inter_makes_interred_depth2
# ==========================================================================
def test_inter_drives_plot_and_case_to_interred_depth2(api):
    """PRD §3.8: "Interment is the head of a two-link close cascade: the plot's
    status advances to INTERRED, and because the plot has become INTERRED, the
    reserved case's interment_status advances to INTERRED".

    Design: Difficulty/transitive_cascade/permit_issue_makes_case_ready_then_inter_makes_interred_depth2
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="A", plot_code="A-13", current_price_cents=80000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    setup_case_interment_ready(home["id"], case["id"])
    reserve_plot(plot["id"], case["id"], plot["version"])

    plot_after = validate_success(api.inter_plot(plot["id"], CLERK))
    assert plot_after["status"] == "INTERRED"

    case_after = validate_success(api.get_case(case["id"], ARRANGER))
    assert case_after["interment_status"] == "INTERRED"


def test_issuing_both_permits_bubbles_case_ready_then_inter(api):
    """PRD §3.7: "a case moves NOT_READY → READY automatically exactly when one
    issued death-certificate permit and one issued burial-transit permit both
    exist for the case."
    PRD §3.8: "Interment ... is allowed only when the plot is RESERVED ... and
    the interment axis of the case holding that plot is READY".

    Design: Difficulty/transitive_cascade/permit_issue_makes_case_ready_then_inter_makes_interred_depth2
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="A", plot_code="A-14", current_price_cents=80000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    dc = apply_permit(case["id"], "DEATH_CERTIFICATE")
    issue_permit(dc["id"], "DC-1")
    bt = apply_permit(case["id"], "BURIAL_TRANSIT")
    issue_permit(bt["id"], "BT-1")

    ready = validate_success(api.get_case(case["id"], ARRANGER))
    assert ready["interment_status"] == "READY"

    reserve_plot(plot["id"], case["id"], plot["version"])
    plot_after = validate_success(api.inter_plot(plot["id"], CLERK))
    assert plot_after["status"] == "INTERRED"


# ==========================================================================
# compensating_invariant / trust_principal_conserved_across_deposit_and_void_refund
# ==========================================================================
def test_trust_principal_and_home_balance_conserved_after_void(api):
    """PRD §3.11: "for every posted principal or earnings deposit on the contract
    the system creates a compensating REFUND trust deposit of equal amount and
    marks the original deposit REFUNDED, so the contract's trust_principal_cents
    returns to 0"
    PRD §3.11: "After the cascade, the home's trust_balance_cents and the
    released plot's availability are both restored to their pre-funding state."

    Design: Difficulty/compensating_invariant/trust_principal_conserved_across_deposit_and_void_refund
    """
    home = create_funeral_home(name="Rose Hill", sales_tax_pct=0.08, state_trust_pct=0.90)
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          preneed_trustable=True, unit_price_cents=200000)
    case = create_disclosed_case(home["id"], case_mode="PRENEED", date_of_death=None)
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "PRENEED_TRUST")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 360000)

    get_success_data(api.cancel_case(case["id"], ARRANGER))

    contract_after = validate_success(api.get_contract(contract["id"], TRUST))
    assert contract_after["status"] == "VOID"
    assert contract_after["trust_principal_cents"] == 0

    home_after = validate_success(api.get_funeral_home(home["id"], ADMIN))
    assert home_after["trust_balance_cents"] == 0


def test_home_trust_balance_reflects_posted_principal_before_void(api):
    """PRD §2.8: "Each funeral home additionally exposes a rolled-up
    trust_balance_cents, a conserved global quantity equal to the sum, across all
    of that home's contracts, of each contract's principal corpus plus its
    credited earnings."

    A 360000 posted principal lifts trust_balance_cents to 360000 before any void.

    Design: Difficulty/compensating_invariant/trust_principal_conserved_across_deposit_and_void_refund
    """
    home = create_funeral_home(name="Rose Hill", sales_tax_pct=0.08, state_trust_pct=0.90)
    svc = create_gpl_item(home["id"], code="SVC-BASIC", name="Basic services",
                          category="SERVICE", taxable=False, non_declinable=True,
                          preneed_trustable=True, unit_price_cents=200000)
    case = create_disclosed_case(home["id"], case_mode="PRENEED", date_of_death=None)
    add_line(case["id"], svc["id"])
    contract = create_contract(case["id"], "PRENEED_TRUST")
    get_success_data(api.issue_gfs(case["id"], ARRANGER))
    post_principal(contract["id"], 360000)

    home_after = validate_success(api.get_funeral_home(home["id"], ADMIN))
    assert home_after["trust_balance_cents"] == 360000


# ==========================================================================
# compensating_invariant / plot_inventory_conserved_across_reserve_and_release
# ==========================================================================
def test_release_restores_plot_to_available_clearing_lock(api):
    """PRD §3.8: "Release is allowed only when the plot is RESERVED ... Release
    clears reserved_case_id and locked_price_cents back to null and increments
    the plot's version."

    Reserve then release returns the plot to AVAILABLE with reserved_case_id and
    locked_price_cents both null — inventory conserved.

    Design: Difficulty/compensating_invariant/plot_inventory_conserved_across_reserve_and_release
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="C", plot_code="C-1", current_price_cents=70000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")
    reserve_plot(plot["id"], case["id"], plot["version"])

    released = validate_success(api.release_plot(plot["id"], CLERK))
    assert released["status"] == "AVAILABLE"
    assert released["reserved_case_id"] is None
    assert released["locked_price_cents"] is None


def test_reserve_sets_locked_price_and_reserved_case(api):
    """PRD §3.8: "On success the plot moves to RESERVED, its reserved_case_id is
    set to the supplied case, and its locked_price_cents is snapshotted from
    current_price_cents as a price lock".

    The reserve half of the conserved reserve/release pair.

    Design: Difficulty/compensating_invariant/plot_inventory_conserved_across_reserve_and_release
    """
    home = create_funeral_home()
    plot = create_plot(home["id"], section="C", plot_code="C-2", current_price_cents=70000)
    case = create_case(home["id"], case_mode="AT_NEED",
                       date_of_death="2026-06-01T00:00:00.000Z")

    reserved = reserve_plot(plot["id"], case["id"], plot["version"])
    assert reserved["status"] == "RESERVED"
    assert reserved["reserved_case_id"] == case["id"]
    assert reserved["locked_price_cents"] == 70000
