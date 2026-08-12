"""Discharge cascade tests: execute depth-3 chain, throughput boundary,
STAT-consult safety gate, patient state lockdown after discharge.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, create_discharge_order_for, create_consult_for,
    discharge_patient,
)

ADMIN = TEST_USERS["group_admin_headers"]


def _setup_h1_p1(api, mrn="M701", acuity="MEDIUM", stay_type="OBSERVATION",
                admitted_at="2026-05-01T08:30:00Z"):
    """H1 ACTIVE shift + P1 admitted and accepted. Returns (h1, s1, p1, asg_id)."""
    h1 = create_hospitalist("H One", "INTERNAL_MEDICINE", max_census_cap=16)
    s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
    set_clock("2026-05-01T09:00:00Z")
    p1 = create_patient(mrn=mrn, acuity=acuity, admit_source="ED",
                        stay_type=stay_type, admitted_at=admitted_at)
    _, asg_id = admit_and_accept(p1["id"])
    return h1, s1, p1, asg_id


class TestDischargeExecuteDepth3Chain:
    """Difficulty instance: discharge_execute_depth3_chain."""

    def test_execute_cascades_patient_discharge_and_obs_close(self, api):
        """PRD §3.5: "The patient flips `ADMITTED` → `DISCHARGED`, and the
        observation axis moves `OBS_ACTIVE` → `OBS_CLOSED` in the same stroke
        while `NONE` stays `NONE`."

        Design: Difficulty/transitive_cascade/discharge_execute_depth3_chain
        """
        h1, s1, p1, asg_id = _setup_h1_p1(api)
        order = create_discharge_order_for(p1["id"], h1["id"],
                                           target_discharge_at="2026-05-03T15:00:00Z",
                                           order=True)
        exe = get_success_data(api.execute_discharge_order(
            order["id"], make_hospitalist_headers(h1["id"])
        ))
        assert exe["status"] == "EXECUTED"
        # 2026-05-01T09:00:00Z <= cutoff 2026-05-03T11:00:00Z -> meets target
        assert exe["meets_throughput_target"] is True
        p_now = get_success_data(api.get_patient(p1["id"], ADMIN))
        assert p_now["admission_status"] == "DISCHARGED"
        assert p_now["observation_status"] == "OBS_CLOSED"

    def test_execute_closes_assignment_and_decrements_census(self, api):
        """PRD §3.5: "The patient's `ACTIVE` assignment closes with
        `close_reason` `DISCHARGE` and `closed_at` stamped; the responsible
        hospitalist's `current_census` decrements by one and
        `distribution_eligible` recomputes".

        Design: Difficulty/transitive_cascade/discharge_execute_depth3_chain
        """
        h1, s1, p1, asg_id = _setup_h1_p1(api)
        order = create_discharge_order_for(p1["id"], h1["id"], order=True)
        get_success_data(api.execute_discharge_order(
            order["id"], make_hospitalist_headers(h1["id"])
        ))
        asg_now = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_now["status"] == "CLOSED"
        assert asg_now["close_reason"] == "DISCHARGE"
        assert asg_now["closed_at"] is not None
        h_now = get_success_data(api.get_hospitalist(h1["id"], ADMIN))
        assert h_now["current_census"] == 0


class TestThroughputCutoffExactBoundary:
    """Corner instance: throughput_cutoff_exact_boundary."""

    def test_execute_exactly_at_cutoff_meets_target(self, api):
        """PRD §3.5: "`meets_throughput_target` is computed: true when
        `executed_at` falls at or before 11:00:00Z on the calendar date of
        `target_discharge_at` — equality meets the target, compared at
        millisecond precision".

        Design: Corner/calculations/throughput_cutoff_exact_boundary
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        # Shift spans multiple days so it covers both executions
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-03T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="K001", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        admit_and_accept(p1["id"])
        p2 = create_patient(mrn="K002", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:05:00Z")
        admit_and_accept(p2["id"])
        d1 = create_discharge_order_for(p1["id"], h1["id"], "2026-05-02T15:00:00Z", order=True)
        d2 = create_discharge_order_for(p2["id"], h1["id"], "2026-05-02T15:00:00Z", order=True)

        # Execute d1 exactly at the 11:00:00Z cutoff
        set_clock("2026-05-02T11:00:00Z")
        e1 = get_success_data(api.execute_discharge_order(d1["id"], make_hospitalist_headers(h1["id"])))
        assert e1["meets_throughput_target"] is True

        # Execute d2 one second past
        set_clock("2026-05-02T11:00:01Z")
        e2 = get_success_data(api.execute_discharge_order(d2["id"], make_hospitalist_headers(h1["id"])))
        assert e2["meets_throughput_target"] is False


class TestDischargeExecuteFromPlannedRejected:
    """Corner instance: discharge_execute_from_planned_rejected."""

    def test_execute_from_planned_fails(self, api):
        """PRD §3.5: "Execution moves `ORDERED` → `EXECUTED` under the same
        ownership rule and only from `ORDERED` (else
        `ERR_DISCHARGE_ORDER_INVALID_STATE`)".

        Design: Corner/state_machines/discharge_execute_from_planned_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="S002", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        admit_and_accept(p1["id"])
        d1 = create_discharge_order_for(p1["id"], h1["id"], order=False)
        resp = api.execute_discharge_order(d1["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_DISCHARGE_ORDER_INVALID_STATE)
        # Order remains PLANNED; patient remains ADMITTED
        d_now = get_success_data(api.get_discharge_order(d1["id"], ADMIN))
        assert d_now["status"] == "PLANNED"
        p_now = get_success_data(api.get_patient(p1["id"], ADMIN))
        assert p_now["admission_status"] == "ADMITTED"


class TestDischargeBlockedByOpenStatConsult:
    """Corner instance: discharge_blocked_by_open_stat_consult."""

    def test_open_stat_blocks_execution(self, api):
        """PRD §3.5: "no `STAT`-priority consult for this patient may sit in
        `OPEN`, `ESCALATED`, `ACKNOWLEDGED`, or `REOPENED`, else
        `ERR_OPEN_STAT_CONSULT_BLOCKS_DISCHARGE` (HTTP 422)."

        Design: Corner/errors/discharge_blocked_by_open_stat_consult
        """
        h1, s1, p1, asg_id = _setup_h1_p1(api, mrn="X008", acuity="HIGH",
                                          stay_type="INPATIENT",
                                          admitted_at="2026-05-01T08:00:00Z")
        create_consult_for(p1["id"], h1["id"], specialty="CARDIOLOGY",
                           priority="STAT", reason="unstable")
        d1 = create_discharge_order_for(p1["id"], h1["id"], order=True)
        resp = api.execute_discharge_order(d1["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_STAT_CONSULT_BLOCKS_DISCHARGE)
        d_now = get_success_data(api.get_discharge_order(d1["id"], ADMIN))
        assert d_now["status"] == "ORDERED"
        p_now = get_success_data(api.get_patient(p1["id"], ADMIN))
        assert p_now["admission_status"] == "ADMITTED"


class TestExecuteUnorderedWithOpenStatConsult:
    """Difficulty instance: execute_unordered_with_open_stat_consult."""

    def test_state_error_masks_safety_error(self, api):
        """PRD §2.7: "Every request passes through a nine-tier validation
        pipeline, and the tiers run in a fixed relative order — an earlier
        tier's failure masks later tiers, so callers always see the earliest
        applicable rejection."
        PRD §2.7 item 5: state preconditions include
        `ERR_DISCHARGE_ORDER_INVALID_STATE` (HTTP 409).
        PRD §2.7 item 6: "A discharge execution colliding with an unresolved
        `STAT` consult is refused — `ERR_OPEN_STAT_CONSULT_BLOCKS_DISCHARGE`
        (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/execute_unordered_with_open_stat_consult
        """
        h1, s1, p1, asg_id = _setup_h1_p1(api, mrn="M901", acuity="HIGH",
                                          stay_type="INPATIENT",
                                          admitted_at="2026-05-01T08:00:00Z")
        create_consult_for(p1["id"], h1["id"], specialty="CARDIOLOGY",
                           priority="STAT", reason="chest pain")
        # Order left in PLANNED (never ordered)
        d1 = create_discharge_order_for(p1["id"], h1["id"], order=False)
        resp = api.execute_discharge_order(d1["id"], make_hospitalist_headers(h1["id"]))
        # Tier 5 (state) fires before tier 6 (safety)
        validate_error(resp, ApiErrorId.ERR_DISCHARGE_ORDER_INVALID_STATE)

    def test_state_error_leaves_order_and_patient_unchanged(self, api):
        """PRD §3.5: "Execution moves `ORDERED` → `EXECUTED` ... only from
        `ORDERED` (else `ERR_DISCHARGE_ORDER_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/execute_unordered_with_open_stat_consult
        """
        h1, s1, p1, asg_id = _setup_h1_p1(api, mrn="M902", acuity="HIGH",
                                          stay_type="INPATIENT",
                                          admitted_at="2026-05-01T08:00:00Z")
        create_consult_for(p1["id"], h1["id"], specialty="CARDIOLOGY",
                           priority="STAT", reason="chest pain")
        d1 = create_discharge_order_for(p1["id"], h1["id"], order=False)
        api.execute_discharge_order(d1["id"], make_hospitalist_headers(h1["id"]))
        d_now = get_success_data(api.get_discharge_order(d1["id"], ADMIN))
        assert d_now["status"] == "PLANNED"
        p_now = get_success_data(api.get_patient(p1["id"], ADMIN))
        assert p_now["admission_status"] == "ADMITTED"


class TestPatientDischargedRejectsNewConsult:
    """Corner instance: patient_discharged_rejects_new_consult."""

    def test_consult_on_discharged_patient_rejected(self, api):
        """PRD §3.7: "the caller must hold the patient's `ACTIVE` assignment
        (ownership, else `ERR_UNAUTHORIZED_ROLE`), the patient must be
        `ADMITTED` (else `ERR_PATIENT_NOT_ADMITTED`)".
        PRD §3.5: executing a discharge order closes the patient's `ACTIVE`
        assignment with `close_reason` `DISCHARGE` — so after discharge the
        caller no longer holds an `ACTIVE` assignment.
        PRD §2.7: the nine-tier pipeline runs authorization/ownership
        (tier 2) before cross-entity rules (tier 8, where
        `ERR_PATIENT_NOT_ADMITTED` lives), and "an earlier tier's failure
        masks later tiers".

        Design: Corner/state_machines/patient_discharged_rejects_new_consult
        """
        h1, s1, p1, asg_id = _setup_h1_p1(api, mrn="S007", acuity="LOW",
                                          stay_type="INPATIENT",
                                          admitted_at="2026-05-01T08:00:00Z")
        discharge_patient(p1["id"], h1["id"])
        resp = api.create_consult_request(
            p1["id"],
            {"specialty": "SURGERY", "priority": "ROUTINE", "reason": "post-discharge question"},
            make_hospitalist_headers(h1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
