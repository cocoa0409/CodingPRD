"""Remedial investigation, sampling, risk characterisation and feasibility."""

from flask import Blueprint

import calc
import constants as K
import derive
import serialize
import shape
import store
import txn
from authz import require
from errors import ApiError
from routes import common

bp = Blueprint("ri", __name__)


@bp.post("/sites/<site_id>/remedial-investigations")
def create_ri(site_id):
    actor = require(K.ROLE_RPM)
    body = shape.get_body()
    scope_summary = shape.str_field(body, "scope_summary")
    exposure_medium = shape.enum_field(body, "exposure_medium", K.EXPOSURE_MEDIA)
    site = common.get_site(site_id)
    common.require_phase(site, K.PHASE_LISTED_OR_LATER)

    ri = common.new_record(
        {
            "site_id": site["id"],
            "scope_summary": scope_summary,
            "exposure_medium": exposure_medium,
            "status": "DRAFT",
            "authored_by_user_id": actor.user_id,
            "approved_by_user_id": None,
            "revision_round_count": 0,
            "valid_sample_count": 0,
            "central_tendency_epc_ug_per_l": None,
            "rme_epc_ug_per_l": None,
            "central_tendency_risk": None,
            "rme_risk": None,
            "hazard_index": None,
            "action_level_exceeded": False,
        }
    )
    store.remedial_investigations[ri["id"]] = ri
    # The first investigation accepted for the site advances its phase; a second
    # one opened while the site is already RI_FS_UNDERWAY leaves it untouched.
    if site["listing_status"] == "LISTED":
        txn.watch(site)
        site["listing_status"] = "RI_FS_UNDERWAY"
        derive.recompute_site_derived(site)
    return common.respond(ri, serialize.remedial_investigation, 201)


@bp.post("/remedial-investigations/<ri_id>/samples")
def create_sample(ri_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    medium = shape.enum_field(body, "medium", K.EXPOSURE_MEDIA)
    contaminant = shape.str_field(body, "contaminant")
    concentration = shape.num_field(
        body, "concentration_ug_per_l", scale=3, minimum=0
    )
    qa_status = shape.enum_field(body, "qa_status", K.QA_STATUSES)
    collected_at = shape.datetime_field(body, "collected_at")
    lab_reference = shape.str_field(body, "lab_reference")
    ri = common.get_ri(ri_id)
    site = store.sites[ri["site_id"]]
    common.deny_deleted(site)

    sample = common.new_record(
        {
            "remedial_investigation_id": ri["id"],
            "medium": medium,
            "contaminant": contaminant,
            "concentration_ug_per_l": concentration,
            "qa_status": qa_status,
            "collected_at": collected_at,
            "lab_reference": lab_reference,
        },
        mutable=False,
    )
    store.contaminant_samples[sample["id"]] = sample
    derive.recompute_valid_sample_count(ri)
    return common.respond(sample, serialize.contaminant_sample, 201)


@bp.post("/remedial-investigations/<ri_id>/submission")
def submit_ri(ri_id):
    require(K.ROLE_RPM)
    shape.get_body()
    ri = common.get_ri(ri_id)
    site = store.sites[ri["site_id"]]
    common.state(ri["status"] in ("DRAFT", "REVISION_REQUESTED"))
    common.deny_deleted(site)
    derive.recompute_valid_sample_count(ri)
    if ri["valid_sample_count"] < 1:
        raise ApiError("ERR_NO_VALID_SAMPLES")

    figures = calc.risk_assessment(ri["exposure_medium"], derive.ri_samples(ri["id"]))
    if figures is None:
        raise ApiError("ERR_NO_VALID_SAMPLES")
    txn.watch(ri)
    ri.update(figures)
    ri["status"] = "UNDER_REVIEW"
    # The flag has just moved, so every alternative already recorded is rescored.
    derive.rescore_alternatives(ri)
    return common.respond(ri, serialize.remedial_investigation)


@bp.post("/remedial-investigations/<ri_id>/review")
def review_ri(ri_id):
    actor = require(K.ROLE_RPM)
    body = shape.get_body()
    decision = shape.enum_field(body, "decision", K.REVIEW_DECISIONS)
    shape.str_field(body, "review_note", required=False)
    ri = common.get_ri(ri_id)
    site = store.sites[ri["site_id"]]
    common.state(ri["status"] == "UNDER_REVIEW")
    common.deny_deleted(site)
    if actor.user_id == ri["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    txn.watch(ri)
    if decision == "APPROVE":
        ri["status"] = "APPROVED"
        ri["approved_by_user_id"] = actor.user_id
    else:
        ri["status"] = "REVISION_REQUESTED"
        ri["revision_round_count"] += 1
    return common.respond(ri, serialize.remedial_investigation)


@bp.post("/remedial-investigations/<ri_id>/remedy-alternatives")
def create_alternative(ri_id):
    require(K.ROLE_RPM)
    body = shape.get_body()
    label = shape.str_field(body, "label")
    capital = shape.money_field(body, "capital_cost_cents", minimum=0)
    annual = shape.money_field(body, "annual_om_cost_cents", minimum=0)
    om_years = shape.int_field(body, "om_years", lo=1, hi=100)
    discount_bp = shape.int_field(body, "discount_rate_bp", lo=0, hi=2000)
    effectiveness = shape.int_field(body, "effectiveness_score", lo=0, hi=100)
    implementability = shape.int_field(body, "implementability_score", lo=0, hi=100)
    ri = common.get_ri(ri_id)
    site = store.sites[ri["site_id"]]
    common.deny_deleted(site)

    npv = calc.remedy_npv(capital, annual, om_years, discount_bp)
    cost_score = calc.cost_score(npv)
    alternative = common.new_record(
        {
            "remedial_investigation_id": ri["id"],
            "selected_by_rod_id": None,
            "label": label,
            "capital_cost_cents": capital,
            "annual_om_cost_cents": annual,
            "om_years": om_years,
            "discount_rate_bp": discount_bp,
            "effectiveness_score": effectiveness,
            "implementability_score": implementability,
            "npv_cents": npv,
            "cost_score": cost_score,
            "remedy_score": calc.remedy_score(
                effectiveness, implementability, cost_score, ri["action_level_exceeded"]
            ),
        }
    )
    store.remedy_alternatives[alternative["id"]] = alternative
    return common.respond(alternative, serialize.remedy_alternative, 201)
