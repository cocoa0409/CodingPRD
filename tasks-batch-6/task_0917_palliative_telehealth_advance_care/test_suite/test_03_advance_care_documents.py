"""Advance care documents: signatures, jurisdiction requirements and execution."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assert_document, assert_same_instant
from test_helpers import factories as f
from test_helpers.fixtures import (
    PHYSICIAN,
    SOCIAL_WORKER,
    designate_surrogate,
    draft_document,
    enroll_patient,
    patient_version,
    sign_document,
    witnessed_document,
)


# ---------------------------------------------------------------------------
# The self-referential supersession edge is queryable in both directions
# ---------------------------------------------------------------------------
def test_documents_can_be_filtered_by_the_document_they_supersede(api):
    """PRD 2.3: "The filters are `patient_id` (care plans, advance care documents,
    code-status orders, symptom assessments, conferences, escalations, claims,
    equipment orders, hospice elections), `status` (surrogate designations,
    medication orders, care plans, hospice elections, advance care documents,
    code-status orders, conferences, escalations, claims, equipment orders),
    `triage_status` (symptom assessments), `care_plan_id` (symptom assessments),
    `supersedes_document_id` and `document_type` (advance care documents),
    `source_document_id` (code-status orders), `decision_maker_id` and
    `conference_type` (conferences), `symptom_assessment_id` (escalations),
    `conference_id` (claims), and `inventory_item_id` (equipment orders)."
    PRD 3.3: "The new row opens in `status` `DRAFT` with
    `witness_signature_count`, `notary_signature_count`,
    `physician_signature_count` and `patient_or_surrogate_signature_count` all at
    0, `execution_ready` false, and an empty `signature_log`."

    Design: Corner/entities/advance_care_document_supersedes_filter_returns_the_superseding_child
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Fia Lundgren")

    first = draft_document(patient["id"], document_type="LIVING_WILL", stated_code_status="DNR")
    second = draft_document(
        patient["id"],
        document_type="LIVING_WILL",
        stated_code_status="DNR_DNI",
        supersedes_document_id=first["id"],
    )
    assert_document(first)
    assert first["signature_log"] == []
    assert first["execution_ready"] is False

    rows, meta = validate_paginated(
        api.list_documents(SOCIAL_WORKER, params={"supersedes_document_id": first["id"]})
    )

    assert len(rows) == 1, (
        f"only the superseding child should match, got {[r['id'] for r in rows]}"
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]
    assert rows[0]["status"] == "DRAFT"
    assert rows[0]["execution_ready"] is False


# ---------------------------------------------------------------------------
# Jurisdiction decides what "ready" means
# ---------------------------------------------------------------------------
def test_two_witnesses_execute_under_one_jurisdiction_and_not_the_other(api):
    """PRD 3.3: "Under `JUR_TWO_WITNESS` the document needs
    `witness_signature_count` of at least 2 and notary signatures are ignored
    entirely, so a notarised document with no witnesses is **not** ready. Under
    `JUR_NOTARY` the document needs `notary_signature_count` of at least 1 and
    witness signatures are ignored entirely, so the same document bearing two
    witnesses and no notary is **not** ready."
    PRD 3.3: "Executing stamps `executed_at` from the logical clock, sets
    `reattest_due_at` to exactly 365 days after `executed_at`, moves the document
    `PENDING_EXECUTION → EXECUTED`, and increments the patient's `version` by 1."

    Design: Corner/calculations/document_execution_requirement_two_witness_and_notary_variants_diverge
    """
    witness_patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Suri Kang",
        jurisdiction_code="JUR_TWO_WITNESS",
    )
    notary_patient, _ = enroll_patient(
        clock=None,
        full_name="Tomas Reyes",
        jurisdiction_code="JUR_NOTARY",
        attending_clinician_user_id="u_attending_2",
    )

    witness_doc = witnessed_document(
        witness_patient["id"], witnesses=2, document_type="LIVING_WILL", stated_code_status="DNR"
    )
    notary_doc = witnessed_document(
        notary_patient["id"], witnesses=2, document_type="LIVING_WILL", stated_code_status="DNR"
    )

    assert witness_doc["execution_ready"] is True
    assert witness_doc["status"] == "PENDING_EXECUTION"
    assert notary_doc["execution_ready"] is False, (
        "two witnesses do not satisfy a notary jurisdiction"
    )
    assert notary_doc["status"] == "DRAFT"

    executed = validate_success(
        api.execute_document(
            witness_doc["id"],
            {"expected_patient_version": patient_version(witness_patient["id"])},
            PHYSICIAN,
        )
    )
    assert executed["status"] == "EXECUTED"
    assert_same_instant(
        executed["executed_at"], "2026-06-01T00:00:00Z", "AdvanceCareDocument.executed_at"
    )
    assert_same_instant(
        executed["reattest_due_at"],
        "2027-06-01T00:00:00Z",
        "AdvanceCareDocument.reattest_due_at",
    )

    rejected = api.execute_document(
        notary_doc["id"],
        {"expected_patient_version": patient_version(notary_patient["id"])},
        PHYSICIAN,
    )
    validate_error(rejected, ApiErrorId.ERR_EXECUTION_REQUIREMENT_UNMET.value, 422)

    still_draft = validate_success(api.get_document(notary_doc["id"], SOCIAL_WORKER))
    assert still_draft["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Witness segregation
# ---------------------------------------------------------------------------
def test_a_surrogate_or_the_attending_clinician_may_not_witness(api):
    """PRD 3.3: "A `WITNESS` signature is refused with `ERR_WITNESS_CONFLICT` when
    its `signer_user_id` matches the patient's `attending_clinician_user_id`, or
    matches the `person_user_id` of any designation for this patient sitting in
    `PROPOSED` or `ACTIVE`, or matches the `person_user_id` of any designation for
    this patient whose `is_beneficiary` is true — and that last disqualification
    applies whatever the designation's `status` is, including `REVOKED`."
    PRD 3.3: "The append adds one entry to `signature_log` — an object holding
    `signature_type`, `signer_user_id` and `signed_at`, where `signed_at` is the
    current logical clock — and increments exactly the one counter that matches: a
    `WITNESS` signature raises `witness_signature_count`, a `NOTARY` signature
    raises `notary_signature_count`, a `SIGNING_PHYSICIAN` signature raises
    `physician_signature_count`, and a `PATIENT_OR_SURROGATE` signature raises
    `patient_or_surrogate_signature_count`."

    Design: Corner/validations/witness_who_is_an_active_surrogate_returns_witness_conflict
    """
    patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Zoe Marchand",
        attending_clinician_user_id="u_attending_1",
    )
    designate_surrogate(
        patient["id"],
        person_user_id="u_spouse_1",
        person_name="Ruth Marchand",
        relationship="SPOUSE",
        is_beneficiary=True,
    )
    document = draft_document(patient["id"], document_type="LIVING_WILL", stated_code_status="DNR")

    validate_error(
        api.add_document_signature(
            document["id"],
            f.signature_payload("WITNESS", "u_spouse_1"),
            SOCIAL_WORKER,
        ),
        ApiErrorId.ERR_WITNESS_CONFLICT.value,
        422,
    )
    validate_error(
        api.add_document_signature(
            document["id"],
            f.signature_payload("WITNESS", "u_attending_1"),
            SOCIAL_WORKER,
        ),
        ApiErrorId.ERR_WITNESS_CONFLICT.value,
        422,
    )

    accepted = validate_success(
        api.add_document_signature(
            document["id"],
            f.signature_payload("WITNESS", "u_witness_1"),
            SOCIAL_WORKER,
        )
    )
    assert accepted["witness_signature_count"] == 1, (
        "only the one accepted witness signature may be counted"
    )
    assert accepted["execution_ready"] is False
    assert accepted["status"] == "DRAFT"
    assert len(accepted["signature_log"]) == 1


# ---------------------------------------------------------------------------
# Rung ordering between the jurisdiction check and the POLST check
# ---------------------------------------------------------------------------
def test_jurisdiction_requirement_is_reported_before_the_polst_signature_check(api):
    """PRD 2.5: "**Jurisdiction execution requirement.** At execution, a patient
    governed by `JUR_TWO_WITNESS` requires the document's
    `witness_signature_count` to be at least 2, and a patient governed by
    `JUR_NOTARY` requires its `notary_signature_count` to be at least 1. Both
    comparisons are inclusive at the required count. Otherwise
    `ERR_EXECUTION_REQUIREMENT_UNMET` (422)."
    PRD 2.5: "**POLST signatures.** A document whose `document_type` is `POLST`
    additionally requires `physician_signature_count` to be at least 1 and
    `patient_or_surrogate_signature_count` to be at least 1. Otherwise
    `ERR_SIGNATURE_INCOMPLETE` (422)."

    Design: Corner/validations/jurisdiction_requirement_outranks_the_polst_signature_check
    """
    witness_patient, _ = enroll_patient(
        clock="2026-06-01T00:00:00Z",
        full_name="Ana Whitlock",
        jurisdiction_code="JUR_TWO_WITNESS",
    )
    polst_w = draft_document(
        witness_patient["id"], document_type="POLST", stated_code_status="DNR"
    )
    sign_document(polst_w["id"], "WITNESS", "u_witness_1")
    sign_document(polst_w["id"], "SIGNING_PHYSICIAN", "u_physician_1", headers=PHYSICIAN)
    sign_document(polst_w["id"], "PATIENT_OR_SURROGATE", "u_patient_w")

    notary_patient, _ = enroll_patient(
        clock=None,
        full_name="Ben Nakamura",
        jurisdiction_code="JUR_NOTARY",
        attending_clinician_user_id="u_attending_2",
    )
    polst_n = draft_document(
        notary_patient["id"], document_type="POLST", stated_code_status="DNR"
    )
    sign_document(polst_n["id"], "NOTARY", "u_notary_1")
    sign_document(polst_n["id"], "SIGNING_PHYSICIAN", "u_physician_1", headers=PHYSICIAN)

    validate_error(
        api.execute_document(
            polst_w["id"],
            {"expected_patient_version": patient_version(witness_patient["id"])},
            PHYSICIAN,
        ),
        ApiErrorId.ERR_EXECUTION_REQUIREMENT_UNMET.value,
        422,
    )
    validate_error(
        api.execute_document(
            polst_n["id"],
            {"expected_patient_version": patient_version(notary_patient["id"])},
            PHYSICIAN,
        ),
        ApiErrorId.ERR_SIGNATURE_INCOMPLETE.value,
        422,
    )

    after_w = validate_success(api.get_document(polst_w["id"], SOCIAL_WORKER))
    after_n = validate_success(api.get_document(polst_n["id"], SOCIAL_WORKER))
    assert after_w["status"] == "DRAFT"
    assert after_n["status"] == "DRAFT"
    assert after_n["notary_signature_count"] == 1
    assert after_n["patient_or_surrogate_signature_count"] == 0
