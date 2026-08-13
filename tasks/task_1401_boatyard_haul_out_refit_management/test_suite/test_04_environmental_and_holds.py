"""Environmental runoff thresholds, the violation cascade, and holds."""
from test_helpers import (
    ApiErrorId,
    create_refit_job,
    create_submitted_job,
    create_vessel,
    create_vessel_with_insurance,
    get_job,
    list_compliance_holds,
    list_lift_slots,
    log_environmental_event,
    post_manual_hold,
    set_clock,
    setup_job_on_hard,
    setup_job_ready_for_splash,
    submit_refit_job,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, api_client

SW = TEST_USERS["service_writer_headers"]
YM = TEST_USERS["yard_manager_headers"]
EO = TEST_USERS["environmental_officer_headers"]
AC = TEST_USERS["accountant_headers"]


class TestRunoffBoundaries:

    def test_ppm_99_9_is_advisory_without_hold(self):
        """PRD section 3.8: "A reading of 50.0 ppm or higher but below 100.0
        is `ADVISORY`."
        PRD section 3.8: "A violation fires a four-hop cascade. Hop one: the
        system creates a `ComplianceHold` of kind `ENVIRONMENTAL`, source
        `AUTO_VIOLATION`, status `OPEN`, whose `source_event_id` references
        the event, and the job's `open_hold_count` increases by one."

        Design: Difficulty/boundary_precision_check/runoff_ppm_exactly_100_flags_violation
        """
        ctx = setup_job_on_hard(vessel_name="MV PPM", loa_ft=30, beam_ft=10,
                                displacement_tons=10, row_code="X",
                                total_stands=6, stands_used=3)
        event = log_environmental_event(ctx["job"]["id"], kind="WASHDOWN",
                                        containment_used=True,
                                        runoff_tss_ppm=99.9)
        assert event["status"] == "ADVISORY"
        assert list_compliance_holds(ctx["job"]["id"]) == [], \
            "ADVISORY never creates a hold"

    def test_ppm_100_0_is_violation_with_auto_hold(self):
        """PRD section 3.8: "A reading of 100.0 ppm or higher is a violation
        — the boundary is inclusive, so exactly 100.0 is a violation — and
        the event is `VIOLATION_FLAGGED`."
        PRD section 2.7: "Percentage comparisons (runoff thresholds) are
        evaluated at one decimal place, with the boundary inclusive: a
        measured value exactly at the violation threshold is a violation."

        Design: Difficulty/boundary_precision_check/runoff_ppm_exactly_100_flags_violation
        """
        ctx = setup_job_on_hard(vessel_name="MV PPM", loa_ft=30, beam_ft=10,
                                displacement_tons=10, row_code="X",
                                total_stands=6, stands_used=3)
        log_environmental_event(ctx["job"]["id"], kind="WASHDOWN",
                                containment_used=True, runoff_tss_ppm=99.9)
        event = log_environmental_event(ctx["job"]["id"], kind="SANDING",
                                        containment_used=True,
                                        runoff_tss_ppm=100.0)
        assert event["status"] == "VIOLATION_FLAGGED"

        holds = list_compliance_holds(ctx["job"]["id"])
        assert len(holds) == 1, "exactly one auto hold after the violation"
        assert holds[0]["status"] == "OPEN"
        assert holds[0]["kind"] == "ENVIRONMENTAL"
        assert holds[0]["source"] == "AUTO_VIOLATION"

    def test_advisory_band_lower_boundary(self):
        """PRD section 3.8: "A reading of 50.0 ppm or higher but below 100.0
        is `ADVISORY`. Below 50.0 ppm the event is simply `LOGGED`."

        Design: Corner/calculations/advisory_band_lower_boundary
        """
        ctx = setup_job_on_hard(vessel_name="MV Band", loa_ft=30, beam_ft=10,
                                displacement_tons=10, row_code="BD",
                                total_stands=6, stands_used=3)
        low = log_environmental_event(ctx["job"]["id"], kind="WASHDOWN",
                                      containment_used=True,
                                      runoff_tss_ppm=49.9)
        mid = log_environmental_event(ctx["job"]["id"], kind="WASHDOWN",
                                      containment_used=True,
                                      runoff_tss_ppm=50.0)
        assert low["status"] == "LOGGED"
        assert mid["status"] == "ADVISORY"
        assert list_compliance_holds(ctx["job"]["id"]) == []


class TestViolationCascade:

    def _ready_job_with_booked_splash(self):
        return setup_job_ready_for_splash(
            vessel_name="MV Sand", hull_type="SAIL", book_splash=True)

    def test_violation_creates_auto_hold_and_revokes_readiness(self):
        """PRD section 3.8: "A violation fires a four-hop cascade. Hop one:
        the system creates a `ComplianceHold` of kind `ENVIRONMENTAL`, source
        `AUTO_VIOLATION`, status `OPEN`, whose `source_event_id` references
        the event, and the job's `open_hold_count` increases by one. Hop two:
        readiness is revoked — if the job was `READY_FOR_SPLASH` it returns
        to `WORK_IN_PROGRESS`."

        Design: Difficulty/transitive_cascade/env_violation_cascade_to_splash_cancel
        """
        ctx = self._ready_job_with_booked_splash()
        assert ctx["job"]["status"] == "READY_FOR_SPLASH"

        event = log_environmental_event(ctx["job"]["id"], kind="SANDING",
                                        containment_used=True,
                                        runoff_tss_ppm=150)
        assert event["status"] == "VIOLATION_FLAGGED"

        holds = list_compliance_holds(ctx["job"]["id"])
        assert len(holds) == 1
        hold = holds[0]
        assert hold["status"] == "OPEN"
        assert hold["kind"] == "ENVIRONMENTAL"
        assert hold["source"] == "AUTO_VIOLATION"
        assert hold["source_event_id"] == event["id"]

        job = get_job(ctx["job"]["id"])
        assert job["status"] == "WORK_IN_PROGRESS", \
            "hop 2: readiness revoked while the auto hold is open"
        assert job["open_hold_count"] == 1

    def test_violation_cancels_booked_splash_slot(self):
        """PRD section 3.8: "Hop three: because the job left
        `READY_FOR_SPLASH`, every `BOOKED` splash slot of the job becomes
        `CANCELLED`."

        Design: Difficulty/transitive_cascade/env_violation_cascade_to_splash_cancel
        """
        ctx = self._ready_job_with_booked_splash()
        splash_id = ctx["splash_slot"]["id"]

        log_environmental_event(ctx["job"]["id"], kind="SANDING",
                                containment_used=True, runoff_tss_ppm=150)
        cancelled = list_lift_slots(ctx["job"]["id"],
                                    params={"status": "CANCELLED"})
        cancelled_ids = [s["id"] for s in cancelled]
        assert splash_id in cancelled_ids, \
            "hop 3: the BOOKED splash slot is cancelled by the cascade"


class TestRemediate:

    def test_auto_violation_hold_rejected_manual_release(self):
        """PRD section 3.9: "An `AUTO_VIOLATION` hold cannot be released
        through the manual release operation at all — attempting it is
        rejected with `ERR_INVALID_STATE`; only remediating the source
        environmental event releases it."

        Design: Corner/state_machines/auto_violation_hold_rejected_manual_release
        """
        ctx = setup_job_on_hard(vessel_name="MV Auto", loa_ft=30, beam_ft=10,
                                displacement_tons=10, row_code="AU",
                                total_stands=6, stands_used=3)
        log_environmental_event(ctx["job"]["id"], kind="SANDING",
                                containment_used=False, runoff_tss_ppm=120)
        hold = list_compliance_holds(ctx["job"]["id"])[0]

        resp = api_client.release_compliance_hold(hold["id"], EO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        holds_after = list_compliance_holds(ctx["job"]["id"])
        assert holds_after[0]["status"] == "OPEN", \
            "a rejected release leaves the auto hold open"

    def test_remediate_restores_splash_readiness(self):
        """PRD section 3.8: "Remediation releases the auto-created hold: the
        `AUTO_VIOLATION` hold becomes `RELEASED` and the job's
        `open_hold_count` decreases by one. When the count returns to zero,
        the job's `ON_HOLD` work orders resume to `IN_PROGRESS` and readiness
        re-evaluation runs."
        PRD section 3.8: "Remediating a flagged violation — an
        `EnvironmentalOfficer` action carrying a `remediation_note`, which is
        recorded — moves the event from `VIOLATION_FLAGGED` to `REMEDIATED`,
        which is terminal."

        Design: Corner/state_machines/remediate_restores_splash_readiness
        """
        ctx = setup_job_ready_for_splash(vessel_name="MV Rem",
                                         deposit_cents=None)
        event = log_environmental_event(ctx["job"]["id"], kind="WASHDOWN",
                                        containment_used=True,
                                        runoff_tss_ppm=130)
        assert get_job(ctx["job"]["id"])["status"] == "WORK_IN_PROGRESS"

        remediated = validate_success(
            api_client.remediate_environmental_event(
                event["id"],
                {"remediation_note": "Containment repaired, runoff retested clean"},
                EO))
        assert remediated["status"] == "REMEDIATED"

        hold = list_compliance_holds(ctx["job"]["id"])[0]
        assert hold["status"] == "RELEASED"
        job = get_job(ctx["job"]["id"])
        assert job["open_hold_count"] == 0
        assert job["status"] == "READY_FOR_SPLASH", \
            "with zero open holds and all work orders complete, readiness returns"


class TestManualHolds:

    def test_manual_hold_revokes_and_restores_readiness(self):
        """PRD section 3.9: "Hold creation — manual or automatic — has the
        same side effects either way: the job's `open_hold_count` increases
        by one; if the job was `READY_FOR_SPLASH` it becomes
        `WORK_IN_PROGRESS`; every `BOOKED` splash slot of the job becomes
        `CANCELLED`; and every `IN_PROGRESS` work order of the job becomes
        `ON_HOLD`."
        PRD section 3.9: "Releasing a manual hold moves it from `OPEN` to
        `RELEASED`, decrements the job's `open_hold_count` by one, and — when
        the count returns to zero — resumes the job's `ON_HOLD` work orders
        to `IN_PROGRESS` and runs readiness re-evaluation."
        PRD section 3.3: "`COMPLETED`, `CANCELLED`, and `NO_SHOW` are all
        terminal for a slot; acting on a terminal slot yields
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/manual_hold_revokes_and_restores_readiness
        """
        ctx = setup_job_ready_for_splash(vessel_name="MV Hold",
                                         book_splash=True)
        splash_id = ctx["splash_slot"]["id"]

        hold = post_manual_hold(ctx["job"]["id"], kind="PAYMENT",
                                note="Invoice dispute")
        assert hold["status"] == "OPEN"
        assert hold["source"] == "MANUAL"
        job = get_job(ctx["job"]["id"])
        assert job["status"] == "WORK_IN_PROGRESS"
        assert job["open_hold_count"] == 1

        released = validate_success(
            api_client.release_compliance_hold(hold["id"], AC))
        assert released["status"] == "RELEASED"
        job = get_job(ctx["job"]["id"])
        assert job["status"] == "READY_FOR_SPLASH"
        assert job["open_hold_count"] == 0

        cancelled = list_lift_slots(ctx["job"]["id"],
                                    params={"status": "CANCELLED"})
        assert splash_id in [s["id"] for s in cancelled], \
            "the cancelled splash slot stays cancelled (one-way compensation)"


class TestHoldRoleSegregation:

    def _intake_job_with_two_holds(self):
        set_clock("2026-08-01T09:00:00Z")
        vessel, _c = create_vessel_with_insurance(
            name="MV Seg", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-S6")
        job = create_submitted_job(vessel["id"])
        hold_pay = post_manual_hold(job["id"], kind="PAYMENT",
                                    note="Unpaid invoice")
        hold_env = post_manual_hold(job["id"], kind="ENVIRONMENTAL",
                                    note="Dust complaint")
        return job, hold_pay, hold_env

    def test_hold_release_kind_role_segregation(self):
        """PRD section 3.9: "Release is again role-segregated by kind: an
        `ENVIRONMENTAL` hold is released by an `EnvironmentalOfficer`, a
        `PAYMENT` hold by an `Accountant`, else `ERR_UNAUTHORIZED`."
        PRD section 2.1: "Compliance-hold creation and release are
        kind-segregated: a hold of kind `ENVIRONMENTAL` may be created or
        released only by an `EnvironmentalOfficer`, and a hold of kind
        `PAYMENT` only by an `Accountant`; a mismatch between the caller's
        role and the hold kind is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/hold_release_kind_role_segregation
        """
        job, hold_pay, hold_env = self._intake_job_with_two_holds()

        wrong1 = api_client.release_compliance_hold(hold_pay["id"], EO)
        validate_error(wrong1, ApiErrorId.ERR_UNAUTHORIZED)
        wrong2 = api_client.release_compliance_hold(hold_env["id"], AC)
        validate_error(wrong2, ApiErrorId.ERR_UNAUTHORIZED)
        holds = {h["id"]: h for h in list_compliance_holds(job["id"])}
        assert holds[hold_pay["id"]]["status"] == "OPEN"
        assert holds[hold_env["id"]]["status"] == "OPEN"

        ok1 = validate_success(
            api_client.release_compliance_hold(hold_pay["id"], AC))
        ok2 = validate_success(
            api_client.release_compliance_hold(hold_env["id"], EO))
        assert ok1["status"] == "RELEASED"
        assert ok2["status"] == "RELEASED"

    def test_yard_manager_cannot_release_hold(self):
        """PRD section 2.1: "A request whose role is authenticated but not
        permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403); this also covers the kind-conditional segregation on
        compliance holds described below."
        PRD section 4: "| POST | /yard/compliance-holds/{holdId}/release |
        Release a manual hold | Accountant, EnvironmentalOfficer |"

        Design: Corner/rbac/yard_manager_cannot_release_hold
        """
        set_clock("2026-08-01T09:00:00Z")
        vessel, _c = create_vessel_with_insurance(
            name="MV Role", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-R3")
        job = create_submitted_job(vessel["id"])
        hold = post_manual_hold(job["id"], kind="PAYMENT",
                                note="Deposit late")

        resp = api_client.release_compliance_hold(hold["id"], YM)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
