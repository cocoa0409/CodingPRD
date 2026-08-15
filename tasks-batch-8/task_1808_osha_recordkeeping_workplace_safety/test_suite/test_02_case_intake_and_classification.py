"""Case intake, recordability determination, and the reclassification loop."""
from test_helpers import (
    ApiErrorId,
    add_day_entry,
    assert_case,
    classify_case,
    create_case,
    create_classified_case,
    create_company,
    create_employee,
    create_establishment,
    get_case,
    get_success_data,
    reclassify_case,
    set_clock,
    setup_org,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, COORDINATOR, OFFICER


class TestIntakeSystemFields:
    def test_case_intake_assigns_system_fields(self, api):
        """PRD §3.2: "As soon as the required intake fields validate, the
        system moves the case from `INTAKE` to `PENDING_REVIEW`, mints a
        per-establishment sequential `case_number` of the form
        `CASE-<establishment_seq>-<yyyy>-<nnn>`, stamps `reported_at` from the
        logical clock, fixes `log_year` to the calendar year of `occurred_at`
        — determining which 300 log carries the case — and computes the
        `recordability_deadline` as seven calendar days after `occurred_at`,
        inclusive of the deadline day."

        Design: Corner/entities/system_fields_ignored_on_input
        """
        _, establishment, employee = setup_org(fein="55-0000005",
                                               site_name="Site S")
        resp = api.create_case(
            {"establishment_id": establishment["id"],
             "employee_id": employee["id"],
             "occurred_at": "2025-12-31T10:00:00Z",
             "description": "Year-edge injury", "body_part": "arm",
             "event_type": "INJURY"},
            OFFICER)
        case = validate_success(resp, 201)
        assert_case(case)
        assert case["status"] == "PENDING_REVIEW", (
            "Intake auto-advances INTAKE -> PENDING_REVIEW")
        assert case["log_year"] == 2025, (
            "log_year derives from occurred_at (2025-12-31), not the clock")
        assert case["case_number"].startswith("CASE-"), (
            f"case_number must follow CASE-<establishment_seq>-<yyyy>-<nnn>, "
            f"got {case['case_number']!r}")
        assert "-2025-" in case["case_number"]

    def test_initial_state_pending_review(self, api):
        """PRD §3.2: "A fresh case has `classification` `NONE`, `is_recordable`
        and `is_dart` both false, and `revision_index` zero."

        Design: Corner/state_machines/initial_state_intake_pending_review
        """
        _, establishment, employee = setup_org(fein="12-0000010",
                                               site_name="Site IS")
        case = create_case(establishment["id"], employee["id"],
                           "2026-07-30T10:00:00Z")
        assert case["status"] == "PENDING_REVIEW"
        assert case["classification"] == "NONE"
        assert case["is_recordable"] is False
        assert case["is_dart"] is False
        assert case["revision_index"] == 0

    def test_establishment_cases_reverse_listing(self, api):
        """PRD §3.2: "The cases of an establishment can be listed with
        optional `status` and `log_year` filters"

        Design: Corner/entities/fk_reverse_reachability_lists
        """
        company, establishment, employee = setup_org(fein="77-0000007",
                                                     site_name="Site F")
        case = create_case(establishment["id"], employee["id"],
                           "2026-07-30T10:00:00Z")
        data = get_success_data(
            api.list_establishment_cases(establishment["id"], OFFICER))
        assert [c["id"] for c in data] == [case["id"]]

        second_est = get_success_data(api.create_establishment(
            {"company_id": company["id"], "site_name": "Empty Site",
             "naics_code": "332710", "state_code": "OH",
             "size_class": "SMALL"}, ADMIN))
        empty = get_success_data(
            api.list_establishment_cases(second_est["id"], OFFICER))
        assert empty == [], "An establishment with no cases lists empty"


class TestIntakeReferentialIntegrity:
    def test_cross_company_employee_reference_rejected(self, api):
        """PRD §3.2: "The employee must belong to the same company as the
        establishment; a cross-company pairing is rejected with
        `ERR_CROSS_COMPANY_REFERENCE`."

        Design: Corner/validations/cross_company_employee_reference_rejected
        """
        co_a = create_company(legal_name="Co Alpha", fein="02-0000020")
        co_b = create_company(legal_name="Co Beta", fein="02-0000021")
        emp_a = create_employee(co_a["id"], full_name="Alpha Worker")
        est_b = create_establishment(co_b["id"], site_name="Beta Site")
        resp = api.create_case(
            {"establishment_id": est_b["id"], "employee_id": emp_a["id"],
             "occurred_at": "2026-08-01T10:00:00Z", "description": "X-co",
             "body_part": "arm", "event_type": "INJURY"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_CROSS_COMPANY_REFERENCE)

    def test_exempt_establishment_blocks_classification(self, api):
        """PRD §3.2: "An establishment flagged `is_partially_exempt` does not
        keep a 300 log, so classification there is refused with
        `ERR_ESTABLISHMENT_EXEMPT` — severe-injury reporting obligations
        nonetheless remain."
        PRD §3.6: "When a case's `is_severe_event` is anything other than
        `NONE`, federal reporting clocks apply — even at partially exempt
        establishments, which keep no 300 log but must still report."

        Design: Corner/validations/exempt_establishment_blocks_classification
        """
        _, establishment, employee = setup_org(
            fein="01-0000019", site_name="Retail Kiosk", naics_code="452210",
            is_partially_exempt=True)
        set_clock("2026-08-01T12:00:00Z")
        case = create_case(establishment["id"], employee["id"],
                           "2026-08-01T10:00:00Z",
                           is_severe_event="AMPUTATION")
        resp = api.classify_case(
            case["id"],
            {"classification": "MEDICAL_TREATMENT",
             "expected_case_version": case["version"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_ESTABLISHMENT_EXEMPT)

        report = get_success_data(api.create_severe_report(
            case["id"],
            {"report_kind": "AMPUTATION",
             "occurred_at": "2026-08-01T10:00:00Z",
             "reported_to_agency_at": "2026-08-01T20:00:00Z"},
            OFFICER))
        assert report["status"] == "TIMELY", (
            "Severe-injury reporting remains available at an exempt "
            "establishment")


class TestTerminalAndInvalidTransitions:
    def test_terminal_state_lockdown_not_recordable(self, api):
        """PRD §3.2: "classifying with `FIRST_AID_ONLY` moves it to
        `NOT_RECORDABLE`, a terminal state."
        PRD §2.9: "Fourth, state admissibility: the target resource must
        currently sit in a state from which the requested transition exists,
        failing with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_not_recordable
        """
        _, establishment, employee = setup_org(fein="99-0000009",
                                               site_name="Site TL")
        case = create_case(establishment["id"], employee["id"],
                           "2026-07-30T10:00:00Z")
        classified = classify_case(case["id"], "FIRST_AID_ONLY")
        assert classified["status"] == "NOT_RECORDABLE"

        resp = api.reclassify_case(
            case["id"],
            {"expected_case_version": classified["version"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_day_count_invalid_from_pending_review(self, api):
        """PRD §3.3: "Day counting closes — `day_count_closed` turns true —
        under any of three conditions: a `SafetyOfficer` explicitly closes the
        count when the worker returns to full duty, a version-checked
        operation carrying `expected_case_version`"
        PRD §2.9: "Fourth, state admissibility: the target resource must
        currently sit in a state from which the requested transition exists,
        failing with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invalid_transition_finalize_from_intake_adjacent_states
        """
        _, establishment, employee = setup_org(fein="88-0000008",
                                               site_name="Site SM")
        case = create_case(establishment["id"], employee["id"],
                           "2026-07-30T10:00:00Z")
        resp = api.close_day_count(
            case["id"], {"expected_case_version": case["version"]}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_case(case["id"])["status"] == "PENDING_REVIEW"


class TestRecordabilityWindow:
    def _past_window_case(self):
        _, establishment, employee = setup_org(fein="55-6667778",
                                               site_name="Terminal 2")
        set_clock("2026-08-01T10:00:00Z")
        case = create_case(establishment["id"], employee["id"],
                           "2026-08-01T08:00:00Z")
        set_clock("2026-08-10T00:00:00Z")
        return case

    def test_classify_past_recordability_window_rejected(self, api):
        """PRD §3.2: "The determination must land by the
        `recordability_deadline`; a late attempt fails with
        `ERR_RECORDABILITY_WINDOW_PASSED`, with a single carve-out: a `DEATH`
        classification is accepted even after the window."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_classify
        """
        case = self._past_window_case()
        assert case["recordability_deadline"].startswith("2026-08-08"), (
            "Deadline is occurred_at + 7 calendar days (2026-08-01 -> "
            "2026-08-08)")
        resp = api.classify_case(
            case["id"],
            {"classification": "MEDICAL_TREATMENT",
             "expected_case_version": case["version"]},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_RECORDABILITY_WINDOW_PASSED)
        assert get_case(case["id"])["status"] == "PENDING_REVIEW"

    def test_classify_death_accepted_after_window(self, api):
        """PRD §3.2: "The determination must land by the
        `recordability_deadline`; a late attempt fails with
        `ERR_RECORDABILITY_WINDOW_PASSED`, with a single carve-out: a `DEATH`
        classification is accepted even after the window."
        PRD §3.2: "A recordable classification sets `is_recordable` true and
        sets `is_dart` true exactly when the class is
        `JOB_TRANSFER_RESTRICTION`, `DAYS_AWAY`, or `DEATH`"

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_classify
        """
        case = self._past_window_case()
        resp = api.classify_case(
            case["id"],
            {"classification": "DEATH",
             "expected_case_version": case["version"]},
            OFFICER)
        classified = validate_success(resp, 200)
        assert classified["status"] == "RECORDABLE"
        assert classified["is_recordable"] is True
        assert classified["is_dart"] is True


class TestReclassificationLoop:
    def _recordable_case_with_entry(self, fein="55-5656565"):
        _, establishment, employee = setup_org(fein=fein, site_name="Shop 3")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-02T10:00:00Z",
            classification="MEDICAL_TREATMENT",
            clock_iso="2026-08-03T09:00:00Z")
        add_day_entry(case["id"], "RESTRICTED", "2026-08-03", "2026-08-05")
        return case

    def test_reclassification_single_loop(self, api):
        """PRD §3.2: "The case moves to `RECLASSIFIED`, `revision_index`
        increments, existing `ACTIVE` day entries survive, and fresh entries
        may still be attached while the case sits in `RECLASSIFIED`."
        PRD §3.2: "From `RECLASSIFIED`, a fresh classification with any value
        different from the current one returns the case to `RECORDABLE` —
        repeating the current class is rejected with `ERR_INVALID_STATE`"

        Design: Difficulty/non_linear_state_machine/case_reclassification_cycle_loop
        """
        case = self._recordable_case_with_entry()
        reclassified = reclassify_case(case["id"])
        assert reclassified["status"] == "RECLASSIFIED"
        assert reclassified["revision_index"] == 1

        back = classify_case(case["id"], "DAYS_AWAY")
        assert back["status"] == "RECORDABLE"
        assert back["classification"] == "DAYS_AWAY"
        assert back["is_dart"] is True

    def test_reclassification_two_loops_revision_index(self, api):
        """PRD §3.2: "The full loop begins when a `SafetyOfficer` opens
        reclassification on a `RECORDABLE` case, which requires either at
        least one non-voided day-count entry on the case or a newly discovered
        fact documented as a `new_classification` in the request. The case
        moves to `RECLASSIFIED`, `revision_index` increments"
        PRD §3.2: "From `RECLASSIFIED`, a fresh classification with any value
        different from the current one returns the case to `RECORDABLE`"

        Design: Difficulty/non_linear_state_machine/case_reclassification_cycle_loop
        """
        case = self._recordable_case_with_entry(fein="55-5656566")
        first = reclassify_case(case["id"])
        assert first["revision_index"] == 1
        classify_case(case["id"], "DAYS_AWAY")

        second = reclassify_case(case["id"])
        assert second["status"] == "RECLASSIFIED"
        assert second["revision_index"] == 2, (
            "revision_index increments once per loop's opening leg")

        final = classify_case(case["id"], "MEDICAL_TREATMENT")
        assert final["status"] == "RECORDABLE"
        assert final["classification"] == "MEDICAL_TREATMENT"
        assert final["is_recordable"] is True
        assert final["is_dart"] is False
        assert final["revision_index"] == 2
