"""Clients, staff, organizations, rooms."""
from flask import Blueprint, request

import db
from auth import require, get_or_404
from envelope import ok, ok_list, paginate
from errors import ApiError, bad_request, forbidden, invalid_state
from util import (body_json, req_str, opt_str, opt_int, req_int, req_enum,
                  parse_date)

bp = Blueprint("registry", __name__)


# ---------------------------------------------------------------------------
# household graph helpers
# ---------------------------------------------------------------------------

def creates_household_cycle(client_id, head_id):
    """True when making head_id the head of client_id creates a cycle:
    the client itself, or any descendant chain leading back to it."""
    cur = head_id
    seen = set()
    while cur:
        if cur == client_id:
            return True
        if cur in seen:
            return False  # pre-existing cycle elsewhere; do not loop forever
        seen.add(cur)
        nxt = db.get("clients", cur)
        cur = nxt.get("household_head_id") if nxt else None
    return False


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

@bp.route("/clients", methods=["POST"])
def create_client():
    require("IntakeSpecialist", "CenterAdmin")
    data = body_json()

    # rung 3: body-referenced ids (household_head_id)
    head_id = data.get("household_head_id")
    if head_id is not None:
        if not isinstance(head_id, str):
            raise bad_request("household_head_id must be a string")
        get_or_404("clients", head_id, "client")

    # rung 7: structural
    full_name = req_str(data, "full_name")
    preferred_language = req_str(data, "preferred_language")
    dob = parse_date(req_str(data, "date_of_birth"), "date_of_birth")
    household_size = opt_int(data, "household_size", 1, minimum=1)
    country = opt_str(data, "country_of_origin", None)
    arrival = data.get("arrival_date")
    if arrival is not None:
        arrival = parse_date(arrival, "arrival_date")

    client = db.new_entity("clients", {
        "full_name": full_name,
        "preferred_language": preferred_language,
        "date_of_birth": dob,
        "household_size": household_size,
        "country_of_origin": country,
        "arrival_date": arrival,
        "household_head_id": head_id,
        "status": "REGISTERED",
        "reportable": False,
    })
    return ok(db.pub(client), status=201)


@bp.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    user_id, role = require("CenterAdmin", "CaseManager", "IntakeSpecialist",
                            "Client")
    if role == "Client" and client_id != user_id:
        raise forbidden("clients may read only their own record")
    client = get_or_404("clients", client_id, "client")
    return ok(db.pub(client))


@bp.route("/clients", methods=["GET"])
def list_clients():
    user_id, role = require("CenterAdmin", "CaseManager", "IntakeSpecialist",
                            "Client")
    items = db.all_of("clients")
    if role == "Client":
        items = [c for c in items if c["id"] == user_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    head = request.args.get("household_head_id")
    if head is not None:
        items = [c for c in items if c.get("household_head_id") == head]
    page, meta = paginate(items)
    return ok_list([db.pub(c) for c in page], meta)


@bp.route("/clients/<client_id>/exit", methods=["POST"])
def exit_client(client_id):
    require("CaseManager", "CenterAdmin")
    client = get_or_404("clients", client_id, "client")
    if client["status"] == "EXITED":
        raise invalid_state("client has already exited")
    open_cases = [c for c in db.all_of("cases")
                  if c["client_id"] == client_id
                  and c["service_status"] != "CLOSED"]
    if open_cases:
        raise invalid_state("all cases must be CLOSED before exit")
    client["status"] = "EXITED"
    db.touch(client)
    return ok(db.pub(client))


@bp.route("/clients/<client_id>", methods=["PATCH"])
def patch_client(client_id):
    require("IntakeSpecialist", "CaseManager", "CenterAdmin")
    client = get_or_404("clients", client_id, "client")
    data = body_json()
    if "household_head_id" in data:
        head_id = data["household_head_id"]
        if head_id is not None:
            if not isinstance(head_id, str):
                raise bad_request("household_head_id must be a string")
            get_or_404("clients", head_id, "client")
            if creates_household_cycle(client_id, head_id):
                raise ApiError("ERR_HOUSEHOLD_HEAD_CYCLE", 409,
                               "household_head_id would create a cycle")
        client["household_head_id"] = head_id
    db.touch(client)
    return ok(db.pub(client))


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

@bp.route("/staff", methods=["POST"])
def create_staff():
    require("CenterAdmin")
    data = body_json()
    full_name = req_str(data, "full_name")
    role_level = req_enum(data, "role_level",
                          {"ADMIN", "CASE_MANAGER", "INTAKE"})
    clearance = req_int(data, "clearance_level")
    if clearance < 1 or clearance > 3:
        raise bad_request("clearance_level must be in 1..3")
    capacity = req_int(data, "weekly_appointment_capacity", minimum=0)
    staff = db.new_entity("staff", {
        "full_name": full_name,
        "role_level": role_level,
        "clearance_level": clearance,
        "weekly_appointment_capacity": capacity,
        "status": "ACTIVE",
    })
    return ok(db.pub(staff), status=201)


@bp.route("/staff/<staff_id>", methods=["GET"])
def get_staff(staff_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    staff = get_or_404("staff", staff_id, "staff")
    return ok(db.pub(staff))


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

ORG_CATEGORIES = {"HOUSING", "EMPLOYMENT", "EDUCATION", "LEGAL", "HEALTH"}


@bp.route("/organizations", methods=["POST"])
def create_org():
    require("CenterAdmin")
    data = body_json()
    name = req_str(data, "name")
    cats = data.get("service_categories")
    if not isinstance(cats, list) or not cats:
        raise bad_request("service_categories must be a non-empty array")
    for c in cats:
        if c not in ORG_CATEGORIES:
            raise bad_request(f"unknown service category: {c!r}")
    capacity = req_int(data, "referral_capacity", minimum=0)
    email = req_str(data, "contact_email")
    org = db.new_entity("organizations", {
        "name": name,
        "service_categories": list(cats),
        "referral_capacity": capacity,
        "referral_slots_used": 0,
        "referral_slots_open": capacity,
        "contact_email": email,
        "status": "ACTIVE",
    })
    return ok(db.pub(org), status=201)


@bp.route("/organizations/<organization_id>", methods=["GET"])
def get_org(organization_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist", "PartnerOrg")
    org = get_or_404("organizations", organization_id, "organization")
    return ok(db.pub(org))


@bp.route("/organizations/<organization_id>/suspend", methods=["POST"])
def suspend_org(organization_id):
    require("CenterAdmin")
    org = get_or_404("organizations", organization_id, "organization")
    if org["status"] != "ACTIVE":
        raise invalid_state("organization is not ACTIVE")
    org["status"] = "SUSPENDED"
    db.touch(org)
    return ok(db.pub(org))


@bp.route("/organizations/<organization_id>/reactivate", methods=["POST"])
def reactivate_org(organization_id):
    require("CenterAdmin")
    org = get_or_404("organizations", organization_id, "organization")
    if org["status"] != "SUSPENDED":
        raise invalid_state("organization is not SUSPENDED")
    org["status"] = "ACTIVE"
    db.touch(org)
    return ok(db.pub(org))


# ---------------------------------------------------------------------------
# Rooms (no updated_at / version — rooms never mutate)
# ---------------------------------------------------------------------------

@bp.route("/rooms", methods=["POST"])
def create_room():
    require("CenterAdmin")
    data = body_json()
    name = req_str(data, "name")
    capacity = req_int(data, "capacity", minimum=1)
    if any(r["name"] == name for r in db.all_of("rooms")):
        raise bad_request("room name must be unique")
    room = db.new_entity("rooms", {"name": name, "capacity": capacity},
                         common=False)
    return ok(db.pub(room), status=201)
