"""Purchase transactions, the point ledger and intra-household transfers."""
from flask import Blueprint

import clock
import db
import middleware
import response
import shape
from errors import ApiError, bad_request
from routes._helpers import invalid_state, listing
from services import calc, core, serializers

bp = Blueprint("purchases", __name__)

POSTING_STATUSES = ("RECORDED", "POSTED", "VOIDED")
ACCRUAL_STATUSES = ("NOT_ACCRUED", "ACCRUED", "REVERSED")
ENTRY_TYPES = ("ACCRUAL", "REVERSAL", "REDEMPTION", "REDEMPTION_RELEASE", "TRANSFER_OUT",
               "TRANSFER_IN", "EXPIRY", "ROLLOVER", "ADJUSTMENT")
SOURCE_KINDS = ("PURCHASE_TRANSACTION", "FUEL_REDEMPTION", "POINT_DISPUTE", "POINT_CYCLE",
                "POINT_TRANSFER")


# ------------------------------------------------------- purchase transactions

def _parse_lines(payload):
    raw = shape.req_list(payload, "lines", 1, 20)
    lines = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise bad_request("'lines[%d]' must be an object" % index)
        category = shape.req_enum(item, "category", calc.CATEGORIES)
        amount_cents = shape.req_int(item, "amount_cents", 0, None)
        quantity = shape.req_int(item, "quantity", 0, None)
        lines.append({"category": category, "amount_cents": amount_cents, "quantity": quantity})
    return lines


@bp.route("/purchase-transactions", methods=["POST"])
def create_purchase_transaction():
    ctx = middleware.require(("StoreOperator", "ProgramAdmin"))
    payload = shape.body()
    member_id = shape.req_str(payload, "member_id")
    site_id = shape.req_str(payload, "site_id")
    transacted_at = shape.req_ts(payload, "transacted_at")
    lines = _parse_lines(payload)

    member = core.fetch("members", member_id)
    site = core.fetch("sites", site_id)

    middleware.own_site(ctx, site["id"])

    if site["site_type"] != "GROCERY":
        raise ApiError("ERR_GROCERY_SITE_REQUIRED",
                       "a basket may only be recorded at a GROCERY site")

    transaction = core.new_entity()
    transaction.update({
        "member_id": member["id"],
        "site_id": site["id"],
        "transacted_at": transacted_at,
        "lines": lines,
        "subtotal_cents": sum(line["amount_cents"] for line in lines),
        "posting_status": "RECORDED",
        "accrual_status": "NOT_ACCRUED",
        "gross_points_awarded": 0,
        "line_points_breakdown": [],
        "applied_promo_event_ids": [],
        "posted_at": None,
        "voided_at": None,
    })
    db.purchase_transactions[transaction["id"]] = transaction
    return response.object_response(serializers.purchase_transaction(transaction), 201)


@bp.route("/purchase-transactions/<transaction_id>", methods=["GET"])
def get_purchase_transaction(transaction_id):
    ctx = middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor",
                              "StoreOperator", "Member"))
    transaction = core.fetch("purchase_transactions", transaction_id)
    del ctx
    return response.object_response(serializers.purchase_transaction(transaction))


@bp.route("/purchase-transactions", methods=["GET"])
def list_purchase_transactions():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "StoreOperator"))
    shape.pagination()
    member_id = shape.arg_str("member_id")
    site_id = shape.arg_str("site_id")
    posting_status = shape.arg_enum("posting_status", POSTING_STATUSES)
    accrual_status = shape.arg_enum("accrual_status", ACCRUAL_STATUSES)
    rows = list(db.purchase_transactions.values())
    if member_id is not None:
        rows = [t for t in rows if t["member_id"] == member_id]
    if site_id is not None:
        rows = [t for t in rows if t["site_id"] == site_id]
    if posting_status is not None:
        rows = [t for t in rows if t["posting_status"] == posting_status]
    if accrual_status is not None:
        rows = [t for t in rows if t["accrual_status"] == accrual_status]
    return listing(rows, serializers.purchase_transaction, order=core.order_key)


@bp.route("/purchase-transactions/<transaction_id>/post", methods=["POST"])
def post_purchase_transaction(transaction_id):
    ctx = middleware.require(("StoreOperator", "ProgramAdmin"))
    transaction = core.fetch("purchase_transactions", transaction_id)
    middleware.own_site(ctx, transaction["site_id"])

    member = db.members[transaction["member_id"]]
    site = db.sites[transaction["site_id"]]
    banner = db.banners[member["banner_id"]]

    if banner["status"] != "ACTIVE":
        raise ApiError("ERR_BANNER_SUSPENDED", "banner %s is SUSPENDED" % banner["id"])
    if site["status"] != "ACTIVE":
        raise ApiError("ERR_SITE_SUSPENDED", "site %s is SUSPENDED" % site["id"])
    if transaction["posting_status"] != "RECORDED" \
            or transaction["accrual_status"] != "NOT_ACCRUED":
        raise invalid_state("only a RECORDED / NOT_ACCRUED basket may be posted "
                            "(current %s / %s)"
                            % (transaction["posting_status"], transaction["accrual_status"]))
    cycle = core.require_open_cycle(banner["id"])
    next_cycle = core.require_next_cycle(cycle)

    gross, breakdown, promo_ids = calc.purchase_point_accrual(banner, transaction)

    transaction["gross_points_awarded"] = gross
    transaction["line_points_breakdown"] = breakdown
    transaction["applied_promo_event_ids"] = promo_ids
    transaction["posting_status"] = "POSTED"
    transaction["posted_at"] = clock.now()
    transaction["accrual_status"] = "ACCRUED"
    core.bump(transaction)

    entry = core.add_entry(member["id"], cycle["id"], "ACCRUAL", gross,
                           "PURCHASE_TRANSACTION", transaction["id"],
                           lot_expires_at=next_cycle["closes_at"])
    if entry is not None:
        core.bump(member)

    return response.object_response(serializers.purchase_transaction(transaction))


@bp.route("/purchase-transactions/<transaction_id>/void", methods=["POST"])
def void_purchase_transaction(transaction_id):
    ctx = middleware.require(("StoreOperator", "ProgramAdmin"))
    transaction = core.fetch("purchase_transactions", transaction_id)
    middleware.own_site(ctx, transaction["site_id"])

    member = db.members[transaction["member_id"]]

    posting = transaction["posting_status"]
    if posting == "RECORDED":
        # Branch A: a bare status flip, no ledger row at all.
        transaction["posting_status"] = "VOIDED"
        transaction["voided_at"] = clock.now()
        core.bump(transaction)
        return response.object_response(serializers.purchase_transaction(transaction))

    if posting != "POSTED" or transaction["accrual_status"] != "ACCRUED":
        raise invalid_state("only a RECORDED or a POSTED / ACCRUED basket may be voided "
                            "(current %s / %s)" % (posting, transaction["accrual_status"]))

    accrual_row = core.accrual_entry_of(transaction["id"])
    accrual_cycle = None
    if accrual_row is not None:
        accrual_cycle = db.point_cycles.get(accrual_row["point_cycle_id"])
        if accrual_cycle is None or accrual_cycle["status"] != "OPEN":
            raise ApiError("ERR_CYCLE_NOT_OPEN",
                           "the cycle carrying this basket's ACCRUAL row is no longer OPEN")

    # hop 1
    transaction["posting_status"] = "VOIDED"
    transaction["voided_at"] = clock.now()
    transaction["accrual_status"] = "REVERSED"
    core.bump(transaction)

    # hop 2
    reversal_cycle = core.cycle_for_clock(member["banner_id"])
    reversal_cycle_id = reversal_cycle["id"] if reversal_cycle is not None else (
        accrual_cycle["id"] if accrual_cycle is not None else None)
    entry = core.add_entry(member["id"], reversal_cycle_id, "REVERSAL",
                           -transaction["gross_points_awarded"],
                           "PURCHASE_TRANSACTION", transaction["id"])
    if entry is not None:
        core.bump(member)

    # hop 3
    voided = core.repair_overdraw(member)

    # hops 4 and 5
    if voided:
        household = core.oldest_active_household(member["id"])
        if household is not None:
            for _redemption in voided:
                core.raise_system_signal(household, "OVERDRAWN_AUTH", 40)

    return response.object_response(serializers.purchase_transaction(transaction))


# -------------------------------------------------------------------- ledger

@bp.route("/point-ledger-entries/<entry_id>", methods=["GET"])
def get_ledger_entry(entry_id):
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "Member"))
    entry = core.fetch("ledger_entries", entry_id)
    return response.object_response(serializers.ledger_entry(entry))


@bp.route("/point-ledger-entries", methods=["GET"])
def list_ledger_entries():
    middleware.require(("ProgramAdmin", "LoyaltyAnalyst", "LoyaltySupervisor", "Member"))
    shape.pagination()
    member_id = shape.arg_str("member_id")
    point_cycle_id = shape.arg_str("point_cycle_id")
    entry_type = shape.arg_enum("entry_type", ENTRY_TYPES)
    source_kind = shape.arg_enum("source_kind", SOURCE_KINDS)
    rows = list(db.ledger_entries.values())
    if member_id is not None:
        rows = [e for e in rows if e["member_id"] == member_id]
    if point_cycle_id is not None:
        rows = [e for e in rows if e["point_cycle_id"] == point_cycle_id]
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    if source_kind is not None:
        rows = [e for e in rows if e["source_kind"] == source_kind]
    return listing(rows, serializers.ledger_entry, order=core.order_key)


# ----------------------------------------------------------------- transfers

@bp.route("/point-transfers", methods=["POST"])
def create_point_transfer():
    ctx = middleware.require(("Member", "LoyaltyAnalyst", "ProgramAdmin"))
    payload = shape.body()
    member_id = shape.req_str(payload, "member_id")
    recipient_member_id = shape.req_str(payload, "recipient_member_id")
    points = shape.req_int(payload, "points")

    sender = core.fetch("members", member_id)
    recipient = core.fetch("members", recipient_member_id)

    middleware.own_member(ctx, sender["id"])

    core.assert_no_frozen_household(sender["id"])

    banner = db.banners[sender["banner_id"]]
    if banner["status"] != "ACTIVE":
        raise ApiError("ERR_BANNER_SUSPENDED", "banner %s is SUSPENDED" % banner["id"])

    cycle = core.require_open_cycle(banner["id"])

    if core.fraud_locked(sender["id"]):
        raise ApiError("ERR_TRANSFER_FRAUD_LOCK",
                       "the sender's household is locked by open fraud signals")

    household = None
    if recipient["id"] != sender["id"]:
        household = core.shared_household(sender["id"], recipient["id"])
    if household is None:
        raise ApiError("ERR_RECIPIENT_NOT_IN_HOUSEHOLD",
                       "the recipient does not hold an ACTIVE linkage to a household of the "
                       "sender")

    block = banner["points_per_discount_block"]
    if points <= 0 or points % block != 0:
        raise ApiError("ERR_INVALID_TRANSFER_AMOUNT",
                       "'points' must be a positive whole multiple of %d" % block)

    limit = banner["max_transfers_per_cycle"]
    used = core.transfer_out_count(household["id"], cycle["id"])
    if used >= limit:
        raise ApiError("ERR_TRANSFER_LIMIT_EXCEEDED",
                       "household %s has already recorded %d transfers this cycle"
                       % (household["id"], used))

    if core.available_points(sender["id"]) < points:
        raise ApiError("ERR_INSUFFICIENT_POINTS",
                       "the sender's available_points is below the requested transfer")

    inherited_expiry = core.earliest_unconsumed_lot_expiry(sender["id"], banner["expiry_basis"])

    out_row = core.add_entry(sender["id"], cycle["id"], "TRANSFER_OUT", -points,
                             "POINT_TRANSFER", None)
    out_row["source_ref_id"] = out_row["id"]
    core.bump(sender)

    core.add_entry(recipient["id"], cycle["id"], "TRANSFER_IN", points,
                   "POINT_TRANSFER", out_row["id"],
                   lot_expires_at=inherited_expiry)
    core.bump(recipient)

    if core.transfer_out_count(household["id"], cycle["id"]) >= limit:
        core.raise_system_signal(household, "RAPID_TRANSFER", 25)

    return response.object_response(serializers.ledger_entry(out_row), 201)
