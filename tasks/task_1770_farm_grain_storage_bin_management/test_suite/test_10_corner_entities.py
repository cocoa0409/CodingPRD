"""Corner queue / entities section — CRUD defaults, not-found, required
fields, enum/type constraints, computed-field handling, list pagination,
uniqueness, applicator create/readback."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, is_valid_uuid,
    create_bin, create_lot, create_applicator,
    get_bin, assert_instant_equal,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_bin_payload, create_lot_payload, create_applicator_payload,
    create_reading_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


def test_bin_create_applies_system_defaults(api):
    """PRD section 3.1: "A new bin starts clean: `posture` is `SOUND`,
    `risk_score` is 0.00, `current_inventory_bu` is 0.00, `insect_activity`
    is false, and `last_reading_at` is null."

    Design: Corner/entities/bin_create_applies_system_defaults
    """
    resp = api_client.create_bin(
        create_bin_payload(name="BIN-1", capacity_bu=5000.00, crop="CORN"), SM)
    data = validate_success(resp, expected_status=201)
    assert data["posture"] == "SOUND"
    assert data["risk_score"] == pytest.approx(0.00, abs=1e-9)
    assert data["current_inventory_bu"] == pytest.approx(0.00, abs=1e-9)
    assert data["insect_activity"] is False
    assert data["last_reading_at"] is None
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])


def test_bin_get_not_found_returns_404(api):
    """PRD section 2.9: "the first identifier that does not resolve to an
    existing resource yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/bin_get_not_found_returns_404
    """
    resp = api_client.get_bin(NON_EXISTENT_UUID, SM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_lot_create_missing_required_field_returns_invalid_request(api):
    """PRD section 3.1: "the payload must be well-formed, so a missing field
    or an out-of-range moisture surfaces as `ERR_VALIDATION`".

    Omitting `original_bu` is a 400 ERR_VALIDATION.

    Design: Corner/entities/lot_create_missing_required_field_returns_invalid_request
    """
    b = create_bin(name="BIN-V")
    payload = create_lot_payload(b["id"])
    payload.pop("original_bu")
    resp = api_client.create_lot(payload, SM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_lot_create_invalid_enum_rejected(api):
    """PRD section 3.1: "the `crop` (`CORN`, `SOYBEAN`, or `WHEAT`)".
    PRD section 2.9: "request-shape validation (`ERR_VALIDATION`, HTTP 400)
    covering required fields, enum membership, numeric ranges, date
    ordering, conditional fields, and ticket-number uniqueness".

    `crop` "RICE" is outside the enum -> 400 ERR_VALIDATION.

    Design: Corner/entities/lot_create_invalid_enum_rejected
    """
    b = create_bin(name="BIN-E")
    payload = create_lot_payload(b["id"], crop="RICE", original_bu=100.00)
    resp = api_client.create_lot(payload, SM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_lot_create_computed_field_input_ignored(api):
    """PRD section 3.1: "The lot's book bushels `current_bu` are its
    `original_bu` minus this provisional shrink". PRD section 3.1: "its
    `status` begins at `STORED`."

    Client-supplied current_bu / provisional_shrink_bu / status are ignored;
    the server computes provisional_shrink 27.00 and current_bu 973.00 for a
    1000.00 bu corn fill at 17.0%.

    Design: Corner/entities/lot_create_computed_field_input_ignored
    """
    b = create_bin(name="BIN-C")
    payload = create_lot_payload(
        b["id"], original_bu=1000.00, fill_moisture_pct=17.0)
    # Pollute with client-computed fields that must be ignored
    payload["current_bu"] = 999
    payload["provisional_shrink_bu"] = 0
    payload["status"] = "DEPLETED"
    resp = api_client.create_lot(payload, SM)
    data = validate_success(resp, expected_status=201)
    assert data["current_bu"] == pytest.approx(973.00, abs=1e-9)
    assert data["provisional_shrink_bu"] == pytest.approx(27.00, abs=1e-9)
    assert data["status"] == "STORED"


def test_reading_response_computed_fields(api):
    """PRD section 3.2: "Each reading stores derived values:
    `max_cable_temp_f`, the highest entry of the cable array;
    `temp_delta_f`, the hottest cable minus the ambient temperature;
    `hotspot_triggered`; and `score_after`, the bin's risk score as
    recomputed at ingestion."
    PRD section 3.2: "A reading is a **hotspot** when the hottest cable
    exceeds ambient by at least 30.0 degrees Fahrenheit".

    cables [80.0, 91.5, 88.0], ambient 60.0 -> max 91.5, delta 31.5,
    hotspot true (31.5 >= 30.0). Empty bin -> moisture/staleness zero;
    score = clamp((31.5 - 10)/20, 0, 1) * 50 = 50.00.

    Design: Corner/entities/reading_response_computed_fields
    """
    b = create_bin(name="BIN-RD")
    resp = api_client.create_reading(create_reading_payload(
        b["id"], recorded_at="2026-08-01T06:00:00Z",
        ambient_temp_f=60.0, cable_temps_f=[80.0, 91.5, 88.0],
        insect_activity=False), SM)
    data = validate_success(resp, expected_status=201)
    assert data["max_cable_temp_f"] == pytest.approx(91.5, abs=1e-9)
    assert data["temp_delta_f"] == pytest.approx(31.5, abs=1e-9)
    assert data["hotspot_triggered"] is True
    assert data["score_after"] == pytest.approx(50.00, abs=1e-9)


def test_lot_list_pagination_and_filters(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
    The `offset` parameter skips a number of items from the front of the
    result set and defaults to 0."
    PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."
    PRD section 3.1: "Lots may be listed with optional `bin_id`, `status`,
    `crop`, and `grade` filters plus pagination".

    Three lots under BIN-L; limit 2 page 1 -> total 3, has_more true;
    offset 2 -> 1 item, has_more false. Combined filters return the same
    3-lot total.

    Design: Corner/entities/lot_list_pagination_and_filters
    """
    b = create_bin(name="BIN-L", capacity_bu=9000.00)
    for bu in (100.00, 200.00, 300.00):
        create_lot(b["id"], original_bu=bu)

    resp1 = api_client.list_lots(FO, params={
        "bin_id": b["id"], "status": "STORED", "crop": "CORN",
        "grade": "GRADE_1", "limit": 2, "offset": 0,
    })
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    resp2 = api_client.list_lots(FO, params={
        "bin_id": b["id"], "limit": 2, "offset": 2,
    })
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 3


def test_assessment_duplicate_period_rejected(api):
    """PRD section 3.7: "The period is globally unique — it serves as the
    idempotency key for the whole epoch — and a repeat submission is
    rejected with `ERR_ASSESSMENT_EXISTS`."

    Second 2026-08 run -> 409 ERR_ASSESSMENT_EXISTS; 2026-09 -> 201.

    Design: Corner/entities/assessment_duplicate_period_rejected
    """
    first = api_client.create_assessment({"period": "2026-08"}, SM)
    validate_success(first, expected_status=201)
    dup = api_client.create_assessment({"period": "2026-08"}, SM)
    validate_error(dup, ApiErrorId.ERR_ASSESSMENT_EXISTS, expected_status=409)
    other = api_client.create_assessment({"period": "2026-09"}, SM)
    validate_success(other, expected_status=201)


def test_applicator_create_and_readback(api):
    """PRD section 3.1: "before any fumigation can be recorded a
    `SiteManager` registers each applicator with a `name`, a state-issued
    `license_no`, and a `cert_expires_at` certification expiry."

    Design: Corner/entities/applicator_create_and_readback
    """
    resp = api_client.create_applicator(create_applicator_payload(
        name="Alice A", license_no="LIC-A",
        cert_expires_at="2027-06-01T00:00:00Z"), SM)
    data = validate_success(resp, expected_status=201)
    assert data["name"] == "Alice A"
    assert data["license_no"] == "LIC-A"
    assert_instant_equal(data["cert_expires_at"], "2027-06-01T00:00:00Z")
    assert is_valid_uuid(data["id"])
