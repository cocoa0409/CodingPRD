"""Specimen accession safety checks, grossing/rejection rules, and the
rejection-driven case recomputation."""
from test_helpers import (
    ADMIN_HEADERS,
    HISTOTECH_HEADERS,
    PA_HEADERS,
    ApiErrorId,
    accession_specimen,
    assert_instant_equal,
    create_block,
    create_case,
    create_patient,
    get_case,
    get_specimen,
    gross_specimen,
    reject_specimen,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_accession_patient_identifier_mismatch_rejected(api):
    """PRD §3.2: "The two identifiers must exactly match the `mrn` and
    `date_of_birth` of the patient who owns the parent case; any mismatch is
    rejected with `ERR_PATIENT_IDENTIFIER_MISMATCH` (HTTP 422)."

    Design: Corner/validations/accession_patient_identifier_mismatch_rejected
    """
    patient = create_patient(mrn="MRN-V1", full_name="Val One", date_of_birth="1980-01-01")
    case = create_case(patient["id"], subspecialty="GI")
    resp = api.accession_specimen(
        case["id"],
        {
            "patient_mrn": "MRN-V1",
            "patient_dob": "1980-01-02",
            "specimen_type": "BIOPSY",
            "anatomical_site": "Colon",
            "collection_datetime": "2026-08-03T09:00:00Z",
            "received_datetime": "2026-08-03T10:00:00Z",
            "container_count": 1,
        },
        HISTOTECH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_PATIENT_IDENTIFIER_MISMATCH)
    # No Specimen row was created for the case.
    _specimens, meta = validate_paginated(
        api.list_specimens(ADMIN_HEADERS, params={"case_id": case["id"]})
    )
    assert meta["total_count"] == 0


def test_accession_received_before_collection_rejected(api):
    """PRD §3.2: "A `received_datetime` earlier than `collection_datetime` is
    rejected with `ERR_COLLECTION_AFTER_RECEIVED` (HTTP 422)."

    Design: Corner/validations/accession_received_before_collection_rejected
    """
    patient = create_patient(mrn="MRN-V2", full_name="Val Two")
    case = create_case(patient["id"], subspecialty="GI")
    resp = api.accession_specimen(
        case["id"],
        {
            "patient_mrn": "MRN-V2",
            "patient_dob": "1980-01-01",
            "specimen_type": "BIOPSY",
            "anatomical_site": "Colon",
            "collection_datetime": "2026-08-03T10:00:00Z",
            "received_datetime": "2026-08-03T09:00:00Z",
            "container_count": 1,
        },
        HISTOTECH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_COLLECTION_AFTER_RECEIVED)


def test_specimen_gross_after_reject_rejected(api):
    """PRD §3.2: "The specimen must still be `ACCESSIONED` — grossing or
    rejecting a specimen in any other status is rejected with
    `ERR_SPECIMEN_NOT_ACCESSIONED` (HTTP 409) — and the parent case must be in
    `OPEN` or `WORKUP`."
    PRD §3.2: "When every specimen of a case is `REJECTED` and the case is still
    `OPEN`, the case auto-transitions to `CANCELLED` with the standard
    cancellation cascade (§3.6)."

    Design: Corner/state_machines/specimen_gross_after_reject_rejected
    """
    patient = create_patient(mrn="MRN-S2", full_name="Sm Two")
    case = create_case(patient["id"], subspecialty="GI")
    sp1 = accession_specimen(
        case["id"], patient_mrn="MRN-S2", anatomical_site="Skin", container_count=2
    )
    accession_specimen(case["id"], patient_mrn="MRN-S2", anatomical_site="Arm")
    reject_specimen(sp1["id"], reason="no tissue in container")

    resp = api.gross_specimen(
        sp1["id"], {"gross_description": "too late"}, PA_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_ACCESSIONED)
    after = get_specimen(sp1["id"])
    assert after["status"] == "REJECTED"
    assert after["gross_description"] is None, "failed gross must not record a description"
    # Only one of two specimens is rejected, so the case stays OPEN.
    assert get_case(case["id"])["status"] == "OPEN"


def test_case_auto_cancel_when_all_specimens_rejected(api):
    """PRD §3.2: "When every specimen of a case is `REJECTED` and the case is
    still `OPEN`, the case auto-transitions to `CANCELLED` with the standard
    cancellation cascade (§3.6)."
    PRD §3.2: "Rejection, by contrast, is a `Histotech` action that moves an
    `ACCESSIONED` specimen to `REJECTED`, recording the supplied `reason` in
    `reject_reason`."

    Design: Corner/state_machines/case_auto_cancel_when_all_specimens_rejected
    """
    patient = create_patient(mrn="MRN-S8", full_name="Sm Eight")
    case = create_case(patient["id"], subspecialty="GI")
    specimen = accession_specimen(
        case["id"],
        patient_mrn="MRN-S8",
        specimen_type="CYTOLOGY",
        anatomical_site="Bile duct brushing",
    )
    resp = api.reject_specimen(
        specimen["id"], {"reason": "acellular"}, HISTOTECH_HEADERS
    )
    rejected = validate_success(resp, expected_status=200)
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "acellular"
    assert get_case(case["id"])["status"] == "CANCELLED", (
        "all specimens rejected while OPEN must auto-cancel the case"
    )


def test_tat_base_moves_when_earliest_specimen_rejected(api):
    """PRD §3.1: "The deadline itself rests on `tat_base_time`: the earliest
    `received_datetime` among the case's specimens that are not `REJECTED`,
    falling back to the case's `created_at` when no such specimen exists"
    PRD §3.2: "A rejection shrinks the case: `tat_base_time` and
    `turnaround_deadline` are recomputed excluding the rejected specimen, and
    `complexity_score` is recomputed likewise."

    Design: Corner/calculations/tat_base_moves_when_earliest_specimen_rejected
    """
    patient = create_patient(mrn="MRN-C5", full_name="Calc Five")
    case = create_case(patient["id"], subspecialty="GI")
    sp1 = accession_specimen(
        case["id"],
        patient_mrn="MRN-C5",
        collection_datetime="2026-08-03T09:00:00Z",
        received_datetime="2026-08-03T10:00:00Z",
    )
    accession_specimen(
        case["id"],
        patient_mrn="MRN-C5",
        anatomical_site="Ileum",
        collection_datetime="2026-08-04T09:00:00Z",
        received_datetime="2026-08-04T10:00:00Z",
    )
    before = get_case(case["id"])
    # SIMPLE allowance is 48h from the earliest receipt 2026-08-03T10:00:00Z.
    assert_instant_equal(
        before["turnaround_deadline"], "2026-08-05T10:00:00Z", "pre-reject deadline"
    )

    resp = api.reject_specimen(sp1["id"], {"reason": "container leaked"}, HISTOTECH_HEADERS)
    validate_success(resp, expected_status=200)

    after = get_case(case["id"])
    assert_instant_equal(after["tat_base_time"], "2026-08-04T10:00:00Z", "tat_base_time")
    assert_instant_equal(
        after["turnaround_deadline"], "2026-08-06T10:00:00Z", "post-reject deadline"
    )
    assert after["status"] == "OPEN", "the surviving specimen keeps the case OPEN"


def test_reject_specimen_with_blocks_rejected(api):
    """PRD §3.2: "Rejection is refused once any block exists for the specimen,
    surfacing `ERR_BLOCKS_EXIST` (HTTP 409)."

    Design: Corner/validations/reject_specimen_with_blocks_rejected
    """
    patient = create_patient(mrn="MRN-VD", full_name="Val Thirteen")
    case = create_case(patient["id"], subspecialty="GI")
    specimen = accession_specimen(case["id"], patient_mrn="MRN-VD")
    gross_specimen(specimen["id"])
    create_block(specimen["id"], block_label="A1")

    resp = api.reject_specimen(
        specimen["id"], {"reason": "late rejection"}, HISTOTECH_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_BLOCKS_EXIST)
    assert get_specimen(specimen["id"])["status"] == "PROCESSING", (
        "the first block moved the specimen to PROCESSING and rejection changed nothing"
    )
