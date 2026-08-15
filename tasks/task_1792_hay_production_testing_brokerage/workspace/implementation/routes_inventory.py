"""Bale lots, spoilage events, forage tests (lab pipeline)."""

from decimal import Decimal

from flask import Blueprint, request

from auth import authorize
from db import store, new_id, stamp_new, stamp_new_light, touch
from domain import (
    BALE_TYPES, SPOILAGE_REASONS, site_occupancy, physical_tonnage,
    quality_tier_assignment, release_open_allocations_for_lot, grower_of_cutting,
)
from errors import (
    ApiError, ERR_CUTTING_NOT_FOUND, ERR_SITE_NOT_FOUND, ERR_LOT_NOT_FOUND,
    ERR_TEST_NOT_FOUND, ERR_LOT_NOT_ACTIVE, ERR_TEST_WRONG_STATE,
    ERR_GROWER_SUSPENDED, ERR_CUTTING_NOT_CUT, ERR_TONS_NOT_POSITIVE,
    ERR_CAPACITY_EXCEEDED, ERR_STALE_VERSION, ERR_SEGREGATION_OF_DUTIES,
)
from response import success
from serializers import bale_lot_out, spoilage_event_out, forage_test_out
from util import (
    D, req, as_str, as_int, as_enum, as_number, as_date,
    get_body, paginate, sorted_by_created, invalid,
)

bp = Blueprint("inventory", __name__)


# --- BaleLot -----------------------------------------------------------------

def _new_lot_physical_tonnage(storage_site, harvested_tonnage, harvested_date):
    """Physical tonnage of a prospective lot, computed with the destination
    site's moisture flag at the current clock."""
    probe = {
        "storage_site_id": storage_site["id"],
        "harvested_tonnage": harvested_tonnage,
        "harvested_date": harvested_date,
        "spoilage_tonnage": Decimal("0.0"),
        "shipped_tonnage": Decimal("0.0"),
        "open_allocated_tonnage": Decimal("0.0"),
    }
    return physical_tonnage(probe)


@bp.post("/api/bale-lots")
def create_bale_lot():
    authorize(["BrokerOps", "PlatformAdmin"])
    body = get_body()
    cutting_id = as_str(req(body, "cutting_id"), "cutting_id")
    storage_site_id = as_str(req(body, "storage_site_id"), "storage_site_id")
    bale_type = as_enum(req(body, "bale_type"), "bale_type", BALE_TYPES)
    bale_count = as_int(req(body, "bale_count"), "bale_count")
    if bale_count <= 0:
        invalid("bale_count must be greater than zero")
    harvested_tonnage = as_number(req(body, "harvested_tonnage"), "harvested_tonnage")
    harvested_date = as_date(req(body, "harvested_date"), "harvested_date")
    # Priority 4: existence, body FKs in declared field order.
    cutting = store["cuttings"].get(cutting_id)
    if cutting is None:
        raise ApiError(ERR_CUTTING_NOT_FOUND, 404, "cutting not found")
    site = store["storage_sites"].get(storage_site_id)
    if site is None:
        raise ApiError(ERR_SITE_NOT_FOUND, 404, "storage site not found")
    # Priority 9: referenced grower must be ACTIVE; cutting must be CUT/HARVESTED.
    grower = grower_of_cutting(cutting)
    if grower is not None and grower["status"] != "ACTIVE":
        raise ApiError(ERR_GROWER_SUSPENDED, 422, "the cutting's grower is suspended")
    if cutting["status"] not in ("CUT", "HARVESTED"):
        raise ApiError(ERR_CUTTING_NOT_CUT, 422, "cutting is not CUT or HARVESTED")
    # Priority 10: tonnage positivity, then the physical capacity gate.
    if harvested_tonnage <= 0:
        raise ApiError(ERR_TONS_NOT_POSITIVE, 422, "harvested_tonnage must be greater than zero")
    occupied, _ = site_occupancy(site["id"])
    incoming = _new_lot_physical_tonnage(site, harvested_tonnage, harvested_date)
    if occupied + incoming > D(site["capacity_tons"]):
        raise ApiError(ERR_CAPACITY_EXCEEDED, 422,
                       "site physical occupancy plus the incoming lot would exceed capacity_tons")
    lot = stamp_new({
        "id": new_id(),
        "cutting_id": cutting_id,
        "storage_site_id": storage_site_id,
        "bale_type": bale_type,
        "bale_count": bale_count,
        "harvested_tonnage": harvested_tonnage,
        "harvested_date": harvested_date,
        "quality_tier": "UNGRADED",
        "certified_protein_pct": None,
        "shipped_tonnage": Decimal("0.0"),
        "spoilage_tonnage": Decimal("0.0"),
        "open_allocated_tonnage": Decimal("0.0"),
        "status": "ACTIVE",
    })
    store["bale_lots"][lot["id"]] = lot
    # First lot flips the cutting CUT -> HARVESTED; further lots remain allowed.
    if cutting["status"] == "CUT":
        cutting["status"] = "HARVESTED"
        touch(cutting)
    return success(bale_lot_out(lot), "object", 201)


@bp.get("/api/bale-lots")
def list_bale_lots():
    authorize(["PlatformAdmin", "BrokerOps"])
    items = list(store["bale_lots"].values())
    cutting_id = request.args.get("cutting_id")
    site_id = request.args.get("storage_site_id")
    status = request.args.get("status")
    tier = request.args.get("quality_tier")
    if cutting_id is not None:
        items = [l for l in items if l["cutting_id"] == cutting_id]
    if site_id is not None:
        items = [l for l in items if l["storage_site_id"] == site_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if tier is not None:
        items = [l for l in items if l["quality_tier"] == tier]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([bale_lot_out(l) for l in page], "array", 200, meta)


@bp.get("/api/bale-lots/<lot_id>")
def get_bale_lot(lot_id):
    authorize(["PlatformAdmin", "BrokerOps"])
    lot = store["bale_lots"].get(lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "bale lot not found")
    return success(bale_lot_out(lot), "object", 200)


@bp.post("/api/bale-lots/<lot_id>/condemn")
def condemn_bale_lot(lot_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    lot = store["bale_lots"].get(lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "bale lot not found")
    if lot["status"] != "ACTIVE":
        raise ApiError(ERR_LOT_NOT_ACTIVE, 409, "only an ACTIVE lot can be condemned")
    lot["status"] = "CONDEMNED"
    touch(lot)
    # Cascade: OPEN allocations -> RELEASED; affected LOADING loads replan.
    release_open_allocations_for_lot(lot)
    return success(bale_lot_out(lot), "object", 200)


@bp.post("/api/bale-lots/<lot_id>/transfer")
def transfer_bale_lot(lot_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    body = get_body()
    dest_site_id = as_str(req(body, "dest_storage_site_id"), "dest_storage_site_id")
    expected_version = as_int(req(body, "expected_bale_lot_version"), "expected_bale_lot_version")
    # Priority 4: path first, then body FK.
    lot = store["bale_lots"].get(lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "bale lot not found")
    dest = store["storage_sites"].get(dest_site_id)
    if dest is None:
        raise ApiError(ERR_SITE_NOT_FOUND, 404, "destination storage site not found")
    # Priority 6: lot must be ACTIVE, then the OCC stale-version guard.
    if lot["status"] != "ACTIVE":
        raise ApiError(ERR_LOT_NOT_ACTIVE, 409, "only an ACTIVE lot can be transferred")
    if expected_version != lot["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_bale_lot_version does not match the lot's current version")
    # Priority 10: destination physical occupancy gate (equality allowed).
    occupied, _ = site_occupancy(dest["id"])
    incoming = physical_tonnage(lot)
    if occupied + incoming > D(dest["capacity_tons"]):
        raise ApiError(ERR_CAPACITY_EXCEEDED, 422,
                       "destination site physical occupancy plus this lot would exceed capacity_tons")
    lot["storage_site_id"] = dest["id"]
    touch(lot)
    return success(bale_lot_out(lot), "object", 200)


# --- SpoilageEvent -----------------------------------------------------------

@bp.post("/api/spoilage-events")
def create_spoilage_event():
    authorize(["BrokerOps", "PlatformAdmin"])
    body = get_body()
    bale_lot_id = as_str(req(body, "bale_lot_id"), "bale_lot_id")
    event_date = as_date(req(body, "event_date"), "event_date")
    tons_lost = as_number(req(body, "tons_lost"), "tons_lost")
    reason = as_enum(req(body, "reason"), "reason", SPOILAGE_REASONS)
    lot = store["bale_lots"].get(bale_lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "bale lot not found")
    if tons_lost <= 0:
        raise ApiError(ERR_TONS_NOT_POSITIVE, 422, "tons_lost must be greater than zero")
    event = stamp_new_light({
        "id": new_id(),
        "bale_lot_id": bale_lot_id,
        "event_date": event_date,
        "tons_lost": tons_lost,
        "reason": reason,
    })
    store["spoilage_events"][event["id"]] = event
    lot["spoilage_tonnage"] = D(lot["spoilage_tonnage"]) + tons_lost
    touch(lot)
    return success(spoilage_event_out(event), "object", 201)


@bp.get("/api/bale-lots/<lot_id>/spoilage-events")
def list_spoilage_events(lot_id):
    authorize(["PlatformAdmin", "BrokerOps"])
    lot = store["bale_lots"].get(lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "bale lot not found")
    items = [e for e in store["spoilage_events"].values() if e["bale_lot_id"] == lot_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([spoilage_event_out(e) for e in page], "array", 200, meta)


# --- ForageTest --------------------------------------------------------------

@bp.post("/api/forage-tests")
def create_forage_test():
    authorize(["BrokerOps", "PlatformAdmin"])
    body = get_body()
    bale_lot_id = as_str(req(body, "bale_lot_id"), "bale_lot_id")
    sample_date = as_date(req(body, "sample_date"), "sample_date")
    lot = store["bale_lots"].get(bale_lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "bale lot not found")
    test = stamp_new({
        "id": new_id(),
        "bale_lot_id": bale_lot_id,
        "sample_date": sample_date,
        "lab_reference": None,
        "rfv": None,
        "protein_pct": None,
        "moisture_pct": None,
        "resulted_by_user_id": None,
        "certified_by_user_id": None,
        "status": "COLLECTED",
    })
    store["forage_tests"][test["id"]] = test
    return success(forage_test_out(test), "object", 201)


@bp.get("/api/forage-tests")
def list_forage_tests():
    authorize(["PlatformAdmin", "BrokerOps", "LabTechnician"])
    items = list(store["forage_tests"].values())
    lot_id = request.args.get("bale_lot_id")
    status = request.args.get("status")
    if lot_id is not None:
        items = [t for t in items if t["bale_lot_id"] == lot_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([forage_test_out(t) for t in page], "array", 200, meta)


@bp.get("/api/forage-tests/<test_id>")
def get_forage_test(test_id):
    authorize(["PlatformAdmin", "BrokerOps", "LabTechnician"])
    test = store["forage_tests"].get(test_id)
    if test is None:
        raise ApiError(ERR_TEST_NOT_FOUND, 404, "forage test not found")
    return success(forage_test_out(test), "object", 200)


@bp.post("/api/forage-tests/<test_id>/submit")
def submit_forage_test(test_id):
    authorize(["LabTechnician"])
    body = get_body()
    lab_reference = as_str(req(body, "lab_reference"), "lab_reference")
    test = store["forage_tests"].get(test_id)
    if test is None:
        raise ApiError(ERR_TEST_NOT_FOUND, 404, "forage test not found")
    # Submit is allowed from COLLECTED or RESULTED (the retest loop).
    if test["status"] not in ("COLLECTED", "RESULTED"):
        raise ApiError(ERR_TEST_WRONG_STATE, 409, "test must be COLLECTED or RESULTED to submit")
    lot = store["bale_lots"].get(test["bale_lot_id"])
    if lot is not None and lot["status"] == "CONDEMNED":
        raise ApiError(ERR_LOT_NOT_ACTIVE, 409, "the referenced lot is CONDEMNED")
    if test["status"] == "RESULTED":
        # Resubmission clears the prior result fields.
        test["rfv"] = None
        test["protein_pct"] = None
        test["moisture_pct"] = None
        test["resulted_by_user_id"] = None
    test["lab_reference"] = lab_reference
    test["status"] = "SUBMITTED"
    touch(test)
    return success(forage_test_out(test), "object", 200)


@bp.post("/api/forage-tests/<test_id>/record-result")
def record_result(test_id):
    uid, _ = authorize(["LabTechnician"])
    body = get_body()
    rfv = as_number(req(body, "rfv"), "rfv")
    protein_pct = as_number(req(body, "protein_pct"), "protein_pct")
    moisture_pct = as_number(req(body, "moisture_pct"), "moisture_pct")
    test = store["forage_tests"].get(test_id)
    if test is None:
        raise ApiError(ERR_TEST_NOT_FOUND, 404, "forage test not found")
    if test["status"] != "SUBMITTED":
        raise ApiError(ERR_TEST_WRONG_STATE, 409, "test must be SUBMITTED to record a result")
    test["rfv"] = rfv
    test["protein_pct"] = protein_pct
    test["moisture_pct"] = moisture_pct
    test["resulted_by_user_id"] = uid
    test["status"] = "RESULTED"
    touch(test)
    return success(forage_test_out(test), "object", 200)


@bp.post("/api/forage-tests/<test_id>/certify")
def certify_forage_test(test_id):
    uid, _ = authorize(["LabTechnician"])
    test = store["forage_tests"].get(test_id)
    if test is None:
        raise ApiError(ERR_TEST_NOT_FOUND, 404, "forage test not found")
    if test["status"] != "RESULTED":
        raise ApiError(ERR_TEST_WRONG_STATE, 409, "test must be RESULTED to certify")
    lot = store["bale_lots"].get(test["bale_lot_id"])
    if lot is None or lot["status"] != "ACTIVE":
        raise ApiError(ERR_LOT_NOT_ACTIVE, 409, "the referenced lot must be ACTIVE to certify")
    # Segregation of duties: certifier != technician who recorded the result.
    if uid == test["resulted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "the certifying technician must differ from the one who recorded the result")
    test["certified_by_user_id"] = uid
    test["status"] = "CERTIFIED"
    touch(test)
    # Last certify wins: write the lot's tier and certified protein.
    lot["quality_tier"] = quality_tier_assignment(test["rfv"], test["protein_pct"], test["moisture_pct"])
    lot["certified_protein_pct"] = test["protein_pct"]
    touch(lot)
    return success(forage_test_out(test), "object", 200)


@bp.post("/api/forage-tests/<test_id>/invalidate")
def invalidate_forage_test(test_id):
    authorize(["LabTechnician", "BrokerOps"])
    test = store["forage_tests"].get(test_id)
    if test is None:
        raise ApiError(ERR_TEST_NOT_FOUND, 404, "forage test not found")
    if test["status"] not in ("COLLECTED", "SUBMITTED"):
        raise ApiError(ERR_TEST_WRONG_STATE, 409, "only COLLECTED or SUBMITTED tests can be invalidated")
    test["status"] = "INVALIDATED"
    touch(test)
    return success(forage_test_out(test), "object", 200)
