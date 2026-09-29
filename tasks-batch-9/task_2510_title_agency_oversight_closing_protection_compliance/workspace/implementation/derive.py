"""Derived values, counters, ledgers and the three named cascades.

Both conserved ledgers (`cpl_outstanding_exposure_cents` and
`unremitted_premium_cents`) are always recomputed from the underlying rows and
never adjusted by a delta (PRD 2.7).
"""

import calc
import db
from db import store


# ---------------------------------------------------------------------------
# row collections
# ---------------------------------------------------------------------------
def agency_audits(agency_id):
    return store.where(db.ESCROW_AUDIT, agency_id=agency_id)


def audit_findings(audit_id):
    return store.where(db.FINDING, escrow_audit_id=audit_id)


def agency_findings(agency_id):
    out = []
    for audit in agency_audits(agency_id):
        out.extend(audit_findings(audit["id"]))
    out.sort(key=lambda r: r["_seq"])
    return out


def statement_lines(statement_id):
    return store.where(db.LINE, remittance_statement_id=statement_id)


def active_appointment(agency_id, state_program_id):
    for appt in store.where(
        db.APPOINTMENT, agency_id=agency_id, state_program_id=state_program_id
    ):
        if appt["status"] == "ACTIVE":
            return appt
    return None


def governing_tolerance_cents(agency_id):
    """three_way_tolerance_cents of the state program attached to the agency's
    oldest ACTIVE appointment (earliest created_at)."""
    for appt in store.where(db.APPOINTMENT, agency_id=agency_id):
        if appt["status"] == "ACTIVE":
            program = store.get(db.STATE_PROGRAM, appt["state_program_id"])
            if program is not None:
                return program["three_way_tolerance_cents"]
    return 0


# ---------------------------------------------------------------------------
# escrow audit counters and risk tier (PRD 3.7)
# ---------------------------------------------------------------------------
def recompute_audit_counters(audit):
    findings = audit_findings(audit["id"])
    open_count = len(
        [f for f in findings if f["status"] in ("OPEN", "REMEDIATION_SUBMITTED")]
    )
    critical_count = len(
        [f for f in findings if f["severity"] == "CRITICAL" and f["status"] != "CLEARED"]
    )
    audit["open_finding_count"] = open_count
    audit["critical_finding_count"] = critical_count
    if any(f["severity"] == "CRITICAL" and f["status"] != "CLEARED" for f in findings):
        tier = "CRITICAL"
    elif any(f["severity"] == "HIGH" and f["status"] != "CLEARED" for f in findings):
        tier = "HIGH"
    elif open_count >= 1:
        tier = "MEDIUM"
    else:
        tier = "LOW"
    audit["risk_tier"] = tier


# ---------------------------------------------------------------------------
# agency ledgers, counters and posture
# ---------------------------------------------------------------------------
def cpl_outstanding_exposure(agency_id):
    total = 0
    for letter in store.where(db.CPL, agency_id=agency_id):
        if letter["status"] == "ISSUED":
            total += letter["approved_coverage_cents"]
    return total


def unremitted_premium(agency_id):
    total = 0
    for pf in store.where(db.POLICY_FILE, agency_id=agency_id):
        if pf["issuance_status"] in ("ISSUED", "LATE_ISSUED") and pf[
            "remittance_status"
        ] in ("UNREPORTED", "REPORTED", "DISPUTED"):
            total += pf["gross_premium_cents"]
    return total


def open_critical_finding_count(agency_id):
    count = 0
    for finding in agency_findings(agency_id):
        if finding["severity"] == "CRITICAL" and finding["status"] in (
            "OPEN",
            "REMEDIATION_SUBMITTED",
            "ESCALATED",
        ):
            count += 1
    return count


def mirrored_unreported_policy_count(agency_id):
    """The unreported_policy_count of the agency's most recently reconciled
    statement; 0 when no statement of the agency remains RECONCILED."""
    candidates = [
        s
        for s in store.where(db.STATEMENT, agency_id=agency_id)
        if s["status"] == "RECONCILED" and s["reconciled_at"] is not None
    ]
    if not candidates:
        return 0
    candidates.sort(key=lambda s: (s["reconciled_at"], s["_seq"]))
    return candidates[-1]["unreported_policy_count"]


def pending_transfer_count(agency_id):
    count = 0
    for pf in store.where(db.POLICY_FILE, agency_id=agency_id):
        if pf["transfer_status"] in ("PENDING_TRANSFER", "TRANSFER_EXCEPTION"):
            count += 1
    return count


def last_remittance_period_end(agency_id):
    ends = [s["period_end"] for s in store.where(db.STATEMENT, agency_id=agency_id)]
    if not ends:
        return None
    return max(ends)


def recompute_agency(agency):
    """Recompute every purely derived agency field, then the posture.

    Returns the posture the agency held before the recomputation.
    """
    agency_id = agency["id"]
    agency["open_critical_finding_count"] = open_critical_finding_count(agency_id)
    agency["unreported_policy_count"] = mirrored_unreported_policy_count(agency_id)
    agency["cpl_outstanding_exposure_cents"] = cpl_outstanding_exposure(agency_id)
    agency["unremitted_premium_cents"] = unremitted_premium(agency_id)
    agency["pending_transfer_count"] = pending_transfer_count(agency_id)
    agency["last_remittance_period_end"] = last_remittance_period_end(agency_id)
    previous = agency["oversight_posture"]
    agency["oversight_posture"] = calc.oversight_posture(agency)
    return previous


# ---------------------------------------------------------------------------
# defalcation score (PRD 3.7, two variants)
# ---------------------------------------------------------------------------
def recompute_defalcation_score(agency, variant):
    agency_id = agency["id"]
    audits = agency_audits(agency_id)
    audits_by_id = dict((a["id"], a) for a in audits)
    findings = agency_findings(agency_id)
    claims = store.where(db.CLAIM, agency_id=agency_id)

    if variant == "rolling_window_365":
        window_start = db.clock_date() - _days(calc.DEFALCATION_WINDOW_DAYS)

        def finding_in_scope(finding):
            parent = audits_by_id.get(finding["escrow_audit_id"])
            if parent is None:
                return False
            as_of = db.parse_date(parent["as_of_date"])
            return as_of is not None and as_of >= window_start

        def audit_in_scope(audit):
            as_of = db.parse_date(audit["as_of_date"])
            return as_of is not None and as_of >= window_start

        def claim_in_scope(claim):
            notice = db.parse_date(claim["notice_date"])
            return notice is not None and notice >= window_start

        scoped_findings = [f for f in findings if finding_in_scope(f)]
        adverse = len(
            [a for a in audits if a["status"] == "CLOSED_ADVERSE" and audit_in_scope(a)]
        )
        defalcation_claims = len(
            [
                c
                for c in claims
                if c["cause_code"] == "ESCROW_DEFALCATION"
                and c["status"] != "INVESTIGATING"
                and claim_in_scope(c)
            ]
        )
    else:  # lifetime_uncleared
        scoped_findings = [f for f in findings if f["status"] != "CLEARED"]
        adverse = len([a for a in audits if a["status"] == "CLOSED_ADVERSE"])
        defalcation_claims = len(
            [
                c
                for c in claims
                if c["cause_code"] == "ESCROW_DEFALCATION"
                and c["status"] != "INVESTIGATING"
            ]
        )

    critical = len([f for f in scoped_findings if f["severity"] == "CRITICAL"])
    high = len([f for f in scoped_findings if f["severity"] == "HIGH"])

    score = calc.defalcation_score(critical, high, adverse, defalcation_claims)
    agency["defalcation_score"] = score
    agency["escrow_standing"] = calc.escrow_standing_for(score)
    return recompute_agency(agency)


def _days(n):
    from datetime import timedelta

    return timedelta(days=n)


# ---------------------------------------------------------------------------
# posture-driven side effects on escrow accounts and letters
# ---------------------------------------------------------------------------
def restrict_open_accounts(agency):
    """Every escrow account whose status is OPEN moves to RESTRICTED,
    in ascending created_at order."""
    for account in store.where(db.ESCROW_ACCOUNT, agency_id=agency["id"]):
        if account["status"] == "OPEN":
            account["status"] = "RESTRICTED"


def release_restricted_accounts(agency):
    """Every escrow account whose status is RESTRICTED moves back to OPEN."""
    for account in store.where(db.ESCROW_ACCOUNT, agency_id=agency["id"]):
        if account["status"] == "RESTRICTED":
            account["status"] = "OPEN"


def apply_freeze_to_accounts(agency, previous_posture):
    """The posture's own downstream effect on trust accounts: an agency that has
    just landed on FROZEN has its OPEN accounts restricted."""
    if agency["oversight_posture"] == "FROZEN" and previous_posture != "FROZEN":
        restrict_open_accounts(agency)


def decline_letters_in_flight(agency, state_program_ids=None):
    """Letters in REQUESTED or REFERRED move to DECLINED with SYSTEM as the
    decider, in ascending created_at order."""
    for letter in store.where(db.CPL, agency_id=agency["id"]):
        if letter["status"] not in ("REQUESTED", "REFERRED"):
            continue
        if state_program_ids is not None and letter["state_program_id"] not in state_program_ids:
            continue
        letter["status"] = "DECLINED"
        letter["decided_by_user_id"] = "SYSTEM"


# ---------------------------------------------------------------------------
# CASCADE-A - adverse escrow audit closure (PRD 3.7)
# ---------------------------------------------------------------------------
def cascade_a(agency, closed_audit):
    """Hops 4 and 5, fired because the recomputed posture is FROZEN."""
    if agency["oversight_posture"] != "FROZEN":
        return
    restrict_open_accounts(agency)
    decline_letters_in_flight(agency)
    db.new_row(
        db.ESCROW_AUDIT,
        {
            "agency_id": agency["id"],
            "escrow_account_id": closed_audit["escrow_account_id"],
            "follow_up_of_audit_id": closed_audit["id"],
            "audit_type": "SURPRISE",
            "as_of_date": db.date_str(db.clock_date()),
            "status": "DRAFT",
            "conducted_by_user_id": "SYSTEM",
            "closed_by_user_id": None,
            "variance_method": None,
            "reconciliation_variance_cents": 0,
            "unidentified_funds_reviewed_cents": 0,
            "risk_tier": "LOW",
            "open_finding_count": 0,
            "critical_finding_count": 0,
            "submitted_at": None,
            "closed_at": None,
        },
    )


# ---------------------------------------------------------------------------
# CASCADE-B - agency termination (PRD 3.9)
# ---------------------------------------------------------------------------
def cascade_b(agency, termination_reason, transferee_agency_id):
    # Hop 1
    agency["appointment_status"] = "TERMINATED"
    agency["termination_reason"] = termination_reason
    agency["transferee_agency_id"] = transferee_agency_id

    # Hop 2 - the posture becomes FROZEN
    recompute_agency(agency)

    # Hop 3 - appointments withdrawn, ascending created_at
    withdrawn_programs = set()
    for appt in store.where(db.APPOINTMENT, agency_id=agency["id"]):
        if appt["status"] in ("PENDING_LICENSE_VERIFICATION", "ACTIVE", "LAPSED"):
            appt["status"] = "WITHDRAWN"
            withdrawn_programs.add(appt["state_program_id"])

    # Hop 4 - letters of a withdrawn state program declined, ascending created_at
    declined_letter_ids = []
    for letter in store.where(db.CPL, agency_id=agency["id"]):
        if letter["status"] in ("REQUESTED", "REFERRED") and letter[
            "state_program_id"
        ] in withdrawn_programs:
            letter["status"] = "DECLINED"
            letter["decided_by_user_id"] = "SYSTEM"
            declined_letter_ids.append(letter["id"])

    # Hop 5 - files backed by those letters and still un-issued are voided
    for pf in store.all(db.POLICY_FILE):
        if pf["cpl_id"] in declined_letter_ids and pf["issuance_status"] in (
            "PENDING",
            "PENDING_REFERRAL",
        ):
            pf["issuance_status"] = "VOIDED"

    # Also caused by hop 1: in-force files leave for the transferee
    for pf in store.where(db.POLICY_FILE, agency_id=agency["id"]):
        if pf["issuance_status"] in ("ISSUED", "LATE_ISSUED") and pf[
            "transfer_status"
        ] == "NOT_REQUIRED":
            pf["transfer_status"] = "PENDING_TRANSFER"
            pf["transferee_agency_id"] = transferee_agency_id

    # Also caused by hop 1 through the posture change: OPEN accounts close
    for account in store.where(db.ESCROW_ACCOUNT, agency_id=agency["id"]):
        if account["status"] == "OPEN":
            account["status"] = "CLOSED"

    recompute_agency(agency)


# ---------------------------------------------------------------------------
# transferee eligibility (PRD 3.9)
# ---------------------------------------------------------------------------
def transferee_eligible(transferee, terminated_agency_id):
    if transferee is None:
        return False
    if transferee["id"] == terminated_agency_id:
        return False
    if transferee["appointment_status"] != "APPOINTED":
        return False
    if transferee["oversight_posture"] == "FROZEN":
        return False
    return True
