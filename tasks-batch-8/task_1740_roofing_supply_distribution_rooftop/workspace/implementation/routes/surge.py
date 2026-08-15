"""Storm surge events and the allocation waterfall (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_BRANCH_NOT_FOUND,
    ERR_SURGE_NOT_FOUND,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_SURGE_NOT_ACTIVE,
    ERR_SURGE_NOT_OPEN,
    ERR_ALLOCATION_NOT_PENDING,
    ERR_ALLOCATION_NOT_REVOCABLE,
    ERR_STALE_VERSION,
    ERR_INVALID_REQUEST,
)
from middleware import authorized, check_contractor_owns
from routes.helpers import body, body_field, render_list, render_one, require_int
from services.core import create_record, get_or_404, mutate, remaining_pool
from services.calculations import tier_cap_bundles, contractor_granted_total
from services.sweep import close_surge_event
from util import parse_dt

bp = Blueprint("surge", __name__)

SURGE_READ_ROLES = ["PlatformAdmin", "BranchManager", "SalesRep", "Contractor"]
ALLOC_READ_ROLES = ["PlatformAdmin", "BranchManager", "Contractor"]


def _version_matches(expected, current):
    """OCC comparison tolerant of JSON string-vs-int transport of the version."""
    try:
        return int(expected) == int(current)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Storm surge events
# ---------------------------------------------------------------------------

@bp.post("/roofing/branches/<bid>/surge-events")
def declare_surge_event(bid):
    authorized(["BranchManager", "PlatformAdmin"])
    branch = get_or_404("branches", bid, ERR_BRANCH_NOT_FOUND)
    data = body()
    starts_at = body_field(data, "starts_at", required=True)
    ends_at = body_field(data, "ends_at", required=True)
    try:
        if parse_dt(ends_at) <= parse_dt(starts_at):
            raise_error(ERR_INVALID_REQUEST, "ends_at must be strictly later than starts_at")
    except (ValueError, AttributeError):
        raise_error(ERR_INVALID_REQUEST, "starts_at and ends_at must be ISO 8601 datetimes")
    rec = create_record("surge_events", {
        "branch_id": branch["id"],
        "event_name": body_field(data, "event_name", required=True),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "surge_multiplier_pct": require_int(body_field(data, "surge_multiplier_pct", required=True),
                                            "surge_multiplier_pct", minimum=0),
        "allocation_pool_bundles": require_int(body_field(data, "allocation_pool_bundles", required=True),
                                               "allocation_pool_bundles", minimum=0),
        "allocated_bundles": 0,
        "status": "DECLARED",
    })
    return render_one("surge_events", rec, status=201)


@bp.get("/roofing/branches/<bid>/surge-events")
def list_branch_surge_events(bid):
    caller = authorized(SURGE_READ_ROLES)
    branch = get_or_404("branches", bid, ERR_BRANCH_NOT_FOUND)
    events = [e for e in db["surge_events"].values() if e["branch_id"] == branch["id"]]
    return render_list(caller, "surge_events",
                       filters={"status": request.args.get("status")},
                       base_records=events)


@bp.get("/roofing/surge-events/<rid>")
def get_surge_event(rid):
    caller = authorized(SURGE_READ_ROLES)
    rec = get_or_404("surge_events", rid, ERR_SURGE_NOT_FOUND)
    return render_one("surge_events", rec)


@bp.post("/roofing/surge-events/<rid>/close")
def close_surge_event_endpoint(rid):
    authorized(["BranchManager"])
    rec = get_or_404("surge_events", rid, ERR_SURGE_NOT_FOUND)
    if rec["status"] not in ("DECLARED", "ACTIVE"):
        raise_error(ERR_SURGE_NOT_ACTIVE, "close requires the event to be DECLARED or ACTIVE")
    close_surge_event(rec)
    return render_one("surge_events", rec)


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

@bp.post("/roofing/surge-events/<rid>/allocations")
def request_allocation(rid):
    caller = authorized(["Contractor"])
    event = get_or_404("surge_events", rid, ERR_SURGE_NOT_FOUND)
    data = body()
    contractor_account_id = body_field(data, "contractor_account_id", required=True)
    account = db["contractor_accounts"].get(contractor_account_id)
    if account is None:
        raise_error(ERR_ACCOUNT_NOT_FOUND, f"contractor account {contractor_account_id} does not exist")
    check_contractor_owns(caller, account["id"])
    product_id = body_field(data, "product_id", required=True)
    if db["products"].get(product_id) is None:
        raise_error(ERR_PRODUCT_NOT_FOUND, f"product {product_id} does not exist")
    requested = require_int(body_field(data, "requested_bundles", required=True),
                            "requested_bundles", minimum=1)
    rec = create_record("allocations", {
        "storm_surge_event_id": event["id"],
        "contractor_account_id": account["id"],
        "product_id": product_id,
        "requested_bundles": requested,
        "granted_bundles": 0,
        "consumed_bundles": 0,
        "expires_at": event["ends_at"],
        "status": "PENDING",
    })
    return render_one("allocations", rec, status=201)


@bp.get("/roofing/surge-events/<rid>/allocations")
def list_event_allocations(rid):
    caller = authorized(ALLOC_READ_ROLES)
    event = get_or_404("surge_events", rid, ERR_SURGE_NOT_FOUND)
    allocs = [a for a in db["allocations"].values() if a["storm_surge_event_id"] == event["id"]]
    return render_list(caller, "allocations",
                       filters={"contractor_account_id": request.args.get("contractor_account_id")},
                       base_records=allocs)


@bp.get("/roofing/allocations")
def list_allocations():
    caller = authorized(ALLOC_READ_ROLES)
    return render_list(caller, "allocations",
                       filters={"contractor_account_id": request.args.get("contractor_account_id"),
                                "product_id": request.args.get("product_id"),
                                "storm_surge_event_id": request.args.get("storm_surge_event_id"),
                                "status": request.args.get("status")})


@bp.get("/roofing/allocations/<rid>")
def get_allocation(rid):
    caller = authorized(ALLOC_READ_ROLES)
    rec = get_or_404("allocations", rid, ERR_ALLOCATION_NOT_FOUND)
    check_contractor_owns(caller, rec["contractor_account_id"])
    return render_one("allocations", rec)


@bp.post("/roofing/allocations/<rid>/grant")
def grant_allocation(rid):
    caller = authorized(["BranchManager"])
    rec = get_or_404("allocations", rid, ERR_ALLOCATION_NOT_FOUND)
    event = db["surge_events"].get(rec["storm_surge_event_id"])

    # Optimistic concurrency on the parent event version (PRD 2.10): a stale
    # pool view is rejected before the grant is computed.
    data = body()
    expected = data.get("expected_storm_surge_event_version")
    if expected is not None and event is not None and not _version_matches(expected, event["version"]):
        raise_error(ERR_STALE_VERSION,
                    "expected_storm_surge_event_version does not match the event version")

    if rec["status"] != "PENDING":
        raise_error(ERR_ALLOCATION_NOT_PENDING, "grant requires the allocation to be PENDING")
    if event is None or event["status"] not in ("DECLARED", "ACTIVE"):
        raise_error(ERR_SURGE_NOT_OPEN, "grant requires the event to be DECLARED or ACTIVE")

    # Waterfall turn for this allocation: tier cap binds before the pool check.
    account = db["contractor_accounts"].get(rec["contractor_account_id"])
    tier = account["pricing_tier"] if account else "STANDARD"
    cap = tier_cap_bundles(tier, event["allocation_pool_bundles"])
    cap_remaining = max(0, cap - contractor_granted_total(event["id"], rec["contractor_account_id"]))
    granted = min(rec["requested_bundles"], cap_remaining, remaining_pool(event))
    if granted < 0:
        granted = 0
    rec["granted_bundles"] = granted
    rec["status"] = "GRANTED"
    mutate(rec)
    event["allocated_bundles"] += granted
    mutate(event)  # +1 version: stale grant writers trip over this
    return render_one("allocations", rec)


@bp.post("/roofing/allocations/<rid>/revoke")
def revoke_allocation(rid):
    authorized(["BranchManager"])
    rec = get_or_404("allocations", rid, ERR_ALLOCATION_NOT_FOUND)
    if rec["status"] not in ("GRANTED", "PARTIALLY_CONSUMED"):
        raise_error(ERR_ALLOCATION_NOT_REVOCABLE,
                    "revoke requires the allocation to be GRANTED or PARTIALLY_CONSUMED")
    event = db["surge_events"].get(rec["storm_surge_event_id"])
    released = rec["granted_bundles"] - rec["consumed_bundles"]
    if event is not None and released:
        event["allocated_bundles"] -= released
        mutate(event)
    rec["status"] = "REVOKED"
    mutate(rec)
    return render_one("allocations", rec)
