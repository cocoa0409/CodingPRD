from flask import Blueprint, request

from db import db
from clock import clock, parse_iso
from db import iso_ms
from middleware import require_role
from response import object_response, array_response
from errors import (
    err, ERR_INVALID_STATE, ERR_STALE_RACK_VERSION, ERR_COI_NOT_VERIFIED,
    ERR_VESSEL_DIMENSIONS_EXCEED_RACK, ERR_RACK_NOT_AVAILABLE,
    ERR_RACK_OCCUPANCY_CONFLICT, ERR_VESSEL_ALREADY_STORED, ERR_INVALID_REQUEST,
)
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_string,
    require_nonneg_int, parse_pagination, paginate,
)
from services.lookups import get_vessel, get_rack, get_agreement
from services.serialize import agreement_view
from services.calculations import compute_monthly_storage

agreements_bp = Blueprint("agreements", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}


def vessel_fits_rack(vessel, rack):
    return (vessel["loa_ft"] <= rack["max_loa_ft"]
            and vessel["beam_ft"] <= rack["max_beam_ft"]
            and vessel["dry_weight_lbs"] <= rack["max_weight_lbs"])


def vessel_has_active_or_winterized(vessel_id, exclude_id=None):
    for a in db.agreements.values():
        if a["id"] == exclude_id:
            continue
        if a["vessel_id"] == vessel_id and a["status"] in ("ACTIVE", "WINTERIZED"):
            return True
    return False


def rack_occupancy_conflict(rack_id, new_activated_at_dt, exclude_id=None):
    """Half-open occupancy intervals [activated_at, terminated_at) on the same
    rack must not overlap; adjacency allowed. A still-open agreement has
    terminated_at == None (open-ended interval to +inf)."""
    for a in db.agreements.values():
        if a["id"] == exclude_id:
            continue
        if a["rack_id"] != rack_id:
            continue
        if a["activated_at"] is None:
            continue
        if a["status"] not in ("ACTIVE", "WINTERIZED", "TERMINATED"):
            continue
        existing_start = parse_iso(a["activated_at"])
        existing_end = parse_iso(a["terminated_at"]) if a["terminated_at"] else None
        # New interval is [new_start, +inf). Overlap with [existing_start, existing_end).
        new_start = new_activated_at_dt
        # No overlap if existing ended at or before new_start (adjacency allowed).
        if existing_end is not None and existing_end <= new_start:
            continue
        # No overlap if existing starts at or after new interval's end; but new
        # interval is open-ended so any not-already-ended existing interval overlaps.
        return True
    return False


@agreements_bp.route("/marina/storage-agreements", methods=["POST"])
def create_agreement():
    require_role({"DockMaster"})
    body = get_json_body()
    require_fields(body, ["vessel_id", "rack_id"])
    require_string(body["vessel_id"], "vessel_id")
    require_string(body["rack_id"], "rack_id")
    with db.lock:
        vessel = get_vessel(body["vessel_id"])
        rack = get_rack(body["rack_id"])
        # Creation-time dimensional fit check (priority 10).
        if not vessel_fits_rack(vessel, rack):
            raise err(ERR_VESSEL_DIMENSIONS_EXCEED_RACK, "Vessel does not fit the rack.")
        rec = {
            "vessel_id": body["vessel_id"],
            "rack_id": body["rack_id"],
            "tier_size_class": None,
            "monthly_base_cents": 0,
            "oversize_surcharge_applied": False,
            "activated_at": None,
            "terminated_at": None,
            "status": "PENDING_COI",
        }
        stamp_create(rec)
        db.agreements[rec["id"]] = rec
    return object_response(agreement_view(rec), 201)


@agreements_bp.route("/marina/storage-agreements/<agreement_id>", methods=["GET"])
def fetch_agreement(agreement_id):
    require_role(READ_ROLES)
    rec = get_agreement(agreement_id)
    return object_response(agreement_view(rec), 200)


@agreements_bp.route("/marina/storage-agreements", methods=["GET"])
def list_agreements():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.agreements.values())
    vessel_id = request.args.get("vessel_id")
    rack_id = request.args.get("rack_id")
    status = request.args.get("status")
    if vessel_id is not None:
        records = [r for r in records if r["vessel_id"] == vessel_id]
    if rack_id is not None:
        records = [r for r in records if r["rack_id"] == rack_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([agreement_view(r) for r in page], limit, offset, total)


@agreements_bp.route("/marina/storage-agreements/<agreement_id>/activate", methods=["POST"])
def activate_agreement(agreement_id):
    require_role({"DockMaster"})
    body = get_json_body()
    require_fields(body, ["expected_rack_version"])
    require_nonneg_int(body["expected_rack_version"], "expected_rack_version")
    with db.lock:
        agreement = get_agreement(agreement_id)
        vessel = db.vessels[agreement["vessel_id"]]
        rack = db.racks[agreement["rack_id"]]
        # Priority 6: state.
        if agreement["status"] != "PENDING_COI":
            raise err(ERR_INVALID_STATE, "Agreement must be PENDING_COI to activate.")
        # Priority 7: OCC on rack version.
        if body["expected_rack_version"] != rack["version"]:
            raise err(ERR_STALE_RACK_VERSION, "expected_rack_version does not match rack version.")
        # Priority 8: COI gate.
        if vessel.get("active_policy_id") is None:
            raise err(ERR_COI_NOT_VERIFIED, "Vessel has no verified in-window insurance.")
        # Priority 10: dimensional fit.
        if not vessel_fits_rack(vessel, rack):
            raise err(ERR_VESSEL_DIMENSIONS_EXCEED_RACK, "Vessel does not fit the rack.")
        # Priority 11: rack availability.
        if rack["status"] != "AVAILABLE":
            raise err(ERR_RACK_NOT_AVAILABLE, "Rack is not AVAILABLE.")
        # Priority 13: rack occupancy interval overlap.
        now = clock.now()
        if rack_occupancy_conflict(rack["id"], now, exclude_id=agreement["id"]):
            raise err(ERR_RACK_OCCUPANCY_CONFLICT, "Rack occupancy interval overlaps.")
        # Priority 17: single-storage exclusivity.
        if vessel_has_active_or_winterized(vessel["id"], exclude_id=agreement["id"]):
            raise err(ERR_VESSEL_ALREADY_STORED, "Vessel already has an ACTIVE/WINTERIZED agreement.")

        # Side effects.
        monthly_base, oversize = compute_monthly_storage(
            rack["size_class"], vessel["loa_ft"], rack["max_loa_ft"])
        agreement["tier_size_class"] = rack["size_class"]
        agreement["monthly_base_cents"] = monthly_base
        agreement["oversize_surcharge_applied"] = oversize
        agreement["activated_at"] = iso_ms(now)
        agreement["status"] = "ACTIVE"
        touch(agreement)
        # Cascade hop 1: rack OCCUPIED + version bump.
        rack["status"] = "OCCUPIED"
        rack["current_agreement_id"] = agreement["id"]
        touch(rack)
        # Cascade hop 2: vessel RACKED + ACTIVE_STORAGE.
        vessel["location_status"] = "RACKED"
        vessel["billing_status"] = "ACTIVE_STORAGE"
        touch(vessel)
    return object_response(agreement_view(agreement), 200)


@agreements_bp.route("/marina/storage-agreements/<agreement_id>/winterize", methods=["POST"])
def winterize_agreement(agreement_id):
    require_role({"DockMaster"})
    with db.lock:
        agreement = get_agreement(agreement_id)
        vessel = db.vessels[agreement["vessel_id"]]
        if agreement["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Agreement must be ACTIVE to winterize.")
        if vessel["location_status"] != "RACKED":
            raise err(ERR_INVALID_STATE, "Vessel must be RACKED to winterize.")
        agreement["status"] = "WINTERIZED"
        touch(agreement)
        vessel["billing_status"] = "WINTER_HOLD"
        touch(vessel)
    return object_response(agreement_view(agreement), 200)


@agreements_bp.route("/marina/storage-agreements/<agreement_id>/reactivate", methods=["POST"])
def reactivate_agreement(agreement_id):
    require_role({"DockMaster"})
    with db.lock:
        agreement = get_agreement(agreement_id)
        vessel = db.vessels[agreement["vessel_id"]]
        if agreement["status"] != "WINTERIZED":
            raise err(ERR_INVALID_STATE, "Agreement must be WINTERIZED to reactivate.")
        # COI gate (priority 8).
        if vessel.get("active_policy_id") is None:
            raise err(ERR_COI_NOT_VERIFIED, "Vessel has no verified in-window insurance.")
        agreement["status"] = "ACTIVE"
        touch(agreement)
        vessel["billing_status"] = "ACTIVE_STORAGE"
        touch(vessel)
    return object_response(agreement_view(agreement), 200)


@agreements_bp.route("/marina/storage-agreements/<agreement_id>/terminate", methods=["POST"])
def terminate_agreement(agreement_id):
    require_role({"DockMaster"})
    with db.lock:
        agreement = get_agreement(agreement_id)
        vessel = db.vessels[agreement["vessel_id"]]
        rack = db.racks[agreement["rack_id"]]
        status = agreement["status"]
        if status == "ACTIVE":
            if vessel["location_status"] == "IN_WATER":
                raise err(ERR_INVALID_STATE, "Cannot terminate while vessel is IN_WATER.")
        elif status == "WINTERIZED":
            pass
        else:
            raise err(ERR_INVALID_STATE, "Agreement must be ACTIVE or WINTERIZED to terminate.")
        agreement["status"] = "TERMINATED"
        agreement["terminated_at"] = iso_ms(clock.now())
        touch(agreement)
        # Compensation: free the rack.
        rack["status"] = "AVAILABLE"
        rack["current_agreement_id"] = None
        touch(rack)
        vessel["location_status"] = "OFF_SITE"
        vessel["billing_status"] = "CLOSED"
        touch(vessel)
    return object_response(agreement_view(agreement), 200)
