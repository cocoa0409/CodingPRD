"""Award endpoints: create (pins spec version, cascades spec CLOSED -> AWARDED),
get/list, accept, issue-amendment (OCC-guarded re-pin)."""
from flask import Blueprint, request

from db import new_record, public, store, touch
from errors import (
    ERR_BID_SPEC_NOT_CLOSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import ALL_ROLES, authenticate, require_roles, scope_district
from response import success
from validation import (
    body,
    get_or_404,
    opt_int,
    paginate,
    parse_pagination,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("awards", __name__)


@bp.route("/v1/awards", methods=["POST"])
def create_award():
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    data = body()

    district_id = data.get("district_id")
    bid_spec_id = data.get("bid_spec_id")
    coop_agreement_id = data.get("coop_agreement_id")

    # priority 3: ownership scope on the district chain
    if isinstance(district_id, str):
        existing = store.districts.get(district_id)
        if existing is not None:
            scope_district(caller, existing["id"])

    # priority 4: body FK existence in canonical order
    if isinstance(district_id, str):
        get_or_404(store.districts, district_id, "district")
    spec = None
    if isinstance(bid_spec_id, str):
        spec = get_or_404(store.bid_specs, bid_spec_id, "bid spec")
    if isinstance(coop_agreement_id, str):
        get_or_404(store.coop_agreements, coop_agreement_id, "coop agreement")

    # priority 5: shape
    district_id = req_str(data, "district_id")
    bid_spec_id = req_str(data, "bid_spec_id")
    pricing_mode = req_enum(data, "pricing_mode", ("COOP_TIERED", "AWARD_FLAT"))
    if pricing_mode == "COOP_TIERED":
        if not isinstance(data.get("coop_agreement_id"), str):
            raise_err(ERR_INVALID_REQUEST, "coop_agreement_id is required when pricing_mode is COOP_TIERED")
    else:
        req_int(data, "flat_unit_price_cents", minimum=1)
    install_rate_cents = req_int(data, "install_rate_cents", minimum=1)
    order_by_date = req_date(data, "order_by_date")
    warranty_years = req_int(data, "warranty_years", minimum=1)
    extended_years = opt_int(data, "extended_years", default=0, minimum=0)
    if district_id != spec["district_id"]:
        raise_err(ERR_INVALID_REQUEST, "district_id must equal the bid spec's district")

    # priority 7: cross-entity state gate
    if spec["status"] != "CLOSED":
        raise_err(ERR_BID_SPEC_NOT_CLOSED, "Award creation requires the bid spec to be CLOSED")

    rec = new_record({
        "bid_spec_id": bid_spec_id,
        "district_id": district_id,
        "pricing_mode": pricing_mode,
        "coop_agreement_id": data.get("coop_agreement_id"),
        "flat_unit_price_cents": data.get("flat_unit_price_cents"),
        "install_rate_cents": install_rate_cents,
        "order_by_date": order_by_date,
        "warranty_years": warranty_years,
        "extended_years": extended_years if extended_years is not None else 0,
        "awarded_spec_version": spec["spec_version"],
        "status": "ISSUED",
    })
    store.awards[rec["id"]] = rec
    # cascade: spec CLOSED -> AWARDED
    spec["status"] = "AWARDED"
    touch(spec)
    return success(public(rec), code=201)


@bp.route("/v1/awards/<rid>", methods=["GET"])
def get_award(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.awards, rid, "award")
    return success(public(rec), code=200)


@bp.route("/v1/awards", methods=["GET"])
def list_awards():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.awards.values())
    bid_spec_id = request.args.get("bid_spec_id")
    district_id = request.args.get("district_id")
    coop_agreement_id = request.args.get("coop_agreement_id")
    status = request.args.get("status")
    if bid_spec_id is not None:
        records = [r for r in records if r["bid_spec_id"] == bid_spec_id]
    if district_id is not None:
        records = [r for r in records if r["district_id"] == district_id]
    if coop_agreement_id is not None:
        records = [r for r in records if r.get("coop_agreement_id") == coop_agreement_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)


@bp.route("/v1/awards/<rid>/accept", methods=["POST"])
def accept_award(rid):
    caller = authenticate()
    require_roles(caller, ["ContractManager"])
    rec = get_or_404(store.awards, rid, "award")
    if rec["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, f"Cannot accept an award in status {rec['status']}")
    rec["status"] = "ACCEPTED"
    touch(rec)
    return success(public(rec), code=200)


@bp.route("/v1/awards/<rid>/issue-amendment", methods=["POST"])
def issue_amendment(rid):
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    rec = store.awards.get(rid)
    if rec is not None:
        scope_district(caller, rec["district_id"])  # priority 3
    rec = get_or_404(store.awards, rid, "award")  # priority 4

    data = body()
    expected = req_int(data, "expected_award_version")
    req_str(data, "amendment_note")

    # priority 6: amendment is an ACCEPTED -> ACCEPTED self-loop
    if rec["status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, f"Cannot amend an award in status {rec['status']}")

    # priority 17: optimistic concurrency, deliberately last
    if expected != rec["version"]:
        raise_err(ERR_STALE_VERSION, "expected_award_version does not match the award's current version")

    spec = store.bid_specs.get(rec["bid_spec_id"])
    rec["awarded_spec_version"] = spec["spec_version"]
    touch(rec)  # increments Award.version by 1
    return success(public(rec), code=200)
