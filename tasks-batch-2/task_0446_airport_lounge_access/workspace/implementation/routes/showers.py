"""ShowerSuite + ShowerReservation endpoints (PRD §3.7)."""
from flask import Blueprint

import errors
import clock
import domain
from db import db, new_id, make_common_fields, touch
from middleware import get_principal, require_role
from validation import get_json_body, require_str, require_int
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("showers", __name__)


# =============================================================================
# ShowerSuite
# =============================================================================
@bp.route("/shower-suites", methods=["POST"])
def create_suite():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()

    lounge_id = require_str(body, "lounge_id")
    label = require_str(body, "label")
    turnover = require_int(body, "turnover_minutes", required=False, minimum=0,
                           default=0)
    if not domain.get_lounge(lounge_id):
        raise errors.not_found("Lounge not found")

    suite = {
        "id": new_id(),
        "lounge_id": lounge_id,
        "label": label,
        "turnover_minutes": turnover,
        "out_of_service": False,
    }
    suite.update(make_common_fields())
    suite["_seq"] = db.shower_suites.next_seq()
    db.shower_suites.items[suite["id"]] = suite
    return success(serialize(suite), status=201)


@bp.route("/shower-suites", methods=["GET"])
def list_suites():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    return list_filtered(db.shower_suites, [("lounge_id", "lounge_id", "str")])


@bp.route("/shower-suites/<suite_id>", methods=["GET"])
def get_suite(suite_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    suite = db.shower_suites.items.get(suite_id)
    if not suite:
        raise errors.not_found("Shower suite not found")
    return success(serialize(suite))


# =============================================================================
# ShowerReservation
# =============================================================================
@bp.route("/shower-reservations", methods=["POST"])
def create_reservation():
    user_id, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    body = get_json_body()

    suite_id = require_str(body, "shower_suite_id")
    visit_id = require_str(body, "visit_id")
    suite = db.shower_suites.items.get(suite_id)
    if not suite:
        raise errors.not_found("Shower suite not found")
    visit = domain.get_visit(visit_id)
    if not visit:
        raise errors.not_found("Visit not found")

    start_raw = require_str(body, "start_at")
    end_raw = require_str(body, "end_at")
    try:
        start_at = clock.parse_iso(start_raw)
        end_at = clock.parse_iso(end_raw)
    except (ValueError, TypeError):
        raise errors.invalid_request("start_at/end_at must be ISO 8601")
    if not (start_at < end_at):
        raise errors.invalid_request("start_at must be before end_at")

    # ownership: a Member booking must own the referenced visit.
    if role == "Member" and user_id != visit.get("member_id"):
        raise errors.not_owner("Member may only book for their own visit")

    # state: visit must be CHECKED_IN and suite not out of service.
    if visit["status"] != "CHECKED_IN" or suite["out_of_service"]:
        raise errors.err("ERR_SHOWER_UNAVAILABLE",
                         "Visit not checked in or suite unavailable")

    # overlap check under buffered turnover geometry (calc 7).
    if _has_conflict(suite, start_at, end_at):
        raise errors.err("ERR_SHOWER_CONFLICT", "Booking interval conflicts")

    res = {
        "id": new_id(),
        "shower_suite_id": suite_id,
        "visit_id": visit_id,
        "start_at": clock.to_iso_millis(start_at),
        "end_at": clock.to_iso_millis(end_at),
        "status": "BOOKED",
    }
    res.update(make_common_fields())
    res["_seq"] = db.shower_reservations.next_seq()
    db.shower_reservations.items[res["id"]] = res
    return success(serialize(res), status=201)


def _has_conflict(suite, new_start, new_end):
    from datetime import timedelta
    buffer = timedelta(minutes=suite["turnover_minutes"])
    for r in db.shower_reservations.items.values():
        if r["shower_suite_id"] != suite["id"]:
            continue
        if r["status"] != "BOOKED":
            continue
        ex_start = clock.parse_iso(r["start_at"])
        ex_end = clock.parse_iso(r["end_at"])
        buffered_end = ex_end + buffer
        if new_start < buffered_end and ex_start < new_end:
            return True
    return False


@bp.route("/shower-reservations", methods=["GET"])
def list_reservations():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    return list_filtered(
        db.shower_reservations,
        [
            ("shower_suite_id", "shower_suite_id", "str"),
            ("visit_id", "visit_id", "str"),
            ("status", "status", "str"),
        ],
    )


@bp.route("/shower-reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    r = db.shower_reservations.items.get(reservation_id)
    if not r:
        raise errors.not_found("Shower reservation not found")
    return success(serialize(r))


@bp.route("/shower-reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    user_id, role = get_principal()
    require_role(role, {"Member", "NetworkAdmin"})
    r = db.shower_reservations.items.get(reservation_id)
    if not r:
        raise errors.not_found("Shower reservation not found")
    visit = domain.get_visit(r["visit_id"])
    if role == "Member":
        if not visit or user_id != visit.get("member_id"):
            raise errors.not_owner("Member may only cancel their own reservation")
    if r["status"] != "BOOKED":
        raise errors.invalid_state("Reservation is not BOOKED")
    r["status"] = "CANCELLED"
    touch(r)
    return success(serialize(r))


@bp.route("/shower-reservations/<reservation_id>/complete", methods=["POST"])
def complete_reservation(reservation_id):
    user_id, role = get_principal()
    require_role(role, {"LoungeAgent"})
    r = db.shower_reservations.items.get(reservation_id)
    if not r:
        raise errors.not_found("Shower reservation not found")
    visit = domain.get_visit(r["visit_id"])
    # ownership: agent must staff the reservation's visit's lounge.
    if not visit or user_id != visit.get("lounge_id"):
        raise errors.not_owner("Agent does not staff this lounge")
    if r["status"] != "BOOKED":
        raise errors.invalid_state("Reservation is not BOOKED")
    r["status"] = "COMPLETED"
    touch(r)
    return success(serialize(r))
