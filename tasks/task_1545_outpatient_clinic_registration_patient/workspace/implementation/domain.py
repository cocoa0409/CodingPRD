"""Business logic: calculations, clearance derivation, matching, cascades.

Every rule here traces to SCAFFOLD.yaml section 1.3 (calculations) and the
workflow narratives of PRD.md section 3.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db
from core import now, touch, parse_d

# --- pinned constants (SCAFFOLD calculations / PRD) ---------------------------
LATE_ARRIVAL_CUTOFF_MINUTES = 30
NO_SHOW_GRACE_MINUTES = 30
ELIGIBILITY_STALENESS_DAYS = 30
STRIKE_WINDOW_DAYS = 365
HIGH_RISK_STRIKE_THRESHOLD = 2
FEE_SCHEDULE_CENTS = {"NEW": 22000, "ESTABLISHED": 14000, "PROCEDURE": 45000, "IMAGING": 38000}
NEW_PATIENT_LOADING = Decimal("1.2")

LIVE_APPT_STATES = ("SCHEDULED", "PRE_CHECKED", "READY", "ARRIVED", "IN_ROOM")
PRE_ARRIVAL_STATES = ("SCHEDULED", "PRE_CHECKED", "READY")


def rhu(x):
    """Round half up to a whole cent (single final rounding)."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ no-show strikes
def strike_count(patient_id, as_of):
    """Trailing 365-day half-open window [as_of - 365d, as_of)."""
    lo = as_of - timedelta(days=STRIKE_WINDOW_DAYS)
    n = 0
    for a in db.appointments.values():
        if a["patient_id"] == patient_id and a["status"] == "NO_SHOW":
            if lo <= a["_start_dt"] < as_of:
                n += 1
    return n


def propagate_strikes(patient_id):
    """Recompute no_show_risk_strikes on the patient's live pre-arrival visits."""
    n = strike_count(patient_id, now())
    for a in db.appointments.values():
        if a["patient_id"] == patient_id and a["status"] in PRE_ARRIVAL_STATES:
            if a["no_show_risk_strikes"] != n:
                a["no_show_risk_strikes"] = n
                touch(a)


# ------------------------------------------------------------- eligibility staleness
def refresh_staleness(chk):
    """Lazy STALE flip: current date strictly more than 30 days after checked date."""
    if chk["result"] != "STALE":
        if now().date() > chk["_checked_dt"].date() + timedelta(days=ELIGIBILITY_STALENESS_DAYS):
            chk["result"] = "STALE"
            touch(chk)


def latest_fresh_check(appt_id, policy_id=None, require_active=False):
    best = None
    for c in db.eligibility_checks.values():
        if c["appointment_id"] != appt_id:
            continue
        if policy_id is not None and c["policy_id"] != policy_id:
            continue
        refresh_staleness(c)
        if c["result"] == "STALE":
            continue
        if require_active and c["coverage_status"] != "ACTIVE":
            continue
        if best is None or c["_seq"] > best["_seq"]:
            best = c
    return best


# ------------------------------------------------------------------ shared lookups
def primary_policy(patient_id):
    """The non-VOIDED policy with priority_rank 1, if any."""
    best = None
    for p in db.policies.values():
        if p["patient_id"] == patient_id and p["status"] != "VOIDED" and p["priority_rank"] == 1:
            if best is None or p["_seq"] < best["_seq"]:
                best = p
    return best


def latest_estimate(appt_id):
    """Latest non-SUPERSEDED estimate for the appointment (PROVISIONAL or FINAL)."""
    best = None
    for e in db.estimates.values():
        if e["appointment_id"] == appt_id and e["status"] != "SUPERSEDED":
            if best is None or e["_seq"] > best["_seq"]:
                best = e
    return best


def latest_provisional_estimate(appt_id):
    best = None
    for e in db.estimates.values():
        if e["appointment_id"] == appt_id and e["status"] == "PROVISIONAL":
            if best is None or e["_seq"] > best["_seq"]:
                best = e
    return best


def satisfying_auth(appt):
    """Earliest APPROVED authorization covering this appointment's date."""
    appt_date = appt["_start_dt"].date()
    best = None
    for a in db.authorizations.values():
        if (a["appointment_id"] == appt["id"] and a["status"] == "APPROVED"
                and parse_d(a["valid_until"]) >= appt_date):
            if best is None or a["_seq"] < best["_seq"]:
                best = a
    return best


# ------------------------------------------------------------------ clearance gate
def compute_clearance(appt):
    """Pinned evaluation order per PRD section 3.5. Pure (no writes)."""
    patient = db.patients.get(appt["patient_id"])
    appt_date = appt["_start_dt"].date()

    # 1. authorization need
    auth_needed = appt["visit_type"] in ("PROCEDURE", "IMAGING")
    if not auth_needed:
        chk = latest_fresh_check(appt["id"])
        if chk is not None and chk["auth_required"]:
            auth_needed = True

    # 2. authorization satisfaction
    auth_satisfied = (not auth_needed) or (satisfying_auth(appt) is not None)

    # 3./4. referral need & satisfaction
    pp = primary_policy(appt["patient_id"])
    referral_needed = pp is not None and pp["plan_type"] in ("HMO", "EPO")
    referral_satisfied = (not referral_needed) or appt["referral_id"] is not None

    # 5. demographics
    demog_ok = patient is not None and patient["status"] == "REGISTERED"

    # 6./7. estimate + gate
    est = latest_estimate(appt["id"])
    if not (demog_ok and auth_satisfied and referral_satisfied):
        gate = "BLOCKED"
    elif (est is not None and est["deposit_required_cents"] > 0
            and appt["amount_collected_cents"] < est["deposit_required_cents"]):
        gate = "CLEAR_WITH_PAYMENT"
    else:
        gate = "CLEAR"
    return gate, auth_satisfied


def recompute_clearance(appt):
    """Write the derived gate/auth_satisfied; bump the appointment on change."""
    gate, sat = compute_clearance(appt)
    changed = gate != appt["registration_gate"] or sat != appt["auth_satisfied"]
    appt["registration_gate"] = gate
    appt["auth_satisfied"] = sat
    if changed:
        touch(appt)
    return changed


# ------------------------------------------------------------------ referral matching
def run_matching(appt):
    """Deterministic weighted selector; returns True when referral_id changed."""
    if appt["status"] not in PRE_ARRIVAL_STATES:
        return False
    d = appt["_start_dt"].date()
    npi = appt["referring_provider_npi"]
    best = None
    best_key = None
    for r in db.referrals.values():
        if r["patient_id"] != appt["patient_id"] or r["status"] != "OPEN":
            continue
        if r["specialty_code"] != appt["department_code"]:
            continue
        if r["procedure_code"] != appt["procedure_code"]:
            continue
        if not (parse_d(r["valid_from"]) <= d <= parse_d(r["valid_until"])):
            continue
        if r["visits_consumed"] >= r["visits_authorized"]:
            continue
        key = (
            0 if (npi is not None and r["referring_provider_npi"] == npi) else 1,
            r["valid_until"],
            r["created_at"],
            r["_seq"],
        )
        if best_key is None or key < best_key:
            best, best_key = r, key
    new_id = best["id"] if best is not None else None
    changed = new_id != appt["referral_id"]
    appt["referral_id"] = new_id
    return changed


def rematch_patient_unmatched(patient_id):
    """Re-run matching for the patient's still-unmatched live appointments."""
    for a in db.appointments.values():
        if (a["patient_id"] == patient_id and a["status"] in PRE_ARRIVAL_STATES
                and a["referral_id"] is None):
            run_matching(a)
            recompute_clearance(a)


# ------------------------------------------------------------------ collections
def recompute_collected(appt):
    """Full (non-incremental) recompute, clamped at zero."""
    posts = refs = 0
    for p in db.payments.values():
        if p["appointment_id"] == appt["id"] and p["status"] == "POSTED":
            if p["kind"] == "POST":
                posts += p["amount_cents"]
            else:
                refs += p["amount_cents"]
    appt["amount_collected_cents"] = max(0, posts - refs)


# ------------------------------------------------------------------ copay estimate
def estimate_amounts(appt, policy, allowed_amount_cents):
    """copay_estimate + deposit_rule. Returns (method, resp_cents, deposit_cents)."""
    chk = latest_fresh_check(appt["id"], policy_id=policy["id"], require_active=True)
    if chk is not None:
        method = "PAYER_VERIFIED"
        resp = chk["copay_cents"]
        if resp == 0:
            ded = min(allowed_amount_cents, policy["deductible_remaining_cents"])
            resp = ded + rhu(
                Decimal(allowed_amount_cents - ded) * Decimal(chk["coinsurance_pct"]) / Decimal(100)
            )
        resp = min(resp, policy["oop_max_remaining_cents"])
    else:
        method = "FEE_SCHEDULE"
        base = FEE_SCHEDULE_CENTS[appt["visit_type"]]
        mult = Decimal("1.0") if appt["visit_type"] == "ESTABLISHED" else NEW_PATIENT_LOADING
        resp = rhu(Decimal(base) * mult)

    strikes = strike_count(appt["patient_id"], now())
    if strikes >= HIGH_RISK_STRIKE_THRESHOLD:
        pct = Decimal("1.00")
    elif appt["visit_type"] == "NEW":
        pct = Decimal("0.50")
    else:
        pct = Decimal("0.25")
    deposit = rhu(Decimal(resp) * pct)
    return method, resp, deposit


def repin_cached_estimate(appt):
    """Re-derive the appointment's cached responsibility from newest PROVISIONAL."""
    est = latest_provisional_estimate(appt["id"])
    appt["estimated_patient_responsibility_cents"] = (
        est["estimated_patient_responsibility_cents"] if est is not None else 0
    )


# ------------------------------------------------------------------ double booking
def double_booked(provider_code, start_dt, duration_minutes, exclude_id=None):
    """[start, start+duration) overlap; touching intervals do not overlap."""
    s = start_dt
    e = s + timedelta(minutes=duration_minutes)
    for a in db.appointments.values():
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if a["provider_code"] != provider_code:
            continue
        if a["status"] not in LIVE_APPT_STATES:
            continue
        s2 = a["_start_dt"]
        e2 = s2 + timedelta(minutes=a["duration_minutes"])
        if s < e2 and s2 < e:
            return True
    return False


# ------------------------------------------------------------------ clock cascades
def expire_timeboxed():
    """Advance-triggered expiry of referrals and authorizations (logical clock)."""
    today = now().date()
    for r in db.referrals.values():
        if r["status"] == "OPEN" and today > parse_d(r["valid_until"]):
            r["status"] = "EXPIRED"
            touch(r)
            for a in db.appointments.values():
                if a["referral_id"] == r["id"] and a["status"] in ("SCHEDULED", "PRE_CHECKED"):
                    a["referral_id"] = None
                    run_matching(a)
                    recompute_clearance(a)
    for auth in db.authorizations.values():
        if auth["status"] == "APPROVED" and today > parse_d(auth["valid_until"]):
            auth["status"] = "EXPIRED"
            touch(auth)
            appt = db.appointments.get(auth["appointment_id"])
            if appt is not None:
                recompute_clearance(appt)
