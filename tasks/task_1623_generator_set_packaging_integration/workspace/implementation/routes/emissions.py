"""EmissionsCertificate endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services.calculations as calc
import services.cascade as cascade

bp = Blueprint("emissions", __name__)


@bp.route("/genset-packaging/emissions-certificates", methods=["POST"])
def create_emissions_certificate():
    mw.require_roles("ComplianceOfficer")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    configuration_id = mw.require_string(body, "configuration_id")
    hour_log_attached = mw.optional_bool(body, "hour_log_attached", False)

    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")
    config = db.configurations.get(configuration_id)
    if config is None:
        raise errors.not_found("Package configuration not found")

    # Derive required_tier from locale
    required_tier = calc.required_tier_for_locale(order["site_locale"])

    # Derive engine_tier from the linked sizing study's engine
    study = db.sizing_studies.get(config["sizing_study_id"])
    if study is None:
        raise errors.not_found("Sizing study not found")
    engine = db.engine_models.get(study["engine_model_id"])
    if engine is None:
        raise errors.not_found("Engine model not found")
    engine_tier = engine["emissions_tier_capability"]

    requires_hour_log = order["application"] == "PRIME"

    record = {
        "order_id": order_id,
        "configuration_id": configuration_id,
        "required_tier": required_tier,
        "engine_tier": engine_tier,
        "requires_hour_log": requires_hour_log,
        "hour_log_attached": hour_log_attached,
        "rejection_reason": None,
        "status": "APP_DRAFT",
    }
    db.stamp_new(record)
    db.emissions_certificates[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/emissions-certificates/<certificateId>", methods=["GET"])
def get_emissions_certificate(certificateId):
    mw.authenticate()
    record = db.emissions_certificates.get(certificateId)
    if record is None:
        raise errors.not_found("Emissions certificate not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/emissions-certificates", methods=["GET"])
def list_emissions_certificates():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.emissions_certificates.values())
    for param in ("order_id", "configuration_id"):
        val = mw.request.args.get(param)
        if val:
            items = [c for c in items if c.get(param) == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/emissions-certificates/<certificateId>/submit", methods=["POST"])
def submit_emissions_certificate(certificateId):
    mw.require_roles("ComplianceOfficer")
    body = mw.get_json_body()

    cert = db.emissions_certificates.get(certificateId)
    if cert is None:
        raise errors.not_found("Emissions certificate not found")

    if cert["status"] not in ("APP_DRAFT", "REJECTED"):
        raise errors.ApiError(
            errors.ERR_CERT_STATE_INVALID, 409,
            "Certificate must be APP_DRAFT or REJECTED to submit",
        )

    # Config must be LOCKED or RELEASED
    config = db.configurations.get(cert["configuration_id"])
    if config is None:
        raise errors.not_found("Package configuration not found")
    if config["status"] not in ("LOCKED", "RELEASED"):
        raise errors.ApiError(
            errors.ERR_CONFIG_STATE_INVALID, 409,
            "Configuration must be LOCKED or RELEASED to submit certificate",
        )

    # Accept optional hour_log_attached at submit
    if "hour_log_attached" in body:
        hour_log = body["hour_log_attached"]
        if not isinstance(hour_log, bool):
            raise errors.invalid_request("hour_log_attached must be a boolean")
        cert["hour_log_attached"] = hour_log

    # Gate: if requires_hour_log then hour_log_attached must be true
    if cert["requires_hour_log"] and not cert["hour_log_attached"]:
        raise errors.ApiError(
            errors.ERR_HOUR_LOG_REQUIRED, 422,
            "PRIME application requires hour_log_attached=true",
        )

    cert["status"] = "SUBMITTED"
    cert["rejection_reason"] = None
    db.touch(cert)
    return resp.success_object(cert)


@bp.route("/genset-packaging/emissions-certificates/<certificateId>/issue", methods=["POST"])
def issue_emissions_certificate(certificateId):
    mw.require_roles("PlatformAdmin")

    cert = db.emissions_certificates.get(certificateId)
    if cert is None:
        raise errors.not_found("Emissions certificate not found")

    if cert["status"] != "SUBMITTED":
        raise errors.ApiError(
            errors.ERR_CERT_STATE_INVALID, 409,
            "Certificate must be SUBMITTED to issue",
        )

    # Tier rank check
    engine_rank = calc.TIER_RANK.get(cert["engine_tier"], 0)
    required_rank = calc.TIER_RANK.get(cert["required_tier"], 0)
    if engine_rank < required_rank:
        raise errors.ApiError(
            errors.ERR_EMISSIONS_TIER_INSUFFICIENT, 422,
            "Engine tier rank below required tier rank",
        )

    cert["status"] = "ISSUED"
    db.touch(cert)

    # Advance order to TESTING if a permit is APPROVED
    order = db.orders.get(cert["order_id"])
    if order is not None:
        cascade.maybe_advance_to_testing(order)

    return resp.success_object(cert)


@bp.route("/genset-packaging/emissions-certificates/<certificateId>/reject", methods=["POST"])
def reject_emissions_certificate(certificateId):
    mw.require_roles("PlatformAdmin")
    body = mw.get_json_body()

    cert = db.emissions_certificates.get(certificateId)
    if cert is None:
        raise errors.not_found("Emissions certificate not found")

    if cert["status"] != "SUBMITTED":
        raise errors.ApiError(
            errors.ERR_CERT_STATE_INVALID, 409,
            "Certificate must be SUBMITTED to reject",
        )

    reason = mw.require_string(body, "reason")
    cert["status"] = "REJECTED"
    cert["rejection_reason"] = reason
    db.touch(cert)
    return resp.success_object(cert)
