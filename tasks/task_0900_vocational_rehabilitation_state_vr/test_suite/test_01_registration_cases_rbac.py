"""Registration, case creation, envelope, and cross-cutting RBAC.

Corner-design queue (§1.9): entities, endpoints, and rbac sections.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_valid_uuid, NON_EXISTENT_UUID, TEST_USERS,
    create_counselor, create_referral, bootstrap_actors, make_counselor_headers,
    create_case_payload, create_provider_payload, create_counselor_payload,
    assert_case, assert_provider,
)

VRADMIN = TEST_USERS["vradmin_headers"]


def test_case_creation_returns_referred(api):
    """PRD §3.2: "The new case begins in `REFERRED`, its `counselor_id` is set from
    `X-User-ID`, its fund fields are initialized, and its `priority_category_id`,
    `disability_significance`, `waitlisted_at`, `closure_type`, and `closure_reason`
    are all null."
    PRD §2.4: "an integer `version` that starts at 1 and increments by one on every mutation."

    Design: Corner/entities/case_creation_returns_referred
    """
    counselor = create_counselor()
    headers = make_counselor_headers(counselor["id"])
    res = api.create_case(create_case_payload(budget_allocated_cents=0), headers)
    case = validate_success(res, 201)
    assert_case(case)
    assert case["status"] == "REFERRED"
    assert case["version"] == 1
    assert case["priority_category_id"] is None
    assert case["counselor_id"] == counselor["id"]


def test_case_get_nonexistent_returns_not_found(api):
    """PRD §2.5: "any identifier that does not resolve to an existing resource yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/case_get_nonexistent_returns_not_found
    """
    res = api.get_case(NON_EXISTENT_UUID, VRADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_case_create_missing_required_field_validation(api):
    """PRD §2.10: "then body well-formedness (`ERR_VALIDATION`, HTTP 422 — required
    fields present, correct types, enums in range, dates parseable, and
    `service_period_start` not later than `service_period_end`)."

    Design: Corner/entities/case_create_missing_required_field_validation
    """
    counselor = create_counselor()
    headers = make_counselor_headers(counselor["id"])
    payload = create_case_payload()
    del payload["consumer_full_name"]
    res = api.create_case(payload, headers)
    validate_error(res, "ERR_VALIDATION")


def test_case_create_invalid_enum_disability_type_validation(api):
    """PRD §3.2: "the `disability_type` (one of `PHYSICAL`, `COGNITIVE`,
    `PSYCHIATRIC`, or `SENSORY`)".
    PRD §2.10: "then body well-formedness (`ERR_VALIDATION`, HTTP 422 — required
    fields present, correct types, enums in range, dates parseable, and
    `service_period_start` not later than `service_period_end`)."

    Design: Corner/entities/case_create_invalid_enum_disability_type_validation
    """
    counselor = create_counselor()
    headers = make_counselor_headers(counselor["id"])
    res = api.create_case(create_case_payload(disability_type="BOGUS"), headers)
    validate_error(res, "ERR_VALIDATION")


def test_provider_status_defaults_active(api):
    """PRD §3.1: "A provider's `status` may be supplied at onboarding as `ACTIVE` or
    `SUSPENDED`; when omitted it defaults to `ACTIVE`. A provider's ledger fields
    `pending_disbursement_cents` and `ledger_paid_cents` are initialized to zero".

    Design: Corner/entities/provider_status_defaults_active
    """
    res = api.create_provider(
        create_provider_payload(name="P1", service_categories=["TRAINING"],
                                max_concurrent_authorizations=3), VRADMIN)
    provider = validate_success(res, 201)
    assert_provider(provider)
    assert provider["status"] == "ACTIVE"
    assert provider["pending_disbursement_cents"] == 0
    assert provider["ledger_paid_cents"] == 0


def test_list_cases_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response reports `limit`, `offset`,
    `total_count` (the total number of records matching the filter, before
    pagination), and `has_more` (true when records remain beyond the current page)."

    Design: Corner/entities/list_cases_pagination_envelope
    """
    ctx = bootstrap_actors(provider=False)
    create_referral(ctx, consumer_full_name="Al Ray")
    create_referral(ctx, consumer_full_name="Bo Ray", disability_type="SENSORY")

    data, meta = validate_paginated(api.list_cases(VRADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_response_envelope_success_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.4: "Every resource carries a server-minted `id` formatted as a UUID with
    no type prefix, and a `created_at` ISO 8601 UTC timestamp with three fractional
    digits recorded at creation."

    Design: Corner/endpoints/response_envelope_success_shape
    """
    res = api.create_counselor(create_counselor_payload(), VRADMIN)
    assert res.status_code == 201
    body = res.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["response_type"] == "object"
    assert is_valid_uuid(body["data"]["id"])


def test_counselor_cannot_create_provider_forbidden(api):
    """PRD §2.1: "If the role is recognized but not permitted for the requested
    operation — or if an ownership-scoped role acts on a resource it does not own —
    the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/counselor_cannot_create_provider_forbidden
    """
    counselor = create_counselor()
    headers = make_counselor_headers(counselor["id"])
    res = api.create_provider(
        create_provider_payload(name="P1", service_categories=["TRAINING"],
                                max_concurrent_authorizations=3), headers)
    validate_error(res, "ERR_FORBIDDEN")


def test_counselor_cannot_act_on_other_counselors_case_forbidden(api):
    """PRD §2.1: "Ownership checks on any case compare the case's `counselor_id` to
    `X-User-ID`: a Counselor may drive application, eligibility, IPE authoring,
    authorization requests, placements, progress reviews, and closure only on cases
    it owns."

    Design: Corner/rbac/counselor_cannot_act_on_other_counselors_case_forbidden
    """
    c1 = create_counselor(email="c1@vr.gov")
    c2 = create_counselor(email="c2@vr.gov")
    case = validate_success(api.create_case(create_case_payload(), make_counselor_headers(c1["id"])), 201)
    res = api.record_application(case["id"], make_counselor_headers(c2["id"]))
    validate_error(res, "ERR_FORBIDDEN")
    unchanged = validate_success(api.get_case(case["id"], VRADMIN), 200)
    assert unchanged["status"] == "REFERRED"


def test_create_case_without_role_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the five recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/create_case_without_role_returns_unauthenticated
    """
    res = api.create_case(create_case_payload(), {"X-User-ID": "nobody"})
    validate_error(res, "ERR_UNAUTHENTICATED")
