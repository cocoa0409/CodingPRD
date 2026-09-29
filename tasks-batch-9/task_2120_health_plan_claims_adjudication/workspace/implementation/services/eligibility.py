"""Coverage termination and the eligibility re-pend cascade (PRD 3.2)."""

from store import db
from services.events import append_event
from services.lookup import coverages_of, covers, lines_of
from services.pipeline import release_line_units, zero_claim_totals, zero_line_money

REPENDABLE_CLAIM_STATUSES = ("RECEIVED", "PENDED", "ADJUDICATED")


def member_covered_now(member_id):
    return any(covers(c, db.clock_date()) for c in coverages_of(member_id))


def activate_member_if_covered(member, segment):
    """A new segment containing the clock date sets the member back to ACTIVE."""
    if covers(segment, db.clock_date()):
        if member["status"] != "ACTIVE":
            member["status"] = "ACTIVE"
            db.touch(member)


def terminate_coverage(coverage, term_date, actor_role, actor_user_id):
    # HOP 1 -- the segment closes.
    coverage["status"] = "TERMINATED"
    coverage["term_date"] = term_date
    db.touch(coverage)

    # HOP 2 -- claims matched to this coverage whose statement period opens on
    # or after the new term date are re-pended for eligibility review.
    for claim in db.values("claims"):
        if claim["coverage_id"] != coverage["id"]:
            continue
        if claim["status"] not in REPENDABLE_CLAIM_STATUSES:
            continue
        if claim["statement_from_date"] is None or claim["statement_from_date"] < term_date:
            continue
        from_status = claim["status"]
        claim["status"] = "PENDED"
        claim["pend_reason_code"] = "PEND_ELIG_REVIEW"
        # HOP 3 -- their priced lines re-pend, zero their money and release the
        # units they were holding; HOP 4 -- each authorization re-derives.
        for line in lines_of(claim):
            if line["line_status"] != "PRICED":
                continue
            release_line_units(line)
            line["line_status"] = "PENDED"
            line["edit_reason_code"] = "PEND_ELIG_REVIEW"
            zero_line_money(line)
            line["authorization_id"] = None
            line["_rule"] = None
            db.touch(line)
        zero_claim_totals(claim)
        db.touch(claim)
        append_event(
            claim,
            "ELIG_REPEND",
            from_status,
            "PENDED",
            "PEND_ELIG_REVIEW",
            "system",
            None,
        )

    # A separate direct effect of HOP 1.
    member = db.members.get(coverage["member_id"])
    if member is not None and not member_covered_now(member["id"]):
        if member["status"] != "TERMINATED":
            member["status"] = "TERMINATED"
            db.touch(member)
    return coverage
