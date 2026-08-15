"""Member registration, profile upkeep, auth headers, and the response
envelope."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_member,
    create_member_payload,
    get_member,
    is_valid_uuid,
    make_member_headers,
    patch_member_payload,
    register_member,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["park_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

_TS_3FRAC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class TestMemberRegistration:
    def test_member_registration_applies_system_defaults(self, api):
        """PRD §3.1: "The new Member is created in `PENDING_VERIFICATION`
        status with `strike_points` at 0, `provisional_strike_score` at 0,
        `guest_passes_used_this_month` at 0, `is_steward` false, and `version`
        1."

        Design: Corner/entities/create_member_applies_defaults
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_member(
            create_member_payload(full_name="New Member", email="new@x.com"),
            ANON,
        )
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["status"] == "PENDING_VERIFICATION"
        assert member["strike_points"] == 0
        assert member["provisional_strike_score"] == 0
        assert member["guest_passes_used_this_month"] == 0
        assert member["is_steward"] is False
        assert member["version"] == 1

    def test_register_member_missing_email_rejected(self, api):
        """PRD §3.1: "Registration requires a `full_name` and an `email` — the
        address is unique per member — with `phone` optional and defaulting to
        null."
        PRD §2.7: "5. **Request shape** — required fields present, enum values
        valid, exactly one of `dog_id` and `guest_pass_id` supplied at check-in,
        `ends_at` strictly after `starts_at`, `peak_capacity` not exceeding
        `capacity`, pagination parameters within bounds: `ERR_INVALID_REQUEST`."

        Design: Corner/entities/register_member_missing_email_rejected
        """
        resp = api.create_member({"full_name": "No Email"}, ANON)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_member_not_found_returns_404(self, api):
        """PRD §2.8: "The not-found family is `ERR_MEMBER_NOT_FOUND`,
        `ERR_DOG_NOT_FOUND`, `ERR_MEMBERSHIP_NOT_FOUND`,
        `ERR_GUEST_PASS_NOT_FOUND`, `ERR_AREA_NOT_FOUND`,
        `ERR_CLOSURE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_WASTE_STATION_NOT_FOUND`."

        Design: Corner/entities/get_member_not_found_returns_404
        """
        resp = api.get_member(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND)


class TestResponseEnvelope:
    def test_create_response_success_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601
        UTC timestamp with three fractional digits."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.5: "`id` (string): a unique, server-minted UUID with no type
        prefix."

        Design: Corner/endpoints/success_envelope_shape_on_create
        """
        resp = api.create_member(
            create_member_payload(full_name="Env Elope", email="env@x.com"),
            ANON,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["response_type"] == "object"
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            "api_request_id starts with req_"
        )
        assert _TS_3FRAC.match(meta["api_request_timestamp"]), (
            "api_request_timestamp is ISO 8601 UTC with three fractional digits"
        )
        assert is_valid_uuid(body["data"]["id"]), "data.id is a bare UUID"


class TestProfileOptimisticConcurrency:
    def test_occ_patch_member_stale_version(self, api):
        """PRD §2.6: "Updating a member profile (`PATCH
        /dog-park/members/{memberId}`) requires `expected_member_version` as a
        non-optional input carrying the client's last-observed `version` of the
        Member; if the member's current `version` no longer matches, the update
        is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client never
        silently overwrites profile fields it never saw."
        PRD §3.1: "A member — or an administrator on their behalf — updates
        `full_name`, `email`, or `phone` through the OCC-guarded profile
        capability (§2.6), which increments the member's `version` by one on
        success."

        Design: Corner/cross_cutting_complexity_layers/occ_patch_member_stale_version
        """
        member = register_member(full_name="Own Er", email="owner@x.com")
        headers = make_member_headers(member["id"])
        assert member["version"] == 1

        first = validate_success(api.patch_member(
            member["id"],
            patch_member_payload(1, full_name="Owner Renamed"),
            headers,
        ))
        assert first["full_name"] == "Owner Renamed"
        assert first["version"] == 2, "version increments by one on success"

        stale = api.patch_member(
            member["id"],
            patch_member_payload(1, full_name="Stale Writer"),
            headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = get_member(member["id"])
        assert after["full_name"] == "Owner Renamed", (
            "the rejected replay never overwrites the profile"
        )


class TestAuthContext:
    def test_missing_user_context_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside these four, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_x_user_id_header_returns_400
        """
        resp = api.list_areas({})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_anonymous_role_cannot_list_visits(self, api):
        """PRD §2.1: "When `X-User-Role` is `Anonymous`, `X-User-ID` is an
        opaque registrant identifier not tied to any persisted entity; the
        server does not compare it to any entity's `id`, and the role carries
        exactly one capability — registering a new member account."
        PRD §2.1: "A request whose role is not listed among the endpoint's
        authorized roles is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/validations/anonymous_cannot_list_visits
        """
        resp = api.list_visits(ANON)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_member_cannot_read_other_member(self, api):
        """PRD §3.1: "Member-role callers may touch only their own record, with
        `ERR_NOT_OWNER` greeting any attempt on another's; reads of a member
        record follow the same self-only rule for the `Member` role, while
        `Steward` and `ParkAdmin` callers read freely."
        PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of
        the acting Member; ownership checks on any resource that references a
        Member — a dog's `member_id`, a membership's `member_id`, a guest
        pass's `sponsor_member_id`, a visit's `member_id` — compare the
        resource's foreign-key field to `X-User-ID`, and a mismatch is rejected
        with `ERR_NOT_OWNER` (HTTP 403)."

        Design: Corner/validations/member_cannot_read_other_member
        """
        m1 = register_member(full_name="M One", email="m1@x.com")
        m2 = register_member(full_name="M Two", email="m2@x.com")
        resp = api.get_member(m2["id"], make_member_headers(m1["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_OWNER)
