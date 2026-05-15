"""Onboarding routes."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from flask import Blueprint, jsonify

from auth import get_caller, require_hr_bound_to_company, require_roles
from clock import clock, format_iso, parse_iso
from errors import (
    ERR_CHECK_INVALID,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_ONBOARDING_ALREADY_EXISTS,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from request_body import check_version, get_json_body, require_field
from response import success_object
from routes.offers import rescind_offer_internal
from services.commission import clawback_record, maybe_create_for_trigger
from store import append_audit, bump, init_common_fields, lock, store


bp = Blueprint("onboardings", __name__)


_CHECK_KINDS = {"BACKGROUND", "MEDICAL"}
_CHECK_OUTCOMES = {"PENDING", "PASSED", "FAILED", "WAIVED"}
_DECISIONS = {"PASS", "FAIL"}
_FEEDBACK_SIDES = {"CANDIDATE", "EMPLOYER"}


def _serialize(o: Dict[str, Any]) -> Dict[str, Any]:
    return dict(o)


@bp.post("/recruitment/onboardings")
def create_onboarding():
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    body = get_json_body()
    offer_id = require_field(body, "offer_id")
    start_date_raw = require_field(body, "start_date")
    if not isinstance(start_date_raw, str) or not start_date_raw:
        raise_err(ERR_VALIDATION, "start_date must be an ISO8601 string.")
    try:
        start_dt = parse_iso(start_date_raw)
    except Exception:
        raise_err(ERR_VALIDATION, "Invalid start_date.")

    offer = store.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_REFERENCE_NOT_FOUND, "offer_id not found.")
    require_hr_bound_to_company(caller, offer["company_id"])
    if offer.get("offer_status") != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "Offer not ACCEPTED.")

    # Uniqueness: one onboarding per offer
    for ob in store.onboardings.values():
        if ob.get("offer_id") == offer_id:
            raise_err(ERR_ONBOARDING_ALREADY_EXISTS, "Onboarding already exists.")

    row = init_common_fields(
        {
            "offer_id": offer_id,
            "start_date": format_iso(start_dt),
            "background_check_status": "PENDING",
            "medical_check_status": "PENDING",
            "onboarding_status": "SCHEDULED",
            "probation_end_at": None,
            "candidate_feedback_score": None,
            "employer_feedback_score": None,
        }
    )
    store.onboardings[row["id"]] = row
    append_audit(
        subject_entity="Onboarding",
        subject_id=row["id"],
        event_kind="STATE_TRANSITION",
        from_state=None,
        to_state="SCHEDULED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(row), 201)
    return jsonify(body_out), status


def _company_id_for_onboarding(ob: Dict[str, Any]) -> str:
    offer = store.offers.get(ob["offer_id"])
    return offer["company_id"] if offer else None


@bp.post("/recruitment/onboardings/<oid>/start-checks")
def start_checks(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    ob = store.onboardings.get(oid)
    if ob is None:
        raise_err(ERR_NOT_FOUND, "Onboarding not found.")
    require_hr_bound_to_company(caller, _company_id_for_onboarding(ob))
    body = get_json_body()
    check_version(body, ob)
    if ob.get("onboarding_status") != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Onboarding not SCHEDULED.")
    ob["onboarding_status"] = "CHECKS_RUNNING"
    bump(ob)
    append_audit(
        subject_entity="Onboarding",
        subject_id=ob["id"],
        event_kind="STATE_TRANSITION",
        from_state="SCHEDULED",
        to_state="CHECKS_RUNNING",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = success_object(_serialize(ob))
    return jsonify(body_out), status


@bp.post("/recruitment/onboardings/<oid>/record-check")
def record_check(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    ob = store.onboardings.get(oid)
    if ob is None:
        raise_err(ERR_NOT_FOUND, "Onboarding not found.")
    require_hr_bound_to_company(caller, _company_id_for_onboarding(ob))
    body = get_json_body()
    check_version(body, ob)
    if ob.get("onboarding_status") != "CHECKS_RUNNING":
        raise_err(ERR_INVALID_STATE, "Onboarding not in CHECKS_RUNNING.")
    check_kind = require_field(body, "check_kind")
    outcome = require_field(body, "outcome")
    if check_kind not in _CHECK_KINDS:
        raise_err(ERR_CHECK_INVALID, "Unknown check_kind.")
    if outcome not in _CHECK_OUTCOMES:
        raise_err(ERR_CHECK_INVALID, "Unknown outcome.")

    if check_kind == "BACKGROUND":
        ob["background_check_status"] = outcome
    else:
        ob["medical_check_status"] = outcome

    # Maybe advance to READY
    if ob["background_check_status"] in {"PASSED", "WAIVED"} and ob["medical_check_status"] in {"PASSED", "WAIVED"}:
        ob["onboarding_status"] = "READY"
        bump(ob)
        append_audit(
            subject_entity="Onboarding",
            subject_id=ob["id"],
            event_kind="STATE_TRANSITION",
            from_state="CHECKS_RUNNING",
            to_state="READY",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
    else:
        bump(ob)
    body_out, status = success_object(_serialize(ob))
    return jsonify(body_out), status


@bp.post("/recruitment/onboardings/<oid>/confirm-onboarded")
def confirm_onboarded(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    ob = store.onboardings.get(oid)
    if ob is None:
        raise_err(ERR_NOT_FOUND, "Onboarding not found.")
    require_hr_bound_to_company(caller, _company_id_for_onboarding(ob))
    body = get_json_body()
    check_version(body, ob)
    if ob.get("onboarding_status") != "READY":
        raise_err(ERR_INVALID_STATE, "Onboarding not READY.")
    start_date = parse_iso(ob["start_date"])
    if clock.now() < start_date:
        raise_err(ERR_INVALID_STATE, "Cannot confirm before start_date.")

    ob["onboarding_status"] = "ONBOARDED"
    ob["probation_end_at"] = format_iso(start_date + timedelta(days=90))
    bump(ob)
    append_audit(
        subject_entity="Onboarding",
        subject_id=ob["id"],
        event_kind="STATE_TRANSITION",
        from_state="READY",
        to_state="ONBOARDED",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    offer = store.offers.get(ob["offer_id"])
    application = store.applications.get(offer["application_id"]) if offer else None
    if offer is not None and application is not None:
        maybe_create_for_trigger(
            application=application,
            offer=offer,
            expected_trigger="ONBOARDED",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
    body_out, status = success_object(_serialize(ob))
    return jsonify(body_out), status


@bp.post("/recruitment/onboardings/<oid>/record-no-show")
def record_no_show(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    ob = store.onboardings.get(oid)
    if ob is None:
        raise_err(ERR_NOT_FOUND, "Onboarding not found.")
    require_hr_bound_to_company(caller, _company_id_for_onboarding(ob))
    body = get_json_body()
    check_version(body, ob)
    if ob.get("onboarding_status") not in {"CHECKS_RUNNING", "READY"}:
        raise_err(ERR_INVALID_STATE, "Onboarding cannot record no-show.")
    start_date = parse_iso(ob["start_date"])
    if clock.now() < start_date:
        raise_err(ERR_INVALID_STATE, "Cannot record no-show before start_date.")

    prev = ob["onboarding_status"]
    ob["onboarding_status"] = "NO_SHOW"
    bump(ob)
    append_audit(
        subject_entity="Onboarding",
        subject_id=ob["id"],
        event_kind="STATE_TRANSITION",
        from_state=prev,
        to_state="NO_SHOW",
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    # Cascade to Offer rescission
    offer = store.offers.get(ob["offer_id"])
    if offer is not None and offer.get("offer_status") not in {"RESCINDED", "EXPIRED", "DECLINED"}:
        # Determine reason
        if prev == "CHECKS_RUNNING":
            failed_check = (
                ob.get("background_check_status") == "FAILED"
                or ob.get("medical_check_status") == "FAILED"
            )
            reason = "BACKGROUND_FAIL" if failed_check else "OTHER"
        else:
            reason = "OTHER"
        if offer.get("offer_status") in {"ISSUED", "ACCEPTED"}:
            rescind_offer_internal(offer, reason, caller.role, caller.user_id)
    body_out, status = success_object(_serialize(ob))
    return jsonify(body_out), status


@bp.post("/recruitment/onboardings/<oid>/conversion-decision")
def conversion_decision(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser"])
    ob = store.onboardings.get(oid)
    if ob is None:
        raise_err(ERR_NOT_FOUND, "Onboarding not found.")
    require_hr_bound_to_company(caller, _company_id_for_onboarding(ob))
    body = get_json_body()
    check_version(body, ob)
    decision = require_field(body, "decision")
    if decision not in _DECISIONS:
        raise_err(ERR_VALIDATION, "decision must be PASS or FAIL.")
    if ob.get("onboarding_status") != "ONBOARDED":
        raise_err(ERR_INVALID_STATE, "Onboarding not ONBOARDED.")
    pe_at = parse_iso(ob["probation_end_at"]) if ob.get("probation_end_at") else None

    if decision == "PASS":
        if pe_at is None or clock.now() < (pe_at - timedelta(days=30)):
            raise_err(ERR_INVALID_STATE, "Conversion PASS too early.")
        ob["onboarding_status"] = "PROBATION_PASSED"
        bump(ob)
        append_audit(
            subject_entity="Onboarding",
            subject_id=ob["id"],
            event_kind="STATE_TRANSITION",
            from_state="ONBOARDED",
            to_state="PROBATION_PASSED",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
        offer = store.offers.get(ob["offer_id"])
        application = store.applications.get(offer["application_id"]) if offer else None
        if offer is not None and application is not None:
            maybe_create_for_trigger(
                application=application,
                offer=offer,
                expected_trigger="PROBATION_PASSED",
                actor_role=caller.role,
                actor_user_id=caller.user_id,
            )
    else:  # FAIL
        ob["onboarding_status"] = "PROBATION_FAILED"
        bump(ob)
        append_audit(
            subject_entity="Onboarding",
            subject_id=ob["id"],
            event_kind="STATE_TRANSITION",
            from_state="ONBOARDED",
            to_state="PROBATION_FAILED",
            actor_role=caller.role,
            actor_user_id=caller.user_id,
        )
        # Clawback any ACCRUED CommissionRecord on same application within clawback window
        offer = store.offers.get(ob["offer_id"])
        application = store.applications.get(offer["application_id"]) if offer else None
        if application is not None:
            now = clock.now()
            for rec in list(store.commission_records.values()):
                if rec.get("application_id") != application["id"]:
                    continue
                if rec.get("settlement_status") != "ACCRUED":
                    continue
                contract = store.headhunter_contracts.get(rec.get("headhunter_contract_id"))
                window = int(contract.get("clawback_window_days", 90)) if contract else 90
                try:
                    rec_created = parse_iso(rec["created_at"])
                except Exception:
                    continue
                age_days = (now - rec_created).total_seconds() / 86400.0
                if age_days < window:
                    clawback_record(rec, caller.role, caller.user_id)
    body_out, status = success_object(_serialize(ob))
    return jsonify(body_out), status


@bp.post("/recruitment/onboardings/<oid>/feedback")
def submit_feedback(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser", "Candidate"])
    ob = store.onboardings.get(oid)
    if ob is None:
        raise_err(ERR_NOT_FOUND, "Onboarding not found.")
    body = get_json_body()
    side = require_field(body, "side")
    score = require_field(body, "score")
    if side not in _FEEDBACK_SIDES:
        raise_err(ERR_VALIDATION, "side invalid.")
    if not isinstance(score, int) or isinstance(score, bool) or score < 1 or score > 5:
        raise_err(ERR_VALIDATION, "score must be integer 1-5.")
    check_version(body, ob)

    offer = store.offers.get(ob["offer_id"])
    application = store.applications.get(offer["application_id"]) if offer else None
    if caller.role == "Candidate":
        if application is None or application.get("candidate_id") != caller.user_id:
            raise_err(ERR_FORBIDDEN, "Cannot submit feedback on another candidate's onboarding.")
        if side != "CANDIDATE":
            raise_err(ERR_FORBIDDEN, "Candidate may only submit CANDIDATE-side feedback.")
    else:
        require_hr_bound_to_company(caller, _company_id_for_onboarding(ob))

    if side == "CANDIDATE":
        ob["candidate_feedback_score"] = score
    else:
        ob["employer_feedback_score"] = score
    bump(ob)
    body_out, status = success_object(_serialize(ob))
    return jsonify(body_out), status


@bp.get("/recruitment/onboardings/<oid>")
def get_onboarding(oid: str):
    caller = get_caller()
    require_roles(caller, ["HrUser", "Candidate"])
    ob = store.onboardings.get(oid)
    if ob is None:
        raise_err(ERR_NOT_FOUND, "Onboarding not found.")
    offer = store.offers.get(ob["offer_id"])
    application = store.applications.get(offer["application_id"]) if offer else None
    if caller.role == "Candidate":
        if application is None or application.get("candidate_id") != caller.user_id:
            raise_err(ERR_FORBIDDEN, "Cannot view another candidate's onboarding.")
    else:
        require_hr_bound_to_company(caller, _company_id_for_onboarding(ob))
    body_out, status = success_object(_serialize(ob))
    return jsonify(body_out), status
