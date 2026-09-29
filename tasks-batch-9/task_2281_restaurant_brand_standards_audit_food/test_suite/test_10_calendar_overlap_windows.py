"""Temporal occupancy: the auditor's buffered half-open interval and the location's quota."""
from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    audit_visit_payload,
    schedule_visit,
    setup_brand_program,
    setup_scheduled_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


def _candidate(program, start_at, end_at, visit_type="UNANNOUNCED"):
    return audit_visit_payload(
        program["location"]["id"], program["auditor"]["id"],
        program["rubric_version"]["id"], start_at, end_at, visit_type=visit_type,
    )


class TestAuditorTravelBuffer:
    def test_a_candidate_inside_the_travel_buffer_conflicts(self):
        """A booking that starts before the buffered predecessor ends is refused.

        PRD: "An auditor cannot be in two restaurants at once, and needs travel time between
        them."

        Design: Difficulty/resource_temporal_overlap/auditor_calendar_half_open_overlap_with_sixty_minute_travel_buffer
        """
        program = setup_scheduled_visit()

        validate_error(
            api_client.create_audit_visit(
                _candidate(program, "2026-08-05T13:00:00Z", "2026-08-05T15:00:00Z"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_AUDITOR_SCHEDULE_CONFLICT,
            expected_status=409,
        )

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 1

    def test_a_candidate_starting_at_the_buffer_edge_is_accepted(self):
        """Because the candidate interval is half-open, touching intervals do not conflict.

        PRD: "Because the candidate interval is half-open, a visit that begins exactly when
        the buffered predecessor interval ends does not conflict."

        Design: Difficulty/resource_temporal_overlap/auditor_calendar_half_open_overlap_with_sixty_minute_travel_buffer
        """
        program = setup_scheduled_visit()
        first_visit_id = program["visit"]["id"]

        created = validate_success(
            api_client.create_audit_visit(
                _candidate(program, "2026-08-05T14:00:00Z", "2026-08-05T16:00:00Z"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["auditor_id"] == program["auditor"]["id"]

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 2

        first = validate_success(api_client.get_audit_visit(first_visit_id, ADMIN_HEADERS))
        assert first["status"] == "SCHEDULED", "the earlier booking is untouched"


class TestLocationUnannouncedQuota:
    def test_a_third_unannounced_visit_inside_the_centred_window_is_refused(self):
        """The candidate itself counts toward the two-visit ceiling.

        PRD: "Counting the candidate itself, at most two non-voided `UNANNOUNCED` visits may
        have a `scheduled_start_at` inside that window; a third is rejected with
        `ERR_LOCATION_VISIT_WINDOW_QUOTA`."

        Design: Difficulty/resource_temporal_overlap/location_unannounced_quota_over_centered_closed_fourteen_day_window
        """
        program = setup_brand_program()
        schedule_visit(program, "2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z")
        schedule_visit(program, "2026-08-08T09:00:00Z", "2026-08-08T13:00:00Z")

        validate_error(
            api_client.create_audit_visit(
                _candidate(program, "2026-08-12T09:00:00Z", "2026-08-12T13:00:00Z"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_LOCATION_VISIT_WINDOW_QUOTA,
            expected_status=409,
        )

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 2

    def test_moving_the_candidate_past_the_window_edge_is_accepted(self):
        """A candidate whose centred window excludes both predecessors is booked.

        PRD: "Consider the closed window that extends seven days on either side of the
        candidate's `scheduled_start_at`, a fourteen-day span centred on the candidate."

        Design: Difficulty/resource_temporal_overlap/location_unannounced_quota_over_centered_closed_fourteen_day_window
        """
        program = setup_brand_program()
        schedule_visit(program, "2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z")
        schedule_visit(program, "2026-08-08T09:00:00Z", "2026-08-08T13:00:00Z")

        created = validate_success(
            api_client.create_audit_visit(
                _candidate(program, "2026-08-16T09:00:00Z", "2026-08-16T13:00:00Z"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["visit_type"] == "UNANNOUNCED"
        assert created["announced_notice_hours"] is None, \
            "an unannounced visit carries no notice obligation"

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 3
