from flask import Blueprint, request

from db import new_common, pub, store, touch
from errors import invalid_request, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from util import as_int, as_str, body_json, paginate, req_field

bp = Blueprint("lowboys", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


def get_lowboy_or_404(lid):
    lb = store.lowboys.get(lid)
    if lb is None:
        raise not_found("Lowboy")
    return lb


@bp.post("/fleet/lowboys")
@require_roles("Dispatcher")
def create_lowboy():
    body = body_json()
    code = as_str(req_field(body, "lowboy_code"), "lowboy_code")
    capacity = as_int(req_field(body, "capacity_units"), "capacity_units")
    if capacity != 1:
        raise invalid_request("capacity_units must be 1 (single-unit trailers in v1)")
    if any(l["lowboy_code"] == code for l in store.lowboys.values()):
        raise invalid_request("lowboy_code must be unique")
    lb = new_common()
    lb.update({
        "lowboy_code": code,
        "status": "AVAILABLE",
        "capacity_units": capacity,
    })
    store.lowboys[lb["id"]] = lb
    return ok(pub(lb), "object", 201)


@bp.get("/fleet/lowboys/<lid>")
@require_roles(*READERS)
def get_lowboy(lid):
    return ok(pub(get_lowboy_or_404(lid)), "object", 200)


@bp.get("/fleet/lowboys")
@require_roles(*READERS)
def list_lowboys():
    rows = list(store.lowboys.values())
    st = request.args.get("status")
    if st is not None:
        rows = [l for l in rows if l["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(l) for l in items], meta)


@bp.post("/fleet/lowboys/<lid>/out-of-service")
@require_roles("Dispatcher")
def out_of_service(lid):
    lb = get_lowboy_or_404(lid)
    if lb["status"] != "AVAILABLE":
        raise invalid_state("Only an AVAILABLE lowboy can be taken out of service")
    lb["status"] = "OUT_OF_SERVICE"
    touch(lb)
    return ok(pub(lb), "object", 200)


@bp.post("/fleet/lowboys/<lid>/return-to-service")
@require_roles("Dispatcher")
def return_to_service(lid):
    lb = get_lowboy_or_404(lid)
    if lb["status"] != "OUT_OF_SERVICE":
        raise invalid_state("Only an OUT_OF_SERVICE lowboy can return to service")
    lb["status"] = "AVAILABLE"
    touch(lb)
    return ok(pub(lb), "object", 200)


@bp.get("/fleet/lowboys/<lid>/transport-jobs")
@require_roles(*READERS)
def lowboy_transport_jobs(lid):
    lb = get_lowboy_or_404(lid)
    rows = [t for t in store.transport_jobs.values() if t["lowboy_id"] == lb["id"]]
    st = request.args.get("status")
    if st is not None:
        rows = [t for t in rows if t["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(t) for t in items], meta)
