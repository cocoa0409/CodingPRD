"""Dedicated-trailer agreements: program lifecycle and monthly shortfall
settlement (PRD 3.8)."""
from flask import Blueprint, request

from authz import ALL_ROLES, FLEET_ADMIN, require_roles
from calc import SHORTFALL_FEE_PER_LOAD_CENTS, commitment_floor_loads
from db import store
from errors import err, invalid_request
from respond import success
from serialize import ser_agreement
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_datetime, req_field, req_int, req_str,
    sorted_by_creation, touch,
)
from timeutil import month_key, month_window, parse_month

bp = Blueprint("agreements", __name__)

OVERLAP_BLOCKING_STATUSES = ("PENDING", "ACTIVE")


@bp.route("/dedicated-trailer-agreements", methods=["POST"])
def create_agreement():
    require_roles([FLEET_ADMIN])
    data = json_body()
    # Priority 3: body-reference existence, left-to-right.
    customer = trailer = None
    if data.get("customer_id") is not None:
        customer = get_or_404(store.customers, "customers", data["customer_id"])
    if data.get("trailer_id") is not None:
        trailer = get_or_404(store.trailers, "trailers", data["trailer_id"])
    # Priority 4: shape.
    reject_unknown(data, {"customer_id", "trailer_id", "committed_loads_per_month",
                          "effective_from", "effective_to"})
    req_field(data, "customer_id")
    req_field(data, "trailer_id")
    committed = req_int(data, "committed_loads_per_month", minimum=1)
    eff_from = req_datetime(data, "effective_from")
    eff_to = req_datetime(data, "effective_to")
    if eff_to < eff_from:
        raise invalid_request("effective_to must be on or after effective_from")
    # Priority 8 temporal: inclusive both-ends period overlap on the same
    # trailer among PENDING/ACTIVE agreements.
    for o in store.agreements.values():
        if o["trailer_id"] != trailer["id"] or o["status"] not in OVERLAP_BLOCKING_STATUSES:
            continue
        if eff_from <= o["effective_to"] and o["effective_from"] <= eff_to:
            raise err("ERR_AGREEMENT_PERIOD_CONFLICT",
                      "Agreement period overlaps another PENDING/ACTIVE agreement on this trailer")
    # Priority 9: the customer must be enrolled in the dedicated program.
    if not customer["dedicated_program_enrolled"]:
        raise err("ERR_NOT_PROGRAM_ENROLLED",
                  "Customer is not enrolled in the dedicated-trailer program")
    a = {
        "id": new_id(),
        "_seq": next(store.seq),
        "customer_id": customer["id"],
        "trailer_id": trailer["id"],
        "committed_loads_per_month": committed,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "flagged_shipment_count": 0,
        "last_settled_month": None,
        "shortfall_events": 0,
        "shortfall_fees_total_cents": 0,
        "status": "PENDING",
    }
    a.update(new_common_fields())
    store.agreements[a["id"]] = a
    return success(ser_agreement(a), status=201)


@bp.route("/dedicated-trailer-agreements", methods=["GET"])
def list_agreements():
    require_roles(ALL_ROLES)
    customer_id = request.args.get("customer_id")
    trailer_id = request.args.get("trailer_id")
    status = request.args.get("status")
    items = [a for a in store.agreements.values()
             if (customer_id is None or a["customer_id"] == customer_id)
             and (trailer_id is None or a["trailer_id"] == trailer_id)
             and (status is None or a["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_agreement(a) for a in page],
                   response_type="array", pagination=pagination)


@bp.route("/dedicated-trailer-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    require_roles(ALL_ROLES)
    return success(ser_agreement(get_or_404(store.agreements, "agreements", aid)))


@bp.route("/dedicated-trailer-agreements/<aid>", methods=["PATCH"])
def patch_agreement(aid):
    require_roles([FLEET_ADMIN])
    a = get_or_404(store.agreements, "agreements", aid)
    data = json_body()
    # Priority 4: shape — the OCC field is non-optional input (PRD 2.7).
    reject_unknown(data, {"committed_loads_per_month", "expected_agreement_version"})
    expected = req_int(data, "expected_agreement_version")
    new_committed = None
    if "committed_loads_per_month" in data and data["committed_loads_per_month"] is not None:
        new_committed = req_int(data, "committed_loads_per_month", minimum=1)
    # Priority 5: optimistic concurrency.
    if expected != a["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_agreement_version does not match the agreement's current version")
    # Priority 6: revision is available only while PENDING.
    if a["status"] != "PENDING":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "Only a PENDING agreement's committed volume may be revised")
    if new_committed is not None:
        a["committed_loads_per_month"] = new_committed
    touch(a)
    return success(ser_agreement(a))


@bp.route("/dedicated-trailer-agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    require_roles([FLEET_ADMIN])
    a = get_or_404(store.agreements, "agreements", aid)
    reject_unknown(json_body(), set())
    if a["status"] != "PENDING":
        raise err("ERR_AGREEMENT_INVALID_STATE", "Activate requires the agreement to be PENDING")
    trailer = store.trailers[a["trailer_id"]]
    if trailer["dedicated_customer_id"] is not None:
        raise err("ERR_TRAILER_ALREADY_DEDICATED",
                  "The trailer is already dedicated to a customer")
    trailer["dedicated_customer_id"] = a["customer_id"]
    touch(trailer)
    a["status"] = "ACTIVE"
    touch(a)
    return success(ser_agreement(a))


@bp.route("/dedicated-trailer-agreements/<aid>/terminate", methods=["POST"])
def terminate_agreement(aid):
    require_roles([FLEET_ADMIN])
    a = get_or_404(store.agreements, "agreements", aid)
    reject_unknown(json_body(), set())
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "Terminate requires the agreement to be ACTIVE or SUSPENDED")
    trailer = store.trailers.get(a["trailer_id"])
    if trailer is not None and trailer["dedicated_customer_id"] is not None:
        # Compensating release of the dedication.
        trailer["dedicated_customer_id"] = None
        touch(trailer)
    a["status"] = "TERMINATED"
    touch(a)
    return success(ser_agreement(a))


@bp.route("/dedicated-trailer-agreements/<aid>/close-month", methods=["POST"])
def close_month(aid):
    require_roles([FLEET_ADMIN])
    a = get_or_404(store.agreements, "agreements", aid)
    data = json_body()
    reject_unknown(data, {"settlement_month"})
    sm = req_str(data, "settlement_month")
    try:
        year, month = parse_month(sm)
    except ValueError:
        raise invalid_request("settlement_month must be in YYYY-MM form")
    if a["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_INVALID_STATE", "Close-month requires the agreement to be ACTIVE")
    # Priority 8 temporal: the month must be strictly before the current
    # clock month and strictly after last_settled_month when one exists.
    if (year, month) >= month_key(store.clock):
        raise err("ERR_MONTH_NOT_CLOSABLE",
                  "settlement_month must be strictly before the current month")
    if a["last_settled_month"] is not None:
        last = parse_month(a["last_settled_month"])
        if (year, month) <= last:
            raise err("ERR_MONTH_NOT_CLOSABLE",
                      "settlement_month must be strictly after last_settled_month")
    # Count completed dedicated loads reconciled inside the half-open month.
    start, end = month_window(year, month)
    completed = 0
    for s in store.shipments.values():
        if (s["customer_id"] == a["customer_id"] and s["trailer_id"] == a["trailer_id"]
                and s["status"] == "RECONCILED" and s["reconciled_at"] is not None
                and start <= s["reconciled_at"] < end):
            completed += 1
    floor_loads = commitment_floor_loads(a["committed_loads_per_month"])
    if completed < floor_loads:  # strict less-than triggers; equality is compliant
        fee = (floor_loads - completed) * SHORTFALL_FEE_PER_LOAD_CENTS
        a["shortfall_fees_total_cents"] += fee
        a["shortfall_events"] += 1
    a["last_settled_month"] = sm
    touch(a)
    return success(ser_agreement(a))
