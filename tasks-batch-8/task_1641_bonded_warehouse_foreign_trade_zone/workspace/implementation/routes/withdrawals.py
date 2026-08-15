"""Withdrawal endpoints (SCAFFOLD 1.5, PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_ZONE_NOT_FOUND, ERR_LOT_NOT_FOUND, ERR_WEEKLY_ENTRY_NOT_FOUND,
    ERR_WITHDRAWAL_NOT_FOUND, ERR_WITHDRAWAL_INVALID_TRANSITION,
    ERR_NOT_RESOURCE_OWNER, ERR_ZONE_NOT_ACTIVE, ERR_ZONE_AUDIT_HOLD,
    ERR_LOT_NOT_IN_ZONE, ERR_INSUFFICIENT_QUANTITY, ERR_ENTRY_NOT_OPEN,
    ERR_WITHDRAWAL_OUTSIDE_ENTRY_WEEK, ERR_WRONG_WITHDRAWAL_TYPE,
    ERR_ZR_CONSUMPTION_FORBIDDEN, ERR_CROSS_ZONE_REFERENCE,
)
from middleware import authorized
from response import success_object, success_list
from serializers import withdrawal_view
from services import (
    new_common, touch, recompute_zone_aggregates, recompute_entry_totals,
    debit_lot_for_withdrawal, restore_lot_for_withdrawal, duty_amount, CLOCK,
)
from validate import (
    get_body, reject_unknown_fields, req_str, req_int, req_enum, opt_nullable_str,
    require_path, require_body_fk, parse_pagination,
)

bp = Blueprint("withdrawals", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]


@bp.route("/zones/withdrawals", methods=["POST"])
def create_withdrawal():
    caller = authorized(["Importer"])
    body = get_body()
    reject_unknown_fields(body, {"zone_id", "lot_id", "weekly_entry_id",
                                 "withdrawal_type", "quantity"})
    zone_id = req_str(body, "zone_id")
    zone = require_body_fk("zones", zone_id, ERR_ZONE_NOT_FOUND, "zone_id")
    lot_id = req_str(body, "lot_id")
    lot = require_body_fk("lots", lot_id, ERR_LOT_NOT_FOUND, "lot_id")
    weekly_entry_id = opt_nullable_str(body, "weekly_entry_id")
    entry = None
    if weekly_entry_id is not None:
        entry = require_body_fk("weekly_entries", weekly_entry_id,
                                ERR_WEEKLY_ENTRY_NOT_FOUND, "weekly_entry_id")
    withdrawal_type = req_enum(body, "withdrawal_type", {"CONSUMPTION", "EXPORT"})
    quantity = req_int(body, "quantity", positive=True)

    # Ownership (priority 5): caller must own the lot; an attached entry must
    # belong to the same importer.
    if lot["importer_ref"] != caller.user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own the lot")
    if entry is not None and entry["importer_ref"] != caller.user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER, "weekly entry belongs to a different importer")

    # PRD 3.5/3.6: at creation the attach checks are zone match and importer
    # match only; the entry-OPEN gate (ERR_ENTRY_NOT_OPEN) is declared solely at
    # filing and at cancellation, so it is deliberately NOT enforced here.

    # Safety prohibition (priority 7): CONSUMPTION against ZONE_RESTRICTED lot.
    if withdrawal_type == "CONSUMPTION" and lot["zone_status"] == "ZONE_RESTRICTED":
        raise_error(ERR_ZR_CONSUMPTION_FORBIDDEN,
                    "zone-restricted merchandise may only be exported")

    # Referential (priority 10): withdrawal zone == lot zone; entry zone == withdrawal zone.
    if lot["zone_id"] != zone["id"]:
        raise_error(ERR_CROSS_ZONE_REFERENCE, "withdrawal zone must equal the lot's zone")
    if entry is not None and entry["zone_id"] != zone["id"]:
        raise_error(ERR_CROSS_ZONE_REFERENCE, "weekly entry zone must equal the withdrawal's zone")

    withdrawal = new_common()
    withdrawal.update({
        "zone_id": zone["id"],
        "importer_ref": caller.user_id,
        "lot_id": lot["id"],
        "weekly_entry_id": entry["id"] if entry is not None else None,
        "withdrawal_type": withdrawal_type,
        "quantity": quantity,
        "estimated_duty_cents": duty_amount(quantity, lot["unit_value_cents"], lot["duty_rate"]),
        "assessed_duty_cents": None,
        "withdrawal_date": None,
        "duty_outcome": "PENDING",
        "status": "DRAFT",
    })
    db["withdrawals"][withdrawal["id"]] = withdrawal
    return success_object(withdrawal_view(withdrawal), status=201)


@bp.route("/zones/withdrawals", methods=["GET"])
def list_withdrawals():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    zone_id = request.args.get("zone_id")
    lot_id = request.args.get("lot_id")
    weekly_entry_id = request.args.get("weekly_entry_id")
    status = request.args.get("status")
    withdrawal_type = request.args.get("withdrawal_type")
    items = sorted(db["withdrawals"].values(), key=lambda w: (w["created_at"], w["id"]))
    if zone_id is not None:
        items = [w for w in items if w["zone_id"] == zone_id]
    if lot_id is not None:
        items = [w for w in items if w["lot_id"] == lot_id]
    if weekly_entry_id is not None:
        items = [w for w in items if w["weekly_entry_id"] == weekly_entry_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    if withdrawal_type is not None:
        items = [w for w in items if w["withdrawal_type"] == withdrawal_type]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([withdrawal_view(w) for w in page], total, limit, offset)


@bp.route("/zones/withdrawals/<withdrawalId>", methods=["GET"])
def get_withdrawal(withdrawalId):
    authorized(ALL_ROLES)
    withdrawal = require_path("withdrawals", withdrawalId, ERR_WITHDRAWAL_NOT_FOUND)
    return success_object(withdrawal_view(withdrawal))


def _zone_gate_active_and_normal(zone):
    if zone["status"] != "ACTIVE":
        raise_error(ERR_ZONE_NOT_ACTIVE, "operation requires zone.status == ACTIVE")
    if zone["compliance_posture"] != "NORMAL":
        raise_error(ERR_ZONE_AUDIT_HOLD, "operation requires zone.compliance_posture == NORMAL")


@bp.route("/zones/withdrawals/<withdrawalId>/file", methods=["POST"])
def file_withdrawal(withdrawalId):
    caller = authorized(["Importer"])
    withdrawal = require_path("withdrawals", withdrawalId, ERR_WITHDRAWAL_NOT_FOUND)
    get_body()
    if caller.user_id != withdrawal["importer_ref"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own this withdrawal")
    if withdrawal["status"] != "DRAFT":
        raise_error(ERR_WITHDRAWAL_INVALID_TRANSITION,
                    f"withdrawal cannot be filed from {withdrawal['status']}")
    zone = db["zones"][withdrawal["zone_id"]]
    _zone_gate_active_and_normal(zone)
    lot = db["lots"][withdrawal["lot_id"]]
    if lot["status"] != "IN_ZONE":
        raise_error(ERR_LOT_NOT_IN_ZONE, "lot must be IN_ZONE")
    entry = None
    if withdrawal["weekly_entry_id"] is not None:
        entry = db["weekly_entries"][withdrawal["weekly_entry_id"]]
        if entry["status"] != "OPEN":
            raise_error(ERR_ENTRY_NOT_OPEN, "attached weekly entry must be OPEN")
    # Temporal (priority 8): filing instant inside the entry week [start, end).
    if entry is not None:
        now = CLOCK.now()
        if not (entry["week_start_date"] <= now < entry["week_end_date"]):
            raise_error(ERR_WITHDRAWAL_OUTSIDE_ENTRY_WEEK,
                        "filing time falls outside the attached entry week")
    # Resource constraint (priority 9): availability checked at filing, equality allowed.
    if withdrawal["quantity"] > lot["quantity_on_hand"] - lot["reserved_quantity"]:
        raise_error(ERR_INSUFFICIENT_QUANTITY, "quantity exceeds available units")

    withdrawal["withdrawal_date"] = CLOCK.now()
    withdrawal["assessed_duty_cents"] = duty_amount(
        withdrawal["quantity"], lot["unit_value_cents"], lot["duty_rate"])
    withdrawal["status"] = "FILED"
    touch(withdrawal)
    debit_lot_for_withdrawal(withdrawal)
    recompute_zone_aggregates(zone)
    if entry is not None:
        recompute_entry_totals(entry)
    return success_object(withdrawal_view(withdrawal))


@bp.route("/zones/withdrawals/<withdrawalId>/pay-duty", methods=["POST"])
def pay_duty(withdrawalId):
    caller = authorized(["Importer"])
    withdrawal = require_path("withdrawals", withdrawalId, ERR_WITHDRAWAL_NOT_FOUND)
    get_body()
    if caller.user_id != withdrawal["importer_ref"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own this withdrawal")
    if withdrawal["status"] != "FILED":
        raise_error(ERR_WITHDRAWAL_INVALID_TRANSITION,
                    f"withdrawal duty cannot be paid from {withdrawal['status']}")
    if withdrawal["withdrawal_type"] != "CONSUMPTION":
        raise_error(ERR_WRONG_WITHDRAWAL_TYPE, "pay-duty requires CONSUMPTION type")
    zone = db["zones"][withdrawal["zone_id"]]
    _zone_gate_active_and_normal(zone)

    withdrawal["status"] = "DUTY_PAID"
    withdrawal["duty_outcome"] = "COLLECTED"
    touch(withdrawal)
    if withdrawal["weekly_entry_id"] is not None:
        recompute_entry_totals(db["weekly_entries"][withdrawal["weekly_entry_id"]])
    return success_object(withdrawal_view(withdrawal))


@bp.route("/zones/withdrawals/<withdrawalId>/confirm-export", methods=["POST"])
def confirm_export(withdrawalId):
    caller = authorized(["CustomsOfficer"])
    withdrawal = require_path("withdrawals", withdrawalId, ERR_WITHDRAWAL_NOT_FOUND)
    get_body()
    if withdrawal["status"] != "FILED":
        raise_error(ERR_WITHDRAWAL_INVALID_TRANSITION,
                    f"withdrawal export cannot be confirmed from {withdrawal['status']}")
    if withdrawal["withdrawal_type"] != "EXPORT":
        raise_error(ERR_WRONG_WITHDRAWAL_TYPE, "confirm-export requires EXPORT type")
    zone = db["zones"][withdrawal["zone_id"]]
    _zone_gate_active_and_normal(zone)

    withdrawal["status"] = "EXPORTED"
    withdrawal["duty_outcome"] = "EXTINGUISHED"
    touch(withdrawal)
    return success_object(withdrawal_view(withdrawal))


@bp.route("/zones/withdrawals/<withdrawalId>/cancel", methods=["POST"])
def cancel_withdrawal(withdrawalId):
    caller = authorized(["Importer"])
    withdrawal = require_path("withdrawals", withdrawalId, ERR_WITHDRAWAL_NOT_FOUND)
    get_body()
    if caller.user_id != withdrawal["importer_ref"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own this withdrawal")
    if withdrawal["status"] not in ("DRAFT", "FILED"):
        raise_error(ERR_WITHDRAWAL_INVALID_TRANSITION,
                    f"withdrawal cannot be cancelled from {withdrawal['status']}")
    zone = db["zones"][withdrawal["zone_id"]]
    # Cancellation checks only the lifecycle gate; audit hold is not a blocker (PRD 3.5).
    if zone["status"] != "ACTIVE":
        raise_error(ERR_ZONE_NOT_ACTIVE, "operation requires zone.status == ACTIVE")
    entry = None
    if withdrawal["weekly_entry_id"] is not None:
        entry = db["weekly_entries"][withdrawal["weekly_entry_id"]]
        if entry["status"] != "OPEN":
            raise_error(ERR_ENTRY_NOT_OPEN, "attached weekly entry must be OPEN")

    was_filed = withdrawal["status"] == "FILED"
    withdrawal["status"] = "CANCELLED"
    withdrawal["duty_outcome"] = "NONE"
    touch(withdrawal)
    if was_filed:
        # Compensation of the filing: restore lot, recompute aggregates + entry totals.
        restore_lot_for_withdrawal(withdrawal)
        recompute_zone_aggregates(zone)
        if entry is not None:
            recompute_entry_totals(entry)
    return success_object(withdrawal_view(withdrawal))
