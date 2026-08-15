"""Club creation, lookup, listing, and unauthenticated access."""
import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_club,
    create_club_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestClubCreation:
    def test_create_club_returns_201_and_system_defaults(self, api):
        """PRD §3.1: "A new club starts with `status` ACTIVE,
        `treasury_balance_cents` at zero, and `star_nomination_count` at zero."
        PRD §2.4: "Every resource carries an `id` — a server-minted UUID with no
        type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with
        three fractional digits recording when the resource was created."

        Design: Corner/entities/club_create_returns_201_and_system_fields
        """
        res = api.create_club(create_club_payload(name="Test Club", county_code="TC"), ADMIN)
        club = validate_success(res, 201)
        assert_club(club)
        assert club["name"] == "Test Club"
        assert club["county_code"] == "TC"
        assert club["status"] == "ACTIVE", f"new club must start ACTIVE, got {club['status']}"
        assert club["treasury_balance_cents"] == 0, (
            f"new club treasury must start at zero, got {club['treasury_balance_cents']}"
        )
        assert club["star_nomination_count"] == 0, (
            f"new club star count must start at zero, got {club['star_nomination_count']}"
        )

    def test_get_club_not_found_returns_404(self, api):
        """PRD §2.8: "The first identifier that does not resolve to an existing
        resource rejects the request with `ERR_NOT_FOUND` (HTTP 404), before any
        later identifier or any business rule is examined."

        Design: Corner/entities/club_get_not_found_returns_404
        """
        res = api.get_club(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, "ERR_NOT_FOUND")


class TestClubListing:
    def test_list_clubs_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_clubs_pagination_envelope
        """
        validate_success(api.create_club(create_club_payload(name="Pg Club 1", county_code="P1"), ADMIN), 201)
        validate_success(api.create_club(create_club_payload(name="Pg Club 2", county_code="P2"), ADMIN), 201)

        data, meta = validate_paginated(api.list_clubs(ADMIN))
        assert len(data) == 2, f"expected both clubs listed, got {len(data)}"
        assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
        assert meta["has_more"] is False
        for club in data:
            assert_club(club)


class TestAuthentication:
    def test_request_without_credentials_is_unauthenticated(self, api):
        """PRD §2.1: "A request that is missing either header, or whose
        `X-User-Role` value is not one of the three recognized roles, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_missing_headers
        """
        res = api.list_clubs(headers=NO_AUTH_HEADERS)
        validate_error(res, "ERR_UNAUTHENTICATED")

    @pytest.mark.parametrize("bad_role", ["SuperUser", "admin", "VOLUNTEER", ""])
    def test_unrecognized_role_is_unauthenticated(self, api, bad_role):
        """PRD §2.1: "A request that is missing either header, or whose
        `X-User-Role` value is not one of the three recognized roles, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_missing_headers
        """
        headers = {"X-User-ID": "whoever", "X-User-Role": bad_role, "Content-Type": "application/json"}
        res = api.list_clubs(headers=headers)
        validate_error(res, "ERR_UNAUTHENTICATED")
