"""Derived fields, posture, and the synchronous cascades (PRD 2.5, 2.6, 3.x)."""

import db
from errors import ApiError
from services import calc
from services.constants import (
    AAI_VALIDITY_DAYS,
    ATTAINMENT_EVENTS_REQUIRED,
    COMPLIANCE_CURRENT_THRESHOLD,
    DEFENCE_CRITICAL,
    ENGINEERING_CONTROL_TYPES,
    OBLIGATION_WEIGHTS,
)


# --------------------------------------------------------------- lookups


def site_rows():
    return db.all_rows("sites")


def protection_for_site(site_id):
    rows = [p for p in db.all_rows("liability_protections")
            if p["site_id"] == site_id]
    return db.ordered(rows)[0] if rows else None


def obligations_of(protection_id):
    return db.ordered([o for o in db.all_rows("continuing_obligations")
                       if o["liability_protection_id"] == protection_id])


def goals_of_site(site_id):
    return db.ordered([g for g in db.all_rows("cleanup_goals")
                       if g["site_id"] == site_id])


def controls_of_site(site_id):
    return db.ordered([c for c in db.all_rows("site_controls")
                       if c["site_id"] == site_id])


def controls_of_plan(plan_id):
    return db.ordered([c for c in db.all_rows("site_controls")
                       if c["remedial_action_plan_id"] == plan_id])


def plans_of_enrollment(enrollment_id):
    return db.ordered([p for p in db.all_rows("remedial_action_plans")
                       if p["vcp_enrollment_id"] == enrollment_id])


def approved_plan_of_enrollment(enrollment_id):
    for plan in plans_of_enrollment(enrollment_id):
        if plan["status"] == "APPROVED":
            return plan
    return None


def approved_plan_of_site(site_id):
    for plan in db.ordered(db.all_rows("remedial_action_plans")):
        if plan["site_id"] == site_id and plan["status"] == "APPROVED":
            return plan
    return None


def letters_of_site(site_id):
    return db.ordered([l for l in db.all_rows("nfa_letters")
                       if l["site_id"] == site_id])


def awards_of_site(site_id):
    return db.ordered([a for a in db.all_rows("funding_awards")
                       if a["site_id"] == site_id])


def findings_of_phase(phase_id):
    return db.ordered([f for f in db.all_rows("contaminant_findings")
                       if f["assessment_phase_id"] == phase_id])


def phases_of_site(site_id):
    return db.ordered([p for p in db.all_rows("assessment_phases")
                       if p["site_id"] == site_id])


# ------------------------------------------------------------- posture gates


def assert_not_frozen(site):
    """Priority 10 gate: a FROZEN parcel refuses every mutating operation
    except the compliance sweep, void-certification and the clock."""
    if site["cleanup_posture"] == "FROZEN":
        raise ApiError("ERR_SITE_FROZEN",
                       "Parcel %s is FROZEN." % site["id"])


def assert_posture_open(site):
    """Priority 11 gate for the four closure-critical operations."""
    if site["cleanup_posture"] == "RESTRICTED":
        raise ApiError("ERR_SITE_POSTURE_RESTRICTED",
                       "Parcel %s posture is RESTRICTED." % site["id"])


# --------------------------------------------------------- cleanup goals


def distinct_contaminant_count(site_id, media):
    approved_phase_ids = set(
        p["id"] for p in phases_of_site(site_id) if p["status"] == "APPROVED"
    )
    codes = set()
    for finding in db.all_rows("contaminant_findings"):
        if finding["assessment_phase_id"] not in approved_phase_ids:
            continue
        if finding["media"] != media:
            continue
        if calc.D(finding["exceedance_factor"]) > calc.D("1.0"):
            codes.add(finding["contaminant_code"])
    return len(codes)


def recompute_goal(goal, site):
    count = distinct_contaminant_count(goal["site_id"], goal["media"])
    goal_ugl, cap_applied = calc.derive_goal(
        goal["screening_level_ugl"],
        goal["basis"],
        goal.get("control_credit_type"),
        goal["media"],
        site["intended_reuse"],
        count,
    )
    goal["contaminant_count_in_media"] = count
    goal["goal_ugl"] = goal_ugl
    goal["cumulative_cap_applied"] = cap_applied
    return goal


def replay_attainment(goal):
    """Replay the goal's compliant streak from scratch (PRD 3.8)."""
    events = [e for e in db.all_rows("monitoring_events")
              if e["cleanup_goal_id"] == goal["id"]
              and e["event_type"] == "SAMPLING"
              and e["status"] == "REPORTED"]
    events.sort(key=lambda e: (e["sample_date"], e["created_at"], e["_seq"]))
    streak = 0
    for event in events:
        value = event.get("result_value_ugl")
        if value is not None and calc.D(value) <= calc.D(goal["goal_ugl"]):
            streak += 1
        else:
            streak = 0
    goal["compliant_streak"] = streak
    goal["attainment_status"] = ("ATTAINED" if streak >= ATTAINMENT_EVENTS_REQUIRED
                                else "NOT_ATTAINED")
    return goal


# ------------------------------------------------------------------- BFPP


def recompute_protection(protection, site=None):
    """Recompute the weight buckets, compliance_pct, obligation_state and
    bfpp_status. Returns True when bfpp_status newly became FORFEITED."""
    if site is None:
        site = db.get("sites", protection["site_id"])
    obligations = obligations_of(protection["id"])
    buckets = {"CURRENT": 0, "SATISFIED": 0, "AT_RISK": 0, "LAPSED": 0}
    total = 0
    defence_lapsed = False
    for obligation in obligations:
        weight = OBLIGATION_WEIGHTS[obligation["obligation_category"]]
        total += weight
        buckets[obligation["status"]] = buckets[obligation["status"]] + weight
        if (obligation["status"] == "LAPSED"
                and obligation["obligation_category"] in DEFENCE_CRITICAL):
            defence_lapsed = True

    protection["obligations_total_weight"] = total
    protection["current_weight"] = buckets["CURRENT"]
    protection["satisfied_weight"] = buckets["SATISFIED"]
    protection["at_risk_weight"] = buckets["AT_RISK"]
    protection["lapsed_weight"] = buckets["LAPSED"]
    compliance = calc.compliance_ratio(buckets["CURRENT"], buckets["SATISFIED"],
                                       buckets["AT_RISK"], total)
    protection["compliance_pct"] = compliance

    if total == 0:
        obligation_state = "OBLIGATIONS_NONE"
    elif defence_lapsed:
        obligation_state = "LAPSED"
    elif calc.D(compliance) >= COMPLIANCE_CURRENT_THRESHOLD:
        obligation_state = "CURRENT"
    else:
        obligation_state = "AT_RISK"
    protection["obligation_state"] = obligation_state

    previous = protection.get("bfpp_status")
    if previous == "FORFEITED":
        status = "FORFEITED"          # absorbing
    elif obligation_state == "LAPSED":
        status = "FORFEITED"
    elif (protection["inquiry_state"] == "AAI_COMPLETE"
            and site is not None and site["acquisition_status"] == "ACQUIRED"):
        status = "ESTABLISHED"
    else:
        status = "NOT_ESTABLISHED"
    protection["bfpp_status"] = status
    return status == "FORFEITED" and previous != "FORFEITED"


def aai_expiry(report_date):
    return db.add_days(report_date, AAI_VALIDITY_DAYS)


# ------------------------------------------------------------ site posture


def recompute_posture(site):
    """Recompute impaired_control_count and cleanup_posture.

    Returns (row_changed, posture_changed)."""
    old_count = site.get("impaired_control_count", 0)
    old_posture = site.get("cleanup_posture", "OPEN")
    count = len([c for c in controls_of_site(site["id"])
                 if c["status"] == "IMPAIRED"])
    protection = protection_for_site(site["id"])
    if protection is not None and protection["bfpp_status"] == "FORFEITED":
        posture = "FROZEN"
    elif count > 0:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    site["impaired_control_count"] = count
    site["cleanup_posture"] = posture
    return (count != old_count or posture != old_posture), posture != old_posture


# -------------------------------------------------- revocation / rescission


def revoke_letters_and_rescind_awards(site, reason):
    """Cascade run when the defence forfeits or a control enters IMPAIRED."""
    for letter in letters_of_site(site["id"]):
        if letter["status"] in ("ISSUED", "ACCEPTED_BY_LENDER"):
            letter["status"] = "REVOKED"
            letter["revocation_reason"] = reason
            db.touch(letter)
    for award in awards_of_site(site["id"]):
        if award["status"] == "AWARDED":
            award["status"] = "RESCINDED"
            award["allocated_cents"] = 0
            db.touch(award)
    rederive_funding(site)


def forfeit_cascade(site):
    """Defence forfeited: freeze the parcel and revoke closure."""
    changed, _ = recompute_posture(site)
    if changed:
        db.touch(site)
    revoke_letters_and_rescind_awards(site, "BFPP_FORFEITED")
    return changed


def impair_control(control, site, revoke_letters=False,
                   source_event_reason="CONTROL_FAILURE"):
    """A control enters IMPAIRED.

    The parcel's posture and a COMPLETION_REVIEW enrollment always move.
    Closure letters are only revoked when the impairment came from a monitoring
    exceedance (§3.8); a failing operation certification stops at the enrollment
    (§3.7)."""
    control["status"] = "IMPAIRED"
    control["impaired_since"] = db.today_str()
    control["impairment_count"] = int(control.get("impairment_count", 0)) + 1
    db.touch(control)

    changed, _ = recompute_posture(site)
    if changed:
        db.touch(site)

    plan = db.get("remedial_action_plans", control["remedial_action_plan_id"])
    if plan is not None:
        enrollment = db.get("vcp_enrollments", plan["vcp_enrollment_id"])
        if (enrollment is not None
                and enrollment["status"] == "COMPLETION_REVIEW"
                and plan["status"] == "APPROVED"):
            enrollment["status"] = "IMPLEMENTATION"
            enrollment["reverted_completion_count"] = int(
                enrollment.get("reverted_completion_count", 0)) + 1
            db.touch(enrollment)

    if revoke_letters:
        revoke_letters_and_rescind_awards(site, source_event_reason)


# ------------------------------------------------------- funding waterfall


def design_line_values(plan):
    return calc.line_values(plan["cost_lines"])


def eligible_base_cents(plan, categories):
    if plan is None:
        return 0
    total = 0
    for line, value in zip(plan["cost_lines"], design_line_values(plan)):
        if line["cost_category"] in categories:
            total += value
    return total


def plan_has_eligible_line(plan, categories):
    if plan is None:
        return False
    return any(line["cost_category"] in categories for line in plan["cost_lines"])


def compute_assembly(site):
    """Pure computation of the parcel's funding assembly."""
    plan = approved_plan_of_site(site["id"])
    need = int(plan["total_funding_need_cents"]) if plan is not None else 0
    awarded = [a for a in awards_of_site(site["id"]) if a["status"] == "AWARDED"]
    awarded.sort(key=lambda a: (a["program_priority"], a["created_at"], a["_seq"]))
    remaining = need
    allocations = []
    local_match = 0
    for award in awarded:
        base = eligible_base_cents(plan, award["eligible_cost_categories"])
        share_cap = calc.share_cap_cents(base, award["max_share_pct"])
        allocated = min(int(award["max_award_cents"]), share_cap, remaining)
        if allocated < 0:
            allocated = 0
        remaining -= allocated
        allocations.append({"funding_award_id": award["id"],
                            "allocated_cents": allocated})
        local_match += calc.local_match_cents(allocated,
                                              award["match_requirement_pct"])
    return {
        "site_id": site["id"],
        "remedial_action_plan_id": plan["id"] if plan is not None else None,
        "total_funding_need_cents": need,
        "allocations": allocations,
        "unfunded_gap_cents": remaining,
        "local_match_required_cents": local_match,
    }


def rederive_funding(site):
    """Re-derive allocated_cents for every AWARDED award on the parcel."""
    assembly = compute_assembly(site)
    by_id = dict((a["funding_award_id"], a["allocated_cents"])
                 for a in assembly["allocations"])
    for award in awards_of_site(site["id"]):
        if award["status"] != "AWARDED":
            continue
        allocated = by_id.get(award["id"], 0)
        if int(award.get("allocated_cents", 0)) != allocated:
            award["allocated_cents"] = allocated
            db.touch(award)
    return assembly


# ---------------------------------------------------------- plan helpers


def recompute_plan_costs(plan, variant="DESIGN"):
    phase = db.get("assessment_phases", plan["basis_assessment_phase_id"])
    confidence = phase["delineation_confidence"] if phase else "SCREENING"
    max_ef = phase["max_exceedance_factor"] if phase else 0
    figures = calc.cost_estimate(plan["cost_lines"], confidence, max_ef,
                                 plan["years_to_construction_start"], variant)
    plan.update(figures)
    bound_premiums = 0
    for policy in db.all_rows("cost_cap_policies"):
        if policy["remedial_action_plan_id"] == plan["id"] and policy["status"] == "BOUND":
            bound_premiums += int(policy["premium_cents"])
    plan["total_funding_need_cents"] = plan["total_estimate_cents"] + bound_premiums
    return plan


def underwriting_estimate_for_plan(plan):
    phase = db.get("assessment_phases", plan["basis_assessment_phase_id"])
    confidence = phase["delineation_confidence"] if phase else "SCREENING"
    max_ef = phase["max_exceedance_factor"] if phase else 0
    figures = calc.cost_estimate(plan["cost_lines"], confidence, max_ef,
                                 plan["years_to_construction_start"],
                                 "UNDERWRITING")
    return figures["total_estimate_cents"]


def control_class_for(control_type):
    return ("ENGINEERING" if control_type in ENGINEERING_CONTROL_TYPES
            else "INSTITUTIONAL")
