"""BidSpec endpoints: create/get/list, publish, issue-addendum, close."""
from flask import Blueprint, request

from db import new_record, public, store, touch
from errors import ERR_INVALID_REQUEST, ERR_INVALID_STATE, raise_err
from middleware import ALL_ROLES, authenticate, require_roles, scope_district
from response import success
from validation import (
    body,
    get_or_404,
    paginate,
    parse_pagination,
    req_date,
    req_str,
)

bp = Blueprint("bid_specs", __name__)


def _load_scoped_spec(caller, rid):
    rec = store.bid_specs.get(rid)
    if rec is not None:
        scope_district(caller, rec["district_id"])  # priority 3
    return get_or_404(store.bid_specs, rid, "bid spec")  # priority 4


@bp.route("/v1/bid-specs", methods=["POST"])
def create_bid_spec():
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    data = body()

    district_id = data.get("district_id")
    if isinstance(district_id, str):
        existing = store.districts.get(district_id)
        if existing is not None:
            scope_district(caller, existing["id"])
    if isinstance(district_id, str):
        get_or_404(store.districts, district_id, "district")

    district_id = req_str(data, "district_id")
    title = req_str(data, "title")
    bid_due_date = req_date(data, "bid_due_date")
    window_start = req_date(data, "delivery_window_start")
    window_end = req_date(data, "delivery_window_end")

    rec = new_record({
        "district_id": district_id,
        "title": title,
        "bid_due_date": bid_due_date,
        "delivery_window_start": window_start,
        "delivery_window_end": window_end,
        "spec_version": 1,
        "status": "DRAFT",
    })
    store.bid_specs[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/bid-specs/<rid>", methods=["GET"])
def get_bid_spec(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.bid_specs, rid, "bid spec")
    return success(public(rec), code=200)


@bp.route("/v1/bid-specs", methods=["GET"])
def list_bid_specs():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.bid_specs.values())
    district_id = request.args.get("district_id")
    status = request.args.get("status")
    if district_id is not None:
        records = [r for r in records if r["district_id"] == district_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


@bp.route("/v1/bid-specs/<rid>/publish", methods=["POST"])
def publish_bid_spec(rid):
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    rec = _load_scoped_spec(caller, rid)

    if rec["status"] == "DRAFT":
        has_lines = any(sl["bid_spec_id"] == rec["id"] for sl in store.spec_lines.values())
        if not has_lines:
            raise_err(ERR_INVALID_REQUEST, "A specification with no lines cannot be published")
        rec["status"] = "PUBLISHED"  # spec_version remains 1 on first publish
    elif rec["status"] == "ADDENDUM_ISSUED":
        rec["status"] = "PUBLISHED"
        rec["spec_version"] += 1  # content version bump invalidates award pins
    else:
        raise_err(ERR_INVALID_STATE, f"Cannot publish a spec in status {rec['status']}")
    touch(rec)
    return success(public(rec), code=200)


@bp.route("/v1/bid-specs/<rid>/issue-addendum", methods=["POST"])
def issue_addendum(rid):
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    rec = _load_scoped_spec(caller, rid)
    data = body()
    req_str(data, "addendum_note")

    if rec["status"] not in ("PUBLISHED", "CLOSED", "AWARDED"):
        raise_err(ERR_INVALID_STATE, f"Cannot issue an addendum on a spec in status {rec['status']}")
    rec["status"] = "ADDENDUM_ISSUED"
    touch(rec)
    return success(public(rec), code=200)


@bp.route("/v1/bid-specs/<rid>/close", methods=["POST"])
def close_bid_spec(rid):
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    rec = _load_scoped_spec(caller, rid)

    if rec["status"] != "PUBLISHED":
        raise_err(ERR_INVALID_STATE, f"Cannot close a spec in status {rec['status']}")
    rec["status"] = "CLOSED"
    touch(rec)
    return success(public(rec), code=200)
