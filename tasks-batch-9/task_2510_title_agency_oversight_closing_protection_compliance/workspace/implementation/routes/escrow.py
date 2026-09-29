"""Escrow trust accounts, three-way reconciliation audits and findings
(PRD 3.6, 3.7)."""

from flask import Blueprint

import calc
import db
import derive
import lookup
import middleware as mw
import response
import shape
import tx
from db import store
from errors import ApiError

bp = Blueprint("escrow", __name__)

AUDIT_TYPES = ("SCHEDULED", "SURPRISE")
AUDIT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "REMEDIATION_REQUIRED",
    "CLOSED_CLEAN",
    "CLOSED_ADVERSE",
)
AUDIT_TRANSITIONS = {
    "DRAFT": ("SUBMITTED",),
    "SUBMITTED": ("UNDER_REVIEW",),
    "UNDER_REVIEW": ("REMEDIATION_REQUIRED", "CLOSED_CLEAN", "CLOSED_ADVERSE"),
    "REMEDIATION_REQUIRED": ("SUBMITTED",),
}
AUDIT_TERMINALS = ("CLOSED_CLEAN", "CLOSED_ADVERSE")
AUDIT_OPEN_FOR_WRITING = ("SUBMITTED", "UNDER_REVIEW", "REMEDIATION_REQUIRED")
AUDIT_NON_TERMINAL = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REMEDIATION_REQUIRED")
AUDIT_TARGET_ROLE = {
    "SUBMITTED": (mw.ESCROW_AUDITOR,),
    "UNDER_REVIEW": (mw.COMPLIANCE_OFFICER,),
    "REMEDIATION_REQUIRED": (mw.COMPLIANCE_OFFICER,),
    # Closure is not narrowed beyond the endpoint roles; SoD-1 guards it.
    "CLOSED_CLEAN": None,
    "CLOSED_ADVERSE": None,
}

FINDING_CODES = (
    "THREE_WAY_VARIANCE",
    "UNIDENTIFIED_FUNDS_AGED",
    "NEGATIVE_FILE_BALANCE",
    "MISSING_RECONCILIATION",
    "COMMINGLING",
)
FINDING_STATUSES = ("OPEN", "REMEDIATION_SUBMITTED", "CLEARED", "ESCALATED")
FINDING_TRANSITIONS = {
    "OPEN": ("REMEDIATION_SUBMITTED", "ESCALATED"),
    "REMEDIATION_SUBMITTED": ("CLEARED", "ESCALATED"),
}
FINDING_TERMINALS = ("CLEARED", "ESCALATED")
FINDING_TARGET_ROLE = {
    "REMEDIATION_SUBMITTED": (mw.AGENCY_PRINCIPAL,),
    "CLEARED": (mw.ESCROW_AUDITOR, mw.COMPLIANCE_OFFICER),
    "ESCALATED": (mw.ESCROW_AUDITOR, mw.COMPLIANCE_OFFICER),
}
FINDING_OPEN_STATUSES = ("OPEN", "REMEDIATION_SUBMITTED")


# ---------------------------------------------------------------------------
# escrow accounts
# ---------------------------------------------------------------------------
@bp.post("/escrow-accounts")
def create_account():
    user_id, role = mw.require_roles(mw.AGENCY_PRINCIPAL)
    payload = shape.body()
    agency_id = shape.req_id(payload, "agency_id")
    bank_name = shape.req_str(payload, "bank_name")
    account_ref = shape.req_str(payload, "account_ref")

    agency = lookup.agency(agency_id)
    mw.require_ownership(user_id, role, agency["id"])

    # Tier 13 - unique among the agency's accounts that are not CLOSED
    for existing in store.where(db.ESCROW_ACCOUNT, agency_id=agency["id"]):
        if existing["status"] != "CLOSED" and existing["account_ref"] == account_ref:
            raise ApiError("ERR_DUPLICATE_ESCROW_ACCOUNT_REF")

    account = db.new_row(
        db.ESCROW_ACCOUNT,
        {
            "agency_id": agency["id"],
            "bank_name": bank_name,
            "account_ref": account_ref,
            "status": "OPEN",
            "book_balance_cents": 0,
            "bank_balance_cents": 0,
            "outstanding_items_cents": 0,
            "adjusted_bank_balance_cents": 0,
            "trial_balance_cents": 0,
            "unidentified_funds_cents": 0,
            "aged_unidentified_over_90_cents": 0,
            "snapshot_as_of": None,
        },
    )
    return response.created(account)


@bp.get("/escrow-accounts/<account_id>")
def read_account(account_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.escrow_account(account_id))


@bp.get("/escrow-accounts")
def list_accounts():
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "agency_id": shape.query_value("agency_id"),
        "status": shape.query_value("status"),
    }
    rows = [
        row
        for row in store.all(db.ESCROW_ACCOUNT)
        if all(v is None or row.get(k) == v for k, v in filters.items())
    ]
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/escrow-accounts/<account_id>/balance-snapshot")
def balance_snapshot(account_id):
    user_id, role = mw.require_roles(mw.AGENCY_PRINCIPAL)
    payload = shape.body()
    book = shape.req_cents(payload, "book_balance_cents")
    bank = shape.req_cents(payload, "bank_balance_cents")
    outstanding = shape.req_cents(payload, "outstanding_items_cents")
    trial = shape.req_cents(payload, "trial_balance_cents")
    unidentified = shape.req_cents(payload, "unidentified_funds_cents")
    aged = shape.req_cents(payload, "aged_unidentified_over_90_cents")
    as_of = shape.req_date(payload, "snapshot_as_of")

    account = lookup.escrow_account(account_id)
    agency = lookup.agency(account["agency_id"])
    mw.require_ownership(user_id, role, agency["id"])

    # Tier 10 - bookkeeping is allowed while RESTRICTED, refused when CLOSED
    if account["status"] == "CLOSED":
        raise ApiError("ERR_ESCROW_ACCOUNT_CLOSED")

    account["book_balance_cents"] = book
    account["bank_balance_cents"] = bank
    account["outstanding_items_cents"] = outstanding
    account["trial_balance_cents"] = trial
    account["unidentified_funds_cents"] = unidentified
    account["aged_unidentified_over_90_cents"] = aged
    account["snapshot_as_of"] = db.date_str(as_of)
    account["adjusted_bank_balance_cents"] = calc.adjusted_bank_balance(bank, outstanding)
    return response.ok(account)


# ---------------------------------------------------------------------------
# findings (shared by client creation and auto-raising)
# ---------------------------------------------------------------------------
def _is_repeat(audit, code):
    """True when the same code was raised on a strictly earlier audit of the
    same escrow account."""
    for other in store.all(db.FINDING):
        if other["code"] != code:
            continue
        parent = store.get(db.ESCROW_AUDIT, other["escrow_audit_id"])
        if parent is None or parent["id"] == audit["id"]:
            continue
        if parent["escrow_account_id"] != audit["escrow_account_id"]:
            continue
        if parent["created_at"] < audit["created_at"]:
            return True
    return False


def _create_finding(audit, code, exposure_cents, narrative):
    base = calc.base_severity(code, exposure_cents)
    is_repeat = _is_repeat(audit, code)
    return db.new_row(
        db.FINDING,
        {
            "escrow_audit_id": audit["id"],
            "code": code,
            "exposure_cents": exposure_cents,
            "narrative": narrative,
            "base_severity": base,
            "is_repeat": is_repeat,
            "severity": calc.effective_severity(base, is_repeat),
            "status": "OPEN",
            "remediation_note": None,
            "cleared_amount_cents": 0,
            "disposition_note": None,
        },
    )


@bp.post("/escrow-audits/<audit_id>/findings")
def create_finding(audit_id):
    mw.require_roles(mw.ESCROW_AUDITOR)
    payload = shape.body()
    code = shape.req_enum(payload, "code", FINDING_CODES)
    exposure = shape.req_cents(payload, "exposure_cents")
    narrative = shape.req_str(payload, "narrative")

    audit = lookup.escrow_audit(audit_id)
    agency = lookup.agency(audit["agency_id"])

    # Tier 10 - a closed audit's findings are frozen
    if audit["status"] not in AUDIT_OPEN_FOR_WRITING:
        raise ApiError("ERR_INVALID_STATE")

    finding = _create_finding(audit, code, exposure, narrative)
    derive.recompute_audit_counters(audit)
    previous = derive.recompute_agency(agency)
    derive.apply_freeze_to_accounts(agency, previous)
    return response.created(finding)


@bp.get("/escrow-audits/<audit_id>/findings")
def list_findings(audit_id):
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    audit = lookup.escrow_audit(audit_id)
    filters = {
        "code": shape.query_value("code"),
        "severity": shape.query_value("severity"),
        "status": shape.query_value("status"),
    }
    rows = [
        row
        for row in derive.audit_findings(audit["id"])
        if all(v is None or row.get(k) == v for k, v in filters.items())
    ]
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


@bp.get("/audit-findings/<finding_id>")
def read_finding(finding_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.finding(finding_id))


@bp.post("/audit-findings/<finding_id>/state")
def finding_state(finding_id):
    user_id, role = mw.require_roles(
        mw.AGENCY_PRINCIPAL, mw.ESCROW_AUDITOR, mw.COMPLIANCE_OFFICER
    )
    payload = shape.body()
    to_state = shape.req_enum(payload, "to_state", FINDING_STATUSES)
    remediation_note = None
    if to_state == "REMEDIATION_SUBMITTED":
        remediation_note = shape.req_str(payload, "remediation_note")
    cleared_amount = shape.opt_int(payload, "cleared_amount_cents", None, minimum=0)
    disposition_note = shape.opt_str(payload, "disposition_note")

    finding = lookup.finding(finding_id)
    audit = store.get(db.ESCROW_AUDIT, finding["escrow_audit_id"])
    agency = lookup.agency(audit["agency_id"])

    # Tier 6
    mw.require_ownership(user_id, role, agency["id"])
    # Tier 7
    mw.require_transition_role(role, FINDING_TARGET_ROLE.get(to_state))
    # Tier 10
    lookup.guard_transition(
        finding["status"], to_state, FINDING_TRANSITIONS, FINDING_TERMINALS
    )

    if to_state == "REMEDIATION_SUBMITTED":
        if audit["status"] not in AUDIT_OPEN_FOR_WRITING:
            raise ApiError("ERR_INVALID_STATE")
        finding["status"] = "REMEDIATION_SUBMITTED"
        finding["remediation_note"] = remediation_note
        if cleared_amount is not None:
            finding["cleared_amount_cents"] = cleared_amount
        # open_finding_count is deliberately unchanged: still an open finding.
        derive.recompute_audit_counters(audit)
        return response.ok(finding)

    finding["status"] = to_state
    if disposition_note is not None:
        finding["disposition_note"] = disposition_note
    derive.recompute_audit_counters(audit)
    previous = derive.recompute_agency(agency)
    derive.apply_freeze_to_accounts(agency, previous)
    return response.ok(finding)


# ---------------------------------------------------------------------------
# escrow audits
# ---------------------------------------------------------------------------
@bp.post("/escrow-audits")
def create_audit():
    user_id, role = mw.require_roles(mw.ESCROW_AUDITOR, mw.COMPLIANCE_OFFICER)
    payload = shape.body()
    agency_id = shape.req_id(payload, "agency_id")
    account_id = shape.req_id(payload, "escrow_account_id")
    audit_type = shape.req_enum(payload, "audit_type", AUDIT_TYPES)
    as_of_date = shape.req_date(payload, "as_of_date")
    follow_up_id = shape.opt_id(payload, "follow_up_of_audit_id")

    # Tier 5 - agency_id, escrow_account_id, follow_up_of_audit_id
    agency = lookup.agency(agency_id)
    account = lookup.escrow_account(account_id)
    if follow_up_id is not None:
        lookup.escrow_audit(follow_up_id)

    # Tier 10
    if account["status"] == "CLOSED":
        raise ApiError("ERR_ESCROW_ACCOUNT_CLOSED")

    # Tier 13
    existing_audits = store.where(db.ESCROW_AUDIT, escrow_account_id=account["id"])
    if audit_type == "SCHEDULED":
        for other in existing_audits:
            if other["audit_type"] != "SCHEDULED":
                continue
            other_as_of = db.parse_date(other["as_of_date"])
            if other_as_of is None:
                continue
            if abs((as_of_date - other_as_of).days) < calc.AUDIT_SPACING_DAYS:
                raise ApiError("ERR_AUDIT_SPACING_VIOLATION")
    else:
        for other in existing_audits:
            if other["audit_type"] == "SURPRISE" and other["status"] in AUDIT_NON_TERMINAL:
                raise ApiError("ERR_SURPRISE_AUDIT_IN_PROGRESS")

    audit = db.new_row(
        db.ESCROW_AUDIT,
        {
            "agency_id": agency["id"],
            "escrow_account_id": account["id"],
            "follow_up_of_audit_id": follow_up_id,
            "audit_type": audit_type,
            "as_of_date": db.date_str(as_of_date),
            "status": "DRAFT",
            "conducted_by_user_id": user_id,
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
    # An actor-initiated creation scores under the lifetime variant.
    previous = derive.recompute_defalcation_score(agency, "lifetime_uncleared")
    derive.apply_freeze_to_accounts(agency, previous)
    tx.force_agency_version_bump(agency)
    return response.created(audit)


@bp.get("/escrow-audits/<audit_id>")
def read_audit(audit_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.escrow_audit(audit_id))


@bp.get("/escrow-audits")
def list_audits():
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "agency_id": shape.query_value("agency_id"),
        "escrow_account_id": shape.query_value("escrow_account_id"),
        "follow_up_of_audit_id": shape.query_value("follow_up_of_audit_id"),
        "audit_type": shape.query_value("audit_type"),
        "status": shape.query_value("status"),
    }
    rows = [
        row
        for row in store.all(db.ESCROW_AUDIT)
        if all(v is None or row.get(k) == v for k, v in filters.items())
    ]
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/escrow-audits/<audit_id>/state")
def audit_state(audit_id):
    user_id, role = mw.require_roles(mw.ESCROW_AUDITOR, mw.COMPLIANCE_OFFICER)
    payload = shape.body()
    to_state = shape.req_enum(payload, "to_state", AUDIT_STATUSES)
    shape.opt_str(payload, "note")

    audit = lookup.escrow_audit(audit_id)
    agency = lookup.agency(audit["agency_id"])
    account = store.get(db.ESCROW_ACCOUNT, audit["escrow_account_id"])

    # Tier 7
    mw.require_transition_role(role, AUDIT_TARGET_ROLE.get(to_state))
    # Tier 8 - SoD-1 on either closure
    if to_state in AUDIT_TERMINALS:
        mw.require_segregation(user_id, audit["conducted_by_user_id"])
    # Tier 10
    lookup.guard_transition(audit["status"], to_state, AUDIT_TRANSITIONS, AUDIT_TERMINALS)

    if to_state == "SUBMITTED":
        _submit_audit(audit, agency, account)
    elif to_state == "UNDER_REVIEW":
        audit["status"] = "UNDER_REVIEW"
    elif to_state == "REMEDIATION_REQUIRED":
        if not any(
            f["status"] in FINDING_OPEN_STATUSES for f in derive.audit_findings(audit["id"])
        ):
            raise ApiError("ERR_NO_OPEN_FINDING")
        audit["status"] = "REMEDIATION_REQUIRED"
    else:
        _close_audit(audit, agency, user_id, to_state)

    return response.ok(audit)


def _submit_audit(audit, agency, account):
    # Tier 10
    if account is None or account["snapshot_as_of"] is None:
        raise ApiError("ERR_BALANCE_SNAPSHOT_REQUIRED")
    if account["status"] == "CLOSED":
        raise ApiError("ERR_ESCROW_ACCOUNT_CLOSED")

    method = calc.variance_method_for(audit["audit_type"])
    adjusted = calc.adjusted_bank_balance(
        account["bank_balance_cents"], account["outstanding_items_cents"]
    )
    variance = calc.reconciliation_variance(
        method, adjusted, account["book_balance_cents"], account["trial_balance_cents"]
    )
    audit["status"] = "SUBMITTED"
    audit["variance_method"] = method
    audit["reconciliation_variance_cents"] = variance
    audit["unidentified_funds_reviewed_cents"] = account["unidentified_funds_cents"]
    audit["submitted_at"] = db.clock_instant()

    live_codes = set(
        f["code"]
        for f in derive.audit_findings(audit["id"])
        if f["status"] in FINDING_OPEN_STATUSES
    )
    tolerance = derive.governing_tolerance_cents(agency["id"])
    if variance > tolerance and "THREE_WAY_VARIANCE" not in live_codes:
        _create_finding(
            audit,
            "THREE_WAY_VARIANCE",
            variance,
            "Auto-raised: reconciliation variance of %d cents exceeds the governing "
            "tolerance of %d cents." % (variance, tolerance),
        )
    aged = account["aged_unidentified_over_90_cents"]
    if aged > 0 and "UNIDENTIFIED_FUNDS_AGED" not in live_codes:
        _create_finding(
            audit,
            "UNIDENTIFIED_FUNDS_AGED",
            aged,
            "Auto-raised: %d cents of unidentified funds held more than ninety days."
            % aged,
        )

    derive.recompute_audit_counters(audit)
    previous = derive.recompute_agency(agency)
    derive.apply_freeze_to_accounts(agency, previous)


def _close_audit(audit, agency, user_id, to_state):
    findings = derive.audit_findings(audit["id"])
    # Tier 10 - finding-population requirements
    if to_state == "CLOSED_CLEAN":
        if any(f["status"] != "CLEARED" for f in findings):
            raise ApiError("ERR_UNREMEDIATED_FINDING_PRESENT")
    else:
        if not any(f["status"] == "ESCALATED" for f in findings):
            raise ApiError("ERR_NO_ESCALATED_FINDING")

    audit["status"] = to_state
    audit["closed_by_user_id"] = user_id
    audit["closed_at"] = db.clock_instant()
    derive.recompute_audit_counters(audit)
    previous = derive.recompute_defalcation_score(agency, "rolling_window_365")
    if to_state == "CLOSED_ADVERSE":
        derive.cascade_a(agency, audit)
    else:
        derive.apply_freeze_to_accounts(agency, previous)
    tx.force_agency_version_bump(agency)
