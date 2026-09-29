"""Optimistic concurrency on the two writes guarded by a parent record's version.

Both cases are ones the state machine cannot judge: a second filing may legally
coexist with an approved one, and a second allocation run is a legal supersede.
Each test goes stale, is refused, re-reads the parent and then succeeds.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_STALE_VERSION
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field_equals,
    find_one,
)
from test_helpers.constants import (
    ALLOCATION_STATUS_PENDING,
    CLOCK_BASE,
    EVENT_STATUS_ALLOCATED,
    FILING_STATUS_APPROVED,
    FILING_STATUS_FILED,
)
from test_helpers.fixtures import (
    allocate_event,
    create_event,
    create_member_insurers,
    create_zone,
    file_rate,
    pin_clock,
    read_allocations,
    read_event,
    read_filing,
    read_member,
    read_zone,
    review_filing,
)
from test_helpers.test_users import admin_headers, rate_analyst_headers, regulator_headers


def test_rate_filing_create_with_a_stale_zone_version_is_rejected(client):
    """The zone version moved twice; the filing quoting the original is refused.

    PRD: "Creating a rate filing requires a non-optional `expected_zone_version`
    field carrying the client's last observed `version` of the target
    `CatastropheZone`. If that number does not equal the zone's current
    `version`, the filing is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    PRD: "This protection is necessary precisely because several filings may
    legitimately sit in `FILED` status on the same territory and package at once,
    so no state precondition can catch the problem; what makes the write wrong is
    that the zone's posture moved underneath the analyst — an approval superseded
    the prior approved filing, or a bind, cancellation, expiry or take-out
    re-derived the zone status — after the version the request carries."

    PRD: "The filing is created in `status` `FILED`, its `filed_by_user_id` is
    taken from `X-User-ID`, its `reviewed_by_user_id` and `review_note` are null,
    and the territory's `version` increments by one because a new filing changes
    the territory's rate posture."

    Design: Corner/complexity_layers/rate_filing_create_with_a_stale_zone_version_is_rejected
    """
    pin_clock(client, CLOCK_BASE)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    assert_field_equals(zone, "version", 1)
    first_filing = file_rate(client, zone["id"])
    review_filing(client, first_filing["id"])

    stale_attempt = client.create_rate_filing(
        f.rate_filing_payload(
            cat_zone_id=zone["id"],
            expected_zone_version=zone["version"],
            filed_rate_per_1000_cents=950,
            effective_date="2026-10-01",
        ),
        rate_analyst_headers(),
    )

    validate_error(stale_attempt, ERR_STALE_VERSION)
    refreshed = read_zone(client, zone["id"])
    assert_field_equals(refreshed, "version", 3)

    retry = client.create_rate_filing(
        f.rate_filing_payload(
            cat_zone_id=zone["id"],
            expected_zone_version=refreshed["version"],
            filed_rate_per_1000_cents=950,
            effective_date="2026-10-01",
        ),
        rate_analyst_headers(),
    )

    second_filing = validate_success(retry, 201)
    assert_field_equals(second_filing, "status", FILING_STATUS_FILED)
    assert_cents(
        second_filing["filed_rate_per_1000_cents"], 950, "filed_rate_per_1000_cents"
    )
    assert_field_equals(
        read_filing(client, first_filing["id"]), "status", FILING_STATUS_APPROVED
    )
    assert_field_equals(read_zone(client, zone["id"]), "version", 4)
    _rows, meta = validate_paginated(
        client.list_cat_zone_rate_filings(zone["id"], regulator_headers(), {"limit": 10})
    )
    assert_field_equals(meta, "total_count", 2)


def test_allocation_run_with_a_stale_assessment_version_is_rejected(client):
    """A supersede re-run is legal, so only the version guard can turn it away.

    PRD: "Running the allocation for an assessment event requires a non-optional
    `expected_assessment_event_version` field carrying the client's last observed
    `version` of the target `AssessmentEvent`. A mismatch with the event's
    current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    PRD: "Here too the state machine cannot help: a re-run from `ALLOCATED` is a
    legitimate supersede that abates the prior pending allocations and rebuilds
    the set from current member weights, so the second caller cannot be turned
    away on state grounds."

    PRD: "A re-run is a legitimate supersede and moves the event `ALLOCATED →
    ALLOCATED`: every prior allocation on the event whose `status` is `PENDING`
    moves `PENDING → ABATED`, a fresh allocation set is built from the members'
    **current** weights (so a carrier that moved to `WITHDRAWN` between runs
    drops out and the total weight changes), `allocation_run_count` increments
    again, each member's `cumulative_assessed_cents` is recomputed from
    non-abated allocations only, and the event's `version` increments by one."

    Design: Corner/complexity_layers/allocation_run_with_a_stale_assessment_version_is_rejected
    """
    pin_clock(client, CLOCK_BASE)
    members = create_member_insurers(client)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    event = create_event(client, zone["id"], 200_000_000, 100_000_000)
    assert_field_equals(event, "version", 1)
    first_run = allocate_event(client, event)
    assert_field_equals(first_run, "status", EVENT_STATUS_ALLOCATED)
    assert_field_equals(first_run, "allocation_run_count", 1)

    stale_attempt = client.run_allocation(
        event["id"], f.allocation_run_payload(event["version"]), admin_headers()
    )

    validate_error(stale_attempt, ERR_STALE_VERSION)
    refreshed = read_event(client, event["id"])
    assert_field_equals(refreshed, "allocation_run_count", 1)
    assert_field_equals(refreshed, "version", 2)

    retry = client.run_allocation(
        event["id"], f.allocation_run_payload(refreshed["version"]), admin_headers()
    )

    rerun = validate_success(retry, 200)
    assert_field_equals(rerun, "allocation_run_count", 2)
    assert_field_equals(rerun, "version", 3)
    assert_cents(rerun["allocated_total_cents"], 100_000_000, "allocated_total_cents")
    assert_cents(rerun["remainder_cents"], 0, "remainder_cents")
    pending, meta = validate_paginated(
        client.list_assessment_event_allocations(
            event["id"],
            admin_headers(),
            {"status": ALLOCATION_STATUS_PENDING, "limit": 10},
        )
    )
    assert_field_equals(meta, "total_count", 3)
    assert_count(pending, 3, "live allocations")
    for member, expected in zip(members, (30_000_000, 30_000_000, 40_000_000)):
        allocation = find_one(pending, "member_insurer_id", member["id"])
        assert_cents(allocation["net_due_cents"], expected, "net_due_cents")
    assert_cents(
        read_member(client, members[2]["id"])["cumulative_assessed_cents"],
        40_000_000,
        "cumulative_assessed_cents",
    )
    assert_count(read_allocations(client, event["id"]), 6, "allocations ever created")
