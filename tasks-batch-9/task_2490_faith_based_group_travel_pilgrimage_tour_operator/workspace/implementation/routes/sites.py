"""Sacred sites and the service schedule (PRD section 3.2)."""

import re
from datetime import timedelta

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import (ROLE_LAND_CONTRACTOR, ROLE_PROGRAM_MANAGER, ROLE_RISK_OFFICER, authorize)
from validate import (apply_filters, body_of, opt_bool, opt_str, pagination, req_datetime,
                      req_enum, req_id, req_int, req_str)

bp = Blueprint("sites", __name__)

READ_ROLES = (ROLE_PROGRAM_MANAGER, ROLE_RISK_OFFICER, ROLE_LAND_CONTRACTOR)
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _load_site(site_id):
    row = db.sacred_sites.get(site_id)
    if row is None:
        err("ERR_SACRED_SITE_NOT_FOUND", "Sacred site %s does not exist." % site_id)
    return row


def _load_booking(booking_id):
    row = db.service_bookings.get(booking_id)
    if row is None:
        err("ERR_SERVICE_BOOKING_NOT_FOUND", "Service booking %s does not exist." % booking_id)
    return row


# ---------------------------------------------------------------------------
# Sacred sites
# ---------------------------------------------------------------------------


@bp.route("/sacred-sites", methods=["POST"])
def create_site():
    authorize((ROLE_PROGRAM_MANAGER,))
    body = body_of()
    with lock:
        name = req_str(body, "name", 1, 160)
        country = req_str(body, "country", 2, 2)
        if not COUNTRY_RE.match(country):
            err("ERR_INVALID_REQUEST", "country must be two uppercase letters.")
        access_regime = req_enum(body, "access_regime", core.ACCESS_REGIMES)
        daily_capacity_pax = req_int(body, "daily_capacity_pax", 1, 5000)
        turnaround_buffer_minutes = req_int(body, "turnaround_buffer_minutes", 0, 240)
        requires_local_clergy = opt_bool(body, "requires_local_clergy", False)

        row = core.base_row()
        row.update({
            "name": name,
            "country": country,
            "access_regime": access_regime,
            "daily_capacity_pax": daily_capacity_pax,
            "turnaround_buffer_minutes": turnaround_buffer_minutes,
            "requires_local_clergy": requires_local_clergy,
        })
        db.sacred_sites[row["id"]] = row
        return response.ok(core.serialize(row), 201)


@bp.route("/sacred-sites/<site_id>", methods=["GET"])
def get_site(site_id):
    authorize(READ_ROLES)
    with lock:
        return response.ok(core.serialize(_load_site(site_id)))


# ---------------------------------------------------------------------------
# Service bookings
# ---------------------------------------------------------------------------


@bp.route("/service-bookings", methods=["POST"])
def create_booking():
    authorize((ROLE_PROGRAM_MANAGER,))
    body = body_of()
    with lock:
        departure_id = req_id(body, "departure_id")
        sacred_site_id = req_id(body, "sacred_site_id")
        service_type = req_enum(body, "service_type", core.SERVICE_TYPES)
        scheduled_start_utc = req_datetime(body, "scheduled_start_utc")
        duration_minutes = req_int(body, "duration_minutes", 10, 480)
        pax_count = req_int(body, "pax_count", 1)
        permit_reference = opt_str(body, "permit_reference", 1, 120, None)

        departure = db.departures.get(departure_id)
        if departure is None:
            err("ERR_DEPARTURE_NOT_FOUND", "Departure %s does not exist." % departure_id)
        site = db.sacred_sites.get(sacred_site_id)
        if site is None:
            err("ERR_SACRED_SITE_NOT_FOUND", "Sacred site %s does not exist." % sacred_site_id)

        core.refresh_posture(departure)
        if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "A service can only be held on a PLANNING or OPEN_FOR_SALE departure.")
        program = core.program_of(departure)
        if site["country"] != program["destination_country"]:
            err("ERR_SERVICE_BOOKING_INVALID_STATE",
                "The site's country does not match the program's destination country.")

        buffered_end = scheduled_start_utc + timedelta(
            minutes=duration_minutes + site["turnaround_buffer_minutes"])

        # Band 12: the interval check, then the daily aggregate.
        for other in db.service_bookings.values():
            if other["sacred_site_id"] != sacred_site_id:
                continue
            if other["status"] not in core.OCCUPYING_SERVICE_STATUSES:
                continue
            other_start = core.as_dt(other["scheduled_start_utc"])
            other_end = core.as_dt(other["buffered_end_utc"])
            if scheduled_start_utc < other_end and other_start < buffered_end:
                err("ERR_SITE_SLOT_CONFLICT",
                    "The buffered interval overlaps an existing booking at this site.")

        day = scheduled_start_utc.date()
        occupied = core.site_occupied_pax(sacred_site_id, day)
        if occupied + pax_count > site["daily_capacity_pax"]:
            err("ERR_SITE_DAILY_CAPACITY_EXCEEDED",
                "The site admits only %d pax on %s." % (site["daily_capacity_pax"], day))

        if site["access_regime"] != "OPEN_ACCESS" and not permit_reference:
            err("ERR_PERMIT_REFERENCE_REQUIRED",
                "A %s site requires a permit_reference at hold time." % site["access_regime"])

        row = core.base_row()
        row.update({
            "departure_id": departure_id,
            "sacred_site_id": sacred_site_id,
            "service_type": service_type,
            "scheduled_start_utc": response.iso_ms(scheduled_start_utc),
            "duration_minutes": duration_minutes,
            "buffered_end_utc": response.iso_ms(buffered_end),
            "pax_count": pax_count,
            "permit_reference": permit_reference,
            "clergy_contact_name": None,
            "clergy_tradition": None,
            "status": "SITE_HELD",
            "cancelled_by_risk": False,
        })
        db.service_bookings[row["id"]] = row

        departure_before = core.snap(departure)
        departure["service_coverage_ok"] = False
        core.touch_if_changed(departure, departure_before)
        return response.ok(core.serialize(row), 201)


@bp.route("/service-bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    authorize(READ_ROLES)
    with lock:
        return response.ok(core.serialize(_load_booking(booking_id)))


@bp.route("/service-bookings", methods=["GET"])
def list_bookings():
    authorize(READ_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.service_bookings.values()))
        rows = apply_filters(rows, {
            "departure_id": "departure_id",
            "sacred_site_id": "sacred_site_id",
            "status": "status",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize(r) for r in page], limit, offset, total)


@bp.route("/service-bookings/<booking_id>/clergy-confirm", methods=["POST"])
def clergy_confirm(booking_id):
    authorize((ROLE_PROGRAM_MANAGER,))
    body = body_of()
    with lock:
        booking = _load_booking(booking_id)
        clergy_contact_name = req_str(body, "clergy_contact_name", 1, 120)
        clergy_tradition = req_enum(body, "clergy_tradition", core.FAITH_TRADITIONS)

        site = db.sacred_sites[booking["sacred_site_id"]]
        if booking["status"] != "SITE_HELD":
            err("ERR_SERVICE_BOOKING_INVALID_STATE",
                "Clergy can only be recorded against a SITE_HELD booking.")
        if not site["requires_local_clergy"]:
            err("ERR_SERVICE_BOOKING_INVALID_STATE",
                "This site does not require a local celebrant.")

        program = core.program_of(core.departure_of(booking))
        if program["faith_tradition"] != "INTERFAITH" and \
                clergy_tradition != program["faith_tradition"]:
            err("ERR_CLERGY_NOT_CONFIRMED",
                "The celebrant's tradition does not match the program's faith tradition.")

        booking["clergy_contact_name"] = clergy_contact_name
        booking["clergy_tradition"] = clergy_tradition
        booking["status"] = "CLERGY_CONFIRMED"
        core.touch(booking)
        return response.ok(core.serialize(booking))


@bp.route("/service-bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(booking_id):
    authorize((ROLE_PROGRAM_MANAGER,))
    with lock:
        booking = _load_booking(booking_id)
        site = db.sacred_sites[booking["sacred_site_id"]]
        departure = core.departure_of(booking)
        core.refresh_posture(departure)

        if booking["status"] in ("CONFIRMED", "CANCELLED"):
            err("ERR_SERVICE_BOOKING_INVALID_STATE",
                "A %s booking cannot be confirmed." % booking["status"])
        if not site["requires_local_clergy"] and booking["status"] != "SITE_HELD":
            err("ERR_SERVICE_BOOKING_INVALID_STATE",
                "This booking is not in SITE_HELD.")

        if departure["risk_posture"] not in ("OPEN", "WATCH"):
            err("ERR_DEPARTURE_POSTURE_BLOCKS_CONFIRM",
                "The departure's risk posture is %s." % departure["risk_posture"])

        if site["requires_local_clergy"] and booking["status"] != "CLERGY_CONFIRMED":
            err("ERR_CLERGY_NOT_CONFIRMED",
                "This site requires a named celebrant before confirmation.")
        if site["access_regime"] == "PERMIT_REQUIRED" and not booking["permit_reference"]:
            err("ERR_PERMIT_REFERENCE_REQUIRED",
                "A PERMIT_REQUIRED site needs a permit_reference before confirmation.")

        booking["status"] = "CONFIRMED"
        core.touch(booking)
        core.recompute_service_coverage(departure)
        return response.ok(core.serialize(booking))


@bp.route("/service-bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    authorize((ROLE_PROGRAM_MANAGER, ROLE_RISK_OFFICER))
    body = body_of()
    with lock:
        booking = _load_booking(booking_id)
        req_str(body, "cancellation_reason", 1, None)
        if booking["status"] == "CANCELLED":
            err("ERR_SERVICE_BOOKING_INVALID_STATE", "The booking is already cancelled.")

        booking["status"] = "CANCELLED"
        booking["cancelled_by_risk"] = False
        core.touch(booking)
        departure = core.departure_of(booking)
        core.refresh_posture(departure)
        core.recompute_service_coverage(departure)
        return response.ok(core.serialize(booking))
