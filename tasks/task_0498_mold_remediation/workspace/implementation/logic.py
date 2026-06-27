"""Domain calculations, derived-field reconciliation, and cascades (PRD §2.5, §2.10, §1.3)."""
from db import db, touch
from util import clock, round_half_up, floor_to_int, parse_dt, days_between_floor
from datetime import timedelta

# ---- Constants (SCAFFOLD §1.3) ----
AIR_ELEVATED = 1000
AIR_HAZARD = 10000
SURFACE_ELEVATED = 50
SURFACE_HAZARD = 500
LITERS_PER_M3 = 1000

NESHAP_SQFT_THRESHOLD = 160
NESHAP_NOTICE_DAYS = 10
SECONDS_PER_DAY = 86400
PPE_FIT_VALID_DAYS = 365
MIN_NEGATIVE_PRESSURE_PA = 5

TIER1_KG = 100
TIER2_KG = 500
RATE1_CPK = 80
RATE2_CPK = 120
RATE3_CPK = 200
ASBESTOS_SURCHARGE = "1.5"
LEAD_SURCHARGE = "1.25"
MOLD_SURCHARGE = "1.0"

ASBESTOS_LIMIT = 70
LEAD_LIMIT = 200
MOLD_LIMIT = 900

LABOR_CPK = 1500

SEVERITY = {"CLEAN": 0, "ELEVATED": 1, "HAZARDOUS": 2}
SEVERITY_INV = {0: "CLEAN", 1: "ELEVATED", 2: "HAZARDOUS"}


# ===========================================================================
# Worker eligibility (§1.3 worker_eligibility)
# ===========================================================================
def is_cert_current(worker):
    now = clock.get()
    cert = parse_dt(worker.get("cert_expires_at"))
    fit = parse_dt(worker.get("ppe_fit_test_at"))
    if cert is None or fit is None:
        return False
    cert_ok = cert > now
    fit_ok = fit > (now - timedelta(days=PPE_FIT_VALID_DAYS))
    return bool(cert_ok and fit_ok)


# ===========================================================================
# NESHAP applicability (§1.3 neshap_applicability)
# ===========================================================================
def compute_neshap_required(project):
    return project["hazard_class"] == "ASBESTOS" and project["structure_sqft"] >= NESHAP_SQFT_THRESHOLD


# ===========================================================================
# Sample concentration & grade (§1.3 sample_concentration / sample_grade)
# ===========================================================================
def compute_sample_concentration(sample):
    if sample["sample_type"] == "AIR":
        return round_half_up(sample["raw_count"] / sample["volume_liters"] * LITERS_PER_M3)
    return sample["raw_count"]


def compute_sample_grade(concentration, sample_type):
    if sample_type == "AIR":
        if concentration < AIR_ELEVATED:
            return "CLEAN"
        if concentration < AIR_HAZARD:
            return "ELEVATED"
        return "HAZARDOUS"
    else:
        if concentration < SURFACE_ELEVATED:
            return "CLEAN"
        if concentration < SURFACE_HAZARD:
            return "ELEVATED"
        return "HAZARDOUS"


# ===========================================================================
# Assessment finding_level (§1.3 finding_level)
# ===========================================================================
def child_samples(assessment_id):
    return [s for s in db.samples.values() if s["assessment_id"] == assessment_id]


def compute_finding_level(assessment):
    analyzed = [s for s in child_samples(assessment["id"]) if s["status"] == "ANALYZED"]
    if not analyzed:
        return "CLEAN"
    worst = max(SEVERITY[s["result_grade"]] for s in analyzed)
    return SEVERITY_INV[worst]


def maybe_advance_assessment_status(assessment):
    """System transition SAMPLED -> ANALYZED when every child sample is in
    {ANALYZED, VOIDED} and >= 1 ANALYZED."""
    if assessment["status"] != "SAMPLED":
        return
    kids = child_samples(assessment["id"])
    if not kids:
        return
    if all(s["status"] in ("ANALYZED", "VOIDED") for s in kids) and any(
        s["status"] == "ANALYZED" for s in kids
    ):
        assessment["status"] = "ANALYZED"
        assessment["finding_level"] = compute_finding_level(assessment)
        touch(assessment)


def recompute_finding_level(assessment):
    new_level = compute_finding_level(assessment)
    if new_level != assessment.get("finding_level"):
        assessment["finding_level"] = new_level
        touch(assessment)


# ===========================================================================
# Project open_finding_count (§1.3 open_findings)
# ===========================================================================
def project_assessments(project_id):
    return [a for a in db.assessments.values() if a["project_id"] == project_id]


def compute_open_finding_count(project_id):
    count = 0
    for a in project_assessments(project_id):
        if a["finding_level"] in ("ELEVATED", "HAZARDOUS") and a["status"] != "CLEARED":
            count += 1
    return count


def recompute_open_finding_count(project):
    new_count = compute_open_finding_count(project["id"])
    if new_count != project.get("open_finding_count"):
        project["open_finding_count"] = new_count
        touch(project)


# ===========================================================================
# Containment compliance (§1.3 containment_compliance)
# ===========================================================================
def zone_logs(zone_id):
    return [pl for pl in db.pressure_logs.values() if pl["zone_id"] == zone_id]


def compute_latest_pressure(zone_id):
    logs = zone_logs(zone_id)
    if not logs:
        return 0
    # greatest reading_at; tie-break greatest created_at (use _seq as created_at proxy)
    def key(pl):
        return (parse_dt(pl["reading_at"]), pl["_seq"])
    latest = max(logs, key=key)
    return latest["reading_pa"]


def recompute_zone_compliance(zone):
    latest = compute_latest_pressure(zone["id"])
    compliant = latest >= zone["required_pressure_pa"]
    changed = (zone.get("latest_pressure_pa") != latest) or (zone.get("is_compliant") != compliant)
    zone["latest_pressure_pa"] = latest
    zone["is_compliant"] = compliant
    if changed:
        touch(zone)
    return compliant


# ===========================================================================
# Revision depth (§1.3 revision_depth)
# ===========================================================================
def compute_revision_index(supersedes_order_id):
    if not supersedes_order_id:
        return 0
    pred = db.orders.get(supersedes_order_id)
    if pred is None:
        return 0
    return pred.get("revision_index", 0) + 1


# ===========================================================================
# Disposal fee (§1.3 disposal_fee) — per-tier floor, then surcharge, then floor
# ===========================================================================
def compute_disposal_fee(manifest_weight_kg, abatement_type):
    from decimal import Decimal
    w = Decimal(str(manifest_weight_kg))
    tier1_kg = min(w, Decimal(TIER1_KG))
    tier2_kg = min(max(w - Decimal(TIER1_KG), Decimal(0)), Decimal(TIER2_KG - TIER1_KG))
    tier3_kg = max(w - Decimal(TIER2_KG), Decimal(0))
    base = 0
    base += floor_to_int(tier1_kg * Decimal(RATE1_CPK))
    base += floor_to_int(tier2_kg * Decimal(RATE2_CPK))
    base += floor_to_int(tier3_kg * Decimal(RATE3_CPK))
    if abatement_type == "ASBESTOS":
        mult = Decimal(ASBESTOS_SURCHARGE)
    elif abatement_type == "LEAD":
        mult = Decimal(LEAD_SURCHARGE)
    else:
        mult = Decimal(MOLD_SURCHARGE)
    return floor_to_int(Decimal(base) * mult)


# ===========================================================================
# Clearance concentration & outcome (§1.3)
# ===========================================================================
def compute_clearance_concentration(ct):
    return round_half_up(ct["clearance_air_count"] / ct["clearance_volume_liters"] * LITERS_PER_M3)


def hazard_limit(hazard_class):
    return {"ASBESTOS": ASBESTOS_LIMIT, "LEAD": LEAD_LIMIT, "MOLD": MOLD_LIMIT}[hazard_class]


def compute_clearance_outcome(concentration, hazard_class):
    limit = hazard_limit(hazard_class)
    return "PASS" if concentration < limit else "FAIL"


# ===========================================================================
# Project posture (§1.3 project_posture) — first-match precedence
# ===========================================================================
def project_orders(project_id):
    return [o for o in db.orders.values() if o["project_id"] == project_id]


def project_zones(project_id):
    return [z for z in db.zones.values() if z["project_id"] == project_id]


def project_clearances(project_id):
    return [c for c in db.clearances.values() if c["project_id"] == project_id]


def compute_posture(project):
    pid = project["id"]
    zones = project_zones(pid)
    orders = project_orders(pid)
    clearances = project_clearances(pid)

    # 1. FROZEN if any zone BREACHED
    if any(z["status"] == "BREACHED" for z in zones):
        return "FROZEN"

    non_cancelled = [o for o in orders if o["status"] != "CANCELLED"]

    # 2. VERIFIED: >=1 order, every order in {COMPLETED, CANCELLED}, every
    #    non-cancelled order has a SIGNED_OFF clearance, open_finding_count == 0
    if orders and all(o["status"] in ("COMPLETED", "CANCELLED") for o in orders):
        signed_orders = {
            c["abatement_order_id"]
            for c in clearances
            if c["status"] == "SIGNED_OFF"
        }
        if non_cancelled and all(o["id"] in signed_orders for o in non_cancelled) and \
                project.get("open_finding_count", 0) == 0:
            return "VERIFIED"

    # 3. CLEARANCE_PENDING: >=1 non-cancelled order and all non-cancelled COMPLETED
    if non_cancelled and all(o["status"] == "COMPLETED" for o in non_cancelled):
        return "CLEARANCE_PENDING"

    # 4. ABATING: any order IN_PROGRESS or REOPENED
    if any(o["status"] in ("IN_PROGRESS", "REOPENED") for o in orders):
        return "ABATING"

    # 5. CONTAINED: any zone ACTIVE
    if any(z["status"] == "ACTIVE" for z in zones):
        return "CONTAINED"

    # 6. ASSESSMENT default
    return "ASSESSMENT"


def recompute_posture(project):
    new_posture = compute_posture(project)
    if new_posture != project.get("posture"):
        project["posture"] = new_posture
        touch(project)


# ===========================================================================
# Insurance estimate & settlement (§1.3 claim_estimate / claim_settlement)
# ===========================================================================
def order_manifests(order_id):
    return [m for m in db.manifests.values() if m["abatement_order_id"] == order_id]


def compute_estimate(project_id):
    orders = project_orders(project_id)
    scope = [o for o in orders if o["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED")]
    scope_ids = {o["id"] for o in scope}
    labor = 0
    for o in scope:
        labor += round_half_up(o["planned_weight_kg"] * LABOR_CPK)
    disposal = 0
    for m in db.manifests.values():
        if m["abatement_order_id"] in scope_ids and m["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED"):
            disposal += m.get("disposal_fee_cents", 0)
    return labor + disposal


def compute_settlement(project_id, claim):
    orders = project_orders(project_id)
    actual = [o for o in orders if o["status"] == "COMPLETED"]
    actual_ids = {o["id"] for o in actual}
    labor = 0
    for o in actual:
        labor += round_half_up(o["removed_weight_kg"] * LABOR_CPK)
    disposal = 0
    for m in db.manifests.values():
        if m["abatement_order_id"] in actual_ids and m["status"] == "ACCEPTED":
            disposal += m.get("disposal_fee_cents", 0)
    gross = labor + disposal
    after_deductible = max(0, gross - claim["deductible_cents"])
    settled = min(after_deductible, claim["coverage_limit_cents"])
    return settled


def compute_settlement_gross(project_id):
    """Gross (pre-deductible/cap) for the coverage-limit fiscal guard at settle."""
    orders = project_orders(project_id)
    actual = [o for o in orders if o["status"] == "COMPLETED"]
    actual_ids = {o["id"] for o in actual}
    labor = 0
    for o in actual:
        labor += round_half_up(o["removed_weight_kg"] * LABOR_CPK)
    disposal = 0
    for m in db.manifests.values():
        if m["abatement_order_id"] in actual_ids and m["status"] == "ACCEPTED":
            disposal += m.get("disposal_fee_cents", 0)
    return labor + disposal


def project_claim(project_id):
    for c in db.claims.values():
        if c["project_id"] == project_id:
            return c
    return None


def recompute_claim_amounts(project_id, recompute_estimate=True, recompute_settled=True):
    claim = project_claim(project_id)
    if claim is None:
        return
    changed = False
    if recompute_estimate:
        est = compute_estimate(project_id)
        if est != claim.get("estimated_amount_cents"):
            claim["estimated_amount_cents"] = est
            changed = True
    if recompute_settled:
        settled = compute_settlement(project_id, claim)
        if settled != claim.get("settled_amount_cents"):
            claim["settled_amount_cents"] = settled
            changed = True
    if changed:
        touch(claim)
