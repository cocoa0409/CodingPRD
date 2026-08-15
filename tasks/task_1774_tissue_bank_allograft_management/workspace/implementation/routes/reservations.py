"""Reservations: retrieval and manual release (PRD §3.5)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_RESERVATION_NOT_FOUND, ERR_RESERVATION_NOT_ACTIVE
from middleware import require_roles, ALL_ROLES
from response import success_object
from services import domain

bp = Blueprint("reservations", __name__)

ANY = ALL_ROLES


def get_reservation_or_404(reservation_id: str) -> dict:
    reservation = db["reservations"].get(reservation_id)
    if reservation is None:
        raise_error(ERR_RESERVATION_NOT_FOUND, f"reservation {reservation_id} does not exist")
    return reservation


@bp.route("/tissue-bank/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    require_roles(ANY)
    return success_object(domain.reservation_json(get_reservation_or_404(reservation_id)))


@bp.route("/tissue-bank/reservations/<reservation_id>/release", methods=["POST"])
def release_reservation(reservation_id):
    require_roles({"TissueBankCoordinator"})
    reservation = get_reservation_or_404(reservation_id)
    if reservation["status"] != "ACTIVE":
        raise_error(ERR_RESERVATION_NOT_ACTIVE, f"reservation status is {reservation['status']}, not ACTIVE")
    reservation["status"] = "RELEASED"
    reservation["release_reason"] = "MANUAL"
    domain.touch(reservation)
    unit = db["units"].get(reservation["tissue_unit_id"])
    if unit is not None and unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        domain.touch(unit)
    return success_object(domain.reservation_json(reservation))
