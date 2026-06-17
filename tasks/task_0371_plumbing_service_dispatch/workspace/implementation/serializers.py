"""Public serialization for each entity type.

Immutable config resources (MembershipPlan, FlatRateItem, Part) carry ONLY
id and created_at — never updated_at or version (PRD §2.4).
"""
import db


def _strip(rec, drop=()):
    out = db.public(rec)
    for k in drop:
        out.pop(k, None)
    return out


def membership_plan(rec):
    # Immutable: id + created_at only.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "tier_code": rec["tier_code"],
        "name": rec["name"],
        "labor_discount_pct": rec["labor_discount_pct"],
        "waives_trip_fee": rec["waives_trip_fee"],
        "annual_fee_cents": rec["annual_fee_cents"],
    }


def flat_rate_item(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "code": rec["code"],
        "category": rec["category"],
        "base_price_cents": rec["base_price_cents"],
        "skill_required": rec["skill_required"],
        "requires_permit": rec["requires_permit"],
    }


def part(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "sku": rec["sku"],
        "name": rec["name"],
        "list_price_cents": rec["list_price_cents"],
    }


def generic(rec):
    """Versioned resources: emit everything public (id, created_at, updated_at,
    version, plus domain fields)."""
    return db.public(rec)
