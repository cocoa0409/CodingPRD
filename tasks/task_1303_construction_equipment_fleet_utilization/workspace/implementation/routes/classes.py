from flask import Blueprint

from db import new_common, pub, store
from errors import invalid_request, not_found
from middleware import require_roles
from response import ok, ok_list
from util import as_int, as_str, body_json, paginate, req_field

bp = Blueprint("classes", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


@bp.post("/fleet/equipment-classes")
@require_roles("FleetAdmin")
def create_class():
    body = body_json()
    class_code = as_str(req_field(body, "class_code"), "class_code")
    daily = as_int(req_field(body, "daily_rate_cents"), "daily_rate_cents", minimum=0)
    ext = as_int(req_field(body, "external_daily_rate_cents"), "external_daily_rate_cents", minimum=0)
    wknd = as_int(req_field(body, "weekend_multiplier_bp"), "weekend_multiplier_bp", minimum=0)
    idle = as_int(req_field(body, "idle_day_multiplier_bp"), "idle_day_multiplier_bp", minimum=0)
    interval = as_int(req_field(body, "service_interval_hours"), "service_interval_hours", minimum=1)
    alert = as_int(req_field(body, "idle_alert_utilization_bp"), "idle_alert_utilization_bp",
                   minimum=0, maximum=10000)
    life = as_int(req_field(body, "expected_life_hours"), "expected_life_hours", minimum=1)
    salvage = as_int(req_field(body, "salvage_value_cents"), "salvage_value_cents", minimum=0)
    if any(c["class_code"] == class_code for c in store.classes.values()):
        raise invalid_request("class_code must be unique")
    c = new_common()
    c.update({
        "class_code": class_code,
        "daily_rate_cents": daily,
        "external_daily_rate_cents": ext,
        "weekend_multiplier_bp": wknd,
        "idle_day_multiplier_bp": idle,
        "service_interval_hours": interval,
        "idle_alert_utilization_bp": alert,
        "expected_life_hours": life,
        "salvage_value_cents": salvage,
    })
    store.classes[c["id"]] = c
    return ok(pub(c), "object", 201)


@bp.get("/fleet/equipment-classes/<cid>")
@require_roles(*READERS)
def get_class(cid):
    c = store.classes.get(cid)
    if c is None:
        raise not_found("EquipmentClass")
    return ok(pub(c), "object", 200)


@bp.get("/fleet/equipment-classes")
@require_roles(*READERS)
def list_classes():
    items, meta = paginate(list(store.classes.values()))
    return ok_list([pub(c) for c in items], meta)
