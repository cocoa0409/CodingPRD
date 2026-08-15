"""FarmerStockLoad, GradeSheet, AflatoxinCertificate (PRD 3.3-3.5)."""
from flask import Blueprint, request

import calc
from authz import (ADMIN, GROWER, INSPECTOR, LABTECH, CLERK,
                   authenticate, require_roles, check_grower_ownership)
from db import store
from errors import err, invalid_state, stale_version
from respond import success
from serialize import ser_load, ser_grade_sheet, ser_certificate
from store_ops import (get_or_404, json_body, list_response,
                       new_common_fields, req_int, req_pct, req_ppb, req_str,
                       req_tons, touch)

bp = Blueprint("intake", __name__)


# ---------------------------------------------------------------------------
# FarmerStockLoad
# ---------------------------------------------------------------------------

@bp.post("/buying-points/loads")
def create_load():
    uid, role = authenticate()
    data = json_body()
    grower_id = req_str(data, "grower_id")
    crop_year = req_int(data, "crop_year")
    require_roles([ADMIN, GROWER])
    grower = get_or_404(store.growers, grower_id)
    bp_rec = calc.bp_for_crop_year(crop_year)
    if bp_rec is None:
        raise err("ERR_NOT_FOUND", 404,
                  "No buying point operates the supplied crop_year")
    check_grower_ownership(uid, role, grower_id)
    if grower["status"] != "ACTIVE":
        raise err("ERR_GROWER_SUSPENDED", 409,
                  "A SUSPENDED grower may not report new loads")
    if calc.intake_posture(bp_rec["id"]) == "SUSPENDED":
        raise err("ERR_INTAKE_SUSPENDED", 409,
                  "The buying point is not accepting farmer stock")
    load = new_common_fields()
    load.update({
        "grower_id": grower_id,
        "crop_year": crop_year,
        "gross_tons": None,
        "weighed_at": None,
        "status": "REPORTED",
        "aflatoxin_status": "UNTESTED",
        "drying_status": "NOT_REQUIRED",
        "payable_tons": None,
        "provisional_net_estimate_cents": None,
        "settlement_id": None,
    })
    store.loads[load["id"]] = load
    return success(ser_load(load), status=201)


@bp.get("/buying-points/loads/<load_id>")
def get_load(load_id):
    uid, role = require_roles([ADMIN, GROWER, INSPECTOR, LABTECH, CLERK])
    load = get_or_404(store.loads, load_id)
    check_grower_ownership(uid, role, load["grower_id"])
    return success(ser_load(load))


@bp.get("/buying-points/loads")
def list_loads():
    uid, role = require_roles([ADMIN, GROWER, INSPECTOR, LABTECH, CLERK])
    items = list(store.loads.values())
    if role == GROWER:
        items = [l for l in items if l["grower_id"] == uid]
    for param, field in (("grower_id", "grower_id"), ("status", "status"),
                         ("aflatoxin_status", "aflatoxin_status"),
                         ("settlement_id", "settlement_id")):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l[field] == v]
    return list_response(items, ser_load)


@bp.post("/buying-points/loads/<load_id>/weigh")
def weigh_load(load_id):
    authenticate()
    data = json_body()
    gross = req_tons(data, "gross_tons")
    require_roles([ADMIN])
    load = get_or_404(store.loads, load_id)
    if load["status"] != "REPORTED":
        raise invalid_state("Only a REPORTED load may be weighed")
    bp_rec = calc.bp_for_crop_year(load["crop_year"])
    if bp_rec is not None and calc.intake_posture(bp_rec["id"]) == "RESTRICTED" \
            and gross > calc.RESTRICTED_MAX_LOAD_TONS:
        raise err("ERR_RESTRICTED_LOAD_LIMIT", 409,
                  "While RESTRICTED, a weigh-in may not exceed 50 gross tons")
    load["gross_tons"] = calc.r3(gross)
    load["weighed_at"] = store.clock
    load["status"] = "WEIGHED"
    touch(load)
    return success(ser_load(load))


# ---------------------------------------------------------------------------
# GradeSheet
# ---------------------------------------------------------------------------

@bp.post("/buying-points/loads/<load_id>/grade-sheets")
def create_grade_sheet(load_id):
    uid, role = authenticate()
    data = json_body()
    moisture = req_pct(data, "moisture_pct")
    fm = req_pct(data, "foreign_material_pct")
    damage = req_pct(data, "damage_pct")
    lsk = req_pct(data, "lsk_pct")
    expected = req_int(data, "expected_farmer_stock_load_version")
    require_roles([INSPECTOR])
    load = get_or_404(store.loads, load_id)
    if load["status"] not in ("WEIGHED", "GRADED", "STORED"):
        raise invalid_state("A grade sheet requires a WEIGHED, GRADED, or STORED load")
    if expected != load["version"]:
        raise stale_version()
    sheet = new_common_fields()
    sheet.update({
        "load_id": load["id"],
        "inspector_ref": uid,
        "schedule_id": None,
        "moisture_pct": moisture,
        "foreign_material_pct": fm,
        "damage_pct": damage,
        "lsk_pct": lsk,
        "payable_tons": None,
        "status": "DRAFT",
    })
    store.grade_sheets[sheet["id"]] = sheet
    touch(load)  # creating a sheet increments the load's version (OCC basis)
    return success(ser_grade_sheet(sheet), status=201)


@bp.get("/buying-points/grade-sheets/<sheet_id>")
def get_grade_sheet(sheet_id):
    require_roles([ADMIN, INSPECTOR, CLERK])
    sheet = get_or_404(store.grade_sheets, sheet_id)
    return success(ser_grade_sheet(sheet))


@bp.get("/buying-points/grade-sheets")
def list_grade_sheets():
    require_roles([ADMIN, INSPECTOR, CLERK])
    items = list(store.grade_sheets.values())
    for param, field in (("load_id", "load_id"), ("schedule_id", "schedule_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[field] == v]
    return list_response(items, ser_grade_sheet)


def _stale_cascade(load_id):
    """Every settlement in {COMPUTED, DISPUTED} containing this load -> STALE."""
    for s in store.settlements.values():
        if s["status"] in ("COMPUTED", "DISPUTED") and load_id in s["included_load_ids"]:
            s["status"] = "STALE"
            touch(s)


def _cancel_receipt_for_reject(load):
    """Re-grade above the moisture reject threshold cancels an OPEN receipt
    with the release cascade of PRD 3.7."""
    for r in list(store.storage_receipts.values()):
        if r["load_id"] != load["id"] or r["status"] != "OPEN":
            continue
        # Allocation lines referencing this receipt are deleted; their calls
        # revert ALLOCATED -> ISSUED when allocated drops below requested.
        affected_calls = set()
        for lid in [lid for lid, l in store.allocation_lines.items()
                    if l["storage_receipt_id"] == r["id"]]:
            affected_calls.add(store.allocation_lines[lid]["delivery_call_id"])
            del store.allocation_lines[lid]
        for call_id in affected_calls:
            call = store.delivery_calls.get(call_id)
            if call is not None and call["status"] == "ALLOCATED" \
                    and calc.call_allocated_tons(call_id) < call["requested_tons"]:
                call["status"] = "ISSUED"
                touch(call)
        r["tons_remaining"] = calc.r3(0)
        r["status"] = "CANCELLED"
        touch(r)


@bp.post("/buying-points/grade-sheets/<sheet_id>/finalize")
def finalize_grade_sheet(sheet_id):
    uid, role = require_roles([INSPECTOR])
    sheet = get_or_404(store.grade_sheets, sheet_id)
    if sheet["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT grade sheet may be finalized")
    load = get_or_404(store.loads, sheet["load_id"])
    # Settlement re-grade lock (priority 9).
    if load["settlement_id"] is not None:
        raise err("ERR_LOAD_LOCKED_BY_SETTLEMENT", 409,
                  "The load is locked into an approved settlement")
    # Schedule coverage at finalize (priority 10).
    schedule = calc.active_schedule_covering(load["weighed_at"])
    if schedule is None:
        raise err("ERR_NO_ACTIVE_SCHEDULE", 409,
                  "No ACTIVE discount schedule covers the load's weigh timestamp")
    prior_status = load["status"]
    # Supersede the prior sheet of record; finalize this sheet.
    for s in store.grade_sheets.values():
        if s["load_id"] == load["id"] and s["status"] == "FINALIZED":
            s["status"] = "SUPERSEDED"
            touch(s)
    sheet["schedule_id"] = schedule["id"]
    sheet["payable_tons"] = calc.compute_payable_tons(
        load["gross_tons"], sheet["foreign_material_pct"], sheet["lsk_pct"])
    sheet["status"] = "FINALIZED"
    touch(sheet)
    if sheet["moisture_pct"] > calc.MOISTURE_REJECT_PCT:
        # The sheet remains the grade of record; the load is terminally
        # rejected. A STORED load's receipt is cancelled with release cascade.
        if prior_status == "STORED":
            _cancel_receipt_for_reject(load)
        load["status"] = "REJECTED"
        touch(load)
        if prior_status in ("GRADED", "STORED"):
            _stale_cascade(load["id"])
        return success(ser_grade_sheet(sheet))
    load["payable_tons"] = sheet["payable_tons"]
    if sheet["moisture_pct"] > calc.MOISTURE_DRYING_REQUIRED_PCT:
        load["drying_status"] = "REQUIRED"
    else:
        load["drying_status"] = "NOT_REQUIRED"
    if prior_status == "WEIGHED":
        load["status"] = "GRADED"
    # GRADED re-grade and STORED re-grade keep the load's current status.
    bp_rec = calc.bp_for_crop_year(load["crop_year"])
    load["provisional_net_estimate_cents"] = calc.provisional_net_estimate(
        load, sheet, schedule, bp_rec)
    touch(load)
    if prior_status in ("GRADED", "STORED"):
        _stale_cascade(load["id"])
    return success(ser_grade_sheet(sheet))


# ---------------------------------------------------------------------------
# AflatoxinCertificate
# ---------------------------------------------------------------------------

@bp.post("/buying-points/loads/<load_id>/aflatoxin-certificates")
def create_certificate(load_id):
    uid, role = authenticate()
    data = json_body()
    sample_ref = req_str(data, "sample_ref")
    require_roles([LABTECH])
    load = get_or_404(store.loads, load_id)
    if load["status"] not in ("WEIGHED", "GRADED"):
        raise invalid_state("A sample may be drawn only on a WEIGHED or GRADED load")
    for c in store.certificates.values():
        if c["load_id"] == load["id"]:
            raise err("ERR_CERTIFICATE_EXISTS", 409,
                      "At most one certificate may ever exist for a load")
    cert = new_common_fields()
    cert.update({
        "load_id": load["id"],
        "sample_ref": sample_ref,
        "lab_tech_ref": uid,
        "result_ppb": None,
        "result_recorded_by": None,
        "confirmed_by": None,
        "determination": None,
        "retest_count": 0,
        "status": "SAMPLED",
    })
    store.certificates[cert["id"]] = cert
    load["aflatoxin_status"] = "SAMPLED"
    touch(load)
    return success(ser_certificate(cert), status=201)


@bp.get("/buying-points/aflatoxin-certificates/<cert_id>")
def get_certificate(cert_id):
    require_roles([ADMIN, LABTECH, CLERK])
    cert = get_or_404(store.certificates, cert_id)
    return success(ser_certificate(cert))


@bp.get("/buying-points/aflatoxin-certificates")
def list_certificates():
    require_roles([ADMIN, LABTECH, CLERK])
    items = list(store.certificates.values())
    for param, field in (("load_id", "load_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    return list_response(items, ser_certificate)


@bp.post("/buying-points/aflatoxin-certificates/<cert_id>/record-result")
def record_result(cert_id):
    uid, role = authenticate()
    data = json_body()
    result = req_ppb(data, "result_ppb")
    require_roles([LABTECH])
    cert = get_or_404(store.certificates, cert_id)
    if cert["status"] != "SAMPLED":
        raise invalid_state("Only a SAMPLED certificate accepts a result")
    cert["result_ppb"] = result
    cert["result_recorded_by"] = uid
    cert["determination"] = calc.aflatoxin_determination(result)
    cert["status"] = "RESULT_RECORDED"
    touch(cert)
    return success(ser_certificate(cert))


@bp.post("/buying-points/aflatoxin-certificates/<cert_id>/confirm")
def confirm_certificate(cert_id):
    uid, role = require_roles([LABTECH])
    cert = get_or_404(store.certificates, cert_id)
    if cert["status"] != "RESULT_RECORDED":
        raise invalid_state("Only a RESULT_RECORDED certificate may be confirmed")
    if uid == cert["result_recorded_by"]:
        raise err("ERR_SEG_OF_DUTIES", 409,
                  "The recording technician may not confirm the result")
    cert["confirmed_by"] = uid
    cert["status"] = "CONFIRMED"
    touch(cert)
    load = store.loads.get(cert["load_id"])
    if load is not None:
        load["aflatoxin_status"] = {
            "PASS": "PASSED", "SEGREGATE": "SEGREGATED", "REJECT": "REJECTED",
        }[cert["determination"]]
        if cert["determination"] == "REJECT" and load["status"] in ("WEIGHED", "GRADED"):
            load["status"] = "REJECTED"
        touch(load)
    return success(ser_certificate(cert))


@bp.post("/buying-points/aflatoxin-certificates/<cert_id>/order-retest")
def order_retest(cert_id):
    uid, role = require_roles([LABTECH])
    cert = get_or_404(store.certificates, cert_id)
    if cert["status"] != "RESULT_RECORDED":
        raise invalid_state("Only a RESULT_RECORDED certificate may be retested")
    if cert["retest_count"] >= calc.RETEST_MAX:
        raise err("ERR_RETEST_LIMIT_EXCEEDED", 409,
                  "The retest cycle cap of 2 has been reached")
    cert["retest_count"] += 1
    cert["status"] = "SAMPLED"  # prior result_ppb/determination retained
    touch(cert)
    return success(ser_certificate(cert))
