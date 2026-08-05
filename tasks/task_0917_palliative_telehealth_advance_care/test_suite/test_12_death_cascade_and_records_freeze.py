"""Death, the five-hop closure cascade and the program-wide records freeze."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assert_same_instant, find_by_id
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN,
    BILLING,
    NURSE,
    PHYSICIAN,
    SOCIAL_WORKER,
    active_care_plan,
    active_medication_order,
    attest_conference,
    book_conference,
    create_claim,
    delivered_equipment_order,
    enroll_patient,
    file_symptom_assessment,
    hold_conference,
    open_escalation,
    open_hospice_election,
    read_care_plan,
    read_inventory,
    read_patient,
    record_death,
    set_clock,
    stock_inventory,
)


def _full_chart():
    """A chart with every entity the death cascade must touch."""
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Gio Ahmadi")
    election = open_hospice_election(patient["id"])
    order = active_medication_order(
        patient["id"],
        drug="MORPHINE_PO",
        dose_amount=30,
        days_supply=14,
        breakthrough_drug="MORPHINE_PO",
    )
    plan = active_care_plan(patient["id"], plan_title="Comfort plan", problem_list=["pain"])
    assessment = file_symptom_assessment(
        patient["id"],
        plan["id"],
        reporter_type="SELF",
        item_pain=6,
        item_dyspnea=6,
        item_nausea=6,
        item_anxiety=6,
        item_fatigue=6,
    )
    escalation = open_escalation(
        patient["id"], assessment["id"], contact_summary="night call for pain crisis"
    )
    return patient, election, order, plan, assessment, escalation


def _frozen_closed_plan():
    """A plan that reached ACTIVE, plus the version read at that moment, then a death."""
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Ivo Marchetti")
    plan = active_care_plan(patient["id"], plan_title="Comfort plan", problem_list=["pain"])
    stale_version = plan["version"]
    record_death(patient["id"])
    return patient, plan, stale_version


# ---------------------------------------------------------------------------
# The five-hop death cascade
# ---------------------------------------------------------------------------
def test_a_death_closes_the_election_and_discontinues_the_analgesic_orders(api):
    """PRD 2.10: "Recording a death event sets `program_status` to `DECEASED`,
    sets `records_frozen` true, stamps `deceased_at` from the logical clock and
    increments the patient's `version` by 1. Then: **hop 1**, every hospice
    election for this patient whose `status` is `PENDING_CERT`, `CERTIFIED`,
    `ELECTED` or `REVOKED` moves to `CLOSED_ON_DEATH`; **hop 2**, because that
    election closed, every medication order for this patient whose `status` is
    `PENDING_VERIFICATION`, `ACTIVE` or `REVIEW_REQUIRED` moves to `DISCONTINUED`
    and the patient's `active_daily_mme` is recomputed to 0.0"

    Design: Difficulty/transitive_cascade/death_event_drives_five_hop_program_closure_chain
    """
    patient, election, order, _, _, _ = _full_chart()
    assert election["status"] == "PENDING_CERT"
    assert order["status"] == "ACTIVE"

    deceased = validate_success(
        api.create_death_event(
            patient["id"], {"pronouncing_clinician_user_id": "u_physician_1"}, PHYSICIAN
        )
    )

    assert deceased["program_status"] == "DECEASED"
    assert deceased["records_frozen"] is True
    assert_same_instant(
        deceased["deceased_at"], "2026-06-01T00:00:00Z", "Patient.deceased_at"
    )
    assert float(deceased["active_daily_mme"]) == 0.0

    closed_election = validate_success(
        api.get_hospice_election(election["id"], PHYSICIAN)
    )
    assert closed_election["status"] == "CLOSED_ON_DEATH"

    orders, _ = validate_paginated(
        api.list_patient_medication_orders(patient["id"], PHYSICIAN)
    )
    discontinued = find_by_id(orders, order["id"])
    assert discontinued is not None
    assert discontinued["status"] == "DISCONTINUED"

    listed = validate_success(api.get_patient(patient["id"], ADMIN))
    assert float(listed["active_daily_mme"]) == 0.0


def test_the_cascade_reaches_the_plan_the_assessment_and_the_escalation(api):
    """PRD 2.10: "**hop 3**, because those medication orders were discontinued,
    every care plan for this patient whose `status` is `DRAFT`, `ACTIVE` or
    `UNDER_REVISION` moves to `CLOSED` with `closed_reason` `PATIENT_DEATH`; **hop
    4**, because those plans closed, every symptom assessment filed under a closed
    plan whose `triage_status` is `OPEN` or `ACKNOWLEDGED` has its `triage_status`
    set to `RESOLVED` with `resolution_reason` `PLAN_CLOSED`, and the patient's
    `open_symptom_count` is recomputed to 0; **hop 5**, because those assessments
    resolved, every on-call escalation naming one of them in
    `symptom_assessment_id` whose `status` is `TIER_NOTIFIED`, `ACKNOWLEDGED` or
    `DISPOSITIONED` moves to `CLOSED` with `disposition` `ADMINISTRATIVE_CLOSE`."

    Design: Difficulty/transitive_cascade/death_event_drives_five_hop_program_closure_chain
    """
    patient, _, _, plan, assessment, escalation = _full_chart()
    assert escalation["status"] == "TIER_NOTIFIED"

    validate_success(
        api.create_death_event(
            patient["id"], {"pronouncing_clinician_user_id": "u_physician_1"}, PHYSICIAN
        )
    )

    closed_plan = read_care_plan(plan["id"])
    assert closed_plan["status"] == "CLOSED"
    assert closed_plan["closed_reason"] == "PATIENT_DEATH"

    resolved = validate_success(api.get_symptom_assessment(assessment["id"], NURSE))
    assert resolved["triage_status"] == "RESOLVED"
    assert resolved["resolution_reason"] == "PLAN_CLOSED"

    closed_escalation = validate_success(api.get_escalation(escalation["id"], NURSE))
    assert closed_escalation["status"] == "CLOSED"
    assert closed_escalation["disposition"] == "ADMINISTRATIVE_CLOSE"

    assert read_patient(patient["id"])["open_symptom_count"] == 0


def test_the_death_event_response_already_carries_the_cascade_effects(api):
    """PRD 3.12: "Recording the death sets `program_status` to `DECEASED` — the
    terminal state of the patient lifecycle — sets `records_frozen` true, stamps
    `deceased_at` from the logical clock and increments the patient's `version` by
    1."
    PRD 4: "Every creating operation returns the resource it created, and every
    other operation returns the resource named by the identifier in its path — a
    capacity determination and a death event both return the updated patient"

    Design: Corner/consistency_model/death_cascade_effects_are_visible_in_the_same_response
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Bram Oyelaran")
    order = active_medication_order(
        patient["id"], drug="MORPHINE_PO", dose_amount=30, days_supply=14
    )
    plan = active_care_plan(patient["id"], plan_title="Plan", problem_list=["pain"])
    file_symptom_assessment(
        patient["id"],
        plan["id"],
        reporter_type="SELF",
        item_pain=6,
        item_dyspnea=6,
        item_nausea=6,
        item_anxiety=6,
        item_fatigue=6,
    )

    body = validate_success(
        api.create_death_event(
            patient["id"], {"pronouncing_clinician_user_id": "u_physician_1"}, PHYSICIAN
        )
    )

    assert body["program_status"] == "DECEASED", (
        "the death-event response body itself must already show the cascade's effects"
    )
    assert float(body["active_daily_mme"]) == 0.0
    assert body["records_frozen"] is True
    assert body["open_symptom_count"] == 0

    assert read_care_plan(plan["id"])["status"] == "CLOSED"
    orders, _ = validate_paginated(
        api.list_patient_medication_orders(patient["id"], PHYSICIAN)
    )
    discontinued = find_by_id(orders, order["id"])
    assert discontinued is not None
    assert discontinued["status"] == "DISCONTINUED"


# ---------------------------------------------------------------------------
# The freeze pre-empts every business rung
# ---------------------------------------------------------------------------
def test_the_freeze_is_reported_instead_of_the_state_and_version_failures(api):
    """PRD 2.5: "Because rung 6 sits above every business rung, no rule numbered 7
    or higher is ever reachable on a frozen patient; the freeze is reported
    instead."
    PRD 3.12: "Everything else — a new referral decision, a care plan activation,
    a symptom assessment, a signature, an execution, an attestation on a
    code-status order, a medication refill, a hospice certification, an escalation
    response — is refused with `ERR_RECORD_FROZEN`, and because that check sits
    above every business rung, it is the error the client sees even when the
    request would have failed some other rule as well."

    Design: Difficulty/priority_pair_validation_conflict/record_freeze_preempts_invalid_state_and_stale_version_on_plan_revision
    """
    patient, plan, stale_version = _frozen_closed_plan()

    closed = read_care_plan(plan["id"])
    assert closed["status"] == "CLOSED", "the death cascade closed the plan"
    assert closed["version"] > stale_version, (
        "the closure cascade advanced the plan version past the one the client holds"
    )

    rejected = api.revise_care_plan(
        plan["id"],
        {
            "expected_care_plan_version": stale_version,
            "revised_problem_list": ["pain", "delirium"],
        },
        NURSE,
    )
    error = validate_error(rejected, ApiErrorId.ERR_RECORD_FROZEN.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_STATE.value
    assert error["error_id"] != ApiErrorId.ERR_STALE_CARE_PLAN_VERSION.value

    unchanged = read_care_plan(plan["id"])
    assert unchanged["status"] == "CLOSED"
    assert unchanged["problem_list"] == ["pain"], (
        "the rejected revision must not have replaced the problem list"
    )


def test_the_freeze_pre_empts_the_version_guard_even_with_a_current_version(api):
    """PRD 2.5: "**Records freeze.** The patient reached by this request does not
    have `records_frozen` set to true, unless the operation is one of the five
    that remain permitted after death. Otherwise `ERR_RECORD_FROZEN` (409)."
    PRD 2.7: "All three checks sit at rung 8 of the ladder, so a frozen patient, a
    bad state or a missing row is reported before the version is even compared."

    Design: Difficulty/priority_pair_validation_conflict/record_freeze_preempts_invalid_state_and_stale_version_on_plan_revision
    """
    _, plan, _ = _frozen_closed_plan()
    current = read_care_plan(plan["id"])

    rejected = api.revise_care_plan(
        plan["id"],
        {
            "expected_care_plan_version": current["version"],
            "revised_problem_list": ["pain", "delirium"],
        },
        NURSE,
    )
    validate_error(rejected, ApiErrorId.ERR_RECORD_FROZEN.value, 409)

    assert read_care_plan(plan["id"])["problem_list"] == ["pain"]


# ---------------------------------------------------------------------------
# The five permitted post-death writes
# ---------------------------------------------------------------------------
def test_the_five_permitted_operations_survive_the_freeze(api):
    """PRD 2.6: "Exactly five write operations survive the freeze, because each of
    them legitimately happens after a death: closing an equipment order (`POST
    /palliative/dme-orders/{id}/close`, which is how equipment is picked up on
    discharge), recording a conference note attestation (`POST
    /palliative/conferences/{id}/attestations`), attesting a claim (`POST
    /palliative/claims/{id}/attest`), submitting a claim (`POST
    /palliative/claims/{id}/submit`) and adjudicating a claim (`POST
    /palliative/claims/{id}/adjudicate`). Every other write against a frozen
    patient is refused, including a second death event on the same patient."
    PRD 3.9: "`PICKED_UP_ON_DISCHARGE` is the bereavement leg: closing an
    equipment order is one of the five operations permitted while a patient's
    records are frozen, which is why the death cascade deliberately leaves
    `DELIVERED` equipment orders open rather than closing them itself."

    Design: Corner/validations/permitted_post_death_operations_bypass_the_records_freeze
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Pau Ferrer")
    plan = active_care_plan(patient["id"], plan_title="Plan", problem_list=["pain"])
    inventory = stock_inventory(
        device_type="OXYGEN_CONCENTRATOR", total_units=3, prior_auth_required=False
    )
    equipment = delivered_equipment_order(
        patient["id"],
        inventory["id"],
        quantity=1,
        delivery_window_start="2026-06-02T08:00:00Z",
        delivery_window_end="2026-06-02T10:00:00Z",
    )

    conference = book_conference(
        patient["id"],
        conference_type="FAMILY",
        modality="IN_PERSON",
        scheduled_start="2026-06-03T09:00:00Z",
        scheduled_end="2026-06-03T10:00:00Z",
    )
    set_clock("2026-06-03T09:00:00Z")
    hold_conference(
        conference["id"],
        documented_minutes=46,
        disciplines_present=["PHYSICIAN", "SOCIAL_WORKER"],
    )
    attest_conference(conference["id"], "PHYSICIAN", "final family meeting documented")

    claim = create_claim(
        patient["id"],
        service_date="2026-06-03T09:30:00Z",
        documented_minutes=46,
        modality="IN_PERSON",
        conference_id=conference["id"],
    )

    frozen = record_death(patient["id"])
    assert frozen["records_frozen"] is True
    assert read_care_plan(plan["id"])["status"] == "CLOSED"

    picked_up = validate_success(
        api.close_dme_order(
            equipment["id"], {"closed_reason": "PICKED_UP_ON_DISCHARGE"}, NURSE
        )
    )
    assert picked_up["status"] == "CLOSED"
    assert picked_up["closed_reason"] == "PICKED_UP_ON_DISCHARGE"
    assert read_inventory(inventory["id"])["available_units"] == 3

    completed = validate_success(
        api.attest_conference(
            conference["id"],
            {"discipline": "SOCIAL_WORKER", "note_text": "bereavement contact recorded"},
            SOCIAL_WORKER,
        )
    )
    assert completed["status"] == "ATTESTED"

    validate_success(
        api.attest_claim(
            claim["id"], {"attestation_statement": "final documentation attested"}, BILLING
        )
    )
    validate_success(api.submit_claim(claim["id"], {}, BILLING))
    paid = validate_success(api.adjudicate_claim(claim["id"], {"outcome": "PAID"}, ADMIN))
    assert paid["status"] == "PAID"

    final_patient = read_patient(patient["id"])
    assert final_patient["acp_minutes_claimed"] == 46
    assert final_patient["acp_paid_cents_ytd"] == 12880

    refused = api.create_symptom_assessment(
        f.symptom_assessment_payload(
            patient["id"],
            plan["id"],
            reporter_type="SELF",
            item_pain=3,
            item_dyspnea=3,
            item_nausea=3,
            item_anxiety=3,
            item_fatigue=3,
        ),
        NURSE,
    )
    validate_error(refused, ApiErrorId.ERR_RECORD_FROZEN.value, 409)
