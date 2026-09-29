"""Test-driving logical clock (PRD 2.6)."""

from flask import Blueprint

import engine as E
import validate as V
from auth import principal
from db import db
from response import ok

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    principal("PlatformAdmin")
    b = V.body()
    moment = V.req_dt(b, "current_utc")
    db.current_utc = moment
    # Repositioning the clock immediately materialises every lapse that the new
    # instant implies (offers, mortgagee consent, refusal windows).
    E.sweep_expiries()
    return ok({"current_utc": E.iso(db.current_utc)})
