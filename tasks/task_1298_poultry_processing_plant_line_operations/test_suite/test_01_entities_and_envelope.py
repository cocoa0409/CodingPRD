"""Entity creation, defaults, append-only events, not-found, and the error envelope."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId,
    assert_processing_line, assert_production_shift, assert_utility_meter_reading,
    create_line_payload, create_shift_payload, create_flock_lot_payload,
    create_utility_reading_payload, create_order_payload,
    TEST_USERS, make_headers,
)

PM = TEST_USERS["plant_manager_headers"]
QA = TEST_USERS["qa_technician_headers"]
RCV = TEST_USERS["receiving_clerk_headers"]
PLAN = TEST_USERS["order_planner_headers"]


class TestEntitiesAndDefaults:

    def test_create_line_returns_201_with_stored_fields(self, api):
        """PRD §4: "Operations that create a new resource return `201 Created`".
        PRD §3.1: "A `PlantManager` registers each line with a `line_code` unique
        across the plant (conventionally something like EV-1 or DB-1), a
        `line_type` of either `EVISCERATION` or `DEBONING`, and a
        `rated_speed_bpm` greater than zero".
        PRD §2.4: "a system-managed integer that increments by one with every
        modification to the resource".
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/entities/create_line_returns_201_with_stored_fields
        """
        resp = api.create_line(
            create_line_payload(line_code="EV-9", line_type="EVISCERATION",
                                rated_speed_bpm=180), PM)
        data = validate_success(resp, expected_status=201)
        assert_processing_line(data)
        assert data["line_code"] == "EV-9"
        assert data["line_type"] == "EVISCERATION"
        assert data["rated_speed_bpm"] == 180
        assert data["version"] == 1
        assert data["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at {data['created_at']} must reflect the startup logical clock")

    def test_shift_create_applies_zero_staffing_defaults(self, api):
        """PRD §3.2: "A new shift is `SCHEDULED`, with all four staffing counts —
        `shacklers_present`, `eviscerators_present`, `deboners_present`, and
        `qa_techs_present` — starting at zero."
        PRD §3.5: "the `suspend_reason` field reads `NONE` whenever the shift is
        not suspended."
        PRD §3.6: "The shift's `labor_hours_remaining` is its
        `labor_hours_budget` minus the sum of `estimated_labor_hours` over the
        shift's batches in `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`, minus the
        sum of `actual_labor_hours` over its batches in `COMPLETED`."

        Design: Corner/entities/shift_create_applies_zero_staffing_defaults
        """
        resp = api.create_shift(
            create_shift_payload(shift_code="NIGHT", shackle_capacity_birds=5000,
                                 labor_hours_budget=20.0), PM)
        data = validate_success(resp, expected_status=201)
        assert_production_shift(data)
        assert data["shacklers_present"] == 0
        assert data["eviscerators_present"] == 0
        assert data["deboners_present"] == 0
        assert data["qa_techs_present"] == 0
        assert data["status"] == "SCHEDULED"
        assert data["suspend_reason"] == "NONE"
        assert data["process_water_gallons"] == 0
        assert data["chiller_water_gallons"] == 0
        assert data["birds_processed"] == 0
        assert data["labor_hours_remaining"] == pytest.approx(20.0)

    def test_get_missing_order_not_found(self, api):
        """PRD §2.6: "Every resource identifier referenced by the path or the
        request body must exist, validated left to right, else `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/get_missing_order_not_found
        """
        resp = api.get_order(NON_EXISTENT_UUID, PLAN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_order_create_invalid_enum_rejected(self, api):
        """PRD §2.6: "Malformed payloads — a missing required field, a type
        mismatch, an invalid enum value, an unknown field, a sanitation
        `window_start` that is not strictly earlier than `window_end`, or a
        required `findings` or `resolution_note` left absent — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.6: "a `temperature_requirement` of `FRESH`, `FROZEN`, or `FLEXIBLE`".

        Design: Corner/entities/order_create_invalid_enum_rejected
        """
        payload = create_order_payload(temperature_requirement="LUKEWARM")
        resp = api.create_order(payload, PLAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_flock_create_with_extra_field_rejected(self, api):
        """PRD §2.6: "Malformed payloads — a missing required field, a type
        mismatch, an invalid enum value, an unknown field, a sanitation
        `window_start` that is not strictly earlier than `window_end`, or a
        required `findings` or `resolution_note` left absent — are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/flock_create_with_extra_field_rejected
        """
        shift = get_success_data(api.create_shift(create_shift_payload(), PM))
        payload = create_flock_lot_payload(shift["id"], lot_code="FL-X",
                                           booked_head_count=100)
        payload["status"] = "SETTLED"  # system-managed field, not an input
        resp = api.create_flock_lot(payload, RCV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_utility_reading_immutable_event_no_version(self, api):
        """PRD §2.4: "Two resources are deliberately different: the utility
        meter reading and the chill-chain log are append-only event records.
        Each carries only `id` and `created_at`; both `updated_at` and `version`
        are absent, because an event, once posted, is never modified."
        PRD §3.5: "the readings of a shift may be listed with an optional
        `meter_type` filter."

        Design: Corner/entities/utility_reading_immutable_event_no_version
        """
        shift = get_success_data(api.create_shift(create_shift_payload(), PM))
        reading = get_success_data(api.create_utility_reading(
            create_utility_reading_payload(shift["id"], meter_type="CHILLER_WATER",
                                           gallons=250.5), QA))
        assert_utility_meter_reading(reading)
        assert reading["gallons"] == pytest.approx(250.5)
        assert reading["meter_type"] == "CHILLER_WATER"
        assert reading["recorded_at"].startswith("2026-08-01T00:00:00")

        data, meta = validate_paginated(
            api.list_shift_utility_readings(shift["id"], QA,
                                            params={"meter_type": "CHILLER_WATER"}))
        matches = [r for r in data if r["id"] == reading["id"]]
        assert len(matches) == 1, "posted reading must be retrievable via the shift sub-resource"
        listed = matches[0]
        assert_utility_meter_reading(listed)
        assert listed["gallons"] == pytest.approx(250.5)


class TestErrorEnvelope:

    def test_error_response_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_response_envelope_shape
        """
        resp = api.get_order(NON_EXISTENT_UUID, PLAN)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

    def test_request_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role that
        is not one of the declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_rejected
        """
        resp = api.create_line(create_line_payload(), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
