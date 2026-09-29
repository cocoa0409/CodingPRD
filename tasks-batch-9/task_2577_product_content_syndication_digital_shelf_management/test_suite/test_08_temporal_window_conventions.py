"""Two calendars, two opposite interval conventions: the half-open placement
calendar accepts touching windows, the closed feed calendar refuses them."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_enhanced_deployment,
    assert_pin_ledger,
    assert_slot_ledger,
    assert_syndication_job,
)
from test_helpers.factories import create_deployment_payload, create_syndication_job_payload
from test_helpers.fixtures import (
    deploy_enhanced_module,
    read_listing_version,
    read_retailer_version,
)
from test_helpers.test_users import (
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)


def _two_back_to_back_modules(world):
    """[2026-08-20, 2026-08-22) followed by [2026-08-22, 2026-08-24) on the same
    listing, both riding the approved change request and the approved hero asset."""
    first = deploy_enhanced_module(
        world["listing"]["id"],
        world["change_request"]["id"],
        world["asset"]["id"],
        "A_PLUS_PAGE",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )
    second = deploy_enhanced_module(
        world["listing"]["id"],
        world["change_request"]["id"],
        world["asset"]["id"],
        "COMPARISON_CHART",
        "2026-08-22T00:00:00Z",
        "2026-08-24T00:00:00Z",
    )
    return first, second


def test_a_placement_starting_where_the_previous_one_ends_is_accepted(simplemart_world):
    """The second module opens at the exact instant the first closes, and because
    both intervals are half-open the calendar treats them as disjoint: both sit in
    PENDING_RETAILER_APPROVAL with no overlap complaint.

    PRD 3.8: "Because both intervals are half-open, two windows that merely touch — where an existing deployment's `window_end` equals the new `window_start` — do **not** intersect and are allowed, so a listing can carry back-to-back placements with no gap."
    Design: Difficulty/resource_temporal_overlap/deployment_windows_touch_at_a_shared_endpoint_without_overlapping
    """
    first, second = _two_back_to_back_modules(simplemart_world)

    assert_enhanced_deployment(first)
    assert_enhanced_deployment(second)
    assert first["state"] == "PENDING_RETAILER_APPROVAL"
    assert second["state"] == "PENDING_RETAILER_APPROVAL"
    assert first["window_end"].startswith("2026-08-22T00:00:00")
    assert second["window_start"].startswith("2026-08-22T00:00:00")


def test_a_placement_straddling_both_accepted_windows_is_refused(simplemart_world):
    """A third window running 2026-08-21 to 2026-08-23 strictly cuts into both
    accepted placements, so the pairwise interval test refuses it and the listing's
    calendar still holds exactly the two modules.

    PRD 3.8: "A genuine overlap is rejected with `ERR_DEPLOYMENT_WINDOW_OVERLAP`."
    Design: Difficulty/resource_temporal_overlap/deployment_windows_touch_at_a_shared_endpoint_without_overlapping
    """
    world = simplemart_world
    _two_back_to_back_modules(world)
    listing_version = read_listing_version(world["listing"]["id"])

    response = api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            world["asset"]["id"],
            "VIDEO_BLOCK",
            "2026-08-21T00:00:00Z",
            "2026-08-23T00:00:00Z",
            listing_version,
        ),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DEPLOYMENT_WINDOW_OVERLAP.value, 409)

    _rows, meta = validate_paginated(
        api_client.list_enhanced_deployments(
            make_content_author_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 2

    listing = get_success_data(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["version"] == listing_version, (
        "the refused creation is a no-op, so it never incremented the listing version"
    )
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01), (
        "neither accepted placement is LIVE, so no enhanced-content bonus is in the blend"
    )


def test_the_two_accepted_placements_add_two_pin_references(simplemart_world):
    """The revision carries three live references: the listing pin from the change
    request join plus one for each pending placement. The refused window added
    nothing.

    PRD 3.8: "Either way the listing's `version` increments by 1, and the `pin_count` of the revision named by the change request's `target_content_version_id` is recomputed upward, because an active deployment is a second kind of live reference to a revision."
    Design: Difficulty/resource_temporal_overlap/deployment_windows_touch_at_a_shared_endpoint_without_overlapping
    """
    world = simplemart_world
    _two_back_to_back_modules(world)
    api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            world["asset"]["id"],
            "VIDEO_BLOCK",
            "2026-08-21T00:00:00Z",
            "2026-08-23T00:00:00Z",
            read_listing_version(world["listing"]["id"]),
        ),
        make_content_author_headers(),
    )

    revision = get_success_data(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert_pin_ledger(revision, 3)


def test_a_feed_window_beginning_where_the_first_one_ends_is_a_conflict(
    bigbox_world_single_window,
):
    """With an allowance of one concurrent window, a second job starting at the exact
    instant the first job's window ends is refused: the feed comparison counts both
    endpoints, so the touching windows intersect.

    PRD 3.6: "The **concurrent-window** guard counts the retailer's jobs — across all of its listings, not just this one — that are in `QUEUED` or `TRANSMITTED` and whose window intersects the requested window, and requires that count to be strictly fewer than the retailer's `max_concurrent_feed_windows`; exceeding it is `ERR_FEED_WINDOW_CONFLICT`."
    Design: Difficulty/resource_temporal_overlap/feed_windows_touching_at_an_endpoint_do_count_as_a_conflict
    """
    world = bigbox_world_single_window
    first = get_success_data(
        api_client.create_syndication_job(
            create_syndication_job_payload(
                world["listing"]["id"],
                world["revision"]["id"],
                1,
                "2026-08-20T00:00:00Z",
                "2026-08-21T00:00:00Z",
                read_retailer_version(world["retailer"]["id"]),
            ),
            make_syndication_operator_headers(),
        )
    )
    assert_syndication_job(first)
    assert first["state"] == "QUEUED"

    retailer_version = read_retailer_version(world["retailer"]["id"])
    assert retailer_version == 2

    touching = api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            1,
            "2026-08-21T00:00:00Z",
            "2026-08-22T00:00:00Z",
            retailer_version,
        ),
        make_syndication_operator_headers(),
    )
    validate_error(touching, ApiErrorId.ERR_FEED_WINDOW_CONFLICT.value, 409)


def test_shifting_the_feed_window_one_second_later_clears_the_conflict(
    bigbox_world_single_window,
):
    """Moving the same request's start from 2026-08-21T00:00:00Z to
    2026-08-21T00:00:01Z leaves the closed windows disjoint, so the allowance of one
    is respected and the second job queues.

    PRD 3.6: "This comparison treats both windows as **closed intervals**, including both endpoints, so a new window that begins at the exact instant an existing window ends **does** count as intersecting."
    Design: Difficulty/resource_temporal_overlap/feed_windows_touching_at_an_endpoint_do_count_as_a_conflict
    """
    world = bigbox_world_single_window
    get_success_data(
        api_client.create_syndication_job(
            create_syndication_job_payload(
                world["listing"]["id"],
                world["revision"]["id"],
                1,
                "2026-08-20T00:00:00Z",
                "2026-08-21T00:00:00Z",
                read_retailer_version(world["retailer"]["id"]),
            ),
            make_syndication_operator_headers(),
        )
    )
    retailer_version = read_retailer_version(world["retailer"]["id"])
    api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            1,
            "2026-08-21T00:00:00Z",
            "2026-08-22T00:00:00Z",
            retailer_version,
        ),
        make_syndication_operator_headers(),
    )

    later = get_success_data(
        api_client.create_syndication_job(
            create_syndication_job_payload(
                world["listing"]["id"],
                world["revision"]["id"],
                1,
                "2026-08-21T00:00:01Z",
                "2026-08-22T00:00:00Z",
                retailer_version,
            ),
            make_syndication_operator_headers(),
        )
    )
    assert later["state"] == "QUEUED"
    assert later["window_start"].startswith("2026-08-21T00:00:01")


def test_only_the_two_accepted_queues_moved_the_slot_ledger(bigbox_world_single_window):
    """Two single-slot jobs are holding, so the ledger reads 2 and the retailer has
    advanced exactly twice; the refused touching window left neither a reservation
    nor a job row, and the listing is PENDING behind its live queue.

    PRD 3.6: "On success, the retailer's `feed_slots_reserved` grows by the job's `slot_count` and the retailer's `version` increments by 1."
    Design: Difficulty/resource_temporal_overlap/feed_windows_touching_at_an_endpoint_do_count_as_a_conflict
    """
    world = bigbox_world_single_window
    get_success_data(
        api_client.create_syndication_job(
            create_syndication_job_payload(
                world["listing"]["id"],
                world["revision"]["id"],
                1,
                "2026-08-20T00:00:00Z",
                "2026-08-21T00:00:00Z",
                read_retailer_version(world["retailer"]["id"]),
            ),
            make_syndication_operator_headers(),
        )
    )
    retailer_version = read_retailer_version(world["retailer"]["id"])
    api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            1,
            "2026-08-21T00:00:00Z",
            "2026-08-22T00:00:00Z",
            retailer_version,
        ),
        make_syndication_operator_headers(),
    )
    get_success_data(
        api_client.create_syndication_job(
            create_syndication_job_payload(
                world["listing"]["id"],
                world["revision"]["id"],
                1,
                "2026-08-21T00:00:01Z",
                "2026-08-22T00:00:00Z",
                retailer_version,
            ),
            make_syndication_operator_headers(),
        )
    )

    retailer = get_success_data(
        api_client.get_retailer(world["retailer"]["id"], make_syndication_operator_headers())
    )
    assert_slot_ledger(retailer, 2)
    assert retailer["version"] == 3

    _jobs, meta = validate_paginated(
        api_client.list_syndication_jobs(
            make_syndication_operator_headers(),
            params={"retailer_listing_id": world["listing"]["id"], "state": "QUEUED"},
        )
    )
    assert meta["total_count"] == 2

    listing = get_success_data(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["syndication_state"] == "PENDING"
