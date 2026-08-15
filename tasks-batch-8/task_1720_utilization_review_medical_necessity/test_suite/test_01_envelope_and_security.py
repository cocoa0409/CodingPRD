"""Response envelope, pagination, authentication, and request-shape security
conventions (PRD §2.1, §2.2, §2.3, §2.5)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_physician,
    create_utilization_case_payload,
    make_payer,
    make_physician,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["ur_director_headers"]
NURSE = TEST_USERS["ur_nurse_headers"]
PAYER_REVIEWER = TEST_USERS["payer_reviewer_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]
APPEALS = TEST_USERS["appeals_coordinator_headers"]


class TestResponseEnvelope:
    def test_list_payers_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_payers_pagination_envelope
        """
        make_payer(name="Payer One")
        make_payer(name="Payer Two", plan_class="COMMERCIAL",
                   requires_inpatient_auth=False,
                   concurrent_review_cadence_hours=24, p2p_window_hours=48,
                   appeal_deadline_days=30, bed_day_budget_per_case=10,
                   avoidable_attribution_method="DOMINANT_CAUSE")

        resp = api.list_payers(CASE_MANAGER)
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array", (
            f"list endpoint must report response_type 'array', got {body['response_type']!r}")
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(data) == 2

    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        resp = api.get_denial_case(NON_EXISTENT_UUID, APPEALS)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {
            "api_request_id", "api_request_timestamp"}, (
            f"error meta must carry only id and timestamp, got {sorted(body['meta'])}")
        assert isinstance(error["message"], str) and error["message"].strip()


class TestAuthenticationAndRoles:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role string other than these seven, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_payers(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_payer_reviewer_cannot_create_case_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/validations/payer_reviewer_cannot_create_case_forbidden
        """
        payer = make_payer()
        attending = make_physician()
        resp = api.create_utilization_case(
            create_utilization_case_payload(payer["id"], attending["id"],
                                            patient_mrn="MRN-RB1"),
            PAYER_REVIEWER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)

        cases, meta = validate_paginated(api.list_utilization_cases(NURSE))
        assert meta["total_count"] == 0 and cases == [], (
            "a rejected create must not persist a utilization case")


class TestRequestShapeIntegrity:
    def test_case_create_missing_required_field_returns_400(self, api):
        """PRD §3.2: "A `URNurse` opens a utilization case at admission by supplying the `patient_mrn`, the `payer_id`, the `attending_physician_id`, the `admit_at` timestamp, the physician-documented `expected_discharge_at`, and the physician's admission order as `requested_admission_status` — either `INPATIENT` or `OBSERVATION`."
        PRD §2.5: "Request-shape integrity — required fields present, enum members valid, numeric ranges honored (including the conference-duration floor of at least 15 minutes with the end strictly after the start), and no client-supplied computed or system-managed fields; failure yields `ERR_VALIDATION_FAILED`."

        Design: Corner/validations/case_create_missing_required_field_returns_400
        """
        attending = make_physician()
        payload = create_utilization_case_payload("unused-payer", attending["id"],
                                                  patient_mrn="MRN-RQ1")
        del payload["payer_id"]
        resp = api.create_utilization_case(payload, NURSE)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED,
                       expected_status=400)

    def test_payer_create_invalid_enum_returns_400(self, api):
        """PRD §3.1: "A **Payer** is created with a display `name`, a `plan_class` of `MEDICARE`, `MANAGED_MEDICARE`, `MEDICAID`, or `COMMERCIAL`, and a policy bundle"
        PRD §2.5: "Request-shape integrity — required fields present, enum members valid, numeric ranges honored (including the conference-duration floor of at least 15 minutes with the end strictly after the start), and no client-supplied computed or system-managed fields; failure yields `ERR_VALIDATION_FAILED`."

        Design: Corner/validations/payer_create_invalid_enum_returns_400
        """
        resp = api.create_payer(
            {"name": "Bad Payer", "plan_class": "TRICARE_PLUS",
             "requires_inpatient_auth": True,
             "concurrent_review_cadence_hours": 48, "p2p_window_hours": 72,
             "appeal_deadline_days": 60, "bed_day_budget_per_case": 30,
             "avoidable_attribution_method": "FIRST_CAUSE"},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_VALIDATION_FAILED,
                       expected_status=400)


class TestResourceDefaultsAndLookup:
    def test_physician_is_advisor_defaults_false(self, api):
        """PRD §3.1: "A **Physician** is registered with a `full_name`, a `specialty`, and an `is_advisor` flag (defaulting to false) that marks the physician as eligible to act as a physician advisor: peer-to-peer medical-director counterpart, CC44 committee reviewer, and advisor second-level reviewer."

        Design: Corner/entities/physician_is_advisor_defaults_false
        """
        created = validate_success(api.create_physician(
            {"full_name": "Dr. Plain", "specialty": "Family Medicine"},
            DIRECTOR), expected_status=201)
        assert_physician(created)
        assert created["is_advisor"] is False, (
            "omitting is_advisor must default the physician to non-advisor")

        fetched = validate_success(api.get_physician(created["id"], NURSE))
        assert fetched["is_advisor"] is False

    def test_get_case_missing_id_returns_not_found(self, api):
        """PRD §2.5: "Path existence — every path identifier resolves, checked left to right; failure yields `ERR_NOT_FOUND`."

        Design: Corner/entities/get_case_missing_id_returns_not_found
        """
        resp = api.get_utilization_case(NON_EXISTENT_UUID, NURSE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
