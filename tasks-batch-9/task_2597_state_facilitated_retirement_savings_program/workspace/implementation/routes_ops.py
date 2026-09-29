"""The three administrative batch jobs.

None of these is a convenience wrapper: they are the only way the notified ->
active, the escalation and the expiry transitions ever happen.
"""
from flask import Blueprint

import calc
import engine
from auth import require
from errors import fail
from response import single
from store import db
from util import parse_date
from validate import parse_body

bp = Blueprint("ops", __name__)


def _as_of(parsed, key):
    supplied = parsed.get(key)
    if supplied:
        return parse_date(supplied)
    return db.today()


# ------------------------------------------------------------- auto enrollment

@bp.route("/_ops/auto-enrollment-run", methods=["POST"])
def auto_enrollment_run():
    require(["ProgramAdministrator"])
    parsed = parse_body({"as_of_date": {"type": "date", "nullable": True}})
    as_of = _as_of(parsed, "as_of_date")

    candidates = []
    skipped = 0
    for enrollment in db.ordered("enrollments"):
        if enrollment["enrollment_status"] != "NOTIFIED":
            continue
        employer = db.employers.get(enrollment["employer_id"])
        deadline = parse_date(enrollment["opt_out_deadline"])
        if as_of < deadline or employer is None or \
                employer["registration_status"] != "REGISTERED":
            skipped += 1
            continue
        candidates.append(enrollment)

    # Pre-scan: the run refuses as a whole rather than opening an account it
    # cannot invest, so no partial work is ever left behind.
    needs_account = []
    for enrollment in candidates:
        participant = db.participants.get(enrollment["participant_id"])
        if participant is None:
            continue
        if calc.posting_target_account(participant["id"]) is None and \
                participant["id"] not in needs_account:
            needs_account.append(participant["id"])
    for participant_id in needs_account:
        option, _basis = calc.default_fund_option(db.participants[participant_id])
        if option is None:
            fail("ERR_NO_DEFAULT_FUND_AVAILABLE",
                 "the fund menu offers no default-eligible option for every saver "
                 "this run would activate")

    activated = 0
    accounts_opened = 0
    for enrollment in candidates:
        participant = db.participants.get(enrollment["participant_id"])
        if participant is None:
            skipped += 1
            continue
        account = calc.posting_target_account(participant["id"])
        if account is None:
            account = engine.open_roth_account(participant)
            accounts_opened += 1
            engine.seed_default_election(account, participant)
            calc.refresh_account(account)
        enrollment["enrollment_status"] = "ACTIVE"
        db.touch(enrollment)
        activated += 1

    return single({"activated_count": activated,
                   "accounts_opened_count": accounts_opened,
                   "skipped_count": skipped})


# ----------------------------------------------------------- annual escalation

@bp.route("/_ops/annual-escalation-run", methods=["POST"])
def annual_escalation_run():
    require(["ProgramAdministrator"])
    parsed = parse_body({"effective_date": {"type": "date", "nullable": True}})
    effective_date = _as_of(parsed, "effective_date")
    cap = int(calc.dial("escalation_cap_bp"))

    escalated = 0
    capped = 0
    skipped = 0
    for enrollment in db.ordered("enrollments"):
        if not calc.escalation_qualifies(enrollment, effective_date):
            continue
        current = int(enrollment["contribution_rate_bp"])
        candidate = calc.escalation_candidate_rate(current)
        if candidate <= current:
            skipped += 1
            continue
        enrollment["contribution_rate_bp"] = candidate
        enrollment["rate_source"] = "ESCALATED"
        db.touch(enrollment)
        escalated += 1
        if candidate == cap:
            capped += 1

    return single({"escalated_count": escalated,
                   "capped_count": capped,
                   "skipped_count": skipped})


# ------------------------------------------------------------ compliance sweep

@bp.route("/_ops/compliance-sweep", methods=["POST"])
def compliance_sweep():
    require(["ComplianceOfficer", "ProgramAdministrator"])
    parsed = parse_body({"as_of_date": {"type": "date", "nullable": True}})
    as_of = _as_of(parsed, "as_of_date")

    delinquent = 0
    for employer in db.ordered("employers"):
        calc.refresh_employer(employer, as_of=as_of, bump=True)
        if employer["compliance_status"] == "DELINQUENT":
            delinquent += 1

    assessments_created = 0
    for employer in db.ordered("employers"):
        deadline = employer.get("registration_deadline")
        if employer["registration_status"] != "PENDING_REGISTRATION" or not deadline:
            continue
        if as_of <= parse_date(deadline):
            continue
        standing = None
        for penalty in calc.employer_assessments(employer["id"]):
            if penalty["violation_type"] == "FAILURE_TO_REGISTER" and \
                    penalty["origin"] == "SWEEP" and \
                    penalty["status"] in ("ASSESSED", "AFFIRMED"):
                standing = penalty
                break
        if standing is not None:
            engine.reaccrue_penalty(standing, employer, as_of)
        else:
            engine.mint_penalty(employer, "FAILURE_TO_REGISTER", deadline, 30,
                                engine.SYSTEM, "SWEEP", as_of=as_of)
            assessments_created += 1
        calc.refresh_employer(employer, as_of=as_of, bump=True)

    expired_cases = 0
    touched_accounts = {}
    for case in db.ordered("excess_cases"):
        if case["status"] not in ("DETECTED", "METHOD_ELECTED"):
            continue
        if as_of <= parse_date(case["deadline_date"]):
            continue
        engine.expire_excess_case(case)
        expired_cases += 1
        account = db.participant_accounts.get(case["account_id"])
        if account is not None:
            touched_accounts[account["id"]] = account

    failed_transfers = 0
    for transfer in db.ordered("portability_transfers"):
        if transfer["status"] != "REQUESTED" or transfer["transfer_kind"] != "INDIRECT_60_DAY":
            continue
        if not transfer["settle_by_date"] or as_of <= parse_date(transfer["settle_by_date"]):
            continue
        engine.lapse_transfer(transfer)
        failed_transfers += 1
        account = db.participant_accounts.get(transfer["source_account_id"])
        if account is not None:
            touched_accounts[account["id"]] = account

    for account in touched_accounts.values():
        calc.refresh_account(account, bump=True)

    return single({"delinquent_employer_count": delinquent,
                   "assessments_created_count": assessments_created,
                   "expired_case_count": expired_cases,
                   "failed_transfer_count": failed_transfers})
