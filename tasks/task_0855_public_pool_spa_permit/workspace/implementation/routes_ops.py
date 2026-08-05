"""Water chemistry, closure orders, staffing, compliance artifacts, complaints."""

from flask import g

import constants as C
import domain
from auth import authenticate, authorize, own_or_403, require_action_role
from clock import LOGICAL_CLOCK, add_days, minutes_between
from errors import ApiError
from helpers import facility_or_404, get_or_404, matches, paged_list
from response import object_response
from serializers import (complaint_json, compliance_artifact_json,
                         closure_order_json, staff_assignment_json,
                         water_reading_json)
from store import DB, base_record, ordered, touch
from validation import (bad, json_body, opt_date, opt_enum, opt_int, opt_number,
                        opt_string, qs, req_date, req_datetime, req_enum,
                        req_int, req_number, req_string)

REOPEN_DECISIONS = ("APPROVE", "DENY", "VOID")
REOPEN_DECISION_ROLES = {
    "APPROVE": ("Inspector", "HealthAuthorityAdmin"),
    "DENY": ("Inspector", "HealthAuthorityAdmin"),
    "VOID": ("HealthAuthorityAdmin",),
}
COMPLAINT_ACTIONS = ("TRIAGE", "START_INVESTIGATION", "SUBSTANTIATE",
                     "UNSUBSTANTIATE", "CLOSE")
COMPLAINT_ACTION_ROLES = {
    "TRIAGE": ("Inspector",),
    "START_INVESTIGATION": ("Inspector",),
    "SUBSTANTIATE": ("Inspector",),
    "UNSUBSTANTIATE": ("Inspector",),
    "CLOSE": ("HealthAuthorityAdmin",),
}


def _invalid_closure_state():
    raise ApiError("ERR_INVALID_CLOSURE_STATE",
                   "The closure order is not in a state that permits this action.")


def _invalid_complaint_state():
    raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                   "The complaint is not in a state that permits this action.")


def register(app):

    # ------------------------------------------------------------------
    # water chemistry readings
    # ------------------------------------------------------------------
    @app.route("/facilities/<facility_id>/water-readings", methods=["POST"])
    def create_water_reading(facility_id):
        authenticate()
        authorize("Operator", "Inspector")
        facility = facility_or_404(facility_id)
        body = json_body()
        sampled_at = req_datetime(body, "sampled_at")
        source = req_enum(body, "source", C.READING_SOURCES)
        free_chlorine_ppm = req_number(body, "free_chlorine_ppm", minimum=0)
        combined_chloramine_ppm = req_number(body, "combined_chloramine_ppm", minimum=0)
        ph = req_number(body, "ph", minimum=0, maximum=14)
        water_temp_f = req_number(body, "water_temp_f", minimum=0)
        cyanuric_acid_ppm = opt_number(body, "cyanuric_acid_ppm", default=0, minimum=0)
        if sampled_at > LOGICAL_CLOCK.now():
            bad("sampled_at must not be later than the logical clock.")

        own_or_403(facility["operator_id"])

        status, breaches = domain.classify_reading(
            facility, free_chlorine_ppm, combined_chloramine_ppm, ph,
            cyanuric_acid_ppm, water_temp_f)

        rec = base_record(versioned=False)
        rec.update({
            "facility_id": facility["id"],
            "sampled_at": sampled_at,
            "source": source,
            "free_chlorine_ppm": free_chlorine_ppm,
            "combined_chloramine_ppm": combined_chloramine_ppm,
            "ph": ph,
            "cyanuric_acid_ppm": cyanuric_acid_ppm,
            "water_temp_f": water_temp_f,
            "compliance_status": status,
            "out_of_range_parameters": breaches,
            "triggered_closure_order_id": None,
        })
        DB.water_readings[rec["id"]] = rec

        if status == "IMMINENT_HAZARD" and not domain.has_blocking_closure(facility["id"]):
            order = domain.create_closure_order(
                facility, "WATER_CHEMISTRY", "system", "system",
                triggering_reading_id=rec["id"])
            rec["triggered_closure_order_id"] = order["id"]

        return object_response(water_reading_json(rec), 201)

    @app.route("/facilities/<facility_id>/water-readings", methods=["GET"])
    def list_water_readings(facility_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        facility = facility_or_404(facility_id)
        f_status = qs("compliance_status")
        rows = [r for r in DB.water_readings.values()
                if r["facility_id"] == facility["id"]
                and matches(r["compliance_status"], f_status)]
        return paged_list(rows, water_reading_json)

    # ------------------------------------------------------------------
    # closure orders
    # ------------------------------------------------------------------
    @app.route("/closure-orders", methods=["POST"])
    def create_closure_order_route():
        authenticate()
        authorize("Inspector", "HealthAuthorityAdmin", "Operator")
        body = json_body()
        facility_id = req_string(body, "facility_id")
        closure_reason = req_enum(body, "closure_reason", C.CLOSURE_REASONS)
        expected_facility_version = req_int(body, "expected_facility_version")
        note = opt_string(body, "note")

        facility = facility_or_404(facility_id)
        own_or_403(facility["operator_id"])

        if expected_facility_version != facility["version"]:
            raise ApiError("ERR_STALE_FACILITY_VERSION",
                           "The facility version has moved on.")

        order = domain.create_closure_order(facility, closure_reason, g.user_id,
                                            g.role, note=note)
        return object_response(closure_order_json(order), 201)

    @app.route("/closure-orders/<order_id>", methods=["GET"])
    def read_closure_order(order_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        rec = get_or_404(DB.closure_orders, order_id, "ERR_CLOSURE_ORDER_NOT_FOUND")
        return object_response(closure_order_json(rec))

    @app.route("/closure-orders", methods=["GET"])
    def list_closure_orders():
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        f_facility = qs("facility_id")
        f_reading = qs("triggering_reading_id")
        f_status = qs("status")
        rows = [o for o in DB.closure_orders.values()
                if matches(o["facility_id"], f_facility)
                and matches(o["triggering_reading_id"], f_reading)
                and matches(o["status"], f_status)]
        return paged_list(rows, closure_order_json)

    @app.route("/closure-orders/<order_id>/reopen-request", methods=["POST"])
    def closure_reopen_request(order_id):
        authenticate()
        authorize("Operator")
        order = get_or_404(DB.closure_orders, order_id, "ERR_CLOSURE_ORDER_NOT_FOUND")
        body = json_body()
        verification_reading_id = req_string(body, "verification_reading_id")
        treatment_free_chlorine_ppm = opt_number(body, "treatment_free_chlorine_ppm")
        treatment_ph = opt_number(body, "treatment_ph")

        reading = get_or_404(DB.water_readings, verification_reading_id,
                             "ERR_READING_NOT_FOUND")
        if reading["facility_id"] != order["facility_id"]:
            raise ApiError("ERR_READING_FACILITY_MISMATCH",
                           "The verification reading belongs to another facility.")

        facility = DB.facilities.get(order["facility_id"])
        own_or_403(facility["operator_id"] if facility else None)

        if order["status"] != "OPEN":
            _invalid_closure_state()

        age_minutes = minutes_between(LOGICAL_CLOCK.now(), reading["sampled_at"])
        if age_minutes < 0 or age_minutes > C.REOPEN_READING_MAX_AGE_MINUTES:
            raise ApiError("ERR_VERIFICATION_READING_STALE",
                           "The verification reading is not fresh.")

        order["status"] = "REOPEN_REQUESTED"
        order["reopen_requested_at"] = LOGICAL_CLOCK.now()
        order["verification_reading_id"] = reading["id"]
        order["treatment_free_chlorine_ppm"] = treatment_free_chlorine_ppm
        order["treatment_ph"] = treatment_ph
        domain.compute_remediation_window(order)
        touch(order)
        domain.bump_facility(facility)
        return object_response(closure_order_json(order))

    @app.route("/closure-orders/<order_id>/reopen-decision", methods=["POST"])
    def closure_reopen_decision(order_id):
        authenticate()
        authorize("Inspector", "HealthAuthorityAdmin")
        order = get_or_404(DB.closure_orders, order_id, "ERR_CLOSURE_ORDER_NOT_FOUND")
        body = json_body()
        decision = req_enum(body, "decision", REOPEN_DECISIONS)
        denial_reason = opt_enum(body, "denial_reason", C.DENIAL_REASONS)
        require_action_role(decision, REOPEN_DECISION_ROLES)
        facility = DB.facilities.get(order["facility_id"])

        if decision in ("APPROVE", "DENY"):
            if order["status"] != "REOPEN_REQUESTED":
                _invalid_closure_state()
        else:
            if order["status"] != "OPEN":
                _invalid_closure_state()

        if decision in ("APPROVE", "DENY"):
            if g.user_id == order["ordered_by_user_id"]:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                               "The actor that ordered this closure may not decide it.")

        if decision == "APPROVE":
            if domain.qualifying_open_violations(order["facility_id"],
                                                 ("IMMINENT_HEALTH_HAZARD",)):
                raise ApiError("ERR_OPEN_CRITICAL_VIOLATIONS",
                               "An open imminent-hazard violation blocks reopening.")
            reading = DB.water_readings.get(order["verification_reading_id"])
            reading_status = reading["compliance_status"] if reading else None
            if reading_status == "IMMINENT_HAZARD":
                raise ApiError("ERR_IMMINENT_HEALTH_HAZARD",
                               "The verification reading is an imminent hazard.")
            if reading_status != "IN_RANGE":
                raise ApiError("ERR_WATER_NOT_IN_RANGE",
                               "The verification reading is not in range.")
            if LOGICAL_CLOCK.now() < order["earliest_reopen_at"]:
                raise ApiError("ERR_REMEDIATION_INCOMPLETE",
                               "The remediation window has not elapsed.")
            order["status"] = "CLEARED"
            order["cleared_at"] = LOGICAL_CLOCK.now()
            order["reopen_decided_at"] = LOGICAL_CLOCK.now()
            order["reopen_decided_by_user_id"] = g.user_id
            order["reopen_denial_reason"] = None
        elif decision == "DENY":
            order["status"] = "OPEN"
            order["denial_count"] += 1
            order["reopen_denial_reason"] = denial_reason
            order["reopen_decided_at"] = LOGICAL_CLOCK.now()
            order["reopen_decided_by_user_id"] = g.user_id
        else:  # VOID
            order["status"] = "VOIDED"
            order["reopen_decided_at"] = LOGICAL_CLOCK.now()
            order["reopen_decided_by_user_id"] = g.user_id

        touch(order)
        domain.bump_facility(facility)
        return object_response(closure_order_json(order))

    # ------------------------------------------------------------------
    # staff assignments
    # ------------------------------------------------------------------
    @app.route("/staff-assignments", methods=["POST"])
    def create_staff_assignment():
        authenticate()
        authorize("Operator")
        body = json_body()
        facility_id = req_string(body, "facility_id")
        staff_ref = req_string(body, "staff_ref", min_len=1, max_len=64)
        staff_name = req_string(body, "staff_name", min_len=1)
        role_type = req_enum(body, "role_type", C.STAFF_ROLE_TYPES)
        certification_expires_on = req_date(body, "certification_expires_on")
        shift_start_at = req_datetime(body, "shift_start_at")
        shift_end_at = req_datetime(body, "shift_end_at")

        facility = facility_or_404(facility_id)
        own_or_403(facility["operator_id"])

        posture, _reason = domain.operating_posture(facility)
        if posture == "CLOSED":
            raise ApiError("ERR_FACILITY_CLOSED",
                           "The facility is closed; no shift may be scheduled.")

        if shift_end_at <= shift_start_at or \
                minutes_between(shift_end_at, shift_start_at) > C.MAX_SHIFT_MINUTES:
            raise ApiError("ERR_SHIFT_TOO_LONG",
                           "The shift interval is invalid or exceeds the maximum.")

        if certification_expires_on < shift_start_at.date():
            raise ApiError("ERR_CERTIFICATION_EXPIRED",
                           "The certification has lapsed before the shift starts.")

        for other in DB.staff_assignments.values():
            if other["staff_ref"] != staff_ref or other["status"] != "SCHEDULED":
                continue
            if shift_start_at < other["shift_end_at"] \
                    and other["shift_start_at"] < shift_end_at:
                raise ApiError("ERR_STAFF_SHIFT_OVERLAP",
                               "This individual already holds an overlapping shift.")

        rec = base_record()
        rec.update({
            "facility_id": facility["id"],
            "staff_ref": staff_ref,
            "staff_name": staff_name,
            "role_type": role_type,
            "certification_expires_on": certification_expires_on,
            "shift_start_at": shift_start_at,
            "shift_end_at": shift_end_at,
            "status": "SCHEDULED",
            "cancel_reason": None,
            "cancelled_at": None,
        })
        DB.staff_assignments[rec["id"]] = rec
        domain.bump_facility(facility)
        return object_response(staff_assignment_json(rec), 201)

    @app.route("/facilities/<facility_id>/staff-assignments", methods=["GET"])
    def list_staff_assignments(facility_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        facility = facility_or_404(facility_id)
        f_status = qs("status")
        f_role = qs("role_type")
        rows = [s for s in DB.staff_assignments.values()
                if s["facility_id"] == facility["id"]
                and matches(s["status"], f_status)
                and matches(s["role_type"], f_role)]
        return paged_list(rows, staff_assignment_json)

    @app.route("/staff-assignments/<assignment_id>/cancel", methods=["POST"])
    def cancel_staff_assignment(assignment_id):
        authenticate()
        authorize("Operator")
        rec = get_or_404(DB.staff_assignments, assignment_id,
                         "ERR_STAFF_ASSIGNMENT_NOT_FOUND")
        json_body()
        facility = DB.facilities.get(rec["facility_id"])
        own_or_403(facility["operator_id"] if facility else None)

        if rec["status"] != "SCHEDULED":
            raise ApiError("ERR_ASSIGNMENT_ALREADY_CANCELLED",
                           "This shift has already been cancelled.")

        rec["status"] = "CANCELLED"
        rec["cancel_reason"] = "OPERATOR_REQUEST"
        rec["cancelled_at"] = LOGICAL_CLOCK.now()
        touch(rec)
        domain.bump_facility(facility)
        return object_response(staff_assignment_json(rec))

    # ------------------------------------------------------------------
    # compliance artifacts
    # ------------------------------------------------------------------
    @app.route("/facilities/<facility_id>/compliance-artifacts", methods=["POST"])
    def create_compliance_artifact(facility_id):
        authenticate()
        authorize("Operator")
        facility = facility_or_404(facility_id)
        body = json_body()
        artifact_type = req_enum(body, "artifact_type", C.ARTIFACT_TYPES)
        effective_on = req_date(body, "effective_on")
        signage_type = opt_enum(body, "signage_type", C.SIGNAGE_TYPES)
        drain_cover_model = opt_string(body, "drain_cover_model", min_len=1)
        sva_system_type = opt_enum(body, "sva_system_type", C.SVA_SYSTEM_TYPES)
        if effective_on > LOGICAL_CLOCK.today():
            bad("effective_on must not be later than the logical-clock date.")

        if artifact_type == "SIGNAGE":
            if signage_type is None or drain_cover_model is not None \
                    or sva_system_type is not None:
                raise ApiError("ERR_ARTIFACT_FIELDS_MISMATCH",
                               "A signage artifact carries signage_type only.")
            expires_on = add_days(effective_on, C.SIGNAGE_VALID_DAYS)
        else:
            if drain_cover_model is None or sva_system_type is None \
                    or signage_type is not None:
                raise ApiError("ERR_ARTIFACT_FIELDS_MISMATCH",
                               "A drain certification carries the drain fields only.")
            expires_on = add_days(effective_on, C.VGB_COVER_LIFESPAN_DAYS)

        own_or_403(facility["operator_id"])

        rec = base_record()
        rec.update({
            "facility_id": facility["id"],
            "artifact_type": artifact_type,
            "signage_type": signage_type,
            "drain_cover_model": drain_cover_model,
            "sva_system_type": sva_system_type,
            "effective_on": effective_on,
            "expires_on": expires_on,
        })
        DB.compliance_artifacts[rec["id"]] = rec
        domain.bump_facility(facility)
        return object_response(compliance_artifact_json(rec), 201)

    @app.route("/facilities/<facility_id>/compliance-artifacts", methods=["GET"])
    def list_compliance_artifacts(facility_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        facility = facility_or_404(facility_id)
        f_type = qs("artifact_type")
        f_status = qs("status")
        rows = []
        for a in DB.compliance_artifacts.values():
            if a["facility_id"] != facility["id"]:
                continue
            if not matches(a["artifact_type"], f_type):
                continue
            if f_status is not None and domain.artifact_status(a) != f_status:
                continue
            rows.append(a)
        return paged_list(rows, compliance_artifact_json)

    # ------------------------------------------------------------------
    # complaints
    # ------------------------------------------------------------------
    @app.route("/complaints", methods=["POST"])
    def create_complaint():
        authenticate()
        authorize("Anonymous", "Operator", "Inspector")
        body = json_body()
        facility_id = req_string(body, "facility_id")
        complaint_type = req_enum(body, "complaint_type", C.COMPLAINT_TYPES)
        narrative = req_string(body, "narrative", min_len=1)
        reporter_contact = opt_string(body, "reporter_contact")
        symptom_onset_date = opt_date(body, "symptom_onset_date")
        illness_case_count = opt_int(body, "illness_case_count", default=0)
        pathogen_suspected = opt_enum(body, "pathogen_suspected", C.PATHOGENS)

        if complaint_type == "RWI_ILLNESS":
            if symptom_onset_date is None:
                bad("symptom_onset_date is required for an RWI_ILLNESS complaint.")
            if illness_case_count < 1:
                bad("illness_case_count must be at least 1 for an RWI_ILLNESS "
                    "complaint.")
            if symptom_onset_date > LOGICAL_CLOCK.today():
                bad("symptom_onset_date must not be later than the logical-clock date.")
        else:
            if symptom_onset_date is not None:
                bad("symptom_onset_date belongs to RWI_ILLNESS complaints only.")
            if illness_case_count != 0:
                bad("illness_case_count belongs to RWI_ILLNESS complaints only.")

        facility = facility_or_404(facility_id)

        rec = base_record()
        rec.update({
            "facility_id": facility["id"],
            "linked_inspection_id": None,
            "complaint_type": complaint_type,
            "reporter_contact": reporter_contact,
            "narrative": narrative,
            "symptom_onset_date": symptom_onset_date,
            "illness_case_count": illness_case_count,
            "pathogen_suspected": pathogen_suspected,
            "reported_at": LOGICAL_CLOCK.now(),
            "risk_variant": None,
            "cluster_case_count": 0,
            "risk_score": 0,
            "escalated": False,
            "status": "RECEIVED",
            "finding": None,
        })
        DB.complaints[rec["id"]] = rec

        variant, cluster_count, score, escalated = domain.score_complaint(rec)
        rec["risk_variant"] = variant
        rec["cluster_case_count"] = cluster_count
        rec["risk_score"] = score
        rec["escalated"] = escalated

        if escalated:
            domain.create_closure_order(facility, "RWI_OUTBREAK", "system", "system")

        return object_response(complaint_json(rec), 201)

    @app.route("/complaints/<complaint_id>", methods=["GET"])
    def read_complaint(complaint_id):
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        rec = get_or_404(DB.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")
        return object_response(complaint_json(rec))

    @app.route("/complaints", methods=["GET"])
    def list_complaints():
        authenticate()
        authorize("Operator", "Inspector", "HealthAuthorityAdmin")
        f_facility = qs("facility_id")
        f_inspection = qs("linked_inspection_id")
        f_type = qs("complaint_type")
        f_status = qs("status")
        rows = [c for c in DB.complaints.values()
                if matches(c["facility_id"], f_facility)
                and matches(c["linked_inspection_id"], f_inspection)
                and matches(c["complaint_type"], f_type)
                and matches(c["status"], f_status)]
        return paged_list(rows, complaint_json)

    @app.route("/complaints/<complaint_id>/transition", methods=["POST"])
    def transition_complaint(complaint_id):
        authenticate()
        authorize("Inspector", "HealthAuthorityAdmin")
        complaint = get_or_404(DB.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")
        body = json_body()
        action = req_enum(body, "action", COMPLAINT_ACTIONS)
        linked_inspection_id = opt_string(body, "linked_inspection_id")
        finding = opt_string(body, "finding")
        require_action_role(action, COMPLAINT_ACTION_ROLES)

        linked = None
        if linked_inspection_id is not None:
            linked = get_or_404(DB.inspections, linked_inspection_id,
                                "ERR_INSPECTION_NOT_FOUND")
            if (linked["facility_id"] != complaint["facility_id"]
                    or linked["inspection_type"] != "COMPLAINT"):
                raise ApiError("ERR_PRIOR_INSPECTION_MISMATCH",
                               "The linked inspection does not qualify.")

        if action == "TRIAGE":
            if complaint["status"] != "RECEIVED":
                _invalid_complaint_state()
            if linked is not None:
                complaint["linked_inspection_id"] = linked["id"]
            complaint["status"] = "TRIAGED"
        elif action == "START_INVESTIGATION":
            if complaint["status"] != "TRIAGED":
                _invalid_complaint_state()
            if complaint["linked_inspection_id"] is None:
                _invalid_complaint_state()
            complaint["status"] = "INVESTIGATING"
        elif action in ("SUBSTANTIATE", "UNSUBSTANTIATE"):
            if complaint["status"] != "INVESTIGATING":
                _invalid_complaint_state()
            attached = DB.inspections.get(complaint["linked_inspection_id"])
            if attached is None or attached["workflow_status"] != "FINALIZED":
                _invalid_complaint_state()
            complaint["status"] = ("SUBSTANTIATED" if action == "SUBSTANTIATE"
                                   else "UNSUBSTANTIATED")
            complaint["finding"] = finding
        else:  # CLOSE
            if complaint["status"] not in ("SUBSTANTIATED", "UNSUBSTANTIATED"):
                _invalid_complaint_state()
            complaint["status"] = "CLOSED"

        touch(complaint)
        return object_response(complaint_json(complaint))
