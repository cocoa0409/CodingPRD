"""What each endpoint promises in its own response: a partial configuration write,
the action endpoints that cycle a job, a bulk child write, a cross-aggregate link
and the two computed reads."""
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_enhanced_deployment,
    assert_pin_ledger,
    assert_rejection_error,
    assert_shelf_summary,
    assert_slot_ledger,
)
from test_helpers.constants import CANCELLED_WITH_JOB, DEFAULT_LIFT_VARIANT
from test_helpers.factories import (
    create_deployment_payload,
    patch_retailer_payload,
    rejection_error_row,
    requeue_payload,
    retailer_response_payload,
)
from test_helpers.fixtures import (
    accept_job,
    ingest_observation,
    queue_job,
    read_listing_version,
    read_retailer_version,
    transmit_job,
)
from test_helpers.test_users import (
    make_account_team_headers,
    make_content_author_headers,
    make_retailer_integration_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

FIRST_WINDOW = ("2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z")
REQUEUE_WINDOW = ("2026-08-18T00:00:00Z", "2026-08-19T00:00:00Z")
DEPLOYMENT_WINDOW = ("2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z")

MISSING_CHANGE_REQUEST_ID = "11111111-1111-4111-8111-111111111111"
MISSING_MEDIA_ASSET_ID = "22222222-2222-4222-8222-222222222222"

WARNING_ROW = rejection_error_row(
    "E-DESC-STYLE", "WARNING", "description style nit", "description"
)
THREE_MIXED_ROWS = [
    rejection_error_row(
        "E-BRAND-MISSING", "BLOCKING", "brand attribute is required", "brand"
    ),
    rejection_error_row("E-DESC-STYLE", "WARNING", "description style nit", "description"),
    rejection_error_row("E-IMG-COUNT", "BLOCKING", "four images required", "title"),
]


def _retailer(retailer_id):
    return validate_success(api_client.get_retailer(retailer_id, make_shelf_admin_headers()))


def _listing(retailer_listing_id):
    return validate_success(
        api_client.get_retailer_listing(retailer_listing_id, make_shelf_admin_headers())
    )


def _product(product_id):
    return validate_success(api_client.get_product(product_id, make_shelf_admin_headers()))


def _job(job_id):
    return validate_success(
        api_client.get_syndication_job(job_id, make_syndication_operator_headers())
    )


def _revision(content_version_id):
    return validate_success(
        api_client.get_content_version(content_version_id, make_content_author_headers())
    )


def _summary(product_id, params=None):
    return validate_success(
        api_client.get_shelf_summary(product_id, make_content_author_headers(), params=params)
    )


def _rejection_rows(job_id, params=None):
    return validate_paginated(
        api_client.list_rejection_errors(
            job_id, make_syndication_operator_headers(), params=params
        )
    )


def _alerts(params):
    return validate_paginated(
        api_client.list_shelf_alerts(make_account_team_headers(), params=params)
    )


def _subscore_values(summary):
    """The per-listing breakdown reduced to the one blended subscore each entry
    contributes, in the order the aggregation produced them.

    PRD 3.9 names the quantity a *subscore* and says each qualifying listing
    "contributes exactly one subscore", so an entry that also spells out the four
    components it blends is read through the field that names the subscore itself.
    """
    values = []
    for entry in summary["retailer_subscores"]:
        if isinstance(entry, dict):
            numbers = {
                key: float(value)
                for key, value in entry.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            assert numbers, "each breakdown entry must carry its numeric subscore"
            named = [value for key, value in numbers.items() if "subscore" in key]
            if named:
                assert len(named) == 1, "an entry contributes exactly one subscore"
                values.append(named[0])
            else:
                assert len(numbers) == 1, (
                    "a breakdown entry must name its blended subscore when it also "
                    "carries the components behind it"
                )
                values.append(next(iter(numbers.values())))
        else:
            values.append(float(entry))
    return values


def _transmitted_job(world, slot_count=4, window=FIRST_WINDOW):
    """A job of the BigBox listing queued on the retailer's current version and then
    handed to the retailer, so it sits in TRANSMITTED awaiting a feed response."""
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        slot_count,
        window[0],
        window[1],
        world["retailer"]["id"],
    )
    transmit_job(job["id"])
    return job


def _partially_accepted_job(world):
    """The same job answered PARTIALLY_ACCEPTED with a single WARNING row, which takes
    the listing LIVE and leaves the row OPEN."""
    job = _transmitted_job(world)
    validate_success(
        api_client.retailer_response(
            job["id"],
            retailer_response_payload("PARTIALLY_ACCEPTED", [WARNING_ROW]),
            make_retailer_integration_headers(world["retailer"]["id"]),
        )
    )
    return job


def _requeue(world, job_id, **overrides):
    payload = requeue_payload(
        slot_count=6,
        window_start=REQUEUE_WINDOW[0],
        window_end=REQUEUE_WINDOW[1],
        expected_retailer_version=read_retailer_version(world["retailer"]["id"]),
        **overrides,
    )
    return validate_success(
        api_client.requeue_syndication_job(job_id, payload, make_syndication_operator_headers())
    )


def _cancel(job_id):
    return validate_success(
        api_client.cancel_syndication_job(job_id, {}, make_syndication_operator_headers())
    )


def _reject_with_three_rows(world):
    """One feed response carrying three per-row complaints — BLOCKING, WARNING,
    BLOCKING in that order — against a transmitted job."""
    job = _transmitted_job(world)
    response = api_client.retailer_response(
        job["id"],
        retailer_response_payload("REJECTED", THREE_MIXED_ROWS),
        make_retailer_integration_headers(world["retailer"]["id"]),
    )
    return job, response


def _take_live_and_crawl(world):
    """BigBox accepted on the feed and then crawled once at 92.00 accuracy, rank 6,
    in stock, 4.50 stars."""
    job = _transmitted_job(world)
    accept_job(job["id"], world["retailer"]["id"])
    observation = ingest_observation(
        world["listing"]["id"],
        "2026-08-11T00:00:00Z",
        in_stock=True,
        content_accuracy_pct=92.00,
        rating_avg=4.50,
        rating_count=120,
        unauthorized_seller_count=0,
        conversion_rate_pct=3.20,
        units_sold=40,
        search_rank=6,
    )
    return {"job": job, "observation": observation}


def _weak_crawl(world, observed_at):
    """A crawl that sees badly drifted content: 30.00 accuracy, rank 41, 3.00 stars."""
    return ingest_observation(
        world["listing"]["id"],
        observed_at,
        in_stock=True,
        content_accuracy_pct=30.00,
        rating_avg=3.00,
        rating_count=10,
        unauthorized_seller_count=0,
        conversion_rate_pct=1.00,
        units_sold=5,
        search_rank=41,
    )


def test_a_status_only_patch_leaves_the_rest_of_the_envelope_exactly_as_it_was(bigbox_world):
    """The adjustment names only `status`, so the four numeric and boolean envelope
    fields keep their stored values — an absent field is not a null one — while the
    row itself moves to PAUSED on version 2.

    PRD 3.1: "The adjustment accepts `expected_retailer_version` plus any subset of `status`, `min_image_count`, `feed_slot_capacity`, `max_concurrent_feed_windows` and `enhanced_content_requires_approval`."
    Design: Corner/endpoints/retailer_patch_updates_only_the_supplied_field_and_bumps_the_version
    """
    world = bigbox_world
    patched = validate_success(
        api_client.patch_retailer(
            world["retailer"]["id"],
            patch_retailer_payload(read_retailer_version(world["retailer"]["id"]), status="PAUSED"),
            make_shelf_admin_headers(),
        )
    )
    assert patched["status"] == "PAUSED"
    assert patched["version"] == 2

    retailer = _retailer(world["retailer"]["id"])
    assert retailer["status"] == "PAUSED"
    assert retailer["version"] == 2
    assert retailer["min_image_count"] == 4
    assert retailer["feed_slot_capacity"] == 10
    assert retailer["max_concurrent_feed_windows"] == 2
    assert retailer["enhanced_content_requires_approval"] is True
    assert retailer["retailer_code"] == "RETB"
    assert retailer["name"] == "BigBox"


def test_the_paused_retailer_is_immediately_findable_under_its_new_status(bigbox_world):
    """The roster filter reads the row as it now stands: one PAUSED retailer, and it is
    the one just adjusted.

    PRD 3.1: "Retailers can be listed with an optional `status` filter alongside the usual page controls, and a single retailer read always reflects its live reserved-slot figure rather than a cached one."
    Design: Corner/endpoints/retailer_patch_updates_only_the_supplied_field_and_bumps_the_version
    """
    world = bigbox_world
    validate_success(
        api_client.patch_retailer(
            world["retailer"]["id"],
            patch_retailer_payload(read_retailer_version(world["retailer"]["id"]), status="PAUSED"),
            make_shelf_admin_headers(),
        )
    )

    rows, meta = validate_paginated(
        api_client.list_retailers(
            make_content_author_headers(),
            params={"status": "PAUSED", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world["retailer"]["id"]
    assert_slot_ledger(rows[0], 0)


def test_leaving_the_image_minimum_alone_leaves_all_three_listing_scores_alone(bigbox_world):
    """The adjustment recomputes every listing of the retailer, but the recompute reads
    the same `min_image_count` of 4 it read before, so certified stays 85.00, declared
    stays 90.00 and readiness stays 51.00.

    PRD 3.1: "Its consequences reach further than the retailer row: the retailer's `version` increments by 1, then `completeness_score_declared`, `completeness_score_certified` and `readiness_score` are recomputed for every listing belonging to that retailer — because `min_image_count` feeds the image component of the certified variant — and then `shelf_health_index` is recomputed for every product touched by those listings."
    Design: Corner/endpoints/retailer_patch_updates_only_the_supplied_field_and_bumps_the_version
    """
    world = bigbox_world
    validate_success(
        api_client.patch_retailer(
            world["retailer"]["id"],
            patch_retailer_payload(read_retailer_version(world["retailer"]["id"]), status="PAUSED"),
            make_shelf_admin_headers(),
        )
    )

    listing = _listing(world["listing"]["id"])
    assert float(listing["completeness_score_certified"]) == pytest.approx(85.00, abs=0.01)
    assert float(listing["completeness_score_declared"]) == pytest.approx(90.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)
    assert listing["syndication_state"] == "NOT_SYNDICATED"


def test_a_partially_accepted_job_reopens_as_attempt_two_with_both_stamps_cleared(
    bigbox_world,
):
    """PARTIALLY_ACCEPTED is a requeueable state even with the warning row still open:
    the job returns to QUEUED as attempt 2 with its transmission and response stamps
    wiped, and the six requested slots are reserved again.

    PRD 3.7: "A successful requeue moves the job back to `QUEUED`, increments `attempt_no` by 1, resets `transmitted_at` and `responded_at` to null, and re-reserves the slots so the retailer's `feed_slots_reserved` is recomputed upward and its `version` increments by 1."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)
    assert job["attempt_no"] == 1
    assert _job(job["id"])["state"] == "PARTIALLY_ACCEPTED"
    assert _listing(world["listing"]["id"])["syndication_state"] == "LIVE"
    before = _retailer(world["retailer"]["id"])
    assert_slot_ledger(before, 0)
    assert before["version"] == 3

    requeued = _requeue(world, job["id"])
    assert requeued["state"] == "QUEUED"
    assert requeued["attempt_no"] == 2
    assert requeued["transmitted_at"] is None
    assert requeued["responded_at"] is None

    after = _retailer(world["retailer"]["id"])
    assert_slot_ledger(after, 6)
    assert after["version"] == 4


def test_the_supplied_slot_count_and_window_overwrite_the_stored_ones(bigbox_world):
    """Every figure the requeue supplies replaces the one the first attempt carried, so
    the job now stands on six slots inside the 18th-to-19th window.

    PRD 3.7: "A `SyndicationOperator` requeues it, optionally supplying a fresh `slot_count`, a fresh `window_start`, a fresh `window_end` and `expected_retailer_version`; any value supplied overwrites the corresponding field on the job, and any value omitted leaves the existing one in place."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)
    assert job["slot_count"] == 4

    requeued = _requeue(world, job["id"])
    assert requeued["slot_count"] == 6
    assert requeued["window_start"].startswith("2026-08-18T00:00:00")
    assert requeued["window_end"].startswith("2026-08-19T00:00:00")

    stored = _job(job["id"])
    assert stored["slot_count"] == 6
    assert stored["window_start"].startswith("2026-08-18T00:00:00")


def test_the_larger_slot_count_refreezes_the_fee_in_the_ten_percent_band(bigbox_world):
    """Four slots subtotalled 10000 cents and earned the 5 percent band for a fee of
    9500; six slots subtotal 15000 and land on the 10 percent band instead, so the
    refrozen fee is 13500 with no rush surcharge either way.

    PRD 3.6: "Second, a volume discount percentage is selected **from that subtotal**: no discount when the subtotal is below 5000 cents, 5 percent when the subtotal is at least 5000 and below 15000 cents, 10 percent when it is at least 15000 and below 25000 cents, and 15 percent when it is 25000 cents or more."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)
    assert job["service_fee_cents"] == 9500

    requeued = _requeue(world, job["id"])
    assert requeued["service_fee_cents"] == 13500


def test_the_requeue_recaptures_the_listings_readiness_as_it_now_stands(bigbox_world):
    """The frozen readiness figure is taken again at the moment of the requeue, and the
    listing still reads 51.00 because nothing touched its inputs.

    PRD 3.7: "Both frozen figures are re-frozen at the current clock position: `readiness_at_queue` recaptures the listing's readiness as it now stands, and `service_fee_cents` is recomputed from scratch — which is how a requeue into a window less than 24 hours away picks up a rush surcharge the original attempt never paid."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)

    requeued = _requeue(world, job["id"])
    assert float(requeued["readiness_at_queue"]) == pytest.approx(51.00, abs=0.01)
    assert float(_listing(world["listing"]["id"])["readiness_score"]) == pytest.approx(
        51.00, abs=0.01
    )


def test_the_requeue_takes_the_listing_back_from_live_to_pending(bigbox_world):
    """The previous attempt was partially accepted, so the listing was LIVE; the new
    attempt puts it back on PENDING while the retailer decides again.

    PRD 3.7: "The listing's `syndication_state` becomes `PENDING`, coming from `NOT_SYNDICATED` when the previous attempt was rejected and its blocking errors were subsequently cleared, or from `LIVE` when the previous attempt was partially accepted."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)
    assert _listing(world["listing"]["id"])["syndication_state"] == "LIVE"

    _requeue(world, job["id"])
    assert _listing(world["listing"]["id"])["syndication_state"] == "PENDING"


def test_cancelling_the_requeued_job_waives_the_surviving_warning_row(bigbox_world):
    """The warning row outlived the first attempt and the requeue; the cancellation
    closes it with the platform's own note rather than leaving it open against a dead
    job.

    PRD 3.6: "Every `OPEN` rejection error still attached to the cancelled job is moved to `WAIVED` with `resolution_note` set to `CANCELLED_WITH_JOB`."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)
    _requeue(world, job["id"])

    rows, meta = _rejection_rows(job["id"])
    assert meta["total_count"] == 1
    assert rows[0]["state"] == "OPEN"

    _cancel(job["id"])

    rows, meta = _rejection_rows(job["id"])
    assert meta["total_count"] == 1
    assert_rejection_error(rows[0])
    assert rows[0]["severity"] == "WARNING"
    assert rows[0]["state"] == "WAIVED"
    assert rows[0]["resolution_note"] == CANCELLED_WITH_JOB


def test_the_cancellation_hands_back_every_reserved_slot(bigbox_world):
    """The six slots the requeue took are released in full, and the release is another
    write on the retailer, so its version moves once more.

    PRD 3.6: "Cancellation releases the whole reservation: the retailer's `feed_slots_reserved` is recomputed from the ledger, dropping the job's `slot_count`, and the retailer's `version` increments by 1."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)
    _requeue(world, job["id"])
    assert_slot_ledger(_retailer(world["retailer"]["id"]), 6)

    cancelled = _cancel(job["id"])
    assert cancelled["state"] == "CANCELLED"

    retailer = _retailer(world["retailer"]["id"])
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 5


def test_the_cancelled_listing_settles_on_not_syndicated_with_no_blocking_rows(bigbox_world):
    """With the waived warning leaving the blocking count at zero and no other job
    holding slots, the listing settles all the way back to NOT_SYNDICATED and its
    readiness carries no penalty.

    PRD 3.6: "The listing's `syndication_state` then settles: it becomes `ERROR_HOLD` when the listing still has a positive `open_blocking_error_count`, becomes `NOT_SYNDICATED` when the listing has no other job in `QUEUED` or `TRANSMITTED`, and is otherwise left unchanged."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)
    _requeue(world, job["id"])
    _cancel(job["id"])

    listing = _listing(world["listing"]["id"])
    assert listing["syndication_state"] == "NOT_SYNDICATED"
    assert listing["open_blocking_error_count"] == 0
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)


def test_the_cancelled_cycle_empties_the_products_health_input_set(bigbox_world):
    """Once the listing is neither LIVE nor on hold, nothing qualifies for the product's
    health roll-up, so the index falls back to 0.00 and the breakdown is empty.

    PRD 3.9: "The product's `shelf_health_index` aggregates only those of its listings whose `syndication_state` is `LIVE` or `ERROR_HOLD`; `NOT_SYNDICATED` and `PENDING` listings are excluded, and when no listing qualifies the index is 0.00 and the per-retailer breakdown is empty."
    Design: Corner/endpoints/partially_accepted_job_requeues_as_attempt_two_then_cancel_waives_the_warning_row
    """
    world = bigbox_world
    job = _partially_accepted_job(world)
    _requeue(world, job["id"])
    _cancel(job["id"])

    assert float(_product(world["product"]["id"])["shelf_health_index"]) == pytest.approx(
        0.00, abs=0.01
    )
    summary = _summary(world["product"]["id"])
    assert_shelf_summary(summary)
    assert summary["qualifying_listing_count"] == 0
    assert summary["retailer_subscores"] == []


def test_one_feed_response_writes_all_three_rows_in_the_order_they_arrived(bigbox_world):
    """The three complaints become three child rows in request order — blocking, then
    warning, then blocking — each keeping the severity and attribute key the retailer
    sent, and each starting open.

    PRD 3.7: "Each element becomes one rejection error row, created in request order, each starting in `state` `OPEN` with `resolution_mode` and `resolved_by_user_id` null."
    Design: Corner/endpoints/three_rejection_rows_are_written_in_request_order_with_per_row_severity
    """
    world = bigbox_world
    job, response = _reject_with_three_rows(world)
    assert validate_success(response)["state"] == "REJECTED"

    rows, meta = _rejection_rows(job["id"], params={"limit": 10, "offset": 0})
    assert meta["total_count"] == 3
    assert [row["retailer_error_code"] for row in rows] == [
        "E-BRAND-MISSING",
        "E-DESC-STYLE",
        "E-IMG-COUNT",
    ]
    assert [row["severity"] for row in rows] == ["BLOCKING", "WARNING", "BLOCKING"]
    assert [row["attribute_key"] for row in rows] == ["brand", "description", "title"]
    for row in rows:
        assert_rejection_error(row)
        assert row["state"] == "OPEN"
        assert row["resolution_mode"] is None
        assert row["resolved_by_user_id"] is None


def test_the_severity_and_state_filters_pick_out_the_two_blocking_rows(bigbox_world):
    """Filtering the same child collection on blocking-and-open returns two of the three
    rows; the warning in the middle is simply not a member.

    PRD 3.7: "A job's rejection error rows can be read back as a list, optionally filtered by `severity` and by `state`."
    Design: Corner/endpoints/three_rejection_rows_are_written_in_request_order_with_per_row_severity
    """
    world = bigbox_world
    job, _response = _reject_with_three_rows(world)

    rows, meta = _rejection_rows(job["id"], params={"severity": "BLOCKING", "state": "OPEN"})
    assert meta["total_count"] == 2
    assert [row["retailer_error_code"] for row in rows] == ["E-BRAND-MISSING", "E-IMG-COUNT"]


def test_only_the_blocking_rows_feed_the_listings_open_blocking_count(bigbox_world):
    """Two of the three rows block, so the listing's count is 2 rather than 3, and a
    positive count puts the listing on hold.

    PRD 3.7: "*Hop 2, caused by hop 1's `BLOCKING` rows:* the listing's `open_blocking_error_count` is recomputed and is now positive, so the listing's `syndication_state` becomes `ERROR_HOLD` and its `readiness_score` is recomputed with the new penalty tier."
    Design: Corner/endpoints/three_rejection_rows_are_written_in_request_order_with_per_row_severity
    """
    world = bigbox_world
    _reject_with_three_rows(world)

    listing = _listing(world["listing"]["id"])
    assert listing["open_blocking_error_count"] == 2
    assert listing["syndication_state"] == "ERROR_HOLD"


def test_a_count_of_two_costs_the_listing_the_five_point_penalty(bigbox_world):
    """Two open blocking rows sit in the first penalty band, so the readiness blend of
    51.00 loses exactly 5 points and reads 46.00 — the warning row costs nothing.

    PRD 3.7: "It selects the readiness penalty described in §3.4 in four bands: no penalty at all when the count is zero, 5 points when the count is 1 or 2, 12 points when the count is 3, 4 or 5, and 25 points once the count reaches 6 or more."
    Design: Corner/endpoints/three_rejection_rows_are_written_in_request_order_with_per_row_severity
    """
    world = bigbox_world
    _reject_with_three_rows(world)

    listing = _listing(world["listing"]["id"])
    assert float(listing["readiness_score"]) == pytest.approx(46.00, abs=0.01)


def test_the_rejection_releases_the_four_reserved_slots(bigbox_world):
    """The response takes the job out of the holding states, so the four slots come back
    and the retailer lands on version 3 — one bump for the queue, one for the response.

    PRD 3.7: "*Hop 1:* the job's `state` becomes `REJECTED`, `responded_at` is stamped, one rejection error row is created per element of `errors` in request order, the retailer's `feed_slots_reserved` drops by the job's `slot_count` and the retailer's `version` increments by 1."
    Design: Corner/endpoints/three_rejection_rows_are_written_in_request_order_with_per_row_severity
    """
    world = bigbox_world
    job, _response = _reject_with_three_rows(world)

    retailer = _retailer(world["retailer"]["id"])
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 3
    assert _job(job["id"])["responded_at"].startswith("2026-08-10T00:00:00")


def test_the_held_listing_scores_twenty_on_availability_alone(bigbox_world):
    """The listing joins the health input set on hold with nothing observed: accuracy
    counts as 0, the missing rank counts as 0 and the missing rating counts as 0, so
    only the in-stock component survives and the index is 20.00.

    PRD 3.9: "The subscore is 0.45 of the accuracy component plus 0.25 of the rank component plus 0.20 of the availability component plus 0.10 of the rating component, **rounded half up to 2 decimal places at this point**."
    Design: Corner/endpoints/three_rejection_rows_are_written_in_request_order_with_per_row_severity
    """
    world = bigbox_world
    _reject_with_three_rows(world)

    listing = _listing(world["listing"]["id"])
    assert listing["content_accuracy_pct"] is None
    assert listing["search_rank_latest"] is None
    assert listing["rating_avg"] is None
    assert listing["in_stock"] is True

    assert float(_product(world["product"]["id"])["shelf_health_index"]) == pytest.approx(
        20.00, abs=0.01
    )
    summary = _summary(world["product"]["id"])
    assert summary["qualifying_listing_count"] == 1
    assert _subscore_values(summary) == [pytest.approx(20.00, abs=0.01)]


def test_the_index_of_twenty_raises_one_health_degraded_alert(bigbox_world):
    """20.00 is well under the alert threshold, so the recompute that follows the
    rejection raises a single medium health alert with no observation behind it.

    PRD 3.7: "*Hop 3, caused by hop 2's `ERROR_HOLD` write, which admits the listing into the health input set:* the product's `shelf_health_index` is recomputed, and when the recomputed index falls below 60.00 a shelf alert with `alert_type` `HEALTH_DEGRADED`, `severity` `MEDIUM` and a null `source_observation_id` is created on that listing — suppressed when a `HEALTH_DEGRADED` alert is already `OPEN` or `ACKNOWLEDGED` there."
    Design: Corner/endpoints/three_rejection_rows_are_written_in_request_order_with_per_row_severity
    """
    world = bigbox_world
    _reject_with_three_rows(world)

    alerts, meta = _alerts(
        {"retailer_listing_id": world["listing"]["id"], "alert_type": "HEALTH_DEGRADED"}
    )
    assert meta["total_count"] == 1
    assert alerts[0]["severity"] == "MEDIUM"
    assert alerts[0]["state"] == "OPEN"
    assert alerts[0]["source_observation_id"] is None


def test_the_single_health_alert_flags_the_product_as_content_at_risk(bigbox_world):
    """One open alert and no unauthorized-seller alert among them puts the product on
    CONTENT_AT_RISK with an alert count of exactly 1.

    PRD 3.7: "*Hop 4, caused by hop 3's alert row:* the product's `open_alert_count` is recomputed and its `governance_flag` becomes `CONTENT_AT_RISK`, or `LISTING_RISK` when an `UNAUTHORIZED_LISTING` alert is also open, and the product's `version` increments by 1."
    Design: Corner/endpoints/three_rejection_rows_are_written_in_request_order_with_per_row_severity
    """
    world = bigbox_world
    _reject_with_three_rows(world)

    product = _product(world["product"]["id"])
    assert product["open_alert_count"] == 1
    assert product["governance_flag"] == "CONTENT_AT_RISK"


def test_a_deployment_naming_an_unknown_change_request_resolves_nothing(simplemart_world):
    """The governance record is looked up before any state is written, so a deployment
    citing an id that no change request carries is a plain not-found and the listing's
    calendar stays empty.

    PRD 2.8: "The referenced change request exists — otherwise `ERR_CHANGE_REQUEST_NOT_FOUND`."
    Design: Corner/endpoints/deployment_link_requires_all_three_referenced_rows_to_exist
    """
    world = simplemart_world
    response = api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            MISSING_CHANGE_REQUEST_ID,
            world["asset"]["id"],
            "A_PLUS_PAGE",
            DEPLOYMENT_WINDOW[0],
            DEPLOYMENT_WINDOW[1],
            read_listing_version(world["listing"]["id"]),
        ),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_CHANGE_REQUEST_NOT_FOUND.value, 404)

    _rows, meta = validate_paginated(
        api_client.list_enhanced_deployments(
            make_content_author_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_a_deployment_naming_an_unknown_media_asset_resolves_nothing(simplemart_world):
    """The rich-media row is resolved on the same terms: an id belonging to no asset is
    a not-found rather than an approval or scope complaint.

    PRD 2.8: "The referenced media asset exists — otherwise `ERR_MEDIA_ASSET_NOT_FOUND`."
    Design: Corner/endpoints/deployment_link_requires_all_three_referenced_rows_to_exist
    """
    world = simplemart_world
    response = api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            MISSING_MEDIA_ASSET_ID,
            "A_PLUS_PAGE",
            DEPLOYMENT_WINDOW[0],
            DEPLOYMENT_WINDOW[1],
            read_listing_version(world["listing"]["id"]),
        ),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_MEDIA_ASSET_NOT_FOUND.value, 404)

    _rows, meta = validate_paginated(
        api_client.list_enhanced_deployments(
            make_content_author_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_neither_failed_link_moves_the_listing_version(simplemart_world):
    """Because both refusals wrote nothing, the version the caller read before them is
    still the listing's current one, and the third attempt carrying that very same
    number is accepted.

    PRD 3.8: "Finally `expected_retailer_listing_version` must equal the listing's current `version`, or the creation fails with `ERR_STALE_VERSION`."
    Design: Corner/endpoints/deployment_link_requires_all_three_referenced_rows_to_exist
    """
    world = simplemart_world
    listing_version = read_listing_version(world["listing"]["id"])

    api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            MISSING_CHANGE_REQUEST_ID,
            world["asset"]["id"],
            "A_PLUS_PAGE",
            DEPLOYMENT_WINDOW[0],
            DEPLOYMENT_WINDOW[1],
            listing_version,
        ),
        make_content_author_headers(),
    )
    api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            MISSING_MEDIA_ASSET_ID,
            "A_PLUS_PAGE",
            DEPLOYMENT_WINDOW[0],
            DEPLOYMENT_WINDOW[1],
            listing_version,
        ),
        make_content_author_headers(),
    )
    assert read_listing_version(world["listing"]["id"]) == listing_version

    created = validate_success(
        api_client.create_enhanced_deployment(
            create_deployment_payload(
                world["listing"]["id"],
                world["change_request"]["id"],
                world["asset"]["id"],
                "A_PLUS_PAGE",
                DEPLOYMENT_WINDOW[0],
                DEPLOYMENT_WINDOW[1],
                listing_version,
            ),
            make_content_author_headers(),
        ),
        201,
    )
    assert created["state"] == "PENDING_RETAILER_APPROVAL"


def _successful_deployment(world):
    """The A+ module the third attempt lands, cited against the approved change request
    and the approved hero asset."""
    return validate_success(
        api_client.create_enhanced_deployment(
            create_deployment_payload(
                world["listing"]["id"],
                world["change_request"]["id"],
                world["asset"]["id"],
                "A_PLUS_PAGE",
                DEPLOYMENT_WINDOW[0],
                DEPLOYMENT_WINDOW[1],
                read_listing_version(world["listing"]["id"]),
            ),
            make_content_author_headers(),
        ),
        201,
    )


def test_the_created_deployment_echoes_all_three_references_it_joined(simplemart_world):
    """The retailer requires approval, so the module is created waiting for it, and the
    row carries back the listing, the change request and the asset it links.

    PRD 3.8: "When the retailer's `enhanced_content_requires_approval` is true, the deployment is created in `PENDING_RETAILER_APPROVAL` and awaits a decision."
    Design: Corner/endpoints/deployment_link_requires_all_three_referenced_rows_to_exist
    """
    world = simplemart_world
    created = _successful_deployment(world)
    assert_enhanced_deployment(created)
    assert created["state"] == "PENDING_RETAILER_APPROVAL"
    assert created["retailer_listing_id"] == world["listing"]["id"]
    assert created["change_request_id"] == world["change_request"]["id"]
    assert created["media_asset_id"] == world["asset"]["id"]
    assert created["module_kind"] == "A_PLUS_PAGE"
    assert created["retailer_decision_at"] is None


def test_the_link_bumps_the_listing_and_takes_a_second_pin_reference(simplemart_world):
    """A pending module is still a live reference to the revision the change request
    named, so the pin ledger reads 2 — one listing pin plus this deployment — and the
    listing's version moves once.

    PRD 3.8: "Either way the listing's `version` increments by 1, and the `pin_count` of the revision named by the change request's `target_content_version_id` is recomputed upward, because an active deployment is a second kind of live reference to a revision."
    Design: Corner/endpoints/deployment_link_requires_all_three_referenced_rows_to_exist
    """
    world = simplemart_world
    before = read_listing_version(world["listing"]["id"])
    assert_pin_ledger(_revision(world["revision"]["id"]), 1)

    _successful_deployment(world)

    assert read_listing_version(world["listing"]["id"]) == before + 1
    assert_pin_ledger(_revision(world["revision"]["id"]), 2)


def test_the_new_module_is_findable_by_its_change_request_and_state(simplemart_world):
    """Filtering the calendar by the authorising governance record and the pending state
    returns exactly the module just created.

    PRD 3.8: "Deployments can be listed filtered by `retailer_listing_id`, by `change_request_id`, by `media_asset_id`, or by `state`."
    Design: Corner/endpoints/deployment_link_requires_all_three_referenced_rows_to_exist
    """
    world = simplemart_world
    created = _successful_deployment(world)

    rows, meta = validate_paginated(
        api_client.list_enhanced_deployments(
            make_content_author_headers(),
            params={
                "change_request_id": world["change_request"]["id"],
                "state": "PENDING_RETAILER_APPROVAL",
            },
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == created["id"]


def test_a_pending_module_earns_the_listing_no_readiness_bonus(simplemart_world):
    """Readiness stays on 60.00 after the link: the five points are earned by being
    published, not by waiting to be.

    PRD 3.8: "A deployment sitting in `PENDING_RETAILER_APPROVAL` earns nothing — waiting for approval is not the same as being published."
    Design: Corner/endpoints/deployment_link_requires_all_three_referenced_rows_to_exist
    """
    world = simplemart_world
    assert float(_listing(world["listing"]["id"])["readiness_score"]) == pytest.approx(
        60.00, abs=0.01
    )

    _successful_deployment(world)

    assert float(_listing(world["listing"]["id"])["readiness_score"]) == pytest.approx(
        60.00, abs=0.01
    )


def test_the_summary_read_exposes_one_subscore_for_the_one_qualifying_listing(bigbox_world):
    """The computed read answers with the product it was asked about, the count of
    listings that qualified, a breakdown holding exactly that many entries, and the
    variant it applied.

    PRD 3.9: "The response echoes `product_id`, reports the two-stage-rounded `shelf_health_index` together with `qualifying_listing_count` and a `retailer_subscores` array giving the per-listing breakdown in the same ascending-`created_at` order used by the aggregation, and reports `conversion_lift_pct` alongside the `lift_variant` actually applied and the group sizes `high_group_size` and `base_group_size` that produced it."
    Design: Corner/endpoints/shelf_summary_read_returns_the_per_retailer_subscore_behind_the_index
    """
    world = bigbox_world
    _take_live_and_crawl(world)

    summary = _summary(world["product"]["id"])
    assert_shelf_summary(summary)
    assert summary["product_id"] == world["product"]["id"]
    assert summary["qualifying_listing_count"] == 1
    assert len(summary["retailer_subscores"]) == 1
    assert summary["lift_variant"] == DEFAULT_LIFT_VARIANT


def test_the_index_is_the_mean_of_the_one_rounded_subscore(bigbox_world):
    """With a single qualifying listing the mean is that listing's own subscore —
    41.40 from accuracy, 18.75 from rank 6, 20.00 from availability and 9.00 from the
    rating — so the read and the stored field both say 89.15.

    PRD 3.9: "The index is then the arithmetic mean of those already-rounded subscores, rounded half up to 2 decimal places again."
    Design: Corner/endpoints/shelf_summary_read_returns_the_per_retailer_subscore_behind_the_index
    """
    world = bigbox_world
    _take_live_and_crawl(world)

    summary = _summary(world["product"]["id"])
    assert _subscore_values(summary) == [pytest.approx(89.15, abs=0.01)]
    assert float(summary["shelf_health_index"]) == pytest.approx(89.15, abs=0.01)
    assert float(_product(world["product"]["id"])["shelf_health_index"]) == pytest.approx(
        89.15, abs=0.01
    )


def test_the_default_variant_files_the_post_pin_crawl_under_high(bigbox_world):
    """The crawl landed on the 11th and the pin on the 10th, so the only observation the
    product has falls into HIGH and BASE is left empty.

    PRD 3.9: "The default variant, named `post_pin_window`, splits on pin time: observations whose `observed_at` is at or after the product's `last_pinned_at` form HIGH, and those strictly before it form BASE."
    Design: Corner/endpoints/shelf_summary_read_returns_the_per_retailer_subscore_behind_the_index
    """
    world = bigbox_world
    _take_live_and_crawl(world)
    assert _product(world["product"]["id"])["last_pinned_at"].startswith("2026-08-10T00:00:00")

    summary = _summary(world["product"]["id"])
    assert summary["high_group_size"] == 1
    assert summary["base_group_size"] == 0


def test_an_empty_base_group_reports_a_zero_lift(bigbox_world):
    """There is nothing to compare the post-pin conversion against, so the lift falls
    back to 0.00 on both the computed read and the stored roll-up.

    PRD 3.9: "If either group is empty the lift is 0.00."
    Design: Corner/endpoints/shelf_summary_read_returns_the_per_retailer_subscore_behind_the_index
    """
    world = bigbox_world
    _take_live_and_crawl(world)

    summary = _summary(world["product"]["id"])
    assert float(summary["conversion_lift_pct"]) == pytest.approx(0.00, abs=0.01)
    assert float(_product(world["product"]["id"])["conversion_lift_pct"]) == pytest.approx(
        0.00, abs=0.01
    )


def test_the_observed_accuracy_lifts_the_listings_readiness_to_eighty_seven_eighty(
    bigbox_world,
):
    """Sixty percent of the certified 85.00 plus forty percent of the observed 92.00 is
    87.80, with no floor applied because the listing is still OK and no penalty or bonus
    in play.

    PRD 3.4: "It blends 60 percent of the listing's `completeness_score_certified` with 40 percent of a floored accuracy figure, then subtracts a penalty for unresolved blocking feed errors and adds a bonus for live enhanced content, clamps the result to the range 0 to 100, and rounds half up to 2 decimal places."
    Design: Corner/endpoints/shelf_summary_read_returns_the_per_retailer_subscore_behind_the_index
    """
    world = bigbox_world
    _take_live_and_crawl(world)

    listing = _listing(world["listing"]["id"])
    assert listing["shelf_state"] == "OK"
    assert listing["open_blocking_error_count"] == 0
    assert float(listing["readiness_score"]) == pytest.approx(87.80, abs=0.01)


def test_the_crawl_is_copied_onto_the_listing_without_rounding(bigbox_world):
    """The snapshot behind the index is the observation itself: rank 6, accuracy 92.00,
    4.50 stars and in stock, all carried across verbatim.

    PRD 3.9: "That row's values are copied verbatim onto the listing with no rounding: `search_rank` into `search_rank_latest`, and `content_accuracy_pct`, `rating_avg` and `in_stock` into the like-named listing fields."
    Design: Corner/endpoints/shelf_summary_read_returns_the_per_retailer_subscore_behind_the_index
    """
    world = bigbox_world
    _take_live_and_crawl(world)

    listing = _listing(world["listing"]["id"])
    assert listing["search_rank_latest"] == 6
    assert float(listing["content_accuracy_pct"]) == pytest.approx(92.00, abs=0.01)
    assert float(listing["rating_avg"]) == pytest.approx(4.50, abs=0.01)
    assert listing["in_stock"] is True


def test_a_healthy_crawl_leaves_the_governance_flag_on_none(bigbox_world):
    """Accuracy above the drift threshold, no unauthorized seller, in stock and an index
    well above the alert line leave the alert set empty, so the flag falls through to
    NONE.

    PRD 3.9: "Its `governance_flag` is derived from that same set under a pinned precedence, evaluated top to bottom: it is `LISTING_RISK` when any alert in the set has `alert_type` `UNAUTHORIZED_LISTING`; otherwise `CONTENT_AT_RISK` when the count is 1 or more; otherwise `NONE`."
    Design: Corner/endpoints/shelf_summary_read_returns_the_per_retailer_subscore_behind_the_index
    """
    world = bigbox_world
    _take_live_and_crawl(world)

    product = _product(world["product"]["id"])
    assert product["open_alert_count"] == 0
    assert product["governance_flag"] == "NONE"

    _rows, meta = _alerts({"retailer_listing_id": world["listing"]["id"]})
    assert meta["total_count"] == 0


def _live_after_a_weak_crawl(world):
    """The drifted crawl first, then the feed cycle that takes the listing LIVE, so the
    health recompute happens with the poor snapshot already in place."""
    first = _weak_crawl(world, "2026-08-11T00:00:00Z")
    job = _transmitted_job(world)
    accept_job(job["id"], world["retailer"]["id"])
    return first


def test_a_crawl_of_an_unsyndicated_listing_leaves_the_index_at_zero(bigbox_world):
    """The listing has never been transmitted, so however bad the crawl is it contributes
    nothing: the input set is empty and the index reads 0.00.

    PRD 3.9: "The product's `shelf_health_index` aggregates only those of its listings whose `syndication_state` is `LIVE` or `ERROR_HOLD`; `NOT_SYNDICATED` and `PENDING` listings are excluded, and when no listing qualifies the index is 0.00 and the per-retailer breakdown is empty."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _weak_crawl(world, "2026-08-11T00:00:00Z")

    assert _listing(world["listing"]["id"])["syndication_state"] == "NOT_SYNDICATED"
    assert float(_product(world["product"]["id"])["shelf_health_index"]) == pytest.approx(
        0.00, abs=0.01
    )


def test_the_first_crawl_raises_no_health_alert_while_the_listing_is_unsyndicated(bigbox_world):
    """An index of 0.00 is below every threshold and still raises nothing, because a
    listing outside the input set cannot carry a health alert; the single open alert on
    the product is the drift one.

    PRD 3.9: "A `NOT_SYNDICATED` or `PENDING` listing never raises it, which is precisely why the empty-input-set index of 0.00 is not an alert condition."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _weak_crawl(world, "2026-08-11T00:00:00Z")

    _rows, meta = _alerts(
        {"retailer_listing_id": world["listing"]["id"], "alert_type": "HEALTH_DEGRADED"}
    )
    assert meta["total_count"] == 0

    product = _product(world["product"]["id"])
    assert product["open_alert_count"] == 1
    assert product["governance_flag"] == "CONTENT_AT_RISK"


def test_the_drifted_crawl_raises_one_low_severity_content_drift_alert(bigbox_world):
    """Thirty percent accuracy is far under the drift line, so the ingest raises a single
    low-severity content alert.

    PRD 3.9: "An observation whose `content_accuracy_pct` is below 85.00 raises an alert with `alert_type` `CONTENT_DRIFT` and `severity` `LOW`."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _weak_crawl(world, "2026-08-11T00:00:00Z")

    alerts, meta = _alerts(
        {"retailer_listing_id": world["listing"]["id"], "alert_type": "CONTENT_DRIFT"}
    )
    assert meta["total_count"] == 1
    assert alerts[0]["severity"] == "LOW"
    assert alerts[0]["state"] == "OPEN"


def test_the_drift_alert_leaves_the_shelf_state_on_ok(bigbox_world):
    """The crawl saw the product in stock with no unauthorized seller, so the only thing
    wrong is the content itself and the availability dimension does not move.

    PRD 3.9: "Content drift does not move `shelf_state`; it is a content-quality signal, not an availability one."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _weak_crawl(world, "2026-08-11T00:00:00Z")

    assert _listing(world["listing"]["id"])["shelf_state"] == "OK"


def test_the_first_crawl_pulls_readiness_down_to_sixty_three(bigbox_world):
    """Sixty percent of the certified 85.00 plus forty percent of the observed 30.00 is
    63.00 — the accuracy is poor but the listing is still OK, so nothing is floored.

    PRD 3.4: "It blends 60 percent of the listing's `completeness_score_certified` with 40 percent of a floored accuracy figure, then subtracts a penalty for unresolved blocking feed errors and adds a bonus for live enhanced content, clamps the result to the range 0 to 100, and rounds half up to 2 decimal places."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _weak_crawl(world, "2026-08-11T00:00:00Z")

    assert float(_listing(world["listing"]["id"])["readiness_score"]) == pytest.approx(
        63.00, abs=0.01
    )


def test_a_search_rank_of_forty_one_contributes_nothing_to_the_index(bigbox_world):
    """Once the accepted feed makes the listing qualify, the index is 13.50 from
    accuracy plus 20.00 from availability plus 6.00 from the rating and nothing at all
    from rank 41, which decays past zero and is clamped there — 39.50 in total.

    PRD 3.9: "Its rank component is 0 when `search_rank_latest` is null, and otherwise 100 reduced by 5 points for every position below the first — so rank 1 scores 100, rank 6 scores 75, rank 11 scores 50 — with the result clamped to the range 0 to 100, meaning rank 21 and everything worse scores 0."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _live_after_a_weak_crawl(world)

    assert _listing(world["listing"]["id"])["search_rank_latest"] == 41
    assert float(_product(world["product"]["id"])["shelf_health_index"]) == pytest.approx(
        39.50, abs=0.01
    )


def test_going_live_recomputes_the_index_without_raising_an_alert_of_its_own(bigbox_world):
    """The accepted response recomputes readiness and the index — which now lands below
    the alert line — but the transition itself raises nothing, so the product still
    carries only the drift alert.

    PRD 3.7: "Because a `LIVE` listing now qualifies for the product's health input set, both the listing's `readiness_score` and the product's `shelf_health_index` are recomputed."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _live_after_a_weak_crawl(world)

    assert _listing(world["listing"]["id"])["syndication_state"] == "LIVE"
    _rows, meta = _alerts(
        {"retailer_listing_id": world["listing"]["id"], "alert_type": "HEALTH_DEGRADED"}
    )
    assert meta["total_count"] == 0
    assert _product(world["product"]["id"])["open_alert_count"] == 1


def test_the_second_crawl_raises_the_health_alert_now_that_the_listing_qualifies(bigbox_world):
    """The repeated crawl changes no projected field, but this time the health recompute
    runs on a LIVE listing sitting at 39.50, so the medium health alert is finally
    raised.

    PRD 3.9: "An alert with `alert_type` `HEALTH_DEGRADED` and `severity` `MEDIUM` is raised on the listing only when the listing is actually inside the product's health input set — that is, its `syndication_state` is `LIVE` or `ERROR_HOLD` — **and** the recomputed `shelf_health_index` is below 60.00."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _live_after_a_weak_crawl(world)
    _weak_crawl(world, "2026-08-12T00:00:00Z")

    alerts, meta = _alerts(
        {
            "retailer_listing_id": world["listing"]["id"],
            "alert_type": "HEALTH_DEGRADED",
            "state": "OPEN",
        }
    )
    assert meta["total_count"] == 1
    assert alerts[0]["severity"] == "MEDIUM"


def test_the_repeated_drift_is_deduplicated_against_the_still_open_alert(bigbox_world):
    """The second crawl is as inaccurate as the first, but the drift alert it would raise
    is suppressed while the first one is still open, so the listing carries one.

    PRD 3.9: "Three monitoring rules then fire, and every alert they raise is de-duplicated: a rule never creates a second alert of the same `alert_type` on the same listing while one of that type is already `OPEN` or `ACKNOWLEDGED`."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _live_after_a_weak_crawl(world)
    _weak_crawl(world, "2026-08-12T00:00:00Z")

    _rows, meta = _alerts(
        {"retailer_listing_id": world["listing"]["id"], "alert_type": "CONTENT_DRIFT"}
    )
    assert meta["total_count"] == 1


def test_the_two_surviving_alerts_are_counted_once_each(bigbox_world):
    """Drift plus health makes two open alerts across the product's one listing; neither
    is an unauthorized-seller alert, so the flag stays CONTENT_AT_RISK and the index the
    second crawl recomputed is unchanged at 39.50.

    PRD 3.9: "The product's `open_alert_count` is the number of alerts across every listing of the product whose `state` is `OPEN` or `ACKNOWLEDGED`."
    Design: Corner/endpoints/health_degraded_alert_is_raised_only_once_the_listing_is_live
    """
    world = bigbox_world
    _live_after_a_weak_crawl(world)
    _weak_crawl(world, "2026-08-12T00:00:00Z")

    product = _product(world["product"]["id"])
    assert product["open_alert_count"] == 2
    assert product["governance_flag"] == "CONTENT_AT_RISK"
    assert float(product["shelf_health_index"]) == pytest.approx(39.50, abs=0.01)
