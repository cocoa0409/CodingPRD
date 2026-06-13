"""Quote routes: draft/lines/send/revise/accept/decline + lazy expiry (PRD §3.3-§3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import lookup
import serialize
import services.calc as calc
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("quotes", __name__)

QUOTE_TYPES = {"SERVICE_CALL", "INSTALL"}
ITEM_KINDS = {"PART", "DOOR", "OPENER", "LABOR"}
EXPIRY_DAYS = 14


def _maybe_expire(quote):
    """Lazily flip a DRAFT/SENT quote to EXPIRED when now >= expires_at (PRD §3.4)."""
    if quote["status"] in ("DRAFT", "SENT") and quote.get("expires_at"):
        exp = calc._parse_iso(quote["expires_at"])
        if exp is not None and clock.now() >= exp:
            quote["status"] = "EXPIRED"
            db.touch(quote)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ----- Create quote -----
@bp.route("/quotes", methods=["POST"])
def create_quote():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["customer_id", "quote_type"])
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "customer_id must be a string")
    quote_type = util.require_enum(body, "quote_type", QUOTE_TYPES)
    door_model_id = body.get("door_model_id")
    opener_model_id = body.get("opener_model_id")
    if door_model_id is not None and not isinstance(door_model_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "door_model_id must be a string")
    if opener_model_id is not None and not isinstance(opener_model_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "opener_model_id must be a string")
    service_call_fee_cents = util.optional_int(body, "service_call_fee_cents", 0)

    # Existence: path/body FKs resolved left-to-right (PRD §2.7)
    lookup.customer(customer_id)
    if quote_type == "INSTALL":
        if door_model_id is not None:
            lookup.door_model(door_model_id)
        if opener_model_id is not None:
            lookup.opener_model(opener_model_id)
    else:
        # SERVICE_CALL: door/opener null
        door_model_id = None
        opener_model_id = None

    q = {
        "customer_id": customer_id, "quote_type": quote_type,
        "door_model_id": door_model_id if quote_type == "INSTALL" else None,
        "opener_model_id": opener_model_id if quote_type == "INSTALL" else None,
        "status": "DRAFT", "revision": 1,
        "service_call_fee_cents": service_call_fee_cents if quote_type == "SERVICE_CALL" else 0,
        "estimate_total_cents": 0,
        "expires_at": None,
    }
    db.stamp_create(q, common_fields=True, versioned=True)
    db.quotes[q["id"]] = q
    return success(serialize.quote(q), status=201)


@bp.route("/quotes/<id>", methods=["GET"])
def get_quote(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer"])
    q = lookup.quote(id)
    _maybe_expire(q)
    return success(serialize.quote(q))


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer"])
    limit, offset = util.parse_pagination()
    customer_id = request.args.get("customer_id")
    door_model_id = request.args.get("door_model_id")
    opener_model_id = request.args.get("opener_model_id")
    status = request.args.get("status")
    rows = []
    for q in db.quotes.values():
        _maybe_expire(q)
        if customer_id is not None and q["customer_id"] != customer_id:
            continue
        if door_model_id is not None and q["door_model_id"] != door_model_id:
            continue
        if opener_model_id is not None and q["opener_model_id"] != opener_model_id:
            continue
        if status is not None and q["status"] != status:
            continue
        rows.append(q)
    page, pagination = util.paginate(rows, limit, offset)
    return success([serialize.quote(q) for q in page], pagination=pagination)


# ----- Quote lines -----
@bp.route("/quotes/<id>/lines", methods=["POST"])
def add_line(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    q = lookup.quote(id)
    body = util.get_body()
    util.require_fields(body, ["item_kind", "qty"])
    item_kind = util.require_enum(body, "item_kind", ITEM_KINDS)
    qty = util.require_qty(body, "qty")

    item_ref_id = body.get("item_ref_id")
    if item_kind == "PART":
        if not isinstance(item_ref_id, str):
            raise errors.err(errors.ERR_INVALID_REQUEST, "item_ref_id required for PART line")
        part = lookup.part(item_ref_id)
        unit_price_cents = util.optional_int(body, "unit_price_cents", part["unit_price_cents"])
    else:
        item_ref_id = None
        unit_price_cents = util.optional_int(body, "unit_price_cents", 0)

    line = {
        "quote_id": q["id"], "item_kind": item_kind, "item_ref_id": item_ref_id,
        "qty": qty, "unit_price_cents": unit_price_cents, "line_total_cents": 0,
    }
    db.stamp_create(line, common_fields=True, versioned=True)
    line["line_total_cents"] = calc.compute_line_total(line)
    db.quote_lines[line["id"]] = line

    # recompute Quote.estimate_total_cents when SENT; increments Quote.version
    if q["status"] == "SENT":
        q["estimate_total_cents"] = calc.quote_estimate_total(q)
    db.touch(q)
    return success(serialize.quote_line(line), status=201)


@bp.route("/quotes/<id>/lines", methods=["GET"])
def list_lines(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer"])
    q = lookup.quote(id)
    rows = [l for l in db.quote_lines.values() if l["quote_id"] == q["id"]]
    limit, offset = util.parse_pagination()
    page, pagination = util.paginate(rows, limit, offset)
    return success([serialize.quote_line(l) for l in page], pagination=pagination)


# ----- Send -----
@bp.route("/quotes/<id>/send", methods=["POST"])
def send_quote(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    q = lookup.quote(id)
    _maybe_expire(q)
    if q["status"] == "EXPIRED":
        raise errors.err(errors.ERR_QUOTE_EXPIRED, "Quote expired")
    if q["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Quote must be DRAFT to send")
    lines = [l for l in db.quote_lines.values() if l["quote_id"] == q["id"]]
    if len(lines) < 1:
        raise errors.err(errors.ERR_INVALID_STATE, "Quote must have at least one line to send")
    q["status"] = "SENT"
    q["expires_at"] = _iso(clock.now() + timedelta(days=EXPIRY_DAYS))
    q["estimate_total_cents"] = calc.quote_estimate_total(q)
    db.touch(q)
    return success(serialize.quote(q))


# ----- Revise (cyclic, OCC-guarded) -----
@bp.route("/quotes/<id>/revise", methods=["POST"])
def revise_quote(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    q = lookup.quote(id)
    body = util.get_body()
    util.require_fields(body, ["expected_quote_version"])
    expected = util.require_int(body, "expected_quote_version")
    _maybe_expire(q)
    if q["status"] == "EXPIRED":
        raise errors.err(errors.ERR_QUOTE_EXPIRED, "Quote expired")
    if q["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Quote must be SENT to revise")
    # OCC check (priority 17, after state per PRD §2.8 ordering)
    if expected != q["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale quote version")
    q["revision"] += 1
    q["expires_at"] = _iso(clock.now() + timedelta(days=EXPIRY_DAYS))
    q["estimate_total_cents"] = calc.quote_estimate_total(q)
    db.touch(q)
    return success(serialize.quote(q))


# ----- Accept (cascade) -----
@bp.route("/quotes/<id>/accept", methods=["POST"])
def accept_quote(id):
    user_id, role = authenticate()
    require_role(role, ["Customer"])
    q = lookup.quote(id)
    _maybe_expire(q)
    if q["status"] == "EXPIRED":
        raise errors.err(errors.ERR_QUOTE_EXPIRED, "Quote expired")
    if q["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Quote must be SENT to accept")
    customer = db.customers[q["customer_id"]]
    if calc.financing_standing(customer["id"]) == "BLOCKED":
        raise errors.err(errors.ERR_CUSTOMER_BLOCKED, "Customer financing standing is BLOCKED")

    # Pre-flight stock check (atomic): all PART lines must fit available_qty.
    part_lines = [l for l in db.quote_lines.values()
                  if l["quote_id"] == q["id"] and l["item_kind"] == "PART"]
    # Aggregate demanded qty per part to validate against current available_qty.
    demanded = {}
    for l in part_lines:
        demanded[l["item_ref_id"]] = demanded.get(l["item_ref_id"], 0) + l["qty"]
    for part_id, want in demanded.items():
        part = db.parts.get(part_id)
        if part is None:
            raise errors.err(errors.ERR_NOT_FOUND, "Part not found")
        available = part["on_hand_qty"] - calc.reserved_qty(part_id)
        if want > available:
            raise errors.err(errors.ERR_INSUFFICIENT_STOCK, "Insufficient stock for accept")

    # Commit: quote -> ACCEPTED
    q["status"] = "ACCEPTED"
    # Create Job (UNSCHEDULED / PENDING)
    job = {
        "quote_id": q["id"], "customer_id": q["customer_id"],
        "technician_id": None, "equipment_unit_id": None,
        "dispatch_status": "UNSCHEDULED", "billing_status": "PENDING",
        "scheduled_start": None, "scheduled_end": None,
        "is_emergency": False, "safety_inspection_passed": False,
        "completed_by_user_id": None,
        "final_total_cents": None, "emergency_surcharge_cents": 0,
    }
    db.stamp_create(job, common_fields=True, versioned=True)
    db.jobs[job["id"]] = job
    # Create HELD reservations per PART line; reserved_qty/available_qty derive live.
    for l in part_lines:
        res = {
            "job_id": job["id"], "part_id": l["item_ref_id"],
            "qty": l["qty"], "status": "HELD",
        }
        db.stamp_create(res, common_fields=True, versioned=True)
        db.part_reservations[res["id"]] = res
    db.touch(q)
    return success(serialize.quote(q))


# ----- Decline -----
@bp.route("/quotes/<id>/decline", methods=["POST"])
def decline_quote(id):
    _, role = authenticate()
    require_role(role, ["Customer"])
    q = lookup.quote(id)
    _maybe_expire(q)
    if q["status"] == "EXPIRED":
        raise errors.err(errors.ERR_QUOTE_EXPIRED, "Quote expired")
    if q["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Quote must be SENT to decline")
    q["status"] = "DECLINED"
    db.touch(q)
    return success(serialize.quote(q))
