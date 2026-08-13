"""Bidder routes."""

from flask import Blueprint

import errors
import middleware as mw
import response
from db import stores

bp = Blueprint("bidders", __name__)

ADMIN = ["GalaAdmin"]
READ = mw.ALL_ROLES


@bp.post("/bidders")
def create_bidder():
    mw.require_auth(ADMIN)
    body = mw.get_json_body()
    gala_event_id = mw.require_string(body, "gala_event_id")
    mw.get_or_404("gala_events", gala_event_id)
    full_name = mw.require_string(body, "full_name")
    email = mw.require_string(body, "email")
    paddle_no = mw.require_int(body, "paddle_no")
    payment_method_on_file = mw.require_bool(body, "payment_method_on_file")
    for b in stores["bidders"].values():
        if b["gala_event_id"] == gala_event_id and b["paddle_no"] == paddle_no:
            raise errors.err_paddle_taken()
    rec = mw.new_record()
    rec["gala_event_id"] = gala_event_id
    rec["full_name"] = full_name
    rec["email"] = email
    rec["paddle_no"] = paddle_no
    rec["payment_method_on_file"] = payment_method_on_file
    rec["status"] = "REGISTERED"
    stores["bidders"][rec["id"]] = rec
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/bidders/<rid>")
def get_bidder(rid):
    mw.require_auth(READ)
    return response.success_object(mw.serialize(mw.get_or_404("bidders", rid)))


@bp.post("/bidders/<rid>/status")
def set_bidder_status(rid):
    mw.require_auth(ADMIN)
    bidder = mw.get_or_404("bidders", rid)
    body = mw.get_json_body()
    target = mw.require_enum(body, "status", {"REGISTERED", "SUSPENDED"})
    if bidder["status"] == target:
        raise errors.err_invalid_state(f"Bidder already {target}")
    bidder["status"] = target
    mw.touch(bidder)
    return response.success_object(mw.serialize(bidder))


@bp.get("/bidders/<rid>/bids")
def list_bidder_bids(rid):
    mw.require_auth(READ)
    bidder = mw.get_or_404("bidders", rid)
    limit, offset = mw.parse_pagination()
    items = [b for b in stores["bids"].values() if b["bidder_id"] == bidder["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(b) for b in page], limit, offset, total)
