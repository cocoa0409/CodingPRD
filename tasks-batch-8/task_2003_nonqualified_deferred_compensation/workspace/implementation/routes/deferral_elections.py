"""Deferral election endpoints."""
from datetime import date, timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_PARTICIPANT_NOT_ACTIVE,
    ERR_ELECTION_NOT_MODIFIABLE,
    ERR_DUPLICATE_ELECTION,
    ERR_WINDOW_NOT_OPEN,
    ERR_ELECTION_DEADLINE_PASSED,
    ERR_PERFORMANCE_TOO_LATE,
    ERR_CROSS_PLAN_REFERENCE,
    ERR_ACCOUNT_REQUIRED,
    ERR_ACCOUNT_CLOSED,
    ERR_DEFERRAL_CAP_EXCEEDED,
    raise_err,
)
from middleware import user_context, require_role, check_participant_ownership
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_string,
    req_enum,
    req_int,
    req_date,
    get_or_404,
    stamp_new,
    touch,
    recompute_account_balances,
    recompute_trusts_for_plan,
)
from util import CLOCK, fmt_date, parse_date, add_months

bp = Blueprint("deferral_elections", __name__)


def election_view(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "participant_id": e["participant_id"],
        "election_window_id": e["election_window_id"],
        "notional_fund_id": e["notional_fund_id"],
        "plan_id": e["plan_id"],
        "election_type": e["election_type"],
        "deferral_percent_bp": e["deferral_percent_bp"],
        "status": e["status"],
        "elected_cap_cents": e["elected_cap_cents"],
        "posted_cents": e["posted_cents"],
        "submitted_at": e["submitted_at"],
        "locked_at": e["locked_at"],
    }


def _ne_deadline(participant):
    return parse_date(participant["initial_eligibility_date"]) + timedelta(days=30)


def _perf_deadline(window):
    return add_months(parse_date(window["performance_period_end"]), -6)


def _check_create_deadline(election_type, participant, window):
    """Create-time deadline gates for NE/PERFORMANCE (GENERAL handled by window gate)."""
    today = CLOCK.date()
    if election_type == "NEWLY_ELIGIBLE":
        if today > _ne_deadline(participant):
            raise_err(ERR_ELECTION_DEADLINE_PASSED, "Newly-eligible election deadline has passed")
    elif election_type == "PERFORMANCE":
        if not window.get("performance_period_end"):
            raise_err(ERR_PERFORMANCE_TOO_LATE, "Window has no performance period")
        if today > _perf_deadline(window):
            raise_err(ERR_PERFORMANCE_TOO_LATE, "Performance election deadline has passed")


@bp.post("/api/deferral-elections")
def create_election():
    data = body()
    from errors import ERR_INVALID_REQUEST

    participant_id = data.get("participant_id")
    window_id = data.get("election_window_id")
    fund_id = data.get("notional_fund_id")
    for f, v in (("participant_id", participant_id), ("election_window_id", window_id), ("notional_fund_id", fund_id)):
        if not isinstance(v, str) or not v:
            raise_err(ERR_INVALID_REQUEST, f"{f} is required and must be a string")
    election_type = req_enum(data, "election_type", {"GENERAL", "NEWLY_ELIGIBLE", "PERFORMANCE"})
    pct = req_int(data, "deferral_percent_bp", 1, 7500)

    user_id, role = user_context()
    require_role(role, {"Participant"})
    check_participant_ownership(user_id, role, participant_id)

    participant = get_or_404(db.participants, participant_id, "Participant")
    window = get_or_404(db.election_windows, window_id, "ElectionWindow")
    fund = get_or_404(db.notional_funds, fund_id, "NotionalFund")
    plan = get_or_404(db.plans, participant["plan_id"], "Plan")

    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to create an election")
    if participant["status"] != "ACTIVE":
        raise_err(ERR_PARTICIPANT_NOT_ACTIVE, "Participant must be ACTIVE to create an election")
    if election_type == "GENERAL" and window["status"] != "OPEN":
        raise_err(ERR_WINDOW_NOT_OPEN, "GENERAL election requires an OPEN window")

    # Temporal deadlines
    _check_create_deadline(election_type, participant, window)

    # Uniqueness
    for e in db.deferral_elections.values():
        if e["participant_id"] == participant_id and e["election_window_id"] == window_id:
            raise_err(ERR_DUPLICATE_ELECTION, "An election already exists for this participant and window")

    # Cross-plan coherence
    if window["plan_id"] != participant["plan_id"] or fund["plan_id"] != participant["plan_id"]:
        raise_err(ERR_CROSS_PLAN_REFERENCE, "Participant, window, and fund must all belong to the same plan")

    election = stamp_new(
        {
            "participant_id": participant_id,
            "election_window_id": window_id,
            "notional_fund_id": fund_id,
            "plan_id": participant["plan_id"],
            "election_type": election_type,
            "deferral_percent_bp": pct,
            "status": "DRAFT",
            "elected_cap_cents": None,
            "posted_cents": 0,
            "submitted_at": None,
            "locked_at": None,
        }
    )
    db.deferral_elections[election["id"]] = election
    return ok_object(election_view(election), 201)


@bp.get("/api/deferral-elections")
def list_elections():
    user_context()
    items = list(db.deferral_elections.values())
    for f in ("participant_id", "election_window_id", "notional_fund_id", "plan_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e[f] == v]
    return _list_response([election_view(e) for e in items], request.args)


@bp.get("/api/deferral-elections/<electionId>")
def get_election(electionId):
    user_context()
    e = get_or_404(db.deferral_elections, electionId, "DeferralElection")
    return ok_object(election_view(e))


def _compute_cap(election, participant, window):
    pct = election["deferral_percent_bp"]
    comp = participant["annual_compensation_cents"]
    if election["election_type"] in ("GENERAL", "PERFORMANCE"):
        return (comp * pct) // 10000
    # NEWLY_ELIGIBLE: two-step floor; submitted_at is an ISO timestamp — take its date part
    submitted_date = parse_date(election["submitted_at"][:10])
    year_end = date(window["plan_year"], 12, 31)
    remaining_days = (year_end - submitted_date).days + 1
    prorated_comp = (comp * remaining_days) // 365
    return (prorated_comp * pct) // 10000


@bp.post("/api/deferral-elections/<electionId>/submit")
def submit_election(electionId):
    body()
    user_id, role = user_context()
    require_role(role, {"Participant"})
    e = get_or_404(db.deferral_elections, electionId, "DeferralElection")
    check_participant_ownership(user_id, role, e["participant_id"])

    participant = db.participants[e["participant_id"]]
    plan = db.plans[e["plan_id"]]
    window = db.election_windows[e["election_window_id"]]

    if e["status"] != "DRAFT":
        raise_err(ERR_ELECTION_NOT_MODIFIABLE, "Submit requires DRAFT")
    if participant["status"] != "ACTIVE":
        raise_err(ERR_PARTICIPANT_NOT_ACTIVE, "Participant must be ACTIVE to submit")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to submit")

    today = CLOCK.date()
    if e["election_type"] == "GENERAL":
        if window["status"] != "OPEN":
            raise_err(ERR_WINDOW_NOT_OPEN, "GENERAL submit requires an OPEN window")
        if today > parse_date(window["general_close_date"]):
            raise_err(ERR_ELECTION_DEADLINE_PASSED, "GENERAL submit deadline has passed")
    elif e["election_type"] == "NEWLY_ELIGIBLE":
        if today > _ne_deadline(participant):
            raise_err(ERR_ELECTION_DEADLINE_PASSED, "Newly-eligible submit deadline has passed")
    else:  # PERFORMANCE
        if today > _perf_deadline(window):
            raise_err(ERR_PERFORMANCE_TOO_LATE, "Performance submit deadline has passed")

    e["status"] = "SUBMITTED"
    e["submitted_at"] = CLOCK.stamp()
    e["elected_cap_cents"] = _compute_cap(e, participant, window)
    touch(e)
    return ok_object(election_view(e))


@bp.post("/api/deferral-elections/<electionId>/void")
def void_election(electionId):
    body()
    user_id, role = user_context()
    require_role(role, {"Participant"})
    e = get_or_404(db.deferral_elections, electionId, "DeferralElection")
    check_participant_ownership(user_id, role, e["participant_id"])
    if e["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_ELECTION_NOT_MODIFIABLE, "Void requires DRAFT or SUBMITTED")
    e["status"] = "VOIDED"
    touch(e)
    return ok_object(election_view(e))


def ledger_entry_view(entry):
    return {
        "id": entry["id"],
        "created_at": entry["created_at"],
        "account_id": entry["account_id"],
        "entry_type": entry["entry_type"],
        "amount_cents": entry["amount_cents"],
        "fund_id": entry["fund_id"],
        "crediting_run_id": entry["crediting_run_id"],
        "election_id": entry["election_id"],
        "distribution_request_id": entry["distribution_request_id"],
        "entry_status": entry["entry_status"],
        "entry_date": entry["entry_date"],
    }


@bp.post("/api/deferral-elections/<electionId>/post-deferral")
def post_deferral(electionId):
    data = body()
    amount = req_int(data, "amount_cents", lo=1)
    sp_start = req_date(data, "service_period_start")
    sp_end = req_date(data, "service_period_end")
    if sp_start >= sp_end:
        from errors import ERR_INVALID_DATE_RANGE

        raise_err(ERR_INVALID_DATE_RANGE, "service_period_start must be before service_period_end")

    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    e = get_or_404(db.deferral_elections, electionId, "DeferralElection")

    plan = db.plans[e["plan_id"]]
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to post a deferral")
    if e["status"] != "LOCKED":
        raise_err(ERR_ELECTION_NOT_MODIFIABLE, "post-deferral requires LOCKED")

    account = None
    for a in db.accounts.values():
        if a["participant_id"] == e["participant_id"] and a["plan_id"] == e["plan_id"]:
            account = a
            break
    if account is None:
        raise_err(ERR_ACCOUNT_REQUIRED, "An account is required for the election's participant and plan")
    if account["status"] == "CLOSED":
        raise_err(ERR_ACCOUNT_CLOSED, "Account is CLOSED")

    if e["posted_cents"] + amount > e["elected_cap_cents"]:
        raise_err(ERR_DEFERRAL_CAP_EXCEEDED, "Posting would exceed the elected cap")

    ts = CLOCK.stamp()
    entry = {
        "id": db.new_id(),
        "created_at": ts,
        "account_id": account["id"],
        "entry_type": "DEFERRAL_CREDIT",
        "amount_cents": amount,
        "fund_id": e["notional_fund_id"],
        "crediting_run_id": None,
        "election_id": e["id"],
        "distribution_request_id": None,
        "entry_status": "PENDING",
        "entry_date": fmt_date(CLOCK.date()),
    }
    db.ledger_entries[entry["id"]] = entry
    e["posted_cents"] += amount
    if e["posted_cents"] == e["elected_cap_cents"]:
        e["status"] = "APPLIED"
    touch(e)
    recompute_account_balances(account)
    recompute_trusts_for_plan(account["plan_id"])
    return ok_object(ledger_entry_view(entry), 201)
