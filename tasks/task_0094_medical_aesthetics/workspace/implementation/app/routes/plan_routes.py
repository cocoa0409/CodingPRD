"""TreatmentPlan routes."""
from __future__ import annotations

from typing import Any

from flask import Flask

from ..audit import emit_sync_event, write_audit, write_payment_event
from ..auth import current_actor, require_auth
from ..calculations import compute_plan_final_total, compute_plan_provisional_total
from ..clock import now_iso_ms
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.plan_helpers import (
    check_doctor_qualified,
    check_item_projects_exist_and_tier,
    collect_contraindication_hits,
    compute_requires_senior_countersign,
    validate_plan_items_basic,
)
from ..services.validation import check_occ, customer_age_at, require_keys, require_str
from ..store import LOCK, bump_version, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok, ok


def register(app: Flask) -> None:
    # --- POST /aesthetics/plans ---
    @app.route("/aesthetics/plans", methods=["POST"])
    @require_auth("Consultant")
    def create_plan():
        body = get_json_body()
        require_keys(body, ["customer_id", "items", "expected_outcome", "risk_disclosure"])
        user_id, _ = current_actor()
        with LOCK:
            cust = get_store().customers.get(body["customer_id"])
            if not cust:
                raise ApiError("ERR_NOT_FOUND", "Customer not found")
            items = validate_plan_items_basic(body["items"])
            check_item_projects_exist_and_tier(items)
            attending_physician_id = body.get("attending_physician_id")
            if attending_physician_id is not None:
                if not isinstance(attending_physician_id, str):
                    raise ApiError("ERR_INVALID_INPUT", "attending_physician_id must be string")
                check_doctor_qualified(attending_physician_id, items)
            expected_outcome = require_str(body["expected_outcome"], "expected_outcome", allow_empty=True)
            risk_disclosure = require_str(body["risk_disclosure"], "risk_disclosure", allow_empty=True)
            plan = common_fields_create()
            plan.update({
                "customer_id": cust["id"],
                "consultant_id": user_id,
                "items": items,
                "expected_outcome": expected_outcome,
                "risk_disclosure": risk_disclosure,
                "attending_physician_id": attending_physician_id,
                "senior_physician_id": None,
                "requires_senior_countersign": False,
                "provisional_total_cents": 0,
                "final_total_cents": None,
                "status": "DRAFT",
                "plan_version": 1,
                "locked_project_versions": None,
                "informed_consent_signed_at": None,
            })
            plan["provisional_total_cents"] = compute_plan_provisional_total(items)
            plan["requires_senior_countersign"] = compute_requires_senior_countersign(plan, cust)
            get_store().treatment_plans[plan["id"]] = plan
        return created(plan)

    # --- PATCH /aesthetics/plans/{id} ---
    @app.route("/aesthetics/plans/<pid>", methods=["PATCH"])
    @require_auth("Consultant")
    def edit_plan(pid: str):
        body = get_json_body()
        user_id, _ = current_actor()
        with LOCK:
            plan = get_store().treatment_plans.get(pid)
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", f"cannot edit from {plan['status']}")
            if plan["consultant_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only the originating consultant may edit")
            check_occ(plan, body)
            if "items" in body:
                items = validate_plan_items_basic(body["items"])
                check_item_projects_exist_and_tier(items)
                plan["items"] = items
            if "expected_outcome" in body:
                plan["expected_outcome"] = require_str(body["expected_outcome"], "expected_outcome", allow_empty=True)
            if "risk_disclosure" in body:
                plan["risk_disclosure"] = require_str(body["risk_disclosure"], "risk_disclosure", allow_empty=True)
            if "attending_physician_id" in body:
                aid = body["attending_physician_id"]
                if aid is not None and not isinstance(aid, str):
                    raise ApiError("ERR_INVALID_INPUT", "attending_physician_id must be string")
                plan["attending_physician_id"] = aid
                if aid:
                    check_doctor_qualified(aid, plan["items"])
            cust = get_store().customers.get(plan["customer_id"])
            plan["provisional_total_cents"] = compute_plan_provisional_total(plan["items"])
            plan["requires_senior_countersign"] = compute_requires_senior_countersign(plan, cust)
            plan["plan_version"] = int(plan.get("plan_version", 1)) + 1
            bump_version(plan)
        return ok(plan)

    # --- POST /aesthetics/plans/{id}/submit ---
    @app.route("/aesthetics/plans/<pid>/submit", methods=["POST"])
    @require_auth("Consultant")
    def submit_plan(pid: str):
        with LOCK:
            plan = get_store().treatment_plans.get(pid)
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", f"cannot submit from {plan['status']}")
            cust = get_store().customers.get(plan["customer_id"])
            if not cust:
                raise ApiError("ERR_NOT_FOUND", "Customer not found")
            # Business-safety: customer age >= 18
            age = customer_age_at(cust["date_of_birth"])
            if age < 18:
                raise ApiError("ERR_CUSTOMER_UNDERAGE", "customer must be 18+")
            # Business-safety: ABSOLUTE contraindication
            project_ids = [it["project_id"] for it in plan["items"]]
            hits = collect_contraindication_hits(cust, project_ids)
            if hits["ABSOLUTE"]:
                raise ApiError("ERR_ABSOLUTE_CONTRAINDICATION", "absolute contraindication triggered")
            # business-referential: doctor qualified
            check_doctor_qualified(plan.get("attending_physician_id"), plan["items"])
            # business-referential: each project ON_SHELF
            for it in plan["items"]:
                proj = get_store().projects.get(it["project_id"])
                if not proj or proj["status"] != "ON_SHELF":
                    raise ApiError("ERR_PROJECT_NOT_ON_SHELF", f"project {it['project_id']} not on shelf")
            # All checks pass
            plan["status"] = "SUBMITTED"
            plan["provisional_total_cents"] = compute_plan_provisional_total(plan["items"])
            plan["requires_senior_countersign"] = compute_requires_senior_countersign(plan, cust)
            bump_version(plan)
            write_audit("PLAN_SUBMITTED", "TreatmentPlan", pid)
        return ok(plan)

    # --- POST /aesthetics/plans/{id}/sign-consent ---
    @app.route("/aesthetics/plans/<pid>/sign-consent", methods=["POST"])
    @require_auth("Customer")
    def sign_consent(pid: str):
        user_id, _ = current_actor()
        with LOCK:
            plan = get_store().treatment_plans.get(pid)
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", "consent only signable while SUBMITTED")
            if plan["customer_id"] != user_id:
                raise ApiError("ERR_FORBIDDEN", "Customer can only sign own plan")
            if plan.get("informed_consent_signed_at"):
                raise ApiError("ERR_INVALID_STATE", "consent already signed")
            plan["informed_consent_signed_at"] = now_iso_ms()
            bump_version(plan)
            write_audit("CONSENT_SIGNED", "TreatmentPlan", pid)
        return ok(plan)

    # --- POST /aesthetics/plans/{id}/approve ---
    @app.route("/aesthetics/plans/<pid>/approve", methods=["POST"])
    @require_auth("AttendingPhysician")
    def approve_plan(pid: str):
        user_id, _ = current_actor()
        with LOCK:
            plan = get_store().treatment_plans.get(pid)
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", "must be SUBMITTED")
            if plan.get("attending_physician_id") != user_id:
                raise ApiError("ERR_FORBIDDEN", "Not the assigned attending physician")
            if not plan.get("informed_consent_signed_at"):
                raise ApiError("ERR_CONSENT_NOT_SIGNED", "consent not signed")
            if plan.get("requires_senior_countersign"):
                raise ApiError("ERR_INVALID_STATE", "this plan requires senior countersign")
            plan["status"] = "APPROVED"
            plan["final_total_cents"] = compute_plan_final_total(plan)
            plan["locked_project_versions"] = {
                it["project_id"]: int(get_store().projects[it["project_id"]]["version"])
                for it in plan["items"]
            }
            bump_version(plan)
            write_audit("PLAN_APPROVED", "TreatmentPlan", pid)
            emit_sync_event("IM", "PLAN_APPROVED", {"plan_id": pid})
        return ok(plan)

    # --- POST /aesthetics/plans/{id}/countersign ---
    @app.route("/aesthetics/plans/<pid>/countersign", methods=["POST"])
    @require_auth("SeniorPhysician")
    def countersign_plan(pid: str):
        user_id, _ = current_actor()
        with LOCK:
            plan = get_store().treatment_plans.get(pid)
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", "must be SUBMITTED")
            if not plan.get("informed_consent_signed_at"):
                raise ApiError("ERR_CONSENT_NOT_SIGNED", "consent not signed")
            if not plan.get("requires_senior_countersign"):
                raise ApiError("ERR_INVALID_STATE", "this plan does not require countersign")
            if plan.get("attending_physician_id") == user_id:
                raise ApiError("ERR_SEGREGATION_VIOLATION", "Same actor cannot be attending and senior")
            plan["status"] = "APPROVED"
            plan["senior_physician_id"] = user_id
            plan["final_total_cents"] = compute_plan_final_total(plan)
            plan["locked_project_versions"] = {
                it["project_id"]: int(get_store().projects[it["project_id"]]["version"])
                for it in plan["items"]
            }
            bump_version(plan)
            write_audit("PLAN_COUNTERSIGNED", "TreatmentPlan", pid)
            emit_sync_event("IM", "PLAN_APPROVED", {"plan_id": pid})
        return ok(plan)

    # --- POST /aesthetics/plans/{id}/reject ---
    @app.route("/aesthetics/plans/<pid>/reject", methods=["POST"])
    @require_auth("AttendingPhysician")
    def reject_plan(pid: str):
        with LOCK:
            plan = get_store().treatment_plans.get(pid)
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", "must be SUBMITTED")
            plan["status"] = "REJECTED"
            bump_version(plan)
            write_audit("PLAN_REJECTED", "TreatmentPlan", pid)
        return ok(plan)

    # --- POST /aesthetics/plans/{id}/return-to-draft ---
    @app.route("/aesthetics/plans/<pid>/return-to-draft", methods=["POST"])
    @require_auth("Consultant")
    def return_to_draft(pid: str):
        user_id, _ = current_actor()
        with LOCK:
            plan = get_store().treatment_plans.get(pid)
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", "must be SUBMITTED")
            if plan.get("consultant_id") != user_id:
                raise ApiError("ERR_FORBIDDEN", "Only originating consultant may return-to-draft")
            plan["status"] = "DRAFT"
            plan["informed_consent_signed_at"] = None
            bump_version(plan)
            write_audit("PLAN_RETURNED_TO_DRAFT", "TreatmentPlan", pid)
        return ok(plan)

    # --- POST /aesthetics/plans/{id}/cancel ---
    @app.route("/aesthetics/plans/<pid>/cancel", methods=["POST"])
    @require_auth("AttendingPhysician")
    def cancel_plan(pid: str):
        with LOCK:
            plan = get_store().treatment_plans.get(pid)
            if not plan:
                raise ApiError("ERR_NOT_FOUND", "Plan not found")
            if plan["status"] != "APPROVED":
                raise ApiError("ERR_INVALID_STATE", "must be APPROVED")
            # Precondition: no appointment is IN_PROGRESS or COMPLETED
            appts = [a for a in get_store().appointments.values() if a["plan_id"] == pid]
            for a in appts:
                if a["status"] in ("IN_PROGRESS", "COMPLETED"):
                    raise ApiError("ERR_INVALID_STATE", "Cannot cancel plan with IN_PROGRESS/COMPLETED appointment")
            # Cascade: cancel appointments in SCHEDULED or CHECKED_IN
            for a in appts:
                if a["status"] in ("SCHEDULED", "CHECKED_IN"):
                    a["status"] = "CANCELLED"
                    bump_version(a)
            # Cascade: if installment ACTIVE -> REFUNDED
            inst_id = get_store().installment_by_plan.get(pid)
            if inst_id:
                inst = get_store().installment_plans.get(inst_id)
                if inst and inst["status"] == "ACTIVE":
                    inst["status"] = "REFUNDED"
                    # Mark remaining PENDING entries as CANCELLED
                    for e in inst["schedule"]:
                        if e["status"] == "PENDING":
                            e["status"] = "CANCELLED"
                    bump_version(inst)
                    write_payment_event(inst["id"], "REFUND", int(inst["paid_amount_cents"]))
                    emit_sync_event("FINANCE_PARTNER", "REFUND_INITIATED", {"installment_plan_id": inst["id"]})
            plan["status"] = "CANCELLED"
            bump_version(plan)
            write_audit("PLAN_CANCELLED", "TreatmentPlan", pid)
        return ok(plan)

    # --- GET /aesthetics/plans/{id} ---
    @app.route("/aesthetics/plans/<pid>", methods=["GET"])
    @require_auth("Consultant", "AttendingPhysician", "SeniorPhysician", "Customer", "FinanceOfficer")
    def fetch_plan(pid: str):
        plan = get_store().treatment_plans.get(pid)
        if not plan:
            raise ApiError("ERR_NOT_FOUND", "Plan not found")
        user_id, role = current_actor()
        if role == "Customer" and plan["customer_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN", "Customer can only access own plan")
        return ok(plan)

    # --- GET /aesthetics/plans ---
    @app.route("/aesthetics/plans", methods=["GET"])
    @require_auth("Consultant", "AttendingPhysician", "SeniorPhysician", "FinanceOfficer")
    def list_plans():
        limit, offset = parse_limit_offset()
        cust = parse_optional_str("customer_id")
        st = parse_optional_str("status")
        items = list(get_store().treatment_plans.values())
        if cust:
            items = [p for p in items if p["customer_id"] == cust]
        if st:
            items = [p for p in items if p["status"] == st]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
