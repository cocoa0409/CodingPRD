"""Invoices, payments, export packets and load-out slots (PRD 3.8, 3.9)."""
from routes.common import (
    ApiError, Blueprint, C, collection_response, db, endpoint, field_currency,
    field_dt, field_enum, field_int, field_str, fetch, invalid_state, json_body,
    new_entity, object_response, pagination, query_enum, query_str,
    require_owner, touch,
)
from middleware import query_required
from response import fmt_dt
from services.calculations import storage_accrual
from services.derive import (
    abandon_invoice, compute_invoice_fields, gross_before_deposit,
    invoice_context, preview_deposit_applied, recompute_bay, recompute_bidder,
    recompute_invoice_paid, recompute_registration_cap,
    refresh_registration_money, stamp_invoice,
)
from services.money import pct

bp = Blueprint("settlement", __name__)


def _invoice_lot(invoice):
    sale = db.sales[invoice["sale_id"]]
    return db.lots[sale["lot_id"]]


def _invoice_auction(invoice):
    sale = db.sales[invoice["sale_id"]]
    return db.auctions[sale["auction_id"]]


# --------------------------------------------------------------------------
# invoices
# --------------------------------------------------------------------------
@bp.get("/invoices/<invoice_id>")
@endpoint("PlatformAdmin", "ComplianceOfficer", "AuctionOperator",
          "SettlementOfficer", "Bidder")
def get_invoice(actor, invoice_id):
    return object_response(fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND"))


@bp.get("/invoices")
@endpoint("PlatformAdmin", "ComplianceOfficer", "AuctionOperator",
          "SettlementOfficer", "Bidder")
def list_invoices(actor):
    limit, offset = pagination()
    sale_id = query_str("sale_id")
    bidder_id = query_str("bidder_id")
    registration_id = query_str("registration_id")
    payment_status = query_enum("payment_status", C.INVOICE_PAYMENT_STATUSES)
    release_status = query_enum("release_status", C.INVOICE_RELEASE_STATUSES)
    rows = list(db.invoices.values())
    if sale_id is not None:
        rows = [i for i in rows if i["sale_id"] == sale_id]
    if bidder_id is not None:
        rows = [i for i in rows if i["bidder_id"] == bidder_id]
    if registration_id is not None:
        rows = [i for i in rows if i["registration_id"] == registration_id]
    if payment_status is not None:
        rows = [i for i in rows if i["payment_status"] == payment_status]
    if release_status is not None:
        rows = [i for i in rows if i["release_status"] == release_status]
    return collection_response(rows, limit, offset)


@bp.get("/invoices/<invoice_id>/settlement-preview")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def settlement_preview(actor, invoice_id):
    variant = query_required("variant")
    if variant not in C.SETTLEMENT_VARIANTS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "variant must be PROVISIONAL or FINAL.")
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    fields = compute_invoice_fields(invoice, variant)
    credit_memo = invoice["credit_memo_cents"]
    gross = gross_before_deposit(fields, credit_memo)
    deposit_applied = preview_deposit_applied(invoice, gross)
    return object_response({
        "invoice_id": invoice["id"],
        "variant": variant,
        "hammer_price_cents": fields["hammer_price_cents"],
        "buyer_premium_cents": fields["buyer_premium_cents"],
        "documentation_fee_cents": fields["documentation_fee_cents"],
        "title_transfer_fee_cents": fields["title_transfer_fee_cents"],
        "financing_fee_cents": fields["financing_fee_cents"],
        "subtotal_cents": fields["subtotal_cents"],
        "tax_rate_applied": fields["tax_rate_applied"],
        "tax_cents": fields["tax_cents"],
        "chargeable_storage_days": fields["chargeable_storage_days"],
        "storage_fee_cents": fields["storage_fee_cents"],
        "credit_memo_cents": credit_memo,
        "deposit_applied_cents": deposit_applied,
        "total_due_cents": gross - deposit_applied,
    })


@bp.post("/invoices/<invoice_id>/finalize")
@endpoint("SettlementOfficer")
def finalize_invoice(actor, invoice_id):
    json_body()
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if invoice["settlement_variant"] != "PROVISIONAL":
        raise invalid_state("This invoice has already been finalised.")
    was_paid = invoice["payment_status"] == "PAID"
    stamp_invoice(invoice, "FINAL")
    if was_paid and invoice["total_due_cents"] > invoice["amount_paid_cents"]:
        invoice["payment_status"] = "PARTIALLY_PAID"
    invoice["outstanding_cents"] = max(
        0, invoice["total_due_cents"] - invoice["amount_paid_cents"])
    touch(invoice)
    recompute_bidder(db.bidders[invoice["bidder_id"]])
    return object_response(invoice)


@bp.post("/invoices/<invoice_id>/fee-waiver")
@endpoint("SettlementOfficer")
def fee_waiver(actor, invoice_id):
    body = json_body()
    waiver = field_int(body, "waiver_cents", required=True, min_value=0)
    field_str(body, "reason", required=True)
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    registration = db.bidder_registrations[invoice["registration_id"]]

    if (registration["credit_approved_by_user_id"] is not None
            and registration["credit_approved_by_user_id"] == actor.user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    ceiling = pct(invoice["subtotal_cents"], C.MAX_WAIVER_PCT)
    if invoice["credit_memo_cents"] + waiver > ceiling:
        raise ApiError("ERR_WAIVER_LIMIT_EXCEEDED")

    invoice["credit_memo_cents"] += waiver
    refresh_registration_money(registration)
    touch(invoice)
    return object_response(invoice)


@bp.post("/invoices/<invoice_id>/authorize-release")
@endpoint("SettlementOfficer")
def authorize_release(actor, invoice_id):
    json_body()
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    sale = db.sales[invoice["sale_id"]]
    lot = db.lots[sale["lot_id"]]

    if invoice["release_status"] != "HELD":
        raise invalid_state("Release has already been decided for this invoice.")
    if sale["status"] not in ("CONFIRMED", "SETTLED"):
        raise invalid_state("The underlying sale is not confirmed.")
    if lot["title_status"] not in C.TITLE_CLEAR_STATUSES:
        raise ApiError("ERR_TITLE_NOT_CLEAR")
    if invoice["payment_status"] != "PAID":
        raise ApiError("ERR_INVOICE_NOT_PAID")
    if invoice["is_cross_border"]:
        cleared = any(
            p["invoice_id"] == invoice["id"] and p["status"] == "EXPORT_CLEARED"
            for p in db.export_packets.values())
        if not cleared:
            raise ApiError("ERR_EXPORT_NOT_CLEARED")

    invoice["release_status"] = "RELEASE_AUTHORIZED"
    touch(invoice)
    return object_response(invoice)


@bp.post("/invoices/<invoice_id>/default")
@endpoint("SettlementOfficer")
def default_invoice(actor, invoice_id):
    json_body()
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if invoice["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise invalid_state("Only an unpaid invoice may be defaulted.")
    if invoice["release_status"] == "LOADED_OUT":
        raise invalid_state("A machine already through the gate cannot be defaulted.")
    if not (invoice["payment_due_at"] and db.now() > invoice["payment_due_at"]):
        raise ApiError("ERR_PAYMENT_NOT_OVERDUE")
    invoice["payment_status"] = "IN_DEFAULT"
    touch(invoice)
    recompute_bidder(db.bidders[invoice["bidder_id"]])
    return object_response(invoice)


@bp.post("/invoices/<invoice_id>/abandon")
@endpoint("SettlementOfficer")
def abandon(actor, invoice_id):
    body = json_body()
    field_str(body, "reason", required=True)
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if invoice["payment_status"] != "IN_DEFAULT":
        raise invalid_state("Only an invoice IN_DEFAULT may be abandoned.")
    if invoice["release_status"] not in ("HELD", "RELEASE_AUTHORIZED",
                                        "LOADOUT_BOOKED"):
        raise invalid_state("This invoice may no longer be abandoned.")
    abandon_invoice(invoice)
    return object_response(invoice)


@bp.get("/invoices/<invoice_id>/payments")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def list_invoice_payments(actor, invoice_id):
    limit, offset = pagination()
    status = query_enum("status", C.PAYMENT_STATUSES)
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    rows = [p for p in db.payments.values() if p["invoice_id"] == invoice["id"]]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return collection_response(rows, limit, offset)


@bp.get("/invoices/<invoice_id>/export-packets")
@endpoint("PlatformAdmin", "ComplianceOfficer", "AuctionOperator",
          "SettlementOfficer", "Bidder")
def list_invoice_packets(actor, invoice_id):
    limit, offset = pagination()
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    rows = [p for p in db.export_packets.values()
            if p["invoice_id"] == invoice["id"]]
    return collection_response(rows, limit, offset)


# --------------------------------------------------------------------------
# payments
# --------------------------------------------------------------------------
@bp.post("/payments")
@endpoint("Bidder")
def create_payment(actor):
    body = json_body()
    invoice_id = field_str(body, "invoice_id", required=True)
    amount = field_int(body, "amount_cents", required=True, min_value=1,
                       max_value=1000000000)
    method = field_enum(body, "method", C.PAYMENT_METHODS, required=True)
    currency_code = field_currency(body, "currency_code", required=True)

    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    require_owner(actor, invoice["bidder_id"])

    if invoice["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
        raise invalid_state("This invoice is not accepting payments.")
    if amount > invoice["outstanding_cents"]:
        raise ApiError("ERR_OVERPAYMENT")
    yard = db.yards[_invoice_auction(invoice)["yard_id"]]
    if currency_code != yard["currency_code"]:
        raise ApiError("ERR_CURRENCY_MISMATCH")

    payment = new_entity(versioned=False)
    payment.update({
        "invoice_id": invoice["id"],
        "amount_cents": amount,
        "method": method,
        "currency_code": currency_code,
        "status": "SETTLED",
        "received_at": db.now(),
    })
    db.payments[payment["id"]] = payment

    recompute_invoice_paid(invoice)
    if invoice["outstanding_cents"] <= 0:
        invoice["payment_status"] = "PAID"
    else:
        invoice["payment_status"] = "PARTIALLY_PAID"
    touch(invoice)
    # PRD 3.5: "This forecast is restamped on the registration whenever any
    # invoice of the registration is written, so `bid_cap_cents` tracks the
    # money actually owed."  A payment writes the invoice.
    recompute_registration_cap(db.bidder_registrations[invoice["registration_id"]])
    recompute_bidder(db.bidders[invoice["bidder_id"]])
    return object_response(payment, 201)


@bp.get("/payments/<payment_id>")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def get_payment(actor, payment_id):
    return object_response(fetch(db.payments, payment_id, "ERR_PAYMENT_NOT_FOUND"))


# --------------------------------------------------------------------------
# export document packets
# --------------------------------------------------------------------------
@bp.post("/export-packets")
@endpoint("ComplianceOfficer")
def create_export_packet(actor):
    body = json_body()
    invoice_id = field_str(body, "invoice_id", required=True)
    destination = field_str(body, "destination_country_code", required=True,
                            min_len=2, max_len=2, pattern=r"^[A-Z]{2}$")
    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    bidder = db.bidders[invoice["bidder_id"]]

    if bidder["country_code"] in C.EMBARGOED_COUNTRY_CODES:
        raise ApiError("ERR_COUNTRY_EMBARGOED")
    if destination != bidder["country_code"] or not invoice["is_cross_border"]:
        raise ApiError("ERR_DESTINATION_COUNTRY_MISMATCH")

    packet = new_entity()
    packet.update({
        "invoice_id": invoice["id"],
        "destination_country_code": destination,
        "title_document_ref": None,
        "customs_entry_ref": None,
        "rejection_reason": None,
        "reopen_count": 0,
        "status": "PREPARING",
    })
    db.export_packets[packet["id"]] = packet
    return object_response(packet, 201)


@bp.get("/export-packets/<packet_id>")
@endpoint("PlatformAdmin", "ComplianceOfficer", "SettlementOfficer", "Bidder")
def get_export_packet(actor, packet_id):
    return object_response(
        fetch(db.export_packets, packet_id, "ERR_EXPORT_PACKET_NOT_FOUND"))


@bp.post("/export-packets/<packet_id>/transition")
@endpoint("ComplianceOfficer")
def transition_export_packet(actor, packet_id):
    body = json_body()
    action = field_enum(body, "action", C.PACKET_ACTIONS, required=True)
    title_ref = field_str(body, "title_document_ref", nullable=True, default=None)
    customs_ref = field_str(body, "customs_entry_ref", nullable=True, default=None)
    rejection_reason = field_str(body, "rejection_reason", nullable=True,
                                 default=None)

    packet = fetch(db.export_packets, packet_id, "ERR_EXPORT_PACKET_NOT_FOUND")
    invoice = db.invoices[packet["invoice_id"]]
    status = packet["status"]

    if action == "ATTACH_TITLE":
        if status != "PREPARING":
            raise invalid_state("A title may only be attached while PREPARING.")
        if not title_ref:
            raise invalid_state("title_document_ref is required to attach a title.")
        lot = _invoice_lot(invoice)
        if lot["title_status"] not in C.TITLE_CLEAR_STATUSES:
            raise ApiError("ERR_TITLE_NOT_CLEAR")
        packet["title_document_ref"] = title_ref
        packet["status"] = "TITLE_ATTACHED"
    elif action == "FILE_CUSTOMS":
        if status != "TITLE_ATTACHED":
            raise invalid_state("Customs may only be filed once the title is attached.")
        if not customs_ref:
            raise invalid_state("customs_entry_ref is required to file customs.")
        packet["customs_entry_ref"] = customs_ref
        packet["status"] = "CUSTOMS_FILED"
    elif action == "CLEAR":
        if status != "CUSTOMS_FILED":
            raise invalid_state("Only a filed packet may be cleared.")
        packet["status"] = "EXPORT_CLEARED"
    elif action == "REJECT":
        if status != "CUSTOMS_FILED":
            raise invalid_state("Only a filed packet may be rejected.")
        if not rejection_reason:
            raise invalid_state("rejection_reason is required to reject a packet.")
        packet["rejection_reason"] = rejection_reason
        packet["status"] = "CUSTOMS_REJECTED"
    else:  # REOPEN
        if status != "CUSTOMS_REJECTED":
            raise invalid_state("Only a rejected packet may be reopened.")
        if packet["reopen_count"] >= C.MAX_PACKET_REOPENS:
            raise ApiError("ERR_MAX_PACKET_REOPENS_EXCEEDED")
        packet["reopen_count"] += 1
        packet["title_document_ref"] = None
        packet["customs_entry_ref"] = None
        packet["status"] = "PREPARING"

    touch(packet)
    return object_response(packet)


# --------------------------------------------------------------------------
# load-out slots
# --------------------------------------------------------------------------
def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [start, end)."""
    return a_start < b_end and b_start < a_end


@bp.post("/loadout-slots")
@endpoint("Bidder")
def create_loadout_slot(actor):
    body = json_body()
    invoice_id = field_str(body, "invoice_id", required=True)
    bay_id = field_str(body, "bay_id", required=True)
    expected_version = field_int(body, "expected_invoice_version", required=True,
                                 min_value=0)
    slot_start = field_dt(body, "slot_start", required=True)
    slot_end = field_dt(body, "slot_end", required=True)
    transport_mode = field_enum(body, "transport_mode", C.TRANSPORT_MODES,
                                required=True)
    tonnage_kg = field_int(body, "tonnage_kg", nullable=True, min_value=1,
                           default=None)
    if slot_end <= slot_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "slot_end must be strictly after slot_start.")

    invoice = fetch(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")
    bay = fetch(db.loadout_bays, bay_id, "ERR_LOADOUT_BAY_NOT_FOUND")
    lot = _invoice_lot(invoice)
    auction = _invoice_auction(invoice)

    if tonnage_kg is None:
        tonnage_kg = lot["weight_kg"]
    elif tonnage_kg > lot["weight_kg"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "tonnage_kg may not exceed the lot's weight_kg.")

    require_owner(actor, invoice["bidder_id"])

    if expected_version != invoice["version"]:
        raise ApiError("ERR_STALE_INVOICE_VERSION")

    if invoice["release_status"] not in ("RELEASE_AUTHORIZED", "LOADOUT_BOOKED"):
        raise invalid_state("Release has not been authorised for this invoice.")

    superseded = None
    if invoice["release_status"] == "LOADOUT_BOOKED":
        booked = [s for s in db.loadout_slots.values()
                  if s["invoice_id"] == invoice["id"] and s["status"] == "BOOKED"]
        if len(booked) != 1:
            raise invalid_state(
                "Rebooking requires exactly one BOOKED slot on the invoice.")
        superseded = booked[0]

    # rung 22 / 30
    if bay["yard_id"] != auction["yard_id"]:
        raise ApiError("ERR_BAY_YARD_MISMATCH")
    if not bay["is_active"]:
        raise ApiError("ERR_BAY_INACTIVE")

    # rung 31 — aggregate crane tonnage over time-overlapping live slots
    reserved = 0
    for slot in db.loadout_slots.values():
        if slot["bay_id"] != bay["id"]:
            continue
        if slot["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        if superseded is not None and slot["id"] == superseded["id"]:
            continue
        if _overlaps(slot_start, slot_end, slot["slot_start"], slot["slot_end"]):
            reserved += slot["tonnage_kg"] or 0
    if reserved + tonnage_kg > bay["crane_capacity_kg"]:
        raise ApiError("ERR_BAY_CAPACITY_EXCEEDED")

    # rung 33 — interval rules
    for slot in db.loadout_slots.values():
        if slot["invoice_id"] != invoice["id"]:
            continue
        if slot["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        if _overlaps(slot_start, slot_end, slot["slot_start"], slot["slot_end"]):
            raise ApiError("ERR_SLOT_OVERLAP")
    if slot_start < auction["window_end"] or slot_end > auction["loadout_deadline_at"]:
        raise ApiError("ERR_SLOT_OUTSIDE_DEADLINE")

    # every validation passed — only now is the prior booking superseded
    if superseded is not None:
        superseded["status"] = "CANCELLED"
        superseded["cancel_reason"] = "SUPERSEDED"
        touch(superseded)

    slot = new_entity()
    slot.update({
        "invoice_id": invoice["id"],
        "bay_id": bay["id"],
        "slot_start": slot_start,
        "slot_end": slot_end,
        "tonnage_kg": tonnage_kg,
        "transport_mode": transport_mode,
        "gate_pass_ref": None,
        "supersedes_slot_id": superseded["id"] if superseded else None,
        "cancel_reason": None,
        "status": "BOOKED",
    })
    db.loadout_slots[slot["id"]] = slot

    recompute_bay(bay)
    if superseded is not None:
        prior_bay = db.loadout_bays.get(superseded["bay_id"])
        if prior_bay is not None:
            recompute_bay(prior_bay)

    invoice["release_status"] = "LOADOUT_BOOKED"
    touch(invoice)
    return object_response(slot, 201)


@bp.get("/loadout-slots/<slot_id>")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def get_loadout_slot(actor, slot_id):
    return object_response(
        fetch(db.loadout_slots, slot_id, "ERR_LOADOUT_SLOT_NOT_FOUND"))


@bp.get("/loadout-slots")
@endpoint("PlatformAdmin", "AuctionOperator", "SettlementOfficer", "Bidder")
def list_loadout_slots(actor):
    limit, offset = pagination()
    invoice_id = query_str("invoice_id")
    bay_id = query_str("bay_id")
    status = query_enum("status", C.SLOT_STATUSES)
    supersedes = query_str("supersedes_slot_id")
    rows = list(db.loadout_slots.values())
    if invoice_id is not None:
        rows = [s for s in rows if s["invoice_id"] == invoice_id]
    if bay_id is not None:
        rows = [s for s in rows if s["bay_id"] == bay_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if supersedes is not None:
        rows = [s for s in rows if s["supersedes_slot_id"] == supersedes]
    return collection_response(rows, limit, offset)


@bp.post("/loadout-slots/<slot_id>/check-in")
@endpoint("Bidder")
def check_in_slot(actor, slot_id):
    json_body()
    slot = fetch(db.loadout_slots, slot_id, "ERR_LOADOUT_SLOT_NOT_FOUND")
    invoice = db.invoices[slot["invoice_id"]]
    require_owner(actor, invoice["bidder_id"])
    if slot["status"] != "BOOKED":
        raise invalid_state("Only a BOOKED slot may be checked in.")
    now = db.now()
    if not (slot["slot_start"] <= now < slot["slot_end"]):
        raise ApiError("ERR_SLOT_NOT_IN_WINDOW")
    slot["status"] = "CHECKED_IN"
    touch(slot)
    recompute_bay(db.loadout_bays[slot["bay_id"]])
    return object_response(slot)


@bp.post("/loadout-slots/<slot_id>/complete")
@endpoint("SettlementOfficer")
def complete_slot(actor, slot_id):
    body = json_body()
    gate_pass_ref = field_str(body, "gate_pass_ref", required=True)
    slot = fetch(db.loadout_slots, slot_id, "ERR_LOADOUT_SLOT_NOT_FOUND")
    invoice = db.invoices[slot["invoice_id"]]
    if slot["status"] != "CHECKED_IN":
        raise invalid_state("Only a CHECKED_IN slot may be completed.")
    if invoice["release_status"] != "LOADOUT_BOOKED":
        raise invalid_state("The invoice is not awaiting load-out.")

    slot["status"] = "COMPLETED"
    slot["gate_pass_ref"] = gate_pass_ref
    touch(slot)

    invoice["release_status"] = "LOADED_OUT"
    touch(invoice)

    lot = _invoice_lot(invoice)
    if lot["lifecycle_status"] == "SETTLED":
        lot["lifecycle_status"] = "RELEASED"
        touch(lot)

    recompute_bay(db.loadout_bays[slot["bay_id"]])
    recompute_bidder(db.bidders[invoice["bidder_id"]])
    return object_response(slot)


@bp.post("/loadout-slots/<slot_id>/cancel")
@endpoint("SettlementOfficer", "Bidder")
def cancel_slot(actor, slot_id):
    body = json_body()
    outcome = field_enum(body, "outcome", C.SLOT_OUTCOMES, required=True)
    cancel_reason = field_str(body, "cancel_reason", nullable=True, default=None)

    slot = fetch(db.loadout_slots, slot_id, "ERR_LOADOUT_SLOT_NOT_FOUND")
    invoice = db.invoices[slot["invoice_id"]]
    if actor.role == "Bidder":
        require_owner(actor, invoice["bidder_id"])
        if outcome == "NO_SHOW":
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "Recording a no-show is a SettlementOfficer action.")
        if slot["status"] == "CHECKED_IN":
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "Cancelling a checked-in slot is a SettlementOfficer action.")

    if outcome == "CANCELLED":
        if slot["status"] not in ("BOOKED", "CHECKED_IN"):
            raise invalid_state("This slot may no longer be cancelled.")
    else:
        if slot["status"] != "BOOKED":
            raise invalid_state("Only a BOOKED slot may be marked as a no-show.")
        if db.now() < slot["slot_end"]:
            raise ApiError("ERR_SLOT_NOT_IN_WINDOW")

    slot["status"] = outcome
    if cancel_reason is not None:
        slot["cancel_reason"] = cancel_reason
    touch(slot)
    recompute_bay(db.loadout_bays[slot["bay_id"]])

    remaining = [s for s in db.loadout_slots.values()
                 if s["invoice_id"] == invoice["id"]
                 and s["status"] in ("BOOKED", "CHECKED_IN")]
    if not remaining and invoice["release_status"] == "LOADOUT_BOOKED":
        invoice["release_status"] = "RELEASE_AUTHORIZED"
        touch(invoice)
    return object_response(slot)
