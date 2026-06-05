"""List filtering (FK reverse-reachability), pagination envelope, and role-based
access control."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_course_payload, create_handicap_revision_payload, create_booking_payload,
    make_proshop_headers, make_anonymous_headers, make_golfer_headers,
    create_course, create_golfer, create_tee_time, post_score, book_as_golfer,
    cancel_as_golfer, set_clock,
)


class TestListFiltering:
    def test_list_tee_times_filtered_by_course(self, api):
        """PRD §3.5: "Slots may be fetched individually or listed; the list view filters by
        course_id and by status."

        Design: Corner/endpoints/list_tee_times_filtered_by_course_fk_reverse
        """
        set_clock()
        ca = create_course(name="CrsA")
        cb = create_course(name="CrsB")
        create_tee_time(ca["id"], "2026-07-02T09:00:00Z", 9, "FOURSOME")
        resp = api.list_tee_times(make_anonymous_headers(), params={"course_id": ca["id"]})
        data, meta = validate_paginated(resp)
        assert all(tt["course_id"] == ca["id"] for tt in data)

    def test_list_bookings_filtered_by_golfer(self, api):
        """PRD §3.6: "Bookings may be fetched individually, listed across the system with
        optional golfer_id and status filters, or listed for a single slot with an optional
        status filter."

        Design: Corner/endpoints/list_bookings_filtered_by_golfer_fk_reverse
        """
        set_clock()
        course = create_course(name="BkFkCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-07-03T09:00:00Z", 9, "FOURSOME")
        book_as_golfer(tt["id"], ga["id"], tt["version"])
        resp = api.list_bookings(make_proshop_headers(), params={"golfer_id": ga["id"]})
        data, meta = validate_paginated(resp)
        assert all(bk["golfer_id"] == ga["id"] for bk in data)

    def test_list_scores_filtered_by_golfer(self, api):
        """PRD §3.2: "the list view accepts a golfer_id filter to see one golfer's rounds and
        a course_id filter to see rounds played on a given course."

        Design: Corner/endpoints/list_scores_filtered_by_golfer_fk_reverse
        """
        course = create_course(name="ScFkCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        post_score(ga["id"], course["id"], "2026-05-01", 85)
        resp = api.list_scores(make_proshop_headers(), params={"golfer_id": ga["id"]})
        data, meta = validate_paginated(resp)
        assert all(s["golfer_id"] == ga["id"] for s in data)

    def test_list_bookings_on_slot_subresource(self, api):
        """PRD §3.6: "or listed for a single slot with an optional status filter."

        Design: Corner/endpoints/list_bookings_on_slot_subresource
        """
        set_clock()
        course = create_course(name="SubCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-07-04T09:00:00Z", 9, "FOURSOME")
        book_as_golfer(tt["id"], ga["id"], tt["version"])
        resp = api.list_slot_bookings(tt["id"], make_proshop_headers())
        data, meta = validate_paginated(resp)
        assert all(bk["tee_time_id"] == tt["id"] for bk in data)


class TestPagination:
    def test_list_courses_pagination_envelope(self, api):
        """PRD §2.3: "The limit parameter caps how many items a single response returns ... The
        meta object of every list response carries limit, offset, total_count, and has_more."

        Design: Corner/endpoints/list_courses_pagination_envelope
        """
        create_course(name="P1")
        create_course(name="P2")
        resp = api.list_courses(make_anonymous_headers(), params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


class TestRoleAccessControl:
    def test_golfer_cannot_create_course(self, api):
        """PRD §2.1: "When a caller presents valid headers but the role is not permitted for
        the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/golfer_cannot_create_course
        """
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        resp = api.create_course(create_course_payload(name="Sneaky"), make_golfer_headers(ga["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_golfer_cannot_run_handicap_revision(self, api):
        """PRD §2.1: "When a caller presents valid headers but the role is not permitted for
        the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/golfer_cannot_run_handicap_revision
        """
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        resp = api.create_handicap_revision(
            create_handicap_revision_payload("2026-03-31T00:00:00Z"), make_golfer_headers(ga["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or X-User-Role is not one of these three
        known roles, the request is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        course = create_course(name="AuthCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        # POST /golf/scores is a non-anonymous endpoint; send no auth headers.
        resp = api._request(
            "POST", "/golf/scores",
            {"golfer_id": ga["id"], "course_id": course["id"],
             "played_on": "2026-05-01", "adjusted_gross_score": 85},
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_proshop_can_cancel_any_golfers_booking(self, api):
        """PRD §2.1: "When X-User-Role is ProShop, X-User-ID is an opaque operator identifier
        not tied to any persisted entity; the server does not compare it to any entity's id,
        and a ProShop operator may act on any golfer's bookings or scores."

        Design: Corner/rbac/proshop_can_cancel_any_golfers_booking
        """
        set_clock()
        course = create_course(name="PsCrs")
        ga = create_golfer(full_name="GA", membership_tier="PUBLIC")
        tt = create_tee_time(course["id"], "2026-07-05T09:00:00Z", 9, "FOURSOME")
        bk = book_as_golfer(tt["id"], ga["id"], tt["version"])
        resp = api.cancel_booking(bk["id"], make_proshop_headers())
        booking = validate_success(resp, 200)
        assert booking["status"] == "CANCELLED"
