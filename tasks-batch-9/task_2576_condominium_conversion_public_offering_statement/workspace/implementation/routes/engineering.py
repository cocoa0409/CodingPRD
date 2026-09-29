"""Engineering reports, component inventories and independent peer review.

Every write in this module except reopening a rejected report sits on the
FROZEN exemption list of PRD 3.1, so the engineering track stays open while the
project is frozen -- that is what makes a frozen project recoverable.
"""

from flask import Blueprint

import clock
import envelope
import serializers
import store
import validation as v
from errors import ApiError
from services import cascades, projects as project_service, suitability

bp = Blueprint("engineering", __name__)

REPORT_CREATE_ROLES = ["LicensedEngineer", "ConverterSponsor"]
REPORT_READ_ROLES = ["ConverterSponsor", "LicensedEngineer",
                     "PeerReviewEngineer", "StateRegulator", "PlatformAdmin"]
COMPONENT_READ_ROLES = ["LicensedEngineer", "PeerReviewEngineer",
                        "ConverterSponsor", "StateRegulator", "PlatformAdmin"]
ASSESSMENT_CREATE_ROLES = ["PeerReviewEngineer", "ConverterSponsor"]
ASSESSMENT_READ_ROLES = ["ConverterSponsor", "PeerReviewEngineer",
                         "LicensedEngineer", "StateRegulator", "PlatformAdmin"]
ASSESSMENT_LIST_ROLES = ["ConverterSponsor", "PeerReviewEngineer",
                         "StateRegulator", "LenderUnderwriter", "PlatformAdmin"]
ASSESSMENT_GET_ROLES = ["ConverterSponsor", "PeerReviewEngineer",
                        "LicensedEngineer", "StateRegulator",
                        "LenderUnderwriter", "PlatformAdmin"]

REPORT_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REVISION_REQUESTED",
                   "SUPERSEDED"]
COMPONENT_TYPES = ["ROOF", "ELEVATOR", "HVAC", "PLUMBING_RISERS",
                   "ELECTRICAL_SERVICE", "FACADE", "FOUNDATION",
                   "PARKING_DECK", "FIRE_SUPPRESSION"]
CONDITION_RATINGS = ["EXCELLENT", "GOOD", "FAIR", "POOR"]
VARIANTS = ["AS_INSPECTED", "POST_REMEDIATION"]


@bp.post("/conversion-projects/<project_id>/engineering-reports")
def create_report(project_id):
    v.authorize(REPORT_CREATE_ROLES)
    project = v.get_project(project_id)
    body = v.parse([
        v.field("report_label", "string", max_len=200),
        v.field("inspection_date", "datetime"),
        v.field("submitted_by_user_id", "string"),
    ])
    v.require_unique(store.project_reports(project["id"]),
                     report_label=body["report_label"])
    report = store.new_record(store.engineering_reports, {
        "_type": "EngineeringReport",
        "conversion_project_id": project["id"],
        "report_label": body["report_label"],
        "inspection_date": body["inspection_date"],
        "submitted_by_user_id": body["submitted_by_user_id"],
        "reviewed_by_user_id": None,
        "status": "DRAFT",
        "revision_round": 0,
        "verified_component_count": 0,
        "total_replacement_cost_cents": 0,
    })
    return envelope.object_response(serializers.dump(report), 201)


@bp.get("/conversion-projects/<project_id>/engineering-reports")
def list_project_reports(project_id):
    v.authorize(REPORT_READ_ROLES)
    project = v.get_project(project_id)
    limit, offset = v.pagination()
    records = [r for r in store.project_reports(project["id"])
               if v.matches(r, status=v.filter_value("status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/engineering-reports/<report_id>")
def get_report(report_id):
    v.authorize(REPORT_READ_ROLES)
    report = v.get_report(report_id)
    return envelope.object_response(serializers.dump(report), 200)


@bp.post("/engineering-reports/<report_id>/submit")
def submit_report(report_id):
    user_id, _role = v.authorize(["LicensedEngineer"])
    report = v.get_report(report_id)
    project = v.get_project(report["conversion_project_id"])
    v.require_state(report, "status", ("DRAFT",))
    components = store.report_components(report["id"])
    if not components:
        # An empty inventory is a declared precondition of DRAFT -> SUBMITTED.
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = user_id
    report["revision_round"] = report["revision_round"] + 1
    for component in components:
        if component["verification_status"] != "VERIFIED":
            component["verification_status"] = "VERIFIED"
            store.touch(component)
    store.touch(report)
    cascades.recompute_report_counters(report)
    # Submission bubbles up only out of FEASIBILITY.
    if project["status"] == "FEASIBILITY":
        project["status"] = "SUITABILITY_REVIEW"
        store.touch(project)
        project_service.sync(project)
        project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(report), 200)


@bp.post("/engineering-reports/<report_id>/peer-review-decisions")
def peer_review(report_id):
    user_id, _role = v.authorize(["PeerReviewEngineer"])
    report = v.get_report(report_id)
    v.require_separation(user_id, report["submitted_by_user_id"])
    project = v.get_project(report["conversion_project_id"])
    body = v.parse([
        v.field("decision", "enum", values=["ACCEPT", "REJECT"]),
        v.field("reviewed_by_user_id", "string"),
        v.field("review_note", "string", required=False, max_len=500),
    ])
    v.require_state(report, "status", ("SUBMITTED",))
    if body["decision"] == "ACCEPT":
        if report["verified_component_count"] < 1:
            # A declared precondition of SUBMITTED -> ACCEPTED.
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        report["status"] = "ACCEPTED"
        report["reviewed_by_user_id"] = user_id
        store.touch(report)
        for other in store.project_reports(project["id"]):
            if other["id"] == report["id"] or other["status"] != "ACCEPTED":
                continue
            other["status"] = "SUPERSEDED"
            for assessment in store.report_assessments(other["id"]):
                if assessment["status"] == "EFFECTIVE":
                    assessment["status"] = "INVALIDATED"
                    store.touch(assessment)
            store.touch(other)
    else:
        cascades.reject_report(report, project, user_id)
    return envelope.object_response(serializers.dump(report), 200)


@bp.post("/engineering-reports/<report_id>/revisions")
def revise_report(report_id):
    v.authorize(["LicensedEngineer"])
    report = v.get_report(report_id)
    project = v.get_project(report["conversion_project_id"])
    v.parse([v.field("revision_note", "string", required=False, max_len=500)])
    v.gate_not_frozen(project)
    v.require_state(report, "status", ("REVISION_REQUESTED",))
    report["status"] = "DRAFT"
    store.touch(report)
    return envelope.object_response(serializers.dump(report), 200)


# --- major components ------------------------------------------------------

COMPONENT_INPUTS = [
    v.field("remaining_useful_life_years", "integer", minimum=0, maximum=80),
    v.field("effective_age_years", "integer", minimum=0, maximum=120),
    v.field("replacement_cost_cents", "integer", minimum=0),
    v.field("funded_pct_bp", "integer", required=False, default=0, minimum=0,
            maximum=10000),
    v.field("condition_rating", "enum", values=CONDITION_RATINGS),
    v.field("planned_remediation_gain_years", "integer", required=False,
            default=0, minimum=0, maximum=40),
    v.field("is_life_safety", "boolean", required=False, default=False),
    v.field("is_structural", "boolean", required=False, default=False),
]


@bp.post("/engineering-reports/<report_id>/major-components")
def create_component(report_id):
    v.authorize(["LicensedEngineer"])
    report = v.get_report(report_id)
    body = v.parse([v.field("component_type", "enum", values=COMPONENT_TYPES)]
                   + COMPONENT_INPUTS)
    v.require_unique(store.report_components(report["id"]),
                     component_type=body["component_type"])
    fields = {"_type": "MajorComponent",
              "engineering_report_id": report["id"],
              "verification_status": "UNVERIFIED"}
    fields.update(body)
    component = store.new_record(store.major_components, fields)
    cascades.recompute_report_counters(report)
    return envelope.object_response(serializers.dump(component), 201)


@bp.get("/engineering-reports/<report_id>/major-components")
def list_components(report_id):
    v.authorize(COMPONENT_READ_ROLES)
    report = v.get_report(report_id)
    limit, offset = v.pagination()
    records = [
        c for c in store.report_components(report["id"])
        if v.matches(c,
                     verification_status=v.filter_value("verification_status"),
                     component_type=v.filter_value("component_type"),
                     is_life_safety=v.filter_bool("is_life_safety"),
                     is_structural=v.filter_bool("is_structural"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/major-components/<component_id>")
def get_component(component_id):
    v.authorize(COMPONENT_READ_ROLES)
    component = v.get_component(component_id)
    return envelope.object_response(serializers.dump(component), 200)


@bp.patch("/major-components/<component_id>")
def patch_component(component_id):
    v.authorize(["LicensedEngineer"])
    component = v.get_component(component_id)
    report = v.get_report(component["engineering_report_id"])
    project = v.get_project(report["conversion_project_id"])
    body = v.parse([dict(spec, required=False, default=v.MISSING)
                    for spec in COMPONENT_INPUTS])
    for name, value in body.items():
        component[name] = value
    store.touch(component)
    cascades.recompute_report_counters(report)
    if report["status"] == "ACCEPTED":
        # The edit invalidates the accepted engineering opinion.
        report["status"] = "SUPERSEDED"
        store.touch(report)
        project["suitability_gate"] = "UNEVALUATED"
        store.touch(project)
        project_service.recompute_posture(project)
    elif report["status"] == "REVISION_REQUESTED":
        # The edit reopens the drafting cycle.
        report["status"] = "DRAFT"
        store.touch(report)
    return envelope.object_response(serializers.dump(component), 200)


@bp.post("/major-components/<component_id>/verification")
def verify_component(component_id):
    v.authorize(["PeerReviewEngineer"])
    component = v.get_component(component_id)
    report = v.get_report(component["engineering_report_id"])
    project = v.get_project(report["conversion_project_id"])
    body = v.parse([v.field("verified", "boolean")])
    v.gate_not_frozen(project)
    component["verification_status"] = ("VERIFIED" if body["verified"]
                                       else "UNVERIFIED")
    store.touch(component)
    cascades.recompute_report_counters(report)
    return envelope.object_response(serializers.dump(component), 200)


# --- suitability assessments ----------------------------------------------

def _project_assessment_verdict(project, assessment):
    """The project's gate and score always mirror the assessment just made."""
    project["suitability_score"] = assessment["score"]
    project["suitability_gate"] = ("PASSED" if assessment["verdict"] == "PASSED"
                                  else "FAILED")
    if (project["status"] == "SUITABILITY_REVIEW"
            and assessment["verdict"] == "PASSED"):
        project["status"] = "DOCUMENTS_PREPARATION"
    store.touch(project)
    project_service.recompute_posture(project)
    return project


@bp.post("/engineering-reports/<report_id>/suitability-assessments")
def create_assessment(report_id):
    v.authorize(ASSESSMENT_CREATE_ROLES)
    report = v.get_report(report_id)
    project = v.get_project(report["conversion_project_id"])
    body = v.parse([
        v.field("variant", "enum", values=VARIANTS),
        v.field("expected_engineering_report_version", "integer", minimum=0),
    ])
    v.require_version(body["expected_engineering_report_version"], report,
                      "ERR_STALE_REPORT_VERSION")
    for prior in store.report_assessments(report["id"]):
        if (prior["variant"] == body["variant"]
                and prior["status"] == "EFFECTIVE"):
            prior["status"] = "SUPERSEDED"
            store.touch(prior)
    scored = suitability.score_report(report, body["variant"])
    assessment = store.new_record(store.suitability_assessments, {
        "_type": "SuitabilityAssessment",
        "engineering_report_id": report["id"],
        "conversion_project_id": report["conversion_project_id"],
        "variant": body["variant"],
        "score": scored["score"],
        "basis": scored["basis"],
        "critical_cap_applied": scored["critical_cap_applied"],
        "verdict": scored["verdict"],
        "status": "EFFECTIVE",
    })
    _project_assessment_verdict(project, assessment)
    store.touch(report)
    return envelope.object_response(serializers.dump(assessment), 201)


@bp.get("/engineering-reports/<report_id>/suitability-assessments")
def list_report_assessments(report_id):
    v.authorize(ASSESSMENT_READ_ROLES)
    report = v.get_report(report_id)
    limit, offset = v.pagination()
    records = [a for a in store.report_assessments(report["id"])
               if v.matches(a,
                            variant=v.filter_value("variant"),
                            verdict=v.filter_value("verdict"),
                            status=v.filter_value("status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/suitability-assessments")
def list_assessments():
    v.authorize(ASSESSMENT_LIST_ROLES)
    limit, offset = v.pagination()
    records = [
        a for a in store.ordered(store.suitability_assessments.values())
        if v.matches(
            a,
            conversion_project_id=v.filter_value("conversion_project_id"),
            engineering_report_id=v.filter_value("engineering_report_id"),
            variant=v.filter_value("variant"),
            verdict=v.filter_value("verdict"),
            status=v.filter_value("status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/suitability-assessments/<assessment_id>")
def get_assessment(assessment_id):
    v.authorize(ASSESSMENT_GET_ROLES)
    assessment = v.get_assessment(assessment_id)
    return envelope.object_response(serializers.dump(assessment), 200)
