"""Platform-wide concerns: response envelope, pagination, not-found family,
and the logical clock default."""
from datetime import datetime, timedelta

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    TEST_USERS,
    create_program,
    create_zone,
    create_hydrant,
    tag_hydrant_out,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestResponseEnvelope:
    def test_envelope_shape_on_object_and_list(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.3: "The response `meta` object for a list call includes
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/response_envelope_shape_on_object_and_list
        """
        program, zone, hydrant = setup_program_zone_hydrant()

        obj_resp = api.get_hydrant(hydrant["id"], ADMIN)
        validate_success(obj_resp)
        obj_body = obj_resp.json()
        assert "api_request_id" in obj_body["meta"], "meta.api_request_id missing"
        assert "api_request_timestamp" in obj_body["meta"], "meta.api_request_timestamp missing"
        assert obj_body["response_type"] == "object", (
            f"object read must use response_type 'object', got {obj_body['response_type']}"
        )
        assert obj_body["data"]["id"] == hydrant["id"]

        list_resp = api.list_hydrants(ADMIN)
        validate_success(list_resp)
        list_body = list_resp.json()
        assert list_body["response_type"] == "array", (
            f"list read must use response_type 'array', got {list_body['response_type']}"
        )
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in list_body["meta"], f"pagination field {field} missing from meta"
        # PRD §2.3 defaults: limit 10, offset 0.
        assert list_body["meta"]["limit"] == 10
        assert list_body["meta"]["offset"] == 0

    def test_list_pagination_and_status_filter(self, api):
        """PRD §2.3: "The response `meta` object for a list call includes
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.1: "The hydrant list endpoint supports filtering by
        `program_id`, `zone_id`, `private_owner_id`, `status`,
        `active_outage_id`, and `latest_inspection_id`, plus pagination."

        Design: Corner/endpoints/list_pagination_and_status_filter
        """
        program = create_program()
        zone = create_zone()
        create_hydrant(program["id"], zone["id"], hydrant_number="H-1")
        create_hydrant(program["id"], zone["id"], hydrant_number="H-2")

        resp = api.list_hydrants(ADMIN, params={"status": "IN_SERVICE", "limit": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"limit=1 must return exactly 1 hydrant, got {len(data)}"
        assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
        assert meta["has_more"] is True, "has_more must be true when a second item remains"
        assert meta["limit"] == 1
        assert meta["offset"] == 0


class TestNotFoundFamily:
    def test_hydrant_get_not_found_returns_404(self, api):
        """PRD §2.9: "Each missing resource yields its own specific error —
        `ERR_PROGRAM_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`,
        `ERR_PRIVATE_OWNER_NOT_FOUND`, `ERR_HYDRANT_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, `ERR_FLOW_TEST_NOT_FOUND`,
        `ERR_FLUSH_SEQUENCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_OUTAGE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_PART_NOT_FOUND`, `ERR_ISO_SNAPSHOT_NOT_FOUND`."

        Design: Corner/entities/hydrant_get_not_found_returns_404
        """
        resp = api.get_hydrant(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_HYDRANT_NOT_FOUND, 404)

    def test_not_found_family_triggerable(self, api):
        """PRD §2.9: "Each missing resource yields its own specific error —
        `ERR_PROGRAM_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`,
        `ERR_PRIVATE_OWNER_NOT_FOUND`, `ERR_HYDRANT_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, `ERR_FLOW_TEST_NOT_FOUND`,
        `ERR_FLUSH_SEQUENCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_OUTAGE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_PART_NOT_FOUND`, `ERR_ISO_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/not_found_family_triggerable
        """
        resp_ft = api.get_flow_test(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp_ft, ApiErrorId.ERR_FLOW_TEST_NOT_FOUND, 404)

        resp_wo = api.get_work_order(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp_wo, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND, 404)

        resp_snap = api.get_iso_snapshot(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp_snap, ApiErrorId.ERR_ISO_SNAPSHOT_NOT_FOUND, 404)


class TestLogicalClock:
    def test_clock_default_and_set(self, api):
        """PRD §2.8: "Before any administrative call, the logical clock reads
        exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time."
        PRD §3.6: "The new outage starts in `ACTIVE` status with
        `notification_status` `PENDING`, `notified_at` set to the current
        logical clock, `ack_deadline` computed as `notified_at` plus 2 hours,
        and `escalated` false."

        Design: Corner/endpoints/clock_default_and_set
        """
        program, zone, hydrant = setup_program_zone_hydrant()

        outage = tag_hydrant_out(hydrant["id"], reason="OTHER")
        assert _parse(outage["notified_at"]) == _parse("2026-08-01T00:00:00Z"), (
            f"notified_at must equal the default logical clock, got {outage['notified_at']}"
        )
        assert _parse(outage["ack_deadline"]) == _parse("2026-08-01T00:00:00Z") + timedelta(hours=2), (
            f"ack_deadline must be notified_at + 2h, got {outage['ack_deadline']}"
        )
