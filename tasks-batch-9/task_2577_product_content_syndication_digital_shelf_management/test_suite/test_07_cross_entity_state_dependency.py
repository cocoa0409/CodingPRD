"""Writes whose outcome is decided by the state of a neighbouring entity rather
than by the payload."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_enhanced_deployment, assert_pin_ledger, assert_slot_ledger
from test_helpers.factories import create_syndication_job_payload
from test_helpers.fixtures import (
    add_bigbox_second_revision,
    deploy_enhanced_module,
    read_retailer_version,
)
from test_helpers.test_users import (
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)


def _queue_payload(world, content_version_id, retailer_version):
    return create_syndication_job_payload(
        world["listing"]["id"],
        content_version_id,
        6,
        "2026-08-20T00:00:00Z",
        "2026-08-21T00:00:00Z",
        retailer_version,
    )


def test_queueing_a_draft_revision_is_refused_on_the_revisions_own_state(bigbox_world):
    """Listing, retailer, capacity, window and completeness inputs are all valid, but
    the named revision is a DRAFT of the same product, so the queue is refused.

    PRD 3.6: "The named revision must be `PINNED` and its `product_id` must equal the listing's `product_id`, otherwise `ERR_VERSION_NOT_PINNED`; only certified content goes on a feed, and a `DRAFT`, `IN_REVIEW` or `SUPERSEDED` revision is refused."
    Design: Difficulty/cross_entity_state_dependency/queue_call_depends_on_the_content_versions_own_pin_state
    """
    revision_2 = add_bigbox_second_revision(bigbox_world, supersedes=bigbox_world["revision"]["id"])
    retailer_version = read_retailer_version(bigbox_world["retailer"]["id"])

    response = api_client.create_syndication_job(
        _queue_payload(bigbox_world, revision_2["id"], retailer_version),
        make_syndication_operator_headers(),
    )
    validate_error(response, ApiErrorId.ERR_VERSION_NOT_PINNED.value, 422)

    draft = validate_success(
        api_client.get_content_version(revision_2["id"], make_content_author_headers())
    )
    assert draft["state"] == "DRAFT"
    assert_pin_ledger(draft, 0)


def test_the_byte_identical_call_on_the_pinned_revision_is_accepted(bigbox_world):
    """Swapping only content_version_id for the PINNED revision 1 makes the same
    request succeed, which locates the refusal in the referenced revision rather
    than anywhere in the listing's own posture.

    PRD 3.6: "The revision's `pin_count` is deliberately **not** touched — a job references a revision, it does not pin it."
    Design: Difficulty/cross_entity_state_dependency/queue_call_depends_on_the_content_versions_own_pin_state
    """
    revision_2 = add_bigbox_second_revision(bigbox_world, supersedes=bigbox_world["revision"]["id"])
    retailer_version = read_retailer_version(bigbox_world["retailer"]["id"])
    validate_error(
        api_client.create_syndication_job(
            _queue_payload(bigbox_world, revision_2["id"], retailer_version),
            make_syndication_operator_headers(),
        ),
        ApiErrorId.ERR_VERSION_NOT_PINNED.value,
        422,
    )

    retailer_after_failure = validate_success(
        api_client.get_retailer(bigbox_world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer_after_failure, 0)
    assert retailer_after_failure["version"] == 1

    job = get_success_data(
        api_client.create_syndication_job(
            _queue_payload(
                bigbox_world,
                bigbox_world["revision"]["id"],
                retailer_after_failure["version"],
            ),
            make_syndication_operator_headers(),
        )
    )
    assert job["state"] == "QUEUED"
    assert job["content_version_id"] == bigbox_world["revision"]["id"]
    assert job["slot_count"] == 6
    assert job["service_fee_cents"] == 13500

    retailer = validate_success(
        api_client.get_retailer(bigbox_world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 6)
    assert retailer["version"] == 2

    pinned = validate_success(
        api_client.get_content_version(
            bigbox_world["revision"]["id"], make_content_author_headers()
        )
    )
    assert_pin_ledger(pinned, 1)


def test_a_deployment_waits_for_the_retailer_that_demands_approval(flag_pair_world):
    """AskFirst has enhanced_content_requires_approval true, so the deployment opens
    in PENDING_RETAILER_APPROVAL with no decision stamp.

    PRD 3.8: "When the retailer's `enhanced_content_requires_approval` is true, the deployment is created in `PENDING_RETAILER_APPROVAL` and awaits a decision."
    Design: Difficulty/cross_entity_state_dependency/deployment_initial_state_reads_the_retailers_approval_flag
    """
    deployment = deploy_enhanced_module(
        flag_pair_world["ask_first_listing"]["id"],
        flag_pair_world["ask_first_change_request"]["id"],
        flag_pair_world["asset"]["id"],
        "A_PLUS_PAGE",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )
    assert_enhanced_deployment(deployment)
    assert deployment["state"] == "PENDING_RETAILER_APPROVAL"
    assert deployment["retailer_decision_at"] is None
    assert deployment["module_kind"] == "A_PLUS_PAGE"


def test_the_same_request_goes_straight_live_where_no_approval_is_required(flag_pair_world):
    """AutoLive differs only in the approval flag, so the very same payload shape
    creates the deployment directly in LIVE, and its decision stamp stays null
    because no decision was ever required.

    PRD 3.8: "When it is false, the very same request creates the deployment directly in `LIVE` with `retailer_decision_at` left null, because no decision was ever required."
    Design: Difficulty/cross_entity_state_dependency/deployment_initial_state_reads_the_retailers_approval_flag
    """
    deployment = deploy_enhanced_module(
        flag_pair_world["auto_live_listing"]["id"],
        flag_pair_world["auto_live_change_request"]["id"],
        flag_pair_world["asset"]["id"],
        "A_PLUS_PAGE",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )
    assert deployment["state"] == "LIVE"
    assert deployment["retailer_decision_at"] is None
    assert deployment["window_end"].startswith("2026-08-22T00:00:00")


def test_only_the_live_branch_earns_the_enhanced_content_bonus(flag_pair_world):
    """Both listings blend the same 100.00 certified score with the same absent
    accuracy, so the only difference between 60.00 and 65.00 is the flat five points
    the LIVE deployment earns.

    PRD 3.8: "That bonus is a flat **5 points** added to the readiness blend described in §3.4, and it is earned by the existence of at least one deployment of the listing in `LIVE`. A deployment sitting in `PENDING_RETAILER_APPROVAL` earns nothing — waiting for approval is not the same as being published."
    Design: Difficulty/cross_entity_state_dependency/deployment_initial_state_reads_the_retailers_approval_flag
    """
    deploy_enhanced_module(
        flag_pair_world["ask_first_listing"]["id"],
        flag_pair_world["ask_first_change_request"]["id"],
        flag_pair_world["asset"]["id"],
        "A_PLUS_PAGE",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )
    deploy_enhanced_module(
        flag_pair_world["auto_live_listing"]["id"],
        flag_pair_world["auto_live_change_request"]["id"],
        flag_pair_world["asset"]["id"],
        "A_PLUS_PAGE",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )

    ask_first_listing = validate_success(
        api_client.get_retailer_listing(
            flag_pair_world["ask_first_listing"]["id"], make_content_author_headers()
        )
    )
    assert float(ask_first_listing["readiness_score"]) == pytest.approx(60.00, abs=0.01)

    auto_live_listing = validate_success(
        api_client.get_retailer_listing(
            flag_pair_world["auto_live_listing"]["id"], make_content_author_headers()
        )
    )
    assert float(auto_live_listing["readiness_score"]) == pytest.approx(65.00, abs=0.01)


def test_both_active_deployment_states_count_as_pin_references(flag_pair_world):
    """A pending deployment and a live deployment are equally live references, so each
    revision now holds two: its listing pin plus its deployment.

    PRD 2.9: "`ContentVersion.pin_count` is the number of references currently held on a revision, and it counts two different kinds of reference: the number of retailer listings whose `pinned_content_version_id` equals the revision's `id`, plus the number of enhanced-content deployments in state `PENDING_RETAILER_APPROVAL` or `LIVE` whose governing change request's `target_content_version_id` equals that same `id`."
    Design: Difficulty/cross_entity_state_dependency/deployment_initial_state_reads_the_retailers_approval_flag
    """
    deploy_enhanced_module(
        flag_pair_world["ask_first_listing"]["id"],
        flag_pair_world["ask_first_change_request"]["id"],
        flag_pair_world["asset"]["id"],
        "A_PLUS_PAGE",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )
    deploy_enhanced_module(
        flag_pair_world["auto_live_listing"]["id"],
        flag_pair_world["auto_live_change_request"]["id"],
        flag_pair_world["asset"]["id"],
        "A_PLUS_PAGE",
        "2026-08-20T00:00:00Z",
        "2026-08-22T00:00:00Z",
    )

    for key in ("revision_1", "revision_2"):
        revision = validate_success(
            api_client.get_content_version(
                flag_pair_world[key]["id"], make_content_author_headers()
            )
        )
        assert_pin_ledger(revision, 2)
