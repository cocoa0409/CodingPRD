"""Non-linear lifecycles: the review fork with its self-loop and join, and the
rejected job that cycles back to QUEUED as a second attempt."""
import pytest

from prd_bench_local_runner.testing import get_success_data, is_iso8601_timestamp, validate_success

from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_change_request,
    assert_content_version,
    assert_retailer_listing,
    assert_slot_ledger,
    assert_syndication_job,
)
from test_helpers.fixtures import (
    queue_job,
    reject_job,
    rejection_errors_of,
    resolve_rejection,
    review_brand,
    review_legal,
    transmit_job,
)
from test_helpers.test_users import (
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

DESCRIPTION_REJECTION = [
    {
        "retailer_error_code": "DESC_LEN",
        "attribute_key": "description",
        "severity": "BLOCKING",
        "message": "description rejected by the retailer feed",
    }
]


def _rejected_bigbox_job(world):
    """Queue six slots into a far window, transmit, and have BigBox reject the
    payload with a single BLOCKING complaint."""
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        6,
        "2026-08-20T00:00:00Z",
        "2026-08-21T00:00:00Z",
        world["retailer"]["id"],
    )
    transmit_job(job["id"])
    reject_job(job["id"], world["retailer"]["id"], DESCRIPTION_REJECTION)
    return job


def test_the_first_track_approval_leaves_the_request_in_review(simplemart_world_unpinned):
    """LegalReviewer approving while the brand track is untouched re-enters
    IN_REVIEW: only the legal dimension moves, and decided_at stays null because
    nothing has been decided yet.

    PRD 3.5: "When the decision is `APPROVED` and the other track is still `PENDING`, the request's aggregate `state` stays `IN_REVIEW`."
    Design: Difficulty/non_linear_state_machine/change_request_fork_join_self_loop_then_join_pin
    """
    world = simplemart_world_unpinned
    change_request = review_legal(
        world["change_request"]["id"], world["product"]["id"], "APPROVED"
    )
    assert_change_request(change_request)
    assert change_request["state"] == "IN_REVIEW"
    assert change_request["legal_review_state"] == "APPROVED"
    assert change_request["brand_review_state"] == "PENDING"
    assert change_request["decided_at"] is None


def test_the_self_loop_pins_nothing_and_writes_no_listing_or_product(simplemart_world_unpinned):
    """After the legal approval the revision is still IN_REVIEW with pin_count 0,
    the listing has no pinned revision and 0.00 completeness, and the product is
    still DRAFT with a null last_pinned_at.

    PRD 3.5: "Nothing is pinned, nothing is superseded, no job is invalidated, and no revision's `pin_count` changes."
    Design: Difficulty/non_linear_state_machine/change_request_fork_join_self_loop_then_join_pin
    """
    world = simplemart_world_unpinned
    review_legal(world["change_request"]["id"], world["product"]["id"], "APPROVED")

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert_content_version(revision)
    assert revision["state"] == "IN_REVIEW"
    assert revision["pin_count"] == 0

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert listing["pinned_content_version_id"] is None
    assert float(listing["completeness_score_certified"]) == pytest.approx(0.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["last_pinned_at"] is None
    assert product["status"] == "DRAFT"


def test_the_second_track_approval_is_the_join_that_advances_the_request(
    simplemart_world_unpinned,
):
    """With legal already APPROVED, the brand approval leaves both dimensions
    APPROVED, so the aggregate state advances out of IN_REVIEW and decided_at is
    stamped from the logical clock standing at 2026-08-10T00:00:00Z.

    PRD 3.5: "When a decision is `APPROVED` and, after applying it, both `legal_review_state` and `brand_review_state` are `APPROVED`, the request advances `IN_REVIEW → APPROVED` — a terminal state — and a four-hop cascade fires inside the same request."
    Design: Difficulty/non_linear_state_machine/change_request_fork_join_self_loop_then_join_pin
    """
    world = simplemart_world_unpinned
    review_legal(world["change_request"]["id"], world["product"]["id"], "APPROVED")
    joined = review_brand(world["change_request"]["id"], world["product"]["id"], "APPROVED")

    assert joined["state"] == "APPROVED"
    assert joined["legal_review_state"] == "APPROVED"
    assert joined["brand_review_state"] == "APPROVED"
    assert is_iso8601_timestamp(joined["decided_at"])
    assert joined["decided_at"].startswith("2026-08-10T00:00:00")


def test_the_join_pins_the_revision_and_repoints_the_listing(simplemart_world_unpinned):
    """Hop 1 of the join moves the revision to PINNED with pin_count 1, repoints the
    listing at it with certified and declared both 100.00 and readiness 60.00, and
    promotes the product to ACTIVE.

    PRD 3.5: "The target revision transitions `IN_REVIEW → PINNED`. The listing joining the request's product and retailer has its `pinned_content_version_id` repointed to that revision. The product's `last_pinned_at` is stamped from the logical clock and its `status` becomes `ACTIVE`."
    Design: Difficulty/non_linear_state_machine/change_request_fork_join_self_loop_then_join_pin
    """
    world = simplemart_world_unpinned
    review_legal(world["change_request"]["id"], world["product"]["id"], "APPROVED")
    review_brand(world["change_request"]["id"], world["product"]["id"], "APPROVED")

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["state"] == "PINNED"
    assert revision["pin_count"] == 1

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert_retailer_listing(listing)
    assert listing["pinned_content_version_id"] == world["revision"]["id"]
    assert float(listing["completeness_score_certified"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["completeness_score_declared"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["status"] == "ACTIVE"
    assert product["last_pinned_at"].startswith("2026-08-10T00:00:00")
    assert product["last_review_at"].startswith("2026-08-10T00:00:00")


def test_fixing_the_last_blocking_row_lifts_the_error_hold(bigbox_world):
    """Resolving the single BLOCKING complaint with FIX takes
    open_blocking_error_count to zero, and because no job of the listing is holding
    slots the listing falls back to NOT_SYNDICATED at an unpenalised 51.00.

    PRD 3.7: "When the closing call takes `open_blocking_error_count` to zero and no job of the listing is in `QUEUED` or `TRANSMITTED`, the listing's `syndication_state` moves `ERROR_HOLD → NOT_SYNDICATED` and its readiness is recomputed with no penalty at all, which in turn changes whether the listing qualifies for the product's health input set."
    Design: Difficulty/non_linear_state_machine/syndication_job_cycles_rejected_back_to_queued_as_attempt_two
    """
    job = _rejected_bigbox_job(bigbox_world)
    rows = rejection_errors_of(job["id"])
    assert len(rows) == 1

    resolved = resolve_rejection(
        rows[0]["id"], "FIX", "description shortened for the retailer ceiling"
    )
    assert resolved["state"] == "RESOLVED"
    assert resolved["resolution_mode"] == "FIX"

    listing = get_success_data(
        api_client.get_retailer_listing(
            bigbox_world["listing"]["id"], make_syndication_operator_headers()
        )
    )
    assert listing["syndication_state"] == "NOT_SYNDICATED"
    assert listing["open_blocking_error_count"] == 0
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)


def test_a_requeued_job_returns_to_queued_as_attempt_two_with_a_fresh_fee(bigbox_world):
    """The same job cycles back out of REJECTED: attempt_no becomes 2, both stamps
    are cleared, and the fee is recomputed at the requeue clock — the six-hour
    window now carries the 20 percent rush surcharge, giving 16200 rather than the
    13500 frozen at attempt 1.

    PRD 3.7: "A successful requeue moves the job back to `QUEUED`, increments `attempt_no` by 1, resets `transmitted_at` and `responded_at` to null, and re-reserves the slots so the retailer's `feed_slots_reserved` is recomputed upward and its `version` increments by 1."
    Design: Difficulty/non_linear_state_machine/syndication_job_cycles_rejected_back_to_queued_as_attempt_two
    """
    job = _rejected_bigbox_job(bigbox_world)
    assert job["service_fee_cents"] == 13500
    rows = rejection_errors_of(job["id"])
    resolve_rejection(rows[0]["id"], "FIX", "description shortened for the retailer ceiling")

    retailer = get_success_data(
        api_client.get_retailer(
            bigbox_world["retailer"]["id"], make_syndication_operator_headers()
        )
    )
    assert retailer["version"] == 3

    requeued = get_success_data(
        api_client.requeue_syndication_job(
            job["id"],
            {
                "slot_count": 6,
                "window_start": "2026-08-10T06:00:00Z",
                "window_end": "2026-08-11T06:00:00Z",
                "expected_retailer_version": retailer["version"],
            },
            make_syndication_operator_headers(),
        )
    )
    assert_syndication_job(requeued)
    assert requeued["state"] == "QUEUED"
    assert requeued["attempt_no"] == 2
    assert requeued["service_fee_cents"] == 16200
    assert requeued["service_fee_cents"] != 13500
    assert requeued["transmitted_at"] is None
    assert requeued["responded_at"] is None


def test_the_requeue_re_reserves_the_slots_and_refreezes_readiness(bigbox_world):
    """The requeue re-reserves all six slots, taking the retailer from version 3 to
    version 4, and recaptures the listing's readiness as it now stands while driving
    the listing back to PENDING.

    PRD 3.7: "Both frozen figures are re-frozen at the current clock position: `readiness_at_queue` recaptures the listing's readiness as it now stands, and `service_fee_cents` is recomputed from scratch — which is how a requeue into a window less than 24 hours away picks up a rush surcharge the original attempt never paid."
    Design: Difficulty/non_linear_state_machine/syndication_job_cycles_rejected_back_to_queued_as_attempt_two
    """
    job = _rejected_bigbox_job(bigbox_world)
    rows = rejection_errors_of(job["id"])
    resolve_rejection(rows[0]["id"], "FIX", "description shortened for the retailer ceiling")

    retailer = get_success_data(
        api_client.get_retailer(
            bigbox_world["retailer"]["id"], make_syndication_operator_headers()
        )
    )
    requeued = get_success_data(
        api_client.requeue_syndication_job(
            job["id"],
            {
                "slot_count": 6,
                "window_start": "2026-08-10T06:00:00Z",
                "window_end": "2026-08-11T06:00:00Z",
                "expected_retailer_version": retailer["version"],
            },
            make_syndication_operator_headers(),
        )
    )
    assert float(requeued["readiness_at_queue"]) == pytest.approx(51.00, abs=0.01)

    retailer_after = get_success_data(
        api_client.get_retailer(
            bigbox_world["retailer"]["id"], make_syndication_operator_headers()
        )
    )
    assert_slot_ledger(retailer_after, 6)
    assert retailer_after["version"] == 4

    listing = get_success_data(
        api_client.get_retailer_listing(
            bigbox_world["listing"]["id"], make_syndication_operator_headers()
        )
    )
    assert listing["syndication_state"] == "PENDING"
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)
