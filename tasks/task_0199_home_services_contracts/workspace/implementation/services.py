"""Domain services: calculations, derived fields, cascades, clock automation.

Every rule traces to a PRD §3 sentence (cited inline).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import models
from common import parse_iso

TERM_DAYS = 365  # PRD §3.3 term_end = term_start + 365 days
LOW_CHARGE_RATIO = Decimal("0.10")  # PRD §3.8 deep-recovery threshold (10%)


# ---------------------------------------------------------------------------
# Equipment refrigerant mass & warranty refresh
# ---------------------------------------------------------------------------
def recompute_charge(equip):
    """current_charge_grams = nameplate + sum(ADD) - sum(RECOVER),
    logs processed in created_at ASC order (PRD §3.7)."""
    logs = [l for l in db.refrigerant_logs.values()
            if l["equipment_id"] == equip["id"]]
    logs.sort(key=lambda l: (l["created_at"], l["_seq"]))
    charge = equip["nameplate_charge_grams"]
    for l in logs:
        if l["action"] == "ADD":
            charge += l["grams"]
        else:  # RECOVER
            charge -= l["grams"]
    equip["current_charge_grams"] = charge
    return charge


def refresh_warranty(equip):
    """On read: if clock >= warranty_expires_at while IN_WARRANTY, flip to EXPIRED
    (PRD §3.7). Returns True if the status changed."""
    if equip["warranty_status"] != "IN_WARRANTY":
        return False
    exp = equip.get("warranty_expires_at")
    if not exp:
        return False
    if db.get_clock() >= parse_iso(exp):
        equip["warranty_status"] = "EXPIRED"
        return True
    return False


def is_below_low_charge(equip):
    """current_charge_grams < 10% of nameplate (PRD §3.8/§3.9)."""
    nameplate = Decimal(equip["nameplate_charge_grams"])
    return Decimal(equip["current_charge_grams"]) < (LOW_CHARGE_RATIO * nameplate)


def at_or_above_low_charge(equip):
    """current_charge_grams >= 10% of nameplate (PRD §3.9 clear-service guard)."""
    nameplate = Decimal(equip["nameplate_charge_grams"])
    return Decimal(equip["current_charge_grams"]) >= (LOW_CHARGE_RATIO * nameplate)


# ---------------------------------------------------------------------------
# Membership derived visits_consumed (PRD §3.8 — derived on read, never written)
# ---------------------------------------------------------------------------
def compute_visits_consumed(membership):
    """Count of this membership's visits in COMPLETED whose completion clock fell
    within the current term window [term_start, term_end)."""
    ts = membership.get("term_start")
    te = membership.get("term_end")
    if not ts or not te:
        return 0
    ts_dt = parse_iso(ts)
    te_dt = parse_iso(te)
    count = 0
    for v in db.service_visits.values():
        if v["membership_id"] != membership["id"]:
            continue
        if v["status"] != "COMPLETED":
            continue
        comp = v.get("completed_at")
        if comp is None:
            continue
        comp_dt = parse_iso(comp)
        if ts_dt <= comp_dt < te_dt:
            count += 1
    return count


def membership_view(membership):
    """Return a serialized membership with visits_consumed recomputed (PRD §2.5)."""
    membership["visits_consumed"] = compute_visits_consumed(membership)
    return models.serialize(membership)


# ---------------------------------------------------------------------------
# SLA evaluation (PRD §3.6 / SCAFFOLD SlaEvaluation)
# ---------------------------------------------------------------------------
def evaluate_sla(visit, plan):
    """sla_met = (window_start - requested_at) hours <= plan.sla_response_hours,
    inclusive. null for non-PRIORITY."""
    if visit["visit_kind"] != "PRIORITY":
        visit["sla_met"] = None
        return None
    ws = parse_iso(visit["window_start"])
    ra = parse_iso(visit["requested_at"])
    latency_hours = (ws - ra).total_seconds() / 3600.0
    visit["sla_met"] = (latency_hours <= plan["sla_response_hours"])
    return visit["sla_met"]


# ---------------------------------------------------------------------------
# Part charge rounding (PRD §3.7 / SCAFFOLD PartChargeRounding)
# ---------------------------------------------------------------------------
def part_charge(list_price_cents, quantity, parts_discount_pct):
    """gross = list_price_cents * quantity; discounted = gross * (1 - pct);
    charged_cents = round_half_up(discounted), per-line."""
    gross = Decimal(list_price_cents) * Decimal(quantity)
    pct = Decimal(str(parts_discount_pct))
    discounted = gross * (Decimal(1) - pct)
    charged = discounted.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(charged)


# ---------------------------------------------------------------------------
# Visit charge assessment (PRD §3.8 / SCAFFOLD VisitChargeAssessment)
# ---------------------------------------------------------------------------
def assess_visit_charge(visit, membership, plan):
    """Stamp billable_charge_cents on the visit being completed.

    WARRANTY -> 0; PRIORITY -> extra_visit_fee_cents always; SEASONAL -> charge
    extra_visit_fee_cents only when (prior in-term SEASONAL completions + 1) >
    included_visits_per_year.
    """
    kind = visit["visit_kind"]
    if kind == "WARRANTY":
        return 0
    if kind == "PRIORITY":
        return plan["extra_visit_fee_cents"]

    # SEASONAL
    ts = parse_iso(membership["term_start"])
    te = parse_iso(membership["term_end"])
    prior_completed = 0
    for v in db.service_visits.values():
        if v["membership_id"] != membership["id"]:
            continue
        if v["id"] == visit["id"]:
            continue
        if v["status"] != "COMPLETED":
            continue
        if v["visit_kind"] != "SEASONAL":
            continue
        comp = v.get("completed_at")
        if comp is None:
            continue
        comp_dt = parse_iso(comp)
        if ts <= comp_dt < te:
            prior_completed += 1
    if (prior_completed + 1) > plan["included_visits_per_year"]:
        return plan["extra_visit_fee_cents"]
    return 0


# ---------------------------------------------------------------------------
# Term setup helpers (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
def begin_first_term(membership):
    start = db.get_clock()
    membership["term_start"] = db.iso(start)
    membership["term_end"] = db.iso(start + timedelta(days=TERM_DAYS))
    membership["term_index"] = 1


def renew_term(membership):
    """New term_start = previous term_end; new term_end = +365 days;
    term_index += 1 (PRD §3.4)."""
    prev_end = parse_iso(membership["term_end"])
    membership["term_start"] = db.iso(prev_end)
    membership["term_end"] = db.iso(prev_end + timedelta(days=TERM_DAYS))
    membership["term_index"] = membership["term_index"] + 1


# ---------------------------------------------------------------------------
# Renewal offer resolution shared by manual + clock-driven paths (PRD §3.4)
# ---------------------------------------------------------------------------
def accept_offer(offer, membership, auto):
    """Drive RENEWAL_PENDING -> ACTIVE on acceptance/auto-acceptance."""
    offer["status"] = "AUTO_ACCEPTED" if auto else "ACCEPTED"
    models.touch(offer)

    membership["plan_id"] = offer["offered_plan_id"]
    renew_term(membership)
    customer = db.customers[membership["customer_id"]]
    customer["billing_balance_cents"] += offer["offered_annual_fee_cents"]
    models.touch(customer)
    membership["status"] = "ACTIVE"
    models.touch(membership)


def lapse_offer(offer, membership, expired):
    """Drive RENEWAL_PENDING -> LAPSED on decline/expiry."""
    offer["status"] = "EXPIRED" if expired else "DECLINED"
    models.touch(offer)
    membership["status"] = "LAPSED"
    models.touch(membership)


# ---------------------------------------------------------------------------
# Clock advance automation (PRD §3.11)
# ---------------------------------------------------------------------------
def advance_clock(target_dt):
    """Set the clock to target; then resolve every still-PENDING offer whose
    expires_at the clock has crossed (expires_at <= clock)."""
    db.set_clock(target_dt)
    # Resolve PENDING offers in created_at ASC order for determinism.
    pending = [o for o in db.renewal_offers.values() if o["status"] == "PENDING"]
    pending.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for offer in pending:
        if offer["status"] != "PENDING":
            continue
        if target_dt < parse_iso(offer["expires_at"]):
            continue
        membership = db.memberships.get(offer["membership_id"])
        if membership is None or membership["status"] != "RENEWAL_PENDING":
            continue
        if membership["auto_renew"]:
            accept_offer(offer, membership, auto=True)
        else:
            lapse_offer(offer, membership, expired=True)


def set_clock(target_dt):
    db.set_clock(target_dt)
