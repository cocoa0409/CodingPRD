"""Member onboarding: creation defaults, envelope, not-found, pagination, auth."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_member,
    create_member_payload,
    get_success_data,
    is_valid_uuid,
    make_member_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMemberCreation:
    def test_create_member_returns_201_with_zeroed_balances(self, api, care_coordinator_headers):
        """PRD §3.1: "The new `Member` begins with `out_of_pocket_balance_cents` and
        `oop_accumulated_cents` at zero and `next_resupply_date` null, since no schedules
        exist yet."

        Design: Corner/entities/create_member_returns_201_with_defaults
        """
        res = api.create_member(
            create_member_payload(
                full_name="New Mem", email="new@x.com",
                date_of_birth="1990-01-01", shipping_address="1 Main St",
            ),
            care_coordinator_headers,
        )
        member = validate_success(res, 201)
        assert_member(member)
        assert member["out_of_pocket_balance_cents"] == 0
        assert member["oop_accumulated_cents"] == 0
        assert member["next_resupply_date"] is None

    def test_create_member_starts_with_no_active_schedules_and_version_one(
        self, api, care_coordinator_headers
    ):
        """PRD §2.10: "Two member-level aggregates are maintained continuously:
        `active_schedule_count` (the number of the member's resupply schedules currently
        `ACTIVE`) and `next_resupply_date` (the earliest `next_eligible_date` among those
        schedules, or null when none are `ACTIVE`)."
        PRD §2.4: "a `version` integer that starts at 1 on creation and increments by
        exactly 1 on every state transition, compensating action, cascade touch, or field
        mutation of that entity."

        Design: Corner/entities/create_member_returns_201_with_defaults
        """
        res = api.create_member(create_member_payload(email="v1@x.com"), care_coordinator_headers)
        member = validate_success(res, 201)
        assert member["active_schedule_count"] == 0
        assert member["version"] == 1


class TestMemberRead:
    def test_get_unknown_member_returns_not_found(self, api, care_coordinator_headers):
        """PRD §2.8: "path identifiers resolve left-to-right and every foreign-key
        reference in the body exists; failures surface the entity-specific not-found
        errors such as `ERR_MEMBER_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`".

        Design: Corner/entities/get_member_not_found_returns_404
        """
        res = api.get_member(NON_EXISTENT_UUID, care_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_MEMBER_NOT_FOUND, expected_status=404)

    def test_member_list_paginates_with_limit_and_offset(self, api, care_coordinator_headers):
        """PRD §2.3: "All list endpoints accept two query parameters: `limit` and `offset`."
        and "The `meta` block of a list response carries `limit`, `offset`, `total_count`,
        and `has_more` so the client can page deterministically through the full result set."

        Design: Corner/entities/member_list_pagination_limit_offset
        """
        api.create_member(create_member_payload(full_name="Pg A", email="pga@x.com"),
                          care_coordinator_headers)
        api.create_member(create_member_payload(full_name="Pg B", email="pgb@x.com"),
                          care_coordinator_headers)

        data, meta = validate_paginated(
            api.list_members(care_coordinator_headers, params={"limit": 1, "offset": 0})
        )
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_members(care_coordinator_headers, params={"limit": 1, "offset": 1})
        )
        assert len(data2) == 1
        assert meta2["has_more"] is False
        assert data2[0]["id"] != data[0]["id"]

    def test_client_supplied_id_and_version_are_ignored(self, api, care_coordinator_headers):
        """PRD §2.4: "Every persisted entity carries a server-minted `id` (a UUID with no
        type prefix)" and "a `version` integer that starts at 1 on creation".

        Design: Corner/entities/member_id_injection_input_ignored
        """
        res = api.create_member(
            create_member_payload(
                full_name="Inj Mem", email="inj@x.com",
                id="11111111-1111-1111-1111-111111111111", version=99,
            ),
            care_coordinator_headers,
        )
        member = validate_success(res, 201)
        assert member["id"] != "11111111-1111-1111-1111-111111111111"
        assert is_valid_uuid(member["id"])
        assert member["version"] == 1


class TestMemberAuth:
    def test_create_member_without_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role that is not one
        of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/create_member_missing_auth_header_returns_unauthenticated
        """
        res = api.create_member(
            create_member_payload(full_name="NoHdr", email="nohdr@x.com"),
            headers={},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_member_cannot_read_another_member(self, api, care_coordinator_headers):
        """PRD §2.1: "A `Member` attempting to act on a resource owned by a different
        member is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403); this applies to
        member-facing endpoints covering pump orders, resupply orders, warranty claims,
        and member-scoped reads of policies, prescriptions, claims, and schedules."

        Design: Corner/validations/member_cannot_read_other_member
        """
        member_a = get_success_data(
            api.create_member(create_member_payload(full_name="Own A", email="owa@x.com"),
                              care_coordinator_headers)
        )
        member_b = get_success_data(
            api.create_member(create_member_payload(full_name="Own B", email="owb@x.com"),
                              care_coordinator_headers)
        )
        res = api.get_member(member_b["id"], make_member_headers(member_a["id"]))
        validate_error(res, ApiErrorId.ERR_OWNERSHIP_VIOLATION, expected_status=403)
