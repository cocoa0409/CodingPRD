"""Validation rules read at their boundaries and in their pinned order.

Each test drives a request that breaks a specific rule — sometimes two rules at
once — and then re-reads the neighbouring rows so that the refusal is shown to be
a complete no-op as well as the right error.
"""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_content_attribute_value,
    assert_rejection_error,
    assert_slot_ledger,
)
from test_helpers.constants import CLOCK_BASE
from test_helpers.factories import (
    create_attribute_value_payload,
    create_deployment_payload,
    create_retailer_payload,
    create_syndication_job_payload,
    patch_retailer_payload,
    resolve_rejection_error_payload,
    retailer_response_payload,
    review_payload,
)
from test_helpers.fixtures import (
    BIGBOX_TITLE,
    build_bigbox_world,
    define_attribute,
    move_clock,
    queue_job,
    read_listing_version,
    read_product_version,
    read_retailer_version,
    register_product,
    reject_job,
    start_revision,
    transmit_job,
    upload_asset,
)
from test_helpers.test_users import (
    make_content_author_headers,
    make_retailer_integration_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

# A request that carries a body but no identity at all.
NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}

ONE_CHAR_OVER_THE_CEILING = BIGBOX_TITLE + "X"

MIXED_SEVERITY_ROWS = [
    {
        "retailer_error_code": "E-BRAND-MISSING",
        "attribute_key": "brand",
        "severity": "BLOCKING",
        "message": "brand attribute is required",
    },
    {
        "retailer_error_code": "E-DESC-STYLE",
        "attribute_key": "description",
        "severity": "WARNING",
        "message": "description style nit",
    },
]

UNKNOWN_KEY_ROWS = [
    {
        "retailer_error_code": "E-BRAND-MISSING",
        "attribute_key": "brand",
        "severity": "BLOCKING",
        "message": "brand attribute is required",
    },
    {
        "retailer_error_code": "E-BULLET",
        "attribute_key": "bullet_1",
        "severity": "BLOCKING",
        "message": "bullet_1 is missing",
    },
]


def _build_ceiling_world():
    """A taxonomy holding a single `title` attribute with a deliberately tight
    27-character ceiling, and a bare DRAFT revision to write it on."""
    move_clock(CLOCK_BASE)
    attribute = define_attribute("title", "STRING", "CORE", 27, 40.00, True)
    product = register_product("SKU-L-1", "00012345679049")
    revision = start_revision(product["id"], 1)
    return {"attribute": attribute, "product": product, "revision": revision}


def _rejected_bigbox_job(world, rows):
    """Queue four slots into a far window, transmit, and let BigBox answer with the
    supplied error rows."""
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        4,
        "2026-08-15T00:00:00Z",
        "2026-08-16T00:00:00Z",
        world["retailer"]["id"],
    )
    transmit_job(job["id"])
    reject_job(job["id"], world["retailer"]["id"], rows)
    return job


def _rejection_rows_of(job_id):
    rows, _meta = validate_paginated(
        api_client.list_rejection_errors(job_id, make_syndication_operator_headers())
    )
    return rows


def _waive(rejection_error_id, note, headers):
    return api_client.resolve_rejection_error(
        rejection_error_id, resolve_rejection_error_payload("WAIVE", note), headers
    )


def _read_listing(listing_id):
    return validate_success(
        api_client.get_retailer_listing(listing_id, make_shelf_admin_headers())
    )


def test_a_write_with_no_role_header_is_unauthenticated_rather_than_unauthorized(
    clock_at_base,
):
    """Onboarding a retailer is a ShelfAdmin-only write, so a caller with no
    identity breaks the role list too; the header check answers first with 401 and
    the roster is left empty.

    PRD 2.8: "Both headers present and `X-User-Role` one of the seven declared roles — otherwise `ERR_UNAUTHENTICATED`."
    Design: Corner/validations/missing_role_header_returns_unauthenticated_before_authorization
    """
    response = api_client.create_retailer(
        create_retailer_payload(name="HeaderlessMart", retailer_code="RETH"),
        NO_IDENTITY_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    _retailers, meta = validate_paginated(api_client.list_retailers(make_shelf_admin_headers()))
    assert meta["total_count"] == 0


def test_a_content_author_deciding_a_review_track_is_refused_as_unauthorized(
    simplemart_world_unpinned,
):
    """The author's colleague names the LEGAL track, which no ContentAuthor could
    ever own; the endpoint's role list is consulted before the track is compared to
    the caller, so the answer is 403 ERR_UNAUTHORIZED and both tracks stay PENDING.

    PRD 2.8: "The acting role is authorised for the endpoint — otherwise `ERR_UNAUTHORIZED`."
    Design: Corner/validations/content_author_on_reviews_returns_unauthorized_not_track_mismatch
    """
    world = simplemart_world_unpinned
    expected_product_version = read_product_version(world["product"]["id"])
    assert expected_product_version == 1

    response = api_client.create_review(
        world["change_request"]["id"],
        review_payload("LEGAL", "APPROVED", expected_product_version),
        make_content_author_headers("author_2"),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    change_request = validate_success(
        api_client.get_change_request(
            world["change_request"]["id"], make_content_author_headers()
        )
    )
    assert change_request["legal_review_state"] == "PENDING"
    assert change_request["brand_review_state"] == "PENDING"
    assert change_request["state"] == "IN_REVIEW"
    assert read_product_version(world["product"]["id"]) == 1


def test_a_body_missing_its_retailer_id_is_refused_before_the_product_lookup(clock_at_base):
    """The listing payload omits the required retailer_id and names a product that
    does not exist either; body shape is checked before any reference is resolved,
    so the caller is told the request is invalid rather than that the product is
    missing.

    PRD 2.8: "Request-body shape: every required field present, types matching their declarations, every enum value a member of its declared set, and no decimal negative where the field forbids it — otherwise `ERR_INVALID_REQUEST`."
    Design: Corner/validations/missing_retailer_id_returns_invalid_request_before_product_not_found
    """
    response = api_client.create_retailer_listing(
        {"product_id": NON_EXISTENT_UUID}, make_content_author_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_transmitting_an_unknown_job_is_a_not_found_rather_than_a_state_error(clock_at_base):
    """Transmission requires a QUEUED job, but a job that was never created cannot
    have a state to inspect; existence is resolved first, so the answer is 404.

    PRD 2.8: "The referenced syndication job exists — otherwise `ERR_SYNDICATION_JOB_NOT_FOUND`."
    Design: Corner/validations/transmit_on_an_unknown_job_returns_not_found_before_the_state_check
    """
    response = api_client.transmit_syndication_job(
        NON_EXISTENT_UUID, {}, make_syndication_operator_headers()
    )
    validate_error(response, ApiErrorId.ERR_SYNDICATION_JOB_NOT_FOUND.value, 404)


def test_a_stale_retailer_version_answers_before_the_paused_retailer_check(bigbox_world):
    """The admin's pause bumped the retailer's version, so the operator's queue
    attempt is simultaneously stale and aimed at a non-ACTIVE retailer; the
    concurrency field is compared first and the caller gets 412.

    PRD 2.8: "The supplied concurrency field equals the current `version` of its named parent — otherwise `ERR_STALE_VERSION`."
    Design: Corner/validations/stale_retailer_version_returns_412_before_the_paused_retailer_check
    """
    world = bigbox_world
    version_the_operator_holds = read_retailer_version(world["retailer"]["id"])
    assert version_the_operator_holds == 1

    paused = validate_success(
        api_client.patch_retailer(
            world["retailer"]["id"],
            patch_retailer_payload(version_the_operator_holds, status="PAUSED"),
            make_shelf_admin_headers(),
        )
    )
    assert paused["status"] == "PAUSED"
    assert paused["version"] == 2

    response = api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            4,
            "2026-08-15T00:00:00Z",
            "2026-08-16T00:00:00Z",
            version_the_operator_holds,
        ),
        make_syndication_operator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    _jobs, meta = validate_paginated(
        api_client.list_syndication_jobs(make_syndication_operator_headers())
    )
    assert meta["total_count"] == 0

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert retailer["status"] == "PAUSED"
    assert retailer["version"] == 2
    assert_slot_ledger(retailer, 0)


def _bigbox_with_a_raised_image_minimum():
    """BigBox onboarded with a feed capacity of only 2, then re-envelope: raising
    min_image_count from 4 to 5 leaves the three approved assets short and drags the
    certified score under the queue gate."""
    world = build_bigbox_world(feed_slot_capacity=2)
    validate_success(
        api_client.patch_retailer(
            world["retailer"]["id"],
            patch_retailer_payload(
                read_retailer_version(world["retailer"]["id"]), min_image_count=5
            ),
            make_shelf_admin_headers(),
        )
    )
    return world


def test_raising_the_image_minimum_pulls_both_completeness_variants_down():
    """Three approved assets against a minimum of five earn three fifths of the
    image weight, so certified lands on 82.00 while the declared variant — which
    counts the revision's claimed four images — lands on 86.00 and readiness falls
    to 49.20.

    PRD 3.4: "Given a count, the image component is the full image weight of 20 when the retailer's `min_image_count` is zero; otherwise it is 20 multiplied by the smaller of 1 and the ratio of the count to `min_image_count`."
    Design: Corner/validations/completeness_gate_returns_422_before_the_capacity_check
    """
    world = _bigbox_with_a_raised_image_minimum()

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert retailer["min_image_count"] == 5
    assert retailer["version"] == 2

    listing = _read_listing(world["listing"]["id"])
    assert float(listing["completeness_score_certified"]) == pytest.approx(82.00, abs=0.01)
    assert float(listing["completeness_score_declared"]) == pytest.approx(86.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(49.20, abs=0.01)


def test_the_completeness_gate_answers_before_the_capacity_guard():
    """The four-slot request breaks the 85.00 completeness gate and the two-slot
    capacity at the same moment; completeness is the earlier guard, so the caller is
    told the content is not certified enough and no slot is reserved.

    PRD 2.8: "The listing's certified completeness score is at least 85.00 — otherwise `ERR_COMPLETENESS_BELOW_THRESHOLD` (HTTP 422)."
    Design: Corner/validations/completeness_gate_returns_422_before_the_capacity_check
    """
    world = _bigbox_with_a_raised_image_minimum()
    retailer_version = read_retailer_version(world["retailer"]["id"])
    assert retailer_version == 2

    response = api_client.create_syndication_job(
        create_syndication_job_payload(
            world["listing"]["id"],
            world["revision"]["id"],
            4,
            "2026-08-15T00:00:00Z",
            "2026-08-16T00:00:00Z",
            retailer_version,
        ),
        make_syndication_operator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_COMPLETENESS_BELOW_THRESHOLD.value, 422)

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert retailer["feed_slot_capacity"] == 2
    assert_slot_ledger(retailer, 0)


def test_an_attribute_value_landing_exactly_on_the_ceiling_is_accepted():
    """A 27-character value against a 27-character ceiling satisfies "at most" and
    is stored, with the derived char_count sitting exactly on the limit and the
    string parsing cleanly as the declared STRING type.

    PRD 3.2: "A length screen then requires `char_count` to be at most the `max_chars` declared on the taxonomy attribute, rejecting with `ERR_ATTRIBUTE_LENGTH_EXCEEDED` otherwise."
    Design: Corner/validations/attribute_value_exactly_at_the_global_ceiling_passes_then_one_char_over_fails
    """
    world = _build_ceiling_world()
    assert len(BIGBOX_TITLE) == 27

    stored = validate_success(
        api_client.create_attribute_value(
            world["revision"]["id"],
            create_attribute_value_payload("title", BIGBOX_TITLE),
            make_content_author_headers(),
        ),
        201,
    )
    assert_content_attribute_value(stored)
    assert stored["char_count"] == 27
    assert stored["type_valid"] is True
    assert stored["value"] == BIGBOX_TITLE


def test_one_character_past_the_ceiling_is_refused_and_leaves_the_stored_row_alone():
    """The 28-character value is one character past the same ceiling and is refused;
    because the write is an upsert, the refusal has to leave the accepted 27-character
    row exactly as it was rather than replacing it.

    PRD 2.8: "The stripped attribute value's `char_count` is at most the global taxonomy ceiling — otherwise `ERR_ATTRIBUTE_LENGTH_EXCEEDED` (HTTP 422)."
    Design: Corner/validations/attribute_value_exactly_at_the_global_ceiling_passes_then_one_char_over_fails
    """
    world = _build_ceiling_world()
    validate_success(
        api_client.create_attribute_value(
            world["revision"]["id"],
            create_attribute_value_payload("title", BIGBOX_TITLE),
            make_content_author_headers(),
        ),
        201,
    )
    assert len(ONE_CHAR_OVER_THE_CEILING) == 28

    response = api_client.create_attribute_value(
        world["revision"]["id"],
        create_attribute_value_payload("title", ONE_CHAR_OVER_THE_CEILING),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_ATTRIBUTE_LENGTH_EXCEEDED.value, 422)

    rows, meta = validate_paginated(
        api_client.list_attribute_values(world["revision"]["id"], make_content_author_headers())
    )
    assert meta["total_count"] == 1
    assert rows[0]["value"] == BIGBOX_TITLE
    assert rows[0]["char_count"] == 27


def test_an_operator_may_waive_the_warning_row_without_moving_the_blocking_count(bigbox_world):
    """The retailer answered with one BLOCKING row and one WARNING row; waiving the
    warning is inside the operator's authority, and because only BLOCKING rows are
    counted the listing keeps its single open blocking error and its 5-point penalty.

    PRD 3.7: "The `open_blocking_error_count` a listing carries is the number of rejection errors with `severity` `BLOCKING` and `state` `OPEN` across every syndication job of that listing, not merely the most recent one."
    Design: Corner/validations/waive_of_a_blocking_row_is_permitted_only_for_shelf_admin
    """
    world = bigbox_world
    job = _rejected_bigbox_job(world, MIXED_SEVERITY_ROWS)
    rows = _rejection_rows_of(job["id"])
    assert rows[0]["severity"] == "BLOCKING"
    assert rows[1]["severity"] == "WARNING"

    waived = validate_success(
        _waive(
            rows[1]["id"],
            "style nit accepted for this launch",
            make_syndication_operator_headers("ops_1"),
        )
    )
    assert_rejection_error(waived)
    assert waived["state"] == "WAIVED"
    assert waived["resolution_mode"] == "WAIVE"
    assert waived["resolved_by_user_id"] == "ops_1"

    listing = _read_listing(world["listing"]["id"])
    assert listing["open_blocking_error_count"] == 1
    assert float(listing["readiness_score"]) == pytest.approx(46.00, abs=0.01)


def test_the_same_waiver_against_the_blocking_row_is_refused_to_the_operator(bigbox_world):
    """resolution_mode WAIVE is not illegal in itself — the operator just used it
    successfully on the warning row — but against a BLOCKING row it is reserved to
    the ShelfAdmin, so the operator is refused and the row stays OPEN.

    PRD 3.7: "A `SyndicationOperator` may `FIX` any row and may `WAIVE` a `WARNING` row, but a `WAIVE` against a row whose `severity` is `BLOCKING` is reserved to `ShelfAdmin` and otherwise fails with `ERR_WAIVE_NOT_PERMITTED`."
    Design: Corner/validations/waive_of_a_blocking_row_is_permitted_only_for_shelf_admin
    """
    world = bigbox_world
    job = _rejected_bigbox_job(world, MIXED_SEVERITY_ROWS)
    blocking_row = _rejection_rows_of(job["id"])[0]

    response = _waive(
        blocking_row["id"],
        "operator tries to waive a blocking row",
        make_syndication_operator_headers("ops_1"),
    )
    validate_error(response, ApiErrorId.ERR_WAIVE_NOT_PERMITTED.value, 403)

    still_open = [
        row for row in _rejection_rows_of(job["id"]) if row["id"] == blocking_row["id"]
    ][0]
    assert still_open["state"] == "OPEN"
    assert still_open["resolved_by_user_id"] is None
    assert _read_listing(world["listing"]["id"])["open_blocking_error_count"] == 1


def test_the_shelf_admin_waiver_clears_the_last_blocking_row_and_lifts_the_hold(bigbox_world):
    """The admin's waiver closes the row the operator could not, and a waived
    blocking row stops blocking exactly as a fixed one would: the count reaches zero,
    no job is holding slots, so the listing falls back to NOT_SYNDICATED at an
    unpenalised 51.00 and leaves the product's health input set empty.

    PRD 3.7: "When the closing call takes `open_blocking_error_count` to zero and no job of the listing is in `QUEUED` or `TRANSMITTED`, the listing's `syndication_state` moves `ERROR_HOLD → NOT_SYNDICATED` and its readiness is recomputed with no penalty at all, which in turn changes whether the listing qualifies for the product's health input set."
    Design: Corner/validations/waive_of_a_blocking_row_is_permitted_only_for_shelf_admin
    """
    world = bigbox_world
    job = _rejected_bigbox_job(world, MIXED_SEVERITY_ROWS)
    rows = _rejection_rows_of(job["id"])
    validate_success(
        _waive(
            rows[1]["id"],
            "style nit accepted for this launch",
            make_syndication_operator_headers("ops_1"),
        )
    )

    admin_waiver = validate_success(
        _waive(
            rows[0]["id"],
            "admin waives after retailer confirmation",
            make_shelf_admin_headers("admin_1"),
        )
    )
    assert admin_waiver["state"] == "WAIVED"
    assert admin_waiver["resolved_by_user_id"] == "admin_1"

    listing = _read_listing(world["listing"]["id"])
    assert listing["open_blocking_error_count"] == 0
    assert listing["syndication_state"] == "NOT_SYNDICATED"
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert float(product["shelf_health_index"]) == pytest.approx(0.00, abs=0.01)


def test_a_deployment_citing_a_foreign_asset_is_a_scope_mismatch_not_an_approval_failure(
    simplemart_world,
):
    """The cited hero shot belongs to a second product and has never been approved,
    so two deployment guards are broken at once; scope is compared before approval
    state, and the refusal leaves the placement calendar, the pin ledger and the
    asset itself untouched.

    PRD 2.8: "The cited change request's retailer and product both match the target listing, and the cited media asset's product matches it too — otherwise `ERR_DEPLOYMENT_SCOPE_MISMATCH` (HTTP 422)."
    Design: Corner/validations/deployment_scope_mismatch_returns_422_before_the_asset_approval_check
    """
    world = simplemart_world
    other_product = register_product("SKU-D-2", "00012345679056")
    foreign_asset = upload_asset(
        other_product["id"], "HERO_IMAGE", "s3://brand/d2/hero.jpg"
    )
    assert foreign_asset["approval_state"] == "PENDING"

    response = api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            foreign_asset["id"],
            "COMPARISON_CHART",
            "2026-08-12T00:00:00Z",
            "2026-08-13T00:00:00Z",
            read_listing_version(world["listing"]["id"]),
        ),
        make_content_author_headers("author_1"),
    )
    validate_error(response, ApiErrorId.ERR_DEPLOYMENT_SCOPE_MISMATCH.value, 422)

    _deployments, meta = validate_paginated(
        api_client.list_enhanced_deployments(
            make_content_author_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 0

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["pin_count"] == 1

    listing = _read_listing(world["listing"]["id"])
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)

    asset = validate_success(
        api_client.get_media_asset(foreign_asset["id"], make_content_author_headers())
    )
    assert asset["approval_state"] == "PENDING"


def test_a_deployment_below_the_approved_image_minimum_is_refused(bigbox_world):
    """The revision claims four images but only three of the product's assets are
    actually approved, and it is the approved library that the minimum is measured
    against, so BigBox's minimum of four refuses the deployment.

    PRD 2.8: "The count of approved image-role assets on the product is at least the retailer's `min_image_count` — otherwise `ERR_IMAGE_COUNT_BELOW_MINIMUM` (HTTP 422)."
    Design: Corner/validations/deployment_below_the_approved_image_minimum_returns_422
    """
    world = bigbox_world
    response = api_client.create_enhanced_deployment(
        create_deployment_payload(
            world["listing"]["id"],
            world["change_request"]["id"],
            world["assets"][0]["id"],
            "A_PLUS_PAGE",
            "2026-08-12T00:00:00Z",
            "2026-08-13T00:00:00Z",
            read_listing_version(world["listing"]["id"]),
        ),
        make_content_author_headers("author_1"),
    )
    validate_error(response, ApiErrorId.ERR_IMAGE_COUNT_BELOW_MINIMUM.value, 422)

    _assets, meta = validate_paginated(
        api_client.list_media_assets(
            make_content_author_headers(),
            params={"product_id": world["product"]["id"], "approval_state": "APPROVED"},
        )
    )
    assert meta["total_count"] == 3

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert retailer["min_image_count"] == 4

    revision = validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )
    assert revision["image_count"] == 4
    assert revision["pin_count"] == 1

    listing = _read_listing(world["listing"]["id"])
    assert float(listing["readiness_score"]) == pytest.approx(51.00, abs=0.01)


def test_one_unknown_attribute_key_in_the_errors_array_rejects_the_whole_response(bigbox_world):
    """The retailer's rejection carries a well-formed brand complaint followed by a
    complaint about an attribute the taxonomy has never heard of; every supplied key
    is resolved before anything is written, so not even the valid first row survives
    and the transmission is left standing with its slots still reserved.

    PRD 2.8: "Every supplied `attribute_key` resolves to a row in the global taxonomy — otherwise `ERR_ATTRIBUTE_KEY_UNKNOWN` (HTTP 422)."
    Design: Corner/validations/unknown_attribute_key_inside_the_errors_array_rejects_the_whole_response
    """
    world = bigbox_world
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        4,
        "2026-08-15T00:00:00Z",
        "2026-08-16T00:00:00Z",
        world["retailer"]["id"],
    )
    transmit_job(job["id"])

    response = api_client.retailer_response(
        job["id"],
        retailer_response_payload("REJECTED", UNKNOWN_KEY_ROWS),
        make_retailer_integration_headers(world["retailer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ATTRIBUTE_KEY_UNKNOWN.value, 422)

    _rows, meta = validate_paginated(
        api_client.list_rejection_errors(job["id"], make_syndication_operator_headers())
    )
    assert meta["total_count"] == 0

    unchanged = validate_success(
        api_client.get_syndication_job(job["id"], make_syndication_operator_headers())
    )
    assert unchanged["state"] == "TRANSMITTED"
    assert unchanged["responded_at"] is None

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 4)

    listing = _read_listing(world["listing"]["id"])
    assert listing["syndication_state"] == "PENDING"
    assert listing["open_blocking_error_count"] == 0
