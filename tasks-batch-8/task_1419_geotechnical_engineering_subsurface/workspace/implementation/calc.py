"""Calculations and derived rollups (SCAFFOLD calculations table; PRD 2.8, 2.10, 3.x).

All money math uses Decimal with ROUND_HALF_UP; never float arithmetic.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store

# ---- constants -------------------------------------------------------------
BASE_FEE = {
    "MOISTURE_CONTENT": 4533,
    "ATTERBERG": 24500,
    "SIEVE_ANALYSIS": 18500,
    "UNCONFINED_COMPRESSION": 32000,
    "DIRECT_SHEAR": 55000,
    "CONSOLIDATION": 88000,
    "PROCTOR": 21000,
}
RUSH_MULT = Decimal("1.5")
LAB_MAX_IN_TEST = 6
RERUN_MAX = 2

PROV_PSF_PER_N = Decimal("400")
PROV_CAP = Decimal("8000")
QULT_SU_FACTOR = Decimal("9")
FINAL_MIN = Decimal("1500")
FINAL_CAP = Decimal("12000")

SETTLE_DENOM_PER_N = Decimal("1200")
DEEP_FOUNDATION_THRESHOLD_IN = Decimal("1.0")

DISCOUNT_TIER_GROSS_CENTS = 500000
DISCOUNT_RATE = Decimal("0.05")

MOBILIZATION_CENTS = Decimal("45000")
T1_RATE, T1_MAX = Decimal("4200"), Decimal("25")
T2_RATE, T2_MAX = Decimal("6800"), Decimal("75")
T3_RATE = Decimal("9500")
ROCK_MULT = Decimal("1.8")
ACCESS_SURCHARGE = Decimal("15000")
BORING_MIN = Decimal("25000")

RB_SHORTFALL_CAP = Decimal("0.5")
SO_MULT = Decimal("1.25")
SO_CAP = Decimal("0.75")
APPEAL_MAX = 1

TEST_TYPES = set(BASE_FEE.keys())
DESTRUCTIVE_TYPES = {"UNCONFINED_COMPRESSION", "DIRECT_SHEAR"}


def dec(value):
    return Decimal(str(value))


def round_cents(value):
    """Round a Decimal amount to whole cents, half-up (away from zero)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(value):
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round3(value):
    return float(dec(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# ---- lookups ---------------------------------------------------------------
def active_plan(project_id):
    """The project's latest revision standing in APPROVED or LOCKED."""
    cands = [
        p
        for p in store.plans.values()
        if p["project_id"] == project_id and p["status"] in ("APPROVED", "LOCKED")
    ]
    if not cands:
        return None
    return max(cands, key=lambda p: (p["revision_no"], p["_seq"]))


def project_of_boring(boring):
    plan = store.plans.get(boring["boring_plan_id"])
    if plan is None:
        return None
    return store.projects.get(plan["project_id"])


def project_of_sample(sample):
    boring = store.borings.get(sample["boring_id"])
    if boring is None:
        return None
    return project_of_boring(boring)


# ---- rollups (recomputed on read; PRD 2.10) --------------------------------
def compute_posture(project_id):
    plan = active_plan(project_id)
    if plan is not None:
        boring_ids = {
            b["id"] for b in store.borings.values() if b["boring_plan_id"] == plan["id"]
        }
        for c in store.clearances.values():
            if c["boring_id"] in boring_ids and c["status"] == "CONFLICT_MARKED":
                return "FROZEN"
    for cl in store.claims.values():
        if cl["project_id"] == project_id and cl["status"] in (
            "UNDER_REVIEW",
            "SUBSTANTIATED",
        ):
            return "CLAIM_REVIEW"
    return "OPEN"


def compute_additional_committed(project_id):
    return sum(
        a["authorized_amount_cents"]
        for a in store.auths.values()
        if a["project_id"] == project_id and a["status"] in ("APPROVED", "EXHAUSTED")
    )


def compute_claims_exposure(project_id):
    total = 0
    for cl in store.claims.values():
        if cl["project_id"] != project_id:
            continue
        if cl["status"] == "UNDER_REVIEW":
            total += cl["claimed_amount_cents"]
        elif cl["status"] == "SUBSTANTIATED":
            total += cl.get("quantum_report_baseline_cents") or 0
    return total


def compute_testing_invoice(project_id):
    return sum(
        o["fee_cents"] for o in store.orders.values() if o["project_id"] == project_id
    )


def compute_total_fee(project):
    """Pinned order: testing -> gross -> tier on PRE-discount gross -> discount -> total."""
    testing = compute_testing_invoice(project["id"])
    gross = project["base_fee_cents"] + testing
    if gross >= DISCOUNT_TIER_GROSS_CENTS:
        discount = round_cents(dec(testing) * DISCOUNT_RATE)
    else:
        discount = 0
    return gross - discount


def compute_committed_rig_hours(subcontractor_id):
    total = Decimal("0")
    for ra in store.rig_assignments.values():
        if ra["subcontractor_id"] == subcontractor_id and ra["status"] in (
            "SCHEDULED",
            "MOBILIZED",
        ):
            secs = dec((ra["_window_end"] - ra["_window_start"]).total_seconds())
            total += secs / Decimal("3600")
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---- order fees --------------------------------------------------------------
def order_fee_cents(test_type, priority):
    """Per-line rounding: round each line to whole cents FIRST, then sum."""
    mult = RUSH_MULT if priority == "RUSH" else Decimal("1")
    return round_cents(dec(BASE_FEE[test_type]) * mult)


# ---- geotechnical calculations ----------------------------------------------
def n60_average(project_id):
    """Mean of avg_n60 over active-plan borings in {DRILLED, LOGGED, CLOSED, REFUSED}.

    Returns a 2dp half-up Decimal, or None when the input set is empty.
    """
    plan = active_plan(project_id)
    if plan is None:
        return None
    vals = [
        dec(b["avg_n60"])
        for b in store.borings.values()
        if b["boring_plan_id"] == plan["id"]
        and b["status"] in ("DRILLED", "LOGGED", "CLOSED", "REFUSED")
        and b["avg_n60"] is not None
    ]
    if not vals:
        return None
    mean = sum(vals) / dec(len(vals))
    return mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def bearing_provisional(n60_avg):
    val = PROV_PSF_PER_N * n60_avg
    if val > PROV_CAP:
        val = PROV_CAP
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def bearing_final(qu_psf, fs_required):
    su = dec(qu_psf) / Decimal("2")
    q_ult = QULT_SU_FACTOR * su
    val = q_ult / dec(fs_required)
    if val < FINAL_MIN:
        val = FINAL_MIN
    if val > FINAL_CAP:
        val = FINAL_CAP
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def settlement_estimate(applied_bearing_psf, footing_width_ft, n60_avg):
    val = (dec(applied_bearing_psf) * dec(footing_width_ft)) / (
        SETTLE_DENOM_PER_N * n60_avg
    )
    rounded = val.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    deep = rounded >= DEEP_FOUNDATION_THRESHOLD_IN
    return float(rounded), deep


def latest_accepted_result(sample_id, test_type):
    """Latest ACCEPTED LabTestResult of the given type for a sample."""
    best = None
    for r in store.results.values():
        order = store.orders.get(r["lab_test_order_id"])
        if (
            order is not None
            and order["sample_id"] == sample_id
            and order["test_type"] == test_type
            and order["status"] == "ACCEPTED"
        ):
            if best is None or r["_seq"] > best["_seq"]:
                best = r
    return best


def latest_accepted_uc_qu(project_id):
    """qu_psf of the latest ACCEPTED UNCONFINED_COMPRESSION result of the project."""
    best = None
    for r in store.results.values():
        order = store.orders.get(r["lab_test_order_id"])
        if (
            order is not None
            and order["project_id"] == project_id
            and order["test_type"] == "UNCONFINED_COMPRESSION"
            and order["status"] == "ACCEPTED"
            and r.get("qu_psf") is not None
        ):
            if best is None or r["_seq"] > best["_seq"]:
                best = r
    return best["qu_psf"] if best else None


def has_accepted_uc_order(project_id):
    return any(
        o["project_id"] == project_id
        and o["test_type"] == "UNCONFINED_COMPRESSION"
        and o["status"] == "ACCEPTED"
        for o in store.orders.values()
    )


def uscs_classify(F, LL, PI):
    """USCS decision tree. A-line evaluated unrounded. F == 50.0 is coarse+fines."""
    F = dec(F)
    LL = dec(LL)
    PI = dec(PI)
    a_line = Decimal("0.73") * (LL - Decimal("20"))
    if F < 5:
        return "SW"
    if F <= 12:
        return "SM"
    if F <= 50:
        return "SC" if PI > 7 else "SM"
    if LL < 50:
        return "CL" if (PI >= 7 and PI >= a_line) else "ML"
    return "CH" if PI >= a_line else "MH"


def drilling_cost_cents(actual_depth_ft, rock_depth_ft, access_difficult, first_of_plan):
    """Tiered per-foot price; rock feet are the DEEPEST R feet billed at band*1.8."""
    D = dec(actual_depth_ft)
    R = dec(rock_depth_ft or 0)
    zero = Decimal("0")
    soil = (
        min(D, T1_MAX) * T1_RATE
        + max(zero, min(D, T2_MAX) - T1_MAX) * T2_RATE
        + max(zero, D - T2_MAX) * T3_RATE
    )
    rock_start = D - R
    band1_ft = max(zero, min(D, T1_MAX) - max(rock_start, zero))
    band2_ft = max(zero, min(D, T2_MAX) - max(rock_start, T1_MAX))
    band3_ft = max(zero, D - max(rock_start, T2_MAX))
    rock_extra = (band1_ft * T1_RATE + band2_ft * T2_RATE + band3_ft * T3_RATE) * (
        ROCK_MULT - Decimal("1")
    )
    surcharge = ACCESS_SURCHARGE if access_difficult else zero
    boring_cost = max(BORING_MIN, soil + rock_extra + surcharge)
    total = boring_cost + (MOBILIZATION_CENTS if first_of_plan else zero)
    return round_cents(total)


def claim_quanta(claim):
    """Both variants of changed_condition_quantum.

    Returns (quantum_report_baseline_cents, quantum_site_observed_cents).
    """
    B = claim.get("baseline_bearing_psf")
    O = observed_bearing_for_claim(claim)
    if B is None or O is None:
        return 0, 0
    B = dec(B)
    O = dec(O)
    if O >= B:
        return 0, 0
    shortfall = (B - O) / B  # unrounded
    claimed = dec(claim["claimed_amount_cents"])
    rb = round_cents(claimed * min(shortfall, RB_SHORTFALL_CAP))
    so = round_cents(claimed * min(shortfall * SO_MULT, SO_CAP))
    return rb, so


def observed_bearing_for_claim(claim):
    """Linked visit's observed value, else the project's most recent FINDINGS_FILED
    visit by visit_date (tie-break created_at ASC)."""
    if claim.get("observation_visit_id"):
        visit = store.visits.get(claim["observation_visit_id"])
        return visit.get("observed_bearing_psf") if visit else None
    cands = [
        v
        for v in store.visits.values()
        if v["project_id"] == claim["project_id"] and v["status"] == "FINDINGS_FILED"
    ]
    if not cands:
        return None
    # most recent by visit_date; ties -> earliest created_at (smallest _seq)
    best = max(cands, key=lambda v: (v["_visit_date"], -v["_seq"]))
    return best.get("observed_bearing_psf")
