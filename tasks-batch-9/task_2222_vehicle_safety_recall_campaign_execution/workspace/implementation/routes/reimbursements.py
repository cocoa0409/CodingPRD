"""Owner reimbursement requests: intake, documents, re-key and adjudication."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import helpers as h
import validators as v
from auth import ALL_ROLES, require_roles
from db import (UTC, base_record, parse_date, parse_instant, sorted_records,
                store, touch)
from errors import ApiError
from response import collection, single

bp = Blueprint("reimbursements", __name__)


def _population_row(campaign_id, vehicle_id):
    for av in store.affected_vehicles.values():
        if av["campaign_id"] == campaign_id and av["vehicle_id"] == vehicle_id:
            return av
    return None


def _assert_window(campaign, invoice_date):
    determined = parse_instant(campaign["defect_determination_date"]) \
        if campaign["defect_determination_date"] else None
    if determined is not None:
        lower = determined.astimezone(UTC).date() - timedelta(
            days=calc.REIMBURSEMENT_LOOKBACK_DAYS)
        if invoice_date < lower:
            raise ApiError("ERR_REIMBURSEMENT_WINDOW_CLOSED")
    released = parse_instant(campaign["remedy_released_at"]) \
        if campaign["remedy_released_at"] else None
    if released is not None:
        upper = released.astimezone(UTC).date() + timedelta(
            days=calc.REIMBURSEMENT_TAIL_DAYS)
        if invoice_date > upper:
            raise ApiError("ERR_REIMBURSEMENT_WINDOW_CLOSED")


@bp.post("/owner-reimbursements")
@require_roles("RecallOperationsManager")
def create_reimbursement():
    payload = v.body()
    campaign_id = v.req_str(payload, "campaign_id")
    vehicle_id = v.req_str(payload, "vehicle_id")
    invoice_raw, invoice_date = v.req_date_str(payload, "invoice_date")
    invoice_amount = v.req_decimal(payload, "invoice_amount", gt=0)
    labor_hours = v.req_decimal(payload, "labor_hours_claimed", gt=0)
    parts_amount = v.opt_decimal(payload, "parts_amount", Decimal("0.00"), ge=0)
    towing_amount = v.opt_decimal(payload, "towing_amount", Decimal("0.00"), ge=0)
    documentation_complete = v.opt_bool(payload, "documentation_complete", True)

    h.get_vehicle(vehicle_id)
    campaign = h.get_campaign(campaign_id)

    h.assert_campaign_writable(campaign)

    if _population_row(campaign_id, vehicle_id) is None:
        raise ApiError("ERR_VEHICLE_NOT_IN_POPULATION")

    _assert_window(campaign, invoice_date)

    if invoice_amount > calc.OWNER_INVOICE_MAX_USD:
        raise ApiError("ERR_REIMBURSEMENT_INVOICE_EXCEEDS_MAX")

    row = base_record()
    row.update({
        "campaign_id": campaign_id,
        "vehicle_id": vehicle_id,
        "labor_operation_id": None,
        "invoice_date": invoice_raw,
        "invoice_amount": calc.q2(invoice_amount),
        "parts_amount": calc.q2(parts_amount),
        "labor_hours_claimed": calc.q2(labor_hours),
        "towing_amount": calc.q2(towing_amount),
        "documentation_complete": documentation_complete,
        "document_round": 0,
        "approved_amount_cents": None,
        "status": "SUBMITTED",
        "requested_items": None,
        "denial_reason": None,
    })
    store.reimbursements[row["id"]] = row
    return single(h.reimbursement_out(row), 201)


@bp.get("/owner-reimbursements")
@require_roles(*ALL_ROLES)
def list_reimbursements():
    status = v.query_enum("status", v.REIMBURSEMENT_STATUSES)
    filters = {
        "campaign_id": request.args.get("campaign_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "labor_operation_id": request.args.get("labor_operation_id"),
    }
    rows = list(store.reimbursements.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(sorted_records(rows), h.reimbursement_out)


@bp.get("/owner-reimbursements/<request_id>")
@require_roles(*ALL_ROLES)
def get_reimbursement(request_id):
    return single(h.reimbursement_out(h.get_reimbursement(request_id)))


@bp.post("/owner-reimbursements/<request_id>/request-documents")
@require_roles("ClaimsAuditor")
def request_documents(request_id):
    row = h.get_reimbursement(request_id)
    payload = v.body()
    requested_items = v.req_str(payload, "requested_items")

    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_REIMBURSEMENT_INVALID_STATE")
    if row["document_round"] >= calc.MAX_DOCUMENT_ROUNDS:
        raise ApiError("ERR_MAX_DOCUMENT_ROUNDS_EXCEEDED")

    row["status"] = "DOCUMENTS_REQUESTED"
    row["document_round"] = row["document_round"] + 1
    row["documentation_complete"] = False
    row["requested_items"] = requested_items
    touch(row)
    return single(h.reimbursement_out(row))


@bp.post("/owner-reimbursements/<request_id>/resubmit")
@require_roles("RecallOperationsManager")
def resubmit_reimbursement(request_id):
    row = h.get_reimbursement(request_id)
    payload = v.body()
    invoice_amount = v.opt_decimal(payload, "invoice_amount", gt=0)
    parts_amount = v.opt_decimal(payload, "parts_amount", ge=0)
    towing_amount = v.opt_decimal(payload, "towing_amount", ge=0)
    labor_hours = v.opt_decimal(payload, "labor_hours_claimed", gt=0)
    documentation_complete = v.opt_bool(payload, "documentation_complete")

    if row["status"] != "DOCUMENTS_REQUESTED":
        raise ApiError("ERR_REIMBURSEMENT_INVALID_STATE")

    if invoice_amount is not None and invoice_amount > calc.OWNER_INVOICE_MAX_USD:
        raise ApiError("ERR_REIMBURSEMENT_INVOICE_EXCEEDS_MAX")

    if invoice_amount is not None:
        row["invoice_amount"] = calc.q2(invoice_amount)
    if parts_amount is not None:
        row["parts_amount"] = calc.q2(parts_amount)
    if towing_amount is not None:
        row["towing_amount"] = calc.q2(towing_amount)
    if labor_hours is not None:
        row["labor_hours_claimed"] = calc.q2(labor_hours)
    row["documentation_complete"] = True
    row["status"] = "SUBMITTED"
    touch(row)
    return single(h.reimbursement_out(row))


@bp.post("/owner-reimbursements/<request_id>/adjudicate")
@require_roles("ClaimsAuditor")
def adjudicate_reimbursement(request_id):
    row = h.get_reimbursement(request_id)
    payload = v.body()
    decision = v.req_enum(payload, "decision", v.DECISIONS_REIMBURSEMENT)
    denial_reason = v.opt_str(payload, "denial_reason")

    if row["status"] not in ("SUBMITTED", "DOCUMENTS_REQUESTED"):
        raise ApiError("ERR_REIMBURSEMENT_INVALID_STATE")

    campaign = store.campaigns.get(row["campaign_id"])

    if decision == "DENY":
        row["status"] = "DENIED"
        row["denial_reason"] = denial_reason
        row["approved_amount_cents"] = 0
        touch(row)
        return single(h.reimbursement_out(row))

    if row["status"] != "SUBMITTED" or not row["documentation_complete"]:
        raise ApiError("ERR_REIMBURSEMENT_INVALID_STATE")

    invoice_date = parse_date(row["invoice_date"])
    labor_op = None
    for candidate in calc.campaign_labor_ops(row["campaign_id"]):
        if parse_date(candidate["effective_from"]) <= invoice_date \
                <= parse_date(candidate["effective_to"]):
            labor_op = candidate
            break
    if labor_op is None:
        raise ApiError("ERR_LABOR_OP_NOT_EFFECTIVE")

    if _population_row(row["campaign_id"], row["vehicle_id"]) is None:
        raise ApiError("ERR_VEHICLE_NOT_IN_POPULATION")

    _assert_window(campaign, invoice_date)

    part = calc.campaign_first_part(row["campaign_id"])
    row["labor_operation_id"] = labor_op["id"]
    row["approved_amount_cents"] = calc.owner_reimbursement_amount_cents(
        row, campaign, labor_op, part)
    row["status"] = "APPROVED"
    touch(row)
    touch(campaign)
    return single(h.reimbursement_out(row))
