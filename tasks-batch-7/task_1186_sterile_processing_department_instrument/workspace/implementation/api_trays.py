"""Trays: registration, reprocessing pipeline, assembly verifications, discard."""
from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, ApiError, auth, created, get_body, invalid_request, ok, ok_list,
    paginate, pagination, query_str, req_fk, req_present,
    req_string,
)

bp = Blueprint("trays", __name__)


def _validate_verification_lines(value):
    if not isinstance(value, list):
        raise invalid_request("Field 'lines' must be a list.")
    lines = []
    for line in value:
        if not isinstance(line, dict):
            raise invalid_request("lines entries must be objects.")
        itype = line.get("instrument_type")
        if not isinstance(itype, str) or not itype:
            raise invalid_request(
                "lines entries need an instrument_type string.")
        qty = line.get("counted_qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            raise invalid_request(
                "lines counted_qty must be an integer >= 0.")
        lines.append({"instrument_type": itype, "counted_qty": qty})
    return lines


@bp.post("/spd/trays")
def create_tray():
    auth(("SpdTechnician",))
    body = get_body()
    template = req_fk(body, "template_id", store.TRAY_TEMPLATES, "TrayTemplate")
    label = req_string(body, "label")

    record = store.new_record()
    record.update({
        "template_id": template["id"],
        "label": label,
        "status": "AWAITING_DECONTAMINATION",
        "current_load_id": None,
        "sterility_expires_at": None,
        "cycles_completed": 0,
        "quarantine_reason": None,
    })
    store.TRAYS[record["id"]] = record
    return created(views.tray_view(record))


@bp.get("/spd/trays")
def list_trays():
    auth(ANY)
    limit, offset = pagination()
    template_id = query_str("template_id")
    current_load_id = query_str("current_load_id")
    status = query_str("status")
    domain.sweep_all_trays()
    rows = [r for r in store.TRAYS.values()
            if (template_id is None or r["template_id"] == template_id)
            and (current_load_id is None or r["current_load_id"] == current_load_id)
            and (status is None or r["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.tray_view(r) for r in page], limit, offset, total)


@bp.get("/spd/trays/<tray_id>")
def get_tray(tray_id):
    auth(ANY)
    tray = store.fetch(store.TRAYS, tray_id)
    domain.sweep_tray(tray)
    return ok(views.tray_view(tray))


@bp.post("/spd/trays/<tray_id>/decontamination/start")
def start_decontamination(tray_id):
    auth(("SpdTechnician",))
    tray = store.fetch(store.TRAYS, tray_id)
    domain.sweep_tray(tray)
    if tray["status"] not in ("AWAITING_DECONTAMINATION", "QUARANTINED"):
        raise ApiError("ERR_TRAY_NOT_READY_FOR_DECONTAMINATION", 409,
                       "decontamination/start requires status "
                       "AWAITING_DECONTAMINATION or QUARANTINED.")
    if tray["status"] == "QUARANTINED":
        tray["quarantine_reason"] = None
    tray["status"] = "IN_DECONTAMINATION"
    store.touch(tray)
    return ok(views.tray_view(tray))


@bp.post("/spd/trays/<tray_id>/decontamination/complete")
def complete_decontamination(tray_id):
    auth(("SpdTechnician",))
    tray = store.fetch(store.TRAYS, tray_id)
    domain.sweep_tray(tray)
    if tray["status"] != "IN_DECONTAMINATION":
        raise ApiError("ERR_TRAY_NOT_IN_DECONTAMINATION", 409,
                       "decontamination/complete requires IN_DECONTAMINATION.")
    tray["status"] = "DECONTAMINATED"
    store.touch(tray)
    return ok(views.tray_view(tray))


@bp.post("/spd/trays/<tray_id>/assembly/start")
def start_assembly(tray_id):
    auth(("SpdTechnician",))
    tray = store.fetch(store.TRAYS, tray_id)
    domain.sweep_tray(tray)
    if tray["status"] != "DECONTAMINATED":
        raise ApiError("ERR_TRAY_NOT_DECONTAMINATED", 409,
                       "assembly/start requires DECONTAMINATED.")
    tray["status"] = "IN_ASSEMBLY"
    store.touch(tray)
    return ok(views.tray_view(tray))


@bp.post("/spd/trays/<tray_id>/assembly-verifications")
def submit_assembly_verification(tray_id):
    actor = auth(("SpdTechnician",))
    tray = store.fetch(store.TRAYS, tray_id)
    domain.sweep_tray(tray)
    body = get_body()
    lines = _validate_verification_lines(req_present(body, "lines"))

    if tray["status"] != "IN_ASSEMBLY":
        raise ApiError("ERR_TRAY_NOT_IN_ASSEMBLY", 409,
                       "assembly-verifications require tray IN_ASSEMBLY.")

    template = store.TRAY_TEMPLATES.get(tray["template_id"])
    requirements = (template or {}).get("instrument_requirements") or []
    required = {}
    for line in requirements:
        required[line["instrument_type"]] = line["quantity"]
    counted = {}
    for line in lines:
        counted[line["instrument_type"]] = (
            counted.get(line["instrument_type"], 0) + line["counted_qty"])

    mismatch = 0
    for itype, qty in required.items():
        if counted.get(itype, 0) != qty:
            mismatch += 1
    for itype in counted:
        if itype not in required:
            mismatch += 1
    result = "PASS" if mismatch == 0 else "FAIL"

    record = store.new_record(with_version=False)
    record.update({
        "tray_id": tray["id"],
        "technician_id": actor.user_id,
        "lines": lines,
        "result": result,
        "mismatch_count": mismatch,
    })
    store.ASSEMBLY_VERIFICATIONS[record["id"]] = record

    if result == "PASS":
        tray["status"] = "ASSEMBLED"
        store.touch(tray)
    else:
        # FAIL keeps the tray IN_ASSEMBLY and records a 2-point demerit.
        domain.add_competency_event(actor.user_id, domain.FAIL_VERIFY_PTS)

    return created(views.assembly_verification_view(record))


@bp.get("/spd/assembly-verifications")
def list_assembly_verifications():
    auth(ANY)
    limit, offset = pagination()
    tray_id = query_str("tray_id")
    technician_id = query_str("technician_id")
    result = query_str("result")
    rows = [r for r in store.ASSEMBLY_VERIFICATIONS.values()
            if (tray_id is None or r["tray_id"] == tray_id)
            and (technician_id is None or r["technician_id"] == technician_id)
            and (result is None or r["result"] == result)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.assembly_verification_view(r) for r in page],
                   limit, offset, total)


@bp.get("/spd/assembly-verifications/<verification_id>")
def get_assembly_verification(verification_id):
    auth(ANY)
    record = store.fetch(store.ASSEMBLY_VERIFICATIONS, verification_id)
    return ok(views.assembly_verification_view(record))


@bp.post("/spd/trays/<tray_id>/discard")
def discard_tray(tray_id):
    auth(("SpdSupervisor",))
    tray = store.fetch(store.TRAYS, tray_id)
    domain.sweep_tray(tray)
    if tray["status"] != "QUARANTINED":
        raise ApiError("ERR_TRAY_NOT_QUARANTINED", 409,
                       "discard requires tray QUARANTINED.")
    tray["status"] = "DISCARDED"
    store.touch(tray)
    return ok(views.tray_view(tray))
