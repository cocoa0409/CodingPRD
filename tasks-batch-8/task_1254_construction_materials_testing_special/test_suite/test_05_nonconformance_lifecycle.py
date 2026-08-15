"""Nonconformance reports: the correction/verification cycle, segregation of
duties, escalation scoring at the daily sweep, and the cascades that create
reports from nonconforming results."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cast_sample,
    get_project,
    list_project_ncrs,
    make_technician_headers,
    record_sample_break,
    schedule_sample_break,
    set_clock,
    setup_concrete_assignment,
    setup_minor_ncr_twice_rejected,
    setup_open_soil_ncr,
    submit_ncr_correction,
    verify_ncr,
    validate_error,
    validate_success,
    get_success_data,
    api_client,
)

PM = TEST_USERS["project_manager_headers"]
CONTRACTOR = TEST_USERS["contractor_headers"]
ADMIN = TEST_USERS["agency_admin_headers"]


def _run_sweep(api):
    return get_success_data(api_client.run_daily_sweep(ADMIN))


class TestCorrectionCycle:
    def test_correction_rejection_returns_ncr_to_open(self, api):
        """PRD §3.6: "A `Contractor` submits a correction — the request carries
        the `correction_note` — moving the report from `OPEN` (or from
        `ESCALATED`, described below) to `CORRECTION_SUBMITTED`."
        PRD §3.6: "A `REJECTED` outcome returns the report to `OPEN`,
        increments `rejection_count` by one, and clears the `correction_note`
        for another remediation round."

        Design: Difficulty/non_linear_state_machine/ncr_correction_rejection_cycle
        """
        ctx = setup_open_soil_ncr(project_overrides={"name": "Cycle", "permit_number": "P-CYC-1"})
        ncr_id = ctx["ncr"]["id"]

        submitted = submit_ncr_correction(ncr_id, "recompact and retest")
        assert submitted["status"] == "CORRECTION_SUBMITTED"

        rejected = verify_ncr(ncr_id, ctx["verifier"]["id"], "REJECTED")
        assert rejected["status"] == "OPEN", "rejection cycles the report back to OPEN"
        assert rejected["rejection_count"] == 1

    def test_ncr_cycle_terminates_at_verified_after_rework(self, api):
        """PRD §3.6: "A `REJECTED` outcome returns the report to `OPEN`,
        increments `rejection_count` by one, and clears the `correction_note`
        for another remediation round."
        PRD §3.6: "A `VERIFIED` outcome records `verified_by_technician_id`,
        decrements the project's `open_ncr_count` by one as a compensating
        action, recomputes posture, and moves the report to `VERIFIED`, its
        terminal state."

        Design: Difficulty/non_linear_state_machine/ncr_correction_rejection_cycle
        """
        ctx = setup_open_soil_ncr(project_overrides={"name": "Cycle", "permit_number": "P-CYC-1"})
        ncr_id = ctx["ncr"]["id"]
        verifier_id = ctx["verifier"]["id"]

        submit_ncr_correction(ncr_id, "recompact and retest")
        verify_ncr(ncr_id, verifier_id, "REJECTED")
        submit_ncr_correction(ncr_id, "second correction pass")
        verified = verify_ncr(ncr_id, verifier_id, "VERIFIED")
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_technician_id"] == verifier_id
        project = get_project(ctx["project"]["id"])
        assert project["open_ncr_count"] == 0, "verification compensates the count exactly"


class TestOpenNcrCountConservation:
    def test_correction_submission_does_not_close_the_count(self, api):
        """PRD §3.9: "Otherwise, if `open_ncr_count` — the number of the
        project's reports in `OPEN`, `CORRECTION_SUBMITTED`, or `ESCALATED` —
        is greater than zero, the posture is `NONCONFORMANCE_OUTSTANDING`."
        PRD §3.6: "A `Contractor` submits a correction — the request carries
        the `correction_note` — moving the report from `OPEN` (or from
        `ESCALATED`, described below) to `CORRECTION_SUBMITTED`."

        Design: Difficulty/compensating_invariant/open_ncr_count_conservation
        """
        ctx = setup_open_soil_ncr(
            project_overrides={"name": "Invariant NCR", "permit_number": "P-INV-1"}
        )
        assert get_project(ctx["project"]["id"])["open_ncr_count"] == 1

        submitted = submit_ncr_correction(ctx["ncr"]["id"], "recompacted to spec")
        assert submitted["status"] == "CORRECTION_SUBMITTED"
        mid = get_project(ctx["project"]["id"])
        assert mid["open_ncr_count"] == 1, "CORRECTION_SUBMITTED still counts as open"
        assert mid["compliance_posture"] == "NONCONFORMANCE_OUTSTANDING"

    def test_verification_restores_count_and_clears_posture(self, api):
        """PRD §3.6: "A `VERIFIED` outcome records `verified_by_technician_id`,
        decrements the project's `open_ncr_count` by one as a compensating
        action, recomputes posture, and moves the report to `VERIFIED`, its
        terminal state."
        PRD §3.9: "Otherwise, if `open_ncr_count` — the number of the project's
        reports in `OPEN`, `CORRECTION_SUBMITTED`, or `ESCALATED` — is greater
        than zero, the posture is `NONCONFORMANCE_OUTSTANDING`."

        Design: Difficulty/compensating_invariant/open_ncr_count_conservation
        """
        ctx = setup_open_soil_ncr(
            project_overrides={"name": "Invariant NCR", "permit_number": "P-INV-1"}
        )
        submit_ncr_correction(ctx["ncr"]["id"], "recompacted to spec")
        verified = verify_ncr(ctx["ncr"]["id"], ctx["verifier"]["id"], "VERIFIED")
        assert verified["status"] == "VERIFIED"
        project = get_project(ctx["project"]["id"])
        assert project["open_ncr_count"] == 0, (
            "compensation restores the pre-incident value exactly"
        )
        assert project["compliance_posture"] != "NONCONFORMANCE_OUTSTANDING"


class TestNonconformingBreakCascade:
    def _break_nonconforming(self, api):
        ctx = setup_concrete_assignment(
            fc=4000, required_count=1,
            project_overrides={"name": "Cascade A", "permit_number": "P-CAS-1"},
        )
        sample = cast_sample(ctx["assignment"]["id"], ctx["technician"]["id"],
                             ctx["lab"]["id"], "2026-04-01T08:00:00Z", 28)
        schedule_sample_break(sample["id"], "2026-04-29")
        broken = record_sample_break(sample["id"], "2026-04-29T08:00:00Z", [3500])
        return ctx, sample, broken

    def test_nonconforming_break_creates_lab_sample_ncr(self, api):
        """PRD §3.5: "A nonconforming break auto-creates an NCR with
        `source_type` of `LAB_SAMPLE`, severity `STRUCTURAL` or `MAJOR` by the
        same `is_structural` rule as field tests, and increments
        `open_ncr_count`."
        PRD §3.6: "Each receives a per-project sequential `ncr_number` in
        creation order (`NCR-0001`, `NCR-0002`, and so on), carries the
        `project_id` inherited from the source result's assignment, a
        polymorphic `source_type` of `FIELD_TEST` or `LAB_SAMPLE` with the
        corresponding `source_id`, the `scope_item_id` copied from that
        assignment, an auto-generated `description`, a computed `severity` of
        `MINOR`, `MAJOR`, or `STRUCTURAL`, and a `detected_at` clock
        timestamp."

        Design: Difficulty/transitive_cascade/nonconforming_break_cascade_depth3
        """
        ctx, sample, broken = self._break_nonconforming(api)
        assert broken["break_result"] == "NONCONFORMING", "3500 psi is below f'c 4000"
        ncrs = list_project_ncrs(ctx["project"]["id"])
        assert len(ncrs) == 1, "exactly one NCR arises from the break"
        ncr = ncrs[0]
        assert ncr["source_type"] == "LAB_SAMPLE"
        assert ncr["source_id"] == sample["id"]
        assert ncr["severity"] == "MAJOR", "is_structural defaults to false"
        assert ncr["status"] == "OPEN"

    def test_nonconforming_break_increments_count_and_degrades_posture(self, api):
        """PRD §3.5: "A nonconforming break auto-creates an NCR with
        `source_type` of `LAB_SAMPLE`, severity `STRUCTURAL` or `MAJOR` by the
        same `is_structural` rule as field tests, and increments
        `open_ncr_count`."
        PRD §3.9: "Otherwise, if `open_ncr_count` — the number of the project's
        reports in `OPEN`, `CORRECTION_SUBMITTED`, or `ESCALATED` — is greater
        than zero, the posture is `NONCONFORMANCE_OUTSTANDING`."

        Design: Difficulty/transitive_cascade/nonconforming_break_cascade_depth3
        """
        ctx, _sample, _broken = self._break_nonconforming(api)
        before = ctx["project"]
        assert before["open_ncr_count"] == 0
        assert before["compliance_posture"] == "IN_PROGRESS"
        project = get_project(ctx["project"]["id"])
        assert project["open_ncr_count"] == 1, "the NCR creation increments the count"
        assert project["compliance_posture"] == "NONCONFORMANCE_OUTSTANDING", (
            "the count increment forces the posture recompute"
        )


class TestEscalationSweep:
    def test_ncr_escalates_at_exactly_threshold_score(self, api):
        """PRD §3.6: "Otherwise the score starts from a severity base — 20 for
        `MINOR`, 40 for `MAJOR`, 60 for `STRUCTURAL` — adds 2 points per day
        open, 3 points per day overdue, and 15 points per rejection, capped at
        100. A score of 70 or more moves the report `OPEN → ESCALATED`;
        exactly 70 escalates."

        Design: Difficulty/combinatorial_formula/ncr_escalation_threshold_crossing
        """
        ctx = setup_minor_ncr_twice_rejected()
        set_clock("2026-06-09T00:00:00Z")
        sweep = _run_sweep(api)
        ncr_id = ctx["ncr"]["id"]
        assert ncr_id in sweep["escalated_ncr_ids"], (
            "score 20 + 2*10 + 3*0 + 15*2 = 70 >= 70 escalates"
        )
        ncr = [n for n in list_project_ncrs(ctx["project"]["id"]) if n["id"] == ncr_id][0]
        assert ncr["status"] == "ESCALATED"
        assert ncr["escalation_score"] == 70

    def test_escalated_ncr_still_counts_as_open_and_keeps_rejections(self, api):
        """PRD §3.9: "Otherwise, if `open_ncr_count` — the number of the
        project's reports in `OPEN`, `CORRECTION_SUBMITTED`, or `ESCALATED` —
        is greater than zero, the posture is `NONCONFORMANCE_OUTSTANDING`."
        PRD §3.6: "Escalated reports still accept contractor corrections, and
        every escalation recomputes the affected project's posture."

        Design: Difficulty/combinatorial_formula/ncr_escalation_threshold_crossing
        """
        ctx = setup_minor_ncr_twice_rejected()
        set_clock("2026-06-09T00:00:00Z")
        _run_sweep(api)
        ncr = [n for n in list_project_ncrs(ctx["project"]["id"])
               if n["id"] == ctx["ncr"]["id"]][0]
        assert ncr["rejection_count"] == 2, "the counter survives the correction cycles"
        project = get_project(ctx["project"]["id"])
        assert project["open_ncr_count"] == 1, "ESCALATED still counts as open"
        assert project["compliance_posture"] == "NONCONFORMANCE_OUTSTANDING"

    def test_sweep_below_threshold_leaves_ncr_open(self, api):
        """PRD §3.6: "Otherwise the score starts from a severity base — 20 for
        `MINOR`, 40 for `MAJOR`, 60 for `STRUCTURAL` — adds 2 points per day
        open, 3 points per day overdue, and 15 points per rejection, capped at
        100. A score of 70 or more moves the report `OPEN → ESCALATED`;
        exactly 70 escalates."
        PRD §3.6: "The sweep responds with the `escalated_ncr_ids` it acted
        on."

        Design: Corner/state_machines/sweep_below_threshold_leaves_ncr_open
        """
        ctx = setup_minor_ncr_twice_rejected()
        set_clock("2026-06-08T00:00:00Z")
        sweep = _run_sweep(api)
        assert sweep["escalated_ncr_ids"] == [], (
            "score 20 + 2*9 + 3*0 + 15*2 = 68 stays below the threshold"
        )
        ncr = [n for n in list_project_ncrs(ctx["project"]["id"])
               if n["id"] == ctx["ncr"]["id"]][0]
        assert ncr["status"] == "OPEN"
        assert ncr["escalation_score"] == 68


class TestVerificationRules:
    def test_verify_without_submitted_correction_rejected(self, api):
        """PRD §3.6: "The verification request carries an `outcome` of
        `VERIFIED` or `REJECTED` plus an optional `verification_note`, and may
        cite an `evidence_field_test_id` — a retest that must reference a
        `RECORDED` field test with a `CONFORMING` result on the same scope
        item, failing which the request is rejected with
        `ERR_REFERENCE_MISMATCH`."
        PRD §2.9: "Fourth, state: whether the target resource's current state
        permits the operation (`ERR_INVALID_STATE`), a tier that also carries
        the domain state errors `ERR_PROJECT_COMPLETED`,
        `ERR_LETTER_ALREADY_ISSUED`, `ERR_NO_LETTER_TO_VOID`,
        `ERR_TEST_NOT_VOIDABLE`, and `ERR_NO_RESULT_RECORDED`."

        Design: Corner/state_machines/ncr_verify_from_open_rejected
        """
        ctx = setup_open_soil_ncr(
            project_overrides={"name": "VerifyOpen", "permit_number": "P-SM-10"}
        )
        resp = api.verify_ncr(
            ctx["ncr"]["id"], {"outcome": "VERIFIED"},
            make_technician_headers(ctx["verifier"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_originating_technician_cannot_verify_correction(self, api):
        """PRD §3.6: "Verification belongs to a `Technician` other than the one
        whose result raised the report: the verifier's `X-User-ID` must differ
        from the source field test's recorded technician, or, for lab-sourced
        reports, from the technician of the assignment that cast the sample; a
        self-verification is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/ncr_verify_by_originating_technician_rejected
        """
        ctx = setup_open_soil_ncr(project_overrides={"name": "SoD", "permit_number": "P-RBAC-4"})
        ncr_id = ctx["ncr"]["id"]
        submit_ncr_correction(ncr_id, "recompacted")

        selfish = api.verify_ncr(
            ncr_id, {"outcome": "VERIFIED"},
            make_technician_headers(ctx["technician"]["id"]),
        )
        validate_error(selfish, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        verified = validate_success(
            api.verify_ncr(
                ncr_id, {"outcome": "VERIFIED"},
                make_technician_headers(ctx["verifier"]["id"]),
            ),
            200,
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_technician_id"] == ctx["verifier"]["id"]
