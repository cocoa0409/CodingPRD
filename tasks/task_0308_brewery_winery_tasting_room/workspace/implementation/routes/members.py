"""Member routes (PRD §3.6). Linear lifecycle; SUSPEND fires a deep cascade."""
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import (
    err, ERR_INVALID_STATE, ERR_AGE_RESTRICTION, ERR_NOT_RESOURCE_OWNER,
)
from middleware import authenticate, authorize
from response import success
from serialize import public
from domain import is_of_age
from club_service import cancel_scheduled_shipments
from validate import (
    get_json_body, require_str, require_enum, get_or_404, resolve_winery_fk,
)
from pagination import paginate, sorted_by_creation
from util import parse_datetime

bp = Blueprint("members", __name__)


def _new_member(winery_id, full_name, email, date_of_birth, ship_to_state_code):
    m = common_fields()
    m.update({
        "winery_id": winery_id,
        "full_name": full_name,
        "email": email,
        "date_of_birth": date_of_birth,
        "ship_to_state_code": ship_to_state_code,
        "status": "PROSPECT",
    })
    return m


@bp.route("/members", methods=["POST"])
def create_member():
    _, role = authenticate()
    authorize(role, ["ClubManager"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    dob = require_str(body, "date_of_birth")
    ship_to_state = require_str(body, "ship_to_state_code")
    parse_datetime(dob, "date_of_birth")  # field validity
    with db.lock:
        resolve_winery_fk(winery_id)
        m = _new_member(winery_id, full_name, email, dob, ship_to_state)
        db.members[m["id"]] = m
        return success(public(m), status=201)


@bp.route("/members", methods=["GET"])
def list_members():
    _, role = authenticate()
    authorize(role, ["ClubManager", "ComplianceOfficer"])
    with db.lock:
        items = list(db.members.values())
        winery_id = request.args.get("winery_id")
        status = request.args.get("status")
        ship_to_state = request.args.get("ship_to_state_code")
        if winery_id is not None:
            items = [m for m in items if m["winery_id"] == winery_id]
        if status is not None:
            items = [m for m in items if m["status"] == status]
        if ship_to_state is not None:
            items = [m for m in items if m["ship_to_state_code"] == ship_to_state]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(m) for m in page], pagination=pg)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    user_id, role = authenticate()
    authorize(role, ["ClubManager", "Member"])
    with db.lock:
        m = get_or_404(db.members, member_id)
        # Member self-service ownership (PRD §2.1): a Member may read only its own record
        if role == "Member" and user_id != m["id"]:
            raise err(ERR_NOT_RESOURCE_OWNER, "Member may only read its own record")
        return success(public(m))


@bp.route("/members/<member_id>/transitions", methods=["POST"])
def transition_member(member_id):
    _, role = authenticate()
    authorize(role, ["ClubManager"])
    with db.lock:
        m = get_or_404(db.members, member_id)
        body = get_json_body()
        action = require_enum(body, "action", {"ACTIVATE", "SUSPEND", "REINSTATE", "CLOSE"})
        winery = db.wineries.get(m["winery_id"])

        if action == "ACTIVATE":
            if m["status"] != "PROSPECT":
                raise err(ERR_INVALID_STATE, "Member is not PROSPECT")
            if not is_of_age(m["date_of_birth"]):
                raise err(ERR_AGE_RESTRICTION, "Member is under the minimum age")
            m["status"] = "ACTIVE"
            touch(m)

        elif action == "SUSPEND":
            if m["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "Member is not ACTIVE")
            m["status"] = "SUSPENDED"
            touch(m)
            # CASCADE hop 1: ACTIVE memberships -> PAUSED
            for ms in db.memberships.values():
                if ms["member_id"] == m["id"] and ms["status"] == "ACTIVE":
                    ms["status"] = "PAUSED"
                    touch(ms)
                    # CASCADE hop 2: SCHEDULED shipments -> CANCELLED, free reservations
                    cancel_scheduled_shipments(ms)

        elif action == "REINSTATE":
            if m["status"] != "SUSPENDED":
                raise err(ERR_INVALID_STATE, "Member is not SUSPENDED")
            m["status"] = "ACTIVE"
            touch(m)

        else:  # CLOSE
            if m["status"] not in ("ACTIVE", "SUSPENDED"):
                raise err(ERR_INVALID_STATE, "Member is not ACTIVE or SUSPENDED")
            for ms in db.memberships.values():
                if ms["member_id"] == m["id"] and ms["status"] == "ACTIVE":
                    raise err(ERR_INVALID_STATE, "Member still has an ACTIVE membership")
            m["status"] = "CLOSED"
            touch(m)

        return success(public(m))
