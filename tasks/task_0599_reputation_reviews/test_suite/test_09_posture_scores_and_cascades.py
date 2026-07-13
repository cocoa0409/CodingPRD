"""Posture derivation, the ingest cascade, and the two reputation-score variants."""

from test_helpers import (
    assert_alert_severity,
    assert_credit_ledger,
    assert_instant_equals,
    assert_score,
    count_alerts,
    create_widget,
    ingest_review,
    publish_widget,
    read_alerts,
    read_campaign,
    read_location,
    read_review,
    read_review_request,
    read_widget,
    setup_campaign_with_queued_requests,
    setup_location_with_connected_listings,
    validate_success,
    verify_review,
)


# ---------------------------------------------------------------------------
# The review-ingest cascade: review -> location -> campaign -> request
# ---------------------------------------------------------------------------
def _setup_location_sitting_exactly_on_the_score_gate():
    """Four reviews rated 4,4,4,3 put reputation_score_provisional on exactly 60.00."""
    env = setup_campaign_with_queued_requests(
        num_requests=2, name="Spring Asks", daily_send_cap=10, credits_allocated=10
    )
    return env


def _ingest_four_reviews_landing_on_sixty(location_id):
    for index, rating in enumerate([4, 4, 4, 3], start=1):
        ingest_review(
            location_id,
            external_review_id=f"g-r{index}",
            author_name=f"A{index}",
            rating=rating,
            text="Good",
        )


def test_an_ingest_dropping_the_score_below_60_restricts_the_location_and_pauses_the_campaign(
    api, admin_headers
):
    """PRD §2.6: "**The review-ingest chain.** Ingesting a review recomputes the location's
    counters and provisional score (link 1), which may drive the posture out of `OPEN` (link
    2), which system-pauses every `RUNNING` campaign at that location (link 3), which
    suppresses every one of those campaigns' `QUEUED` requests and releases their credits."
    PRD §2.5: "When armed, it fires if `reputation_score_provisional` is strictly below
    60.00."

    Design: Difficulty/transitive_cascade/ingest_restricts_location_pauses_campaign_suppresses_requests
    """
    env = _setup_location_sitting_exactly_on_the_score_gate()
    location_id = env["location"]["id"]
    _ingest_four_reviews_landing_on_sixty(location_id)

    before = read_location(location_id)
    assert_score(before["reputation_score_provisional"], 60.00, "provisional score before ingest")
    assert before["posture"] == "OPEN"
    posture_alerts_before = count_alerts(location_id, "POSTURE_CHANGED")

    validate_success(
        api.ingest_review(
            location_id,
            {
                "site": "GOOGLE",
                "external_review_id": "g-r5",
                "author_name": "E",
                "rating": 3,
                "text": "Fine",
                "posted_at": "2026-05-01T00:00:00Z",
            },
            admin_headers,
        ),
        201,
    )

    after = read_location(location_id)
    assert_score(after["avg_rating"], 3.60, "avg_rating")
    assert_score(after["reputation_score_provisional"], 58.20, "reputation_score_provisional")
    assert after["posture"] == "RESTRICTED", "link 2 of the ingest chain"

    assert read_campaign(env["campaign"]["id"])["status"] == "PAUSED", "link 3 of the ingest chain"

    assert count_alerts(location_id, "POSTURE_CHANGED") == posture_alerts_before + 1, (
        "exactly one POSTURE_CHANGED alert for the OPEN -> RESTRICTED degradation"
    )
    for alert in read_alerts(location_id, "POSTURE_CHANGED"):
        if alert["alert_type"] == "POSTURE_CHANGED":
            assert_alert_severity(alert)


def test_the_system_pause_suppresses_queued_requests_and_releases_their_credits(
    api, admin_headers
):
    """PRD §3.6: "A *system* pause — the one triggered whenever the location's posture leaves
    `OPEN`, whether by degrading to `RESTRICTED` or by being frozen — also takes the campaign
    `RUNNING → PAUSED`, but it additionally **empties the queue**: every `QUEUED` request of
    that campaign is moved to `SUPPRESSED`, and for each one, `credits_reserved` drops by one
    while `credits_released` rises by one."

    Design: Difficulty/transitive_cascade/ingest_restricts_location_pauses_campaign_suppresses_requests
    """
    env = _setup_location_sitting_exactly_on_the_score_gate()
    location_id = env["location"]["id"]
    _ingest_four_reviews_landing_on_sixty(location_id)
    assert read_campaign(env["campaign"]["id"])["credits_reserved"] == 2

    ingest_review(
        location_id, external_review_id="g-r5", author_name="E", rating=3, text="Fine"
    )

    for request in env["requests"]:
        assert read_review_request(request["id"])["status"] == "SUPPRESSED"

    campaign = read_campaign(env["campaign"]["id"])
    assert_credit_ledger(campaign, reserved=0, consumed=0, released=2)


# ---------------------------------------------------------------------------
# The score gate is inclusive on the passing side
# ---------------------------------------------------------------------------
def test_a_provisional_score_of_exactly_60_keeps_the_location_open(api, admin_headers):
    """PRD §2.5: "**The score predicate.** It is armed only once the location has at least 3
    non-flagged reviews — that is, once `review_count` is 3 or more. When armed, it fires if
    `reputation_score_provisional` is strictly below 60.00. The boundary is inclusive on the
    passing side: a score of exactly 60.00 does not degrade the location, while 59.99 does."
    PRD §3.3: "That leaves a rating of exactly 3 as the only `NEUTRAL` value."

    Design: Difficulty/boundary_precision_check/posture_score_gate_at_exactly_60_stays_open
    """
    env = setup_location_with_connected_listings()
    location_id = env["location"]["id"]
    for index, rating in enumerate([4, 4, 4], start=1):
        ingest_review(
            location_id, external_review_id=f"g-r{index}", author_name=f"A{index}",
            rating=rating, text="Good",
        )

    fourth = validate_success(
        api.ingest_review(
            location_id,
            {
                "site": "GOOGLE",
                "external_review_id": "g-r4",
                "author_name": "D",
                "rating": 3,
                "text": "Fine",
                "posted_at": "2026-05-01T00:00:00Z",
            },
            admin_headers,
        ),
        201,
    )
    assert fourth["sentiment"] == "NEUTRAL"

    location = read_location(location_id)
    assert location["review_count"] == 4
    assert_score(location["avg_rating"], 3.75, "avg_rating")
    assert_score(location["reputation_score_provisional"], 60.00, "reputation_score_provisional")
    assert location["posture"] == "OPEN", "a score of exactly 60.00 does not degrade the location"


def test_landing_on_the_score_gate_appends_no_posture_changed_alert(api, admin_headers):
    """PRD §2.10: "Every posture change — degradation, recovery, freeze and unfreeze alike —
    appends a `POSTURE_CHANGED` alert whose `payload_ref_id` is the location's own `id`."
    PRD §2.5: "The boundary is inclusive on the passing side: a score of exactly 60.00 does not
    degrade the location, while 59.99 does."

    Design: Difficulty/boundary_precision_check/posture_score_gate_at_exactly_60_stays_open
    """
    env = setup_location_with_connected_listings()
    location_id = env["location"]["id"]
    for index, rating in enumerate([4, 4, 4], start=1):
        ingest_review(
            location_id, external_review_id=f"g-r{index}", author_name=f"A{index}",
            rating=rating, text="Good",
        )
    assert read_location(location_id)["posture"] == "OPEN"
    posture_alerts_before = count_alerts(location_id, "POSTURE_CHANGED")

    ingest_review(
        location_id, external_review_id="g-r4", author_name="D", rating=3, text="Fine"
    )

    assert read_location(location_id)["posture"] == "OPEN"
    assert count_alerts(location_id, "POSTURE_CHANGED") == posture_alerts_before, (
        "the posture did not change, so no POSTURE_CHANGED alert may be appended"
    )


# ---------------------------------------------------------------------------
# PROVISIONAL vs CERTIFIED
# ---------------------------------------------------------------------------
def _setup_location_with_one_old_verified_and_one_fresh_unverified_review():
    env = setup_location_with_connected_listings()
    location_id = env["location"]["id"]

    old = ingest_review(
        location_id, site="GOOGLE", external_review_id="g-r1", author_name="Ann",
        rating=5, text="Superb", posted_at="2026-01-01T00:00:00Z",
    )
    verify_review(old["id"])
    fresh = ingest_review(
        location_id, site="GOOGLE", external_review_id="g-r2", author_name="Bob",
        rating=3, text="Okay", posted_at="2026-04-30T00:00:00Z",
    )
    env["old_review"] = old
    env["fresh_review"] = fresh
    return env


def test_certification_writes_a_decay_weighted_score_that_diverges_from_the_provisional_one(
    api, admin_headers
):
    """PRD §3.8: "**The CERTIFIED variant** is written to `reputation_score_certified`, and it
    is refreshed **only** by the audit checkpoint, never by ordinary traffic. It differs from
    the provisional variant in two ways. Its review set is narrower: only reviews whose
    `moderation_state` is exactly `VERIFIED` count, so unverified reviews are dropped
    entirely."
    PRD §3.8: "Its weight starts at 1 and loses 0.02 for every completed block of 30 days of
    age — the number of completed 30-day blocks being the age in days divided by 30 and rounded
    down — but the weight never falls below a floor of 0.5, however old the review is."
    PRD §3.8: "Because the two variants read different sets and weight them differently,
    identical data yields two different numbers whenever the sets diverge or any review is
    older than 30 days."

    Design: Difficulty/dual_variant_calc/location_reputation_provisional_vs_certified_diverge
    """
    env = _setup_location_with_one_old_verified_and_one_fresh_unverified_review()
    location_id = env["location"]["id"]

    certified = validate_success(api.certify_location(location_id, admin_headers))

    assert_score(certified["listing_health_score"], 100.00, "listing_health_score")
    assert_score(certified["avg_rating"], 4.00, "avg_rating")
    # PROVISIONAL: mean(5,3)=4.00 -> 48.00 + 0 response + 15.00 listing.
    assert_score(
        certified["reputation_score_provisional"], 63.00, "reputation_score_provisional"
    )
    # CERTIFIED: only the VERIFIED 5-star review survives; its weight cancels out of the
    # weighted mean, so the rating component is the full 60.00, plus 15.00 listing.
    assert_score(certified["reputation_score_certified"], 75.00, "reputation_score_certified")
    assert certified["reputation_score_certified"] != certified["reputation_score_provisional"]
    assert_instant_equals(
        certified["certified_at"], "2026-05-01T00:00:00Z", "Location.certified_at"
    )


def test_certification_leaves_the_provisional_score_and_posture_untouched(api, admin_headers):
    """PRD §3.8: "The **certification checkpoint** is the audit action, available to a
    `BusinessOwner` or a `PlatformAdmin`. It recomputes the CERTIFIED variant, writes it to
    `reputation_score_certified`, and stamps `certified_at` with the current logical instant.
    It deliberately does **not** touch `reputation_score_provisional` and does **not**
    re-derive the posture."
    PRD §3.1: "A fresh location is `OPEN`, with a `listing_health_score` of 0.00, a
    `reputation_score_provisional` of 0.00, a `reputation_score_certified` of 0.00, a null
    `certified_at`, an `avg_rating` of 0.00, an `nps_score` of 0.00, and every counter at
    zero."

    Design: Difficulty/dual_variant_calc/location_reputation_provisional_vs_certified_diverge
    """
    env = _setup_location_with_one_old_verified_and_one_fresh_unverified_review()
    location_id = env["location"]["id"]

    before = read_location(location_id)
    assert before["certified_at"] is None, "certified_at is null until the first checkpoint"
    assert_score(before["reputation_score_certified"], 0.00, "reputation_score_certified before")
    assert_score(before["reputation_score_provisional"], 63.00, "provisional score before")

    validate_success(api.certify_location(location_id, admin_headers))

    after = read_location(location_id)
    assert_score(
        after["reputation_score_provisional"], 63.00, "provisional score after certification"
    )
    assert after["posture"] == before["posture"], "certification does not re-derive the posture"
    assert_score(after["reputation_score_certified"], 75.00, "reputation_score_certified after")


# ---------------------------------------------------------------------------
# The compliance hold
# ---------------------------------------------------------------------------
def test_a_compliance_hold_freezes_the_location_and_unpublishes_its_widget(api, admin_headers):
    """PRD §3.8: "Setting it true takes the location from `OPEN` or from `RESTRICTED` to
    `FROZEN`, sets `compliance_hold` to true, system-pauses every `RUNNING` campaign at that
    location, reverts a `PUBLISHED` widget to `DRAFT` with a null `published_at`, appends a
    `POSTURE_CHANGED` alert, and increments the location's `version`."
    PRD §2.10: "`POSTURE_CHANGED` — severity `CRITICAL`."

    Design: Corner/state_machines/compliance_hold_freezes_location_and_unpublishes_widget
    """
    env = setup_location_with_connected_listings()
    location_id = env["location"]["id"]
    widget = create_widget(location_id, min_rating=4, max_reviews=10)
    publish_widget(widget["id"])

    before = read_location(location_id)
    assert before["posture"] == "OPEN"
    assert read_widget(location_id)["status"] == "PUBLISHED"

    held = validate_success(
        api.set_compliance_hold(location_id, {"on_hold": True}, admin_headers)
    )
    assert held["compliance_hold"] is True
    assert held["posture"] == "FROZEN"

    after_widget = read_widget(location_id)
    assert after_widget["status"] == "DRAFT"
    assert after_widget["published_at"] is None

    posture_alerts = [
        alert for alert in read_alerts(location_id, "POSTURE_CHANGED")
        if alert["alert_type"] == "POSTURE_CHANGED"
    ]
    assert posture_alerts, "the freeze appends a POSTURE_CHANGED alert"
    for alert in posture_alerts:
        assert_alert_severity(alert)
