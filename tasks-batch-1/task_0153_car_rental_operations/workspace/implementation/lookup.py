"""Existence resolution (PRD §2.6). Raises ERR_NOT_FOUND (404) when missing."""
import db
from errors import err


def get_location(loc_id):
    rec = db.locations.get(loc_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Location not found: %s" % loc_id)
    return rec


def get_vehicle_class(class_id):
    rec = db.vehicle_classes.get(class_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "VehicleClass not found: %s" % class_id)
    return rec


def get_vehicle(vehicle_id):
    rec = db.vehicles.get(vehicle_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Vehicle not found: %s" % vehicle_id)
    return rec


def get_member(member_id):
    rec = db.members.get(member_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "LoyaltyMember not found: %s" % member_id)
    return rec


def get_reservation(reservation_id):
    rec = db.reservations.get(reservation_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Reservation not found: %s" % reservation_id)
    return rec


def get_agreement(agreement_id):
    rec = db.agreements.get(agreement_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "RentalAgreement not found: %s" % agreement_id)
    return rec


def get_rate_plan(plan_id):
    rec = db.rate_plans.get(plan_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "RatePlan not found: %s" % plan_id)
    return rec


def get_incident(incident_id):
    rec = db.incidents.get(incident_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "IncidentReport not found: %s" % incident_id)
    return rec
