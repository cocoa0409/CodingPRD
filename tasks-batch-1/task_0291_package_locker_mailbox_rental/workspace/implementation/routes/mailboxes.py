"""MailboxUnit endpoints."""
from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import err
from response import success, list_response
from middleware import require_roles
from common import (get_json, require_fields, require_str, require_enum, require_int,
                    fk_or_404, get_or_404, touch, parse_pagination, paginate)
import constants as C
import serializers as S

bp = Blueprint("mailboxes", __name__)


@bp.post("/mailbox-units")
def create_mailbox():
    require_roles("FacilityOperator")
    body = get_json()
    require_fields(body, ["facility_id", "box_number", "size_tier", "monthly_fee_cents"])
    facility_id = require_str(body, "facility_id")
    box_number = require_str(body, "box_number")
    size_tier = require_enum(body, "size_tier", C.MAILBOX_SIZE_TIERS)
    monthly_fee_cents = require_int(body, "monthly_fee_cents", minimum=0)
    facility = fk_or_404(db.facilities, facility_id)
    for m in db.mailbox_units.values():
        if m["facility_id"] == facility_id and m["box_number"] == box_number:
            raise err("ERR_DUPLICATE", "box_number already exists in facility")
    mid = new_id()
    mailbox = {
        "id": mid,
        "facility_id": facility_id,
        "box_number": box_number,
        "size_tier": size_tier,
        "monthly_fee_cents": monthly_fee_cents,
        "status": "VACANT",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.mailbox_units[mid] = mailbox
    return success(S.mailbox_out(mailbox), status=201)


@bp.get("/mailbox-units/<mid>")
def get_mailbox(mid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    mailbox = get_or_404(db.mailbox_units, mid)
    return success(S.mailbox_out(mailbox))


@bp.get("/mailbox-units")
def list_mailboxes():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.mailbox_units.values())
    fid = request.args.get("facility_id")
    status = request.args.get("status")
    size_tier = request.args.get("size_tier")
    if fid is not None:
        items = [x for x in items if x["facility_id"] == fid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if size_tier is not None:
        items = [x for x in items if x["size_tier"] == size_tier]
    page, total = paginate(items, limit, offset)
    return list_response([S.mailbox_out(x) for x in page], limit, offset, total)


@bp.post("/mailbox-units/<mid>/out-of-service")
def mailbox_oos(mid):
    require_roles("FacilityOperator")
    mailbox = get_or_404(db.mailbox_units, mid)
    if mailbox["status"] != "VACANT":
        raise err("ERR_MAILBOX_NOT_VACANT", "Mailbox must be VACANT to take out of service")
    mailbox["status"] = "OUT_OF_SERVICE"
    touch(mailbox)
    return success(S.mailbox_out(mailbox))


@bp.post("/mailbox-units/<mid>/restore")
def mailbox_restore(mid):
    require_roles("FacilityOperator")
    mailbox = get_or_404(db.mailbox_units, mid)
    if mailbox["status"] != "OUT_OF_SERVICE":
        raise err("ERR_MAILBOX_NOT_VACANT", "Mailbox must be OUT_OF_SERVICE to restore")
    mailbox["status"] = "VACANT"
    touch(mailbox)
    return success(S.mailbox_out(mailbox))
