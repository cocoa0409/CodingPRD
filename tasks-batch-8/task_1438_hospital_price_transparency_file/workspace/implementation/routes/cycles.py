"""PublicationCycle: open, read, facility-scoped list, freeze, publish."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CYCLE_NOT_FOUND,
    ERR_CYCLE_PERIOD_OVERLAP,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_POSTURE_NOT_FREEZABLE,
    ERR_POSTURE_NOT_PUBLISHABLE,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import cycle_posture, cycle_sealed_file, cycle_view
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("cycles", __name__)

CYCLE_TYPES = {"MONTHLY", "ANNUAL"}


def get_cycle_or_404(cid: str) -> dict:
    c = db.publication_cycles.get(cid)
    if c is None:
        raise_err(ERR_CYCLE_NOT_FOUND, "Publication cycle not found")
    return c


@bp.post("/transparency/publication-cycles")
@require_roles("TransparencyOfficer")
def create_cycle(_user_id: str, _role: str):
    body = get_json_body()
    facility_id = require_string(body, "facility_id")
    cycle_type_raw = require_string(body, "cycle_type")
    period_start = require_ts(body, "period_start")
    period_end = require_ts(body, "period_end")
    schema_version = require_string(body, "schema_version")

    # Existence (P3).
    if facility_id not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")

    # Enum membership after FK existence.
    if cycle_type_raw not in CYCLE_TYPES:
        raise_err(ERR_INVALID_REQUEST, "cycle_type must be MONTHLY or ANNUAL")

    # Temporal sanity first (PRD 3.3 prose order): the half-open window must
    # be non-empty — equality is rejected.
    start = parse_iso8601(period_start, "period_start")
    end = parse_iso8601(period_end, "period_end")
    if start >= end:
        raise_err(ERR_INVALID_WINDOW, "period_start must be strictly before period_end")

    # Structural: half-open overlap with non-terminal cycles of the same
    # facility+cycle_type; touching endpoints do NOT count as overlap.
    for other in db.publication_cycles.values():
        if (
            other["facility_id"] == facility_id
            and other["cycle_type"] == cycle_type_raw
            and other["status"] != "SUPERSEDED"
        ):
            o_start = parse_iso8601(other["period_start"], "period_start")
            o_end = parse_iso8601(other["period_end"], "period_end")
            if start < o_end and end > o_start:
                raise_err(ERR_CYCLE_PERIOD_OVERLAP, "Overlapping non-terminal cycle exists for this facility+cycle_type")

    cycle = db.stamp_new({
        "facility_id": facility_id,
        "cycle_type": cycle_type_raw,
        "period_start": period_start,
        "period_end": period_end,
        "schema_version": schema_version,
        "status": "OPEN",
    })
    db.publication_cycles[cycle["id"]] = cycle
    return success_object(cycle_view(cycle), 201)


@bp.get("/transparency/publication-cycles/<cid>")
@require_roles(*ALL_ROLES)
def get_cycle(cid: str, _user_id: str, _role: str):
    return success_object(cycle_view(get_cycle_or_404(cid)), 200)


@bp.get("/transparency/facilities/<fid>/publication-cycles")
@require_roles(*ALL_ROLES)
def list_facility_cycles(fid: str, _user_id: str, _role: str):
    if fid not in db.facilities:
        raise_err(ERR_FACILITY_NOT_FOUND, "Facility not found")
    limit, offset = parse_pagination()
    items = [c for c in db.publication_cycles.values() if c["facility_id"] == fid]
    items = apply_filters(items, ["cycle_type", "status"])
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([cycle_view(c) for c in page], limit, offset, total)


@bp.post("/transparency/publication-cycles/<cid>/freeze")
@require_roles("TransparencyOfficer")
def freeze_cycle(cid: str, _user_id: str, _role: str):
    cycle = get_cycle_or_404(cid)
    # Posture gate: any posture other than FREEZABLE rejects, including cycles
    # that have already left OPEN (PRD 3.4).
    if cycle_posture(cycle) != "FREEZABLE":
        raise_err(ERR_POSTURE_NOT_FREEZABLE, "Cycle posture is not FREEZABLE")
    cycle["status"] = "FROZEN"
    db.bump(cycle)
    return success_object(cycle_view(cycle), 200)


@bp.post("/transparency/publication-cycles/<cid>/publish")
@require_roles("TransparencyOfficer")
def publish_cycle(cid: str, _user_id: str, _role: str):
    cycle = get_cycle_or_404(cid)
    # Posture gate: exactly PUBLISHABLE required (one SEALED VALID file).
    if cycle_posture(cycle) != "PUBLISHABLE":
        raise_err(ERR_POSTURE_NOT_PUBLISHABLE, "Cycle posture is not PUBLISHABLE")

    sealed = cycle_sealed_file(cid)

    # Main transition.
    cycle["status"] = "PUBLISHED"
    db.bump(cycle)

    # Link: the cycle's VALIDATED records publish with it.
    for rec in db.standard_charge_records.values():
        if rec["publication_cycle_id"] == cid and rec["status"] == "VALIDATED":
            rec["status"] = "PUBLISHED"
            db.bump(rec)

    # Link: the sealed file publishes on its generation dimension.
    if sealed is not None:
        sealed["generation_status"] = "PUBLISHED"
        db.bump(sealed)

    # Monthly/annual versioning: the prior PUBLISHED cycle of the same
    # facility+cycle_type supersedes, taking its PUBLISHED records and files.
    priors = [
        c for c in db.publication_cycles.values()
        if c["facility_id"] == cycle["facility_id"]
        and c["cycle_type"] == cycle["cycle_type"]
        and c["status"] == "PUBLISHED"
        and c["id"] != cid
    ]
    priors.sort(key=lambda c: (-db.parse_dt(c["period_start"]).timestamp(), c["created_at"], c["_seq"]))
    for prior in priors:
        prior["status"] = "SUPERSEDED"
        db.bump(prior)
        for rec in db.standard_charge_records.values():
            if rec["publication_cycle_id"] == prior["id"] and rec["status"] == "PUBLISHED":
                rec["status"] = "SUPERSEDED"
                db.bump(rec)
        for f in db.machine_readable_files.values():
            if f["publication_cycle_id"] == prior["id"] and f["generation_status"] == "PUBLISHED":
                f["generation_status"] = "SUPERSEDED"
                db.bump(f)

    return success_object(cycle_view(cycle), 200)
