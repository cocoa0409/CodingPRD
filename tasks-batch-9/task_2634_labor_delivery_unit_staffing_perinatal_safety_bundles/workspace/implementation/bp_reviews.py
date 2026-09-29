"""Newborn complication reviews (PRD 3.9): 7 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import rev
import store
from fields import q_enum, q_str, s_array, s_dt, s_enum, s_str
from pipeline import begin, need, run_checks, same_unit
from store import S

bp = Blueprint("reviews", __name__)

READ_ROLES = ["ChargeNurse", "ObstetricianAttending", "PerinatalSafetyOfficer"]


def _ever_on_case(staff_id, encounter_id):
    """Any CareAssignment in any status whatsoever counts as participation."""
    for row in calc.rows("care", encounter_id=encounter_id):
        if row["staff_id"] == staff_id:
            return True
    return False


@bp.post("/newborn-complication-reviews")
def open_review():
    ctx = begin(
        roles=["ChargeNurse", "PerinatalSafetyOfficer"],
        body_refs=[("encounter_id", "encounter"), ("facilitator_staff_id", "staff")],
        specs=[s_str("encounter_id", required=True),
               s_enum("complication_code", const.COMPLICATION_CODES, required=True),
               s_str("facilitator_staff_id", required=True)],
        scope=lambda c: same_unit(c, c.r["encounter"]["unit_id"], [c.r["staff"]]),
    )
    enc = ctx.r["encounter"]
    facilitator = ctx.r["staff"]

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def duties():
        need(not _ever_on_case(facilitator["id"], enc["id"]),
             "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    def credential():
        need(facilitator["employment_status"] == "ACTIVE"
             and facilitator["credential_expires_at"] > clock.now(),
             "ERR_STAFF_CREDENTIAL_EXPIRED")

    run_checks([(8.01, phase), (10, duties), (11.1, credential)])

    opened_at = clock.now()
    review = store.new_record({
        "encounter_id": enc["id"],
        "complication_code": ctx.v["complication_code"],
        "facilitator_staff_id": facilitator["id"],
        "opened_at": opened_at,
        "debrief_due_at": clock.plus_hours(opened_at, const.DEBRIEF_DUE_HOURS),
        "debrief_scheduled_for_utc": None,
        "debrief_held_at": None,
        "findings_summary": None,
        "contributing_factor_codes": None,
        "status": "OPEN",
        "rework_count": 0,
        "closed_by_user_id": None,
    })
    S.reviews[review["id"]] = review
    calc.rederive_encounter(enc)
    return common.created("reviews", review)


@bp.get("/newborn-complication-reviews")
def list_reviews():
    begin(roles=READ_ROLES)
    encounter_id = q_str("encounter_id")
    facilitator = q_str("facilitator_staff_id")
    status = q_enum("status", const.REVIEW_STATUSES)
    code = q_enum("complication_code", const.COMPLICATION_CODES)
    found = [r for r in S.reviews.values()
             if common.match(r, "encounter_id", encounter_id)
             and common.match(r, "facilitator_staff_id", facilitator)
             and common.match(r, "status", status)
             and common.match(r, "complication_code", code)]
    return common.listing("reviews", found,
                          [("opened_at", "desc"), ("created_at", "desc")])


@bp.get("/newborn-complication-reviews/<review_id>")
def read_review(review_id):
    ctx = begin(roles=READ_ROLES, path=[("review", review_id)])
    return common.single("reviews", ctx.p["review"])


@bp.post("/newborn-complication-reviews/<review_id>/schedule-debrief")
def schedule_debrief(review_id):
    ctx = begin(roles=["ChargeNurse"], path=[("review", review_id)],
                specs=[s_dt("debrief_scheduled_for_utc", required=True)])
    review = ctx.p["review"]
    slot = ctx.v["debrief_scheduled_for_utc"]

    def declared():
        need(review["status"] in ("OPEN", "REWORK_REQUESTED"),
             "ERR_INVALID_STATE_TRANSITION")

    def duties():
        need(not _ever_on_case(review["facilitator_staff_id"],
                               review["encounter_id"]),
             "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    def window():
        # Both boundaries inclusive, against the possibly extended deadline.
        need(clock.now() <= slot <= review["debrief_due_at"],
             "ERR_DEBRIEF_WINDOW_VIOLATION")

    run_checks([(8, declared), (10, duties), (14.2, window)])

    review["status"] = "DEBRIEF_SCHEDULED"
    review["debrief_scheduled_for_utc"] = slot
    rev.touch(review)
    return common.single("reviews", review)


@bp.post("/newborn-complication-reviews/<review_id>/submit-findings")
def submit_findings(review_id):
    ctx = begin(roles=["ChargeNurse"], path=[("review", review_id)],
                specs=[s_str("findings_summary"),
                       s_array("contributing_factor_codes", max_len=10)])
    review = ctx.p["review"]
    enc = S.encounters.get(review["encounter_id"])
    summary = ctx.v["findings_summary"]
    factors = ctx.v["contributing_factor_codes"]

    def declared():
        need(review["status"] == "DEBRIEF_SCHEDULED", "ERR_INVALID_STATE_TRANSITION")

    def notes():
        need(summary is not None and 40 <= len(summary) <= 2000,
             "ERR_DEBRIEF_NOTES_REQUIRED")

    def contributing():
        need(factors is not None and len(factors) >= 1,
             "ERR_CONTRIBUTING_FACTORS_REQUIRED")

    def bundles():
        for activation in calc.rows("activations", encounter_id=enc["id"]):
            need(activation["status"] in ("CLOSED", "RESCINDED"),
                 "ERR_BUNDLE_NOT_CLOSED")

    def held():
        # Inclusive: the scheduled instant itself counts as held. Lateness against
        # debrief_due_at is deliberately NOT blocked here.
        need(clock.now() >= review["debrief_scheduled_for_utc"],
             "ERR_DEBRIEF_NOT_HELD")

    run_checks([(8, declared), (9, notes), (9.1, contributing), (11.5, bundles),
                (14.2, held)])

    review["status"] = "FINDINGS_SUBMITTED"
    review["findings_summary"] = summary
    review["contributing_factor_codes"] = list(factors)
    review["debrief_held_at"] = clock.now()
    rev.touch(review)
    return common.single("reviews", review)


@bp.post("/newborn-complication-reviews/<review_id>/request-rework")
def request_rework(review_id):
    ctx = begin(roles=["PerinatalSafetyOfficer"], path=[("review", review_id)],
                specs=[s_str("rework_reason", required=True, min_len=10,
                             max_len=500)])
    review = ctx.p["review"]

    def declared():
        need(review["status"] == "FINDINGS_SUBMITTED", "ERR_INVALID_STATE_TRANSITION")

    def limit():
        need((review.get("rework_count") or 0) < const.REWORK_LIMIT,
             "ERR_REVIEW_REWORK_LIMIT_REACHED")

    def duties():
        need(ctx.user_id != review["facilitator_staff_id"],
             "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    run_checks([(8, declared), (8.10, limit), (10, duties)])

    review["status"] = "REWORK_REQUESTED"
    review["rework_count"] = (review.get("rework_count") or 0) + 1
    review["findings_summary"] = None
    review["contributing_factor_codes"] = None
    review["debrief_scheduled_for_utc"] = None
    review["debrief_held_at"] = None
    # The only deadline anywhere in the system that is ever mutated.
    review["debrief_due_at"] = clock.plus_hours(clock.now(),
                                                const.REWORK_EXTENSION_HOURS)
    rev.touch(review)
    return common.single("reviews", review)


@bp.post("/newborn-complication-reviews/<review_id>/close")
def close_review(review_id):
    ctx = begin(roles=["PerinatalSafetyOfficer"], path=[("review", review_id)])
    review = ctx.p["review"]
    enc = S.encounters.get(review["encounter_id"])

    def declared():
        need(review["status"] == "FINDINGS_SUBMITTED", "ERR_INVALID_STATE_TRANSITION")

    def contributing():
        factors = review.get("contributing_factor_codes")
        need(factors is not None and len(factors) >= 1,
             "ERR_CONTRIBUTING_FACTORS_REQUIRED")

    def duties():
        need(ctx.user_id != review["facilitator_staff_id"],
             "ERR_SEGREGATION_OF_DUTIES_VIOLATION")
        need(not _ever_on_case(ctx.user_id, review["encounter_id"]),
             "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    run_checks([(8, declared), (9, contributing), (10, duties)])

    review["status"] = "CLOSED"
    review["closed_by_user_id"] = ctx.user_id
    rev.touch(review)
    calc.rederive_encounter(enc)
    return common.single("reviews", review)
