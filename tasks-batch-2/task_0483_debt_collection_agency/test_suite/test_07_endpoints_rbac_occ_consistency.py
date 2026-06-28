"""Action endpoints, RBAC, optimistic concurrency, cross-entity cascades, derived
field reconciliation, and immediate consistency.

All tests translate corner-design (queue B) instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    set_clock,
    create_creditor,
    create_consumer,
    create_account_payload,
    create_skip_trace_payload,
    setup_working_account,
    setup_working_account_with_open_accuracy_dispute,
    raise_dispute,
    furnish_tradeline,
    open_bureau_dispute,
    post_payment,
    refresh_account,
    TEST_USERS,
)

COLLECTOR = TEST_USERS["collector_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
BUREAU = TEST_USERS["bureau_operator_headers"]


# ===========================================================================
# endpoints / skip_trace_located_updates_consumer
# ===========================================================================
def test_skip_trace_located_updates_consumer():
    """PRD §3.1: "A `LOCATED` result sets the consumer's `contactability` to
    `LOCATED` and, where the corresponding new value is provided, overwrites the
    consumer's `phone` and `address` with `new_phone` and `new_address`."

    Design: Corner/endpoints/skip_trace_located_updates_consumer
    """
    consumer = create_consumer()
    res = api_client.create_skip_trace(
        create_skip_trace_payload(consumer["id"], "LOCATED", new_phone="555-0100"),
        COLLECTOR,
    )
    validate_success(res, 201)
    refreshed = validate_success(api_client.get_consumer(consumer["id"], COLLECTOR), 200)
    assert refreshed["contactability"] == "LOCATED"
    assert refreshed["phone"] == "555-0100"


# ===========================================================================
# endpoints / skip_trace_filtered_list_by_consumer
# ===========================================================================
def test_skip_trace_filtered_list_by_consumer():
    """PRD §3.1: "Skip-trace records are retrievable individually and as a list
    filterable by `consumer_id`."

    Design: Corner/endpoints/skip_trace_filtered_list_by_consumer
    """
    consumer = create_consumer()
    get_success_data(api_client.create_skip_trace(
        create_skip_trace_payload(consumer["id"], "NOT_FOUND"), COLLECTOR
    ))
    data, meta = validate_paginated(
        api_client.list_skip_traces(COLLECTOR, params={"consumer_id": consumer["id"]})
    )
    assert meta["total_count"] == 1


# ===========================================================================
# endpoints / bureau_dispute_corrected_updates_furnishing_balance
# ===========================================================================
def test_bureau_dispute_corrected_updates_furnishing_balance():
    """PRD §3.11: "A `CORRECTED` outcome moves the referenced furnishing's `status` to
    `UPDATED` and refreshes its `furnished_balance_cents` to the account's current
    `balance_cents`"

    Design: Corner/endpoints/bureau_dispute_corrected_updates_furnishing_balance
    """
    ctx = setup_working_account(clock="2026-01-01T00:00:00Z",
                                account_overrides={"original_principal_cents": 100000})
    furn = furnish_tradeline(ctx["account"]["id"], "EQUIFAX")
    bd = open_bureau_dispute(furn["id"])
    # Post a 40000 payment after furnishing so balance moves to 60000.
    get_success_data(post_payment(ctx["account"]["id"], 40000))
    get_success_data(
        api_client.resolve_bureau_dispute(bd["id"], {"outcome": "CORRECTED"}, BUREAU)
    )
    refreshed = validate_success(api_client.get_bureau_furnishing(furn["id"], BUREAU), 200)
    assert refreshed["status"] == "UPDATED"
    assert refreshed["furnished_balance_cents"] == 60000


# ===========================================================================
# rbac / collector_cannot_place_account_forbidden
# ===========================================================================
def test_collector_cannot_place_account_forbidden():
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/collector_cannot_place_account_forbidden
    """
    creditor, _ = create_creditor()
    consumer = create_consumer()
    res = api_client.create_account(
        create_account_payload(creditor["id"], consumer["id"],
                               original_principal_cents=50000),
        COLLECTOR,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ===========================================================================
# rbac / collector_cannot_resolve_dispute_forbidden
# ===========================================================================
def test_collector_cannot_resolve_dispute_forbidden():
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/collector_cannot_resolve_dispute_forbidden
    """
    ctx = setup_working_account_with_open_accuracy_dispute(
        clock="2026-01-01T00:00:00Z",
        account_overrides={"original_principal_cents": 50000},
    )
    res = api_client.resolve_dispute(
        ctx["dispute"]["id"], {"resolution": "VERIFIED"}, COLLECTOR
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ===========================================================================
# cross_cutting_complexity_layers / occ_stale_account_version_on_recall_rejected
# ===========================================================================
def test_occ_stale_account_version_on_recall_rejected():
    """PRD §2.7: "If they do not match — because some other writer has, since the
    client's last read, posted a payment, accepted a settlement, or otherwise
    advanced the account — the request is rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_recall_rejected
    """
    ctx = setup_working_account(clock="2026-01-01T00:00:00Z",
                                account_overrides={"original_principal_cents": 100000})
    v_pre = refresh_account(ctx)["version"]
    # A payment bumps account.version, making v_pre stale.
    get_success_data(post_payment(ctx["account"]["id"], 10000))
    res = api_client.recall_account(
        ctx["account"]["id"], {"expected_account_version": v_pre}, ctx["creditor_headers"]
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    acct = refresh_account(ctx)
    assert acct["work_status"] == "WORKING", "recall must be rejected, not applied"


# ===========================================================================
# cross_cutting_complexity_layers / occ_stale_account_version_on_reverse_rejected
# ===========================================================================
def test_occ_stale_account_version_on_reverse_rejected():
    """PRD §2.7: "If they do not match — because some other writer has, since the
    client's last read, posted a payment, accepted a settlement, or otherwise
    advanced the account — the request is rejected with `ERR_STALE_VERSION` (HTTP
    412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_reverse_rejected
    """
    ctx = setup_working_account(clock="2026-01-01T00:00:00Z",
                                account_overrides={"original_principal_cents": 100000})
    p1 = get_success_data(post_payment(ctx["account"]["id"], 10000))
    v_after_p1 = refresh_account(ctx)["version"]
    # A second payment advances version past v_after_p1, making it stale.
    get_success_data(post_payment(ctx["account"]["id"], 5000))
    res = api_client.reverse_payment(
        p1["id"], {"expected_account_version": v_after_p1}, COLLECTOR
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    pay = validate_success(api_client.get_payment(p1["id"], COLLECTOR), 200)
    assert pay["status"] == "POSTED", "reverse must be rejected, not applied"


# ===========================================================================
# cross_cutting_complexity_layers / dispute_deleted_cascades_account_close_and_furnishing_delete
# ===========================================================================
def test_dispute_deleted_cascades_account_close_and_furnishing_delete():
    """PRD §3.4: "A `DELETED` resolution — applicable to either dispute type — closes
    the account: it drives the account's `work_status` to `CLOSED_UNCOLLECTIBLE` and,
    as part of that closure cascade, transitions every still-open `BureauFurnishing`
    row for the account to `DELETED`."

    Design: Corner/cross_cutting_complexity_layers/dispute_deleted_cascades_account_close_and_furnishing_delete
    """
    ctx = setup_working_account(clock="2026-01-01T00:00:00Z",
                                account_overrides={"original_principal_cents": 100000})
    furn = furnish_tradeline(ctx["account"]["id"], "EQUIFAX")
    disp = raise_dispute(ctx["account"]["id"], "ACCURACY")
    get_success_data(api_client.investigate_dispute(disp["id"], COMPLIANCE))
    get_success_data(
        api_client.resolve_dispute(disp["id"], {"resolution": "DELETED"}, COMPLIANCE)
    )
    acct = refresh_account(ctx)
    refreshed_furn = validate_success(
        api_client.get_bureau_furnishing(furn["id"], COMPLIANCE), 200
    )
    assert acct["work_status"] == "CLOSED_UNCOLLECTIBLE"
    assert refreshed_furn["status"] == "DELETED"


# ===========================================================================
# cross_cutting_complexity_layers / time_barred_recomputed_on_clock_advance
# ===========================================================================
def test_time_barred_recomputed_on_clock_advance():
    """PRD §3.2: "The statute-of-limitations verdict is published on the account as
    the boolean `time_barred` and is recomputed at account creation, on every payment
    posting, on payment reversal, on settlement acceptance, and whenever the clock
    advances."

    Design: Corner/cross_cutting_complexity_layers/time_barred_recomputed_on_clock_advance
    """
    # charge_off 2022-01-01, sol_years 4 (CHARGE_OFF) -> expiry 2026-01-01.
    set_clock("2025-12-31T23:59:59Z")
    creditor, creditor_headers = create_creditor()
    consumer = create_consumer()
    acct = get_success_data(api_client.create_account(
        create_account_payload(creditor["id"], consumer["id"],
                               original_principal_cents=100000,
                               charge_off_date="2022-01-01T00:00:00Z",
                               sol_years=4, sol_anchor_basis="CHARGE_OFF"),
        creditor_headers,
    ))
    assert acct["time_barred"] is False
    set_clock("2026-01-01T00:00:00Z")
    advanced = validate_success(api_client.get_account(acct["id"], COLLECTOR), 200)
    assert advanced["time_barred"] is True


# ===========================================================================
# consistency_model / payment_post_reflects_balance_in_same_response
# ===========================================================================
def test_payment_post_reflects_balance_immediately():
    """PRD §3.7: "The account's `amount_collected_cents` is the sum of `amount_cents`
    across all of its `POSTED` payments, and the account's `balance_cents` is
    recomputed as the original principal minus the amount collected minus the amount
    forgiven, floored at zero"

    Design: Corner/consistency_model/payment_post_reflects_balance_in_same_response
    """
    ctx = setup_working_account(clock="2026-01-01T00:00:00Z",
                                account_overrides={"original_principal_cents": 100000})
    get_success_data(post_payment(ctx["account"]["id"], 25000))
    acct = validate_success(api_client.get_account(ctx["account"]["id"], COLLECTOR), 200)
    assert acct["balance_cents"] == 75000
    assert acct["amount_collected_cents"] == 25000
