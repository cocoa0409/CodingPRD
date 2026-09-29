"""Requests that break two rules at once, and the pinned order that decides which
error the caller is told about."""
import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_slot_ledger
from test_helpers.constants import AUTO_CLEARED_BY_ACCOUNT_TEAM
from test_helpers.factories import (
    create_attribute_value_payload,
    create_syndication_job_payload,
    shelf_status_payload,
)
from test_helpers.fixtures import ingest_observation, read_retailer_version
from test_helpers.test_users import (
    make_account_team_headers,
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

PROHIBITED_VALUE = "This herbal tonic cures every ailment within a single week of use."
CLEAN_LONG_VALUE = "A compact 900 watt blender with six speeds and a glass jar."


def _unauthorized_crawl(world):
    return ingest_observation(
        world["listing"]["id"],
        "2026-08-09T00:00:00Z",
        in_stock=True,
        content_accuracy_pct=95.00,
        rating_avg=4.00,
        rating_count=80,
        unauthorized_seller_count=1,
        conversion_rate_pct=3.00,
        units_sold=25,
        search_rank=2,
    )


def _ten_slot_queue_payload(world, retailer_version):
    return create_syndication_job_payload(
        world["listing"]["id"],
        world["revision"]["id"],
        10,
        "2026-08-20T00:00:00Z",
        "2026-08-21T00:00:00Z",
        retailer_version,
    )


def test_the_shelf_block_guard_is_reported_ahead_of_the_capacity_guard(
    bigbox_world_capacity_6,
):
    """The ten-slot request breaks the shelf-block rule and the six-slot capacity
    rule at the same time; the earlier guard wins and the caller is told the listing
    is blocked.

    PRD 3.6: "The listing's `shelf_state` must be neither `SUSPENDED` nor `UNAUTHORIZED`, otherwise `ERR_LISTING_SHELF_BLOCKED` — a listing under unauthorized-seller enforcement is not a listing you push more content to."
    Design: Difficulty/priority_pair_validation_conflict/shelf_blocked_priority_34_beats_feed_capacity_priority_45
    """
    world = bigbox_world_capacity_6
    retailer_version = read_retailer_version(world["retailer"]["id"])
    _unauthorized_crawl(world)

    response = api_client.create_syndication_job(
        _ten_slot_queue_payload(world, retailer_version), make_syndication_operator_headers()
    )
    validate_error(response, ApiErrorId.ERR_LISTING_SHELF_BLOCKED.value, 409)


def test_clearing_the_shelf_block_exposes_the_capacity_guard_underneath(
    bigbox_world_capacity_6,
):
    """Once the account team clears the listing back to OK, the byte-identical
    payload is refused for capacity instead — 0 reserved plus 10 requested against a
    capacity of 6 — which proves the first refusal was an ordering decision.

    PRD 3.6: "The **slot capacity** guard requires that the retailer's current `feed_slots_reserved` plus the requested `slot_count` is at most `feed_slot_capacity`; landing exactly on capacity is allowed, and exceeding it is `ERR_FEED_CAPACITY_EXCEEDED`."
    Design: Difficulty/priority_pair_validation_conflict/shelf_blocked_priority_34_beats_feed_capacity_priority_45
    """
    world = bigbox_world_capacity_6
    retailer_version = read_retailer_version(world["retailer"]["id"])
    _unauthorized_crawl(world)
    payload = _ten_slot_queue_payload(world, retailer_version)

    validate_error(
        api_client.create_syndication_job(payload, make_syndication_operator_headers()),
        ApiErrorId.ERR_LISTING_SHELF_BLOCKED.value,
        409,
    )

    cleared = validate_success(
        api_client.set_shelf_status(
            world["listing"]["id"],
            shelf_status_payload("OK"),
            make_account_team_headers("acct_bigbox_1"),
        )
    )
    assert cleared["shelf_state"] == "OK"
    assert float(cleared["readiness_score"]) == pytest.approx(89.00, abs=0.01)

    validate_error(
        api_client.create_syndication_job(payload, make_syndication_operator_headers()),
        ApiErrorId.ERR_FEED_CAPACITY_EXCEEDED.value,
        409,
    )


def test_neither_refused_queue_reserves_slots_or_creates_a_job(bigbox_world_capacity_6):
    """Both refusals leave the ledger at zero with the retailer still on its original
    version, no job row behind them, and the listing still unsyndicated.

    PRD 2.9: "`Retailer.feed_slots_reserved` is the sum of `slot_count` over every syndication job belonging to any listing of that retailer whose `state` is `QUEUED` or `TRANSMITTED`."
    Design: Difficulty/priority_pair_validation_conflict/shelf_blocked_priority_34_beats_feed_capacity_priority_45
    """
    world = bigbox_world_capacity_6
    retailer_version = read_retailer_version(world["retailer"]["id"])
    _unauthorized_crawl(world)
    payload = _ten_slot_queue_payload(world, retailer_version)

    api_client.create_syndication_job(payload, make_syndication_operator_headers())
    validate_success(
        api_client.set_shelf_status(
            world["listing"]["id"],
            shelf_status_payload("OK"),
            make_account_team_headers("acct_bigbox_1"),
        )
    )
    api_client.create_syndication_job(payload, make_syndication_operator_headers())

    retailer = validate_success(
        api_client.get_retailer(world["retailer"]["id"], make_shelf_admin_headers())
    )
    assert_slot_ledger(retailer, 0)
    assert retailer["version"] == 1

    _jobs, meta = validate_paginated(
        api_client.list_syndication_jobs(
            make_syndication_operator_headers(),
            params={"retailer_listing_id": world["listing"]["id"]},
        )
    )
    assert meta["total_count"] == 0

    listing = validate_success(
        api_client.get_retailer_listing(world["listing"]["id"], make_shelf_admin_headers())
    )
    assert listing["syndication_state"] == "NOT_SYNDICATED"


def test_the_account_team_clearance_closes_the_unauthorized_alert(bigbox_world_capacity_6):
    """Clearing to OK resolves the unauthorized-listing alert with the platform's own
    resolution note, which drops the product's governance flag all the way back to
    NONE because no other alert is open.

    PRD 3.9: "Clearing to `OK` is permitted from `UNAUTHORIZED`, `OOS_WATCH` or `SUSPENDED`, leaves `syndication_state` untouched, and resolves every `UNAUTHORIZED_LISTING` alert of the listing still in `OPEN` or `ACKNOWLEDGED` with `resolution_note` set to the literal string `AUTO_CLEARED_BY_ACCOUNT_TEAM`; it then recomputes the listing's `readiness_score`, the product's `open_alert_count` and `governance_flag`, and increments the product's `version` by 1."
    Design: Difficulty/priority_pair_validation_conflict/shelf_blocked_priority_34_beats_feed_capacity_priority_45
    """
    world = bigbox_world_capacity_6
    _unauthorized_crawl(world)
    validate_success(
        api_client.set_shelf_status(
            world["listing"]["id"],
            shelf_status_payload("OK"),
            make_account_team_headers("acct_bigbox_1"),
        )
    )

    alerts, meta = validate_paginated(
        api_client.list_shelf_alerts(
            make_account_team_headers(),
            params={
                "retailer_listing_id": world["listing"]["id"],
                "alert_type": "UNAUTHORIZED_LISTING",
            },
        )
    )
    assert meta["total_count"] == 1
    assert alerts[0]["state"] == "RESOLVED"
    assert alerts[0]["resolution_note"] == AUTO_CLEARED_BY_ACCOUNT_TEAM

    product = validate_success(
        api_client.get_product(world["product"]["id"], make_shelf_admin_headers())
    )
    assert product["governance_flag"] == "NONE"


def test_the_prohibited_claim_screen_runs_before_the_length_screen(tight_description_world):
    """A 66-character value carrying the token "cures" breaks both content screens at
    once against a 40-character ceiling, and the claim screen is the one that
    answers.

    PRD 3.2: "A prohibited-claim screen performs a case-insensitive substring match for the tokens *cures*, *fda approved* and *100% guaranteed*; a match anywhere in the stripped value is rejected with `ERR_PROHIBITED_CLAIM`."
    Design: Difficulty/priority_pair_validation_conflict/prohibited_claim_priority_35_beats_attribute_length_priority_40
    """
    response = api_client.create_attribute_value(
        tight_description_world["revision"]["id"],
        create_attribute_value_payload("description", PROHIBITED_VALUE),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_PROHIBITED_CLAIM.value, 422)
    assert len(PROHIBITED_VALUE) == 66


def test_a_clean_value_over_the_ceiling_reaches_the_length_screen(tight_description_world):
    """The same key with a 59-character value carrying no prohibited token gets past
    the claim screen and is refused by the taxonomy ceiling instead.

    PRD 3.2: "A length screen then requires `char_count` to be at most the `max_chars` declared on the taxonomy attribute, rejecting with `ERR_ATTRIBUTE_LENGTH_EXCEEDED` otherwise."
    Design: Difficulty/priority_pair_validation_conflict/prohibited_claim_priority_35_beats_attribute_length_priority_40
    """
    response = api_client.create_attribute_value(
        tight_description_world["revision"]["id"],
        create_attribute_value_payload("description", CLEAN_LONG_VALUE),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_ATTRIBUTE_LENGTH_EXCEEDED.value, 422)
    assert len(CLEAN_LONG_VALUE) == 59


def test_neither_refused_attribute_write_leaves_a_row_behind(tight_description_world):
    """Both rejected writes are complete no-ops: the revision still holds no attribute
    values and is still an untouched DRAFT at version 1.

    PRD 3.2: "Writes are upserts: at most one row exists per attribute key per revision, and a second write on the same key replaces the existing row rather than creating a second one."
    Design: Difficulty/priority_pair_validation_conflict/prohibited_claim_priority_35_beats_attribute_length_priority_40
    """
    revision_id = tight_description_world["revision"]["id"]
    api_client.create_attribute_value(
        revision_id,
        create_attribute_value_payload("description", PROHIBITED_VALUE),
        make_content_author_headers(),
    )
    api_client.create_attribute_value(
        revision_id,
        create_attribute_value_payload("description", CLEAN_LONG_VALUE),
        make_content_author_headers(),
    )

    _rows, meta = validate_paginated(
        api_client.list_attribute_values(revision_id, make_content_author_headers())
    )
    assert meta["total_count"] == 0

    revision = get_success_data(
        api_client.get_content_version(revision_id, make_content_author_headers())
    )
    assert revision["state"] == "DRAFT"
    assert revision["version"] == 1
