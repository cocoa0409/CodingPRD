"""Capacity studies: creation, the review cycle and the breakdown view."""

from flask import Blueprint

import constants as C
from clock import clock
from db import created_order, db, new_record, public, touch
from errors import fail
from middleware import require
from response import created, ok
from routes.common import list_response
from services.capacity import compute_all, program_capacity, selected_projections
from services.reliance import recompute_school_flag
from validation import (
    get_body, lookup, need_enum, need_int, need_school_year, need_string,
    resolve_body_fk,
)

bp = Blueprint("studies", __name__)

FROZEN_DEFAULTS = {
    "gross_room_seats": 0,
    "set_aside_deduction_seats": 0,
    "program_capacity_seats": 0,
    "projected_enrollment_total": 0,
    "utilization_pct": 0.0,
    "portable_trigger_met": False,
    "seat_deficit": 0,
    "required_portable_count": 0,
}


def _check_policy_band_and_year(study_school_year, school, policy):
    """Rules 21 then 22, in that order."""
    if policy["grade_band"] != C.PRIMARY_BAND[school["grade_configuration"]]:
        fail("ERR_POLICY_BAND_MISMATCH",
             "The pinned policy governs grade band %s, not the campus primary band."
             % policy["grade_band"])
    if policy["effective_school_year"] != study_school_year:
        fail("ERR_POLICY_YEAR_MISMATCH",
             "The pinned policy is effective for %s, not %s."
             % (policy["effective_school_year"], study_school_year))


@bp.post("/capacity-studies")
def create_study():
    actor = require(["FacilitiesPlanner"])
    body = get_body()
    # rule 5: body foreign keys in entity-declaration order
    school = resolve_body_fk("school", body, "school_id")
    policy = resolve_body_fk("policy", body, "class_size_policy_id")
    # rule 6: body shape
    if school is None:
        need_string(body, "school_id")
    if policy is None:
        need_string(body, "class_size_policy_id")
    school_year = need_school_year(body, "school_year")
    method = need_enum(body, "method", C.STUDY_METHODS)
    expected = need_int(body, "expected_school_version", minimum=0)
    # rule 8: optimistic concurrency against the campus
    if expected != school["version"]:
        fail("ERR_STALE_SCHOOL_VERSION",
             "Campus version is %d, not %d." % (school["version"], expected))
    # rules 21 and 22
    _check_policy_band_and_year(school_year, school, policy)

    # a new study supersedes any DRAFT or RETURNED study for the same year
    superseded = created_order([
        s for s in db.studies.values()
        if s["school_id"] == school["id"]
        and s["school_year"] == school_year
        and s["status"] in ("DRAFT", "RETURNED")
    ])
    for old in superseded:
        old["status"] = "SUPERSEDED"
        touch(old)

    rec = new_record(dict({
        "school_id": school["id"],
        "class_size_policy_id": policy["id"],
        "school_year": school_year,
        "method": method,
        "status": "DRAFT",
        "revision_round": 0,
        "authored_by_user_id": actor.user_id,
        "certified_by_user_id": None,
    }, **dict(FROZEN_DEFAULTS, certified_on=None)))
    db.studies[rec["id"]] = rec
    # The campus row itself is not mutated by opening a study (PRD 2.4 ties a
    # version increment to "every mutation of that row"), so its version stands.
    return created(public(rec))


@bp.get("/capacity-studies/<study_id>")
def read_study(study_id):
    require(C.ALL_EXCEPT_CREW_LEAD)
    return ok(public(lookup("study", study_id)))


@bp.get("/capacity-studies")
def list_studies():
    require(C.ALL_EXCEPT_CREW_LEAD)
    return list_response(
        db.studies,
        ["school_id", "class_size_policy_id", "status", "school_year"],
    )


@bp.get("/capacity-studies/<study_id>/capacity-breakdown")
def capacity_breakdown(study_id):
    require(["DistrictAdmin", "FacilitiesPlanner", "CapacityCertifier"])
    study = lookup("study", study_id)
    school = db.schools[study["school_id"]]
    policy = db.policies[study["class_size_policy_id"]]

    own = compute_all(school, policy, study["school_year"], study["method"])
    _g, _d, state_seats = program_capacity(
        school["id"], policy, "STATE_LOADING_STANDARD")
    _g2, _d2, district_seats = program_capacity(
        school["id"], policy, "DISTRICT_POLICY")

    def total_for(method):
        selected, _missing = selected_projections(
            school["id"], study["school_year"], school["grade_configuration"], method)
        return sum(row["projected_students"] for row in selected.values())

    return ok({
        "method": study["method"],
        "gross_room_seats": own["gross_room_seats"],
        "set_aside_deduction_seats": own["set_aside_deduction_seats"],
        "program_capacity_seats": own["program_capacity_seats"],
        "state_standard_seats": state_seats,
        "district_policy_seats": district_seats,
        "projected_enrollment_total": own["projected_enrollment_total"],
        "state_projected_total": total_for("STATE_LOADING_STANDARD"),
        "district_projected_total": total_for("DISTRICT_POLICY"),
        "utilization_pct": own["utilization_pct"],
        "portable_trigger_met": own["portable_trigger_met"],
        "seat_deficit": own["seat_deficit"],
        "required_portable_count": own["required_portable_count"],
    })


@bp.post("/capacity-studies/<study_id>/submit")
def submit_study(study_id):
    require(["FacilitiesPlanner"])
    study = lookup("study", study_id)
    # rule 10
    if study["status"] != "DRAFT":
        fail("ERR_STUDY_STATE_INVALID",
             "A study in %s cannot be submitted." % study["status"])
    school = db.schools[study["school_id"]]
    policy = db.policies[study["class_size_policy_id"]]
    # rules 21 and 22
    _check_policy_band_and_year(study["school_year"], school, policy)
    # rule 25: projection coverage
    selected, missing = selected_projections(
        school["id"], study["school_year"], school["grade_configuration"],
        study["method"])
    if missing:
        fail("ERR_PROJECTION_COVERAGE_GAP",
             "No surviving enrolment projection for grade(s) %s."
             % ", ".join(str(g) for g in missing))
    # rule 26: zero program capacity
    figures = compute_all(school, policy, study["school_year"], study["method"])
    if figures["program_capacity_seats"] <= 0:
        fail("ERR_ZERO_PROGRAM_CAPACITY",
             "Program capacity computes to 0 seats under this method.")

    study.update(figures)
    study["status"] = "SUBMITTED"
    touch(study)
    return ok(public(study))


@bp.post("/capacity-studies/<study_id>/certify")
def certify_study(study_id):
    actor = require(["CapacityCertifier"])
    study = lookup("study", study_id)
    # rule 10
    if study["status"] != "SUBMITTED":
        fail("ERR_STUDY_STATE_INVALID",
             "A study in %s cannot be certified." % study["status"])
    # rule 14
    if actor.user_id == study["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The author of a study may not certify it.")
    school = db.schools[study["school_id"]]
    # rule 27
    if study["method"] == "DISTRICT_POLICY":
        selected, _missing = selected_projections(
            school["id"], study["school_year"], school["grade_configuration"],
            study["method"])
        for row in selected.values():
            if row["confidence_tier"] == "LOW":
                fail("ERR_LOW_CONFIDENCE_PROJECTION",
                     "A DISTRICT_POLICY study cannot be certified on a LOW "
                     "confidence projection.")

    study["status"] = "CERTIFIED"
    study["certified_by_user_id"] = actor.user_id
    study["certified_on"] = clock.iso()
    touch(study)

    for other in created_order([
        s for s in db.studies.values()
        if s["id"] != study["id"]
        and s["school_id"] == study["school_id"]
        and s["school_year"] == study["school_year"]
        and s["status"] == "CERTIFIED"
    ]):
        other["status"] = "SUPERSEDED"
        touch(other)

    school["certified_study_id"] = study["id"]
    recompute_school_flag(school)
    touch(school)
    return ok(public(study))


@bp.post("/capacity-studies/<study_id>/return")
def return_study(study_id):
    actor = require(["CapacityCertifier"])
    study = lookup("study", study_id)
    body = get_body()
    correction_note = need_string(body, "correction_note", 1, 2000)
    if study["status"] != "SUBMITTED":
        fail("ERR_STUDY_STATE_INVALID",
             "A study in %s cannot be returned." % study["status"])
    if actor.user_id == study["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The author of a study may not return it.")

    study["status"] = "RETURNED"
    study["revision_round"] = study["revision_round"] + 1
    study.update(FROZEN_DEFAULTS)
    touch(study)
    _ = correction_note
    return ok(public(study))


@bp.post("/capacity-studies/<study_id>/reopen")
def reopen_study(study_id):
    require(["FacilitiesPlanner"])
    study = lookup("study", study_id)
    if study["status"] != "RETURNED":
        fail("ERR_STUDY_STATE_INVALID",
             "A study in %s cannot be reopened." % study["status"])
    if study["revision_round"] >= C.MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_REACHED",
             "The study has already been through %d revision rounds."
             % study["revision_round"])
    study["status"] = "DRAFT"
    touch(study)
    return ok(public(study))
