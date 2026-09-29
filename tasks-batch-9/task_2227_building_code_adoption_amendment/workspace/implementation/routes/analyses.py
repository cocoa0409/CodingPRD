"""Impact analyses: filing (OCC-guarded) and review (PRD 3.3)."""
from flask import Blueprint

import config
import db
import middleware
import response
import validate
from errors import ApiError
from routes.common import apply_filters, as_str, paged
from services import calc, derive, lookup, serialize

bp = Blueprint("analyses", __name__)

_FILING_REVIEW_STATES = ("SCREENED", "COMMENT_OPEN", "COMMENT_CLOSED")


@bp.post("/amendment-proposals/<proposal_id>/impact-analyses")
def create_analysis(proposal_id):
    user_id, _ = middleware.require((config.ROLE_TECHNICAL_STAFF,))
    body = validate.body()
    expected_proposal_version = validate.req_int(body, "expected_proposal_version")
    analysis_type = validate.req_enum(body, "analysis_type", config.ANALYSIS_TYPES)

    incremental_cost_by_occupancy = None
    affected_permit_count = None
    annual_cost_savings_cents = None
    measure_life_years = None
    annual_energy_savings_kwh = None
    energy_delta_pct = None

    if analysis_type == "COST_BENEFIT":
        incremental_cost_by_occupancy = validate.req_object(body, "incremental_cost_by_occupancy")
        for key, value in incremental_cost_by_occupancy.items():
            if key not in config.OCCUPANCY_KEYS:
                raise validate.bad_request("incremental_cost_by_occupancy has an unrecognized "
                                           "occupancy class %r." % key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise validate.bad_request("incremental_cost_by_occupancy values must be "
                                           "integer cents.")
        affected_permit_count = validate.req_int(body, "affected_permit_count", 0)
        annual_cost_savings_cents = validate.req_int(body, "annual_cost_savings_cents", 0)
        measure_life_years = validate.req_int(body, "measure_life_years",
                                             config.MEASURE_LIFE_YEARS_MIN,
                                             config.MEASURE_LIFE_YEARS_MAX)
    else:
        annual_energy_savings_kwh = validate.req_number(body, "annual_energy_savings_kwh")
        energy_delta_pct = validate.req_number(body, "energy_delta_pct")

    proposal = lookup.proposal(proposal_id)

    if expected_proposal_version != proposal["version"]:
        raise ApiError("ERR_STALE_PROPOSAL_VERSION")

    if proposal["review_status"] not in _FILING_REVIEW_STATES:
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")

    statewide = None
    if analysis_type == "COST_BENEFIT":
        statewide = calc.statewide_incremental_cost(affected_permit_count,
                                                    incremental_cost_by_occupancy)

    record = db.new_record({
        "proposal_id": proposal["id"],
        "analysis_type": analysis_type,
        "prepared_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "incremental_cost_by_occupancy": incremental_cost_by_occupancy,
        "affected_permit_count": affected_permit_count,
        "annual_cost_savings_cents": annual_cost_savings_cents,
        "measure_life_years": measure_life_years,
        "annual_energy_savings_kwh": annual_energy_savings_kwh,
        "energy_delta_pct": energy_delta_pct,
        "statewide_incremental_cost_cents": statewide,
        "status": "SUBMITTED",
    })
    db.impact_analyses[record["id"]] = record
    db.touch(proposal)
    return response.object_response(serialize.impact_analysis(record), 201)


@bp.get("/amendment-proposals/<proposal_id>/impact-analyses")
def list_proposal_analyses(proposal_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    proposal = lookup.proposal(proposal_id)
    rows = derive.analyses_of_proposal(proposal["id"])
    return paged(rows, serialize.impact_analysis, limit, offset)


@bp.get("/impact-analyses")
def list_analyses():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.impact_analyses.values()), {
        "proposal_id": ("proposal_id", as_str),
        "analysis_type": ("analysis_type", as_str),
        "status": ("status", as_str),
    })
    return paged(rows, serialize.impact_analysis, limit, offset)


@bp.get("/impact-analyses/<analysis_id>")
def get_analysis(analysis_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.analysis(analysis_id)
    return response.object_response(serialize.impact_analysis(record))


@bp.post("/impact-analyses/<analysis_id>/review")
def review_analysis(analysis_id):
    user_id, _ = middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("ACCEPT", "RETURN"))
    analysis = lookup.analysis(analysis_id)

    if analysis["status"] != "SUBMITTED":
        raise ApiError("ERR_ANALYSIS_STATE_INVALID")

    proposal = db.amendment_proposals.get(analysis["proposal_id"])
    if proposal is None or proposal["review_status"] not in _FILING_REVIEW_STATES:
        raise ApiError("ERR_PROPOSAL_STAGE_INVALID")

    if user_id == analysis["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    analysis["reviewed_by_user_id"] = user_id

    if decision == "RETURN":
        analysis["status"] = "RETURNED"
        db.touch(analysis)
        return response.object_response(serialize.impact_analysis(analysis))

    analysis["status"] = "ACCEPTED"
    db.touch(analysis)

    for other in db.ordered(derive.analyses_of_proposal(proposal["id"])):
        if (other["id"] != analysis["id"]
                and other["analysis_type"] == analysis["analysis_type"]
                and other["status"] == "ACCEPTED"):
            other["status"] = "SUPERSEDED"
            db.touch(other)

    proposal_changed = False
    if analysis["analysis_type"] == "COST_BENEFIT":
        cost = calc.statewide_incremental_cost(analysis["affected_permit_count"],
                                               analysis["incremental_cost_by_occupancy"])
        proposal["statewide_incremental_cost_cents"] = cost
        proposal["affected_permit_count"] = analysis["affected_permit_count"]
        proposal["preliminary_benefit_cost_ratio"] = calc.preliminary_bcr(
            analysis["annual_cost_savings_cents"], cost)
        proposal_changed = True

    energy_required = derive.energy_analysis_required(proposal)
    has_cost_benefit = derive.accepted_analysis(proposal["id"], "COST_BENEFIT") is not None
    has_energy = derive.accepted_analysis(proposal["id"], "ENERGY_IMPACT") is not None
    if has_cost_benefit and (not energy_required or has_energy):
        target = "COMPLETE"
    elif has_cost_benefit or has_energy:
        target = "PARTIAL"
    else:
        target = proposal["analysis_status"]
    if target != proposal["analysis_status"]:
        proposal["analysis_status"] = target
        proposal_changed = True

    if proposal_changed:
        db.touch(proposal)

    return response.object_response(serialize.impact_analysis(analysis))
