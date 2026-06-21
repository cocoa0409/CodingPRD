"""Composite setup helpers for multi-step test prerequisites (PRD §3).

The harness restarts the API process before every individual test, so the
database is empty at the start of each test — every fixture rebuilds its
preconditions from scratch using only PRD-declared endpoints.

Uses ``get_success_data()`` (lenient validator) internally so setup failures
surface as clear "Setup failed" errors rather than confusing assertion
failures inside the test body.

Client identity threading (PRD §2.1): a fixture that drives an estimate
accept/decline acts as the work order's owning Client via
``make_client_headers(client_user_id)`` — using the same `client_user_id`
that was stamped on the work order at create time — so the ownership check
passes. Every work order created here is owned by ``DEFAULT_CLIENT_USER_ID``
unless overridden.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_service_area_payload,
    create_crew_payload,
    create_equipment_payload,
    create_work_order_payload,
    create_tree_payload,
    create_line_item_payload,
    create_permit_payload,
    decide_permit_payload,
    create_booking_payload,
    finalize_booking_payload,
    create_disposal_ticket_payload,
)
from .test_users import TEST_USERS, make_client_headers, DEFAULT_CLIENT_USER_ID


# ─── Provisioning primitives (PRD §3.1) ─────────────────


def create_service_area(**overrides) -> dict:
    """Create a service area (Dispatcher). Pass requires_permit_authority,
    heritage_surcharge_pct, disposal_fee_cents_per_ton as overrides."""
    return get_success_data(api_client.create_service_area(
        create_service_area_payload(**overrides),
        TEST_USERS["dispatcher_headers"],
    ))


def create_crew(service_area_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_crew(
        create_crew_payload(service_area_id, **overrides),
        TEST_USERS["dispatcher_headers"],
    ))


def create_equipment(service_area_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_equipment(
        create_equipment_payload(service_area_id, **overrides),
        TEST_USERS["dispatcher_headers"],
    ))


def create_work_order(service_area_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(service_area_id, **overrides),
        TEST_USERS["dispatcher_headers"],
    ))


def add_tree(work_order_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_tree(
        work_order_id, create_tree_payload(**overrides),
        TEST_USERS["arborist_headers"],
    ))


def assess(work_order_id: str) -> dict:
    return get_success_data(api_client.assess_work_order(
        work_order_id, TEST_USERS["arborist_headers"],
    ))


def create_estimate(work_order_id: str) -> dict:
    return get_success_data(api_client.create_estimate(
        work_order_id, TEST_USERS["arborist_headers"],
    ))


def add_line_item(estimate_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_line_item(
        create_line_item_payload(estimate_id, **overrides),
        TEST_USERS["arborist_headers"],
    ))


def issue_estimate(work_order_id: str, estimate_id: str) -> dict:
    return get_success_data(api_client.issue_estimate(
        work_order_id, estimate_id, TEST_USERS["arborist_headers"],
    ))


def accept_estimate(work_order_id: str, estimate_id: str,
                    client_user_id: str = DEFAULT_CLIENT_USER_ID) -> dict:
    return get_success_data(api_client.accept_estimate(
        work_order_id, estimate_id, make_client_headers(client_user_id),
    ))


def current_version(work_order_id: str) -> int:
    """Read the work order's current version (any GET-authorized role)."""
    wo = get_success_data(api_client.get_work_order(
        work_order_id, TEST_USERS["dispatcher_headers"],
    ))
    return wo["version"]


def create_booking(work_order_id: str, resource_kind: str, **overrides) -> dict:
    """Create a booking, defaulting expected_work_order_version to the live
    work order version unless supplied in overrides."""
    if "expected_work_order_version" not in overrides:
        overrides["expected_work_order_version"] = current_version(work_order_id)
    return get_success_data(api_client.create_booking(
        create_booking_payload(work_order_id, resource_kind, **overrides),
        TEST_USERS["dispatcher_headers"],
    ))


def finalize_booking(booking_id: str, actual_hours: float) -> dict:
    return get_success_data(api_client.finalize_booking(
        booking_id, finalize_booking_payload(actual_hours),
        TEST_USERS["dispatcher_headers"],
    ))


def record_disposal_ticket(work_order_id: str, debris_tons: float = 3.5) -> dict:
    return get_success_data(api_client.create_disposal_ticket(
        work_order_id, create_disposal_ticket_payload(debris_tons),
        TEST_USERS["finance_clerk_headers"],
    ))


def finalize_disposal_ticket(work_order_id: str, ticket_id: str) -> dict:
    return get_success_data(api_client.finalize_disposal_ticket(
        work_order_id, ticket_id, TEST_USERS["finance_clerk_headers"],
    ))


def create_permit(work_order_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_permit(
        work_order_id, create_permit_payload(**overrides),
        TEST_USERS["arborist_headers"],
    ))


def submit_permit(work_order_id: str, permit_id: str) -> dict:
    return get_success_data(api_client.submit_permit(
        work_order_id, permit_id, TEST_USERS["arborist_headers"],
    ))


def decide_permit(work_order_id: str, permit_id: str, decision: str) -> dict:
    return get_success_data(api_client.decide_permit(
        work_order_id, permit_id, decide_permit_payload(decision),
        TEST_USERS["dispatcher_headers"],
    ))


# ─── Tier 1/2: composite work-order state progression ───


def setup_assessed_work_order(
    pricing_mode: str = "PER_JOB",
    tree_overrides: Optional[dict] = None,
    area_overrides: Optional[dict] = None,
    wo_overrides: Optional[dict] = None,
):
    """Area + DRAFT work order + one tree + assess -> ASSESSED.

    Returns (area, work_order, tree). Use tree_overrides to control dbh /
    flags so the tree's hazard tier and the work order's requires_permit are
    what the test needs.
    """
    area = create_service_area(**(area_overrides or {}))
    wo = create_work_order(area["id"], pricing_mode=pricing_mode, **(wo_overrides or {}))
    tree = add_tree(wo["id"], **(tree_overrides or {}))
    assess(wo["id"])
    wo = get_success_data(api_client.get_work_order(
        wo["id"], TEST_USERS["dispatcher_headers"],
    ))
    return area, wo, tree


def setup_estimate_with_lines(
    pricing_mode: str = "PER_JOB",
    line_items: Optional[list] = None,
    tree_overrides: Optional[dict] = None,
    area_overrides: Optional[dict] = None,
    wo_overrides: Optional[dict] = None,
):
    """ASSESSED work order + a DRAFT estimate populated with line_items.

    Each entry in ``line_items`` is a dict of create_line_item overrides
    (service_type / quantity / tree_asset_id). When an entry needs the tree
    that was created here, pass ``{"use_tree": True, ...}`` and this helper
    substitutes the tree's id for ``tree_asset_id``.

    Returns (area, work_order, tree, estimate).
    """
    area, wo, tree = setup_assessed_work_order(
        pricing_mode=pricing_mode,
        tree_overrides=tree_overrides,
        area_overrides=area_overrides,
        wo_overrides=wo_overrides,
    )
    est = create_estimate(wo["id"])
    for spec in (line_items or [{"service_type": "REMOVAL", "quantity": 1, "use_tree": True}]):
        spec = dict(spec)
        if spec.pop("use_tree", False):
            spec["tree_asset_id"] = tree["id"]
        add_line_item(est["id"], **spec)
    return area, wo, tree, est


def setup_quoted_work_order(
    pricing_mode: str = "PER_JOB",
    line_items: Optional[list] = None,
    tree_overrides: Optional[dict] = None,
    area_overrides: Optional[dict] = None,
    wo_overrides: Optional[dict] = None,
):
    """ASSESSED -> estimate issued -> work order QUOTED.

    Returns (area, work_order, tree, estimate) with the estimate ISSUED.
    """
    area, wo, tree, est = setup_estimate_with_lines(
        pricing_mode=pricing_mode,
        line_items=line_items,
        tree_overrides=tree_overrides,
        area_overrides=area_overrides,
        wo_overrides=wo_overrides,
    )
    est = issue_estimate(wo["id"], est["id"])
    return area, wo, tree, est


def setup_scheduled_work_order(
    pricing_mode: str = "HOURLY",
    line_items: Optional[list] = None,
    tree_overrides: Optional[dict] = None,
    area_overrides: Optional[dict] = None,
    wo_overrides: Optional[dict] = None,
    client_user_id: str = DEFAULT_CLIENT_USER_ID,
):
    """Full chain to SCHEDULED: area + WO + tree + assess + estimate +
    line item + issue + accept (no permit required by default — the tree is
    non-protected).

    Returns (area, work_order, tree, estimate) with the work order SCHEDULED.
    """
    area, wo, tree, est = setup_quoted_work_order(
        pricing_mode=pricing_mode,
        line_items=line_items,
        tree_overrides=tree_overrides,
        area_overrides=area_overrides,
        wo_overrides={**(wo_overrides or {}), "client_user_id": client_user_id},
    )
    accept_estimate(wo["id"], est["id"], client_user_id=client_user_id)
    wo = get_success_data(api_client.get_work_order(
        wo["id"], TEST_USERS["dispatcher_headers"],
    ))
    return area, wo, tree, est


def setup_scheduled_with_crew(
    pricing_mode: str = "HOURLY",
    crew_overrides: Optional[dict] = None,
    tree_overrides: Optional[dict] = None,
    area_overrides: Optional[dict] = None,
):
    """SCHEDULED work order + a crew registered in the same region.

    Returns (area, work_order, tree, estimate, crew). The crew is in-region
    so region-match passes; pass crew_overrides for clearance certification.
    """
    area = create_service_area(**(area_overrides or {}))
    crew = create_crew(area["id"], **(crew_overrides or {}))
    wo = create_work_order(area["id"], pricing_mode=pricing_mode)
    tree = add_tree(wo["id"], **(tree_overrides or {}))
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    est = issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    wo = get_success_data(api_client.get_work_order(
        wo["id"], TEST_USERS["dispatcher_headers"],
    ))
    return area, wo, tree, est, crew


def setup_permit_work_order_under_review(area_overrides: Optional[dict] = None):
    """PER_JOB work order with a protected tree (requires_permit true after
    assess), an ISSUED estimate, and a permit driven to UNDER_REVIEW.

    Returns (area, work_order, tree, estimate, permit).
    """
    overrides = {"requires_permit_authority": True}
    overrides.update(area_overrides or {})
    area = create_service_area(**overrides)
    wo = create_work_order(area["id"], pricing_mode="PER_JOB")
    tree = add_tree(wo["id"], species="Oak", dbh_inches=30, is_protected=True)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    est = issue_estimate(wo["id"], est["id"])
    permit = create_permit(wo["id"], authority_ref="PRM-77")
    permit = submit_permit(wo["id"], permit["id"])
    return area, wo, tree, est, permit
