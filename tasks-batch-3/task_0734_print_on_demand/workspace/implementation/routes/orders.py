"""Order endpoints — checkout, payment/fulfillment state transitions, refunds."""
from flask import Blueprint, request

import db
from clock import clock
from errors import raise_error
from middleware import require_auth
from response import ok, created, paginate_and_serialize
from services.calc import (
    DOMESTIC_SHIPPING_CENTS,
    CROSS_BORDER_SHIPPING_CENTS,
    backlog_delta,
    base_per_unit,
    listing_price_cents,
    partner_charge_cents,
    per_unit_creator_markup_cents,
)
from services.serialize import serialize

bp = Blueprint("orders", __name__)


def _get_order_or_404(oid):
    row = db.orders.get(oid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"order {oid} not found")
    return row


def _resolve_order_context(order):
    """Fetch related listing/design/variant/product/storefront/creator for an order."""
    listing = db.listings.get(order["listing_id"])
    variant = db.variants.get(listing["variant_id"]) if listing else None
    product = db.products.get(variant["product_id"]) if variant else None
    storefront = db.storefronts.get(listing["storefront_id"]) if listing else None
    design = db.designs.get(listing["design_id"]) if listing else None
    creator = db.creators.get(storefront["creator_id"]) if storefront else None
    return listing, design, variant, product, storefront, creator


def _job_for_order(order_id):
    """Return the (single) FulfillmentJob for an order, if any."""
    for j in db.fulfillment_jobs.all():
        if j["order_id"] == order_id:
            return j
    return None


def _provisional_creator_net(order, listing, variant, product, storefront):
    if order["is_sample"]:
        return 0
    base = base_per_unit(product, variant)
    per_unit = per_unit_creator_markup_cents(base, storefront["markup_bps"])
    return per_unit * int(order["item_count"])


def _final_creator_net(order, job, variant, product, storefront):
    """PRD §3.8 — final variant: gross_markup - final_partner_absorb.
    Sample orders always yield 0.
    """
    if order["is_sample"]:
        return 0
    base = base_per_unit(product, variant)
    per_unit_markup = per_unit_creator_markup_cents(base, storefront["markup_bps"])
    gross_markup = per_unit_markup * int(order["item_count"])
    if job is None:
        return gross_markup
    reprint_gen = int(job.get("reprint_generation", 0))
    initial = order.get("_initial_partner_charge_cents") or 0
    if reprint_gen > 0:
        absorb = int(job["partner_charge_cents"]) - initial
        return gross_markup - absorb
    return gross_markup


# ---- Create Order ----

@bp.post("/pod/orders")
@require_auth(["Anonymous", "Creator"])
def create_order():
    body = request.get_json(silent=True) or {}
    for f in ("storefront_id", "listing_id", "buyer_email", "ship_country_code", "item_count"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")

    is_sample = bool(body.get("is_sample", False))

    # Priority 4 FK resolution.
    storefront = db.storefronts.get(body["storefront_id"])
    if not storefront:
        raise_error("ERR_FK_NOT_FOUND", "storefront not found")
    listing = db.listings.get(body["listing_id"])
    if not listing:
        raise_error("ERR_FK_NOT_FOUND", "listing not found")

    item_count = body["item_count"]
    if not isinstance(item_count, int) or isinstance(item_count, bool) or item_count < 1:
        raise_error("ERR_INVALID_REQUEST", "item_count must be positive int")

    # Priority 10: listing availability (PUBLISHED + Design APPROVED + Variant active).
    variant = db.variants.get(listing["variant_id"])
    if not variant:
        raise_error("ERR_FK_NOT_FOUND", "variant not found")
    product = db.products.get(variant["product_id"])
    if not product:
        raise_error("ERR_FK_NOT_FOUND", "product not found")
    design = db.designs.get(listing["design_id"])
    if not design:
        raise_error("ERR_FK_NOT_FOUND", "design not found")
    if (
        listing["status"] != "PUBLISHED"
        or design["status"] != "APPROVED"
        or not variant.get("active", True)
    ):
        raise_error("ERR_LISTING_NOT_AVAILABLE", "listing not available for orders")

    # Priority 11: sample limit.
    if is_sample and item_count > 3:
        raise_error("ERR_SAMPLE_LIMIT_EXCEEDED", "sample orders limited to item_count <= 3")

    # Ensure listing is on the storefront the caller named.
    if listing["storefront_id"] != storefront["id"]:
        raise_error("ERR_FK_NOT_FOUND", "listing does not belong to storefront")

    row = db.new_common_fields()
    row.update(
        {
            "storefront_id": storefront["id"],
            "buyer_email": body["buyer_email"],
            "ship_country_code": body["ship_country_code"],
            "item_count": item_count,
            "listing_id": listing["id"],
            "is_sample": is_sample,
            "gross_amount_cents": 0,
            "shipping_cents": 0,
            "payment_status": "DRAFT",
            "fulfillment_status": "PENDING",
            "routed_partner_id": None,
            "creator_net_cents": 0,
            "_initial_partner_charge_cents": None,
            "_delivered_at": None,
        }
    )
    # Provisional variant of creator_profit.
    row["creator_net_cents"] = _provisional_creator_net(row, listing, variant, product, storefront)
    db.orders.insert(row)
    return created(serialize(row))


@bp.get("/pod/orders/<oid>")
@require_auth(["Creator", "PlatformAdmin"])
def read_order(oid):
    return ok(serialize(_get_order_or_404(oid)))


@bp.get("/pod/orders")
@require_auth(["Creator", "PlatformAdmin"])
def list_orders():
    storefront_id = request.args.get("storefront_id")
    listing_id = request.args.get("listing_id")
    routed_partner_id = request.args.get("routed_partner_id")
    rows = db.orders.all()
    if storefront_id is not None:
        rows = [r for r in rows if r["storefront_id"] == storefront_id]
    if listing_id is not None:
        rows = [r for r in rows if r["listing_id"] == listing_id]
    if routed_partner_id is not None:
        rows = [r for r in rows if r.get("routed_partner_id") == routed_partner_id]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


# ---- Payment axis: authorize / capture / refund / void / cancel ----

@bp.post("/pod/orders/<oid>/authorize")
@require_auth(["PlatformAdmin"])
def authorize_order(oid):
    order = _get_order_or_404(oid)
    if order["payment_status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "order not in DRAFT payment")

    listing, design, variant, product, storefront, _ = _resolve_order_context(order)
    if not listing or listing["status"] != "PUBLISHED":
        raise_error("ERR_INVALID_STATE", "listing not PUBLISHED")
    if not variant or not variant.get("active", True):
        raise_error("ERR_INVALID_STATE", "variant not active")

    # Recompute listed_price for this order (from current listing) and gross_amount.
    listed_price = listing_price_cents(product, variant, storefront, is_sample=order["is_sample"])
    order["gross_amount_cents"] = listed_price * int(order["item_count"]) + int(order.get("shipping_cents", 0))
    order["payment_status"] = "AUTHORIZED"
    db.bump(order)
    return ok(serialize(order))


def _run_routing(order):
    """PRD §3.7 routing selector. Returns the selected partner or raises."""
    ship = order["ship_country_code"]
    candidates = [
        p
        for p in db.fulfillment_partners.all()
        if p["status"] == "ACTIVE"
        and p["country_code"] == ship
        and int(p["current_backlog_hours"]) < int(p["max_backlog_hours"])
    ]
    if not candidates:
        # Cross-border fallback.
        candidates = [
            p
            for p in db.fulfillment_partners.all()
            if p["status"] == "ACTIVE"
            and int(p["current_backlog_hours"]) < int(p["max_backlog_hours"])
        ]
    if not candidates:
        raise_error("ERR_NO_ELIGIBLE_PARTNER", "no eligible partner found")

    # Sort by (cost_multiplier_bps asc, current_backlog_hours asc, created_at asc).
    candidates.sort(
        key=lambda p: (
            int(p["cost_multiplier_bps"]),
            int(p["current_backlog_hours"]),
            p.get("created_at", ""),
            p.get("_seq", 0),
        )
    )
    return candidates[0]


@bp.post("/pod/orders/<oid>/capture")
@require_auth(["PlatformAdmin"])
def capture_order(oid):
    order = _get_order_or_404(oid)
    if order["payment_status"] != "AUTHORIZED":
        raise_error("ERR_INVALID_STATE", "order not AUTHORIZED")
    if order["fulfillment_status"] not in ("PENDING", "ROUTED"):
        raise_error("ERR_INVALID_STATE", "order fulfillment_status must be PENDING or ROUTED")

    order["payment_status"] = "CAPTURED"
    db.bump(order)

    # If PENDING, fire routing selector.
    if order["fulfillment_status"] == "PENDING":
        listing, design, variant, product, storefront, _ = _resolve_order_context(order)
        if not listing or listing["status"] != "PUBLISHED":
            raise_error("ERR_INVALID_STATE", "listing not PUBLISHED at routing")
        selected = _run_routing(order)
        base = base_per_unit(product, variant)
        charge = partner_charge_cents(base, order["item_count"], selected["cost_multiplier_bps"])

        # Shipping.
        ship_cents = (
            DOMESTIC_SHIPPING_CENTS
            if selected["country_code"] == order["ship_country_code"]
            else CROSS_BORDER_SHIPPING_CENTS
        )

        order["routed_partner_id"] = selected["id"]
        order["shipping_cents"] = ship_cents
        order["fulfillment_status"] = "ROUTED"
        # Recompute gross_amount to include shipping now that partner is picked.
        listed_price = listing_price_cents(product, variant, storefront, is_sample=order["is_sample"])
        order["gross_amount_cents"] = listed_price * int(order["item_count"]) + ship_cents
        order["_initial_partner_charge_cents"] = charge
        db.bump(order)

        # Create FulfillmentJob.
        job = db.new_common_fields()
        job.update(
            {
                "order_id": order["id"],
                "partner_id": selected["id"],
                "status": "QUEUED",
                "reprint_generation": 0,
                "partner_charge_cents": charge,
                "shipped_at": None,
            }
        )
        db.fulfillment_jobs.insert(job)

        # Bump partner backlog.
        selected["current_backlog_hours"] = int(selected["current_backlog_hours"]) + backlog_delta(order["item_count"])
        db.bump(selected)

    return ok(serialize(order))


def _apply_wallet_delta(creator_id, delta):
    creator = db.creators.get(creator_id)
    if not creator:
        return
    creator["payout_wallet_cents"] = int(creator["payout_wallet_cents"]) + delta
    db.bump(creator)


@bp.post("/pod/orders/<oid>/refund")
@require_auth(["PlatformAdmin"])
def refund_order(oid):
    order = _get_order_or_404(oid)
    if order["payment_status"] != "CAPTURED":
        raise_error("ERR_INVALID_STATE", "order not CAPTURED")

    body = request.get_json(silent=True) or {}
    amt = body.get("refund_amount_cents")
    if not isinstance(amt, int) or isinstance(amt, bool):
        raise_error("ERR_INVALID_REQUEST", "refund_amount_cents must be int")
    gross = int(order["gross_amount_cents"])
    if amt <= 0 or amt > gross:
        raise_error("ERR_REFUND_AMOUNT_INVALID", "invalid refund amount")

    listing, design, variant, product, storefront, creator = _resolve_order_context(order)
    job = _job_for_order(order["id"])

    was_delivered = order["fulfillment_status"] == "DELIVERED"
    was_routed = order["fulfillment_status"] == "ROUTED"

    if amt == gross:
        order["payment_status"] = "REFUND_FULL"
        # Zero out this order's wallet contribution.
        if was_delivered:
            prior = int(order.get("creator_net_cents", 0))
            _apply_wallet_delta(storefront["creator_id"], -prior)
        # Zero the order's contribution.
        order["creator_net_cents"] = 0

        # Full-refund fulfillment coupling.
        if order["fulfillment_status"] in ("PENDING", "ROUTED"):
            if was_routed:
                partner = db.fulfillment_partners.get(order["routed_partner_id"]) if order["routed_partner_id"] else None
                if partner:
                    new_backlog = int(partner["current_backlog_hours"]) - backlog_delta(order["item_count"])
                    if new_backlog < 0:
                        new_backlog = 0
                    partner["current_backlog_hours"] = new_backlog
                    db.bump(partner)
            order["fulfillment_status"] = "CANCELLED"
    else:
        order["payment_status"] = "REFUND_PARTIAL"
        # Reduce net margin proportionally.
        if was_delivered and creator and storefront:
            prior = int(order.get("creator_net_cents", 0))
            # Reduce by refund fraction of gross.
            # net_after = prior - floor(prior * amt / gross)
            reduction = (prior * amt) // gross
            new_net = prior - reduction
            _apply_wallet_delta(storefront["creator_id"], -reduction)
            order["creator_net_cents"] = new_net

    db.bump(order)
    return ok(serialize(order))


@bp.post("/pod/orders/<oid>/void")
@require_auth(["PlatformAdmin"])
def void_order(oid):
    order = _get_order_or_404(oid)
    if order["payment_status"] != "AUTHORIZED":
        raise_error("ERR_INVALID_STATE", "order not AUTHORIZED")
    if order["fulfillment_status"] not in ("PENDING", "CANCELLED"):
        raise_error("ERR_INVALID_STATE", "fulfillment_status must be PENDING or CANCELLED")
    order["payment_status"] = "VOIDED"
    db.bump(order)
    return ok(serialize(order))


@bp.post("/pod/orders/<oid>/cancel")
@require_auth(["PlatformAdmin"])
def cancel_order(oid):
    order = _get_order_or_404(oid)
    if order["fulfillment_status"] != "PENDING":
        raise_error("ERR_INVALID_STATE", "fulfillment_status must be PENDING")
    if order["payment_status"] not in ("DRAFT", "AUTHORIZED"):
        raise_error("ERR_INVALID_STATE", "payment_status must be DRAFT or AUTHORIZED")

    if order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "VOIDED"
    order["fulfillment_status"] = "CANCELLED"
    db.bump(order)
    return ok(serialize(order))


# ---- Fulfillment axis: mark-in-print / mark-shipped / mark-delivered ----

@bp.post("/pod/orders/<oid>/mark-in-print")
@require_auth(["FulfillmentPartner"])
def mark_in_print(oid):
    order = _get_order_or_404(oid)
    # Reprint re-entry: after an approved reprint, PRD §3.8 puts the order back at
    # IN_PRINT with the job cycled back to QUEUED — "re-enters the print → ship →
    # deliver sequence as if it were a fresh routing." Accept order.fulfillment_status
    # in {ROUTED, IN_PRINT} when the job is QUEUED; otherwise the transition is invalid.
    if order["fulfillment_status"] not in ("ROUTED", "IN_PRINT"):
        raise_error("ERR_INVALID_STATE", "order not ROUTED")
    job = _job_for_order(order["id"])
    if not job or job["status"] != "QUEUED":
        raise_error("ERR_INVALID_STATE", "linked job must be QUEUED")

    order["fulfillment_status"] = "IN_PRINT"
    db.bump(order)
    job["status"] = "PRINTING"
    db.bump(job)
    return ok(serialize(order))


@bp.post("/pod/orders/<oid>/mark-shipped")
@require_auth(["FulfillmentPartner"])
def mark_shipped(oid):
    order = _get_order_or_404(oid)
    if order["fulfillment_status"] != "IN_PRINT":
        raise_error("ERR_INVALID_STATE", "order not IN_PRINT")
    job = _job_for_order(order["id"])
    if not job or job["status"] != "PRINTING":
        raise_error("ERR_INVALID_STATE", "linked job must be PRINTING")

    order["fulfillment_status"] = "SHIPPED"
    db.bump(order)
    now_iso = clock.now_iso()
    job["status"] = "SHIPPED"
    job["shipped_at"] = now_iso
    db.bump(job)

    # Decrement partner backlog.
    partner = db.fulfillment_partners.get(order["routed_partner_id"])
    if partner:
        new_backlog = int(partner["current_backlog_hours"]) - backlog_delta(order["item_count"])
        if new_backlog < 0:
            new_backlog = 0
        partner["current_backlog_hours"] = new_backlog
        db.bump(partner)

    return ok(serialize(order))


@bp.post("/pod/orders/<oid>/mark-delivered")
@require_auth(["FulfillmentPartner"])
def mark_delivered(oid):
    order = _get_order_or_404(oid)
    if order["fulfillment_status"] != "SHIPPED":
        raise_error("ERR_INVALID_STATE", "order not SHIPPED")
    job = _job_for_order(order["id"])
    if not job or job["status"] != "SHIPPED":
        raise_error("ERR_INVALID_STATE", "linked job must be SHIPPED")

    listing, design, variant, product, storefront, creator = _resolve_order_context(order)

    order["fulfillment_status"] = "DELIVERED"
    db.bump(order)
    job["status"] = "DELIVERED"
    db.bump(job)

    # Final creator_profit variant.
    prior_net = int(order.get("creator_net_cents", 0))
    was_previously_delivered = order.get("_delivered_at") is not None
    final_net = _final_creator_net(order, job, variant, product, storefront)
    order["creator_net_cents"] = final_net
    order["_delivered_at"] = clock.now_iso()
    db.bump(order)

    if storefront:
        # If this is a re-delivery from a reprint cycle, roll back prior contribution first.
        if was_previously_delivered:
            _apply_wallet_delta(storefront["creator_id"], -prior_net)
        _apply_wallet_delta(storefront["creator_id"], final_net)

    return ok(serialize(order))
