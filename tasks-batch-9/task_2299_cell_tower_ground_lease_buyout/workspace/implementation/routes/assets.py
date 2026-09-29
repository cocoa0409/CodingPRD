"""Tower companies, tower sites and landowners (PRD 3.2)."""

from flask import Blueprint

import engine as E
import validate as V
from auth import principal
from db import db
from response import created, ok, ok_list

bp = Blueprint("assets", __name__)

STRUCTURE_TYPES = ("MONOPOLE", "LATTICE", "GUYED", "ROOFTOP")
ENTITY_TYPES = ("INDIVIDUAL", "LLC", "TRUST", "CORPORATION", "MUNICIPALITY")

SITE_READ_ROLES = ("AcquisitionAnalyst", "PlatformAdmin", "PortfolioManager", "TitleOfficer")
LANDOWNER_READ_ROLES = ("AcquisitionAnalyst", "PlatformAdmin", "PortfolioManager",
                        "ServicingAgent", "Landowner")


# ------------------------------------------------------------- tower companies

@bp.post("/tower-companies")
def create_tower_company():
    principal("PlatformAdmin", "AcquisitionAnalyst")
    b = V.body()
    legal_name = V.req_str(b, "legal_name")
    notice_email = V.req_str(b, "notice_email")
    rofr_required = V.opt_bool(b, "rofr_required", default=False)
    window_days = V.opt_int(b, "rofr_window_days", default=30, minimum=1, maximum=90)

    company = E.new_entity(
        legal_name=legal_name,
        rofr_required=rofr_required,
        rofr_window_days=window_days,
        notice_email=notice_email,
        site_count=0,
    )
    db.tower_companies[company["id"]] = company
    return created(E.tower_company_json(company))


# ----------------------------------------------------------------- tower sites

@bp.post("/tower-sites")
def create_tower_site():
    principal("AcquisitionAnalyst", "PlatformAdmin")
    b = V.body()
    company = E.fk(b, "tower_company_id", "tower_companies", "ERR_TOWER_COMPANY_NOT_FOUND")
    if company is None:
        V.bad()
    site_code = V.req_str(b, "site_code")
    state_code = V.req_str(b, "state_code")
    area = V.req_int(b, "ground_area_sqft", minimum=1)
    structure = V.req_enum(b, "structure_type", STRUCTURE_TYPES)

    site = E.new_entity(
        tower_company_id=company["id"],
        site_code=site_code,
        state_code=state_code,
        ground_area_sqft=area,
        structure_type=structure,
        lease_stream_count=0,
    )
    db.tower_sites[site["id"]] = site
    company["site_count"] += 1
    E.touch(company)
    return created(E.tower_site_json(site))


@bp.get("/tower-sites")
def list_tower_sites():
    principal(*SITE_READ_ROLES)
    limit, offset = V.pagination()
    company_id = V.str_filter("tower_company_id")
    state_code = V.str_filter("state_code")
    structure = V.enum_filter("structure_type", STRUCTURE_TYPES)
    rows = E.ordered(list(db.tower_sites.values()))
    if company_id is not None:
        rows = [r for r in rows if r["tower_company_id"] == company_id]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if structure is not None:
        rows = [r for r in rows if r["structure_type"] == structure]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.tower_site_json(r) for r in page], total, limit, offset)


@bp.get("/tower-sites/<sid>")
def get_tower_site(sid):
    principal(*SITE_READ_ROLES)
    site = E.find("tower_sites", sid, "ERR_TOWER_SITE_NOT_FOUND")
    return ok(E.tower_site_json(site))


# ------------------------------------------------------------------ landowners

@bp.post("/landowners")
def create_landowner():
    principal("AcquisitionAnalyst", "PlatformAdmin")
    b = V.body()
    legal_name = V.req_str(b, "legal_name")
    entity_type = V.req_enum(b, "entity_type", ENTITY_TYPES)
    contact_email = V.req_str(b, "contact_email")

    landowner = E.new_entity(
        legal_name=legal_name,
        entity_type=entity_type,
        contact_email=contact_email,
        derived_outreach_status="NEW",
        suppress_outreach=False,
        open_dispute_count=0,
    )
    db.landowners[landowner["id"]] = landowner
    return created(E.landowner_json(landowner))


@bp.get("/landowners/<lid>")
def get_landowner(lid):
    principal(*LANDOWNER_READ_ROLES)
    landowner = E.find("landowners", lid, "ERR_LANDOWNER_NOT_FOUND")
    return ok(E.landowner_json(landowner))


@bp.patch("/landowners/<lid>")
def patch_landowner(lid):
    principal("AcquisitionAnalyst", "PlatformAdmin")
    landowner = E.find("landowners", lid, "ERR_LANDOWNER_NOT_FOUND")
    b = V.body()
    email = V.opt_str(b, "contact_email")
    suppress = V.opt_bool(b, "suppress_outreach")

    changed = False
    if email is not None and email != landowner["contact_email"]:
        landowner["contact_email"] = email
        changed = True
    if suppress is not None and suppress != landowner["suppress_outreach"]:
        landowner["suppress_outreach"] = suppress
        changed = True
    if changed:
        E.touch(landowner)
    return ok(E.landowner_json(landowner))
