"""Checkout assessments and the manual-review queue (PRD 3.4 / 3.6)."""

from flask import Blueprint, g

import calc
import services as svc
import validators as v
from db import db
from errors import ApiError
from middleware import roles
from response import created, ok, serialize
from routes._common import paged

bp = Blueprint("assessments", __name__, url_prefix="/fraud")

ASSESSMENT_READERS = (
    "CheckoutService",
    "RiskAnalyst",
    "ReviewLead",
    "PolicyEngineer",
    "PlatformAdmin",
)
CASE_READERS = ("RiskAnalyst", "ReviewLead", "PlatformAdmin")


# ===================================================== CheckoutAssessment
@bp.route("/checkout-assessments", methods=["POST"])
@roles("CheckoutService")
def create_assessment():
    payload = v.body()
    # priority 11: body foreign keys in the declared input order
    customer = v.required_fk(payload, "customer_id", db.customers, "ERR_CUSTOMER_NOT_FOUND")
    device = v.required_fk(
        payload, "device_profile_id", db.devices, "ERR_DEVICE_NOT_FOUND"
    )
    shipping = v.required_fk(
        payload, "shipping_address_id", db.addresses, "ERR_ADDRESS_NOT_FOUND"
    )
    billing = v.required_fk(
        payload, "billing_address_id", db.addresses, "ERR_ADDRESS_NOT_FOUND"
    )
    # priority 14: the foreign keys themselves are required
    if customer is None or device is None or shipping is None or billing is None:
        v.bad()

    amount_cents = v.as_int(payload, "amount_cents", minimum=1)
    card_bin = v.as_card_bin(payload, "card_bin")
    ip_country = v.as_country(payload, "ip_country")
    session_seconds = v.as_int(payload, "session_seconds", minimum=0)
    cart_item_count = v.as_int(payload, "cart_item_count", minimum=1)
    model_raw_probability = v.as_decimal(
        payload, "model_raw_probability", minimum=0, maximum=1
    )
    promo_code = v.as_str(payload, "promo_code", required=False, default=None)

    # priority 41
    if customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_ACCOUNT_LOCKED")

    # priority 64: version-pinning of both decisioning assets (PRD 2.7)
    now = db.now()
    pack = svc.active_rule_pack(now)
    if pack is None:
        raise ApiError("ERR_NO_ACTIVE_RULE_PACK")
    model = svc.active_risk_model()
    if model is None:
        raise ApiError("ERR_NO_ACTIVE_RISK_MODEL")

    row = svc.new_row(
        customer_id=customer["id"],
        device_profile_id=device["id"],
        shipping_address_id=shipping["id"],
        billing_address_id=billing["id"],
        rule_pack_id=pack["id"],
        risk_model_id=model["id"],
        applied_exception_id=None,
        amount_cents=amount_cents,
        card_bin=card_bin,
        ip_country=ip_country,
        session_seconds=session_seconds,
        cart_item_count=cart_item_count,
        promo_code=promo_code,
        model_raw_probability=model_raw_probability,
        state="PENDING_SIGNALS",
        decision=None,
        decision_reason=None,
        rule_score=None,
        model_points=None,
        blended_score=None,
        triggered_rule_codes=None,
        hard_decline_triggered=False,
        primary_signal_family=None,
        velocity_customer_assessment_count_1h=None,
        velocity_device_distinct_card_bin_count_24h=None,
        velocity_promo_address_count_30d=None,
        good_customer_at_decision=None,
        final_disposition=None,
        outcome_label="UNKNOWN",
        decided_at=None,
    )
    db.assessments[row["id"]] = row
    return created(serialize(row))


@bp.route("/checkout-assessments", methods=["GET"])
@roles(*ASSESSMENT_READERS)
def list_assessments():
    return paged(
        list(db.assessments.values()),
        [
            ("customer_id", v.query_str("customer_id")),
            ("device_profile_id", v.query_str("device_profile_id")),
            ("shipping_address_id", v.query_str("shipping_address_id")),
            ("billing_address_id", v.query_str("billing_address_id")),
            ("rule_pack_id", v.query_str("rule_pack_id")),
            ("risk_model_id", v.query_str("risk_model_id")),
            ("applied_exception_id", v.query_str("applied_exception_id")),
            ("state", v.query_enum("state", calc.ASSESSMENT_STATES)),
            ("decision", v.query_enum("decision", calc.DECISIONS)),
            ("outcome_label", v.query_enum("outcome_label", calc.OUTCOME_LABELS)),
        ],
    )


@bp.route("/checkout-assessments/<aid>", methods=["GET"])
@roles(*ASSESSMENT_READERS)
def read_assessment(aid):
    return ok(serialize(v.lookup(db.assessments, aid, "ERR_ASSESSMENT_NOT_FOUND")))


@bp.route("/checkout-assessments/<aid>/score", methods=["POST"])
@roles("CheckoutService")
def score_assessment(aid):
    assessment = v.lookup(db.assessments, aid, "ERR_ASSESSMENT_NOT_FOUND")
    customer = db.customers[assessment["customer_id"]]
    pack = db.rule_packs[assessment["rule_pack_id"]]
    model = db.risk_models[assessment["risk_model_id"]]

    # PRD 3.4: 40 -> 41 -> 42 -> 62 -> 63
    if assessment["state"] != "PENDING_SIGNALS":
        raise ApiError("ERR_ASSESSMENT_ALREADY_SCORED")
    if customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_ACCOUNT_LOCKED")
    if customer["ato_posture"] == "CONTAINED":
        raise ApiError("ERR_CUSTOMER_ATO_CONTAINED")
    if pack["status"] != "ACTIVE":
        raise ApiError("ERR_RULE_PACK_NOT_ACTIVE")
    if model["status"] != "ACTIVE":
        raise ApiError("ERR_RISK_MODEL_NOT_ACTIVE")

    svc.score_assessment(assessment)
    return ok(serialize(assessment))


# ============================================================= ReviewCase
@bp.route("/review-cases", methods=["GET"])
@roles(*CASE_READERS)
def list_review_cases():
    return paged(
        list(db.review_cases.values()),
        [
            ("assessment_id", v.query_str("assessment_id")),
            ("assigned_analyst_id", v.query_str("assigned_analyst_id")),
            ("escalated_by_analyst_id", v.query_str("escalated_by_analyst_id")),
            ("state", v.query_enum("state", calc.CASE_STATES)),
            (
                "primary_signal_family",
                v.query_enum("primary_signal_family", calc.SKILL_FAMILIES),
            ),
        ],
        order="queue",
    )


@bp.route("/review-cases/<cid>", methods=["GET"])
@roles(*CASE_READERS)
def read_review_case(cid):
    return ok(serialize(v.lookup(db.review_cases, cid, "ERR_CASE_NOT_FOUND")))


@bp.route("/review-cases/<cid>/assign", methods=["POST"])
@roles("ReviewLead")
def assign_review_case(cid):
    case = v.lookup(db.review_cases, cid, "ERR_CASE_NOT_FOUND")
    payload = v.body()
    analyst = v.required_fk(payload, "analyst_id", db.analysts, "ERR_ANALYST_NOT_FOUND")
    if analyst is None:
        v.bad()
    expected_version = v.as_int(payload, "expected_analyst_version")

    # PRD 3.6: 43 -> 52 -> 58 -> 59 -> 60 -> 61 -> 76
    if case["state"] not in ("QUEUED", "ESCALATED"):
        raise ApiError("ERR_CASE_STATE_INVALID")
    if expected_version != analyst["version"]:
        raise ApiError("ERR_STALE_ANALYST_VERSION")
    if case["state"] == "ESCALATED":
        if analyst["id"] == case.get("escalated_by_analyst_id"):
            raise ApiError("ERR_ESCALATION_SEGREGATION_VIOLATION")
        if analyst["seniority"] != "LEAD":
            raise ApiError("ERR_ESCALATED_REQUIRES_LEAD")
    if case["primary_signal_family"] not in analyst["skill_families"]:
        raise ApiError("ERR_ANALYST_SKILL_MISMATCH")
    if analyst["status"] != "AVAILABLE":
        raise ApiError("ERR_ANALYST_NOT_AVAILABLE")
    if analyst["open_case_count"] >= analyst["shift_capacity_cases"]:
        raise ApiError("ERR_ANALYST_CAPACITY_EXCEEDED")

    svc.assign_case(case, analyst)
    return ok(serialize(case))


@bp.route("/review-cases/<cid>/auto-assign", methods=["POST"])
@roles("ReviewLead")
def auto_assign_review_case(cid):
    case = v.lookup(db.review_cases, cid, "ERR_CASE_NOT_FOUND")
    # 43 then 77
    if case["state"] not in ("QUEUED", "ESCALATED"):
        raise ApiError("ERR_CASE_STATE_INVALID")
    analyst = svc.select_analyst(case)
    if analyst is None:
        raise ApiError("ERR_NO_ELIGIBLE_ANALYST")
    svc.assign_case(case, analyst)
    return ok(serialize(case))


@bp.route("/review-cases/<cid>/resolve", methods=["POST"])
@roles("RiskAnalyst", "ReviewLead")
def resolve_review_case(cid):
    case = v.lookup(db.review_cases, cid, "ERR_CASE_NOT_FOUND")
    payload = v.body()
    action = v.as_enum(payload, "action", ("APPROVE", "DECLINE", "ESCALATE"))
    note = v.as_str(payload, "resolution_note", required=False, default=None)

    # priority 43 (state before ownership), then priority 65
    if case["state"] != "ASSIGNED":
        raise ApiError("ERR_CASE_STATE_INVALID")
    owner = case.get("assigned_analyst_id")
    if g.role == "RiskAnalyst" and g.user_id != owner:
        raise ApiError("ERR_NOT_CASE_OWNER")
    if action == "ESCALATE" and g.user_id != owner:
        # escalation additionally requires the acting principal to hold the case
        raise ApiError("ERR_NOT_CASE_OWNER")

    if action == "APPROVE":
        svc.resolve_case_approve(case, note)
    elif action == "DECLINE":
        svc.resolve_case_decline(case, note)
    else:
        svc.escalate_case(case, g.user_id, note)
    return ok(serialize(case))
