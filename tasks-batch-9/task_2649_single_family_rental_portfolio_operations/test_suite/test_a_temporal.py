"""Two interval-collision rules whose edges are single shared instants and dates.

The showing calendar rejects a zero-gap neighbour on the buffer alone, and vendor capacity is
decided per calendar date, so two windows sharing exactly one boundary date collide there.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import ERR_SHOWING_SLOT_OVERLAP, ERR_VENDOR_CAPACITY_EXCEEDED
from test_helpers.assertions import assert_fields, created, failed, ok, page
from test_helpers.constants import (
    CLOCK_AUG_01,
    SLOT_AVAILABLE,
    WO_DISPATCHED,
    WO_PENDING_DISPATCH,
)


def test_a_zero_gap_neighbour_collides_and_a_thirty_minute_gap_does_not(api):
    """Butting up against S1 on either side is refused; 30 minutes clear is published.

    PRD SS3.7: "The collision test considers, on the same `home_id`, every existing window whose
    `status` is `AVAILABLE`, `BOOKED` or `BLOCKED_BY_POSTURE`, and fails if that window's
    half-open interval from `starts_at` inclusive to `ends_at` exclusive either overlaps the new
    interval, or is separated from it by **strictly fewer** than `showing_buffer_minutes` whole
    minutes on either side -- the buffer being the lockbox re-code interval that must follow and
    precede every tour. Because the intervals are half-open, a new window beginning exactly when
    an existing one ends does not overlap, though it must still clear the buffer."

    Design: Difficulty/resource_temporal_overlap/showing_slot_buffer_treats_zero_gap_as_overlap_and_thirty_minute_gap_as_clear
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    first = created(
        api.create_showing_slot(
            f.showing_slot_payload(
                home["id"],
                starts_at="2026-09-10T15:00:00Z",
                ends_at="2026-09-10T15:30:00Z",
            ),
            x.AGENT,
        )
    )
    assert_fields(first, status=SLOT_AVAILABLE)

    failed(
        api.create_showing_slot(
            f.showing_slot_payload(
                home["id"],
                starts_at="2026-09-10T15:30:00Z",
                ends_at="2026-09-10T16:00:00Z",
            ),
            x.AGENT,
        ),
        ERR_SHOWING_SLOT_OVERLAP,
    )
    failed(
        api.create_showing_slot(
            f.showing_slot_payload(
                home["id"],
                starts_at="2026-09-10T14:30:00Z",
                ends_at="2026-09-10T15:00:00Z",
            ),
            x.AGENT,
        ),
        ERR_SHOWING_SLOT_OVERLAP,
    )

    clear = created(
        api.create_showing_slot(
            f.showing_slot_payload(
                home["id"],
                starts_at="2026-09-10T16:00:00Z",
                ends_at="2026-09-10T16:30:00Z",
            ),
            x.AGENT,
        )
    )
    assert_fields(clear, status=SLOT_AVAILABLE, starts_at="2026-09-10T16:00:00Z")

    rows, _meta = page(api.list_showing_slots(x.AGENT, {"home_id": home["id"]}))
    assert sorted(row["id"] for row in rows) == sorted([first["id"], clear["id"]])


def test_vendor_capacity_is_decided_on_the_single_shared_boundary_date(api):
    """Three plus two fails on the 12th; three plus one fits at exactly four.

    PRD SS3.4: "That last clause is a per-date capacity test, not an aggregate one. For **every**
    calendar date in the closed-inclusive window from `scheduled_start_date` through
    `scheduled_end_date`, the sum of `crew_size` over that vendor's work orders whose `status` is
    `DISPATCHED` or `ACCEPTED` and whose own closed-inclusive windows contain that date, plus this
    work order's `crew_size`, must not exceed the vendor's `daily_crew_capacity`. If even one date
    fails, the dispatch is refused with `ERR_VENDOR_CAPACITY_EXCEEDED`. ... a vendor with a
    `daily_crew_capacity` of 4 already carrying a three-crew job from the 10th through the 12th
    cannot take a two-crew job running the 12th through the 14th, since the 12th would need 5.
    Rescoped to one crew member, the same job fits exactly at 4 and succeeds, taking
    `committed_crew_days` from 9 to 12".

    Design: Difficulty/resource_temporal_overlap/vendor_daily_crew_capacity_aggregates_on_shared_boundary_date
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])
    vendor = x.create_vendor(
        api,
        market["id"],
        legal_name="Peachtree Painting LLC",
        daily_crew_capacity=4,
    )
    x.certify_vendor(api, vendor["id"], "PAINT", expires_on="2027-01-31")
    first = get_success_data(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                fulfillment_channel="VENDOR",
            ),
            x.OPS,
        )
    )
    get_success_data(api.dispatch_work_order(first["id"], {"vendor_id": vendor["id"]}, x.OPS))
    assert_fields(ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER)), committed_crew_days=9)
    two_crew = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                crew_size=2,
                scheduled_start_date="2026-08-12",
                scheduled_end_date="2026-08-14",
                fulfillment_channel="VENDOR",
            ),
            x.OPS,
        )
    )
    one_crew = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                crew_size=1,
                scheduled_start_date="2026-08-12",
                scheduled_end_date="2026-08-14",
                fulfillment_channel="VENDOR",
            ),
            x.OPS,
        )
    )
    assert_fields(two_crew, crew_days=6)
    assert_fields(one_crew, crew_days=3)

    failed(
        api.dispatch_work_order(two_crew["id"], {"vendor_id": vendor["id"]}, x.OPS),
        ERR_VENDOR_CAPACITY_EXCEEDED,
    )
    assert_fields(ok(api.get_work_order(two_crew["id"], x.OPS)), status=WO_PENDING_DISPATCH)
    assert_fields(ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER)), committed_crew_days=9)

    dispatched = ok(api.dispatch_work_order(one_crew["id"], {"vendor_id": vendor["id"]}, x.OPS))
    assert_fields(dispatched, status=WO_DISPATCHED, vendor_id=vendor["id"])
    assert_fields(ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER)), committed_crew_days=12)
