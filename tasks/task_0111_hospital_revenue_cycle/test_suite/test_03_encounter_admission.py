"""Encounter admission, REGISTERED state, and policy_patient_mismatch.

Covers PRD §3.2 (admission) and the priority-6 business referential
check (policy_id / patient_id ownership).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_encounter,
    create_encounter,
    create_encounter_payload,
    create_patient,
    create_policy,
    create_policy_payload,
    is_iso8601_timestamp,
    setup_patient_with_policy,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.2 Admission — initial state and stamps
# ===========================================================================
class TestAdmission:
    """PRD §3.2: A RegistrationClerk admits a patient by supplying
    patient_id and policy_id."""

    def test_admit_initialises_registered_with_stamps_and_zero_totals(
        self, api,
    ):
        """PRD §3.2: "On creation, the server stamps `admission_at` to the current clock instant, sets `discharge_at` to null, sets the encounter's `status` to `REGISTERED`, and initialises all five computed totals (`total_charges_cents`, `payer_responsibility_cents`, `patient_responsibility_cents`, `estimated_patient_responsibility_cents`, and `write_off_cents`) to 0."

        Claim: a freshly admitted Encounter carries status=REGISTERED,
        admission_at set, discharge_at null, and all five totals == 0.
        """
        patient, policy = setup_patient_with_policy()
        res = api.create_encounter(
            create_encounter_payload(
                patient_id=patient["id"], policy_id=policy["id"],
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_encounter(data)
        assert data["status"] == "REGISTERED"
        assert is_iso8601_timestamp(data["admission_at"])
        assert data.get("discharge_at") in (None, "")
        for field in (
            "total_charges_cents",
            "payer_responsibility_cents",
            "patient_responsibility_cents",
            "estimated_patient_responsibility_cents",
            "write_off_cents",
        ):
            assert data[field] == 0, f"{field} must be 0 on creation"

    def test_admit_records_patient_and_policy_ids(self, api):
        """PRD §3.2: "A `RegistrationClerk` admits a patient by supplying the `patient_id` and the `policy_id` that will be the encounter's billing policy."

        Claim: the response carries the same patient_id and policy_id
        the request supplied.
        """
        patient, policy = setup_patient_with_policy()
        data = validate_success(
            api.create_encounter(
                create_encounter_payload(
                    patient_id=patient["id"], policy_id=policy["id"],
                ),
                TEST_USERS["registration_clerk_headers"],
            ),
            expected_status=201,
        )
        assert data["patient_id"] == patient["id"]
        assert data["policy_id"] == policy["id"]


# ===========================================================================
# §3.2 Policy/patient ownership mismatch
# ===========================================================================
class TestPolicyPatientMismatch:
    """PRD §3.2: the policy referenced by policy_id must belong to the
    patient referenced by patient_id."""

    def test_policy_owned_by_different_patient_rejected(self, api):
        """PRD §3.2: "Before the encounter is persisted, the system verifies that the policy referenced by `policy_id` belongs to the patient referenced by `patient_id`; if the policy's `patient_id` does not match the encounter's `patient_id`, the admission is rejected with `ERR_POLICY_PATIENT_MISMATCH`."

        Claim: POST /encounters with policy_id belonging to a
        different patient returns ERR_POLICY_PATIENT_MISMATCH.
        """
        patient_a = create_patient()
        patient_b = create_patient()
        policy_for_b = create_policy(patient=patient_b)
        res = api.create_encounter(
            create_encounter_payload(
                patient_id=patient_a["id"], policy_id=policy_for_b["id"],
            ),
            TEST_USERS["registration_clerk_headers"],
        )
        validate_error(res, "ERR_POLICY_PATIENT_MISMATCH")


# ===========================================================================
# §3.2 Metadata update path
# ===========================================================================
class TestEncounterPatch:
    """PRD §3.2: "While the encounter remains in `REGISTERED`, the `RegistrationClerk` may update its metadata — most importantly, swapping the `policy_id` if registration discovers the wrong policy was attached.\""""

    def test_patch_policy_id_while_registered_succeeds(self, api):
        """PRD §3.2: "Updates supply the current `version` (or omit it to skip the OCC check) and only `policy_id` is modifiable through this path."

        Claim: PATCH /encounters/{id} with a different policy_id (on
        the same patient) succeeds while encounter is REGISTERED.
        """
        from test_helpers import patch_encounter_payload
        patient = create_patient()
        policy_one = create_policy(patient=patient)
        policy_two = create_policy(patient=patient)
        encounter = create_encounter(patient=patient, policy=policy_one)
        res = api.patch_encounter(
            encounter["id"],
            patch_encounter_payload(policy_id=policy_two["id"]),
            TEST_USERS["registration_clerk_headers"],
        )
        data = validate_success(res)
        assert data["policy_id"] == policy_two["id"]
        assert data["status"] == "REGISTERED"
