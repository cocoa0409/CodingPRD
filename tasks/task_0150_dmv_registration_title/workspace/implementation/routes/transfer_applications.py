"""TransferApplication endpoints — create, read, list, all state transitions."""

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, g, request

from config import (
    APP_TYPE_INITIAL_REGISTRATION,
    APP_TYPE_TITLE_TRANSFER,
    APPLICATION_TYPES,
    FUEL_ELECTRIC,
    LIEN_STATUS_ACTIVE,
    PLATE_ACTIVE,
    PLATE_ISSUED,
    PLATE_SURRENDER_TRANSFER_COMPLETE,
    PLATE_SURRENDERED,
    PLATE_SUSPENDED,
    REALID_ENFORCEMENT_ISO,
    REAL_ID_APPROVED,
    REAL_ID_REVOKED,
    REJECTION_NON_REPAIRABLE_SALVAGE,
    REJECTION_WITHDRAWN,
    ROLE_APPLICANT,
    ROLE_PLATE_ISSUER,
    ROLE_PLATFORM_ADMIN,
    ROLE_SALVAGE_OFFICER,
    ROLE_TAX_ASSESSOR,
    ROLE_VIN_VERIFIER,
    SALVAGE_DECISION_APPROVE,
    SALVAGE_DECISION_DENY,
    TITLE_STATUS_CLEAN,
    TITLE_STATUS_NON_REPAIRABLE,
    TITLE_STATUS_REBUILT,
    TITLE_STATUS_SALVAGE_PENDING_REBUILD,
    TXAPP_COMPLETED,
    TXAPP_DRAFT,
    TXAPP_EMISSIONS_PASSED,
    TXAPP_EMISSIONS_PENDING,
    TXAPP_PLATE_ISSUED,
    TXAPP_REJECTED,
    TXAPP_SALVAGE_APPROVED,
    TXAPP_SALVAGE_REVIEW,
    TXAPP_STATUSES,
    TXAPP_TAX_ASSESSED,
    TXAPP_VIN_VERIFIED,
    VIN_HOLD,
    VIN_UNVERIFIED,
    VIN_VERIFIED,
)
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import (
    build_pagination_meta,
    paginate_and_sort,
    parse_pagination,
    require_decimal,
    require_enum,
    require_field,
    require_str,
)
from services.calculations import (
    registration_fee,
    sales_tax_on_transfer,
    total_due_with_processing,
)
from services.engine import (
    append_assessment_ledger,
    stamp_create,
    stamp_update,
    supersede_title_and_create_new,
)
from services.serializers import serialize_transfer_application
from utils import (
    PLATE_REGEX,
    decimal_to_cents,
    iso_format,
    new_uuid,
    parse_iso8601,
)

transfer_bp = Blueprint("transfer", __name__)


# -----------------------------------------------------------------------------
# Create / read / list
# -----------------------------------------------------------------------------
@transfer_bp.route("/vehicles/<vehicle_id>/transfer-applications", methods=["POST"])
@require_auth(allowed_roles=[ROLE_APPLICANT])
def create_transfer_application(vehicle_id: str):
    body = parse_json_body()
    application_type = require_enum(require_field(body, "application_type"),
                                    "application_type", APPLICATION_TYPES)
    applicant_owner_id = require_str(require_field(body, "applicant_owner_id"),
                                     "applicant_owner_id")
    declared_sale_price = require_decimal(require_field(body, "declared_sale_price"),
                                          "declared_sale_price",
                                          min_value=Decimal("0.01"),
                                          max_value=Decimal("2000000.00"))
    trade_in_raw = body.get("trade_in_value", "0.00")
    if trade_in_raw is None:
        trade_in_raw = "0.00"
    trade_in_value = require_decimal(trade_in_raw, "trade_in_value",
                                     min_value=Decimal("0.00"),
                                     max_value=Decimal("1000000.00"))

    with store.lock:
        vehicle = store.vehicles.get(vehicle_id)
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        owner = store.owners.get(applicant_owner_id)
        if owner is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        # Ownership: Applicant's X-User-ID must equal applicant_owner_id
        if g.user_id != applicant_owner_id:
            raise make_error("ERR_ROLE_FORBIDDEN")

        app = {
            "vehicle_id": vehicle_id,
            "applicant_owner_id": applicant_owner_id,
            "application_type": application_type,
            "status": TXAPP_DRAFT,
            "salvage_branch_taken": False,
            "trade_in_value": trade_in_value,
            "declared_sale_price": declared_sale_price,
            "fee_subtotal": None,
            "processing_fee": None,
            "total_due": None,
            "paid_at": None,
            "plate_id": None,
            "rejection_reason": None,
        }
        stamp_create(app, now=store.now())
        store.transfer_applications[app["id"]] = app

    return success(serialize_transfer_application(app), status=201)


@transfer_bp.route("/transfer-applications/<app_id>", methods=["GET"])
@require_auth(allowed_roles=[
    ROLE_APPLICANT, ROLE_VIN_VERIFIER, ROLE_TAX_ASSESSOR, ROLE_PLATE_ISSUER,
    ROLE_SALVAGE_OFFICER, ROLE_PLATFORM_ADMIN,
])
def read_transfer_application(app_id: str):
    app = store.transfer_applications.get(app_id)
    if app is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    return success(serialize_transfer_application(app))


@transfer_bp.route("/transfer-applications", methods=["GET"])
@require_auth(allowed_roles=[
    ROLE_PLATFORM_ADMIN, ROLE_VIN_VERIFIER, ROLE_TAX_ASSESSOR, ROLE_PLATE_ISSUER,
])
def list_transfer_applications():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    applicant_owner_id = request.args.get("applicant_owner_id")
    vehicle_id = request.args.get("vehicle_id")
    if status is not None and status not in TXAPP_STATUSES:
        raise make_error("ERR_VALIDATION", "Invalid status filter.")

    rows = []
    for app in store.transfer_applications.values():
        if status is not None and app["status"] != status:
            continue
        if applicant_owner_id is not None and app["applicant_owner_id"] != applicant_owner_id:
            continue
        if vehicle_id is not None and app["vehicle_id"] != vehicle_id:
            continue
        rows.append(app)
    page, total = paginate_and_sort(rows, limit, offset, sort_key="created_at")
    return success([serialize_transfer_application(a) for a in page],
                   pagination=build_pagination_meta(limit, offset, total))


# -----------------------------------------------------------------------------
# Verify VIN (path: /vehicles/{vehicle_id}/transfer-applications/{id}/verify-vin)
# -----------------------------------------------------------------------------
@transfer_bp.route("/vehicles/<vehicle_id>/transfer-applications/<app_id>/verify-vin",
                   methods=["POST"])
@require_auth(allowed_roles=[ROLE_VIN_VERIFIER])
def verify_vin_nested(vehicle_id: str, app_id: str):
    parse_json_body()
    with store.lock:
        vehicle = store.vehicles.get(vehicle_id)
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        app = store.transfer_applications.get(app_id)
        if app is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        if app["vehicle_id"] != vehicle_id:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        # Priority 5: VIN on hold
        if vehicle["vin_verification_status"] == VIN_HOLD:
            raise make_error("ERR_VIN_ON_HOLD")
        # Priority 6: TransferApplication state matches the from-state DRAFT
        if app["status"] != TXAPP_DRAFT:
            raise make_error("ERR_INVALID_STATE")
        # PRD §3.4: verify-vin succeeds on every title_status — if the
        # vehicle is SALVAGE_PENDING_REBUILD or NON_REPAIRABLE, the
        # application auto-branches into SALVAGE_REVIEW; otherwise it
        # advances to EMISSIONS_PENDING. verify-vin does NOT itself
        # reject on any title_status value.
        # Priority 18: outstanding holds on owner
        owner = store.owners.get(app["applicant_owner_id"])
        if owner is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        if owner["outstanding_holds_count"] > 0:
            raise make_error("ERR_OWNER_HAS_HOLDS")

        now = store.now()
        # Apply VIN verification side effects
        vehicle["vin_verification_status"] = VIN_VERIFIED
        vehicle["vin_verified_at"] = iso_format(now)
        stamp_update(vehicle, now=now)

        # Transition app DRAFT -> VIN_VERIFIED then auto-branch
        app["status"] = TXAPP_VIN_VERIFIED
        stamp_update(app, now=now)

        if vehicle["title_status"] in (TITLE_STATUS_SALVAGE_PENDING_REBUILD,
                                       TITLE_STATUS_NON_REPAIRABLE):
            app["status"] = TXAPP_SALVAGE_REVIEW
            app["salvage_branch_taken"] = True
            stamp_update(app, now=now)
        else:
            # CLEAN or REBUILT -> EMISSIONS_PENDING
            app["status"] = TXAPP_EMISSIONS_PENDING
            stamp_update(app, now=now)

    return success(serialize_transfer_application(app))


# Also expose the non-nested form per SCAFFOLD endpoint listing:
# POST /transfer-applications/{id}/verify-vin (PRD §4 also lists this exact route)
@transfer_bp.route("/transfer-applications/<app_id>/verify-vin", methods=["POST"])
@require_auth(allowed_roles=[ROLE_VIN_VERIFIER])
def verify_vin_direct(app_id: str):
    app = store.transfer_applications.get(app_id)
    if app is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    return verify_vin_nested(app["vehicle_id"], app_id)


# -----------------------------------------------------------------------------
# Approve-salvage
# -----------------------------------------------------------------------------
@transfer_bp.route("/transfer-applications/<app_id>/approve-salvage", methods=["POST"])
@require_auth(allowed_roles=[ROLE_SALVAGE_OFFICER])
def approve_salvage(app_id: str):
    body = parse_json_body()
    decision = require_enum(require_field(body, "decision"), "decision",
                            {SALVAGE_DECISION_APPROVE, SALVAGE_DECISION_DENY})

    with store.lock:
        app = store.transfer_applications.get(app_id)
        if app is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        if app["status"] != TXAPP_SALVAGE_REVIEW:
            raise make_error("ERR_INVALID_STATE")
        vehicle = store.vehicles.get(app["vehicle_id"])
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        now = store.now()
        if decision == SALVAGE_DECISION_APPROVE:
            # APPROVE is permitted only when title_status == SALVAGE_PENDING_REBUILD
            # AND application_type == TITLE_TRANSFER
            if vehicle["title_status"] != TITLE_STATUS_SALVAGE_PENDING_REBUILD:
                raise make_error("ERR_INVALID_STATE",
                                 "APPROVE requires title_status SALVAGE_PENDING_REBUILD.")
            if app["application_type"] != APP_TYPE_TITLE_TRANSFER:
                raise make_error("ERR_INVALID_STATE",
                                 "APPROVE requires application_type TITLE_TRANSFER.")
            vehicle["title_status"] = TITLE_STATUS_REBUILT
            vehicle["emissions_expires_at"] = None
            stamp_update(vehicle, now=now)
            app["status"] = TXAPP_SALVAGE_APPROVED
            stamp_update(app, now=now)
            # System follow-on to EMISSIONS_PENDING
            app["status"] = TXAPP_EMISSIONS_PENDING
            stamp_update(app, now=now)
        else:
            # DENY: requires title_status == NON_REPAIRABLE
            if vehicle["title_status"] != TITLE_STATUS_NON_REPAIRABLE:
                raise make_error("ERR_INVALID_STATE",
                                 "DENY requires title_status NON_REPAIRABLE.")
            app["status"] = TXAPP_REJECTED
            app["rejection_reason"] = REJECTION_NON_REPAIRABLE_SALVAGE
            stamp_update(app, now=now)

    return success(serialize_transfer_application(app))


# -----------------------------------------------------------------------------
# Assess-fees
# -----------------------------------------------------------------------------
@transfer_bp.route("/transfer-applications/<app_id>/assess-fees", methods=["POST"])
@require_auth(allowed_roles=[ROLE_TAX_ASSESSOR])
def assess_fees(app_id: str):
    parse_json_body()
    with store.lock:
        app = store.transfer_applications.get(app_id)
        if app is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        # Priority 6: state must be EMISSIONS_PASSED
        if app["status"] != TXAPP_EMISSIONS_PASSED:
            raise make_error("ERR_INVALID_STATE")

        vehicle = store.vehicles.get(app["vehicle_id"])
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        owner = store.owners.get(app["applicant_owner_id"])
        if owner is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        # Priority 7: NON_REPAIRABLE / SALVAGE_PENDING_REBUILD blocks
        if vehicle["title_status"] in (TITLE_STATUS_NON_REPAIRABLE,
                                       TITLE_STATUS_SALVAGE_PENDING_REBUILD):
            raise make_error("ERR_VEHICLE_SALVAGE_LOCKED")

        # Priority 9: emissions expiry
        emissions_expires_at = vehicle.get("emissions_expires_at")
        if vehicle["fuel_type"] != FUEL_ELECTRIC:
            if emissions_expires_at is None:
                raise make_error("ERR_EMISSIONS_EXPIRED")
            expiry_dt = parse_iso8601(emissions_expires_at)
            if store.now() >= expiry_dt:
                raise make_error("ERR_EMISSIONS_EXPIRED")

        # Priority 10: REAL ID revoked
        if owner["real_id_status"] == REAL_ID_REVOKED:
            raise make_error("ERR_OWNER_REAL_ID_REVOKED")

        # Priority 11: lien active
        if vehicle["lien_status"] == LIEN_STATUS_ACTIVE:
            raise make_error("ERR_LIEN_ACTIVE")

        # Run calculations
        now = store.now()
        current_year = now.year
        reg_fee = registration_fee(
            vehicle["curb_weight_lbs"], vehicle["model_year"],
            owner["is_resident"], current_year,
        )
        sales_tax = sales_tax_on_transfer(
            app["declared_sale_price"], app["trade_in_value"],
            owner["is_resident"], app["application_type"],
        )
        fee_subtotal, processing_fee, total_due = total_due_with_processing(
            sales_tax, reg_fee,
        )

        app["fee_subtotal"] = fee_subtotal
        app["processing_fee"] = processing_fee
        app["total_due"] = total_due
        app["status"] = TXAPP_TAX_ASSESSED
        stamp_update(app, now=now)

        # Ledger writes (positive cents)
        append_assessment_ledger(
            app["id"],
            sales_tax_cents=decimal_to_cents(sales_tax),
            reg_fee_cents=decimal_to_cents(reg_fee),
            processing_fee_cents=decimal_to_cents(processing_fee),
            now=now,
        )

        # Record the X-User-ID who ran assessment (for segregation-of-duties later)
        store.assess_fees_actor[app["id"]] = g.user_id

    return success(serialize_transfer_application(app))


# -----------------------------------------------------------------------------
# Mark-paid
# -----------------------------------------------------------------------------
@transfer_bp.route("/transfer-applications/<app_id>/mark-paid", methods=["POST"])
@require_auth(allowed_roles=[ROLE_APPLICANT])
def mark_paid(app_id: str):
    parse_json_body()
    with store.lock:
        app = store.transfer_applications.get(app_id)
        if app is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        if app["status"] != TXAPP_TAX_ASSESSED:
            raise make_error("ERR_INVALID_STATE")
        # Ownership
        if g.user_id != app["applicant_owner_id"]:
            raise make_error("ERR_ROLE_FORBIDDEN")
        now = store.now()
        app["paid_at"] = iso_format(now)
        stamp_update(app, now=now)
    return success(serialize_transfer_application(app))


# -----------------------------------------------------------------------------
# Issue-plate
# -----------------------------------------------------------------------------
@transfer_bp.route("/transfer-applications/<app_id>/issue-plate", methods=["POST"])
@require_auth(allowed_roles=[ROLE_PLATE_ISSUER])
def issue_plate(app_id: str):
    body = parse_json_body()
    plate_number = require_str(require_field(body, "plate_number"), "plate_number")
    if not PLATE_REGEX.match(plate_number):
        raise make_error("ERR_VALIDATION", "plate_number must match ^[A-Z0-9]{2,8}$.")

    with store.lock:
        app = store.transfer_applications.get(app_id)
        if app is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        # Priority 6: state from TAX_ASSESSED
        if app["status"] != TXAPP_TAX_ASSESSED:
            raise make_error("ERR_INVALID_STATE")
        vehicle = store.vehicles.get(app["vehicle_id"])
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        owner = store.owners.get(app["applicant_owner_id"])
        if owner is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        # Priority 7: NON_REPAIRABLE blocks
        if vehicle["title_status"] in (TITLE_STATUS_NON_REPAIRABLE,
                                       TITLE_STATUS_SALVAGE_PENDING_REBUILD):
            raise make_error("ERR_VEHICLE_SALVAGE_LOCKED")

        # Priority 10: REAL ID revoked
        if owner["real_id_status"] == REAL_ID_REVOKED:
            raise make_error("ERR_OWNER_REAL_ID_REVOKED")

        # Priority 13: plate-number uniqueness among ISSUED/ACTIVE/SUSPENDED plates
        for p in store.plates.values():
            if p["plate_number"] == plate_number and p["status"] in (
                    PLATE_ISSUED, PLATE_ACTIVE, PLATE_SUSPENDED):
                raise make_error("ERR_PLATE_NUMBER_TAKEN")

        # Priority 14: segregation of duties — same X-User-ID cannot have run assess-fees
        assess_actor = store.assess_fees_actor.get(app["id"])
        if assess_actor is not None and assess_actor == g.user_id:
            raise make_error("ERR_SEGREGATION_OF_DUTIES")

        # Priority 17: payment required
        if app.get("paid_at") is None:
            raise make_error("ERR_PAYMENT_REQUIRED")

        # REAL ID enforcement: APPROVED OR now < 2027-05-07T00:00:00Z
        enforcement_dt = parse_iso8601(REALID_ENFORCEMENT_ISO)
        if owner["real_id_status"] != REAL_ID_APPROVED and store.now() >= enforcement_dt:
            raise make_error("ERR_OWNER_REAL_ID_REVOKED",
                             "REAL ID approval is required after the federal enforcement date.")

        now = store.now()
        # Create plate (ISSUED then auto-follow to ACTIVE)
        plate = {
            "plate_number": plate_number,
            "vehicle_id": vehicle["id"],
            "status": PLATE_ACTIVE,
            "activated_at": iso_format(now),
            "suspended_at": None,
            "surrender_reason": None,
        }
        stamp_create(plate, now=now)
        store.plates[plate["id"]] = plate

        # Update application
        app["plate_id"] = plate["id"]
        app["status"] = TXAPP_PLATE_ISSUED
        stamp_update(app, now=now)

        # If TITLE_TRANSFER and prior plate exists on the vehicle, surrender it
        if app["application_type"] == APP_TYPE_TITLE_TRANSFER:
            for p in store.plates.values():
                if p["id"] == plate["id"]:
                    continue
                if p["vehicle_id"] != vehicle["id"]:
                    continue
                if p["status"] in (PLATE_ACTIVE, PLATE_SUSPENDED, PLATE_ISSUED):
                    p["status"] = PLATE_SURRENDERED
                    p["surrender_reason"] = PLATE_SURRENDER_TRANSFER_COMPLETE
                    stamp_update(p, now=now)

        # System follow-on PLATE_ISSUED -> COMPLETED + create new Title
        supersede_title_and_create_new(
            vehicle, owner_id=app["applicant_owner_id"],
            application_id=app["id"], now=now,
        )
        app["status"] = TXAPP_COMPLETED
        stamp_update(app, now=now)

    return success(serialize_transfer_application(app))


# -----------------------------------------------------------------------------
# Withdraw
# -----------------------------------------------------------------------------
@transfer_bp.route("/transfer-applications/<app_id>/withdraw", methods=["POST"])
@require_auth(allowed_roles=[ROLE_APPLICANT])
def withdraw(app_id: str):
    parse_json_body()
    with store.lock:
        app = store.transfer_applications.get(app_id)
        if app is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        if app["status"] != TXAPP_DRAFT:
            raise make_error("ERR_INVALID_STATE")
        if g.user_id != app["applicant_owner_id"]:
            raise make_error("ERR_ROLE_FORBIDDEN")
        app["status"] = TXAPP_REJECTED
        app["rejection_reason"] = REJECTION_WITHDRAWN
        stamp_update(app, now=store.now())
    return success(serialize_transfer_application(app))
