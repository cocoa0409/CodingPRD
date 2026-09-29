"""Shared existence lookups, gates, conservation invariants and cascades."""

import calc
import clockutil
import store
from errors import ApiError

NOT_FOUND = {
    "petitions": "ERR_PETITION_NOT_FOUND",
    "classifications": "ERR_CLASSIFICATION_NOT_FOUND",
    "election_agreements": "ERR_ELECTION_AGREEMENT_NOT_FOUND",
    "voter_lists": "ERR_VOTER_LIST_NOT_FOUND",
    "voter_list_entries": "ERR_VOTER_LIST_ENTRY_NOT_FOUND",
    "supervisors": "ERR_SUPERVISOR_NOT_FOUND",
    "campaign_communications": "ERR_CAMPAIGN_COMMUNICATION_NOT_FOUND",
    "election_rounds": "ERR_ELECTION_ROUND_NOT_FOUND",
    "poll_sessions": "ERR_POLL_SESSION_NOT_FOUND",
    "challenged_ballots": "ERR_CHALLENGED_BALLOT_NOT_FOUND",
    "objections": "ERR_OBJECTION_NOT_FOUND",
    "ulp_charges": "ERR_ULP_CHARGE_NOT_FOUND",
}


def must_exist(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection], "No such %s." % collection[:-1].replace("_", " "))
    return row


def require_open_posture(petition):
    """PRD 2.5 / 2.11 step 11: the election-advancing operations sit behind the posture gate."""
    if petition["case_posture"] != "OPEN":
        raise ApiError("ERR_CASE_POSTURE_BLOCKED",
                       "The case posture is %s; the election may not advance."
                       % petition["case_posture"])


def require_same_petition(expected_petition_id, actual_petition_id):
    if expected_petition_id != actual_petition_id:
        raise ApiError("ERR_CROSS_PETITION_REFERENCE",
                       "The referenced row belongs to a different case.")


# ------------------------------------------------------ conservation invariants

def check_headcount_conservation(petition):
    total = (petition["included_headcount"] + petition["excluded_headcount"]
             + petition["pending_headcount"])
    if total != petition["total_classified_headcount"]:
        raise ApiError("ERR_HEADCOUNT_CONSERVATION_VIOLATION",
                       "included + excluded + pending must equal total_classified_headcount.")


def check_ballot_conservation(rnd):
    total = (rnd["provisional_votes_for"] + rnd["challenged_counted_for_count"]
             + rnd["provisional_votes_against"] + rnd["challenged_counted_against_count"]
             + rnd["provisional_void_count"] + rnd["challenged_voided_count"]
             + rnd["challenged_withdrawn_count"] + rnd["challenged_open_count"])
    if total != rnd["ballots_cast_total"]:
        raise ApiError("ERR_BALLOT_CONSERVATION_VIOLATION",
                       "The challenge buckets must sum to ballots_cast_total.")


# ------------------------------------------------------------- voter list grading

def recount_list(voter_list):
    """Recompute the counters a voter entry write disturbs."""
    entries = store.entries_of(voter_list["id"])
    voter_list["total_entry_count"] = len(entries)
    voter_list["complete_entry_count"] = sum(
        1 for e in entries if e["is_statutory_content_complete"])
    voter_list["eligible_voter_count"] = sum(
        1 for e in entries if e["eligibility_status"] == "ELIGIBLE")


def grade_list(voter_list):
    """Grading at submission and at every resubmission (PRD 3.5)."""
    recount_list(voter_list)
    pct = calc.completeness_pct(voter_list["complete_entry_count"],
                               voter_list["total_entry_count"])
    voter_list["completeness_pct"] = calc.as_number(pct)
    submitted_at = clockutil.parse_dt(voter_list.get("submitted_at"))
    due_at = clockutil.parse_dt(voter_list.get("due_at"))
    is_late = bool(submitted_at is not None and due_at is not None and submitted_at > due_at)
    voter_list["is_late"] = is_late
    grade = calc.base_grade(pct)
    if is_late:
        grade = calc.worsen(grade)
    voter_list["list_grade"] = grade


def recompute_entry(entry):
    """Re-run the statutory content count and the six eligibility rules."""
    missing, complete = calc.statutory_content(entry)
    entry["missing_field_count"] = missing
    entry["is_statutory_content_complete"] = complete
    voter_list = store.get("voter_lists", entry["voter_list_id"])
    classification = store.get("classifications", entry["classification_id"])
    petition = store.petition(voter_list["petition_id"]) if voter_list else None
    agreement = None
    if voter_list is not None:
        agreement = store.get("election_agreements", voter_list.get("election_agreement_id"))
    status, reason = calc.voter_eligibility(entry, classification, petition, agreement)
    entry["eligibility_status"] = status
    entry["ineligibility_reason"] = reason


# ----------------------------------------------------------------- cascades

def dismissal_cascade(petition):
    """PRD 3.3: the INSUFFICIENT verdict reaches four other resource types."""
    for classification in store.classifications_of(petition["id"]):
        if classification["scope_ruling"] == "PENDING":
            classification["scope_ruling"] = "MOOT"
            store.touch(classification)
    for agreement in store.agreements_of(petition["id"]):
        if agreement["status"] in ("PROPOSED", "HEARING_REQUESTED"):
            agreement["status"] = "VOID"
            agreement["voter_list_due_at"] = None
            store.touch(agreement)
    for message in store.communications_of(petition["id"]):
        if message["status"] in ("DRAFT", "PENDING_LEGAL_REVIEW", "APPROVED"):
            message["status"] = "BLOCKED"
            message["blocked_reason"] = "CASE_DISMISSED"
            store.touch(message)
    for voter_list in store.voter_lists_of(petition["id"]):
        if voter_list["status"] == "DRAFT":
            voter_list["status"] = "CANCELLED"
            store.touch(voter_list)


def presenter_decertification_cascade(supervisor, petition):
    """PRD 3.6 hops two and three."""
    blocked_any = False
    for message in store.communications_of(supervisor["petition_id"]):
        if message.get("presenter_supervisor_id") != supervisor["id"]:
            continue
        if message["status"] in ("PENDING_LEGAL_REVIEW", "APPROVED"):
            message["status"] = "BLOCKED"
            message["blocked_reason"] = "PRESENTER_DECERTIFIED"
            store.touch(message)
            blocked_any = True
    if blocked_any and petition is not None and not petition["retraining_required"]:
        petition["retraining_required"] = True
        store.touch(petition)
    return blocked_any


def rerun_blackout_cascade(petition):
    """PRD 3.9 hop four."""
    for voter_list in store.voter_lists_of(petition["id"]):
        if voter_list["status"] == "ACCEPTED":
            voter_list["status"] = "SUPERSEDED"
            store.touch(voter_list)
    for message in store.communications_of(petition["id"]):
        if message["status"] in ("APPROVED", "PENDING_LEGAL_REVIEW"):
            message["status"] = "BLOCKED"
            message["blocked_reason"] = "RERUN_BLACKOUT"
            store.touch(message)


def blocking_charge_cascade(petition):
    """PRD 3.9: a blocking charge drives the posture to BLOCKED or IMPOUNDED."""
    latest = store.current_round(petition["id"])
    if latest is not None and latest["status"] in ("POLLS_CLOSED", "TALLY_POSTED",
                                                   "TALLY_REVISED"):
        petition["case_posture"] = "IMPOUNDED"
        latest["ballots_impounded"] = True
        store.touch(latest)
        return
    petition["case_posture"] = "BLOCKED"
    if latest is not None and latest["status"] == "SCHEDULED":
        latest["status"] = "SUSPENDED"
        for session in store.sessions_of(latest["id"]):
            if session["status"] == "SCHEDULED":
                session["status"] = "CANCELLED"
                store.touch(session)
        latest["scheduled_session_count"] = 0
        store.touch(latest)
    for message in store.communications_of(petition["id"]):
        if message["status"] == "APPROVED":
            message["status"] = "BLOCKED"
            message["blocked_reason"] = "POSTURE_BLOCKED"
            store.touch(message)


def unblock_chain(petition):
    """PRD 3.9: narrower than the block. Cancelled sessions are never restored."""
    if petition["blocking_charge_count"] > 0:
        return
    was_impounded = petition["case_posture"] == "IMPOUNDED"
    petition["case_posture"] = "OPEN"
    for rnd in store.rounds_of(petition["id"]):
        if rnd["status"] == "SUSPENDED":
            rnd["status"] = "SCHEDULED"
            store.touch(rnd)
        if was_impounded and rnd["ballots_impounded"]:
            rnd["ballots_impounded"] = False
            store.touch(rnd)
    for message in store.communications_of(petition["id"]):
        if message["status"] == "BLOCKED" and message.get("blocked_reason") == "POSTURE_BLOCKED":
            message["status"] = "APPROVED"
            message["blocked_reason"] = None
            store.touch(message)


def create_election_round(petition, agreement, round_number, prior_round_id,
                          voting_method, election_date, polls_open_at, polls_close_at):
    """Rounds are never created directly by a client; they appear as consequences."""
    return store.insert("election_rounds", {
        "petition_id": petition["id"],
        "election_agreement_id": agreement["id"] if agreement else None,
        "prior_round_id": prior_round_id,
        "round_number": round_number,
        "voting_method": voting_method,
        "election_date": election_date,
        "polls_open_at": polls_open_at,
        "polls_close_at": polls_close_at,
        "status": "SCHEDULED",
        "ballots_impounded": False,
        "scheduled_session_count": 0,
        "closed_session_count": 0,
        "ballots_cast_total": 0,
        "provisional_votes_for": 0,
        "provisional_votes_against": 0,
        "provisional_void_count": 0,
        "provisional_margin": 0,
        "challenged_open_count": 0,
        "challenged_counted_for_count": 0,
        "challenged_counted_against_count": 0,
        "challenged_voided_count": 0,
        "challenged_withdrawn_count": 0,
        "determinative_challenges": False,
        "revised_votes_for": None,
        "revised_votes_against": None,
        "revised_void_count": None,
        "revised_margin": None,
        "valid_votes_cast": None,
        "majority_threshold": None,
        "tally_posted_at": None,
        "tally_revised_at": None,
        "objection_window_close_at": None,
    })
