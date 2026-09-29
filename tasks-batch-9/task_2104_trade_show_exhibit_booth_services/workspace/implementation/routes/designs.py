"""Exhibit designs and the rental-versus-purchase quote (PRD §3.3)."""
from flask import Blueprint

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, require_roles
from routes.assets import _new_asset
from services import calc
from validation import json_body, require_row

bp = Blueprint("designs", __name__)
store = db.store

DESIGN_STATUSES = ("DRAFT", "QUOTED", "APPROVED", "RELEASED_TO_FAB", "CANCELLED")
QUOTE_FIELDS = ("rental_quote_cents", "purchase_quote_cents", "rental_per_show_cents",
                "purchase_per_show_cents", "breakeven_show_count", "quoted_price_cents")


def _venue_of_booth(booth):
    show = store.shows.get(booth["show_id"])
    if show is None:
        return None
    return store.venues.get(show["venue_id"])


def _check_hanging_sign(design, booth):
    if not design["has_hanging_sign"]:
        return
    venue = _venue_of_booth(booth)
    permitted = (venue or {}).get("hanging_sign_booth_types") or []
    if booth["booth_type"] not in permitted:
        raise ApiError("ERR_HANGING_SIGN_NOT_PERMITTED",
                       "The venue does not permit a hanging sign on this booth type")


@bp.post("/exhibit-designs")
def create_design():
    require_roles("Exhibitor")
    body = json_body()
    own_exhibitor(body.peek_str("exhibitor_id"))
    exhibitor_id = body.string("exhibitor_id")
    booth_id = body.string("booth_id")
    sqft = body.integer("sqft")
    linear_feet = body.integer("linear_feet")
    mode = body.enum("selected_acquisition_mode", ("RENTAL", "PURCHASE"))
    has_sign = body.boolean("has_hanging_sign", required=False, default=False)
    expected_show_count = body.integer("expected_show_count", required=False, default=1)
    if expected_show_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", "expected_show_count must be at least 1")

    require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND", "Exhibitor")
    booth = require_row(store.booths, booth_id, "ERR_BOOTH_NOT_FOUND", "Booth")

    design = {
        "id": db.new_id(),
        "exhibitor_id": exhibitor_id,
        "booth_id": booth_id,
        "asset_id": None,
        "sqft": sqft,
        "linear_feet": linear_feet,
        "has_hanging_sign": has_sign,
        "expected_show_count": expected_show_count,
        "selected_acquisition_mode": mode,
        "rental_quote_cents": None,
        "purchase_quote_cents": None,
        "rental_per_show_cents": None,
        "purchase_per_show_cents": None,
        "breakeven_show_count": None,
        "quoted_price_cents": None,
        "revision_count": 0,
        "status": "DRAFT",
    }
    _check_hanging_sign(design, booth)
    db.stamp_common(design)
    store.designs[design["id"]] = design
    return response.created(design)


@bp.get("/exhibit-designs/<design_id>")
def get_design(design_id):
    require_roles(ANY_ROLE)
    design = store.designs.get(design_id)
    own_exhibitor(design["exhibitor_id"] if design else None)
    design = require_row(store.designs, design_id, "ERR_DESIGN_NOT_FOUND", "Design")
    return response.ok(design)


@bp.get("/exhibit-designs")
def list_designs():
    require_roles(ANY_ROLE)
    rows = list(store.designs.values())
    rows = response.filter_rows(rows, "exhibitor_id", "booth_id", "asset_id", "status")
    return response.listing(rows)


@bp.post("/exhibit-designs/<design_id>/quote")
def quote_design(design_id):
    require_roles("Exhibitor")
    body = json_body()
    design = store.designs.get(design_id)
    own_exhibitor(design["exhibitor_id"] if design else None)
    mode = body.enum("selected_acquisition_mode", ("RENTAL", "PURCHASE"), required=False,
                     default=None)
    design = require_row(store.designs, design_id, "ERR_DESIGN_NOT_FOUND", "Design")
    booth = store.booths.get(design["booth_id"])

    guards.transition(design["status"], ("CANCELLED",), ("DRAFT",))
    if booth is not None:
        guards.booth_not_frozen(booth)
    if int(design["revision_count"]) > calc.MAX_DESIGN_REVISIONS:
        raise ApiError("ERR_DESIGN_REVISION_LIMIT", "The revision budget is exhausted")
    if booth is not None:
        _check_hanging_sign(design, booth)

    if mode is not None:
        design["selected_acquisition_mode"] = mode

    quote = calc.acquisition_quote(design["sqft"], design["linear_feet"],
                                   design["has_hanging_sign"],
                                   design["expected_show_count"],
                                   design["selected_acquisition_mode"])
    design.update(quote)
    design["status"] = "QUOTED"
    db.touch(design)
    return response.ok(design)


@bp.post("/exhibit-designs/<design_id>/decision")
def decide_design(design_id):
    require_roles("ShowOperations")
    body = json_body()
    decision = body.enum("decision", ("APPROVE", "REQUEST_REVISION", "CANCEL"))
    body.string("note", required=False, default=None)
    design = require_row(store.designs, design_id, "ERR_DESIGN_NOT_FOUND", "Design")
    booth = store.booths.get(design["booth_id"])

    if decision == "APPROVE":
        guards.transition(design["status"], ("CANCELLED",), ("QUOTED",))
        if booth is not None:
            guards.booth_open(booth)
        if design["quoted_price_cents"] is None:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The design carries no quoted price")
        design["status"] = "APPROVED"
    elif decision == "REQUEST_REVISION":
        guards.transition(design["status"], ("CANCELLED",), ("QUOTED",))
        if int(design["revision_count"]) >= calc.MAX_DESIGN_REVISIONS:
            raise ApiError("ERR_DESIGN_REVISION_LIMIT",
                           "The design revision budget is exhausted")
        design["revision_count"] = int(design["revision_count"]) + 1
        for field in QUOTE_FIELDS:
            design[field] = None
        design["status"] = "DRAFT"
    else:  # CANCEL
        guards.transition(design["status"], ("CANCELLED",),
                          ("DRAFT", "QUOTED", "APPROVED"))
        if design["asset_id"] is not None:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "An asset has already been minted from this design")
        design["status"] = "CANCELLED"

    db.touch(design)
    return response.ok(design)


@bp.post("/exhibit-designs/<design_id>/release")
def release_design(design_id):
    require_roles("ShowOperations")
    json_body()
    design = require_row(store.designs, design_id, "ERR_DESIGN_NOT_FOUND", "Design")
    booth = store.booths.get(design["booth_id"])

    guards.transition(design["status"], ("CANCELLED",), ("APPROVED",))
    if booth is not None:
        guards.booth_not_frozen(booth)

    asset = _new_asset(design["exhibitor_id"], design["selected_acquisition_mode"],
                       design["quoted_price_cents"],
                       int(design["sqft"]) * calc.ASSET_LBS_PER_SQFT, "A", None)
    design["asset_id"] = asset["id"]
    design["status"] = "RELEASED_TO_FAB"
    db.touch(design)
    return response.ok(design)
