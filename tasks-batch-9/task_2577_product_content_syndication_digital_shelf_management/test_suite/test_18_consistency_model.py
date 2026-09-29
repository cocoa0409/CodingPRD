"""Nothing about the approval join is deferred: the reviewer's own 200 already carries the
joined request, and the reads issued straight afterwards — no intervening write, no repeat —
already carry the pin, the two completeness variants, readiness and the pin ledger.
"""
import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers.factories import review_payload
from test_helpers.fixtures import read_product_version
from test_helpers.test_users import (
    make_brand_approver_headers,
    make_content_author_headers,
    make_legal_reviewer_headers,
    make_shelf_admin_headers,
)


def _decide(change_request_id, track, headers, expected_product_version):
    return api_client.create_review(
        change_request_id,
        review_payload(track, "APPROVED", expected_product_version),
        headers,
    )


def _join(world):
    """Approve LEGAL, then BRAND, and hand back the second review's own response together with
    the product version the brand reviewer quoted."""
    _decide(
        world["change_request"]["id"],
        "LEGAL",
        make_legal_reviewer_headers(),
        read_product_version(world["product"]["id"]),
    )
    version_before_brand = read_product_version(world["product"]["id"])
    response = _decide(
        world["change_request"]["id"],
        "BRAND",
        make_brand_approver_headers(),
        version_before_brand,
    )
    return response, version_before_brand


def _listing(retailer_listing_id):
    return validate_success(
        api_client.get_retailer_listing(retailer_listing_id, make_content_author_headers())
    )


def test_the_second_review_response_already_carries_the_joined_request(simplemart_world_unpinned):
    """The reviewer does not have to read the request back to learn that their approval was the
    one that joined it — the cascade runs inside the request that triggered it, so the review's
    own body already reports the terminal state.

    PRD 3.5: "When a decision is `APPROVED` and, after applying it, both `legal_review_state` and `brand_review_state` are `APPROVED`, the request advances `IN_REVIEW → APPROVED` — a terminal state — and a four-hop cascade fires inside the same request."
    Design: Corner/consistency_model/the_join_response_and_the_next_read_already_show_every_derived_field
    """
    world = simplemart_world_unpinned
    response, _version_before_brand = _join(world)

    body = validate_success(response)
    assert body["legal_review_state"] == "APPROVED"
    assert body["brand_review_state"] == "APPROVED"
    assert body["state"] == "APPROVED"


def test_the_first_request_read_after_the_join_shows_the_stamp(simplemart_world_unpinned):
    """The decision stamp is not written by a later sweep: the very next read of the request
    already has it, at the logical clock the join ran on.

    PRD 3.5: "The request's `state` becomes `APPROVED` and its `decided_at` is stamped from the logical clock."
    Design: Corner/consistency_model/the_join_response_and_the_next_read_already_show_every_derived_field
    """
    world = simplemart_world_unpinned
    _join(world)

    request = validate_success(
        api_client.get_change_request(
            world["change_request"]["id"], make_content_author_headers()
        )
    )
    assert request["state"] == "APPROVED"
    assert request["decided_at"].startswith("2026-08-10T00:00:00")


def test_the_first_revision_read_after_the_join_shows_it_pinned(simplemart_world_unpinned):
    """The revision was `IN_REVIEW` when the brand reviewer called; the first read afterwards
    finds it certified, with no retry in between.

    PRD 3.5: "The target revision transitions `IN_REVIEW → PINNED`."
    Design: Corner/consistency_model/the_join_response_and_the_next_read_already_show_every_derived_field
    """
    world = simplemart_world_unpinned
    assert validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )["state"] == "IN_REVIEW"

    _join(world)

    assert validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )["state"] == "PINNED"


def test_the_first_listing_read_after_the_join_shows_the_pointer(simplemart_world_unpinned):
    """The listing was carrying a null pointer a moment earlier; the pin lands on the junction
    row inside the review request, so the next read has it.

    PRD 3.5: "The listing joining the request's product and retailer has its `pinned_content_version_id` repointed to that revision."
    Design: Corner/consistency_model/the_join_response_and_the_next_read_already_show_every_derived_field
    """
    world = simplemart_world_unpinned
    assert _listing(world["listing"]["id"])["pinned_content_version_id"] is None

    _join(world)

    assert _listing(world["listing"]["id"])["pinned_content_version_id"] == world["revision"]["id"]


def test_the_first_product_read_after_the_join_shows_it_active(simplemart_world_unpinned):
    """The product's own promotion out of `DRAFT` is part of the same hop, so it too is visible
    on the first read rather than on a second attempt.

    PRD 3.5: "The product's `last_pinned_at` is stamped from the logical clock and its `status` becomes `ACTIVE`."
    Design: Corner/consistency_model/the_join_response_and_the_next_read_already_show_every_derived_field
    """
    world = simplemart_world_unpinned
    before = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert before["status"] == "DRAFT"
    assert before["last_pinned_at"] is None

    _join(world)

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["status"] == "ACTIVE"
    assert product["last_pinned_at"].startswith("2026-08-10T00:00:00")


def test_every_derived_score_is_already_at_its_final_value(simplemart_world_unpinned):
    """All four derived numbers move with the join and none of them lags: both completeness
    variants, readiness and the pin ledger are final on the first read, and the product's
    version has advanced exactly one step past the value the brand reviewer quoted.

    PRD 3.5: "Alongside the four hops, the join recomputes `completeness_score_certified`, `completeness_score_declared` and `readiness_score` on each touched listing, recomputes the newly pinned revision's `pin_count` upward, recomputes the product's `shelf_health_index`, and — like every review decision — stamps `last_review_at` and increments the product's `version`."
    Design: Corner/consistency_model/the_join_response_and_the_next_read_already_show_every_derived_field
    """
    world = simplemart_world_unpinned
    before = _listing(world["listing"]["id"])
    assert float(before["completeness_score_certified"]) == pytest.approx(0.00, abs=0.01)
    assert float(before["readiness_score"]) == pytest.approx(0.00, abs=0.01)

    _response, version_before_brand = _join(world)

    listing = _listing(world["listing"]["id"])
    assert float(listing["completeness_score_certified"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["completeness_score_declared"]) == pytest.approx(100.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)

    assert validate_success(
        api_client.get_content_version(world["revision"]["id"], make_content_author_headers())
    )["pin_count"] == 1
    assert read_product_version(world["product"]["id"]) == version_before_brand + 1


def test_the_diagnostic_read_agrees_with_the_stored_scores_immediately(simplemart_world_unpinned):
    """The on-demand comparison recomputes from the same rows the join just wrote, and it agrees
    with the stored figures on the first call: both variants read the newly pinned revision,
    both credit the whole image weight, and the shared denominator is the declared 40 plus 20.

    PRD 3.4: "It echoes the `retailer_listing_id`, reports `declared_score` and `certified_score`, names the revision each variant read as `declared_source_content_version_id` and `certified_source_content_version_id` (either of which is null when that variant had no source), reports `requirement_weight_total` as the shared denominator described above — the summed weights of the scoring set plus the image weight of 20 — and reports `declared_image_component` and `certified_image_component` as the two image contributions actually credited."
    Design: Corner/consistency_model/the_join_response_and_the_next_read_already_show_every_derived_field
    """
    world = simplemart_world_unpinned
    _join(world)

    report = validate_success(
        api_client.get_listing_completeness(world["listing"]["id"], make_content_author_headers())
    )
    assert report["retailer_listing_id"] == world["listing"]["id"]
    assert report["declared_source_content_version_id"] == world["revision"]["id"]
    assert report["certified_source_content_version_id"] == world["revision"]["id"]
    assert float(report["declared_score"]) == pytest.approx(100.00, abs=0.01)
    assert float(report["certified_score"]) == pytest.approx(100.00, abs=0.01)
    assert float(report["requirement_weight_total"]) == pytest.approx(60.00, abs=0.01)
    assert float(report["declared_image_component"]) == pytest.approx(20.00, abs=0.01)
    assert float(report["certified_image_component"]) == pytest.approx(20.00, abs=0.01)
