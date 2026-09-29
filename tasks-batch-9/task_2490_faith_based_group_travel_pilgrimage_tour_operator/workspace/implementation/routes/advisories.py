"""Destination risk advisories and the publication cascade (PRD section 3.9)."""

import re

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import (ROLE_FINANCE_CONTROLLER, ROLE_PROGRAM_MANAGER,
                        ROLE_PROTECTION_ADMINISTRATOR, ROLE_RISK_OFFICER, authorize)
from validate import body_of, req_datetime, req_enum, req_str

bp = Blueprint("advisories", __name__)

READ_ROLES = (ROLE_RISK_OFFICER, ROLE_PROGRAM_MANAGER, ROLE_PROTECTION_ADMINISTRATOR,
              ROLE_FINANCE_CONTROLLER)
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _load(advisory_id):
    row = db.advisories.get(advisory_id)
    if row is None:
        err("ERR_ADVISORY_NOT_FOUND", "Risk advisory %s does not exist." % advisory_id)
    return row


@bp.route("/risk-advisories", methods=["POST"])
def create_advisory():
    authorize((ROLE_RISK_OFFICER,))
    body = body_of()
    with lock:
        country = req_str(body, "country", 2, 2)
        if not COUNTRY_RE.match(country):
            err("ERR_INVALID_REQUEST", "country must be two uppercase letters.")
        level = req_enum(body, "level", core.ADVISORY_LEVELS)
        effective_from = req_datetime(body, "effective_from")
        source = req_str(body, "source", 1, 120)

        row = core.base_row()
        row.update({
            "country": country,
            "level": level,
            "effective_from": response.iso_ms(effective_from),
            "source": source,
            "status": "DRAFT",
            "affected_departure_count": 0,
        })
        db.advisories[row["id"]] = row
        return response.ok(core.serialize(row), 201)


@bp.route("/risk-advisories/<advisory_id>", methods=["GET"])
def get_advisory(advisory_id):
    authorize(READ_ROLES)
    with lock:
        return response.ok(core.serialize(_load(advisory_id)))


@bp.route("/risk-advisories/<advisory_id>/publish", methods=["POST"])
def publish(advisory_id):
    caller = authorize((ROLE_RISK_OFFICER,))
    with lock:
        advisory = _load(advisory_id)
        if advisory["status"] != "DRAFT":
            err("ERR_ADVISORY_INVALID_STATE",
                "A %s advisory cannot be published." % advisory["status"])
        if core.as_dt(advisory["effective_from"]) > core.clock_now():
            err("ERR_ADVISORY_EFFECTIVE_IN_FUTURE",
                "An advisory may not be published before it takes effect.")

        # At most one advisory per country governs at a time.
        for other in core.order_rows(list(db.advisories.values())):
            if other["id"] == advisory["id"]:
                continue
            if other["country"] != advisory["country"] or other["status"] != "PUBLISHED":
                continue
            other["status"] = "SUPERSEDED"
            core.touch(other)

        advisory["status"] = "PUBLISHED"

        # Hop one: re-derive the posture of every live departure to this country.
        visited = []
        for departure in core.order_rows(list(db.departures.values())):
            program = core.program_of(departure)
            if program["destination_country"] != advisory["country"]:
                continue
            if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE", "SALES_CLOSED"):
                continue
            previous_posture = departure["risk_posture"]
            core.refresh_posture(departure)
            visited.append(departure)
            newly_suspended = (departure["risk_posture"] == "SUSPENDED"
                               and previous_posture != "SUSPENDED")
            if departure["risk_posture"] == "SUSPENDED" and \
                    departure["status"] == "OPEN_FOR_SALE":
                departure["status"] = "SALES_CLOSED"
            if not newly_suspended:
                continue

            # Hop two: risk-cancel every live service booking.
            for booking in core.service_bookings_of_departure(departure["id"]):
                if booking["status"] == "CANCELLED":
                    continue
                booking["status"] = "CANCELLED"
                booking["cancelled_by_risk"] = True
                core.touch(booking)

            # Hop three: the departure needs a rebuilt itinerary, ratified by a
            # second officer who is not the publishing officer.
            departure["service_coverage_ok"] = False
            departure["pending_modification_required"] = True
            departure["pending_modification_reason"] = "RISK_SUSPENSION"
            departure["pending_modification_cost_delta_cents"] = 0
            departure["pending_modification_proposed_by_user_id"] = caller.user_id

            # Hop four: the seat blocks follow the suspension.
            for block in core.air_blocks_of_departure(departure["id"]):
                if block["status"] in ("DRAFT", "OFFERED", "COUNTERED"):
                    block["status"] = "EXPIRED"
                    core.touch(block)
                elif block["status"] == "CONFIRMED":
                    block["status"] = "RELEASED"
                    core.touch(block)
                    for pilgrim in core.pilgrims_of_departure(departure["id"]):
                        if pilgrim["ticketed_name"] is None:
                            continue
                        pilgrim_before = core.snap(pilgrim)
                        pilgrim["ticketed_name"] = None
                        core.touch_if_changed(pilgrim, pilgrim_before)

        advisory["affected_departure_count"] = len(visited)
        core.touch(advisory)
        for departure in visited:
            core.touch(departure)
        return response.ok(core.serialize(advisory))
