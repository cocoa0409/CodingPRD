"""Payer policies and authorization-requirement lookup (PRD 3.1)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import raise_error, ERR_VALIDATION_FAILED, ERR_POLICY_NOT_FOUND, ERR_DUPLICATE_POLICY
from middleware import authorized
from response import success_object
from routes.helpers import ALL_ROLES, get_policy
from serializers import serialize
from util import new_id, CLOCK
from validate import get_body, req_str, req_int, req_number, req_enum, opt_bool, opt_int, opt_number, opt_enum

bp = Blueprint("policies", __name__)

BENEFIT_CHANNELS = ["MEDICAL", "PHARMACY", "EITHER"]
SITE_POLICIES = ["NO_STEERING", "STEER_TO_HOME", "STEER_TO_OFFICE"]


@bp.post("/infusion/payer-policies")
def create_policy():
    authorized(["PolicyAdmin"])
    body = get_body()
    payer_code = req_str(body, "payer_code")
    drug_code = req_str(body, "drug_code")
    regimen_name = req_str(body, "regimen_name")
    benefit_channel = req_enum(body, "benefit_channel", BENEFIT_CHANNELS)
    validity_days = req_int(body, "validity_days")
    max_course_days = req_int(body, "max_course_days")
    max_dose_mg = req_int(body, "max_dose_mg")
    deductible_cents = req_int(body, "deductible_cents")
    coinsurance_pct = req_number(body, "coinsurance_pct")
    oop_max_cents = req_int(body, "oop_max_cents")
    prepay_limit_cents = req_int(body, "prepay_limit_cents")
    requires_prior_auth = opt_bool(body, "requires_prior_auth", True)
    buy_and_bill_required = opt_bool(body, "buy_and_bill_required", False)
    pharmacy_validity_days = opt_int(body, "pharmacy_validity_days", 30)
    allowed_amount_known = opt_bool(body, "allowed_amount_known", True)
    discount_rate = opt_number(body, "discount_rate", 0.80)
    site_policy = opt_enum(body, "site_policy", SITE_POLICIES, "NO_STEERING")
    steer_threshold = opt_number(body, "steer_threshold", 1.50)

    # (payer_code, drug_code) unique across the system
    for existing in db["payer_policies"].values():
        if existing["payer_code"] == payer_code and existing["drug_code"] == drug_code:
            raise_error(ERR_DUPLICATE_POLICY,
                        f"a payer policy already exists for ({payer_code}, {drug_code})")

    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "payer_code": payer_code,
        "drug_code": drug_code,
        "regimen_name": regimen_name,
        "requires_prior_auth": requires_prior_auth,
        "benefit_channel": benefit_channel,
        "buy_and_bill_required": buy_and_bill_required,
        "validity_days": validity_days,
        "pharmacy_validity_days": pharmacy_validity_days,
        "max_course_days": max_course_days,
        "max_dose_mg": max_dose_mg,
        "allowed_amount_known": allowed_amount_known,
        "discount_rate": discount_rate,
        "site_policy": site_policy,
        "steer_threshold": steer_threshold,
        "deductible_cents": deductible_cents,
        "coinsurance_pct": coinsurance_pct,
        "oop_max_cents": oop_max_cents,
        "prepay_limit_cents": prepay_limit_cents,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["payer_policies"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/payer-policies/<pid>")
def read_policy(pid):
    authorized(ALL_ROLES)
    return success_object(serialize(get_policy(pid)))


@bp.get("/infusion/authorization-requirements/lookup")
def lookup_requirement():
    authorized(ALL_ROLES)
    payer_code = request.args.get("payer_code")
    drug_code = request.args.get("drug_code")
    if not payer_code or not drug_code:
        raise_error(ERR_VALIDATION_FAILED, "payer_code and drug_code query parameters are required")
    for policy in db["payer_policies"].values():
        if policy["payer_code"] == payer_code and policy["drug_code"] == drug_code:
            return success_object({
                "policy_id": policy["id"],
                "requires_prior_auth": policy["requires_prior_auth"],
                "benefit_channel": policy["benefit_channel"],
                "validity_days": policy["validity_days"],
                "pharmacy_validity_days": policy["pharmacy_validity_days"],
                "max_dose_mg": policy["max_dose_mg"],
                "site_policy": policy["site_policy"],
                "buy_and_bill_required": policy["buy_and_bill_required"],
            })
    raise_error(ERR_POLICY_NOT_FOUND,
                f"no payer policy matches ({payer_code}, {drug_code})")
