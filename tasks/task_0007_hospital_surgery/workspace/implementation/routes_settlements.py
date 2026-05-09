from flask import Blueprint, request

from audit import write_audit
from calc import insurance_split_calculation, to_decimal
from db import db
from errors import (
    raise_error,
    ERR_SETTLEMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CASE_NOT_COMPLETED,
    ERR_INVALID_INSURANCE_SPLIT,
    ERR_INSURANCE_PRE_AUTH_REQUIRED,
)
from middleware import auth_required
from response import success, paginate
from serialize import serialize_settlement
from utils import get_json_body, get_pagination, check_version, require_str

bp = Blueprint("settlements", __name__)


@bp.route("/settlements", methods=["GET"])
@auth_required("Any")
def list_settlements():
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    with db.lock:
        items = sorted(db.settlements.values(), key=lambda r: (r["created_at"], r["_seq"]))
        if status_filter:
            items = [r for r in items if r["status"] == status_filter]
        sliced, pagination = paginate(items, limit, offset)
        data = [serialize_settlement(r) for r in sliced]
    return success(data, response_type="array", pagination=pagination)


@bp.route("/settlements/<sid>", methods=["GET"])
@auth_required("Any")
def get_settlement(sid):
    with db.lock:
        s = db.settlements.get(sid)
        if s is None:
            raise_error(ERR_SETTLEMENT_NOT_FOUND, f"Settlement {sid} not found")
        return success(serialize_settlement(s))


@bp.route("/settlements/<sid>/pre-authorize", methods=["POST"])
@auth_required("BillingAdmin")
def pre_authorize(sid):
    body = get_json_body()
    with db.lock:
        s = db.settlements.get(sid)
        if s is None:
            raise_error(ERR_SETTLEMENT_NOT_FOUND, f"Settlement {sid} not found")

        # State check: settlement must be DRAFT and case must be in approved set
        if s["status"] != "DRAFT":
            raise_error(ERR_INVALID_STATE,
                        f"pre-authorize requires settlement DRAFT, got {s['status']}")
        case = db.surgical_cases.get(s["case_id"])
        if case is None or case["status"] not in {"APPROVED", "SCHEDULED", "IN_PROGRESS", "COMPLETED"}:
            raise_error(ERR_INVALID_STATE,
                        "pre-authorize requires owning case in APPROVED/SCHEDULED/IN_PROGRESS/COMPLETED")
        check_version(body, s)
        ref = require_str(body, "insurance_pre_auth_reference")

        s["insurance_pre_auth_reference"] = ref
        s["status"] = "PRE_AUTHORIZED"
        db.stamp_update(s)
        write_audit("Settlement", s["id"], "SETTLEMENT_PRE_AUTHORIZED",
                    {"insurance_pre_auth_reference": ref})
        return success(serialize_settlement(s))


@bp.route("/settlements/<sid>/itemize", methods=["POST"])
@auth_required("BillingAdmin")
def itemize(sid):
    from calc import build_line_items  # avoid circular import at module load
    body = get_json_body()
    with db.lock:
        s = db.settlements.get(sid)
        if s is None:
            raise_error(ERR_SETTLEMENT_NOT_FOUND, f"Settlement {sid} not found")
        if s["status"] != "PRE_AUTHORIZED":
            raise_error(ERR_INVALID_STATE,
                        f"itemize requires PRE_AUTHORIZED, got {s['status']}")
        case = db.surgical_cases.get(s["case_id"])
        if case is None or case["status"] != "COMPLETED":
            raise_error(ERR_CASE_NOT_COMPLETED,
                        "itemize requires owning case in COMPLETED")

        # Validate insurance_split (ERR_INVALID_INSURANCE_SPLIT precedes other shape checks
        # only when the split structure is parseable; pure shape failures are ERR_INVALID_REQUEST).
        splits = body.get("insurance_split")
        if splits is None:
            raise_error(ERR_INVALID_REQUEST, "Missing required field 'insurance_split'")
        if not isinstance(splits, list) or len(splits) == 0:
            raise_error(ERR_INVALID_REQUEST, "insurance_split must be a non-empty list")
        for entry in splits:
            if not isinstance(entry, dict):
                raise_error(ERR_INVALID_REQUEST, "insurance_split entries must be objects")
            if "payer_id" not in entry or not isinstance(entry["payer_id"], str) or not entry["payer_id"]:
                raise_error(ERR_INVALID_REQUEST,
                            "insurance_split entries must include non-empty 'payer_id'")
            pct = entry.get("percentage")
            if isinstance(pct, bool) or not isinstance(pct, int):
                raise_error(ERR_INVALID_REQUEST,
                            "insurance_split.percentage must be an integer")
            if pct < 0 or pct > 100:
                raise_error(ERR_INVALID_REQUEST,
                            "insurance_split.percentage must be in [0,100]")
        total_pct = sum(int(e["percentage"]) for e in splits)
        if total_pct != 100:
            raise_error(ERR_INVALID_INSURANCE_SPLIT,
                        f"insurance_split percentages must sum to 100, got {total_pct}")
        check_version(body, s)

        room = db.operating_rooms.get(case.get("scheduled_room_id"))
        # final_total_amount expected to be pinned at /complete; if not, recompute.
        total = to_decimal(s.get("final_total_amount"))
        implant_component = to_decimal(s.get("implant_cost"))
        line_items = build_line_items(case, room, implant_component) if room else []
        per_payer = insurance_split_calculation(total, splits)

        s["insurance_split"] = [{"payer_id": e["payer_id"], "percentage": int(e["percentage"])}
                                for e in splits]
        s["line_items"] = line_items
        s["per_payer_amounts"] = per_payer
        s["status"] = "ITEMIZED"
        db.stamp_update(s)
        write_audit("Settlement", s["id"], "SETTLEMENT_ITEMIZED",
                    {"per_payer_amounts": [
                        {"payer_id": p["payer_id"], "amount": float(p["amount"])}
                        for p in per_payer
                    ],
                     "total": float(total)})
        return success(serialize_settlement(s))


@bp.route("/settlements/<sid>/settle", methods=["POST"])
@auth_required("BillingAdmin")
def settle(sid):
    body = get_json_body()
    with db.lock:
        s = db.settlements.get(sid)
        if s is None:
            raise_error(ERR_SETTLEMENT_NOT_FOUND, f"Settlement {sid} not found")
        if s["status"] != "ITEMIZED":
            raise_error(ERR_INVALID_STATE,
                        f"settle requires ITEMIZED, got {s['status']}")
        if not s.get("insurance_pre_auth_reference"):
            raise_error(ERR_INSURANCE_PRE_AUTH_REQUIRED,
                        "settle requires non-null insurance_pre_auth_reference")
        check_version(body, s)

        s["status"] = "SETTLED"
        db.stamp_update(s)
        write_audit("Settlement", s["id"], "SETTLEMENT_SETTLED", {})
        return success(serialize_settlement(s))
