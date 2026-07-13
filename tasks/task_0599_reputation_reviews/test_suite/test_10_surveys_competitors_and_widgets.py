"""Surveys and NPS, competitor benchmarking, and the website widget."""

from test_helpers import (
    ApiErrorId,
    assert_alert_severity,
    assert_competitor,
    assert_instant_equals,
    assert_score,
    assert_widget,
    create_competitor_payload,
    create_email_contact,
    create_survey,
    create_widget,
    create_widget_payload,
    ingest_review,
    read_alerts,
    read_dashboard,
    read_location,
    read_widget,
    set_clock,
    setup_bare_location,
    submit_survey,
    validate_error,
    validate_success,
)
from test_helpers.test_users import anonymous_headers


# ---------------------------------------------------------------------------
# NPS
# ---------------------------------------------------------------------------
def test_nps_bucketing_boundaries_and_the_location_nps_score(api, admin_headers):
    """PRD §3.7: "The submitted score is bucketed into `nps_category`: a score of 9 or above is
    a `PROMOTER`, a score of 6 or below is a `DETRACTOR`, and the scores 7 and 8 in between are
    `PASSIVE`. A `DETRACTOR` submission also appends an alert of type `NPS_DETRACTOR` pointing
    at the survey."
    PRD §3.7: "Take the count of promoters divided by the number of submitted surveys,
    multiplied by 100; take the count of detractors divided by the same number, multiplied by
    100; subtract the second percentage from the first; and round that difference half up to 2
    decimal places."

    Design: Corner/calculations/nps_bucketing_boundaries_9_promoter_8_passive_6_detractor
    """
    env = setup_bare_location()
    business_id = env["business"]["id"]
    location_id = env["location"]["id"]

    surveys = []
    for i in (1, 2, 3, 4):
        contact = create_email_contact(business_id, f"S {i}", f"s{i}@example.com")
        surveys.append(create_survey(location_id, contact["id"]))

    submit_survey(surveys[0]["id"], 9)
    submit_survey(surveys[1]["id"], 10)
    submit_survey(surveys[2]["id"], 8)

    last = validate_success(
        api.submit_survey(
            surveys[3]["id"],
            {"nps_score": 6, "comment": "Slow front desk"},
            anonymous_headers(),
        )
    )
    assert last["nps_category"] == "DETRACTOR"
    assert last["status"] == "SUBMITTED"
    assert_instant_equals(last["submitted_at"], "2026-05-01T00:00:00Z", "submitted_at")

    categories = [
        validate_success(api.get_survey(survey["id"], admin_headers))["nps_category"]
        for survey in surveys
    ]
    assert categories == ["PROMOTER", "PROMOTER", "PASSIVE", "DETRACTOR"]

    # promoters 2/4 x 100 = 50.00, detractors 1/4 x 100 = 25.00, difference 25.00
    assert_score(read_location(location_id)["nps_score"], 25.00, "Location.nps_score")

    alerts = [a for a in read_alerts(location_id, "NPS_DETRACTOR")
              if a["alert_type"] == "NPS_DETRACTOR"]
    assert len(alerts) == 1
    assert_alert_severity(alerts[0])


def test_a_pending_survey_is_excluded_from_the_nps_input_set(api, admin_headers):
    """PRD §3.7: "The location's `nps_score` — a different field on a different entity, carrying
    the standard Net Promoter shape — is then recomputed over that location's `SUBMITTED`
    surveys only; `PENDING` rows are excluded, and an empty set yields 0.00."
    PRD §3.7: "the row records its `location_id`, lands in `PENDING`, and is stamped with an
    `expires_at` set to a fortnight — 14 days — after its `created_at`. Its `nps_score`,
    `nps_category`, `comment` and `submitted_at` are all null while it is `PENDING`."

    Design: Corner/calculations/nps_score_is_zero_when_no_survey_has_been_submitted
    """
    env = setup_bare_location()
    contact = create_email_contact(env["business"]["id"], "S One", "s1@example.com")
    survey = create_survey(env["location"]["id"], contact["id"])

    reread = validate_success(api.get_survey(survey["id"], admin_headers))
    assert reread["status"] == "PENDING"
    assert reread["nps_score"] is None
    assert reread["nps_category"] is None
    assert_instant_equals(
        reread["expires_at"], "2026-05-15T00:00:00Z", "SurveyResponse.expires_at"
    )

    dashboard = read_dashboard(env["location"]["id"])
    assert_score(dashboard["nps_score"], 0.00, "dashboard nps_score")


def test_submitting_a_survey_at_exactly_its_expiry_instant_is_rejected(api, admin_headers):
    """PRD §3.7: "Timing is strict: the submission must happen strictly before `expires_at`. A
    submission at *exactly* `expires_at`, or after it, is already too late and is rejected with
    `ERR_SURVEY_EXPIRED` (409)."

    Design: Corner/validations/survey_submit_at_exactly_expires_at_is_rejected
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    contact = create_email_contact(env["business"]["id"], "S One", "s1@example.com")
    survey = create_survey(location_id, contact["id"])

    set_clock("2026-05-15T00:00:00Z")

    resp = api.submit_survey(survey["id"], {"nps_score": 10}, anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_SURVEY_EXPIRED.value)

    reread = validate_success(api.get_survey(survey["id"], admin_headers))
    assert reread["status"] == "PENDING"
    assert reread["nps_score"] is None
    assert_score(read_location(location_id)["nps_score"], 0.00, "Location.nps_score")


# ---------------------------------------------------------------------------
# Competitors
# ---------------------------------------------------------------------------
def test_competitor_benchmark_deltas_are_computed_over_every_snapshot(api, admin_headers):
    """PRD §3.7: "Otherwise, `competitor_avg_rating` is the mean of the competitors'
    `avg_rating` values, rounded half up to 2 decimal places; `rating_delta` is the location's
    `avg_rating` minus that competitor mean, rounded half up to 2 decimal places; and
    `review_volume_delta` is an integer — the location's `review_count` minus the competitors'
    mean `review_count` with that mean rounded *down* to a whole number."

    Design: Corner/calculations/competitor_benchmark_deltas_against_two_snapshots
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    ingest_review(location_id, rating=5)

    validate_success(
        api.create_competitor(
            location_id,
            create_competitor_payload(name="Rival A", site="GOOGLE", avg_rating=4.00,
                                      review_count=80),
            admin_headers,
        ),
        201,
    )
    validate_success(
        api.create_competitor(
            location_id,
            create_competitor_payload(name="Rival B", site="YELP", avg_rating=3.00,
                                      review_count=60),
            admin_headers,
        ),
        201,
    )

    dashboard = validate_success(api.get_dashboard(location_id, admin_headers))
    assert_score(dashboard["competitor_avg_rating"], 3.50, "competitor_avg_rating")
    assert_score(dashboard["rating_delta"], 1.50, "rating_delta")
    assert dashboard["review_volume_delta"] == -69, "1 - floor((80 + 60) / 2)"
    assert_score(dashboard["avg_rating"], 5.00, "avg_rating")


def test_a_competitor_snapshot_carries_no_version_and_no_updated_at(api, admin_headers):
    """PRD §2.4: "Two entities are append-only snapshots and are never modified after creation: a
    `Competitor` row and an `Alert` row carry only `id` and `created_at` — they have no
    `updated_at` and no `version` field at all."
    PRD §3.7: "A **`Competitor`** row is an immutable benchmarking snapshot recorded against a
    location. It carries the competitor's `name`, the `site` the snapshot came from (`GOOGLE`,
    `YELP` or `FACEBOOK`), its `avg_rating` on that site (at least 1.00 and at most 5.00), and
    its `review_count` on that site (not negative)."

    Design: Corner/entities/competitor_is_immutable_and_carries_no_version
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]

    competitor = validate_success(
        api.create_competitor(
            location_id,
            create_competitor_payload(name="Rival Dental", site="GOOGLE", avg_rating=4.20,
                                      review_count=80),
            admin_headers,
        ),
        201,
    )
    assert_competitor(competitor)

    rows = validate_success(api.list_competitors(location_id, admin_headers))
    assert len(rows) == 1
    assert_score(rows[0]["avg_rating"], 4.20, "Competitor.avg_rating")
    assert rows[0]["review_count"] == 80
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------
def test_widget_creation_mints_the_system_owned_fields(api, admin_headers):
    """PRD §3.7: "It is created in `DRAFT` with a server-minted `embed_token` (an opaque
    identity string that is never a decision input) and a null `published_at`."

    Design: Corner/entities/widget_system_fields_minted_by_server
    """
    env = setup_bare_location()

    widget = validate_success(
        api.create_widget(
            env["location"]["id"],
            create_widget_payload(min_rating=4, max_reviews=10),
            admin_headers,
        ),
        201,
    )
    assert_widget(widget)

    assert widget["status"] == "DRAFT"
    assert widget["published_at"] is None
    assert isinstance(widget["embed_token"], str) and widget["embed_token"], (
        "the embed_token is minted by the server, not supplied by the client"
    )
    assert widget["min_rating"] == 4
    assert widget["max_reviews"] == 10


def test_widget_creation_without_the_optional_settings_uses_the_declared_defaults(
    api, admin_headers
):
    """PRD §3.7: "Two optional settings shape the public feed: `min_rating`, the lowest review
    rating the feed will display, which must be between 1 and 5 inclusive and defaults to 4; and
    `max_reviews`, the maximum number of reviews the feed will display, which must be between 1
    and 50 inclusive and defaults to 10."

    Design: Corner/entities/widget_create_omitting_optionals_uses_defaults
    """
    env = setup_bare_location()

    widget = validate_success(
        api.create_widget(env["location"]["id"], create_widget_payload(), admin_headers), 201
    )
    assert widget["min_rating"] == 4
    assert widget["max_reviews"] == 10
    assert widget["status"] == "DRAFT"


def test_a_second_widget_on_the_same_location_is_rejected(api, admin_headers):
    """PRD §3.7: "A **`Widget`** is the review feed a location embeds on its own website, and a
    location may have **at most one** — a second creation attempt is rejected with
    `ERR_WIDGET_ALREADY_EXISTS` (409)."

    Design: Corner/validations/second_widget_on_same_location_is_rejected
    """
    env = setup_bare_location()
    location_id = env["location"]["id"]
    create_widget(location_id, min_rating=4, max_reviews=10)

    resp = api.create_widget(
        location_id, create_widget_payload(min_rating=1, max_reviews=50), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_WIDGET_ALREADY_EXISTS.value)

    widget = read_widget(location_id)
    assert widget["min_rating"] == 4, "the original widget's config is untouched"
    assert widget["max_reviews"] == 10
