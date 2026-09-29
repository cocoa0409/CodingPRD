"""Remittance statements and lines: premium splits, reconciliation, CASCADE-C
settlement and both reopen paths (PRD 3.5)."""

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
from routes.cpl import require_expected_version
from routes.policy_files import ISSUED_STATUSES

bp = Blueprint("remittance", __name__)

STATEMENT_STATUSES = ("DRAFT", "SUBMITTED", "RECONCILED", "SETTLED")
STATEMENT_TRANSITIONS = {
    "DRAFT": ("SUBMITTED",),
    "SUBMITTED": ("RECONCILED",),
    "RECONCILED": ("SETTLED", "DRAFT"),
    "SETTLED": ("DRAFT",),
}
STATEMENT_TERMINALS = ()
# The statement dimension has no terminal state.
TARGET_ROLE = {
    "SUBMITTED": (mw.AGENCY_PRINCIPAL,),
    "RECONCILED": (mw.COMPLIANCE_OFFICER,),
    "SETTLED": (mw.COMPLIANCE_OFFICER,),
    # A reopen is not narrowed by the PRD, so both endpoint roles may reopen.
    "DRAFT": None,
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _refresh_totals(statement):
    lines = derive.statement_lines(statement["id"])
    statement["reported_gross_premium_cents"] = sum(
        line["reported_gross_premium_cents"] for line in lines
    )
    statement["agency_retention_cents"] = sum(
        line["agency_retention_cents"] for line in lines
    )
    statement["underwriter_share_cents"] = sum(
        line["underwriter_share_cents"] for line in lines
    )


def _expected_set(statement):
    """Every ISSUED / LATE_ISSUED policy file of the agency whose closing_date
    falls inside the statement period, inclusive."""
    period_start = db.parse_date(statement["period_start"])
    period_end = db.parse_date(statement["period_end"])
    out = []
    for pf in store.where(db.POLICY_FILE, agency_id=statement["agency_id"]):
        if pf["issuance_status"] not in ISSUED_STATUSES:
            continue
        closing = db.parse_date(pf["closing_date"])
        if closing is None or closing < period_start or closing > period_end:
            continue
        out.append(pf)
    return out


def _referenced_policies(statement):
    out = []
    seen = set()
    for line in derive.statement_lines(statement["id"]):
        if line["policy_file_id"] in seen:
            continue
        seen.add(line["policy_file_id"])
        pf = store.get(db.POLICY_FILE, line["policy_file_id"])
        if pf is not None:
            out.append(pf)
    return out


# ---------------------------------------------------------------------------
# statements
# ---------------------------------------------------------------------------
@bp.post("/remittance-statements")
def create_statement():
    user_id, role = mw.require_roles(mw.AGENCY_PRINCIPAL)
    payload = shape.body()
    agency_id = shape.req_id(payload, "agency_id")
    period_start = shape.req_date(payload, "period_start")
    period_end = shape.req_date(payload, "period_end")
    expected_version = shape.req_int(payload, "expected_agency_version")
    if period_start > period_end:
        raise shape.bad("period_start must not fall after period_end.")

    # Tier 5
    agency = lookup.agency(agency_id)
    # Tier 6
    mw.require_ownership(user_id, role, agency["id"])
    # Tier 9
    require_expected_version(agency, expected_version)
    # Tier 13 - two closed intervals overlap, in any status whatsoever
    for existing in store.where(db.STATEMENT, agency_id=agency["id"]):
        other_start = db.parse_date(existing["period_start"])
        other_end = db.parse_date(existing["period_end"])
        if period_start <= other_end and other_start <= period_end:
            raise ApiError("ERR_REMITTANCE_PERIOD_OVERLAP")

    statement = db.new_row(
        db.STATEMENT,
        {
            "agency_id": agency["id"],
            "period_start": db.date_str(period_start),
            "period_end": db.date_str(period_end),
            "status": "DRAFT",
            "reported_gross_premium_cents": 0,
            "underwriter_share_cents": 0,
            "agency_retention_cents": 0,
            "expected_gross_premium_cents": 0,
            "variance_cents": 0,
            "unreported_policy_count": 0,
            "unreported_premium_cents": 0,
            "late_fee_cents": 0,
            "settled_amount_cents": 0,
            "reopen_count": 0,
            "submitted_at": None,
            "reconciled_at": None,
            "settled_at": None,
            "reopen_reason": None,
        },
    )
    derive.recompute_agency(agency)
    tx.force_agency_version_bump(agency)
    return response.created(statement)


@bp.get("/remittance-statements/<statement_id>")
def read_statement(statement_id):
    mw.require_roles(*mw.ALL_ROLES)
    return response.ok(lookup.statement(statement_id))


@bp.get("/remittance-statements")
def list_statements():
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "agency_id": shape.query_value("agency_id"),
        "status": shape.query_value("status"),
    }
    rows = [
        row
        for row in store.all(db.STATEMENT)
        if all(v is None or row.get(k) == v for k, v in filters.items())
    ]
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# lines
# ---------------------------------------------------------------------------
@bp.post("/remittance-statements/<statement_id>/lines")
def create_line(statement_id):
    user_id, role = mw.require_roles(mw.AGENCY_PRINCIPAL)
    payload = shape.body()
    policy_file_id = shape.req_id(payload, "policy_file_id")
    reported = shape.req_positive_cents(payload, "reported_gross_premium_cents")

    # Tier 4 then tier 5
    statement = lookup.statement(statement_id)
    policy_file = lookup.policy_file(policy_file_id)
    agency = lookup.agency(statement["agency_id"])
    # Tier 6
    mw.require_ownership(user_id, role, agency["id"])

    # Tier 12
    if (
        policy_file["agency_id"] != statement["agency_id"]
        or policy_file["issuance_status"] not in ISSUED_STATUSES
    ):
        raise ApiError("ERR_LINE_POLICY_NOT_ISSUED")
    closing = db.parse_date(policy_file["closing_date"])
    if closing is None or closing < db.parse_date(
        statement["period_start"]
    ) or closing > db.parse_date(statement["period_end"]):
        raise ApiError("ERR_POLICY_NOT_IN_PERIOD")
    # Tier 13
    for existing in derive.statement_lines(statement["id"]):
        if existing["policy_file_id"] == policy_file["id"]:
            raise ApiError("ERR_POLICY_ALREADY_ON_STATEMENT")

    program = store.get(db.STATE_PROGRAM, policy_file["state_program_id"])
    retention, share = calc.line_split(reported, program["premium_split_agency_pct"])
    line = db.new_row(
        db.LINE,
        {
            "remittance_statement_id": statement["id"],
            "policy_file_id": policy_file["id"],
            "reported_gross_premium_cents": reported,
            "agency_retention_cents": retention,
            "underwriter_share_cents": share,
            "premium_mismatch": reported != policy_file["gross_premium_cents"],
        },
    )
    _refresh_totals(statement)
    return response.created(line)


@bp.get("/remittance-statements/<statement_id>/lines")
def list_statement_lines(statement_id):
    mw.require_roles(*mw.ALL_ROLES)
    limit, offset = shape.pagination()
    statement = lookup.statement(statement_id)
    mismatch = shape.query_bool("premium_mismatch")
    rows = [
        line
        for line in derive.statement_lines(statement["id"])
        if mismatch is None or line["premium_mismatch"] == mismatch
    ]
    return response.ok_list(shape.page(rows, limit, offset), limit, offset, len(rows))


# ---------------------------------------------------------------------------
# statement state machine
# ---------------------------------------------------------------------------
@bp.post("/remittance-statements/<statement_id>/state")
def statement_state(statement_id):
    user_id, role = mw.require_roles(mw.AGENCY_PRINCIPAL, mw.COMPLIANCE_OFFICER)
    payload = shape.body()
    to_state = shape.req_enum(payload, "to_state", STATEMENT_STATUSES)
    settled_amount = None
    reopen_reason = None
    if to_state == "SETTLED":
        settled_amount = shape.req_cents(payload, "settled_amount_cents")
    if to_state == "DRAFT":
        reopen_reason = shape.req_str(payload, "reopen_reason")

    statement = lookup.statement(statement_id)
    agency = lookup.agency(statement["agency_id"])
    # Tier 6
    mw.require_ownership(user_id, role, agency["id"])
    # Tier 7
    mw.require_transition_role(role, TARGET_ROLE.get(to_state))
    # Tier 10
    lookup.guard_transition(
        statement["status"], to_state, STATEMENT_TRANSITIONS, STATEMENT_TERMINALS
    )

    if to_state == "SUBMITTED":
        _submit(statement, agency)
    elif to_state == "RECONCILED":
        _reconcile(statement, agency)
    elif to_state == "SETTLED":
        _settle(statement, agency, settled_amount)
    elif statement["status"] == "SETTLED":
        _reopen_from_settled(statement, agency, reopen_reason)
    else:
        _reopen_from_reconciled(statement, agency, reopen_reason)

    return response.ok(statement)


def _submit(statement, agency):
    # Tier 10
    if not derive.statement_lines(statement["id"]):
        raise ApiError("ERR_STATEMENT_HAS_NO_LINES")
    if agency["appointment_status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE")
    statement["status"] = "SUBMITTED"
    statement["submitted_at"] = db.clock_instant()
    _refresh_totals(statement)


def _reconcile(statement, agency):
    expected = _expected_set(statement)
    referenced_ids = set(
        line["policy_file_id"] for line in derive.statement_lines(statement["id"])
    )
    unreported = [pf for pf in expected if pf["id"] not in referenced_ids]

    expected_total = sum(pf["gross_premium_cents"] for pf in expected)
    _refresh_totals(statement)
    statement["expected_gross_premium_cents"] = expected_total
    statement["variance_cents"] = (
        expected_total - statement["reported_gross_premium_cents"]
    )
    statement["unreported_policy_count"] = len(unreported)
    statement["unreported_premium_cents"] = sum(
        pf["gross_premium_cents"] for pf in unreported
    )

    period_end = db.parse_date(statement["period_end"])
    submitted = db.parse_datetime(statement["submitted_at"])
    filing_late = False
    if submitted is not None:
        grace_end = period_end + _timedelta(calc.REMITTANCE_GRACE_DAYS)
        filing_late = submitted.date() > grace_end
    statement["late_fee_cents"] = calc.late_fee(
        statement["unreported_premium_cents"], filing_late
    )

    statement["status"] = "RECONCILED"
    statement["reconciled_at"] = db.clock_instant()

    # The reported policies' accounting dimension advances with the line
    for line in derive.statement_lines(statement["id"]):
        pf = store.get(db.POLICY_FILE, line["policy_file_id"])
        if pf is None or pf["remittance_status"] != "UNREPORTED":
            continue
        if pf["issuance_status"] not in ISSUED_STATUSES:
            continue
        pf["remittance_status"] = "DISPUTED" if line["premium_mismatch"] else "REPORTED"

    previous = derive.recompute_agency(agency)
    derive.apply_freeze_to_accounts(agency, previous)
    tx.force_agency_version_bump(agency)


def _settle(statement, agency, settled_amount):
    # Tier 14 - the settlement amount identity
    due = statement["underwriter_share_cents"] + statement["late_fee_cents"]
    if settled_amount != due:
        raise ApiError("ERR_SETTLEMENT_AMOUNT_MISMATCH")

    # Hop 1
    statement["status"] = "SETTLED"
    statement["settled_at"] = db.clock_instant()
    statement["settled_amount_cents"] = settled_amount
    # Hop 2 - REPORTED policies become REMITTED, DISPUTED stay put
    for pf in _referenced_policies(statement):
        if pf["remittance_status"] == "REPORTED":
            pf["remittance_status"] = "REMITTED"
    # Hops 3 and 4
    previous = derive.recompute_agency(agency)
    # Hop 5
    if previous in ("FROZEN", "RESTRICTED") and agency["oversight_posture"] == "OPEN":
        derive.release_restricted_accounts(agency)
    derive.apply_freeze_to_accounts(agency, previous)
    tx.force_agency_version_bump(agency)


def _reset_reconciliation_outputs(statement):
    statement["expected_gross_premium_cents"] = 0
    statement["variance_cents"] = 0
    statement["unreported_policy_count"] = 0
    statement["unreported_premium_cents"] = 0
    statement["late_fee_cents"] = 0


def _reopen_from_settled(statement, agency, reopen_reason):
    statement["status"] = "DRAFT"
    statement["reopen_reason"] = reopen_reason
    statement["reopen_count"] = statement["reopen_count"] + 1
    statement["settled_at"] = None
    statement["reconciled_at"] = None
    statement["submitted_at"] = None
    _reset_reconciliation_outputs(statement)
    for pf in _referenced_policies(statement):
        if pf["remittance_status"] == "REMITTED":
            pf["remittance_status"] = "REPORTED"
        elif pf["remittance_status"] == "DISPUTED":
            pf["remittance_status"] = "UNREPORTED"
    previous = derive.recompute_agency(agency)
    derive.apply_freeze_to_accounts(agency, previous)
    tx.force_agency_version_bump(agency)


def _reopen_from_reconciled(statement, agency, reopen_reason):
    statement["status"] = "DRAFT"
    statement["reopen_reason"] = reopen_reason
    statement["reopen_count"] = statement["reopen_count"] + 1
    _reset_reconciliation_outputs(statement)
    for pf in _referenced_policies(statement):
        if pf["remittance_status"] in ("REPORTED", "DISPUTED"):
            pf["remittance_status"] = "UNREPORTED"
    previous = derive.recompute_agency(agency)
    derive.apply_freeze_to_accounts(agency, previous)
    tx.force_agency_version_bump(agency)


def _timedelta(days):
    from datetime import timedelta

    return timedelta(days=days)
