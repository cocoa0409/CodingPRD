"""Chapter chartering, retrieval, listing, filters, lifecycle guard rails,
authentication and authorization, and the chapter freeze."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_chapter,
    create_active_chapter,
    create_chapter,
    create_chapter_payload,
    create_member_payload,
    set_clock,
    suspend_chapter,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADVISOR = TEST_USERS["advisor_headers"]
DIRECTOR = TEST_USERS["director_headers"]
MEMBER = TEST_USERS["member_headers"]


class TestChapterCreation:
    def test_chapter_create_returns_201_with_initial_fields(self):
        """PRD section 3.1: "A freshly created chapter begins in `DRAFT` status
        with `standing` of `GOOD_STANDING`, a `fund_balance_cents` of zero,
        `dues_arrears_cents` of zero, an `active_member_count` of zero, and
        `version` 1."

        Design: Corner/entities/chapter_create_returns_201_with_initial_fields
        """
        set_clock()
        resp = api_client.create_chapter(create_chapter_payload(), DIRECTOR)
        data = validate_success(resp, expected_status=201)
        assert_chapter(data)
        assert data["status"] == "DRAFT"
        assert data["standing"] == "GOOD_STANDING"
        assert data["fund_balance_cents"] == 0
        assert data["dues_arrears_cents"] == 0
        assert data["active_member_count"] == 0
        assert data["version"] == 1

    def test_chapter_default_logical_clock_stamps_created_at(self):
        """PRD section 2.4: "Before any explicit adjustment, the logical clock
        reads `2026-08-01T00:00:00Z`."
        PRD section 2.4: "The server must not fall back to real wall-clock time
        under any circumstances."

        Design: Corner/endpoints/clock_default_is_2026_08_01
        """
        # No set_clock call: the default logical clock must drive created_at.
        resp = api_client.create_chapter(create_chapter_payload(), DIRECTOR)
        data = validate_success(resp, expected_status=201)
        assert data["created_at"].startswith("2026-08-01T00:00"), (
            f"created_at must reflect the default logical clock, got "
            f"{data['created_at']}"
        )


class TestChapterRetrieval:
    def test_chapter_get_by_id_returns_stored_entity(self):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field."
        PRD section 4: "GET | `/chapters/{chapterId}` | Fetch a chapter".

        Design: Corner/entities/chapter_get_by_id_returns_stored_entity
        """
        set_clock()
        chapter = create_chapter(school_name="Get High")
        resp = api_client.get_chapter(chapter["id"], ADVISOR)
        data = validate_success(resp)
        assert_chapter(data)
        assert data["id"] == chapter["id"]
        assert data["school_name"] == "Get High"
        assert data["version"] == 1

    def test_chapter_get_nonexistent_returns_404(self):
        """PRD section 2.6: "The first identifier that does not correspond to an
        existing resource — or that exists but is not nested under the
        previously resolved parent — terminates the request with
        `ERR_NOT_FOUND` (HTTP 404); the server never reports a deeper
        identifier's problem while a shallower one is unresolved."

        Design: Corner/entities/chapter_get_nonexistent_returns_404
        """
        set_clock()
        resp = api_client.get_chapter(NON_EXISTENT_UUID, ADVISOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestChapterListing:
    def test_chapter_list_returns_paginated_array(self):
        """PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/chapter_list_returns_paginated_array
        """
        set_clock()
        create_chapter(school_name="P1")
        create_chapter(school_name="P2")
        resp = api_client.list_chapters(ADVISOR, params={"limit": 10,
                                                         "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

    def test_chapter_list_filter_by_status(self):
        """PRD section 2.3: "A filter parameter restricts the result set to
        resources whose corresponding field equals the supplied value."

        Design: Corner/endpoints/chapter_list_filter_by_status
        """
        set_clock()
        active = create_active_chapter(school_name="A1")
        draft = create_chapter(school_name="A2")
        resp = api_client.list_chapters(ADVISOR, params={"status": "ACTIVE"})
        data, _meta = validate_paginated(resp)
        assert len(data) >= 1
        assert all(c["status"] == "ACTIVE" for c in data)
        ids = [c["id"] for c in data]
        assert active["id"] in ids
        assert draft["id"] not in ids


class TestChapterLifecycleGuards:
    def test_chapter_draft_to_dissolved_rejected(self):
        """PRD section 3.1: "Dissolution is the terminal act: a chapter may move
        from `ACTIVE` to `DISSOLVED` only when its `fund_balance_cents` is
        exactly zero, when every member has reached `ALUMNUS` or `DISMISSED`,
        and when no officer election remains in `DRAFT`, `OPEN`, or `TALLIED`."
        PRD section 2.6: "then the target resource's state-machine legality
        (`ERR_INVALID_STATE`, HTTP 409, raised whenever a transition is
        attempted from a state that does not permit it)."

        Design: Corner/state_machines/chapter_invalid_transition_draft_to_dissolved
        """
        set_clock()
        chapter = create_chapter()
        resp = api_client.dissolve_chapter(chapter["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_frozen_chapter_blocks_member_creation(self):
        """PRD section 2.7: "While a chapter is `SUSPENDED` or `DISSOLVED`,
        every mutating request nested under that chapter — any create or action
        endpoint below the chapter's path — is rejected with
        `ERR_CHAPTER_FROZEN` (HTTP 409)."

        Design: Corner/errors/err_chapter_frozen_on_suspended_chapter
        """
        set_clock()
        chapter = create_active_chapter()
        suspend_chapter(chapter["id"])
        resp = api_client.create_member(chapter["id"], create_member_payload(),
                                        ADVISOR)
        validate_error(resp, ApiErrorId.ERR_CHAPTER_FROZEN)


class TestAuthenticationAndAuthorization:
    def test_missing_role_header_rejected_unauthenticated(self):
        """PRD section 2.1: "A request whose `X-User-Role` header is missing or
        does not carry one of these four values, or whose `X-User-ID` header is
        missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/err_unauthenticated_missing_role_header
        """
        resp = api_client.create_chapter(
            create_chapter_payload(), {"X-User-ID": "someone-no-role"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_member_cannot_activate_chapter(self):
        """PRD section 2.1: "an authenticated caller attempting an operation
        outside their role is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "POST | `/chapters/{chapterId}/activate` | Activate a
        chapter | ActivitiesDirector".

        Design: Corner/errors/err_unauthorized_member_cannot_activate_chapter
        """
        set_clock()
        chapter = create_chapter()
        resp = api_client.activate_chapter(chapter["id"], MEMBER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
