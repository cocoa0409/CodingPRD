"""Dispatch eligibility and the one structural check that outranks the state machine.

Every refusal here is decided by a row the dispatch payload names only indirectly -- the
vendor's insurance date, its market, its certification shelf -- or by no row at all, when the
eligible set comes back empty.  The second test is the only place in the system where a
structural guard is documented to speak before the transition guard.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_IN_HOUSE_SAFETY_CRITICAL,
    ERR_INVALID_STATE,
    ERR_MARKET_MISMATCH,
    ERR_NO_ELIGIBLE_VENDOR,
    ERR_VENDOR_INSURANCE_EXPIRED,
    ERR_VENDOR_NOT_CERTIFIED,
    ERR_WORK_ORDER_NOT_ASSIGNED,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_money_group,
    created,
    failed,
    ok,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    WO_PENDING_DISPATCH,
)


def test_four_ways_to_be_ineligible_and_the_bench_that_refuses_safety_critical_work(api):
    """Lapsed cover, wrong market, no certificate, nobody left -- and none of it moves a ledger.

    PRD SS3.4 fixes every clause: "Whether the vendor was named explicitly or selected
    automatically, it must satisfy every eligibility clause: its `status` must be `ACTIVE`, or the
    dispatch fails with `ERR_VENDOR_INACTIVE`; its `insurance_expires_on` must be on or after the
    current logical-clock date, or `ERR_VENDOR_INSURANCE_EXPIRED`; its `market_id` must equal the
    home's `market_id`, and an explicitly supplied cross-market vendor is refused with
    `ERR_MARKET_MISMATCH`; it must hold a certification whose `certification_code` equals the work
    order's scope template `certification_code`, whose `status` is `ACTIVE`, whose `effective_on`
    is on or before the clock date and whose `expires_on` is on or after the clock date, or
    `ERR_VENDOR_NOT_CERTIFIED`".  On the automatic path, PRD SS3.4: "the system builds the
    eligible set from every vendor in the home's market that passes all of the clauses above",
    and "If the eligible set is empty, the dispatch is refused with `ERR_NO_ELIGIBLE_VENDOR`."
    PRD SS3.4 on the other branch: "The branch requires that the work order's scope template is
    not `safety_critical` -- a safety-critical scope on the in-house bench is refused with
    `ERR_IN_HOUSE_SAFETY_CRITICAL`".  Nothing may be left behind -- PRD SS2.9: "if a guard
    rejects the operation, nothing at all is written, including the cascade targets", and PRD
    SS2.9 on the labour ledger: "For every vendor, `committed_crew_days` always equals the sum of
    `crew_days` over that vendor's work orders whose `status` is `DISPATCHED` or `ACCEPTED`."  The
    HVAC benchmark is the PRD's own: PRD SS3.3 works "612450 * 10250 / 10000 = 627761.25 ->
    627761" for a single system.

    Design: Corner/validations/dispatch_rejects_expired_cross_market_and_safety_critical_assignments
    """
    x.set_clock(api, CLOCK_AUG_01)
    atl = x.create_market(api)
    dal = x.create_market(api, f.dallas_market_payload())
    paint = x.create_scope_template(api, f.scope_template_paint())
    hvac = x.create_scope_template(api, f.scope_template_hvac())
    home = x.create_home(api, atl["id"])

    lapsed = x.create_vendor(
        api,
        atl["id"],
        legal_name="Lapsed Cover Painting",
        cost_index_bps=9700,
        quality_score_bps=8800,
        insurance_expires_on="2026-07-31",
    )
    x.certify_vendor(api, lapsed["id"], "PAINT")
    cross_market = x.create_vendor(
        api,
        dal["id"],
        legal_name="Trinity Coatings",
        daily_crew_capacity=8,
        cost_index_bps=9600,
        quality_score_bps=9000,
        insurance_expires_on="2027-01-31",
    )
    x.certify_vendor(api, cross_market["id"], "PAINT")
    uncertified = x.create_vendor(
        api,
        atl["id"],
        legal_name="Uncertified Crews LLC",
        cost_index_bps=9500,
        quality_score_bps=9100,
        insurance_expires_on="2027-01-31",
    )

    paint_order = created(
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
    hvac_order = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                hvac["id"],
                work_type="RESIDENT_MAINTENANCE",
                quoted_cost_cents=640000,
                scheduled_start_date="2026-08-17",
                scheduled_end_date="2026-08-19",
            ),
            x.OPS,
        )
    )

    failed(
        api.dispatch_work_order(paint_order["id"], {"vendor_id": lapsed["id"]}, x.OPS),
        ERR_VENDOR_INSURANCE_EXPIRED,
    )
    failed(
        api.dispatch_work_order(paint_order["id"], {"vendor_id": cross_market["id"]}, x.OPS),
        ERR_MARKET_MISMATCH,
    )
    failed(
        api.dispatch_work_order(paint_order["id"], {"vendor_id": uncertified["id"]}, x.OPS),
        ERR_VENDOR_NOT_CERTIFIED,
    )
    failed(api.dispatch_work_order(paint_order["id"], {}, x.OPS), ERR_NO_ELIGIBLE_VENDOR)
    failed(
        api.dispatch_work_order(hvac_order["id"], {}, x.OPS), ERR_IN_HOUSE_SAFETY_CRITICAL
    )

    stalled = ok(api.get_work_order(paint_order["id"], x.OPS))
    assert_fields(stalled, status=WO_PENDING_DISPATCH)
    assert_absent_or_empty(stalled, "vendor_id")

    untouched_hvac = ok(api.get_work_order(hvac_order["id"], x.OPS))
    assert_fields(untouched_hvac, status=WO_PENDING_DISPATCH)
    assert_money_group(untouched_hvac, benchmark_total_cents=627761)

    for vendor in (lapsed, cross_market, uncertified):
        assert_fields(
            ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER)), committed_crew_days=0
        )


def test_completing_an_unassigned_vendor_order_names_rank_250_not_the_state_guard(api):
    """Same call, same status, two channels: one reports the structural gap, the other the state.

    PRD SS2.7 is explicit about the ordering: "**Rank 250 -- vendor-channel work order with no
    assigned vendor.** `ERR_WORK_ORDER_NOT_ASSIGNED` (409) on work-order accept and complete. This
    structural check deliberately runs **before** the state guard at rank 300, so accepting or
    completing a `VENDOR`-channel work order whose `vendor_id` is still the empty string reports
    `ERR_WORK_ORDER_NOT_ASSIGNED` no matter which status the row sits in."  Rank 300 is the
    fallback: "**Rank 300 -- undefined transition.** `ERR_INVALID_STATE` (409) whenever a
    transition is not defined from the row's current status", and "Evaluation stops at the first
    violated rule, and only that rule's error is reported."  On the in-house channel there is
    nothing for rank 250 to catch -- PRD SS3.4: "On the `IN_HOUSE` branch the work order moves
    `PENDING_DISPATCH -> IN_PROGRESS` directly, `vendor_id` stays the empty string".  Both rows
    keep the creation defaults, PRD SS3.3: "A new work order is created in `PENDING_DISPATCH` with
    `vendor_id` the empty string, `actual_cost_cents` 0, `completed_on` the empty string".

    Design: Corner/validations/unassigned_vendor_channel_order_reports_v250_before_the_state_guard
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])

    vendor_channel = created(
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
    in_house = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                scheduled_start_date="2026-08-17",
                scheduled_end_date="2026-08-19",
            ),
            x.OPS,
        )
    )
    assert_absent_or_empty(vendor_channel, "vendor_id")
    assert_absent_or_empty(in_house, "vendor_id")

    structural = failed(
        api.complete_work_order(
            vendor_channel["id"],
            f.complete_work_order_payload(300000, "2026-08-12"),
            x.OPS,
        ),
        ERR_WORK_ORDER_NOT_ASSIGNED,
    )
    assert structural.get("error_id") != ERR_INVALID_STATE

    failed(
        api.complete_work_order(
            in_house["id"], f.complete_work_order_payload(300000, "2026-08-19"), x.OPS
        ),
        ERR_INVALID_STATE,
    )

    for order in (vendor_channel, in_house):
        after = ok(api.get_work_order(order["id"], x.OPS))
        assert_fields(after, status=WO_PENDING_DISPATCH)
        assert_money_group(after, actual_cost_cents=0)
        assert_absent_or_empty(after, "completed_on")
