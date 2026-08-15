"""Taxable events: record, classify, rate, reclassify, void."""
from flask import Blueprint, request

import errors
from errors import raise_err
from store import DB
from auth import (
    require_roles, ALL_READ_ROLES, body_dict, req_str, req_int, req_dt, opt_str,
    opt_bool, new_entity, touch, get_or_404, public, paginate,
)
from response import success_object, success_list
from utiltime import fmt_dt, now_dt, period_of_date
import services

bp = Blueprint("events", __name__)

EVENT_FIELDS = ["registration_id", "jurisdiction_id", "product_class_id", "event_date",
                "quantity_units", "customer_reference", "is_export", "period",
                "determination", "exemption_certificate_id", "bonded_movement_id",
                "gross_tax_cents", "tax_cents", "return_id", "status"]


def ser_event(e):
    return public(e, EVENT_FIELDS)


@bp.post("/taxable-events")
def create_event():
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    registration_id = req_str(body, "registration_id")
    jurisdiction_id = req_str(body, "jurisdiction_id")
    product_class_id = req_str(body, "product_class_id")
    event_dt = req_dt(body, "event_date")
    quantity_units = req_int(body, "quantity_units", minimum=1)
    customer_reference = opt_str(body, "customer_reference")
    is_export = opt_bool(body, "is_export", default=False)
    reg = get_or_404(DB.registrations, registration_id, "Registration")
    jurisdiction = get_or_404(DB.jurisdictions, jurisdiction_id, "Jurisdiction")
    get_or_404(DB.product_classes, product_class_id, "ProductClass")
    if reg["status"] != "ACTIVE":
        raise_err(errors.ERR_REG_NOT_ACTIVE,
                  "Registration must be ACTIVE to record taxable activity")
    if jurisdiction_id != reg["jurisdiction_id"]:
        raise_err(errors.ERR_REG_JUR_MISMATCH,
                  "event.jurisdiction_id must equal the registration's jurisdiction")
    period = period_of_date(jurisdiction["return_frequency"], event_dt)
    ev = new_entity({
        "registration_id": registration_id,
        "jurisdiction_id": jurisdiction_id,
        "product_class_id": product_class_id,
        "event_date": fmt_dt(event_dt),
        "quantity_units": quantity_units,
        "customer_reference": customer_reference,
        "is_export": is_export,
        "period": period,
        "determination": "STANDARD",
        "exemption_certificate_id": None,
        "bonded_movement_id": None,
        "gross_tax_cents": 0,
        "tax_cents": 0,
        "return_id": None,
        "status": "DRAFT",
        "_event_dt": event_dt,
        "_tax_rate_id": None,
        "_rate_millicents_used": None,
    })
    DB.events[ev["id"]] = ev
    return success_object(ser_event(ev), 201)


@bp.get("/taxable-events/<eid>")
def get_event(eid):
    require_roles(ALL_READ_ROLES)
    ev = get_or_404(DB.events, eid, "TaxableEvent")
    return success_object(ser_event(ev))


@bp.get("/taxable-events")
def list_events():
    require_roles(ALL_READ_ROLES)
    items = list(DB.events.values())
    for param in ("registration_id", "jurisdiction_id", "product_class_id",
                  "return_id", "exemption_certificate_id", "bonded_movement_id",
                  "status", "period"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    data, limit, offset, total = paginate(items, ser_event)
    return success_list(data, limit, offset, total)


@bp.post("/taxable-events/<eid>/classify")
def classify_event(eid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    ev = get_or_404(DB.events, eid, "TaxableEvent")
    if ev["status"] != "DRAFT":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Event in status {ev['status']} cannot be classified")
    reg = DB.registrations[ev["registration_id"]]
    if reg["status"] != "ACTIVE":
        raise_err(errors.ERR_REG_NOT_ACTIVE,
                  "Registration must be ACTIVE to classify an event")
    if not services.any_rate_for_pair(ev["jurisdiction_id"], ev["product_class_id"]):
        raise_err(errors.ERR_NO_APPLICABLE_RATE,
                  "The product class / jurisdiction pairing is not taxable-identified")
    ev["status"] = "CLASSIFIED"
    touch(ev)
    return success_object(ser_event(ev))


@bp.post("/taxable-events/<eid>/rate")
def rate_event(eid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    cert_id = opt_str(body, "exemption_certificate_id")
    movement_id = opt_str(body, "bonded_movement_id")
    ev = get_or_404(DB.events, eid, "TaxableEvent")
    cert = get_or_404(DB.certificates, cert_id, "ExemptionCertificate") if cert_id else None
    movement = get_or_404(DB.movements, movement_id, "BondedMovement") if movement_id else None
    if ev["status"] not in ("CLASSIFIED", "ADJUSTED"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Event in status {ev['status']} cannot be rated")
    ev["_status_before_rate"] = ev["status"]
    reg = DB.registrations[ev["registration_id"]]
    if reg["status"] != "ACTIVE":
        raise_err(errors.ERR_REG_NOT_ACTIVE,
                  "Registration must be ACTIVE to rate an event")
    if ev["status"] == "CLASSIFIED":
        _target, is_open = services.period_open_target(
            ev["registration_id"], ev["jurisdiction_id"], ev["period"])
        if not is_open:
            raise_err(errors.ERR_PERIOD_LOCKED,
                      "The event's period is locked; route corrections through an amendment")
    # Linkage validation: certificate first, then movement, then rate window.
    if cert is not None:
        if cert["status"] != "ACTIVE":
            raise_err(errors.ERR_CERT_NOT_ACTIVE,
                      "The referenced exemption certificate is not ACTIVE")
        covers = (cert["_valid_from"] <= ev["_event_dt"] <= cert["_valid_to"]
                  and (cert["product_class_id"] is None
                       or cert["product_class_id"] == ev["product_class_id"])
                  and cert["customer_reference"] == ev["customer_reference"]
                  and cert["registration_id"] == ev["registration_id"])
        if cert["certificate_type"] == "EXPORT" and not ev["is_export"]:
            covers = False
        if not covers:
            raise_err(errors.ERR_CERT_NOT_APPLICABLE,
                      "The certificate does not cover this event")
    if movement is not None:
        if (movement["registration_id"] != ev["registration_id"]
                or movement["product_class_id"] != ev["product_class_id"]
                or movement["status"] not in ("IN_TRANSIT", "RECEIVED")):
            raise_err(errors.ERR_MOVEMENT_NOT_LINKABLE,
                      "The referenced bonded movement is not linkable to this event")
    resolved = services.resolve_rate(ev["jurisdiction_id"], ev["product_class_id"],
                                     ev["_event_dt"])
    if resolved is None:
        raise_err(errors.ERR_NO_APPLICABLE_RATE,
                  "No tax rate window contains the event date")

    from utiltime import rhu_div_1000
    gross = rhu_div_1000(ev["quantity_units"] * resolved["rate_millicents_per_unit"])
    tax = 0 if (cert is not None or movement is not None) else gross
    ev["exemption_certificate_id"] = cert_id
    ev["bonded_movement_id"] = movement_id
    ev["gross_tax_cents"] = gross
    ev["tax_cents"] = tax
    ev["determination"] = "STANDARD"
    ev["_tax_rate_id"] = resolved["id"]
    ev["_rate_millicents_used"] = resolved["rate_millicents_per_unit"]
    ev["status"] = "RATED"

    prior_status = ev["_status_before_rate"]
    if prior_status == "ADJUSTED":
        # ADJUSTED -> RATED inside an open amendment: values land on the amendment.
        target = DB.returns.get(ev.get("return_id"))
        touch(ev)
        if target is not None:
            services.recompute_return(target)
    else:
        target, locked = services.get_or_create_open_return(
            ev["registration_id"], ev["jurisdiction_id"], ev["period"])
        if not locked and target is not None:
            ev["return_id"] = target["id"]
        touch(ev)
        if not locked and target is not None:
            services.recompute_return(target)
    services.recompute_rollup(reg["registrant_id"])
    return success_object(ser_event(ev))


@bp.post("/taxable-events/<eid>/reclassify")
def reclassify_event(eid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    ev = get_or_404(DB.events, eid, "TaxableEvent")
    if ev["status"] == "RATED":
        containing = DB.returns.get(ev.get("return_id"))
        if containing is not None and containing["filing_status"] != "DRAFT":
            raise_err(errors.ERR_INVALID_STATE,
                      "The containing return is not in DRAFT; withdraw it first")
        new_status = "CLASSIFIED"
    elif ev["status"] == "RETURNED":
        containing = DB.returns.get(ev.get("return_id"))
        in_open_amendment = (containing is not None
                             and containing["amendment_of_id"] is not None
                             and containing["filing_status"] in ("DRAFT", "SUBMITTED"))
        if not in_open_amendment:
            raise_err(errors.ERR_INVALID_STATE,
                      "A returned event can only be reclassified inside an open amendment")
        jurisdiction = DB.jurisdictions[containing["jurisdiction_id"]]
        if services.audit_hold_blocks(containing["registration_id"],
                                      containing["jurisdiction_id"],
                                      containing["period"],
                                      jurisdiction["return_frequency"]):
            raise_err(errors.ERR_AUDIT_HOLD,
                      "An audit records hold covers this period")
        new_status = "ADJUSTED"
    else:
        raise_err(errors.ERR_INVALID_STATE,
                  f"Event in status {ev['status']} cannot be reclassified")
    ev["status"] = new_status
    ev["gross_tax_cents"] = 0
    ev["tax_cents"] = 0
    ev["exemption_certificate_id"] = None
    ev["bonded_movement_id"] = None
    ev["_tax_rate_id"] = None
    ev["_rate_millicents_used"] = None
    touch(ev)
    containing = DB.returns.get(ev.get("return_id"))
    if containing is not None:
        services.recompute_return(containing)
        reg = DB.registrations[containing["registration_id"]]
        services.recompute_rollup(reg["registrant_id"])
    return success_object(ser_event(ev))


@bp.post("/taxable-events/<eid>/void")
def void_event(eid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    ev = get_or_404(DB.events, eid, "TaxableEvent")
    if ev["status"] not in ("DRAFT", "CLASSIFIED"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Event in status {ev['status']} cannot be voided")
    ev["status"] = "VOIDED"
    touch(ev)
    return success_object(ser_event(ev))
