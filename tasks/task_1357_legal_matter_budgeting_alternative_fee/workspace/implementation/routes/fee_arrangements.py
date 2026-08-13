"""FeeArrangement endpoints (PRD §3.2)."""
from flask import Blueprint

import db
import util
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MATTER_NOT_OPEN,
    ERR_STALE_VERSION,
    ERR_ARRANGEMENT_FIELDS_INCOMPLETE,
    ERR_ARRANGEMENT_ALREADY_ACTIVE,
)
from middleware import get_context, require_roles
from response import success_object, success_list
from services import derived

bp = Blueprint("fee_arrangements", __name__)

ARRANGEMENT_TYPES = {"FLAT_FEE", "CAPPED_FEE", "SUCCESS_FEE", "COLLAR"}
READ_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner", "ManagingPartner")

REQUIRED_FIELDS = {
    "FLAT_FEE": ["flat_fee_cents"],
    "CAPPED_FEE": ["capped_fee_cents"],
    "SUCCESS_FEE": ["success_fee_uplift_pct_bp"],
    "COLLAR": ["collar_lower_bound_cents", "collar_upper_bound_cents", "collar_share_pct_bp"],
}
ALL_TYPE_FIELDS = [
    "flat_fee_cents", "capped_fee_cents", "success_fee_uplift_pct_bp",
    "collar_lower_bound_cents", "collar_upper_bound_cents", "collar_share_pct_bp",
]


def _type_fields_complete(arr):
    for f in REQUIRED_FIELDS.get(arr.get("arrangement_type"), []):
        if arr.get(f) is None:
            return False
    return True


def _other_active_or_pending(arr):
    """Any OTHER arrangement on the matter in ACTIVE or PENDING_APPROVAL.

    A draft submitted as a re-papering (supersedes_arrangement_id pointing at
    the currently ACTIVE arrangement) is exempt for that one referenced
    arrangement — the supersession hand-off happens at activation."""
    supersedes = arr.get("supersedes_arrangement_id")
    for other in derived.arrangements_of(arr["matter_id"]):
        if other["id"] == arr["id"]:
            continue
        if other.get("status") not in ("ACTIVE", "PENDING_APPROVAL"):
            continue
        if supersedes and other["id"] == supersedes and other.get("status") == "ACTIVE":
            continue
        return True
    return False


@bp.post("/firms/<firmId>/matters/<matterId>/fee_arrangements")
def create_arrangement(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst")
    matter = util.get_matter_scoped(firmId, matterId)
    data = util.body()
    util.require_fields(data, ["arrangement_type", "fiscal_year_index"])
    arr_type = util.check_enum(data, "arrangement_type", ARRANGEMENT_TYPES)
    fiscal_year_index = util.check_int(data, "fiscal_year_index")

    fields = {}
    for f in ALL_TYPE_FIELDS:
        val = data.get(f)
        if val is not None:
            val = util.check_int(data, f)
        fields[f] = val

    supersedes_id = data.get("supersedes_arrangement_id")
    if supersedes_id is not None:
        target = db.fee_arrangements.get(supersedes_id)
        if target is None or target.get("firm_id") != firmId:
            from errors import err_not_found
            raise err_not_found(f"FeeArrangement {supersedes_id} not found")

    arr = util.new_resource()
    arr.update({
        "matter_id": matter["id"],
        "firm_id": firmId,
        "arrangement_type": arr_type,
        "flat_fee_cents": fields["flat_fee_cents"],
        "capped_fee_cents": fields["capped_fee_cents"],
        "success_fee_uplift_pct_bp": fields["success_fee_uplift_pct_bp"],
        "collar_lower_bound_cents": fields["collar_lower_bound_cents"],
        "collar_upper_bound_cents": fields["collar_upper_bound_cents"],
        "collar_share_pct_bp": fields["collar_share_pct_bp"],
        "fiscal_year_index": fiscal_year_index,
        "status": "DRAFT",
        "submitted_period_index": None,
        "activated_period_index": None,
        "supersedes_arrangement_id": supersedes_id,
    })
    db.fee_arrangements[arr["id"]] = arr
    return success_object(arr, 201)


@bp.get("/firms/fee_arrangements/<arrangementId>")
def get_arrangement(arrangementId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    arr = util.get_arrangement_flat(arrangementId)
    return success_object(arr, 200)


@bp.get("/firms/fee_arrangements")
def list_arrangements():
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    filters = util.query_filters([
        "firm_id", "matter_id", "supersedes_arrangement_id", "status", "arrangement_type",
    ])
    items = util.apply_filters(list(db.fee_arrangements.values()), filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/matters/<matterId>/fee_arrangements")
def list_arrangements_for_matter(matterId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    matter = util.get_matter_flat(matterId)
    filters = util.query_filters(["status"])
    items = [a for a in db.fee_arrangements.values() if a.get("matter_id") == matter["id"]]
    items = util.apply_filters(items, filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/fee_arrangements/<arrangementId>/submit")
def submit_arrangement(firmId, arrangementId):
    ctx = get_context()
    require_roles(ctx, "PricingAnalyst")
    firm = util.get_firm(firmId)
    arr = util.get_arrangement_scoped(firmId, arrangementId)
    if arr["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT arrangement can be submitted", 409)
    if not _type_fields_complete(arr):
        raise ApiError(ERR_ARRANGEMENT_FIELDS_INCOMPLETE,
                       "Arrangement-type-specific required field missing", 422)
    if _other_active_or_pending(arr):
        raise ApiError(ERR_ARRANGEMENT_ALREADY_ACTIVE,
                       "Matter already has ACTIVE or PENDING_APPROVAL arrangement", 409)
    arr["status"] = "PENDING_APPROVAL"
    arr["submitted_period_index"] = int(firm.get("current_period_index", 0))
    util.touch(arr)
    return success_object(arr, 200)


@bp.post("/firms/<firmId>/fee_arrangements/<arrangementId>/activate")
def activate_arrangement(firmId, arrangementId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    firm = util.get_firm(firmId)
    arr = util.get_arrangement_scoped(firmId, arrangementId)
    if arr["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a PENDING_APPROVAL arrangement can be activated", 409)
    matter = db.matters.get(arr["matter_id"])
    if matter is None:
        from errors import err_not_found
        raise err_not_found("Matter not found")

    # OCC on the parent matter (PRD §2.7) — checked before business gates.
    data = util.body()
    expected = data.get("expected_matter_version")
    if expected is not None:
        if not util.is_int(expected):
            from errors import err_invalid_request
            raise err_invalid_request("expected_matter_version must be an integer")
        if int(expected) != int(matter.get("version", 1)):
            raise ApiError(ERR_STALE_VERSION,
                           "OCC mismatch on expected_matter_version", 412)

    if matter["status"] not in ("OPEN", "ACTIVE", "REOPENED"):
        raise ApiError(ERR_MATTER_NOT_OPEN,
                       "Matter not in OPEN/ACTIVE/REOPENED for arrangement activation", 409)

    prior = None
    if arr.get("supersedes_arrangement_id"):
        prior = db.fee_arrangements.get(arr["supersedes_arrangement_id"])
        if prior is None or prior.get("status") != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE_TRANSITION,
                           "Superseded arrangement must currently be ACTIVE", 409)

    arr["status"] = "ACTIVE"
    arr["activated_period_index"] = int(firm.get("current_period_index", 0))
    util.touch(arr)

    if prior is not None:
        prior["status"] = "SUPERSEDED"
        util.touch(prior)

    matter["fee_arrangement_id"] = arr["id"]
    if matter["status"] == "OPEN":
        matter["status"] = "ACTIVE"
    util.touch(matter)
    return success_object(arr, 200)


@bp.post("/firms/<firmId>/fee_arrangements/<arrangementId>/reject")
def reject_arrangement(firmId, arrangementId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    arr = util.get_arrangement_scoped(firmId, arrangementId)
    if arr["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a PENDING_APPROVAL arrangement can be rejected", 409)
    arr["status"] = "REJECTED"
    util.touch(arr)
    return success_object(arr, 200)
