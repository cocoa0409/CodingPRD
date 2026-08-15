"""Routes: logical clock, sites, providers, fee schedules, stipend agreements."""
from flask import Blueprint, request

from store import db, fmt_iso
from errors import ApiError, err_invalid_request
from envelope import ok, ok_list
from validate import auth, get_body, check_body, sort_and_page, apply_filters, parse_iso8601
import services
import serializers as ser

bp = Blueprint("core", __name__, url_prefix="/anesthesia-ops")

GA = ["GroupAdministrator"]
ALL = ["GroupAdministrator", "Scheduler", "AttendingAnesthesiologist", "CRNA",
       "BillingSpecialist", "ComplianceAuditor"]


# ---------------------------------------------------------------- clock ----
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(GA)
    body = get_body()
    check_body(body, {"to_iso8601": {"kind": "iso8601", "req": True}})
    new_clock = parse_iso8601(body["to_iso8601"])
    db.clock = new_clock
    services.sweep_clock(new_clock)
    return ok({"current_utc": fmt_iso(db.clock)})


# ---------------------------------------------------------------- sites ----
@bp.post("/sites")
def create_site():
    auth(GA)
    body = get_body()
    check_body(body, {"name": {"kind": "str", "req": True}})
    rec = db.new_record(name=body["name"], status="ACTIVE")
    db.sites[rec["id"]] = rec
    return ok(ser.site(rec), 201)


@bp.get("/sites/<site_id>")
def get_site(site_id):
    auth(ALL)
    rec = db.sites.get(site_id)
    if rec is None:
        raise ApiError("ERR_SITE_NOT_FOUND", 404, "Site not found")
    return ok(ser.site(rec))


# ------------------------------------------------------------ providers ----
@bp.post("/providers")
def create_provider():
    auth(GA)
    body = get_body()
    check_body(body, {
        "full_name": {"kind": "str", "req": True},
        "provider_type": {"kind": ("enum", ("ANESTHESIOLOGIST", "CRNA", "AA")), "req": True},
        "npi": {"kind": "str", "req": True},
        "credential_expires_on": {"kind": "date", "req": True},
        "dea_expires_on": {"kind": "date", "req": True},
    })
    for p in db.providers.values():
        if p["npi"] == body["npi"]:
            raise ApiError("ERR_DUPLICATE_PROVIDER_NPI", 409, "npi already registered")
    rec = db.new_record(full_name=body["full_name"], provider_type=body["provider_type"],
                        npi=body["npi"], credential_expires_on=body["credential_expires_on"],
                        dea_expires_on=body["dea_expires_on"], status="ACTIVE")
    db.providers[rec["id"]] = rec
    return ok(ser.provider(rec), 201)


@bp.get("/providers")
def list_providers():
    auth(ALL)
    items = apply_filters(db.providers.values(), request.args, ["provider_type", "status"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.provider(r) for r in page], limit, offset, total)


@bp.get("/providers/<provider_id>")
def get_provider(provider_id):
    auth(ALL)
    rec = db.providers.get(provider_id)
    if rec is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "Provider not found")
    return ok(ser.provider(rec))


@bp.patch("/providers/<provider_id>/credentials")
def patch_credentials(provider_id):
    auth(GA)
    body = get_body()
    check_body(body, {
        "credential_expires_on": {"kind": "date", "req": True},
        "dea_expires_on": {"kind": "date", "req": True},
        "expected_provider_version": {"kind": "int", "req": True},
    })
    rec = db.providers.get(provider_id)
    if rec is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "Provider not found")
    if body["expected_provider_version"] != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Provider version is stale")
    rec["credential_expires_on"] = body["credential_expires_on"]
    rec["dea_expires_on"] = body["dea_expires_on"]
    clock_date = db.clock_date_str()
    if rec["status"] == "SUSPENDED" and rec["credential_expires_on"] >= clock_date \
            and rec["dea_expires_on"] >= clock_date:
        rec["status"] = "ACTIVE"
    db.bump(rec)  # single increment covers patch + reinstatement
    services.raise_credential_lapse_findings(rec, rec["credential_expires_on"],
                                             rec["dea_expires_on"])
    return ok(ser.provider(rec))


# --------------------------------------------------------- fee schedules ----
@bp.post("/fee-schedules")
def create_fee_schedule():
    auth(GA)
    body = get_body()
    check_body(body, {
        "procedure_code": {"kind": "str", "req": True},
        "base_units": {"kind": "int", "req": True, "min": 1, "max": 50},
        "contracted_max_cents": {"kind": "int", "req": True},
        "description": {"kind": "str", "req": False},
    })
    for f in db.fee_schedules.values():
        if f["procedure_code"] == body["procedure_code"]:
            raise ApiError("ERR_DUPLICATE_PROCEDURE_CODE", 409, "procedure_code already exists")
    rec = db.new_record(procedure_code=body["procedure_code"], base_units=body["base_units"],
                        contracted_max_cents=body["contracted_max_cents"],
                        description=body.get("description", ""))
    db.fee_schedules[rec["id"]] = rec
    return ok(ser.fee_schedule(rec), 201)


@bp.get("/fee-schedules/<fs_id>")
def get_fee_schedule(fs_id):
    auth(ALL)
    rec = db.fee_schedules.get(fs_id)
    if rec is None:
        raise ApiError("ERR_FEE_SCHEDULE_NOT_FOUND", 404, "Fee schedule not found")
    return ok(ser.fee_schedule(rec))


@bp.patch("/fee-schedules/<fs_id>")
def patch_fee_schedule(fs_id):
    auth(GA)
    body = get_body()
    check_body(body, {
        "base_units": {"kind": "int", "req": False, "min": 1, "max": 50},
        "contracted_max_cents": {"kind": "int", "req": False},
    })
    rec = db.fee_schedules.get(fs_id)
    if rec is None:
        raise ApiError("ERR_FEE_SCHEDULE_NOT_FOUND", 404, "Fee schedule not found")
    if "base_units" in body:
        rec["base_units"] = body["base_units"]
    if "contracted_max_cents" in body:
        rec["contracted_max_cents"] = body["contracted_max_cents"]
    db.bump(rec)
    return ok(ser.fee_schedule(rec))


# ------------------------------------------------------ stipend agreements ----
@bp.post("/stipend-agreements")
def create_agreement():
    auth(GA)
    body = get_body()
    cents = {"kind": "int", "req": True, "min": 0}
    check_body(body, {
        "site_id": {"kind": "str", "req": True},
        "effective_from": {"kind": "date", "req": True},
        "effective_to": {"kind": "date", "req": True},
        "call_stipend_cents": dict(cents),
        "late_stay_rate_cents_per_minute": dict(cents),
        "standby_full_cents": dict(cents),
        "standby_partial_cents": dict(cents),
    })
    if body["effective_to"] < body["effective_from"]:
        raise err_invalid_request("effective_to must not precede effective_from")
    site = db.sites.get(body["site_id"])
    if site is None:
        raise ApiError("ERR_SITE_NOT_FOUND", 404, "Site not found")
    for ag in db.agreements.values():
        if ag["site_id"] == body["site_id"] and \
                body["effective_from"] <= ag["effective_to"] and \
                ag["effective_from"] <= body["effective_to"]:
            raise ApiError("ERR_AGREEMENT_WINDOW_OVERLAP", 409,
                           "Agreement window overlaps another agreement for this site")
    rec = db.new_record(
        site_id=body["site_id"], effective_from=body["effective_from"],
        effective_to=body["effective_to"], call_stipend_cents=body["call_stipend_cents"],
        late_stay_rate_cents_per_minute=body["late_stay_rate_cents_per_minute"],
        standby_full_cents=body["standby_full_cents"],
        standby_partial_cents=body["standby_partial_cents"])
    db.agreements[rec["id"]] = rec
    return ok(ser.agreement(rec), 201)


@bp.get("/stipend-agreements")
def list_agreements():
    auth(ALL)
    items = apply_filters(db.agreements.values(), request.args, ["site_id"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.agreement(r) for r in page], limit, offset, total)


@bp.get("/stipend-agreements/<ag_id>")
def get_agreement(ag_id):
    auth(ALL)
    rec = db.agreements.get(ag_id)
    if rec is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Stipend agreement not found")
    return ok(ser.agreement(rec))
