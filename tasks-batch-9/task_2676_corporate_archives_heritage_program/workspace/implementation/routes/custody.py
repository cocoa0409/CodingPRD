"""Accessions, archival items, storage zones and finding aids."""

from flask import Blueprint, g

from core import clock, register, sorted_rows, store, touch
from errors import ApiError
from middleware import endpoint
from response import apply_filters, collection_response, object_response
from services import calc
from services.lookup import (
    described_item_count,
    fetch,
    items_of_accession,
    recompute_accession_counters,
    series_of_accession,
    stale_item_count,
)
from validation import (
    ARRANGEMENT_LEVELS,
    CONDITION_GRADES,
    ORIGINAL_FORMATS,
    SENSITIVITY_LEVELS,
    TRANSFER_INSTRUMENTS,
    body,
    venum,
    vid,
    vint,
    vnum,
    vstr,
)

bp = Blueprint("custody", __name__)

ALL_READERS = (
    "ArchivesDirector",
    "Archivist",
    "LegalCounsel",
    "AccessServicesOfficer",
    "PreservationOfficer",
)
ZONE_READERS = ("ArchivesDirector", "Archivist", "PreservationOfficer")
AID_READERS = ("ArchivesDirector", "Archivist", "AccessServicesOfficer", "Requester")


def _guard_series_not_frozen(series):
    if series["disposition_state"] == "SUSPENDED" or series["legal_hold_active"]:
        raise ApiError("ERR_SERIES_DISPOSITION_SUSPENDED")


# --- accessions ------------------------------------------------------------


@bp.post("/accessions")
@endpoint(("Archivist",))
def create_accession():
    payload = body()
    record_series_id = vid(payload, "record_series_id")
    donor_name = vstr(payload, "donor_name", 1, 160)
    transfer_instrument = venum(payload, "transfer_instrument", TRANSFER_INSTRUMENTS)
    declared_unit_count = vint(payload, "declared_unit_count", 1, None)
    series = fetch("record_series", record_series_id)
    row = register(
        store.accessions,
        {
            "record_series_id": series["id"],
            "donor_name": donor_name,
            "transfer_instrument": transfer_instrument,
            "declared_unit_count": declared_unit_count,
            "status": "RECEIVED",
            "provenance_documented": False,
            "provenance_statement": None,
            "transfer_instrument_reference": None,
            "rejection_reason": None,
            "processed_unit_count": 0,
            "deaccessioned_unit_count": 0,
        },
    )
    return object_response(row, 201)


@bp.get("/accessions")
@endpoint(ALL_READERS)
def list_accessions():
    rows = apply_filters(
        sorted_rows(store.accessions),
        {"record_series_id": "record_series_id", "status": "status"},
    )
    return collection_response(rows)


@bp.get("/accessions/<resource_id>")
@endpoint(ALL_READERS)
def get_accession(resource_id):
    return object_response(fetch("accessions", resource_id))


@bp.post("/accessions/<resource_id>/verify-provenance")
@endpoint(("Archivist",))
def verify_provenance(resource_id):
    payload = body()
    statement = vstr(payload, "provenance_statement", 1, None)
    reference = vstr(payload, "transfer_instrument_reference", 1, None)
    accession = fetch("accessions", resource_id)
    if accession["status"] != "RECEIVED":
        raise ApiError("ERR_ACCESSION_STATE_INVALID")
    _guard_series_not_frozen(series_of_accession(accession))
    accession["provenance_statement"] = statement
    accession["transfer_instrument_reference"] = reference
    accession["provenance_documented"] = True
    accession["status"] = "PROVENANCE_VERIFIED"
    touch(accession)
    return object_response(accession)


@bp.post("/accessions/<resource_id>/process")
@endpoint(("Archivist",))
def process_accession(resource_id):
    accession = fetch("accessions", resource_id)
    # rung 11 sits ahead of the state guard
    if not accession["provenance_documented"]:
        raise ApiError("ERR_PROVENANCE_NOT_DOCUMENTED")
    if accession["status"] != "PROVENANCE_VERIFIED":
        raise ApiError("ERR_ACCESSION_STATE_INVALID")
    if accession["processed_unit_count"] != accession["declared_unit_count"]:
        raise ApiError("ERR_UNIT_COUNT_MISMATCH")
    accession["status"] = "PROCESSED"
    touch(accession)
    for item in sorted_rows(store.archival_items):
        if item["accession_id"] != accession["id"] or item["status"] != "UNPROCESSED":
            continue
        item["status"] = "ACCESSIONED"
        item["units_on_shelf"] = item["unit_count"]
        item["units_on_loan"] = 0
        item["units_deaccessioned"] = 0
        item["preservation_format"] = item["original_format"]
        touch(item)
    return object_response(accession)


@bp.post("/accessions/<resource_id>/reject")
@endpoint(("ArchivesDirector",))
def reject_accession(resource_id):
    payload = body()
    reason = vstr(payload, "rejection_reason", 1, None)
    accession = fetch("accessions", resource_id)
    if accession["status"] not in ("RECEIVED", "PROVENANCE_VERIFIED"):
        raise ApiError("ERR_ACCESSION_STATE_INVALID")
    accession["rejection_reason"] = reason
    accession["status"] = "REJECTED"
    touch(accession)
    for item in sorted_rows(store.archival_items):
        if item["accession_id"] != accession["id"] or item["status"] != "UNPROCESSED":
            continue
        item["status"] = "REJECTED_ITEM"
        item["units_on_shelf"] = 0
        touch(item)
    recompute_accession_counters(accession)
    return object_response(accession)


# --- archival items --------------------------------------------------------


@bp.post("/archival-items")
@endpoint(("Archivist",))
def create_archival_item():
    payload = body()
    accession_id = vid(payload, "accession_id")
    storage_zone_id = vid(payload, "storage_zone_id")
    item_label = vstr(payload, "item_label", 1, 120)
    unit_count = vint(payload, "unit_count", 1, None)
    condition_grade = venum(payload, "condition_grade", CONDITION_GRADES)
    original_format = venum(payload, "original_format", ORIGINAL_FORMATS)
    sensitivity_level = venum(payload, "sensitivity_level", SENSITIVITY_LEVELS)
    brand_use_year = vint(payload, "brand_use_year", 1800, 2100, required=False, default=None)
    accession = fetch("accessions", accession_id)
    zone = fetch("storage_zones", storage_zone_id)
    row = register(
        store.archival_items,
        {
            "accession_id": accession["id"],
            "storage_zone_id": zone["id"],
            "item_label": item_label,
            "unit_count": unit_count,
            "condition_grade": condition_grade,
            "original_format": original_format,
            "preservation_format": original_format,
            "sensitivity_level": sensitivity_level,
            "brand_use_year": brand_use_year,
            "status": "UNPROCESSED",
            "units_on_shelf": unit_count,
            "units_on_loan": 0,
            "units_deaccessioned": 0,
            "digital_surrogate_available": False,
            "last_loan_window_end": None,
        },
    )
    recompute_accession_counters(accession)
    return object_response(row, 201)


@bp.get("/archival-items")
@endpoint(ALL_READERS)
def list_archival_items():
    rows = apply_filters(
        sorted_rows(store.archival_items),
        {
            "accession_id": "accession_id",
            "storage_zone_id": "storage_zone_id",
            "status": "status",
            "original_format": "original_format",
        },
    )
    return collection_response(rows)


@bp.get("/archival-items/<resource_id>")
@endpoint(ALL_READERS)
def get_archival_item(resource_id):
    return object_response(fetch("archival_items", resource_id))


# --- storage zones ---------------------------------------------------------


@bp.post("/storage-zones")
@endpoint(("PreservationOfficer",))
def create_storage_zone():
    payload = body()
    zone_code = vstr(payload, "zone_code", 2, 32)
    temperature_c = vnum(payload, "temperature_c")
    relative_humidity_pct = vnum(payload, "relative_humidity_pct")
    max_overlapping = vint(payload, "max_overlapping_migration_jobs", 1, 20)
    for existing in store.storage_zones.values():
        if existing["zone_code"] == zone_code:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE_KEY", "Zone code '%s' already exists." % zone_code
            )
    row = register(
        store.storage_zones,
        {
            "zone_code": zone_code,
            "temperature_c": temperature_c,
            "relative_humidity_pct": relative_humidity_pct,
            "max_overlapping_migration_jobs": max_overlapping,
            "environmental_status": calc.zone_environmental_status(
                temperature_c, relative_humidity_pct
            ),
            "reading_count": 1,
        },
    )
    return object_response(row, 201)


@bp.get("/storage-zones")
@endpoint(ZONE_READERS)
def list_storage_zones():
    rows = apply_filters(
        sorted_rows(store.storage_zones), {"environmental_status": "environmental_status"}
    )
    return collection_response(rows)


@bp.get("/storage-zones/<resource_id>")
@endpoint(ZONE_READERS)
def get_storage_zone(resource_id):
    return object_response(fetch("storage_zones", resource_id))


@bp.post("/storage-zones/<resource_id>/environment-readings")
@endpoint(("PreservationOfficer",))
def record_environment_reading(resource_id):
    payload = body()
    temperature_c = vnum(payload, "temperature_c")
    relative_humidity_pct = vnum(payload, "relative_humidity_pct")
    zone = fetch("storage_zones", resource_id)
    zone["temperature_c"] = temperature_c
    zone["relative_humidity_pct"] = relative_humidity_pct
    zone["environmental_status"] = calc.zone_environmental_status(
        temperature_c, relative_humidity_pct
    )
    zone["reading_count"] += 1
    touch(zone)
    return object_response(zone)


# --- finding aids ----------------------------------------------------------


@bp.post("/finding-aids")
@endpoint(("Archivist",))
def create_finding_aid():
    payload = body()
    accession_id = vid(payload, "accession_id")
    title = vstr(payload, "title", 1, 200)
    arrangement_level = venum(payload, "arrangement_level", ARRANGEMENT_LEVELS)
    version_label = vstr(payload, "version_label", 1, 16)
    accession = fetch("accessions", accession_id)
    row = register(
        store.finding_aids,
        {
            "accession_id": accession["id"],
            "title": title,
            "arrangement_level": arrangement_level,
            "version_label": version_label,
            "status": "DRAFT",
            "described_item_count": 0,
            "stale_item_count": 0,
            "revision_cycle_count": 0,
            "published_at": None,
        },
    )
    return object_response(row, 201)


@bp.get("/finding-aids")
@endpoint(AID_READERS)
def list_finding_aids():
    rows = apply_filters(
        sorted_rows(store.finding_aids), {"accession_id": "accession_id", "status": "status"}
    )
    return collection_response(rows)


@bp.get("/finding-aids/<resource_id>")
@endpoint(AID_READERS)
def get_finding_aid(resource_id):
    return object_response(fetch("finding_aids", resource_id))


@bp.post("/finding-aids/<resource_id>/submit-review")
@endpoint(("Archivist",))
def submit_finding_aid_review(resource_id):
    payload = body()
    version_label = vstr(payload, "version_label", 1, 16, required=False, default=None)
    aid = fetch("finding_aids", resource_id)
    if aid["status"] not in ("DRAFT", "NEEDS_REVISION"):
        raise ApiError("ERR_FINDING_AID_STATE_INVALID")
    accession = store.accessions[aid["accession_id"]]
    if aid["status"] == "DRAFT" and accession["status"] != "PROCESSED":
        raise ApiError("ERR_ACCESSION_STATE_INVALID")
    if aid["status"] == "NEEDS_REVISION":
        aid["revision_cycle_count"] += 1
    if version_label is not None:
        aid["version_label"] = version_label
    aid["described_item_count"] = described_item_count(accession["id"])
    aid["stale_item_count"] = stale_item_count(accession["id"])
    aid["status"] = "UNDER_REVIEW"
    touch(aid)
    return object_response(aid)


@bp.post("/finding-aids/<resource_id>/publish")
@endpoint(("ArchivesDirector",))
def publish_finding_aid(resource_id):
    aid = fetch("finding_aids", resource_id)
    if aid["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_FINDING_AID_STATE_INVALID")
    if aid["stale_item_count"] != 0:
        raise ApiError(
            "ERR_FINDING_AID_STATE_INVALID",
            "The finding aid still describes items sliding towards disposal.",
        )
    aid["described_item_count"] = described_item_count(aid["accession_id"])
    aid["published_at"] = clock.now()
    aid["status"] = "PUBLISHED"
    touch(aid)
    return object_response(aid)
