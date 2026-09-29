"""Domain enumerations, derived-field calculations and cascades.

Every rule here is a direct transcription of PRD sections 2.7 - 2.9 and 3.1 - 3.9.
"""

from decimal import Decimal, ROUND_HALF_UP

import clock
import db

# --------------------------------------------------------------- enums ------
CAMP_TYPES = ("RESIDENT", "DAY", "TRAVEL_TRIP", "FAMILY", "SPECIAL_NEEDS")
POPULATIONS = ("YOUTH_ONLY", "ADULT_INCLUSIVE", "MEDICALLY_FRAGILE")
PROGRAM_ELEMENTS = (
    "AQUATICS_POOL",
    "AQUATICS_OPEN_WATER",
    "ADVENTURE_CHALLENGE_COURSE",
    "ADVENTURE_CLIMBING",
    "HORSEBACK",
    "TRANSPORTATION",
    "TRIP_CAMPING",
)
STAFFING_LEVELS = (
    "NONE",
    "FIRST_AIDER_ONLY",
    "LPN_ONSITE",
    "RN_ONSITE",
    "PHYSICIAN_ONSITE",
)
STAFFING_RANK = {
    "NONE": 0,
    "FIRST_AIDER_ONLY": 1,
    "LPN_ONSITE": 2,
    "RN_ONSITE": 3,
    "PHYSICIAN_ONSITE": 4,
}
RANK_STAFFING = {v: k for k, v in STAFFING_RANK.items()}

ACCREDITATION_STATUSES = (
    "NOT_ACCREDITED",
    "ACCREDITED",
    "ACCREDITED_WITH_CORRECTION",
    "PROVISIONAL",
    "REVOKED",
)
LICENSE_STATUSES = ("NONE", "PENDING", "ACTIVE", "PROBATION", "SUSPENDED")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
INTAKE_STATUSES = ("OPEN", "SUSPENDED")
RISK_VARIANTS = ("PRE_VISIT", "POST_VISIT")

SET_STATUSES = ("DRAFT", "PUBLISHED", "RETIRED")
DOMAINS = (
    "SUPERVISION",
    "HEALTH_WELLNESS",
    "EMERGENCY_RESPONSE",
    "AQUATICS",
    "ADVENTURE",
    "TRANSPORTATION",
    "OPERATIONS",
)
PLAN_TYPES = (
    "SUPERVISION",
    "HEALTH_CARE",
    "EMERGENCY_RESPONSE",
    "AQUATICS_SAFETY",
    "TRANSPORTATION_SAFETY",
    "ADVENTURE_OPERATIONS",
)
PLAN_STATUSES = (
    "SUBMITTED",
    "VERIFIED",
    "REJECTED",
    "REVALIDATION_REQUIRED",
    "SUPERSEDED",
)

CYCLE_STATUSES = (
    "SELF_ASSESSMENT",
    "VISIT_SCHEDULED",
    "VISIT_COMPLETED",
    "IN_CORRECTION",
    "CLOSED",
    "TERMINATED",
)
DECISION_LEVELS = ("ACCREDITED", "ACCREDITED_WITH_CORRECTION", "PROVISIONAL", "DENIED")

SELF_SCORES = ("NOT_MET", "PARTIAL", "MET")
SELF_STATUSES = ("DRAFT", "SUBMITTED", "VERIFIED", "REJECTED")
VISITOR_SCORES = ("MET", "NOT_MET", "NOT_APPLICABLE")
SCORE_SOURCES = ("OBSERVED", "DOCUMENT", "INTERVIEW")
VISIT_SCORE_STATUSES = ("UNSCORED", "SCORED", "LOCKED")

CERTIFICATIONS = (
    "LEAD_VISITOR",
    "AQUATICS_SPECIALIST",
    "ADVENTURE_SPECIALIST",
    "HEALTH_SPECIALIST",
)
VISITOR_STATUSES = ("ACTIVE", "INACTIVE")

VISIT_STATUSES = ("DRAFT", "SCHEDULED", "IN_PROGRESS", "SCORED", "RESCINDED")
TEAM_ROLES = (
    "LEAD",
    "MEMBER",
    "SPECIALIST_AQUATICS",
    "SPECIALIST_ADVENTURE",
    "SPECIALIST_HEALTH",
)
ASSIGNMENT_STATUSES = ("ASSIGNED", "WITHDRAWN", "COMPLETED")
SPECIALIST_DOMAINS = ("AQUATICS", "ADVENTURE", "HEALTH_WELLNESS")
SPECIALIST_SEAT_FOR_DOMAIN = {
    "AQUATICS": ("SPECIALIST_AQUATICS", "AQUATICS_SPECIALIST"),
    "ADVENTURE": ("SPECIALIST_ADVENTURE", "ADVENTURE_SPECIALIST"),
    "HEALTH_WELLNESS": ("SPECIALIST_HEALTH", "HEALTH_SPECIALIST"),
}
DOMAIN_CERTIFICATION = {
    "AQUATICS": "AQUATICS_SPECIALIST",
    "ADVENTURE": "ADVENTURE_SPECIALIST",
    "HEALTH_WELLNESS": "HEALTH_SPECIALIST",
}

SEVERITIES = ("MANDATORY_CRITICAL", "MANDATORY", "SCORED")
SEVERITY_POINTS = {"MANDATORY_CRITICAL": 8, "MANDATORY": 5, "SCORED": 2}
CRITICAL_DOMAINS = ("HEALTH_WELLNESS", "EMERGENCY_RESPONSE", "AQUATICS")
DEFICIENCY_STATUSES = (
    "OPEN",
    "PLAN_SUBMITTED",
    "PLAN_ACCEPTED",
    "CORRECTED",
    "WAIVED",
    "ESCALATED",
)
COUNTED_DEFICIENCY_STATUSES = ("OPEN", "PLAN_SUBMITTED", "ESCALATED")
OPEN_DEFICIENCY_STATUSES = ("OPEN", "PLAN_SUBMITTED", "PLAN_ACCEPTED")
PLAN_REVISION_LIMIT = 3

MEDICATION_CLASSES = ("OTC", "PRESCRIPTION", "CONTROLLED")
ADMIN_ROLES = ("RN", "LPN", "FIRST_AIDER", "PHYSICIAN", "UNLICENSED_DESIGNEE")
RECORD_STATUSES = ("RECORDED", "VOIDED")
COMPLIANCE_FLAGS = ("COMPLIANT", "DOCUMENTATION_INCOMPLETE")
CLASS_STAFFING_FLOOR = {"CONTROLLED": 3, "PRESCRIPTION": 2, "OTC": 1}
CLASS_ALLOWED_ROLES = {
    "CONTROLLED": ("RN", "PHYSICIAN"),
    "PRESCRIPTION": ("LPN", "RN", "PHYSICIAN"),
    "OTC": ("FIRST_AIDER", "LPN", "RN", "PHYSICIAN"),
}

REPORT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "LATE",
    "ACCEPTED",
    "REJECTED",
    "REOPENED",
    "ARCHIVED",
)
INCIDENT_TYPES = (
    "SERIOUS_INJURY",
    "HOSPITALIZATION",
    "DEATH",
    "ABUSE_ALLEGATION",
    "MEDICATION_ERROR",
    "AQUATICS_RESCUE",
    "TRANSPORTATION_COLLISION",
    "COMMUNICABLE_DISEASE_OUTBREAK",
)
DISCLOSURE_STATUSES = ("REPORTED", "LATE_DISCLOSED")
INCIDENT_WEIGHT = {
    "DEATH": 25,
    "ABUSE_ALLEGATION": 20,
    "HOSPITALIZATION": 12,
    "SERIOUS_INJURY": 8,
    "COMMUNICABLE_DISEASE_OUTBREAK": 8,
    "TRANSPORTATION_COLLISION": 6,
    "AQUATICS_RESCUE": 5,
    "MEDICATION_ERROR": 4,
}
STATE_NOTIFIABLE_INCIDENTS = (
    "DEATH",
    "ABUSE_ALLEGATION",
    "HOSPITALIZATION",
    "COMMUNICABLE_DISEASE_OUTBREAK",
)
PROGRAM_WEIGHT = {
    "AQUATICS_OPEN_WATER": 8,
    "ADVENTURE_CLIMBING": 7,
    "ADVENTURE_CHALLENGE_COURSE": 6,
    "HORSEBACK": 6,
    "AQUATICS_POOL": 5,
    "TRANSPORTATION": 4,
    "TRIP_CAMPING": 3,
}
LICENSE_PENALTY = {"NONE": 6, "PENDING": 4, "ACTIVE": 0, "PROBATION": 10, "SUSPENDED": 20}
POPULATION_MULTIPLIER = {
    "MEDICALLY_FRAGILE": Decimal("1.4"),
    "ADULT_INCLUSIVE": Decimal("1.1"),
    "YOUTH_ONLY": Decimal("1.0"),
}

LICENSE_TRANSITIONS = {
    ("NONE", "PENDING"),
    ("PENDING", "ACTIVE"),
    ("NONE", "ACTIVE"),
    ("ACTIVE", "PROBATION"),
    ("ACTIVE", "SUSPENDED"),
    ("PROBATION", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("PROBATION", "ACTIVE"),
}

FEE_BASE_CENTS = Decimal("95000")
FEE_PER_STANDARD_CENTS = Decimal("350")
FEE_DOMAIN_SURCHARGE_ORDER = (
    ("AQUATICS", Decimal("18125")),
    ("ADVENTURE", Decimal("22125")),
    ("TRANSPORTATION", Decimal("12125")),
    ("HEALTH_WELLNESS", Decimal("15125")),
    ("SUPERVISION", Decimal("0")),
    ("EMERGENCY_RESPONSE", Decimal("0")),
    ("OPERATIONS", Decimal("0")),
)
FEE_TRAVEL_DAY_RATE = Decimal("24000") * Decimal("0.75")

TWO = Decimal("0.01")


# ------------------------------------------------------------ numerics ------
def d2(value):
    """Round half up to two decimal places, returned as a float."""
    return float(Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP))


def cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct(numerator, denominator):
    if denominator == 0:
        return 100.00
    return d2(Decimal(100) * Decimal(numerator) / Decimal(denominator))


def rank(level):
    return STAFFING_RANK.get(level, 0)


# ---------------------------------------------------------- traversals ------
def camp_cycles(camp_id):
    return db.ordered(db.cycles, lambda c: c["camp_id"] == camp_id)


def cycle_evaluations(cycle_id):
    return db.ordered(db.evaluations, lambda e: e["cycle_id"] == cycle_id)


def cycle_visits(cycle_id):
    return db.ordered(db.visits, lambda v: v["cycle_id"] == cycle_id)


def active_visit(cycle_id):
    """The cycle's single non-rescinded visit, or None."""
    rows = [v for v in cycle_visits(cycle_id) if v["status"] != "RESCINDED"]
    return rows[-1] if rows else None


def standing_visit(cycle_id):
    """A visit still in DRAFT or SCHEDULED for the cycle."""
    for v in cycle_visits(cycle_id):
        if v["status"] in ("DRAFT", "SCHEDULED"):
            return v
    return None


def visit_assignments(visit_id):
    return db.ordered(db.assignments, lambda a: a["visit_id"] == visit_id)


def visit_deficiencies(visit_id):
    return db.ordered(db.deficiencies, lambda x: x["visit_id"] == visit_id)


def visitor_assignments(visitor_id):
    return db.ordered(db.assignments, lambda a: a["visitor_id"] == visitor_id)


def camp_plans(camp_id):
    return db.ordered(db.written_plans, lambda p: p["camp_id"] == camp_id)


def camp_reports(camp_id):
    return db.ordered(db.annual_reports, lambda r: r["camp_id"] == camp_id)


def report_disclosures(report_id):
    return db.ordered(db.disclosures, lambda x: x["annual_report_id"] == report_id)


def camp_of_visit(visit):
    cycle = db.cycles.get(visit["cycle_id"])
    if cycle is None:
        return None
    return db.camps.get(cycle["camp_id"])


def camp_id_of_deficiency(deficiency):
    visit = db.visits.get(deficiency["visit_id"])
    if visit is None:
        return None
    cycle = db.cycles.get(visit["cycle_id"])
    return cycle["camp_id"] if cycle else None


def camp_deficiencies(camp_id):
    return [
        x
        for x in db.ordered(db.deficiencies)
        if camp_id_of_deficiency(x) == camp_id
    ]


def camp_disclosures(camp_id):
    report_ids = set(r["id"] for r in camp_reports(camp_id))
    return [
        x for x in db.ordered(db.disclosures) if x["annual_report_id"] in report_ids
    ]


# ------------------------------------------- required staffing (PRD 3.1) ----
def required_staffing_components(camp):
    camp_type = camp["camp_type"]
    if camp_type == "DAY":
        type_component = 1
    elif camp_type == "RESIDENT":
        type_component = 3
    else:
        type_component = 2

    population = camp["population_served"]
    if population == "MEDICALLY_FRAGILE":
        population_component = 4
    elif population == "ADULT_INCLUSIVE":
        population_component = 2
    else:
        population_component = 1

    census = camp["resident_census"]
    if census <= 50:
        census_component = 1
    elif census <= 120:
        census_component = 2
    else:
        census_component = 3

    distance = camp["distance_to_hospital_km"]
    if distance >= 40:
        distance_component = 3
    elif distance >= 20:
        distance_component = 2
    else:
        distance_component = 1

    elements = camp["program_elements"] or []
    if "AQUATICS_OPEN_WATER" in elements or "ADVENTURE_CLIMBING" in elements:
        program_component = 3
    else:
        program_component = 1

    return [
        type_component,
        population_component,
        census_component,
        distance_component,
        program_component,
    ]


def required_staffing_level(camp):
    components = required_staffing_components(camp)
    result = max(components)
    if len([c for c in components if c >= 2]) >= 3:
        result += 1
    result = min(result, 4)
    return RANK_STAFFING[result]


def recompute_required_staffing(camp):
    level = required_staffing_level(camp)
    if camp.get("required_health_staffing_level") != level:
        camp["required_health_staffing_level"] = level
        db.touch(camp)
    return level


# ----------------------------------------------- conserved quantities -------
def recompute_penalty_balance(camp):
    total = 0
    for deficiency in camp_deficiencies(camp["id"]):
        if deficiency["status"] in COUNTED_DEFICIENCY_STATUSES:
            total += deficiency["penalty_points"]
    if camp.get("penalty_point_balance") != total:
        camp["penalty_point_balance"] = total
        db.touch(camp)
    return total


def recompute_controlled_balance(camp):
    consumed = 0
    for record in db.med_records.values():
        if (
            record["camp_id"] == camp["id"]
            and record["medication_class"] == "CONTROLLED"
            and record["record_status"] == "RECORDED"
        ):
            consumed += record["dose_units"]
    on_hand = camp["controlled_intake_units"] - consumed
    if on_hand < 0:
        on_hand = 0
    if camp.get("controlled_on_hand_units") != on_hand:
        camp["controlled_on_hand_units"] = on_hand
        db.touch(camp)
    return on_hand


def recompute_committed_travel_days(visitor):
    total = 0
    for seat in visitor_assignments(visitor["id"]):
        if seat["status"] in ("ASSIGNED", "COMPLETED"):
            total += seat["travel_days"]
    if visitor.get("committed_travel_days") != total:
        visitor["committed_travel_days"] = total
        db.touch(visitor)
    return total


# -------------------------------------------- posture and cascade (2.7/2.8) -
def compute_posture(camp):
    balance = camp["penalty_point_balance"]
    license_status = camp["state_license_status"]
    deficiencies = camp_deficiencies(camp["id"])
    if (
        balance >= 12
        or license_status == "SUSPENDED"
        or any(x["status"] == "ESCALATED" for x in deficiencies)
    ):
        return "FROZEN"
    if (
        balance >= 5
        or license_status in ("PENDING", "PROBATION")
        or rank(camp["health_staffing_level"]) < rank(camp["required_health_staffing_level"])
    ):
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(camp):
    posture = compute_posture(camp)
    intake = "SUSPENDED" if posture == "FROZEN" else "OPEN"
    changed = (
        camp.get("compliance_posture") != posture
        or camp.get("health_intake_status") != intake
    )
    camp["compliance_posture"] = posture
    camp["health_intake_status"] = intake
    if changed:
        db.touch(camp)
    if posture == "FROZEN":
        run_freeze_cascade(camp)
    return posture


def run_freeze_cascade(camp):
    """Hop 1 happens in recompute_posture; hops 2 and 3 happen here."""
    for plan in camp_plans(camp["id"]):
        if plan["status"] != "VERIFIED":
            continue
        plan["status"] = "REVALIDATION_REQUIRED"
        db.touch(plan)
        for evaluation in db.ordered(
            db.evaluations, lambda e: e["written_plan_id"] == plan["id"]
        ):
            if evaluation["self_status"] == "VERIFIED":
                evaluation["self_status"] = "REJECTED"
                db.touch(evaluation)


# --------------------------------------------- risk index (PRD 2.9) --------
def newest_cycle(camp_id):
    rows = camp_cycles(camp_id)
    if not rows:
        return None
    rows = sorted(rows, key=lambda c: (-c["cycle_year"], c["created_at"], c["_seq"]))
    return rows[0]


def risk_variant(camp_id):
    cycle = newest_cycle(camp_id)
    if cycle is None:
        return "PRE_VISIT"
    if cycle["status"] in ("SELF_ASSESSMENT", "VISIT_SCHEDULED"):
        return "PRE_VISIT"
    return "POST_VISIT"


def risk_breakdown(camp):
    camp_id = camp["id"]
    current_year = clock.today().year

    incident_total = Decimal("0")
    for disclosure in camp_disclosures(camp_id):
        occurred_year = int(disclosure["occurred_at"][0:4])
        if occurred_year < current_year - 2:
            continue
        weight = Decimal(INCIDENT_WEIGHT[disclosure["incident_type"]])
        factor = Decimal("1.5") if disclosure["status"] == "LATE_DISCLOSED" else Decimal("1.0")
        incident_total += (weight * factor).quantize(TWO, rounding=ROUND_HALF_UP)

    program_total = Decimal(
        sum(PROGRAM_WEIGHT.get(e, 0) for e in (camp["program_elements"] or []))
    )

    staffing_penalty = Decimal(
        15
        if rank(camp["health_staffing_level"]) < rank(camp["required_health_staffing_level"])
        else 0
    )
    license_penalty = Decimal(LICENSE_PENALTY[camp["state_license_status"]])

    cycle = newest_cycle(camp_id)
    variant = risk_variant(camp_id)
    if cycle is None:
        compliance = Decimal("0.00")
    else:
        denominator = max(1, cycle["applicable_mandatory_count"])
        if variant == "PRE_VISIT":
            count = 0
            for evaluation in cycle_evaluations(cycle["id"]):
                if not evaluation["applicable"] or not evaluation["mandatory"]:
                    continue
                if evaluation["self_score"] != "MET":
                    count += 1
        else:
            count = 0
            visit = active_visit(cycle["id"])
            if visit is not None:
                for deficiency in visit_deficiencies(visit["id"]):
                    if deficiency["severity"] in ("MANDATORY_CRITICAL", "MANDATORY") and (
                        deficiency["status"] in COUNTED_DEFICIENCY_STATUSES
                    ):
                        count += 1
        compliance = (Decimal(count * 30) / Decimal(denominator)).quantize(
            TWO, rounding=ROUND_HALF_UP
        )

    subtotal = (
        Decimal("10")
        + incident_total
        + program_total
        + staffing_penalty
        + license_penalty
        + compliance
    )
    multiplier = POPULATION_MULTIPLIER[camp["population_served"]]
    product = subtotal * multiplier
    if product > Decimal("100"):
        product = Decimal("100")
    index = product.quantize(TWO, rounding=ROUND_HALF_UP)

    return {
        "camp_id": camp_id,
        "risk_index_variant": variant,
        "incident_component": float(incident_total.quantize(TWO, rounding=ROUND_HALF_UP)),
        "program_component": float(program_total.quantize(TWO, rounding=ROUND_HALF_UP)),
        "staffing_gap_penalty": float(staffing_penalty.quantize(TWO, rounding=ROUND_HALF_UP)),
        "license_penalty": float(license_penalty.quantize(TWO, rounding=ROUND_HALF_UP)),
        "compliance_component": float(compliance),
        "population_multiplier": float(multiplier),
        "risk_index": float(index),
    }


def recompute_risk_index(camp):
    breakdown = risk_breakdown(camp)
    if (
        camp.get("risk_index") != breakdown["risk_index"]
        or camp.get("risk_index_variant") != breakdown["risk_index_variant"]
    ):
        camp["risk_index"] = breakdown["risk_index"]
        camp["risk_index_variant"] = breakdown["risk_index_variant"]
        db.touch(camp)
    return breakdown


def recompute_camp(camp, risk=True):
    """Full derived-field refresh in the canonical order of PRD 3.1."""
    recompute_required_staffing(camp)
    recompute_controlled_balance(camp)
    recompute_penalty_balance(camp)
    recompute_posture(camp)
    if risk:
        recompute_risk_index(camp)
    return camp


# ------------------------------------- applicability (PRD 3.3) -------------
def standard_applies(standard, camp):
    types = standard["applies_to_camp_types"] or []
    if types and camp["camp_type"] not in types:
        return False
    elements = standard["requires_program_elements_any"] or []
    if elements and not set(elements) & set(camp["program_elements"] or []):
        return False
    populations = standard["applies_to_populations"] or []
    if populations and camp["population_served"] not in populations:
        return False
    if standard["requires_state_licensed"] and camp["state_license_status"] not in (
        "ACTIVE",
        "PROBATION",
    ):
        return False
    return True


# ----------------------------------- compliance variants (PRD 3.6 / 3.7) ---
def applicable_mandatory_rows(cycle_id):
    return [
        e
        for e in cycle_evaluations(cycle_id)
        if e["applicable"] and e["mandatory"]
    ]


def provisional_figures(cycle_id):
    denominator = 0
    numerator = 0
    for row in applicable_mandatory_rows(cycle_id):
        if row["score_source"] not in ("OBSERVED", "DOCUMENT"):
            continue
        if row["visitor_score"] is None or row["visitor_score"] == "NOT_APPLICABLE":
            continue
        denominator += 1
        if row["visitor_score"] == "MET":
            numerator += 1
    return denominator, numerator, pct(numerator, denominator)


def final_figures(cycle_id):
    rows = applicable_mandatory_rows(cycle_id)
    denominator = len(rows)
    numerator = len([r for r in rows if r["visitor_score"] == "MET"])
    return denominator, numerator, pct(numerator, denominator)


def weighted_figures(cycle_id):
    total = 0
    met = 0
    for row in cycle_evaluations(cycle_id):
        if not row["applicable"]:
            continue
        total += row["scoring_weight"]
        if row["visitor_score"] == "MET":
            met += row["scoring_weight"]
    return total, met, pct(met, total)


def open_deficiency_count(cycle_id):
    visit = active_visit(cycle_id)
    if visit is None:
        return 0
    return len(
        [
            x
            for x in visit_deficiencies(visit["id"])
            if x["status"] in OPEN_DEFICIENCY_STATUSES
        ]
    )


def decision_level(camp, final_mandatory_pct, final_weighted_pct):
    if camp["state_license_status"] == "SUSPENDED" or final_mandatory_pct < 90.00:
        return "DENIED"
    if final_mandatory_pct < 100.00:
        return "PROVISIONAL"
    if final_weighted_pct < 95.00:
        return "ACCREDITED_WITH_CORRECTION"
    return "ACCREDITED"


# ------------------------------------------------- fee (PRD 3.7) ----------
def discount_fraction(prior_accredited_cycle_count):
    count = prior_accredited_cycle_count
    if count <= 0:
        return Decimal("0")
    if count == 1:
        return Decimal("0.05")
    return Decimal("0.10")


def assess_fee(cycle, camp):
    discount = discount_fraction(camp["prior_accredited_cycle_count"])
    factor = Decimal("1") - discount

    total = cents(FEE_BASE_CENTS)

    applicable_standards = Decimal(cycle["applicable_standard_count"])
    total += cents(FEE_PER_STANDARD_CENTS * applicable_standards * factor)

    domains_present = set()
    for row in cycle_evaluations(cycle["id"]):
        if not row["applicable"]:
            continue
        standard = db.standards.get(row["standard_id"])
        if standard is not None:
            domains_present.add(standard["domain"])
    for domain_name, surcharge in FEE_DOMAIN_SURCHARGE_ORDER:
        if domain_name in domains_present:
            total += cents(surcharge * factor)

    travel_days = 0
    visit = active_visit(cycle["id"])
    if visit is not None:
        for seat in visit_assignments(visit["id"]):
            if seat["status"] in ("ASSIGNED", "COMPLETED"):
                travel_days += seat["travel_days"]
    total += cents(FEE_TRAVEL_DAY_RATE * Decimal(travel_days) * factor)

    return total


# --------------------------------- deficiency batch (PRD 3.6) -------------
def classify_severity(evaluation, standard):
    if evaluation["mandatory"]:
        if standard is not None and standard["domain"] in CRITICAL_DOMAINS:
            return "MANDATORY_CRITICAL"
        return "MANDATORY"
    return "SCORED"


def escalation_tier(base_total):
    if base_total <= 9:
        return 0
    if base_total <= 19:
        return 1
    return 2


TIER_SURCHARGE = {0: 0, 1: 2, 2: 5}
TIER_WINDOW_DAYS = {0: 90, 1: 60, 2: 30}


# --------------------------------- team completeness (PRD 3.5) -----------
def required_specialist_domains(camp):
    elements = camp["program_elements"] or []
    domains = []
    if "AQUATICS_POOL" in elements or "AQUATICS_OPEN_WATER" in elements:
        domains.append("AQUATICS")
    if "ADVENTURE_CHALLENGE_COURSE" in elements or "ADVENTURE_CLIMBING" in elements:
        domains.append("ADVENTURE")
    if camp["required_health_staffing_level"] in ("RN_ONSITE", "PHYSICIAN_ONSITE"):
        domains.append("HEALTH_WELLNESS")
    return domains


def team_complete(visit):
    if visit["lead_visitor_id"] is None:
        return False
    if visit["team_size"] < 2:
        return False
    seats = [a for a in visit_assignments(visit["id"]) if a["status"] == "ASSIGNED"]
    for domain_name in visit["required_specialist_domains"] or []:
        seat_role, certification = SPECIALIST_SEAT_FOR_DOMAIN[domain_name]
        satisfied = False
        for seat in seats:
            if seat["team_role"] != seat_role:
                continue
            visitor = db.visitors.get(seat["visitor_id"])
            if visitor is not None and certification in (visitor["certifications"] or []):
                satisfied = True
                break
        if not satisfied:
            return False
    return True


def withdraw_seat(seat, reason=None):
    """Move an ASSIGNED seat to WITHDRAWN with every ledger consequence."""
    if seat["status"] != "ASSIGNED":
        return
    seat["status"] = "WITHDRAWN"
    if reason is not None:
        seat["withdrawal_reason"] = reason
    db.touch(seat)
    visitor = db.visitors.get(seat["visitor_id"])
    if visitor is not None:
        recompute_committed_travel_days(visitor)
    visit = db.visits.get(seat["visit_id"])
    if visit is not None:
        visit["team_size"] = max(0, visit["team_size"] - 1)
        if visit["lead_visitor_id"] == seat["visitor_id"] and seat["team_role"] == "LEAD":
            visit["lead_visitor_id"] = None
        db.touch(visit)


def rescind_visit(visit):
    """DRAFT/SCHEDULED -> RESCINDED, withdrawing every assigned seat."""
    was_scheduled = visit["status"] == "SCHEDULED"
    visit["status"] = "RESCINDED"
    db.touch(visit)
    for seat in visit_assignments(visit["id"]):
        if seat["status"] == "ASSIGNED":
            withdraw_seat(seat)
    return was_scheduled


def revert_visit_if_incomplete(visit):
    """A SCHEDULED visit that loses completeness falls back to DRAFT."""
    if visit["status"] != "SCHEDULED":
        return False
    if team_complete(visit):
        return False
    visit["status"] = "DRAFT"
    visit["scheduled_by_user_id"] = None
    db.touch(visit)
    cycle = db.cycles.get(visit["cycle_id"])
    if cycle is not None and cycle["status"] == "VISIT_SCHEDULED":
        cycle["status"] = "SELF_ASSESSMENT"
        db.touch(cycle)
    return True


def archive_prior_reports(camp_id, cycle_year):
    for report in camp_reports(camp_id):
        if report["status"] == "ACCEPTED" and report["report_year"] < cycle_year:
            report["status"] = "ARCHIVED"
            db.touch(report)


def recompute_visit_scoring_counts(visit, cycle_id):
    scored = 0
    met = 0
    for row in applicable_mandatory_rows(cycle_id):
        if row["visitor_score"] is not None:
            scored += 1
        if row["visitor_score"] == "MET":
            met += 1
    visit["mandatory_scored_count"] = scored
    visit["mandatory_met_count"] = met
    db.touch(visit)


def recompute_open_deficiency_count(cycle):
    count = open_deficiency_count(cycle["id"])
    if cycle.get("open_deficiency_count") != count:
        cycle["open_deficiency_count"] = count
        db.touch(cycle)
    return count


def recompute_set_counts(standards_set):
    rows = [
        s for s in db.standards.values() if s["standards_set_id"] == standards_set["id"]
    ]
    standards_set["standard_count"] = len(rows)
    standards_set["mandatory_count"] = len([s for s in rows if s["mandatory"]])
    db.touch(standards_set)


def recompute_disclosed_count(report):
    report["disclosed_incident_count"] = len(report_disclosures(report["id"]))
    db.touch(report)
