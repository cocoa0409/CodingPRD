"""All API routes. Validations are applied in the priority order from PRD §3.11:
  1. auth headers present + role known
  2. role permitted (RBAC)
  3. path resource ids exist (left-to-right)
  4. FK body fields exist
  5. target resource in a valid state for the transition
  6. OCC (expected_*_version)
  7+. operation-specific business constraints
"""
from flask import request

import errors
import response
import serializers as S
import services as svc
from db import db, stamp_create, touch
from helpers import (
    get_json_body, get_pagination, paginate,
    require_string, require_int, require_bool, require_enum,
)
from middleware import get_user_context, require_roles

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
WINGS = {"ASSISTED_LIVING", "MEMORY_CARE"}
STAY_TYPES = {"STANDARD", "RESPITE"}
INCIDENT_TYPES = {"FALL", "MEDICATION_ERROR", "ELOPEMENT", "INJURY", "OTHER"}
SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}
OUTCOMES = {"GIVEN", "REFUSED", "HELD", "MISSED"}
SCOPE_SEVERITIES = {"A_C_NO_HARM", "D_F_NO_HARM", "G_I_ACTUAL_HARM", "J_L_IMMEDIATE_JEOPARDY"}
LICENSE_ACTIONS = {"PLACE_CONDITIONAL", "SUSPEND", "REINSTATE"}
DISPOSITIONS = {"TRANSFER_TO_SNF", "OTHER"}
REVIEW_DECISIONS = {"ACCEPT", "REJECT"}


# ---------------------------------------------------------------------------
# Existence helpers (raise the resource-specific not-found error)
# ---------------------------------------------------------------------------
def _get_or_404(coll, oid, err):
    obj = coll.get(oid)
    if obj is None:
        errors.raise_error(err, "Resource not found")
    return obj


def get_facility(fid):
    return _get_or_404(db.facilities, fid, errors.ERR_FACILITY_NOT_FOUND)


def get_unit(uid):
    return _get_or_404(db.units, uid, errors.ERR_UNIT_NOT_FOUND)


def get_resident(rid):
    return _get_or_404(db.residents, rid, errors.ERR_RESIDENT_NOT_FOUND)


def get_assessment(aid):
    return _get_or_404(db.assessments, aid, errors.ERR_ASSESSMENT_NOT_FOUND)


def get_care_plan(cid):
    return _get_or_404(db.care_plans, cid, errors.ERR_CARE_PLAN_NOT_FOUND)


def get_med_order(mid):
    return _get_or_404(db.medication_orders, mid, errors.ERR_MEDICATION_ORDER_NOT_FOUND)


def get_agreement(aid):
    return _get_or_404(db.move_in_agreements, aid, errors.ERR_AGREEMENT_NOT_FOUND)


def get_statement(sid):
    return _get_or_404(db.billing_statements, sid, errors.ERR_STATEMENT_NOT_FOUND)


def get_incident(iid):
    return _get_or_404(db.incident_reports, iid, errors.ERR_INCIDENT_NOT_FOUND)


def get_administration(aid):
    obj = db.administrations.get(aid)
    if obj is None:
        # No administration-specific code in the catalog; use a generic 404.
        raise errors.ApiError("ERR_ADMINISTRATION_NOT_FOUND", 404, "Administration record not found")
    return obj


def get_deficiency(did):
    return _get_or_404(db.survey_deficiencies, did, errors.ERR_DEFICIENCY_NOT_FOUND)


def _list_response(items, serializer):
    limit, offset = get_pagination()
    window, total = paginate(items, limit, offset)
    return response.success_list([serializer(o) for o in window], limit, offset, total)


def register_routes(app):
    # =======================================================================
    # FACILITY
    # =======================================================================
    @app.route("/facilities", methods=["POST"])
    def create_facility():
        _, role = get_user_context()
        require_roles(role, {"Registrar", "ComplianceOfficer"})
        body = get_json_body()
        name = require_string(body, "name")
        state_code = require_string(body, "state_code")
        license_number = require_string(body, "license_number")
        care_point_rate_cents = require_int(body, "care_point_rate_cents")
        obj = {
            "name": name,
            "state_code": state_code,
            "license_number": license_number,
            "care_point_rate_cents": care_point_rate_cents,
            "license_status": "ACTIVE",
            "bed_count": 0,
            "occupied_bed_count": 0,
            "occupancy_rate_bps": 0,
            "open_deficiency_count": 0,
        }
        stamp_create(obj)
        db.facilities[obj["id"]] = obj
        return response.success(S.facility(obj), 201)

    @app.route("/facilities", methods=["GET"])
    def list_facilities():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return _list_response(list(db.facilities.values()), S.facility)

    @app.route("/facilities/<facility_id>", methods=["GET"])
    def get_facility_route(facility_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        obj = get_facility(facility_id)
        return response.success(S.facility(obj), 200)

    @app.route("/facilities/<facility_id>/license-action", methods=["POST"])
    def license_action(facility_id):
        _, role = get_user_context()
        require_roles(role, {"ComplianceOfficer"})
        facility = get_facility(facility_id)
        body = get_json_body()
        action = require_enum(body, "action", LICENSE_ACTIONS)
        # expected_facility_version is accepted but NOT OCC-guarded (PRD §2.9)
        current = facility["license_status"]
        target = None
        if action == "PLACE_CONDITIONAL":
            if current == "ACTIVE":
                target = "CONDITIONAL"
        elif action == "SUSPEND":
            if current in ("ACTIVE", "CONDITIONAL"):
                target = "SUSPENDED"
        elif action == "REINSTATE":
            if current in ("SUSPENDED", "CONDITIONAL"):
                target = "ACTIVE"
        if target is None:
            errors.raise_error(errors.ERR_INVALID_STATE,
                               f"License action {action} not allowed from {current}")
        facility["license_status"] = target
        touch(facility)
        return response.success(S.facility(facility), 200)

    # =======================================================================
    # UNIT
    # =======================================================================
    @app.route("/facilities/<facility_id>/units", methods=["POST"])
    def create_unit(facility_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        facility = get_facility(facility_id)
        body = get_json_body()
        unit_number = require_string(body, "unit_number")
        wing = require_enum(body, "wing", WINGS)
        monthly_base_rent_cents = require_int(body, "monthly_base_rent_cents")
        # unique unit_number within facility among non-RETIRED units
        for u in db.units.values():
            if (u["facility_id"] == facility_id and u["status"] != "RETIRED"
                    and u["unit_number"] == unit_number):
                errors.raise_error(errors.ERR_DUPLICATE_UNIT_NUMBER,
                                   "unit_number already used by a non-RETIRED unit")
        obj = {
            "facility_id": facility_id,
            "unit_number": unit_number,
            "wing": wing,
            "monthly_base_rent_cents": monthly_base_rent_cents,
            "current_resident_id": None,
            "status": "AVAILABLE",
        }
        stamp_create(obj)
        db.units[obj["id"]] = obj
        svc.touch_facility_metrics(facility, occupancy=True)
        return response.success(S.unit(obj), 201)

    @app.route("/units", methods=["GET"])
    def list_units():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.units.values())
        fid = request.args.get("facility_id")
        crid = request.args.get("current_resident_id")
        wing = request.args.get("wing")
        status = request.args.get("status")
        if fid is not None:
            items = [u for u in items if u["facility_id"] == fid]
        if crid is not None:
            items = [u for u in items if u["current_resident_id"] == crid]
        if wing is not None:
            items = [u for u in items if u["wing"] == wing]
        if status is not None:
            items = [u for u in items if u["status"] == status]
        return _list_response(items, S.unit)

    @app.route("/units/<unit_id>", methods=["GET"])
    def get_unit_route(unit_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.unit(get_unit(unit_id)), 200)

    @app.route("/facilities/<facility_id>/units/<unit_id>/mark-clean", methods=["POST"])
    def mark_clean(facility_id, unit_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        facility = get_facility(facility_id)
        unit = get_unit(unit_id)
        if unit["facility_id"] != facility_id:
            errors.raise_error(errors.ERR_UNIT_NOT_FOUND, "Unit not in facility")
        if unit["status"] != "CLEANING":
            errors.raise_error(errors.ERR_INVALID_STATE, "Unit is not CLEANING")
        unit["status"] = "AVAILABLE"
        touch(unit)
        return response.success(S.unit(unit), 200)

    @app.route("/facilities/<facility_id>/units/<unit_id>/retire", methods=["POST"])
    def retire_unit(facility_id, unit_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        facility = get_facility(facility_id)
        unit = get_unit(unit_id)
        if unit["facility_id"] != facility_id:
            errors.raise_error(errors.ERR_UNIT_NOT_FOUND, "Unit not in facility")
        if unit["status"] != "AVAILABLE":
            errors.raise_error(errors.ERR_INVALID_STATE, "Unit is not AVAILABLE")
        unit["status"] = "RETIRED"
        touch(unit)
        svc.touch_facility_metrics(facility, occupancy=True)
        return response.success(S.unit(unit), 200)

    # =======================================================================
    # RESIDENT
    # =======================================================================
    @app.route("/residents", methods=["POST"])
    def create_resident():
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        body = get_json_body()
        facility_id = require_string(body, "facility_id")
        full_name = require_string(body, "full_name")
        date_of_birth = require_string(body, "date_of_birth")
        stay_type = require_enum(body, "stay_type", STAY_TYPES, required=False) or "STANDARD"
        respite_end_date = body.get("respite_end_date")
        # FK existence (priority 4)
        get_facility(facility_id)
        # respite window validation (priority 9)
        if stay_type == "RESPITE":
            if not respite_end_date or not isinstance(respite_end_date, str):
                errors.raise_error(errors.ERR_INVALID_RESPITE_WINDOW,
                                   "RESPITE stay requires a respite_end_date")
        else:  # STANDARD
            if respite_end_date is not None:
                errors.raise_error(errors.ERR_INVALID_RESPITE_WINDOW,
                                   "STANDARD stay must omit respite_end_date")
        obj = {
            "facility_id": facility_id,
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "stay_type": stay_type,
            "respite_end_date": respite_end_date if stay_type == "RESPITE" else None,
            "current_care_level": None,
            "current_care_points": 0,
            "assigned_unit_id": None,
            "open_balance_cents": 0,
            "status": "PROSPECT",
            "discharge_disposition": None,
        }
        stamp_create(obj)
        db.residents[obj["id"]] = obj
        return response.success(S.resident(obj), 201)

    @app.route("/residents", methods=["GET"])
    def list_residents():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.residents.values())
        fid = request.args.get("facility_id")
        uid = request.args.get("assigned_unit_id")
        status = request.args.get("status")
        if fid is not None:
            items = [r for r in items if r["facility_id"] == fid]
        if uid is not None:
            items = [r for r in items if r["assigned_unit_id"] == uid]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        return _list_response(items, S.resident)

    @app.route("/residents/<resident_id>", methods=["GET"])
    def get_resident_route(resident_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.resident(get_resident(resident_id)), 200)

    @app.route("/residents/<resident_id>/admit", methods=["POST"])
    def admit_resident(resident_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        resident = get_resident(resident_id)
        if resident["status"] != "ASSESSED":
            errors.raise_error(errors.ERR_INVALID_STATE, "Resident is not ASSESSED")
        facility = get_facility(resident["facility_id"])
        # ACTIVE agreement bound to a RESERVED unit held for this resident
        agreement = svc.active_agreement_for_resident(resident_id)
        unit = None
        if agreement is not None:
            unit = db.units.get(agreement["unit_id"])
        valid_binding = (
            agreement is not None and unit is not None
            and unit["status"] == "RESERVED"
            and unit["current_resident_id"] == resident_id
        )
        if not valid_binding:
            errors.raise_error(errors.ERR_INVALID_STATE,
                               "No ACTIVE agreement with a RESERVED bed held for this resident")
        # license check (priority 13)
        if facility["license_status"] == "SUSPENDED":
            errors.raise_error(errors.ERR_LICENSE_SUSPENDED, "Facility license is SUSPENDED")
        # transitions
        resident["status"] = "ADMITTED"
        resident["assigned_unit_id"] = agreement["unit_id"]
        touch(resident)
        unit["status"] = "OCCUPIED"
        unit["current_resident_id"] = resident_id
        touch(unit)
        svc.touch_facility_metrics(facility, occupancy=True)
        return response.success(S.resident(resident), 200)

    @app.route("/residents/<resident_id>/initiate-discharge", methods=["POST"])
    def initiate_discharge(resident_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        resident = get_resident(resident_id)
        if resident["status"] != "ADMITTED":
            errors.raise_error(errors.ERR_INVALID_STATE, "Resident is not ADMITTED")
        if resident["open_balance_cents"] != 0:
            errors.raise_error(errors.ERR_OUTSTANDING_BALANCE, "Resident has an outstanding balance")
        resident["status"] = "DISCHARGE_PENDING"
        touch(resident)
        return response.success(S.resident(resident), 200)

    @app.route("/residents/<resident_id>/rescind-discharge", methods=["POST"])
    def rescind_discharge(resident_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        resident = get_resident(resident_id)
        if resident["status"] != "DISCHARGE_PENDING":
            errors.raise_error(errors.ERR_INVALID_STATE, "Resident is not DISCHARGE_PENDING")
        resident["status"] = "ADMITTED"
        touch(resident)
        return response.success(S.resident(resident), 200)

    @app.route("/residents/<resident_id>/finalize-discharge", methods=["POST"])
    def finalize_discharge(resident_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        resident = get_resident(resident_id)
        body = get_json_body()
        disposition = require_enum(body, "disposition", DISPOSITIONS)
        if resident["status"] != "DISCHARGE_PENDING":
            errors.raise_error(errors.ERR_INVALID_STATE, "Resident is not DISCHARGE_PENDING")
        # all medication orders DISCONTINUED (priority 19)
        for m in db.medication_orders.values():
            if m["resident_id"] == resident_id and m["status"] != "DISCONTINUED":
                errors.raise_error(errors.ERR_ACTIVE_MED_ORDERS, "Resident has active medication orders")
        # cascade
        unit = None
        if resident.get("assigned_unit_id"):
            unit = db.units.get(resident["assigned_unit_id"])
        resident["status"] = "DISCHARGED"
        resident["discharge_disposition"] = disposition
        resident["assigned_unit_id"] = None
        touch(resident)
        facility = db.facilities.get(resident["facility_id"])
        if unit is not None:
            unit["status"] = "CLEANING"
            unit["current_resident_id"] = None
            touch(unit)
        if facility is not None:
            svc.touch_facility_metrics(facility, occupancy=True)
        # ACTIVE agreement -> TERMINATED
        for a in db.move_in_agreements.values():
            if a["resident_id"] == resident_id and a["status"] == "ACTIVE":
                a["status"] = "TERMINATED"
                touch(a)
        # ACTIVE/DRAFT care plans -> ARCHIVED
        for c in db.care_plans.values():
            if c["resident_id"] == resident_id and c["status"] in ("ACTIVE", "DRAFT"):
                c["status"] = "ARCHIVED"
                touch(c)
        return response.success(S.resident(resident), 200)

    # =======================================================================
    # ASSESSMENT
    # =======================================================================
    @app.route("/assessments", methods=["POST"])
    def create_assessment():
        _, role = get_user_context()
        require_roles(role, {"ClinicalDirector"})
        body = get_json_body()
        resident_id = require_string(body, "resident_id")
        # required ADL + cognition fields must be present and integer typed
        adl_bathing = require_int(body, "adl_bathing")
        adl_dressing = require_int(body, "adl_dressing")
        adl_toileting = require_int(body, "adl_toileting")
        adl_transferring = require_int(body, "adl_transferring")
        adl_eating = require_int(body, "adl_eating")
        cognition_score = require_int(body, "cognition_score")
        behavior_flags = require_int(body, "behavior_flags", required=False)
        if behavior_flags is None:
            behavior_flags = 0
        # FK existence (priority 4)
        get_resident(resident_id)
        # business range validation (priority 7)
        for v in (adl_bathing, adl_dressing, adl_toileting, adl_transferring, adl_eating):
            if v < 0 or v > 4:
                errors.raise_error(errors.ERR_INVALID_ASSESSMENT_INPUT, "ADL score out of 0..4")
        if cognition_score < 0 or cognition_score > 10:
            errors.raise_error(errors.ERR_INVALID_ASSESSMENT_INPUT, "cognition_score out of 0..10")
        if behavior_flags < 0:
            errors.raise_error(errors.ERR_INVALID_ASSESSMENT_INPUT, "behavior_flags must be >= 0")
        obj = {
            "resident_id": resident_id,
            "adl_bathing": adl_bathing,
            "adl_dressing": adl_dressing,
            "adl_toileting": adl_toileting,
            "adl_transferring": adl_transferring,
            "adl_eating": adl_eating,
            "cognition_score": cognition_score,
            "behavior_flags": behavior_flags,
            "status": "DRAFT",
        }
        obj["care_points_total"] = svc.compute_care_points(obj)
        obj["care_level"] = svc.compute_care_level(obj["care_points_total"], cognition_score)
        stamp_create(obj)
        db.assessments[obj["id"]] = obj
        return response.success(S.assessment(obj), 201)

    @app.route("/assessments", methods=["GET"])
    def list_assessments():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.assessments.values())
        rid = request.args.get("resident_id")
        status = request.args.get("status")
        if rid is not None:
            items = [a for a in items if a["resident_id"] == rid]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        return _list_response(items, S.assessment)

    @app.route("/assessments/<assessment_id>", methods=["GET"])
    def get_assessment_route(assessment_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.assessment(get_assessment(assessment_id)), 200)

    @app.route("/assessments/<assessment_id>/finalize", methods=["POST"])
    def finalize_assessment(assessment_id):
        _, role = get_user_context()
        require_roles(role, {"ClinicalDirector"})
        assessment = get_assessment(assessment_id)
        body = get_json_body()
        expected_resident_version = require_int(body, "expected_resident_version")
        resident = get_resident(assessment["resident_id"])
        # state check (priority 5): DRAFT and resident not DISCHARGED
        if assessment["status"] != "DRAFT" or resident["status"] == "DISCHARGED":
            errors.raise_error(errors.ERR_INVALID_STATE,
                               "Assessment not DRAFT or resident DISCHARGED")
        # OCC check (priority 6)
        if expected_resident_version != resident["version"]:
            errors.raise_error(errors.ERR_STALE_VERSION, "Resident version is stale")
        # freeze points/level (recompute once)
        assessment["care_points_total"] = svc.compute_care_points(assessment)
        assessment["care_level"] = svc.compute_care_level(
            assessment["care_points_total"], assessment["cognition_score"])
        assessment["status"] = "FINALIZED"
        touch(assessment)
        # supersede prior FINALIZED assessments for the same resident
        for other in db.assessments.values():
            if (other["id"] != assessment_id
                    and other["resident_id"] == resident["id"]
                    and other["status"] == "FINALIZED"):
                other["status"] = "SUPERSEDED"
                touch(other)
        # copy to resident + advance status
        resident["current_care_level"] = assessment["care_level"]
        resident["current_care_points"] = assessment["care_points_total"]
        if resident["status"] == "PROSPECT":
            resident["status"] = "ASSESSED"
        elif resident["status"] == "ADMITTED":
            resident["status"] = "ASSESSED"
        touch(resident)
        return response.success(S.assessment(assessment), 200)

    # =======================================================================
    # CARE PLAN
    # =======================================================================
    @app.route("/care-plans", methods=["POST"])
    def create_care_plan():
        _, role = get_user_context()
        require_roles(role, {"ClinicalDirector"})
        body = get_json_body()
        resident_id = require_string(body, "resident_id")
        source_assessment_id = require_string(body, "source_assessment_id")
        if "adl_support_items" not in body or body["adl_support_items"] is None:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field: adl_support_items")
        adl_support_items = body["adl_support_items"]
        if not isinstance(adl_support_items, list):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "adl_support_items must be an array")
        supersedes_care_plan_id = body.get("supersedes_care_plan_id")
        if supersedes_care_plan_id is not None and not isinstance(supersedes_care_plan_id, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "supersedes_care_plan_id must be a string")
        # FK existence (priority 4)
        get_resident(resident_id)
        get_assessment(source_assessment_id)
        if supersedes_care_plan_id is not None:
            get_care_plan(supersedes_care_plan_id)
        obj = {
            "resident_id": resident_id,
            "source_assessment_id": source_assessment_id,
            "supersedes_care_plan_id": supersedes_care_plan_id,
            "adl_support_items": adl_support_items,
            "status": "DRAFT",
        }
        stamp_create(obj)
        db.care_plans[obj["id"]] = obj
        return response.success(S.care_plan(obj), 201)

    @app.route("/care-plans", methods=["GET"])
    def list_care_plans():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.care_plans.values())
        rid = request.args.get("resident_id")
        said = request.args.get("source_assessment_id")
        scid = request.args.get("supersedes_care_plan_id")
        status = request.args.get("status")
        if rid is not None:
            items = [c for c in items if c["resident_id"] == rid]
        if said is not None:
            items = [c for c in items if c["source_assessment_id"] == said]
        if scid is not None:
            items = [c for c in items if c["supersedes_care_plan_id"] == scid]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        return _list_response(items, S.care_plan)

    @app.route("/care-plans/<care_plan_id>", methods=["GET"])
    def get_care_plan_route(care_plan_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.care_plan(get_care_plan(care_plan_id)), 200)

    @app.route("/care-plans/<care_plan_id>/activate", methods=["POST"])
    def activate_care_plan(care_plan_id):
        _, role = get_user_context()
        require_roles(role, {"ClinicalDirector"})
        plan = get_care_plan(care_plan_id)
        # state precondition: DRAFT, source FINALIZED, resident in {ASSESSED, ADMITTED}
        if plan["status"] != "DRAFT":
            errors.raise_error(errors.ERR_INVALID_STATE, "Care plan is not DRAFT")
        source = db.assessments.get(plan["source_assessment_id"])
        if source is None or source["status"] != "FINALIZED":
            errors.raise_error(errors.ERR_INVALID_STATE, "Source assessment is not FINALIZED")
        resident = db.residents.get(plan["resident_id"])
        if resident is None or resident["status"] not in ("ASSESSED", "ADMITTED"):
            errors.raise_error(errors.ERR_INVALID_STATE, "Resident not in ASSESSED/ADMITTED")
        plan["status"] = "ACTIVE"
        touch(plan)
        if plan["supersedes_care_plan_id"]:
            prior = db.care_plans.get(plan["supersedes_care_plan_id"])
            if prior is not None and prior["status"] == "ACTIVE":
                prior["status"] = "SUPERSEDED"
                touch(prior)
        return response.success(S.care_plan(plan), 200)

    # =======================================================================
    # MEDICATION ORDER + eMAR
    # =======================================================================
    @app.route("/medication-orders", methods=["POST"])
    def create_med_order():
        _, role = get_user_context()
        require_roles(role, {"Nurse", "ClinicalDirector"})
        body = get_json_body()
        resident_id = require_string(body, "resident_id")
        drug_name = require_string(body, "drug_name")
        dose = require_string(body, "dose")
        if "schedule_times" not in body or body["schedule_times"] is None:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field: schedule_times")
        schedule_times = body["schedule_times"]
        if not isinstance(schedule_times, list) or len(schedule_times) == 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "schedule_times must be a non-empty array")
        for t in schedule_times:
            if not isinstance(t, str):
                errors.raise_error(errors.ERR_INVALID_REQUEST, "schedule_times entries must be strings")
        is_controlled = require_bool(body, "is_controlled", default=False)
        get_resident(resident_id)
        obj = {
            "resident_id": resident_id,
            "drug_name": drug_name,
            "dose": dose,
            "schedule_times": schedule_times,
            "is_controlled": is_controlled,
            "status": "ACTIVE",
        }
        stamp_create(obj)
        db.medication_orders[obj["id"]] = obj
        return response.success(S.medication_order(obj), 201)

    @app.route("/medication-orders", methods=["GET"])
    def list_med_orders():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.medication_orders.values())
        rid = request.args.get("resident_id")
        status = request.args.get("status")
        if rid is not None:
            items = [m for m in items if m["resident_id"] == rid]
        if status is not None:
            items = [m for m in items if m["status"] == status]
        return _list_response(items, S.medication_order)

    @app.route("/medication-orders/<med_order_id>", methods=["GET"])
    def get_med_order_route(med_order_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.medication_order(get_med_order(med_order_id)), 200)

    @app.route("/medication-orders/<med_order_id>/discontinue", methods=["POST"])
    def discontinue_med_order(med_order_id):
        _, role = get_user_context()
        require_roles(role, {"Nurse", "ClinicalDirector"})
        order = get_med_order(med_order_id)
        if order["status"] != "ACTIVE":
            errors.raise_error(errors.ERR_INVALID_STATE, "Order is not ACTIVE")
        order["status"] = "DISCONTINUED"
        touch(order)
        return response.success(S.medication_order(order), 200)

    @app.route("/medication-orders/<med_order_id>/administrations", methods=["POST"])
    def record_administration(med_order_id):
        user_id, role = get_user_context()
        require_roles(role, {"Nurse"})
        order = get_med_order(med_order_id)
        body = get_json_body()
        scheduled_time = require_string(body, "scheduled_time")
        outcome = require_enum(body, "outcome", OUTCOMES)
        witness_user_id = body.get("witness_user_id")
        if witness_user_id is not None and not isinstance(witness_user_id, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "witness_user_id must be a string")
        # witness requirement (priority 14) BEFORE slot validity (priority 15)
        if order["is_controlled"] and outcome == "GIVEN":
            if not witness_user_id or witness_user_id == user_id:
                errors.raise_error(errors.ERR_WITNESS_REQUIRED,
                                   "Controlled GIVEN requires a distinct witness_user_id")
        # slot membership (priority 15)
        if scheduled_time not in order["schedule_times"]:
            errors.raise_error(errors.ERR_INVALID_MED_SLOT, "scheduled_time not in order schedule_times")
        obj = {
            "medication_order_id": med_order_id,
            "resident_id": order["resident_id"],
            "scheduled_time": scheduled_time,
            "outcome": outcome,
            "witness_user_id": witness_user_id,
            "administered_by_user_id": user_id,
        }
        stamp_create(obj, common_fields=False)
        db.administrations[obj["id"]] = obj
        return response.success(S.administration(obj), 201)

    @app.route("/administrations", methods=["GET"])
    def list_administrations():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.administrations.values())
        rid = request.args.get("resident_id")
        moid = request.args.get("medication_order_id")
        if rid is not None:
            items = [a for a in items if a["resident_id"] == rid]
        if moid is not None:
            items = [a for a in items if a["medication_order_id"] == moid]
        return _list_response(items, S.administration)

    @app.route("/administrations/<administration_id>", methods=["GET"])
    def get_administration_route(administration_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.administration(get_administration(administration_id)), 200)

    # =======================================================================
    # MOVE-IN AGREEMENT
    # =======================================================================
    @app.route("/move-in-agreements", methods=["POST"])
    def create_agreement():
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        body = get_json_body()
        resident_id = require_string(body, "resident_id")
        unit_id = require_string(body, "unit_id")
        move_in_date = require_string(body, "move_in_date")
        community_fee_cents = require_int(body, "community_fee_cents", required=False)
        if community_fee_cents is None:
            community_fee_cents = 0
        # FK existence (priority 4)
        get_resident(resident_id)
        unit = get_unit(unit_id)
        # at most one DRAFT/ACTIVE agreement (priority 10)
        if svc.open_agreement_for_resident(resident_id) is not None:
            errors.raise_error(errors.ERR_AGREEMENT_ALREADY_OPEN,
                               "Resident already has a DRAFT or ACTIVE agreement")
        obj = {
            "resident_id": resident_id,
            "unit_id": unit_id,
            "move_in_date": move_in_date,
            "monthly_base_rent_cents": unit["monthly_base_rent_cents"],
            "community_fee_cents": community_fee_cents,
            "status": "DRAFT",
        }
        stamp_create(obj)
        db.move_in_agreements[obj["id"]] = obj
        return response.success(S.move_in_agreement(obj), 201)

    @app.route("/move-in-agreements", methods=["GET"])
    def list_agreements():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.move_in_agreements.values())
        rid = request.args.get("resident_id")
        uid = request.args.get("unit_id")
        status = request.args.get("status")
        if rid is not None:
            items = [a for a in items if a["resident_id"] == rid]
        if uid is not None:
            items = [a for a in items if a["unit_id"] == uid]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        return _list_response(items, S.move_in_agreement)

    @app.route("/move-in-agreements/<agreement_id>", methods=["GET"])
    def get_agreement_route(agreement_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.move_in_agreement(get_agreement(agreement_id)), 200)

    @app.route("/move-in-agreements/<agreement_id>/activate", methods=["POST"])
    def activate_agreement(agreement_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        agreement = get_agreement(agreement_id)
        body = get_json_body()
        expected_unit_version = require_int(body, "expected_unit_version")
        # state check (priority 5)
        if agreement["status"] != "DRAFT":
            errors.raise_error(errors.ERR_INVALID_STATE, "Agreement is not DRAFT")
        unit = db.units.get(agreement["unit_id"])
        if unit is None:
            errors.raise_error(errors.ERR_UNIT_NOT_FOUND, "Bound unit no longer exists")
        # OCC check (priority 6)
        if expected_unit_version != unit["version"]:
            errors.raise_error(errors.ERR_STALE_VERSION, "Unit version is stale")
        # bed availability (priority 11)
        if unit["status"] != "AVAILABLE":
            errors.raise_error(errors.ERR_BED_NOT_AVAILABLE, "Unit is not AVAILABLE")
        # wing match (priority 12)
        resident = db.residents.get(agreement["resident_id"])
        if (resident is not None and resident.get("current_care_level") == "MEMORY_CARE"
                and unit["wing"] != "MEMORY_CARE"):
            errors.raise_error(errors.ERR_WING_MISMATCH,
                               "MEMORY_CARE resident requires a MEMORY_CARE wing unit")
        # transitions
        agreement["status"] = "ACTIVE"
        touch(agreement)
        unit["status"] = "RESERVED"
        unit["current_resident_id"] = agreement["resident_id"]
        touch(unit)
        return response.success(S.move_in_agreement(agreement), 200)

    @app.route("/move-in-agreements/<agreement_id>/cancel", methods=["POST"])
    def cancel_agreement(agreement_id):
        _, role = get_user_context()
        require_roles(role, {"Registrar"})
        agreement = get_agreement(agreement_id)
        # PRD §3.5: "An agreement moves through DRAFT -> ACTIVE -> TERMINATED, or
        # DRAFT -> CANCELLED." Cancel is therefore defined only from DRAFT;
        # PRD §2.8: "an attempt to drive a transition from any other state is
        # rejected with ERR_INVALID_STATE." So cancelling an ACTIVE agreement is
        # rejected. (A DRAFT agreement holds no bed, so the "releases the bed"
        # clause below is a no-op for the only legal cancel state, but is kept
        # defensively in case a DRAFT agreement is ever found holding a unit.)
        if agreement["status"] != "DRAFT":
            errors.raise_error(errors.ERR_INVALID_STATE, "Agreement is not DRAFT")
        agreement["status"] = "CANCELLED"
        touch(agreement)
        unit = db.units.get(agreement["unit_id"])
        if unit is not None and unit["status"] == "RESERVED" \
                and unit["current_resident_id"] == agreement["resident_id"]:
            unit["status"] = "AVAILABLE"
            unit["current_resident_id"] = None
            touch(unit)
        return response.success(S.move_in_agreement(agreement), 200)

    # =======================================================================
    # BILLING STATEMENT
    # =======================================================================
    @app.route("/billing-statements", methods=["POST"])
    def create_statement():
        _, role = get_user_context()
        require_roles(role, {"BillingClerk"})
        body = get_json_body()
        resident_id = require_string(body, "resident_id")
        period_year = require_int(body, "period_year")
        period_month = require_int(body, "period_month")
        is_first_statement = require_bool(body, "is_first_statement", default=False)
        if period_month < 1 or period_month > 12:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "period_month must be 1..12")
        # FK existence (priority 4)
        get_resident(resident_id)
        # duplicate non-VOID period (priority 16)
        for s in db.billing_statements.values():
            if (s["resident_id"] == resident_id
                    and s["period_year"] == period_year
                    and s["period_month"] == period_month
                    and s["status"] != "VOID"):
                errors.raise_error(errors.ERR_DUPLICATE_STATEMENT_PERIOD,
                                   "Non-VOID statement already exists for this period")
        obj = {
            "resident_id": resident_id,
            "period_year": period_year,
            "period_month": period_month,
            "is_first_statement": is_first_statement,
            "rent_charge_cents": 0,
            "care_points_charge_cents": 0,
            "community_fee_charge_cents": 0,
            "total_charge_cents": 0,
            "paid_cents": 0,
            "status": "DRAFT",
        }
        stamp_create(obj)
        db.billing_statements[obj["id"]] = obj
        return response.success(S.billing_statement(obj), 201)

    @app.route("/billing-statements", methods=["GET"])
    def list_statements():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.billing_statements.values())
        rid = request.args.get("resident_id")
        status = request.args.get("status")
        if rid is not None:
            items = [s for s in items if s["resident_id"] == rid]
        if status is not None:
            items = [s for s in items if s["status"] == status]
        return _list_response(items, S.billing_statement)

    @app.route("/billing-statements/<statement_id>", methods=["GET"])
    def get_statement_route(statement_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.billing_statement(get_statement(statement_id)), 200)

    @app.route("/billing-statements/<statement_id>/issue", methods=["POST"])
    def issue_statement(statement_id):
        _, role = get_user_context()
        require_roles(role, {"BillingClerk"})
        statement = get_statement(statement_id)
        if statement["status"] != "DRAFT":
            errors.raise_error(errors.ERR_INVALID_STATE, "Statement is not DRAFT")
        resident = get_resident(statement["resident_id"])
        agreement = svc.active_agreement_for_resident(resident["id"])
        if agreement is None:
            errors.raise_error(errors.ERR_INVALID_STATE, "Resident has no ACTIVE move-in agreement")
        facility = db.facilities.get(resident["facility_id"])
        svc.compute_monthly_charge(statement, resident, agreement, facility)
        statement["status"] = "ISSUED"
        touch(statement)
        svc.recompute_resident_balance(resident)
        return response.success(S.billing_statement(statement), 200)

    @app.route("/billing-statements/<statement_id>/payments", methods=["POST"])
    def record_payment(statement_id):
        _, role = get_user_context()
        require_roles(role, {"BillingClerk"})
        statement = get_statement(statement_id)
        body = get_json_body()
        amount_cents = require_int(body, "amount_cents")
        # state check (priority 5)
        if statement["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            errors.raise_error(errors.ERR_INVALID_STATE, "Statement is not payable")
        remaining = statement["total_charge_cents"] - statement["paid_cents"]
        # fiscal check (priority 17)
        if amount_cents <= 0 or amount_cents > remaining:
            errors.raise_error(errors.ERR_PAYMENT_EXCEEDS_BALANCE,
                               "Payment must be > 0 and <= remaining balance")
        if amount_cents == remaining:
            statement["paid_cents"] = statement["total_charge_cents"]
            statement["status"] = "PAID"
        else:
            statement["paid_cents"] += amount_cents
            statement["status"] = "PARTIALLY_PAID"
        touch(statement)
        resident = db.residents.get(statement["resident_id"])
        if resident is not None:
            svc.recompute_resident_balance(resident)
        return response.success(S.billing_statement(statement), 200)

    @app.route("/billing-statements/<statement_id>/void", methods=["POST"])
    def void_statement(statement_id):
        _, role = get_user_context()
        require_roles(role, {"BillingClerk"})
        statement = get_statement(statement_id)
        if statement["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            errors.raise_error(errors.ERR_INVALID_STATE, "Statement is not voidable")
        statement["status"] = "VOID"
        touch(statement)
        resident = db.residents.get(statement["resident_id"])
        if resident is not None:
            svc.recompute_resident_balance(resident)
        return response.success(S.billing_statement(statement), 200)

    # =======================================================================
    # INCIDENT REPORT
    # =======================================================================
    @app.route("/incident-reports", methods=["POST"])
    def create_incident():
        _, role = get_user_context()
        require_roles(role, {"Nurse"})
        body = get_json_body()
        resident_id = require_string(body, "resident_id")
        incident_type = require_enum(body, "incident_type", INCIDENT_TYPES)
        occurred_at = require_string(body, "occurred_at")
        severity = require_enum(body, "severity", SEVERITIES)
        get_resident(resident_id)
        requires_state_report = (severity == "SEVERE" or incident_type == "ELOPEMENT")
        obj = {
            "resident_id": resident_id,
            "incident_type": incident_type,
            "occurred_at": occurred_at,
            "severity": severity,
            "requires_state_report": requires_state_report,
            "linked_deficiency_id": None,
            "status": "REPORTED",
        }
        stamp_create(obj)
        db.incident_reports[obj["id"]] = obj
        return response.success(S.incident_report(obj), 201)

    @app.route("/incident-reports", methods=["GET"])
    def list_incidents():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.incident_reports.values())
        rid = request.args.get("resident_id")
        ldid = request.args.get("linked_deficiency_id")
        status = request.args.get("status")
        if rid is not None:
            items = [i for i in items if i["resident_id"] == rid]
        if ldid is not None:
            items = [i for i in items if i["linked_deficiency_id"] == ldid]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        return _list_response(items, S.incident_report)

    @app.route("/incident-reports/<incident_id>", methods=["GET"])
    def get_incident_route(incident_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.incident_report(get_incident(incident_id)), 200)

    @app.route("/incident-reports/<incident_id>/investigate", methods=["POST"])
    def investigate_incident(incident_id):
        _, role = get_user_context()
        require_roles(role, {"Nurse"})
        incident = get_incident(incident_id)
        if incident["status"] != "REPORTED":
            errors.raise_error(errors.ERR_INVALID_STATE, "Incident is not REPORTED")
        incident["status"] = "UNDER_INVESTIGATION"
        touch(incident)
        return response.success(S.incident_report(incident), 200)

    @app.route("/incident-reports/<incident_id>/resolve", methods=["POST"])
    def resolve_incident(incident_id):
        _, role = get_user_context()
        require_roles(role, {"Nurse"})
        incident = get_incident(incident_id)
        if incident["status"] != "UNDER_INVESTIGATION":
            errors.raise_error(errors.ERR_INVALID_STATE, "Incident is not UNDER_INVESTIGATION")
        incident["status"] = "RESOLVED"
        touch(incident)
        return response.success(S.incident_report(incident), 200)

    @app.route("/incident-reports/<incident_id>/escalate", methods=["POST"])
    def escalate_incident(incident_id):
        _, role = get_user_context()
        require_roles(role, {"ComplianceOfficer"})
        incident = get_incident(incident_id)
        body = get_json_body()
        scope_severity = require_enum(body, "scope_severity", SCOPE_SEVERITIES)
        tag_code = require_string(body, "tag_code")
        cited_at = require_string(body, "cited_at")
        # state check (priority 5)
        if incident["status"] != "UNDER_INVESTIGATION":
            errors.raise_error(errors.ERR_INVALID_STATE, "Incident is not UNDER_INVESTIGATION")
        # state-reportable requirement (priority 20)
        if not incident["requires_state_report"]:
            errors.raise_error(errors.ERR_NOT_STATE_REPORTABLE, "Incident is not state-reportable")
        resident = db.residents.get(incident["resident_id"])
        facility = db.facilities.get(resident["facility_id"]) if resident else None
        # spawn deficiency
        deficiency = {
            "facility_id": facility["id"] if facility else None,
            "tag_code": tag_code,
            "scope_severity": scope_severity,
            "cited_at": cited_at,
            "poc_due_date": svc.compute_poc_due_date(cited_at, scope_severity),
            "poc_text": None,
            "status": "CITED",
        }
        stamp_create(deficiency)
        db.survey_deficiencies[deficiency["id"]] = deficiency
        incident["status"] = "ESCALATED"
        incident["linked_deficiency_id"] = deficiency["id"]
        touch(incident)
        if facility is not None:
            svc.touch_facility_metrics(facility, deficiencies=True)
        return response.success(S.incident_report(incident), 200)

    # =======================================================================
    # SURVEY DEFICIENCY
    # =======================================================================
    @app.route("/facilities/<facility_id>/deficiencies", methods=["POST"])
    def cite_deficiency(facility_id):
        _, role = get_user_context()
        require_roles(role, {"ComplianceOfficer"})
        facility = get_facility(facility_id)
        body = get_json_body()
        tag_code = require_string(body, "tag_code")
        scope_severity = require_enum(body, "scope_severity", SCOPE_SEVERITIES)
        cited_at = require_string(body, "cited_at")
        obj = {
            "facility_id": facility_id,
            "tag_code": tag_code,
            "scope_severity": scope_severity,
            "cited_at": cited_at,
            "poc_due_date": svc.compute_poc_due_date(cited_at, scope_severity),
            "poc_text": None,
            "status": "CITED",
        }
        stamp_create(obj)
        db.survey_deficiencies[obj["id"]] = obj
        svc.touch_facility_metrics(facility, deficiencies=True)
        return response.success(S.survey_deficiency(obj), 201)

    @app.route("/deficiencies", methods=["GET"])
    def list_deficiencies():
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        items = list(db.survey_deficiencies.values())
        fid = request.args.get("facility_id")
        status = request.args.get("status")
        if fid is not None:
            items = [d for d in items if d["facility_id"] == fid]
        if status is not None:
            items = [d for d in items if d["status"] == status]
        return _list_response(items, S.survey_deficiency)

    @app.route("/deficiencies/<deficiency_id>", methods=["GET"])
    def get_deficiency_route(deficiency_id):
        _, role = get_user_context()
        require_roles(role, {"Staff"})
        return response.success(S.survey_deficiency(get_deficiency(deficiency_id)), 200)

    @app.route("/facilities/<facility_id>/deficiencies/<deficiency_id>/submit-poc", methods=["POST"])
    def submit_poc(facility_id, deficiency_id):
        _, role = get_user_context()
        require_roles(role, {"ComplianceOfficer"})
        get_facility(facility_id)
        deficiency = get_deficiency(deficiency_id)
        if deficiency["facility_id"] != facility_id:
            errors.raise_error(errors.ERR_DEFICIENCY_NOT_FOUND, "Deficiency not in facility")
        body = get_json_body()
        poc_text = require_string(body, "poc_text")
        if deficiency["status"] not in ("CITED", "POC_REJECTED"):
            errors.raise_error(errors.ERR_INVALID_STATE, "Deficiency not in a submittable state")
        deficiency["status"] = "POC_SUBMITTED"
        deficiency["poc_text"] = poc_text
        touch(deficiency)
        return response.success(S.survey_deficiency(deficiency), 200)

    @app.route("/facilities/<facility_id>/deficiencies/<deficiency_id>/review-poc", methods=["POST"])
    def review_poc(facility_id, deficiency_id):
        _, role = get_user_context()
        require_roles(role, {"ComplianceOfficer"})
        get_facility(facility_id)
        deficiency = get_deficiency(deficiency_id)
        if deficiency["facility_id"] != facility_id:
            errors.raise_error(errors.ERR_DEFICIENCY_NOT_FOUND, "Deficiency not in facility")
        body = get_json_body()
        decision = require_enum(body, "decision", REVIEW_DECISIONS)
        if deficiency["status"] != "POC_SUBMITTED":
            errors.raise_error(errors.ERR_INVALID_STATE, "Deficiency is not POC_SUBMITTED")
        deficiency["status"] = "POC_ACCEPTED" if decision == "ACCEPT" else "POC_REJECTED"
        touch(deficiency)
        return response.success(S.survey_deficiency(deficiency), 200)

    @app.route("/facilities/<facility_id>/deficiencies/<deficiency_id>/mark-corrected", methods=["POST"])
    def mark_corrected(facility_id, deficiency_id):
        _, role = get_user_context()
        require_roles(role, {"ComplianceOfficer"})
        facility = get_facility(facility_id)
        deficiency = get_deficiency(deficiency_id)
        if deficiency["facility_id"] != facility_id:
            errors.raise_error(errors.ERR_DEFICIENCY_NOT_FOUND, "Deficiency not in facility")
        if deficiency["status"] != "POC_ACCEPTED":
            errors.raise_error(errors.ERR_INVALID_STATE, "Deficiency is not POC_ACCEPTED")
        deficiency["status"] = "CORRECTED"
        touch(deficiency)
        svc.touch_facility_metrics(facility, deficiencies=True)
        return response.success(S.survey_deficiency(deficiency), 200)
