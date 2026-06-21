"""Entity creation defaults, required-field and type validation, FK existence,
owner email uniqueness, and server-forced system fields.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, assert_household,
    create_household, create_owner_payload, create_patient_payload,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]

NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_household_returns_201_with_defaults(api):
    """PRD 3.1: "on creation it starts in status `ACTIVE` ... with `account_credit_cents`
    and `lifetime_invoiced_cents` both initialized to zero and `version` at 1."

    Design: Corner/entities/create_household_returns_201_with_defaults
    """
    res = api.create_household({"account_name": "Alpha"}, RECEPTIONIST)
    hh = validate_success(res, 201)
    assert_household(hh)
    assert hh["status"] == "ACTIVE"
    assert hh["account_credit_cents"] == 0
    assert hh["version"] == 1


def test_get_patient_not_found_returns_404(api):
    """PRD 2.8: "a missing resource yields the corresponding `404` not-found error for
    that resource type ... `ERR_PATIENT_NOT_FOUND`".

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    res = api.get_patient(NON_EXISTENT, RECEPTIONIST)
    validate_error(res, "ERR_PATIENT_NOT_FOUND", expected_status=404)


def test_create_patient_missing_required_species_returns_invalid_request(api):
    """PRD 3.1: "Registration takes the owning `household_id`, the pet's `name`, its
    `species` ... and its current body weight `weight_kg`". PRD 5: ERR_INVALID_REQUEST for
    a missing required field.

    Design: Corner/entities/create_patient_missing_required_species_returns_invalid_request
    """
    hh = create_household("Beta")
    res = api.create_patient({
        "household_id": hh["id"], "name": "NoSpecies", "weight_kg": 5,
    }, RECEPTIONIST)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_patient_bad_weight_returns_invalid_request(api):
    """PRD 3.1: "its current body weight `weight_kg` in kilograms, which must be strictly
    greater than zero". A weight of 0 is rejected with ERR_INVALID_REQUEST.

    Design: Corner/entities/create_patient_bad_weight_returns_invalid_request
    """
    hh = create_household("Gamma")
    res = api.create_patient({
        "household_id": hh["id"], "name": "Zero", "species": "DOG", "weight_kg": 0,
    }, RECEPTIONIST)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_patient_bad_species_enum_returns_invalid_request(api):
    """PRD 3.1: "its `species` — one of `DOG`, `CAT`, `RABBIT`, or `FERRET`". A species
    outside that set is rejected with ERR_INVALID_REQUEST.

    Design: Corner/entities/create_patient_bad_species_enum_returns_invalid_request
    """
    hh = create_household("Delta")
    res = api.create_patient({
        "household_id": hh["id"], "name": "Bird", "species": "PARROT", "weight_kg": 1,
    }, RECEPTIONIST)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_patient_unknown_household_returns_404(api):
    """PRD 2.8: "The same not-found identifiers also apply to foreign keys carried in a
    request body when they fail to resolve" — a patient referencing a non-existent
    household_id yields ERR_HOUSEHOLD_NOT_FOUND.

    Design: Corner/entities/create_patient_unknown_household_returns_404
    """
    res = api.create_patient({
        "household_id": NON_EXISTENT, "name": "Orphan", "species": "CAT", "weight_kg": 3,
    }, RECEPTIONIST)
    validate_error(res, "ERR_HOUSEHOLD_NOT_FOUND", expected_status=404)


def test_create_owner_duplicate_email_returns_email_taken(api):
    """PRD 3.1: "The email must be unique across all owners in the system — an attempt to
    reuse an address already held by another owner is rejected with `ERR_OWNER_EMAIL_TAKEN`."

    Design: Corner/entities/create_owner_duplicate_email_returns_email_taken
    """
    hh = create_household("Eps")
    validate_success(api.create_owner({
        "household_id": hh["id"], "full_name": "First", "email": "dup@x.com",
    }, RECEPTIONIST), 201)
    res = api.create_owner({
        "household_id": hh["id"], "full_name": "Second", "email": "dup@x.com",
    }, RECEPTIONIST)
    validate_error(res, "ERR_OWNER_EMAIL_TAKEN", expected_status=409)


def test_system_fields_ignored_on_patient_create(api):
    """PRD 3.1: "A new patient begins in status `ACTIVE`". A client-supplied status is
    ignored; the server forces ACTIVE.

    Design: Corner/entities/system_fields_ignored_on_patient_create
    """
    hh = create_household("Zeta")
    res = api.create_patient({
        "household_id": hh["id"], "name": "Server", "species": "DOG",
        "weight_kg": 7, "status": "DECEASED",
    }, RECEPTIONIST)
    pat = validate_success(res, 201)
    assert pat["status"] == "ACTIVE", f"Expected forced ACTIVE, got {pat['status']}"
