"""Catalog foundations: Provider, MembershipPackage, InjectableLot, Patient,
LoyaltyAccount (PRD §3.1)."""
from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import ApiError
from middleware import require_roles
from helpers import (get_json_body, require_string, require_enum, require_int,
                     require_number, require_datetime, optional_string, paginate)
from response import success_object, success_array
import domain

bp = Blueprint("catalog", __name__)

PRODUCTS = {"BOTOX", "DYSPORT", "JUVEDERM", "RESTYLANE"}
TIERS = {"BASIC", "PLUS", "VIP"}
LOYALTY_PROGRAMS = {"ALLE", "ASPIRE"}
ROLE_KINDS = {"INJECTOR", "MEDICAL_DIRECTOR"}


def _base_common():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


# --------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------
@bp.route("/aesthetics/providers", methods=["POST"])
@require_roles("ClinicAdmin")
def create_provider():
    body = get_json_body()
    full_name = require_string(body, "full_name")
    license_number = require_string(body, "license_number")
    role_kind = require_enum(body, "role_kind", ROLE_KINDS)

    provider = _base_common()
    provider.update({
        "full_name": full_name,
        "license_number": license_number,
        "role_kind": role_kind,
        "status": "ACTIVE",
        "open_complication_count": 0,
        "resolved_complication_count": 0,
        "committed_session_count": 0,
    })
    db.providers[provider["id"]] = provider
    return success_object(domain.serialize(provider, "Provider"), 201)


@bp.route("/aesthetics/providers", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_providers():
    role_kind = request.args.get("role_kind")
    status = request.args.get("status")
    records = list(db.providers.values())
    if role_kind is not None:
        records = [r for r in records if r["role_kind"] == role_kind]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "Provider") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/providers/<pid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_provider(pid):
    provider = db.providers.get(pid)
    if provider is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", "Provider not found")
    domain.recompute_provider_counts(provider)
    return success_object(domain.serialize(provider, "Provider"))


@bp.route("/aesthetics/providers/<pid>/suspend", methods=["POST"])
@require_roles("ClinicAdmin")
def suspend_provider(pid):
    provider = db.providers.get(pid)
    if provider is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", "Provider not found")
    body = get_json_body()
    expected = require_int(body, "expected_provider_version")
    if expected != provider["version"]:
        raise ApiError("ERR_STALE_PROVIDER_VERSION", "Stale provider version")
    provider["status"] = "SUSPENDED"
    domain.touch(provider)
    return success_object(domain.serialize(provider, "Provider"))


# --------------------------------------------------------------------------
# MembershipPackage
# --------------------------------------------------------------------------
@bp.route("/aesthetics/membership-packages", methods=["POST"])
@require_roles("ClinicAdmin")
def create_membership():
    body = get_json_body()
    tier = require_enum(body, "tier", TIERS)
    member_discount_pct = require_number(body, "member_discount_pct",
                                         minimum=0, maximum_exclusive=1)
    loyalty_program = require_enum(body, "loyalty_program", LOYALTY_PROGRAMS)
    monthly_fee_cents = require_int(body, "monthly_fee_cents", minimum=0)

    pkg = _base_common()
    pkg.update({
        "tier": tier,
        "member_discount_pct": member_discount_pct,
        "loyalty_program": loyalty_program,
        "monthly_fee_cents": monthly_fee_cents,
    })
    db.membership_packages[pkg["id"]] = pkg
    return success_object(domain.serialize(pkg, "MembershipPackage"), 201)


@bp.route("/aesthetics/membership-packages", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_memberships():
    tier = request.args.get("tier")
    records = list(db.membership_packages.values())
    if tier is not None:
        records = [r for r in records if r["tier"] == tier]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "MembershipPackage") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/membership-packages/<mid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_membership(mid):
    pkg = db.membership_packages.get(mid)
    if pkg is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND", "Membership package not found")
    return success_object(domain.serialize(pkg, "MembershipPackage"))


# --------------------------------------------------------------------------
# InjectableLot
# --------------------------------------------------------------------------
@bp.route("/aesthetics/injectable-lots", methods=["POST"])
@require_roles("ClinicAdmin")
def create_lot():
    body = get_json_body()
    product = require_enum(body, "product", PRODUCTS)
    lot_number = require_string(body, "lot_number")
    expiration_dt = require_datetime(body, "expiration_date")
    total_units = require_int(body, "total_units", positive=True)

    lot = _base_common()
    lot.update({
        "product": product,
        "lot_number": lot_number,
        "expiration_date": body["expiration_date"],
        "_expiration_dt": expiration_dt,
        "total_units": total_units,
        "reserved_units": 0,
        "consumed_units": 0,
        "remaining_units": total_units,
        "status": "AVAILABLE",
    })
    db.injectable_lots[lot["id"]] = lot
    return success_object(domain.serialize(lot, "InjectableLot"), 201)


@bp.route("/aesthetics/injectable-lots", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_lots():
    product = request.args.get("product")
    status = request.args.get("status")
    records = list(db.injectable_lots.values())
    if product is not None:
        records = [r for r in records if r["product"] == product]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "InjectableLot") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/injectable-lots/<lid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_lot(lid):
    lot = db.injectable_lots.get(lid)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "Injectable lot not found")
    return success_object(domain.serialize(lot, "InjectableLot"))


@bp.route("/aesthetics/injectable-lots/<lid>/quarantine", methods=["POST"])
@require_roles("ClinicAdmin")
def quarantine_lot(lid):
    lot = db.injectable_lots.get(lid)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "Injectable lot not found")
    body = get_json_body()
    expected = require_int(body, "expected_lot_version")
    if expected != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION", "Stale lot version")
    lot["status"] = "QUARANTINED"
    domain.touch(lot)
    return success_object(domain.serialize(lot, "InjectableLot"))


# --------------------------------------------------------------------------
# Patient
# --------------------------------------------------------------------------
@bp.route("/aesthetics/patients", methods=["POST"])
@require_roles("ClinicAdmin")
def create_patient():
    body = get_json_body()
    full_name = require_string(body, "full_name")
    require_datetime(body, "date_of_birth")
    membership_id = optional_string(body, "membership_id")
    if membership_id is not None and membership_id not in db.membership_packages:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND", "Membership package not found")

    patient = _base_common()
    patient.update({
        "full_name": full_name,
        "date_of_birth": body["date_of_birth"],
        "membership_id": membership_id,
        "photo_consent_on_file": False,
    })
    db.patients[patient["id"]] = patient
    return success_object(domain.serialize(patient, "Patient"), 201)


@bp.route("/aesthetics/patients", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_patients():
    membership_id = request.args.get("membership_id")
    records = list(db.patients.values())
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "Patient") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/patients/<pid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_patient(pid):
    patient = db.patients.get(pid)
    if patient is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "Patient not found")
    return success_object(domain.serialize(patient, "Patient"))


# --------------------------------------------------------------------------
# LoyaltyAccount
# --------------------------------------------------------------------------
@bp.route("/aesthetics/loyalty-accounts", methods=["POST"])
@require_roles("ClinicAdmin")
def create_loyalty_account():
    body = get_json_body()
    patient_id = require_string(body, "patient_id")
    program = require_enum(body, "program", LOYALTY_PROGRAMS)

    patient = db.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "Patient not found")

    # Loyalty program agreement (priority 5): program must equal the patient's
    # membership loyalty_program.
    membership_id = patient.get("membership_id")
    membership = db.membership_packages.get(membership_id) if membership_id else None
    if membership is None or membership["loyalty_program"] != program:
        raise ApiError("ERR_LOYALTY_PROGRAM_MISMATCH",
                       "Loyalty program does not match patient's membership")

    account = _base_common()
    account.update({
        "patient_id": patient_id,
        "program": program,
        "points_earned": 0,
        "points_redeemed": 0,
        "points_balance": 0,
    })
    db.loyalty_accounts[account["id"]] = account
    return success_object(domain.serialize(account, "LoyaltyAccount"), 201)


@bp.route("/aesthetics/loyalty-accounts", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_loyalty_accounts():
    patient_id = request.args.get("patient_id")
    records = list(db.loyalty_accounts.values())
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "LoyaltyAccount") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/loyalty-accounts/<aid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_loyalty_account(aid):
    account = db.loyalty_accounts.get(aid)
    if account is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "Loyalty account not found")
    return success_object(domain.serialize(account, "LoyaltyAccount"))
