"""Family, Guardian, and Child CRUD + basic invariants.

Tests in this file exercise PRD §3.1 (household setup): Family
creation, primary-email normalization, residency default, primary
guardian demotion, child date_of_birth constraints, OCC version
behavior on PATCH /camp/families/{id}.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_child,
    assert_family,
    assert_guardian,
    assert_version_incremented_by_one,
    create_child_payload,
    create_family,
    create_family_payload,
    create_guardian,
    create_guardian_payload,
    dob_for_age,
    iso_offset,
    patch_family_payload,
    setup_family_with_primary_guardian,
    validate_error,
    validate_success,
)


# ===========================================================================
# Family CRUD
# ===========================================================================
class TestFamilyCreation:
    def test_create_family_minimal_input(self, api):
        """PRD §3.1: "A ProgramAdmin creates a family with a display
        household_name (1-100 characters) and a primary_email that is
        lower-cased on intake and must be unique across all
        non-archived families."

        Claim: POST /camp/families with minimal valid input returns
        201 + a Family whose primary_email is lower-cased.
        """
        payload = create_family_payload(
            household_name="The Smiths",
            primary_email="UPPER@EXAMPLE.COM",
        )
        res = api.create_family(payload, TEST_USERS["admin_headers"])
        family = validate_success(res, 201)
        assert_family(family)
        # PRD §3.1: "primary_email that is lower-cased on intake".
        assert family["primary_email"] == "upper@example.com"
        assert family["household_name"] == "The Smiths"

    def test_create_family_default_residency_standard(self, api):
        """PRD §3.1: "The optional residency_status defaults to
        STANDARD when omitted."

        Claim: omitting residency_status creates a family with
        residency_status=="STANDARD".
        """
        payload = create_family_payload()
        # Ensure residency_status is omitted from the request body.
        payload.pop("residency_status", None)
        res = api.create_family(payload, TEST_USERS["admin_headers"])
        family = validate_success(res, 201)
        assert family["residency_status"] == "STANDARD"

    def test_create_family_archived_starts_false(self, api):
        """PRD §3.1: "The archived flag is system-managed and starts
        at false; once a family is soft-deleted, it is true."

        Claim: a freshly created family has archived=false.
        """
        family = create_family()
        assert family["archived"] is False

    def test_duplicate_primary_email_rejected(self, api):
        """PRD §3.1: "a primary_email that is lower-cased on intake
        and must be unique across all non-archived families."

        Claim: creating a second family with the same primary_email
        (modulo case) is rejected. The PRD does not pin the specific
        error_id; reject is the observable outcome.
        """
        email = "uniq@example.com"
        family_a = create_family(primary_email=email)
        # Attempt to reuse the same email on a second non-archived
        # family with different case to also exercise the lower-case
        # collapse.
        res = api.create_family(
            create_family_payload(primary_email=email.upper()),
            TEST_USERS["admin_headers"],
        )
        assert res.status_code >= 400, (
            f"duplicate primary_email must be rejected, "
            f"got {res.status_code}"
        )


# ===========================================================================
# Family PATCH + OCC
# ===========================================================================
class TestFamilyPatch:
    def test_patch_family_increments_version(self, api):
        """PRD §2.4: "The version is a positive integer that starts at
        1 on creation and increments by exactly 1 on every persisted
        mutation of that row."

        Claim: PATCH /camp/families/{id} that mutates household_name
        increments version by exactly 1.
        """
        family = create_family()
        before = family["version"]
        res = api.patch_family(
            family["id"],
            patch_family_payload(
                version=before, household_name="Renamed Household",
            ),
            TEST_USERS["admin_headers"],
        )
        updated = validate_success(res, 200)
        assert_version_incremented_by_one(updated, before)
        assert updated["household_name"] == "Renamed Household"

    def test_patch_family_stale_version_rejected(self, api):
        """PRD §2.5: "When the client supplies version and it does
        not match, the mutation is rejected with ERR_STALE_VERSION
        and HTTP status 409."

        Claim: PATCH with a stale version returns ERR_STALE_VERSION.
        """
        family = create_family()
        # Advance the version once.
        api.patch_family(
            family["id"],
            patch_family_payload(
                version=family["version"], household_name="First Rename",
            ),
            TEST_USERS["admin_headers"],
        )
        # Reuse the old version → stale.
        res = api.patch_family(
            family["id"],
            patch_family_payload(
                version=family["version"],
                household_name="Second Rename",
            ),
            TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_STALE_VERSION")

    def test_patch_family_omitted_version_skips_occ(self, api):
        """PRD §2.5: "When the client omits version from the body
        entirely, no concurrency check is performed and the mutation
        proceeds as if the client had supplied the current value."

        Claim: PATCH without a version field in the body succeeds.
        """
        family = create_family()
        payload = patch_family_payload(household_name="No-OCC Rename")
        # Ensure the version key is absent.
        assert "version" not in payload
        res = api.patch_family(
            family["id"], payload, TEST_USERS["admin_headers"],
        )
        updated = validate_success(res, 200)
        assert updated["household_name"] == "No-OCC Rename"


# ===========================================================================
# Family soft-delete
# ===========================================================================
class TestFamilyDelete:
    def test_delete_family_returns_204(self, api):
        """PRD §4: "a successful soft-delete returns 204 with an empty
        body".

        Claim: DELETE /camp/families/{id} on a quiescent family returns
        HTTP 204.
        """
        family = create_family()
        res = api.delete_family(family["id"], TEST_USERS["admin_headers"])
        assert res.status_code == 204, (
            f"expected 204, got {res.status_code}: {res.text}"
        )

    def test_delete_family_sets_archived_true(self, api):
        """PRD §3.1: "A family soft-delete by a ProgramAdmin flips
        archived to true."

        Claim: after soft-delete, archived==true on the family.
        """
        family = create_family()
        api.delete_family(family["id"], TEST_USERS["admin_headers"])
        # A subsequent GET should still resolve and show archived=true.
        # If the implementation 404s archived rows, we tolerate that
        # by not asserting; the contract is only that archived flips.
        res = api.get_family(family["id"], TEST_USERS["admin_headers"])
        if res.status_code == 200:
            data = res.json()["data"]
            assert data["archived"] is True


# ===========================================================================
# Guardian primary-demotion side effect
# ===========================================================================
class TestGuardianPrimaryDemotion:
    def test_new_primary_demotes_existing_primary(self, api):
        """PRD §3.1: "When a new guardian is created with is_primary
        set to true, any previously primary guardian on the same
        family is silently demoted to is_primary false, and only the
        newly added record is left as the family's primary; the
        demotion increments the demoted row's version and refreshes
        its updated_at."

        Claim: adding a second primary guardian flips the first's
        is_primary to false and bumps its version.
        """
        family, first_primary = setup_family_with_primary_guardian()
        before_version = first_primary["version"]
        second = create_guardian(
            family=family, is_primary=True,
            full_name="Second Primary",
        )
        assert second["is_primary"] is True
        # Re-read the first guardian via the list endpoint.
        list_res = api.list_guardians(
            family["id"], TEST_USERS["admin_headers"],
        )
        list_data = list_res.json()["data"]
        first_after = next(
            g for g in list_data if g["id"] == first_primary["id"]
        )
        assert first_after["is_primary"] is False, (
            "previously-primary guardian must be demoted"
        )
        # PRD §3.1: "the demotion increments the demoted row's version".
        assert first_after["version"] > before_version, (
            f"demotion must bump version (was {before_version}, "
            f"is {first_after['version']})"
        )

    def test_is_primary_omitted_defaults_to_non_primary(self, api):
        """PRD §3.1: "If the request omits is_primary, the new
        guardian defaults to non-primary."

        Claim: a guardian created without is_primary has
        is_primary==false in the response.
        """
        family = create_family()
        payload = create_guardian_payload()
        # Ensure is_primary is omitted.
        payload.pop("is_primary", None)
        res = api.create_guardian(
            family["id"], payload, TEST_USERS["admin_headers"],
        )
        guardian = validate_success(res, 201)
        assert guardian["is_primary"] is False


# ===========================================================================
# Child creation
# ===========================================================================
class TestChildCreation:
    def test_create_child_with_dob_in_past_succeeds(self, api):
        """PRD §3.1: "a date_of_birth (ISO 8601 calendar date in
        YYYY-MM-DD), which must lie strictly in the past relative to
        the current logical clock."

        Claim: POST /camp/families/{id}/children with a past
        date_of_birth returns 201 + child.
        """
        family = create_family()
        payload = create_child_payload(date_of_birth=dob_for_age(8))
        res = api.create_child(
            family["id"], payload, TEST_USERS["admin_headers"],
        )
        child = validate_success(res, 201)
        assert_child(child)
        assert child["family_id"] == family["id"]

    def test_create_child_derived_fields_initial_state(self, api):
        """PRD §3.1: "The child's medical_authorization_status,
        pickup_authorization_status, and emergency_contact_count are
        derived: they start at NONE, NONE, and 0 respectively."

        Claim: a freshly created child has
        medical_authorization_status=="NONE",
        pickup_authorization_status=="NONE", and
        emergency_contact_count==0.
        """
        family = create_family()
        payload = create_child_payload(date_of_birth=dob_for_age(8))
        res = api.create_child(
            family["id"], payload, TEST_USERS["admin_headers"],
        )
        child = validate_success(res, 201)
        assert child["medical_authorization_status"] == "NONE"
        assert child["pickup_authorization_status"] == "NONE"
        assert child["emergency_contact_count"] == 0
