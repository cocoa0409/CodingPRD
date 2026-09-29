"""Shared domain mutations: credential gaps, ledgers, and the two named cascades."""
from core import DB, now, now_date, touch
import calc


# ---------------------------------------------------------------------------
# Credential gap maintenance
# ---------------------------------------------------------------------------
def has_cleared_head_coach(school_id, sport):
    for c in DB.credentials.values():
        if c["school_id"] == school_id and c["sport"] == sport \
                and c["role_title"] == "HEAD_COACH" and c["status"] == "CLEARED":
            return True
    return False


def gap_add(school, sport):
    if sport not in school["credential_gap_sports"]:
        school["credential_gap_sports"].append(sport)
        touch(school)
        return True
    return False


def gap_remove(school, sport):
    if sport in school["credential_gap_sports"]:
        school["credential_gap_sports"].remove(sport)
        touch(school)
        return True
    return False


# ---------------------------------------------------------------------------
# Fee ledger
# ---------------------------------------------------------------------------
def recompute_outstanding(case):
    case["fee_outstanding_cents"] = (case["fee_amount_cents"]
                                     - case["fee_paid_cents"]
                                     - case["fee_waived_cents"]
                                     + case["fee_refunded_cents"])
    return case["fee_outstanding_cents"]


def school_of_case(case):
    student = DB.students.get(case["student_id"])
    if student is None:
        return None
    return DB.schools.get(student["school_id"])


# ---------------------------------------------------------------------------
# Officials / transport unwinding helpers
# ---------------------------------------------------------------------------
def withdraw_assignments(contest):
    for a in DB.assignments.values():
        if a["contest_id"] != contest["id"]:
            continue
        if a["status"] not in ("OFFERED", "ACCEPTED"):
            continue
        was_accepted = a["status"] == "ACCEPTED"
        a["status"] = "WITHDRAWN"
        a["stipend_cents"] = None
        touch(a)
        if was_accepted:
            official = DB.officials.get(a["official_id"])
            if official is not None:
                official["accepted_assignment_count"] = max(
                    0, official["accepted_assignment_count"] - 1)
                touch(official)


def cancel_trips(contest, statuses, reason="CONTEST_HOLD_CASCADE"):
    for t in DB.transports.values():
        if t["contest_id"] != contest["id"]:
            continue
        if t["status"] not in statuses:
            continue
        was_approved = t["status"] == "APPROVED"
        t["status"] = "CANCELLED"
        t["cancelled_reason"] = reason
        touch(t)
        if was_approved:
            school = DB.schools.get(t["requesting_school_id"])
            if school is not None:
                school["release_minutes_used"] -= t["release_minutes"]
                touch(school)


# ---------------------------------------------------------------------------
# CASCADE A: credential revocation / expiry
# ---------------------------------------------------------------------------
def cascade_a(credential, school):
    """Links 2-4. Called only when link 1 actually opened a coaching gap."""
    sport = credential["sport"]
    clock = now()
    affected = []
    for c in DB.contests.values():
        if c["home_school_id"] != school["id"]:
            continue
        season = DB.seasons.get(c["sport_season_id"])
        if season is None or season["sport"] != sport:
            continue
        if c["status"] not in ("OFFICIALS_ASSIGNED", "CONFIRMED"):
            continue
        if not (c["starts_at"] > clock):
            continue
        affected.append(c)

    for c in affected:
        # LINK 2
        c["status"] = "SCHEDULED"
        c["hold_reason"] = "COACH_CREDENTIAL_REVOKED"
        c["accepted_official_count"] = 0
        touch(c)
        withdraw_assignments(c)
        # LINK 3 + LINK 4
        cancel_trips(c, ("APPROVED",))


def apply_credential_cleared(credential, school):
    """Common side effects when a credential reaches CLEARED."""
    if credential["role_title"] == "HEAD_COACH":
        gap_remove(school, credential["sport"])


def apply_credential_lost(credential, school):
    """Common side effects when a CLEARED credential leaves CLEARED.

    Returns True when a coaching gap was actually opened by this move.
    """
    if credential["role_title"] != "HEAD_COACH":
        return False
    if has_cleared_head_coach(school["id"], credential["sport"]):
        return False
    return gap_add(school, credential["sport"]) or credential["sport"] in school["credential_gap_sports"]


# ---------------------------------------------------------------------------
# CASCADE B: forfeit -> sanction posture -> provisional revocation
# ---------------------------------------------------------------------------
def derive_sanction(forfeit_count):
    if forfeit_count >= calc.SANCTION_SUSPENSION_THRESHOLD:
        return "SUSPENDED"
    if forfeit_count >= calc.SANCTION_PROBATION_THRESHOLD:
        return "PROBATION"
    return "GOOD_STANDING"


def cascade_b(contest, forfeiting_school):
    """Links 1-3, plus the independent trip cancellation."""
    clock = now()
    # LINK 1
    contest["status"] = "FORFEITED"
    contest["forfeiting_school_id"] = forfeiting_school["id"]
    if forfeiting_school["id"] == contest["home_school_id"]:
        contest["home_score"] = calc.FORFEIT_LOSS_SCORE
        contest["away_score"] = calc.FORFEIT_WIN_SCORE
    else:
        contest["home_score"] = calc.FORFEIT_WIN_SCORE
        contest["away_score"] = calc.FORFEIT_LOSS_SCORE
    contest["result_recorded_at"] = clock
    touch(contest)

    before = forfeiting_school["sanction_status"]
    forfeiting_school["forfeit_count"] += 1
    # LINK 2
    forfeiting_school["sanction_status"] = derive_sanction(forfeiting_school["forfeit_count"])
    touch(forfeiting_school)

    # LINK 3 - fired only because the school entered PROBATION
    if before == "GOOD_STANDING" and forfeiting_school["sanction_status"] == "PROBATION":
        for case in DB.cases.values():
            if case["status"] != "PROVISIONAL_ELIGIBLE":
                continue
            student = DB.students.get(case["student_id"])
            if student is None or student["school_id"] != forfeiting_school["id"]:
                continue
            case["status"] = "UNDER_REVIEW"
            case["provisional_revoked_at"] = clock
            touch(case)

    # independent of links 1-3
    cancel_trips(contest, ("REQUESTED", "APPROVED"))


# ---------------------------------------------------------------------------
# Medical hold helpers
# ---------------------------------------------------------------------------
def student_has_live_injury(student_id, exclude_id=None):
    for i in DB.injuries.values():
        if i["student_id"] != student_id:
            continue
        if exclude_id is not None and i["id"] == exclude_id:
            continue
        if i["status"] in ("REPORTED", "RTP_IN_PROGRESS"):
            return True
    return False
