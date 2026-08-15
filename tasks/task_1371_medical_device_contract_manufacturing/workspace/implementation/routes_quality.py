"""Nonconformance reports, complaints, CAPAs, field actions (PRD section 3.7)."""
from flask import Blueprint, request

from auth import (QUALITY_ENGINEER, QUALITY_MANAGER, REGULATORY_AFFAIRS,
                  context, require_role)
from domain import (SEVERITY_PENALTY, components_of_lot, hold_inflight_lots_with_part,
                    hold_lot_system, list_data, ncrs_of_lot,
                    recall_lot, recompute_all_suppliers_with_auto_suspend,
                    recompute_dmr_complaint_rate, revalidate_protocol,
                    scrap_lot, serialize)
from envelope import pagination_params, success
from errors import ApiError, err_sod, err_state, err_validation
from store import DB, bump, new_entity, now
from validate import (get_body, get_or_404, opt_bool, opt_fk, req_bool,
                      req_dt, req_enum, req_str)
import uuid

bp = Blueprint("quality", __name__)

QE = QUALITY_ENGINEER
QM = QUALITY_MANAGER
RA = REGULATORY_AFFAIRS


def _list(kind, extra_filters):
    context()
    filters = [(n, request.args.get(n)) for n in extra_filters]
    items = list_data(kind, filters)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return success([serialize(o) for o in page], 200, pagination={
        "limit": limit, "offset": offset, "total_count": len(items),
        "has_more": offset + len(page) < len(items),
    })


# ---------------------------------------------------------------------------
# Nonconformance reports
# ---------------------------------------------------------------------------

@bp.post("/api/nonconformance-reports")
def create_ncr():
    uid, role = context()
    require_role(role, QE)
    data = get_body()
    ncr_code = req_str(data, "ncr_code")
    description = req_str(data, "description")
    severity = req_enum(data, "severity", ("MINOR", "MAJOR", "CRITICAL"))
    lot_id = opt_fk(data, "lot_id")
    part_id = opt_fk(data, "supplier_part_id")
    # step 3: at least one of lot_id / supplier_part_id
    if lot_id is None and part_id is None:
        raise err_validation("An NCR must reference at least one of lot_id or supplier_part_id")
    # step 4: body FKs (supplier_part_id before lot_id per the pipeline listing)
    if part_id is not None:
        get_or_404("parts", part_id)
    lot = get_or_404("lots", lot_id) if lot_id is not None else None
    # step 12
    if any(n["ncr_code"] == ncr_code for n in DB["ncrs"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "ncr_code already exists")
    ncr = new_entity({
        "ncr_code": ncr_code,
        "lot_id": lot_id,
        "supplier_part_id": part_id,
        "description": description,
        "severity": severity,
        "fault": "UNDETERMINED",
        "disposition": "NONE",
        "status": "OPEN",
        "initiator_user_id": uid,
        "penalty_points_applied": 0,
    })
    DB["ncrs"][ncr["id"]] = ncr
    # creation is itself a containment signal
    if lot is not None and lot["disposition_status"] in ("IN_PRODUCTION", "COMPLETED"):
        hold_lot_system(lot, "NCR_OPEN")
    return success(serialize(ncr), 201)


@bp.get("/api/nonconformance-reports")
def list_ncrs():
    return _list("ncrs", ["lot_id", "supplier_part_id", "status", "fault"])


@bp.get("/api/nonconformance-reports/<id>")
def get_ncr(id):
    context()
    return success(serialize(get_or_404("ncrs", id)), 200)


@bp.post("/api/nonconformance-reports/<id>/contain")
def contain_ncr(id):
    uid, role = context()
    require_role(role, QE)
    ncr = get_or_404("ncrs", id)
    if ncr["status"] != "OPEN":
        raise err_state()
    ncr["status"] = "CONTAINED"
    bump(ncr)
    return success(serialize(ncr), 200)


@bp.post("/api/nonconformance-reports/<id>/disposition")
def disposition_ncr(id):
    uid, role = context()
    require_role(role, QE)
    data = get_body()
    disposition = req_enum(data, "disposition",
                           ("USE_AS_IS", "REWORK", "SCRAP", "RETURN_TO_SUPPLIER"))
    fault = req_enum(data, "fault", ("INTERNAL", "SUPPLIER"))
    ncr = get_or_404("ncrs", id)
    if ncr["status"] != "CONTAINED":
        raise err_state()
    lot = DB["lots"].get(ncr["lot_id"]) if ncr.get("lot_id") else None
    if disposition == "SCRAP" and lot is not None and \
            lot["disposition_status"] not in ("IN_PRODUCTION", "COMPLETED"):
        raise err_state()
    ncr["fault"] = fault
    ncr["disposition"] = disposition
    ncr["status"] = "DISPOSITIONED"
    if fault == "SUPPLIER":
        ncr["penalty_points_applied"] = SEVERITY_PENALTY[ncr["severity"]]
    bump(ncr)
    if fault == "SUPPLIER":
        # supplier score penalty + auto-suspension cascade
        recompute_all_suppliers_with_auto_suspend()
        if ncr.get("supplier_part_id"):
            part = DB["parts"].get(ncr["supplier_part_id"])
            if part is not None:
                if part["status"] == "QUALIFIED":
                    part["status"] = "ON_HOLD"
                    bump(part)
                hold_inflight_lots_with_part(part["id"])
    if disposition == "SCRAP" and lot is not None:
        scrap_lot(lot)
    return success(serialize(ncr), 200)


@bp.post("/api/nonconformance-reports/<id>/close")
def close_ncr(id):
    uid, role = context()
    require_role(role, QM)
    ncr = get_or_404("ncrs", id)
    # step 6: closer must not be the initiator (before state-shape)
    if uid == ncr["initiator_user_id"]:
        raise err_sod()
    if ncr["status"] != "DISPOSITIONED":
        raise err_state()
    ncr["status"] = "CLOSED"
    bump(ncr)
    # supplier-fault penalty moves into the finalized accumulator
    recompute_all_suppliers_with_auto_suspend()
    # containment release: clear the lot's NCR_OPEN hold when no open NCRs remain
    lot = DB["lots"].get(ncr["lot_id"]) if ncr.get("lot_id") else None
    if lot is not None and lot["hold_status"] == "ON_HOLD" and lot["hold_reason"] == "NCR_OPEN":
        if not any(n["status"] in ("OPEN", "CONTAINED") for n in ncrs_of_lot(lot["id"])):
            lot["hold_status"] = "CLEAR"
            lot["hold_reason"] = "NONE"
            bump(lot)
    return success(serialize(ncr), 200)


@bp.post("/api/nonconformance-reports/<id>/reopen")
def reopen_ncr(id):
    uid, role = context()
    require_role(role, QE)
    ncr = get_or_404("ncrs", id)
    if ncr["status"] != "DISPOSITIONED":
        raise err_state()
    ncr["status"] = "OPEN"
    ncr["fault"] = "UNDETERMINED"
    ncr["disposition"] = "NONE"
    ncr["penalty_points_applied"] = 0
    bump(ncr)
    # reverse the supplier penalty exactly
    recompute_all_suppliers_with_auto_suspend()
    lot = DB["lots"].get(ncr["lot_id"]) if ncr.get("lot_id") else None
    if lot is not None and lot["disposition_status"] == "IN_PRODUCTION":
        hold_lot_system(lot, "NCR_OPEN")
    return success(serialize(ncr), 200)


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

@bp.post("/api/complaints")
def create_complaint():
    uid, role = context()
    require_role(role, RA)
    data = get_body()
    complaint_code = req_str(data, "complaint_code")
    lot_id = req_str(data, "lot_id")
    severity = req_enum(data, "severity",
                        ("COSMETIC", "MINOR", "SERIOUS_INJURY", "DEATH"))
    description = req_str(data, "description")
    lot = get_or_404("lots", lot_id)
    # step 9: complaint intake requires a RELEASED or RECALLED lot
    if lot["disposition_status"] not in ("RELEASED", "RECALLED"):
        raise ApiError("ERR_LOT_NOT_RELEASED", 409,
                       "Complaint intake requires the lot in RELEASED or RECALLED")
    if any(c["complaint_code"] == complaint_code for c in DB["complaints"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "complaint_code already exists")
    complaint = new_entity({
        "complaint_code": complaint_code,
        "lot_id": lot_id,
        "severity": severity,
        "description": description,
        "confirmed": False,
        "received_at": now(),
        "investigator_user_id": None,
        "status": "RECEIVED",
    })
    DB["complaints"][complaint["id"]] = complaint
    return success(serialize(complaint), 201)


@bp.get("/api/complaints")
def list_complaints():
    return _list("complaints", ["lot_id", "status", "confirmed"])


@bp.get("/api/complaints/<id>")
def get_complaint(id):
    context()
    return success(serialize(get_or_404("complaints", id)), 200)


@bp.post("/api/complaints/<id>/start-investigation")
def start_investigation(id):
    uid, role = context()
    require_role(role, RA)
    complaint = get_or_404("complaints", id)
    if complaint["status"] != "RECEIVED":
        raise err_state()
    complaint["status"] = "UNDER_INVESTIGATION"
    complaint["investigator_user_id"] = uid
    bump(complaint)
    return success(serialize(complaint), 200)


@bp.post("/api/complaints/<id>/complete-investigation")
def complete_investigation(id):
    uid, role = context()
    require_role(role, RA)
    data = get_body()
    confirmed = req_bool(data, "confirmed")
    complaint = get_or_404("complaints", id)
    if complaint["status"] != "UNDER_INVESTIGATION":
        raise err_state()
    complaint["status"] = "INVESTIGATED"
    complaint["confirmed"] = confirmed
    bump(complaint)
    lot = DB["lots"].get(complaint["lot_id"])
    dmr = DB["dmrs"].get(lot["dmr_id"]) if lot is not None else None
    if dmr is not None:
        recompute_dmr_complaint_rate(dmr)
    if confirmed and complaint["severity"] in ("SERIOUS_INJURY", "DEATH") and dmr is not None:
        # auto-create a CAPA
        capa = new_entity({
            "capa_code": "CAPA-AUTO-" + uuid.uuid4().hex[:16],
            "dmr_id": dmr["id"],
            "source_type": "COMPLAINT",
            "source_complaint_id": complaint["id"],
            "source_ncr_id": None,
            "process_change": False,
            "action_summary": None,
            "initiator_user_id": complaint["investigator_user_id"],
            "closer_user_id": None,
            "effectiveness_cycles": 0,
            "status": "INITIATED",
        })
        DB["capas"][capa["id"]] = capa
        # investigation hold on sibling COMPLETED lots of the same DMR
        for l in DB["lots"].values():
            if l["dmr_id"] == dmr["id"] and l["disposition_status"] == "COMPLETED" \
                    and l["hold_status"] == "CLEAR":
                hold_lot_system(l, "FIELD_ACTION")
    return success(serialize(complaint), 200)


@bp.post("/api/complaints/<id>/reopen")
def reopen_complaint(id):
    uid, role = context()
    require_role(role, RA)
    complaint = get_or_404("complaints", id)
    if complaint["status"] != "INVESTIGATED":
        raise err_state()
    complaint["status"] = "UNDER_INVESTIGATION"
    complaint["confirmed"] = False
    bump(complaint)
    lot = DB["lots"].get(complaint["lot_id"])
    dmr = DB["dmrs"].get(lot["dmr_id"]) if lot is not None else None
    if dmr is not None:
        recompute_dmr_complaint_rate(dmr)
    return success(serialize(complaint), 200)


@bp.post("/api/complaints/<id>/close")
def close_complaint(id):
    uid, role = context()
    require_role(role, RA)
    complaint = get_or_404("complaints", id)
    if complaint["status"] != "INVESTIGATED":
        raise err_state()
    if any(c.get("source_complaint_id") == id and c["status"] != "CLOSED"
           for c in DB["capas"].values()):
        raise ApiError("ERR_CAPA_NOT_CLOSED", 409,
                       "A CAPA spawned from this complaint is not CLOSED")
    complaint["status"] = "CLOSED"
    bump(complaint)
    return success(serialize(complaint), 200)


# ---------------------------------------------------------------------------
# CAPAs
# ---------------------------------------------------------------------------

@bp.post("/api/capas")
def create_capa():
    uid, role = context()
    require_role(role, QE)
    data = get_body()
    capa_code = req_str(data, "capa_code")
    dmr_id = req_str(data, "dmr_id")
    source_type = req_enum(data, "source_type", ("COMPLAINT", "NCR", "AUDIT", "MANUAL"))
    complaint_id = opt_fk(data, "source_complaint_id")
    ncr_id = opt_fk(data, "source_ncr_id")
    process_change = opt_bool(data, "process_change", False)
    # step 4: body FKs
    get_or_404("dmrs", dmr_id)
    complaint = get_or_404("complaints", complaint_id) if complaint_id is not None else None
    get_or_404("ncrs", ncr_id) if ncr_id is not None else None
    # step 11: source linkage must match source_type
    def mismatch():
        return ApiError("ERR_SOURCE_MISMATCH", 422,
                        "CAPA source linkage does not match source_type or DMR")
    if source_type == "COMPLAINT":
        if complaint_id is None or ncr_id is not None:
            raise mismatch()
        lot = DB["lots"].get(complaint["lot_id"])
        if lot is None or lot["dmr_id"] != dmr_id:
            raise mismatch()
    elif source_type == "NCR":
        if ncr_id is None or complaint_id is not None:
            raise mismatch()
    else:  # AUDIT / MANUAL take neither
        if complaint_id is not None or ncr_id is not None:
            raise mismatch()
    # step 12
    if any(c["capa_code"] == capa_code for c in DB["capas"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "capa_code already exists")
    capa = new_entity({
        "capa_code": capa_code,
        "dmr_id": dmr_id,
        "source_type": source_type,
        "source_complaint_id": complaint_id,
        "source_ncr_id": ncr_id,
        "process_change": process_change,
        "action_summary": None,
        "initiator_user_id": uid,
        "closer_user_id": None,
        "effectiveness_cycles": 0,
        "status": "INITIATED",
    })
    DB["capas"][capa["id"]] = capa
    return success(serialize(capa), 201)


@bp.get("/api/capas")
def list_capas():
    return _list("capas", ["dmr_id", "status", "source_complaint_id", "source_ncr_id"])


@bp.get("/api/capas/<id>")
def get_capa(id):
    context()
    return success(serialize(get_or_404("capas", id)), 200)


@bp.post("/api/capas/<id>/begin-investigation")
def begin_investigation(id):
    uid, role = context()
    require_role(role, QE)
    capa = get_or_404("capas", id)
    if capa["status"] != "INITIATED":
        raise err_state()
    capa["status"] = "INVESTIGATING"
    bump(capa)
    return success(serialize(capa), 200)


@bp.post("/api/capas/<id>/plan-actions")
def plan_actions(id):
    uid, role = context()
    require_role(role, QE)
    data = get_body()
    action_summary = req_str(data, "action_summary")
    capa = get_or_404("capas", id)
    if capa["status"] != "INVESTIGATING":
        raise err_state()
    capa["action_summary"] = action_summary
    capa["status"] = "ACTION_PLANNED"
    bump(capa)
    return success(serialize(capa), 200)


@bp.post("/api/capas/<id>/implement")
def implement_capa(id):
    uid, role = context()
    require_role(role, QE)
    capa = get_or_404("capas", id)
    if capa["status"] != "ACTION_PLANNED":
        raise err_state()
    capa["status"] = "IMPLEMENTING"
    bump(capa)
    if capa["process_change"]:
        for p in DB["protocols"].values():
            if p["dmr_id"] == capa["dmr_id"] and p["status"] == "VALIDATED":
                revalidate_protocol(p, "CAPA_PROCESS_CHANGE")
    return success(serialize(capa), 200)


@bp.post("/api/capas/<id>/complete-implementation")
def complete_implementation(id):
    uid, role = context()
    require_role(role, QE)
    capa = get_or_404("capas", id)
    if capa["status"] != "IMPLEMENTING":
        raise err_state()
    capa["status"] = "EFFECTIVENESS_CHECK"
    bump(capa)
    return success(serialize(capa), 200)


@bp.post("/api/capas/<id>/verify-effectiveness")
def verify_effectiveness(id):
    uid, role = context()
    require_role(role, QM)
    data = get_body()
    effective = req_bool(data, "effective")
    capa = get_or_404("capas", id)
    # step 6: verifier must not be the initiator (before state-shape)
    if uid == capa["initiator_user_id"]:
        raise err_sod()
    if capa["status"] != "EFFECTIVENESS_CHECK":
        raise err_state()
    if effective:
        if capa.get("source_ncr_id"):
            ncr = DB["ncrs"].get(capa["source_ncr_id"])
            if ncr is None or ncr["status"] != "CLOSED":
                raise ApiError("ERR_SOURCE_NOT_CLOSED", 409,
                               "The source NCR is not CLOSED")
        capa["status"] = "CLOSED"
        capa["closer_user_id"] = uid
    else:
        capa["status"] = "INEFFECTIVE"
    bump(capa)
    return success(serialize(capa), 200)


@bp.post("/api/capas/<id>/restart-investigation")
def restart_investigation(id):
    uid, role = context()
    require_role(role, QE)
    capa = get_or_404("capas", id)
    if capa["status"] != "INEFFECTIVE":
        raise err_state()
    capa["status"] = "INVESTIGATING"
    capa["effectiveness_cycles"] += 1
    bump(capa)
    return success(serialize(capa), 200)


# ---------------------------------------------------------------------------
# Field actions
# ---------------------------------------------------------------------------

@bp.post("/api/field-actions")
def create_field_action():
    uid, role = context()
    require_role(role, RA)
    data = get_body()
    action_code = req_str(data, "action_code")
    dmr_id = req_str(data, "dmr_id")
    action_type = req_enum(data, "action_type", ("CORRECTION", "REMOVAL"))
    scope_start = req_dt(data, "scope_mfg_start")
    scope_end = req_dt(data, "scope_mfg_end")
    reason_id = req_str(data, "reason_complaint_id")
    if not scope_start < scope_end:
        raise err_validation("scope_mfg_start must be strictly before scope_mfg_end")
    get_or_404("dmrs", dmr_id)
    complaint = get_or_404("complaints", reason_id)
    # step 11: the reason complaint must be actionable
    lot = DB["lots"].get(complaint["lot_id"])
    actionable = (
        complaint["confirmed"]
        and complaint["severity"] in ("SERIOUS_INJURY", "DEATH")
        and lot is not None and lot["dmr_id"] == dmr_id
    )
    if not actionable:
        raise ApiError("ERR_COMPLAINT_NOT_ACTIONABLE", 422,
                       "Reason complaint must be confirmed, SERIOUS_INJURY/DEATH, and on the same DMR")
    if any(f["action_code"] == action_code for f in DB["field_actions"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "action_code already exists")
    fa = new_entity({
        "action_code": action_code,
        "dmr_id": dmr_id,
        "action_type": action_type,
        "scope_mfg_start": scope_start,
        "scope_mfg_end": scope_end,
        "reason_complaint_id": reason_id,
        "issued_at": None,
        "recalled_lot_count": 0,
        "status": "DRAFT",
    })
    DB["field_actions"][fa["id"]] = fa
    return success(serialize(fa), 201)


@bp.get("/api/field-actions")
def list_field_actions():
    return _list("field_actions", ["dmr_id", "status", "reason_complaint_id"])


@bp.get("/api/field-actions/<id>")
def get_field_action(id):
    context()
    return success(serialize(get_or_404("field_actions", id)), 200)


@bp.post("/api/field-actions/<id>/issue")
def issue_field_action(id):
    uid, role = context()
    require_role(role, RA)
    fa = get_or_404("field_actions", id)
    if fa["status"] != "DRAFT":
        raise err_state()
    fa["status"] = "ISSUED"
    fa["issued_at"] = now()
    # recall every in-scope RELEASED lot of the DMR (closed scope interval)
    count = 0
    for lot in DB["lots"].values():
        if lot["dmr_id"] == fa["dmr_id"] and lot["disposition_status"] == "RELEASED" \
                and fa["scope_mfg_start"] <= lot["manufactured_at"] <= fa["scope_mfg_end"]:
            recall_lot(lot)
            count += 1
    fa["recalled_lot_count"] = count
    bump(fa)
    dmr = DB["dmrs"].get(fa["dmr_id"])
    if dmr is not None:
        recompute_dmr_complaint_rate(dmr)
    return success(serialize(fa), 200)


@bp.post("/api/field-actions/<id>/close")
def close_field_action(id):
    uid, role = context()
    require_role(role, RA)
    fa = get_or_404("field_actions", id)
    if fa["status"] != "ISSUED":
        raise err_state()
    complaint = DB["complaints"].get(fa["reason_complaint_id"])
    if complaint is None or complaint["status"] != "CLOSED":
        raise ApiError("ERR_SOURCE_NOT_CLOSED", 409,
                       "The reason complaint is not CLOSED")
    fa["status"] = "CLOSED"
    bump(fa)
    return success(serialize(fa), 200)
