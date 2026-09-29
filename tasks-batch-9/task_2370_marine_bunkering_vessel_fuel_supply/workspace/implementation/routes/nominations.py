"""Nomination intake, compliance review, confirmation and auto-scheduling."""

import re
from datetime import timedelta

from flask import Blueprint, g

import db
import serializers
from db import store, touch
from errors import ApiError
from lookup import body_ref, path_ref
from middleware import roles
from response import success, success_list
from services import calc, scheduling
from validation import (
    apply_page,
    body,
    pagination,
    q_enum,
    q_str,
    v_bool,
    v_datetime,
    v_decimal,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("nominations", __name__)

DELIVERY_MODES = ("BARGE", "TRUCK")
FULFILLMENT_STATUSES = (
    "DRAFT",
    "CONFIRMED",
    "SCHEDULED",
    "AWAITING_SCHEDULE",
    "DELIVERED",
    "CLOSED",
)
COMPLIANCE_STATUSES = ("PENDING_REVIEW", "APPROVED", "REJECTED")
REVIEW_DECISIONS = ("APPROVE", "REJECT", "REOPEN")
IMO_PATTERN = re.compile(r"^\d{7}$")


@bp.post("/nominations")
@roles("OpsCoordinator", "CustomerRep")
def create_nomination():
    data = body()
    # PRD 2.7: port_id, then grade_id, then customer_id.
    port = body_ref(data, "port_id", store.ports, "ERR_PORT_NOT_FOUND")
    grade = body_ref(data, "grade_id", store.fuel_grades, "ERR_FUEL_GRADE_NOT_FOUND")
    customer = body_ref(data, "customer_id", store.customers, "ERR_CUSTOMER_NOT_FOUND")

    customer_id = v_string(data, "customer_id", min_len=1)
    port_id = v_string(data, "port_id", min_len=1)
    grade_id = v_string(data, "grade_id", min_len=1)
    vessel_imo = v_string(data, "vessel_imo")
    if not IMO_PATTERN.match(vessel_imo):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'vessel_imo' must be exactly 7 digits.")
    vessel_name = v_string(data, "vessel_name", min_len=1)
    scrubber_fitted = v_bool(data, "scrubber_fitted", required=False, default=False)
    nominated_quantity_mt = v_decimal(data, "nominated_quantity_mt", 3, positive=True)
    window_start = v_datetime(data, "window_start")
    window_end = v_datetime(data, "window_end")
    delivery_mode = v_enum(data, "delivery_mode", DELIVERY_MODES)
    declared_sulfur_pct = v_decimal(data, "declared_sulfur_pct", 3, positive=True)
    eca_documentation_ref = v_string(data, "eca_documentation_ref", required=False)

    if port is None:
        raise ApiError("ERR_PORT_NOT_FOUND")
    if grade is None:
        raise ApiError("ERR_FUEL_GRADE_NOT_FOUND")
    if customer is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND")

    if window_end < window_start + timedelta(hours=calc.MIN_WINDOW_HOURS):
        raise ApiError("ERR_WINDOW_TOO_SHORT")

    nomination = db.new_record()
    nomination.update(
        {
            "customer_id": customer_id,
            "port_id": port_id,
            "grade_id": grade_id,
            "vessel_imo": vessel_imo,
            "vessel_name": vessel_name,
            "scrubber_fitted": scrubber_fitted,
            "nominated_quantity_mt": nominated_quantity_mt,
            "window_start": window_start,
            "window_end": window_end,
            "delivery_mode": delivery_mode,
            "declared_sulfur_pct": declared_sulfur_pct,
            "eca_documentation_ref": eca_documentation_ref,
            "fulfillment_status": "DRAFT",
            "compliance_status": "PENDING_REVIEW",
            "compliance_reviewer_user_id": None,
        }
    )
    store.nominations[nomination["id"]] = nomination
    return success(serializers.nomination(nomination), 201)


@bp.get("/nominations/<rec_id>")
@roles("OpsCoordinator", "ComplianceOfficer", "CustomerRep")
def get_nomination(rec_id):
    nomination = path_ref(store.nominations, rec_id, "ERR_NOMINATION_NOT_FOUND")
    return success(serializers.nomination(nomination))


@bp.get("/nominations")
@roles("OpsCoordinator", "ComplianceOfficer", "CustomerRep")
def list_nominations():
    customer_id = q_str("customer_id")
    if g.role == "CustomerRep":
        if customer_id is not None and customer_id != g.user_id:
            raise ApiError("ERR_CUSTOMER_SCOPE_VIOLATION")
        customer_id = g.user_id
    port_id = q_str("port_id")
    grade_id = q_str("grade_id")
    fulfillment_status = q_enum("fulfillment_status", FULFILLMENT_STATUSES)
    compliance_status = q_enum("compliance_status", COMPLIANCE_STATUSES)
    limit, offset = pagination()

    def match(row):
        if customer_id is not None and row["customer_id"] != customer_id:
            return False
        if port_id is not None and row["port_id"] != port_id:
            return False
        if grade_id is not None and row["grade_id"] != grade_id:
            return False
        if fulfillment_status is not None and row["fulfillment_status"] != fulfillment_status:
            return False
        if compliance_status is not None and row["compliance_status"] != compliance_status:
            return False
        return True

    rows = db.sorted_rows(store.nominations, match)
    page = apply_page(rows, limit, offset)
    return success_list([serializers.nomination(r) for r in page], limit, offset, len(rows))


@bp.post("/nominations/<rec_id>/compliance-review")
@roles("ComplianceOfficer")
def compliance_review(rec_id):
    nomination = path_ref(store.nominations, rec_id, "ERR_NOMINATION_NOT_FOUND")
    data = body()
    decision = v_enum(data, "decision", REVIEW_DECISIONS)

    port = store.ports.get(nomination["port_id"])
    grade = store.fuel_grades.get(nomination["grade_id"])

    if decision == "APPROVE":
        if nomination["compliance_status"] != "PENDING_REVIEW":
            raise ApiError("ERR_INVALID_NOMINATION_STATE")
        eca_applies = port["eca_zone"] and not nomination["scrubber_fitted"]
        if eca_applies:
            if not grade["eca_permitted"] or (
                grade["max_sulfur_pct"] > port["eca_sulfur_limit_pct"]
            ):
                raise ApiError("ERR_ECA_SULFUR_VIOLATION")
            if nomination["eca_documentation_ref"] is None:
                raise ApiError("ERR_ECA_DOCUMENTATION_MISSING")
        if nomination["declared_sulfur_pct"] > grade["max_sulfur_pct"]:
            raise ApiError("ERR_ECA_SULFUR_VIOLATION")
        nomination["compliance_status"] = "APPROVED"
        nomination["compliance_reviewer_user_id"] = g.user_id
    elif decision == "REJECT":
        if nomination["compliance_status"] != "PENDING_REVIEW":
            raise ApiError("ERR_INVALID_NOMINATION_STATE")
        nomination["compliance_status"] = "REJECTED"
        nomination["compliance_reviewer_user_id"] = g.user_id
    else:  # REOPEN
        if nomination["compliance_status"] != "REJECTED":
            raise ApiError("ERR_INVALID_NOMINATION_STATE")
        if nomination["fulfillment_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_NOMINATION_STATE")
        nomination["compliance_status"] = "PENDING_REVIEW"
        nomination["compliance_reviewer_user_id"] = None

    touch(nomination)
    return success(serializers.nomination(nomination))


@bp.post("/nominations/<rec_id>/confirm")
@roles("OpsCoordinator")
def confirm_nomination(rec_id):
    nomination = path_ref(store.nominations, rec_id, "ERR_NOMINATION_NOT_FOUND")
    if nomination["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_NOMINATION_STATE")
    if nomination["compliance_status"] != "APPROVED":
        raise ApiError("ERR_COMPLIANCE_NOT_APPROVED")

    customer = store.customers.get(nomination["customer_id"])
    # Raises ERR_INDEX_QUOTE_UNAVAILABLE (priority 59) before the fiscal gates.
    calc.index_price(nomination["grade_id"], db.now(), strict=True)
    if customer["credit_status"] == "HOLD":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")
    if not calc.credit_availability_passes(nomination, customer):
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")

    nomination["fulfillment_status"] = "CONFIRMED"
    touch(nomination)
    return success(serializers.nomination(nomination))


@bp.post("/nominations/<rec_id>/auto-schedule")
@roles("OpsCoordinator")
def auto_schedule(rec_id):
    nomination = path_ref(store.nominations, rec_id, "ERR_NOMINATION_NOT_FOUND")
    data = body()
    requested_slot_start = v_datetime(data, "requested_slot_start")
    expected_nomination_version = v_int(data, "expected_nomination_version")

    if expected_nomination_version != nomination["version"]:
        raise ApiError("ERR_STALE_NOMINATION_VERSION")
    if nomination["fulfillment_status"] not in ("CONFIRMED", "AWAITING_SCHEDULE"):
        raise ApiError("ERR_INVALID_NOMINATION_STATE")

    port = store.ports.get(nomination["port_id"])
    grade = store.fuel_grades.get(nomination["grade_id"])
    slot_start, slot_end = calc.derive_auto_slot(nomination, requested_slot_start)

    scheduling.check_slot_in_window(nomination, slot_start, slot_end)
    if calc.port_capacity_exceeded(port, slot_start, slot_end):
        raise ApiError("ERR_PORT_CAPACITY_EXCEEDED")
    scheduling.check_notice_period(port, slot_start)

    asset = calc.auto_select_asset(nomination, port, grade, slot_start, slot_end)
    if asset is None:
        raise ApiError("ERR_NO_ELIGIBLE_ASSET")

    scheduling.supersede_orders(nomination)
    order = scheduling.create_order(
        nomination, asset, nomination["nominated_quantity_mt"], slot_start, slot_end
    )
    return success(serializers.delivery_order(order), 201)
