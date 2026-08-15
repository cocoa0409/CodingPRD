"""Business logic: week windows, compliance posture, coverage, pricing, match,
cascades, clock sweeps, and entity serializers."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import clock_date, store, touch

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

AGREEMENT_ACTIVE_STATES = ("SIGNED", "AMENDMENT_PROPOSED", "FULFILLING")
AGREEMENT_TERMINAL_STATES = ("COMPLETED", "BREACHED", "CANCELLED")
CLAIM_PAST_REVIEW = ("AWARDED", "PARTIALLY_AWARDED", "REJECTED", "RECONCILED", "REVERSED")


# ---------------------------------------------------------------------------
# Program calendar (PRD section 2.8)
# ---------------------------------------------------------------------------

def week_of(d, start_date):
    """Week number of date d within a year whose week 1 begins on start_date."""
    return (d - start_date).days // 7 + 1


def in_window(w, s, e):
    """Inclusive week-window containment with wraparound."""
    if s <= e:
        return s <= w <= e
    return w >= s or w <= e


def window_weeks(s, e):
    if s <= e:
        return set(range(s, e + 1))
    return set(range(s, 53)) | set(range(1, e + 1))


def window_inside(inner_s, inner_e, outer_s, outer_e):
    return window_weeks(inner_s, inner_e).issubset(window_weeks(outer_s, outer_e))


# ---------------------------------------------------------------------------
# Farm compliance posture (calculations.farm_compliance_posture)
# ---------------------------------------------------------------------------

def docs_compliant(farm, ref_date):
    """Document completeness at a reference date (no farm-status condition)."""
    safety = False
    insurance = False
    for d in store["documents"].values():
        if d["farm_id"] != farm["id"] or d["status"] != "ACTIVE":
            continue
        if not (d["effective_on"] <= ref_date <= d["expires_on"]):
            continue
        if d["doc_type"] == "SAFETY_CERT":
            safety = True
        elif d["doc_type"] == "LIABILITY_INSURANCE":
            if (d.get("coverage_cents") or 0) >= farm["required_insurance_cents"]:
                insurance = True
    return safety and insurance


def posture(farm, ref_date):
    if farm["status"] == "APPROVED" and docs_compliant(farm, ref_date):
        return "COMPLIANT"
    return "NON_COMPLIANT"


# ---------------------------------------------------------------------------
# Preference points (calculations.preference_points)
# ---------------------------------------------------------------------------

def preference(distance, radius, model):
    if distance > radius:
        return False, 0
    if model == "TIERED":
        if distance <= 25:
            pts = 100
        elif distance <= 50:
            pts = 75
        elif distance <= 100:
            pts = 50
        else:
            pts = 25
    else:  # LINEAR
        pts = 100 - distance
    return True, pts


# ---------------------------------------------------------------------------
# Forecast coverage (calculations.forecast_coverage)
# ---------------------------------------------------------------------------

def line_coverage(line):
    reserved = 0
    for ag in store["agreements"].values():
        if ag["program_year_id"] != line["program_year_id"]:
            continue
        if ag["status"] not in AGREEMENT_ACTIVE_STATES:
            continue
        off = store["offerings"].get(ag["offering_id"])
        if not off or off["product_id"] != line["product_id"]:
            continue
        if not in_window(line["week_number"], ag["harvest_start_week"], ag["harvest_end_week"]):
            continue
        reserved += ag["committed_quantity"]
    uncovered = max(0, line["planned_quantity"] - reserved)
    return reserved, uncovered


def find_forecast_line(year_id, product_id, week):
    for line in store["forecast_lines"].values():
        if (line["program_year_id"] == year_id and line["product_id"] == product_id
                and line["week_number"] == week):
            return line
    return None


# ---------------------------------------------------------------------------
# Delivered aggregation (calculations.delivered_aggregation)
# ---------------------------------------------------------------------------

def delivered_quantity(agreement_id):
    total = 0
    for d in store["deliveries"].values():
        if d["agreement_id"] == agreement_id and d["status"] == "ACCEPTED":
            total += d.get("accepted_quantity") or 0
    return total


def scheduled_held_quantity(agreement_id):
    total = 0
    for d in store["deliveries"].values():
        if d["agreement_id"] == agreement_id and d["status"] in ("SCHEDULED", "CHECKED_IN"):
            total += d["quantity"]
    return total


# ---------------------------------------------------------------------------
# Invoice pricing (calculations.invoice_pricing)
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def incentive_credit(farm_id, year_id, local_eligible, subtotal):
    if not local_eligible:
        return 0
    ytd = 0
    for inv in store["invoices"].values():
        if inv["farm_id"] != farm_id or inv["status"] not in ("APPROVED", "PAID"):
            continue
        ag = store["agreements"].get(inv["agreement_id"])
        if not ag or ag["program_year_id"] != year_id or not ag["local_eligible"]:
            continue
        ytd += inv["subtotal_cents"]
    if ytd < 1000000:
        rate = Decimal("0.02")
    elif ytd < 5000000:
        rate = Decimal("0.03")
    else:
        rate = Decimal("0.05")
    return int((Decimal(subtotal) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Match credit (calculations.match_credit) and claim totals
# ---------------------------------------------------------------------------

def rhu_half(x):
    return int((Decimal(x) * Decimal("0.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def claim_lines_of(claim_id):
    return [l for l in store["claim_lines"].values() if l["claim_id"] == claim_id]


def line_awarded(line):
    if line["audit_status"] == "ALLOWED":
        return line["claimed_amount_cents"]
    if line["audit_status"] == "DISALLOWED":
        return line["claimed_amount_cents"] - line["disallowed_amount_cents"]
    return 0


def claim_totals(claim):
    lines = claim_lines_of(claim["id"])
    total_claimed = sum(l["claimed_amount_cents"] for l in lines)
    total_awarded = sum(line_awarded(l) for l in lines)
    match_prov = sum(rhu_half(l["claimed_amount_cents"]) for l in lines)
    if claim["status"] in CLAIM_PAST_REVIEW:
        match_final = sum(rhu_half(line_awarded(l)) for l in lines)
    else:
        match_final = None
    return total_claimed, total_awarded, match_prov, match_final


def grant_drawn(year_id):
    total = 0
    for c in store["claims"].values():
        if c["program_year_id"] == year_id and c["status"] == "RECONCILED":
            total += claim_totals(c)[1]
    return total


# ---------------------------------------------------------------------------
# Substitution cap (calculations.substitution_cap)
# ---------------------------------------------------------------------------

def substitution_cap_check(year_id, product_id, extra_quantity):
    """PRD 3.8: the request's product is the forecast line's product (the
    demand being substituted), and the request's program year is the line's
    year; the cap is floor(20% of that product's planned total in that year),
    and the consumed room is the quantity of APPROVED requests anchored to
    lines of that same product and year."""
    product_planned = sum(
        l["planned_quantity"] for l in store["forecast_lines"].values()
        if l["program_year_id"] == year_id and l["product_id"] == product_id
    )
    cap = product_planned // 5  # floor(0.20 * product_planned)
    approved_so_far = 0
    for r in store["substitutions"].values():
        if r["status"] != "APPROVED":
            continue
        line = store["forecast_lines"].get(r["forecast_line_id"])
        if (line and line["program_year_id"] == year_id
                and line["product_id"] == product_id):
            approved_so_far += r["quantity"]
    return approved_so_far + extra_quantity <= cap


# ---------------------------------------------------------------------------
# Cascades and clock sweeps
# ---------------------------------------------------------------------------

def breach_agreement(ag):
    """Agreement -> BREACHED with full release bookkeeping and child resolution."""
    ag["released_quantity"] = ag["committed_quantity"] - delivered_quantity(ag["id"])
    ag["status"] = "BREACHED"
    touch(ag)
    for am in store["amendments"].values():
        if am["agreement_id"] == ag["id"] and am["status"] == "PROPOSED":
            am["status"] = "REJECTED"
            touch(am)
    for dv in store["deliveries"].values():
        if dv["agreement_id"] == ag["id"] and dv["status"] == "SCHEDULED":
            dv["status"] = "CANCELLED"
            touch(dv)
    for inv in store["invoices"].values():
        if inv["agreement_id"] == ag["id"] and inv["status"] == "DRAFT":
            inv["status"] = "VOIDED"
            touch(inv)


def suspend_farm_cascade(farm):
    suspended_offering_ids = set()
    for o in store["offerings"].values():
        if o["farm_id"] == farm["id"] and o["status"] == "VERIFIED":
            o["status"] = "SUSPENDED"
            touch(o)
            suspended_offering_ids.add(o["id"])
    for ag in store["agreements"].values():
        if ag["offering_id"] in suspended_offering_ids and ag["status"] in AGREEMENT_ACTIVE_STATES:
            breach_agreement(ag)


def reinstate_farm_cascade(farm):
    for o in store["offerings"].values():
        if o["farm_id"] == farm["id"] and o["status"] == "SUSPENDED":
            o["status"] = "VERIFIED"
            touch(o)


def run_clock_sweeps():
    today = clock_date()
    # 1. Document expiry sweep
    for d in store["documents"].values():
        if d["status"] == "ACTIVE" and d["expires_on"] < today:
            d["status"] = "EXPIRED"
            touch(d)
    # 2. Delivery no-show sweep
    for dv in store["deliveries"].values():
        if dv["status"] == "SCHEDULED" and dv["delivery_date"] < today:
            dv["status"] = "NO_SHOW"
            touch(dv)
    # 3. Agreement harvest window-close sweep
    for ag in store["agreements"].values():
        if ag["status"] not in AGREEMENT_ACTIVE_STATES:
            continue
        year = store["program_years"].get(ag["program_year_id"])
        if not year:
            continue
        current_week = week_of(today, year["start_date"])
        if current_week > ag["harvest_end_week"]:
            if delivered_quantity(ag["id"]) == ag["committed_quantity"]:
                ag["status"] = "COMPLETED"
                touch(ag)
            else:
                breach_agreement(ag)


# ---------------------------------------------------------------------------
# Serializers (computed fields resolved at read time)
# ---------------------------------------------------------------------------

def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_year(y):
    drawn = grant_drawn(y["id"])
    out = _base(y)
    out.update({
        "school_year_label": y["school_year_label"],
        "start_date": y["start_date"].isoformat(),
        "end_date": y["end_date"].isoformat(),
        "local_radius_miles": y["local_radius_miles"],
        "preference_model": y["preference_model"],
        "grant_award_cents": y["grant_award_cents"],
        "local_spend_target_pct": y["local_spend_target_pct"],
        "grant_drawn_cents": drawn,
        "grant_remaining_cents": y["grant_award_cents"] - drawn,
        "status": y["status"],
    })
    return out


def ser_farm(f):
    out = _base(f)
    out.update({
        "legal_name": f["legal_name"],
        "contact_email": f["contact_email"],
        "distance_miles_to_hub": f["distance_miles_to_hub"],
        "acres": f["acres"],
        "is_small_farm": f["is_small_farm"],
        "required_insurance_cents": f["required_insurance_cents"],
        "compliance_posture": posture(f, clock_date()),
        "status": f["status"],
    })
    return out


def ser_doc(d):
    out = _base(d)
    out.update({
        "farm_id": d["farm_id"],
        "doc_type": d["doc_type"],
        "issuer": d["issuer"],
        "coverage_cents": d.get("coverage_cents"),
        "effective_on": d["effective_on"].isoformat(),
        "expires_on": d["expires_on"].isoformat(),
        "status": d["status"],
    })
    return out


def ser_product(p):
    out = _base(p)
    out.update({
        "name": p["name"],
        "category": p["category"],
        "unit": p["unit"],
        "season_start_week": p["season_start_week"],
        "season_end_week": p["season_end_week"],
        "status": p["status"],
    })
    return out


def ser_offering(o):
    out = _base(o)
    out.update({
        "farm_id": o["farm_id"],
        "program_year_id": o["program_year_id"],
        "product_id": o["product_id"],
        "price_cents_per_unit": o["price_cents_per_unit"],
        "max_weekly_quantity": o["max_weekly_quantity"],
        "harvest_start_week": o["harvest_start_week"],
        "harvest_end_week": o["harvest_end_week"],
        "is_local_eligible": o["is_local_eligible"],
        "preference_points": o["preference_points"],
        "status": o["status"],
    })
    return out


def ser_forecast_line(line):
    reserved, uncovered = line_coverage(line)
    out = _base(line)
    out.update({
        "program_year_id": line["program_year_id"],
        "product_id": line["product_id"],
        "week_number": line["week_number"],
        "planned_quantity": line["planned_quantity"],
        "reserved_quantity": reserved,
        "uncovered_quantity": uncovered,
    })
    return out


def ser_kitchen(k):
    out = _base(k)
    out.update({"name": k["name"]})
    return out


def ser_window(w):
    # Receiving windows carry only id + created_at (immutable; no updated_at/version)
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "kitchen_id": w["kitchen_id"],
        "weekday": w["weekday"],
        "start_minute": w["start_minute"],
        "end_minute": w["end_minute"],
        "capacity_deliveries": w["capacity_deliveries"],
    }


def ser_agreement(ag):
    delivered = delivered_quantity(ag["id"])
    terminal = ag["status"] in AGREEMENT_TERMINAL_STATES
    out = _base(ag)
    out.update({
        "program_year_id": ag["program_year_id"],
        "offering_id": ag["offering_id"],
        "committed_quantity": ag["committed_quantity"],
        "harvest_start_week": ag["harvest_start_week"],
        "harvest_end_week": ag["harvest_end_week"],
        "unit_price_cents": ag["unit_price_cents"],
        "local_eligible": ag["local_eligible"],
        "delivered_quantity": delivered,
        "remaining_quantity": 0 if terminal else ag["committed_quantity"] - delivered,
        "released_quantity": ag["released_quantity"],
        "status": ag["status"],
    })
    return out


def ser_amendment(am):
    out = _base(am)
    out.update({
        "agreement_id": am["agreement_id"],
        "proposed_by_role": am["proposed_by_role"],
        "new_committed_quantity": am.get("new_committed_quantity"),
        "new_unit_price_cents": am.get("new_unit_price_cents"),
        "status": am["status"],
    })
    return out


def ser_delivery(dv):
    out = _base(dv)
    out.update({
        "agreement_id": dv["agreement_id"],
        "kitchen_id": dv["kitchen_id"],
        "window_id": dv["window_id"],
        "delivery_date": dv["delivery_date"].isoformat(),
        "quantity": dv["quantity"],
        "week_number": dv["week_number"],
        "accepted_quantity": dv.get("accepted_quantity"),
        "rejection_reason": dv.get("rejection_reason"),
        "status": dv["status"],
    })
    return out


def ser_invoice(inv):
    out = _base(inv)
    out.update({
        "farm_id": inv["farm_id"],
        "delivery_id": inv["delivery_id"],
        "agreement_id": inv["agreement_id"],
        "invoice_number": inv["invoice_number"],
        "quantity_billed": inv["quantity_billed"],
        "unit_price_cents": inv["unit_price_cents"],
        "subtotal_cents": inv["subtotal_cents"],
        "incentive_credit_cents": inv["incentive_credit_cents"],
        "total_cents": inv["total_cents"],
        "farm_compliant_at_delivery": inv["farm_compliant_at_delivery"],
        "approved_by_user_id": inv.get("approved_by_user_id"),
        "paid_at": inv.get("paid_at"),
        "status": inv["status"],
    })
    return out


def ser_claim(c):
    total_claimed, total_awarded, match_prov, match_final = claim_totals(c)
    out = _base(c)
    out.update({
        "program_year_id": c["program_year_id"],
        "period_month": c["period_month"],
        "submitted_by_user_id": c.get("submitted_by_user_id"),
        "total_claimed_cents": total_claimed,
        "total_awarded_cents": total_awarded,
        "match_provisional_cents": match_prov,
        "match_final_cents": match_final,
        "status": c["status"],
    })
    return out


def ser_claim_line(l):
    out = _base(l)
    out.update({
        "claim_id": l["claim_id"],
        "invoice_id": l["invoice_id"],
        "claimed_amount_cents": l["claimed_amount_cents"],
        "audit_status": l["audit_status"],
        "disallowed_amount_cents": l["disallowed_amount_cents"],
        "disallowance_reason": l.get("disallowance_reason"),
    })
    return out


def ser_substitution(r):
    out = _base(r)
    out.update({
        "forecast_line_id": r["forecast_line_id"],
        "substitute_product_id": r["substitute_product_id"],
        "quantity": r["quantity"],
        "reason": r["reason"],
        "status": r["status"],
    })
    return out
