"""Applicant readiness logic."""

import db
import util


def recompute_profile_status(applicant_id: str) -> None:
    """Re-evaluate the applicant's profile_status per §3.1.

    READY when:
      - full_name is present (non-empty)
      - gpa is present (non-null)
      - at least one Recommender row exists for this applicant

    Otherwise DRAFT.

    Bumps updated_at + version only if the value actually changes.
    """
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        return

    has_name = bool(applicant.get("full_name"))
    has_gpa = applicant.get("gpa") is not None
    # PRD §3.1 + §2.7: the readiness invariant requires "at least one
    # Recommender row exists for this applicant". A declined invitation is
    # terminal (PRD §3.2) and the decline cascade (§2.7) explicitly states
    # that this is the path by which "the deletion ... leaves the applicant
    # with no remaining recommender rows" — meaning a DECLINED row does not
    # count as a remaining recommender. Only non-DECLINED rows back the
    # readiness predicate.
    has_recommender = any(
        r["applicant_id"] == applicant_id and r.get("invite_status") != "DECLINED"
        for r in db.recommenders.values()
    )

    new_status = "READY" if (has_name and has_gpa and has_recommender) else "DRAFT"
    if applicant["profile_status"] != new_status:
        applicant["profile_status"] = new_status
        util.stamp_update(applicant)
