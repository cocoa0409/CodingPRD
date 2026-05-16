"""Patient registration, policy attachment, and entity invariants.

Covers PRD §3.1 (registration + policy attachment) and PRD §2.5 (common
fields shape).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_insurance_policy,
    assert_patient,
    create_patient,
    create_patient_payload,
    create_policy,
    create_policy_payload,
    setup_patient_with_policy,
    validate_success,
)


# ===========================================================================
# §3.1 Patient creation
# ===========================================================================
class TestPatientCreation:
    """PRD §3.1: A RegistrationClerk opens a new patient record."""

    def test_create_patient_returns_active_status(self, api):
        """PRD §3.1: "A newly created patient record is in the `ACTIVE` status; the only other terminal status the patient record may reach is `ARCHIVED`."

        Claim: a freshly created Patient carries status == 'ACTIVE'.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["registration_clerk_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_patient(data)
        assert data["status"] == "ACTIVE"

    def test_create_patient_carries_common_fields(self, api):
        """PRD §2.5: "Every resource the API persists carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp formatted as an ISO 8601 UTC string with three fractional digits"

        Claim: a created Patient carries id, created_at, updated_at,
        and version=1.
        """
        data = validate_success(
            api.create_patient(
                create_patient_payload(),
                TEST_USERS["registration_clerk_headers"],
            ),
            expected_status=201,
        )
        assert_patient(data)
        assert data["version"] == 1


# ===========================================================================
# §3.1 Policy attachment
# ===========================================================================
class TestPolicyAttachment:
    """PRD §3.1: Insurance policies are attached to a patient."""

    def test_attach_policy_initialises_unverified(self, api):
        """PRD §3.1: "A newly attached policy is created in the `UNVERIFIED` status with `deductible_met_cents` initialised to 0, `oop_accumulated_cents` initialised to 0, and `verified_at` initialised to null."

        Claim: a freshly attached policy has status='UNVERIFIED',
        deductible_met_cents=0, oop_accumulated_cents=0, verified_at
        null.
        """
        patient = create_patient()
        res = api.create_policy(
            patient["id"], create_policy_payload(),
            TEST_USERS["registration_clerk_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_insurance_policy(data)
        assert data["status"] == "UNVERIFIED"
        assert data["deductible_met_cents"] == 0
        assert data["oop_accumulated_cents"] == 0
        assert data.get("verified_at") is None

    def test_policy_owns_patient_id(self, api):
        """PRD §3.1: "The path encodes the owning patient via `patient_id`, and the same `patient_id` is stamped onto the resulting policy."

        Claim: the policy's patient_id equals the patient.id from the
        path.
        """
        patient = create_patient()
        data = validate_success(
            api.create_policy(
                patient["id"], create_policy_payload(),
                TEST_USERS["registration_clerk_headers"],
            ),
            expected_status=201,
        )
        assert data["patient_id"] == patient["id"]


# ===========================================================================
# §2.7 Policy field bounds
# ===========================================================================
class TestPolicyFieldBounds:
    """PRD §2.7: deductible / coinsurance / OOP-max bounds."""

    def test_default_policy_invariants(self, api):
        """PRD §2.7: "The coinsurance rate itself is stored in basis points via `coinsurance_rate_bps` and is constrained to lie between 0 and 10000 inclusive"
        PRD §2.7: "The annual out-of-pocket maximum `oop_max_cents` must be at least as large as `deductible_cents`."

        Claim: a default-configured policy satisfies the bounds.
        """
        patient, policy = setup_patient_with_policy()
        assert 0 <= policy["coinsurance_rate_bps"] <= 10000
        assert policy["oop_max_cents"] >= policy["deductible_cents"]


# ===========================================================================
# §2.5 Mutable common fields
# ===========================================================================
class TestCommonFieldsMutable:
    """PRD §2.5: Patient, InsurancePolicy, Encounter, ChargeItem, and
    CodingRecord carry id + created_at + updated_at + version."""

    def test_patient_has_updated_at_and_version(self, api):
        """PRD §2.5: "The `Patient`, `InsurancePolicy`, `Encounter`, `ChargeItem`, and `CodingRecord` resources additionally carry an `updated_at` ISO 8601 UTC timestamp that is refreshed on every mutation of the resource, and an integer `version` that begins at 1 on creation and is incremented by exactly one on each subsequent mutation."

        Claim: a created Patient response carries updated_at and
        version=1.
        """
        data = validate_success(
            api.create_patient(
                create_patient_payload(),
                TEST_USERS["registration_clerk_headers"],
            ),
            expected_status=201,
        )
        assert isinstance(data["updated_at"], str)
        assert data["version"] == 1

    def test_policy_has_updated_at_and_version(self, api):
        """PRD §2.5: Patient, InsurancePolicy, Encounter, ChargeItem,
        and CodingRecord carry updated_at and version.

        Claim: a created InsurancePolicy carries updated_at and
        version=1.
        """
        patient = create_patient()
        data = validate_success(
            api.create_policy(
                patient["id"], create_policy_payload(),
                TEST_USERS["registration_clerk_headers"],
            ),
            expected_status=201,
        )
        assert isinstance(data["updated_at"], str)
        assert data["version"] == 1
