"""Listings, the NAP record, the sync lifecycle and the listing health score."""

from test_helpers import (
    ApiErrorId,
    assert_listing,
    assert_location,
    assert_score,
    create_listing,
    create_listing_payload,
    ingest_review,
    nap_payload,
    read_alerts,
    read_dashboard,
    read_listing,
    read_location,
    setup_bare_location,
    setup_location_with_google_only,
    sync_listing,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# The three-input per-site formula
# ---------------------------------------------------------------------------
def _setup_mixed_health_location():
    """GOOGLE synced+matched, YELP phone-mismatched+never-synced, FACEBOOK matched+failed."""
    env = setup_bare_location()
    location_id = env["location"]["id"]

    google = create_listing(location_id, "GOOGLE")
    yelp = create_listing(location_id, "YELP", listed_nap_phone="+19998887777")
    facebook = create_listing(location_id, "FACEBOOK")

    sync_listing(google["id"], "SUCCESS")
    sync_listing(facebook["id"], "FAILURE")

    env["listings"] = {"GOOGLE": google, "YELP": yelp, "FACEBOOK": facebook}
    return env


def test_listing_health_folds_nap_match_state_factor_and_staleness(api, admin_headers):
    """PRD §3.2: "Google carries a weight of 0.5, Yelp 0.3, and Facebook 0.2."
    PRD §3.2: "Second, a **state factor** multiplying that base, fixed by the listing's
    `sync_state`: `CONNECTED` multiplies by 1.0, `PENDING_SYNC` by 0.6, `SYNC_FAILED`
    by 0.3, and `DISCONNECTED` by 0.0."
    PRD §3.2: "Staleness is measured in whole days between `last_synced_at` and the
    current logical instant, taking the floor of the elapsed time in days; a listing
    that has never had a successful sync — `last_synced_at` still null — is treated as
    maximally stale at 365 days."
    PRD §3.2: "The penalty is 2 points for each such day beyond the grace period, and
    it is capped at 30 points."

    Design: Difficulty/combinatorial_formula/listing_health_nonlinear_three_input_site_score
    """
    env = _setup_mixed_health_location()
    location_id = env["location"]["id"]

    dashboard = validate_success(api.get_dashboard(location_id, admin_headers))

    # GOOGLE: 3/3 match, CONNECTED (x1.0), staleness 0 -> 100.0, weighted 0.5 -> 50.00
    # YELP:   2/3 match, PENDING_SYNC (x0.6), never synced -> 30 penalty -> 10.0, x0.3 -> 3.00
    # FACEBOOK: 3/3 match, SYNC_FAILED (x0.3), never synced -> 30 penalty -> 0.0, x0.2 -> 0.00
    assert_score(dashboard["listing_health_score"], 53.00, "listing_health_score")


def test_listing_health_feeds_the_provisional_scores_listing_component(api, admin_headers):
    """PRD §3.8: "A **listing component** worth up to 15 points: the location's
    `listing_health_score` divided by 100, multiplied by 15. Both variants read the
    same, single `listing_health_score`."
    PRD §2.5: "**The listing-health predicate.** Always armed. It fires when
    `listing_health_score` is strictly below 40.00."

    Design: Difficulty/combinatorial_formula/listing_health_nonlinear_three_input_site_score
    """
    env = _setup_mixed_health_location()
    location_id = env["location"]["id"]

    dashboard = validate_success(api.get_dashboard(location_id, admin_headers))
    assert_score(dashboard["reputation_score_provisional"], 7.95, "reputation_score_provisional")
    assert dashboard["posture"] == "OPEN", "53.00 clears the 40.00 listing-health floor"

    google = read_listing(location_id, "GOOGLE")
    yelp = read_listing(location_id, "YELP")
    facebook = read_listing(location_id, "FACEBOOK")
    for listing in (google, yelp, facebook):
        assert_listing(listing)

    assert google["sync_state"] == "CONNECTED"
    assert yelp["sync_state"] == "PENDING_SYNC"
    assert yelp["nap_match_count"] == 2, "only the phone part disagrees with the canonical record"
    assert facebook["sync_state"] == "SYNC_FAILED"
    assert facebook["sync_failure_count"] == 1


# ---------------------------------------------------------------------------
# Corner cases
# ---------------------------------------------------------------------------
def test_second_listing_on_the_same_site_is_rejected(api, admin_headers):
    """PRD §3.2: "At most one listing may exist per location and site combination; a
    second attempt is rejected with `ERR_DUPLICATE_LISTING`."

    Design: Corner/validations/duplicate_listing_for_same_site_is_rejected
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    create_listing(location_id, "GOOGLE")

    resp = api.create_listing(
        location_id,
        create_listing_payload("GOOGLE", external_listing_id="g-2"),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LISTING.value)

    rows = validate_success(api.list_listings(location_id, admin_headers))
    assert len(rows) == 1, "the duplicate must not have been persisted"


def test_third_consecutive_failure_disconnects_the_listing_and_locks_it(api, admin_headers):
    """PRD §3.2: "The failure that pushes the counter *to* three — that is, the one
    applied when the counter already stands at 2 — drives the listing to
    `DISCONNECTED`. `DISCONNECTED` is terminal: any further sync attempt on it is
    rejected with `ERR_INVALID_STATE`."
    PRD §3.2: "On `FAILURE`, the published fields are left exactly as they were and
    `sync_failure_count` climbs by one, an alert of type `LISTING_SYNC_FAILED` is
    appended, and the listing's `sync_state` moves according to how many consecutive
    failures have now accumulated."

    Design: Corner/state_machines/listing_disconnects_after_three_failures_and_further_sync_is_rejected
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    listing = create_listing(location_id, "GOOGLE")
    sync_listing(listing["id"], "FAILURE")
    sync_listing(listing["id"], "FAILURE")

    third = validate_success(api.sync_listing(listing["id"], {"outcome": "FAILURE"}, admin_headers))
    assert third["sync_state"] == "DISCONNECTED"
    assert third["sync_failure_count"] == 3

    resp = api.sync_listing(listing["id"], {"outcome": "SUCCESS"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = read_listing(location_id, "GOOGLE")
    assert after["sync_state"] == "DISCONNECTED", "the rejected sync must not move the listing"

    alerts = read_alerts(location_id, "LISTING_SYNC_FAILED")
    sync_alerts = [a for a in alerts if a["alert_type"] == "LISTING_SYNC_FAILED"]
    assert len(sync_alerts) == 3, "one alert per FAILURE outcome"


def test_replacing_the_nap_record_kicks_a_connected_listing_back_to_pending_sync(
    api, admin_headers
):
    """PRD §3.1: "It increments the location's `version` by one, it kicks every
    `CONNECTED` listing of that location back to `PENDING_SYNC` (leaving the sites'
    published copies untouched, which is precisely what makes their match counts drop),
    and it then re-runs the recomputation chain of §2.6 — listing health, then
    provisional score, then posture."
    PRD §3.2: "The listing's derived `nap_match_count` is the number of the three NAP
    parts — name, address, phone — where the published value equals the canonical value
    under case-sensitive exact string comparison."

    Design: Corner/state_machines/nap_update_reverts_connected_listing_to_pending_sync
    """
    env = setup_location_with_google_only()
    location_id = env["location"]["id"]

    before = read_location(location_id)
    assert_score(before["listing_health_score"], 50.00, "listing_health_score before")

    resp = api.update_nap(
        location_id, nap_payload(nap_phone="+15559990000"), admin_headers
    )
    location = validate_success(resp)
    assert_location(location)

    listing = read_listing(location_id, "GOOGLE")
    assert listing["sync_state"] == "PENDING_SYNC"
    assert listing["listed_nap_phone"] == "+15551110000", (
        "the site's published copy is deliberately left untouched"
    )
    assert listing["nap_match_count"] == 2, "the phone part no longer matches the canonical record"

    assert location["nap_phone"] == "+15559990000"
    # 2/3 base x 0.6 PENDING_SYNC factor, no staleness penalty -> 40.0, weighted 0.5.
    assert_score(location["listing_health_score"], 20.00, "listing_health_score after")
    assert location["posture"] == "RESTRICTED", "20.00 is below the 40.00 listing-health floor"


def test_nap_update_response_already_carries_the_recomputed_derived_fields(api, admin_headers):
    """PRD §2.6: "The location's derived fields form a dependency chain, and the server
    evaluates them in a pinned order after any mutation that feeds them:
    **`listing_health_score` first, then `reputation_score_provisional` (which consumes
    it), then `posture` (which consumes both, plus the counters).**"
    PRD §2.4: "Crucially, a mutation of a *derived* field counts as a mutation. When the
    server recomputes a location's scores, counters or posture as a downstream
    consequence of some other action, that location's `updated_at` is refreshed and its
    `version` is incremented, exactly as if the operator had edited it directly."

    Design: Corner/consistency_model/nap_update_response_already_carries_the_recomputed_derived_fields
    """
    env = setup_location_with_google_only()
    location_id = env["location"]["id"]
    before = read_location(location_id)

    resp = api.update_nap(location_id, nap_payload(nap_address="9 New Ave"), admin_headers)
    body = validate_success(resp)

    assert_score(body["listing_health_score"], 20.00, "PUT /nap response listing_health_score")
    assert body["posture"] == "RESTRICTED", "the PUT response itself already shows the new posture"
    assert body["version"] == before["version"] + 1, "the NAP replacement bumps version by one"

    reread = read_location(location_id)
    assert_score(reread["listing_health_score"], 20.00, "re-read listing_health_score")
    assert reread["posture"] == "RESTRICTED", "the re-read agrees with the mutation response"


def test_a_location_with_no_listings_scores_zero_health_and_is_restricted(api, admin_headers):
    """PRD §3.2: "This is the location's 0-to-100 measure of how faithfully the three
    sites represent it, and it is deliberately unforgiving about *absence*. All three
    sites are always weighted, so a site with no listing row at all contributes a
    per-site score of zero for its weight."
    PRD §3.2: "Because a location with no listings at all scores 0.00, and because 0.00
    is below the 40.00 listing-health floor of §2.5, an unlisted location is
    `RESTRICTED` as soon as anything causes its posture to be re-derived."

    Design: Corner/calculations/listing_health_is_zero_when_no_listing_exists
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]

    ingest_review(location_id, rating=5)

    location = read_location(location_id)
    assert_score(location["listing_health_score"], 0.00, "listing_health_score")
    assert_score(location["avg_rating"], 5.00, "avg_rating")
    # rating 5/5 x 60 = 60.00, response rate 0, listing component 0.
    assert_score(location["reputation_score_provisional"], 60.00, "reputation_score_provisional")
    assert location["posture"] == "RESTRICTED", (
        "listing health alone degrades the location; the score predicate is not armed at 1 review"
    )

    dashboard = read_dashboard(location_id)
    assert_score(dashboard["listing_health_score"], 0.00, "dashboard listing_health_score")
