"""Shared state-transition cascades (PRD Sections 2.10, 3.2, 3.5, 3.6, 3.8)."""
import calc
import config
import derive
import store

ROSTER_TYPES = ("LEVEL", "COMPLEX")
LIVE_PLAN_STATUSES = ("DRAFT", "ACTIVE", "REVISION_REQUESTED")
LIVE_REPORT_STATUSES = ("PENDING", "FILED", "REJECTED_BY_LEAGUE")

TRANSACTION_TYPE_FOR_REASON = {
    "INITIAL": "OPTIONAL_ASSIGNMENT",
    "LATERAL": "OPTIONAL_ASSIGNMENT",
    "DEMOTION": "OPTIONAL_ASSIGNMENT",
    "PROMOTION": "PROMOTION",
    "REHAB_START": "REHAB_ASSIGNMENT",
}


# ------------------------------------------------------------- report / option year
def create_report(assignment, transaction_type):
    record = store.base_record()
    effective = store.parse_date(assignment["effective_date"])
    deadline = store.add_days(effective, config.FILING_WINDOW_DAYS)
    record.update({
        "assignment_id": assignment["id"],
        "transaction_type": transaction_type,
        "status": "PENDING",
        "initiated_by_user_id": assignment["initiated_by_user_id"],
        "certified_by_user_id": None,
        "filing_deadline": store.iso_date(deadline),
        "filed_at": None,
        "is_late": False,
        "late_fee_cents": 0,
        "refile_count": 0,
        "league_note": None,
    })
    store.reports[record["id"]] = record
    return record


def create_option_year(assignment):
    record = store.base_record()
    effective = store.parse_date(assignment["effective_date"])
    record.update({
        "triggering_assignment_id": assignment["id"],
        "season_year": effective.year,
        "optional_days": assignment["projected_optional_days"],
        "status": "CHARGED",
        "charged_at": store.now_iso(),
    })
    store.option_years[record["id"]] = record
    return record


# --------------------------------------------------------------------- cascades
def lapse_plans(assignment):
    lapsed = []
    for plan in derive.plans_of_assignment(assignment["id"]):
        if plan["status"] in LIVE_PLAN_STATUSES:
            plan["status"] = "LAPSED"
            store.touch(plan)
            lapsed.append(plan)
    return lapsed


def void_reports(assignment):
    for report in derive.reports_of_assignment(assignment["id"]):
        if report["status"] in LIVE_REPORT_STATUSES:
            report["status"] = "VOIDED"
            store.touch(report)


def rescind_option_years(assignment):
    for record in derive.option_years_of_assignment(assignment["id"]):
        if record["status"] == "CHARGED":
            record["status"] = "RESCINDED"
            store.touch(record)


def _release_roster(assignment, restricted=False):
    """Move the player off the roster when their last live level/complex
    assignment leaves ACTIVE."""
    if assignment["assignment_type"] not in ROSTER_TYPES:
        return
    player = store.players.get(assignment["player_id"])
    if player is None:
        return
    remaining = [a for a in derive.assignments_of_player(player["id"])
                 if a["id"] != assignment["id"]
                 and a["status"] == "ACTIVE"
                 and a["assignment_type"] in ROSTER_TYPES]
    if remaining:
        return
    player["roster_status"] = "RESTRICTED" if restricted else "RESERVE_LIST"


def suspend_assignment(assignment, by_clearance_revocation=False):
    assignment["status"] = "SUSPENDED"
    store.touch(assignment)
    _release_roster(assignment, restricted=by_clearance_revocation)


def revoke_assignment(assignment):
    """REVOKE from PENDING_CLEARANCE, ACTIVE or SUSPENDED."""
    previous = assignment["status"]
    assignment["status"] = "REVOKED"
    store.touch(assignment)
    lapse_plans(assignment)
    if previous == "PENDING_CLEARANCE":
        return
    rescind_option_years(assignment)
    void_reports(assignment)
    create_report(assignment, "REVOCATION")
    _release_roster(assignment)


def complete_assignment(assignment):
    assignment["status"] = "COMPLETED"
    store.touch(assignment)
    if assignment["assignment_type"] == "REHAB":
        create_report(assignment, "REHAB_COMPLETE")
    lapse_plans(assignment)
    _release_roster(assignment)


def cascade_agreement_suspended(affiliate_id):
    for assignment in derive.assignments_of_affiliate(affiliate_id):
        if assignment["status"] == "ACTIVE":
            suspend_assignment(assignment)


def cascade_agreement_terminated(affiliate_id):
    for assignment in store.sorted_rows(derive.assignments_of_affiliate(affiliate_id)):
        if assignment["status"] in ("PENDING_CLEARANCE", "ACTIVE", "SUSPENDED"):
            revoke_assignment(assignment)
    for allocation in store.sorted_rows(derive.allocations_of_affiliate(affiliate_id)):
        if allocation["status"] in ("PROPOSED", "ACTIVE"):
            allocation["status"] = "RECALLED"
            store.touch(allocation)


def cascade_pool_hard_capped(pool, approved_signing_id):
    for signing in store.sorted_rows(derive.signings_of_pool(pool["id"])):
        if signing["id"] == approved_signing_id:
            continue
        if signing["status"] == "SUBMITTED":
            signing["status"] = "REJECTED"
            signing["rejection_reason"] = "POOL_HARD_CAPPED"
            store.touch(signing)
