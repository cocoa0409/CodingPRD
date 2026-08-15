"""Post-exposure prophylaxis lifecycle and the serology follow-up program."""
from test_helpers import (
    ApiErrorId,
    assert_instant,
    assert_pep_regimen,
    assert_serology_followup,
    create_exposure_case,
    get_case_followup,
    get_case_pep,
    get_employee,
    get_exposure_case,
    list_case_followups,
    list_restrictions,
    make_staff_employee_headers,
    register_employee,
    set_clock,
    setup_case_with_pep_started,
    start_pep,
    validate_error,
    validate_paginated,
    validate_success,
)

EXPOSURE = "2026-07-30T10:00:00Z"


class TestPepWindowBoundary:
    def test_start_exactly_at_window_deadline_succeeds(self, api,
                                                       physician_headers):
        """PRD §3.5: "Starting is eligible only while the current logical time
        is no later than the window deadline — the boundary is inclusive, so
        starting exactly at the deadline succeeds, and any later attempt is
        rejected with `ERR_PEP_WINDOW_EXPIRED`." and "A prophylaxis regimen
        begins `RECOMMENDED`, with its `window_deadline` set exactly
        seventy-two hours after the parent case's `exposure_datetime`."

        Design: Difficulty/boundary_precision_check/pep_window_inclusive_start_strict_expiry
        """
        emp = register_employee("E-BP1", full_name="Win Dow", department="ED")
        set_clock("2026-08-10T10:00:00Z")
        case = create_exposure_case(
            emp["id"], exposure_datetime="2026-08-10T09:00:00Z",
            source_known=False, body_fluid="BLOOD",
        )
        pep = get_case_pep(case["id"])
        assert_instant(pep["window_deadline"], "2026-08-13T09:00:00")

        set_clock("2026-08-13T09:00:00Z")
        started = start_pep(pep["id"], "2026-08-13T09:00:00Z")
        assert started["status"] == "STARTED", (
            "starting exactly at the deadline succeeds (inclusive boundary)"
        )
        assert_instant(started["started_at"], "2026-08-13T09:00:00")

    def test_auto_expiry_fires_only_strictly_after_deadline(self, api,
                                                            physician_headers):
        """PRD §3.5: "If the clock advances strictly past the `window_deadline`
        while the regimen is still `RECOMMENDED`, the regimen automatically
        becomes `WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/pep_window_inclusive_start_strict_expiry
        """
        emp = register_employee("E-BP1B", full_name="Win Dow Two", department="ED")
        set_clock("2026-08-10T10:00:00Z")
        case = create_exposure_case(
            emp["id"], exposure_datetime="2026-08-10T09:00:00Z",
            source_known=False, body_fluid="BLOOD",
        )
        pep = get_case_pep(case["id"])

        # At now == deadline the strict greater-than is not met.
        set_clock("2026-08-13T09:00:00Z")
        at_deadline = validate_success(api.get_pep_regimen(pep["id"], physician_headers))
        assert at_deadline["status"] == "RECOMMENDED"

        # One second past the deadline the regimen auto-expires.
        set_clock("2026-08-13T09:00:01Z")
        after = validate_success(api.get_pep_regimen(pep["id"], physician_headers))
        assert after["status"] == "WINDOW_EXPIRED"


class TestPepCourseLength:
    def test_completion_requires_full_28_day_course(self, api,
                                                    physician_headers):
        """PRD §3.5: "Completion requires a full course: the physician's
        transition to `COMPLETED` is permitted only from `STARTED`, and is
        rejected with `ERR_PEP_COURSE_INCOMPLETE` unless the current logical
        time has reached or passed the instant twenty-eight days after
        `started_at` — again an inclusive boundary."

        Design: Corner/state_machines/pep_complete_course_length_boundary
        """
        _emp, case, pep = setup_case_with_pep_started("E-SM18")

        set_clock("2026-08-11T12:00:00Z")  # started_at + 10 days
        early = api.transition_pep_regimen(
            pep["id"], {"to_state": "COMPLETED"}, physician_headers
        )
        validate_error(early, ApiErrorId.ERR_PEP_COURSE_INCOMPLETE)

        set_clock("2026-08-29T12:00:00Z")  # started_at + 28 days exactly
        done = validate_success(api.transition_pep_regimen(
            pep["id"], {"to_state": "COMPLETED"}, physician_headers
        ))
        assert done["status"] == "COMPLETED", (
            "at started_at + 28 days exactly the inclusive boundary permits completion"
        )


class TestPepStateBeatsSafety:
    def test_start_on_declined_regimen_yields_invalid_state(self, api,
                                                            physician_headers):
        """PRD §3.5: "Any regimen transition requested from a status other than
        the valid from-state — starting a regimen that is not `RECOMMENDED`,
        completing one that is not `STARTED`, declining one that is not
        `RECOMMENDED` — is rejected with `ERR_INVALID_STATE`."
        PRD §2.8: "Every endpoint applies its checks in a single pinned order,
        and a failure surfaces the error of the earliest failing category
        rather than a later one." (state legality precedes safety gates).

        Design: Difficulty/priority_pair_validation_conflict/pep_start_state_beats_safety
        """
        emp = register_employee("E-PP1", full_name="Pri Ority")
        case = create_exposure_case(emp["id"], exposure_datetime=EXPOSURE,
                                    source_known=False, body_fluid="BLOOD")
        pep = get_case_pep(case["id"])

        # The exposed employee themself declines (clock still inside the 72h
        # window, so no auto-expiry interferes).
        declined = validate_success(api.transition_pep_regimen(
            pep["id"], {"to_state": "DECLINED"},
            make_staff_employee_headers(emp["id"]),
        ))
        assert declined["status"] == "DECLINED"

        # started_at is past the 2026-08-02T10:00:00Z deadline AND in the
        # future — but the state check fires first.
        resp = api.transition_pep_regimen(
            pep["id"],
            {"to_state": "STARTED", "started_at": "2026-08-05T12:00:00Z"},
            physician_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_pep_regimen(pep["id"], physician_headers))
        assert after["status"] == "DECLINED"

    def test_start_on_window_expired_regimen_yields_invalid_state(self, api,
                                                                  physician_headers):
        """PRD §3.5: "Any regimen transition requested from a status other than
        the valid from-state — starting a regimen that is not `RECOMMENDED`,
        completing one that is not `STARTED`, declining one that is not
        `RECOMMENDED` — is rejected with `ERR_INVALID_STATE`." and "If the
        clock advances
        strictly past the `window_deadline` while the regimen is still
        `RECOMMENDED`, the regimen automatically becomes `WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/pep_start_state_beats_safety
        """
        emp = register_employee("E-PP1W", full_name="Pri Expired")
        case = create_exposure_case(emp["id"], exposure_datetime=EXPOSURE,
                                    source_known=False, body_fluid="BLOOD")
        pep = get_case_pep(case["id"])

        # Past the 2026-08-02T10:00:00Z deadline: the regimen auto-expires.
        set_clock("2026-08-03T00:00:00Z")
        expired = validate_success(api.get_pep_regimen(pep["id"], physician_headers))
        assert expired["status"] == "WINDOW_EXPIRED"

        resp = api.transition_pep_regimen(
            pep["id"],
            {"to_state": "STARTED", "started_at": "2026-08-01T12:00:00Z"},
            physician_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_pep_regimen(pep["id"], physician_headers))
        assert after["status"] == "WINDOW_EXPIRED"


class TestPepStartSideEffects:
    def test_start_spawns_followups_and_injury_report(self, api, safety_headers):
        """PRD §3.5: "Two automatic creations accompany a start: serology
        follow-ups for the `WEEK_6`, `WEEK_12`, and `MONTH_6` milestones appear
        in `SCHEDULED` status, and an injury report is filed automatically with
        `origin` `PEP_LINKAGE`, `injury_type` `NEEDLESTICK`, `injury_datetime`
        taken from the case's `exposure_datetime`, status `FILED`, and the case
        linked"

        Design: Corner/complexity_layers/pep_start_spawns_followups_and_injury
        """
        emp = register_employee("E-L2", full_name="Spawn Fx", department="ED")
        case = create_exposure_case(emp["id"], exposure_datetime=EXPOSURE,
                                    source_known=False, body_fluid="BLOOD")
        set_clock("2026-08-01T12:00:00Z")
        pep = get_case_pep(case["id"])
        started = start_pep(pep["id"], "2026-08-01T12:00:00Z")
        assert_instant(started["started_at"], "2026-08-01T12:00:00")

        followups = list_case_followups(case["id"])
        milestones = {row["milestone"] for row in followups}
        assert milestones == {"BASELINE", "WEEK_6", "WEEK_12", "MONTH_6"}
        for row in followups:
            assert_serology_followup(row)
            assert row["status"] in {"SCHEDULED", "DUE"}

        resp = api.list_injury_reports(
            safety_headers, params={"exposure_case_id": case["id"]}
        )
        injuries, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        injury = injuries[0]
        assert injury["origin"] == "PEP_LINKAGE"
        assert injury["injury_type"] == "NEEDLESTICK"
        assert injury["status"] == "FILED"
        assert_instant(injury["injury_datetime"], "2026-07-30T10:00:00")
        # PRD §3.8: a NEEDLESTICK injury is recordable.
        assert injury["osha_recordable"] is True


class TestSerologySchedule:
    def test_schedule_dates_computed_from_exposure(self, api, nurse_headers):
        """PRD §3.5: "The `BASELINE` milestone is scheduled at the
        `exposure_datetime` itself; `WEEK_6` is scheduled forty-two days after
        the exposure, `WEEK_12` at eighty-four days, and `MONTH_6` at one
        hundred eighty-three days — each follow-up's `scheduled_date`. Every
        follow-up carries a window: `window_open` is seven days before its
        `scheduled_date` (for `BASELINE`, the `window_open` is the
        `exposure_datetime`), and `window_close` is twenty-eight days after its
        `scheduled_date`."

        Design: Corner/calculations/serology_schedule_dates_literal
        """
        emp = register_employee("E-CL3", full_name="Sched Ule", department="ED")
        case = create_exposure_case(emp["id"], exposure_datetime=EXPOSURE,
                                    source_known=False, body_fluid="BLOOD")
        set_clock("2026-08-01T12:00:00Z")
        pep = get_case_pep(case["id"])
        start_pep(pep["id"], "2026-08-01T12:00:00Z")

        followups = list_case_followups(case["id"])
        assert len(followups) == 4
        by_milestone = {row["milestone"]: row for row in followups}

        week6 = by_milestone["WEEK_6"]
        assert_instant(week6["scheduled_date"], "2026-09-10T10:00:00")
        assert_instant(week6["window_open"], "2026-09-03T10:00:00")
        assert_instant(week6["window_close"], "2026-10-08T10:00:00")
        assert week6["status"] == "SCHEDULED"

        assert_instant(by_milestone["WEEK_12"]["scheduled_date"], "2026-10-22T10:00:00")
        # 183 days after 2026-07-30T10:00:00Z.
        assert_instant(by_milestone["MONTH_6"]["scheduled_date"], "2027-01-29T10:00:00")

        baseline = by_milestone["BASELINE"]
        assert_instant(baseline["scheduled_date"], "2026-07-30T10:00:00")
        assert_instant(baseline["window_open"], "2026-07-30T10:00:00")
        assert baseline["status"] == "DUE", (
            "after the clock advance, now >= window_open flips BASELINE to DUE"
        )


class TestSerologyResultAndWaiveGates:
    def test_result_while_scheduled_rejected(self, api, nurse_headers):
        """PRD §3.5: "Resulting requires the follow-up to be `DUE` or
        `OVERDUE`; attempting it from `SCHEDULED` — or from a terminal state —
        is rejected with `ERR_FOLLOWUP_NOT_DUE`."

        Design: Corner/state_machines/serology_result_while_scheduled_rejected
        """
        _emp, case, _pep = setup_case_with_pep_started("E-SM7")
        week6 = get_case_followup(case["id"], "WEEK_6")
        assert week6["status"] == "SCHEDULED", (
            "window_open 2026-09-03T10:00:00Z not yet reached at 2026-08-01T12:00:00Z"
        )

        resp = api.transition_serology_followup(
            week6["id"],
            {"to_state": "RESULTED", "result": "NEGATIVE",
             "resulted_at": "2026-08-01T11:00:00Z"},
            nurse_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FOLLOWUP_NOT_DUE)

        after = validate_success(api.get_serology_followup(week6["id"], nurse_headers))
        assert after["status"] == "SCHEDULED"
        assert after["result"] == "PENDING"

    def test_waive_with_short_reason_rejected(self, api, physician_headers,
                                              nurse_headers):
        """PRD §3.5: "A physician may instead waive a follow-up from `DUE` or
        `OVERDUE` by submitting `to_state` `WAIVED` with a `reason` of at least
        ten characters (`ERR_INSUFFICIENT_JUSTIFICATION`)."

        Design: Corner/state_machines/serology_waive_short_reason_rejected
        """
        emp = register_employee("E-SM8", full_name="Waive Short", job_category="TECH",
                                department="LAB")
        case = create_exposure_case(
            emp["id"], exposure_type="SKIN_CONTACT", exposure_datetime=EXPOSURE,
            source_known=False, body_fluid="NON_INFECTIOUS",
        )
        # BASELINE window_open is the exposure datetime; one second of clock
        # advance evaluates it into DUE (inclusive boundary).
        set_clock("2026-08-01T00:00:01Z")
        baseline = get_case_followup(case["id"], "BASELINE")
        assert baseline["status"] == "DUE"

        resp = api.transition_serology_followup(
            baseline["id"], {"to_state": "WAIVED", "reason": "short"},
            physician_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_JUSTIFICATION)

        after = validate_success(api.get_serology_followup(baseline["id"], nurse_headers))
        assert after["status"] == "DUE"


class TestSeroconversionCascade:
    def test_positive_week6_result_seroconverts_case(self, api, nurse_headers,
                                                     physician_headers):
        """PRD §3.5: "A `POSITIVE` result on any milestone other than
        `BASELINE` triggers the seroconversion cascade: the parent case
        transitions automatically from `REPORTED`, `EVALUATION`, or
        `MANAGEMENT` to `SEROCONVERTED`; the system auto-creates a work
        restriction of type `FULL_EXCLUSION` for the employee with `start_date`
        set to the follow-up's `resulted_at`, no `end_date` (open-ended), and
        `origin` `SEROCONVERSION`; the employee's `open_restriction_count`
        increments by one; and the posture recomputes, yielding `WORK_EXCLUDED`
        unless a hold already places the employee `ON_HOLD`."

        Design: Difficulty/transitive_cascade/serology_positive_seroconversion_cascade
        """
        emp, case, _pep = setup_case_with_pep_started("E-TC2")

        # BASELINE is DUE after the clock advance; result it NEGATIVE first.
        # resulted_at must be no later than the current logical time
        # (2026-08-01T12:00:00Z, set by setup) per PRD §3.5 — use exactly now.
        baseline = get_case_followup(case["id"], "BASELINE")
        assert baseline["status"] == "DUE"
        validate_success(api.transition_serology_followup(
            baseline["id"],
            {"to_state": "RESULTED", "result": "NEGATIVE",
             "resulted_at": "2026-08-01T12:00:00Z"},
            nurse_headers,
        ))
        assert get_exposure_case(case["id"])["case_status"] == "REPORTED", (
            "a NEGATIVE baseline leaves the case dimension untouched"
        )

        # At exactly window_open (2026-09-03T10:00:00Z, inclusive) WEEK_6 is DUE.
        set_clock("2026-09-03T10:00:00Z")
        week6 = get_case_followup(case["id"], "WEEK_6")
        assert week6["status"] == "DUE"

        validate_success(api.transition_serology_followup(
            week6["id"],
            {"to_state": "RESULTED", "result": "POSITIVE",
             "resulted_at": "2026-09-03T10:00:00Z"},
            nurse_headers,
        ))

        case_after = get_exposure_case(case["id"])
        assert case_after["case_status"] == "SEROCONVERTED"

        restrictions = list_restrictions(emp["id"], status="ACTIVE")
        assert len(restrictions) == 1
        restriction = restrictions[0]
        assert restriction["restriction_type"] == "FULL_EXCLUSION"
        assert restriction["origin"] == "SEROCONVERSION"
        assert_instant(restriction["start_date"], "2026-09-03T10:00:00")
        assert restriction["end_date"] is None

        emp_after = get_employee(emp["id"])
        assert emp_after["open_restriction_count"] == 1
        assert emp_after["compliance_posture"] == "WORK_EXCLUDED"

    def test_positive_baseline_result_carries_no_cascade(self, api,
                                                         nurse_headers,
                                                         physician_headers):
        """PRD §3.5: "A positive `BASELINE` result carries no such cascade —
        the conversion logic applies only to the post-baseline milestones."

        Design: Difficulty/transitive_cascade/serology_positive_seroconversion_cascade
        """
        emp = register_employee("E-TC2B", full_name="Base Pos", department="ED")
        case = create_exposure_case(emp["id"], exposure_datetime=EXPOSURE,
                                    source_known=False, body_fluid="BLOOD")
        set_clock("2026-08-01T00:00:01Z")
        baseline = get_case_followup(case["id"], "BASELINE")
        assert baseline["status"] == "DUE"

        resulted = validate_success(api.transition_serology_followup(
            baseline["id"],
            {"to_state": "RESULTED", "result": "POSITIVE",
             "resulted_at": "2026-08-01T00:00:01Z"},
            nurse_headers,
        ))
        assert resulted["status"] == "RESULTED"

        case_after = get_exposure_case(case["id"])
        assert case_after["case_status"] == "REPORTED", (
            "a POSITIVE baseline must not seroconvert the case"
        )
        assert list_restrictions(emp["id"], status="ACTIVE") == []
        emp_after = get_employee(emp["id"])
        assert emp_after["open_restriction_count"] == 0
        assert emp_after["compliance_posture"] == "CLEAR"
