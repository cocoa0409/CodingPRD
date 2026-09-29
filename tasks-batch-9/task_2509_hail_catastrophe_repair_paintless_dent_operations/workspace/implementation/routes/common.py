"""Shared lookup helpers. Identifiers report the type-specific 404 (PRD §2.10)."""

from db import db
from errors import api_error

API_PREFIX = "/hail-ops"


def _resolve(collection, identifier, error_id, label):
    if not isinstance(identifier, str) or identifier == "":
        raise api_error(error_id, "%s not found." % label)
    row = collection.get(identifier)
    if row is None:
        raise api_error(error_id, "%s not found." % label)
    return row


def get_storm_event(identifier):
    return _resolve(db.storm_events, identifier, "ERR_STORM_EVENT_NOT_FOUND", "Storm event")


def get_facility(identifier):
    return _resolve(db.facilities, identifier, "ERR_FACILITY_NOT_FOUND", "Facility")


def get_vehicle(identifier):
    return _resolve(db.vehicles, identifier, "ERR_VEHICLE_NOT_FOUND", "Vehicle")


def get_technician(identifier):
    return _resolve(db.technicians, identifier, "ERR_TECHNICIAN_NOT_FOUND", "Technician")


def get_insurer(identifier):
    return _resolve(db.insurers, identifier, "ERR_INSURER_NOT_FOUND", "Insurer")


def get_rate_agreement(identifier):
    return _resolve(
        db.rate_agreements, identifier, "ERR_RATE_AGREEMENT_NOT_FOUND", "Rate agreement"
    )


def get_permit(identifier):
    return _resolve(db.permits, identifier, "ERR_RESOURCE_NOT_FOUND", "Permit")


def get_housing_unit(identifier):
    return _resolve(db.housing_units, identifier, "ERR_RESOURCE_NOT_FOUND", "Housing unit")


def get_crew_deployment(identifier):
    return _resolve(
        db.crew_deployments, identifier, "ERR_RESOURCE_NOT_FOUND", "Crew deployment"
    )


def get_damage_line(identifier):
    return _resolve(db.damage_lines, identifier, "ERR_RESOURCE_NOT_FOUND", "Damage line")


def get_work_ticket(identifier):
    return _resolve(db.work_tickets, identifier, "ERR_RESOURCE_NOT_FOUND", "Work ticket")


def get_supplement(identifier):
    return _resolve(db.supplements, identifier, "ERR_RESOURCE_NOT_FOUND", "Supplement")


def get_quality_inspection(identifier):
    return _resolve(
        db.quality_inspections, identifier, "ERR_RESOURCE_NOT_FOUND", "Quality inspection"
    )
