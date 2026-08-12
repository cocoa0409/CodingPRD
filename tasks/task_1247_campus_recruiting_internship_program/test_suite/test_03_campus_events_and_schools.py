"""Campus events, school target list, overlap rules, drop cascade."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    make_recruiter_headers,
    create_campus_event_payload, create_school_target_payload,
)
from test_helpers import fixtures as fx

RECRUITER = make_recruiter_headers()


class TestSchoolTargetCrud:
    def test_school_target_invalid_enum_rejected(self, api, admin_headers):
        """PRD §2.11: "(5) request body shape — required fields present, types
        valid, enum members recognized, and ranges honored (interview scores
        and intern ratings are integers between 1 and 5 inclusive; capacities
        and hour fields are at least 1; cent amounts are at least 0 with the
        weekly pay rate strictly positive; an interval's end is strictly later
        than its start; relocation distance and prior-internship counts are at
        least 0), with violations rejected as `ERR_VALIDATION` (HTTP 400)".
        PRD §3.1: each target declares "a `tier` of `CORE`, `TARGET`, or
        `EXPLORATORY`".

        Design: Corner/entities/school_target_invalid_enum_rejected
        """
        season = fx.create_season(shortlist_score_threshold=50)
        resp = api.create_school_target(
            season["id"],
            create_school_target_payload(tier="IVY"),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_school_targets_list_pagination(self, api, admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of returned items;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the start of the
        result set and defaults to 0. Unless otherwise specified, every list
        endpoint returns resources sorted by their creation timestamp in
        ascending order. The `meta` object of a list response includes
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/school_targets_list_pagination
        """
        season = fx.create_season(shortlist_score_threshold=50)
        fx.create_school(
            season["id"], school_name="StateU", tier="CORE",
            stipend_region="METRO",
        )
        fx.create_school(
            season["id"], school_name="TechU", tier="TARGET",
            stipend_region="REGIONAL",
        )
        fx.create_school(
            season["id"], school_name="CityU", tier="EXPLORATORY",
            stipend_region="REMOTE",
        )
        resp1 = api.list_school_targets(
            season["id"], RECRUITER, params={"limit": 2, "offset": 0},
        )
        page1, meta1 = validate_paginated(resp1)
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2
        resp2 = api.list_school_targets(
            season["id"], RECRUITER, params={"limit": 2, "offset": 2},
        )
        page2, meta2 = validate_paginated(resp2)
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1


class TestCampusEventOverlap:
    def test_event_half_open_touching_boundary_allowed(self, api):
        """PRD §3.2: "Two events that merely touch — one ending at exactly the
        instant the other begins — do not intersect and are allowed".

        Design: Difficulty/resource_temporal_overlap/event_half_open_adjacency_allowed
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])  # OPEN
        resp1 = api.create_campus_event(
            season["id"],
            create_campus_event_payload(
                school_target_id=school["id"], event_type="INFO_SESSION",
                start_at="2026-05-12T10:00:00Z", end_at="2026-05-12T12:00:00Z",
            ),
            RECRUITER,
        )
        assert validate_success(resp1, expected_status=201)["status"] == "SCHEDULED"
        resp2 = api.create_campus_event(
            season["id"],
            create_campus_event_payload(
                school_target_id=school["id"], event_type="CAREER_FAIR",
                start_at="2026-05-12T12:00:00Z", end_at="2026-05-12T14:00:00Z",
            ),
            RECRUITER,
        )
        assert validate_success(resp2, expected_status=201)["status"] == "SCHEDULED"

    def test_event_one_second_overlap_rejected(self, api):
        """PRD §3.2: "a new event is rejected with `ERR_EVENT_TIME_OVERLAP`
        (HTTP 409) when its interval intersects any existing event of the same
        school target in `SCHEDULED` or `COMPLETED` status".

        Design: Difficulty/resource_temporal_overlap/event_half_open_adjacency_allowed
        """
        season = fx.create_season()
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        resp1 = api.create_campus_event(
            season["id"],
            create_campus_event_payload(
                school_target_id=school["id"], event_type="INFO_SESSION",
                start_at="2026-05-12T10:00:00Z", end_at="2026-05-12T12:00:00Z",
            ),
            RECRUITER,
        )
        assert resp1.status_code == 201
        resp = api.create_campus_event(
            season["id"],
            create_campus_event_payload(
                school_target_id=school["id"], event_type="RESUME_DROP",
                start_at="2026-05-12T11:59:59Z", end_at="2026-05-12T13:00:00Z",
            ),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_TIME_OVERLAP)


class TestCampusEventLifecycle:
    def test_event_complete_records_resumes_and_locks(self, api):
        """PRD §3.2: "marking it complete moves it `SCHEDULED → COMPLETED` and
        records the number of resumes collected from the payload's
        `resume_count` (a count of at least 0, defaulting to 0 before
        completion)". PRD §3.2: "acting on an already-terminal event is
        rejected with `ERR_EVENT_STATE_FORBIDDEN` (HTTP 409)".

        Design: Corner/state_machines/event_complete_records_resumes_and_locks
        """
        season = fx.create_season(shortlist_score_threshold=50)
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        resp = api.create_campus_event(
            season["id"],
            create_campus_event_payload(school_target_id=school["id"]),
            RECRUITER,
        )
        event = validate_success(resp, expected_status=201)
        resp = api.complete_campus_event(event["id"], 42, RECRUITER)
        data = validate_success(resp)
        assert data["status"] == "COMPLETED"
        assert data["resume_count"] == 42
        resp = api.complete_campus_event(event["id"], 1, RECRUITER)
        validate_error(resp, ApiErrorId.ERR_EVENT_STATE_FORBIDDEN)


class TestSchoolDrop:
    def test_school_drop_cascades_events(self, api, admin_headers):
        """PRD §3.1: "The drop cascades: every campus event of that school
        still in `SCHEDULED` status is cancelled."

        Design: Corner/state_machines/school_drop_cascades_events
        """
        season = fx.create_season(shortlist_score_threshold=50)
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        resp = api.create_campus_event(
            season["id"],
            create_campus_event_payload(
                school_target_id=school["id"], event_type="INFO_SESSION",
            ),
            RECRUITER,
        )
        event = validate_success(resp, expected_status=201)
        resp = api.drop_school_target(school["id"], admin_headers)
        assert validate_success(resp)["status"] == "DROPPED"
        event_after = validate_success(api.get_campus_event(event["id"], RECRUITER))
        assert event_after["status"] == "CANCELLED"

    def test_dropped_school_blocks_application(self, api, admin_headers):
        """PRD §3.2: "the referenced school target must still be `ACTIVE`;
        scheduling against a dropped school is rejected with
        `ERR_SCHOOL_DROPPED` (HTTP 422)"; PRD §3.3 lists "the referenced school
        must still be `ACTIVE` (`ERR_SCHOOL_DROPPED`)" among the submission
        guards.

        Design: Corner/state_machines/dropped_school_blocks_application
        """
        season = fx.create_season(shortlist_score_threshold=50)
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])  # OPEN
        resp = api.drop_school_target(school["id"], admin_headers)
        assert resp.status_code == 200
        fx.set_clock("2026-05-15T00:00:00Z")
        candidate = fx.create_candidate()
        from test_helpers import make_candidate_headers, create_application_payload
        resp = api.create_application(
            season["id"],
            create_application_payload(
                candidate_id=candidate["id"], school_target_id=school["id"],
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_DROPPED)

    def test_dropped_school_blocks_event_scheduling(self, api, admin_headers):
        """PRD §3.2: "the referenced school target must still be `ACTIVE`;
        scheduling against a dropped school is rejected with
        `ERR_SCHOOL_DROPPED` (HTTP 422)".

        Design: Corner/state_machines/dropped_school_blocks_application
        """
        season = fx.create_season(shortlist_score_threshold=50)
        school = fx.create_school(season["id"])
        fx.advance_season(season["id"])
        resp = api.drop_school_target(school["id"], admin_headers)
        assert resp.status_code == 200
        resp = api.create_campus_event(
            season["id"],
            create_campus_event_payload(school_target_id=school["id"]),
            RECRUITER,
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_DROPPED)
