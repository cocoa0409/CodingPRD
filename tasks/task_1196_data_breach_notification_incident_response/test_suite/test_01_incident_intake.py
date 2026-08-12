"""Incident intake and basic CRUD (corner design — entities section)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_incident,
    create_incident,
    create_incident_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
FL = TEST_USERS["forensic_lead_headers"]


class TestIncidentCreation:
    def test_incident_creation_returns_server_fields(self, api):
        """PRD §3.1: "The new incident is initialized with `investigation_status`
        set to `INTAKE`, `notification_status` set to `NOT_REQUIRED`, `severity`
        set to `UNCLASSIFIED`, `remediation_status` set to `NOT_STARTED`, all
        derived counters set to zero, and `version` set to 1."

        Design: Corner/entities/incident_creation_returns_server_fields
        """
        resp = api.create_incident(create_incident_payload(title="X"), IC)
        data = validate_success(resp, expected_status=201)
        assert_incident(data)
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert data["investigation_status"] == "INTAKE"
        assert data["notification_status"] == "NOT_REQUIRED"
        assert data["severity"] == "UNCLASSIFIED"
        assert data["remediation_status"] == "NOT_STARTED"
        assert data["total_affected_subjects"] == 0
        # Logical-clock default (PRD §3.13): created_at lands on 2026-05-01.
        assert data["created_at"].startswith("2026-05-01"), (
            f"expected logical-clock default date, got {data['created_at']}"
        )

    def test_incident_creation_ignores_client_supplied_computed_total(self, api):
        """PRD §3.1: "all derived counters set to zero". A client-supplied
        `total_affected_subjects` is never authoritative — the server computes
        the counter and returns zero at intake.

        Design: Corner/entities/computed_field_input_ignored
        """
        resp = api.create_incident(
            create_incident_payload(title="X", total_affected_subjects=999),
            IC,
        )
        data = validate_success(resp, expected_status=201)
        assert data["total_affected_subjects"] == 0

    def test_incident_missing_required_title_returns_invalid_request(self, api):
        """PRD §3.1 lists `title` among the inputs supplied at creation; PRD §5
        catalogues `ERR_INVALID_REQUEST` (HTTP 422) for a schema validation
        failure on the request payload.

        Design: Corner/entities/incident_missing_required_field_returns_invalid_request
        """
        payload = create_incident_payload()
        payload.pop("title")
        resp = api.create_incident(payload, IC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)

    def test_incident_get_not_found(self, api):
        """PRD §2.5: "If any path-template id fails to resolve to an existing
        row in scope — `incidentId`, `scopeId`, `itemId`, `subjectId`,
        `noticeId`, `batchId`, `offerId`, `planId`, `subId`, `actionId`,
        `jurisdictionEvaluationId`, or `evaluationId` — the request is
        rejected with `ERR_NOT_FOUND` (HTTP 404) before any later check runs."

        Design: Corner/entities/incident_get_not_found
        """
        resp = api.get_incident(NON_EXISTENT_UUID, IC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_incident_list_pagination_defaults(self, api):
        """PRD §2.3: "The default value of `limit` is 10, the minimum accepted
        value is 1, and the maximum accepted value is 100. The default value of
        `offset` is 0. List responses order results by `created_at` ascending.
        The `meta` object on every list response carries the four pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/incident_list_pagination_defaults
        """
        api.create_incident(create_incident_payload(title="A"), IC)
        api.create_incident(
            create_incident_payload(title="B", source_channel="THIRD_PARTY_REPORT"),
            IC,
        )
        resp = api.list_incidents(IC)
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0

    def test_custody_log_immutable_entity_shape(self, api):
        """PRD §3.2: "Custody rows are append-only: they carry `id` and
        `created_at` but no `updated_at` and no `version`."

        Design: Corner/entities/custody_log_immutable_entity_shape
        """
        inc = create_incident()
        ev_resp = api.create_evidence_item(
            inc["id"],
            {
                "label": "e",
                "evidence_type": "LOG",
                "collected_at": "2026-04-29T00:00:00Z",
                "collected_by_user_id": "fl-1",
                "preservation_hash": (
                    "0123456789abcdef0123456789abcdef"
                    "0123456789abcdef0123456789abcdef"
                ),
            },
            FL,
        )
        ev = validate_success(ev_resp, expected_status=201)
        log_resp = api.create_custody_log(
            inc["id"],
            {
                "evidence_item_id": ev["id"],
                "custodian_user_id": "u1",
                "start_at": "2026-05-01T10:00:00Z",
                "end_at": "2026-05-01T12:00:00Z",
                "purpose": "intake",
            },
            FL,
        )
        log = validate_success(log_resp, expected_status=201)
        assert "version" not in log
        assert "updated_at" not in log
        assert is_valid_uuid(log["id"])
