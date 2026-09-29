"""SponsorAllocation endpoints: reservation and the fulfillment obligation."""

from flask import Blueprint

import calc
import derive
import enums
import serial
import store
import validate
from auth import CHARITY_TREASURER, SPONSORSHIP_MANAGER, TOURNAMENT_DIRECTOR, auth
from envelope import created, ok, paginate
from errors import fail
from lookup import allocation as get_allocation
from lookup import asset as get_asset
from lookup import registration as get_registration
from store import touch

bp = Blueprint("allocations", __name__)

READ_ROLES = (SPONSORSHIP_MANAGER, TOURNAMENT_DIRECTOR, CHARITY_TREASURER)

CREATE_FIELDS = ("registration_id", "sponsorship_asset_id", "source",
                 "service_window_start", "service_window_end")


@bp.post("/outing-ops/sponsor-allocations")
def create_allocation():
    auth((SPONSORSHIP_MANAGER,))
    body = validate.body()
    validate.only_fields(body, CREATE_FIELDS)
    registration_id = validate.req_ref(body, "registration_id")
    asset_id = validate.req_ref(body, "sponsorship_asset_id")
    source = validate.req_enum(body, "source", enums.ALLOCATION_SOURCE)
    window_start = validate.opt_ts(body, "service_window_start")
    window_end = validate.opt_ts(body, "service_window_end")
    reg = get_registration(registration_id)
    asset = get_asset(asset_id)
    windowed = asset["asset_type"] in enums.WINDOWED_ASSET_TYPES
    if windowed and (window_start is None or window_end is None):
        fail("ERR_INVALID_REQUEST",
             "A %s unit requires a service window." % asset["asset_type"])
    if not windowed:
        window_start = None
        window_end = None
    if reg["outing_id"] != asset["outing_id"]:
        fail("ERR_CROSS_OUTING_REFERENCE",
             "The registration and the unit belong to different outings.")
    outing = store.outings.get(reg["outing_id"])
    if outing is None or outing["play_status"] != "OPEN":
        fail("ERR_REGISTRATION_CLOSED", "The outing's field is not open.")

    tier = derive.tier_of(reg)
    if source == "PACKAGE_ENTITLEMENT":
        entitled = tier["entitled_asset_type"] if tier is not None else "NONE"
        if asset["asset_type"] != entitled:
            fail("ERR_ASSET_TYPE_MISMATCH",
                 "The tier entitles %s units, not %s."
                 % (entitled, asset["asset_type"]))
        if reg["entitled_asset_balance"] < 1:
            fail("ERR_ALLOCATION_NOT_ENTITLED",
                 "The registration has no entitlement balance left.")
    elif asset["list_price_cents"] <= 0:
        fail("ERR_ALLOCATION_NOT_ENTITLED",
             "An upsell requires a positive list price.")

    _check_service_window(asset, window_start, window_end)

    if asset["status"] == "WITHDRAWN":
        fail("ERR_ASSET_WITHDRAWN", "The unit has been withdrawn.")
    if asset["remaining_capacity"] < 1:
        fail("ERR_ASSET_CAPACITY_EXCEEDED", "The unit has no capacity left.")
    if asset["exclusive"]:
        for other in derive.allocs_of_asset(asset["id"]):
            if other["status"] != "RELEASED":
                fail("ERR_EXCLUSIVE_ASSET_CONFLICT",
                     "The unit is exclusive and already occupied.")

    row = store.new_row("SponsorAllocation", {
        "registration_id": registration_id,
        "sponsorship_asset_id": asset_id,
        "source": source,
        "service_window_start": window_start,
        "service_window_end": window_end,
        "status": "RESERVED",
        "upsell_price_cents": (asset["list_price_cents"] if source == "UPSELL" else 0),
        "fulfillment_credit_cents": 0,
        "waived_reason": None,
        "artwork_approved_by_user_id": None,
        "verified_by_user_id": None,
        "committed_at": None,
    })
    derive.rederive_asset(asset)
    derive.rederive_entitled_balance(reg)
    derive.rederive_outing_counters(outing)
    return created(serial.dump(row))


def _check_service_window(asset, window_start, window_end):
    """Closed intervals padded by thirty minutes on both sides (PRD 3.4)."""
    if window_start is None or window_end is None:
        return
    pad = store.minutes(calc.CHANGEOVER_BUFFER_MINUTES)
    start = store.parse_ts(window_start) - pad
    end = store.parse_ts(window_end) + pad
    for other in derive.allocs_of_asset(asset["id"]):
        if other["status"] == "RELEASED":
            continue
        if other["service_window_start"] is None or other["service_window_end"] is None:
            continue
        o_start = store.parse_ts(other["service_window_start"]) - pad
        o_end = store.parse_ts(other["service_window_end"]) + pad
        if start <= o_end and o_start <= end:
            fail("ERR_SERVICE_WINDOW_CONFLICT",
                 "The padded service windows intersect.")


@bp.get("/outing-ops/sponsor-allocations/<row_id>")
def read_allocation(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_allocation(row_id)))


@bp.get("/outing-ops/sponsor-allocations")
def list_allocations():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    registration_id = validate.q_str("registration_id")
    asset_id = validate.q_str("sponsorship_asset_id")
    status = validate.q_enum("status", enums.ALLOCATION_STATUS)
    source = validate.q_enum("source", enums.ALLOCATION_SOURCE)
    rows = store.sorted_rows(store.sponsor_allocations.values())
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    if asset_id is not None:
        rows = [r for r in rows if r["sponsorship_asset_id"] == asset_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    return paginate(rows, limit, offset, serial.dump)


WAIVABLE_STATES = ("COMMITTED", "ARTWORK_APPROVED", "INSTALLED")


@bp.post("/outing-ops/sponsor-allocations/<row_id>/fulfillment")
def fulfillment(row_id):
    user_id, _role = auth((SPONSORSHIP_MANAGER,))
    body = validate.body()
    validate.only_fields(body, ("action", "waived_reason"))
    action = validate.req_enum(body, "action", enums.ALLOCATION_ACTIONS)
    if action == "WAIVE":
        waived_reason = validate.req_str(body, "waived_reason")
    else:
        waived_reason = validate.opt_str(body, "waived_reason")
    alloc = get_allocation(row_id)
    asset = store.sponsorship_assets.get(alloc["sponsorship_asset_id"])
    reg = store.registrations.get(alloc["registration_id"])
    outing = store.outings.get(reg["outing_id"]) if reg is not None else None
    status = alloc["status"]

    if action == "COMMIT":
        if status != "RESERVED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "COMMIT is not an edge out of %s." % status)
        if not derive.is_revenue(reg):
            fail("ERR_REGISTRATION_NOT_REVENUE_RECOGNIZED",
                 "The sponsor registration is not revenue recognized.")
        alloc["status"] = "COMMITTED"
        alloc["committed_at"] = store.now_iso()
    elif action == "APPROVE_ARTWORK":
        if status != "COMMITTED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "APPROVE_ARTWORK is not an edge out of %s." % status)
        _require_window_open(asset)
        alloc["status"] = "ARTWORK_APPROVED"
        alloc["artwork_approved_by_user_id"] = user_id
    elif action == "INSTALL":
        if status != "ARTWORK_APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "INSTALL is not an edge out of %s." % status)
        alloc["status"] = "INSTALLED"
    elif action == "VERIFY":
        if status != "INSTALLED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "VERIFY is not an edge out of %s." % status)
        if user_id == alloc["artwork_approved_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The verifier may not be the artwork approver.")
        _require_window_open(asset)
        alloc["status"] = "VERIFIED"
        alloc["verified_by_user_id"] = user_id
    elif action == "WAIVE":
        if status not in WAIVABLE_STATES:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "WAIVE is not an edge out of %s." % status)
        alloc["status"] = "WAIVED"
        alloc["waived_reason"] = waived_reason
        price = asset["list_price_cents"] if asset is not None else 0
        alloc["fulfillment_credit_cents"] = calc.pct_of(calc.WAIVER_CREDIT_PCT, price)
    else:
        if status not in derive.NON_TERMINAL_ALLOCATION_STATES:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "RELEASE is not an edge out of %s." % status)
        alloc["status"] = "RELEASED"

    touch(alloc)
    if asset is not None:
        derive.rederive_asset(asset)
    if reg is not None:
        derive.rederive_entitled_balance(reg)
        derive.rederive_registration_fulfillment_credit(reg)
    if outing is not None:
        derive.rederive_outing_counters(outing)
        if action in ("COMMIT", "WAIVE", "RELEASE"):
            derive.run_rollup(outing)
    return ok(serial.dump(alloc))


def _require_window_open(asset):
    if asset is None or asset["fulfillment_due_at"] is None:
        return
    if store.now_dt() > store.parse_ts(asset["fulfillment_due_at"]):
        fail("ERR_FULFILLMENT_WINDOW_ELAPSED",
             "The unit's fulfillment deadline has passed.")
