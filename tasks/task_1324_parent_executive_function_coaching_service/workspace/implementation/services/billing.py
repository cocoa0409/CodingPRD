"""Family ledger, package pricing/status, plan posture, delinquency cascades."""
from decimal import Decimal

import db
import middleware as mw

DELINQUENCY_THRESHOLD_CENTS = 20000
MATERIALS_FEE_CENTS = 2500
PACKAGE_VALIDITY_DAYS = 180


# ---------------------------------------------------------------------------
# Package pricing (calculation: package_pricing)
# ---------------------------------------------------------------------------

def tier_rate(credits_total):
    if credits_total <= 8:
        return 15000
    if credits_total <= 16:
        return 13500
    return 12000


def compute_package_pricing(family_id, track, credits_total):
    unit_gross = mw.rhu(Decimal(tier_rate(credits_total)) * (Decimal("1.00") if track == "INDIVIDUAL" else Decimal("0.60")))
    subtotal = unit_gross * credits_total
    sibling_count = sum(
        1 for c in db.clients.values()
        if c["family_id"] == family_id and c["status"] in ("INTAKE", "ACTIVE", "PAUSED")
    )
    if sibling_count >= 2:
        subtotal = mw.rhu(Decimal(subtotal) * Decimal("0.90"))
    price_paid = subtotal + MATERIALS_FEE_CENTS
    per_credit_value = mw.rhu(Decimal(price_paid) / Decimal(credits_total))
    return unit_gross, price_paid, per_credit_value


def credit_refund_final(pkg):
    """FINAL variant: gross re-price of consumed+forfeited, fee never refunded."""
    used = pkg["credits_consumed"] + pkg["credits_forfeited"]
    return max(0, pkg["price_paid_cents"] - used * pkg["unit_gross_cents"])


# ---------------------------------------------------------------------------
# Family ledger
# ---------------------------------------------------------------------------

def family_outstanding(fam):
    return fam["total_charged_cents"] - fam["total_refunded_cents"] - fam["total_paid_cents"]


def recompute_family_billing(fam):
    """INV-MONEY re-derivation + billing_status recompute (stored for sweeps)."""
    fam["outstanding_balance_cents"] = family_outstanding(fam)
    fam["billing_status"] = "DELINQUENT" if fam["outstanding_balance_cents"] > DELINQUENCY_THRESHOLD_CENTS else "CURRENT"


def charge_family(fam, amount_cents):
    fam["total_charged_cents"] += amount_cents
    recompute_family_billing(fam)


def refund_family(fam, amount_cents):
    fam["total_refunded_cents"] += amount_cents
    recompute_family_billing(fam)


# ---------------------------------------------------------------------------
# Plan posture
# ---------------------------------------------------------------------------

def compute_plan_posture(plan):
    client = db.clients[plan["client_id"]]
    fam = db.families[client["family_id"]]
    coach = db.coaches[plan["coach_id"]]
    if fam["status"] != "ACTIVE":
        return "SCHEDULING_BLOCKED"
    if client["status"] != "ACTIVE":
        return "SCHEDULING_BLOCKED"
    if coach["status"] == "INACTIVE":
        return "SCHEDULING_BLOCKED"
    has_credit = any(
        p["family_id"] == fam["id"] and p["track"] == "INDIVIDUAL" and p["status"] == "ACTIVE"
        and (p["credits_total"] - p["credits_consumed"] - p["credits_forfeited"] - p["reserved_count"]) >= 1
        for p in db.packages.values()
    )
    return "SCHEDULABLE" if has_credit else "SCHEDULING_BLOCKED"


def recompute_plan_posture(plan):
    new = compute_plan_posture(plan)
    if new != plan["posture"]:
        plan["posture"] = new
        mw.touch(plan)


def recompute_family_plan_postures(family_id):
    for c in db.clients.values():
        if c["family_id"] != family_id:
            continue
        for p in db.plans.values():
            if p["client_id"] == c["id"] and p["status"] == "ACTIVE":
                recompute_plan_posture(p)


# ---------------------------------------------------------------------------
# Package status recompute
# ---------------------------------------------------------------------------

def package_credits_remaining(pkg):
    return pkg["credits_total"] - pkg["credits_consumed"] - pkg["credits_forfeited"]


def recompute_package_status(pkg):
    """ACTIVE<->EXHAUSTED on credit crossings; EXPIRED packages stay expired."""
    if pkg["status"] == "ACTIVE" and package_credits_remaining(pkg) <= 0:
        pkg["status"] = "EXHAUSTED"
        mw.touch(pkg)
        recompute_family_plan_postures(pkg["family_id"])
    elif pkg["status"] == "EXHAUSTED" and package_credits_remaining(pkg) > 0:
        pkg["status"] = "ACTIVE"
        mw.touch(pkg)
        recompute_family_plan_postures(pkg["family_id"])


# ---------------------------------------------------------------------------
# Session cascade helper: cancel SCHEDULED sessions early + release credits
# ---------------------------------------------------------------------------

def cancel_sessions_early(session_rows):
    for sess in session_rows:
        sess["attendance_state"] = "CANCELLED_EARLY"
        sess["billing_state"] = "RETURNED"
        sess["cancellation_fee_cents"] = 0
        sess["resolved_at"] = db.now_iso()
        mw.touch(sess)
        pkg = db.packages.get(sess["package_id"])
        if pkg is not None and pkg["reserved_count"] > 0:
            pkg["reserved_count"] -= 1
            mw.touch(pkg)
            recompute_package_status(pkg)


def scheduled_sessions_of_plan(plan_id):
    return [s for s in db.sessions.values()
            if s["plan_id"] == plan_id and s["attendance_state"] == "SCHEDULED"]


def scheduled_sessions_of_client(client_id):
    plan_ids = [p["id"] for p in db.plans.values() if p["client_id"] == client_id]
    return [s for s in db.sessions.values()
            if s["plan_id"] in plan_ids and s["attendance_state"] == "SCHEDULED"]


# ---------------------------------------------------------------------------
# Delinquency auto-suspend (only after cancellation/no-show fee charges)
# ---------------------------------------------------------------------------

def maybe_auto_suspend(fam):
    if fam["outstanding_balance_cents"] > DELINQUENCY_THRESHOLD_CENTS and fam["status"] == "ACTIVE":
        suspend_family(fam)


def suspend_family(fam):
    fam["status"] = "SUSPENDED"
    mw.touch(fam)
    recompute_family_plan_postures(fam["id"])


# ---------------------------------------------------------------------------
# Consent note-sealing cascade
# ---------------------------------------------------------------------------

def seal_notes_shared_to(contact_id):
    for n in db.notes.values():
        if n["shared_with_contact_id"] == contact_id and n["status"] == "SHARED":
            n["status"] = "SEALED"
            mw.touch(n)


def revoke_consents_for_contact(contact_id):
    for cg in db.consents.values():
        if cg["contact_id"] == contact_id and cg["status"] in ("PENDING_SIGNATURE", "ACTIVE"):
            cg["status"] = "REVOKED"
            mw.touch(cg)
    seal_notes_shared_to(contact_id)
