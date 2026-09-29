"""Compensating actions have to return the derived ledgers to precisely their
pre-action values, not merely decrement a stored counter."""
import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_enhanced_deployment,
    assert_pin_ledger,
    assert_slot_ledger,
)
from test_helpers.fixtures import (
    deploy_enhanced_module,
    queue_job,
    read_retailer_version,
    withdraw_deployment,
)
from test_helpers.test_users import (
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

WITHDRAWN_REASON = "module pulled at the brand's request"


def _queue_six_then_cancel(world):
    """Reserve six of BigBox's ten slots, then cancel the job that holds them."""
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        6,
        "2026-08-20T00:00:00Z",
        "2026-08-21T00:00:00Z",
        world["retailer"]["id"],
    )
    after_queue = get_success_data(
        api_client.get_retailer(world["retailer"]["id"], make_syndication_operator_headers())
    )
    cancelled = get_success_data(
        api_client.cancel_syndication_job(job["id"], {}, make_syndication_operator_headers())
    )
    return job, after_queue, cancelled


def _live_video_module(world):
    return deploy_enhanced_module(
        world["listing"]["id"],
        world["change_request"]["id"],
        world["asset"]["id"],
        "VIDEO_BLOCK",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )


def test_cancelling_a_queued_job_returns_the_slot_ledger_to_zero(bigbox_world):
    """Six slots go out and come straight back: the ledger reads 6 while the job
    holds them and 0 once it is cancelled, and the retailer's version advances on
    both writes rather than being rolled back with the reservation.

    PRD 3.6: "Cancellation releases the whole reservation: the retailer's `feed_slots_reserved` is recomputed from the ledger, dropping the job's `slot_count`, and the retailer's `version` increments by 1."
    Design: Difficulty/compensating_invariant/feed_slot_ledger_returns_to_zero_after_cancel_and_frees_full_capacity
    """
    world = bigbox_world
    _job, after_queue, cancelled = _queue_six_then_cancel(world)

    assert_slot_ledger(after_queue, 6)
    assert after_queue["version"] == 2
    assert cancelled["state"] == "CANCELLED"

    after_cancel = get_success_data(
        api_client.get_retailer(world["retailer"]["id"], make_syndication_operator_headers())
    )
    assert_slot_ledger(after_cancel, 0)
    assert after_cancel["version"] == 3


def test_the_freed_capacity_takes_a_queue_for_every_slot_the_retailer_owns(bigbox_world):
    """The proof that nothing leaked is a ten-slot queue against a capacity of ten:
    a single stranded slot would have made the sum exceed capacity and refused the
    request, and afterwards the ledger stands at a full ten.

    PRD 3.6: "The **slot capacity** guard requires that the retailer's current `feed_slots_reserved` plus the requested `slot_count` is at most `feed_slot_capacity`; landing exactly on capacity is allowed, and exceeding it is `ERR_FEED_CAPACITY_EXCEEDED`."
    Design: Difficulty/compensating_invariant/feed_slot_ledger_returns_to_zero_after_cancel_and_frees_full_capacity
    """
    world = bigbox_world
    _queue_six_then_cancel(world)

    full_queue = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        10,
        "2026-08-25T00:00:00Z",
        "2026-08-26T00:00:00Z",
        expected_retailer_version=read_retailer_version(world["retailer"]["id"]),
    )
    assert full_queue["state"] == "QUEUED"

    retailer = get_success_data(
        api_client.get_retailer(world["retailer"]["id"], make_syndication_operator_headers())
    )
    assert_slot_ledger(retailer, 10)
    assert retailer["version"] == 4


def test_the_cancelled_job_keeps_its_slot_count_and_only_leaves_the_input_set(bigbox_world):
    """The released reservation is not a mutation of the job: the cancelled row still
    records the six slots it once held, it simply no longer contributes to the sum,
    while the listing is PENDING behind the fresh queue at an unpenalised 51.00.

    PRD 2.9: "`Retailer.feed_slots_reserved` is the sum of `slot_count` over every syndication job belonging to any listing of that retailer whose `state` is `QUEUED` or `TRANSMITTED`."
    Design: Difficulty/compensating_invariant/feed_slot_ledger_returns_to_zero_after_cancel_and_frees_full_capacity
    """
    world = bigbox_world
    job, _after_queue, _cancelled = _queue_six_then_cancel(world)
    queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        10,
        "2026-08-25T00:00:00Z",
        "2026-08-26T00:00:00Z",
        expected_retailer_version=read_retailer_version(world["retailer"]["id"]),
    )

    stored = get_success_data(
        api_client.get_syndication_job(job["id"], make_syndication_operator_headers())
    )
    assert stored["state"] == "CANCELLED"
    assert stored["slot_count"] == 6

    listing = get_success_data(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["syndication_state"] == "PENDING"
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)


def test_a_deployment_on_an_auto_live_retailer_adds_a_reference_and_the_bonus(
    simplemart_world_auto_live,
):
    """SimpleMart asks for no approval, so the module lands straight in LIVE: the
    pinned revision picks up a second live reference and the listing's readiness
    climbs from 60.00 to 65.00 on the flat five-point bonus.

    PRD 3.8: "That bonus is a flat **5 points** added to the readiness blend described in §3.4, and it is earned by the existence of at least one deployment of the listing in `LIVE`."
    Design: Difficulty/compensating_invariant/pin_reference_ledger_returns_after_a_live_deployment_is_withdrawn
    """
    world = simplemart_world_auto_live
    deployment = _live_video_module(world)

    assert_enhanced_deployment(deployment)
    assert deployment["state"] == "LIVE"

    revision = get_success_data(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert_pin_ledger(revision, 2)

    listing = get_success_data(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert float(listing["readiness_score"]) == pytest.approx(65.00, abs=0.01)


def test_withdrawing_the_live_module_reverses_both_the_pin_and_the_bonus(
    simplemart_world_auto_live,
):
    """Withdrawal is the author's compensating action and it undoes exactly what the
    creation did: the reason is recorded, the pin ledger returns to the single
    listing reference, and readiness falls back to 60.00.

    PRD 3.8: "The deployment moves to the terminal `WITHDRAWN`, the revision's `pin_count` is recomputed downward — returning the pin ledger to precisely its pre-creation value, which is the point of calling withdrawal a compensating action — the listing's `readiness_score` is recomputed with the bonus removed, the product's `shelf_health_index` is recomputed, and the listing's `version` increments by 1."
    Design: Difficulty/compensating_invariant/pin_reference_ledger_returns_after_a_live_deployment_is_withdrawn
    """
    world = simplemart_world_auto_live
    deployment = _live_video_module(world)
    withdrawn = withdraw_deployment(deployment["id"], WITHDRAWN_REASON)

    assert withdrawn["state"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason"] == WITHDRAWN_REASON

    revision = get_success_data(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert_pin_ledger(revision, 1)

    listing = get_success_data(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)


def test_the_withdrawn_row_keeps_its_window_but_leaves_the_health_input_set_alone(
    simplemart_world_auto_live,
):
    """The withdrawn deployment still carries the window it was booked for, and
    because the listing was never syndicated no deployment change can move the
    product's health index off 0.00.

    PRD 3.9: "The product's `shelf_health_index` aggregates only those of its listings whose `syndication_state` is `LIVE` or `ERROR_HOLD`; `NOT_SYNDICATED` and `PENDING` listings are excluded, and when no listing qualifies the index is 0.00 and the per-retailer breakdown is empty."
    Design: Difficulty/compensating_invariant/pin_reference_ledger_returns_after_a_live_deployment_is_withdrawn
    """
    world = simplemart_world_auto_live
    deployment = _live_video_module(world)
    withdraw_deployment(deployment["id"], WITHDRAWN_REASON)

    stored = get_success_data(
        api_client.get_enhanced_deployment(deployment["id"], make_content_author_headers())
    )
    assert stored["window_start"].startswith("2026-08-20T00:00:00")
    assert stored["window_end"].startswith("2026-08-22T00:00:00")

    product = get_success_data(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(0.00, abs=0.01)

    listing = get_success_data(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["syndication_state"] == "NOT_SYNDICATED"
