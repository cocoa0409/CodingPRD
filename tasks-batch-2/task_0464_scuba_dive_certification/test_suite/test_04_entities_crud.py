"""Entity CRUD breadth: creation defaults, retrieval, listing/pagination,
not-found, required fields, defaults, computed fields, system fields, type
constraints, immutability, parent relationships, FK-filtered listing.

Queue B (Corner): section entities.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_iso8601_timestamp,
    make_shop_admin_headers, make_instructor_headers,
    create_diver, create_course, create_instructor, create_enrollment,
    set_clock, certify_diver_open_water,
)
from test_helpers import factories as f
from test_helpers import ApiErrorId

ADMIN = make_shop_admin_headers()


class TestDiverCrud:
    def test_create_diver_returns_201_with_defaults(self, api):
        """PRD 3.1: "A newly registered diver starts with `cert_level` equal to
        `NONE`, `nitrox_certified` false, `medical_status` `UNKNOWN`, and
        `deposit_on_hold_cents` zero — none of which the registrant supplies; they
        are all system-initialized."

        Design: Corner/entities/create_diver_returns_201_with_defaults
        """
        data = validate_success(
            api.create_diver(f.create_diver_payload(full_name="Dee Fault"), ADMIN),
            expected_status=201,
        )
        assert data["cert_level"] == "NONE", data
        assert data["nitrox_certified"] is False, data
        assert data["medical_status"] == "UNKNOWN", data
        assert data["deposit_on_hold_cents"] == 0, data
        assert data["version"] == 1, data

    def test_get_diver_returns_stored_entity(self, api):
        """PRD 3.1: "A diver enters the system through registration, supplying a
        `full_name` and a contact `email` (unique per diver)."

        Design: Corner/entities/get_diver_returns_stored_entity
        """
        created = create_diver(full_name="Reed Get")
        fetched = validate_success(api.get_diver(created["id"], ADMIN))
        assert fetched["id"] == created["id"]
        assert fetched["full_name"] == "Reed Get", fetched

    def test_list_divers_paginated_envelope(self, api):
        """PRD 2.3: "The `meta` object of every list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where
        `total_count` is the number of resources matching the query before
        pagination is applied and `has_more` is true exactly when items remain
        beyond the current page."

        Design: Corner/entities/list_divers_paginated_envelope
        """
        create_diver(full_name="List A")
        create_diver(full_name="List B")
        data, meta = validate_paginated(api.list_divers(ADMIN, params={"limit": 1, "offset": 0}))
        assert meta["total_count"] == 2, meta
        assert meta["has_more"] is True, meta

    def test_get_diver_not_found(self, api):
        """PRD 2.9: "third, existence — every referenced resource, whether named in
        the URL path or in the request body, resolves to a real resource, with path
        and body references checked left to right (`ERR_NOT_FOUND`)".

        Design: Corner/entities/get_diver_not_found
        """
        resp = api.get_diver("00000000-0000-0000-0000-000000000000", ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)

    def test_diver_system_fields_generated(self, api):
        """PRD 2.4: "Each such resource has an `id` (a server-minted UUID with no
        type prefix), a `created_at` timestamp recording when it was first created
        (ISO 8601 UTC with three fractional digits) ... and a `version` integer
        that begins at its initial value on creation".

        Design: Corner/entities/diver_system_fields_generated
        """
        data = validate_success(
            api.create_diver(f.create_diver_payload(full_name="Sys Field"), ADMIN),
            expected_status=201,
        )
        assert data["version"] == 1, data
        assert is_iso8601_timestamp(data["created_at"]), data


class TestCourseCrud:
    def test_create_course_missing_required_field(self, api):
        """PRD 2.9: "fourth, request well-formedness — required fields are present,
        enum values are in range, and numeric fields satisfy their declared
        constraints (`ERR_INVALID_REQUEST`)".
        PRD 3.2: "A `Course` is created with a `title`, a `course_type`
        (`OPEN_WATER` for the entry-level program or `ADVANCED`)".

        Design: Corner/entities/create_course_missing_required_field
        """
        resp = api.create_course(
            {"title": "No Type", "required_pool_sessions": 0,
             "required_open_water_sessions": 1, "price_cents": 50000}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_course_grants_specialty_default_none(self, api):
        """PRD 3.2: "an optional `grants_specialty` that defaults to `NONE` and may
        instead be `ENRICHED_AIR`."

        Design: Corner/entities/course_grants_specialty_default_none
        """
        data = validate_success(
            api.create_course(
                {"title": "Plain OW", "course_type": "OPEN_WATER",
                 "required_pool_sessions": 0, "required_open_water_sessions": 1,
                 "price_cents": 50000}, ADMIN,
            ), expected_status=201,
        )
        assert data["grants_specialty"] == "NONE", data


class TestSessionComputedAndConstraints:
    def test_session_max_students_computed_from_ratio(self, api):
        """PRD 3.4: "For a `POOL` session, `max_students` is 8 plus 4 for each
        assistant."
        PRD 3.4: "The session's `max_students` capacity is computed once at creation
        from the instructor ratio and is not recomputed afterward".

        Design: Corner/entities/session_computed_max_students_ignores_input
        """
        course = create_course(required_pool_sessions=1, required_open_water_sessions=1)
        instructor = create_instructor(full_name="Pool Pat")
        data = validate_success(
            api.create_session(
                f.create_session_payload(
                    course["id"], instructor["id"], session_type="POOL",
                    assistant_count=1,
                    starts_at="2026-07-10T08:00:00Z", ends_at="2026-07-10T10:00:00Z",
                ), ADMIN,
            ), expected_status=201,
        )
        assert data["max_students"] == 12, data  # 8 + 4*1

    def test_session_ends_before_starts_rejected(self, api):
        """PRD 3.4: "the session window as `starts_at` and `ends_at` (the end must
        be strictly after the start, or the request is malformed)".

        Design: Corner/entities/session_ends_before_starts_rejected
        """
        course = create_course()
        instructor = create_instructor(full_name="Order Inst")
        resp = api.create_session(
            f.create_session_payload(
                course["id"], instructor["id"], session_type="OPEN_WATER",
                starts_at="2026-07-01T12:00:00Z", ends_at="2026-07-01T11:00:00Z",
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestInstructorConstraints:
    def test_instructor_invalid_rating_enum(self, api):
        """PRD 3.2: "An `Instructor` is added by a `ShopAdmin` with a `full_name`
        and a professional `rating` of either `DIVEMASTER` or `INSTRUCTOR`."

        Design: Corner/entities/instructor_invalid_rating_enum
        """
        resp = api.create_instructor(
            {"full_name": "Bad Rating", "rating": "MASTER"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestCertificationCardImmutability:
    def test_certification_card_immutable_no_version(self, api):
        """PRD 2.4: "a `CertificationCard` and a `Waiver` are immutable once created
        and therefore carry only `id` and `created_at` — they have neither an
        `updated_at` field nor a `version` field."
        PRD 3.6: "a `level` mirroring the course's `course_type` (`OPEN_WATER` or
        `ADVANCED`), a `specialty` taken from the course's `grants_specialty`
        (`NONE` or `ENRICHED_AIR`)".

        Design: Corner/entities/certification_card_immutable_no_version
        """
        diver, course, enr, _card = certify_diver_open_water(diver_full_name="Card Carl")
        cards, meta = validate_paginated(
            api.list_certification_cards(ADMIN, params={"diver_id": diver["id"]})
        )
        assert len(cards) == 1, cards
        card = cards[0]
        assert card["level"] == "OPEN_WATER", card
        assert card["specialty"] == "NONE", card
        assert "version" not in card, card
        assert "updated_at" not in card, card


class TestEnrollmentParentRelationships:
    def test_enrollment_wrong_course_parent_not_found(self, api):
        """PRD 2.10: "The first reference that does not resolve to an existing
        resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404)
        for that reference, before the system attempts to validate anything that
        depends on it."

        Design: Corner/entities/enrollment_wrong_course_parent_not_found
        """
        diver = create_diver(full_name="Orphan Olive")
        resp = api.create_enrollment(
            {"diver_id": diver["id"],
             "course_id": "00000000-0000-0000-0000-000000000000"}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_list_enrollments_filtered_by_diver(self, api):
        """PRD 3.3: "Enrollments can be fetched individually or listed (optionally
        filtered by `diver_id` or `course_id`)."

        Design: Corner/entities/flat_fk_filtered_list_enrollment_by_diver
        """
        course = create_course()
        diver = create_diver(full_name="Filt Fran")
        enr = create_enrollment(diver["id"], course["id"])
        data, meta = validate_paginated(
            api.list_enrollments(ADMIN, params={"diver_id": diver["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert any(e["id"] == enr["id"] for e in data), data
