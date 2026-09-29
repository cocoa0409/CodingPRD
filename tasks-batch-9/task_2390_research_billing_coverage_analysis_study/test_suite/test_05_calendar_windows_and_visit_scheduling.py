"""The calendar's day-offset axis, the research clinic's daily capacity, the
generation pin that visit completion checks, and the two route-creation guards.
"""

from test_helpers import (
    ANALYST_ONE,
    COORDINATOR_ONE,
    MANAGER_ONE,
    api_client,
    build_calendar_generation,
    complete_visit,
    create_calendar_visit_payload,
    create_subject_visit_payload,
    create_visit_charge_route_payload,
    item_spec,
    make_analyst_headers,
    make_coordinator_headers,
    make_manager_headers,
    read_calendar,
    route_spec,
    setup_consented_subject,
    setup_open_to_accrual,
    setup_scheduled_visit,
    setup_study_with_approved_analysis,
    validate_error,
    validate_paginated,
    validate_success,
    visit_spec,
)

# Visit 1 sits on the closed interval [0, 3]; visit 2 on [27, 33].  The two do
# not touch, so both are legal on one calendar.
VISIT_ONE = visit_spec("Cycle 1 Day 1", 1, 0, 0, 3)
VISIT_TWO = visit_spec("Cycle 2 Day 1", 2, 30, 3, 3)

PER_PATIENT_ITEM = item_spec(
    "J9999",
    classification="RESEARCH_PAID",
    budget_category="PER_PATIENT",
    charge_master_unit_cents=50000,
    negotiated_unit_cents=40000,
    expected_occurrences=1,
)
INVOICEABLE_FEE = item_spec(
    "IRB-FEE",
    classification="RESEARCH_PAID",
    budget_category="INVOICEABLE",
    charge_master_unit_cents=300000,
    negotiated_unit_cents=300000,
    expected_occurrences=1,
)


def _schedule_attempt(subject_id, calendar_visit_id, service_date):
    return api_client.create_subject_visit(
        create_subject_visit_payload(subject_id, calendar_visit_id, service_date),
        make_coordinator_headers(COORDINATOR_ONE),
    )


def _visit_attempt(calendar_id, **overrides):
    return api_client.create_calendar_visit(
        create_calendar_visit_payload(calendar_id, **overrides),
        make_analyst_headers(ANALYST_ONE),
    )


def _route_attempt(calendar_visit_id, coverage_item_id, occurrences=1):
    return api_client.create_visit_charge_route(
        create_visit_charge_route_payload(
            calendar_visit_id, coverage_item_id, occurrences=occurrences
        ),
        make_analyst_headers(ANALYST_ONE),
    )


def _read_subject_visit(subject_visit_id):
    return validate_success(
        api_client.get_subject_visit(
            subject_visit_id, make_coordinator_headers(COORDINATOR_ONE)
        )
    )


def _crowded_clinic_day():
    """A protocol open to accrual with two visits on the calendar and the
    clinic day 2026-09-02 already holding its two permitted occurrences."""
    ctx = setup_open_to_accrual(
        [PER_PATIENT_ITEM],
        [VISIT_ONE, VISIT_TWO],
        [route_spec("Cycle 1 Day 1", "J9999")],
        clock="2026-09-01T08:00:00Z",
        qct_registry_number="NCT10000014",
        study_overrides={"protocol_number": "AMC-2390-P"},
    )
    subjects = []
    for index in (1, 2, 3):
        subjects.append(
            setup_consented_subject(
                ctx, subject_number="S-%03d" % index, consent_date="2026-09-01"
            )
        )
    ctx["subjects"] = subjects
    ctx["first_visit"] = setup_scheduled_visit(
        ctx,
        visit_name="Cycle 1 Day 1",
        actual_service_date="2026-09-02",
        subject=subjects[0],
    )
    ctx["second_visit"] = setup_scheduled_visit(
        ctx,
        visit_name="Cycle 1 Day 1",
        actual_service_date="2026-09-02",
        subject=subjects[1],
    )
    return ctx


class TestVisitWindowOutranksDailyCapacity:
    """One request breaks the per-row window rule and the aggregate day limit."""

    def test_01_the_out_of_window_date_is_reported_not_the_full_clinic_day(self):
        """Scheduling visit 2 on day offset 1 is both outside [27, 33] and on a
        day already holding its two occurrences; the window check is earlier.

        PRD §2.11: "When several checks could reject the same request, they are
        evaluated in the fixed order below and the first failure is the one
        reported. Text order elsewhere in this document does not imply
        precedence; this list does."

        Design: Difficulty/priority_pair_validation_conflict/visit_window_violation_beats_daily_capacity_exhaustion
        """
        ctx = _crowded_clinic_day()
        assert ctx["first_visit"]["day_offset_actual"] == 1
        assert ctx["first_visit"]["status"] == "SCHEDULED"
        assert ctx["second_visit"]["status"] == "SCHEDULED"
        assert ctx["visit_by_name"]["Cycle 2 Day 1"]["window_start_day"] == 27
        assert ctx["visit_by_name"]["Cycle 2 Day 1"]["window_end_day"] == 33

        response = _schedule_attempt(
            ctx["subjects"][2]["id"],
            ctx["visit_by_name"]["Cycle 2 Day 1"]["id"],
            "2026-09-02",
        )
        validate_error(response, "ERR_VISIT_DATE_OUTSIDE_WINDOW", 422)

        rows, meta = validate_paginated(
            api_client.list_subject_visits(
                make_coordinator_headers(COORDINATOR_ONE),
                params={"study_subject_id": ctx["subjects"][2]["id"]},
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_02_each_of_the_two_checks_is_reachable_on_its_own(self):
        """In window but on the full day the capacity code appears; out of window
        on an empty day the temporal code appears.

        PRD §2.11: "34. Daily research-visit capacity —
        `ERR_RESEARCH_VISIT_DAILY_CAPACITY_EXCEEDED` (409) on subject-visit
        creation."

        Design: Difficulty/priority_pair_validation_conflict/visit_window_violation_beats_daily_capacity_exhaustion
        """
        ctx = _crowded_clinic_day()
        third_subject = ctx["subjects"][2]

        validate_error(
            _schedule_attempt(
                third_subject["id"],
                ctx["visit_by_name"]["Cycle 1 Day 1"]["id"],
                "2026-09-02",
            ),
            "ERR_RESEARCH_VISIT_DAILY_CAPACITY_EXCEEDED",
            409,
        )
        validate_error(
            _schedule_attempt(
                third_subject["id"],
                ctx["visit_by_name"]["Cycle 2 Day 1"]["id"],
                "2026-09-03",
            ),
            "ERR_VISIT_DATE_OUTSIDE_WINDOW",
            422,
        )


class TestDailyCapacityIsAggregateAcrossSubjects:
    """Two individually legal schedules exhaust the clinic day between them."""

    def test_03_a_third_occurrence_on_one_service_date_is_refused(self):
        """The third request is legal in every per-row respect and fails only
        because the study already holds two occurrences on that date.

        PRD §3.6: "Research visits are also capacity-constrained: at most two
        subject visits of the same study whose `status` is `SCHEDULED` or
        `OCCURRED` may share one service date, and a third is refused with
        `ERR_RESEARCH_VISIT_DAILY_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/research_visit_daily_capacity_is_aggregate_across_subjects
        """
        ctx = _crowded_clinic_day()
        visit_one_id = ctx["visit_by_name"]["Cycle 1 Day 1"]["id"]
        # The two occupants belong to two different subjects.
        assert ctx["first_visit"]["study_subject_id"] != ctx["second_visit"]["study_subject_id"]
        assert ctx["second_visit"]["day_offset_actual"] == 1

        validate_error(
            _schedule_attempt(ctx["subjects"][2]["id"], visit_one_id, "2026-09-02"),
            "ERR_RESEARCH_VISIT_DAILY_CAPACITY_EXCEEDED",
            409,
        )

        rows, meta = validate_paginated(
            api_client.list_subject_visits(
                make_coordinator_headers(COORDINATOR_ONE),
                params={"calendar_visit_id": visit_one_id},
            )
        )
        assert meta["total_count"] == 2

        # The very same visit one day later, on an empty clinic day, is fine.
        moved = validate_success(
            _schedule_attempt(ctx["subjects"][2]["id"], visit_one_id, "2026-09-03"), 201
        )
        assert moved["status"] == "SCHEDULED"
        assert moved["day_offset_actual"] == 2

    def test_04_an_occurred_visit_keeps_consuming_its_slot(self):
        """Capacity counts `SCHEDULED` and `OCCURRED` rows alike, so completing
        one of the two occupants does not free the day.

        PRD §3.6: "On success the server computes `day_offset_actual` as the
        whole number of days from the subject's `consent_date` to the
        `actual_service_date`, snapshots the owning calendar's `build_generation`
        into `calendar_generation_at_schedule`, and opens the row at `status`
        `SCHEDULED`."

        Design: Difficulty/resource_temporal_overlap/research_visit_daily_capacity_is_aggregate_across_subjects
        """
        ctx = _crowded_clinic_day()
        visit_one_id = ctx["visit_by_name"]["Cycle 1 Day 1"]["id"]

        completed = complete_visit(ctx["first_visit"]["id"])
        assert completed["status"] == "OCCURRED"

        validate_error(
            _schedule_attempt(ctx["subjects"][2]["id"], visit_one_id, "2026-09-02"),
            "ERR_RESEARCH_VISIT_DAILY_CAPACITY_EXCEEDED",
            409,
        )

        rows, meta = validate_paginated(
            api_client.list_subject_visits(
                make_coordinator_headers(COORDINATOR_ONE),
                params={"calendar_visit_id": visit_one_id},
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["status"] for row in rows) == ["OCCURRED", "SCHEDULED"]


class TestCalendarVisitWindowsAreClosedIntervals:
    """A single shared day offset is a collision."""

    def _draft_calendar(self):
        ctx = setup_study_with_approved_analysis(
            [PER_PATIENT_ITEM],
            qct_registry_number="NCT10000015",
            study_overrides={"protocol_number": "AMC-2390-U"},
        )
        return build_calendar_generation(ctx, [VISIT_ONE], publish=False)

    def test_05_a_window_that_merely_touches_the_first_is_refused(self):
        """A second visit at target day 7 with four days of tolerance before it
        occupies [3, 10] and shares day 3 with the first visit's [0, 3].

        PRD §3.4: "Those two numbers define a closed day interval, and no two
        visits on the same calendar may have intervals that intersect — touching
        endpoints count as an intersection, so a visit ending on day 14 and a
        visit starting on day 14 collide and the second is refused with
        `ERR_VISIT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/calendar_visit_windows_are_closed_and_may_not_touch
        """
        ctx = self._draft_calendar()
        first = ctx["visits"][0]
        assert first["window_start_day"] == 0
        assert first["window_end_day"] == 3

        validate_error(
            _visit_attempt(
                ctx["calendar"]["id"],
                visit_name="Cycle 1 Day 8",
                sequence_index=2,
                target_day_offset=7,
                window_before_days=4,
                window_after_days=3,
            ),
            "ERR_VISIT_WINDOW_OVERLAP",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_calendar_visits_of_calendar(
                ctx["calendar"]["id"], make_analyst_headers(ANALYST_ONE)
            )
        )
        assert meta["total_count"] == 1
        assert read_calendar(ctx["calendar"]["id"])["visit_count"] == 1

    def test_06_one_day_further_out_is_accepted_and_a_shared_endpoint_is_not(self):
        """The boundary between adjacent and touching is exactly one day wide:
        [4, 12] is accepted next to [0, 3], while [3, 6] is not.

        PRD §3.4: "From the tolerances the server derives `window_start_day` as
        the target day offset less the days allowed before it, and
        `window_end_day` as the target day offset plus the days allowed after
        it."

        Design: Difficulty/resource_temporal_overlap/calendar_visit_windows_are_closed_and_may_not_touch
        """
        ctx = self._draft_calendar()

        validate_error(
            _visit_attempt(
                ctx["calendar"]["id"],
                visit_name="Cycle 1 Day 3",
                sequence_index=2,
                target_day_offset=3,
                window_before_days=0,
                window_after_days=3,
            ),
            "ERR_VISIT_WINDOW_OVERLAP",
            409,
        )

        accepted = validate_success(
            _visit_attempt(
                ctx["calendar"]["id"],
                visit_name="Cycle 1 Day 9",
                sequence_index=2,
                target_day_offset=8,
                window_before_days=4,
                window_after_days=4,
            ),
            201,
        )
        assert accepted["window_start_day"] == 4
        assert accepted["window_end_day"] == 12
        assert read_calendar(ctx["calendar"]["id"])["visit_count"] == 2


class TestVisitCompletionChecksTheGenerationPin:
    """A third party publishing a fresh generation strands a scheduled visit."""

    def _stranded(self):
        ctx = setup_open_to_accrual(
            [PER_PATIENT_ITEM],
            [VISIT_ONE],
            [route_spec("Cycle 1 Day 1", "J9999")],
            clock="2026-09-01T08:00:00Z",
            qct_registry_number="NCT10000016",
            study_overrides={"protocol_number": "AMC-2390-G"},
        )
        setup_consented_subject(ctx, consent_date="2026-09-01")
        setup_scheduled_visit(ctx, actual_service_date="2026-09-02")
        ctx["generation_one"] = ctx["calendar"]
        ctx["stranded_visit"] = ctx["subject_visit"]
        ctx["pinned_subject"] = ctx["subject"]
        # A second generation is built from the same approved analysis and
        # published, which retires the generation the subject is pinned to.
        build_calendar_generation(
            ctx,
            [VISIT_ONE],
            [route_spec("Cycle 1 Day 1", "J9999")],
            publish=True,
        )
        ctx["generation_two"] = ctx["calendar"]
        return ctx

    def test_07_completion_is_refused_and_no_charge_is_dropped(self):
        """The visit itself never changed; the generation underneath it did.

        PRD §3.6: "The coordinator moves it `SCHEDULED → OCCURRED`, permitted
        only while the subject's `status` is `CONSENTED` and only while the
        calendar owning the referenced calendar visit is *still* the `PUBLISHED`
        generation with a `build_generation` still equal both to the visit's
        `calendar_generation_at_schedule` and to the subject's
        `consented_calendar_generation`; a generation that has drifted to
        `RETIRED` or `REBUILD_REQUIRED`, or a mismatch between the two
        snapshots, raises `ERR_STALE_CALENDAR_GENERATION`."

        Design: Difficulty/cross_entity_state_dependency/visit_completion_blocked_by_superseded_calendar_generation
        """
        ctx = self._stranded()
        assert ctx["generation_one"]["build_generation"] == 1
        assert ctx["generation_two"]["build_generation"] == 2
        assert ctx["generation_two"]["status"] == "PUBLISHED"
        assert ctx["stranded_visit"]["calendar_generation_at_schedule"] == 1
        assert ctx["pinned_subject"]["consented_calendar_generation"] == 1
        assert read_calendar(ctx["generation_one"]["id"])["status"] == "RETIRED"

        validate_error(
            api_client.complete_subject_visit(
                ctx["stranded_visit"]["id"], make_coordinator_headers(COORDINATOR_ONE)
            ),
            "ERR_STALE_CALENDAR_GENERATION",
            409,
        )

        after = _read_subject_visit(ctx["stranded_visit"]["id"])
        assert after["status"] == "SCHEDULED"
        assert after["generated_charge_count"] == 0

        _, meta = validate_paginated(
            api_client.list_charges(
                make_manager_headers(MANAGER_ONE),
                params={"study_id": ctx["study"]["id"]},
            )
        )
        assert meta["total_count"] == 0

    def test_08_the_pin_is_not_silently_repointed_at_the_new_generation(self):
        """The subject stays anchored to the generation it consented to, and a
        subject who consents to generation 2 completes normally.

        PRD §3.4: "On success `published_at` is stamped, and every other
        calendar of the same study whose `status` is `PUBLISHED` or
        `REBUILD_REQUIRED` is moved to `RETIRED`, which is terminal."

        Design: Difficulty/cross_entity_state_dependency/visit_completion_blocked_by_superseded_calendar_generation
        """
        ctx = self._stranded()
        validate_error(
            api_client.complete_subject_visit(
                ctx["stranded_visit"]["id"], make_coordinator_headers(COORDINATOR_ONE)
            ),
            "ERR_STALE_CALENDAR_GENERATION",
            409,
        )

        stranded_subject = validate_success(
            api_client.get_study_subject(
                ctx["pinned_subject"]["id"], make_coordinator_headers(COORDINATOR_ONE)
            )
        )
        assert stranded_subject["consented_calendar_id"] == ctx["generation_one"]["id"]
        assert stranded_subject["consented_calendar_generation"] == 1
        assert stranded_subject["status"] == "CONSENTED"

        # A subject pinned to the live generation is unaffected.
        fresh = setup_consented_subject(
            ctx, subject_number="S-002", consent_date="2026-09-01"
        )
        assert fresh["consented_calendar_id"] == ctx["generation_two"]["id"]
        assert fresh["consented_calendar_generation"] == 2
        scheduled = setup_scheduled_visit(
            ctx, actual_service_date="2026-09-03", subject=fresh
        )
        completed = complete_visit(scheduled["id"])
        assert completed["status"] == "OCCURRED"
        assert completed["generated_charge_count"] == 1


class TestItemAnalysisMismatchOutranksTheInvoiceableGuard:
    """A foreign invoiceable item breaks referential integrity first."""

    def _two_studies(self, local_specs):
        local = setup_study_with_approved_analysis(
            local_specs,
            qct_registry_number="NCT10000018",
            study_overrides={"protocol_number": "AMC-2390-L2"},
        )
        local = build_calendar_generation(local, [VISIT_ONE], publish=False)
        foreign = setup_study_with_approved_analysis(
            [INVOICEABLE_FEE],
            qct_registry_number="NCT10000019",
            study_overrides={"protocol_number": "AMC-2390-M3"},
        )
        return local, foreign

    def test_09_a_foreign_invoiceable_item_reports_the_referential_failure(self):
        """The item is both foreign to the calendar's source analysis and of a
        category that may never sit on a visit; the referential check is earlier.

        PRD §3.4: "The routed item must belong to the calendar's
        `source_analysis_id`, or the link is refused with
        `ERR_ITEM_ANALYSIS_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/item_analysis_mismatch_beats_invoiceable_not_routable
        """
        local, foreign = self._two_studies([PER_PATIENT_ITEM])
        visit_id = local["visits"][0]["id"]
        foreign_item = foreign["item_by_code"]["IRB-FEE"]
        assert foreign_item["budget_category"] == "INVOICEABLE"

        validate_error(
            _route_attempt(visit_id, foreign_item["id"]),
            "ERR_ITEM_ANALYSIS_MISMATCH",
            422,
        )

        _, meta = validate_paginated(
            api_client.list_visit_charge_routes(
                make_analyst_headers(ANALYST_ONE),
                params={"calendar_visit_id": visit_id},
            )
        )
        assert meta["total_count"] == 0

        calendar = read_calendar(local["calendar"]["id"])
        assert calendar["routed_item_count"] == 0
        assert calendar["unrouted_per_patient_item_count"] == 1

    def test_10_the_invoiceable_guard_is_reachable_on_the_calendars_own_item(self):
        """The outranked check really does fire once the referential condition
        is satisfied by an item of the calendar's own analysis.

        PRD §3.4: "An item whose `budget_category` is `INVOICEABLE` represents
        milestone or one-time money that is never dropped on a patient visit, so
        routing one onto a visit is refused with
        `ERR_INVOICEABLE_ITEM_NOT_VISIT_ROUTABLE`."

        Design: Difficulty/priority_pair_validation_conflict/item_analysis_mismatch_beats_invoiceable_not_routable
        """
        local, foreign = self._two_studies([PER_PATIENT_ITEM, INVOICEABLE_FEE])
        visit_id = local["visits"][0]["id"]

        validate_error(
            _route_attempt(visit_id, local["item_by_code"]["IRB-FEE"]["id"]),
            "ERR_INVOICEABLE_ITEM_NOT_VISIT_ROUTABLE",
            422,
        )
        validate_error(
            _route_attempt(visit_id, foreign["item_by_code"]["IRB-FEE"]["id"]),
            "ERR_ITEM_ANALYSIS_MISMATCH",
            422,
        )

        routed = validate_success(
            _route_attempt(visit_id, local["item_by_code"]["J9999"]["id"]), 201
        )
        assert routed["routing_target"] == "SPONSOR"
        assert routed["expected_amount_cents"] == 40000
