"""Read-your-writes: an allocation run's cascade is complete before it answers.

One write, then immediate reads from a second identity — no sweep, no re-run and
no waiting — must already show the carrier's ledger and the allocation rows the
run created.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field_equals,
    assert_field_null,
    assert_pct,
)
from test_helpers.constants import (
    ALLOCATION_STATUS_PENDING,
    CLOCK_BASE,
    EVENT_STATUS_ALLOCATED,
)
from test_helpers.fixtures import (
    create_event,
    create_member_insurers,
    create_zone,
    pin_clock,
)
from test_helpers.test_users import admin_headers, make_member_insurer_headers


def test_allocation_run_side_effects_are_visible_in_the_same_request_and_on_immediate_reads(
    client,
):
    """The run's own body carries the totals, and the carrier sees its bill at once.

    PRD: "Cascades run to completion within the request that triggered them;
    there is no deferred or eventual reconciliation, and a read issued
    immediately afterward observes every hop."

    PRD: "A first run moves the event `DRAFT → ALLOCATED`: it creates one
    allocation per eligible member, each in `status` `PENDING` with `paid_at`
    null, writes `allocated_total_cents` and `remainder_cents`, increments
    `allocation_run_count` by one, raises each touched member's
    `cumulative_assessed_cents` by that member's `net_due_cents` while
    incrementing each member's `version` by one, and increments the event's
    `version` by one."

    PRD: "Each eligible member's weight is its `market_share_pct` when the event's
    `allocation_basis` is `MARKET_SHARE`, and its `written_premium_share_pct` when
    the basis is `PREMIUM_VOLUME`; that weight is snapshotted onto the resulting
    allocation as `basis_weight_pct`."

    PRD: "The offset written to `takeout_credit_applied_cents` is the smaller of
    two figures: fifty percent of that member's `gross_share_cents`, rounded half
    up to whole cents, and the member's `takeout_credit_count` multiplied by
    500,000 cents."

    Design: Corner/consistency_model/allocation_run_side_effects_are_visible_in_the_same_request_and_on_immediate_reads
    """
    pin_clock(client, CLOCK_BASE)
    members = create_member_insurers(client)
    zone = create_zone(client, exposure_cap_cents=900_000_000)
    event = create_event(client, zone["id"], 200_000_000, 100_000_000)
    carrier = members[2]
    carrier_headers = make_member_insurer_headers(carrier["id"])

    response = client.run_allocation(
        event["id"], f.allocation_run_payload(event["version"]), admin_headers()
    )

    allocated = validate_success(response, 200)
    assert_field_equals(allocated, "status", EVENT_STATUS_ALLOCATED)
    assert_cents(allocated["allocated_total_cents"], 100_000_000, "allocated_total_cents")
    assert_cents(allocated["remainder_cents"], 0, "remainder_cents")
    assert_field_equals(allocated, "allocation_run_count", 1)
    assert_field_equals(allocated, "version", 2)

    carrier_record = validate_success(
        client.get_member_insurer(carrier["id"], carrier_headers), 200
    )
    assert_cents(
        carrier_record["cumulative_assessed_cents"],
        40_000_000,
        "cumulative_assessed_cents",
    )

    rows, meta = validate_paginated(
        client.list_member_insurer_allocations(
            carrier["id"],
            carrier_headers,
            {"status": ALLOCATION_STATUS_PENDING, "limit": 10},
        )
    )
    assert_field_equals(meta, "total_count", 1)
    assert_count(rows, 1, "allocations charged to the forty-percent carrier")
    allocation = rows[0]
    assert_field_equals(allocation, "member_insurer_id", carrier["id"])
    assert_field_equals(allocation, "assessment_event_id", event["id"])
    assert_pct(allocation["basis_weight_pct"], "40.00", "basis_weight_pct")
    assert_cents(allocation["gross_share_cents"], 40_000_000, "gross_share_cents")
    assert_cents(allocation["takeout_credit_applied_cents"], 0, "takeout_credit_applied_cents")
    assert_cents(allocation["net_due_cents"], 40_000_000, "net_due_cents")
    assert_field_equals(allocation, "status", ALLOCATION_STATUS_PENDING)
    assert_field_null(allocation, "paid_at")

    _all_rows, all_meta = validate_paginated(
        client.list_assessment_event_allocations(
            event["id"], admin_headers(), {"limit": 10}
        )
    )
    assert_field_equals(all_meta, "total_count", 3)
