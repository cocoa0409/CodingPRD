"""Access control (headers, role matrix, ownership scoping), response envelope,
pagination, 404 family, reverse-reachability lists."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    NON_EXISTENT_UUID, build_user_headers,
    create_referral_payload, create_patient_payload, loop_closure_payload,
    create_plan, create_provider, create_specialist, create_patient,
    create_participation, create_referral, create_pending_verification_referral,
    set_clock, get_referral,
    make_referring_provider_headers, make_auditor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestUserContextHeaders:
    def test_missing_headers_and_undeclared_role_rejected(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing, or if the value of `X-User-Role`
        is not one of the declared role strings, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_unauthenticated
        """
        no_headers = api.list_referrals({"Content-Type": "application/json"})
        validate_error(no_headers,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=401)

        bogus_role = api.list_referrals(build_user_headers("someone", "SuperUser"))
        validate_error(bogus_role,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=401)


class TestRoleDenialMatrix:
    def test_each_role_denied_others_exclusive_operations(self, api):
        """PRD §2.1: "If the role is valid but not permitted for the invoked
        endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4 endpoint table: POST /referrals/{id}/accept is ReferralCoordinator;
        POST /appointments/{id}/mark-no-show is ReferralCoordinator; POST /referrals
        is ReferringProvider; POST /referrals/{id}/loop-closures is
        ComplianceAuditor.

        Design: Corner/rbac/role_denial_matrix
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        specialist = create_specialist()
        create_participation(specialist["id"], plan["id"])
        provider = create_provider()
        patient = create_patient(plan["id"])
        r1 = create_referral(provider["id"], patient["id"], diagnosis_code="I10")
        # Carry a second referral to PENDING_VERIFICATION for the closure probe.
        r2, a2, _note = create_pending_verification_referral(
            provider["id"], patient["id"], specialist["id"],
            "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z",
            complete_at="2026-08-02T11:00:00Z", coordinator_user_id="coord-1",
            diagnosis_code="I11",
        )

        e1 = api.accept_referral(r1["id"], make_referring_provider_headers(provider["id"]))
        validate_error(e1, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

        e2 = api.mark_no_show(a2["id"], TEST_USERS["specialist_provider_headers"])
        validate_error(e2, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

        e3 = api.create_referral(
            create_referral_payload(patient["id"], diagnosis_code="I20"),
            make_auditor_headers("audit-1"),
        )
        validate_error(e3, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

        e4 = api.accept_referral(r1["id"], ADMIN)
        validate_error(e4, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)

        e5 = api.create_loop_closure(
            r2["id"],
            loop_closure_payload(r2["version"], "VERIFIED_CLOSED", verification_note="x"),
            COORD,
        )
        validate_error(e5, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


class TestProviderOwnershipScoping:
    def test_provider_cannot_read_others_referral(self, api):
        """PRD §2.1: "In particular, a `ReferringProvider` may only read, resubmit,
        or cancel referrals whose `referring_provider_id` equals their `X-User-ID`,
        and may only read their own leakage records, snapshots, and leakage report;
        violating this scoping yields `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."
        PRD §4: "List referrals; ReferringProvider role sees only own referrals".

        Design: Corner/rbac/provider_cannot_read_others_referral
        """
        plan = create_plan()
        pa = create_provider(name="Dr A", npi="2000000001")
        pb = create_provider(name="Dr B", npi="2000000002", specialty="FAMILY_MEDICINE")
        patient = create_patient(plan["id"])
        referral = create_referral(pa["id"], patient["id"])

        res = api.get_referral(referral["id"], make_referring_provider_headers(pb["id"]))
        validate_error(res, ApiErrorId.ERR_OWNERSHIP_VIOLATION, expected_status=403)

        data, meta = validate_paginated(
            api.list_referrals(make_referring_provider_headers(pb["id"]))
        )
        assert data == [] and meta["total_count"] == 0, (
            "A provider's referral list is auto-scoped to their own referrals"
        )


class TestNotFoundMatrix:
    def test_not_found_matrix_across_resources(self, api):
        """PRD §2.7: "Fifth, existence: path resource ids are validated left to
        right, then body foreign-key references in their declared input order
        (priority 5 — the 404 family such as `ERR_REFERRAL_NOT_FOUND`,
        `ERR_PATIENT_NOT_FOUND`, `ERR_SPECIALIST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_PARTICIPATION_NOT_FOUND`, `ERR_AUTH_RULE_NOT_FOUND`,
        `ERR_APPOINTMENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_CONSULT_NOTE_NOT_FOUND`)."

        Design: Corner/errors/not_found_matrix_across_resources
        """
        cases = [
            (api.get_patient(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_PATIENT_NOT_FOUND),
            (api.get_insurance_plan(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_PLAN_NOT_FOUND),
            (api.get_participation(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_PARTICIPATION_NOT_FOUND),
            (api.get_auth_rule(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_AUTH_RULE_NOT_FOUND),
            (api.get_appointment(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_APPOINTMENT_NOT_FOUND),
            (api.get_referring_provider(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_PROVIDER_NOT_FOUND),
            (api.get_consult_note(NON_EXISTENT_UUID, COORD), ApiErrorId.ERR_CONSULT_NOTE_NOT_FOUND),
        ]
        for res, expected in cases:
            validate_error(res, expected, expected_status=404)


class TestPaginationEnvelope:
    def test_pagination_defaults_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1, and
        may not exceed 100. The `offset` parameter defaults to 0. List responses are
        sorted by `created_at` ascending. The `meta` block of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`, so a client can page
        deterministically through the full result set."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources." and "The `api_request_id` is a
        server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/endpoints/pagination_defaults_and_envelope
        """
        plan = create_plan()
        for i in range(1, 4):
            create_patient(plan["id"], mrn=f"M00{i}", full_name=f"P{i}")

        page1, meta1 = validate_paginated(api.list_patients(COORD, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_patients(COORD, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        body = api.list_patients(COORD, params={"limit": 2, "offset": 0}).json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")


class TestReverseReachabilityLists:
    def test_sub_resource_lists_return_empty_arrays(self, api):
        """PRD §4 endpoint table: GET /referrals/{id}/authorization-records,
        /consult-notes, /loop-closures, /leakage-records are list endpoints.
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."
        PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`".

        Design: Corner/endpoints/reverse_reachability_lists_return_arrays
        """
        plan = create_plan()
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_referral(provider["id"], patient["id"])

        for list_call in (
            api.list_referral_authorization_records,
            api.list_referral_consult_notes,
            api.list_referral_loop_closures,
            api.list_referral_leakage_records,
        ):
            data, meta = validate_paginated(list_call(referral["id"], COORD))
            assert data == [], "A fresh referral has no sub-resource rows"
            assert meta["total_count"] == 0
            assert meta["has_more"] is False
