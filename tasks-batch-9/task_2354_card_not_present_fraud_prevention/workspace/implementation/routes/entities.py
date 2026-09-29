"""Customers, analysts, device profiles and address records (PRD 3.1 / 3.6)."""

from flask import Blueprint, g

import calc
import services as svc
import validators as v
from db import db, touch
from errors import ApiError
from middleware import roles
from response import created, ok, serialize
from routes._common import paged

bp = Blueprint("entities", __name__, url_prefix="/fraud")

READ_ALL = (
    "PlatformAdmin",
    "CheckoutService",
    "RiskAnalyst",
    "ReviewLead",
    "PolicyEngineer",
)


# =============================================================== Customer
@bp.route("/customers", methods=["POST"])
@roles("PlatformAdmin", "CheckoutService")
def create_customer():
    payload = v.body()
    email = v.as_str(payload, "email")
    home_country = v.as_country(payload, "home_country")
    tier = v.as_enum(payload, "tier", calc.TIERS, required=False, default="STANDARD")

    row = svc.new_row(
        email=email,
        tier=tier,
        home_country=home_country,
        account_status="ACTIVE",
        ato_posture="CLEAR",
        lifetime_net_approved_cents=0,
        approved_count=0,
        declined_count=0,
        confirmed_fraud_count=0,
        failed_login_count=0,
        good_customer_flag=False,
        locked_reason=None,
    )
    db.customers[row["id"]] = row
    return created(serialize(row))


@bp.route("/customers", methods=["GET"])
@roles(*READ_ALL)
def list_customers():
    return paged(
        list(db.customers.values()),
        [
            ("tier", v.query_enum("tier", calc.TIERS)),
            ("account_status", v.query_enum("account_status", calc.ACCOUNT_STATUSES)),
            ("ato_posture", v.query_enum("ato_posture", calc.ATO_POSTURES)),
            ("good_customer_flag", v.query_bool("good_customer_flag")),
        ],
    )


@bp.route("/customers/<cid>", methods=["GET"])
@roles(*READ_ALL)
def read_customer(cid):
    return ok(serialize(v.lookup(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")))


@bp.route("/customers/<cid>/posture", methods=["POST"])
@roles("PlatformAdmin")
def customer_posture(cid):
    customer = v.lookup(db.customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    payload = v.body()
    account_status = v.as_enum(
        payload, "account_status", calc.ACCOUNT_STATUSES, required=False
    )
    ato_posture = v.as_enum(
        payload, "ato_posture", calc.ATO_POSTURES, required=False
    )
    reason = v.as_str(payload, "reason", required=False)
    # priority 15: exactly one axis must be driven
    if (account_status is None) == (ato_posture is None):
        v.bad()

    if account_status is not None:
        current = customer["account_status"]
        if current == "ACTIVE" and account_status == "LOCKED":
            customer["account_status"] = "LOCKED"
            customer["locked_reason"] = reason
            svc.recompute_good_standing(customer)
        elif current == "LOCKED" and account_status == "ACTIVE":
            customer["account_status"] = "ACTIVE"
            customer["locked_reason"] = None
            svc.recompute_good_standing(customer)
        elif current == "ACTIVE" and account_status == "CLOSED":
            customer["account_status"] = "CLOSED"
            customer["good_customer_flag"] = False
        else:
            raise ApiError("ERR_CUSTOMER_POSTURE_INVALID")
    else:
        if customer["ato_posture"] == "CONTAINED" and ato_posture == "CLEAR":
            customer["ato_posture"] = "CLEAR"
            customer["failed_login_count"] = 0
            svc.recompute_good_standing(customer)
        else:
            raise ApiError("ERR_CUSTOMER_POSTURE_INVALID")

    touch(customer)
    return ok(serialize(customer))


# ================================================================ Analyst
@bp.route("/analysts", methods=["POST"])
@roles("PlatformAdmin")
def create_analyst():
    payload = v.body()
    display_name = v.as_str(payload, "display_name")
    seniority = v.as_enum(payload, "seniority", calc.SENIORITIES)
    skill_families = v.as_string_array(payload, "skill_families", calc.SKILL_FAMILIES)
    shift_capacity_cases = v.as_int(payload, "shift_capacity_cases", minimum=1)

    row = svc.new_row(
        display_name=display_name,
        seniority=seniority,
        skill_families=skill_families,
        shift_capacity_cases=shift_capacity_cases,
        status="AVAILABLE",
        open_case_count=0,
        resolved_case_count=0,
    )
    db.analysts[row["id"]] = row
    return created(serialize(row))


@bp.route("/analysts", methods=["GET"])
@roles("PlatformAdmin", "ReviewLead", "RiskAnalyst")
def list_analysts():
    return paged(
        list(db.analysts.values()),
        [
            ("status", v.query_enum("status", calc.ANALYST_STATUSES)),
            ("seniority", v.query_enum("seniority", calc.SENIORITIES)),
        ],
    )


@bp.route("/analysts/<aid>", methods=["GET"])
@roles("PlatformAdmin", "ReviewLead", "RiskAnalyst")
def read_analyst(aid):
    return ok(serialize(v.lookup(db.analysts, aid, "ERR_ANALYST_NOT_FOUND")))


@bp.route("/analysts/<aid>/shift", methods=["POST"])
@roles("PlatformAdmin")
def analyst_shift(aid):
    analyst = v.lookup(db.analysts, aid, "ERR_ANALYST_NOT_FOUND")
    payload = v.body()
    status = v.as_enum(payload, "status", calc.ANALYST_STATUSES)

    previous = analyst["status"]
    analyst["status"] = status
    if previous == "AVAILABLE" and status != "AVAILABLE":
        # shift-release cascade (PRD 3.6)
        svc.release_analyst_cases(analyst)
    touch(analyst)
    return ok(serialize(analyst))


# ========================================================== DeviceProfile
@bp.route("/devices", methods=["POST"])
@roles("CheckoutService", "PlatformAdmin")
def create_device():
    payload = v.body()
    device_hash = v.as_str(payload, "device_hash")
    tz_offset_minutes = v.as_int(payload, "tz_offset_minutes")
    emulator_flag = v.as_bool(payload, "emulator_flag", required=False, default=False)

    # priority 80: device_hash is globally unique
    for other in db.devices.values():
        if other["device_hash"] == device_hash:
            raise ApiError("ERR_DUPLICATE_DEVICE_HASH")

    row = svc.new_row(
        device_hash=device_hash,
        emulator_flag=emulator_flag,
        tz_offset_minutes=tz_offset_minutes,
        reputation="NEW",
        distinct_customer_count=0,
        approved_use_count=0,
        fraud_confirmed_count=0,
    )
    db.devices[row["id"]] = row
    svc.recompute_device(row)
    return created(serialize(row))


@bp.route("/devices", methods=["GET"])
@roles(*READ_ALL)
def list_devices():
    return paged(
        list(db.devices.values()),
        [
            ("reputation", v.query_enum("reputation", calc.DEVICE_REPUTATIONS)),
            ("emulator_flag", v.query_bool("emulator_flag")),
        ],
    )


@bp.route("/devices/<did>", methods=["GET"])
@roles(*READ_ALL)
def read_device(did):
    return ok(serialize(v.lookup(db.devices, did, "ERR_DEVICE_NOT_FOUND")))


# ========================================================== AddressRecord
@bp.route("/addresses", methods=["POST"])
@roles("CheckoutService", "RiskAnalyst", "PlatformAdmin")
def create_address():
    payload = v.body()
    # priority 11: body foreign key first
    parent = v.required_fk(
        payload, "canonical_parent_address_id", db.addresses, "ERR_ADDRESS_NOT_FOUND"
    )
    line1 = v.as_str(payload, "line1")
    postal_code = v.as_str(payload, "postal_code")
    country_code = v.as_country(payload, "country_code")
    classification = v.as_enum(
        payload,
        "classification",
        calc.ADDRESS_CLASSIFICATIONS,
        required=False,
        default="RESIDENTIAL",
    )
    # priority 68: clusters are single-level
    if parent is not None and parent.get("canonical_parent_address_id") is not None:
        raise ApiError("ERR_ADDRESS_CLUSTER_DEPTH")

    row = svc.new_row(
        line1=line1,
        postal_code=postal_code,
        country_code=country_code,
        classification=classification,
        canonical_parent_address_id=parent["id"] if parent is not None else None,
        canonical_address_id=None,
        distinct_customer_count=0,
        approved_use_count=0,
        fraud_confirmed_count=0,
        promo_redemption_count=0,
        drop_risk_state="CLEAN",
        reshipper_confidence=calc.rh(0, 2),
    )
    row["canonical_address_id"] = parent["id"] if parent is not None else row["id"]
    db.addresses[row["id"]] = row
    if parent is not None:
        svc.recompute_address_cluster(parent)
    return created(serialize(row))


@bp.route("/addresses", methods=["GET"])
@roles(*READ_ALL)
def list_addresses():
    return paged(
        list(db.addresses.values()),
        [
            (
                "canonical_parent_address_id",
                v.query_str("canonical_parent_address_id"),
            ),
            ("canonical_address_id", v.query_str("canonical_address_id")),
            (
                "classification",
                v.query_enum("classification", calc.ADDRESS_CLASSIFICATIONS),
            ),
            ("drop_risk_state", v.query_enum("drop_risk_state", calc.DROP_RISK_STATES)),
        ],
    )


@bp.route("/addresses/<aid>", methods=["GET"])
@roles(*READ_ALL)
def read_address(aid):
    return ok(serialize(v.lookup(db.addresses, aid, "ERR_ADDRESS_NOT_FOUND")))
