"""Composite setup helpers.

Each fixture builds a multi-step scenario (retailer + category + supplier +
products + planograms, etc.) so tests can focus on the trigger and the
assertion. Internally they use ``get_success_data`` so a setup failure raises
a clear "Setup failed" assertion rather than a confusing downstream error.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_payload,
    create_category_payload,
    create_funding_deal_payload,
    create_planogram_line_payload,
    create_planogram_payload,
    create_product_payload,
    create_reset_assignment_payload,
    create_reset_crew_payload,
    create_reset_project_payload,
    create_retailer_payload,
    create_store_payload,
    create_supplier_payload,
)
from .test_users import TEST_USERS, make_category_captain_headers


def _expect_ok(resp, label: str) -> Dict[str, Any]:
    """Lenient validator for setup calls — surfaces a clear message on failure."""
    try:
        return get_success_data(resp)
    except AssertionError as exc:  # pragma: no cover - defensive
        raise AssertionError(f"Setup failed at {label}: {exc}") from exc


# ---------------------------------------------------------------------------
# Tier 1 — small building blocks
# ---------------------------------------------------------------------------

def create_retailer(name: str = "R", compliance_threshold_pct: Optional[int] = None) -> Dict[str, Any]:
    payload = create_retailer_payload(name=name)
    if compliance_threshold_pct is not None:
        payload["compliance_threshold_pct"] = compliance_threshold_pct
    headers = TEST_USERS["platform_admin_headers"]
    resp = api_client.create_retailer(payload, headers)
    return _expect_ok(resp, "create_retailer")


def create_category(rid: str, **overrides) -> Dict[str, Any]:
    payload = create_category_payload(**overrides)
    headers = TEST_USERS["category_manager_headers"]
    resp = api_client.create_category(rid, payload, headers)
    return _expect_ok(resp, "create_category")


def create_supplier(rid: str, **overrides) -> Dict[str, Any]:
    payload = create_supplier_payload(**overrides)
    headers = TEST_USERS["retailer_admin_headers"]
    resp = api_client.create_supplier(rid, payload, headers)
    return _expect_ok(resp, "create_supplier")


def create_product(rid: str, category_id: str, supplier_id: str, **overrides) -> Dict[str, Any]:
    payload = create_product_payload(category_id, supplier_id, **overrides)
    headers = TEST_USERS["category_manager_headers"]
    resp = api_client.create_product(rid, payload, headers)
    return _expect_ok(resp, "create_product")


def list_product(rid: str, product_id: str) -> Dict[str, Any]:
    """Cut-in: CANDIDATE -> LISTED."""
    headers = TEST_USERS["category_manager_headers"]
    resp = api_client.list_product_cut_in(rid, product_id, headers)
    return _expect_ok(resp, "list_product")


def create_store(rid: str, **overrides) -> Dict[str, Any]:
    payload = create_store_payload(**overrides)
    headers = TEST_USERS["retailer_admin_headers"]
    resp = api_client.create_store(rid, payload, headers)
    return _expect_ok(resp, "create_store")


def create_reset_crew(rid: str, **overrides) -> Dict[str, Any]:
    payload = create_reset_crew_payload(**overrides)
    headers = TEST_USERS["reset_coordinator_headers"]
    resp = api_client.create_reset_crew(rid, payload, headers)
    return _expect_ok(resp, "create_reset_crew")


def create_planogram(rid: str, cid: str, **overrides) -> Dict[str, Any]:
    payload = create_planogram_payload(**overrides)
    headers = TEST_USERS["category_manager_headers"]
    resp = api_client.create_planogram(rid, cid, payload, headers)
    return _expect_ok(resp, "create_planogram")


def add_planogram_line(rid: str, cid: str, pgid: str, product_id: str, **overrides) -> Dict[str, Any]:
    payload = create_planogram_line_payload(product_id, **overrides)
    headers = TEST_USERS["category_manager_headers"]
    resp = api_client.create_planogram_line(rid, cid, pgid, payload, headers)
    return _expect_ok(resp, "add_planogram_line")


def submit_planogram(rid: str, cid: str, pgid: str, captain_supplier_id: str) -> Dict[str, Any]:
    headers = make_category_captain_headers(captain_supplier_id)
    resp = api_client.submit_planogram(rid, cid, pgid, headers)
    return _expect_ok(resp, "submit_planogram")


def approve_planogram(rid: str, cid: str, pgid: str) -> Dict[str, Any]:
    headers = TEST_USERS["category_manager_headers"]
    resp = api_client.approve_planogram(rid, cid, pgid, headers)
    return _expect_ok(resp, "approve_planogram")


def activate_planogram(rid: str, cid: str, pgid: str, expected_category_version: int) -> Dict[str, Any]:
    headers = TEST_USERS["category_manager_headers"]
    payload = {"expected_category_version": expected_category_version}
    resp = api_client.activate_planogram(rid, cid, pgid, payload, headers)
    return _expect_ok(resp, "activate_planogram")


def get_category_version(rid: str, cid: str) -> int:
    headers = TEST_USERS["category_manager_headers"]
    data = _expect_ok(api_client.get_category(rid, cid, headers), "get_category")
    return data["version"]


def get_product(rid: str, pid: str) -> Dict[str, Any]:
    headers = TEST_USERS["category_manager_headers"]
    return _expect_ok(api_client.get_product(rid, pid, headers), "get_product")


def get_planogram(rid: str, cid: str, pgid: str) -> Dict[str, Any]:
    headers = TEST_USERS["category_manager_headers"]
    return _expect_ok(api_client.get_planogram(rid, cid, pgid, headers), "get_planogram")


def get_reset_project(rid: str, cid: str, rpid: str) -> Dict[str, Any]:
    headers = TEST_USERS["reset_coordinator_headers"]
    return _expect_ok(api_client.get_reset_project(rid, cid, rpid, headers), "get_reset_project")


def get_reset_assignment(rid: str, cid: str, rpid: str, raid: str) -> Dict[str, Any]:
    headers = TEST_USERS["reset_coordinator_headers"]
    return _expect_ok(
        api_client.get_reset_assignment(rid, cid, rpid, raid, headers),
        "get_reset_assignment",
    )


# ---------------------------------------------------------------------------
# Tier 2 — small composed scenarios
# ---------------------------------------------------------------------------

def setup_retailer_category_supplier(
    category_overrides: Optional[Dict[str, Any]] = None,
    retailer_overrides: Optional[Dict[str, Any]] = None,
    supplier_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Retailer + Category + Supplier. Returns (retailer, category, supplier)."""
    r_over = retailer_overrides or {}
    c_over = category_overrides or {}
    s_over = supplier_overrides or {}
    retailer = create_retailer(
        name=r_over.get("name", "R"),
        compliance_threshold_pct=r_over.get("compliance_threshold_pct"),
    )
    category = create_category(retailer["id"], **c_over)
    supplier = create_supplier(retailer["id"], **s_over)
    return retailer, category, supplier


def setup_category_with_listed_product(
    product_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    retailer_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Retailer + Category + Supplier + one LISTED Product."""
    p_over = product_overrides or {}
    retailer, category, supplier = setup_retailer_category_supplier(
        category_overrides=category_overrides,
        retailer_overrides=retailer_overrides,
    )
    product = create_product(retailer["id"], category["id"], supplier["id"], **p_over)
    list_product(retailer["id"], product["id"])
    return retailer, category, supplier, product


def setup_draft_planogram_with_line(
    product_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    retailer_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """(retailer, category, supplier, product, planogram, line) with planogram in DRAFT."""
    retailer, category, supplier, product = setup_category_with_listed_product(
        product_overrides=product_overrides,
        category_overrides=category_overrides,
        retailer_overrides=retailer_overrides,
    )
    pg = create_planogram(retailer["id"], category["id"])
    line = add_planogram_line(
        retailer["id"], category["id"], pg["id"], product["id"], **(line_overrides or {})
    )
    return retailer, category, supplier, product, pg, line


def setup_planogram_in_review(
    product_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    retailer_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Planogram in IN_REVIEW state (submitted by the supplier as captain)."""
    retailer, category, supplier, product, pg, line = setup_draft_planogram_with_line(
        product_overrides=product_overrides,
        line_overrides=line_overrides,
        category_overrides=category_overrides,
        retailer_overrides=retailer_overrides,
    )
    submit_planogram(retailer["id"], category["id"], pg["id"], supplier["id"])
    return retailer, category, supplier, product, pg, line


def setup_approved_planogram(
    product_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    retailer_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Planogram in APPROVED state."""
    retailer, category, supplier, product, pg, line = setup_planogram_in_review(
        product_overrides=product_overrides,
        line_overrides=line_overrides,
        category_overrides=category_overrides,
        retailer_overrides=retailer_overrides,
    )
    approve_planogram(retailer["id"], category["id"], pg["id"])
    return retailer, category, supplier, product, pg, line


def setup_active_planogram(
    product_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    retailer_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Planogram fully ACTIVE (BASE variant)."""
    retailer, category, supplier, product, pg, line = setup_approved_planogram(
        product_overrides=product_overrides,
        line_overrides=line_overrides,
        category_overrides=category_overrides,
        retailer_overrides=retailer_overrides,
    )
    cat_v = get_category_version(retailer["id"], category["id"])
    activate_planogram(retailer["id"], category["id"], pg["id"], cat_v)
    return retailer, category, supplier, product, pg, line


def setup_submitted_audit(
    product_overrides: Optional[Dict[str, Any]] = None,
    line_overrides: Optional[Dict[str, Any]] = None,
    category_overrides: Optional[Dict[str, Any]] = None,
    retailer_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """ACTIVE planogram + Store + SUBMITTED Audit.

    Returns (retailer, category, supplier, product, planogram, store, audit).
    """
    retailer, category, supplier, product, pg, line = setup_active_planogram(
        product_overrides=product_overrides,
        line_overrides=line_overrides,
        category_overrides=category_overrides,
        retailer_overrides=retailer_overrides,
    )
    store = create_store(retailer["id"])
    auditor_headers = TEST_USERS["field_auditor_headers"]
    resp = api_client.create_audit(
        retailer["id"], store["id"], create_audit_payload(pg["id"]), auditor_headers
    )
    audit = _expect_ok(resp, "create_audit")
    return retailer, category, supplier, product, pg, store, audit
