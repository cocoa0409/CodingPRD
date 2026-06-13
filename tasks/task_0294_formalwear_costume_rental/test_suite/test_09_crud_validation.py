"""Corner: entity creation, input validation, and not-found behavior."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_catalog, create_customer,
    NON_EXISTENT_UUID, assert_catalog, assert_garment_unit,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import (
    create_catalog_payload, create_customer_payload, create_garment_unit_payload,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_create_catalog_returns_201_with_all_fields(api):
    """PRD §3.1: "A freshly created catalog reports an `active_unit_count` of 0".
    PRD §2.4: "The `version` field is an integer that begins at 1 when the resource is created and increases by exactly 1 on every mutation".

    Design: Corner/entities/create_catalog_returns_201_with_all_fields
    """
    set_clock()
    res = api_client.create_catalog(
        create_catalog_payload(style_name="Tux Z", category="FORMALWEAR",
                               daily_rate_cents=5000, deposit_cents=20000,
                               replacement_value_cents=80000, waiver_daily_rate_cents=1200,
                               cleaning_buffer_days=1, late_fee_daily_rate_cents=2000),
        MANAGER)
    catalog = validate_success(res, 201)
    assert_catalog(catalog)
    assert catalog["style_name"] == "Tux Z"
    assert catalog["active_unit_count"] == 0
    assert catalog["version"] == 1


def test_get_catalog_not_found_returns_404(api):
    """PRD §2.5: "the system validates those references left to right, in the order they appear, and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_catalog_not_found_returns_404
    """
    set_clock()
    res = api_client.get_catalog(NON_EXISTENT_UUID, MANAGER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_create_catalog_missing_required_field_returns_invalid_request(api):
    """PRD §2.6: "A well-formed-body check applies to every create and update endpoint and covers: all required fields present, every enum-typed field holding one of its permitted values, every integer at or above its declared minimum, and — on customer creation — the `email` being unique across all existing customers."

    Design: Corner/entities/create_catalog_missing_required_field_returns_invalid_request
    """
    set_clock()
    payload = create_catalog_payload(style_name="Tux NoRate", category="FORMALWEAR")
    del payload["daily_rate_cents"]
    res = api_client.create_catalog(payload, MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_catalog_invalid_enum_category_returns_invalid_request(api):
    """PRD §2.6: "A well-formed-body check applies to every create and update endpoint and covers: all required fields present, every enum-typed field holding one of its permitted values, every integer at or above its declared minimum, and — on customer creation — the `email` being unique across all existing customers."

    Design: Corner/entities/create_catalog_invalid_enum_category_returns_invalid_request
    """
    set_clock()
    res = api_client.create_catalog(
        create_catalog_payload(style_name="Bad Cat", category="SPORTSWEAR"), MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_customer_duplicate_email_returns_invalid_request(api):
    """PRD §2.6: "and — on customer creation — the `email` being unique across all existing customers."

    Design: Corner/entities/create_customer_duplicate_email_returns_invalid_request
    """
    set_clock()
    validate_success(api_client.create_customer(
        create_customer_payload(full_name="First", email="dup@x.com"), CLERK), 201)
    res = api_client.create_customer(
        create_customer_payload(full_name="Second", email="dup@x.com"), CLERK)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_garment_unit_system_fields_defaulted_on_create(api):
    """PRD §3.1: "A new unit comes to life `AVAILABLE`, at `condition_grade` `GRADE_A`, with a `damage_strike_count` of 0, and the owning catalog's `active_unit_count` is recomputed to include it."

    Design: Corner/entities/garment_unit_system_fields_ignored_input_on_create
    """
    set_clock()
    catalog = create_catalog(style_name="Tux Y")
    res = api_client.create_garment_unit(
        create_garment_unit_payload(catalog["id"], "L"), MANAGER)
    unit = validate_success(res, 201)
    assert_garment_unit(unit)
    assert unit["status"] == "AVAILABLE"
    assert unit["condition_grade"] == "GRADE_A"
    assert unit["damage_strike_count"] == 0
