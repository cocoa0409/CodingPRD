"""Season/member/section creation defaults, request shape, uniqueness, pagination."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_member,
    assert_season,
    create_member_payload,
    create_open_season_with_section,
    create_season,
    create_section,
    create_section_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSeasonCreationDefaults:
    def test_season_creation_applies_system_defaults(self, api,
                                                     president_headers):
        """PRD §3.1: "A new season is born in `DRAFT` posture with
        `ops_week_index` at 0, `pool_available_cents` equal to
        `scholarship_pool_cents`, `pool_reserved_cents` and `pool_spent_cents`
        at zero, and an empty treasury."
        PRD §3.1: "Two policy knobs are optional: `audition_slot_minutes`, the
        fixed audition slot length defaulting to 30, and `attendance_threshold`,
        the minimum attendance rate for performance eligibility defaulting to
        0.75."

        Design: Corner/entities/season_creation_applies_system_defaults
        """
        season = create_season()
        assert_season(season)
        assert season["posture"] == "DRAFT"
        assert season["ops_week_index"] == 0
        assert season["pool_available_cents"] == 50000
        assert season["pool_reserved_cents"] == 0
        assert season["pool_spent_cents"] == 0
        assert season["treasury_balance_cents"] == 0
        assert season["audition_slot_minutes"] == 30, \
            "audition_slot_minutes defaults to 30"
        assert season["attendance_threshold"] == 0.75, \
            "attendance_threshold defaults to 0.75"
        assert isinstance(season["version"], int), \
            "version is a system-managed integer"

        fetched = validate_success(
            api.get_season(season["id"], president_headers))
        assert fetched["posture"] == "DRAFT"
        assert fetched["pool_available_cents"] == 50000
        assert fetched["treasury_balance_cents"] == 0
        assert is_valid_uuid(fetched["id"])


class TestMemberCreation:
    def test_member_create_initial_state_and_computed_defaults(
            self, api, director_headers):
        """PRD §3.2: "A new member starts as an `APPLICANT` with
        `attendance_rate` at 1.0, `performance_eligible` false, and no
        `section_id`."
        PRD §3.4: "a member's `dues_balance_cents` is the sum of
        `balance_cents` over their invoices that have not reached a terminal
        state."
        PRD §3.5: "A member's `ledger_balance_cents` accumulates exactly these
        library charges; a positive value means the member owes."

        Design: Corner/entities/member_create_initial_state_and_computed_defaults
        """
        season, _section = create_open_season_with_section()
        resp = api.create_member(
            create_member_payload(season["id"], "Ada", "ada@x.org"),
            director_headers,
        )
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["status"] == "APPLICANT"
        assert member["attendance_rate"] == 1.0
        assert member["performance_eligible"] is False
        assert member["section_id"] is None
        assert member["dues_balance_cents"] == 0
        assert member["ledger_balance_cents"] == 0

    def test_member_create_computed_field_input_ignored(self, api,
                                                        director_headers):
        """PRD §2.8: "Fifth, request shape: missing required fields, wrong
        types, and unknown fields are rejected with `ERR_INVALID_REQUEST`, and
        an enum field carrying an undeclared value is rejected with
        `ERR_INVALID_ENUM`."

        Design: Corner/entities/member_create_computed_field_input_ignored
        """
        season, _section = create_open_season_with_section()
        payload = create_member_payload(season["id"], "Ada", "ada@x.org")
        payload["attendance_rate"] = 0.1  # computed field, not an input
        resp = api.create_member(payload, director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_member_get_nonexistent_id_returns_not_found(self, api,
                                                         president_headers):
        """PRD §2.8: "Fourth, existence: resource ids appearing in the path and
        in the body are validated left to right, and the first id that does not
        resolve to an existing resource yields `ERR_NOT_FOUND`."

        Design: Corner/entities/member_get_nonexistent_id_returns_not_found
        """
        resp = api.get_member(NON_EXISTENT_UUID, president_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSectionCreation:
    def test_section_create_missing_required_returns_invalid_request(
            self, api, director_headers):
        """PRD §3.1: "Sections themselves are managed by the `ChoirDirector`,
        who creates one per voice part with a `season_id`, a `voice_part` of
        `SOPRANO`, `ALTO`, `TENOR`, or `BASS`, and the staffing targets
        `target_min` and `target_max`."
        PRD §2.8: "Fifth, request shape: missing required fields, wrong types,
        and unknown fields are rejected with `ERR_INVALID_REQUEST`"

        Design: Corner/entities/section_create_missing_required_returns_invalid_request
        """
        season = create_season()
        payload = create_section_payload(season["id"], "ALTO", 1)
        del payload["target_max"]
        resp = api.create_section(payload, director_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_section_create_invalid_enum_returns_invalid_enum(
            self, api, director_headers):
        """PRD §3.1: "a `voice_part` of `SOPRANO`, `ALTO`, `TENOR`, or `BASS`"
        PRD §2.8: "an enum field carrying an undeclared value is rejected with
        `ERR_INVALID_ENUM`."

        Design: Corner/entities/section_create_invalid_enum_returns_invalid_enum
        """
        season = create_season()
        resp = api.create_section(
            create_section_payload(season["id"], "SOPRANINO", 1, 2),
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)

    def test_duplicate_voice_part_returns_duplicate_section(
            self, api, director_headers):
        """PRD §3.1: "The same voice part may not be created twice within a
        season — the duplicate is rejected with `ERR_DUPLICATE_SECTION`."

        Design: Corner/entities/duplicate_voice_part_returns_duplicate_section
        """
        season = create_season()
        create_section(season["id"], "SOPRANO", 1, 2)
        resp = api.create_section(
            create_section_payload(season["id"], "SOPRANO", 1, 3),
            director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SECTION)


class TestMemberUniqueness:
    def test_duplicate_email_returns_duplicate_membership(self, api,
                                                          director_headers):
        """PRD §3.2: "The email must be unique among members of that season; a
        duplicate registration is rejected with `ERR_DUPLICATE_MEMBERSHIP`."

        Design: Corner/entities/duplicate_email_returns_duplicate_membership
        """
        season, _section = create_open_season_with_section()
        resp1 = api.create_member(
            create_member_payload(season["id"], "Ada", "ada@x.org"),
            director_headers,
        )
        validate_success(resp1, 201)
        resp2 = api.create_member(
            create_member_payload(season["id"], "Ada Clone", "ada@x.org"),
            director_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_MEMBERSHIP)


class TestMemberListPagination:
    def test_members_list_pagination_envelope(self, api, president_headers,
                                              director_headers):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items skipped and defaults to 0. Unless otherwise
        specified, list endpoints return resources sorted by `created_at` in
        ascending order. The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/members_list_pagination_envelope
        """
        season, _section = create_open_season_with_section()
        for name, email in (("A", "a@x.org"), ("B", "b@x.org"),
                            ("C", "c@x.org")):
            resp = api.create_member(
                create_member_payload(season["id"], name, email),
                director_headers,
            )
            validate_success(resp, 201)

        page1, meta1 = validate_paginated(api.list_members(
            president_headers, params={"season_id": season["id"], "limit": 2}))
        assert len(page1) == 2, "limit=2 returns 2 items"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_members(
            president_headers,
            params={"season_id": season["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1, "offset=2 skips the first page, 1 item remains"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

        ids = {m["id"] for m in page1} | {m["id"] for m in page2}
        assert len(ids) == 3, "Pages partition the collection without overlap"
