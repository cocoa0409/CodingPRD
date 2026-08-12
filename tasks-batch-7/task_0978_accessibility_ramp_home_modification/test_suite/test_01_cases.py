"""Case intake, retrieval, listing, defaults, and immediate-consistency claims."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_case,
    create_case, create_case_payload, set_clock, get_case,
)

IC = TEST_USERS["intake_coordinator_headers"]
PM = TEST_USERS["project_manager_headers"]


def test_case_creation_returns_201_with_initial_state(api):
    """PRD §3.1: "The new case starts in `INTAKE` status with its computed fields
    initialized: all ledger totals at zero and `funding_posture` at `UNFUNDED`."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is
    created and increments by one on every mutation."

    Design: Corner/entities/case_creation_returns_201_with_initial_state
    """
    set_clock()
    res = api.create_case(
        {"client_name": "Ann Bell", "client_address": "1 Start St", "client_phone": "555-0201"}, IC)
    case = validate_success(res, 201)
    assert_case(case)
    assert case["status"] == "INTAKE"
    assert case["version"] == 1
    assert case["total_quoted_cents"] == 0
    assert case["total_funded_cents"] == 0
    assert case["total_billed_cents"] == 0
    assert case["total_paid_cents"] == 0
    assert case["balance_due_cents"] == 0
    assert case["funding_posture"] == "UNFUNDED"
    assert is_valid_uuid(case["id"])


def test_case_get_returns_stored_fields(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §2.4: "`created_at` is an ISO 8601 UTC timestamp with three fractional
    digits recording when the resource was created. `updated_at` is the same kind
    of timestamp, refreshed on every mutation of the resource."

    Design: Corner/entities/case_get_returns_stored_fields
    """
    case = create_case(client_name="Bob Cray", client_address="2 Read Rd",
                       client_phone="555-0202", referral_source="VA")
    got = validate_success(api.get_case(case["id"], IC), 200)
    assert_case(got)
    assert got["client_name"] == "Bob Cray"
    assert got["client_address"] == "2 Read Rd"
    assert got["referral_source"] == "VA"
    assert is_iso8601_timestamp(got["created_at"])
    assert is_iso8601_timestamp(got["updated_at"])


def test_case_list_pagination_envelope_fields(api):
    """PRD §2.3: "List responses report `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object, where `total_count` is the full count of
    matching records and `has_more` indicates whether further records exist beyond
    the returned page."

    Design: Corner/entities/case_list_pagination_envelope_fields
    """
    for i in range(3):
        create_case(client_name=f"C {i}", client_address=f"3{i} List Ave",
                    client_phone=f"555-020{i}")
    data, meta = validate_paginated(api.list_cases(IC, params={"limit": 2, "offset": 0}))
    assert len(data) == 2, f"expected exactly 2 items for limit=2, got {len(data)}"
    assert meta["total_count"] >= 3
    assert meta["has_more"] is True


def test_case_get_unknown_id_returns_404(api):
    """PRD §2.7: "The not-found errors are: `ERR_CASE_NOT_FOUND` for a case,
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_QUOTE_NOT_FOUND` for a
    quote, `ERR_FUNDING_SOURCE_NOT_FOUND` for a funding source, `ERR_JOB_NOT_FOUND`
    for an installation job, `ERR_RAMP_NOT_FOUND` for a rental ramp,
    `ERR_UNIT_NOT_FOUND` for an inventory unit, `ERR_INSPECTION_NOT_FOUND` for an
    inspection, `ERR_INVOICE_NOT_FOUND` for an invoice, `ERR_CLAIM_NOT_FOUND` for
    a warranty claim, `ERR_CONSULT_NOT_FOUND` for an OT consultation, and
    `ERR_SCHEDULE_NOT_FOUND` for a reassessment schedule — each with HTTP 404."

    Design: Corner/entities/case_get_unknown_id_returns_404
    """
    res = api.get_case(NON_EXISTENT_UUID, IC)
    validate_error(res, ApiErrorId.ERR_CASE_NOT_FOUND, expected_status=404)


def test_case_create_missing_client_name_returns_400(api):
    """PRD §2.6: "A request that is malformed, missing required fields, or
    carrying invalid values is rejected as `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "An `IntakeCoordinator` opens a case by supplying the client's
    `client_name`, `client_address`, and `client_phone`, plus an optional
    `referral_source` drawn from `PHYSICIAN`, `OT`, `VA`, `SELF`, and `AGENCY`;
    when no referral source is supplied it defaults to `SELF`."

    Design: Corner/entities/case_create_missing_client_name_returns_400
    """
    res = api.create_case({"client_address": "4 Missing St", "client_phone": "555-0206"}, IC)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_case_referral_source_defaults_to_self(api):
    """PRD §3.1: "An `IntakeCoordinator` opens a case by supplying the client's
    `client_name`, `client_address`, and `client_phone`, plus an optional
    `referral_source` drawn from `PHYSICIAN`, `OT`, `VA`, `SELF`, and `AGENCY`;
    when no referral source is supplied it defaults to `SELF`."

    Design: Corner/entities/case_referral_source_defaults_to_self
    """
    case = create_case(client_name="Dee Edd", client_address="5 Default Dr",
                       client_phone="555-0207")
    assert case["referral_source"] == "SELF"
    got = validate_success(api.get_case(case["id"], IC), 200)
    assert got["referral_source"] == "SELF"


def test_case_create_with_id_input_ignored(api):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix; clients never
    supply it. `created_at` is an ISO 8601 UTC timestamp with three fractional
    digits recording when the resource was created."

    Design: Corner/entities/case_create_with_id_input_ignored
    """
    set_clock()
    supplied_id = "11111111-1111-1111-1111-111111111111"
    res = api.create_case(
        {"id": supplied_id, "created_at": "1999-01-01T00:00:00Z",
         "client_name": "Ida Joss", "client_address": "10 Mint Rd",
         "client_phone": "555-0212"}, IC)
    case = validate_success(res, 201)
    assert case["id"] != supplied_id, "server must mint its own UUID, ignoring client input"
    assert is_valid_uuid(case["id"])
    assert case["created_at"] != "1999-01-01T00:00:00Z", "client-supplied created_at must be ignored"
    assert is_iso8601_timestamp(case["created_at"])


def test_case_create_funding_posture_input_ignored(api):
    """PRD §3.1: "The new case starts in `INTAKE` status with its computed fields
    initialized: all ledger totals at zero and `funding_posture` at `UNFUNDED`."
    PRD §2.8: "When `total_funded_cents` is zero the posture is `UNFUNDED`."

    Design: Corner/entities/case_create_funding_posture_input_ignored
    """
    res = api.create_case(
        {"client_name": "Jay Kipp", "client_address": "11 Computed Ave",
         "client_phone": "555-0213", "funding_posture": "FULLY_FUNDED",
         "total_funded_cents": 999999}, IC)
    case = validate_success(res, 201)
    assert case["funding_posture"] == "UNFUNDED", "computed funding_posture must ignore client input"
    assert case["total_funded_cents"] == 0


def test_case_list_filter_by_status(api):
    """PRD §2.3: "Several list endpoints additionally accept domain filters: the
    case list accepts optional `status` and `funding_posture` filters, the quote
    list and the invoice list each accept an optional `status` filter, and the
    inventory-unit list accepts optional `status` and `ramp_type` filters."

    Design: Corner/endpoints/case_list_filter_by_status
    """
    case1 = create_case(client_name="Vic Yell", client_address="48 Filter Rd",
                        client_phone="555-0502")
    case2 = create_case(client_name="Wyn Zeff", client_address="49 Filter Rd",
                        client_phone="555-0503")
    validate_success(api.cancel_case(case2["id"], PM), 200)
    data, _ = validate_paginated(api.list_cases(IC, params={"status": "CANCELLED"}))
    ids = [c["id"] for c in data]
    assert all(c["status"] == "CANCELLED" for c in data)
    assert case2["id"] in ids
    assert case1["id"] not in ids


def test_writes_visible_immediately_after_mutation(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §2.4: "`updated_at` is the same kind of timestamp, refreshed on every
    mutation of the resource."

    Design: Corner/consistency_model/writes_visible_immediately_after_mutation
    """
    set_clock()
    res = api.create_case(
        {"client_name": "Imm Read", "client_address": "76 Now St",
         "client_phone": "555-0901", "referral_source": "AGENCY"}, IC)
    created = validate_success(res, 201)
    got = validate_success(api.get_case(created["id"], IC), 200)
    assert got["client_name"] == "Imm Read"
    assert got["referral_source"] == "AGENCY"
    assert got["status"] == "INTAKE"
    assert got["version"] == 1
    for field in ("id", "client_name", "client_address", "client_phone",
                  "referral_source", "status", "version", "created_at"):
        assert got[field] == created[field], (
            f"POST response and subsequent GET disagree on {field}: "
            f"{created[field]!r} vs {got[field]!r}")
