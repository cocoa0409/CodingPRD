"""PermitCase endpoints."""

from datetime import date, timedelta

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services.calculations as calc
import services.cascade as cascade

bp = Blueprint("permits", __name__)


def _logical_date():
    return date.fromisoformat(db.logical_today())


@bp.route("/genset-packaging/permit-cases", methods=["POST"])
def create_permit_case():
    mw.require_roles("ComplianceOfficer")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    configuration_id = mw.require_string(body, "configuration_id")

    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")
    config = db.configurations.get(configuration_id)
    if config is None:
        raise errors.not_found("Package configuration not found")

    locale = order["site_locale"]
    base_fee, resubmission_fee = calc.permit_fees_for_locale(locale)

    record = {
        "order_id": order_id,
        "configuration_id": configuration_id,
        "jurisdiction_locale": locale,
        "base_fee_cents": base_fee,
        "resubmission_fee_cents": resubmission_fee,
        "total_fees_paid_cents": 0,
        "revision_count": 0,
        "submitted_on": None,
        "expires_on": None,
        "status": "DRAFT",
    }
    db.stamp_new(record)
    db.permit_cases[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/permit-cases/<permitId>", methods=["GET"])
def get_permit_case(permitId):
    mw.authenticate()
    record = db.permit_cases.get(permitId)
    if record is None:
        raise errors.not_found("Permit case not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/permit-cases", methods=["GET"])
def list_permit_cases():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.permit_cases.values())
    for param in ("order_id", "configuration_id"):
        val = mw.request.args.get(param)
        if val:
            items = [p for p in items if p.get(param) == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/permit-cases/<permitId>/submit", methods=["POST"])
def submit_permit(permitId):
    mw.require_roles("ComplianceOfficer")

    permit = db.permit_cases.get(permitId)
    if permit is None:
        raise errors.not_found("Permit case not found")

    today = _logical_date()
    expiry_days = calc.expiry_days_for_locale(permit["jurisdiction_locale"])

    if permit["status"] == "DRAFT":
        # First submission: config must be LOCKED
        config = db.configurations.get(permit["configuration_id"])
        if config is None:
            raise errors.not_found("Package configuration not found")
        if config["status"] != "LOCKED":
            raise errors.ApiError(
                errors.ERR_CONFIG_STATE_INVALID, 409,
                "Configuration must be LOCKED for first permit submission",
            )

        permit["submitted_on"] = today.isoformat()
        permit["expires_on"] = (today + timedelta(days=expiry_days)).isoformat()
        permit["total_fees_paid_cents"] += permit["base_fee_cents"]
        permit["status"] = "SUBMITTED"
        db.touch(permit)

        # Order build: CONFIGURING -> PERMITTING on first SUBMITTED permit
        order = db.orders.get(permit["order_id"])
        if order is not None and order["build_status"] == "CONFIGURING":
            order["build_status"] = "PERMITTING"
            db.touch(order)

    elif permit["status"] == "CORRECTION_REQUESTED":
        # Resubmission: clock must be on or before expires_on
        if permit["expires_on"] is not None:
            expires = date.fromisoformat(permit["expires_on"])
            if today > expires:
                raise errors.ApiError(
                    errors.ERR_PERMIT_EXPIRED, 422,
                    "Permit resubmission attempted after expires_on",
                )

        permit["revision_count"] += 1
        permit["submitted_on"] = today.isoformat()
        permit["expires_on"] = (today + timedelta(days=expiry_days)).isoformat()
        permit["total_fees_paid_cents"] += permit["resubmission_fee_cents"]
        permit["status"] = "SUBMITTED"
        db.touch(permit)
    else:
        raise errors.ApiError(
            errors.ERR_PERMIT_STATE_INVALID, 409,
            "Permit must be DRAFT or CORRECTION_REQUESTED to submit",
        )

    return resp.success_object(permit)


@bp.route("/genset-packaging/permit-cases/<permitId>/request-correction", methods=["POST"])
def request_correction(permitId):
    mw.require_roles("PlatformAdmin")

    permit = db.permit_cases.get(permitId)
    if permit is None:
        raise errors.not_found("Permit case not found")

    if permit["status"] != "SUBMITTED":
        raise errors.ApiError(
            errors.ERR_PERMIT_STATE_INVALID, 409,
            "Permit must be SUBMITTED to request corrections",
        )

    permit["status"] = "CORRECTION_REQUESTED"
    db.touch(permit)
    return resp.success_object(permit)


@bp.route("/genset-packaging/permit-cases/<permitId>/approve-ahj", methods=["POST"])
def approve_permit(permitId):
    mw.require_roles("PlatformAdmin")

    permit = db.permit_cases.get(permitId)
    if permit is None:
        raise errors.not_found("Permit case not found")

    if permit["status"] != "SUBMITTED":
        raise errors.ApiError(
            errors.ERR_PERMIT_STATE_INVALID, 409,
            "Permit must be SUBMITTED to approve",
        )

    permit["status"] = "APPROVED"
    db.touch(permit)

    # Advance order to TESTING if an ISSUED cert exists
    order = db.orders.get(permit["order_id"])
    if order is not None:
        cascade.maybe_advance_to_testing(order)

    return resp.success_object(permit)


@bp.route("/genset-packaging/permit-cases/<permitId>/withdraw", methods=["POST"])
def withdraw_permit(permitId):
    mw.require_roles("ComplianceOfficer")

    permit = db.permit_cases.get(permitId)
    if permit is None:
        raise errors.not_found("Permit case not found")

    if permit["status"] not in ("DRAFT", "SUBMITTED", "CORRECTION_REQUESTED"):
        raise errors.ApiError(
            errors.ERR_PERMIT_STATE_INVALID, 409,
            "Permit must be DRAFT, SUBMITTED, or CORRECTION_REQUESTED to withdraw",
        )

    cascade.withdraw_permit(permit)
    return resp.success_object(permit)


@bp.route("/genset-packaging/permit-cases/<permitId>/expire-check", methods=["POST"])
def expire_check_permit(permitId):
    mw.require_roles("PlatformAdmin")

    permit = db.permit_cases.get(permitId)
    if permit is None:
        raise errors.not_found("Permit case not found")

    if permit["status"] != "SUBMITTED":
        raise errors.ApiError(
            errors.ERR_PERMIT_STATE_INVALID, 409,
            "Permit must be SUBMITTED for expire-check",
        )

    today = _logical_date()
    if permit["expires_on"] is not None:
        expires = date.fromisoformat(permit["expires_on"])
        if today <= expires:
            raise errors.ApiError(
                errors.ERR_PERMIT_NOT_EXPIRED, 422,
                "Current logical-clock date is not strictly past expires_on",
            )

    permit["status"] = "EXPIRED"
    db.touch(permit)
    return resp.success_object(permit)
