"""ScreeningOrder endpoints, consent capture, dispatch, cancel, escalate,
individualized assessments, and the adjudication decision."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_BAN_THE_BOX, ERR_DUPLICATE_ORDER,
    ERR_CANDIDATE_NOT_ACTIVE, ERR_ORDER_NOT_OPEN, ERR_ORDER_NOT_CONSENT_CAPTURED,
    ERR_ORDER_NOT_CANCELLABLE, ERR_SLA_NOT_BREACHED, ERR_ORDER_NOT_DISPATCHED,
    ERR_DISCLOSURE, ERR_CONSENT_FUTURE, ERR_CONSENT_EXPIRED,
    ERR_RESCREEN_SAME_VENDOR, ERR_PACKAGE_NOT_ACTIVE, ERR_VENDOR_CAPACITY,
    ERR_VENDOR_NOT_ACTIVE, ERR_ADJ_NOT_REVIEWABLE, ERR_ADVERSE_NOT_RECOMMENDED,
    ERR_IA_REQUIRED,
)
from middleware import (
    auth, require_role, get_body, req_str, req_bool, req_enum, forbid, invalid,
    parse_pagination, sort_key, ALL_ROLES,
)
from response import success_object, success_list
from services import (
    active_rule_for, latest_consent, cancel_order_cascade,
    assessments_of_order,
)
from timeutil import now, parse_iso, sla_due_at, business_day_add

bp = Blueprint("orders", __name__)

GREEN_FACTORS = ("LOW", "MODERATE", "HIGH")
IA_DECISIONS = ("PROCEED_ADVERSE", "CLEAR_CANDIDATE")
ADJ_DECISIONS = ("CLEAR_CANDIDATE", "INITIATE_ADVERSE")
FCRA_BASE_WAIT_BUSINESS_DAYS = 5

ORDER_FILTERS = (
    "candidate_id", "position_id", "vendor_id", "fulfillment_status",
    "adjudication_status", "rescreen_of_order_id", "pinned_package_id",
    "pinned_matrix_id",
)


def _load_order(order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Order not found")
    return order


@bp.route("/screening-orders", methods=["POST"])
def create_order():
    auth_uid, role = auth()
    require_role(role, {"HiringManager"})
    body = get_body()
    # existence (priority 3), left-to-right: candidate_id, position_id
    raw_candidate = body.get("candidate_id")
    if raw_candidate is not None and raw_candidate not in db.candidates:
        raise ApiError(ERR_NOT_FOUND, 404, "Candidate not found")
    raw_position = body.get("position_id")
    if raw_position is not None and raw_position not in db.positions:
        raise ApiError(ERR_NOT_FOUND, 404, "Position not found")
    # shape (3.8)
    candidate_id = req_str(body, "candidate_id")
    position_id = req_str(body, "position_id")
    offer_dt = None
    if body.get("conditional_offer_extended_at") is not None:
        try:
            offer_dt = parse_iso(body["conditional_offer_extended_at"])
        except (ValueError, TypeError):
            invalid("conditional_offer_extended_at must be an ISO 8601 instant")
    candidate = db.candidates[candidate_id]
    position = db.positions[position_id]
    # business safety (5): ban-the-box gate
    rule = active_rule_for(position["jurisdiction_code"])
    if rule is not None and rule["screening_gate_stage"] == "POST_CONDITIONAL_OFFER":
        if offer_dt is None or offer_dt > now():
            raise ApiError(ERR_BAN_THE_BOX, 403,
                           "conditional_offer_extended_at required and must not "
                           "be in the future for POST_CONDITIONAL_OFFER "
                           "jurisdictions")
    # uniqueness (6): one non-terminal INITIAL order per (candidate, position)
    for other in db.orders.values():
        if (other["candidate_id"] == candidate_id
                and other["position_id"] == position_id
                and other["order_type"] == "INITIAL"
                and other["fulfillment_status"] not in ("CLOSED", "CANCELLED")):
            raise ApiError(ERR_DUPLICATE_ORDER, 409,
                           "A non-terminal INITIAL order already exists for this "
                           "candidate and position")
    # referential (8.2): candidate must be ACTIVE
    if candidate["status"] != "ACTIVE":
        raise ApiError(ERR_CANDIDATE_NOT_ACTIVE, 409,
                       "Candidate must be ACTIVE")
    order = db.new_entity({
        "candidate_id": candidate_id,
        "position_id": position_id,
        "order_type": "INITIAL",
        "rescreen_of_order_id": None,
        "vendor_id": None,
        "conditional_offer_extended_at": offer_dt,
        "fulfillment_status": "DRAFT",
        "adjudication_status": "NOT_STARTED",
        "dispatched_at": None,
        "sla_due_at": None,
        "escalation_level": 0,
        "provisional_fee_cents": None,
        "final_fee_cents": None,
        "pinned_package_id": None,
        "pinned_package_version": None,
        "pinned_matrix_id": None,
        "pinned_matrix_version": None,
        "recommended_outcome": None,
        "adverse_initiated_by_user_id": None,
    })
    db.orders[order["id"]] = order
    return success_object(order, 201)


@bp.route("/screening-orders", methods=["GET"])
def list_orders():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.orders.values())
    for field in ORDER_FILTERS:
        value = request.args.get(field)
        if value is not None:
            rows = [o for o in rows if o.get(field) == value]
    rows.sort(key=sort_key)
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)


@bp.route("/screening-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return success_object(_load_order(order_id), 200)


@bp.route("/screening-orders/<order_id>/consents", methods=["POST"])
def capture_consent(order_id):
    uid, role = auth()
    require_role(role, {"Candidate"})
    order = _load_order(order_id)
    # entity-backed ownership (2.5)
    if uid != order["candidate_id"]:
        forbid("Candidate may only capture consent on their own order")
    body = get_body()
    disclosure_form_id = req_str(body, "disclosure_form_id")
    extraneous = req_bool(body, "contains_extraneous_terms")
    raw_signed = body.get("authorization_signed_at")
    if raw_signed is None:
        invalid("authorization_signed_at is required")
    try:
        signed_at = parse_iso(raw_signed)
    except (ValueError, TypeError):
        invalid("authorization_signed_at must be an ISO 8601 instant")
    # state (4): DRAFT, or CONSENT_CAPTURED whose latest consent is EXPIRED
    allowed = order["fulfillment_status"] == "DRAFT"
    if not allowed and order["fulfillment_status"] == "CONSENT_CAPTURED":
        latest = latest_consent(order["id"])
        if latest is not None and latest["status"] == "EXPIRED":
            allowed = True
    if not allowed:
        raise ApiError(ERR_ORDER_NOT_OPEN, 409,
                       "Consent capture requires fulfillment DRAFT (or "
                       "CONSENT_CAPTURED with latest consent EXPIRED)")
    # business safety (5.1, 5.2) — evaluated after state checks
    if extraneous:
        raise ApiError(ERR_DISCLOSURE, 422,
                       "Disclosure must be a standalone document")
    if signed_at > now():
        raise ApiError(ERR_CONSENT_FUTURE, 422,
                       "authorization_signed_at must not be in the future")
    consent = db.new_entity({
        "order_id": order["id"],
        "disclosure_form_id": disclosure_form_id,
        "contains_extraneous_terms": extraneous,
        "authorization_signed_at": signed_at,
        "captured_by_user_id": uid,
        "status": "CAPTURED",
    })
    db.consents[consent["id"]] = consent
    order["fulfillment_status"] = "CONSENT_CAPTURED"
    bump(order)
    return success_object(consent, 201)


@bp.route("/screening-orders/<order_id>/consents", methods=["GET"])
def list_consents(order_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    order = _load_order(order_id)
    limit, offset = parse_pagination()
    rows = [c for c in db.consents.values() if c["order_id"] == order["id"]]
    rows.sort(key=sort_key)
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)


@bp.route("/screening-orders/<order_id>/dispatch", methods=["POST"])
def dispatch_order(order_id):
    auth_uid, role = auth()
    require_role(role, {"HiringManager"})
    order = _load_order(order_id)
    body = get_body()
    # existence (3): body vendor_id must resolve
    raw_vendor = body.get("vendor_id")
    if raw_vendor is not None and raw_vendor not in db.vendors:
        raise ApiError(ERR_NOT_FOUND, 404, "Vendor not found")
    # shape (3.8)
    vendor_id = req_str(body, "vendor_id")
    vendor = db.vendors[vendor_id]
    # state (4)
    if order["fulfillment_status"] != "CONSENT_CAPTURED":
        raise ApiError(ERR_ORDER_NOT_CONSENT_CAPTURED, 409,
                       "Dispatch requires fulfillment_status CONSENT_CAPTURED")
    # business constraint (6.6): RESCREEN must go to a different vendor
    original = None
    if order["order_type"] == "RESCREEN":
        original = db.orders.get(order["rescreen_of_order_id"])
        if original is not None and vendor_id == original["vendor_id"]:
            raise ApiError(ERR_RESCREEN_SAME_VENDOR, 422,
                           "RESCREEN orders must dispatch to a different vendor")
    # temporal (7): consent freshness (original order's consent for RESCREEN)
    consent_source = order if original is None else original
    latest = latest_consent(consent_source["id"])
    if latest is None or latest["status"] != "CAPTURED":
        raise ApiError(ERR_CONSENT_EXPIRED, 409, "Consent is not CAPTURED")
    if now() > latest["authorization_signed_at"] + timedelta(days=90):
        latest["status"] = "EXPIRED"
        bump(latest)
        raise ApiError(ERR_CONSENT_EXPIRED, 409,
                       "Consent expired: now is past authorization_signed_at "
                       "+ 90 days")
    # referential (8.4): position's package still ACTIVE at dispatch
    position = db.positions.get(order["position_id"])
    package = db.packages.get(position["package_id"]) if position else None
    if package is None or package["status"] != "ACTIVE":
        raise ApiError(ERR_PACKAGE_NOT_ACTIVE, 409,
                       "Position's package must be ACTIVE at dispatch")
    # fiscal (9): capacity before vendor-active per validation priority order
    if vendor["active_order_count"] >= vendor["max_concurrent_orders"]:
        raise ApiError(ERR_VENDOR_CAPACITY, 409,
                       "Vendor active_order_count reached max_concurrent_orders")
    # fiscal (9.1)
    if vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_NOT_ACTIVE, 409,
                       "Dispatch requires vendor ACTIVE")
    # side effects
    dispatched_at = now()
    order["vendor_id"] = vendor_id
    order["dispatched_at"] = dispatched_at
    order["sla_due_at"] = sla_due_at(dispatched_at, package["tat_business_hours"])
    order["pinned_package_id"] = package["id"]
    order["pinned_package_version"] = package["version"]
    order["provisional_fee_cents"] = (package["fee_cents"]
                                      + vendor["surcharge_cents"])
    order["fulfillment_status"] = "DISPATCHED"
    bump(order)
    vendor["active_order_count"] += 1
    bump(vendor)
    return success_object(order, 200)


@bp.route("/screening-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    auth_uid, role = auth()
    require_role(role, {"HiringManager"})
    order = _load_order(order_id)
    if order["fulfillment_status"] not in ("DRAFT", "CONSENT_CAPTURED",
                                           "DISPATCHED"):
        raise ApiError(ERR_ORDER_NOT_CANCELLABLE, 409,
                       "Cancel requires fulfillment DRAFT, CONSENT_CAPTURED or "
                       "DISPATCHED")
    cancel_order_cascade(order)
    return success_object(order, 200)


@bp.route("/screening-orders/<order_id>/escalate", methods=["POST"])
def escalate_order(order_id):
    auth_uid, role = auth()
    require_role(role, {"HiringManager", "HRAdmin"})
    order = _load_order(order_id)
    if order["fulfillment_status"] != "DISPATCHED":
        raise ApiError(ERR_ORDER_NOT_DISPATCHED, 409,
                       "Escalation requires a dispatched order")
    if now() <= order["sla_due_at"]:
        raise ApiError(ERR_SLA_NOT_BREACHED, 409,
                       "Escalation requires now > sla_due_at")
    order["escalation_level"] += 1
    bump(order)
    return success_object(order, 200)


@bp.route("/screening-orders/<order_id>/individualized-assessments",
          methods=["POST"])
def create_assessment(order_id):
    uid, role = auth()
    require_role(role, {"Adjudicator"})
    order = _load_order(order_id)
    body = get_body()
    nature = req_enum(body, "green_factor_nature_gravity", GREEN_FACTORS)
    elapsed = req_enum(body, "green_factor_time_elapsed", GREEN_FACTORS)
    relatedness = req_enum(body, "green_factor_job_relatedness", GREEN_FACTORS)
    evidence = req_bool(body, "evidence_considered")
    decision = req_enum(body, "decision", IA_DECISIONS)
    if order["adjudication_status"] != "PENDING_REVIEW":
        raise ApiError(ERR_ADJ_NOT_REVIEWABLE, 409,
                       "IA creation requires adjudication_status PENDING_REVIEW")
    assessment = db.new_entity({
        "order_id": order["id"],
        "adjudicator_user_id": uid,
        "green_factor_nature_gravity": nature,
        "green_factor_time_elapsed": elapsed,
        "green_factor_job_relatedness": relatedness,
        "evidence_considered": evidence,
        "decision": decision,
        "status": "DECIDED",
    })
    db.assessments[assessment["id"]] = assessment
    if decision == "CLEAR_CANDIDATE":
        order["adjudication_status"] = "CLEARED"
        order["fulfillment_status"] = "CLOSED"
        bump(order)
    return success_object(assessment, 201)


@bp.route("/screening-orders/<order_id>/individualized-assessments",
          methods=["GET"])
def list_assessments(order_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    order = _load_order(order_id)
    limit, offset = parse_pagination()
    rows = [a for a in db.assessments.values() if a["order_id"] == order["id"]]
    rows.sort(key=sort_key)
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)


@bp.route("/screening-orders/<order_id>/adjudication-decision",
          methods=["POST"])
def adjudication_decision(order_id):
    uid, role = auth()
    require_role(role, {"Adjudicator"})
    order = _load_order(order_id)
    body = get_body()
    decision = req_enum(body, "decision", ADJ_DECISIONS)
    if order["adjudication_status"] != "PENDING_REVIEW":
        raise ApiError(ERR_ADJ_NOT_REVIEWABLE, 409,
                       "Adjudication decision requires PENDING_REVIEW")
    if decision == "CLEAR_CANDIDATE":
        order["adjudication_status"] = "CLEARED"
        order["fulfillment_status"] = "CLOSED"
        bump(order)
        return success_object(order, 200)
    # INITIATE_ADVERSE — safety gates in pinned order
    if order["recommended_outcome"] == "CLEAR":
        raise ApiError(ERR_ADVERSE_NOT_RECOMMENDED, 409,
                       "INITIATE_ADVERSE requires recommended_outcome != CLEAR")
    position = db.positions.get(order["position_id"])
    rule = active_rule_for(position["jurisdiction_code"]) if position else None
    ia_mandatory = (order["recommended_outcome"] == "IA_REQUIRED"
                    or (rule is not None
                        and rule["individualized_assessment_required"]))
    if ia_mandatory:
        found = any(
            a["status"] == "DECIDED" and a["decision"] == "PROCEED_ADVERSE"
            for a in assessments_of_order(order["id"]))
        if not found:
            raise ApiError(ERR_IA_REQUIRED, 409,
                           "INITIATE_ADVERSE requires a DECIDED PROCEED_ADVERSE "
                           "individualized assessment")
    order["adverse_initiated_by_user_id"] = uid
    order["adjudication_status"] = "PRE_ADVERSE_PENDING"
    bump(order)
    wait_required = FCRA_BASE_WAIT_BUSINESS_DAYS
    if rule is not None:
        wait_required = max(FCRA_BASE_WAIT_BUSINESS_DAYS,
                            rule["pre_adverse_wait_business_days"])
    pre_notice = now()
    case = db.new_entity({
        "order_id": order["id"],
        "initiated_by_user_id": uid,
        "pre_notice_sent_at": pre_notice,
        "wait_business_days_required": wait_required,
        "total_hold_business_days": 0,
        "earliest_final_notice_at": business_day_add(pre_notice, wait_required),
        "hold_started_at": None,
        "final_notice_sent_at": None,
        "final_notice_issuer_user_id": None,
        "status": "WAITING_PERIOD",
    })
    db.cases[case["id"]] = case
    return success_object(order, 200)
