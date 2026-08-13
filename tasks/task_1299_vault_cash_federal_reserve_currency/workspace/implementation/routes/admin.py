"""Logical clock endpoint (test-driving capability, PRD 2.4)."""
from flask import Blueprint

from db import CLOCK, DB
from middleware import auth
from response import ok
from services import derive_site_posture, touch
from util import body, required, as_iso_dt, parse_dt

bp = Blueprint("admin", __name__)


@bp.post("/vault-cash/_clock/set_current_utc")
def set_clock():
    auth(["CashOperationsAdmin"])
    data = body()
    to_iso = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    # Normalize through the parser so the stored value is canonical.
    dt = parse_dt(to_iso)
    CLOCK["current_utc"] = (
        dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    )
    # Advancing the clock re-derives posture at sites holding SEIZED cases.
    for site in DB["vault_sites"].values():
        derive_site_posture(site)
        touch(site)
    return ok({"current_utc": CLOCK["current_utc"]})
