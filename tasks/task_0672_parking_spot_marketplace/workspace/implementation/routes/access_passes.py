"""Gate redemption via QR token."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_GATE_PASS_INVALID
from middleware import require_auth, require_role
from response import success
from serialize import access_pass_view
from util import require_body, require_str

bp = Blueprint("access_passes", __name__)


@bp.post("/access-passes/redeem")
def redeem():
    caller = require_auth()
    require_role(caller, "Driver")
    data = require_body(request.get_json(silent=True))
    qr_token = require_str(data, "qr_token")

    pass_rec = None
    for p in db.access_passes.values():
        if p["qr_token"] == qr_token:
            pass_rec = p
            break
    # Requires a valid pass with gate_opens_remaining > 0 matching a booking.
    if pass_rec is None or pass_rec["gate_opens_remaining"] <= 0:
        raise err(ERR_GATE_PASS_INVALID, "No valid access pass for this token.")
    if pass_rec["booking_id"] not in db.bookings:
        raise err(ERR_GATE_PASS_INVALID, "Access pass has no matching booking.")

    pass_rec["gate_opens_remaining"] -= 1
    return success(access_pass_view(pass_rec))
