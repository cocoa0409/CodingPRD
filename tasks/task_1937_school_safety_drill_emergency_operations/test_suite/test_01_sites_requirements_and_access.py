"""Campus onboarding, statutory requirement configuration, optimistic
concurrency on requirement updates, response envelopes, and access control."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_drill_counter_sum,
    assert_school_site,
    create_compliance_report,
    create_requirement_payload,
    create_site,
    create_site_payload,
    get_compliance_report,
    get_drill_requirement,
    get_type_attainment,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_site_with_requirement,
    validate_error,
    validate_success,
)


class TestSiteCreation:
    def test_site_creation_defaults(self, api, coordinator_headers):
        """PRD: "Upon creation the site's `compliance_posture` is set to `ON_TRACK` and all four drill counters — `drills_scheduled_count`, `drills_completed_count`, `drills_missed_count`, and `drills_cancelled_count` — initialize to zero."
        PRD: "At server startup, before any clock-advance call, the logical clock reads 2026-08-01T00:00:00Z."

        Design: Corner/entities/site_creation_defaults
        """
        resp = api.create_site(
            create_site_payload(name="Ridgeview Elementary", enrollment_count=500),
            coordinator_headers,
        )
        site = validate_success(resp, 201)
        assert_school_site(site)
        assert site["compliance_posture"] == "ON_TRACK", (
            f"New site must start ON_TRACK, got {site['compliance_posture']}")
        assert site["drills_scheduled_count"] == 0
        assert site["drills_completed_count"] == 0
        assert site["drills_missed_count"] == 0
        assert site["drills_cancelled_count"] == 0
        assert_drill_counter_sum(site, 0)
        assert is_valid_uuid(site["id"])
        assert site["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at must reflect the startup logical clock, got {site['created_at']}")

    def test_site_get_not_found_returns_404(self, api, coordinator_headers):
        """PRD: "The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource, before any subsequent validation occurs."

        Design: Corner/entities/site_get_not_found_returns_404
        """
        resp = api.get_site(NON_EXISTENT_UUID, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_site_with_extra_field_returns_invalid_request(
            self, api, coordinator_headers):
        """PRD: "(4) input validation — required fields present, types correct, enum members valid, date and datetime formats valid, unknown top-level fields rejected, and conditional requirements enforced (such as `return_reason` required when `decision` is `RETURN`), else `ERR_VALIDATION`"

        Design: Corner/entities/create_site_with_extra_field_returns_invalid_request
        """
        payload = create_site_payload(name="Ridgeview Elementary")
        payload["compliance_posture"] = "NON_COMPLIANT"
        resp = api.create_site(payload, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_create_site_missing_required_field_returns_invalid_request(
            self, api, coordinator_headers):
        """PRD: "(4) input validation — required fields present, types correct, enum members valid, date and datetime formats valid, unknown top-level fields rejected, and conditional requirements enforced (such as `return_reason` required when `decision` is `RETURN`), else `ERR_VALIDATION`"
        PRD: "A `DistrictSafetyCoordinator` begins by creating a **SchoolSite**, providing a `name` for the campus, an `enrollment_count` (a non-negative integer, purely informational and feeding no gate), and the academic year boundaries `academic_year_start` and `academic_year_end`."

        Design: Corner/entities/create_site_missing_required_field_returns_invalid_request
        """
        payload = create_site_payload(name="Ridgeview Elementary")
        del payload["name"]
        resp = api.create_site(payload, coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestRequirementConfiguration:
    def test_requirement_body_fk_not_found_returns_404(
            self, api, coordinator_headers):
        """PRD: "Body-referenced foreign keys — such as `site_id` on a creation payload — must also reference an existing resource; a nonexistent reference is rejected with `ERR_NOT_FOUND`."

        Design: Corner/entities/drill_requirement_body_fk_not_found_returns_404
        """
        resp = api.create_drill_requirement(
            create_requirement_payload(site_id=NON_EXISTENT_UUID),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_requirement_exists_rejected(self, api, coordinator_headers):
        """PRD: "Only one requirement may exist per campus and drill type combination; a duplicate creation is rejected with `ERR_REQUIREMENT_EXISTS`."

        Design: Corner/validations/requirement_exists_rejected
        """
        ctx = setup_site_with_requirement(site_name="Cedar Grove High",
                                          enrollment_count=1200)
        resp = api.create_drill_requirement(
            create_requirement_payload(site_id=ctx["site"]["id"],
                                       drill_type="FIRE", required_per_year=4,
                                       min_spacing_days=10,
                                       target_evac_seconds=240),
            coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REQUIREMENT_EXISTS)

    def test_occ_stale_version_returns_412_and_version_increments(
            self, api, coordinator_headers):
        """PRD: "Updating a requirement additionally requires OCC — the request must carry `expected_requirement_version` matching the requirement's current `version`, else the update is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful update increments the requirement's `version` by 1 and refreshes its `updated_at`."

        Design: Corner/cross_cutting_layers/occ_stale_version_returns_412_and_version_increments
        """
        ctx = setup_site_with_requirement()
        requirement = ctx["requirement"]
        observed_version = requirement["version"]

        first = api.update_drill_requirement(
            requirement["id"],
            {"target_evac_seconds": 240,
             "expected_requirement_version": observed_version},
            coordinator_headers,
        )
        updated = validate_success(first, 200)
        assert updated["version"] == observed_version + 1, (
            f"A successful update increments version by 1: "
            f"{observed_version} -> {updated['version']}")
        assert updated["target_evac_seconds"] == 240

        replay = api.update_drill_requirement(
            requirement["id"],
            {"target_evac_seconds": 250,
             "expected_requirement_version": observed_version},
            coordinator_headers,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

        current = get_drill_requirement(ctx["site"]["id"], requirement["id"])
        assert current["target_evac_seconds"] == 240, (
            "The rejected write must not change target_evac_seconds")
        assert current["version"] == observed_version + 1

    def test_requirement_update_stales_draft_report(self, api, coordinator_headers):
        """PRD: "Creating or updating a requirement has system-wide ripple effects: the site's `compliance_posture` is recomputed, and every ComplianceReport at that site still in `DRAFT` status transitions to `STALE`, since the statutory baseline has shifted."
        PRD: "Regeneration is available from either `STALE` or `REJECTED`: the coordinator regenerates the report, which recomputes the full snapshot (statutory attainment and overall score), stamps `snapshot_generated_at` anew, and moves the report back to `DRAFT`."

        Design: Corner/cross_cutting_layers/requirement_update_stales_draft_report
        """
        ctx = setup_site_with_requirement(site_name="Harborview Middle",
                                          enrollment_count=700)
        site_id = ctx["site"]["id"]
        requirement = ctx["requirement"]
        report = create_compliance_report(site_id)
        assert report["status"] == "DRAFT"

        update = api.update_drill_requirement(
            requirement["id"],
            {"required_per_year": 3,
             "expected_requirement_version": requirement["version"]},
            coordinator_headers,
        )
        validate_success(update, 200)

        stale = get_compliance_report(site_id, report["id"])
        assert stale["status"] == "STALE", (
            f"Updating the requirement must stale the DRAFT report, got {stale['status']}")

        regenerated = api.regenerate_compliance_report(report["id"],
                                                       coordinator_headers)
        regenerated_data = validate_success(regenerated, 200)
        assert regenerated_data["status"] == "DRAFT"
        attainment = get_type_attainment(regenerated_data, "FIRE")
        assert attainment["required_count"] == 3, (
            "Regeneration recomputes against the updated required_per_year")


class TestAccessControlAndEnvelopes:
    def test_officer_cannot_create_site_returns_forbidden(
            self, api, officer_headers):
        """PRD: "A request whose role is not listed as authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: POST /sites is authorized for DistrictSafetyCoordinator only.

        Design: Corner/rbac/officer_cannot_create_site_returns_forbidden
        """
        resp = api.create_site(create_site_payload(), officer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_missing_x_user_role_header_returns_unauthenticated(self, api):
        """PRD: "A request missing a valid `X-User-Role` header, or carrying a role value not among the five declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
        """
        headers = {"X-User-ID": "test-user-no-role",
                   "Content-Type": "application/json"}
        resp = api.create_site(create_site_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_success_envelope_shape(self, api, coordinator_headers,
                                    officer_headers):
        """PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/success_envelope_shape
        """
        site = create_site()
        resp = api.get_site(site["id"], officer_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == site["id"]

    def test_error_envelope_shape(self, api, coordinator_headers):
        """PRD: "All error API responses (4xx status codes) follow this standard envelope format" with "response_type": "error" and a data object carrying "error_id" and "message"; "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_site(NON_EXISTENT_UUID, coordinator_headers)
        body = resp.json()
        assert body.get("response_type") == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str)
        assert len(body["data"]["message"].strip()) > 0
