"""Catalog setup, customer intake, resource reads, existence checks, listing.

Translations of scaffold_corner_design instances in the `entities`, `endpoints`,
and `consistency_model` sections.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_customer, assert_designer,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_customer_payload, create_designer_payload,
    create_project_payload, create_design_appointment_payload,
    create_project,
)

PA = TEST_USERS["platform_admin_headers"]
IC = TEST_USERS["install_coordinator_headers"]


def test_customer_intake_defaults_credit_to_zero(api):
    """PRD §3.1: "A customer's referral_credit_cents begins at 0."

    Design: Corner/entities/customer_create_success_echoes_fields
    """
    resp = api.create_customer(create_customer_payload(full_name="Ada Adams"), PA)
    data = validate_success(resp, 201)
    assert_customer(data)
    assert data["referral_credit_cents"] == 0, (
        f"referral_credit_cents must begin at 0, got {data['referral_credit_cents']}"
    )


def test_designer_active_defaults_to_true(api):
    """PRD §3.1: "a designer's active flag governs whether they accept new
    appointments and defaults to true."

    Design: Corner/entities/designer_active_default_applied
    """
    resp = api.create_designer(create_designer_payload(), PA)
    data = validate_success(resp, 201)
    assert_designer(data)
    assert data["active"] is True, "active must default to true when omitted"


def test_get_unknown_project_returns_not_found(api):
    """PRD §2.5: "Every identifier carried in the path or body must resolve to a
    live resource, checked left-to-right in the order the identifiers appear. The
    first unresolved identifier determines the error: ERR_CUSTOMER_NOT_FOUND,
    ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND, ERR_PROJECT_NOT_FOUND,
    ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND, ERR_BOOKING_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all 404)."

    Design: Corner/entities/project_get_nonexistent_returns_not_found
    """
    resp = api.get_project(NON_EXISTENT_UUID, IC)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)


def test_project_create_missing_bathroom_type_rejected(api):
    """PRD §2.5: "On mutating endpoints, required fields must be present with
    correct types, enum values must be members of their allowed set, monetary and
    area amounts must be positive, and where a time interval is supplied
    scheduled_end must be strictly after scheduled_start; any violation is
    ERR_VALIDATION (422)."

    Design: Corner/entities/project_create_missing_bathroom_type_returns_validation
    """
    cust = validate_success(api.create_customer(create_customer_payload(), PA), 201)
    payload = create_project_payload(cust["id"])
    payload.pop("bathroom_type")
    resp = api.create_project(payload, IC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_project_create_invalid_bathroom_type_enum_rejected(api):
    """PRD §2.5: "On mutating endpoints, required fields must be present with
    correct types, enum values must be members of their allowed set, monetary and
    area amounts must be positive, and where a time interval is supplied
    scheduled_end must be strictly after scheduled_start; any violation is
    ERR_VALIDATION (422)."

    Design: Corner/entities/project_create_invalid_enum_bathroom_type_returns_validation
    """
    cust = validate_success(api.create_customer(create_customer_payload(), PA), 201)
    resp = api.create_project(create_project_payload(cust["id"], bathroom_type="PALACE"), IC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_project_create_unknown_customer_returns_customer_not_found(api):
    """PRD §2.5: "The first unresolved identifier determines the error:
    ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND, ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all
    404)."

    Design: Corner/entities/project_create_unknown_customer_returns_customer_not_found
    """
    resp = api.create_project(create_project_payload(NON_EXISTENT_UUID), IC)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_book_appointment_unknown_designer_returns_designer_not_found(api):
    """PRD §2.5: "The first unresolved identifier determines the error:
    ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND, ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all
    404)."

    Design: Corner/entities/appointment_create_unknown_designer_returns_designer_not_found
    """
    cust = validate_success(api.create_customer(create_customer_payload(), PA), 201)
    proj = create_project(api, cust["id"])
    resp = api.create_design_appointment(
        create_design_appointment_payload(proj["id"], NON_EXISTENT_UUID), IC)
    validate_error(resp, ApiErrorId.ERR_DESIGNER_NOT_FOUND.value)


def test_project_list_returns_paginated_envelope(api):
    """PRD §2.3: "List responses carry the pagination bookkeeping in the meta
    object of the envelope: limit, offset, total_count, and has_more."

    Design: Corner/entities/project_list_pagination_envelope
    """
    cust = validate_success(api.create_customer(create_customer_payload(), PA), 201)
    proj = create_project(api, cust["id"])
    resp = api.list_projects(IC, params={"customer_id": cust["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, "has_more must be false for a single-item page"
    assert len(data) == 1 and data[0]["id"] == proj["id"]


def test_project_immediately_readable_after_create(api):
    """PRD §2.7: "The system applies all such secondary effects synchronously and
    immediately as part of the triggering operation, so that a client reading any
    affected resource afterward sees a fully reconciled state."
    PRD §3.2: "A fresh project starts in LEAD status with no assigned designer_id,
    its warranty_status at NONE, and its permit_status at NOT_APPLICABLE."

    Design: Corner/consistency_model/immediate_visibility_project_created_then_get
    """
    cust = validate_success(api.create_customer(create_customer_payload(), PA), 201)
    proj = create_project(api, cust["id"])
    data = validate_success(api.get_project(proj["id"], IC), 200)
    assert data["status"] == "LEAD", f"freshly created project must be LEAD, got {data['status']}"


def test_complete_unknown_appointment_returns_not_found(api):
    """PRD §2.5: "The first unresolved identifier determines the error:
    ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND, ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all
    404)."

    Design: Corner/endpoints/complete_unknown_appointment_returns_not_found
    """
    des = validate_success(api.create_designer(create_designer_payload(), PA), 201)
    from test_helpers import make_designer_headers
    resp = api.complete_design_appointment(
        NON_EXISTENT_UUID, {"measured_wall_area_sqft": 100}, make_designer_headers(des["id"]))
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value)


def test_get_unknown_quote_returns_not_found(api):
    """PRD §2.5: "The first unresolved identifier determines the error:
    ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND, ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all
    404)."

    Design: Corner/endpoints/get_unknown_quote_returns_not_found
    """
    resp = api.get_quote(NON_EXISTENT_UUID, IC)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_FOUND.value)


def test_cancel_unknown_booking_returns_not_found(api):
    """PRD §2.5: "The first unresolved identifier determines the error:
    ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND, ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all
    404)."

    Design: Corner/endpoints/cancel_unknown_booking_returns_not_found
    """
    resp = api.cancel_install_booking(NON_EXISTENT_UUID, IC)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND.value)


def test_decide_unknown_claim_returns_not_found(api):
    """PRD §2.5: "The first unresolved identifier determines the error:
    ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND, ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all
    404)."

    Design: Corner/endpoints/decide_unknown_claim_returns_not_found
    """
    resp = api.decide_warranty_claim(
        NON_EXISTENT_UUID, {"decision": "APPROVE", "resolution": "REPAIR"}, IC)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FOUND.value)


def test_void_unknown_referral_returns_not_found(api):
    """PRD §2.5: "The first unresolved identifier determines the error:
    ERR_CUSTOMER_NOT_FOUND, ERR_DESIGNER_NOT_FOUND, ERR_CREW_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND, ERR_APPOINTMENT_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND, ERR_CLAIM_NOT_FOUND, or ERR_REFERRAL_NOT_FOUND (all
    404)."

    Design: Corner/endpoints/void_unknown_referral_returns_not_found
    """
    resp = api.void_referral(NON_EXISTENT_UUID, PA)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_FOUND.value)
