"""Response envelopes, the identity-header guard, and the computed
targets_weight_total (PRD §2.1, §2.2, §3.2)."""
from test_helpers import (
    validate_success, validate_error, is_iso8601_timestamp, ApiErrorId,
    create_approved_school, create_draft_contract, create_target_payload,
    create_application_payload,
    make_applicant_headers, make_staff_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


class TestSuccessEnvelopeShape:
    def test_create_and_list_use_the_standard_envelope(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/endpoints/ep_success_envelope_shape
        """
        create_res = api.create_application(
            create_application_payload(school_name="EP Envelope Academy"),
            make_applicant_headers("applicant_p1"))
        assert create_res.status_code == 201
        create_body = create_res.json()
        assert "meta" in create_body and "data" in create_body
        request_id = create_body["meta"]["api_request_id"]
        assert isinstance(request_id, str) and request_id.startswith("req_")
        assert is_iso8601_timestamp(create_body["meta"]["api_request_timestamp"])
        assert create_body["response_type"] == "object"
        app_id = create_body["data"]["id"]

        list_res = api.list_applications(STAFF)
        assert list_res.status_code == 200
        list_body = list_res.json()
        assert list_body["response_type"] == "array"
        assert isinstance(list_body["data"], list)
        assert any(a["id"] == app_id for a in list_body["data"])
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in list_body["meta"], f"meta missing pagination field {field}"


class TestErrorEnvelopeShape:
    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/ep_error_envelope_shape
        """
        res = api.get_application("11111111-2222-4333-8444-555555555555", STAFF)
        assert res.status_code == 404
        body = res.json()
        assert body["response_type"] == "error"
        assert "meta" in body
        assert body["meta"]["api_request_id"]
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestMissingIdentityHeaders:
    def test_request_without_identity_headers_rejected(self, api):
        """PRD §2.1: "Every request carries two identity headers: `X-User-ID`
        and `X-User-Role`. A request missing either header, or presenting a
        role outside the declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/val_auth_missing_header_rejected
        """
        res = api.list_schools(headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)


class TestContractTargetsWeightTotalComputed:
    def test_weight_total_recomputed_per_target_addition(self, api):
        """PRD §3.2: "A successful create lands the contract in `DRAFT` with
        `targets_weight_total` at zero and increments the school's `version` by
        one, so any writer holding an older read of the school must refresh
        before its own create."
        PRD §3.2: "Every addition recomputes the contract's
        `targets_weight_total`, the running sum of its targets' weights."

        Design: Corner/endpoints/ep_contract_targets_weight_total_computed
        """
        _app, school = create_approved_school(school_name="EP Weights Academy",
                                              applicant_id="applicant_p2")
        school = validate_success(api.get_school(school["id"], STAFF), 200)
        contract = create_draft_contract(school["id"], school["version"])
        assert contract["targets_weight_total"] == 0

        validate_success(api.add_contract_target(
            contract["id"], create_target_payload(weight=0.5), STAFF), 201)
        validate_success(api.add_contract_target(
            contract["id"], create_target_payload(
                domain="FINANCIAL", metric_code="AUDIT_CLEAN", target_value=1,
                floor_value=1, weight=0.25), STAFF), 201)
        mid = validate_success(api.get_contract(contract["id"], STAFF), 200)
        assert mid["targets_weight_total"] == 0.75

        validate_success(api.add_contract_target(
            contract["id"], create_target_payload(
                domain="OPERATIONAL", metric_code="ENROLL_PCT", target_value=95,
                floor_value=85, weight=0.25), STAFF), 201)
        full = validate_success(api.get_contract(contract["id"], STAFF), 200)
        assert full["targets_weight_total"] == 1.0
