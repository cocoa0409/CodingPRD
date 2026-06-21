"""Entity creation: defaults, required fields, FK existence, immutability, computed seeds.

Translates the Corner/entities section.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, NON_EXISTENT_UUID,
    assert_client, assert_skill, assert_job_order,
    create_skill, create_client,
    make_account_manager_headers, make_recruiter_headers,
)

AM = make_account_manager_headers()
RECRUITER = make_recruiter_headers()


def test_create_client_returns_201_with_defaults(api):
    """PRD 3.1: "A newly created client begins with `status` of `ACTIVE`, with
    `outstanding_balance_cents` and `open_exposure_cents` both at zero."
    PRD 3.1: "this value must be greater than 0 and at most 1, and when omitted it defaults to
    0.20, that is, twenty percent."
    PRD 2.4: "a `version` integer that begins at 1 on creation."

    Design: Corner/entities/create_client_returns_201_with_defaults
    """
    resp = api.create_client({"name": "Acme", "credit_limit_cents": 5000000}, AM)
    data = validate_success(resp, expected_status=201)
    assert_client(data)
    assert data["status"] == "ACTIVE", f"status {data['status']}"
    assert data["outstanding_balance_cents"] == 0, f"outstanding {data['outstanding_balance_cents']}"
    assert data["open_exposure_cents"] == 0, f"exposure {data['open_exposure_cents']}"
    assert data["conversion_fee_pct"] == 0.20, f"conversion_fee_pct {data['conversion_fee_pct']}"
    assert data["version"] == 1, f"version {data['version']}"


def test_create_candidate_missing_skill_codes_returns_422(api):
    """PRD 3.1: "A `Recruiter` builds the talent pool by registering a **Candidate** with a
    `full_name`, an array of `skill_codes`, and a `base_pay_rate_cents`."
    PRD 2.6: "a body missing a required field ... is rejected with `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/entities/create_candidate_missing_skill_codes_returns_422
    """
    resp = api.create_candidate({"full_name": "No Skills", "base_pay_rate_cents": 8000}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_candidate_with_unknown_skill_code_returns_skill_not_found(api):
    """PRD 3.1: "Every code in `skill_codes` must reference an existing entry in the skill catalog;
    a code with no matching catalog entry is rejected as a missing skill reference."
    PRD 2.5: "the first unresolved reference yields the corresponding not-found error —
    ... `ERR_SKILL_NOT_FOUND` ... each returned with HTTP 404."

    Design: Corner/entities/candidate_skill_code_unknown_returns_skill_not_found
    """
    resp = api.create_candidate(
        {"full_name": "Ghost Skill", "skill_codes": ["NOPE"], "base_pay_rate_cents": 8000}, RECRUITER)
    validate_error(resp, ApiErrorId.ERR_SKILL_NOT_FOUND)


def test_get_nonexistent_client_returns_not_found(api):
    """PRD 2.5: "A request naming a submission, placement, or invoice that does not exist is
    rejected with that parent's not-found error before any child lookup occurs."
    PRD 2.5: "the first unresolved reference yields the corresponding not-found error —
    `ERR_CLIENT_NOT_FOUND` ... each returned with HTTP 404."

    Design: Corner/entities/get_client_nonexistent_returns_not_found
    """
    resp = api.get_client(NON_EXISTENT_UUID, AM)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND)


def test_skill_is_immutable_and_code_uppercased(api):
    """PRD 3.1: "The code is uppercased before it is stored — so a submission of "java" persists
    as "JAVA"."
    PRD 2.4: "Two resource types are immutable configuration or ledger records and therefore carry
    only `id` and `created_at`; they have neither an `updated_at` nor a `version` field. These are
    the `Skill` catalog entry and the `InvoiceLineItem`."

    Design: Corner/entities/skill_immutable_no_version_field
    """
    resp = api.create_skill({"code": "java", "category": "TECH"}, RECRUITER)
    data = validate_success(resp, expected_status=201)
    assert_skill(data)
    assert data["code"] == "JAVA", f"code should be uppercased to JAVA, got {data['code']!r}"
    assert "version" not in data, "Skill must not carry a version field"
    assert "updated_at" not in data, "Skill must not carry an updated_at field"


def test_duplicate_skill_code_returns_conflict(api):
    """PRD 3.1: "it must be unique across the catalog; an attempt to register a code that already
    exists (after uppercasing) is rejected with `ERR_SKILL_CODE_DUPLICATE`."

    Design: Corner/entities/skill_duplicate_code_returns_conflict
    """
    create_skill(code="JAVA", category="TECH")
    resp = api.create_skill({"code": "java", "category": "TECH"}, AM)
    validate_error(resp, ApiErrorId.ERR_SKILL_CODE_DUPLICATE)


def test_job_order_created_draft_with_zero_filled_count(api):
    """PRD 3.2: "A job order is created in `status` `DRAFT` with a `filled_count` of 0, and
    `filled_count` is thereafter a read-only count of this order's placements whose
    `assignment_status` is `ACTIVE`."

    Design: Corner/entities/job_order_filled_count_computed_starts_zero
    """
    create_skill(code="JAVA", category="TECH")
    cl = create_client(name="Acme")
    resp = api.create_job_order(
        {"client_id": cl["id"], "title": "Dev", "employment_type": "TEMP",
         "required_skill_code": "JAVA", "openings": 3, "bill_rate_cents": 12000,
         "target_pay_rate_cents": 8000}, AM)
    data = validate_success(resp, expected_status=201)
    assert_job_order(data)
    assert data["filled_count"] == 0, f"filled_count {data['filled_count']}"
    assert data["status"] == "DRAFT", f"status {data['status']}"
