"""Ordered validation: which of two live failures is the one that gets reported."""
from test_helpers import (
    ADMIN_HEADERS,
    FIRST_VISIT_START,
    ApiErrorId,
    api_client,
    audit_visit_payload,
    make_auditor_headers,
    scored_item_payload,
    setup_brand_program,
    setup_in_progress_visit,
    setup_scheduled_visit,
    start_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStateBeforePointsRange:
    def test_the_visit_state_check_outranks_the_points_range_check(self):
        """A scoring call on a scheduled visit reports the state error, not the range error.

        PRD: "This ordering is normative. A request that violates a lower-numbered rule and
        a higher-numbered rule at once reports the lower-numbered error."

        Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_points_exceed_max_on_scored_item_create
        """
        program = setup_scheduled_visit()
        visit_id = program["visit"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        validate_error(
            api_client.create_scored_item(
                visit_id, scored_item_payload(program["item_ids"]["FS-1"], 99), auditor_headers,
            ),
            ApiErrorId.ERR_INVALID_VISIT_STATE,
            expected_status=409,
        )

        rows, meta = validate_paginated(
            api_client.list_scored_items(ADMIN_HEADERS, params={"visit_id": visit_id})
        )
        assert meta["total_count"] == 0, "the rejected call persisted nothing"
        assert rows == []

    def test_the_points_range_check_fires_once_the_state_is_legal(self):
        """With the visit in progress the same body trips the range check instead.

        PRD: "`points_awarded` must be at least 0 and at most that rubric item's
        `max_points`, or the call is rejected with `ERR_POINTS_EXCEED_MAX`"

        Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_points_exceed_max_on_scored_item_create
        """
        program = setup_scheduled_visit()
        visit_id = program["visit"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        started = start_visit(program, visit_id, at=FIRST_VISIT_START)
        assert started["status"] == "IN_PROGRESS"

        validate_error(
            api_client.create_scored_item(
                visit_id, scored_item_payload(program["item_ids"]["FS-1"], 99), auditor_headers,
            ),
            ApiErrorId.ERR_POINTS_EXCEED_MAX,
            expected_status=422,
        )

        _, meta = validate_paginated(
            api_client.list_scored_items(ADMIN_HEADERS, params={"visit_id": visit_id})
        )
        assert meta["total_count"] == 0


class TestSuspensionBeforeCalendarConflict:
    def test_the_suspension_check_outranks_the_calendar_conflict_check(self):
        """A suspended auditor's booking reports the suspension, not the overlap.

        PRD: "The auditor bound to the operation is not `SUSPENDED` — `ERR_AUDITOR_SUSPENDED`,
        on `POST /audit-visits`, `POST /audit-visits/{id}/start`,
        `POST /corrective-actions/{id}/verify`, `POST /disputes/{id}/request-info`,
        `POST /disputes/{id}/resolve`, and `POST /calibration-records`."

        Design: Difficulty/priority_pair_validation_conflict/auditor_suspended_wins_over_schedule_conflict_on_visit_create
        """
        program = setup_scheduled_visit()
        auditor_id = program["auditor"]["id"]

        suspended = validate_success(
            api_client.suspend_auditor(auditor_id, ADMIN_HEADERS, {"note": "Integrity review"})
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "MANUAL_REVIEW"

        candidate = audit_visit_payload(
            program["location"]["id"], auditor_id, program["rubric_version"]["id"],
            "2026-08-05T13:00:00Z", "2026-08-05T15:00:00Z",
        )
        validate_error(
            api_client.create_audit_visit(candidate, ADMIN_HEADERS),
            ApiErrorId.ERR_AUDITOR_SUSPENDED,
            expected_status=409,
        )

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 1, "only the pre-existing visit remains"

    def test_the_calendar_conflict_surfaces_once_the_auditor_is_reinstated(self):
        """Reinstatement clears the suspension gate and exposes the travel-buffer overlap.

        PRD: "Every existing non-voided visit of the same auditor is expanded by a
        60-minute travel buffer at both ends, and if the candidate interval intersects any
        expanded interval the request is rejected with `ERR_AUDITOR_SCHEDULE_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/auditor_suspended_wins_over_schedule_conflict_on_visit_create
        """
        program = setup_scheduled_visit()
        auditor_id = program["auditor"]["id"]
        validate_success(
            api_client.suspend_auditor(auditor_id, ADMIN_HEADERS, {"note": "Integrity review"})
        )

        reinstated = validate_success(
            api_client.certify_auditor(auditor_id, ADMIN_HEADERS, {})
        )
        assert reinstated["status"] == "CERTIFIED"
        assert reinstated["suspension_reason"] is None

        candidate = audit_visit_payload(
            program["location"]["id"], auditor_id, program["rubric_version"]["id"],
            "2026-08-05T13:00:00Z", "2026-08-05T15:00:00Z",
        )
        validate_error(
            api_client.create_audit_visit(candidate, ADMIN_HEADERS),
            ApiErrorId.ERR_AUDITOR_SCHEDULE_CONFLICT,
            expected_status=409,
        )

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 1


class TestNoticeBeforeUnannouncedMix:
    def test_the_notice_check_outranks_the_unannounced_mix_check(self):
        """A short-notice announced visit reports the notice error even with a 0% mix.

        PRD: "An announced visit carries sufficient notice — `ERR_ANNOUNCED_NOTICE_TOO_SHORT`
        (HTTP 422), on `POST /audit-visits`."

        Design: Difficulty/priority_pair_validation_conflict/announced_notice_error_wins_over_unannounced_mix_shortfall
        """
        program = setup_brand_program()

        payload = audit_visit_payload(
            program["location"]["id"], program["auditor"]["id"],
            program["rubric_version"]["id"],
            "2026-08-02T09:00:00Z", "2026-08-02T13:00:00Z", visit_type="ANNOUNCED",
        )
        validate_error(
            api_client.create_audit_visit(payload, ADMIN_HEADERS),
            ApiErrorId.ERR_ANNOUNCED_NOTICE_TOO_SHORT,
            expected_status=422,
        )

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 0

    def test_the_mix_shortfall_surfaces_once_the_notice_is_sufficient(self):
        """With ample notice the same announced booking fails the brand's mix floor.

        PRD: "If that percentage is below the brand's `unannounced_min_ratio_pct`, creation
        is rejected with `ERR_UNANNOUNCED_MIX_BELOW_MINIMUM`; a percentage exactly equal to
        the minimum passes."

        Design: Difficulty/priority_pair_validation_conflict/announced_notice_error_wins_over_unannounced_mix_shortfall
        """
        program = setup_brand_program()
        assert program["brand"]["unannounced_min_ratio_pct"] == 40

        payload = audit_visit_payload(
            program["location"]["id"], program["auditor"]["id"],
            program["rubric_version"]["id"],
            "2026-08-06T09:00:00Z", "2026-08-06T13:00:00Z", visit_type="ANNOUNCED",
        )
        validate_error(
            api_client.create_audit_visit(payload, ADMIN_HEADERS),
            ApiErrorId.ERR_UNANNOUNCED_MIX_BELOW_MINIMUM,
            expected_status=422,
        )

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 0


class TestInProgressVisitPrecondition:
    def test_scoring_an_in_progress_visit_is_the_control_case(self):
        """The same rubric item and a legal point value are accepted in progress.

        PRD: "While the visit is `IN_PROGRESS`, its auditor records one **ScoredItem** per
        rubric line item observed."

        Design: Difficulty/priority_pair_validation_conflict/state_error_wins_over_points_exceed_max_on_scored_item_create
        """
        program = setup_in_progress_visit()
        visit_id = program["visit"]["id"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        scored = validate_success(
            api_client.create_scored_item(
                visit_id, scored_item_payload(program["item_ids"]["FS-1"], 27), auditor_headers,
            ),
            expected_status=201,
        )
        assert scored["points_awarded"] == 27
        assert scored["status"] == "SCORED"
