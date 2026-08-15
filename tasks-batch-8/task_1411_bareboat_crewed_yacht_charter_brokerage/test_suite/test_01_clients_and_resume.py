"""Client qualification lifecycle, resume review RBAC, bareboat submit gates,
and the segregation-of-duties rule at request creation."""
from test_helpers import (
    ApiErrorId,
    assert_charter_request,
    create_broker_payload,
    create_client,
    create_listed_yacht,
    create_operator,
    create_qualified_client,
    create_request,
    create_resume_payload,
    make_client_headers,
    make_retail_broker_headers,
    review_resume,
    submit_resume,
    TEST_USERS,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_resume_rejected_resubmit_cycle(api, platform_admin_headers):
    """PRD section 3.1: "Rejection is not the end of the road: a `REJECTED`
    client may resubmit a revised resume, which re-enters `PENDING_REVIEW` and
    overwrites `resume_class`, `skippered_hours`, and `resume_submitted_at`
    with the new declarations."

    Design: Corner/state_machines/resume_rejected_resubmit_cycle
    """
    client = create_client()

    pending = submit_resume(client["id"], resume_class="COASTAL", skippered_hours=40)
    assert pending["qualification_status"] == "PENDING_REVIEW"

    rejected = review_resume(client["id"], "REJECTED")
    assert rejected["qualification_status"] == "REJECTED"

    resubmitted = submit_resume(client["id"], resume_class="OFFSHORE",
                                skippered_hours=300)
    assert resubmitted["qualification_status"] == "PENDING_REVIEW", (
        "a REJECTED client may resubmit a revised resume, re-entering "
        "PENDING_REVIEW")

    qualified = review_resume(client["id"], "QUALIFIED")
    assert qualified["qualification_status"] == "QUALIFIED"
    assert qualified["resume_class"] == "OFFSHORE"
    assert qualified["skippered_hours"] == 300, (
        "the resubmission overwrites resume_class and skippered_hours with "
        "the new declarations")


def test_client_cannot_review_own_resume(api, platform_admin_headers):
    """PRD section 3.1: "A `PlatformAdmin` then reviews the submission,
    recording an `outcome` of `QUALIFIED` or `REJECTED`, which settles the
    client into the corresponding state."
    PRD section 2.1: "A well-authenticated caller who attempts an operation
    not open to their role, or who violates an ownership rule — an operator
    touching another operator's yacht, a non-party acting on a request or
    agreement, an offer issued by a broker who is not the listing central
    agent — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/client_cannot_review_own_resume
    """
    client = create_client()
    submit_resume(client["id"])

    res = api.review_resume(client["id"], {"outcome": "QUALIFIED"},
                            make_client_headers(client["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    after = validate_success(api.get_client(client["id"], ADMIN), 200)
    assert after["qualification_status"] == "PENDING_REVIEW", (
        "a rejected review attempt must leave the client's qualification "
        "status untouched")


def test_submit_pending_review_client_rejected_not_qualified(api):
    """PRD section 3.3: "For a `BAREBOAT` yacht, two qualification gates
    follow: the client's `qualification_status` must be `QUALIFIED`, else
    `ERR_CLIENT_NOT_QUALIFIED`, and the client's `resume_class` must rank at
    or above the yacht's `required_resume_class` on the `NONE`-to-`OCEAN`
    ladder, else `ERR_RESUME_CLASS_INSUFFICIENT`; a `CREWED` yacht skips both
    gates, since a professional crew carries the vessel."

    Design: Difficulty/cross_entity_state_dependency/submit_gated_by_client_qualification
    """
    operator = create_operator()
    ca = create_broker_payload()
    central_agent = validate_success(api.create_broker(ca, ADMIN), 201)
    pending_client = create_client(full_name="Pend Ing", email="p@example.com")
    submit_resume(pending_client["id"], resume_class="OFFSHORE",
                  skippered_hours=300)  # stays PENDING_REVIEW: never reviewed
    yacht = create_listed_yacht(operator["id"], central_agent["id"],
                                required_resume_class="OFFSHORE")

    request = create_request(pending_client["id"], yacht["id"])
    res = api.submit_charter_request(
        request["id"], make_client_headers(pending_client["id"]))
    validate_error(res, ApiErrorId.ERR_CLIENT_NOT_QUALIFIED, expected_status=422)

    after = validate_success(
        api.get_charter_request(request["id"],
                                make_client_headers(pending_client["id"])), 200)
    assert after["status"] == "DRAFT", "a rejected submit must not transition"


def test_submit_qualified_but_resume_class_insufficient(api):
    """PRD section 3.3: "For a `BAREBOAT` yacht, two qualification gates
    follow: the client's `qualification_status` must be `QUALIFIED`, else
    `ERR_CLIENT_NOT_QUALIFIED`, and the client's `resume_class` must rank at
    or above the yacht's `required_resume_class` on the `NONE`-to-`OCEAN`
    ladder, else `ERR_RESUME_CLASS_INSUFFICIENT`; a `CREWED` yacht skips both
    gates, since a professional crew carries the vessel."

    Design: Difficulty/cross_entity_state_dependency/submit_gated_by_client_qualification
    """
    operator = create_operator()
    central_agent = validate_success(
        api.create_broker(create_broker_payload(), ADMIN), 201)
    coastal_client = create_qualified_client(resume_class="COASTAL",
                                             skippered_hours=120,
                                             full_name="Coast Al",
                                             email="q@example.com")
    yacht = create_listed_yacht(operator["id"], central_agent["id"],
                                required_resume_class="OFFSHORE")

    request = create_request(coastal_client["id"], yacht["id"])
    res = api.submit_charter_request(
        request["id"], make_client_headers(coastal_client["id"]))
    validate_error(res, ApiErrorId.ERR_RESUME_CLASS_INSUFFICIENT,
                   expected_status=422)

    after = validate_success(
        api.get_charter_request(request["id"],
                                make_client_headers(coastal_client["id"])), 200)
    assert_charter_request(after)
    assert after["status"] == "DRAFT", (
        "COASTAL ranks below OFFSHORE on the NONE-to-OCEAN ladder, so the "
        "request must stay DRAFT")


def test_broker_conflict_of_interest_rejected(api):
    """PRD section 3.3: "Either way, segregation of duties is enforced at
    creation, ahead of the field-level gates: the deal's retail broker —
    caller or supplied — must differ from the yacht's
    `listing_central_agent_id`, or the creation is rejected with
    `ERR_BROKER_CONFLICT_OF_INTEREST`."

    Design: Corner/validations/broker_conflict_of_interest_rejected
    """
    operator = create_operator()
    both_broker = validate_success(
        api.create_broker(create_broker_payload(display_name="Both Broker",
                                                broker_type="BOTH",
                                                license_no="LIC-B-1"), ADMIN),
        201)
    client = create_qualified_client()
    yacht = create_listed_yacht(operator["id"], both_broker["id"])

    # The BOTH broker is the yacht's listing central agent; acting as the
    # RetailBroker creator would put the same broker on both sides of the deal.
    res = api.create_charter_request(
        {"client_id": client["id"], "yacht_id": yacht["id"],
         "start_date": "2026-10-01", "end_date": "2026-10-11",
         "guests_count": 4},
        make_retail_broker_headers(both_broker["id"]))
    validate_error(res, ApiErrorId.ERR_BROKER_CONFLICT_OF_INTEREST,
                   expected_status=422)

    data, meta = validate_paginated(api.list_charter_requests(
        ADMIN, params={"client_id": client["id"]}))
    assert meta["total_count"] == 0 and data == [], (
        "a creation rejected for conflict of interest must persist nothing")
