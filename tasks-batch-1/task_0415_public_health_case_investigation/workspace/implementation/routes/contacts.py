"""Contact lifecycle: elicit, notify, monitor, promote, void, exposure events."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import (base_entity, touch, parse_pagination, sorted_by_creation,
                     get_or_404, get_in_program_or_404, require_string, require_enum,
                     require_bool, require_non_negative_int, require_non_negative_number,
                     parse_dt, add_days, day_diff, at_utc_midnight)
from middleware import get_user_context, require_role
from response import success, success_list
from serializers import (ser_contact, ser_case, ser_monitoring_period,
                         ser_exposure_event)
from calculations import (find_condition, compute_priority, compute_quarantine,
                          earliest_qualifying_date, compute_completeness,
                          compute_infectious_window)
from services import (check_contact_scope, inc_active_monitoring,
                      dec_active_monitoring, active_monitoring_period_for,
                      void_contact)
from routes.config import ALL_ROLES

bp = Blueprint("contacts", __name__)

EXPOSURE_SETTINGS = {"HOUSEHOLD", "HEALTHCARE", "WORKPLACE", "SOCIAL", "COMMUNITY"}
RESULT_VALUES = {"POSITIVE", "NEGATIVE", "INDETERMINATE"}
MONITORING_TYPES = {"QUARANTINE", "ISOLATION"}


# --- Elicit / List / Get ---
@bp.route("/surveillance/contacts", methods=["POST"])
def elicit_contact():
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    body = request.get_json(silent=True) or {}
    # FK presence (needed to resolve existence first per PRD 2.6 ordering)
    program_id = require_string(body, "program_id")
    source_case_id = require_string(body, "source_case_id")
    monitoring_jurisdiction_id = require_string(body, "monitoring_jurisdiction_id")

    with db.lock:
        # existence (priority 4) before typed field validation (last)
        get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        case = get_in_program_or_404(db.cases, source_case_id, program_id, "ERR_CASE_NOT_FOUND")
        get_in_program_or_404(db.jurisdictions, monitoring_jurisdiction_id, program_id,
                              "ERR_JURISDICTION_NOT_FOUND")

        # jurisdiction scope (priority 5): the contact lifecycle is scoped to the
        # tracer's jurisdiction; eliciting a contact whose monitoring_jurisdiction_id
        # is outside the acting tracer's jurisdiction is denied.
        if role in ("IntakeProcessor", "CaseInvestigator", "ContactTracer"):
            if monitoring_jurisdiction_id != user_id:
                raise err("ERR_JURISDICTION_SCOPE_VIOLATION",
                          "Scoped role acting outside its jurisdiction")

        # field-level input validation
        contact_reference = require_string(body, "contact_reference")
        exposure_setting = require_enum(body, "exposure_setting", EXPOSURE_SETTINGS)
        proximity_meters = require_non_negative_number(body, "proximity_meters")
        cumulative_exposure_minutes = require_non_negative_int(body, "cumulative_exposure_minutes")
        is_high_risk_contact = require_bool(body, "is_high_risk_contact", default=False)
        last_exposure_date = require_string(body, "last_exposure_date")
        parse_dt(last_exposure_date)

        ent = base_entity(common_fields=True)
        score, band = compute_priority(exposure_setting, proximity_meters,
                                       cumulative_exposure_minutes, is_high_risk_contact)
        ent.update({
            "program_id": program_id,
            "source_case_id": source_case_id,
            "monitoring_jurisdiction_id": monitoring_jurisdiction_id,
            "contact_reference": contact_reference,
            "exposure_setting": exposure_setting,
            "proximity_meters": proximity_meters,
            "cumulative_exposure_minutes": cumulative_exposure_minutes,
            "is_high_risk_contact": is_high_risk_contact,
            "last_exposure_date": last_exposure_date,
            "priority_score": score,
            "priority_band": band,
            "quarantine_release_basis": "STANDARD",
            "quarantine_end_date": None,
            "has_qualifying_negative_test": False,
            "notification_attempts": 0,
            "promoted_case_id": None,
            "status": "ELICITED",
        })
        # quarantine end (STANDARD) — based on source case's condition
        cond = find_condition(program_id, case["condition_code"])
        basis, qend = compute_quarantine(ent, cond)
        ent["quarantine_release_basis"] = basis
        ent["quarantine_end_date"] = qend
        db.contacts[ent["id"]] = ent

        # increment source case contact_count + recompute completeness
        case["contact_count"] = case.get("contact_count", 0) + 1
        case["completeness_score"] = compute_completeness(case)
        touch(case)
        return success(ser_contact(ent), 201)


@bp.route("/surveillance/contacts", methods=["GET"])
def list_contacts():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        filters = ["program_id", "source_case_id", "monitoring_jurisdiction_id",
                   "status", "priority_band", "promoted_case_id"]
        items = []
        for c in db.contacts.values():
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
        return success_list([ser_contact(c) for c in page], limit, offset, total)


@bp.route("/surveillance/contacts/<contact_id>", methods=["GET"])
def get_contact(contact_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        c = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        return success(ser_contact(c), 200)


# --- Qualifying test ---
@bp.route("/surveillance/contacts/<contact_id>/qualifying-test", methods=["POST"])
def qualifying_test(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        body = request.get_json(silent=True) or {}
        result_value = require_enum(body, "result_value", RESULT_VALUES)
        specimen_collection_date = require_string(body, "specimen_collection_date")
        spec_dt = parse_dt(specimen_collection_date)

        case = db.cases.get(contact["source_case_id"])
        cond = find_condition(contact["program_id"], case["condition_code"]) if case else None
        earliest = earliest_qualifying_date(contact, cond)

        qualifies = (result_value == "NEGATIVE" and earliest is not None
                     and at_utc_midnight(spec_dt) >= earliest)
        if qualifies:
            contact["has_qualifying_negative_test"] = True
        basis, qend = compute_quarantine(contact, cond)
        contact["quarantine_release_basis"] = basis
        contact["quarantine_end_date"] = qend
        touch(contact)
        return success(ser_contact(contact), 200)


# --- Notification queue / record ---
@bp.route("/surveillance/contacts/<contact_id>/queue-notification", methods=["POST"])
def queue_notification(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        if contact["status"] not in ("ELICITED", "NOTIFICATION_FAILED"):
            raise err("ERR_CONTACT_NOT_QUEUEABLE", "Contact not in ELICITED/NOTIFICATION_FAILED to queue")
        contact["status"] = "NOTIFICATION_PENDING"
        touch(contact)
        return success(ser_contact(contact), 200)


@bp.route("/surveillance/contacts/<contact_id>/record-notification", methods=["POST"])
def record_notification(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        body = request.get_json(silent=True) or {}
        outcome = require_enum(body, "outcome", {"SUCCESS", "FAILED"})
        if contact["status"] != "NOTIFICATION_PENDING":
            raise err("ERR_CONTACT_NOT_PENDING_NOTIFICATION",
                      "Contact not in NOTIFICATION_PENDING for record-notification")
        contact["notification_attempts"] = contact.get("notification_attempts", 0) + 1
        if outcome == "SUCCESS":
            contact["status"] = "NOTIFIED"
        else:
            contact["status"] = "NOTIFICATION_FAILED"
        touch(contact)
        return success(ser_contact(contact), 200)


# --- Monitoring periods ---
@bp.route("/surveillance/contacts/<contact_id>/monitoring-periods", methods=["POST"])
def schedule_monitoring_period(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        body = request.get_json(silent=True) or {}
        monitoring_type = require_enum(body, "monitoring_type", MONITORING_TYPES)
        start_date = require_string(body, "start_date")
        end_date = require_string(body, "end_date")
        start_dt = at_utc_midnight(parse_dt(start_date))
        end_dt = at_utc_midnight(parse_dt(end_date))
        if end_dt < start_dt:
            raise err("ERR_INVALID_REQUEST", "end_date must be >= start_date")

        # overlap check against existing non-terminal (SCHEDULED/ACTIVE) periods
        for m in db.monitoring_periods.values():
            if m["contact_id"] != contact_id:
                continue
            if m["status"] not in ("SCHEDULED", "ACTIVE"):
                continue
            m_start = at_utc_midnight(parse_dt(m["start_date"]))
            m_end = at_utc_midnight(parse_dt(m["end_date"]))
            # shares any day if ranges intersect (inclusive); adjacency allowed
            if start_dt <= m_end and m_start <= end_dt:
                raise err("ERR_MONITORING_PERIOD_OVERLAP",
                          "New monitoring period shares a day with an existing non-terminal period")

        ent = base_entity(common_fields=True)
        ent.update({
            "program_id": contact["program_id"],
            "contact_id": contact_id,
            "jurisdiction_id": contact["monitoring_jurisdiction_id"],
            "monitoring_type": monitoring_type,
            "start_date": start_date,
            "end_date": end_date,
            "status": "SCHEDULED",
        })
        db.monitoring_periods[ent["id"]] = ent
        return success(ser_monitoring_period(ent), 201)


@bp.route("/surveillance/contacts/<contact_id>/start-monitoring", methods=["POST"])
def start_monitoring(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        if contact["status"] != "NOTIFIED":
            raise err("ERR_CONTACT_NOT_NOTIFIED", "Contact not in NOTIFIED for start-monitoring")
        if not contact.get("quarantine_end_date"):
            raise err("ERR_QUARANTINE_WINDOW_MISSING", "quarantine_end_date missing")
        scheduled = None
        for m in sorted_by_creation(list(db.monitoring_periods.values())):
            if m["contact_id"] == contact_id and m["status"] == "SCHEDULED":
                scheduled = m
                break
        if scheduled is None:
            raise err("ERR_NO_SCHEDULED_MONITORING", "No SCHEDULED MonitoringPeriod for contact")
        scheduled["status"] = "ACTIVE"
        touch(scheduled)
        contact["status"] = "MONITORING_ACTIVE"
        touch(contact)
        inc_active_monitoring(contact["monitoring_jurisdiction_id"])
        return success(ser_contact(contact), 200)


@bp.route("/surveillance/contacts/<contact_id>/complete-monitoring", methods=["POST"])
def complete_monitoring(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        if contact["status"] != "MONITORING_ACTIVE":
            raise err("ERR_CONTACT_NOT_MONITORING", "Contact not in MONITORING_ACTIVE for complete-monitoring")
        program = db.programs.get(contact["program_id"])
        current = at_utc_midnight(parse_dt(program["current_date"])) if program else None
        qend = at_utc_midnight(parse_dt(contact.get("quarantine_end_date")))
        if current is None or qend is None or current < qend:
            raise err("ERR_MONITORING_NOT_ELAPSED",
                      "current_date has not reached quarantine_end_date")
        mp = active_monitoring_period_for(contact_id)
        if mp is not None:
            mp["status"] = "COMPLETED"
            touch(mp)
        contact["status"] = "MONITORING_COMPLETE"
        touch(contact)
        dec_active_monitoring(contact["monitoring_jurisdiction_id"])
        return success(ser_contact(contact), 200)


# --- Promote ---
@bp.route("/surveillance/contacts/<contact_id>/promote", methods=["POST"])
def promote_contact(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        if contact["status"] not in ("MONITORING_ACTIVE", "NOTIFIED"):
            raise err("ERR_CONTACT_NOT_PROMOTABLE",
                      "Contact not in MONITORING_ACTIVE/NOTIFIED for promote")
        body = request.get_json(silent=True) or {}
        symptom_onset_date = body.get("symptom_onset_date")
        if not symptom_onset_date:
            raise err("ERR_ONSET_OR_SPECIMEN_REQUIRED", "symptom_onset_date required for promote")
        parse_dt(symptom_onset_date)

        was_active = contact["status"] == "MONITORING_ACTIVE"
        source_case = db.cases.get(contact["source_case_id"])
        condition_code = source_case["condition_code"] if source_case else None

        new_case = base_entity(common_fields=True)
        new_case.update({
            "program_id": contact["program_id"],
            "jurisdiction_id": contact["monitoring_jurisdiction_id"],
            "condition_code": condition_code,
            "patient_reference": contact["contact_reference"],
            "source_lab_result_id": None,
            "source_contact_id": contact["id"],
            "symptom_onset_date": symptom_onset_date,
            "specimen_collection_date": None,
            "last_symptomatic_date": None,
            "is_symptomatic": True,
            "interview_completed": False,
            "infectious_start_date": None,
            "infectious_end_date": None,
            "isolation_end_date": None,
            "completeness_score": 0,
            "contact_count": 0,
            "linked_positive_count": 0,
            "cluster_id": None,
            "exposure_setting_location_id": None,
            "classification": "SUSPECT",
            "status": "OPEN",
            "_prior_status": None,
        })
        db.cases[new_case["id"]] = new_case

        contact["promoted_case_id"] = new_case["id"]
        contact["status"] = "PROMOTED_TO_CASE"
        if was_active:
            mp = active_monitoring_period_for(contact_id)
            if mp is not None:
                mp["status"] = "RELEASED_EARLY"
                touch(mp)
            dec_active_monitoring(contact["monitoring_jurisdiction_id"])
        touch(contact)
        return success(ser_case(new_case), 201)


# --- Void ---
@bp.route("/surveillance/contacts/<contact_id>/void", methods=["POST"])
def void_contact_route(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        if contact["status"] not in ("ELICITED", "NOTIFICATION_PENDING", "NOTIFIED",
                                     "NOTIFICATION_FAILED", "MONITORING_ACTIVE"):
            raise err("ERR_CONTACT_NOT_VOIDABLE", "Contact already terminal for void")
        void_contact(contact)
        return success(ser_contact(contact), 200)


# --- Exposure events ---
@bp.route("/surveillance/contacts/<contact_id>/exposure-events", methods=["POST"])
def append_exposure_event(contact_id):
    user_id, role = get_user_context()
    require_role(role, {"ContactTracer"})
    with db.lock:
        contact = get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")
        check_contact_scope(user_id, role, contact)
        body = request.get_json(silent=True) or {}
        encounter_date = require_string(body, "encounter_date")
        enc_dt = at_utc_midnight(parse_dt(encounter_date))
        setting_note = require_string(body, "setting_note", required=False)

        case = db.cases.get(contact["source_case_id"])
        start = at_utc_midnight(parse_dt(case.get("infectious_start_date"))) if case else None
        end = at_utc_midnight(parse_dt(case.get("infectious_end_date"))) if case else None
        if start is None or end is None or enc_dt < start or enc_dt > end:
            raise err("ERR_ENCOUNTER_OUTSIDE_INFECTIOUS_WINDOW",
                      "encounter_date outside the index case infectious window")

        ent = base_entity(common_fields=False)
        ent.update({
            "program_id": contact["program_id"],
            "contact_id": contact_id,
            "case_id": contact["source_case_id"],
            "encounter_date": encounter_date,
            "setting_note": setting_note,
        })
        db.exposure_events[ent["id"]] = ent
        return success(ser_exposure_event(ent), 201)


# --- Exposure event reads ---
@bp.route("/surveillance/exposure-events", methods=["GET"])
def list_exposure_events():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        filters = ["program_id", "contact_id", "case_id"]
        items = []
        for e in db.exposure_events.values():
            ok = True
            for f in filters:
                v = request.args.get(f)
                if v is not None and e.get(f) != v:
                    ok = False
                    break
            if ok:
                items.append(e)
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_exposure_event(e) for e in page], limit, offset, total)


@bp.route("/surveillance/exposure-events/<event_id>", methods=["GET"])
def get_exposure_event(event_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        e = get_or_404(db.exposure_events, event_id, "ERR_EXPOSURE_EVENT_NOT_FOUND")
        return success(ser_exposure_event(e), 200)


# --- Monitoring period reads ---
@bp.route("/surveillance/monitoring-periods", methods=["GET"])
def list_monitoring_periods():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        filters = ["program_id", "contact_id", "jurisdiction_id", "status"]
        items = []
        for m in db.monitoring_periods.values():
            ok = True
            for f in filters:
                v = request.args.get(f)
                if v is not None and m.get(f) != v:
                    ok = False
                    break
            if ok:
                items.append(m)
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_monitoring_period(m) for m in page], limit, offset, total)


@bp.route("/surveillance/monitoring-periods/<period_id>", methods=["GET"])
def get_monitoring_period(period_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        m = get_or_404(db.monitoring_periods, period_id, "ERR_MONITORING_PERIOD_NOT_FOUND")
        return success(ser_monitoring_period(m), 200)
