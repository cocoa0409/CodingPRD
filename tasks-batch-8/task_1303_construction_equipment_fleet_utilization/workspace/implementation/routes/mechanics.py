from flask import Blueprint, request

from db import new_common, pub, store, touch
from errors import invalid_request, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from util import as_str, body_json, check_body_fks, paginate, req_field

bp = Blueprint("mechanics", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


def get_mechanic_or_404(mid):
    m = store.mechanics.get(mid)
    if m is None:
        raise not_found("Mechanic")
    return m


@bp.post("/fleet/mechanics")
@require_roles("FleetAdmin")
def create_mechanic():
    body = body_json()
    check_body_fks([(store.projects, body, "home_project_id")])
    code = as_str(req_field(body, "mechanic_code"), "mechanic_code")
    name = as_str(req_field(body, "name"), "name", allow_empty=True)
    home = as_str(req_field(body, "home_project_id"), "home_project_id")
    if any(m["mechanic_code"] == code for m in store.mechanics.values()):
        raise invalid_request("mechanic_code must be unique")
    m = new_common()
    m.update({
        "mechanic_code": code,
        "name": name,
        "status": "AVAILABLE",
        "home_project_id": home,
        "active_work_order_count": 0,
    })
    store.mechanics[m["id"]] = m
    return ok(pub(m), "object", 201)


@bp.get("/fleet/mechanics/<mid>")
@require_roles(*READERS)
def get_mechanic(mid):
    return ok(pub(get_mechanic_or_404(mid)), "object", 200)


@bp.get("/fleet/mechanics")
@require_roles(*READERS)
def list_mechanics():
    rows = list(store.mechanics.values())
    for f in ("home_project_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [m for m in rows if m.get(f) == v]
    items, meta = paginate(rows)
    return ok_list([pub(m) for m in items], meta)


@bp.post("/fleet/mechanics/<mid>/off-duty")
@require_roles("FleetAdmin")
def off_duty(mid):
    m = get_mechanic_or_404(mid)
    if m["status"] != "AVAILABLE" or m["active_work_order_count"] != 0:
        raise invalid_state("OFF_DUTY requires status AVAILABLE with zero active work orders")
    m["status"] = "OFF_DUTY"
    touch(m)
    return ok(pub(m), "object", 200)


@bp.post("/fleet/mechanics/<mid>/on-duty")
@require_roles("FleetAdmin")
def on_duty(mid):
    m = get_mechanic_or_404(mid)
    if m["status"] != "OFF_DUTY":
        raise invalid_state("Only an OFF_DUTY mechanic can return to AVAILABLE")
    m["status"] = "AVAILABLE"
    touch(m)
    return ok(pub(m), "object", 200)
