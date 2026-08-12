"""ConversionRequest endpoints (PRD §3.10)."""
from datetime import timedelta

from flask import Blueprint

import domain
import errors
from db import store
from middleware import require_auth, json_body, require_fields, ALL_ROLES
from response import ok_object
from routes.policies import get_policy_or_404, _paged
from services import calculations as calc
from services import engine
from util import age_years

bp = Blueprint("conversions", __name__)


def get_conversion_or_404(policy, cid):
    conv = store.conversion_requests.get(cid)
    if conv is None or conv["source_policy_id"] != policy["id"]:
        raise errors.not_found(errors.ERR_CONVERSION_NOT_FOUND, "conversion request")
    return conv


def _window_open(policy):
    return store.current_date() <= policy["issue_date"] + timedelta(
        days=domain.FIVE_YEARS_DAYS)


def _target_compatible(target_id):
    target = store.product_templates.get(target_id)
    if target is None or target["product_type"] == "TERM_CONVERTIBLE":
        raise errors.incompatible_reference(
            "Target product template must exist and must not be TERM_CONVERTIBLE")
    return target


@bp.route("/policies/<policy_id>/conversion-requests", methods=["POST"])
def create_conversion(policy_id):
    ctx = require_auth(["Agent"])
    policy = get_policy_or_404(policy_id)
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Policy is in a terminal form state")
    body = json_body(required=True)
    # Clock window (priority 6)
    if not _window_open(policy):
        raise errors.window_expired("Conversion window (5 years from issue) has passed")
    # Referential compatibility (priority 7)
    target_id = body.get("target_product_template_id")
    if isinstance(target_id, str) and target_id:
        _target_compatible(target_id)
    # Field constraints (priority 8)
    require_fields(body, ["target_product_template_id", "requested_face_amount_cents"])
    face = body["requested_face_amount_cents"]
    if isinstance(face, bool) or not isinstance(face, int) or face <= 0:
        raise errors.invalid_request("requested_face_amount_cents must be a positive integer")

    insured = domain.insured_of(policy)
    conv = domain.stamp_new({
        "source_policy_id": policy["id"],
        "target_product_template_id": target_id,
        "requested_face_amount_cents": face,
        "attained_age_at_conversion": age_years(insured["date_of_birth"],
                                                store.current_date()),
        "new_policy_id": None,
        "status": "PENDING",
        "_requester_user_id": ctx.user_id,
    })
    store.conversion_requests[conv["id"]] = conv
    return ok_object(domain.serialize_conversion(conv), status=201)


@bp.route("/policies/<policy_id>/conversion-requests", methods=["GET"])
def list_policy_conversions(policy_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    return _paged([c for c in store.conversion_requests.values()
                   if c["source_policy_id"] == policy["id"]],
                  domain.serialize_conversion)


@bp.route("/policies/<policy_id>/conversion-requests/<cid>/approve", methods=["POST"])
def approve_conversion(policy_id, cid):
    ctx = require_auth(["Underwriter"])
    policy = get_policy_or_404(policy_id)
    conv = get_conversion_or_404(policy, cid)
    if conv["status"] in domain.CONVERSION_TERMINAL:
        raise errors.already_terminal("Conversion request is in a terminal state")
    if conv["status"] != "PENDING":
        raise errors.invalid_state("Conversion request must be PENDING to approve")
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Source policy is in a terminal form state")
    if policy["form_status"] != "IN_FORCE":
        raise errors.invalid_state("Source policy must be IN_FORCE to convert")
    # Segregation of duties (priority 5)
    if conv.get("_requester_user_id") == ctx.user_id:
        raise errors.segregation(
            "Approving underwriter must differ from the requesting agent")
    # Window (priority 6)
    if not _window_open(policy):
        raise errors.window_expired("Conversion window (5 years from issue) has passed")
    # Referential compatibility (priority 7)
    source_template = domain.template_of(policy)
    if source_template["product_type"] != "TERM_CONVERTIBLE":
        raise errors.incompatible_reference("Source policy product must be TERM_CONVERTIBLE")
    target = _target_compatible(conv["target_product_template_id"])
    # Field constraint (priority 8)
    if conv["requested_face_amount_cents"] > policy["face_amount_cents"]:
        raise errors.invalid_request(
            "requested_face_amount_cents must not exceed the source policy face amount")

    # Issue the new policy
    today = store.current_date()
    uw_class = policy["underwriting_class"]
    extra_bps = policy.get("_substandard_extra_pct_bps", 0)
    modal = calc.modal_premium(conv["requested_face_amount_cents"],
                               target["base_monthly_premium_rate_per_thousand_cents"],
                               uw_class, extra_bps, policy["premium_mode"])
    new_policy = domain.stamp_new({
        "application_id": policy["application_id"],
        "insured_person_id": policy["insured_person_id"],
        "product_template_id": target["id"],
        "policy_number": store.next_policy_number(),
        "issue_date": today,
        "face_amount_cents": conv["requested_face_amount_cents"],
        "premium_mode": policy["premium_mode"],
        "modal_premium_cents": modal,
        "underwriting_class": uw_class,
        "premium_payment_status": "CURRENT",
        "form_status": "IN_FORCE",
        "grace_period_end_date": None,
        "cash_value_cents": 0,
        "outstanding_loan_principal_cents": 0,
        "accrued_loan_interest_cents": 0,
        "dividend_accumulation_cents": 0,
        "dividend_option": "CASH",
        "paid_to_date": today,
        "attained_age_at_issue": conv["attained_age_at_conversion"],
        "_substandard_extra_pct_bps": extra_bps,
        "_lapsed_date": None,
    })
    store.policies[new_policy["id"]] = new_policy
    engine.create_cycle(new_policy, 1, today)

    conv["status"] = "APPROVED"
    conv["new_policy_id"] = new_policy["id"]
    domain.touch(conv)

    policy["form_status"] = "CONVERTED"
    domain.touch_policy(policy)
    for rider in engine.policy_riders(policy):
        if rider["status"] == "ACTIVE":
            rider["status"] = "TERMINATED"
            rider["_cascade"] = "conversion"
            domain.touch(rider)
    return ok_object(domain.serialize_conversion(conv))


@bp.route("/policies/<policy_id>/conversion-requests/<cid>/decline", methods=["POST"])
def decline_conversion(policy_id, cid):
    require_auth(["Underwriter"])
    policy = get_policy_or_404(policy_id)
    conv = get_conversion_or_404(policy, cid)
    if conv["status"] in domain.CONVERSION_TERMINAL:
        raise errors.already_terminal("Conversion request is in a terminal state")
    if conv["status"] != "PENDING":
        raise errors.invalid_state("Conversion request must be PENDING to decline")
    conv["status"] = "DECLINED"
    domain.touch(conv)
    return ok_object(domain.serialize_conversion(conv))


# ---------------------------------------------------------------------------
# Flat filtered listings
# ---------------------------------------------------------------------------
@bp.route("/conversion-requests", methods=["GET"])
def list_all_conversions():
    require_auth(ALL_ROLES)
    from flask import request
    records = list(store.conversion_requests.values())
    for param, field in (("source_policy_id", "source_policy_id"),
                         ("target_product_template_id", "target_product_template_id"),
                         ("new_policy_id", "new_policy_id")):
        value = request.args.get(param)
        if value is not None:
            records = [c for c in records if c.get(field) == value]
    return _paged(records, domain.serialize_conversion)


@bp.route("/conversion-requests/<row_id>", methods=["GET"])
def get_conversion_flat(row_id):
    require_auth(ALL_ROLES)
    row = store.conversion_requests.get(row_id)
    if row is None:
        raise errors.not_found(errors.ERR_CONVERSION_NOT_FOUND, "conversion request")
    return ok_object(domain.serialize_conversion(row))
