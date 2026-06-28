from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

from core import (store, require, get_body, get_or_404, ok, ok_list, paginate, common_create, touch,
                  clock, new_id, parse_iso, to_iso,
                  req_str, req_int, req_enum, opt_int, opt_number, opt_str, ApiError,
                  ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                  ERR_VARIETY_NOT_ACTIVE, ERR_ZONE_NOT_OPEN, ERR_CLIMATE_MISMATCH,
                  ERR_INVALID_STARTED_COUNT, ERR_ZONE_CAPACITY_EXCEEDED, ERR_ZONE_TIGHT_FILL_CAP,
                  ERR_STALE_VERSION, ERR_GROW_CYCLE_INCOMPLETE, ERR_NO_GRADE_MEASUREMENT,
                  ERR_BATCH_HAS_COMMITMENTS)
import services as svc

bp = Blueprint("batches", __name__)

READ_ROLES = ["GrowerManager", "ProductionTech", "SalesCoordinator"]
CREATE_ROLES = ["GrowerManager", "ProductionTech"]
EVENT_TYPES = {"CLIMATE", "IRRIGATION", "FERTILIZER", "SCOUTING", "GRADE"}


def _grade_logs(batch_id):
    return [l for l in store.input_logs.values()
            if l["batch_id"] == batch_id and l["event_type"] == "GRADE" and l.get("mean_height_cm") is not None]


def _has_grade_measurement(batch_id):
    return len(_grade_logs(batch_id)) > 0


def _latest_grade_seq(batch_id):
    seqs = [l["_seq"] for l in _grade_logs(batch_id)]
    return max(seqs) if seqs else -1


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------
@bp.post("/nursery/batches")
def create_batch():
    require(CREATE_ROLES)
    body = get_body()
    # existence of present, string-typed FKs first
    raw_vid = body.get("variety_id")
    raw_zid = body.get("zone_id")
    if isinstance(raw_vid, str) and raw_vid not in store.varieties:
        raise ApiError(ERR_NOT_FOUND, "Variety not found")
    if isinstance(raw_zid, str) and raw_zid not in store.zones:
        raise ApiError(ERR_NOT_FOUND, "Zone not found")
    # well-formedness
    variety_id = req_str(body, "variety_id")
    zone_id = req_str(body, "zone_id")
    source_supplier = req_str(body, "source_supplier")
    sourced_count = req_int(body, "sourced_count", minimum=1)
    if variety_id not in store.varieties:
        raise ApiError(ERR_NOT_FOUND, "Variety not found")
    if zone_id not in store.zones:
        raise ApiError(ERR_NOT_FOUND, "Zone not found")
    variety = store.varieties[variety_id]
    zone = store.zones[zone_id]
    # business
    if variety["status"] != "ACTIVE":
        raise ApiError(ERR_VARIETY_NOT_ACTIVE, "Variety is not ACTIVE")
    if zone["status"] != "OPEN_FOR_USE":
        raise ApiError(ERR_ZONE_NOT_OPEN, "Zone is not open for placement")
    footprint = sourced_count * variety["container_footprint_units"]
    if zone["fill_state"] == "FULL":
        raise ApiError(ERR_ZONE_CAPACITY_EXCEEDED, "Zone is full")
    if zone["fill_state"] == "TIGHT" and footprint > (zone["free_units"] // 2):
        raise ApiError(ERR_ZONE_TIGHT_FILL_CAP, "Reservation exceeds tight-zone fill cap")
    if footprint > zone["free_units"]:
        raise ApiError(ERR_ZONE_CAPACITY_EXCEEDED, "Reservation exceeds zone free space")

    b = common_create({
        "variety_id": variety_id,
        "zone_id": zone_id,
        "lot_code": "LOT-" + new_id().replace("-", "")[:10].upper(),
        "source_supplier": source_supplier,
        "sourced_count": sourced_count,
        "started_count": 0,
        "cull_count": 0,
        "live_count": 0,
        "shipped_count": 0,
        "saleable_count": 0,
        "mean_height_cm": 0,
        "stick_date": None,
        "target_ship_date": None,
        "status": "PLANNED",
    })
    b["_grade_gate_seq"] = -1
    store.batches[b["id"]] = b
    svc.cascade_zone(zone)
    return ok(b, 201)


@bp.get("/nursery/batches/<bid>")
def get_batch(bid):
    require(READ_ROLES)
    b = get_or_404(store.batches, bid)
    return ok(b)


@bp.get("/nursery/batches")
def list_batches():
    require(READ_ROLES)
    rows = list(store.batches.values())
    for key in ("status", "variety_id", "zone_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r[key] == val]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Transplant (OCC on zone)
# ---------------------------------------------------------------------------
@bp.post("/nursery/batches/<bid>/transplant")
def transplant(bid):
    require(["ProductionTech"])
    b = get_or_404(store.batches, bid)
    body = get_body()
    started_count = req_int(body, "started_count")
    expected_zone_version = req_int(body, "expected_zone_version")
    if b["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, "Batch is not PLANNED")
    variety = store.varieties.get(b["variety_id"])
    zone = store.zones.get(b["zone_id"])
    # business preconditions, in PRD order
    if variety["status"] != "ACTIVE":
        raise ApiError(ERR_VARIETY_NOT_ACTIVE, "Variety is not ACTIVE")
    if zone["status"] != "OPEN_FOR_USE":
        raise ApiError(ERR_ZONE_NOT_OPEN, "Zone is not open for placement")
    # climate compatibility: MIXED zones accept all; no variety climate requirement is
    # modeled (the variety entity carries no climate field), so non-MIXED zones are
    # treated as compatible. ERR_CLIMATE_MISMATCH is unreachable absent a variety climate attribute.
    if zone["climate_class"] != "MIXED":
        pass
    if not (1 <= started_count <= b["sourced_count"]):
        raise ApiError(ERR_INVALID_STARTED_COUNT, "started_count must be in [1, sourced_count]")
    footprint = variety["container_footprint_units"]
    planted = started_count * footprint
    own_reservation = b["sourced_count"] * footprint
    if planted > zone["free_units"] + own_reservation:
        raise ApiError(ERR_ZONE_CAPACITY_EXCEEDED, "Planted footprint exceeds zone capacity")
    if expected_zone_version != zone["version"]:
        raise ApiError(ERR_STALE_VERSION, "Zone version is stale")

    b["started_count"] = started_count
    b["cull_count"] = 0
    b["shipped_count"] = 0
    svc.recompute_live(b)  # live_count = started_count
    b["saleable_count"] = 0
    stick = clock.now()
    b["stick_date"] = to_iso(stick)
    b["target_ship_date"] = to_iso(stick + timedelta(days=variety["grow_cycle_days"]))
    b["status"] = "GROWING"
    touch(b)
    svc.cascade_zone(zone)
    return ok(b)


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------
@bp.post("/nursery/batches/<bid>/start-grading")
def start_grading(bid):
    require(["ProductionTech"])
    b = get_or_404(store.batches, bid)
    if b["status"] not in ("GROWING", "HELD", "SALEABLE"):
        raise ApiError(ERR_INVALID_STATE, "Batch cannot begin grading from %s" % b["status"])
    if b["status"] == "GROWING":
        target = parse_iso(b["target_ship_date"])
        if clock.now() < target:
            raise ApiError(ERR_GROW_CYCLE_INCOMPLETE, "Grow cycle is not complete")
        if not _has_grade_measurement(b["id"]):
            raise ApiError(ERR_NO_GRADE_MEASUREMENT, "No GRADE measurement recorded")
    elif b["status"] == "HELD":
        if _latest_grade_seq(b["id"]) <= b.get("_grade_gate_seq", -1):
            raise ApiError(ERR_NO_GRADE_MEASUREMENT, "No newer GRADE measurement since entering HELD")
    else:  # SALEABLE
        if svc.has_committed_draw(b):
            raise ApiError(ERR_BATCH_HAS_COMMITMENTS, "Batch has committed order lines")
        if _latest_grade_seq(b["id"]) <= b.get("_grade_gate_seq", -1):
            raise ApiError(ERR_NO_GRADE_MEASUREMENT, "No newer GRADE measurement since entering SALEABLE")
    b["status"] = "GRADING"
    b["saleable_count"] = svc.provisional_saleable(b)
    touch(b)
    return ok(b)


@bp.post("/nursery/batches/<bid>/finalize-grade")
def finalize_grade(bid):
    require(["ProductionTech"])
    b = get_or_404(store.batches, bid)
    if b["status"] != "GRADING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not GRADING")
    variety = store.varieties.get(b["variety_id"])
    height_ok = b["mean_height_cm"] >= variety["ship_ready_grade_min_height_cm"]
    live_ok = False
    if b["started_count"] > 0:
        live_ok = (Decimal(b["live_count"]) / Decimal(b["started_count"])) >= Decimal(str(variety["ship_ready_min_live_pct"]))
    if height_ok and live_ok:
        b["status"] = "SALEABLE"
        b["saleable_count"] = svc.final_saleable(b)
        b["_grade_gate_seq"] = store._seq
        touch(b)
        for e in svc.open_entries_for_batch(b["id"]):
            e["published_quantity"] = b["saleable_count"]
            svc.recompute_availability(e)
            touch(e)
    else:
        b["status"] = "HELD"
        b["saleable_count"] = 0
        b["_grade_gate_seq"] = store._seq
        touch(b)
    return ok(b)


# ---------------------------------------------------------------------------
# Cull / void
# ---------------------------------------------------------------------------
@bp.post("/nursery/batches/<bid>/cull-batch")
def cull_batch(bid):
    require(["ProductionTech"])
    b = get_or_404(store.batches, bid)
    get_body()  # loss_basis optional, not surfaced
    if b["status"] not in ("GROWING", "HELD", "SALEABLE"):
        raise ApiError(ERR_INVALID_STATE, "Batch cannot be culled from %s" % b["status"])
    if b["status"] in ("GROWING", "SALEABLE") and svc.has_committed_draw(b):
        raise ApiError(ERR_BATCH_HAS_COMMITMENTS, "Batch has committed order lines")
    svc.do_full_cull(b)
    return ok(b)


@bp.post("/nursery/batches/<bid>/void")
def void_batch(bid):
    require(["GrowerManager"])
    b = get_or_404(store.batches, bid)
    if b["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, "Only PLANNED batches can be voided")
    b["status"] = "VOIDED"
    touch(b)
    zone = store.zones.get(b["zone_id"])
    if zone:
        svc.cascade_zone(zone)
    return ok(b)


# ---------------------------------------------------------------------------
# Input logs
# ---------------------------------------------------------------------------
@bp.get("/nursery/batches/<bid>/input-logs")
def list_input_logs(bid):
    require(READ_ROLES)
    get_or_404(store.batches, bid)
    rows = [l for l in store.input_logs.values() if l["batch_id"] == bid]
    event_type = request.args.get("event_type")
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.post("/nursery/batches/<bid>/input-logs")
def record_input_log(bid):
    require(["ProductionTech"])
    b = get_or_404(store.batches, bid)
    body = get_body()
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    temperature_c = opt_number(body, "temperature_c")
    irrigation_liters = opt_number(body, "irrigation_liters")
    fertilizer_ppm_n = opt_number(body, "fertilizer_ppm_n")
    mean_height_cm = opt_number(body, "mean_height_cm")
    dead_observed = opt_int(body, "dead_observed", default=0, minimum=0)
    note = opt_str(body, "note")
    if event_type == "GRADE" and mean_height_cm is None:
        raise ApiError(ERR_INVALID_REQUEST, "mean_height_cm is required for GRADE events")

    log = {
        "id": new_id(),
        "created_at": clock.now_iso(),
        "batch_id": bid,
        "event_type": event_type,
        "recorded_at": clock.now_iso(),
        "temperature_c": temperature_c,
        "irrigation_liters": irrigation_liters,
        "fertilizer_ppm_n": fertilizer_ppm_n,
        "mean_height_cm": mean_height_cm,
        "dead_observed": dead_observed,
        "note": note,
        "_seq": store.next_seq(),
    }
    store.input_logs[log["id"]] = log

    if event_type == "GRADE":
        b["mean_height_cm"] = mean_height_cm

    drives_shrink = (event_type in ("SCOUTING", "GRADE") and dead_observed > 0
                     and b["status"] in ("GROWING", "GRADING", "HELD"))
    if drives_shrink:
        b["cull_count"] += dead_observed
        svc.recompute_live(b)
        cumulative = Decimal(b["cull_count"]) / Decimal(b["started_count"]) if b["started_count"] > 0 else Decimal(0)
        if cumulative >= svc.AUTO_CULL_PCT:
            svc.do_full_cull(b)  # touches batch + cascades zone + closes availability
        else:
            touch(b)
            zone = store.zones.get(b["zone_id"])
            if zone:
                svc.cascade_zone(zone)
    elif event_type == "GRADE":
        touch(b)

    return ok(log, 201)
