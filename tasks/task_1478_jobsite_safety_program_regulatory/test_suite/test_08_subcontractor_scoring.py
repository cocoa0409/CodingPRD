"""Subcontractor compliance scoring and standing thresholds: realtime vs
90-day variants, overdue doubling, score refund on NOT_SUB_FAULT, and the
strict/inclusive 80-point boundaries (PRD §3.7)."""
from test_helpers import (
    ApiErrorId, api_client,
    validate_error, validate_success,
    create_project, create_subcontractor, create_worker,
    create_completed_inspection, create_deficiency, submit_correction,
    verify_deficiency_closed, get_subcontractor, get_deficiency,
    create_incident, investigate_incident, record_determination,
    probation_review, set_clock,
    make_safety_manager_headers,
)

SM = make_safety_manager_headers()


def _project_with_sub(name="Site", hours=100000, company="Amp Electric",
                      trade="electrical"):
    set_clock("2026-08-01T08:00:00Z")
    project = create_project(name=name, annual_hours_worked=hours)
    sub = create_subcontractor(project["id"], company_name=company, trade=trade)
    return project, sub


class TestScoreVariants:

    def _confirmed_closed_major_setup(self, name):
        """MAJOR deficiency assigned to the sub, closed CONFIRMED, then the clock
        advanced 30 days (still inside the trailing 90-day window)."""
        project, sub = _project_with_sub(name=name)
        inspection = create_completed_inspection(project["id"],
                                                 findings_summary="panel covers missing")
        deficiency = create_deficiency(inspection["id"], "missing panel covers",
                                       "MAJOR", assigned_subcontractor_id=sub["id"],
                                       creator_id="insp-1")
        submit_correction(deficiency["id"], "covers installed",
                          subcontractor_id=sub["id"])
        verify_deficiency_closed(deficiency["id"], "CONFIRMED", "insp-2")
        set_clock("2026-08-31T08:00:00Z")
        return project, sub

    def test_realtime_variant_drops_verified_closed_deficiency(self, api):
        """PRD §3.7: "The realtime variant, `compliance_score_realtime`, counts
        deficiencies assigned to the subcontractor in status `OPEN`, `OVERDUE`,
        or `CORRECTION_SUBMITTED` — with the severity deduction doubled for any
        deficiency currently `OVERDUE` — plus recordable incidents in status
        `DETERMINATION_MADE` or `CLOSED`; deficiencies already `VERIFIED_CLOSED`
        contribute nothing to the realtime score."

        Design: Difficulty/dual_variant_calc/subcontractor_score_realtime_vs_period
        """
        _project, sub = self._confirmed_closed_major_setup("Riverside Garage")
        data = get_subcontractor(sub["id"])
        assert data["compliance_score_realtime"] == 100, (
            f"VERIFIED_CLOSED contributes nothing to realtime, got "
            f"{data['compliance_score_realtime']}"
        )

    def test_period_variant_keeps_confirmed_deduction(self, api):
        """PRD §3.7: "The period variant, `compliance_score_period_90d`, counts
        every deficiency assigned to the subcontractor that was created within the
        trailing 90 days regardless of its current status — except those closed as
        `NOT_SUB_FAULT`, which are refunded — with no overdue doubling, plus
        recordable incidents that occurred within the trailing 90 days; a
        deficiency closed `CONFIRMED` keeps its deduction in this variant."
        PRD §3.7: "Severity deductions are 5 points for a `MINOR` deficiency, 15
        for `MAJOR`, 30 for `CRITICAL`, and 50 for `IMMINENT_DANGER`"

        Design: Difficulty/dual_variant_calc/subcontractor_score_realtime_vs_period
        """
        _project, sub = self._confirmed_closed_major_setup("Riverside Garage 2")
        data = get_subcontractor(sub["id"])
        assert data["compliance_score_realtime"] == 100
        assert data["compliance_score_period_90d"] == 85, (
            f"CONFIRMED closure keeps the 15-point MAJOR deduction in the period "
            f"variant, got {data['compliance_score_period_90d']}"
        )
        assert data["compliance_score_realtime"] - data["compliance_score_period_90d"] == 15


class TestOverdueDoubling:

    def _overdue_major_plus_recordable_setup(self, name):
        """One MAJOR deficiency flipped OVERDUE by the clock, plus one recordable
        incident (DETERMINATION_MADE) on the sub's worker."""
        project, sub = _project_with_sub(name=name, hours=80000,
                                         company="Deep Foundations",
                                         trade="excavation")
        sub_worker = create_worker(project["id"], full_name="T Okafor",
                                   employer_type="SUBCONTRACTOR",
                                   subcontractor_id=sub["id"])
        inspection = create_completed_inspection(project["id"],
                                                 due_date="2026-08-05T17:00:00Z",
                                                 findings_summary="shoring gap")
        deficiency = create_deficiency(inspection["id"], "shoring not per plan",
                                       "MAJOR", assigned_subcontractor_id=sub["id"],
                                       creator_id="insp-1")
        # MAJOR SLA is 7 days: created 2026-08-01T08:00Z, so due 2026-08-08T08:00Z.
        set_clock("2026-08-10T08:00:00Z")
        incident = create_incident(
            project["id"], worker_id=sub_worker["id"], incident_type="INJURY",
            severity="SERIOUS", occurred_at="2026-08-09T10:00:00Z",
            work_related=True, description="struck-by",
        )
        investigate_incident(incident["id"], "spotter absent", "insp-1")
        record_determination(incident["id"], manager_id="sm-1",
                             medical_treatment_beyond_first_aid=True,
                             days_away_from_work=0)
        return project, sub, deficiency

    def test_realtime_applies_overdue_doubling_and_incident_deduction(self, api):
        """PRD §3.7: "with the severity deduction doubled for any deficiency
        currently `OVERDUE`"
        PRD §3.7: "each OSHA-recordable incident involving one of the
        subcontractor's workers deducts 25 points."
        PRD §2.5: "deficiencies whose `due_at` is strictly earlier than the new
        current time flip from `OPEN` to `OVERDUE`"

        Design: Difficulty/combinatorial_formula/score_tiered_overdue_doubling
        """
        _project, sub, deficiency = self._overdue_major_plus_recordable_setup(
            "Pier 62"
        )
        assert get_deficiency(deficiency["id"])["status"] == "OVERDUE"
        data = get_subcontractor(sub["id"])
        # 100 - 15 (MAJOR) - 15 (overdue doubling) - 25 (recordable incident) = 45
        assert data["compliance_score_realtime"] == 45, (
            f"realtime must double the OVERDUE MAJOR deduction: expected 45, got "
            f"{data['compliance_score_realtime']}"
        )

    def test_period_variant_applies_no_overdue_doubling(self, api):
        """PRD §3.7: "with no overdue doubling"
        PRD §3.7: "Severity deductions are 5 points for a `MINOR` deficiency, 15
        for `MAJOR`, 30 for `CRITICAL`, and 50 for `IMMINENT_DANGER`; each
        OSHA-recordable incident involving one of the subcontractor's workers
        deducts 25 points."

        Design: Difficulty/combinatorial_formula/score_tiered_overdue_doubling
        """
        _project, sub, _deficiency = self._overdue_major_plus_recordable_setup(
            "Pier 62 North"
        )
        data = get_subcontractor(sub["id"])
        # 100 - 15 (MAJOR, no doubling in the period variant) - 25 (incident) = 60
        assert data["compliance_score_period_90d"] == 60, (
            f"period variant must not double: expected 60, got "
            f"{data['compliance_score_period_90d']}"
        )


class TestDemoteThreshold:

    def test_demote_rejected_at_exactly_80(self, api):
        """PRD §3.7: "A probation review with `action` `DEMOTE` moves a
        subcontractor from `GOOD_STANDING` to `PROBATION` and requires
        `compliance_score_realtime` to be strictly below 80 — a score of exactly
        80 does not qualify. ... A threshold failure is rejected with
        `ERR_SCORE_THRESHOLD_NOT_MET`"

        Design: Difficulty/boundary_precision_check/score_threshold_exactly_80_demote_rejected
        """
        project, sub = _project_with_sub(name="Rainer Vista", hours=95000,
                                         company="Peak Framing", trade="carpentry")
        inspection = create_completed_inspection(project["id"],
                                                 findings_summary="guardrails + signage")
        create_deficiency(inspection["id"], "guardrail missing", "MAJOR",
                          assigned_subcontractor_id=sub["id"], creator_id="insp-1")
        create_deficiency(inspection["id"], "signage faded", "MINOR",
                          assigned_subcontractor_id=sub["id"], creator_id="insp-1")
        assert get_subcontractor(sub["id"])["compliance_score_realtime"] == 80

        resp = api.probation_review(sub["id"], {"action": "DEMOTE"}, SM)
        validate_error(resp, ApiErrorId.ERR_SCORE_THRESHOLD_NOT_MET)
        after = get_subcontractor(sub["id"])
        assert after["standing"] == "GOOD_STANDING"
        assert after["compliance_score_realtime"] == 80

    def test_demote_succeeds_just_below_80(self, api):
        """PRD §3.7: "A probation review with `action` `DEMOTE` moves a
        subcontractor from `GOOD_STANDING` to `PROBATION` and requires
        `compliance_score_realtime` to be strictly below 80 — a score of exactly
        80 does not qualify."

        Design: Difficulty/boundary_precision_check/score_threshold_exactly_80_demote_rejected
        """
        project, sub = _project_with_sub(name="Rainer Vista 2", hours=96000,
                                         company="Peak Framing", trade="carpentry")
        inspection = create_completed_inspection(project["id"])
        create_deficiency(inspection["id"], "major item", "MAJOR",
                          assigned_subcontractor_id=sub["id"], creator_id="insp-1")
        create_deficiency(inspection["id"], "minor item 1", "MINOR",
                          assigned_subcontractor_id=sub["id"], creator_id="insp-1")
        create_deficiency(inspection["id"], "minor item 2", "MINOR",
                          assigned_subcontractor_id=sub["id"], creator_id="insp-1")
        assert get_subcontractor(sub["id"])["compliance_score_realtime"] == 75

        data = probation_review(sub["id"], "DEMOTE")
        assert data["standing"] == "PROBATION"
        assert data["compliance_score_realtime"] == 75


class TestRestoreThreshold:

    def test_restore_succeeds_at_exactly_80(self, api):
        """PRD §3.7: "A probation review with `action` `RESTORE` moves a
        subcontractor from `PROBATION` back to `GOOD_STANDING` and requires the
        realtime score to be at least 80 — exactly 80 qualifies."

        Design: Corner/validations/subcontractor_probation_restore_at_exactly_80
        """
        project, sub = _project_with_sub(name="Highland Park", hours=36000,
                                         company="Peak Framing", trade="carpentry")
        inspection = create_completed_inspection(project["id"],
                                                 findings_summary="three items")
        create_deficiency(inspection["id"], "major item", "MAJOR",
                          assigned_subcontractor_id=sub["id"], creator_id="insp-1")
        create_deficiency(inspection["id"], "minor item 1", "MINOR",
                          assigned_subcontractor_id=sub["id"], creator_id="insp-1")
        d2 = create_deficiency(inspection["id"], "minor item 2", "MINOR",
                               assigned_subcontractor_id=sub["id"], creator_id="insp-1")
        # realtime 75 (< 80): DEMOTE is allowed.
        probation_review(sub["id"], "DEMOTE")
        # Closing one MINOR (CONFIRMED) lifts its 5 from the realtime variant:
        # VERIFIED_CLOSED deficiencies contribute nothing -> realtime exactly 80.
        submit_correction(d2["id"], "fixed", subcontractor_id=sub["id"])
        verify_deficiency_closed(d2["id"], "CONFIRMED", "insp-2")
        assert get_subcontractor(sub["id"])["compliance_score_realtime"] == 80

        resp = api.probation_review(sub["id"], {"action": "RESTORE"}, SM)
        data = validate_success(resp, 200)
        assert data["standing"] == "GOOD_STANDING"
        assert data["compliance_score_realtime"] == 80

    def test_remove_from_good_standing_rejected(self, api):
        """PRD §3.7: "Removing a subcontractor — a `SafetyManager` action carrying
        a `reason` — moves the firm from `PROBATION` to the terminal `REMOVED`
        standing"
        PRD §3.7: "a review attempted from the wrong standing — including any
        action against a `REMOVED` firm, which is terminal — is rejected with
        `ERR_SUBCONTRACTOR_INVALID_STANDING`."

        Design: Corner/errors/subcontractor_remove_from_good_standing_rejected
        """
        project, sub = _project_with_sub(name="Leschi", hours=21000,
                                         company="Amp")
        assert sub["standing"] == "GOOD_STANDING"
        resp = api.remove_subcontractor(sub["id"], {"reason": "premature"}, SM)
        validate_error(resp, ApiErrorId.ERR_SUBCONTRACTOR_INVALID_STANDING)
        assert get_subcontractor(sub["id"])["standing"] == "GOOD_STANDING"


class TestScoreRefundInvariant:

    def _major_deficiency_setup(self, name):
        project, sub = _project_with_sub(name=name, company="Amp Electric")
        inspection = create_completed_inspection(project["id"],
                                                 findings_summary="wiring")
        deficiency = create_deficiency(inspection["id"], "unlabeled circuits",
                                       "MAJOR", assigned_subcontractor_id=sub["id"],
                                       creator_id="insp-1")
        return project, sub, deficiency

    def test_not_sub_fault_closure_refunds_exactly(self, api):
        """PRD §3.5: "When the deficiency was assigned to a subcontractor and the
        disposition is `NOT_SUB_FAULT`, the severity deduction is refunded to both
        compliance score variants, returning them toward their pre-creation
        values"
        PRD §3.7: "A new subcontractor starts in `GOOD_STANDING` with both
        compliance scores at 100."

        Design: Difficulty/compensating_invariant/score_deduction_refund_invariant
        """
        _project, sub, deficiency = self._major_deficiency_setup("Columbia Center")
        mid = get_subcontractor(sub["id"])
        assert mid["compliance_score_realtime"] == 85, (
            f"MAJOR creation deducts 15 from realtime: got "
            f"{mid['compliance_score_realtime']}"
        )

        submit_correction(deficiency["id"],
                          "labeled; pre-existing condition documented",
                          subcontractor_id=sub["id"])
        verify_deficiency_closed(deficiency["id"], "NOT_SUB_FAULT", "insp-2")

        after = get_subcontractor(sub["id"])
        assert after["compliance_score_realtime"] == 100, (
            f"NOT_SUB_FAULT refunds realtime to baseline: got "
            f"{after['compliance_score_realtime']}"
        )
        assert after["compliance_score_period_90d"] == 100, (
            f"NOT_SUB_FAULT refunds the period variant too: got "
            f"{after['compliance_score_period_90d']}"
        )

    def test_confirmed_closure_refunds_realtime_only(self, api):
        """PRD §3.5: "a `CONFIRMED` closure keeps the deduction in the 90-day
        variant only, as §3.7 describes."
        PRD §3.7: "deficiencies already `VERIFIED_CLOSED` contribute nothing to
        the realtime score."

        Design: Difficulty/compensating_invariant/score_deduction_refund_invariant
        """
        _project, sub, deficiency = self._major_deficiency_setup("Columbia Center 2")
        assert get_subcontractor(sub["id"])["compliance_score_realtime"] == 85

        submit_correction(deficiency["id"], "labeled", subcontractor_id=sub["id"])
        verify_deficiency_closed(deficiency["id"], "CONFIRMED", "insp-2")

        after = get_subcontractor(sub["id"])
        assert after["compliance_score_realtime"] == 100, (
            f"realtime drops the closed deficiency: got "
            f"{after['compliance_score_realtime']}"
        )
        assert after["compliance_score_period_90d"] == 85, (
            f"CONFIRMED closure keeps the deduction in the 90-day variant: got "
            f"{after['compliance_score_period_90d']}"
        )
