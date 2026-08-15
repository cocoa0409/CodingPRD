"""Vendor routes (PRD §3.5)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    check_string,
    check_int,
    check_list,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from services.transitions import guard_transition

bp = Blueprint("vendors", __name__)

CAPABILITIES = ("CONFORM", "COLOR", "SOUND", "QC", "ARCHIVE")
VENDOR_TERMINAL = ("OFFBOARDED",)
LIST_ROLES = ("FacilityAdmin", "PostSupervisor", "VendorRep")


def serialize(vendor):
    return dict(vendor)


def get_vendor_or_404(vendor_id):
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise ApiError(ERR_NOT_FOUND, f"Vendor {vendor_id} does not exist", 404)
    return vendor


def vendor_in_flight_count(vendor_id):
    """Steady load: turnovers with this vendor in ISSUED or ACKED."""
    return sum(
        1
        for to in db.turnovers.values()
        if to.get("vendor_id") == vendor_id and to["status"] in ("ISSUED", "ACKED")
    )


@bp.route("/post-production/vendors", methods=["POST"])
def create_vendor():
    require_roles(("FacilityAdmin",))
    body = get_json_body()
    require_fields(
        body, ("vendor_name", "capabilities", "day_rate_cents", "capacity_slots")
    )
    vendor_name = check_string(body, "vendor_name")
    capabilities = check_list(body, "capabilities", min_len=1, max_len=5)
    for entry in capabilities:
        if not isinstance(entry, str) or entry not in CAPABILITIES:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Field 'capabilities' entries must be drawn from CONFORM, "
                "COLOR, SOUND, QC, ARCHIVE",
                400,
            )
    if len(set(capabilities)) != len(capabilities):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'capabilities' entries must be unique",
            400,
        )
    day_rate_cents = check_int(body, "day_rate_cents", min_v=0)
    capacity_slots = check_int(body, "capacity_slots", min_v=1, max_v=20)
    for existing in db.vendors.values():
        if existing["vendor_name"] == vendor_name:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"vendor_name '{vendor_name}' already exists",
                400,
            )
    vendor = new_entity(
        {
            "vendor_name": vendor_name,
            "capabilities": list(capabilities),
            "day_rate_cents": day_rate_cents,
            "capacity_slots": capacity_slots,
            "status": "ONBOARDED",
        }
    )
    db.vendors[vendor["id"]] = vendor
    return success_object(serialize(vendor), 201)


@bp.route("/post-production/vendors", methods=["GET"])
def list_vendors():
    require_roles(LIST_ROLES)
    limit, offset = get_pagination()
    items = list(db.vendors.values())
    status = get_filter("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(v) for v in window], limit, offset, total)


@bp.route("/post-production/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    require_roles(LIST_ROLES)
    vendor = get_vendor_or_404(vendor_id)
    return success_object(serialize(vendor))


@bp.route("/post-production/vendors/<vendor_id>/suspend", methods=["POST"])
def suspend_vendor(vendor_id):
    require_roles(("FacilityAdmin",))
    vendor = get_vendor_or_404(vendor_id)
    guard_transition(vendor, "ONBOARDED", VENDOR_TERMINAL, "vendor")
    vendor["status"] = "SUSPENDED"
    touch(vendor)
    # Side effect: all VendorBids by this vendor in SUBMITTED -> EXPIRED.
    for bid in db.vendor_bids.values():
        if bid["vendor_id"] == vendor_id and bid["status"] == "SUBMITTED":
            bid["status"] = "EXPIRED"
            touch(bid)
    return success_object(serialize(vendor))


@bp.route("/post-production/vendors/<vendor_id>/reinstate", methods=["POST"])
def reinstate_vendor(vendor_id):
    require_roles(("FacilityAdmin",))
    vendor = get_vendor_or_404(vendor_id)
    guard_transition(vendor, "SUSPENDED", VENDOR_TERMINAL, "vendor")
    vendor["status"] = "ONBOARDED"
    touch(vendor)
    return success_object(serialize(vendor))


@bp.route("/post-production/vendors/<vendor_id>/offboard", methods=["POST"])
def offboard_vendor(vendor_id):
    require_roles(("FacilityAdmin",))
    vendor = get_vendor_or_404(vendor_id)
    guard_transition(vendor, "SUSPENDED", VENDOR_TERMINAL, "vendor")
    # No TurnoverPackage references this vendor in {ISSUED, ACKED, RETURNED}.
    for to in db.turnovers.values():
        if to.get("vendor_id") == vendor_id and to["status"] in (
            "ISSUED",
            "ACKED",
            "RETURNED",
        ):
            raise ApiError(
                ERR_INVALID_STATE,
                "A TurnoverPackage references this vendor in ISSUED, ACKED, "
                "or RETURNED; offboard refused",
                409,
            )
    vendor["status"] = "OFFBOARDED"
    touch(vendor)
    return success_object(serialize(vendor))


# ---------------------------------------------------------------------------
# Computed read + reverse reachability
# ---------------------------------------------------------------------------


@bp.route("/post-production/vendors/<vendor_id>/load", methods=["GET"])
def vendor_load(vendor_id):
    require_roles(LIST_ROLES)
    vendor = get_vendor_or_404(vendor_id)
    load = vendor_in_flight_count(vendor_id)
    utilization_pct = (100 * load) // vendor["capacity_slots"]
    return success_object(
        {
            "vendor_id": vendor["id"],
            "in_flight_count": load,
            "capacity_slots": vendor["capacity_slots"],
            "utilization_pct": utilization_pct,
        }
    )


@bp.route("/post-production/vendors/<vendor_id>/turnovers", methods=["GET"])
def list_vendor_turnovers(vendor_id):
    require_roles(LIST_ROLES)
    get_vendor_or_404(vendor_id)
    from routes.turnovers import serialize as serialize_turnover

    limit, offset = get_pagination()
    items = [t for t in db.turnovers.values() if t.get("vendor_id") == vendor_id]
    status = get_filter("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_turnover(t) for t in window], limit, offset, total)


@bp.route("/post-production/vendors/<vendor_id>/bids", methods=["GET"])
def list_vendor_bids(vendor_id):
    require_roles(LIST_ROLES)
    get_vendor_or_404(vendor_id)
    from routes.vendor_bids import serialize as serialize_bid

    limit, offset = get_pagination()
    items = [b for b in db.vendor_bids.values() if b.get("vendor_id") == vendor_id]
    status = get_filter("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize_bid(b) for b in window], limit, offset, total)
