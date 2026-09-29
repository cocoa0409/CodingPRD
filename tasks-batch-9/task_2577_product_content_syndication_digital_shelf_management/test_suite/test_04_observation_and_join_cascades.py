"""Transitive cascades: one observation driving projection, alerts and the product
roll-up, and one review join driving supersede, invalidation and slot release."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_shelf_alert,
    assert_slot_ledger,
    assert_pin_ledger,
    assert_retailer_listing,
)
from test_helpers.fixtures import (
    add_bigbox_second_revision,
    ingest_observation,
    queue_job,
    raise_change_request,
    review_brand,
    review_legal,
)
from test_helpers.test_users import (
    make_account_team_headers,
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)


def _out_of_stock_crawl(world):
    return ingest_observation(
        world["listing"]["id"],
        "2026-08-11T00:00:00Z",
        in_stock=False,
        content_accuracy_pct=70.00,
        rating_avg=4.00,
        rating_count=120,
        unauthorized_seller_count=0,
        conversion_rate_pct=2.00,
        units_sold=40,
        search_rank=3,
    )


def test_the_ingest_projects_the_latest_crawl_onto_the_listing(simplemart_world):
    """The single crawl is the latest row, so its rank, accuracy, rating and
    availability are copied straight onto the listing with no rounding.

    PRD 3.9: "That row's values are copied verbatim onto the listing with no rounding: `search_rank` into `search_rank_latest`, and `content_accuracy_pct`, `rating_avg` and `in_stock` into the like-named listing fields."
    Design: Difficulty/transitive_cascade/observation_ingest_cascades_projection_then_alerts_then_product_rollup
    """
    _out_of_stock_crawl(simplemart_world)

    listing = validate_success(
        api_client.get_retailer_listing(
            simplemart_world["listing"]["id"], make_shelf_admin_headers()
        )
    )
    assert_retailer_listing(listing)
    assert listing["search_rank_latest"] == 3
    assert float(listing["content_accuracy_pct"]) == pytest.approx(70.00, abs=0.01)
    assert float(listing["rating_avg"]) == pytest.approx(4.00, abs=0.01)
    assert listing["in_stock"] is False


def test_the_projected_stockout_moves_only_the_shelf_dimension(simplemart_world):
    """The out-of-stock crawl with no unauthorized sellers takes the listing from OK
    to OOS_WATCH and raises the MEDIUM out-of-stock alert, while the feed dimension
    is left untouched at NOT_SYNDICATED.

    PRD 3.9: "An observation with `in_stock` false and `unauthorized_seller_count` zero moves an `OK` listing to `OOS_WATCH` and raises an alert with `alert_type` `OUT_OF_STOCK`, `severity` `MEDIUM`, and `source_observation_id` pointing at the observation that triggered it."
    Design: Difficulty/transitive_cascade/observation_ingest_cascades_projection_then_alerts_then_product_rollup
    """
    observation = _out_of_stock_crawl(simplemart_world)

    listing = validate_success(
        api_client.get_retailer_listing(
            simplemart_world["listing"]["id"], make_shelf_admin_headers()
        )
    )
    assert listing["shelf_state"] == "OOS_WATCH"
    assert listing["syndication_state"] == "NOT_SYNDICATED"

    rows, _meta = validate_paginated(
        api_client.list_shelf_alerts(
            make_account_team_headers(),
            params={
                "retailer_listing_id": simplemart_world["listing"]["id"],
                "alert_type": "OUT_OF_STOCK",
            },
        )
    )
    assert len(rows) == 1
    assert_shelf_alert(rows[0])
    assert rows[0]["severity"] == "MEDIUM"
    assert rows[0]["state"] == "OPEN"
    assert rows[0]["source_observation_id"] == observation["id"]


def test_leaving_ok_floors_the_accuracy_input_of_the_readiness_blend(simplemart_world):
    """Because hop 2 took the listing off OK, the 70.00 accuracy is replaced by
    60.00 in the blend, so readiness lands on 84.00 rather than the 88.00 an
    unfloored accuracy would give.

    PRD 3.4: "The accuracy figure is the listing's `content_accuracy_pct`, treated as 0.00 while no observation has ever been recorded; and it is floored — meaning it is replaced by the smaller of itself and 60.00 — whenever the listing's `shelf_state` is anything other than `OK`."
    Design: Difficulty/transitive_cascade/observation_ingest_cascades_projection_then_alerts_then_product_rollup
    """
    _out_of_stock_crawl(simplemart_world)

    listing = validate_success(
        api_client.get_retailer_listing(
            simplemart_world["listing"]["id"], make_shelf_admin_headers()
        )
    )
    assert float(listing["readiness_score"]) == pytest.approx(84.00, abs=0.01)
    assert float(listing["readiness_score"]) != pytest.approx(88.00, abs=0.01)


def test_a_sub_threshold_accuracy_adds_a_second_low_severity_alert(simplemart_world):
    """The same crawl is below 85.00 accuracy, so it also raises a LOW content-drift
    alert: two alerts in total on the listing, both OPEN, both pointing back at the
    observation and both inheriting the listing's account-team owner.

    PRD 3.9: "An observation whose `content_accuracy_pct` is below 85.00 raises an alert with `alert_type` `CONTENT_DRIFT` and `severity` `LOW`."
    Design: Difficulty/transitive_cascade/observation_ingest_cascades_projection_then_alerts_then_product_rollup
    """
    observation = _out_of_stock_crawl(simplemart_world)

    rows, meta = validate_paginated(
        api_client.list_shelf_alerts(
            make_account_team_headers(),
            params={"retailer_listing_id": simplemart_world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["alert_type"] for row in rows) == ["CONTENT_DRIFT", "OUT_OF_STOCK"]
    drift = [row for row in rows if row["alert_type"] == "CONTENT_DRIFT"][0]
    assert drift["severity"] == "LOW"
    for row in rows:
        assert row["state"] == "OPEN"
        assert row["source_observation_id"] == observation["id"]
        assert row["assigned_account_team_user_id"] == "acct_simplemart_1"


def test_the_alert_rows_roll_up_onto_the_product(simplemart_world):
    """Hop 4 counts the two open alerts onto the product and, with no unauthorized
    listing among them, stops the flag precedence at CONTENT_AT_RISK; the
    NOT_SYNDICATED listing still contributes nothing to the health index, and the
    single post-pin observation leaves BASE empty so the lift stays 0.00.

    PRD 3.9: "Its `governance_flag` is derived from that same set under a pinned precedence, evaluated top to bottom: it is `LISTING_RISK` when any alert in the set has `alert_type` `UNAUTHORIZED_LISTING`; otherwise `CONTENT_AT_RISK` when the count is 1 or more; otherwise `NONE`."
    Design: Difficulty/transitive_cascade/observation_ingest_cascades_projection_then_alerts_then_product_rollup
    """
    _out_of_stock_crawl(simplemart_world)

    product = validate_success(
        api_client.get_product(simplemart_world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["open_alert_count"] == 2
    assert product["governance_flag"] == "CONTENT_AT_RISK"
    assert float(product["shelf_health_index"]) == pytest.approx(0.00, abs=0.01)
    assert float(product["conversion_lift_pct"]) == pytest.approx(0.00, abs=0.01)
    assert product["version"] == 4

    degraded, meta = validate_paginated(
        api_client.list_shelf_alerts(
            make_account_team_headers(),
            params={
                "retailer_listing_id": simplemart_world["listing"]["id"],
                "alert_type": "HEALTH_DEGRADED",
            },
        )
    )
    assert meta["total_count"] == 0
    assert degraded == []


def _bigbox_with_queued_job_and_second_request(world):
    """Queue six slots against revision 1, then open and submit a second change
    request for a superseding revision that also carries the brand attribute."""
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        6,
        "2026-08-20T00:00:00Z",
        "2026-08-21T00:00:00Z",
        world["retailer"]["id"],
    )
    revision_2 = add_bigbox_second_revision(world, supersedes=world["revision"]["id"])
    change_request = raise_change_request(
        world["product"]["id"],
        world["retailer"]["id"],
        revision_2["id"],
        "roll revision 2 with the brand attribute onto BigBox",
    )
    return job, revision_2, change_request


def _approve_second_request(world, change_request):
    review_legal(change_request["id"], world["product"]["id"], "APPROVED", "legal_2")
    return review_brand(change_request["id"], world["product"]["id"], "APPROVED", "brand_2")


def test_the_join_supersedes_the_previously_pinned_revision(bigbox_world):
    """Pinning revision 2 moves revision 1 out of PINNED and strips the one listing
    reference it held, leaving the new revision holding it instead.

    PRD 3.5: "Whatever revision that listing's `pinned_content_version_id` previously named, if any, transitions `PINNED → SUPERSEDED` and has its `pin_count` recomputed downward, losing exactly the one listing reference it held."
    Design: Difficulty/transitive_cascade/cr_join_supersedes_version_invalidates_queued_job_and_releases_feed_slots
    """
    _job, revision_2, change_request = _bigbox_with_queued_job_and_second_request(bigbox_world)
    joined = _approve_second_request(bigbox_world, change_request)
    assert joined["state"] == "APPROVED"

    new_revision = validate_success(
        api_client.get_content_version(revision_2["id"], make_content_author_headers())
    )
    assert new_revision["state"] == "PINNED"
    assert_pin_ledger(new_revision, 1)

    old_revision = validate_success(
        api_client.get_content_version(
            bigbox_world["revision"]["id"], make_content_author_headers()
        )
    )
    assert old_revision["state"] == "SUPERSEDED"
    assert_pin_ledger(old_revision, 0)


def test_the_supersede_invalidates_the_queued_job_that_referenced_it(bigbox_world):
    """Hop 3 reaches a job two entities away from the review write: the QUEUED job
    that named revision 1 is invalidated.

    PRD 3.5: "Every syndication job still in `QUEUED` whose `content_version_id` is the newly superseded revision transitions `QUEUED → INVALIDATED`, processed in ascending `created_at` order."
    Design: Difficulty/transitive_cascade/cr_join_supersedes_version_invalidates_queued_job_and_releases_feed_slots
    """
    job, _revision_2, change_request = _bigbox_with_queued_job_and_second_request(bigbox_world)
    _approve_second_request(bigbox_world, change_request)

    refreshed = get_success_data(
        api_client.get_syndication_job(job["id"], make_syndication_operator_headers())
    )
    assert refreshed["state"] == "INVALIDATED"


def test_the_invalidation_releases_the_reserved_feed_slots(bigbox_world):
    """Hop 4 returns the six reserved slots to BigBox — the queue had taken the
    retailer to version 2, and the release takes it to version 3 — and the listing,
    left with no holding job, falls back to NOT_SYNDICATED behind the new pin.

    PRD 3.5: "Each invalidated job releases its `slot_count`, so the owning retailer's `feed_slots_reserved` is recomputed from the ledger and the retailer's `version` increments by 1."
    Design: Difficulty/transitive_cascade/cr_join_supersedes_version_invalidates_queued_job_and_releases_feed_slots
    """
    _job, revision_2, change_request = _bigbox_with_queued_job_and_second_request(bigbox_world)
    _approve_second_request(bigbox_world, change_request)

    retailer = validate_success(
        api_client.get_retailer(bigbox_world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 3

    listing = validate_success(
        api_client.get_retailer_listing(
            bigbox_world["listing"]["id"], make_content_author_headers()
        )
    )
    assert listing["syndication_state"] == "NOT_SYNDICATED"
    assert listing["pinned_content_version_id"] == revision_2["id"]


def test_the_join_rescores_the_listing_on_the_newly_pinned_revision(bigbox_world):
    """Revision 2 supplies the brand attribute the first revision lacked, so the
    certified score rises to 95.00 — the three requirement weights plus three
    quarters of the image weight — against a declared 100.00, and readiness follows
    to 57.00.

    PRD 3.5: "Alongside the four hops, the join recomputes `completeness_score_certified`, `completeness_score_declared` and `readiness_score` on each touched listing, recomputes the newly pinned revision's `pin_count` upward, recomputes the product's `shelf_health_index`, and — like every review decision — stamps `last_review_at` and increments the product's `version`."
    Design: Difficulty/transitive_cascade/cr_join_supersedes_version_invalidates_queued_job_and_releases_feed_slots
    """
    _job, _revision_2, change_request = _bigbox_with_queued_job_and_second_request(bigbox_world)
    _approve_second_request(bigbox_world, change_request)

    listing = validate_success(
        api_client.get_retailer_listing(
            bigbox_world["listing"]["id"], make_content_author_headers()
        )
    )
    assert float(listing["completeness_score_certified"]) == pytest.approx(95.00, abs=0.01)
    assert float(listing["completeness_score_declared"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(57.00, abs=0.01)

    product = validate_success(
        api_client.get_product(bigbox_world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["last_pinned_at"].startswith("2026-08-10T00:00:00")
    assert product["version"] == 5
