"""Fiscal impact analyses (PRD §3.4). The FiscalAnalyst identity is opaque: no municipality scope."""

from flask import Blueprint

import validate as v
from auth import ANY_ROLE, prelude
from db import base_record, db, touch
from errors import ApiError
from response import object_response, paginate
from services import calc, domain

bp = Blueprint("fiscal", __name__)


def utility_monthly_base_total(case):
    """Territory accounts projected at the post-annexation inside-city rate (PRD §3.4)."""
    total = 0
    for parcel in domain.own_parcels(case):
        if parcel["parcel_status"] not in domain.LIVE_PARCEL_STATUSES:
            continue
        for account in domain.parcel_accounts(parcel):
            if account["account_status"] == "DISCONNECTED":
                continue
            total += int(account["monthly_base_cents"])
    return total


@bp.post("/fiscal-impact-analyses")
def create_analysis():
    user_id, _role = prelude(("FiscalAnalyst",))
    body = v.get_body()

    case_id = v.id_field(body, "annexation_case_id")
    case = domain.body_ref("cases", case_id)

    analysis_method = v.enum_field(body, "analysis_method", ("AVERAGE_COST", "MARGINAL_COST"))
    projected_population = v.int_field(body, "projected_population", minimum=0)
    expected_case_version = v.int_field(body, "expected_case_version", minimum=0)
    horizon_years = v.int_field(
        body, "horizon_years", required=False, default=5, minimum=1, maximum=20
    )
    marginals = {}
    for name in (
        "marginal_police_cost_cents",
        "marginal_fire_cost_cents",
        "marginal_water_cost_cents",
        "marginal_sewer_cost_cents",
    ):
        marginals[name] = v.int_field(body, name, required=False, default=0, minimum=0)

    if expected_case_version != int(case["version"]):
        raise ApiError(
            "ERR_STALE_CASE_VERSION",
            "expected_case_version does not match the annexation case's current version.",
        )

    domain.assert_case_not_terminal(case)

    municipality = domain.municipality_of_case(case)
    statute = domain.statute_of_municipality(municipality)
    if analysis_method != statute["fiscal_method"]:
        raise ApiError(
            "ERR_FISCAL_METHOD_NOT_AUTHORIZED",
            "The statute mandates the %s methodology." % statute["fiscal_method"],
        )

    # A newer analysis supersedes every prior analysis of the case.
    cleared_finalized = False
    for prior in domain.rows("analyses"):
        if prior["annexation_case_id"] != case["id"]:
            continue
        if prior["status"] not in ("DRAFT", "FINALIZED"):
            continue
        if prior["status"] == "FINALIZED":
            cleared_finalized = True
        prior["status"] = "SUPERSEDED"
        touch(prior)
    if cleared_finalized:
        case["fiscal_finalized_by_user_id"] = None

    record = base_record()
    record.update(
        {
            "annexation_case_id": case["id"],
            "analysis_method": analysis_method,
            "projected_population": projected_population,
            "horizon_years": horizon_years,
            "status": "DRAFT",
            "finalized_by_user_id": None,
        }
    )
    record.update(marginals)
    record.update(
        calc.fiscal_impact_projection(
            record, case, municipality, statute, utility_monthly_base_total(case)
        )
    )
    db.analyses[record["id"]] = record

    touch(case)
    return object_response(record, 201)


@bp.get("/fiscal-impact-analyses/<analysis_id>")
def read_analysis(analysis_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("analyses", analysis_id))


@bp.get("/fiscal-impact-analyses")
def list_analyses():
    prelude(ANY_ROLE)
    return paginate(domain.rows("analyses"), ("annexation_case_id", "status"))


@bp.post("/fiscal-impact-analyses/<analysis_id>/finalize")
def finalize_analysis(analysis_id):
    user_id, _role = prelude(("FiscalAnalyst",))
    analysis = domain.path_record("analyses", analysis_id)
    case = domain.case_of_analysis(analysis)
    domain.assert_case_not_terminal(case)

    if case is not None and case["status"] == "EFFECTIVE":
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "An analysis may not be finalized once the case is EFFECTIVE.",
        )
    if analysis["status"] != "DRAFT":
        raise ApiError("ERR_ANALYSIS_STATE_INVALID", "Only a DRAFT analysis may be finalized.")
    for other in domain.rows("analyses"):
        if (
            other["id"] != analysis["id"]
            and other["annexation_case_id"] == analysis["annexation_case_id"]
            and other["status"] == "FINALIZED"
        ):
            raise ApiError(
                "ERR_ANALYSIS_STATE_INVALID",
                "The case already has a FINALIZED analysis.",
            )

    analysis["status"] = "FINALIZED"
    analysis["finalized_by_user_id"] = user_id
    touch(analysis)
    if case is not None:
        case["fiscal_finalized_by_user_id"] = user_id
        touch(case)
    return object_response(analysis)
