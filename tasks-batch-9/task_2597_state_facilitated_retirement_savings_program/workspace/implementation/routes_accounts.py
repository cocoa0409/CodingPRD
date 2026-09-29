"""Participant accounts, investment elections, earnings, closure and excess cases."""
from flask import Blueprint

import calc
import engine
import serializers
from auth import get_account, get_excess_case, own_participant, require
from errors import fail
from response import created, paginate, query_filter, query_int, single
from store import db
from util import parse_date, parse_instant
from validate import parse_body

bp = Blueprint("accounts", __name__)

ACCOUNT_ROLES = ["ProgramAdministrator", "ComplianceOfficer", "Recordkeeper", "Participant"]
ACCOUNT_STATUSES = ("OPEN", "CLOSURE_PENDING", "CLOSED")
ACCOUNT_TYPES = ("ROTH_IRA", "TRADITIONAL_IRA")
POSTURES = ("UNRESTRICTED", "RESTRICTED", "LOCKED")
ELECTION_STATUSES = ("ACTIVE", "SUPERSEDED")
ELECTION_SOURCES = ("SYSTEM_DEFAULT", "PARTICIPANT_ELECTED")
CASE_STATUSES = ("DETECTED", "METHOD_ELECTED", "COMPLETED", "EXPIRED", "VOIDED")
CORRECTION_METHODS = ("REFUND_TO_PARTICIPANT", "RECHARACTERIZE_TO_TRADITIONAL", "CARRY_FORWARD")
CLOSURE_REASONS = ("PARTICIPANT_REQUEST", "ROLLOVER_OUT", "DECEASED", "PROGRAM_ACTION")
RESIDUAL_DISPOSITIONS = ("ROLLOVER_OUT", "CASH_DISTRIBUTION")


@bp.route("/participant-accounts/<account_id>", methods=["GET"])
def read_account(account_id):
    principal = require(ACCOUNT_ROLES)
    account = get_account(account_id)
    own_participant(principal, account["participant_id"])
    return single(serializers.account(account))


@bp.route("/participant-accounts", methods=["GET"])
def list_accounts():
    principal = require(ACCOUNT_ROLES)
    participant_id = query_filter("participant_id")
    rolled_over_from = query_filter("rolled_over_from_account_id")
    status = query_filter("account_status", ACCOUNT_STATUSES)
    account_type = query_filter("account_type", ACCOUNT_TYPES)
    posture = query_filter("posture", POSTURES)
    rows = db.ordered("participant_accounts")
    for row in rows:
        calc.refresh_account(row)
    if principal.is_participant:
        rows = [a for a in rows if a["participant_id"] == principal.user_id]
    if participant_id is not None:
        rows = [a for a in rows if a["participant_id"] == participant_id]
    if rolled_over_from is not None:
        rows = [a for a in rows if a["rolled_over_from_account_id"] == rolled_over_from]
    if status is not None:
        rows = [a for a in rows if a["account_status"] == status]
    if account_type is not None:
        rows = [a for a in rows if a["account_type"] == account_type]
    if posture is not None:
        rows = [a for a in rows if a["posture"] == posture]
    return paginate(rows, serializers.account)


# ---------------------------------------------------------- investment elections

@bp.route("/participant-accounts/<account_id>/investment-elections", methods=["POST"])
def create_election(account_id):
    principal = require(["Participant", "ProgramAdministrator"])
    account = get_account(account_id)
    own_participant(principal, account["participant_id"])
    parsed = parse_body({
        "allocations": {"type": "array", "required": True, "min_items": 1},
        "expected_account_version": {"type": "int", "required": True},
    })
    allocations = []
    for entry in parsed["allocations"]:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "each allocation must be an object")
        code = entry.get("fund_code")
        weight = entry.get("allocation_bp")
        if not isinstance(code, str) or not code:
            fail("ERR_INVALID_REQUEST", "each allocation needs a fund_code")
        if isinstance(weight, bool) or not isinstance(weight, int):
            fail("ERR_INVALID_REQUEST", "each allocation needs an integer allocation_bp")
        allocations.append({"fund_code": code, "allocation_bp": weight})
    if parsed["expected_account_version"] != int(account["version"]):
        fail("ERR_STALE_ACCOUNT_VERSION",
             "the account has advanced to version %d" % int(account["version"]))
    if account["account_status"] == "CLOSED":
        fail("ERR_ACCOUNT_CLOSED", "this account is closed")
    menu = {o["fund_code"]: o for o in db.investment_options.values()}
    for entry in allocations:
        option = menu.get(entry["fund_code"])
        if option is None or option["status"] != "OPEN":
            fail("ERR_FUND_NOT_AVAILABLE",
                 "fund %s is not available for new elections" % entry["fund_code"])
    codes = [entry["fund_code"] for entry in allocations]
    if len(set(codes)) != len(codes):
        fail("ERR_ALLOCATION_TOTAL_INVALID", "a fund_code may not appear twice")
    if any(entry["allocation_bp"] <= 0 for entry in allocations):
        fail("ERR_ALLOCATION_TOTAL_INVALID", "every allocation_bp must be greater than zero")
    if sum(entry["allocation_bp"] for entry in allocations) != calc.FULL_ALLOCATION_BP:
        fail("ERR_ALLOCATION_TOTAL_INVALID", "allocation weights must sum to exactly 10000")
    election = engine.new_election(account, allocations, "PARTICIPANT_ELECTED", None)
    calc.refresh_account(account, bump=True)
    return created(serializers.election(election))


@bp.route("/participant-accounts/<account_id>/investment-elections", methods=["GET"])
def list_elections(account_id):
    principal = require(ACCOUNT_ROLES)
    account = get_account(account_id)
    own_participant(principal, account["participant_id"])
    status = query_filter("status", ELECTION_STATUSES)
    source = query_filter("source", ELECTION_SOURCES)
    rows = [e for e in db.ordered("investment_elections") if e["account_id"] == account_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    if source is not None:
        rows = [e for e in rows if e["source"] == source]
    return paginate(rows, serializers.election)


# ------------------------------------------------------------ earnings postings

@bp.route("/participant-accounts/<account_id>/earnings-postings", methods=["POST"])
def post_earnings(account_id):
    require(["Recordkeeper"])
    account = get_account(account_id)
    parsed = parse_body({
        "earnings_cents": {"type": "int", "required": True},
        "posting_date": {"type": "date", "required": True},
    })
    if account["account_status"] == "CLOSED":
        fail("ERR_ACCOUNT_CLOSED", "this account is closed")
    account["balance_cents"] = int(account["balance_cents"]) + int(parsed["earnings_cents"])
    calc.refresh_account(account, bump=True)
    return single(serializers.account(account))


# --------------------------------------------------------------------- closure

@bp.route("/participant-accounts/<account_id>/closure-requests", methods=["POST"])
def request_closure(account_id):
    principal = require(["Participant", "ProgramAdministrator"])
    account = get_account(account_id)
    own_participant(principal, account["participant_id"])
    parsed = parse_body({
        "closure_reason": {"type": "str", "required": True, "enum": CLOSURE_REASONS},
        "residual_disposition": {"type": "str", "required": True, "enum": RESIDUAL_DISPOSITIONS},
    })
    if account["account_status"] == "CLOSED":
        fail("ERR_ACCOUNT_CLOSED", "this account is closed")
    if calc.account_posture(account) != "UNRESTRICTED":
        fail("ERR_ACCOUNT_RESTRICTED", "this account is not free of holds")
    account["account_status"] = "CLOSURE_PENDING"
    account["closure_reason"] = parsed["closure_reason"]
    account["residual_disposition"] = parsed["residual_disposition"]
    calc.refresh_account(account, bump=True)
    return single(serializers.account(account))


@bp.route("/participant-accounts/<account_id>/closure-completion", methods=["POST"])
def complete_closure(account_id):
    require(["Recordkeeper"])
    account = get_account(account_id)
    parse_body({"completion_note": {"type": "str", "nullable": True}})
    if account["account_status"] != "CLOSURE_PENDING":
        fail("ERR_CLOSURE_STATE_INVALID", "this account is not awaiting closure")
    for case in calc.account_cases(account_id):
        if case["status"] in ("DETECTED", "METHOD_ELECTED"):
            fail("ERR_CLOSURE_STATE_INVALID",
                 "an unresolved excess-contribution case is still open on this account")
    if int(account["balance_cents"]) != 0:
        fail("ERR_RESIDUAL_BALANCE_PRESENT", "this account still holds money")
    election = calc.active_election(account_id)
    if election is not None:
        election["status"] = "SUPERSEDED"
        election["superseded_at"] = db.now_iso()
        db.touch(election)
    account["account_status"] = "CLOSED"
    account["closed_at"] = db.now_iso()
    calc.refresh_account(account, bump=True)
    account["active_election_id"] = None
    return single(serializers.account(account))


# ------------------------------------------------------ excess contribution cases

@bp.route("/participant-accounts/<account_id>/excess-contribution-cases", methods=["GET"])
def list_account_cases(account_id):
    principal = require(ACCOUNT_ROLES)
    account = get_account(account_id)
    own_participant(principal, account["participant_id"])
    status = query_filter("status", CASE_STATUSES)
    year = query_int("calendar_year")
    rows = [c for c in db.ordered("excess_cases") if c["account_id"] == account_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if year is not None:
        rows = [c for c in rows if int(c["calendar_year"]) == year]
    return paginate(rows, serializers.excess_case)


def _case_scope(principal, case):
    account = db.participant_accounts.get(case["account_id"])
    if account is not None:
        own_participant(principal, account["participant_id"])
    return account


@bp.route("/excess-contribution-cases/<case_id>", methods=["GET"])
def read_case(case_id):
    principal = require(ACCOUNT_ROLES)
    case = get_excess_case(case_id)
    _case_scope(principal, case)
    return single(serializers.excess_case(case))


@bp.route("/excess-contribution-cases/<case_id>/method-election", methods=["POST"])
def elect_method(case_id):
    principal = require(["Participant", "ProgramAdministrator"])
    case = get_excess_case(case_id)
    _case_scope(principal, case)
    parsed = parse_body({
        "correction_method": {"type": "str", "required": True, "enum": CORRECTION_METHODS},
    })
    if case["status"] != "DETECTED":
        fail("ERR_EXCESS_CASE_STATE_INVALID", "this case is not awaiting a method election")
    if db.today() > parse_date(case["deadline_date"]):
        fail("ERR_CORRECTION_DEADLINE_PASSED", "the correction deadline has passed")
    case["correction_method"] = parsed["correction_method"]
    case["status"] = "METHOD_ELECTED"
    db.touch(case)
    return single(serializers.excess_case(case))


def _period_contributions(case):
    """Cents contributed into the account from computation_period_start onwards,
    always including the deposit that carried the excess."""
    start = parse_date(case["computation_period_start"])
    total = 0
    for line in calc.account_lines(case["account_id"]):
        if line["status"] != "POSTED":
            continue
        remittance = db.payroll_remittances.get(line["remittance_id"])
        if remittance is None or not remittance.get("posted_at"):
            continue
        posted = parse_instant(remittance["posted_at"])
        if posted is not None and posted.date() >= start:
            total += int(line["allocated_cents"])
    return max(total, int(case.get("period_contributions_cents") or 0))


@bp.route("/excess-contribution-cases/<case_id>/completion", methods=["POST"])
def complete_case(case_id):
    require(["Recordkeeper"])
    case = get_excess_case(case_id)
    parsed = parse_body({"settlement_reference": {"type": "str", "required": True}})
    if case["status"] != "METHOD_ELECTED":
        fail("ERR_EXCESS_CASE_STATE_INVALID", "this case has no elected correction to execute")
    if db.today() > parse_date(case["deadline_date"]):
        fail("ERR_CORRECTION_DEADLINE_PASSED", "the correction deadline has passed")
    account = db.participant_accounts.get(case["account_id"])
    if account is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "the account of this case no longer exists")
    closing = int(account["balance_cents"])
    period_contributions = _period_contributions(case)
    adjusted = calc.nia_adjusted_balance_cents(case, closing, period_contributions)
    prorata = calc.nia_daily_prorata_cents(case, db.today())
    method = calc.nia_method_for(case, db.now())
    applied = adjusted if method == "ADJUSTED_BALANCE" else prorata
    detected = int(case["detected_excess_cents"])
    corrected = detected + applied
    if case["correction_method"] == "REFUND_TO_PARTICIPANT" and closing < corrected:
        fail("ERR_INSUFFICIENT_ACCOUNT_BALANCE",
             "the account cannot fund a refund of %d cents" % corrected)
    case["closing_fmv_cents"] = closing
    case["period_contributions_cents"] = period_contributions
    case["nia_adjusted_balance_cents"] = adjusted
    case["nia_daily_prorata_cents"] = prorata
    case["nia_method_applied"] = method
    case["applied_nia_cents"] = applied
    case["corrected_amount_cents"] = corrected
    case["settlement_reference"] = parsed["settlement_reference"]
    case["completed_at"] = db.now_iso()
    case["status"] = "COMPLETED"
    db.touch(case)

    method_elected = case["correction_method"]
    if method_elected == "REFUND_TO_PARTICIPANT":
        account["balance_cents"] = int(account["balance_cents"]) - corrected
        account["contribution_basis_cents"] = int(account["contribution_basis_cents"]) - corrected
        account["ytd_contribution_cents"] = int(account["ytd_contribution_cents"]) - detected
    elif method_elected == "RECHARACTERIZE_TO_TRADITIONAL":
        participant = db.participants.get(account["participant_id"])
        traditional = engine.open_traditional_account(participant, account["id"])
        traditional["balance_cents"] = corrected
        traditional["contribution_basis_cents"] = corrected
        calc.refresh_account(traditional)
        account["balance_cents"] = int(account["balance_cents"]) - corrected
        account["contribution_basis_cents"] = int(account["contribution_basis_cents"]) - corrected
        account["ytd_contribution_cents"] = int(account["ytd_contribution_cents"]) - detected
    else:  # CARRY_FORWARD moves no money at all.
        account["ytd_contribution_cents"] = int(account["ytd_contribution_cents"]) - detected
    calc.refresh_account(account, bump=True)
    return single(serializers.excess_case(case))
