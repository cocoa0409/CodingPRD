"""Tier 4 / tier 5 reference resolution and the generic state-tier guard."""

import db
from db import store
from errors import ApiError

_NOT_FOUND = {
    db.AGENCY: "ERR_AGENCY_NOT_FOUND",
    db.STATE_PROGRAM: "ERR_STATE_PROGRAM_NOT_FOUND",
    db.APPOINTMENT: "ERR_AGENCY_APPOINTMENT_NOT_FOUND",
    db.CPL: "ERR_CPL_NOT_FOUND",
    db.POLICY_FILE: "ERR_POLICY_FILE_NOT_FOUND",
    db.STATEMENT: "ERR_REMITTANCE_STATEMENT_NOT_FOUND",
    db.ESCROW_ACCOUNT: "ERR_ESCROW_ACCOUNT_NOT_FOUND",
    db.ESCROW_AUDIT: "ERR_ESCROW_AUDIT_NOT_FOUND",
    db.FINDING: "ERR_AUDIT_FINDING_NOT_FOUND",
    db.CLAIM: "ERR_AGENCY_CLAIM_NOT_FOUND",
}


def must(kind, row_id):
    row = store.get(kind, row_id)
    if row is None:
        raise ApiError(_NOT_FOUND[kind])
    return row


def agency(row_id):
    return must(db.AGENCY, row_id)


def state_program(row_id):
    return must(db.STATE_PROGRAM, row_id)


def appointment(row_id):
    return must(db.APPOINTMENT, row_id)


def letter(row_id):
    return must(db.CPL, row_id)


def policy_file(row_id):
    return must(db.POLICY_FILE, row_id)


def statement(row_id):
    return must(db.STATEMENT, row_id)


def escrow_account(row_id):
    return must(db.ESCROW_ACCOUNT, row_id)


def escrow_audit(row_id):
    return must(db.ESCROW_AUDIT, row_id)


def finding(row_id):
    return must(db.FINDING, row_id)


def claim(row_id):
    return must(db.CLAIM, row_id)


def guard_transition(current, to_state, transitions, terminals):
    """Tier 10, first two clauses.  A terminal dimension is reported as such so
    both ERR_ALREADY_TERMINAL and ERR_INVALID_STATE stay reachable."""
    if current in terminals:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if to_state not in transitions.get(current, ()):
        raise ApiError("ERR_INVALID_STATE")
