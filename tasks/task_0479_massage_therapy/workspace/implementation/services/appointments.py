"""Appointment business logic: gates, pricing, fees, commission (PRD §3.3-3.9)."""
from datetime import timedelta
from fractions import Fraction

import clock
import db
import helpers as h
import util
from routes.therapists import license_status, cert_status
from services import packages as pkgsvc


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------

NON_TERMINAL = ("SCHEDULED", "CHECKED_IN", "COMPLETED")


def appt_interval(appt):
    start = util.parse_iso(appt["start_at"])
    end = util.parse_iso(appt["end_at"])
    return start, end


# ---------------------------------------------------------------------------
# Booking gates (PRD §3.3) — each raises its named error; order fixed in §3.4
# ---------------------------------------------------------------------------

def active_intake_for(client_id):
    """Return the client's currently ACTIVE intake (regardless of expiry), or None."""
    for i in db.intakes.values():
        if i["client_id"] == client_id and i["intake_status"] == "ACTIVE":
            return i
    return None


def cleared_tags_for(client_id):
    """Tags currently cleared for a client by FINALIZED/AMENDED notes.

    A SoapNote clears tags for the appointment's client. We track cleared tags
    per client on the client record under the internal key _cleared_tags as a
    multiset-free set; clearance is applied/revoked at finalize/reopen time.
    """
    client = db.clients.get(client_id)
    if client is None:
        return set()
    return set(client.get("_cleared_tags", set()))


def consent_gate(consent, modality):
    """ERR_CONSENT_REQUIRED if consent not usable for this modality."""
    if consent["consent_status"] != "ACTIVE":
        return False
    if consent["draping_policy"] == "DECLINE_TREATMENT":
        return False
    # DEEP_TISSUE-tagged modality requires sensitive_area_consent True
    if "DEEP_TISSUE" in modality.get("contraindication_tags", []):
        if not consent["sensitive_area_consent"]:
            return False
    return True


def contraindication_gate(client_id, modality):
    """ERR_CONTRAINDICATION if any matching risk tag lacks a clearing note.

    Compares modality contraindication_tags against the client's ACTIVE intake
    risk_flags. For each tag in both, a finalized note must have cleared it.
    """
    intake = active_intake_for(client_id)
    risks = set(intake["risk_flags"]) if intake else set()
    tags = set(modality.get("contraindication_tags", []))
    matching = tags & risks
    if not matching:
        return True
    cleared = cleared_tags_for(client_id)
    for tag in matching:
        if tag not in cleared:
            return False
    return True


def intake_gate(client_id):
    """ERR_INTAKE_INVALID unless client has ACTIVE intake with expires_at > clock."""
    intake = active_intake_for(client_id)
    if intake is None:
        return False
    if util.parse_iso(intake["expires_at"]) > clock.now():
        return True
    return False


def license_gate(therapist):
    return license_status(therapist) == "ACTIVE"


def certification_gate(therapist, modality):
    if not modality.get("requires_certification", False):
        return True
    for c in db.certifications.values():
        if (c["therapist_id"] == therapist["id"]
                and c["modality_code"] == modality["code"]
                and cert_status(c) == "ACTIVE"):
            return True
    return False


def table_suitable(table, modality):
    """ERR_TABLE_UNSUITABLE: PRENATAL on non-prenatal table, or archived table."""
    if table["archived"]:
        return False
    if modality["code"] == "PRENATAL" and not table["supports_prenatal"]:
        return False
    return True


def table_overlap(table, start, end, exclude_id=None):
    """True when buffered intervals collide with a non-terminal appt on table.

    The requested interval, extended by turnover_buffer_minutes, is checked
    against every non-terminal appointment on the same table. Sessions closer
    together than the buffer collide (interval-with-buffer adjacency).
    """
    buffer = timedelta(minutes=table["turnover_buffer_minutes"])
    req_start = start - buffer
    req_end = end + buffer
    for a in db.appointments.values():
        if a["id"] == exclude_id:
            continue
        if a["table_id"] != table["id"]:
            continue
        if a["scheduling_status"] not in NON_TERMINAL:
            continue
        a_start, a_end = appt_interval(a)
        # collide if buffered request interval overlaps the other interval
        # Buffered adjacency: gap smaller than buffer => collide. Using
        # half-open overlap on the buffer-extended request interval vs raw other.
        if req_start < a_end and a_start < req_end:
            return True
    return False


def therapist_overlap(therapist_id, start, end, exclude_id=None):
    """True on genuine overlap (closed interval, no buffer); touching is allowed."""
    for a in db.appointments.values():
        if a["id"] == exclude_id:
            continue
        if a["therapist_id"] != therapist_id:
            continue
        if a["scheduling_status"] not in NON_TERMINAL:
            continue
        a_start, a_end = appt_interval(a)
        # touching end-to-start allowed -> strict overlap only
        if start < a_end and a_start < end:
            return True
    return False


# ---------------------------------------------------------------------------
# Fee proration (PRD §3.7)
# ---------------------------------------------------------------------------

def base_value(modality, duration_minutes):
    """base_price_cents * duration_minutes / 60 as exact rational."""
    return Fraction(modality["base_price_cents"] * duration_minutes, 60)


def fee_fraction(lead_minutes):
    if lead_minutes >= 1440:
        return Fraction(0)
    if lead_minutes >= 120:
        return Fraction(1, 2)
    if lead_minutes > 0:
        return Fraction(3, 4)
    return Fraction(1)


def compute_fee(modality, duration_minutes, start_at_dt, strikes):
    base = base_value(modality, duration_minutes)
    lead_seconds = (start_at_dt - clock.now()).total_seconds()
    lead_minutes = Fraction(int(lead_seconds), 60)
    frac = fee_fraction(lead_minutes)
    multiplier = Fraction(3, 2) if strikes >= 3 else Fraction(1)
    raw = base * frac * multiplier
    return util.round_half_up(raw)


# ---------------------------------------------------------------------------
# Service charge & waterfall (PRD §3.8)
# ---------------------------------------------------------------------------

def active_package_for(appt):
    """Return the appointment's package if ACTIVE and owned by appt client."""
    pid = appt.get("package_id")
    if not pid:
        return None
    pkg = db.packages.get(pid)
    if pkg is None:
        return None
    if pkg["package_status"] != "ACTIVE":
        return None
    if pkg["client_id"] != appt["client_id"]:
        return None
    return pkg


def compute_service_charge(appt, modality):
    base = base_value(modality, appt["duration_minutes"])
    if appt["payer"] == "MEMBERSHIP":
        return 0
    if appt["payer"] in ("CASH", "HSA"):
        pkg = active_package_for(appt)
        if pkg is not None:
            plan = db.membership_plans[pkg["plan_id"]]
            disc = plan.get("_disc_frac")
            if disc is None:
                disc = Fraction(str(plan["member_discount_pct"]))
            discounted = base * (Fraction(1) - disc)
            return util.round_half_up(discounted)
    return util.round_half_up(base)


# ---------------------------------------------------------------------------
# Commission (PRD §3.9)
# ---------------------------------------------------------------------------

def compute_commission(therapist, service_charge_cents):
    if service_charge_cents <= 0:
        return 0
    if therapist["commission_scheme"] == "FLAT":
        frac = therapist.get("_flat_frac")
        if frac is None:
            frac = Fraction(str(therapist["flat_commission_pct"]))
        return util.round_half_up(Fraction(service_charge_cents) * frac)
    # TIERED — marginal across non-archived tiers
    tiers = [t for t in db.commission_tiers.values() if not t["archived"]]
    tiers.sort(key=lambda t: (t["tier_index"], t["floor_revenue_cents"], t["created_at"], t.get("_seq", 0)))
    old = Fraction(therapist["mtd_service_revenue_cents"])
    new = old + Fraction(service_charge_cents)
    total = Fraction(0)
    for i, tier in enumerate(tiers):
        lower = Fraction(tier["floor_revenue_cents"])
        if i + 1 < len(tiers):
            upper = Fraction(tiers[i + 1]["floor_revenue_cents"])
        else:
            upper = None
        hi = new if upper is None else min(new, upper)
        lo = max(old, lower)
        slice_amt = hi - lo
        if slice_amt > 0:
            pct = tier.get("_pct_frac")
            if pct is None:
                pct = Fraction(str(tier["commission_pct"]))
            total += slice_amt * pct
    return util.round_half_up(total)


# ---------------------------------------------------------------------------
# Cascades & reverts
# ---------------------------------------------------------------------------

def refund_credit_if_redeemed(appt):
    """If a credit was redeemed for this appt, write a REFUND entry (delta +1)."""
    if appt.get("_credit_redeemed") and appt.get("package_id"):
        pkg = db.packages.get(appt["package_id"])
        if pkg is not None:
            pkgsvc.refund_credit(pkg)
            appt["_credit_redeemed"] = False


def cancel_for_consent_revoke(appt):
    """Cascade cancellation triggered by consent revocation (PRD §3.2)."""
    appt["scheduling_status"] = "CANCELLED"
    appt["cancel_reason"] = "CONSENT_REVOKED"
    appt["no_show_fee_cents"] = 0
    refund_credit_if_redeemed(appt)
    h.touch(appt)
