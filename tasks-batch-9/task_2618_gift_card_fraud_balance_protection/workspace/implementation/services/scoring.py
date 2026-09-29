"""Drain risk scores and digital issuance screening (PRD 3.2, 3.6)."""
from datetime import timedelta
from decimal import Decimal

import clock
import db as dbm
from db import db
from services import cards as card_svc
from services.money import clamp_score, round_half_up

PAYMENT_BANDS = ("LOW", "MEDIUM", "HIGH")
PAYMENT_COMPONENT = {"LOW": 0, "MEDIUM": 25, "HIGH": 60}
INQUIRY_CHANNELS = ("POS", "IVR", "WEB", "MOBILE", "RESELLER_API")


def inquiry_velocity_count(card_id, policy=None):
    """Inquiries on this card inside the trailing window, both ends inclusive."""
    policy = policy or dbm.policy()
    now = clock.now()
    start = now - timedelta(minutes=policy["inquiry_velocity_window_minutes"])
    return len([
        i for i in db.inquiries.values()
        if i["card_id"] == card_id and start <= i["occurred_at"] <= now
    ])


def inquiry_weighted_score(card, velocity_count):
    raw = (Decimal(12) * Decimal(velocity_count)
           + Decimal(30) * card_svc.drawdown(card)
           + Decimal(5) * Decimal(card["distinct_merchant_count"]))
    return clamp_score(raw)


def redemption_weighted_score(card):
    raw = (Decimal(45) * card_svc.drawdown(card)
           + Decimal(14) * Decimal(card["distinct_merchant_count"])
           + Decimal(6) * Decimal(card["recent_redemption_count"]))
    return clamp_score(raw)


def email_component(email_age_days):
    if email_age_days >= 365:
        return 0
    if email_age_days >= 90:
        return 20
    if email_age_days >= 7:
        return 45
    return 70


def amount_component(face_value_cents):
    return min(30, (face_value_cents // 5000) * 5)


def digital_screening(request_rec):
    """Four transforms, then the weighted blend rounded exactly once, then the
    bulk surcharge applied after the rounding."""
    device = max(0, 100 - request_rec["device_reputation_score"])
    email = email_component(request_rec["email_age_days"])
    payment = PAYMENT_COMPONENT[request_rec["payment_risk_band"]]
    amount = amount_component(request_rec["face_value_cents"])
    blended = (Decimal("0.35") * Decimal(device)
               + Decimal("0.25") * Decimal(email)
               + Decimal("0.25") * Decimal(payment)
               + Decimal("0.15") * Decimal(amount))
    base = round_half_up(blended)
    base = max(0, min(100, base))
    surcharge = 0
    bulk_order_id = request_rec.get("bulk_order_id")
    if bulk_order_id:
        order = db.bulk_orders.get(bulk_order_id)
        if order is not None and order["state"] == "PENDING_IDENTITY":
            surcharge = 15
    score = min(100, base + surcharge) if surcharge else base
    components = {
        "device": device,
        "email": email,
        "payment": payment,
        "amount": amount,
        "base": base,
        "bulk_surcharge": surcharge,
    }
    return score, components


def digital_disposition(score, policy):
    """Both boundaries bite on the threshold itself."""
    if score >= policy["digital_decline_score_threshold"]:
        return "DECLINED"
    if score >= policy["digital_hold_score_threshold"]:
        return "HELD_FOR_REVIEW"
    return "APPROVED"
