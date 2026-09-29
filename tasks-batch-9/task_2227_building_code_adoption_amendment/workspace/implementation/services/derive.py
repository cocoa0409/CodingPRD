"""Derived (source: computed) fields plus the seating / ledger recomputations."""
from decimal import Decimal

import clock
import config
import db
from services import calc


# ------------------------------------------------------------------ selections
def children(store, key, value):
    return [row for row in store.values() if row.get(key) == value]


def committee_members_of(committee_id):
    return children(db.committee_members, "committee_id", committee_id)


def proposals_of_cycle(cycle_id):
    return children(db.amendment_proposals, "code_cycle_id", cycle_id)


def analyses_of_proposal(proposal_id):
    return children(db.impact_analyses, "proposal_id", proposal_id)


def comments_of_proposal(proposal_id):
    return children(db.public_comments, "proposal_id", proposal_id)


def enrollments_of_session(session_id):
    return children(db.training_enrollments, "training_session_id", session_id)


# ------------------------------------------------------------------ committee
def active_voting_member_count(committee_id):
    return len([m for m in committee_members_of(committee_id)
                if m["voting_seat"] and m["status"] == "ACTIVE"])


def chair_member_count(committee_id):
    return len([m for m in committee_members_of(committee_id)
                if m["is_chair"] and m["status"] == "ACTIVE"])


def sector_coverage_complete(committee_id):
    sectors = {m["sector"] for m in committee_members_of(committee_id)
               if m["status"] == "ACTIVE"}
    return all(sector in sectors for sector in config.REQUIRED_SECTORS)


def committee_quorum_required(committee_id):
    return calc.quorum_required(active_voting_member_count(committee_id))


def seating_requirements_met(committee):
    threshold = calc.quorum_required(committee["voting_seat_count"])
    return (active_voting_member_count(committee["id"]) >= threshold
            and sector_coverage_complete(committee["id"])
            and chair_member_count(committee["id"]) == 1)


def refresh_committee_seating(committee):
    """FORMING <-> SEATED bubble-up / bubble-down after a membership change."""
    if committee["status"] == "DISSOLVED":
        return
    met = seating_requirements_met(committee)
    if committee["status"] == "FORMING" and met:
        committee["status"] = "SEATED"
        db.touch(committee)
    elif committee["status"] == "SEATED" and not met:
        committee["status"] = "FORMING"
        db.touch(committee)
        cancel_scheduled_hearings(committee["id"])


def cancel_scheduled_hearings(committee_id):
    for hearing in db.ordered(children(db.hearings, "committee_id", committee_id)):
        if hearing["status"] == "SCHEDULED":
            hearing["status"] = "CANCELLED"
            hearing["agenda_proposal_ids"] = []
            db.touch(hearing)


def seated_committee_count(cycle_id):
    return len([c for c in children(db.discipline_committees, "code_cycle_id", cycle_id)
                if c["status"] == "SEATED"])


# ------------------------------------------------------------------ proposal
def energy_analysis_required(proposal):
    return (proposal["discipline"] == "ENERGY"
            or proposal["stringency_direction"] == "MORE_STRINGENT")


def comment_tallies(proposal):
    support = oppose = total = 0
    for comment in comments_of_proposal(proposal["id"]):
        if comment["comment_round"] != proposal["comment_round"]:
            continue
        total += 1
        if comment["position"] == "SUPPORT":
            support += 1
        elif comment["position"] == "OPPOSE":
            oppose += 1
    return support, oppose, total


def accepted_analysis(proposal_id, analysis_type):
    for analysis in analyses_of_proposal(proposal_id):
        if analysis["analysis_type"] == analysis_type and analysis["status"] == "ACCEPTED":
            return analysis
    return None


# ------------------------------------------------------------------ cycle ledger
def approved_proposals_of_cycle(cycle_id):
    return [p for p in proposals_of_cycle(cycle_id) if p["review_status"] == "APPROVED"]


def cycle_ledger(cycle_id):
    approved = approved_proposals_of_cycle(cycle_id)
    cost = sum(int(p["statewide_incremental_cost_cents"] or 0) for p in approved)
    permits = sum(int(p["affected_permit_count"] or 0) for p in approved)
    return {
        "approved_proposal_count": len(approved),
        "approved_incremental_cost_cents": cost,
        "approved_permit_backlog_count": permits,
    }


def refresh_draft_adoption_rules(cycle_id):
    """Any DRAFT order of the cycle re-derives its schedule from the fresh backlog."""
    ledger = cycle_ledger(cycle_id)
    for rule in db.ordered(children(db.adoption_rules, "code_cycle_id", cycle_id)):
        if rule["status"] != "DRAFT":
            continue
        schedule = calc.adoption_schedule(rule["base_date"],
                                          ledger["approved_permit_backlog_count"])
        if any(rule.get(key) != value for key, value in schedule.items()):
            rule.update(schedule)
            db.touch(rule)


# ------------------------------------------------------------------ jurisdiction
def _building_official_rows(jurisdiction_id):
    rows = []
    for enrollment in db.training_enrollments.values():
        if enrollment["jurisdiction_id"] != jurisdiction_id:
            continue
        if enrollment["attendee_role"] != "BUILDING_OFFICIAL":
            continue
        session = db.training_sessions.get(enrollment["training_session_id"])
        if session is None or session["status"] == "CANCELLED":
            continue
        rows.append(enrollment)
    return rows


def jurisdiction_compliance(jurisdiction):
    rows = _building_official_rows(jurisdiction["id"])
    enrolled_names = {r["attendee_name"] for r in rows
                      if r["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW")}
    attended_names = {r["attendee_name"] for r in rows if r["status"] == "ATTENDED"}
    headcount = jurisdiction["official_headcount"]
    enrollment_pct = calc.compliance_pct(len(enrolled_names), headcount)
    attendance_pct = calc.compliance_pct(len(attended_names), headcount)
    readiness = "READY" if attendance_pct >= config.READINESS_THRESHOLD_PCT else "NOT_READY"
    return enrollment_pct, attendance_pct, readiness


def effective_local_amendment_count(jurisdiction_id):
    return len([la for la in db.local_amendments.values()
                if la["jurisdiction_id"] == jurisdiction_id
                and la["status"] == "FILED_EFFECTIVE"])


def statewide_readiness_pct():
    rows = []
    for jurisdiction in db.jurisdictions.values():
        _, attendance_pct, _ = jurisdiction_compliance(jurisdiction)
        rows.append((jurisdiction["population"], attendance_pct))
    return calc.statewide_readiness(rows)


# ------------------------------------------------------------------ session
def session_counts(session_id):
    enrolled = attended = no_show = 0
    for enrollment in enrollments_of_session(session_id):
        if enrollment["status"] == "ENROLLED":
            enrolled += 1
        elif enrollment["status"] == "ATTENDED":
            attended += 1
        elif enrollment["status"] == "NO_SHOW":
            no_show += 1
    return enrolled, attended, no_show


def session_seats_available(session):
    enrolled, attended, no_show = session_counts(session["id"])
    return session["seat_capacity"] - (enrolled + attended + no_show)
