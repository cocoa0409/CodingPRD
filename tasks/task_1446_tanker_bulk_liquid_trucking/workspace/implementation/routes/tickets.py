"""Meter tickets (read), delivery tickets (read + close), retain samples
(PRD 3.4-3.5)."""
from flask import Blueprint, request

from authz import ALL_ROLES, DRIVER, SAFETY_OFFICER, require_roles
from calc import (
    FLAG_SUSPEND_THRESHOLD, RETAIN_SAMPLE_DAYS, active_agreement_for,
    allowed_loss_gal, closed_meter_ticket, net60_gallons, variance_gallons,
)
from cascades import release_trailer
from db import store
from errors import err
from respond import success
from serialize import ser_delivery_ticket, ser_meter_ticket, ser_retain_sample
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_int, req_number, sorted_by_creation, touch,
)
from timeutil import add_days

bp = Blueprint("tickets", __name__)


# ---------------------------------------------------------------------------
# Meter tickets (read-only surface; lifecycle rides on shipment actions)
# ---------------------------------------------------------------------------

@bp.route("/meter-tickets", methods=["GET"])
def list_meter_tickets():
    require_roles(ALL_ROLES)
    shipment_id = request.args.get("shipment_id")
    rack_id = request.args.get("rack_id")
    items = [t for t in store.meter_tickets.values()
             if (shipment_id is None or t["shipment_id"] == shipment_id)
             and (rack_id is None or t["rack_id"] == rack_id)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_meter_ticket(t) for t in page],
                   response_type="array", pagination=pagination)


@bp.route("/meter-tickets/<tid>", methods=["GET"])
def get_meter_ticket(tid):
    require_roles(ALL_ROLES)
    return success(ser_meter_ticket(get_or_404(store.meter_tickets, "meter_tickets", tid)))


# ---------------------------------------------------------------------------
# Delivery tickets
# ---------------------------------------------------------------------------

@bp.route("/delivery-tickets", methods=["GET"])
def list_delivery_tickets():
    require_roles(ALL_ROLES)
    shipment_id = request.args.get("shipment_id")
    items = [t for t in store.delivery_tickets.values()
             if shipment_id is None or t["shipment_id"] == shipment_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_delivery_ticket(t) for t in page],
                   response_type="array", pagination=pagination)


@bp.route("/delivery-tickets/<tid>", methods=["GET"])
def get_delivery_ticket(tid):
    require_roles(ALL_ROLES)
    return success(ser_delivery_ticket(get_or_404(store.delivery_tickets, "delivery_tickets", tid)))


@bp.route("/delivery-tickets/<tid>/close", methods=["POST"])
def close_delivery_ticket(tid):
    uid, _role = require_roles([DRIVER])
    # Priority 3: existence.
    t = get_or_404(store.delivery_tickets, "delivery_tickets", tid)
    s = store.shipments[t["shipment_id"]]
    # Priority 2 identity: only the assigned driver closes the ticket.
    if uid != s["driver_id"]:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Only the assigned driver may close the delivery ticket")
    # Priority 4: shape.
    data = json_body()
    reject_unknown(data, {"delivered_observed_gal", "delivered_temp_F", "retain_sample_ml"})
    delivered_observed = req_number(data, "delivered_observed_gal", minimum=0, exclusive_minimum=True)
    delivered_temp = req_number(data, "delivered_temp_F")
    retain_ml = req_int(data, "retain_sample_ml", minimum=1)
    # Priority 6: the ticket must still be OPEN.
    if t["status"] != "OPEN":
        raise err("ERR_DELIVERY_TICKET_NOT_OPEN",
                  "Delivery close requires the ticket to be OPEN")
    # Computations (1dp round-half-up); equality on the allowance ACCEPTS.
    product = store.products[s["product_id"]]
    delivered_net60 = net60_gallons(delivered_observed, product["temp_coeff_per_degF"], delivered_temp)
    meter = closed_meter_ticket(s["id"])
    loaded_net60 = meter["net60_gallons"]
    allowed = allowed_loss_gal(s["route_miles"])
    variance = variance_gallons(loaded_net60, delivered_net60)
    accepted = variance <= allowed
    # Commit: ticket close, retain sample, trailer release, shipment advance.
    t["delivered_observed_gal"] = delivered_observed
    t["delivered_temp_F"] = delivered_temp
    t["delivered_net60_gal"] = delivered_net60
    t["loaded_net60_gal"] = loaded_net60
    t["allowed_loss_gal"] = allowed
    t["variance_gallons"] = variance
    t["closed_at"] = store.clock
    t["closed_by_driver_id"] = uid
    t["status"] = "CLOSED_ACCEPTED" if accepted else "CLOSED_VARIANCE"
    touch(t)
    sample = {
        "id": new_id(),
        "_seq": next(store.seq),
        "shipment_id": s["id"],
        "delivery_ticket_id": t["id"],
        "quantity_ml": retain_ml,
        "taken_at": store.clock,
        "retain_until": add_days(store.clock, RETAIN_SAMPLE_DAYS),
        "status": "RETAINED",
    }
    sample.update(new_common_fields())
    store.retain_samples[sample["id"]] = sample
    release_trailer(s["trailer_id"])
    if accepted:
        s["status"] = "DELIVERED"
        touch(s)
    else:
        s["status"] = "VARIANCE_REVIEW"
        touch(s)
        # Variance cascade: flag the matching ACTIVE dedicated agreement; the
        # counter reaching FLAG_SUSPEND_THRESHOLD suspends the agreement.
        agr = active_agreement_for(s["customer_id"], s["trailer_id"])
        if agr is not None:
            agr["flagged_shipment_count"] += 1
            if agr["flagged_shipment_count"] >= FLAG_SUSPEND_THRESHOLD:
                agr["status"] = "SUSPENDED"
            touch(agr)
    return success(ser_delivery_ticket(t))


# ---------------------------------------------------------------------------
# Retain samples
# ---------------------------------------------------------------------------

@bp.route("/retain-samples", methods=["GET"])
def list_retain_samples():
    require_roles(ALL_ROLES)
    shipment_id = request.args.get("shipment_id")
    ticket_id = request.args.get("delivery_ticket_id")
    items = [smp for smp in store.retain_samples.values()
             if (shipment_id is None or smp["shipment_id"] == shipment_id)
             and (ticket_id is None or smp["delivery_ticket_id"] == ticket_id)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_retain_sample(smp) for smp in page],
                   response_type="array", pagination=pagination)


@bp.route("/retain-samples/<sid>", methods=["GET"])
def get_retain_sample(sid):
    require_roles(ALL_ROLES)
    return success(ser_retain_sample(get_or_404(store.retain_samples, "retain_samples", sid)))


@bp.route("/retain-samples/<sid>/dispose", methods=["POST"])
def dispose_retain_sample(sid):
    require_roles([SAFETY_OFFICER])
    smp = get_or_404(store.retain_samples, "retain_samples", sid)
    reject_unknown(json_body(), set())
    if smp["status"] != "RETAINED":
        raise err("ERR_SAMPLE_NOT_RETAINED", "Dispose requires the sample to be RETAINED")
    if not store.clock > smp["retain_until"]:
        raise err("ERR_SAMPLE_STILL_IN_RETENTION",
                  "The sample is still within its retention period")
    smp["status"] = "DISPOSED"
    touch(smp)
    return success(ser_retain_sample(smp))
