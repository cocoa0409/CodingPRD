"""Composed formulas: nested bounds on an assessment, rounding order inside the
fill-rate aggregation, and the pinned evaluation order of the dispute reversal
determination.

Every test builds its own world from an empty store, starting by pinning the
programme's logical clock.
"""
import pytest

from test_helpers import (
    add_dispute_evidence,
    add_evidence,
    add_requirement,
    assess_violation,
    create_guide,
    create_po,
    create_scorecard,
    create_shipment,
    create_vendor,
    decide_dispute,
    file_violation,
    finalize_scorecard,
    measure_scorecard,
    open_dispute,
    publish_guide,
    read_chargeback,
    read_dispute,
    read_scorecard,
    read_vendor,
    receive_shipment,
    set_clock,
)

LBL_01_TIER_1 = {
    "requirement_code": "LBL-01",
    "domain": "LABELING",
    "severity_tier": "TIER_1",
    "min_evidence_count": 2,
    "fixed_fee_cents": 25000,
    "per_unit_recovery_cents": 30,
    "handling_pct": 2.00,
    "min_fee_cents": 30000,
    "cap_cents": 40000,
}
SHP_04_TIER_1 = {
    "requirement_code": "SHP-04",
    "domain": "SHIPMENT",
    "severity_tier": "TIER_1",
    "min_evidence_count": 2,
    "fixed_fee_cents": 200000,
    "per_unit_recovery_cents": 500,
    "handling_pct": 5.00,
    "min_fee_cents": 100000,
    "cap_cents": 900000,
}


# ---------------------------------------------------------------------------
# Nested-bound assessment world
# ---------------------------------------------------------------------------
def _capped_labeling_breach():
    """A TIER_1 labeling breach on 500 of 1000 received units, fully evidenced and
    ready to assess against a 500000-cent receipt."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V1001", legal_name="Acme Supply Co", payment_terms_days=60
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    requirement = add_requirement(guide["id"], LBL_01_TIER_1)
    publish_guide(guide["id"])
    set_clock("2026-08-10T00:00:00Z")
    po = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    shipment = receive_shipment(shipment["id"], 1000)
    violation = file_violation(
        shipment["id"],
        requirement["id"],
        affected_units=500,
        affected_cartons=20,
        narrative="GS1-128 carton labels missing on half the load.",
    )
    add_evidence(
        violation["id"], kind="PHOTO", reference_uri="s3://evidence/lbl-01/carton-face.jpg"
    )
    add_evidence(
        violation["id"], kind="SCAN", reference_uri="s3://evidence/lbl-01/scan-fail.txt"
    )
    return vendor, violation


def test_tier_one_assessment_is_clamped_down_to_the_requirement_cap(api):
    """PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."
    PRD §3.5: "Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."

    Design: Difficulty/combinatorial_formula/mode_a_nested_min_max_tier1_cap_clamps_assessment
    """
    vendor, violation = _capped_labeling_breach()

    minted = assess_violation(
        violation["id"], assessment_note="TIER_1 labeling failure; cap applies."
    )

    chargeback = read_chargeback(minted["id"])
    assert chargeback["fixed_fee_cents"] == 25000
    assert chargeback["cost_recovery_cents"] == 25000, (
        "the TIER_1 branch charges unit recovery 15000 plus handling recovery 10000, "
        f"got {chargeback['cost_recovery_cents']}"
    )
    assert chargeback["gross_assessed_cents"] == 40000, (
        "a raw amount of 50000 must be clamped down to the 40000 cap, got "
        f"{chargeback['gross_assessed_cents']}"
    )


def test_tier_one_assessment_is_standard_with_the_min_fee_floor_inert(api):
    """PRD §3.5: "Otherwise the variant is `STANDARD` — which is always the case
    for a `TIER_1` requirement, and is also the case for a `TIER_2` or `TIER_3`
    requirement once a matching prior chargeback exists inside that 180-day
    lookback."
    PRD §3.5: "A handling-recovery amount is formed by multiplying the shipment's
    `invoice_value_cents` by the requirement's `handling_pct`, dividing by 100, and
    rounding the result half up to a whole number of cents before it is used
    anywhere."

    Design: Difficulty/combinatorial_formula/mode_a_nested_min_max_tier1_cap_clamps_assessment
    """
    vendor, violation = _capped_labeling_breach()

    minted = assess_violation(
        violation["id"], assessment_note="TIER_1 labeling failure; cap applies."
    )

    chargeback = read_chargeback(minted["id"])
    assert chargeback["assessment_variant"] == "STANDARD", (
        "a TIER_1 requirement is never graced, even on a first occurrence, got "
        f"{chargeback['assessment_variant']}"
    )
    assert chargeback["fixed_fee_cents"] + chargeback["cost_recovery_cents"] == 50000, (
        "the raw amount is the flat fee 25000 plus cost recovery 25000"
    )
    assert chargeback["gross_assessed_cents"] == 40000, (
        "the 30000 min_fee floor is inert on a raw amount of 50000; only the 40000 "
        f"cap binds, got {chargeback['gross_assessed_cents']}"
    )


def test_capped_assessment_opens_outstanding_and_supplier_exposure_at_the_cap(api):
    """PRD §3.5: "It opens with `reversal_cents` 0, `recovered_cents` 0,
    `outstanding_cents` equal to `gross_assessed_cents`, `deduction_posted` false,
    `dispute_status` `NONE` and `settlement_status` `ASSESSED`."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's chargebacks
    whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED` only, of
    `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this
    figure entirely."

    Design: Difficulty/combinatorial_formula/mode_a_nested_min_max_tier1_cap_clamps_assessment
    """
    vendor, violation = _capped_labeling_breach()

    minted = assess_violation(
        violation["id"], assessment_note="TIER_1 labeling failure; cap applies."
    )

    chargeback = read_chargeback(minted["id"])
    assert chargeback["outstanding_cents"] == 40000, (
        "a fresh chargeback owes exactly its capped assessment, got "
        f"{chargeback['outstanding_cents']}"
    )
    supplier = read_vendor(vendor["id"])
    assert supplier["open_chargeback_cents"] == 40000, (
        f"supplier exposure must follow the capped figure, got {supplier['open_chargeback_cents']}"
    )


# ---------------------------------------------------------------------------
# Rounding-order world
# ---------------------------------------------------------------------------
def _ragged_orders_world():
    """Three small ragged orders, each received on its deadline and each far below
    the fill tolerance, plus one open measurement period."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V3003", legal_name="Ragged Lot Trading", payment_terms_days=30
    )
    plan = (
        ("PO-R1", "ASN-R1", 3, 2),
        ("PO-R2", "ASN-R2", 7, 5),
        ("PO-R3", "ASN-R3", 6, 1),
    )
    shipments = []
    for po_number, asn_number, ordered, _received in plan:
        po = create_po(
            vendor["id"],
            po_number=po_number,
            ordered_units=ordered,
            unit_cost_cents=1000,
            ship_window_start="2026-08-02T00:00:00Z",
            ship_window_end="2026-08-04T00:00:00Z",
            must_arrive_by="2026-08-05T00:00:00Z",
        )
        shipments.append(
            create_shipment(
                po["id"],
                vendor["id"],
                asn_number=asn_number,
                shipped_units=ordered,
                carton_count=1,
            )
        )
    set_clock("2026-08-05T00:00:00Z")
    for shipment, (_po, _asn, _ordered, received) in zip(shipments, plan):
        receive_shipment(shipment["id"], received)
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-M08",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T23:59:59Z",
    )
    return vendor, scorecard


def test_unit_weighted_fill_rate_sums_the_units_then_rounds_once(api):
    """PRD §3.7: "Under `UNIT_WEIGHTED` the rule is aggregate-then-round:
    `received_units` is summed across the whole scope, `ordered_units` is summed
    across the whole scope, `fill_rate_pct` is 100 multiplied by the first sum and
    divided by the second, and only that final quotient is rounded half up to two
    decimals."
    PRD §3.7: "The composite is 0.60 multiplied by `otif_pct` plus 0.40 multiplied
    by `fill_rate_pct`, rounded half up to two decimals"

    Design: Difficulty/combinatorial_formula/mode_b_fill_rate_round_then_average_versus_sum_then_round
    """
    vendor, scorecard = _ragged_orders_world()

    measure_scorecard(scorecard["id"], "UNIT_WEIGHTED")

    measured = read_scorecard(scorecard["id"])
    assert measured["fill_rate_pct"] == pytest.approx(50.00, abs=0.005), (
        "8 received units over 16 ordered units is a single quotient of 50.00, got "
        f"{measured['fill_rate_pct']}"
    )
    assert measured["composite_score"] == pytest.approx(20.00, abs=0.005), (
        f"0.60 * 0.00 + 0.40 * 50.00 is 20.00, got {measured['composite_score']}"
    )


def test_order_weighted_fill_rate_rounds_each_order_before_averaging(api):
    """PRD §3.7: "Under `ORDER_WEIGHTED` the rule is round-then-aggregate: each
    order's fill percentage is rounded to two decimals first, those already-rounded
    per-order values are summed, the sum is divided by `measured_po_count`, and the
    average is rounded half up to two decimals again."
    PRD §3.7: "the order's fill percentage is 100 multiplied by its
    `received_units`, divided by its `ordered_units`, rounded half up to two
    decimals, and the order passes when that value is at or above 100.00 less
    `fill_tolerance_pct` — at exactly the floor the order passes."

    Design: Difficulty/combinatorial_formula/mode_b_fill_rate_round_then_average_versus_sum_then_round
    """
    vendor, scorecard = _ragged_orders_world()
    measure_scorecard(scorecard["id"], "UNIT_WEIGHTED")

    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")

    measured = read_scorecard(scorecard["id"])
    assert measured["measured_po_count"] == 3
    assert measured["on_time_count"] == 3
    assert measured["in_full_count"] == 0
    assert measured["otif_count"] == 0
    assert measured["otif_pct"] == pytest.approx(0.00, abs=0.005)
    assert measured["fill_rate_pct"] == pytest.approx(51.59, abs=0.005), (
        "the rounded per-order fills 66.67, 71.43 and 16.67 average to 51.59, got "
        f"{measured['fill_rate_pct']}"
    )
    assert measured["composite_score"] == pytest.approx(20.64, abs=0.005), (
        f"0.60 * 0.00 + 0.40 * 51.59 is 20.64, got {measured['composite_score']}"
    )


def test_rounding_order_alone_moves_the_ragged_fill_rate_by_one_and_a_half_points(api):
    """PRD §3.7: "The two variants differ in one place only — where the rounding
    sits relative to the aggregation of fill rate — and that single difference is
    enough to move the headline score."
    PRD §3.7: "Across a change of variant, `measured_po_count`, `on_time_count`,
    `in_full_count` and `otif_count` are invariant — they depend only on the scope
    and the tolerance windows — while `fill_rate_pct` and `composite_score` change."

    Design: Difficulty/combinatorial_formula/mode_b_fill_rate_round_then_average_versus_sum_then_round
    """
    vendor, scorecard = _ragged_orders_world()

    measure_scorecard(scorecard["id"], "UNIT_WEIGHTED")
    unit_weighted = read_scorecard(scorecard["id"])
    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")
    order_weighted = read_scorecard(scorecard["id"])

    assert unit_weighted["fill_rate_pct"] == pytest.approx(50.00, abs=0.005)
    assert unit_weighted["composite_score"] == pytest.approx(20.00, abs=0.005)
    assert order_weighted["fill_rate_pct"] == pytest.approx(51.59, abs=0.005)
    assert order_weighted["composite_score"] == pytest.approx(20.64, abs=0.005)
    for field in ("measured_po_count", "on_time_count", "in_full_count", "otif_count"):
        assert unit_weighted[field] == order_weighted[field], (
            f"{field} must not move with the weighting variant"
        )


# ---------------------------------------------------------------------------
# Pinned-order dispute determination world
# ---------------------------------------------------------------------------
def _goodwill_eligible_dispute():
    """A 425000-cent TIER_1 assessment, a perfect finalized September scorecard
    lifting the supplier's `otif_score` to 100.00, and one first-round dispute
    claiming 300000 on carrier causation."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V4004", legal_name="Cascade Freight Goods", payment_terms_days=60
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    requirement = add_requirement(guide["id"], SHP_04_TIER_1)
    publish_guide(guide["id"])

    set_clock("2026-08-10T00:00:00Z")
    po = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    shipment = receive_shipment(shipment["id"], 1000)
    violation = file_violation(
        shipment["id"],
        requirement["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="ASN transmitted after the trailer arrived.",
    )
    add_evidence(
        violation["id"],
        kind="DOCUMENT",
        reference_uri="s3://evidence/shp-04/asn-timestamp.pdf",
    )
    add_evidence(
        violation["id"], kind="MEASUREMENT", reference_uri="s3://evidence/shp-04/gate-log.csv"
    )
    chargeback = assess_violation(
        violation["id"], assessment_note="Late ASN on inbound load."
    )

    po_sep = create_po(
        vendor["id"],
        po_number="PO-SEP",
        ordered_units=100,
        unit_cost_cents=500,
        ship_window_start="2026-09-01T00:00:00Z",
        ship_window_end="2026-09-03T00:00:00Z",
        must_arrive_by="2026-09-05T00:00:00Z",
    )
    shipment_sep = create_shipment(
        po_sep["id"], vendor["id"], asn_number="ASN-SEP", shipped_units=100, carton_count=4
    )
    set_clock("2026-09-05T00:00:00Z")
    receive_shipment(shipment_sep["id"], 100)
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-M09",
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-30T23:59:59Z",
    )
    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")
    finalize_scorecard(scorecard["id"])

    dispute = open_dispute(
        chargeback["id"],
        vendor["id"],
        reason_code="CARRIER_CAUSED",
        claimed_reversal_cents=300000,
        narrative="Carrier held the trailer at the yard; ASN timing was outside our control.",
    )
    add_dispute_evidence(
        dispute["id"],
        vendor["id"],
        kind="DOCUMENT",
        reference_uri="s3://evidence/dispute/carrier-hold-letter.pdf",
    )
    return vendor, chargeback, scorecard, dispute


def test_goodwill_uplift_is_measured_against_the_pre_goodwill_gap(api):
    """PRD §3.6: "**Step five** classifies the pre-goodwill outcome as full when
    the requested amount is at or above the eligible cap and partial otherwise,
    then computes `goodwill_cents`. Goodwill is granted only when all three of the
    following hold: the pre-goodwill outcome is partial, the supplier's
    `otif_score` is at or above 95.00, and the dispute's `round_count` is exactly
    1. When they all hold, `goodwill_cents` is 25 per cent of the gap between the
    eligible cap and the requested amount, rounded half up to whole cents;
    otherwise `goodwill_cents` is 0."
    PRD §3.6: "**Step six** sets `approved_reversal_cents` to the requested amount
    plus `goodwill_cents`, capped at the eligible cap so the uplift can never carry
    the reversal past what is assessed."

    Design: Difficulty/combinatorial_formula/mode_c_dispute_goodwill_uplift_pinned_evaluation_order
    """
    vendor, chargeback, scorecard, dispute = _goodwill_eligible_dispute()

    decide_dispute(
        dispute["id"],
        "APPROVE",
        review_note=(
            "Carrier causation accepted; ceiling applied with goodwill for a 100.00 "
            "OTIF supplier."
        ),
    )

    decided = read_dispute(dispute["id"])
    assert decided["reason_ceiling_pct"] == pytest.approx(60.00, abs=0.005), (
        f"carrier causation resolves to a 60.00 ceiling, got {decided['reason_ceiling_pct']}"
    )
    assert decided["goodwill_cents"] == 42500, (
        "goodwill is 25 per cent of the pre-goodwill gap 425000 - 255000, expected "
        f"42500, got {decided['goodwill_cents']}"
    )
    assert decided["approved_reversal_cents"] == 297500, (
        "the approved reversal is the requested 255000 plus the 42500 uplift, got "
        f"{decided['approved_reversal_cents']}"
    )
    assert decided["status"] == "APPROVED_PARTIAL", (
        "297500 is neither zero nor the whole eligible cap, so the outcome is "
        f"partial, got {decided['status']}"
    )
    assert decided["decided_by_user_id"] == "co-2", (
        "the adjudicating officer's identifier is stamped on the dispute, got "
        f"{decided['decided_by_user_id']}"
    )


def test_finalized_scorecard_publishes_the_otif_score_that_unlocks_goodwill(api):
    """PRD §3.7: "The second, caused by the first, copies `composite_score` into
    the supplier's `otif_score` and writes the supplier's `repeat_offender_flag`
    from the repeat-offender determination."
    PRD §3.6: "A supplier that needed a second round to make its case therefore
    forfeits goodwill, as does a supplier whose on-time in-full performance is
    below the 95.00 threshold."

    Design: Difficulty/combinatorial_formula/mode_c_dispute_goodwill_uplift_pinned_evaluation_order
    """
    vendor, chargeback, scorecard, dispute = _goodwill_eligible_dispute()

    finalized = read_scorecard(scorecard["id"])
    assert finalized["composite_score"] == pytest.approx(100.00, abs=0.005), (
        "a single order received on its deadline and in full scores 100.00, got "
        f"{finalized['composite_score']}"
    )
    supplier = read_vendor(vendor["id"])
    assert supplier["otif_score"] == pytest.approx(100.00, abs=0.005), (
        "finalization publishes the composite onto the supplier, got "
        f"{supplier['otif_score']}"
    )
    assert read_dispute(dispute["id"])["round_count"] == 1, (
        "the dispute is still on its first round, which is what goodwill requires"
    )


def test_partial_approval_cascades_into_the_chargeback_and_supplier_exposure(api):
    """PRD §3.6: "The second link, caused by the first, adds
    `approved_reversal_cents` to the chargeback's `reversal_cents` and moves its
    dispute dimension: `OPEN → REVERSED` when the determination classified a full
    approval, `OPEN → PARTIALLY_REVERSED` when it classified a partial one, and
    `OPEN → UPHELD` on a denial."
    PRD §3.9: "its `outstanding_cents` is the net assessed balance less
    `recovered_cents`, floored at 0 so it never reads negative"
    PRD §3.9: "`refund_due_cents` is the sum, over every one of the supplier's
    chargebacks with no settlement filter at all, of the excess of
    `recovered_cents` over `gross_assessed_cents` less `reversal_cents`, counting
    zero where there is no excess — so a written-off chargeback that still holds
    the supplier's cash contributes its whole recovered amount to the refund owed."

    Design: Difficulty/combinatorial_formula/mode_c_dispute_goodwill_uplift_pinned_evaluation_order
    """
    vendor, chargeback, scorecard, dispute = _goodwill_eligible_dispute()

    decide_dispute(
        dispute["id"],
        "APPROVE",
        review_note=(
            "Carrier causation accepted; ceiling applied with goodwill for a 100.00 "
            "OTIF supplier."
        ),
    )

    settled = read_chargeback(chargeback["id"])
    assert settled["reversal_cents"] == 297500, (
        f"the approved reversal lands on the chargeback, got {settled['reversal_cents']}"
    )
    assert settled["dispute_status"] == "PARTIALLY_REVERSED", (
        f"a partial approval moves the dispute dimension, got {settled['dispute_status']}"
    )
    assert settled["outstanding_cents"] == 127500, (
        "425000 assessed less 297500 reversed and nothing recovered leaves 127500, got "
        f"{settled['outstanding_cents']}"
    )
    assert settled["settlement_status"] == "ASSESSED", (
        "no money has moved, so the settlement dimension stays put, got "
        f"{settled['settlement_status']}"
    )

    supplier = read_vendor(vendor["id"])
    assert supplier["open_chargeback_cents"] == 127500, (
        f"exposure follows the shrunken balance, got {supplier['open_chargeback_cents']}"
    )
    assert supplier["refund_due_cents"] == 0, (
        "nothing was ever recovered, so nothing is refundable, got "
        f"{supplier['refund_due_cents']}"
    )
