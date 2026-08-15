"""Sampling and inspection: threshold variants, boundary precision, evaluation
cascades, close gating, and the closed-reopen appeal window."""
import pytest

from test_helpers import (
    ApiErrorId,
    close_inspection_ok,
    close_noncompliance_ok,
    evaluate_inspection_ok,
    find_noncompliance,
    get_vessel,
    list_deficiencies,
    list_inspections,
    list_noncompliance,
    make_flag_surveyor_headers,
    record_inspection,
    respond_noncompliance_ok,
    set_clock,
    setup_voyage_in_progress,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestThresholdVariants:
    def _setup_two_inspections(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000002", vessel_name="MV Boreal", voyage_number="V1002"
        )
        statutory = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=7.0,
            tss=30.0, recorder_user_id="fs-rec-1",
        )
        internal = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="COMPANY_INTERNAL", organism=7.0,
            tss=30.0, sampled_at="2026-07-29T06:00:00Z", recorder_user_id="fs-rec-1",
        )
        return vessel, voyage, statutory, internal

    def test_statutory_limits_not_exceeded_at_sub_limit_readings(self, api):
        """PRD section 3.5: "The statutory threshold is an indicator organism
        concentration of 10 cfu/100mL and a total suspended solids level of 50 mg/L;
        a reading at or above either limit — 10 exactly counts as an exceedance — sets
        `exceeded` true."

        Design: Difficulty/dual_variant_calc/sampling_statutory_vs_internal_threshold_variants
        """
        vessel, voyage, statutory, internal = self._setup_two_inspections()
        evaluated = evaluate_inspection_ok(vessel["id"], voyage["id"], statutory["id"],
                                           evaluator_user_id="fs-eval-1")
        # Statutory variant: 7.0 < 10 and 30.0 < 50 -> no exceedance.
        assert evaluated["exceeded"] is False

    def test_internal_stricter_limits_exceeded_at_same_readings(self, api):
        """PRD section 3.5: "For `COMPANY_INTERNAL` inspections the company applies
        stricter limits of 5 cfu/100mL and 25 mg/L."
        PRD section 3.5: "When `exceeded` is true, evaluation cascades: if the
        inspection kind is `PORT_STATE_CONTROL`, a port state control deficiency is
        created with `action_code` defaulting to `A15`; a noncompliance record with
        `source_type` `SAMPLING_EXCEEDANCE` is created; and the vessel's
        `compliance_posture` is recomputed (it may become `RESTRICTED`)."
        PRD section 3.10: "A sampling exceedance contributes 40 points"
        PRD section 3.10: "A score of at least 70 yields `CRITICAL`; at least 40
        yields `MAJOR`; otherwise `MINOR`."

        Design: Difficulty/dual_variant_calc/sampling_statutory_vs_internal_threshold_variants
        """
        vessel, voyage, statutory, internal = self._setup_two_inspections()
        evaluate_inspection_ok(vessel["id"], voyage["id"], statutory["id"],
                               evaluator_user_id="fs-eval-1")
        evaluated = evaluate_inspection_ok(vessel["id"], voyage["id"], internal["id"],
                                           evaluator_user_id="fs-eval-1")
        # Internal variant: 7.0 >= 5 -> exceeded.
        assert evaluated["exceeded"] is True

        # Exactly one noncompliance record: the statutory variant spawned none.
        records = list_noncompliance(vessel["id"], voyage["id"])
        assert len(records) == 1
        assert records[0]["source_type"] == "SAMPLING_EXCEEDANCE"
        # Score 40 (sampling exceedance), posture OPEN at detection -> MAJOR.
        assert records[0]["severity"] == "MAJOR"


class TestOrganismBoundary:
    def test_organism_exactly_10_is_exceedance(self, api):
        """PRD section 3.5: "The statutory threshold is an indicator organism
        concentration of 10 cfu/100mL and a total suspended solids level of 50 mg/L;
        a reading at or above either limit — 10 exactly counts as an exceedance — sets
        `exceeded` true."

        Design: Difficulty/boundary_precision_check/sampling_organism_exactly_at_limit_exceeded
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000015", vessel_name="MV Osprey", voyage_number="V7001"
        )
        at_limit = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=10.0,
            tss=10.0, recorder_user_id="fs-rec-3",
        )
        evaluated = evaluate_inspection_ok(vessel["id"], voyage["id"], at_limit["id"],
                                           evaluator_user_id="fs-eval-3")
        # "at or above" — the limit comparison is inclusive.
        assert evaluated["exceeded"] is True

        record = find_noncompliance(vessel["id"], voyage["id"],
                                    source_type="SAMPLING_EXCEEDANCE")
        assert record["response_status"] == "OPEN"

    def test_organism_just_below_10_is_not_exceedance(self, api):
        """PRD section 3.5: "The statutory threshold is an indicator organism
        concentration of 10 cfu/100mL and a total suspended solids level of 50 mg/L;
        a reading at or above either limit — 10 exactly counts as an exceedance — sets
        `exceeded` true."

        Design: Difficulty/boundary_precision_check/sampling_organism_exactly_at_limit_exceeded
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000015", vessel_name="MV Osprey", voyage_number="V7001"
        )
        below = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=9.999,
            tss=10.0, sampled_at="2026-07-29T01:00:00Z", recorder_user_id="fs-rec-3",
        )
        evaluated = evaluate_inspection_ok(vessel["id"], voyage["id"], below["id"],
                                           evaluator_user_id="fs-eval-3")
        assert evaluated["exceeded"] is False

        records = list_noncompliance(vessel["id"], voyage["id"])
        assert len(records) == 0, "a sub-limit evaluation must spawn no record"


class TestCleanEvaluation:
    def test_inspection_evaluate_clean_has_no_side_effects(self, api, flag_surveyor_headers):
        """PRD section 3.5: "When `exceeded` is true, evaluation cascades: if the
        inspection kind is `PORT_STATE_CONTROL`, a port state control deficiency is
        created with `action_code` defaulting to `A15`; a noncompliance record with
        `source_type` `SAMPLING_EXCEEDANCE` is created; and the vessel's
        `compliance_posture` is recomputed (it may become `RESTRICTED`)."
        PRD section 2.8: "Otherwise the vessel is `OPEN`."

        Design: Corner/state_machines/inspection_evaluate_clean_has_no_side_effects
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100031", vessel_name="MV Veery", voyage_number="V9310"
        )
        inspection = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="PORT_STATE_CONTROL",
            organism=2.0, tss=5.0, recorder_user_id="psc-1",
        )
        resp = api.evaluate_inspection(vessel["id"], voyage["id"], inspection["id"],
                                       make_flag_surveyor_headers("fs-1"))
        evaluated = validate_success(resp, 200)
        assert evaluated["exceeded"] is False
        assert evaluated["status"] == "EVALUATED"

        assert list_deficiencies(vessel["id"]) == [], (
            "a clean evaluation must spawn no PSC deficiency"
        )
        assert list_noncompliance(vessel["id"], voyage["id"]) == [], (
            "a clean evaluation must spawn no noncompliance record"
        )
        assert get_vessel(vessel["id"])["compliance_posture"] == "OPEN"


class TestInspectionCloseGating:
    def _setup_exceeded_inspection(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000022", vessel_name="MV Vireo", voyage_number="V8004"
        )
        inspection = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=12.0,
            tss=10.0, findings=["BWMS-05"], recorder_user_id="fs-rec-4",
        )
        evaluate_inspection_ok(vessel["id"], voyage["id"], inspection["id"],
                               evaluator_user_id="fs-eval-4")
        record = find_noncompliance(vessel["id"], voyage["id"],
                                    source_type="SAMPLING_EXCEEDANCE")
        return vessel, voyage, inspection, record

    def test_close_blocked_while_linked_record_open(self, api, flag_surveyor_headers):
        """PRD section 3.5: "Closing by a `FlagSurveyor` moves the inspection from
        `EVALUATED` to `CLOSED` — but if `exceeded` is true, every linked
        noncompliance record must first be `RESPONDED` or `CLOSED`"
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/inspection_close_requires_records_responded
        """
        vessel, voyage, inspection, record = self._setup_exceeded_inspection()
        assert record["response_status"] == "OPEN"

        resp = api.close_inspection(vessel["id"], voyage["id"], inspection["id"],
                                    flag_surveyor_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_succeeds_after_record_responded(self, api, flag_surveyor_headers):
        """PRD section 3.5: "Closing by a `FlagSurveyor` moves the inspection from
        `EVALUATED` to `CLOSED` — but if `exceeded` is true, every linked
        noncompliance record must first be `RESPONDED` or `CLOSED`"
        PRD section 3.10: "Response by a `ShoreComplianceOfficer` moves the record
        from `OPEN` to `RESPONDED`, provided the response arrives by
        `response_due_at`; the vessel's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/inspection_close_requires_records_responded
        """
        vessel, voyage, inspection, record = self._setup_exceeded_inspection()

        blocked = api.close_inspection(vessel["id"], voyage["id"], inspection["id"],
                                       flag_surveyor_headers)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        respond_noncompliance_ok(vessel["id"], voyage["id"], record["id"])
        resp = api.close_inspection(vessel["id"], voyage["id"], inspection["id"],
                                    flag_surveyor_headers)
        closed = validate_success(resp, 200)
        assert closed["status"] == "CLOSED"


class TestInspectionReopenCycle:
    def _setup_closed_exceeded_inspection(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000007", vessel_name="MV Gannet", voyage_number="V4002"
        )
        inspection = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=12.0,
            tss=10.0, findings=["BWMS-02"], recorder_user_id="fs-rec-2",
        )
        evaluate_inspection_ok(vessel["id"], voyage["id"], inspection["id"],
                               evaluator_user_id="fs-eval-2")
        record = find_noncompliance(vessel["id"], voyage["id"],
                                    source_type="SAMPLING_EXCEEDANCE")
        respond_noncompliance_ok(vessel["id"], voyage["id"], record["id"])
        close_noncompliance = close_noncompliance_ok(vessel["id"], voyage["id"], record["id"])
        assert close_noncompliance["response_status"] == "CLOSED"
        close_inspection_ok(vessel["id"], voyage["id"], inspection["id"])
        return vessel, voyage, inspection, record

    def test_reopen_closed_inspection_within_90_days(self, api, flag_surveyor_headers):
        """PRD section 3.5: "A closed inspection may be reopened by a `FlagSurveyor`
        within 90 days of `sampled_at`, moving it from `CLOSED` to `REOPENED`"

        Design: Difficulty/non_linear_state_machine/inspection_closed_reopen_cycle_restores_records
        """
        vessel, voyage, inspection, record = self._setup_closed_exceeded_inspection()
        # sampled_at 2026-07-29T00:00:00Z; logical clock 2026-08-01 is within 90 days.
        resp = api.reopen_inspection(vessel["id"], voyage["id"], inspection["id"],
                                     flag_surveyor_headers)
        reopened = validate_success(resp, 200)
        assert reopened["status"] == "REOPENED"

    def test_reopen_reopens_previously_closed_noncompliance_record(
            self, api, flag_surveyor_headers):
        """PRD section 3.5: "reopening flips any noncompliance record previously
        closed under the inspection back from `CLOSED` to `OPEN` and recomputes the
        vessel's posture."

        Design: Difficulty/non_linear_state_machine/inspection_closed_reopen_cycle_restores_records
        """
        vessel, voyage, inspection, record = self._setup_closed_exceeded_inspection()
        resp = api.reopen_inspection(vessel["id"], voyage["id"], inspection["id"],
                                     flag_surveyor_headers)
        validate_success(resp, 200)

        records = list_noncompliance(vessel["id"], voyage["id"])
        target = [r for r in records if r["id"] == record["id"]][0]
        assert target["response_status"] == "OPEN", (
            "the backward cascade must re-open the previously CLOSED record"
        )


class TestReopenNinetyDayWindow:
    def _setup_two_closed_clean_inspections(self):
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000024", vessel_name="MV Xanthus", voyage_number="V9002"
        )
        first = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=1.0,
            tss=1.0, recorder_user_id="fs-rec-5",
        )
        second = record_inspection(
            vessel["id"], voyage["id"], inspection_kind="FLAG_STATE", organism=1.0,
            tss=1.0, recorder_user_id="fs-rec-5",
        )
        for inspection in (first, second):
            evaluate_inspection_ok(vessel["id"], voyage["id"], inspection["id"],
                                   evaluator_user_id="fs-eval-5")
            close_inspection_ok(vessel["id"], voyage["id"], inspection["id"])
        return vessel, voyage, first, second

    def test_reopen_at_exactly_ninety_days_succeeds(self, api, flag_surveyor_headers):
        """PRD section 3.5: "A closed inspection may be reopened by a `FlagSurveyor`
        within 90 days of `sampled_at`, moving it from `CLOSED` to `REOPENED`"

        Design: Difficulty/resource_temporal_overlap/inspection_reopen_ninety_day_closed_window
        """
        vessel, voyage, first, second = self._setup_two_closed_clean_inspections()
        # sampled_at 2026-07-29T00:00:00Z + 90 days == 2026-10-27T00:00:00Z; the
        # appeal window still reaches that instant.
        set_clock("2026-10-27T00:00:00Z")
        resp = api.reopen_inspection(vessel["id"], voyage["id"], first["id"],
                                     flag_surveyor_headers)
        reopened = validate_success(resp, 200)
        assert reopened["status"] == "REOPENED"

    def test_reopen_one_second_past_ninety_days_rejected(self, api, flag_surveyor_headers):
        """PRD section 3.5: "A closed inspection may be reopened by a `FlagSurveyor`
        within 90 days of `sampled_at`, moving it from `CLOSED` to `REOPENED`"
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/inspection_reopen_ninety_day_closed_window
        """
        vessel, voyage, first, second = self._setup_two_closed_clean_inspections()
        set_clock("2026-10-27T00:00:01Z")
        resp = api.reopen_inspection(vessel["id"], voyage["id"], second["id"],
                                     flag_surveyor_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
