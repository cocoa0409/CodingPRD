"""Applicants and their vehicles."""

from flask import Blueprint

import domain
import guards
from envelope import created, ok, ok_list
from errors import fail
from store import db, new_row

bp = Blueprint("applicants", __name__)

READ_ROLES = (
    "PlanAdministrator",
    "ComplianceExaminer",
    "ProducerAgent",
    "ServicingCarrier",
)
WRITE_ROLES = ("PlanAdministrator", "ProducerAgent")


@bp.post("/plan/applicants")
def create_applicant():
    guards.authenticate(WRITE_ROLES)
    data = guards.body()
    full_name = guards.req_str(data, "full_name", min_len=1, max_len=200)
    dln = guards.req_str(data, "driver_license_number", min_len=1, max_len=64)
    territory_code = guards.req_enum(data, "territory_code", guards.TERRITORIES)
    driver_class = guards.req_enum(data, "driver_class", guards.DRIVER_CLASSES)
    first_licensed_date = guards.req_dt(data, "first_licensed_date")

    for existing in db.applicants.values():
        if existing["driver_license_number"] == dln:
            fail("ERR_DUPLICATE_IDENTIFIER", "driver_license_number already exists.")

    row = new_row()
    row.update(
        {
            "full_name": full_name,
            "driver_license_number": dln,
            "territory_code": territory_code,
            "driver_class": driver_class,
            "first_licensed_date": first_licensed_date,
            "voluntary_market_eligible": False,
        }
    )
    db.applicants[row["id"]] = row
    return created(domain.applicant_out(row))


@bp.get("/plan/applicants/<applicant_id>")
def read_applicant(applicant_id):
    guards.authenticate(READ_ROLES)
    applicant = guards.need_applicant(applicant_id)
    return ok(domain.applicant_out(applicant))


@bp.post("/plan/applicants/<applicant_id>/vehicles")
def create_vehicle(applicant_id):
    guards.authenticate(WRITE_ROLES)
    data = guards.body()
    vin = guards.req_str(data, "vin", exact_len=17)
    vehicle_class_code = guards.req_enum(data, "vehicle_class_code", guards.VEHICLE_CLASSES)
    garaging_territory_code = guards.req_enum(
        data, "garaging_territory_code", guards.TERRITORIES
    )
    model_year = guards.req_int(data, "model_year", minimum=1980, maximum=2027)
    applicant = guards.need_applicant(applicant_id)

    for existing in db.vehicles.values():
        if existing["vin"] == vin:
            fail("ERR_DUPLICATE_IDENTIFIER", "vin already exists.")

    row = new_row()
    row.update(
        {
            # The owner comes from the addressed applicant, never from the body.
            "applicant_id": applicant["id"],
            "vin": vin,
            "vehicle_class_code": vehicle_class_code,
            "garaging_territory_code": garaging_territory_code,
            "model_year": model_year,
        }
    )
    db.vehicles[row["id"]] = row
    return created(domain.vehicle_out(row))


@bp.get("/plan/applicants/<applicant_id>/vehicles")
def list_vehicles(applicant_id):
    guards.authenticate(READ_ROLES)
    limit, offset = guards.pagination()
    applicant = guards.need_applicant(applicant_id)

    rows = [v for v in db.vehicles.values() if v["applicant_id"] == applicant["id"]]
    rows = domain.sort_default(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.vehicle_out(r) for r in page], limit, offset, total)
