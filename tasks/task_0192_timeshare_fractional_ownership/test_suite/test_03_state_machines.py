"""State machines: contract lifecycle, reservation cycle, exchange recall,
foreclosure branch fork, invoice/payment transitions.

Difficulty: non_linear_state_machine (exchange recall cycle; foreclose branch
fork). Corner: rescission-window preconditions, rescind side effects, invalid
transitions, terminal lockdown, grace gate, below-threshold foreclose, payment
clear cascade cure.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    create_resort, create_owner, create_active_contract,
    create_contract, create_confirmed_reservation, create_deposited_reservation,
    create_issued_invoice, setup_lien_case,
    setup_active_contract_with_unit,
    create_resale_transfer_payload, create_invoice_payload,
    create_payment_payload,
    set_clock, make_owner_headers, TEST_USERS,
)

_RM = TEST_USERS["resort_manager_headers"]
_RA = TEST_USERS["resale_agent_headers"]
_CO = TEST_USERS["compliance_officer_headers"]


# =========================================================================== #
# Difficulty: non_linear_state_machine — reservation exchange recall cycle
# =========================================================================== #
def test_recall_returns_reservation_to_confirmed(api):
    """PRD §3.6: "Alternatively, an `Owner` may recall it, moving it from `DEPOSITED` to `RECALLED`;
    recall pulls the week back from the network, restoring the underlying
    reservation's `status` to `CONFIRMED` and the inventory unit's `status` to
    `RESERVED`."

    Design: Difficulty/non_linear_state_machine/reservation_exchange_recall_cycle
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(season="GOLD", week_number=20,
                                                                    contract_overrides={"annual_points_allotment": 5000})
    resv, deposit = create_deposited_reservation(resort, owner, contract, unit, exchange_network="RCI")
    headers = make_owner_headers(owner["id"])

    recalled = validate_success(api.recall_exchange_deposit(deposit["id"], headers))
    assert recalled["status"] == "RECALLED", f"expected RECALLED, got {recalled['status']}"

    reserv = get_success_data(api.get_reservation(resv["id"], headers))
    assert reserv["status"] == "CONFIRMED", \
        f"reservation must return to CONFIRMED, got {reserv['status']}"
    unit_after = get_success_data(api.get_inventory_unit(unit["id"], headers))
    assert unit_after["status"] == "RESERVED", \
        f"unit must return to RESERVED, got {unit_after['status']}"


def test_deposit_then_redeem_consumes_credits(api):
    """PRD §3.6: "An `Owner` may redeem it, moving it from `DEPOSITED` to `REDEEMED`, at which point
    the credits are considered consumed externally."

    Design: Difficulty/non_linear_state_machine/reservation_exchange_recall_cycle
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(season="GOLD", week_number=21,
                                                                    contract_overrides={"annual_points_allotment": 5000})
    resv, deposit = create_deposited_reservation(resort, owner, contract, unit, exchange_network="RCI")
    headers = make_owner_headers(owner["id"])

    redeemed = validate_success(api.redeem_exchange_deposit(deposit["id"], headers))
    assert redeemed["status"] == "REDEEMED", f"expected REDEEMED, got {redeemed['status']}"


# =========================================================================== #
# Difficulty: non_linear_state_machine — foreclose branch fork (RTU -> TERMINATION)
# =========================================================================== #
def test_foreclose_right_to_use_terminates(api):
    """PRD §3.9: "A `RIGHT_TO_USE` contract is instead terminated: the case moves from `LIEN` to
    `TERMINATION` and the contract cascades from `SUSPENDED` to `TERMINATED`."
    PRD §3.9: "In either branch the contract's terminal transition writes off its `DELINQUENT`
    invoices to `WRITTEN_OFF".

    Design: Difficulty/non_linear_state_machine/delinquency_foreclose_branch_fork
    """
    resort, owner, contract, invoice, case = setup_lien_case(
        escalations=2,
        contract_overrides={"ownership_type": "RIGHT_TO_USE", "annual_points_allotment": 8000,
                            "rtu_expiry_use_year": 2030})
    closed = validate_success(api.foreclose_delinquency_case(case["id"], _CO))
    assert closed["status"] == "TERMINATION", \
        f"RIGHT_TO_USE branch -> TERMINATION, got {closed['status']}"

    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "TERMINATED", f"contract -> TERMINATED, got {c['status']}"
    inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert inv["status"] == "WRITTEN_OFF", f"invoice -> WRITTEN_OFF, got {inv['status']}"


def test_foreclose_deeded_forecloses(api):
    """PRD §3.9: "A `DEEDED` contract is foreclosed: the case moves from `LIEN` to `FORECLOSURE` and
    the contract cascades from `SUSPENDED` to `FORECLOSED`."

    Design: Difficulty/non_linear_state_machine/delinquency_foreclose_branch_fork
    """
    resort, owner, contract, invoice, case = setup_lien_case(
        escalations=2, contract_overrides={"ownership_type": "DEEDED", "annual_points_allotment": 10000})
    closed = validate_success(api.foreclose_delinquency_case(case["id"], _CO))
    assert closed["status"] == "FORECLOSURE", \
        f"DEEDED branch -> FORECLOSURE, got {closed['status']}"
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "FORECLOSED", f"contract -> FORECLOSED, got {c['status']}"


# =========================================================================== #
# Corner: state_machines — rescission window preconditions
# =========================================================================== #
def test_activate_before_rescission_window_elapsed_rejected(api):
    """PRD §3.2: "An attempt to activate while the window is still open is rejected with
    `ERR_RESCISSION_WINDOW_OPEN`."

    Design: Corner/state_machines/activate_before_rescission_window_elapsed_rejected
    """
    resort = create_resort(rescission_days=7)  # clock anchored 2026-01-01
    owner = create_owner(resort["id"])
    contract = create_contract(resort["id"], owner["id"], annual_points_allotment=5000)
    set_clock(resort["id"], "2026-01-03T00:00:00Z")  # < signed_at + 7 days
    resp = api.activate_contract(contract["id"], _RM)
    validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_OPEN.value)
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "PENDING_RESCISSION", f"status must stay PENDING_RESCISSION, got {c['status']}"


def test_rescind_after_window_closed_rejected(api):
    """PRD §3.2: "An attempt to rescind after the window has closed is rejected with
    `ERR_RESCISSION_WINDOW_CLOSED`."

    Design: Corner/state_machines/rescind_after_window_closed_rejected
    """
    resort = create_resort(rescission_days=7)
    owner = create_owner(resort["id"])
    contract = create_contract(resort["id"], owner["id"], annual_points_allotment=5000)
    set_clock(resort["id"], "2026-01-20T00:00:00Z")  # window long closed
    resp = api.rescind_contract(contract["id"], make_owner_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_CLOSED.value)
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "PENDING_RESCISSION", f"status must stay PENDING_RESCISSION, got {c['status']}"


def test_rescind_within_window_writes_off_draft_invoice(api):
    """PRD §3.2: "Rescission voids the contract's invoices: every `DRAFT` and every `ISSUED`
    `MaintenanceFeeInvoice` for the contract transitions to `WRITTEN_OFF`."

    Design: Corner/state_machines/contract_rescind_within_window_writes_off_invoices
    """
    resort = create_resort(rescission_days=7)
    owner = create_owner(resort["id"])
    contract = create_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    inv = get_success_data(api.create_invoice(
        create_invoice_payload(contract["id"], 2026, "2026-02-01T00:00:00Z"), _RM))  # DRAFT
    set_clock(resort["id"], "2026-01-03T00:00:00Z")  # still inside window
    rescinded = validate_success(api.rescind_contract(contract["id"], make_owner_headers(owner["id"])))
    assert rescinded["status"] == "RESCINDED", f"expected RESCINDED, got {rescinded['status']}"
    inv_after = get_success_data(api.get_invoice(inv["id"], _RM))
    assert inv_after["status"] == "WRITTEN_OFF", f"DRAFT invoice -> WRITTEN_OFF, got {inv_after['status']}"


# =========================================================================== #
# Corner: state_machines — invalid transitions / terminal lockdown
# =========================================================================== #
def test_confirm_completed_reservation_invalid_state(api):
    """PRD §2.7: "the target resource being in a legal from-state for the requested transition,
    yielding `ERR_INVALID_STATE`."
    PRD §3.4: "an `Owner` confirms a `HELD` reservation, advancing it from `HELD` to `CONFIRMED`."

    Design: Corner/state_machines/confirm_reservation_invalid_from_completed_rejected
    """
    resort, owner, contract, unit = setup_active_contract_with_unit(season="GOLD", week_number=8,
                                                                    contract_overrides={"annual_points_allotment": 5000})
    confirmed = create_confirmed_reservation(resort, owner, contract, unit)
    headers = make_owner_headers(owner["id"])
    get_success_data(api.complete_reservation(confirmed["id"], _RM))  # -> COMPLETED
    resp = api.confirm_reservation(confirmed["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    r = get_success_data(api.get_reservation(confirmed["id"], headers))
    assert r["status"] == "COMPLETED", f"status must stay COMPLETED, got {r['status']}"


def test_complete_resale_transfer_twice_invalid_state(api):
    """PRD §2.7: "the target resource being in a legal from-state for the requested transition,
    yielding `ERR_INVALID_STATE`."
    PRD §3.9: "Completion moves the transfer to `COMPLETED".

    Design: Corner/state_machines/terminal_resale_complete_twice_rejected
    """
    resort = create_resort(rescission_days=7)
    seller = create_owner(resort["id"], full_name="Seller", email="seller@x.com")
    buyer = create_owner(resort["id"], full_name="Buyer", email="buyer@x.com")
    contract = create_active_contract(resort["id"], seller["id"], annual_points_allotment=10000)
    transfer = get_success_data(api.create_resale_transfer(
        create_resale_transfer_payload(contract["id"], buyer["id"], 2026, 120), _RA))
    set_clock(resort["id"], "2026-01-20T00:00:00Z")  # window elapsed
    get_success_data(api.complete_resale_transfer(transfer["id"], _RA))  # COMPLETED
    resp = api.complete_resale_transfer(transfer["id"], _RA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    t = get_success_data(api.get_resale_transfer(transfer["id"], _RM))
    assert t["status"] == "COMPLETED", f"status must stay COMPLETED, got {t['status']}"


# =========================================================================== #
# Corner: state_machines — grace gate, below-threshold foreclose, cure cascade
# =========================================================================== #
def test_mark_delinquent_during_grace_rejected(api):
    """PRD §3.7: "the resort's `current_utc` must be at or after the `due_date` plus
    `delinquency_grace_days` days, otherwise the request is rejected with
    `ERR_GRACE_PERIOD_ACTIVE`."

    Design: Corner/state_machines/mark_delinquent_during_grace_rejected
    """
    resort = create_resort(delinquency_grace_days=30)
    owner = create_owner(resort["id"])
    contract = create_active_contract(resort["id"], owner["id"], annual_points_allotment=10000)
    inv = create_issued_invoice(resort, contract, use_year=2026, due_date="2026-02-01T00:00:00Z")
    set_clock(resort["id"], "2026-02-15T00:00:00Z")  # within grace (30 days not elapsed)
    resp = api.mark_invoice_delinquent(inv["id"], _RM)
    validate_error(resp, ApiErrorId.ERR_GRACE_PERIOD_ACTIVE.value)
    after = get_success_data(api.get_invoice(inv["id"], _RM))
    assert after["status"] == "ISSUED", f"status must stay ISSUED, got {after['status']}"


def test_foreclose_below_threshold_rejected(api):
    """PRD §3.9: "Foreclosure is gated on eligibility: the case must be in `LIEN` and its
    `escalation_periods` must be at least the resort's
    `foreclosure_threshold_periods`, otherwise the request is rejected with
    `ERR_FORECLOSURE_NOT_ELIGIBLE`."

    Design: Corner/state_machines/foreclose_below_threshold_rejected
    """
    resort, owner, contract, invoice, case = setup_lien_case(
        escalations=1, resort_overrides={"foreclosure_threshold_periods": 2},
        contract_overrides={"annual_points_allotment": 10000})
    assert case["escalation_periods"] == 1  # below threshold 2
    resp = api.foreclose_delinquency_case(case["id"], _CO)
    validate_error(resp, ApiErrorId.ERR_FORECLOSURE_NOT_ELIGIBLE.value)
    c = get_success_data(api.get_delinquency_case(case["id"], _CO))
    assert c["status"] == "LIEN", f"case must stay LIEN, got {c['status']}"


def test_payment_clear_cures_case_and_reactivates_contract(api):
    """PRD §3.7: "Each invoice whose `amount_due_cents` reaches 0 transitions to `PAID` as a cascade.
    When clearing brings the contract's last `DELINQUENT` invoice to a zero
    `amount_due_cents`, the owning delinquency case is cured".
    PRD §3.8: "A cure out of `LIEN` additionally cascades the owning contract from `SUSPENDED` back
    to `ACTIVE`."

    Design: Corner/state_machines/payment_clear_cascades_invoice_paid_and_case_cured
    """
    resort, owner, contract, invoice, case = setup_lien_case(
        escalations=1, resort_overrides={"foreclosure_threshold_periods": 2},
        contract_overrides={"annual_points_allotment": 10000})
    # amount_due = 200000 + floor(200000*0.05)=10000 late = 210000.
    inv = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert inv["amount_due_cents"] == 210000, f"expected 210000 due, got {inv['amount_due_cents']}"

    payment = get_success_data(api.create_payment(
        create_payment_payload(contract["id"], 210000, invoice_id=invoice["id"]), _RM))
    get_success_data(api.clear_payment(payment["id"], _RM))

    inv_after = get_success_data(api.get_invoice(invoice["id"], _RM))
    assert inv_after["status"] == "PAID", f"invoice -> PAID, got {inv_after['status']}"
    assert inv_after["amount_due_cents"] == 0, f"due must be 0, got {inv_after['amount_due_cents']}"
    case_after = get_success_data(api.get_delinquency_case(case["id"], _CO))
    assert case_after["status"] == "CURED", f"case -> CURED, got {case_after['status']}"
    c = get_success_data(api.get_contract(contract["id"], _RM))
    assert c["status"] == "ACTIVE", f"contract reactivated -> ACTIVE, got {c['status']}"
