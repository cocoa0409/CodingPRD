"""Shared route helpers: path/FK resolution (priorities 3 and 4) and paging."""

import errors as E
from db import db, ordered
from errors import ApiError
from response import ok_list
from validation import pagination

PARTY_TYPES = ("ROOFER", "SOLAR_OWNER", "SYSTEM_OWNER", "SOLAR_CONTRACTOR")
OWNERSHIP_MODELS = ("HOST_OWNED", "LEASE", "PPA")
PROJECT_PHASES = (
    "INTAKE",
    "APPROVALS_OPEN",
    "AUTHORIZED",
    "DEENERGIZED",
    "DECK_WORK",
    "REINSTALL",
    "COMMISSIONED",
    "CLOSED",
)
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
APPROVAL_STATUSES = ("PENDING", "APPROVED", "CHANGES_REQUESTED")
CIRCUIT_STATUSES = ("ENERGIZED", "ISOLATION_PENDING", "ISOLATED")
UNIT_TYPES = ("PANEL", "OPTIMIZER")
HANDLING_STATUSES = ("ON_ROOF", "REMOVED", "STORED", "REINSTALLED", "SCRAPPED")
CONDITION_GRADES = ("UNINSPECTED", "SERVICEABLE", "DAMAGED", "REPLACED")
FINDING_TYPES = (
    "SHEATHING_ROT",
    "FASTENER_PULLOUT",
    "FLASHING_FAILURE",
    "MOISTURE_INTRUSION",
    "STRUCTURAL_DEFLECTION",
)
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
FINDING_STATUSES = ("OPEN", "UPGRADE_SCOPED", "UPGRADE_COMPLETED", "WAIVED")
PERMIT_SCOPES = ("REINSTALL_ONLY", "STRUCTURAL_UPGRADE", "FULL_REPERMIT")
PERMIT_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
INSPECTION_TYPES = ("ROOF_DECK", "MOUNTING", "ELECTRICAL_FINAL")
INSPECTION_STATUSES = ("SCHEDULED", "PASSED", "FAILED", "CORRECTION_REQUIRED")
TRADES = ("ROOFING", "SOLAR_REMOVAL", "SOLAR_REINSTALL")
WINDOW_STATUSES = (
    "SCHEDULED",
    "IN_PROGRESS",
    "COMPLETED",
    "WEATHER_ABORTED",
    "SUPERSEDED",
    "REVOKED",
)
ORDER_STATUSES = ("PENDING_REVIEW", "APPROVED", "REJECTED", "RECEIVED")
MATCH_CLASSES = ("EXACT", "COMPATIBLE", "MISMATCHED")


def _lookup(collection, identifier, error_id, label):
    row = None
    if isinstance(identifier, str):
        row = collection.get(identifier)
    if row is None:
        raise ApiError(error_id, "%s not found" % label, 404)
    return row


def get_project(identifier):
    return _lookup(db.projects, identifier, E.ERR_PROJECT_NOT_FOUND, "project")


def get_party(identifier):
    return _lookup(db.parties, identifier, E.ERR_PARTY_NOT_FOUND, "party")


def get_jurisdiction(identifier):
    return _lookup(db.jurisdictions, identifier, E.ERR_JURISDICTION_NOT_FOUND, "jurisdiction")


def get_approval(identifier):
    return _lookup(db.approvals, identifier, E.ERR_APPROVAL_NOT_FOUND, "consent record")


def get_circuit(identifier):
    return _lookup(db.circuits, identifier, E.ERR_CIRCUIT_NOT_FOUND, "array circuit")


def get_bin(identifier):
    return _lookup(db.bins, identifier, E.ERR_BIN_NOT_FOUND, "storage bin")


def get_unit(identifier):
    return _lookup(db.units, identifier, E.ERR_UNIT_NOT_FOUND, "hardware unit")


def get_finding(identifier):
    return _lookup(db.findings, identifier, E.ERR_FINDING_NOT_FOUND, "deck finding")


def get_permit(identifier):
    return _lookup(db.permits, identifier, E.ERR_PERMIT_NOT_FOUND, "permit application")


def get_inspection(identifier):
    return _lookup(db.inspections, identifier, E.ERR_INSPECTION_NOT_FOUND, "inspection")


def get_window(identifier):
    return _lookup(db.windows, identifier, E.ERR_WINDOW_NOT_FOUND, "work window")


def get_order(identifier):
    return _lookup(db.orders, identifier, E.ERR_SOURCING_ORDER_NOT_FOUND, "sourcing order")


def resolve_fk(body, name, getter):
    """Validation priority 4: resolve a body foreign key before schema checks.

    A missing or non-string value is left for the schema step to reject.
    """
    if not isinstance(body, dict):
        return None
    value = body.get(name)
    if not isinstance(value, str) or value == "":
        return None
    return getter(value)


def require_party_type(party, allowed):
    if party is None:
        return
    if party["party_type"] not in allowed:
        raise ApiError(
            E.ERR_PARTY_TYPE_MISMATCH,
            "party %s has type %s which is not one of %s"
            % (party["id"], party["party_type"], ", ".join(allowed)),
            422,
        )


def party_type_mismatch(message):
    return ApiError(E.ERR_PARTY_TYPE_MISMATCH, message, 422)


def acting_party_must_be(role_types):
    """Priority 17: the acting party's own party_type must be suitable."""
    from flask import g

    party = db.parties.get(g.get("actor_id"))
    if party is None or party["party_type"] not in role_types:
        raise party_type_mismatch(
            "acting party must be of type %s" % ", ".join(role_types)
        )
    return party


def check_frozen(project):
    """Priority 10."""
    if project["posture"] == "FROZEN":
        raise ApiError(
            E.ERR_PROJECT_POSTURE_FROZEN, "project posture is FROZEN", 409
        )


def check_restricted(project):
    """Priority 11."""
    if project["posture"] == "RESTRICTED":
        raise ApiError(
            E.ERR_PROJECT_POSTURE_RESTRICTED, "project posture is RESTRICTED", 409
        )


def invalid_state(message):
    return ApiError(E.ERR_INVALID_STATE, message, 409)


def list_response(rows):
    limit, offset = pagination()
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def paged(rows):
    """Validate paging first (priority 5) then return the response."""
    return list_response(rows)
