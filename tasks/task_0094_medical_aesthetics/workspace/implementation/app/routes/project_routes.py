"""Project catalog endpoints."""
from __future__ import annotations

from typing import Any

from flask import Flask, request

from ..audit import write_audit
from ..auth import require_auth, current_actor
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.validation import check_occ, require_keys, require_str, require_int
from ..store import LOCK, common_fields_create, bump_version, get_store, new_id, now_iso
from ._helpers import get_json_body, ok, created, list_ok


_ALLOWED_CATEGORIES = {"SURGICAL", "NON_SURGICAL", "SKINCARE"}
_ALLOWED_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
_ALL_READ_ROLES = ("MedicalDirector", "Consultant", "AttendingPhysician", "SeniorPhysician", "Nurse", "FinanceOfficer")


def _validate_pricing_tiers(tiers: Any) -> list[dict[str, Any]]:
    if not isinstance(tiers, list) or len(tiers) < 1:
        raise ApiError("ERR_INVALID_INPUT", "pricing_tiers must be a non-empty array")
    codes = set()
    norm = []
    for t in tiers:
        if not isinstance(t, dict):
            raise ApiError("ERR_INVALID_INPUT", "pricing_tier entry must be an object")
        tc = t.get("tier_code")
        bp = t.get("base_price_cents")
        mq = t.get("min_quantity")
        if not isinstance(tc, str) or tc == "":
            raise ApiError("ERR_INVALID_INPUT", "pricing_tier.tier_code required")
        if tc in codes:
            raise ApiError("ERR_INVALID_INPUT", f"duplicate tier_code: {tc}")
        codes.add(tc)
        if not isinstance(bp, int) or isinstance(bp, bool) or bp < 0:
            raise ApiError("ERR_INVALID_INPUT", "pricing_tier.base_price_cents must be non-negative int")
        if not isinstance(mq, int) or isinstance(mq, bool) or mq < 1:
            raise ApiError("ERR_INVALID_INPUT", "pricing_tier.min_quantity must be >= 1")
        norm.append({"tier_code": tc, "base_price_cents": bp, "min_quantity": mq})
    norm.sort(key=lambda x: x["min_quantity"])
    return norm


def _validate_bom(bom: Any) -> list[dict[str, Any]]:
    if not isinstance(bom, list) or len(bom) < 1:
        raise ApiError("ERR_INVALID_INPUT", "bom must be a non-empty array")
    out = []
    for b in bom:
        if not isinstance(b, dict):
            raise ApiError("ERR_INVALID_INPUT", "bom entry must be object")
        sku_id = b.get("sku_id")
        q = b.get("quantity")
        if not isinstance(sku_id, str) or sku_id == "":
            raise ApiError("ERR_INVALID_INPUT", "bom.sku_id required")
        if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
            raise ApiError("ERR_INVALID_INPUT", "bom.quantity must be > 0")
        # Existence check for sku
        if sku_id not in get_store().consumable_skus:
            raise ApiError("ERR_NOT_FOUND", f"ConsumableSku {sku_id} not found")
        out.append({"sku_id": sku_id, "quantity": q})
    return out


def _validate_qualified_doctor_ids(arr: Any) -> list[str]:
    if not isinstance(arr, list) or len(arr) < 1:
        raise ApiError("ERR_INVALID_INPUT", "qualified_doctor_ids must be a non-empty array")
    out = []
    for d in arr:
        if not isinstance(d, str) or d == "":
            raise ApiError("ERR_INVALID_INPUT", "qualified_doctor_ids entries must be strings")
        out.append(d)
    return out


def register(app: Flask) -> None:
    # --- POST /aesthetics/projects ---
    @app.route("/aesthetics/projects", methods=["POST"])
    @require_auth("MedicalDirector", "Consultant")
    def create_project():
        body = get_json_body()
        require_keys(body, ["code", "name", "category", "technique", "duration_minutes", "recovery_days", "risk_level", "bom", "qualified_doctor_ids", "pricing_tiers"])
        code = require_str(body["code"], "code")
        if not (3 <= len(code) <= 32):
            raise ApiError("ERR_INVALID_INPUT", "code length must be 3..32")
        # Unique code
        for p in get_store().projects.values():
            if p.get("code") == code:
                raise ApiError("ERR_INVALID_INPUT", f"code already exists: {code}")
        name = require_str(body["name"], "name")
        category = body["category"]
        if category not in _ALLOWED_CATEGORIES:
            raise ApiError("ERR_INVALID_INPUT", f"invalid category: {category}")
        technique = require_str(body["technique"], "technique", allow_empty=True)
        dm = require_int(body["duration_minutes"], "duration_minutes")
        if not (5 <= dm <= 480):
            raise ApiError("ERR_INVALID_INPUT", "duration_minutes must be 5..480")
        rd = require_int(body["recovery_days"], "recovery_days")
        if not (0 <= rd <= 365):
            raise ApiError("ERR_INVALID_INPUT", "recovery_days must be 0..365")
        risk_level = body["risk_level"]
        if risk_level not in _ALLOWED_RISK_LEVELS:
            raise ApiError("ERR_INVALID_INPUT", f"invalid risk_level: {risk_level}")
        bom = _validate_bom(body["bom"])
        qdocs = _validate_qualified_doctor_ids(body["qualified_doctor_ids"])
        tiers = _validate_pricing_tiers(body["pricing_tiers"])

        with LOCK:
            proj = common_fields_create()
            proj.update({
                "code": code,
                "name": name,
                "category": category,
                "technique": technique,
                "duration_minutes": dm,
                "recovery_days": rd,
                "risk_level": risk_level,
                "bom": bom,
                "qualified_doctor_ids": qdocs,
                "pricing_tiers": tiers,
                "status": "DRAFT",
                "reviewer_id": None,
            })
            get_store().projects[proj["id"]] = proj
        return created(proj)

    # --- PATCH /aesthetics/projects/{id} ---
    @app.route("/aesthetics/projects/<pid>", methods=["PATCH"])
    @require_auth("MedicalDirector", "Consultant")
    def edit_project(pid: str):
        body = get_json_body()
        with LOCK:
            proj = get_store().projects.get(pid)
            if not proj:
                raise ApiError("ERR_NOT_FOUND", "Project not found")
            if proj["status"] not in ("DRAFT", "UNDER_REVIEW"):
                raise ApiError("ERR_INVALID_STATE", f"Cannot edit project in status {proj['status']}")
            check_occ(proj, body)
            if "name" in body:
                proj["name"] = require_str(body["name"], "name")
            if "technique" in body:
                proj["technique"] = require_str(body["technique"], "technique", allow_empty=True)
            if "duration_minutes" in body:
                dm = require_int(body["duration_minutes"], "duration_minutes")
                if not (5 <= dm <= 480):
                    raise ApiError("ERR_INVALID_INPUT", "duration_minutes must be 5..480")
                proj["duration_minutes"] = dm
            if "recovery_days" in body:
                rd = require_int(body["recovery_days"], "recovery_days")
                if not (0 <= rd <= 365):
                    raise ApiError("ERR_INVALID_INPUT", "recovery_days must be 0..365")
                proj["recovery_days"] = rd
            if "risk_level" in body:
                if body["risk_level"] not in _ALLOWED_RISK_LEVELS:
                    raise ApiError("ERR_INVALID_INPUT", "invalid risk_level")
                proj["risk_level"] = body["risk_level"]
            if "bom" in body:
                proj["bom"] = _validate_bom(body["bom"])
            if "qualified_doctor_ids" in body:
                proj["qualified_doctor_ids"] = _validate_qualified_doctor_ids(body["qualified_doctor_ids"])
            if "pricing_tiers" in body:
                proj["pricing_tiers"] = _validate_pricing_tiers(body["pricing_tiers"])
            bump_version(proj)
        return ok(proj)

    # --- POST /aesthetics/projects/{id}/submit ---
    @app.route("/aesthetics/projects/<pid>/submit", methods=["POST"])
    @require_auth("MedicalDirector", "Consultant")
    def submit_project(pid: str):
        with LOCK:
            proj = get_store().projects.get(pid)
            if not proj:
                raise ApiError("ERR_NOT_FOUND", "Project not found")
            if proj["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", f"cannot submit from {proj['status']}")
            # Preconditions: bom, qualified_doctor_ids, pricing_tiers non-empty
            if not proj.get("bom") or not proj.get("qualified_doctor_ids") or not proj.get("pricing_tiers"):
                raise ApiError("ERR_INVALID_INPUT", "bom/qualified_doctor_ids/pricing_tiers must be non-empty")
            proj["status"] = "UNDER_REVIEW"
            bump_version(proj)
            write_audit("PROJECT_SUBMITTED", "Project", pid)
        return ok(proj)

    # --- POST /aesthetics/projects/{id}/approve ---
    @app.route("/aesthetics/projects/<pid>/approve", methods=["POST"])
    @require_auth("MedicalDirector")
    def approve_project(pid: str):
        user_id, _ = current_actor()
        with LOCK:
            proj = get_store().projects.get(pid)
            if not proj:
                raise ApiError("ERR_NOT_FOUND", "Project not found")
            if proj["status"] != "UNDER_REVIEW":
                raise ApiError("ERR_INVALID_STATE", f"cannot approve from {proj['status']}")
            proj["status"] = "ON_SHELF"
            proj["reviewer_id"] = user_id
            bump_version(proj)
            write_audit("PROJECT_APPROVED", "Project", pid)
        return ok(proj)

    # --- POST /aesthetics/projects/{id}/reject ---
    @app.route("/aesthetics/projects/<pid>/reject", methods=["POST"])
    @require_auth("MedicalDirector")
    def reject_project(pid: str):
        with LOCK:
            proj = get_store().projects.get(pid)
            if not proj:
                raise ApiError("ERR_NOT_FOUND", "Project not found")
            if proj["status"] != "UNDER_REVIEW":
                raise ApiError("ERR_INVALID_STATE", f"cannot reject from {proj['status']}")
            proj["status"] = "DRAFT"
            bump_version(proj)
            write_audit("PROJECT_REJECTED", "Project", pid)
        return ok(proj)

    # --- POST /aesthetics/projects/{id}/take-off-shelf ---
    @app.route("/aesthetics/projects/<pid>/take-off-shelf", methods=["POST"])
    @require_auth("MedicalDirector")
    def take_off_shelf(pid: str):
        with LOCK:
            proj = get_store().projects.get(pid)
            if not proj:
                raise ApiError("ERR_NOT_FOUND", "Project not found")
            if proj["status"] != "ON_SHELF":
                raise ApiError("ERR_INVALID_STATE", f"cannot take off-shelf from {proj['status']}")
            # No non-terminal (DRAFT/SUBMITTED) plan references this project
            for plan in get_store().treatment_plans.values():
                if plan["status"] in ("DRAFT", "SUBMITTED"):
                    for item in plan.get("items") or []:
                        if item.get("project_id") == pid:
                            raise ApiError("ERR_PROJECT_IN_USE", "Non-terminal plan references this project")
            proj["status"] = "OFF_SHELF"
            bump_version(proj)
            write_audit("PROJECT_OFF_SHELF", "Project", pid)
        return ok(proj)

    # --- POST /aesthetics/projects/{id}/return-to-shelf ---
    @app.route("/aesthetics/projects/<pid>/return-to-shelf", methods=["POST"])
    @require_auth("MedicalDirector")
    def return_to_shelf(pid: str):
        with LOCK:
            proj = get_store().projects.get(pid)
            if not proj:
                raise ApiError("ERR_NOT_FOUND", "Project not found")
            if proj["status"] != "OFF_SHELF":
                raise ApiError("ERR_INVALID_STATE", f"cannot return to shelf from {proj['status']}")
            proj["status"] = "ON_SHELF"
            bump_version(proj)
            write_audit("PROJECT_RETURNED", "Project", pid)
        return ok(proj)

    # --- GET /aesthetics/projects/{id} ---
    @app.route("/aesthetics/projects/<pid>", methods=["GET"])
    @require_auth(*_ALL_READ_ROLES)
    def fetch_project(pid: str):
        proj = get_store().projects.get(pid)
        if not proj:
            raise ApiError("ERR_NOT_FOUND", "Project not found")
        return ok(proj)

    # --- GET /aesthetics/projects ---
    @app.route("/aesthetics/projects", methods=["GET"])
    @require_auth(*_ALL_READ_ROLES)
    def list_projects():
        limit, offset = parse_limit_offset()
        cat = parse_optional_str("category")
        st = parse_optional_str("status")
        rl = parse_optional_str("risk_level")
        items = list(get_store().projects.values())
        if cat:
            items = [p for p in items if p["category"] == cat]
        if st:
            items = [p for p in items if p["status"] == st]
        if rl:
            items = [p for p in items if p["risk_level"] == rl]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
