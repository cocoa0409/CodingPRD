"""Each refusal reported under its own identifier, at its own HTTP status, leaving the
rows it touched exactly as they were."""
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_pin_ledger, assert_slot_ledger
from test_helpers.factories import (
    create_deployment_payload,
    create_requirement_payload,
    create_retailer_listing_payload,
    create_syndication_job_payload,
    patch_retailer_payload,
    rejection_error_row,
    resolve_rejection_error_payload,
    retailer_response_payload,
)
from test_helpers.fixtures import (
    queue_job,
    read_listing_version,
    read_retailer_version,
    register_product,
    register_retailer,
    review_brand,
    review_legal,
    transmit_job,
    upload_asset,
)
from test_helpers.test_users import (
    make_account_team_headers,
    make_content_author_headers,
    make_retailer_integration_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

MISSING_CONTENT_VERSION_ID = "33333333-3333-4333-8333-333333333333"
MISSING_LISTING_ID = "44444444-4444-4444-8444-444444444444"
MISSING_REJECTION_ERROR_ID = "55555555-5555-4555-8555-555555555555"
MISSING_DEPLOYMENT_ID = "66666666-6666-4666-8666-666666666666"
MISSING_ALERT_ID = "77777777-7777-4777-8777-777777777777"

FIRST_WINDOW = ("2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z")
DEPLOYMENT_WINDOW = ("2026-08-12T00:00:00Z", "2026-08-13T00:00:00Z")

BLOCKING_BRAND_ROW = rejection_error_row(
    "E-BRAND-MISSING", "BLOCKING", "brand attribute is required", "brand"
)


def _retailer(retailer_id):
    return validate_success(api_client.get_retailer(retailer_id, make_shelf_admin_headers()))


def _listing(retailer_listing_id):
    return validate_success(
        api_client.get_retailer_listing(retailer_listing_id, make_shelf_admin_headers())
    )


def _revision(content_version_id):
    return validate_success(
        api_client.get_content_version(content_version_id, make_content_author_headers())
    )


def _rejection_rows(job_id, params=None):
    return validate_paginated(
        api_client.list_rejection_errors(
            job_id, make_syndication_operator_headers(), params=params
        )
    )


def _resolve(rejection_error_id, note, operator_user_id, mode="FIX"):
    return api_client.resolve_rejection_error(
        rejection_error_id,
        resolve_rejection_error_payload(mode, note),
        make_syndication_operator_headers(operator_user_id),
    )


def _one_retailer_roster():
    """A roster holding exactly one retailer, so a page of any accepted size reports a
    single row."""
    return register_retailer(
        "PageMart",
        "RETP",
        min_image_count=1,
        feed_slot_capacity=4,
        max_concurrent_feed_windows=1,
        enhanced_content_requires_approval=False,
    )


def _rejected_with_one_blocking_row(world):
    """A BigBox job transmitted and then refused by the retailer over the missing brand
    attribute, which puts the listing on ERROR_HOLD with one open blocking row."""
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        4,
        FIRST_WINDOW[0],
        FIRST_WINDOW[1],
        world["retailer"]["id"],
    )
    transmit_job(job["id"])
    validate_success(
        api_client.retailer_response(
            job["id"],
            retailer_response_payload("REJECTED", [BLOCKING_BRAND_ROW]),
            make_retailer_integration_headers(world["retailer"]["id"]),
        )
    )
    rows, _meta = _rejection_rows(job["id"])
    return job, rows[0]


def test_an_unknown_content_revision_reports_its_own_not_found(clock_at_base):
    """The revision collection answers for itself rather than through a shared generic
    code.

    PRD 2.8: "The referenced content revision exists, whether it is named as a target, as a superseded predecessor, or as the payload of a transmission — otherwise `ERR_CONTENT_VERSION_NOT_FOUND`."
    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_error
    """
    response = api_client.get_content_version(
        MISSING_CONTENT_VERSION_ID, make_content_author_headers()
    )
    validate_error(response, ApiErrorId.ERR_CONTENT_VERSION_NOT_FOUND.value, 404)


def test_an_unknown_listing_reports_its_own_not_found(clock_at_base):
    """A junction row that does not exist is a listing not-found, not a product or
    retailer one.

    PRD 2.8: "The referenced retailer listing exists — otherwise `ERR_LISTING_NOT_FOUND`."
    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_error
    """
    response = api_client.get_retailer_listing(MISSING_LISTING_ID, make_shelf_admin_headers())
    validate_error(response, ApiErrorId.ERR_LISTING_NOT_FOUND.value, 404)


def test_resolving_an_unknown_rejection_row_is_a_not_found_not_a_state_error(clock_at_base):
    """The id lookup happens before the row's own state rule, so an id belonging to no
    row can never come back as an already-closed complaint.

    PRD 2.8: "The referenced rejection error exists — otherwise `ERR_REJECTION_ERROR_NOT_FOUND`."
    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_error
    """
    response = _resolve(MISSING_REJECTION_ERROR_ID, "no such row", "ops_1")
    validate_error(response, ApiErrorId.ERR_REJECTION_ERROR_NOT_FOUND.value, 404)


def test_an_unknown_deployment_reports_its_own_not_found(clock_at_base):
    """The placement calendar answers for itself too.

    PRD 2.8: "The referenced deployment exists — otherwise `ERR_DEPLOYMENT_NOT_FOUND`."
    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_error
    """
    response = api_client.get_enhanced_deployment(
        MISSING_DEPLOYMENT_ID, make_content_author_headers()
    )
    validate_error(response, ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND.value, 404)


def test_acknowledging_an_unknown_alert_reports_its_own_not_found(clock_at_base):
    """Acknowledgement resolves the alert id before it considers the alert's lifecycle,
    so an unknown id is a plain not-found rather than an already-resolved complaint.

    PRD 2.8: "The referenced shelf alert exists — otherwise `ERR_ALERT_NOT_FOUND`."
    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_error
    """
    response = api_client.acknowledge_shelf_alert(
        MISSING_ALERT_ID, {}, make_account_team_headers()
    )
    validate_error(response, ApiErrorId.ERR_ALERT_NOT_FOUND.value, 404)


def test_every_not_found_payload_carries_only_the_identifier_and_the_message(clock_at_base):
    """Each of the five refusals answers with the same two-key error payload and nothing
    else — no partial resource, no echoed request.

    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    Design: Corner/errors/every_unknown_id_returns_its_own_not_found_error
    """
    payloads = [
        validate_error(
            api_client.get_content_version(
                MISSING_CONTENT_VERSION_ID, make_content_author_headers()
            ),
            ApiErrorId.ERR_CONTENT_VERSION_NOT_FOUND.value,
            404,
        ),
        validate_error(
            api_client.get_retailer_listing(MISSING_LISTING_ID, make_shelf_admin_headers()),
            ApiErrorId.ERR_LISTING_NOT_FOUND.value,
            404,
        ),
        validate_error(
            _resolve(MISSING_REJECTION_ERROR_ID, "no such row", "ops_1"),
            ApiErrorId.ERR_REJECTION_ERROR_NOT_FOUND.value,
            404,
        ),
        validate_error(
            api_client.get_enhanced_deployment(
                MISSING_DEPLOYMENT_ID, make_content_author_headers()
            ),
            ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND.value,
            404,
        ),
        validate_error(
            api_client.acknowledge_shelf_alert(
                MISSING_ALERT_ID, {}, make_account_team_headers()
            ),
            ApiErrorId.ERR_ALERT_NOT_FOUND.value,
            404,
        ),
    ]
    for payload in payloads:
        assert set(payload) == {"error_id", "message"}


def test_a_page_size_below_one_is_refused(clock_at_base):
    """Zero is not a page size, and the refusal is a pagination complaint rather than a
    body-shape one.

    PRD 2.3: "A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400); both parameters must be integers."
    Design: Corner/errors/pagination_bounds_are_rejected_and_the_upper_limit_is_inclusive
    """
    _one_retailer_roster()
    response = api_client.list_retailers(
        make_shelf_admin_headers(), params={"limit": 0, "offset": 0}
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_a_page_size_above_one_hundred_is_refused(clock_at_base):
    """One past the ceiling is refused on the same rule that admits the ceiling itself.

    PRD 2.3: "A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400); both parameters must be integers."
    Design: Corner/errors/pagination_bounds_are_rejected_and_the_upper_limit_is_inclusive
    """
    _one_retailer_roster()
    response = api_client.list_retailers(
        make_shelf_admin_headers(), params={"limit": 101, "offset": 0}
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_a_negative_offset_is_refused(clock_at_base):
    """The starting position has a floor of zero and no ceiling, so minus one is the only
    way to break it.

    PRD 2.3: "`offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0, with no upper bound."
    Design: Corner/errors/pagination_bounds_are_rejected_and_the_upper_limit_is_inclusive
    """
    _one_retailer_roster()
    response = api_client.list_retailers(
        make_shelf_admin_headers(), params={"limit": 10, "offset": -1}
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)


def test_a_page_size_of_exactly_one_hundred_is_accepted(clock_at_base):
    """The upper bound is inclusive: a hundred is the largest page the platform will
    serve, and it serves it.

    PRD 2.3: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."
    Design: Corner/errors/pagination_bounds_are_rejected_and_the_upper_limit_is_inclusive
    """
    retailer = _one_retailer_roster()

    rows, meta = validate_paginated(
        api_client.list_retailers(make_shelf_admin_headers(), params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == retailer["id"]


def test_a_feed_window_ending_at_its_own_start_is_refused(bigbox_world):
    """Equal endpoints are not a zero-length window the feed will accept: strictness is
    required in both directions, so nothing queues.

    PRD 3.6: "`window_end` must be strictly after `window_start`, otherwise `ERR_WINDOW_INVALID`."
    Design: Corner/errors/window_end_not_after_window_start_returns_400_on_both_writers
    """
    world = bigbox_world
    response = api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            4,
            "2026-08-15T00:00:00Z",
            "2026-08-15T00:00:00Z",
            read_retailer_version(world["retailer"]["id"]),
        ),
        make_syndication_operator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_INVALID.value, 400)

    _jobs, meta = validate_paginated(
        api_client.list_syndication_jobs(
            make_syndication_operator_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_a_backwards_placement_window_is_refused_before_the_image_gate(bigbox_world):
    """The placement calendar reads its own bounds first. This listing would also fail
    the four-image minimum with only three approved images, yet the answer is the window
    complaint, because the window check comes first.

    PRD 3.8: "The window is **half-open**: `window_start` is inclusive and `window_end` is exclusive, and `window_end` must be strictly after `window_start` or the request fails with `ERR_WINDOW_INVALID`."
    Design: Corner/errors/window_end_not_after_window_start_returns_400_on_both_writers
    """
    world = bigbox_world
    response = api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            world["assets"][0]["id"],
            "A_PLUS_PAGE",
            "2026-08-14T00:00:00Z",
            "2026-08-13T00:00:00Z",
            read_listing_version(world["listing"]["id"]),
        ),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_INVALID.value, 400)

    _rows, meta = validate_paginated(
        api_client.list_enhanced_deployments(
            make_content_author_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_neither_refused_window_moved_a_single_counter(bigbox_world):
    """Both writers refused before touching state: no slots are held, the retailer sits
    at its opening version, and the listing is untouched and still unsyndicated.

    PRD 2.8: "`window_end` is strictly after `window_start`, and both bounds parse as ISO 8601 UTC instants — otherwise `ERR_WINDOW_INVALID`."
    Design: Corner/errors/window_end_not_after_window_start_returns_400_on_both_writers
    """
    world = bigbox_world
    listing_version = read_listing_version(world["listing"]["id"])

    api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            4,
            "2026-08-15T00:00:00Z",
            "2026-08-15T00:00:00Z",
            read_retailer_version(world["retailer"]["id"]),
        ),
        make_syndication_operator_headers(),
    )
    api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            world["assets"][0]["id"],
            "A_PLUS_PAGE",
            "2026-08-14T00:00:00Z",
            "2026-08-13T00:00:00Z",
            listing_version,
        ),
        make_content_author_headers(),
    )

    retailer = _retailer(world["retailer"]["id"])
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 1

    listing = _listing(world["listing"]["id"])
    assert listing["version"] == listing_version
    assert listing["syndication_state"] == "NOT_SYNDICATED"


def test_a_second_listing_for_the_same_pair_is_refused(bigbox_world):
    """Naming a different account team lead does not make it a different relationship:
    the pair is already carried, so the second open is a duplicate and the surviving row
    keeps the first lead.

    PRD 3.4: "At most one listing may exist per product-and-retailer pair, and a second attempt is rejected with `ERR_DUPLICATE_LISTING`."
    Design: Corner/errors/duplicate_listing_and_duplicate_requirement_both_return_409
    """
    world = bigbox_world
    response = api_client.create_retailer_listing(
        create_retailer_listing_payload(
            world["product"]["id"],
            world["retailer"]["id"],
            account_team_user_id="acct_bigbox_2",
        ),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_LISTING.value, 409)

    rows, meta = validate_paginated(
        api_client.list_retailer_listings(
            make_shelf_admin_headers(),
            params={
                "product_id": world["product"]["id"],
                "retailer_id": world["retailer"]["id"],
            },
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["account_team_user_id"] == "acct_bigbox_1"


def test_a_second_requirement_for_the_same_attribute_key_is_refused(bigbox_world):
    """Re-declaring `title` at a softer level with a weight override does not overwrite
    the contract — the retailer keeps its three original rows, `title` still REQUIRED and
    still on the taxonomy weight.

    PRD 3.1: "A retailer may hold at most one requirement row per attribute key; a second attempt is rejected with `ERR_DUPLICATE_REQUIREMENT`."
    Design: Corner/errors/duplicate_listing_and_duplicate_requirement_both_return_409
    """
    world = bigbox_world
    response = api_client.create_retailer_requirement(
        world["retailer"]["id"],
        create_requirement_payload(
            attribute_key="title", requirement_level="RECOMMENDED", weight_override=5.00
        ),
        make_shelf_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_REQUIREMENT.value, 409)

    rows, meta = validate_paginated(
        api_client.list_retailer_requirements(
            world["retailer"]["id"], make_shelf_admin_headers(), params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 3
    title_row = next(row for row in rows if row["attribute_key"] == "title")
    assert title_row["requirement_level"] == "REQUIRED"
    assert title_row["weight_override"] is None


def test_the_refused_requirement_recomputed_no_score(bigbox_world):
    """A declaration that never lands never runs the cascade, so the listing still shows
    the three-required-row arithmetic it started with.

    PRD 3.1: "Declaring a requirement recomputes both completeness variants and the readiness score of every listing of that retailer, and then the shelf health index of every product those listings touch."
    Design: Corner/errors/duplicate_listing_and_duplicate_requirement_both_return_409
    """
    world = bigbox_world
    api_client.create_retailer_requirement(
        world["retailer"]["id"],
        create_requirement_payload(
            attribute_key="title", requirement_level="RECOMMENDED", weight_override=5.00
        ),
        make_shelf_admin_headers(),
    )

    listing = _listing(world["listing"]["id"])
    assert float(listing["completeness_score_certified"]) == pytest.approx(85.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)


def _paused_bigbox_with_a_second_product(world):
    """A second product on the shelf-side of the house, and the retailer moved to PAUSED
    with its opening version supplied as the guard."""
    second_product = register_product("SKU-B-2", "00012345679063")
    validate_success(
        api_client.patch_retailer(
            world["retailer"]["id"],
            patch_retailer_payload(1, status="PAUSED"),
            make_shelf_admin_headers(),
        )
    )
    return second_product


def test_a_listing_cannot_be_opened_against_a_paused_retailer(bigbox_world):
    """The second product never reaches the shelf: pausing the retailer closes the door
    on new listings, and nothing is recorded for the pair.

    PRD 3.4: "A listing may only be opened against a retailer whose `status` is `ACTIVE`; against a `PAUSED` or `OFFBOARDED` retailer the attempt is rejected with `ERR_RETAILER_NOT_ACTIVE`."
    Design: Corner/errors/paused_retailer_blocks_both_the_listing_and_the_queue_call
    """
    world = bigbox_world
    second_product = _paused_bigbox_with_a_second_product(world)

    response = api_client.create_retailer_listing(
        create_retailer_listing_payload(second_product["id"], world["retailer"]["id"]),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_RETAILER_NOT_ACTIVE.value, 409)

    _rows, meta = validate_paginated(
        api_client.list_retailer_listings(
            make_shelf_admin_headers(), params={"product_id": second_product["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_queueing_against_a_paused_retailer_is_a_status_refusal_not_a_version_refusal(
    bigbox_world,
):
    """The queue call supplies the retailer's *current* version, which is now 2 after the
    pause, so the concurrency guard has nothing to complain about — the refusal can only
    be the status gate, and it is.

    PRD 2.8: "The retailer's `status` is `ACTIVE` — otherwise `ERR_RETAILER_NOT_ACTIVE`."
    Design: Corner/errors/paused_retailer_blocks_both_the_listing_and_the_queue_call
    """
    world = bigbox_world
    _paused_bigbox_with_a_second_product(world)

    response = api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            4,
            FIRST_WINDOW[0],
            FIRST_WINDOW[1],
            read_retailer_version(world["retailer"]["id"]),
        ),
        make_syndication_operator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_RETAILER_NOT_ACTIVE.value, 409)

    _jobs, meta = validate_paginated(
        api_client.list_syndication_jobs(
            make_syndication_operator_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_the_refused_queue_call_reserved_no_slots(bigbox_world):
    """Only a successful queue moves the ledger, so the reserved figure is still zero and
    the retailer's version has advanced exactly once — for the pause itself.

    PRD 3.6: "On success, the retailer's `feed_slots_reserved` grows by the job's `slot_count` and the retailer's `version` increments by 1."
    Design: Corner/errors/paused_retailer_blocks_both_the_listing_and_the_queue_call
    """
    world = bigbox_world
    _paused_bigbox_with_a_second_product(world)
    api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            4,
            FIRST_WINDOW[0],
            FIRST_WINDOW[1],
            read_retailer_version(world["retailer"]["id"]),
        ),
        make_syndication_operator_headers(),
    )

    retailer = _retailer(world["retailer"]["id"])
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 2


def test_pausing_a_retailer_recomputes_its_existing_listing_without_erasing_it(bigbox_world):
    """A pause is not a delete. The existing listing is recomputed by the envelope write
    and comes back with exactly the same arithmetic, still carried and still unsyndicated.

    PRD 3.1: "Its consequences reach further than the retailer row: the retailer's `version` increments by 1, then `completeness_score_declared`, `completeness_score_certified` and `readiness_score` are recomputed for every listing belonging to that retailer — because `min_image_count` feeds the image component of the certified variant — and then `shelf_health_index` is recomputed for every product touched by those listings."
    Design: Corner/errors/paused_retailer_blocks_both_the_listing_and_the_queue_call
    """
    world = bigbox_world
    _paused_bigbox_with_a_second_product(world)

    retailer = _retailer(world["retailer"]["id"])
    assert retailer["status"] == "PAUSED"
    assert retailer["version"] == 2

    listing = _listing(world["listing"]["id"])
    assert float(listing["completeness_score_certified"]) == pytest.approx(85.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)
    assert listing["syndication_state"] == "NOT_SYNDICATED"


def test_the_first_close_records_the_acting_operator_and_the_mode(bigbox_world):
    """The operator who fixes the content is the one written onto the row, together with
    the mode and the note supplied on that call.

    PRD 3.7: "A `FIX` moves the row `OPEN → RESOLVED` and a `WAIVE` moves it `OPEN → WAIVED`; both are terminal, both record `resolved_by_user_id` from the acting `X-User-ID` and stamp `resolved_at` from the logical clock alongside the supplied `resolution_note`, and — this is the important symmetry — both have exactly the same downstream effect."
    Design: Corner/errors/resolving_an_already_closed_rejection_row_returns_409
    """
    world = bigbox_world
    _job, row = _rejected_with_one_blocking_row(world)

    closed = validate_success(_resolve(row["id"], "brand attribute added", "ops_1"))
    assert closed["state"] == "RESOLVED"
    assert closed["resolution_mode"] == "FIX"
    assert closed["resolved_by_user_id"] == "ops_1"
    assert closed["resolution_note"] == "brand attribute added"
    assert closed["resolved_at"].startswith("2026-08-10T00:00:00")


def test_the_first_close_lifts_the_listing_off_error_hold(bigbox_world):
    """With the only blocking row closed and no job left holding the feed, the listing
    walks back to NOT_SYNDICATED and its readiness loses the penalty entirely.

    PRD 3.7: "When the closing call takes `open_blocking_error_count` to zero and no job of the listing is in `QUEUED` or `TRANSMITTED`, the listing's `syndication_state` moves `ERROR_HOLD → NOT_SYNDICATED` and its readiness is recomputed with no penalty at all, which in turn changes whether the listing qualifies for the product's health input set."
    Design: Corner/errors/resolving_an_already_closed_rejection_row_returns_409
    """
    world = bigbox_world
    _job, row = _rejected_with_one_blocking_row(world)
    validate_success(_resolve(row["id"], "brand attribute added", "ops_1"))

    listing = _listing(world["listing"]["id"])
    assert listing["syndication_state"] == "NOT_SYNDICATED"
    assert listing["open_blocking_error_count"] == 0
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)


def test_closing_an_already_closed_row_a_second_time_is_refused(bigbox_world):
    """The row is terminal after the first close, so a second operator repeating the same
    FIX is told the row is already closed rather than being allowed to overwrite it.

    PRD 3.7: "The row must be in `OPEN`, otherwise the attempt is `ERR_REJECTION_ERROR_ALREADY_CLOSED`."
    Design: Corner/errors/resolving_an_already_closed_rejection_row_returns_409
    """
    world = bigbox_world
    _job, row = _rejected_with_one_blocking_row(world)
    validate_success(_resolve(row["id"], "brand attribute added", "ops_1"))

    response = _resolve(row["id"], "adding brand again", "ops_2")
    validate_error(response, ApiErrorId.ERR_REJECTION_ERROR_ALREADY_CLOSED.value, 409)


def test_the_refused_second_close_neither_rewrote_the_row_nor_re_ran_the_cascade(bigbox_world):
    """The row still names the first operator and the first note, and no downstream figure
    moved a second time: readiness stays where the first close left it and the retailer's
    version still counts only the queue and the rejection.

    PRD 3.7: "The row must be in `OPEN`, otherwise the attempt is `ERR_REJECTION_ERROR_ALREADY_CLOSED`."
    Design: Corner/errors/resolving_an_already_closed_rejection_row_returns_409
    """
    world = bigbox_world
    job, row = _rejected_with_one_blocking_row(world)
    validate_success(_resolve(row["id"], "brand attribute added", "ops_1"))
    _resolve(row["id"], "adding brand again", "ops_2")

    rows, meta = _rejection_rows(job["id"])
    assert meta["total_count"] == 1
    assert rows[0]["state"] == "RESOLVED"
    assert rows[0]["resolved_by_user_id"] == "ops_1"
    assert rows[0]["resolution_note"] == "brand attribute added"

    listing = _listing(world["listing"]["id"])
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)
    assert _retailer(world["retailer"]["id"])["version"] == 3


def _pending_secondary_asset(world):
    """A second image asset on the same product, left in PENDING because nobody has
    approved it."""
    return upload_asset(world["product"]["id"], "SECONDARY_IMAGE", "s3://brand/d/sec1.jpg")


def _attempt_deployment(world, media_asset_id):
    return api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            media_asset_id,
            "A_PLUS_PAGE",
            DEPLOYMENT_WINDOW[0],
            DEPLOYMENT_WINDOW[1],
            read_listing_version(world["listing"]["id"]),
        ),
        make_content_author_headers(),
    )


def _clear_both_review_tracks(world):
    """Legal then brand approve, which is the join that pins the revision onto the
    listing and puts the change request into APPROVED."""
    review_legal(world["change_request"]["id"], world["product"]["id"])
    review_brand(world["change_request"]["id"], world["product"]["id"])


def test_a_deployment_on_a_request_still_in_review_is_refused(simplemart_world_unpinned):
    """The asset is approved and the window is sound, but the governance record has only
    been submitted — one track approved is not the same as the request approved, so the
    placement is refused and the request is left exactly where it was.

    PRD 3.8: "The cited change request must be in `APPROVED`, otherwise `ERR_CHANGE_REQUEST_NOT_APPROVED` — enhanced content rides on governance that has already cleared both review tracks."
    Design: Corner/errors/deployment_needs_an_approved_change_request_and_an_approved_asset
    """
    world = simplemart_world_unpinned
    _pending_secondary_asset(world)

    response = _attempt_deployment(world, world["asset"]["id"])
    validate_error(response, ApiErrorId.ERR_CHANGE_REQUEST_NOT_APPROVED.value, 422)

    change_request = validate_success(
        api_client.get_change_request(
            world["change_request"]["id"], make_content_author_headers()
        )
    )
    assert change_request["state"] == "IN_REVIEW"


def test_a_deployment_citing_an_unapproved_asset_is_refused(simplemart_world_unpinned):
    """With governance cleared the request passes, and the scope check passes too because
    the pending asset belongs to the listing's own product — so the only thing left to
    refuse it is the asset's own approval state.

    PRD 3.8: "The cited asset's `approval_state` must be `APPROVED`, otherwise `ERR_MEDIA_ASSET_NOT_APPROVED`."
    Design: Corner/errors/deployment_needs_an_approved_change_request_and_an_approved_asset
    """
    world = simplemart_world_unpinned
    pending_asset = _pending_secondary_asset(world)
    _clear_both_review_tracks(world)

    response = _attempt_deployment(world, pending_asset["id"])
    validate_error(response, ApiErrorId.ERR_MEDIA_ASSET_NOT_APPROVED.value, 422)


def test_neither_refused_deployment_left_a_placement_or_a_reference(simplemart_world_unpinned):
    """The revision carries exactly one reference — the listing pin the approval join
    created — because no deployment ever came into existence to add a second.

    PRD 2.9: "`ContentVersion.pin_count` is the number of references currently held on a revision, and it counts two different kinds of reference: the number of retailer listings whose `pinned_content_version_id` equals the revision's `id`, plus the number of enhanced-content deployments in state `PENDING_RETAILER_APPROVAL` or `LIVE` whose governing change request's `target_content_version_id` equals that same `id`."
    Design: Corner/errors/deployment_needs_an_approved_change_request_and_an_approved_asset
    """
    world = simplemart_world_unpinned
    pending_asset = _pending_secondary_asset(world)
    _attempt_deployment(world, world["asset"]["id"])
    _clear_both_review_tracks(world)
    _attempt_deployment(world, pending_asset["id"])

    _rows, meta = validate_paginated(
        api_client.list_enhanced_deployments(
            make_content_author_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 0

    assert_pin_ledger(_revision(world["revision"]["id"]), 1)


def test_the_refused_deployments_left_the_listing_version_and_readiness_alone(
    simplemart_world_unpinned,
):
    """Only a created deployment advances the listing, so the version is exactly the one
    the pin left behind and readiness carries no enhanced-content bonus.

    PRD 3.8: "Either way the listing's `version` increments by 1, and the `pin_count` of the revision named by the change request's `target_content_version_id` is recomputed upward, because an active deployment is a second kind of live reference to a revision."
    Design: Corner/errors/deployment_needs_an_approved_change_request_and_an_approved_asset
    """
    world = simplemart_world_unpinned
    pending_asset = _pending_secondary_asset(world)
    _attempt_deployment(world, world["asset"]["id"])
    _clear_both_review_tracks(world)
    version_after_the_pin = read_listing_version(world["listing"]["id"])

    _attempt_deployment(world, pending_asset["id"])

    listing = _listing(world["listing"]["id"])
    assert listing["version"] == version_after_the_pin
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)
