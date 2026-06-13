"""State-machine compliance: the Account's two parallel dimensions, the
AssistanceGrant consumption cycle (including the void-driven reverse edge),
and the invalid-transition guards across Bill, ServiceOrder, Tariff, and
Account.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    NONEXISTENT_UUID,
)
from test_helpers.fixtures import (
    OPERATOR,
    DISPATCHER,
    create_active_tariff,
    open_account,
    add_meter,
    create_draft_bill,
    issue_bill_with_occ,
    issue_bill_with_occ_data,
    setup_issued_bill,
    setup_account_in_arrears,
    setup_disconnect_pending,
    setup_assisted_issued_bill,
    pay_account_data,
    reads_for_2636,
)



# ===========================================================================
# Queue A — non_linear_state_machine (parallel dimensions)
# ===========================================================================
def test_account_carries_parallel_service_and_financial_dimensions(api):
    """PRD §2.8: "An account carries two status dimensions that evolve
    independently and never collapse into a single field."
    PRD §3.6: "Raising a notice advances the account's `service_status` from
    `ACTIVE` to `DISCONNECT_PENDING` and creates a `SCHEDULED` **ServiceOrder**
    of `order_type` `DISCONNECT` with `reason` `NONPAY`"

    An IN_ARREARS account (financial dimension) raised to DISCONNECT_PENDING
    (service dimension) reports both states independently on one row.

    Design: Difficulty/non_linear_state_machine/account_parallel_service_and_financial_dimensions
    """
    scene, order = setup_disconnect_pending()
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["service_status"] == "DISCONNECT_PENDING", acct["service_status"]
    assert acct["financial_status"] == "IN_ARREARS", acct["financial_status"]
    assert order["order_type"] == "DISCONNECT", order["order_type"]
    assert order["status"] == "SCHEDULED", order["status"]
    assert order["reason"] == "NONPAY", order["reason"]


def test_disconnect_notice_creates_scheduled_disconnect_order(api):
    """PRD §3.6: "Raising a notice advances the account's `service_status` from
    `ACTIVE` to `DISCONNECT_PENDING` and creates a `SCHEDULED` **ServiceOrder**
    of `order_type` `DISCONNECT` with `reason` `NONPAY`, returning that service
    order with a 201."

    The service dimension moves while the financial dimension stays IN_ARREARS —
    the two never collapse.

    Design: Difficulty/non_linear_state_machine/account_parallel_service_and_financial_dimensions
    """
    scene = setup_account_in_arrears()
    res = api.disconnect_notice(scene["account"]["id"], OPERATOR)
    order = validate_success(res, 201)
    assert order["order_type"] == "DISCONNECT"
    assert order["status"] == "SCHEDULED"
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["service_status"] == "DISCONNECT_PENDING"
    assert acct["financial_status"] == "IN_ARREARS"


# ===========================================================================
# Queue A — non_linear_state_machine (assistance grant cycle on void)
# ===========================================================================
def test_grant_exhausted_then_void_returns_it_to_applied(api):
    """PRD §3.8: "Should a bill that consumed assistance later be voided, the
    refund flows back into the grant's `remaining_cents`, and an `EXHAUSTED`
    grant returns to `APPLIED` (or to `PLEDGED` when the refund restores
    `remaining_cents` all the way to `pledged_cents`)."
    PRD §3.4: "refunds `assistance_applied_cents` back into the source
    assistance grant's `remaining_cents` (un-exhausting the grant if it had been
    fully consumed)."

    A 2000 grant fully consumed by a bill is EXHAUSTED (remaining 0); voiding
    that bill refunds 2000, restoring the grant to APPLIED/PLEDGED.

    Design: Difficulty/non_linear_state_machine/assistance_grant_cycles_exhausted_back_to_applied_on_void
    """
    scene = setup_assisted_issued_bill(pledged_cents=2000)
    grant_id = scene["grant"]["id"]
    before = get_success_data(api.get_assistance_grant(grant_id, OPERATOR))
    assert scene["bill"]["assistance_applied_cents"] == 2000
    assert before["status"] == "EXHAUSTED", before["status"]
    validate_success(api.void_bill(scene["bill"]["id"], OPERATOR), 200)
    after = get_success_data(api.get_assistance_grant(grant_id, OPERATOR))
    assert after["remaining_cents"] == 2000, after["remaining_cents"]
    assert after["status"] in ("APPLIED", "PLEDGED"), after["status"]


def test_grant_pledged_to_exhausted_in_one_bill(api):
    """PRD §3.8: "When a bill consumes the last of the remaining balance so that
    `remaining_cents` reaches zero, the grant moves to `EXHAUSTED`: from
    `APPLIED` if it had been partially consumed before, or directly
    `PLEDGED → EXHAUSTED` when a single bill consumes the entire grant in one
    step."

    A 2000 grant consumed entirely by one 2756-gross bill moves
    PLEDGED -> EXHAUSTED in a single step (remaining 0).

    Design: Difficulty/non_linear_state_machine/assistance_grant_cycles_exhausted_back_to_applied_on_void
    """
    scene = setup_assisted_issued_bill(pledged_cents=2000)
    grant = get_success_data(api.get_assistance_grant(scene["grant"]["id"], OPERATOR))
    assert grant["remaining_cents"] == 0, grant["remaining_cents"]
    assert grant["status"] == "EXHAUSTED", grant["status"]


# ===========================================================================
# Queue B — state_machines (invalid transitions / initial state)
# ===========================================================================
def test_reissue_already_issued_bill_rejected(api):
    """PRD §3.3: "Issuance requires the bill to be in `DRAFT` (otherwise
    `ERR_INVALID_STATE`)"

    Re-issuing an already ISSUED bill is rejected ERR_INVALID_STATE; no second
    debit occurs.

    Design: Corner/state_machines/issue_already_issued_bill_returns_invalid_state
    """
    scene = setup_issued_bill(read_tuples=reads_for_2636())
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    res = api.issue_bill(
        scene["bill"]["id"], {"expected_account_version": acct["version"]}, OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_void_paid_bill_rejected(api):
    """PRD §3.4: "Voiding is permitted only when the bill is in `ISSUED` status
    with `amount_paid_cents` equal to zero; a void attempt against a bill in any
    other state, or one that already carries payment, is rejected with
    `ERR_INVALID_STATE`."

    A fully PAID bill cannot be voided.

    Design: Corner/state_machines/void_paid_bill_returns_invalid_state
    """
    scene = setup_issued_bill(read_tuples=reads_for_2636())  # actual 2636
    pay_account_data(scene["account"]["id"], 2636)
    paid = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert paid["status"] == "PAID", paid["status"]
    res = api.void_bill(scene["bill"]["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    still = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert still["status"] == "PAID", still["status"]


def test_complete_service_order_twice_rejected(api):
    """PRD §3.6: "Completion requires the order to be `SCHEDULED` (otherwise
    `ERR_INVALID_STATE`)"

    Completing an already COMPLETED (terminal) disconnect order is rejected
    ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_service_order_twice_returns_invalid_state
    """
    scene, order = setup_disconnect_pending()
    validate_success(api.complete_service_order(order["id"], DISPATCHER), 200)
    res = api.complete_service_order(order["id"], DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    final = get_success_data(api.get_service_order(order["id"], OPERATOR))
    assert final["status"] == "COMPLETED", final["status"]


def test_retire_draft_tariff_rejected(api):
    """PRD §3.1: "Activation requires the tariff to currently be in `DRAFT` and
    retirement requires it to currently be in `ACTIVE`; attempting either
    transition from any other state is rejected with `ERR_INVALID_STATE`."

    Retiring a never-activated DRAFT tariff is rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/retire_draft_tariff_returns_invalid_state
    """
    tariff = get_success_data(api.create_tariff({
        "code": "RES-RETIRE-DRAFT", "name": "Draft Retire",
        "fixed_charge_cents": 1000, "tier_breakpoints_kwh": [500],
        "tier_rates_cents_per_kwh": [12, 18],
        "tou_multipliers": {"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
        "demand_charge_cents_per_kw": 800, "net_metering_credit_cents_per_kwh": 10,
    }, OPERATOR))
    res = api.retire_tariff(tariff["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    still = get_success_data(api.get_tariff(tariff["id"], OPERATOR))
    assert still["status"] == "DRAFT", still["status"]


def test_new_account_starts_active_and_current(api):
    """PRD §3.2: "A new account starts with `service_status` of `ACTIVE`,
    `financial_status` of `CURRENT`, a `balance_cents` of 0, a
    `net_metering_credit_balance_cents` of 0, a null
    `oldest_unpaid_bill_due_date`, and a null `budget_plan_id`."

    Design: Corner/state_machines/newly_created_account_starts_active_and_current
    """
    tariff = create_active_tariff()
    res = api.create_account(
        {"tariff_id": tariff["id"], "holder_name": "Init Holder"}, OPERATOR)
    acct = validate_success(res, 201)
    assert acct["service_status"] == "ACTIVE", acct["service_status"]
    assert acct["financial_status"] == "CURRENT", acct["financial_status"]
    assert acct["balance_cents"] == 0, acct["balance_cents"]


def test_reconnect_request_on_active_account_rejected(api):
    """PRD §3.6: "A reconnect request requires the account's service dimension to
    be `DISCONNECTED` (otherwise `ERR_INVALID_STATE`)"

    A reconnect-request on a fresh ACTIVE-service account is rejected
    ERR_INVALID_STATE.

    Design: Corner/state_machines/reconnect_request_on_active_account_returns_invalid_state
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    res = api.reconnect_request(account["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
