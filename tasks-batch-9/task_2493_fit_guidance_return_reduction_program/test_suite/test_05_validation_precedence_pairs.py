"""Requests that break two rules at once.

The validation ladder is evaluated top to bottom and stops at the first failure, so
when two conditions are both violated the error the client sees is decided by rank
and not by which check is cheaper to run.  Each scenario here arms both rules and
then proves the lower-ranked one really would have fired on its own.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    ApiErrorId,
    create_return_case_payload,
    grade_rule,
    make_customer_headers,
    make_returns_auditor_headers,
    make_vendor_user_headers,
    resubmit_measurement_spec_payload,
    size_point,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx  # noqa: E402

# A five-size chest run whose M-to-L step of 46 millimetres breaks the enforced
# five-millimetre tolerance, so verification requests a correction.
VIOLATING_FIVE_SIZE_POINTS = [
    size_point("XS", 0, 800, 720, 840, 700),
    size_point("S", 1, 840, 760, 880, 710),
    size_point("M", 2, 880, 800, 920, 720),
    size_point("L", 3, 926, 845, 965, 730),
    size_point("XL", 4, 965, 885, 1005, 740),
]

CORRECTED_FIVE_SIZE_POINTS = [
    size_point("XS", 0, 800, 720, 840, 700),
    size_point("S", 1, 840, 760, 880, 710),
    size_point("M", 2, 880, 800, 920, 720),
    size_point("L", 3, 925, 845, 965, 730),
    size_point("XL", 4, 965, 885, 1005, 740),
]

CHEST_GRADE_RULES = [grade_rule("CHEST", 40, 1250, 3)]


def _correction_requested_spec_on_new_item(
    api: ApiClient, vendor_id: str, sku: str
) -> dict:
    """A listed item under an existing brand whose specification has failed
    verification once, so it waits at correction-requested and the brand has been
    charged for the round."""
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor_id,
            sku=sku,
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    spec = fx.create_spec(
        api,
        item["id"],
        vendor_id,
        size_system="US_ALPHA",
        base_size_label="M",
        fabric_stretch_class="RIGID",
        size_points=VIOLATING_FIVE_SIZE_POINTS,
        grade_rules=CHEST_GRADE_RULES,
    )
    fx.submit_spec(api, spec["id"], vendor_id)
    spec = fx.verify_spec(api, spec["id"])
    return {"item": item, "spec": spec}


def _build_delisted_item_and_overdrawn_brand(api: ApiClient) -> dict:
    """A brand whose 2,000-cent allowance has already been overspent by one
    2,500-cent correction round, and whose item has since been delisted, so a
    resubmission now breaks the delisting rule and the allowance rule together."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Budget Basics", brand_code="BDGT", correction_budget_cents=2000
    )
    built = _correction_requested_spec_on_new_item(api, vendor["id"], "BDGT-TEE-01")
    built["vendor"] = vendor
    built["item"] = fx.delist_item(
        api, built["item"]["id"], delist_reason_code="MANUAL"
    )
    return built


def test_a_delisted_item_is_reported_ahead_of_an_overdrawn_correction_allowance(api):
    """PRD §2.9: "A resubmission by a suspended vendor whose allowance is also
    exhausted reports `ERR_VENDOR_SUSPENDED`, not
    `ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED`, because vendor standing sits at rank 17
    and the allowance check sits at rank 31."  The delisting rule sits at rank 9,
    earlier still, so a resubmission that breaks both reports the delisting with HTTP
    409 rather than the allowance refusal's HTTP 402.

    Design: Difficulty/priority_pair_validation_conflict/delisted_item_outranks_vendor_budget_exhausted_on_resubmit
    """
    built = _build_delisted_item_and_overdrawn_brand(api)

    assert built["spec"]["status"] == "CORRECTION_REQUESTED"
    assert built["item"]["listing_status"] == "DELISTED"

    response = api.resubmit_measurement_spec(
        built["spec"]["id"],
        resubmit_measurement_spec_payload(CORRECTED_FIVE_SIZE_POINTS),
        make_vendor_user_headers(built["vendor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ITEM_DELISTED.value, 409)


def test_the_refused_resubmit_leaves_the_specification_exactly_where_it_stood(api):
    """PRD §3.1: "Once an item is `DELISTED`, the ten operations listed at rank 9 of
    §2.9 refuse to touch it with `ERR_ITEM_DELISTED`."  Refusing to touch it means
    the revision round does not advance, the correction reason is not cleared, and
    the brand is not charged a second time.

    Design: Difficulty/priority_pair_validation_conflict/delisted_item_outranks_vendor_budget_exhausted_on_resubmit
    """
    built = _build_delisted_item_and_overdrawn_brand(api)

    api.resubmit_measurement_spec(
        built["spec"]["id"],
        resubmit_measurement_spec_payload(CORRECTED_FIVE_SIZE_POINTS),
        make_vendor_user_headers(built["vendor"]["id"]),
    )

    spec = fx.read_spec(api, built["spec"]["id"])
    assert spec["status"] == "CORRECTION_REQUESTED"
    assert spec["revision_round"] == 0
    assert spec["correction_reason"] == "GRADE_TOLERANCE_VIOLATION"

    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["correction_round_count"] == 1
    assert vendor["correction_spend_cents"] == 2500
    assert vendor["status"] == "PROBATION"


def test_the_allowance_rule_that_was_outranked_refuses_a_still_listed_item(api):
    """PRD §3.2: "Resubmission is permitted only from `CORRECTION_REQUESTED`, only by
    the owning brand, only while the item is not `DELISTED`, and only while
    `correction_spend_cents` is less than or equal to `correction_budget_cents` — an
    overdrawn allowance blocks the resubmission with
    `ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED` and HTTP 402."  The same overdrawn brand
    resubmitting against an item that is still listed hits exactly that refusal, which
    is what makes the delisted case a genuine conflict rather than a single failure.

    Design: Difficulty/priority_pair_validation_conflict/delisted_item_outranks_vendor_budget_exhausted_on_resubmit
    """
    built = _build_delisted_item_and_overdrawn_brand(api)
    second = _correction_requested_spec_on_new_item(
        api, built["vendor"]["id"], "BDGT-TEE-02"
    )

    assert second["item"]["listing_status"] == "LISTED"
    vendor = fx.read_vendor(api, built["vendor"]["id"])
    assert vendor["correction_spend_cents"] > vendor["correction_budget_cents"]

    response = api.resubmit_measurement_spec(
        second["spec"]["id"],
        resubmit_measurement_spec_payload(CORRECTED_FIVE_SIZE_POINTS),
        make_vendor_user_headers(built["vendor"]["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_VENDOR_CORRECTION_BUDGET_EXHAUSTED.value, 402
    )


def _build_blocked_shopper_with_a_lapsed_line(api: ApiClient) -> dict:
    """A shopper carrying three live cases across four delivered lines, which puts
    the return rate at 7,500 basis points and blocks them, plus a fourth line whose
    shortened window closed back in January."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    vendor = fx.create_vendor(
        api, name="Blocked Basics", brand_code="BLKD", correction_budget_cents=10000
    )
    item = fx.list_item(
        api,
        fx.create_item(
            api,
            vendor["id"],
            sku="BLKD-TEE-01",
            category_code="TOPS",
            brand_size_system="US_ALPHA",
            unit_price_cents=2295,
        )["id"],
    )
    fx.create_policy(
        api,
        category_code="TOPS",
        window_days=30,
        restocking_applies=True,
        non_refundable_shipping=False,
        effective_from="2026-01-01T00:00:00Z",
    )
    customer = fx.create_customer(api, email="shopper-r5b@example.com")

    def line(size_label: str, delivered_at: str) -> dict:
        return fx.create_order_line(
            api,
            customer["id"],
            item["id"],
            size_label=size_label,
            quantity=1,
            unit_price_cents=2295,
            shipping_allocated_cents=0,
            delivered_at=delivered_at,
        )

    recent = [line("M", "2026-05-20T00:00:00Z") for _ in range(3)]
    lapsed = line("L", "2026-01-05T00:00:00Z")

    for order_line, reason in zip(
        recent, ("FIT_TOO_SMALL", "FIT_TOO_LARGE", "EXPECTATION_MISMATCH")
    ):
        fx.open_case(
            api, order_line["id"], customer["id"], requested_reason_code=reason
        )

    return {
        "item": item,
        "customer": fx.read_customer(api, customer["id"]),
        "lapsed_line": lapsed,
    }


def test_blocked_standing_is_reported_ahead_of_the_closed_return_window(api):
    """PRD §2.9: "And a return-case create by a blocked shopper past the deadline
    reports `ERR_CUSTOMER_RETURN_BLOCKED`, because rank 13 precedes rank 14."  The
    lapsed line's shortened fifteen-day window ran out on 20 January, months before
    the clock, yet the refusal is the standing one with HTTP 409 rather than the
    window's HTTP 422.

    Design: Difficulty/priority_pair_validation_conflict/blocked_customer_outranks_closed_return_window
    """
    built = _build_blocked_shopper_with_a_lapsed_line(api)

    assert built["customer"]["abuse_status"] == "BLOCKED"

    response = api.create_return_case(
        create_return_case_payload(
            built["lapsed_line"]["id"], requested_reason_code="FIT_TOO_SMALL"
        ),
        make_customer_headers(built["customer"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CUSTOMER_RETURN_BLOCKED.value, 409)


def test_the_rate_rule_blocks_a_shopper_who_never_earned_a_single_strike(api):
    """PRD §3.8: "Note that the rate rule can block a shopper who never earned a
    single change-of-mind strike, so this axis is not a strict ladder — a `CLEAR`
    shopper can jump straight to `BLOCKED` after a return-case creation, a
    resolution, a void, or an ops-run, and can drop straight back to `CLEAR` when a
    void removes a case or an ops-run ages every strike out, provided their strike
    count is below 1 and the rate rule no longer holds."  Three live cases over four
    purchased lines put the rate at 7,500 basis points with the strike count still at
    0, and the block in turn shortens every future window.

    Design: Difficulty/priority_pair_validation_conflict/blocked_customer_outranks_closed_return_window
    """
    built = _build_blocked_shopper_with_a_lapsed_line(api)
    customer = built["customer"]

    assert customer["purchase_line_count"] == 4
    assert customer["return_case_count"] == 3
    assert customer["return_rate_bp"] == 7500
    assert customer["abuse_strike_count"] == 0
    assert customer["abuse_status"] == "BLOCKED"
    assert customer["policy_class"] == "RESTRICTED_WINDOW"


def test_the_refused_open_writes_no_case_and_leaves_the_line_delivered(api):
    """PRD §3.7: "A shopper whose `abuse_status` is `BLOCKED` cannot open one at all:
    the request is refused with `ERR_CUSTOMER_RETURN_BLOCKED`."  Nothing at all is
    written: the lapsed line keeps its delivered status, no case is attached to it,
    and the shopper's own case count does not move.

    Design: Difficulty/priority_pair_validation_conflict/blocked_customer_outranks_closed_return_window
    """
    built = _build_blocked_shopper_with_a_lapsed_line(api)

    api.create_return_case(
        create_return_case_payload(
            built["lapsed_line"]["id"], requested_reason_code="FIT_TOO_SMALL"
        ),
        make_customer_headers(built["customer"]["id"]),
    )

    order_line = fx.read_order_line(api, built["lapsed_line"]["id"])
    assert order_line["status"] == "DELIVERED"

    rows, _ = validate_paginated(
        api.list_return_cases(
            make_returns_auditor_headers(),
            {"order_line_id": built["lapsed_line"]["id"]},
        )
    )
    assert rows == []

    customer = fx.read_customer(api, built["customer"]["id"])
    assert customer["return_case_count"] == 3
