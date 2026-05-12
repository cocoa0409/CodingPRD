"""Treatment records, finalization, and amend (PRD §3.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    amend_treatment_record_payload,
    assert_treatment_record,
    build_user_headers,
    create_treatment_record,
    create_treatment_record_payload,
    create_visit,
    create_visit_payload,
    finalize_treatment_record,
    get_pet,
    get_success_data,
    setup_owner_and_pet,
    setup_visit_in_consult,
    setup_visit_with_finalized_treatment,
    triage,
    validate_error,
    validate_success,
    vet_headers_for_visit,
)


class TestTreatmentRecordCreation:
    def test_create_when_visit_in_consult(self, api):
        """PRD §3.5: 'The visit must be in IN_CONSULT (otherwise
        ERR_INVALID_STATE).'"""
        owner, pet, visit = setup_visit_in_consult()
        headers = vet_headers_for_visit(visit["id"])
        res = api.create_treatment_record(
            create_treatment_record_payload(visit_id=visit["id"]),
            headers,
        )
        data = validate_success(res, expected_status=201)
        assert_treatment_record(data)
        assert data["status"] == "DRAFT"

    def test_create_blocked_when_visit_not_in_consult(self, api, drafting_vet_headers):
        """PRD §3.5: 'The visit must be in IN_CONSULT (otherwise
        ERR_INVALID_STATE).'"""
        owner, pet = setup_owner_and_pet()
        visit = create_visit(pet_id=pet["id"], severity_score=4)
        # Visit is in REGISTERED — not IN_CONSULT.
        res = api.create_treatment_record(
            create_treatment_record_payload(visit_id=visit["id"]),
            drafting_vet_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestTreatmentRecordFinalize:
    def test_finalize_requires_consent(self, api):
        """PRD §3.5: 'Three preconditions apply: consent_recorded must
        be true; the caller's X-User-ID must equal the visit's
        assigned_vet_id; and the visit must be in IN_CONSULT.'"""
        owner, pet, visit = setup_visit_in_consult()
        headers = vet_headers_for_visit(visit["id"])
        # Consent intentionally false at draft.
        tr = create_treatment_record(
            visit_id=visit["id"], consent_recorded=False,
        )
        res = api.finalize_treatment_record(tr["id"], headers)
        # PRD names the rule but does not commit to a specific error_id;
        # ERR_INVALID_STATE / ERR_VALIDATION_FAILED both faithful.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res, ["ERR_INVALID_STATE", "ERR_VALIDATION_FAILED"],
        )

    def test_finalize_appends_consult_line_to_bill(self, api, cashier_headers):
        """PRD §3.5: 'On success, three side effects fire: ... a CONSULT
        line item is appended to the visit's bill, which forces a
        recompute of provisional_total_cents (cascade hop 2).'"""
        from test_helpers import create_bill, recompute_bill
        owner, pet, visit = setup_visit_in_consult()
        # Create the bill BEFORE finalize so the cascade has a target.
        bill = create_bill(visit_id=visit["id"])
        tr = create_treatment_record(visit_id=visit["id"])
        finalize_treatment_record(visit_id=visit["id"], tr_id=tr["id"])
        # Bill should now have one CONSULT line.
        bill_after = get_success_data(
            api.recompute_bill(bill["id"], cashier_headers),
        )
        consult_lines = [
            li for li in bill_after["line_items"]
            if li.get("kind") == "CONSULT"
        ]
        assert len(consult_lines) >= 1, (
            f"Expected at least one CONSULT line after finalize, "
            f"got {bill_after['line_items']}"
        )

    def test_finalize_appends_to_pet_medical_history(self, api):
        """PRD §3.5: 'an entry of the form {visit_id, diagnosis_code,
        finalized_at} is appended to the pet's medical_history (cascade
        hop 1, ordered by finalization time ascending).'"""
        owner, pet, visit, tr = setup_visit_with_finalized_treatment(
            diagnosis_code="K30",
        )
        re_pet = get_pet(pet["id"])
        history = re_pet["medical_history"]
        assert any(
            h.get("visit_id") == visit["id"] and h.get("diagnosis_code") == "K30"
            for h in history
        ), (
            f"Expected medical_history to contain {{visit_id, diagnosis_code}} "
            f"snapshot, got {history}"
        )


class TestTreatmentRecordAmend:
    def test_amend_with_correct_version_succeeds(self, api):
        """PRD §3.5: 'A treatment record can be amended after finalization.
        The amend action is an update that requires the version field
        for OCC and accepts optional consultation_notes and optional
        treatment_plan.'

        PRD §3.5: 'On success, the record's status becomes AMENDED.'"""
        owner, pet, visit, tr = setup_visit_with_finalized_treatment()
        headers = vet_headers_for_visit(visit["id"])
        res = api.amend_treatment_record(
            tr["id"],
            amend_treatment_record_payload(
                version=tr["version"],
                consultation_notes="Updated notes after follow-up.",
            ),
            headers,
        )
        data = validate_success(res)
        assert data["status"] == "AMENDED"

    def test_amend_with_stale_version_rejected(self, api):
        """PRD §2.4: 'A mismatch is rejected with ERR_STALE_VERSION.'"""
        owner, pet, visit, tr = setup_visit_with_finalized_treatment()
        headers = vet_headers_for_visit(visit["id"])
        res = api.amend_treatment_record(
            tr["id"],
            amend_treatment_record_payload(
                version=tr["version"] + 99,
                consultation_notes="Stale version body.",
            ),
            headers,
        )
        validate_error(res, "ERR_STALE_VERSION")

    def test_amend_does_not_rewrite_medical_history_snapshot(self, api):
        """PRD §3.5: 'The pet's medical_history snapshot is not rewritten
        by an amend — the array is event-style append-only and the
        originally finalized entry stays as-is.'"""
        owner, pet, visit, tr = setup_visit_with_finalized_treatment(
            diagnosis_code="K30",
        )
        before = get_pet(pet["id"])["medical_history"]
        headers = vet_headers_for_visit(visit["id"])
        validate_success(
            api.amend_treatment_record(
                tr["id"],
                amend_treatment_record_payload(
                    version=tr["version"],
                    consultation_notes="Amended notes.",
                ),
                headers,
            )
        )
        after = get_pet(pet["id"])["medical_history"]
        # Snapshot for this finalized record (matched on visit_id) must
        # remain present and unchanged in count for this visit.
        before_for_visit = [h for h in before if h.get("visit_id") == visit["id"]]
        after_for_visit = [h for h in after if h.get("visit_id") == visit["id"]]
        assert before_for_visit == after_for_visit, (
            "medical_history snapshots for the visit must not change on amend"
        )
