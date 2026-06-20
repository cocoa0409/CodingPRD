"""CRUD surface, defaults, computed-field initialization, listing, and RBAC.

Corner queue: entities, state_machines (n/a here), rbac.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_lessor,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_lessor,
    create_approved_vendor,
    create_approved_lessee,
    create_lease,
    attach_equipment,
    create_lessor_payload,
    TEST_USERS,
)

ANALYST = TEST_USERS["credit_analyst_headers"]
OFFICER = TEST_USERS["funding_officer_headers"]
SERVICER = TEST_USERS["servicer_headers"]
ASSET_MGR = TEST_USERS["asset_manager_headers"]


# ─── Corner: entities / create_lessor_returns_201_with_fields ─────────
def test_create_lessor_returns_201_and_initializes_portfolio(api):
    """PRD §3.1: "On creation the lessor's logical clock is initialized and its
    `portfolio_value_cents` starts at zero."
    PRD §4: "Operations that create a new, distinct resource return `201 Created`".

    POST /lessors echoes legal_name and starts portfolio_value_cents at 0.

    Design: Corner/entities/create_lessor_returns_201_with_fields
    """
    res = api.create_lessor(create_lessor_payload(
        legal_name="Sierra Leasing", home_state_code="TX",
        sales_tax_rate_bps=625, property_tax_rate_bps=100), OFFICER)
    lessor = validate_success(res, 201)
    assert_lessor(lessor)
    assert lessor["legal_name"] == "Sierra Leasing", f"got {lessor['legal_name']}"
    assert lessor["portfolio_value_cents"] == 0, f"got {lessor['portfolio_value_cents']}"


# ─── Corner: entities / create_credit_application_missing_required_field ─
def test_create_credit_application_missing_credit_score_rejected(api):
    """PRD §2.11: "fourth, request-body well-formedness — required fields present,
    enumerations valid, and amounts strictly positive where required
    (`ERR_INVALID_REQUEST`)".
    PRD §3.2: "A `CreditAnalyst` opens a **Credit Application** by providing the
    prospective lessee's `applicant_legal_name`, the `requested_amount_cents` they
    are seeking, and the applicant's bureau `credit_score`."

    Omitting credit_score returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_credit_application_missing_required_field
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    res = api.create_credit_application(
        lessor_id, {"applicant_legal_name": "Cust", "requested_amount_cents": 500_000},
        ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Corner: entities / get_lease_nonexistent_returns_not_found ───────
def test_get_nonexistent_lease_returns_not_found(api):
    """PRD §2.6: "the system confirms the existence of each identifier in order and
    rejects the request with `ERR_NOT_FOUND` at the first identifier that does not
    resolve."

    GET a lease id that does not exist returns ERR_NOT_FOUND.

    Design: Corner/entities/get_lease_nonexistent_returns_not_found
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    res = api.get_lease(lessor_id, NON_EXISTENT_UUID, OFFICER)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Corner: entities / lease_system_ids_ignore_client_input ──────────
def test_created_lease_starts_in_origination_pending_version_one(api):
    """PRD §3.4: "A freshly created lease sits in `lifecycle_status` `ORIGINATION`
    and `funding_status` `PENDING_FUNDING`; these two dimensions advance
    independently."
    PRD §2.4: "an integer `version` that begins at 1".

    A created lease starts lifecycle ORIGINATION, funding PENDING_FUNDING, version 1.

    Design: Corner/entities/lease_system_ids_ignore_client_input
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    res = api.create_lease(
        lessor_id, lessee_id,
        {"vendor_id": vendor_id, "lease_type": "FMV", "equipment_cost_cents": 500_000,
         "term_months": 12, "monthly_rate_factor_bps": 2000}, OFFICER)
    lease = validate_success(res, 201)
    assert lease["lifecycle_status"] == "ORIGINATION", f"got {lease['lifecycle_status']}"
    assert lease["funding_status"] == "PENDING_FUNDING", f"got {lease['funding_status']}"
    assert lease["version"] == 1, f"got {lease['version']}"


# ─── Corner: entities / lease_advance_and_deposit_defaults_applied ────
def test_lease_advance_and_deposit_default_to_zero(api):
    """PRD §3.4: "`advance_payment_count`, the number of monthly payments collected
    up front (defaulting to zero); and `security_deposit_cents`, a refundable
    deposit collected at booking (defaulting to zero)."
    PRD §3.4: "`financed_amount_cents`, the credit exposure, is the equipment cost
    minus the product of `advance_payment_count` and the just-computed monthly
    payment, minus the security deposit".

    Omitting both advance and deposit defaults them to 0, so financed_amount equals
    the equipment cost (500000) after booking.

    Design: Corner/entities/lease_advance_and_deposit_defaults_applied
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "Y-SN-1", original_cost_cents=500_000)
    booked = get_success_data(api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, OFFICER))
    assert booked["advance_payment_count"] == 0, f"got {booked['advance_payment_count']}"
    assert booked["security_deposit_cents"] == 0, f"got {booked['security_deposit_cents']}"
    assert booked["financed_amount_cents"] == 500_000, f"got {booked['financed_amount_cents']}"


# ─── Corner: entities / invalid_lease_type_enum_rejected ──────────────
def test_invalid_lease_type_enum_rejected(api):
    """PRD §2.11: "fourth, request-body well-formedness — required fields present,
    enumerations valid, and amounts strictly positive where required
    (`ERR_INVALID_REQUEST`)".
    PRD §3.4: "the `lease_type` (one of `FMV`, `DOLLAR_OUT`, or `TRAC`)".

    Creating a lease with lease_type LEASE_TO_OWN (not a valid enum value) returns
    ERR_INVALID_REQUEST.

    Design: Corner/entities/invalid_lease_type_enum_rejected
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    res = api.create_lease(
        lessor_id, lessee_id,
        {"vendor_id": vendor_id, "lease_type": "LEASE_TO_OWN",
         "equipment_cost_cents": 500_000, "term_months": 12,
         "monthly_rate_factor_bps": 2000}, OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Corner: entities / list_vendors_pagination_envelope ──────────────
def test_list_vendors_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    With one vendor created, the vendor list returns an array envelope with
    total_count 1 and has_more false.

    Design: Corner/entities/list_vendors_pagination_envelope
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    create_approved_vendor(lessor_id)  # one vendor (approve does not add rows)
    data, meta = validate_paginated(api.list_vendors(lessor_id, OFFICER))
    assert meta["total_count"] == 1, f"got {meta['total_count']}"
    assert meta["has_more"] is False, f"got {meta['has_more']}"


# ─── Corner: rbac / servicer_cannot_book_lease ────────────────────────
def test_servicer_cannot_book_lease(api):
    """PRD §2.1: "When a caller's role is not authorized for the requested operation,
    the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §2.1: "A `FundingOfficer` onboards vendors, creates the lessor book of
    business, originates leases, books and funds them, attaches equipment, and
    manages UCC filings."

    A Servicer calling the FundingOfficer-only book endpoint returns
    ERR_FORBIDDEN_FOR_ROLE.

    Design: Corner/rbac/servicer_cannot_book_lease
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    vendor_id = create_approved_vendor(lessor_id)["id"]
    lessee_id = create_approved_lessee(lessor_id, approved_amount_cents=1_000_000)["id"]
    lease = create_lease(lessor_id, lessee_id, vendor_id,
                         equipment_cost_cents=500_000, term_months=12,
                         monthly_rate_factor_bps=2000)
    attach_equipment(lessor_id, lease["id"], "S-SN-1", original_cost_cents=500_000)
    res = api.book_lease(
        lessor_id, lease["id"], {"expected_lease_version": lease["version"]}, SERVICER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ─── Corner: rbac / asset_manager_cannot_create_credit_application ────
def test_asset_manager_cannot_create_credit_application(api):
    """PRD §2.1: "When a caller's role is not authorized for the requested operation,
    the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §2.1: "A `CreditAnalyst` underwrites credit applications — creating,
    submitting, returning for information, revising, approving, and declining them."

    An AssetManager calling the CreditAnalyst-only credit-application create returns
    ERR_FORBIDDEN_FOR_ROLE.

    Design: Corner/rbac/asset_manager_cannot_create_credit_application
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    res = api.create_credit_application(
        lessor_id, {"applicant_legal_name": "Cust", "requested_amount_cents": 500_000,
                    "credit_score": 760}, ASSET_MGR)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ─── Corner: rbac / missing_user_context_header_rejected ──────────────
def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, naming their operational
    capacity. If either header is missing or malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    A request carrying no user-context headers returns
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    lessor_id = create_lessor(home_state_code="TX")["id"]
    res = api.get_lessor(lessor_id, {})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
