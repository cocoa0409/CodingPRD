"""Routes for /minibar-items and /minibar-consumptions."""

from datetime import timedelta

from flask import Blueprint, request, g

from db import DB, LOCK, new_id
from errors import (
    raise_error,
    ERR_CONSUMPTION_NOT_FOUND,
    ERR_CONSUMPTION_NOT_PENDING,
    ERR_CONSUMPTION_NOT_POSTED,
    ERR_CONSUMPTION_NOT_DISPUTED,
    ERR_CONSUMPTION_NOT_INVESTIGATED,
    ERR_DISPUTE_WINDOW_EXPIRED,
    ERR_DUPLICATE_MINIBAR_LINE_ITEM,
    ERR_INVALID_LINE_QUANTITY,
    ERR_INVALID_REQUEST,
    ERR_MINIBAR_ITEM_ARCHIVED,
    ERR_MINIBAR_ITEM_NOT_FOUND,
    ERR_ROOM_NOT_FOUND,
)
from middleware import auth_required
from response import success_response, list_response
from services.audit import append_audit
from services.calculations import compute_minibar_totals
from services.common import (
    bump,
    require_body_dict,
    require_enum,
    require_field,
    stamp_create,
)
from services.pagination import parse_pagination, paginate
from services.serializers import (
    serialize_minibar_consumption,
    serialize_minibar_item,
)
from services.time_util import now_utc, parse_iso, utc_now_iso


bp = Blueprint("minibar", __name__)


SOURCE_TYPES = {"HOUSEKEEPER", "GUEST_SELF_REPORT"}
DISPUTE_WINDOW_HOURS = 72


# --------------------------------------------------------------------------- #
# Minibar items
# --------------------------------------------------------------------------- #
@bp.route("/minibar-items", methods=["POST"])
@auth_required(["Supervisor"])
def create_item():
    body = require_body_dict(request.get_json(silent=True))
    sku_code = require_field(body, "sku_code", str)
    display_name = require_field(body, "display_name", str)
    unit_price_cents = require_field(body, "unit_price_cents", int)
    par_level = require_field(body, "par_level", int)
    replenishment_threshold = require_field(body, "replenishment_threshold", int)
    if isinstance(unit_price_cents, bool) or unit_price_cents < 0:
        raise_error(ERR_INVALID_REQUEST, "unit_price_cents must be a non-negative integer")
    if isinstance(par_level, bool) or par_level < 0:
        raise_error(ERR_INVALID_REQUEST, "par_level must be a non-negative integer")
    if isinstance(replenishment_threshold, bool) or replenishment_threshold < 0:
        raise_error(ERR_INVALID_REQUEST, "replenishment_threshold must be a non-negative integer")
    with LOCK:
        for it in DB["minibar_items"].values():
            if it["sku_code"] == sku_code and it.get("status", "ACTIVE") == "ACTIVE":
                raise_error(ERR_INVALID_REQUEST,
                            "sku_code must be unique across active items")
        item = {
            "sku_code": sku_code,
            "display_name": display_name,
            "unit_price_cents": int(unit_price_cents),
            "par_level": int(par_level),
            "replenishment_threshold": int(replenishment_threshold),
            "status": "ACTIVE",
        }
        stamp_create(item)
        DB["minibar_items"][item["id"]] = item
    return success_response(serialize_minibar_item(item), http_status=201)


@bp.route("/minibar-items", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper", "Engineer"])
def list_items():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = list(DB["minibar_items"].values())
    if status:
        items = [i for i in items if i.get("status") == status]
    items.sort(key=lambda i: i["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_minibar_item(i) for i in page], total, limit, offset
    )


@bp.route("/minibar-items/<item_id>/archive", methods=["POST"])
@auth_required(["Supervisor"])
def archive_item(item_id):
    with LOCK:
        item = DB["minibar_items"].get(item_id)
        if item is None:
            raise_error(ERR_MINIBAR_ITEM_NOT_FOUND, "MinibarItem not found")
        item["status"] = "ARCHIVED"
        bump(item)
    return success_response(serialize_minibar_item(item))


# --------------------------------------------------------------------------- #
# Minibar consumptions
# --------------------------------------------------------------------------- #
def get_consumption_or_404(cid):
    c = DB["minibar_consumptions"].get(cid)
    if c is None:
        raise_error(ERR_CONSUMPTION_NOT_FOUND, "MinibarConsumption not found")
    return c


@bp.route("/minibar-consumptions", methods=["POST"])
@auth_required(["Housekeeper", "FrontDesk"])
def create_consumption():
    body = require_body_dict(request.get_json(silent=True))
    room_id = require_field(body, "room_id", str)
    source_type = require_enum(body, "source_type", SOURCE_TYPES)
    line_items = body.get("line_items")
    cleaning_task_id = body.get("cleaning_task_id")

    with LOCK:
        # Path 0 existence: room_id
        if room_id not in DB["rooms"]:
            raise_error(ERR_ROOM_NOT_FOUND, "Room not found")

        # Validate line_items shape FIRST (priority 11 in scaffold ordering)
        if not isinstance(line_items, list) or len(line_items) == 0:
            raise_error(ERR_INVALID_LINE_QUANTITY,
                        "line_items must be a non-empty array")
        # Quantity, then duplicates, then existence (priority: line shape > duplicate > existence)
        seen = set()
        for li in line_items:
            if not isinstance(li, dict):
                raise_error(ERR_INVALID_REQUEST,
                            "line_items entries must be objects")
            qty = li.get("quantity")
            if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
                raise_error(ERR_INVALID_LINE_QUANTITY,
                            "quantity must be an integer >= 1")
        # Duplicate check (priority 10 in scaffold)
        for li in line_items:
            mi_id = li.get("minibar_item_id")
            if not isinstance(mi_id, str):
                raise_error(ERR_INVALID_REQUEST,
                            "minibar_item_id must be a string")
            if mi_id in seen:
                raise_error(ERR_DUPLICATE_MINIBAR_LINE_ITEM,
                            "minibar_item_id appears twice in line_items")
            seen.add(mi_id)
        # Existence
        for li in line_items:
            if li["minibar_item_id"] not in DB["minibar_items"]:
                raise_error(ERR_MINIBAR_ITEM_NOT_FOUND,
                            "minibar_item_id does not exist")
        # Archived check (priority 12)
        for li in line_items:
            it = DB["minibar_items"][li["minibar_item_id"]]
            if it.get("status") != "ACTIVE":
                raise_error(ERR_MINIBAR_ITEM_ARCHIVED,
                            "minibar item is archived")

        if source_type == "GUEST_SELF_REPORT" and cleaning_task_id is not None:
            raise_error(ERR_INVALID_REQUEST,
                        "cleaning_task_id must be null for GUEST_SELF_REPORT")
        if cleaning_task_id is not None and cleaning_task_id not in DB["cleaning_tasks"]:
            raise_error(ERR_INVALID_REQUEST, "cleaning_task_id does not exist")

        consumption = {
            "room_id": room_id,
            "cleaning_task_id": cleaning_task_id,
            "source_type": source_type,
            "line_items": [
                {"minibar_item_id": li["minibar_item_id"], "quantity": int(li["quantity"])}
                for li in line_items
            ],
            "gross_amount_cents": None,
            "tax_cents": None,
            "posted_amount_cents": None,
            "posted_at": None,
            "folio_reference": None,
            "dispute_note": None,
            "finding_note": None,
            "status": "PENDING",
        }
        stamp_create(consumption)
        DB["minibar_consumptions"][consumption["id"]] = consumption
    return success_response(serialize_minibar_consumption(consumption), http_status=201)


@bp.route("/minibar-consumptions", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper"])
def list_consumptions():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    room_id = request.args.get("room_id")
    items = list(DB["minibar_consumptions"].values())
    if status:
        items = [c for c in items if c["status"] == status]
    if room_id:
        items = [c for c in items if c["room_id"] == room_id]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_minibar_consumption(c) for c in page], total, limit, offset
    )


@bp.route("/minibar-consumptions/<cid>", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper"])
def get_consumption(cid):
    c = get_consumption_or_404(cid)
    return success_response(serialize_minibar_consumption(c))


@bp.route("/minibar-consumptions/<cid>/post", methods=["POST"])
@auth_required(["FrontDesk"])
def post_consumption(cid):
    with LOCK:
        c = get_consumption_or_404(cid)
        if c["status"] != "PENDING":
            raise_error(ERR_CONSUMPTION_NOT_PENDING,
                        "Consumption is not in PENDING state")
        # Re-check archived status on the items
        item_lookup = {}
        for li in c["line_items"]:
            it = DB["minibar_items"].get(li["minibar_item_id"])
            if it is None:
                raise_error(ERR_MINIBAR_ITEM_NOT_FOUND,
                            "minibar item not found")
            if it.get("status") != "ACTIVE":
                raise_error(ERR_MINIBAR_ITEM_ARCHIVED,
                            "minibar item is archived")
            item_lookup[it["id"]] = it
        gross, tax, posted = compute_minibar_totals(c["line_items"], item_lookup)
        c["gross_amount_cents"] = gross
        c["tax_cents"] = tax
        c["posted_amount_cents"] = posted
        c["folio_reference"] = "folio_" + new_id().replace("-", "")[:20]
        c["posted_at"] = utc_now_iso()
        c["status"] = "POSTED"
        bump(c)
        append_audit(
            actor_id=g.user_id,
            actor_role=g.user_role,
            action_type="MINIBAR_CONSUMPTION_POST",
            subject_entity="MinibarConsumption",
            subject_id=c["id"],
            detail={
                "gross_amount_cents": gross,
                "tax_cents": tax,
                "posted_amount_cents": posted,
                "folio_reference": c["folio_reference"],
            },
        )
    return success_response(serialize_minibar_consumption(c))


@bp.route("/minibar-consumptions/<cid>/dispute", methods=["POST"])
@auth_required(["FrontDesk"])
def dispute_consumption(cid):
    body = require_body_dict(request.get_json(silent=True))
    dispute_note = require_field(body, "dispute_note", str)
    with LOCK:
        c = get_consumption_or_404(cid)
        if c["status"] != "POSTED":
            raise_error(ERR_CONSUMPTION_NOT_POSTED,
                        "Consumption is not in POSTED state")
        posted_at = parse_iso(c["posted_at"])
        if posted_at is None:
            raise_error(ERR_DISPUTE_WINDOW_EXPIRED,
                        "Missing posted_at")
        elapsed = now_utc() - posted_at
        if elapsed >= timedelta(hours=DISPUTE_WINDOW_HOURS):
            raise_error(ERR_DISPUTE_WINDOW_EXPIRED,
                        f"Dispute window of {DISPUTE_WINDOW_HOURS}h has elapsed")
        c["status"] = "DISPUTED"
        c["dispute_note"] = dispute_note
        bump(c)
        append_audit(
            actor_id=g.user_id,
            actor_role=g.user_role,
            action_type="MINIBAR_CONSUMPTION_DISPUTE",
            subject_entity="MinibarConsumption",
            subject_id=c["id"],
            detail={"dispute_note": dispute_note},
        )
    return success_response(serialize_minibar_consumption(c))


@bp.route("/minibar-consumptions/<cid>/investigate", methods=["POST"])
@auth_required(["Supervisor"])
def investigate_consumption(cid):
    body = require_body_dict(request.get_json(silent=True))
    finding_note = require_field(body, "finding_note", str)
    with LOCK:
        c = get_consumption_or_404(cid)
        if c["status"] != "DISPUTED":
            raise_error(ERR_CONSUMPTION_NOT_DISPUTED,
                        "Consumption is not in DISPUTED state")
        c["status"] = "INVESTIGATED"
        c["finding_note"] = finding_note
        bump(c)
    return success_response(serialize_minibar_consumption(c))


@bp.route("/minibar-consumptions/<cid>/resolve", methods=["POST"])
@auth_required(["Supervisor"])
def resolve_consumption(cid):
    body = require_body_dict(request.get_json(silent=True))
    if "keep_charge" not in body or not isinstance(body["keep_charge"], bool):
        raise_error(ERR_INVALID_REQUEST, "keep_charge must be a boolean")
    keep_charge = body["keep_charge"]
    with LOCK:
        c = get_consumption_or_404(cid)
        if c["status"] != "INVESTIGATED":
            raise_error(ERR_CONSUMPTION_NOT_INVESTIGATED,
                        "Consumption is not in INVESTIGATED state")
        if keep_charge:
            c["status"] = "RESOLVED"
            bump(c)
            append_audit(
                actor_id=g.user_id,
                actor_role=g.user_role,
                action_type="ROOM_STATUS_CHANGE",
                subject_entity="MinibarConsumption",
                subject_id=c["id"],
                detail={"resolved": "kept_charge"},
            )
        else:
            if int(c.get("posted_amount_cents") or 0) <= 0:
                raise_error(ERR_INVALID_REQUEST,
                            "Cannot waive: posted_amount_cents is not positive")
            c["status"] = "WAIVED"
            bump(c)
            append_audit(
                actor_id=g.user_id,
                actor_role=g.user_role,
                action_type="MINIBAR_CONSUMPTION_WAIVE",
                subject_entity="MinibarConsumption",
                subject_id=c["id"],
                detail={
                    # PRD §3.11 invariant: "the absolute reversal
                    # recorded at resolution exactly equals the
                    # gross_amount_cents plus tax_cents posted on the
                    # original folio-post action".
                    "amount_cents": int(c["posted_amount_cents"]),
                    "posted_amount_cents": int(c["posted_amount_cents"]),
                    "reversal_amount_cents": int(c["posted_amount_cents"]),
                    "folio_reference": c.get("folio_reference"),
                },
            )
    return success_response(serialize_minibar_consumption(c))
