"""Review ingest, sentiment, the two parallel state dimensions, and moderation."""

from test_helpers import (
    ApiErrorId,
    assert_alert_severity,
    assert_review,
    assert_score,
    build_user_headers,
    draft_response,
    flag_review,
    ingest_review,
    ingest_review_payload,
    read_alerts,
    read_dashboard,
    read_escalations,
    read_location,
    read_open_escalation,
    read_review,
    read_review_response,
    setup_bare_location,
    setup_location_with_connected_listings,
    validate_error,
    validate_success,
    verify_review,
)


# ---------------------------------------------------------------------------
# Parallel state dimensions
# ---------------------------------------------------------------------------
def test_verify_moves_moderation_and_leaves_the_reply_dimension_drafted(api, admin_headers):
    """PRD §3.3: "A `Review` is unusual in that it lives in **two independent state
    dimensions at once**, and an action in one leaves the other completely untouched."
    PRD §3.3: "The first dimension is `moderation_state`, which tracks authenticity.
    Every review lands at `UNVERIFIED`. A `LocationManager` may confirm it, taking it
    `UNVERIFIED → VERIFIED`, or repudiate it, taking it `UNVERIFIED → FLAGGED` or
    `VERIFIED → FLAGGED`."

    Design: Difficulty/non_linear_state_machine/review_parallel_dimensions_evolve_independently
    """
    env = setup_location_with_connected_listings(sites=("GOOGLE",))
    review = ingest_review(env["location"]["id"], rating=5)
    response = draft_response(review["id"], body="Thank you!")
    assert read_review(review["id"])["response_state"] == "DRAFTED"

    verified = validate_success(api.verify_review(review["id"], admin_headers))
    assert_review(verified)

    assert verified["moderation_state"] == "VERIFIED"
    assert verified["response_state"] == "DRAFTED", (
        "the reply dimension is independent and must not be disturbed by moderation"
    )
    assert read_review_response(response["id"])["state"] == "DRAFT"


def test_drafting_a_reply_moves_the_reply_dimension_and_leaves_moderation_unverified(
    api, response_agent_headers
):
    """PRD §3.4: "Creating it flips the review's reply dimension `NONE → DRAFTED` and
    increments the review's `version` by one."
    PRD §3.4: "The response is attached to the review by `review_id`, is created in
    `state` `DRAFT`, and records the acting `X-User-ID` in `drafted_by_user_id` — the
    key on which segregation of duties will later turn."

    Design: Difficulty/non_linear_state_machine/review_parallel_dimensions_evolve_independently
    """
    env = setup_location_with_connected_listings(sites=("GOOGLE",))
    review = ingest_review(env["location"]["id"], rating=5)

    response = draft_response(review["id"], body="Thank you!")
    assert response["state"] == "DRAFT"
    assert response["drafted_by_user_id"] == "agent-1"

    after = read_review(review["id"])
    assert after["response_state"] == "DRAFTED"
    assert after["moderation_state"] == "UNVERIFIED", (
        "drafting a reply must not touch the moderation dimension"
    )
    assert after["version"] == review["version"] + 1


# ---------------------------------------------------------------------------
# The escalation counter is conserved across ingest -> flag
# ---------------------------------------------------------------------------
def test_flagging_a_negative_review_cancels_its_escalation_and_restores_the_counter(
    api, admin_headers
):
    """PRD §3.3: "An `Escalation` is appended against the review with `reason`
    `NEGATIVE_SENTIMENT` and `state` `OPEN`, which raises the location's
    `open_escalation_count` by one."
    PRD §3.3: "Flagging a review removes it from every counter and from both score input
    sets, and — as a compensating action for the auto-escalation raised at ingest —
    every escalation of that review still sitting in `OPEN` or `ACKNOWLEDGED` is
    `CANCELLED`, with `open_escalation_count` reduced by one for each."
    PRD §3.3: "At ingest, and exactly once — it is never recomputed afterwards, no
    matter what happens to the review — the server assigns the review's `sentiment` from
    its `rating`."

    Design: Difficulty/compensating_invariant/open_escalation_count_conserved_on_negative_ingest_then_flag
    """
    env = setup_location_with_connected_listings()
    location_id = env["location"]["id"]

    review = ingest_review(location_id, rating=1, author_name="Angry Ann", text="Terrible")
    escalation = read_open_escalation(review["id"])
    before = read_location(location_id)
    assert before["open_escalation_count"] == 1
    assert_score(before["reputation_score_provisional"], 27.00, "provisional score after ingest")

    flagged = validate_success(
        api.flag_review(review["id"], {"reason": "Fake review from a competitor"}, admin_headers)
    )
    assert flagged["moderation_state"] == "FLAGGED"
    assert flagged["sentiment"] == "NEGATIVE", "sentiment is assigned at ingest and never recomputed"

    rows = read_escalations(review["id"])
    cancelled = [row for row in rows if row["id"] == escalation["id"]][0]
    assert cancelled["state"] == "CANCELLED"

    after = read_location(location_id)
    assert after["open_escalation_count"] == 0, "the counter returns to its pre-ingest value"
    assert after["review_count"] == 0, "a FLAGGED review leaves every location counter"
    assert after["sentiment_negative_count"] == 0


def test_flagging_restores_the_provisional_score_to_its_pre_ingest_value(api):
    """PRD §3.8: "Its review set is every review at the location whose `moderation_state`
    is `UNVERIFIED` or `VERIFIED`. Its average rating is the plain, unweighted mean of
    those reviews' `rating` values — no recency weighting whatsoever — and 0 when the set
    is empty."
    PRD §3.8: "Reviews whose `moderation_state` is `FLAGGED` are excluded from **both**
    variants."

    Design: Difficulty/compensating_invariant/open_escalation_count_conserved_on_negative_ingest_then_flag
    """
    env = setup_location_with_connected_listings()
    location_id = env["location"]["id"]

    pre_ingest = read_location(location_id)
    assert_score(pre_ingest["reputation_score_provisional"], 15.00, "pre-ingest provisional score")
    assert pre_ingest["posture"] == "OPEN"

    review = ingest_review(location_id, rating=1, author_name="Angry Ann", text="Terrible")
    flag_review(review["id"], reason="Fake review from a competitor")

    after = read_location(location_id)
    assert_score(after["avg_rating"], 0.00, "avg_rating over an empty non-flagged set")
    assert_score(
        after["reputation_score_provisional"], 15.00, "provisional score restored with no drift"
    )
    assert after["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# Ingest validation
# ---------------------------------------------------------------------------
def test_ingest_without_the_rating_field_is_rejected(api, admin_headers):
    """PRD §2.9: "Request well-formedness — required fields present, types correct, enum
    members recognised, `rating` between 1 and 5 inclusive, `nps_score` between 0 and 10
    inclusive, send-window strings well-formed with the close strictly after the open,
    `limit` within 1 to 100 and `offset` not negative (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/review_ingest_missing_required_field_returns_invalid_request
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]

    payload = ingest_review_payload(author_name="Ann", text="No stars given")
    payload.pop("rating")

    resp = api.ingest_review(location_id, payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    assert read_location(location_id)["review_count"] == 0, "no Review row may be created"


def test_ingest_with_a_rating_above_five_is_rejected(api, admin_headers):
    """PRD §3.3: "an integer `rating` between 1 and 5 inclusive"
    PRD §2.9: "Request well-formedness — required fields present, types correct, enum
    members recognised, `rating` between 1 and 5 inclusive, `nps_score` between 0 and 10
    inclusive, send-window strings well-formed with the close strictly after the open,
    `limit` within 1 to 100 and `offset` not negative (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/review_ingest_rating_out_of_range_rejected
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]

    resp = api.ingest_review(
        location_id, ingest_review_payload(rating=6, text="Off scale"), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    assert read_location(location_id)["review_count"] == 0


def test_replaying_the_same_external_review_id_is_rejected(api, admin_headers):
    """PRD §3.3: "No two reviews may share the same location, site and
    `external_review_id` — a repeat is rejected with `ERR_DUPLICATE_EXTERNAL_REVIEW`."

    Design: Corner/validations/duplicate_external_review_id_on_same_site_is_rejected
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    ingest_review(location_id, external_review_id="g-r1", rating=5)

    resp = api.ingest_review(
        location_id,
        ingest_review_payload(external_review_id="g-r1", rating=5, text="Superb (replay)"),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXTERNAL_REVIEW.value)

    location = read_location(location_id)
    assert location["review_count"] == 1, "a connector replay must not double-count a review"
    assert_score(location["avg_rating"], 5.00, "avg_rating")


def test_verifying_an_already_verified_review_is_an_invalid_transition(api, admin_headers):
    """PRD §3.3: "Both verification and flagging are barred while the location is
    `FROZEN`, and either one applied to a review already in the destination state is an
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/verify_an_already_verified_review_returns_invalid_state
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    review = ingest_review(location_id, rating=5)
    verify_review(review["id"])

    resp = api.verify_review(review["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    assert read_review(review["id"])["moderation_state"] == "VERIFIED"
    assert read_location(location_id)["review_count"] == 1, "no counter may be double-counted"


def test_reinstating_a_flagged_negative_review_raises_a_fresh_escalation(api, admin_headers):
    """PRD §3.3: "A false flag can be undone: `FLAGGED → VERIFIED` reinstates the review."
    PRD §3.3: "Reinstating a `FLAGGED` review to `VERIFIED` puts it back into every
    counter, and if its `sentiment` is `NEGATIVE`, a *fresh* `OPEN` escalation with
    `reason` `NEGATIVE_SENTIMENT` is raised against it and `open_escalation_count` climbs
    again."

    Design: Corner/state_machines/flagged_review_reinstated_by_verify_reopens_escalation
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    review = ingest_review(location_id, rating=1, author_name="Angry Ann", text="Terrible")
    first_escalation = read_open_escalation(review["id"])
    flag_review(review["id"], reason="Suspected fake")

    before = read_location(location_id)
    assert read_review(review["id"])["moderation_state"] == "FLAGGED"
    assert before["open_escalation_count"] == 0

    reinstated = validate_success(api.verify_review(review["id"], admin_headers))
    assert reinstated["moderation_state"] == "VERIFIED"

    rows = read_escalations(review["id"])
    assert len(rows) == 2, "the cancelled escalation is not resurrected; a fresh one is appended"
    original = [row for row in rows if row["id"] == first_escalation["id"]][0]
    assert original["state"] == "CANCELLED"
    assert len([row for row in rows if row["state"] == "OPEN"]) == 1

    after = read_location(location_id)
    assert after["open_escalation_count"] == 1
    assert after["review_count"] == 1
    assert after["sentiment_negative_count"] == 1


def test_dashboard_reports_the_sentiment_breakdown_of_the_non_flagged_set(api, admin_headers):
    """PRD §3.3: "A rating of 4 or above is `POSITIVE`. A rating of 2 or below is
    `NEGATIVE`. That leaves a rating of exactly 3 as the only `NEUTRAL` value."
    PRD §3.3: "Over that non-flagged set, the server maintains `review_count` (its size),
    `avg_rating` (the mean `rating`, rounded half up to 2 decimal places, and 0.00 when
    the set is empty), the three sentiment tallies `sentiment_positive_count`,
    `sentiment_neutral_count` and `sentiment_negative_count`, and
    `responded_review_count` (how many of them have reached a `response_state` of
    `RESPONDED`)."

    Design: Corner/endpoints/dashboard_reports_sentiment_breakdown_and_derived_fields
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    r1 = ingest_review(location_id, external_review_id="g-r1", author_name="A", rating=5,
                       text="Great")
    r2 = ingest_review(location_id, external_review_id="g-r2", author_name="B", rating=3,
                       text="Fine")
    r3 = ingest_review(location_id, external_review_id="g-r3", author_name="C", rating=2,
                       text="Poor")

    assert r1["sentiment"] == "POSITIVE"
    assert r2["sentiment"] == "NEUTRAL"
    assert r3["sentiment"] == "NEGATIVE"

    dashboard = validate_success(api.get_dashboard(location_id, admin_headers))
    assert dashboard["review_count"] == 3
    assert_score(dashboard["avg_rating"], 3.33, "avg_rating")
    assert dashboard["sentiment_positive_count"] == 1
    assert dashboard["sentiment_neutral_count"] == 1
    assert dashboard["sentiment_negative_count"] == 1
    assert dashboard["open_escalation_count"] == 1, "the 2-star review auto-escalated"
    assert_score(dashboard["reputation_score_certified"], 0.00, "never certified")

    alerts = read_alerts(location_id, "NEGATIVE_REVIEW")
    negative = [a for a in alerts if a["alert_type"] == "NEGATIVE_REVIEW"]
    assert len(negative) == 1
    assert_alert_severity(negative[0])


def test_anonymous_caller_cannot_ingest_a_review(api):
    """PRD §2.1: "A role that is not listed among the target endpoint's authorized roles
    is rejected with `ERR_UNAUTHORIZED` (403)."
    PRD §3.3: "Reviews arrive through a `PlatformAdmin`-only site-connector ingest."

    Design: Corner/rbac/anonymous_cannot_ingest_a_review
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]

    resp = api.ingest_review(
        location_id,
        ingest_review_payload(author_name="Ghost", rating=5, text="Self review"),
        build_user_headers("public-1", "Anonymous"),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    assert read_location(location_id)["review_count"] == 0
