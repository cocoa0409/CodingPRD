"""Foundations: parcel creation, field validation, FK integrity, and role denial."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_parcel, create_parcel_payload, create_tax_year_payload,
    TEST_USERS, MISSING_UUID,
)

CASHIER = TEST_USERS["cashier_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


def test_create_parcel_returns_201_and_system_fields(api):
    """PRD 4: "Operations that create a new stand-alone resource return `201 Created`."
    PRD 2.4: "an integer `version` that begins at 1 and increments by one on every
    mutation of that resource."

    Design: Corner/entities/create_parcel_returns_201_and_system_fields
    """
    payload = create_parcel_payload(parcel_number="APN-C1", owner_name="Cee One",
                                    situs_address="1 Corner", assessed_value_cents=12345600,
                                    property_class="RESIDENTIAL")
    data = validate_success(api.create_parcel(payload, CASHIER), 201)
    assert_parcel(data)
    assert data["assessed_value_cents"] == 12345600
    assert data["property_class"] == "RESIDENTIAL"
    assert data["version"] == 1


def test_parcel_homestead_defaults_to_false(api):
    """PRD 3.1: "The owner-occupied flag `homestead` is a boolean that defaults to false
    when omitted."

    Design: Corner/entities/parcel_homestead_defaults_to_false
    """
    payload = create_parcel_payload(parcel_number="APN-C2", owner_name="Def Ault",
                                    situs_address="2 Corner", assessed_value_cents=1000000,
                                    property_class="AGRICULTURAL")
    payload.pop("homestead", None)
    data = validate_success(api.create_parcel(payload, CASHIER), 201)
    assert data["homestead"] is False


def test_get_parcel_unknown_id_returns_not_found(api):
    """PRD 2.6: "Ids are validated left to right, and the first unresolved id yields
    `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/get_parcel_unknown_id_returns_not_found
    """
    resp = api.get_parcel(MISSING_UUID, TREASURER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_parcel_missing_required_field_rejected(api):
    """PRD 2.6: "A missing or mistyped field, or a violated amount or date constraint,
    yields `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_parcel_missing_required_field_rejected
    """
    payload = create_parcel_payload(parcel_number="APN-C3", owner_name="No Val",
                                    situs_address="3 Corner", property_class="RESIDENTIAL")
    payload.pop("assessed_value_cents")
    resp = api.create_parcel(payload, CASHIER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_parcel_invalid_property_class_enum_rejected(api):
    """PRD 2.6: "An enum field whose value lies outside its declared domain yields
    `ERR_INVALID_ENUM` (422)."

    Design: Corner/entities/create_parcel_invalid_property_class_enum_rejected
    """
    payload = create_parcel_payload(parcel_number="APN-C4", owner_name="Bad Enum",
                                    situs_address="4 Corner", assessed_value_cents=1000000,
                                    property_class="MANSION")
    resp = api.create_parcel(payload, CASHIER)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_create_parcel_unknown_escrow_agent_fk_rejected(api):
    """PRD 2.6: "Every resource id referenced in the path or body — `bill_id`, `parcel_id`,
    `tax_year_id`, `escrow_agent_id`, and any referral, refund, or
    application id — must resolve to a live resource."

    Design: Corner/entities/create_parcel_unknown_escrow_agent_fk_rejected
    """
    payload = create_parcel_payload(parcel_number="APN-C5", owner_name="No Agent",
                                    situs_address="5 Corner", assessed_value_cents=1000000,
                                    property_class="COMMERCIAL", escrow_agent_id=MISSING_UUID)
    resp = api.create_parcel(payload, CASHIER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_cashier_cannot_certify_tax_year(api):
    """PRD 2.1: "If the role is recognized but not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/cashier_cannot_certify_tax_year
    """
    resp = api.create_tax_year(create_tax_year_payload(), CASHIER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
