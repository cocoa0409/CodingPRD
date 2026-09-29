"""Bulk purchase order pricing (PRD 3.3)."""
from services.money import apply_bps

PAYMENT_METHODS = ("CASH", "DEBIT", "CREDIT", "CORPORATE_ACH")
ID_TYPES = ("DRIVERS_LICENSE", "PASSPORT", "STATE_ID", "MILITARY_ID")
BULK_STATES = ("PENDING_IDENTITY", "IDENTITY_VERIFIED", "APPROVED", "DECLINED")
DECISIONS = ("APPROVE", "DECLINE", "REQUEST_INFO")


def fee_rate_bps(face_value_subtotal_cents):
    """Tier selected from the PRE-FEE subtotal alone."""
    subtotal = face_value_subtotal_cents
    if subtotal < 25000:
        return 0
    if subtotal < 100000:
        return 150
    if subtotal < 500000:
        return 225
    return 300


def price(card_quantity, face_value_cents_each):
    subtotal = card_quantity * face_value_cents_each
    bps = fee_rate_bps(subtotal)
    fee = apply_bps(subtotal, bps)
    return subtotal, bps, fee, subtotal + fee
