"""calc payout_verdict — the dual-variant payment decision (SCAFFOLD.yaml).

STRICT_PAYMENT_DATE forfeits any termination before the payment date regardless
of reason; GOOD_LEAVER_PRORATION keeps the already-prorated award for a good
leaver.  A participant whose termination_date equals plan.payment_date exactly
counts as employed on the payment date.
"""

import db

EMPLOYED_STATUSES = ("ACTIVE", "ON_LEAVE")
LIVE_DISPUTE_STATUSES = ("OPEN", "UNDER_REVIEW")


def employed_on_payment_date(plan, participant):
    if participant["employment_status"] in EMPLOYED_STATUSES:
        return True
    termination_date = participant["termination_date"]
    if termination_date is None:
        return False
    return db.as_date(termination_date) >= db.as_date(plan["payment_date"])


def verdict_cents(plan, participant, award):
    employed = employed_on_payment_date(plan, participant)
    if plan["termination_treatment_policy"] == "STRICT_PAYMENT_DATE":
        return award["final_award_cents"] if employed else 0
    if employed or award["eligibility_status"] == "GOOD_LEAVER":
        return award["final_award_cents"]
    return 0


def has_live_dispute(award_id):
    return any(d["status"] in LIVE_DISPUTE_STATUSES
               for d in db.award_disputes(award_id))


def payment_outcome(plan, participant, award):
    """(payment_status, payout_amount_cents) the run would write."""
    amount = verdict_cents(plan, participant, award)
    if has_live_dispute(award["id"]):
        return "DEFERRED", amount
    if amount > 0:
        return "PAID", amount
    return "FORFEITED", 0
