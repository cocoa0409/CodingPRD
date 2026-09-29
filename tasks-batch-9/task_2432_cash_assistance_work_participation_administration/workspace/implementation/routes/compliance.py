"""Compliance episodes: conciliation, good cause, sanctions and cures (PRD 3.7)."""

from flask import Blueprint

import guards
from calc import SANCTION_PCT_BY_LEVEL, CONCILIATION_DAYS, pct
from domain import (lookup, pause_recoupment, recompute_case_sanction,
                    resume_recoupment, rows_where, terminate_open_assignments)
from errors import fail
from guards import Fields, body_str, raw_body, require
from respond import created, filter_value, listing, ok, pagination
from store import add_days, clock_date, clock_fiscal_year, clock_month, db, \
    new_record, touch

bp = Blueprint("compliance", __name__)

ALLEGATION_REASONS = ("HOURS_SHORTFALL", "REFUSED_ASSIGNMENT", "QUIT_EMPLOYMENT",
                      "MISSED_APPOINTMENT")
GOOD_CAUSE_REASONS = ("DOMESTIC_VIOLENCE", "NO_CHILD_CARE_AVAILABLE", "ILLNESS",
                      "TRANSPORTATION_UNAVAILABLE")
REFERRAL_COMPLIANCE = ("ASSIGNED", "EXEMPT", "CURE_PENDING")
SANCTIONED_STATUSES = ("SANCTION_IMPOSED", "CURE_PENDING")


def _episode(episode_id):
    return lookup("compliance_episodes", episode_id,
                  "ERR_COMPLIANCE_EPISODE_NOT_FOUND")


def _apply_case_posture(case):
    """The sanction rollup and the payment dimension it drives (PRD 3.7)."""
    level = recompute_case_sanction(case)
    if level == 3:
        if case["benefit_status"] in ("ACTIVE", "SUSPENDED"):
            case["benefit_status"] = "CLOSED"
            case["closure_reason"] = "FULL_FAMILY_SANCTION"
            case["benefit_amount_cents"] = 0
            touch(case)
            terminate_open_assignments(case, "CASE_CLOSED", clock_fiscal_year())
            pause_recoupment(case)
    elif level == 2:
        if case["benefit_status"] == "ACTIVE":
            case["benefit_status"] = "SUSPENDED"
            touch(case)
            pause_recoupment(case)
    return level


@bp.post("/compliance-episodes")
def open_episode():
    require(guards.SPECIALIST)
    body = raw_body()
    candidate_case = body_str(body, "case_id")
    if candidate_case is not None:
        lookup("cases", candidate_case, "ERR_CASE_NOT_FOUND")
    candidate_prior = body_str(body, "prior_episode_id")
    if candidate_prior is not None:
        lookup("compliance_episodes", candidate_prior,
               "ERR_COMPLIANCE_EPISODE_NOT_FOUND")
    fields = Fields(body)
    fields.identifier("case_id")
    fields.enum("allegation_reason", ALLEGATION_REASONS)
    fields.integer("expected_case_version")
    fields.identifier("prior_episode_id", required=False, default=None)

    case = db.cases[fields["case_id"]]
    if fields["expected_case_version"] != case["version"]:
        fail("ERR_STALE_CASE_VERSION",
             "The case has changed since it was read.")
    if case["compliance_status"] not in REFERRAL_COMPLIANCE:
        fail("ERR_INVALID_CASE_STATE",
             "The case compliance posture does not permit a referral.")
    prior_id = fields.get("prior_episode_id")
    if prior_id is not None:
        prior = db.compliance_episodes[prior_id]
        if prior["case_id"] != case["id"] or \
                prior["status"] not in SANCTIONED_STATUSES:
            fail("ERR_PRIOR_EPISODE_MISMATCH",
                 "The prior episode must be a sanctioned episode of the same case.")

    episode = new_record({
        "case_id": case["id"],
        "prior_episode_id": prior_id,
        "allegation_reason": fields["allegation_reason"],
        "origin": "CASEWORKER_REFERRAL",
        "status": "ALLEGED",
        "conciliation_start_date": None,
        "conciliation_deadline_date": None,
        "sanction_level": 0,
        "sanction_pct": 0.00,
        "sanction_imposed_month": None,
        "good_cause_reason": "NONE",
        "cure_plan_note": None,
    })
    db.compliance_episodes[episode["id"]] = episode
    case["compliance_status"] = "CONCILIATION_PENDING"
    touch(case)
    return created(episode)


@bp.get("/compliance-episodes/<episode_id>")
def read_episode(episode_id):
    require()
    return ok(_episode(episode_id))


@bp.get("/compliance-episodes")
def search_episodes():
    require(*guards.STAFF_ROLES)
    limit, offset = pagination()
    rows = rows_where("compliance_episodes")
    for name in ("case_id", "prior_episode_id", "status"):
        value = filter_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return listing(rows, limit, offset)


@bp.post("/compliance-episodes/<episode_id>/start-conciliation")
def start_conciliation(episode_id):
    require(guards.SPECIALIST)
    episode = _episode(episode_id)
    if episode["status"] != "ALLEGED":
        fail("ERR_INVALID_EPISODE_STATE",
             "Conciliation may only start from an ALLEGED episode.")
    start = clock_date()
    episode["status"] = "CONCILIATION"
    episode["conciliation_start_date"] = start
    episode["conciliation_deadline_date"] = add_days(start, CONCILIATION_DAYS)
    touch(episode)
    return ok(episode)


@bp.post("/compliance-episodes/<episode_id>/grant-good-cause")
def grant_good_cause(episode_id):
    require(guards.SUPERVISOR)
    episode = _episode(episode_id)
    fields = Fields(raw_body())
    fields.enum("good_cause_reason", GOOD_CAUSE_REASONS)
    if episode["status"] != "CONCILIATION":
        fail("ERR_INVALID_EPISODE_STATE",
             "Good cause may only be granted from CONCILIATION.")
    episode["status"] = "GOOD_CAUSE_GRANTED"
    episode["good_cause_reason"] = fields["good_cause_reason"]
    episode["sanction_level"] = 0
    episode["sanction_pct"] = 0.00
    touch(episode)
    case = db.cases[episode["case_id"]]
    case["compliance_status"] = "EXEMPT"
    touch(case)
    recompute_case_sanction(case)
    return ok(episode)


@bp.post("/compliance-episodes/<episode_id>/resolve-compliant")
def resolve_compliant(episode_id):
    require(guards.SPECIALIST)
    episode = _episode(episode_id)
    if episode["status"] not in ("CONCILIATION", "CURE_PENDING"):
        fail("ERR_INVALID_EPISODE_STATE",
             "Only a CONCILIATION or CURE_PENDING episode may be resolved.")
    episode["status"] = "RESOLVED_COMPLIANT"
    episode["sanction_level"] = 0
    episode["sanction_pct"] = 0.00
    touch(episode)
    case = db.cases[episode["case_id"]]
    case["compliance_status"] = "ASSIGNED"
    touch(case)
    level = recompute_case_sanction(case)
    if level == 0:
        if case["benefit_status"] == "SUSPENDED":
            case["benefit_status"] = "ACTIVE"
            touch(case)
        if case["benefit_status"] == "ACTIVE":
            resume_recoupment(case)
    return ok(episode)


@bp.post("/compliance-episodes/<episode_id>/impose-sanction")
def impose_sanction(episode_id):
    require(guards.SUPERVISOR)
    episode = _episode(episode_id)
    if episode["good_cause_reason"] != "NONE":
        fail("ERR_GOOD_CAUSE_ACTIVE",
             "Good cause has been granted for this episode.")
    if episode["status"] not in ("CONCILIATION", "CURE_PENDING"):
        fail("ERR_INVALID_EPISODE_STATE",
             "A sanction may only be imposed from CONCILIATION or CURE_PENDING.")
    deadline = episode["conciliation_deadline_date"]
    if deadline is None or clock_date() < deadline:
        fail("ERR_CONCILIATION_NOT_COMPLETE",
             "The conciliation period has not ended.")

    if episode["status"] == "CURE_PENDING":
        level = episode["sanction_level"] + 1
    elif episode["prior_episode_id"]:
        prior = db.compliance_episodes[episode["prior_episode_id"]]
        level = prior["sanction_level"] + 1
    else:
        level = 1
    level = min(level, 3)
    episode["sanction_level"] = level
    episode["sanction_pct"] = pct(SANCTION_PCT_BY_LEVEL[level])
    if episode["sanction_imposed_month"] is None:
        episode["sanction_imposed_month"] = clock_month()
    episode["status"] = "SANCTION_IMPOSED"
    touch(episode)

    case = db.cases[episode["case_id"]]
    _apply_case_posture(case)
    case["compliance_status"] = "SANCTIONED"
    touch(case)
    return ok(episode)


@bp.post("/compliance-episodes/<episode_id>/begin-cure")
def begin_cure(episode_id):
    require(guards.SPECIALIST)
    episode = _episode(episode_id)
    fields = Fields(raw_body())
    fields.text("cure_plan_note")
    if episode["status"] != "SANCTION_IMPOSED":
        fail("ERR_INVALID_EPISODE_STATE",
             "A cure may only begin from SANCTION_IMPOSED.")
    episode["status"] = "CURE_PENDING"
    episode["cure_plan_note"] = fields["cure_plan_note"]
    touch(episode)
    case = db.cases[episode["case_id"]]
    case["compliance_status"] = "CURE_PENDING"
    touch(case)
    recompute_case_sanction(case)
    return ok(episode)
