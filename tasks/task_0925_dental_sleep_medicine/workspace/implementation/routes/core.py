"""The logical clock, providers, payers and patients."""

from flask import Blueprint, request

import domain
import validation as v
from access import actor, body_refs, new_row, path_row, require_scope
from envelope import created, ok
from errors import fail
from serializers import dump
from store import DB, clock_now, parse_instant, render_instant, set_clock

bp = Blueprint("core", __name__)


# ------------------------------------------------------------------- clock

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    actor(["PlatformAdmin"])
    body = v.read_body()
    fields = [v.S("to_iso8601", required=True)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    instant = parse_instant(body["to_iso8601"])
    if instant is None:
        fail("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 instant.")
    set_clock(instant)
    domain.sweep_recall_postures()
    return ok({"current_utc": render_instant(clock_now())})


# --------------------------------------------------------------- providers

@bp.post("/providers")
def create_provider():
    actor(["PlatformAdmin"])
    body = v.read_body()
    fields = [
        v.S("npi", required=True),
        v.S("full_name", required=True),
        v.S("provider_type", required=True, enum=v.ENUM_PROVIDER_TYPE),
        v.S("state_license"),
        v.S("dme_supplier_number"),
        v.S("status", enum=v.ENUM_PROVIDER_STATUS),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    npi = body["npi"]
    if len(npi) != 10 or not npi.isdigit():
        fail("ERR_VALIDATION", "npi must be exactly ten digits.")
    for existing in DB["providers"].values():
        if existing["npi"] == npi:
            fail("ERR_DUPLICATE_IDENTIFIER", "npi is already registered.")
    row = new_row("providers", {
        "npi": npi,
        "full_name": body["full_name"],
        "provider_type": body["provider_type"],
        "state_license": v.get(body, "state_license", "UNVERIFIED"),
        "dme_supplier_number": body.get("dme_supplier_number"),
        "status": v.get(body, "status", "ACTIVE"),
        "open_efficacy_loop_count": 0,
    })
    return created(dump("provider", row))


@bp.get("/providers/<provider_id>")
def read_provider(provider_id):
    actor(["PlatformAdmin", "SleepPhysician", "Dentist", "LabTechnician",
           "ClinicCoordinator", "BillingSpecialist"])
    row = path_row("provider_id", provider_id)
    return ok(dump("provider", row))


# ------------------------------------------------------------------ payers

@bp.post("/payers")
def create_payer():
    actor(["PlatformAdmin"])
    body = v.read_body()
    fields = [
        v.S("name", required=True),
        v.S("payer_kind", required=True, enum=v.ENUM_PAYER_KIND),
        v.B("prior_auth_required"),
        v.I("useful_lifetime_months"),
        v.N("coinsurance_pct"),
        v.I("appeal_limit"),
        v.N("residual_ahi_target"),
        v.N("pct_reduction_target"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    v.between(body, "coinsurance_pct", 0.0, 1.0)
    row = new_row("payers", {
        "name": body["name"],
        "payer_kind": body["payer_kind"],
        "prior_auth_required": v.get(body, "prior_auth_required", True),
        "useful_lifetime_months": v.get(body, "useful_lifetime_months", 60),
        "coinsurance_pct": v.get(body, "coinsurance_pct", 0.20),
        "appeal_limit": v.get(body, "appeal_limit", 2),
        "residual_ahi_target": v.get(body, "residual_ahi_target", 5.0),
        "pct_reduction_target": v.get(body, "pct_reduction_target", 0.50),
    })
    return created(dump("payer", row))


@bp.get("/payers/<payer_id>")
def read_payer(payer_id):
    actor(["PlatformAdmin", "BillingSpecialist", "ClinicCoordinator", "Dentist"])
    row = path_row("payer_id", payer_id)
    return ok(dump("payer", row))


# ---------------------------------------------------------------- patients

@bp.post("/patients")
def create_patient():
    actor(["ClinicCoordinator", "PlatformAdmin"])
    body = v.read_body()
    body_refs(body, ["medical_payer_id", "dental_payer_id"])
    fields = [
        v.S("mrn", required=True),
        v.S("full_name", required=True),
        v.D("date_of_birth", required=True),
        v.S("medical_payer_id", required=True),
        v.S("dental_payer_id"),
        v.I("deductible_remaining_cents"),
        v.I("epworth_score"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    date_of_birth = v.date_of(body, "date_of_birth")
    v.at_least(body, "deductible_remaining_cents", 0)
    v.between(body, "epworth_score", 0, 24)
    for existing in DB["patients"].values():
        if existing["mrn"] == body["mrn"]:
            fail("ERR_DUPLICATE_IDENTIFIER", "mrn is already registered.")
    row = new_row("patients", {
        "mrn": body["mrn"],
        "full_name": body["full_name"],
        "date_of_birth": date_of_birth,
        "medical_payer_id": body["medical_payer_id"],
        "dental_payer_id": body.get("dental_payer_id"),
        "deductible_remaining_cents": v.get(body, "deductible_remaining_cents", 0),
        "epworth_score": v.get(body, "epworth_score", 0),
        "records_frozen": False,
    })
    return created(dump("patient", row))


@bp.get("/patients/<patient_id>")
def read_patient(patient_id):
    uid, role = actor(["ClinicCoordinator", "PlatformAdmin", "SleepPhysician",
                       "Dentist", "BillingSpecialist", "Patient"])
    row = path_row("patient_id", patient_id)
    require_scope(role, uid, row["id"])
    return ok(dump("patient", row))


@bp.get("/patients")
def list_patients():
    actor(["ClinicCoordinator", "PlatformAdmin", "BillingSpecialist"])
    limit, offset = v.pagination()
    filters = {
        "medical_payer_id": request.args.get("medical_payer_id"),
        "dental_payer_id": request.args.get("dental_payer_id"),
    }
    return domain.paginate("patient", "patients", filters, limit, offset)
