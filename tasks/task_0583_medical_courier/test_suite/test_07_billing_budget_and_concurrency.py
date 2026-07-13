"""Run billing: the optimistic-concurrency guard, the budget gate, and money conservation."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assign_route_payload,
    billing_payload,
    assert_billing_components_sum,
    fixtures,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Issuing debits the laboratory; voiding credits exactly the same amount back
# ---------------------------------------------------------------------------
def test_issuing_a_billing_raises_the_lab_balance_by_its_net_charge(api):
    """PRD §3.8: "Issuing a draft billing moves it `DRAFT → ISSUED` and debits the
    laboratory. The billing must be `DRAFT`, else `ERR_BILLING_INVALID_STATE`, and the
    laboratory's `billed_balance_cents` plus this billing's `net_charge_cents` must not
    exceed its `budget_cents`, else `ERR_BUDGET_EXCEEDED`; on success the laboratory's
    `billed_balance_cents` rises by `net_charge_cents`."

    Design: Difficulty/compensating_invariant/billing_issue_void_conserves_lab_money
    """
    ctx = fixtures.setup_route_with_draft_billing()

    before = validate_success(api.get_lab_client(ctx["lab"]["id"], DISPATCHER))
    assert before["billed_balance_cents"] == 0, "A DRAFT billing exerts no budget pressure"

    issued = validate_success(api.issue_billing(ctx["billing"]["id"], DISPATCHER))
    assert issued["status"] == "ISSUED"
    assert issued["net_charge_cents"] == 2599
    assert_billing_components_sum(issued)

    after = validate_success(api.get_lab_client(ctx["lab"]["id"], DISPATCHER))
    assert after["billed_balance_cents"] == 2599, (
        f"Expected the balance to rise by the 2599-cent net charge, "
        f"got {after['billed_balance_cents']}"
    )


def test_voiding_an_issued_billing_restores_the_lab_balance(api):
    """PRD §3.8: "Voiding an issued billing moves it `ISSUED → VOIDED` and reverses the
    debit. The billing must be `ISSUED`, else `ERR_BILLING_INVALID_STATE`; on success the
    laboratory's `billed_balance_cents` falls by `net_charge_cents`, restoring the
    conserved total."
    PRD §3.8: "Because `billed_balance_cents` is defined as the sum of `net_charge_cents`
    across only the laboratory's `ISSUED` billings, a `DRAFT` billing exerts no pressure
    on the budget until it is issued, and a `VOIDED` one exerts none thereafter."

    Design: Difficulty/compensating_invariant/billing_issue_void_conserves_lab_money
    """
    ctx = fixtures.setup_route_with_issued_billing()
    assert ctx["billing"]["net_charge_cents"] == 2599

    voided = validate_success(api.void_billing(ctx["billing"]["id"], DISPATCHER))
    assert voided["status"] == "VOIDED"

    lab = validate_success(api.get_lab_client(ctx["lab"]["id"], DISPATCHER))
    assert lab["billed_balance_cents"] == 0, (
        f"Voiding must credit back exactly the 2599 cents that issuing debited, "
        f"got {lab['billed_balance_cents']}"
    )


# ---------------------------------------------------------------------------
# The optimistic-concurrency guard on billing generation
# ---------------------------------------------------------------------------
def test_generating_a_billing_with_the_current_route_version_succeeds(api):
    """PRD §3.8: "The request carries `expected_route_version`, which must equal the
    route's current `version`, else `ERR_STALE_VERSION`."
    PRD §3.8: "The new billing begins in `DRAFT` status, and generating it advances the
    route's `version` by one, which is precisely why a second generation working from a
    stale `expected_route_version` is refused — an earlier generation legitimately
    supersedes any prior draft."

    Design: Corner/cross_cutting_complexity_layers/billing_create_correct_version_succeeds
    """
    ctx = fixtures.setup_completed_route()
    route = ctx["route"]

    billing = validate_success(
        api.create_billing(route["id"], billing_payload(route["version"]), DISPATCHER),
        expected_status=201,
    )
    assert billing["status"] == "DRAFT"
    assert billing["net_charge_cents"] == 2599
    assert billing["route_id"] == route["id"]
    assert billing["lab_client_id"] == ctx["lab"]["id"]

    after = validate_success(api.get_route(route["id"], DISPATCHER))
    assert after["version"] == route["version"] + 1, (
        f"Generating a billing advances the route's version by one: expected "
        f"{route['version'] + 1}, got {after['version']}"
    )


def test_generating_a_second_billing_from_a_stale_route_version_is_rejected(api):
    """PRD §2.7: "If that value does not equal the route's current `version`, the
    operation is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "This matters because generating a billing legitimately supersedes any
    earlier draft and, as a side effect, advances the route's `version` by one; a client
    working from a `version` it read before an earlier billing was generated therefore no
    longer matches, and its create is refused as a stale-version write rather than
    silently overwriting a billing it never saw."

    Design: Corner/cross_cutting_complexity_layers/billing_create_stale_version_returns_412
    """
    ctx = fixtures.setup_route_with_draft_billing()

    resp = api.create_billing(
        ctx["route"]["id"], billing_payload(ctx["stale_route_version"]), DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_route_version_increments_on_assignment(api):
    """PRD §2.4: "`version`: an integer that begins at creation and increments by one on
    every mutation. It underpins the optimistic-concurrency mechanism of §2.7."
    PRD §3.3: "On success the route's `driver_id` and `vehicle_id` are set and the
    vehicle transitions `AVAILABLE → IN_USE`."

    Design: Corner/cross_cutting_complexity_layers/route_version_increments_on_assign
    """
    ctx = fixtures.setup_scenario(stops=[], specimens=[])
    created_version = ctx["route"]["version"]

    assigned = validate_success(
        api.assign_route(
            ctx["route"]["id"],
            assign_route_payload(ctx["driver"]["id"], ctx["vehicle"]["id"]),
            DISPATCHER,
        )
    )
    assert assigned["version"] == created_version + 1, (
        f"Assignment mutates the route, so its version must rise by one: expected "
        f"{created_version + 1}, got {assigned['version']}"
    )


# ---------------------------------------------------------------------------
# Billing state and the budget gate at issue
# ---------------------------------------------------------------------------
def test_issuing_an_already_issued_billing_is_rejected(api):
    """PRD §3.8: "Issuing a draft billing moves it `DRAFT → ISSUED` and debits the
    laboratory. The billing must be `DRAFT`, else `ERR_BILLING_INVALID_STATE`, and the
    laboratory's `billed_balance_cents` plus this billing's `net_charge_cents` must not
    exceed its `budget_cents`, else `ERR_BUDGET_EXCEEDED`; on success the laboratory's
    `billed_balance_cents` rises by `net_charge_cents`."

    Design: Corner/state_machines/issue_already_issued_billing_returns_409
    """
    ctx = fixtures.setup_route_with_issued_billing()
    resp = api.issue_billing(ctx["billing"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_BILLING_INVALID_STATE.value)


def test_issuing_a_billing_beyond_the_lab_budget_is_rejected(api):
    """PRD §3.8: "Issuing a draft billing moves it `DRAFT → ISSUED` and debits the
    laboratory. The billing must be `DRAFT`, else `ERR_BILLING_INVALID_STATE`, and the
    laboratory's `billed_balance_cents` plus this billing's `net_charge_cents` must not
    exceed its `budget_cents`, else `ERR_BUDGET_EXCEEDED`; on success the laboratory's
    `billed_balance_cents` rises by `net_charge_cents`."

    A budget of 2598 covers the 2598-cent provisional charge at dispatch, but not the
    2599-cent net charge the completed run actually produced.

    Design: Corner/validations/issue_over_budget_returns_402
    """
    ctx = fixtures.setup_route_with_draft_billing(lab={"budget_cents": 2598})
    assert ctx["billing"]["net_charge_cents"] == 2599

    resp = api.issue_billing(ctx["billing"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
