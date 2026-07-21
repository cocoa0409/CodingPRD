"""Developer accounts, marketplace configuration and the payout-hold guard."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_developer,
    assert_revenue_share_tier,
    assert_tax_jurisdiction,
    configure_jurisdiction,
    configure_tier,
    create_developer,
    create_developer_payload,
    create_tax_jurisdiction_payload,
    create_verified_developer,
    make_developer_headers,
    read_developer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_open_developer_account_starts_pending_verification(api, admin_headers):
    """PRD 3.2: "New accounts begin at `PENDING_VERIFICATION`, with `payout_hold` and
    `risk_watch` both false, with `policy_strike_count`, `lifetime_revenue_base_cents`,
    `unpaid_accrual_cents`, `negative_balance_cents`, `carryover_cents` and `risk_score`
    all at 0, and with `risk_variant` at `STANDARD`."
    PRD 2.4: "The `version` of a resource begins at 1 when the resource is created and
    advances by exactly 1 on every mutation of that resource, with `updated_at` refreshed
    at the same moment."

    Design: Corner/entities/corner_developer_create_returns_201_pending_verification
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    payload = create_developer_payload(
        legal_name="Fresh Start LLC", email="fresh@start.test",
        country_code="US", tax_id_provided=True,
    )
    data = validate_success(api.create_developer(payload, admin_headers), 201)
    assert_developer(data)
    assert data["status"] == "PENDING_VERIFICATION"
    assert data["version"] == 1
    assert data["payout_hold"] is False
    assert data["risk_watch"] is False
    assert data["lifetime_revenue_base_cents"] == 0
    assert data["unpaid_accrual_cents"] == 0
    assert data["negative_balance_cents"] == 0
    assert data["carryover_cents"] == 0
    assert data["risk_score"] == 0
    assert data["risk_variant"] == "STANDARD"
    assert data["policy_strike_count"] == 0


def test_read_developer_returns_the_persisted_legal_name(api, admin_headers):
    """PRD 3.2: "A developer account is opened by a `PlatformAdmin` with a `legal_name` —
    the payee name that will be printed on the annual tax form — an `email`, a
    `country_code` of tax residence given as two uppercase letters, and optionally
    `tax_id_provided`."

    Design: Corner/entities/corner_developer_get_by_id_returns_stored_row
    """
    developer = create_developer(
        api, legal_name="Readback Inc", email="rb@x.test", country_code="US",
        tax_id_provided=True,
    )
    data = validate_success(api.get_developer(developer["id"], admin_headers))
    assert data["legal_name"] == "Readback Inc"
    assert data["country_code"] == "US"
    assert data["email"] == "rb@x.test"


def test_developer_list_reports_total_count_and_has_more(api, admin_headers):
    """PRD 2.3: "The `meta` object of a list response carries `limit` and `offset` as
    applied, `total_count` giving the number of records matching the filters before
    pagination was applied, and `has_more`, which is true exactly when records remain
    beyond the current page."

    Design: Corner/entities/corner_developers_list_returns_pagination_envelope
    """
    create_developer(api, legal_name="Dev One", email="1@x.test", country_code="US")
    create_developer(api, legal_name="Dev Two", email="2@x.test", country_code="US")
    create_developer(api, legal_name="Dev Three", email="3@x.test",
                     country_code="DE", tax_id_provided=False)

    response = api.list_developers(admin_headers, {"limit": 2, "offset": 0})
    data, meta = validate_paginated(response)
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2
    assert response.json()["response_type"] == "array"


def test_read_unknown_developer_returns_developer_not_found(api, admin_headers):
    """PRD 2.8: "Every resource named in the URL path exists, validated left to right, so
    that the outermost missing segment is the one reported. The error identifier names the
    missing resource type: `ERR_DEVELOPER_NOT_FOUND`, `ERR_APP_NOT_FOUND`,
    `ERR_REVIEW_SUBMISSION_NOT_FOUND`, `ERR_PRICING_PLAN_NOT_FOUND`,
    `ERR_TAX_JURISDICTION_NOT_FOUND`, `ERR_REVENUE_SHARE_TIER_NOT_FOUND`,
    `ERR_PURCHASE_NOT_FOUND`, `ERR_REFUND_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND`,
    `ERR_POLICY_CASE_NOT_FOUND`, `ERR_PAYOUT_BATCH_NOT_FOUND`,
    `ERR_PAYOUT_LINE_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or
    `ERR_TAX_FORM_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/corner_developer_get_unknown_id_returns_not_found
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    response = api.get_developer(NON_EXISTENT_UUID, admin_headers)
    validate_error(response, ApiErrorId.ERR_DEVELOPER_NOT_FOUND)
    assert response.status_code == 404


def test_tax_id_provided_defaults_to_false_when_omitted(api, admin_headers):
    """PRD 3.2: "That last flag defaults to false, and false means the account is in
    backup withholding: every payout line it later generates will have tax withheld."

    Design: Corner/entities/corner_developer_create_omitting_tax_id_provided_defaults_false
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    payload = {"legal_name": "No TIN Co", "email": "notin@x.test", "country_code": "US"}
    data = validate_success(api.create_developer(payload, admin_headers), 201)
    assert data["tax_id_provided"] is False
    assert data["status"] == "PENDING_VERIFICATION"


def test_verify_without_tax_id_is_rejected(api, admin_headers):
    """PRD 3.2: "Verification moves an account `PENDING_VERIFICATION → ACTIVE`, and it is
    refused unless `tax_id_provided` is already true — an attempt against an account with
    no tax identification on file is rejected with `ERR_TAX_ID_REQUIRED`."

    Design: Corner/validations/corner_verify_without_tax_id_returns_tax_id_required
    """
    developer = create_developer(
        api, legal_name="No TIN Two", email="nt2@x.test", country_code="US",
        tax_id_provided=False,
    )
    response = api.verify_developer(developer["id"], admin_headers)
    validate_error(response, ApiErrorId.ERR_TAX_ID_REQUIRED)
    assert response.status_code == 422
    assert read_developer(api, developer["id"])["status"] == "PENDING_VERIFICATION"


def test_pagination_limit_below_one_is_rejected(api, admin_headers):
    """PRD 2.3: "A `limit` outside the range 1 through 100 inclusive, or a negative
    `offset`, or a non-integer value for either, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/corner_pagination_limit_zero_returns_invalid_pagination
    """
    create_developer(api, legal_name="Page Co", email="pg@x.test", country_code="US")
    response = api.list_developers(admin_headers, {"limit": 0})
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION)
    assert response.status_code == 400


def test_second_jurisdiction_for_the_same_country_is_rejected(api, admin_headers):
    """PRD 3.1: "At most one jurisdiction may exist per country; a second registration for
    the same `country_code` is rejected with `ERR_JURISDICTION_EXISTS`."

    Design: Corner/entities/corner_tax_jurisdiction_duplicate_country_code_rejected
    """
    first = configure_jurisdiction(api, "US", 0, True)
    assert_tax_jurisdiction(first)

    duplicate = create_tax_jurisdiction_payload(
        country_code="US", vat_rate_bps=700, marketplace_facilitator=False
    )
    response = api.create_tax_jurisdiction(duplicate, admin_headers)
    validate_error(response, ApiErrorId.ERR_JURISDICTION_EXISTS)
    assert response.status_code == 409

    rows, _meta = validate_paginated(api.list_tax_jurisdictions(admin_headers, {"country_code": "US"}))
    us_rows = [r for r in rows if r["country_code"] == "US"]
    assert len(us_rows) == 1
    assert us_rows[0]["vat_rate_bps"] == 0


def test_read_unknown_revenue_share_tier_returns_its_own_not_found(api, admin_headers):
    """PRD 2.8: "The error identifier names the missing resource type:
    `ERR_DEVELOPER_NOT_FOUND`, `ERR_APP_NOT_FOUND`, `ERR_REVIEW_SUBMISSION_NOT_FOUND`,
    `ERR_PRICING_PLAN_NOT_FOUND`, `ERR_TAX_JURISDICTION_NOT_FOUND`,
    `ERR_REVENUE_SHARE_TIER_NOT_FOUND`, `ERR_PURCHASE_NOT_FOUND`, `ERR_REFUND_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_POLICY_CASE_NOT_FOUND`,
    `ERR_PAYOUT_BATCH_NOT_FOUND`, `ERR_PAYOUT_LINE_NOT_FOUND`,
    `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_TAX_FORM_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/errors/corner_revenue_share_tier_unknown_id_not_found
    """
    tier = configure_tier(api, "BASE", 0, 7000)
    assert_revenue_share_tier(tier)
    response = api.get_revenue_share_tier(NON_EXISTENT_UUID, admin_headers)
    validate_error(response, ApiErrorId.ERR_REVENUE_SHARE_TIER_NOT_FOUND)
    assert response.status_code == 404


def test_suspend_then_reinstate_restores_active_and_clears_hold(api, officer_headers):
    """PRD 3.2: "An `ACTIVE → SUSPENDED` move sets `payout_hold` to true, sets
    `risk_watch` to true — which switches risk scoring to its accelerated window and sets
    `risk_variant` to `ACCELERATED` — and then reaches into payouts: every payout line of
    that developer that is still `PAYABLE` and belongs to a batch in `CALCULATED` or
    `PENDING_APPROVAL` flips `PAYABLE → HELD_DEVELOPER` with its `payout_amount_cents`
    forced to 0."
    PRD 3.2: "Reinstatement by a `PolicyOfficer`, also carrying a `reason`, moves the
    account `SUSPENDED → ACTIVE`, clears `risk_watch` and recomputes the risk score under
    the standard variant."

    Design: Corner/state_machines/corner_developer_suspend_reinstate_cycle_restores_active
    """
    developer = create_verified_developer(
        api, legal_name="Cycle Co", email="cy@x.test", country_code="US"
    )
    suspended = validate_success(
        api.suspend_developer(developer["id"], {"reason": "manual review"}, officer_headers)
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["risk_watch"] is True
    assert suspended["payout_hold"] is True

    reinstated = validate_success(
        api.reinstate_developer(developer["id"], {"reason": "review cleared"}, officer_headers)
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["risk_watch"] is False
    assert reinstated["payout_hold"] is False, (
        "negative_balance_cents is 0, so reinstatement must clear the payout hold"
    )


def test_payout_hold_with_stale_developer_version_is_rejected(api, admin_headers, finance_headers):
    """PRD 2.7: "Setting or clearing a developer's payout hold requires the request body
    to carry `expected_developer_version`, a non-optional field holding the client's last
    observed `version` of the target `Developer`. If that value does not equal the
    developer's current `version`, the request is rejected with
    `ERR_STALE_DEVELOPER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_payout_hold_with_stale_developer_version_returns_412
    """
    created = create_developer(
        api, legal_name="OCC Dev Co", email="occd@x.test", country_code="US"
    )
    assert created["version"] == 1
    verified = validate_success(api.verify_developer(created["id"], admin_headers))
    assert verified["version"] == 2

    response = api.set_payout_hold(
        created["id"],
        {"hold": True, "expected_developer_version": 1, "reason": "stale write"},
        finance_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_DEVELOPER_VERSION)
    assert response.status_code == 412

    after = read_developer(api, created["id"])
    assert after["payout_hold"] is False
    assert after["version"] == 2


def test_payout_hold_with_current_version_succeeds_and_advances_version(api, finance_headers):
    """PRD 2.7: "Setting or clearing a developer's payout hold requires the request body
    to carry `expected_developer_version`, a non-optional field holding the client's last
    observed `version` of the target `Developer`."
    PRD 2.4: "The `version` of a resource begins at 1 when the resource is created and
    advances by exactly 1 on every mutation of that resource, with `updated_at` refreshed
    at the same moment."

    Design: Corner/cross_cutting_complexity_layers/corner_payout_hold_with_current_developer_version_succeeds_and_bumps
    """
    verified = create_verified_developer(
        api, legal_name="OCC Happy Co", email="occh@x.test", country_code="US"
    )
    assert verified["version"] == 2

    data = validate_success(
        api.set_payout_hold(
            verified["id"],
            {"hold": True, "expected_developer_version": 2, "reason": "risk review"},
            finance_headers,
        )
    )
    assert data["payout_hold"] is True
    assert data["version"] == 3
