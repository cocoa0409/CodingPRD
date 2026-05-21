"""CompPlan endpoints (PRD §3.7).

Validation order (from PRD §2.7) for propose/approve, after auth/existence/state:
  60  ERR_PROMO_BLOCKED_BY_PIP   (promotion on ON_PIP)
  61  ERR_FACILITATOR_CONFLICT   (n/a here)
  62  ERR_APPROVER_IS_MANAGER    (segregation)
  63  ERR_PROMO_STEP_INVALID     (promotion step not +1)
  70  ERR_PINNED_REVIEW_STALE    (version pin)
  90  ERR_MERIT_BUDGET_EXCEEDED
  91  ERR_EQUITY_POOL_EXHAUSTED
"""

from flask import Blueprint, g as flask_g, request

import config
from clock import clock
from db import _format_iso, store, utcnow_iso
from errors import raise_err
from middleware import require_role
from response import ok, paginate
from services.audit import log_event
from services.calculations import equity_refresh_units, merit_increase_cents
from services.serializers import comp_plan_view

from . import _helpers as H

bp = Blueprint("comp_plans", __name__)


def _find_finalized_case_for_subject(cycle_id: str, subject_id: str):
    for rc in store.review_cases.values():
        if (rc["cycle_id"] == cycle_id
                and rc["subject_employee_id"] == subject_id
                and rc["status"] == "FINALIZED"):
            return rc
    return None


def _recompute_amounts(cp, cycle, subject, pinned_rating: str):
    cp["merit_increase_cents"] = merit_increase_cents(
        pinned_base_salary_cents=cp["pinned_base_salary_cents"],
        final_rating=pinned_rating,
        cadence=cycle["cadence"],
        promotion_to_level=cp.get("promotion_to_level"),
        employee_status=subject["status"],
        current_job_level=subject["job_level"],
    )
    cp["equity_refresh_units"] = equity_refresh_units(
        final_rating=pinned_rating,
        job_level=subject["job_level"],
        cadence=cycle["cadence"],
        promotion_to_level=cp.get("promotion_to_level"),
        employee_status=subject["status"],
    )


@bp.route("/cycles/<cycle_id>/comp-plans", methods=["POST"])
@require_role("Manager", "HRBP")
def create_comp_plan(cycle_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        body = H.get_body()
        subject_id = H.require_str(
            H.require_field(body, "subject_employee_id"), "subject_employee_id",
        )
        promotion = body.get("promotion_to_level")
        if promotion is not None:
            promotion = H.require_int(promotion, "promotion_to_level", 1, 10)

        if cycle["status"] != "COMP_PLANNING":
            raise_err("ERR_INVALID_STATE", f"Cycle is in {cycle['status']}, not COMP_PLANNING.")

        subject = store.employees.get(subject_id)
        if not subject:
            raise_err("ERR_REFERENCE_NOT_FOUND",
                      f"subject_employee_id '{subject_id}' not found.")

        # Uniqueness (cycle, subject)
        for cp in store.comp_plans.values():
            if cp["cycle_id"] == cycle_id and cp["subject_employee_id"] == subject_id:
                raise_err("ERR_INVALID_STATE",
                          "A CompPlan already exists for this (cycle, subject).")

        rc = _find_finalized_case_for_subject(cycle_id, subject_id)
        if not rc:
            raise_err("ERR_REFERENCE_NOT_FOUND",
                      "No FINALIZED ReviewCase exists for this subject in this cycle.")

        # PIP-promotion safety (priority 60) before step (63)
        if promotion is not None and subject["status"] == "ON_PIP":
            raise_err("ERR_PROMO_BLOCKED_BY_PIP",
                      "Promotion may not be set while subject is ON_PIP.")
        if promotion is not None and promotion != int(subject["job_level"]) + 1:
            raise_err("ERR_PROMO_STEP_INVALID",
                      "promotion_to_level must equal current job_level + 1.")

        cp = H.new_entity({
            "cycle_id": cycle_id,
            "subject_employee_id": subject_id,
            "pinned_review_case_id": rc["id"],
            "pinned_review_case_version": int(rc["version"]),
            "pinned_base_salary_cents": int(subject["base_salary_cents"]),
            "merit_increase_cents": 0,
            "promotion_to_level": promotion,
            "equity_refresh_units": 0,
            "status": "DRAFT",
            "approved_at": None,
        })
        _recompute_amounts(cp, cycle, subject, rc.get("final_rating"))
        store.comp_plans[cp["id"]] = cp
        log_event("CompPlan", cp["id"], "comp_plan.create", payload=body)
        return ok(comp_plan_view(cp), status=201)


@bp.route("/cycles/<cycle_id>/comp-plans", methods=["GET"])
@require_role("HRBP", "Approver", "Manager")
def list_comp_plans(cycle_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        status = request.args.get("status")
        subject_id = request.args.get("subject_employee_id")
        limit, offset = H.pagination_params()
        items = [cp for cp in store.comp_plans.values() if cp["cycle_id"] == cycle_id]
        if status is not None:
            if status not in config.COMP_PLAN_STATUSES:
                raise_err("ERR_VALIDATION", "Invalid status filter.")
            items = [cp for cp in items if cp["status"] == status]
        if subject_id is not None:
            items = [cp for cp in items if cp["subject_employee_id"] == subject_id]
        items.sort(key=lambda cp: cp["created_at"])
        sliced, page_meta = paginate(items, limit, offset)
        return ok([comp_plan_view(cp) for cp in sliced], pagination=page_meta)


@bp.route("/cycles/<cycle_id>/comp-plans/<comp_plan_id>", methods=["GET"])
@require_role("HRBP", "Approver", "Manager")
def read_comp_plan(cycle_id, comp_plan_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        cp = H.get_comp_plan_or_404(cycle_id, comp_plan_id)
        return ok(comp_plan_view(cp))


@bp.route("/cycles/<cycle_id>/comp-plans/<comp_plan_id>", methods=["PATCH"])
@require_role("Manager", "HRBP")
def patch_comp_plan(cycle_id, comp_plan_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cp = H.get_comp_plan_or_404(cycle_id, comp_plan_id)
        body = H.get_body()
        supplied_version = body.get("version")

        if cp["status"] != "DRAFT":
            raise_err("ERR_INVALID_STATE",
                      f"CompPlan is in {cp['status']}, not DRAFT.")

        subject = store.employees.get(cp["subject_employee_id"])
        rc = store.review_cases.get(cp["pinned_review_case_id"])

        new_promo = "__unset__"
        if "promotion_to_level" in body:
            v = body["promotion_to_level"]
            if v is None:
                new_promo = None
            else:
                new_promo = H.require_int(v, "promotion_to_level", 1, 10)

        # priority 60 then 63 — these run BEFORE OCC (120).
        # Evaluate against the would-be promo value.
        effective_promo = cp.get("promotion_to_level") if new_promo == "__unset__" else new_promo
        if effective_promo is not None and subject and subject["status"] == "ON_PIP":
            raise_err("ERR_PROMO_BLOCKED_BY_PIP",
                      "Promotion may not be set while subject is ON_PIP.")
        if (effective_promo is not None and subject
                and effective_promo != int(subject["job_level"]) + 1):
            raise_err("ERR_PROMO_STEP_INVALID",
                      "promotion_to_level must equal current job_level + 1.")

        H.check_version(cp, supplied_version)

        if new_promo != "__unset__":
            cp["promotion_to_level"] = new_promo
        # Recompute amounts on any PATCH (PRD says "any such edit recomputes")
        if subject and rc:
            _recompute_amounts(cp, cycle, subject, rc.get("final_rating"))
        H.bump(cp)
        log_event("CompPlan", cp["id"], "comp_plan.patch", payload=body)
        return ok(comp_plan_view(cp))


@bp.route("/cycles/<cycle_id>/comp-plans/<comp_plan_id>/propose", methods=["POST"])
@require_role("Manager", "HRBP")
def propose_comp_plan(cycle_id, comp_plan_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cp = H.get_comp_plan_or_404(cycle_id, comp_plan_id)
        if cp["status"] != "DRAFT":
            raise_err("ERR_INVALID_STATE",
                      f"CompPlan is in {cp['status']}, not DRAFT.")
        if cycle["status"] != "COMP_PLANNING":
            raise_err("ERR_INVALID_STATE",
                      f"Cycle is in {cycle['status']}, not COMP_PLANNING.")

        subject = store.employees.get(cp["subject_employee_id"])
        rc = store.review_cases.get(cp["pinned_review_case_id"])
        if not subject or not rc:
            raise_err("ERR_REFERENCE_NOT_FOUND", "Plan references unknown entity.")

        # Priority 60: PIP-promotion safety
        if cp.get("promotion_to_level") is not None and subject["status"] == "ON_PIP":
            raise_err("ERR_PROMO_BLOCKED_BY_PIP",
                      "Promotion may not be proposed while subject is ON_PIP.")
        # 63: step constraint (re-check; job_level may have moved)
        if (cp.get("promotion_to_level") is not None
                and cp["promotion_to_level"] != int(subject["job_level"]) + 1):
            raise_err("ERR_PROMO_STEP_INVALID",
                      "promotion_to_level must equal current job_level + 1.")

        # Subject status must be ACTIVE or ON_PIP
        if subject["status"] not in config.LIVE_EMPLOYEE_STATUSES:
            raise_err("ERR_INVALID_STATE",
                      "Subject is not ACTIVE or ON_PIP.")

        # Priority 70: pin equality
        if int(cp["pinned_review_case_version"]) != int(rc["version"]):
            raise_err("ERR_PINNED_REVIEW_STALE",
                      "Pinned ReviewCase version is stale.")

        # Recompute amounts
        _recompute_amounts(cp, cycle, subject, rc.get("final_rating"))
        cp["status"] = "PROPOSED"
        H.bump(cp)
        log_event("CompPlan", cp["id"], "comp_plan.propose", payload={})
        return ok(comp_plan_view(cp))


@bp.route("/cycles/<cycle_id>/comp-plans/<comp_plan_id>/approve", methods=["POST"])
@require_role("Approver")
def approve_comp_plan(cycle_id, comp_plan_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cp = H.get_comp_plan_or_404(cycle_id, comp_plan_id)
        if cp["status"] != "PROPOSED":
            raise_err("ERR_INVALID_STATE",
                      f"CompPlan is in {cp['status']}, not PROPOSED.")
        if cycle["status"] != "COMP_PLANNING":
            raise_err("ERR_INVALID_STATE",
                      f"Cycle is in {cycle['status']}, not COMP_PLANNING.")

        subject = store.employees.get(cp["subject_employee_id"])
        rc = store.review_cases.get(cp["pinned_review_case_id"])
        if not subject or not rc:
            raise_err("ERR_REFERENCE_NOT_FOUND", "Plan references unknown entity.")

        # Priority 60: PIP-promotion safety (PIP guard ABOVE budget)
        if cp.get("promotion_to_level") is not None and subject["status"] == "ON_PIP":
            raise_err("ERR_PROMO_BLOCKED_BY_PIP",
                      "Promotion may not be approved while subject is ON_PIP.")

        # Priority 62: approver-is-manager segregation
        manager_emp_id = rc.get("manager_employee_id")
        if manager_emp_id and flask_g.user_id == manager_emp_id:
            raise_err("ERR_APPROVER_IS_MANAGER",
                      "Approver may not be the case's manager.")

        # Priority 63: step constraint
        if (cp.get("promotion_to_level") is not None
                and cp["promotion_to_level"] != int(subject["job_level"]) + 1):
            raise_err("ERR_PROMO_STEP_INVALID",
                      "promotion_to_level must equal current job_level + 1.")

        # Priority 70: pin equality
        if int(cp["pinned_review_case_version"]) != int(rc["version"]):
            raise_err("ERR_PINNED_REVIEW_STALE",
                      "Pinned ReviewCase version is stale.")

        # If promotion set, subject must be ACTIVE (not ON_PIP)
        if cp.get("promotion_to_level") is not None and subject["status"] != "ACTIVE":
            raise_err("ERR_PROMO_BLOCKED_BY_PIP",
                      "Promotion approval requires subject to be ACTIVE.")

        # Recompute amounts at approval (subject status may have changed)
        _recompute_amounts(cp, cycle, subject, rc.get("final_rating"))

        # Priority 90: merit budget guard
        new_consumed = int(cycle.get("merit_budget_consumed_cents", 0)) + int(cp["merit_increase_cents"])
        if new_consumed > int(cycle["merit_budget_cents"]):
            raise_err("ERR_MERIT_BUDGET_EXCEEDED",
                      "Approving this plan would exceed merit budget.")
        # Priority 91: equity pool guard
        new_equity = int(cycle.get("equity_pool_consumed_units", 0)) + int(cp["equity_refresh_units"])
        if new_equity > int(cycle["equity_refresh_pool_units"]):
            raise_err("ERR_EQUITY_POOL_EXHAUSTED",
                      "Approving this plan would exhaust equity refresh pool.")

        cycle["merit_budget_consumed_cents"] = new_consumed
        cycle["equity_pool_consumed_units"] = new_equity
        H.bump(cycle)

        cp["status"] = "APPROVED"
        cp["approved_at"] = utcnow_iso()
        H.bump(cp)
        log_event("CompPlan", cp["id"], "comp_plan.approve", payload={})
        return ok(comp_plan_view(cp))


@bp.route("/cycles/<cycle_id>/comp-plans/<comp_plan_id>/reject", methods=["POST"])
@require_role("Approver")
def reject_comp_plan(cycle_id, comp_plan_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cp = H.get_comp_plan_or_404(cycle_id, comp_plan_id)
        if cp["status"] != "PROPOSED":
            raise_err("ERR_INVALID_STATE",
                      f"CompPlan is in {cp['status']}, not PROPOSED.")
        if cycle["status"] != "COMP_PLANNING":
            raise_err("ERR_INVALID_STATE",
                      f"Cycle is in {cycle['status']}, not COMP_PLANNING.")

        rc = store.review_cases.get(cp["pinned_review_case_id"])
        manager_emp_id = rc.get("manager_employee_id") if rc else None
        if manager_emp_id and flask_g.user_id == manager_emp_id:
            raise_err("ERR_APPROVER_IS_MANAGER",
                      "Approver may not be the case's manager.")

        cp["status"] = "REJECTED"
        H.bump(cp)
        log_event("CompPlan", cp["id"], "comp_plan.reject", payload={})
        return ok(comp_plan_view(cp))


@bp.route("/cycles/<cycle_id>/comp-plans/<comp_plan_id>/recall", methods=["POST"])
@require_role("Approver")
def recall_comp_plan(cycle_id, comp_plan_id):
    with store.lock:
        cycle = H.get_cycle_or_404(cycle_id)
        cp = H.get_comp_plan_or_404(cycle_id, comp_plan_id)
        if cp["status"] != "APPROVED":
            raise_err("ERR_INVALID_STATE",
                      f"CompPlan is in {cp['status']}, not APPROVED.")
        if cycle["status"] != "COMP_PLANNING":
            raise_err("ERR_INVALID_STATE",
                      f"Cycle is in {cycle['status']}, not COMP_PLANNING.")

        rc = store.review_cases.get(cp["pinned_review_case_id"])
        manager_emp_id = rc.get("manager_employee_id") if rc else None
        if manager_emp_id and flask_g.user_id == manager_emp_id:
            raise_err("ERR_APPROVER_IS_MANAGER",
                      "Approver may not be the case's manager.")

        # Compensating release
        cycle["merit_budget_consumed_cents"] = int(cycle.get("merit_budget_consumed_cents", 0)) - int(cp["merit_increase_cents"])
        cycle["equity_pool_consumed_units"] = int(cycle.get("equity_pool_consumed_units", 0)) - int(cp["equity_refresh_units"])
        H.bump(cycle)

        cp["status"] = "REJECTED"
        H.bump(cp)
        log_event("CompPlan", cp["id"], "comp_plan.recall", payload={})
        return ok(comp_plan_view(cp))
