"""Payments, refunds, restock fee, and the conserved-quantity invariants
(PRD 2.9, 3.7)."""
from test_helpers import validate_success
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.assertions import assert_glass_units_conserved

ADVISOR = fx.ADVISOR
MANAGER = fx.MANAGER


# ---------------------------------------------------------------------------
# Difficulty rule 1 — refund_full_vs_restock_diverge_on_payment
# Same 56854-cent payment refunds to 48326 once a REPLACE work order is
# IN_SERVICE+ (15% restock) but to its full amount when pre-service / REPAIR.
# ---------------------------------------------------------------------------
def test_refund_replace_in_service_applies_restock_fee(api):
    """PRD 3.7: "A restocking fee applies only when the work order has reached
    IN_SERVICE or beyond ... and the service_decision is REPLACE ... the restocking
    fee is 15 percent of the payment's amount_cents, rounded half-up to the nearest
    cent, and the refunded_amount_cents is the payment's amount_cents minus that fee."

    Design: Difficulty/dual_variant_calc/refund_full_vs_restock_diverge_on_payment
    """
    # REPLACE+ADAS work order driven to IN_SERVICE, paid 56854 in full.
    ctx = fx.setup_in_service(decision="REPLACE", adas_equipped=True, state="CA")
    wo = ctx["work_order"]
    pay = fx.pay_in_full(wo["id"], 56854, "CARD")
    refunded = validate_success(api.refund_payment(pay["id"], MANAGER), 200)
    # restock = round_half_up(56854*0.15 = 8528.1 -> 8528); refunded = 56854-8528 = 48326.
    assert refunded["refunded_amount_cents"] == 48326, (
        f"REPLACE in-service refund must be 48326, got {refunded['refunded_amount_cents']}")
    assert refunded["status"] == "REFUNDED", f"payment must be REFUNDED, got {refunded['status']}"


def test_refund_repair_pre_service_full_amount(api):
    """PRD 3.7: "In every other case — the work order is still OPEN, ASSESSED, or
    SCHEDULED, or the service_decision is REPAIR — no restocking fee applies and the
    refunded_amount_cents is the full amount_cents."

    Design: Difficulty/dual_variant_calc/refund_full_vs_restock_diverge_on_payment
    """
    # REPAIR work order in ASSESSED, paid 9657 in full.
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPAIR")
    pay = fx.pay_in_full(wo["id"], 9657, "CARD")
    refunded = validate_success(api.refund_payment(pay["id"], MANAGER), 200)
    assert refunded["refunded_amount_cents"] == 9657, (
        f"REPAIR refund must be full 9657, got {refunded['refunded_amount_cents']}")


def test_refund_resets_amount_paid_to_zero(api):
    """PRD 3.7: "the work order's amount_paid_cents equals the sum of amount_cents
    over all CAPTURED payments for the work order minus the sum of all
    refunded_amount_cents, and it recomputes amount_paid_cents on every payment and
    refund."

    Design: Difficulty/dual_variant_calc/refund_full_vs_restock_diverge_on_payment
    """
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPAIR")
    pay = fx.pay_in_full(wo["id"], 9657, "CARD")
    validate_success(api.refund_payment(pay["id"], MANAGER), 200)
    wo_after = validate_success(api.get_work_order(wo["id"], ADVISOR), 200)
    assert wo_after["amount_paid_cents"] == 0, (
        f"after refund amount_paid_cents must be 0, got {wo_after['amount_paid_cents']}")


# ---------------------------------------------------------------------------
# Difficulty rule 9 — refund_money_conservation_amount_paid_invariant
# ---------------------------------------------------------------------------
def test_refund_money_conservation_invariant(api):
    """PRD 3.7: "the work order's amount_paid_cents equals the sum of amount_cents
    over all CAPTURED payments for the work order minus the sum of all
    refunded_amount_cents".

    Design: Difficulty/compensating_invariant/refund_money_conservation_amount_paid_invariant
    """
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPAIR")
    pay = fx.pay_in_full(wo["id"], 9657, "CARD")
    wo_paid = validate_success(api.get_work_order(wo["id"], ADVISOR), 200)
    assert wo_paid["amount_paid_cents"] == 9657, (
        f"amount_paid_cents must be 9657 after capture, got {wo_paid['amount_paid_cents']}")
    refunded = validate_success(api.refund_payment(pay["id"], MANAGER), 200)
    assert refunded["refunded_amount_cents"] == 9657, (
        f"REPAIR refund must be full 9657, got {refunded['refunded_amount_cents']}")
    assert refunded["status"] == "REFUNDED"
    wo_after = validate_success(api.get_work_order(wo["id"], ADVISOR), 200)
    # 9657 captured - 9657 refunded = 0; invariant holds.
    assert wo_after["amount_paid_cents"] == 0, (
        f"amount_paid_cents must conserve to 0, got {wo_after['amount_paid_cents']}")


def test_refund_marks_payment_refunded(api):
    """PRD 3.7: "A refund computes a refunded_amount_cents for the payment, moves the
    payment from CAPTURED to REFUNDED".

    Design: Difficulty/compensating_invariant/refund_money_conservation_amount_paid_invariant
    """
    cust, veh, wo, _ = fx.setup_assessed_work_order(decision="REPAIR")
    pay = fx.pay_in_full(wo["id"], 9657, "CARD")
    assert pay["status"] == "CAPTURED", f"captured payment must be CAPTURED, got {pay['status']}"
    refunded = validate_success(api.refund_payment(pay["id"], MANAGER), 200)
    assert refunded["status"] == "REFUNDED", f"refunded payment must be REFUNDED, got {refunded['status']}"


# ---------------------------------------------------------------------------
# Difficulty rule 9 — cancel_releases_reserved_glass_stock_conservation
# ---------------------------------------------------------------------------
def test_cancel_releases_reserved_glass_stock(api):
    """PRD 3.7: "any RESERVED part order for it is moved to CANCELLED with its stock
    released — the part's on_hand_qty is restored by the quantity and its
    reserved_qty is decremented by the quantity."

    Design: Difficulty/compensating_invariant/cancel_releases_reserved_glass_stock_conservation
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FWCONS")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    part = fx.create_glass_part(oem_part_number="FWCONS", adas_compatible=False, on_hand_qty=5)
    po = fx.get_success_data(api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], wo2["version"]), ADVISOR))
    # After reserve: on_hand 4, reserved 1 (total 5).
    part_reserved = validate_success(api.get_glass_part(part["id"], MANAGER), 200)
    assert part_reserved["on_hand_qty"] == 4 and part_reserved["reserved_qty"] == 1
    # Cancel the work order -> RESERVED part order released.
    wo_cancel = validate_success(api.cancel_work_order(wo["id"], ADVISOR), 200)
    assert wo_cancel["status"] == "CANCELLED"
    po_after = validate_success(api.get_part_order(po["id"], ADVISOR), 200)
    assert po_after["status"] == "CANCELLED", f"part order must be CANCELLED, got {po_after['status']}"
    part_after = validate_success(api.get_glass_part(part["id"], MANAGER), 200)
    assert part_after["on_hand_qty"] == 5, f"on_hand_qty must restore to 5, got {part_after['on_hand_qty']}"
    assert part_after["reserved_qty"] == 0, f"reserved_qty must drop to 0, got {part_after['reserved_qty']}"


def test_cancel_conserves_total_glass_units(api):
    """PRD 2.9: "Reserving a part moves units out of on_hand_qty and into
    reserved_qty ... cancelling a reserved order returns units to on_hand_qty and
    draws down reserved_qty".

    Design: Difficulty/compensating_invariant/cancel_releases_reserved_glass_stock_conservation
    """
    cust, veh = fx.setup_customer_and_vehicle(state="CA", adas_equipped=False, oem="FWCONS2")
    wo = fx.create_work_order(cust["id"], veh["id"])
    asmt = fx.get_success_data(api.create_damage_assessment(wo["id"], f.replace_assessment_payload(), ADVISOR))
    wo2 = validate_success(api.accept_assessment(wo["id"], {"assessment_id": asmt["id"]}, ADVISOR), 200)
    part = fx.create_glass_part(oem_part_number="FWCONS2", adas_compatible=False, on_hand_qty=5)
    fx.get_success_data(api.create_part_order(
        f.create_part_order_payload(wo["id"], part["id"], wo2["version"]), ADVISOR))
    part_reserved = validate_success(api.get_glass_part(part["id"], MANAGER), 200)
    assert_glass_units_conserved(part_reserved, 5)
    validate_success(api.cancel_work_order(wo["id"], ADVISOR), 200)
    part_after = validate_success(api.get_glass_part(part["id"], MANAGER), 200)
    assert_glass_units_conserved(part_after, 5)
