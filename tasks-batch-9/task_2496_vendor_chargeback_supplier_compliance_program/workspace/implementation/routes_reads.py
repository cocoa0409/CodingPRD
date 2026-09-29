"""All 25 collection and single-resource reads. Every role may read
everything (PRD 2.1); ordering and filters follow PRD 2.4."""

from flask import Blueprint

import lookup
import serializers as ser
from core import (
    ALL_ROLES,
    authenticate,
    list_response,
    object_response,
    query_bool,
    query_filter,
    sort_asc,
    store,
)
from derive import evidence_of_dispute, evidence_of_violation, shipments_of_po

bp = Blueprint("reads", __name__)


def _sort_desc(items, field):
    return sorted(items, key=lambda item: (item[field], item["_seq"]), reverse=True)


def _match(record, field, value):
    if value is None:
        return True
    return record.get(field) == value


# ---------------------------------------------------------------------------
# Single-resource reads
# ---------------------------------------------------------------------------


@bp.get("/compliance/vendors/<identifier>")
def read_vendor(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.vendor_out(lookup.vendor(identifier)))


@bp.get("/compliance/routing-guides/<identifier>")
def read_guide(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.guide_out(lookup.guide(identifier)))


@bp.get("/compliance/purchase-orders/<identifier>")
def read_purchase_order(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.purchase_order_out(lookup.purchase_order(identifier)))


@bp.get("/compliance/shipments/<identifier>")
def read_shipment(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.shipment_out(lookup.shipment(identifier)))


@bp.get("/compliance/violations/<identifier>")
def read_violation(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.violation_out(lookup.violation(identifier)))


@bp.get("/compliance/chargebacks/<identifier>")
def read_chargeback(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.chargeback_out(lookup.chargeback(identifier)))


@bp.get("/compliance/disputes/<identifier>")
def read_dispute(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.dispute_out(lookup.dispute(identifier)))


@bp.get("/compliance/scorecards/<identifier>")
def read_scorecard(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.scorecard_out(lookup.scorecard(identifier)))


@bp.get("/compliance/corrective-action-plans/<identifier>")
def read_cap(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.cap_out(lookup.cap(identifier)))


@bp.get("/compliance/deductions/<identifier>")
def read_deduction(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.deduction_out(lookup.deduction(identifier)))


@bp.get("/compliance/recovery-allocations/<identifier>")
def read_allocation(identifier):
    authenticate(ALL_ROLES)
    return object_response(ser.allocation_out(lookup.allocation(identifier)))


# ---------------------------------------------------------------------------
# Collection reads
# ---------------------------------------------------------------------------


@bp.get("/compliance/vendors")
def list_vendors():
    authenticate(ALL_ROLES)
    status = query_filter("status")
    repeat = query_bool("repeat_offender_flag")
    exposure = query_bool("exposure_alert_flag")
    items = [
        record
        for record in store.vendors.values()
        if _match(record, "status", status)
        and _match(record, "repeat_offender_flag", repeat)
        and _match(record, "exposure_alert_flag", exposure)
    ]
    return list_response(_sort_desc(items, "created_at"), ser.vendor_out)


@bp.get("/compliance/routing-guides")
def list_guides():
    authenticate(ALL_ROLES)
    status = query_filter("status")
    scope = query_filter("scope_code")
    supersedes = query_filter("supersedes_guide_id")
    items = [
        record
        for record in store.guides.values()
        if _match(record, "status", status)
        and _match(record, "scope_code", scope)
        and _match(record, "supersedes_guide_id", supersedes)
    ]
    return list_response(sort_asc(items, "effective_from", "created_at"), ser.guide_out)


@bp.get("/compliance/routing-guides/<identifier>/requirements")
def list_requirements(identifier):
    authenticate(ALL_ROLES)
    guide = lookup.guide(identifier)
    domain = query_filter("domain")
    tier = query_filter("severity_tier")
    items = [
        record
        for record in store.requirements.values()
        if record["guide_id"] == guide["id"]
        and _match(record, "domain", domain)
        and _match(record, "severity_tier", tier)
    ]
    return list_response(sort_asc(items, "requirement_code"), ser.requirement_out)


@bp.get("/compliance/purchase-orders")
def list_purchase_orders():
    authenticate(ALL_ROLES)
    vendor_id = query_filter("vendor_id")
    status = query_filter("status")
    items = [
        record
        for record in store.purchase_orders.values()
        if _match(record, "vendor_id", vendor_id) and _match(record, "status", status)
    ]
    return list_response(_sort_desc(items, "created_at"), ser.purchase_order_out)


@bp.get("/compliance/purchase-orders/<identifier>/shipments")
def list_shipments(identifier):
    authenticate(ALL_ROLES)
    order = lookup.purchase_order(identifier)
    status = query_filter("status")
    items = [
        record for record in shipments_of_po(order["id"]) if _match(record, "status", status)
    ]
    return list_response(sort_asc(items, "created_at"), ser.shipment_out)


@bp.get("/compliance/violations")
def list_violations():
    authenticate(ALL_ROLES)
    shipment_id = query_filter("shipment_id")
    requirement_id = query_filter("requirement_id")
    status = query_filter("status")
    items = [
        record
        for record in store.violations.values()
        if _match(record, "shipment_id", shipment_id)
        and _match(record, "requirement_id", requirement_id)
        and _match(record, "status", status)
    ]
    return list_response(sort_asc(items, "detected_at", "created_at"), ser.violation_out)


@bp.get("/compliance/violations/<identifier>/evidence")
def list_violation_evidence(identifier):
    authenticate(ALL_ROLES)
    violation = lookup.violation(identifier)
    kind = query_filter("kind")
    items = [
        record
        for record in evidence_of_violation(violation["id"])
        if _match(record, "kind", kind)
    ]
    return list_response(sort_asc(items, "captured_at"), ser.evidence_out)


@bp.get("/compliance/disputes/<identifier>/evidence")
def list_dispute_evidence(identifier):
    authenticate(ALL_ROLES)
    dispute = lookup.dispute(identifier)
    kind = query_filter("kind")
    items = [
        record for record in evidence_of_dispute(dispute["id"]) if _match(record, "kind", kind)
    ]
    return list_response(sort_asc(items, "captured_at"), ser.evidence_out)


@bp.get("/compliance/chargebacks")
def list_chargebacks():
    authenticate(ALL_ROLES)
    vendor_id = query_filter("vendor_id")
    violation_id = query_filter("violation_id")
    requirement_id = query_filter("requirement_id")
    dispute_status = query_filter("dispute_status")
    settlement_status = query_filter("settlement_status")
    items = [
        record
        for record in store.chargebacks.values()
        if _match(record, "vendor_id", vendor_id)
        and _match(record, "violation_id", violation_id)
        and _match(record, "requirement_id", requirement_id)
        and _match(record, "dispute_status", dispute_status)
        and _match(record, "settlement_status", settlement_status)
    ]
    return list_response(sort_asc(items, "assessed_at", "created_at"), ser.chargeback_out)


@bp.get("/compliance/disputes")
def list_disputes():
    authenticate(ALL_ROLES)
    vendor_id = query_filter("vendor_id")
    chargeback_id = query_filter("chargeback_id")
    status = query_filter("status")
    items = [
        record
        for record in store.disputes.values()
        if _match(record, "vendor_id", vendor_id)
        and _match(record, "chargeback_id", chargeback_id)
        and _match(record, "status", status)
    ]
    return list_response(sort_asc(items, "submitted_at", "created_at"), ser.dispute_out)


@bp.get("/compliance/scorecards")
def list_scorecards():
    authenticate(ALL_ROLES)
    vendor_id = query_filter("vendor_id")
    period_code = query_filter("period_code")
    status = query_filter("status")
    items = [
        record
        for record in store.scorecards.values()
        if _match(record, "vendor_id", vendor_id)
        and _match(record, "period_code", period_code)
        and _match(record, "status", status)
    ]
    return list_response(sort_asc(items, "period_start", "created_at"), ser.scorecard_out)


@bp.get("/compliance/corrective-action-plans")
def list_caps():
    authenticate(ALL_ROLES)
    vendor_id = query_filter("vendor_id")
    trigger_id = query_filter("trigger_scorecard_id")
    predecessor_id = query_filter("predecessor_cap_id")
    status = query_filter("status")
    items = [
        record
        for record in store.caps.values()
        if _match(record, "vendor_id", vendor_id)
        and _match(record, "trigger_scorecard_id", trigger_id)
        and _match(record, "predecessor_cap_id", predecessor_id)
        and _match(record, "status", status)
    ]
    return list_response(sort_asc(items, "issued_at", "created_at"), ser.cap_out)


@bp.get("/compliance/deductions")
def list_deductions():
    authenticate(ALL_ROLES)
    vendor_id = query_filter("vendor_id")
    status = query_filter("status")
    items = [
        record
        for record in store.deductions.values()
        if _match(record, "vendor_id", vendor_id) and _match(record, "status", status)
    ]
    return list_response(_sort_desc(items, "created_at"), ser.deduction_out)


@bp.get("/compliance/recovery-allocations")
def list_allocations():
    authenticate(ALL_ROLES)
    chargeback_id = query_filter("chargeback_id")
    deduction_id = query_filter("deduction_id")
    source_type = query_filter("source_type")
    effective_status = query_filter("effective_status")
    items = [
        record
        for record in store.allocations.values()
        if _match(record, "chargeback_id", chargeback_id)
        and _match(record, "deduction_id", deduction_id)
        and _match(record, "source_type", source_type)
        and _match(record, "effective_status", effective_status)
    ]
    return list_response(sort_asc(items, "applied_at", "created_at"), ser.allocation_out)
