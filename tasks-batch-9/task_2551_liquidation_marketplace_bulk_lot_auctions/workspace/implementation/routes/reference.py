"""Reference layer: seller, buyer, warehouse, carrier and brand-policy rows."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.helpers import list_rows
from services import aggregates, calc, lookups
from util import clock

bp = Blueprint("reference", __name__)

ADMIN = (mw.PLATFORM_ADMIN,)


# ------------------------------------------------------------ seller accounts

@bp.post("/liquidation/seller-accounts")
def create_seller():
    mw.authenticate(ADMIN)
    payload = mw.body()
    legal_name = mw.req_str(payload, "legal_name")
    tax_id = mw.req_str(payload, "tax_id")
    state_code = mw.req_str(payload, "state_code")
    contact_email = mw.req_str(payload, "contact_email")
    for existing in db.sellers.values():
        if existing["tax_id"] == tax_id:
            raise ApiError("ERR_DUPLICATE_TAX_ID")
    row = db.new_row(
        legal_name=legal_name,
        tax_id=tax_id,
        state_code=state_code,
        contact_email=contact_email,
        account_status="ACTIVE",
        commission_tier="TIER_STANDARD",
        commission_rate_bps=calc.TIER_STANDARD_BPS,
        gross_hammer_cents=0,
        listed_retail_value_cents=0,
        gross_recovery_rate=0.0,
        net_proceeds_cents=0,
        sold_retail_value_cents=0,
        net_recovery_rate=0.0,
        manifest_accuracy_avg=1.0,
        scored_lot_count=0,
    )
    db.sellers[row["id"]] = row
    return response.created(db.view("seller", row))


@bp.get("/liquidation/seller-accounts/<seller_id>")
def read_seller(seller_id):
    mw.authenticate((mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.TRUST_SAFETY))
    return response.success(db.view("seller", lookups.seller(seller_id)))


@bp.get("/liquidation/seller-accounts")
def list_sellers():
    mw.authenticate((mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.TRUST_SAFETY))
    return list_rows(
        "seller",
        list(db.sellers.values()),
        (("account_status", "account_status"), ("commission_tier", "commission_tier")),
    )


# ------------------------------------------------------------- buyer accounts

@bp.post("/liquidation/buyer-accounts")
def create_buyer():
    mw.authenticate(ADMIN)
    payload = mw.body()
    legal_name = mw.req_str(payload, "legal_name")
    tax_id = mw.req_str(payload, "tax_id")
    state_code = mw.req_str(payload, "state_code")
    contact_email = mw.req_str(payload, "contact_email")
    certificate_number = mw.opt_str(payload, "resale_certificate_number")
    expires_on = mw.opt_date(payload, "resale_certificate_expires_on")
    requested = mw.opt_int(payload, "requested_credit_limit_cents", 0, minimum=0)
    for existing in db.buyers.values():
        if existing["tax_id"] == tax_id:
            raise ApiError("ERR_DUPLICATE_TAX_ID")
    row = db.new_row(
        legal_name=legal_name,
        tax_id=tax_id,
        state_code=state_code,
        contact_email=contact_email,
        resale_certificate_number=certificate_number,
        resale_certificate_expires_on=expires_on,
        requested_credit_limit_cents=requested,
        business_verification_status="UNVERIFIED",
        qualification_status="PENDING",
        approved_credit_limit_cents=0,
        outstanding_exposure_cents=0,
        wallet_credit_cents=0,
    )
    db.buyers[row["id"]] = row
    return response.created(db.view("buyer", row))


@bp.get("/liquidation/buyer-accounts/<buyer_id>")
def read_buyer(buyer_id):
    mw.authenticate((mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.TRUST_SAFETY, mw.BUYER))
    return response.success(db.view("buyer", lookups.buyer(buyer_id)))


@bp.get("/liquidation/buyer-accounts")
def list_buyers():
    mw.authenticate((mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.TRUST_SAFETY))
    return list_rows(
        "buyer",
        list(db.buyers.values()),
        (("qualification_status", "qualification_status"), ("state_code", "state_code")),
    )


QUALIFICATION_FROM_STATES = {
    "QUALIFY": ("PENDING", "SUSPENDED"),
    "REJECT": ("PENDING",),
    "SUSPEND": ("QUALIFIED",),
}


@bp.post("/liquidation/buyer-accounts/<buyer_id>/qualification-decisions")
def decide_qualification(buyer_id):
    mw.authenticate((mw.TRUST_SAFETY,))
    buyer = lookups.buyer(buyer_id)
    payload = mw.body()
    decision = mw.req_enum(payload, "decision", ("QUALIFY", "REJECT", "SUSPEND"))
    business_verified = mw.opt_bool(payload, "business_verified", None)
    approved_limit = mw.opt_int(payload, "approved_credit_limit_cents", None, minimum=0)

    # band 9: legal from-state
    if buyer["qualification_status"] not in QUALIFICATION_FROM_STATES[decision]:
        raise ApiError("ERR_BUYER_QUALIFICATION_STATE_INVALID")

    if decision == "QUALIFY":
        # band 12: the resale certificate must not have lapsed
        if buyer["qualification_status"] == "PENDING":
            number = buyer.get("resale_certificate_number")
            if not number or not str(number).strip():
                raise ApiError("ERR_RESALE_CERTIFICATE_EXPIRED")
        expires_on = buyer.get("resale_certificate_expires_on")
        if expires_on is None or expires_on <= clock.now().date():
            raise ApiError("ERR_RESALE_CERTIFICATE_EXPIRED")
        # band 15: the request must attest business verification
        if buyer["qualification_status"] == "PENDING" and business_verified is not True:
            raise ApiError("ERR_BUSINESS_NOT_VERIFIED")

    if decision == "QUALIFY":
        buyer["qualification_status"] = "QUALIFIED"
        buyer["business_verification_status"] = "VERIFIED"
    elif decision == "REJECT":
        buyer["qualification_status"] = "REJECTED"
        buyer["business_verification_status"] = "REJECTED"
    else:
        buyer["qualification_status"] = "SUSPENDED"

    if approved_limit is not None:
        buyer["approved_credit_limit_cents"] = approved_limit
    db.touch(buyer)
    return response.success(db.view("buyer", buyer))


@bp.post("/liquidation/buyer-accounts/<buyer_id>/credit-limits")
def set_credit_limit(buyer_id):
    mw.authenticate(ADMIN)
    buyer = lookups.buyer(buyer_id)
    payload = mw.body()
    approved_limit = mw.req_int(payload, "approved_credit_limit_cents", minimum=0)
    buyer["approved_credit_limit_cents"] = approved_limit
    aggregates.recompute_buyer_exposure(buyer)
    db.touch(buyer)
    return response.success(db.view("buyer", buyer))


# ------------------------------------------------------- warehouses, carriers

@bp.post("/liquidation/warehouses")
def create_warehouse():
    mw.authenticate(ADMIN)
    payload = mw.body()
    row = db.new_row(
        name=mw.req_str(payload, "name"),
        state_code=mw.req_str(payload, "state_code"),
        dock_door_count=mw.req_int(payload, "dock_door_count", minimum=1),
        turnaround_buffer_minutes=mw.opt_int(
            payload, "turnaround_buffer_minutes", 15, minimum=0
        ),
    )
    db.warehouses[row["id"]] = row
    return response.created(db.view("warehouse", row))


@bp.get("/liquidation/warehouses/<warehouse_id>")
def read_warehouse(warehouse_id):
    mw.authenticate((mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.BUYER))
    return response.success(db.view("warehouse", lookups.warehouse(warehouse_id)))


@bp.post("/liquidation/carriers")
def create_carrier():
    mw.authenticate(ADMIN)
    payload = mw.body()
    name = mw.req_str(payload, "name")
    scac_code = mw.req_str(payload, "scac_code")
    capacity = mw.req_int(payload, "daily_pickup_capacity", minimum=1)
    for existing in db.carriers.values():
        if existing["scac_code"] == scac_code:
            raise ApiError("ERR_DUPLICATE_SCAC")
    row = db.new_row(name=name, scac_code=scac_code, daily_pickup_capacity=capacity)
    db.carriers[row["id"]] = row
    return response.created(db.view("carrier", row))


@bp.get("/liquidation/carriers/<carrier_id>")
def read_carrier(carrier_id):
    mw.authenticate((mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.BUYER))
    return response.success(db.view("carrier", lookups.carrier(carrier_id)))


# ------------------------------------------------------------- brand policies

@bp.post("/liquidation/brand-policies")
def create_brand_policy():
    mw.authenticate(ADMIN)
    payload = mw.body()
    brand_code = mw.req_str(payload, "brand_code")
    channels = mw.req_str_list(payload, "permitted_channels", non_empty=True)
    for channel in channels:
        if channel not in mw.RESALE_CHANNELS:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "permitted_channels must contain only declared resale channels.",
            )
    states = mw.opt_str_list(payload, "prohibited_buyer_state_codes", []) or []
    row = db.new_row(
        brand_code=brand_code,
        permitted_channels=channels,
        de_branding_required=mw.opt_bool(payload, "de_branding_required", False),
        debranding_fee_cents_per_unit=mw.opt_int(
            payload, "debranding_fee_cents_per_unit", 0, minimum=0
        ),
        prohibited_buyer_state_codes=states,
        embargo_start_at=mw.opt_datetime(payload, "embargo_start_at"),
        embargo_end_at=mw.opt_datetime(payload, "embargo_end_at"),
    )
    db.brand_policies[row["id"]] = row
    return response.created(db.view("brand_policy", row))


@bp.get("/liquidation/brand-policies/<policy_id>")
def read_brand_policy(policy_id):
    mw.authenticate((mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.TRUST_SAFETY))
    return response.success(db.view("brand_policy", lookups.brand_policy(policy_id)))
