"""Customer, Pet, and address verification (PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_customer,
    assert_pet,
    assert_version_incremented,
    create_customer_payload,
    create_pet,
    create_pet_payload,
    make_address,
    make_customer_headers,
    reload_customer,
    reload_pet,
    setup_customer_with_pet,
    setup_verified_customer,
    update_pet_payload,
    validate_error,
    validate_success,
)
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Customer creation — address.verified is forced to false on create
# ---------------------------------------------------------------------------
def test_customer_create_initializes_address_verified_false(api):
    """PRD §3.1: 'On create, verified is forced to false regardless of
    input; the address must be verified through the dedicated
    verification capability before any downstream operation that
    requires a verified address may proceed.'
    """
    payload = create_customer_payload(
        default_shipping_address=make_address(verified=True),  # try to lie
    )
    res = api.create_customer(payload, TEST_USERS["customer_headers"])
    customer = validate_success(res, expected_status=201)
    assert_customer(customer)
    assert customer["default_shipping_address"]["verified"] is False, (
        "PRD §3.1: address.verified must be false on create regardless "
        "of input."
    )


def test_customer_create_initializes_money_counters_zero(api):
    """PRD §2.10: 'For every Customer, the sum of total_cents across
    the customer's orders whose payment_status is PAID must equal
    total_charged_cents.' On create no orders exist → both counters
    must be 0.
    """
    res = api.create_customer(
        create_customer_payload(), TEST_USERS["customer_headers"],
    )
    customer = validate_success(res, expected_status=201)
    assert customer["total_charged_cents"] == 0
    assert customer["total_refunded_cents"] == 0


# ---------------------------------------------------------------------------
# Address verification — supported / unsupported countries
# ---------------------------------------------------------------------------
def test_address_verify_succeeds_for_us_address(api):
    """PRD §3.1: 'The verification calculation marks verified as true
    only when all four of the following hold simultaneously: country
    is one of US, CA, UK, AU, DE, FR, JP, CN; postal_code matches the
    country's format (for US, five digits optionally followed by a
    hyphen and four digits; for every other supported country, any
    non-empty string); line1 is non-empty; and city is non-empty.'
    """
    customer = setup_verified_customer()
    assert (
        customer["default_shipping_address"]["verified"] is True
    ), "PRD §3.1: a valid US address should verify to true."


@pytest.mark.parametrize("country", ["XX", "ZZ", "MX"])
def test_address_verify_fails_for_unsupported_country(api, country):
    """PRD §3.1: 'If any of the four checks fails, verified remains
    false and the call is rejected with
    ERR_ADDRESS_VERIFICATION_FAILED.' country outside the supported
    set fails.
    """
    res = api.create_customer(
        create_customer_payload(
            default_shipping_address=make_address(country=country),
        ),
        TEST_USERS["customer_headers"],
    )
    customer = validate_success(res, expected_status=201)
    verify_res = api.verify_customer_address(
        customer["id"], make_customer_headers(customer["id"]),
    )
    validate_error(
        verify_res, ApiErrorId.ERR_ADDRESS_VERIFICATION_FAILED.value,
    )


@pytest.mark.parametrize("postal_code", ["1234", "abcde", "12345-67", ""])
def test_address_verify_fails_for_invalid_us_postal_code(api, postal_code):
    """PRD §3.1: 'for US, five digits optionally followed by a hyphen
    and four digits'. Patterns not matching that regex fail.
    """
    res = api.create_customer(
        create_customer_payload(
            default_shipping_address=make_address(
                country="US", postal_code=postal_code,
            ),
        ),
        TEST_USERS["customer_headers"],
    )
    customer = validate_success(res, expected_status=201)
    verify_res = api.verify_customer_address(
        customer["id"], make_customer_headers(customer["id"]),
    )
    validate_error(
        verify_res, ApiErrorId.ERR_ADDRESS_VERIFICATION_FAILED.value,
    )


@pytest.mark.parametrize("missing_field,bad_value", [
    ("line1", ""),
    ("city", ""),
])
def test_address_verify_fails_when_required_field_empty(
    api, missing_field, bad_value,
):
    """PRD §3.1: 'line1 is non-empty; and city is non-empty.'"""
    addr = make_address()
    addr[missing_field] = bad_value
    res = api.create_customer(
        create_customer_payload(default_shipping_address=addr),
        TEST_USERS["customer_headers"],
    )
    customer = validate_success(res, expected_status=201)
    verify_res = api.verify_customer_address(
        customer["id"], make_customer_headers(customer["id"]),
    )
    validate_error(
        verify_res, ApiErrorId.ERR_ADDRESS_VERIFICATION_FAILED.value,
    )


# ---------------------------------------------------------------------------
# Pet creation — life_stage derivation
# ---------------------------------------------------------------------------
def test_pet_create_initial_life_stage_adult_dog(api):
    """PRD §3.1: 'For dogs, fewer than 12 months gives PUPPY_KITTEN,
    fewer than 84 gives ADULT, and 84 or more gives SENIOR.'
    A 36-month-old dog must be ADULT.
    """
    customer = setup_verified_customer()
    pet = create_pet(
        customer,
        species="DOG",
        birthdate="2023-01-01",  # ~28 months from default test today
    )
    assert_pet(pet)
    assert pet["life_stage"] == "ADULT"


def test_pet_create_initial_life_stage_puppy_dog(api):
    """PRD §3.1: 'For dogs, fewer than 12 months gives PUPPY_KITTEN.'"""
    customer = setup_verified_customer()
    # Very recent birthdate so months < 12 from any reasonable clock.
    pet = create_pet(
        customer,
        species="DOG",
        birthdate="2026-01-01",  # within last year
    )
    assert pet["life_stage"] == "PUPPY_KITTEN"


def test_pet_create_initial_life_stage_senior_dog(api):
    """PRD §3.1: 'For dogs, ... 84 or more gives SENIOR.' Months equals
    the number of whole 30-day intervals between birthdate and now.
    """
    customer = setup_verified_customer()
    pet = create_pet(
        customer,
        species="DOG",
        birthdate="2010-01-01",  # ~16 years old
    )
    assert pet["life_stage"] == "SENIOR"


def test_pet_create_initial_life_stage_senior_cat(api):
    """PRD §3.1: 'For cats ... 120 or more gives SENIOR.'"""
    customer = setup_verified_customer()
    pet = create_pet(
        customer,
        species="CAT",
        birthdate="2010-01-01",  # ~16 years old → >120 months
    )
    assert pet["life_stage"] == "SENIOR"


def test_pet_create_initializes_status_active_and_empty_collections(api):
    """PRD §3.1: 'On create, the pet's life_stage is computed from
    species and birthdate; the system fills photo_gallery and
    adjustment_history with empty arrays, sets status to ACTIVE, and
    the customer_id is taken from the path parameter.'
    """
    customer = setup_verified_customer()
    pet = create_pet(customer)
    assert pet["status"] == "ACTIVE"
    assert pet["photo_gallery"] == []
    assert pet["adjustment_history"] == []
    assert pet["customer_id"] == customer["id"]


def test_pet_update_bumps_version_and_updated_at(api):
    """PRD §2.4: 'version, an integer that starts at 1 on creation and
    is incremented by exactly one on every successful mutation.'
    PRD §3.1: 'A successful update bumps the pet's version and
    refreshes its updated_at.'
    """
    customer, pet = setup_customer_with_pet()
    res = api.update_pet(
        customer["id"], pet["id"],
        update_pet_payload(weight_kg=18.0),
        make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert_version_incremented(after["version"], pet["version"])
    assert after["weight_kg"] == 18.0


def test_pet_update_birthdate_immutable(api):
    """PRD §3.1: 'birthdate is not editable; the implementation must
    reject any attempt to change it.'
    """
    customer, pet = setup_customer_with_pet()
    res = api.update_pet(
        customer["id"], pet["id"],
        {"birthdate": "2000-01-01"},
        make_customer_headers(customer["id"]),
    )
    # PRD does not explicitly name the error_id, but rejecting via 4xx
    # is a hard requirement ('the implementation must reject'). Accept
    # ERR_INVALID_REQUEST as the canonical payload-shape rejection.
    body = res.json()
    assert body["response_type"] == "error", (
        "PRD §3.1: birthdate edits must be rejected."
    )


# ---------------------------------------------------------------------------
# PRD §2.4 OCC on pet update
# ---------------------------------------------------------------------------
def test_pet_update_with_stale_version_rejected(api):
    """PRD §2.4: 'When the caller includes version and the value
    supplied does not equal the entity's current version, the request
    is rejected with HTTP 409 and ERR_VERSION_CONFLICT.'
    """
    customer, pet = setup_customer_with_pet()
    stale_version = pet["version"]
    # First mutation advances version.
    api.update_pet(
        customer["id"], pet["id"],
        update_pet_payload(weight_kg=17.5),
        make_customer_headers(customer["id"]),
    )
    # Second mutation with old version → conflict.
    res = api.update_pet(
        customer["id"], pet["id"],
        update_pet_payload(weight_kg=18.5, version=stale_version),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


def test_pet_update_without_version_skips_occ_check(api):
    """PRD §2.4: 'When the caller omits version, the check is skipped
    and the mutation proceeds (still subject to all other
    validations).'
    """
    customer, pet = setup_customer_with_pet()
    # Bump version once.
    api.update_pet(
        customer["id"], pet["id"],
        update_pet_payload(weight_kg=17.5),
        make_customer_headers(customer["id"]),
    )
    # Now omit version — should still succeed.
    res = api.update_pet(
        customer["id"], pet["id"],
        update_pet_payload(activity_level="HIGH"),
        make_customer_headers(customer["id"]),
    )
    after = validate_success(res)
    assert after["activity_level"] == "HIGH"


# ---------------------------------------------------------------------------
# Photo gallery append-only
# ---------------------------------------------------------------------------
def test_photo_gallery_append_grows_array(api):
    """PRD §2.11: 'Pet.photo_gallery is append-only — once a photo
    with its photo_id, url, and uploaded_at is appended via the gallery
    endpoint, that element cannot be edited or removed.'
    """
    from test_helpers import add_pet_photo_payload

    customer, pet = setup_customer_with_pet()
    res = api.add_pet_photo(
        customer["id"], pet["id"],
        add_pet_photo_payload(url="https://example.com/a.jpg"),
        make_customer_headers(customer["id"]),
    )
    after = validate_success(res, expected_status=201)
    assert len(after["photo_gallery"]) == 1
    entry = after["photo_gallery"][0]
    assert "photo_id" in entry
    assert "url" in entry
    assert "uploaded_at" in entry
