"""Seven roles, seven exclusive slices of the write surface, one shared read surface —
and the four refusals that keep the slices apart."""
import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_slot_ledger
from test_helpers.factories import (
    create_media_asset_payload,
    create_observation_payload,
    create_product_payload,
    create_retailer_payload,
    media_decision_payload,
    resolve_alert_payload,
    retailer_response_payload,
    review_payload,
    shelf_status_payload,
)
from test_helpers.fixtures import (
    accept_job,
    ingest_observation,
    queue_job,
    read_product_version,
    register_retailer,
    transmit_job,
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

FIRST_WINDOW = ("2026-08-15T00:00:00Z", "2026-08-16T00:00:00Z")
MISSING_JOB_ID = "88888888-8888-4888-8888-888888888888"
BIGBOX_ACCOUNT_TEAM = "acct_bigbox_1"


def _listing(retailer_listing_id):
    return validate_success(
        api_client.get_retailer_listing(retailer_listing_id, make_shelf_admin_headers())
    )


def _product(product_id):
    return validate_success(api_client.get_product(product_id, make_shelf_admin_headers()))


def _change_request(change_request_id, headers):
    return validate_success(api_client.get_change_request(change_request_id, headers))


def _job(job_id):
    return validate_success(
        api_client.get_syndication_job(job_id, make_syndication_operator_headers())
    )


def _queued_and_transmitted_job(world):
    """The operator's own two-step: a four-slot job queued into the retailer's window and
    then handed to the retailer."""
    job = queue_job(
        world["listing"]["id"],
        world["revision"]["id"],
        4,
        FIRST_WINDOW[0],
        FIRST_WINDOW[1],
        world["retailer"]["id"],
    )
    transmit_job(job["id"])
    return job


def _live_listing_with_an_unauthorized_crawl(world):
    """The feed is confirmed, so the listing is LIVE, and a crawl showing two unauthorized
    sellers puts it on UNAUTHORIZED and raises the alert the account team owns."""
    job = _queued_and_transmitted_job(world)
    accept_job(job["id"], world["retailer"]["id"])
    ingest_observation(
        world["listing"]["id"],
        "2026-08-11T00:00:00Z",
        unauthorized_seller_count=2,
        search_rank=3,
    )
    return job


def _unauthorized_alert(world):
    rows, meta = validate_paginated(
        api_client.list_shelf_alerts(
            make_retailer_integration_headers(world["retailer"]["id"]),
            params={
                "retailer_listing_id": world["listing"]["id"],
                "alert_type": "UNAUTHORIZED_LISTING",
                "state": "OPEN",
            },
        )
    )
    assert meta["total_count"] == 1
    return rows[0]


def test_the_shelf_admin_owns_the_roster_the_taxonomy_and_the_crawl_feed(bigbox_world):
    """All three of those surfaces answer to the platform operator: the roster row and the
    three taxonomy attributes it onboarded are readable back, and it is the admin — nobody
    else — who lands a crawl observation on a listing.

    PRD 2.1: "It owns the retailer roster, the global attribute taxonomy, the crawl ingestion feed, the logical clock, and the sole authority to waive a blocking feed error."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world

    _retailers, retailer_meta = validate_paginated(
        api_client.list_retailers(make_shelf_admin_headers())
    )
    assert retailer_meta["total_count"] == 1

    _attributes, attribute_meta = validate_paginated(
        api_client.list_attribute_definitions(make_shelf_admin_headers())
    )
    assert attribute_meta["total_count"] == 3

    observation = get_success_data(
        api_client.create_observation(
            world["listing"]["id"],
            create_observation_payload(observed_at="2026-08-11T00:00:00Z", search_rank=3),
            make_shelf_admin_headers(),
        )
    )
    assert observation["retailer_listing_id"] == world["listing"]["id"]

    _rows, observation_meta = validate_paginated(
        api_client.list_observations(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert observation_meta["total_count"] == 1


def test_the_content_author_owns_the_product_the_media_and_the_revision(bigbox_world):
    """The author's slice covers registration through authoring: a fourth media asset goes
    up on its own authority, and the product and revision it already created read back.

    PRD 2.1: "A `ContentAuthor` registers products, drafts content revisions and attribute values, registers rich media, opens retailer listings, raises and submits change requests, and deploys and withdraws enhanced content."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world

    asset = get_success_data(
        api_client.create_media_asset(
            create_media_asset_payload(
                world["product"]["id"],
                asset_role="SECONDARY_IMAGE",
                source_uri="s3://brand/b/sec3.jpg",
            ),
            make_content_author_headers(),
        )
    )
    assert asset["approval_state"] == "PENDING"

    _products, product_meta = validate_paginated(
        api_client.list_products(make_content_author_headers())
    )
    assert product_meta["total_count"] == 1

    _revisions, revision_meta = validate_paginated(
        api_client.list_content_versions(
            make_content_author_headers(), params={"product_id": world["product"]["id"]}
        )
    )
    assert revision_meta["total_count"] == 1


def test_the_legal_reviewer_decided_the_legal_track_and_is_recorded_on_it(bigbox_world):
    """The LEGAL dimension carries the legal reviewer's own identity and nothing from the
    brand side.

    PRD 2.1: "A `LegalReviewer` decides the `LEGAL` review track of a change request and nothing else."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world
    change_request = _change_request(
        world["change_request"]["id"], make_legal_reviewer_headers()
    )
    assert change_request["legal_review_state"] == "APPROVED"
    assert change_request["legal_reviewer_user_id"] == "legal_1"


def test_the_brand_approver_decided_the_brand_track_and_closed_the_request(bigbox_world):
    """The second dimension is decided by the brand role, and only once both are in does
    the aggregate request reach APPROVED.

    PRD 2.1: "A `BrandGovernanceApprover` decides the `BRAND` review track of a change request and nothing else."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world
    change_request = _change_request(
        world["change_request"]["id"], make_brand_approver_headers()
    )
    assert change_request["brand_review_state"] == "APPROVED"
    assert change_request["brand_reviewer_user_id"] == "brand_1"
    assert change_request["state"] == "APPROVED"


def test_the_syndication_operator_queues_and_transmits_the_feed(bigbox_world):
    """Both hops of the outbound feed belong to the operator, and the slot ledger follows
    the job it created.

    PRD 2.1: "A `SyndicationOperator` queues, transmits, requeues and cancels syndication jobs, and resolves rejection errors by fixing content."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world
    job = _queued_and_transmitted_job(world)

    assert _job(job["id"])["state"] == "TRANSMITTED"
    assert_slot_ledger(
        validate_success(
            api_client.get_retailer(world["retailer"]["id"], make_syndication_operator_headers())
        ),
        4,
    )


def test_the_retailer_integration_account_confirms_its_own_transmitted_feed(bigbox_world):
    """The confirmation is the retailer's own act, made with the retailer's id as the acting
    principal, and it takes the listing live.

    PRD 2.1: "It confirms or rejects transmitted feeds and approves rich media and enhanced-content modules for its own listings."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world
    job = _queued_and_transmitted_job(world)

    accepted = validate_success(
        api_client.retailer_response(
            job["id"],
            retailer_response_payload("ACCEPTED"),
            make_retailer_integration_headers(world["retailer"]["id"]),
        )
    )
    assert accepted["state"] == "ACCEPTED"
    assert _listing(world["listing"]["id"])["syndication_state"] == "LIVE"


def test_the_account_team_lead_acknowledges_the_alert_it_owns(bigbox_world):
    """Acknowledgement is the account team's act and records the acting lead, while the
    product's open follow-up count deliberately stays where it was.

    PRD 3.9: "Acknowledging one moves it `OPEN → ACKNOWLEDGED` and records `acknowledged_by_user_id` from the acting `X-User-ID`; the product's `open_alert_count` is deliberately **unchanged**, because an acknowledged alert is still open follow-up."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world
    _live_listing_with_an_unauthorized_crawl(world)
    alert = _unauthorized_alert(world)

    acknowledged = validate_success(
        api_client.acknowledge_shelf_alert(
            alert["id"], {}, make_account_team_headers(BIGBOX_ACCOUNT_TEAM)
        )
    )
    assert acknowledged["state"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_by_user_id"] == BIGBOX_ACCOUNT_TEAM
    assert _product(world["product"]["id"])["open_alert_count"] == 1


def test_the_account_team_lead_resolves_the_alert_it_acknowledged(bigbox_world):
    """Resolution is terminal, carries the note the lead supplied, and is what finally
    drops the product's open follow-up count.

    PRD 3.9: "Resolving one is permitted from `OPEN` or from `ACKNOWLEDGED`, moves it to the terminal `RESOLVED`, records the supplied `resolution_note`, stamps `resolved_at` from the logical clock, then recomputes the product's `open_alert_count` downward and its `governance_flag`, and increments the product's `version` by 1."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world
    _live_listing_with_an_unauthorized_crawl(world)
    alert = _unauthorized_alert(world)
    validate_success(
        api_client.acknowledge_shelf_alert(
            alert["id"], {}, make_account_team_headers(BIGBOX_ACCOUNT_TEAM)
        )
    )

    resolved = validate_success(
        api_client.resolve_shelf_alert(
            alert["id"],
            resolve_alert_payload("grey-market seller removed by the marketplace"),
            make_account_team_headers(BIGBOX_ACCOUNT_TEAM),
        )
    )
    assert resolved["state"] == "RESOLVED"
    assert resolved["resolution_note"] == "grey-market seller removed by the marketplace"

    product = _product(world["product"]["id"])
    assert product["open_alert_count"] == 0
    assert product["governance_flag"] == "NONE"


def test_the_account_team_lead_clears_the_listing_back_to_ok(bigbox_world):
    """The suspend-or-clear decision is the account team's too. Clearing leaves the live
    feed alone and lifts the accuracy floor, so readiness climbs from 75.00 to 89.00.

    PRD 3.9: "Clearing to `OK` is permitted from `UNAUTHORIZED`, `OOS_WATCH` or `SUSPENDED`, leaves `syndication_state` untouched, and resolves every `UNAUTHORIZED_LISTING` alert of the listing still in `OPEN` or `ACKNOWLEDGED` with `resolution_note` set to the literal string `AUTO_CLEARED_BY_ACCOUNT_TEAM`; it then recomputes the listing's `readiness_score`, the product's `open_alert_count` and `governance_flag`, and increments the product's `version` by 1."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world
    _live_listing_with_an_unauthorized_crawl(world)

    cleared = validate_success(
        api_client.set_shelf_status(
            world["listing"]["id"],
            shelf_status_payload("OK"),
            make_account_team_headers(BIGBOX_ACCOUNT_TEAM),
        )
    )
    assert cleared["shelf_state"] == "OK"
    assert cleared["syndication_state"] == "LIVE"
    assert float(cleared["readiness_score"]) == pytest.approx(89.00, abs=0.01)


def test_the_listing_read_is_open_to_all_seven_roles(bigbox_world):
    """Every role, including the retailer's own integration account, can read the listing:
    the read surface is shared even though every write above was exclusive.

    PRD 2.1: "Read operations under `/digital-shelf` are open to all seven roles."
    Design: Corner/rbac/every_role_can_perform_its_own_exclusive_operations
    """
    world = bigbox_world
    for headers in (
        make_shelf_admin_headers(),
        make_content_author_headers(),
        make_legal_reviewer_headers(),
        make_brand_approver_headers(),
        make_syndication_operator_headers(),
        make_retailer_integration_headers(world["retailer"]["id"]),
        make_account_team_headers(BIGBOX_ACCOUNT_TEAM),
    ):
        listing = validate_success(
            api_client.get_retailer_listing(world["listing"]["id"], headers)
        )
        assert listing["id"] == world["listing"]["id"]


def test_a_content_author_cannot_onboard_a_retailer(simplemart_world_unpinned):
    """The roster is the platform operator's alone, so the author's attempt is refused on
    the role check and no RogueMart row appears.

    PRD 2.1: "If the headers are well-formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    Design: Corner/rbac/another_roles_exclusive_operation_returns_unauthorized
    """
    response = api_client.create_retailer(
        create_retailer_payload(name="RogueMart", retailer_code="RETX", status="ACTIVE"),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    rows, meta = validate_paginated(api_client.list_retailers(make_shelf_admin_headers()))
    assert meta["total_count"] == 1
    assert [row["name"] for row in rows] == ["SimpleMart"]


def test_a_shelf_admin_cannot_register_a_product(simplemart_world_unpinned):
    """Owning the platform does not include owning the catalogue: product registration is
    the author's write, and the admin is refused it.

    PRD 2.1: "Every write is scoped to the role that owns the operation, as enumerated in §4."
    Design: Corner/rbac/another_roles_exclusive_operation_returns_unauthorized
    """
    response = api_client.create_product(
        create_product_payload(sku="SKU-X-1", gtin="00012345679070"),
        make_shelf_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    _rows, meta = validate_paginated(api_client.list_products(make_shelf_admin_headers()))
    assert meta["total_count"] == 1


def test_a_syndication_operator_cannot_ingest_a_crawl(simplemart_world_unpinned):
    """The crawl feed belongs to the admin, so the operator's observation is refused and
    the listing has no snapshot at all.

    PRD 2.1: "If the headers are well-formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    Design: Corner/rbac/another_roles_exclusive_operation_returns_unauthorized
    """
    world = simplemart_world_unpinned
    response = api_client.create_observation(
        world["listing"]["id"],
        create_observation_payload(
            observed_at="2026-08-11T00:00:00Z", content_accuracy_pct=90.00, rating_count=10
        ),
        make_syndication_operator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    _rows, meta = validate_paginated(
        api_client.list_observations(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert meta["total_count"] == 0


def test_a_syndication_operator_cannot_suspend_a_listing(simplemart_world_unpinned):
    """The suspend-or-clear decision is the account team's, so the operator cannot reach it
    and the listing stays OK.

    PRD 2.1: "Every write is scoped to the role that owns the operation, as enumerated in §4."
    Design: Corner/rbac/another_roles_exclusive_operation_returns_unauthorized
    """
    world = simplemart_world_unpinned
    response = api_client.set_shelf_status(
        world["listing"]["id"],
        shelf_status_payload("SUSPENDED"),
        make_syndication_operator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert _listing(world["listing"]["id"])["shelf_state"] == "OK"


def test_the_role_check_answers_before_the_platform_looks_for_the_job(
    simplemart_world_unpinned,
):
    """Transmission is the operator's write, and the author is turned away on the role check
    before anybody goes looking for the job — which is why an id belonging to no job at all
    still comes back 403 rather than 404.

    PRD 2.8: "The acting role is authorised for the endpoint — otherwise `ERR_UNAUTHORIZED`."
    Design: Corner/rbac/another_roles_exclusive_operation_returns_unauthorized
    """
    response = api_client.transmit_syndication_job(
        MISSING_JOB_ID, {}, make_content_author_headers()
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_a_legal_reviewer_reaching_for_the_brand_track_is_a_track_mismatch(
    simplemart_world_unpinned,
):
    """The reviews endpoint does admit a LegalReviewer, so this is not an authorisation
    failure at all — the refusal comes one rule later, from asking to decide the wrong
    dimension, and neither track records anything.

    PRD 2.8: "On a review-track decision, the acting role matches the requested `track` — otherwise `ERR_TRACK_ROLE_MISMATCH`."
    Design: Corner/rbac/another_roles_exclusive_operation_returns_unauthorized
    """
    world = simplemart_world_unpinned
    response = api_client.create_review(
        world["change_request"]["id"],
        review_payload("BRAND", "APPROVED", read_product_version(world["product"]["id"])),
        make_legal_reviewer_headers(),
    )
    validate_error(response, ApiErrorId.ERR_TRACK_ROLE_MISMATCH.value, 403)

    change_request = _change_request(
        world["change_request"]["id"], make_content_author_headers()
    )
    assert change_request["state"] == "IN_REVIEW"
    assert change_request["legal_review_state"] == "PENDING"
    assert change_request["brand_review_state"] == "PENDING"


def test_every_refused_role_keeps_the_shared_read_surface(simplemart_world_unpinned):
    """Being barred from four writes costs the operator nothing on the read side: the same
    principal reads the listing back without complaint.

    PRD 2.1: "Read operations under `/digital-shelf` are open to all seven roles."
    Design: Corner/rbac/another_roles_exclusive_operation_returns_unauthorized
    """
    world = simplemart_world_unpinned
    api_client.set_shelf_status(
        world["listing"]["id"],
        shelf_status_payload("SUSPENDED"),
        make_syndication_operator_headers(),
    )

    listing = validate_success(
        api_client.get_retailer_listing(
            world["listing"]["id"], make_syndication_operator_headers()
        )
    )
    assert listing["id"] == world["listing"]["id"]


def _decide_track(change_request_id, track, user_headers, expected_product_version):
    return api_client.create_review(
        change_request_id,
        review_payload(track, "APPROVED", expected_product_version),
        user_headers,
    )


def test_the_request_author_cannot_review_their_own_request(simplemart_world_unpinned):
    """author_1 raised the request and now wears the LegalReviewer role — the role is right
    for the track, but the person is the author, so the decision is barred and the track
    stays PENDING.

    PRD 2.8: "On a review-track decision, `X-User-ID` differs from the change request's `author_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/rbac/the_author_and_the_first_reviewer_are_both_barred_from_the_second_track
    """
    world = simplemart_world_unpinned
    response = _decide_track(
        world["change_request"]["id"],
        "LEGAL",
        make_legal_reviewer_headers("author_1"),
        read_product_version(world["product"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    change_request = _change_request(
        world["change_request"]["id"], make_content_author_headers()
    )
    assert change_request["legal_review_state"] == "PENDING"
    assert change_request["legal_reviewer_user_id"] is None


def test_a_distinct_legal_reviewer_decides_the_first_track_on_the_same_version(
    simplemart_world_unpinned,
):
    """The refused attempt consumed nothing, so the very same expected product version is
    still current when legal_1 decides — and one approved track leaves the request itself in
    review.

    PRD 3.5: "When the decision is `APPROVED` and the other track is still `PENDING`, the request's aggregate `state` stays `IN_REVIEW`."
    Design: Corner/rbac/the_author_and_the_first_reviewer_are_both_barred_from_the_second_track
    """
    world = simplemart_world_unpinned
    product_version = read_product_version(world["product"]["id"])
    _decide_track(
        world["change_request"]["id"],
        "LEGAL",
        make_legal_reviewer_headers("author_1"),
        product_version,
    )

    decided = validate_success(
        _decide_track(
            world["change_request"]["id"],
            "LEGAL",
            make_legal_reviewer_headers("legal_1"),
            product_version,
        )
    )
    assert decided["legal_review_state"] == "APPROVED"
    assert decided["legal_reviewer_user_id"] == "legal_1"
    assert decided["state"] == "IN_REVIEW"
    assert decided["brand_review_state"] == "PENDING"


def test_the_legal_reviewer_cannot_also_decide_the_brand_track(simplemart_world_unpinned):
    """legal_1 now wears the BrandGovernanceApprover role, so the track matches the role —
    but the two-person rule refuses the same human on the second dimension, and it is the
    segregation error rather than an already-decided complaint because BRAND is untouched.

    PRD 2.8: "On a review-track decision, `X-User-ID` differs from the other track's already-recorded reviewer — otherwise `ERR_SEGREGATION_OF_DUTIES`."
    Design: Corner/rbac/the_author_and_the_first_reviewer_are_both_barred_from_the_second_track
    """
    world = simplemart_world_unpinned
    _decide_track(
        world["change_request"]["id"],
        "LEGAL",
        make_legal_reviewer_headers("legal_1"),
        read_product_version(world["product"]["id"]),
    )

    response = _decide_track(
        world["change_request"]["id"],
        "BRAND",
        make_brand_approver_headers("legal_1"),
        read_product_version(world["product"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    change_request = _change_request(
        world["change_request"]["id"], make_content_author_headers()
    )
    assert change_request["brand_review_state"] == "PENDING"
    assert change_request["state"] == "IN_REVIEW"


def test_a_third_distinct_user_closes_the_request(simplemart_world_unpinned):
    """Only a third identity gets past both segregation rules, and that decision is the one
    that closes the request.

    PRD 3.5: "The request's `state` becomes `APPROVED` and its `decided_at` is stamped from the logical clock."
    Design: Corner/rbac/the_author_and_the_first_reviewer_are_both_barred_from_the_second_track
    """
    world = simplemart_world_unpinned
    _decide_track(
        world["change_request"]["id"],
        "LEGAL",
        make_legal_reviewer_headers("legal_1"),
        read_product_version(world["product"]["id"]),
    )
    _decide_track(
        world["change_request"]["id"],
        "BRAND",
        make_brand_approver_headers("legal_1"),
        read_product_version(world["product"]["id"]),
    )

    joined = validate_success(
        _decide_track(
            world["change_request"]["id"],
            "BRAND",
            make_brand_approver_headers("brand_1"),
            read_product_version(world["product"]["id"]),
        )
    )
    assert joined["state"] == "APPROVED"
    assert joined["brand_reviewer_user_id"] == "brand_1"
    assert joined["decided_at"].startswith("2026-08-10T00:00:00")


def test_only_the_two_accepted_decisions_advanced_the_product(simplemart_world_unpinned):
    """The join rescores the listing and takes the pin ledger up, and the product's version
    has moved exactly twice — once per accepted decision — because the two refusals wrote
    nothing at all.

    PRD 3.5: "Alongside the four hops, the join recomputes `completeness_score_certified`, `completeness_score_declared` and `readiness_score` on each touched listing, recomputes the newly pinned revision's `pin_count` upward, recomputes the product's `shelf_health_index`, and — like every review decision — stamps `last_review_at` and increments the product's `version`."
    Design: Corner/rbac/the_author_and_the_first_reviewer_are_both_barred_from_the_second_track
    """
    world = simplemart_world_unpinned
    version_before = read_product_version(world["product"]["id"])
    _decide_track(
        world["change_request"]["id"],
        "LEGAL",
        make_legal_reviewer_headers("author_1"),
        version_before,
    )
    _decide_track(
        world["change_request"]["id"],
        "LEGAL",
        make_legal_reviewer_headers("legal_1"),
        version_before,
    )
    after_legal = read_product_version(world["product"]["id"])
    _decide_track(
        world["change_request"]["id"],
        "BRAND",
        make_brand_approver_headers("legal_1"),
        after_legal,
    )
    _decide_track(
        world["change_request"]["id"],
        "BRAND",
        make_brand_approver_headers("brand_1"),
        after_legal,
    )

    listing = _listing(world["listing"]["id"])
    assert float(listing["completeness_score_certified"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)
    assert read_product_version(world["product"]["id"]) == version_before + 2


def _outsider_and_a_transmitted_job(world):
    """A second ACTIVE retailer that carries none of this product, plus a four-slot BigBox
    job already handed to BigBox."""
    outsider = register_retailer(
        "OtherMart",
        "RETO",
        min_image_count=1,
        feed_slot_capacity=4,
        max_concurrent_feed_windows=1,
        enhanced_content_requires_approval=False,
    )
    job = _queued_and_transmitted_job(world)
    return outsider, job


def test_an_outsider_retailer_cannot_confirm_another_retailers_feed(bigbox_world):
    """The payload is exactly the one the owning retailer would send; the only difference is
    who is sending it, and that alone refuses the call and leaves the job in flight.

    PRD 3.7: "Confirmation comes from the retailer's own integration account, acting on a job that is in `TRANSMITTED`; from any other state the attempt is `ERR_INVALID_JOB_STATE`, and from an account whose `X-User-ID` is not the retailer owning the job's listing it is `ERR_RETAILER_SCOPE_VIOLATION`."
    Design: Corner/rbac/retailer_integration_cannot_act_on_another_retailers_resources
    """
    world = bigbox_world
    outsider, job = _outsider_and_a_transmitted_job(world)

    response = api_client.retailer_response(
        job["id"],
        retailer_response_payload("ACCEPTED"),
        make_retailer_integration_headers(outsider["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RETAILER_SCOPE_VIOLATION.value, 403)

    assert _job(job["id"])["state"] == "TRANSMITTED"


def test_an_outsider_retailer_cannot_decide_media_it_does_not_carry(bigbox_world):
    """No listing exists for this product and OtherMart, so OtherMart has no standing to
    reverse the hero image's approval, and the asset keeps BigBox's decision.

    PRD 3.3: "Two guards apply beyond the ordinary state check: the asset must still be `PENDING`, and a `RetailerListing` must already exist for the pair formed by the asset's `product_id` and the acting `X-User-ID` — a retailer that does not carry the product cannot express an opinion on its media, and the attempt is rejected with `ERR_RETAILER_SCOPE_VIOLATION`."
    Design: Corner/rbac/retailer_integration_cannot_act_on_another_retailers_resources
    """
    world = bigbox_world
    outsider, _job_row = _outsider_and_a_transmitted_job(world)
    hero = world["assets"][0]

    response = api_client.decide_media_asset(
        hero["id"],
        media_decision_payload("REJECT"),
        make_retailer_integration_headers(outsider["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RETAILER_SCOPE_VIOLATION.value, 403)

    asset = validate_success(api_client.get_media_asset(hero["id"], make_shelf_admin_headers()))
    assert asset["approval_state"] == "APPROVED"
    assert asset["approving_retailer_id"] == world["retailer"]["id"]


def test_the_two_scope_refusals_touched_neither_retailers_ledger(bigbox_world):
    """The owning retailer still holds the four slots its transmitted job reserved, and the
    outsider — which wrote nothing — is untouched on both counters.

    PRD 2.8: "When the acting role is `RetailerIntegration`, `X-User-ID` equals the retailer that owns the target resource — otherwise `ERR_RETAILER_SCOPE_VIOLATION`."
    Design: Corner/rbac/retailer_integration_cannot_act_on_another_retailers_resources
    """
    world = bigbox_world
    outsider, job = _outsider_and_a_transmitted_job(world)
    api_client.retailer_response(
        job["id"],
        retailer_response_payload("ACCEPTED"),
        make_retailer_integration_headers(outsider["id"]),
    )
    api_client.decide_media_asset(
        world["assets"][0]["id"],
        media_decision_payload("REJECT"),
        make_retailer_integration_headers(outsider["id"]),
    )

    owner = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(owner, 4)
    assert owner["version"] == 2

    other = validate_success(api_client.get_retailer(outsider["id"], make_shelf_admin_headers()))
    assert_slot_ledger(other, 0)
    assert other["version"] == 1


def test_the_owning_retailer_makes_the_identical_call_successfully(bigbox_world):
    """Same endpoint, same payload, different acting identity: from the retailer that owns
    the listing the confirmation lands and the listing goes live.

    PRD 3.7: "On `ACCEPTED` the job reaches its terminal `ACCEPTED` state and the listing's `syndication_state` moves `PENDING → LIVE`."
    Design: Corner/rbac/retailer_integration_cannot_act_on_another_retailers_resources
    """
    world = bigbox_world
    outsider, job = _outsider_and_a_transmitted_job(world)
    api_client.retailer_response(
        job["id"],
        retailer_response_payload("ACCEPTED"),
        make_retailer_integration_headers(outsider["id"]),
    )

    accepted = validate_success(
        api_client.retailer_response(
            job["id"],
            retailer_response_payload("ACCEPTED"),
            make_retailer_integration_headers(world["retailer"]["id"]),
        )
    )
    assert accepted["state"] == "ACCEPTED"
    assert _listing(world["listing"]["id"])["syndication_state"] == "LIVE"


def test_the_owners_confirmation_releases_the_slots_the_outsider_could_not(bigbox_world):
    """Only the real confirmation moves the ledger, and when it does the four slots are
    released in full while the retailer's version advances for the third time.

    PRD 2.9: "Those are the only two holding states; a job that has reached `ACCEPTED`, `PARTIALLY_ACCEPTED`, `REJECTED`, `CANCELLED` or `INVALIDATED` releases its slots entirely."
    Design: Corner/rbac/retailer_integration_cannot_act_on_another_retailers_resources
    """
    world = bigbox_world
    outsider, job = _outsider_and_a_transmitted_job(world)
    api_client.retailer_response(
        job["id"],
        retailer_response_payload("ACCEPTED"),
        make_retailer_integration_headers(outsider["id"]),
    )
    validate_success(
        api_client.retailer_response(
            job["id"],
            retailer_response_payload("ACCEPTED"),
            make_retailer_integration_headers(world["retailer"]["id"]),
        )
    )

    owner = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(owner, 0)
    assert owner["version"] == 3
