"""Load lifecycle: tender → carrier-accept → depart → deliver → invoice."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_ACCESSORIAL_PENDING,
    ERR_CARRIER_NOT_FOUND,
    ERR_CARRIER_NOT_QUALIFIED,
    ERR_INSURANCE_EXPIRED,
    ERR_INVALID_DELIVERY_TIMES,
    ERR_LOAD_NOT_ACCEPTED,
    ERR_LOAD_NOT_CANCELLABLE,
    ERR_LOAD_NOT_DELIVERED,
    ERR_LOAD_NOT_FOUND,
    ERR_LOAD_NOT_IN_TRANSIT,
    ERR_LOAD_NOT_TENDERED,
    ERR_QUOTE_NOT_ACCEPTED,
    ERR_QUOTE_REQUEST_NOT_FOUND,
    ERR_SHIPPER_NOT_FOUND,
    ERR_SMARTWAY_REQUIRED,
)
from ..helpers import (
    check_version,
    ensure_carrier_self_access,
    ensure_shipper_self_access,
    get_body,
    get_brokerage_or_404,
    get_scoped,
    require_field,
    require_iso,
)
from ..services.calc import detention_cents
from ..services.cascade import maybe_auto_settle, recompute_invoice_balance
from ..store import store
from ..timeutil import iso_now, parse_iso


loads_bp = Blueprint("loads", __name__, url_prefix="/brokerages")


# ---------------------------------------------------------------------------
# Tender
# ---------------------------------------------------------------------------
@loads_bp.post("/<brokerage_id>/shippers/<shipper_id>/loads")
@require_auth(["BrokerOps"])
def tender_load(brokerage_id, shipper_id):
    body = get_body()
    quote_request_id = require_field(body, "quote_request_id", str)
    carrier_id = require_field(body, "carrier_id", str)

    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        s = get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)

        q = get_scoped(store.quote_requests, quote_request_id, brokerage_id, ERR_QUOTE_REQUEST_NOT_FOUND)
        if q.get("shipper_id") != shipper_id:
            raise ApiError(ERR_QUOTE_REQUEST_NOT_FOUND, 404, "Quote request not found for this shipper.")

        carrier = get_scoped(store.carriers, carrier_id, brokerage_id, ERR_CARRIER_NOT_FOUND)

        if q.get("status") != "ACCEPTED":
            raise ApiError(ERR_QUOTE_NOT_ACCEPTED, 409, "Quote request not in ACCEPTED.")

        # Combined carrier gate (validations priority 6→8)
        if carrier.get("status") != "QUALIFIED":
            raise ApiError(ERR_CARRIER_NOT_QUALIFIED, 409, "Carrier not in QUALIFIED.")
        clock_now = parse_iso(bk["clock_now_iso"])
        if parse_iso(carrier["insurance_expires_on"]) <= clock_now:
            raise ApiError(ERR_INSURANCE_EXPIRED, 409, "Carrier insurance expired.")
        if bool(s.get("smartway_required")) and not bool(carrier.get("smartway_certified")):
            raise ApiError(ERR_SMARTWAY_REQUIRED, 409, "Carrier is not SmartWay certified.")

        ld = {
            "shipper_id": shipper_id,
            "brokerage_id": brokerage_id,
            "quote_request_id": quote_request_id,
            "carrier_id": carrier_id,
            "rate_source": q.get("rate_source"),
            "linehaul_cents": int(q.get("quoted_linehaul_cents") or 0),
            "provisional_detention_cents": 0,
            "final_detention_cents": None,
            "accessorial_total_cents": 0,
            "actual_arrive_at": None,
            "actual_depart_at": None,
            "status": "TENDERED",
        }
        store.stamp_create(ld)
        store.loads[ld["id"]] = ld
    return ok_object(ld, status=201)


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------
@loads_bp.get("/<brokerage_id>/shippers/<shipper_id>/loads/<load_id>")
@require_auth(["BrokerOps", "ShipperUser", "CarrierUser"])
def get_load(brokerage_id, shipper_id, load_id):
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        # Shipper self-access for ShipperUser
        ensure_shipper_self_access(shipper_id)
        ld = get_scoped(store.loads, load_id, brokerage_id, ERR_LOAD_NOT_FOUND)
        if ld.get("shipper_id") != shipper_id:
            raise ApiError(ERR_LOAD_NOT_FOUND, 404, "Load not found for this shipper.")
        # CarrierUser must be the assigned carrier
        ensure_carrier_self_access(ld.get("carrier_id"))
    return ok_object(ld)


# ---------------------------------------------------------------------------
# Carrier accept
# ---------------------------------------------------------------------------
@loads_bp.post("/<brokerage_id>/shippers/<shipper_id>/loads/<load_id>/carrier-accept")
@require_auth(["CarrierUser"])
def carrier_accept(brokerage_id, shipper_id, load_id):
    body = get_body()
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        s = get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ld = get_scoped(store.loads, load_id, brokerage_id, ERR_LOAD_NOT_FOUND)
        if ld.get("shipper_id") != shipper_id:
            raise ApiError(ERR_LOAD_NOT_FOUND, 404, "Load not found for this shipper.")
        ensure_carrier_self_access(ld.get("carrier_id"))
        check_version(ld, body)

        if ld.get("status") != "TENDERED":
            raise ApiError(ERR_LOAD_NOT_TENDERED, 409, "Load not in TENDERED.")

        carrier = store.carriers.get(ld["carrier_id"])
        if carrier is None:
            raise ApiError(ERR_CARRIER_NOT_FOUND, 404, "Carrier not found.")
        if carrier.get("status") != "QUALIFIED":
            raise ApiError(ERR_CARRIER_NOT_QUALIFIED, 409, "Carrier not in QUALIFIED.")
        clock_now = parse_iso(bk["clock_now_iso"])
        if parse_iso(carrier["insurance_expires_on"]) <= clock_now:
            raise ApiError(ERR_INSURANCE_EXPIRED, 409, "Carrier insurance expired.")
        if bool(s.get("smartway_required")) and not bool(carrier.get("smartway_certified")):
            raise ApiError(ERR_SMARTWAY_REQUIRED, 409, "Carrier is not SmartWay certified.")

        ld["status"] = "ACCEPTED"
        store.bump(ld)
    return ok_object(ld)


# ---------------------------------------------------------------------------
# Depart
# ---------------------------------------------------------------------------
@loads_bp.post("/<brokerage_id>/shippers/<shipper_id>/loads/<load_id>/depart")
@require_auth(["CarrierUser"])
def depart(brokerage_id, shipper_id, load_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ld = get_scoped(store.loads, load_id, brokerage_id, ERR_LOAD_NOT_FOUND)
        if ld.get("shipper_id") != shipper_id:
            raise ApiError(ERR_LOAD_NOT_FOUND, 404, "Load not found for this shipper.")
        ensure_carrier_self_access(ld.get("carrier_id"))
        check_version(ld, body)

        if ld.get("status") != "ACCEPTED":
            raise ApiError(ERR_LOAD_NOT_ACCEPTED, 409, "Load not in ACCEPTED.")
        ld["status"] = "IN_TRANSIT"
        store.bump(ld)
    return ok_object(ld)


# ---------------------------------------------------------------------------
# Deliver
# ---------------------------------------------------------------------------
@loads_bp.post("/<brokerage_id>/shippers/<shipper_id>/loads/<load_id>/deliver")
@require_auth(["CarrierUser"])
def deliver(brokerage_id, shipper_id, load_id):
    body = get_body()
    arrive = require_iso(body, "actual_arrive_at")
    depart_at = require_iso(body, "actual_depart_at")
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ld = get_scoped(store.loads, load_id, brokerage_id, ERR_LOAD_NOT_FOUND)
        if ld.get("shipper_id") != shipper_id:
            raise ApiError(ERR_LOAD_NOT_FOUND, 404, "Load not found for this shipper.")
        ensure_carrier_self_access(ld.get("carrier_id"))
        check_version(ld, body)

        if ld.get("status") != "IN_TRANSIT":
            raise ApiError(ERR_LOAD_NOT_IN_TRANSIT, 409, "Load not in IN_TRANSIT.")

        if depart_at < arrive:
            raise ApiError(ERR_INVALID_DELIVERY_TIMES, 422, "actual_depart_at < actual_arrive_at.")

        ld["actual_arrive_at"] = iso_now(arrive)
        ld["actual_depart_at"] = iso_now(depart_at)
        provisional = detention_cents(
            arrive=arrive,
            depart=depart_at,
            free_minutes=int(bk["detention_free_minutes"]),
            rate_cents_per_15min=int(bk["detention_rate_cents_per_15min"]),
        )
        ld["provisional_detention_cents"] = int(provisional)
        ld["status"] = "DELIVERED"
        store.bump(ld)
    return ok_object(ld)


# ---------------------------------------------------------------------------
# Invoice (DELIVERED → INVOICED, creates Invoice row)
# ---------------------------------------------------------------------------
@loads_bp.post("/<brokerage_id>/shippers/<shipper_id>/loads/<load_id>/invoice")
@require_auth(["BrokerOps"])
def invoice_load(brokerage_id, shipper_id, load_id):
    body = get_body()
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        shipper = get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ld = get_scoped(store.loads, load_id, brokerage_id, ERR_LOAD_NOT_FOUND)
        if ld.get("shipper_id") != shipper_id:
            raise ApiError(ERR_LOAD_NOT_FOUND, 404, "Load not found for this shipper.")
        check_version(ld, body)

        if ld.get("status") != "DELIVERED":
            raise ApiError(ERR_LOAD_NOT_DELIVERED, 409, "Load not in DELIVERED.")

        # All accessorials must be APPROVED or DENIED (no REQUESTED)
        approved_total = 0
        for ac in store.accessorial_charges.values():
            if ac.get("load_id") != load_id:
                continue
            if ac.get("status") == "REQUESTED":
                raise ApiError(ERR_ACCESSORIAL_PENDING, 409, "Pending accessorial on load.")
            if ac.get("status") == "APPROVED":
                approved_total += int(ac.get("amount_cents", 0))

        # Final detention recomputation with latest brokerage settings.
        arrive = parse_iso(ld["actual_arrive_at"])
        depart_at = parse_iso(ld["actual_depart_at"])
        final = detention_cents(
            arrive=arrive,
            depart=depart_at,
            free_minutes=int(bk["detention_free_minutes"]),
            rate_cents_per_15min=int(bk["detention_rate_cents_per_15min"]),
        )
        ld["final_detention_cents"] = int(final)
        ld["accessorial_total_cents"] = int(approved_total)

        # Create the Invoice row (immutable financial record per PRD §2.4 —
        # no version field, no updated_at).
        linehaul = int(ld.get("linehaul_cents") or 0)
        detention_total = int(final)
        accessorial = int(approved_total)
        total = linehaul + detention_total + accessorial

        from ..store import new_id

        invoice = {
            "id": new_id(),
            "created_at": iso_now(),
            "load_id": load_id,
            "shipper_id": shipper_id,
            "brokerage_id": brokerage_id,
            "linehaul_cents": linehaul,
            "detention_cents": detention_total,
            "accessorial_cents": accessorial,
            "invoice_total_cents": total,
            "original_invoice_total_cents": total,
            "amount_paid_cents": 0,
            "amount_credited_cents": 0,
            "balance_due_cents": total,
            "factoring_status": "NOT_FACTORED",
            "settlement_status": "ISSUED",
        }
        store.invoices[invoice["id"]] = invoice

        # Update shipper's outstanding by full invoice total
        shipper["outstanding_invoiced_cents"] = int(shipper.get("outstanding_invoiced_cents", 0)) + total
        store.bump(shipper)

        ld["status"] = "INVOICED"
        store.bump(ld)
    return ok_object(invoice, status=201)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@loads_bp.post("/<brokerage_id>/shippers/<shipper_id>/loads/<load_id>/cancel")
@require_auth(["BrokerOps", "ShipperUser"])
def cancel_load(brokerage_id, shipper_id, load_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ensure_shipper_self_access(shipper_id)
        ld = get_scoped(store.loads, load_id, brokerage_id, ERR_LOAD_NOT_FOUND)
        if ld.get("shipper_id") != shipper_id:
            raise ApiError(ERR_LOAD_NOT_FOUND, 404, "Load not found for this shipper.")
        check_version(ld, body)

        if ld.get("status") not in ("TENDERED", "ACCEPTED"):
            raise ApiError(ERR_LOAD_NOT_CANCELLABLE, 409, "Load not in TENDERED/ACCEPTED.")
        ld["status"] = "CANCELLED"
        store.bump(ld)
    return ok_object(ld)


# ---------------------------------------------------------------------------
# Accessorial charge creation (nested under load)
# ---------------------------------------------------------------------------
@loads_bp.post("/<brokerage_id>/shippers/<shipper_id>/loads/<load_id>/accessorial-charges")
@require_auth(["CarrierUser"])
def request_accessorial(brokerage_id, shipper_id, load_id):
    body = get_body()
    VALID_TYPES = {"LAYOVER", "TONU", "REWEIGH", "LUMPER"}
    charge_type = require_field(body, "charge_type", str)
    if charge_type not in VALID_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid charge_type.")
    if "amount_cents" not in body or body["amount_cents"] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing amount_cents.")
    amount = body["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be a positive integer.")

    with store.lock:
        get_brokerage_or_404(brokerage_id)
        get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ld = get_scoped(store.loads, load_id, brokerage_id, ERR_LOAD_NOT_FOUND)
        if ld.get("shipper_id") != shipper_id:
            raise ApiError(ERR_LOAD_NOT_FOUND, 404, "Load not found for this shipper.")
        ensure_carrier_self_access(ld.get("carrier_id"))

        # Per PRD §3.7 the charge is filed while load is between ACCEPTED and DELIVERED.
        if ld.get("status") not in ("ACCEPTED", "IN_TRANSIT", "DELIVERED"):
            # No specific error in the scaffold for this; use closest state error
            raise ApiError(ERR_LOAD_NOT_ACCEPTED, 409, "Load not in an accessorial-eligible state.")

        ac = {
            "load_id": load_id,
            "brokerage_id": brokerage_id,
            "charge_type": charge_type,
            "amount_cents": int(amount),
            "status": "REQUESTED",
        }
        store.stamp_create(ac)
        store.accessorial_charges[ac["id"]] = ac
    return ok_object(ac, status=201)
