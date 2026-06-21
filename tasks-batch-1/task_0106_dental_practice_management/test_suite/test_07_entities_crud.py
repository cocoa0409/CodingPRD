"""Entity creation, defaults, required fields, immutability, and listing.

Corner queue B: entities section instances.
"""
from test_helpers import (
    setup_practice,
    create_provider,
    create_patient,
    create_plan_with_items,
    propose_plan,
    accept_plan,
    complete_item_via_visit,
    create_claim,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_patient,
    assert_claim_attachment,
    assert_tooth_chart_entry,
    make_clinician_headers,
    TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]
BILL = TEST_USERS["billing_headers"]


def test_create_patient_returns_201_with_defaults():
    """PRD §3.1: "A `FrontDesk` user registers a patient with a `full_name` and a
    `date_of_birth`; the new patient opens in `ACTIVE` status with
    `balance_owed_cents` initialized to zero."

    Design: Corner/entities/create_patient_returns_201_with_defaults
    """
    resp = api_client.create_patient({"full_name": "New Pat", "date_of_birth": "1992-01-01"}, FD)
    data = validate_success(resp, expected_status=201)
    assert_patient(data)
    assert data["status"] == "ACTIVE"
    assert data["balance_owed_cents"] == 0
    assert is_valid_uuid(data["id"])


def test_get_patient_not_found_returns_404():
    """PRD §2.8: "A path or body identifier that does not correspond to an existing
    resource yields the matching not-found error for that resource type —
    `ERR_PATIENT_NOT_FOUND` ... all carrying HTTP 404."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    resp = api_client.get_patient(NON_EXISTENT_UUID, FD)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


def test_create_patient_missing_required_field_returns_422():
    """PRD §3.1: "A `FrontDesk` user registers a patient with a `full_name` and a
    `date_of_birth`".
    PRD §2.8: "the system validate[s] that the request body is well-formed:
    required fields present ... A malformed body yields `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_patient_missing_required_field_returns_422
    """
    resp = api_client.create_patient({"full_name": "No DOB"}, FD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_create_operatory_default_turnover_buffer_applied():
    """PRD §3.1: "`FrontDesk` creates an operatory with a `room_name` and an
    optional `turnover_buffer_minutes` that defaults to 15 and must be at least 0".

    Design: Corner/entities/create_operatory_default_turnover_buffer_applied
    """
    resp = api_client.create_operatory({"room_name": "OP-D1"}, FD)
    data = validate_success(resp, expected_status=201)
    assert data["turnover_buffer_minutes"] == 15


def test_tooth_chart_surface_requires_surface_field():
    """PRD §3.1: "If the entry is `SURFACE` and omits `surface`, or is `PERIO` and
    omits `pocket_depth_mm`, the request fails body validation with
    `ERR_VALIDATION`."

    Design: Corner/entities/tooth_chart_surface_requires_surface_field
    """
    patient = create_patient()
    provider = create_provider(provider_type="DENTIST")
    resp = api_client.create_tooth_chart(
        patient["id"],
        {"provider_id": provider["id"], "tooth_number": 14, "chart_type": "SURFACE",
         "finding": "caries"},
        make_clinician_headers(provider["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_tooth_chart_perio_pocket_depth_recorded():
    """PRD §3.1: "or `PERIO`, a pocket-depth reading that instead requires a
    `pocket_depth_mm` value between 1 and 12 millimeters."

    Design: Corner/entities/tooth_chart_perio_pocket_depth_recorded
    """
    patient = create_patient()
    provider = create_provider(provider_type="HYGIENIST")
    resp = api_client.create_tooth_chart(
        patient["id"],
        {"provider_id": provider["id"], "tooth_number": 30, "chart_type": "PERIO",
         "pocket_depth_mm": 5, "finding": "4-5-4"},
        make_clinician_headers(provider["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert_tooth_chart_entry(data)
    assert data["pocket_depth_mm"] == 5


def test_claim_attachment_immutable_no_version_field():
    """PRD §2.4: "`ClaimAttachment` is the one exception. An attachment is
    immutable after creation, so it carries only `id` and `created_at`; it has
    neither an `updated_at` field nor a `version` field."

    Design: Corner/entities/claim_attachment_immutable_no_version_field
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    plan, items = create_plan_with_items(
        patient["id"], provider["id"],
        [{"cdt_code": "D2150", "category": "BASIC", "fee_cents": 40_000,
          "phase_number": 1, "tooth_number": 5}],
    )
    item = items[0]
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    complete_item_via_visit(patient["id"], provider["id"], operatory["id"], item["id"],
                            start_at="2026-02-01T09:00:00Z", end_at="2026-02-01T10:00:00Z")
    claim = create_claim(patient["id"], item["id"], coverage["id"])
    resp = api_client.add_claim_attachment(
        claim["id"], {"attachment_type": "XRAY", "document_ref": "ref://att1"}, BILL)
    data = validate_success(resp, expected_status=201)
    assert data["document_ref"] == "ref://att1"
    assert_claim_attachment(data)  # asserts no version / updated_at


def test_list_patients_pagination_envelope():
    """PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_patients_pagination_envelope
    """
    create_patient(full_name="List Pat")
    resp = api_client.list_patients(FD)
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert "total_count" in meta and "has_more" in meta
