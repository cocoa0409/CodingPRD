"""The reply workflow: draft, submit, approve, reject, revise, publish."""

from test_helpers import (
    ApiErrorId,
    assert_review_response,
    create_listing,
    create_review_response_payload,
    create_template,
    draft_response,
    ingest_review,
    make_admin_headers,
    read_listing,
    read_location,
    read_review,
    read_review_response,
    reject_response,
    setup_approved_response,
    setup_bare_location,
    setup_location_with_connected_listings,
    setup_pending_approval_response,
    submit_response,
    sync_listing,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# The DRAFT -> PENDING_APPROVAL -> REJECTED -> DRAFT cycle
# ---------------------------------------------------------------------------
def _setup_rejected_response():
    env = setup_location_with_connected_listings(sites=("GOOGLE",))
    review = ingest_review(env["location"]["id"], rating=5)
    response = setup_pending_approval_response(review["id"], body="Thanks a lot")
    reject_response(response["id"], reason="Tone too casual")
    env["review"] = review
    env["response"] = read_review_response(response["id"])
    return env


def test_revising_a_rejected_reply_returns_it_to_draft_and_counts_the_revision(
    api, response_agent_headers
):
    """PRD §3.4: "**Revision** closes the cycle. The drafting agent takes a `REJECTED`
    response back to `DRAFT` by supplying a replacement `body`; this raises
    `revision_count` by one and returns the review's reply dimension to `DRAFTED`."

    Design: Difficulty/non_linear_state_machine/response_reject_revise_cycle_returns_to_draft
    """
    env = _setup_rejected_response()
    response_id = env["response"]["id"]
    assert env["response"]["state"] == "REJECTED"
    assert env["response"]["revision_count"] == 0

    revised = validate_success(
        api.revise_review_response(
            response_id, {"body": "Thank you for your kind words."}, response_agent_headers
        )
    )
    assert_review_response(revised)

    assert revised["state"] == "DRAFT"
    assert revised["revision_count"] == 1
    assert revised["body"] == "Thank you for your kind words."
    assert read_review(env["review"]["id"])["response_state"] == "DRAFTED"


def test_resubmitting_a_revised_reply_reenters_pending_approval(api, response_agent_headers):
    """PRD §3.4: "The loop `DRAFT → PENDING_APPROVAL → REJECTED → DRAFT` may be walked as
    many times as needed."
    PRD §3.4: "If the response has no template at all, *or* if its backing template has
    `requires_approval` set to true, the submit takes the response `DRAFT →
    PENDING_APPROVAL` and the review's reply dimension `DRAFTED → AWAITING_APPROVAL`."

    Design: Difficulty/non_linear_state_machine/response_reject_revise_cycle_returns_to_draft
    """
    env = _setup_rejected_response()
    response_id = env["response"]["id"]
    validate_success(
        api.revise_review_response(
            response_id, {"body": "Thank you for your kind words."}, response_agent_headers
        )
    )

    resubmitted = validate_success(
        api.submit_review_response(response_id, response_agent_headers)
    )
    assert resubmitted["state"] == "PENDING_APPROVAL"
    assert resubmitted["revision_count"] == 1
    assert read_review(env["review"]["id"])["response_state"] == "AWAITING_APPROVAL"


# ---------------------------------------------------------------------------
# Publication needs a CONNECTED listing for the review's own site
# ---------------------------------------------------------------------------
def _setup_approved_reply_on_an_unconnected_site():
    """GOOGLE CONNECTED, YELP still PENDING_SYNC; the review under reply lives on YELP."""
    env = setup_bare_location()
    location_id = env["location"]["id"]
    google = create_listing(location_id, "GOOGLE")
    create_listing(location_id, "YELP")
    sync_listing(google["id"], "SUCCESS")

    review = ingest_review(location_id, site="YELP", external_review_id="y-r1", rating=5)
    env["review"] = review
    env["response"] = setup_approved_response(review["id"])
    return env


def test_publishing_to_a_site_whose_listing_is_not_connected_is_rejected(
    api, compliance_officer_headers
):
    """PRD §3.4: "**Publication** is the terminal act, performed by a
    `ComplianceOfficer` on an `APPROVED` response, and it demands a live channel: a
    listing must exist for the review's own location and site combination, and that
    listing's `sync_state` must be `CONNECTED`. A missing listing, or one in any other
    sync state, is rejected with `ERR_LISTING_NOT_CONNECTED` (409)."

    Design: Difficulty/cross_entity_state_dependency/response_publish_requires_connected_listing_for_review_site
    """
    env = _setup_approved_reply_on_an_unconnected_site()

    resp = api.publish_review_response(env["response"]["id"], compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_CONNECTED.value)

    yelp = read_listing(env["location"]["id"], "YELP")
    assert yelp["sync_state"] == "PENDING_SYNC", (
        "the CONNECTED GOOGLE listing of the same location does not stand in for YELP"
    )


def test_a_rejected_publish_leaves_the_reply_approved_and_the_review_not_responded(
    api, compliance_officer_headers
):
    """PRD §3.4: "On success the response reaches `PUBLISHED` — a terminal state — and
    `published_at` is stamped. That is link one of the publish chain: the review's reply
    dimension advances `APPROVED → RESPONDED`; link two resolves every escalation of that
    review still sitting in `OPEN` or `ACKNOWLEDGED`; and link three drops the location's
    `open_escalation_count` by one for each escalation so resolved, refreshes
    `responded_review_count`, recomputes `reputation_score_provisional`, and re-derives
    `posture` — which is how a location earns its way back from `RESTRICTED` to `OPEN`
    once all three degradation predicates clear."

    Design: Difficulty/cross_entity_state_dependency/response_publish_requires_connected_listing_for_review_site
    """
    env = _setup_approved_reply_on_an_unconnected_site()

    resp = api.publish_review_response(env["response"]["id"], compliance_officer_headers)
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_CONNECTED.value)

    response = read_review_response(env["response"]["id"])
    assert response["state"] == "APPROVED", "the rejected publish must not move the response"
    assert response["published_at"] is None

    review = read_review(env["review"]["id"])
    assert review["response_state"] == "APPROVED", "the reply dimension must not reach RESPONDED"
    assert read_location(env["location"]["id"])["responded_review_count"] == 0


# ---------------------------------------------------------------------------
# Templates, the approval flag, RBAC and OCC on the reply surface
# ---------------------------------------------------------------------------
def test_template_whose_band_excludes_the_reviews_rating_is_rejected(
    api, response_agent_headers
):
    """PRD §3.4: "When a `template_id` is supplied, the template's rating band must
    contain the review's rating: the template's `min_rating` must be at or below the
    review's `rating` and its `max_rating` at or above it. A band that does not contain
    the rating is rejected with `ERR_TEMPLATE_RATING_MISMATCH` (422)."

    Design: Corner/validations/template_outside_review_rating_band_is_rejected
    """
    env = setup_bare_location()
    template = create_template(
        env["business"]["id"],
        {"name": "Praise", "body": "Thanks for the kind words!", "min_rating": 4, "max_rating": 5},
    )
    review = ingest_review(env["location"]["id"], rating=2, author_name="Bob", text="Not great")

    payload = create_review_response_payload(
        review["version"], body="Thanks for the kind words!", template_id=template["id"]
    )
    resp = api.create_review_response(review["id"], payload, response_agent_headers)
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_RATING_MISMATCH.value)

    assert read_review(review["id"])["response_state"] == "NONE"
    rows = validate_success(
        api.list_review_responses(response_agent_headers, {"review_id": review["id"]})
    )
    assert rows == [], "no ReviewResponse row may be created"


def test_template_with_requires_approval_false_skips_the_approval_hop(
    api, response_agent_headers, compliance_officer_headers
):
    """PRD §3.4: "If, and only if, the response has a non-null `template_id` whose
    template has `requires_approval` set to false, the submit collapses the approval hop
    entirely: the response goes straight `DRAFT → APPROVED` and the review's reply
    dimension goes straight `DRAFTED → APPROVED`. Because no human approved it,
    `approved_by_user_id` is explicitly left null, and the segregation-of-duties check is
    bypassed altogether."

    Design: Corner/cross_cutting_complexity_layers/template_with_requires_approval_false_skips_the_approval_hop
    """
    env = setup_location_with_connected_listings(sites=("GOOGLE",))
    template = create_template(
        env["business"]["id"],
        {
            "name": "Auto Thanks",
            "body": "Thanks for the feedback!",
            "min_rating": 1,
            "max_rating": 5,
            "requires_approval": False,
        },
    )
    review = ingest_review(env["location"]["id"], rating=5)
    response = draft_response(
        review["id"], body="Thanks for the feedback!", template_id=template["id"]
    )

    submitted = validate_success(
        api.submit_review_response(response["id"], response_agent_headers)
    )
    assert submitted["state"] == "APPROVED", "the flag collapses submit and approve into one hop"
    assert submitted["approved_by_user_id"] is None, "auto-approval carries no human approver"
    assert read_review(review["id"])["response_state"] == "APPROVED"

    published = validate_success(
        api.publish_review_response(response["id"], compliance_officer_headers)
    )
    assert published["state"] == "PUBLISHED"
    assert read_review(review["id"])["response_state"] == "RESPONDED"
    assert read_location(env["location"]["id"])["responded_review_count"] == 1


def test_response_agent_may_not_approve_a_reply(api, response_agent_headers):
    """PRD §2.1: "`ResponseAgent` and `ComplianceOfficer` are deliberately disjoint by
    role — an agent drafts, submits and revises but never approves, rejects or publishes;
    an officer approves, rejects and publishes but never drafts or revises."
    PRD §2.1: "A role that is not listed among the target endpoint's authorized roles is
    rejected with `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/response_agent_cannot_approve_a_response
    """
    env = setup_bare_location()
    review = ingest_review(env["location"]["id"], rating=5)
    response = setup_pending_approval_response(review["id"])

    resp = api.approve_review_response(response["id"], response_agent_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    after = read_review_response(response["id"])
    assert after["state"] == "PENDING_APPROVAL"
    assert after["approved_by_user_id"] is None


def test_the_drafter_may_not_approve_their_own_reply_however_privileged(api):
    """PRD §3.4: "Both are guarded by segregation of duties: the acting `X-User-ID` must
    differ from the response's `drafted_by_user_id`, and a self-approval or
    self-rejection is rejected with `ERR_SEGREGATION_OF_DUTIES` (403) regardless of how
    privileged the actor's role is."
    PRD §3.4: "Approving takes the response `PENDING_APPROVAL → APPROVED`, stamps
    `approved_by_user_id` with the approver's `X-User-ID`, and moves the review's reply
    dimension to `APPROVED`."

    Design: Corner/rbac/same_user_cannot_approve_the_response_they_drafted
    """
    admin_1 = make_admin_headers("admin-1")
    admin_2 = make_admin_headers("admin-2")

    env = setup_bare_location()
    review = ingest_review(env["location"]["id"], rating=5)
    response = draft_response(review["id"], headers=admin_1)
    submit_response(response["id"], headers=admin_1)

    resp = api.approve_review_response(response["id"], admin_1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    approved = validate_success(api.approve_review_response(response["id"], admin_2))
    assert approved["state"] == "APPROVED"
    assert approved["approved_by_user_id"] == "admin-2"
    assert approved["drafted_by_user_id"] == "admin-1"
    assert read_review(review["id"])["response_state"] == "APPROVED"


def test_second_draft_carrying_the_pre_draft_review_version_is_stale(
    api, response_agent2_headers
):
    """PRD §2.8: "Creating a reply to a review requires `expected_review_version`,
    carrying the client's last observed `version` of that `Review`. If it does not equal
    the review's current `version`, the create is rejected with `ERR_STALE_VERSION`
    (412)."
    PRD §2.9: "7. Optimistic concurrency — `expected_location_version` and
    `expected_review_version` (`ERR_STALE_VERSION`)."

    Design: Corner/cross_cutting_complexity_layers/stale_review_version_on_response_create_returns_412
    """
    env = setup_bare_location()
    review = ingest_review(env["location"]["id"], rating=5)
    observed_version = review["version"]
    first = draft_response(review["id"], body="Thank you!")

    resp = api.create_review_response(
        review["id"],
        create_review_response_payload(observed_version, body="A competing draft"),
        response_agent2_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    rows = validate_success(
        api.list_review_responses(response_agent2_headers, {"review_id": review["id"]})
    )
    assert len(rows) == 1, "the stale create must not add a second ReviewResponse"
    assert read_review_response(first["id"])["state"] == "DRAFT"
    assert read_review(review["id"])["response_state"] == "DRAFTED"
