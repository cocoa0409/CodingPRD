"""Entity CRUD: member registration defaults, not-found, pagination,
required-field rejection, enum constraints, FK reverse-reachability."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    create_property,
    create_member,
    NON_EXISTENT_UUID,
    ApiErrorId,
    make_member_services_headers,
    make_loyalty_manager_headers,
)


class TestMemberCreation:
    """PRD §3.1: a fresh Member is created with all default state values."""

    def test_create_member_returns_201_with_default_state(self, api):
        """PRD §3.1: "On success, the row is created with tier_status GOLD,
        tier_credits_ytd zero, tier_credits_lifetime zero, exclusion_status
        NOT_EXCLUDED, velocity_status NORMAL, assigned_host_id null, and
        version 1."

        Design: Corner/entities/member_create_with_required_fields_returns_201
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        resp = api.create_member(
            {
                "full_name": "Alice K",
                "email": "alicek@x.com",
                "home_property_id": prop["id"],
            },
            make_member_services_headers("ms_1"),
        )
        data = validate_success(resp, expected_status=201)
        assert data["tier_status"] == "GOLD"
        assert data["tier_credits_ytd"] == pytest.approx(0, abs=0.01)
        assert data["tier_credits_lifetime"] == pytest.approx(0, abs=0.01)
        assert data["exclusion_status"] == "NOT_EXCLUDED"
        assert data["velocity_status"] == "NORMAL"
        assert data["assigned_host_id"] is None
        assert data["version"] == 1


class TestMemberNotFound:
    """PRD §2.4 + §2.10: unknown path-segment ids resolve to ERR_NOT_FOUND."""

    def test_get_member_by_unknown_id_returns_404(self, api):
        """PRD §2.4: "Path-segment ids are validated strictly left to right.
        For a nested path of the shape /parents/{parent_id}/children/{child_id},
        the server first verifies that parent_id resolves to an existing
        parent row, and only then that child_id resolves to a child whose
        parent_id matches; either failure surfaces as ERR_NOT_FOUND
        (HTTP 404)."

        Design: Corner/entities/member_get_by_unknown_id_returns_404
        """
        set_clock("2026-02-01T00:00:00Z")
        resp = api.get_member(
            NON_EXISTENT_UUID, make_member_services_headers("ms_1"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestMemberListing:
    """PRD §2.3: list endpoints return a paginated envelope with
    limit/offset/total_count/has_more."""

    def test_list_members_returns_pagination_envelope(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters: limit
        (default 10, minimum 1, maximum 100) and offset (default 0,
        minimum 0). The four pagination fields exposed in meta are limit,
        offset, total_count, and has_more; has_more is true when more rows
        exist beyond the returned page and false otherwise."

        Design: Corner/entities/member_list_returns_pagination_envelope
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        create_member(
            property_id=prop["id"], full_name="P", email="p@x.com",
        )
        resp = api.list_members(make_member_services_headers("ms_1"))
        items, meta = validate_paginated(resp)
        assert meta["total_count"] >= 1
        assert isinstance(meta["has_more"], bool)


class TestMemberCreateValidationErrors:
    """PRD: required body fields must be supplied; missing ones return 400."""

    def test_create_member_missing_email_returns_400(self, api):
        """PRD §3.1: "A new member enters the system through a
        MemberServices registration, which carries the prospective
        member's full_name, their email, and the home_property_id of the
        property at which they are enrolling."

        Design: Corner/entities/member_create_missing_email_returns_400
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        resp = api.create_member(
            {"full_name": "NoMail", "home_property_id": prop["id"]},
            make_member_services_headers("ms_1"),
        )
        assert resp.status_code == 400, (
            f"Missing required field 'email' must return 400, "
            f"got {resp.status_code}: {resp.text}"
        )


class TestGamingSessionEnumConstraint:
    """PRD §3.3: game_type is constrained to {SLOTS, TABLE_GAMES, POKER}."""

    def test_create_gaming_session_invalid_game_type_returns_400(self, api):
        """PRD §3.3: "the game_type (SLOTS, TABLE_GAMES, or POKER)".

        A value outside the allowed enum is a malformed request — 400.

        Design: Corner/entities/gaming_session_invalid_game_type_enum_rejected
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(property_id=prop["id"], email="g@x.com")
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-02-01T10:00:00Z",
                "ended_at": "2026-02-01T11:00:00Z",
                "game_type": "BACCARAT",
                "theoretical_loss_cents": 10000,
            },
            make_member_services_headers("ms_1"),
        )
        assert resp.status_code == 400, (
            f"Invalid game_type enum value must return 400, "
            f"got {resp.status_code}: {resp.text}"
        )


class TestPropertyMemberReverseReachability:
    """PRD §3.1: GET /properties/{id}/members returns members whose
    home_property_id matches the path id."""

    def test_property_members_listing_returns_all_assigned_members(self, api):
        """PRD §3.1: "A reverse-reachability query exposes the members
        whose home_property_id matches a given property's id."

        Design: Corner/entities/property_get_member_fk_reverse_reachability
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        create_member(property_id=prop["id"], full_name="P1", email="p1@x.com")
        create_member(property_id=prop["id"], full_name="P2", email="p2@x.com")
        resp = api.list_property_members(
            prop["id"], make_member_services_headers("ms_1"),
        )
        items, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, (
            f"Expected 2 members for property, got {meta['total_count']}"
        )
