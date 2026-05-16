"""Student creation and AllergyProfileEntry lifecycle.

PRD §3.1 (student initial tier=PAID and eligibility_application_id=null).
PRD §3.2 (allergy entries: severity SEVERE → doctor_note_attached
required; duplicate (student, allergen) where status=ACTIVE rejected;
revocation requires ACTIVE status and parent ownership).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_allergy_profile_entry,
    assert_student,
    create_allergy_entry,
    create_allergy_entry_payload,
    create_student,
    create_student_payload,
    make_parent_headers,
    revoke_allergy_entry,
    setup_district_with_family,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 Student creation
# ===========================================================================
class TestStudentCreation:
    """PRD §3.1: every student starts at the paid tier."""

    def test_new_student_initial_tier_paid(self, api):
        """PRD §3.1: "On creation, every student starts at the paid
        tier — eligibility_tier is PAID and eligibility_application_id
        is null — until an APPROVED FrlApplication mints a more
        favourable tier."

        Claim: POST /students → eligibility_tier == 'PAID' AND
        eligibility_application_id is null.
        """
        district, parent, student = setup_district_with_family()
        assert_student(student)
        assert student["eligibility_tier"] == "PAID", (
            f"expected initial tier PAID, got {student['eligibility_tier']}"
        )
        assert student.get("eligibility_application_id") is None, (
            f"expected null eligibility_application_id, got "
            f"{student.get('eligibility_application_id')!r}"
        )

    def test_new_student_meals_served_today_count_zero(self, api):
        """PRD §3.1: "Two derived fields on a Student,
        allergy_block_active and meals_served_today_count, are
        evaluated on read."
        PRD §3.6: "the student's meals_served_today_count becomes 1"
        only after a successful serving.

        Claim: a freshly-created student has meals_served_today_count
        == 0.
        """
        _, _, student = setup_district_with_family()
        assert student["meals_served_today_count"] == 0

    def test_grade_level_zero_kindergarten_allowed(self, api):
        """PRD §3.1: "grade_level is an integer from 0 through 12
        inclusive (0 representing kindergarten)".

        Claim: grade_level=0 is accepted.
        """
        district, parent, _ = setup_district_with_family()
        student = create_student(
            district=district, parent_account=parent, grade_level=0,
        )
        assert student["grade_level"] == 0

    def test_grade_level_twelve_allowed(self, api):
        """PRD §3.1: "grade_level is an integer from 0 through 12
        inclusive".

        Claim: grade_level=12 is accepted (inclusive upper bound).
        """
        district, parent, _ = setup_district_with_family()
        student = create_student(
            district=district, parent_account=parent, grade_level=12,
        )
        assert student["grade_level"] == 12


# ===========================================================================
# §3.2 AllergyProfileEntry creation
# ===========================================================================
class TestAllergyEntryCreation:
    """PRD §3.2: allergen + severity + doctor_note_attached; SEVERE
    requires doctor_note_attached=true; duplicate (student, allergen)
    where status=ACTIVE is ERR_DUPLICATE_ALLERGEN."""

    def test_create_active_allergy_entry(self, api):
        """PRD §3.2: "A new entry is born ACTIVE."

        Claim: POST /allergy-entries returns status='ACTIVE'.
        """
        district, parent, student = setup_district_with_family()
        entry = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="PEANUT", severity="MODERATE",
            doctor_note_attached=False,
        )
        assert_allergy_profile_entry(entry)
        assert entry["status"] == "ACTIVE"
        assert entry["allergen"] == "PEANUT"
        assert entry["severity"] == "MODERATE"

    def test_severe_without_doctor_note_rejected(self, api):
        """PRD §3.2: "When severity is SEVERE, the system requires
        doctor_note_attached to be true and otherwise rejects the
        request with ERR_DOCTOR_NOTE_REQUIRED."

        Claim: SEVERE + doctor_note_attached=false →
        ERR_DOCTOR_NOTE_REQUIRED.
        """
        district, parent, student = setup_district_with_family()
        res = api.create_allergy_entry(
            district["id"], student["id"],
            create_allergy_entry_payload(
                allergen="PEANUT", severity="SEVERE",
                doctor_note_attached=False,
            ),
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_DOCTOR_NOTE_REQUIRED")

    def test_severe_with_doctor_note_accepted(self, api):
        """PRD §3.2: "When severity is SEVERE, the system requires
        doctor_note_attached to be true."

        Claim: SEVERE + doctor_note_attached=true succeeds with
        status=ACTIVE.
        """
        district, parent, student = setup_district_with_family()
        entry = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="DAIRY", severity="SEVERE",
            doctor_note_attached=True,
        )
        assert entry["status"] == "ACTIVE"
        assert entry["severity"] == "SEVERE"
        assert entry["doctor_note_attached"] is True

    def test_duplicate_active_allergen_rejected(self, api):
        """PRD §3.2: "The system also forbids a student from holding
        two ACTIVE allergy entries for the same allergen: a second
        insertion that would collide with an existing ACTIVE row for
        the same (student_id, allergen) pair is rejected with
        ERR_DUPLICATE_ALLERGEN."

        Claim: second ACTIVE entry with same allergen →
        ERR_DUPLICATE_ALLERGEN.
        """
        district, parent, student = setup_district_with_family()
        create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="PEANUT", severity="MILD",
        )
        res = api.create_allergy_entry(
            district["id"], student["id"],
            create_allergy_entry_payload(
                allergen="PEANUT", severity="MILD",
            ),
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_DUPLICATE_ALLERGEN")

    def test_duplicate_allowed_after_revocation(self, api):
        """PRD §3.2: "forbids a student from holding two ACTIVE allergy
        entries for the same allergen" — the constraint is on ACTIVE
        rows specifically. PRD §3.2: "Revoking an entry ... the parent
        who owns the student moves it from ACTIVE to REVOKED".

        Claim: after revoking an entry, a fresh ACTIVE entry for the
        same allergen is permitted.
        """
        district, parent, student = setup_district_with_family()
        first = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="PEANUT", severity="MILD",
        )
        revoke_allergy_entry(
            district=district, parent_account=parent, student=student,
            entry_id=first["id"],
        )
        # A second ACTIVE entry for PEANUT is now permitted.
        second = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="PEANUT", severity="MILD",
        )
        assert second["status"] == "ACTIVE"
        assert second["id"] != first["id"]

    def test_different_allergens_coexist_active(self, api):
        """PRD §3.2: the duplicate constraint is on (student_id,
        allergen), so different allergens for the same student are
        permitted.

        Claim: two ACTIVE entries for different allergens succeed.
        """
        district, parent, student = setup_district_with_family()
        peanut = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="PEANUT", severity="MILD",
        )
        dairy = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="DAIRY", severity="MILD",
        )
        assert peanut["status"] == "ACTIVE"
        assert dairy["status"] == "ACTIVE"
        assert peanut["allergen"] != dairy["allergen"]


# ===========================================================================
# §3.2 AllergyProfileEntry revocation
# ===========================================================================
class TestAllergyEntryRevocation:
    """PRD §3.2: revocation moves ACTIVE → REVOKED; a second revocation
    surfaces ERR_INVALID_STATE."""

    def test_revoke_sets_status_revoked(self, api):
        """PRD §3.2: "the parent who owns the student moves it from
        ACTIVE to REVOKED via the dedicated capability".

        Claim: DELETE on an ACTIVE entry sets status=REVOKED.
        """
        district, parent, student = setup_district_with_family()
        entry = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="EGG", severity="MILD",
        )
        revoked = revoke_allergy_entry(
            district=district, parent_account=parent, student=student,
            entry_id=entry["id"],
        )
        assert revoked["status"] == "REVOKED"

    def test_revoke_already_revoked_rejected(self, api):
        """PRD §3.2: "revocation is permitted only when the entry is
        currently ACTIVE; a second revocation on the same entry
        surfaces ERR_INVALID_STATE."

        Claim: DELETE on a REVOKED entry → ERR_INVALID_STATE.
        """
        district, parent, student = setup_district_with_family()
        entry = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="SOY", severity="MILD",
        )
        revoke_allergy_entry(
            district=district, parent_account=parent, student=student,
            entry_id=entry["id"],
        )
        # Second revocation.
        res = api.delete_allergy_entry(
            district["id"], student["id"], entry["id"],
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_allergy_entry_carries_only_id_and_created_at(self, api):
        """PRD §2.4: "Two entity types are append-only event records
        and deliberately omit updated_at and version:
        AllergyProfileEntry and PaidLedgerEntry. Both carry only id and
        created_at from the common-fields set."

        Claim: an AllergyProfileEntry response does NOT carry
        updated_at or version.
        """
        district, parent, student = setup_district_with_family()
        entry = create_allergy_entry(
            district=district, parent_account=parent, student=student,
            allergen="WHEAT", severity="MILD",
        )
        # PRD-required omissions for append-only entities.
        assert "updated_at" not in entry or entry.get("updated_at") is None, (
            f"AllergyProfileEntry must not carry updated_at; got "
            f"{entry.get('updated_at')!r}"
        )
        assert "version" not in entry or entry.get("version") is None, (
            f"AllergyProfileEntry must not carry version; got "
            f"{entry.get('version')!r}"
        )
