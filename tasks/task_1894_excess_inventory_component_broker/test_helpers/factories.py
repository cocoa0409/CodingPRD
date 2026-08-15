"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "SELLER_NAME": "Test Seller",
    "SELLER_EMAIL": "seller@example.com",
    "CUSTOMER_NAME": "Test Customer",
    "CUSTOMER_EMAIL": "customer@example.com",
    "CREDIT_LIMIT_CENTS": 1_000_000,
    "BIN_CAPACITY_UNITS": 100,
    "MPN": "LM317T",
    "OFFER_QUANTITY": 10,
    "ASK_PRICE_PER_UNIT_CENTS": 8000,
    "AGREED_UNIT_PRICE_CENTS": 5000,
    "ACQUISITION_MODE": "BROKER_OWNED",
    "PROVENANCE_DOC_URL": "https://docs.example.com/provenance.pdf",
    "LISTING_ASKING_PRICE_CENTS": 8000,
    "SPOT_PRICE_CENTS": 9000,
    "SNAPSHOT_SOURCE": "DISTRIBUTOR_FEED",
    "BROKER_FEE_BPS": 1000,
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_TO": "2027-08-01T00:00:00Z",
    "ORDER_QUANTITY": 1,
    "RETURN_REASON": "WRONG_PART",
}


def create_seller_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SELLER_NAME"],
        "contact_email": DEFAULTS["SELLER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "contact_email": DEFAULTS["CUSTOMER_EMAIL"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_storage_bin_payload(**overrides) -> dict:
    defaults = {
        "bin_code": "BIN-0001",
        "capacity_units": DEFAULTS["BIN_CAPACITY_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_buy_offer_payload(seller_id, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "mpn": DEFAULTS["MPN"],
        "quantity": DEFAULTS["OFFER_QUANTITY"],
        "ask_price_per_unit_cents": DEFAULTS["ASK_PRICE_PER_UNIT_CENTS"],
        "provenance_doc_url": DEFAULTS["PROVENANCE_DOC_URL"],
    }
    defaults.update(overrides)
    return defaults


def accept_buy_offer_payload(**overrides) -> dict:
    defaults = {
        "agreed_unit_price_cents": DEFAULTS["AGREED_UNIT_PRICE_CENTS"],
        "acquisition_mode": DEFAULTS["ACQUISITION_MODE"],
    }
    defaults.update(overrides)
    return defaults


def inspect_buy_offer_payload(**overrides) -> dict:
    defaults = {
        "outcome": "PASS",
    }
    defaults.update(overrides)
    return defaults


def convert_to_lot_payload(storage_bin_id, **overrides) -> dict:
    defaults = {"storage_bin_id": storage_bin_id}
    defaults.update(overrides)
    return defaults


def create_consignment_agreement_payload(seller_id, lot_id, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "lot_id": lot_id,
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
        "broker_fee_bps": DEFAULTS["BROKER_FEE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "asking_price_per_unit_cents": DEFAULTS["LISTING_ASKING_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def patch_listing_payload(asking_price_per_unit_cents, expected_listing_version, **overrides) -> dict:
    defaults = {
        "asking_price_per_unit_cents": asking_price_per_unit_cents,
        "expected_listing_version": expected_listing_version,
    }
    defaults.update(overrides)
    return defaults


def create_market_price_snapshot_payload(**overrides) -> dict:
    defaults = {
        "mpn": DEFAULTS["MPN"],
        "spot_price_cents": DEFAULTS["SPOT_PRICE_CENTS"],
        "source": DEFAULTS["SNAPSHOT_SOURCE"],
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(customer_id, listing_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "listing_id": listing_id,
        "quantity": DEFAULTS["ORDER_QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_return_case_payload(sales_order_id, **overrides) -> dict:
    defaults = {
        "sales_order_id": sales_order_id,
        "reason": DEFAULTS["RETURN_REASON"],
    }
    defaults.update(overrides)
    return defaults
