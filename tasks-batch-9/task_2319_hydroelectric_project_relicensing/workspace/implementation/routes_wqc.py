"""Water-quality certifications and mitigation (PME) measures."""
from flask import Blueprint, g

import auth
import clock
import constants as C
import listing
import payload
import response
import serializers as S
import services as SV
from db import db, sorted_rows
from errors import ApiError
from numeric import q1, q2

bp = Blueprint("wqc", __name__)


def _new_measure(
    project,
    source,
    status,
    measure_name,
    resource_category,
    capital_cost_usd,
    annual_om_cost_usd,
    construction_start_year,
    implementation_months,
    flow_release_cfs,
    gross_head_ft,
    release_days,
    settlement_id=None,
    prerequisite_measure_id=None,
    created_by_user_id=None,
):
    measure = SV.base_row()
    measure.update(
        {
            "project_id": project["id"],
            "settlement_id": settlement_id,
            "prerequisite_measure_id": prerequisite_measure_id,
            "measure_name": measure_name,
            "resource_category": resource_category,
            "source": source,
            "status": status,
            "capital_cost_usd": capital_cost_usd,
            "annual_om_cost_usd": annual_om_cost_usd,
            "construction_start_year": construction_start_year,
            "implementation_months": implementation_months,
            "flow_release_cfs": flow_release_cfs,
            "gross_head_ft": gross_head_ft,
            "release_days": release_days,
            "cost_estimate_variant": "PRELIMINARY",
            "escalated_capital_usd": q2(0),
            "annualized_capital_usd": q2(0),
            "annual_cost_usd": q2(0),
            "annual_generation_loss_mwh": q1(0),
            "annual_generation_value_usd": q2(0),
            "annual_burden_usd": q2(0),
            "created_by_user_id": created_by_user_id,
            "definitive_estimate_by_user_id": None,
        }
    )
    SV.run_measure_calculation(measure, project, "PRELIMINARY")
    db.measures[measure["id"]] = measure
    return measure


# ---------------------------------------------------------------------------
# water-quality certifications
# ---------------------------------------------------------------------------


@bp.post("/relicensing/water-quality-certifications")
def request_wqc():
    auth.authenticate(["Licensee"])
    data = payload.body()

    project_id = payload.req_string(data, "project_id")
    project = SV.fetch("projects", project_id)
    agency_name = payload.req_string(data, "certifying_agency_name")

    for row in db.wqcs.values():
        if row["project_id"] == project_id and row["status"] == "REQUESTED":
            raise ApiError(
                "ERR_WQC_STATE_INVALID",
                "The project already holds a certification in REQUESTED status.",
            )
    if project["stage"] not in C.WQC_REQUEST_STAGES:
        raise ApiError(
            "ERR_WQC_STATE_INVALID",
            "A certification cannot be requested while the project stage is %s." % project["stage"],
        )

    SV.require_not_frozen(project)

    requested_at = clock.now_iso()
    wqc = SV.base_row()
    wqc.update(
        {
            "project_id": project_id,
            "certifying_agency_name": agency_name,
            "status": "REQUESTED",
            "requested_at": requested_at,
            "statutory_waiver_date": clock.fmt_date(
                clock.add_months(clock.today(), C.WQC_WAIVER_MONTHS)
            ),
            "decided_at": None,
            "condition_count": 0,
            "denial_reason": None,
        }
    )
    db.wqcs[wqc["id"]] = wqc

    SV.finalize_project(project)
    SV.touch(project)
    return response.object_response(S.wqc(wqc), 201)


@bp.get("/relicensing/water-quality-certifications")
def list_wqcs():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(sorted_rows(db.wqcs), S.wqc, ("project_id", "status"))


@bp.get("/relicensing/water-quality-certifications/<wqc_id>")
def get_wqc(wqc_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.wqc(SV.fetch("wqcs", wqc_id)))


@bp.post("/relicensing/water-quality-certifications/<wqc_id>/decision")
def decide_wqc(wqc_id):
    auth.authenticate(["StateCertifier"])
    wqc = SV.fetch("wqcs", wqc_id)
    data = payload.body()
    decision = payload.req_enum(data, "decision", C.WQC_DECISIONS)

    conditions = None
    denial_reason = None
    if decision == "ISSUE_WITH_CONDITIONS":
        raw = data.get("conditions")
        if not isinstance(raw, list) or len(raw) == 0:
            raise ApiError("ERR_INVALID_REQUEST", "conditions must be a non-empty array.")
        conditions = []
        for element in raw:
            if not isinstance(element, dict):
                raise ApiError("ERR_INVALID_REQUEST", "Each condition must be an object.")
            conditions.append(
                {
                    "measure_name": payload.req_string(element, "measure_name"),
                    "resource_category": payload.req_enum(
                        element, "resource_category", C.RESOURCE_CATEGORIES
                    ),
                    "capital_cost_usd": payload.req_number(element, "capital_cost_usd", minimum=0),
                    "annual_om_cost_usd": payload.req_number(
                        element, "annual_om_cost_usd", minimum=0
                    ),
                    "construction_start_year": payload.req_int(element, "construction_start_year"),
                    "implementation_months": payload.req_int(
                        element, "implementation_months", minimum=0
                    ),
                    "flow_release_cfs": payload.opt_number(
                        element, "flow_release_cfs", q2(0), minimum=0
                    ),
                    "gross_head_ft": payload.opt_number(element, "gross_head_ft", q2(0), minimum=0),
                    "release_days": payload.opt_int(
                        element, "release_days", 0, minimum=0, maximum=365
                    ),
                }
            )
    else:
        denial_reason = payload.opt_string(data, "denial_reason")
        if denial_reason is None or not denial_reason.strip():
            raise ApiError("ERR_INVALID_REQUEST", "denial_reason must be non-empty.")

    project = db.projects[wqc["project_id"]]
    SV.require_not_frozen(project)

    if wqc["status"] != "REQUESTED":
        raise ApiError(
            "ERR_WQC_STATE_INVALID",
            "Only a REQUESTED certification can be decided.",
        )

    wqc["decided_at"] = clock.now_iso()
    if decision == "ISSUE_WITH_CONDITIONS":
        wqc["status"] = "CERTIFIED_WITH_CONDITIONS"
        wqc["condition_count"] = len(conditions)
        for element in conditions:
            _new_measure(
                project,
                "WQC_CONDITION",
                "INCLUDED",
                element["measure_name"],
                element["resource_category"],
                element["capital_cost_usd"],
                element["annual_om_cost_usd"],
                element["construction_start_year"],
                element["implementation_months"],
                element["flow_release_cfs"],
                element["gross_head_ft"],
                element["release_days"],
                created_by_user_id=g.user_id,
            )
    else:
        wqc["status"] = "DENIED"
        wqc["denial_reason"] = denial_reason

    SV.touch(wqc)
    SV.finalize_project(project)
    SV.touch(project)
    return response.object_response(S.wqc(wqc))


# ---------------------------------------------------------------------------
# PME measures
# ---------------------------------------------------------------------------


@bp.post("/relicensing/pme-measures")
def create_measure():
    auth.authenticate(["Licensee"])
    data = payload.body()

    project_id = payload.req_string(data, "project_id")
    project = SV.fetch("projects", project_id)

    settlement = None
    if payload.present(data, "settlement_id"):
        settlement_id = payload.req_string(data, "settlement_id")
        settlement = SV.fetch("settlements", settlement_id)

    prerequisite = None
    if payload.present(data, "prerequisite_measure_id"):
        prerequisite_id = payload.req_string(data, "prerequisite_measure_id")
        prerequisite = SV.fetch("measures", prerequisite_id)

    if settlement is not None and settlement["project_id"] != project_id:
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "The settlement belongs to a different project.",
        )
    if prerequisite is not None and prerequisite["project_id"] != project_id:
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "The prerequisite measure belongs to a different project.",
        )

    measure_name = payload.req_string(data, "measure_name")
    resource_category = payload.req_enum(data, "resource_category", C.RESOURCE_CATEGORIES)
    source = payload.req_enum(data, "source", C.MEASURE_INPUT_SOURCES)
    capital_cost = payload.req_number(data, "capital_cost_usd", minimum=0)
    om_cost = payload.req_number(data, "annual_om_cost_usd", minimum=0)
    construction_start_year = payload.req_int(data, "construction_start_year")
    implementation_months = payload.req_int(data, "implementation_months", minimum=0)
    flow = payload.opt_number(data, "flow_release_cfs", q2(0), minimum=0)
    head = payload.opt_number(data, "gross_head_ft", q2(0), minimum=0)
    release_days = payload.opt_int(data, "release_days", 0, minimum=0, maximum=365)

    if source == "SETTLEMENT" and settlement is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "settlement_id is required when source is SETTLEMENT.",
        )

    SV.require_not_frozen(project)

    status = "PROPOSED" if source == "SETTLEMENT" else "INCLUDED"

    measure = _new_measure(
        project,
        source,
        status,
        measure_name,
        resource_category,
        capital_cost,
        om_cost,
        construction_start_year,
        implementation_months,
        flow,
        head,
        release_days,
        settlement_id=settlement["id"] if settlement is not None else None,
        prerequisite_measure_id=prerequisite["id"] if prerequisite is not None else None,
        created_by_user_id=g.user_id,
    )

    if status == "INCLUDED":
        SV.finalize_project(project)
        SV.touch(project)
    else:
        SV.finalize_project(project)

    return response.object_response(S.measure(measure), 201)


@bp.get("/relicensing/pme-measures")
def list_measures():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.measures),
        S.measure,
        (
            "project_id",
            "settlement_id",
            "prerequisite_measure_id",
            "status",
            "source",
            "resource_category",
            "cost_estimate_variant",
        ),
    )


@bp.get("/relicensing/pme-measures/<measure_id>")
def get_measure(measure_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.measure(SV.fetch("measures", measure_id)))


@bp.patch("/relicensing/pme-measures/<measure_id>")
def patch_measure(measure_id):
    auth.authenticate(["Licensee"])
    measure = SV.fetch("measures", measure_id)
    data = payload.body()

    prerequisite = None
    prerequisite_supplied = payload.present(data, "prerequisite_measure_id")
    if prerequisite_supplied:
        prerequisite_id = payload.req_string(data, "prerequisite_measure_id")
        prerequisite = SV.fetch("measures", prerequisite_id)
        if prerequisite["project_id"] != measure["project_id"]:
            raise ApiError(
                "ERR_CROSS_PROJECT_REFERENCE",
                "The prerequisite measure belongs to a different project.",
            )

    measure_name = payload.opt_string(data, "measure_name", None, allow_empty=False)
    capital_cost = payload.opt_number(data, "capital_cost_usd", None, minimum=0)
    om_cost = payload.opt_number(data, "annual_om_cost_usd", None, minimum=0)
    construction_start_year = payload.opt_int(data, "construction_start_year")
    implementation_months = payload.opt_int(data, "implementation_months", None, minimum=0)
    flow = payload.opt_number(data, "flow_release_cfs", None, minimum=0)
    head = payload.opt_number(data, "gross_head_ft", None, minimum=0)
    release_days = payload.opt_int(data, "release_days", None, minimum=0, maximum=365)

    project = db.projects[measure["project_id"]]
    SV.require_not_frozen(project)

    if measure["status"] not in ("PROPOSED", "INCLUDED"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "A measure in %s can no longer be amended." % measure["status"],
        )

    if prerequisite_supplied and SV.creates_cycle(measure["id"], prerequisite["id"]):
        raise ApiError(
            "ERR_PREREQUISITE_CYCLE",
            "The requested prerequisite would close a cycle in the prerequisite graph.",
        )

    if measure_name is not None:
        measure["measure_name"] = measure_name
    if capital_cost is not None:
        measure["capital_cost_usd"] = capital_cost
    if om_cost is not None:
        measure["annual_om_cost_usd"] = om_cost
    if construction_start_year is not None:
        measure["construction_start_year"] = construction_start_year
    if implementation_months is not None:
        measure["implementation_months"] = implementation_months
    if flow is not None:
        measure["flow_release_cfs"] = flow
    if head is not None:
        measure["gross_head_ft"] = head
    if release_days is not None:
        measure["release_days"] = release_days
    if prerequisite_supplied:
        measure["prerequisite_measure_id"] = prerequisite["id"]

    SV.run_measure_calculation(measure, project)
    SV.touch(measure)

    SV.finalize_project(project)
    return response.object_response(S.measure(measure))


@bp.post("/relicensing/pme-measures/<measure_id>/cost-estimate")
def measure_cost_estimate(measure_id):
    auth.authenticate(["Licensee"])
    measure = SV.fetch("measures", measure_id)
    data = payload.body()

    capital_cost = payload.opt_number(data, "capital_cost_usd", None, minimum=0)
    om_cost = payload.opt_number(data, "annual_om_cost_usd", None, minimum=0)
    head = payload.opt_number(data, "gross_head_ft", None, minimum=0)
    payload.opt_string(data, "estimate_note")

    project = db.projects[measure["project_id"]]
    SV.require_not_frozen(project)

    if measure["cost_estimate_variant"] != "PRELIMINARY":
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The measure already carries a DEFINITIVE estimate.",
        )

    if measure["created_by_user_id"] is not None and measure["created_by_user_id"] == g.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who created the measure may not record its definitive estimate.",
        )

    if capital_cost is not None:
        measure["capital_cost_usd"] = capital_cost
    if om_cost is not None:
        measure["annual_om_cost_usd"] = om_cost
    if head is not None:
        measure["gross_head_ft"] = head

    measure["definitive_estimate_by_user_id"] = g.user_id
    SV.run_measure_calculation(measure, project, "DEFINITIVE")
    SV.touch(measure)

    SV.finalize_project(project)
    return response.object_response(S.measure(measure))
