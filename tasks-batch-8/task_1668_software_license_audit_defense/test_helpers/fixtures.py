"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Setup calls use get_success_data() so a failure surfaces as a clear "Setup step
failed" error rather than a confusing assertion failure deep inside a test.
"""
from datetime import datetime

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_case_payload,
    create_data_submission_payload,
    create_deployment_payload,
    create_entitlement_payload,
    create_product_payload,
    create_remediation_payload,
    create_scope_item_payload,
    create_settlement_offer_payload,
    create_vendor_payload,
)
from .test_users import (
    TEST_USERS,
    make_legal_counsel_headers,
    make_procurement_lead_headers,
    make_sam_manager_headers,
    make_vendor_auditor_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SAM_MGR = TEST_USERS["sam_manager_headers"]
IT_ANALYST = TEST_USERS["it_analyst_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]
PROCUREMENT = TEST_USERS["procurement_lead_headers"]
AUDITOR = TEST_USERS["vendor_auditor_headers"]


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp tolerating optional fractional digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ─── Catalog primitives ───────────────────────────────

def create_vendor(**overrides) -> dict:
    return get_success_data(api_client.create_vendor(create_vendor_payload(**overrides), ADMIN))


def create_product(vendor_id: str = None, **overrides) -> dict:
    if vendor_id is None:
        vendor_id = create_vendor()["id"]
    return get_success_data(
        api_client.create_product(create_product_payload(vendor_id, **overrides), ADMIN))


def create_vendor_and_product(**product_overrides):
    vendor = create_vendor()
    product = create_product(vendor["id"], **product_overrides)
    return vendor, product


def set_clock(to_iso8601: str) -> dict:
    """Set the logical clock (PRD §2.4); triggers the entitlement and alert sweeps."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ─── Entitlements & deployments ───────────────────────

def create_entitlement(product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_entitlement(create_entitlement_payload(product_id, **overrides),
                                      SAM_MGR))


def create_deployment(product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_deployment(create_deployment_payload(product_id, **overrides),
                                     IT_ANALYST))


def confirm_deployment(deployment_id: str) -> dict:
    return get_success_data(api_client.confirm_deployment(deployment_id, SAM_MGR))


def create_confirmed_deployment(product_id: str, measured_quantity: int, **overrides) -> dict:
    dep = create_deployment(product_id, measured_quantity=measured_quantity, **overrides)
    return confirm_deployment(dep["id"])


def list_product_deployments(product_id: str) -> list:
    return get_success_data(api_client.list_deployments(product_id, SAM_MGR))


def list_product_entitlements(product_id: str) -> list:
    return get_success_data(api_client.list_entitlements(product_id, SAM_MGR))


# ─── License positions & alerts ───────────────────────

def get_license_position(product_id: str) -> dict:
    """PRD §3.4: exactly one position exists per product; the read returns an array."""
    rows = get_success_data(api_client.list_license_positions(product_id, SAM_MGR))
    assert isinstance(rows, list) and len(rows) == 1, \
        f"expected exactly one LicensePosition for product {product_id}, got {rows!r}"
    return rows[0]


def list_product_alerts(product_id: str, params: dict = None) -> list:
    return get_success_data(api_client.list_monitoring_alerts(product_id, SAM_MGR,
                                                              params=params))


def recalculate_position(position_id: str) -> dict:
    return get_success_data(api_client.recalculate_license_position(position_id, SAM_MGR))


# ─── Product-with-gap composite ───────────────────────

def setup_product_with_gap(entitled: int = 0, deployed: int = 0,
                           unit_list_price_cents: int = 10000,
                           support_rate_pct: float = 0.22,
                           license_metric: str = "PER_INSTALL",
                           deployment_quantities=None,
                           **product_overrides) -> dict:
    """Vendor + product + one ACTIVE entitlement of `entitled` units + CONFIRMED
    deployments totalling `deployed` PRODUCTION units.

    `deployment_quantities` overrides `deployed`: a list of (quantity, environment)
    tuples, each created and confirmed individually. Returns a context dict with
    vendor, product, entitlement, deployments, and the recomputed position.
    """
    vendor, product = create_vendor_and_product(
        license_metric=license_metric,
        unit_list_price_cents=unit_list_price_cents,
        support_rate_pct=support_rate_pct,
        **product_overrides)
    entitlement = None
    if entitled > 0:
        entitlement = create_entitlement(product["id"], quantity=entitled)
    deployments = []
    if deployment_quantities is not None:
        for qty, env in deployment_quantities:
            deployments.append(
                create_confirmed_deployment(product["id"], qty, environment=env))
    elif deployed > 0:
        deployments.append(create_confirmed_deployment(product["id"], deployed))
    position = get_license_position(product["id"])
    return {
        "vendor": vendor,
        "product": product,
        "entitlement": entitlement,
        "deployments": deployments,
        "position": position,
    }


# ─── Audit case primitives ────────────────────────────

def create_audit_case(vendor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_audit_case(create_audit_case_payload(vendor_id, **overrides),
                                     COUNSEL))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_audit_case(case_id, COUNSEL))


def advance_case(case_id: str, to_state: str) -> dict:
    return get_success_data(
        api_client.advance_audit_case(case_id, {"to_state": to_state}, COUNSEL))


def propose_scope_item(case_id: str, product_id: str,
                       rationale: str = "in scope", party: str = "VENDOR") -> dict:
    """party=VENDOR proposes as VendorAuditor; party=CUSTOMER as SAMManager (PRD §3.5)."""
    headers = AUDITOR if party == "VENDOR" else SAM_MGR
    return get_success_data(api_client.create_scope_item(
        create_scope_item_payload(case_id, product_id, inclusion_rationale=rationale),
        headers))


def confirm_scope_item(scope_item_id: str) -> dict:
    return get_success_data(api_client.confirm_scope_item(scope_item_id, COUNSEL))


def list_case_scope_items(case_id: str) -> list:
    return get_success_data(api_client.list_scope_items(case_id, COUNSEL))


def get_scope_item(case_id: str, scope_item_id: str) -> dict:
    for row in list_case_scope_items(case_id):
        if row["id"] == scope_item_id:
            return row
    raise AssertionError(f"scope item {scope_item_id} not found in case {case_id}")


# ─── Case progression composites ──────────────────────

def setup_case_in_scope_negotiation(product_ctx: dict = None) -> dict:
    """Vendor + product + case advanced to SCOPE_NEGOTIATION."""
    if product_ctx is None:
        product_ctx = setup_product_with_gap()
    case = create_audit_case(product_ctx["vendor"]["id"])
    case = advance_case(case["id"], "SCOPE_NEGOTIATION")
    return {**product_ctx, "case": case}


def setup_case_with_confirmed_item(product_ctx: dict = None, party: str = "VENDOR",
                                   rationale: str = "in scope") -> dict:
    """Case in SCOPE_NEGOTIATION with one CONFIRMED scope item for the product."""
    ctx = setup_case_in_scope_negotiation(product_ctx)
    item = propose_scope_item(ctx["case"]["id"], ctx["product"]["id"],
                              rationale=rationale, party=party)
    item = confirm_scope_item(item["id"])
    ctx["scope_item"] = item
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def setup_case_in_evidence_collection(product_ctx: dict = None,
                                      party: str = "VENDOR") -> dict:
    ctx = setup_case_with_confirmed_item(product_ctx, party=party)
    ctx["case"] = advance_case(ctx["case"]["id"], "EVIDENCE_COLLECTION")
    return ctx


# ─── Data submission composites ───────────────────────

def create_submission(case_id: str, covered_scope_item_ids,
                      preparer_user_id: str = "sam-mgr-1", **overrides) -> dict:
    return get_success_data(api_client.create_data_submission(
        create_data_submission_payload(case_id, covered_scope_item_ids, **overrides),
        make_sam_manager_headers(preparer_user_id)))


def submit_for_review(submission_id: str, user_id: str = "sam-mgr-1") -> dict:
    return get_success_data(
        api_client.submit_for_review(submission_id, make_sam_manager_headers(user_id)))


def approve_submission(submission_id: str, approver_user_id: str = "counsel-1") -> dict:
    return get_success_data(
        api_client.approve_submission(submission_id,
                                      make_legal_counsel_headers(approver_user_id)))


def release_submission(submission_id: str, releaser_user_id: str = "counsel-1",
                       payload: dict = None) -> dict:
    return get_success_data(api_client.release_submission(
        submission_id, payload or {}, make_legal_counsel_headers(releaser_user_id)))


def setup_released_submission(ctx: dict, covered_ids=None,
                              preparer_user_id: str = "sam-mgr-1",
                              approver_user_id: str = "counsel-1", **overrides) -> dict:
    """DRAFT -> PRIVILEGE_REVIEW -> APPROVED -> RELEASED on one package (PRD §3.6)."""
    covered_ids = covered_ids or [ctx["scope_item"]["id"]]
    sub = create_submission(ctx["case"]["id"], covered_ids, preparer_user_id, **overrides)
    submit_for_review(sub["id"], preparer_user_id)
    approve_submission(sub["id"], approver_user_id)
    return release_submission(sub["id"], approver_user_id)


def setup_case_in_findings_review(product_ctx: dict = None, party: str = "VENDOR") -> dict:
    """Case advanced to FINDINGS_REVIEW with one RELEASED submission (PRD §3.5)."""
    ctx = setup_case_in_evidence_collection(product_ctx, party=party)
    ctx["submission"] = setup_released_submission(ctx)
    ctx["case"] = advance_case(ctx["case"]["id"], "FINDINGS_REVIEW")
    return ctx


def record_vendor_finding(scope_item_id: str) -> dict:
    return get_success_data(
        api_client.record_vendor_finding(scope_item_id, AUDITOR))


def setup_case_in_settlement_negotiation(product_ctx: dict = None,
                                         record_finding: bool = True) -> dict:
    """Full flow to SETTLEMENT_NEGOTIATION (PRD §3.5–§3.7). ctx["case"] carries the
    fresh version usable as expected_audit_case_version for tendering offers."""
    ctx = setup_case_in_findings_review(product_ctx)
    if record_finding:
        ctx["scope_item"] = record_vendor_finding(ctx["scope_item"]["id"])
    ctx["case"] = advance_case(ctx["case"]["id"], "SETTLEMENT_NEGOTIATION")
    return ctx


# ─── Settlement offer composites ──────────────────────

def tender_offer(case_id: str, offered_by: str, amount_cents: int,
                 expected_audit_case_version: int, tenderer_user_id: str = None,
                 **overrides):
    """Tender an offer; returns the RAW response so callers can validate either
    success or an expected error."""
    payload = create_settlement_offer_payload(
        case_id, offered_by, amount_cents, expected_audit_case_version, **overrides)
    if offered_by == "CUSTOMER":
        headers = make_procurement_lead_headers(tenderer_user_id or "proc-1")
    else:
        headers = make_vendor_auditor_headers(tenderer_user_id or "aud-1")
    return api_client.create_settlement_offer(payload, headers)


def tender_offer_ok(case_id: str, offered_by: str, amount_cents: int,
                    expected_audit_case_version: int, tenderer_user_id: str = None,
                    **overrides) -> dict:
    return get_success_data(
        tender_offer(case_id, offered_by, amount_cents, expected_audit_case_version,
                     tenderer_user_id, **overrides))


# ─── Remediation composites ───────────────────────────

def create_remediation(product_id: str, action_type: str, **overrides) -> dict:
    return get_success_data(api_client.create_remediation_action(
        create_remediation_payload(product_id, action_type, **overrides), SAM_MGR))


def start_remediation(action_id: str) -> dict:
    return get_success_data(api_client.start_remediation(action_id, SAM_MGR))


def complete_remediation(action_id: str) -> dict:
    return get_success_data(api_client.complete_remediation(action_id, SAM_MGR))


def fail_verification(action_id: str, **overrides) -> dict:
    return get_success_data(api_client.fail_verification(action_id, overrides, SAM_MGR))
