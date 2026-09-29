"""
Entity surface: minted identity, declared defaults, computed fields the client may
not supply, listing windows, and the two shapes of a refused create.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from test_helpers.assertions import assert_envelope_meta, assert_page
from test_helpers.test_users import ADMIN_HEADERS, make_agency_headers
from test_helpers.types import (
    ACCOUNT_ACTIVE,
    AGENCY_ACTIVE,
    BENEFIT_BAGGAGE_FEE_CREDIT,
    CATEGORY_GAS,
    ENTITLEMENT_ACTIVE,
    OFFER_OPEN,
    PARITY_IN,
    POSTURE_CLEAR,
    PRODUCT_PREMIER,
)

UNKNOWN_ID = "00000000-0000-0000-0000-0000000f0f0f"


def test_a_new_account_carries_its_minted_identity_and_declared_defaults(api):
    """
    "A freshly enrolled account starts with `status` `ACTIVE`, `fraud_posture`
    `CLEAR`, and every points aggregate at zero."

    Design: Corner/entities/account_creation_returns_envelope_with_system_and_default_fields
    """
    response = api.create_account(
        f.account_payload(
            cardholder_name="Hana Vidal",
            email="hana@example.com",
            card_product_code=PRODUCT_PREMIER,
            enrolled_at="2025-01-15T00:00:00.000Z",
        ),
        ADMIN_HEADERS,
    )

    assert_envelope_meta(response, "object")
    data = validate_success(response, 201)
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert data["cardholder_name"] == "Hana Vidal"
    assert data["card_product_code"] == PRODUCT_PREMIER
    assert data["status"] == ACCOUNT_ACTIVE
    assert data["fraud_posture"] == POSTURE_CLEAR
    assert data["points_balance"] == 0
    assert data["points_pending_redemption"] == 0
    assert data["transfer_hold_count"] == 0
    assert data["terms_notice_id"] is None
    assert data["closed_at"] is None
    assert data["version"] == 1


def test_reading_an_agency_echoes_the_stored_row_and_its_zero_payable(api):
    """
    "A newly onboarded agency is `ACTIVE` with `payable_cents` at 0, and
    `suspended_reason` null."

    Design: Corner/entities/agency_partner_retrieval_returns_stored_row
    """
    created = fx.new_agency(
        api,
        ADMIN_HEADERS,
        name="Cobalt Concierge",
        contracted_markup_bps=2500,
        parity_tolerance_bps=500,
        invoice_terms_days=45,
    )

    row = validate_success(api.get_agency_partner(created["id"], ADMIN_HEADERS))

    assert row["name"] == "Cobalt Concierge"
    assert row["contracted_markup_bps"] == 2500
    assert row["parity_tolerance_bps"] == 500
    assert row["invoice_terms_days"] == 45
    assert row["status"] == AGENCY_ACTIVE
    assert row["payable_cents"] == 0
    assert row["suspended_reason"] is None


def test_the_account_listing_reports_the_window_and_the_matching_total(api):
    """
    "`total_count` is the number of rows matching the filters before the window is
    applied, and `has_more` is true exactly when rows remain beyond `offset` plus
    `limit`."

    Design: Corner/entities/accounts_list_paginates_with_total_count_and_has_more
    """
    fx.new_account(
        api, ADMIN_HEADERS, cardholder_name="Alpha One", email="alpha@example.com",
        card_product_code=PRODUCT_PREMIER,
    )
    fx.new_account(
        api, ADMIN_HEADERS, cardholder_name="Beta Two", email="beta@example.com",
        card_product_code=PRODUCT_PREMIER,
    )
    fx.new_account(
        api, ADMIN_HEADERS, cardholder_name="Gamma Three", email="gamma@example.com"
    )

    first = api.list_accounts(ADMIN_HEADERS, {"limit": 2, "offset": 0})
    assert_page(first, total_count=3, has_more=True, limit=2, offset=0, length=2)

    second = api.list_accounts(ADMIN_HEADERS, {"limit": 2, "offset": 2})
    assert_page(second, total_count=3, has_more=False, limit=2, offset=2, length=1)

    filtered = api.list_accounts(ADMIN_HEADERS, {"card_product_code": "CORE"})
    rows, meta = validate_paginated(filtered)
    assert meta["total_count"] == 1
    assert [row["cardholder_name"] for row in rows] == ["Gamma Three"]


def test_reading_an_id_that_was_never_minted_is_a_naming_404(api):
    """
    "The first identifier that names no row rejects the request with
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404), and the message names the resource type that
    failed to resolve."

    Design: Corner/entities/account_get_unknown_id_not_found
    """
    error = validate_error(
        api.get_account(UNKNOWN_ID, ADMIN_HEADERS), ERR_RESOURCE_NOT_FOUND, 404
    )

    assert "Account" in error["message"]
    assert api.get_account(UNKNOWN_ID, ADMIN_HEADERS).json()["response_type"] == "error"


def test_an_enrolment_missing_its_email_is_refused_and_stores_nothing(api):
    """
    "Required fields present, types correct, enum members recognised, the numeric
    constraints stated throughout §3 honoured, declared arrays non-empty, and no
    duplicate members in a fraud case's `signals` array (`ERR_INVALID_REQUEST`, 400,
    every endpoint)."

    Design: Corner/entities/account_create_without_email_invalid_request
    """
    payload = f.account_payload(cardholder_name="No Email")
    payload.pop("email")

    validate_error(
        api.create_account(payload, ADMIN_HEADERS), ERR_INVALID_REQUEST, 400
    )

    _, meta = validate_paginated(api.list_accounts(ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_an_omitted_fallback_flag_lands_false_and_a_new_benefit_starts_unused(api):
    """
    "Exactly one row in the whole table may set `is_fallback` to true; it is the
    catch-all used when an inbound purchase presents an `mcc_code` no row maps. The
    flag defaults to false when omitted."

    Design: Corner/entities/merchant_category_is_fallback_defaults_to_false
    """
    account = fx.new_account(
        api, ADMIN_HEADERS, cardholder_name="Dara Kilic", email="dara@example.com"
    )

    category = validate_success(
        api.create_merchant_category(
            f.merchant_category_payload(
                mcc_code="5541",
                display_name="Service Stations",
                base_category=CATEGORY_GAS,
                base_multiplier=1.5,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    entitlement = fx.grant_entitlement(
        api,
        account["id"],
        ADMIN_HEADERS,
        benefit_type=BENEFIT_BAGGAGE_FEE_CREDIT,
        annual_allowance=2,
    )

    assert category["is_fallback"] is False
    assert entitlement["status"] == ENTITLEMENT_ACTIVE
    assert entitlement["used_count"] == 0
    assert entitlement["remaining_allowance"] == 2
    assert entitlement["last_consumed_at"] is None
    assert entitlement["suspension_reason"] is None


def test_the_portal_price_is_recomputed_and_smuggled_computed_fields_are_ignored(api):
    """
    "**The portal price is computed, never supplied.** The offer's
    `portal_price_cents` is the `net_rate_cents` multiplied by one plus the agency's
    `contracted_markup_bps` divided by 10,000, rounded half up to whole cents."

    Design: Corner/entities/offer_portal_price_recomputed_and_client_input_ignored
    """
    agency = fx.new_agency(
        api,
        ADMIN_HEADERS,
        name="Northwind Travel",
        contracted_markup_bps=2000,
        parity_tolerance_bps=1000,
    )
    supplier = make_agency_headers(agency["id"])

    offer = validate_success(
        api.create_offer(
            f.offer_payload(
                agency_partner_id=agency["id"],
                itinerary_code="IAD-CPH-01",
                depart_at="2026-10-01T12:00:00.000Z",
                return_at="2026-10-10T12:00:00.000Z",
                net_rate_cents=40000,
                agency_public_price_cents=50000,
                agency_public_seats=3,
                portal_seats=2,
                tax_cents=4000,
                portal_price_cents=1,
                seats_committed=99,
            ),
            supplier,
        ),
        201,
    )

    assert offer["portal_price_cents"] == 48000
    assert offer["cash_copay_cents"] == 4000
    assert offer["parity_status"] == PARITY_IN
    assert offer["seats_committed"] == 0
    assert offer["status"] == OFFER_OPEN
    assert offer["version"] == 1
