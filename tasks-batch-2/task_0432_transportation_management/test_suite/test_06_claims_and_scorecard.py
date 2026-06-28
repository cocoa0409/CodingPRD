"""Claims settlement and the carrier scorecard.

Covers the OSD_OVERAGE-versus-standard settlement divergence, the delivery
cascade that bumps carrier counters and recomputes the scorecard, the
probation grade on a late delivery, the deny compensation, and the
claim-driven scorecard reconciliation.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    assert_claim,
    ApiErrorId,
    create_claim_payload,
    setup_delivered_shipment,
)

CARRIER = TEST_USERS["carrier_ops_headers"]
SHIPPER = TEST_USERS["shipper_ops_headers"]
DOCK = TEST_USERS["dock_ops_headers"]
AUDITOR = TEST_USERS["freight_auditor_headers"]


class TestClaimSettlementOverageVsStandard:
    """Two claims with identical claimed amounts settle differently by type."""

    def test_damage_claim_caps_at_declared_value(self, api):
        """PRD §3.12: "The settlement is liability-capped: the order's
        `declared_value_cents` is the liability ceiling, and the
        `approved_amount_cents` is the smaller of the claimed amount and that
        ceiling"

        Design: Difficulty/dual_variant_calc/claim_settlement_overage_vs_standard_diverge_on_claim
        """
        ctx = setup_delivered_shipment(
            order_weight=10000, declared_value_cents=200000, ship_weight=6000)
        claim = validate_success(api.create_claim(create_claim_payload(
            shipment_id=ctx["shipment"]["id"], claim_type="DAMAGE",
            claimed_amount_cents=250000), SHIPPER), 201)
        approved = validate_success(api.approve_claim(claim["id"], AUDITOR), 200)
        assert_claim(approved)
        assert approved["status"] == "APPROVED"
        assert approved["approved_amount_cents"] == 200000

    def test_overage_claim_settles_to_zero(self, api):
        """PRD §3.12: "There is one special case: a claim whose type is
        `OSD_OVERAGE` settles to zero regardless of the claimed amount, because an
        overage is not a carrier liability."

        Design: Difficulty/dual_variant_calc/claim_settlement_overage_vs_standard_diverge_on_claim
        """
        ctx = setup_delivered_shipment(
            order_weight=10000, declared_value_cents=200000, ship_weight=6000)
        claim = validate_success(api.create_claim(create_claim_payload(
            shipment_id=ctx["shipment"]["id"], claim_type="OSD_OVERAGE",
            claimed_amount_cents=250000), SHIPPER), 201)
        approved = validate_success(api.approve_claim(claim["id"], AUDITOR), 200)
        assert approved["approved_amount_cents"] == 0


class TestDeliverCascadeToScorecard:
    """Delivery bumps the carrier counters which recompute the derived scorecard."""

    def test_on_time_delivery_grades_carrier_a(self, api):
        """PRD §3.8: "the assigned carrier's `delivered_count` is increased by one,
        and additionally, if the delivered minute is at or before the shipment's
        `promised_eta_minute`, its `on_time_count` is increased by one."
        PRD §3.1: "if the on-time percentage is at least 95 and the claim ratio is
        at most 0.02, the grade is `A`"

        Design: Difficulty/transitive_cascade/shipment_deliver_cascade_depth2_carrier_counters_to_scorecard
        """
        ctx = setup_delivered_shipment(delivered_minute=400, promised_eta_minute=500)
        carrier = validate_success(api.get_carrier(ctx["carrier"]["id"], CARRIER), 200)
        assert carrier["delivered_count"] == 1
        assert carrier["on_time_count"] == 1
        assert carrier["on_time_pct"] == 100.0
        assert carrier["scorecard_grade"] == "A"

    def test_delivery_bubbles_order_to_closed(self, api):
        """PRD §3.8: "Delivery also bubbles up to the order, driving it from
        `PLANNED` to `CLOSED` as described in §2.5."

        Design: Difficulty/transitive_cascade/shipment_deliver_cascade_depth2_carrier_counters_to_scorecard
        """
        ctx = setup_delivered_shipment(delivered_minute=400, promised_eta_minute=500)
        order = validate_success(api.get_order(ctx["order"]["id"], SHIPPER), 200)
        assert order["status"] == "CLOSED"


def test_scorecard_probation_when_late_delivery(api):
    """PRD §3.1: "The `on_time_pct` is the on-time count divided by the delivered
    count, multiplied by 100 and rounded half up to two decimal places"
    PRD §3.1: "otherwise, if the on-time percentage is at least 80, the grade is
    `C`; and failing all of these, the grade is `PROBATION`."

    Design: Corner/calculations/scorecard_probation_when_late_delivery
    """
    ctx = setup_delivered_shipment(delivered_minute=600, promised_eta_minute=500)
    carrier = validate_success(api.get_carrier(ctx["carrier"]["id"], CARRIER), 200)
    assert carrier["delivered_count"] == 1
    assert carrier["on_time_count"] == 0
    assert carrier["on_time_pct"] == 0.0
    assert carrier["scorecard_grade"] == "PROBATION"


def test_claim_deny_sets_approved_amount_zero(api):
    """PRD §3.12: "Denial requires the claim to be `OPEN` (otherwise
    `ERR_CLAIM_NOT_OPEN`), moves the claim `OPEN → DENIED`, and sets
    `approved_amount_cents` to zero."

    Design: Corner/state_machines/claim_approve_compensation_deny_sets_zero
    """
    ctx = setup_delivered_shipment()
    claim = validate_success(api.create_claim(create_claim_payload(
        shipment_id=ctx["shipment"]["id"], claim_type="DAMAGE",
        claimed_amount_cents=50000), SHIPPER), 201)
    denied = validate_success(api.deny_claim(claim["id"], AUDITOR), 200)
    assert denied["status"] == "DENIED"
    assert denied["approved_amount_cents"] == 0


def test_scorecard_derived_field_reconciliation_after_claim(api):
    """PRD §3.12: "Opening a claim immediately increments the `claim_count` on the
    carrier assigned to the shipment, which in turn recomputes that carrier's
    `scorecard_grade` as described in §3.1."
    PRD §3.1: "otherwise, if the on-time percentage is at least 90 and the claim
    ratio is at most 0.05, the grade is `B`; otherwise, if the on-time percentage
    is at least 80, the grade is `C`"

    Design: Corner/cross_cutting_complexity_layers/scorecard_derived_field_reconciliation_after_claim
    """
    ctx = setup_delivered_shipment(delivered_minute=400, promised_eta_minute=500)
    validate_success(api.create_claim(create_claim_payload(
        shipment_id=ctx["shipment"]["id"], claim_type="DAMAGE",
        claimed_amount_cents=50000), SHIPPER), 201)
    carrier = validate_success(api.get_carrier(ctx["carrier"]["id"], CARRIER), 200)
    assert carrier["claim_count"] == 1
    assert carrier["on_time_pct"] == 100.0
    assert carrier["scorecard_grade"] == "C"
