"""Shipments: creation, OCC revision, planning, loading, departure (PRD 3.3-3.4).

The plan endpoint runs the full validation chain in the PRD 2.8 pipeline
order: auth -> authz -> existence -> shape -> (OCC n/a) -> state gates ->
business safety -> temporal -> constraint -> referential -> fiscal.
"""
from datetime import datetime, timezone

from flask import Blueprint, request

from authz import (
    CUSTOMER_REP, DISPATCHER, DRIVER, FLEET_ADMIN, SAFETY_OFFICER,
    TERMINAL_OPERATOR, ALL_ROLES, require_customer_identity, require_roles,
)
from calc import (
    WASH_RANK, approved_spill_plan, closed_meter_ticket, find_rule,
    net60_gallons, open_meter_ticket, plan_estimate_cents, billing_total_cents,
    shortage_credit_cents, expected_gross_lb, WEIGHT_SUM_TOLERANCE_PCT, D, rhup1,
)
from cascades import recompute_exposure, release_shipment_plan
from db import store
from errors import err, invalid_request
from respond import success
from serialize import ser_meter_ticket, ser_shipment
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_datetime, req_field, req_int, req_number, req_str,
    sorted_by_creation, touch,
)

bp = Blueprint("shipments", __name__)

SHIPMENT_CREATE_FIELDS = {"customer_id", "product_id", "ordered_gallons",
                          "route_miles", "rate_per_gal_cents"}
SHIPMENT_PATCH_FIELDS = {"ordered_gallons", "route_miles", "rate_per_gal_cents",
                         "expected_shipment_version"}
PLAN_FIELDS = {"trailer_id", "driver_id", "rack_id", "rack_window_start",
               "rack_window_end", "wash_cert_id"}
CLOSE_METER_FIELDS = {"meter_start_gal", "meter_end_gal", "observed_temp_F"}
WEIGHT_FIELDS = {"steer_lb", "drive_lb", "trailer_lb"}

# Trailer is ASSIGNED while a shipment in one of these statuses references it.
WINDOW_BLOCKING_STATUSES = ("PLANNED", "LOADING", "LOADED")


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    uid, role = require_roles([DISPATCHER, CUSTOMER_REP])
    data = json_body()
    # Priority 2 identity: a CustomerRep may only create for its own customer.
    if role == CUSTOMER_REP and data.get("customer_id") is not None:
        require_customer_identity(uid, data["customer_id"])
    # Priority 3: body-reference existence, left-to-right.
    customer = product = None
    if data.get("customer_id") is not None:
        customer = get_or_404(store.customers, "customers", data["customer_id"])
    if data.get("product_id") is not None:
        product = get_or_404(store.products, "products", data["product_id"])
    # Priority 4: shape.
    reject_unknown(data, SHIPMENT_CREATE_FIELDS)
    req_field(data, "customer_id")
    req_field(data, "product_id")
    ordered = req_int(data, "ordered_gallons", minimum=1)
    route_miles = req_int(data, "route_miles", minimum=1)
    rate = req_int(data, "rate_per_gal_cents", minimum=1)
    # Priority 6: referenced-entity state gate — customer must be ACTIVE.
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_NOT_ACTIVE",
                  "Shipment create requires the customer to be ACTIVE")
    s = {
        "id": new_id(),
        "_seq": next(store.seq),
        "customer_id": customer["id"],
        "product_id": product["id"],
        "ordered_gallons": ordered,
        "route_miles": route_miles,
        "rate_per_gal_cents": rate,
        "trailer_id": None,
        "driver_id": None,
        "rack_id": None,
        "wash_cert_id": None,
        "rack_window_start": None,
        "rack_window_end": None,
        "weights_verified_at": None,
        "placards_confirmed": False,
        "provisional_total_cents": None,
        "final_total_cents": None,
        "reconciled_at": None,
        "resolution_note": None,
        "status": "DRAFT",
    }
    s.update(new_common_fields())
    store.shipments[s["id"]] = s
    return success(ser_shipment(s), status=201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    require_roles(ALL_ROLES)
    filters = {k: request.args.get(k) for k in
               ("customer_id", "product_id", "trailer_id", "driver_id",
                "rack_id", "wash_cert_id", "status")}
    items = []
    for s in store.shipments.values():
        if any(v is not None and s[k] != v for k, v in filters.items()):
            continue
        items.append(s)
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_shipment(s) for s in page],
                   response_type="array", pagination=pagination)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    require_roles(ALL_ROLES)
    return success(ser_shipment(get_or_404(store.shipments, "shipments", sid)))


@bp.route("/shipments/<sid>", methods=["PATCH"])
def patch_shipment(sid):
    require_roles([DISPATCHER])
    s = get_or_404(store.shipments, "shipments", sid)
    data = json_body()
    # Priority 4: shape — the OCC field is non-optional input (PRD 2.7).
    reject_unknown(data, SHIPMENT_PATCH_FIELDS)
    expected = req_int(data, "expected_shipment_version")
    new_values = {}
    if "ordered_gallons" in data and data["ordered_gallons"] is not None:
        new_values["ordered_gallons"] = req_int(data, "ordered_gallons", minimum=1)
    if "route_miles" in data and data["route_miles"] is not None:
        new_values["route_miles"] = req_int(data, "route_miles", minimum=1)
    if "rate_per_gal_cents" in data and data["rate_per_gal_cents"] is not None:
        new_values["rate_per_gal_cents"] = req_int(data, "rate_per_gal_cents", minimum=1)
    # Priority 5: optimistic concurrency.
    if expected != s["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_shipment_version does not match the shipment's current version")
    # Priority 6: revision is available only while DRAFT.
    if s["status"] != "DRAFT":
        raise err("ERR_SHIPMENT_INVALID_STATE",
                  "Only a DRAFT shipment's commercial terms may be revised")
    s.update(new_values)
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/plan", methods=["POST"])
def plan_shipment(sid):
    require_roles([DISPATCHER])
    # Priority 3: path id, then body-reference ids left-to-right.
    s = get_or_404(store.shipments, "shipments", sid)
    data = json_body()
    trailer = driver = rack = cert = None
    if data.get("trailer_id") is not None:
        trailer = get_or_404(store.trailers, "trailers", data["trailer_id"])
    if data.get("driver_id") is not None:
        driver = get_or_404(store.drivers, "drivers", data["driver_id"])
    if data.get("rack_id") is not None:
        rack = get_or_404(store.racks, "racks", data["rack_id"])
    if data.get("wash_cert_id") is not None:
        cert = get_or_404(store.wash_certs, "wash_certs", data["wash_cert_id"])
    # Priority 4: shape.
    reject_unknown(data, PLAN_FIELDS)
    req_field(data, "trailer_id")
    req_field(data, "driver_id")
    req_field(data, "rack_id")
    w_start = req_datetime(data, "rack_window_start")
    w_end = req_datetime(data, "rack_window_end")
    if w_end <= w_start:
        raise invalid_request("rack_window_end must be later than rack_window_start")
    if "wash_cert_id" in data and data["wash_cert_id"] is not None \
            and not isinstance(data["wash_cert_id"], str):
        raise invalid_request("Field wash_cert_id must be a string")
    product = store.products[s["product_id"]]
    customer = store.customers[s["customer_id"]]

    # Priority 6: state gates.
    if s["status"] != "DRAFT":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Plan requires the shipment to be DRAFT")
    if driver["status"] != "ACTIVE":
        raise err("ERR_DRIVER_NOT_ACTIVE", "Plan requires an ACTIVE driver")
    if trailer["status"] != "AVAILABLE":
        raise err("ERR_TRAILER_NOT_AVAILABLE", "Plan requires the trailer to be AVAILABLE")
    if cert is not None:
        if cert["status"] != "CERTIFIED":
            raise err("ERR_CERT_INVALID_STATE",
                      "An attached certificate must be CERTIFIED")
        if cert["trailer_id"] != trailer["id"]:
            raise err("ERR_CERT_INVALID_STATE",
                      "The certificate belongs to a different trailer")
    elif trailer["last_product_group"] is not None:
        # No certificate attached: one is mandatory when the compatibility
        # rule imposes a wash above NONE (a missing certificate cannot be
        # CERTIFIED). Missing/forbidden rules surface at the safety step.
        peek = find_rule(trailer["last_product_group"], product["compatibility_group"])
        if (peek is not None and not peek["forbidden"]
                and peek["required_wash_level"] != "NONE"):
            raise err("ERR_CERT_INVALID_STATE",
                      "A CERTIFIED wash certificate is required for this prior-load pair")

    # Priority 7: business safety — compatibility, wash rank, endorsements.
    requirement = "NONE"
    if trailer["last_product_group"] is not None:
        rule = find_rule(trailer["last_product_group"], product["compatibility_group"])
        if rule is None:
            raise err("ERR_COMPATIBILITY_RULE_MISSING",
                      "No compatibility rule exists for (%s, %s)"
                      % (trailer["last_product_group"], product["compatibility_group"]))
        if rule["forbidden"]:
            raise err("ERR_PRODUCT_INCOMPATIBILITY_FORBIDDEN",
                      "The pair (%s, %s) may never be hauled consecutively"
                      % (trailer["last_product_group"], product["compatibility_group"]))
        requirement = rule["required_wash_level"]
    if cert is not None and requirement != "NONE":
        if WASH_RANK[cert["wash_level"]] < WASH_RANK[requirement]:
            raise err("ERR_WASH_LEVEL_INSUFFICIENT",
                      "Certificate wash level %s is below required %s"
                      % (cert["wash_level"], requirement))
    if not driver["tanker_endorsement"]:
        raise err("ERR_DRIVER_ENDORSEMENT_MISSING",
                  "Driver lacks the tanker (N) endorsement")
    if product["hazmat_class"] != "NONE" and not driver["hazmat_endorsement"]:
        raise err("ERR_DRIVER_ENDORSEMENT_MISSING",
                  "Driver lacks the hazmat (H) endorsement")

    # Priority 8: temporal — operating hours, rack conflict, cert expiry,
    # endorsement expiry.
    day = w_start.date()
    if w_end.date() != day:
        raise err("ERR_WINDOW_OUTSIDE_OPERATING_HOURS",
                  "Rack window must lie on a single UTC calendar day")
    open_dt = datetime(day.year, day.month, day.day, rack["open_hour"], tzinfo=timezone.utc)
    close_dt = datetime(day.year, day.month, day.day, rack["close_hour"], tzinfo=timezone.utc)
    if w_start < open_dt or w_end > close_dt:
        raise err("ERR_WINDOW_OUTSIDE_OPERATING_HOURS",
                  "Rack window must lie within [%02d:00, %02d:00] UTC"
                  % (rack["open_hour"], rack["close_hour"]))
    for o in store.shipments.values():
        if (o["id"] == s["id"] or o["rack_id"] != rack["id"]
                or o["status"] not in WINDOW_BLOCKING_STATUSES):
            continue
        if w_start < o["rack_window_end"] and o["rack_window_start"] < w_end:
            raise err("ERR_RACK_WINDOW_CONFLICT",
                      "Rack window overlaps another active shipment on this rack")
    if cert is not None and not (cert["expires_at"] > store.clock):
        # Plan-time use of an expired cert fails without mutating the cert.
        raise err("ERR_WASH_CERT_EXPIRED",
                  "The attached certificate expires before the current time")
    if driver["endorsement_expires_on"] < store.clock.date():
        raise err("ERR_DRIVER_ENDORSEMENT_EXPIRED",
                  "Driver endorsements expired before the current logical date")

    # Priority 9: capacity and dedication.
    if s["ordered_gallons"] > trailer["capacity_gallons"]:
        raise err("ERR_CAPACITY_EXCEEDED",
                  "ordered_gallons exceeds the trailer's capacity_gallons")
    if (trailer["dedicated_customer_id"] is not None
            and trailer["dedicated_customer_id"] != s["customer_id"]):
        raise err("ERR_TRAILER_DEDICATION_MISMATCH",
                  "Trailer is dedicated to a different customer")

    # Priority 10: referential — rack authorization for the product group.
    if product["compatibility_group"] not in rack["authorized_groups"]:
        raise err("ERR_RACK_NOT_AUTHORIZED_FOR_PRODUCT",
                  "Rack is not authorized for %s" % product["compatibility_group"])

    # Priority 11: fiscal credit gate (equality allowed).
    estimate = plan_estimate_cents(s["ordered_gallons"], s["rate_per_gal_cents"])
    if customer["exposure_cents"] + estimate > customer["credit_limit_cents"]:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED",
                  "Plan would push customer exposure above credit_limit_cents")

    # Commit: DRAFT -> PLANNED with trailer assign, cert hold, exposure.
    trailer["status"] = "ASSIGNED"
    touch(trailer)
    if cert is not None:
        cert["status"] = "HELD"
        touch(cert)
    s["trailer_id"] = trailer["id"]
    s["driver_id"] = driver["id"]
    s["rack_id"] = rack["id"]
    s["wash_cert_id"] = cert["id"] if cert is not None else None
    s["rack_window_start"] = w_start
    s["rack_window_end"] = w_end
    s["status"] = "PLANNED"
    touch(s)
    recompute_exposure(customer["id"])
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/unplan", methods=["POST"])
def unplan_shipment(sid):
    require_roles([DISPATCHER])
    s = get_or_404(store.shipments, "shipments", sid)
    reject_unknown(json_body(), set())
    if s["status"] != "PLANNED":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Unplan requires the shipment to be PLANNED")
    release_shipment_plan(s)
    s["status"] = "DRAFT"
    touch(s)
    recompute_exposure(s["customer_id"])
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/cancel", methods=["POST"])
def cancel_shipment(sid):
    uid, role = require_roles([DISPATCHER, CUSTOMER_REP])
    s = get_or_404(store.shipments, "shipments", sid)
    # Priority 2 identity: the owning CustomerRep may cancel.
    if role == CUSTOMER_REP:
        require_customer_identity(uid, s["customer_id"])
    reject_unknown(json_body(), set())
    if s["status"] not in ("DRAFT", "PLANNED"):
        raise err("ERR_SHIPMENT_INVALID_STATE",
                  "Cancel requires the shipment to be DRAFT or PLANNED")
    if s["status"] == "PLANNED":
        release_shipment_plan(s)
    s["status"] = "CANCELLED"
    touch(s)
    recompute_exposure(s["customer_id"])
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/check-in", methods=["POST"])
def check_in_shipment(sid):
    require_roles([TERMINAL_OPERATOR])
    s = get_or_404(store.shipments, "shipments", sid)
    reject_unknown(json_body(), set())
    # Priority 6: state gates (target state, driver still ACTIVE).
    if s["status"] != "PLANNED":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Check-in requires the shipment to be PLANNED")
    driver = store.drivers.get(s["driver_id"])
    if driver is None or driver["status"] != "ACTIVE":
        raise err("ERR_DRIVER_NOT_ACTIVE", "Driver is no longer ACTIVE")
    # Priority 7: endorsements re-validated at the gate.
    product = store.products[s["product_id"]]
    if not driver["tanker_endorsement"]:
        raise err("ERR_DRIVER_ENDORSEMENT_MISSING",
                  "Driver lacks the tanker (N) endorsement")
    if product["hazmat_class"] != "NONE" and not driver["hazmat_endorsement"]:
        raise err("ERR_DRIVER_ENDORSEMENT_MISSING",
                  "Driver lacks the hazmat (H) endorsement")
    # Priority 8: endorsement expiry, then the rack window being active.
    if driver["endorsement_expires_on"] < store.clock.date():
        raise err("ERR_DRIVER_ENDORSEMENT_EXPIRED",
                  "Driver endorsements expired before the current logical date")
    if not (s["rack_window_start"] <= store.clock < s["rack_window_end"]):
        raise err("ERR_RACK_WINDOW_NOT_ACTIVE",
                  "Logical clock is outside the reserved rack window")
    # Commit: PLANNED -> LOADING and a fresh OPEN meter ticket.
    t = {
        "id": new_id(),
        "_seq": next(store.seq),
        "shipment_id": s["id"],
        "rack_id": s["rack_id"],
        "opened_at": store.clock,
        "closed_at": None,
        "meter_start_gal": None,
        "meter_end_gal": None,
        "observed_temp_F": None,
        "observed_gallons": None,
        "net60_gallons": None,
        "closed_by_user_id": None,
        "status": "OPEN",
    }
    t.update(new_common_fields())
    store.meter_tickets[t["id"]] = t
    s["status"] = "LOADING"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/abort-loading", methods=["POST"])
def abort_loading(sid):
    require_roles([TERMINAL_OPERATOR])
    s = get_or_404(store.shipments, "shipments", sid)
    reject_unknown(json_body(), set())
    if s["status"] != "LOADING":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Abort-loading requires the shipment to be LOADING")
    ticket = open_meter_ticket(s["id"])
    if ticket is not None:
        ticket["status"] = "VOIDED"  # ticket history is retained
        touch(ticket)
    s["status"] = "PLANNED"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/close-meter", methods=["POST"])
def close_meter(sid):
    uid, _role = require_roles([TERMINAL_OPERATOR])
    s = get_or_404(store.shipments, "shipments", sid)
    data = json_body()
    # Priority 4: shape (end strictly greater than start).
    reject_unknown(data, CLOSE_METER_FIELDS)
    meter_start = req_number(data, "meter_start_gal", minimum=0)
    meter_end = req_number(data, "meter_end_gal", minimum=0)
    observed_temp = req_number(data, "observed_temp_F")
    if not D(meter_end) > D(meter_start):
        raise invalid_request("meter_end_gal must be strictly greater than meter_start_gal")
    # Priority 6: state.
    if s["status"] != "LOADING":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Close-meter requires the shipment to be LOADING")
    ticket = open_meter_ticket(s["id"])
    if ticket is None:
        raise err("ERR_SHIPMENT_INVALID_STATE", "Shipment has no OPEN meter ticket")
    product = store.products[s["product_id"]]
    trailer = store.trailers.get(s["trailer_id"])
    # Computations (1dp round-half-up).
    observed = rhup1(D(meter_end) - D(meter_start))
    net60 = net60_gallons(observed, product["temp_coeff_per_degF"], observed_temp)
    provisional = billing_total_cents(observed, s["rate_per_gal_cents"], 0)
    # Commit: ticket OPEN -> CLOSED, shipment LOADING -> LOADED, side effects.
    ticket["meter_start_gal"] = meter_start
    ticket["meter_end_gal"] = meter_end
    ticket["observed_temp_F"] = observed_temp
    ticket["observed_gallons"] = observed
    ticket["net60_gallons"] = net60
    ticket["closed_at"] = store.clock
    ticket["closed_by_user_id"] = uid
    ticket["status"] = "CLOSED"
    touch(ticket)
    if trailer is not None:
        trailer["last_product_group"] = product["compatibility_group"]
        touch(trailer)
    if s["wash_cert_id"] is not None:
        cert = store.wash_certs.get(s["wash_cert_id"])
        if cert is not None and cert["status"] == "HELD":
            cert["status"] = "CONSUMED"
            cert["consumed_by_shipment_id"] = s["id"]
            touch(cert)
    s["provisional_total_cents"] = provisional
    s["status"] = "LOADED"
    touch(s)
    recompute_exposure(s["customer_id"])
    return success(ser_meter_ticket(ticket))


@bp.route("/shipments/<sid>/record-weights", methods=["POST"])
def record_weights(sid):
    uid, _role = require_roles([TERMINAL_OPERATOR])
    s = get_or_404(store.shipments, "shipments", sid)
    data = json_body()
    reject_unknown(data, WEIGHT_FIELDS)
    steer = req_int(data, "steer_lb", minimum=0)
    drive = req_int(data, "drive_lb", minimum=0)
    trailer_lb = req_int(data, "trailer_lb", minimum=0)
    # Priority 6: state gates.
    if s["status"] != "LOADED":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Record-weights requires the shipment to be LOADED")
    if s["weights_verified_at"] is not None:
        raise err("ERR_WEIGHTS_ALREADY_VERIFIED",
                  "Weights have already been verified for this shipment")
    # Priority 7: axle compliance checks in the pinned order.
    trailer = store.trailers[s["trailer_id"]]
    product = store.products[s["product_id"]]
    ticket = closed_meter_ticket(s["id"])
    if steer > trailer["steer_axle_rating_lb"]:
        raise err("ERR_AXLE_LIMIT_EXCEEDED", "steer_lb exceeds the steer axle rating")
    if drive > trailer["drive_axle_rating_lb"]:
        raise err("ERR_AXLE_LIMIT_EXCEEDED", "drive_lb exceeds the drive axle rating")
    if trailer_lb > trailer["trailer_axle_rating_lb"]:
        raise err("ERR_AXLE_LIMIT_EXCEEDED", "trailer_lb exceeds the trailer axle rating")
    measured = steer + drive + trailer_lb
    if measured > trailer["gvwr_lb"]:
        raise err("ERR_GVWR_EXCEEDED", "Measured axle sum exceeds gvwr_lb")
    expected = expected_gross_lb(trailer, ticket["net60_gallons"], product["density_lb_per_gal"])
    if abs(measured - expected) > WEIGHT_SUM_TOLERANCE_PCT * expected:
        raise err("ERR_WEIGHT_SUM_INCONSISTENT",
                  "Measured sum deviates from expected gross by more than 3%")
    # Priority 9: segregation of duties — the weight verifier must differ
    # from the operator who closed the meter.
    if uid == ticket["closed_by_user_id"]:
        raise err("ERR_SAME_OPERATOR_SEGREGATION",
                  "The weight verifier must differ from the meter closer")
    s["weights_verified_at"] = store.clock
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/confirm-placards", methods=["POST"])
def confirm_placards(sid):
    require_roles([TERMINAL_OPERATOR])
    s = get_or_404(store.shipments, "shipments", sid)
    data = json_body()
    reject_unknown(data, {"observed_placard_code"})
    observed = req_str(data, "observed_placard_code")
    if s["status"] != "LOADED":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Confirm-placards requires the shipment to be LOADED")
    product = store.products[s["product_id"]]
    if observed != product["placard_code"]:
        raise err("ERR_PLACARD_MISMATCH",
                  "Observed placard code does not match the product placard code")
    s["placards_confirmed"] = True
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/depart", methods=["POST"])
def depart_shipment(sid):
    require_roles([DISPATCHER])
    s = get_or_404(store.shipments, "shipments", sid)
    reject_unknown(json_body(), set())
    # Priority 6: state gates in declaration order.
    if s["status"] != "LOADED":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Depart requires the shipment to be LOADED")
    if s["weights_verified_at"] is None:
        raise err("ERR_WEIGHTS_NOT_VERIFIED", "Depart requires verified weights")
    if not s["placards_confirmed"]:
        raise err("ERR_PLACARDS_NOT_CONFIRMED", "Depart requires confirmed placards")
    # Priority 7: an APPROVED, unexpired spill response plan for the pair.
    if approved_spill_plan(s["customer_id"], s["product_id"]) is None:
        raise err("ERR_SPILL_PLAN_NOT_APPROVED",
                  "No APPROVED, unexpired spill response plan for this customer and product")
    s["status"] = "IN_TRANSIT"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/start-delivery", methods=["POST"])
def start_delivery(sid):
    uid, _role = require_roles([DRIVER])
    s = get_or_404(store.shipments, "shipments", sid)
    # Priority 2 identity: only the assigned driver starts the delivery.
    if uid != s["driver_id"]:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Only the assigned driver may start the delivery")
    reject_unknown(json_body(), set())
    if s["status"] != "IN_TRANSIT":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Start-delivery requires the shipment to be IN_TRANSIT")
    t = {
        "id": new_id(),
        "_seq": next(store.seq),
        "shipment_id": s["id"],
        "opened_at": store.clock,
        "closed_at": None,
        "delivered_observed_gal": None,
        "delivered_temp_F": None,
        "delivered_net60_gal": None,
        "loaded_net60_gal": None,
        "allowed_loss_gal": None,
        "variance_gallons": None,
        "closed_by_driver_id": None,
        "status": "OPEN",
    }
    t.update(new_common_fields())
    store.delivery_tickets[t["id"]] = t
    s["status"] = "DELIVERING"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/resolve-variance", methods=["POST"])
def resolve_variance(sid):
    require_roles([SAFETY_OFFICER])
    s = get_or_404(store.shipments, "shipments", sid)
    data = json_body()
    reject_unknown(data, {"resolution_note"})
    note = req_str(data, "resolution_note")
    if s["status"] != "VARIANCE_REVIEW":
        raise err("ERR_SHIPMENT_INVALID_STATE",
                  "Resolve-variance requires the shipment to be VARIANCE_REVIEW")
    s["resolution_note"] = note
    s["status"] = "DELIVERED"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/reconcile", methods=["POST"])
def reconcile_shipment(sid):
    require_roles([FLEET_ADMIN])
    s = get_or_404(store.shipments, "shipments", sid)
    reject_unknown(json_body(), set())
    if s["status"] != "DELIVERED":
        raise err("ERR_SHIPMENT_INVALID_STATE", "Reconcile requires the shipment to be DELIVERED")
    # Priority 10 referential: no open spill incident on this shipment.
    for i in store.spill_incidents.values():
        if i["shipment_id"] == s["id"] and i["status"] in ("REPORTED", "UNDER_REVIEW"):
            raise err("ERR_OPEN_INCIDENT",
                      "An open spill incident blocks reconciliation")
    # Final billing: net-60 delivered basis minus the shortage credit.
    ticket = None
    for t in store.delivery_tickets.values():
        if t["shipment_id"] == s["id"] and t["status"] in ("CLOSED_ACCEPTED", "CLOSED_VARIANCE"):
            ticket = t
            break
    credit = shortage_credit_cents(ticket["loaded_net60_gal"],
                                   ticket["delivered_net60_gal"],
                                   ticket["allowed_loss_gal"],
                                   s["rate_per_gal_cents"])
    s["final_total_cents"] = billing_total_cents(
        ticket["delivered_net60_gal"], s["rate_per_gal_cents"], credit)
    s["reconciled_at"] = store.clock
    s["status"] = "RECONCILED"
    touch(s)
    recompute_exposure(s["customer_id"])
    return success(ser_shipment(s))
