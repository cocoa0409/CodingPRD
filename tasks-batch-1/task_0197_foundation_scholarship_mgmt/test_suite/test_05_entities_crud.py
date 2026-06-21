"""Entity CRUD tests: creation defaults, required fields, not-found, listing,
pagination, type constraints, immutability, parent relationships, computed fields,
and filtered-list reads.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_applicant_headers,
    make_committee_member_headers,
    create_fund_payload,
    create_applicant_payload,
    create_application_payload,
    create_recommendation_payload,
    create_rubric_score_payload,
    assert_fund,
    fixtures,
)

ADMIN = TEST_USERS["foundation_admin_headers"]


# ===========================================================================
# Queue B — entities
# ===========================================================================
def test_create_fund_returns_201_with_system_fields(api):
    """PRD §3.1: "A freshly created fund opens in `DRAFT` status with `committed_cents`
    set to 0, `disbursed_cents` set to 0, `available_cents` equal to the full
    `endowment_cents`, and `version` at 1."

    Design: Corner/entities/create_scholarship_fund_returns_201_with_system_fields
    """
    payload = create_fund_payload(fund_name="F1", endowment_cents=1_000_000)
    fund = validate_success(api.create_fund(payload, ADMIN), 201)
    assert_fund(fund)
    assert fund["status"] == "DRAFT"
    assert fund["committed_cents"] == 0
    assert fund["disbursed_cents"] == 0
    assert fund["available_cents"] == 1_000_000
    assert fund["version"] == 1


def test_create_fund_default_award_term_is_fall(api):
    """PRD §3.1: "The disbursement term label `award_term` may be supplied; it is one
    of `FALL`, `SPRING`, or `SUMMER`, and defaults to `FALL` when omitted."

    Design: Corner/entities/create_fund_default_award_term_is_fall
    """
    payload = {"fund_name": "F2", "endowment_cents": 500_000}
    fund = validate_success(api.create_fund(payload, ADMIN), 201)
    assert fund["award_term"] == "FALL"


def test_create_fund_missing_required_field_rejected(api):
    """PRD §3.1: "A `FoundationAdmin` begins by creating a scholarship fund, supplying
    a `fund_name` and an `endowment_cents` total (which must be at least 0)."
    PRD §2.5: "Field-level input validation — required fields present, correct types,
    numeric ranges, enum membership, and pagination bounds — is the lowest-priority
    class and raises `ERR_INVALID_REQUEST` (or `ERR_INVALID_PAGINATION` for
    out-of-range pagination parameters)."

    Design: Corner/entities/create_fund_missing_required_field_returns_invalid_request
    """
    validate_error(api.create_fund({"fund_name": "NoEndow"}, ADMIN), ApiErrorId.ERR_INVALID_REQUEST)


def test_get_fund_nonexistent_returns_not_found(api):
    """PRD §2.4: "A path resource that does not exist yields a not-found error
    specific to its type: `ERR_FUND_NOT_FOUND`"

    Design: Corner/entities/get_fund_nonexistent_returns_not_found
    """
    validate_error(api.get_fund(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_FUND_NOT_FOUND)


def test_list_funds_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_funds_pagination_envelope
    """
    validate_success(api.create_fund(create_fund_payload(fund_name="A", endowment_cents=100_000), ADMIN), 201)
    validate_success(api.create_fund(create_fund_payload(fund_name="B", endowment_cents=100_000), ADMIN), 201)
    data, meta = validate_paginated(api.list_funds(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_list_funds_invalid_pagination_rejected(api):
    """PRD §2.3: "A `limit` or `offset` outside its allowed range is rejected with
    `ERR_INVALID_PAGINATION`."

    Design: Corner/entities/list_funds_invalid_pagination_returns_error
    """
    validate_error(
        api.list_funds(ADMIN, params={"limit": 101, "offset": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )


def test_applicant_self_reported_gpa_out_of_range_rejected(api):
    """PRD §3.2: "a `self_reported_gpa` (between 0.00 and 4.00)"
    PRD §2.5: "Field-level input validation — required fields present, correct types,
    numeric ranges, enum membership, and pagination bounds — is the lowest-priority
    class and raises `ERR_INVALID_REQUEST`"

    Design: Corner/entities/applicant_self_reported_gpa_out_of_range_rejected
    """
    payload = create_applicant_payload(self_reported_gpa=4.50)
    validate_error(api.create_applicant(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST)


def test_rubric_score_input_out_of_range_rejected(api):
    """PRD §3.4: "three integer raw scores, each in the range from 0 to 100"
    PRD §2.5: "Field-level input validation — required fields present, correct types,
    numeric ranges, enum membership, and pagination bounds — is the lowest-priority
    class and raises `ERR_INVALID_REQUEST`"

    Design: Corner/entities/rubric_score_input_out_of_range_rejected
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=100_000)
    member = fixtures.create_member()
    fixtures.assign_member(app["id"], member["id"])
    mh = make_committee_member_headers(member["id"])
    payload = create_rubric_score_payload(app["id"], member["id"], academic_score=150, need_score=50, essay_score=50)
    validate_error(api.create_rubric_score(payload, mh), ApiErrorId.ERR_INVALID_REQUEST)


def test_recommendation_immutable_has_no_version_field(api):
    """PRD §2.4: "recommendation and transcript records are immutable upload
    artifacts. Each carries only an `id` and a `created_at`; neither `updated_at` nor
    `version` is present on a recommendation or a transcript, because once uploaded
    they are never modified."

    Design: Corner/entities/recommendation_immutable_has_no_version_field
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=100_000)
    headers = make_applicant_headers(applicant["id"])
    rec = validate_success(
        api.create_recommendation(create_recommendation_payload(app["id"]), headers), 201
    )
    assert "id" in rec and rec["id"]
    assert "created_at" in rec
    assert "version" not in rec
    assert "updated_at" not in rec


def test_application_create_rejected_when_applicant_missing(api):
    """PRD §2.4: "Body foreign keys on create endpoints are subject to the same
    existence check: an unresolved `fund_id` raises `ERR_FUND_NOT_FOUND`, an unresolved
    `applicant_id` raises `ERR_APPLICANT_NOT_FOUND`, an unresolved `application_id`
    raises `ERR_APPLICATION_NOT_FOUND`, an unresolved `award_id` raises
    `ERR_AWARD_NOT_FOUND`, and an unresolved `committee_member_id` raises
    `ERR_COMMITTEE_MEMBER_NOT_FOUND`."

    Design: Corner/entities/application_create_rejected_when_applicant_id_missing_row
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    payload = create_application_payload(fund["id"], NON_EXISTENT_UUID, requested_amount_cents=100_000)
    validate_error(api.create_application(payload, ADMIN), ApiErrorId.ERR_APPLICANT_NOT_FOUND)


def test_fund_computed_ledger_fields_initialized_to_zero(api):
    """PRD §3.1: "A freshly created fund opens in `DRAFT` status with `committed_cents`
    set to 0"
    PRD §2.6: "The fund's derived monetary fields (`committed_cents`, `disbursed_cents`,
    `available_cents`) are recomputed as part of any ledger-affecting cascade and are
    never set directly by a client."

    Design: Corner/entities/fund_computed_ledger_fields_ignore_client_input
    """
    payload = create_fund_payload(fund_name="Ign", endowment_cents=1_000_000)
    fund = validate_success(api.create_fund(payload, ADMIN), 201)
    assert fund["committed_cents"] == 0


# ===========================================================================
# Queue B — endpoints (filtered lists)
# ===========================================================================
def test_filtered_list_applications_by_fund_id(api):
    """PRD §4: "List applications (filter by fund_id and/or applicant_id)"
    PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/filtered_list_applications_by_fund_id
    """
    fund_a = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    fund_b = fixtures.create_fund(endowment_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund_a["id"], applicant["id"], requested_amount_cents=100_000)
    data, meta = validate_paginated(api.list_applications(ADMIN, params={"fund_id": fund_a["id"]}))
    assert meta["total_count"] == 1
    assert all(a["fund_id"] == fund_a["id"] for a in data)


def test_filtered_list_recommendations_by_application_id(api):
    """PRD §4: "List recommendations (filter by application_id)"
    PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/filtered_list_recommendations_by_application_id
    """
    fund = fixtures.create_open_fund(endowment_cents=500_000, max_award_cents=500_000)
    applicant = fixtures.create_applicant()
    app = fixtures.create_application(fund["id"], applicant["id"], requested_amount_cents=100_000)
    fixtures.add_recommendation(app["id"], applicant["id"])
    data, meta = validate_paginated(
        api.list_recommendations(ADMIN, params={"application_id": app["id"]})
    )
    assert meta["total_count"] == 1
    assert all(r["application_id"] == app["id"] for r in data)
