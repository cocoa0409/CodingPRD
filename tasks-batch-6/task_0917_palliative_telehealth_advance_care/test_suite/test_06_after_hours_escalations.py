"""After-hours escalation tiers and the two independent status axes."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assert_escalation, assert_same_instant
from test_helpers.fixtures import (
    NURSE,
    ONCALL,
    active_care_plan,
    enroll_patient,
    file_symptom_assessment,
    open_escalation,
    read_patient,
    set_clock,
)


def _escalated_assessment(clock="2026-06-01T00:00:00Z", **items):
    """Enrolled patient, ACTIVE plan, one assessment, one open escalation."""
    patient, _ = enroll_patient(clock=clock, full_name="Elin Vasquez")
    plan = active_care_plan(patient["id"], plan_title="Dyspnea and pain plan",
                            problem_list=["pain", "dyspnea"])
    assessment = file_symptom_assessment(
        patient["id"], plan["id"], reporter_type="SELF", **items
    )
    return patient, plan, assessment


# ---------------------------------------------------------------------------
# The two axes move independently
# ---------------------------------------------------------------------------
def test_triage_and_escalation_axes_advance_without_touching_each_other(api):
    """PRD 3.5: "Those two status fields are **independent axes on the same row**,
    and this is the point most easily got wrong. Clinical triage advances along
    `triage_status`, from `OPEN` to `ACKNOWLEDGED` to `RESOLVED`. After-hours
    handling advances along `escalation_status`, from `NONE` to `ESCALATED` to
    `DISPOSITIONED`. An assessment can be `ACKNOWLEDGED` on the triage axis while
    still `NONE` on the escalation axis, and equally can be `ESCALATED` while
    still `OPEN`. Neither axis's transitions touch the other's value."
    PRD 3.6: "Opening one requires the named assessment to sit at
    `escalation_status` `NONE` with a `triage_status` of `OPEN` or `ACKNOWLEDGED`;
    the assessment's `escalation_status` then moves `NONE → ESCALATED` while its
    `triage_status` is left exactly as it was."

    Design: Difficulty/non_linear_state_machine/symptom_assessment_triage_and_escalation_axes_advance_independently
    """
    patient, _, assessment = _escalated_assessment(
        item_pain=6, item_dyspnea=6, item_nausea=6, item_anxiety=6, item_fatigue=6
    )
    assert assessment["distress_score"] == 60
    assert assessment["severity_tier"] == "MODERATE"

    acknowledged = validate_success(
        api.update_symptom_triage(
            assessment["id"], {"action": "ACKNOWLEDGE", "triage_note": "nurse reviewed"}, NURSE
        )
    )
    assert acknowledged["triage_status"] == "ACKNOWLEDGED"
    assert acknowledged["escalation_status"] == "NONE", (
        "acknowledging on the triage axis must leave the escalation axis alone"
    )

    escalation = open_escalation(
        patient["id"],
        assessment["id"],
        contact_summary="family called overnight about breathlessness",
    )
    after_open = validate_success(api.get_symptom_assessment(assessment["id"], NURSE))
    assert after_open["escalation_status"] == "ESCALATED"
    assert after_open["triage_status"] == "ACKNOWLEDGED", (
        "opening an escalation must leave triage_status exactly as it was"
    )

    validate_success(
        api.respond_escalation(escalation["id"], {"response_type": "ACKNOWLEDGE"}, ONCALL)
    )
    validate_success(
        api.respond_escalation(
            escalation["id"],
            {"response_type": "DISPOSITION", "disposition": "URGENT_TELEHEALTH_VISIT"},
            ONCALL,
        )
    )

    after_disposition = validate_success(api.get_symptom_assessment(assessment["id"], NURSE))
    assert after_disposition["escalation_status"] == "DISPOSITIONED"
    assert after_disposition["triage_status"] == "ACKNOWLEDGED"


def test_resolving_after_a_disposition_closes_the_escalation_and_the_counter(api):
    """PRD 3.5: "`RESOLVE` moves `ACKNOWLEDGED → RESOLVED`; it stamps
    `resolution_reason` as `ESCALATION_DISPOSITIONED` when the row's
    `escalation_status` is `DISPOSITIONED` and as `SYMPTOM_CONTROLLED` otherwise;
    it decrements the patient's `open_symptom_count` by 1; and it closes out the
    after-hours side by moving every on-call escalation naming this assessment and
    sitting in `DISPOSITIONED` to `CLOSED`."
    PRD 3.6: "A `DISPOSITION` response applies only to an escalation already in
    `ACKNOWLEDGED`, moves it to `DISPOSITIONED`, stores the `disposition`, and
    pushes the linked assessment's `escalation_status` from `ESCALATED` to
    `DISPOSITIONED` while again leaving its `triage_status` untouched."

    Design: Difficulty/non_linear_state_machine/symptom_assessment_triage_and_escalation_axes_advance_independently
    """
    patient, _, assessment = _escalated_assessment(
        item_pain=6, item_dyspnea=6, item_nausea=6, item_anxiety=6, item_fatigue=6
    )
    validate_success(
        api.update_symptom_triage(
            assessment["id"], {"action": "ACKNOWLEDGE", "triage_note": "nurse reviewed"}, NURSE
        )
    )
    escalation = open_escalation(
        patient["id"],
        assessment["id"],
        contact_summary="family called overnight about breathlessness",
    )
    validate_success(
        api.respond_escalation(escalation["id"], {"response_type": "ACKNOWLEDGE"}, ONCALL)
    )
    validate_success(
        api.respond_escalation(
            escalation["id"],
            {"response_type": "DISPOSITION", "disposition": "URGENT_TELEHEALTH_VISIT"},
            ONCALL,
        )
    )

    resolved = validate_success(
        api.update_symptom_triage(
            assessment["id"],
            {"action": "RESOLVE", "triage_note": "symptom controlled after visit"},
            NURSE,
        )
    )

    assert resolved["triage_status"] == "RESOLVED"
    assert resolved["escalation_status"] == "DISPOSITIONED"
    assert resolved["resolution_reason"] == "ESCALATION_DISPOSITIONED"

    closed = validate_success(api.get_escalation(escalation["id"], ONCALL))
    assert closed["status"] == "CLOSED"
    assert closed["disposition"] == "URGENT_TELEHEALTH_VISIT"
    assert read_patient(patient["id"])["open_symptom_count"] == 0


# ---------------------------------------------------------------------------
# Tier promotion and its ceiling
# ---------------------------------------------------------------------------
def test_promotion_needs_the_deadline_and_stops_at_the_third_tier(api):
    """PRD 3.6: "`ack_due_at` is `tier_notified_at` plus 15 minutes at tier 1,
    plus 30 minutes at tier 2, and plus 60 minutes at tier 3."
    PRD 3.6: "Promotion is a self-loop on `TIER_NOTIFIED`: it requires the current
    `tier` to be strictly below the ceiling of 3 and the current logical clock to
    be at or after `ack_due_at` — exactly `ack_due_at` permits promotion, one
    second earlier does not. It increments `tier` by 1, re-stamps
    `tier_notified_at` to the current clock, and recomputes `ack_due_at` from the
    new tier's deadline. There is no transition out of tier 3 by promotion, so a
    fourth attempt is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/escalation_tier_promotion_is_capped_at_tier_three
    """
    patient, _, assessment = _escalated_assessment(
        item_pain=10, item_dyspnea=10, item_nausea=5, item_anxiety=5, item_fatigue=5
    )
    assert assessment["distress_score"] == 70
    assert assessment["severity_tier"] == "SEVERE"

    escalation = open_escalation(
        patient["id"], assessment["id"], contact_summary="uncontrolled pain overnight"
    )
    assert_escalation(escalation)
    assert escalation["tier"] == 1
    assert_same_instant(
        escalation["ack_due_at"], "2026-06-01T00:15:00Z", "OnCallEscalation.ack_due_at"
    )

    set_clock("2026-06-01T00:14:00Z")
    validate_error(
        api.promote_escalation(escalation["id"], {}, ONCALL),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    set_clock("2026-06-01T00:15:00Z")
    tier_two = validate_success(api.promote_escalation(escalation["id"], {}, ONCALL))
    assert tier_two["tier"] == 2

    set_clock("2026-06-01T00:45:00Z")
    tier_three = validate_success(api.promote_escalation(escalation["id"], {}, ONCALL))
    assert tier_three["tier"] == 3
    assert_same_instant(
        tier_three["tier_notified_at"],
        "2026-06-01T00:45:00Z",
        "OnCallEscalation.tier_notified_at",
    )
    assert_same_instant(
        tier_three["ack_due_at"], "2026-06-01T01:45:00Z", "OnCallEscalation.ack_due_at"
    )

    set_clock("2026-06-01T01:45:00Z")
    validate_error(
        api.promote_escalation(escalation["id"], {}, ONCALL),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    final = validate_success(api.get_escalation(escalation["id"], ONCALL))
    assert final["tier"] == 3
    assert final["status"] == "TIER_NOTIFIED"


# ---------------------------------------------------------------------------
# Escalations are reachable from the assessment they name
# ---------------------------------------------------------------------------
def test_escalations_filter_by_symptom_assessment_returns_only_the_linked_child(api):
    """PRD 2.3: "Most list endpoints also accept domain filters, and every filter
    is optional; when several are supplied they combine conjunctively, so a row
    must match all of them to be returned."
    PRD 3.6: "When a symptom report arrives outside clinic hours, an
    `OnCallClinician` or `PalliativeNurse` opens an escalation carrying
    `patient_id`, `symptom_assessment_id` naming the assessment that triggered it,
    and a `contact_summary`."

    Design: Corner/endpoints/escalations_filtered_by_symptom_assessment_returns_the_linked_child
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Tova Grimes")
    plan = active_care_plan(patient["id"], plan_title="Plan", problem_list=["pain"])

    first = file_symptom_assessment(
        patient["id"], plan["id"], reporter_type="SELF",
        item_pain=6, item_dyspnea=6, item_nausea=6, item_anxiety=6, item_fatigue=6,
    )
    second = file_symptom_assessment(
        patient["id"], plan["id"], reporter_type="SELF",
        item_pain=4, item_dyspnea=4, item_nausea=4, item_anxiety=4, item_fatigue=4,
    )
    open_escalation(patient["id"], first["id"], contact_summary="call about assessment one")
    second_escalation = open_escalation(
        patient["id"], second["id"], contact_summary="call about assessment two"
    )

    rows, meta = validate_paginated(
        api.list_escalations(ONCALL, params={"symptom_assessment_id": second["id"]})
    )

    assert len(rows) == 1, f"only the linked escalation should match, got {len(rows)}"
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second_escalation["id"]

    linked = validate_success(api.get_symptom_assessment(second["id"], NURSE))
    assert linked["escalation_status"] == "ESCALATED"
    assert linked["distress_score"] == 40
    assert linked["severity_tier"] == "MODERATE"
