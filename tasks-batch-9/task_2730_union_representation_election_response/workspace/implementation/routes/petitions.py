"""Petition docketing, scope analysis, showing-of-interest, rerun scheduling and certification."""

from flask import Blueprint

import auth
import calc
import clockutil
import gates
import store
import validate
from errors import ApiError
from routes import common

bp = Blueprint("petitions", __name__)

BASE = "/labor-relations/petitions"

READ_ROLES = (auth.DIRECTOR, auth.ANALYST, auth.COUNSEL, auth.TRAINER, auth.BOARD, auth.UNION)


@bp.route(BASE, methods=["POST"])
@auth.endpoint([auth.DIRECTOR])
def create_petition(user_id, role):
    schema = validate.Schema(validate.body())
    case_number = schema.string("case_number")
    petition_type = schema.enum("petition_type", common.PETITION_TYPES)
    union_name = schema.string("union_name")
    filed_date = schema.date("filed_date")
    proposed_unit_description = schema.string("proposed_unit_description")
    claimed_employee_count = schema.integer("claimed_employee_count", minimum=1)
    payroll_period_end = schema.date("payroll_period_end")

    for existing in store.DB["petitions"].values():
        if existing["case_number"] == case_number:
            raise ApiError("ERR_DUPLICATE_CASE_NUMBER",
                           "The docket number is already in use.")

    row = store.insert("petitions", {
        "case_number": case_number,
        "petition_type": petition_type,
        "union_name": union_name,
        "filed_date": filed_date,
        "proposed_unit_description": proposed_unit_description,
        "claimed_employee_count": claimed_employee_count,
        "payroll_period_end": payroll_period_end,
        "case_status": "RECEIVED",
        "case_posture": "OPEN",
        "total_classified_headcount": 0,
        "included_headcount": 0,
        "excluded_headcount": 0,
        "pending_headcount": 0,
        "core_avg_hourly_wage_cents": None,
        "core_wage_locked_at": None,
        "submitted_card_count": 0,
        "duplicate_card_count": 0,
        "undated_card_count": 0,
        "stale_card_count": 0,
        "nonunit_card_count": 0,
        "valid_card_count": None,
        "showing_of_interest_pct": None,
        "showing_headcount_basis": None,
        "showing_verdict": "PENDING",
        "retraining_required": False,
        "certification_outcome": "NONE",
        "certified_at": None,
        "certified_round_id": None,
        "bargaining_obligation_start_at": None,
        "bargaining_obligation_end_at": None,
        "certification_year_end_at": None,
        "election_bar_end_at": None,
        "decert_window_open_at": None,
        "notice_posting_end_at": None,
        "pending_objection_count": 0,
        "blocking_charge_count": 0,
    })
    return common.one_created(row)


@bp.route(BASE, methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_petitions(user_id, role):
    case_status = validate.query_enum("case_status", common.CASE_STATUSES)
    case_posture = validate.query_enum("case_posture", common.CASE_POSTURES)
    certified_round_id = validate.query_string("certified_round_id")
    rows = store.ordered("petitions")
    if case_status is not None:
        rows = [r for r in rows if r["case_status"] == case_status]
    if case_posture is not None:
        rows = [r for r in rows if r["case_posture"] == case_posture]
    if certified_round_id is not None:
        rows = [r for r in rows if r["certified_round_id"] == certified_round_id]
    return common.list_response(rows)


@bp.route(BASE + "/<pid>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def read_petition(user_id, role, pid):
    return common.one(gates.must_exist("petitions", pid))


@bp.route(BASE + "/<pid>/open-scope-analysis", methods=["POST"])
@auth.endpoint([auth.DIRECTOR])
def open_scope_analysis(user_id, role, pid):
    validate.body()
    petition = gates.must_exist("petitions", pid)
    gates.require_open_posture(petition)
    if petition["case_status"] != "RECEIVED":
        raise ApiError("ERR_PETITION_STATUS_INVALID",
                       "Scope analysis may only be opened from RECEIVED.")
    petition["case_status"] = "SCOPE_ANALYSIS"
    store.touch(petition)
    return common.one(petition)


@bp.route(BASE + "/<pid>/verify-showing", methods=["POST"])
@auth.endpoint([auth.BOARD])
def verify_showing(user_id, role, pid):
    schema = validate.Schema(validate.body())
    submitted = schema.integer("submitted_card_count", minimum=0)
    duplicate = schema.integer("duplicate_card_count", minimum=0)
    undated = schema.integer("undated_card_count", minimum=0)
    stale = schema.integer("stale_card_count", minimum=0)
    nonunit = schema.integer("nonunit_card_count", minimum=0)
    petition = gates.must_exist("petitions", pid)

    valid = calc.valid_card_count((submitted, duplicate, undated, stale, nonunit))
    classifications = store.classifications_of(pid)
    basis = calc.showing_basis(classifications)
    denominator = (petition["included_headcount"] if basis == "AS_RULED"
                   else petition["total_classified_headcount"])

    pct = None
    verdict = None
    if valid >= 0 and denominator > 0:
        pct = calc.showing_pct(valid, denominator)
        verdict = calc.showing_verdict(pct)

    # The dismissal branch alone escapes the posture gate (PRD 3.3).
    if verdict != "INSUFFICIENT":
        gates.require_open_posture(petition)
    if petition["case_status"] not in ("SCOPE_ANALYSIS", "SOI_VERIFIED"):
        raise ApiError("ERR_PETITION_STATUS_INVALID",
                       "The showing may only be verified from SCOPE_ANALYSIS or SOI_VERIFIED.")
    if valid < 0:
        raise ApiError("ERR_CARD_COUNTS_INCONSISTENT",
                       "The struck card counts exceed the submitted card count.")
    if denominator <= 0:
        raise ApiError("ERR_UNIT_HEADCOUNT_ZERO",
                       "The selected headcount denominator is zero.")

    petition["submitted_card_count"] = submitted
    petition["duplicate_card_count"] = duplicate
    petition["undated_card_count"] = undated
    petition["stale_card_count"] = stale
    petition["nonunit_card_count"] = nonunit
    petition["valid_card_count"] = valid
    petition["showing_of_interest_pct"] = calc.as_number(pct)
    petition["showing_headcount_basis"] = basis
    petition["showing_verdict"] = verdict

    if verdict == "SUFFICIENT":
        petition["case_status"] = "SOI_VERIFIED"
    else:
        petition["case_status"] = "DISMISSED"
    store.touch(petition)
    if verdict == "INSUFFICIENT":
        gates.dismissal_cascade(petition)
    return common.one(petition)


@bp.route(BASE + "/<pid>/schedule-rerun", methods=["POST"])
@auth.endpoint([auth.BOARD])
def schedule_rerun(user_id, role, pid):
    schema = validate.Schema(validate.body())
    rerun_election_date = schema.date("rerun_election_date")
    voting_method = schema.enum("voting_method", common.VOTING_METHODS)
    polls_open_at = schema.datetime("polls_open_at")
    polls_close_at = schema.datetime("polls_close_at")
    validate.time_window(polls_open_at, polls_close_at)
    petition = gates.must_exist("petitions", pid)
    gates.require_open_posture(petition)
    if petition["case_status"] != "RERUN_DIRECTED":
        raise ApiError("ERR_PETITION_STATUS_INVALID",
                       "A rerun may only be scheduled from RERUN_DIRECTED.")

    set_aside = [r for r in store.rounds_of(pid) if r["status"] == "SET_ASIDE"]
    prior = max(set_aside, key=lambda r: r["round_number"]) if set_aside else None
    if prior is None:
        prior = store.current_round(pid)
    agreement = store.get("election_agreements", prior["election_agreement_id"]) if prior else None
    rnd = gates.create_election_round(
        petition, agreement,
        (prior["round_number"] + 1) if prior else 1,
        prior["id"] if prior else None,
        voting_method, rerun_election_date, polls_open_at, polls_close_at)
    petition["case_status"] = "ELECTION_SET"
    store.touch(petition)
    return common.one_created(rnd)


@bp.route(BASE + "/<pid>/certify", methods=["POST"])
@auth.endpoint([auth.BOARD])
def certify(user_id, role, pid):
    schema = validate.Schema(validate.body())
    election_round_id = schema.reference("election_round_id")
    petition = gates.must_exist("petitions", pid)
    rnd = gates.must_exist("election_rounds", election_round_id)

    gates.require_open_posture(petition)
    if petition["case_status"] != "TALLY_POSTED":
        raise ApiError("ERR_PETITION_STATUS_INVALID",
                       "Certification is only available from TALLY_POSTED.")
    if rnd["status"] != "TALLY_REVISED":
        raise ApiError("ERR_ROUND_NOT_REVISED",
                       "The named round has not been revised.")
    window_close = clockutil.parse_dt(rnd.get("objection_window_close_at"))
    now = clockutil.now()
    if window_close is not None and not now > window_close:
        raise ApiError("ERR_OBJECTION_WINDOW_OPEN",
                       "The objection window has not closed.")
    if petition["pending_objection_count"] != 0:
        raise ApiError("ERR_PENDING_OBJECTIONS", "Objections are still pending.")
    if petition["blocking_charge_count"] != 0:
        raise ApiError("ERR_BLOCKING_CHARGE_PENDING", "A blocking charge is still pending.")
    notice_end = clockutil.parse_dt(petition.get("notice_posting_end_at"))
    if notice_end is not None and notice_end > now:
        raise ApiError("ERR_NOTICE_POSTING_ACTIVE", "The notice-posting period is still running.")

    certified_at = clockutil.fmt_dt(now)
    petition["certified_at"] = certified_at
    petition["certified_round_id"] = rnd["id"]
    petition["case_status"] = "CERTIFIED"

    union_prevailed = ((rnd.get("revised_votes_for") or 0)
                       >= (rnd.get("majority_threshold") or 0))
    if union_prevailed:
        petition["certification_outcome"] = "CERTIFICATION_OF_REPRESENTATIVE"
        petition["bargaining_obligation_start_at"] = certified_at
        year_end = clockutil.fmt_dt(clockutil.add_days(now, calc.CERTIFICATION_YEAR_DAYS))
        petition["certification_year_end_at"] = year_end
        petition["decert_window_open_at"] = year_end
        petition["election_bar_end_at"] = None
        petition["bargaining_obligation_end_at"] = None
    else:
        petition["certification_outcome"] = "CERTIFICATION_OF_RESULTS"
        petition["election_bar_end_at"] = clockutil.fmt_dt(
            clockutil.add_days(now, calc.ELECTION_BAR_DAYS))
        petition["bargaining_obligation_start_at"] = None
        petition["certification_year_end_at"] = None
        petition["decert_window_open_at"] = None
        petition["bargaining_obligation_end_at"] = (
            certified_at if petition["petition_type"] == "RD" else None)

    store.touch(petition)
    rnd["status"] = "ROUND_CERTIFIED"
    store.touch(rnd)
    return common.one(petition)
