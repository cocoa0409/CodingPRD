"""Role-based access control and reverse-reachability list reads."""
from test_helpers import (
    validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_consumer_headers, create_program_payload,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["program_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
FRAUD1 = TEST_USERS["fraud_analyst_1_headers"]


def test_consumer_cannot_approve_claim(api):
    """PRD §2.1: "Once authenticated, if the caller's role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/consumer_cannot_approve_claim
    """
    ctx = fx.setup_claim_under_review(api)
    consumer_headers = make_consumer_headers(ctx["consumer"]["id"])
    resp = api.approve_claim(ctx["claim"]["id"], ctx["program_version"], consumer_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert get_success_data(api.get_claim(ctx["claim"]["id"], ADMIN))["status"] == "UNDER_REVIEW"


def test_anonymous_cannot_create_program(api):
    """PRD §2.1: "When `X-User-Role` is `Anonymous`, the caller is an
    unauthenticated visitor whose identity is opaque and tied to no persisted
    entity; the only operation available is self-registration of a new consumer".

    Design: Corner/rbac/anonymous_cannot_create_program
    """
    payload = create_program_payload(
        eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0)
    resp = api.create_program(payload, ANON)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_fraudanalyst_cannot_open_program(api):
    """PRD §2.1: "Once authenticated, if the caller's role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/fraudanalyst_cannot_open_program
    """
    program = fx.create_program(
        api, eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0)
    resp = api.open_program(program["id"], FRAUD1)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert get_success_data(api.get_program(program["id"], PM))["status"] == "DRAFT"


def test_consumer_cannot_submit_others_claim(api):
    """PRD §2.1: "Ownership checks on any resource that references a consumer
    compare that resource's `consumer_id` to `X-User-ID` ... A consumer acting on
    a claim they do not own is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/consumer_cannot_submit_others_claim
    """
    fx.set_clock(api)
    program = fx.create_open_program(
        api, eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0)
    consumer_a = fx.register_consumer(api)
    consumer_b = fx.register_consumer(api)
    claim = fx.create_claim(api, consumer_a, program["id"], claimed_amount_cents=25000)
    # Consumer B attempts to submit Consumer A's claim.
    resp = api.submit_claim(claim["id"], make_consumer_headers(consumer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert get_success_data(api.get_claim(claim["id"], ADMIN))["status"] == "DRAFT"


def test_claims_filtered_by_consumer_id(api):
    """PRD §4 (GET /rebate-aggregator/claims): "List claims (filter by
    consumer_id, program_id, status)". PRD §2.1: "a consumer reading their claims,
    documents, matches, payouts, notifications, or eligibility assessments sees
    only their own."

    Design: Corner/endpoints/claims_filtered_by_consumer_id
    """
    program = fx.create_open_program(
        api, eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0)
    consumer = fx.register_consumer(api)
    claim = fx.create_claim(api, consumer, program["id"], claimed_amount_cents=12000)
    resp = api.list_claims(make_consumer_headers(consumer["id"]),
                          params={"consumer_id": consumer["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == claim["id"]


def test_notifications_reverse_list_after_submit(api):
    """PRD §3.3: "When all five pass, submission stamps `submitted_at` to the
    current instant, computes the forward-looking `provisional_payout_cents`, and
    sends the consumer a `Notification` with `event_type` `CLAIM_SUBMITTED`."

    Design: Corner/endpoints/notifications_reverse_list_after_submit
    """
    fx.set_clock(api)
    program = fx.create_open_program(api)
    consumer = fx.register_verified_consumer(api)
    claim = fx.create_claim(api, consumer, program["id"], claimed_amount_cents=25000)
    fx.add_document(api, claim, consumer)
    fx.submit_claim(api, claim, consumer)
    resp = api.list_notifications(consumer["id"], make_consumer_headers(consumer["id"]))
    data, _meta = validate_paginated(resp)
    assert len(data) >= 1
    assert any(n["event_type"] == "CLAIM_SUBMITTED" for n in data)
