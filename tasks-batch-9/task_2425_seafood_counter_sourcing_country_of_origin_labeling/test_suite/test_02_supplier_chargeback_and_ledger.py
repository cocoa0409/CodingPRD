"""Dealer chargeback assessment, goodwill banding, settlement and reversal."""
from test_helpers import ApiErrorId, fixtures, validate_error, validate_success
from test_helpers.assertions import (
    assert_cents,
    assert_supplier,
    assert_supplier_chargeback_identity,
)
from test_helpers.test_users import (
    OFFICER_LEDGER_USER_ID,
    make_compliance_officer_headers,
    make_supplier_rep_headers,
)


def _mismatched_tilapia_lot(api, *, lot_code="TIL-0801-B", unit_cost_cents_per_kg=1700,
                            retail_price_cents_per_kg=2300,
                            cooked_retail_price_cents_per_kg=2500,
                            lab_reference="LAB-B-0001") -> dict:
    """A cased and labelled 10.000 kg tilapia lot whose laboratory result names cod."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    tilapia = fixtures.register_tilapia(api)
    lot = fixtures.receive_tilapia_lot(
        api,
        counter_id,
        env["supplier"]["id"],
        tilapia["id"],
        lot_code=lot_code,
        received_weight_kg=10.000,
        unit_cost_cents_per_kg=unit_cost_cents_per_kg,
        retail_price_cents_per_kg=retail_price_cents_per_kg,
        cooked_retail_price_cents_per_kg=cooked_retail_price_cents_per_kg,
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.publish_case_label(api, counter_id, lot["id"])
    sample = fixtures.draw_sample(api, lot["id"])
    fixtures.send_sample_to_lab(api, sample["id"], lab_reference)
    fixtures.record_sample_result(api, sample["id"], env["cod"]["id"])
    env["tilapia"] = tilapia
    env["lot"] = fixtures.read_lot(api, counter_id, lot["id"])
    return env


def _assessed_tilapia_lot(api) -> dict:
    """The default mismatch chain, whose pre-credit subtotal lands in the 8 percent band."""
    return _mismatched_tilapia_lot(api)


def test_01_goodwill_band_is_selected_from_the_pre_credit_subtotal(api):
    """PRD §3.8: "**Step three** selects the goodwill rate from that subtotal, and from
    that subtotal only: a subtotal below 50,000 cents earns a 15 percent goodwill rate, a
    subtotal from 50,000 cents inclusive up to but not including 120,000 cents earns 8
    percent, and a subtotal of 120,000 cents or more earns nothing at all."

    Design: Difficulty/combinatorial_formula/supplier_chargeback_goodwill_tier_pinned_order
    """
    env = _assessed_tilapia_lot(api)

    lot = env["lot"]
    assert lot["chargeback_status"] == "ASSESSED"
    assert_cents(lot["chargeback_assessed_cents"], 47840)
    assert lot["chargeback_assessed_cents"] != 44200, (
        "44200 would be the 15 percent band applied to the same 52000 cent subtotal"
    )


def test_02_assessment_pushes_the_whole_amount_into_the_dealer_ledger(api):
    """PRD §3.8: "The assessment then updates the dealer's ledger:
    `chargeback_assessed_total_cents` and `chargeback_outstanding_cents` each increase by
    the assessed amount, and the dealer's `status` is recomputed."

    Design: Difficulty/combinatorial_formula/supplier_chargeback_goodwill_tier_pinned_order
    """
    env = _assessed_tilapia_lot(api)

    supplier = fixtures.read_supplier(api, env["supplier"]["id"])
    assert_supplier(supplier)
    assert_cents(supplier["chargeback_assessed_total_cents"], 47840)
    assert_cents(supplier["chargeback_outstanding_cents"], 47840)
    assert supplier["status"] == "GOOD_STANDING"
    assert_supplier_chargeback_identity(supplier)


def test_03_a_subtotal_of_exactly_fifty_thousand_cents_earns_the_eight_percent_rate(api):
    """PRD §3.8: "The boundary at exactly 50,000 cents belongs to the 8 percent band."

    Design: Difficulty/boundary_precision_check/goodwill_tier_boundary_at_exactly_fifty_thousand
    """
    env = _mismatched_tilapia_lot(
        api,
        lot_code="TIL-0801-C",
        unit_cost_cents_per_kg=1500,
        retail_price_cents_per_kg=2100,
        cooked_retail_price_cents_per_kg=2400,
        lab_reference="LAB-C-0001",
    )

    lot = env["lot"]
    assert_cents(lot["chargeback_assessed_cents"], 46000)
    assert lot["chargeback_assessed_cents"] != 42500, (
        "42500 would be the 15 percent band, which the boundary subtotal does not earn"
    )
    supplier = fixtures.read_supplier(api, env["supplier"]["id"])
    assert_cents(supplier["chargeback_outstanding_cents"], 46000)


def test_04_the_cascade_shrink_event_prices_disposal_at_the_mislabel_factor(api):
    """PRD §3.9: "The third is disposal: the `shrink_weight_kg` multiplied by a base
    disposal rate of 40 cents per kilogram, then multiplied by a disposal factor determined
    by the `reason` — 1.0 for `UNSOLD_FRESH`, 1.5 for `MISLABEL_DESTRUCTION` and 2.0 for
    `COLD_CHAIN_DISPOSAL` — with the whole product rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/goodwill_tier_boundary_at_exactly_fifty_thousand
    """
    env = _mismatched_tilapia_lot(
        api,
        lot_code="TIL-0801-C",
        unit_cost_cents_per_kg=1500,
        retail_price_cents_per_kg=2100,
        cooked_retail_price_cents_per_kg=2400,
        lab_reference="LAB-C-0001",
    )

    event = fixtures.only_shrink_event(api, env["counter"]["id"], env["lot"]["id"])
    assert event["reason"] == "MISLABEL_DESTRUCTION"
    assert_cents(event["provisional_value_cents"], 16450)


def test_05_compliance_reversal_moves_the_lot_into_the_terminal_reversed_state(api):
    """PRD §3.8: "A `ComplianceOfficer` reverses by submitting a `reversal_note`, which
    moves `chargeback_status` to `REVERSED`, decreases the dealer's
    `chargeback_outstanding_cents` by the lot's `chargeback_assessed_cents`, increases the
    dealer's `chargeback_reversed_cents` by the same amount, and recomputes the dealer's
    `status`."

    Design: Difficulty/compensating_invariant/supplier_chargeback_ledger_identity_after_reversal
    """
    env = _assessed_tilapia_lot(api)
    counter_id = env["counter"]["id"]

    response = api.reverse_chargeback(
        env["lot"]["id"],
        {"reversal_note": "dealer produced a countervailing genetic report"},
        make_compliance_officer_headers(OFFICER_LEDGER_USER_ID),
    )
    validate_success(response, expected_status=200)

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["chargeback_status"] == "REVERSED"
    assert_cents(lot["chargeback_assessed_cents"], 47840)


def test_06_reversal_preserves_the_lifetime_assessed_total_without_drift(api):
    """PRD §2.11: "A reversal never reduces `chargeback_assessed_total_cents`, so the
    identity that the assessed total equals outstanding plus settled plus reversed holds
    permanently."

    Design: Difficulty/compensating_invariant/supplier_chargeback_ledger_identity_after_reversal
    """
    env = _assessed_tilapia_lot(api)
    fixtures.reverse_chargeback(
        api,
        env["lot"]["id"],
        "dealer produced a countervailing genetic report",
        officer_id=OFFICER_LEDGER_USER_ID,
    )

    supplier = fixtures.read_supplier(api, env["supplier"]["id"])
    assert_cents(supplier["chargeback_assessed_total_cents"], 47840)
    assert_cents(supplier["chargeback_outstanding_cents"], 0)
    assert_cents(supplier["chargeback_settled_cents"], 0)
    assert_cents(supplier["chargeback_reversed_cents"], 47840)
    assert_supplier_chargeback_identity(supplier)
    assert supplier["status"] == "GOOD_STANDING"


def test_07_settling_a_lot_with_no_chargeback_fails_on_state_not_on_amount(api):
    """PRD §3.8: "`SETTLED` and `REVERSED` are both terminal; addressing either action to a
    lot in any other chargeback state fails with `ERR_CHARGEBACK_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/settle_chargeback_state_beats_fiscal_amount_mismatch
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    lot = fixtures.cased_lot(api, counter_id, supplier_id, env["cod"]["id"], 1)
    assert lot["chargeback_status"] == "NONE"

    response = api.settle_chargeback(
        lot["id"], {"payment_amount_cents": 500}, make_supplier_rep_headers(supplier_id)
    )
    error = validate_error(
        response, ApiErrorId.ERR_CHARGEBACK_STATE_INVALID.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_SETTLEMENT_AMOUNT_MISMATCH.value


def test_08_a_rejected_settlement_leaves_the_dealer_ledger_untouched(api):
    """PRD §3.8: "A `SupplierRep` settles by submitting a `payment_amount_cents` that must
    equal the dealer's `chargeback_outstanding_cents` exactly — partial payment is rejected
    with `ERR_SETTLEMENT_AMOUNT_MISMATCH` — which moves `chargeback_status` to `SETTLED`,
    decreases the dealer's `chargeback_outstanding_cents` by the lot's
    `chargeback_assessed_cents` and increases the dealer's `chargeback_settled_cents` by
    the same amount."

    Design: Difficulty/priority_pair_validation_conflict/settle_chargeback_state_beats_fiscal_amount_mismatch
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    lot = fixtures.cased_lot(api, counter_id, supplier_id, env["cod"]["id"], 1)

    response = api.settle_chargeback(
        lot["id"], {"payment_amount_cents": 500}, make_supplier_rep_headers(supplier_id)
    )
    validate_error(response, ApiErrorId.ERR_CHARGEBACK_STATE_INVALID.value, expected_status=409)

    assert fixtures.read_lot(api, counter_id, lot["id"])["chargeback_status"] == "NONE"
    supplier = fixtures.read_supplier(api, supplier_id)
    assert_cents(supplier["chargeback_settled_cents"], 0)
    assert_cents(supplier["chargeback_outstanding_cents"], 0)
