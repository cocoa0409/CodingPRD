"""DamageClaim endpoints (PRD §3.7)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain, calculations as calc
from util import (new_resource, touch, pagination_params, paginate, sort_by_created)

bp = Blueprint("damage_claims", __name__)

READ_ROLES = {"OpsManager", "TourManager", "WarehouseTech"}


@bp.route("/backline/damage-claims/<claim_id>", methods=["GET"])
def fetch_claim(claim_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    claim = domain.get_claim(claim_id)
    return success_object(domain.serialize(claim), status=200)


@bp.route("/backline/damage-claims", methods=["GET"])
def list_claims():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    reservation_line_id = request.args.get("reservation_line_id")
    gear_unit_id = request.args.get("gear_unit_id")
    status = request.args.get("status")
    items = list(store.damage_claims.values())
    if reservation_line_id is not None:
        items = [c for c in items if c.get("reservation_line_id") == reservation_line_id]
    if gear_unit_id is not None:
        items = [c for c in items if c.get("gear_unit_id") == gear_unit_id]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(c) for c in page], meta, status=200)


@bp.route("/backline/damage-claims/<claim_id>/assess", methods=["POST"])
def assess_claim(claim_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    claim = domain.get_claim(claim_id)
    if claim["status"] != "FILED":
        raise errors.invalid_state("Claim must be FILED to assess")
    # Gate 6: segregation of duties — the filer may not assess their own claim
    if auth["user_id"] == claim.get("filed_by_user_id"):
        raise errors.segregation_of_duties("Claim filer may not assess their own claim")
    claim["status"] = "ASSESSED"
    claim["assessed_at_dt"] = store.current_utc
    # Condition-score decrement per severity, floored at 0
    unit = store.gear_units.get(claim.get("gear_unit_id")) if claim.get("gear_unit_id") else None
    if unit is not None:
        impact = calc.CONDITION_IMPACT.get(claim.get("assessed_severity"), 0)
        unit["condition_score"] = max(0, unit.get("condition_score", 100) - impact)
        # MAJOR/TOTAL_LOSS: quarantined unit moves on to MAINTENANCE with a
        # DAMAGE_REPAIR ticket opened against it
        if claim.get("assessed_severity") in {"MAJOR", "TOTAL_LOSS"} and \
                unit.get("status") == "QUARANTINED":
            unit["status"] = "MAINTENANCE"
            touch(unit)
            domain.open_maintenance_ticket(unit, "DAMAGE_REPAIR")
        else:
            touch(unit)
    # Artist risk score recomputed from scratch on each triggering event
    reservation = store.reservation_lines.get(claim.get("reservation_line_id"))
    if reservation is not None:
        tour = store.tours.get(reservation.get("tour_id"))
        if tour is not None:
            artist = store.artists.get(tour.get("artist_id"))
            if artist is not None:
                artist["risk_score"] = calc.artist_risk_score(artist["id"])
                touch(artist)
    touch(claim)
    return success_object(domain.serialize(claim), status=200)


@bp.route("/backline/damage-claims/<claim_id>/charge", methods=["POST"])
def charge_claim(claim_id):
    auth = get_auth()
    require_roles(auth, {"TourManager", "OpsManager"})
    claim = domain.get_claim(claim_id)
    # From ASSESSED a TourManager charges; from DISPUTED only an OpsManager (§3.7)
    if claim["status"] == "ASSESSED":
        if auth["role"] != "TourManager":
            raise errors.unauthorized("Only TourManager may charge an ASSESSED claim")
    elif claim["status"] == "DISPUTED":
        if auth["role"] != "OpsManager":
            raise errors.unauthorized("Only OpsManager may charge a DISPUTED claim")
    else:
        raise errors.invalid_state("Claim must be ASSESSED or DISPUTED to charge")
    reservation = store.reservation_lines.get(claim.get("reservation_line_id"))
    rider_line = store.rider_lines.get(reservation.get("rider_line_id")) if reservation else None
    model = store.gear_models.get(rider_line.get("gear_model_id")) if rider_line else None
    replacement_value = model.get("replacement_value_cents", 0) if model else 0
    held = reservation.get("deposit_held_cents", 0) if reservation else 0
    charge, overage = calc.damage_charge_rule(
        claim.get("assessed_severity"), claim.get("repair_estimate_cents", 0),
        replacement_value, held)
    claim["charge_cents"] = charge
    claim["status"] = "CHARGED"
    touch(claim)
    return success_object(domain.serialize(claim), status=200)


@bp.route("/backline/damage-claims/<claim_id>/dispute", methods=["POST"])
def dispute_claim(claim_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    claim = domain.get_claim(claim_id)
    if claim["status"] != "ASSESSED":
        raise errors.invalid_state("Claim must be ASSESSED to dispute")
    claim["status"] = "DISPUTED"
    touch(claim)
    return success_object(domain.serialize(claim), status=200)


@bp.route("/backline/damage-claims/<claim_id>/waive", methods=["POST"])
def waive_claim(claim_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    claim = domain.get_claim(claim_id)
    if claim["status"] not in {"ASSESSED", "DISPUTED"}:
        raise errors.invalid_state("Only ASSESSED or DISPUTED claims may be waived")
    claim["status"] = "WAIVED"
    touch(claim)
    return success_object(domain.serialize(claim), status=200)


@bp.route("/backline/damage-claims/<claim_id>/mark-paid", methods=["POST"])
def mark_paid(claim_id):
    auth = get_auth()
    require_roles(auth, {"TourManager"})
    claim = domain.get_claim(claim_id)
    if claim["status"] != "CHARGED":
        raise errors.invalid_state("Claim must be CHARGED to mark paid")
    claim["status"] = "PAID"
    touch(claim)
    # Risk score recomputation also triggers on PAID settlement (§3.1)
    reservation = store.reservation_lines.get(claim.get("reservation_line_id"))
    if reservation is not None:
        tour = store.tours.get(reservation.get("tour_id"))
        if tour is not None:
            artist = store.artists.get(tour.get("artist_id"))
            if artist is not None:
                artist["risk_score"] = calc.artist_risk_score(artist["id"])
                touch(artist)
    return success_object(domain.serialize(claim), status=200)
