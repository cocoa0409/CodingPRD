"""The fourteen calculations plus the derived counters they feed (PRD 3, SCAFFOLD
calculations[]).  Every non-integer result is produced with decimal.Decimal and
ROUND_HALF_UP at the precision the PRD pins.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import clock
import store
import vocab
from errors import ApiError

ZERO = Decimal("0")
CENT = Decimal("0.01")


def q2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def f2(value):
    """A 2-decimal quantity as it appears on the wire."""
    return float(q2(value))


# --------------------------------------------------------------------------- #
# Relationship helpers
# --------------------------------------------------------------------------- #

def finding_selection(finding):
    return store.get(store.INSPECTION_SELECTIONS, finding["selection_id"])


def finding_inspection(finding):
    selection = finding_selection(finding)
    return store.get(store.INSPECTIONS, selection["inspection_id"]) if selection else None


def finding_firm_id(finding):
    inspection = finding_inspection(finding)
    return inspection["firm_id"] if inspection else None


def firm_findings(firm_id):
    out = []
    for finding in store.rows(store.FINDINGS):
        if finding_firm_id(finding) == firm_id:
            out.append(finding)
    return out


def firm_of(collection, row):
    """The firm a row belongs to, resolved through its own foreign-key chain (PRD 2.1)."""
    if row is None:
        return None
    if collection == store.FIRMS:
        return row["id"]
    if collection in (store.PARTNERS, store.ENGAGEMENTS, store.QUALITY_RISKS,
                      store.INSPECTIONS, store.PEER_REVIEWS):
        return row.get("firm_id")
    if collection == store.RISK_RESPONSES:
        return firm_of(store.QUALITY_RISKS,
                       store.get(store.QUALITY_RISKS, row["quality_risk_id"]))
    if collection == store.QUALITY_REVIEWS:
        return firm_of(store.ENGAGEMENTS,
                       store.get(store.ENGAGEMENTS, row["engagement_id"]))
    if collection == store.INSPECTION_SELECTIONS:
        return firm_of(store.INSPECTIONS, store.get(store.INSPECTIONS, row["inspection_id"]))
    if collection == store.FINDINGS:
        return finding_firm_id(row)
    if collection in (store.RCAS, store.PLANS):
        finding = store.get(store.FINDINGS, row["finding_id"])
        return finding_firm_id(finding) if finding else None
    if collection in (store.PR_SELECTIONS, store.CAPS):
        review = store.get(store.PEER_REVIEWS, row["peer_review_id"])
        return review["firm_id"] if review else None
    return None


def children(collection, key, value):
    return [row for row in store.rows(collection) if row.get(key) == value]


# --------------------------------------------------------------------------- #
# Partner derived fields
# --------------------------------------------------------------------------- #

def refresh_partner(partner, force=False):
    """eqr_eligible is recomputed on every write that could change its inputs; the two
    open-work counters are derived from the rows themselves so they can never drift."""
    open_eqr = 0
    for review in store.rows(store.QUALITY_REVIEWS):
        if review["reviewer_partner_id"] == partner["id"] and \
                review["state"] in vocab.EQR_OPEN_STATES:
            open_eqr += 1
    open_engagements = 0
    for engagement in store.rows(store.ENGAGEMENTS):
        if engagement["engagement_partner_id"] == partner["id"] and \
                engagement["workflow_state"] != "REPORT_RELEASED":
            open_engagements += 1
    eligible = (
        partner["status"] == "ACTIVE"
        and partner["cpe_hours_last_3y"] >= 120
        and "EQ_REVIEWER" in partner["designations"]
    )
    return store.mutate(partner, {
        "open_eqr_count": open_eqr,
        "open_engagement_count": open_engagements,
        "eqr_eligible": eligible,
    }, force=force)


# --------------------------------------------------------------------------- #
# Calculation 6: firm_risk_posture (and the counters that feed it)
# --------------------------------------------------------------------------- #

def firm_counters(firm_id):
    open_deficiency = 0
    open_material = 0
    for finding in firm_findings(firm_id):
        if finding["classification"] in vocab.DEFICIENCY_CLASSES and \
                finding["state"] not in ("VERIFIED", "WITHDRAWN"):
            open_deficiency += 1
            if finding["classification"] == "MATERIAL_FAILURE":
                open_material += 1
    critical = 0
    for risk in store.rows(store.QUALITY_RISKS):
        if risk["firm_id"] == firm_id and risk["state"] == "EVALUATED" and \
                risk["severity_band"] == "CRITICAL":
            critical += 1
    return open_deficiency, open_material, critical


def latest_rating(firm_id):
    """Firm.last_peer_review_rating mirrors the rating of the most recent peer review that
    reached ACCEPTED or FOLLOW_UP_REQUIRED, ordered by report_issued_at descending."""
    candidates = [
        review for review in store.rows(store.PEER_REVIEWS)
        if review["firm_id"] == firm_id
        and review["state"] in ("ACCEPTED", "FOLLOW_UP_REQUIRED")
    ]
    if not candidates:
        return "NONE"
    candidates.sort(key=lambda r: (r["report_issued_at"] or "", store.order_key(r)),
                    reverse=True)
    return candidates[0]["rating"]


def recompute_counters(firm, bump=True):
    """Recompute the counters from the underlying finding and quality-risk rows."""
    open_deficiency, open_material, critical = firm_counters(firm["id"])
    updates = {
        "open_deficiency_count": open_deficiency,
        "open_material_failure_count": open_material,
        "critical_risk_count": critical,
        "last_peer_review_rating": latest_rating(firm["id"]),
    }
    if not bump:
        firm.update(updates)
        return False
    return store.mutate(firm, updates)


def recompute_posture(firm, bump=True):
    """The counters feeding the ladder are always recomputed immediately before it runs
    within the same request, so the posture never reads a stale counter."""
    recompute_counters(firm, bump=bump)
    if firm["last_peer_review_rating"] == "FAIL" or \
            firm["open_material_failure_count"] >= 1 or firm["critical_risk_count"] >= 3:
        posture = "CRITICAL"
    elif firm["last_peer_review_rating"] == "PASS_WITH_DEFICIENCY" or \
            firm["critical_risk_count"] >= 1 or firm["open_deficiency_count"] >= 5:
        posture = "ELEVATED"
    else:
        posture = "STABLE"
    if not bump:
        firm["risk_posture"] = posture
        return posture
    store.mutate(firm, {"risk_posture": posture})
    return posture


# --------------------------------------------------------------------------- #
# Calculation 1: engagement_risk_score
# --------------------------------------------------------------------------- #

TYPE_WEIGHT = {
    "AUDIT": 20, "REVIEW": 8, "ATTESTATION": 6,
    "ERISA_AUDIT": 30, "SINGLE_AUDIT": 32, "BROKER_DEALER": 28,
}

SPEC_FOR_TYPE = {
    "ERISA_AUDIT": "EBP", "SINGLE_AUDIT": "GOVERNMENT", "BROKER_DEALER": "BROKER_DEALER",
}


def engagement_risk_score(engagement_type, is_first_year_client, is_public_interest,
                          prior_finding_count_3y, partner_open_engagements,
                          partner_specializations):
    base = TYPE_WEIGHT[engagement_type]
    if is_first_year_client:
        base += 15
    if is_public_interest:
        base += 12
    base += min(20, 4 * prior_finding_count_3y)
    load_penalty = max(0, partner_open_engagements - 8) * 3
    spec = SPEC_FOR_TYPE.get(engagement_type)
    spec_credit = 10 if spec is not None and spec in partner_specializations else 0
    # The clamp is applied last, to the assembled total.
    return min(100, max(0, base + load_penalty - spec_credit))


# --------------------------------------------------------------------------- #
# Calculation 2: eqr_required_determination
# --------------------------------------------------------------------------- #

def eqr_required(engagement, firm):
    if engagement["risk_score"] >= 70:
        return True
    if engagement["engagement_type"] in vocab.MUST_SELECT_ENGAGEMENT_TYPES:
        return True
    if engagement["is_public_interest"]:
        return True
    if firm["risk_posture"] in ("ELEVATED", "CRITICAL"):
        return True
    return False


def apply_eqr_required(engagement, firm):
    """Once true the flag never reverts to false."""
    if engagement["eqr_required"]:
        return False
    return eqr_required(engagement, firm)


# --------------------------------------------------------------------------- #
# Calculation 3: eqr_reviewer_eligibility (ordered clauses, first failure wins)
# --------------------------------------------------------------------------- #

def eqr_reviewer_eligibility(engagement, candidate, objectivity_attested):
    if candidate["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_INACTIVE")
    if candidate["firm_id"] != engagement["firm_id"]:
        raise ApiError("ERR_PARTNER_FIRM_MISMATCH")
    if candidate["id"] == engagement["engagement_partner_id"]:
        raise ApiError("ERR_EQR_SELF_REVIEW")
    if "EQ_REVIEWER" not in candidate["designations"] or \
            candidate["cpe_hours_last_3y"] < 120:
        raise ApiError("ERR_CPE_REQUIREMENT_NOT_MET")
    if engagement["client_name"] in candidate["independence_conflict_client_names"]:
        raise ApiError("ERR_REVIEWER_INDEPENDENCE_CONFLICT")
    if objectivity_attested is not True:
        raise ApiError("ERR_OBJECTIVITY_NOT_ATTESTED")

    # Cooling-off: latest exit_date for this client, earlier array position on a tie.
    best = None
    for entry in candidate["prior_engagement_team_clients"]:
        if entry["client_name"] != engagement["client_name"]:
            continue
        exit_date = clock.parse_date(entry["exit_date"])
        if exit_date is None:
            continue
        if best is None or exit_date > best:
            best = exit_date
    if best is None:
        return None
    period_end = clock.parse_date(engagement["period_end"])
    days = clock.days_between(period_end, best)
    if days < 730:
        raise ApiError("ERR_COOLING_OFF_NOT_MET")
    return days


# --------------------------------------------------------------------------- #
# Calculation 4: eqr_reviewer_concurrency_window
# --------------------------------------------------------------------------- #

def eqr_concurrency_check(engagement, candidate):
    """Half-open intervals with no buffer; touching endpoints do not overlap."""
    new_start = clock.now()
    overlaps = 0
    for review in store.rows(store.QUALITY_REVIEWS):
        if review["reviewer_partner_id"] != candidate["id"]:
            continue
        if review["state"] not in vocab.EQR_OPEN_STATES:
            continue
        start = clock.parse_instant(review["assigned_at"])
        end = clock.parse_instant(review["concluded_at"])
        # new = [new_start, +inf) so `new_start < existing_end` and `start < +inf`.
        if end is None or new_start < end:
            overlaps += 1
    if overlaps >= 3:
        raise ApiError("ERR_EQR_CAPACITY_EXCEEDED")
    for review in store.rows(store.QUALITY_REVIEWS):
        if review["engagement_id"] == engagement["id"] and \
                review["state"] in vocab.EQR_OPEN_STATES:
            raise ApiError("ERR_EQR_ALREADY_ASSIGNED")


# --------------------------------------------------------------------------- #
# Calculation 5: residual_risk_score
# --------------------------------------------------------------------------- #

DESIGN_CREDIT = {
    "EFFECTIVE": Decimal("0.35"), "PARTIALLY_EFFECTIVE": Decimal("0.20"),
}
OPERATING_CREDIT = {
    "EFFECTIVE": Decimal("0.30"), "PARTIALLY_EFFECTIVE": Decimal("0.10"),
}
DESIGN_CAP = Decimal("0.80")


def risk_responses(risk_id):
    return [row for row in store.rows(store.RISK_RESPONSES)
            if row["quality_risk_id"] == risk_id]


def residual_risk_score(risk, basis):
    inherent = Decimal(risk["likelihood"] * risk["impact"])
    responses = risk_responses(risk["id"])
    if basis == "DESIGN_BASIS":
        total = ZERO
        for response in responses:
            if response["status"] not in ("DESIGNED", "TESTED"):
                continue
            total += DESIGN_CREDIT.get(response["design_effectiveness"], ZERO)
        if total > DESIGN_CAP:
            total = DESIGN_CAP
        residual = q2(inherent * (Decimal(1) - total))
    else:
        tested = [r for r in responses if r["status"] == "TESTED"]
        if not tested:
            raise ApiError("ERR_NO_TESTED_RESPONSE")
        tested.sort(key=lambda r: (r["tested_on"] or "", store.order_key(r)))
        running = inherent
        for response in tested:
            credit = OPERATING_CREDIT.get(response["operating_effectiveness"], ZERO)
            running = running * (Decimal(1) - credit)
        residual = q2(running)
    return residual, severity_band(residual)


def severity_band(residual):
    value = Decimal(residual)
    if value >= Decimal("15.00"):
        return "CRITICAL"
    if value >= Decimal("8.00"):
        return "HIGH"
    if value >= Decimal("4.00"):
        return "MODERATE"
    return "LOW"


def response_count(risk_id):
    return len([r for r in risk_responses(risk_id) if r["status"] in ("DESIGNED", "TESTED")])


# --------------------------------------------------------------------------- #
# Calculation 7: inspection_engagement_selection
# --------------------------------------------------------------------------- #

def window_eligible(inspection):
    """Firm engagements in REPORT_RELEASED whose period_end falls inside the inspection
    year, both endpoints inclusive."""
    year = inspection["inspection_year"]
    low = "%04d-01-01" % year
    high = "%04d-12-31" % year
    out = []
    for engagement in store.rows(store.ENGAGEMENTS):
        if engagement["firm_id"] != inspection["firm_id"]:
            continue
        if engagement["workflow_state"] != "REPORT_RELEASED":
            continue
        if not (low <= engagement["period_end"] <= high):
            continue
        out.append(engagement)
    return out


def inspection_engagement_selection(inspection):
    """Blocks A (must-select type), B (partner coverage), C (risk-based fill).

    Returns an ordered list of (engagement, selection_reason, is_must_select) tuples.
    ``id`` is never consulted as a tie-break.
    """
    eligible = window_eligible(inspection)
    if not eligible:
        return []

    block_a = [e for e in eligible
               if e["engagement_type"] in vocab.MUST_SELECT_ENGAGEMENT_TYPES]
    block_a.sort(key=lambda e: (e["period_end"], store.order_key(e)))
    taken = {e["id"] for e in block_a}

    rest = [e for e in eligible if e["id"] not in taken]
    year = inspection["inspection_year"]
    picks = []
    seen_partners = []
    for engagement in rest:
        partner_id = engagement["engagement_partner_id"]
        if partner_id in seen_partners:
            continue
        seen_partners.append(partner_id)
        partner = store.get(store.PARTNERS, partner_id)
        if partner is None:
            continue
        last = partner["last_inspected_year"]
        if last is not None and last > year - 3:
            continue
        candidates = [e for e in rest if e["engagement_partner_id"] == partner_id]
        candidates.sort(
            key=lambda e: (-e["risk_score"], e["period_end"], store.order_key(e)))
        picks.append(candidates[0])
    picks.sort(key=lambda e: (-e["risk_score"], store.order_key(e)))
    block_b = picks
    taken.update(e["id"] for e in block_b)

    remaining = [e for e in eligible if e["id"] not in taken]
    remaining.sort(key=lambda e: (-e["risk_score"], store.order_key(e)))
    room = max(0, inspection["target_engagement_count"] - len(block_a) - len(block_b))
    block_c = remaining[:room]

    ordered = []
    for engagement in block_a:
        ordered.append((engagement,
                        "MUST_SELECT_" + engagement["engagement_type"], True))
    for engagement in block_b:
        ordered.append((engagement, "MUST_SELECT_PARTNER_COVERAGE", True))
    for engagement in block_c:
        ordered.append((engagement, "RISK_BASED", False))
    return ordered


# --------------------------------------------------------------------------- #
# Calculation 8: must_select_coverage_pct
# --------------------------------------------------------------------------- #

def must_select_coverage(inspection):
    eligible_count = len([
        e for e in window_eligible(inspection)
        if e["engagement_type"] in vocab.MUST_SELECT_ENGAGEMENT_TYPES])
    selected_count = len([
        s for s in children(store.INSPECTION_SELECTIONS, "inspection_id", inspection["id"])
        if s["is_must_select"] and
        s["selection_reason"] != "MUST_SELECT_PARTNER_COVERAGE"])
    if eligible_count == 0:
        pct = Decimal("100.00")
    else:
        pct = q2(Decimal(100) * Decimal(selected_count) / Decimal(eligible_count))
    return eligible_count, selected_count, pct


# --------------------------------------------------------------------------- #
# Calculation 9: deficiency_severity_index
# --------------------------------------------------------------------------- #

CLASS_POINTS = {
    "UNCLASSIFIED": 0, "OBSERVATION": 0, "DEFICIENCY": 3,
    "SIGNIFICANT_DEFICIENCY": 8, "MATERIAL_FAILURE": 20,
}


def selection_findings(selection_id, exclude_withdrawn=True):
    out = []
    for finding in children(store.FINDINGS, "selection_id", selection_id):
        if exclude_withdrawn and finding["state"] == "WITHDRAWN":
            continue
        out.append(finding)
    return out


def selection_weighted_points(selection):
    raw = sum(CLASS_POINTS[f["classification"]]
              for f in selection_findings(selection["id"]))
    multiplier = Decimal("1.5") if selection["is_must_select"] else Decimal("1.0")
    return q2(Decimal(raw) * multiplier)


def deficiency_severity_index(inspection, basis):
    selections = children(store.INSPECTION_SELECTIONS, "inspection_id", inspection["id"])
    findings = []
    for selection in selections:
        findings.extend(selection_findings(selection["id"]))

    if basis == "ENGAGEMENT_WEIGHTED":
        total = ZERO
        per_selection = {}
        for selection in selections:
            points = selection_weighted_points(selection)
            per_selection[selection["id"]] = points
            total += points
        divisor = inspection["engagements_selected_count"] or 1
        return q2(total / Decimal(divisor)), per_selection

    comp_points = {}
    for finding in findings:
        comp = finding["sqm_component"]
        comp_points[comp] = comp_points.get(comp, 0) + CLASS_POINTS[finding["classification"]]
    peak = max(comp_points.values()) if comp_points else 0
    systemic_bonus = 5 * len([f for f in findings if f["pervasiveness"] == "SYSTEMIC"])
    distinct = len(comp_points)
    index = q2(Decimal(peak + systemic_bonus) / Decimal(max(1, distinct)))
    return index, None


# --------------------------------------------------------------------------- #
# Calculation 10: root_cause_depth_score
# --------------------------------------------------------------------------- #

METHOD_BONUS = {"FIVE_WHYS": 2, "FISHBONE": 3, "PARETO": 1}


def rca_inspection(rca):
    finding = store.get(store.FINDINGS, rca["finding_id"])
    return finding_inspection(finding) if finding else None


def root_cause_depth_score(rca):
    inspection = rca_inspection(rca)
    firm_id = inspection["firm_id"] if inspection else None
    year = inspection["inspection_year"] if inspection else None
    recurrence = False
    if year is not None:
        for other in store.rows(store.RCAS):
            if other["id"] == rca["id"] or other["state"] != "VALIDATED":
                continue
            if other["root_cause_category"] != rca["root_cause_category"]:
                continue
            other_inspection = rca_inspection(other)
            if other_inspection is None or other_inspection["firm_id"] != firm_id:
                continue
            if other_inspection["inspection_year"] in (year - 1, year - 2):
                recurrence = True
                break
    depth = min(10, 2 * rca["contributing_factor_count"]
                + METHOD_BONUS[rca["method"]] + (2 if recurrence else 0))
    return recurrence, q2(Decimal(depth))


# --------------------------------------------------------------------------- #
# Calculation 11: remediation_acceptance_score
# --------------------------------------------------------------------------- #

PENALTY_RATE = {
    "CRITICAL": Decimal("0.15"), "STANDARD": Decimal("0.10"), "STRONG": Decimal("0.05"),
}


def remediation_acceptance_score(plan, rca):
    depth = Decimal(str(rca["depth_score"]))
    specificity = Decimal(str(plan["action_specificity_score"]))
    completed = Decimal(plan["completed_action_count"])
    actions = Decimal(plan["action_count"])
    raw = q2(Decimal("0.40") * depth + Decimal("0.35") * specificity
             + Decimal("0.25") * (Decimal(10) * completed / actions))
    if raw < Decimal("5.00"):
        tier = "CRITICAL"
    elif raw < Decimal("8.00"):
        tier = "STANDARD"
    else:
        tier = "STRONG"
    target = clock.parse_date(plan["target_completion_date"])
    late_days = max(0, clock.days_between(clock.today(), target))
    score = q2(max(ZERO, raw - PENALTY_RATE[tier] * Decimal(late_days)))
    return raw, tier, score


# --------------------------------------------------------------------------- #
# PeerReviewer derived counters
# --------------------------------------------------------------------------- #

def refresh_reviewer(reviewer):
    active = 0
    hours = 0
    for review in store.rows(store.PEER_REVIEWS):
        if review["assigned_reviewer_id"] != reviewer["id"]:
            continue
        if review["state"] in vocab.PEER_REVIEW_PRE_REPORT_STATES:
            active += 1
        for selection in children(store.PR_SELECTIONS, "peer_review_id", review["id"]):
            if selection["status"] == "COMMITTED":
                hours += selection["hours_committed"]
    return store.mutate(reviewer, {
        "active_review_count": active,
        "committed_hours_balance": hours,
    })


def refresh_all_reviewers():
    for reviewer in store.rows(store.PEER_REVIEWERS):
        refresh_reviewer(reviewer)


# --------------------------------------------------------------------------- #
# Calculation 13 (shared sub-formula): firm_must_select_categories
# --------------------------------------------------------------------------- #

def firm_must_select_categories(firm, year_end):
    """Emitted in the fixed declaration order, never in engagement order."""
    pool = []
    for engagement in store.rows(store.ENGAGEMENTS):
        if engagement["firm_id"] != firm["id"]:
            continue
        if engagement["workflow_state"] != "REPORT_RELEASED":
            continue
        if engagement["period_end"] > year_end:
            continue
        pool.append(engagement)
    out = []
    if any(e["engagement_type"] == "ERISA_AUDIT" for e in pool):
        out.append("ERISA_AUDIT")
    if any(e["engagement_type"] == "SINGLE_AUDIT" for e in pool):
        out.append("SINGLE_AUDIT")
    if any(e["engagement_type"] == "BROKER_DEALER" for e in pool):
        out.append("BROKER_DEALER")
    for engagement in pool:
        if engagement["engagement_type"] != "AUDIT":
            continue
        partner = store.get(store.PARTNERS, engagement["engagement_partner_id"])
        if partner is not None and "GOVERNMENT" in partner["industry_specializations"]:
            out.append("GOVERNMENTAL")
            break
    if any(e["is_public_interest"] for e in pool):
        out.append("PUBLIC_INTEREST")
    return out


def engagement_must_select_category(engagement):
    """The single category an engagement satisfies, taken in declaration order."""
    if engagement["engagement_type"] == "ERISA_AUDIT":
        return "ERISA_AUDIT"
    if engagement["engagement_type"] == "SINGLE_AUDIT":
        return "SINGLE_AUDIT"
    if engagement["engagement_type"] == "BROKER_DEALER":
        return "BROKER_DEALER"
    if engagement["engagement_type"] == "AUDIT":
        partner = store.get(store.PARTNERS, engagement["engagement_partner_id"])
        if partner is not None and "GOVERNMENT" in partner["industry_specializations"]:
            return "GOVERNMENTAL"
    if engagement["is_public_interest"]:
        return "PUBLIC_INTEREST"
    return None


# --------------------------------------------------------------------------- #
# Calculation 12: peer_reviewer_selection
# --------------------------------------------------------------------------- #

TRAVEL_BUFFER_DAYS = 5


def reviewer_window_conflict(reviewer, review):
    """Half-open windows, with the 5 travel days added to the EXISTING window's end."""
    new_start = clock.parse_date(review["scheduled_window_start"])
    new_end = clock.parse_date(review["scheduled_window_end"])
    for other in store.rows(store.PEER_REVIEWS):
        if other["id"] == review["id"]:
            continue
        if other["assigned_reviewer_id"] != reviewer["id"]:
            continue
        if other["state"] not in vocab.PEER_REVIEW_WINDOW_STATES:
            continue
        other_start = clock.parse_date(other["scheduled_window_start"])
        other_end = clock.parse_date(other["scheduled_window_end"])
        extended_end = clock.add_days(other_end, TRAVEL_BUFFER_DAYS)
        if new_start < extended_end and other_start < new_end:
            return True
    return False


def reviewer_pool(firm, review, target_categories):
    pool = []
    targets = set(target_categories)
    for reviewer in store.rows(store.PEER_REVIEWERS):
        if reviewer["status"] != "ACTIVE":
            continue
        if reviewer["license_state"] != firm["state_code"] and \
                not reviewer["accepts_out_of_state"]:
            continue
        if not targets.issubset(set(reviewer["qualified_categories"])):
            continue
        if firm["legal_name"] in reviewer["independence_conflict_firm_names"]:
            continue
        if reviewer["id"] in firm["prior_reviewer_ids"]:
            continue
        if reviewer["active_review_count"] >= reviewer["max_concurrent_reviews"]:
            continue
        if reviewer_window_conflict(reviewer, review):
            continue
        pool.append(reviewer)
    pool.sort(key=lambda p: (
        -len(set(p["qualified_categories"]) & targets),
        p["active_review_count"],
        -p["experience_hours"],
        store.order_key(p),
    ))
    return pool


def check_named_reviewer(firm, review, reviewer, target_categories):
    """The named-candidate path evaluates the same clauses one by one, in ascending
    validation-priority order, and reports the specific clause that failed."""
    if firm["legal_name"] in reviewer["independence_conflict_firm_names"]:
        raise ApiError("ERR_REVIEWER_INDEPENDENCE_CONFLICT")
    if reviewer["id"] in firm["prior_reviewer_ids"]:
        raise ApiError("ERR_REVIEWER_ROTATION_REQUIRED")
    if reviewer_window_conflict(reviewer, review):
        raise ApiError("ERR_REVIEWER_WINDOW_CONFLICT")
    if reviewer["status"] != "ACTIVE":
        raise ApiError("ERR_REVIEWER_SUSPENDED")
    if reviewer["license_state"] != firm["state_code"] and \
            not reviewer["accepts_out_of_state"]:
        raise ApiError("ERR_REVIEWER_STATE_NOT_LICENSED")
    if reviewer["active_review_count"] >= reviewer["max_concurrent_reviews"]:
        raise ApiError("ERR_REVIEWER_AT_CAPACITY")
    if not set(target_categories).issubset(set(reviewer["qualified_categories"])):
        raise ApiError("ERR_MUST_SELECT_CATEGORY_NOT_QUALIFIED")


# --------------------------------------------------------------------------- #
# Calculation 13: peer_review_hours_scope
# --------------------------------------------------------------------------- #

CATEGORY_HOURS = {
    "ERISA_AUDIT": 8, "SINGLE_AUDIT": 10, "BROKER_DEALER": 8,
    "GOVERNMENTAL": 6, "PUBLIC_INTEREST": 12,
}


def base_tier(aa_hours):
    if aa_hours <= 500:
        return 16
    if aa_hours <= 2000:
        return 24
    if aa_hours <= 10000:
        return 40
    return 64


def posture_uplift(posture):
    if posture == "CRITICAL":
        return Decimal("0.25")
    if posture == "ELEVATED":
        return Decimal("0.10")
    return Decimal("0.00")


def peer_review_hours_scope(firm, categories):
    tier = Decimal(base_tier(firm["aa_hours_last_year"]))
    uplift = Decimal(1) + posture_uplift(firm["risk_posture"])
    component_base = q2(tier * uplift)
    category_sum = Decimal(sum(CATEGORY_HOURS[c] for c in categories))
    component_must_sel = q2(category_sum * uplift)
    total = int(math.ceil(component_base + component_must_sel))
    return total


# --------------------------------------------------------------------------- #
# Calculation 14: peer_review_rating
# --------------------------------------------------------------------------- #

def committed_selections(review_id):
    return [s for s in children(store.PR_SELECTIONS, "peer_review_id", review_id)
            if s["status"] == "COMMITTED"]


def peer_review_rating(review):
    selections = committed_selections(review["id"])
    scope_limitations = len([s for s in selections if s["is_scope_limitation"]])
    significant = len([s for s in selections
                       if s["disposition"] == "SIGNIFICANT_DEFICIENCY"])
    deficiencies = len([s for s in selections if s["disposition"] == "DEFICIENCY"])
    must_select_non_conforming = len([
        s for s in selections
        if s["non_conforming"] and s["must_select_category"] is not None])
    non_conforming = len([s for s in selections if s["non_conforming"]])
    if significant >= 1 or must_select_non_conforming >= 1 or scope_limitations >= 2:
        rating = "FAIL"
    elif deficiencies >= 1 or non_conforming >= 1 or scope_limitations == 1:
        rating = "PASS_WITH_DEFICIENCY"
    else:
        rating = "PASS"
    return rating, scope_limitations


def committed_hours(review_id):
    return sum(s["hours_committed"] for s in committed_selections(review_id))
