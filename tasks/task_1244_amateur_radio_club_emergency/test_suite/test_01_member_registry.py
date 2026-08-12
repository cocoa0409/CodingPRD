"""Member registry: creation defaults, uniqueness, dues lifecycle, profile
maintenance, listing/pagination, auth envelope, and read access (PRD §2, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equals,
    assert_member,
    assert_member_invariants,
    create_member,
    create_member_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_member_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMemberCreationDefaults:
    def test_new_member_starts_pending_with_good_standing(self, api, admin_headers):
        """PRD §3.1: "New members start in `membership_status` `PENDING`: they
        hold no active standing until dues are paid." and "Their
        `equipment_privilege` starts at `GOOD_STANDING`."

        Design: Corner/entities/member_creation_defaults
        """
        resp = api.create_member(create_member_payload(callsign="K1NEW"), admin_headers)
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["membership_status"] == "PENDING"
        assert member["equipment_privilege"] == "GOOD_STANDING"
        assert member["version"] == 1

    def test_new_member_readiness_is_bonus_only_and_ineligible(self, api, admin_headers):
        """PRD §3.1: "a brand-new member's `readiness_score` and
        `readiness_score_optimistic` both evaluate to 20 and their
        `readiness_tier` is `INELIGIBLE` until participation accrues."

        Design: Corner/entities/member_creation_defaults
        """
        resp = api.create_member(create_member_payload(callsign="K1NEW"), admin_headers)
        member = validate_success(resp, 201)
        assert member["readiness_score"] == 20
        assert member["readiness_score_optimistic"] == 20
        assert member["readiness_tier"] == "INELIGIBLE"
        assert_member_invariants(member)


class TestCallsignUniqueness:
    def test_duplicate_callsign_rejected_case_insensitive(self, api, admin_headers):
        """PRD §3.1: "The callsign is unique club-wide and compared
        case-insensitively; a duplicate registration is rejected with
        `ERR_CALLSIGN_TAKEN`."

        Design: Corner/entities/member_duplicate_callsign_rejected
        """
        first = api.create_member(
            create_member_payload(callsign="K1DUP", full_name="First"), admin_headers)
        validate_success(first, 201)
        second = api.create_member(
            create_member_payload(callsign="k1dup", full_name="Second"), admin_headers)
        validate_error(second, ApiErrorId.ERR_CALLSIGN_TAKEN)


class TestMemberLookup:
    def test_get_member_not_found(self, api, admin_headers):
        """PRD §2.6: "The first identifier that does not resolve to an existing
        resource rejects the whole request with `ERR_NOT_FOUND` before any
        business rule runs."

        Design: Corner/entities/member_get_not_found
        """
        resp = api.get_member(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_member_reads_own_detail(self, api, admin_headers):
        """PRD §4: the member detail endpoint is listed for roles "ClubAdmin,
        Member, EmergencyCoordinator, NetControl, ExamLiaison", and §3.1:
        "Renewal moves a `PENDING` or `LAPSED` member to `ACTIVE`".

        Design: Corner/rbac/member_reads_own_detail
        """
        member = create_member("K1OPR")
        get_success_data(api.renew_member(member["id"], {"periods": 1}, admin_headers))
        resp = api.get_member(member["id"], make_member_headers(member["id"]))
        detail = validate_success(resp, 200)
        assert detail["membership_status"] == "ACTIVE"
        assert detail["readiness_score"] == 20


class TestMemberValidation:
    def test_license_class_outside_enum_rejected(self, api, admin_headers):
        """PRD §2.10: "a structurally malformed request body — a missing
        required field, a wrong-typed value, an enum value outside its declared
        set, or an unknown or read-only field supplied by the client — is
        rejected with `ERR_VALIDATION`."

        Design: Corner/validations/member_invalid_enum_rejected
        """
        payload = create_member_payload(callsign="K1BAD", license_class="NOVICE")
        resp = api.create_member(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestMemberLifecycle:
    def test_clock_past_dues_lapses_member_then_renewal_recovers(self, api, admin_headers):
        """PRD §3.1: "when the logical clock advances past `dues_paid_through`,
        the member transitions `ACTIVE` → `LAPSED` with readiness recomputed."
        PRD §3.1: "The paid-through instant is computed as the later of the
        current logical clock and the member's existing `dues_paid_through`
        (treated as the epoch `1970-01-01T00:00:00Z` when none has ever been
        set), extended by `periods` times 365 days, and stored back as the new
        `dues_paid_through`."

        Design: Corner/state_machines/member_lapse_and_renew_cycle
        """
        member = create_member("K1OPR", license_class="GENERAL")
        renewed = get_success_data(
            api.renew_member(member["id"], {"periods": 1}, admin_headers))
        assert renewed["membership_status"] == "ACTIVE"
        get_success_data(api.set_clock({"to_iso8601": "2027-05-02T00:00:00Z"}, admin_headers))
        lapsed = get_success_data(api.get_member(member["id"], admin_headers))
        assert lapsed["membership_status"] == "LAPSED"
        renewed_again = get_success_data(
            api.renew_member(member["id"], {"periods": 1}, admin_headers))
        assert renewed_again["membership_status"] == "ACTIVE"
        assert_instant_equals(renewed_again["dues_paid_through"],
                              "2028-05-02T00:00:00Z", "dues_paid_through")

    def test_renewal_extends_from_paid_through_not_clock(self, api, admin_headers):
        """PRD §3.1: "The paid-through instant is computed as the later of the
        current logical clock and the member's existing `dues_paid_through`
        (treated as the epoch `1970-01-01T00:00:00Z` when none has ever been
        set), extended by `periods` times 365 days, and stored back as the new
        `dues_paid_through`."

        Design: Corner/calculations/membership_renewal_extends_from_paid_through
        """
        member = create_member("K1OPR", license_class="GENERAL")
        get_success_data(api.renew_member(member["id"], {"periods": 1}, admin_headers))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, admin_headers))
        renewed = get_success_data(
            api.renew_member(member["id"], {"periods": 1}, admin_headers))
        assert renewed["membership_status"] == "ACTIVE"
        assert_instant_equals(renewed["dues_paid_through"],
                              "2028-05-01T00:00:00Z", "dues_paid_through")

    def test_reinstate_with_lapsed_dues_rejected(self, api, admin_headers):
        """PRD §3.1: "Reinstatement requires that the member's dues are still
        current — `dues_paid_through` strictly later than the current clock —
        otherwise the request is rejected with `ERR_DUES_LAPSED`."

        Design: Corner/validations/reinstate_with_lapsed_dues_rejected
        """
        member = create_member("K1OPR")
        get_success_data(api.renew_member(member["id"], {"periods": 1}, admin_headers))
        get_success_data(
            api.member_set_status(member["id"], {"to": "SUSPENDED"}, admin_headers))
        get_success_data(api.set_clock({"to_iso8601": "2027-06-01T00:00:00Z"}, admin_headers))
        resp = api.member_set_status(member["id"], {"to": "ACTIVE"}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUES_LAPSED)
        member_after = get_success_data(api.get_member(member["id"], admin_headers))
        assert member_after["membership_status"] == "SUSPENDED"


class TestMemberMutationVersioning:
    def test_version_increments_on_create_renew_and_patch(self, api, admin_headers):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource, including
        mutations caused by cascades originating on other entities."
        PRD §3.1: "an administrator may update `full_name`, `license_class`, or
        `license_expires_at` in place, which bumps `version` without any status
        change."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_mutation
        """
        member = create_member("K1OPR")
        assert member["version"] == 1
        renewed = get_success_data(
            api.renew_member(member["id"], {"periods": 1}, admin_headers))
        assert renewed["version"] == 2
        patched = get_success_data(
            api.patch_member(member["id"], {"full_name": "Operator Renamed"}, admin_headers))
        assert patched["version"] == 3
        assert patched["full_name"] == "Operator Renamed"


class TestMemberListing:
    def test_member_list_pagination_defaults(self, api, admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10 when omitted, with a minimum of 1 and a maximum of
        100. The `offset` parameter skips a number of items from the front of
        the result set and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/member_list_pagination_defaults
        """
        for i in range(1, 13):
            create_member(f"K1P{i:02d}", full_name=f"P{i:02d}", license_class="GENERAL")
        first_page, meta = validate_paginated(api.list_members(admin_headers))
        assert len(first_page) == 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        second_page, meta2 = validate_paginated(
            api.list_members(admin_headers, params={"offset": 10}))
        assert len(second_page) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestResponseEnvelope:
    def test_success_and_error_envelope_shapes(self, api, admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and
        "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape
        """
        resp = api.create_member(create_member_payload(callsign="K1ENV"), admin_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict)

        err_resp = api.get_member(NON_EXISTENT_UUID, admin_headers)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, presenting a role
        outside this set, or — for the entity-backed roles below — presenting
        an `X-User-ID` that does not reference an existing club member is
        rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_auth_headers_unauthenticated
        """
        resp = api.create_member(create_member_payload(callsign="K1NAH"), headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestMemberRbac:
    def test_member_cannot_create_member(self, api, admin_headers):
        """PRD §4: the member-registration endpoint is listed with authorized
        role "ClubAdmin" only, and §2.1: "A request whose role is not listed
        for the target endpoint, or that fails a declared ownership sub-check
        (a net control acting on another operator's net, a member touching
        another member's roster entry, loan, contact, or message), is rejected
        with `ERR_FORBIDDEN`."

        Design: Corner/rbac/member_cannot_create_member
        """
        member = create_member("K1OPR")
        resp = api.create_member(create_member_payload(callsign="K2NEW"),
                                 make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
