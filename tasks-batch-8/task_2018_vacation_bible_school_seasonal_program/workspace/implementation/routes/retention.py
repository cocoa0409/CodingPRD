"""Retention list: generation at COMPLETED, invite, record-response (PRD §3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import store
from auth import authenticate, require_role
from derived import retention_entry_view, days_of_program, attended_days
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_RETENTION_EXISTS,
)
from routes.common import paginate, empty_body, guard_program_writable
from util import round4_dec
from validate import Field, get_body, validate_body

bp = Blueprint("retention", __name__)

_GENERATE_SPEC = {
    "force": Field("bool", default=False),
}

_RESPONSE_SPEC = {
    "outcome": Field("enum", enum={"YES", "NO"}, required=True),
}

TIER_A_RATE = Decimal("0.80")
TIER_A_BONUS_RATE = Decimal("0.60")
TIER_B_RATE = Decimal("0.50")


def get_entry_or_404(entry_id):
    entry = store.get("retention_entries", entry_id)
    if entry is None:
        raise_err(ERR_NOT_FOUND, "retention entry not found")
    return entry


def _family_volunteer_bonus(child):
    """True iff a volunteer linked to the child's family ever reached CONFIRMED."""
    for vol in store.all_of("volunteers"):
        if vol["family_id"] != child["family_id"]:
            continue
        for ra in store.all_of("role_assignments"):
            if ra["volunteer_id"] == vol["id"] and ra["status"] in ("CONFIRMED", "RELEASED"):
                return True
    return False


def _priority_tier(rate, bonus):
    if rate >= TIER_A_RATE or (rate >= TIER_A_BONUS_RATE and bonus):
        return "A"
    if rate >= TIER_B_RATE or bonus:
        return "B"
    return "C"


def _make_entry(program, child, total_days):
    attended = attended_days(program["id"], child["id"])
    rate = round4_dec(attended, total_days)
    bonus = _family_volunteer_bonus(child)
    entry = store.new_record(
        program_id=program["id"],
        child_id=child["id"],
        attended_days=attended,
        attendance_rate=float(rate),
        family_volunteer_bonus=bonus,
        priority_tier=_priority_tier(rate, bonus),
        status="LISTED",
    )
    store.put("retention_entries", entry)
    return entry


@bp.post("/vbs/programs/<program_id>/retention-list/generate")
def generate_retention(program_id):
    body = get_body()
    data = validate_body(body, _GENERATE_SPEC)
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    program = store.get("programs", program_id)
    if program is None:
        raise_err(ERR_NOT_FOUND, "program not found")
    if program["status"] != "COMPLETED":
        raise_err(ERR_INVALID_STATE, "retention generation requires a COMPLETED program")
    existing = [
        e for e in store.all_of("retention_entries") if e["program_id"] == program["id"]
    ]
    if existing and not data["force"]:
        raise_err(ERR_RETENTION_EXISTS, "retention entries already exist; pass force to regenerate")
    regenerated = bool(existing)
    preserved_children = set()
    for entry in list(existing):
        if entry["status"] in ("RESPONDED_YES", "RESPONDED_NO"):
            preserved_children.add(entry["child_id"])
        else:
            store.delete("retention_entries", entry["id"])
    total_days = len(days_of_program(program["id"]))
    day_ids = {d["id"] for d in days_of_program(program["id"])}
    qualifying_child_ids = []
    seen = set()
    for rec in store.by_seq(store.all_of("attendance_records")):
        if (
            rec["program_day_id"] in day_ids
            and rec["status"] == "CHECKED_OUT"
            and rec["child_id"] not in seen
        ):
            seen.add(rec["child_id"])
            qualifying_child_ids.append(rec["child_id"])
    created_count = 0
    for child_id in qualifying_child_ids:
        if child_id in preserved_children:
            continue
        child = store.get("children", child_id)
        if child is None:
            continue
        _make_entry(program, child, total_days)
        created_count += 1
    return ok_object({"created_count": created_count, "regenerated": regenerated}, status=201)


@bp.get("/vbs/retention-entries/<entry_id>")
def get_entry(entry_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    return ok_object(retention_entry_view(get_entry_or_404(entry_id)))


@bp.get("/vbs/retention-entries")
def list_entries():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator")
    items = list(store.all_of("retention_entries"))
    program_id = request.args.get("program_id")
    child_id = request.args.get("child_id")
    priority_tier = request.args.get("priority_tier")
    status = request.args.get("status")
    if program_id is not None:
        items = [e for e in items if e["program_id"] == program_id]
    if child_id is not None:
        items = [e for e in items if e["child_id"] == child_id]
    if priority_tier is not None:
        items = [e for e in items if e["priority_tier"] == priority_tier]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate(items, retention_entry_view)


@bp.post("/vbs/retention-entries/<entry_id>/invite")
def invite_entry(entry_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    entry = get_entry_or_404(entry_id)
    guard_program_writable(store.get("programs", entry["program_id"]))
    if entry["status"] != "LISTED":
        raise_err(ERR_INVALID_STATE, "only a LISTED entry may be invited")
    entry["status"] = "INVITED"
    store.touch(entry)
    return ok_object(retention_entry_view(entry))


@bp.post("/vbs/retention-entries/<entry_id>/record-response")
def record_response(entry_id):
    body = get_body()
    data = validate_body(body, _RESPONSE_SPEC)
    ctx = authenticate()
    require_role(ctx, "ProgramDirector")
    entry = get_entry_or_404(entry_id)
    guard_program_writable(store.get("programs", entry["program_id"]))
    if entry["status"] != "INVITED":
        raise_err(ERR_INVALID_STATE, "only an INVITED entry may record a response")
    entry["status"] = "RESPONDED_YES" if data["outcome"] == "YES" else "RESPONDED_NO"
    store.touch(entry)
    return ok_object(retention_entry_view(entry))
