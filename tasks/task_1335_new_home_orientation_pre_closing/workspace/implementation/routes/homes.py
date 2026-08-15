"""Home lifecycle: create, read/list, mark-ready, reschedule-closing, close
(PRD §3.1, §3.7)."""
from flask import Blueprint, request

import db
from db import communities, escrows, homebuyers, homes
from errors import (
    err_invalid_state, err_not_found, err_referenced_entity_not_found,
    err_stale_version, err_funding_mismatch, err_validation,
)
from logic import FINAL_ESCROW_STATUSES, escrow_amount, non_voided_escrow
from middleware import ROLE_BUYER, ROLE_MANAGER, ROLE_REP, require_roles
from response import paginate, success_list, success_object
from validation import json_body, req_datetime_str, req_int, req_str, req_version

bp = Blueprint("homes", __name__)

READ_ROLES = (ROLE_MANAGER, ROLE_REP, ROLE_BUYER)


def _get_home_or_404(home_id):
    home = homes.get(home_id)
    if home is None:
        raise err_not_found("Home %s not found." % home_id)
    return home


@bp.post("/api/homes")
def create_home():
    require_roles(ROLE_MANAGER)
    body = json_body()
    community_id = req_str(body, "community_id")
    primary_buyer_id = req_str(body, "primary_buyer_id")
    lot_number = req_str(body, "lot_number")
    address = req_str(body, "address")
    sales_price_cents = req_int(body, "sales_price_cents")
    closing_date = req_datetime_str(body, "closing_date")
    if community_id not in communities:
        raise err_referenced_entity_not_found("community_id does not resolve.")
    if primary_buyer_id not in homebuyers:
        raise err_referenced_entity_not_found("primary_buyer_id does not resolve.")
    rec = db.stamp({
        "id": db.new_id(),
        "community_id": community_id,
        "primary_buyer_id": primary_buyer_id,
        "lot_number": lot_number,
        "address": address,
        "sales_price_cents": sales_price_cents,
        "closing_date": closing_date,
        "status": "UNDER_CONSTRUCTION",
        "open_before_closing_count": 0,
        "open_after_closing_count": 0,
    })
    homes[rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.get("/api/homes/<home_id>")
def get_home(home_id):
    require_roles(*READ_ROLES)
    return success_object(db.public(_get_home_or_404(home_id)))


@bp.get("/api/homes")
def list_homes():
    require_roles(*READ_ROLES)
    items = list(homes.values())
    for f in ("community_id", "primary_buyer_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [h for h in items if h.get(f) == v]
    items.sort(key=db.sort_key)
    page, pagination = paginate(items, request.args)
    return success_list([db.public(h) for h in page], pagination)


@bp.post("/api/homes/<home_id>/mark-ready")
def mark_ready(home_id):
    require_roles(ROLE_MANAGER)
    home = _get_home_or_404(home_id)
    if home["status"] != "UNDER_CONSTRUCTION":
        raise err_invalid_state("mark-ready is only valid from UNDER_CONSTRUCTION.")
    home["status"] = "PRE_CLOSE_READY"
    db.touch(home)
    return success_object(db.public(home))


@bp.post("/api/homes/<home_id>/reschedule-closing")
def reschedule_closing(home_id):
    require_roles(ROLE_MANAGER)
    body = json_body()
    closing_date = req_datetime_str(body, "closing_date")
    expected = req_version(body, "expected_home_version")
    home = _get_home_or_404(home_id)
    if expected != home["version"]:
        raise err_stale_version("expected_home_version does not match the home's current version.")
    home["closing_date"] = closing_date
    db.touch(home)
    return success_object(db.public(home))


@bp.post("/api/homes/<home_id>/close")
def close_home(home_id):
    require_roles(ROLE_MANAGER)
    body = json_body()
    funded_given = "funded_holdback_cents" in body and body["funded_holdback_cents"] is not None
    if funded_given:
        funded = req_int(body, "funded_holdback_cents")
    else:
        funded = None
    home = _get_home_or_404(home_id)
    if home["status"] != "READY_TO_CLOSE":
        raise err_invalid_state("Only a READY_TO_CLOSE home can be closed.")

    escrow = non_voided_escrow(home_id)
    community = communities[home["community_id"]]
    final_amount = escrow_amount(home, community, FINAL_ESCROW_STATUSES) if escrow else 0

    if escrow is not None and final_amount > 0:
        if funded is None:
            raise err_validation("funded_holdback_cents is required and must equal the final holdback.")
        if funded != final_amount:
            raise err_funding_mismatch()
    else:
        if funded is not None:
            raise err_validation("funded_holdback_cents must be omitted when no holdback is due.")
        funded = 0

    if escrow is not None:
        escrow["final_holdback_cents"] = final_amount
        escrow["funded_amount_cents"] = funded
        escrow["remaining_amount_cents"] = funded - escrow["released_amount_cents"]
        if final_amount == 0 and escrow["status"] == "DRAFT":
            escrow["status"] = "VOIDED"
        db.touch(escrow)
    home["status"] = "CLOSED"
    db.touch(home)
    return success_object(db.public(home))
