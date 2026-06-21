"""TitleSearch + TitleInsurancePolicy services."""
from __future__ import annotations

from typing import Any

from calculations import title_insurance_premium_cents
from clock import CLOCK
from db import DB_INSTANCE, new_id
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_TITLE_SEARCH_VERSION,
    ERR_TITLE_NOT_INSURABLE,
    err,
)
from lookup import (
    get_fk_agreement,
    get_fk_title_search,
    get_title_search_or_404,
)
from validation import require_fields, require_int, require_str


def create_title_search(body: dict) -> dict:
    require_fields(body, ["agreement_id"])
    agreement_id = require_str(body, "agreement_id")
    a = get_fk_agreement(agreement_id)
    if a["status"] not in ("ACTIVE", "UNDER_CONTRACT"):
        raise err(ERR_INVALID_STATE, "title search may only be ordered on ACTIVE or UNDER_CONTRACT")
    now = CLOCK.now()
    t = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "agreement_id": agreement_id,
        "defects": [],
        "status": "ORDERED",
        "has_material_defect": False,
    }
    DB_INSTANCE.title_searches[t["id"]] = t
    return t


def _validate_defect(defect: Any) -> dict:
    if not isinstance(defect, dict):
        raise err(ERR_INVALID_REQUEST, "each defect must be an object")
    for key in ("kind", "severity", "description"):
        if key not in defect:
            raise err(ERR_INVALID_REQUEST, f"defect missing {key}")
    if not isinstance(defect["kind"], str) or defect["kind"] == "":
        raise err(ERR_INVALID_REQUEST, "defect.kind must be non-empty string")
    if defect["severity"] not in ("MINOR", "MATERIAL"):
        raise err(ERR_INVALID_REQUEST, "defect.severity must be MINOR or MATERIAL")
    if not isinstance(defect["description"], str):
        raise err(ERR_INVALID_REQUEST, "defect.description must be a string")
    return {"kind": defect["kind"], "severity": defect["severity"], "description": defect["description"]}


def complete_title_search(ts_id: str, body: dict) -> dict:
    t = get_title_search_or_404(ts_id)
    if t["status"] != "ORDERED":
        raise err(ERR_INVALID_STATE, "title search is not in ORDERED")

    a = DB_INSTANCE.purchase_agreements.get(t["agreement_id"])
    if a is None or a["status"] not in ("ACTIVE", "UNDER_CONTRACT"):
        raise err(ERR_INVALID_STATE, "agreement must be ACTIVE or UNDER_CONTRACT")

    defects_raw = body.get("defects")
    if defects_raw is None:
        defects_raw = []
    if not isinstance(defects_raw, list):
        raise err(ERR_INVALID_REQUEST, "defects must be an array")
    defects = [_validate_defect(d) for d in defects_raw]

    t["defects"] = defects
    t["status"] = "COMPLETED"
    t["has_material_defect"] = any(d["severity"] == "MATERIAL" for d in defects)
    t["updated_at"] = CLOCK.now()
    t["version"] += 1
    return t


def resolve_title_search(ts_id: str, body: dict) -> dict:
    t = get_title_search_or_404(ts_id)
    if t["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "title search is not in COMPLETED")

    if t["has_material_defect"]:
        notes = body.get("resolution_notes")
        if not isinstance(notes, str) or notes == "":
            raise err(ERR_INVALID_REQUEST, "resolution_notes is required when has_material_defect=true")

    # Rewrite MATERIAL -> MINOR (downgrade).
    if t["has_material_defect"]:
        for d in t["defects"]:
            if d["severity"] == "MATERIAL":
                d["severity"] = "MINOR"
        t["has_material_defect"] = any(d["severity"] == "MATERIAL" for d in t["defects"])

    t["status"] = "RESOLVED"
    t["updated_at"] = CLOCK.now()
    t["version"] += 1
    return t


def list_title_searches(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.title_searches.values())
    if filters.get("agreement_id"):
        items = [t for t in items if t["agreement_id"] == filters["agreement_id"]]
    if filters.get("status"):
        items = [t for t in items if t["status"] == filters["status"]]
    items.sort(key=lambda t: t["created_at"])
    return items


# ---------------------------------------------------------------------------
# TitleInsurancePolicy
# ---------------------------------------------------------------------------


def issue_title_policy(body: dict) -> dict:
    require_fields(body, ["title_search_id", "expected_title_search_version"])
    ts_id = require_str(body, "title_search_id")
    expected_version = require_int(body, "expected_title_search_version")

    # FK check.
    t = get_fk_title_search(ts_id)

    # OCC (priority 6).
    if expected_version != t["version"]:
        raise err(ERR_STALE_TITLE_SEARCH_VERSION, "expected_title_search_version mismatch")

    # Priority 13: TitleSearch must be RESOLVED with has_material_defect=false.
    if t["status"] != "RESOLVED" or t["has_material_defect"] is True:
        raise err(ERR_TITLE_NOT_INSURABLE, "TitleSearch is not RESOLVED with has_material_defect=false")

    a = DB_INSTANCE.purchase_agreements.get(t["agreement_id"])
    if a is None:
        raise err(ERR_INVALID_STATE, "agreement missing for title search")

    # Determine lender_concurrent variant.
    lender_concurrent = any(
        w["agreement_id"] == a["id"] and w["party"] == "LENDER" and w["status"] != "REJECTED"
        for w in DB_INSTANCE.wire_instructions.values()
    )
    premium = title_insurance_premium_cents(a["purchase_price_cents"], lender_concurrent)
    coverage = a["purchase_price_cents"]

    now = CLOCK.now()
    policy = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "title_search_id": ts_id,
        "coverage_amount_cents": coverage,
        "premium_cents": premium,
        "status": "ISSUED",
    }
    DB_INSTANCE.title_insurance_policies[policy["id"]] = policy

    # OCC-pinned write bumps parent's version.
    t["version"] += 1
    t["updated_at"] = CLOCK.now()
    return policy


def list_title_policies(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.title_insurance_policies.values())
    if filters.get("title_search_id"):
        items = [p for p in items if p["title_search_id"] == filters["title_search_id"]]
    if filters.get("status"):
        items = [p for p in items if p["status"] == filters["status"]]
    items.sort(key=lambda p: p["created_at"])
    return items
