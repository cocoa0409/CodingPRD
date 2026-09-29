"""Server-owned derived state: the two organization posture dimensions, the
fundraiser registry status, and disclosure clause resolution.

Neither posture dimension is ever supplied by a client, and a change to one
leaves the other untouched (PRD 2.8).  Every recomputation of a derived field is
a mutation of its row: updated_at moves and version increments (PRD 2.5).
"""
from db import db, sorted_rows, touch, touch_once
from validate import CANONICAL_CLAUSE_ORDER

OUTSTANDING_ENFORCEMENT_STATUSES = ("OPEN", "REMEDIATION_SUBMITTED", "ESCALATED")


def organization_derived_snapshot(organization):
    """Compute the six derived organization fields from the organization's children."""
    organization_id = organization["id"]

    ceased = sorted({
        r["state_code"] for r in db.state_registrations.values()
        if r["organization_id"] == organization_id and r["status"] == "CEASED"
    })

    registered_count = sum(
        1 for r in db.state_registrations.values()
        if r["organization_id"] == organization_id and r["status"] == "REGISTERED"
    )
    delinquent_count = sum(
        1 for r in db.state_registrations.values()
        if r["organization_id"] == organization_id and r["status"] == "DELINQUENT"
    )

    penalty = sum(
        a["penalty_cents"] for a in db.enforcement_actions.values()
        if a["organization_id"] == organization_id
        and a["status"] in OUTSTANDING_ENFORCEMENT_STATUSES
    )

    # Dimension 1 -- solicitation_posture, a function of ceased_state_codes.
    if not ceased:
        solicitation = "CLEAR"
    elif organization["domicile_state_code"] in ceased or len(ceased) >= 2:
        solicitation = "HALTED"
    else:
        solicitation = "RESTRICTED"

    # Dimension 2 -- filing_posture, a function of delinquent_registration_count.
    filing = "DELINQUENT" if delinquent_count >= 1 else "CURRENT"

    return {
        "ceased_state_codes": ceased,
        "registered_state_count": registered_count,
        "delinquent_registration_count": delinquent_count,
        "penalty_outstanding_cents": penalty,
        "solicitation_posture": solicitation,
        "filing_posture": filing,
    }


def recompute_organization(organization, once=True):
    """Recompute both posture dimensions, both counters and the penalty ledger.

    Returns the pair of posture values as they read *before* the recomputation so
    that callers can fire the cascade links that are gated on a posture actually
    having flipped.

    ``once=False`` is used by the compliance sweep, where each candidate
    registration runs its own independent three-link cascade and therefore
    increments Organization.version once per candidate.
    """
    previous_solicitation = organization["solicitation_posture"]
    previous_filing = organization["filing_posture"]
    organization.update(organization_derived_snapshot(organization))
    if once:
        touch_once(organization, "organization")
    else:
        touch(organization)
    return previous_solicitation, previous_filing


def recompute_registry_status(fundraiser):
    """REGISTERED / LAPSED / UNREGISTERED as a pure function of the firm's rows.

    A firm that never registered and a firm whose registrations all expired are
    treated differently by examiners, hence the three-way distinction.
    """
    rows = [r for r in db.fundraiser_registrations.values()
            if r["fundraiser_id"] == fundraiser["id"]]
    if any(r["status"] == "ACTIVE" for r in rows):
        status = "REGISTERED"
    elif rows:
        status = "LAPSED"
    else:
        status = "UNREGISTERED"
    fundraiser["registry_status"] = status
    touch_once(fundraiser, "professional_fundraiser")
    return status


def has_filed_solicitor_engagement(organization_id, state_code):
    """A filed PROFESSIONAL_SOLICITOR engagement covering this state.

    A FUNDRAISING_COUNSEL or COMMERCIAL_COVENTURER engagement does not count, and
    contracts in DRAFT or VOIDED are ignored.
    """
    for contract in db.fundraising_contracts.values():
        if contract["organization_id"] != organization_id:
            continue
        if contract["status"] not in ("FILED", "LATE_FILED"):
            continue
        if state_code not in contract["state_codes"]:
            continue
        firm = db.professional_fundraisers.get(contract["fundraiser_id"])
        if firm is not None and firm["fundraiser_type"] == "PROFESSIONAL_SOLICITOR":
            return True
    return False


def has_live_promotion(organization_id, state_code):
    """A live charitable sales promotion covering this state.

    Promotions in DRAFT, SETTLED, DEFICIENT_REMITTANCE or HALTED are ignored.
    """
    for promotion in db.coventure_promotions.values():
        if promotion["organization_id"] != organization_id:
            continue
        if promotion["status"] not in ("FILED", "ACTIVE"):
            continue
        if state_code in promotion["state_codes"]:
            return True
    return False


def resolve_disclosure(statement):
    """Resolve required_clauses, missing_clauses and compliance_status (PRD 3.8).

    The base is the state's disclosure_required_clauses; the two conditional
    additions are idempotent, and every emitted array is in canonical order.
    """
    profile = db.state_profiles[statement["state_code"]]
    required = set(profile["disclosure_required_clauses"])

    if has_filed_solicitor_engagement(statement["organization_id"], statement["state_code"]):
        required.add("PAID_SOLICITOR_IDENTITY")
    if has_live_promotion(statement["organization_id"], statement["state_code"]):
        required.add("PERCENT_TO_CHARITY")

    statement["required_clauses"] = [c for c in CANONICAL_CLAUSE_ORDER if c in required]
    included = set(statement["included_clauses"])
    statement["missing_clauses"] = [
        c for c in statement["required_clauses"] if c not in included
    ]
    statement["compliance_status"] = (
        "COMPLIANT" if not statement["missing_clauses"] else "NON_COMPLIANT"
    )
    return statement


def recompute_disclosures_for(organization_id, state_codes):
    """Re-resolve the charity's materials for the triggering record's states.

    Previously compliant copy can fall out of compliance -- and voided copy back
    into it -- without anyone touching the material itself.
    """
    codes = set(state_codes)
    affected = [s for s in db.disclosure_statements.values()
                if s["organization_id"] == organization_id and s["state_code"] in codes]
    for statement in sorted_rows(affected):
        resolve_disclosure(statement)
        touch_once(statement, "disclosure_statement")
    return affected
