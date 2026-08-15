"""Response envelope, pagination, staff roster defaults, auth pipeline order,
and immediate read-after-write consistency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_staff_member,
    create_staff_member,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["planning_chief_headers"]
LC = TEST_USERS["logistics_chief_headers"]
HA = TEST_USERS["hospital_administrator_headers"]


class TestStaffDefaults:
    def test_staff_member_create_applies_defaults_and_system_fields(self, api):
        """PRD §3.5: "`is_active`, defaulting to true, marks current employment;
        `callback_eligible`, defaulting to false, marks whether the member may
        receive surge call-backs; and `callback_seniority_score`, defaulting to 0,
        ranks the member for automated selection, higher scores being called earlier."
        PRD §2.4: "`id` (string): a server-minted unique identifier, formatted as a
        bare UUID with no type prefix."
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/entities/staff_member_create_applies_defaults_and_system_fields
        """
        resp = api.create_staff_member(
            {
                "full_name": "Pat Lee",
                "badge_number": "B-100",
                "department": "NURSING",
                "role_qualifications": ["PLANNING_CHIEF"],
            },
            HA,
        )
        staff = validate_success(resp, expected_status=201)
        assert_staff_member(staff)
        assert staff["is_active"] is True, "is_active defaults to true"
        assert staff["callback_eligible"] is False, "callback_eligible defaults to false"
        assert staff["callback_seniority_score"] == 0, "seniority score defaults to 0"
        assert is_valid_uuid(staff["id"]), "id must be a bare UUID"
        assert staff["created_at"] == "2026-08-01T00:00:00.000Z", (
            f"created_at must be the startup logical clock with three fractional "
            f"digits, got {staff['created_at']!r}"
        )
        assert isinstance(staff["version"], int), "version is a system-managed integer"

    def test_staff_create_duplicate_badge_rejected(self, api):
        """PRD §3.5: "Badge numbers are unique across the roster; registering a
        member with a `badge_number` already in use is rejected with
        `ERR_BADGE_NUMBER_EXISTS`."

        Design: Corner/entities/staff_create_duplicate_badge_rejected
        """
        first = api.create_staff_member(
            {"full_name": "First", "badge_number": "B-200", "department": "ICU",
             "role_qualifications": []},
            HA,
        )
        validate_success(first, expected_status=201)
        resp = api.create_staff_member(
            {"full_name": "Second", "badge_number": "B-200", "department": "ICU",
             "role_qualifications": []},
            HA,
        )
        validate_error(resp, ApiErrorId.ERR_BADGE_NUMBER_EXISTS)


class TestListingAndPagination:
    def test_staff_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; when omitted it defaults to 10, and it must lie between 1 and
        100 inclusive. The `offset` parameter sets how many items to skip and
        defaults to 0."
        PRD §2.3: "Paginated list responses carry four pagination fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/endpoints/staff_list_pagination_envelope
        """
        for i in range(12):
            create_staff_member(full_name=f"P{i + 1}", badge_number=f"B-7{i + 1:02d}",
                                department="ICU")

        page1_resp = api.list_staff_members(HA)
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 10, "default limit is 10"
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert isinstance(meta1["api_request_id"], str) and meta1["api_request_id"]
        assert is_iso8601_timestamp(meta1["api_request_timestamp"])

        page2, meta2 = validate_paginated(api.list_staff_members(HA, params={"offset": 10}))
        assert len(page2) == 2
        assert meta2["offset"] == 10
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestErrorEnvelope:
    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_not_found
        """
        resp = api.get_supply_item(NON_EXISTENT_UUID, LC)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        assert error["message"].strip(), "error envelope carries a human-readable message"

    def test_get_unknown_incident_id_returns_not_found(self, api):
        """PRD §2.9: "Where a path contains resource identifiers, existence is
        validated left to right, and the first identifier that fails to resolve
        rejects the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_unknown_incident_id_returns_not_found
        """
        resp = api.get_incident(NON_EXISTENT_UUID, IC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAuthentication:
    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role string
        outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.get_incident(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unauthenticated_action_beats_not_found_priority(self, api):
        """PRD §2.11: "When several validations apply to one request, the server
        evaluates them in a fixed order, and the first failure determines the
        response."
        PRD §2.11: "1. Header authentication (§2.1): failures yield
        `ERR_UNAUTHENTICATED`."
        PRD §2.11: "3. Path identifier resolution, validated left to right:
        `ERR_NOT_FOUND`."

        Design: Corner/validations/unauthenticated_action_beats_not_found_priority
        """
        resp = api.demobilize_incident(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_existence_beats_state_priority(self, api):
        """PRD §2.11: "3. Path identifier resolution, validated left to right:
        `ERR_NOT_FOUND`."
        PRD §2.11: "8. State-transition legality on the target resource — the
        generic guard that rejects any action whose target's current state does
        not permit it: `ERR_INVALID_STATE`."

        Design: Corner/validations/existence_beats_state_priority
        """
        resp = api.discharge_patient(NON_EXISTENT_UUID, PC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestImmediateConsistency:
    def test_immediate_read_after_write_reflects_mutation(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.5: "The administrator may later patch `department`,
        `role_qualifications`, `is_active`, `callback_eligible`, or
        `callback_seniority_score`, each patch advancing the member's `version`."
        PRD §2.4: "`version` (integer): a system-managed integer that increments
        by one on every mutation of the resource, and which backs the optimistic
        concurrency control described in §2.8."

        Design: Corner/consistency_model/immediate_read_after_write_reflects_mutation
        """
        staff = create_staff_member(full_name="M Fourteen", department="PHARMACY")
        assert staff["is_active"] is True

        patched = validate_success(
            api.patch_staff_member(staff["id"], {"is_active": False}, HA)
        )
        assert patched["is_active"] is False, "PATCH response carries the updated object"
        assert patched["version"] == staff["version"] + 1, "version advances by one"

        reread = validate_success(api.get_staff_member(staff["id"], HA))
        assert reread["is_active"] is False, "the very next read observes the new value"
