"""PIPCase endpoints (PRD §3.6)."""

from flask import Blueprint, request

import config
from clock import clock
from db import parse_iso, store
from errors import raise_err
from middleware import require_role
from response import ok, paginate
from services.audit import log_event
from services.cascades import reject_open_comp_plans_for
from services.serializers import pip_case_view

from . import _helpers as H

bp = Blueprint("pip_cases", __name__)


@bp.route("/cycles/<cycle_id>/pip-cases", methods=["GET"])
@require_role("HRBP", "Admin", "Manager")
def list_pips(cycle_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        status = request.args.get("status")
        subject_id = request.args.get("subject_employee_id")
        limit, offset = H.pagination_params()
        items = [p for p in store.pip_cases.values() if p["cycle_id"] == cycle_id]
        if status is not None:
            if status not in config.PIP_STATUSES:
                raise_err("ERR_VALIDATION", "Invalid status filter.")
            items = [p for p in items if p["status"] == status]
        if subject_id is not None:
            items = [p for p in items if p["subject_employee_id"] == subject_id]
        items.sort(key=lambda p: p["created_at"])
        sliced, page_meta = paginate(items, limit, offset)
        return ok([pip_case_view(p) for p in sliced], pagination=page_meta)


@bp.route("/cycles/<cycle_id>/pip-cases/<pip_case_id>", methods=["GET"])
@require_role("HRBP", "Admin", "Manager")
def read_pip(cycle_id, pip_case_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        p = H.get_pip_or_404(cycle_id, pip_case_id)
        return ok(pip_case_view(p))


@bp.route("/cycles/<cycle_id>/pip-cases/<pip_case_id>/pass", methods=["POST"])
@require_role("HRBP")
def pass_pip(cycle_id, pip_case_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        p = H.get_pip_or_404(cycle_id, pip_case_id)
        if p["status"] != "ACTIVE":
            raise_err("ERR_INVALID_STATE", f"PIPCase is in {p['status']}, not ACTIVE.")
        now = clock.now()
        ends_at = parse_iso(p["ends_at"])
        if now < ends_at:
            raise_err("ERR_PIP_NOT_ELAPSED",
                      "PIP duration has not elapsed yet.")
        p["status"] = "PASSED"
        H.bump(p)
        emp = store.employees.get(p["subject_employee_id"])
        if emp and emp["status"] == "ON_PIP":
            emp["status"] = "ACTIVE"
            H.bump(emp)
        log_event("PIPCase", p["id"], "pip_case.pass", payload={})
        return ok(pip_case_view(p))


@bp.route("/cycles/<cycle_id>/pip-cases/<pip_case_id>/fail", methods=["POST"])
@require_role("HRBP")
def fail_pip(cycle_id, pip_case_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        p = H.get_pip_or_404(cycle_id, pip_case_id)
        if p["status"] != "ACTIVE":
            raise_err("ERR_INVALID_STATE", f"PIPCase is in {p['status']}, not ACTIVE.")
        now = clock.now()
        ends_at = parse_iso(p["ends_at"])
        if now < ends_at:
            raise_err("ERR_PIP_NOT_ELAPSED",
                      "PIP duration has not elapsed yet.")
        p["status"] = "FAILED"
        H.bump(p)
        emp = store.employees.get(p["subject_employee_id"])
        if emp:
            emp["status"] = "TERMINATED"
            H.bump(emp)
        # Reject DRAFT/PROPOSED comp plans for this subject in the cycle
        reject_open_comp_plans_for(cycle_id, p["subject_employee_id"])
        log_event("PIPCase", p["id"], "pip_case.fail", payload={})
        return ok(pip_case_view(p))


@bp.route("/cycles/<cycle_id>/pip-cases/<pip_case_id>/withdraw", methods=["POST"])
@require_role("HRBP")
def withdraw_pip(cycle_id, pip_case_id):
    with store.lock:
        H.get_cycle_or_404(cycle_id)
        p = H.get_pip_or_404(cycle_id, pip_case_id)
        if p["status"] != "ACTIVE":
            raise_err("ERR_INVALID_STATE", f"PIPCase is in {p['status']}, not ACTIVE.")
        now = clock.now()
        ends_at = parse_iso(p["ends_at"])
        if now >= ends_at:
            raise_err("ERR_INVALID_STATE",
                      "PIP can only be withdrawn before ends_at.")
        p["status"] = "WITHDRAWN"
        H.bump(p)
        emp = store.employees.get(p["subject_employee_id"])
        if emp and emp["status"] == "ON_PIP":
            emp["status"] = "ACTIVE"
            H.bump(emp)
        log_event("PIPCase", p["id"], "pip_case.withdraw", payload={})
        return ok(pip_case_view(p))
