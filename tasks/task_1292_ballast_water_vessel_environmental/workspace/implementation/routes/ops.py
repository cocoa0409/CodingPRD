"""Record books and entries, emissions/fuel records, and crew drills
(PRD 3.7, 3.8, 3.9)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from auth import ALL_ROLES, require_roles
from db import now, store
from errors import (ApiError, ERR_BOOK_SEALED, ERR_ENTRY_KIND_MISMATCH,
                    ERR_INVALID_STATE, ERR_OFFICER_REQUIRED,
                    ERR_SULFUR_OUT_OF_RANGE, ERR_VALIDATION)
from response import ok, ok_list
from services import (DRILL_RECURRENCE_DAYS, ECA_LIMIT, GLOBAL_LIMIT,
                      book_json, create_noncompliance, drill_json,
                      emission_json, entry_json, get_book, get_drill,
                      get_emission, get_vessel, get_voyage, mint,
                      recompute_posture, touch)
from utils import (by_created, get_body, opt_num, opt_str, pagination_params,
                   parse_dt, query_filter, req_bool, req_enum, req_field,
                   req_list, req_num, req_str)

bp = Blueprint("ops", __name__)

BOOK_KINDS = ("BALLAST_WATER", "GARBAGE", "SEWAGE", "OILY_WATER")
STANDING_BOOK_KINDS = ("GARBAGE", "SEWAGE", "OILY_WATER")
ENTRY_KINDS_BY_BOOK = {
    "BALLAST_WATER": ("UPTAKE", "DISCHARGE", "EXCHANGE", "TREATMENT",
                      "TANK_FLUSH"),
    "GARBAGE": ("DISCHARGE_SEA", "DISCHARGE_RECEPTION", "INCINERATION"),
    "SEWAGE": ("DISCHARGE_TREATED", "DISCHARGE_UNTREATED"),
    "OILY_WATER": ("BILGE_DISCHARGE", "SLUDGE_DISPOSAL", "ODM_FLUSH"),
}
# Entries whose kind names a discharge require position coordinates.
DISCHARGE_TYPE_ENTRIES = ("DISCHARGE", "DISCHARGE_SEA", "DISCHARGE_RECEPTION",
                          "DISCHARGE_TREATED", "DISCHARGE_UNTREATED",
                          "BILGE_DISCHARGE")
DISTANCE_REQUIRED_ENTRIES = ("DISCHARGE_SEA", "DISCHARGE_UNTREATED",
                             "BILGE_DISCHARGE")
FUEL_TYPES = ("HFO", "VLSFO", "MGO", "MDO", "LNG", "BIOFUEL_BLEND")
DRILL_KINDS = ("BWMS_OPERATION", "EMERGENCY_BALLAST_EXCHANGE",
               "OIL_SPILL_RESPONSE", "SEWAGE_SYSTEM", "GARBAGE_MANAGEMENT",
               "MARPOL_AWARENESS")


def _officer_present(attendees):
    """True iff the attendee list includes at least one officer."""
    for attendee in attendees or []:
        if isinstance(attendee, str) and "officer" in attendee.lower():
            return True
        if isinstance(attendee, dict):
            for key in ("rank", "role", "title", "position"):
                value = attendee.get(key)
                if isinstance(value, str) and "officer" in value.lower():
                    return True
            for key in ("officer", "is_officer"):
                if attendee.get(key) is True:
                    return True
    return False


# ---------------------------------------------------------------------------
# Record books
# ---------------------------------------------------------------------------

@bp.post("/vessels/<vessel_id>/record-books")
@require_roles("ShoreComplianceOfficer", "VesselMaster")
def create_book(vessel_id):
    vessel = get_vessel(vessel_id)
    body = get_body()
    kind = req_enum(body, "book_kind", BOOK_KINDS)
    if kind == "BALLAST_WATER":
        raise ApiError(ERR_VALIDATION, 400,
                       "BALLAST_WATER record books are auto-created per "
                       "voyage on departure")
    voyage_id = opt_str(body, "voyage_id")
    if voyage_id is not None:
        voyage = store.voyages.get(voyage_id)
        if voyage is None or voyage["vessel_id"] != vessel["id"]:
            raise ApiError(ERR_VALIDATION, 400,
                           "voyage_id does not resolve to a voyage of this "
                           "vessel")
    with store.lock:
        book = mint({
            "vessel_id": vessel["id"],
            "book_kind": kind,
            "voyage_id": voyage_id,
            "status": "OPEN",
        })
        store.record_books[book["id"]] = book
    return ok(book_json(book), 201)


@bp.get("/vessels/<vessel_id>/record-books")
@require_roles(*ALL_ROLES)
def list_books(vessel_id):
    vessel = get_vessel(vessel_id)
    limit, offset = pagination_params()
    kind = query_filter("book_kind")
    status = query_filter("status")
    voyage_id = query_filter("voyage_id")
    items = [b for b in store.record_books.values()
             if b["vessel_id"] == vessel["id"]]
    if kind is not None:
        items = [b for b in items if b["book_kind"] == kind]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if voyage_id is not None:
        items = [b for b in items if b["voyage_id"] == voyage_id]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([book_json(b) for b in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/record-books/<book_id>/entries")
@require_roles("VesselMaster")
def create_entry(vessel_id, book_id):
    vessel = get_vessel(vessel_id)
    book = get_book(vessel, book_id)
    if book["status"] == "SEALED":
        raise ApiError(ERR_BOOK_SEALED, 409,
                       "a sealed record book rejects new entries")
    body = get_body()
    kind = req_enum(body, "entry_kind",
                    tuple(k for kinds in ENTRY_KINDS_BY_BOOK.values()
                          for k in kinds))
    occurred_at = parse_dt(req_field(body, "occurred_at"), "occurred_at")
    quantity = req_num(body, "quantity", gt=0)
    signed_by = req_str(body, "signed_by")
    if kind not in ENTRY_KINDS_BY_BOOK[book["book_kind"]]:
        raise ApiError(ERR_ENTRY_KIND_MISMATCH, 422,
                       "entry_kind %s is not allowed for a %s book"
                       % (kind, book["book_kind"]))
    lat = opt_num(body, "position_lat")
    lon = opt_num(body, "position_lon")
    distance = opt_num(body, "distance_from_shore_nm")
    countersigned_by = opt_str(body, "countersigned_by")
    if kind in DISCHARGE_TYPE_ENTRIES and (lat is None or lon is None):
        raise ApiError(ERR_VALIDATION, 400,
                       "position coordinates are required for discharge-type "
                       "entries")
    if kind in DISTANCE_REQUIRED_ENTRIES and distance is None:
        raise ApiError(ERR_VALIDATION, 400,
                       "distance_from_shore_nm is required for this entry "
                       "kind")
    # PRD 3.7 lists countersigned_by among the optional append fields; the
    # countersignature requirement for OILY_WATER and SEWAGE entries is
    # enforced at sealing ("every entry in the book must carry its required
    # countersignature"), not at append.
    with store.lock:
        entry = mint({
            "record_book_id": book["id"],
            "entry_kind": kind,
            "occurred_at": occurred_at,
            "quantity": quantity,
            "position_lat": lat,
            "position_lon": lon,
            "distance_from_shore_nm": distance,
            "signed_by": signed_by,
            "countersigned_by": countersigned_by,
        }, ledger=True)
        store.record_entries[entry["id"]] = entry
    return ok(entry_json(entry), 201)


@bp.get("/vessels/<vessel_id>/record-books/<book_id>/entries")
@require_roles(*ALL_ROLES)
def list_entries(vessel_id, book_id):
    vessel = get_vessel(vessel_id)
    book = get_book(vessel, book_id)
    limit, offset = pagination_params()
    kind = query_filter("entry_kind")
    items = [e for e in store.record_entries.values()
             if e["record_book_id"] == book["id"]]
    if kind is not None:
        items = [e for e in items if e["entry_kind"] == kind]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([entry_json(e) for e in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/record-books/<book_id>/seal")
@require_roles("VesselMaster")
def seal_book(vessel_id, book_id):
    vessel = get_vessel(vessel_id)
    book = get_book(vessel, book_id)
    if book["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "only an OPEN book may be sealed")
    if book["book_kind"] == "BALLAST_WATER":
        voyage = store.voyages.get(book["voyage_id"])
        if voyage is None or voyage["compliance_status"] not in (
                "COMPLIANT", "NONCOMPLIANT", "EXEMPT"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "a BALLAST_WATER book may be sealed only once the "
                           "voyage is COMPLIANT, NONCOMPLIANT, or EXEMPT")
    entries = [e for e in store.record_entries.values()
               if e["record_book_id"] == book["id"]]
    if book["book_kind"] in ("OILY_WATER", "SEWAGE"):
        if any(e for e in entries if not e["countersigned_by"]):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "every entry must carry its required "
                           "countersignature before the book can be sealed")
    with store.lock:
        book["status"] = "SEALED"
        touch(book)
        touch(vessel)
    return ok(book_json(book), 200)


# ---------------------------------------------------------------------------
# Emissions / fuel records
# ---------------------------------------------------------------------------

@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/emissions")
@require_roles("VesselMaster")
def create_emission(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    body = get_body()
    fuel_type = req_enum(body, "fuel_type", FUEL_TYPES)
    sulfur = req_field(body, "sulfur_content_pct")
    if isinstance(sulfur, bool) or not isinstance(sulfur, (int, float)):
        raise ApiError(ERR_VALIDATION, 400,
                       "sulfur_content_pct must be a number")
    if sulfur < 0 or sulfur > 5.0:
        raise ApiError(ERR_SULFUR_OUT_OF_RANGE, 422,
                       "sulfur_content_pct must be in [0, 5.0]")
    consumed = req_num(body, "consumed_volume_mt", gt=0)
    inside = req_num(body, "inside_eca_hours", gte=0)
    outside = req_num(body, "outside_eca_hours", gte=0)
    scrubber = req_bool(body, "scrubber_installed")
    with store.lock:
        record = mint({
            "voyage_id": voyage["id"],
            "fuel_type": fuel_type,
            "sulfur_content_pct": sulfur,
            "consumed_volume_mt": consumed,
            "inside_eca_hours": inside,
            "outside_eca_hours": outside,
            "compliance_status": "PENDING_EVAL",
            "scrubber_installed": scrubber,
        })
        store.emissions[record["id"]] = record
    return ok(emission_json(record), 201)


@bp.get("/vessels/<vessel_id>/voyages/<voyage_id>/emissions")
@require_roles(*ALL_ROLES)
def list_emissions(vessel_id, voyage_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    limit, offset = pagination_params()
    status = query_filter("compliance_status")
    items = [e for e in store.emissions.values()
             if e["voyage_id"] == voyage["id"]]
    if status is not None:
        items = [e for e in items if e["compliance_status"] == status]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([emission_json(e) for e in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/voyages/<voyage_id>/emissions/<record_id>/evaluate")
@require_roles("ShoreComplianceOfficer")
def evaluate_emission(vessel_id, voyage_id, record_id):
    vessel = get_vessel(vessel_id)
    voyage = get_voyage(vessel, voyage_id)
    record = get_emission(voyage, record_id)
    if record["compliance_status"] != "PENDING_EVAL":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a PENDING_EVAL record may be evaluated")
    with store.lock:
        if record["scrubber_installed"]:
            # An approved EGCS exempts the fuel sulfur limit; with no ECA
            # hours logged the record is simply compliant.
            outcome = ("EXEMPT_SCRUBBER" if record["inside_eca_hours"] > 0
                       else "COMPLIANT")
        else:
            sulfur = Decimal(str(record["sulfur_content_pct"]))
            eca_ok = record["inside_eca_hours"] == 0 or sulfur <= ECA_LIMIT
            global_ok = sulfur <= GLOBAL_LIMIT
            outcome = "COMPLIANT" if (eca_ok and global_ok) else "NONCOMPLIANT"
        record["compliance_status"] = outcome
        touch(record)
        if outcome == "COMPLIANT":
            touch(vessel)
        elif outcome == "NONCOMPLIANT":
            create_noncompliance(vessel, voyage["id"],
                                 "DETERMINATION_NONCOMPLIANT", record["id"])
            recompute_posture(vessel)
    return ok(emission_json(record), 200)


# ---------------------------------------------------------------------------
# Crew training and drills
# ---------------------------------------------------------------------------

@bp.post("/vessels/<vessel_id>/drills")
@require_roles("ShoreComplianceOfficer", "VesselMaster")
def create_drill(vessel_id):
    vessel = get_vessel(vessel_id)
    body = get_body()
    kind = req_enum(body, "drill_kind", DRILL_KINDS)
    scheduled_for = parse_dt(req_field(body, "scheduled_for"), "scheduled_for")
    attendees = req_list(body, "attendees")
    with store.lock:
        drill = mint({
            "vessel_id": vessel["id"],
            "drill_kind": kind,
            "scheduled_for": scheduled_for,
            "completed_at": None,
            "completion_status": "SCHEDULED",
            "attendees": attendees,
            "officer_present": _officer_present(attendees),
            "next_due_at": None,
        })
        store.drills[drill["id"]] = drill
    return ok(drill_json(drill), 201)


@bp.get("/vessels/<vessel_id>/drills")
@require_roles(*ALL_ROLES)
def list_drills(vessel_id):
    vessel = get_vessel(vessel_id)
    limit, offset = pagination_params()
    kind = query_filter("drill_kind")
    status = query_filter("completion_status")
    items = [d for d in store.drills.values() if d["vessel_id"] == vessel["id"]]
    if kind is not None:
        items = [d for d in items if d["drill_kind"] == kind]
    if status is not None:
        items = [d for d in items if d["completion_status"] == status]
    items = by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([drill_json(d) for d in page], total, limit, offset)


@bp.post("/vessels/<vessel_id>/drills/<drill_id>/complete")
@require_roles("VesselMaster")
def complete_drill(vessel_id, drill_id):
    vessel = get_vessel(vessel_id)
    drill = get_drill(vessel, drill_id)
    if drill["completion_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SCHEDULED drill may be completed")
    body = get_body()
    completed_at = drill["completed_at"]
    if body.get("completed_at") is not None:
        completed_at = parse_dt(body["completed_at"], "completed_at")
    if completed_at is None:
        completed_at = now()
    attendees = drill["attendees"]
    if body.get("attendees") is not None:
        attendees = req_list(body, "attendees")
    officer = _officer_present(attendees)
    if drill["drill_kind"] == "BWMS_OPERATION" and not officer:
        raise ApiError(ERR_OFFICER_REQUIRED, 422,
                       "a BWMS_OPERATION drill requires at least one officer "
                       "present to complete")
    with store.lock:
        drill["attendees"] = attendees
        drill["officer_present"] = officer
        drill["completion_status"] = "COMPLETED"
        drill["completed_at"] = completed_at
        drill["next_due_at"] = completed_at + timedelta(
            days=DRILL_RECURRENCE_DAYS[drill["drill_kind"]])
        touch(drill)
    return ok(drill_json(drill), 200)


@bp.post("/vessels/<vessel_id>/drills/<drill_id>/cancel")
@require_roles("VesselMaster")
def cancel_drill(vessel_id, drill_id):
    vessel = get_vessel(vessel_id)
    drill = get_drill(vessel, drill_id)
    if drill["completion_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SCHEDULED drill may be cancelled")
    if now() > drill["scheduled_for"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "a drill may only be cancelled no later than its "
                       "scheduled time")
    with store.lock:
        drill["completion_status"] = "CANCELLED"
        touch(drill)
    return ok(drill_json(drill), 200)
