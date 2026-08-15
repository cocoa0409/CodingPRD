"""Business logic: calculations, sweeps, cascades, recomputations."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

import db
from db import (
    policies, auditors, class_codes, selection_runs, work_orders,
    records_requests, appointments, allocations, exposures, certificates,
    results, disputes, billings, mod_revisions,
)

getcontext().prec = 28

# --- constants --------------------------------------------------------------
PHYSICAL_MIN_PREMIUM_CENTS = 1000000
VOLUNTARY_MIN_PREMIUM_CENTS = 500000
RECORDS_DUE_DAYS = 15
APPOINTMENT_WINDOW_DAYS = 60
DISPUTE_WINDOW_DAYS = 30
BILLING_DUE_DAYS = 30
CANCELLATION_GRACE_DAYS = 30
ESTIMATED_AUDIT_MULTIPLIER = Decimal("1.25")
VARIANCE_THRESHOLD = Decimal("0.05")
STEPS_PER_UNIT_VARIANCE = 20
MOD_FLOOR = Decimal("0.75")
MOD_CEILING = Decimal("1.50")

WO_TERMINAL = {"CLOSED", "SUPERSEDED_BY_REAUDIT", "CANCELLED"}
APPOINTMENT_ACTIVE = {"SCHEDULED", "CONFIRMED"}
RECORDS_NONTERMINAL = {"OPEN", "OVERDUE"}
ALLOC_MUTATION_WO_STATES = {
    "RECORDS_REQUESTED", "APPOINTMENT_SCHEDULED", "FIELD_WORK_DONE", "RESULT_DRAFTED",
}


def round_half_up(value):
    """Round a Decimal to integer, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- graph helpers ----------------------------------------------------------

def policy_of_wo(wo):
    return policies.get(wo["policy_id"])


def wo_of_allocation(alloc):
    return work_orders.get(alloc["audit_work_order_id"])


def wo_of_exposure(exposure):
    return work_orders.get(exposure["audit_work_order_id"])


def exposure_of_cert(cert):
    return exposures.get(cert["subcontractor_exposure_id"])


def wo_of_cert(cert):
    exp = exposure_of_cert(cert)
    return work_orders.get(exp["audit_work_order_id"]) if exp else None


def wo_of_appointment(appt):
    return work_orders.get(appt["audit_work_order_id"])


def wo_of_records_request(rr):
    return work_orders.get(rr["audit_work_order_id"])


def wo_of_result(result):
    return work_orders.get(result["audit_work_order_id"])


def result_of_dispute(dispute):
    return results.get(dispute["audit_result_id"])


def result_of_billing(billing):
    return results.get(billing["audit_result_id"])


def result_of_wo(wo):
    for r in results.values():
        if r["audit_work_order_id"] == wo["id"]:
            return r
    return None


def billings_of_result(result_id):
    return [b for b in billings.values() if b["audit_result_id"] == result_id]


def appointments_of_wo(wo_id):
    return [a for a in appointments.values() if a["audit_work_order_id"] == wo_id]


def allocations_of_wo(wo_id):
    return [a for a in allocations.values() if a["audit_work_order_id"] == wo_id]


def exposures_of_wo(wo_id):
    return [e for e in exposures.values() if e["audit_work_order_id"] == wo_id]


def certs_of_exposure(exposure_id):
    return [c for c in certificates.values()
            if c["subcontractor_exposure_id"] == exposure_id]


def records_of_wo(wo_id):
    return [r for r in records_requests.values()
            if r["audit_work_order_id"] == wo_id]


# --- subcontractor inclusion (stored world: VERIFIED certs only) -------------

def _date_intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def _covered_days_union(cert_list, period_start, period_end):
    """Merge cert coverage windows (closed, day granularity) and count days
    covered within the audit period."""
    p_s = period_start.date()
    p_e = period_end.date()
    intervals = []
    for c in cert_list:
        c_s = db.parse_dt(c["coverage_effective_date"]).date()
        c_e = db.parse_dt(c["coverage_expiration_date"]).date()
        lo = max(c_s, p_s)
        hi = min(c_e, p_e)
        if lo <= hi:
            intervals.append((lo.toordinal(), hi.toordinal()))
    if not intervals:
        return 0
    intervals.sort()
    covered = 0
    cur_lo, cur_hi = intervals[0]
    for lo, hi in intervals[1:]:
        if lo <= cur_hi + 1:
            cur_hi = max(cur_hi, hi)
        else:
            covered += cur_hi - cur_lo + 1
            cur_lo, cur_hi = lo, hi
    covered += cur_hi - cur_lo + 1
    return covered


def inclusion_from_certs(cert_list, payments_dollars, period_start, period_end):
    """Return (status, included_dollars) given the acceptable certificates."""
    period_days = (period_end.date() - period_start.date()).days + 1
    if period_days <= 0:
        period_days = 1
    if not cert_list:
        return "INCLUDED", payments_dollars
    covered = _covered_days_union(cert_list, period_start, period_end)
    if covered >= period_days:
        return "EXCLUDED", 0
    if covered <= 0:
        return "INCLUDED", payments_dollars
    uncovered = period_days - covered
    included = round_half_up(
        Decimal(payments_dollars) * Decimal(uncovered) / Decimal(period_days))
    return "PARTIAL_INCLUDED", included


def recompute_exposure(exposure):
    """Stored inclusion reflects VERIFIED certificates only. Mutates the
    exposure (full mutation) and refreshes the work order's premium base."""
    wo = wo_of_exposure(exposure)
    verified = [c for c in certs_of_exposure(exposure["id"])
                if c["status"] == "VERIFIED"]
    period_start = db.parse_dt(wo["audit_period_start"])
    period_end = db.parse_dt(wo["audit_period_end"])
    status, included = inclusion_from_certs(
        verified, exposure["payments_dollars"], period_start, period_end)
    if exposure["status"] != status or exposure["included_dollars"] != included:
        exposure["status"] = status
        exposure["included_dollars"] = included
        db.touch(exposure)
    recompute_wo_base(wo)


def recompute_wo_base(wo):
    """total_premium_base_dollars = VERIFIED allocations' auditable dollars
    + all exposures' included_dollars. Derived recomputation: updated_at
    refreshes; version does not increment (workflow does not state it)."""
    total = 0
    for a in allocations_of_wo(wo["id"]):
        if a["status"] == "VERIFIED":
            total += a["auditable_payroll_dollars"]
    for e in exposures_of_wo(wo["id"]):
        total += e["included_dollars"]
    if wo.get("total_premium_base_dollars") != total:
        wo["total_premium_base_dollars"] = total
    db.touch_no_version(wo)


# --- audit result computation ------------------------------------------------

def _provisional_included(exposure, wo):
    """Provisional variant: SUBMITTED certificates are treated as if verified
    at full coverage (full exclusion). Otherwise the VERIFIED-based stored
    value stands."""
    certs = certs_of_exposure(exposure["id"])
    if any(c["status"] == "SUBMITTED" for c in certs):
        return 0
    return exposure["included_dollars"]


def compute_figures(wo, variant):
    """variant: 'provisional' | 'final'. Returns dict with total_payroll,
    manual_premium_cents, mod_factor_applied, earned_premium_cents."""
    policy = policy_of_wo(wo)
    base_by_code = {}
    total = 0
    for a in allocations_of_wo(wo["id"]):
        if variant == "final":
            if a["status"] != "VERIFIED":
                continue
        else:
            if a["status"] not in ("DRAFT", "VERIFIED"):
                continue
        base_by_code[a["class_code_id"]] = \
            base_by_code.get(a["class_code_id"], 0) + a["auditable_payroll_dollars"]
        total += a["auditable_payroll_dollars"]
    for e in exposures_of_wo(wo["id"]):
        inc = e["included_dollars"] if variant == "final" \
            else _provisional_included(e, wo)
        base_by_code[e["governing_class_code_id"]] = \
            base_by_code.get(e["governing_class_code_id"], 0) + inc
        total += inc
    manual = 0
    for code_id, base in base_by_code.items():
        cc = class_codes.get(code_id)
        if cc is None:
            continue
        cents = Decimal(base) * Decimal(cc["rate_per_100_cents"]) / Decimal(100)
        manual += round_half_up(cents)
    mod_dec = Decimal(str(policy["experience_mod_factor"]))
    modified = round_half_up(Decimal(manual) * mod_dec)
    earned = max(modified, policy["minimum_premium_cents"])
    return {
        "total_payroll_dollars": total,
        "manual_premium_cents": manual,
        "mod_factor_applied": policy["experience_mod_factor"],
        "earned_premium_cents": earned,
    }


def create_billing_for_result(result, policy):
    adjustment = result["adjustment_cents"]
    if adjustment == 0:
        return None
    btype = "ADDITIONAL_PREMIUM_INVOICE" if adjustment > 0 else "RETURN_PREMIUM_CREDIT"
    issued = db.now_iso()
    due = db.fmt_dt(db.clock_now() + timedelta(days=BILLING_DUE_DAYS))
    billing = db.new_entity({
        "audit_result_id": result["id"],
        "type": btype,
        "amount_cents": abs(adjustment),
        "paid_cents": 0,
        "issued_at": issued,
        "due_at": due,
        "status": "ISSUED",
    })
    billings[billing["id"]] = billing
    return billing


def maybe_create_mod_revision(result, wo, policy):
    """WC only; |variance| >= 0.05. Computed LAST after billing."""
    if policy["coverage_line"] != "WC":
        return None
    estimate = policy["payroll_estimate_dollars"]
    audited = result["total_payroll_dollars"]
    variance = Decimal(audited - estimate) / Decimal(estimate)
    if abs(variance) < VARIANCE_THRESHOLD:
        return None
    steps = int(variance * STEPS_PER_UNIT_VARIANCE)  # trunc toward zero
    revised = Decimal(str(policy["experience_mod_factor"])) + \
        Decimal(steps) * Decimal("0.01")
    revised = revised.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if revised < MOD_FLOOR:
        revised = MOD_FLOOR
    if revised > MOD_CEILING:
        revised = MOD_CEILING
    rev = db.new_entity({
        "policy_id": policy["id"],
        "source_work_order_id": wo["id"],
        "prior_mod_factor": policy["experience_mod_factor"],
        "payroll_variance_ratio": (audited - estimate) / estimate,
        "revised_mod_factor": float(revised),
        "status": "DRAFT",
    })
    mod_revisions[rev["id"]] = rev
    return rev


# --- audit selection ----------------------------------------------------------

def run_selection():
    clock = db.clock_now()
    eligible = [p for p in policies.values()
                if p["status"] == "ACTIVE"
                and db.parse_dt(p["expiration_date"]) <= clock]
    eligible.sort(key=lambda p: (db.parse_dt(p["expiration_date"]),
                                 p["policy_number"]))
    run = db.new_entity({
        "run_at": db.now_iso(),
        "evaluated_count": len(eligible),
        "physical_count": 0,
        "voluntary_count": 0,
        "exempt_count": 0,
    })
    selection_runs[run["id"]] = run
    for p in eligible:
        has_open = any(
            wo["policy_id"] == p["id"] and wo["status"] not in WO_TERMINAL
            for wo in work_orders.values())
        if has_open:
            continue  # skipped silently
        high_hazard = any(
            class_codes.get(cid, {}).get("high_hazard") for cid in p["class_code_ids"])
        if p["estimated_annual_premium_cents"] >= PHYSICAL_MIN_PREMIUM_CENTS \
                or high_hazard:
            tier = "PHYSICAL"
        elif p["estimated_annual_premium_cents"] >= VOLUNTARY_MIN_PREMIUM_CENTS:
            tier = "VOLUNTARY_REPORT"
        else:
            run["exempt_count"] += 1
            continue
        wo = db.new_entity({
            "policy_id": p["id"],
            "selection_run_id": run["id"],
            "reaudit_of_work_order_id": None,
            "assigned_auditor_id": None,
            "audit_type": tier,
            "audit_period_start": p["effective_date"],
            "audit_period_end": p["expiration_date"],
            "status": "SELECTED",
            "no_show_count": 0,
            "marked_noncompliant_by_user_id": None,
            "total_premium_base_dollars": 0,
        })
        work_orders[wo["id"]] = wo
        if tier == "PHYSICAL":
            run["physical_count"] += 1
        else:
            run["voluntary_count"] += 1
        p["status"] = "AUDIT_PENDING"
        db.touch(p)
    db.touch_no_version(run)
    return run


# --- cancellation cascade ------------------------------------------------------

def cancel_policy(policy):
    """Full cancellation cascade; idempotent if already CANCELLED."""
    if policy["status"] == "CANCELLED":
        return
    policy["status"] = "CANCELLED"
    db.touch(policy)
    wos = [wo for wo in work_orders.values() if wo["policy_id"] == policy["id"]]
    for wo in wos:
        if wo["status"] in WO_TERMINAL:
            continue
        wo["status"] = "CANCELLED"
        db.touch(wo)
        for appt in appointments_of_wo(wo["id"]):
            if appt["status"] in APPOINTMENT_ACTIVE:
                appt["status"] = "CANCELLED"
                db.touch(appt)
    for wo in wos:
        res = result_of_wo(wo)
        if not res:
            continue
        for b in billings_of_result(res["id"]):
            if b["status"] in ("ISSUED", "PAST_DUE"):
                b["status"] = "CANCELLED"
                db.touch(b)


# --- clock sweeps ---------------------------------------------------------------

def run_sweeps():
    clock = db.clock_now()
    for rr in records_requests.values():
        if rr["status"] == "OPEN" and clock > db.parse_dt(rr["due_at"]):
            rr["status"] = "OVERDUE"
            db.touch(rr)
    for b in billings.values():
        if b["status"] == "ISSUED" and clock > db.parse_dt(b["due_at"]):
            b["status"] = "PAST_DUE"
            db.touch(b)
    for b in list(billings.values()):
        if b["status"] != "PAST_DUE":
            continue
        grace_end = db.parse_dt(b["due_at"]) + timedelta(days=CANCELLATION_GRACE_DAYS)
        if clock > grace_end:
            res = result_of_billing(b)
            if not res:
                continue
            wo = wo_of_result(res)
            if not wo:
                continue
            policy = policies.get(wo["policy_id"])
            if policy and policy["status"] != "CANCELLED":
                cancel_policy(policy)
