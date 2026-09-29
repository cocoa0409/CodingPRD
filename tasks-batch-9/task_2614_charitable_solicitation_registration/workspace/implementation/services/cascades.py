"""Multi-link server-driven cascades (PRD 2.8, 3.2, 3.4, 3.9).

No cascade is partial: either the whole chain applies or the request fails and
nothing changes.  Every entity a cascade touches has its ``updated_at`` refreshed
and its ``version`` incremented.
"""
import clock
from dates import add_days, fmt, parse_iso
from db import db, sorted_rows, stamp_new, touch, touch_once
from services import calc
from services.derive import (recompute_disclosures_for, recompute_organization,
                             recompute_registry_status)

LIVE_ENFORCEMENT_STATUSES = ("OPEN", "REMEDIATION_SUBMITTED", "ESCALATED")


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------
def registrations_of(organization_id):
    return [r for r in db.state_registrations.values()
            if r["organization_id"] == organization_id]


def actions_for_registration(registration_id, statuses=None):
    rows = [a for a in db.enforcement_actions.values()
            if a["registration_id"] == registration_id
            and (statuses is None or a["status"] in statuses)]
    return sorted_rows(rows)


def deny_pending_extension_requests(organization_id, at_iso):
    """Every PENDING request on ANY registration of this organization is denied.

    A charity that has gone delinquent forfeits all its pending pleas for more
    time (PRD 3.9 link D3 / PRD 2.8).
    """
    registration_ids = {r["id"] for r in registrations_of(organization_id)}
    denied = []
    candidates = [e for e in db.extension_requests.values()
                  if e["registration_id"] in registration_ids and e["status"] == "PENDING"]
    for row in sorted_rows(candidates):
        row["status"] = "DENIED"
        row["decided_at"] = at_iso
        touch_once(row, "extension_request")
        denied.append(row["id"])
    return denied


def issue_enforcement_action(organization, registration, action_type, penalty_cents,
                             once=True):
    """Create an OPEN action and re-derive the organization's penalty ledger.

    ``state_code`` is copied from the linked filing rather than supplied, and
    ``cure_deadline`` is issued_at plus the state's cure_period_days in whole days.
    """
    profile = db.state_profiles[registration["state_code"]]
    issued_at = clock.now()
    action = {
        "organization_id": organization["id"],
        "registration_id": registration["id"],
        "state_code": registration["state_code"],
        "action_type": action_type,
        "penalty_cents": penalty_cents,
        "status": "OPEN",
        "issued_at": clock.now_iso(),
        "cure_deadline": fmt(add_days(issued_at, profile["cure_period_days"])),
        "settlement_total_cents": 0,
        "remediation_note": None,
    }
    stamp_new(action)
    db.enforcement_actions[action["id"]] = action
    return action


# ---------------------------------------------------------------------------
# R1 / R2 / R3 -- financial restatement (PRD 3.2)
# ---------------------------------------------------------------------------
def apply_restatement(new_statement):
    """Supersede the prior CURRENT statement for the same fiscal year and repoint.

    A restatement does not reopen a filing the state has already accepted:
    registrations in REGISTERED, EXPIRED, DELINQUENT, CEASED or WITHDRAWN are
    untouched by all three links.
    """
    organization_id = new_statement["organization_id"]
    fiscal_year = new_statement["fiscal_year"]
    priors = [s for s in db.financial_statements.values()
              if s["organization_id"] == organization_id
              and s["fiscal_year"] == fiscal_year
              and s["id"] != new_statement["id"]
              and s["statement_status"] == "CURRENT"]
    if not priors:
        return False

    for prior in sorted_rows(priors):
        # R1 -- the prior statement moves CURRENT -> SUPERSEDED.
        prior["statement_status"] = "SUPERSEDED"
        touch_once(prior, "financial_statement")

        # R2 -- open filings are repointed and their attestation re-derived.
        repointed = [r for r in db.state_registrations.values()
                     if r["financial_statement_id"] == prior["id"]
                     and r["status"] in ("DRAFT", "SUBMITTED", "DEFICIENT")]
        for registration in sorted_rows(repointed):
            was_submitted = registration["status"] == "SUBMITTED"
            registration["financial_statement_id"] = new_statement["id"]
            requirement = calc.recompute_attestation(registration)

            # R3 -- a submitted filing whose fresh requirement now outranks the
            # new statement's assurance level is pushed back to DEFICIENT.
            if was_submitted and (calc.ASSURANCE_RANK[requirement]
                                  > calc.ASSURANCE_RANK[new_statement["assurance_level"]]):
                registration["status"] = "DEFICIENT"
                registration["deficiency_reasons"] = ["ASSURANCE_LEVEL_INSUFFICIENT"]
                registration["deficiency_round_count"] += 1
            touch_once(registration, "state_registration")
    return True


# ---------------------------------------------------------------------------
# L1 / L2 / L3 -- regulator approval of a filing (PRD 3.4)
# ---------------------------------------------------------------------------
def apply_review_approve(registration):
    """SUBMITTED -> REGISTERED, accept the documents, expire the predecessor."""
    organization = db.organizations[registration["organization_id"]]
    registration["status"] = "REGISTERED"
    registration["registered_at"] = clock.now_iso()
    for document in sorted_rows([d for d in db.registration_documents.values()
                                 if d["registration_id"] == registration["id"]]):
        document["review_status"] = "ACCEPTED"
        touch_once(document, "registration_document")
    touch_once(registration, "state_registration")

    target_id = registration["supersedes_registration_id"]
    if target_id:
        target = db.state_registrations.get(target_id)
        if target is not None and target["status"] in ("REGISTERED", "DELINQUENT"):
            # L1 -- expire the predecessor.
            target["status"] = "EXPIRED"
            touch_once(target, "state_registration")
            # L2 -- filing the renewal is itself a cure path for the predecessor.
            for action in actions_for_registration(target_id, LIVE_ENFORCEMENT_STATUSES):
                action["status"] = "CURED"
                touch_once(action, "enforcement_action")

    # L3 -- refresh the organization's counters, ledger and postures.
    recompute_organization(organization)
    return registration


# ---------------------------------------------------------------------------
# extension supersession (PRD 3.5)
# ---------------------------------------------------------------------------
def supersede_extension_history(registration):
    """Drive every earlier PENDING or GRANTED request on this filing to SUPERSEDED.

    Superseding a PENDING request has no effect on the deadline.  Superseding a
    GRANTED one clears extended_due_date back to null and snaps effective_due_date
    back to the unextended renewal_due_date.
    """
    superseded_granted = False
    candidates = [e for e in db.extension_requests.values()
                  if e["registration_id"] == registration["id"]
                  and e["status"] in ("PENDING", "GRANTED")]
    for row in sorted_rows(candidates):
        if row["status"] == "GRANTED":
            superseded_granted = True
        row["status"] = "SUPERSEDED"
        row["decided_at"] = clock.now_iso()
        touch_once(row, "extension_request")
    if superseded_granted:
        calc.recompute_deadlines(registration)
        touch_once(registration, "state_registration")
    return superseded_granted


# ---------------------------------------------------------------------------
# E1 / E2 / E3 -- escalation to a cease-solicitation order (PRD 3.9)
# ---------------------------------------------------------------------------
def halt_promotions_for_state(organization_id, state_code):
    """Stop cause marketing in a newly ceased state."""
    halted = []
    candidates = [p for p in db.coventure_promotions.values()
                  if p["organization_id"] == organization_id
                  and p["status"] in ("FILED", "ACTIVE")
                  and state_code in p["state_codes"]]
    for promotion in sorted_rows(candidates):
        promotion["status"] = "HALTED"
        touch_once(promotion, "coventure_promotion")
        halted.append(promotion["id"])
    return halted


def apply_escalate(action):
    """The action's status becomes ESCALATED and its action_type is overwritten."""
    registration = db.state_registrations[action["registration_id"]]
    organization = db.organizations[registration["organization_id"]]

    action["status"] = "ESCALATED"
    action["action_type"] = "CEASE_SOLICITATION_ORDER"
    touch_once(action, "enforcement_action")

    if registration["status"] == "DELINQUENT":
        # E1 -- cease the filing.
        registration["status"] = "CEASED"
        touch_once(registration, "state_registration")
        # E2 -- add the state to ceased_state_codes and re-derive the posture.
        previous_solicitation, _ = recompute_organization(organization)
        # E3 -- fires only where the posture actually became RESTRICTED or HALTED.
        if (organization["solicitation_posture"] in ("RESTRICTED", "HALTED")
                and organization["solicitation_posture"] != previous_solicitation):
            halt_promotions_for_state(organization["id"], registration["state_code"])
    return action


# ---------------------------------------------------------------------------
# C1 / C2 -- curing an action (PRD 3.9)
# ---------------------------------------------------------------------------
def apply_cure(action):
    """The action moves to CURED and the linked filing is restored to REGISTERED."""
    registration = db.state_registrations[action["registration_id"]]
    organization = db.organizations[registration["organization_id"]]

    action["status"] = "CURED"
    touch_once(action, "enforcement_action")

    if registration["status"] in ("CEASED", "DELINQUENT"):
        registration["status"] = "REGISTERED"
        touch_once(registration, "state_registration")

    recompute_organization(organization)
    return action


def apply_vacate(action):
    """Vacatur -- the compensating action for issuance (penalty_ledger_conservation).

    The variant from ESCALATED does more, because escalation had ceased a filing.
    """
    previous_status = action["status"]
    registration = db.state_registrations[action["registration_id"]]
    organization = db.organizations[registration["organization_id"]]

    action["status"] = "VACATED"
    touch_once(action, "enforcement_action")

    if previous_status == "ESCALATED" and registration["status"] == "CEASED":
        registration["status"] = "REGISTERED"
        touch_once(registration, "state_registration")

    recompute_organization(organization)
    return action


# ---------------------------------------------------------------------------
# F1 / F2 / F3 -- fundraiser credential lapse (PRD 3.9 second pass)
# ---------------------------------------------------------------------------
def void_contracts_for_lapse(fundraiser_id, state_code):
    """Void the firm's filed contracts covering the lapsed state, then re-resolve.

    A voided solicitor engagement can *remove* a clause that was previously
    required, so material that read as non-compliant may become compliant.
    """
    voided = []
    candidates = [c for c in db.fundraising_contracts.values()
                  if c["fundraiser_id"] == fundraiser_id
                  and c["status"] in ("FILED", "LATE_FILED")
                  and state_code in c["state_codes"]]
    for contract in sorted_rows(candidates):
        contract["status"] = "VOIDED"
        touch_once(contract, "fundraising_contract")
        voided.append(contract["id"])
        recompute_disclosures_for(contract["organization_id"], contract["state_codes"])
    return voided


# ---------------------------------------------------------------------------
# D1 / D2 / D3 plus F1 / F2 / F3 -- the compliance sweep (PRD 3.9)
# ---------------------------------------------------------------------------
def _renewal_already_covers(registration):
    """True when a REGISTERED renewal already supersedes this filing."""
    for other in db.state_registrations.values():
        if other["organization_id"] != registration["organization_id"]:
            continue
        if other["state_code"] != registration["state_code"]:
            continue
        if other["registration_type"] != "RENEWAL":
            continue
        if other["status"] != "REGISTERED":
            continue
        if other["supersedes_registration_id"] == registration["id"]:
            return True
    return False


def run_sweep(state_code=None):
    """Two independent passes; candidates processed in created_at ascending order."""
    now = clock.now()
    swept_at = clock.now_iso()

    delinquent_ids = []
    enforcement_action_ids = []
    denied_extension_request_ids = []
    lapsed_ids = []
    voided_contract_ids = []

    # ---- first pass: lapsed renewals -------------------------------------
    candidates = []
    for registration in db.state_registrations.values():
        if registration["status"] != "REGISTERED":
            continue
        if state_code is not None and registration["state_code"] != state_code:
            continue
        due = parse_iso(registration["effective_due_date"])
        if due is None or not (due < now):
            # A filing due exactly now is not yet late.
            continue
        if _renewal_already_covers(registration):
            continue
        candidates.append(registration)

    for registration in sorted_rows(candidates):
        organization = db.organizations[registration["organization_id"]]
        profile = db.state_profiles[registration["state_code"]]
        registration["status"] = "DELINQUENT"
        touch_once(registration, "state_registration")
        delinquent_ids.append(registration["id"])

        # D1 -- issue the delinquency notice.
        penalty = calc.late_penalty_accrual(registration, profile, now)
        action = issue_enforcement_action(
            organization, registration, "DELINQUENCY_NOTICE", penalty
        )
        enforcement_action_ids.append(action["id"])

        # D2 -- raise the ledger, raise the counter, recompute filing_posture.
        _, previous_filing = recompute_organization(organization, once=False)

        # D3 -- fires only where that recomputation actually flipped the posture.
        if organization["filing_posture"] == "DELINQUENT" and previous_filing != "DELINQUENT":
            denied_extension_request_ids.extend(
                deny_pending_extension_requests(organization["id"], swept_at)
            )

    # ---- second pass: expired fundraiser credentials ---------------------
    lapse_candidates = []
    for registration in db.fundraiser_registrations.values():
        if registration["status"] != "ACTIVE":
            continue
        if state_code is not None and registration["state_code"] != state_code:
            continue
        expires = parse_iso(registration["expires_at"])
        if expires is None or not (expires <= now):
            # Inclusive here, unlike the renewal test.
            continue
        lapse_candidates.append(registration)

    for registration in sorted_rows(lapse_candidates):
        registration["status"] = "LAPSED"
        touch_once(registration, "fundraiser_registration")
        lapsed_ids.append(registration["id"])
        firm = db.professional_fundraisers.get(registration["fundraiser_id"])
        if firm is not None:
            recompute_registry_status(firm)
        voided_contract_ids.extend(
            void_contracts_for_lapse(registration["fundraiser_id"], registration["state_code"])
        )

    return {
        "swept_at": swept_at,
        "delinquent_registration_count": len(delinquent_ids),
        "delinquent_registration_ids": delinquent_ids,
        "enforcement_action_ids": enforcement_action_ids,
        "lapsed_fundraiser_registration_ids": lapsed_ids,
        "voided_contract_ids": voided_contract_ids,
        "denied_extension_request_ids": denied_extension_request_ids,
    }
