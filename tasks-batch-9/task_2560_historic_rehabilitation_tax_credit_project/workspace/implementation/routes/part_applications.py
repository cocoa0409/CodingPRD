"""Part applications, the two-agency review gauntlet, and standards findings."""

from flask import Blueprint

import calc
import services
from auth import acting_reviewer, own_project, require
from clock import clock, parse_iso
from db import base_record, ordered, public, store, touch
from errors import ApiError
from response import created_response, object_response
from support import fetch, filter_eq, respond_list
from validate import (
    body,
    pagination,
    query_int,
    query_str,
    req_enum,
    req_id_list,
    req_int,
    req_str,
)

bp = Blueprint("part_applications", __name__)

NON_TERMINAL = ("DRAFT", "SHPO_REVIEW", "NPS_REVIEW", "CONDITIONAL", "REVISION_REQUIRED")
OCCUPYING = ("SHPO_REVIEW", "NPS_REVIEW", "CONDITIONAL")
RECOMMENDATIONS = ("RECOMMEND_APPROVAL", "RECOMMEND_DENIAL")
DETERMINATIONS = ("APPROVED", "CONDITIONAL", "DENIED")
SEVERITIES = ("ADVISORY", "CONDITION", "VIOLATION")

ALL_READ_ROLES = (
    "PlatformAdmin",
    "Developer",
    "ShpoReviewer",
    "NpsReviewer",
    "ComplianceMonitor",
    "InvestorAdmin",
)
FINDING_READ_ROLES = (
    "PlatformAdmin",
    "Developer",
    "ShpoReviewer",
    "NpsReviewer",
    "ComplianceMonitor",
)


def _window_conflicts(reviewer_id, exclude_id):
    """Closed-interval occupation count for a prospective submission window."""
    start = clock.today()
    end = calc.add_days(start, calc.SHPO_REVIEW_WINDOW_DAYS)
    conflicts = 0
    for other in store.part_applications.values():
        if other["id"] == exclude_id:
            continue
        if other["shpo_reviewer_id"] != reviewer_id:
            continue
        if other["status"] not in OCCUPYING:
            continue
        if other["submitted_at"] is None or other["review_window_end"] is None:
            continue
        other_start = parse_iso(other["submitted_at"]).date()
        other_end = parse_iso(other["review_window_end"]).date()
        if calc.closed_overlap(start, end, other_start, other_end):
            conflicts += 1
    return conflicts


def _stamp_submission(application):
    application["submitted_at"] = clock.now_iso()
    application["review_window_end"] = clock.plus_days_iso(calc.SHPO_REVIEW_WINDOW_DAYS)


# --------------------------------------------------------------------------
# create / read / list
# --------------------------------------------------------------------------


@bp.post("/part-applications")
def create_application():
    uid, _role = require("Developer")
    data = body()
    project_id = req_str(data, "project_id")
    part_number = req_int(data, "part_number", allowed=(1, 2, 3))
    narrative = req_str(data, "narrative", min_len=1, max_len=2000)
    expected = req_int(data, "expected_project_version", min_v=0)

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(project, uid)

    if project["certification_status"] == "DECERTIFIED":
        raise ApiError(
            "ERR_PROJECT_INVALID_STATE",
            "No part application may be created on a decertified project.",
        )

    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")

    siblings = services.project_apps(project_id)

    if part_number > 1:
        predecessor = [
            a
            for a in siblings
            if a["part_number"] == part_number - 1 and a["status"] in ("CONDITIONAL", "APPROVED")
        ]
        if not predecessor:
            raise ApiError("ERR_PART_SEQUENCE_VIOLATION")

    if any(a["part_number"] == part_number and a["status"] == "APPROVED" for a in siblings):
        raise ApiError("ERR_PART_ALREADY_CERTIFIED")

    if part_number == 3 and project["substantial_test_status"] != "MET":
        raise ApiError("ERR_SUBSTANTIAL_TEST_NOT_MET")

    superseded_id = None
    for other in siblings:
        if other["part_number"] == part_number and other["status"] in NON_TERMINAL:
            other["status"] = "SUPERSEDED"
            touch(other)
            superseded_id = other["id"]

    record = base_record()
    record.update(
        {
            "project_id": project_id,
            "part_number": part_number,
            "narrative": narrative,
            "status": "DRAFT",
            "supersedes_application_id": superseded_id,
            "review_round": 1,
            "shpo_reviewer_id": None,
            "nps_reviewer_id": None,
            "submitted_at": None,
            "review_window_end": None,
            "decision_at": None,
            "shpo_recommendation": "NONE",
            "determination": "NONE",
            "unresolved_condition_count": 0,
            "unresolved_violation_count": 0,
        }
    )
    store.part_applications[record["id"]] = record
    touch(project)
    return created_response(public(record))


@bp.get("/part-applications")
def list_applications():
    require(*ALL_READ_ROLES)
    limit, offset = pagination()
    part_number = query_int("part_number")
    rows = ordered(store.part_applications.values())
    rows = filter_eq(rows, "project_id", query_str("project_id"))
    rows = filter_eq(rows, "part_number", part_number)
    rows = filter_eq(rows, "status", query_str("status"))
    rows = filter_eq(rows, "shpo_reviewer_id", query_str("shpo_reviewer_id"))
    rows = filter_eq(rows, "nps_reviewer_id", query_str("nps_reviewer_id"))
    rows = filter_eq(rows, "supersedes_application_id", query_str("supersedes_application_id"))
    return respond_list(rows, limit, offset)


@bp.get("/part-applications/<application_id>")
def read_application(application_id):
    require(*ALL_READ_ROLES)
    record = fetch(store.part_applications, application_id, "ERR_PART_APPLICATION_NOT_FOUND")
    return object_response(public(record))


# --------------------------------------------------------------------------
# submit / resubmit
# --------------------------------------------------------------------------


@bp.post("/part-applications/<application_id>/submit")
def submit_application(application_id):
    uid, _role = require("Developer")
    data = body()
    reviewer_id = req_str(data, "shpo_reviewer_id")

    application = fetch(store.part_applications, application_id, "ERR_PART_APPLICATION_NOT_FOUND")
    reviewer = fetch(store.reviewers, reviewer_id, "ERR_REVIEWER_NOT_FOUND")
    project = store.projects[application["project_id"]]
    own_project(project, uid)

    if reviewer["agency"] != "SHPO" or reviewer["credential_status"] != "ACTIVE":
        raise ApiError("ERR_REVIEWER_NOT_ELIGIBLE")

    if application["status"] != "DRAFT":
        raise ApiError(
            "ERR_PART_APPLICATION_INVALID_STATE", "Only a DRAFT application may be submitted."
        )
    if application["part_number"] == 3 and project["placed_in_service_date"] is None:
        raise ApiError("ERR_PROJECT_NOT_PLACED_IN_SERVICE")

    prop = store.properties[project["property_id"]]
    if prop["listing_status"] == "DISTRICT_NONCONTRIBUTING":
        raise ApiError(
            "ERR_PROPERTY_NOT_CERTIFIED_HISTORIC",
            "A non-contributing building in a district can never be certified.",
        )
    if application["part_number"] in (2, 3) and prop["evaluation_status"] != "CERTIFIED_HISTORIC":
        raise ApiError("ERR_PROPERTY_NOT_CERTIFIED_HISTORIC")

    if _window_conflicts(reviewer_id, application["id"]) >= calc.REVIEWER_WINDOW_CAPACITY:
        raise ApiError("ERR_REVIEWER_WINDOW_CAPACITY")

    application["shpo_reviewer_id"] = reviewer_id
    application["status"] = "SHPO_REVIEW"
    _stamp_submission(application)
    touch(application)
    return object_response(public(application))


@bp.post("/part-applications/<application_id>/resubmit")
def resubmit_application(application_id):
    uid, _role = require("Developer")
    data = body()
    narrative = req_str(data, "narrative", min_len=1, max_len=2000)

    application = fetch(store.part_applications, application_id, "ERR_PART_APPLICATION_NOT_FOUND")
    project = store.projects[application["project_id"]]
    own_project(project, uid)

    reviewer_id = application["shpo_reviewer_id"]
    if reviewer_id is not None:
        reviewer = store.reviewers.get(reviewer_id)
        if reviewer is None or reviewer["credential_status"] != "ACTIVE":
            raise ApiError("ERR_REVIEWER_NOT_ELIGIBLE")

    if application["status"] != "REVISION_REQUIRED":
        raise ApiError(
            "ERR_PART_APPLICATION_INVALID_STATE",
            "Only an application returned for revision may be resubmitted.",
        )
    if application["review_round"] + 1 > calc.MAX_REVIEW_ROUNDS:
        raise ApiError(
            "ERR_PART_APPLICATION_INVALID_STATE",
            "An application passes through at most three review rounds.",
        )

    if _window_conflicts(reviewer_id, application["id"]) >= calc.REVIEWER_WINDOW_CAPACITY:
        raise ApiError("ERR_REVIEWER_WINDOW_CAPACITY")

    application["narrative"] = narrative
    application["review_round"] += 1
    application["status"] = "SHPO_REVIEW"
    application["shpo_recommendation"] = "NONE"
    application["determination"] = "NONE"
    application["nps_reviewer_id"] = None
    application["decision_at"] = None
    _stamp_submission(application)
    touch(application)
    return object_response(public(application))


# --------------------------------------------------------------------------
# SHPO recommendation
# --------------------------------------------------------------------------


@bp.post("/part-applications/<application_id>/shpo-recommend")
def shpo_recommend(application_id):
    uid, _role = require("ShpoReviewer")
    data = body()
    recommendation = req_enum(data, "recommendation", RECOMMENDATIONS)
    req_str(data, "review_note", min_len=1, max_len=2000, required=False)

    application = fetch(store.part_applications, application_id, "ERR_PART_APPLICATION_NOT_FOUND")
    acting_reviewer(uid, "SHPO")

    if application["status"] != "SHPO_REVIEW":
        raise ApiError(
            "ERR_PART_APPLICATION_INVALID_STATE",
            "A recommendation may only be recorded on an application in SHPO review.",
        )
    if application["shpo_reviewer_id"] != uid:
        raise ApiError(
            "ERR_UNAUTHORIZED", "Only the assigned SHPO reviewer may recommend on this application."
        )

    application["shpo_recommendation"] = recommendation
    application["status"] = "NPS_REVIEW"
    touch(application)
    return object_response(public(application))


# --------------------------------------------------------------------------
# NPS determination
# --------------------------------------------------------------------------


@bp.post("/part-applications/<application_id>/nps-determination")
def nps_determination(application_id):
    uid, _role = require("NpsReviewer")
    data = body()
    determination = req_enum(data, "determination", DETERMINATIONS)
    waived_ids = req_id_list(data, "waived_finding_ids")
    req_str(data, "review_note", min_len=1, max_len=2000, required=False)

    application = fetch(store.part_applications, application_id, "ERR_PART_APPLICATION_NOT_FOUND")

    waived = []
    for finding_id in waived_ids:
        waived.append(fetch(store.findings, finding_id, "ERR_STANDARD_FINDING_NOT_FOUND"))

    if application["shpo_reviewer_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    acting_reviewer(uid, "NPS")

    if application["status"] != "NPS_REVIEW":
        raise ApiError(
            "ERR_PART_APPLICATION_INVALID_STATE",
            "A determination may only be issued on an application in NPS review.",
        )

    if any(f["severity"] == "VIOLATION" for f in waived):
        raise ApiError(
            "ERR_PRESERVATION_STANDARD_VIOLATION",
            "A VIOLATION-severity finding can never be waived.",
        )

    waived_set = {f["id"] for f in waived}
    own_findings = services.app_findings(application["id"])
    violations = sum(
        1
        for f in own_findings
        if f["severity"] == "VIOLATION"
        and f["resolution_state"] == "UNRESOLVED"
        and f["id"] not in waived_set
    )
    conditions = sum(
        1
        for f in own_findings
        if f["severity"] == "CONDITION"
        and f["resolution_state"] == "UNRESOLVED"
        and f["id"] not in waived_set
    )

    project = store.projects[application["project_id"]]

    if determination == "APPROVED":
        if violations > 0:
            raise ApiError("ERR_PRESERVATION_STANDARD_VIOLATION")
        if conditions > 0:
            raise ApiError(
                "ERR_PART_APPLICATION_INVALID_STATE",
                "CONDITIONAL is the declared outcome while conditions remain unresolved.",
            )
        if application["part_number"] == 3 and project["substantial_test_status"] != "MET":
            raise ApiError("ERR_SUBSTANTIAL_TEST_NOT_MET")
    elif determination == "CONDITIONAL":
        if violations > 0:
            raise ApiError("ERR_PRESERVATION_STANDARD_VIOLATION")
        if conditions < 1:
            raise ApiError(
                "ERR_PART_APPLICATION_INVALID_STATE",
                "APPROVED is the declared outcome when no condition is unresolved.",
            )

    # --- commit the waivers -------------------------------------------------
    touched_apps = set()
    for finding in waived:
        if finding["resolution_state"] != "WAIVED":
            finding["resolution_state"] = "WAIVED"
            touch(finding)
            touched_apps.add(finding["part_application_id"])
    for app_id in touched_apps:
        if app_id == application["id"]:
            continue
        other = store.part_applications.get(app_id)
        if other is not None:
            services.recompute_finding_counts(other)
            touch(other)
    services.recompute_finding_counts(application)

    application["determination"] = determination
    application["nps_reviewer_id"] = uid
    application["decision_at"] = clock.now_iso()

    if determination == "APPROVED":
        application["status"] = "APPROVED"
    elif determination == "CONDITIONAL":
        application["status"] = "CONDITIONAL"
    else:
        application["status"] = "REVISION_REQUIRED"
    touch(application)

    prop = store.properties[project["property_id"]]
    if determination == "APPROVED":
        if application["part_number"] == 1:
            services.certify_property(prop)
        services.advance_certification(project, application["part_number"])
    elif determination == "DENIED" and application["part_number"] == 1:
        services.decertify(project, prop)

    return object_response(public(application))


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------


@bp.post("/part-applications/<application_id>/findings")
def create_finding(application_id):
    require("ShpoReviewer", "NpsReviewer")
    data = body()
    standard_number = req_int(data, "standard_number", min_v=1, max_v=10)
    severity = req_enum(data, "severity", SEVERITIES)
    description = req_str(data, "description", min_len=1, max_len=1000)

    application = fetch(store.part_applications, application_id, "ERR_PART_APPLICATION_NOT_FOUND")
    if application["status"] not in OCCUPYING:
        raise ApiError(
            "ERR_PART_APPLICATION_INVALID_STATE",
            "Findings may only be raised against an application under review.",
        )

    record = base_record()
    record.update(
        {
            "part_application_id": application["id"],
            "standard_number": standard_number,
            "severity": severity,
            "description": description,
            "resolution_state": "UNRESOLVED",
        }
    )
    store.findings[record["id"]] = record

    services.recompute_finding_counts(application)
    touch(application)

    project = store.projects[application["project_id"]]
    if severity == "VIOLATION" and project["compliance_status"] != "NOT_MONITORED":
        if services.rescore_in_service(project):
            touch(project)

    return created_response(public(record))


@bp.get("/part-applications/<application_id>/findings")
def list_findings(application_id):
    require(*FINDING_READ_ROLES)
    limit, offset = pagination()
    standard_number = query_int("standard_number")
    application = fetch(store.part_applications, application_id, "ERR_PART_APPLICATION_NOT_FOUND")
    rows = services.app_findings(application["id"])
    rows = filter_eq(rows, "severity", query_str("severity"))
    rows = filter_eq(rows, "resolution_state", query_str("resolution_state"))
    rows = filter_eq(rows, "standard_number", standard_number)
    return respond_list(rows, limit, offset)


@bp.get("/findings/<finding_id>")
def read_finding(finding_id):
    require(*FINDING_READ_ROLES)
    record = fetch(store.findings, finding_id, "ERR_STANDARD_FINDING_NOT_FOUND")
    return object_response(public(record))
