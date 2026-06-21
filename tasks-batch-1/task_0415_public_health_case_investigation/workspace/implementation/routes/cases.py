"""Case lifecycle: open, interview, classify, close, reopen, link-lab, cluster."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import (base_entity, touch, parse_pagination, sorted_by_creation,
                     get_or_404, get_in_program_or_404, require_string,
                     require_bool, parse_dt)
from middleware import get_user_context, require_role
from response import success, success_list
from serializers import ser_case, ser_lab_result, ser_cluster
from calculations import (find_condition, compute_infectious_window,
                          compute_isolation_end, compute_completeness,
                          recompute_linked_positive)
from services import check_case_scope, evaluate_cluster, void_contact
from routes.config import ALL_ROLES

bp = Blueprint("cases", __name__)

CLASSIFY_VALUES = {"CONFIRMED", "PROBABLE", "NOT_A_CASE"}


# --- Open / List / Get ---
@bp.route("/surveillance/cases", methods=["POST"])
def open_case():
    _, role = get_user_context()
    require_role(role, {"IntakeProcessor", "CaseInvestigator"})
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    jurisdiction_id = require_string(body, "jurisdiction_id")
    condition_code = require_string(body, "condition_code")
    source_lab_result_id = require_string(body, "source_lab_result_id", required=False)

    with db.lock:
        get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        get_in_program_or_404(db.jurisdictions, jurisdiction_id, program_id, "ERR_JURISDICTION_NOT_FOUND")
        cond = find_condition(program_id, condition_code)
        if cond is None:
            raise err("ERR_CONDITION_NOT_FOUND", "condition_code unknown in program")
        if source_lab_result_id is not None:
            get_in_program_or_404(db.lab_results, source_lab_result_id, program_id, "ERR_LAB_RESULT_NOT_FOUND")

        # field-level validation after existence
        patient_reference = require_string(body, "patient_reference")
        is_symptomatic = require_bool(body, "is_symptomatic", default=True)
        for f in ("symptom_onset_date", "specimen_collection_date", "last_symptomatic_date"):
            if body.get(f) is not None:
                parse_dt(require_string(body, f, required=False))
        exposure_setting_location_id = require_string(body, "exposure_setting_location_id", required=False)

        ent = base_entity(common_fields=True)
        ent.update({
            "program_id": program_id,
            "jurisdiction_id": jurisdiction_id,
            "condition_code": condition_code,
            "patient_reference": patient_reference,
            "source_lab_result_id": source_lab_result_id,
            "source_contact_id": None,
            "symptom_onset_date": body.get("symptom_onset_date"),
            "specimen_collection_date": body.get("specimen_collection_date"),
            "last_symptomatic_date": body.get("last_symptomatic_date"),
            "is_symptomatic": is_symptomatic,
            "interview_completed": False,
            "infectious_start_date": None,
            "infectious_end_date": None,
            "isolation_end_date": None,
            "completeness_score": 0,
            "contact_count": 0,
            "linked_positive_count": 0,
            "cluster_id": None,
            "exposure_setting_location_id": exposure_setting_location_id,
            "classification": "SUSPECT",
            "status": "OPEN",
            "_prior_status": None,
        })
        db.cases[ent["id"]] = ent
        return success(ser_case(ent), 201)


@bp.route("/surveillance/cases", methods=["GET"])
def list_cases():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        filters = ["program_id", "jurisdiction_id", "condition_code", "status",
                   "cluster_id", "source_contact_id", "source_lab_result_id"]
        items = []
        for c in db.cases.values():
            ok = True
            for f in filters:
                v = request.args.get(f)
                if v is not None and c.get(f) != v:
                    ok = False
                    break
            if ok:
                items.append(c)
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_case(c) for c in page], limit, offset, total)


@bp.route("/surveillance/cases/<case_id>", methods=["GET"])
def get_case(case_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        c = get_or_404(db.cases, case_id, "ERR_CASE_NOT_FOUND")
        return success(ser_case(c), 200)


# --- Interview ---
@bp.route("/surveillance/cases/<case_id>/interview", methods=["POST"])
def interview_case(case_id):
    user_id, role = get_user_context()
    require_role(role, {"CaseInvestigator"})
    with db.lock:
        case = get_or_404(db.cases, case_id, "ERR_CASE_NOT_FOUND")
        check_case_scope(user_id, role, case)
        if case["status"] not in ("OPEN", "REOPENED"):
            raise err("ERR_CASE_NOT_INTERVIEWABLE", "Case not in OPEN/REOPENED for interview")
        body = request.get_json(silent=True) or {}
        # interview may revise these fields
        for f in ("symptom_onset_date", "specimen_collection_date", "last_symptomatic_date"):
            if f in body and body.get(f) is not None:
                parse_dt(require_string(body, f, required=False))
                case[f] = body[f]
            elif f in body and body.get(f) is None:
                case[f] = None
        if "is_symptomatic" in body:
            case["is_symptomatic"] = require_bool(body, "is_symptomatic", default=case["is_symptomatic"])

        # onset/specimen requirement
        if case["is_symptomatic"]:
            if not case.get("symptom_onset_date"):
                raise err("ERR_ONSET_OR_SPECIMEN_REQUIRED",
                          "symptom_onset_date required when symptomatic")
        else:
            if not case.get("specimen_collection_date"):
                raise err("ERR_ONSET_OR_SPECIMEN_REQUIRED",
                          "specimen_collection_date required when asymptomatic")

        case["status"] = "UNDER_INVESTIGATION"
        case["interview_completed"] = True
        start, end = compute_infectious_window(case)
        case["infectious_start_date"] = start
        case["infectious_end_date"] = end
        case["completeness_score"] = compute_completeness(case)
        touch(case)
        return success(ser_case(case), 200)


# --- Classify ---
@bp.route("/surveillance/cases/<case_id>/classify", methods=["POST"])
def classify_case(case_id):
    user_id, role = get_user_context()
    require_role(role, {"CaseInvestigator"})
    with db.lock:
        case = get_or_404(db.cases, case_id, "ERR_CASE_NOT_FOUND")
        check_case_scope(user_id, role, case)
        if case["status"] != "UNDER_INVESTIGATION":
            raise err("ERR_CASE_NOT_CLASSIFIABLE", "Case not in UNDER_INVESTIGATION for classify")
        if not case.get("interview_completed"):
            raise err("ERR_INTERVIEW_NOT_COMPLETE", "Classify attempted before interview completed")
        body = request.get_json(silent=True) or {}
        classification = body.get("classification")
        if classification not in CLASSIFY_VALUES:
            raise err("ERR_INVALID_CLASSIFICATION",
                      "classify value not in {CONFIRMED, PROBABLE, NOT_A_CASE}")

        cond = find_condition(case["program_id"], case["condition_code"])

        if classification == "CONFIRMED":
            if cond is not None and cond.get("requires_lab_confirmation") \
                    and case.get("linked_positive_count", 0) < 1:
                raise err("ERR_LAB_CONFIRMATION_REQUIRED",
                          "CONFIRMED requires >= 1 linked POSITIVE lab result")

        case["status"] = "CLASSIFIED"
        case["classification"] = classification

        if classification == "CONFIRMED":
            case["isolation_end_date"] = compute_isolation_end(case, cond)
            if case.get("exposure_setting_location_id"):
                evaluate_cluster(case)
        elif classification == "NOT_A_CASE":
            # depth-3 cascade: void each non-VOIDED contact of this case
            contacts = [c for c in db.contacts.values()
                        if c["source_case_id"] == case["id"] and c["status"] != "VOIDED"]
            for ct in contacts:
                void_contact(ct)
        # PROBABLE: no isolation, no cluster, no cascade

        case["completeness_score"] = compute_completeness(case)
        touch(case)
        return success(ser_case(case), 200)


# --- Close ---
@bp.route("/surveillance/cases/<case_id>/close", methods=["POST"])
def close_case(case_id):
    user_id, role = get_user_context()
    require_role(role, {"CaseInvestigator"})
    with db.lock:
        case = get_or_404(db.cases, case_id, "ERR_CASE_NOT_FOUND")
        check_case_scope(user_id, role, case)
        if case["status"] != "CLASSIFIED":
            raise err("ERR_CASE_NOT_CLOSEABLE", "Case not in CLASSIFIED for close")
        # no MONITORING_ACTIVE contact
        for c in db.contacts.values():
            if c["source_case_id"] == case["id"] and c["status"] == "MONITORING_ACTIVE":
                raise err("ERR_ACTIVE_MONITORING_EXISTS",
                          "Case close blocked: a contact is MONITORING_ACTIVE")
        # no REQUESTED transfer
        for t in db.transfers.values():
            if t["case_id"] == case["id"] and t["status"] == "REQUESTED":
                raise err("ERR_TRANSFER_PENDING_EXISTS",
                          "Case close blocked: a REQUESTED transfer exists")
        case["status"] = "CLOSED"
        touch(case)
        return success(ser_case(case), 200)


# --- Reopen ---
@bp.route("/surveillance/cases/<case_id>/reopen", methods=["POST"])
def reopen_case(case_id):
    user_id, role = get_user_context()
    require_role(role, {"CaseInvestigator"})
    with db.lock:
        case = get_or_404(db.cases, case_id, "ERR_CASE_NOT_FOUND")
        check_case_scope(user_id, role, case)
        if case["status"] != "CLOSED":
            raise err("ERR_CASE_NOT_REOPENABLE", "Case not in CLOSED for reopen")
        case["status"] = "REOPENED"
        case["classification"] = "SUSPECT"
        case["interview_completed"] = False
        case["infectious_start_date"] = None
        case["infectious_end_date"] = None
        case["isolation_end_date"] = None
        case["completeness_score"] = compute_completeness(case)
        touch(case)
        return success(ser_case(case), 200)


# --- Manual lab link ---
@bp.route("/surveillance/cases/<case_id>/link-lab-result", methods=["POST"])
def link_lab_result(case_id):
    user_id, role = get_user_context()
    require_role(role, {"CaseInvestigator"})
    with db.lock:
        case = get_or_404(db.cases, case_id, "ERR_CASE_NOT_FOUND")
        body = request.get_json(silent=True) or {}
        lab_result_id = require_string(body, "lab_result_id")
        lab = get_in_program_or_404(db.lab_results, lab_result_id, case["program_id"],
                                    "ERR_LAB_RESULT_NOT_FOUND")
        check_case_scope(user_id, role, case)
        # state: lab must be RECEIVED or UNLINKED
        if lab["status"] not in ("RECEIVED", "UNLINKED"):
            raise err("ERR_LAB_NOT_LINKABLE", "Lab result not in RECEIVED/UNLINKED for linking")
        # case must not be CLOSED
        if case["status"] == "CLOSED":
            raise err("ERR_CASE_NOT_LINKABLE", "Cannot link lab result to a CLOSED case")
        # condition match (before patient)
        if lab["condition_code"] != case["condition_code"]:
            raise err("ERR_LAB_CONDITION_MISMATCH", "Lab result condition_code differs from case")
        if lab["patient_reference"] != case["patient_reference"]:
            raise err("ERR_LAB_PATIENT_MISMATCH", "Lab result patient_reference differs from case")
        lab["status"] = "LINKED"
        lab["linked_case_id"] = case["id"]
        touch(lab)
        recompute_linked_positive(case)
        case["completeness_score"] = compute_completeness(case)
        touch(case)
        return success(ser_lab_result(lab), 200)


# --- Cluster reverse lookup ---
@bp.route("/surveillance/cases/<case_id>/cluster", methods=["GET"])
def case_cluster(case_id):
    _, role = get_user_context()
    require_role(role, {"JurisdictionAdmin", "CaseInvestigator", "ContactTracer", "EpiAnalyst"})
    with db.lock:
        case = get_or_404(db.cases, case_id, "ERR_CASE_NOT_FOUND")
        result = []
        cid = case.get("cluster_id")
        if cid and cid in db.clusters:
            result.append(ser_cluster(db.clusters[cid]))
        return success_list(result, 10, 0, len(result))
