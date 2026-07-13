"""Contact opt-out and the logical clock."""

from flask import Blueprint

import store
import validation as v
from auth import endpoint, resolve_contact
from envelope import ok
from services import touch

bp = Blueprint("misc", __name__)


@bp.post("/reputation/contacts/<contact_id>/opt-out")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager", "Anonymous"])
def opt_out(contact_id):
    contact = resolve_contact(contact_id)
    # One of only two mutations that stay legal while a location is FROZEN.
    contact["opted_out"] = True
    touch(contact)
    return ok(store.contact_out(contact))


@bp.post("/reputation/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_clock():
    data = v.body()
    instant = v.req_datetime(data, "to_iso8601")
    store.set_clock(instant)
    return ok({"current_utc": store.iso(instant)})
