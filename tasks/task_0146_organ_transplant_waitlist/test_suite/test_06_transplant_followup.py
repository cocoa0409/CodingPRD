"""Transplant recording (cold-ischemia computation) and follow-up scheduling /
completion / mark-missed gates.

Translates difficulty instance rto_followup_must_not_precede_transplant and
corner instances corner_cold_ischemia_actual_computed and
corner_followup_mark_missed_before_due_invalid_state.
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, setup_transplant, schedule_follow_up,
    create_follow_up_payload,
    make_center_headers,
)


def test_cold_ischemia_hours_actual_computed(api):
    """PRD §3.9: "computes cold_ischemia_hours_actual as the elapsed time from the
    organ's recovered_at to transplanted_at expressed in hours — the difference in
    seconds divided by 3,600 — rounded half-up to two decimal places."

    Design: Corner/calculations/corner_cold_ischemia_actual_computed
    """
    scenario = setup_transplant(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="CI1", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85,
                             recovered_at="2026-06-01T00:00:00Z"),
        transplanted_at="2026-06-01T06:30:00Z")
    # recovered 00:00, transplanted 06:30 -> 6.5 hours.
    assert scenario["transplant"]["cold_ischemia_hours_actual"] == 6.50


def test_followup_before_transplant_rejected(api):
    """PRD §3.9: "A follow-up's scheduled_for may not precede the parent
    transplant's transplanted_at; an earlier schedule is rejected with
    ERR_FOLLOWUP_BEFORE_TRANSPLANT."

    Design: Difficulty/resource_temporal_overlap/rto_followup_must_not_precede_transplant
    """
    scenario = setup_transplant(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="I2", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85),
        transplanted_at="2026-06-01T06:00:00Z")
    center_headers = make_center_headers(scenario["center"]["id"])
    res = api.create_follow_up(
        scenario["transplant"]["id"],
        create_follow_up_payload(interval_label="M1",
                                 scheduled_for="2026-06-01T05:00:00Z",
                                 graft_functioning=True),
        center_headers)
    validate_error(res, "ERR_FOLLOWUP_BEFORE_TRANSPLANT")


def test_mark_missed_before_due_rejected(api):
    """PRD §3.9: "Marking a follow-up missed moves it from SCHEDULED to MISSED and
    is permitted only when the current clock instant is strictly after its
    scheduled_for."

    Design: Corner/state_machines/corner_followup_mark_missed_before_due_invalid_state
    """
    scenario = setup_transplant(
        center_overrides=dict(unos_center_code="C005", region_code=5),
        opo_overrides=dict(opo_code="OPO5", region_code=5),
        candidate_overrides=dict(mrn="S5", blood_type="A",
                                 date_of_birth="1975-01-01T00:00:00Z",
                                 height_cm=178, weight_kg=80),
        organ_overrides=dict(blood_type="O", donor_weight_kg=85),
        transplanted_at="2026-06-01T06:00:00Z")
    center = scenario["center"]
    center_headers = make_center_headers(center["id"])
    # Follow-up due 2026-12-01; clock still at 2026-06-01 (before due).
    fu = schedule_follow_up(center, scenario["transplant"], interval_label="M6",
                            scheduled_for="2026-12-01T00:00:00Z", graft_functioning=True)
    res = api.mark_follow_up_missed(fu["id"], center_headers)
    validate_error(res, "ERR_INVALID_STATE")
