"""Depth-3 cascades (PRD 2.9)."""
import db
import lookups
from constants import PAE_SUSPENSION_THRESHOLD
from services import logbook


def undeliverable_event(voter_rec, election_rec, reason_code, actor):
    """Second and third links of the enrollment-suspension cascade.

    Head one is a NON_FORWARDABLE address result; head two is an undeliverable
    packet. Both behave identically from here.
    """
    if voter_rec is None:
        return
    enrollment = lookups.active_enrollment_of_voter(voter_rec)
    if enrollment is None:
        return
    enrollment["consecutive_undeliverable_count"] += 1
    db.touch(enrollment)
    if enrollment["consecutive_undeliverable_count"] >= PAE_SUSPENSION_THRESHOLD:
        enrollment["status"] = "SUSPENDED"
        enrollment["suspension_reason_code"] = reason_code
        db.touch(enrollment)
        voter_rec["permanent_absentee_active"] = False
        db.touch(voter_rec)
        logbook.append(
            election_rec,
            "ENROLLMENT_SUSPENDED",
            actor.role,
            actor.user_id,
            "PermanentAbsenteeEnrollment",
            enrollment["id"],
            "Permanent absentee enrollment suspended (%s)." % reason_code,
        )


def refer_to_provisional(voter_rec, election_rec, actor_role, actor_user_id, summary):
    """Third link of the rejection cascade: voter flag, counter, log entry."""
    if voter_rec is not None:
        voter_rec["provisional_ballot_eligible"] = True
        db.touch(voter_rec)
    if election_rec is not None:
        election_rec["provisional_referral_count"] += 1
        db.touch(election_rec)
    if voter_rec is not None:
        logbook.append(
            election_rec,
            "PROVISIONAL_REFERRAL",
            actor_role,
            actor_user_id,
            "Voter",
            voter_rec["id"],
            summary,
        )
