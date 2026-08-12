"""Device claiming, the onboarding handshake, transfer and decommission
(PRD 3.3 and 3.4)."""

from flask import Blueprint, request

import serializers as S
from counters import (ENTITLED_STATES, device_has_rma_in_flight,
                      recompute_household_counts, recompute_overage_device_count)
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from firmware_svc import block_pending_rollouts
from ladder import (bad_request, begin, filter_enum, gates, in_force_subscription,
                    invalid_state, plan_of, req_id, req_str, require_subscription,
                    resolve, scope_household, touch)
from money import (ACTIVATION_MAX_ATTEMPTS, ACTIVATION_TOKEN_TTL_MINUTES,
                   BILLING_CYCLE_DAYS, PRORATION_MIN_DAYS, as_decimal, clamp_days,
                   round_half_up)
from store import clock, db, new_row, new_token, sort_rows
from timeutil import (add_minutes, floor_days_between, render_instant,
                      try_parse_date, try_parse_instant)
from warranty import pin_warranty

bp = Blueprint("devices", __name__)
PREFIX = "/smart-home-support"

DEVICE_READ_ROLES = ("PlatformAdmin", "SupportAgent", "Owner", "Member", "BillingAdmin")


def _validate_serial(value):
    if len(value) < 6 or len(value) > 32 or not value.isalnum() or value != value.upper():
        bad_request("serial_number must be 6-32 uppercase alphanumeric characters.")


def _entitlement(household, subscription, plan):
    """PRD 3.3 first computation: the boundary is `after <= included`, so the
    claim that brings the count to exactly the included number is free."""
    included = plan["included_device_count"]
    before = household.get("entitled_device_count") or 0
    after = before + 1
    if after <= included:
        return False
    if subscription.get("allow_overage"):
        return True
    raise ApiError("ERR_DEVICE_CAP_EXCEEDED")


def _overage_charge(subscription, plan):
    """PRD 3.3 second computation, run only when the claim is an overage."""
    cycle_end = try_parse_instant(subscription["cycle_end_at"])
    days = clamp_days(floor_days_between(clock.now(), cycle_end))
    if days < PRORATION_MIN_DAYS:
        return 0
    charge = round_half_up(as_decimal(plan["overage_fee_cents_per_device"])
                           * as_decimal(days) / as_decimal(BILLING_CYCLE_DAYS))
    subscription["overage_charges_cents_this_cycle"] = (
        subscription.get("overage_charges_cents_this_cycle") or 0) + charge
    subscription["next_invoice_adjustment_cents"] = (
        subscription.get("next_invoice_adjustment_cents") or 0) + charge
    return charge


@bp.post(PREFIX + "/devices/claim")
def claim_device():
    ctx = begin(("Owner", "PlatformAdmin"))
    body = ctx.body
    found = resolve(household=body.get("household_id"), catalog=body.get("catalog_entry_id"))
    household = found.get("household")
    if household is None:
        req_id(body, "household_id")
    # Rung 7 -- the operation needs the household's in-force subscription.
    subscription = require_subscription(household["id"])
    catalog = found.get("catalog")
    if catalog is None:
        req_id(body, "catalog_entry_id")
    scope_household(ctx, household["id"])

    serial_number = req_str(body, "serial_number", 1)
    _validate_serial(serial_number)
    purchase_date = req_str(body, "purchase_date", 1)
    if try_parse_date(purchase_date) is None:
        bad_request("purchase_date must be a YYYY-MM-DD calendar date.")
    gates(household=household)

    # Rung 28 -- the serial must start with the catalog entry's serial_prefix.
    if not serial_number.startswith(catalog["serial_prefix"]):
        raise ApiError("ERR_SERIAL_MODEL_MISMATCH")
    # Rung 29 -- globally unique across every Device row, in any lifecycle
    # state including DECOMMISSIONED.
    for dev in db.devices.values():
        if dev.get("serial_number") == serial_number:
            raise ApiError("ERR_SERIAL_ALREADY_CLAIMED")

    plan = plan_of(subscription)
    # Rung 50 -- the entitlement check.
    is_overage = _entitlement(household, subscription, plan)
    if is_overage:
        _overage_charge(subscription, plan)
    warranty_expires_at, warranty_basis = pin_warranty(
        catalog, subscription, plan, purchase_date)

    now = clock.now()
    row = new_row()
    row.update({
        "household_id": household["id"],
        "catalog_entry_id": catalog["id"],
        "transfer_target_household_id": None,
        "serial_number": serial_number,
        # purchase_date is a caller-supplied date string, echoed verbatim (G2).
        "purchase_date": purchase_date,
        "lifecycle_status": "CLAIMED",
        "firmware_status": "CURRENT",
        "firmware_version": None,
        "activation_token": new_token(),
        "activation_expires_at": render_instant(add_minutes(now, ACTIVATION_TOKEN_TTL_MINUTES)),
        "activation_attempts": 0,
        "activated_at": None,
        "warranty_expires_at": warranty_expires_at,
        "warranty_basis": warranty_basis,
        "is_overage": is_overage,
    })
    db.devices[row["id"]] = row
    recompute_household_counts(household)
    recompute_overage_device_count(subscription)
    return created(S.device(row))


@bp.get(PREFIX + "/devices")
def list_devices():
    begin(DEVICE_READ_ROLES)
    limit, offset = read_pagination(request.args)
    lifecycle = filter_enum(request.args, "lifecycle_status")
    hid = request.args.get("household_id")
    cid = request.args.get("catalog_entry_id")
    target = request.args.get("transfer_target_household_id")
    rows = []
    for row in db.devices.values():
        if hid is not None and row.get("household_id") != hid:
            continue
        if cid is not None and row.get("catalog_entry_id") != cid:
            continue
        if target is not None and row.get("transfer_target_household_id") != target:
            continue
        if lifecycle is not None and row.get("lifecycle_status") != lifecycle:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.device(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/devices/<did>")
def read_device(did):
    ctx = begin(DEVICE_READ_ROLES)
    found = resolve(device=did)
    device = found["device"]
    scope_household(ctx, device.get("household_id"))
    return ok(S.device(device))


@bp.post(PREFIX + "/devices/<did>/activate")
def activate_device(did):
    ctx = begin(("Owner",))
    found = resolve(device=did)
    device = found["device"]
    household = db.households.get(device.get("household_id"))
    scope_household(ctx, device.get("household_id"))
    activation_code = req_str(ctx.body, "activation_code", 1)
    gates(household=household, device=device)

    # Rung 27 -- the lifecycle axis must permit the transition.
    if device.get("lifecycle_status") != "CLAIMED":
        invalid_state("Only a CLAIMED device may be activated.")

    now = clock.now()
    expires = try_parse_instant(device.get("activation_expires_at"))
    # Rung 30 -- expiry.  The expiry path still moves the row.
    if expires is None or now >= expires:
        device["lifecycle_status"] = "RECLAIMABLE"
        device["activation_token"] = None
        touch(device)
        recompute_household_counts(household)
        raise ApiError("ERR_ACTIVATION_TOKEN_EXPIRED")

    attempts = device.get("activation_attempts") or 0
    # Rung 31 -- the attempt cap, evaluated before the code itself.
    if attempts >= ACTIVATION_MAX_ATTEMPTS:
        raise ApiError("ERR_ACTIVATION_ATTEMPTS_EXCEEDED")

    if activation_code != device.get("activation_token"):
        if attempts + 1 >= ACTIVATION_MAX_ATTEMPTS:
            # The third failure moves the row as well as bumping the counter.
            device["activation_attempts"] = ACTIVATION_MAX_ATTEMPTS
            device["lifecycle_status"] = "RECLAIMABLE"
            device["activation_token"] = None
            touch(device)
            recompute_household_counts(household)
            raise ApiError("ERR_ACTIVATION_ATTEMPTS_EXCEEDED")
        # A first or second bad code only bumps the counter.
        device["activation_attempts"] = attempts + 1
        touch(device)
        raise ApiError("ERR_ACTIVATION_CODE_INVALID")

    catalog = db.device_catalog.get(device.get("catalog_entry_id"))
    device["lifecycle_status"] = "ACTIVE"
    device["activated_at"] = clock.now_iso()
    device["firmware_version"] = catalog["current_firmware_version"] if catalog else None
    device["activation_token"] = None
    touch(device)
    recompute_household_counts(household)
    return ok(S.device(device))


@bp.post(PREFIX + "/devices/<did>/reclaim")
def reclaim_device(did):
    ctx = begin(("SupportAgent", "PlatformAdmin"))
    found = resolve(device=did)
    device = found["device"]
    household = db.households.get(device.get("household_id"))
    gates(household=household, device=device)
    # Rung 33 -- reclaim has its own eligibility rung rather than rung 27.
    if device.get("lifecycle_status") != "RECLAIMABLE":
        raise ApiError("ERR_RECLAIM_NOT_ELIGIBLE")
    device["activation_token"] = new_token()
    device["activation_expires_at"] = render_instant(
        add_minutes(clock.now(), ACTIVATION_TOKEN_TTL_MINUTES))
    device["activation_attempts"] = 0
    device["lifecycle_status"] = "CLAIMED"
    touch(device)
    recompute_household_counts(household)
    return ok(S.device(device))


@bp.post(PREFIX + "/devices/<did>/decommission")
def decommission_device(did):
    ctx = begin(("Owner", "PlatformAdmin"))
    found = resolve(device=did)
    device = found["device"]
    household = db.households.get(device.get("household_id"))
    scope_household(ctx, device.get("household_id"))
    gates(household=household, device=device)

    status = device.get("lifecycle_status")
    if status not in ("CLAIMED", "RECLAIMABLE", "ACTIVE"):
        invalid_state("Decommission is available from CLAIMED, RECLAIMABLE or ACTIVE only.")
    if status == "ACTIVE" and device_has_rma_in_flight(device["id"]):
        raise ApiError("ERR_RMA_IN_FLIGHT")

    device["lifecycle_status"] = "DECOMMISSIONED"
    touch(device)
    if status == "ACTIVE":
        block_pending_rollouts(device)
    recompute_household_counts(household)
    recompute_overage_device_count(in_force_subscription(household["id"]))
    return ok(S.device(device))


@bp.post(PREFIX + "/devices/<did>/transfer")
def transfer_device(did):
    ctx = begin(("Owner",))
    body = ctx.body
    found = resolve(household=body.get("target_household_id"), device=did)
    target_household = found.get("household")
    device = found["device"]
    if target_household is None:
        req_id(body, "target_household_id")
    household = db.households.get(device.get("household_id"))
    scope_household(ctx, device.get("household_id"))
    gates(household=household, device=device)

    # Rung 27 -- device ACTIVE, and the target household's account_status
    # ACTIVE, which has no rung of its own and is therefore ERR_INVALID_STATE.
    if device.get("lifecycle_status") != "ACTIVE":
        invalid_state("Only an ACTIVE device may be offered for transfer.")
    if target_household.get("account_status") != "ACTIVE":
        invalid_state("The target household's account must be ACTIVE.")
    # Rung 34 -- no in-flight RMA case on the device.
    if device_has_rma_in_flight(device["id"]):
        raise ApiError("ERR_RMA_IN_FLIGHT")

    device["transfer_target_household_id"] = target_household["id"]
    device["lifecycle_status"] = "TRANSFER_PENDING"
    touch(device)
    recompute_household_counts(household)
    return ok(S.device(device))


@bp.post(PREFIX + "/devices/<did>/accept-transfer")
def accept_transfer(did):
    ctx = begin(("Owner",))
    found = resolve(device=did)
    device = found["device"]
    source_household = db.households.get(device.get("household_id"))
    # Row scope on this endpoint compares the acting member's household_id
    # against transfer_target_household_id -- PRD 3.4 states that requirement
    # explicitly, and using the generic Device.household_id here would make
    # the endpoint unreachable for the only caller entitled to use it.  When
    # no transfer is pending the generic comparison is used instead, which is
    # what keeps ERR_INVALID_STATE reachable below.
    pending_target = device.get("transfer_target_household_id")
    scope_household(ctx, pending_target or device.get("household_id"))
    gates(household=source_household, device=device)

    if device.get("lifecycle_status") != "TRANSFER_PENDING":
        invalid_state("Only a TRANSFER_PENDING device may be accepted.")

    target_household = db.households.get(pending_target)
    if target_household is None:
        raise ApiError("ERR_HOUSEHOLD_NOT_FOUND")
    target_sub = require_subscription(target_household["id"])
    target_plan = plan_of(target_sub)

    # Rung 50 -- the receiving household's entitlement check.
    included = target_plan["included_device_count"]
    after = (target_household.get("entitled_device_count") or 0) + 1
    if after > included and not target_sub.get("allow_overage"):
        raise ApiError("ERR_DEVICE_CAP_EXCEEDED")

    device["household_id"] = target_household["id"]
    device["transfer_target_household_id"] = None
    device["lifecycle_status"] = "ACTIVE"
    device["is_overage"] = after > included
    touch(device)
    recompute_household_counts(source_household)
    recompute_household_counts(target_household)
    recompute_overage_device_count(in_force_subscription(source_household["id"]))
    recompute_overage_device_count(target_sub)
    return ok(S.device(device))
