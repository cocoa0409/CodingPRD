"""Computation rules: chargeback pricing branches, rounding discipline, exposure
reconciliation input sets and the scorecard / corrective-action arithmetic.

Every world here is built from scratch out of PRD-declared endpoints only: the
harness restarts the service and wipes the store before each individual test.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    add_evidence,
    add_requirement,
    assess_violation,
    cash_application_payload,
    create_guide,
    create_po,
    create_scorecard,
    create_shipment,
    create_vendor,
    file_violation,
    measure_scorecard,
    publish_guide,
    read_chargeback,
    read_purchase_order,
    read_scorecard,
    read_shipment,
    read_vendor,
    read_violation,
    receive_shipment,
    set_clock,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]

# Fee-schedule rows used by these worlds. The PRD fixes no particular schedule,
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
DOC_03_TIER_3 = {
    "requirement_code": "DOC-03",
    "domain": "DOCUMENTATION",
    "severity_tier": "TIER_3",
    "min_evidence_count": 0,
    "fixed_fee_cents": 15000,
    "per_unit_recovery_cents": 10,
    "handling_pct": 1.00,
    "min_fee_cents": 15000,
    "cap_cents": 100000,
}
PRC_01_TIER_1_ROUNDING = {
    "requirement_code": "PRC-01",
    "domain": "SHIPMENT",
    "severity_tier": "TIER_1",
    "min_evidence_count": 0,
    "fixed_fee_cents": 1000,
    "per_unit_recovery_cents": 0,
    "handling_pct": 1.00,
    "min_fee_cents": 0,
    "cap_cents": 100000,
}


def _assert_instant(value, expected_prefix, label):
    assert value is not None, f"{label} must be stamped, got null"
    assert str(value).startswith(expected_prefix), (
        f"{label} should sit at {expected_prefix}, got {value}"
    )


def test_tier_two_cost_recovery_takes_the_larger_term_then_the_min_fee_floor(api):
    """PRD §3.5: "For a `TIER_2` requirement, `cost_recovery_cents` is whichever
    of the two amounts is larger, and the smaller one is discarded."
    PRD §3.5: "Under `STANDARD`, `cost_recovery_cents` keeps the value the
    severity-tier branch produced, the raw amount is the flat fee plus that cost
    recovery, the requirement's `min_fee_cents` is applied as a floor to the raw
    amount, and the requirement's `cap_cents` is applied as a ceiling to the
    floored result; `gross_assessed_cents` is that floored-then-capped figure."
    PRD §3.5: "Under `GRACE_FIRST_OCCURRENCE`, `cost_recovery_cents` is forced to
    zero and the `min_fee_cents` floor is not applied at all, so
    `gross_assessed_cents` is simply whichever is smaller of the flat fee and
    `cap_cents`."

    Design: Corner/calculations/corner_tier2_cost_recovery_takes_the_max_branch_and_the_min_fee_floor
    """
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2030", legal_name="Maxbranch Manufacturing", payment_terms_days=30
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
    po = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=2000,
        unit_cost_cents=500,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    shipment_one = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=1000, carton_count=40
    )
    shipment_two = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-2", shipped_units=1000, carton_count=40
    )
    receive_shipment(shipment_one["id"], 1000)
    receive_shipment(shipment_two["id"], 1000)

    # The supplier's first PKG-02 breach consumes the grace occurrence.
    first_violation = file_violation(
        shipment_one["id"],
        requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Crushed master cartons, first occurrence.",
    )
    add_evidence(first_violation["id"], kind="PHOTO", reference_uri="s3://evidence/pkg/1.jpg")
    first_chargeback = assess_violation(
        first_violation["id"], assessment_note="First PKG-02 occurrence."
    )

    second_violation = file_violation(
        shipment_two["id"],
        requirement["id"],
        affected_units=400,
        affected_cartons=16,
        narrative="Crushed master cartons, repeat.",
    )
    add_evidence(second_violation["id"], kind="PHOTO", reference_uri="s3://evidence/pkg/2.jpg")

    response = api.assess_violation(
        second_violation["id"], {"assessment_note": "Repeat PKG-02 occurrence."}, OFFICER
    )
    second_chargeback = validate_success(response, 201)

    assert second_chargeback["assessment_variant"] == "STANDARD"
    assert second_chargeback["fixed_fee_cents"] == 20000
    assert second_chargeback["cost_recovery_cents"] == 15000, (
        "TIER_2 charges the larger of unit recovery 10000 and handling recovery "
        f"15000, got {second_chargeback['cost_recovery_cents']}"
    )
    assert second_chargeback["gross_assessed_cents"] == 45000, (
        "raw 35000 sits under the 45000 floor, so the floor should lift the "
        f"assessment to 45000, got {second_chargeback['gross_assessed_cents']}"
    )
    assert second_chargeback["outstanding_cents"] == 45000
    assert second_chargeback["reversal_cents"] == 0
    assert second_chargeback["recovered_cents"] == 0
    assert second_chargeback["requirement_id"] == requirement["id"]
    assert second_chargeback["evidence_at_assessment_count"] == 1

    graced = read_chargeback(first_chargeback["id"])
    assert graced["assessment_variant"] == "GRACE_FIRST_OCCURRENCE"
    assert graced["gross_assessed_cents"] == 20000, (
        "the graced first occurrence charges the flat fee only, got "
        f"{graced['gross_assessed_cents']}"
    )

    supplier = read_vendor(vendor["id"])
    assert supplier["open_chargeback_cents"] == 65000, (
        f"20000 + 45000 should be owed, got {supplier['open_chargeback_cents']}"
    )


def test_tier_one_requirement_never_takes_the_grace_variant(api):
    """PRD §3.5: "The variant is `GRACE_FIRST_OCCURRENCE` when the pinned
    requirement's `severity_tier` is `TIER_2` or `TIER_3` **and** the supplier has
    no other chargeback at all whose pinned requirement carries this same
    `requirement_code` with an `assessed_at` falling within the 180 days
    immediately before the current logical clock. Otherwise the variant is
    `STANDARD` — which is always the case for a `TIER_1` requirement, and is also
    the case for a `TIER_2` or `TIER_3` requirement once a matching prior
    chargeback exists inside that 180-day lookback."
    PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."
    PRD §3.5: "For a `TIER_3` requirement, `cost_recovery_cents` is zero and only
    the flat fee survives."

    Design: Corner/calculations/corner_variant_selection_tier1_never_takes_the_grace_path
    """
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2031", legal_name="Variantpick Ventures", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    label_requirement = add_requirement(guide["id"], LBL_01_TIER_1)
    document_requirement = add_requirement(guide["id"], DOC_03_TIER_3)
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
    receive_shipment(shipment["id"], 1000)

    label_violation = file_violation(
        shipment["id"],
        label_requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable GS1-128 labels.",
    )
    add_evidence(label_violation["id"], kind="PHOTO", reference_uri="s3://evidence/lbl/a.jpg")
    add_evidence(label_violation["id"], kind="SCAN", reference_uri="s3://evidence/lbl/b.txt")
    document_violation = file_violation(
        shipment["id"],
        document_requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Missing packing list.",
    )

    label_chargeback = validate_success(
        api.assess_violation(
            label_violation["id"], {"assessment_note": "First-ever LBL-01."}, OFFICER
        ),
        201,
    )
    document_chargeback = validate_success(
        api.assess_violation(
            document_violation["id"], {"assessment_note": "First-ever DOC-03."}, OFFICER
        ),
        201,
    )

    assert label_chargeback["assessment_variant"] == "STANDARD", (
        "a TIER_1 requirement is excluded from the grace path even on a "
        "first-ever breach"
    )
    assert label_chargeback["cost_recovery_cents"] == 13000
    assert label_chargeback["gross_assessed_cents"] == 38000

    assert document_chargeback["assessment_variant"] == "GRACE_FIRST_OCCURRENCE"
    assert document_chargeback["cost_recovery_cents"] == 0
    assert document_chargeback["gross_assessed_cents"] == 15000

    assert read_violation(document_violation["id"])["status"] == "CHARGED"

    supplier = read_vendor(vendor["id"])
    assert supplier["open_chargeback_cents"] == 53000, (
        f"38000 + 15000 should be owed, got {supplier['open_chargeback_cents']}"
    )
    assert supplier["open_violation_count"] == 0, (
        "both findings are charged, so the open set is empty, got "
        f"{supplier['open_violation_count']}"
    )


def test_handling_recovery_rounds_half_up_to_a_whole_cent(api):
    """PRD §3.5: "A handling-recovery amount is formed by multiplying the
    shipment's `invoice_value_cents` by the requirement's `handling_pct`, dividing
    by 100, and rounding the result half up to a whole number of cents before it
    is used anywhere."
    PRD §3.3: "On success the shipment advances `IN_TRANSIT → RECEIVED`, stores
    the counted `received_units`, stamps `arrived_at` with the current logical
    clock, and computes `invoice_value_cents` as the counted `received_units`
    multiplied by the owning order's `unit_cost_cents`."
    PRD §3.5: "For a `TIER_1` requirement, `cost_recovery_cents` is the
    unit-recovery amount plus the handling-recovery amount — both components are
    charged."

    Design: Corner/calculations/corner_handling_recovery_rounds_half_up_to_whole_cents
    """
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2032", legal_name="Halfcent Holdings", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-P",
        title="Precision Guide",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    requirement = add_requirement(guide["id"], PRC_01_TIER_1_ROUNDING)
    publish_guide(guide["id"])

    set_clock("2026-08-10T00:00:00Z")
    po = create_po(
        vendor["id"],
        po_number="PO-1",
        ordered_units=100,
        unit_cost_cents=5,
        ship_window_start="2026-08-06T00:00:00Z",
        ship_window_end="2026-08-09T00:00:00Z",
        must_arrive_by="2026-08-10T00:00:00Z",
    )
    shipment = create_shipment(
        po["id"], vendor["id"], asn_number="ASN-1", shipped_units=100, carton_count=2
    )
    receive_shipment(shipment["id"], 70)
    violation = file_violation(
        shipment["id"],
        requirement["id"],
        affected_units=10,
        affected_cartons=1,
        narrative="Rounding probe.",
    )

    chargeback = validate_success(
        api.assess_violation(violation["id"], {"assessment_note": "Rounding probe."}, OFFICER),
        201,
    )

    assert read_shipment(shipment["id"])["invoice_value_cents"] == 350
    assert chargeback["assessment_variant"] == "STANDARD"
    assert chargeback["fixed_fee_cents"] == 1000
    assert chargeback["cost_recovery_cents"] == 4, (
        "350 x 1.00 / 100 = 3.5 rounds half up to 4 whole cents, got "
        f"{chargeback['cost_recovery_cents']}"
    )
    assert chargeback["gross_assessed_cents"] == 1004
    assert chargeback["outstanding_cents"] == 1004
    assert read_vendor(vendor["id"])["open_chargeback_cents"] == 1004


def test_open_exposure_drops_a_fully_recovered_chargeback(api):
    """PRD §3.9: "`open_chargeback_cents` is the sum, over the supplier's
    chargebacks whose `settlement_status` is `ASSESSED` or `PARTIALLY_RECOVERED`
    only, of `gross_assessed_cents` less `reversal_cents` less `recovered_cents`;
    chargebacks that are `RECOVERED` or `WRITTEN_OFF` are excluded from this
    figure entirely."
    PRD §3.9: "`recovered_lifetime_cents` is the sum of `allocated_cents` over
    every allocation on any of the supplier's chargebacks whose
    `effective_status` is `EFFECTIVE`, with no filter on the chargeback's
    settlement state."
    PRD §3.9: "The application creates an allocation with `source_type` `CASH`,
    `deduction_id` null, `effective_status` `EFFECTIVE` and `applied_at` stamped
    from the logical clock at creation, storing the applied amount in the
    allocation's `allocated_cents` field and the supplied reference in
    `remittance_reference`."

    Design: Corner/calculations/corner_open_exposure_excludes_recovered_chargebacks
    """
    set_clock("2026-08-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2033", legal_name="Filterset Foods", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-08-05T00:00:00Z",
    )
    label_requirement = add_requirement(guide["id"], LBL_01_TIER_1)
    document_requirement = add_requirement(guide["id"], DOC_03_TIER_3)
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
    receive_shipment(shipment["id"], 1000)

    label_violation = file_violation(
        shipment["id"],
        label_requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels.",
    )
    add_evidence(label_violation["id"], kind="PHOTO", reference_uri="s3://evidence/lbl/a.jpg")
    add_evidence(label_violation["id"], kind="SCAN", reference_uri="s3://evidence/lbl/b.txt")
    label_chargeback = assess_violation(
        label_violation["id"], assessment_note="Label scan failures."
    )
    document_violation = file_violation(
        shipment["id"],
        document_requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Missing packing list.",
    )
    document_chargeback = assess_violation(
        document_violation["id"], assessment_note="Missing packing list."
    )

    before = read_vendor(vendor["id"])
    assert before["open_chargeback_cents"] == 53000, (
        f"38000 + 15000 should be owed before any recovery, got "
        f"{before['open_chargeback_cents']}"
    )

    observed_version = read_chargeback(label_chargeback["id"])["version"]
    response = api.apply_cash(
        label_chargeback["id"],
        cash_application_payload(38000, observed_version, remittance_reference="WIRE-8891"),
        ACCOUNTANT,
    )
    allocation = validate_success(response, 201)

    assert allocation["source_type"] == "CASH"
    assert allocation["effective_status"] == "EFFECTIVE"
    assert allocation["allocated_cents"] == 38000
    assert allocation["remittance_reference"] == "WIRE-8891"
    assert allocation.get("deduction_id") is None

    settled = read_chargeback(label_chargeback["id"])
    assert settled["settlement_status"] == "RECOVERED"
    assert settled["recovered_cents"] == 38000
    assert settled["outstanding_cents"] == 0
    assert settled["deduction_posted"] is False, (
        "cash bypasses payables, so no deduction has been posted on this row"
    )
    assert read_chargeback(document_chargeback["id"])["settlement_status"] == "ASSESSED"

    supplier = read_vendor(vendor["id"])
    assert supplier["open_chargeback_cents"] == 15000, (
        "the recovered row drops out, leaving only the still-assessed 15000, got "
        f"{supplier['open_chargeback_cents']}"
    )
    assert supplier["recovered_lifetime_cents"] == 38000
    assert supplier["refund_due_cents"] == 0
    assert supplier["exposure_alert_flag"] is False


def test_scorecard_scope_is_decided_by_the_contractual_deadline(api):
    """PRD §3.7: "The input set is the supplier's purchase orders whose
    `must_arrive_by` falls inside the closed interval running from `period_start`
    through `period_end` inclusive and whose `status` is `OPEN`,
    `PARTIALLY_RECEIVED` or `RECEIVED`."
    PRD §3.7: "The count of that set is `measured_po_count`, and a period
    containing no measurable orders is refused with
    `ERR_SCORECARD_NO_MEASURABLE_ORDERS`."
    PRD §3.7: "`on_time_pct` is 100 multiplied by `on_time_count`, divided by
    `measured_po_count`, rounded half up to two decimals, and `otif_pct` is the
    same expression built from `otif_count`."
    PRD §3.7: "Each measurement also stamps `measured_at` from the logical clock,
    records the requested `measurement_variant`, and re-derives `cap_required`
    from the repeat-offender rule of §3.8 without yet creating any plan."

    Design: Corner/calculations/corner_scorecard_scope_excludes_orders_outside_the_period
    """
    set_clock("2026-06-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2034", legal_name="Periodscope Provisions", payment_terms_days=30
    )
    order_at_lower_edge = create_po(
        vendor["id"],
        po_number="PO-EDGE-LOW",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-06-20T00:00:00Z",
        ship_window_end="2026-06-28T00:00:00Z",
        must_arrive_by="2026-07-01T00:00:00Z",
    )
    order_at_upper_edge = create_po(
        vendor["id"],
        po_number="PO-EDGE-HIGH",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-07-20T00:00:00Z",
        ship_window_end="2026-07-28T00:00:00Z",
        must_arrive_by="2026-07-31T00:00:00Z",
    )
    order_outside_period = create_po(
        vendor["id"],
        po_number="PO-OUT",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-07-25T00:00:00Z",
        ship_window_end="2026-07-30T00:00:00Z",
        must_arrive_by="2026-08-01T00:00:00Z",
    )
    shipment_low = create_shipment(
        order_at_lower_edge["id"],
        vendor["id"],
        asn_number="ASN-LOW",
        shipped_units=1000,
        carton_count=40,
    )
    shipment_high = create_shipment(
        order_at_upper_edge["id"],
        vendor["id"],
        asn_number="ASN-HIGH",
        shipped_units=1000,
        carton_count=40,
    )

    set_clock("2026-07-01T00:00:00Z")
    receive_shipment(shipment_low["id"], 1000)
    set_clock("2026-07-30T00:00:00Z")
    receive_shipment(shipment_high["id"], 1000)

    set_clock("2026-09-05T00:00:00Z")
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-07",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-31T00:00:00Z",
    )

    measured = validate_success(
        api.measure_scorecard(
            scorecard["id"], {"measurement_variant": "ORDER_WEIGHTED"}, OFFICER
        ),
        200,
    )

    assert measured["status"] == "MEASURED"
    assert measured["measured_po_count"] == 2, (
        "only the two orders whose must_arrive_by falls inside the closed period "
        f"are in scope, got {measured['measured_po_count']}"
    )
    assert measured["on_time_count"] == 2
    assert measured["in_full_count"] == 2
    assert measured["otif_count"] == 2
    assert measured["on_time_pct"] == pytest.approx(100.00, abs=0.01)
    assert measured["otif_pct"] == pytest.approx(100.00, abs=0.01)
    assert measured["fill_rate_pct"] == pytest.approx(100.00, abs=0.01)
    assert measured["composite_score"] == pytest.approx(100.00, abs=0.01)
    assert measured["cap_required"] is False
    _assert_instant(measured["measured_at"], "2026-09-05T00:00:00", "measured_at")

    excluded = read_purchase_order(order_outside_period["id"])
    assert excluded["status"] == "OPEN"
    assert excluded["received_units"] == 0

    reread = read_scorecard(scorecard["id"])
    assert reread["measured_po_count"] == 2


def test_finalization_derives_escalation_level_and_the_level_dependent_due_date(api):
    """PRD §3.7: "The composite is 0.60 multiplied by `otif_pct` plus 0.40
    multiplied by `fill_rate_pct`, rounded half up to two decimals — on-time-in-full
    performance carries three fifths of the weight and raw fill rate the remaining
    two fifths."
    PRD §3.8: "The supplier is flagged as a repeat offender when the
    charged-violation count has reached 3 or more, **or** when at least one
    `TIER_1` chargeback sits in the window and the period's `composite_score` is
    strictly below 90.00."
    PRD §3.8: "A plan is required — `cap_required` becomes true — only when the
    supplier is flagged as a repeat offender **and** the period's
    `composite_score` is strictly below 92.00, so a repeat offender that
    nonetheless scored 92.00 or better is flagged without being placed under a
    plan."
    PRD §3.8: "The `escalation_level` is one plus the number of prior unremediated
    plans in the window, plus one more when the period's `composite_score` is
    strictly below 80.00, and the whole sum is capped at 3."
    PRD §3.8: "The plan's `repeat_count` records the charged-violation count that
    justified it."
    PRD §3.7: "The first moves the scorecard `MEASURED → FINALIZED` and stamps
    `finalized_at`. The second, caused by the first, copies `composite_score` into
    the supplier's `otif_score` and writes the supplier's `repeat_offender_flag`
    from the repeat-offender determination. The third, caused by the second,
    applies only when `cap_required` is true: a corrective action plan is issued as
    described in §3.8, carrying `trigger_scorecard_id` pointing at this scorecard,
    and the supplier's `open_cap_count` is recomputed. The fourth, caused by the
    third, moves an `ACTIVE` supplier to `PROBATION` because a plan is now open
    against it."
    PRD §3.8: "When finalization issues a plan, that plan opens in `ISSUED` with
    `vendor_id` naming the supplier, `trigger_scorecard_id` naming the scorecard
    that produced it, the computed `escalation_level` and `repeat_count`,
    `submission_round` 0, `buying_decision` `NONE`, `milestone_text` and
    `committed_completion_at` null, `issued_at` stamped from the logical clock, and
    `decided_at`, `escalated_at`, `closed_at`, `review_note`, `escalation_note` and
    `closure_note` all null."
    PRD §3.8: "it points at the supplier's corrective action plan in
    `CLOSED_UNREMEDIATED` ranked first by `closed_at` descending and, where two
    share a closure instant, by `created_at` descending, and it is null when the
    supplier has never failed to remediate."
    PRD §3.8: "The deadline `due_at` is derived from `issued_at` plus a
    level-dependent allowance: 30 days at escalation level 1, 21 days at level 2
    and 14 days at level 3."

    Design: Corner/calculations/corner_escalation_constants_drive_cap_level_and_due_date
    """
    set_clock("2026-06-01T00:00:00Z")
    vendor = create_vendor(
        vendor_code="V2035", legal_name="Constantly Late Ltd", payment_terms_days=30
    )
    guide = create_guide(
        guide_code="RG-2026-A",
        title="Domestic Routing Guide 2026-A",
        scope_code="ALL",
        effective_from="2026-06-05T00:00:00Z",
    )
    requirement = add_requirement(
        guide["id"], dict(LBL_01_TIER_1, min_evidence_count=0)
    )
    publish_guide(guide["id"])

    order_in_full = create_po(
        vendor["id"],
        po_number="PO-FULL",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-07-10T00:00:00Z",
        ship_window_end="2026-07-17T00:00:00Z",
        must_arrive_by="2026-07-20T00:00:00Z",
    )
    order_short = create_po(
        vendor["id"],
        po_number="PO-SHORT",
        ordered_units=1000,
        unit_cost_cents=500,
        ship_window_start="2026-07-10T00:00:00Z",
        ship_window_end="2026-07-17T00:00:00Z",
        must_arrive_by="2026-07-20T00:00:00Z",
    )
    shipment_full = create_shipment(
        order_in_full["id"],
        vendor["id"],
        asn_number="ASN-FULL",
        shipped_units=1000,
        carton_count=40,
    )
    shipment_short = create_shipment(
        order_short["id"],
        vendor["id"],
        asn_number="ASN-SHORT",
        shipped_units=1000,
        carton_count=40,
    )

    set_clock("2026-07-19T00:00:00Z")
    receive_shipment(shipment_full["id"], 1000)
    receive_shipment(shipment_short["id"], 500)

    violation = file_violation(
        shipment_short["id"],
        requirement["id"],
        affected_units=100,
        affected_cartons=4,
        narrative="Unreadable labels on the short shipment.",
    )
    assess_violation(
        violation["id"],
        assessment_note="TIER_1 assessment inside the lookback window.",
    )

    set_clock("2026-09-05T00:00:00Z")
    scorecard = create_scorecard(
        vendor["id"],
        period_code="2026-07",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-31T00:00:00Z",
    )
    measured = measure_scorecard(scorecard["id"], "ORDER_WEIGHTED")
    assert measured["measured_po_count"] == 2
    assert measured["on_time_count"] == 2
    assert measured["in_full_count"] == 1
    assert measured["otif_count"] == 1
    assert measured["otif_pct"] == pytest.approx(50.00, abs=0.01)
    assert measured["fill_rate_pct"] == pytest.approx(75.00, abs=0.01)
    assert measured["composite_score"] == pytest.approx(60.00, abs=0.01)
    assert measured["cap_required"] is True

    set_clock("2026-09-06T00:00:00Z")
    finalized = validate_success(api.finalize_scorecard(scorecard["id"], OFFICER), 200)

    assert finalized["status"] == "FINALIZED"
    assert finalized["composite_score"] == pytest.approx(60.00, abs=0.01)
    _assert_instant(finalized["finalized_at"], "2026-09-06T00:00:00", "finalized_at")

    supplier = read_vendor(vendor["id"])
    assert supplier["otif_score"] == pytest.approx(60.00, abs=0.01)
    assert supplier["repeat_offender_flag"] is True
    assert supplier["status"] == "PROBATION"
    assert supplier["open_cap_count"] == 1

    plans, meta = validate_paginated(
        api.list_caps(OFFICER, params={"vendor_id": vendor["id"]})
    )
    assert meta["total_count"] == 1, (
        f"finalisation should have issued exactly one plan, got {meta['total_count']}"
    )
    plan = plans[0]
    assert plan["status"] == "ISSUED"
    assert plan["escalation_level"] == 2, (
        "a composite of 60.00 is strictly below 80.00, which lifts the level from "
        f"1 to 2, got {plan['escalation_level']}"
    )
    assert plan["repeat_count"] == 1
    assert plan.get("predecessor_cap_id") is None
    assert plan["trigger_scorecard_id"] == scorecard["id"]
    _assert_instant(plan["issued_at"], "2026-09-06T00:00:00", "issued_at")
    _assert_instant(plan["due_at"], "2026-09-27T00:00:00", "due_at")
    assert plan["submission_round"] == 0
