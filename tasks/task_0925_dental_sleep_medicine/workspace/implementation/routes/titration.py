"""Titration visits and adherence downloads."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import validation as v
from access import (actor, body_refs, gate_device, gate_frozen, in_scope, new_row,
                    ordered, path_row, require_scope, touch)
from envelope import created, ok
from errors import fail
from serializers import dump
from store import DB, add_days, clock_date, day_span, dec

bp = Blueprint("titration", __name__)


@bp.post("/titration-visits")
def create_visit():
    uid, role = actor(["Dentist"])
    body = v.read_body()
    refs = body_refs(body, ["appliance_id", "performed_by_dentist_id"])
    appliance = refs["appliance_id"]
    if appliance is not None:
        gate_frozen(DB["patients"].get(appliance["patient_id"]))
        require_scope(role, uid, appliance["patient_id"])
    fields = [
        v.S("appliance_id", required=True),
        v.S("performed_by_dentist_id", required=True),
        v.D("scheduled_for", required=True),
        v.N("requested_increment_mm", required=True),
        v.I("expected_appliance_version", required=True),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    scheduled_for = v.date_of(body, "scheduled_for")
    v.between(body, "requested_increment_mm", 0.25, 2.00)
    v.multiple_of_quarter(body, "requested_increment_mm")
    if body["expected_appliance_version"] != appliance["version"]:
        fail("ERR_STALE_VERSION", "expected_appliance_version does not match the appliance.")
    gate_device(appliance)
    dentist = refs["performed_by_dentist_id"]
    if dentist["provider_type"] != "DENTIST" or dentist["status"] != "ACTIVE":
        fail("ERR_PROVIDER_TYPE_MISMATCH", "performed_by_dentist_id must be an ACTIVE DENTIST.")

    prior = domain.visits_of(appliance["id"])
    for visit in prior:
        if visit["status"] in ("SCHEDULED", "HELD"):
            visit["status"] = "SUPERSEDED"
            touch(visit)
    row = new_row("titration_visits", {
        "appliance_id": appliance["id"],
        "performed_by_dentist_id": dentist["id"],
        "visit_seq": len(prior) + 1,
        "scheduled_for": scheduled_for,
        "requested_increment_mm": body["requested_increment_mm"],
        "side_effect_severity": None,
        "applied_increment_mm": None,
        "applied_on": None,
        "days_since_prior_applied": None,
        "status": "SCHEDULED",
    })
    touch(appliance)
    return created(dump("titration_visit", row))


@bp.get("/titration-visits/<visit_id>")
def read_visit(visit_id):
    uid, role = actor(["Dentist", "ClinicCoordinator", "PlatformAdmin"])
    visit = path_row("visit_id", visit_id)
    appliance = DB["appliances"].get(visit["appliance_id"])
    if appliance is not None:
        require_scope(role, uid, appliance["patient_id"])
    return ok(dump("titration_visit", visit))


@bp.get("/titration-visits")
def list_visits():
    uid, role = actor(["Dentist", "ClinicCoordinator", "PlatformAdmin"])
    limit, offset = v.pagination()
    filters = {
        "appliance_id": request.args.get("appliance_id"),
        "performed_by_dentist_id": request.args.get("performed_by_dentist_id"),
        "status": request.args.get("status"),
    }

    def scope_pred(row):
        appliance = DB["appliances"].get(row["appliance_id"])
        return appliance is not None and in_scope(role, uid, appliance["patient_id"])

    return domain.paginate("titration_visit", "titration_visits", filters, limit, offset, scope_pred)


@bp.post("/titration-visits/<visit_id>/apply")
def apply_visit(visit_id):
    uid, role = actor(["Dentist"])
    visit = path_row("visit_id", visit_id)
    body = v.read_body()
    appliance = DB["appliances"].get(visit["appliance_id"])
    gate_frozen(DB["patients"].get(appliance["patient_id"]) if appliance else None)
    if appliance is not None:
        require_scope(role, uid, appliance["patient_id"])
    fields = [v.S("side_effect_severity", required=True, enum=v.ENUM_SIDE_EFFECT)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if visit["status"] not in ("SCHEDULED", "HELD"):
        fail("ERR_INVALID_STATE", "Only an open visit may be applied.")
    if appliance["lifecycle_status"] not in ("DELIVERED", "IN_TITRATION"):
        fail("ERR_INVALID_STATE", "The appliance is not in a titratable state.")
    gate_device(appliance)

    severity = body["side_effect_severity"]
    prior = domain.last_resolved_visit(appliance["id"])
    today = clock_date()

    if severity in ("NONE", "MILD"):
        if prior is not None:
            if day_span(prior["applied_on"], today) < calc.MIN_TITRATION_INTERVAL_DAYS:
                fail("ERR_TITRATION_INTERVAL", "Fourteen whole days must separate applications.")
        bounded = min(dec(visit["requested_increment_mm"]), calc.MAX_INCREMENT_PER_VISIT_MM)
        if dec(appliance["current_advancement_mm"]) + bounded > dec(appliance["max_protrusive_mm"]):
            fail("ERR_PROTRUSION_LIMIT_EXCEEDED", "The increment would breach the protrusive ceiling.")
        visit["applied_increment_mm"] = bounded.quantize(Decimal("0.01"))
        visit["applied_on"] = today
        visit["days_since_prior_applied"] = (
            None if prior is None else day_span(prior["applied_on"], today))
        visit["status"] = "APPLIED"
    elif severity == "MODERATE":
        visit["applied_increment_mm"] = Decimal("0.00")
        visit["applied_on"] = None
        visit["scheduled_for"] = add_days(visit["scheduled_for"], calc.MIN_TITRATION_INTERVAL_DAYS)
        visit["status"] = "HELD"
    else:
        reduction = min(calc.SEVERE_SIDE_EFFECT_REDUCTION_MM, dec(appliance["current_advancement_mm"]))
        visit["applied_increment_mm"] = (-reduction).quantize(Decimal("0.01"))
        visit["applied_on"] = today
        visit["days_since_prior_applied"] = (
            None if prior is None else day_span(prior["applied_on"], today))
        visit["status"] = "REDUCED"

    visit["side_effect_severity"] = severity
    touch(visit)
    if visit["status"] in ("APPLIED", "REDUCED"):
        was_zero = appliance["applied_visit_count"] == 0
        domain.recompute_advancement(appliance)
        if was_zero and appliance["lifecycle_status"] == "DELIVERED":
            appliance["lifecycle_status"] = "IN_TITRATION"
        touch(appliance)
    return ok(dump("titration_visit", visit))


# ------------------------------------------------------- adherence downloads

@bp.post("/adherence-downloads")
def create_download():
    uid, role = actor(["Dentist", "ClinicCoordinator", "Patient"])
    body = v.read_body()
    refs = body_refs(body, ["appliance_id"])
    appliance = refs["appliance_id"]
    if appliance is not None:
        gate_frozen(DB["patients"].get(appliance["patient_id"]))
        require_scope(role, uid, appliance["patient_id"])
    fields = [
        v.S("appliance_id", required=True),
        v.S("source", required=True, enum=v.ENUM_ADHERENCE_SOURCE),
        v.D("window_start", required=True),
        v.D("window_end", required=True),
        v.I("nights_recorded", required=True),
        v.I("nights_at_or_above_min_hours", required=True),
        v.N("mean_hours_per_worn_night", required=True),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    window_start = v.date_of(body, "window_start")
    window_end = v.date_of(body, "window_end")
    if day_span(window_start, window_end) != calc.ADHERENCE_WINDOW_DAYS - 1:
        fail("ERR_VALIDATION", "The adherence window must span exactly thirty inclusive nights.")
    v.between(body, "nights_recorded", 0, calc.ADHERENCE_WINDOW_DAYS)
    v.at_least(body, "nights_at_or_above_min_hours", 0)
    if body["nights_at_or_above_min_hours"] > body["nights_recorded"]:
        fail("ERR_VALIDATION", "nights_at_or_above_min_hours may not exceed nights_recorded.")
    v.between(body, "mean_hours_per_worn_night", 0, 24)
    if body["source"] == "OBJECTIVE_MICRORECORDER" and not appliance["has_microrecorder"]:
        fail("ERR_VALIDATION", "This device carries no microrecorder.")

    rate_window, rate_recorded, compliant = calc.adherence_rates(
        body["nights_at_or_above_min_hours"], body["nights_recorded"])
    row = new_row("adherence_downloads", {
        "appliance_id": appliance["id"],
        "source": body["source"],
        "window_start": window_start,
        "window_end": window_end,
        "nights_recorded": body["nights_recorded"],
        "nights_at_or_above_min_hours": body["nights_at_or_above_min_hours"],
        "mean_hours_per_worn_night": body["mean_hours_per_worn_night"],
        "rate_of_window": rate_window,
        "rate_of_recorded": rate_recorded,
        "compliant": compliant,
    }, versioned=False)
    return created(dump("adherence_download", row))


@bp.get("/adherence-downloads/<adherence_download_id>")
def read_download(adherence_download_id):
    uid, role = actor(["Dentist", "BillingSpecialist", "PlatformAdmin", "Patient"])
    row = path_row("adherence_download_id", adherence_download_id)
    appliance = DB["appliances"].get(row["appliance_id"])
    if appliance is not None:
        require_scope(role, uid, appliance["patient_id"])
    return ok(dump("adherence_download", row))


@bp.get("/adherence-downloads")
def list_downloads():
    uid, role = actor(["Dentist", "BillingSpecialist", "PlatformAdmin", "Patient"])
    limit, offset = v.pagination()
    filters = {
        "appliance_id": request.args.get("appliance_id"),
        "source": request.args.get("source"),
    }

    def scope_pred(row):
        appliance = DB["appliances"].get(row["appliance_id"])
        return appliance is not None and in_scope(role, uid, appliance["patient_id"])

    return domain.paginate("adherence_download", "adherence_downloads", filters,
                           limit, offset, scope_pred)
