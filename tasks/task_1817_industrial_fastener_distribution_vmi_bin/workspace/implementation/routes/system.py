"""Clock-driving and cert-expiry sweep endpoints."""

from flask import Blueprint

import errors
from db import store, parse_iso
from middleware import authenticate, require_roles, json_body, need, as_dt
from response import success
from services import cert_expiry_cascade

bp = Blueprint("system", __name__)


@bp.post("/vmi/_clock/set_current_utc")
def set_clock():
    role = authenticate()
    body = json_body()
    to_iso8601 = as_dt(need(body, "to_iso8601"), "to_iso8601")
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        store.clock_dt = parse_iso(to_iso8601)
        store.clock_raw = to_iso8601
    return success({"current_utc": store.clock_raw}, 200)


@bp.post("/vmi/_sweep/cert-expiry")
def sweep_cert_expiry():
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    expired = []
    with store.lock:
        for cert in sorted(store.certs.values(), key=lambda c: c["_seq"]):
            if cert["status"] != "VALID":
                continue
            if parse_iso(cert["cert_expires_at"]) <= store.clock_dt:
                cert_expiry_cascade(cert)
                expired.append(cert["id"])
    return success({"expired_cert_ids": expired}, 200)
