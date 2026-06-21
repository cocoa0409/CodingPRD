"""Breadth tests for pagination/listing, RBAC, optimistic concurrency, derived-field
reconciliation, immediate consistency, and the nothing-payable error.

Queue B (Corner) translations for the `endpoints`, `errors`, `rbac`,
`cross_cutting_complexity_layers`, and `consistency_model` sections.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    make_producer_headers,
    create_active_carrier,
    create_product,
    create_producer,
    create_account,
    create_trust_account,
    create_quoted_policy,
    setup_compliant_writer,
    setup_active_policy_no_split,
    open_trust_account_with_balance,
    open_statement,
    finalize_statement,
    set_clock,
    factories,
)

ADMIN = lambda: TEST_USERS["agency_admin_headers"]
MANAGER = lambda: TEST_USERS["account_manager_headers"]
TRUST = lambda: TEST_USERS["trust_accountant_headers"]


# ===========================================================================
# endpoints
# ===========================================================================
def test_list_carriers_paginated_envelope(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the total number
    of records matching the query before pagination), and `has_more` (true when records beyond
    the current page remain) inside the `meta` object."

    Design: Corner/endpoints/list_carriers_paginated_envelope
    """
    api.create_carrier(factories.create_carrier_payload(name="List A"), ADMIN())
    api.create_carrier(factories.create_carrier_payload(name="List B"), ADMIN())
    resp = api.list_carriers(ADMIN(), params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_list_policies_filtered_by_account(api):
    """PRD §3.3: "Policies may be listed filtered by `account_id`, `product_id`,
    `writing_producer_id`, `renewed_from_policy_id`, and `status`."

    Design: Corner/endpoints/list_policies_filtered_by_account
    """
    carrier = create_active_carrier()
    product = create_product(carrier["id"])
    producer = create_producer()
    account1 = create_account(producer["id"], name="Acct LF1")
    create_account(producer["id"], name="Acct LF2")
    policy = create_quoted_policy(
        {"account": account1, "product": product, "producer": producer},
        annual_premium_cents=100000,
        effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
    )
    resp = api.list_policies(MANAGER(), params={"account_id": account1["id"]})
    data, meta = validate_paginated(resp)
    assert all(p["account_id"] == account1["id"] for p in data), data
    ids = [p["id"] for p in data]
    assert policy["id"] in ids, data
    assert len(data) == 1, data


def test_trust_ledger_entries_subresource(api):
    """PRD §3.9: "Ledger entries can be listed for a given trust account, and across the
    system filtered by `policy_id`, `trust_account_id`, and `entry_type`."

    Design: Corner/endpoints/trust_ledger_entries_subresource
    """
    trust = create_trust_account(state_code="CA")
    get_success_data(
        api.create_ledger_entry(
            trust["id"],
            factories.create_ledger_entry_payload("OPENING_BALANCE", 1_000_000, trust["version"]),
            TRUST(),
        )
    )
    resp = api.list_trust_account_entries(trust["id"], TRUST())
    data, meta = validate_paginated(resp)
    assert len(data) == 1, data
    assert data[0]["entry_type"] == "OPENING_BALANCE", data
    assert data[0]["amount_cents"] == 1_000_000, data


# ===========================================================================
# errors
# ===========================================================================
def test_nothing_payable_on_nonpositive_net(api):
    """PRD §3.10: "A statement whose `net_payable_cents` is zero or negative cannot be paid and
    is rejected with `ERR_NOTHING_PAYABLE` (HTTP 422)."

    Design: Corner/errors/nothing_payable_on_nonpositive_net
    """
    set_clock("2026-03-01T00:00:00Z")
    producer = create_producer()
    trust = create_trust_account(state_code="CA")
    stmt = open_statement(producer["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
    finalized = finalize_statement(stmt["id"], stmt["version"])
    assert finalized["net_payable_cents"] == 0, finalized
    resp = api.pay_statement(
        stmt["id"],
        {"expected_commissionstatement_version": finalized["version"], "trust_account_id": trust["id"]},
        TRUST(),
    )
    validate_error(resp, ApiErrorId.ERR_NOTHING_PAYABLE.value)


# ===========================================================================
# rbac
# ===========================================================================
def test_producer_cannot_create_carrier(api):
    """PRD §2.1: "If the headers are present but the named role is not permitted to invoke the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST `/carriers` ... AgencyAdmin" (Producer is not authorized).

    Design: Corner/rbac/producer_cannot_create_carrier
    """
    producer = create_producer()
    resp = api.create_carrier(
        factories.create_carrier_payload(name="Sneaky"), make_producer_headers(producer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_account_manager_cannot_pay_statement(api):
    """PRD §2.1: "If the headers are present but the named role is not permitted to invoke the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST `/commission-statements/{id}/pay` ... TrustAccountant" (AccountManager is not
    authorized).

    Design: Corner/rbac/account_manager_cannot_pay_statement
    """
    set_clock("2026-03-01T00:00:00Z")
    producer = create_producer()
    trust = create_trust_account(state_code="CA")
    stmt = open_statement(producer["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
    finalized = finalize_statement(stmt["id"], stmt["version"])
    resp = api.pay_statement(
        stmt["id"],
        {"expected_commissionstatement_version": finalized["version"], "trust_account_id": trust["id"]},
        MANAGER(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request to the API (with the single exception noted below) must carry
    two headers identifying the caller ... If either header is missing or malformed, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_carriers({})  # no X-User-ID / X-User-Role.
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# cross_cutting_complexity_layers
# ===========================================================================
def test_occ_split_create_stale_policy_version(api):
    """PRD §2.9: "a request to add a `CommissionSplit` must carry `expected_policy_version`
    matching the target `Policy`'s current `version`. If another writer has advanced the
    policy's `version` since the client last read it ... the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_split_create_stale_policy_version
    """
    carrier = create_active_carrier()
    product = create_product(carrier["id"])
    writer = create_producer(full_name="Writer OC", default_split_pct=0.6)
    servicer = create_producer(full_name="Servicer OC", default_split_pct=0.4)
    account = create_account(writer["id"])
    policy = get_success_data(
        api.create_policy(
            factories.create_policy_payload(
                account["id"], product["id"], writer["id"],
                annual_premium_cents=1_200_000,
                effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
            ),
            make_producer_headers(writer["id"]),
        )
    )
    stale_version = policy["version"]
    # First split advances Policy.version.
    get_success_data(
        api.create_commission_split(
            factories.create_commission_split_payload(
                policy["id"], writer["id"], stale_version, split_pct=0.6, role="WRITING"
            ),
            make_producer_headers(writer["id"]),
        )
    )
    # Second split still carries the stale (pre-first) policy version.
    resp = api.create_commission_split(
        factories.create_commission_split_payload(
            policy["id"], servicer["id"], stale_version, split_pct=0.4, role="SERVICING"
        ),
        make_producer_headers(writer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_ledger_post_stale_trust_version(api):
    """PRD §2.9: "a request to post a `TrustLedgerEntry` must carry
    `expected_trustaccount_version` matching the target `TrustAccount`'s current `version`. If
    another posting ... has advanced the account's `version` since the client last read the
    balance, the post is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_ledger_post_stale_trust_version
    """
    trust = create_trust_account(state_code="CA")
    stale_version = trust["version"]
    get_success_data(
        api.create_ledger_entry(
            trust["id"],
            factories.create_ledger_entry_payload("OPENING_BALANCE", 1_000_000, stale_version),
            TRUST(),
        )
    )
    resp = api.create_ledger_entry(
        trust["id"],
        factories.create_ledger_entry_payload("PREMIUM_RECEIPT", 500000, stale_version),
        TRUST(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occ_correct_version_succeeds_and_increments(api):
    """PRD §2.9: "When such an operation runs, the supplied value must equal the target
    resource's current `version`."
    PRD §3.9: "Posting an entry recomputes the account's `balance_cents` and increments the
    account's `version`".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    trust = create_trust_account(state_code="CA")
    v1 = trust["version"]
    get_success_data(
        api.create_ledger_entry(
            trust["id"],
            factories.create_ledger_entry_payload("OPENING_BALANCE", 1_000_000, v1),
            TRUST(),
        )
    )
    mid = get_success_data(api.get_trust_account(trust["id"], TRUST()))
    get_success_data(
        api.create_ledger_entry(
            trust["id"],
            factories.create_ledger_entry_payload("PREMIUM_RECEIPT", 500000, mid["version"]),
            TRUST(),
        )
    )
    after = get_success_data(api.get_trust_account(trust["id"], TRUST()))
    assert after["version"] == v1 + 2, after
    assert after["balance_cents"] == 1_500_000, after


def test_account_count_derived_field_reconciliation(api):
    """PRD §3.4: "the owning account's `active_policy_count` is recomputed and bubbled up."
    PRD §3.3: "An account tracks a derived `active_policy_count` — the number of policies under
    it whose status is either `ACTIVE` or `PENDING_RENEWAL` — which starts at 0 and is
    recomputed on every policy state change that could affect it."

    Design: Corner/cross_cutting_complexity_layers/account_count_derived_field_reconciliation
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_compliant_writer()
    policy = create_quoted_policy(
        ctx,
        annual_premium_cents=1_200_000,
        effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
    )
    bound = get_success_data(
        api.bind_policy(
            policy["id"], {"expected_policy_version": policy["version"]},
            make_producer_headers(ctx["producer"]["id"]),
        )
    )
    before = get_success_data(api.get_account(ctx["account"]["id"], MANAGER()))
    assert before["active_policy_count"] == 0, before  # BOUND not counted.
    get_success_data(
        api.activate_policy(policy["id"], {"expected_policy_version": bound["version"]}, MANAGER())
    )
    after = get_success_data(api.get_account(ctx["account"]["id"], MANAGER()))
    assert after["active_policy_count"] == 1, after


# ===========================================================================
# consistency_model
# ===========================================================================
def test_immediate_visibility_of_cancel_effects(api):
    """PRD §3.6: "Under the `PRO_RATA` variant, the return premium is the policy's
    `annual_premium_cents` multiplied by the unearned days and divided by the term days, with
    that single result rounded half-up to whole cents".
    PRD §2.2: "operations that create or modify a resource will return the created or updated
    resource object in the data field."

    Design: Corner/consistency_model/immediate_visibility_of_cancel_effects
    """
    set_clock("2026-07-01T00:00:00Z")
    open_trust_account_with_balance(5_000_000, state_code="CA")
    s = setup_active_policy_no_split(
        policy_overrides={
            "annual_premium_cents": 1_200_000,
            "effective_date": "2026-01-01T00:00:00Z",
            "expiration_date": "2027-01-01T00:00:00Z",
        }
    )
    policy = s["policy"]
    resp = api.cancel_policy(
        policy["id"],
        {
            "expected_policy_version": policy["version"],
            "cancellation_date": "2026-07-01T00:00:00Z",
            "cancellation_reason": "INSURED_REQUEST",
        },
        MANAGER(),
    )
    data = validate_success(resp, 200)
    # The cancel response body itself carries the computed figures (no re-read needed).
    assert data["return_premium_cents"] == 604932, data
    assert data["status"] == "CANCELLED", data
