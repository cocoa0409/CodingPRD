"""Corner tests covering case creation, intake validation, and basic reads."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_case_payload, reset_clock, create_case, create_triaged_case,
    NON_EXISTENT_UUID,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_case_creation_defaults_and_computed_fields(api):
    """PRD §3.1: "The new case enters `INTAKE` status. Its initial derived
    values are: `preservation_completeness_ratio` of 1.00 (vacuous compliance
    with no notices yet), `active_privileged_artifact_count` of 0,
    `open_remediation_count` of 0, `pattern_escalated` false, and a
    `case_priority_score` computed by the rule described in §3.10 below."
    PRD §3.1: "Upon creation the server assigns a `case_number` of the form
    `INV-<yyyy>-<NNNN>` — for example `INV-2026-0001` — where the four-digit
    sequence is zero-padded and ordered by `created_at` across all cases
    created in the same calendar year."
    PRD §3.10: "The raw score is 10 times the severity weight (`LOW` 1,
    `MEDIUM` 2, `HIGH` 3, `CRITICAL` 4)... The `priority_tier` is `URGENT`
    when the raw score is at least 40, `ELEVATED` when it is at least 20 and
    below 40, and `ROUTINE` when it is below 20."

    Design: Corner/entities/case_creation_defaults_and_computed_fields
    """
    reset_clock()
    payload = create_case_payload(
        title="First Case", allegation_category="FRAUD", severity="HIGH",
        department="Finance", lead_investigator_id="inv-lead-1",
    )
    resp = api.create_case(payload, IC)
    case = validate_success(resp, expected_status=201)
    assert case["status"] == "INTAKE"
    assert case["version"] == 1
    assert case["case_number"] == "INV-2026-0001"
    assert case["pattern_escalated"] is False
    assert case["active_privileged_artifact_count"] == 0
    assert case["open_remediation_count"] == 0
    # HIGH severity weight = 3 => raw 30 => ELEVATED
    assert case["case_priority_score"] == 30
    assert case["priority_tier"] == "ELEVATED"
    # Vacuous compliance — no notices yet
    assert case["preservation_completeness_ratio"] == 1.00


def test_case_missing_required_field_returns_400(api):
    """PRD §3.1: "Creation requires `title`, `allegation_category`, `severity`,
    and `lead_investigator_id`; `description` and `department` are optional at
    this stage."
    PRD §5: `ERR_MISSING_REQUIRED_FIELD` maps to HTTP 400.

    Design: Corner/entities/case_missing_required_field_returns_400
    """
    reset_clock()
    payload = {
        "allegation_category": "FRAUD",
        "severity": "HIGH",
        "lead_investigator_id": "inv-lead-1",
    }
    resp = api.create_case(payload, IC)
    validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_FIELD, expected_status=400)
    # No row persisted
    data, meta = validate_paginated(api.list_cases(IC))
    assert meta["total_count"] == 0


def test_case_invalid_enum_rejected(api):
    """PRD §3.1: "The `severity` is one of `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`"
    PRD §5: `ERR_VALIDATION` maps to HTTP 400.

    Design: Corner/entities/case_invalid_enum_rejected
    """
    reset_clock()
    payload = create_case_payload(
        title="Bad Enum", allegation_category="FRAUD", severity="EXTREME",
        lead_investigator_id="inv-lead-1",
    )
    resp = api.create_case(payload, IC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_get_case_not_found_returns_404(api):
    """PRD §2.10: "If a parent id does not exist, the request fails with
    `ERR_NOT_FOUND` (HTTP 404) before any child id is consulted."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    reset_clock()
    resp = api.get_case(NON_EXISTENT_UUID, INV)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_system_fields_input_ignored(api):
    """PRD §2.4: "Every persisted resource carries `id` as a server-minted
    UUID with no type prefix. Every resource also carries `created_at` and
    `updated_at` as ISO 8601 UTC timestamps with three fractional digits, and
    an integer `version` starting at 1 that increments by exactly 1 on each
    mutation of that row."
    PRD §2.6: "At server startup the clock reads exactly
    `2026-05-01T00:00:00Z`; before any clock-set call it never falls back to
    wall-clock time."

    Design: Corner/entities/system_fields_input_ignored
    """
    reset_clock("2026-05-01T00:00:00Z")
    payload = create_case_payload(
        title="SysFields", allegation_category="BRIBERY", severity="LOW",
        department="Sales", lead_investigator_id="inv-lead-1",
        id="client-supplied", version=99,
    )
    resp = api.create_case(payload, IC)
    case = validate_success(resp, expected_status=201)
    assert case["id"] != "client-supplied"
    assert case["version"] == 1
    assert case["created_at"] == "2026-05-01T00:00:00Z"


def test_allegation_anonymous_with_reporter_ref_rejected(api):
    """PRD §3.1: "When `is_anonymous` is true, `reporter_ref` must be null —
    providing one is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/allegation_anonymous_with_reporter_ref_rejected
    """
    reset_clock()
    case = create_case(title="Anon Case", allegation_category="HARASSMENT",
                       severity="MEDIUM", department="Ops")
    payload = {
        "reporter_channel": "ANONYMOUS_PORTAL",
        "is_anonymous": True,
        "reporter_ref": "rep-9",
        "narrative": "x",
    }
    resp = api.create_allegation(case["id"], payload, IC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_evidence_custodian_mismatch_rejected(api):
    """PRD §3.4: "The supplied `custodian_ref` must equal the scope's
    `custodian_ref`, and `size_bytes` must be greater than zero — violations
    are rejected with `ERR_VALIDATION`."

    Design: Corner/entities/evidence_custodian_mismatch_rejected
    """
    from test_helpers import (
        create_case_in_fieldwork, add_acknowledged_notice,
        create_collection_scope_payload, create_evidence_item_payload,
        make_investigator_headers, make_manager_headers, TEST_DEFAULTS,
        create_evidence_item_payload,
    )
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="EvCase", allegation_category="FRAUD", severity="HIGH",
        department="Finance",
    )
    case = bundle["case"]
    notice = add_acknowledged_notice(case["id"], custodian_ref="EMP-100")
    scope_payload = create_collection_scope_payload(
        custodian_ref="EMP-100", data_source="EMAIL",
        preservation_notice_id=notice["id"],
    )
    scope = get_success_data(api.create_collection_scope(case["id"], scope_payload, INV))
    mgr = make_manager_headers(TEST_DEFAULTS["APPROVER_ID"])
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "APPROVED"}, mgr))
    get_success_data(api.transition_collection_scope(scope["id"], {"to_status": "IN_PROGRESS"}, inv1))
    bad_ev = create_evidence_item_payload(
        custodian_ref="EMP-999", hash_value="hx", size_bytes=1000,
    )
    resp = api.create_evidence_item(scope["id"], bad_ev, INV)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)
