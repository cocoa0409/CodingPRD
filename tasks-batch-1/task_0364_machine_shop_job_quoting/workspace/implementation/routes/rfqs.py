"""RFQ and PartLine routes (PRD §3.1)."""
from flask import Blueprint

from db import db, lock, base_fields, touch
from errors import err
from middleware import require_roles, require_auth
from helpers import (
    get_body, require_fields, validate_enum, as_int, as_str, parse_datetime,
    paginate, serialize, serialize_list,
)
from response import success, list_response
import services as svc

bp = Blueprint("rfqs", __name__)

INCOTERMS = {"EXW", "FOB", "DDP"}
MATERIAL_SPECS = {"AL_6061", "SS_304", "TI_6AL4V", "BRASS_360"}
TOLERANCE_CLASSES = {"STANDARD", "PRECISION", "CRITICAL"}


def get_rfq_or_404(rfq_id):
    rfq = db.rfqs.get(rfq_id)
    if rfq is None:
        raise err("ERR_NOT_FOUND", "RFQ not found")
    return rfq


# ---------------------------------------------------------------------------
# RFQ
# ---------------------------------------------------------------------------


@bp.route("/rfqs", methods=["POST"])
def create_rfq():
    require_roles("ShopAdmin")
    body = get_body()
    require_fields(body, "customer_name", "customer_id", "requested_due_date")
    customer_name = as_str(body, "customer_name")
    customer_id = as_str(body, "customer_id")
    requested_due_date = body["requested_due_date"]
    parse_datetime(requested_due_date, "requested_due_date")  # validate format
    incoterm = body.get("incoterm")
    if incoterm is None:
        incoterm = "EXW"
    else:
        validate_enum(incoterm, INCOTERMS, "incoterm")
    with lock():
        rec = base_fields()
        rec.update({
            "customer_name": customer_name,
            "customer_id": customer_id,
            "requested_due_date": requested_due_date,
            "incoterm": incoterm,
            "status": "DRAFT",
            "part_line_count": 0,
        })
        db.rfqs[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/rfqs/<rfq_id>", methods=["GET"])
def get_rfq(rfq_id):
    require_auth()
    with lock():
        return success(serialize(get_rfq_or_404(rfq_id)))


@bp.route("/rfqs", methods=["GET"])
def list_rfqs():
    require_auth()
    from flask import request
    status = request.args.get("status")
    with lock():
        items = list(db.rfqs.values())
        if status:
            items = [r for r in items if r["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/rfqs/<rfq_id>/submit", methods=["POST"])
def submit_rfq(rfq_id):
    require_roles("ShopAdmin")
    with lock():
        rfq = get_rfq_or_404(rfq_id)
        if rfq["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "RFQ must be DRAFT to submit")
        if rfq["part_line_count"] < 1:
            raise err("ERR_RFQ_NO_PART_LINES", "RFQ has no part lines")
        rfq["status"] = "SUBMITTED"
        touch(rfq)
        return success(serialize(rfq))


@bp.route("/rfqs/<rfq_id>/close", methods=["POST"])
def close_rfq(rfq_id):
    require_roles("ShopAdmin")
    with lock():
        rfq = get_rfq_or_404(rfq_id)
        if rfq["status"] != "QUOTED":
            raise err("ERR_INVALID_STATE", "RFQ must be QUOTED to close")
        # Every WorkOrder derived from this RFQ's quotes must be SHIPPED or CLOSED
        for q in svc.quotes_for_rfq(rfq_id):
            for wo in svc.work_orders_for_quote(q["id"]):
                if wo["status"] not in ("SHIPPED", "CLOSED"):
                    raise err("ERR_INVALID_STATE", "Not all work orders are shipped/closed")
        rfq["status"] = "CLOSED"
        touch(rfq)
        return success(serialize(rfq))


@bp.route("/rfqs/<rfq_id>/cancel", methods=["POST"])
def cancel_rfq(rfq_id):
    require_roles("ShopAdmin")
    with lock():
        rfq = get_rfq_or_404(rfq_id)
        if rfq["status"] not in ("DRAFT", "SUBMITTED"):
            raise err("ERR_INVALID_STATE", "RFQ can only be cancelled from DRAFT or SUBMITTED")
        if rfq["status"] == "SUBMITTED":
            quotes = svc.quotes_for_rfq(rfq_id)
            if any(q["status"] == "APPROVED" for q in quotes):
                raise err("ERR_RFQ_HAS_APPROVED_QUOTE", "RFQ has an approved quote")
            # cascade: DRAFT/PRICED quotes -> REJECTED
            for q in quotes:
                if q["status"] in ("DRAFT", "PRICED"):
                    q["status"] = "REJECTED"
                    q["rejection_reason"] = "RFQ cancelled"
                    touch(q)
        rfq["status"] = "CANCELLED"
        touch(rfq)
        return success(serialize(rfq))


# ---------------------------------------------------------------------------
# PartLine
# ---------------------------------------------------------------------------


@bp.route("/rfqs/<rfq_id>/part-lines", methods=["POST"])
def create_part_line(rfq_id):
    require_roles("ShopAdmin")
    with lock():
        rfq = get_rfq_or_404(rfq_id)
        body = get_body()
        require_fields(body, "part_number", "drawing_rev", "material_spec", "quantity")
        part_number = as_str(body, "part_number")
        drawing_rev = as_str(body, "drawing_rev")
        material_spec = body["material_spec"]
        validate_enum(material_spec, MATERIAL_SPECS, "material_spec")
        quantity = as_int(body, "quantity", minimum=1)
        tolerance_class = body.get("tolerance_class")
        if tolerance_class is None:
            tolerance_class = "STANDARD"
        else:
            validate_enum(tolerance_class, TOLERANCE_CLASSES, "tolerance_class")
        if rfq["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "PartLines can only be added to a DRAFT RFQ")
        rec = base_fields()
        rec.update({
            "rfq_id": rfq_id,
            "part_number": part_number,
            "drawing_rev": drawing_rev,
            "material_spec": material_spec,
            "quantity": quantity,
            "tolerance_class": tolerance_class,
        })
        db.part_lines[rec["id"]] = rec
        svc.recompute_part_line_count(rfq)
        return success(serialize(rec), status=201)


@bp.route("/rfqs/<rfq_id>/part-lines", methods=["GET"])
def list_rfq_part_lines(rfq_id):
    require_auth()
    with lock():
        get_rfq_or_404(rfq_id)
        items = [p for p in db.part_lines.values() if p["rfq_id"] == rfq_id]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/part-lines", methods=["GET"])
def list_part_lines():
    require_auth()
    from flask import request
    rfq_id = request.args.get("rfq_id")
    with lock():
        items = list(db.part_lines.values())
        if rfq_id:
            items = [p for p in items if p["rfq_id"] == rfq_id]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/part-lines/<part_line_id>", methods=["GET"])
def get_part_line(part_line_id):
    require_auth()
    with lock():
        pl = db.part_lines.get(part_line_id)
        if pl is None:
            raise err("ERR_NOT_FOUND", "PartLine not found")
        return success(serialize(pl))
