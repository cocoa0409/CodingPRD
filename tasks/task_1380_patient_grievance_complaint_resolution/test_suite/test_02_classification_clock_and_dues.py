"""Classification decisions, regulatory due computation, ack/breach clock,
the systemic-issue sweep, and OCC on the classification endpoint."""
from test_helpers import (
    api_client,
    ApiErrorId,
    classify_case,
    create_case,
    create_unit,
    get_case,
    get_case_version,
    get_success_data,
    register_holiday,
    set_clock,
    setup_open_investigation,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def _timeline(case_id):
    return get_success_data(api_client.get_case_timeline(case_id, INTAKE))


class TestDualVariantTimeline:
    def _setup_grievance_with_holiday(self, api):
        set_clock("2026-08-07T18:00:00.000Z")
        register_holiday("2026-08-17", "Founders Day")
        unit = create_unit("ICU North", "ICU")
        case = create_case(unit["id"], patient_ref="P-1001",
                           received_at="2026-08-07T16:00:00.000Z", channel="PHONE",
                           description="Medication delay during night shift",
                           grievance_category="CARE_QUALITY")
        classify_case(case["id"], "GRIEVANCE")
        return case

    def test_calendar_variant_and_ack_due(self, api):
        """PRD §3.2: "A `GRIEVANCE` must receive a written response within
        thirty calendar days of `received_at`" and "`ack_due_at` is exactly
        seven calendar days after `received_at`, always computed on the
        calendar variant, and stays null for complaints and unclassified
        cases." PRD §2.8: "Calendar-day arithmetic adds a number of whole days
        — each exactly 86,400 seconds — directly to a base instant, ignoring
        weekends and holidays; it backs the binding regulatory deadlines."

        Design: Difficulty/dual_variant_calc/case_timeline_calendar_vs_business_variants
        """
        case = self._setup_grievance_with_holiday(api)
        timeline = _timeline(case["id"])
        assert timeline["response_due_calendar_at"] == "2026-09-06T16:00:00.000Z", (
            "received 2026-08-07T16:00:00Z + 30 calendar days")
        assert timeline["ack_due_at"] == "2026-08-14T16:00:00.000Z", (
            "received + 7 calendar days (grievance acknowledgment window)")

    def test_business_variant_skips_weekends_and_holiday(self, api):
        """PRD §2.8: "Business-day arithmetic counts days beginning the day
        after the base date, skipping Saturdays, Sundays, and every registered
        `HolidayObservance` `observance_date`, and lands at the same time of
        day as the base instant; it backs internal workplan targets and filing
        windows." and "An identical base instant therefore yields a
        business-day due that is strictly later than — or equal to — the
        calendar due whenever the window contains a non-business day."

        Design: Difficulty/dual_variant_calc/case_timeline_calendar_vs_business_variants
        """
        case = self._setup_grievance_with_holiday(api)
        timeline = _timeline(case["id"])
        assert timeline["response_due_business_at"] == "2026-09-21T16:00:00.000Z", (
            "30 business days from 2026-08-07 skipping Sat/Sun and the "
            "2026-08-17 holiday")
        assert timeline["response_due_business_at"] != timeline["response_due_calendar_at"], (
            "dual variants must diverge on identical inputs here")


class TestRegulatoryWindows:
    def test_expedited_window_for_critical_grievance(self, api):
        """PRD §3.2: "A `GRIEVANCE` must receive a written response within
        thirty calendar days of `received_at`; the window shrinks to seven
        calendar days when the case is `severity_tier` `CRITICAL` or carries
        `alleged_abuse_flag`."

        Design: Corner/calculations/expedited_window_for_critical_grievance
        """
        set_clock("2026-08-03T12:00:00.000Z")
        unit = create_unit("ICU", "ICU")
        case = create_case(unit["id"], patient_ref="P-0202",
                           received_at="2026-08-03T10:00:00.000Z", channel="IN_PERSON",
                           description="Critical care concern",
                           grievance_category="CARE_QUALITY",
                           severity_tier="CRITICAL")
        classify_case(case["id"], "GRIEVANCE")
        timeline = _timeline(case["id"])
        assert timeline["response_due_calendar_at"] == "2026-08-10T10:00:00.000Z", (
            "seven calendar days")
        assert timeline["response_due_business_at"] == "2026-08-12T10:00:00.000Z", (
            "seven business days: Aug 4,5,6,7,10,11,12")
        assert timeline["ack_due_at"] == "2026-08-10T10:00:00.000Z"

    def test_complaint_window_three_days_no_ack_requirement(self, api):
        """PRD §3.2: "A `COMPLAINT` carries a three-day internal target through
        the same fields." and "`ack_due_at` is exactly seven calendar days
        after `received_at`, always computed on the calendar variant, and stays
        null for complaints and unclassified cases."

        Design: Corner/calculations/complaint_window_three_days_no_ack_requirement
        """
        set_clock("2026-08-03T12:00:00.000Z")
        unit = create_unit("Clinic", "OUTPATIENT")
        case = create_case(unit["id"], patient_ref="P-0203",
                           received_at="2026-08-03T10:00:00.000Z", channel="PORTAL",
                           description="Scheduling annoyance",
                           grievance_category="ACCESS_DELAY")
        classify_case(case["id"], "COMPLAINT")
        timeline = _timeline(case["id"])
        assert timeline["response_due_calendar_at"] == "2026-08-06T10:00:00.000Z"
        assert timeline["ack_due_at"] is None, (
            "ack requirement applies to grievances only")

    def test_ack_breach_boundary_exact_second(self, api):
        """PRD §3.5: "Otherwise, a grievance whose acknowledgment has not been
        recorded once the clock passes `ack_due_at` reads `ACK_BREACH`.
        Anything else reads `ON_TRACK`."

        Design: Corner/calculations/ack_breach_boundary_exact_second
        """
        set_clock("2026-08-03T12:00:00.000Z")
        unit = create_unit("ED Main", "EMERGENCY")
        case = create_case(unit["id"], patient_ref="P-0201",
                           received_at="2026-08-03T10:00:00.000Z", channel="PHONE",
                           description="Concern", grievance_category="OTHER")
        classify_case(case["id"], "GRIEVANCE")

        set_clock("2026-08-10T10:00:00.000Z")
        at_due = _timeline(case["id"])
        assert at_due["ack_due_at"] == "2026-08-10T10:00:00.000Z"
        assert at_due["regulatory_clock_status"] == "ON_TRACK", (
            "now == ack_due_at is not yet a breach (strict pass semantics)")

        set_clock("2026-08-10T10:00:01.000Z")
        past_due = _timeline(case["id"])
        assert past_due["regulatory_clock_status"] == "ACK_BREACH", (
            "one second past the acknowledgment deadline breaches")


class TestAcknowledge:
    def test_acknowledge_twice_rejected(self, api):
        """PRD §3.2: "It is accepted only while the case is neither `CLOSED`
        nor `WITHDRAWN` (otherwise `ERR_CASE_INVALID_STATE`) and only once — a
        second attempt meets `ERR_ALREADY_ACKNOWLEDGED`." and "Recording stamps
        `acknowledged_at` with the current clock and advances the case
        `version` by one"

        Design: Corner/validations/acknowledge_twice_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED", "EMERGENCY")
        case = create_case(unit["id"], patient_ref="P-0319",
                           received_at="2026-08-03T09:00:00.000Z", channel="PHONE",
                           description="Concern", grievance_category="OTHER")
        classify_case(case["id"], "GRIEVANCE")

        first = validate_success(api.acknowledge_case(case["id"], INTAKE))
        assert first["acknowledged_at"] == "2026-08-03T10:00:00.000Z"

        second = api.acknowledge_case(case["id"], INTAKE)
        validate_error(second, ApiErrorId.ERR_ALREADY_ACKNOWLEDGED)


class TestReclassification:
    def test_reclassification_recomputes_from_received_at(self, api):
        """PRD §3.2: "Every accepted decision advances the case `version` by
        one and recomputes the regulatory dues from `received_at`." and "the
        server stamps `decided_by_id` from the caller and links
        `supersedes_decision_id` to the case's previously current decision
        (null on the first)." PRD §3.5: "Otherwise, a grievance whose
        acknowledgment has not been recorded once the clock passes `ack_due_at`
        reads `ACK_BREACH`."

        Design: Corner/calculations/reclassification_recomputes_from_received_at
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED Main", "EMERGENCY")
        case = create_case(unit["id"], patient_ref="P-0206",
                           received_at="2026-08-03T09:00:00.000Z", channel="PHONE",
                           description="Initially minor concern",
                           grievance_category="STAFF_CONDUCT")
        first = classify_case(case["id"], "COMPLAINT")

        set_clock("2026-08-20T12:00:00.000Z")
        second = validate_success(api.create_classification_decision(
            case["id"],
            {"decision": "GRIEVANCE", "rationale_code": "ESCALATION_OF_CONCERN",
             "expected_case_version": get_case_version(case["id"])},
            INTAKE), expected_status=201)
        assert second["supersedes_decision_id"] == first["id"], (
            "supersede chain must link the new decision to the old")

        timeline = _timeline(case["id"])
        assert timeline["response_due_calendar_at"] == "2026-09-02T09:00:00.000Z", (
            "recomputed from received_at, not from the reclassification time")
        assert timeline["ack_due_at"] == "2026-08-10T09:00:00.000Z"
        assert timeline["regulatory_clock_status"] == "ACK_BREACH", (
            "ack deadline passed while the case was still a complaint")

    def test_reclassify_during_investigation_rejected(self, api):
        """PRD §3.2: "decisions may not be recorded on a `CLOSED` or
        `WITHDRAWN` case, and a downgrade from `GRIEVANCE` to `COMPLAINT` is
        accepted only while the case is still in `INTAKE` or `CLASSIFIED` —
        both violations surface as `ERR_CASE_INVALID_STATE`."

        Design: Corner/state_machines/reclassify_during_investigation_rejected
        """
        base = setup_open_investigation(
            unit_name="ICU", unit_category="ICU", patient_ref="P-0108",
            grievance_category="OTHER", description="Concern")
        assert base.case["lifecycle_status"] == "UNDER_INVESTIGATION"
        resp = api.create_classification_decision(
            base.case["id"],
            {"decision": "COMPLAINT", "rationale_code": "DIRECTOR_OVERRIDE",
             "expected_case_version": get_case_version(base.case["id"])},
            INTAKE)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


class TestOccOnClassification:
    def test_occ_stale_classification_version_rejected(self, api):
        """PRD §3.2: "Because decisions supersede legitimately, the recording
        request is OCC-guarded: it must carry `expected_case_version` equal to
        the case's current `version`, and a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412) before any business rule runs."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_classification_version_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED", "EMERGENCY")
        case = create_case(unit["id"], patient_ref="P-0601",
                           received_at="2026-08-03T09:00:00.000Z", channel="PHONE",
                           description="Concern", grievance_category="OTHER")
        stale_version = case["version"]

        first = api.create_classification_decision(
            case["id"],
            {"decision": "COMPLAINT", "rationale_code": "INITIAL_INTAKE",
             "expected_case_version": stale_version},
            INTAKE)
        validate_success(first, expected_status=201)

        second = api.create_classification_decision(
            case["id"],
            {"decision": "GRIEVANCE", "rationale_code": "ESCALATION_OF_CONCERN",
             "expected_case_version": stale_version},
            INTAKE)
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)

        after = get_case(case["id"])
        assert after["classification"] == "COMPLAINT", (
            "the stale supersede attempt must not have applied")


class TestSystemicIssueSweep:
    def _create_conduct_cases(self, count):
        set_clock("2026-08-10T12:00:00.000Z")
        unit = create_unit("Stepdown 3", "INPATIENT")
        cases = []
        for i in range(count):
            cases.append(create_case(
                unit["id"], patient_ref=f"P-81{i:02d}",
                received_at="2026-08-05T09:00:00.000Z", channel="PHONE",
                description=f"Nurse rudeness report {i}",
                grievance_category="STAFF_CONDUCT"))
        return cases

    def test_third_grievance_triggers_systemic_escalation(self, api):
        """PRD §3.2: "When that count reaches three — exactly three triggers
        the sweep's effect, two does not — and no `SYSTEMIC` escalation on any
        case of that unit and category currently stands in `FILED`, `IN_REVIEW`,
        or `REVIEWS_COMPLETE`, the system files a `SYSTEMIC` escalation on the
        newly classified case itself, with `source` `AUTO_SYSTEMIC_THRESHOLD`,
        `filed_by_id` recorded as 'system', and status `FILED` (§3.6)."

        Design: Difficulty/boundary_precision_check/third_grievance_triggers_systemic_escalation
        """
        c1, c2, c3 = self._create_conduct_cases(3)
        classify_case(c1["id"], "GRIEVANCE")
        classify_case(c2["id"], "GRIEVANCE")

        escalations_after_two, _ = validate_paginated(
            api.list_escalations(INTAKE, params={"case_id": c1["id"]}))
        assert escalations_after_two == [], (
            "two grievances must not trigger the sweep (boundary: 2 < 3)")

        classify_case(c3["id"], "GRIEVANCE")
        escalations, _ = validate_paginated(
            api.list_escalations(INTAKE, params={"case_id": c3["id"]}))
        assert len(escalations) == 1
        auto = escalations[0]
        assert auto["escalation_type"] == "SYSTEMIC"
        assert auto["source"] == "AUTO_SYSTEMIC_THRESHOLD"
        assert auto["status"] == "FILED"
        assert auto["filed_by_id"] == "system"

    def test_fourth_grievance_does_not_duplicate_open_systemic_escalation(self, api):
        """PRD §3.2: "When that count reaches three — exactly three triggers
        the sweep's effect, two does not — and no `SYSTEMIC` escalation on any
        case of that unit and category currently stands in `FILED`, `IN_REVIEW`,
        or `REVIEWS_COMPLETE`, the system files a `SYSTEMIC` escalation on the
        newly classified case itself, with `source` `AUTO_SYSTEMIC_THRESHOLD`,
        `filed_by_id` recorded as 'system', and status `FILED` (§3.6)."

        Design: Difficulty/boundary_precision_check/third_grievance_triggers_systemic_escalation
        """
        c1, c2, c3, c4 = self._create_conduct_cases(4)
        for case in (c1, c2, c3):
            classify_case(case["id"], "GRIEVANCE")
        # The third classification opened a SYSTEMIC escalation on c3.
        classify_case(c4["id"], "GRIEVANCE")

        escalations_c4, _ = validate_paginated(
            api.list_escalations(INTAKE, params={"case_id": c4["id"]}))
        assert escalations_c4 == [], (
            "an open SYSTEMIC escalation for the unit+category suppresses duplicates")
