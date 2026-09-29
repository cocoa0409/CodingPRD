"""Planning studies, alternatives, screening and sufficiency certification (PRD §3.1)."""

from flask import Blueprint, g

import response as resp
from db import insert, store
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import calc, derive
from validation import (
    apply_filters,
    collection_list,
    find_path,
    fk,
    get_body,
    paginate,
    req_enum,
    req_id,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("studies", __name__)

ALTERNATIVE_KINDS = ("TRANSMISSION", "NON_TRANSMISSION", "HYBRID")
NON_WIRES_KINDS = ("NON_TRANSMISSION", "HYBRID")
SCREENING_DECISIONS = ("SCREEN_IN", "SCREEN_OUT")


# ----------------------------------------------------------- reads ----
@bp.get("/siting/planning-studies")
@endpoint(ALL_ROLES)
def list_studies():
    rows, pagination = collection_list(store.planning_studies, ["project_id", "status"])
    return resp.listing(rows, pagination)


@bp.get("/siting/planning-studies/<study_id>")
@endpoint(ALL_ROLES)
def read_study(study_id):
    return resp.ok(find_path(store.planning_studies, study_id))


@bp.get("/siting/planning-studies/<study_id>/alternatives")
@endpoint(ALL_ROLES)
def list_study_alternatives(study_id):
    find_path(store.planning_studies, study_id)
    rows = apply_filters(
        derive.alternatives_of_study(study_id), ["kind", "screening_status", "study_id"]
    )
    rows, pagination = paginate(rows)
    return resp.listing(rows, pagination)


@bp.get("/siting/alternatives")
@endpoint(ALL_ROLES)
def list_alternatives():
    rows, pagination = collection_list(store.alternatives, ["study_id", "kind", "screening_status"])
    return resp.listing(rows, pagination)


@bp.get("/siting/alternatives/<alternative_id>")
@endpoint(ALL_ROLES)
def read_alternative(alternative_id):
    return resp.ok(find_path(store.alternatives, alternative_id))


# ---------------------------------------------------------- writes ----
@bp.post("/siting/planning-studies")
@endpoint(["Developer"])
def create_study():
    body = get_body()
    fk(body, "project_id", store.projects)
    project_id = req_id(body, "project_id")
    horizon_year = req_int(body, "horizon_year")
    reliability_deficit_mw = req_num(body, "reliability_deficit_mw", exclusive_min=0)
    transmission_capex_cents = req_int(body, "transmission_capex_cents", minimum=1)
    benefit_pv_cents = req_int(body, "benefit_pv_cents", minimum=0)

    row = insert(
        store.planning_studies,
        {
            "project_id": project_id,
            "horizon_year": horizon_year,
            "reliability_deficit_mw": reliability_deficit_mw,
            "transmission_capex_cents": transmission_capex_cents,
            "benefit_pv_cents": benefit_pv_cents,
            "status": "DRAFT",
            "transmission_levelized_cents_per_mw": None,
            "benefit_ratio": None,
            "need_margin_ratio": None,
            "selected_nta_alternative_id": None,
            "alternatives_screened_in_count": 0,
            "authored_by_user_id": g.user_id,
            "certified_by_user_id": None,
        },
    )
    return resp.created(row)


@bp.post("/siting/planning-studies/<study_id>/sufficiency-certification")
@endpoint(["Developer"])
def certify_study(study_id):
    study = find_path(store.planning_studies, study_id)
    body = get_body()
    req_str(body, "attestation_note")

    # tier 8/9 — the study dimension
    if study["status"] == "CERTIFIED_SUFFICIENT":
        raise ApiError("ERR_TERMINAL_STATE", "The study is already CERTIFIED_SUFFICIENT.")
    if study["status"] != "ALTERNATIVES_ANALYZED":
        raise ApiError("ERR_INVALID_STATE", "Only an ALTERNATIVES_ANALYZED study may be certified.")

    # tier 11 — segregation of duties (§2.10)
    if g.user_id == study["authored_by_user_id"]:
        raise ApiError("ERR_SELF_CERTIFICATION", "The study's author may not certify its sufficiency.")

    # tier 15 — selector pool, then tier 16 — screened-in count
    candidates = [
        a
        for a in derive.alternatives_of_study(study_id)
        if a["kind"] in NON_WIRES_KINDS and a["screening_status"] == "SCREENED_IN"
    ]
    if not candidates:
        raise ApiError(
            "ERR_NO_NONTRANSMISSION_ALTERNATIVE",
            "No screened-in NON_TRANSMISSION or HYBRID alternative exists on this study.",
        )
    if study["alternatives_screened_in_count"] < calc.MIN_SCREENED_IN_ALTERNATIVES:
        raise ApiError(
            "ERR_INSUFFICIENT_ALTERNATIVES",
            "At least %d screened-in alternatives are required."
            % calc.MIN_SCREENED_IN_ALTERNATIVES,
        )

    selected = sorted(
        candidates, key=lambda a: (calc.D(a["levelized_cost_cents_per_mw"]), a["created_at"], a["_seq"])
    )[0]

    levelized = calc.transmission_levelized(
        study["transmission_capex_cents"], study["reliability_deficit_mw"]
    )
    ratio = calc.benefit_ratio(study["benefit_pv_cents"], study["transmission_capex_cents"])
    margin = calc.need_margin_ratio(selected["levelized_cost_cents_per_mw"], levelized, ratio)
    status = (
        "CERTIFIED_SUFFICIENT" if margin >= calc.NEED_MARGIN_THRESHOLD else "INSUFFICIENT"
    )

    derive.apply(
        study,
        transmission_levelized_cents_per_mw=levelized,
        benefit_ratio=ratio,
        need_margin_ratio=margin,
        selected_nta_alternative_id=selected["id"],
        certified_by_user_id=g.user_id,
        status=status,
    )
    return resp.created(study)


@bp.post("/siting/alternatives")
@endpoint(["RouteAnalyst", "Developer"])
def create_alternative():
    body = get_body()
    fk(body, "study_id", store.planning_studies)
    study_id = req_id(body, "study_id")
    kind = req_enum(body, "kind", ALTERNATIVE_KINDS)
    description = req_str(body, "description")
    capex_cents = req_int(body, "capex_cents", minimum=0)
    deliverable_mw = req_num(body, "deliverable_mw")

    if calc.D(deliverable_mw) <= 0:
        raise ApiError("ERR_ZERO_DELIVERABLE", "deliverable_mw must be strictly positive.")

    row = insert(
        store.alternatives,
        {
            "study_id": study_id,
            "kind": kind,
            "description": description,
            "capex_cents": capex_cents,
            "deliverable_mw": deliverable_mw,
            "levelized_cost_cents_per_mw": calc.levelized_alternative_cost(
                capex_cents, deliverable_mw
            ),
            "screening_status": "SUBMITTED",
            "screen_reason": None,
        },
    )
    return resp.created(row)


@bp.post("/siting/alternatives/<alternative_id>/screening")
@endpoint(["RouteAnalyst"])
def screen_alternative(alternative_id):
    alternative = find_path(store.alternatives, alternative_id)
    body = get_body()
    decision = req_enum(body, "decision", SCREENING_DECISIONS)
    screen_reason = req_str(body, "screen_reason")

    current = alternative["screening_status"]
    if current == "SCREENED_OUT":
        raise ApiError("ERR_TERMINAL_STATE", "The alternative is already SCREENED_OUT.")
    if decision == "SCREEN_IN" and current != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED alternative may be screened in.")

    study = store.planning_studies.get(alternative["study_id"])
    if study is not None and study["status"] == "CERTIFIED_SUFFICIENT":
        raise ApiError(
            "ERR_INVALID_STATE", "Alternatives may not be re-screened once the study is certified."
        )

    target = "SCREENED_IN" if decision == "SCREEN_IN" else "SCREENED_OUT"
    derive.apply(alternative, screening_status=target, screen_reason=screen_reason)

    if study is not None:
        derive.recompute_study_screened_in(study)
        if decision == "SCREEN_IN" and study["status"] in ("DRAFT", "INSUFFICIENT"):
            fields = {"status": "ALTERNATIVES_ANALYZED"}
            if study["status"] == "INSUFFICIENT":
                fields.update(
                    {
                        "need_margin_ratio": None,
                        "benefit_ratio": None,
                        "transmission_levelized_cents_per_mw": None,
                        "selected_nta_alternative_id": None,
                        "certified_by_user_id": None,
                    }
                )
            derive.apply(study, **fields)

    return resp.created(alternative)
