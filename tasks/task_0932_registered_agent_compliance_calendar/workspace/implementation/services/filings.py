"""Filing fee breakdown and the money split that follows it (PRD 3.7)."""

import lookup
from constants import EXPEDITE_SERVICE_FEE_CENTS, SERVICE_FEE_BASE_CENTS
from store import DB


def expedite_halves(tier, rule):
    """The expedite component splits in two.

    ADJUDICATION OF FRICTION 5 -- which rule version supplies
    expedite_surcharge_cents on an OBLIGATION-BACKED filing.  Reading: THE
    OBLIGATION'S OWN PINNED governing_rule_id (the caller passes that rule in
    here); a standalone filing uses the rule effective on the filing's creation
    date, which is the rule its own rung-18 gate already required.  This is the
    reading that keeps the most declared behaviour reachable: rung 18 is
    declared to apply to POST /registrations/{id}/filings but NOT to
    POST /compliance-obligations/{id}/filings, so an obligation-backed draft
    must never be able to fail with ERR_NO_EFFECTIVE_STATE_RULE -- which it
    could if it had to resolve today's rule.  Pinning also matches PRD 2.6's
    non-retroactivity: the period was determined under that version.
    """
    service_half = EXPEDITE_SERVICE_FEE_CENTS[tier]
    state_half = 0 if tier == "NONE" else rule["expedite_surcharge_cents"]
    return service_half, state_half


def standalone_state_fee(kind, rule, reinstatement_case):
    if kind == "FOREIGN_QUALIFICATION":
        return rule["foreign_qualification_fee_cents"]
    if kind == "WITHDRAWAL":
        return rule["withdrawal_fee_cents"]
    if kind == "DISSOLUTION":
        return rule["dissolution_fee_cents"]
    if kind == "REINSTATEMENT":
        return reinstatement_case["back_fee_total_cents"] if reinstatement_case else 0
    # ANNUAL_REPORT / FRANCHISE_TAX / FINAL_REPORT drafted standalone carry no
    # jurisdiction fee of their own: PRD 3.7 names a state fee only for the
    # four standalone kinds above.
    return 0


def breakdown(state_fee_cents, service_fee_cents, tier, rule):
    service_half, state_half = expedite_halves(tier, rule)
    state_portion = state_fee_cents + state_half
    service_portion = service_fee_cents + service_half
    return {
        "state_fee_cents": state_fee_cents,
        "service_fee_cents": service_fee_cents,
        "expedite_fee_cents": service_half + state_half,
        "state_portion_cents": state_portion,
        "service_portion_cents": service_portion,
        "total_fee_cents": state_portion + service_portion,
    }


def obligation_backed_breakdown(obligation, tier, rule):
    state_fee = (
        obligation["state_fee_cents"]
        + obligation["franchise_tax_cents"]
        + obligation["late_fee_cents"]
    )
    return breakdown(state_fee, obligation["service_fee_cents"], tier, rule)


def base_service_fee():
    return SERVICE_FEE_BASE_CENTS


def recompute_paid_amount(filing):
    """paid_amount_cents is at all times the NET sum of the allocation rows
    pointing at this filing, reversal rows included as negatives (PRD 3.7)."""
    filing["paid_amount_cents"] = sum(
        a["amount_cents"] for a in lookup.allocations_of_filing(filing["id"])
    )
    return filing["paid_amount_cents"]


def case_for_reinstatement_filing(filing):
    """ADJUDICATION OF FRICTION 10 -- how a REINSTATEMENT filing is linked to a
    reinstatement case when the Filing entity has no persisted
    reinstatement_case_id field.  Reading: LINKAGE BY REGISTRATION + kind
    REINSTATEMENT, exactly as the two declared cascades state their
    preconditions ("a REINSTATEMENT Filing on this registration has ...").  The
    optional body-supplied reinstatement_case_id is retained internally only to
    disambiguate which case prices the draft and which case a cascade prefers;
    when it was omitted the cascade still fires, so both declared cascades stay
    reachable either way -- which is what the reachability tie-break requires.
    """
    preferred = filing.get("_reinstatement_case_id")
    if preferred and preferred in DB.reinstatement_cases:
        return DB.reinstatement_cases[preferred]
    cases = lookup.cases_of_registration(filing["registration_id"])
    if not cases:
        return None
    cases.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return cases[-1]


def cases_in_status(filing, status):
    """Every candidate case for a cascade, most recent first."""
    preferred = filing.get("_reinstatement_case_id")
    if preferred and preferred in DB.reinstatement_cases:
        case = DB.reinstatement_cases[preferred]
        return [case] if case["status"] == status else []
    cases = [
        c
        for c in lookup.cases_of_registration(filing["registration_id"])
        if c["status"] == status
    ]
    cases.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return cases[-1:] if cases else []
