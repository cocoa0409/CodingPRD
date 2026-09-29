"""Pure derivations: ownership walk, effort arithmetic, scores and postures.

Nothing in this module mutates `version` or `updated_at`; the computed values
are written back onto the record so a read is always consistent with the facts.
Version bookkeeping for a recompute lives in services/cascade.py.
"""

from decimal import Decimal

import db
import util
from errors import ApiError
from services import enums as E


# ============================================================ ownership graph

def ownership_chain(org, strict=False):
    """Walk the chain of control rooted at `org` (PRD 2.10).

    Returns (chain, best_designation, best_depth) where chain[i] is the chain
    member `i` controlling hops above `org`.
    """
    chain = [org]
    visited = {org["id"]}
    best = org.get("own_designation") or "NONE"
    best_depth = 0
    node = org
    depth = 0
    while node.get("parent_organization_id"):
        pct = util.dec(node.get("parent_ownership_pct"))
        if pct is None:
            break
        if util.round2(pct) < E.CONTROL_THRESHOLD_PCT:
            break
        parent = db.organizations.get(node["parent_organization_id"])
        if parent is None:
            break
        if parent["id"] in visited:
            if strict:
                raise ApiError("ERR_OWNERSHIP_CYCLE",
                               "Ownership chain revisits organization %s."
                               % parent["id"])
            break
        visited.add(parent["id"])
        depth += 1
        if depth > E.MAX_OWNERSHIP_DEPTH:
            if strict:
                raise ApiError("ERR_OWNERSHIP_DEPTH_EXCEEDED",
                               "Ownership chain exceeds %d controlling hops."
                               % E.MAX_OWNERSHIP_DEPTH)
            break
        chain.append(parent)
        if (E.DESIGNATION_STRICTNESS[parent.get("own_designation") or "NONE"]
                > E.DESIGNATION_STRICTNESS[best]):
            best = parent.get("own_designation") or "NONE"
            best_depth = depth
        node = parent
    return chain, best, best_depth


def effective_designation(org):
    if org is None:
        return "NONE", 0
    _chain, best, depth = ownership_chain(org)
    return best, depth


def chain_member_at(org, depth):
    chain, _best, _depth = ownership_chain(org)
    if 0 <= depth < len(chain):
        return chain[depth]
    return org


def direct_children(org_id):
    return db.ordered([o for o in db.organizations.values()
                       if o.get("parent_organization_id") == org_id])


def controlled_descendants(org_id):
    """Every organization reachable downward through >=50% ownership hops."""
    found = []
    seen = {org_id}
    frontier = [org_id]
    while frontier:
        current = frontier.pop(0)
        for child in db.ordered(db.organizations.values()):
            if child.get("parent_organization_id") != current:
                continue
            pct = util.dec(child.get("parent_ownership_pct"))
            if pct is None or util.round2(pct) < E.CONTROL_THRESHOLD_PCT:
                continue
            if child["id"] in seen:
                continue
            seen.add(child["id"])
            found.append(child)
            frontier.append(child["id"])
    return found


# ================================================================== training

def training_status(assignment):
    """Derived on every read against the logical clock (PRD 3.9)."""
    if assignment.get("waived_on"):
        return "WAIVED"
    if assignment.get("completed_on"):
        return "COMPLETED"
    due = util.parse_dt(assignment.get("due_on"))
    if due is not None and db.clock_dt() >= due:
        return "EXPIRED"
    return "ASSIGNED"


def has_satisfied_course(investigator_id, course_code):
    for assignment in db.trainings.values():
        if assignment["investigator_id"] != investigator_id:
            continue
        if assignment["course_code"] != course_code:
            continue
        if training_status(assignment) in ("COMPLETED", "WAIVED"):
            return True
    return False


# ============================================================== disclosures

def disclosure_items(disclosure_id):
    return db.ordered([i for i in db.items.values()
                       if i["disclosure_id"] == disclosure_id])


def investigator_disclosures(investigator_id):
    return db.ordered([d for d in db.disclosures.values()
                       if d["investigator_id"] == investigator_id])


def compute_disclosure(disclosure):
    rows = disclosure_items(disclosure["id"])
    disclosure["item_count"] = sum(
        1 for i in rows if i["status"] in ("DECLARED", "VERIFIED", "DISPUTED"))
    disclosure["late_item_count"] = sum(1 for i in rows if i.get("_late_at_create"))
    disclosure["undisclosed_item_count"] = sum(
        1 for i in rows if i["source"] == "INCIDENT_REMEDIATION")

    raw = (E.BASE_SCORE
           - E.UNDISCLOSED_PENALTY * disclosure["undisclosed_item_count"]
           - E.LATE_ITEM_PENALTY * disclosure["late_item_count"]
           - E.REVISION_PENALTY * disclosure["revision_round"])
    raw = max(0, raw)
    if raw >= E.TIER_A_FLOOR:
        tier = "A"
    elif raw >= E.TIER_B_FLOOR:
        tier = "B"
    else:
        tier = "C"
    disclosure["completeness_tier"] = tier
    disclosure["completeness_score"] = max(0, raw - E.TIER_PENALTY[tier])
    return disclosure


def has_disputed_items(disclosure_id):
    return any(i["status"] == "DISPUTED" for i in disclosure_items(disclosure_id))


# ============================================================ item risk points

def item_risk_points(item):
    org = db.organizations.get(item.get("foreign_organization_id"))
    designation, _depth = effective_designation(org)
    base = Decimal(E.ITEM_POINTS[item["item_type"]])
    value = base * E.DESIGNATION_MULTIPLIER[designation]
    if item.get("is_paid"):
        value = value + E.PAID_SURCHARGE
    return util.round_int(value)


def compute_item(item):
    item["item_risk_points"] = item_risk_points(item)
    return item


# ================================================================ investigator

def active_personnel(investigator_id):
    return [p for p in db.personnel.values()
            if p["investigator_id"] == investigator_id and p["status"] == "ACTIVE"]


def scoring_items(investigator_id):
    """VERIFIED items on the investigator's non-REJECTED disclosures."""
    live = {d["id"] for d in db.disclosures.values()
            if d["investigator_id"] == investigator_id
            and d["review_status"] != "REJECTED"}
    return db.ordered([i for i in db.items.values()
                       if i["disclosure_id"] in live and i["status"] == "VERIFIED"])


def investigator_incidents(investigator_id):
    return db.ordered([i for i in db.incidents.values()
                       if i["investigator_id"] == investigator_id])


def investigator_statements(investigator_id):
    return db.ordered([s for s in db.statements.values()
                       if s["investigator_id"] == investigator_id])


def committed_effort_pct(investigator_id):
    total = Decimal("0")
    for row in active_personnel(investigator_id):
        months = util.dec(row["committed_person_months"])
        total += util.round2(months / E.MONTHS_PER_YEAR * Decimal("100"))
    return total


def outside_effort_pct(investigator_id):
    total = Decimal("0")
    for item in scoring_items(investigator_id):
        hours = util.dec(item.get("annual_effort_hours") or 0)
        total += util.round2(hours / E.ANNUAL_HOURS_BASE * Decimal("100"))
    return total


def active_plan_credit_disclosure(investigator_id):
    """An acknowledged plan still ahead of the logical clock, if any."""
    now = db.clock_dt()
    for disclosure in investigator_disclosures(investigator_id):
        if disclosure["plan_status"] != "PLAN_ACKNOWLEDGED":
            continue
        expires = util.parse_dt(disclosure.get("plan_expires_on"))
        if expires is not None and now < expires:
            return disclosure
    return None


def risk_score(investigator_id):
    item_subtotal = sum(item_risk_points(i) for i in scoring_items(investigator_id))
    item_subtotal = min(item_subtotal, E.ITEM_POINT_CAP)

    incident_subtotal = 0
    for incident in investigator_incidents(investigator_id):
        if incident.get("finding") == "SUBSTANTIATED":
            incident_subtotal += E.INCIDENT_POINTS.get(incident.get("severity"), 0)

    discrepancy_subtotal = E.DISCREPANCY_POINTS * sum(
        1 for s in investigator_statements(investigator_id)
        if s["status"] == "INCONSISTENT")

    credit = E.PLAN_CREDIT if active_plan_credit_disclosure(investigator_id) else 0

    total = item_subtotal + incident_subtotal + discrepancy_subtotal - credit
    return max(0, min(100, total))


def substantiated_incident_count(investigator_id):
    return sum(1 for i in investigator_incidents(investigator_id)
               if i.get("finding") == "SUBSTANTIATED")


def material_discrepancy_count(investigator_id):
    return sum(1 for s in investigator_statements(investigator_id)
               if s["status"] == "INCONSISTENT")


def training_compliant(investigator_id):
    for assignment in db.trainings.values():
        if assignment["investigator_id"] != investigator_id:
            continue
        if assignment.get("required_for_project_id") is not None:
            continue
        if training_status(assignment) in ("ASSIGNED", "EXPIRED"):
            return False
    return True


def disclosure_posture(investigator_id, risk, substantiated, discrepancies):
    for incident in investigator_incidents(investigator_id):
        if incident["status"] == "AGENCY_NOTIFIED":
            return "SUSPENDED"
        if incident.get("agency_notified_on"):
            return "SUSPENDED"
        if (incident.get("finding") == "SUBSTANTIATED"
                and incident.get("severity") == "CRITICAL"):
            return "SUSPENDED"
    if substantiated >= 1 or risk >= 60:
        return "RESTRICTED"
    if risk >= 30 or discrepancies >= 1:
        return "REVIEW_REQUIRED"
    for disclosure in investigator_disclosures(investigator_id):
        if disclosure["plan_status"] == "PLAN_REQUIRED":
            return "REVIEW_REQUIRED"
    return "CLEAR"


def compute_investigator(investigator):
    investigator_id = investigator["id"]
    committed = committed_effort_pct(investigator_id)
    outside = outside_effort_pct(investigator_id)
    base = util.dec(investigator["institutional_base_effort_pct"])
    total = base + committed + outside
    investigator["committed_effort_pct"] = committed
    investigator["outside_effort_pct"] = outside
    investigator["total_commitment_pct"] = total
    investigator["overcommitment_pct"] = util.round2(
        max(Decimal("0"), total - E.FULL_COMMITMENT_PCT))

    risk = risk_score(investigator_id)
    substantiated = substantiated_incident_count(investigator_id)
    discrepancies = material_discrepancy_count(investigator_id)
    investigator["risk_score"] = risk
    investigator["substantiated_incident_count"] = substantiated
    investigator["material_discrepancy_count"] = discrepancies
    investigator["training_compliant"] = training_compliant(investigator_id)
    investigator["disclosure_posture"] = disclosure_posture(
        investigator_id, risk, substantiated, discrepancies)
    return investigator


def posture_of(investigator):
    compute_investigator(investigator)
    return investigator["disclosure_posture"]


def projected_total_commitment(investigator, extra_person_months):
    """total_commitment_pct as it would read with one more ACTIVE row."""
    compute_investigator(investigator)
    extra = util.round2(util.dec(extra_person_months) / E.MONTHS_PER_YEAR
                        * Decimal("100"))
    return util.dec(investigator["total_commitment_pct"]) + extra


# ===================================================================== project

def project_personnel(project_id):
    return db.ordered([p for p in db.personnel.values()
                       if p["project_id"] == project_id])


def project_subawards(project_id):
    return db.ordered([s for s in db.subawards.values()
                       if s["project_id"] == project_id])


def project_grants(project_id):
    return db.ordered([g for g in db.grants.values()
                       if g["project_id"] == project_id])


def project_incidents(project_id):
    return db.ordered([i for i in db.incidents.values()
                       if i.get("project_id") == project_id])


def project_statements(project_id):
    return db.ordered([s for s in db.statements.values()
                       if s.get("project_id") == project_id])


def project_trainings(project_id):
    return db.ordered([t for t in db.trainings.values()
                       if t.get("required_for_project_id") == project_id])


def active_grant_count(project_id):
    return sum(1 for g in project_grants(project_id) if g["status"] == "ACTIVE")


def open_incident_count(project_id):
    return sum(1 for i in project_incidents(project_id)
               if i["status"] in ("REPORTED", "INVESTIGATING", "SUBSTANTIATED"))


def has_certified_disclosure(investigator_id):
    return any(d["review_status"] == "CERTIFIED"
               for d in investigator_disclosures(investigator_id))


def activation_blockers(project):
    project_id = project["id"]
    found = set()
    if project["security_status"] != "CLEARED":
        found.add("SECURITY_NOT_CLEARED")

    active_rows = [p for p in project_personnel(project_id)
                   if p["status"] == "ACTIVE"]
    for row in active_rows:
        investigator = db.investigators.get(row["investigator_id"])
        if investigator is None:
            continue
        if not has_certified_disclosure(investigator["id"]):
            found.add("DISCLOSURE_NOT_CERTIFIED")
        if posture_of(investigator) == "SUSPENDED":
            found.add("INVESTIGATOR_SUSPENDED")

    for assignment in project_trainings(project_id):
        if training_status(assignment) in ("ASSIGNED", "EXPIRED"):
            found.add("TRAINING_INCOMPLETE")
            break

    for subaward in project_subawards(project_id):
        if subaward["status"] in ("PENDING", "FLAGGED", "BLOCKED"):
            found.add("SUBAWARD_BLOCKED")
            break

    for statement in project_statements(project_id):
        if statement["status"] == "INCONSISTENT":
            found.add("SUPPORT_INCONSISTENT")
            break

    if not any(p["role_on_project"] == "PI" and p["status"] == "ACTIVE"
               for p in project_personnel(project_id)):
        found.add("PERSONNEL_MISSING_PI")

    return [code for code in E.BLOCKER_ORDER if code in found]


def controlled_area_posture(project):
    if project["security_status"] in ("SUSPENDED", "TERMINATED"):
        return "LOCKED_DOWN"
    if int(project["controlled_area_capacity"]) == 0:
        return "LOCKED_DOWN"
    if project["active_grant_count"] >= int(project["controlled_area_capacity"]):
        return "RESTRICTED"
    return "OPEN"


def compute_project(project):
    project["active_grant_count"] = active_grant_count(project["id"])
    project["open_incident_count"] = open_incident_count(project["id"])
    project["activation_blockers"] = activation_blockers(project)
    project["controlled_area_posture"] = controlled_area_posture(project)
    return project


# ================================================== controlled-area capacity

def peak_concurrency(project_id, valid_from, valid_until, exclude_grant_id=None):
    """Half-open peak-occupancy projection (PRD 3.7)."""
    candidate_from = util.parse_dt(valid_from)
    candidate_until = util.parse_dt(valid_until)
    occupying = []
    for grant in project_grants(project_id):
        if grant["id"] == exclude_grant_id:
            continue
        if grant["status"] not in ("REQUESTED", "ACTIVE", "SUSPENDED"):
            continue
        other_from = util.parse_dt(grant["valid_from"])
        other_until = util.parse_dt(grant["valid_until"])
        if other_from is None or other_until is None:
            continue
        if other_from < candidate_until and candidate_from < other_until:
            occupying.append((other_from, other_until))

    instants = [candidate_from]
    inside = sorted({start for start, _ in occupying
                     if candidate_from < start < candidate_until})
    instants.extend(inside)

    peak = 0
    for instant in instants:
        live = 1 + sum(1 for start, end in occupying
                       if start <= instant < end)
        peak = max(peak, live)
    return peak


# ============================================================ travel projection

def travel_conflicts(registration):
    """Closed-interval overlap against the traveller's live registrations."""
    depart = util.parse_dt(registration["depart_on"])
    ret = util.parse_dt(registration["return_on"])
    for other in db.travel.values():
        if other["id"] == registration["id"]:
            continue
        if other["investigator_id"] != registration["investigator_id"]:
            continue
        if other["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        other_depart = util.parse_dt(other["depart_on"])
        other_return = util.parse_dt(other["return_on"])
        if other_depart is None or other_return is None:
            continue
        if depart <= other_return and ret >= other_depart:
            return True
    return False


def compute_travel_device(registration):
    flags = 0
    if registration["destination_country_code"] in E.HIGH_RISK_COUNTRIES:
        flags += 1
    host_id = registration.get("host_organization_id")
    if host_id:
        host = db.organizations.get(host_id)
        designation, _depth = effective_designation(host)
        if E.DESIGNATION_STRICTNESS[designation] >= E.HOST_STRICTNESS_FLOOR:
            flags += 1
    project_id = registration.get("project_id")
    if project_id:
        project = db.projects.get(project_id)
        if project is not None and project["sensitivity_level"] in (
                "CONTROLLED", "RESTRICTED"):
            flags += 1
    investigator = db.investigators.get(registration["investigator_id"])
    if investigator is not None and posture_of(investigator) in (
            "RESTRICTED", "SUSPENDED"):
        flags += 1

    if not registration.get("carries_institutional_device") and flags == 0:
        tier = "NONE"
    elif flags <= 1:
        tier = "STANDARD"
    elif flags <= 3:
        tier = "LOANER_REQUIRED"
    else:
        tier = "LOANER_PLUS_ESCORT"

    registration["risk_flag_count"] = flags
    registration["device_requirement_tier"] = tier
    registration["briefing_required"] = tier in ("LOANER_REQUIRED",
                                                 "LOANER_PLUS_ESCORT")
    return registration


# ========================================================== incident severity

def freeze_severity(incident):
    points = E.TYPE_POINTS[incident["incident_type"]]
    project = db.projects.get(incident.get("project_id")) \
        if incident.get("project_id") else None
    if project is not None:
        if project["award_status"] == "ACTIVE":
            points += E.ACTIVE_AWARD_SURCHARGE
        if project["sensitivity_level"] == "RESTRICTED":
            points += E.RESTRICTED_PROJECT_SURCHARGE
    priors = sum(1 for other in investigator_incidents(incident["investigator_id"])
                 if other["id"] != incident["id"]
                 and other.get("finding") == "SUBSTANTIATED")
    points += min(E.PRIOR_INCIDENT_POINTS * priors, E.PRIOR_INCIDENT_CAP)

    if points < E.MODERATE_FLOOR:
        severity = "LOW"
    elif points < E.HIGH_FLOOR:
        severity = "MODERATE"
    elif points < E.CRITICAL_FLOOR:
        severity = "HIGH"
    else:
        severity = "CRITICAL"

    incident["severity_points"] = points
    incident["severity"] = severity
    substantiated = util.parse_dt(incident["substantiated_at"])
    incident["notification_due_on"] = util.fmt_dt(
        util.plus_days(substantiated, E.NOTIFICATION_DAYS[severity]))
    return incident
