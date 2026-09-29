"""
Entity surface, second half: system-captured operators, enum constraints, the two
immutable collections, fallback classification, and the flat topology's FK filters.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from test_helpers.assertions import assert_immutable_row, read_ledger
from test_helpers.test_users import ADMIN_2_HEADERS, ADMIN_2_USER_ID, ADMIN_HEADERS
from test_helpers.types import (
    CATEGORY_DINING,
    CATEGORY_GROCERY,
    CATEGORY_OTHER,
    CHANGE_BENEFIT_REMOVAL,
    CLASSIFICATION_FALLBACK,
    ENTRY_EARN_BASE,
    NOTICE_DRAFT,
    PRODUCT_LEGACY_GOLD,
    SOURCE_TRANSACTION,
)

UNKNOWN_ACCOUNT_ID = "00000000-0000-0000-0000-0000000abcde"


def test_a_drafted_notice_records_the_acting_operator_and_starts_unannounced(api):
    """
    "The acting `X-User-ID` is recorded as `drafted_by_user_id` and the notice starts
    in `DRAFT`, with `announced_at`, `approved_by_user_id`, and `withdrawn_reason`
    null."

    Design: Corner/entities/change_notice_drafted_by_user_id_is_system_captured
    """
    notice = validate_success(
        api.create_notice(
            f.notice_payload(
                notice_code="NB-2026-01",
                change_type=CHANGE_BENEFIT_REMOVAL,
                effective_at="2026-12-01T00:00:00.000Z",
                grandfather_window_days=30,
                cohort_enrolled_before="2025-01-01T00:00:00.000Z",
            ),
            ADMIN_2_HEADERS,
        ),
        201,
    )

    assert notice["drafted_by_user_id"] == ADMIN_2_USER_ID
    assert notice["status"] == NOTICE_DRAFT
    assert notice["announced_at"] is None
    assert notice["approved_by_user_id"] is None
    assert notice["target_agreement_id"] is None
    assert notice["withdrawn_reason"] is None
    assert notice["version"] == 1


def test_a_card_product_outside_the_three_declared_members_is_refused(api):
    """
    "The `card_product_code` is one of `PREMIER`, `CORE`, or `LEGACY_GOLD`, and it is
    the single most consequential input on the row"

    Design: Corner/entities/account_card_product_code_unknown_enum_rejected
    """
    validate_error(
        api.create_account(
            f.account_payload(
                cardholder_name="Ghost Tier",
                email="ghost@example.com",
                card_product_code="PLATINUM_INFINITE",
            ),
            ADMIN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    accepted = validate_success(
        api.create_account(
            f.account_payload(
                cardholder_name="Real Tier",
                email="real@example.com",
                card_product_code=PRODUCT_LEGACY_GOLD,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["card_product_code"] == PRODUCT_LEGACY_GOLD
    _, meta = validate_paginated(api.list_accounts(ADMIN_HEADERS))
    assert meta["total_count"] == 1


def test_a_ledger_entry_carries_only_id_and_created_at(api):
    """
    "`PointsLedgerEntry` and `LiabilitySnapshot` are the two exceptions: both are
    immutable once written, so both carry only `id` and `created_at`. Neither
    `updated_at` nor `version` exists on those two resources at all, and no request
    may address them for mutation."

    Design: Corner/entities/ledger_entry_is_immutable_and_carries_no_version
    """
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code="5411",
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )
    account, _ = fx.funded_account(
        api, 0, cardholder_name="Ivo Sund", email="ivo@example.com"
    )
    purchase = fx.fund_account(api, account["id"], 10000, mcc_code="5411")

    entries = read_ledger(api, ADMIN_HEADERS, account["id"])

    assert len(entries) == 1
    entry = assert_immutable_row(entries[0])
    assert entry["entry_type"] == ENTRY_EARN_BASE
    assert entry["points_delta"] == 10000
    assert entry["balance_after"] == 10000
    assert entry["source_entity_type"] == SOURCE_TRANSACTION
    assert entry["source_entity_id"] == purchase["id"]
    assert entry["occurred_at"] == "2026-08-01T00:00:00.000Z"


def test_an_unmapped_code_earns_at_the_fallback_rows_multiplier(api):
    """
    "Exactly one row in the whole table may set `is_fallback` to true; it is the
    catch-all used when an inbound purchase presents an `mcc_code` no row maps."

    Design: Corner/entities/transaction_unmapped_mcc_falls_back_to_fallback_category
    """
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code="5812",
        display_name="Restaurants",
        base_category=CATEGORY_DINING,
        base_multiplier=3.0,
    )
    fallback = fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code="0000",
        display_name="Unclassified",
        base_category=CATEGORY_OTHER,
        base_multiplier=1.0,
        is_fallback=True,
    )
    account = fx.new_account(
        api, ADMIN_HEADERS, cardholder_name="Zola Ferreira", email="zola@example.com"
    )

    purchase = validate_success(
        api.create_transaction(
            f.transaction_payload(
                account_id=account["id"], mcc_code="9999", amount_cents=50000
            ),
            ADMIN_HEADERS,
        ),
        201,
    )

    assert purchase["classification_source"] == CLASSIFICATION_FALLBACK
    assert purchase["merchant_category_id"] == fallback["id"]
    assert purchase["base_points"] == 500
    assert purchase["bonus_points"] == 0
    assert purchase["total_points_earned"] == 500
    assert purchase["rotation_id"] is None
    assert fx.read_account(api, account["id"])["points_balance"] == 500


def test_a_purchase_naming_no_account_is_a_404_before_any_arithmetic(api):
    """
    "Path parameters are resolved strictly left to right, and body identifiers are
    resolved after path identifiers, again in declaration order. The first identifier
    that names no row rejects the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/transaction_for_unknown_account_id_not_found
    """
    fx.ensure_mapping(
        api,
        ADMIN_HEADERS,
        mcc_code="5411",
        display_name="Grocery Stores",
        base_category=CATEGORY_GROCERY,
        base_multiplier=1.0,
    )

    validate_error(
        api.create_transaction(
            f.transaction_payload(
                account_id=UNKNOWN_ACCOUNT_ID, mcc_code="5411", amount_cents=100000
            ),
            ADMIN_HEADERS,
        ),
        ERR_RESOURCE_NOT_FOUND,
        404,
    )

    _, transactions = validate_paginated(api.list_transactions(ADMIN_HEADERS))
    assert transactions["total_count"] == 0
    _, ledger = validate_paginated(api.list_ledger_entries(ADMIN_HEADERS))
    assert ledger["total_count"] == 0


def test_cascade_created_children_are_reachable_through_their_fk_filters(api):
    """
    "Every list endpoint also accepts the filter parameters named for it in §3 and §4.
    Filters combine conjunctively: a request that supplies both `account_id` and
    `status` returns only rows matching both."

    Design: Corner/entities/flat_topology_children_are_discoverable_by_fk_filters
    """
    account, cardholder = fx.funded_account(
        api, 40000, cardholder_name="Rune Halle", email="rune@example.com"
    )
    agency, offer, supplier = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={
            "name": "Bare Fare Consolidators",
            "contracted_markup_bps": 0,
            "parity_tolerance_bps": 0,
        },
        itinerary_code="MSP-KEF-06",
        net_rate_cents=10000,
        agency_public_price_cents=10000,
        agency_public_seats=2,
        portal_seats=2,
        tax_cents=0,
    )
    order = fx.book(api, offer, account["id"], cardholder, traveler_name="Rune Halle")

    orders, orders_meta = validate_paginated(
        api.list_orders(ADMIN_HEADERS, {"inventory_offer_id": offer["id"]})
    )
    assert orders_meta["total_count"] == 1
    assert orders[0]["id"] == order["id"]
    assert orders[0]["account_id"] == account["id"]
    assert order["points_debited"] == 10000

    offers, offers_meta = validate_paginated(
        api.list_offers(ADMIN_HEADERS, {"agency_partner_id": agency["id"]})
    )
    assert offers_meta["total_count"] == 1
    assert offers[0]["id"] == offer["id"]

    earns, earns_meta = validate_paginated(
        api.list_ledger_entries(
            ADMIN_HEADERS, {"account_id": account["id"], "entry_type": ENTRY_EARN_BASE}
        )
    )
    assert earns_meta["total_count"] == 1
    assert earns[0]["points_delta"] == 40000
