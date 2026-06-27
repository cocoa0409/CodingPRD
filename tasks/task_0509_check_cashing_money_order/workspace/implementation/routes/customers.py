"""Customer + ComplianceScreen routes (PRD §3.1)."""
from flask import Blueprint

import errors
from auth import require_auth, BOTH, MANAGER_ONLY
from db import db, new_id, common_fields, audit_fields, serialize
from helpers import (
    get_json_body,
    parse_pagination,
    paginate,
    sort_by_creation,
    require_str,
    require_enum,
    require_bool,
)
import lookups
from response import created, ok, listed

bp = Blueprint("customers", __name__)

ID_TYPES = {"DRIVERS_LICENSE", "STATE_ID", "PASSPORT", "MILITARY_ID"}
KYC_STATUSES = {"PENDING", "VERIFIED", "OFAC_BLOCKED", "REJECTED"}


def _serialize_customer(c):
    return serialize(c)


def _serialize_screen(s):
    return serialize(s)


@bp.route("/customers", methods=["POST"])
def create_customer():
    require_auth(BOTH)
    body = get_json_body()
    full_name = require_str(body, "full_name")
    id_type = require_enum(body, "id_type", ID_TYPES)
    id_number = require_str(body, "id_number")
    date_of_birth = require_str(body, "date_of_birth")

    cid = new_id()
    customer = {
        "id": cid,
        "full_name": full_name,
        "id_type": id_type,
        "id_number": id_number,
        "date_of_birth": date_of_birth,
        "kyc_status": "PENDING",
        "risk_tier": "STANDARD",
        "risk_score": 0,
        "daily_cashed_amount_cents": 0,
        "daily_transaction_count": 0,
        "limit_window_opened_at": None,
        "outstanding_recovery_cents": 0,
    }
    customer.update(common_fields())
    db.customers[cid] = customer
    return created(_serialize_customer(customer))


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    require_auth(BOTH)
    customer = lookups.get_customer(cid)
    return ok(_serialize_customer(customer))


@bp.route("/customers", methods=["GET"])
def list_customers():
    require_auth(BOTH)
    from flask import request

    limit, offset = parse_pagination()
    items = list(db.customers.values())
    kyc_status = request.args.get("kyc_status")
    if kyc_status is not None:
        items = [c for c in items if c["kyc_status"] == kyc_status]
    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([_serialize_customer(c) for c in page], limit, offset, total)


@bp.route("/customers/<cid>/compliance-screens", methods=["GET"])
def list_customer_screens(cid):
    require_auth(BOTH)
    lookups.get_customer(cid)
    limit, offset = parse_pagination()
    items = [s for s in db.compliance_screens.values() if s["customer_id"] == cid]
    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([_serialize_screen(s) for s in page], limit, offset, total)


@bp.route("/customers/<cid>/returned-items", methods=["GET"])
def list_customer_returned_items(cid):
    require_auth(BOTH)
    lookups.get_customer(cid)
    limit, offset = parse_pagination()
    items = [r for r in db.returned_items.values() if r["customer_id"] == cid]
    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([serialize(r) for r in page], limit, offset, total)


@bp.route("/compliance-screens", methods=["POST"])
def create_compliance_screen():
    require_auth(MANAGER_ONLY)
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    ofac_list_hit = require_bool(body, "ofac_list_hit")
    kyc_documents_valid = require_bool(body, "kyc_documents_valid")

    # existence (priority 3)
    customer = lookups.get_customer(customer_id)

    # priority 7: sanctioned customer cannot be re-screened.
    if customer["kyc_status"] == "OFAC_BLOCKED":
        raise errors.err(errors.ERR_OFAC_BLOCKED, "Customer is OFAC blocked")

    # outcome (PRD §3.1)
    if ofac_list_hit:
        outcome = "OFAC_BLOCKED"
    elif not kyc_documents_valid:
        outcome = "REJECTED"
    else:
        outcome = "VERIFIED"

    sid = new_id()
    screen = {
        "id": sid,
        "customer_id": customer_id,
        "ofac_list_hit": ofac_list_hit,
        "kyc_documents_valid": kyc_documents_valid,
        "outcome": outcome,
    }
    screen.update(audit_fields())
    db.compliance_screens[sid] = screen

    # cascade: write outcome to Customer.kyc_status
    customer["kyc_status"] = outcome
    from db import touch
    touch(customer)

    return created(_serialize_screen(screen))
