"""Investigational Drug Randomization API — Flask entry point.

Implements PRD.md exactly. All state in-memory (db.store). Logical clock starts at
2026-08-01T00:00:00Z and advances only via POST /api/_clock/set_current_utc.
"""

import os
from datetime import timedelta

from flask import Flask

import db as dbmod
import errors as E
import middleware as M
import response as R
import services as S
from db import store, new_id, clock_iso, stamp_created, touch

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(E.ApiError)
def handle_api_error(err):
    return R.error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(_):
    return R.error_response("ERR_NOT_FOUND", 404, "Route not found")


@app.errorhandler(405)
def handle_405(_):
    return R.error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, E.ApiError):
        return R.error_response(err.error_id, err.http_status, err.message)
    return R.error_response("ERR_INVALID_REQUEST", 400, str(err))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_study_or_404(study_id):
    s = store.studies.get(study_id)
    if s is None:
        raise E.study_not_found()
    return s


def get_site_or_404(site_id):
    s = store.sites.get(site_id)
    if s is None:
        raise E.site_not_found()
    return s


def get_kit_or_404(kit_id):
    k = store.kits.get(kit_id)
    if k is None:
        raise E.kit_not_found()
    return k


def get_subject_or_404(subject_id):
    s = store.subjects.get(subject_id)
    if s is None:
        raise E.subject_not_found()
    return s


def get_lot_or_404(lot_id):
    l = store.lots.get(lot_id)
    if l is None:
        raise E.not_found("Lot not found")
    return l


def get_staff_or_404(staff_id):
    s = store.staff.get(staff_id)
    if s is None:
        raise E.not_found("Staff not found")
    return s


def get_slot_or_404(slot_id):
    s = store.slots.get(slot_id)
    if s is None:
        raise E.not_found("Randomization slot not found")
    return s


def get_excursion_or_404(exc_id):
    e = store.excursions.get(exc_id)
    if e is None:
        raise E.not_found("Excursion not found")
    return e


def get_log_or_404(log_id):
    l = store.temperature_logs.get(log_id)
    if l is None:
        raise E.not_found("Temperature log not found")
    return l


def get_dispensing_or_404(did):
    d = store.dispensing_records.get(did)
    if d is None:
        raise E.not_found("Dispensing record not found")
    return d


def get_return_or_404(rid):
    r = store.returns.get(rid)
    if r is None:
        raise E.not_found("Drug return not found")
    return r


def get_destruction_or_404(did):
    d = store.destruction_records.get(did)
    if d is None:
        raise E.not_found("Destruction record not found")
    return d


def get_unblinding_or_404(uid):
    u = store.unblinding_requests.get(uid)
    if u is None:
        raise E.not_found("Unblinding request not found")
    return u


def get_visit_or_404(vid):
    v = store.monitor_visits.get(vid)
    if v is None:
        raise E.not_found("Monitor visit not found")
    return v


def get_fee_schedule_or_404(fid):
    f = store.fee_schedules.get(fid)
    if f is None:
        raise E.not_found("Fee schedule not found")
    return f


def lot_expired(lot):
    expiry = S._parse_stored(lot["expiry_date"]) if isinstance(lot["expiry_date"], str) else lot["expiry_date"]
    return store.clock >= expiry


# ===========================================================================
# Clock + ops
# ===========================================================================

@app.post("/api/_clock/set_current_utc")
def clock_set():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    to_dt = M.req_datetime(body, "to_iso8601")
    store.clock = to_dt
    return R.success_object({"current_utc": clock_iso()})


@app.post("/api/_ops/expiry_sweep")
def expiry_sweep_ep():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    counters = S.expiry_sweep()
    return R.success_object(counters)


# ===========================================================================
# Studies
# ===========================================================================

ALL_ROLES = {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor", "Investigator"}
PHASES = {"PHASE_I", "PHASE_II", "PHASE_III", "PHASE_IV"}
BLINDING_MODELS = {"DOUBLE_BLIND", "SINGLE_BLIND", "OPEN_LABEL"}


@app.post("/api/studies")
def create_study():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    protocol_number = M.req_string(body, "protocol_number")
    title = M.req_string(body, "title")
    phase = M.req_enum(body, "phase", PHASES)
    blinding_model = M.req_enum(body, "blinding_model", BLINDING_MODELS)
    max_dose = M.req_int(body, "max_dose_per_visit_mg")
    threshold = body.get("unblinding_suspension_threshold_pct", 10)
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        raise E.invalid_request("unblinding_suspension_threshold_pct must be an integer")

    # uniqueness (priority 9)
    for s in store.studies.values():
        if s["protocol_number"] == protocol_number:
            raise E.duplicate_protocol_number()

    study = {
        "id": new_id(),
        "protocol_number": protocol_number,
        "title": title,
        "phase": phase,
        "blinding_model": blinding_model,
        "status": "DRAFT",
        "max_dose_per_visit_mg": max_dose,
        "unblinding_suspension_threshold_pct": threshold,
        "randomized_subject_count": 0,
        "unblinded_subject_count": 0,
    }
    stamp_created(study)
    store.studies[study["id"]] = study
    return R.success_object(S.serialize(study, "study", ctx), 201)


@app.get("/api/studies")
def list_studies():
    ctx = M.require_auth()
    M.require_role(ctx, ALL_ROLES)
    from flask import request
    items = list(store.studies.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "study", ctx), limit, offset, total)


@app.get("/api/studies/<sid>")
def get_study(sid):
    ctx = M.require_auth()
    M.require_role(ctx, ALL_ROLES)
    study = get_study_or_404(sid)
    return R.success_object(S.serialize(study, "study", ctx))


@app.post("/api/studies/<sid>/transition")
def transition_study(sid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    to = M.req_enum(body, "to", {"ACTIVE", "SUSPENDED", "CLOSED"})
    study = get_study_or_404(sid)

    if study["status"] in S.STUDY_TERMINAL:
        raise E.already_terminal("Study is CLOSED")

    current = study["status"]
    allowed = {
        ("DRAFT", "ACTIVE"),
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "CLOSED"),
        ("SUSPENDED", "CLOSED"),
    }
    if (current, to) not in allowed:
        raise E.invalid_state(f"Study cannot transition {current} -> {to}")

    if to == "ACTIVE":
        approved = any(f for f in store.fee_schedules.values()
                       if f["study_id"] == study["id"] and f["status"] == "APPROVED")
        if not approved:
            raise E.no_approved_fee_schedule()

    study["status"] = to
    if to == "SUSPENDED":
        for site in store.sites.values():
            if site["study_id"] == study["id"] and site["status"] == "ACTIVE":
                site["status"] = "ON_HOLD"
                touch(site)
    touch(study)
    return R.success_object(S.serialize(study, "study", ctx))


# ===========================================================================
# Sites
# ===========================================================================

@app.post("/api/sites")
def create_site():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    study_id = M.req_string(body, "study_id")
    site_number = M.req_string(body, "site_number")
    name = M.req_string(body, "name")
    pi = M.req_string(body, "principal_investigator")
    get_study_or_404(study_id)
    for s in store.sites.values():
        if s["study_id"] == study_id and s["site_number"] == site_number:
            raise E.invalid_request("site_number already exists in this study")
    site = {
        "id": new_id(),
        "study_id": study_id,
        "site_number": site_number,
        "name": name,
        "principal_investigator": pi,
        "status": "INITIATED",
        "activated_at": None,
    }
    stamp_created(site)
    store.sites[site["id"]] = site
    return R.success_object(S.serialize(site, "site", ctx), 201)


@app.get("/api/sites")
def list_sites():
    ctx = M.require_auth()
    M.require_role(ctx, ALL_ROLES)
    from flask import request
    items = list(store.sites.values())
    study_id = request.args.get("study_id")
    status = request.args.get("status")
    if study_id is not None:
        items = [s for s in items if s["study_id"] == study_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "site", ctx), limit, offset, total)


@app.get("/api/sites/<sid>")
def get_site(sid):
    ctx = M.require_auth()
    M.require_role(ctx, ALL_ROLES)
    site = get_site_or_404(sid)
    return R.success_object(S.serialize(site, "site", ctx))


@app.post("/api/sites/<sid>/transition")
def transition_site(sid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    to = M.req_enum(body, "to", {"ACTIVE", "ON_HOLD", "CLOSED"})
    site = get_site_or_404(sid)
    if site["status"] in S.SITE_TERMINAL:
        raise E.already_terminal("Site is CLOSED")
    current = site["status"]
    allowed = {
        ("INITIATED", "ACTIVE"),
        ("ACTIVE", "ON_HOLD"),
        ("ON_HOLD", "ACTIVE"),
        ("ACTIVE", "CLOSED"),
        ("ON_HOLD", "CLOSED"),
    }
    if (current, to) not in allowed:
        raise E.invalid_state(f"Site cannot transition {current} -> {to}")
    if to == "ACTIVE":
        study = get_study_or_404(site["study_id"])
        if study["status"] != "ACTIVE":
            raise E.study_not_active()
        if site["activated_at"] is None:
            site["activated_at"] = clock_iso()
    site["status"] = to
    touch(site)
    return R.success_object(S.serialize(site, "site", ctx))


# ===========================================================================
# Staff
# ===========================================================================

@app.post("/api/staff")
def create_staff():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    site_id = M.req_string(body, "site_id")
    full_name = M.req_string(body, "full_name")
    license_number = M.req_string(body, "license_number")
    is_unblinded = M.opt_bool(body, "is_unblinded", False)
    get_site_or_404(site_id)
    for s in store.staff.values():
        if s["license_number"] == license_number:
            raise E.invalid_request("license_number already exists")
    staff = {
        "id": new_id(),
        "site_id": site_id,
        "full_name": full_name,
        "license_number": license_number,
        "is_unblinded": is_unblinded,
    }
    stamp_created(staff)
    store.staff[staff["id"]] = staff
    return R.success_object(S.serialize(staff, "staff", ctx), 201)


@app.get("/api/staff")
def list_staff():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist"})
    from flask import request
    items = list(store.staff.values())
    site_id = request.args.get("site_id")
    is_unblinded = request.args.get("is_unblinded")
    if site_id is not None:
        items = [s for s in items if s["site_id"] == site_id]
    if is_unblinded is not None:
        v = is_unblinded.lower()
        if v not in ("true", "false"):
            raise E.invalid_request("is_unblinded must be true or false")
        flag = (v == "true")
        items = [s for s in items if s["is_unblinded"] == flag]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "staff", ctx), limit, offset, total)


@app.get("/api/staff/<sid>")
def get_staff(sid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist"})
    staff = get_staff_or_404(sid)
    return R.success_object(S.serialize(staff, "staff", ctx))


# ===========================================================================
# Lots
# ===========================================================================

@app.post("/api/lots")
def create_lot():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    study_id = M.req_string(body, "study_id")
    lot_number = M.req_string(body, "lot_number")
    product_name = M.req_string(body, "product_name")
    strength_mg = M.req_int(body, "strength_mg")
    dosage_form = M.req_string(body, "dosage_form")
    expiry_date = M.req_datetime(body, "expiry_date")
    tmin = M.req_number(body, "storage_temp_min_celsius")
    tmax = M.req_number(body, "storage_temp_max_celsius")
    budget = M.req_int(body, "stability_budget_minutes")
    get_study_or_404(study_id)
    for l in store.lots.values():
        if l["study_id"] == study_id and l["lot_number"] == lot_number:
            raise E.invalid_request("lot_number already exists in this study")
    lot = {
        "id": new_id(),
        "study_id": study_id,
        "lot_number": lot_number,
        "product_name": product_name,
        "strength_mg": strength_mg,
        "dosage_form": dosage_form,
        "expiry_date": _fmt_dt(expiry_date),
        "storage_temp_min_celsius": tmin,
        "storage_temp_max_celsius": tmax,
        "stability_budget_minutes": budget,
        "stability_minutes_consumed": 0,
        "status": "ACTIVE",
    }
    stamp_created(lot)
    store.lots[lot["id"]] = lot
    return R.success_object(S.serialize(lot, "lot", ctx), 201)


def _fmt_dt(dt):
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/api/lots")
def list_lots():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    from flask import request
    items = list(store.lots.values())
    study_id = request.args.get("study_id")
    status = request.args.get("status")
    if study_id is not None:
        items = [l for l in items if l["study_id"] == study_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "lot", ctx), limit, offset, total)


@app.get("/api/lots/<lid>")
def get_lot(lid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    lot = get_lot_or_404(lid)
    return R.success_object(S.serialize(lot, "lot", ctx))


# ===========================================================================
# Shipments + Kits
# ===========================================================================

@app.post("/api/shipments")
def create_shipment():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    lot_id = M.req_string(body, "lot_id")
    site_id = M.req_string(body, "site_id")
    kit_numbers = body.get("kit_numbers")
    if not isinstance(kit_numbers, list) or len(kit_numbers) == 0:
        raise E.invalid_request("kit_numbers must be a non-empty array")
    for kn in kit_numbers:
        if not isinstance(kn, str) or kn == "":
            raise E.invalid_request("kit_numbers entries must be non-empty strings")
    units_per_kit = M.req_int(body, "units_per_kit")
    lot = get_lot_or_404(lot_id)
    get_site_or_404(site_id)

    # All-or-nothing duplicate check: within payload AND against existing kits in the study
    seen = set()
    payload_set = set()
    for kn in kit_numbers:
        if kn in payload_set:
            raise E.duplicate_kit_number()
        payload_set.add(kn)
    existing = {k["kit_number"] for k in store.kits.values()
                if store.lots.get(k["lot_id"], {}).get("study_id") == lot["study_id"]}
    for kn in kit_numbers:
        if kn in existing:
            raise E.duplicate_kit_number()

    created = []
    for kn in kit_numbers:
        kit = {
            "id": new_id(),
            "lot_id": lot_id,
            "site_id": site_id,
            "kit_number": kn,
            "status": "IN_TRANSIT",
            "pre_quarantine_status": None,
            "excursion_id": None,
            "allocated_subject_id": None,
            "units_received": units_per_kit,
            "units_dispensed": 0,
            "units_returned": 0,
            "units_destroyed": 0,
            "units_lost": 0,
            "on_hand_units": units_per_kit,
        }
        stamp_created(kit)
        store.kits[kit["id"]] = kit
        created.append(kit)
    return R.success_list(S.serialize_list(created, "kit", ctx), len(created), 0, len(created), 201)


@app.get("/api/kits")
def list_kits():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    from flask import request
    items = list(store.kits.values())
    for param in ("lot_id", "site_id", "status", "allocated_subject_id", "excursion_id"):
        v = request.args.get(param)
        if v is not None:
            items = [k for k in items if str(k.get(param)) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "kit", ctx), limit, offset, total)


@app.get("/api/kits/<kid>")
def get_kit(kid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    kit = get_kit_or_404(kid)
    return R.success_object(S.serialize(kit, "kit", ctx))


@app.post("/api/kits/<kid>/receive")
def receive_kit(kid):
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    body = M.body()
    temp = M.req_number(body, "storage_temp_celsius")
    kit = get_kit_or_404(kid)
    if kit["status"] in S.KIT_TERMINAL:
        raise E.already_terminal("Kit is DESTROYED")
    site = get_site_or_404(kit["site_id"])
    if site["status"] == "CLOSED":
        raise E.site_not_active("Site is CLOSED")
    if kit["status"] != "IN_TRANSIT":
        raise E.invalid_state("Kit is not IN_TRANSIT")

    lot = get_lot_or_404(kit["lot_id"])
    in_range = lot["storage_temp_min_celsius"] <= temp <= lot["storage_temp_max_celsius"]
    # Every receipt creates a TemperatureLog with source MANUAL
    log, excursion = S.record_temperature(kit["site_id"], temp, "MANUAL")

    if in_range:
        kit["status"] = "QUARANTINED_RECEIPT"
    else:
        kit["status"] = "QUARANTINED_EXCURSION"
        kit["pre_quarantine_status"] = "QUARANTINED_RECEIPT"
        if excursion is not None:
            kit["excursion_id"] = excursion["id"]
    touch(kit)
    return R.success_object(S.serialize(kit, "kit", ctx))


@app.post("/api/kits/<kid>/release")
def release_kit(kid):
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    kit = get_kit_or_404(kid)
    if kit["status"] in S.KIT_TERMINAL:
        raise E.already_terminal("Kit is DESTROYED")
    if kit["status"] != "QUARANTINED_RECEIPT":
        raise E.kit_not_releasable()
    lot = get_lot_or_404(kit["lot_id"])
    if lot["status"] == "EXPIRED":
        raise E.lot_expired()
    if lot["status"] != "ACTIVE":
        raise E.invalid_state("Lot is not ACTIVE")
    if lot_expired(lot):
        raise E.lot_expired()
    if lot["stability_minutes_consumed"] >= lot["stability_budget_minutes"]:
        raise E.lot_stability_exhausted()
    study = get_study_or_404(lot["study_id"])
    if study["status"] != "ACTIVE":
        raise E.study_not_active()
    kit["status"] = "AVAILABLE"
    touch(kit)
    return R.success_object(S.serialize(kit, "kit", ctx))


# ===========================================================================
# Temperature logs & excursions
# ===========================================================================

@app.post("/api/temperature-logs")
def create_temp_log():
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    body = M.body()
    site_id = M.req_string(body, "site_id")
    celsius = M.req_number(body, "celsius")
    source = M.req_enum(body, "source", {"MANUAL", "DATALOGGER"})
    get_site_or_404(site_id)
    log, _ = S.record_temperature(site_id, celsius, source)
    return R.success_object(S.serialize(log, "temperature_log", ctx), 201)


@app.get("/api/temperature-logs")
def list_temp_logs():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    from flask import request
    items = list(store.temperature_logs.values())
    site_id = request.args.get("site_id")
    excursion_id = request.args.get("excursion_id")
    if site_id is not None:
        items = [l for l in items if l["site_id"] == site_id]
    if excursion_id is not None:
        items = [l for l in items if l.get("excursion_id") == excursion_id]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "temperature_log", ctx), limit, offset, total)


@app.get("/api/temperature-logs/<lid>")
def get_temp_log(lid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    log = get_log_or_404(lid)
    return R.success_object(S.serialize(log, "temperature_log", ctx))


@app.get("/api/temperature-excursions")
def list_excursions():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    from flask import request
    items = list(store.excursions.values())
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    if site_id is not None:
        items = [x for x in items if x["site_id"] == site_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "excursion", ctx), limit, offset, total)


@app.get("/api/temperature-excursions/<eid>")
def get_excursion(eid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    ex = get_excursion_or_404(eid)
    return R.success_object(S.serialize(ex, "excursion", ctx))


@app.post("/api/temperature-excursions/<eid>/assess")
def assess_excursion_ep(eid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    outcome = M.req_enum(body, "outcome", {"ACCEPTABLE", "UNACCEPTABLE", "VOID"})
    rationale = body.get("resolution_rationale")
    if outcome in ("ACCEPTABLE", "UNACCEPTABLE"):
        rationale = M.req_string(body, "resolution_rationale")
    ex = get_excursion_or_404(eid)
    S.assess_excursion(ex, outcome, rationale)
    return R.success_object(S.serialize(ex, "excursion", ctx))


# ===========================================================================
# Subjects & randomization
# ===========================================================================

STRATA = {"STANDARD", "HIGH_RISK"}


@app.post("/api/subjects")
def create_subject():
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    body = M.body()
    site_id = M.req_string(body, "site_id")
    subject_number = M.req_string(body, "subject_number")
    stratum = M.req_enum(body, "stratum", STRATA)
    get_site_or_404(site_id)
    for s in store.subjects.values():
        if s["site_id"] == site_id and s["subject_number"] == subject_number:
            raise E.invalid_request("subject_number already exists at this site")
    subject = {
        "id": new_id(),
        "site_id": site_id,
        "subject_number": subject_number,
        "stratum": stratum,
        "enrollment_status": "SCREENING",
        "blinded_status": "BLINDED",
        "rescreen_count": 0,
        "randomized_at": None,
    }
    stamp_created(subject)
    store.subjects[subject["id"]] = subject
    return R.success_object(S.serialize(subject, "subject", ctx), 201)


@app.get("/api/subjects")
def list_subjects():
    ctx = M.require_auth()
    M.require_role(ctx, ALL_ROLES)
    from flask import request
    items = list(store.subjects.values())
    for param in ("site_id", "enrollment_status", "blinded_status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(param) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "subject", ctx), limit, offset, total)


@app.get("/api/subjects/<sid>")
def get_subject(sid):
    ctx = M.require_auth()
    M.require_role(ctx, ALL_ROLES)
    subject = get_subject_or_404(sid)
    return R.success_object(S.serialize(subject, "subject", ctx))


@app.post("/api/subjects/<sid>/transition")
def transition_subject(sid):
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    body = M.body()
    to = M.req_enum(body, "to", {"SCREEN_FAILED", "SCREENING", "COMPLETED", "WITHDRAWN"})
    # reason optional; if present must be string
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        raise E.invalid_request("reason must be a string")
    subject = get_subject_or_404(sid)

    if subject["enrollment_status"] in S.SUBJECT_TERMINAL:
        raise E.already_terminal("Subject enrollment is terminal")

    current = subject["enrollment_status"]
    allowed = {
        ("SCREENING", "SCREEN_FAILED"),
        ("SCREEN_FAILED", "SCREENING"),
        ("RANDOMIZED", "COMPLETED"),
        ("RANDOMIZED", "WITHDRAWN"),
    }
    if (current, to) not in allowed:
        raise E.invalid_state(f"Subject cannot transition {current} -> {to}")

    if to == "SCREENING" and current == "SCREEN_FAILED":
        if subject["rescreen_count"] >= 1:
            raise E.rescreen_limit()
        subject["rescreen_count"] += 1

    if to in ("COMPLETED", "WITHDRAWN"):
        active = any(d for d in store.dispensing_records.values()
                     if d["subject_id"] == subject["id"] and d["status"] == "ACTIVE")
        if active:
            raise E.active_dispensing_exists()

    subject["enrollment_status"] = to
    touch(subject)
    return R.success_object(S.serialize(subject, "subject", ctx))


def _select_slot(study_id, stratum):
    candidates = [s for s in store.slots.values()
                  if s["study_id"] == study_id and s["stratum"] == stratum and s["status"] == "UNASSIGNED"]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["sequence_number"], s.get("created_at") or "", s["id"]))
    return candidates[0]


def _resolve_slot_kit_at_site(slot, site_id):
    for k in store.kits.values():
        if k["kit_number"] == slot["kit_number"] and k["site_id"] == site_id:
            return k
    return None


def _do_allocate(subject):
    """Shared slot-selection + kit-allocation for randomize and allocate-kit."""
    site = get_site_or_404(subject["site_id"])
    study = get_study_or_404(site["study_id"])

    if site["status"] != "ACTIVE":
        raise E.site_not_active()
    if study["status"] != "ACTIVE":
        raise E.study_not_active()

    slot = _select_slot(study["id"], subject["stratum"])
    if slot is None:
        raise E.no_randomization_slot()

    kit = _resolve_slot_kit_at_site(slot, subject["site_id"])
    if kit is None:
        raise E.slot_kit_unavailable()
    if kit["status"] == "QUARANTINED_EXCURSION":
        raise E.kit_quarantined_excursion()
    if kit["status"] != "AVAILABLE":
        raise E.slot_kit_unavailable()

    lot = get_lot_or_404(kit["lot_id"])
    if lot_expired(lot):
        raise E.lot_expired()

    slot["status"] = "ASSIGNED"
    slot["assigned_subject_id"] = subject["id"]
    touch(slot)

    kit["status"] = "ALLOCATED"
    kit["allocated_subject_id"] = subject["id"]
    touch(kit)
    return study, slot, kit


@app.post("/api/subjects/<sid>/randomize")
def randomize_subject(sid):
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    subject = get_subject_or_404(sid)
    if subject["enrollment_status"] in S.SUBJECT_TERMINAL:
        raise E.already_terminal("Subject enrollment is terminal")
    if subject["enrollment_status"] != "SCREENING":
        raise E.subject_not_randomizable()

    study, slot, kit = _do_allocate(subject)
    subject["enrollment_status"] = "RANDOMIZED"
    subject["randomized_at"] = clock_iso()
    touch(subject)

    study["randomized_subject_count"] = study.get("randomized_subject_count", 0) + 1
    touch(study)
    return R.success_object(S.serialize(subject, "subject", ctx))


@app.post("/api/subjects/<sid>/allocate-kit")
def allocate_kit(sid):
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    subject = get_subject_or_404(sid)
    if subject["enrollment_status"] in S.SUBJECT_TERMINAL:
        raise E.already_terminal("Subject enrollment is terminal")
    if subject["enrollment_status"] != "RANDOMIZED":
        raise E.subject_not_randomized()
    _do_allocate(subject)
    return R.success_object(S.serialize(subject, "subject", ctx))


@app.post("/api/studies/<sid>/randomization-slots/replace")
def replace_slots(sid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    slots = body.get("slots")
    if not isinstance(slots, list):
        raise E.invalid_request("slots must be an array")
    if "expected_study_version" not in body:
        raise E.invalid_request("Missing required field: expected_study_version")
    expected = body["expected_study_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise E.invalid_request("expected_study_version must be an integer")

    # validate payload schema before existence/state (schema is priority 3)
    parsed = []
    for entry in slots:
        if not isinstance(entry, dict):
            raise E.invalid_request("slot entries must be objects")
        seq = entry.get("sequence_number")
        if isinstance(seq, bool) or not isinstance(seq, int):
            raise E.invalid_request("slot.sequence_number must be an integer")
        stratum = entry.get("stratum")
        if stratum not in STRATA:
            raise E.invalid_request("slot.stratum must be STANDARD or HIGH_RISK")
        kit_number = entry.get("kit_number")
        if not isinstance(kit_number, str) or kit_number == "":
            raise E.invalid_request("slot.kit_number must be a non-empty string")
        arm_code = entry.get("arm_code")
        if not isinstance(arm_code, str) or arm_code == "":
            raise E.invalid_request("slot.arm_code must be a non-empty string")
        parsed.append({"sequence_number": seq, "stratum": stratum,
                       "kit_number": kit_number, "arm_code": arm_code})

    study = get_study_or_404(sid)

    if study["status"] in S.STUDY_TERMINAL:
        raise E.already_terminal("Study is CLOSED")

    # OCC check
    if expected != study["version"]:
        raise E.stale_version()

    # retire UNASSIGNED slots
    for s in list(store.slots.values()):
        if s["study_id"] == study["id"] and s["status"] == "UNASSIGNED":
            s["status"] = "RELEASED"
            touch(s)

    created = []
    for p in parsed:
        slot = {
            "id": new_id(),
            "study_id": study["id"],
            "sequence_number": p["sequence_number"],
            "stratum": p["stratum"],
            "kit_number": p["kit_number"],
            "arm_code": p["arm_code"],
            "status": "UNASSIGNED",
            "assigned_subject_id": None,
        }
        stamp_created(slot)
        store.slots[slot["id"]] = slot
        created.append(slot)

    touch(study)
    return R.success_list(S.serialize_list(created, "slot", ctx), len(created), 0, len(created))


@app.get("/api/randomization-slots")
def list_slots():
    ctx = M.require_auth()
    M.require_role(ctx, ALL_ROLES)
    from flask import request
    items = list(store.slots.values())
    for param in ("study_id", "status", "stratum", "assigned_subject_id", "kit_number"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if str(s.get(param)) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "slot", ctx), limit, offset, total)


@app.get("/api/randomization-slots/<sid>")
def get_slot(sid):
    ctx = M.require_auth()
    M.require_role(ctx, ALL_ROLES)
    slot = get_slot_or_404(sid)
    return R.success_object(S.serialize(slot, "slot", ctx))


# ===========================================================================
# Dispensing & returns
# ===========================================================================

@app.post("/api/dispensing-records")
def create_dispensing():
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    body = M.body()
    subject_id = M.req_string(body, "subject_id")
    kit_id = M.req_string(body, "kit_id")
    visit_number = M.req_int(body, "visit_number")
    quantity_dispensed = M.req_int(body, "quantity_dispensed")
    if quantity_dispensed < 1:
        raise E.invalid_request("quantity_dispensed must be >= 1")

    subject = get_subject_or_404(subject_id)
    kit = get_kit_or_404(kit_id)

    if subject["enrollment_status"] in S.SUBJECT_TERMINAL:
        raise E.already_terminal("Subject enrollment is terminal")
    if subject["enrollment_status"] != "RANDOMIZED":
        raise E.subject_not_randomized()

    site = get_site_or_404(subject["site_id"])
    study = get_study_or_404(site["study_id"])
    if study["status"] != "ACTIVE":
        raise E.study_not_active()

    if kit["status"] in S.KIT_TERMINAL:
        raise E.already_terminal("Kit is DESTROYED")
    if kit["status"] == "QUARANTINED_EXCURSION":
        raise E.kit_quarantined_excursion()
    if kit["status"] != "ALLOCATED" or kit.get("allocated_subject_id") != subject["id"]:
        raise E.kit_not_dispensable()

    lot = get_lot_or_404(kit["lot_id"])
    if lot_expired(lot):
        raise E.lot_expired()

    # dose cap
    if quantity_dispensed * lot["strength_mg"] > study["max_dose_per_visit_mg"]:
        raise E.dose_exceeds()

    # visit sequence (priority 9)
    subject_records = [d for d in store.dispensing_records.values() if d["subject_id"] == subject["id"]]
    expected_visit = len(subject_records) + 1
    if visit_number != expected_visit:
        raise E.visit_out_of_sequence()

    # visit window: [randomized_at + 28*(visit_number-1) - 3d, +3d]
    randomized_at = S._parse_stored(subject["randomized_at"])
    nominal = randomized_at + timedelta(days=28 * (visit_number - 1))
    window_start = nominal - timedelta(days=3)
    window_end = nominal + timedelta(days=3)
    now = store.clock
    if now < window_start or now > window_end:
        raise E.visit_window_violation()

    record = {
        "id": new_id(),
        "subject_id": subject_id,
        "kit_id": kit_id,
        "visit_number": visit_number,
        "quantity_dispensed": quantity_dispensed,
        "dose_mg": quantity_dispensed * lot["strength_mg"],
        "dispensed_at": clock_iso(),
        "status": "ACTIVE",
    }
    stamp_created(record)
    store.dispensing_records[record["id"]] = record

    kit["status"] = "DISPENSED"
    kit["units_dispensed"] += quantity_dispensed
    S.recompute_kit_balance(kit)
    touch(kit)

    return R.success_object(S.serialize(record, "dispensing", ctx), 201)


@app.get("/api/dispensing-records")
def list_dispensing():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    from flask import request
    items = list(store.dispensing_records.values())
    for param in ("subject_id", "kit_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d.get(param) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "dispensing", ctx), limit, offset, total)


@app.get("/api/dispensing-records/<did>")
def get_dispensing(did):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    record = get_dispensing_or_404(did)
    return R.success_object(S.serialize(record, "dispensing", ctx))


@app.post("/api/returns")
def create_return():
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    body = M.body()
    dispensing_record_id = M.req_string(body, "dispensing_record_id")
    quantity_returned = M.req_int(body, "quantity_returned")

    record = get_dispensing_or_404(dispensing_record_id)

    # one return per dispensing record
    for r in store.returns.values():
        if r["dispensing_record_id"] == dispensing_record_id:
            raise E.quantity_mismatch("A return already exists for this dispensing record")

    if record["status"] != "ACTIVE":
        raise E.invalid_state("Dispensing record is not ACTIVE")

    if quantity_returned < 1 or quantity_returned > record["quantity_dispensed"]:
        raise E.quantity_mismatch("quantity_returned out of range")

    kit = get_kit_or_404(record["kit_id"])

    ret = {
        "id": new_id(),
        "dispensing_record_id": dispensing_record_id,
        "quantity_returned": quantity_returned,
        "status": "RECORDED",
        "recorded_by_staff_id": ctx.user_id,
        "verified_by_staff_id": None,
    }
    stamp_created(ret)
    store.returns[ret["id"]] = ret

    kit["status"] = "RETURNED"
    kit["units_returned"] += quantity_returned
    S.recompute_kit_balance(kit)
    touch(kit)

    record["status"] = "RETURNED"
    touch(record)

    return R.success_object(S.serialize(ret, "return", ctx), 201)


@app.get("/api/returns")
def list_returns():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    from flask import request
    items = list(store.returns.values())
    for param in ("dispensing_record_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "return", ctx), limit, offset, total)


@app.get("/api/returns/<rid>")
def get_return(rid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    ret = get_return_or_404(rid)
    return R.success_object(S.serialize(ret, "return", ctx))


@app.post("/api/returns/<rid>/verify")
def verify_return(rid):
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    ret = get_return_or_404(rid)
    if ret["status"] == "VERIFIED":
        raise E.already_terminal("Return already VERIFIED")
    if ret["status"] != "RECORDED":
        raise E.invalid_state("Return is not RECORDED")
    if ctx.user_id == ret["recorded_by_staff_id"]:
        raise E.segregation("Verifier must differ from recorder")
    ret["status"] = "VERIFIED"
    ret["verified_by_staff_id"] = ctx.user_id
    touch(ret)
    return R.success_object(S.serialize(ret, "return", ctx))


# ===========================================================================
# Destruction
# ===========================================================================

DESTRUCTION_METHODS = {"INCINERATION", "CHEMICAL_NEUTRALIZATION", "RETURN_TO_SPONSOR"}


@app.post("/api/destruction-records")
def create_destruction():
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    body = M.body()
    kit_id = M.req_string(body, "kit_id")
    site_id = M.req_string(body, "site_id")
    method = M.req_enum(body, "method", DESTRUCTION_METHODS)
    ws = M.req_datetime(body, "facility_window_start")
    we = M.req_datetime(body, "facility_window_end")
    quantity_destroyed = M.req_int(body, "quantity_destroyed")
    witness_staff_id = M.req_string(body, "witness_staff_id")

    if we <= ws:
        raise E.invalid_request("facility_window_end must be after facility_window_start")

    kit = get_kit_or_404(kit_id)
    get_site_or_404(site_id)
    witness = get_staff_or_404(witness_staff_id)

    if kit["status"] in S.KIT_TERMINAL:
        raise E.already_terminal("Kit is DESTROYED")
    if kit["status"] not in ("RETURNED", "EXPIRED"):
        raise E.invalid_state("Kit must be RETURNED or EXPIRED to book destruction")

    if kit["site_id"] != site_id:
        raise E.invalid_request("site_id must equal the kit's site")
    if witness["site_id"] != site_id:
        raise E.invalid_request("witness must be a staff member of the same site")

    # quantity must equal book on-hand (received - dispensed + returned)
    expected = kit["units_received"] - kit["units_dispensed"] + kit["units_returned"]
    if quantity_destroyed != expected:
        raise E.quantity_mismatch("quantity_destroyed must equal kit book on-hand")

    # window conflict: closed-interval + 30-min buffer at the same site, non-VOIDED
    for d in store.destruction_records.values():
        if d["site_id"] != site_id or d["status"] == "VOIDED":
            continue
        ows = S._parse_stored(d["facility_window_start"])
        owe = S._parse_stored(d["facility_window_end"])
        # intersect as closed intervals OR new window begins within 30 min after other ends
        if ws <= owe and we >= ows:
            raise E.destruction_window_conflict()
        if ws >= owe and ws < owe + timedelta(minutes=30):
            raise E.destruction_window_conflict()

    record = {
        "id": new_id(),
        "kit_id": kit_id,
        "site_id": site_id,
        "method": method,
        "facility_window_start": _fmt_dt(ws),
        "facility_window_end": _fmt_dt(we),
        "quantity_destroyed": quantity_destroyed,
        "witness_staff_id": witness_staff_id,
        "created_by_staff_id": ctx.user_id,
        "kit_prior_status": kit["status"],
        "status": "DRAFT",
    }
    stamp_created(record)
    store.destruction_records[record["id"]] = record

    kit["status"] = "DESTRUCTION_PENDING"
    touch(kit)

    return R.success_object(S.serialize(record, "destruction", ctx), 201)


@app.get("/api/destruction-records")
def list_destructions():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    from flask import request
    items = list(store.destruction_records.values())
    for param in ("kit_id", "site_id", "witness_staff_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d.get(param) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "destruction", ctx), limit, offset, total)


@app.get("/api/destruction-records/<did>")
def get_destruction(did):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    record = get_destruction_or_404(did)
    return R.success_object(S.serialize(record, "destruction", ctx))


@app.post("/api/destruction-records/<did>/attest")
def attest_destruction(did):
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    from flask import request as _req
    body = {}
    if _req.content_length:
        body = M.body()
    void_flag = body.get("void", False)
    if not isinstance(void_flag, bool):
        raise E.invalid_request("void must be a boolean")
    record = get_destruction_or_404(did)
    if record["status"] in S.DESTRUCTION_TERMINAL:
        raise E.already_terminal("Destruction record is terminal")
    if record["status"] != "DRAFT":
        raise E.invalid_state("Destruction record is not DRAFT")

    kit = get_kit_or_404(record["kit_id"])

    if void_flag:
        # only creator may void
        if ctx.user_id != record["created_by_staff_id"]:
            raise E.unauthorized_role("Only the creator may void a DRAFT destruction")
        record["status"] = "VOIDED"
        kit["status"] = record["kit_prior_status"]
        touch(kit)
        touch(record)
        return R.success_object(S.serialize(record, "destruction", ctx))

    # witness mode
    if ctx.user_id != record["witness_staff_id"]:
        raise E.unauthorized_role("Only the designated witness may attest")
    if ctx.user_id == record["created_by_staff_id"]:
        raise E.segregation("Witness may not be the creator")
    record["status"] = "WITNESSED"
    touch(record)
    return R.success_object(S.serialize(record, "destruction", ctx))


@app.post("/api/destruction-records/<did>/finalize")
def finalize_destruction(did):
    ctx = M.require_auth()
    M.require_role(ctx, {"Pharmacist"})
    record = get_destruction_or_404(did)
    if record["status"] in S.DESTRUCTION_TERMINAL:
        raise E.already_terminal("Destruction record is terminal")
    if record["status"] != "WITNESSED":
        raise E.invalid_state("Destruction record is not WITNESSED")

    kit = get_kit_or_404(record["kit_id"])
    kit["status"] = "DESTROYED"
    kit["units_destroyed"] = record["quantity_destroyed"]
    S.recompute_kit_balance(kit)
    touch(kit)

    record["status"] = "FINALIZED"
    touch(record)

    # lot usable-count recompute
    S.recompute_lot_usable(kit["lot_id"])
    return R.success_object(S.serialize(record, "destruction", ctx))


# ===========================================================================
# Unblinding
# ===========================================================================

@app.post("/api/unblinding-requests")
def create_unblinding():
    ctx = M.require_auth()
    M.require_role(ctx, {"Investigator"})
    body = M.body()
    subject_id = M.req_string(body, "subject_id")
    reason = M.req_string(body, "reason")
    subject = get_subject_or_404(subject_id)
    if subject["enrollment_status"] in S.SUBJECT_TERMINAL:
        raise E.already_terminal("Subject enrollment is terminal")
    if subject["enrollment_status"] != "RANDOMIZED":
        raise E.subject_not_randomized()
    if subject["blinded_status"] != "BLINDED":
        raise E.invalid_state("Subject is already UNBLINDED")
    site = get_site_or_404(subject["site_id"])
    study = get_study_or_404(site["study_id"])
    if study["blinding_model"] == "OPEN_LABEL":
        raise E.study_open_label()

    req = {
        "id": new_id(),
        "subject_id": subject_id,
        "reason": reason,
        "requested_by_user_id": ctx.user_id,
        "status": "REQUESTED",
        "decided_by_staff_id": None,
        "revealed_arm_code": None,
    }
    stamp_created(req)
    store.unblinding_requests[req["id"]] = req
    return R.success_object(S.serialize(req, "unblinding_request", ctx), 201)


@app.get("/api/unblinding-requests")
def list_unblindings():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Investigator"})
    from flask import request
    items = list(store.unblinding_requests.values())
    for param in ("subject_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [u for u in items if u.get(param) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "unblinding_request", ctx), limit, offset, total)


@app.get("/api/unblinding-requests/<uid>")
def get_unblinding(uid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Investigator"})
    req = get_unblinding_or_404(uid)
    return R.success_object(S.serialize(req, "unblinding_request", ctx))


@app.post("/api/unblinding-requests/<uid>/decide")
def decide_unblinding(uid):
    ctx = M.require_auth()
    M.require_role(ctx, {"UnblindedPharmacist"})
    body = M.body()
    decision = M.req_enum(body, "decision", {"APPROVED", "REJECTED"})
    req = get_unblinding_or_404(uid)
    if req["status"] in ("EXECUTED", "REJECTED"):
        raise E.already_terminal("Unblinding request is terminal")
    if req["status"] != "REQUESTED":
        raise E.invalid_state("Unblinding request is not REQUESTED")
    if ctx.user_id == req["requested_by_user_id"]:
        raise E.segregation("Requester may not decide their own request")
    req["status"] = decision
    req["decided_by_staff_id"] = ctx.user_id
    touch(req)
    return R.success_object(S.serialize(req, "unblinding_request", ctx))


@app.post("/api/unblinding-requests/<uid>/execute")
def execute_unblinding(uid):
    ctx = M.require_auth()
    M.require_role(ctx, {"UnblindedPharmacist"})
    req = get_unblinding_or_404(uid)
    if req["status"] in ("EXECUTED", "REJECTED"):
        raise E.already_terminal("Unblinding request is terminal")
    if req["status"] != "APPROVED":
        raise E.invalid_state("Unblinding request is not APPROVED")
    if ctx.user_id == req["decided_by_staff_id"]:
        raise E.segregation("Approver may not execute")

    subject = get_subject_or_404(req["subject_id"])
    slot = None
    for s in store.slots.values():
        if s.get("assigned_subject_id") == subject["id"] and s["status"] == "ASSIGNED":
            slot = s
            break
    if slot is None:
        raise E.invalid_state("No ASSIGNED slot for subject")
    req["revealed_arm_code"] = slot["arm_code"]
    req["status"] = "EXECUTED"
    touch(req)

    subject["blinded_status"] = "UNBLINDED"
    touch(subject)

    site = get_site_or_404(subject["site_id"])
    study = get_study_or_404(site["study_id"])
    S.recompute_unblinded_count_and_maybe_suspend(study)

    return R.success_object(S.serialize(req, "unblinding_request", ctx))


# ===========================================================================
# Monitor visits
# ===========================================================================

@app.post("/api/monitor-visits")
def create_visit():
    ctx = M.require_auth()
    M.require_role(ctx, {"Monitor"})
    body = M.body()
    site_id = M.req_string(body, "site_id")
    monitor_name = M.req_string(body, "monitor_name")
    ss = M.req_datetime(body, "scheduled_start")
    se = M.req_datetime(body, "scheduled_end")
    if se <= ss:
        raise E.invalid_request("scheduled_end must be after scheduled_start")
    get_site_or_404(site_id)
    # half-open overlap against SCHEDULED/IN_PROGRESS at same site; adjacency allowed
    for v in store.monitor_visits.values():
        if v["site_id"] != site_id or v["status"] in S.VISIT_TERMINAL:
            continue
        os_ = S._parse_stored(v["scheduled_start"])
        oe = S._parse_stored(v["scheduled_end"])
        # half-open [ss, se) intersects [os, oe) iff ss < oe and os < se
        if ss < oe and os_ < se:
            raise E.monitor_visit_overlap()
    visit = {
        "id": new_id(),
        "site_id": site_id,
        "monitor_name": monitor_name,
        "scheduled_start": _fmt_dt(ss),
        "scheduled_end": _fmt_dt(se),
        "status": "SCHEDULED",
        "started_at": None,
        "closed_at": None,
        "actual_minutes": None,
        "discrepancy_count": 0,
    }
    stamp_created(visit)
    store.monitor_visits[visit["id"]] = visit
    return R.success_object(S.serialize(visit, "visit", ctx), 201)


@app.get("/api/monitor-visits")
def list_visits():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    from flask import request
    items = list(store.monitor_visits.values())
    for param in ("site_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [x for x in items if x.get(param) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "visit", ctx), limit, offset, total)


@app.get("/api/monitor-visits/<vid>")
def get_visit(vid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor"})
    visit = get_visit_or_404(vid)
    return R.success_object(S.serialize(visit, "visit", ctx))


@app.post("/api/monitor-visits/<vid>/start")
def start_visit(vid):
    ctx = M.require_auth()
    M.require_role(ctx, {"Monitor"})
    visit = get_visit_or_404(vid)
    if visit["status"] in S.VISIT_TERMINAL:
        raise E.already_terminal("Monitor visit is closed")
    if visit["status"] != "SCHEDULED":
        raise E.invalid_state("Monitor visit is not SCHEDULED")
    now = store.clock
    ss = S._parse_stored(visit["scheduled_start"])
    se = S._parse_stored(visit["scheduled_end"])
    if now < ss or now > se:
        raise E.outside_visit_window()
    visit["status"] = "IN_PROGRESS"
    visit["started_at"] = clock_iso()
    touch(visit)
    return R.success_object(S.serialize(visit, "visit", ctx))


@app.post("/api/monitor-visits/<vid>/close")
def close_visit(vid):
    ctx = M.require_auth()
    M.require_role(ctx, {"Monitor"})
    body = M.body()
    counts = body.get("counts")
    if not isinstance(counts, list):
        raise E.invalid_request("counts must be an array")
    parsed = []
    for entry in counts:
        if not isinstance(entry, dict):
            raise E.invalid_request("counts entries must be objects")
        kit_id = entry.get("kit_id")
        if not isinstance(kit_id, str) or kit_id == "":
            raise E.invalid_request("counts.kit_id must be a non-empty string")
        physical = entry.get("physical_units")
        if isinstance(physical, bool) or not isinstance(physical, int):
            raise E.invalid_request("counts.physical_units must be an integer")
        parsed.append((kit_id, physical))

    visit = get_visit_or_404(vid)
    if visit["status"] in S.VISIT_TERMINAL:
        raise E.already_terminal("Monitor visit is closed")
    if visit["status"] != "IN_PROGRESS":
        raise E.invalid_state("Monitor visit is not IN_PROGRESS")

    site_id = visit["site_id"]

    # all drug returns for dispensing records at this site must be VERIFIED
    for r in store.returns.values():
        d = store.dispensing_records.get(r["dispensing_record_id"])
        if d is None:
            continue
        kit = store.kits.get(d["kit_id"])
        if kit is None or kit["site_id"] != site_id:
            continue
        if r["status"] != "VERIFIED":
            raise E.unverified_return_pending()

    # counts must cover every kit at site in on-hand states exactly once
    on_hand_kits = {k["id"] for k in store.kits.values()
                    if k["site_id"] == site_id and k["status"] in S.ON_HAND_STATES}
    seen = set()
    for kit_id, _ in parsed:
        if kit_id not in store.kits:
            raise E.kit_not_found()
        if kit_id in seen:
            raise E.count_incomplete("Duplicate kit in counts")
        seen.add(kit_id)
    if seen != on_hand_kits:
        raise E.count_incomplete("Counts do not cover every on-hand kit exactly once")

    visit["closed_at"] = clock_iso()
    started = S._parse_stored(visit["started_at"])
    closed = S._parse_stored(visit["closed_at"])
    visit["actual_minutes"] = int((closed - started).total_seconds() // 60)

    discrepancies = 0
    for kit_id, physical in parsed:
        kit = store.kits[kit_id]
        adjustment = S.book_on_hand(kit) - physical
        if adjustment != 0:
            kit["units_lost"] += adjustment
            S.recompute_kit_balance(kit)
            touch(kit)
            discrepancies += 1
    visit["discrepancy_count"] = discrepancies
    visit["status"] = "CLOSED_RECONCILED" if discrepancies == 0 else "CLOSED_DISCREPANCY"

    # reconcile verified-return dispensing records at this site
    for d in store.dispensing_records.values():
        if d["status"] != "RETURNED":
            continue
        kit = store.kits.get(d["kit_id"])
        if kit is None or kit["site_id"] != site_id:
            continue
        ret = next((r for r in store.returns.values() if r["dispensing_record_id"] == d["id"]), None)
        if ret is not None and ret["status"] == "VERIFIED":
            d["status"] = "RECONCILED"
            touch(d)

    touch(visit)
    return R.success_object(S.serialize(visit, "visit", ctx))


# ===========================================================================
# Fee schedules & invoice
# ===========================================================================

@app.post("/api/fee-schedules")
def create_fee_schedule():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    study_id = M.req_string(body, "study_id")
    get_study_or_404(study_id)
    fs = {
        "id": new_id(),
        "study_id": study_id,
        "status": "DRAFT",
        "setup_fee_cents": M.req_int(body, "setup_fee_cents"),
        "dispensing_fee_cents": M.req_int(body, "dispensing_fee_cents"),
        "dispensing_tier_threshold": M.req_int(body, "dispensing_tier_threshold"),
        "dispensing_tier_fee_cents": M.req_int(body, "dispensing_tier_fee_cents"),
        "monitoring_fee_cents_per_hour": M.req_int(body, "monitoring_fee_cents_per_hour"),
        "storage_fee_cents_per_kit_month": M.req_int(body, "storage_fee_cents_per_kit_month"),
        "unblinding_fee_cents": M.req_int(body, "unblinding_fee_cents"),
        "overhead_pct": M.req_number(body, "overhead_pct"),
    }
    stamp_created(fs)
    store.fee_schedules[fs["id"]] = fs
    return R.success_object(S.serialize(fs, "fee_schedule", ctx), 201)


@app.get("/api/fee-schedules")
def list_fee_schedules():
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    from flask import request
    items = list(store.fee_schedules.values())
    for param in ("study_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f.get(param) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.serialize_list(page, "fee_schedule", ctx), limit, offset, total)


@app.get("/api/fee-schedules/<fid>")
def get_fee_schedule(fid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    fs = get_fee_schedule_or_404(fid)
    return R.success_object(S.serialize(fs, "fee_schedule", ctx))


@app.post("/api/fee-schedules/<fid>/approve")
def approve_fee_schedule(fid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    body = M.body()
    if "expected_study_version" not in body:
        raise E.invalid_request("Missing required field: expected_study_version")
    expected = body["expected_study_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise E.invalid_request("expected_study_version must be an integer")

    fs = get_fee_schedule_or_404(fid)
    study = get_study_or_404(fs["study_id"])

    if fs["status"] == "SUPERSEDED":
        raise E.already_terminal("Fee schedule is SUPERSEDED")
    if fs["status"] != "DRAFT":
        raise E.invalid_state("Only a DRAFT fee schedule can be approved")

    if expected != study["version"]:
        raise E.stale_version()

    # supersede currently approved schedules of the same study
    for other in store.fee_schedules.values():
        if other["study_id"] == study["id"] and other["status"] == "APPROVED" and other["id"] != fs["id"]:
            other["status"] = "SUPERSEDED"
            touch(other)

    fs["status"] = "APPROVED"
    touch(fs)
    touch(study)
    return R.success_object(S.serialize(fs, "fee_schedule", ctx))


@app.get("/api/sites/<sid>/invoice")
def site_invoice(sid):
    ctx = M.require_auth()
    M.require_role(ctx, {"SponsorAdmin"})
    from flask import request
    from decimal import Decimal, ROUND_HALF_UP

    ps_raw = request.args.get("period_start")
    pe_raw = request.args.get("period_end")
    variant = request.args.get("variant")
    if ps_raw is None or pe_raw is None or variant is None:
        raise E.invalid_request("period_start, period_end and variant are required")
    if variant not in ("PROVISIONAL", "FINAL"):
        raise E.invalid_request("variant must be PROVISIONAL or FINAL")
    period_start = M.parse_datetime(ps_raw, "period_start")
    period_end = M.parse_datetime(pe_raw, "period_end")
    if period_end <= period_start:
        raise E.invalid_request("period_end must be after period_start")

    site = get_site_or_404(sid)
    study = get_study_or_404(site["study_id"])
    fs = next((f for f in store.fee_schedules.values()
               if f["study_id"] == study["id"] and f["status"] == "APPROVED"), None)
    if fs is None:
        raise E.no_approved_fee_schedule()

    def in_period(dt_str):
        dt = S._parse_stored(dt_str)
        return period_start <= dt < period_end

    # Line 1: setup
    setup_cents = 0
    if site.get("activated_at") and in_period(site["activated_at"]):
        setup_cents = fs["setup_fee_cents"]

    # Line 2: dispensing, per-subject chronological tiering
    site_kits = {k["id"] for k in store.kits.values() if k["site_id"] == site["id"]}
    dispensing_records = [d for d in store.dispensing_records.values()
                          if d["kit_id"] in site_kits and in_period(d["dispensed_at"])]
    by_subject = {}
    for d in dispensing_records:
        by_subject.setdefault(d["subject_id"], []).append(d)
    dispensing_cents = 0
    for subj_id, recs in by_subject.items():
        recs.sort(key=lambda d: (d["dispensed_at"], d["created_at"], d["id"]))
        for idx, d in enumerate(recs, start=1):
            if idx <= fs["dispensing_tier_threshold"]:
                dispensing_cents += fs["dispensing_fee_cents"]
            else:
                dispensing_cents += fs["dispensing_tier_fee_cents"]

    # Line 3: monitoring (per-visit rounding, then sum)
    monitoring_cents = 0
    for v in store.monitor_visits.values():
        if v["site_id"] != site["id"]:
            continue
        if variant == "FINAL":
            if v["status"] not in ("CLOSED_RECONCILED", "CLOSED_DISCREPANCY"):
                continue
            if not in_period(v["closed_at"]):
                continue
            minutes = v["actual_minutes"]
        else:  # PROVISIONAL
            if v["status"] not in ("SCHEDULED", "IN_PROGRESS", "CLOSED_RECONCILED", "CLOSED_DISCREPANCY"):
                continue
            ss = S._parse_stored(v["scheduled_start"])
            se = S._parse_stored(v["scheduled_end"])
            # window overlaps period: ss < period_end and period_start < se
            if not (ss < period_end and period_start < se):
                continue
            if v["status"] in ("CLOSED_RECONCILED", "CLOSED_DISCREPANCY"):
                minutes = v["actual_minutes"]
            else:
                minutes = int((se - ss).total_seconds() // 60)
        fee = (Decimal(fs["monitoring_fee_cents_per_hour"]) * Decimal(minutes)
               / Decimal(60)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        monitoring_cents += int(fee)

    # Line 4: storage
    storage_count = 0
    for k in store.kits.values():
        if k["site_id"] != site["id"] or k["status"] not in S.STORAGE_FEE_STATES:
            continue
        created = S._parse_stored(k["created_at"])
        if created < period_end:
            storage_count += 1
    storage_cents = fs["storage_fee_cents_per_kit_month"] * storage_count

    # Line 5: unblinding
    site_subjects = {s["id"] for s in store.subjects.values() if s["site_id"] == site["id"]}
    unblinding_count = 0
    for u in store.unblinding_requests.values():
        if u["subject_id"] not in site_subjects:
            continue
        if variant == "FINAL":
            if u["status"] != "EXECUTED":
                continue
        else:
            if u["status"] not in ("APPROVED", "EXECUTED"):
                continue
        if in_period(u["updated_at"]):
            unblinding_count += 1
    unblinding_cents = fs["unblinding_fee_cents"] * unblinding_count

    subtotal = setup_cents + dispensing_cents + monitoring_cents + storage_cents + unblinding_cents
    overhead = (Decimal(subtotal) * Decimal(str(fs["overhead_pct"]))
                / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    overhead_cents = int(overhead)
    total = subtotal + overhead_cents

    return R.success_object({
        "setup_fee_cents": setup_cents,
        "dispensing_fees_cents": dispensing_cents,
        "monitoring_fees_cents": monitoring_cents,
        "storage_fees_cents": storage_cents,
        "unblinding_fees_cents": unblinding_cents,
        "subtotal_cents": subtotal,
        "overhead_cents": overhead_cents,
        "total_cents": total,
        "variant": variant,
    })


# ===========================================================================
# Boot
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
