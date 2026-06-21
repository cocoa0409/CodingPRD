"""Resource creation contracts, existence/validation errors, invalid transitions,
session-close sweep, pagination envelope, and role-based access control
(PRD §2.1, §2.3, §2.5, §3.1)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    build_user_headers, make_candidate_headers,
    fixtures, factories,
)

ADMIN = TEST_USERS["test_center_admin_headers"]
REVIEWER = TEST_USERS["accommodation_reviewer_headers"]
SCORE_OPS = TEST_USERS["score_ops_headers"]


class TestCreationAndFields:
    def test_create_test_center_returns_201_with_fields(self, api):
        """PRD §3.1: "A freshly created center has its net_revenue_cents ledger
        initialized to zero." PRD §3.1: "A TestCenterAdmin creates a test center by
        supplying its display name, the two-letter US state_code where it
        physically sits (such as CA or NY), and the seat capacities of its two
        rooms: room_capacity_standard for the main room and
        room_capacity_accommodated for the separate extended-time room."

        Design: Corner/entities/create_test_center_returns_201_with_fields
        """
        resp = api.create_test_center(
            factories.create_test_center_payload(name="Bay Center", state_code="CA",
                                                 room_capacity_standard=50, room_capacity_accommodated=5),
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert data["net_revenue_cents"] == 0
        assert data["state_code"] == "CA"

    def test_registration_system_fields_generated(self, api):
        """PRD §3.3: "A successful reservation lands the registration in lifecycle
        status RESERVED and score status PENDING, with seat_kind defaulting to
        STANDARD, drawing the seat from the standard pool: standard_seats_reserved
        is increased by one and the session version is incremented." PRD §2.4:
        "an integer version that begins at 1 and increments by one on each
        mutation."

        Design: Corner/entities/registration_system_fields_generated
        """
        center = fixtures.create_center()
        cand = fixtures.create_candidate()
        session = fixtures.create_session(center["id"])
        resp = api.create_registration(
            factories.create_registration_payload(session["id"], cand["id"], session["version"]),
            make_candidate_headers(cand["id"]),
        )
        reg = validate_success(resp, 201)
        assert reg["lifecycle_status"] == "RESERVED"
        assert reg["score_status"] == "PENDING"
        assert reg["seat_kind"] == "STANDARD"
        assert reg["version"] == 1


class TestExistenceAndValidation:
    def test_create_registration_missing_candidate_id_invalid_request(self, api):
        """PRD §2.5: "all required fields must be present, every enumerated field
        must carry a value inside its declared set, and every numeric field must
        fall within its accepted bounds. A malformed body — a missing required
        field, an out-of-range enum, or an out-of-bounds score — is rejected with
        ERR_INVALID_REQUEST."

        Design: Corner/entities/create_registration_missing_required_field_invalid_request
        """
        center = fixtures.create_center()
        session = fixtures.create_session(center["id"])
        resp = api.create_registration(
            {"test_session_id": session["id"], "expected_test_session_version": session["version"]},
            build_user_headers("missing-candidate-id", "Candidate"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_registration_nonexistent_id_not_found(self, api):
        """PRD §2.5: "the first identifier that does not resolve to a stored
        resource causes the request to be rejected with ERR_NOT_FOUND before any
        later identifier is examined."

        Design: Corner/entities/get_registration_nonexistent_id_not_found
        """
        resp = api.get_registration(NON_EXISTENT_UUID, TEST_USERS["candidate_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_invalid_enum_exam_type_rejected(self, api):
        """PRD §2.5: "A malformed body — a missing required field, an out-of-range
        enum, or an out-of-bounds score — is rejected with ERR_INVALID_REQUEST."

        Design: Corner/entities/invalid_enum_exam_type_rejected
        """
        center = fixtures.create_center()
        resp = api.create_test_session(
            factories.create_test_session_payload(center["id"], exam_type="GRE"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_registration_wrong_parent_session_not_found(self, api):
        """PRD §2.5: "Before any business rule runs, the system confirms that every
        resource the request names actually exists. This covers both identifiers
        embedded in the URL path and foreign-key identifiers carried in the request
        body."

        Design: Corner/entities/registration_wrong_parent_session_not_found
        """
        center = fixtures.create_center(room_capacity_standard=5, room_capacity_accommodated=5)
        cand = fixtures.create_candidate()
        real_session = fixtures.create_session(center["id"])
        # Non-existent test_session_id, but carry the real session's version: existence
        # (priority 3) is checked before the OCC version check (priority 5).
        resp = api.create_registration(
            factories.create_registration_payload(
                "00000000-0000-4000-8000-000000000001", cand["id"], real_session["version"]),
            make_candidate_headers(cand["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestInvalidTransitionsAndClose:
    def test_confirm_from_cancelled_invalid_state(self, api):
        """PRD §3.3: "A reserved registration is advanced to CONFIRMED by the
        candidate, provided the registration is currently RESERVED and the host
        session's registration_status is still OPEN; otherwise the transition is
        rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/confirm_from_already_cancelled_invalid_state
        """
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center, candidate, session, reg = fixtures.create_reserved_registration()
        cid = candidate["id"]
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(cid)))
        resp = api.confirm_registration(reg["id"], make_candidate_headers(cid))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_session_close_sweeps_confirmed_to_no_show(self, api):
        """PRD §3.1: "every registration on the session that is CONFIRMED but was
        never CHECKED_IN is moved to NO_SHOW, and for each such forfeiture the
        matching seat pool is reduced by one — with no refund, since the seat is
        forfeited — and the session version is incremented once per release." PRD
        §3.1: "Closing flips registration_status to CLOSED, which blocks any further
        registrations."

        Design: Corner/state_machines/session_close_sweeps_confirmed_to_no_show
        """
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center, candidate, session, reg = fixtures.create_confirmed_registration(
            center_overrides={"room_capacity_standard": 5, "room_capacity_accommodated": 5},
        )
        fixtures.set_clock("2026-09-02T00:00:00.000Z")
        validate_success(api.close_test_session(session["id"], ADMIN))
        reg_after = get_success_data(api.get_registration(reg["id"], TEST_USERS["candidate_headers"]))
        assert reg_after["lifecycle_status"] == "NO_SHOW"
        assert reg_after["amount_refunded_cents"] == 0, "forfeited, no refund"
        sess_after = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert sess_after["registration_status"] == "CLOSED"


class TestPagination:
    def test_list_test_sessions_pagination_envelope(self, api):
        """PRD §2.3: "The limit parameter caps the number of items returned; when
        omitted it defaults to 10, and accepted values range from a minimum of 1 to
        a maximum of 100." PRD §2.3: "Each list response carries the pagination
        bookkeeping inside the meta object of the envelope: limit, offset,
        total_count, and has_more."

        Design: Corner/endpoints/list_test_sessions_pagination_envelope
        """
        center = fixtures.create_center()
        fixtures.create_session(center["id"], exam_type="SAT", test_date="2026-09-01",
                                window_start_utc="2026-09-01T13:00:00.000Z",
                                window_end_utc="2026-09-01T17:00:00.000Z")
        fixtures.create_session(center["id"], exam_type="ACT", test_date="2026-10-03",
                                window_start_utc="2026-10-03T13:00:00.000Z",
                                window_end_utc="2026-10-03T17:00:00.000Z", base_fee_cents=7000)
        resp = api.list_test_sessions(
            TEST_USERS["candidate_headers"],
            params={"test_center_id": center["id"], "limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestRBAC:
    def test_candidate_cannot_create_test_session(self, api):
        """PRD §2.1: "an operation attempted by a role that does not own it is
        rejected with ERR_UNAUTHORIZED." PRD §2.1: "A TestCenterAdmin is a center
        operator who owns test centers, test sessions, session close, on-site
        check-in, and identity verification."

        Design: Corner/rbac/candidate_cannot_create_test_session_unauthorized
        """
        center = fixtures.create_center()
        resp = api.create_test_session(
            factories.create_test_session_payload(center["id"]),
            build_user_headers("intruder", "Candidate"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_scoreops_cannot_approve_accommodation(self, api):
        """PRD §2.1: "An AccommodationReviewer owns the 504/IEP review queue —
        beginning review, requesting more information, approving, and denying
        accommodation requests." PRD §2.1: "an operation attempted by a role that
        does not own it is rejected with ERR_UNAUTHORIZED."

        Design: Corner/rbac/scoreops_cannot_approve_accommodation_unauthorized
        """
        center, candidate, session, reg, acc = fixtures.create_accommodation_under_review(
            "EXTENDED_TIME_50", "PLAN_504",
        )
        resp = api.approve_accommodation(acc["id"], SCORE_OPS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_unknown_role_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or if X-User-Role does not name
        a role the system recognizes, the request is rejected with
        ERR_UNAUTHENTICATED."

        Design: Corner/rbac/missing_headers_unauthenticated
        """
        resp = api.create_test_center(
            factories.create_test_center_payload(name="Ghost Center", room_capacity_standard=5,
                                                 room_capacity_accommodated=5),
            build_user_headers("x", "NotARole"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
