"""The area's two independent state dimensions and the cascades that move them.

A screening area carries a designation and a data status that answer to different
events, and both an indicator supersede and a confirmed violation set off chains
that reach all the way through to a permit application's own state.
"""

from test_helpers import (
    ADEQUACY_COMPLIANT,
    ANALYST_HEADERS,
    APP_ENHANCED_REVIEW,
    APP_STANDARD_REVIEW,
    ASSESSMENT_ACCEPTED,
    ASSESSMENT_INVALIDATED,
    BASE_COMMENT_DAYS,
    COMPLAINT_INSPECTED,
    COMPLAINT_TYPE_DUST,
    COMPLIANCE_IN_COMPLIANCE,
    COMPLIANCE_VIOLATION_ON_RECORD,
    DATA_STATUS_CURRENT,
    DATA_STATUS_STALE,
    DESIGNATION_OVERBURDENED,
    DESIGNATION_UNDESIGNATED,
    DETERMINATION_ENHANCED_REQUIRED,
    DETERMINATION_STANDARD,
    ENFORCEMENT_POINTS_PER_VIOLATION,
    FINDING_VIOLATION_CONFIRMED,
    INDICATOR_STATUS_ACTIVE,
    INDICATOR_STATUS_SUPERSEDED,
    INSPECTION_COMPLETED,
    INSPECTOR_1_USER_ID,
    OVERBURDENED_EXTRA_DAYS,
    PLAN_CLOSED,
    PLAN_PLANNED,
    SEVERITY_HIGH,
    TIER_2,
    TRACK_ENHANCED,
    TRIGGER_DESIGNATION,
    add_complaint,
    assert_amount,
    assert_amounts,
    assert_area_scores,
    assert_empty_listing,
    assert_field,
    assert_fields,
    assert_page,
    assign_next,
    complete_inspection,
    file_indicator,
    find_assessment,
    find_inspection,
    read_application,
    read_area,
    read_complaint,
    read_facility,
    read_plan,
    triage_accept,
)


def _confirm_a_dust_violation(api, state, scheduled_date):
    """File, triage, assign and confirm one HIGH dust complaint at the facility."""
    complaint = add_complaint(
        api,
        state,
        COMPLAINT_TYPE_DUST,
        SEVERITY_HIGH,
        "Visible dust plume crossing the school fence line",
        resident=2,
    )
    triage_accept(api, complaint["id"])
    inspection = assign_next(
        api, state, INSPECTOR_1_USER_ID, scheduled_date, narrow_to_area=True
    )
    complete_inspection(
        api, inspection["id"], FINDING_VIOLATION_CONFIRMED, "Fugitive dust controls absent"
    )
    return complaint, inspection


class TestParallelAreaDimensions:
    """PRD §3.1 keeps the designation and the data status on separate tracks."""

    def test_one_violation_moves_the_data_status_but_not_the_designation(
        self, api, area_a_inspection_pending
    ):
        """`CURRENT → STALE` while `OVERBURDENED` survives the rescore upward.

        PRD §3.8: "**Second**, that facility change adds **5 enforcement points** to
        the area's `enforcement_burden_points`, which feeds the penalty term of both
        screening score variants; both scores are recomputed, `designation` is
        re-evaluated with all the consequences of §3.1, and `data_status` is driven to
        `STALE`."
        PRD §3.1: "Then add the enforcement penalty — the area's
        `enforcement_burden_points` multiplied by 0.50 — take the smaller of 100.00 and
        that sum, and round half up to two decimals for the final score."
        PRD §3.1: "A score of **at least 80.00** designates the area
        `SEVERELY_OVERBURDENED`; otherwise a score of **at least 65.00** designates it
        `OVERBURDENED`; otherwise it is `UNDESIGNATED`."

        Design: Difficulty/non_linear_state_machine/screening_area_parallel_designation_and_data_status_dimensions
        """
        state = area_a_inspection_pending
        before = read_area(api, state["area_id"])
        assert_field(before, "data_status", DATA_STATUS_CURRENT)
        assert_field(before, "designation", DESIGNATION_OVERBURDENED)
        assert_area_scores(before, statewide=74.03, county=39.68)

        complete_inspection(
            api,
            state["inspection_id"],
            FINDING_VIOLATION_CONFIRMED,
            "Uncontrolled rendering vent observed",
        )

        area = read_area(api, state["area_id"])
        assert_fields(
            area,
            {
                # The two dimensions moved independently under one event.
                "data_status": DATA_STATUS_STALE,
                "designation": DESIGNATION_OVERBURDENED,
                "enforcement_burden_points": ENFORCEMENT_POINTS_PER_VIOLATION,
                "active_indicator_count": 4,
            },
        )
        # 5 points x 0.50 lifts both scores by 2.50 without crossing 80.00.
        assert_area_scores(area, statewide=76.53, county=42.18)

    def test_the_completed_visit_records_its_priority_snapshot_and_the_violation(
        self, api, area_a_inspection_pending
    ):
        """The 45.87 score that won the assignment is what the record keeps.

        PRD §3.8: "A successful assignment creates an inspection in `status`
        `SCHEDULED` naming the `community_complaint_id` that earned it, copying the
        selected complaint's `facility_id` into the inspection's own `facility_id`,
        recording `priority_score_at_assignment` as a snapshot of the winning
        complaint's `priority_score`, and leaving `finding` null."
        PRD §3.8: "Completion moves the inspection `SCHEDULED → COMPLETED`, writes the
        finding, moves the complaint `INSPECTION_ASSIGNED → INSPECTED`, and increments
        both rows' `version` by 1."
        PRD §3.8: "**First**, the inspected facility's `compliance_status` flips to
        `VIOLATION_ON_RECORD` and its `confirmed_violation_count` increases by 1."
        PRD §3.8: "From the score comes `priority_tier`: `TIER_1` when the score is at
        least 70.00, otherwise `TIER_2` when it is at least 45.00, otherwise `TIER_3`."

        Design: Difficulty/non_linear_state_machine/screening_area_parallel_designation_and_data_status_dimensions
        """
        state = area_a_inspection_pending
        complaint_id = state["complaint_id"]

        complete_inspection(
            api,
            state["inspection_id"],
            FINDING_VIOLATION_CONFIRMED,
            "Uncontrolled rendering vent observed",
        )

        inspection = find_inspection(api, complaint_id, state["inspection_id"])
        assert_fields(
            inspection,
            {
                "status": INSPECTION_COMPLETED,
                "finding": FINDING_VIOLATION_CONFIRMED,
            },
        )
        # 39.68 county score x 0.40 = 15.87, plus 30 severity points for HIGH.
        assert_amount(
            inspection.get("priority_score_at_assignment"),
            45.87,
            "priority_score_at_assignment",
        )

        complaint = read_complaint(api, complaint_id)
        assert_field(complaint, "status", COMPLAINT_INSPECTED)
        assert_field(complaint, "priority_tier", TIER_2)
        assert_amount(complaint.get("priority_score"), 45.87, "priority_score")

        facility = read_facility(api, state["facility_id"])
        assert_field(facility, "compliance_status", COMPLIANCE_VIOLATION_ON_RECORD)
        assert_field(facility, "confirmed_violation_count", 1)


class TestIndicatorSupersedeCascade:
    """PRD §3.1 lets one indicator filing reach a standard-track application."""

    def test_a_superseding_indicator_pushes_the_area_over_the_designation_cut(
        self, api, area_d_standard_track
    ):
        """A 40.00 to 70.00 percentile swap rescores 57.50 up to 72.68.

        PRD §3.1: "Each indicator carries a `status` of `ACTIVE` or `SUPERSEDED`; a
        newly filed row lands `ACTIVE`, and if an `ACTIVE` row already exists for the
        same area and the same `indicator_code`, that row moves to `SUPERSEDED` and the
        new row records the displaced row's identifier in `superseded_indicator_id`."
        PRD §3.1: "Take the pollution component multiplied by 0.55, add the health
        component multiplied by 0.45, then multiply the result by the demographic
        component divided by 100; round that half up to two decimals to obtain the
        pre-penalty score."
        PRD §3.1: "The number of qualifying rows is written to `active_indicator_count`
        and is shared by both variants."

        Design: Difficulty/transitive_cascade/indicator_supersede_escalates_designation_and_flips_standard_to_enhanced
        """
        state = area_d_standard_track
        before = read_area(api, state["area_id"])
        assert_area_scores(before, statewide=57.50, county=38.40)
        assert_field(before, "designation", DESIGNATION_UNDESIGNATED)
        assert_field(before, "translation_required", False)

        determinations = assert_page(
            api.list_applicability_determinations(state["app_id"], ANALYST_HEADERS),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
        assert_field(determinations[0], "result", DETERMINATION_STANDARD)
        assert_field(determinations[0], "trigger_codes", [])
        assert_field(
            read_application(api, state["app_id"]), "status", APP_STANDARD_REVIEW
        )

        filed = file_indicator(
            api,
            state["area_id"],
            "PM25",
            raw_value=15.60,
            statewide_percentile=70.00,
            county_percentile=60.00,
            expected_area_version=state["area_version"],
        )

        assert_field(filed, "status", INDICATOR_STATUS_ACTIVE)
        assert_field(filed, "superseded_indicator_id", state["indicator_pm25_id"])

        rows = assert_page(
            api.list_burden_indicators(state["area_id"], ANALYST_HEADERS, params={"limit": 100}),
            expected_rows=4,
            expected_total=4,
            expected_has_more=False,
        )
        superseded = [row for row in rows if row["id"] == state["indicator_pm25_id"]]
        assert len(superseded) == 1, "the predecessor row should still be listed"
        assert_field(superseded[0], "status", INDICATOR_STATUS_SUPERSEDED)

        area = read_area(api, state["area_id"])
        assert_field(area, "active_indicator_count", 3)
        # 70.00 x 0.55 + 90.00 x 0.45 = 79.00, scaled by 92/100.
        assert_area_scores(area, statewide=72.68, county=51.60)
        assert_field(area, "designation", DESIGNATION_OVERBURDENED)
        assert_field(area, "translation_required", False)

    def test_the_escalated_designation_flips_the_application_and_creates_a_plan(
        self, api, area_d_standard_track
    ):
        """The standard file becomes enhanced and picks up a 45-day plan.

        PRD §3.1: "Moving `UNDESIGNATED → OVERBURDENED` (statewide score at least 65.00
        and below 80.00) escalates every application in `STANDARD_REVIEW` at a facility
        in the area onto the enhanced track, recomputes the required comment-period
        length on every participation plan of the area's applications whose status is
        `PLANNED`, `OPEN` or `EXTENDED`, and increments the area's `version` by 1."
        PRD §3.1: "Filing an indicator therefore fans out: the predecessor row is
        superseded, both score variants and `active_indicator_count` are recomputed,
        designation is re-evaluated with the escalation consequences above (each newly
        escalated application also acquires an applicability determination and a
        participation plan, as described in §3.2 and §3.4), the priority score of every
        complaint in the area whose status is `RECEIVED` or `TRIAGED` is recomputed
        against the new county score, and the area's `version` increments by 1."
        PRD §3.4: "Every enhanced-track application gets a **participation plan**,
        created by the system rather than by a person: it names the application through
        `permit_application_id` and lands in `status` `PLANNED` with
        `granted_extension_days` 0, `comment_start_date` and `comment_end_date` both
        null, `translated_languages` an empty array, `materials_translated` false,
        `meeting_count` 0, `comment_count` 0, `adequacy_status` `PENDING` and
        `deficiency_codes` an empty array."
        PRD §3.4: "Start from a base of **30 days**. Add 15 days when the area's
        `designation` is `OVERBURDENED`."

        Design: Difficulty/transitive_cascade/indicator_supersede_escalates_designation_and_flips_standard_to_enhanced
        """
        state = area_d_standard_track
        file_indicator(
            api,
            state["area_id"],
            "PM25",
            raw_value=15.60,
            statewide_percentile=70.00,
            county_percentile=60.00,
            expected_area_version=state["area_version"],
        )

        application = read_application(api, state["app_id"])
        assert_fields(
            application,
            {
                "status": APP_ENHANCED_REVIEW,
                "review_track": TRACK_ENHANCED,
                "screening_stale_flag": False,
                "revision_round": 0,
            },
        )

        determinations = assert_page(
            api.list_applicability_determinations(state["app_id"], ANALYST_HEADERS),
            expected_rows=2,
            expected_total=2,
            expected_has_more=False,
        )
        current = determinations[0]
        assert_fields(
            current,
            {
                "result": DETERMINATION_ENHANCED_REQUIRED,
                "trigger_codes": [TRIGGER_DESIGNATION],
                "determined_by_user_id": "system",
                "area_designation_snapshot": DESIGNATION_OVERBURDENED,
                "revision_round": 0,
            },
        )
        assert_amount(
            current.get("ej_screen_score_snapshot"), 72.68, "ej_screen_score_snapshot"
        )

        plans = assert_page(
            api.list_application_plans(state["app_id"], ANALYST_HEADERS),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
        assert_fields(
            plans[0],
            {
                "status": PLAN_PLANNED,
                # 30 base days plus 15 for the fresh OVERBURDENED designation.
                "required_comment_days": BASE_COMMENT_DAYS + OVERBURDENED_EXTRA_DAYS,
                "granted_extension_days": 0,
                "comment_end_date": None,
                "meeting_count": 0,
                "comment_count": 0,
            },
        )
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 0)


class TestViolationCascadeRegressesTheApplication:
    """PRD §3.8 will not let a permit rest on data enforcement has questioned."""

    def test_a_confirmed_violation_invalidates_the_accepted_assessment(
        self, api, app_a_pending_decision
    ):
        """The `STALE` data status reaches through to the governing assessment.

        PRD §3.8: "**Third**, the `STALE` data status invalidates every `ACCEPTED`
        cumulative impact assessment belonging to an application at any facility in
        that area, moving each `ACCEPTED → INVALIDATED`."
        PRD §3.3: "When an enforcement violation drives the area's `data_status` to
        `STALE`, every `ACCEPTED` assessment belonging to an application at a facility
        in that area moves `ACCEPTED → INVALIDATED`."
        PRD §3.8: "**First**, the inspected facility's `compliance_status` flips to
        `VIOLATION_ON_RECORD` and its `confirmed_violation_count` increases by 1."

        Design: Difficulty/transitive_cascade/inspection_violation_cascade_invalidates_accepted_assessment_and_regresses_application
        """
        state = app_a_pending_decision
        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_ACCEPTED,
        )
        assert_field(
            read_facility(api, state["facility_id"]),
            "compliance_status",
            COMPLIANCE_IN_COMPLIANCE,
        )

        complaint, inspection = _confirm_a_dust_violation(api, state, "2026-10-12")

        facility = read_facility(api, state["facility_id"])
        assert_field(facility, "compliance_status", COMPLIANCE_VIOLATION_ON_RECORD)
        assert_field(facility, "confirmed_violation_count", 1)

        area = read_area(api, state["area_id"])
        assert_field(area, "enforcement_burden_points", ENFORCEMENT_POINTS_PER_VIOLATION)
        assert_field(area, "data_status", DATA_STATUS_STALE)
        assert_field(area, "designation", DESIGNATION_OVERBURDENED)
        assert_amount(
            area.get("ej_screen_score_statewide"), 76.53, "ej_screen_score_statewide"
        )

        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_INVALIDATED,
        )
        assert_field(read_complaint(api, complaint["id"]), "status", COMPLAINT_INSPECTED)
        assert_field(
            find_inspection(api, complaint["id"], inspection["id"]),
            "status",
            INSPECTION_COMPLETED,
        )

    def test_the_invalidated_assessment_regresses_the_pending_application(
        self, api, app_a_pending_decision
    ):
        """`PENDING_DECISION → ENHANCED_REVIEW` with both indices collapsed to 0.00.

        PRD §3.8: "**Fourth**, each application whose governing assessment was just
        invalidated sets `screening_stale_flag` to true, and any such application
        sitting in `PENDING_DECISION` regresses `PENDING_DECISION → ENHANCED_REVIEW` on
        the enhanced track, recomputing its `pre_mitigation_index` and
        `residual_impact_index` and incrementing its `version` by 1." and "This is the
        intended serialisation point between enforcement and permitting: a permit
        cannot be issued on the strength of screening data that an enforcement finding
        has just called into question."
        PRD §3.3: "When no candidate exists there is no governing assessment, and both
        `pre_mitigation_index` and `residual_impact_index` are 0.00."

        Design: Difficulty/transitive_cascade/inspection_violation_cascade_invalidates_accepted_assessment_and_regresses_application
        """
        state = app_a_pending_decision
        before = read_application(api, state["app_id"])
        assert_amount(before.get("pre_mitigation_index"), 81.82, "pre_mitigation_index")

        _confirm_a_dust_violation(api, state, "2026-10-12")

        application = read_application(api, state["app_id"])
        assert_fields(
            application,
            {
                "status": APP_ENHANCED_REVIEW,
                "review_track": TRACK_ENHANCED,
                "screening_stale_flag": True,
            },
        )
        assert_amounts(
            application,
            {
                "pre_mitigation_index": 0.00,
                "residual_impact_index": 0.00,
            },
        )

        # The closed plan is untouched by this cascade.
        plan = read_plan(api, state["plan_id"])
        assert_field(plan, "status", PLAN_CLOSED)
        assert_field(plan, "adequacy_status", ADEQUACY_COMPLIANT)

        assert_empty_listing(
            api.list_application_decisions(state["app_id"], ANALYST_HEADERS)
        )
