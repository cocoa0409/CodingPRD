"""CRUD, defaults, computed fields, RBAC forbidden-role, error catalogue, and OCC tests."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, fixtures, factories,
)
from test_helpers.fixtures import (
    SPONSOR_ADMIN, COMPLIANCE, CONTRIB_ADMIN, advisor_headers, officer_headers,
)


# ===========================================================================
# Corner: entities — creation, defaults, retrieval, listing, type/required
# ===========================================================================
def test_create_sponsor_applies_defaults(api):
    """PRD 3.1: "may optionally set policy parameters: `minimum_grant_cents` (the smallest single grant the program will permit, defaulting to 5000 cents, i.e. fifty dollars), `inactivity_quarters` (how many quarters an account may go without a paid grant before it becomes inactivity-eligible, defaulting to 8), and `admin_fee_bps_default` (the default annual administration-fee rate in basis points, defaulting to 50). The sponsor's fiscal clock, `current_quarter_index`, is initialized to 0 at creation."

    Design: Corner/entities/create_sponsor_returns_201_with_defaults_applied
    """
    sponsor = validate_success(api.create_sponsor(
        factories.create_sponsor_payload(name="Default Sponsor"), SPONSOR_ADMIN),
        expected_status=201)
    assert sponsor["minimum_grant_cents"] == 5000
    assert sponsor["inactivity_quarters"] == 8
    assert sponsor["admin_fee_bps_default"] == 50
    assert sponsor["current_quarter_index"] == 0
    assert sponsor["version"] == 1


def test_get_pool_returns_stored_data(api):
    """PRD 3.1: "each tied to a sponsor by `sponsor_id` and described by a `name`, a `risk_tier` that must be one of `CONSERVATIVE`, `BALANCED`, or `GROWTH`, a starting net-asset-value `nav_per_unit_cents`, and a pool-specific annual fee rate `fee_bps"
    PRD (cont.): "A pool starts with `status` of `OPEN`."

    Design: Corner/entities/get_pool_returns_stored_data
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], risk_tier="GROWTH", nav_per_unit_cents=2500, fee_bps=50)
    fetched = validate_success(api.get_pool(pool["id"], advisor_headers("adv-r1")))
    assert fetched["nav_per_unit_cents"] == 2500
    assert fetched["risk_tier"] == "GROWTH"
    assert fetched["status"] == "OPEN"


def test_list_charities_pagination_envelope(api):
    """PRD 2.3: "The `meta` block of a list response reports `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when more records remain beyond the current page)."

    Design: Corner/entities/list_charities_pagination_envelope
    """
    sponsor = fixtures.create_sponsor()
    fixtures.create_charity(sponsor["id"], legal_name="C One", ein="20-9000001")
    fixtures.create_charity(sponsor["id"], legal_name="C Two", ein="20-9000002")
    data, meta = validate_paginated(api.list_charities(
        SPONSOR_ADMIN, params={"sponsor_id": sponsor["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(c["sponsor_id"] == sponsor["id"] for c in data)


def test_get_account_nonexistent_returns_not_found(api):
    """PRD 2.5: "Any path-referenced or body-referenced resource that does not exist causes `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    validate_error(api.get_account(NON_EXISTENT_UUID, SPONSOR_ADMIN),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_pool_missing_risk_tier_invalid_request(api):
    """PRD 3.10: "Generic body-shape problems — a missing required field, an invalid enum value, a non-positive amount, or a non-positive `nav_per_unit_cents` — surface as `ERR_INVALID_REQUEST` on any write endpoint."

    Design: Corner/entities/create_pool_missing_required_field_returns_invalid_request
    """
    sponsor = fixtures.create_sponsor()
    validate_error(api.create_pool(
        {"sponsor_id": sponsor["id"], "name": "Bad Pool", "nav_per_unit_cents": 2500, "fee_bps": 50},
        SPONSOR_ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_grant_default_recurrence_and_anonymous(api):
    """PRD 3.5: "with the `amount_cents` to grant and an optional `is_anonymous` flag (default false)"
    PRD (cont.): "and a `recurrence` of either `ONE_TIME` (the default) or `RECURRING"

    Design: Corner/entities/create_grant_default_recurrence_one_time
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-d1")
    version = fixtures.current_account_version(account["id"])
    grant = validate_success(api.create_grant(
        factories.create_grant_payload(account["id"], charity["id"], 100000, version),
        advisor_headers("adv-d1")), expected_status=201)
    assert grant["recurrence"] == "ONE_TIME"
    assert grant["is_anonymous"] is False
    assert grant["recommended_by_user_id"] == "adv-d1"


def test_computed_cash_balance_initialized_to_zero(api):
    """PRD 3.4: "A new account starts in `status` `ACTIVE` with `cash_balance_cents`, `invested_value_cents`, `committed_grants_cents`, `admin_fee_accrued_cents`, and `grantable_balance_cents` all initialized to 0, and `last_grant_paid_quarter` null."

    Design: Corner/entities/computed_cash_balance_ignores_client_input
    """
    sponsor = fixtures.create_sponsor()
    account = validate_success(api.create_account(
        factories.create_account_payload(sponsor["id"], "adv-c1", account_name="Comp Fund"),
        SPONSOR_ADMIN), expected_status=201)
    assert account["cash_balance_cents"] == 0
    assert account["grantable_balance_cents"] == 0
    assert account["status"] == "ACTIVE"
    assert account["last_grant_paid_quarter"] is None


def test_pool_invalid_risk_tier_enum_rejected(api):
    """PRD 3.1: "a `risk_tier` that must be one of `CONSERVATIVE`, `BALANCED`, or `GROWTH"
    PRD 3.10: "an invalid enum value"
    PRD (cont.): "surface as `ERR_INVALID_REQUEST` on any write endpoint."

    Design: Corner/entities/pool_invalid_risk_tier_enum_rejected
    """
    sponsor = fixtures.create_sponsor()
    validate_error(api.create_pool(
        factories.create_pool_payload(sponsor["id"], risk_tier="AGGRESSIVE"), SPONSOR_ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_substantiation_receipt_immutable_no_version(api):
    """PRD 2.4: "the `SubstantiationReceipt` (the IRS letter minted when a contribution settles) and the `LedgerEntry` (a single posted cash-balance movement)"
    PRD (cont.): "carry **only** `id` and `created_at` — they have neither `updated_at` nor `version"
    PRD 3.3: "a `deductible_value_cents` frozen equal to the contribution's `fair_market_value_cents` at settlement"

    Design: Corner/entities/substantiation_receipt_immutable_no_version_field
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-i1")
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 500000), advisor_headers("adv-i1")))
    get_success_data(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    receipts = get_success_data(api.list_receipts(
        CONTRIB_ADMIN, params={"contribution_id": contrib["id"]}))
    receipt_id = receipts[0]["id"]
    receipt = validate_success(api.get_receipt(receipt_id, CONTRIB_ADMIN))
    assert receipt["deductible_value_cents"] == 500000
    assert "version" not in receipt
    assert receipt["contribution_id"] == contrib["id"]


def test_create_charity_unknown_sponsor_not_found(api):
    """PRD 2.5: "whenever a request body names a foreign-key resource (for example a `donor_account_id`, `charity_id`, `investment_pool_id`, `source_pool_id`, or `target_pool_id`), those references are resolved after the path"
    PRD (cont.): "Any path-referenced or body-referenced resource that does not exist causes `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_charity_with_unknown_sponsor_returns_not_found
    """
    validate_error(api.create_charity(
        factories.create_charity_payload(NON_EXISTENT_UUID, legal_name="Orphan", ein="20-9000099"),
        COMPLIANCE),
        ApiErrorId.ERR_NOT_FOUND.value)


def test_allocation_reverse_reachable_by_account(api):
    """PRD 3.4: "those micro-units are added to the target allocation's `units_micro` (creating the target allocation lazily if the account does not yet hold one)"
    PRD (cont.): "Allocations can be listed and filtered by `donor_account_id`, `investment_pool_id`, and `status`."

    Design: Corner/entities/flat_fk_allocation_reverse_reachable_by_account
    """
    sponsor, pool, account, _buy = fixtures.setup_account_with_pool_holding(
        cash_amount_cents=100000, buy_amount_cents=50000, advisor_user_id="adv-f1",
        nav_per_unit_cents=2500, target_pct_bps=5000)
    allocs = get_success_data(api.list_allocations(
        advisor_headers("adv-f1"), params={"donor_account_id": account["id"]}))
    assert len(allocs) == 1
    assert allocs[0]["donor_account_id"] == account["id"]
    assert allocs[0]["investment_pool_id"] == pool["id"]
    assert allocs[0]["units_micro"] == 20000000
    assert allocs[0]["status"] == "ACTIVE"


# ===========================================================================
# Corner: errors
# ===========================================================================
def test_missing_user_context_rejected(api):
    """PRD 2.1: "Every request must carry two headers identifying the caller: `X-User-ID`, an opaque string identifying the acting user, and `X-User-Role`, naming the role under which the call is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400)."

    Design: Corner/errors/missing_user_context_header_rejected
    """
    validate_error(api.create_sponsor(
        factories.create_sponsor_payload(name="NoHdr Sponsor"), {}),
        ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


def test_invalid_request_negative_amount_rejected(api):
    """PRD 3.10: "Generic body-shape problems — a missing required field, an invalid enum value, a non-positive amount, or a non-positive `nav_per_unit_cents` — surface as `ERR_INVALID_REQUEST` on any write endpoint."

    Design: Corner/errors/invalid_request_negative_amount_rejected
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-er2")
    validate_error(api.create_contribution(
        {"donor_account_id": account["id"], "asset_type": "CASH", "cash_amount_cents": -100},
        advisor_headers("adv-er2")),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_receipt_not_found(api):
    """PRD 2.5: "A request for a substantiation receipt id that does not exist returns `ERR_RECEIPT_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/receipt_not_found_returns_error
    """
    validate_error(api.get_receipt(NON_EXISTENT_UUID, CONTRIB_ADMIN),
                   ApiErrorId.ERR_RECEIPT_NOT_FOUND.value)


def test_not_account_owner_cancel_grant_rejected(api):
    """PRD 2.1: "for owner-scoped actions — cancelling a grant, executing or cancelling a rebalance order, and creating or confirming a succession plan — the acting `DonorAdvisor`'s `X-User-ID` must equal the `primary_advisor_user_id` of the account the action targets; otherwise the request is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403)."

    Design: Corner/errors/not_account_owner_cancel_grant_rejected
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="owner-adv")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "owner-adv")
    validate_error(api.cancel_grant(grant["id"], advisor_headers("intruder-adv")),
                   ApiErrorId.ERR_NOT_ACCOUNT_OWNER.value)
    refreshed = get_success_data(api.get_grant(grant["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "SUBMITTED"


# ===========================================================================
# Corner: rbac — forbidden role
# ===========================================================================
def test_donor_advisor_cannot_settle_contribution(api):
    """PRD 2.1: "ContributionAdmin`** — settles and values irrevocable contributions and mints the IRS substantiation receipts."
    PRD 2.1: "If the headers are present but the named role is not permitted to invoke the requested endpoint (per the authorization column in Section 4), the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/donor_advisor_cannot_settle_contribution
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-rb1")
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 100000), advisor_headers("adv-rb1")))
    validate_error(api.settle_contribution(contrib["id"], advisor_headers("adv-rb1")),
                   ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    refreshed = get_success_data(api.get_contribution(contrib["id"], CONTRIB_ADMIN))
    assert refreshed["status"] == "PENDING"


def test_grant_officer_cannot_vet_charity(api):
    """PRD 2.1: "ComplianceOfficer`** — vets recipient charities for grant eligibility, recording approve, watchlist, and revoke decisions."
    PRD 2.1: "If the headers are present but the named role is not permitted to invoke the requested endpoint (per the authorization column in Section 4), the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/grant_officer_cannot_vet_charity
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_charity(sponsor["id"], legal_name="Rb2 Charity")
    validate_error(api.vet_charity(
        charity["id"], factories.vet_decision_payload("APPROVE"), officer_headers("officer-rb2")),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    refreshed = get_success_data(api.get_charity(charity["id"], COMPLIANCE))
    assert refreshed["status"] == "PENDING_VETTING"


def test_donor_advisor_cannot_create_sponsor(api):
    """PRD 2.1: "SponsorAdmin`** — the sponsoring program's operator. Creates sponsors, investment pools, NAV periods, and donor accounts"
    PRD 2.1: "If the headers are present but the named role is not permitted to invoke the requested endpoint (per the authorization column in Section 4), the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/donor_advisor_cannot_create_sponsor
    """
    validate_error(api.create_sponsor(
        factories.create_sponsor_payload(name="Rb3 Sponsor"), advisor_headers("adv-rb3")),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ===========================================================================
# Corner: cross-cutting OCC
# ===========================================================================
def test_occ_stale_account_version_on_grant_submit(api):
    """PRD 2.9: "if another writer has advanced the account's version since the client last read it — for instance by submitting another grant that raised `committed_grants_cents` and so consumed grantable balance — the submitting client's view of the grantable balance is stale, and the submission is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) rather than silently over-committing the fund."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_grant_submit
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-cc1")
    observed = fixtures.current_account_version(account["id"])
    # First submit with observed version succeeds and bumps the account version.
    get_success_data(api.create_grant(
        factories.create_grant_payload(account["id"], charity["id"], 100000, observed),
        advisor_headers("adv-cc1")))
    # Second submit reuses the now-stale observed version.
    validate_error(api.create_grant(
        factories.create_grant_payload(account["id"], charity["id"], 100000, observed),
        advisor_headers("adv-cc1")),
        ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)


def test_occ_correct_version_grant_submit_succeeds_and_bumps(api):
    """PRD 2.9: "When `expected_account_version` matches the account's current `version`, the submission proceeds, the grant is recorded, and the account's `version` is incremented by one as part of recording the new commitment."
    PRD 3.5: "on success records the grant in `status` `SUBMITTED`, recomputes the account's `committed_grants_cents` and `grantable_balance_cents`, and increments the account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_grant_submit_succeeds_and_bumps
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-cc2")
    ver_before = fixtures.current_account_version(account["id"])
    grant = validate_success(api.create_grant(
        factories.create_grant_payload(account["id"], charity["id"], 150000, ver_before),
        advisor_headers("adv-cc2")), expected_status=201)
    assert grant["status"] == "SUBMITTED"
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["version"] == ver_before + 1
    assert acct["committed_grants_cents"] == 150000
