"""Lookups, lazy re-derivations and shared state helpers.

Lazy re-derivation is never a mutation: it refreshes derived fields in place and
must not bump version or refresh updated_at.
"""
from db import base_record, db, now, ordered
from errors import api_error
from services import calc
from util import add_days, whole_days

ACTIVE_RETURN_LOGISTICS = ("REQUESTED", "PICKUP_SCHEDULED", "PICKED_UP",
                           "INSPECTED", "DISPOSITIONED")
OPEN_CLAIM_STATUSES = ("SUBMITTED", "EVIDENCE_REQUESTED")
LIVE_FULFILLMENT = ("CREATED", "IN_TRANSIT", "DELIVERED", "DAMAGED_REPORTED")


# ------------------------------------------------------------- derivations ---
def derive_order(order):
    """Advance the trial clock and refresh the live nights_slept reading."""
    clock = now()
    if order["trial_status"] == "BREAK_IN":
        ends = order["break_in_ends_at"]
        if ends is not None and clock >= ends:
            order["trial_status"] = "TRIAL_ACTIVE"
    if order["trial_status"] == "TRIAL_ACTIVE":
        ends = order["trial_ends_at"]
        if ends is not None and clock >= ends:
            order["trial_status"] = "TRIAL_EXPIRED"
    if order["delivered_at"] is not None and not order["_nights_frozen"]:
        elapsed = whole_days(order["delivered_at"], clock)
        order["nights_slept"] = max(0, elapsed)
    return order


def customer_signals(customer_id):
    return ordered([s for s in db.abuse_signals.values()
                    if s["customer_id"] == customer_id])


def derive_customer(customer):
    """Re-derive both abuse scores, then the posture cascade in strict order."""
    clock = now()
    signals = customer_signals(customer["id"])
    rolling, lifetime = calc.abuse_scores(signals, clock)
    customer["abuse_score_rolling"] = rolling
    customer["abuse_score_lifetime"] = lifetime
    customer["signal_count"] = len(signals)
    if rolling >= calc.ABUSE_BLOCK_THRESHOLD:
        customer["status"] = "BLOCKED"
        customer["trial_block_until"] = add_days(clock, calc.ABUSE_BLOCK_DAYS)
    elif (customer["trial_block_until"] is not None
          and clock < customer["trial_block_until"]):
        customer["status"] = "BLOCKED"
    elif rolling >= calc.ABUSE_RESTRICT_THRESHOLD:
        customer["status"] = "TRIAL_RESTRICTED"
        customer["trial_block_until"] = None
    else:
        customer["status"] = "ACTIVE"
        customer["trial_block_until"] = None
    return customer


def add_signal(customer, signal_type, recorded_at=None, source_note=None):
    signal = base_record(versioned=False)
    signal.update({
        "customer_id": customer["id"],
        "signal_type": signal_type,
        "recorded_at": recorded_at or now(),
        "weight": calc.signal_weight(signal_type),
        "source_note": source_note,
    })
    db.abuse_signals[signal["id"]] = signal
    return signal


# ----------------------------------------------------------------- lookups ---
def _fetch(collection, key, error_id, label):
    if not isinstance(key, str):
        raise api_error(error_id, "%s not found" % label)
    record = collection.get(key)
    if record is None:
        raise api_error(error_id, "%s %s not found" % (label, key))
    return record


def get_customer(customer_id):
    customer = _fetch(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND",
                      "Customer")
    return derive_customer(customer)


def get_model(model_id):
    return _fetch(db.mattress_models, model_id, "ERR_CATALOG_NOT_FOUND",
                  "Mattress model")


def get_bundle(bundle_id):
    return _fetch(db.promotion_bundles, bundle_id, "ERR_CATALOG_NOT_FOUND",
                  "Promotion bundle")


def get_retail_partner(partner_id):
    return _fetch(db.retail_partners, partner_id, "ERR_PARTNER_NOT_FOUND",
                  "Retail partner")


def get_disposition_partner(partner_id):
    return _fetch(db.disposition_partners, partner_id,
                  "ERR_PARTNER_NOT_FOUND", "Disposition partner")


def get_order(order_id):
    order = _fetch(db.trial_orders, order_id, "ERR_ORDER_NOT_FOUND",
                   "Trial order")
    return derive_order(order)


def get_return_case(case_id):
    return _fetch(db.return_cases, case_id, "ERR_RETURN_CASE_NOT_FOUND",
                  "Return case")


def get_route(route_id):
    return _fetch(db.pickup_routes, route_id, "ERR_ROUTE_NOT_FOUND",
                  "Pickup route")


def get_appointment(appointment_id):
    return _fetch(db.pickup_appointments, appointment_id,
                  "ERR_APPOINTMENT_NOT_FOUND", "Pickup appointment")


def get_assignment(assignment_id):
    return _fetch(db.disposition_assignments, assignment_id,
                  "ERR_ASSIGNMENT_NOT_FOUND", "Disposition assignment")


def get_refund(refund_id):
    return _fetch(db.refund_authorizations, refund_id, "ERR_REFUND_NOT_FOUND",
                  "Refund authorization")


def get_exchange(exchange_id):
    return _fetch(db.comfort_exchanges, exchange_id, "ERR_EXCHANGE_NOT_FOUND",
                  "Comfort exchange")


def get_claim(claim_id):
    return _fetch(db.quality_claims, claim_id, "ERR_CLAIM_NOT_FOUND",
                  "Quality claim")


def get_attribution_claim(claim_id):
    return _fetch(db.attribution_claims, claim_id,
                  "ERR_ATTRIBUTION_CLAIM_NOT_FOUND", "Attribution claim")


# ------------------------------------------------------------- graph walks ---
def order_of_case(case):
    return get_order(case["order_id"])


def model_of_order(order):
    return db.mattress_models[order["model_id"]]


def bundle_of_order(order):
    if order["bundle_id"] is None:
        return None
    return db.promotion_bundles[order["bundle_id"]]


def customer_of_order(order):
    return get_customer(order["customer_id"])


def household_customers(household_hash):
    return [c for c in db.customers.values()
            if c["household_hash"] == household_hash]


def orders_of_customer(customer_id):
    return [o for o in db.trial_orders.values()
            if o["customer_id"] == customer_id]


def active_return_cases(order_id):
    return [c for c in db.return_cases.values()
            if c["order_id"] == order_id
            and c["logistics_status"] in ACTIVE_RETURN_LOGISTICS]


def open_quality_claims(order_id, exclude_claim_id=None):
    return [c for c in db.quality_claims.values()
            if c["order_id"] == order_id
            and c["status"] in OPEN_CLAIM_STATUSES
            and c["id"] != exclude_claim_id]


def appointments_of_case(case_id):
    return ordered([a for a in db.pickup_appointments.values()
                    if a["return_case_id"] == case_id])


def appointments_of_route(route_id):
    return ordered([a for a in db.pickup_appointments.values()
                    if a["route_id"] == route_id])


def refresh_route_capacity(route):
    booked = sum(a["units"] for a in db.pickup_appointments.values()
                 if a["route_id"] == route["id"]
                 and a["status"] in ("BOOKED", "COMPLETED"))
    route["booked_units"] = booked
    route["available_units"] = route["capacity_units"] - booked
    return route


def partner_day_booked_units(partner_id, intake_date):
    return sum(a["units"] for a in db.disposition_assignments.values()
               if a["partner_id"] == partner_id
               and a["intake_date"] == intake_date
               and a["status"] in ("ASSIGNED", "DELIVERED"))
