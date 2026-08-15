"""Checkrides, segregation of duties, and the enrollment retraining loop."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_applicant,
    get_checkride,
    get_enrollment,
    get_success_data,
    list_ledger_entries,
    make_checkride,
    make_check_airman_headers,
    make_instructor,
    make_simulator_slot,
    pass_milestone,
    record_checkride,
    schedule_event,
    set_clock,
    setup_enrollment_at_checkride_phase,
    validate_error,
    validate_success,
)

TC = TEST_USERS["training_coordinator_headers"]
CS = TEST_USERS["crew_scheduler_headers"]


def _setup_remediation_ctx():
    """Enrollment at CHECKRIDE phase; one PRACTICAL ride recorded FAIL by a
    clean airman. Returns ctx carrying instructor (taught the milestones),
    examiner (clean airman), and the failed checkride."""
    ctx = setup_enrollment_at_checkride_phase(
        eq_kwargs={"code": "A321", "sim_rate": 45000, "ioe_hours": 10},
        ap_kwargs={"email": "fay@x.com", "license_number": "L030",
                   "full_name": "Fay Fenn", "hours": 3400, "age": 31},
        instructor_name="Kit Kage")
    examiner = make_instructor("Quin Qing", "CHECK_AIRMAN")
    ctx["examiner"] = examiner
    ck = make_checkride(ctx["enrollment"]["id"], examiner["id"],
                        scheduled_at="2026-08-12T09:00:00Z")
    set_clock("2026-08-12T09:00:00Z")
    record_checkride(ck["id"], "FAIL", examiner["id"])
    ctx["checkride"] = get_checkride(ck["id"])
    ctx["enrollment"] = get_enrollment(ctx["enrollment"]["id"])
    return ctx


class TestEnrollmentRetrainingLoop:
    def test_failed_checkride_cascades_enrollment_into_remediation(self, api):
        """PRD §3.3: "A failed checkride (§3.5) cascades the enrollment from
        `IN_PROGRESS` to `REMEDIATION`, stamping `entered_remediation_at` and
        recomputing `failed_attempts` as the count of the enrollment's
        `COMPLETED_FAIL` checkrides."
        PRD §3.5: "An `outcome` of `FAIL` moves the checkride `SCHEDULED` →
        `COMPLETED_FAIL`, stamps `completed_at`, books the same flat `CHECKRIDE`
        charge as a pass, and then fires a three-link cascade."

        Design: Difficulty/non_linear_state_machine/enrollment_retraining_loop_cycle
        """
        ctx = _setup_remediation_ctx()
        assert ctx["checkride"]["status"] == "COMPLETED_FAIL"
        assert ctx["checkride"]["completed_at"] is not None
        enrollment = ctx["enrollment"]
        assert enrollment["status"] == "REMEDIATION", (
            "Link 1: the enrollment enters remediation")
        assert enrollment["failed_attempts"] == 1
        assert enrollment["entered_remediation_at"] is not None

    def test_passing_remediation_milestone_closes_the_loop(self, api):
        """PRD §3.3: "Resuming moves `REMEDIATION` → `IN_PROGRESS` only when a
        passing remediation milestone exists — a training event of the
        enrollment with `event_type` `MILESTONE`, status `COMPLETED`, and
        `score` at least 80 whose `updated_at` is later than
        `entered_remediation_at` — otherwise the resume is rejected with
        `ERR_PHASE_PREREQUISITE_NOT_MET` (422)."
        PRD §3.8: "A ground-school event, completed or failed, bills a flat
        150,000 cents per session as a `GROUND_SCHOOL` entry. A simulator event
        bills its duration — the exact elapsed time between `scheduled_start`
        and `scheduled_end`, expressed in hours as an exact decimal —
        multiplied by the fleet's `simulator_cost_per_hour_cents`, as a
        `SIMULATOR` entry."
        PRD §3.5: "Link 2, caused by the enrollment entering remediation, books
        a `RETRAINING` ledger charge equal to the 120,000-cent checkride fee
        multiplied by the 0.25 surcharge rate and rounded half-up — 30,000
        cents."

        Design: Difficulty/non_linear_state_machine/enrollment_retraining_loop_cycle
        """
        ctx = _setup_remediation_ctx()
        en_id = ctx["enrollment"]["id"]
        # Remediation milestone: an earlier phase is allowed while REMEDIATION.
        slot2 = make_simulator_slot(ctx["equipment"]["id"],
                                    "2026-08-13T08:00:00Z", "2026-08-13T18:00:00Z")
        pass_milestone(en_id, ctx["instructor"]["id"], "SIMULATOR",
                       "2026-08-13T09:00:00Z", "2026-08-13T11:00:00Z",
                       score=90, slot_id=slot2["id"])
        resumed = validate_success(api.resume_enrollment(en_id, TC))
        assert resumed["status"] == "IN_PROGRESS", "The retraining loop closes"
        assert resumed["failed_attempts"] == 1

        balance = get_applicant(ctx["applicant"]["id"])["ledger_balance_cents"]
        # 150000 (GROUND milestone flat) + 90000 (SIM milestone 2h*45000)
        # + 120000 (CHECKRIDE) + 30000 (RETRAINING) + 90000 (remediation SIM)
        assert balance == 480000


class TestStateBeatsSafetyOnRecordOutcome:
    def _setup_conflicted_ride(self):
        """Enrollment at CHECKRIDE phase; clean airman ca3 takes the ride,
        then ca3 instructs a CHECKRIDE-phase session (becoming conflicted)."""
        ctx = setup_enrollment_at_checkride_phase(
            eq_kwargs={"code": "B739", "sim_rate": 45000, "ioe_hours": 10},
            ap_kwargs={"email": "ned@x.com", "license_number": "L070",
                       "full_name": "Ned Ogg", "hours": 3900, "age": 29},
            instructor_name="Ora Gnd")
        ca3 = make_instructor("Rea Vew", "CHECK_AIRMAN")
        ctx["examiner"] = ca3
        ck = make_checkride(ctx["enrollment"]["id"], ca3["id"],
                            scheduled_at="2026-08-12T09:00:00Z")
        ctx["checkride"] = ck
        # ca3 instructs a CHECKRIDE-phase session (tier CHECK_AIRMAN covers the
        # phase), becoming conflicted for the ride.
        schedule_event(ctx["enrollment"]["id"], ca3["id"], "CHECKRIDE",
                       "SESSION", "2026-08-11T15:00:00Z", "2026-08-11T16:00:00Z")
        return ctx

    def test_withdrawn_enrollment_state_error_wins_over_conflict(self, api):
        """PRD §3.5: "The remaining checks then run in order — the checkride
        must be `SCHEDULED` (else `ERR_CHECKRIDE_INVALID_STATE`, 409), the
        enrollment must be `IN_PROGRESS` or `REMEDIATION` (else
        `ERR_ENROLLMENT_INVALID_STATE`), the segregation-of-duties re-check
        fires, and finally the medical gate: when the applicant holds a
        qualification for the class's equipment, its `operating_state` must not
        be `GROUNDED`, otherwise `ERR_MEDICAL_GROUNDED`."
        PRD §3.3: "Scheduled checkrides are explicitly not cancelled by
        withdrawal — only an explicit checkride cancellation does that."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_checkride_record_outcome
        """
        ctx = self._setup_conflicted_ride()
        # Withdraw the enrollment; the ride stays SCHEDULED per the pin above.
        get_success_data(api.withdraw_enrollment(ctx["enrollment"]["id"], TC))
        set_clock("2026-08-12T09:00:00Z")
        resp = api.record_checkride_outcome(
            ctx["checkride"]["id"], {"outcome": "PASS"},
            make_check_airman_headers(ctx["examiner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE)
        ride = validate_success(api.get_checkride(ctx["checkride"]["id"], TC))
        assert ride["status"] == "SCHEDULED", (
            "A rejected outcome recording leaves the ride untouched")

    def test_conflict_alone_rejects_outcome_recording(self, api):
        """PRD §3.5: "Segregation of duties is enforced twice: at scheduling
        and again at outcome recording, the check airman must not have
        instructed any non-cancelled training event of the same enrollment. A
        conflict is rejected with `ERR_CHECK_AIRMAN_CONFLICT` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_checkride_record_outcome
        """
        ctx = self._setup_conflicted_ride()
        # No withdrawal: the enrollment stays IN_PROGRESS, so only the
        # segregation-of-duties failure is live at outcome time.
        set_clock("2026-08-12T09:00:00Z")
        resp = api.record_checkride_outcome(
            ctx["checkride"]["id"], {"outcome": "PASS"},
            make_check_airman_headers(ctx["examiner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECK_AIRMAN_CONFLICT)


class TestCheckrideRules:
    def test_checkride_double_outcome_rejected(self, api):
        """PRD §3.5: "A coordinator may cancel a `SCHEDULED` checkride, which
        becomes `CANCELLED`; any action against a ride no longer scheduled is
        rejected with `ERR_CHECKRIDE_INVALID_STATE`."

        Design: Corner/state_machines/checkride_double_outcome_rejected
        """
        ctx = setup_enrollment_at_checkride_phase(
            eq_kwargs={"code": "MD90", "sim_rate": 40000, "ioe_hours": 8},
            ap_kwargs={"email": "dbl@x.com", "license_number": "L416",
                       "full_name": "Dbl Out", "hours": 3000},
            instructor_name="Air One")
        examiner = make_instructor("Air Two", "CHECK_AIRMAN")
        ck = make_checkride(ctx["enrollment"]["id"], examiner["id"],
                            scheduled_at="2026-08-12T09:00:00Z")
        set_clock("2026-08-12T09:00:00Z")
        passed = record_checkride(ck["id"], "PASS", examiner["id"])
        assert passed["status"] == "COMPLETED_PASS"
        resp = api.record_checkride_outcome(
            ck["id"], {"outcome": "FAIL"},
            make_check_airman_headers(examiner["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKRIDE_INVALID_STATE)

    def test_check_airman_conflict_at_creation(self, api):
        """PRD §3.5: "Segregation of duties is enforced twice: at scheduling
        and again at outcome recording, the check airman must not have
        instructed any non-cancelled training event of the same enrollment. A
        conflict is rejected with `ERR_CHECK_AIRMAN_CONFLICT` (422)."

        Design: Corner/validations/check_airman_conflict_at_creation
        """
        ctx = setup_enrollment_at_checkride_phase(
            eq_kwargs={"code": "B732", "sim_rate": 38000, "ioe_hours": 8},
            ap_kwargs={"email": "con@x.com", "license_number": "L439",
                       "full_name": "Con Flict"},
            instructor_name="Tea Ch")
        # The instructor who taught both milestones may not examine the ride.
        resp = api.create_checkride(
            {"enrollment_id": ctx["enrollment"]["id"],
             "check_airman_id": ctx["instructor"]["id"],
             "ride_type": "PRACTICAL",
             "scheduled_at": "2026-08-12T09:00:00Z"}, TC)
        validate_error(resp, ApiErrorId.ERR_CHECK_AIRMAN_CONFLICT)

    def test_checkride_fail_bills_checkride_plus_retraining_surcharge(self, api):
        """PRD §3.8: "A checkride, passed or failed, bills a flat 120,000-cent
        `CHECKRIDE` fee, and a failed checkride adds the 30,000-cent
        `RETRAINING` surcharge described in §3.5."
        PRD §3.5: "Link 2, caused by the enrollment entering remediation, books
        a `RETRAINING` ledger charge equal to the 120,000-cent checkride fee
        multiplied by the 0.25 surcharge rate and rounded half-up — 30,000
        cents."

        Design: Corner/calculations/checkride_fail_bills_checkride_plus_retraining_surcharge
        """
        ctx = setup_enrollment_at_checkride_phase(
            eq_kwargs={"code": "ATR7", "sim_rate": 38000, "ioe_hours": 8},
            ap_kwargs={"email": "ret@x.com", "license_number": "L425",
                       "full_name": "Ret Rain", "hours": 3300},
            instructor_name="Ins Truct")
        examiner = make_instructor("Rid Er", "CHECK_AIRMAN")
        ck = make_checkride(ctx["enrollment"]["id"], examiner["id"],
                            scheduled_at="2026-08-12T09:00:00Z")
        set_clock("2026-08-12T09:00:00Z")
        record_checkride(ck["id"], "FAIL", examiner["id"])

        rows = list_ledger_entries(CS, enrollment_id=ctx["enrollment"]["id"])
        by_type = {}
        for row in rows:
            by_type.setdefault(row["entry_type"], []).append(row["amount_cents"])
        assert by_type["GROUND_SCHOOL"] == [150000]
        assert by_type["SIMULATOR"] == [76000], "2h * 38000 for the milestone"
        assert by_type["CHECKRIDE"] == [120000]
        assert by_type["RETRAINING"] == [30000]
        balance = get_applicant(ctx["applicant"]["id"])["ledger_balance_cents"]
        assert balance == 376000

        enrollment = get_enrollment(ctx["enrollment"]["id"])
        assert enrollment["status"] == "REMEDIATION"
        assert enrollment["failed_attempts"] == 1


class TestMaxCheckrideAttempts:
    def test_retrain_blocked_after_third_failure(self, api):
        """PRD §3.3: "Disqualification moves `IN_PROGRESS` or `REMEDIATION` to
        `DISQUALIFIED`, and disqualification is not terminal: retraining moves
        `DISQUALIFIED` → `REMEDIATION` provided the class is `IN_SESSION` and
        `failed_attempts` is at most 2, stamping a fresh
        `entered_remediation_at`. A retrain attempted after the second recorded
        failure is rejected with `ERR_MAX_ATTEMPTS_EXCEEDED` (422)."

        Design: Corner/validations/max_checkride_attempts_blocks_retrain
        """
        ctx = setup_enrollment_at_checkride_phase(
            eq_kwargs={"code": "B731", "sim_rate": 38000, "ioe_hours": 8},
            ap_kwargs={"email": "max@x.com", "license_number": "L438",
                       "full_name": "Max Att"},
            instructor_name="Tea Cher")
        en_id = ctx["enrollment"]["id"]
        instructor = ctx["instructor"]
        examiner = make_instructor("Exa Miner", "CHECK_AIRMAN")
        # One long slot window covering every remediation milestone.
        big_slot = make_simulator_slot(ctx["equipment"]["id"],
                                       "2026-08-12T08:00:00Z",
                                       "2026-08-20T18:00:00Z")

        def fail_once(ride_day):
            ck = make_checkride(en_id, examiner["id"],
                                scheduled_at=f"{ride_day}T09:00:00Z")
            set_clock(f"{ride_day}T09:00:00Z")
            record_checkride(ck["id"], "FAIL", examiner["id"])

        def remediate_and_resume(day):
            pass_milestone(en_id, instructor["id"], "SIMULATOR",
                           f"{day}T09:00:00Z", f"{day}T11:00:00Z", score=90,
                           slot_id=big_slot["id"])
            resumed = validate_success(api.resume_enrollment(en_id, TC))
            assert resumed["status"] == "IN_PROGRESS"

        # FAIL #1 -> REMEDIATION (failed_attempts 1), then resume.
        fail_once("2026-08-12")
        remediate_and_resume("2026-08-13")
        # FAIL #2 -> REMEDIATION (failed_attempts 2), then resume.
        fail_once("2026-08-14")
        remediate_and_resume("2026-08-15")
        # FAIL #3 -> REMEDIATION (failed_attempts 3); disqualify; retrain fails.
        fail_once("2026-08-16")
        enrollment = get_enrollment(en_id)
        assert enrollment["failed_attempts"] == 3
        disqualified = validate_success(api.disqualify_enrollment(en_id, TC))
        assert disqualified["status"] == "DISQUALIFIED"

        resp = api.retrain_enrollment(en_id, TC)
        validate_error(resp, ApiErrorId.ERR_MAX_ATTEMPTS_EXCEEDED)
