"""ServiceZone endpoints."""
from flask import Blueprint

from db import store, new_record, touch
from errors import fail
from middleware import endpoint
from response import success
from services import domain
from util import check_fields, get_body, paginate, parse_dt

bp = Blueprint("zones", __name__)

ALL_ROLES = ["ZoneOperator", "Resident", "Driver", "PartnerManager", "Inspector",
             "SponsorManager", "CharityAdmin", "SensorGateway"]


@bp.route("/service-zones", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_zone(user_id, role):
    body = get_body()
    check_fields(body, {"name": ("str", True)})
    rec = new_record()
    rec.update({"name": body["name"], "charity_splits": []})
    store.zones[rec["id"]] = rec
    return success(domain.zone_view(rec), code=201)


@bp.route("/service-zones/<zid>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_zone(user_id, role, zid):
    zone = domain.get_or_404(store.zones, zid, "ServiceZone")
    return success(domain.zone_view(zone))


@bp.route("/service-zones/<zid>/charity-split", methods=["PUT"])
@endpoint(["ZoneOperator"])
def put_charity_split(user_id, role, zid):
    zone = store.zones.get(zid)  # existence deferred to priority 4
    body = get_body()
    # p3: well-formedness (declared fields, structural types)
    check_fields(body, {"charity_splits": ("list", True),
                        "expected_zone_version": ("int", True)})
    splits = body["charity_splits"]
    for line in splits:
        if not isinstance(line, dict):
            fail("ERR_INVALID_REQUEST", "charity_splits lines must be objects")
        for key in line:
            if key not in ("charity_id", "pct"):
                fail("ERR_INVALID_REQUEST", "Undeclared field in split line: %s" % key)
        if "charity_id" not in line or "pct" not in line:
            fail("ERR_INVALID_REQUEST", "split line requires charity_id and pct")
        if not isinstance(line["charity_id"], str):
            fail("ERR_INVALID_REQUEST", "charity_id must be a string")
    # p4: existence — zone, then each referenced charity
    if zone is None:
        fail("ERR_NOT_FOUND", "ServiceZone not found: %s" % zid)
    for line in splits:
        if line["charity_id"] not in store.charities:
            fail("ERR_NOT_FOUND", "Charity not found: %s" % line["charity_id"])
    # p6: optimistic concurrency
    if body["expected_zone_version"] != zone["version"]:
        fail("ERR_STALE_VERSION", "expected_zone_version does not match current version")
    # p9e: split shape — pct integer 1..100, unique ids, sum <= 100
    seen = set()
    total = 0
    for line in splits:
        pct = line["pct"]
        if isinstance(pct, bool) or not isinstance(pct, int) or pct < 1 or pct > 100:
            fail("ERR_SPLIT_SUM_INVALID", "pct must be an integer in 1..100")
        if line["charity_id"] in seen:
            fail("ERR_SPLIT_SUM_INVALID", "duplicate charity_id in splits")
        seen.add(line["charity_id"])
        total += pct
    if total > 100:
        fail("ERR_SPLIT_SUM_INVALID", "sum of pct exceeds 100")
    zone["charity_splits"] = [{"charity_id": l["charity_id"], "pct": l["pct"]} for l in splits]
    touch(zone)
    return success(domain.zone_view(zone))


@bp.route("/service-zones/<zid>/residents", methods=["GET"])
@endpoint(["ZoneOperator"])
def list_zone_residents(user_id, role, zid):
    domain.get_or_404(store.zones, zid, "ServiceZone")
    items = [r for r in store.residents.values() if r["zone_id"] == zid]
    page, meta = paginate(items)
    return success([domain.resident_view(r) for r in page], response_type="array",
                   pagination=meta)


@bp.route("/service-zones/<zid>/dropboxes", methods=["GET"])
@endpoint(["ZoneOperator", "Driver", "SensorGateway"])
def list_zone_dropboxes(user_id, role, zid):
    domain.get_or_404(store.zones, zid, "ServiceZone")
    items = [b for b in store.dropboxes.values() if b["zone_id"] == zid]
    page, meta = paginate(items)
    return success([domain.dropbox_view(b) for b in page], response_type="array",
                   pagination=meta)


@bp.route("/service-zones/<zid>/sponsor-funds", methods=["GET"])
@endpoint(["ZoneOperator", "SponsorManager"])
def list_zone_funds(user_id, role, zid):
    domain.get_or_404(store.zones, zid, "ServiceZone")
    items = [f for f in store.funds.values() if f["zone_id"] == zid]
    page, meta = paginate(items)
    return success([domain.fund_view(f) for f in page], response_type="array",
                   pagination=meta)


@bp.route("/service-zones/<zid>/reporting-periods", methods=["GET"])
@endpoint(["ZoneOperator", "SponsorManager", "CharityAdmin"])
def list_zone_periods(user_id, role, zid):
    domain.get_or_404(store.zones, zid, "ServiceZone")
    items = [p for p in store.periods.values() if p["zone_id"] == zid]
    page, meta = paginate(items)
    return success([domain.period_view(p) for p in page], response_type="array",
                   pagination=meta)


@bp.route("/service-zones/<zid>/reporting-periods", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_period(user_id, role, zid):
    zone = store.zones.get(zid)
    body = get_body()
    check_fields(body, {"period_start": ("dt", True), "period_end": ("dt", True)})
    if zone is None:
        fail("ERR_NOT_FOUND", "ServiceZone not found: %s" % zid)
    start = parse_dt(body["period_start"])
    end = parse_dt(body["period_end"])
    # p8: shape then overlap (adjacency allowed)
    if not (end > start):
        fail("ERR_INVALID_WINDOW", "period_end must be after period_start")
    for p in store.periods.values():
        if p["zone_id"] != zid:
            continue
        if start < p["_end"] and p["_start"] < end:
            fail("ERR_PERIOD_OVERLAP", "period overlaps an existing period of this zone")
    rec = new_record()
    rec.update({
        "zone_id": zid,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "status": "OPEN",
        "closed_at": None,
        "aggregates": None,
        "_start": start,
        "_end": end,
    })
    store.periods[rec["id"]] = rec
    return success(domain.period_view(rec), code=201)
