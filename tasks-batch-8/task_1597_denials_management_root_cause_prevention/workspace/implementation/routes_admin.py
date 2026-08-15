"""Routes: logical clock, payers, payer appeal policies, remittance codes,
prevention programs."""

from flask import Blueprint, request

from auth import require_roles
from cascades import run_expiry_sweep
from db import store
from envelope import list_response, ok
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_POLICY_WINDOW_OVERLAP,
    ERR_PROGRAM_WINDOW_OVERLAP,
    ERR_VALIDATION,
)
from services import find_payer, find_policy, find_program, make_record, public, touch
from util import (
    ALL_ROLES,
    ATTACHMENT_TYPES,
    CATEGORIES,
    DEPARTMENTS,
    PAYER_STATUSES,
    PLAN_TYPES,
    fmt_clock,
    get_body,
    opt_bool,
    opt_date,
    opt_enum,
    opt_enum_list,
    opt_int,
    opt_str,
    parse_date,
    parse_datetime,
    req_date,
    req_enum,
    req_int,
    req_number,
    req_str,
    req_value,
    sort_created,
)

bp = Blueprint("admin", __name__)

RCD = ("RevenueCycleDirector",)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.post("/rcm/_clock/set_current_utc")
@require_roles(*RCD)
def set_clock():
    body = get_body()
    raw = req_value(body, "to_iso8601")
    new_clock = parse_datetime(raw, "to_iso8601")
    store.clock = new_clock
    expired_ids = run_expiry_sweep()
    return ok({"current_utc": fmt_clock(new_clock), "expired_denial_ids": expired_ids})


# ---------------------------------------------------------------------------
# Payers
# ---------------------------------------------------------------------------


@bp.post("/rcm/payers")
@require_roles(*RCD)
def create_payer():
    body = get_body()
    name = req_str(body, "name")
    plan_type = req_enum(body, "plan_type", PLAN_TYPES)
    days = req_int(body, "default_timely_filing_days")
    if days <= 0:
        raise ApiError(ERR_VALIDATION, 400, "default_timely_filing_days must be > 0")
    payer = make_record(
        {
            "name": name,
            "plan_type": plan_type,
            "default_timely_filing_days": days,
            "status": "ACTIVE",
            "appeal_policy_review_required": False,
        }
    )
    store.payers[payer["id"]] = payer
    return ok(public(payer), "object", 201)


@bp.get("/rcm/payers")
@require_roles(*ALL_ROLES)
def list_payers():
    items = list(store.payers.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    plan_type = request.args.get("plan_type")
    if plan_type is not None:
        items = [p for p in items if p["plan_type"] == plan_type]
    return list_response([public(p) for p in sort_created(items)])


@bp.get("/rcm/payers/<pid>")
@require_roles(*ALL_ROLES)
def get_payer(pid):
    return ok(public(find_payer(pid)))


@bp.patch("/rcm/payers/<pid>")
@require_roles(*RCD)
def patch_payer(pid):
    body = get_body()
    days = opt_int(body, "default_timely_filing_days")
    if days is not None and days <= 0:
        raise ApiError(ERR_VALIDATION, 400, "default_timely_filing_days must be > 0")
    status = opt_enum(body, "status", PAYER_STATUSES)
    payer = find_payer(pid)
    changed = False
    if days is not None and days != payer["default_timely_filing_days"]:
        payer["default_timely_filing_days"] = days
        changed = True
    if status is not None:
        if status == payer["status"]:
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Payer is already %s; only a toggle to the opposite status is allowed"
                % status,
            )
        payer["status"] = status
        changed = True
    if changed:
        touch(payer)
    return ok(public(payer))


# ---------------------------------------------------------------------------
# Payer appeal policies
# ---------------------------------------------------------------------------


@bp.post("/rcm/payer-appeal-policies")
@require_roles(*RCD)
def create_policy():
    body = get_body()
    payer_id = req_str(body, "payer_id")
    level = req_int(body, "level_number")
    if level < 1 or level > 3:
        raise ApiError(ERR_VALIDATION, 400, "level_number must be in 1..3")
    filing_days = req_int(body, "timely_filing_days")
    if filing_days <= 0:
        raise ApiError(ERR_VALIDATION, 400, "timely_filing_days must be > 0")
    response_days = opt_int(body, "response_window_days", 30)
    if response_days is None or response_days <= 0:
        raise ApiError(ERR_VALIDATION, 400, "response_window_days must be > 0")
    required = opt_enum_list(body, "required_attachment_types", ATTACHMENT_TYPES, [])
    eff_from = req_date(body, "effective_from")
    eff_to = opt_date(body, "effective_to")
    start = parse_date(eff_from)
    end = parse_date(eff_to) if eff_to else None
    if end is not None and end <= start:
        raise ApiError(
            ERR_VALIDATION, 400, "effective_to must be after effective_from"
        )
    find_payer(payer_id)  # 404 gate
    for pol in store.policies.values():
        if pol["payer_id"] != payer_id or pol["level_number"] != level:
            continue
        ex_start = parse_date(pol["effective_from"])
        ex_end = parse_date(pol["effective_to"]) if pol.get("effective_to") else None
        # Half-open overlap: new.from < existing.to and existing.from < new.to
        overlap = (ex_end is None or start < ex_end) and (end is None or ex_start < end)
        if overlap:
            raise ApiError(
                ERR_POLICY_WINDOW_OVERLAP,
                409,
                "Policy window overlaps an existing window for this payer and level",
            )
    policy = make_record(
        {
            "payer_id": payer_id,
            "level_number": level,
            "timely_filing_days": filing_days,
            "response_window_days": response_days,
            "required_attachment_types": required,
            "effective_from": eff_from,
            "effective_to": eff_to,
        }
    )
    store.policies[policy["id"]] = policy
    return ok(public(policy), "object", 201)


@bp.get("/rcm/payer-appeal-policies")
@require_roles(*ALL_ROLES)
def list_policies():
    items = list(store.policies.values())
    payer_id = request.args.get("payer_id")
    if payer_id is not None:
        items = [p for p in items if p["payer_id"] == payer_id]
    level_s = request.args.get("level_number")
    if level_s is not None:
        try:
            level = int(level_s)
        except ValueError:
            items = []
        else:
            items = [p for p in items if p["level_number"] == level]
    return list_response([public(p) for p in sort_created(items)])


@bp.get("/rcm/payer-appeal-policies/<pid>")
@require_roles(*ALL_ROLES)
def get_policy(pid):
    return ok(public(find_policy(pid)))


# ---------------------------------------------------------------------------
# Remittance codes
# ---------------------------------------------------------------------------


@bp.post("/rcm/remittance-codes")
@require_roles(*RCD)
def create_remittance_code():
    body = get_body()
    code = req_str(body, "code")
    category = req_enum(body, "category", CATEGORIES)
    department = req_enum(body, "default_department", DEPARTMENTS)
    appealable = opt_bool(body, "appealable", True)
    description = opt_str(body, "description", "")
    for existing in store.remittance_codes.values():
        if existing["code"] == code:
            raise ApiError(
                ERR_VALIDATION, 400, "Remittance code %s already exists" % code
            )
    rec = make_record(
        {
            "code": code,
            "category": category,
            "default_department": department,
            "appealable": appealable,
            "description": description,
        }
    )
    store.remittance_codes[rec["id"]] = rec
    return ok(public(rec), "object", 201)


@bp.get("/rcm/remittance-codes")
@require_roles(*ALL_ROLES)
def list_remittance_codes():
    items = list(store.remittance_codes.values())
    category = request.args.get("category")
    if category is not None:
        items = [c for c in items if c["category"] == category]
    appealable_s = request.args.get("appealable")
    if appealable_s is not None:
        val = appealable_s.lower()
        if val in ("true", "false"):
            flag = val == "true"
            items = [c for c in items if c["appealable"] == flag]
        else:
            items = []
    return list_response([public(c) for c in sort_created(items)])


# ---------------------------------------------------------------------------
# Prevention programs
# ---------------------------------------------------------------------------


@bp.post("/rcm/prevention-programs")
@require_roles(*RCD)
def create_program():
    body = get_body()
    department = req_enum(body, "department", DEPARTMENTS)
    name = req_str(body, "name")
    start_s = req_date(body, "start_date")
    end_s = req_date(body, "end_date")
    target = req_number(body, "target_reduction_pct")
    start = parse_date(start_s)
    end = parse_date(end_s)
    if end < start:
        raise ApiError(ERR_VALIDATION, 400, "end_date must be on or after start_date")
    if target < 0 or target > 100:
        raise ApiError(
            ERR_VALIDATION, 400, "target_reduction_pct must be between 0 and 100"
        )
    for prog in store.programs.values():
        if prog["department"] != department:
            continue
        ex_start = parse_date(prog["start_date"])
        ex_end = parse_date(prog["end_date"])
        # Closed windows: touching endpoints conflict.
        if start <= ex_end and ex_start <= end:
            raise ApiError(
                ERR_PROGRAM_WINDOW_OVERLAP,
                409,
                "Program window overlaps or touches an existing program for this department",
            )
    prog = make_record(
        {
            "department": department,
            "name": name,
            "start_date": start_s,
            "end_date": end_s,
            "target_reduction_pct": target,
            "status": "PLANNED",
        }
    )
    store.programs[prog["id"]] = prog
    return ok(public(prog), "object", 201)


@bp.get("/rcm/prevention-programs")
@require_roles(*ALL_ROLES)
def list_programs():
    items = list(store.programs.values())
    department = request.args.get("department")
    if department is not None:
        items = [p for p in items if p["department"] == department]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response([public(p) for p in sort_created(items)])


@bp.get("/rcm/prevention-programs/<pid>")
@require_roles(*ALL_ROLES)
def get_program(pid):
    return ok(public(find_program(pid)))


@bp.post("/rcm/prevention-programs/<pid>/activate")
@require_roles(*RCD)
def activate_program(pid):
    prog = find_program(pid)
    if prog["status"] != "PLANNED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only a PLANNED program can be activated"
        )
    prog["status"] = "ACTIVE"
    touch(prog)
    return ok(public(prog))


@bp.post("/rcm/prevention-programs/<pid>/complete")
@require_roles(*RCD)
def complete_program(pid):
    prog = find_program(pid)
    if prog["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE program can be completed")
    prog["status"] = "COMPLETED"
    touch(prog)
    return ok(public(prog))
