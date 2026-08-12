"""Warranty, RMA routing and the advance-replacement hold (PRD 3.11)."""

from flask import Blueprint, request

import serializers as S
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from ladder import (begin, gates, in_force_subscription, invalid_state, occ,
                    plan_of, req_id, require_subscription, resolve,
                    scope_household, touch)
from money import (ADVANCE_REPLACEMENT_HOLD_PCT_OF_MSRP,
                   ADVANCE_REPLACEMENT_MIN_WARRANTY_DAYS, RMA_RETURN_WINDOW_DAYS,
                   as_decimal, round_half_up)
from store import clock, db, new_row, sort_rows
from timeutil import add_days, floor_days_between, render_instant, try_parse_instant

bp = Blueprint("rma", __name__)
PREFIX = "/smart-home-support"

RMA_READ_ROLES = ("PlatformAdmin", "SupportAgent", "Owner")


@bp.post(PREFIX + "/rma-cases")
def open_case():
    ctx = begin(("SupportAgent",))
    body = ctx.body
    found = resolve(device=body.get("device_id"), ticket=body.get("ticket_id"))
    device = found.get("device")
    if device is None:
        req_id(body, "device_id")
    ticket = found.get("ticket")
    household = db.households.get(device.get("household_id"))
    # Rung 22 -- optimistic concurrency on the parent Device row.
    occ(body, "expected_device_version", device)
    gates(household=household, device=device)

    subscription = require_subscription(device["household_id"])
    plan = plan_of(subscription)
    catalog = db.device_catalog.get(device.get("catalog_entry_id"))
    now = clock.now()

    # Computation 1 -- the warranty state, decided with a STRICT comparison.
    expires = try_parse_instant(device.get("warranty_expires_at")) \
        if device.get("warranty_expires_at") else None
    in_warranty = expires is not None and now < expires
    warranty_state = "IN_WARRANTY" if in_warranty else "EXPIRED"
    remaining_days = max(0, floor_days_between(now, expires)) if expires is not None else 0

    # Computation 2 -- routing, first matching branch wins; the ordering is
    # normative and no later branch may pre-empt an earlier one.
    device_class = catalog.get("device_class") if catalog else None
    eligible = bool(plan and plan.get("advance_replacement_eligible"))
    if warranty_state == "EXPIRED":
        routing_target = "CUSTOMER_PAID_DEPOT"
    elif eligible and device_class == "HUB":
        routing_target = "ADVANCE_REPLACEMENT"
    elif (eligible and device_class in ("CAMERA", "LOCK")
            and remaining_days >= ADVANCE_REPLACEMENT_MIN_WARRANTY_DAYS):
        routing_target = "ADVANCE_REPLACEMENT"
    elif catalog is not None and catalog.get("manufacturer_service_only"):
        routing_target = "MANUFACTURER"
    else:
        routing_target = "IN_HOUSE_DEPOT"

    # Computation 3 -- the hold, only on the advance-replacement target.
    if routing_target == "ADVANCE_REPLACEMENT":
        hold_amount = round_half_up(as_decimal(catalog["msrp_cents"])
                                    * ADVANCE_REPLACEMENT_HOLD_PCT_OF_MSRP)
        hold_state = "HELD"
    else:
        hold_amount = 0
        hold_state = "NONE"

    # Supersession: any prior OPEN or ROUTED case on the same device.
    superseded_id = None
    priors = [c for c in db.rma_cases.values()
              if c.get("device_id") == device["id"] and c.get("status") in ("OPEN", "ROUTED")]
    for prior in sorted(priors, key=lambda c: (c["created_at"], c["id"])):
        prior["status"] = "SUPERSEDED"
        touch(prior)
        superseded_id = prior["id"]

    row = new_row()
    row.update({
        "device_id": device["id"],
        "ticket_id": ticket["id"] if ticket is not None else None,
        "supersedes_rma_id": superseded_id,
        "warranty_state": warranty_state,
        "routing_target": routing_target,
        # The case walks OPEN -> ROUTED inside the creating request, so a
        # freshly created case is returned in ROUTED with version 1.
        "status": "ROUTED",
        "hold_amount_cents": hold_amount,
        "hold_state": hold_state,
        "shipped_at": None,
        "return_deadline_at": None,
        "returned_at": None,
    })
    db.rma_cases[row["id"]] = row
    touch(device)
    return created(S.rma_case(row))


@bp.get(PREFIX + "/rma-cases")
def list_cases():
    begin(RMA_READ_ROLES)
    limit, offset = read_pagination(request.args)
    did = request.args.get("device_id")
    tid = request.args.get("ticket_id")
    sup = request.args.get("supersedes_rma_id")
    rows = []
    for row in db.rma_cases.values():
        if did is not None and row.get("device_id") != did:
            continue
        if tid is not None and row.get("ticket_id") != tid:
            continue
        if sup is not None and row.get("supersedes_rma_id") != sup:
            continue
        rows.append(row)
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.rma_case(r) for r in page], limit, offset, total)


def _case_scope(ctx, case):
    device = db.devices.get(case.get("device_id"))
    scope_household(ctx, device.get("household_id") if device else None)
    return device


@bp.get(PREFIX + "/rma-cases/<rid>")
def read_case(rid):
    ctx = begin(RMA_READ_ROLES)
    found = resolve(rma=rid)
    case = found["rma"]
    _case_scope(ctx, case)
    return ok(S.rma_case(case))


@bp.post(PREFIX + "/rma-cases/<rid>/ship-advance-replacement")
def ship_advance_replacement(rid):
    ctx = begin(("SupportAgent",))
    found = resolve(rma=rid)
    case = found["rma"]
    device = _case_scope(ctx, case)
    household = db.households.get(device.get("household_id")) if device else None
    gates(household=household)

    if case.get("status") != "ROUTED":
        invalid_state("Only a ROUTED case may ship an advance replacement.")
    # Rung 48 -- sits below rung 27.
    if case.get("routing_target") != "ADVANCE_REPLACEMENT":
        raise ApiError("ERR_ADVANCE_REPLACEMENT_NOT_ELIGIBLE")

    shipped_at = clock.now_iso()
    case["shipped_at"] = shipped_at
    case["return_deadline_at"] = render_instant(
        add_days(clock.now(), RMA_RETURN_WINDOW_DAYS))
    # The case walks ROUTED -> ADVANCE_SHIPPED -> AWAITING_RETURN inside the
    # one request; its version still rises by exactly one.
    case["status"] = "AWAITING_RETURN"
    touch(case)
    if device is not None and device.get("lifecycle_status") == "ACTIVE":
        device["lifecycle_status"] = "SUSPENDED_RMA"
        touch(device)
    return ok(S.rma_case(case))


@bp.post(PREFIX + "/rma-cases/<rid>/receive-return")
def receive_return(rid):
    ctx = begin(("SupportAgent",))
    found = resolve(rma=rid)
    case = found["rma"]
    device = _case_scope(ctx, case)
    household = db.households.get(device.get("household_id")) if device else None
    gates(household=household)

    status = case.get("status")
    if status == "ROUTED":
        # The depot and manufacturer branches never ship an advance unit and
        # skip the hold sub-path entirely: the case closes outright.
        if case.get("routing_target") not in ("MANUFACTURER", "IN_HOUSE_DEPOT",
                                              "CUSTOMER_PAID_DEPOT"):
            invalid_state("A ROUTED advance-replacement case must ship before it returns.")
        case["returned_at"] = clock.now_iso()
        case["hold_state"] = "NONE"
        case["status"] = "CLOSED"
        touch(case)
        return ok(S.rma_case(case))

    if status != "AWAITING_RETURN":
        invalid_state("The case's status does not permit recording a return.")
    deadline = try_parse_instant(case.get("return_deadline_at"))
    if deadline is None or clock.now() > deadline:
        invalid_state("The return window has closed.")

    case["returned_at"] = clock.now_iso()
    case["hold_state"] = "RELEASED"
    case["status"] = "RETURN_RECEIVED"
    touch(case)
    if device is not None and device.get("lifecycle_status") == "SUSPENDED_RMA":
        device["lifecycle_status"] = "ACTIVE"
        touch(device)
    return ok(S.rma_case(case))


@bp.post(PREFIX + "/rma-cases/<rid>/close-return-window")
def close_return_window(rid):
    ctx = begin(("SupportAgent",))
    found = resolve(rma=rid)
    case = found["rma"]
    device = _case_scope(ctx, case)
    household = db.households.get(device.get("household_id")) if device else None
    gates(household=household)

    status = case.get("status")
    if status not in ("RETURN_RECEIVED", "AWAITING_RETURN"):
        invalid_state("The case's status does not permit closing the return window.")

    if status == "RETURN_RECEIVED":
        case["status"] = "CLOSED"
        touch(case)
        return ok(S.rma_case(case))

    # Rung 49 -- strictly after the deadline.
    deadline = try_parse_instant(case.get("return_deadline_at"))
    if deadline is None or clock.now() <= deadline:
        raise ApiError("ERR_RETURN_WINDOW_OPEN")

    # AWAITING_RETURN -> RETURN_WINDOW_EXPIRED -> CHARGED -> CLOSED, one bump.
    subscription = in_force_subscription(device["household_id"]) if device else None
    if case.get("hold_state") == "HELD":
        case["hold_state"] = "CHARGED"
        if subscription is not None:
            subscription["next_invoice_adjustment_cents"] = (
                subscription.get("next_invoice_adjustment_cents") or 0) + (
                case.get("hold_amount_cents") or 0)
            touch(subscription)
    case["status"] = "CLOSED"
    touch(case)
    if device is not None and device.get("lifecycle_status") == "SUSPENDED_RMA":
        device["lifecycle_status"] = "ACTIVE"
        touch(device)
    return ok(S.rma_case(case))
