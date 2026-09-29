"""The compliance sweep and the deterministic logical clock."""
from flask import Blueprint

import domain as D
import validators as V
from common import iso, parse_iso, set_clock
from response import ok

bp = Blueprint("system", __name__)


@bp.post("/compliance-sweeps")
def run_sweep():
    from auth import authorize
    authorize("CertificationOfficer")
    V.body()
    return ok(D.run_compliance_sweep())


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    from auth import authorize, raw_identity
    user_id, role = raw_identity()
    # PRD 2.4: the one endpoint exempt from the missing-header-pair check; when
    # headers are supplied the role restriction still applies.
    if user_id is not None or role is not None:
        authorize("CertificationOfficer")
    data = V.body()
    moment = V.req_instant(data, "to_iso8601")
    set_clock(moment)
    return ok({"current_utc": iso(moment)})
