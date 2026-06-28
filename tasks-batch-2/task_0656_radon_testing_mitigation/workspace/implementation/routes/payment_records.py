"""PaymentRecord endpoints (PRD §3.5). Append-only ledger; id + created_at only."""

from flask import Blueprint, request

from db import store
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body, parse_pagination
from response import object_response, array_response
from services import validate
from services.domain import append_payment, recompute_job_payments, public
from services.listing import paginate

bp = Blueprint("payment_records", __name__)

KINDS = {"DEPOSIT", "BALANCE", "REFUND"}
GET_ROLES = {"PlatformAdmin", "MitigationDesigner", "ClientContact", "ComplianceOfficer"}


@bp.route("/payment-records", methods=["POST"])
def create_payment():
    _, role = get_user_context()
    require_role(role, {"ClientContact", "MitigationDesigner", "PlatformAdmin"})
    body = get_json_body()

    mitigation_job_id = validate.require_string(body, "mitigation_job_id")
    kind = validate.require_enum(body, "kind", KINDS)
    # amount_cents: integer; positive for DEPOSIT/BALANCE, negative for REFUND.
    amount_cents = validate.require_int(body, "amount_cents")
    if kind in {"DEPOSIT", "BALANCE"} and amount_cents < 0:
        validate.bad_request("DEPOSIT/BALANCE amount_cents must be non-negative.")
    if kind == "REFUND" and amount_cents > 0:
        validate.bad_request("REFUND amount_cents must be non-positive.")

    # body FK existence (priority 4).
    job = store.mitigation_jobs.get(mitigation_job_id)
    if job is None:
        raise ApiError(
            errors.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404, "mitigation_job_id not found."
        )

    record = append_payment(job, kind, amount_cents)
    recompute_job_payments(job)
    return object_response(public(record), 201)


@bp.route("/payment-records/<record_id>", methods=["GET"])
def get_payment(record_id):
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    record = store.payment_records.get(record_id)
    if record is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Payment record not found.")
    return object_response(public(record), 200)


@bp.route("/payment-records", methods=["GET"])
def list_payments():
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "mitigation_job_id": request.args.get("mitigation_job_id"),
        "kind": request.args.get("kind"),
    }
    items, total = paginate(store.payment_records, filters, limit, offset)
    return array_response(items, limit, offset, total, 200)
