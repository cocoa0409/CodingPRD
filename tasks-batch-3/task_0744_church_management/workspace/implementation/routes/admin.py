"""Admin/test-driving endpoints: logical clock + payment simulator."""

from flask import Blueprint

import db
from common import (
    require_role, get_json_body, success, must_exist, parse_iso8601,
    format_iso8601, bump,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)
from services.donation import apply_post, apply_fail

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # PlatformAdmin only.
    require_role({"PlatformAdmin"})
    body = get_json_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        dt = parse_iso8601(body["to_iso8601"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO8601")
    # Normalize to canonical iso format with ms precision (Z suffix).
    formatted = format_iso8601(dt)
    db.set_clock_iso(formatted)
    return success({"current_utc": db.get_clock_iso()}, 200)


@bp.route("/_payments/simulate", methods=["POST"])
def simulate_payment():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    for k in ("donation_id", "outcome"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if body["outcome"] not in ("SUCCEEDED", "FAILED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be SUCCEEDED or FAILED")
    donation = must_exist(db.donations, body["donation_id"], "Donation")
    if donation["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "donation must be PENDING to simulate payment")

    if body["outcome"] == "SUCCEEDED":
        apply_post(donation)
        bump(donation)
    else:
        apply_fail(donation)
        bump(donation)
    return success(donation, 200)
