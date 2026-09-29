"""Producer registration and read."""

from flask import Blueprint

import domain
import guards
from envelope import created, ok
from errors import fail
from store import db, new_row

bp = Blueprint("producers", __name__)


@bp.post("/plan/producers")
def create_producer():
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    name = guards.req_str(data, "name", min_len=1, max_len=200)
    license_number = guards.req_str(data, "license_number", min_len=1, max_len=100)
    territories = guards.req_territories(data, "appointed_territories")
    status = guards.opt_enum(data, "status", ("ACTIVE", "SUSPENDED"), "ACTIVE")

    for existing in db.producers.values():
        if existing["license_number"] == license_number:
            fail("ERR_DUPLICATE_IDENTIFIER", "license_number is already registered.")

    row = new_row()
    row.update(
        {
            "name": name,
            "license_number": license_number,
            "appointed_territories": territories,
            "status": status,
        }
    )
    db.producers[row["id"]] = row
    return created(domain.producer_out(row))


@bp.get("/plan/producers/<producer_id>")
def read_producer(producer_id):
    guards.authenticate(("PlanAdministrator", "ComplianceExaminer", "ProducerAgent"))
    producer = guards.need_producer(producer_id)
    return ok(domain.producer_out(producer))
