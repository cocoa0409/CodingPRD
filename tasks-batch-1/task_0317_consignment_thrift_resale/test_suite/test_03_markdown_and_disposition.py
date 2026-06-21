"""Markdown pricing over the aging clock and unsold-stock disposition.

Covers markdown aged-read and floor corner instances, donation valuation, the
return-window half-open interval difficulty instance, and the dispose-before-
window corner.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_item, assert_donation_record,
    TEST_USERS,
    set_clock, setup_on_floor_item,
)

ADMIN = TEST_USERS["store_admin_headers"]
GRADER = TEST_USERS["intake_grader_headers"]
CASHIER = TEST_USERS["cashier_clerk_headers"]
SETTLER = TEST_USERS["settlement_manager_headers"]

# Three-tier schedule used by the aging-read corner instances.
THREE_TIERS = [
    {"min_age_days": 0, "discount_pct": 0.0},
    {"min_age_days": 30, "discount_pct": 0.20},
    {"min_age_days": 60, "discount_pct": 0.40},
]


def test_markdown_aged_read_selects_correct_tier(api):
    """PRD §3.4: "the applicable tier is selected as a step function: among all
    tiers whose `min_age_days` is less than or equal to the item's age in days,
    the one with the greatest `min_age_days` wins. A raw price is then computed by
    multiplying the `list_price_cents` by one minus that tier's `discount_pct` and
    rounding the product half up to a whole cent."

    Design: Corner/calculations/markdown_aged_read_selects_correct_tier
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, _, item = setup_on_floor_item(
        list_price_cents=10000, base_floor_pct=0.30, tiers=THREE_TIERS,
        consignor_email="age@x.com")
    set_clock("2026-07-01T00:00:00Z")  # 30 days on floor -> tier-30 (20% off)
    read = validate_success(api.get_item(item["id"], CASHIER), 200)
    assert read["current_price_cents"] == 8000, (
        f"expected 8000 at age 30, got {read['current_price_cents']}")


def test_markdown_floors_at_base_floor_for_deep_age(api):
    """PRD §3.4: "Independently, a floor price is computed by multiplying the
    `list_price_cents` by the schedule's `base_floor_pct` and flooring the product
    to a whole cent. The `current_price_cents` is whichever of the raw price and
    the floor price is greater."

    Design: Corner/calculations/markdown_floors_at_base_floor_for_deep_age
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, _, item = setup_on_floor_item(
        list_price_cents=10000, base_floor_pct=0.30, tiers=THREE_TIERS,
        consignor_email="deep@x.com")
    set_clock("2026-12-18T00:00:00Z")  # 200 days -> tier-60 (40% off): raw 6000 > floor 3000
    read = validate_success(api.get_item(item["id"], CASHIER), 200)
    assert read["current_price_cents"] == 6000, (
        f"expected 6000 at deep age, got {read['current_price_cents']}")


def test_donation_record_returned_disposition_zero_receipt(api):
    """PRD §3.8: "When the disposition is `RETURN_TO_CONSIGNOR`, the item advances
    `ON_FLOOR → RETURNED` and a `DonationRecord` is created with a `disposition`
    of `RETURNED` and a `tax_receipt_value_cents` of 0."

    Design: Corner/calculations/donation_record_returned_disposition_zero_receipt
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, _, item = setup_on_floor_item(
        list_price_cents=10000, unsold_disposition="RETURN_TO_CONSIGNOR",
        return_window_days=90, consignor_email="ret@x.com")
    set_clock("2026-08-30T00:00:00Z")  # 90 days -> past window (>=)
    rec = validate_success(api.dispose_item(item["id"], SETTLER), 201)
    assert_donation_record(rec)
    assert rec["disposition"] == "RETURNED"
    assert rec["tax_receipt_value_cents"] == 0
    after = validate_success(api.get_item(item["id"], GRADER), 200)
    assert after["listing_status"] == "RETURNED"


def test_dispose_before_window_returns_return_window_not_elapsed(api):
    """PRD §3.8: "A `SettlementManager` or `StoreAdmin` disposes of an on-floor
    item only once it has passed its return window — that is, the item's age since
    `floor_date` is at least the agreement's `return_window_days`; disposing
    before the window has elapsed is rejected with `ERR_RETURN_WINDOW_NOT_ELAPSED`."

    Design: Corner/state_machines/dispose_before_window_returns_return_window_not_elapsed
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, _, item = setup_on_floor_item(
        list_price_cents=10000, unsold_disposition="DONATE",
        return_window_days=90, consignor_email="win@x.com")
    set_clock("2026-06-11T00:00:00Z")  # only 10 days on floor
    res = api.dispose_item(item["id"], SETTLER)
    validate_error(res, "ERR_RETURN_WINDOW_NOT_ELAPSED", expected_status=409)


# ─── Difficulty: resource temporal overlap — return-window half-open interval ─

def test_at_window_boundary_pull_rejected_dispose_allowed(api):
    """PRD §3.4: "Pulling is only allowed while the item is `ON_FLOOR` and has
    **not** yet passed its return window — that is, the item's age since
    `floor_date` is strictly less than the agreement's `return_window_days`; an
    attempt to pull an item already past its window is rejected with
    `ERR_RETURN_WINDOW_ELAPSED`."
    PRD §3.8: "the item's age since `floor_date` is at least the agreement's
    `return_window_days`; disposing before the window has elapsed is rejected with
    `ERR_RETURN_WINDOW_NOT_ELAPSED`."

    Design: Difficulty/resource_temporal_overlap/item_return_window_half_open_interval_on_floor_age
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, _, item = setup_on_floor_item(
        list_price_cents=10000, unsold_disposition="DONATE",
        return_window_days=90, consignor_email="window@x.com")
    set_clock("2026-08-30T00:00:00Z")  # exactly 90 days -> at/over the window
    pull_res = api.pull_item(item["id"], GRADER)
    validate_error(pull_res, "ERR_RETURN_WINDOW_ELAPSED", expected_status=409)
    rec = validate_success(api.dispose_item(item["id"], SETTLER), 201)
    after = validate_success(api.get_item(item["id"], GRADER), 200)
    assert after["listing_status"] == "DONATED"
    assert rec["tax_receipt_value_cents"] == 2500, (
        f"floor(10000*0.25)=2500, got {rec['tax_receipt_value_cents']}")


def test_before_window_boundary_pull_allowed_dispose_rejected(api):
    """PRD §3.4: "Pulling is only allowed while the item is `ON_FLOOR` and has
    **not** yet passed its return window — that is, the item's age since
    `floor_date` is strictly less than the agreement's `return_window_days`."
    PRD §3.8: "disposing before the window has elapsed is rejected with
    `ERR_RETURN_WINDOW_NOT_ELAPSED`."

    Design: Difficulty/resource_temporal_overlap/item_return_window_half_open_interval_on_floor_age
    """
    set_clock("2026-06-01T00:00:00Z")
    _, _, _, _, item = setup_on_floor_item(
        list_price_cents=10000, unsold_disposition="DONATE",
        return_window_days=90, consignor_email="window2@x.com")
    set_clock("2026-08-29T00:00:00Z")  # 89 days -> strictly inside the window
    dispose_res = api.dispose_item(item["id"], SETTLER)
    validate_error(dispose_res, "ERR_RETURN_WINDOW_NOT_ELAPSED", expected_status=409)
    pulled = validate_success(api.pull_item(item["id"], GRADER), 200)
    assert pulled["listing_status"] == "PULLED"
