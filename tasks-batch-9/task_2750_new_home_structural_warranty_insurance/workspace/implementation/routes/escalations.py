"""Mediation, binding arbitration and the logical clock (PRD 3.9, 3.4)."""

from flask import Blueprint

import calc
import db
import listing
import response
import store
import validators as v
from errors import err, invalid
from middleware import (ROLE_ADJUSTER, ROLE_COMPLIANCE, ROLE_HOMEOWNER,
                        ROLE_UNDERWRITER, endpoint)

bp = Blueprint("escalations", __name__)
clock_bp = Blueprint("clock", __name__)

CASE_READERS = (ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER, ROLE_HOMEOWNER)
BOOKED_STATES = ("SCHEDULED", "SETTLED", "IMPASSE", "AWARD_ISSUED")
STAGE_CREDENTIALS = {"MEDIATION": ("MEDIATOR", "BOTH"),
                     "ARBITRATION": ("ARBITRATOR", "BOTH")}
CLAIM_FROM_STATE = {"MEDIATION": "DENIED", "ARBITRATION": "MEDIATION"}


def _bad_case_state(case, message=None):
    return err("ERR_INVALID_ESCALATION_STATE",
               message or "escalation case is in status '%s'" % case["status"])


def _refresh_booked_count(neutral):
    neutral["booked_session_count"] = sum(
        1 for c in store.cases_of_neutral(neutral["id"])
        if c["status"] in BOOKED_STATES)


@bp.post("/claims/<claim_id>/escalations")
@endpoint(ROLE_HOMEOWNER)
def open_escalation(claim_id, user_id, role):
    claim = store.get_claim(claim_id)
    policy = db.policies[claim["policy_id"]]
    if policy["current_owner_id"] != user_id:
        raise err("ERR_NOT_POLICY_OWNER",
                  "X-User-ID is not the current owner of this policy")
    body = v.body()
    neutral = None
    if isinstance(body.get("neutral_id"), str):
        neutral = store.get_neutral(body["neutral_id"])
    prior_case = None
    if isinstance(body.get("prior_case_id"), str):
        prior_case = store.get_case(body["prior_case_id"])

    stage = v.req_enum(body, "stage", ("MEDIATION", "ARBITRATION"))
    neutral_id = v.req_str(body, "neutral_id")
    window_start = v.req_instant(body, "window_start")
    window_end = v.req_instant(body, "window_end")
    prior_case_id = v.opt_str(body, "prior_case_id")
    if window_end <= window_start:
        raise invalid("field 'window_end' must be later than 'window_start'")
    if neutral is None:
        neutral = store.get_neutral(neutral_id)

    if claim["status"] != CLAIM_FROM_STATE[stage]:
        raise err("ERR_INVALID_CLAIM_STATE",
                  "claim is in status '%s'" % claim["status"])
    if neutral["status"] != "ACTIVE":
        raise err("ERR_NEUTRAL_INACTIVE", "the booked neutral is not ACTIVE")
    if neutral["credential"] not in STAGE_CREDENTIALS[stage]:
        raise err("ERR_NEUTRAL_CREDENTIAL_MISMATCH",
                  "credential '%s' may not take a %s session"
                  % (neutral["credential"], stage))
    if stage == "ARBITRATION":
        if prior_case is None or prior_case["status"] != "IMPASSE":
            raise err("ERR_MEDIATION_NOT_EXHAUSTED",
                      "arbitration requires a mediation case at IMPASSE")
    deadline = claim["escalation_deadline_date"]
    if deadline is None or v.fmt_date(db.clock_date()) > deadline:
        raise err("ERR_ESCALATION_WINDOW_ELAPSED",
                  "the escalation window has elapsed")
    if store.neutral_window_conflict(neutral["id"], window_start, window_end):
        raise err("ERR_NEUTRAL_WINDOW_CONFLICT",
                  "the neutral is already booked around that window")
    if prior_case is not None and prior_case["claim_id"] != claim["id"]:
        raise err("ERR_PRIOR_CASE_CLAIM_MISMATCH",
                  "prior_case_id belongs to a different claim")

    case = {
        "claim_id": claim["id"],
        "neutral_id": neutral["id"],
        "prior_case_id": prior_case_id,
        "stage": stage,
        "window_start": db.iso_ms(window_start),
        "window_end": db.iso_ms(window_end),
        "binding": stage == "ARBITRATION",
        "settlement_amount_cents": None,
        "award_amount_cents": None,
        "outcome_recorded_by_user_id": None,
        "status": "SCHEDULED",
        "_window_start": window_start,
        "_window_end": window_end,
    }
    db.stamp_create(case)
    db.escalation_cases[case["id"]] = case
    _refresh_booked_count(neutral)
    db.mark(neutral)
    claim["status"] = stage
    db.mark(claim)
    return response.object_response(db.public(case), 201)


@bp.post("/escalation-cases/<case_id>/session-outcome")
@endpoint(ROLE_ADJUSTER)
def record_session_outcome(case_id, user_id, role):
    case = store.get_case(case_id)
    body = v.body()
    outcome = v.req_enum(body, "outcome", ("SETTLED", "IMPASSE"))
    settled_amount = v.opt_int(body, "settlement_amount_cents", 0)
    if outcome == "SETTLED" and settled_amount is None:
        raise invalid("field 'settlement_amount_cents' is required on a settlement")
    if case["status"] != "SCHEDULED":
        raise _bad_case_state(case)
    if db.clock_now() < case["_window_start"]:
        raise err("ERR_SESSION_WINDOW_NOT_STARTED",
                  "the session window has not started")
    claim = db.claims[case["claim_id"]]
    case["outcome_recorded_by_user_id"] = user_id
    if outcome == "SETTLED":
        case["status"] = "SETTLED"
        case["settlement_amount_cents"] = settled_amount
        claim["status"] = "CLOSED_SETTLED"
        store.authorize_amount(claim, settled_amount)
        store.recompute_builder(store.builder_of_claim(claim))
    else:
        case["status"] = "IMPASSE"
        claim["escalation_deadline_date"] = v.fmt_date(
            store.deadline_from(db.clock_date(), calc.ARBITRATION_WINDOW_DAYS))
    db.mark(case)
    db.mark(claim)
    return response.object_response(db.public(case))


@bp.post("/escalation-cases/<case_id>/award")
@endpoint(ROLE_ADJUSTER)
def issue_award(case_id, user_id, role):
    case = store.get_case(case_id)
    prior_case = db.escalation_cases.get(case["prior_case_id"]) \
        if case["prior_case_id"] else None
    if (prior_case is not None
            and prior_case["outcome_recorded_by_user_id"] == user_id):
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "the adjuster who recorded the mediation outcome may not award")
    body = v.body()
    amount = v.req_int(body, "award_amount_cents", 0)
    v.opt_str(body, "award_note", non_blank=False)
    if case["stage"] != "ARBITRATION":
        raise _bad_case_state(case, "an award requires an ARBITRATION-stage case")
    if case["status"] != "SCHEDULED":
        raise _bad_case_state(case)
    if db.clock_now() < case["_window_start"]:
        raise err("ERR_SESSION_WINDOW_NOT_STARTED",
                  "the session window has not started")
    claim = db.claims[case["claim_id"]]
    case["status"] = "AWARD_ISSUED"
    case["award_amount_cents"] = amount
    if amount > 0:
        claim["status"] = "CLOSED_AWARDED"
        store.authorize_amount(claim, amount)
    else:
        claim["status"] = "CLOSED_DENIED_FINAL"
        store.release_reserve(claim, user_id)
    store.recompute_builder(store.builder_of_claim(claim))
    db.mark(case)
    db.mark(claim)
    return response.object_response(db.public(case))


@bp.get("/escalation-cases/<case_id>")
@endpoint(*CASE_READERS)
def read_case(case_id, user_id, role):
    return response.object_response(db.public(store.get_case(case_id)))


@bp.get("/escalation-cases")
@endpoint(*CASE_READERS)
def list_cases(user_id, role):
    rows = store.all_rows(db.escalation_cases)
    rows = listing.eq_filter(rows, "claim_id")
    rows = listing.eq_filter(rows, "neutral_id")
    rows = listing.eq_filter(rows, "prior_case_id")
    rows = listing.eq_filter(rows, "stage")
    rows = listing.eq_filter(rows, "status")
    return response.paginate(rows)


# ---------------------------------------------------------------------------
# The logical-clock control endpoint sits outside the /warranty prefix.
# ---------------------------------------------------------------------------
@clock_bp.post("/_clock/set_current_utc")
@endpoint(ROLE_COMPLIANCE)
def set_clock(user_id, role):
    instant = v.req_instant(v.body(), "to_iso8601")
    if instant < db.clock_now():
        raise err("ERR_CLOCK_REGRESSION", "the logical clock never moves backwards")
    db.clock_set(instant)
    expired_policies, elapsed_terms = store.epoch_sweep(v.fmt_date(instant.date()))
    return response.object_response({
        "current_utc": db.iso_ms(instant),
        "expired_policy_count": expired_policies,
        "elapsed_term_count": elapsed_terms,
    })
