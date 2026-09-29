"""Artists, sites, artworks, maintenance protocols and conservators (PRD 3.1, 3.3, 3.4, 3.7)."""

from flask import Blueprint, g

import services as svc
from db import create_record, db, fmt_instant, now, ordered, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, listing, ok
from validate import (
    ACCREDITATIONS,
    CONSERVATION_STATUSES,
    CUSTODY_STATUSES,
    EXPOSURE_CLASSES,
    MATERIAL_CLASSES,
    PRIORITY_BASES,
    PROTOCOL_METHODS,
    SIGNIFICANCE_TIERS,
    SOLVENT_CLASSES,
    apply_filters,
    bad,
    field,
    paging,
    parse_input,
)

bp = Blueprint("registry", __name__)


# ---------------------------------------------------------------------------
# Artist
# ---------------------------------------------------------------------------

@bp.post("/public-art/artists")
@endpoint(("CollectionsRegistrar", "PublicArtManager"))
def create_artist():
    body = parse_input({
        "full_name": field("string", required=True),
        "is_living": field("bool", required=True),
        "contact_email": field("string", required=True),
        "deceased_on": field("date"),
        "moral_rights_waiver_on_file": field("bool", default=False),
        "notice_wait_days": field("int", default=90, minimum=1, maximum=365),
        "consultation_response_days": field("int", default=30, minimum=1, maximum=180),
        "represented_by": field("string"),
    })
    if body["is_living"] and body["deceased_on"] is not None:
        bad("deceased_on must be null when is_living is true.")
    if not body["is_living"] and body["deceased_on"] is None:
        bad("deceased_on is required when is_living is false.")
    record = create_record(db.artists, {
        "full_name": body["full_name"],
        "is_living": body["is_living"],
        "deceased_on": body["deceased_on"],
        "moral_rights_waiver_on_file": body["moral_rights_waiver_on_file"],
        "notice_wait_days": body["notice_wait_days"],
        "consultation_response_days": body["consultation_response_days"],
        "contact_email": body["contact_email"],
        "represented_by": body["represented_by"],
        "artwork_count": 0,
    })
    return created(record)


@bp.get("/public-art/artists/<artist_id>")
@endpoint(ANY_ROLE)
def read_artist(artist_id):
    return ok(svc.artist_or_404(artist_id))


@bp.get("/public-art/artists")
@endpoint(ANY_ROLE)
def list_artists():
    limit, offset = paging()
    rows = apply_filters(db.artists.values(), (("is_living", "is_living", "bool"),))
    return listing(ordered(rows), limit, offset)


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------

@bp.post("/public-art/sites")
@endpoint(("CollectionsRegistrar", "PublicArtManager"))
def create_site():
    body = parse_input({
        "site_code": field("string", required=True),
        "name": field("string", required=True),
        "address_ref": field("string", required=True),
        "exposure_class": field("enum", required=True, enum=EXPOSURE_CLASSES),
        "capacity_units": field("int", required=True, minimum=0),
        "concurrent_work_capacity": field("int", default=1, minimum=1),
    })
    for existing in db.sites.values():
        if existing["site_code"] == body["site_code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "site_code is already registered.")
    record = create_record(db.sites, {
        "site_code": body["site_code"],
        "name": body["name"],
        "address_ref": body["address_ref"],
        "exposure_class": body["exposure_class"],
        "capacity_units": body["capacity_units"],
        "installed_units_used": 0,
        "concurrent_work_capacity": body["concurrent_work_capacity"],
    })
    return created(record)


@bp.get("/public-art/sites/<site_id>")
@endpoint(ANY_ROLE)
def read_site(site_id):
    return ok(svc.site_or_404(site_id))


@bp.get("/public-art/sites")
@endpoint(ANY_ROLE)
def list_sites():
    limit, offset = paging()
    rows = apply_filters(db.sites.values(), (("exposure_class", "exposure_class", "string"),))
    return listing(ordered(rows), limit, offset)


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------

def _moral_rights_status(artist):
    if artist.get("moral_rights_waiver_on_file"):
        return "WAIVED"
    if not artist.get("is_living"):
        return "EXPIRED"
    return "ACTIVE"


@bp.post("/public-art/artworks")
@endpoint(("CollectionsRegistrar",))
def create_artwork():
    body = parse_input({
        "accession_number": field("string", required=True),
        "title": field("string", required=True),
        "artist_id": field("id", required=True),
        "site_id": field("id", required=True),
        "material_class": field("enum", required=True, enum=MATERIAL_CLASSES),
        "significance_tier": field("enum", required=True, enum=SIGNIFICANCE_TIERS),
        "footprint_units": field("int", required=True, minimum=1),
        "insured_value_cents": field("int", required=True, minimum=0),
        "acquisition_date": field("date", required=True),
        "acquisition_document_ref": field("string", required=True),
        "recognized_stature": field("bool", default=False),
    })
    artist = svc.artist_or_404(body["artist_id"])
    site = svc.site_or_404(body["site_id"])
    for existing in db.artworks.values():
        if existing["accession_number"] == body["accession_number"]:
            raise ApiError("ERR_DUPLICATE_CODE", "accession_number is already in use.")
    if int(site["installed_units_used"]) + int(body["footprint_units"]) > int(site["capacity_units"]):
        raise ApiError("ERR_SITE_CAPACITY_EXCEEDED")

    record = create_record(db.artworks, {
        "accession_number": body["accession_number"],
        "title": body["title"],
        "artist_id": artist["id"],
        "site_id": site["id"],
        "material_class": body["material_class"],
        "significance_tier": body["significance_tier"],
        "footprint_units": body["footprint_units"],
        "insured_value_cents": body["insured_value_cents"],
        "acquisition_date": body["acquisition_date"],
        "acquisition_document_ref": body["acquisition_document_ref"],
        "recognized_stature": body["recognized_stature"],
        "custody_status": "ON_VIEW",
        "conservation_status": "MONITORED",
        "condition_index": None,
        "treatment_priority_score": None,
        "treatment_priority_rank": None,
        "priority_basis": "NONE",
        "moral_rights_status": _moral_rights_status(artist),
        "open_notice_count": 0,
        "last_maintenance_completed_on": None,
        "next_maintenance_due_on": None,
        "maintenance_applications_ytd": 0,
    })
    svc.recompute_site_units(site)
    svc.recompute_artist_count(artist)
    return created(record)


@bp.get("/public-art/artworks/<artwork_id>")
@endpoint(ANY_ROLE)
def read_artwork(artwork_id):
    return ok(svc.artwork_or_404(artwork_id))


@bp.get("/public-art/artworks")
@endpoint(ANY_ROLE)
def list_artworks():
    limit, offset = paging()
    rows = apply_filters(db.artworks.values(), (
        ("artist_id", "artist_id", "string"),
        ("site_id", "site_id", "string"),
        ("material_class", "material_class", "string"),
        ("custody_status", "custody_status", "string"),
        ("conservation_status", "conservation_status", "string"),
        ("priority_basis", "priority_basis", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/artworks/<artwork_id>/relocate")
@endpoint(("CollectionsRegistrar",))
def relocate_artwork(artwork_id):
    artwork = svc.artwork_or_404(artwork_id)
    body = parse_input({
        "to_storage": field("bool"),
        "to_site_id": field("id"),
        "relocation_note": field("string"),
    })
    to_storage = body["to_storage"] is True
    to_site_id = body["to_site_id"]
    if to_storage and to_site_id is not None:
        bad("Supply either to_storage or to_site_id, not both.")
    if not to_storage and to_site_id is None:
        bad("Supply to_storage true to withdraw the work, or to_site_id to reinstall it.")
    target_site = svc.site_or_404(to_site_id) if to_site_id is not None else None

    svc.require_in_collection(artwork)

    if to_storage:
        if artwork["custody_status"] != "ON_VIEW":
            raise ApiError("ERR_ARTWORK_CUSTODY_INVALID")
        notice = None
        if artwork["moral_rights_status"] == "ACTIVE":
            notice = svc.authorizing_notice(artwork, ("RELOCATION",))
        old_site = svc.site_of(artwork)
        artwork["custody_status"] = "IN_STORAGE"
        touch(artwork)
        if notice is not None:
            svc.consume_notice(notice, artwork["id"])
            svc.recompute_open_notice_count(artwork)
        svc.recompute_site_units(old_site)
        return ok(artwork)

    if artwork["custody_status"] != "IN_STORAGE":
        raise ApiError("ERR_ARTWORK_CUSTODY_INVALID")
    if int(target_site["installed_units_used"]) + int(artwork["footprint_units"]) > int(
        target_site["capacity_units"]
    ):
        raise ApiError("ERR_SITE_CAPACITY_EXCEEDED")
    old_site = svc.site_of(artwork)
    artwork["site_id"] = target_site["id"]
    artwork["custody_status"] = "ON_VIEW"
    touch(artwork)
    if old_site is not None and old_site["id"] != target_site["id"]:
        svc.recompute_site_units(old_site)
    svc.recompute_site_units(target_site)
    return ok(artwork)


# ---------------------------------------------------------------------------
# MaintenanceProtocol
# ---------------------------------------------------------------------------

@bp.post("/public-art/maintenance-protocols")
@endpoint(("ChiefConservator", "PublicArtManager"))
def create_protocol():
    body = parse_input({
        "protocol_code": field("string", required=True),
        "material_class": field("enum", required=True, enum=MATERIAL_CLASSES),
        "method": field("enum", required=True, enum=PROTOCOL_METHODS),
        "cycle_days": field("int", required=True, minimum=1, maximum=3650),
        "max_annual_applications": field("int", default=4, minimum=1),
        "requires_conservator": field("bool", default=False),
        "solvent_class": field("enum", default="NONE", enum=SOLVENT_CLASSES),
    })
    for existing in db.protocols.values():
        if existing["protocol_code"] == body["protocol_code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "protocol_code is already declared.")
    record = create_record(db.protocols, {
        "protocol_code": body["protocol_code"],
        "material_class": body["material_class"],
        "method": body["method"],
        "cycle_days": body["cycle_days"],
        "max_annual_applications": body["max_annual_applications"],
        "requires_conservator": body["requires_conservator"],
        "solvent_class": body["solvent_class"],
    })
    return created(record)


@bp.get("/public-art/maintenance-protocols/<protocol_id>")
@endpoint(ANY_ROLE)
def read_protocol(protocol_id):
    return ok(svc.protocol_or_404(protocol_id))


@bp.get("/public-art/maintenance-protocols")
@endpoint(ANY_ROLE)
def list_protocols():
    limit, offset = paging()
    rows = apply_filters(db.protocols.values(), (
        ("material_class", "material_class", "string"),
        ("method", "method", "string"),
    ))
    return listing(ordered(rows), limit, offset)


# ---------------------------------------------------------------------------
# Conservator
# ---------------------------------------------------------------------------

@bp.post("/public-art/conservators")
@endpoint(("PublicArtManager",))
def create_conservator():
    body = parse_input({
        "firm_name": field("string", required=True),
        "accreditation": field("enum", required=True, enum=ACCREDITATIONS),
        "material_specialties": field("enum_array", required=True, enum=MATERIAL_CLASSES),
        "hourly_rate_cents": field("int", required=True, minimum=1),
        "insurance_expires_on": field("date", required=True),
    })
    record = create_record(db.conservators, {
        "firm_name": body["firm_name"],
        "accreditation": body["accreditation"],
        "material_specialties": body["material_specialties"],
        "hourly_rate_cents": body["hourly_rate_cents"],
        "insurance_expires_on": body["insurance_expires_on"],
        "status": "ACTIVE",
        "active_engagement_count": 0,
    })
    return created(record)


@bp.get("/public-art/conservators/<conservator_id>")
@endpoint(ANY_ROLE)
def read_conservator(conservator_id):
    return ok(svc.conservator_or_404(conservator_id))


@bp.get("/public-art/conservators")
@endpoint(ANY_ROLE)
def list_conservators():
    limit, offset = paging()
    rows = apply_filters(db.conservators.values(), (
        ("status", "status", "string"),
        ("material_specialty", "material_specialties", "member"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/conservators/<conservator_id>/suspend")
@endpoint(("PublicArtManager",))
def suspend_conservator(conservator_id):
    conservator = svc.conservator_or_404(conservator_id)
    parse_input({"reason": field("string", required=True)})
    if conservator["status"] != "SUSPENDED":
        conservator["status"] = "SUSPENDED"
        touch(conservator)
    return ok(conservator)
