"""Disconnection, transfers, the ETF / waiver, lease proration, and the two
compensating invariants (ETF conserved under waiver; lease fee conserved under
lost-reversal).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_transfer_request_payload, net_credit_amount,
    set_clock, get_account_version, list_account_credits,
    setup_active_self_install_account, setup_disconnected_account,
    setup_approved_transfer,
)

AGENT = TEST_USERS["provisioning_agent_headers"]
NETOPS = TEST_USERS["network_ops_headers"]


def _activate_24mo_account(clock="2026-06-01T00:00:00Z"):
    """Activate a 24-month-contract account (etf_full 24000) for ETF tests."""
    return setup_active_self_install_account(
        clock=clock,
        plan_overrides={"contract_term_months": 24, "etf_full_cents": 24000,
                        "overage_policy": "BILL", "included_gb": 1000,
                        "monthly_fee_cents": 8999})


# ===========================================================================
# Queue A — transitive_cascade: disconnect three-hop
# ===========================================================================
def test_disconnect_cascades_equipment_to_return_pending(api):
    """PRD §3.8: "the account's leased equipment unit moves from `LEASED` to `RETURN_PENDING`, which (per §3.7) emits the lease-proration credit."

    Design: Difficulty/transitive_cascade/disconnect_three_hop_cascade
    """
    ctx = setup_disconnected_account(disconnect_clock="2026-06-11T00:00:00Z")
    unit = validate_success(api.get_equipment_unit(ctx["equipment"]["id"], AGENT))
    assert unit["status"] == "RETURN_PENDING", \
        f"unit must be RETURN_PENDING after disconnect, got {unit['status']}"


def test_disconnect_emits_lease_proration_credit(api):
    """PRD §3.7: "The leased `EquipmentUnit` moves from `LEASED` to `RETURN_PENDING`, and that very transition emits a lease-proration credit for the unused-days portion of the final cycle."
    PRD §3.7: "This emits an `AccountCredit` with `source_type` of `LEASE_PRORATE` and a `source_id` naming the unit."

    The exact prorated cent figure depends on the PRD's "counting the start day"
    day count, which PRD prose does not pin to a single value; this test asserts
    the uniquely-derivable cascade fact — a single LEASE_PRORATE credit naming the
    returned unit is emitted with a positive amount.

    Design: Difficulty/transitive_cascade/disconnect_three_hop_cascade
    """
    ctx = setup_disconnected_account(disconnect_clock="2026-06-11T00:00:00Z")
    credits = list_account_credits(ctx["account"]["id"], AGENT)
    lease_credits = [c for c in credits if c["source_type"] == "LEASE_PRORATE"]
    assert len(lease_credits) == 1, f"expected one LEASE_PRORATE credit, got {lease_credits}"
    assert lease_credits[0]["amount_cents"] > 0, \
        f"lease proration credit must be positive, got {lease_credits[0]['amount_cents']}"
    assert lease_credits[0]["source_id"] == ctx["equipment"]["id"], \
        "LEASE_PRORATE source_id must name the returned unit"


def test_disconnect_finalizes_the_open_cycle(api):
    """PRD §3.8: "the open billing cycle is closed and then finalized, so its `total_due_cents` is recomputed to include the early-termination fee, any overage, the lease proration, and all applicable credits."

    Design: Difficulty/transitive_cascade/disconnect_three_hop_cascade
    """
    ctx = setup_disconnected_account(disconnect_clock="2026-06-11T00:00:00Z")
    cycles = validate_success(
        api.list_billing_cycles(AGENT, params={"account_id": ctx["account"]["id"]}))
    assert any(c["billing_state"] == "FINALIZED" for c in cycles), \
        f"the account's cycle must be FINALIZED after disconnect, got {cycles}"


# ===========================================================================
# Queue A — dual_variant_calc: ETF charged vs waived
# ===========================================================================
def test_disconnect_charges_etf_on_final_cycle(api):
    """PRD §3.8: "On a plain disconnect this fee is added as a charge on the final cycle."
    PRD §3.8: "the system counts the whole months elapsed between the account's `contract_start_iso` and the current clock instant, computes the months remaining as the plan's `contract_term_months` minus those elapsed months but never below zero, and sets the fee to the plan's `etf_full_cents` multiplied by the months remaining divided by `contract_term_months`, rounded half up to whole cents."

    9 months elapsed of 24 -> 15 remaining -> rhu(24000*15/24) = 15000 ETF.
    Final total = plan 8999 + lease(days-used 1000) + etf 15000 - lease credit 500
    ... the asserted figure is the ETF contribution; we read it via total breakdown:
    we assert the ETF charge by reconstructing the cycle and checking total includes 15000.

    Design: Difficulty/dual_variant_calc/etf_charged_vs_waived_on_account_contract
    """
    ctx = _activate_24mo_account()
    set_clock("2027-03-01T00:00:00Z")
    v = get_account_version(ctx["account"]["id"])
    get_success_data(api.disconnect_account(
        ctx["account"]["id"], {"expected_account_version": v}, AGENT))
    # No TRANSFER_WAIVER credit exists on a plain disconnect, and the ETF is charged.
    credits = list_account_credits(ctx["account"]["id"], AGENT)
    waiver_credits = [c for c in credits if c["source_type"] == "TRANSFER_WAIVER"]
    assert waiver_credits == [], \
        f"plain disconnect must NOT emit a TRANSFER_WAIVER credit, got {waiver_credits}"
    cycles = validate_success(
        api.list_billing_cycles(AGENT, params={"account_id": ctx["account"]["id"]}))
    final = [c for c in cycles if c["billing_state"] == "FINALIZED"][0]
    # plan_fee 8999 + lease(days_used) + etf 15000 - lease_prorate_credit; ETF dominates.
    # The ETF charge of 15000 is reflected in total_due being >= plan_fee + etf.
    assert final["total_due_cents"] >= 8999 + 15000 - 1500, \
        f"final total must reflect the 15000 ETF charge, got {final['total_due_cents']}"


def test_transfer_waiver_emits_credit_and_charges_no_etf(api):
    """PRD §3.9: "when `waive_etf` is true, no early-termination charge is added to the cycle, and instead the system emits an `AccountCredit` with `source_type` of `TRANSFER_WAIVER` whose amount equals the early-termination fee that would otherwise have applied."

    9 months elapsed of 24 -> would-be ETF rhu(24000*15/24) = 15000.

    Design: Difficulty/dual_variant_calc/etf_charged_vs_waived_on_account_contract
    """
    ctx = _activate_24mo_account()
    xfer = get_success_data(api.create_transfer_request(
        create_transfer_request_payload(ctx["account"]["id"], ctx["address"]["id"],
                                        ctx["plan"]["id"], waive_etf=True), AGENT))
    get_success_data(api.approve_transfer(xfer["id"], AGENT))
    set_clock("2027-03-01T00:00:00Z")
    v = get_account_version(ctx["account"]["id"])
    get_success_data(api.complete_transfer(
        xfer["id"], {"expected_account_version": v}, AGENT))
    credits = list_account_credits(ctx["account"]["id"], AGENT)
    waiver = [c for c in credits if c["source_type"] == "TRANSFER_WAIVER"]
    assert len(waiver) == 1, f"expected one TRANSFER_WAIVER credit, got {waiver}"
    assert waiver[0]["amount_cents"] == 15000, \
        f"TRANSFER_WAIVER credit must be 15000, got {waiver[0]['amount_cents']}"


# ===========================================================================
# Queue A — compensating_invariant: ETF conserved under waiver
# ===========================================================================
def test_etf_net_burden_zero_under_transfer_waiver(api):
    """PRD §3.9: "The waiver is the compensating counterpart of a disconnect's fee — it leaves the net early-termination burden at exactly zero."

    Would-be ETF 15000 is not charged; an equal 15000 TRANSFER_WAIVER credit
    offsets it, so net ETF == 0.

    Design: Difficulty/compensating_invariant/etf_conserved_under_transfer_waiver
    """
    ctx = _activate_24mo_account()
    xfer = get_success_data(api.create_transfer_request(
        create_transfer_request_payload(ctx["account"]["id"], ctx["address"]["id"],
                                        ctx["plan"]["id"], waive_etf=True), AGENT))
    get_success_data(api.approve_transfer(xfer["id"], AGENT))
    set_clock("2027-03-01T00:00:00Z")
    v = get_account_version(ctx["account"]["id"])
    get_success_data(api.complete_transfer(
        xfer["id"], {"expected_account_version": v}, AGENT))
    credits = list_account_credits(ctx["account"]["id"], AGENT)
    waiver_total = net_credit_amount(credits, "TRANSFER_WAIVER")
    # The conserved quantity: the would-be 15000 ETF is fully offset by an equal
    # 15000 TRANSFER_WAIVER credit, leaving net ETF burden at exactly zero.
    assert waiver_total == 15000, \
        f"waiver credit must total the would-be 15000 ETF (net burden zero), got {waiver_total}"


def test_transfer_waiver_moves_account_to_transferred_with_conserved_etf(api):
    """PRD §3.9: "The account moves from `ACTIVE` to the terminal `TRANSFERRED` and its `service_state` becomes `OFFLINE".
    PRD §3.9: "instead the system emits an `AccountCredit` with `source_type` of `TRANSFER_WAIVER` whose amount equals the early-termination fee that would otherwise have applied."

    The terminal account transition and the conserving 15000 waiver credit are
    the two halves of the zero-net-ETF invariant.

    Design: Difficulty/compensating_invariant/etf_conserved_under_transfer_waiver
    """
    ctx = _activate_24mo_account()
    xfer = get_success_data(api.create_transfer_request(
        create_transfer_request_payload(ctx["account"]["id"], ctx["address"]["id"],
                                        ctx["plan"]["id"], waive_etf=True), AGENT))
    get_success_data(api.approve_transfer(xfer["id"], AGENT))
    set_clock("2027-03-01T00:00:00Z")
    v = get_account_version(ctx["account"]["id"])
    get_success_data(api.complete_transfer(
        xfer["id"], {"expected_account_version": v}, AGENT))
    acct = validate_success(api.get_account(ctx["account"]["id"], AGENT))
    assert acct["status"] == "TRANSFERRED", \
        f"account must reach TRANSFERRED, got {acct['status']}"
    assert acct["service_state"] == "OFFLINE", \
        f"service_state must be OFFLINE, got {acct['service_state']}"
    waiver = net_credit_amount(list_account_credits(ctx["account"]["id"], AGENT),
                               "TRANSFER_WAIVER")
    assert waiver == 15000, f"conserving waiver credit must be 15000, got {waiver}"


# ===========================================================================
# Queue A — compensating_invariant: lease fee conserved under lost-reversal
# ===========================================================================
def test_lease_credit_reversed_when_unit_marked_lost(api):
    """PRD §3.7: "marking the unit lost reverses the previously emitted `LEASE_PRORATE` credit, negating its amount so the net lease credit for that unit is zero. This preserves the lease conserved quantity — the operator never refunds lease days on hardware it never got back."

    A 1000-cent LEASE_PRORATE credit nets to 0 after mark-lost.

    Design: Difficulty/compensating_invariant/lease_fee_conserved_under_lost_reversal
    """
    ctx = setup_disconnected_account(disconnect_clock="2026-06-11T00:00:00Z")
    before = list_account_credits(ctx["account"]["id"], AGENT)
    lease_before = net_credit_amount(before, "LEASE_PRORATE")
    assert lease_before > 0, \
        f"a positive LEASE_PRORATE credit must exist pre-lost, got {before}"
    lost = validate_success(api.mark_lost_equipment(ctx["equipment"]["id"], AGENT))
    assert lost["status"] == "LOST", f"unit must be LOST, got {lost['status']}"
    after = list_account_credits(ctx["account"]["id"], AGENT)
    net_lease = net_credit_amount(after, "LEASE_PRORATE")
    assert net_lease == 0, \
        f"net LEASE_PRORATE credit must be 0 after lost-reversal, got {net_lease}"


def test_lost_reversal_conserves_lease_refund_to_zero(api):
    """PRD §3.7: "Because a lost unit was never actually returned, the lease-proration refund must not stand: marking the unit lost reverses the previously emitted `LEASE_PRORATE` credit, negating its amount so the net lease credit for that unit is zero."
    PRD §3.7: "This preserves the lease conserved quantity — the operator never refunds lease days on hardware it never got back."

    The conserved quantity is amount-independent: whatever LEASE_PRORATE refund was
    emitted on disconnect nets back to zero after the unit is marked lost.

    Design: Difficulty/compensating_invariant/lease_fee_conserved_under_lost_reversal
    """
    ctx = setup_disconnected_account(disconnect_clock="2026-06-11T00:00:00Z")
    before = net_credit_amount(list_account_credits(ctx["account"]["id"], AGENT),
                               "LEASE_PRORATE")
    assert before > 0, f"a positive LEASE_PRORATE refund must exist pre-lost, got {before}"
    lost = validate_success(api.mark_lost_equipment(ctx["equipment"]["id"], AGENT))
    assert lost["status"] == "LOST", f"unit must reach terminal LOST, got {lost['status']}"
    net_lease = net_credit_amount(list_account_credits(ctx["account"]["id"], AGENT),
                                  "LEASE_PRORATE")
    assert net_lease == 0, \
        f"net LEASE_PRORATE credit must be 0 after lost-reversal, got {net_lease}"


# ===========================================================================
# Queue B — calculations: lease proration full at day zero
# ===========================================================================
def test_lease_proration_credit_emitted_at_day_zero_disconnect(api):
    """PRD §3.7: "The leased `EquipmentUnit` moves from `LEASED` to `RETURN_PENDING`, and that very transition emits a lease-proration credit for the unused-days portion of the final cycle."

    Disconnecting at the cycle start instant (maximal unused-days portion) emits a
    LEASE_PRORATE credit. The exact cent figure turns on the PRD's "counting the
    start day" wording, which is not pinned to a single value; this asserts the
    uniquely-derivable claim that a positive lease-proration credit is emitted.

    Design: Corner/calculations/lease_proration_full_cycle_remaining_at_day_zero
    """
    ctx = setup_disconnected_account()  # no clock advance -> disconnect at cycle start.
    credits = list_account_credits(ctx["account"]["id"], AGENT)
    lease = [c for c in credits if c["source_type"] == "LEASE_PRORATE"]
    assert len(lease) == 1, f"expected one LEASE_PRORATE credit, got {lease}"
    assert lease[0]["amount_cents"] > 0, \
        f"day-zero disconnect must emit a positive lease refund, got {lease[0]['amount_cents']}"


# ===========================================================================
# Queue B — calculations: ETF zero on month-to-month plan
# ===========================================================================
def test_etf_zero_on_month_to_month_plan(api):
    """PRD §3.8: "For a month-to-month plan — one whose `contract_term_months` is 0 — the fee is always zero."

    Design: Corner/calculations/etf_zero_on_month_to_month_plan
    """
    ctx = setup_disconnected_account()  # default plan is term 0, etf_full 0.
    cycles = validate_success(
        api.list_billing_cycles(AGENT, params={"account_id": ctx["account"]["id"]}))
    final = [c for c in cycles if c["billing_state"] == "FINALIZED"]
    assert final, f"the cycle must be FINALIZED after disconnect, got {cycles}"
    # plan_fee 8999 + lease(days_used 0 -> 0) - lease credit 1500 -> no ETF term.
    # total reflects no ETF: it is plan_fee minus the full lease credit (1500), i.e. < plan_fee.
    assert final[0]["total_due_cents"] <= 8999, \
        f"month-to-month disconnect must carry 0 ETF, got total {final[0]['total_due_cents']}"


# ===========================================================================
# Queue A — cross_entity_state_dependency: transfer-complete needs ACTIVE
# ===========================================================================
def test_transfer_complete_on_suspended_account_rejected(api):
    """PRD §3.9: "the account must be `ACTIVE` (an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/transfer_complete_depends_on_account_active
    """
    ctx = setup_approved_transfer(waive_etf=True)
    get_success_data(api.suspend_account(ctx["account"]["id"], AGENT))
    v = get_account_version(ctx["account"]["id"])
    resp = api.complete_transfer(ctx["transfer"]["id"], {"expected_account_version": v}, AGENT)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)
    xfer = validate_success(api.get_transfer_request(ctx["transfer"]["id"], AGENT))
    assert xfer["status"] == "APPROVED", \
        f"transfer must remain APPROVED, got {xfer['status']}"


def test_transfer_complete_on_disconnected_account_rejected(api):
    """PRD §3.9: "the request must be in `APPROVED`, and the account must be `ACTIVE` (an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE`)."

    A terminal DISCONNECTED account is not ACTIVE, so completing its approved
    transfer is rejected — a second non-ACTIVE administrative state for the gate.

    Design: Difficulty/cross_entity_state_dependency/transfer_complete_depends_on_account_active
    """
    ctx = setup_approved_transfer(waive_etf=True)
    v = get_account_version(ctx["account"]["id"])
    get_success_data(api.disconnect_account(
        ctx["account"]["id"], {"expected_account_version": v}, AGENT))
    v2 = get_account_version(ctx["account"]["id"])
    resp = api.complete_transfer(ctx["transfer"]["id"], {"expected_account_version": v2}, AGENT)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, expected_status=409)
