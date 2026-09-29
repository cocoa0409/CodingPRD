"""The cumulative baseline and the resource-effects analyses (PRD 3.7)."""

from flask import Blueprint

import db
import response
import validation as v
from errors import fail
from middleware import endpoint
from routes.helpers import list_response, of_action, office_of, path_row
from services import calc, record, rollups

bp = Blueprint("analysis", __name__)

CUMULATIVE_SPEC = {
    "resource_area": {"required": True, "check": v.c_enum(v.RESOURCE_AREAS)},
    "label": {"required": True, "check": v.c_str(1)},
    "intensity_contribution": {"required": True, "check": v.c_num(lo=0, hi=100)},
    "footprint_hectares": {"required": True, "check": v.c_num(lo=0)},
    "distance_km": {"required": True, "check": v.c_num(lo=0)},
    "temporal_scope": {
        "required": True,
        "check": v.c_enum(("PAST", "PRESENT", "REASONABLY_FORESEEABLE")),
    },
}

ANALYSIS_SPEC = {
    "resource_area": {"required": True, "check": v.c_enum(v.RESOURCE_AREAS)},
    "intensity_score": {"required": True, "check": v.c_num(lo=0, hi=100)},
    "context_sensitivity_score": {"required": True, "check": v.c_num(lo=0, hi=100)},
    "affected_area_hectares": {"required": True, "check": v.c_num(lo=0)},
    "mitigation_reduction_points": {"check": v.c_num(lo=0, hi=40), "default": 0.0},
}

ANALYSIS_READ_ROLES = [
    "ResourceSpecialist",
    "NepaCoordinator",
    "ReviewingOfficial",
    "DecidingOfficial",
]


# ------------------------------------------------------- cumulative baseline


@endpoint(bp, "/proposed-actions/<action_id>/cumulative-actions", ["POST"], ["ResourceSpecialist"])
def create_cumulative_action(action_id):
    body = v.parse_body(CUMULATIVE_SPEC)
    action = path_row("actions", action_id, "proposed action")
    office = office_of(action)

    for entry in of_action("cumulative_actions", action["id"]):
        if entry["resource_area"] == body["resource_area"] and entry["label"] == body["label"]:
            fail(
                "ERR_CONSTRAINT_VIOLATION",
                "label is already used in this resource area for the action",
            )

    fields = dict(body)
    fields["action_id"] = action["id"]
    fields["inclusion_status"] = calc.cumulative_inclusion(body["distance_km"], office)
    row = db.new_row("cumulative_actions", fields)
    return response.created(db.public(row))


@endpoint(bp, "/proposed-actions/<action_id>/cumulative-actions", ["GET"], [
    "ResourceSpecialist",
    "NepaCoordinator",
    "ReviewingOfficial",
])
def list_cumulative_actions(action_id):
    path_row("actions", action_id, "proposed action")
    return list_response(
        of_action("cumulative_actions", action_id), "resource_area", "inclusion_status"
    )


# -------------------------------------------------------- resource analyses


@endpoint(bp, "/proposed-actions/<action_id>/resource-analyses", ["POST"], ["ResourceSpecialist"])
def create_analysis(action_id):
    body = v.parse_body(ANALYSIS_SPEC)
    action = path_row("actions", action_id, "proposed action")

    for existing in of_action("analyses", action["id"]):
        if existing["resource_area"] == body["resource_area"]:
            fail(
                "ERR_DUPLICATE_RESOURCE_ANALYSIS",
                "an analysis already exists for this action and resource area",
            )

    fields = dict(body)
    fields["action_id"] = action["id"]
    fields.update(
        {
            "cumulative_effect_score": 0.0,
            "unmitigated_score": 0.0,
            "mitigated_score": 0.0,
            "significance_score": None,
            "significance_determination": None,
            "variant_applied": None,
            "status": "DRAFT",
        }
    )
    row = db.new_row("analyses", fields)
    return response.created(db.public(row))


@endpoint(
    bp, "/proposed-actions/<action_id>/resource-analyses", ["GET"], ANALYSIS_READ_ROLES
)
def list_analyses(action_id):
    path_row("actions", action_id, "proposed action")
    return list_response(of_action("analyses", action_id), "resource_area", "status")


@endpoint(bp, "/resource-analyses/<analysis_id>", ["GET"], ANALYSIS_READ_ROLES)
def get_analysis(analysis_id):
    analysis = path_row("analyses", analysis_id, "resource analysis")
    return response.ok(db.public(analysis))


@endpoint(bp, "/resource-analyses/<analysis_id>/finalize", ["POST"], ["ResourceSpecialist"])
def finalize_analysis(analysis_id):
    body = v.parse_body(
        {"basis": {"required": True, "check": v.c_enum(("UNMITIGATED", "MITIGATED"))}}
    )
    analysis = path_row("analyses", analysis_id, "resource analysis")
    action = db.find("actions", analysis["action_id"])
    office = office_of(action)

    if analysis["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT analysis may be finalized")
    if action["review_stage"] != "ANALYSIS":
        fail("ERR_INVALID_STATE", "the action's review_stage must be ANALYSIS")
    if body["basis"] == "MITIGATED" and not calc.D(analysis["mitigation_reduction_points"]) > 0:
        fail(
            "ERR_MITIGATION_BASIS_REQUIRED",
            "a MITIGATED basis requires mitigation_reduction_points greater than zero",
        )

    included = [
        entry
        for entry in of_action("cumulative_actions", action["id"])
        if entry["resource_area"] == analysis["resource_area"]
        and entry["inclusion_status"] == "INCLUDED"
    ]
    cumulative = calc.cumulative_effect_score(included)
    unmitigated, mitigated = calc.significance_scores(analysis, office, cumulative)

    analysis["cumulative_effect_score"] = float(cumulative)
    analysis["unmitigated_score"] = float(unmitigated)
    analysis["mitigated_score"] = float(mitigated)
    analysis["variant_applied"] = body["basis"]
    chosen = unmitigated if body["basis"] == "UNMITIGATED" else mitigated
    analysis["significance_score"] = float(chosen)
    analysis["significance_determination"] = calc.determination(chosen, office)
    analysis["status"] = "FINAL"
    db.touch(analysis)

    for issue in of_action("issues", action["id"]):
        if issue["resource_area"] == analysis["resource_area"] and issue["status"] == "OPEN":
            issue["status"] = "ANALYZED"
            db.touch(issue)

    rollups.refresh_action(action)
    record.add_entry(
        action,
        "ANALYSIS_FINALIZED",
        "ResourceAnalysis",
        analysis["id"],
        "Resource analysis for %s finalized on a %s basis"
        % (analysis["resource_area"], body["basis"]),
    )
    return response.ok(db.public(analysis))


@endpoint(bp, "/resource-analyses/<analysis_id>/reopen", ["POST"], ["ResourceSpecialist"])
def reopen_analysis(analysis_id):
    v.no_body()
    analysis = path_row("analyses", analysis_id, "resource analysis")
    action = db.find("actions", analysis["action_id"])

    if analysis["status"] != "FINAL":
        fail("ERR_INVALID_STATE", "only a FINAL analysis may be reopened")

    for document in of_action("documents", action["id"]):
        if document["publication_status"] in ("PUBLISHED", "FINAL"):
            fail("ERR_ANALYSIS_LOCKED", "a published or final document freezes the analysis")
    for decision in of_action("decisions", action["id"]):
        if decision["status"] == "SIGNED":
            fail("ERR_ANALYSIS_LOCKED", "a signed decision freezes the analysis")

    analysis["significance_score"] = None
    analysis["significance_determination"] = None
    analysis["variant_applied"] = None
    analysis["status"] = "DRAFT"
    db.touch(analysis)

    for issue in of_action("issues", action["id"]):
        if issue["resource_area"] == analysis["resource_area"] and issue["status"] == "ANALYZED":
            issue["status"] = "OPEN"
            db.touch(issue)

    rollups.refresh_action(action)
    record.add_entry(
        action,
        "ANALYSIS_REOPENED",
        "ResourceAnalysis",
        analysis["id"],
        "Resource analysis for %s returned to DRAFT" % analysis["resource_area"],
    )
    return response.ok(db.public(analysis))
