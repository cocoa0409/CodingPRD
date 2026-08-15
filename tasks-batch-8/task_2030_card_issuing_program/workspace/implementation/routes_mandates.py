"""Mandate and MandateAck endpoints (segregation-of-duties workflow)."""
from flask import Blueprint, request

from core import (
    STORE, ApiError, ok, ok_list, body, req_field, req_enum,
    new_entity, touch, pub, sort_created, get_or_404, require_roles,
    parse_dt, fmt_dt, now, current_role, current_user_id,
    NETWORKS, SEVERITIES,
)

bp = Blueprint("mandates", __name__)

MANDATE_READ = ("ComplianceOfficer", "ProgramManager", "PlatformAdmin")
ACK_READ = ("ComplianceOfficer", "ProgramManager", "PlatformAdmin")


def _get_mandate(mid):
    return get_or_404("mandates", mid, "mandate")


def _get_ack(mid, aid):
    ack = get_or_404("acks", aid, "mandate acknowledgement")
    if ack["mandate_id"] != mid:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "mandate acknowledgement %s not found under mandate %s"
                       % (aid, mid))
    return ack


# ---------------------------------------------------------------------------
# Mandate
# ---------------------------------------------------------------------------

@bp.post("/issuing/mandates")
@require_roles("ComplianceOfficer")
def create_mandate():
    data = body()
    network = req_enum(data, "network", NETWORKS)
    mandate_code = req_field(data, "mandate_code")
    if not isinstance(mandate_code, str) or not mandate_code:
        raise ApiError("ERR_VALIDATION", 400, "mandate_code must be a non-empty string")
    title = req_field(data, "title")
    if not isinstance(title, str) or not title:
        raise ApiError("ERR_VALIDATION", 400, "title must be a non-empty string")
    try:
        effective_at = parse_dt(req_field(data, "effective_at"))
        compliance_deadline = parse_dt(req_field(data, "compliance_deadline"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400,
                       "effective_at/compliance_deadline must be ISO8601 timestamps")
    if not compliance_deadline > effective_at:
        raise ApiError("ERR_VALIDATION", 400,
                       "compliance_deadline must be strictly after effective_at")
    severity = req_enum(data, "severity", SEVERITIES)
    for m in STORE["mandates"].values():
        if m["network"] == network and m["mandate_code"] == mandate_code:
            raise ApiError("ERR_VALIDATION", 409,
                           "mandate_code must be unique per network")
    m = new_entity()
    m.update({
        "network": network,
        "mandate_code": mandate_code,
        "title": title,
        "effective_at": fmt_dt(effective_at),
        "compliance_deadline": fmt_dt(compliance_deadline),
        "severity": severity,
        "status": "ANNOUNCED",
        "_effective_at": effective_at,
        "_compliance_deadline": compliance_deadline,
    })
    STORE["mandates"][m["id"]] = m
    return ok(pub(m), 201)


@bp.get("/issuing/mandates")
@require_roles(*MANDATE_READ)
def list_mandates():
    items = list(STORE["mandates"].values())
    for param in ("network", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [m for m in items if m.get(param) == val]
    return ok_list([pub(m) for m in sort_created(items)])


@bp.get("/issuing/mandates/<mid>")
@require_roles(*MANDATE_READ)
def get_mandate(mid):
    return ok(pub(_get_mandate(mid)))


@bp.post("/issuing/mandates/<mid>/retire")
@require_roles("ComplianceOfficer")
def retire_mandate(mid):
    m = _get_mandate(mid)
    if m["status"] not in ("ANNOUNCED", "EFFECTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "retire requires status ANNOUNCED or EFFECTIVE")
    was_effective = m["status"] == "EFFECTIVE"
    if was_effective:
        for ack in STORE["acks"].values():
            if ack["mandate_id"] == mid and ack["status"] == "SUBMITTED":
                raise ApiError("ERR_MANDATE_HAS_OPEN_ACKS", 409,
                               "a MandateAck is still SUBMITTED for this mandate")
    m["status"] = "RETIRED"
    touch(m)
    affected_programs = set()
    for ack in STORE["acks"].values():
        if ack["mandate_id"] == mid:
            affected_programs.add(ack["program_id"])
            if ack["status"] in ("DRAFT", "RETURNED"):
                ack["status"] = "REJECTED"
                touch(ack)
    if was_effective:
        # Recompute each affected program's lock: locked iff some ack is
        # SUBMITTED against a still-active (non-RETIRED) mandate.
        for pid in affected_programs:
            prog = STORE["programs"].get(pid)
            if prog is None:
                continue
            locked = False
            for ack in STORE["acks"].values():
                if ack["program_id"] != pid or ack["status"] != "SUBMITTED":
                    continue
                other = STORE["mandates"].get(ack["mandate_id"])
                if other is not None and other["status"] in ("ANNOUNCED", "EFFECTIVE"):
                    locked = True
                    break
            prog["authorization_rules_locked"] = locked
            if not locked and prog.get("_lock_ack_id") is not None and \
                    STORE["acks"].get(prog["_lock_ack_id"], {}).get("mandate_id") == mid:
                prog["_lock_ack_id"] = None
            touch(prog)
    return ok(pub(m))


# ---------------------------------------------------------------------------
# MandateAck
# ---------------------------------------------------------------------------

@bp.post("/issuing/mandates/<mid>/acks")
@require_roles("ComplianceOfficer")
def create_ack(mid):
    _get_mandate(mid)
    data = body()
    program_id = req_field(data, "program_id")
    if not isinstance(program_id, str) or program_id not in STORE["programs"]:
        raise ApiError("ERR_INVALID_REFERENCE", 422,
                       "program_id does not resolve to an existing program")
    notes = data.get("implementation_notes", "")
    if not isinstance(notes, str):
        raise ApiError("ERR_VALIDATION", 400,
                       "implementation_notes must be a string")
    ack = new_entity()
    ack.update({
        "mandate_id": mid,
        "program_id": program_id,
        "implementation_notes": notes,
        "submitted_by_role": None,
        "submitted_by_user_id": None,
        "verified_by_user_id": None,
        "revision_count": 0,
        "status": "DRAFT",
    })
    STORE["acks"][ack["id"]] = ack
    return ok(pub(ack), 201)


@bp.get("/issuing/mandates/<mid>/acks")
@require_roles(*ACK_READ)
def list_acks(mid):
    _get_mandate(mid)
    items = [a for a in STORE["acks"].values() if a["mandate_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    return ok_list([pub(a) for a in sort_created(items)])


@bp.get("/issuing/programs/<pid>/mandate-acks")
@require_roles("ComplianceOfficer", "ProgramManager", "PlatformAdmin")
def list_program_acks(pid):
    get_or_404("programs", pid, "program")
    items = [a for a in STORE["acks"].values() if a["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return ok_list([pub(a) for a in sort_created(items)])


@bp.get("/issuing/mandates/<mid>/acks/<aid>")
@require_roles(*ACK_READ)
def get_ack(mid, aid):
    return ok(pub(_get_ack(mid, aid)))


def _release_lock(prog):
    prog["authorization_rules_locked"] = False
    prog["_lock_ack_id"] = None
    touch(prog)


@bp.post("/issuing/mandates/<mid>/acks/<aid>/submit")
@require_roles("ComplianceOfficer")
def submit_ack(mid, aid):
    m = _get_mandate(mid)
    ack = _get_ack(mid, aid)
    if ack["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "submit requires status DRAFT or RETURNED")
    if m["status"] not in ("ANNOUNCED", "EFFECTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "mandate must be ANNOUNCED or EFFECTIVE")
    prog = STORE["programs"].get(ack["program_id"])
    if prog is None or prog["posture"] not in ("LIVE", "SUNSETTING"):
        raise ApiError("ERR_PROGRAM_NOT_EDITABLE", 409,
                       "program posture must be LIVE or SUNSETTING")
    if prog["authorization_rules_locked"] and prog.get("_lock_ack_id") != aid:
        raise ApiError("ERR_PROGRAM_RULES_LOCKED", 409,
                       "program authorization rules are locked by another ack")
    was_returned = ack["status"] == "RETURNED"
    ack["status"] = "SUBMITTED"
    if was_returned:
        ack["revision_count"] += 1
    ack["submitted_by_role"] = current_role()
    ack["submitted_by_user_id"] = current_user_id()
    prog["authorization_rules_locked"] = True
    prog["_lock_ack_id"] = aid
    touch(prog)
    touch(ack)
    return ok(pub(ack))


@bp.post("/issuing/mandates/<mid>/acks/<aid>/return")
@require_roles("ComplianceOfficer")
def return_ack(mid, aid):
    _get_mandate(mid)
    ack = _get_ack(mid, aid)
    if ack["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "return requires status SUBMITTED")
    if current_user_id() == ack["submitted_by_user_id"]:
        raise ApiError("ERR_SOD_SAME_USER", 409,
                       "returning operator must differ from the submitter")
    ack["status"] = "RETURNED"
    prog = STORE["programs"].get(ack["program_id"])
    if prog is not None:
        _release_lock(prog)
    touch(ack)
    return ok(pub(ack))


@bp.post("/issuing/mandates/<mid>/acks/<aid>/verify")
@require_roles("ComplianceOfficer")
def verify_ack(mid, aid):
    m = _get_mandate(mid)
    ack = _get_ack(mid, aid)
    if ack["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "verify requires status SUBMITTED")
    if current_user_id() == ack["submitted_by_user_id"]:
        raise ApiError("ERR_SOD_SAME_USER", 409,
                       "verifying operator must differ from the submitter")
    if not now() < m["_compliance_deadline"]:
        raise ApiError("ERR_MANDATE_DEADLINE_PASSED", 409,
                       "mandate compliance deadline has passed")
    ack["status"] = "VERIFIED"
    ack["verified_by_user_id"] = current_user_id()
    prog = STORE["programs"].get(ack["program_id"])
    if prog is not None:
        _release_lock(prog)
    touch(ack)
    return ok(pub(ack))


@bp.post("/issuing/mandates/<mid>/acks/<aid>/reject")
@require_roles("ComplianceOfficer")
def reject_ack(mid, aid):
    _get_mandate(mid)
    ack = _get_ack(mid, aid)
    if ack["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "reject requires status SUBMITTED")
    if current_user_id() == ack["submitted_by_user_id"]:
        raise ApiError("ERR_SOD_SAME_USER", 409,
                       "rejecting operator must differ from the submitter")
    ack["status"] = "REJECTED"
    prog = STORE["programs"].get(ack["program_id"])
    if prog is not None:
        _release_lock(prog)
    touch(ack)
    return ok(pub(ack))
