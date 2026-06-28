"""Logical clock endpoint (PRD §2.8)."""
import app as A
import errors
import middleware
import response
from app import app
from db import store


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    middleware.require_roles({A.R_ADMIN})
    body = A.get_body()
    value = A.require_field(body, "to_iso8601")
    dt = A.parse_iso(value)
    store.clock = dt
    current = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return response.object_response({"current_utc": current})
