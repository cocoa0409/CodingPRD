from decimal import Decimal
from flask import Blueprint

from core import (store, require, get_body, ok_empty, clock, parse_iso, touch,
                  req_str, ApiError, ERR_INVALID_REQUEST)
import services as svc

bp = Blueprint("ops", __name__)


@bp.post("/nursery/run-ops")
def run_ops():
    require(["GrowerManager"])
    now = clock.now()
    # Expire VALID certificates strictly past valid_until
    for cert in store.phyto_certs.values():
        if cert["status"] == "VALID" and now > parse_iso(cert["valid_until"]):
            cert["status"] = "EXPIRED"
            touch(cert)
    # Auto-cull batches whose cumulative shrink has reached/exceeded the threshold
    for batch in list(store.batches.values()):
        if batch["status"] in ("GROWING", "GRADING", "HELD") and batch["started_count"] > 0:
            cumulative = Decimal(batch["cull_count"]) / Decimal(batch["started_count"])
            if cumulative >= svc.AUTO_CULL_PCT:
                svc.do_full_cull(batch)
    return ok_empty()


@bp.post("/_clock/set_current_utc")
def set_clock():
    require(["GrowerManager"])
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso8601)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    clock.set(dt)
    return ok_empty()
