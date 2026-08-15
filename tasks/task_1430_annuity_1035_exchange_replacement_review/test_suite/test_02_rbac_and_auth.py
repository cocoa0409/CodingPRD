"""User-context header enforcement and role-based authorization (PRD §2.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    assert_document,
    create_case_payload,
    create_client_payload,
    make_principal_headers,
    make_producer_headers,
    make_reviewer_headers,
    open_case,
    register_client,
    register_contract,
    register_producer,
    setup_case_in_review,
    setup_case_pending_principal,
    start_review,
    submit_case,
    submit_document,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_submit_without_user_context_headers_rejected(api):
    """PRD §2.1: "A request in which either header is missing or empty, or
    whose role value is not one of the declared roles, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/submit_case_missing_auth_headers
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"], living_benefit_rider=False
    )
    case = open_case(producer["id"], client["id"], contract["id"])

    res = api.submit_case(case["id"], {"Content-Type": "application/json"})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    case_after = validate_success(
        api.get_case(case["id"], make_producer_headers(producer["id"]))
    )
    assert case_after["status"] == "DRAFT", "rejected submit must not move the case"


def test_producer_cannot_approve_case(api):
    """PRD §2.1: "A request whose role is declared but does not appear in the
    endpoint's authorized role list is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §4: POST /cases/{id}/approve is authorized for Principal only.

    Design: Corner/rbac/producer_cannot_approve_returns_forbidden
    """
    bundle = setup_case_pending_principal()
    producer = bundle["producer"]
    res = api.approve_case(
        bundle["case_id"],
        {"rationale": "self-service"},
        make_producer_headers(producer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    case_after = validate_success(
        api.get_case(bundle["case_id"], make_producer_headers(producer["id"]))
    )
    assert case_after["status"] == "PENDING_PRINCIPAL"


def test_reviewer_cannot_suspend_producer(api):
    """PRD §2.1: "A request whose role is declared but does not appear in the
    endpoint's authorized role list is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §3.8: "Discipline is manual. A `ComplianceOfficer` suspends a producer
    from `ACTIVE` or `FLAGGED`, moving them to `SUSPENDED` with a
    `PRODUCER_SUSPENDED` event"

    Design: Corner/rbac/reviewer_cannot_suspend_producer
    """
    producer = register_producer()
    res = api.suspend_producer(producer["id"], make_reviewer_headers("rev-1"))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    producer_after = validate_success(
        api.get_producer(producer["id"], make_reviewer_headers("rev-1"))
    )
    assert producer_after["status"] == "ACTIVE"


def test_ops_desk_cannot_verify_documents(api, ops_headers):
    """PRD §2.1: "A request whose role is declared but does not appear in the
    endpoint's authorized role list is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §3.3: "verifying one moves it `SUBMITTED` → `VERIFIED`" is the
    reviewer's adjudication; POST /documents/{id}/verify is authorized for
    SuitabilityReviewer only (§4).

    Design: Corner/rbac/ops_desk_cannot_verify_documents
    """
    bundle = setup_case_in_review()
    doc = submit_document(
        bundle["case_id"], bundle["producer"]["id"], "REPLACEMENT_DISCLOSURE"
    )
    res = api.verify_document(doc["id"], ops_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    docs, meta = validate_paginated(
        api.list_case_documents(bundle["case_id"], ops_headers)
    )
    assert docs[0]["status"] == "SUBMITTED", "document must remain unverified"


def test_principal_cannot_set_clock(api, principal_headers, carrier_admin_headers):
    """PRD §2.4: "A `CarrierAdmin`-only test-driving capability sets the clock:
    the caller supplies a `to_iso8601` instant and receives the new
    `current_utc` back."
    PRD §2.1: "A request whose role is declared but does not appear in the
    endpoint's authorized role list is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/principal_cannot_set_clock
    """
    res = api.set_clock({"to_iso8601": "2026-08-02T00:00:00Z"}, principal_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    # The clock must still read the startup default: a client born 1961-08-02
    # is 64 at 2026-08-01 but would be 65 if the clock had actually moved.
    producer = register_producer()
    probe = validate_success(
        api.create_client(
            create_client_payload(full_name="Clock Probe", date_of_birth="1961-08-02"),
            make_producer_headers(producer["id"]),
        ),
        expected_status=201,
    )
    assert probe["age_years"] == 64, (
        "clock must still read the startup default 2026-08-01T00:00:00Z"
    )


def test_compliance_officer_cannot_create_cases(api, compliance_headers):
    """PRD §2.1: "A request whose role is declared but does not appear in the
    endpoint's authorized role list is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §3.2: "A `Producer` originates a replacement case by naming themselves
    via `producer_id` (which must equal the caller's `X-User-ID`), the
    `client_id`, and the `existing_contract_id` of the contract being replaced,
    together with the replacement product's `new_product_code` and
    `new_product_surrender_years` (the length of the new product's own
    surrender schedule in years)."

    Design: Corner/rbac/compliance_cannot_create_cases
    """
    producer = register_producer()
    client = register_client(producer["id"])
    contract = register_contract(
        producer["id"], client["id"], living_benefit_rider=False
    )
    payload = create_case_payload(producer["id"], client["id"], contract["id"])
    res = api.create_case(payload, compliance_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
