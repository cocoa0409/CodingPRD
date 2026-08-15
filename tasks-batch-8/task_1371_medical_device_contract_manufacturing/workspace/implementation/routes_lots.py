"""Device lot, lot component, and UDI label endpoints (PRD section 3.6)."""
from flask import Blueprint, request

from auth import (PRODUCTION_OPERATOR, QUALITY_ENGINEER, QUALITY_MANAGER,
                  context, require_role)
from domain import (approved_revision_of_family, compute_lot_expiry,
                    compute_sample_qty, components_of_lot, hold_lot_system,
                    labels_of_lot, list_data, ncrs_of_lot,
                    recompute_dmr_complaint_rate, scrap_lot, serialize,
                    udi_check_digit_ok)
from envelope import pagination_params, success
from errors import ApiError, err_state, err_udi_check, err_validation
from store import DB, bump, new_entity, now
from validate import get_body, get_or_404, req_dt, req_enum, req_int, req_str

bp = Blueprint("lots", __name__)


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
# Device lots
# ---------------------------------------------------------------------------

@bp.post("/api/device-lots")
def create_lot():
    uid, role = context()
    require_role(role, PRODUCTION_OPERATOR)
    data = get_body()
    lot_number = req_str(data, "lot_number")
    dmr_id = req_str(data, "dmr_id")
    protocol_id = req_str(data, "validation_protocol_id")
    quantity = req_int(data, "quantity", min_value=1)
    manufactured_at = req_dt(data, "manufactured_at")
    # step 4: body FKs (dmr_id before validation_protocol_id)
    dmr = get_or_404("dmrs", dmr_id)
    protocol = get_or_404("protocols", protocol_id)
    # step 9: DMR revision APPROVED
    if dmr["status"] != "APPROVED":
        raise ApiError("ERR_DMR_NOT_APPROVED", 409,
                       "Lot creation requires the DMR revision in APPROVED")
    # step 11: protocol must be pinned to the same DMR revision
    if protocol["dmr_id"] != dmr_id:
        raise ApiError("ERR_PROTOCOL_DMR_MISMATCH", 422,
                       "validation_protocol_id validates a different DMR revision")
    # step 12: lot_number unique within the DMR
    if any(l["dmr_id"] == dmr_id and l["lot_number"] == lot_number
           for l in DB["lots"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "lot_number already exists for this DMR")
    lot = new_entity({
        "lot_number": lot_number,
        "dmr_id": dmr_id,
        "validation_protocol_id": protocol_id,
        "quantity": quantity,
        "manufactured_at": manufactured_at,
        "sample_qty": 0,
        "releasable_qty": quantity,  # quantity - sample_qty
        "expiry_date": None,
        "expiry_basis": None,
        "sterility_result": "PENDING",
        "disposition_status": "IN_PRODUCTION",
        "hold_status": "CLEAR",
        "hold_reason": "NONE",
    })
    compute_lot_expiry(lot, dmr)  # PROVISIONAL or FINAL per study state
    DB["lots"][lot["id"]] = lot
    return success(serialize(lot), 201)


@bp.get("/api/device-lots")
def list_lots():
    return _list("lots", ["dmr_id", "validation_protocol_id", "disposition_status", "hold_status"])


@bp.get("/api/device-lots/<id>")
def get_lot(id):
    context()
    return success(serialize(get_or_404("lots", id)), 200)


@bp.post("/api/device-lots/<id>/complete")
def complete_lot(id):
    uid, role = context()
    require_role(role, PRODUCTION_OPERATOR)
    lot = get_or_404("lots", id)
    if lot["disposition_status"] != "IN_PRODUCTION":
        raise err_state()
    if not components_of_lot(id):
        raise ApiError("ERR_NO_COMPONENTS_RECORDED", 409,
                       "Lot completion requires at least one recorded component")
    lot["sample_qty"] = compute_sample_qty(lot)
    lot["releasable_qty"] = lot["quantity"] - lot["sample_qty"]
    lot["disposition_status"] = "COMPLETED"
    bump(lot)
    return success(serialize(lot), 200)


@bp.post("/api/device-lots/<id>/place-hold")
def place_hold(id):
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    lot = get_or_404("lots", id)
    if lot["hold_status"] != "CLEAR":
        raise err_state()
    if lot["disposition_status"] not in ("IN_PRODUCTION", "COMPLETED"):
        raise err_state()
    lot["hold_status"] = "ON_HOLD"
    lot["hold_reason"] = "MANUAL"
    bump(lot)
    return success(serialize(lot), 200)


@bp.post("/api/device-lots/<id>/release-hold")
def release_hold(id):
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    lot = get_or_404("lots", id)
    if lot["hold_status"] != "ON_HOLD":
        raise err_state()
    # step 8: hold_reason-specific resolution conditions
    reason = lot["hold_reason"]
    resolved = False
    if reason == "MANUAL":
        resolved = True
    elif reason == "NCR_OPEN":
        resolved = not any(n["status"] in ("OPEN", "CONTAINED") for n in ncrs_of_lot(id))
    elif reason == "SUPPLIER_QUALITY":
        resolved = all(
            (DB["parts"].get(c["supplier_part_id"]) or {}).get("status") == "QUALIFIED"
            for c in components_of_lot(id)
        )
    elif reason == "REVALIDATION":
        protocol = DB["protocols"].get(lot["validation_protocol_id"])
        resolved = protocol is not None and protocol["status"] == "VALIDATED"
    # STERILITY_FAILURE and FIELD_ACTION holds never clear through this operation
    if not resolved:
        raise ApiError("ERR_HOLD_CONDITION_UNRESOLVED", 409,
                       "The hold_reason's resolution condition is not met")
    lot["hold_status"] = "CLEAR"
    lot["hold_reason"] = "NONE"
    bump(lot)
    return success(serialize(lot), 200)


@bp.post("/api/device-lots/<id>/release")
def release_lot(id):
    uid, role = context()
    require_role(role, QUALITY_MANAGER)
    lot = get_or_404("lots", id)
    # step 7
    if lot["disposition_status"] != "COMPLETED":
        raise err_state()
    # step 8
    if lot["hold_status"] != "CLEAR":
        raise ApiError("ERR_LOT_ON_HOLD", 409, "Release attempted while the lot is ON_HOLD")
    # step 9: safety gates in pinned order
    dmr = DB["dmrs"].get(lot["dmr_id"])
    if dmr is not None and dmr["sterile"] and lot["sterility_result"] != "PASSED":
        raise ApiError("ERR_STERILITY_NOT_PASSED", 409,
                       "Release of a sterile-device lot requires sterility_result PASSED")
    protocol = DB["protocols"].get(lot["validation_protocol_id"])
    if protocol is None or protocol["status"] != "VALIDATED":
        raise ApiError("ERR_PROTOCOL_NOT_VALIDATED", 409,
                       "Release requires the validation protocol in VALIDATED")
    if any(n["status"] in ("OPEN", "CONTAINED") for n in ncrs_of_lot(id)):
        raise ApiError("ERR_OPEN_NCRS_EXIST", 409,
                       "Release is blocked by NCRs in OPEN or CONTAINED")
    if not any(l["status"] == "PRINTED" and dmr is not None and
               l["label_revision"] == dmr["revision_code"]
               for l in labels_of_lot(id)):
        raise ApiError("ERR_NO_PRINTED_LABEL", 409,
                       "Release requires a PRINTED label matching the lot's DMR revision")
    if dmr is None or dmr["status"] != "APPROVED":
        raise ApiError("ERR_DMR_NOT_APPROVED", 409,
                       "Release requires the DMR revision in APPROVED")
    lot["disposition_status"] = "RELEASED"
    bump(lot)
    for comp in components_of_lot(id):
        part = DB["parts"].get(comp["supplier_part_id"])
        if part is not None:
            part["quantity_committed"] -= comp["quantity_used"]
            part["quantity_in_released_lots"] += comp["quantity_used"]
            bump(part)
    if dmr is not None:
        recompute_dmr_complaint_rate(dmr)
    return success(serialize(lot), 200)


@bp.post("/api/device-lots/<id>/scrap")
def scrap_lot_ep(id):
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    lot = get_or_404("lots", id)
    if lot["disposition_status"] not in ("IN_PRODUCTION", "COMPLETED"):
        raise err_state()
    scrap_lot(lot)
    return success(serialize(lot), 200)


@bp.post("/api/device-lots/<id>/record-sterility-result")
def record_sterility(id):
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    data = get_body()
    result = req_enum(data, "result", ("PASSED", "FAILED"))
    lot = get_or_404("lots", id)
    # step 7
    if lot["disposition_status"] != "COMPLETED":
        raise err_state()
    # step 8
    if lot["sterility_result"] != "PENDING":
        raise ApiError("ERR_STERILITY_ALREADY_RESULTED", 409,
                       "Sterility has already been resulted for this lot")
    lot["sterility_result"] = result
    bump(lot)
    if result == "FAILED":
        hold_lot_system(lot, "STERILITY_FAILURE")
    return success(serialize(lot), 200)


# ---------------------------------------------------------------------------
# Lot components (genealogy)
# ---------------------------------------------------------------------------

@bp.post("/api/device-lots/<lotId>/components")
def create_component(lotId):
    uid, role = context()
    require_role(role, PRODUCTION_OPERATOR)
    data = get_body()
    part_id = req_str(data, "supplier_part_id")
    quantity_used = req_int(data, "quantity_used", min_value=1)
    supplier_lot_number = req_str(data, "supplier_lot_number")
    # step 4: path id first, then body FK
    lot = get_or_404("lots", lotId)
    part = get_or_404("parts", part_id)
    # step 7: genealogy is recorded while the lot is IN_PRODUCTION
    if lot["disposition_status"] != "IN_PRODUCTION":
        raise err_state()
    # step 12, in listed order
    if any(c["lot_id"] == lotId and c["supplier_part_id"] == part_id and
           c["supplier_lot_number"] == supplier_lot_number
           for c in DB["components"].values()):
        raise ApiError("ERR_DUPLICATE_COMPONENT_LOT", 409,
                       "(lot_id, supplier_part_id, supplier_lot_number) already recorded")
    if part["quantity_remaining"] < quantity_used:
        raise ApiError("ERR_INSUFFICIENT_PART_QUANTITY", 409,
                       "quantity_used exceeds the part's quantity_remaining")
    supplier = DB["suppliers"].get(part["supplier_id"])
    if part["status"] != "QUALIFIED" or supplier is None or supplier["status"] != "QUALIFIED":
        raise ApiError("ERR_PART_NOT_QUALIFIED", 409,
                       "Component commit requires part and supplier both QUALIFIED")
    comp = new_entity({
        "lot_id": lotId,
        "supplier_part_id": part_id,
        "quantity_used": quantity_used,
        "supplier_lot_number": supplier_lot_number,
    })
    DB["components"][comp["id"]] = comp
    part["quantity_remaining"] -= quantity_used
    part["quantity_committed"] += quantity_used
    bump(part)
    return success(serialize(comp), 201)


@bp.get("/api/lot-components")
def list_components():
    return _list("components", ["lot_id", "supplier_part_id"])


@bp.get("/api/lot-components/<id>")
def get_component(id):
    context()
    return success(serialize(get_or_404("components", id)), 200)


@bp.delete("/api/lot-components/<id>")
def delete_component(id):
    uid, role = context()
    require_role(role, PRODUCTION_OPERATOR)
    comp = get_or_404("components", id)
    lot = DB["lots"].get(comp["lot_id"])
    if lot is None or lot["disposition_status"] != "IN_PRODUCTION":
        raise err_state()
    part = DB["parts"].get(comp["supplier_part_id"])
    if part is not None:
        part["quantity_committed"] -= comp["quantity_used"]
        part["quantity_remaining"] += comp["quantity_used"]
        bump(part)
    del DB["components"][id]
    return "", 204


# ---------------------------------------------------------------------------
# UDI labels
# ---------------------------------------------------------------------------

@bp.post("/api/device-lots/<lotId>/udi-labels")
def create_label(lotId):
    uid, role = context()
    require_role(role, PRODUCTION_OPERATOR)
    data = get_body()
    udi_di = req_str(data, "udi_di")
    # step 3: exactly 14 digits, then the GS1 check digit (same priority)
    if len(udi_di) != 14 or not udi_di.isdigit():
        raise err_validation("udi_di must be exactly 14 digits")
    if not udi_check_digit_ok(udi_di):
        raise err_udi_check()
    lot = get_or_404("lots", lotId)
    dmr = DB["dmrs"].get(lot["dmr_id"])
    udi_pi = "LOT-" + lot["lot_number"] + "-EXP-" + lot["expiry_date"].strftime("%Y%m%d")
    label = new_entity({
        "lot_id": lotId,
        "udi_di": udi_di,
        "udi_pi": udi_pi,
        "label_revision": dmr["revision_code"] if dmr is not None else None,
        "status": "DRAFT",
        "printed_at": None,
        "void_reason": "NONE",
    })
    DB["labels"][label["id"]] = label
    return success(serialize(label), 201)


@bp.get("/api/udi-labels")
def list_labels():
    return _list("labels", ["lot_id", "status"])


@bp.get("/api/udi-labels/<id>")
def get_label(id):
    context()
    return success(serialize(get_or_404("labels", id)), 200)


@bp.post("/api/udi-labels/<id>/approve")
def approve_label(id):
    uid, role = context()
    require_role(role, QUALITY_MANAGER)
    label = get_or_404("labels", id)
    lot = DB["lots"].get(label["lot_id"])
    # step 7: label DRAFT and lot still in flight
    if label["status"] != "DRAFT":
        raise err_state()
    if lot is None or lot["disposition_status"] not in ("IN_PRODUCTION", "COMPLETED"):
        raise err_state()
    # step 9: some revision of the lot's device-code family must be APPROVED
    dmr = DB["dmrs"].get(lot["dmr_id"])
    family_approved = approved_revision_of_family(dmr["device_code"]) if dmr is not None else None
    if family_approved is None:
        raise ApiError("ERR_DMR_NOT_APPROVED", 409,
                       "No revision of the lot's device-code family is APPROVED")
    # step 11: label_revision must equal that APPROVED revision's code
    if label["label_revision"] != family_approved["revision_code"]:
        raise ApiError("ERR_LABEL_REVISION_MISMATCH", 422,
                       "label_revision does not match the currently APPROVED family revision")
    # step 12: one active label per lot
    if any(l["id"] != id and l["lot_id"] == label["lot_id"] and
           l["status"] in ("APPROVED", "PRINTED") for l in DB["labels"].values()):
        raise ApiError("ERR_ACTIVE_LABEL_EXISTS", 409,
                       "Another label of this lot is APPROVED or PRINTED")
    label["status"] = "APPROVED"
    bump(label)
    return success(serialize(label), 200)


@bp.post("/api/udi-labels/<id>/print")
def print_label(id):
    uid, role = context()
    require_role(role, PRODUCTION_OPERATOR)
    label = get_or_404("labels", id)
    if label["status"] != "APPROVED":
        raise err_state()
    lot = DB["lots"].get(label["lot_id"])
    if lot is None or lot["disposition_status"] != "COMPLETED":
        raise ApiError("ERR_LOT_NOT_COMPLETED", 409,
                       "Label print requires the lot disposition COMPLETED")
    label["status"] = "PRINTED"
    label["printed_at"] = now()
    bump(label)
    return success(serialize(label), 200)


@bp.post("/api/udi-labels/<id>/void")
def void_label(id):
    uid, role = context()
    require_role(role, QUALITY_MANAGER)
    label = get_or_404("labels", id)
    if label["status"] not in ("DRAFT", "APPROVED", "PRINTED"):
        raise err_state()
    label["status"] = "VOID"
    label["void_reason"] = "MANUAL"
    bump(label)
    return success(serialize(label), 200)
