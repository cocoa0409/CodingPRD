"""All derived quantities and cascades (PRD 2.7 - 2.9, 3.x)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from store import TABLES, as_date, touch, where

# ---- constants (PRD / SCAFFOLD 1.4) --------------------------------------
CONSTRAINED_DEMAND_RATIO = Decimal("0.8")

LEVEL_RATIO = {"TRAINEE": 0, "ASSISTANT": 4, "LEAD": 8}
CERT_CAP = {"NONE": 0, "BASIC_FIRST_AID": 4, "WFR": 8, "WEMT": 12}
EXPERIENCE_BONUS_MAX = 2
EXPERIENCE_SEASONS_PER_POINT = 3

TIER_1_CEILING_CENTS = 2500000
TIER_2_CEILING_CENTS = 10000000
RATE_TIER_1_BP = 300
RATE_TIER_2_BP = 400
RATE_TIER_3_BP = 500
MINIMUM_ANNUAL_FEE_CENTS = 30000
DEDUCTION_CAP_PCT = Decimal("0.15")

BOND_CENTS_PER_SERVICE_DAY = 5000
BOND_FLOOR_CENTS = 250000
BOND_CEILING_CENTS = 5000000

WEIGHT_EXPERIENCE = Decimal("0.30")
WEIGHT_GUIDE = Decimal("0.30")
WEIGHT_ASSURANCE = Decimal("0.20")
WEIGHT_NEED_MATCH = Decimal("0.20")
EXPERIENCE_PTS_PER_PRIOR_PERMIT = 25

WEIGHT_RESOURCE_PROTECTION = Decimal("0.35")
WEIGHT_CLIENT_SAFETY = Decimal("0.25")
WEIGHT_REPORTING_TIMELINESS = Decimal("0.20")
WEIGHT_FEE_COMPLIANCE = Decimal("0.20")
PENALTY_CAP = Decimal("30.0")
BAND_SUPERIOR_MIN = Decimal("90.0")
BAND_SATISFACTORY_MIN = Decimal("75.0")
BAND_MARGINAL_MIN = Decimal("60.0")
PENALTY_MULTIPLIER = {
    "SUPERIOR": Decimal("0.5"),
    "SATISFACTORY": Decimal("1.0"),
    "MARGINAL": Decimal("1.5"),
    "UNSATISFACTORY": Decimal("2.0"),
}

POINTS_BY_SEVERITY = {"MINOR": 2, "MODERATE": 5, "MAJOR": 10}
NONCOMPLIANT_POINT_THRESHOLD = 12
PROBATION_POINT_THRESHOLD = 5
ROLLING_WINDOW_DAYS = 1095
BASE_SUSPENSION_DAYS = 30

MAX_AUTHORIZED_GUIDES_PER_PERMIT = 8
MAX_REVISION_ROUNDS = 2
PERMIT_TERM_BUFFER_DAYS = 14
SECTION_WEIGHT = Decimal("25.0")

HOLDING_APPLICATION_STATUSES = (
    "CAPACITY_SCREENED",
    "DIRECT_AWARD_PENDING",
    "PROSPECTUS_QUEUED",
    "PROSPECTUS_RESPONDED",
    "AWARDED",
)
COMMITTING_PERMIT_STATUSES = ("ISSUED", "ACTIVE", "SUSPENDED")

PLAN_REQUIRED_KEYS = {
    "sanitation_section": ["human_waste_method", "greywater_method", "packout_commitment"],
    "campsite_section": ["designated_sites_only", "max_nights_per_site", "fire_policy"],
    "stock_section": ["stock_type", "max_head", "feed_source", "tie_method"],
    "resource_protection_section": [
        "weed_free_certification",
        "sensitive_site_avoidance",
        "monitoring_commitment",
    ],
}
PLAN_SECTION_NAMES = list(PLAN_REQUIRED_KEYS.keys())


# ---- rounding ------------------------------------------------------------
def rh(value, places):
    """round_half_up to `places` decimal places, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def rh_cents(value):
    """round_half_up to a whole cent, returning an int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(dec):
    """JSON-friendly number for a Decimal score."""
    if dec is None:
        return None
    return float(dec)


# ---- use-area service-day ledger (PRD 2.7) ------------------------------
def area_ledger(area):
    allocatable = area["total_allocated_service_days"] - area["reserved_admin_service_days"]
    committed = 0
    for p in TABLES["permits"].values():
        if p["use_area_id"] == area["id"] and p["administrative_status"] in COMMITTING_PERMIT_STATUSES:
            committed += p["authorized_service_days"]
    pending = 0
    for a in TABLES["applications"].values():
        if a["use_area_id"] == area["id"] and a["status"] in HOLDING_APPLICATION_STATUSES:
            pending += a["requested_service_days"]
    available = allocatable - committed - pending
    if allocatable > 0:
        ratio = rh(Decimal(committed + pending) / Decimal(allocatable), 4)
    else:
        ratio = rh(Decimal(0), 4)
    if available <= 0:
        posture = "EXHAUSTED"
    elif ratio >= CONSTRAINED_DEMAND_RATIO:
        posture = "CONSTRAINED"
    else:
        posture = "OPEN"
    return {
        "allocatable_service_days": allocatable,
        "committed_service_days": committed,
        "pending_service_days": pending,
        "available_service_days": available,
        "demand_ratio": ratio,
        "allocation_posture": posture,
    }


def recompute_area(area, bump=True):
    led = area_ledger(area)
    area["allocatable_service_days"] = led["allocatable_service_days"]
    area["committed_service_days"] = led["committed_service_days"]
    area["pending_service_days"] = led["pending_service_days"]
    area["available_service_days"] = led["available_service_days"]
    area["demand_ratio"] = led["demand_ratio"]
    area["allocation_posture"] = led["allocation_posture"]
    if bump:
        touch(area)
    return led


# ---- needs assessment (PRD 3.1) -----------------------------------------
def assessment_prospectus_required(finding, unallocated):
    return finding == "NO_NEED" or unallocated <= 0


def recompute_assessment_fields(assessment, allocated):
    determined = assessment["determined_capacity_service_days"]
    assessment["allocated_service_days"] = allocated
    assessment["unallocated_service_days"] = max(0, determined - allocated)
    assessment["prospectus_required"] = assessment_prospectus_required(
        assessment["public_need_finding"], assessment["unallocated_service_days"]
    )


def published_assessment(use_area_id, year):
    for a in TABLES["needs_assessments"].values():
        if (
            a["use_area_id"] == use_area_id
            and a["assessment_year"] == year
            and a["status"] == "PUBLISHED"
        ):
            return a
    return None


def recompute_governing_assessment(use_area_id, year):
    """Only the single PUBLISHED assessment is ever recomputed (PRD 3.1)."""
    assessment = published_assessment(use_area_id, year)
    if assessment is None:
        return None
    area = store.get("use_areas", use_area_id)
    led = area_ledger(area)
    recompute_assessment_fields(
        assessment, led["committed_service_days"] + led["pending_service_days"]
    )
    touch(assessment)
    return assessment


def season_year_of_permit(permit):
    app = store.get("applications", permit.get("application_id"))
    if app is not None:
        return app.get("season_year")
    return None


# ---- guide capacity (PRD 3.1) -------------------------------------------
def guide_capacity(guide):
    level = guide["qualification_level"]
    cert = guide["first_aid_cert_type"]
    if level == "TRAINEE" or cert == "NONE":
        return 0
    bonus = min(
        EXPERIENCE_BONUS_MAX,
        guide.get("seasons_experience", 0) // EXPERIENCE_SEASONS_PER_POINT,
    )
    return max(0, min(LEVEL_RATIO[level], CERT_CAP[cert]) + bonus)


def recompute_guide_capacity(guide):
    guide["base_client_capacity"] = guide_capacity(guide)


def recompute_permit_capacity_total(permit):
    total = 0
    for row in TABLES["authorizations"].values():
        if row["permit_id"] == permit["id"] and row["status"] == "AUTHORIZED":
            total += row["authorized_client_capacity"]
    permit["authorized_client_capacity_total"] = total
    return total


# ---- financial assurance (PRD 3.6) --------------------------------------
def required_assurance(permit):
    raw = permit["authorized_service_days"] * BOND_CENTS_PER_SERVICE_DAY
    return min(BOND_CEILING_CENTS, max(BOND_FLOOR_CENTS, raw))


def bond_is_current(permit):
    need = required_assurance(permit)
    for b in TABLES["bonds"].values():
        if (
            b["permit_id"] == permit["id"]
            and b["status"] == "ACTIVE"
            and b["bond_amount_cents"] >= need
        ):
            return True
    return False


def active_gl_certs(permit):
    return [
        c
        for c in TABLES["insurance_certificates"].values()
        if c["permit_id"] == permit["id"]
        and c["status"] == "ACTIVE"
        and c["coverage_type"] == "GENERAL_LIABILITY"
    ]


def gl_coverage_sufficient(permit, area):
    certs = active_gl_certs(permit)
    if not certs:
        return False
    total = 0
    for c in certs:
        if not c["additional_insured_endorsed"]:
            return False
        total += c["coverage_amount_cents"]
    return total >= area["min_liability_coverage_cents"]


def insurance_is_current(permit, area):
    """PRD 3.4/3.6: an ACTIVE endorsed GL certificate reaching the area minimum."""
    for c in active_gl_certs(permit):
        if c["additional_insured_endorsed"] and c["coverage_amount_cents"] >= area[
            "min_liability_coverage_cents"
        ]:
            return True
    return False


def coverage_has_gap(permit):
    """True when the ACTIVE GL set leaves an uncovered day inside the term."""
    certs = active_gl_certs(permit)
    if not certs:
        return False  # empty set is a sufficiency failure, not a gap
    start = as_date(permit["term_start_date"])
    end = as_date(permit["term_end_date"])
    spans = sorted(
        (as_date(c["effective_date"]), as_date(c["expiration_date"])) for c in certs
    )
    one_day = timedelta(days=1)
    cursor = start
    for eff, exp in spans:
        if eff > cursor:
            return True
        if exp + one_day > cursor:
            cursor = exp + one_day
        if cursor > end:
            return False
    return cursor <= end


# ---- fee assessment (PRD 3.7) -------------------------------------------
def bracket_rate_bp(x):
    if x <= TIER_1_CEILING_CENTS:
        return RATE_TIER_1_BP
    if x <= TIER_2_CEILING_CENTS:
        return RATE_TIER_2_BP
    return RATE_TIER_3_BP


def deduction_cap(gross_revenue_cents):
    return int((Decimal(gross_revenue_cents) * DEDUCTION_CAP_PCT).to_integral_value(
        rounding="ROUND_FLOOR"
    ))


def ordered_accepted_reports(permit_id, season_year):
    rows = [
        r
        for r in TABLES["use_reports"].values()
        if r["permit_id"] == permit_id
        and r["status"] == "ACCEPTED"
        and r["season_year"] == season_year
    ]
    return sorted(
        rows, key=lambda r: (as_date(r["period_start_date"]), r["_created_dt"], r["_seq"])
    )


def compute_assessment(assessment, permit, variant, write_report_fields=True):
    """Recompute one FeeAssessment under the named variant (full recompute)."""
    ordered = ordered_accepted_reports(permit["id"], assessment["season_year"])
    flat = permit["fee_schedule_code"] == "FLAT_THREE_PERCENT"
    total_agr = sum(r["adjusted_gross_revenue_cents"] for r in ordered)

    if variant == "PROVISIONAL_PER_REPORT":
        cum = 0
        rate_fee = 0
        for r in ordered:
            rate = RATE_TIER_1_BP if flat else bracket_rate_bp(cum)
            component = rh_cents(Decimal(r["adjusted_gross_revenue_cents"]) * rate / 10000)
            if write_report_fields:
                r["applied_rate_bp"] = rate
                r["fee_component_cents"] = component
            cum += r["adjusted_gross_revenue_cents"]
            rate_fee += component
    else:
        if flat:
            rate_fee = rh_cents(Decimal(total_agr) * RATE_TIER_1_BP / 10000)
        else:
            b1 = min(total_agr, TIER_1_CEILING_CENTS)
            b2 = max(0, min(total_agr, TIER_2_CEILING_CENTS) - TIER_1_CEILING_CENTS)
            b3 = max(0, total_agr - TIER_2_CEILING_CENTS)
            rate_fee = rh_cents(
                Decimal(
                    b1 * RATE_TIER_1_BP + b2 * RATE_TIER_2_BP + b3 * RATE_TIER_3_BP
                )
                / 10000
            )

    paid = assessment.get("paid_to_date_cents", 0)
    assessment["variant_applied"] = variant
    assessment["minimum_fee_applied"] = rate_fee < MINIMUM_ANNUAL_FEE_CENTS
    assessment["assessed_fee_cents"] = max(MINIMUM_ANNUAL_FEE_CENTS, rate_fee)
    assessment["reported_agr_cents"] = total_agr
    assessment["balance_due_cents"] = max(0, assessment["assessed_fee_cents"] - paid)
    assessment["credit_balance_cents"] = max(0, paid - assessment["assessed_fee_cents"])
    return assessment


def recompute_service_days_ytd(permit):
    total = 0
    for r in TABLES["use_reports"].values():
        if r["permit_id"] == permit["id"] and r["status"] == "ACCEPTED":
            total += r["service_days_used"]
    permit["service_days_used_ytd"] = total
    return total


def permit_fee_delinquent(permit):
    for a in TABLES["fee_assessments"].values():
        if (
            a["permit_id"] == permit["id"]
            and a["status"] in ("PROVISIONAL", "FINAL")
            and a["balance_due_cents"] > 0
        ):
            return True
    return False


def permit_has_outstanding_balance(permit_id):
    for a in TABLES["fee_assessments"].values():
        if a["permit_id"] == permit_id and a["balance_due_cents"] > 0:
            return True
    return False


# ---- prospectus scoring (PRD 3.3) ---------------------------------------
def prospectus_score(app, prospectus, variant):
    outfitter = store.get("outfitters", app["outfitter_id"])
    prior = outfitter["prior_permit_count"] if outfitter else 0
    experience_pts = Decimal(min(100, prior * EXPERIENCE_PTS_PER_PRIOR_PERMIT))

    roster = [
        g
        for g in TABLES["guides"].values()
        if g["outfitter_id"] == app["outfitter_id"]
        and g["status"] in ("QUALIFIED", "PENDING_QUALIFICATION", "LAPSED")
    ]
    guide_total = len(roster)
    if variant == "PRELIMINARY":
        numerator = sum(
            1 for g in roster if g["status"] in ("QUALIFIED", "PENDING_QUALIFICATION")
        )
    else:
        numerator = sum(1 for g in roster if g["status"] == "QUALIFIED")
    if guide_total == 0:
        guide_pts = Decimal("0.00")
    else:
        guide_pts = rh(Decimal(100 * numerator) / Decimal(guide_total), 2)

    if variant == "PRELIMINARY":
        assurance_pts = Decimal("100.0")
    else:
        assurance_pts = (
            Decimal("100.0")
            if outfitter and outfitter["prequalification_insurance_verified"]
            else Decimal("0.0")
        )

    offered = prospectus["offered_service_days"]
    diff = abs(app["requested_service_days"] - offered)
    pct = rh(Decimal(diff * 100) / Decimal(offered), 2)
    need_match_pts = Decimal("100.0") - min(Decimal("100.0"), pct)

    return rh(
        WEIGHT_EXPERIENCE * experience_pts
        + WEIGHT_GUIDE * guide_pts
        + WEIGHT_ASSURANCE * assurance_pts
        + WEIGHT_NEED_MATCH * need_match_pts,
        2,
    )


# ---- performance evaluation (PRD 3.8) -----------------------------------
def band(score):
    if score >= BAND_SUPERIOR_MIN:
        return "SUPERIOR"
    if score >= BAND_SATISFACTORY_MIN:
        return "SATISFACTORY"
    if score >= BAND_MARGINAL_MIN:
        return "MARGINAL"
    return "UNSATISFACTORY"


def performance_weighted_rating(rp, cs, rt, fc, open_points):
    raw = rh(
        WEIGHT_RESOURCE_PROTECTION * rp
        + WEIGHT_CLIENT_SAFETY * cs
        + WEIGHT_REPORTING_TIMELINESS * rt
        + WEIGHT_FEE_COMPLIANCE * fc,
        2,
    )
    provisional = band(raw)
    multiplier = PENALTY_MULTIPLIER[provisional]
    penalty = rh(min(PENALTY_CAP, Decimal(open_points) * multiplier), 2)
    weighted = rh(max(Decimal("0.0"), raw - penalty), 2)
    return raw, provisional, penalty, weighted, band(weighted)


def recompute_latest_performance_rating(permit):
    rows = [
        e for e in TABLES["performance_evaluations"].values() if e["permit_id"] == permit["id"]
    ]
    if not rows:
        permit["latest_performance_rating"] = None
        return None
    rows.sort(key=lambda e: (e["evaluation_year"], e["_created_dt"], e["_seq"]))
    best_year = rows[-1]["evaluation_year"]
    same = [e for e in rows if e["evaluation_year"] == best_year]
    chosen = same[-1]  # tie-break created_at DESC
    permit["latest_performance_rating"] = chosen["rating"]
    return chosen["rating"]


# ---- noncompliance points (PRD 3.8) -------------------------------------
def open_points(permit):
    cutoff = store.now_dt() - timedelta(days=ROLLING_WINDOW_DAYS)
    total = 0
    for a in TABLES["noncompliance_actions"].values():
        if a["permit_id"] != permit["id"]:
            continue
        if a["status"] not in ("ISSUED", "APPEALED", "UPHELD"):
            continue
        if a["_created_dt"] >= cutoff:
            total += a["points"]
    return total


def upheld_major_count(permit):
    return sum(
        1
        for a in TABLES["noncompliance_actions"].values()
        if a["permit_id"] == permit["id"]
        and a["severity"] == "MAJOR"
        and a["status"] == "UPHELD"
    )


def suspension_days_for_threshold(permit):
    return BASE_SUSPENSION_DAYS * (1 + upheld_major_count(permit))


# ---- outfitter status (PRD 3.1) -----------------------------------------
def derive_outfitter(outfitter_id):
    outfitter = store.get("outfitters", outfitter_id)
    if outfitter is None:
        return None
    permits = [p for p in TABLES["permits"].values() if p["outfitter_id"] == outfitter_id]
    active = sum(1 for p in permits if p["administrative_status"] == "ACTIVE")
    suspended = sum(1 for p in permits if p["administrative_status"] == "SUSPENDED")
    held = sum(
        1 for p in permits if p["administrative_status"] in COMMITTING_PERMIT_STATUSES
    )
    outfitter["active_permit_count"] = active
    outfitter["prior_permit_count"] = len(permits)
    if active >= 1:
        outfitter["status"] = "PERMITTED"
    elif suspended >= 1:
        outfitter["status"] = "SUSPENDED"
    elif held >= 1:
        outfitter["status"] = "PERMITTED"
    else:
        outfitter["status"] = "APPLICANT"
    touch(outfitter)
    return outfitter


# ---- operating plan completeness (PRD 3.5) -------------------------------
def plan_completeness(plan):
    score = Decimal("0.0")
    for section, keys in PLAN_REQUIRED_KEYS.items():
        body = plan.get(section)
        if not isinstance(body, dict):
            continue
        if all(key in body and body[key] is not None for key in keys):
            score += SECTION_WEIGHT
    return score


def recompute_plan_completeness(plan):
    plan["completeness_score"] = plan_completeness(plan)
    return plan["completeness_score"]


def approved_plan_for_year(permit_id, year):
    for p in TABLES["operating_plans"].values():
        if (
            p["permit_id"] == permit_id
            and p["plan_year"] == year
            and p["status"] == "APPROVED"
        ):
            return p
    return None


# ---- permit compliance and the cascades it drives (PRD 3.8) --------------
def recompute_permit_signals(permit):
    area = store.get("use_areas", permit["use_area_id"])
    permit["insurance_current"] = insurance_is_current(permit, area) if area else False
    permit["bond_current"] = bond_is_current(permit)
    permit["fee_delinquent"] = permit_fee_delinquent(permit)
    permit["open_noncompliance_points"] = open_points(permit)


def compliance_value(permit):
    pts = permit["open_noncompliance_points"]
    if pts >= NONCOMPLIANT_POINT_THRESHOLD:
        return "NONCOMPLIANT"
    if (
        pts >= PROBATION_POINT_THRESHOLD
        or permit["insurance_current"] is False
        or permit["fee_delinquent"] is True
    ):
        return "PROBATION"
    return "COMPLIANT"


def derive_compliance(permit, counters=None, allow_suspend=True):
    previous = permit["compliance_status"]
    permit["compliance_status"] = compliance_value(permit)
    touch(permit)
    if (
        allow_suspend
        and permit["compliance_status"] == "NONCOMPLIANT"
        and previous != "NONCOMPLIANT"
        and permit["administrative_status"] == "ACTIVE"
    ):
        days = suspension_days_for_threshold(permit)
        until = store.fmt_dt(store.now_dt() + timedelta(days=days))
        suspend_permit(permit, "POINTS_THRESHOLD", until, counters)
        return True
    return False


def revoke_roster(permit, reason_code):
    count = 0
    for row in TABLES["authorizations"].values():
        if row["permit_id"] == permit["id"] and row["status"] == "AUTHORIZED":
            row["status"] = "REVOKED"
            row["revoked_at"] = store.now_str()
            row["revocation_reason_code"] = reason_code
            touch(row)
            count += 1
    recompute_permit_capacity_total(permit)
    return count


def close_settled_assessments(permit):
    for a in TABLES["fee_assessments"].values():
        if (
            a["permit_id"] == permit["id"]
            and a["status"] != "CLOSED"
            and a["balance_due_cents"] == 0
        ):
            a["status"] = "CLOSED"
            touch(a)


def suspend_permit(permit, reason_code, until_value, counters=None):
    permit["administrative_status"] = "SUSPENDED"
    permit["suspension_count"] = permit.get("suspension_count", 0) + 1
    permit["suspended_until_date"] = until_value
    permit["suspension_reason_code"] = reason_code
    touch(permit)
    revoked = revoke_roster(permit, "PERMIT_SUSPENDED")
    derive_outfitter(permit["outfitter_id"])
    if counters is not None:
        counters["permits_suspended"] += 1
        counters["authorizations_revoked"] += revoked
    return revoked


def close_out_permit(permit, new_status, counters=None):
    """Shared tail of revoke / expiry / succession close: release days and paper."""
    permit["administrative_status"] = new_status
    touch(permit)
    revoked = revoke_roster(permit, "PERMIT_CLOSED")
    close_settled_assessments(permit)
    area = store.get("use_areas", permit["use_area_id"])
    if area is not None:
        recompute_area(area)
        recompute_governing_assessment(area["id"], season_year_of_permit(permit))
    derive_outfitter(permit["outfitter_id"])
    if counters is not None:
        counters["authorizations_revoked"] += revoked
    return revoked
