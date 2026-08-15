"""Core shared services: record lifecycle, committee selector, lazy expiry,
and the multi-entity cascades (withdrawal, remand)."""
from datetime import timedelta

from db import db, next_seq
from errors import raise_error, ERR_NO_ELIGIBLE_COMMITTEE
from util import CLOCK, clock_stamp, fmt_dt, new_id, parse_dt
from services import calculations as calc


# ---------------------------------------------------------------------------
# Record lifecycle (PRD §2.5)
# ---------------------------------------------------------------------------

def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = clock_stamp()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    rec["updated_at"] = clock_stamp()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_case(case_id):
    return db["cases"].get(case_id)


def get_candidate(candidate_id):
    return db["candidates"].get(candidate_id)


def case_of_invitation(inv):
    return db["cases"].get(inv["case_id"])


def case_of_round(round_rec):
    return db["cases"].get(round_rec["case_id"])


def case_of_vote(vote):
    rnd = db["rounds"].get(vote["round_id"])
    return db["cases"].get(rnd["case_id"]) if rnd else None


# ---------------------------------------------------------------------------
# Case clock recomputation (extension approve / rescind — PRD §3.3)
# ---------------------------------------------------------------------------

def recompute_case_clock(case):
    case["extension_days"] = calc.approved_extension_days(case["id"])
    candidate = get_candidate(case["candidate_id"])
    mrd = calc.compute_mandatory_review_date(
        candidate["tenure_clock_start"], case["clock_policy"], case["extension_days"]
    )
    case["mandatory_review_date"] = fmt_dt(mrd)


# ---------------------------------------------------------------------------
# Committee selection (calculation committee_selection, PRD §3.5)
# ---------------------------------------------------------------------------

STAGE_FOR_LEVEL = {
    "DEPARTMENT": "DEPT_COMMITTEE",
    "COLLEGE": "COLLEGE_COMMITTEE",
    "UNIVERSITY": "UNIVERSITY_COMMITTEE",
}


def select_committee(level, candidate):
    """Eligibility filter then ranking: term_start DESC, created_at ASC.
    Entity ids are never used for ranking. Empty pool -> ERR_NO_ELIGIBLE_COMMITTEE."""
    now = CLOCK.now()
    eligible = []
    for c in db["committees"].values():
        if c["level"] != level:
            continue
        if level == "DEPARTMENT" and c["academic_unit"] != candidate["department"]:
            continue
        if level == "COLLEGE" and c["academic_unit"] != candidate["college"]:
            continue
        # UNIVERSITY matches on level only
        if not (parse_dt(c["term_start"]) <= now <= parse_dt(c["term_end"])):
            continue
        eligible.append(c)
    if not eligible:
        raise_error(ERR_NO_ELIGIBLE_COMMITTEE,
                    f"no eligible {level} committee for the case")
    eligible.sort(key=lambda c: (c["created_at"], c["_seq"]))
    eligible.sort(key=lambda c: parse_dt(c["term_start"]), reverse=True)
    return eligible[0]


def create_round(case, level):
    """System-created review round (never via POST) — starts SCHEDULED."""
    candidate = get_candidate(case["candidate_id"])
    committee = select_committee(level, candidate)
    rec = new_record("rounds", {
        "case_id": case["id"],
        "committee_id": committee["id"],
        "level": level,
        "opened_at": None,
        "status": "SCHEDULED",
        "active_member_count": None,
        "recusal_count": 0,
        "eligible_voter_count": None,
        "quorum_required": None,
        "votes_cast": 0,
        "yes_count": 0,
        "no_count": 0,
        "abstain_count": 0,
        "quorum_met": False,
        "yes_percentage": None,
        "passed": None,
        "recommendation": None,
        "letter_text": None,
        "certified_at": None,
    })
    return rec


# ---------------------------------------------------------------------------
# ReviewerInvitation lazy expiry (PRD §2.4)
# ---------------------------------------------------------------------------

def lazy_expire_invitation(inv):
    """Flip a SOLICITED invitation to EXPIRED when the clock has passed its
    response_deadline. Applied when a request targets the invitation by path
    id, and in a batch at close-solicitation. Returns True when flipped."""
    if inv["status"] == "SOLICITED" and CLOCK.now() > parse_dt(inv["response_deadline"]):
        inv["status"] = "EXPIRED"
        touch(inv)  # lazy expiry increments ReviewerInvitation.version by 1
        return True
    return False


def lazy_expire_case_invitations(case_id):
    for inv in db["invitations"].values():
        if inv["case_id"] == case_id:
            lazy_expire_invitation(inv)


# ---------------------------------------------------------------------------
# Case withdrawal cascade (PRD §3.9)
# ---------------------------------------------------------------------------

def cancel_pending_extensions(case_id):
    for e in db["clock_extensions"].values():
        if e["case_id"] == case_id and e["status"] == "PENDING":
            e["status"] = "CANCELLED"
            touch(e)


def withdraw_case_cascade(case, from_stage):
    """Shared effects plus the stage-dependent teardown."""
    candidate = get_candidate(case["candidate_id"])
    if candidate is not None and candidate["status"] != "WITHDRAWN":
        candidate["status"] = "WITHDRAWN"
        touch(candidate)
    cancel_pending_extensions(case["id"])
    if from_stage == "EXTERNAL_REVIEW":
        for inv in db["invitations"].values():
            if inv["case_id"] == case["id"] and inv["status"] in ("SOLICITED", "ACCEPTED"):
                inv["status"] = "WITHDRAWN"
                touch(inv)
    elif from_stage in ("DEPT_COMMITTEE", "COLLEGE_COMMITTEE", "UNIVERSITY_COMMITTEE"):
        now = clock_stamp()
        for rnd in db["rounds"].values():
            if rnd["case_id"] == case["id"] and rnd["status"] in ("SCHEDULED", "VOTING_OPEN", "TALLYING"):
                was_live = rnd["status"] in ("VOTING_OPEN", "TALLYING")
                rnd["status"] = "CANCELLED"
                touch(rnd)
                if was_live:
                    for v in db["votes"].values():
                        if v["round_id"] == rnd["id"] and v["status"] == "CAST":
                            v["status"] = "RETRACTED"
                            v["retracted_at"] = now
                            touch(v)
    case["stage"] = "WITHDRAWN"
    touch(case)


# ---------------------------------------------------------------------------
# Appeal remand cascade (PRD §3.8)
# ---------------------------------------------------------------------------

def remand_cascade(case):
    """DECIDED|NOTIFIED -> DEPT_COMMITTEE with the full remand cascade.
    The committee selector runs FIRST so an empty pool fails the resolve call
    atomically (no partial mutation)."""
    candidate = get_candidate(case["candidate_id"])
    # selector before any mutation (atomicity of the cascade)
    # (create_round runs the selector; we pre-check to keep the call atomic)
    select_committee("DEPARTMENT", candidate)

    recorded = [
        d for d in db["decisions"].values()
        if d["case_id"] == case["id"] and d["status"] == "RECORDED"
    ]
    for d in recorded:
        d["status"] = "VOIDED"
        touch(d)
    if candidate is not None and candidate["status"] in ("TENURED", "NOT_RENEWED"):
        candidate["status"] = "ACTIVE"
        touch(candidate)
    case["recommendation_score"] = None
    if case["stage"] == "NOTIFIED":
        case["appeal_filing_deadline"] = None
    create_round(case, "DEPARTMENT")
    case["stage"] = "DEPT_COMMITTEE"
    touch(case)


def recorded_decision_for_case(case_id):
    for d in db["decisions"].values():
        if d["case_id"] == case_id and d["status"] == "RECORDED":
            return d
    return None
