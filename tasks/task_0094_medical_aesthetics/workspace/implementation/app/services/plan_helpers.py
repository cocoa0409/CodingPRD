"""Helpers for TreatmentPlan: contraindication evaluation, snapshotting, etc."""
from __future__ import annotations

from typing import Any

from ..errors import ApiError
from ..store import get_store


def _resolve_field(customer: dict[str, Any], dotted: str) -> Any:
    """Resolve a dotted path on a Customer."""
    parts = dotted.split(".")
    cur: Any = customer
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def _evaluate_predicate(customer: dict[str, Any], predicate: dict[str, Any]) -> bool:
    """Evaluate a contraindication predicate against a customer.

    op:
      EQ  - field equals value
      IN  - field contains value (assumed field is array)
      GT  - field > value
      LT  - field < value
    """
    field = predicate.get("field")
    op = predicate.get("op")
    value = predicate.get("value")
    actual = _resolve_field(customer, field) if field else None
    if op == "EQ":
        return actual == value
    if op == "IN":
        if isinstance(actual, list):
            return value in actual
        return False
    if op == "GT":
        try:
            return actual is not None and actual > value
        except TypeError:
            return False
    if op == "LT":
        try:
            return actual is not None and actual < value
        except TypeError:
            return False
    return False


def collect_contraindication_hits(customer: dict[str, Any], project_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Return {'ABSOLUTE': [...rules...], 'RELATIVE': [...]} for rules that match."""
    hits = {"ABSOLUTE": [], "RELATIVE": []}
    for rule in get_store().contraindication_rules.values():
        if rule["project_id"] not in project_ids:
            continue
        if _evaluate_predicate(customer, rule["predicate"]):
            hits[rule["severity"]].append(rule)
    return hits


def compute_requires_senior_countersign(plan: dict[str, Any], customer: dict[str, Any]) -> bool:
    """True if any project is HIGH risk, any RELATIVE rule matches, or risk_score >= 80."""
    items = plan.get("items") or []
    project_ids = [it["project_id"] for it in items]
    for pid in project_ids:
        proj = get_store().projects.get(pid)
        if proj and proj.get("risk_level") == "HIGH":
            return True
    if customer.get("risk_score") is not None and float(customer["risk_score"]) >= 80.0:
        return True
    hits = collect_contraindication_hits(customer, project_ids)
    if hits["RELATIVE"]:
        return True
    return False


def validate_plan_items_basic(items: Any) -> list[dict[str, Any]]:
    """Validate items array shape and the length range (1..10)."""
    if not isinstance(items, list):
        raise ApiError("ERR_INVALID_INPUT", "items must be a list")
    if len(items) < 1 or len(items) > 10:
        raise ApiError("ERR_PLAN_ITEMS_OUT_OF_RANGE", "items length must be 1..10")
    norm = []
    for it in items:
        if not isinstance(it, dict):
            raise ApiError("ERR_INVALID_INPUT", "item must be object")
        pid = it.get("project_id")
        tc = it.get("tier_code")
        q = it.get("quantity", 1)
        if not isinstance(pid, str) or pid == "":
            raise ApiError("ERR_INVALID_INPUT", "item.project_id required")
        if not isinstance(tc, str) or tc == "":
            raise ApiError("ERR_INVALID_INPUT", "item.tier_code required")
        if q is None:
            q = 1
        if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
            raise ApiError("ERR_INVALID_INPUT", "item.quantity must be positive int")
        norm.append({"project_id": pid, "tier_code": tc, "quantity": q})
    return norm


def check_item_projects_exist_and_tier(items: list[dict[str, Any]]) -> None:
    """Check projects exist and tier_codes exist within the projects."""
    for it in items:
        proj = get_store().projects.get(it["project_id"])
        if not proj:
            raise ApiError("ERR_NOT_FOUND", f"Project {it['project_id']} not found")
        tcs = {t["tier_code"] for t in proj.get("pricing_tiers") or []}
        if it["tier_code"] not in tcs:
            raise ApiError("ERR_INVALID_INPUT", f"tier_code {it['tier_code']} not in project {it['project_id']}")


def check_doctor_qualified(attending_physician_id: str | None, items: list[dict[str, Any]]) -> None:
    """All projects' qualified_doctor_ids must contain attending_physician_id."""
    if not attending_physician_id:
        return
    for it in items:
        proj = get_store().projects.get(it["project_id"])
        if not proj:
            continue
        if attending_physician_id not in (proj.get("qualified_doctor_ids") or []):
            raise ApiError("ERR_DOCTOR_NOT_QUALIFIED", f"doctor not qualified for project {it['project_id']}")
