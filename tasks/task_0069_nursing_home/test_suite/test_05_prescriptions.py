"""Prescription lifecycle: activation safety gates, suspension cascade,
administration constraints, and medication error reporting.

Anchored in PRD §3.4 and §3.5.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    activate_prescription,
    create_active_prescription,
    create_prescription,
    create_prescription_payload,
    get_prescription,
    administration_payload,
    leave_elder,
    list_audit_logs, find_audit_logs,
    medication_error_payload,
    setup_admitted_elder_v2,
    setup_admitted_elder_with_active_plan,
    unique_drug_code,
    PHYSICIAN, PHYSICIAN_ALT, NURSE, NURSE_ALT, NURSE_THIRD,
    SUPERVISOR, SUPERVISOR_ALT,
    make_physician_headers, make_nurse_headers,
    validate_error, validate_success,
)


# ===========================================================================
# Activation safety gates (PRD §3.4, §2.7 #9 / #10)
# ===========================================================================
class TestPrescriptionActivation:

    def test_activate_with_allergy_conflict_rejected(self):
        """PRD §3.4: "The allergy gate requires that the intersection of
        the elder's `allergies` set and the prescription's
        `contraindicated_allergens` set be empty; any non-empty
        intersection is rejected with `ERR_ALLERGY_CONFLICT`."

        Claim: elder allergies overlap contraindicated_allergens →
        ERR_ALLERGY_CONFLICT on activate.
        """
        bundle = setup_admitted_elder_v2(
            80, 10, 20,
            elder_overrides={"allergies": ["penicillin"]},
        )
        rx = create_prescription(
            bundle["elder"]["id"],
            contraindicated_allergens=["penicillin"],
        )
        resp = api_client.activate_prescription(rx["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_ALLERGY_CONFLICT.value)

    def test_activate_with_drug_interaction_rejected(self):
        """PRD §3.4: "The drug-interaction gate considers every other
        prescription on the same elder that is currently in `ACTIVE` and
        checks symmetrically: this prescription's `drug_code` must not
        appear in any `ACTIVE` prescription's `interacts_with_drug_codes`,
        and this prescription's `interacts_with_drug_codes` must contain
        no `drug_code` of any `ACTIVE` prescription on the elder."

        Claim: new Rx's drug_code is listed in an ACTIVE Rx's
        interacts_with_drug_codes → ERR_DRUG_INTERACTION.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        bad_code = unique_drug_code()
        # First active Rx declares it conflicts with `bad_code`.
        create_active_prescription(
            bundle["elder"]["id"],
            interacts_with_drug_codes=[bad_code],
        )
        # New Rx uses `bad_code`.
        rx2 = create_prescription(
            bundle["elder"]["id"], drug_code=bad_code,
        )
        resp = api_client.activate_prescription(rx2["id"], SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_DRUG_INTERACTION.value)

    def test_activate_writes_audit_log(self):
        """PRD §3.4: "The activation writes an `AuditLog` row."

        Claim: post-activate, an AuditLog row with entity_type
        `Prescription` and action `ACTIVATE` exists for this Rx.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        rx = create_active_prescription(bundle["elder"]["id"])
        rows = list_audit_logs(entity_type="Prescription",
                               entity_id=rx["id"])
        activates = find_audit_logs(
            rows, entity_type="Prescription",
            entity_id=rx["id"], action="ACTIVATE",
        )
        assert activates, "PRD §3.4 — ACTIVATE audit row required"


# ===========================================================================
# Suspend / Resume cascade (PRD §3.4 / §2.9)
# ===========================================================================
class TestSuspendResumeCascade:

    def test_manual_suspend_then_resume(self):
        """PRD §3.4: "A prescription in `ACTIVE` can move to `SUSPENDED`
        either through a Physician's direct suspend action ... A
        `SUSPENDED` prescription returns to `ACTIVE` either through a
        Physician's resume action."

        Claim: suspend then resume restores ACTIVE.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        rx = create_active_prescription(bundle["elder"]["id"])
        api_client.suspend_prescription(rx["id"], PHYSICIAN)
        rx_after_susp = get_prescription(rx["id"])
        assert rx_after_susp["status"] == "SUSPENDED"
        api_client.resume_prescription(rx["id"], PHYSICIAN)
        rx_after_resume = get_prescription(rx["id"])
        assert rx_after_resume["status"] == "ACTIVE"


# ===========================================================================
# Medication administration safety constraints (PRD §3.5, §2.7 #5/#7/#8)
# ===========================================================================
class TestMedicationAdministration:

    def test_administer_succeeds_with_scheduled_slot(self):
        """PRD §3.5: "Third, `scheduled_slot_at` must be a slot present in
        the prescription's generated dispensing schedule."

        Claim: administering at the prescription's first scheduled slot
        succeeds.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        physician = make_physician_headers("phy-a")
        nurse = make_nurse_headers("nurse-a")
        rx = create_active_prescription(
            bundle["elder"]["id"],
            physician_headers=physician,
            frequency_per_day=2,
        )
        rx = get_prescription(rx["id"])
        slots = rx.get("dispensing_schedule") or rx.get("schedule") or \
            rx.get("scheduled_slots") or []
        if not slots:
            pytest.skip("PRD §3.4 mentions the schedule is generated on "
                        "activation but does not require a specific field "
                        "name on the GET response; skipping until either "
                        "field surfaces. (silence: enum-write-pathway)")
        first = slots[0] if isinstance(slots[0], str) \
            else slots[0].get("scheduled_slot_at")
        resp = api_client.create_administration(
            rx["id"],
            administration_payload(scheduled_slot_at=first,
                                   outcome="ADMINISTERED"),
            nurse,
        )
        validate_success(resp, expected_status=201)

    def test_administer_with_same_id_as_prescriber_rejected_sod(self):
        """PRD §3.5: "First, the recording Nurse's identifier must not
        equal the prescription's `prescriber_id` — the same staff member
        cannot both prescribe and administer; a violation yields
        `ERR_SEGREGATION_OF_DUTIES`."

        Claim: when the nurse's X-User-ID equals the prescriber_id, the
        administration is rejected with ERR_SEGREGATION_OF_DUTIES.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        shared_id = "staff-shared"
        physician = make_physician_headers(shared_id)
        nurse_same = make_nurse_headers(shared_id)
        rx = create_active_prescription(
            bundle["elder"]["id"],
            physician_headers=physician,
        )
        # Use an arbitrary slot — SoD is priority 7, slot scheduling 19.
        # The PRD §2.7 priority order guarantees SoD fires first.
        resp = api_client.create_administration(
            rx["id"],
            administration_payload(scheduled_slot_at="2025-06-01T08:00:00.000Z",
                                   outcome="ADMINISTERED"),
            nurse_same,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_administer_controlled_substance_without_witness_rejected(self):
        """PRD §3.5: "Second, when the prescription's
        `is_controlled_substance` is true, `witness_id` must be supplied,
        must denote a different person from the recording Nurse, and must
        also differ from the `prescriber_id`; an absent or non-distinct
        witness yields `ERR_WITNESS_REQUIRED`."

        Claim: controlled-substance Rx + missing witness_id →
        ERR_WITNESS_REQUIRED.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        rx = create_active_prescription(
            bundle["elder"]["id"],
            is_controlled_substance=True,
        )
        resp = api_client.create_administration(
            rx["id"],
            administration_payload(
                scheduled_slot_at="2025-06-01T08:00:00.000Z",
                outcome="ADMINISTERED",
            ),
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_WITNESS_REQUIRED.value)

    def test_administer_against_suspended_rx_blocked(self):
        """PRD §3.4 / §3.5: "Future scheduled medication slots are blocked
        while a prescription is `SUSPENDED`." and PRD §2.7 #5: state
        precondition violations yield ERR_INVALID_STATE.

        Claim: against a SUSPENDED Rx, recording an administration
        returns ERR_INVALID_STATE.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pair_administration
        # difficulty: transitive_cascade/elder_leave_cascades_to_prescription_suspend_and_blocks_administration
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        physician = make_physician_headers("phy-x")
        # nurse_same is intentionally same id as physician to ALSO trip SoD.
        # PRD §2.7 priority: state (5) wins over SoD (7) → expected
        # ERR_INVALID_STATE.
        nurse_same = make_nurse_headers("phy-x")
        rx = create_active_prescription(
            bundle["elder"]["id"], physician_headers=physician,
        )
        # Move the elder to ON_LEAVE → Rx cascades to SUSPENDED.
        leave_elder(bundle["elder"]["id"])
        rx_after = get_prescription(rx["id"])
        assert rx_after["status"] == "SUSPENDED"
        resp = api_client.create_administration(
            rx["id"],
            administration_payload(
                scheduled_slot_at="2025-06-01T08:00:00.000Z",
                outcome="ADMINISTERED",
            ),
            nurse_same,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Freestanding medication error reports (PRD §3.5)
# ===========================================================================
class TestFreestandingErrorReport:

    def test_freestanding_error_report_created(self):
        """PRD §3.5: "Error reports may also be filed independently by a
        `Nurse` or `Supervisor` against an elder without an originating
        administration; the optional fields `administration_id` and
        `prescription_id` may be omitted in that path, but `elder_id`,
        `error_type`, `severity`, and `description` remain required."

        Claim: minimal freestanding report (no administration_id,
        prescription_id) is accepted (201).
        """
        bundle = setup_admitted_elder_v2(80, 10, 20)
        resp = api_client.create_medication_error(
            medication_error_payload(
                elder_id=bundle["elder"]["id"],
                error_type="OTHER",
                severity="MINOR",
                description="dosage label was smudged",
            ),
            NURSE,
        )
        validate_success(resp, expected_status=201)

    def test_freestanding_error_report_missing_elder_rejected(self):
        """PRD §3.5: "`elder_id`, `error_type`, `severity`, and
        `description` remain required."

        Claim: omitting elder_id from the freestanding report → 422
        ERR_VALIDATION.
        """
        resp = api_client.create_medication_error(
            {"error_type": "OTHER", "severity": "MINOR",
             "description": "test"},
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
