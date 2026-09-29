"""Every documented transition of the four lifecycles that own state in this
platform: the change request with its forked review, the syndication job with its
holding states, the enhanced deployment and the shelf alert.

The tests walk both the legal edges and the refused ones, and after every refusal
they re-read the neighbouring rows to show that a rejected transition wrote
nothing at all.
"""
import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_change_request,
    assert_content_version,
    assert_enhanced_deployment,
    assert_media_asset,
    assert_pin_ledger,
    assert_shelf_alert,
    assert_slot_ledger,
    assert_syndication_job,
)
from test_helpers.constants import AUTO_CLEARED_BY_ACCOUNT_TEAM
from test_helpers.factories import (
    create_attribute_value_payload,
    media_decision_payload,
    requeue_payload,
    resolve_alert_payload,
    resolve_rejection_error_payload,
    review_payload,
)
from test_helpers.fixtures import (
    BIGBOX_TITLE,
    accept_job,
    decide_deployment,
    deploy_enhanced_module,
    ingest_observation,
    move_clock,
    queue_job,
    read_product_version,
    read_retailer_version,
    reject_job,
    rejection_errors_of,
    transmit_job,
    upload_asset,
)
from test_helpers.test_users import (
    make_account_team_headers,
    make_brand_approver_headers,
    make_content_author_headers,
    make_legal_reviewer_headers,
    make_retailer_integration_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

SINGLE_BLOCKING_ROW = [
    {
        "retailer_error_code": "E-BRAND-MISSING",
        "attribute_key": "brand",
        "severity": "BLOCKING",
        "message": "brand attribute is required",
    }
]

THREE_BLOCKING_ROWS = [
    {
        "retailer_error_code": "E-BRAND-MISSING",
        "attribute_key": "brand",
        "severity": "BLOCKING",
        "message": "brand attribute is required",
    },
    {
        "retailer_error_code": "E-TITLE-CASE",
        "attribute_key": "title",
        "severity": "BLOCKING",
        "message": "title casing violates the style guide",
    },
    {
        "retailer_error_code": "E-DESC-LEN",
        "attribute_key": "description",
        "severity": "BLOCKING",
        "message": "description too short for this category",
    },
]


def _queue_four_slots(world, window_start="2026-08-15T00:00:00Z", window_end="2026-08-16T00:00:00Z"):
    return queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        4,
        window_start,
        window_end,
        world["retailer"]["id"],
    )


def _transmitted_four_slot_job(world):
    job = _queue_four_slots(world)
    transmit_job(job["id"])
    return job


def _unauthorized_crawl_of_a_live_listing(world):
    """Take the BigBox listing LIVE through an accepted job, then crawl it showing
    two unauthorized sellers."""
    job = _transmitted_four_slot_job(world)
    accept_job(job["id"], world["retailer"]["id"])
    return ingest_observation(
        world["listing"]["id"],
        "2026-08-12T00:00:00Z",
        in_stock=True,
        content_accuracy_pct=96.00,
        rating_avg=4.50,
        rating_count=120,
        unauthorized_seller_count=2,
        conversion_rate_pct=3.00,
        units_sold=40,
        search_rank=3,
    )


def _out_of_stock_crawl(world):
    return ingest_observation(
        world["listing"]["id"],
        "2026-08-11T00:00:00Z",
        in_stock=False,
        content_accuracy_pct=92.00,
        rating_avg=4.50,
        rating_count=60,
        unauthorized_seller_count=0,
        conversion_rate_pct=2.00,
        units_sold=8,
        search_rank=4,
    )


def _only_alert_of(listing_id):
    alerts, meta = validate_paginated(
        api_client.list_shelf_alerts(
            make_account_team_headers(), params={"retailer_listing_id": listing_id}
        )
    )
    assert meta["total_count"] == 1
    return alerts[0]


def _pending_a_plus_deployment(world):
    return deploy_enhanced_module(
        world["listing"]["id"],
        world["change_request"]["id"],
        world["asset"]["id"],
        "A_PLUS_PAGE",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )


def test_a_raised_change_request_and_its_target_revision_both_sit_in_draft(
    simplemart_world_draft_request,
):
    """Before submission the request is DRAFT with both tracks PENDING, no reviewer
    recorded on either, and the author's own identifier on the row; the target
    revision is still an editable DRAFT that nothing points at.

    PRD 3.5: "A newly raised request sits in `state` `DRAFT` with `legal_review_state` and `brand_review_state` both `PENDING`, `legal_reviewer_user_id` and `brand_reviewer_user_id` both null, `submitted_at` and `decided_at` both null, and `author_user_id` recorded from the calling `X-User-ID` — the value that will later bar this user from deciding either of its two tracks."
    Design: Corner/state_machines/change_request_and_target_revision_both_sit_in_draft_before_submit
    """
    world = simplemart_world_draft_request

    change_request = validate_success(
        api_client.get_change_request(
            world["change_request"]["id"], make_content_author_headers()
        )
    )
    assert_change_request(change_request)
    assert change_request["state"] == "DRAFT"
    assert change_request["submitted_at"] is None
    assert change_request["decided_at"] is None
    assert change_request["legal_review_state"] == "PENDING"
    assert change_request["brand_review_state"] == "PENDING"
    assert change_request["legal_reviewer_user_id"] is None
    assert change_request["brand_reviewer_user_id"] is None
    assert change_request["author_user_id"] == "author_1"

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert_content_version(revision)
    assert revision["state"] == "DRAFT"
    assert_pin_ledger(revision, 0)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert listing["pinned_content_version_id"] is None

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["status"] == "DRAFT"


def test_submission_forks_the_two_tracks_and_freezes_the_target_revision(
    simplemart_world_draft_request,
):
    """Submission stamps submitted_at from the logical clock, leaves both review
    dimensions PENDING so each can be decided independently, and drags the target
    revision into IN_REVIEW without pinning it — so the declared score already
    reads 100.00 while the certified score is still 0.00.

    PRD 3.5: "Submission moves the request `DRAFT → IN_REVIEW`, stamps `submitted_at` from the logical clock, and **forks** the review into two independently decidable dimensions by leaving both `legal_review_state` and `brand_review_state` at `PENDING`."
    Design: Corner/state_machines/submit_forks_both_tracks_and_freezes_the_target_revision
    """
    world = simplemart_world_draft_request

    submitted = validate_success(
        api_client.submit_change_request(
            world["change_request"]["id"], {}, make_content_author_headers("author_1")
        )
    )
    assert submitted["state"] == "IN_REVIEW"
    assert submitted["submitted_at"].startswith("2026-08-10T00:00:00")
    assert submitted["legal_review_state"] == "PENDING"
    assert submitted["brand_review_state"] == "PENDING"

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["state"] == "IN_REVIEW"
    assert_pin_ledger(revision, 0)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert listing["pinned_content_version_id"] is None
    assert float(listing["completeness_score_declared"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["completeness_score_certified"]) == pytest.approx(0.00, abs=0.01)

    assert read_product_version(world["product"]["id"]) == 1


def test_an_attribute_write_against_a_frozen_revision_is_refused(simplemart_world_unpinned):
    """The revision went into IN_REVIEW when the request was submitted, so the
    author can no longer overwrite the title: the write is refused and the stored
    row still carries its original value.

    PRD 3.2: "Writing against a revision in `IN_REVIEW`, `PINNED` or `SUPERSEDED` is rejected with `ERR_VERSION_NOT_DRAFT` — this is the content freeze that makes a review meaningful."
    Design: Corner/state_machines/attribute_write_on_a_frozen_in_review_revision_is_rejected
    """
    world = simplemart_world_unpinned

    response = api_client.create_attribute_value(
        world["revision"]["id"],
        create_attribute_value_payload("title", "Bright Kitchen Blender 900W v2"),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_VERSION_NOT_DRAFT.value, 409)

    rows, meta = validate_paginated(
        api_client.list_attribute_values(world["revision"]["id"], make_content_author_headers())
    )
    assert meta["total_count"] == 1
    assert rows[0]["value"] == BIGBOX_TITLE

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["state"] == "IN_REVIEW"

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert float(listing["completeness_score_declared"]) == pytest.approx(100.00, abs=0.01)


def test_resubmitting_a_request_already_in_review_is_refused(simplemart_world_unpinned):
    """Submission is a one-shot act: the second call is refused and the original
    submitted_at is not restamped even though the clock has moved on. The first
    submission froze the target revision at IN_REVIEW, and the revision guard of step
    25 is consulted before the request guard of step 26, so the refusal names
    ERR_VERSION_NOT_DRAFT.

    PRD 2.8: "25. The target content revision's `state` is `DRAFT` — otherwise `ERR_VERSION_NOT_DRAFT`. Applies to three operations: writing an attribute value, raising a change request, and submitting one. 26. The change request's `state` is `DRAFT` — otherwise `ERR_CHANGE_REQUEST_NOT_DRAFT`. Applies to submission."
    Design: Corner/state_machines/resubmitting_an_in_review_change_request_returns_not_draft
    """
    world = simplemart_world_unpinned
    move_clock("2026-08-11T00:00:00Z")

    response = api_client.submit_change_request(
        world["change_request"]["id"], {}, make_content_author_headers("author_1")
    )
    validate_error(response, ApiErrorId.ERR_VERSION_NOT_DRAFT.value, 409)

    change_request = validate_success(
        api_client.get_change_request(
            world["change_request"]["id"], make_content_author_headers()
        )
    )
    assert change_request["state"] == "IN_REVIEW"
    assert change_request["submitted_at"].startswith("2026-08-10T00:00:00")


def test_the_legal_approval_records_its_reviewer_and_bumps_the_product(
    simplemart_world_unpinned,
):
    """The first track decision is a self-loop on the request but a real write on
    the product: the acting legal identity is recorded, last_review_at is stamped
    from the clock and the product version moves from 1 to 2 while the request
    stays IN_REVIEW with nothing pinned.

    PRD 3.5: "Whichever way the decision goes, the acting identity is recorded as `legal_reviewer_user_id` or `brand_reviewer_user_id` according to the track, the product's `last_review_at` is stamped from the logical clock, and the product's `version` increments by 1."
    Design: Corner/state_machines/first_track_approval_holds_the_change_request_in_review_self_loop
    """
    world = simplemart_world_unpinned
    assert read_product_version(world["product"]["id"]) == 1

    decided = validate_success(
        api_client.create_review(
            world["change_request"]["id"],
            review_payload("LEGAL", "APPROVED", 1),
            make_legal_reviewer_headers("legal_1"),
        )
    )
    assert decided["state"] == "IN_REVIEW"
    assert decided["legal_review_state"] == "APPROVED"
    assert decided["legal_reviewer_user_id"] == "legal_1"
    assert decided["brand_review_state"] == "PENDING"
    assert decided["decided_at"] is None

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["state"] == "IN_REVIEW"
    assert_pin_ledger(revision, 0)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert listing["pinned_content_version_id"] is None
    assert float(listing["completeness_score_certified"]) == pytest.approx(0.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["version"] == 2
    assert product["last_review_at"].startswith("2026-08-10T00:00:00")
    assert product["status"] == "DRAFT"


def test_a_brand_rejection_short_circuits_the_join_and_reopens_the_revision(
    simplemart_world_unpinned,
):
    """With legal already APPROVED, the brand rejection takes the aggregate request
    straight to the terminal REJECTED without rolling the approved track back, and
    the target revision falls back to DRAFT so the author can edit it again — while
    the listing keeps its empty pin and 0.00 scores.

    PRD 3.5: "When a decision is `REJECTED` on either track, the outcome is deliberately asymmetric to the join, and it short-circuits: the named dimension becomes `REJECTED` and the request's aggregate `state` becomes `REJECTED` immediately, **even while the other track is still `PENDING`**."
    Design: Corner/state_machines/brand_rejection_short_circuits_the_join_and_reopens_the_revision
    """
    world = simplemart_world_unpinned
    validate_success(
        api_client.create_review(
            world["change_request"]["id"],
            review_payload("LEGAL", "APPROVED", 1),
            make_legal_reviewer_headers("legal_1"),
        )
    )
    assert read_product_version(world["product"]["id"]) == 2

    rejected = validate_success(
        api_client.create_review(
            world["change_request"]["id"],
            review_payload("BRAND", "REJECTED", 2),
            make_brand_approver_headers("brand_1"),
        )
    )
    assert rejected["state"] == "REJECTED"
    assert rejected["brand_review_state"] == "REJECTED"
    assert rejected["legal_review_state"] == "APPROVED"
    assert rejected["decided_at"].startswith("2026-08-10T00:00:00")

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["state"] == "DRAFT"
    assert_pin_ledger(revision, 0)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert listing["pinned_content_version_id"] is None
    assert float(listing["completeness_score_certified"]) == pytest.approx(0.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(0.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["status"] == "DRAFT"
    assert product["last_pinned_at"] is None
    assert product["version"] == 3


def test_a_second_decision_on_the_same_track_is_refused(simplemart_world_unpinned):
    """A different legal reviewer cannot overturn the track his colleague already
    decided: the second LEGAL call is refused, the recorded reviewer is still the
    first one, and the refused call is not a write — the product version has not
    moved.

    PRD 2.8: "The named review track is still `PENDING` — otherwise `ERR_TRACK_ALREADY_DECIDED`."
    Design: Corner/state_machines/second_decision_on_the_same_track_returns_track_already_decided
    """
    world = simplemart_world_unpinned
    validate_success(
        api_client.create_review(
            world["change_request"]["id"],
            review_payload("LEGAL", "APPROVED", 1),
            make_legal_reviewer_headers("legal_1"),
        )
    )

    response = api_client.create_review(
        world["change_request"]["id"],
        review_payload("LEGAL", "REJECTED", 2),
        make_legal_reviewer_headers("legal_2"),
    )
    validate_error(response, ApiErrorId.ERR_TRACK_ALREADY_DECIDED.value, 409)

    change_request = validate_success(
        api_client.get_change_request(
            world["change_request"]["id"], make_content_author_headers()
        )
    )
    assert change_request["legal_review_state"] == "APPROVED"
    assert change_request["legal_reviewer_user_id"] == "legal_1"
    assert change_request["state"] == "IN_REVIEW"

    assert read_product_version(world["product"]["id"]) == 2


def test_an_approved_change_request_is_closed_to_further_review_calls(simplemart_world):
    """APPROVED is terminal for the request, so a late reviewer is turned away on
    the aggregate-state guard rather than the per-track one, and the pin the join
    established stands untouched.

    PRD 2.8: "The change request's `state` is `IN_REVIEW` — otherwise `ERR_CHANGE_REQUEST_NOT_IN_REVIEW`."
    Design: Corner/state_machines/approved_change_request_locks_out_further_review_calls
    """
    world = simplemart_world
    assert read_product_version(world["product"]["id"]) == 3

    response = api_client.create_review(
        world["change_request"]["id"],
        review_payload("LEGAL", "REJECTED", 3),
        make_legal_reviewer_headers("legal_9"),
    )
    validate_error(response, ApiErrorId.ERR_CHANGE_REQUEST_NOT_IN_REVIEW.value, 409)

    change_request = validate_success(
        api_client.get_change_request(
            world["change_request"]["id"], make_content_author_headers()
        )
    )
    assert change_request["state"] == "APPROVED"
    assert change_request["legal_review_state"] == "APPROVED"

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["state"] == "PINNED"
    assert_pin_ledger(revision, 1)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert listing["pinned_content_version_id"] == world["revision"]["id"]
    assert read_product_version(world["product"]["id"]) == 3


def test_transmission_stamps_the_clock_and_keeps_the_slots_reserved(bigbox_world):
    """Transmission is a plain advance out of QUEUED: transmitted_at is stamped,
    responded_at stays null, the four slots stay reserved because TRANSMITTED is
    still a holding state, and the retailer version was bumped by the queue write
    alone.

    PRD 3.6: "The job moves `QUEUED → TRANSMITTED` and `transmitted_at` is stamped from the logical clock."
    Design: Corner/state_machines/queue_then_transmit_holds_the_slots_and_stamps_transmitted_at
    """
    world = bigbox_world
    job = _queue_four_slots(world)
    assert read_retailer_version(world["retailer"]["id"]) == 2

    transmitted = validate_success(
        api_client.transmit_syndication_job(
            job["id"], {}, make_syndication_operator_headers()
        )
    )
    assert_syndication_job(transmitted)
    assert transmitted["state"] == "TRANSMITTED"
    assert transmitted["transmitted_at"].startswith("2026-08-10T00:00:00")
    assert transmitted["responded_at"] is None
    assert transmitted["attempt_no"] == 1
    assert float(transmitted["readiness_at_queue"]) == pytest.approx(51.00, abs=0.01)
    assert transmitted["service_fee_cents"] == 9500

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 4)
    assert retailer["version"] == 2

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["syndication_state"] == "PENDING"


def test_transmitting_an_already_transmitted_job_is_refused(bigbox_world):
    """Transmission requires QUEUED, so the second call a day later is refused, the
    original stamp is not overwritten with the new clock reading, and the ledger is
    untouched.

    PRD 2.8: "The job's current `state` admits the requested transition — otherwise `ERR_INVALID_JOB_STATE`."
    Design: Corner/state_machines/transmitting_an_already_transmitted_job_returns_invalid_job_state
    """
    world = bigbox_world
    job = _transmitted_four_slot_job(world)
    move_clock("2026-08-11T00:00:00Z")

    response = api_client.transmit_syndication_job(
        job["id"], {}, make_syndication_operator_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_JOB_STATE.value, 409)

    reread = validate_success(
        api_client.get_syndication_job(job["id"], make_syndication_operator_headers())
    )
    assert reread["state"] == "TRANSMITTED"
    assert reread["transmitted_at"].startswith("2026-08-10T00:00:00")

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 4)
    assert retailer["version"] == 2


def test_an_accepted_response_releases_the_ledger_and_takes_the_listing_live(bigbox_world):
    """The retailer's acceptance is the terminal hop of the job: responded_at is
    stamped, the four reserved slots come back, the listing moves PENDING → LIVE,
    and because a LIVE listing now qualifies for the health input set the product
    index climbs off zero on the availability term alone.

    PRD 3.7: "On `ACCEPTED` the job reaches its terminal `ACCEPTED` state and the listing's `syndication_state` moves `PENDING → LIVE`."
    Design: Corner/state_machines/accepted_response_releases_the_slot_ledger_and_takes_the_listing_live
    """
    world = bigbox_world
    job = _transmitted_four_slot_job(world)

    accepted = get_success_data(
        api_client.retailer_response(
            job["id"],
            {"outcome": "ACCEPTED"},
            make_retailer_integration_headers(world["retailer"]["id"]),
        )
    )
    assert accepted["state"] == "ACCEPTED"
    assert accepted["responded_at"].startswith("2026-08-10T00:00:00")

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 3

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["syndication_state"] == "LIVE"
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(20.00, abs=0.01)


def test_a_rejected_response_cascades_through_all_four_hops(bigbox_world):
    """Three blocking complaints arrive at once: the rows are stored in request
    order, the slots are released, the listing lands in ERROR_HOLD carrying the
    3-to-5 penalty tier, the health recompute raises a HEALTH_DEGRADED alert with no
    source observation behind it, and the product's governance flag turns.

    PRD 3.7: "*Hop 2, caused by hop 1's `BLOCKING` rows:* the listing's `open_blocking_error_count` is recomputed and is now positive, so the listing's `syndication_state` becomes `ERROR_HOLD` and its `readiness_score` is recomputed with the new penalty tier."
    Design: Corner/state_machines/rejected_response_cascades_error_hold_penalty_health_and_governance_flag
    """
    world = bigbox_world
    job = _transmitted_four_slot_job(world)

    rejected = reject_job(job["id"], world["retailer"]["id"], THREE_BLOCKING_ROWS)
    assert rejected["state"] == "REJECTED"

    rows, meta = validate_paginated(
        api_client.list_rejection_errors(job["id"], make_syndication_operator_headers())
    )
    assert meta["total_count"] == 3
    assert rows[0]["retailer_error_code"] == "E-BRAND-MISSING"

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 3

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["open_blocking_error_count"] == 3
    assert listing["syndication_state"] == "ERROR_HOLD"
    assert float(listing["readiness_score"]) == pytest.approx(39.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(20.00, abs=0.01)
    assert product["open_alert_count"] == 1
    assert product["governance_flag"] == "CONTENT_AT_RISK"

    alert = _only_alert_of(world["listing"]["id"])
    assert_shelf_alert(alert)
    assert alert["alert_type"] == "HEALTH_DEGRADED"
    assert alert["state"] == "OPEN"
    assert alert["source_observation_id"] is None


def test_closing_the_last_blocking_row_lifts_the_listing_out_of_error_hold(bigbox_world):
    """A single FIX takes the blocking count to zero, so the listing leaves
    ERROR_HOLD for NOT_SYNDICATED at an unpenalised readiness — and by leaving the
    health input set it drops the product index back to 0.00 while the
    HEALTH_DEGRADED alert, which has no automatic clearing path, stays open.

    PRD 3.7: "A `FIX` moves the row `OPEN → RESOLVED` and a `WAIVE` moves it `OPEN → WAIVED`; both are terminal, both record `resolved_by_user_id` from the acting `X-User-ID` and stamp `resolved_at` from the logical clock alongside the supplied `resolution_note`, and — this is the important symmetry — both have exactly the same downstream effect."
    Design: Corner/state_machines/closing_the_last_blocking_row_lifts_the_listing_out_of_error_hold
    """
    world = bigbox_world
    job = _transmitted_four_slot_job(world)
    reject_job(job["id"], world["retailer"]["id"], SINGLE_BLOCKING_ROW)
    row = rejection_errors_of(job["id"])[0]

    resolved = validate_success(
        api_client.resolve_rejection_error(
            row["id"],
            resolve_rejection_error_payload(
                "FIX", "brand attribute added to the pinned revision"
            ),
            make_syndication_operator_headers("ops_1"),
        )
    )
    assert resolved["state"] == "RESOLVED"
    assert resolved["resolution_mode"] == "FIX"
    assert resolved["resolved_by_user_id"] == "ops_1"

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["open_blocking_error_count"] == 0
    assert listing["syndication_state"] == "NOT_SYNDICATED"
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(0.00, abs=0.01)
    assert product["open_alert_count"] == 1
    assert product["governance_flag"] == "CONTENT_AT_RISK"


def test_a_requeue_is_refused_while_a_blocking_row_is_still_open(bigbox_world):
    """The rejected job cannot cycle until its blocking complaint is closed: the
    requeue is refused, the job keeps attempt_no 1 and its original window, and the
    slots are not re-reserved.

    PRD 3.7: "Requeue is rejected with `ERR_INVALID_JOB_STATE` from any state other than `REJECTED` or `PARTIALLY_ACCEPTED`, and with `ERR_BLOCKING_ERRORS_UNRESOLVED` while any `BLOCKING` rejection error of the job is still `OPEN` rather than `RESOLVED` or `WAIVED`."
    Design: Corner/state_machines/requeue_with_an_open_blocking_row_returns_blocking_errors_unresolved
    """
    world = bigbox_world
    job = _transmitted_four_slot_job(world)
    reject_job(job["id"], world["retailer"]["id"], SINGLE_BLOCKING_ROW)

    retailer_version = read_retailer_version(world["retailer"]["id"])
    assert retailer_version == 3

    response = api_client.requeue_syndication_job(
        job["id"],
        requeue_payload(
            slot_count=4,
            window_start="2026-08-17T00:00:00Z",
            window_end="2026-08-18T00:00:00Z",
            expected_retailer_version=retailer_version,
        ),
        make_syndication_operator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_BLOCKING_ERRORS_UNRESOLVED.value, 409)

    reread = validate_success(
        api_client.get_syndication_job(job["id"], make_syndication_operator_headers())
    )
    assert reread["state"] == "REJECTED"
    assert reread["attempt_no"] == 1
    assert reread["window_start"].startswith("2026-08-15T00:00:00")

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 3


def test_a_crawl_moves_the_shelf_dimension_without_disturbing_syndication(bigbox_world):
    """The listing carries two independent dimensions: the unauthorized-seller crawl
    drives shelf_state to UNAUTHORIZED and raises the HIGH alert owned by the named
    account team, while syndication_state stays LIVE — and readiness pays the
    accuracy floor precisely because the listing is no longer OK.

    PRD 3.9: "An observation with `unauthorized_seller_count` of 1 or more moves the listing to `UNAUTHORIZED` — provided it is not already `SUSPENDED` — and raises an alert with `alert_type` `UNAUTHORIZED_LISTING` and `severity` `HIGH`, whose `assigned_account_team_user_id` is copied from the listing's `account_team_user_id` and is null when the listing has no named owner."
    Design: Corner/state_machines/syndication_and_shelf_dimensions_of_a_listing_move_independently
    """
    world = bigbox_world
    observation = _unauthorized_crawl_of_a_live_listing(world)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["shelf_state"] == "UNAUTHORIZED"
    assert listing["syndication_state"] == "LIVE"
    assert listing["search_rank_latest"] == 3
    assert float(listing["content_accuracy_pct"]) == pytest.approx(96.00, abs=0.01)
    assert float(listing["rating_avg"]) == pytest.approx(4.50, abs=0.01)
    assert listing["in_stock"] is True
    assert float(listing["readiness_score"]) == pytest.approx(75.00, abs=0.01)

    alert = _only_alert_of(world["listing"]["id"])
    assert alert["alert_type"] == "UNAUTHORIZED_LISTING"
    assert alert["severity"] == "HIGH"
    assert alert["assigned_account_team_user_id"] == "acct_bigbox_1"
    assert alert["source_observation_id"] == observation["id"]

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(94.70, abs=0.01)
    assert product["open_alert_count"] == 1
    assert product["governance_flag"] == "LISTING_RISK"


def test_the_account_team_clearance_resolves_the_unauthorized_alert(bigbox_world):
    """Only a human clears unauthorized-seller enforcement. The clearance moves the
    shelf dimension back to OK without touching syndication, stamps the platform's
    own resolution note on the alert, and lifts the accuracy floor off readiness
    while the observation-driven health index stays exactly where it was.

    PRD 3.9: "Clearing to `OK` is permitted from `UNAUTHORIZED`, `OOS_WATCH` or `SUSPENDED`, leaves `syndication_state` untouched, and resolves every `UNAUTHORIZED_LISTING` alert of the listing still in `OPEN` or `ACKNOWLEDGED` with `resolution_note` set to the literal string `AUTO_CLEARED_BY_ACCOUNT_TEAM`; it then recomputes the listing's `readiness_score`, the product's `open_alert_count` and `governance_flag`, and increments the product's `version` by 1."
    Design: Corner/state_machines/account_team_shelf_status_ok_auto_resolves_the_unauthorized_alert
    """
    world = bigbox_world
    _unauthorized_crawl_of_a_live_listing(world)

    cleared = validate_success(
        api_client.set_shelf_status(
            world["listing"]["id"],
            {"shelf_state": "OK"},
            make_account_team_headers("acct_bigbox_1"),
        )
    )
    assert cleared["shelf_state"] == "OK"
    assert cleared["syndication_state"] == "LIVE"
    assert float(cleared["readiness_score"]) == pytest.approx(89.40, abs=0.01)

    alerts, meta = validate_paginated(
        api_client.list_shelf_alerts(
            make_account_team_headers(),
            params={"retailer_listing_id": world["listing"]["id"], "state": "RESOLVED"},
        )
    )
    assert meta["total_count"] == 1
    assert alerts[0]["resolution_note"] == AUTO_CLEARED_BY_ACCOUNT_TEAM
    assert alerts[0]["resolved_at"].startswith("2026-08-10T00:00:00")

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["open_alert_count"] == 0
    assert product["governance_flag"] == "NONE"
    assert float(product["shelf_health_index"]) == pytest.approx(94.70, abs=0.01)


def test_approving_the_fourth_image_lifts_only_the_certified_variant(bigbox_world):
    """The retailer's blessing on the fourth image completes the min_image_count of
    4, so the certified image component fills to its full 20.00 and the certified
    score climbs to meet the declared one — which never moved, because the author's
    claimed image_count was 4 all along and brand is still absent from both views.

    PRD 3.3: "On `APPROVE`, the newly approved asset raises the approved image-role count for the product, so `completeness_score_certified` and `readiness_score` of the listing joining that product to the acting retailer are recomputed on the spot."
    Design: Corner/state_machines/media_asset_approval_lifts_only_the_certified_variant
    """
    world = bigbox_world
    fourth = upload_asset(world["product"]["id"], "SECONDARY_IMAGE", "s3://brand/b/sec3.jpg")
    assert fourth["approval_state"] == "PENDING"

    approved = validate_success(
        api_client.decide_media_asset(
            fourth["id"],
            media_decision_payload("APPROVE"),
            make_retailer_integration_headers(world["retailer"]["id"]),
        )
    )
    assert_media_asset(approved)
    assert approved["approval_state"] == "APPROVED"
    assert approved["approving_retailer_id"] == world["retailer"]["id"]
    assert approved["decided_at"].startswith("2026-08-10T00:00:00")

    diagnostic = validate_success(
        api_client.get_listing_completeness(
            world["listing"]["id"], make_content_author_headers()
        )
    )
    assert float(diagnostic["certified_score"]) == pytest.approx(90.00, abs=0.01)
    assert float(diagnostic["declared_score"]) == pytest.approx(90.00, abs=0.01)
    assert float(diagnostic["certified_image_component"]) == pytest.approx(20.00, abs=0.01)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert float(listing["completeness_score_certified"]) == pytest.approx(90.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(54.00, abs=0.01)


def test_acknowledging_then_resolving_an_alert_keeps_the_rollup_honest(simplemart_world):
    """An acknowledged alert is still open follow-up, so the product rollup does not
    move on the acknowledgement and only falls when the alert is resolved. Resolving
    it leaves the shelf dimension alone: the listing is still on OOS_WATCH and still
    paying the accuracy floor.

    PRD 3.9: "Acknowledging one moves it `OPEN → ACKNOWLEDGED` and records `acknowledged_by_user_id` from the acting `X-User-ID`; the product's `open_alert_count` is deliberately **unchanged**, because an acknowledged alert is still open follow-up."
    Design: Corner/state_machines/alert_acknowledge_then_resolve_keeps_the_rollup_honest
    """
    world = simplemart_world
    _out_of_stock_crawl(world)
    alert = _only_alert_of(world["listing"]["id"])
    assert alert["alert_type"] == "OUT_OF_STOCK"

    acknowledged = validate_success(
        api_client.acknowledge_shelf_alert(
            alert["id"], {}, make_account_team_headers("acct_simplemart_1")
        )
    )
    assert acknowledged["state"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == "acct_simplemart_1"

    mid = validate_success(
        api_client.get_product(world["product"]["id"], make_account_team_headers())
    )
    assert mid["open_alert_count"] == 1
    assert mid["governance_flag"] == "CONTENT_AT_RISK"

    note = "third-party seller listing removed and stock replenished"
    resolved = validate_success(
        api_client.resolve_shelf_alert(
            alert["id"],
            resolve_alert_payload(note),
            make_account_team_headers("acct_simplemart_1"),
        )
    )
    assert resolved["state"] == "RESOLVED"
    assert resolved["resolution_note"] == note
    assert resolved["resolved_at"].startswith("2026-08-10T00:00:00")

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_account_team_headers())
    )
    assert product["open_alert_count"] == 0
    assert product["governance_flag"] == "NONE"

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["shelf_state"] == "OOS_WATCH"
    assert float(listing["readiness_score"]) == pytest.approx(84.00, abs=0.01)


def test_both_alert_actions_are_refused_once_the_alert_is_resolved(simplemart_world):
    """RESOLVED is terminal for an alert: neither a late acknowledgement nor a second
    resolution is admitted, and the note recorded by the first resolution is not
    overwritten by the refused one.

    PRD 3.9: "Acknowledging an already-acknowledged alert, or acting on a `RESOLVED` one, is rejected with `ERR_ALERT_ALREADY_RESOLVED`."
    Design: Corner/state_machines/acknowledging_a_resolved_alert_returns_alert_already_resolved
    """
    world = simplemart_world
    _out_of_stock_crawl(world)
    alert = _only_alert_of(world["listing"]["id"])
    validate_success(
        api_client.resolve_shelf_alert(
            alert["id"],
            resolve_alert_payload("first pass"),
            make_account_team_headers("acct_simplemart_1"),
        )
    )

    validate_error(
        api_client.acknowledge_shelf_alert(
            alert["id"], {}, make_account_team_headers("acct_simplemart_1")
        ),
        ApiErrorId.ERR_ALERT_ALREADY_RESOLVED.value,
        409,
    )
    validate_error(
        api_client.resolve_shelf_alert(
            alert["id"],
            resolve_alert_payload("second pass"),
            make_account_team_headers("acct_simplemart_1"),
        ),
        ApiErrorId.ERR_ALERT_ALREADY_RESOLVED.value,
        409,
    )

    reread = validate_success(
        api_client.get_shelf_alert(alert["id"], make_account_team_headers())
    )
    assert reread["state"] == "RESOLVED"
    assert reread["resolution_note"] == "first pass"

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_account_team_headers())
    )
    assert product["open_alert_count"] == 0


def test_retailer_approval_takes_a_deployment_live_and_earns_the_bonus(simplemart_world):
    """SimpleMart requires approval, so the new module waits in
    PENDING_RETAILER_APPROVAL earning nothing. The retailer's APPROVE moves it to
    LIVE, stamps the decision instant, and the flat five-point enhanced-content
    bonus appears in readiness — while the revision now carries two live references.

    PRD 3.8: "On `APPROVE` the deployment moves `PENDING_RETAILER_APPROVAL → LIVE`, `retailer_decision_at` is stamped from the logical clock, the listing's `readiness_score` is recomputed now carrying the 5-point bonus, the product's `shelf_health_index` is recomputed, and the listing's `version` increments by 1."
    Design: Corner/state_machines/retailer_approval_takes_a_deployment_live_and_earns_the_readiness_bonus
    """
    world = simplemart_world
    deployment = _pending_a_plus_deployment(world)
    assert_enhanced_deployment(deployment)
    assert deployment["state"] == "PENDING_RETAILER_APPROVAL"

    live = decide_deployment(deployment["id"], world["retailer"]["id"], "APPROVE")
    assert live["state"] == "LIVE"
    assert live["retailer_decision_at"].startswith("2026-08-10T00:00:00")

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert_pin_ledger(revision, 2)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert float(listing["readiness_score"]) == pytest.approx(65.00, abs=0.01)
    assert float(listing["completeness_score_certified"]) == pytest.approx(100.00, abs=0.01)


def test_withdrawing_a_rejected_deployment_is_refused(simplemart_world):
    """REJECTED is terminal, and the retailer's rejection has already given the pin
    ledger its reference back, so the author's compensating withdrawal has nothing
    left to compensate: it is refused, withdrawn_reason is never recorded, and the
    listing carries no bonus.

    PRD 3.8: "Withdrawal is the author's compensating action and is available from either `PENDING_RETAILER_APPROVAL` or `LIVE`; from `REJECTED` or `WITHDRAWN` the attempt is `ERR_DEPLOYMENT_NOT_ACTIVE`."
    Design: Corner/state_machines/withdrawing_a_rejected_deployment_returns_deployment_not_active
    """
    world = simplemart_world
    deployment = _pending_a_plus_deployment(world)
    rejected = decide_deployment(deployment["id"], world["retailer"]["id"], "REJECT")
    assert rejected["state"] == "REJECTED"

    response = api_client.withdraw_enhanced_deployment(
        deployment["id"],
        {"withdrawn_reason": "pulled from the launch plan"},
        make_content_author_headers("author_1"),
    )
    validate_error(response, ApiErrorId.ERR_DEPLOYMENT_NOT_ACTIVE.value, 409)

    reread = validate_success(
        api_client.get_enhanced_deployment(deployment["id"], make_content_author_headers())
    )
    assert reread["state"] == "REJECTED"
    assert reread["withdrawn_reason"] is None

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert_pin_ledger(revision, 1)

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_content_author_headers())
    )
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)
