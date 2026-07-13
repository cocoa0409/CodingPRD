"""Carrier/entity registration, read shapes, pagination, and authentication.

Corner-design (breadth) translations from the `entities`, `consistency_model`, and
`rbac` sections, plus the carrier not-found error.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_carrier_payload,
    create_screening_payload,
    assert_carrier,
    setup_referred_overweight_screening,
    create_carrier,
    create_station,
    create_bay,
    create_driver,
    create_screening,
)

ADMIN = TEST_USERS["compliance_admin_headers"]
SCREENER = TEST_USERS["screener_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
BOGUS_UUID = "00000000-0000-4000-8000-000000000000"


def test_carrier_create_returns_active_defaults(api):
    """PRD §3.1: "A freshly registered carrier begins in `status` `ACTIVE` with
    `oos_points`, `unpaid_fines_cents`, `iss_score`, and `certified_iss_score` all
    zero, `prism_flagged` and `registration_hold` both false, and `version` 1."

    Design: Corner/entities/carrier_create_returns_defaults
    """
    resp = api.create_carrier(
        create_carrier_payload(usdot_number="DOT-C1", legal_name="Corner One"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_carrier(data)
    assert data["status"] == "ACTIVE"
    assert data["oos_points"] == 0
    assert data["unpaid_fines_cents"] == 0
    assert data["iss_score"] == 0
    assert data["certified_iss_score"] == 0
    assert data["prism_flagged"] is False
    assert data["registration_hold"] is False
    assert data["version"] == 1


def test_carrier_get_missing_returns_404(api):
    """PRD §2.5: "A missing carrier yields `ERR_CARRIER_NOT_FOUND`, a missing station
    `ERR_STATION_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing driver
    `ERR_DRIVER_NOT_FOUND`, a missing screening `ERR_SCREENING_NOT_FOUND`, a missing
    inspection `ERR_INSPECTION_NOT_FOUND`, and a missing citation
    `ERR_CITATION_NOT_FOUND`."

    Design: Corner/entities/carrier_get_not_found_returns_404
    """
    resp = api.get_carrier(BOGUS_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)


def test_carrier_duplicate_usdot_rejected(api):
    """PRD §3.1: "The `usdot_number` must be unique across all carriers; a second
    registration reusing an existing number is rejected with `ERR_DUPLICATE_USDOT`."

    Design: Corner/entities/carrier_duplicate_usdot_rejected
    """
    validate_success(api.create_carrier(
        create_carrier_payload(usdot_number="DOT-DUP", legal_name="First"), ADMIN),
        expected_status=201)
    resp = api.create_carrier(
        create_carrier_payload(usdot_number="DOT-DUP", legal_name="Second"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_USDOT)


def test_screening_missing_required_field_rejected(api):
    """PRD §2.6: "Field and constraint validity — required fields, enum membership,
    ranges, USDOT uniqueness, and bay availability; otherwise `ERR_VALIDATION`,
    `ERR_DUPLICATE_USDOT`, or `ERR_BAY_UNAVAILABLE` (422 for the first, 409 for the
    latter two)."

    Design: Corner/entities/screening_missing_required_field_returns_422
    """
    carrier = create_carrier(usdot_number="DOT-C2", legal_name="Corner Two")
    station = create_station(name="S2", state_code="AZ")
    driver = create_driver(carrier["id"], cdl_number="CDL-C2", full_name="Cor Two")
    payload = create_screening_payload(station["id"], carrier["id"], driver["id"],
                                       vehicle_plate="PLT-C2", heaviest_axle_lbs=19000)
    del payload["gross_weight_lbs"]  # omit a required field
    resp = api.create_screening(payload, SCREENER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_carrier_list_pagination_shape(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/carrier_list_pagination_shape
    """
    create_carrier(usdot_number="DOT-P1", legal_name="Page One")
    create_carrier(usdot_number="DOT-P2", legal_name="Page Two")
    resp = api.list_carriers(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_inspection_driver_id_copied_from_screening(api):
    """PRD §3.4: "The inspection copies its `driver_id` from the screening, starts in
    `status` `IN_PROGRESS` with `result` `NONE`, `oos_flag` false, `reinspection_count`
    zero, and `oos_points_applied` zero."

    Design: Corner/entities/inspection_driver_id_copied_from_screening
    """
    d = setup_referred_overweight_screening(
        carrier_overrides={"usdot_number": "DOT-C3", "legal_name": "Corner Three"})
    resp = api.create_inspection(
        {"screening_id": d["screening"]["id"], "bay_id": d["bay"]["id"], "level": "LEVEL_I",
         "scheduled_start": "2026-03-02T10:00:00Z", "scheduled_end": "2026-03-02T11:00:00Z"},
        INSPECTOR)
    data = validate_success(resp, expected_status=201)
    assert data["driver_id"] == d["driver"]["id"]


def test_carrier_create_visible_in_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/carrier_create_visible_in_same_response
    """
    resp = api.create_carrier(
        create_carrier_payload(usdot_number="DOT-C24", legal_name="Corner TwentyFour"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["legal_name"] == "Corner TwentyFour"
    assert data["status"] == "ACTIVE"
    assert data["id"]


def test_unauthenticated_missing_role_rejected(api):
    """PRD §2.1: "A request that omits either header, or that presents an `X-User-Role`
    value outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_missing_role_returns_401
    """
    resp = api.create_carrier(
        create_carrier_payload(usdot_number="DOT-C21", legal_name="Corner TwentyOne"),
        headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
