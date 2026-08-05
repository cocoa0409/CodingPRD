"""Intake, booking creation, property, and FK-reverse listing (Corner queue)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_inmate, assert_property_item, fixtures,
)
from test_helpers import factories as f

INTAKE = TEST_USERS["intake_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def test_register_inmate_returns_201_in_custody(api):
    """PRD §3.1: "A newly registered inmate starts with `status` `IN_CUSTODY`."
    PRD §2.4: "an integer `version` that starts at 1 and increments by 1 on every mutation."

    Design: Corner/entities/inmate_create_returns_201_with_fields
    """
    resp = api.create_inmate(f.create_inmate_payload(full_name="Test Person"), INTAKE)
    data = validate_success(resp, expected_status=201)
    assert_inmate(data)
    assert data["status"] == "IN_CUSTODY", f"expected IN_CUSTODY, got {data['status']}"
    assert data["version"] == 1, f"expected version 1 at create, got {data['version']}"


def test_get_unknown_booking_returns_not_found(api):
    """PRD §2.6: "existence of every path-referenced resource, validated left-to-right
    along the URL so that a parent named earlier in the path is checked before a child
    named later (`ERR_NOT_FOUND`)".

    Design: Corner/entities/booking_not_found_returns_404
    """
    resp = api.get_booking(NON_EXISTENT_UUID, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_booking_missing_sentence_days_rejected(api):
    """PRD §2.6: "presence and correct typing of required body fields (`ERR_VALIDATION`)".
    PRD §3.1: "the `sentence_days` (which must be strictly greater than zero)".

    Design: Corner/entities/booking_missing_sentence_days_returns_validation
    """
    inmate = fixtures.create_inmate(api)
    payload = {
        "inmate_id": inmate["id"],
        "arrest_datetime": "2026-05-01T00:00:00Z",
        "charge_severity": "FELONY",
        "prior_bookings_count": 0,
        "sentence_start_date": "2026-05-01",
    }
    resp = api.create_booking(payload, INTAKE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_booking_invalid_charge_severity_enum(api):
    """PRD §2.6: "enum-valued fields carrying a declared member (`ERR_INVALID_ENUM`)".
    PRD §3.1: "the most serious `charge_severity` (one of `FELONY`, `MISDEMEANOR`, or `INFRACTION`)".

    Design: Corner/entities/booking_invalid_charge_severity_enum
    """
    inmate = fixtures.create_inmate(api)
    payload = f.create_booking_payload(inmate["id"], charge_severity="TRAFFIC", sentence_days=30)
    resp = api.create_booking(payload, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_booking_auto_provisions_commissary_account(api):
    """PRD §3.4: "Each booking owns exactly one `CommissaryAccount`, created automatically
    at booking time with `balance_cents` and `total_deposited_cents` both at zero."

    Design: Corner/entities/booking_create_auto_provisions_commissary_account
    """
    inmate = fixtures.create_inmate(api, sex="FEMALE")
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=30)
    resp = api.get_commissary_account(booking["id"], INTAKE)
    data = validate_success(resp)
    assert isinstance(data, list) and len(data) == 1, "exactly one account expected"
    account = data[0]
    assert account["balance_cents"] == 0, f"expected balance 0, got {account['balance_cents']}"
    assert account["total_deposited_cents"] == 0, (
        f"expected total_deposited 0, got {account['total_deposited_cents']}"
    )


def test_list_bookings_by_inmate_fk_reverse(api):
    """PRD §3.1: "an `IntakeOfficer` books an inmate by supplying the `inmate_id`".
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count` (the total number
    of matching records before pagination), and `has_more` ... inside `meta`."

    Design: Corner/endpoints/fk_reverse_list_bookings_by_inmate
    """
    inmate = fixtures.create_inmate(api)
    bk1 = fixtures.create_booking(api, inmate["id"], charge_severity="MISDEMEANOR", sentence_days=30)
    bk2 = fixtures.create_booking(api, inmate["id"], charge_severity="FELONY",
                                  prior_bookings_count=1, sentence_days=90)
    resp = api.list_inmate_bookings(inmate["id"], SUPERVISOR)
    data, meta = validate_paginated(resp)
    ids = {b["id"] for b in data}
    assert {bk1["id"], bk2["id"]} <= ids, "both bookings must appear in the FK-reverse list"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"


def test_release_stored_property_item(api):
    """PRD §3.1: "An `IntakeOfficer` may later return a single stored item to its owner,
    moving it from `STORED` to `RETURNED`; a return is permitted only when the item is
    currently `STORED`, otherwise `ERR_INVALID_STATE`."

    Design: Corner/endpoints/property_release_returns_item
    """
    inmate = fixtures.create_inmate(api)
    booking = fixtures.create_booking(api, inmate["id"], sentence_days=30)
    item = fixtures.add_property(api, booking["id"], "silver watch", "ELECTRONICS")
    resp = api.release_property(item["id"], INTAKE)
    data = validate_success(resp)
    assert_property_item(data)
    assert data["property_status"] == "RETURNED", (
        f"expected RETURNED, got {data['property_status']}"
    )
