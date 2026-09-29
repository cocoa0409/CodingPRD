"""Three shared parents, three version fields: the second reviewer, the second placement
and the second queue each have to prove they saw the parent as it now stands."""
import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_pin_ledger, assert_slot_ledger
from test_helpers.factories import (
    create_deployment_payload,
    create_syndication_job_payload,
    review_payload,
)
from test_helpers.fixtures import (
    read_listing_version,
    read_product_version,
    read_retailer_version,
    transmit_job,
)
from test_helpers.test_users import (
    make_brand_approver_headers,
    make_content_author_headers,
    make_legal_reviewer_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

FIRST_DEPLOYMENT_WINDOW = ("2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z")
SECOND_DEPLOYMENT_WINDOW = ("2026-08-14T00:00:00Z", "2026-08-15T00:00:00Z")
FIRST_FEED_WINDOW = ("2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z")
SECOND_FEED_WINDOW = ("2026-08-18T00:00:00Z", "2026-08-19T00:00:00Z")


def _listing(retailer_listing_id):
    return validate_success(
        api_client.get_retailer_listing(retailer_listing_id, make_shelf_admin_headers())
    )


def _revision(content_version_id):
    return validate_success(
        api_client.get_content_version(content_version_id, make_content_author_headers())
    )


def _retailer(retailer_id):
    return validate_success(api_client.get_retailer(retailer_id, make_shelf_admin_headers()))


def _change_request(change_request_id):
    return validate_success(
        api_client.get_change_request(change_request_id, make_content_author_headers())
    )


def _decide(change_request_id, track, headers, expected_product_version):
    return api_client.create_review(
        change_request_id,
        review_payload(track, "APPROVED", expected_product_version),
        headers,
    )


def _approve_legal(world, expected_product_version):
    return validate_success(
        _decide(
            world["change_request"]["id"],
            "LEGAL",
            make_legal_reviewer_headers(),
            expected_product_version,
        )
    )


def _deploy(world, module_kind, window, expected_retailer_listing_version):
    return api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            world["asset"]["id"],
            module_kind,
            window[0],
            window[1],
            expected_retailer_listing_version,
        ),
        make_content_author_headers(),
    )


def _deployments(world, params=None):
    return validate_paginated(
        api_client.list_enhanced_deployments(
            make_content_author_headers(),
            params=params or {"retailer_listing_id": world["listing"]["id"]},
        )
    )


def test_the_legal_decision_advances_the_shared_product_version(simplemart_world_unpinned):
    """Every review decision touches the product the two tracks share, so the version the
    brand reviewer read before the legal decision is already one behind.

    PRD 3.5: "Whichever way the decision goes, the acting identity is recorded as `legal_reviewer_user_id` or `brand_reviewer_user_id` according to the track, the product's `last_review_at` is stamped from the logical clock, and the product's `version` increments by 1."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_product_version_on_the_second_review_track_returns_412
    """
    world = simplemart_world_unpinned
    version_before = read_product_version(world["product"]["id"])

    decided = _approve_legal(world, version_before)
    assert decided["legal_reviewer_user_id"] == "legal_1"

    assert read_product_version(world["product"]["id"]) == version_before + 1


def test_the_brand_reviewer_holding_the_pre_legal_version_is_refused(
    simplemart_world_unpinned,
):
    """The BRAND track is genuinely still open, so nothing about the business flow objects —
    what refuses the call is that the reviewer is deciding from a product view predating the
    LEGAL decision.

    PRD 2.6: "Recording a review-track decision must carry `expected_product_version` matching the current `version` of the change request's product."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_product_version_on_the_second_review_track_returns_412
    """
    world = simplemart_world_unpinned
    stale_version = read_product_version(world["product"]["id"])
    _approve_legal(world, stale_version)

    response = _decide(
        world["change_request"]["id"], "BRAND", make_brand_approver_headers(), stale_version
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_the_stale_review_wrote_nothing_at_all(simplemart_world_unpinned):
    """The refused decision left the track PENDING, the request in review, the revision still
    frozen for review rather than pinned, the listing unpinned — and it did not itself advance
    the version, so a re-read returns exactly what the LEGAL decision left.

    PRD 2.8: "The supplied concurrency field equals the current `version` of its named parent — otherwise `ERR_STALE_VERSION`."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_product_version_on_the_second_review_track_returns_412
    """
    world = simplemart_world_unpinned
    stale_version = read_product_version(world["product"]["id"])
    _approve_legal(world, stale_version)
    _decide(
        world["change_request"]["id"], "BRAND", make_brand_approver_headers(), stale_version
    )

    change_request = _change_request(world["change_request"]["id"])
    assert change_request["brand_review_state"] == "PENDING"
    assert change_request["state"] == "IN_REVIEW"

    assert _revision(world["revision"]["id"])["state"] == "IN_REVIEW"
    assert _listing(world["listing"]["id"])["pinned_content_version_id"] is None
    assert read_product_version(world["product"]["id"]) == stale_version + 1


def test_the_retry_with_the_re_read_version_pins_the_revision(simplemart_world_unpinned):
    """Re-reading the product and resubmitting the identical decision reaches the join, and
    the join is what takes the revision out of review and into the pinned state.

    PRD 3.5: "The target revision transitions `IN_REVIEW → PINNED`."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_product_version_on_the_second_review_track_returns_412
    """
    world = simplemart_world_unpinned
    stale_version = read_product_version(world["product"]["id"])
    _approve_legal(world, stale_version)
    _decide(
        world["change_request"]["id"], "BRAND", make_brand_approver_headers(), stale_version
    )

    joined = validate_success(
        _decide(
            world["change_request"]["id"],
            "BRAND",
            make_brand_approver_headers(),
            read_product_version(world["product"]["id"]),
        )
    )
    assert joined["state"] == "APPROVED"
    assert _revision(world["revision"]["id"])["state"] == "PINNED"


def test_the_join_rescores_the_listing_and_advanced_the_product_exactly_twice(
    simplemart_world_unpinned,
):
    """The accepted retry runs the whole join: both completeness variants and readiness are
    recomputed on the listing, the pinned revision picks up its single reference, and the
    product's version has moved once per accepted decision and not at all for the refusal.

    PRD 3.5: "Alongside the four hops, the join recomputes `completeness_score_certified`, `completeness_score_declared` and `readiness_score` on each touched listing, recomputes the newly pinned revision's `pin_count` upward, recomputes the product's `shelf_health_index`, and — like every review decision — stamps `last_review_at` and increments the product's `version`."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_product_version_on_the_second_review_track_returns_412
    """
    world = simplemart_world_unpinned
    base_version = read_product_version(world["product"]["id"])
    _approve_legal(world, base_version)
    _decide(
        world["change_request"]["id"], "BRAND", make_brand_approver_headers(), base_version
    )
    validate_success(
        _decide(
            world["change_request"]["id"],
            "BRAND",
            make_brand_approver_headers(),
            read_product_version(world["product"]["id"]),
        )
    )

    listing = _listing(world["listing"]["id"])
    assert float(listing["completeness_score_certified"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["completeness_score_declared"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)

    assert_pin_ledger(_revision(world["revision"]["id"]), 1)
    assert read_product_version(world["product"]["id"]) == base_version + 2


def test_the_first_placement_advances_the_listing_version(simplemart_world):
    """Creating a deployment is a write on the listing itself, so the placement calendar the
    next writer must have seen has already moved.

    PRD 3.8: "Either way the listing's `version` increments by 1, and the `pin_count` of the revision named by the change request's `target_content_version_id` is recomputed upward, because an active deployment is a second kind of live reference to a revision."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_retailer_listing_version_on_the_second_deployment_returns_412
    """
    world = simplemart_world
    version_before = read_listing_version(world["listing"]["id"])

    first = get_success_data(
        _deploy(world, "A_PLUS_PAGE", FIRST_DEPLOYMENT_WINDOW, version_before)
    )
    assert first["state"] == "PENDING_RETAILER_APPROVAL"

    assert read_listing_version(world["listing"]["id"]) == version_before + 1


def test_the_second_placement_on_a_disjoint_window_is_refused_for_staleness(simplemart_world):
    """The [08-14, 08-15) window does not come near [08-12, 08-13), so the interval test has
    no complaint at all — the only thing wrong is the listing version the writer carried, and
    no second row is created.

    PRD 3.8: "Finally `expected_retailer_listing_version` must equal the listing's current `version`, or the creation fails with `ERR_STALE_VERSION`."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_retailer_listing_version_on_the_second_deployment_returns_412
    """
    world = simplemart_world
    stale_version = read_listing_version(world["listing"]["id"])
    first = get_success_data(
        _deploy(world, "A_PLUS_PAGE", FIRST_DEPLOYMENT_WINDOW, stale_version)
    )

    response = _deploy(world, "COMPARISON_CHART", SECOND_DEPLOYMENT_WINDOW, stale_version)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    rows, meta = _deployments(world)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_the_retry_with_the_fresh_listing_version_is_accepted(simplemart_world):
    """Two non-intersecting windows were always allowed to coexist; once the writer re-reads
    the listing the identical request lands, and the calendar carries both placements.

    PRD 2.6: "Two deployments on non-intersecting windows are both legal, so nothing in the window arithmetic rejects the second writer; the stale version is what reveals that the writer did not see the placement calendar as it now stands."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_retailer_listing_version_on_the_second_deployment_returns_412
    """
    world = simplemart_world
    stale_version = read_listing_version(world["listing"]["id"])
    _deploy(world, "A_PLUS_PAGE", FIRST_DEPLOYMENT_WINDOW, stale_version)
    _deploy(world, "COMPARISON_CHART", SECOND_DEPLOYMENT_WINDOW, stale_version)

    fresh_version = read_listing_version(world["listing"]["id"])
    second = get_success_data(
        _deploy(world, "COMPARISON_CHART", SECOND_DEPLOYMENT_WINDOW, fresh_version)
    )
    assert second["module_kind"] == "COMPARISON_CHART"
    assert read_listing_version(world["listing"]["id"]) == fresh_version + 1

    _rows, meta = _deployments(
        world,
        params={
            "retailer_listing_id": world["listing"]["id"],
            "state": "PENDING_RETAILER_APPROVAL",
        },
    )
    assert meta["total_count"] == 2


def test_the_two_accepted_placements_are_the_only_new_pin_references(simplemart_world):
    """The revision now holds three references — the listing pin plus one per pending
    placement — and the refused attempt contributed none.

    PRD 2.9: "`ContentVersion.pin_count` is the number of references currently held on a revision, and it counts two different kinds of reference: the number of retailer listings whose `pinned_content_version_id` equals the revision's `id`, plus the number of enhanced-content deployments in state `PENDING_RETAILER_APPROVAL` or `LIVE` whose governing change request's `target_content_version_id` equals that same `id`."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_retailer_listing_version_on_the_second_deployment_returns_412
    """
    world = simplemart_world
    stale_version = read_listing_version(world["listing"]["id"])
    _deploy(world, "A_PLUS_PAGE", FIRST_DEPLOYMENT_WINDOW, stale_version)
    _deploy(world, "COMPARISON_CHART", SECOND_DEPLOYMENT_WINDOW, stale_version)
    _deploy(
        world,
        "COMPARISON_CHART",
        SECOND_DEPLOYMENT_WINDOW,
        read_listing_version(world["listing"]["id"]),
    )

    assert_pin_ledger(_revision(world["revision"]["id"]), 3)


def test_neither_pending_placement_earns_the_readiness_bonus(simplemart_world):
    """Two placements are booked and both are still waiting on the retailer, so readiness sits
    exactly where the pin left it.

    PRD 3.8: "A deployment sitting in `PENDING_RETAILER_APPROVAL` earns nothing — waiting for approval is not the same as being published."
    Design: Corner/cross_cutting_complexity_layers/stale_expected_retailer_listing_version_on_the_second_deployment_returns_412
    """
    world = simplemart_world
    stale_version = read_listing_version(world["listing"]["id"])
    _deploy(world, "A_PLUS_PAGE", FIRST_DEPLOYMENT_WINDOW, stale_version)
    _deploy(world, "COMPARISON_CHART", SECOND_DEPLOYMENT_WINDOW, stale_version)
    _deploy(
        world,
        "COMPARISON_CHART",
        SECOND_DEPLOYMENT_WINDOW,
        read_listing_version(world["listing"]["id"]),
    )

    assert float(_listing(world["listing"]["id"])["readiness_score"]) == pytest.approx(
        60.00, abs=0.01
    )


def _queue(world, slot_count, window, expected_retailer_version):
    return api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            slot_count,
            window[0],
            window[1],
            expected_retailer_version,
        ),
        make_syndication_operator_headers(),
    )


def _queued_then_cancelled(world):
    """Four slots queued, transmitted and then cancelled — three feed writes of which only
    two moved the shared slot pool. Returns the version the operator first read."""
    opening_version = read_retailer_version(world["retailer"]["id"])
    job = get_success_data(_queue(world, 4, FIRST_FEED_WINDOW, opening_version))
    transmit_job(job["id"])
    validate_success(
        api_client.cancel_syndication_job(job["id"], {}, make_syndication_operator_headers())
    )
    return opening_version, job


def test_queueing_reserves_the_slots_and_advances_the_retailer(bigbox_world):
    """The queue is the write that moves the shared pool, so it is also the write that moves
    the version the next queue will have to quote.

    PRD 3.6: "On success, the retailer's `feed_slots_reserved` grows by the job's `slot_count` and the retailer's `version` increments by 1."
    Design: Corner/cross_cutting_complexity_layers/retailer_version_advances_only_on_accepted_feed_writes
    """
    world = bigbox_world
    opening_version = read_retailer_version(world["retailer"]["id"])
    assert opening_version == 1

    get_success_data(_queue(world, 4, FIRST_FEED_WINDOW, opening_version))

    retailer = _retailer(world["retailer"]["id"])
    assert_slot_ledger(retailer, 4)
    assert retailer["version"] == 2


def test_transmission_moves_no_capacity_and_so_no_version(bigbox_world):
    """Handing the payload to the retailer changes nothing about the reservation, so the
    version stays exactly where the queue left it.

    PRD 3.6: "Slots stay reserved, because `TRANSMITTED` is still a holding state of the slot ledger."
    Design: Corner/cross_cutting_complexity_layers/retailer_version_advances_only_on_accepted_feed_writes
    """
    world = bigbox_world
    job = get_success_data(
        _queue(world, 4, FIRST_FEED_WINDOW, read_retailer_version(world["retailer"]["id"]))
    )
    transmit_job(job["id"])

    retailer = _retailer(world["retailer"]["id"])
    assert_slot_ledger(retailer, 4)
    assert retailer["version"] == 2


def test_cancellation_releases_the_reservation_and_advances_the_retailer_again(bigbox_world):
    """Cancellation gives the whole reservation back, and because that is another move of the
    shared pool it costs another version.

    PRD 3.6: "Cancellation releases the whole reservation: the retailer's `feed_slots_reserved` is recomputed from the ledger, dropping the job's `slot_count`, and the retailer's `version` increments by 1."
    Design: Corner/cross_cutting_complexity_layers/retailer_version_advances_only_on_accepted_feed_writes
    """
    world = bigbox_world
    _opening_version, job = _queued_then_cancelled(world)

    assert validate_success(
        api_client.get_syndication_job(job["id"], make_syndication_operator_headers())
    )["state"] == "CANCELLED"

    retailer = _retailer(world["retailer"]["id"])
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 3


def test_a_second_queue_quoting_the_opening_version_is_refused(bigbox_world):
    """Two slots against a pool holding none would pass the capacity guard, and the listing's
    certified score would pass the completeness gate — the stale retailer version is the only
    thing that refuses it, and no job row appears.

    PRD 2.6: "Queueing a syndication job must carry `expected_retailer_version` matching the current `version` of the retailer that owns the target listing."
    Design: Corner/cross_cutting_complexity_layers/retailer_version_advances_only_on_accepted_feed_writes
    """
    world = bigbox_world
    opening_version, job = _queued_then_cancelled(world)

    response = _queue(world, 2, SECOND_FEED_WINDOW, opening_version)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    rows, meta = validate_paginated(
        api_client.list_syndication_jobs(
            make_syndication_operator_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == job["id"]
    assert read_retailer_version(world["retailer"]["id"]) == 3


def test_the_retry_with_the_re_read_retailer_version_reserves_two_slots(bigbox_world):
    """Re-reading the retailer is all the second queue ever needed: the identical request now
    lands, reserving two slots and advancing the version a fourth time.

    PRD 2.6: "Feed slots are a shared pool, so an earlier queue, cancel or invalidation cascade may already have moved `feed_slots_reserved` since the client last read the retailer; a second queue attempt would otherwise be perfectly legal and capacity might well admit it, which is exactly why the stale-version check is the only thing that distinguishes it."
    Design: Corner/cross_cutting_complexity_layers/retailer_version_advances_only_on_accepted_feed_writes
    """
    world = bigbox_world
    opening_version, _job = _queued_then_cancelled(world)
    _queue(world, 2, SECOND_FEED_WINDOW, opening_version)

    get_success_data(
        _queue(world, 2, SECOND_FEED_WINDOW, read_retailer_version(world["retailer"]["id"]))
    )

    retailer = _retailer(world["retailer"]["id"])
    assert_slot_ledger(retailer, 2)
    assert retailer["version"] == 4


def test_the_accepted_retry_is_a_first_attempt_that_puts_the_listing_pending(bigbox_world):
    """The retry is a brand-new job, not a continuation of the cancelled one: attempt one,
    neither stamp set, and the listing back in the pending state behind it.

    PRD 3.6: "The new job begins in `state` `QUEUED` with `attempt_no` 1, `transmitted_at` and `responded_at` both null, and it drives the target listing's `syndication_state` from `NOT_SYNDICATED` to `PENDING`."
    Design: Corner/cross_cutting_complexity_layers/retailer_version_advances_only_on_accepted_feed_writes
    """
    world = bigbox_world
    opening_version, _job = _queued_then_cancelled(world)
    _queue(world, 2, SECOND_FEED_WINDOW, opening_version)

    retry = get_success_data(
        _queue(world, 2, SECOND_FEED_WINDOW, read_retailer_version(world["retailer"]["id"]))
    )
    assert retry["state"] == "QUEUED"
    assert retry["attempt_no"] == 1
    assert retry["transmitted_at"] is None
    assert retry["responded_at"] is None

    assert _listing(world["listing"]["id"])["syndication_state"] == "PENDING"


def test_the_accepted_retry_freezes_the_readiness_it_found(bigbox_world):
    """The score frozen onto the job is the listing's readiness at that moment — unchanged by
    the queue, transmit, cancel and refusal that came before it.

    PRD 3.6: "Two figures are frozen onto the job at this moment: `readiness_at_queue` captures the listing's readiness score as it stands, and `service_fee_cents` captures the feed fee computed below."
    Design: Corner/cross_cutting_complexity_layers/retailer_version_advances_only_on_accepted_feed_writes
    """
    world = bigbox_world
    opening_version, _job = _queued_then_cancelled(world)
    _queue(world, 2, SECOND_FEED_WINDOW, opening_version)

    retry = get_success_data(
        _queue(world, 2, SECOND_FEED_WINDOW, read_retailer_version(world["retailer"]["id"]))
    )
    assert float(retry["readiness_at_queue"]) == pytest.approx(51.00, abs=0.01)
    assert float(_listing(world["listing"]["id"])["readiness_score"]) == pytest.approx(
        51.00, abs=0.01
    )
