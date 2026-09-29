"""Complaint intake, triage, the inspection queue and the enforcement cascade.

Complaints are what tie inspection effort back to community burden, so the
priority score, the inspector's daily ceiling, the referral precondition and the
confirmed-violation cascade are all exercised here against a live queue.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    ApiErrorId,
    COMPLAINT_DISMISSED,
    COMPLAINT_INSPECTED,
    COMPLAINT_INSPECTION_ASSIGNED,
    COMPLAINT_RECEIVED,
    COMPLAINT_RESOLVED,
    COMPLAINT_TRIAGED,
    COMPLAINT_TYPE_DUST,
    COMPLAINT_TYPE_NOISE,
    COMPLAINT_TYPE_ODOR,
    COMPLAINT_TYPE_SMOKE,
    COMPLIANCE_IN_COMPLIANCE,
    COMPLIANCE_VIOLATION_ON_RECORD,
    DATA_STATUS_CURRENT,
    DATA_STATUS_STALE,
    DESIGNATION_OVERBURDENED,
    ENFORCEMENT_POINTS_PER_VIOLATION,
    FINDING_NO_VIOLATION,
    FINDING_VIOLATION_CONFIRMED,
    INSPECTION_COMPLETED,
    INSPECTOR_1_USER_ID,
    LIAISON_HEADERS,
    MAX_INSPECTIONS_PER_INSPECTOR_PER_DAY,
    RESOLUTION_REFERRED_ENFORCEMENT,
    RESOLUTION_RESOLVED,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    TIER_3,
    add_complaint,
    assert_amount,
    assert_area_scores,
    assert_array_envelope,
    assert_field,
    assert_fields,
    assert_page,
    assert_rejected,
    assign_next,
    assign_next_payload,
    complete_inspection,
    find_inspection,
    page_params,
    read_area,
    read_complaint,
    read_facility,
    reopen_complaint_payload,
    resolve_complaint_payload,
    triage_accept,
    triage_dismiss,
    validate_success,
)


class TestComplaintReopenCycle:
    """PRD §3.8 lets a community push a closed complaint back into the queue."""

    def test_resolved_complaint_reopened_reenters_triaged(self, api, area_g_facility):
        """The cycle back to `TRIAGED` rescores rather than replaying the filing.

        PRD §3.8: "A `CommunityLiaison` may reopen a `RESOLVED` complaint with a
        `reason`, moving it `RESOLVED → TRIAGED`, incrementing `reopen_count` by 1,
        incrementing the area's `open_complaint_count` by 1, recomputing
        `priority_score` and `priority_tier`, and incrementing the complaint's
        `version` by 1 — the `TRIAGED` through `RESOLVED` back to `TRIAGED` cycle
        lets a community push back on a closed file."
        PRD §3.8: "Then `priority_score` is the sum of five terms, rounded half up
        to two decimals: the area's **county** screening score multiplied by 0.40;
        severity points of 5 for `LOW`, 15 for `MEDIUM` or 30 for `HIGH`; the
        smaller of 20 and four points per prior repeat, so the repeat contribution
        saturates at five priors; a flat 10 points when a `facility_id` was named
        and that facility's `compliance_status` is `VIOLATION_ON_RECORD`; and a
        flat 5 points when the area's `designation` is `SEVERELY_OVERBURDENED`."
        PRD §3.8: "From the score comes `priority_tier`: `TIER_1` when the score is
        at least 70.00, otherwise `TIER_2` when it is at least 45.00, otherwise
        `TIER_3`."
        PRD §3.8: "A `NO_VIOLATION` finding fires none of these four steps."

        Design: Corner/state_machines/complaint_resolved_then_reopened_reenters_triaged
        """
        state = area_g_facility
        complaint = add_complaint(
            api,
            state,
            COMPLAINT_TYPE_ODOR,
            SEVERITY_MEDIUM,
            "Lacquer smell in the afternoons",
            resident=7,
        )
        triage_accept(api, complaint["id"])
        inspection = assign_next(
            api, state, INSPECTOR_1_USER_ID, "2026-08-05", narrow_to_area=True
        )
        complete_inspection(
            api, inspection["id"], FINDING_NO_VIOLATION, "Spray booth filters in service"
        )
        resolved = validate_success(
            api.resolve_complaint(
                complaint["id"],
                resolve_complaint_payload(RESOLUTION_RESOLVED, note="No violation observed"),
                ANALYST_HEADERS,
            )
        )
        assert_field(resolved, "status", COMPLAINT_RESOLVED)

        response = api.reopen_complaint(
            complaint["id"],
            reopen_complaint_payload("Odor recurred the following week"),
            LIAISON_HEADERS,
        )

        reopened = validate_success(response)
        assert_fields(
            reopened,
            {
                "status": COMPLAINT_TRIAGED,
                "reopen_count": 1,
                "priority_tier": TIER_3,
            },
        )
        # AREA_G has no indicators, so the county term contributes nothing and the
        # MEDIUM severity term of 15 is the whole score.
        assert_amount(reopened.get("priority_score"), 15.00, "priority_score")

        stored = read_complaint(api, complaint["id"])
        assert_field(stored, "status", COMPLAINT_TRIAGED)
        assert_field(stored, "reopen_count", 1)

        assert_field(read_area(api, state["area_id"]), "open_complaint_count", 1)

        facility = read_facility(api, state["facility_id"])
        assert_field(facility, "compliance_status", COMPLIANCE_IN_COMPLIANCE)
        assert_field(facility, "confirmed_violation_count", 0)

        assert_field(
            find_inspection(api, complaint["id"], inspection["id"]),
            "status",
            INSPECTION_COMPLETED,
        )


class TestInspectorDayCapacity:
    """PRD §3.8 checks the inspector's daily ceiling before it selects anything."""

    def test_fourth_assignment_for_one_inspector_and_day_is_rejected(
        self, api, area_m_facility
    ):
        """Three scheduled visits fill the day, so the fourth pull selects nothing.

        PRD §3.8: "**Inspector day capacity is validated before selection:** if the
        named inspector already has three or more inspections with `status`
        `SCHEDULED` on that `scheduled_date`, the request is refused with
        `ERR_INSPECTOR_DAY_CAPACITY_EXCEEDED` and nothing is selected."
        PRD §3.8: "The complaint moves `TRIAGED → INSPECTION_ASSIGNED` and its
        `version` increments by 1."
        PRD §3.8: "A new complaint lands in `status` `RECEIVED` with `reopen_count`
        0, is scored immediately, and increments the area's `open_complaint_count`
        by 1."

        Design: Corner/errors/inspector_day_capacity_exceeded_on_fourth_assignment
        """
        state = area_m_facility
        filings = (
            (COMPLAINT_TYPE_ODOR, SEVERITY_HIGH, "Feed odor at dawn", 11),
            (COMPLAINT_TYPE_DUST, SEVERITY_HIGH, "Grain dust on parked cars", 12),
            (COMPLAINT_TYPE_NOISE, SEVERITY_MEDIUM, "Night blower noise", 13),
            (COMPLAINT_TYPE_SMOKE, SEVERITY_LOW, "Occasional visible plume", 14),
        )
        for complaint_type, severity, description, resident in filings:
            complaint = add_complaint(
                api, state, complaint_type, severity, description, resident=resident
            )
            triage_accept(api, complaint["id"])

        for _ in range(MAX_INSPECTIONS_PER_INSPECTOR_PER_DAY):
            assign_next(api, state, INSPECTOR_1_USER_ID, "2026-08-05", narrow_to_area=True)

        response = api.assign_next_inspection(
            assign_next_payload(
                inspector_user_id=INSPECTOR_1_USER_ID,
                scheduled_date="2026-08-05",
                screening_area_id=state["area_id"],
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.INSPECTOR_DAY_CAPACITY_EXCEEDED)

        assigned = assert_page(
            api.list_complaints(
                ANALYST_HEADERS,
                params=page_params(
                    limit=10,
                    offset=0,
                    screening_area_id=state["area_id"],
                    status=COMPLAINT_INSPECTION_ASSIGNED,
                ),
            ),
            expected_rows=3,
            expected_total=3,
            expected_has_more=False,
        )
        for row in assigned:
            assert_field(row, "status", COMPLAINT_INSPECTION_ASSIGNED)

        waiting = assert_page(
            api.list_complaints(
                ANALYST_HEADERS,
                params=page_params(
                    limit=10,
                    offset=0,
                    screening_area_id=state["area_id"],
                    status=COMPLAINT_TRIAGED,
                ),
            ),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
        assert_field(waiting[0], "status", COMPLAINT_TRIAGED)

        assert_field(read_area(api, state["area_id"]), "open_complaint_count", 4)


class TestEnforcementReferralPrecondition:
    """PRD §3.8 only allows a referral the inspection record supports."""

    def test_referral_after_a_no_violation_finding_is_rejected(
        self, api, area_m_facility
    ):
        """Enforcement cannot be handed a complaint the inspector cleared.

        PRD §3.8: "`REFERRED_ENFORCEMENT` moves it `INSPECTED →
        REFERRED_ENFORCEMENT`, which is terminal, and is permitted only when the
        complaint's latest `COMPLETED` inspection recorded a `finding` of
        `VIOLATION_CONFIRMED`; an unsupported referral is refused with
        `ERR_REFERRAL_UNSUPPORTED`."
        PRD §3.8: "A `NO_VIOLATION` finding fires none of these four steps."

        Design: Corner/errors/enforcement_referral_without_confirmed_violation_rejected
        """
        state = area_m_facility
        complaint = add_complaint(
            api, state, COMPLAINT_TYPE_ODOR, SEVERITY_HIGH, "Feed odor at dawn", resident=11
        )
        triage_accept(api, complaint["id"])
        inspection = assign_next(
            api, state, INSPECTOR_1_USER_ID, "2026-08-05", narrow_to_area=True
        )
        complete_inspection(
            api,
            inspection["id"],
            FINDING_NO_VIOLATION,
            "Odour not detectable at the fence line",
        )

        response = api.resolve_complaint(
            complaint["id"],
            resolve_complaint_payload(
                RESOLUTION_REFERRED_ENFORCEMENT, note="Send to enforcement anyway"
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.REFERRAL_UNSUPPORTED)

        assert_field(read_complaint(api, complaint["id"]), "status", COMPLAINT_INSPECTED)
        assert_field(
            read_facility(api, state["facility_id"]),
            "compliance_status",
            COMPLIANCE_IN_COMPLIANCE,
        )
        assert_field(read_area(api, state["area_id"]), "open_complaint_count", 1)


class TestComplaintListing:
    """PRD §3.8 exposes the queue through a filtered, paginated listing."""

    def test_complaint_listing_filters_by_status_and_paginates(
        self, api, area_m_facility
    ):
        """A dismissal moves one row from one status bucket into another.

        PRD §3.8: "Complaints can be listed with filters on `screening_area_id`,
        `facility_id`, `status` and `priority_tier`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."
        PRD §3.8: "Dismissing requires a `dismissal_reason`, moves the complaint
        `RECEIVED → DISMISSED` (terminal), decrements the area's
        `open_complaint_count` by 1, and increments the complaint's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/complaint_list_filters_by_status_and_paginates
        """
        state = area_m_facility
        add_complaint(
            api, state, COMPLAINT_TYPE_ODOR, SEVERITY_HIGH, "Feed odor at dawn", resident=11
        )
        add_complaint(
            api,
            state,
            COMPLAINT_TYPE_DUST,
            SEVERITY_MEDIUM,
            "Grain dust on parked cars",
            resident=12,
        )
        third = add_complaint(
            api, state, COMPLAINT_TYPE_NOISE, SEVERITY_LOW, "Night blower noise", resident=13
        )

        first_page = api.list_complaints(
            ANALYST_HEADERS,
            params=page_params(limit=2, offset=0, screening_area_id=state["area_id"]),
        )
        assert_array_envelope(first_page)
        assert_page(first_page, expected_rows=2, expected_total=3, expected_has_more=True)

        triage_dismiss(api, third["id"], "Outside agency jurisdiction")

        received = assert_page(
            api.list_complaints(
                ANALYST_HEADERS,
                params=page_params(
                    limit=10,
                    offset=0,
                    screening_area_id=state["area_id"],
                    status=COMPLAINT_RECEIVED,
                ),
            ),
            expected_rows=2,
            expected_total=2,
            expected_has_more=False,
        )
        for row in received:
            assert_field(row, "status", COMPLAINT_RECEIVED)

        dismissed = assert_page(
            api.list_complaints(
                ANALYST_HEADERS,
                params=page_params(
                    limit=10,
                    offset=0,
                    screening_area_id=state["area_id"],
                    status=COMPLAINT_DISMISSED,
                ),
            ),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
        assert_field(dismissed[0], "id", third["id"])
        assert_field(dismissed[0], "status", COMPLAINT_DISMISSED)

        assert_field(read_complaint(api, third["id"]), "status", COMPLAINT_DISMISSED)
        assert_field(read_area(api, state["area_id"]), "open_complaint_count", 2)


class TestRecertificationAfterEnforcement:
    """PRD §3.1 restores the data status but keeps the enforcement penalty."""

    def test_recertify_rescores_the_area_with_its_enforcement_points(
        self, api, area_a_inspection_pending
    ):
        """`STALE → CURRENT` re-runs both scoring passes, penalty included.

        PRD §3.8: "**Second**, that facility change adds **5 enforcement points**
        to the area's `enforcement_burden_points`, which feeds the penalty term of
        both screening score variants; both scores are recomputed, `designation` is
        re-evaluated with all the consequences of §3.1, and `data_status` is driven
        to `STALE`."
        PRD §3.1: "Only a `ProgramAdmin` can bring it back: **recertifying** a
        screening area moves `data_status` `STALE → CURRENT`, recomputes both
        screening score variants, re-evaluates designation, and increments the
        area's `version` by 1."
        PRD §3.1: "Then add the enforcement penalty — the area's
        `enforcement_burden_points` multiplied by 0.50 — take the smaller of 100.00
        and that sum, and round half up to two decimals for the final score."

        Design: Corner/calculations/recertify_stale_area_rescores_with_enforcement_points
        """
        state = area_a_inspection_pending
        complete_inspection(
            api, state["inspection_id"], FINDING_VIOLATION_CONFIRMED, "Thermal oxidizer bypassed"
        )
        stale = read_area(api, state["area_id"])
        assert_field(stale, "data_status", DATA_STATUS_STALE)
        assert_field(stale, "enforcement_burden_points", ENFORCEMENT_POINTS_PER_VIOLATION)

        response = api.recertify_screening_area(state["area_id"], ADMIN_HEADERS)

        recertified = validate_success(response)
        assert_fields(
            recertified,
            {
                "data_status": DATA_STATUS_CURRENT,
                "enforcement_burden_points": ENFORCEMENT_POINTS_PER_VIOLATION,
                "designation": DESIGNATION_OVERBURDENED,
                "active_indicator_count": 4,
            },
        )
        # 74.03 and 39.68 before the violation, each lifted by 5 x 0.50 points.
        assert_area_scores(recertified, statewide=76.53, county=42.18)

        stored = read_area(api, state["area_id"])
        assert_field(stored, "data_status", DATA_STATUS_CURRENT)
        assert_area_scores(stored, statewide=76.53, county=42.18)

        facility = read_facility(api, state["facility_id"])
        assert_field(facility, "compliance_status", COMPLIANCE_VIOLATION_ON_RECORD)
        assert_field(facility, "confirmed_violation_count", 1)
