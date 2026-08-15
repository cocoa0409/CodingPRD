"""Deficiency items: identify, classify, decide, repair loop, withdraw,
sign-off (PRD §3.4/§3.5)."""
from flask import Blueprint, request

import db
from db import appointments, communities, deficiency_items, homes
from errors import (
    err_invalid_state, err_not_found, err_photo_evidence,
    err_referenced_entity_not_found, err_withdraw_not_allowed,
)
from logic import (
    escrow_on_decide, identification_cascade, recompute_home,
)
from middleware import (
    ROLE_BUYER, ROLE_MANAGER, ROLE_REP, check_buyer_ownership, require_roles,
)
from response import paginate, success_list, success_object
from validation import json_body, opt_str, req_enum, req_int, req_str

bp = Blueprint("deficiency_items", __name__)

READ_ROLES = (ROLE_MANAGER, ROLE_REP, ROLE_BUYER)
SYSTEM_KEYS = ("HVAC", "PLUMBING", "ELECTRICAL", "APPLIANCES", "EXTERIOR", "SAFETY", "OTHER")
CLASSIFICATIONS = ("WARRANTABLE", "COSMETIC")
RESOLUTIONS = ("COMPLETE_BEFORE_CLOSING", "COMPLETE_AFTER_CLOSING")


def _get_item_or_404(item_id):
    item = deficiency_items.get(item_id)
    if item is None:
        raise err_not_found("Deficiency item %s not found." % item_id)
    return item


def _buyer_scoped_item(actor, item_id):
    """Resolve the item for ownership (priority 3) before schema/existence:
    when the item exists, the buyer ownership check fires first."""
    item = deficiency_items.get(item_id)
    if item is not None:
        check_buyer_ownership(actor, homes[item["home_id"]])
    return item


@bp.post("/api/deficiency-items")
def create_deficiency_item():
    require_roles(ROLE_REP)
    body = json_body()
    home_id = req_str(body, "home_id")
    appointment_id = req_str(body, "appointment_id")
    system_key = body.get("system_key")
    if system_key is not None and (not isinstance(system_key, str) or system_key not in SYSTEM_KEYS):
        from errors import err_validation
        raise err_validation("Field 'system_key' must be one of %s." % sorted(SYSTEM_KEYS))
    title = req_str(body, "title")
    description = opt_str(body, "description")

    home = homes.get(home_id)
    appt = appointments.get(appointment_id)
    if home is None or appt is None:
        raise err_referenced_entity_not_found("home_id or appointment_id does not resolve.")
    if appt["home_id"] != home_id:
        raise err_referenced_entity_not_found("appointment_id does not belong to home_id.")
    if appt["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise err_invalid_state("Deficiencies can only be identified on an IN_PROGRESS or COMPLETED appointment.")

    rec = db.stamp({
        "id": db.new_id(),
        "home_id": home_id,
        "appointment_id": appointment_id,
        "system_key": system_key,
        "title": title,
        "description": description,
        "classification": None,
        "estimated_repair_cost_cents": None,
        "photo_evidence_ref": None,
        "resolution": None,
        "status": "IDENTIFIED",
        "signed_off_at": None,
        "holdback_released": False,
    })
    deficiency_items[rec["id"]] = rec
    identification_cascade(home)
    return success_object(db.public(rec), status=201)


@bp.get("/api/deficiency-items/<item_id>")
def get_deficiency_item(item_id):
    require_roles(*READ_ROLES)
    return success_object(db.public(_get_item_or_404(item_id)))


@bp.get("/api/deficiency-items")
def list_deficiency_items():
    require_roles(*READ_ROLES)
    items = list(deficiency_items.values())
    for f in ("home_id", "appointment_id", "status", "classification"):
        v = request.args.get(f)
        if v is not None:
            items = [i for i in items if i.get(f) == v]
    items.sort(key=db.sort_key)
    page, pagination = paginate(items, request.args)
    return success_list([db.public(i) for i in page], pagination)


@bp.post("/api/deficiency-items/<item_id>/classify")
def classify_item(item_id):
    require_roles(ROLE_REP)
    body = json_body()
    classification = req_enum(body, "classification", CLASSIFICATIONS)
    cost = req_int(body, "estimated_repair_cost_cents", minimum=0)
    photo_ref = opt_str(body, "photo_evidence_ref")

    item = _get_item_or_404(item_id)
    if item["status"] != "IDENTIFIED":
        raise err_invalid_state("Only an IDENTIFIED item can be classified.")
    home = homes[item["home_id"]]
    community = communities[home["community_id"]]
    if classification == "COSMETIC" and community["cosmetic_photo_required"] and not photo_ref:
        raise err_photo_evidence()

    item["classification"] = classification
    item["estimated_repair_cost_cents"] = cost
    item["photo_evidence_ref"] = photo_ref
    item["status"] = "CLASSIFIED"
    db.touch(item)
    return success_object(db.public(item))


@bp.post("/api/deficiency-items/<item_id>/decide")
def decide_item(item_id):
    require_roles(ROLE_MANAGER)
    body = json_body()
    resolution = req_enum(body, "resolution", RESOLUTIONS)

    item = _get_item_or_404(item_id)
    if item["status"] not in ("CLASSIFIED", "DECIDED"):
        raise err_invalid_state("Only a CLASSIFIED or DECIDED item can be decided.")

    item["resolution"] = resolution
    item["status"] = "DECIDED"
    db.touch(item)
    home = homes[item["home_id"]]
    escrow_on_decide(home)
    recompute_home(home)
    return success_object(db.public(item))


@bp.post("/api/deficiency-items/<item_id>/start-repair")
def start_repair(item_id):
    require_roles(ROLE_REP)
    item = _get_item_or_404(item_id)
    if item["status"] != "DECIDED":
        raise err_invalid_state("Only a DECIDED item can start repair.")
    item["status"] = "IN_REPAIR"
    db.touch(item)
    recompute_home(homes[item["home_id"]])
    return success_object(db.public(item))


@bp.post("/api/deficiency-items/<item_id>/complete-repair")
def complete_repair(item_id):
    require_roles(ROLE_REP)
    item = _get_item_or_404(item_id)
    if item["status"] != "IN_REPAIR":
        raise err_invalid_state("Only an IN_REPAIR item can complete repair.")
    item["status"] = "READY_FOR_REINSPECTION"
    db.touch(item)
    recompute_home(homes[item["home_id"]])
    return success_object(db.public(item))


@bp.post("/api/deficiency-items/<item_id>/withdraw")
def withdraw_item(item_id):
    actor = require_roles(ROLE_BUYER)
    item = _buyer_scoped_item(actor, item_id)
    json_body()
    if item is None:
        raise err_not_found("Deficiency item %s not found." % item_id)
    if item["status"] == "IDENTIFIED":
        pass  # always withdrawable
    elif item["status"] == "CLASSIFIED" and item["classification"] == "COSMETIC":
        pass
    else:
        # WARRANTABLE-classified, or any item past CLASSIFIED (PRD §3.4)
        raise err_withdraw_not_allowed()
    item["status"] = "WITHDRAWN"
    db.touch(item)
    return success_object(db.public(item))


@bp.post("/api/deficiency-items/<item_id>/sign-off")
def sign_off_item(item_id):
    actor = require_roles(ROLE_BUYER)
    item = _buyer_scoped_item(actor, item_id)
    json_body()
    if item is None:
        raise err_not_found("Deficiency item %s not found." % item_id)
    if item["status"] != "VERIFIED":
        raise err_invalid_state("Only a VERIFIED item can be signed off.")
    item["status"] = "SIGNED_OFF"
    item["signed_off_at"] = db.fmt_dt(db.now())
    db.touch(item)
    recompute_home(homes[item["home_id"]])
    return success_object(db.public(item))
