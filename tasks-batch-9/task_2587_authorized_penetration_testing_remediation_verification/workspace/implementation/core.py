"""Shared record mechanics: audit stamps, ledgers, posture and the cascades.

PRD 2.4: every mutated record's version advances by exactly 1 per request and
its updated_at is refreshed.  PRD 2.9: cascades are immediate -- by the time the
response is written every touched record already shows its new state.
"""
from decimal import Decimal

from flask import g

import calc
from store import store
from util import dec, q2

ZERO = Decimal("0")


def touched():
    if not hasattr(g, "touched"):
        g.touched = set()
    return g.touched


def touch(rec):
    """Advance version/updated_at once per request for this record."""
    seen = touched()
    if rec["id"] in seen:
        return rec
    seen.add(rec["id"])
    rec["version"] = rec["version"] + 1
    rec["updated_at"] = store.now()
    return rec


def new_record(**fields):
    now = store.now()
    rec = {
        "id": store.new_id(),
        "_seq": store.next_seq(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rec.update(fields)
    return rec


def new_immutable(**fields):
    """Training recommendations carry only id and created_at (PRD 2.4)."""
    rec = {"id": store.new_id(), "_seq": store.next_seq(), "created_at": store.now()}
    rec.update(fields)
    return rec


def ordered(records):
    """Default list ordering: created_at ascending, creation sequence as tie-break."""
    return sorted(records, key=lambda rec: (rec["created_at"], rec["_seq"]))


# ---------------------------------------------------------------- lookups

def plan_scope_items(plan_id):
    return [item for item in store.scope_items.values() if item["test_plan_id"] == plan_id]


def plan_engagements(plan_id):
    return [eng for eng in store.engagements.values() if eng["test_plan_id"] == plan_id]


def engagement_findings(engagement_id):
    return [f for f in store.findings.values() if f["engagement_id"] == engagement_id]


def engagement_assignments(engagement_id):
    return [a for a in store.assignments.values() if a["engagement_id"] == engagement_id]


def engagement_alerts(engagement_id):
    ids = {f["id"] for f in engagement_findings(engagement_id)}
    return [a for a in store.alerts.values() if a["finding_id"] in ids]


def live_roe(engagement_id):
    """The one document an engagement may hold at DRAFT, SIGNED or SUSPENDED."""
    for roe in ordered(list(store.roes.values())):
        if roe["engagement_id"] == engagement_id and roe["status"] in (
            "DRAFT",
            "SIGNED",
            "SUSPENDED",
        ):
            return roe
    return None


def roe_of_engagement(engagement_id):
    """The live document if there is one, else the most recent revoked document."""
    live = live_roe(engagement_id)
    if live is not None:
        return live
    candidates = [r for r in store.roes.values() if r["engagement_id"] == engagement_id]
    if not candidates:
        return None
    return ordered(candidates)[-1]


def roe_targets(roe_id):
    return ordered([t for t in store.targets.values() if t["roe_id"] == roe_id])


def finding_alerts(finding_id):
    return ordered([a for a in store.alerts.values() if a["finding_id"] == finding_id])


def remediation_retests(remediation_id):
    return ordered([r for r in store.retests.values() if r["remediation_id"] == remediation_id])


def plan_of_engagement(engagement):
    return store.test_plans.get(engagement["test_plan_id"])


def plan_of_finding(finding):
    engagement = store.engagements.get(finding["engagement_id"])
    if engagement is None:
        return None
    return plan_of_engagement(engagement)


# ---------------------------------------------------------------- plan derived values

def coverage_value(plan):
    """Distinct tier-1/2 assets this plan holds APPROVED or CONSUMED candidates for."""
    covered = set()
    for item in plan_scope_items(plan["id"]):
        if item["status"] not in ("APPROVED", "CONSUMED"):
            continue
        asset = store.assets.get(item["asset_id"])
        if asset is None:
            continue
        if int(asset["criticality_tier"]) in (1, 2):
            covered.add(asset["id"])
    return calc.coverage_score(list(store.assets.values()), covered)


def recompute_coverage(plan):
    plan["coverage_score"] = coverage_value(plan)
    return plan["coverage_score"]


RANKED_STATUSES = ("PROPOSED", "APPROVED")


def recompute_ranks(plan_id):
    """Only PROPOSED/APPROVED candidates are ranked; every other rank is null."""
    population = []
    for item in plan_scope_items(plan_id):
        if item["status"] in RANKED_STATUSES:
            population.append(item)
        else:
            item["priority_rank"] = None
    population.sort(
        key=lambda item: (
            -item["priority_score"],
            dec(item["requested_engagement_hours"]),
            item["created_at"],
            item["_seq"],
        )
    )
    for index, item in enumerate(population, start=1):
        item["priority_rank"] = index


def score_scope_item(item, plan):
    asset = store.assets[item["asset_id"]]
    mode = plan["prioritization_mode"]
    item["priority_score"] = calc.scope_priority_score(asset, mode, store.now())
    item["scored_mode"] = mode
    item["below_threshold_flag"] = item["priority_score"] < dec(plan["admission_threshold"])


def ledger_move(plan, source, target, points):
    """Points only ever move between buckets; the total is never touched."""
    if source is not None:
        plan[source] = plan[source] - points
    if target is not None:
        plan[target] = plan[target] + points
    touch(plan)


def bubble_up(plan):
    """A plan is never closed by a direct call (PRD 2.9 / 3.9)."""
    if plan is None or plan["status"] != "ACTIVE":
        return
    engagements = plan_engagements(plan["id"])
    if not engagements:
        return
    for engagement in engagements:
        if engagement["execution_state"] != "CLOSED":
            return
    plan["status"] = "CLOSED"
    touch(plan)


# ---------------------------------------------------------------- asset posture

def asset_open_delta(asset, finding, delta):
    """Keep the asset counters true and cycle the exposure posture (PRD 3.1)."""
    asset["open_finding_count"] = max(0, asset["open_finding_count"] + delta)
    critical = finding["severity_band"] == "CRITICAL"
    if critical:
        asset["open_critical_finding_count"] = max(
            0, asset["open_critical_finding_count"] + delta
        )
        if delta > 0:
            if (
                asset["open_critical_finding_count"] >= 1
                and asset["exposure_state"] in ("MONITORED", "CLEARED")
            ):
                asset["exposure_state"] = "ELEVATED"
        elif delta < 0:
            if asset["open_critical_finding_count"] == 0 and asset["exposure_state"] == "ELEVATED":
                asset["exposure_state"] = "CLEARED"
                asset["last_cleared_at"] = store.now()
    touch(asset)


# ---------------------------------------------------------------- hour ledger

def recompute_hours(engagement):
    engagement["hours_available"] = q2(
        dec(engagement["hours_allocated"])
        - dec(engagement["hours_reserved"])
        - dec(engagement["hours_consumed"])
    )


def revoke_assignment(assignment):
    """The single settlement path; reachable four ways (PRD 3.5)."""
    now = store.now()
    engagement = store.engagements[assignment["engagement_id"]]
    tester = store.testers[assignment["tester_id"]]
    was_provisioned = assignment["access_state"] == "PROVISIONED"
    assignment["revoked_at"] = now
    if was_provisioned:
        assignment["settled_hours"] = calc.settled_hours(assignment, now)
    else:
        assignment["settled_hours"] = ZERO
    assignment["access_state"] = "REVOKED"
    touch(assignment)
    engagement["hours_reserved"] = q2(
        dec(engagement["hours_reserved"]) - dec(assignment["requested_hours"])
    )
    engagement["hours_consumed"] = q2(
        dec(engagement["hours_consumed"]) + dec(assignment["settled_hours"])
    )
    recompute_hours(engagement)
    touch(engagement)
    if was_provisioned:
        tester["active_assignment_count"] = max(0, tester["active_assignment_count"] - 1)
        if tester["active_assignment_count"] == 0 and tester["availability_state"] == "ASSIGNED":
            tester["availability_state"] = "AVAILABLE"
        touch(tester)


def revoke_live_assignments(engagement_id):
    """Closing or terminating revokes every grant still REQUESTED or PROVISIONED."""
    for assignment in ordered(engagement_assignments(engagement_id)):
        if assignment["access_state"] in ("REQUESTED", "PROVISIONED"):
            revoke_assignment(assignment)


# ---------------------------------------------------------------- assurance

def stamp_provisional_assurance(engagement):
    engagement["provisional_assurance_score"] = calc.assurance_score(
        engagement_findings(engagement["id"]), "PROVISIONAL"
    )


def stamp_final_assurance(engagement):
    engagement["final_assurance_score"] = calc.assurance_score(
        engagement_findings(engagement["id"]), "FINAL"
    )


# ---------------------------------------------------------------- suspension cascades

def cascade_pause(engagement, reason):
    """The six-link chain of PRD 2.9 / 3.9.  The execution axis is untouched."""
    engagement["authorization_state"] = "SUSPENDED"
    engagement["suspension_reason"] = reason
    touch(engagement)
    roe = live_roe(engagement["id"])
    suspended_assets = set()
    if roe is not None:
        if roe["status"] == "SIGNED":
            roe["status"] = "SUSPENDED"
            touch(roe)
        for target in roe_targets(roe["id"]):
            if target["state"] == "ACTIVE":
                target["state"] = "SUSPENDED"
                touch(target)
                roe["active_target_count"] = max(0, roe["active_target_count"] - 1)
                touch(roe)
                suspended_assets.add(target["asset_id"])
    for assignment in ordered(engagement_assignments(engagement["id"])):
        if assignment["access_state"] != "PROVISIONED":
            continue
        if not suspended_assets.intersection(set(assignment["granted_asset_ids"])):
            continue
        revoke_assignment(assignment)


def cascade_terminate(engagement, reason):
    """Terminal on both axes: the document is revoked and every target suspended."""
    engagement["suspension_reason"] = reason
    engagement["authorization_state"] = "TERMINATED"
    touch(engagement)
    roe = live_roe(engagement["id"])
    if roe is not None:
        roe["status"] = "REVOKED"
        touch(roe)
        for target in roe_targets(roe["id"]):
            if target["state"] != "SUSPENDED":
                target["state"] = "SUSPENDED"
                touch(target)
        roe["active_target_count"] = 0
    revoke_live_assignments(engagement["id"])
    engagement["execution_state"] = "CLOSED"
    stamp_final_assurance(engagement)
    touch(engagement)
    bubble_up(plan_of_engagement(engagement))


def cascade_resume(engagement):
    """Excluded targets are decisions, not side effects: they are never revived."""
    engagement["authorization_state"] = "AUTHORIZED"
    engagement["suspension_reason"] = None
    touch(engagement)
    roe = live_roe(engagement["id"])
    if roe is not None:
        if roe["status"] == "SUSPENDED":
            roe["status"] = "SIGNED"
            touch(roe)
        for target in roe_targets(roe["id"]):
            if target["state"] == "SUSPENDED":
                target["state"] = "ACTIVE"
                touch(target)
                roe["active_target_count"] = roe["active_target_count"] + 1
                touch(roe)


# ---------------------------------------------------------------- closure cascade

def cascade_close_finding(finding):
    """Links 3 to 5 of the closure chain: finding closed, ledger and asset adjusted."""
    now = store.now()
    finding["status"] = "CLOSED"
    finding["closed_at"] = now
    touch(finding)
    plan = plan_of_finding(finding)
    if plan is not None:
        ledger_move(plan, "open_risk_points", "closed_risk_points", finding["severity_points"])
    asset = store.assets.get(finding["asset_id"])
    if asset is not None:
        asset_open_delta(asset, finding, -1)
        asset["remediated_finding_count"] = asset["remediated_finding_count"] + 1
        touch(asset)
