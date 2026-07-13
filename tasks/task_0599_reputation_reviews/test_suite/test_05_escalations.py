"""Escalations: acknowledge, resolve, and the publish cascade that closes them."""

from test_helpers import (
    ApiErrorId,
    assert_alert_severity,
    assert_escalation,
    assert_score,
    ingest_review,
    read_alerts,
    read_escalations,
    read_location,
    read_open_escalation,
    read_review,
    read_review_response,
    setup_bare_location,
    setup_location_with_connected_listings,
    setup_approved_response,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# The publish cascade: response -> review -> escalation -> location
# ---------------------------------------------------------------------------
def _setup_negative_review_with_approved_reply():
    env = setup_location_with_connected_listings()
    review = ingest_review(
        env["location"]["id"], rating=2, author_name="Angry Ann", text="Bad"
    )
    env["review"] = review
    env["escalation"] = read_open_escalation(review["id"])
    env["response"] = setup_approved_response(
        review["id"], body="We are sorry, please contact us."
    )
    return env


def test_publishing_a_reply_marks_the_review_responded_and_resolves_its_escalation(
    api, compliance_officer_headers
):
    """PRD §2.6: "**The publish chain.** Publishing a reply flips the review's reply
    dimension to `RESPONDED` (link 1), which resolves every still-open escalation on that
    review (link 2), which decrements the location's `open_escalation_count`, recomputes
    `reputation_score_provisional` and re-derives `posture` (link 3) — potentially
    returning the location from `RESTRICTED` to `OPEN`."

    Design: Difficulty/transitive_cascade/publish_response_resolves_escalation_and_reprices_location
    """
    env = _setup_negative_review_with_approved_reply()
    location_id = env["location"]["id"]

    before = read_location(location_id)
    assert before["open_escalation_count"] == 1
    assert_score(before["reputation_score_provisional"], 39.00, "provisional score before publish")

    published = validate_success(
        api.publish_review_response(env["response"]["id"], compliance_officer_headers)
    )
    assert published["state"] == "PUBLISHED"
    assert published["published_at"] is not None

    review = read_review(env["review"]["id"])
    assert review["response_state"] == "RESPONDED", "link 1 of the publish chain"
    assert review["moderation_state"] == "UNVERIFIED", "moderation is an independent dimension"

    escalation = [
        row for row in read_escalations(review["id"]) if row["id"] == env["escalation"]["id"]
    ][0]
    assert_escalation(escalation)
    assert escalation["state"] == "RESOLVED", "link 2 of the publish chain"


def test_the_publish_cascade_reprices_the_location_and_clears_the_escalation_counter(
    api, compliance_officer_headers
):
    """PRD §3.8: "A **response component** worth up to 25 points: the variant's response
    rate — the fraction of the variant's reviews whose reply dimension reads `RESPONDED`
    — multiplied by 25."
    PRD §3.5: "**Resolving** an escalation — from `OPEN` or from `ACKNOWLEDGED` — closes
    it for good, stamping `resolved_at`, dropping the location's `open_escalation_count`
    by one and re-deriving the posture."

    Design: Difficulty/transitive_cascade/publish_response_resolves_escalation_and_reprices_location
    """
    env = _setup_negative_review_with_approved_reply()
    location_id = env["location"]["id"]

    validate_success(
        api.publish_review_response(env["response"]["id"], compliance_officer_headers)
    )

    location = read_location(location_id)
    assert location["open_escalation_count"] == 0, "link 3 of the publish chain"
    assert location["responded_review_count"] == 1
    # rating 2/5 x 60 = 24.00, response rate 1/1 x 25 = 25.00, listing 100/100 x 15 = 15.00
    assert_score(location["reputation_score_provisional"], 64.00, "reputation_score_provisional")
    assert location["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# Acknowledge and the manual-resolve precondition
# ---------------------------------------------------------------------------
def test_acknowledging_an_escalation_leaves_it_counted_as_open(api, admin_headers):
    """PRD §3.5: "A `LocationManager` may **acknowledge** an `OPEN` escalation, taking it
    `OPEN → ACKNOWLEDGED` and stamping `acknowledged_by_user_id` with the acting
    `X-User-ID`. Acknowledgement is a signal of human attention, not of closure: an
    `ACKNOWLEDGED` escalation still counts toward the location's `open_escalation_count`,
    which is therefore left completely unchanged by this transition."

    Design: Corner/state_machines/escalation_acknowledge_still_counts_as_open
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    review = ingest_review(location_id, rating=1, author_name="Angry Ann", text="Terrible")
    escalation = read_open_escalation(review["id"])

    acknowledged = validate_success(
        api.acknowledge_escalation(escalation["id"], admin_headers)
    )
    assert_escalation(acknowledged)

    assert acknowledged["state"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == admin_headers["X-User-ID"]
    assert acknowledged["resolved_at"] is None
    assert read_location(location_id)["open_escalation_count"] == 1, (
        "ACKNOWLEDGED still counts as open for the posture predicate"
    )

    alerts = [a for a in read_alerts(location_id, "NEGATIVE_REVIEW")
              if a["alert_type"] == "NEGATIVE_REVIEW"]
    assert len(alerts) == 1
    assert_alert_severity(alerts[0])


def test_manually_resolving_an_escalation_before_the_review_is_responded_is_rejected(
    api, admin_headers
):
    """PRD §3.5: "When a human resolves it manually, the underlying review must already
    have been replied to: its reply dimension must read `RESPONDED`, and if it does not,
    the request is rejected with `ERR_REVIEW_NOT_RESPONDED` (409)."

    Design: Corner/validations/escalation_resolve_before_review_is_responded_is_rejected
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    review = ingest_review(location_id, rating=1, author_name="Angry Ann", text="Terrible")
    escalation = read_open_escalation(review["id"])
    assert read_review(review["id"])["response_state"] == "NONE"

    resp = api.resolve_escalation(escalation["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_RESPONDED.value)

    rows = read_escalations(review["id"])
    assert rows[0]["state"] == "OPEN", "the rejected resolve must not move the escalation"
    assert read_location(location_id)["open_escalation_count"] == 1
