"""Offer endpoints (PRD 3.2)."""

from datetime import timedelta

from flask import Blueprint, request

import domain as D
from db import store, new_record, bump
from errors import (
    ApiError, ERR_VALIDATION, ERR_OFFER_NOT_FOUND, ERR_CASE_NOT_FOUND,
    ERR_STALE_VERSION, ERR_ACTIVE_OFFER_EXISTS, ERR_AMENDMENT_WINDOW_CLOSED,
    ERR_OFFER_NOT_EXTENDABLE, ERR_NEGOTIATION_NOT_OPEN,
    ERR_NEGOTIATION_ROUND_LIMIT, ERR_OFFER_NOT_ACCEPTED, ERR_OFFER_EXPIRED,
    ERR_START_DATE_BEFORE_CREDENTIAL_ETA, ERR_INVALID_STATE,
)
from middleware import get_context, require_role, forbid
from response import success_object, paginate

bp = Blueprint("offers", __name__)

TERM_FIELDS = (
    "base_salary_cents", "signing_bonus_cents", "guarantee_monthly_cents",
    "guarantee_term_months", "panel_capacity", "proposed_start_date", "expires_at",
)


def _validate_term_values(base_salary, signing_bonus, monthly, term, capacity):
    for value, field in (
        (base_salary, "base_salary_cents"),
        (signing_bonus, "signing_bonus_cents"),
        (monthly, "guarantee_monthly_cents"),
    ):
        D.non_negative(value, field)
    if not (1 <= term <= 24):
        raise ApiError(ERR_VALIDATION, 400, "guarantee_term_months must be between 1 and 24")
    if capacity < 1:
        raise ApiError(ERR_VALIDATION, 400, "panel_capacity must be at least 1")


def _get_offer(oid):
    offer = store.offers.get(oid)
    if offer is None:
        raise ApiError(ERR_OFFER_NOT_FOUND, 404, "Offer not found")
    return offer


def _get_offer_case(offer):
    return store.cases.get(offer["onboarding_case_id"])


def _check_ownership(offer, user_id):
    case = _get_offer_case(offer)
    if case is None or case["physician_id"] != user_id:
        forbid("A Physician may act only on offers of their own case")


def _check_not_expired(offer):
    expires_at = D.parse_datetime(offer["expires_at"], "expires_at")
    if D.clock() >= expires_at:
        raise ApiError(ERR_OFFER_EXPIRED, 422, "The offer has expired")


def _touch_offer_and_case(offer):
    bump(offer)
    case = _get_offer_case(offer)
    if case is not None:
        bump(case)


@bp.route("/onboarding/offers", methods=["POST"])
def create_offer():
    _uid, role = get_context()
    require_role(role, ["Recruiter"])
    body = D.get_body()
    case_id = D.req_str(body, "onboarding_case_id")
    expected_version = D.req_int(body, "expected_onboarding_case_version")
    base_salary = D.req_int(body, "base_salary_cents")
    signing_bonus = D.req_int(body, "signing_bonus_cents")
    monthly = D.req_int(body, "guarantee_monthly_cents")
    term = D.req_int(body, "guarantee_term_months")
    capacity = D.req_int(body, "panel_capacity")
    proposed_start_date = D.req_str(body, "proposed_start_date")
    expires_at = D.req_str(body, "expires_at")
    D.parse_date(proposed_start_date, "proposed_start_date")
    D.parse_datetime(expires_at, "expires_at")
    _validate_term_values(base_salary, signing_bonus, monthly, term, capacity)

    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "OnboardingCase not found")
    if expected_version != case["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_onboarding_case_version does not match the case's current version")

    case_offers = D.offers_of_case(case_id)
    if any(o["status"] in D.NON_TERMINAL_OFFER_STATUSES for o in case_offers):
        raise ApiError(ERR_ACTIVE_OFFER_EXISTS, 409,
                       "A non-terminal offer already exists on the case")
    if any(o["status"] == "EXECUTED" for o in case_offers):
        guarantee = D.guarantee_of_case(case_id)
        milestones = D.milestones_of_case(case_id)
        if (guarantee is None or guarantee["status"] != "DRAFT"
                or any(m["status"] != "PENDING" for m in milestones)):
            raise ApiError(ERR_AMENDMENT_WINDOW_CLOSED, 409,
                           "Amendments are permitted only while the guarantee is DRAFT "
                           "and every milestone is PENDING")

    rec = new_record()
    rec.update({
        "onboarding_case_id": case_id,
        "base_salary_cents": base_salary,
        "signing_bonus_cents": signing_bonus,
        "guarantee_monthly_cents": monthly,
        "guarantee_term_months": term,
        "panel_capacity": capacity,
        "proposed_start_date": proposed_start_date,
        "expires_at": expires_at,
        "negotiation_round": 0,
        "status": "DRAFT",
    })
    store.offers[rec["id"]] = rec
    bump(case)
    return success_object(D.serialize_offer(rec), status=201)


@bp.route("/onboarding/offers/<oid>", methods=["GET"])
def get_offer(oid):
    get_context()
    return success_object(D.serialize_offer(_get_offer(oid)))


@bp.route("/onboarding/offers", methods=["GET"])
def list_offers():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    status = request.args.get("status")
    records = sorted(store.offers.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([D.serialize_offer(r) for r in records], request.args)


@bp.route("/onboarding/offers/<oid>/extend", methods=["POST"])
def extend_offer(oid):
    _uid, role = get_context()
    require_role(role, ["Recruiter"])
    offer = _get_offer(oid)
    if offer["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError(ERR_OFFER_NOT_EXTENDABLE, 409, "Offer is not extendable")
    body = D.get_body()
    for field in TERM_FIELDS:
        if field not in body or body[field] is None:
            continue
        if field in ("base_salary_cents", "signing_bonus_cents", "guarantee_monthly_cents",
                     "guarantee_term_months", "panel_capacity"):
            value = D.opt_int(body, field)
            if value is None:
                raise ApiError(ERR_VALIDATION, 400, "%s must be an integer" % field)
            offer[field] = value
        elif field == "proposed_start_date":
            value = D.req_str(body, field)
            D.parse_date(value, field)
            offer[field] = value
        elif field == "expires_at":
            value = D.req_str(body, field)
            D.parse_datetime(value, field)
            offer[field] = value
    _validate_term_values(
        offer["base_salary_cents"], offer["signing_bonus_cents"],
        offer["guarantee_monthly_cents"], offer["guarantee_term_months"],
        offer["panel_capacity"],
    )
    offer["status"] = "EXTENDED"
    _touch_offer_and_case(offer)
    return success_object(D.serialize_offer(offer))


@bp.route("/onboarding/offers/<oid>/counter", methods=["POST"])
def counter_offer(oid):
    uid, role = get_context()
    require_role(role, ["Physician"])
    offer = _get_offer(oid)
    _check_ownership(offer, uid)
    if offer["status"] != "EXTENDED":
        raise ApiError(ERR_NEGOTIATION_NOT_OPEN, 409, "Negotiation is not open")
    _check_not_expired(offer)
    if offer["negotiation_round"] >= D.MAX_NEGOTIATION_ROUNDS:
        raise ApiError(ERR_NEGOTIATION_ROUND_LIMIT, 422,
                       "The negotiation round limit has been reached")
    offer["status"] = "COUNTERED"
    offer["negotiation_round"] += 1
    _touch_offer_and_case(offer)
    return success_object(D.serialize_offer(offer))


@bp.route("/onboarding/offers/<oid>/accept", methods=["POST"])
def accept_offer(oid):
    uid, role = get_context()
    require_role(role, ["Physician"])
    offer = _get_offer(oid)
    _check_ownership(offer, uid)
    if offer["status"] not in ("EXTENDED", "COUNTERED"):
        raise ApiError(ERR_NEGOTIATION_NOT_OPEN, 409, "Negotiation is not open")
    _check_not_expired(offer)
    offer["status"] = "ACCEPTED"
    _touch_offer_and_case(offer)
    return success_object(D.serialize_offer(offer))


@bp.route("/onboarding/offers/<oid>/decline", methods=["POST"])
def decline_offer(oid):
    uid, role = get_context()
    require_role(role, ["Physician"])
    offer = _get_offer(oid)
    _check_ownership(offer, uid)
    if offer["status"] not in ("EXTENDED", "COUNTERED"):
        raise ApiError(ERR_NEGOTIATION_NOT_OPEN, 409, "Negotiation is not open")
    offer["status"] = "DECLINED"
    _touch_offer_and_case(offer)
    return success_object(D.serialize_offer(offer))


@bp.route("/onboarding/offers/<oid>/withdraw", methods=["POST"])
def withdraw_offer(oid):
    _uid, role = get_context()
    require_role(role, ["Recruiter"])
    offer = _get_offer(oid)
    if offer["status"] not in ("DRAFT", "EXTENDED", "COUNTERED", "ACCEPTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Offer cannot be withdrawn from its current state")
    offer["status"] = "WITHDRAWN"
    _touch_offer_and_case(offer)
    return success_object(D.serialize_offer(offer))


@bp.route("/onboarding/offers/<oid>/execute", methods=["POST"])
def execute_offer(oid):
    _uid, role = get_context()
    require_role(role, ["ContractAdministrator"])
    offer = _get_offer(oid)
    if offer["status"] != "ACCEPTED":
        raise ApiError(ERR_OFFER_NOT_ACCEPTED, 409, "Offer is not in ACCEPTED state")
    case = _get_offer_case(offer)

    proposed = D.parse_date(offer["proposed_start_date"], "proposed_start_date")
    earliest = D.clock_date() + timedelta(
        days=D.critical_path_days(case["id"]) + D.START_DATE_BUFFER_DAYS
    )
    if proposed < earliest:
        raise ApiError(ERR_START_DATE_BEFORE_CREDENTIAL_ETA, 422,
                       "proposed_start_date is earlier than the credential critical "
                       "path plus the start-date buffer")

    physician = store.physicians.get(case["physician_id"])
    prior_executed = D.executed_offer_of_case(case["id"])

    if prior_executed is not None:
        # Amendment: supersede the prior executed offer, overwrite the still-DRAFT
        # guarantee terms and the panel capacity; nothing new is provisioned.
        prior_executed["status"] = "SUPERSEDED"
        bump(prior_executed)
        guarantee = D.guarantee_of_case(case["id"])
        guarantee["monthly_guarantee_cents"] = offer["guarantee_monthly_cents"]
        guarantee["term_months"] = offer["guarantee_term_months"]
        guarantee["start_month"] = offer["proposed_start_date"][0:7]
        bump(guarantee)
        panel = D.panel_of_case(case["id"])
        if panel is not None:
            panel["capacity"] = offer["panel_capacity"]
            bump(panel)
    else:
        guarantee = new_record()
        guarantee.update({
            "onboarding_case_id": case["id"],
            "monthly_guarantee_cents": offer["guarantee_monthly_cents"],
            "term_months": offer["guarantee_term_months"],
            "start_month": offer["proposed_start_date"][0:7],
            "total_repaid_cents": 0,
            "status": "DRAFT",
        })
        store.guarantees[guarantee["id"]] = guarantee

        plan = new_record()
        required_codes = list(D.BASE_REQUIRED_MODULES)
        if physician["hire_type"] == "NEW_GRAD":
            required_codes.append("BILLING")
        plan.update({
            "onboarding_case_id": case["id"],
            "required_module_count": len(required_codes),
            "templates_required": 5 if physician["hire_type"] == "NEW_GRAD" else 3,
            "status": "PLANNED",
        })
        store.training_plans[plan["id"]] = plan
        for code in required_codes:
            module = new_record()
            module.update({
                "training_plan_id": plan["id"],
                "module_code": code,
                "required": True,
                "scheduled_on": None,
                "score": None,
                "templates_built_count": None,
                "status": "NOT_STARTED",
            })
            store.training_modules[module["id"]] = module

        panel = new_record()
        panel.update({
            "onboarding_case_id": case["id"],
            "capacity": offer["panel_capacity"],
            "current_size": 0,
            "opened_at": None,
            "status": "NOT_OPEN",
        })
        store.panels[panel["id"]] = panel

        for offset in range(1, offer["guarantee_term_months"] + 1):
            milestone = new_record()
            milestone.update({
                "onboarding_case_id": case["id"],
                "month_offset": offset,
                "target_wrvu": D.WRVU_TARGET_CURVE[min(offset, len(D.WRVU_TARGET_CURVE)) - 1],
                "actual_wrvu": None,
                "collections_cents": None,
                "attained": None,
                "status": "PENDING",
            })
            store.milestones[milestone["id"]] = milestone

    offer["status"] = "EXECUTED"
    case["actual_start_date"] = offer["proposed_start_date"]
    D.recompute_training_status(case)
    D.recompute_posture(case)
    _touch_offer_and_case(offer)
    return success_object(D.serialize_offer(offer))
