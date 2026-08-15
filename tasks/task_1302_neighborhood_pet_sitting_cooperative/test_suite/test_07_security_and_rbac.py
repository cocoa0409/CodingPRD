"""Caller identity, role permission gates, and nested-resource resolution
(PRD §2.1, §2.7, §2.8)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_holiday_window_payload, create_sitting_request_payload,
    create_claim_payload, create_member_payload,
    make_member_headers, make_admin_headers, make_anonymous_headers,
    bootstrap_founders, create_applicant, create_pet, post_request, claim_request,
    setup_confirmed_sit, get_member,
    ADMIN, ANON,
)


class TestCallerIdentity:
    def test_missing_x_user_id_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming the capacity in which
        they act. A request missing either header, or presenting a malformed value,
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/get_members_missing_x_user_id_header_returns_400
        """
        headers = {"X-User-Role": "Member"}  # X-User-ID omitted
        res = api.list_members(headers)
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       expected_status=400)

    def test_anonymous_list_members_unauthorized(self, api):
        """PRD §2.1: "Each operation additionally restricts which roles may invoke
        it (§4). A caller whose role is not permitted for the endpoint is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| GET | `/coop/members` | List members | CoopAdmin, Member |"

        Design: Corner/validations/anonymous_list_members_returns_unauthorized
        """
        res = api.list_members(ANON)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestNotFound:
    def test_get_member_not_found_404(self, api):
        """PRD §2.7: "3. Existence of every resource named in the path, resolved
        left to right — otherwise `ERR_NOT_FOUND` (HTTP 404)."
        PRD §2.8: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not resolve to an existing resource; identifiers
        to the right of that point are never examined."

        Design: Corner/entities/get_member_not_found_returns_404
        """
        res = api.get_member(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_nested_claim_on_missing_request_404(self, api):
        """PRD §2.8: "Endpoints that address a resource through its parents — for
        example a claim addressed through its sitting request — validate path
        identifiers strictly left to right."
        PRD §2.8: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not resolve to an existing resource; identifiers
        to the right of that point are never examined."

        Design: Corner/entities/nested_claim_on_missing_request_returns_404
        """
        x = create_applicant("Claimant", "claimant@coop.test", "+15550303")
        res = api.create_claim(NON_EXISTENT_UUID, create_claim_payload(
            message="Claiming a ghost request"), make_member_headers(x["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestRoleGates:
    def test_member_denied_admin_exclusive_ops(self, api):
        """PRD §2.1: "Each operation additionally restricts which roles may invoke
        it (§4). A caller whose role is not permitted for the endpoint is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/coop/holiday-windows` | Create a holiday demand window |
        CoopAdmin |"
        PRD §4: "| POST | `/coop/members/{memberId}/finalize-vetting` | Vet a member
        after reciprocity and liability checks | CoopAdmin |"
        PRD §4: "| POST | `/coop/sitting-assignments/{assignmentId}/settle` | Settle
        a completed assignment (posts ledger entries) | CoopAdmin |"

        Design: Corner/rbac/member_cannot_perform_admin_exclusive_ops_returns_unauthorized
        """
        f = bootstrap_founders()
        sit = setup_confirmed_sit(founders=f)
        member_headers = make_member_headers(f["f1"]["id"])

        res = api.create_holiday_window(create_holiday_window_payload(
            name="Sneaky", demand_multiplier=2.0), member_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

        res = api.finalize_vetting(f["f2"]["id"], member_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

        res = api.settle_assignment(sit["assignment"]["id"], member_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

        # No side effects from any denied call.
        windows = get_success_data(api.list_holiday_windows(ADMIN))
        assert windows == []
        assert get_member(f["f2"]["id"])["vetting_status"] == "VETTED"
        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "CONFIRMED"
        from test_helpers import list_ledger
        assert list_ledger(f["f2"]["id"], params={"entry_type": "SIT_EARNED"}) == []

    def test_admin_cannot_post_sitting_request(self, api):
        """PRD §2.1: "Each operation additionally restricts which roles may invoke
        it (§4). A caller whose role is not permitted for the endpoint is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/coop/sitting-requests` | Post a sitting request |
        Member |"

        Design: Corner/rbac/admin_cannot_post_sitting_request_returns_unauthorized
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        res = api.create_sitting_request(create_sitting_request_payload(
            pet["id"], instructions="Admin posting attempt"), ADMIN)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        data = get_success_data(api.list_sitting_requests(ADMIN))
        assert data == []

    def test_member_shared_reads_allowed(self, api):
        """PRD §2.1: "Each operation additionally restricts which roles may invoke
        it (§4). A caller whose role is not permitted for the endpoint is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| GET | `/coop/members` | List members | CoopAdmin, Member |"
        PRD §4: "| GET | `/coop/holiday-windows` | List holiday windows | CoopAdmin,
        Member |"
        PRD §4: "| GET | `/coop/sitting-requests` | List sitting requests |
        CoopAdmin, Member |"

        Design: Corner/rbac/member_shared_reads_allowed
        """
        from test_helpers import create_window
        f = bootstrap_founders()
        create_window(name="W1", demand_multiplier=2.0)
        headers = make_member_headers(f["f1"]["id"])

        members = validate_success(api.list_members(headers), 200)
        assert len(members) == 3
        windows = validate_success(api.list_holiday_windows(headers), 200)
        assert len(windows) == 1
        requests = validate_success(api.list_sitting_requests(headers), 200)
        assert requests == []
