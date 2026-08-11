"""List pagination defaults, response envelope, and anonymous access."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_member_payload,
    create_range_session_payload,
    set_clock,
    validate_error,
    validate_paginated,
)

ANONYMOUS = TEST_USERS["anonymous_headers"]
RANGE_OFFICER = TEST_USERS["range_officer_headers"]


class TestMemberListPagination:
    def test_member_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` defaults to 10, with a minimum of 1 and a
        maximum of 100; the `offset` defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`, where
        `total_count` is the full count of matching resources and `has_more`
        indicates whether further pages exist beyond the returned window."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601
        UTC timestamp with three fractional digits."

        Design: Corner/endpoints/member_list_pagination_defaults
        """
        set_clock("2026-05-01T08:00:00Z")
        for i in range(1, 13):
            resp = api.create_member(
                create_member_payload(
                    email=f"p{i:02d}@x.com", full_name=f"Member {i:02d}"
                ),
                ANONYMOUS,
            )
            assert resp.status_code == 201, f"Setup failed (member {i})"

        first_page = api.list_members(RANGE_OFFICER)
        data1, meta1 = validate_paginated(first_page)
        assert len(data1) == 10
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        body = first_page.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        second_page = api.list_members(RANGE_OFFICER, params={"offset": 10})
        data2, meta2 = validate_paginated(second_page)
        assert len(data2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestAnonymousAccess:
    def test_anonymous_cannot_book_session(self, api):
        """PRD §2.1: "An unauthenticated caller participates as `Anonymous`: it
        may register a new member and may read the public resources (lanes,
        coaches, leagues, standings, and pro-shop products), and nothing else."
        PRD §2.1: "A role attempting an operation outside its grant is rejected
        with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/anonymous_cannot_book_session
        """
        resp = api.create_range_session(
            create_range_session_payload(
                "00000000-0000-4000-8000-000000000000", "WALK_IN",
                "2026-05-01T10:00:00Z", "2026-05-01T11:00:00Z",
            ),
            ANONYMOUS,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
