"""Disposable packs, surgeon adjudication and pre-bypass pump checklists."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import serialize
import svc
import valid as V
from auth import (ROLE_CHIEF, ROLE_CONTRACT_ADMIN, ROLE_PERFUSIONIST, ROLE_SURGEON, endpoint)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, ordered, stamp_new, touch

D = Decimal
bp = Blueprint("packs", __name__)

PACK_READ = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST, ROLE_SURGEON)
CHECKLIST_READ = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST)


def _validate_substitutions(body):
    entries = V.varray(body, "substitutions", min_len=0,
                       max_len=C.MAX_SUBSTITUTIONS_PER_PACK, default=[])
    seen = set()
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_FIELD_VALUE", "substitutions entries must be objects.")
        code = V.vstr(entry, "line_code")
        replacement = V.vstr(entry, "replacement_code")
        cost = V.vint(entry, "replacement_unit_cost_cents", minimum=1)
        reason = V.vstr(entry, "reason", allow_empty=True)
        if code is None or replacement is None or cost is None:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "substitutions entries require line_code, replacement_code and "
                           "replacement_unit_cost_cents.")
        if code in seen:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "substitutions line_code values must be unique.")
        seen.add(code)
        out.append({"line_code": code, "replacement_code": replacement,
                    "replacement_unit_cost_cents": cost, "reason": reason})
    return out


@bp.post("/bypass-cases/<cid>/disposable-packs")
@endpoint([ROLE_PERFUSIONIST, ROLE_CHIEF])
def configure_pack(actor, cid):
    body = V.payload()
    V.require(body, "primary_device_id")
    primary_id = V.vstr(body, "primary_device_id", required=True)
    supplied_backup_id = V.vstr(body, "backup_device_id")
    substitutions = _validate_substitutions(body)

    case = svc.get_case(cid)
    primary = svc.get_device(primary_id)
    if supplied_backup_id is not None:
        svc.get_device(supplied_backup_id)

    if case["bypass_status"] != "STAFFED":
        raise ApiError("ERR_CASE_NOT_STAFFED")

    if (primary["device_class"] != "HEART_LUNG_MACHINE"
            or primary["contract_id"] != case["contract_id"]
            or primary["status"] not in ("AVAILABLE", "RESERVED")):
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE")

    backup_id = supplied_backup_id or primary.get("backup_device_id")
    backup = db.perfusion_devices.get(backup_id) if backup_id else None
    if backup is not None and backup["status"] not in ("AVAILABLE", "RESERVED"):
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE")

    if D(primary["runtime_hours_since_service"]) >= D(primary["service_interval_hours"]):
        raise ApiError("ERR_DEVICE_SERVICE_OVERDUE")

    if backup_id is None:
        raise ApiError("ERR_NO_BACKUP_DEVICE_AVAILABLE")
    if backup is None:
        raise ApiError("ERR_DEVICE_NOT_FOUND")
    if (backup["id"] == primary["id"]
            or backup["device_class"] != "HEART_LUNG_MACHINE"
            or backup["contract_id"] != case["contract_id"]):
        raise ApiError("ERR_INVALID_BACKUP_DEVICE")

    card = calc.select_preference_card(case["surgeon_id"], case["procedure_type"])
    if card is None:
        raise ApiError("ERR_NO_ACTIVE_PREFERENCE_CARD")

    template_codes = set(li["line_code"] for li in card["pack_line_items"])
    for sub in substitutions:
        if sub["line_code"] not in template_codes:
            raise ApiError("ERR_INVALID_SUBSTITUTION_LINE")

    for device in (primary, backup):
        for other in svc.cases_holding_device(device["id"], "either",
                                              C.RESERVATION_HOLDING_STATUSES):
            if other["id"] == case["id"]:
                continue
            if svc.turnaround_collides(case["scheduled_start"], case["scheduled_end"],
                                       other["scheduled_start"], other["scheduled_end"]):
                raise ApiError("ERR_DEVICE_TURNAROUND_CONFLICT")

    contract = db.hospital_contracts[case["contract_id"]]
    line_items, pack_cost = calc.disposable_pack_cost(contract, card, substitutions)
    requires_approval = len(substitutions) > 0

    pack = {
        "case_id": case["id"],
        "applied_preference_card_id": card["id"],
        "line_items": line_items,
        "substitutions": substitutions,
        "requires_surgeon_approval": requires_approval,
        "approval_status": "PENDING" if requires_approval else "NOT_REQUIRED",
        "pack_cost_cents": pack_cost,
        "prime_volume_ml": card["prime_volume_ml"],
    }
    stamp_new(pack)
    insert("disposable_packs", pack)

    case["primary_device_id"] = primary["id"]
    case["backup_device_id"] = backup["id"]
    case["readiness_flag"] = "NONE"
    case["bypass_status"] = "PACK_CONFIGURED"
    touch(case)

    for device in (primary, backup):
        if device["status"] == "AVAILABLE":
            device["status"] = "RESERVED"
        touch(device)

    return ok(serialize.pack(pack), 201)


@bp.get("/disposable-packs/<pid>")
@endpoint(PACK_READ)
def read_pack(actor, pid):
    return ok(serialize.pack(svc.get_pack(pid)))


@bp.get("/disposable-packs")
@endpoint(PACK_READ)
def list_packs(actor):
    limit, offset = V.pagination()
    rows = ordered("disposable_packs")
    for key in ("case_id", "applied_preference_card_id", "approval_status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return ok_list([serialize.pack(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/disposable-packs/<pid>/approve")
@endpoint([ROLE_SURGEON])
def approve_pack(actor, pid):
    body = V.payload()
    V.require(body, "decision")
    decision = V.venum(body, "decision", ("APPROVED", "REJECTED"), required=True)
    V.vstr(body, "note", allow_empty=True)
    pack = svc.get_pack(pid)
    case = db.bypass_cases.get(pack["case_id"])
    if case is None or actor.user_id != case["surgeon_id"]:
        raise ApiError("ERR_NOT_CARD_OWNER")
    if pack["approval_status"] != "PENDING":
        raise ApiError("ERR_PACK_APPROVAL_STATE_INVALID")
    pack["approval_status"] = decision
    touch(pack)
    return ok(serialize.pack(pack))


# ---------------------------------------------------------- checklists

def _validate_check_results(body):
    entries = V.varray(body, "check_results", min_len=1, max_len=20, required=True)
    seen = set()
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_FIELD_VALUE", "check_results entries must be objects.")
        code = V.vstr(entry, "check_code")
        passed = V.vbool(entry, "passed")
        note = V.vstr(entry, "note", allow_empty=True)
        if code is None or passed is None:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "check_results entries require check_code and passed.")
        if code in seen:
            raise ApiError("ERR_INVALID_FIELD_VALUE", "check_results check_code values must be unique.")
        seen.add(code)
        out.append({"check_code": code, "passed": passed, "note": note})
    return out


def _missing_codes(case_id, check_results):
    pack = svc.case_latest_pack(case_id)
    if pack is None:
        return []
    card = db.preference_cards.get(pack["applied_preference_card_id"])
    if card is None:
        return []
    passed = set(cr["check_code"] for cr in check_results if cr["passed"])
    missing = [code for code in card["required_safety_check_codes"] if code not in passed]
    return sorted(missing)


@bp.post("/bypass-cases/<cid>/pump-checklists")
@endpoint([ROLE_PERFUSIONIST, ROLE_CHIEF])
def create_checklist(actor, cid):
    body = V.payload()
    V.require(body, "check_results", "blood_management_protocol", "hematocrit_pct")
    row = {
        "case_id": cid,
        "verified_by_perfusionist_id": None,
        "check_results": _validate_check_results(body),
        "blood_management_protocol": V.venum(body, "blood_management_protocol",
                                             C.BLOOD_PROTOCOLS, required=True),
        "hematocrit_pct": V.vnum(body, "hematocrit_pct", minimum=5, maximum=45, required=True),
        "blood_mgmt_signoff": False,
        "status": "DRAFT",
        "verified_at": None,
        "missing_check_codes": [],
    }
    case = svc.get_case(cid)
    if case["bypass_status"] != "PACK_CONFIGURED":
        raise ApiError("ERR_CASE_NOT_PACK_CONFIGURED")
    row["missing_check_codes"] = _missing_codes(cid, row["check_results"])
    stamp_new(row)
    insert("pump_checklists", row)
    return ok(serialize.checklist(row), 201)


@bp.get("/pump-checklists/<clid>")
@endpoint(CHECKLIST_READ)
def read_checklist(actor, clid):
    return ok(serialize.checklist(svc.get_checklist(clid)))


@bp.get("/pump-checklists")
@endpoint(CHECKLIST_READ)
def list_checklists(actor):
    limit, offset = V.pagination()
    rows = ordered("pump_checklists")
    for key in ("case_id", "verified_by_perfusionist_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return ok_list([serialize.checklist(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/pump-checklists/<clid>/verify")
@endpoint([ROLE_PERFUSIONIST])
def verify_checklist(actor, clid):
    checklist = svc.get_checklist(clid)
    case = db.bypass_cases.get(checklist["case_id"])
    if case is None or actor.user_id != case.get("assigned_perfusionist_id"):
        raise ApiError("ERR_NOT_ASSIGNED_PERFUSIONIST")
    if case["bypass_status"] != "PACK_CONFIGURED":
        raise ApiError("ERR_CASE_NOT_PACK_CONFIGURED")
    if checklist["status"] != "DRAFT":
        raise ApiError("ERR_CHECKLIST_NOT_DRAFT")

    pack = svc.case_latest_pack(case["id"])
    card = db.preference_cards.get(pack["applied_preference_card_id"]) if pack else None

    missing = _missing_codes(case["id"], checklist["check_results"])
    if missing:
        raise ApiError("ERR_SAFETY_CHECKS_INCOMPLETE")
    if card is not None and checklist["blood_management_protocol"] != card["blood_management_protocol"]:
        raise ApiError("ERR_BLOOD_PROTOCOL_MISMATCH")
    if card is not None and D(checklist["hematocrit_pct"]) < D(card["min_hematocrit_pct"]):
        raise ApiError("ERR_HEMATOCRIT_BELOW_MINIMUM")
    if pack is not None and pack["approval_status"] not in ("NOT_REQUIRED", "APPROVED"):
        raise ApiError("ERR_PACK_APPROVAL_PENDING")

    now = db.now()
    checklist["status"] = "VERIFIED"
    checklist["blood_mgmt_signoff"] = True
    checklist["verified_by_perfusionist_id"] = actor.user_id
    checklist["verified_at"] = now
    checklist["missing_check_codes"] = missing
    touch(checklist)

    case["bypass_status"] = "SETUP_VERIFIED"
    case["setup_verified_at"] = now
    touch(case)

    return ok(serialize.checklist(checklist))
