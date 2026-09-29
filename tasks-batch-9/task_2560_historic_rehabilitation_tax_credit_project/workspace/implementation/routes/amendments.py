"""Amendments and the two-agency concurrence fork-join (PRD 3.5)."""

from flask import Blueprint

import calc
import services
from auth import acting_reviewer, own_project, require
from clock import clock
from db import base_record, ordered, public, store, touch
from errors import ApiError
from response import created_response, object_response
from support import fetch, filter_eq, respond_list
from validate import body, pagination, query_str, req_enum, req_int, req_str

bp = Blueprint("amendments", __name__)

SCOPE_CATEGORIES = (
    "WINDOW_REPLACEMENT",
    "MASONRY_TREATMENT",
    "INTERIOR_PARTITION",
    "ROOF_ALTERATION",
    "SYSTEMS_UPGRADE",
    "ADDITION",
)
DECISIONS = ("CONCUR", "OBJECT")
NPS_SCOPE_CATEGORIES = ("ADDITION", "ROOF_ALTERATION")

READ_ROLES = (
    "PlatformAdmin",
    "Developer",
    "ShpoReviewer",
    "NpsReviewer",
    "ComplianceMonitor",
)


def _requires_nps(scope_category, cost_delta_cents, finding):
    if scope_category in NPS_SCOPE_CATEGORIES:
        return True
    if abs(cost_delta_cents) >= calc.NPS_CONCURRENCE_DELTA_CENTS:
        return True
    if finding is not None and finding["severity"] == "VIOLATION":
        return True
    return False


@bp.post("/amendments")
def create_amendment():
    uid, _role = require("Developer")
    data = body()
    project_id = req_str(data, "project_id")
    part_application_id = req_str(data, "part_application_id")
    scope_category = req_enum(data, "scope_category", SCOPE_CATEGORIES)
    change_description = req_str(data, "change_description", min_len=1, max_len=1000)
    cost_delta_cents = req_int(data, "cost_delta_cents")
    finding_id = req_str(data, "addresses_finding_id", required=False)

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    application = fetch(
        store.part_applications, part_application_id, "ERR_PART_APPLICATION_NOT_FOUND"
    )
    finding = None
    if finding_id is not None:
        finding = fetch(store.findings, finding_id, "ERR_STANDARD_FINDING_NOT_FOUND")

    own_project(project, uid)

    if finding is not None and finding["part_application_id"] != application["id"]:
        raise ApiError("ERR_AMENDMENT_FINDING_MISMATCH")

    record = base_record()
    record.update(
        {
            "project_id": project_id,
            "part_application_id": part_application_id,
            "addresses_finding_id": finding_id,
            "scope_category": scope_category,
            "change_description": change_description,
            "cost_delta_cents": cost_delta_cents,
            "requires_nps_concurrence": _requires_nps(scope_category, cost_delta_cents, finding),
            "status": "DRAFT",
            "shpo_decision": "NONE",
            "nps_decision": "NONE",
            "submitted_at": None,
        }
    )
    store.amendments[record["id"]] = record
    return created_response(public(record))


@bp.get("/amendments")
def list_amendments():
    require(*READ_ROLES)
    limit, offset = pagination()
    rows = ordered(store.amendments.values())
    rows = filter_eq(rows, "project_id", query_str("project_id"))
    rows = filter_eq(rows, "part_application_id", query_str("part_application_id"))
    rows = filter_eq(rows, "addresses_finding_id", query_str("addresses_finding_id"))
    rows = filter_eq(rows, "status", query_str("status"))
    return respond_list(rows, limit, offset)


@bp.get("/amendments/<amendment_id>")
def read_amendment(amendment_id):
    require(*READ_ROLES)
    record = fetch(store.amendments, amendment_id, "ERR_AMENDMENT_NOT_FOUND")
    return object_response(public(record))


@bp.post("/amendments/<amendment_id>/submit")
def submit_amendment(amendment_id):
    uid, _role = require("Developer")
    body()
    amendment = fetch(store.amendments, amendment_id, "ERR_AMENDMENT_NOT_FOUND")
    project = store.projects[amendment["project_id"]]
    own_project(project, uid)

    if amendment["status"] != "DRAFT":
        raise ApiError("ERR_AMENDMENT_INVALID_STATE", "Only a DRAFT amendment may be submitted.")

    application = store.part_applications[amendment["part_application_id"]]
    if application["part_number"] != 2 or application["status"] not in ("CONDITIONAL", "APPROVED"):
        raise ApiError(
            "ERR_AMENDMENT_INVALID_STATE",
            "An amendment may only be submitted against a conditional or approved Part 2 scope.",
        )

    amendment["status"] = "SUBMITTED"
    amendment["submitted_at"] = clock.now_iso()
    touch(amendment)
    return object_response(public(amendment))


def _resolution_cascade(amendment):
    """The four-hop cascade fired by the concurrence that reaches CONCURRED."""
    finding_id = amendment["addresses_finding_id"]
    if finding_id is None:
        return
    finding = store.findings.get(finding_id)
    if finding is None or finding["resolution_state"] != "UNRESOLVED":
        return
    if finding["part_application_id"] != amendment["part_application_id"]:
        return

    finding["resolution_state"] = "RESOLVED"
    touch(finding)

    application = store.part_applications[finding["part_application_id"]]
    services.recompute_finding_counts(application)

    completed = False
    if (
        application["unresolved_condition_count"] == 0
        and application["unresolved_violation_count"] == 0
        and application["status"] == "CONDITIONAL"
    ):
        application["status"] = "APPROVED"
        application["determination"] = "APPROVED"
        application["decision_at"] = clock.now_iso()
        completed = True
    touch(application)

    if completed:
        project = store.projects[application["project_id"]]
        prop = store.properties[project["property_id"]]
        if application["part_number"] == 1:
            services.certify_property(prop)
        services.advance_certification(project, application["part_number"])


def _objection_cascade(amendment):
    finding_id = amendment["addresses_finding_id"]
    if finding_id is None:
        return
    finding = store.findings.get(finding_id)
    if finding is None or finding["severity"] != "CONDITION":
        return
    if finding["resolution_state"] != "UNRESOLVED":
        return
    application = store.part_applications[finding["part_application_id"]]
    if application["status"] != "CONDITIONAL":
        return
    application["status"] = "REVISION_REQUIRED"
    application["determination"] = "DENIED"
    application["decision_at"] = clock.now_iso()
    touch(application)


@bp.post("/amendments/<amendment_id>/concur")
def concur_amendment(amendment_id):
    uid, role = require("ShpoReviewer", "NpsReviewer")
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    req_str(data, "concurrence_note", min_len=1, max_len=2000, required=False)

    amendment = fetch(store.amendments, amendment_id, "ERR_AMENDMENT_NOT_FOUND")
    agency = "SHPO" if role == "ShpoReviewer" else "NPS"
    acting_reviewer(uid, agency)

    application = store.part_applications[amendment["part_application_id"]]

    if agency == "SHPO":
        if amendment["status"] != "SUBMITTED" or amendment["shpo_decision"] != "NONE":
            raise ApiError(
                "ERR_AMENDMENT_INVALID_STATE",
                "The state office may only decide a submitted amendment once.",
            )
        if decision == "OBJECT":
            amendment["shpo_decision"] = "OBJECT"
            amendment["status"] = "OBJECTED"
            touch(amendment)
            _objection_cascade(amendment)
            return object_response(public(amendment))

        amendment["shpo_decision"] = "CONCUR"
        if amendment["requires_nps_concurrence"]:
            amendment["status"] = "SHPO_CONCURRED"
            touch(amendment)
            return object_response(public(amendment))

        amendment["status"] = "CONCURRED"
        touch(amendment)
        _resolution_cascade(amendment)
        return object_response(public(amendment))

    # --- NPS branch ---------------------------------------------------------
    if amendment["status"] != "SHPO_CONCURRED" or amendment["nps_decision"] != "NONE":
        raise ApiError(
            "ERR_AMENDMENT_INVALID_STATE",
            "The federal agency may only decide an amendment the state office has concurred in.",
        )

    if decision == "OBJECT":
        amendment["nps_decision"] = "OBJECT"
        amendment["status"] = "OBJECTED"
        touch(amendment)
        _objection_cascade(amendment)
        return object_response(public(amendment))

    if application["unresolved_violation_count"] != 0:
        raise ApiError("ERR_PRESERVATION_STANDARD_VIOLATION")

    amendment["nps_decision"] = "CONCUR"
    amendment["status"] = "CONCURRED"
    touch(amendment)
    _resolution_cascade(amendment)
    return object_response(public(amendment))
