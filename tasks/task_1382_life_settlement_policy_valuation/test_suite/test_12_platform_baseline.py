"""Platform baseline: envelopes, clock default, auth/role/existence order,
OCC on offer counter, aggregate guards (PRD §2.1–2.7, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_broker_headers,
    create_broker_payload,
    setup_case_marketed, setup_broker_insured_policy, create_case_for,
    create_offer,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestEnvelope:
    def test_response_envelope_and_error_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format" with "data": {"error_id": ..., "message": ...}."

        Design: Corner/endpoints/response_envelope_and_error_shape
        """
        resp = api.create_broker(create_broker_payload(name="B", license_number="BR-1",
                                                       state_code="TX"), ADMIN)
        body = resp.json()
        assert resp.status_code == 201
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert body["data"]["name"] == "B"

        err_resp = api.get_policy(NON_EXISTENT_UUID, CM)
        err_body = err_resp.json()
        assert err_resp.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]

    def test_clock_default_stamp_on_create(self, api):
        """PRD §2.4: "The clock's startup default, before any call to set it, is
        exactly 2026-08-01T00:00:00Z."

        Design: Corner/endpoints/clock_default_stamp_on_create
        """
        broker = validate_success(api.create_broker(
            create_broker_payload(name="B", license_number="BR-1", state_code="TX"), ADMIN),
            expected_status=201)
        assert broker["created_at"] == "2026-08-01T00:00:00Z"


class TestAuthOrder:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or malformed, or the role value
        is not one of the recognized roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.7: "Across all rules attached to an endpoint, evaluation follows a
        fixed priority order, and the first failure determines the response:
        1. Header presence and role recognition
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.get_policy(NON_EXISTENT_UUID, {"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_role_not_in_endpoint_roles_unauthorized(self, api):
        """PRD §2.1: "If the role is recognized but does not appear in the
        endpoint's authorized role list, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "POST | /api/cases | Create a `DRAFT` policy case; `broker_id`
        set from caller | Broker"

        Design: Corner/validations/role_not_in_endpoint_roles_unauthorized
        """
        broker, insured, policy = setup_broker_insured_policy(with_license=False,
                                                              insured_overrides={"smoker_status": "UNKNOWN"})
        resp = api.create_case({"policy_id": policy["id"]}, UW)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_nonexistent_offer_counter_returns_404(self, api):
        """PRD §2.7: "Where a URL nests one resource under another, path identifiers
        are validated left to right: each id must exist before the next is
        examined, and the first missing id yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/nonexistent_offer_counter_returns_404
        """
        broker = validate_success(api.create_broker(create_broker_payload(name="B"), ADMIN),
                                  expected_status=201)
        resp = api.counter_offer(
            NON_EXISTENT_UUID,
            {"counter_amount_cents": 100, "expected_offer_version": broker["version"]},
            make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestOfferOCC:
    def test_occ_offer_counter_stale_version(self, api):
        """PRD §2.6: "Countering an offer requires `expected_offer_version`
        carrying the client's last observed `version` of the target offer. If the
        offer's version has advanced since that observation — for example because a
        re-offer response has already rewritten `amount_cents` and `round_number`,
        so the client's counter would be computed against superseded terms — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_offer_counter_stale_version
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=False,
                                  insured_overrides={"smoker_status": "UNKNOWN"})
        case, broker = ctx["case"], ctx["broker"]
        bh = make_broker_headers(broker["id"])
        offer = create_offer(case, 6000000)
        v1 = offer["version"]

        countered = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 6100000, "expected_offer_version": v1}, bh))
        assert countered["status"] == "COUNTERED"
        reoffered = validate_success(api.respond_to_offer(
            offer["id"], {"action": "RE_OFFER", "amount_cents": 6050000}, UW))
        v3 = reoffered["version"]
        assert v3 == v1 + 2

        # Stale by two mutations: rejected even though the increment is valid.
        resp = api.counter_offer(
            offer["id"], {"counter_amount_cents": 6110500, "expected_offer_version": v1}, bh)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        ok = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 6110500, "expected_offer_version": v3}, bh))
        assert ok["status"] == "COUNTERED"


class TestAggregateGuards:
    def test_duplicate_active_case_rejected_then_allowed(self, api):
        """PRD §3.1: "A policy may carry at most one case in a non-terminal status
        at a time; attempting to open a second case against a policy that already
        has one is rejected with `ERR_DUPLICATE_ACTIVE_CASE` (HTTP 409)."
        PRD §3.1: "From `DRAFT`, and later from `SCREENING`, `SCREEN_FAILED`,
        `UNDERWRITING`, or `MARKETED`, the owning broker may also withdraw the case
        outright, landing it in `WITHDRAWN`."

        Design: Corner/validations/duplicate_active_case_rejected_then_allowed
        """
        broker, insured, policy = setup_broker_insured_policy(
            with_license=False, insured_overrides={"smoker_status": "UNKNOWN"})
        bh = make_broker_headers(broker["id"])
        case1 = create_case_for(broker, policy)

        resp = api.create_case({"policy_id": policy["id"]}, bh)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_CASE)

        validate_success(api.withdraw_case(case1["id"], bh))
        case2 = validate_success(api.create_case({"policy_id": policy["id"]}, bh),
                                 expected_status=201)
        assert case2["id"] != case1["id"]

    def test_policy_patch_locked_while_marketed(self, api):
        """PRD §2.9: "A broker or case manager may amend a policy's financial
        fields — `face_amount_cents`, `annual_premium_cents`, `cash_value_cents`,
        `policy_loan_cents` — through the amendment endpoint, but only while no
        case of that policy is in `UNDERWRITING`, `MARKETED`, `IN_CLOSING`, or
        `ACQUIRED`; an amendment attempted under an active case in one of those
        states is rejected with `ERR_POLICY_LOCKED_BY_ACTIVE_CASE` (HTTP 409)."

        Design: Corner/validations/policy_patch_locked_while_marketed
        """
        ctx = setup_case_marketed(with_disclosures=False, with_offer=False,
                                  insured_overrides={"smoker_status": "UNKNOWN"})
        policy, broker = ctx["policy"], ctx["broker"]
        assert ctx["case"]["status"] == "MARKETED"
        resp = api.patch_policy(policy["id"], {"annual_premium_cents": 700000},
                                make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_POLICY_LOCKED_BY_ACTIVE_CASE)
        policy_after = validate_success(api.get_policy(policy["id"], CM))
        assert policy_after["annual_premium_cents"] == 600000


class TestSegregationOfDuties:
    def test_sod_release_by_approver_rejected(self, api):
        """PRD §3.5: "the releasing finance officer's `X-User-ID` must differ from
        the closing package's `approved_by_user_id` — the segregation-of-duties
        check, rejected as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the same
        operator approved the package"

        Design: Corner/errors/sod_release_by_approver_rejected
        """
        from test_helpers import setup_ownership_confirmed, set_clock
        ctx = setup_ownership_confirmed(
            insured_overrides={"smoker_status": "UNKNOWN"})  # funded at default clock
        set_clock("2026-08-16T00:00:00Z")

        # Approver co_1 attempts the release under a FinanceOfficer role.
        resp = api.release_escrow(ctx["escrow"]["id"],
                                  {"X-User-ID": "co_1", "X-User-Role": "FinanceOfficer",
                                   "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        released = validate_success(api.release_escrow(
            ctx["escrow"]["id"],
            {"X-User-ID": "fo_9", "X-User-Role": "FinanceOfficer",
             "Content-Type": "application/json"}))
        assert released["status"] == "RELEASED"
