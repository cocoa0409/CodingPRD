"""Discharge gating and cascade, government-filing lifecycle (including the cyclic
revision loop and SSN prerequisite), follow-up task escalation, and the cross-entity
and priority-conflict rules around discharge.

Difficulty queue: non_linear_state_machine (followup cycle, filing loop),
transitive_cascade (discharge spawns tasks), priority_pair_validation_conflict
(state beats prerequisite), cross_entity_state_dependency (discharge/SSN).
Corner queue: bag-already-issued, pharmacy signoff, legal-name, terminal lockdown,
filing-cancel state, filtered list, patch.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f


# =========================================================================
# Difficulty/non_linear_state_machine/followup_task_cyclic_record_attempt_then_escalate
# =========================================================================
class TestFollowUpCyclicEscalation:
    def test_third_attempt_escalates_task(self, api):
        """PRD §3.9: "The attempt whose post-increment attempt_count reaches exactly 3
        moves the task from ATTEMPTED to ESCALATED and journals a FOLLOWUP_ESCALATED
        audit event — three consecutive missed contacts escalate the task."

        Design: Difficulty/non_linear_state_machine/followup_task_cyclic_record_attempt_then_escalate
        """
        ctx = fx.setup_discharged(discharge_clock="2026-03-10T08:00:00Z")
        task = fx.get_followup_task(ctx["newborn_id"], "WEIGHT_CHECK")
        assert task is not None and task["status"] == "OPEN"

        get_success_data(api.record_attempt(task["id"], fx.NURSE,
                         f.record_attempt_payload("2026-03-11T09:00:00Z")))
        get_success_data(api.record_attempt(task["id"], fx.NURSE,
                         f.record_attempt_payload("2026-03-12T09:00:00Z")))
        data = validate_success(api.record_attempt(task["id"], fx.NURSE,
                                f.record_attempt_payload("2026-03-13T09:00:00Z")))
        assert data["attempt_count"] == 3, (
            f"three recorded attempts should leave attempt_count 3, got {data['attempt_count']}")
        assert data["status"] == "ESCALATED", (
            f"the 3rd attempt should escalate the task, got {data['status']}")

    def test_first_attempt_moves_open_to_attempted(self, api):
        """PRD §3.9: "The first recorded attempt moves an OPEN task to ATTEMPTED."

        Design: Difficulty/non_linear_state_machine/followup_task_cyclic_record_attempt_then_escalate
        """
        ctx = fx.setup_discharged(discharge_clock="2026-03-10T08:00:00Z")
        task = fx.get_followup_task(ctx["newborn_id"], "WEIGHT_CHECK")
        assert task is not None and task["status"] == "OPEN"

        data = validate_success(api.record_attempt(task["id"], fx.NURSE,
                                f.record_attempt_payload("2026-03-11T09:00:00Z")))
        assert data["status"] == "ATTEMPTED", (
            f"first attempt moves OPEN to ATTEMPTED, got {data['status']}")
        assert data["attempt_count"] == 1, (
            f"attempt_count should be 1 after the first attempt, got {data['attempt_count']}")


# =========================================================================
# Difficulty/non_linear_state_machine/government_filing_rejected_resubmit_revision_loop
# =========================================================================
class TestFilingRevisionLoop:
    def test_rejected_filing_resubmits_to_submitted(self, api):
        """PRD §3.7: "A REJECTED filing may be resubmitted: submitting again moves it
        from REJECTED back to SUBMITTED (this revision loop again requires a non-null
        legal_name), re-stamps submitted_at, and increments the version, making the
        filing lifecycle cyclic."

        Design: Difficulty/non_linear_state_machine/government_filing_rejected_resubmit_revision_loop
        """
        fx.set_clock("2026-03-06T08:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(
            legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
        filing = fx.create_birth_cert(newborn["id"])
        get_success_data(api.submit_filing(filing["id"], fx.VITAL))
        rejected = get_success_data(api.acknowledge_filing(
            filing["id"], f.acknowledge_filing_payload("REJECTED"), fx.VITAL))
        assert rejected["status"] == "REJECTED"

        data = validate_success(api.submit_filing(filing["id"], fx.VITAL))
        assert data["status"] == "SUBMITTED", (
            f"resubmit of a REJECTED filing must return to SUBMITTED, got {data['status']}")

    def test_acknowledge_rejected_then_accepted_after_resubmit(self, api):
        """PRD §3.7: "Acknowledging a filing as accepted requires a reference_number in
        the request; it stores that reference and stamps acknowledged_at with the
        current clock, moving a SUBMITTED filing or a LATE_FLAGGED filing to ACCEPTED."

        Design: Difficulty/non_linear_state_machine/government_filing_rejected_resubmit_revision_loop
        """
        fx.set_clock("2026-03-06T08:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(
            legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
        filing = fx.create_birth_cert(newborn["id"])
        get_success_data(api.submit_filing(filing["id"], fx.VITAL))
        get_success_data(api.acknowledge_filing(
            filing["id"], f.acknowledge_filing_payload("REJECTED"), fx.VITAL))
        get_success_data(api.submit_filing(filing["id"], fx.VITAL))  # back to SUBMITTED

        data = validate_success(api.acknowledge_filing(
            filing["id"], f.acknowledge_filing_payload("ACCEPTED", reference_number="BC-12345"),
            fx.VITAL))
        assert data["status"] == "ACCEPTED", (
            f"a resubmitted filing should accept to ACCEPTED, got {data['status']}")


# =========================================================================
# Difficulty/transitive_cascade/discharge_spawns_followup_tasks_depth2
# =========================================================================
class TestDischargeSpawnsFollowups:
    def test_discharge_spawns_exactly_four_followup_tasks(self, api):
        """PRD §3.8: "spawns four follow-up tasks for the nurse: one each of type
        WEIGHT_CHECK, JAUNDICE_CHECK, FEEDING_CHECK, and SAFETY_CALL, each created in
        OPEN with a computed deadline."

        Design: Difficulty/transitive_cascade/discharge_spawns_followup_tasks_depth2
        """
        ctx = fx.setup_discharge_ready()
        fx.set_clock("2026-03-10T08:00:00Z")
        get_success_data(api.discharge(ctx["newborn_id"], fx.NURSE))

        resp = api.list_follow_up_tasks(fx.NURSE, params={"newborn_id": ctx["newborn_id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 4, (
            f"discharge must spawn exactly four follow-up tasks, got {meta['total_count']}")

    def test_weight_check_due_at_is_discharge_plus_48_hours(self, api):
        """PRD §3.9: "a WEIGHT_CHECK is due 48 hours after discharge"

        Design: Difficulty/transitive_cascade/discharge_spawns_followup_tasks_depth2
        """
        ctx = fx.setup_discharge_ready()
        fx.set_clock("2026-03-10T08:00:00Z")
        get_success_data(api.discharge(ctx["newborn_id"], fx.NURSE))

        resp = api.list_follow_up_tasks(
            fx.NURSE, params={"newborn_id": ctx["newborn_id"], "task_type": "WEIGHT_CHECK"})
        data, _ = validate_paginated(resp)
        assert len(data) == 1, "exactly one WEIGHT_CHECK task should exist"
        # discharged_at 2026-03-10T08:00:00Z + 48h = 2026-03-12T08:00:00.000Z.
        assert data[0]["due_at"] == "2026-03-12T08:00:00.000Z", (
            f"WEIGHT_CHECK due_at should be discharge + 48h, got {data[0]['due_at']}")


# =========================================================================
# Difficulty/priority_pair_validation_conflict/discharge_state_beats_discharge_prerequisite
# =========================================================================
def test_discharge_state_check_beats_prerequisite(api):
    """PRD §3.11: "Only then is the state check applied: an action whose transition is
    not defined from the target resource's current state yields ERR_INVALID_STATE."
    PRD §3.11: "the consult buffer, the admit window, and the already-issued bag — are
    evaluated after these foundational checks."

    Design: Difficulty/priority_pair_validation_conflict/discharge_state_beats_discharge_prerequisite
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    # ROOMING_IN (not DISCHARGE_READY) with NO issued bag and NO birth cert: both the
    # state check and the discharge prerequisite would fail; state must win.
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=3200, gestational_age_weeks=39, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    get_success_data(api.room_in(newborn["id"], fx.NURSE))

    resp = api.discharge(newborn["id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# A second test for this difficulty instance: the same precedence holds when the
# newborn is still BORN (also not DISCHARGE_READY) and lacks prerequisites.
def test_discharge_from_born_returns_invalid_state_not_prerequisite(api):
    """PRD §3.11: "Only then is the state check applied: an action whose transition is
    not defined from the target resource's current state yields ERR_INVALID_STATE."

    Design: Difficulty/priority_pair_validation_conflict/discharge_state_beats_discharge_prerequisite
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=3200, gestational_age_weeks=39, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    # Still BORN: no discharge transition is defined from BORN, and no bag/filing exist.

    resp = api.discharge(newborn["id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# Difficulty/cross_entity_state_dependency/discharge_requires_issued_bag_newborn_depends_on_dischargebag
# =========================================================================
def test_discharge_blocked_when_only_bag_is_recalled(api):
    """PRD §3.8: "Discharge is gated on two sibling prerequisites: exactly one discharge
    bag for the infant must be in ISSUED, and a BIRTH_CERTIFICATE filing for the infant
    must be in SUBMITTED or ACCEPTED. If either prerequisite is unmet, the discharge is
    rejected with ERR_DISCHARGE_PREREQUISITE."

    Design: Difficulty/cross_entity_state_dependency/discharge_requires_issued_bag_newborn_depends_on_dischargebag
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    # Reach DISCHARGE_READY with a SUBMITTED birth cert and an ISSUED bag, then recall
    # the bag so no ISSUED bag remains.
    ctx = fx.setup_discharge_ready(weight_grams=2500, gestational_age_weeks=37, apgar_5min=9)
    get_success_data(api.recall_discharge_bag(ctx["bag_id"], fx.NURSE))

    resp = api.discharge(ctx["newborn_id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_DISCHARGE_PREREQUISITE.value)


# =========================================================================
# Difficulty/cross_entity_state_dependency/ssn_submit_requires_birthcert_filing_to_filing_dependency
# =========================================================================
def test_ssn_submit_blocked_while_birthcert_pending(api):
    """PRD §3.7: "for an SSN_APPLICATION only, the same infant's BIRTH_CERTIFICATE
    filing must already be in SUBMITTED, LATE_FLAGGED, or ACCEPTED; submitting an SSN
    application before its companion birth certificate has at least been submitted is
    rejected with ERR_BIRTH_CERT_PREREQUISITE."

    Design: Difficulty/cross_entity_state_dependency/ssn_submit_requires_birthcert_filing_to_filing_dependency
    """
    fx.set_clock("2026-03-06T08:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
    fx.create_birth_cert(newborn["id"])           # left PENDING
    ssn = fx.create_ssn_filing(newborn["id"])     # PENDING

    resp = api.submit_filing(ssn["id"], fx.VITAL)
    validate_error(resp, ApiErrorId.ERR_BIRTH_CERT_PREREQUISITE.value)


def test_ssn_submit_allowed_once_birthcert_submitted(api):
    """PRD §3.7: "for an SSN_APPLICATION only, the same infant's BIRTH_CERTIFICATE
    filing must already be in SUBMITTED, LATE_FLAGGED, or ACCEPTED; submitting an SSN
    application before its companion birth certificate has at least been submitted is
    rejected with ERR_BIRTH_CERT_PREREQUISITE."

    Design: Difficulty/cross_entity_state_dependency/ssn_submit_requires_birthcert_filing_to_filing_dependency
    """
    fx.set_clock("2026-03-06T08:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
    bc = fx.create_birth_cert(newborn["id"])
    get_success_data(api.submit_filing(bc["id"], fx.VITAL))  # birth cert now SUBMITTED
    ssn = fx.create_ssn_filing(newborn["id"])

    # With the companion birth certificate SUBMITTED, the SSN prerequisite is satisfied.
    data = validate_success(api.submit_filing(ssn["id"], fx.VITAL))
    assert data["status"] == "SUBMITTED", (
        f"SSN submit should succeed once the birth cert is SUBMITTED, got {data['status']}")


# =========================================================================
# Difficulty/cross_entity_state_dependency/discharge_requires_issued_bag_newborn_depends_on_dischargebag
#   (second test: the positive direction — discharge succeeds with the sibling bag ISSUED)
# =========================================================================
def test_discharge_succeeds_with_issued_bag_and_submitted_birthcert(api):
    """PRD §3.8: "Discharge is gated on two sibling prerequisites: exactly one discharge
    bag for the infant must be in ISSUED, and a BIRTH_CERTIFICATE filing for the infant
    must be in SUBMITTED or ACCEPTED."
    PRD §3.8: "A successful discharge sets care_location to RELEASED, stamps
    discharged_at with the current clock"

    Design: Difficulty/cross_entity_state_dependency/discharge_requires_issued_bag_newborn_depends_on_dischargebag
    """
    ctx = fx.setup_discharge_ready(weight_grams=2500, gestational_age_weeks=37, apgar_5min=9)
    fx.set_clock("2026-03-10T08:00:00Z")

    # With one ISSUED bag and a SUBMITTED birth cert (built by the fixture), discharge succeeds.
    data = validate_success(api.discharge(ctx["newborn_id"], fx.NURSE))
    assert data["clinical_status"] == "DISCHARGED", (
        f"discharge with both sibling prerequisites met should release the infant, "
        f"got {data['clinical_status']}")
    assert data["care_location"] == "RELEASED", (
        f"a successful discharge sets care_location RELEASED, got {data['care_location']}")


# =========================================================================
# Difficulty/resource_temporal_overlap/lactation_consult_closed_buffer_conflict_rejected
# =========================================================================
class TestConsultBuffer:
    def test_consult_within_240_minutes_rejected(self, api):
        """PRD §3.5: "scheduling a consult is rejected with ERR_CONSULT_BUFFER_CONFLICT
        when its consult_datetime falls within 240 minutes of an existing consult for
        the same infant whose status is SCHEDULED, COMPLETED, or FEEDING_AT_RISK."

        Design: Difficulty/resource_temporal_overlap/lactation_consult_closed_buffer_conflict_rejected
        """
        fx.set_clock("2026-03-05T08:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(
            birth_datetime="2026-03-05T07:00:00Z")
        get_success_data(api.create_lactation_consult(
            f.create_lactation_consult_payload(newborn["id"], "2026-03-05T11:00:00Z"), fx.NURSE))

        # Second consult at 13:00Z is 120 minutes from the existing 11:00Z SCHEDULED one (<= 240).
        resp = api.create_lactation_consult(
            f.create_lactation_consult_payload(newborn["id"], "2026-03-05T13:00:00Z"), fx.NURSE)
        validate_error(resp, ApiErrorId.ERR_CONSULT_BUFFER_CONFLICT.value)

    def test_consult_exactly_240_minutes_apart_rejected_inclusive(self, api):
        """PRD §3.5: "The buffer is closed on both sides — the conflict triggers when
        the absolute gap between the new consult time and an existing consult time is
        240 minutes or less, both endpoints inclusive — and consults already in
        CANCELLED are ignored for this test."

        Design: Difficulty/resource_temporal_overlap/lactation_consult_closed_buffer_conflict_rejected
        """
        fx.set_clock("2026-03-05T08:00:00Z")
        newborn, _, _ = fx.setup_admitted_with_newborn(
            birth_datetime="2026-03-05T07:00:00Z")
        get_success_data(api.create_lactation_consult(
            f.create_lactation_consult_payload(newborn["id"], "2026-03-05T11:00:00Z"), fx.NURSE))

        # A consult exactly 240 minutes (4h) later at 15:00Z is at the inclusive boundary.
        resp = api.create_lactation_consult(
            f.create_lactation_consult_payload(newborn["id"], "2026-03-05T15:00:00Z"), fx.NURSE)
        validate_error(resp, ApiErrorId.ERR_CONSULT_BUFFER_CONFLICT.value)


# =========================================================================
# Corner/state_machines/room_in_from_discharged_invalid_state
# =========================================================================
def test_room_in_on_discharged_newborn_invalid_state(api):
    """PRD §3.8: "DISCHARGED is the newborn's terminal clinical state"
    PRD §3.3: "Rooming in requires that the infant currently be in BORN."

    Design: Corner/state_machines/room_in_from_discharged_invalid_state
    """
    ctx = fx.setup_discharged(discharge_clock="2026-03-10T08:00:00Z")

    resp = api.room_in(ctx["newborn_id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# Corner/state_machines/discharged_newborn_terminal_lockdown
# =========================================================================
def test_second_discharge_on_discharged_newborn_invalid_state(api):
    """PRD §3.8: "Discharging the infant is the final clinical transition, moving it
    from DISCHARGE_READY to DISCHARGED."
    PRD §3.8: "DISCHARGED is the newborn's terminal clinical state"

    Design: Corner/state_machines/discharged_newborn_terminal_lockdown
    """
    ctx = fx.setup_discharged(discharge_clock="2026-03-10T08:00:00Z")

    resp = api.discharge(ctx["newborn_id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# Corner/state_machines/lactation_consult_complete_latch_below_7_branches_feeding_at_risk
# =========================================================================
def test_complete_consult_latch_below_7_is_feeding_at_risk(api):
    """PRD §3.5: "When the recorded latch_score is below 7, the consult moves instead
    from SCHEDULED to FEEDING_AT_RISK, the score is stored, and feeding_adequate stays
    false"

    Design: Corner/state_machines/lactation_consult_complete_latch_below_7_branches_feeding_at_risk
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
    consult = get_success_data(api.create_lactation_consult(
        f.create_lactation_consult_payload(newborn["id"], "2026-03-05T11:00:00Z"), fx.NURSE))

    data = validate_success(api.complete_lactation_consult(
        consult["id"], f.complete_consult_payload(5), fx.NURSE))
    assert data["status"] == "FEEDING_AT_RISK", (
        f"latch < 7 should branch to FEEDING_AT_RISK, got {data['status']}")
    assert data["feeding_adequate"] is False, (
        "feeding_adequate must stay false when latch < 7")


# =========================================================================
# Corner/validations/issue_medication_bag_without_signoff_rejected
# =========================================================================
def test_issue_medication_bag_without_signoff_rejected(api):
    """PRD §3.6: "When a bag carries the pharmacy flag — that is, when
    requires_pharmacy_signoff is true because a medication line is present — the issue
    request must carry pharmacy_signoff equal to true; issuing such a bag without that
    sign-off is rejected with ERR_PHARMACY_SIGNOFF_REQUIRED."

    Design: Corner/validations/issue_medication_bag_without_signoff_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
    bag = get_success_data(api.create_discharge_bag(
        f.create_discharge_bag_payload(newborn["id"], line_items=[
            {"sku": "MED-A", "category": "MEDICATION", "qty": 1, "unit_value_cents": 1499}]),
        fx.NURSE))
    get_success_data(api.assemble_discharge_bag(bag["id"], fx.NURSE))

    resp = api.issue_discharge_bag(bag["id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_PHARMACY_SIGNOFF_REQUIRED.value)


# =========================================================================
# Corner/validations/government_filing_submit_without_legal_name_rejected
# =========================================================================
def test_filing_submit_without_legal_name_rejected(api):
    """PRD §3.7: "First, the infant's legal_name must be non-null; submitting while the
    name is still null is rejected with ERR_LEGAL_NAME_REQUIRED."

    Design: Corner/validations/government_filing_submit_without_legal_name_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    # No legal_name supplied at birth -> legal_name is null.
    newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
    filing = fx.create_birth_cert(newborn["id"])

    resp = api.submit_filing(filing["id"], fx.VITAL)
    validate_error(resp, ApiErrorId.ERR_LEGAL_NAME_REQUIRED.value)


# =========================================================================
# Corner/validations/mark_discharge_ready_below_threshold_rejected
# =========================================================================
def test_mark_discharge_ready_below_threshold_rejected(api):
    """PRD §3.8: "the score is recomputed at the moment of the call and must be at
    least 70; a recomputed score below 70 is rejected with
    ERR_READINESS_BELOW_THRESHOLD."

    Design: Corner/validations/mark_discharge_ready_below_threshold_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    # weight 1850 -> 10, no feeding -> 0, no open NICU -> 20, birth cert SUBMITTED -> 10 = 40 < 70.
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=1850, gestational_age_weeks=37, apgar_5min=9,
        legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
    get_success_data(api.room_in(newborn["id"], fx.NURSE))
    bc = fx.create_birth_cert(newborn["id"])
    get_success_data(api.submit_filing(bc["id"], fx.VITAL))

    resp = api.mark_discharge_ready(newborn["id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_READINESS_BELOW_THRESHOLD.value)


# =========================================================================
# Corner/validations/cancel_submitted_filing_invalid_state
# =========================================================================
def test_cancel_submitted_filing_invalid_state(api):
    """PRD §3.7: "A filing may be cancelled only while it is still PENDING, moving it
    from PENDING to CANCELLED and incrementing the version; once a filing has been
    submitted, late-flagged, accepted, or rejected it follows the acknowledge and
    resubmit paths instead."

    Design: Corner/validations/cancel_submitted_filing_invalid_state
    """
    fx.set_clock("2026-03-06T08:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
    filing = fx.create_birth_cert(newborn["id"])
    get_success_data(api.submit_filing(filing["id"], fx.VITAL))

    resp = api.cancel_filing(filing["id"], fx.VITAL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================
# Corner/errors/second_issued_bag_rejected_bag_already_issued
# =========================================================================
def test_second_issued_bag_rejected(api):
    """PRD §3.6: "attempting to issue a bag for an infant that already has another
    ISSUED bag is rejected with ERR_BAG_ALREADY_ISSUED."

    Design: Corner/errors/second_issued_bag_rejected_bag_already_issued
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
    bag1 = get_success_data(api.create_discharge_bag(
        f.create_discharge_bag_payload(newborn["id"], line_items=[
            {"sku": "FORM-A", "category": "FORMULA", "qty": 1, "unit_value_cents": 1299}]),
        fx.NURSE))
    get_success_data(api.assemble_discharge_bag(bag1["id"], fx.NURSE))
    get_success_data(api.issue_discharge_bag(bag1["id"], fx.NURSE))
    bag2 = get_success_data(api.create_discharge_bag(
        f.create_discharge_bag_payload(newborn["id"], line_items=[
            {"sku": "DIA-A", "category": "DIAPERS", "qty": 1, "unit_value_cents": 333}]),
        fx.NURSE))
    get_success_data(api.assemble_discharge_bag(bag2["id"], fx.NURSE))

    resp = api.issue_discharge_bag(bag2["id"], fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_BAG_ALREADY_ISSUED.value)


# =========================================================================
# Corner/endpoints/filtered_list_government_filings_by_newborn
# =========================================================================
def test_list_government_filings_filtered_by_newborn(api):
    """PRD §4: "List government filings; filter by newborn_id, filing_type, or status"

    Design: Corner/endpoints/filtered_list_government_filings_by_newborn
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        legal_name="Baby Doe", birth_datetime="2026-03-05T10:00:00Z")
    fx.create_birth_cert(newborn["id"])

    resp = api.list_government_filings(fx.VITAL, params={"newborn_id": newborn["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, (
        f"only the single filing for this newborn should be listed, got {meta['total_count']}")
    assert all(item["newborn_id"] == newborn["id"] for item in data), (
        "every returned filing must belong to the filtered newborn")


# =========================================================================
# Corner/endpoints/patch_newborn_legal_name_updates_field
# =========================================================================
def test_patch_newborn_legal_name_updates_field_and_bumps_version(api):
    """PRD §3.7: "The nurse or vital-records officer may set legal_name on the newborn
    at any time before filing."
    PRD §2.4: "The version field is an integer that begins at its initial value and
    increments by one on every mutation of the resource"

    Design: Corner/endpoints/patch_newborn_legal_name_updates_field
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    newborn, _, _ = fx.setup_admitted_with_newborn(birth_datetime="2026-03-05T10:00:00Z")
    assert newborn["version"] == 1

    data = validate_success(api.patch_newborn(
        newborn["id"], {"legal_name": "Robin Doe"}, fx.VITAL))
    assert data["legal_name"] == "Robin Doe", (
        f"legal_name should update to 'Robin Doe', got {data['legal_name']}")
    assert data["version"] == 2, (
        f"a PATCH mutation should bump version to 2, got {data['version']}")
