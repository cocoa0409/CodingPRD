"""Visit registration, triage scoring, and routing (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_visit,
    create_owner,
    create_pet,
    create_visit,
    create_visit_payload,
    setup_owner_and_pet,
    triage,
    validate_error,
    validate_success,
)


class TestVisitCreation:
    def test_visit_created_with_status_registered(self, api, triage_nurse_headers):
        """PRD §3.4: 'The created visit carries a pet_id (taken from the
        path), a default status of REGISTERED, and a closed_at of null.'"""
        owner, pet = setup_owner_and_pet()
        res = api.create_visit(
            pet["id"], create_visit_payload(), triage_nurse_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_visit(data)
        assert data["status"] == "REGISTERED"
        assert data.get("closed_at") is None
        assert data["pet_id"] == pet["id"]


class TestTriagePreconditions:
    def test_triage_requires_owner_verified(self, api, triage_nurse_headers):
        """PRD §3.4: 'Two preconditions apply: the owner's contact_verified
        must be true (otherwise ERR_OWNER_NOT_VERIFIED), and the pet must
        not be archived.'"""
        owner = create_owner(with_verification=False, with_deposit_cents=0)
        pet = create_pet(owner_id=owner["id"])
        visit = create_visit(pet_id=pet["id"], severity_score=5)
        res = api.triage_visit(visit["id"], triage_nurse_headers)
        validate_error(res, "ERR_OWNER_NOT_VERIFIED")


class TestTriagePriorityScoringBoundaries:
    """PRD §3.4: triage_priority bucket boundaries (lower-bound inclusive)."""

    def test_score_at_emergency_threshold_8_inclusive(self, api):
        """PRD §3.4: 'The bucket is selected with lower-bound-inclusive
        boundaries: a final score of at least 8.0 maps triage_priority
        to EMERGENCY; otherwise a final score of at least 5.0 maps it
        to URGENT; otherwise it maps to ROUTINE.'

        DOG (factor 1.0), age 200 days (factor 1.0), severity=8 → 8.0
        → EMERGENCY at the inclusive boundary.
        """
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01", weight_kg=10.0,
        )
        visit = create_visit(pet_id=pet["id"], severity_score=8)
        triaged = triage(visit["id"])
        assert triaged["triage_priority"] == "EMERGENCY"

    def test_score_just_below_emergency_threshold_is_urgent(self, api):
        """PRD §3.4: 'a final score of at least 8.0 maps triage_priority
        to EMERGENCY; otherwise a final score of at least 5.0 maps it
        to URGENT.'

        DOG, severity=7 → score 7.0 < 8.0 → URGENT.
        """
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01", weight_kg=10.0,
        )
        visit = create_visit(pet_id=pet["id"], severity_score=7)
        triaged = triage(visit["id"])
        assert triaged["triage_priority"] == "URGENT"

    def test_score_at_urgent_threshold_5_inclusive(self, api):
        """PRD §3.4: 'a final score of at least 5.0 maps it to URGENT;
        otherwise it maps to ROUTINE.'

        DOG, severity=5 → 5.0 → URGENT (inclusive).
        """
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01", weight_kg=10.0,
        )
        visit = create_visit(pet_id=pet["id"], severity_score=5)
        triaged = triage(visit["id"])
        assert triaged["triage_priority"] == "URGENT"

    def test_score_below_urgent_threshold_is_routine(self, api):
        """PRD §3.4: 'a final score of at least 5.0 maps it to URGENT;
        otherwise it maps to ROUTINE.'

        DOG, severity=4 → 4.0 → ROUTINE.
        """
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01", weight_kg=10.0,
        )
        visit = create_visit(pet_id=pet["id"], severity_score=4)
        triaged = triage(visit["id"])
        assert triaged["triage_priority"] == "ROUTINE"


class TestDepartmentRouting:
    """PRD §3.4 — keyword-based department routing.

    These tests pin SEVERITY low enough not to trigger EMERGENCY so the
    keyword path is exercised. (EMERGENCY priority forces department
    EMERGENCY regardless of keywords.)
    """

    def test_emergency_priority_routes_to_emergency_department(self, api):
        """PRD §3.4: 'When triage_priority is EMERGENCY, department_code
        is set to EMERGENCY regardless of symptom keywords.'"""
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01",
        )
        visit = create_visit(
            pet_id=pet["id"], severity_score=10, symptom_text="dental pain",
        )
        triaged = triage(visit["id"])
        assert triaged["triage_priority"] == "EMERGENCY"
        assert triaged["department_code"] == "EMERGENCY"

    def test_skin_keyword_routes_to_dermatology(self, api):
        """PRD §3.4: 'Otherwise the symptom text is lower-cased and
        inspected: if it contains the substring "skin", department_code
        is DERMATOLOGY.'"""
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01",
        )
        visit = create_visit(
            pet_id=pet["id"], severity_score=4, symptom_text="itchy skin rash",
        )
        triaged = triage(visit["id"])
        assert triaged["triage_priority"] != "EMERGENCY"
        assert triaged["department_code"] == "DERMATOLOGY"

    def test_tooth_keyword_routes_to_dental(self, api):
        """PRD §3.4: 'otherwise if it contains "tooth" or "dental",
        department_code is DENTAL.'"""
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01",
        )
        visit = create_visit(
            pet_id=pet["id"], severity_score=4, symptom_text="loose tooth",
        )
        triaged = triage(visit["id"])
        assert triaged["department_code"] == "DENTAL"

    def test_severity_6_no_keyword_routes_to_surgery(self, api):
        """PRD §3.4: 'otherwise if severity_score is at least 6,
        department_code is SURGERY.'"""
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01",
        )
        visit = create_visit(
            pet_id=pet["id"], severity_score=6, symptom_text="abdominal pain",
        )
        triaged = triage(visit["id"])
        # severity 6 with DOG factor 1 + adult age factor 1 → 6.0 → URGENT
        assert triaged["triage_priority"] == "URGENT"
        assert triaged["department_code"] == "SURGERY"

    def test_default_routes_to_internal_med(self, api):
        """PRD §3.4: 'otherwise department_code is INTERNAL_MED.'"""
        owner, pet = setup_owner_and_pet(
            species="DOG", birth_date="2025-01-01",
        )
        visit = create_visit(
            pet_id=pet["id"], severity_score=3, symptom_text="mild fatigue",
        )
        triaged = triage(visit["id"])
        assert triaged["department_code"] == "INTERNAL_MED"


class TestVisitCancel:
    def test_cancel_registered_visit_with_no_artifacts(self, api):
        """PRD §3.4: 'A TriageNurse may cancel a visit from REGISTERED
        or from TRIAGED only when the visit has no treatment record, no
        lab report, no prescription, and no hospitalization yet attached.'"""
        owner, pet = setup_owner_and_pet()
        visit = create_visit(pet_id=pet["id"], severity_score=4)
        res = api.cancel_visit(visit["id"], TEST_USERS["triage_nurse_headers"])
        data = validate_success(res)
        assert data["status"] == "CANCELLED"


class TestStartConsultIdentity:
    def test_start_consult_requires_assigned_vet_id(self, api):
        """PRD §3.4: 'The drafting vet who consults the visit calls the
        start-consult action to advance from TRIAGED to IN_CONSULT; the
        request is admitted only when X-User-ID matches the visit's
        assigned_vet_id.'"""
        owner, pet = setup_owner_and_pet()
        visit = create_visit(pet_id=pet["id"], severity_score=4)
        triaged = triage(visit["id"])
        # Use a DraftingVet header whose id is NOT the assigned_vet_id.
        wrong_id = "different-vet-id"
        from test_helpers import build_user_headers
        if triaged.get("assigned_vet_id") == wrong_id:
            wrong_id = "different-vet-id-2"
        bad_headers = build_user_headers(wrong_id, "DraftingVet")
        res = api.start_consult(visit["id"], bad_headers)
        # Identity mismatch surfaces as state/access — PRD §3.4 names
        # the rule but does not commit to a specific error_id, so we
        # accept either ERR_FORBIDDEN or ERR_INVALID_STATE.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, ["ERR_FORBIDDEN", "ERR_INVALID_STATE"])
