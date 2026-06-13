"""Sanctions screenings: cross-collection list, single get, resolve."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth, require_role
from response import success_array, success_object
from services.common import (
    parse_pagination,
    paginate,
    require_body,
    sort_by_created,
)
from services.lookups import get_sanctions_screening
from services.model import serialize, touch
from services.posture import recompute_provider

bp = Blueprint("sanctions", __name__)


@bp.route("/sanctions-screenings", methods=["GET"])
def list_screenings():
    _, role = require_auth()
    require_role(role, {"ComplianceOfficer", "SystemAdmin"})
    source_id = request.args.get("sanctions_source_id")
    provider_id = request.args.get("provider_id")
    limit, offset = parse_pagination()
    rows = []
    for s in store.sanctions_screenings.values():
        if source_id is not None and s["sanctions_source_id"] != source_id:
            continue
        if provider_id is not None and s["provider_id"] != provider_id:
            continue
        rows.append(s)
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/sanctions-screenings/<rid>", methods=["GET"])
def get_screening_route(rid):
    _, role = require_auth()
    require_role(role, {"ComplianceOfficer", "CredentialingSpecialist",
                        "MedicalDirector", "SystemAdmin"})
    rec = get_sanctions_screening(rid)
    return success_object(serialize(rec), 200)


@bp.route("/sanctions-screenings/<rid>/resolve", methods=["POST"])
def resolve_screening(rid):
    _, role = require_auth()
    require_role(role, {"ComplianceOfficer"})
    sc = get_sanctions_screening(rid)
    body = require_body()

    resolution_note = body.get("resolution_note")

    if sc["status"] != "OPEN":
        raise err("ERR_SCREENING_NOT_OPEN", "Screening is not OPEN.")
    if not isinstance(resolution_note, str) or resolution_note.strip() == "":
        raise err("ERR_RESOLUTION_NOTE_REQUIRED", "resolution_note is required.")

    sc["status"] = "RESOLVED"
    sc["resolution_note"] = resolution_note
    touch(sc)

    prov = store.providers.get(sc["provider_id"])
    if prov is not None:
        recompute_provider(prov, recompute_readiness=True)
    return success_object(serialize(sc), 200)
