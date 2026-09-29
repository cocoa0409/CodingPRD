"""Project intake, the posture sweep and the three conservation summaries."""

from flask import Blueprint

import envelope
import serializers
import store
import validation as v
from services import projects as project_service, sales

bp = Blueprint("projects", __name__)

CREATE_ROLES = ["ConverterSponsor"]
LIST_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
              "EscrowAgent", "PlatformAdmin"]
READ_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
              "EscrowAgent", "PlatformAdmin", "LicensedEngineer",
              "PeerReviewEngineer"]
PATCH_ROLES = ["ConverterSponsor", "PlatformAdmin"]
SWEEP_ROLES = ["ConverterSponsor", "StateRegulator", "PlatformAdmin"]
ESCROW_SUMMARY_ROLES = ["ConverterSponsor", "EscrowAgent", "StateRegulator",
                        "PlatformAdmin"]
WARRANTABILITY_ROLES = ["ConverterSponsor", "LenderUnderwriter",
                        "StateRegulator", "PlatformAdmin"]
RELOCATION_SUMMARY_ROLES = ["ConverterSponsor", "StateRegulator",
                            "PlatformAdmin"]

DEFAULT_MAX_OVERLAPPING_REMEDIATIONS = 2


@bp.post("/conversion-projects")
def create_project():
    v.authorize(CREATE_ROLES)
    body = v.parse([
        v.field("building_address", "string", max_len=200),
        v.field("year_built", "integer", minimum=1800, maximum=2026),
        v.field("total_unit_count", "integer", minimum=2, maximum=400),
        v.field("sponsor_user_id", "string"),
        v.field("max_overlapping_remediations", "integer", required=False,
                default=DEFAULT_MAX_OVERLAPPING_REMEDIATIONS, minimum=1,
                maximum=5),
    ])
    project = project_service.new_project(body)
    return envelope.object_response(serializers.dump(project), 201)


@bp.get("/conversion-projects")
def list_projects():
    v.authorize(LIST_ROLES)
    limit, offset = v.pagination()
    records = [p for p in store.ordered(store.projects.values())
               if v.matches(p,
                            status=v.filter_value("status"),
                            posture=v.filter_value("posture"),
                            suitability_gate=v.filter_value("suitability_gate"),
                            sponsor_user_id=v.filter_value("sponsor_user_id"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/conversion-projects/<project_id>")
def get_project(project_id):
    v.authorize(READ_ROLES)
    project = v.get_project(project_id)
    return envelope.object_response(serializers.dump(project), 200)


@bp.patch("/conversion-projects/<project_id>")
def patch_project(project_id):
    v.authorize(PATCH_ROLES)
    project = v.get_project(project_id)
    body = v.parse([
        v.field("building_address", "string", required=False, max_len=200),
        v.field("total_unit_count", "integer", required=False, minimum=2,
                maximum=400),
        v.field("max_overlapping_remediations", "integer", required=False,
                minimum=1, maximum=5),
    ])
    v.gate_not_frozen(project)
    for name in ("building_address", "total_unit_count",
                 "max_overlapping_remediations"):
        if name in body:
            project[name] = body[name]
    store.touch(project)
    return envelope.object_response(serializers.dump(project), 200)


@bp.post("/conversion-projects/<project_id>/posture-recalculations")
def recalculate_posture(project_id):
    v.authorize(SWEEP_ROLES)
    project = v.get_project(project_id)
    # Running a recalculation is on the FROZEN exemption list.
    project_service.posture_recalculation(project)
    return envelope.object_response(serializers.dump(project), 200)


@bp.get("/conversion-projects/<project_id>/escrow-summary")
def escrow_summary(project_id):
    v.authorize(ESCROW_SUMMARY_ROLES)
    project = v.get_project(project_id)
    return envelope.object_response(serializers.dump(project), 200)


@bp.get("/conversion-projects/<project_id>/relocation-summary")
def relocation_summary(project_id):
    v.authorize(RELOCATION_SUMMARY_ROLES)
    project = v.get_project(project_id)
    return envelope.object_response(serializers.dump(project), 200)


@bp.get("/conversion-projects/<project_id>/warrantability-summary")
def warrantability_summary(project_id):
    v.authorize(WARRANTABILITY_ROLES)
    project = v.get_project(project_id)
    # The read is not passive: it runs both bases and persists both verdicts.
    sales.recompute_warrantability(project, "contract", bump=False)
    sales.recompute_warrantability(project, "closed", bump=False)
    return envelope.object_response(serializers.dump(project), 200)
