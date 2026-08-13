"""Mariner/vessel registry creation, schema validation, and pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_mariner,
    create_course,
    create_credential_payload,
    create_mariner,
    create_mariner_payload,
    create_vessel,
    create_vessel_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMarinerCreation:

    def test_mariner_creation_defaults_and_computed_fields(self, fleet_admin_headers):
        """PRD section 3.1: "A newly registered mariner starts in `APPLICANT`
        status with `training_privileges` `ENABLED`, a `no_show_strike_count`
        of zero, and a computed `readiness_posture` of `BLOCKED` carrying the
        reason `STATUS_NOT_ACTIVE` — applicants are not crewable until
        activated."
        PRD section 3.1: "The optional `annual_training_cap_cents` seeds the
        mariner's yearly training budgets and defaults to 500,000 cents (five
        thousand dollars) when omitted."

        Design: Corner/entities/mariner_creation_defaults_and_computed_fields
        """
        resp = api_client.create_mariner(
            create_mariner_payload(
                full_name="Corner Create", home_port_code="NOLA",
                hire_channel="DIRECT", rank_track="ENGINE", rank_grade=3,
                primary_endorsement_code="ENG_QMED"),
            fleet_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_mariner(data)
        assert data["status"] == "APPLICANT"
        assert data["readiness_posture"] == "BLOCKED"
        assert data["training_privileges"] == "ENABLED"
        assert data["no_show_strike_count"] == 0
        assert data["annual_training_cap_cents"] == 500000, \
            f"default cap must apply when omitted, got {data['annual_training_cap_cents']}"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])

        got = validate_success(
            api_client.get_mariner(data["id"], fleet_admin_headers))
        assert got["status"] == "APPLICANT"
        assert "STATUS_NOT_ACTIVE" in got["readiness_reasons"], \
            f"BLOCKED applicant must carry STATUS_NOT_ACTIVE, got {got['readiness_reasons']}"

    def test_mariner_create_system_fields_input_ignored(self, fleet_admin_headers):
        """PRD section 2.4: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD section 3.1: "A newly registered mariner starts in `APPLICANT`
        status with `training_privileges` `ENABLED`, a `no_show_strike_count`
        of zero, and a computed `readiness_posture` of `BLOCKED` carrying the
        reason `STATUS_NOT_ACTIVE`"

        Design: Corner/entities/mariner_create_system_fields_input_ignored
        """
        supplied_id = "00000000-0000-0000-0000-0000000000aa"
        resp = api_client.create_mariner(
            create_mariner_payload(
                full_name="Ignored Fields", id=supplied_id, version=99,
                readiness_posture="CLEAR"),
            fleet_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["id"] != supplied_id, "server must mint its own id"
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1, \
            f"client-supplied version must be ignored, got {data['version']}"
        assert data["readiness_posture"] == "BLOCKED", \
            f"client-supplied posture must be ignored, got {data['readiness_posture']}"
        assert data["status"] == "APPLICANT"

    def test_mariner_missing_required_field_rejected(self, fleet_admin_headers):
        """PRD section 2.5: "Required fields must be present, types must be
        valid, enum membership must be valid, date ranges must be ordered (end
        on or after start, or strictly after, as each field specifies),
        `rank_grade` must lie within 1 through 9 inclusive, and the uniqueness
        constraints on `mariner_reference_number`, `imo_number`,
        `course_code`, and `local_number` must hold. Any violation is
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/mariner_missing_required_field_rejected
        """
        payload = create_mariner_payload(full_name="No Track")
        del payload["rank_track"]
        resp = api_client.create_mariner(payload, fleet_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_mariner_duplicate_reference_number_rejected(self, fleet_admin_headers):
        """PRD section 3.1: "A `FleetAdmin` registers a mariner with
        `full_name`, a `mariner_reference_number` unique across all mariners"
        PRD section 2.5: "the uniqueness constraints on
        `mariner_reference_number`, `imo_number`, `course_code`, and
        `local_number` must hold. Any violation is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/mariner_duplicate_reference_number_rejected
        """
        first = create_mariner(mariner_reference_number="MRN-DUP-1")
        resp = api_client.create_mariner(
            create_mariner_payload(
                full_name="Dup Two",
                mariner_reference_number="MRN-DUP-1",
                home_port_code="SEA", hire_channel="UNION_HALL",
                rank_track="ENGINE", rank_grade=2,
                primary_endorsement_code="ENG_QMED"),
            fleet_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(
            api_client.list_mariners(fleet_admin_headers))
        assert meta["total_count"] == 1, \
            f"only the first mariner may persist, got total_count={meta['total_count']}"
        assert data[0]["id"] == first["id"]

    def test_mariner_get_not_found_returns_404(self, fleet_admin_headers):
        """PRD section 2.5: "Identifiers in the URL are resolved strictly left
        to right; the first identifier that does not correspond to an existing
        resource yields that resource's dedicated 404"

        Design: Corner/entities/mariner_get_not_found_returns_404
        """
        resp = api_client.get_mariner(NON_EXISTENT_UUID, fleet_admin_headers)
        validate_error(resp, ApiErrorId.ERR_MARINER_NOT_FOUND)


class TestVesselAndCredentialValidation:

    def test_vessel_invalid_enum_rejected(self, fleet_admin_headers):
        """PRD section 3.6: "a `vessel_class` of `TANKER`, `CONTAINER`,
        `BULK`, `PASSENGER`, or `OSV`"
        PRD section 2.5: "Required fields must be present, types must be
        valid, enum membership must be valid, date ranges must be ordered (end
        on or after start, or strictly after, as each field specifies)"

        Design: Corner/entities/vessel_invalid_enum_rejected
        """
        resp = api_client.create_vessel(
            create_vessel_payload(vessel_name="SS Hover",
                                  vessel_class="HOVERCRAFT"),
            fleet_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_credential_create_under_missing_mariner_not_found(self, officer_headers):
        """PRD section 2.5: "for example, a credential action under a
        non-existent mariner fails with `ERR_MARINER_NOT_FOUND` before the
        credential id is ever examined"

        Design: Corner/entities/credential_create_under_missing_mariner_not_found
        """
        resp = api_client.create_credential(
            NON_EXISTENT_UUID, create_credential_payload(), officer_headers)
        validate_error(resp, ApiErrorId.ERR_MARINER_NOT_FOUND)


class TestCourseListingPagination:

    def test_course_listing_pagination_envelope(self, fleet_admin_headers):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10, accepts a minimum of 1, and accepts a
        maximum of 100. The `offset` parameter skips a number of items from
        the front of the result set and defaults to 0."
        PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD section 2.3: "Unless a more specific rule is stated, every list
        endpoint returns its resources sorted by `created_at` in ascending
        order."

        Design: Corner/entities/course_listing_pagination_envelope
        """
        course_a = create_course(course_code="PAGE-A", title="Course A",
                                 cost_cents=50000)
        course_b = create_course(course_code="PAGE-B", title="Course B",
                                 cost_cents=60000,
                                 start_date="2026-09-10T00:00:00Z",
                                 end_date="2026-09-12T00:00:00Z")

        resp1 = api_client.list_courses(
            fleet_admin_headers, params={"limit": 1, "offset": 0})
        page1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array"
        assert "api_request_id" in resp1.json()["meta"]
        assert len(page1) == 1 and meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == course_a["id"], \
            "created_at ascending order puts the first-created course first"

        page2, meta2 = validate_paginated(
            api_client.list_courses(
                fleet_admin_headers, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1 and meta2["has_more"] is False
        assert page2[0]["id"] == course_b["id"]
