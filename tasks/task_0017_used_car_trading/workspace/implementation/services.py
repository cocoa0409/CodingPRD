"""Business logic shared across routes — state transitions, cascades, deposit recompute."""

from datetime import timedelta
from calendar import monthrange

from clock import iso, now
import audit
import calculations as calc
from db import DB_INSTANCE, new_uuid
from errors import err
from helpers import bump


# ---- Deposit reconciliation (calc:deposit_balance_reconciliation) ----

def recompute_deposit(buyer_id: str):
    """Recompute Buyer.deposit_held_cents == deposit_balance_cents."""
    buyer = DB_INSTANCE.buyers.get(buyer_id)
    if not buyer:
        return
    held = 0
    for b in DB_INSTANCE.bids.values():
        if b["buyer_id"] == buyer_id and b["status"] == "LIVE":
            held += int(b["deposit_cents"])
    for r in DB_INSTANCE.reservations.values():
        if r["buyer_id"] == buyer_id and r["status"] == "HOLDING":
            held += int(r["deposit_cents"])
    old = buyer.get("deposit_held_cents", 0)
    if held != old:
        buyer["deposit_held_cents"] = held
        buyer["deposit_balance_cents"] = held
        bump(buyer)
        if held > old:
            audit.log("Buyer", buyer_id, "FINANCIAL_HOLD", from_value=old, to_value=held,
                      actor_role="system", actor_id="system")
        else:
            audit.log("Buyer", buyer_id, "FINANCIAL_RELEASE", from_value=old, to_value=held,
                      actor_role="system", actor_id="system")


def check_deposit_limit_for_increase(buyer_id: str, additional_cents: int):
    """Raises ERR_DEPOSIT_LIMIT_EXCEEDED if held + additional > limit."""
    buyer = DB_INSTANCE.buyers.get(buyer_id)
    held = buyer.get("deposit_held_cents", 0) if buyer else 0
    if held + additional_cents > calc.BUYER_DEPOSIT_LIMIT_CENTS:
        raise err("ERR_DEPOSIT_LIMIT_EXCEEDED",
                  "Buyer deposit limit exceeded")


# ---- Vehicle helpers ----

def transition_vehicle(vehicle: dict, new_status: str, actor_role="system", actor_id="system"):
    old = vehicle["vehicle_status"]
    if old == new_status:
        return
    vehicle["vehicle_status"] = new_status
    bump(vehicle)
    audit.log("Vehicle", vehicle["id"], "STATE_TRANSITION",
              from_value=old, to_value=new_status,
              actor_role=actor_role, actor_id=actor_id)


def vehicle_has_other_active_listings(vehicle_id: str, exclude_listing_id: str = None) -> bool:
    for l in DB_INSTANCE.listings.values():
        if l["vehicle_id"] != vehicle_id:
            continue
        if exclude_listing_id is not None and l["id"] == exclude_listing_id:
            continue
        if l["status"] in ("UNDER_REVIEW", "ACTIVE", "RESERVED"):
            return True
    return False


# ---- Listing helpers ----

def transition_listing(listing: dict, new_status: str, actor_role="system", actor_id="system"):
    old = listing["status"]
    if old == new_status:
        return
    listing["status"] = new_status
    bump(listing)
    audit.log("Listing", listing["id"], "STATE_TRANSITION",
              from_value=old, to_value=new_status,
              actor_role=actor_role, actor_id=actor_id)


# ---- Bid helpers ----

def transition_bid(bid: dict, new_status: str, actor_role="system", actor_id="system"):
    old = bid["status"]
    if old == new_status:
        return
    bid["status"] = new_status
    audit.log("Bid", bid["id"], "STATE_TRANSITION",
              from_value=old, to_value=new_status,
              actor_role=actor_role, actor_id=actor_id)


# ---- Reservation helpers ----

def transition_reservation(reservation: dict, new_status: str,
                           actor_role="system", actor_id="system"):
    old = reservation["status"]
    if old == new_status:
        return
    reservation["status"] = new_status
    audit.log("Reservation", reservation["id"], "STATE_TRANSITION",
              from_value=old, to_value=new_status,
              actor_role=actor_role, actor_id=actor_id)


def listing_reservations_sorted(listing_id: str):
    """Return reservations for a listing sorted FIFO by created_at then id (only non-terminal)."""
    items = [r for r in DB_INSTANCE.reservations.values() if r["listing_id"] == listing_id]
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


def promote_next_reservation(listing: dict, actor_role="system", actor_id="system"):
    """Find the next QUEUED reservation for the listing and promote it to HOLDING.
    Returns the promoted reservation, or None if there is no successor."""
    queued = [r for r in listing_reservations_sorted(listing["id"]) if r["status"] == "QUEUED"]
    if not queued:
        return None
    nxt = queued[0]
    nxt["queue_position"] = 1
    transition_reservation(nxt, "HOLDING", actor_role=actor_role, actor_id=actor_id)
    nxt["hold_expires_at"] = iso(now() + timedelta(hours=24))
    listing["reservation_buyer_id"] = nxt["buyer_id"]
    bump(listing)
    # Listing may already be RESERVED; if not, bump to RESERVED.
    if listing["status"] == "ACTIVE":
        transition_listing(listing, "RESERVED")
    recompute_deposit(nxt["buyer_id"])
    return nxt


# ---- Calendar add months with EOM clamp ----

def add_months_eom_clamp(start_dt, months: int):
    y = start_dt.year
    m = start_dt.month + months
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    last_day = monthrange(y, m)[1]
    d = min(start_dt.day, last_day)
    return start_dt.replace(year=y, month=m, day=d)


# ---- Warranty cascade helpers ----

def find_warranty_for_order(order_id: str):
    for w in DB_INSTANCE.warranties.values():
        if w["purchase_order_id"] == order_id:
            return w
    return None


def find_loan_for_order(order_id: str):
    for ln in DB_INSTANCE.loans.values():
        if ln["purchase_order_id"] == order_id:
            return ln
    return None


def find_transfer_for_order(order_id: str):
    for t in DB_INSTANCE.transfers.values():
        if t["purchase_order_id"] == order_id:
            return t
    return None


# ---- PurchaseOrder PAID cascade ----

def perform_paid_cascade(order: dict, paid_at_iso: str):
    """Implements PRD §3.5 / state-machine PAID side effects.
    Caller is responsible for first transitioning order to PAID."""
    listing = DB_INSTANCE.listings.get(order["listing_id"])
    vehicle = DB_INSTANCE.vehicles.get(order["vehicle_id"])

    # Listing RESERVED → SOLD
    if listing and listing["status"] == "RESERVED":
        transition_listing(listing, "SOLD")
    # Vehicle LISTED → SOLD
    if vehicle and vehicle["vehicle_status"] == "LISTED":
        transition_vehicle(vehicle, "SOLD")

    # AUCTION: winning bid LIVE→WON; other LIVE→LOST and release their deposits
    # FIXED_PRICE: HOLDING reservation → CONVERTED; queued → CANCELLED
    if listing:
        if listing.get("sale_mode") == "AUCTION":
            active_bid_id = listing.get("active_bid_id")
            buyers_to_recompute = set()
            for b in DB_INSTANCE.bids.values():
                if b["listing_id"] != listing["id"]:
                    continue
                if b["status"] == "LIVE":
                    if b["id"] == active_bid_id:
                        transition_bid(b, "WON")
                    else:
                        transition_bid(b, "LOST")
                    buyers_to_recompute.add(b["buyer_id"])
            for bid_buyer in buyers_to_recompute:
                recompute_deposit(bid_buyer)
        elif listing.get("sale_mode") == "FIXED_PRICE":
            buyers_to_recompute = set()
            for r in list(DB_INSTANCE.reservations.values()):
                if r["listing_id"] != listing["id"]:
                    continue
                if r["status"] == "HOLDING":
                    transition_reservation(r, "CONVERTED")
                    buyers_to_recompute.add(r["buyer_id"])
                elif r["status"] == "QUEUED":
                    transition_reservation(r, "CANCELLED")
                    buyers_to_recompute.add(r["buyer_id"])
            for buyer in buyers_to_recompute:
                recompute_deposit(buyer)

    # Activate Warranty: PENDING_ACTIVATION → ACTIVE
    warranty = find_warranty_for_order(order["id"])
    if warranty and warranty["status"] == "PENDING_ACTIVATION":
        from clock import parse_iso
        old_status = warranty["status"]
        warranty["status"] = "ACTIVE"
        warranty["effective_at"] = paid_at_iso
        # expires_at = effective_at + package_months
        eff_dt = parse_iso(paid_at_iso)
        months = calc.WARRANTY_PACKAGES[warranty["package_code"]]["months"]
        expires_dt = add_months_eom_clamp(eff_dt, months)
        warranty["expires_at"] = iso(expires_dt)
        bump(warranty)
        audit.log("Warranty", warranty["id"], "STATE_TRANSITION",
                  from_value=old_status, to_value="ACTIVE",
                  actor_role="system", actor_id="system")

    # All other still-active or under-review listings for the same vehicle → DELISTED
    if vehicle:
        for l in list(DB_INSTANCE.listings.values()):
            if l["vehicle_id"] != vehicle["id"]:
                continue
            if l["id"] == order["listing_id"]:
                continue
            if l["status"] in ("DRAFT", "UNDER_REVIEW", "ACTIVE", "RESERVED"):
                transition_listing(l, "DELISTED")

    # Auto-transition order PAID → AWAITING_TRANSFER, create TransferCase DOCS_PENDING
    old_order_status = order["status"]
    order["status"] = "AWAITING_TRANSFER"
    bump(order)
    audit.log("PurchaseOrder", order["id"], "STATE_TRANSITION",
              from_value=old_order_status, to_value="AWAITING_TRANSFER",
              actor_role="system", actor_id="system")

    # Create TransferCase
    transfer_id = new_uuid()
    transfer = {
        "id": transfer_id,
        "purchase_order_id": order["id"],
        "required_documents": [
            {"doc_type": dt, "submitted": False, "doc_url": None}
            for dt in ("ID_BUYER", "ID_SELLER", "TITLE", "REGISTRATION",
                       "RELEASE_OF_LIEN", "EMISSIONS_CERT")
        ],
        "appointment_at": None,
        "dmv_office_code": None,
        "status": "DOCS_PENDING",
        "license_plate_action": "REASSIGN",
        "new_plate_number": None,
        "failure_reason": None,
        "rolled_back_at": None,
        "created_at": iso(now()),
        "updated_at": iso(now()),
        "version": 1,
    }
    DB_INSTANCE.transfers[transfer_id] = transfer
    audit.log("TransferCase", transfer_id, "STATE_TRANSITION",
              from_value=None, to_value="DOCS_PENDING",
              actor_role="system", actor_id="system")


# ---- PurchaseOrder REFUNDED cascade (transfer rollback or REFUND_FULL dispute) ----

def perform_refund_cascade(order: dict):
    """Compensation cascade. Order must already be set to REFUNDED by the caller."""
    listing = DB_INSTANCE.listings.get(order["listing_id"])
    vehicle = DB_INSTANCE.vehicles.get(order["vehicle_id"])

    if listing and listing["status"] == "SOLD":
        transition_listing(listing, "ACTIVE")
        # Reset reservation_buyer_id; clear active_bid_id as auction is over
        listing["reservation_buyer_id"] = None
        listing["active_bid_id"] = None
        bump(listing)
    if vehicle and vehicle["vehicle_status"] == "SOLD":
        transition_vehicle(vehicle, "LISTED")
        # Vehicle ownership reverts to original seller
        original_seller_id = order["seller_id"]
        if vehicle.get("ownership_seller_id") != original_seller_id:
            old_owner = vehicle.get("ownership_seller_id")
            vehicle["ownership_seller_id"] = original_seller_id
            bump(vehicle)
            audit.log("Vehicle", vehicle["id"], "OWNERSHIP_CHANGE",
                      from_value=old_owner, to_value=original_seller_id,
                      actor_role="system", actor_id="system")

    # Warranty ACTIVE → VOIDED
    warranty = find_warranty_for_order(order["id"])
    if warranty and warranty["status"] == "ACTIVE":
        old = warranty["status"]
        warranty["status"] = "VOIDED"
        bump(warranty)
        audit.log("Warranty", warranty["id"], "STATE_TRANSITION",
                  from_value=old, to_value="VOIDED",
                  actor_role="system", actor_id="system")

    # Loan: DISBURSED → CANCELLED
    ln = find_loan_for_order(order["id"])
    if ln and ln["status"] == "DISBURSED":
        old = ln["status"]
        ln["status"] = "CANCELLED"
        bump(ln)
        audit.log("Loan", ln["id"], "STATE_TRANSITION",
                  from_value=old, to_value="CANCELLED",
                  actor_role="system", actor_id="system")


# ---- Order cancellation cascade (PENDING_PAYMENT → CANCELLED) ----

def perform_pending_cancel_cascade(order: dict):
    """Release bid/reservation deposit, restore Listing to ACTIVE, cancel any loan."""
    listing = DB_INSTANCE.listings.get(order["listing_id"])

    # Release winning bid (LIVE) for AUCTION
    buyers_to_recompute = set()
    if listing and listing.get("sale_mode") == "AUCTION":
        for b in DB_INSTANCE.bids.values():
            if b["listing_id"] == listing["id"] and b["status"] == "LIVE":
                # the winning live bid is the active_bid; we cancel only orders for it
                # but for safety release all live bids' deposits
                pass
        # When the order was created from an auction-close, winning bid was set to WON.
        # The order cancel here is only valid in PENDING_PAYMENT, so the bid is in WON.
        for b in DB_INSTANCE.bids.values():
            if b["listing_id"] == listing["id"] and b["status"] == "WON":
                transition_bid(b, "CANCELLED")
                buyers_to_recompute.add(b["buyer_id"])

    if listing and listing.get("sale_mode") == "FIXED_PRICE":
        # Release HOLDING reservation back to CANCELLED
        for r in DB_INSTANCE.reservations.values():
            if r["listing_id"] == listing["id"] and r["status"] == "HOLDING":
                transition_reservation(r, "CANCELLED")
                buyers_to_recompute.add(r["buyer_id"])
                listing["reservation_buyer_id"] = None
                bump(listing)
        # Promote next queued reservation if any (re-purposes promotion logic)
        nxt_promoted = promote_next_reservation(listing)
        if nxt_promoted is None:
            if listing["status"] == "RESERVED":
                transition_listing(listing, "ACTIVE")

    if listing and listing.get("sale_mode") == "AUCTION":
        if listing["status"] == "RESERVED":
            transition_listing(listing, "ACTIVE")
        listing["active_bid_id"] = None
        bump(listing)

    for b in buyers_to_recompute:
        recompute_deposit(b)

    # Loan cascade
    ln = find_loan_for_order(order["id"])
    if ln and ln["status"] in ("APPLIED", "CREDIT_CHECKING", "APPROVED"):
        old = ln["status"]
        ln["status"] = "CANCELLED"
        bump(ln)
        audit.log("Loan", ln["id"], "STATE_TRANSITION",
                  from_value=old, to_value="CANCELLED",
                  actor_role="system", actor_id="system")


# ---- TransferCase SUCCEEDED cascade ----

def perform_transfer_succeeded_cascade(transfer: dict):
    order = DB_INSTANCE.purchase_orders.get(transfer["purchase_order_id"])
    vehicle = DB_INSTANCE.vehicles.get(order["vehicle_id"]) if order else None

    if order and order["status"] == "AWAITING_TRANSFER":
        old = order["status"]
        order["status"] = "COMPLETED"
        bump(order)
        audit.log("PurchaseOrder", order["id"], "STATE_TRANSITION",
                  from_value=old, to_value="COMPLETED",
                  actor_role="system", actor_id="system")

    if vehicle and vehicle["vehicle_status"] == "SOLD":
        transition_vehicle(vehicle, "ARCHIVED")
        # Vehicle.ownership_seller_id := buyer's id
        new_owner = order["buyer_id"] if order else None
        if new_owner:
            old_owner = vehicle.get("ownership_seller_id")
            vehicle["ownership_seller_id"] = new_owner
            bump(vehicle)
            audit.log("Vehicle", vehicle["id"], "OWNERSHIP_CHANGE",
                      from_value=old_owner, to_value=new_owner,
                      actor_role="system", actor_id="system")
