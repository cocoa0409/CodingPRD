"""The customer's return-risk score: the ROLLING/STRICT variant boundary and the
gate that locks a risky customer out of new kits."""

from test_helpers import (
    ApiErrorId,
    create_kit_payload,
    make_customer_headers,
    read_customer,
    read_frame,
    read_kit,
    set_clock,
    setup_risk_score_at_seventy,
    setup_three_kit_strict_history,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN


# ═════════════════════════════════════════════════════════════════════════════
# Dual variant — ROLLING (fewer than three kits) vs STRICT (three or more)
# ═════════════════════════════════════════════════════════════════════════════

def test_third_history_kit_switches_the_score_onto_the_strict_variant(api):
    """PRD §3.4: "**The STRICT variant** applies when `lifetime_kit_count` is **three
    or more**. Enough history exists to average over the whole relationship, so the
    window holds **every** kit in the history regardless of `due_date`, and no cutoff
    is applied at all."
    PRD §3.4: "Otherwise the system counts two things across the window: the number of
    kits whose `kept_count` is zero (the customer borrowed and bought nothing), and the
    number of kits whose `was_overdue` flag is true (the customer held the samples past
    the deadline). A kit can contribute to both counts. The zero-kept count is weighted
    at six tenths, the overdue count at four tenths; the two weighted counts are added,
    divided by the number of kits in the window, multiplied by one hundred, and the
    result is rounded half up to a whole integer."

    Three history kits — one old clean one (due 2025-11-12), two zero-kept overdue ones
    — put the count at three, so STRICT admits all three: 100 * (0.6*2 + 0.4*2) / 3
    rounds half up to 67. Under ROLLING the 2025-11-12 kit would fall outside the
    180-day window and the score would read 100 instead.

    Design: Difficulty/dual_variant_calc/risk_score_rolling_vs_strict_variant_on_customer
    """
    scenario = setup_three_kit_strict_history()

    resp = api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN)
    validate_success(resp, 200)

    customer = read_customer(scenario["customer"]["id"])
    assert customer["lifetime_kit_count"] == 3
    assert customer["return_risk_score"] == 67, (
        "STRICT keeps the old clean kit in the denominator; ROLLING would score 100"
    )


def test_the_clock_that_completes_the_history_also_flips_the_third_kit_overdue(api):
    """PRD §2.5: "Second, every `SHIPPED` home try-on kit whose `due_date` is strictly
    before the new clock value transitions to `OVERDUE`, latches `was_overdue` to true,
    increments its own `version`, and triggers a recomputation of its owning customer's
    `return_risk_score`."
    PRD §3.4: "The fee is five hundred cents for each day late, and it is then clamped
    to a ceiling of five thousand cents — so a kit ten or more days late incurs the same
    fifty-dollar maximum as a kit a hundred days late."

    The second kit came back eight days late, so its fee is 8 * 500 == 4,000c, short of
    the ceiling.

    Design: Difficulty/dual_variant_calc/risk_score_rolling_vs_strict_variant_on_customer
    """
    scenario = setup_three_kit_strict_history()

    clock = validate_success(
        api.set_clock({"to_iso8601": "2026-05-20T00:00:00Z"}, ADMIN), 200
    )
    assert scenario["kit_two"]["id"] in clock["overdue_kit_ids"]

    kit_two = read_kit(scenario["kit_two"]["id"])
    assert kit_two["status"] == "OVERDUE"
    assert kit_two["was_overdue"] is True

    kit_one = read_kit(scenario["kit_one"]["id"])
    assert kit_one["late_fee_cents"] == 4000, "eight days late at five hundred cents a day"


# ═════════════════════════════════════════════════════════════════════════════
# The gate fires at exactly seventy
# ═════════════════════════════════════════════════════════════════════════════

def test_risk_gate_blocks_a_new_kit_at_a_score_of_exactly_seventy(api):
    """PRD §3.4: "The requesting customer's `return_risk_score` must be **strictly below
    70** — the gate fires at a score of exactly 70 and above, not merely above 70 — or
    the request is refused with `ERR_CUSTOMER_TRYON_BLOCKED`."
    PRD §3.4: "That integer is the customer's `return_risk_score`, and once it reaches 70
    the customer is locked out of new kits until returns bring it back down."

    Two overdue kits — one that kept a frame, one that kept nothing — score
    100 * (0.6 * 1 + 0.4 * 2) / 2 == 70 exactly.

    Design: Corner/cross_cutting_complexity_layers/risk_gate_blocks_a_new_kit_at_exactly_seventy
    """
    scenario = setup_risk_score_at_seventy()
    customer_id = scenario["customer"]["id"]

    customer = read_customer(customer_id)
    assert customer["lifetime_kit_count"] == 2
    assert customer["return_risk_score"] == 70

    resp = api.create_home_try_on_kit(
        create_kit_payload(
            customer_id,
            [scenario["frame"]["id"]],
            "2026-02-11T00:00:00Z",
            "2026-02-21T00:00:00Z",
        ),
        make_customer_headers(customer_id),
    )
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_TRYON_BLOCKED.value)

    assert scenario["kit_two"]["late_fee_cents"] == 5000, (
        "the second kit came back ten days late, at the clamped ceiling"
    )
    assert read_frame(scenario["frame"]["id"])["tryon_available"] == 3, (
        "both kits released their holds; the blocked request took none"
    )
