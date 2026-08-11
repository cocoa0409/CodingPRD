"""SpecLine endpoints."""
from flask import Blueprint, request

from db import new_record, public, store
from errors import ERR_INVALID_STATE, raise_err
from middleware import ALL_ROLES, authenticate, require_roles, scope_district
from response import success
from validation import (
    body,
    get_or_404,
    opt_str,
    paginate,
    parse_pagination,
    req_int,
    req_str,
)

bp = Blueprint("spec_lines", __name__)


@bp.route("/v1/spec-lines", methods=["POST"])
def create_spec_line():
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    data = body()

    bid_spec_id = data.get("bid_spec_id")
    spec = store.bid_specs.get(bid_spec_id) if isinstance(bid_spec_id, str) else None
    if spec is not None:
        scope_district(caller, spec["district_id"])  # priority 3
    if isinstance(bid_spec_id, str):
        get_or_404(store.bid_specs, bid_spec_id, "bid spec")  # priority 4

    bid_spec_id = req_str(data, "bid_spec_id")
    manufacturer = req_str(data, "manufacturer")
    model = req_str(data, "model")
    qty = req_int(data, "qty", minimum=1)
    max_unit_price_cents = req_int(data, "max_unit_price_cents", minimum=1)
    description = opt_str(data, "description", default=None)

    # priority 6: line creation requires the spec in DRAFT or ADDENDUM_ISSUED
    if spec["status"] not in ("DRAFT", "ADDENDUM_ISSUED"):
        raise_err(ERR_INVALID_STATE, f"Cannot add spec lines to a spec in status {spec['status']}")

    rec = new_record({
        "bid_spec_id": bid_spec_id,
        "manufacturer": manufacturer,
        "model": model,
        "qty": qty,
        "max_unit_price_cents": max_unit_price_cents,
        "description": description,
        "remaining_qty": qty,
    })
    store.spec_lines[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/spec-lines/<rid>", methods=["GET"])
def get_spec_line(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.spec_lines, rid, "spec line")
    return success(public(rec), code=200)


@bp.route("/v1/spec-lines", methods=["GET"])
def list_spec_lines():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.spec_lines.values())
    bid_spec_id = request.args.get("bid_spec_id")
    if bid_spec_id is not None:
        records = [r for r in records if r["bid_spec_id"] == bid_spec_id]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)
