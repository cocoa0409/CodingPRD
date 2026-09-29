"""Land operator pools and their assignments (PRD section 3.3)."""

import re
from datetime import timedelta

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import (ROLE_FINANCE_CONTROLLER, ROLE_LAND_CONTRACTOR, ROLE_PROGRAM_MANAGER,
                        authorize)
from validate import (apply_filters, body_of, pagination, req_date, req_enum, req_id, req_int,
                      req_str)

bp = Blueprint("land", __name__)

READ_ROLES = (ROLE_LAND_CONTRACTOR, ROLE_PROGRAM_MANAGER, ROLE_FINANCE_CONTROLLER)
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _load_resource(resource_id):
    row = db.land_resources.get(resource_id)
    if row is None:
        err("ERR_LAND_RESOURCE_NOT_FOUND", "Land resource %s does not exist." % resource_id)
    return row


def _load_line(line_id):
    row = db.land_assignments.get(line_id)
    if row is None:
        err("ERR_LAND_ASSIGNMENT_NOT_FOUND", "Land assignment %s does not exist." % line_id)
    return row


def _dates(date_from, date_to):
    day = date_from
    while day <= date_to:
        yield day
        day = day + timedelta(days=1)


# ---------------------------------------------------------------------------
# Land resources
# ---------------------------------------------------------------------------


@bp.route("/land-resources", methods=["POST"])
def create_resource():
    authorize((ROLE_LAND_CONTRACTOR,))
    body = body_of()
    with lock:
        operator_name = req_str(body, "operator_name", 1, 120)
        country = req_str(body, "country", 2, 2)
        if not COUNTRY_RE.match(country):
            err("ERR_INVALID_REQUEST", "country must be two uppercase letters.")
        resource_type = req_enum(body, "resource_type", core.RESOURCE_TYPES)
        units_total = req_int(body, "units_total", 1, 500)
        unit_rate_local_cents = req_int(body, "unit_rate_local_cents", 1)
        fx_rate_bp = req_int(body, "fx_rate_bp", 1, 1000000)
        force_majeure_notice_days = req_int(body, "force_majeure_notice_days", 0, 180)

        row = core.base_row()
        row.update({
            "operator_name": operator_name,
            "country": country,
            "resource_type": resource_type,
            "units_total": units_total,
            "unit_rate_local_cents": unit_rate_local_cents,
            "fx_rate_bp": fx_rate_bp,
            "force_majeure_notice_days": force_majeure_notice_days,
        })
        db.land_resources[row["id"]] = row
        return response.ok(core.serialize(row), 201)


@bp.route("/land-resources/<resource_id>", methods=["GET"])
def get_resource(resource_id):
    authorize(READ_ROLES)
    with lock:
        return response.ok(core.serialize(_load_resource(resource_id)))


# ---------------------------------------------------------------------------
# Land assignments
# ---------------------------------------------------------------------------


@bp.route("/land-assignments", methods=["POST"])
def create_assignment():
    authorize((ROLE_LAND_CONTRACTOR,))
    body = body_of()
    with lock:
        land_resource_id = req_id(body, "land_resource_id")
        departure_id = req_id(body, "departure_id")
        date_from = req_date(body, "date_from")
        date_to = req_date(body, "date_to")
        units_requested = req_int(body, "units_requested", 1)
        if date_to < date_from:
            err("ERR_INVALID_REQUEST", "date_to must be on or after date_from.")

        resource = db.land_resources.get(land_resource_id)
        if resource is None:
            err("ERR_LAND_RESOURCE_NOT_FOUND",
                "Land resource %s does not exist." % land_resource_id)
        departure = db.departures.get(departure_id)
        if departure is None:
            err("ERR_DEPARTURE_NOT_FOUND", "Departure %s does not exist." % departure_id)

        core.refresh_posture(departure)
        # Drawing a land line is the one child-creating operation that also
        # tolerates SALES_CLOSED (PRD section 3.1).
        if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE", "SALES_CLOSED"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "A land line requires a PLANNING, OPEN_FOR_SALE or SALES_CLOSED departure.")
        program = core.program_of(departure)
        if resource["country"] != program["destination_country"]:
            err("ERR_LAND_ASSIGNMENT_INVALID_STATE",
                "The resource's country does not match the program's destination country.")

        existing = [la for la in db.land_assignments.values()
                    if la["land_resource_id"] == land_resource_id
                    and la["status"] in ("DRAFT", "COUNTERSIGNED")]
        for day in _dates(date_from, date_to):
            drawn = 0
            for line in existing:
                if core.as_date(line["date_from"]) <= day <= core.as_date(line["date_to"]):
                    drawn += line["units_requested"]
            if drawn + units_requested > resource["units_total"]:
                err("ERR_LAND_RESOURCE_OVERSUBSCRIBED",
                    "The pool holds only %d units on %s."
                    % (resource["units_total"], core.date_str(day)))

        days, line_local, line_usd = core.land_line_amounts(
            resource, date_from, date_to, units_requested)
        row = core.base_row()
        row.update({
            "land_resource_id": land_resource_id,
            "departure_id": departure_id,
            "date_from": core.date_str(date_from),
            "date_to": core.date_str(date_to),
            "units_requested": units_requested,
            "days_inclusive": days,
            "line_local_cents": line_local,
            "line_usd_cents": line_usd,
            "status": "DRAFT",
            "terminated_penalty_free": False,
        })
        db.land_assignments[row["id"]] = row
        return response.ok(core.serialize(row), 201)


@bp.route("/land-assignments/<line_id>", methods=["GET"])
def get_assignment(line_id):
    authorize(READ_ROLES)
    with lock:
        return response.ok(core.serialize(_load_line(line_id)))


@bp.route("/land-assignments", methods=["GET"])
def list_assignments():
    authorize(READ_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.land_assignments.values()))
        rows = apply_filters(rows, {
            "land_resource_id": "land_resource_id",
            "departure_id": "departure_id",
            "status": "status",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize(r) for r in page], limit, offset, total)


@bp.route("/land-assignments/<line_id>/countersign", methods=["POST"])
def countersign(line_id):
    authorize((ROLE_LAND_CONTRACTOR,))
    with lock:
        line = _load_line(line_id)
        departure = core.departure_of(line)
        core.refresh_posture(departure)
        if departure["status"] == "CANCELLED":
            err("ERR_DEPARTURE_INVALID_STATE",
                "A line on a cancelled departure cannot be countersigned.")
        if line["status"] != "DRAFT":
            err("ERR_LAND_ASSIGNMENT_INVALID_STATE", "Only a DRAFT line can be countersigned.")

        resource = db.land_resources[line["land_resource_id"]]
        days, line_local, line_usd = core.land_line_amounts(
            resource, core.as_date(line["date_from"]), core.as_date(line["date_to"]),
            line["units_requested"])
        line["days_inclusive"] = days
        line["line_local_cents"] = line_local
        line["line_usd_cents"] = line_usd
        line["status"] = "COUNTERSIGNED"
        core.touch(line)
        core.recompute_land_rollup(departure)
        return response.ok(core.serialize(line))


@bp.route("/land-assignments/<line_id>/terminate", methods=["POST"])
def terminate(line_id):
    authorize((ROLE_LAND_CONTRACTOR,))
    body = body_of()
    with lock:
        line = _load_line(line_id)
        req_str(body, "termination_reason", 1, None)
        if line["status"] == "TERMINATED":
            err("ERR_LAND_ASSIGNMENT_INVALID_STATE", "The line is already terminated.")

        resource = db.land_resources[line["land_resource_id"]]
        notice_days = core.whole_days(core.as_date(line["date_from"]), core.clock_date())
        line["status"] = "TERMINATED"
        line["terminated_penalty_free"] = notice_days >= resource["force_majeure_notice_days"]
        core.touch(line)
        departure = core.departure_of(line)
        core.refresh_posture(departure)
        core.recompute_land_rollup(departure)
        return response.ok(core.serialize(line))
