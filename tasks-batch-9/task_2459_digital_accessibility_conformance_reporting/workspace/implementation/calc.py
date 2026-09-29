"""The six calculation rules (PRD 2.8, 3.4, 3.6, 3.9, 3.10 / SCAFFOLD 1.3)."""
from decimal import Decimal, ROUND_HALF_UP

from db import db, clock_date, clock_now, sort_key
from validate import AT_PROFILES, DISABILITY_CATEGORIES

# ------------------------------------------------------------- constants ----
PROFILE_WEIGHTS = {
    "SCREEN_READER": Decimal("0.45"),
    "KEYBOARD": Decimal("0.35"),
    "MAGNIFICATION": Decimal("0.20"),
}
AUTOMATED_CREDIT = Decimal("0.4")
MANUAL_CREDIT = Decimal("1.0")
AUTOMATED_ONLY_CAP = Decimal("0.60")
MIN_ATTEST_COVERAGE_PCT = Decimal("45.00")

SUPPORT_WEIGHT = {
    "SUPPORTS": Decimal("1.0"),
    "PARTIALLY_SUPPORTS": Decimal("0.5"),
    "DOES_NOT_SUPPORT": Decimal("0.0"),
}


def weight_to_support(weight):
    """Reverse map of SUPPORT_WEIGHT for the report snapshot (PRD 3.6)."""
    if weight == Decimal("1.0"):
        return "SUPPORTS"
    if weight == Decimal("0.5"):
        return "PARTIALLY_SUPPORTS"
    return "DOES_NOT_SUPPORT"



LEVELS_FOR_TARGET = {"A": ["A"], "AA": ["A", "AA"], "AAA": ["A", "AA", "AAA"]}
POSTURE_INDEX_FLOOR = Decimal("85.00")

SEVERITY_POINTS = {
    "BLOCKER": Decimal("40"),
    "SERIOUS": Decimal("25"),
    "MODERATE": Decimal("12"),
    "MINOR": Decimal("5"),
}
BREADTH_STEP = Decimal("0.15")
REACH_FLOOR = Decimal("0.5")
AGING_STEP = Decimal("0.02")
AGING_CAP_DAYS = 60
COMPLAINT_STEP = Decimal("0.10")
COMPLAINT_CAP = 5
RISK_CEILING = Decimal("100.0")

COST_PER_POINT_CENTS = Decimal("18750")
OVERHEAD_MULT = Decimal("1.0725")

ISSUE_DEBT = {
    "BLOCKER": Decimal("8"),
    "SERIOUS": Decimal("5"),
    "MODERATE": Decimal("3"),
    "MINOR": Decimal("1"),
}
OVERDUE_SURCHARGE = Decimal("2")
TIER_STANDARD_MAX = Decimal("6")
TIER_ELEVATED_MAX = Decimal("12")
TIER_PENALTY = {
    "STANDARD": Decimal("0.5"),
    "ELEVATED": Decimal("1.0"),
    "CRITICAL": Decimal("2.0"),
}
STALENESS_BUCKET_DAYS = 30
STALENESS_BUCKET_CAP = 4

STALE_QUESTIONNAIRE_LIMIT = 2
STALE_WINDOW_DAYS = 30
CORRECTION_WINDOW_DAYS = 10
UPDATE_CADENCE_DAYS = 90
EVIDENCE_MAX_AGE_DAYS = 90

DEBT_ISSUE_STATES = ("OPEN", "TRIAGED", "COMMITTED", "PUBLISHED_COMMITTED")


def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round0(value):
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def criterion_sort_key(criterion):
    raw = criterion.get("criterion_number") or ""
    try:
        return (0, tuple(int(part) for part in raw.split(".")), raw)
    except (TypeError, ValueError):
        return (1, tuple(), raw)


# ------------------------------------------------- component coverage -------
def component_runs(component_id, status="COMPLETED"):
    return [run for run in db.runs.values()
            if run["component_id"] == component_id and run["status"] == status]


def component_coverage_pct(component):
    """AT-profile weighted coverage with the automated-evidence cap (PRD 3.4)."""
    denom = Decimal(component["applicable_criteria_count"])
    runs = component_runs(component["id"])
    total = Decimal("0")
    for profile in AT_PROFILES:
        auto = sum((run["criteria_exercised"] for run in runs
                    if run["method"] == "AUTOMATED" and run["at_profile"] == profile), 0)
        manual = sum((run["criteria_exercised"] for run in runs
                      if run["method"] == "MANUAL" and run["at_profile"] == profile), 0)
        raw = (AUTOMATED_CREDIT * Decimal(auto) + MANUAL_CREDIT * Decimal(manual)) / denom
        if raw > Decimal("1.0"):
            raw = Decimal("1.0")
        cap = AUTOMATED_ONLY_CAP if manual == 0 else Decimal("1.00")
        score = raw if raw < cap else cap
        total += PROFILE_WEIGHTS[profile] * score
    # exactly one rounding, on the final weighted sum
    return round2(Decimal("100") * total)


def component_validated_categories(component):
    """Union over COMPLETED MANUAL runs only (PRD 3.4)."""
    found = set()
    for run in component_runs(component["id"]):
        if run["method"] == "MANUAL":
            found.update(run["disability_categories_validated"])
    return [category for category in DISABILITY_CATEGORIES if category in found]


def component_evidence_units(component):
    return sum((run["criteria_exercised"] for run in component_runs(component["id"])), 0)


# ------------------------------------------------- conformance index --------
def in_scope_criteria(product):
    levels = LEVELS_FOR_TARGET[product["target_level"]]
    rows = [c for c in db.criteria.values()
            if c["standard_id"] == product["standard_id"] and c["level"] in levels]
    rows.sort(key=criterion_sort_key)
    return rows


def in_scope_components(product):
    rows = [c for c in db.components.values()
            if c["product_id"] == product["id"] and c["in_scope"]]
    rows.sort(key=sort_key)
    return rows


def _qualifying_assessment(component_id, criterion_id, states):
    rows = [a for a in db.assessments.values()
            if a["component_id"] == component_id
            and a["criterion_id"] == criterion_id
            and a["attestation_state"] in states]
    if not rows:
        return None
    # greatest created_at, tie-break greatest version
    rows.sort(key=lambda a: (a["created_at"], a["version"], a["_seq"]))
    return rows[-1]


def conformance_index(product, variant):
    """Returns (index Decimal, denominator int, snapshot list) — PRD 3.6."""
    states = ("DRAFT", "ATTESTED") if variant == "PROVISIONAL" else ("ATTESTED",)
    criteria = in_scope_criteria(product)
    components = in_scope_components(product)

    denominator = 0
    numerator = Decimal("0")
    snapshot = []

    for criterion in criteria:
        contributions = []
        not_applicable_present = False
        missing_qualifying = False
        for component in components:
            pick = _qualifying_assessment(component["id"], criterion["id"], states)
            if pick is None:
                missing_qualifying = True
            elif pick["support_level"] == "NOT_APPLICABLE":
                not_applicable_present = True
            else:
                contributions.append(SUPPORT_WEIGHT[pick["support_level"]])

        if contributions:
            rolled = min(contributions)
            if variant == "CERTIFIED" and missing_qualifying:
                rolled = Decimal("0.0")
            included = True
        else:
            if variant == "PROVISIONAL":
                included = False
                rolled = None
            elif not_applicable_present:
                included = False
                rolled = None
            else:
                included = True
                rolled = Decimal("0.0")

        if included:
            denominator += 1
            numerator += rolled
            snapshot.append({
                "criterion_id": criterion["id"],
                "rolled_support_level": weight_to_support(rolled),
                "weight": float(rolled),
            })
        else:
            snapshot.append({
                "criterion_id": criterion["id"],
                "rolled_support_level": "NOT_APPLICABLE",
                "weight": None,
            })

    if denominator == 0:
        index = Decimal("0.00")
    else:
        index = round2(Decimal("100") * numerator / Decimal(denominator))
    return index, denominator, snapshot


# ------------------------------------------------------- risk scoring -------
def _risk_base(issue):
    criterion = db.criteria.get(issue["criterion_id"])
    component = db.components.get(issue["component_id"])
    breadth = len(set(criterion["disability_categories"])) if criterion else 1
    reach_pct = Decimal(component["user_reach_pct"]) if component else Decimal("0")
    usage_weight = reach_pct / Decimal("100")
    breadth_factor = Decimal("1") + BREADTH_STEP * Decimal(breadth - 1)
    reach_factor = REACH_FLOOR + (Decimal("1") - REACH_FLOOR) * usage_weight
    return SEVERITY_POINTS[issue["severity"]] * breadth_factor * reach_factor


def remediation_risk_score(issue, variant):
    """PRD 3.9 — the base term is never pre-rounded."""
    base = _risk_base(issue)
    if variant == "INTAKE_ESTIMATE":
        return round2(base)
    days_late = 0
    target = issue.get("_target_date")
    if target is not None:
        delta = (clock_date() - target).days
        days_late = delta if delta > 0 else 0
    aging = Decimal("1") + AGING_STEP * Decimal(min(days_late, AGING_CAP_DAYS))
    amp = Decimal("1") + COMPLAINT_STEP * Decimal(
        min(issue.get("linked_complaint_count", 0), COMPLAINT_CAP))
    product = base * aging * amp
    if product > RISK_CEILING:
        product = RISK_CEILING
    return round2(product)


# ------------------------------------------------ disclosure debt -----------
def questionnaire_disclosure_debt(questionnaire):
    """Four pinned steps; the tier is keyed on base_debt only (PRD 3.10)."""
    today = clock_date()
    base_debt = Decimal("0")
    for issue in db.issues.values():
        if issue["product_id"] != questionnaire["product_id"]:
            continue
        if issue["publish_intent"] != "INCLUDED":
            continue
        if issue["state"] not in DEBT_ISSUE_STATES:
            continue
        base_debt += ISSUE_DEBT[issue["severity"]]
        target = issue.get("_target_date")
        if target is not None and target < today:
            base_debt += OVERDUE_SURCHARGE

    if base_debt <= TIER_STANDARD_MAX:
        tier = "STANDARD"
    elif base_debt <= TIER_ELEVATED_MAX:
        tier = "ELEVATED"
    else:
        tier = "CRITICAL"

    reference = questionnaire.get("_last_attested_dt") or questionnaire["_created_dt"]
    days_since = int((clock_now() - reference).total_seconds() // 86400)
    if days_since < 0:
        days_since = 0
    bucket = min(STALENESS_BUCKET_CAP, days_since // STALENESS_BUCKET_DAYS)
    penalty = TIER_PENALTY[tier] * Decimal(bucket)
    return round2(base_debt + penalty), tier


# --------------------------------------------- budget waterfall -------------
def allocation_candidates(train, product_id):
    rows = [issue for issue in db.issues.values()
            if issue.get("release_train_id") == train["id"]
            and issue["product_id"] == product_id
            and issue["state"] in ("COMMITTED", "PUBLISHED_COMMITTED")]
    rows.sort(key=lambda i: (-i["risk_score"], i["target_remediation_date"],
                             i["created_at"], i["_seq"]))
    return rows


def issue_ask_cents(issue):
    raw = Decimal(issue["effort_points"]) * COST_PER_POINT_CENTS * OVERHEAD_MULT
    return int(round0(raw))
