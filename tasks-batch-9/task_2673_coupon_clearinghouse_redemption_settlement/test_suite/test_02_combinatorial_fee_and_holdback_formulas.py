"""Two formulas whose composition order decides the cent.

The handling fee rounds once per lot and only then sums; the statement holdback
subtracts the offset, adds the risk premium and only then caps.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    ANALYST,
    OFFICER,
    IntakeStatus,
    LotStatus,
    StatementStatus,
    SETTLEMENT_OFFICER_ID,
    ValuationVariant,
    assert_fields,
    assert_lot_valuation,
    assert_money,
    assert_rate_equals,
    assert_statement_waterfall,
    databar_payload,
    factories as f,
)

SOUP50_BARCODE = databar_payload("038000", 50, 2, "2026-12-31", 30)


@pytest.fixture
def priced_shipment(build):
    """A 63-coupon shipment whose two lots price at 403 and 105 cents.

    Lot A holds 60 coupons sampled down to six images, five of them backed by a
    two-unit basket and the sixth quoting a register reference no basket carries.
    Lot B holds three coupons claiming five, four and four units against baskets
    of ten, eight and eight qualifying units.
    """
    mfr = build.manufacturer(gs1_company_prefix="038000",
                             legal_name="Kellwood Foods",
                             handling_fee_policy="CONTRACT_RATE",
                             dispute_window_days=45)
    ret = build.retailer(legal_name="Northgate Markets", channel_capability="BOTH",
                         payment_terms="NET_30", base_fee_tier="PREFERRED",
                         fraud_scoring_mode="ROLLING_WINDOW")
    offer = build.active_offer(
        mfr["id"], offer_code="SOUP50", face_value_cents=50,
        handling_fee_cents=7, expiration_date="2026-12-31",
        redemption_instructions="Save 50c on two cans",
        max_redemptions=100000, purchase_requirement_units=2,
        redemption_grace_days=30, digital_enabled=False, clip_validity_days=14)

    for index in range(1, 6):
        build.purchase_record(ret["id"], offer["id"], f"POS-A{index}",
                              "2026-07-05", 2)
    for ref, units in (("POS-C1", 10), ("POS-C2", 8), ("POS-C3", 8)):
        build.purchase_record(ret["id"], offer["id"], ref, "2026-07-06", units)

    submission = build.verified_submission(ret["id"], 63, "2026-07-01",
                                           "2026-07-31")
    lot_a = build.lot(submission["id"], offer["id"], mfr["id"], 60)
    lot_b = build.lot(submission["id"], offer["id"], mfr["id"], 3)
    build.capture(lot_a["id"], [
        f.item_payload(SOUP50_BARCODE, f"s3://img/a{index}.jpg", "2026-07-05",
                       pos_transaction_ref=f"POS-A{index}", claimed_units=1)
        for index in range(1, 7)
    ])
    build.capture(lot_b["id"], [
        f.item_payload(SOUP50_BARCODE, "s3://img/c1.jpg", "2026-07-06",
                       pos_transaction_ref="POS-C1", claimed_units=5),
        f.item_payload(SOUP50_BARCODE, "s3://img/c2.jpg", "2026-07-06",
                       pos_transaction_ref="POS-C2", claimed_units=4),
        f.item_payload(SOUP50_BARCODE, "s3://img/c3.jpg", "2026-07-06",
                       pos_transaction_ref="POS-C3", claimed_units=4),
    ])
    finalized_a = build.finalize(lot_a["id"])
    return {
        "manufacturer": mfr, "retailer": ret, "offer": offer,
        "retailer_id": ret["id"], "submission_id": submission["id"],
        "lot_a": finalized_a, "lot_a_id": lot_a["id"], "lot_b_id": lot_b["id"],
    }


def test_01_each_lot_rounds_its_own_fee_before_the_submission_sums_them(
        api, build, priced_shipment):
    """403 plus 105 is 508, one cent above the single-rounding answer.

    "Lot A's 50 units price at 402.5, which rounds to 403; lot B's 13 units
    price at 104.65, which rounds to 105; and `settled_handling_fee_cents` is
    508."

    Design: Difficulty/combinatorial_formula/per_lot_handling_fee_round_then_sum
    """
    lot_b = build.finalize(priced_shipment["lot_b_id"])

    assert_money(priced_shipment["lot_a"], "handling_fee_cents", 403)
    assert_money(lot_b, "handling_fee_cents", 105)

    submission = validate_success(
        api.get_submission(priced_shipment["submission_id"], ANALYST))
    assert_money(submission, "settled_handling_fee_cents", 508)
    assert submission["settled_handling_fee_cents"] != 507, (
        "508 is the sum of the two already-rounded lot fees; 507 is what "
        "summing 63 units first and rounding once would produce"
    )


def test_02_the_three_coupon_lot_prices_every_unit_it_actually_holds(
        api, build, priced_shipment):
    """Thirteen claimed units at 7 cents on a 1.15 multiplier give 104.65.

    "There is no rate, no extrapolation and no rounding, because both operands
    are integers."

    "Immediately after valuation, the handling fee for the lot is priced from the
    projected units."

    Design: Difficulty/combinatorial_formula/per_lot_handling_fee_round_then_sum
    """
    lot_b = build.finalize(priced_shipment["lot_b_id"])

    assert_fields(lot_b, {"valuation_variant": ValuationVariant.FULL_COUNT})
    assert_lot_valuation(lot_b, status=LotStatus.VALIDATED, accepted_qty=13,
                         rejected_qty=0, projected_accepted_units=13,
                         gross_face_value_cents=650, handling_fee_cents=105)


def test_03_closing_the_shipment_publishes_the_two_summed_totals(
        api, build, priced_shipment):
    """The last lot to sort carries the submission to CLOSED with 3150 and 508.

    "In the same way, `settled_gross_face_value_cents` is the plain integer sum
    of `gross_face_value_cents` over the submission's `VALIDATED` and
    `REINSTATED` lots, and it is the billable gross a statement will copy."

    Design: Difficulty/combinatorial_formula/per_lot_handling_fee_round_then_sum
    """
    submission_id = priced_shipment["submission_id"]

    build.finalize(priced_shipment["lot_b_id"])

    submission = validate_success(api.get_submission(submission_id, ANALYST))
    assert_fields(submission, {"intake_status": IntakeStatus.CLOSED})
    assert_money(submission, "settled_gross_face_value_cents", 3150)
    assert_money(submission, "settled_handling_fee_cents", 508)
    assert submission["settled_gross_face_value_cents"] == 2500 + 650, (
        "the billable gross is the plain sum of the two validated lot grosses"
    )


@pytest.fixture
def closed_shipment(build, priced_shipment):
    """The priced shipment carried to CLOSED, with the retailer's standing re-derived.

    The analyst re-derives the standing before any statement is drawn, so the
    holdback reads a misredemption rate that reflects all nine adjudicated
    coupons.
    """
    build.finalize(priced_shipment["lot_b_id"])
    build.rescore(priced_shipment["retailer_id"])
    return priced_shipment


def test_04_the_holdback_band_takes_the_addon_before_the_cap(
        api, closed_shipment):
    """3658 sits in the zero band, the 0.03 premium lands, the cap never bites.

    "Worked through: a gross of 3150 and a fee of 508 with no offset give a
    `provisional_net_cents` of 3658; 3658 is below 100000 so the base band is
    0.00; the retailer's `misredemption_rate` of 11.11 is at least 5.00 so the
    add-on is 0.03; `holdback_pct` is the lesser of 0.03 and 0.06, namely 0.03;
    the holdback is 109.74 rounded half up to 110; and `net_payable_cents` is
    3548."

    Design: Difficulty/combinatorial_formula/statement_holdback_band_then_riskaddon_then_cap
    """
    submission_id = closed_shipment["submission_id"]
    submission = validate_success(api.get_submission(submission_id, OFFICER))

    statement = validate_success(api.issue_statement(
        submission_id, submission["version"], OFFICER,
        prior_chargeback_offset_cents=0), 201)

    assert_statement_waterfall(statement, gross=3150, fee_total=508, offset=0,
                               provisional_net=3658, holdback_pct="0.03",
                               holdback=110, net_payable=3548)


def test_05_the_holdback_is_a_share_of_the_net_and_not_of_the_gross(
        api, closed_shipment):
    """110 cents, not the 95 that three percent of 3150 would give.

    "And the holdback is a percentage of `provisional_net_cents` — gross plus
    fee minus offset — not of gross alone and not of gross plus fee."

    Design: Difficulty/combinatorial_formula/statement_holdback_band_then_riskaddon_then_cap
    """
    submission_id = closed_shipment["submission_id"]
    submission = validate_success(api.get_submission(submission_id, OFFICER))

    statement = validate_success(api.issue_statement(
        submission_id, submission["version"], OFFICER,
        prior_chargeback_offset_cents=0), 201)

    assert_money(statement, "misredemption_holdback_cents", 110)
    assert statement["misredemption_holdback_cents"] != 95, (
        "95 is three percent of the gross alone; the holdback is taken on the "
        "provisional net of 3658"
    )
    assert statement["net_payable_cents"] != 3563, (
        "3563 is the net that a gross-based holdback would leave"
    )


def test_06_the_rate_that_triggers_the_addon_is_the_one_the_close_left_behind(
        api, closed_shipment):
    """One misredemption in nine adjudicated coupons is 11.11 percent.

    "The risk add-on is 0.03 when the retailer's current `misredemption_rate` is
    at least 5.00 percent and 0.00 otherwise."

    Design: Difficulty/combinatorial_formula/statement_holdback_band_then_riskaddon_then_cap
    """
    retailer = validate_success(
        api.get_retailer(closed_shipment["retailer_id"], OFFICER))
    assert_rate_equals(retailer["misredemption_rate"], "11.11",
                       "misredemption_rate")

    submission = validate_success(
        api.get_submission(closed_shipment["submission_id"], OFFICER))
    statement = validate_success(api.issue_statement(
        closed_shipment["submission_id"], submission["version"], OFFICER,
        prior_chargeback_offset_cents=0), 201)

    assert_fields(statement, {
        "status": StatementStatus.DRAFT,
        "issued_by_user_id": SETTLEMENT_OFFICER_ID,
        "submission_id": closed_shipment["submission_id"],
        "retailer_id": closed_shipment["retailer_id"],
    })
