"""Machine placements, their two status axes, and telemetry ingest."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from middleware import (
    ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT, ROLE_PLATFORM_ADMIN,
    ROLE_QUALITY_AUDITOR, ROLE_SERVICE_TECHNICIAN,
)
from routes import common
from services import derive, telemetry

bp = Blueprint("placements", __name__)

SOURCES = ("DEVICE", "MANUAL_AUDIT")


@bp.route("/machine-placements", methods=["POST"])
def create_placement():
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    body = middleware.body_object()
    site_id = middleware.f_str(body, "site_id", required=True)
    agreement_id = middleware.f_str(body, "agreement_id", required=True)
    model_id = middleware.f_str(body, "machine_model_id", required=True)
    asset_tag = middleware.f_str(
        body, "asset_tag", required=True, min_len=1, max_len=40
    )
    expected_version = middleware.f_int(
        body, "expected_agreement_version", required=True, minimum=0
    )
    initial_cycles = middleware.f_int(body, "initial_cycle_count", minimum=0)
    if initial_cycles is None:
        initial_cycles = 0

    site = middleware.must_reference("sites", site_id, "site_id")
    agreement = middleware.must_reference(
        "service_agreements", agreement_id, "agreement_id"
    )
    model = middleware.must_reference(
        "machine_models", model_id, "machine_model_id"
    )

    middleware.check_parent_version(
        agreement, expected_version, "ServiceAgreement"
    )

    if agreement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_AGREEMENT_NOT_ACTIVE",
            "The agreement is %s, not ACTIVE" % agreement["status"],
        )
    if site["customer_id"] != agreement["customer_id"]:
        raise ApiError(
            "ERR_UNKNOWN_REFERENCE",
            "The site and the agreement belong to different accounts",
        )
    for existing in db.rows("machine_placements"):
        if (existing["asset_tag"] == asset_tag
                and existing["placement_status"] != "CANCELLED"):
            raise ApiError(
                "ERR_ASSET_TAG_TAKEN", "asset_tag %s is in use" % asset_tag
            )

    customer = db.get("customers", site["customer_id"])
    if customer is not None and customer["billing_status"] == "CREDIT_HOLD":
        raise ApiError(
            "ERR_CUSTOMER_CREDIT_HOLD", "The account is on credit hold"
        )

    row = db.insert("machine_placements", {
        "site_id": site_id,
        "agreement_id": agreement_id,
        "machine_model_id": model_id,
        "asset_tag": asset_tag,
        "initial_cycle_count": initial_cycles,
        "placement_status": "PENDING_INSTALL",
        "operational_status": "UP",
        "installed_at": None,
        "last_cycle_count": initial_cycles,
        "cycles_since_calibration": 0,
        "open_alert_count": 0,
        "retrieval_due_date": None,
        "retrieved_at": None,
        "_calibration_baseline": initial_cycles,
    })
    derive.recompute_customer(customer)
    derive.recompute_agreement_placements(agreement)
    return response.created(response.serialize(row))


@bp.route("/machine-placements/<placement_id>", methods=["GET"])
def read_placement(placement_id):
    user_id, role = middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR,
        ROLE_CUSTOMER_CONTACT,
    )
    row = db.get("machine_placements", placement_id)
    middleware.scope_customer(role, user_id, common.owner_of_placement(row))
    row = middleware.must_exist(
        "machine_placements", placement_id, "MachinePlacement"
    )
    return response.ok(response.serialize(row))


@bp.route("/machine-placements", methods=["GET"])
def list_placements():
    middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR
    )
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("machine_placements"), (
        ("site_id", "site_id"),
        ("agreement_id", "agreement_id"),
        ("machine_model_id", "machine_model_id"),
        ("placement_status", "placement_status"),
        ("operational_status", "operational_status"),
        ("asset_tag", "asset_tag"),
    ))
    return common.listing(rows, limit, offset)


@bp.route("/machine-placements/<placement_id>/install", methods=["POST"])
def install_placement(placement_id):
    middleware.require_roles(ROLE_SERVICE_TECHNICIAN)
    middleware.body_object()
    placement = middleware.must_exist(
        "machine_placements", placement_id, "MachinePlacement"
    )
    if placement["placement_status"] != "PENDING_INSTALL":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The placement is %s, not PENDING_INSTALL"
            % placement["placement_status"],
        )
    agreement = db.get("service_agreements", placement["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_AGREEMENT_NOT_ACTIVE", "The financing agreement is not ACTIVE"
        )
    site = db.get("sites", placement["site_id"])
    if site is None or site["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", "The site is not ACTIVE"
        )

    placement["placement_status"] = "INSTALLED"
    placement["installed_at"] = db.now()
    db.mark(placement)
    return response.ok(response.serialize(placement))


@bp.route("/machine-placements/<placement_id>/retrieval-order",
          methods=["POST"])
def retrieval_order(placement_id):
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    body = middleware.body_object()
    due_date = middleware.f_date(body, "retrieval_due_date")
    placement = middleware.must_exist(
        "machine_placements", placement_id, "MachinePlacement"
    )
    status = placement["placement_status"]
    site = db.get("sites", placement["site_id"])
    agreement = db.get("service_agreements", placement["agreement_id"])
    customer = db.get("customers", site["customer_id"]) if site else None

    if status == "PENDING_INSTALL":
        placement["placement_status"] = "CANCELLED"
        placement["operational_status"] = "OFFLINE"
        if due_date is not None:
            placement["retrieval_due_date"] = due_date
        db.mark(placement)
        derive.recompute_customer(customer)
        derive.recompute_agreement_placements(agreement)
        return response.ok(response.serialize(placement))

    if status != "INSTALLED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A placement in %s cannot be ordered for retrieval" % status,
        )

    placement["placement_status"] = "RETRIEVAL_SCHEDULED"
    placement["retrieval_due_date"] = (
        due_date if due_date is not None
        else db.now().date() + timedelta(days=14)
    )
    db.mark(placement)
    derive.end_placement_chemistry(placement)
    derive.recompute_site(site)
    return response.ok(response.serialize(placement))


@bp.route("/machine-placements/<placement_id>/retrieval-completion",
          methods=["POST"])
def retrieval_completion(placement_id):
    middleware.require_roles(ROLE_SERVICE_TECHNICIAN)
    middleware.body_object()
    placement = middleware.must_exist(
        "machine_placements", placement_id, "MachinePlacement"
    )
    if placement["placement_status"] != "RETRIEVAL_SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The placement is %s, not RETRIEVAL_SCHEDULED"
            % placement["placement_status"],
        )
    for ticket in derive.tickets_of_placement(placement_id):
        if ticket["status"] in derive.RETRIEVAL_BLOCKING_STATUSES:
            raise ApiError(
                "ERR_OPEN_TICKET_BLOCKS_RETRIEVAL",
                "A ticket in %s blocks retrieval" % ticket["status"],
            )

    placement["placement_status"] = "RETRIEVED"
    placement["retrieved_at"] = db.now()
    if placement["operational_status"] in ("UP", "DEGRADED", "DOWN"):
        placement["operational_status"] = "OFFLINE"
    db.mark(placement)
    for dispenser in derive.dispensers_of_placement(placement_id):
        if dispenser["dispenser_status"] == "REMOVED":
            continue
        dispenser["dispenser_status"] = "REMOVED"
        dispenser["lockout_reason"] = None
        db.mark(dispenser)
    site = db.get("sites", placement["site_id"])
    derive.recompute_customer(
        db.get("customers", site["customer_id"]) if site else None
    )
    derive.recompute_agreement_placements(
        db.get("service_agreements", placement["agreement_id"])
    )
    derive.recompute_site(site)
    return response.ok(response.serialize(placement))


# --------------------------------------------------------------------------
# telemetry ingest (nested evidence write, PRD 3.4)
# --------------------------------------------------------------------------

@bp.route("/machine-placements/<placement_id>/telemetry-readings",
          methods=["POST"])
def ingest_reading(placement_id):
    middleware.require_roles(ROLE_PLATFORM_ADMIN)
    body = middleware.body_object()
    reading_at = middleware.f_dt(body, "reading_at", required=True)
    cycle_count_total = middleware.f_int(
        body, "cycle_count_total", required=True, minimum=0
    )
    wash_temp = middleware.f_int(
        body, "wash_temp_f", required=True, minimum=0, maximum=250
    )
    rinse_temp = middleware.f_int(
        body, "final_rinse_temp_f", required=True, minimum=0, maximum=250
    )
    pressure = middleware.f_int(
        body, "rinse_pressure_psi", required=True, minimum=0, maximum=80
    )
    source = middleware.f_enum(body, "source", SOURCES) or "DEVICE"

    placement = middleware.must_exist(
        "machine_placements", placement_id, "MachinePlacement"
    )
    if placement["placement_status"] != "INSTALLED":
        raise ApiError(
            "ERR_PLACEMENT_NOT_INSTALLED",
            "The placement is %s, not INSTALLED"
            % placement["placement_status"],
        )

    if source == "DEVICE":
        previous = telemetry.preceding_device_reading(placement_id, reading_at)
        floor = telemetry.baseline_cycle_count(placement, previous)
        if cycle_count_total < floor:
            raise ApiError(
                "ERR_NON_MONOTONIC_CYCLE_COUNT",
                "cycle_count_total %s is below the preceding %s"
                % (cycle_count_total, floor),
            )

    installed_at = placement["installed_at"]
    if installed_at is not None and reading_at < installed_at:
        raise ApiError(
            "ERR_READING_BEFORE_INSTALL",
            "reading_at predates the placement's installed_at",
        )
    if reading_at > db.now():
        raise ApiError(
            "ERR_READING_BEFORE_INSTALL",
            "reading_at is later than the current logical clock",
        )

    model = derive.model_of_placement(placement)
    site = db.get("sites", placement["site_id"])
    reading = telemetry.ingest(
        placement, model, site, reading_at, cycle_count_total, wash_temp,
        rinse_temp, pressure, source,
    )
    return response.created(response.serialize(reading))
