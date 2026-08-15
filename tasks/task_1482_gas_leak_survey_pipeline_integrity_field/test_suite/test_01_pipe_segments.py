"""Pipe segment registration, envelope shape, pagination, and decommissioning (PRD §2.2, §2.3, §3.1, §3.12)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_pipe_segment,
    get_success_data,
    make_org,
    make_segment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.factories import create_pipe_segment_payload


class TestPipeSegmentRegistration:
    def test_pipe_segment_creation_initializes_computed_fields(self, api):
        """PRD §3.1: "A new segment starts with all three open-grade counters at 0,
        `posture` of `NORMAL`, `status` of `ACTIVE`, and both `last_surveyed_at`
        and `next_survey_due_at` null."
        PRD §2.4: "an integer starting at 1 on creation".

        Design: Corner/entities/pipe_segment_creation_initializes_computed_fields
        """
        ctx = make_org()
        data = validate_success(api.create_pipe_segment(
            create_pipe_segment_payload(segment_code="SEG-C1"), ctx["ia_h"],
        ), expected_status=201)
        assert_pipe_segment(data)
        assert data["status"] == "ACTIVE"
        assert data["posture"] == "NORMAL"
        assert data["open_grade1_count"] == 0
        assert data["open_grade2_count"] == 0
        assert data["open_grade3_count"] == 0
        assert data["last_surveyed_at"] is None
        assert data["next_survey_due_at"] is None
        assert data["version"] == 1

    def test_pipe_segment_missing_segment_code_rejected(self, api):
        """PRD §2.5: "Malformed input, a missing required field, or an out-of-range
        value yields `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "The creation payload carries the operator-assigned `segment_code`".

        Design: Corner/entities/pipe_segment_missing_segment_code_rejected
        """
        ctx = make_org()
        payload = create_pipe_segment_payload(segment_code="SEG-X")
        del payload["segment_code"]
        resp = api.create_pipe_segment(payload, ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_pipe_segment_invalid_material_enum_rejected(self, api):
        """PRD §3.1: "the `material` (one of `STEEL`, `CAST_IRON`, `PLASTIC_PE`,
        `PLASTIC_PVC`, `COPPER`)".
        PRD §2.5: "or an out-of-range value yields `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/pipe_segment_invalid_material_enum_rejected
        """
        ctx = make_org()
        resp = api.create_pipe_segment(
            create_pipe_segment_payload(segment_code="SEG-BADMAT", material="UNOBTAINIUM"),
            ctx["ia_h"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_missing_pipe_segment_returns_not_found(self, api):
        """PRD §2.5: "every identifier referenced by the request — path-template
        identifiers resolved left to right, then identifiers referenced in the
        request body — must resolve to an existing entity, else `ERR_NOT_FOUND`."

        Design: Corner/entities/get_missing_pipe_segment_returns_not_found
        """
        make_org()
        resp = api.get_pipe_segment(NON_EXISTENT_UUID, _bootstrap_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_pipe_segments_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1, and
        may be at most 100. The `offset` parameter defaults to 0. List responses
        include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object."

        Design: Corner/entities/list_pipe_segments_pagination_envelope
        """
        ctx = make_org()
        make_segment(ctx, segment_code="SEG-PG-A")
        make_segment(ctx, segment_code="SEG-PG-B")

        page1, meta1 = validate_paginated(
            api.list_pipe_segments(ctx["ia_h"], params={"limit": 1, "offset": 0})
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_pipe_segments(ctx["ia_h"], params={"limit": 1, "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

    def test_success_envelope_shape_on_create(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format" with "The `api_request_id` is a
        server-generated unique identifier for the request that starts with `req_`."
        and "The `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/success_envelope_shape_on_create
        """
        ctx = make_org()
        resp = api.create_pipe_segment(
            create_pipe_segment_payload(segment_code="SEG-ENV"), ctx["ia_h"],
        )
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
        assert body["data"]["segment_code"] == "SEG-ENV"

    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format" where "The `error_id` is a unique, machine-readable string
        that identifies the specific error" and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_not_found
        """
        make_org()
        resp = api.get_pipe_segment(NON_EXISTENT_UUID, _bootstrap_headers())
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def _bootstrap_headers():
    from test_helpers import TEST_USERS
    return TEST_USERS["integrity_analyst_headers"]


class TestSegmentDecommissioning:
    def test_segment_out_of_service_twice_rejected(self, api):
        """PRD §3.12: "Taking a segment out of service is an `IntegrityAnalyst`
        action requiring the segment to be `ACTIVE` (`ERR_SEGMENT_NOT_ACTIVE`)."

        Design: Corner/state_machines/segment_out_of_service_twice_rejected
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-OS2")
        get_success_data(api.out_of_service_segment(segment["id"], ctx["ia_h"]))
        resp = api.out_of_service_segment(segment["id"], ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_ACTIVE)

    def test_segment_abandon_from_active_rejected(self, api):
        """PRD §3.12: "Abandoning a segment (`OUT_OF_SERVICE → ABANDONED`, terminal)
        likewise requires `OUT_OF_SERVICE` state (`ERR_SEGMENT_NOT_OUT_OF_SERVICE`)."

        Design: Corner/state_machines/segment_abandon_from_active_rejected
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-ABA")
        resp = api.abandon_segment(segment["id"], ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_OUT_OF_SERVICE)

    def test_segment_out_of_service_blocked_by_dispatched_order(self, api):
        """PRD §3.12: "requiring that no repair order on the segment be in
        `DISPATCHED` or `ON_SITE` status (`ERR_OPEN_REPAIR_ORDERS_EXIST`)."

        Design: Corner/state_machines/segment_out_of_service_blocked_by_dispatched_order
        """
        from test_helpers import setup_dispatched_repair
        ctx = setup_dispatched_repair()
        segment = ctx["segments"][0]
        resp = api.out_of_service_segment(segment["id"], ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_OPEN_REPAIR_ORDERS_EXIST)
        after = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert after["status"] == "ACTIVE"

    def test_segment_return_to_service_with_clean_reading(self, api):
        """PRD §3.12: "Returning a segment to service (`OUT_OF_SERVICE → ACTIVE`)
        requires `OUT_OF_SERVICE` state (`ERR_SEGMENT_NOT_OUT_OF_SERVICE`) and
        requires a cathodic-protection reading on the segment, taken within the
        last 90 days, with `is_anomalous` false (`ERR_NO_RECENT_CLEAN_CP_READING`)."

        Design: Corner/state_machines/segment_return_to_service_with_clean_reading
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-RTS")
        get_success_data(api.create_cp_reading(
            {
                "segment_id": segment["id"],
                "test_point_id": "TP-1",
                "pipe_to_soil_potential_mv": -1000.0,
                "instant_off_potential_mv": -950.0,
            },
            ctx["ft_h"],
        ))
        get_success_data(api.out_of_service_segment(segment["id"], ctx["ia_h"]))
        data = validate_success(api.return_to_service_segment(segment["id"], ctx["ia_h"]))
        assert data["status"] == "ACTIVE"
        assert data["version"] == 3  # create=1, out-of-service=2, return=3 (PRD §2.4)

    def test_segment_return_to_service_without_clean_reading(self, api):
        """PRD §3.12: "requires a cathodic-protection reading on the segment, taken
        within the last 90 days, with `is_anomalous` false
        (`ERR_NO_RECENT_CLEAN_CP_READING`)."

        Design: Corner/state_machines/segment_return_to_service_without_clean_reading
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-RTN")
        get_success_data(api.out_of_service_segment(segment["id"], ctx["ia_h"]))
        resp = api.return_to_service_segment(segment["id"], ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_NO_RECENT_CLEAN_CP_READING)
