"""Extension fork: CONFIRM extends the booking and reserves added capacity, while
REJECT leaves the booking untouched.
"""
from test_helpers import (
    get_success_data,
    setup_stored_booking,
)

THREE_BAGS_ONE_OVERSIZE = [
    {"declared_value_cents": 20000, "dimension_sum_cm": 100},
    {"declared_value_cents": 20000, "dimension_sum_cm": 100},
    {"declared_value_cents": 20000, "dimension_sum_cm": 160},
]


def _stored_with_extension(api, new_check_out_date):
    ctx, booking, bags = setup_stored_booking(
        api, tier="PREMIUM", per_bag_coverage_cents=50000, premium_cents_per_bag_day=200,
        bags=THREE_BAGS_ONE_OVERSIZE, seal_codes=["K0", "K1", "K2"],
        check_in_date="2026-06-10", check_out_date="2026-06-13")
    extension = get_success_data(api.create_extension(
        booking["id"], {"new_check_out_date": new_check_out_date}, ctx["traveler_headers"]))
    return ctx, booking, extension


def test_extension_confirm_records_status_and_cost(api):
    """PRD §3.5: "That incremental cost covers the added days only: it is the sum, over
    `added_days`, of the per-day storage charge (`per_bag_day_rate_cents` times `bag_count`),
    the per-day oversize surcharge (`oversize_surcharge_cents_per_day` times `oversize_count`),
    and the per-day insurance premium (`premium_cents_per_bag_day` times `bag_count`)."

    Design: Difficulty/non_linear_state_machine/extension_branch_confirm_extends_booking
    """
    ctx, booking, extension = _stored_with_extension(api, "2026-06-16")
    assert extension["added_days"] == 3
    confirmed = get_success_data(api.decide_extension(
        extension["id"], {"decision": "CONFIRM"}, ctx["host_headers"]))
    assert confirmed["status"] == "CONFIRMED"
    # per day: 500*3 + 300*1 + 200*3 = 2400; over 3 days = 7200
    assert confirmed["added_cost_cents"] == 7200


def test_extension_confirm_advances_booking_and_estimate(api):
    """PRD §3.5: "On confirmation the booking's `check_out_date` is advanced to the
    `new_check_out_date`, the booking's `billable_days` and `estimated_total_cents` are
    recomputed to include the added days, the location reserves capacity for the added
    interval, and the extension records its `added_cost_cents`."

    Design: Difficulty/non_linear_state_machine/extension_branch_confirm_extends_booking
    """
    ctx, booking, extension = _stored_with_extension(api, "2026-06-16")
    get_success_data(api.decide_extension(extension["id"], {"decision": "CONFIRM"}, ctx["host_headers"]))
    updated = get_success_data(api.get_booking(booking["id"], ctx["traveler_headers"]))
    assert updated["check_out_date"] == "2026-06-16"
    # billable_days now 6: base 500*3*6 + oversize 300*1*6 + insurance 200*3*6 = 14400
    assert updated["estimated_total_cents"] == 14400


def test_extension_reject_leaves_booking_unchanged(api):
    """PRD §3.5: "Rejecting an extension leaves the booking untouched — its pickup date and
    all derived amounts are unchanged."

    Design: Corner/state_machines/extension_reject_leaves_booking_unchanged
    """
    ctx, booking, extension = _stored_with_extension(api, "2026-06-16")
    rejected = get_success_data(api.decide_extension(
        extension["id"], {"decision": "REJECT"}, ctx["host_headers"]))
    assert rejected["status"] == "REJECTED"
    updated = get_success_data(api.get_booking(booking["id"], ctx["traveler_headers"]))
    assert updated["check_out_date"] == "2026-06-13"
    assert updated["estimated_total_cents"] == 7200
