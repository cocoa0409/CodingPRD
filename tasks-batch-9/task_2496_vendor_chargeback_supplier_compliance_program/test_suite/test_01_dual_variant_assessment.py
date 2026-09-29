"""Dual-variant assessment.

Two places in the programme price the same underlying facts two different ways:
the chargeback assessment picks between `GRACE_FIRST_OCCURRENCE` and `STANDARD`
on the money side, and the on-time in-full measurement picks between
`ORDER_WEIGHTED` and `UNIT_WEIGHTED` on the performance side.  Each test below
builds its whole world from scratch — the harness restarts the service and wipes
the store before every individual test — starting by pinning the logical clock.
"""
import pytest

from test_helpers import (
    add_evidence,
    add_requirement,
    assess_violation,
    create_guide,
    create_po,
    create_scorecard,
    create_shipment,
    create_vendor,
    file_violation,
    measure_scorecard,
    publish_guide,
    read_chargeback,
    read_scorecard,
    read_vendor,
    receive_shipment,
    set_clock,
)

# Fee-schedule row for a packaging breach. The PRD fixes no particular schedule,
# only the arithmetic that consumes one.
PKG_02_TIER_2 = {
    "requirement_code": "PKG-02",
    "domain": "PACKAGING",
    "severity_tier": "TIER_2",
    "min_evidence_count": 1,
    "fixed_fee_cents": 20000,
    "per_unit_recovery_cents": 25,
    "handling_pct": 3.00,
    "min_fee_cents": 45000,
    "cap_cents": 400000,
}


def _packaging_world():
    """Clock pinned, supplier registered with a clean sheet, one PUBLISHED
    edition carrying the TIER_2 packaging requirement, and two identical
    1000-unit receipts each valued at 500000 cents."""
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
    requirement = add_requirement(guide["id"], PKG_02_TIER_2)
    publish_guide(guide["id"])
    set_clock("2026-08-10T00:00:00Z")
    shipments = []
    for po_number, asn_number in (("PO-1", "ASN-1"), ("PO-2", "ASN-2")):
        po = create_po(
            vendor["id"],
            po_number=po_number,
            ordered_units=1000,
            unit_cost_cents=500,
            ship_window_start="2026-08-06T00:00:00Z",
            ship_window_end="2026-08-09T00:00:00Z",
            must_arrive_by="2026-08-10T00:00:00Z",
        )
        shipment = create_shipment(
            po["id"], vendor["id"], asn_number=asn_number, shipped_units=1000, carton_count=40
        )
        shipment = receive_shipment(shipment["id"], 1000)
        shipments.append(shipment)
    return vendor, requirement, shipments


def _assess_packaging_breach(
    shipment_id, requirement_id, narrative, reference_uri, assessment_note
):
    """File the packaging breach on 400 units, evidence it once and assess it."""
    violation = file_violation(
        shipment_id,
        requirement_id,
        affected_units=400,
        affected_cartons=16,
        narrative=narrative,
    )
    add_evidence(violation["id"], kind="PHOTO", reference_uri=reference_uri)
    return assess_violation(violation["id"], assessment_note=assessment_note)


def _otif_world():
    """Two orders of very different sizes, both received exactly on their
    contractual deadline, and one open measurement period over August."""
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2002", legal_name="Northwind Textiles", payment_terms_days=45
    )
    po_a = create_po(
        vendor["id"],
        po_number="PO-A",
        ordered_units=100,
        unit_cost_cents=500,
        ship_window_start="2026-08-02T00:00:00Z",
        ship_window_end="2026-08-04T00:00:00Z",
        must_arrive_by="2026-08-05T00:00:00Z",
    )
    po_b = create_po(
        vendor["id"],
        po_number="PO-B",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-08-02T00:00:00Z",
        ship_window_end="2026-08-04T00:00:00Z",
        must_arrive_by="2026-08-06T00:00:00Z",
    )
    shipment_a = create_shipment(
        po_a["id"], vendor["id"], asn_number="ASN-A", shipped_units=100, carton_count=4
    )
    shipment_b = create_shipment(
        po_b["id"], vendor["id"], asn_number="ASN-B", shipped_units=1000, carton_count=40
    )
    set_clock("2026-08-05T00:00:00Z")
    receive_shipment(shipment_a["id"], 90)
    set_clock("2026-08-06T00:00:00Z")
    receive_shipment(shipment_b["id"], 995)
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-M08",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-31T23:59:59Z",
    )
    return vendor, scorecard


def test_first_packaging_breach_priced_under_the_grace_variant(api):
    """PRD §3.5: "The variant is `GRACE_FIRST_OCCURRENCE` when the pinned
    requirement's `severity_tier` is `TIER_2` or `TIER_3` **and** the supplier has
    no other chargeback at all whose pinned requirement carries this same
    `requirement_code` with an `assessed_at` falling within the 180 days
    immediately before the current logical clock."
    PRD §3.5: "Under `GRACE_FIRST_OCCURRENCE`, `cost_recovery_cents` is forced to
    zero and the `min_fee_cents` floor is not applied at all, so
    `gross_assessed_cents` is simply whichever is smaller of the flat fee and
    `cap_cents`."

    Design: Difficulty/dual_variant_calc/dual_variant_chargeback_grace_vs_standard_on_chargeback_money
    """
    vendor, requirement, shipments = _packaging_world()

    first = _assess_packaging_breach(
        shipments[0]["id"],
        requirement["id"],
        "Master cartons crushed; inner packs unprotected.",
        "s3://evidence/pkg-02/asn-1-a.jpg",
        "First PKG-02 occurrence for this vendor.",
    )

    chargeback = read_chargeback(first["id"])
    assert chargeback["assessment_variant"] == "GRACE_FIRST_OCCURRENCE", (
        "a first TIER_2 breach inside the lookback must be priced under the grace "
        f"variant, got {chargeback['assessment_variant']}"
    )
    assert chargeback["fixed_fee_cents"] == 20000
    assert chargeback["cost_recovery_cents"] == 0, (
        "the grace variant forces cost recovery to zero, got "
        f"{chargeback['cost_recovery_cents']}"
    )
    assert chargeback["gross_assessed_cents"] == 20000, (
        "the grace variant charges the smaller of the flat fee and the cap and "
        f"skips the min_fee floor, expected 20000, got {chargeback['gross_assessed_cents']}"
    )


def test_repeat_packaging_breach_priced_under_the_standard_variant(api):
    """PRD §3.5: "Otherwise the variant is `STANDARD` — which is always the case
    for a `TIER_1` requirement, and is also the case for a `TIER_2` or `TIER_3`
    requirement once a matching prior chargeback exists inside that 180-day
    lookback."
    PRD §3.5: "For a `TIER_2` requirement, `cost_recovery_cents` is whichever of
    the two amounts is larger, and the smaller one is discarded."
    PRD §3.5: "Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."

    Design: Difficulty/dual_variant_calc/dual_variant_chargeback_grace_vs_standard_on_chargeback_money
    """
    vendor, requirement, shipments = _packaging_world()

    _assess_packaging_breach(
        shipments[0]["id"],
        requirement["id"],
        "Master cartons crushed; inner packs unprotected.",
        "s3://evidence/pkg-02/asn-1-a.jpg",
        "First PKG-02 occurrence for this vendor.",
    )
    second = _assess_packaging_breach(
        shipments[1]["id"],
        requirement["id"],
        "Master cartons crushed again on the follow-up load.",
        "s3://evidence/pkg-02/asn-2-a.jpg",
        "Repeat PKG-02 inside the 180-day grace lookback.",
    )

    chargeback = read_chargeback(second["id"])
    assert chargeback["assessment_variant"] == "STANDARD", (
        "a repeat breach of the same requirement code inside the lookback must be "
        f"priced under the standard variant, got {chargeback['assessment_variant']}"
    )
    assert chargeback["fixed_fee_cents"] == 20000
    assert chargeback["cost_recovery_cents"] == 15000, (
        "the TIER_2 branch keeps the larger of unit recovery (10000) and handling "
        f"recovery (15000), got {chargeback['cost_recovery_cents']}"
    )
    assert chargeback["gross_assessed_cents"] == 45000, (
        "a raw amount of 35000 is lifted to the 45000 min_fee floor and left below "
        f"the 400000 cap, got {chargeback['gross_assessed_cents']}"
    )
    assert chargeback["outstanding_cents"] == 45000


def test_grace_and_standard_variants_diverge_on_identical_breach_data(api):
    """PRD §3.5: "Identical violation data therefore yields a different
    `gross_assessed_cents` under the two variants, and a supplier's second breach
    of the same requirement type inside that 180-day lookback is materially more
    expensive than its first."
    PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's chargebacks
    whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED` only, of
    `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this
    figure entirely."
    PRD §3.9: "Finally `exposure_alert_flag` is true exactly when
    `open_chargeback_cents` has reached 500,000 cents or more."

    Design: Difficulty/dual_variant_calc/dual_variant_chargeback_grace_vs_standard_on_chargeback_money
    """
    vendor, requirement, shipments = _packaging_world()

    first = _assess_packaging_breach(
        shipments[0]["id"],
        requirement["id"],
        "Master cartons crushed; inner packs unprotected.",
        "s3://evidence/pkg-02/asn-1-a.jpg",
        "First PKG-02 occurrence for this vendor.",
    )
    second = _assess_packaging_breach(
        shipments[1]["id"],
        requirement["id"],
        "Master cartons crushed again on the follow-up load.",
        "s3://evidence/pkg-02/asn-2-a.jpg",
        "Repeat PKG-02 inside the 180-day grace lookback.",
    )

    graced = read_chargeback(first["id"])
    standard = read_chargeback(second["id"])
    assert graced["gross_assessed_cents"] == 20000
    assert standard["gross_assessed_cents"] == 45000
    assert standard["gross_assessed_cents"] - graced["gross_assessed_cents"] == 25000, (
        "the same breach data must be 25000 cents more expensive on the repeat, got "
        f"{standard['gross_assessed_cents'] - graced['gross_assessed_cents']}"
    )

    supplier = read_vendor(vendor["id"])
    assert supplier["open_chargeback_cents"] == 65000, (
        "exposure is the sum of both assessments, expected 65000, got "
        f"{supplier['open_chargeback_cents']}"
    )
    assert supplier["exposure_alert_flag"] is False, (
        "65000 cents of exposure is well below the 500000-cent alert threshold"
    )


def test_order_weighted_measurement_rounds_each_order_before_averaging(api):
    """PRD §3.7: "Under `ORDER_WEIGHTED` the rule is round-then-aggregate: each
    order's fill percentage is rounded to two decimals first, those already-rounded
    per-order values are summed, the sum is divided by `measured_po_count`, and the
    average is rounded half up to two decimals again."
    PRD §3.7: "The composite is 0.60 multiplied by `otif_pct` plus 0.40 multiplied
    by `fill_rate_pct`, rounded half up to two decimals"

    Design: Difficulty/dual_variant_calc/dual_variant_otif_order_weighted_vs_unit_weighted_on_vendor_performance
    """
    vendor, scorecard = _otif_world()

    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")

    measured = read_scorecard(scorecard["id"])
    assert measured["measurement_variant"] == "ORDER_WEIGHTED"
    assert measured["measured_po_count"] == 2
    assert measured["on_time_count"] == 2
    assert measured["in_full_count"] == 1
    assert measured["otif_count"] == 1
    assert measured["fill_rate_pct"] == pytest.approx(94.75, abs=0.005), (
        "the average of the rounded per-order fills 90.00 and 99.50 is 94.75, got "
        f"{measured['fill_rate_pct']}"
    )
    assert measured["composite_score"] == pytest.approx(67.90, abs=0.005), (
        f"0.60 * 50.00 + 0.40 * 94.75 is 67.90, got {measured['composite_score']}"
    )


def test_unit_weighted_re_measurement_aggregates_before_rounding(api):
    """PRD §3.7: "Under `UNIT_WEIGHTED` the rule is aggregate-then-round:
    `received_units` is summed across the whole scope, `ordered_units` is summed
    across the whole scope, `fill_rate_pct` is 100 multiplied by the first sum and
    divided by the second, and only that final quotient is rounded half up to two
    decimals."
    PRD §3.7: "It is permitted from `OPEN` and from `MEASURED`, taking the
    scorecard `OPEN → MEASURED` on the first run and `MEASURED → MEASURED` on any
    re-run; a scorecard already `FINALIZED` is refused with
    `ERR_SCORECARD_ALREADY_FINALIZED`."

    Design: Difficulty/dual_variant_calc/dual_variant_otif_order_weighted_vs_unit_weighted_on_vendor_performance
    """
    vendor, scorecard = _otif_world()
    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")

    measure_scorecard(scorecard["id"], "UNIT_WEIGHTED")

    measured = read_scorecard(scorecard["id"])
    assert measured["measurement_variant"] == "UNIT_WEIGHTED"
    assert measured["status"] == "MEASURED"
    assert measured["on_time_pct"] == pytest.approx(100.00, abs=0.005)
    assert measured["otif_pct"] == pytest.approx(50.00, abs=0.005)
    assert measured["fill_rate_pct"] == pytest.approx(98.64, abs=0.005), (
        "1085 received over 1100 ordered rounds once to 98.64, got "
        f"{measured['fill_rate_pct']}"
    )
    assert measured["composite_score"] == pytest.approx(69.46, abs=0.005), (
        f"0.60 * 50.00 + 0.40 * 98.64 is 69.46, got {measured['composite_score']}"
    )
    assert measured["cap_required"] is False, (
        "a supplier with no chargebacks at all cannot be placed under a plan"
    )


def test_variant_change_moves_fill_rate_while_the_counts_stay_invariant(api):
    """PRD §3.7: "Across a change of variant, `measured_po_count`,
    `on_time_count`, `in_full_count` and `otif_count` are invariant — they depend
    only on the scope and the tolerance windows — while `fill_rate_pct` and
    `composite_score` change."
    PRD §3.7: "For identical underlying data the two variants therefore produce
    different `fill_rate_pct` values and, through it, different `composite_score`
    values."

    Design: Difficulty/dual_variant_calc/dual_variant_otif_order_weighted_vs_unit_weighted_on_vendor_performance
    """
    vendor, scorecard = _otif_world()

    measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")
    order_weighted = read_scorecard(scorecard["id"])
    measure_scorecard(scorecard["id"], "UNIT_WEIGHTED")
    unit_weighted = read_scorecard(scorecard["id"])

    for field, expected in (
        ("measured_po_count", 2),
        ("on_time_count", 2),
        ("in_full_count", 1),
        ("otif_count", 1),
    ):
        assert order_weighted[field] == expected
        assert unit_weighted[field] == expected, (
            f"{field} must not change with the weighting variant, got "
            f"{unit_weighted[field]} after the re-run"
        )

    assert order_weighted["fill_rate_pct"] == pytest.approx(94.75, abs=0.005)
    assert order_weighted["composite_score"] == pytest.approx(67.90, abs=0.005)
    assert unit_weighted["fill_rate_pct"] == pytest.approx(98.64, abs=0.005)
    assert unit_weighted["composite_score"] == pytest.approx(69.46, abs=0.005)
    assert unit_weighted["fill_rate_pct"] - order_weighted["fill_rate_pct"] == pytest.approx(
        3.89, abs=0.005
    ), "the unit-weighted reading must sit 3.89 points above the order-weighted one"
    assert unit_weighted["composite_score"] - order_weighted[
        "composite_score"
    ] == pytest.approx(1.56, abs=0.005), (
        "the composite must move 1.56 points with the fill-rate reading"
    )
