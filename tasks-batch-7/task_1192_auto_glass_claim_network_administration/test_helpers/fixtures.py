"""Composite setup helpers (PRD §3.1-§3.7).

Every helper builds preconditions from scratch through the public API; the
test harness restarts the server (empty DB) before each test. Setup calls use
the lenient get_success_data() so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_policyholder_payload, create_state_regulation_payload,
    create_policy_payload, create_glass_shop_payload,
    create_part_catalog_entry_payload, create_claim_payload,
    create_choice_disclosure_payload, schedule_payload,
    create_calibration_event_payload, create_invoice_payload,
    audit_decision_payload, part_line, create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS, make_policyholder_headers, make_shop_operator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]       # opaque id "adjuster-1"
AUDITOR = TEST_USERS["auditor_headers"]         # opaque id "auditor-1" (SOD-safe vs adjuster-1)
AUDITOR2 = TEST_USERS["auditor2_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.4)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed (set_clock): {resp.text}"
    return get_success_data(resp)


def make_regulation(state_code: str = "FL", zero_deductible_windshield: bool = False,
                    max_deductible_cents=None, tax_bp: int = 0) -> dict:
    payload = create_state_regulation_payload(
        state_code=state_code,
        zero_deductible_windshield=zero_deductible_windshield,
        glass_sales_tax_rate_bp=tax_bp,
    )
    if max_deductible_cents is not None:
        payload["max_deductible_cents"] = max_deductible_cents
    resp = api_client.create_state_regulation(payload, ADMIN)
    assert resp.status_code == 201, f"Setup failed (regulation {state_code}): {resp.text}"
    return get_success_data(resp)


def make_policyholder(**overrides) -> dict:
    resp = api_client.create_policyholder(create_policyholder_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed (policyholder): {resp.text}"
    return get_success_data(resp)


def make_policy(policyholder_id: str, **overrides) -> dict:
    resp = api_client.create_policy(create_policy_payload(policyholder_id, **overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed (policy): {resp.text}"
    return get_success_data(resp)


def make_shop(**overrides) -> dict:
    resp = api_client.create_glass_shop(create_glass_shop_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed (shop): {resp.text}"
    return get_success_data(resp)


def make_part(**overrides) -> dict:
    resp = api_client.create_part_catalog_entry(create_part_catalog_entry_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed (part): {resp.text}"
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: claim lifecycle steps
# ---------------------------------------------------------------------------

def make_claim(policyholder: dict, policy: dict, **overrides) -> dict:
    """POST /claims as the owning policyholder (identity from X-User-ID)."""
    resp = api_client.create_claim(
        create_claim_payload(policy["id"], **overrides),
        make_policyholder_headers(policyholder["id"]),
    )
    assert resp.status_code == 201, f"Setup failed (claim): {resp.text}"
    return get_success_data(resp)


def add_disclosure(claim_id: str, policyholder_id: str, shop_solicited: bool = False,
                   **overrides) -> dict:
    resp = api_client.create_choice_disclosure(
        claim_id,
        create_choice_disclosure_payload(shop_solicited=shop_solicited, **overrides),
        make_policyholder_headers(policyholder_id),
    )
    assert resp.status_code == 201, f"Setup failed (disclosure): {resp.text}"
    return get_success_data(resp)


def verify_claim(claim_id: str, adjuster_headers=None) -> dict:
    resp = api_client.verify_coverage(claim_id, {}, adjuster_headers or ADJUSTER)
    assert resp.status_code == 200, f"Setup failed (verify-coverage): {resp.text}"
    return get_success_data(resp)


def route_claim(claim_id: str, adjuster_headers=None, requested_shop_id=None,
                expected_claim_version=None) -> dict:
    """Create a routing decision; returns the new OFFERED work order."""
    if expected_claim_version is None:
        claim = get_success_data(api_client.get_claim(claim_id, adjuster_headers or ADJUSTER))
        expected_claim_version = claim["version"]
    payload = {"expected_claim_version": expected_claim_version}
    if requested_shop_id is not None:
        payload["requested_shop_id"] = requested_shop_id
    resp = api_client.create_routing_decision(claim_id, payload, adjuster_headers or ADJUSTER)
    assert resp.status_code == 201, f"Setup failed (routing-decisions): {resp.text}"
    return get_success_data(resp)


def accept_work_order(work_order_id: str, shop_id: str) -> dict:
    resp = api_client.accept_work_order(work_order_id, make_shop_operator_headers(shop_id))
    assert resp.status_code == 200, f"Setup failed (accept): {resp.text}"
    return get_success_data(resp)


def schedule_work_order(work_order_id: str, shop_id: str, service_mode: str = "IN_SHOP",
                        start: str = "2026-05-02T10:00:00Z",
                        end: str = "2026-05-02T11:00:00Z",
                        expected_work_order_version=None) -> dict:
    if expected_work_order_version is None:
        wo = get_success_data(api_client.get_work_order(work_order_id, ADMIN))
        expected_work_order_version = wo["version"]
    resp = api_client.schedule_work_order(
        work_order_id,
        schedule_payload(
            expected_work_order_version,
            service_mode=service_mode, scheduled_start=start, scheduled_end=end,
        ),
        make_shop_operator_headers(shop_id),
    )
    assert resp.status_code == 200, f"Setup failed (schedule): {resp.text}"
    return get_success_data(resp)


def complete_work_order(work_order_id: str, shop_id: str) -> dict:
    resp = api_client.complete_work_order(work_order_id, make_shop_operator_headers(shop_id))
    assert resp.status_code == 200, f"Setup failed (complete): {resp.text}"
    return get_success_data(resp)


def create_invoice(work_order_id: str, shop_id: str, line_items: list) -> dict:
    resp = api_client.create_invoice(
        work_order_id, create_invoice_payload(line_items),
        make_shop_operator_headers(shop_id),
    )
    assert resp.status_code == 201, f"Setup failed (invoice): {resp.text}"
    return get_success_data(resp)


def submit_invoice(invoice_id: str, shop_id: str, revised_line_items=None) -> dict:
    payload = {}
    if revised_line_items is not None:
        payload["revised_line_items"] = revised_line_items
    resp = api_client.submit_invoice(
        invoice_id, payload, make_shop_operator_headers(shop_id))
    assert resp.status_code == 200, f"Setup failed (submit): {resp.text}"
    return get_success_data(resp)


def approve_invoice(invoice_id: str, adjustment_lines, auditor_headers=None) -> dict:
    resp = api_client.create_audit_decision(
        invoice_id, audit_decision_payload("APPROVE", adjustment_lines),
        auditor_headers or AUDITOR,
    )
    assert resp.status_code == 200, f"Setup failed (APPROVE): {resp.text}"
    return get_success_data(resp)


def dispute_invoice(invoice_id: str, adjustment_lines, auditor_headers=None) -> dict:
    resp = api_client.create_audit_decision(
        invoice_id, audit_decision_payload("DISPUTE", adjustment_lines),
        auditor_headers or AUDITOR,
    )
    assert resp.status_code == 200, f"Setup failed (DISPUTE): {resp.text}"
    return get_success_data(resp)


def pay_invoice(invoice_id: str, auditor_headers=None) -> dict:
    resp = api_client.pay_invoice(invoice_id, auditor_headers or AUDITOR)
    assert resp.status_code == 200, f"Setup failed (pay): {resp.text}"
    return get_success_data(resp)


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, ADMIN))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def get_shop(shop_id: str) -> dict:
    return get_success_data(api_client.get_glass_shop(shop_id, ADMIN))


def get_policyholder(policyholder_id: str) -> dict:
    return get_success_data(api_client.get_policyholder(policyholder_id, ADMIN))


def get_capacity(shop_id: str, date: str) -> dict:
    return get_success_data(api_client.get_shop_capacity(shop_id, date, ADMIN))


def list_fraud_alerts_for_claim(claim_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_fraud_alerts(INVESTIGATOR, params={"claim_id": claim_id}))
    return data


# ---------------------------------------------------------------------------
# Tier 3: composite scenario builders
# ---------------------------------------------------------------------------

def setup_network(state_code: str = "FL", zero_deductible_windshield: bool = False,
                  max_deductible_cents=None, tax_bp: int = 0,
                  deductible_cents: int = 50000, oem_endorsement: bool = False,
                  coverage_type: str = "COMPREHENSIVE",
                  shop_overrides: dict = None, part_overrides: dict = None,
                  with_shop: bool = True, with_part: bool = True) -> dict:
    """Regulation + policyholder + policy (+ optional default shop and part)."""
    regulation = make_regulation(state_code, zero_deductible_windshield,
                                 max_deductible_cents, tax_bp)
    policyholder = make_policyholder(state_code=state_code)
    policy = make_policy(
        policyholder["id"], state_code=state_code,
        coverage_type=coverage_type, deductible_cents=deductible_cents,
        oem_endorsement=oem_endorsement,
    )
    ctx = {"regulation": regulation, "policyholder": policyholder, "policy": policy}
    if with_shop:
        ctx["shop"] = make_shop(**(shop_overrides or {}))
    if with_part:
        ctx["part"] = make_part(**(part_overrides or {}))
    return ctx


def setup_claim_verified(network: dict = None, claim_overrides: dict = None,
                         with_disclosure: bool = True, **network_kwargs) -> dict:
    """Network + claim in COVERAGE_VERIFIED (disclosure optional)."""
    ctx = network or setup_network(**network_kwargs)
    claim = make_claim(ctx["policyholder"], ctx["policy"], **(claim_overrides or {}))
    ctx["claim"] = claim
    if with_disclosure:
        ctx["disclosure"] = add_disclosure(claim["id"], ctx["policyholder"]["id"])
    ctx["claim"] = verify_claim(claim["id"])
    return ctx


def setup_work_order_offered(network: dict = None, claim_overrides: dict = None,
                             requested_shop_id=None, **network_kwargs) -> dict:
    """Claim routed; work order OFFERED. claim version advanced by routing."""
    ctx = setup_claim_verified(network, claim_overrides, with_disclosure=True,
                               **network_kwargs)
    requested = requested_shop_id if requested_shop_id is not None else (
        ctx["shop"]["id"] if "shop" in ctx else None)
    ctx["work_order"] = route_claim(ctx["claim"]["id"], requested_shop_id=requested)
    return ctx


def setup_work_order_accepted(**kwargs) -> dict:
    ctx = setup_work_order_offered(**kwargs)
    ctx["work_order"] = accept_work_order(ctx["work_order"]["id"], ctx["work_order"]["shop_id"])
    return ctx


def setup_work_order_scheduled(service_mode: str = "IN_SHOP",
                               start: str = "2026-05-02T10:00:00Z",
                               end: str = "2026-05-02T11:00:00Z", **kwargs) -> dict:
    ctx = setup_work_order_accepted(**kwargs)
    ctx["work_order"] = schedule_work_order(
        ctx["work_order"]["id"], ctx["work_order"]["shop_id"],
        service_mode=service_mode, start=start, end=end)
    return ctx


def setup_work_order_completed(service_mode: str = "IN_SHOP",
                               start: str = "2026-05-02T10:00:00Z",
                               end: str = "2026-05-02T11:00:00Z",
                               complete_at: str = "2026-05-02T12:00:00Z",
                               **kwargs) -> dict:
    """Work order SCHEDULED then COMPLETED; claim cascades to WORK_COMPLETED."""
    ctx = setup_work_order_scheduled(service_mode, start, end, **kwargs)
    set_clock(complete_at)
    ctx["work_order"] = complete_work_order(ctx["work_order"]["id"], ctx["work_order"]["shop_id"])
    return ctx


def setup_invoice_submitted(line_items: list = None, part_price_cents: int = 95000,
                            **kwargs) -> dict:
    """Completed work order + DRAFT invoice + submit; claim INVOICED."""
    ctx = setup_work_order_completed(**kwargs)
    if line_items is None:
        line_items = [part_line(ctx["part"]["id"], part_price_cents)]
    ctx["invoice"] = create_invoice(ctx["work_order"]["id"], ctx["work_order"]["shop_id"],
                                    line_items)
    ctx["invoice"] = submit_invoice(ctx["invoice"]["id"], ctx["work_order"]["shop_id"])
    return ctx


def setup_invoice_approved(approve_amounts: list = None, **kwargs) -> dict:
    """Submitted invoice + APPROVE in full (or per approve_amounts)."""
    ctx = setup_invoice_submitted(**kwargs)
    invoice = ctx["invoice"]
    if approve_amounts is None:
        lines, _meta = validate_paginated(
            api_client.list_invoice_line_items(invoice["id"], ADMIN))
        approve_amounts = [ln["line_total_cents"] for ln in lines]
    adjustment = [
        {"line_index": i, "approved_amount_cents": amt}
        for i, amt in enumerate(approve_amounts)
    ]
    ctx["invoice"] = approve_invoice(invoice["id"], adjustment)
    return ctx


def setup_invoice_paid(**kwargs) -> dict:
    """Full billing lifecycle through PAID; claim SETTLED."""
    ctx = setup_invoice_approved(**kwargs)
    ctx["invoice"] = pay_invoice(ctx["invoice"]["id"])
    return ctx


def setup_warranty_filed(**kwargs) -> dict:
    """Completed work order + one warranty claim FILED by the policyholder."""
    ctx = setup_work_order_completed(**kwargs)
    resp = api_client.create_warranty_claim(
        ctx["work_order"]["id"], create_warranty_claim_payload(),
        make_policyholder_headers(ctx["policyholder"]["id"]),
    )
    assert resp.status_code == 201, f"Setup failed (warranty claim): {resp.text}"
    ctx["warranty_claim"] = get_success_data(resp)
    return ctx


def setup_calibration_event(ctx: dict, start: str = "2026-05-02T12:30:00Z",
                            end: str = "2026-05-02T13:00:00Z",
                            calibration_type: str = "STATIC") -> dict:
    """Book a calibration event beneath ctx's work order (must be ACCEPTED/SCHEDULED)."""
    resp = api_client.create_calibration_event(
        ctx["work_order"]["id"],
        create_calibration_event_payload(
            calibration_type=calibration_type, scheduled_start=start, scheduled_end=end),
        make_shop_operator_headers(ctx["work_order"]["shop_id"]),
    )
    assert resp.status_code == 201, f"Setup failed (calibration event): {resp.text}"
    return get_success_data(resp)
