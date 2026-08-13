"""Contractor account lifecycle: creation defaults, credit posture, suspension,
closure cascades, and the account-state gate on takeoff submission (PRD §3.1)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_contractor_account,
    create_account, create_product, create_project, create_takeoff_with_lines,
    submit_takeoff, get_project,
    setup_stocked_order_scenario, setup_scheduled_order_scenario,
)
from test_helpers import api_client

CM = TEST_USERS["credit_manager_headers"]
EST = TEST_USERS["estimator_headers"]


def test_create_account_returns_201_with_active_status_and_zero_ar(api, credit_manager_headers):
    """PRD §3.1: "A new account starts in `ACTIVE` status with
    `ar_outstanding_cents` equal to zero."

    Design: Corner/entities/contractor_account_create_returns_201_and_active_status
    """
    res = api.create_contractor_account(
        {"company_name": "New Co", "credit_limit_cents": 100000,
         "default_waste_pct_bp": 1500},
        credit_manager_headers)
    account = validate_success(res, 201)
    assert_contractor_account(account)
    assert account["status"] == "ACTIVE"
    assert account["ar_outstanding_cents"] == 0


def test_get_nonexistent_account_returns_404(api, credit_manager_headers):
    """PRD §2.7: "The first segment that fails to resolve — or a child found to
    belong to a different parent — yields `ERR_NOT_FOUND` (HTTP 404), and no
    business validation runs before path resolution completes."

    Design: Corner/entities/get_nonexistent_account_returns_404
    """
    res = api.get_contractor_account(NON_EXISTENT_UUID, credit_manager_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_close_account_with_open_balance_rejected(api):
    """PRD §3.1: "Closing an account requires the ledger to be fully settled:
    `ar_outstanding_cents` must be exactly zero, or the close is rejected with
    `ERR_ACCOUNT_BALANCE_OPEN`."

    Setup: a stocked order auto-issues a draw, so AR is positive.

    Design: Corner/errors/err_account_balance_open_triggered_on_close
    """
    ctx = setup_stocked_order_scenario(
        account_overrides={"company_name": "Open Co", "credit_limit_cents": 9000000})
    res = api_client.close_contractor_account(ctx["account"]["id"], CM)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_BALANCE_OPEN)


def test_suspend_account_cancels_draft_takeoffs(api, estimator_headers):
    """PRD §3.1: "Suspension has teeth: every takeoff still in `DRAFT` on any
    project of the account is immediately cancelled (releasing no stock, since
    drafts reserve none), and any subsequent attempt to submit a takeoff on one
    of the account's projects is rejected with `ERR_ACCOUNT_SUSPENDED`."

    Design: Corner/state_machines/cascade_down_suspend_cancels_draft_takeoffs
    """
    account = create_account(company_name="Casc Co")
    product = create_product()
    project = create_project(account["id"])
    takeoff, _lines = create_takeoff_with_lines(project["id"], [(product["id"], 20)])
    assert takeoff["status"] == "DRAFT"

    validate_success(api_client.suspend_contractor_account(account["id"], CM), 200)

    takeoff_after = get_success_data(api_client.get_takeoff(takeoff["id"], estimator_headers))
    assert takeoff_after["status"] == "CANCELLED", (
        f"DRAFT takeoff must be CANCELLED by account suspension, got {takeoff_after['status']}")


def test_takeoff_submit_blocked_when_account_suspended(api):
    """PRD §3.1: "Suspension has teeth: every takeoff still in `DRAFT` on any
    project of the account is immediately cancelled (releasing no stock, since
    drafts reserve none), and any subsequent attempt to submit a takeoff on one
    of the account's projects is rejected with `ERR_ACCOUNT_SUSPENDED`."
    PRD §2.8: "The order is: authentication (`ERR_UNAUTHENTICATED`) first, then
    authorization (`ERR_FORBIDDEN`), then path resolution (`ERR_NOT_FOUND`),
    then the account-posture guard (`ERR_ACCOUNT_SUSPENDED`), then generic
    state guards (`ERR_INVALID_STATE`), and only then the business rules."

    The drafted takeoff is cancelled by the suspension cascade, yet the
    account-posture guard outranks the generic state guard, so the submit
    attempt reports ERR_ACCOUNT_SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/takeoff_submit_blocked_when_account_suspended
    """
    account = create_account(company_name="Susp Co")
    product = create_product()
    project = create_project(account["id"])
    takeoff, _lines = create_takeoff_with_lines(project["id"], [(product["id"], 20)])

    validate_success(api_client.suspend_contractor_account(account["id"], CM), 200)

    res = api_client.submit_takeoff(takeoff["id"], EST)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_SUSPENDED)


def test_takeoff_submit_unblocked_after_reinstatement(api):
    """PRD §3.1: "Reinstatement, also a `CreditManager` action, is legal only
    from `SUSPENDED` and only while `ar_outstanding_cents` is at or below
    `credit_limit_cents`; it returns the account to `ACTIVE` and unblocks
    takeoff submission."

    Design: Difficulty/cross_entity_state_dependency/takeoff_submit_blocked_when_account_suspended
    """
    account = create_account(company_name="Susp Co 2")
    product = create_product()
    project = create_project(account["id"])
    takeoff, _lines = create_takeoff_with_lines(project["id"], [(product["id"], 20)])

    validate_success(api_client.suspend_contractor_account(account["id"], CM), 200)
    validate_success(api_client.reinstate_contractor_account(account["id"], CM), 200)

    # The original takeoff was cancelled by suspension; draft a fresh one.
    takeoff2, _lines2 = create_takeoff_with_lines(project["id"], [(product["id"], 20)])
    submitted = submit_takeoff(takeoff2["id"])
    assert submitted["status"] == "SUBMITTED"


def test_account_close_cascades_projects_to_cancelled(api):
    """PRD §3.1: "Closure is permitted from either `ACTIVE` or `SUSPENDED`, and
    it cascades hard — every non-terminal project on the account is cancelled,
    and every non-terminal stocking order on those projects is cancelled with
    it."

    Design: Difficulty/transitive_cascade/account_close_cascades_to_orders
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "Closer Co", "credit_limit_cents": 9000000},
        project_overrides={"jobsite_name": "P-Active"})
    idle = create_project(ctx["account"]["id"], jobsite_name="P-Idle",
                          distance_miles=10, framing_pct_complete=10)

    closed = validate_success(
        api_client.close_contractor_account(ctx["account"]["id"], CM), 200)
    assert closed["status"] == "CLOSED"

    idle_after = get_project(idle["id"])
    active_after = get_project(ctx["project"]["id"])
    assert idle_after["status"] == "CANCELLED", (
        f"PLANNING project must be CANCELLED by account close, got {idle_after['status']}")
    assert active_after["status"] == "CANCELLED", (
        f"STOCKING_OPEN project must be CANCELLED by account close, got {active_after['status']}")


def test_account_close_cascades_scheduled_orders_to_cancelled(api, dispatcher_headers):
    """PRD §3.1: "Closure is permitted from either `ACTIVE` or `SUSPENDED`, and
    it cascades hard — every non-terminal project on the account is cancelled,
    and every non-terminal stocking order on those projects is cancelled with
    it."

    Design: Difficulty/transitive_cascade/account_close_cascades_to_orders
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "Closer Co 2", "credit_limit_cents": 9000000})
    assert ctx["order"]["status"] == "SCHEDULED"

    validate_success(api_client.close_contractor_account(ctx["account"]["id"], CM), 200)

    order_after = get_success_data(
        api_client.get_stocking_order(ctx["order"]["id"], dispatcher_headers))
    assert order_after["status"] == "CANCELLED", (
        f"SCHEDULED order must be CANCELLED by the account-close cascade, "
        f"got {order_after['status']}")
