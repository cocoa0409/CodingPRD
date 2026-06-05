"""Domain calculations and serializers.

Computed fields (fees, balances, verification posture, booked counts) are
derived here so reads always reflect current state.
"""
from decimal import Decimal

from money import D, round2, money_out
from store import db, fmt_ts


# ---- Calculation constants (from scaffold / PRD) ----
TIER1_CEILING = Decimal("50000")
TIER2_CEILING = Decimal("500000")
TIER2_WIDTH = Decimal("450000")  # 50k..500k
TIER1_MULT = Decimal("1.00")
TIER2_MULT = Decimal("0.80")
TIER3_MULT = Decimal("0.60")
REQUIRED_BOND_FLOOR = Decimal("15000")


# =====================================================================
# Fee calculations
# =====================================================================
def compute_assessed_valuation(permit, jurisdiction):
    if permit["fee_method"] == "VALUATION":
        v = D(permit.get("declared_valuation", 0))
    else:  # SQUARE_FOOT
        v = D(permit.get("floor_area_sqft", 0)) * D(jurisdiction["square_foot_rate"])
    return round2(v)


def compute_base_permit_fee(assessed_valuation, jurisdiction):
    v = D(assessed_valuation)
    r = D(jurisdiction["valuation_fee_rate_per_1000"])

    tier1 = min(v, TIER1_CEILING)
    tier2 = min(max(v - TIER1_CEILING, Decimal("0")), TIER2_WIDTH)
    tier3 = max(v - TIER2_CEILING, Decimal("0"))

    raw = (
        (tier1 / Decimal("1000")) * r * TIER1_MULT
        + (tier2 / Decimal("1000")) * r * TIER2_MULT
        + (tier3 / Decimal("1000")) * r * TIER3_MULT
    )
    rounded = round2(raw)
    floor = round2(jurisdiction["minimum_permit_fee"])
    return max(rounded, floor)


def compute_total_fee(base_permit_fee, jurisdiction):
    """Returns (plan_review_fee, total_permit_fee) as Decimals.

    Per-component rounding is pinned: round base (already rounded), round the
    surcharge of the rounded base, then sum and round.
    """
    base = round2(base_permit_fee)
    plan_review_fee = round2(base * D(jurisdiction["plan_review_fee_pct"]))
    total = round2(base + plan_review_fee)
    return plan_review_fee, total


def recompute_fees(permit):
    """Recompute assessed_valuation / base / plan-review / total on a permit dict.

    Stores the Decimal-equivalent rounded values back onto the permit (as strings
    via Decimal kept in a private numeric cache). We keep canonical numeric values
    on the permit as Decimals are not JSON-serializable, so store floats rounded
    to 2dp for output but keep Decimal copies for exact arithmetic.
    """
    jur = db.jurisdictions[permit["jurisdiction_id"]]
    assessed = compute_assessed_valuation(permit, jur)
    base = compute_base_permit_fee(assessed, jur)
    plan_review_fee, total = compute_total_fee(base, jur)

    permit["assessed_valuation"] = assessed
    permit["base_permit_fee"] = base
    permit["plan_review_fee"] = plan_review_fee
    permit["total_permit_fee"] = total


def compute_amount_paid(permit_id):
    total = Decimal("0")
    for p in db.fee_payments.values():
        if p["permit_id"] == permit_id and p["payment_status"] == "CLEARED":
            total += D(p["amount"])
    return round2(total)


def compute_balance_due(permit):
    total = D(permit["total_permit_fee"])
    accrued = D(permit.get("accrued_renewal_fees", 0))
    paid = compute_amount_paid(permit["id"])
    return round2(total + accrued - paid)


# =====================================================================
# Contractor verification posture
# =====================================================================
def compute_verification_status(contractor):
    now = db.clock.now()
    from store import parse_ts

    license_current = contractor["license_status"] == "ACTIVE"
    if license_current:
        try:
            expiry = parse_ts(contractor["license_expiry"])
            license_current = now < expiry  # strict <
        except (ValueError, KeyError, TypeError):
            license_current = False

    bond_ok = (
        contractor["bond_status"] == "VERIFIED"
        and D(contractor["bond_amount"]) >= REQUIRED_BOND_FLOOR
    )
    return "VERIFIED" if (license_current and bond_ok) else "FAILED"


# =====================================================================
# Inspection slot booked count
# =====================================================================
def compute_booked_count(slot_id):
    n = 0
    for insp in db.inspections.values():
        if insp["slot_id"] == slot_id and insp["inspection_status"] in (
            "SCHEDULED",
            "PASSED",
            "FAILED",
        ):
            n += 1
    return n


def compute_open_correction_count(permit_id):
    n = 0
    for cn in db.correction_notices.values():
        if cn["permit_id"] == permit_id and cn["item_status"] == "OPEN":
            n += 1
    return n


# =====================================================================
# Serializers
# =====================================================================
def _common(rec, include_version=True):
    out = {
        "id": rec["id"],
        "created_at": fmt_ts(rec["_created_at"]),
    }
    if include_version:
        out["updated_at"] = fmt_ts(rec["_updated_at"])
        out["version"] = rec["version"]
    return out


def ser_jurisdiction(j):
    out = _common(j)
    out.update(
        {
            "name": j["name"],
            "code_edition": j["code_edition"],
            "valuation_fee_rate_per_1000": money_out(j["valuation_fee_rate_per_1000"]),
            "square_foot_rate": money_out(j["square_foot_rate"]),
            "plan_review_fee_pct": _num(j["plan_review_fee_pct"]),
            "minimum_permit_fee": money_out(j["minimum_permit_fee"]),
            "renewal_fee_pct": _num(j["renewal_fee_pct"]),
            "permit_valid_days": j["permit_valid_days"],
        }
    )
    return out


def ser_contractor(c):
    out = _common(c)
    out.update(
        {
            "business_name": c["business_name"],
            "license_number": c["license_number"],
            "license_status": c["license_status"],
            "license_expiry": c["license_expiry"],
            "bond_amount": money_out(c["bond_amount"]),
            "bond_status": c["bond_status"],
            "verification_status": compute_verification_status(c),
        }
    )
    return out


def ser_permit(p):
    out = _common(p)
    amount_paid = compute_amount_paid(p["id"])
    balance_due = compute_balance_due(p)
    out.update(
        {
            "jurisdiction_id": p["jurisdiction_id"],
            "contractor_id": p["contractor_id"],
            "work_class": p["work_class"],
            "fee_method": p["fee_method"],
            "declared_valuation": money_out(p["declared_valuation"]),
            "floor_area_sqft": _num(p["floor_area_sqft"]),
            "assessed_valuation": money_out(p["assessed_valuation"]),
            "base_permit_fee": money_out(p["base_permit_fee"]),
            "plan_review_fee": money_out(p["plan_review_fee"]),
            "total_permit_fee": money_out(p["total_permit_fee"]),
            "amount_paid": money_out(amount_paid),
            "balance_due": money_out(balance_due),
            "accrued_renewal_fees": money_out(p.get("accrued_renewal_fees", 0)),
            "status": p["status"],
            "work_status": p["work_status"],
            "open_correction_count": compute_open_correction_count(p["id"]),
            "review_cycle": p["review_cycle"],
            "issued_at": fmt_ts(p["issued_at"]) if p.get("issued_at") else None,
            "expires_at": fmt_ts(p["expires_at"]) if p.get("expires_at") else None,
            "approving_reviewer_id": p.get("approving_reviewer_id"),
        }
    )
    return out


def ser_plan_review(r):
    out = _common(r)
    out.update(
        {
            "permit_id": r["permit_id"],
            "reviewer_id": r["reviewer_id"],
            "cycle_number": r["cycle_number"],
            "decision": r["decision"],
            "review_status": r["review_status"],
        }
    )
    return out


def ser_correction_notice(cn):
    out = _common(cn)
    out.update(
        {
            "plan_review_id": cn["plan_review_id"],
            "permit_id": cn["permit_id"],
            "code_section": cn["code_section"],
            "description": cn["description"],
            "item_status": cn["item_status"],
        }
    )
    return out


def ser_inspector(i):
    out = _common(i)
    out.update({"full_name": i["full_name"], "badge_number": i["badge_number"]})
    return out


def ser_plan_reviewer(pr):
    out = _common(pr)
    out.update({"full_name": pr["full_name"], "cert_number": pr["cert_number"]})
    return out


def ser_slot(s):
    out = _common(s)
    out.update(
        {
            "inspector_id": s["inspector_id"],
            "window_start": s["window_start"],
            "window_end": s["window_end"],
            "max_inspections": s["max_inspections"],
            "booked_count": compute_booked_count(s["id"]),
        }
    )
    return out


def ser_inspection(insp):
    out = _common(insp)
    out.update(
        {
            "permit_id": insp["permit_id"],
            "slot_id": insp["slot_id"],
            "inspector_id": insp["inspector_id"],
            "inspection_type": insp["inspection_type"],
            "scheduled_start": insp["scheduled_start"],
            "scheduled_end": insp["scheduled_end"],
            "inspection_status": insp["inspection_status"],
        }
    )
    return out


def ser_swo(s):
    out = _common(s)
    out.update(
        {
            "permit_id": s["permit_id"],
            "reason": s["reason"],
            "order_status": s["order_status"],
        }
    )
    return out


def ser_certificate(c):
    out = _common(c)
    out.update(
        {
            "permit_id": c["permit_id"],
            "final_inspection_id": c["final_inspection_id"],
            "co_type": c["co_type"],
            "co_status": c["co_status"],
        }
    )
    return out


def ser_fee_payment(p):
    # FeePayment is append-only: only id + created_at common fields.
    return {
        "id": p["id"],
        "created_at": fmt_ts(p["_created_at"]),
        "permit_id": p["permit_id"],
        "amount": money_out(p["amount"]),
        "payment_status": p["payment_status"],
    }


def ser_permit_event(e):
    # PermitEvent is an immutable audit record: only id + created_at.
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["_created_at"]),
        "permit_id": e["permit_id"],
        "event_type": e["event_type"],
        "detail": e["detail"],
    }


def _num(value):
    """Render a non-money numeric. Keep ints as ints, others as float."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    return value
