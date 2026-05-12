"""Guest routes."""
from flask import Blueprint, request

import db
from errors import (
    raise_error,
    ERR_GUEST_CAPACITY_EXCEEDED,
    ERR_TABLE_SEAT_LIMIT_EXCEEDED,
    ERR_VERSION_CONFLICT,
)
from middleware import require_roles, check_planner_owns_project
from response import success, list_response, parse_pagination
from services.lookup import (
    get_project,
    get_guest,
    assert_project_not_terminal,
)


bp = Blueprint("guests", __name__)


SCALE_CAPS = {
    "INTIMATE": 50,
    "MEDIUM": 200,
    "GRAND": 500,
}
TABLE_SEAT_LIMIT = 10


def _confirmed_total(project_id, exclude_id=None, override_party=None, override_status=None) -> int:
    total = 0
    for g in db.guests.values():
        if g["project_id"] != project_id:
            continue
        if g["id"] == exclude_id:
            # Use override values
            status = override_status if override_status is not None else g["rsvp_status"]
            party = override_party if override_party is not None else int(g["party_size"])
        else:
            status = g["rsvp_status"]
            party = int(g["party_size"])
        if status == "CONFIRMED":
            total += party
    return total


def _table_total(project_id, table_number, exclude_id=None, override_party=None) -> int:
    total = 0
    for g in db.guests.values():
        if g["project_id"] != project_id:
            continue
        if g["id"] == exclude_id:
            party = override_party if override_party is not None else int(g["party_size"])
            tnum = g.get("table_number")  # use existing table unless we override below
        else:
            party = int(g["party_size"])
            tnum = g.get("table_number")
        if tnum == table_number:
            total += party
    return total


@bp.post("/wedding-projects/<project_id>/guests")
def create_guest(project_id):
    require_roles("Planner", "Couple")
    p = get_project(project_id)
    if request.headers.get("X-User-Role") == "Planner":
        check_planner_owns_project(p)
    assert_project_not_terminal(p)
    body = request.get_json(silent=True) or {}
    party_size = int(body.get("party_size", 1))
    if party_size < 1:
        # PRD says party_size MUST be at least 1; raise capacity error
        raise_error(ERR_GUEST_CAPACITY_EXCEEDED, "party_size must be >= 1")
    guest = {
        "project_id": project_id,
        "full_name": body.get("full_name"),
        "party_size": party_size,
        "rsvp_status": "INVITED",
        "dietary_requirements": body.get("dietary_requirements") or [],
        "accessibility_requirements": body.get("accessibility_requirements") or [],
        "table_number": None,
        "gift_amount_cents": 0,
        "thank_you_sent_at": None,
    }
    db.add_common_create(guest)
    db.guests[guest["id"]] = guest
    return success(guest, status=201)


@bp.get("/wedding-projects/<project_id>/guests")
def list_guests(project_id):
    require_roles("Planner", "Auditor", "Couple")
    get_project(project_id)
    limit, offset = parse_pagination(request.args)
    rs = request.args.get("rsvp_status")
    items = [g for g in db.guests.values() if g["project_id"] == project_id]
    if rs:
        items = [g for g in items if g["rsvp_status"] == rs]
    items.sort(key=lambda g: g["created_at"])
    return list_response(items, limit, offset)


@bp.patch("/wedding-projects/<project_id>/guests/<guest_id>")
def patch_guest(project_id, guest_id):
    require_roles("Planner", "Couple")
    p = get_project(project_id)
    if request.headers.get("X-User-Role") == "Planner":
        check_planner_owns_project(p)
    assert_project_not_terminal(p)
    guest = get_guest(project_id, guest_id)
    body = request.get_json(silent=True) or {}

    # Compute candidate state for capacity / table checks
    new_party = int(body["party_size"]) if "party_size" in body else int(guest["party_size"])
    if new_party < 1:
        raise_error(ERR_GUEST_CAPACITY_EXCEEDED, "party_size must be >= 1")
    new_table = body["table_number"] if "table_number" in body else guest.get("table_number")

    # Capacity check (priority 11)
    cap = SCALE_CAPS.get(p["scale"], 0)
    new_total = _confirmed_total(project_id, exclude_id=guest_id,
                                 override_party=new_party,
                                 override_status=guest["rsvp_status"])
    if new_total > cap:
        raise_error(ERR_GUEST_CAPACITY_EXCEEDED,
                    f"Confirmed guest total {new_total} exceeds cap {cap}")

    # Table check (priority 12)
    if new_table is not None:
        if not isinstance(new_table, int) or new_table <= 0:
            raise_error(ERR_TABLE_SEAT_LIMIT_EXCEEDED, "table_number must be a positive integer")
        # Sum party_size across the table including this guest
        ttotal = 0
        for g in db.guests.values():
            if g["project_id"] != project_id:
                continue
            if g["id"] == guest_id:
                continue
            if g.get("table_number") == new_table:
                ttotal += int(g["party_size"])
        ttotal += new_party
        if ttotal > TABLE_SEAT_LIMIT:
            raise_error(ERR_TABLE_SEAT_LIMIT_EXCEEDED,
                        f"Table {new_table} would have {ttotal} seats, exceeds {TABLE_SEAT_LIMIT}")

    # OCC last (priority 15)
    new_version = body.get("version")
    if new_version is not None and int(new_version) != int(guest["version"]):
        raise_error(ERR_VERSION_CONFLICT, "Version mismatch")

    # Apply changes
    for fld in ("full_name", "party_size", "dietary_requirements",
                "accessibility_requirements", "table_number",
                "gift_amount_cents", "thank_you_sent_at"):
        if fld in body:
            guest[fld] = body[fld]
    db.bump(guest)
    return success(guest)


@bp.post("/wedding-projects/<project_id>/guests/<guest_id>/rsvp")
def set_rsvp(project_id, guest_id):
    require_roles("Planner", "Couple")
    p = get_project(project_id)
    if request.headers.get("X-User-Role") == "Planner":
        check_planner_owns_project(p)
    assert_project_not_terminal(p)
    guest = get_guest(project_id, guest_id)
    body = request.get_json(silent=True) or {}
    new_status = body.get("rsvp_status")
    if new_status not in ("INVITED", "CONFIRMED", "DECLINED", "NO_RESPONSE"):
        raise_error(ERR_GUEST_CAPACITY_EXCEEDED, "Invalid rsvp_status")
    if new_status == "CONFIRMED":
        cap = SCALE_CAPS.get(p["scale"], 0)
        new_total = _confirmed_total(project_id, exclude_id=guest_id,
                                     override_party=int(guest["party_size"]),
                                     override_status="CONFIRMED")
        if new_total > cap:
            raise_error(ERR_GUEST_CAPACITY_EXCEEDED,
                        f"Confirmed guest total {new_total} exceeds cap {cap}")
    guest["rsvp_status"] = new_status
    db.bump(guest)
    return success(guest)
