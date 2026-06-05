"""CRUD, field validation, reference integrity, listing/pagination, RBAC, and the
premium-amount-mismatch path on an in-force policy.

Covers the corner entities / validations / endpoints / rbac instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_applicant, assert_paramed_exam,
    setup_issued_policy,
    create_product, create_underwriter, create_draft_application,
    make_underwriter_headers, make_policyowner_headers, make_admin_headers,
    NON_EXISTENT_UUID, EXAM_STANDARD,
)


# ─── entities ─────────────────────────────────────────
def test_create_applicant_returns_201_with_all_fields(api):
    """PRD §3.1: "An `Applicant` — the proposed insured — is created with a legal
    `full_name`, a `date_of_birth` given as an ISO 8601 date in the past, a `sex` that must
    be either `MALE` or `FEMALE`, a `tobacco_use` boolean recording any tobacco use in the
    prior twelve months, and an `email` that must be non-empty and unique across applicants"
    PRD §2.4: "Every resource has an `id`, a server-minted UUID with no type prefix"

    Design: Corner/entities/create_applicant_returns_201_with_all_fields
    """
    data = validate_success(
        api.create_applicant(
            {"full_name": "New Person", "date_of_birth": "1990-01-01", "sex": "MALE",
             "tobacco_use": False, "email": "new-person@example.com"},
            make_underwriter_headers("any-underwriter")),
        expected_status=201,
    )
    assert_applicant(data)
    assert data["full_name"] == "New Person"
    assert data["sex"] == "MALE"
    assert data["tobacco_use"] is False


def test_get_nonexistent_applicant_returns_not_found(api):
    """PRD §2.5: "The server validates path identifiers strictly left to right, rejecting
    the request with `ERR_NOT_FOUND` at the first segment that names a non-existent resource"

    Design: Corner/entities/get_nonexistent_applicant_returns_not_found
    """
    resp = api.get_applicant(NON_EXISTENT_UUID, make_underwriter_headers("u"))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_application_missing_required_field(api):
    """PRD §3.2: "An `Underwriter` opens a case by creating an `Application`, which
    references an applicant via `applicant_id` and a product via `product_id` and records the
    `requested_face_amount_cents`, the death benefit sought, which must be at least one
    hundred thousand cents."
    PRD §2.11: "then well-formedness of the body — required fields present, correct types,
    enum values within their declared sets, and integers inside their declared ranges
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_application_missing_required_field_returns_invalid_request
    """
    product = create_product()
    u = create_underwriter()
    applicant = validate_success(
        api.create_applicant(
            {"full_name": "Req Test", "date_of_birth": "1990-01-01", "sex": "FEMALE",
             "tobacco_use": False, "email": "req-test@example.com"},
            make_underwriter_headers(u["id"])),
        expected_status=201,
    )
    # Omit requested_face_amount_cents (required, no default).
    resp = api.create_application(
        {"applicant_id": applicant["id"], "product_id": product["id"]},
        make_underwriter_headers(u["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_product_defaults_applied_when_optional_fields_omitted(api):
    """PRD §3.1: "The `contestability_months` field is the length of the contestability
    window in whole months measured from issue and defaults to 24"
    PRD §3.1: "The `grace_period_days` field is the number of days after a missed due date
    before the contract lapses and defaults to 31"
    PRD §3.1: "The `max_loan_to_cash_value_pct` field is the largest loan principal
    expressible as a whole-number percentage of net cash value, defaulting to 90"
    PRD §3.1: "The `exam_validity_days` field is how many days a paramed exam remains valid
    from its exam date, defaulting to 180"

    Design: Corner/entities/product_defaults_applied_when_optional_fields_omitted
    """
    data = validate_success(
        api.create_product(
            {"code": "DEF-PROD", "base_annual_rate_per_thousand_cents": 250,
             "max_face_amount_cents": 100_000_000, "cash_value_accrual_rate_bps": 300},
            make_admin_headers()),
        expected_status=201,
    )
    assert data["contestability_months"] == 24, data
    assert data["grace_period_days"] == 31, data
    assert data["max_loan_to_cash_value_pct"] == 90, data
    assert data["exam_validity_days"] == 180, data


def test_applicant_invalid_sex_enum_rejected(api):
    """PRD §3.1: "a `sex` that must be either `MALE` or `FEMALE`"
    PRD §2.11: "enum values within their declared sets, and integers inside their declared
    ranges (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/applicant_invalid_sex_enum_returns_invalid_request
    """
    resp = api.create_applicant(
        {"full_name": "Bad Sex", "date_of_birth": "1990-01-01", "sex": "OTHER",
         "tobacco_use": False, "email": "bad-sex@example.com"},
        make_underwriter_headers("u"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_application_wrong_product_reference(api):
    """PRD §2.5: "when a create body carries a foreign key — `applicant_id`, `product_id`,
    `application_id`, or `policy_id` — the referenced row must exist; a dangling reference is
    rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/create_application_wrong_product_reference_returns_reference_not_found
    """
    u = create_underwriter()
    applicant = validate_success(
        api.create_applicant(
            {"full_name": "Ref Person", "date_of_birth": "1990-01-01", "sex": "MALE",
             "tobacco_use": False, "email": "ref-person@example.com"},
            make_underwriter_headers(u["id"])),
        expected_status=201,
    )
    resp = api.create_application(
        {"applicant_id": applicant["id"], "product_id": NON_EXISTENT_UUID,
         "requested_face_amount_cents": 50_000_000},
        make_underwriter_headers(u["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ─── validations ──────────────────────────────────────
def test_duplicate_applicant_email_rejected(api):
    """PRD §3.1: "an `email` that must be non-empty and unique across applicants, with
    duplicates rejected as `ERR_DUPLICATE_VALUE`."

    Design: Corner/validations/duplicate_applicant_email_rejected
    """
    u_h = make_underwriter_headers("u")
    validate_success(
        api.create_applicant(
            {"full_name": "First", "date_of_birth": "1990-01-01", "sex": "MALE",
             "tobacco_use": False, "email": "dup@example.com"}, u_h),
        expected_status=201,
    )
    resp = api.create_applicant(
        {"full_name": "Second", "date_of_birth": "1991-02-02", "sex": "FEMALE",
         "tobacco_use": False, "email": "dup@example.com"}, u_h,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VALUE.value)


def test_face_exceeds_product_max_rejected_at_create(api):
    """PRD §3.2: "At create time the requested face amount is checked against the chosen
    product's ceiling; a request exceeding `max_face_amount_cents` is rejected with
    `ERR_FACE_EXCEEDS_PRODUCT_MAX`."

    Design: Corner/validations/face_exceeds_product_max_rejected_at_create
    """
    product = create_product(max_face_amount_cents=10_000_000)
    u = create_underwriter()
    applicant = validate_success(
        api.create_applicant(
            {"full_name": "Fmax Person", "date_of_birth": "1990-01-01", "sex": "MALE",
             "tobacco_use": False, "email": "fmax@example.com"},
            make_underwriter_headers(u["id"])),
        expected_status=201,
    )
    resp = api.create_application(
        {"applicant_id": applicant["id"], "product_id": product["id"],
         "requested_face_amount_cents": 50_000_000},
        make_underwriter_headers(u["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FACE_EXCEEDS_PRODUCT_MAX.value)


def test_premium_amount_mismatch_on_in_force_policy(api):
    """PRD §3.7: "A `PremiumPayment` carries an `amount_cents` that must be at least 1 and,
    to be accepted, must exactly equal the policy's `annual_premium_cents`; any other amount
    is rejected with `ERR_PREMIUM_AMOUNT_MISMATCH`."

    Design: Corner/validations/premium_amount_mismatch_on_in_force_policy
    """
    # IN_FORCE policy (state precondition satisfied) so priority 13 fires in isolation.
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    applicant_id = ctx["applicant"]["id"]
    resp = api.create_premium_payment(
        policy_id, {"amount_cents": 100000}, make_policyowner_headers(applicant_id)
    )
    validate_error(resp, ApiErrorId.ERR_PREMIUM_AMOUNT_MISMATCH.value)


# ─── endpoints (listing) ──────────────────────────────
def test_list_applications_pagination_envelope(api):
    """PRD §2.3: "Every list response surfaces `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object."
    PRD §2.3: "The `limit` parameter caps the number of items returned"

    Design: Corner/endpoints/list_applications_pagination_envelope
    """
    product = create_product()
    u = create_underwriter()
    applicant, app1 = create_draft_application(product["id"], u["id"])
    u_h = make_underwriter_headers(u["id"])
    validate_success(
        api.create_application(
            {"applicant_id": applicant["id"], "product_id": product["id"],
             "requested_face_amount_cents": 40_000_000}, u_h),
        expected_status=201,
    )
    data, meta = validate_paginated(
        api.list_applications(u_h, params={"applicant_id": applicant["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_filtered_list_paramed_exams_by_application_fk(api):
    """PRD §4 (GET /applications/{id}/paramed-exams): "List paramed exams for an application"
    PRD §3.3: "A `ParamedExam` is attached to an application while it sits in `EXAM_PENDING`,
    created in `ORDERED` status."

    Design: Corner/endpoints/filtered_list_paramed_exams_by_application_fk
    """
    product = create_product()
    u = create_underwriter()
    _, app = create_draft_application(product["id"], u["id"])
    u_h = make_underwriter_headers(u["id"])
    validate_success(api.submit_application(app["id"], u_h))
    validate_success(api.order_exam(app["id"], u_h))
    validate_success(api.create_paramed_exam(
        app["id"], {"height_inches": 70, "weight_pounds": 160, "systolic_bp": 120,
                    "exam_date": "2026-01-10"}, u_h), expected_status=201)
    validate_success(api.create_paramed_exam(
        app["id"], {"height_inches": 70, "weight_pounds": 165, "systolic_bp": 122,
                    "exam_date": "2026-09-01"}, u_h), expected_status=201)
    exams, _ = validate_paginated(api.list_paramed_exams(app["id"], u_h))
    assert len(exams) == 2, exams
    for e in exams:
        assert e["application_id"] == app["id"], e
        assert_paramed_exam(e)


# ─── rbac ─────────────────────────────────────────────
def test_policyowner_cannot_create_products(api):
    """PRD §2.1: "A syntactically valid request whose role is not permitted to invoke the
    targeted operation is rejected with `ERR_UNAUTHORIZED`."
    PRD §4 (POST /products): "Create a product (rate table and policy parameters) | Admin"

    Design: Corner/rbac/policyowner_cannot_create_products
    """
    resp = api.create_product(
        {"code": "RBAC-X", "base_annual_rate_per_thousand_cents": 250,
         "max_face_amount_cents": 100_000_000, "cash_value_accrual_rate_bps": 300},
        make_policyowner_headers("some-applicant"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_underwriter_cannot_draw_policy_loan(api):
    """PRD §2.1: "A syntactically valid request whose role is not permitted to invoke the
    targeted operation is rejected with `ERR_UNAUTHORIZED`."
    PRD §4 (POST /policies/{id}/policy-loans): "Draw a policy loan against net cash value |
    PolicyOwner"

    Design: Corner/rbac/underwriter_cannot_draw_policy_loan
    """
    ctx = setup_issued_policy(issue_clock="2026-06-01T00:00:00Z", exam_overrides=dict(EXAM_STANDARD))
    policy_id = ctx["policy"]["id"]
    resp = api.create_policy_loan(
        policy_id, {"principal_cents": 1000, "expected_policy_version": ctx["policy"]["version"]},
        make_underwriter_headers(ctx["u2"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role`, carries a value outside this set, or
    omits `X-User-ID` where the role requires an identity is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    # No auth headers at all.
    resp = api._request("GET", f"/applications/{NON_EXISTENT_UUID}", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
