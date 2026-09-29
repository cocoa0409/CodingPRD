"""FIRM panel inventory and the map-revision cascade (Cascade C)."""

from flask import Blueprint

from db import base_fields, db, iso, iso_now, sort_rows, to_dt, touch
from errors import fail
from middleware import ALL_ROLES, require
from response import list_response, object_response
from services import calc, engine
from validation import (body, fk, lookup, opt_num, pagination, paginate,
                        query_filters, req_dt, req_enum, req_str)

bp = Blueprint("panels", __name__)


def _effective_sibling(community_id, panel_number, exclude_id=None):
    for panel in sort_rows(list(db.firm_panels.values())):
        if (panel["community_id"] == community_id
                and panel["panel_number"] == panel_number
                and panel["status"] == "EFFECTIVE"
                and panel["id"] != exclude_id):
            return panel
    return None


def _check_geometry(community_id, panel_number, effective_date, exclude_id=None):
    incumbent = _effective_sibling(community_id, panel_number, exclude_id)
    if incumbent is not None and to_dt(incumbent["effective_date"]) >= to_dt(effective_date):
        fail("ERR_PANEL_EFFECTIVE_DATE_OVERLAP")
    return incumbent


@bp.post("/firm-panels")
def create_panel():
    require("StateNfipCoordinator")
    data = body()
    community_id = fk(data, "community_id", "community")
    panel_number = req_str(data, "panel_number")
    suffix = req_str(data, "suffix")
    flood_zone = req_enum(data, "flood_zone", calc.FLOOD_ZONES)
    effective_date = req_dt(data, "effective_date")
    bfe = opt_num(data, "base_flood_elevation_ft")
    lookup("community", community_id)

    _check_geometry(community_id, panel_number, effective_date)
    for panel in db.firm_panels.values():
        if (panel["community_id"] == community_id
                and panel["panel_number"] == panel_number
                and panel["status"] == "PENDING_REVISION"):
            fail("ERR_DUPLICATE_PANEL_REVISION")

    row = base_fields()
    row.update({
        "community_id": community_id,
        "panel_number": panel_number,
        "suffix": suffix,
        "flood_zone": flood_zone,
        "base_flood_elevation_ft": bfe,
        "effective_date": iso(effective_date),
        "status": "PENDING_REVISION",
        "supersedes_panel_id": None,
        "activated_at": None,
    })
    db.firm_panels[row["id"]] = row
    return object_response(row, 201)


@bp.get("/firm-panels/<panel_id>")
def read_panel(panel_id):
    require(*ALL_ROLES)
    return object_response(lookup("firm_panel", panel_id))


@bp.get("/firm-panels")
def list_panels():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.firm_panels.values()), {
        "community_id": ("community_id", None),
        "supersedes_panel_id": ("supersedes_panel_id", None),
        "panel_number": ("panel_number", None),
        "status": ("status", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/firm-panels/<panel_id>/activate")
def activate_panel(panel_id):
    require("StateNfipCoordinator")
    panel = lookup("firm_panel", panel_id)
    if panel["status"] != "PENDING_REVISION":
        fail("ERR_PANEL_NOT_PENDING")
    incumbent = _check_geometry(panel["community_id"], panel["panel_number"],
                               panel["effective_date"], exclude_id=panel["id"])

    panel["status"] = "EFFECTIVE"
    panel["activated_at"] = iso_now()
    panel["supersedes_panel_id"] = incumbent["id"] if incumbent else None
    touch(panel)

    if incumbent is not None:
        _map_revision_cascade(panel, incumbent)
    return object_response(panel)


def _map_revision_cascade(panel, incumbent):
    # hop 1 — the incumbent retires
    incumbent["status"] = "SUPERSEDED"
    touch(incumbent)

    # hop 2 — properties are repointed
    repointed = [p for p in db.properties.values()
                 if p["firm_panel_id"] == incumbent["id"]]
    repointed = sort_rows(repointed)
    for prop in repointed:
        prop["firm_panel_id"] = panel["id"]
        touch(prop)

    # hop 3 — stale permit snapshots are pushed back into revision
    property_ids = {p["id"] for p in repointed}
    candidates = [p for p in db.permits.values()
                  if p["property_id"] in property_ids
                  and p["status"] in ("UNDER_REVIEW", "APPROVED")]
    moved = []
    for permit in sort_rows(candidates):
        if (permit["determined_bfe_ft"] == panel["base_flood_elevation_ft"]
                and permit["determined_zone"] == panel["flood_zone"]):
            continue
        structure = db.structures.get(permit["structure_id"])
        permit["status"] = "REVISION_REQUIRED"
        permit["determined_zone"] = panel["flood_zone"]
        permit["determined_bfe_ft"] = panel["base_flood_elevation_ft"]
        permit["required_lowest_floor_elevation_ft"] = (
            engine.required_elevation(permit, structure) if structure else None)
        touch(permit)
        if structure is not None:
            engine.refresh_submitted_certificates(permit)
            moved.append(permit)

    # hop 4 — accepted surveys of those structures no longer reflect the map
    seen = set()
    for permit in moved:
        structure_id = permit["structure_id"]
        if structure_id in seen:
            continue
        seen.add(structure_id)
        structure = db.structures[structure_id]
        superseded = False
        for certificate in sort_rows(engine.certificates_of_structure(structure_id)):
            if certificate["status"] != "ACCEPTED":
                continue
            certificate["status"] = "SUPERSEDED"
            touch(certificate)
            superseded = True
        if not superseded:
            continue
        changed = False
        if structure["lowest_floor_elevation_ft"] is not None:
            structure["lowest_floor_elevation_ft"] = None
            changed = True
        if structure["compliance_status"] not in ("PRE_FIRM_EXISTING", "PENDING_CERTIFICATE"):
            structure["compliance_status"] = "PENDING_CERTIFICATE"
            changed = True
        if changed:
            touch(structure)
