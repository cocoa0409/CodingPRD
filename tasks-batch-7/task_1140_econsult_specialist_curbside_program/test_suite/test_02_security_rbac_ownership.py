"""Security: auth context, role gates, ownership, and segregation of duties."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, create_consult, create_provider,
    create_specialist, get_consult,
    make_provider_headers, make_reviewer_headers, make_specialist_headers,
    set_clock, setup_answered_consult, setup_assigned_consult, setup_panel_scenario,
    validate_error,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


class TestSecurityRbacOwnership:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the system
        does not declare, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        set_clock("2026-06-01T00:00:00Z")
        res = api.list_consult_requests(headers={})
        error_data = validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )
        assert error_data["error_id"] == "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
        assert res.json()["response_type"] == "error"

    def test_provider_role_cannot_create_specialty_track(self, api):
        """PRD §2.1: "Each operation restricts which roles may invoke it; a caller
        whose role is not listed for the endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/validations/provider_role_cannot_create_specialty_track
        """
        set_clock("2026-06-01T00:00:00Z")
        provider = create_provider(npi="1000004001")
        res = api.create_specialty_track({
            "specialty_code": "NEUROLOGY",
            "response_time_target_hours": 48,
            "urgent_target_hours": 12,
            "base_response_fee_cents": 10000,
            "conversion_response_fee_cents": 8000,
            "clarification_fee_cents": 2500,
            "late_penalty_cents": 3000,
            "monthly_billing_cap_cents": 1000000,
        }, make_provider_headers(provider["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_unknown_consult_id_returns_not_found(self, api):
        """PRD §2.8: "Existence of every path- and body-referenced resource id comes
        next, validated left to right, with the first missing resource producing
        `ERR_NOT_FOUND`."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/validations/unknown_consult_id_returns_not_found
        """
        set_clock("2026-06-01T00:00:00Z")
        res = api.get_consult_request(NON_EXISTENT_UUID, COORD)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        body = res.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]

    def test_specialist_role_cannot_open_quality_review(self, api):
        """PRD §2.1: "Each operation restricts which roles may invoke it; a caller
        whose role is not listed for the endpoint is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4 lists POST /econsult/quality-reviews under QualityReviewer only.

        Design: Corner/rbac/specialist_role_cannot_open_quality_review
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-R1", provider_npi="1000006001",
            specialist_npi="2000006001",
        )
        res = api.create_quality_review(
            {"response_id": scenario["response"]["id"]},
            make_specialist_headers(scenario["specialist"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_billing_clerk_cannot_submit_response(self, api):
        """PRD §2.1: "Clinical and fiscal duties are deliberately segregated: billing
        operations are unavailable to every clinical role, and quality review is
        unavailable to the specialist who wrote the response."
        PRD §4 lists POST /econsult/consult-requests/{id}/responses under Specialist
        only, and §2.1 rejects unlisted roles with ERR_INSUFFICIENT_PERMISSIONS.

        Design: Corner/rbac/billing_clerk_cannot_submit_response
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-R2", provider_npi="1000006002",
            specialist_npi="2000006002",
        )
        res = api.create_response(
            scenario["consult"]["id"],
            {"disposition": "MANAGE_WITH_PLAN",
             "recommendation_text": "Drop aspirin after 4 weeks, continue apixaban plus clopidogrel short course."},
            BILLING,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    def test_provider_cannot_patch_others_consult(self, api):
        """PRD §3.3: "Only the owning provider may amend; anyone else is rejected with
        `ERR_NOT_CONSULT_OWNER`."

        Design: Corner/rbac/provider_cannot_patch_others_consult
        """
        scenario = setup_panel_scenario(provider_npi="1000006003",
                                        specialist_npi="2000006003")
        provider_b = create_provider(npi="1000006004", full_name="Dr. Bob Primary")
        consult = create_consult(
            scenario["track"]["id"], scenario["provider"]["id"], patient_ref="PAT-R3",
            question_text="Valvular heart disease surveillance interval question for moderate mitral regurgitation.",
            icd10_primary="I34",
        )
        res = api.patch_consult_request(
            consult["id"],
            {"icd10_primary": "I35", "expected_consult_version": consult["version"]},
            make_provider_headers(provider_b["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_CONSULT_OWNER, expected_status=403)
        # The failed amendment leaves the consult untouched.
        after = get_consult(consult["id"])
        assert after["icd10_primary"] == "I34"

    def test_reviewer_cannot_review_own_response(self, api):
        """PRD §3.7: "the reviewer — whose `reviewer_specialist_id` is set from the
        caller's `X-User-ID` — must not be the specialist who wrote the response; that
        segregation-of-duties violation is rejected with `ERR_REVIEWER_IS_RESPONDER`
        (HTTP 403)."

        Design: Corner/validations/reviewer_cannot_review_own_response
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-V4", provider_npi="1000004005",
            specialist_npi="2000004006",
        )
        # The responding specialist doubles as QualityReviewer (same X-User-ID).
        res = api.create_quality_review(
            {"response_id": scenario["response"]["id"]},
            make_reviewer_headers(scenario["specialist"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REVIEWER_IS_RESPONDER, expected_status=403)

    def test_non_assigned_specialist_cannot_respond(self, api):
        """PRD §3.5: "The caller must be the assigned specialist
        (`ERR_NOT_ASSIGNED_SPECIALIST`)"

        Design: Corner/validations/non_assigned_specialist_cannot_respond
        """
        scenario = setup_panel_scenario(provider_npi="1000004007",
                                        specialist_npi="2000004007")
        # A second registered specialist with no panel seat on this track.
        other = create_specialist(npi="2000004008", full_name="Dr. Beta Specialist")
        consult = create_consult(
            scenario["track"]["id"], scenario["provider"]["id"], patient_ref="PAT-V6",
            question_text="Pulmonary hypertension on sildenafil; asks about adding ambrisentan for persistent symptoms.",
            icd10_primary="I27",
        )
        assert consult["assigned_membership_id"] == scenario["membership"]["id"]
        res = api.create_response(
            consult["id"],
            {"disposition": "MANAGE_WITH_PLAN",
             "recommendation_text": "Combination therapy reasonable; check LFTs monthly after adding ambrisentan."},
            make_specialist_headers(other["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOT_ASSIGNED_SPECIALIST, expected_status=403)
