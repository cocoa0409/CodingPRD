"""Two pairs of calculations that read the same events and deliberately disagree.

A correction notice carries a terminal-provisional delta and an audit-final
delta; a shipper account carries a rolling liability index and a lifetime one.
In both pairs only one member of the pair drives anything.
"""

from test_helpers import (
    assert_correction_notice,
    assert_credit_memo,
    assert_customer,
    assert_customer_offender_record,
    factories,
)
from test_helpers import fixtures as fx

CLOCK = "2026-01-10T08:00:00Z"


def _two_line_capture_scenario():
    """A two-line billed shipment measured 200 pounds heavy with one line reclassed."""
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_two_line_billed_shipment(
        env=env,
        pro_number="PRO1001",
        shipment_overrides={"bol_declared_total_weight_lb": 1100},
    )
    assert scenario["shipment"]["original_charge_cents"] == 26754
    scenario["capture_event"] = fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        1300,
        [
            factories.line_measurement(1, 520, 48.0, 40.0, 48.0),
            factories.line_measurement(2, 780, 40.0, 40.0, 40.0),
        ],
    )
    scenario["notice"] = fx.find_draft_notice(scenario["shipment_id"])
    return scenario


def _liability_scenario():
    """One notice resolved UPHELD_CARRIER in February and a second notice, raised
    manually in June against the same capture, disputed and awaiting resolution."""
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_issued_notice_scenario(
        env=env, pro_number="PRO2001", measured_total_weight_lb=520
    )
    assert scenario["shipment"]["original_charge_cents"] == 12500

    first_dispute = fx.file_dispute(
        scenario["notice_id"], scenario["customer_id"], evidence_doc_count=1
    )
    fx.set_clock("2026-02-05T00:00:00Z")
    fx.resolve_dispute(
        first_dispute["id"],
        "UPHELD_CARRIER",
        resolution_note="Dimensioner evidence stands.",
    )

    fx.set_clock("2026-06-01T00:00:00Z")
    second_notice = fx.draft_manual_notice(
        scenario["shipment_id"],
        notice_type="RECLASS",
        basis_capture_event_id=scenario["capture_event"]["id"],
    )
    fx.issue_notice(second_notice["id"])
    second_dispute = fx.file_dispute(
        second_notice["id"],
        scenario["customer_id"],
        claim_basis="EXCEPTION_AGREEMENT",
        evidence_doc_count=2,
    )

    scenario["first_notice_id"] = scenario["notice_id"]
    scenario["second_notice_id"] = second_notice["id"]
    scenario["second_dispute_id"] = second_dispute["id"]
    return scenario


# ==========================================================================
# Provisional versus audit-final correction delta
# ==========================================================================


def test_provisional_delta_prices_each_line_on_its_own_weight_break():
    """The dock-quoted variant rounds per line and never applies the minimum charge.

    PRD: "For each line, an amount is formed as the line's weight divided by 100,
    multiplied by the program's `base_rate_per_cwt_cents`, multiplied by a class
    divided by 100, multiplied by a weight-break factor derived from *that line's
    own weight* rather than from the shipment total, multiplied by one minus the
    program's `discount_pct`, and rounded to a whole number of cents *for that
    line alone*."

    Design: Difficulty/dual_variant_calc/notice_provisional_versus_audit_final_delta_divergence
    """
    scenario = _two_line_capture_scenario()

    notice = scenario["notice"]

    assert_correction_notice(notice)
    assert notice["provisional_delta_cents"] == 33388, (
        f"per-line weight breaks and per-line rounding give 33388, "
        f"got {notice['provisional_delta_cents']}"
    )


def test_final_delta_prices_the_shipment_on_its_aggregate_weight_break():
    """The audit-final variant differs from the provisional one on identical data.

    PRD: "Because the weight break is aggregate rather than per line, because the
    rounding happens once rather than per line, and because the floor applies,
    the two variants produce different numbers on identical data."

    Design: Difficulty/dual_variant_calc/notice_provisional_versus_audit_final_delta_divergence
    """
    scenario = _two_line_capture_scenario()

    notice = scenario["notice"]

    assert notice["final_delta_cents"] == 30030, (
        f"one aggregate weight break and one rounding give 30030, "
        f"got {notice['final_delta_cents']}"
    )
    assert notice["provisional_delta_cents"] - notice["final_delta_cents"] == 3358, (
        "the two variants must diverge by 3358 cents on this data"
    )
    assert notice["notice_type"] == "BOTH"


def test_draft_notice_freezes_no_money_and_leaves_the_ledger_untouched():
    """While the notice is `DRAFT` the applied delta and the fee are both 0 and the
    shipment still shows what it was billed.

    PRD: "At every instant it equals the shipment's `original_charge_cents`, plus the
    sum over every correction notice of that shipment whose `status` is `ISSUED`,
    `DISPUTED`, `EVIDENCE_REQUESTED`, `UPHELD`, `PARTIALLY_OVERTURNED` or
    `OVERTURNED` of that notice's `applied_delta_cents` added to its
    `inspection_fee_cents`, minus the sum over the credit memos of those notices of
    each memo's `freight_credit_cents` added to its `fee_credit_cents`. Notices in
    `DRAFT` or `VOID` contribute nothing."

    Design: Difficulty/dual_variant_calc/notice_provisional_versus_audit_final_delta_divergence
    """
    scenario = _two_line_capture_scenario()

    notice = scenario["notice"]
    shipment = fx.get_shipment(scenario["shipment_id"])
    line_one = fx.get_shipment_line(scenario["line_ids"][0])

    assert notice["status"] == "DRAFT"
    assert notice["applied_delta_cents"] == 0
    assert notice["inspection_fee_cents"] == 0
    assert shipment["assessed_total_cents"] == 26754
    assert line_one["measured_cubic_ft"] == 213.33
    assert line_one["effective_class_code"] == 250
    assert line_one["classification_source"] == "DIMENSIONER"


# ==========================================================================
# Rolling versus lifetime liability index
# ==========================================================================


def test_rolling_index_windows_and_decays_the_contributing_strikes():
    """The February strike has fallen out of the 90-day window, so only the June
    partial overturn contributes, at half weight and undecayed on the same day.

    PRD: "`liability_index_rolling` looks only at contributing notices whose
    `resolved_at` falls at or after 90 days before the current logical instant,
    and decays each of them by age."

    Design: Difficulty/dual_variant_calc/liability_index_rolling_versus_lifetime_divergence
    """
    scenario = _liability_scenario()

    fx.resolve_dispute(
        scenario["second_dispute_id"],
        "PARTIAL",
        outcome_class_code=175,
        resolution_note="Density recomputed to class 175.",
    )
    customer = fx.get_customer(scenario["customer_id"])

    assert_customer(customer)
    assert customer["liability_index_rolling"] == 0.50, (
        f"only the June PARTIALLY_OVERTURNED notice is inside the window, "
        f"got {customer['liability_index_rolling']}"
    )


def test_lifetime_index_keeps_every_resolved_strike_at_full_weight():
    """The lifetime index sums both resolved notices with neither window nor decay,
    and the tier still reads the rolling figure alone.

    PRD: "`offender_tier` is derived from `liability_index_rolling` alone:
    `TIER_3` when the rolling index is at least 6.00, otherwise `TIER_2` when it
    is at least 3.00, otherwise `TIER_1` when it is at least 1.00, otherwise
    `TIER_0`."

    Design: Difficulty/dual_variant_calc/liability_index_rolling_versus_lifetime_divergence
    """
    scenario = _liability_scenario()

    fx.resolve_dispute(
        scenario["second_dispute_id"],
        "PARTIAL",
        outcome_class_code=175,
        resolution_note="Density recomputed to class 175.",
    )
    customer = fx.get_customer(scenario["customer_id"])

    assert customer["liability_index_lifetime"] == 1.50, (
        f"1.0 for the UPHELD notice plus 0.5 for the partial one is 1.50, "
        f"got {customer['liability_index_lifetime']}"
    )
    assert customer["offender_tier"] == "TIER_0"
    assert customer["dispute_window_days"] == 30
    assert customer["offender_strike_count"] == 2, (
        "an UPHELD and a PARTIALLY_OVERTURNED notice both still count as strikes"
    )
    assert_customer_offender_record(customer)


def test_partial_overturn_credits_freight_and_interest_but_no_fee():
    """A partial overturn fills bucket one and bucket three only.

    PRD: "Bucket two is the accessorial fee: `fee_credit_cents` is the notice's
    frozen `inspection_fee_cents` on a full overturn and exactly 0 on a partial
    one, since only a complete reversal refunds the inspection fee."

    Design: Difficulty/dual_variant_calc/liability_index_rolling_versus_lifetime_divergence
    """
    scenario = _liability_scenario()

    fx.resolve_dispute(
        scenario["second_dispute_id"],
        "PARTIAL",
        outcome_class_code=175,
        resolution_note="Density recomputed to class 175.",
    )

    first_notice = fx.get_notice(scenario["first_notice_id"])
    second_notice = fx.get_notice(scenario["second_notice_id"])
    memos = [
        memo
        for memo in fx.list_credit_memos_for(scenario["customer_id"])
        if memo["correction_notice_id"] == scenario["second_notice_id"]
    ]
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert first_notice["status"] == "UPHELD"
    assert second_notice["status"] == "PARTIALLY_OVERTURNED"
    assert second_notice["applied_delta_cents"] == 28314
    assert len(memos) == 1, f"a partial overturn creates exactly one memo, found {len(memos)}"
    memo = memos[0]
    assert_credit_memo(memo)
    assert memo["freight_credit_cents"] == 12245
    assert memo["fee_credit_cents"] == 0
    assert memo["interest_credit_cents"] == 61
    assert memo["amount_cents"] == 12306
    assert shipment["assessed_total_cents"] == 65883
