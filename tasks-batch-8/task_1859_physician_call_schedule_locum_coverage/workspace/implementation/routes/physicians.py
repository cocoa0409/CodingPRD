"""Physician registry: register/list/get/deactivate (with cascade, PRD §3.2)."""
from flask import Blueprint

import db
import validation as V
from db import store
from errors import ApiError
from middleware import require_roles
from response import ok, created, paginate
from services import domain as D

bp = Blueprint("physicians", __name__)

ADMIN = ["SchedulerAdmin"]
ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_physician_or_404(physician_id):
    physician = store.physicians.get(physician_id)
    if physician is None:
        raise ApiError("ERR_PHYSICIAN_NOT_FOUND", 404, "Physician id does not exist")
    return physician


@bp.route("/api/physicians", methods=["POST"])
def create_physician():
    require_roles(ADMIN)
    body = V.json_body()
    full_name = V.req_str(body, "full_name")
    specialty = V.req_str(body, "specialty")
    employment_type = V.req_enum(body, "employment_type", ("STAFF", "LOCUM"))
    moonlight_cap_hours = V.opt_int(body, "moonlight_cap_hours", 96)
    if moonlight_cap_hours <= 0:
        V._bad("moonlight_cap_hours must be > 0")
    physician = db.new_common({
        "full_name": full_name,
        "specialty": specialty,
        "employment_type": employment_type,
        "moonlight_cap_hours": moonlight_cap_hours,
        "status": "ACTIVE",
    })
    store.physicians[physician["id"]] = physician
    return created(physician)


@bp.route("/api/physicians", methods=["GET"])
def list_physicians():
    require_roles(ALL)
    rows = list(store.physicians.values())
    rows = paginate.filter(rows, "employment_type")
    rows = paginate.filter(rows, "status")
    rows = paginate.filter(rows, "specialty")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/physicians/<physician_id>", methods=["GET"])
def get_physician(physician_id):
    require_roles(ALL)
    return ok(get_physician_or_404(physician_id))


@bp.route("/api/physicians/<physician_id>/deactivate", methods=["POST"])
def deactivate_physician(physician_id):
    require_roles(ADMIN)
    V.json_body()
    physician = get_physician_or_404(physician_id)
    if physician["status"] != "ACTIVE":
        raise ApiError("ERR_PHYSICIAN_INACTIVE", 409, "Physician is already INACTIVE")
    now = db.now_logical()
    # Hop 1: cancel every future SCHEDULED assignment (slot.window_end > now).
    cancelled_ids = []
    for a in D.assignments_of_physician(physician["id"], ("SCHEDULED",)):
        slot = D.slot_of(a)
        if slot is not None and slot["window_end"] > now:
            D.cancel_assignment_cascade(a, "PHYSICIAN_DEACTIVATED")
            cancelled_ids.append(a["id"])
    # Hop 2: swaps referencing cancelled assignments, offered by, or claimed by
    # this physician in {POSTED, CLAIMED, APPROVED} -> CANCELLED.
    for sw in store.swaps.values():
        if sw["status"] not in D.NON_TERMINAL_SWAP_STATUSES:
            continue
        if sw["assignment_id"] in cancelled_ids \
                or sw["offerer_physician_id"] == physician["id"] \
                or sw["claimant_physician_id"] == physician["id"]:
            sw["status"] = "CANCELLED"
            db.touch(sw)
    physician["status"] = "INACTIVE"
    db.touch(physician)
    return ok(physician)
