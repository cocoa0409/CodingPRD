"""Multi-level cascades: reopen (PRD 3.6), vote outcome (3.5), withdrawal (3.7)."""
import clock
import db
from services import calc, derive


# ------------------------------------------------------------------ vote outcome
def apply_vote_outcome(proposal, cycle, outcome):
    """An APPROVED outcome advances the proposal and the cycle ledger."""
    if outcome == "APPROVED":
        proposal["review_status"] = "APPROVED"
        db.touch(proposal)
        if cycle is not None:
            db.touch(cycle)
            derive.refresh_draft_adoption_rules(cycle["id"])
    else:
        proposal["review_status"] = "REJECTED"
        db.touch(proposal)


# ------------------------------------------------------------------ reopen
def reopen_proposal(proposal, cycle):
    was_approved = proposal["review_status"] == "APPROVED"

    # level 1 — the proposal itself
    proposal["review_status"] = "RETURNED_FOR_REVISION"
    proposal["revision_round"] = proposal["revision_round"] + 1
    if proposal["analysis_status"] == "COMPLETE":
        proposal["analysis_status"] = "STALE"

    # level 2 — child analyses
    for analysis in db.ordered(derive.analyses_of_proposal(proposal["id"])):
        if analysis["status"] in ("ACCEPTED", "SUBMITTED"):
            analysis["status"] = "SUPERSEDED"
            db.touch(analysis)

    # level 3 — clear the certified figures
    proposal["statewide_incremental_cost_cents"] = None
    proposal["affected_permit_count"] = None
    proposal["preliminary_benefit_cost_ratio"] = None
    proposal["final_benefit_cost_ratio"] = None
    db.touch(proposal)

    if not was_approved:
        return

    # level 4 — the cycle ledger is compensated (derived from the live rows)
    # level 6 — the compound RULEMAKING gate no longer holds
    if cycle is not None:
        if cycle["status"] == "RULEMAKING":
            cycle["status"] = "DELIBERATION"
        db.touch(cycle)
        # level 5 — DRAFT rulemaking orders re-derive their schedules
        derive.refresh_draft_adoption_rules(cycle["id"])


# ------------------------------------------------------------------ withdrawal
def withdraw_published_rule(rule, reason):
    rule["status"] = "WITHDRAWN"
    rule["withdrawal_reason"] = reason
    db.touch(rule)

    touched_jurisdictions = set()

    # levels 2 and 3 — sessions and their enrollments
    for session in db.ordered(derive.children(db.training_sessions,
                                              "adoption_rule_id", rule["id"])):
        if session["status"] not in ("SCHEDULED", "ENROLLMENT_OPEN",
                                    "ENROLLMENT_CLOSED", "DELIVERED"):
            continue
        session["status"] = "CANCELLED"
        db.touch(session)
        for enrollment in db.ordered(derive.enrollments_of_session(session["id"])):
            if enrollment["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW"):
                enrollment["status"] = "CANCELLED"
                db.touch(enrollment)
                touched_jurisdictions.add(enrollment["jurisdiction_id"])

    # fan-out 1 — local amendments
    for amendment in db.ordered(derive.children(db.local_amendments,
                                                "adoption_rule_id", rule["id"])):
        if amendment["status"] not in ("SUBMITTED", "UNDER_REVIEW",
                                      "RETURNED", "FILED_EFFECTIVE"):
            continue
        was_effective = amendment["status"] == "FILED_EFFECTIVE"
        amendment["status"] = "VOIDED"
        db.touch(amendment)
        if was_effective:
            touched_jurisdictions.add(amendment["jurisdiction_id"])

    # fan-out 2 — interpretation requests
    for request in db.ordered(derive.children(db.interpretation_requests,
                                              "adoption_rule_id", rule["id"])):
        if request["status"] in ("SUBMITTED", "ASSIGNED", "OPINION_DRAFTED"):
            request["status"] = "DECLINED"
            request["decline_reason"] = "underlying rule withdrawn"
            db.touch(request)

    # levels 4 and 5 — jurisdictions recompute compliance and readiness
    for jurisdiction_id in sorted(touched_jurisdictions):
        jurisdiction = db.jurisdictions.get(jurisdiction_id)
        if jurisdiction is not None:
            db.touch(jurisdiction)


# ------------------------------------------------------------------ session cancel
def cancel_session(session, reason):
    session["status"] = "CANCELLED"
    session["cancellation_reason"] = reason
    db.touch(session)
    for enrollment in db.ordered(derive.enrollments_of_session(session["id"])):
        if enrollment["status"] == "ENROLLED":
            enrollment["status"] = "CANCELLED"
            db.touch(enrollment)


# ------------------------------------------------------------------ effective
def make_rule_effective(rule, cycle, readiness_pct):
    rule["status"] = "EFFECTIVE"
    rule["statewide_readiness_pct_at_effective"] = readiness_pct
    db.touch(rule)
    for other in db.ordered(derive.children(db.adoption_rules,
                                            "code_cycle_id", rule["code_cycle_id"])):
        if other["id"] != rule["id"] and other["status"] == "EFFECTIVE":
            other["status"] = "SUPERSEDED"
            db.touch(other)
    if cycle is not None and cycle["status"] == "RULEMAKING":
        cycle["status"] = "ADOPTED"
        db.touch(cycle)
