"""Standing orders: weekday-mask generation, idempotent rolling horizon, and
suppression while the owning member's order is paused by an eligibility lapse.

Corner queue B (calculations standing-order generation).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_paginated,
    get_success_data,
    create_member_payload,
    create_eligibility_span_payload,
    create_standing_order_payload,
)
from test_helpers import fixtures

COORD = TEST_USERS["coordinator_headers"]


def test_standing_order_generation_weekday_mask_and_idempotency(api):
    """PRD 3.6: "Walking the dates in ascending order from that effective start up
    to but not including `generate_through`, the system creates one `DRAFT` trip
    for each date whose weekday bit is set in `weekday_mask` — but only while the
    order's `status` is `ACTIVE` and the owning member is not paused."
    PRD 3.6: "The effective start is the later of `generate_from` and the order's
    current `horizon_through` ... so dates already covered by a prior run are
    skipped rather than duplicated. ... After the run, the order's
    `horizon_through` is advanced to `generate_through`."

    Design: Corner/calculations/standing_order_generation_weekday_mask_and_idempotency
    """
    fixtures.set_clock("2026-03-01T08:00:00Z")
    member = fixtures.create_member(medicaid_id="M-SO1", mobility_level="WHEELCHAIR",
                                    home_county="C1")
    fixtures.create_span(member["id"], level_of_service="ROUTINE",
                         coverage_start="2026-01-01T00:00:00Z",
                         coverage_end="2027-01-01T00:00:00Z")
    so = get_success_data(api.create_standing_order(
        create_standing_order_payload(member["id"], modality="WHEELCHAIR",
                                      level_of_service="ROUTINE", weekday_mask=21,
                                      appointment_time_utc="09:00:00",
                                      scheduled_loaded_miles=7), COORD))
    # Mon|Wed|Fri over [2026-03-02 Mon, 2026-03-09 Mon) -> Mon 03-02, Wed 03-04, Fri 03-06 = 3.
    window = {"generate_from": "2026-03-02T00:00:00Z", "generate_through": "2026-03-09T00:00:00Z"}
    get_success_data(api.generate_standing_order(so["id"], window, COORD))
    # Idempotent re-generation over the same window.
    final = get_success_data(api.generate_standing_order(so["id"], window, COORD))
    assert final["horizon_through"] == "2026-03-09T00:00:00Z"
    resp = api.list_trips(COORD, params={"standing_order_id": so["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3, "Mon+Wed+Fri = 3 trips; re-generate added none"


def test_standing_order_paused_member_suppresses_generation(api):
    """PRD 3.1: "The member's `standing_orders_paused` flag is set to true, and
    every `ACTIVE` standing order for the member is moved to `PAUSED`."
    PRD 3.6: "the system creates one `DRAFT` trip for each date whose weekday bit
    is set in `weekday_mask` — but only while the order's `status` is `ACTIVE` and
    the owning member is not paused."

    Design: Corner/calculations/standing_order_paused_member_suppresses_generation
    """
    fixtures.set_clock("2026-03-01T08:00:00Z")
    member = fixtures.create_member(medicaid_id="M-SP1", mobility_level="WHEELCHAIR",
                                    home_county="C1")
    # Span lapses at 2026-03-03; recompute at 2026-03-04 pauses the active order.
    fixtures.create_span(member["id"], level_of_service="ROUTINE",
                         coverage_start="2026-01-01T00:00:00Z",
                         coverage_end="2026-03-03T00:00:00Z")
    so = get_success_data(api.create_standing_order(
        create_standing_order_payload(member["id"], modality="WHEELCHAIR",
                                      level_of_service="ROUTINE", weekday_mask=21,
                                      appointment_time_utc="09:00:00",
                                      scheduled_loaded_miles=7), COORD))
    fixtures.set_clock("2026-03-04T00:00:00Z")
    recomputed = get_success_data(api.recompute_eligibility(member["id"], COORD))
    assert recomputed["standing_orders_paused"] is True
    so_after = get_success_data(api.get_standing_order(so["id"], COORD))
    assert so_after["status"] == "PAUSED"
    # Generate over a future window: suppressed while paused.
    get_success_data(api.generate_standing_order(
        so["id"],
        {"generate_from": "2026-03-09T00:00:00Z", "generate_through": "2026-03-16T00:00:00Z"},
        COORD))
    resp = api.list_trips(COORD, params={"standing_order_id": so["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, "no trips generated while order paused"
