"""Deterministic calculations (PRD Section 2.3 / Section 3, scaffold calculations)."""

import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import by_creation, clock_date, db, touch

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
BP = Decimal("0.0001")

# ---------------------------------------------------------------- constants

SUITE_CLASS_PREMIUM_PSF = {
    "STANDARD_EXAM": Decimal("0.00"),
    "IMAGING": Decimal("6.50"),
    "PROCEDURE": Decimal("4.25"),
    "INFUSION": Decimal("3.00"),
}

PUBLISHED_FLOOR_FACTOR = Decimal("0.80")
PUBLISHED_CEILING_FACTOR = Decimal("1.15")
APPRAISAL_FLOOR_FACTOR = Decimal("0.90")
APPRAISAL_CEILING_FACTOR = Decimal("1.10")

HOLDOVER_PREMIUM_FACTOR = Decimal("1.50")
FMV_DEVIATION_THRESHOLD_PCT = Decimal("0.1500")

APPRAISAL_VALIDITY_DAYS = 365
RENT_GRACE_DAYS = 10
DELINQUENCY_TIER_1_DAYS = 30
DELINQUENCY_TIER_2_DAYS = 60
DELINQUENCY_TIER_1_WEIGHT = 15
DELINQUENCY_TIER_2_WEIGHT = 30
DELINQUENCY_TIER_3_WEIGHT = 50
WRITE_OFF_WEIGHT = 40
RISK_SCORE_WATCH_THRESHOLD = 45
ROLLING_WINDOW_DAYS = 365
RISK_SCORE_CAP = 100

REMEDIATION_WINDOW_DAYS = 30
MIN_TERM_MONTHS = 12

PARKING_MONTHLY_FEE_PSF = {
    "STAFF": Decimal("50.00"),
    "PATIENT": Decimal("0.00"),
}

PARKING_WAIVER_TIERS = (
    (Decimal("5000.00"), Decimal("0.00")),
    (Decimal("12000.00"), Decimal("0.25")),
)
PARKING_WAIVER_TOP_TIER = Decimal("0.50")

TURNOVER_BUFFER_DAYS = {
    "STANDARD_EXAM": 0,
    "IMAGING": 30,
    "PROCEDURE": 14,
    "INFUSION": 14,
}

MIX_COUNTED_LEASE_STATUSES = ("EXECUTED", "ACTIVE", "HOLDOVER")
MIX_COUNTED_LEASE_TYPES = ("DIRECT", "MASTER")
ANCHOR_AFFILIATIONS = ("HEALTH_SYSTEM_ANCHOR", "HEALTH_SYSTEM_AFFILIATED")
RESTRICTED_THRESHOLD = Decimal("0.7500")
CONCENTRATED_THRESHOLD = Decimal("0.6000")

OCCUPYING_LEASE_STATUSES = ("EXECUTED", "ACTIVE", "HOLDOVER")
TERM_CONFLICT_STATUSES = ("FMV_CERTIFIED", "EXECUTED", "ACTIVE", "HOLDOVER")
ACTIVE_CASE_STATUSES = ("OPEN", "REMEDIATION_PLANNED", "REPORTED")
CLOSED_LEASE_STATUSES = ("TERMINATED", "WITHDRAWN")


def q2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(BP, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- lookups


def leases_of_tenant(tenant_id):
    return by_creation([l for l in db.leases.values() if l["tenant_id"] == tenant_id])


def leases_of_building(building_id):
    return by_creation([l for l in db.leases.values() if l["building_id"] == building_id])


def appraisals_of_lease(lease_id):
    return by_creation([a for a in db.appraisals.values() if a["lease_id"] == lease_id])


def invoices_of_lease(lease_id):
    return by_creation([i for i in db.rent_invoices.values() if i["lease_id"] == lease_id])


def cases_of_tenant(tenant_id):
    return by_creation([c for c in db.compliance_cases.values() if c["tenant_id"] == tenant_id])


def line_items_of_project(project_id):
    rows = [r for r in db.ti_line_items.values() if r["ti_project_id"] == project_id]
    return sorted(rows, key=lambda r: r["sequence_no"])


def projects_of_lease(lease_id):
    return by_creation([p for p in db.ti_projects.values() if p["lease_id"] == lease_id])


def bookings_of_lease(lease_id):
    return by_creation([b for b in db.bookings.values() if b["lease_id"] == lease_id])


def bookings_of_space(space_id):
    return by_creation([b for b in db.bookings.values() if b["shared_space_id"] == space_id])


def allocations_of_lease(lease_id):
    return by_creation(
        [a for a in db.parking_allocations.values() if a["lease_id"] == lease_id]
    )


def allocations_of_building(building_id):
    return by_creation(
        [a for a in db.parking_allocations.values() if a["building_id"] == building_id]
    )


# ---------------------------------------------------------------- term length


def term_months(term_start, term_end):
    """Whole calendar months spanned by an inclusive [term_start, term_end]."""
    end_exclusive = term_end + timedelta(days=1)
    months = (end_exclusive.year - term_start.year) * 12 + (
        end_exclusive.month - term_start.month
    )
    if end_exclusive.day < term_start.day:
        months -= 1
    return months


# ---------------------------------------------------------------- FMV band


def published_psf(building, suite):
    return building["market_base_rent_psf_annual"] + SUITE_CLASS_PREMIUM_PSF[
        suite["suite_class"]
    ]


def published_band(psf):
    return q2(psf * PUBLISHED_FLOOR_FACTOR), q2(psf * PUBLISHED_CEILING_FACTOR)


def controlling_appraisal(lease_id):
    """QUALIFIED, still valid at the clock date; newest appraisal_date wins,
    created_at descending breaks a tie."""
    today = clock_date()
    candidates = [
        a
        for a in db.appraisals.values()
        if a["lease_id"] == lease_id
        and a["status"] == "QUALIFIED"
        and a["expires_on"] >= today
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["appraisal_date"], a["_seq"]), reverse=True)
    return candidates[0]


def fmv_band(lease, tenant, building, suite):
    """Returns (floor_psf, ceiling_psf, controlling)."""
    psf = published_psf(building, suite)
    pub_floor, pub_ceiling = published_band(psf)
    if not tenant["is_physician_owned"]:
        return pub_floor, pub_ceiling, None
    controlling = controlling_appraisal(lease["id"])
    if controlling is None:
        return None, None, None
    midpoint = controlling["opinion_midpoint_psf"]
    appraisal_floor = q2(midpoint * APPRAISAL_FLOOR_FACTOR)
    appraisal_ceiling = q2(midpoint * APPRAISAL_CEILING_FACTOR)
    return max(appraisal_floor, pub_floor), min(appraisal_ceiling, pub_ceiling), controlling


# ---------------------------------------------------------------- rent


def recompute_provisional_rent(lease):
    suite = db.suites[lease["suite_id"]]
    building = db.buildings[lease["building_id"]]
    lease["provisional_base_rent_annual"] = q2(
        published_psf(building, suite) * suite["rentable_sf"]
    )


def apply_rent_variant(lease):
    """Selects the rent variant from fmv_certification_status and rolls the
    holdover premium into effective_base_rent_annual."""
    suite = db.suites[lease["suite_id"]]
    if lease["fmv_certification_status"] == "CERTIFIED":
        certified = q2(lease["base_rent_psf_annual"] * suite["rentable_sf"])
        lease["certified_base_rent_annual"] = certified
        if lease["status"] == "HOLDOVER":
            lease["effective_base_rent_annual"] = q2(certified * HOLDOVER_PREMIUM_FACTOR)
        else:
            lease["effective_base_rent_annual"] = certified
        provisional = lease["provisional_base_rent_annual"]
        variance = q2(certified - provisional)
        lease["fmv_variance_annual"] = variance
        lease["fmv_variance_pct"] = q4(variance / provisional) if provisional else Decimal("0.0000")
    else:
        # Only the certified variant applies the holdover multiplier: a lease
        # rolling into HOLDOVER while STALE is carried at the plain published
        # figure with no premium at all (PRD Section 3.4). The provisional
        # figure itself is frozen at review submission and is never re-derived
        # here — callers that must re-derive it say so explicitly.
        lease["effective_base_rent_annual"] = lease["provisional_base_rent_annual"]
        lease["certified_base_rent_annual"] = None
        lease["fmv_variance_annual"] = None
        lease["fmv_variance_pct"] = None


# ---------------------------------------------------------------- tenant mix


def recompute_building_mix(building):
    anchor = 0
    independent = 0
    for lease in leases_of_building(building["id"]):
        if lease["status"] not in MIX_COUNTED_LEASE_STATUSES:
            continue
        if lease["lease_type"] not in MIX_COUNTED_LEASE_TYPES:
            continue
        suite = db.suites.get(lease["suite_id"])
        tenant = db.tenants.get(lease["tenant_id"])
        if suite is None or tenant is None:
            continue
        if tenant["affiliation"] in ANCHOR_AFFILIATIONS:
            anchor += suite["rentable_sf"]
        else:
            independent += suite["rentable_sf"]
    leased = anchor + independent
    building["anchor_rentable_sf"] = anchor
    building["independent_rentable_sf"] = independent
    building["leased_rentable_sf"] = leased
    building["vacant_rentable_sf"] = building["total_rentable_sf"] - leased
    share = q4(Decimal(anchor) / Decimal(leased)) if leased else Decimal("0.0000")
    building["anchor_share_pct"] = share
    if building["mix_freeze_override"]:
        building["tenant_mix_posture"] = "FROZEN"
    elif share > RESTRICTED_THRESHOLD:
        building["tenant_mix_posture"] = "RESTRICTED"
    elif share > CONCENTRATED_THRESHOLD:
        building["tenant_mix_posture"] = "ANCHOR_CONCENTRATED"
    else:
        building["tenant_mix_posture"] = "BALANCED"
    return building["tenant_mix_posture"]


# ---------------------------------------------------------------- parking


def recompute_parking_pool(building):
    staff = 0
    patient = 0
    for alloc in allocations_of_building(building["id"]):
        if alloc["status"] != "ACTIVE":
            continue
        if alloc["category"] == "STAFF":
            staff += alloc["stall_count"]
        else:
            patient += alloc["stall_count"]
    building["staff_allocated_stalls"] = staff
    building["patient_allocated_stalls"] = patient
    building["unallocated_stalls"] = building["total_parking_stalls"] - staff - patient


def patient_reserve_minimum(building):
    exact = Decimal(building["total_parking_stalls"]) * building["patient_min_reserve_pct"]
    return int(math.ceil(exact))


# ---------------------------------------------------------------- risk score


def delinquency_weights(tenant_id):
    weights = []
    for lease in leases_of_tenant(tenant_id):
        for invoice in invoices_of_lease(lease["id"]):
            weight = invoice.get("delinquency_tier_weight") or 0
            if weight > 0:
                weights.append((invoice["due_date"], weight))
    return weights


def risk_scores(tenant_id):
    weights = delinquency_weights(tenant_id)
    window_start = clock_date() - timedelta(days=ROLLING_WINDOW_DAYS)
    rolling = sum(w for due, w in weights if due >= window_start)
    strict = sum(w for _, w in weights)
    return min(rolling, RISK_SCORE_CAP), strict


def watch_status_for(tenant_id, rolling):
    if rolling >= RISK_SCORE_WATCH_THRESHOLD:
        return "WATCH"
    for case in cases_of_tenant(tenant_id):
        if case["status"] in ACTIVE_CASE_STATUSES:
            return "WATCH"
    return "CLEAR"


SEVERITY_HIGH_THRESHOLD = 90
SEVERITY_MEDIUM_THRESHOLD = 45


def severity_for(score):
    """>= 90 HIGH, >= 45 MEDIUM, else LOW (PRD Section 3.8)."""
    if score >= SEVERITY_HIGH_THRESHOLD:
        return "HIGH"
    if score >= SEVERITY_MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def recompute_tenant_risk(tenant, force_bump=False, force_watch=None):
    rolling, strict = risk_scores(tenant["id"])
    watch = force_watch or watch_status_for(tenant["id"], rolling)
    changed = (
        tenant["referral_compliance_risk_score"] != rolling
        or tenant["strict_cumulative_risk_score"] != strict
        or tenant["compliance_watch_status"] != watch
    )
    tenant["referral_compliance_risk_score"] = rolling
    tenant["strict_cumulative_risk_score"] = strict
    tenant["compliance_watch_status"] = watch
    if changed or force_bump:
        touch(tenant)
    return rolling


# ---------------------------------------------------------------- TI cost share


def line_effective_share(project, category, override):
    if category == "SHIELDING" and project["target_suite_class"] == "IMAGING":
        return Decimal("1.0000")
    if override is not None:
        return override
    return project["landlord_share_pct"]


def split_line(cost_amount, share):
    landlord = q2(cost_amount * share)
    return landlord, q2(cost_amount - landlord)


def recompute_ti_totals(project):
    landlord_total = ZERO
    tenant_total = ZERO
    count = 0
    for line in line_items_of_project(project["id"]):
        landlord_total += line["landlord_share_amount"]
        tenant_total += line["tenant_share_amount"]
        count += 1
    project["landlord_committed_amount"] = q2(landlord_total)
    project["tenant_committed_amount"] = q2(tenant_total)
    project["allowance_remaining"] = q2(
        project["authorized_allowance_total"] - project["landlord_committed_amount"]
    )
    project["line_item_count"] = count


# ---------------------------------------------------------------- invoicing


def parking_fee_gross(lease_id):
    gross = ZERO
    for alloc in allocations_of_lease(lease_id):
        if alloc["status"] != "ACTIVE":
            continue
        gross += q2(Decimal(alloc["stall_count"]) * PARKING_MONTHLY_FEE_PSF[alloc["category"]])
    return q2(gross)


def parking_waiver_pct(pre_waiver_total):
    for upper, pct in PARKING_WAIVER_TIERS:
        if pre_waiver_total <= upper:
            return pct
    return PARKING_WAIVER_TOP_TIER


def build_invoice_charges(lease):
    building = db.buildings[lease["building_id"]]
    suite = db.suites[lease["suite_id"]]
    base = q2(lease["effective_base_rent_annual"] / Decimal(12))
    cam = q2(
        building["operating_expense_annual_psf"] * Decimal(suite["rentable_sf"]) / Decimal(12)
    )
    gross = parking_fee_gross(lease["id"])
    pre_waiver = q2(base + cam + gross)
    pct = parking_waiver_pct(pre_waiver)
    waiver = q2(gross * pct)
    total = q2(pre_waiver - waiver)
    return {
        "base_rent_amount": base,
        "cam_amount": cam,
        "parking_fee_gross": gross,
        "pre_waiver_total": pre_waiver,
        "parking_waiver_pct": pct,
        "parking_waiver_amount": waiver,
        "total_amount": total,
    }


def live_days_past_due(invoice):
    delta = (clock_date() - invoice["due_date"]).days
    return delta


def delinquency_tier_weight(days_past_due):
    if days_past_due <= DELINQUENCY_TIER_1_DAYS:
        return DELINQUENCY_TIER_1_WEIGHT
    if days_past_due <= DELINQUENCY_TIER_2_DAYS:
        return DELINQUENCY_TIER_2_WEIGHT
    return DELINQUENCY_TIER_3_WEIGHT


def outstanding_balance(invoice):
    return q2(invoice["total_amount"] - invoice["amount_paid"])


def lease_has_outstanding_rent(lease_id):
    for invoice in invoices_of_lease(lease_id):
        if invoice["status"] in ("ISSUED", "DELINQUENT"):
            return True
    return False


# ---------------------------------------------------------------- shared space


def is_after_hours(window_start, window_end, opens_at, closes_at):
    """True when any instant of [window_start, window_end) falls outside the
    space's daily operating window."""
    from datetime import datetime, timezone

    cursor = window_start
    while cursor < window_end:
        day = cursor.date()
        open_dt = datetime.combine(day, opens_at, tzinfo=timezone.utc)
        close_dt = datetime.combine(day, closes_at, tzinfo=timezone.utc)
        if cursor < open_dt or cursor >= close_dt:
            return True
        cursor = close_dt
    return False


def peak_overlap_load(space_id, window_start, window_end, occupant_count, exclude_id=None):
    """Boundary sweep over the candidate window; strict overlap on both sides."""
    existing = [
        b
        for b in bookings_of_space(space_id)
        if b["status"] == "BOOKED" and b["id"] != exclude_id
    ]
    overlapping = [
        b
        for b in existing
        if b["window_start"] < window_end and window_start < b["window_end"]
    ]
    points = {window_start}
    for booking in overlapping:
        for boundary in (booking["window_start"], booking["window_end"]):
            if window_start <= boundary < window_end:
                points.add(boundary)
    peak = occupant_count
    for point in sorted(points):
        load = occupant_count + sum(
            b["occupant_count"]
            for b in overlapping
            if b["window_start"] <= point < b["window_end"]
        )
        peak = max(peak, load)
    return peak


# ---------------------------------------------------------------- suite terms


def find_suite_term_conflict(candidate):
    suite = db.suites[candidate["suite_id"]]
    buffer_days = TURNOVER_BUFFER_DAYS[suite["suite_class"]]
    for incumbent in by_creation(list(db.leases.values())):
        if incumbent["id"] == candidate["id"]:
            continue
        if incumbent["suite_id"] != candidate["suite_id"]:
            continue
        if incumbent["status"] not in TERM_CONFLICT_STATUSES:
            continue
        if candidate.get("master_lease_id") == incumbent["id"]:
            continue
        low = incumbent["term_start"] - timedelta(days=buffer_days)
        high = incumbent["term_end"] + timedelta(days=buffer_days)
        if candidate["term_start"] <= high and low <= candidate["term_end"]:
            return incumbent
    return None


def suite_occupied_by_other(suite_id, lease_id):
    for lease in by_creation(list(db.leases.values())):
        if lease["id"] == lease_id:
            continue
        if lease["suite_id"] != suite_id:
            continue
        if lease["status"] in OCCUPYING_LEASE_STATUSES:
            return lease
    return None
