"""Application state transitions and cascades.

Implements every transition described in SCAFFOLD §1.2 (Application) and the
cascade rules in PRD §2.7.
"""

import db
import errors
import util
from services import applicants as applicants_service
from services import schools as schools_service
from services import waitlist as waitlist_service


# Status sets ------------------------------------------------------------------

NON_TERMINAL_STATUSES = frozenset({
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ADMITTED",
    "WAITLISTED", "DEFERRED",
})
TERMINAL_STATUSES = frozenset({"WITHDRAWN", "DENIED", "DECLINED_OFFER"})
ED_NON_TERMINAL_FOR_BINDING = NON_TERMINAL_STATUSES  # alias for readability


# ----------------------------------------------------------------------------- #
# DRAFT -> SUBMITTED
# ----------------------------------------------------------------------------- #

def can_transition_submitted(application_row) -> None:
    """Raise APIError if the DRAFT->SUBMITTED preconditions are not met.

    Priority ordering (see PRD §2.6):
      10 ERR_INVALID_STATE (must be DRAFT)
      11 ERR_ED_BINDING_VIOLATION
      12 ERR_DEADLINE_PASSED
      14 ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE (essay word count)
      15 ERR_ED_REQUIRES_LETTER

    Other shape-level checks (profile READY, exactly-one essay, all letters
    SUBMITTED) fall under ERR_INVALID_STATE.
    """
    # Priority 10: from-state
    if application_row["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Application is not in DRAFT state.")

    applicant = db.applicants.get(application_row["applicant_id"])
    school = db.schools.get(application_row["school_id"])
    plan = application_row["plan"]

    # Priority 11: ED binding (recheck — must remain unique among non-terminal)
    if plan == "EARLY_DECISION":
        for other in db.applications.values():
            if other["id"] == application_row["id"]:
                continue
            if other["applicant_id"] != application_row["applicant_id"]:
                continue
            if other["plan"] == "EARLY_DECISION" and other["status"] in NON_TERMINAL_STATUSES:
                errors.raise_error(
                    errors.ERR_ED_BINDING_VIOLATION,
                    "Applicant already has another non-terminal ED application.",
                )

    # Priority 12: deadline window
    now = util.server_clock_dt()
    if plan == "EARLY_DECISION":
        if now > school["ed_deadline_iso"]:
            errors.raise_error(errors.ERR_DEADLINE_PASSED,
                               "Past Early Decision deadline.")
    elif plan == "EARLY_ACTION":
        if now > school["ea_deadline_iso"]:
            errors.raise_error(errors.ERR_DEADLINE_PASSED,
                               "Past Early Action deadline.")
    elif plan == "REGULAR":
        if now > school["rd_deadline_iso"]:
            errors.raise_error(errors.ERR_DEADLINE_PASSED,
                               "Past Regular Decision deadline.")
    elif plan == "ROLLING":
        if not school.get("rolling_open"):
            errors.raise_error(errors.ERR_DEADLINE_PASSED,
                               "School is not accepting rolling submissions.")

    # Profile READY check (treated as INVALID_STATE — applicant readiness)
    if applicant is None or applicant.get("profile_status") != "READY":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Applicant profile is not READY.")

    # Exactly one essay
    essays = [
        e for e in db.essay_submissions.values()
        if e["application_id"] == application_row["id"]
    ]
    if len(essays) != 1:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Exactly one essay submission is required.")

    # Priority 14: essay word count
    essay = essays[0]
    if not (1 <= essay["word_count"] <= 650):
        errors.raise_error(errors.ERR_ESSAY_WORD_COUNT_OUT_OF_RANGE,
                           "Essay word_count out of 1..650 inclusive.")

    # Letters: all letters must be SUBMITTED
    letters = [
        letter for letter in db.recommendation_letters.values()
        if letter["application_id"] == application_row["id"]
    ]

    if plan == "EARLY_DECISION":
        # Priority 15: ED requires at least one SUBMITTED letter
        submitted_letters = [l for l in letters if l["status"] == "SUBMITTED"]
        if len(submitted_letters) == 0:
            errors.raise_error(errors.ERR_ED_REQUIRES_LETTER,
                               "Early Decision submission requires at least one SUBMITTED letter.")

    # All existing letters must be in SUBMITTED status (any pending letter blocks submission)
    for letter in letters:
        if letter["status"] != "SUBMITTED":
            errors.raise_error(errors.ERR_INVALID_STATE,
                               "All recommendation letters must be SUBMITTED before submission.")


def do_submit(application_row):
    can_transition_submitted(application_row)
    application_row["status"] = "SUBMITTED"
    application_row["submitted_at"] = util.server_clock_dt()
    # Lock the essay
    for essay in db.essay_submissions.values():
        if essay["application_id"] == application_row["id"]:
            essay["locked"] = True
            util.stamp_update(essay)
    util.stamp_update(application_row)


# ----------------------------------------------------------------------------- #
# Start review and decisions
# ----------------------------------------------------------------------------- #

def do_start_review(application_row):
    status = application_row["status"]
    if status == "SUBMITTED":
        application_row["status"] = "UNDER_REVIEW"
        util.stamp_update(application_row)
        return
    if status == "DEFERRED":
        school = db.schools[application_row["school_id"]]
        # Must be strictly past the ED deadline
        if util.server_clock_dt() <= school["ed_deadline_iso"]:
            errors.raise_error(errors.ERR_INVALID_STATE,
                               "Deferred application re-review only after ED deadline.")
        application_row["status"] = "UNDER_REVIEW"
        util.stamp_update(application_row)
        return
    errors.raise_error(errors.ERR_INVALID_STATE,
                       "Application is not in SUBMITTED or DEFERRED state.")


def do_decide(application_row, decision: str):
    """Apply a decision (ADMIT/WAITLIST/DENY/DEFER) to an UNDER_REVIEW app."""
    if application_row["status"] != "UNDER_REVIEW":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Application is not in UNDER_REVIEW state.")
    now = util.server_clock_dt()
    if decision == "ADMIT":
        application_row["status"] = "ADMITTED"
        application_row["decision_at"] = now
    elif decision == "WAITLIST":
        application_row["status"] = "WAITLISTED"
        application_row["decision_at"] = now
        application_row["waitlist_added_at"] = now
        util.stamp_update(application_row)
        waitlist_service.recompute_waitlist_ranks(application_row["school_id"])
        return  # already stamp_update'd above
    elif decision == "DENY":
        application_row["status"] = "DENIED"
        application_row["decision_at"] = now
    elif decision == "DEFER":
        if application_row["plan"] not in ("EARLY_DECISION", "EARLY_ACTION"):
            errors.raise_error(
                errors.ERR_INVALID_STATE,
                "DEFER is only meaningful for early plans.",
            )
        application_row["status"] = "DEFERRED"
        application_row["decision_at"] = now
        application_row["plan"] = "REGULAR"
    else:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"Unknown decision value: {decision!r}.")
    util.stamp_update(application_row)


# ----------------------------------------------------------------------------- #
# Accept / Decline / Revoke
# ----------------------------------------------------------------------------- #

def do_accept_offer(application_row):
    if application_row["status"] != "ADMITTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Application is not in ADMITTED state.")
    # Priority 13: single-enrollment
    applicant_id = application_row["applicant_id"]
    for other in db.applications.values():
        if other["id"] == application_row["id"]:
            continue
        if other["applicant_id"] == applicant_id and other["status"] == "ENROLLED":
            errors.raise_error(errors.ERR_ALREADY_ENROLLED,
                               "Applicant already has another enrolled application.")

    application_row["status"] = "ENROLLED"
    util.stamp_update(application_row)
    schools_service.inc_enrollment(application_row["school_id"])

    # ED cascade — withdraw every other non-terminal application by this applicant
    if application_row["plan"] == "EARLY_DECISION":
        affected_schools_for_rank = set()
        for other in list(db.applications.values()):
            if other["id"] == application_row["id"]:
                continue
            if other["applicant_id"] != applicant_id:
                continue
            if other["status"] in NON_TERMINAL_STATUSES:
                was_waitlisted = other["status"] == "WAITLISTED"
                other["status"] = "WITHDRAWN"
                if was_waitlisted:
                    other["waitlist_rank"] = None
                    affected_schools_for_rank.add(other["school_id"])
                util.stamp_update(other)
        # Recompute waitlist ranks on freed schools (depth 3)
        for sid in affected_schools_for_rank:
            waitlist_service.recompute_waitlist_ranks(sid)


def do_decline_offer(application_row):
    if application_row["status"] != "ADMITTED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Application is not in ADMITTED state.")
    application_row["status"] = "DECLINED_OFFER"
    util.stamp_update(application_row)


def do_revoke_enrollment(application_row):
    if application_row["status"] != "ENROLLED":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Application is not in ENROLLED state.")
    application_row["status"] = "DECLINED_OFFER"
    util.stamp_update(application_row)
    schools_service.dec_enrollment(application_row["school_id"])


# ----------------------------------------------------------------------------- #
# Withdraw
# ----------------------------------------------------------------------------- #

def do_withdraw(application_row):
    if application_row["status"] not in NON_TERMINAL_STATUSES:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Application is not in a non-terminal state.")
    was_waitlisted = application_row["status"] == "WAITLISTED"
    application_row["status"] = "WITHDRAWN"
    if was_waitlisted:
        application_row["waitlist_rank"] = None
    util.stamp_update(application_row)
    if was_waitlisted:
        waitlist_service.recompute_waitlist_ranks(application_row["school_id"])
