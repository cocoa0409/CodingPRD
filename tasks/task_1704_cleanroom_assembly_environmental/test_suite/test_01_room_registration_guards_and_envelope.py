"""Room registration, request guards (headers / RBAC / existence), and the
response envelope."""
from test_helpers import (
    ENV_TECH,
    MAT_HANDLER,
    NON_EXISTENT_UUID,
    PROD_OP,
    QA,
    ApiErrorId,
    add_sampling_point,
    assert_cleanroom,
    create_room,
    create_room_payload,
    open_investigation,
    record_excursion_sample,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRoomRegistration:
    def test_create_room_applies_system_defaults(self, api):
        """PRD §3.1: "A new room is born with `certification_status`
        `UNCERTIFIED`, `environment_posture` `IN_CONTROL`, lifecycle `status`
        `ACTIVE`, a null `certified_at`, and `version` 1."

        Design: Corner/entities/create_room_applies_system_defaults
        """
        resp = api.create_room(create_room_payload(room_code="CR-E1"), QA)
        room = validate_success(resp, 201)
        assert_cleanroom(room)
        assert room["certification_status"] == "UNCERTIFIED"
        assert room["environment_posture"] == "IN_CONTROL"
        assert room["status"] == "ACTIVE"
        assert room["version"] == 1
        assert room["certified_at"] is None

    def test_create_room_rejects_action_limit_not_above_alert(self, api):
        """PRD §2.6: "For each metric the action limit must be strictly greater
        than the corresponding alert limit; a room registration whose limits
        violate that ordering is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_room_rejects_action_limit_not_above_alert
        """
        resp = api.create_room(
            create_room_payload(room_code="CR-E2", particle_alert_limit=300000,
                                particle_action_limit=300000),
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_room_rejects_invalid_iso_class_enum(self, api):
        """PRD §3.1: "the target `iso_class` — one of `ISO_5`, `ISO_6`, `ISO_7`,
        or `ISO_8`".
        PRD §2.10: "Structural request validity — required fields present, enum
        values valid, each action limit strictly greater than its alert limit,
        an audit's `window_end` strictly after its `window_start`,
        `dwell_minutes` not negative, `result_value` not negative, and
        `root_cause` at least 20 characters long (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/create_room_rejects_invalid_iso_class_enum
        """
        resp = api.create_room(
            create_room_payload(room_code="CR-E3", iso_class="ISO_4",
                                particle_alert_limit=1, particle_action_limit=2,
                                viable_alert_limit=1, viable_action_limit=2),
            QA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_room_not_found_returns_404(self, api):
        """PRD §2.10: "Existence of every identifier in the path and every
        foreign-key identifier in the body, validated left to right
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_room_not_found_returns_404
        """
        resp = api.get_room(NON_EXISTENT_UUID, QA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRequestGuards:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring that user's
        operational capacity. A request in which either header is missing or
        malformed is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_rejected
        """
        resp = api.create_room(create_room_payload(room_code="CR-V1"), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_environment_tech_cannot_create_room(self, api):
        """PRD §2.1: "`EnvironmentTech` — the environmental monitoring
        technician: records environmental samples and records cleaning cycles."
        PRD §2.1: "A request whose declared role is not permitted to invoke the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/environment_tech_cannot_create_room
        """
        resp = api.create_room(create_room_payload(room_code="CR-RB1"), ENV_TECH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_production_operator_cannot_approve_investigation(self, api):
        """PRD §2.1: "`ProductionOperator` — the assembly operator: logs room
        entry and exit, opens batches, adds traveler steps, and starts and
        completes those steps."
        PRD §2.1: "`QualityAssurance` — the QA unit: registers rooms and
        sampling points, records and voids certifications, opens and
        dispositions excursion investigations, verifies and rejects cleaning
        cycles, releases, rejects, and resumes batches, voids traveler steps,
        hosts customer audits, grants and revokes gowning qualifications,
        suspends and reinstates personnel, decommissions rooms, and drives the
        logical clock."
        PRD §2.1: "A request whose declared role is not permitted to invoke the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/production_operator_cannot_approve_investigation
        """
        room = create_room(room_code="CR-RB2", iso_class="ISO_5",
                           particle_alert_limit=100000,
                           particle_action_limit=352000,
                           viable_alert_limit=10, viable_action_limit=20)
        point = add_sampling_point(room["id"], point_code="SP-RB2", metric="VIABLE")
        _sample, excursion_id = record_excursion_sample(
            point["id"], 15, tech_user_id="tech-rb2")
        investigation = open_investigation(
            excursion_id,
            root_cause="Investigation narrative for RB2 denial",
            investigator_id="qa-rb2")

        resp = api.approve_investigation(investigation["id"], PROD_OP)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_material_handler_cannot_record_sample(self, api):
        """PRD §2.1: "`MaterialHandler` — the warehouse/material handler: stages
        material transfers into the airlock and introduces or rejects them."
        PRD §2.1: "A request whose declared role is not permitted to invoke the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/roles/material_handler_cannot_record_sample
        """
        room = create_room(room_code="CR-RB3")
        point = add_sampling_point(room["id"], point_code="SP-RB3", metric="PARTICLE")

        resp = api.create_sample(
            {"sampling_point_id": point["id"], "result_value": 5,
             "sampled_at": "2026-08-01T09:00:00Z"},
            MAT_HANDLER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestResponseEnvelope:
    def test_list_rooms_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10, and it accepts a minimum of 1 and a
        maximum of 100. The `offset` parameter states how many items to skip
        and defaults to 0."
        PRD §2.3: "Paginated list responses carry the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_rooms_pagination_envelope
        """
        create_room(room_code="CR-P1")
        create_room(room_code="CR-P2", iso_class="ISO_8",
                    particle_alert_limit=3500000, particle_action_limit=3520000,
                    viable_alert_limit=100, viable_action_limit=200)

        resp = api.list_rooms(QA, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"limit=1 must return one room, got {len(data)}"
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "array"

    def test_response_envelope_error_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format".
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        resp = api.get_room(NON_EXISTENT_UUID, QA)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(error["message"], str) and error["message"].strip()
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
