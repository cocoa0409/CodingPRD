"""Add-on orders: bundle pricing, install credits, proration and fulfilment
(PRD 3.10)."""

from flask import Blueprint, request

import serializers as S
from counters import recompute_household_counts, recompute_overage_device_count
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from ladder import (bad_request, begin, gates, in_force_subscription, invalid_state,
                    occ, plan_of, req_id, req_str, require_subscription, resolve,
                    scope_household, touch)
from money import (ADDON_ORDER_MAX_LINES, BILLING_CYCLE_DAYS,
                   BUNDLE_DISCOUNT_TIER1_MIN_SUBTOTAL_CENTS, BUNDLE_DISCOUNT_TIER1_PCT,
                   BUNDLE_DISCOUNT_TIER2_MIN_SUBTOTAL_CENTS, BUNDLE_DISCOUNT_TIER2_PCT,
                   INSTALL_VISIT_FEE_CENTS, PRORATION_MIN_DAYS, ACTIVATION_TOKEN_TTL_MINUTES,
                   as_decimal, clamp_days, round_half_up)
from store import clock, db, new_row, new_token, sort_rows
from timeutil import (add_minutes, floor_days_between, render_instant,
                      try_parse_date, try_parse_instant)
from warranty import pin_warranty

bp = Blueprint("addons", __name__)
PREFIX = "/smart-home-support"

ORDER_READ_ROLES = ("PlatformAdmin", "BillingAdmin", "Owner")


def _line_catalog_ids(lines):
    out = []
    if not isinstance(lines, list):
        return out
    for line in lines:
        if isinstance(line, dict) and isinstance(line.get("catalog_entry_id"), str):
            out.append(line["catalog_entry_id"])
    return out


def _validate_lines(lines):
    if not isinstance(lines, list):
        bad_request("lines must be an array.")
    if len(lines) < 1 or len(lines) > ADDON_ORDER_MAX_LINES:
        bad_request("lines must carry between 1 and %d entries." % ADDON_ORDER_MAX_LINES)
    out = []
    for line in lines:
        if not isinstance(line, dict):
            bad_request("Every line must be an object.")
        cid = line.get("catalog_entry_id")
        if not isinstance(cid, str) or not cid:
            bad_request("Every line must carry a catalog_entry_id string.")
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int):
            bad_request("Every line's quantity must be an integer.")
        if qty < 1:
            bad_request("Every line's quantity must be at least 1.")
        out.append({"catalog_entry_id": cid, "quantity": qty})
    return out


@bp.post(PREFIX + "/addon-orders")
def place_order():
    ctx = begin(("BillingAdmin", "Owner"))
    body = ctx.body
    found = resolve(household=body.get("household_id"),
                    subscription=body.get("subscription_id"),
                    catalog=_line_catalog_ids(body.get("lines")))
    household = found.get("household")
    if household is None:
        req_id(body, "household_id")
    subscription = found.get("subscription")
    if subscription is None:
        req_id(body, "subscription_id")
    scope_household(ctx, household["id"])
    lines = _validate_lines(body.get("lines"))
    # Rung 22 -- optimistic concurrency on the parent Subscription row.
    occ(body, "expected_subscription_version", subscription)
    gates(household=household)

    plan = plan_of(subscription)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    entries = [db.device_catalog[line["catalog_entry_id"]] for line in lines]

    included = plan["included_device_count"]
    total_units = sum(line["quantity"] for line in lines)
    before = household.get("entitled_device_count") or 0
    # Rung 50 -- the entitlement cap is enforced on placement as a projection.
    if (before + total_units) > included and not subscription.get("allow_overage"):
        raise ApiError("ERR_DEVICE_CAP_EXCEEDED")

    # Step 1 -- subtotal.
    subtotal = sum(entries[i]["msrp_cents"] * lines[i]["quantity"] for i in range(len(lines)))
    # Step 2 -- the bundle discount, keyed on the SUBTOTAL ALONE and rounded
    # once, before any install charge or proration is added.
    if subtotal >= BUNDLE_DISCOUNT_TIER2_MIN_SUBTOTAL_CENTS:
        pct = BUNDLE_DISCOUNT_TIER2_PCT
    elif subtotal >= BUNDLE_DISCOUNT_TIER1_MIN_SUBTOTAL_CENTS:
        pct = BUNDLE_DISCOUNT_TIER1_PCT
    else:
        pct = as_decimal(0)
    discount_cents = round_half_up(as_decimal(subtotal) * pct)
    discounted_subtotal = subtotal - discount_cents

    # Step 3 -- the install-credit waterfall.  Only units whose model has
    # requires_install true participate; the most expensive installation is
    # covered first, ties broken by line position then unit index.
    units = []
    for li, line in enumerate(lines):
        entry = entries[li]
        if not entry.get("requires_install"):
            continue
        for ui in range(line["quantity"]):
            units.append((-entry["msrp_cents"], li, ui))
    units.sort()
    credits = subscription.get("install_credits_remaining") or 0
    applied = 0
    for _unit in units:
        if credits > 0:
            credits -= 1
            applied += 1
    uncovered = len(units) - applied
    # Step 4 -- the install charge.
    install_charge = uncovered * INSTALL_VISIT_FEE_CENTS

    # Step 5 -- proration, rounded PER LINE and only then summed.
    cycle_end = try_parse_instant(subscription["cycle_end_at"])
    days = clamp_days(floor_days_between(clock.now(), cycle_end))
    running = before
    line_extra = []
    for line in lines:
        extra = 0
        for _ in range(line["quantity"]):
            running += 1
            if running > included:
                extra += 1
        line_extra.append(extra)
    monthly_delta = plan["overage_fee_cents_per_device"] * sum(line_extra)
    if days >= PRORATION_MIN_DAYS:
        proration_mode = "MID_CYCLE_PRORATED"
        proration = 0
        for extra in line_extra:
            proration += round_half_up(
                as_decimal(plan["overage_fee_cents_per_device"]) * as_decimal(extra)
                * as_decimal(days) / as_decimal(BILLING_CYCLE_DAYS))
    else:
        proration_mode = "NEXT_CYCLE_FULL"
        proration = 0

    # Step 6 -- the total, with no further rounding.
    order_total = discounted_subtotal + install_charge + proration

    row = new_row()
    row.update({
        "household_id": household["id"],
        "subscription_id": subscription["id"],
        "lines": [dict(line) for line in lines],
        "status": "PLACED",
        "subtotal_cents": subtotal,
        "bundle_discount_pct": float(pct),
        "bundle_discount_cents": discount_cents,
        "discounted_subtotal_cents": discounted_subtotal,
        "install_credits_applied": applied,
        "install_charge_cents": install_charge,
        "monthly_delta_cents": monthly_delta,
        "proration_mode": proration_mode,
        "proration_cents": proration,
        "order_total_cents": order_total,
        "fulfilled_device_ids": [],
    })
    db.addon_orders[row["id"]] = row

    subscription["install_credits_consumed"] = (
        subscription.get("install_credits_consumed") or 0) + applied
    subscription["install_credits_remaining"] = max(
        0, subscription["install_credits_granted"] - subscription["install_credits_consumed"])
    subscription["next_invoice_adjustment_cents"] = (
        subscription.get("next_invoice_adjustment_cents") or 0) + order_total
    touch(subscription)
    return created(S.addon_order(row))


@bp.get(PREFIX + "/addon-orders")
def list_orders():
    begin(ORDER_READ_ROLES)
    limit, offset = read_pagination(request.args)
    hid = request.args.get("household_id")
    sid = request.args.get("subscription_id")
    rows = []
    for row in db.addon_orders.values():
        if hid is not None and row.get("household_id") != hid:
            continue
        if sid is not None and row.get("subscription_id") != sid:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.addon_order(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/addon-orders/<oid>")
def read_order(oid):
    ctx = begin(ORDER_READ_ROLES)
    found = resolve(order=oid)
    order = found["order"]
    scope_household(ctx, order.get("household_id"))
    return ok(S.addon_order(order))


@bp.post(PREFIX + "/addon-orders/<oid>/fulfill")
def fulfill_order(oid):
    ctx = begin(("BillingAdmin", "PlatformAdmin"))
    found = resolve(order=oid)
    order = found["order"]
    household = db.households.get(order.get("household_id"))
    scope_household(ctx, order.get("household_id"))

    serial_numbers = ctx.body.get("serial_numbers")
    if not isinstance(serial_numbers, list) or not all(
            isinstance(s, str) for s in serial_numbers):
        bad_request("serial_numbers must be an array of strings.")
    purchase_date = req_str(ctx.body, "purchase_date", 1)
    if try_parse_date(purchase_date) is None:
        bad_request("purchase_date must be a YYYY-MM-DD calendar date.")
    total_units = sum(line["quantity"] for line in order["lines"])
    if len(serial_numbers) != total_units:
        bad_request("serial_numbers must carry exactly one entry per ordered unit.")
    gates(household=household)

    if order.get("status") != "PLACED":
        invalid_state("Only a PLACED order may be fulfilled.")
    subscription = db.subscriptions.get(order.get("subscription_id"))
    if subscription is None or subscription.get("status") not in ("ACTIVE", "PAST_DUE"):
        invalid_state("The household's subscription must be ACTIVE or PAST_DUE.")
    plan = plan_of(subscription)

    # The serial-prefix and serial-uniqueness rungs are scoped to device
    # claiming and are NOT part of the fulfilment path (PRD 3.10).
    included = plan["included_device_count"] if plan else 0
    running = household.get("entitled_device_count") or 0
    now = clock.now()
    created_ids = []
    cursor = 0
    for line in order["lines"]:
        entry = db.device_catalog.get(line["catalog_entry_id"])
        for _ in range(line["quantity"]):
            serial = serial_numbers[cursor]
            cursor += 1
            running += 1
            warranty_expires_at, warranty_basis = pin_warranty(
                entry, subscription, plan, purchase_date)
            row = new_row()
            row.update({
                "household_id": household["id"],
                "catalog_entry_id": entry["id"],
                "transfer_target_household_id": None,
                "serial_number": serial,
                "purchase_date": purchase_date,
                "lifecycle_status": "CLAIMED",
                "firmware_status": "CURRENT",
                "firmware_version": None,
                # Adjudication of friction 3: READING A -- fulfilment mints an
                # activation_token exactly as a claim does, with
                # activation_expires_at at the instant plus 1440 minutes.
                # Reading B (a null token reclaimed later by a support agent)
                # is self-defeating: reclaim requires lifecycle RECLAIMABLE,
                # and the only route from CLAIMED to RECLAIMABLE is a failed
                # or expired activation attempt, which itself needs a token.
                # Reading B would therefore strand every fulfilled unit in
                # CLAIMED forever and make ACTIVE, and with it every ticket,
                # firmware and RMA behaviour declared for these devices,
                # unreachable.  Reading A keeps all of that reachable.
                "activation_token": new_token(),
                "activation_expires_at": render_instant(
                    add_minutes(now, ACTIVATION_TOKEN_TTL_MINUTES)),
                "activation_attempts": 0,
                "activated_at": None,
                "warranty_expires_at": warranty_expires_at,
                "warranty_basis": warranty_basis,
                # The order's own entitlement walk is the only declared notion
                # of which units of the basket are extra, so it is what sets
                # is_overage; no further charge is booked because the order
                # already booked its proration.
                "is_overage": running > included,
            })
            db.devices[row["id"]] = row
            created_ids.append(row["id"])

    order["fulfilled_device_ids"] = created_ids
    order["status"] = "FULFILLED"
    touch(order)
    recompute_household_counts(household)
    recompute_overage_device_count(subscription)
    return ok(S.addon_order(order))
