"""Site evaluations: perc holes, the certified rate and departmental review."""
from flask import Blueprint

import calc
import derive
import lookup
import response
import serialize
import store
import validate as v
from auth import authenticate
from errors import ApiError
from store import ordered, touch
from util import add_years, dec

bp = Blueprint("site_evaluations", __name__)

SOIL_GROUPS = ("SANDY", "LOAMY", "CLAY_LOAM", "CLAY")
EVAL_READ_ROLES = ["Applicant", "DesignProfessional",
                   "EnvironmentalHealthSpecialist", "HealthOfficer",
                   "RecordsClerk"]
EVAL_DECISIONS = ("APPROVE", "REJECT")


@bp.post("/site-evaluations")
def create_site_evaluation():
    actor = authenticate(["DesignProfessional"])
    body = v.body()
    parcel = lookup.parcel(v.req_fk(body, "parcel_id"))
    evaluated_on = v.req_dt(body, "evaluated_on")
    soil_group = v.req_enum(body, "soil_group", SOIL_GROUPS)
    depth = v.req_int(body, "depth_to_limiting_layer_in", minimum=0)

    evaluation = store.new_record()
    evaluation.update({
        "parcel_id": parcel["id"],
        "evaluator_user_id": actor.user_id,
        "evaluated_on": evaluated_on,
        "soil_group": soil_group,
        "depth_to_limiting_layer_in": depth,
        "perc_holes": [],
        "preliminary_perc_rate_min_per_in": None,
        "certified_perc_rate_min_per_in": None,
        "soil_loading_rate_gpd_per_sqft": None,
        "valid_until": add_years(evaluated_on, calc.SITE_EVAL_VALIDITY_YEARS),
        "status": "DRAFT",
        "review_note": None,
        "revision_round": 0,
    })
    store.site_evaluations[evaluation["id"]] = evaluation
    return response.ok(serialize.site_evaluation(evaluation), 201)


@bp.get("/site-evaluations/<evaluation_id>")
def read_site_evaluation(evaluation_id):
    authenticate(EVAL_READ_ROLES)
    evaluation = lookup.site_evaluation(evaluation_id)
    return response.ok(serialize.site_evaluation(evaluation))


@bp.get("/site-evaluations/<evaluation_id>/system-designs")
def list_designs_of_evaluation(evaluation_id):
    authenticate(EVAL_READ_ROLES)
    evaluation = lookup.site_evaluation(evaluation_id)
    limit, offset = v.pagination()
    status = v.q("status")
    rows = derive.designs_of_evaluation(evaluation["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("system_design", page),
                            limit, offset, total)


@bp.post("/site-evaluations/<evaluation_id>/perc-holes")
def append_perc_hole(evaluation_id):
    authenticate(["DesignProfessional"])
    evaluation = lookup.site_evaluation(evaluation_id)
    body = v.body()
    hole_number = v.req_int(body, "hole_number")
    drop_inches = v.req_num(body, "drop_inches")
    elapsed_minutes = v.req_num(body, "elapsed_minutes")
    presoak_ok = v.req_bool(body, "presoak_ok")

    if evaluation["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE")

    valid, rate = calc.perc_hole_derivation(drop_inches, elapsed_minutes,
                                            presoak_ok)
    evaluation["perc_holes"].append({
        "hole_number": hole_number,
        "drop_inches": drop_inches,
        "elapsed_minutes": elapsed_minutes,
        "presoak_ok": presoak_ok,
        "valid": valid,
        "rate_min_per_in": rate,
    })
    derive.recompute_evaluation_rates(evaluation)
    touch(evaluation)
    return response.ok(serialize.site_evaluation(evaluation))


@bp.post("/site-evaluations/<evaluation_id>/submit")
def submit_site_evaluation(evaluation_id):
    actor = authenticate(["DesignProfessional"])
    evaluation = lookup.site_evaluation(evaluation_id)
    if evaluation["evaluator_user_id"] != actor.user_id:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only the evaluating professional may submit this evaluation.")
    if evaluation["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE")
    if not any(h["valid"] for h in evaluation["perc_holes"]):
        raise ApiError("ERR_NO_VALID_PERC_HOLES")

    derive.recompute_evaluation_rates(evaluation)
    evaluation["status"] = "SUBMITTED"
    evaluation["revision_round"] += 1
    touch(evaluation)
    return response.ok(serialize.site_evaluation(evaluation))


@bp.post("/site-evaluations/<evaluation_id>/review")
def review_site_evaluation(evaluation_id):
    authenticate(["EnvironmentalHealthSpecialist"])
    evaluation = lookup.site_evaluation(evaluation_id)
    body = v.body()
    decision = v.req_enum(body, "decision", EVAL_DECISIONS)
    review_note = v.opt_str(body, "review_note")

    if evaluation["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")

    if decision == "APPROVE":
        certified = evaluation["certified_perc_rate_min_per_in"]
        if certified is None or dec(certified) > calc.MAX_PERCOLATION_RATE_MIN_PER_IN:
            raise ApiError("ERR_SOIL_UNSUITABLE")
        if evaluation["depth_to_limiting_layer_in"] < calc.MIN_LIMITING_LAYER_DEPTH_IN:
            raise ApiError("ERR_SOIL_UNSUITABLE")
        evaluation["review_note"] = review_note
        evaluation["status"] = "APPROVED"
        touch(evaluation)
        _supersede_siblings(evaluation)
    else:
        evaluation["review_note"] = review_note
        evaluation["status"] = "REJECTED"
        touch(evaluation)

    return response.ok(serialize.site_evaluation(evaluation))


def _supersede_siblings(approved):
    """Approval leaves exactly one live approved evaluation per parcel, and
    supersedes the designs drawn from the ones it displaces (PRD 3.3)."""
    for other in ordered(store.site_evaluations.values()):
        if other["id"] == approved["id"]:
            continue
        if other["parcel_id"] != approved["parcel_id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        other["status"] = "SUPERSEDED"
        touch(other)
        derive.supersede_designs_of_evaluation(other["id"])
