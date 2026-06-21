"""Inventory CRUD, creation defaults, field validation, and locker out-of-service.

Covers corner-design 'entities' instances plus the locker OOS round-trip.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_facility_payload, create_locker_unit_payload, create_customer_payload,
    create_form_1583_payload, create_rental_agreement_payload,
    assert_facility, assert_locker_unit,
    TEST_USERS, make_facility_operator_headers, make_compliance_officer_headers,
    setup_active_agreement, create_facility, create_customer, create_form,
)

OP = make_facility_operator_headers()
CO = make_compliance_officer_headers()


def test_create_facility_returns_201_with_defaults(api):
    """PRD §3.1: "A FacilityOperator stands up a facility by supplying its name
    and, optionally, a time_zone; when the time zone is omitted it defaults to UTC.
    A new facility opens with its logical clock at the epoch, its total_locker_count
    and available_locker_count at zero, and its version at 1."

    Design: Corner/entities/create_facility_returns_201_with_defaults
    """
    resp = api.create_facility({"name": "Depot"}, OP)
    data = validate_success(resp, expected_status=201)
    assert_facility(data)
    assert data["time_zone"] == "UTC", "time_zone must default to UTC"
    assert data["version"] == 1, "version must start at 1"
    assert data["available_locker_count"] == 0, "available_locker_count must open at 0"
    assert data["total_locker_count"] == 0, "total_locker_count must open at 0"
    assert data["current_utc"] == "1970-01-01T00:00:00.000Z", "clock must open at the epoch"


def test_create_locker_missing_size_tier_returns_invalid_request(api):
    """PRD §2.10: "A request body is well-formed when every required field is
    present, every enum value is one of its declared members, every integer
    respects its declared minimum, and — for a forwarding request whose kind is
    FORWARD — a destination_address is supplied. A body that violates any of these
    is rejected with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_locker_missing_size_tier_returns_invalid_request
    """
    fac = create_facility(name="Depot")
    resp = api.create_locker_unit({"facility_id": fac["id"], "label": "L1"}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_locker_bad_enum_size_tier_returns_invalid_request(api):
    """PRD §3.1: "An operator creates a LockerUnit by giving its facility_id, a
    physical label that must be unique within the facility, and a size_tier of
    SMALL, MEDIUM, LARGE, or XL."
    PRD §2.10: "A body that violates any of these is rejected with
    ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_locker_bad_enum_size_tier_returns_invalid_request
    """
    fac = create_facility(name="Depot")
    resp = api.create_locker_unit(
        create_locker_unit_payload(fac["id"], label="L1", size_tier="HUGE"), OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_package_nonexistent_returns_not_found(api):
    """PRD §2.8: "For any such path the system validates identifiers left to right
    and rejects the request with ERR_NOT_FOUND (HTTP 404) at the first identifier
    in the path that does not resolve, before considering anything to its right."

    Design: Corner/entities/get_package_nonexistent_returns_not_found
    """
    create_facility(name="Depot")
    resp = api.get_package(NON_EXISTENT_UUID, OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_rental_agreement_unknown_mailbox_fk_returns_not_found(api):
    """PRD §2.8: "any foreign key supplied in a body — a facility_id, a customer_id,
    a mailbox_unit_id, a form_1583_id, a rental_agreement_id, a mail_item_id, an
    invoice_id, a locker_unit_id — must reference an existing row, and a dangling
    reference is ERR_NOT_FOUND."

    Design: Corner/entities/create_rental_agreement_unknown_mailbox_fk_returns_not_found
    """
    fac = create_facility(name="Depot")
    cust = create_customer(fac["id"], email="z@x.com")
    form = create_form(fac["id"], cust["id"])
    resp = api.create_rental_agreement(
        create_rental_agreement_payload(fac["id"], cust["id"], NON_EXISTENT_UUID,
                                        form["id"], term_months=1), OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_duplicate_customer_email_returns_duplicate(api):
    """PRD §3.2: "A customer is registered with a facility_id, a full_name, an
    email unique within the facility, and a phone; a Customer begins ACTIVE, and a
    duplicate email in the same facility is rejected with ERR_DUPLICATE."

    Design: Corner/entities/duplicate_customer_email_returns_duplicate
    """
    fac = create_facility(name="Depot")
    get_success_data(api.create_customer(
        create_customer_payload(fac["id"], full_name="A", email="c@x.com", phone="1"), OP))
    resp = api.create_customer(
        create_customer_payload(fac["id"], full_name="B", email="c@x.com", phone="2"), OP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_package_oversize_fee_computed_in_tier_is_zero(api):
    """PRD §3.4: "A six-digit pickup_code is minted and held on the package, and
    the oversize surcharge is computed once and pinned into oversize_fee_cents (see §3.5)."
    PRD §3.5: "the dimension caps are 30 cm for SMALL, 50 cm for MEDIUM, 80 cm for
    LARGE, and 120 cm for XL; the weight caps are 2,000 g for SMALL, 5,000 g for
    MEDIUM, 15,000 g for LARGE, and 40,000 g for XL."

    Design: Corner/entities/package_oversize_fee_computed_input_ignored
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1, locker_size="MEDIUM")
    resp = api.create_package(
        {"facility_id": s["facility"]["id"], "rental_agreement_id": s["agreement"]["id"],
         "carrier": "UPS", "size_tier": "MEDIUM", "longest_dim_cm": 40, "weight_g": 3000}, OP)
    data = validate_success(resp, expected_status=201)
    assert data["oversize_fee_cents"] == 0, "in-tier MEDIUM package has no oversize fee"
    assert isinstance(data["pickup_code"], str) and len(data["pickup_code"]) == 6 \
        and data["pickup_code"].isdigit(), "pickup_code must be a 6-digit string"


def test_locker_oos_then_restore_roundtrip(api):
    """PRD §3.1: "An operator may take an AVAILABLE locker out of service,
    transitioning AVAILABLE → OUT_OF_SERVICE and decrementing available_locker_count
    by one; restoring it transitions OUT_OF_SERVICE → AVAILABLE and increments the
    count by one."

    Design: Corner/state_machines/locker_oos_then_restore_roundtrip
    """
    fac = create_facility(name="Depot")
    locker = get_success_data(api.create_locker_unit(
        create_locker_unit_payload(fac["id"], label="L1", size_tier="SMALL"), OP))

    validate_success(api.locker_out_of_service(locker["id"], OP))
    fac_oos = validate_success(api.get_facility(fac["id"], OP))
    assert fac_oos["available_locker_count"] == 0, "available drops to 0 while OUT_OF_SERVICE"

    validate_success(api.locker_restore(locker["id"], OP))
    fac_restored = validate_success(api.get_facility(fac["id"], OP))
    assert fac_restored["available_locker_count"] == 1, "available returns to 1 after restore"
