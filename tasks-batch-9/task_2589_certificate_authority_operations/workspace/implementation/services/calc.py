"""Deterministic calculations (PRD 2.9 and the calculation rules of PRD 3)."""

import datetime
from decimal import Decimal, ROUND_HALF_UP

from db import db

# --- issuance_charge_settlement -----------------------------------------
TIER_MULTIPLIER = {"DV": Decimal("1.0"), "OV": Decimal("1.5"), "EV": Decimal("2.5")}
EXPEDITE_PCT = Decimal("0.25")

# --- subscriber_risk_score ----------------------------------------------
CATEGORY_WEIGHT = {
    "KEY_COMPROMISE": 40,
    "DOMAIN_MISISSUANCE": 25,
    "ORG_MISISSUANCE": 15,
    "PROCEDURAL": 5,
}

# --- incident_remediation_penalty ---------------------------------------
BASE_PENALTY_CENTS = Decimal(1000)
CATEGORY_PENALTY_WEIGHT = {
    "KEY_COMPROMISE": Decimal("3.0"),
    "DOMAIN_MISISSUANCE": Decimal("2.0"),
    "ORG_MISISSUANCE": Decimal("1.5"),
    "PROCEDURAL": Decimal("0.5"),
}

# --- revocation_deadline -------------------------------------------------
REASON_DEADLINE_HOURS = {
    "KEY_COMPROMISE": 24,
    "PRIVILEGE_WITHDRAWN": 24,
    "AFFILIATION_CHANGED": 120,
    "SUPERSEDED": 120,
    "CESSATION_OF_OPERATION": 120,
    "UNSPECIFIED": 120,
}

# --- mass revocation reason mapping -------------------------------------
CATEGORY_REASON = {
    "KEY_COMPROMISE": "KEY_COMPROMISE",
    "DOMAIN_MISISSUANCE": "PRIVILEGE_WITHDRAWN",
    "ORG_MISISSUANCE": "AFFILIATION_CHANGED",
    "PROCEDURAL": "UNSPECIFIED",
}

MASS_REVOKE_BATCH_SIZE = 50
VETTING_LEVEL_RANK = {"NONE": 0, "OV": 1, "EV": 2}


def round_half_up(value):
    """Round a Decimal to a whole number of cents, half away from zero up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def issuance_charge(profile, domain_count, expedited):
    """Six pinned steps; rounding happens at steps 1, 4 and 5 only."""
    unit_cents = round_half_up(
        Decimal(profile["base_fee_cents"]) * TIER_MULTIPLIER[profile["validation_type"]]
    )
    subtotal = unit_cents * domain_count
    if subtotal <= 49999:
        pct = Decimal("0.00")
    elif subtotal <= 149999:
        pct = Decimal("0.10")
    else:
        pct = Decimal("0.20")
    discount = round_half_up(Decimal(subtotal) * pct)
    discounted = subtotal - discount
    expedite = round_half_up(Decimal(discounted) * EXPEDITE_PCT) if expedited else 0
    return discounted + expedite


def capped_days(requested_validity_days, profile):
    return min(requested_validity_days, profile["max_validity_days"])


def revocation_deadline(requested_at, reason_code, has_incident, profile):
    base = REASON_DEADLINE_HOURS[reason_code]
    incident_cap = 24 if has_incident else base
    profile_cap = 48 if profile and profile["validation_type"] == "EV" else base
    effective = max(4, min(base, incident_cap, profile_cap))
    return requested_at + datetime.timedelta(hours=effective)


def recompute_risk_operational(subscriber_id):
    """min(100, sum of category weights over the subscriber's non-CLOSED
    incidents). Returns the new value, or None when there is no subscriber."""
    if subscriber_id is None:
        return None
    subscriber = db.subscribers.get(subscriber_id)
    if subscriber is None:
        return None
    total = 0
    for incident in db.incidents.values():
        if incident["subscriber_id"] != subscriber_id:
            continue
        if incident["state"] == "CLOSED":
            continue
        total += CATEGORY_WEIGHT[incident["category"]]
    return min(100, total)


def risk_score_audit_final(subscriber_id, period_start, period_end, opinion_at):
    """Weighted, closure-discounted, age-decayed sum rounded once at the end."""
    total = Decimal(0)
    for incident in db.incidents.values():
        if incident["subscriber_id"] != subscriber_id:
            continue
        discovered = incident["discovered_at"]
        if discovered < period_start or discovered > period_end:
            continue
        weight = Decimal(CATEGORY_WEIGHT[incident["category"]])
        closure = Decimal("0.5") if incident["state"] == "CLOSED" else Decimal("1.0")
        age_days = int((opinion_at - discovered).total_seconds() // 86400)
        if age_days < 0:
            age_days = 0
        steps = age_days // 30
        decay = Decimal(1) - (Decimal("0.1") * Decimal(steps))
        if decay < Decimal("0.4"):
            decay = Decimal("0.4")
        total += weight * closure * decay
    value = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value > Decimal("100.00"):
        value = Decimal("100.00")
    return float(value)


def certificate_penalty_cents(cert, category, now):
    """Residual-lifetime penalty for one certificate, rounded per certificate."""
    span = (cert["not_after"] - cert["not_before"]).total_seconds()
    if span <= 0:
        residual = Decimal(0)
    else:
        residual = Decimal(str((cert["not_after"] - now).total_seconds())) / Decimal(str(span))
        if residual < 0:
            residual = Decimal(0)
    return round_half_up(BASE_PENALTY_CENTS * CATEGORY_PENALTY_WEIGHT[category] * residual)


def incidents_of_subscriber_in_period(subscriber_id, period_start, period_end):
    result = []
    for incident in db.incidents.values():
        if incident["subscriber_id"] != subscriber_id:
            continue
        discovered = incident["discovered_at"]
        if period_start <= discovered <= period_end:
            result.append(incident)
    return result
