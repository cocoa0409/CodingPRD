"""Cascade primitives shared by more than one route module.

Nothing here is seeded at import time; every function below only ever runs as
part of a request or a batch job.
"""
import calc
from errors import fail
from store import db
from util import add_days, fmt_date, parse_date

SYSTEM = "SYSTEM"
FULL_BP = 10000


# ------------------------------------------------------------------- accounts

def open_roth_account(participant):
    """Open the participant's programme account (PRD 3.3 / 3.4)."""
    return db.insert("participant_accounts", {
        "participant_id": participant["id"],
        "account_type": "ROTH_IRA",
        "rolled_over_from_account_id": None,
        "account_status": "OPEN",
        "posture": "UNRESTRICTED",
        "balance_cents": 0,
        "contribution_basis_cents": 0,
        "ytd_contribution_cents": 0,
        "remaining_headroom_cents": 0,
        "uncorrected_excess_cents": 0,
        "fund_balances": [],
        "active_election_id": None,
        "closure_reason": None,
        "residual_disposition": None,
        "closed_at": None,
    })


def open_traditional_account(participant, source_account_id):
    return db.insert("participant_accounts", {
        "participant_id": participant["id"],
        "account_type": "TRADITIONAL_IRA",
        "rolled_over_from_account_id": source_account_id,
        "account_status": "OPEN",
        "posture": "UNRESTRICTED",
        "balance_cents": 0,
        "contribution_basis_cents": 0,
        "ytd_contribution_cents": 0,
        "remaining_headroom_cents": 0,
        "uncorrected_excess_cents": 0,
        "fund_balances": [],
        "active_election_id": None,
        "closure_reason": None,
        "residual_disposition": None,
        "closed_at": None,
    })


def new_election(account, allocations, source, selection_basis=None):
    """Create an election, superseding whichever one currently governs."""
    previous = calc.active_election(account["id"])
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        previous["superseded_at"] = db.now_iso()
        db.touch(previous)
    election = db.insert("investment_elections", {
        "account_id": account["id"],
        "allocations": allocations,
        "source": source,
        "status": "ACTIVE",
        "effective_date": fmt_date(db.today()),
        "superseded_at": None,
        "selection_basis": selection_basis,
    })
    account["active_election_id"] = election["id"]
    return election


def seed_default_election(account, participant):
    """The automatic selector; the saver's preferences are deliberately ignored."""
    option, basis = calc.default_fund_option(participant)
    if option is None:
        fail("ERR_NO_DEFAULT_FUND_AVAILABLE",
             "the fund menu offers no default-eligible option for this saver")
    allocations = [{"fund_code": option["fund_code"], "allocation_bp": FULL_BP}]
    return new_election(account, allocations, "SYSTEM_DEFAULT", basis)


# ------------------------------------------------------------------ penalties

def mint_penalty(employer, violation_type, notice_date, cure_days, assessed_by,
                 origin, as_of=None):
    as_of = as_of or db.today()
    if not notice_date:
        notice_date = fmt_date(as_of)
    amounts = calc.penalty_amounts(employer, violation_type, notice_date,
                                   employer["employee_count"], as_of)
    row = {
        "employer_id": employer["id"],
        "violation_type": violation_type,
        "notice_date": notice_date,
        "cure_days": int(cure_days),
        "cure_deadline": fmt_date(add_days(parse_date(notice_date), int(cure_days))),
        "employee_count_at_assessment": int(employer["employee_count"]),
        "status": "ASSESSED",
        "assessed_by_user_id": assessed_by,
        "disposed_by_user_id": None,
        "disposition_note": None,
        "origin": origin,
        "last_accrual_date": None,
    }
    row.update(amounts)
    return db.insert("penalty_assessments", row)


def reaccrue_penalty(penalty, employer, as_of):
    """A later sweep re-accrues the amounts of an assessment it already raised."""
    amounts = calc.penalty_amounts(employer, penalty["violation_type"],
                                   penalty["notice_date"],
                                   penalty["employee_count_at_assessment"], as_of)
    penalty.update(amounts)
    penalty["last_accrual_date"] = fmt_date(as_of)
    db.touch(penalty)
    return penalty


def mint_referral(penalty, employer, agency, referral_basis, referred_by):
    return db.insert("enforcement_referrals", {
        "penalty_id": penalty["id"],
        "agency": agency,
        "referral_basis": referral_basis,
        "status": "OPEN",
        "referred_at": db.now_iso(),
        "referred_by_user_id": referred_by,
        "withdrawn_reason": None,
        "employer_ein_snapshot": employer["ein"],
    })


def affirmed_assessment_of(employer_id, exclude_id=None):
    rows = [p for p in db.penalty_assessments.values()
            if p["employer_id"] == employer_id and p["status"] == "AFFIRMED"
            and p["id"] != exclude_id]
    rows.sort(key=lambda p: p.get("_seq", 0))
    return rows[0] if rows else None


# ------------------------------------------------------------ sweep primitives

def expire_excess_case(case):
    case["status"] = "EXPIRED"
    case["excise_tax_cents"] = calc.excise_tax_cents(case["detected_excess_cents"])
    db.touch(case)
    account = db.participant_accounts.get(case["account_id"])
    if account is not None:
        calc.refresh_account(account)
    return case


def lapse_transfer(transfer):
    """An indirect rollover that never settled is a deemed taxable distribution:
    no money comes back to the source account."""
    transfer["status"] = "FAILED_TAXABLE"
    transfer["in_transit_cents"] = 0
    transfer["is_taxable_distribution"] = True
    db.touch(transfer)
    account = db.participant_accounts.get(transfer["source_account_id"])
    if account is not None:
        calc.refresh_account(account)
    return transfer


# ------------------------------------------------------------------ enrolments

def live_enrollments_of(employer_id):
    return [e for e in db.enrollments.values()
            if e["employer_id"] == employer_id
            and e["enrollment_status"] in ("NOTIFIED", "ACTIVE", "OPTED_OUT")]


def employer_has_active_enrollment(employer_id):
    return any(e["employer_id"] == employer_id and e["enrollment_status"] == "ACTIVE"
               for e in db.enrollments.values())


def certifications_of(employer_id):
    rows = [c for c in db.exemption_certifications.values() if c["employer_id"] == employer_id]
    rows.sort(key=lambda c: c.get("_seq", 0))
    return rows


def referrals_of(penalty_id):
    rows = [r for r in db.enforcement_referrals.values() if r["penalty_id"] == penalty_id]
    rows.sort(key=lambda r: r.get("_seq", 0))
    return rows
