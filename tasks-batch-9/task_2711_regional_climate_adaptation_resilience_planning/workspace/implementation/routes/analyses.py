"""PRD 3.6 -- preparing, certifying and rejecting a benefit-cost analysis."""

from decimal import Decimal

from flask import Blueprint

import calc
import envelope
import lookup
import serialize
import store
import validate
from auth import (ROLE_BCA_REVIEWER, ROLE_PROJECT_SPONSOR, acting_user, guard,
                  require_owned_jurisdiction)
from core import clock
from errors import fail

bp = Blueprint("analyses", __name__)

METHODS = ("DISCOUNTED_NPV", "ANNUALIZED_EQUIVALENT")


@bp.post("/resilience/projects/<project_id>/analyses")
@guard(ROLE_PROJECT_SPONSOR)
def prepare_analysis(project_id):
    project = lookup.need("project", project_id)
    require_owned_jurisdiction(project["jurisdiction_id"], roles=(ROLE_PROJECT_SPONSOR,))
    body = validate.json_body()
    method = validate.enum_field(body, "method", METHODS, required=True)
    discount_rate_bps = validate.int_field(
        body, "discount_rate_bps", default=700, minimum=1, maximum=2000
    )

    if project["screening_status"] != "SCREENED_IN":
        fail("ERR_PROJECT_NOT_SCREENED_IN", "The project is not SCREENED_IN.")
    if lookup.certified_analysis(project["id"]) is not None:
        fail("ERR_BCA_ALREADY_CERTIFIED", "The project already holds a CERTIFIED analysis.")
    links = lookup.links_of(project["id"])
    if not links:
        fail("ERR_NO_LINKED_ASSETS", "The project has no linked lifeline assets.")
    for link in links:
        asset = store.assets.get(link["asset_id"])
        if asset is None or asset["criticality_status"] != "RANKED":
            fail(
                "ERR_ASSET_RANKING_REQUIRED",
                "Every linked lifeline asset must be RANKED.",
            )

    horizon = project["service_life_years"]
    benefit, cost, bcr, eligible = calc.benefit_cost(
        method,
        discount_rate_bps,
        horizon,
        project["total_program_cost_cents"],
        [link["avoided_loss_annual_cents"] for link in links],
    )

    record = store.insert(store.analyses, {
        "project_id": project["id"],
        "method": method,
        "discount_rate_bps": discount_rate_bps,
        "analysis_horizon_years": horizon,
        "benefit_measure_cents": benefit,
        "cost_measure_cents": cost,
        "bcr": bcr,
        "grant_eligible": eligible,
        "status": "DRAFT",
        "prepared_by_user_id": acting_user(),
        "certified_by_user_id": None,
        "certified_at": None,
        "stale_reason": "NONE",
    })
    project["analysis_status"] = "BCA_PENDING"
    store.touch(project)
    return envelope.created(serialize.analysis(record))


@bp.get("/resilience/analyses")
@guard()
def list_analyses():
    rows = envelope.match(
        store.ordered(store.analyses),
        project_id=envelope.str_filter("project_id"),
        method=envelope.str_filter("method"),
        status=envelope.str_filter("status"),
        grant_eligible=envelope.bool_filter("grant_eligible"),
    )
    return envelope.listing(rows, serialize.analysis)


@bp.get("/resilience/analyses/<analysis_id>")
@guard()
def get_analysis(analysis_id):
    row = lookup.need("analysis", analysis_id)
    return envelope.ok(serialize.analysis(row))


@bp.post("/resilience/analyses/<analysis_id>/certify")
@guard(ROLE_BCA_REVIEWER)
def certify_analysis(analysis_id):
    analysis = lookup.need("analysis", analysis_id)
    if analysis["status"] != "DRAFT":
        fail("ERR_ANALYSIS_NOT_DRAFT", "Only a DRAFT analysis may be certified.")
    other = lookup.certified_analysis(analysis["project_id"])
    if other is not None and other["id"] != analysis["id"]:
        fail("ERR_BCA_ALREADY_CERTIFIED", "The project already holds a CERTIFIED analysis.")
    if acting_user() == analysis["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The preparer may not certify the analysis.")
    if analysis["bcr"] is None or analysis["bcr"] < Decimal("1.0000"):
        fail("ERR_BCR_BELOW_FLOOR", "The benefit-cost ratio is below 1.0000.")

    analysis["status"] = "CERTIFIED"
    analysis["certified_by_user_id"] = acting_user()
    analysis["certified_at"] = clock.now()
    analysis["stale_reason"] = "NONE"
    store.touch(analysis)
    project = store.projects.get(analysis["project_id"])
    if project is not None:
        project["analysis_status"] = "BCA_CERTIFIED"
        store.touch(project)
    return envelope.ok(serialize.analysis(analysis))


@bp.post("/resilience/analyses/<analysis_id>/reject")
@guard(ROLE_BCA_REVIEWER)
def reject_analysis(analysis_id):
    analysis = lookup.need("analysis", analysis_id)
    if analysis["status"] != "DRAFT":
        fail("ERR_ANALYSIS_NOT_DRAFT", "Only a DRAFT analysis may be rejected.")
    if acting_user() == analysis["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The preparer may not reject the analysis.")

    analysis["status"] = "REJECTED"
    store.touch(analysis)
    project = store.projects.get(analysis["project_id"])
    if project is not None:
        project["analysis_status"] = "BCA_REJECTED"
        store.touch(project)
    return envelope.ok(serialize.analysis(analysis))
