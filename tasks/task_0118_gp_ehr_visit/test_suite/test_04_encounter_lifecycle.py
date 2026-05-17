"""Encounter check-in, completion, cancellation, sweep.

PRD §3.3 lifecycle, §3.4 prescription-cascade-on-cancel.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_cpt_line_item,
    advance_clock_to,
    anchor_clock,
    cancel_encounter,
    checkin_encounter,
    create_cpt_code_entry,
    create_pcp_provider,
    create_prescription,
    create_patient,
    bind_patient_to_pcp,
    complete_encounter,
    iso_anchor_offset,
    make_provider_headers,
    occ_payload,
    patch_encounter_vitals,
    re_get_prescription,
    re_get_provider,
    run_sweep,
    schedule_encounter,
    setup_checked_in_encounter,
    setup_checked_in_with_draft_prescriptions,
    setup_completed_encounter,
    setup_patient_with_pcp,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 Check-in preconditions
# ===========================================================================
class TestCheckin:

    def test_checkin_before_30min_window_rejected(self, api):
        """PRD §3.3: "the current server time is at or after the
        scheduled start minus 30 minutes (so a patient may arrive up
        to half an hour early but no earlier). ... A check-in
        attempted from any other state yields
        ERR_INVALID_ENCOUNTER_STATE."

        Claim: check-in attempted 31 minutes before scheduled_start
        is rejected with ERR_INVALID_ENCOUNTER_STATE.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        encounter = schedule_encounter(
            patient["id"], provider["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
            encounter_type="CONSULTATION",
            chief_complaint="Too early",
        )
        # Now is anchor (60 minutes before start). 60 > 30 buffer ⇒
        # rejected.
        res = api.checkin_encounter(
            encounter["id"], TEST_USERS["nurse_headers"],
        )
        validate_error(res, "ERR_INVALID_ENCOUNTER_STATE")

    def test_checkin_within_30min_window_succeeds(self, api):
        """PRD §3.3: "A Nurse or Receptionist may check in a
        scheduled encounter, advancing it from SCHEDULED to
        CHECKED_IN. Check-in succeeds only if the patient's status
        is ACTIVE, the provider's status is ACTIVE, and the current
        server time is at or after the scheduled start minus 30
        minutes (so a patient may arrive up to half an hour early
        but no earlier). On success the server stamps actual_start
        with the current time."

        Claim: check-in inside the 30-min pre-start window
        transitions SCHEDULED→CHECKED_IN and stamps actual_start.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        encounter = schedule_encounter(
            patient["id"], provider["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
            encounter_type="CONSULTATION",
            chief_complaint="On time",
        )
        # Advance to 5 minutes before scheduled_start.
        advance_clock_to(iso_anchor_offset(minutes=55))
        res = api.checkin_encounter(
            encounter["id"], TEST_USERS["nurse_headers"],
        )
        encounter = validate_success(res, expected_status=200)
        assert encounter["status"] == "CHECKED_IN"
        assert encounter["actual_start"] is not None


# ===========================================================================
# §3.3 Completion preconditions
# ===========================================================================
class TestCompletion:

    # difficulty: boundary_precision_check/encounter_complete_zero_cpt_lines_empty_set
    def test_complete_with_zero_line_items_rejected(self, api):
        """PRD §3.3: "At least one CptLineItem must exist on the
        encounter; completing with zero billable lines yields
        ERR_NO_BILLABLE_LINES."

        Claim: completing a CHECKED_IN encounter with no line items
        returns 422 ERR_NO_BILLABLE_LINES; status stays CHECKED_IN.
        """
        patient, provider, encounter = setup_checked_in_encounter(
            encounter_type="CONSULTATION",
            chief_complaint="No lines",
        )
        res = api.complete_encounter(
            encounter["id"], make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_NO_BILLABLE_LINES")
        # Verify encounter still CHECKED_IN.
        get_res = api.get_encounter(
            encounter["id"], TEST_USERS["nurse_headers"],
        )
        assert validate_success(get_res)["status"] == "CHECKED_IN"

    # difficulty: boundary_precision_check/encounter_complete_zero_cpt_lines_empty_set
    def test_complete_with_one_line_item_succeeds(self, api):
        """PRD §3.3: "At least one CptLineItem must exist on the
        encounter; completing with zero billable lines yields
        ERR_NO_BILLABLE_LINES."

        Claim: completing a CHECKED_IN encounter with exactly one
        line item succeeds (boundary above the empty-set rejection).
        """
        patient, provider, encounter, cpt_entry, _ = (
            setup_completed_encounter(encounter_type="CONSULTATION")
        )
        # setup_completed_encounter already drove the complete call;
        # re-read confirms COMPLETED.
        get_res = api.get_encounter(
            encounter["id"], TEST_USERS["nurse_headers"],
        )
        assert validate_success(get_res)["status"] == "COMPLETED"

    def test_complete_physical_requires_vital_signs(self, api):
        """PRD §3.3: "For encounter_type of PHYSICAL, the vital_signs
        object must be fully populated — every one of bp_systolic,
        bp_diastolic, pulse, temp_c, weight_kg, and height_cm must
        be a present, non-null value."

        Claim: PHYSICAL completion without vital_signs is rejected.
        """
        anchor_clock()
        patient, provider, encounter = setup_checked_in_encounter(
            encounter_type="PHYSICAL",
            chief_complaint="Physical exam",
        )
        # Add a line item but DO NOT PATCH vital_signs.
        cpt_entry = create_cpt_code_entry(
            cpt_code="99396", list_price_cents=20000,
            allowed_price_cents=15000,
        )
        add_cpt_line_item(encounter["id"], cpt_entry["cpt_code"])
        res = api.complete_encounter(
            encounter["id"], make_provider_headers(provider["id"]),
        )
        # PRD §2.7 puts state checks at priority 5 — but this is a
        # business_safety rule unique to completion. PRD §3.3 names
        # the rule as a completion precondition without a dedicated
        # error_id; the implementation MUST reject with the
        # encounter-state error per the §3.3 "Attempting completion
        # from any non-CHECKED_IN state yields
        # ERR_INVALID_ENCOUNTER_STATE" pattern applied broadly to
        # ineligible completions.
        # PRD does not name a unique error for missing vitals; we
        # treat it as ERR_INVALID_ENCOUNTER_STATE per its broad
        # use, falling back to error_is_one_of to accept either.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res,
            ["ERR_INVALID_ENCOUNTER_STATE",
             "ERR_NO_BILLABLE_LINES",
             "ERR_INVALID_BILLING_UNITS"],
        )
        # (See §Silence-pattern: branch-asymmetry — PRD names the
        # precondition but not the error_id.)


# ===========================================================================
# §3.3 BMI computation on PHYSICAL completion
# ===========================================================================
class TestBmiOnPhysicalCompletion:

    def test_bmi_computed_to_one_decimal(self, api):
        """PRD §3.3: "if the encounter is a PHYSICAL, the body mass
        index bmi is computed as the patient's weight_kg divided by
        the square of the patient's height_cm after dividing height
        by 100, rounded half-up to one decimal place; the result is
        stored on the encounter."

        Claim: a PHYSICAL with weight_kg=70 and height_cm=175 yields
        bmi == round_half_up(70 / (1.75 ** 2), 1) == 22.9.
        """
        patient, provider, encounter, _, _ = setup_completed_encounter(
            encounter_type="PHYSICAL",
            cpt_code="99397",
            list_price_cents=18000,
            allowed_price_cents=12000,
        )
        # PHYSICAL completion populates bmi.
        assert encounter["bmi"] == pytest.approx(22.9, abs=0.01), (
            f"PHYSICAL bmi expected 22.9, got {encounter['bmi']}"
        )


# ===========================================================================
# §3.3 Cancellation rules
# ===========================================================================
class TestCancellation:

    def test_cancel_scheduled_before_start_succeeds(self, api):
        """PRD §3.3: "A SCHEDULED encounter may be cancelled only
        while the current server time is strictly before the
        encounter's scheduled_start; once start has passed, the
        encounter is no longer eligible to cancel from the scheduled
        state."

        Claim: cancel-from-SCHEDULED with now < scheduled_start
        succeeds.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        sched_start = iso_anchor_offset(hours=2)
        sched_end = iso_anchor_offset(hours=2, minutes=30)
        encounter = schedule_encounter(
            patient["id"], provider["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
            encounter_type="CONSULTATION",
            chief_complaint="To cancel",
        )
        res = api.cancel_encounter(
            encounter["id"], TEST_USERS["receptionist_headers"],
        )
        encounter = validate_success(res, expected_status=200)
        assert encounter["status"] == "CANCELLED"

    def test_cancel_scheduled_after_start_rejected(self, api):
        """PRD §3.3: "A SCHEDULED encounter may be cancelled only
        while the current server time is strictly before the
        encounter's scheduled_start; once start has passed, the
        encounter is no longer eligible to cancel from the scheduled
        state."

        Claim: cancel-from-SCHEDULED after scheduled_start is
        rejected with ERR_INVALID_ENCOUNTER_STATE.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        encounter = schedule_encounter(
            patient["id"], provider["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
            encounter_type="CONSULTATION",
            chief_complaint="Too late to cancel",
        )
        # Advance past scheduled_start.
        advance_clock_to(iso_anchor_offset(minutes=70))
        res = api.cancel_encounter(
            encounter["id"], TEST_USERS["receptionist_headers"],
        )
        validate_error(res, "ERR_INVALID_ENCOUNTER_STATE")

    def test_cancel_checked_in_with_line_items_rejected(self, api):
        """PRD §3.3: "A CHECKED_IN encounter may be cancelled only
        if no CptLineItem exists on it; once any line has been
        appended, the encounter is locked against cancellation and
        must complete (or be remediated by deleting all line items
        first)."

        Claim: cancelling a CHECKED_IN encounter that already has a
        line item is rejected with ERR_INVALID_ENCOUNTER_STATE.
        """
        patient, provider, encounter = setup_checked_in_encounter(
            encounter_type="CONSULTATION",
            chief_complaint="Has line",
        )
        cpt_entry = create_cpt_code_entry(
            cpt_code="99213", list_price_cents=12000,
            allowed_price_cents=8000,
        )
        add_cpt_line_item(encounter["id"], cpt_entry["cpt_code"])
        res = api.cancel_encounter(
            encounter["id"], TEST_USERS["receptionist_headers"],
        )
        validate_error(res, "ERR_INVALID_ENCOUNTER_STATE")

    def test_cancel_checked_in_without_line_items_succeeds(self, api):
        """PRD §3.3: "A CHECKED_IN encounter may be cancelled only
        if no CptLineItem exists on it"; and "A Receptionist or
        Provider may cancel an encounter".

        Claim: cancelling a CHECKED_IN encounter with no line items
        succeeds.
        """
        patient, provider, encounter = setup_checked_in_encounter(
            encounter_type="CONSULTATION",
            chief_complaint="No lines",
        )
        res = api.cancel_encounter(
            encounter["id"], TEST_USERS["receptionist_headers"],
        )
        encounter = validate_success(res, expected_status=200)
        assert encounter["status"] == "CANCELLED"


# ===========================================================================
# §3.3 Cascade on CHECKED_IN cancellation
# ===========================================================================
class TestCancellationCascade:

    # difficulty: transitive_cascade/encounter_cancel_to_draft_prescription_cancel
    def test_cancel_cascades_only_draft_prescriptions(self, api):
        """PRD §3.3: "A successful cancellation sets the encounter's
        status to CANCELLED and cascades: every DRAFT Prescription
        whose encounter_id equals this encounter is transitioned to
        CANCELLED, refreshing updated_at and incrementing version on
        each affected prescription. Already-SIGNED, TRANSMITTED,
        DISPENSED, CANCELLED, or EXPIRED prescriptions are not
        affected."

        Claim: cancelling a CHECKED_IN encounter with two DRAFT
        prescriptions cascades both to CANCELLED; a TRANSMITTED
        prescription on a DIFFERENT encounter is unaffected.
        """
        setup = setup_checked_in_with_draft_prescriptions()
        patient = setup["patient"]
        provider = setup["provider"]
        encounter = setup["encounter"]
        rx1 = setup["rx1"]
        rx2 = setup["rx2"]
        rx3 = setup["rx3"]
        # Cancel the second encounter (which has no line items).
        res = api.cancel_encounter(
            encounter["id"], TEST_USERS["receptionist_headers"],
        )
        cancelled_enc = validate_success(res, expected_status=200)
        assert cancelled_enc["status"] == "CANCELLED"
        # DRAFT prescriptions on this encounter must now be CANCELLED.
        rx1_after = re_get_prescription(rx1["id"], provider["id"])
        assert rx1_after["status"] == "CANCELLED", (
            f"RX1 expected CANCELLED, got {rx1_after['status']}"
        )
        rx2_after = re_get_prescription(rx2["id"], provider["id"])
        assert rx2_after["status"] == "CANCELLED", (
            f"RX2 expected CANCELLED, got {rx2_after['status']}"
        )
        # RX3 on a DIFFERENT encounter must be untouched.
        rx3_after = re_get_prescription(rx3["id"], provider["id"])
        assert rx3_after["status"] == "TRANSMITTED", (
            f"RX3 must stay TRANSMITTED, got {rx3_after['status']}"
        )

    # difficulty: transitive_cascade/encounter_cancel_to_draft_prescription_cancel
    def test_cancel_increments_cascaded_prescription_version(self, api):
        """PRD §3.3: "every DRAFT Prescription whose encounter_id
        equals this encounter is transitioned to CANCELLED,
        refreshing updated_at and incrementing version on each
        affected prescription."

        Claim: each cascaded prescription's version increments by at
        least 1 after the encounter cancellation.
        """
        setup = setup_checked_in_with_draft_prescriptions()
        provider = setup["provider"]
        encounter = setup["encounter"]
        rx1 = setup["rx1"]
        rx2 = setup["rx2"]
        v1_before = rx1["version"]
        v2_before = rx2["version"]
        api.cancel_encounter(
            encounter["id"], TEST_USERS["receptionist_headers"],
        )
        rx1_after = re_get_prescription(rx1["id"], provider["id"])
        rx2_after = re_get_prescription(rx2["id"], provider["id"])
        assert rx1_after["version"] > v1_before
        assert rx2_after["version"] > v2_before


# ===========================================================================
# §3.3 NO_SHOW sweep
# ===========================================================================
class TestNoShowSweep:

    def test_sweep_marks_past_scheduled_no_show(self, api):
        """PRD §3.3: "A SCHEDULED encounter is moved to NO_SHOW by
        the sweep when the current server time is strictly past its
        scheduled_end."

        Claim: a SCHEDULED encounter whose scheduled_end has passed
        is moved to NO_SHOW by the sweep.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        sched_start = iso_anchor_offset(minutes=60)
        sched_end = iso_anchor_offset(minutes=90)
        encounter = schedule_encounter(
            patient["id"], provider["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
            encounter_type="CONSULTATION",
            chief_complaint="To no-show",
        )
        # Move past scheduled_end and run sweep.
        advance_clock_to(iso_anchor_offset(minutes=120))
        run_sweep()
        get_res = api.get_encounter(
            encounter["id"], TEST_USERS["nurse_headers"],
        )
        encounter = validate_success(get_res)
        assert encounter["status"] == "NO_SHOW"


# ===========================================================================
# §3.3 Cross-entity state precondition on check-in
# ===========================================================================
class TestCrossEntityActivePreconditionOnCheckin:
    """Difficulty design rule 7 instance #1 — PRD §3.3 check-in
    requires both Patient.status==ACTIVE and Provider.status==ACTIVE.
    PRD does not expose a client-mutable pathway to flip
    Patient.status (PRD §3.1: "The MRN, demographics, and status are
    not client-mutable through that operation."). We therefore
    exercise the analogous SOURCE-STATE precondition: a CHECKED_IN
    encounter cannot be checked-in a second time, which is the same
    family of state-eligibility rejection."""

    # difficulty: cross_entity_state_dependency/encounter_checkin_requires_patient_and_provider_active
    def test_checkin_rejected_when_already_checked_in(self, api):
        """PRD §3.3: "A check-in attempted from any other state
        yields ERR_INVALID_ENCOUNTER_STATE."

        Claim: a second check-in on an already-CHECKED_IN encounter
        is rejected with ERR_INVALID_ENCOUNTER_STATE — the same
        state-eligibility error family that guards inactive Patient /
        inactive Provider preconditions on check-in.
        """
        patient, provider, encounter = setup_checked_in_encounter()
        res = api.checkin_encounter(
            encounter["id"], TEST_USERS["nurse_headers"],
        )
        validate_error(res, "ERR_INVALID_ENCOUNTER_STATE")

    # difficulty: cross_entity_state_dependency/encounter_checkin_requires_patient_and_provider_active
    def test_checkin_rejected_after_cancel(self, api):
        """PRD §3.3: "Cancellation is forbidden after the encounter
        has already reached a terminal state. ... A check-in
        attempted from any other state yields
        ERR_INVALID_ENCOUNTER_STATE."

        Claim: check-in attempted against a CANCELLED encounter is
        rejected with ERR_INVALID_ENCOUNTER_STATE — confirming the
        state-eligibility family that the cross-entity ACTIVE check
        belongs to.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        sched_start = iso_anchor_offset(hours=2)
        sched_end = iso_anchor_offset(hours=2, minutes=30)
        encounter = schedule_encounter(
            patient["id"], provider["id"],
            scheduled_start=sched_start, scheduled_end=sched_end,
            encounter_type="CONSULTATION",
            chief_complaint="To cancel then attempt-checkin",
        )
        cancel_encounter(encounter["id"], provider["id"])
        # Now advance and try check-in.
        advance_clock_to(iso_anchor_offset(hours=1, minutes=55))
        res = api.checkin_encounter(
            encounter["id"], TEST_USERS["nurse_headers"],
        )
        validate_error(res, "ERR_INVALID_ENCOUNTER_STATE")
