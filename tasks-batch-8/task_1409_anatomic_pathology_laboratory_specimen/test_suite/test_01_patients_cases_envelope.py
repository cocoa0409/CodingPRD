"""Patient registration, case intake defaults, envelope, pagination, and
child-discovery listing behavior."""
from test_helpers import (
    ADMIN_HEADERS,
    HISTOTECH_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    accession_specimen,
    assert_case,
    assert_instant_equal,
    assert_specimen,
    create_block,
    create_case,
    create_patient,
    gross_specimen,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_patient_create_missing_required_mrn_returns_400(api):
    """PRD §3.1: "A `LabAdmin` registers each patient once, supplying the medical
    record number `mrn`, the patient's `full_name`, and `date_of_birth` in
    `YYYY-MM-DD` form."
    PRD §2.9: "The priority-3 shape validation rejects with `ERR_INVALID_REQUEST`
    (HTTP 400) on any of: a missing required field, an invalid enum member, an
    out-of-range number such as a `container_count` below 1 or a `consumption_pct`
    of 0 or less"

    Design: Corner/entities/patient_create_missing_required_mrn_returns_400
    """
    resp = api.create_patient(
        {"full_name": "No Mrn", "date_of_birth": "1990-01-01"}, ADMIN_HEADERS
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_patient_duplicate_mrn_rejected(api):
    """PRD §3.1: "The `mrn` is unique across all patients and must be non-empty;
    a duplicate registration is rejected with `ERR_DUPLICATE_MRN` (HTTP 409)."

    Design: Corner/entities/patient_duplicate_mrn_rejected
    """
    create_patient(mrn="MRN-DUP", full_name="First", date_of_birth="1990-01-01")
    resp = api.create_patient(
        {"mrn": "MRN-DUP", "full_name": "Second", "date_of_birth": "1991-02-02"},
        ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MRN)


def test_case_create_applies_defaults_and_initial_deadline(api, lab_admin_headers):
    """PRD §3.1: "The turnaround mode selects the deadline variant: `CALENDAR`,
    the default when omitted, counts plain clock hours with weekends and nights
    included"
    PRD §3.1: "Every case begins life in `OPEN` status with `complexity_class`
    `SIMPLE` and no assigned pathologist (`assigned_pathologist_id` null), no
    signed report (`current_signed_report_id` null), no amender
    (`amender_pathologist_id` null), no finalization timestamp (`finalized_at`
    null), and an `open_critical_discrepancy_count` of zero."
    PRD §3.1: "The deadline itself rests on `tat_base_time`: the earliest
    `received_datetime` among the case's specimens that are not `REJECTED`,
    falling back to the case's `created_at` when no such specimen exists — which
    is exactly the situation at creation, so a fresh case's initial
    `turnaround_deadline` is computed from its creation timestamp."
    PRD §2.5: "At startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`, and it never silently falls back to wall time."

    Design: Corner/entities/case_create_applies_defaults_and_initial_deadline
    """
    patient = create_patient(mrn="MRN-D1", full_name="Defaults")
    resp = api.create_case(
        {"patient_id": patient["id"], "subspecialty": "BREAST"}, lab_admin_headers
    )
    case = validate_success(resp, expected_status=201)
    assert_case(case)
    assert case["tat_mode"] == "CALENDAR", "omitted tat_mode must default to CALENDAR"
    assert case["status"] == "OPEN"
    assert case["complexity_class"] == "SIMPLE"
    assert case["complexity_score"] == 0.0
    assert case["assigned_pathologist_id"] is None
    assert case["current_signed_report_id"] is None
    assert case["amender_pathologist_id"] is None
    assert case["finalized_at"] is None
    assert case["open_critical_discrepancy_count"] == 0
    assert case["tat_breached"] is False
    assert case["version"] == 1
    # Startup logical clock is 2026-08-01T00:00:00Z; SIMPLE allowance is 48h.
    assert_instant_equal(case["created_at"], "2026-08-01T00:00:00Z", "case.created_at")
    assert_instant_equal(
        case["turnaround_deadline"], "2026-08-03T00:00:00Z", "case.turnaround_deadline"
    )


def test_specimen_accession_computed_fields(api):
    """PRD §2.4: "Beyond the UUID, each accessioned specimen also receives a
    human-facing `accession_number`, minted by the server in the format `SP`
    followed by the two-digit year, a hyphen, and a six-digit sequence number
    that restarts each calendar year (for example, `SP26-000001`)."
    PRD §3.2: "The clinical payload comprises `specimen_type` — one of `BIOPSY`,
    `EXCISION`, `RESECTION`, or `CYTOLOGY` — free-text `anatomical_site`, the
    `collection_datetime` when the tissue left the patient, the
    `received_datetime` when the laboratory took custody, a `container_count` of
    at least 1, and an optional `fixative_type` of `FORMALIN`, `SALINE`,
    `FROZEN`, or `NONE` that defaults to `FORMALIN`."
    PRD §3.2: "On acceptance the server mints the `accession_number` (§2.4),
    computes `cold_ischemia_minutes` as the whole minutes from collection to
    receipt truncated toward zero — a value that later gates cold-sensitive
    stains — and sets the specimen's `status` to `ACCESSIONED`"

    Design: Corner/entities/specimen_accession_computed_fields
    """
    patient = create_patient(mrn="MRN-D2", full_name="Computed")
    case = create_case(patient["id"], subspecialty="GI")
    resp = api.accession_specimen(
        case["id"],
        {
            "patient_mrn": "MRN-D2",
            "patient_dob": "1980-01-01",
            "specimen_type": "BIOPSY",
            "anatomical_site": "Colon",
            "collection_datetime": "2026-08-03T09:30:00Z",
            "received_datetime": "2026-08-03T10:00:00Z",
            "container_count": 1,
        },
        HISTOTECH_HEADERS,
    )
    specimen = validate_success(resp, expected_status=201)
    assert_specimen(specimen)
    # First accession of the default-clock year 2026.
    assert specimen["accession_number"] == "SP26-000001"
    assert specimen["cold_ischemia_minutes"] == 30, "30 whole minutes 09:30 -> 10:00"
    assert specimen["fixative_type"] == "FORMALIN", "omitted fixative defaults to FORMALIN"
    assert specimen["status"] == "ACCESSIONED"
    assert specimen["gross_description"] is None
    assert specimen["reject_reason"] is None


def test_entity_get_not_found_returns_404(api):
    """PRD §2.6: "Any endpoint whose path nests one resource beneath another
    validates path identifiers strictly left to right, returning `ERR_NOT_FOUND`
    (HTTP 404) for the first path identifier that does not resolve, and only
    then checks identifiers referenced in the request body, each unresolved
    reference likewise producing `ERR_NOT_FOUND`."

    Design: Corner/entities/entity_get_not_found_returns_404
    """
    resp = api.get_case(NON_EXISTENT_UUID, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_case_list_pagination_envelope(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` caps the
    number of returned items: it defaults to 10, with a minimum of 1 and a
    maximum of 100. `offset` skips a number of items and defaults to 0."
    PRD §2.3: "The `meta` envelope of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/case_list_pagination_envelope
    """
    patient = create_patient(mrn="MRN-D3", full_name="Paged")
    for _ in range(3):
        create_case(patient["id"], subspecialty="GI")

    page1, meta1 = validate_paginated(
        api.list_cases(ADMIN_HEADERS, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2, f"page 1 must hold 2 items, got {len(page1)}"
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0
    assert str(meta1.get("api_request_id", "")).startswith("req_")

    page2, meta2 = validate_paginated(
        api.list_cases(ADMIN_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1, f"page 2 must hold exactly 1 item, got {len(page2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_fk_reverse_reachability_lists_children(api):
    """PRD §2.3: "List endpoints also accept resource-specific filter parameters,
    each matching on exact equality: the case list accepts `patient_id`,
    `assigned_pathologist_id`, `amender_pathologist_id`, `status`, and
    `tat_breached`; the specimen list accepts `case_id` and `status`; the block
    list accepts `specimen_id` and `status`"

    Design: Corner/entities/fk_reverse_reachability_lists_children
    """
    patient = create_patient(mrn="MRN-D4", full_name="Fk")
    case = create_case(patient["id"], subspecialty="GI")
    specimen = accession_specimen(case["id"], patient_mrn="MRN-D4")
    gross_specimen(specimen["id"])
    block_a = create_block(specimen["id"], block_label="A1")
    block_b = create_block(specimen["id"], block_label="A2")

    specimens, s_meta = validate_paginated(
        api.list_specimens(ADMIN_HEADERS, params={"case_id": case["id"]})
    )
    assert s_meta["total_count"] == 1
    assert specimens[0]["id"] == specimen["id"]

    blocks, b_meta = validate_paginated(
        api.list_blocks(ADMIN_HEADERS, params={"specimen_id": specimen["id"]})
    )
    assert b_meta["total_count"] == 2
    returned_ids = {b["id"] for b in blocks}
    assert returned_ids == {block_a["id"], block_b["id"]}
    for b in blocks:
        assert b["specimen_id"] == specimen["id"]
