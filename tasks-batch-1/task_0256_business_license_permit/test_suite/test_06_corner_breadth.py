"""Breadth coverage: entity CRUD, input validation, pagination, RBAC, simple
state-machine rejections, and consistency — the non-stub corner-design instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_applicant_headers, make_licensing_officer_headers,
    create_activity_category_payload, create_business_payload,
    create_application_payload, create_inspection_payload,
    record_inspection_payload,
    TEST_USERS, ANONYMOUS_HEADERS,
    setup_issued_license, setup_zoning_cleared_application,
    settle_all_license_fees, set_clock,
)

OFFICER = TEST_USERS["licensing_officer_headers"]
INSPECTOR = TEST_USERS["inspection_officer_headers"]
APPLICANT = TEST_USERS["applicant_headers"]
ISSUER = make_licensing_officer_headers("officer-issuer")

# Distinct, well-formed v4 UUID that does not resolve to any entity.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"


# ─── entities ──────────────────────────────────────────────────────────────
def test_create_business_returns_201_with_defaults(api):
    """PRD §3.1: "On registration its derived regulatory `standing` is initialized
    to `GOOD`, its `prior_revocation_flag` to false, and its
    `compliance_risk_score` to 0."

    Design: Corner/entities/create_business_returns_201_with_defaults
    """
    res = api.create_business(
        create_business_payload(legal_name="New Biz", owner_name="N Owner",
                                zone_code="C1"), APPLICANT)
    biz = validate_success(res, 201)
    assert biz["standing"] == "GOOD", biz["standing"]
    assert biz["prior_revocation_flag"] is False, biz["prior_revocation_flag"]
    assert biz["compliance_risk_score"] == 0, biz["compliance_risk_score"]
    assert biz["version"] == 1, biz["version"]


def test_create_application_missing_required_field(api):
    """PRD §2.4: "Request well-formedness comes fourth: a missing required field,
    a wrongly typed value, or an enum value outside its allowed set yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_application_missing_required_field_returns_invalid_request
    """
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Req Biz", owner_name="RB",
                                zone_code="C1"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    # Omit activity_category_id.
    payload = {"business_id": biz["id"], "declared_employee_count": 1,
               "requested_zone_code": "C1"}
    res = api.create_application(payload, biz_h)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_license_nonexistent_returns_not_found(api):
    """PRD §2.4: "Resource existence comes third: any resource named in the path or
    body that does not exist yields `ERR_NOT_FOUND`".

    Design: Corner/entities/get_license_nonexistent_returns_not_found
    """
    res = api.get_license(ABSENT_UUID, OFFICER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_activity_category_base_risk_out_of_range(api):
    """PRD §2.4: "A `declared_employee_count` below zero, a `verified_employee_count`
    or `failed_item_count` below zero, an `activity_base_risk` outside the inclusive
    range 0 through 40, a `required_inspection_count` outside the inclusive range 0
    through 5, a `risk_tier` that is not one of the recognized tiers, or a
    `term_months` that is not one of the recognized terms — each of these passes a
    bare type check yet is rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/activity_category_base_risk_out_of_range_unprocessable
    """
    payload = create_activity_category_payload(code="RANGE_BAD", risk_tier="LOW",
                                               activity_base_risk=99)
    res = api.create_activity_category(payload, OFFICER)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_application_system_fields_input_ignored(api):
    """PRD §3.2: "A fresh application starts with `status` `DRAFT` and
    `zoning_status` `PENDING`."

    Design: Corner/entities/application_system_fields_input_ignored
    """
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Sys Biz", owner_name="SB",
                                zone_code="C1"), APPLICANT))
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(code="SYS_CAT"), OFFICER))
    biz_h = make_applicant_headers(biz["id"])
    # Attempt to set computed fields on create; they must be ignored.
    payload = create_application_payload(biz["id"], cat["id"],
                                         declared_employee_count=3)
    payload["status"] = "APPROVED"
    payload["estimated_fee"] = 9999
    app = validate_success(api.create_application(payload, biz_h), 201)
    assert app["status"] == "DRAFT", app["status"]
    assert app["estimated_fee"] == 0, app["estimated_fee"]
    assert app["version"] == 1, app["version"]


def test_list_activity_categories_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_activity_categories_pagination_envelope
    """
    get_success_data(api.create_activity_category(
        create_activity_category_payload(code="PAGE_A"), OFFICER))
    get_success_data(api.create_activity_category(
        create_activity_category_payload(code="PAGE_B"), OFFICER))
    data, meta = validate_paginated(
        api.list_activity_categories(OFFICER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "The `limit` parameter caps how many items are returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. ... A `limit` or
    `offset` outside its allowed range is rejected with `ERR_PAGINATION_INVALID`
    (HTTP 400)."

    Design: Corner/entities/pagination_limit_out_of_range_rejected
    """
    res = api.list_licenses(OFFICER, params={"limit": 500})
    validate_error(res, "ERR_PAGINATION_INVALID", expected_status=400)


# ─── state machines (simple rejections) ────────────────────────────────────
def test_approve_application_from_draft_invalid_state(api):
    """PRD §2.4: "State legality comes fifth: if the target resource is not in a
    state from which the requested transition is defined, the request is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/approve_application_from_draft_invalid_state
    """
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Inv Biz", owner_name="IB",
                                zone_code="C1"), APPLICANT))
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(code="INV_CAT"), OFFICER))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))  # DRAFT
    res = api.approve_application(app["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_revoke_active_license_invalid_state(api):
    """PRD §3.7: "Revocation is the punitive terminus, performed by a
    `LicensingOfficer` on a `DELINQUENT` license, advancing it `DELINQUENT →
    REVOKED`."

    Design: Corner/state_machines/revoke_active_license_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "ACT_CAT", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    # License is ACTIVE, never delinquent -> revoke not defined from ACTIVE.
    res = api.revoke_license(ctx["license"]["id"], OFFICER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_record_inspection_twice_rejected(api):
    """PRD §3.4: "An outcome may only be recorded against an inspection still in
    `SCHEDULED`; recording against one already resolved is rejected with
    `ERR_INSPECTION_ALREADY_RECORDED` (HTTP 409)."

    Design: Corner/state_machines/record_inspection_twice_rejected
    """
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Insp Biz", owner_name="IPB",
                                zone_code="C1"), APPLICANT))
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(code="DBL_INSP", required_inspection_count=1), OFFICER))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"]), biz_h))
    insp = get_success_data(api.create_inspection(
        create_inspection_payload(app["id"], "insp-x"), INSPECTOR))
    get_success_data(api.record_inspection(
        insp["id"], record_inspection_payload("PASSED", 1, 0), INSPECTOR))
    # Second record on a non-SCHEDULED inspection.
    res = api.record_inspection(
        insp["id"], record_inspection_payload("FAILED", 1, 2), INSPECTOR)
    validate_error(res, "ERR_INSPECTION_ALREADY_RECORDED", expected_status=409)


# ─── validations ────────────────────────────────────────────────────────────
def test_duplicate_activity_code_rejected(api):
    """PRD §3.1: "The `code` must be unique across all activity categories and is
    immutable once created; an attempt to create a second category with an existing
    code is rejected with `ERR_DUPLICATE_ACTIVITY_CODE` (HTTP 409)."

    Design: Corner/validations/duplicate_activity_code_rejected
    """
    get_success_data(api.create_activity_category(
        create_activity_category_payload(code="DUP_CODE", risk_tier="LOW"), OFFICER))
    res = api.create_activity_category(
        create_activity_category_payload(code="DUP_CODE", risk_tier="HIGH",
                                         activity_base_risk=30, required_inspection_count=1,
                                         requires_zoning_check=True, term_months=24,
                                         allowed_zones=["C2"]), OFFICER)
    validate_error(res, "ERR_DUPLICATE_ACTIVITY_CODE", expected_status=409)


def test_zoning_denied_no_variance_path(api):
    """PRD §3.3: "If the requested zone is outside the allowed set and the category
    does not permit a variance path, the check is denied outright with
    `ERR_ZONING_DENIED` (HTTP 409)."

    Design: Corner/validations/zoning_denied_no_variance_path
    """
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="NOVAR_CAT", risk_tier="LOW", activity_base_risk=10,
            required_inspection_count=0, requires_zoning_check=False,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Zone Biz", owner_name="ZB",
                                zone_code="X9"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"],
                                   declared_employee_count=1, requested_zone_code="X9"), biz_h))
    get_success_data(api.submit_application(app["id"], biz_h))
    res = api.zoning_check_application(app["id"], OFFICER)
    validate_error(res, "ERR_ZONING_DENIED", expected_status=409)


def test_surrender_with_no_outstanding_fees_succeeds(api):
    """PRD §3.7: "Surrender is the voluntary terminus, performed by an `Applicant`
    on an `ACTIVE` license, advancing it `ACTIVE → SURRENDERED`. It is gated
    fiscally: a license may be surrendered only when it has no outstanding
    unsettled `FeeAssessment`".

    Design: Corner/validations/surrender_with_no_outstanding_fees_succeeds
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "SUR_LOW", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    settle_all_license_fees(lic["id"], biz_h)  # settle the ISSUANCE_FEE
    res = api.surrender_license(lic["id"], biz_h)
    surrendered = validate_success(res, 200)
    assert surrendered["status"] == "SURRENDERED", surrendered["status"]


def test_surrender_with_outstanding_fee_rejected(api):
    """PRD §3.7: "a license may be surrendered only when it has no outstanding
    unsettled `FeeAssessment`; if any unsettled assessment remains, the surrender
    is rejected with `ERR_OUTSTANDING_FEES` (HTTP 409)."

    Design: Corner/validations/surrender_active_license_with_outstanding_fee_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "OUTF_LOW", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    biz_h = ctx["biz_headers"]
    # Leave the ISSUANCE_FEE assessment unsettled; license is ACTIVE so the state
    # gate passes and the fiscal gate is the deciding rejection.
    res = api.surrender_license(lic["id"], biz_h)
    validate_error(res, "ERR_OUTSTANDING_FEES", expected_status=409)


# ─── endpoints ──────────────────────────────────────────────────────────────
def test_zoning_check_clears_allowed_zone_no_surcharge(api):
    """PRD §3.3: "When the `requested_zone_code` is one of the category's
    `allowed_zones`, the application clears: it advances `SUBMITTED →
    ZONING_CLEARED` and its `zoning_status` is set to `CLEARED`."

    Design: Corner/endpoints/zoning_check_clears_allowed_zone_no_surcharge
    """
    set_clock("2026-06-01T00:00:00Z")
    cat = get_success_data(api.create_activity_category(
        create_activity_category_payload(
            code="CLR_HIGH", risk_tier="HIGH", activity_base_risk=30,
            required_inspection_count=0, requires_zoning_check=True,
            term_months=12, allowed_zones=["C1"]), OFFICER))
    biz = get_success_data(api.create_business(
        create_business_payload(legal_name="Clr Biz", owner_name="CB",
                                zone_code="C1"), APPLICANT))
    biz_h = make_applicant_headers(biz["id"])
    app = get_success_data(api.create_application(
        create_application_payload(biz["id"], cat["id"],
                                   declared_employee_count=12, requested_zone_code="C1"), biz_h))
    submitted = get_success_data(api.submit_application(app["id"], biz_h))  # 600 + 60 = 660
    cleared = validate_success(api.zoning_check_application(app["id"], OFFICER), 200)
    assert cleared["zoning_status"] == "CLEARED", cleared["zoning_status"]
    assert cleared["estimated_fee"] == 660.00 == submitted["estimated_fee"], cleared


# ─── rbac ───────────────────────────────────────────────────────────────────
def test_applicant_cannot_approve_application(api):
    """PRD §2.1: "A request whose role is recognized but not permitted to perform
    the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/applicant_cannot_approve_application
    """
    ctx = setup_zoning_cleared_application(category_overrides={
        "code": "RBAC_LOW", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    app = ctx["application"]
    biz_h = ctx["biz_headers"]
    res = api.approve_application(app["id"], biz_h)  # Applicant calling officer op
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that names a role outside
    this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api.create_business(
        create_business_payload(legal_name="NoAuth Biz", owner_name="NA",
                                zone_code="C1"), ANONYMOUS_HEADERS)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── consistency ────────────────────────────────────────────────────────────
def test_issued_license_immediately_readable(api):
    """PRD §3.5: "sets the application's `license_id` to the new license, and marks
    the application `ISSUED`."
    PRD §2.2: "operations that create or modify a resource will return the created
    or updated resource object in the data field."

    Design: Corner/consistency_model/issued_license_immediately_readable
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_issued_license(category_overrides={
        "code": "IMM_LOW", "risk_tier": "LOW", "activity_base_risk": 10,
        "required_inspection_count": 0, "requires_zoning_check": False,
        "term_months": 12, "allowed_zones": ["C1"]})
    lic = ctx["license"]
    # Immediately readable.
    fetched = validate_success(api.get_license(lic["id"], OFFICER), 200)
    assert fetched["status"] == "ACTIVE", fetched["status"]
    # And the application's license_id is set in the same cycle.
    app_after = get_success_data(api.get_application(ctx["application"]["id"], OFFICER))
    assert app_after["license_id"] == lic["id"], app_after["license_id"]
