"""Sterilizers."""
from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, auth, created, get_body, ok, ok_list, paginate, pagination,
    query_str, req_enum, req_int, req_string,
)

bp = Blueprint("sterilizers", __name__)


@bp.post("/spd/sterilizers")
def create_sterilizer():
    auth(("FacilityAdmin",))
    body = get_body()
    name = req_string(body, "name")
    method = req_enum(body, "method", domain.STERILIZER_METHODS)
    chamber_capacity = req_int(body, "chamber_capacity", minimum=1)
    cycle_minutes = req_int(body, "cycle_minutes", minimum=1)
    required_certification_level = req_int(
        body, "required_certification_level", minimum=1, maximum=3)

    record = store.new_record()
    record.update({
        "name": name,
        "method": method,
        "chamber_capacity": chamber_capacity,
        "cycle_minutes": cycle_minutes,
        "required_certification_level": required_certification_level,
        "status": "IDLE",
    })
    store.STERILIZERS[record["id"]] = record
    return created(views.sterilizer_view(record))


@bp.get("/spd/sterilizers")
def list_sterilizers():
    auth(ANY)
    limit, offset = pagination()
    status = query_str("status")
    method = query_str("method")
    rows = [r for r in store.STERILIZERS.values()
            if (status is None or r["status"] == status)
            and (method is None or r["method"] == method)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.sterilizer_view(r) for r in page], limit, offset, total)


@bp.get("/spd/sterilizers/<sterilizer_id>")
def get_sterilizer(sterilizer_id):
    auth(ANY)
    record = store.fetch(store.STERILIZERS, sterilizer_id)
    return ok(views.sterilizer_view(record))
