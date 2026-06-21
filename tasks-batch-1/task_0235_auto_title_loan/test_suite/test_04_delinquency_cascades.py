"""Delinquency lifecycle, reinstatement cures, and the device cascade chains."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_originated_loan,
    setup_delinquent_loan,
    file_loan_lien,
    install_device,
    set_clock,
    CLOCK_ORIGIN,
    CLOCK_PAST_DUE,
    create_payment_payload,
)

_SERVICER = TEST_USERS["loan_servicer_headers"]
_RECOVERY = TEST_USERS["recovery_manager_headers"]
_CLERK = TEST_USERS["title_clerk_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Non-linear cyclic state machine: CURRENT -> DELINQUENT -> CURRENT
# ─────────────────────────────────────────────────────────────────────────
def test_loan_delinquency_cycle_current_delinquent_current(api):
    """PRD §3.7: "When a DELINQUENT loan is reinstated, the system reduces
    principal_balance_cents by the past-due principal, reduces accrued_interest_cents by
    the past-due interest, sets fees_balance_cents to 0 (the cure exactly retires
    arrears and fees, and there is no repossession fee while merely DELINQUENT), sets
    all PAST_DUE installments to PAID, and advances delinquency_status DELINQUENT →
    CURRENT."

    Design: Difficulty/non_linear_state_machine/loan_delinquency_cycle_current_delinquent_current
    """
    ctx = setup_delinquent_loan(install_dev=True)
    loan_id = ctx["loan"]["id"]
    assert ctx["loan"]["delinquency_status"] == "DELINQUENT"
    validate_success(
        api.create_payment(loan_id, create_payment_payload(434236, "REINSTATEMENT"), _SERVICER), 201)
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["delinquency_status"] == "CURRENT"
    assert loan["fees_balance_cents"] == 0


def test_reinstatement_returns_loan_to_current_from_delinquent(api):
    """PRD §3.6: "A LoanServicer assesses delinquency on a loan, advancing
    delinquency_status from CURRENT to DELINQUENT."
    PRD §3.7: "advances delinquency_status DELINQUENT → CURRENT."

    Design: Difficulty/non_linear_state_machine/loan_delinquency_cycle_current_delinquent_current
    """
    ctx = setup_delinquent_loan(install_dev=True)
    loan_id = ctx["loan"]["id"]
    validate_success(
        api.create_payment(loan_id, create_payment_payload(434236, "REINSTATEMENT"), _SERVICER), 201)
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["delinquency_status"] == "CURRENT"


# ─────────────────────────────────────────────────────────────────────────
# Compensating invariant: device active_disable_count returns to 0 on reinstatement
# ─────────────────────────────────────────────────────────────────────────
def test_device_disable_count_conserved_to_zero_on_reinstatement(api):
    """PRD §3.7: "If a device exists, a STARTER_ENABLE command is issued (in ISSUED
    status) with effective_start and effective_end at the current clock time, the
    device's starter_state set to ENABLED, and active_disable_count decreased by 1
    (never below 0), compensating the prior disable".
    PRD §3.6: "an `active_disable_count` that begins at 0 and represents the net number
    of unreversed disable commands; this count is an invariant target that must return to
    0 when a loan is reinstated or redeemed."

    Design: Difficulty/compensating_invariant/device_disable_count_conserved_to_zero_on_reinstatement
    """
    ctx = setup_delinquent_loan(install_dev=True)
    loan_id = ctx["loan"]["id"]
    device_id = ctx["device"]["id"]
    validate_success(
        api.create_payment(loan_id, create_payment_payload(434236, "REINSTATEMENT"), _SERVICER), 201)
    device = get_success_data(api.get_device(device_id, _SERVICER))
    assert device["active_disable_count"] == 0
    assert device["starter_state"] == "ENABLED"
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["delinquency_status"] == "CURRENT"


def test_assess_delinquency_disables_device_then_reinstatement_re_enables(api):
    """PRD §3.6: "if a device exists on the vehicle the system issues a STARTER_DISABLE
    command (in ISSUED status) with effective_start and effective_end both set to the
    current clock time (a zero-length window), sets the device's starter_state to
    DISABLED, and increases active_disable_count by 1".

    Design: Difficulty/compensating_invariant/device_disable_count_conserved_to_zero_on_reinstatement
    """
    ctx = setup_delinquent_loan(install_dev=True)
    # After assessment the device must be DISABLED with count 1.
    disabled = get_success_data(api.get_device(ctx["device"]["id"], _SERVICER))
    assert disabled["starter_state"] == "DISABLED"
    assert disabled["active_disable_count"] == 1
    validate_success(
        api.create_payment(ctx["loan"]["id"], create_payment_payload(434236, "REINSTATEMENT"),
                           _SERVICER), 201)
    after = get_success_data(api.get_device(ctx["device"]["id"], _SERVICER))
    assert after["active_disable_count"] == 0


# ─────────────────────────────────────────────────────────────────────────
# Transitive cascade depth-3: declare-default -> repo ORDERED -> device DISABLE
# ─────────────────────────────────────────────────────────────────────────
def test_declare_default_cascade_depth3_to_device_disable(api):
    """PRD §3.7: "Declaring default creates a repossession order in ORDERED status as a
    cascade, and that order's creation itself issues a STARTER_DISABLE command to the
    collateral's device when one exists — a depth-three chain (default → order → device
    command) — with effective_start and effective_end both at the current clock time,
    the device's starter_state set to DISABLED, and active_disable_count increased by 1."

    Design: Difficulty/transitive_cascade/declare_default_to_repo_to_device_disable_depth3
    """
    # Isolate the chain: reach DELINQUENT (device count 1), reinstate (count 0, ENABLED),
    # then re-assess and declare default so the depth-3 chain bumps count to 2.
    ctx = setup_delinquent_loan(install_dev=True)
    loan_id = ctx["loan"]["id"]
    device_id = ctx["device"]["id"]
    # Declare default directly from DELINQUENT (count currently 1).
    loan = get_success_data(api.declare_default(loan_id, _SERVICER))
    assert loan["delinquency_status"] == "DEFAULT"
    orders, _meta = _list(api.list_loan_repossession_orders(loan_id, _RECOVERY))
    assert any(o["status"] == "ORDERED" for o in orders)
    device = get_success_data(api.get_device(device_id, _SERVICER))
    assert device["starter_state"] == "DISABLED"
    assert device["active_disable_count"] == 2


def test_declare_default_opens_ordered_repossession_order(api):
    """PRD §3.7: "Declaring default creates a repossession order in `ORDERED` status as
    a cascade".
    PRD §3.6: "A `LoanServicer` declares default on a loan, advancing
    `delinquency_status` from `DELINQUENT` to `DEFAULT`."

    Design: Difficulty/transitive_cascade/declare_default_to_repo_to_device_disable_depth3
    """
    ctx = setup_delinquent_loan(install_dev=True)
    loan_id = ctx["loan"]["id"]
    get_success_data(api.declare_default(loan_id, _SERVICER))
    orders, _meta = _list(api.list_loan_repossession_orders(loan_id, _RECOVERY))
    ordered = [o for o in orders if o["status"] == "ORDERED"]
    assert len(ordered) >= 1


# ─────────────────────────────────────────────────────────────────────────
# Transitive cascade depth-2: REDEMPTION -> lien RELEASED -> vehicle CLEAR
# ─────────────────────────────────────────────────────────────────────────
def test_redemption_cascade_depth2_lien_release_vehicle_clear(api):
    """PRD §3.7: "Redemption cascades: the title lien transitions `FILED → RELEASED` and
    the vehicle's `lien_state` is set to `CLEAR`, any active repossession order
    transitions to `CANCELLED`, and a `STARTER_ENABLE` command is issued that resets the
    device's `active_disable_count` to 0."

    Design: Difficulty/transitive_cascade/redemption_to_lien_release_to_vehicle_clear_depth2
    """
    ctx = setup_delinquent_loan(install_dev=True, file_lien=True)
    loan_id = ctx["loan"]["id"]
    lien_id = ctx["lien_id"]
    validate_success(
        api.create_payment(loan_id, create_payment_payload(640176, "REDEMPTION"), _SERVICER), 201)
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["payoff_status"] == "REDEEMED"
    lien = get_success_data(api.get_title_lien(lien_id, _CLERK))
    assert lien["status"] == "RELEASED"
    vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], _SERVICER))
    assert vehicle["lien_state"] == "CLEAR"


def test_redemption_payment_advances_loan_to_redeemed(api):
    """PRD §3.7: "A REDEMPTION payment pays the full redemption amount and advances the
    loan's payoff dimension OUTSTANDING → REDEEMED."

    Design: Difficulty/transitive_cascade/redemption_to_lien_release_to_vehicle_clear_depth2
    """
    ctx = setup_delinquent_loan(install_dev=True, file_lien=True)
    loan_id = ctx["loan"]["id"]
    validate_success(
        api.create_payment(loan_id, create_payment_payload(640176, "REDEMPTION"), _SERVICER), 201)
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["payoff_status"] == "REDEEMED"


# ─────────────────────────────────────────────────────────────────────────
# Corner: vehicle lien_state flips CLEAR -> ENCUMBERED on approval (origination)
# ─────────────────────────────────────────────────────────────────────────
def test_vehicle_lien_state_encumbered_on_origination(api):
    """PRD §3.3: "The collateral vehicle's lien_state is set to ENCUMBERED."

    Design: Corner/cross_cutting_complexity_layers/vehicle_lien_state_reconciliation_on_origination
    """
    ctx = setup_originated_loan()
    vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], TEST_USERS["underwriter_headers"]))
    assert vehicle["lien_state"] == "ENCUMBERED"


# ─────────────────────────────────────────────────────────────────────────
# helper
# ─────────────────────────────────────────────────────────────────────────
def _list(response):
    body = get_success_data(response)
    return (body, {}) if isinstance(body, list) else (body, {})
