"""Entity creation, defaults, system-minted fields, FK / required-field / uniqueness
and multiplier-validity checks.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    setup_catalog_model_customer,
    create_catalog,
    create_customer,
    create_device_model,
    api_client,
    make_customer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]


def test_create_trade_in_returns_201_with_defaults(api):
    """PRD §3.3: "an optional `declared_defects` list of defect-flag keys defaulting to
    an empty list, and an optional `declared_powers_on` boolean defaulting to true."
    PRD §3.3: "The new trade-in is created in `DRAFT` status with `final_value_cents`
    null and a `version` that the lifecycle's later steps will advance."

    POST /trade-ins with required fields only returns 201; status DRAFT,
    declared_defects [], declared_powers_on true, version 1.

    Design: Corner/entities/create_trade_in_returns_201_with_defaults
    """
    _cat, model, customer = setup_catalog_model_customer()
    resp = api.create_trade_in(
        {"customer_id": customer["id"], "device_model_id": model["id"], "declared_grade": "GOOD"},
        make_customer_headers(customer["id"]),
    )
    ti = validate_success(resp, expected_status=201)
    assert ti["status"] == "DRAFT"
    assert ti["declared_defects"] == []
    assert ti["declared_powers_on"] is True
    assert ti["version"] == 1


def test_get_trade_in_not_found_returns_404(api):
    """PRD §2.5: "the server validates each identifier from left to right and rejects
    the request with `ERR_NOT_FOUND` at the **first** identifier that does not resolve."

    GET /trade-ins/{random-uuid} for a non-existent id returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_trade_in_not_found_returns_404
    """
    resp = api.get_trade_in("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, "ERR_NOT_FOUND")


def test_create_trade_in_missing_declared_grade_returns_400(api):
    """PRD §2.4: "Request well-formedness — required body fields are present and
    correctly typed and any enum members are valid, otherwise `ERR_INVALID_REQUEST`."

    POST /trade-ins omitting the required declared_grade returns ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_trade_in_missing_declared_grade_returns_400
    """
    _cat, model, customer = setup_catalog_model_customer()
    resp = api.create_trade_in(
        {"customer_id": customer["id"], "device_model_id": model["id"]},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_create_trade_in_bad_fk_returns_404(api):
    """PRD §3.3: "At creation the supplied `customer_id` and `device_model_id` must
    resolve to existing rows, failing with `ERR_FK_NOT_FOUND` (HTTP 404) otherwise."

    POST /trade-ins with a device_model_id that does not resolve returns ERR_FK_NOT_FOUND.

    Design: Corner/entities/create_trade_in_bad_fk_returns_404
    """
    customer = create_customer()
    resp = api.create_trade_in(
        {"customer_id": customer["id"], "device_model_id": "00000000-0000-4000-8000-0000000000aa", "declared_grade": "GOOD"},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, "ERR_FK_NOT_FOUND")


def test_device_model_status_and_version_system_minted(api):
    """PRD §3.1: "A newly registered model starts with `status` of `ACTIVE`."
    PRD §2.6: "a `version` (an integer that starts at its initial value and increments
    by one on every mutation)."

    A newly registered device model has status ACTIVE and version 1.

    Design: Corner/entities/device_model_id_and_timestamps_are_system_minted
    """
    cat = create_catalog()
    resp = api.create_device_model(
        cat["id"],
        {
            "manufacturer": "Acme", "model_code": "PHN-9", "category": "LAPTOP",
            "base_value_cents": 80000,
            "condition_multipliers": {"FLAWLESS": 1.0, "GOOD": 0.8, "FAIR": 0.6, "POOR": 0.35},
            "defect_deductions": {"CRACKED_SCREEN": 12000, "BATTERY_DEGRADED": 4000, "WATER_DAMAGE": 20000, "MISSING_PARTS": 5000, "WONT_POWER_ON": 15000, "DENTED_BODY": 3000},
        },
        ADMIN,
    )
    dm = validate_success(resp, expected_status=201)
    assert dm["status"] == "ACTIVE"
    assert dm["version"] == 1


def test_duplicate_model_code_returns_409(api):
    """PRD §3.1: "The `model_code` must be unique within its catalog among models that
    are not retired, compared case-insensitively; a collision is rejected with
    `ERR_DUPLICATE` (HTTP 409)."

    A second ACTIVE device model with the same model_code in the same catalog returns
    ERR_DUPLICATE (409).

    Design: Corner/entities/duplicate_model_code_returns_409
    """
    cat = create_catalog()
    create_device_model(cat["id"], model_code="PHN-1")
    resp = api.create_device_model(
        cat["id"],
        {
            "manufacturer": "Globex", "model_code": "PHN-1", "category": "SMARTPHONE",
            "base_value_cents": 50000,
            "condition_multipliers": {"FLAWLESS": 1.0, "GOOD": 0.8, "FAIR": 0.6, "POOR": 0.35},
            "defect_deductions": {"CRACKED_SCREEN": 12000, "BATTERY_DEGRADED": 4000, "WATER_DAMAGE": 20000, "MISSING_PARTS": 5000, "WONT_POWER_ON": 15000, "DENTED_BODY": 3000},
        },
        ADMIN,
    )
    validate_error(resp, "ERR_DUPLICATE")


def test_device_model_bad_multipliers_returns_422(api):
    """PRD §3.1: "The `condition_multipliers` field maps cosmetic grade to a multiplier
    fraction and must define exactly the four keys `FLAWLESS`, `GOOD`, `FAIR`, and
    `POOR`, each a number between 0 and 1 inclusive; a map that omits a key, adds an
    extra key, or carries a value outside that range is rejected with
    `ERR_INVALID_MULTIPLIERS` (HTTP 422)."

    A device model whose condition_multipliers omit POOR returns ERR_INVALID_MULTIPLIERS.

    Design: Corner/entities/device_model_bad_multipliers_returns_422
    """
    cat = create_catalog()
    resp = api.create_device_model(
        cat["id"],
        {
            "manufacturer": "Acme", "model_code": "PHN-2", "category": "SMARTPHONE",
            "base_value_cents": 60000,
            "condition_multipliers": {"FLAWLESS": 1.0, "GOOD": 0.8, "FAIR": 0.6},
            "defect_deductions": {"CRACKED_SCREEN": 12000, "BATTERY_DEGRADED": 4000, "WATER_DAMAGE": 20000, "MISSING_PARTS": 5000, "WONT_POWER_ON": 15000, "DENTED_BODY": 3000},
        },
        ADMIN,
    )
    validate_error(resp, "ERR_INVALID_MULTIPLIERS")


def test_customer_wallet_and_lifetime_default_zero(api):
    """PRD §3.3: "A customer also carries two computed running totals that begin at 0:
    `wallet_balance_cents`, the store-credit balance, and `lifetime_payout_cents`, the
    conserved sum of payouts ever settled to them."

    A freshly created customer has wallet_balance_cents 0 and lifetime_payout_cents 0.

    Design: Corner/entities/customer_wallet_and_lifetime_default_zero
    """
    resp = api.create_customer({"email": "fresh@example.com", "full_name": "Fresh"}, ADMIN)
    cust = validate_success(resp, expected_status=201)
    assert cust["wallet_balance_cents"] == 0
    assert cust["lifetime_payout_cents"] == 0


def test_duplicate_customer_email_returns_409(api):
    """PRD §3.3: "Customers are registered with a unique `email` (compared
    case-insensitively; a collision is rejected with `ERR_DUPLICATE`, HTTP 409)".

    Registering a second customer with an already-used email (case-insensitive) returns
    ERR_DUPLICATE (409).

    Design: Corner/entities/duplicate_customer_email_returns_409
    """
    validate_success(api.create_customer({"email": "dup@example.com", "full_name": "First"}, ADMIN), expected_status=201)
    resp = api.create_customer({"email": "DUP@example.com", "full_name": "Second"}, ADMIN)
    validate_error(resp, "ERR_DUPLICATE")
