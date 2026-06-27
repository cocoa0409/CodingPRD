"""CashDrawer routes (PRD §3.3, §3.7, §2.10)."""
from flask import Blueprint, request

import errors
from auth import require_auth, BOTH, MANAGER_ONLY
from db import db, new_id, common_fields, serialize, touch
from helpers import (
    get_json_body,
    parse_pagination,
    paginate,
    sort_by_creation,
    require_int,
    require_str,
)
import lookups
from response import created, ok, listed

bp = Blueprint("cash_drawers", __name__)


@bp.route("/cash-drawers", methods=["POST"])
def create_drawer():
    require_auth(MANAGER_ONLY)
    body = get_json_body()
    store_code = require_str(body, "store_code")
    business_date = require_str(body, "business_date")
    opening_float_cents = require_int(body, "opening_float_cents", minimum=0)

    # priority 16: single-occupancy conflict on (store_code, business_date)
    for d in db.cash_drawers.values():
        if (
            d["store_code"] == store_code
            and d["business_date"] == business_date
            and d["status"] == "OPEN"
        ):
            raise errors.err(
                errors.ERR_DRAWER_CONFLICT,
                "An OPEN drawer already exists for this store_code/business_date",
            )

    did = new_id()
    drawer = {
        "id": did,
        "store_code": store_code,
        "business_date": business_date,
        "opening_float_cents": opening_float_cents,
        "status": "OPEN",
        "expected_cash_cents": opening_float_cents,
        "counted_cash_cents": None,
        "variance_cents": 0,
    }
    drawer.update(common_fields())
    db.cash_drawers[did] = drawer
    return created(serialize(drawer))


@bp.route("/cash-drawers/<did>", methods=["GET"])
def get_drawer(did):
    require_auth(BOTH)
    drawer = lookups.get_drawer(did)
    return ok(serialize(drawer))


@bp.route("/cash-drawers/<did>/transactions", methods=["GET"])
def list_drawer_transactions(did):
    require_auth(BOTH)
    lookups.get_drawer(did)
    limit, offset = parse_pagination()
    items = [t for t in db.transactions.values() if t["drawer_id"] == did]

    lifecycle_state = request.args.get("lifecycle_state")
    if lifecycle_state is not None:
        items = [t for t in items if t["lifecycle_state"] == lifecycle_state]

    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([serialize(t) for t in page], limit, offset, total)


@bp.route("/cash-drawers/<did>/begin-reconcile", methods=["POST"])
def begin_reconcile(did):
    require_auth(MANAGER_ONLY)
    drawer = lookups.get_drawer(did)

    # priority 4: must be OPEN to begin reconciling
    if drawer["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Drawer is not OPEN")

    # priority 15: no DRAFT (risk-held) transactions may remain on the drawer
    for t in db.transactions.values():
        if t["drawer_id"] == did and t["lifecycle_state"] == "DRAFT":
            raise errors.err(
                errors.ERR_OPEN_ITEMS_REMAIN,
                "A risk-held (DRAFT) transaction remains on this drawer",
            )

    # expected_cash_cents already reflects current postings; freeze by moving state.
    drawer["status"] = "RECONCILING"
    touch(drawer)
    return ok(serialize(drawer))


@bp.route("/cash-drawers/<did>/close", methods=["POST"])
def close_drawer(did):
    require_auth(MANAGER_ONLY)
    drawer = lookups.get_drawer(did)
    body = get_json_body()

    counted_cash_cents = require_int(body, "counted_cash_cents", minimum=0)
    expected_drawer_version = require_int(body, "expected_drawer_version")

    # priority 4: must be RECONCILING to close
    if drawer["status"] != "RECONCILING":
        raise errors.err(errors.ERR_INVALID_STATE, "Drawer is not RECONCILING")

    # OCC (PRD §2.10): expected_drawer_version must match current version (412)
    if expected_drawer_version != drawer["version"]:
        raise errors.err(
            errors.ERR_STALE_DRAWER_VERSION,
            "expected_drawer_version does not match current drawer version",
        )

    variance = counted_cash_cents - drawer["expected_cash_cents"]
    drawer["counted_cash_cents"] = counted_cash_cents
    drawer["variance_cents"] = variance
    drawer["status"] = "CLOSED" if variance == 0 else "OVER_SHORT"
    touch(drawer)
    return ok(serialize(drawer))
