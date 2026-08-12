"""DropBox, FillReading and box-collection endpoints."""
from flask import Blueprint

from db import store, new_record, touch, now_dt, now_iso, next_seq, new_id
from errors import fail
from middleware import endpoint
from response import success
from services import calc, domain
from util import check_fields, get_body, paginate, parse_dt

bp = Blueprint("dropboxes", __name__)


@bp.route("/dropboxes", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_dropbox(user_id, role):
    body = get_body()
    check_fields(body, {
        "zone_id": ("str", True),
        "label": ("str", True),
        "location": ("str", True),
    })
    if body["zone_id"] not in store.zones:
        fail("ERR_NOT_FOUND", "ServiceZone not found: %s" % body["zone_id"])
    rec = new_record()
    rec.update({
        "zone_id": body["zone_id"],
        "label": body["label"],
        "location": body["location"],
        "fill_pct": 0,
        "posture": "OK",
        "last_collected_at": None,
    })
    store.dropboxes[rec["id"]] = rec
    return success(domain.dropbox_view(rec), code=201)


@bp.route("/dropboxes/<bid>", methods=["GET"])
@endpoint(["ZoneOperator", "Driver", "SensorGateway"])
def get_dropbox(user_id, role, bid):
    box = domain.get_or_404(store.dropboxes, bid, "DropBox")
    return success(domain.dropbox_view(box))


@bp.route("/dropboxes/<bid>/fill-readings", methods=["POST"])
@endpoint(["SensorGateway"])
def post_fill_reading(user_id, role, bid):
    box = store.dropboxes.get(bid)
    body = get_body()
    check_fields(body, {"fill_pct": ("num", True), "recorded_at": ("dt", True)})
    pct = calc.dec(body["fill_pct"])
    if pct < 0 or pct > 100:
        fail("ERR_INVALID_REQUEST", "fill_pct must be between 0 and 100")
    if box is None:
        fail("ERR_NOT_FOUND", "DropBox not found: %s" % bid)
    # append-only event: id + created_at only
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "dropbox_id": bid,
        "fill_pct": body["fill_pct"],
        "recorded_at": body["recorded_at"],
        "_recorded_at": parse_dt(body["recorded_at"]),
        "_seq": next_seq(),
    }
    store.readings[rec["id"]] = rec
    domain.recompute_box_posture(box)
    touch(box)
    return success(domain.reading_view(rec), code=201)


@bp.route("/dropboxes/<bid>/fill-readings", methods=["GET"])
@endpoint(["ZoneOperator", "SensorGateway"])
def list_fill_readings(user_id, role, bid):
    domain.get_or_404(store.dropboxes, bid, "DropBox")
    items = [r for r in store.readings.values() if r["dropbox_id"] == bid]
    page, meta = paginate(items)
    return success([domain.reading_view(r) for r in page], response_type="array",
                   pagination=meta)


@bp.route("/dropboxes/<bid>/collections", methods=["POST"])
@endpoint(["Driver"])
def collect_dropbox(user_id, role, bid):
    box = store.dropboxes.get(bid)
    body = get_body()
    check_fields(body, {"provisional_weight_kg": ("num", True)})
    if calc.dec(body["provisional_weight_kg"]) <= 0:
        fail("ERR_INVALID_REQUEST", "provisional_weight_kg must be > 0")
    if box is None:
        fail("ERR_NOT_FOUND", "DropBox not found: %s" % bid)
    # p5 dedicated form: posture must be FULL_PENDING_COLLECTION
    if box["posture"] != "FULL_PENDING_COLLECTION":
        fail("ERR_DROPBOX_NOT_FULL", "Drop box is not FULL_PENDING_COLLECTION")
    ticket = new_record()
    ticket.update({
        "source_type": "DROPBOX",
        "source_id": box["id"],
        "provisional_weight_kg": body["provisional_weight_kg"],
        "certified_weight_kg": None,
        "grade": None,
        "status": "PROVISIONAL",
        "projected_credit_cents": calc.projected_credit_cents(body["provisional_weight_kg"]),
        "highest_upheld_severity": "NONE",
        "certified_at": None,
        "_certified_at": None,
    })
    store.tickets[ticket["id"]] = ticket
    box["fill_pct"] = 0
    box["posture"] = "OK"
    box["last_collected_at"] = now_iso()
    touch(box)
    return success(domain.ticket_view(ticket), code=201)


@bp.route("/dropboxes/<bid>/weight-tickets", methods=["GET"])
@endpoint(["ZoneOperator", "Driver"])
def list_box_tickets(user_id, role, bid):
    domain.get_or_404(store.dropboxes, bid, "DropBox")
    items = [t for t in store.tickets.values()
             if t["source_type"] == "DROPBOX" and t["source_id"] == bid]
    page, meta = paginate(items)
    return success([domain.ticket_view(t) for t in page], response_type="array",
                   pagination=meta)
