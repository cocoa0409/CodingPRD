"""Append-only ledger lines, envelope, pagination, and 404 behavior (PRD §2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_physician_payload,
    setup_case_with_lines,
    setup_ortho_tdabc,
    validate_error,
    validate_paginated,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]


class TestLedgerLineShape:
    def test_activity_cost_line_immutable_no_update_endpoint(self, api):
        """PRD §2.4: "**Activity cost lines** and **supply lines** are append-only
        ledger lines: they carry only `id` and `created_at`. Both `updated_at` and
        `version` are absent from them, because a ledger line, once written, is
        never modified — re-pricing regenerates the line's computed content
        rather than versioning it."

        Design: Corner/entities/activity_cost_line_immutable_no_update_endpoint
        """
        scenario = setup_ortho_tdabc()
        case = setup_case_with_lines(scenario, [100])

        data, _meta = validate_paginated(api.list_activity_lines(case["id"], CA))
        assert len(data) == 1, f"Expected exactly one activity line, got {len(data)}"
        line = data[0]
        assert line["id"], "activity line must carry id"
        assert line.get("created_at"), "activity line must carry created_at"
        assert "updated_at" not in line, "append-only line must not carry updated_at"
        assert "version" not in line, "append-only line must not carry version"


class TestNotFoundAndEnvelope:
    def test_case_not_found_returns_404(self, api):
        """PRD §2.10: "the first identifier that does not resolve to an existing
        resource yields `ERR_NOT_FOUND`."

        Design: Corner/entities/case_not_found_returns_404
        """
        resp = api.get_case(NON_EXISTENT_UUID, FC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_case_list_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/case_list_pagination_envelope
        """
        resp = api.list_cases(FC)
        body = resp.json()
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert body.get("response_type") == "array"
        assert body.get("meta", {}).get("api_request_id"), "meta.api_request_id required"
        data, meta = validate_paginated(resp)
        assert data == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_pagination_limit_max_enforced(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100."

        Design: Corner/cross_cutting_layers/pagination_limit_max_enforced
        """
        first = api.create_physician(create_physician_payload(npi="1000000001"), FC)
        assert first.status_code == 201, f"Setup failed: {first.text}"
        second = api.create_physician(
            create_physician_payload(npi="1000000002", full_name="Dr. Two",
                                     specialty="Cardiology"), FC
        )
        assert second.status_code == 201, f"Setup failed: {second.text}"

        data, meta = validate_paginated(
            api.list_physicians(FC, params={"limit": 1, "offset": 0})
        )
        assert len(data) == 1, f"limit=1 must return exactly one record, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
