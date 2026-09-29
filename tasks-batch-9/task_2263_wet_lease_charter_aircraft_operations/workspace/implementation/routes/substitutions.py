"""Airframe substitutions and irregular-operations recovery (PRD 3.7)."""

from flask import Blueprint, request

from db import db, new_row, touch, public
from errors import ApiError
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, MAINTENANCE_CONTROLLER,
)
from response import object_response, pagination, paged
from routes.common import find_aircraft, find_lease, find_substitution, filtered
from services import calculations as C
from services import workflows as W
import validate as V

bp = Blueprint("substitutions", __name__)

SUBSTITUTABLE_LEASE_STATUSES = ("ACTIVE", "SUSPENDED")
OPEN_SUBSTITUTION_STATUSES = ("REQUESTED", "LESSEE_CONSENT_PENDING", "APPROVED")


@bp.post("/wetlease/substitutions")
def create_substitution():
    require((LESSOR_OPS,))
    body = V.json_body()
    lease_id = V.req_str(body, "lease_id")
    original_aircraft_id = V.req_str(body, "original_aircraft_id")
    reason = V.req_enum(body, "reason", ("AOG", "SCHEDULED_MAINTENANCE", "IRREGULAR_OPS"))
    effective_raw, effective_from = V.req_datetime(body, "effective_from")
    expected_lease_version = V.req_int(body, "expected_lease_version")
    substitute_aircraft_id = V.opt_str(body, "substitute_aircraft_id")
    consent_note = V.opt_str(body, "consent_note")

    original = find_aircraft(original_aircraft_id)
    substitute = find_aircraft(substitute_aircraft_id) \
        if substitute_aircraft_id is not None else None
    lease = find_lease(lease_id)

    if expected_lease_version != lease["version"]:
        raise ApiError("ERR_STALE_LEASE_VERSION")
    if lease["status"] not in SUBSTITUTABLE_LEASE_STATUSES:
        raise ApiError("ERR_LEASE_INVALID_STATE")

    if substitute is not None:
        selection_basis = "CLIENT_SPECIFIED"
        if substitute["maintenance_program_ref"] != lease["required_maintenance_program_ref"]:
            raise ApiError("ERR_MAINTENANCE_PROGRAM_MISALIGNED")
        if not C.substitute_is_eligible(substitute, original, lease):
            raise ApiError("ERR_SUBSTITUTION_TYPE_MISMATCH")
    else:
        selection_basis = "SERVER_SELECTED"
        pool = [a for a in db.aircraft.values()
                if C.substitute_is_eligible(a, original, lease)]
        if not pool:
            raise ApiError("ERR_NO_SUBSTITUTE_AIRCRAFT_AVAILABLE")
        substitute = C.rank_substitutes(pool, original)[0]

    if lease["substitution_rights"] == "LESSOR_UNILATERAL":
        status = "APPROVED"
        for other in W.substitutions_of_lease(lease_id):
            if other["status"] in OPEN_SUBSTITUTION_STATUSES:
                other["status"] = "WITHDRAWN"
                touch(other)
    else:
        status = "LESSEE_CONSENT_PENDING"

    row = new_row()
    row.update({
        "lease_id": lease_id,
        "original_aircraft_id": original_aircraft_id,
        "substitute_aircraft_id": substitute["id"],
        "reason": reason,
        "effective_from": effective_raw,
        "selection_basis": selection_basis,
        "seat_delta": substitute["seat_count"] - original["seat_count"],
        "repointed_leg_count": 0,
        "status": status,
        "consent_note": consent_note,
        "_effective_from": effective_from,
    })
    db.substitutions[row["id"]] = row

    touch(lease)
    return object_response(public(row), 201)


@bp.get("/wetlease/substitutions/<substitution_id>")
def get_substitution(substitution_id):
    actor = require((LESSOR_OPS, MAINTENANCE_CONTROLLER, LESSEE))
    row = find_substitution(substitution_id)
    check_ownership(actor, "substitution", row)
    return object_response(public(row))


@bp.get("/wetlease/substitutions")
def list_substitutions():
    actor = require((LESSOR_OPS, MAINTENANCE_CONTROLLER, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.substitutions.values()), request.args, {
        "lease_id": "lease_id",
        "original_aircraft_id": "original_aircraft_id",
        "substitute_aircraft_id": "substitute_aircraft_id",
        "status": "status",
    })
    rows = scope_for_lessee(actor, "substitution", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/substitutions/<substitution_id>/consent")
def consent_substitution(substitution_id):
    actor = require((LESSEE,))
    body = V.json_body()
    decision = V.req_enum(body, "decision", ("GRANT", "WITHHOLD"))
    consent_note = V.opt_str(body, "consent_note")
    row = find_substitution(substitution_id)
    check_ownership(actor, "substitution", row)

    if row["status"] != "LESSEE_CONSENT_PENDING":
        raise ApiError("ERR_SUBSTITUTION_INVALID_STATE")

    row["status"] = "APPROVED" if decision == "GRANT" else "REJECTED"
    if consent_note is not None:
        row["consent_note"] = consent_note
    touch(row)
    return object_response(public(row))


@bp.post("/wetlease/substitutions/<substitution_id>/effectuate")
def effectuate_substitution(substitution_id):
    require((LESSOR_OPS,))
    V.json_body()
    row = find_substitution(substitution_id)
    lease = db.leases.get(row["lease_id"])
    if lease is None:
        raise ApiError("ERR_LEASE_NOT_FOUND")

    if lease["status"] not in SUBSTITUTABLE_LEASE_STATUSES:
        raise ApiError("ERR_LEASE_INVALID_STATE")

    consent_pending = (row["status"] == "LESSEE_CONSENT_PENDING"
                       and lease["substitution_rights"] == "LESSEE_CONSENT_REQUIRED")
    if row["status"] != "APPROVED" and not consent_pending:
        raise ApiError("ERR_SUBSTITUTION_INVALID_STATE")

    substitute = db.aircraft.get(row["substitute_aircraft_id"])
    if substitute is None:
        raise ApiError("ERR_AIRCRAFT_NOT_FOUND")
    if substitute["status"] != "AVAILABLE" or substitute["assigned_lease_id"] is not None:
        raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")
    if substitute["maintenance_program_ref"] != lease["required_maintenance_program_ref"]:
        raise ApiError("ERR_MAINTENANCE_PROGRAM_MISALIGNED")

    if consent_pending:
        raise ApiError("ERR_SUBSTITUTION_CONSENT_REQUIRED")

    original = db.aircraft.get(row["original_aircraft_id"])

    # Level one — re-point the airframe of record.
    substitute["status"] = "ASSIGNED"
    substitute["assigned_lease_id"] = lease["id"]
    touch(substitute)
    if original is not None:
        original["assigned_lease_id"] = None
        if original["status"] == "ASSIGNED":
            original["status"] = "AVAILABLE"
        touch(original)
    lease["primary_aircraft_id"] = substitute["id"]

    # Level two — re-point the affected scheduled legs.
    repointed = []
    for leg in W.legs_of_lease(lease["id"]):
        if (leg["status"] == "SCHEDULED"
                and leg["aircraft_id"] == row["original_aircraft_id"]
                and leg["_scheduled_out"] >= row["_effective_from"]):
            leg["aircraft_id"] = substitute["id"]
            touch(leg)
            repointed.append(leg)

    row["status"] = "EFFECTIVE"
    row["repointed_leg_count"] = len(repointed)
    touch(row)

    # Levels three and four — strand the unrated crews.
    for leg in repointed:
        captain = db.crew_members.get(leg["captain_id"])
        first_officer = db.crew_members.get(leg["first_officer_id"])
        rated = True
        for crew in (captain, first_officer):
            if crew is None or substitute["type_designator"] not in crew["type_ratings"]:
                rated = False
        if not rated:
            W.cancel_leg(leg, "LESSOR", "CREW", requalification=True)

    touch(lease)
    return object_response(public(row))
