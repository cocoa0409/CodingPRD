"""Purchase orders, advance shipping notices, door receipt, violation
detection, evidence capture, assessment and voiding."""

from flask import Blueprint

import lookup
import serializers as ser
from core import (
    EVIDENCE_KINDS,
    ROLE_CATEGORY_BUYER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DC_INSPECTOR,
    ROLE_VENDOR,
    VIOLATION_FILING_WINDOW_HOURS,
    ApiError,
    authenticate,
    body_dict,
    clock,
    hours,
    invalid,
    new_append_only_record,
    new_record,
    object_response,
    opt_str,
    req_dt,
    req_enum,
    req_int,
    req_str,
    store,
    touch,
)
from derive import (
    assess_amounts,
    guide_governs,
    pinned_requirement,
    po_of_shipment,
    recompute_purchase_order,
    recompute_shipment_counters,
    recompute_violation_evidence_count,
    reconcile_vendor,
    vendor_of_shipment,
    violations_of_shipment,
)

bp = Blueprint("supply", __name__)

BUYER = (ROLE_CATEGORY_BUYER,)
VENDOR = (ROLE_VENDOR,)
INSPECTOR = (ROLE_DC_INSPECTOR,)
OFFICER = (ROLE_COMPLIANCE_OFFICER,)

LIVE_VIOLATION_STATES = ("DETECTED", "EVIDENCE_COMPLETE")


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------


@bp.post("/compliance/purchase-orders")
def create_purchase_order():
    authenticate(BUYER)
    body = body_dict()
    vendor_id = req_str(body, "vendor_id")
    po_number = req_str(body, "po_number", 1, 32)
    ordered_units = req_int(body, "ordered_units", 1)
    unit_cost_cents = req_int(body, "unit_cost_cents", 1)
    ship_window_start = req_dt(body, "ship_window_start")
    ship_window_end = req_dt(body, "ship_window_end")
    must_arrive_by = req_dt(body, "must_arrive_by")
    if ship_window_end <= ship_window_start:
        raise invalid("Field 'ship_window_end' must be later than 'ship_window_start'.")
    if must_arrive_by < ship_window_end:
        raise invalid("Field 'must_arrive_by' may not be earlier than 'ship_window_end'.")

    vendor = lookup.vendor(vendor_id)
    if vendor["status"] == "SOURCING_HOLD":
        raise ApiError(
            "ERR_VENDOR_SOURCING_HOLD",
            "New purchase orders are blocked while the vendor is on sourcing hold.",
        )

    order = new_record(
        vendor_id=vendor["id"],
        po_number=po_number,
        ordered_units=ordered_units,
        unit_cost_cents=unit_cost_cents,
        ship_window_start=ship_window_start,
        ship_window_end=ship_window_end,
        must_arrive_by=must_arrive_by,
        status="OPEN",
        received_units=0,
        first_receipt_at=None,
    )
    store.purchase_orders[order["id"]] = order
    return object_response(ser.purchase_order_out(order), 201)


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------


@bp.post("/compliance/purchase-orders/<identifier>/shipments")
def create_shipment(identifier):
    user_id, _role = authenticate(VENDOR)
    body = body_dict()
    asn_number = req_str(body, "asn_number", 1, 32)
    shipped_units = req_int(body, "shipped_units", 1)
    carton_count = req_int(body, "carton_count", 1)

    order = lookup.purchase_order(identifier)
    if order["vendor_id"] != user_id:
        raise ApiError(
            "ERR_VENDOR_SCOPE_VIOLATION", "A vendor may only advise its own purchase orders."
        )

    shipment = new_record(
        po_id=order["id"],
        asn_number=asn_number,
        shipped_units=shipped_units,
        carton_count=carton_count,
        received_units=None,
        arrived_at=None,
        invoice_value_cents=0,
        status="IN_TRANSIT",
        open_violation_count=0,
        evidence_capture_count=0,
    )
    store.shipments[shipment["id"]] = shipment
    return object_response(ser.shipment_out(shipment), 201)


@bp.post("/compliance/shipments/<identifier>/receive")
def receive_shipment(identifier):
    authenticate(INSPECTOR)
    body = body_dict()
    received_units = req_int(body, "received_units", 0)

    shipment = lookup.shipment(identifier)
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError(
            "ERR_SHIPMENT_ALREADY_RECEIVED", "This shipment has already been received."
        )
    if received_units > shipment["shipped_units"]:
        raise ApiError(
            "ERR_RECEIPT_EXCEEDS_SHIPPED",
            "received_units may not exceed the advised shipped_units.",
        )

    order = po_of_shipment(shipment)
    shipment["status"] = "RECEIVED"
    shipment["received_units"] = received_units
    shipment["arrived_at"] = clock.now()
    shipment["invoice_value_cents"] = received_units * order["unit_cost_cents"]
    touch(shipment)

    recompute_purchase_order(order)
    return object_response(ser.shipment_out(shipment))


# ---------------------------------------------------------------------------
# Violations
# ---------------------------------------------------------------------------


@bp.post("/compliance/shipments/<identifier>/violations")
def file_violation(identifier):
    user_id, _role = authenticate(INSPECTOR)
    body = body_dict()
    requirement_id = req_str(body, "requirement_id")
    affected_units = req_int(body, "affected_units", 0)
    affected_cartons = req_int(body, "affected_cartons", 0)
    narrative = req_str(body, "narrative", 1, 500)

    shipment = lookup.shipment(identifier)
    requirement = lookup.requirement(requirement_id)

    if shipment["status"] != "RECEIVED":
        raise ApiError(
            "ERR_SHIPMENT_NOT_RECEIVED", "A violation may only be filed against a receipt."
        )
    if not guide_governs(store.guides.get(requirement["guide_id"]), shipment["arrived_at"]):
        raise ApiError(
            "ERR_GUIDE_NOT_EFFECTIVE",
            "The requirement's guide edition did not govern this arrival.",
        )
    if clock.now() >= shipment["arrived_at"] + hours(VIOLATION_FILING_WINDOW_HOURS):
        raise ApiError(
            "ERR_VIOLATION_FILING_WINDOW_CLOSED", "The 72-hour filing window has closed."
        )

    for other in violations_of_shipment(shipment["id"]):
        if other["status"] not in ("DETECTED", "EVIDENCE_COMPLETE", "CHARGED"):
            continue
        other_requirement = pinned_requirement(other)
        if (
            other_requirement is not None
            and other_requirement["requirement_code"] == requirement["requirement_code"]
        ):
            raise ApiError(
                "ERR_DUPLICATE_VIOLATION",
                "A live violation citing this requirement code already exists.",
            )

    if affected_units > (shipment["received_units"] or 0):
        raise ApiError(
            "ERR_AFFECTED_UNITS_EXCEED_RECEIPT",
            "affected_units may not exceed the counted received_units.",
        )
    if affected_cartons > shipment["carton_count"]:
        raise ApiError(
            "ERR_AFFECTED_UNITS_EXCEED_RECEIPT",
            "affected_cartons may not exceed the declared carton_count.",
        )

    violation = new_record(
        shipment_id=shipment["id"],
        requirement_id=requirement["id"],
        affected_units=affected_units,
        affected_cartons=affected_cartons,
        narrative=narrative,
        detected_by_user_id=user_id,
        detected_at=clock.now(),
        status="EVIDENCE_COMPLETE" if requirement["min_evidence_count"] == 0 else "DETECTED",
        evidence_count=0,
        void_reason=None,
    )
    store.violations[violation["id"]] = violation

    recompute_shipment_counters(shipment)
    vendor = vendor_of_shipment(shipment)
    if vendor is not None:
        reconcile_vendor(vendor)
    return object_response(ser.violation_out(violation), 201)


@bp.post("/compliance/violations/<identifier>/evidence")
def capture_violation_evidence(identifier):
    user_id, _role = authenticate(INSPECTOR)
    body = body_dict()
    kind = req_enum(body, "kind", EVIDENCE_KINDS)
    reference_uri = req_str(body, "reference_uri", 1, 300)
    note = opt_str(body, "note", 1, 1000)

    violation = lookup.violation(identifier)
    if violation["status"] not in LIVE_VIOLATION_STATES:
        raise ApiError("ERR_VIOLATION_NOT_OPEN", "This violation is no longer open.")

    evidence = new_append_only_record(
        violation_id=violation["id"],
        dispute_id=None,
        subject_type="VIOLATION",
        kind=kind,
        reference_uri=reference_uri,
        note=note,
        captured_by_user_id=user_id,
        captured_at=clock.now(),
    )
    store.evidence[evidence["id"]] = evidence

    recompute_violation_evidence_count(violation)
    shipment = store.shipments.get(violation["shipment_id"])
    if shipment is not None:
        recompute_shipment_counters(shipment)
    return object_response(ser.evidence_out(evidence), 201)


@bp.post("/compliance/violations/<identifier>/assess")
def assess_violation(identifier):
    authenticate(OFFICER)
    body = body_dict()
    opt_str(body, "assessment_note", 1, 1000)

    violation = lookup.violation(identifier)
    if violation["status"] in ("VOIDED", "CHARGED"):
        raise ApiError("ERR_VIOLATION_NOT_OPEN", "This violation is no longer assessable.")

    shipment = store.shipments.get(violation["shipment_id"])
    if shipment is None or shipment["status"] != "RECEIVED":
        raise ApiError("ERR_SHIPMENT_NOT_RECEIVED", "The shipment has not been received.")

    requirement = pinned_requirement(violation)
    if requirement is None:
        raise ApiError("ERR_REQUIREMENT_NOT_FOUND")
    if violation["evidence_count"] < requirement["min_evidence_count"]:
        raise ApiError(
            "ERR_EVIDENCE_INSUFFICIENT",
            "The violation does not carry the required number of evidence items.",
        )
    if not guide_governs(store.guides.get(requirement["guide_id"]), shipment["arrived_at"]):
        raise ApiError(
            "ERR_GUIDE_NOT_EFFECTIVE",
            "The requirement's guide edition did not govern this arrival.",
        )

    vendor = vendor_of_shipment(shipment)
    amounts = assess_amounts(violation, shipment, requirement, vendor)

    # Cascade link 1.
    violation["status"] = "CHARGED"
    touch(violation)

    # Cascade link 2.
    chargeback = new_record(
        violation_id=violation["id"],
        vendor_id=vendor["id"],
        requirement_id=requirement["id"],
        assessment_variant=amounts["assessment_variant"],
        fixed_fee_cents=amounts["fixed_fee_cents"],
        cost_recovery_cents=amounts["cost_recovery_cents"],
        gross_assessed_cents=amounts["gross_assessed_cents"],
        reversal_cents=0,
        recovered_cents=0,
        outstanding_cents=amounts["gross_assessed_cents"],
        evidence_at_assessment_count=violation["evidence_count"],
        dispute_status="NONE",
        deduction_posted=False,
        settlement_status="ASSESSED",
        assessed_at=clock.now(),
    )
    store.chargebacks[chargeback["id"]] = chargeback

    recompute_shipment_counters(shipment)

    # Cascade links 3 and 4.
    reconcile_vendor(vendor, force_bump=True)
    return object_response(ser.chargeback_out(chargeback), 201)


@bp.post("/compliance/violations/<identifier>/void")
def void_violation(identifier):
    authenticate(OFFICER)
    body = body_dict()
    void_reason = req_str(body, "void_reason", 1, 500)

    violation = lookup.violation(identifier)
    if violation["status"] not in LIVE_VIOLATION_STATES:
        raise ApiError("ERR_VIOLATION_NOT_OPEN", "This violation is no longer open.")

    violation["status"] = "VOIDED"
    violation["void_reason"] = void_reason
    touch(violation)

    shipment = store.shipments.get(violation["shipment_id"])
    if shipment is not None:
        recompute_shipment_counters(shipment)
        vendor = vendor_of_shipment(shipment)
        if vendor is not None:
            reconcile_vendor(vendor)
    return object_response(ser.violation_out(violation))
