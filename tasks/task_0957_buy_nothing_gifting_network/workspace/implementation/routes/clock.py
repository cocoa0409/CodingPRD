from flask import Blueprint

import db
from middleware import get_auth, require_role, validate, v_datetime
from response import ok, get_body
from services import epoch_sweep

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_current_utc():
    role, _uid = get_auth()
    require_role(role, ("PlatformAdmin",))
    body = get_body()
    fields = validate(body, {"to_iso8601": (True, v_datetime)})
    db.store.clock = fields["to_iso8601"]
    epoch_sweep()
    return ok({}, status=200)
