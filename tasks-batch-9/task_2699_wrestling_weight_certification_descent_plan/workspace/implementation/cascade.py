"""Cascade primitives.

PRD 2.10: every hop of a cascade is applied inside the same request,
immediately and completely, and every row a cascade touches has its
updated_at refreshed and its version incremented.
"""

from datetime import timedelta

import calc
import lookups
import serialize
from calc import D, r1
from store import (
    DB,
    clock_date,
    clock_iso,
    fmt_date,
    new_row,
    parse_date,
    touch,
)

SEVERITY = {
    "HYDRATION_FAIL": 1,
    "RAPID_LOSS": 2,
    "PLAN_BREACH": 3,
    "WEIGH_IN_DEFICIT": 4,
}


# --------------------------------------------------------------------------
# health flags and team posture
# --------------------------------------------------------------------------

def raise_flag(wrestler, source, weigh_in_id=None):
    row = new_row()
    row.update({
        "wrestler_id": wrestler["id"],
        "weigh_in_id": weigh_in_id,
        "source": source,
        "severity": SEVERITY[source],
        "status": "OPEN",
        "raised_at": clock_iso(),
        "review_note": None,
        "reviewer_user_id": None,
    })
    DB.flags[row["id"]] = row
    # The ledger and the derived posture are recomputed from the flag rows on
    # read; the only stored consequence of a raise is the probation demotion.
    demote_on_probation(wrestler.get("team_id"))
    return row


def demote_on_probation(team_id):
    """Any ELIGIBLE wrestler of a team that has just landed on PROBATION
    is demoted to RESTRICTED."""
    if team_id is None:
        return
    if serialize.team_posture(team_id) != "PROBATION":
        return
    for wrestler in lookups.wrestlers_of_team(team_id):
        if wrestler.get("eligibility_status") == "ELIGIBLE":
            wrestler["eligibility_status"] = "RESTRICTED"
            touch(wrestler)


def restore_from_probation(team_id, was_probation):
    """The compensating action: leaving PROBATION returns every RESTRICTED,
    CERTIFIED wrestler of the team to ELIGIBLE."""
    if team_id is None or not was_probation:
        return
    if serialize.team_posture(team_id) == "PROBATION":
        return
    for wrestler in lookups.wrestlers_of_team(team_id):
        if (wrestler.get("eligibility_status") == "RESTRICTED"
                and wrestler.get("certification_status") == "CERTIFIED"):
            wrestler["eligibility_status"] = "ELIGIBLE"
            touch(wrestler)


def has_escalated_flag(wrestler_id):
    return any(
        f.get("wrestler_id") == wrestler_id and f.get("status") == "ESCALATED"
        for f in DB.flags.values()
    )


# --------------------------------------------------------------------------
# wrestler certified figures
# --------------------------------------------------------------------------

def refresh_lowest_eligible(wrestler, season):
    """Recompute the wrestler's lowest eligible class as of the clock date.
    This is a derived-figure refresh and does not bump the row's version."""
    if season is None:
        return
    result = calc.lowest_eligible_class_at_date(season, wrestler, clock_date())
    wrestler["lowest_eligible_class_lbs"] = result["lowest_eligible_class_lbs"]


def repoint_wrestler_figures(wrestler, assessment, season):
    """Repoint source_assessment_id and recompute all five certified figures."""
    wrestler["source_assessment_id"] = assessment["id"]
    wrestler["alpha_weight_lbs"] = assessment.get("alpha_weight_lbs")
    wrestler["body_fat_pct"] = assessment.get("body_fat_pct")
    wrestler["minimum_certified_weight_lbs"] = assessment.get("minimum_certified_weight_lbs")
    wrestler["min_weight_class_lbs"] = assessment.get("min_weight_class_lbs")
    refresh_lowest_eligible(wrestler, season)


def clear_wrestler_figures(wrestler, hold_reason):
    wrestler["source_assessment_id"] = None
    wrestler["alpha_weight_lbs"] = None
    wrestler["body_fat_pct"] = None
    wrestler["minimum_certified_weight_lbs"] = None
    wrestler["min_weight_class_lbs"] = None
    wrestler["lowest_eligible_class_lbs"] = None
    wrestler["certification_hold_reason"] = hold_reason


# --------------------------------------------------------------------------
# plans, milestones and entries
# --------------------------------------------------------------------------

def cancel_plans(wrestler_id, statuses, reason):
    cancelled = []
    for plan in lookups.plans_of_wrestler(wrestler_id):
        if plan.get("status") in statuses:
            plan["status"] = "CANCELLED"
            plan["cancel_reason"] = reason
            touch(plan)
            cancelled.append(plan)
    return cancelled


def scratch_entries(wrestler_id, statuses, reason, event_statuses=None):
    scratched = []
    for entry in lookups.entries_of_wrestler(wrestler_id):
        if entry.get("status") not in statuses:
            continue
        if event_statuses is not None:
            event = DB.events.get(entry.get("event_id"))
            if event is None or event.get("status") not in event_statuses:
                continue
        entry["status"] = "SCRATCHED"
        entry["scratch_reason"] = reason
        touch(entry)
        scratched.append(entry)
    return scratched


def generate_milestones(plan, wrestler, season, weights, start_date, base_index=0):
    """Create one DescentMilestone per week index of the projection."""
    min_cert = wrestler.get("minimum_certified_weight_lbs")
    created = []
    for offset, allowable in enumerate(weights):
        floor = allowable
        if min_cert is not None and D(min_cert) > D(allowable):
            floor = min_cert
        row = new_row()
        row.update({
            "plan_id": plan["id"],
            "week_index": base_index + offset,
            "effective_date": fmt_date(start_date + timedelta(days=7 * offset)),
            "allowable_weight_lbs": allowable,
            "min_eligible_class_lbs": calc.smallest_class_at_least(season, floor),
            "status": "SCHEDULED",
            "evaluated_recorded_weight_lbs": None,
        })
        DB.milestones[row["id"]] = row
        created.append(row)
    return created


def refresh_latest_effective_weight(entry):
    """The recorded weight of the entry's passing weigh-in with the greatest
    day_index, ties broken by created_at ascending.  A FAIL never overwrites."""
    passing = [
        w for w in lookups.weighins_of_entry(entry["id"])
        if w.get("result") in ("PASS", "PASS_WITH_ALLOWANCE")
    ]
    if not passing:
        return
    passing.sort(key=lambda w: (
        int(w.get("day_index") or 0),
        w.get("created_at") or "",
        w.get("_seq") or 0,
    ))
    best_day = int(passing[-1].get("day_index") or 0)
    tied = [w for w in passing if int(w.get("day_index") or 0) == best_day]
    tied.sort(key=lambda w: (w.get("created_at") or "", w.get("_seq") or 0))
    entry["latest_effective_weight_lbs"] = tied[0].get("recorded_weight_lbs")


def most_recent_weigh_in(entry_id):
    rows = lookups.weighins_of_entry(entry_id)
    if not rows:
        return None
    rows.sort(key=lambda w: (
        int(w.get("day_index") or 0),
        w.get("created_at") or "",
        w.get("_seq") or 0,
    ))
    return rows[-1]


# --------------------------------------------------------------------------
# seeding
# --------------------------------------------------------------------------

def reseed_classes(event, class_values, skip_entry_id=None):
    """Renumber the named class groups to a contiguous run beginning at 1."""
    for class_lbs in sorted({int(c) for c in class_values}):
        group = [
            e for e in lookups.entries_of_event(event["id"])
            if e.get("status") == "SEEDED" and int(e.get("weight_class_lbs")) == int(class_lbs)
        ]
        group.sort(key=calc.seed_rank_key)
        for index, entry in enumerate(group, start=1):
            if entry.get("seed_number") != index:
                entry["seed_number"] = index
                if entry["id"] != skip_entry_id:
                    touch(entry)


# --------------------------------------------------------------------------
# the season compliance run (PRD 3.6)
# --------------------------------------------------------------------------

def compliance_run(season):
    team_ids = {t["id"] for t in lookups.teams_of_season(season["id"])}
    plans = [
        p for p in DB.plans.values()
        if p.get("status") == "CERTIFIED"
        and (DB.wrestlers.get(p.get("wrestler_id")) or {}).get("team_id") in team_ids
    ]
    plans.sort(key=lambda p: (p.get("created_at") or "", p.get("_seq") or 0))
    today = clock_date()
    breach_limit = int(season.get("plan_breach_limit"))

    for plan in plans:
        wrestler = DB.wrestlers.get(plan.get("wrestler_id"))
        if wrestler is None:
            continue
        milestones = lookups.milestones_of_plan(plan["id"])
        milestones.sort(key=lambda m: int(m.get("week_index") or 0))
        for milestone in milestones:
            if milestone.get("status") != "SCHEDULED":
                continue
            effective = parse_date(milestone.get("effective_date"))
            if effective is None or effective > today:
                continue
            weigh_in = calc.qualifying_weigh_in(wrestler["id"], effective)
            if weigh_in is None:
                milestone["status"] = "MISSED"
                milestone["evaluated_recorded_weight_lbs"] = None
            else:
                recorded = weigh_in.get("recorded_weight_lbs")
                milestone["evaluated_recorded_weight_lbs"] = recorded
                if D(recorded) <= D(milestone.get("allowable_weight_lbs")):
                    milestone["status"] = "MET"
                else:
                    milestone["status"] = "MISSED"
            touch(milestone)

        total, missed = serialize.plan_milestone_counts(plan["id"])
        if missed >= breach_limit:
            plan["status"] = "BREACHED"
            plan["breach_count"] = int(plan.get("breach_count") or 0) + 1
            touch(plan)
            raise_flag(wrestler, "PLAN_BREACH")
        else:
            rows = lookups.milestones_of_plan(plan["id"])
            complete = rows and all(m.get("status") in ("MET", "WAIVED") for m in rows)
            expected = (plan.get("total_weeks") or 0) + 1
            if complete and total == expected:
                plan["status"] = "COMPLETED"
                touch(plan)


# --------------------------------------------------------------------------
# the audit-failure cascade (PRD 3.9, five hops)
# --------------------------------------------------------------------------

def audit_fail_cascade(audit, season):
    assessor = DB.assessors.get(audit.get("assessor_id"))
    if assessor is None:
        return

    # hop 1 -- the assessor loses the credential
    if assessor.get("status") == "CERTIFIED":
        assessor["status"] = "SUSPENDED"
        assessor["suspension_reason"] = "AUDIT_FAIL:%s" % audit["id"]
        touch(assessor)

    window_start = parse_date(audit.get("sample_window_start"))
    void_reason = "AUDIT_FAIL:%s" % audit["id"]

    # hop 2 -- their validated work inside the sample window is voided
    voided = []
    rows = lookups.assessments_of_assessor(assessor["id"])
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    for assessment in rows:
        if assessment.get("status") != "VALIDATED":
            continue
        assessed = assessment.get("_assessed_date")
        if window_start is not None and (assessed is None or assessed < window_start):
            continue
        assessment["status"] = "VOIDED"
        assessment["void_reason"] = void_reason
        touch(assessment)
        voided.append(assessment)
        audit["voided_assessment_count"] = int(audit.get("voided_assessment_count") or 0) + 1
        for appeal in lookups.appeals_of_assessment(assessment["id"]):
            if appeal.get("status") in ("SUBMITTED", "UNDER_REVIEW",
                                        "RETEST_ORDERED", "RETEST_COMPLETED"):
                appeal["status"] = "WITHDRAWN"
                appeal["decision_note"] = "WITHDRAWN_ASSESSMENT_VOIDED"
                touch(appeal)

    if not voided:
        return

    voided_ids = {a["id"] for a in voided}

    # hop 3 -- wrestlers sourced from a voided assessment are suspended
    wrestlers = [
        w for w in DB.wrestlers.values()
        if w.get("source_assessment_id") in voided_ids
    ]
    wrestlers.sort(key=lambda w: (w.get("created_at") or "", w.get("_seq") or 0))
    for wrestler in wrestlers:
        previous = wrestler.get("certification_status")
        if previous not in ("CERTIFIED", "PROVISIONAL"):
            continue
        wrestler["certification_status"] = "SUSPENDED"
        clear_wrestler_figures(wrestler, "SOURCE_ASSESSMENT_VOIDED")
        wrestler["eligibility_status"] = "INELIGIBLE"
        touch(wrestler)

        if previous == "CERTIFIED":
            # hop 4 -- the certified plan is cancelled
            cancel_plans(wrestler["id"], ("CERTIFIED",), "WRESTLER_SUSPENDED")
            # hop 5 -- live entries on live events are scratched
            scratch_entries(
                wrestler["id"],
                ("ENTERED", "WEIGHED_IN", "SEEDED"),
                "PLAN_CANCELLED",
                event_statuses=("SCHEDULED", "WEIGH_IN_OPEN", "WEIGH_IN_CLOSED", "SEEDED"),
            )
        else:
            cancel_plans(wrestler["id"], ("DRAFT",), "WRESTLER_SUSPENDED")
