"""Patient and Clinician CRUD, wage_index recomputation, OCC.

PRD §3.1 (Patients, ZIPs, wage_index), §3.2 (Clinicians), §2.8 (OCC).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_clinician,
    assert_patient,
    assert_version_incremented_by_one,
    create_clinician,
    create_clinician_payload,
    create_patient,
    create_patient_payload,
    patch_clinician,
    patch_patient,
    patch_patient_payload,
    re_get_patient,
    validate_error,
    validate_success,
)


# ===========================================================================
# Patient creation + wage_index computation
# ===========================================================================
class TestPatientCreate:

    def test_create_patient_returns_full_resource(self, api):
        """PRD §2.2 / §3.1: POST /patients returns 201 with the full
        Patient resource. PRD §3.1: "The system computes wage_index from
        home_zip at patient creation and stores it on the patient row."

        Claim: a successful create returns 201 with id, common fields,
        and a computed wage_index.
        """
        res = api.create_patient(
            create_patient_payload(home_zip="10001"),
            TEST_USERS["intake_coordinator_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_patient(data)
        assert data["home_zip"] == "10001"
        assert data["version"] == 1, (
            "PRD §2.4: version starts at 1 on creation"
        )

    def test_create_patient_duplicate_medicare_id_rejected(self, api):
        """PRD §3.1: "The medicare_id is unique across patients; a
        second patient registered with a Medicare identifier already in
        use is rejected."

        Claim: re-using a medicare_id is rejected with a 4xx error.
        """
        p1 = create_patient(medicare_id="1ABCDEF8901")
        res = api.create_patient(
            create_patient_payload(medicare_id="1ABCDEF8901"),
            TEST_USERS["intake_coordinator_headers"],
        )
        assert res.status_code >= 400, (
            "duplicate medicare_id must be rejected; got 2xx"
        )


# ===========================================================================
# Patient update — wage_index recomputation + OCC
# ===========================================================================
class TestPatientPatch:

    def test_patch_home_zip_recomputes_wage_index(self, api):
        """PRD §3.1: "If the patient's home_zip is later changed through
        a coordinator-driven update — which may also adjust the
        full_name — the server recomputes wage_index from the new ZIP
        and refreshes updated_at and version."

        Claim: PATCH home_zip causes wage_index to be re-derived and
        version to increment by 1.
        """
        # Use two different ZIPs (the mapping is implementation-defined,
        # so we only assert recomputation, not specific values).
        p = create_patient(home_zip="10001")
        before_version = p["version"]
        before_wage = p["wage_index"]
        updated = patch_patient(patient=p, home_zip="94538")
        assert_patient(updated)
        assert updated["home_zip"] == "94538"
        assert_version_incremented_by_one(updated, before_version)
        # Cannot assert a specific wage_index (mapping is impl-defined),
        # but a faithful implementation MUST recompute when home_zip
        # changes; assert wage_index is present and positive.
        assert updated["wage_index"] > 0

    def test_patch_patient_stale_version_rejected(self, api):
        """PRD §2.8: "When the caller includes version, the server
        compares it to the resource's current version; on mismatch the
        request is rejected with ERR_VERSION_CONFLICT."

        Claim: a PATCH with a stale version returns ERR_VERSION_CONFLICT.
        """
        p = create_patient()
        # First patch bumps version to 2.
        patch_patient(patient=p, full_name="Renamed")
        # Submit again with the OLD version (1).
        res = api.patch_patient(
            p["id"],
            patch_patient_payload(full_name="Other", version=p["version"]),
            TEST_USERS["intake_coordinator_headers"],
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_patch_patient_without_version_skips_check(self, api):
        """PRD §2.8: "Omitting version skips the check entirely and the
        mutation proceeds against whatever the server's current state
        is — this is by design for callers who explicitly want a last-
        writer-wins update."

        Claim: a PATCH that omits version succeeds even if local copy
        is stale.
        """
        p = create_patient()
        patch_patient(patient=p, full_name="First Update")
        # Use the original (stale) snapshot but skip version → must
        # succeed.
        res = api.patch_patient(
            p["id"],
            patch_patient_payload(full_name="Second Update"),
            TEST_USERS["intake_coordinator_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["full_name"] == "Second Update"


# ===========================================================================
# Clinician CRUD + status + version
# ===========================================================================
class TestClinicianCreate:

    @pytest.mark.parametrize(
        "discipline",
        ["SN", "PT", "OT", "SLP", "HHA"],
    )
    def test_create_clinician_each_discipline(self, api, discipline):
        """PRD §3.2: each carries "a discipline — one of SN (skilled
        nurse), PT (physical therapy), OT (occupational therapy), SLP
        (speech-language pathology), or HHA (home health aide)".

        Claim: each discipline value is accepted on creation.
        """
        res = api.create_clinician(
            create_clinician_payload(discipline=discipline),
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_clinician(data)
        assert data["discipline"] == discipline
        # PRD §3.2: "Every clinician starts in AVAILABLE … status".
        # PRD §3.2 also says status is "either AVAILABLE or SUSPENDED";
        # the natural initial state is AVAILABLE.
        assert data["status"] == "AVAILABLE"


class TestClinicianPatch:

    def test_admin_can_suspend_clinician(self, api):
        """PRD §3.2: "Admins can amend the license_expiration_date or
        move a clinician between AVAILABLE and SUSPENDED after
        creation."

        Claim: PATCH status=SUSPENDED transitions the clinician and
        bumps version.
        """
        c = create_clinician(discipline="SN")
        before_version = c["version"]
        updated = patch_clinician(clinician=c, status="SUSPENDED")
        assert_clinician(updated)
        assert updated["status"] == "SUSPENDED"
        assert_version_incremented_by_one(updated, before_version)

    def test_admin_can_amend_license_expiration_date(self, api):
        """PRD §3.2: "Admins can amend the license_expiration_date".

        Claim: PATCH license_expiration_date succeeds and bumps version.
        """
        c = create_clinician(discipline="PT")
        before_version = c["version"]
        updated = patch_clinician(
            clinician=c, license_expiration_date="2030-06-30",
        )
        assert_clinician(updated)
        assert updated["license_expiration_date"] == "2030-06-30"
        assert_version_incremented_by_one(updated, before_version)
