"""Composite setup helpers for multi-step preconditions.

Walking the PRD's lifecycle from a fresh BudgetAccount through to a CLOSED
PurchaseOrder is too expensive to repeat per test. This module captures
the common multi-call sequences once, with sensible defaults plus
**override hooks for boundary tests.

Identity threading (PRD §2.1): when a fixture creates a Supplier, ANY
downstream ownership-gated call (POST /invoices, POST /contracts/{id}/sign
with role=Supplier) MUST use make_supplier_headers(supplier["id"]).
That is enforced here at the helper level so tests inherit it for free.

Setup calls use get_success_data (lenient validator) so a precondition
failure surfaces as a clear "Setup failed" rather than as a confusing
assertion mismatch later.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_quote_payload,
    amend_contract_payload,
    apply_payment_payload,
    approve_step_payload,
    award_payload,
    create_budget_account_payload,
    create_clause_template_payload,
    create_contract_payload,
    create_invoice_payload,
    create_receipt_payload,
    create_requirement_payload,
    create_supplier_payload,
    delegate_step_payload,
    override_invoice_payload,
    reject_invoice_payload,
    shortlist_payload,
    sign_contract_payload,
    supplier_delivery_payload,
    terminate_contract_payload,
    unique_delivery_note_no,
    unique_invoice_no,
)
from .test_users import (
    TEST_USERS,
    make_buyer_headers,
    make_dept_head_headers,
    make_finance_headers,
    make_gm_headers,
    make_inspector_headers,
    make_legal_headers,
    make_platform_admin_headers,
    make_requester_headers,
    make_supplier_headers,
)


# ===========================================================================
# Time helpers (PRD §3.11 logical clock)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits
    (PRD §2.4 timestamp format)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


def advance_clock(to_iso: str) -> Dict[str, Any]:
    """POST /_clock/advance with PlatformAdmin headers (PRD §3.11)."""
    return get_success_data(
        api_client.advance_clock(to_iso, TEST_USERS["platform_admin_headers"])
    )


# ===========================================================================
# Far-future / safe defaults
# ===========================================================================
DEFAULT_DELIVERY_DATE = "2030-12-01T00:00:00.000Z"
DEFAULT_QUALIFICATION_EXPIRES = "2099-12-31T23:59:59.000Z"


# ===========================================================================
# Tier 1: Budget + Supplier scaffolding
# ===========================================================================
def create_budget_account(
    *,
    total_amount_cents: int = 100_000_000,
    department: str = "IT",
    fiscal_year: int = 2030,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a BudgetAccount in ACTIVE (PRD §3.1)."""
    payload = create_budget_account_payload(
        total_amount_cents=total_amount_cents,
        department=department,
        fiscal_year=fiscal_year,
        **overrides,
    )
    return get_success_data(
        api_client.create_budget_account(payload, TEST_USERS["finance_headers"])
    )


def create_provisional_supplier(
    *,
    qualification_categories: Optional[List[str]] = None,
    qualification_expires_at: str = DEFAULT_QUALIFICATION_EXPIRES,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a Supplier in PROVISIONAL status (PRD §3.1)."""
    payload = create_supplier_payload(
        qualification_categories=qualification_categories or ["IT_HARDWARE"],
        qualification_expires_at=qualification_expires_at,
        **overrides,
    )
    return get_success_data(
        api_client.create_supplier(payload, TEST_USERS["buyer_headers"])
    )


def create_qualified_supplier(
    *,
    qualification_categories: Optional[List[str]] = None,
    qualification_expires_at: str = DEFAULT_QUALIFICATION_EXPIRES,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register + qualify a Supplier (PRD §3.1).

    PRD §3.1: "A LegalApprover later promotes the supplier to QUALIFIED
    after due diligence." Returns the post-qualify Supplier.
    """
    s = create_provisional_supplier(
        qualification_categories=qualification_categories,
        qualification_expires_at=qualification_expires_at,
        **overrides,
    )
    return get_success_data(
        api_client.qualify_supplier(s["id"], TEST_USERS["legal_headers"])
    )


def create_qualified_suppliers(
    n: int,
    *,
    qualification_categories: Optional[List[str]] = None,
    qualification_expires_at: str = DEFAULT_QUALIFICATION_EXPIRES,
) -> List[Dict[str, Any]]:
    return [
        create_qualified_supplier(
            qualification_categories=qualification_categories,
            qualification_expires_at=qualification_expires_at,
        )
        for _ in range(n)
    ]


# ===========================================================================
# Tier 2: Requirement progression
# ===========================================================================
def create_draft_requirement(
    *,
    budget_account_id: str,
    category: str = "IT_HARDWARE",
    quantity: int = 10,
    estimated_unit_price_cents: int = 100_000,
    expected_delivery_date: str = DEFAULT_DELIVERY_DATE,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Requirement in DRAFT (PRD §3.2)."""
    payload = create_requirement_payload(
        budget_account_id=budget_account_id,
        category=category,
        quantity=quantity,
        estimated_unit_price_cents=estimated_unit_price_cents,
        expected_delivery_date=expected_delivery_date,
        **overrides,
    )
    return get_success_data(
        api_client.create_requirement(payload, TEST_USERS["requester_headers"])
    )


def submit_requirement(req_id: str) -> Dict[str, Any]:
    """Advance Requirement DRAFT -> SUBMITTED (PRD §3.2)."""
    return get_success_data(
        api_client.submit_requirement(req_id, TEST_USERS["requester_headers"])
    )


def add_quote(
    req_id: str,
    *,
    supplier_id: str,
    unit_price_cents: int,
    technical_score: float = 80.0,
    lead_time_days: int = 14,
) -> Dict[str, Any]:
    """Add a Quote to a SUBMITTED/IN_SOURCING Requirement (PRD §3.2)."""
    payload = add_quote_payload(
        supplier_id=supplier_id,
        unit_price_cents=unit_price_cents,
        technical_score=technical_score,
        lead_time_days=lead_time_days,
    )
    return get_success_data(
        api_client.add_quote(req_id, payload, TEST_USERS["buyer_headers"])
    )


def shortlist_quotes(req_id: str, quote_ids: List[str]) -> Dict[str, Any]:
    """Designate the SHORTLISTED set (PRD §3.2)."""
    payload = shortlist_payload(quote_ids=quote_ids)
    return get_success_data(
        api_client.shortlist_quotes(req_id, payload, TEST_USERS["buyer_headers"])
    )


def award_requirement(
    req_id: str,
    *,
    awarded_quote_id: str,
    justification: str = "Selected by composite-score ranking.",
) -> Dict[str, Any]:
    """Award a Requirement -> creates PO (PRD §3.3)."""
    payload = award_payload(
        awarded_quote_id=awarded_quote_id, justification=justification
    )
    return get_success_data(
        api_client.award_requirement(req_id, payload, TEST_USERS["buyer_headers"])
    )


# ===========================================================================
# Tier 3: Composite — Requirement IN_SOURCING with N quotes
# ===========================================================================
def setup_requirement_with_quotes(
    *,
    quote_specs: List[Tuple[int, float]],
    category: str = "IT_HARDWARE",
    quantity: int = 10,
    budget_total_cents: int = 100_000_000,
    expected_delivery_date: str = DEFAULT_DELIVERY_DATE,
    qualification_expires_at: str = DEFAULT_QUALIFICATION_EXPIRES,
) -> Dict[str, Any]:
    """Build BudgetAccount + N qualified Suppliers + Requirement SUBMITTED
    + N Quotes (in SUBMITTED) on the Requirement.

    quote_specs is a list of (unit_price_cents, technical_score) tuples;
    one Supplier and one Quote are produced per entry. Returns dict with
    keys: budget, suppliers, requirement, quotes.
    """
    budget = create_budget_account(total_amount_cents=budget_total_cents)
    suppliers = create_qualified_suppliers(
        len(quote_specs),
        qualification_categories=[category],
        qualification_expires_at=qualification_expires_at,
    )
    req = create_draft_requirement(
        budget_account_id=budget["id"],
        category=category,
        quantity=quantity,
        expected_delivery_date=expected_delivery_date,
    )
    submit_requirement(req["id"])
    quotes: List[Dict[str, Any]] = []
    for supplier, (price, tech) in zip(suppliers, quote_specs):
        q = add_quote(
            req["id"],
            supplier_id=supplier["id"],
            unit_price_cents=price,
            technical_score=tech,
        )
        quotes.append(q)
    return {
        "budget": budget,
        "suppliers": suppliers,
        "requirement": req,
        "quotes": quotes,
    }


def setup_shortlisted_requirement(
    *,
    quote_specs: List[Tuple[int, float]],
    shortlist_indices: Optional[List[int]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """As setup_requirement_with_quotes, but additionally shortlists the
    indicated quote indices (default: all). When shortlist_indices is an
    empty list, no shortlist call is made — quotes remain in SUBMITTED."""
    setup = setup_requirement_with_quotes(quote_specs=quote_specs, **kwargs)
    if shortlist_indices is None:
        shortlist_indices = list(range(len(setup["quotes"])))
    if not shortlist_indices:
        # Empty list: caller wants quotes to remain in SUBMITTED. Do not
        # POST /shortlist (PRD requires quote_ids to be a non-empty list).
        return setup
    quote_ids = [setup["quotes"][i]["id"] for i in shortlist_indices]
    shortlist_quotes(setup["requirement"]["id"], quote_ids)
    return setup


def setup_awarded_po(
    *,
    quote_specs: Optional[List[Tuple[int, float]]] = None,
    awarded_index: int = 0,
    quantity: int = 10,
    budget_total_cents: int = 100_000_000,
    category: str = "IT_HARDWARE",
    qualification_expires_at: str = DEFAULT_QUALIFICATION_EXPIRES,
    expected_delivery_date: str = DEFAULT_DELIVERY_DATE,
    justification: str = "Selected by composite-score ranking.",
    actor_suffix: Optional[str] = None,  # noqa: ARG001 — accepted for parity
                                         # with setup_approved_po; unused at
                                         # award time, but threading-friendly
                                         # for callers that pass it through.
) -> Dict[str, Any]:
    """Walk Requirement -> AWARDED, creating a PO and approval steps.

    Default quote_specs are three quotes ranked so quote[0] wins on
    price+tech. Returns dict with keys: budget, suppliers, requirement,
    quotes, po, approval_steps.
    """
    if quote_specs is None:
        quote_specs = [(100_000, 90.0), (110_000, 80.0), (120_000, 70.0)]
    setup = setup_shortlisted_requirement(
        quote_specs=quote_specs,
        category=category,
        quantity=quantity,
        budget_total_cents=budget_total_cents,
        qualification_expires_at=qualification_expires_at,
        expected_delivery_date=expected_delivery_date,
    )
    awarded_quote = setup["quotes"][awarded_index]
    po = award_requirement(
        setup["requirement"]["id"],
        awarded_quote_id=awarded_quote["id"],
        justification=justification,
    )
    steps = get_success_data(
        api_client.list_approval_steps(po["id"], TEST_USERS["buyer_headers"])
    )
    if isinstance(steps, dict):
        steps = steps.get("approval_steps") or steps.get("data") or []
    setup["po"] = po
    setup["approval_steps"] = steps
    setup["awarded_quote"] = awarded_quote
    return setup


# ===========================================================================
# Tier 4: Approval state progression
# ===========================================================================
def approve_step_as(
    step_id: str,
    *,
    role_headers: Dict[str, str],
    decision_comment: Optional[str] = None,
) -> Dict[str, Any]:
    payload = approve_step_payload(decision_comment=decision_comment)
    return get_success_data(
        api_client.approve_step(step_id, role_headers, payload=payload)
    )


def reject_step_as(
    step_id: str,
    *,
    role_headers: Dict[str, str],
    decision_comment: Optional[str] = None,
) -> Dict[str, Any]:
    payload = approve_step_payload(decision_comment=decision_comment)
    return get_success_data(
        api_client.reject_step(step_id, role_headers, payload=payload)
    )


# Stage -> opaque-role-headers builder. Each PO needs distinct user_ids per
# step to satisfy PRD §2.8 priority 7 segregation-of-duties.
_STAGE_HEADERS_BUILDER = {
    "DEPARTMENT_HEAD": (make_dept_head_headers, "dept-head"),
    "FINANCE": (make_finance_headers, "finance-step"),
    "LEGAL": (make_legal_headers, "legal-step"),
    "GENERAL_MANAGER": (make_gm_headers, "gm-step"),
}


def stage_actor(stage: str, suffix: str) -> Dict[str, str]:
    """Build headers for a step actor with a stable per-step distinct id.

    PRD §2.8 priority 7 segregation-of-duties bars the same X-User-ID from
    appearing as decider on more than one ApprovalStep of the same PO, so
    the per-step suffix ensures every step has its own actor.
    """
    builder, prefix = _STAGE_HEADERS_BUILDER[stage]
    return builder(f"{prefix}-{suffix}")


def approve_all_serial(
    setup: Dict[str, Any],
    *,
    skip_stages: Optional[List[str]] = None,
    decision_comments: Optional[Dict[str, str]] = None,
    actor_suffix: str = "default",
) -> List[Dict[str, Any]]:
    """Approve every step on the PO in order (TIER_1 / TIER_2 / TIER_3 /
    TIER_4 routing all supported).

    PRD §3.3 routings:
      TIER_1: [DEPARTMENT_HEAD]
      TIER_2: [DEPARTMENT_HEAD, FINANCE] serial
      TIER_3/4: [DEPARTMENT_HEAD, {FINANCE | LEGAL parallel}, GENERAL_MANAGER]
    """
    skip_stages = skip_stages or []
    decision_comments = decision_comments or {}
    steps = list(setup["approval_steps"])

    decided: List[Dict[str, Any]] = []
    # Order: SERIAL then PARALLEL pairs then trailing SERIAL.
    # The simplest correct walk: department head first, then any
    # PARALLEL group, then GM.
    serial_first = [s for s in steps if s["mode"] == "SERIAL" and s["stage"] == "DEPARTMENT_HEAD"]
    parallel_group = [s for s in steps if s["mode"] == "PARALLEL"]
    serial_others = [
        s for s in steps
        if s["mode"] == "SERIAL" and s["stage"] != "DEPARTMENT_HEAD"
    ]
    # Within serial_others, preserve original order (FINANCE before GM).
    ordered: List[Dict[str, Any]] = serial_first + parallel_group + serial_others

    for step in ordered:
        if step["stage"] in skip_stages:
            continue
        headers = stage_actor(step["stage"], actor_suffix)
        comment = decision_comments.get(step["stage"])
        # PRD §3.3: "on a TIER_4 purchase order the final GENERAL_MANAGER
        # step's decision_comment is required". Provide a default so the
        # generic walker works for all tiers.
        if step["stage"] == "GENERAL_MANAGER" and comment is None:
            comment = "Approved at GM."
        d = approve_step_as(
            step["id"], role_headers=headers, decision_comment=comment
        )
        decided.append(d)
    return decided


def setup_approved_po(
    *,
    quote_specs: Optional[List[Tuple[int, float]]] = None,
    awarded_index: int = 0,
    quantity: int = 10,
    budget_total_cents: int = 100_000_000,
    category: str = "IT_HARDWARE",
    actor_suffix: str = "approved-po",
) -> Dict[str, Any]:
    """Walk PO from PENDING_APPROVAL -> APPROVED (PRD §3.3)."""
    setup = setup_awarded_po(
        quote_specs=quote_specs,
        awarded_index=awarded_index,
        quantity=quantity,
        budget_total_cents=budget_total_cents,
        category=category,
    )
    approve_all_serial(setup, actor_suffix=actor_suffix)
    # Refresh PO and steps to reflect new state.
    po = get_success_data(
        api_client.get_purchase_order(setup["po"]["id"], TEST_USERS["buyer_headers"])
    )
    steps = get_success_data(
        api_client.list_approval_steps(po["id"], TEST_USERS["buyer_headers"])
    )
    if isinstance(steps, dict):
        steps = steps.get("approval_steps") or steps.get("data") or []
    setup["po"] = po
    setup["approval_steps"] = steps
    return setup


# ===========================================================================
# Tier 5: Contract progression and execution
# ===========================================================================
def create_clause_template(
    *,
    code: Optional[str] = None,
    category: str = "PAYMENT",
    is_active_override: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a ClauseTemplate (PRD §3.6).

    is_active_override is unused at create-time (PRD §3.6: "is_active flag
    defaults to true") but kept as a parameter for future patch support.
    """
    payload = create_clause_template_payload(code=code, category=category)
    return get_success_data(
        api_client.create_clause_template(payload, TEST_USERS["legal_headers"])
    )


def create_contract_for(
    po: Dict[str, Any],
    *,
    payment_terms_type: str = "ON_DELIVERY",
    payment_terms_params: Optional[Dict[str, Any]] = None,
    parties_required: Optional[List[str]] = None,
    n_clauses: int = 1,
) -> Dict[str, Any]:
    """Create a Contract draft for an APPROVED PO (PRD §3.6)."""
    clauses = [create_clause_template() for _ in range(n_clauses)]
    payload = create_contract_payload(
        purchase_order_id=po["id"],
        clause_template_ids=[c["id"] for c in clauses],
        payment_terms_type=payment_terms_type,
        payment_terms_params=(
            payment_terms_params if payment_terms_params is not None else {}
        ),
        parties_required=parties_required or ["Buyer", "Supplier"],
    )
    return get_success_data(
        api_client.create_contract(payload, TEST_USERS["buyer_headers"])
    )


def submit_contract_review(contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_contract_for_review(
            contract_id, TEST_USERS["buyer_headers"]
        )
    )


def finalize_contract_review(contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.finalize_contract_review(
            contract_id, TEST_USERS["legal_headers"]
        )
    )


def buyer_signs(contract_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.sign_contract(
            contract_id,
            sign_contract_payload(role="Buyer"),
            TEST_USERS["buyer_headers"],
        )
    )


def supplier_signs(contract_id: str, supplier_id: str) -> Dict[str, Any]:
    """Sign as Supplier. PRD §3.6: "A Supplier party's X-User-ID must equal
    the supplier_id of the purchase order behind the contract" — identity
    threaded via make_supplier_headers(supplier_id)."""
    return get_success_data(
        api_client.sign_contract(
            contract_id,
            sign_contract_payload(role="Supplier"),
            make_supplier_headers(supplier_id),
        )
    )


def setup_executed_contract(
    *,
    payment_terms_type: str = "ON_DELIVERY",
    payment_terms_params: Optional[Dict[str, Any]] = None,
    quote_specs: Optional[List[Tuple[int, float]]] = None,
    quantity: int = 10,
    budget_total_cents: int = 100_000_000,
    actor_suffix: str = "exec-ctr",
) -> Dict[str, Any]:
    """Create budget+supplier+req+quote+award+approve all steps + contract
    + signatures -> EXECUTED. Cascades PO -> CONTRACTED + emits
    PaymentSchedule (PRD §3.6, §3.7)."""
    setup = setup_approved_po(
        quote_specs=quote_specs,
        quantity=quantity,
        budget_total_cents=budget_total_cents,
        actor_suffix=actor_suffix,
    )
    contract = create_contract_for(
        setup["po"],
        payment_terms_type=payment_terms_type,
        payment_terms_params=payment_terms_params,
    )
    submit_contract_review(contract["id"])
    finalize_contract_review(contract["id"])
    buyer_signs(contract["id"])
    supplier_signs(contract["id"], setup["po"]["supplier_id"])
    contract = get_success_data(
        api_client.get_contract(contract["id"], TEST_USERS["buyer_headers"])
    )
    po = get_success_data(
        api_client.get_purchase_order(setup["po"]["id"], TEST_USERS["buyer_headers"])
    )
    schedule = get_success_data(
        api_client.get_payment_schedule(po["id"], TEST_USERS["finance_headers"])
    )
    if isinstance(schedule, dict):
        schedule = (
            schedule.get("payment_schedule")
            or schedule.get("data")
            or schedule.get("entries")
            or []
        )
    setup["contract"] = contract
    setup["po"] = po
    setup["payment_schedule"] = schedule
    return setup


# ===========================================================================
# Tier 6: Receipt / delivery flow (PRD §3.8, §3.11)
# ===========================================================================
def post_supplier_delivery(
    po_id: str,
    *,
    delivery_note_no: Optional[str] = None,
    declared_quantity: int = 10,
) -> Dict[str, Any]:
    payload = supplier_delivery_payload(
        purchase_order_id=po_id,
        delivery_note_no=delivery_note_no or unique_delivery_note_no(),
        declared_quantity=declared_quantity,
    )
    res = get_success_data(
        api_client.supplier_delivery_event(
            payload, TEST_USERS["platform_admin_headers"]
        )
    )
    res["delivery_note_no"] = payload["delivery_note_no"]
    return res


def setup_receipt_in_inspecting(
    *,
    quote_specs: Optional[List[Tuple[int, float]]] = None,
    quantity: int = 10,
    received_quantity: int = 10,
    accepted_quantity: int = 10,
    quality_rating: float = 90.0,
    payment_terms_type: str = "ON_DELIVERY",
) -> Dict[str, Any]:
    """Walk to PO CONTRACTED + register supplier delivery + create
    Receipt + advance to INSPECTING (PRD §3.8)."""
    setup = setup_executed_contract(
        quote_specs=quote_specs,
        quantity=quantity,
        payment_terms_type=payment_terms_type,
    )
    delivery_note_no = unique_delivery_note_no()
    post_supplier_delivery(
        setup["po"]["id"],
        delivery_note_no=delivery_note_no,
        declared_quantity=received_quantity,
    )
    receipt = get_success_data(
        api_client.create_receipt(
            setup["po"]["id"],
            create_receipt_payload(
                delivery_note_no=delivery_note_no,
                received_quantity=received_quantity,
                accepted_quantity=accepted_quantity,
                quality_rating=quality_rating,
            ),
            TEST_USERS["inspector_headers"],
        )
    )
    receipt = get_success_data(
        api_client.inspect_receipt(receipt["id"], TEST_USERS["inspector_headers"])
    )
    setup["receipt"] = receipt
    setup["delivery_note_no"] = delivery_note_no
    return setup


def setup_receipts_for_invoice(
    *,
    quote_specs: Optional[List[Tuple[int, float]]] = None,
    quantity: int = 10,
    accepted_full: bool = True,
    quality_rating: float = 90.0,
    payment_terms_type: str = "ON_DELIVERY",
) -> Dict[str, Any]:
    """Walk all the way to PO FULFILLED (or partially-accepted CONTRACTED)
    so a downstream Invoice has receipts to match against (PRD §3.9)."""
    if quote_specs is None:
        quote_specs = [(100_000, 90.0), (110_000, 80.0), (120_000, 70.0)]
    accepted_qty = quantity if accepted_full else max(1, quantity // 2)
    setup = setup_receipt_in_inspecting(
        quote_specs=quote_specs,
        quantity=quantity,
        received_quantity=quantity,
        accepted_quantity=accepted_qty,
        quality_rating=quality_rating,
        payment_terms_type=payment_terms_type,
    )
    receipt = get_success_data(
        api_client.accept_receipt(
            setup["receipt"]["id"], TEST_USERS["inspector_headers"]
        )
    )
    setup["receipt"] = receipt
    setup["po"] = get_success_data(
        api_client.get_purchase_order(setup["po"]["id"], TEST_USERS["buyer_headers"])
    )
    return setup


# ===========================================================================
# Tier 7: Invoice / Payment flow (PRD §3.9, §3.10)
# ===========================================================================
def _compute_expected_tax_cents(
    invoiced_amount_cents: int, tax_rate_declared: float
) -> int:
    """Mirror PRD §3.9: expected tax = invoiced_amount_cents - round_half_up(
    invoiced_amount_cents / (1 + tax_rate_declared)) — to the nearest cent."""
    from decimal import Decimal, ROUND_HALF_UP

    rate = Decimal(str(tax_rate_declared))
    one_plus = Decimal("1") + rate
    if one_plus <= 0:
        return 0
    net = Decimal(invoiced_amount_cents) / one_plus
    tax_expected_decimal = Decimal(invoiced_amount_cents) - net
    return int(tax_expected_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def submit_invoice(
    *,
    po: Dict[str, Any],
    supplier_id: str,
    invoiced_quantity: int = 10,
    invoiced_amount_cents: int = 100_000,
    tax_amount_cents: Optional[int] = None,
    tax_rate_declared: float = 0.13,
    invoice_no: Optional[str] = None,
) -> Dict[str, Any]:
    """Supplier submits an invoice. PRD §2.1 ownership: X-User-ID must
    equal supplier_id, threaded via make_supplier_headers(supplier_id).

    When tax_amount_cents is None, the helper computes the value that
    sits at zero tax-delta against invoiced_amount_cents and
    tax_rate_declared, so callers that don't care about tax compliance
    can call submit_invoice without doing the math themselves."""
    if tax_amount_cents is None:
        tax_amount_cents = _compute_expected_tax_cents(
            invoiced_amount_cents, tax_rate_declared
        )
    payload = create_invoice_payload(
        purchase_order_id=po["id"],
        supplier_id=supplier_id,
        invoice_no=invoice_no or unique_invoice_no(),
        invoiced_quantity=invoiced_quantity,
        invoiced_amount_cents=invoiced_amount_cents,
        tax_amount_cents=tax_amount_cents,
        tax_rate_declared=tax_rate_declared,
    )
    return get_success_data(
        api_client.create_invoice(payload, make_supplier_headers(supplier_id))
    )


def setup_invoice_match_ready(
    *,
    quantity: int = 10,
    invoiced_quantity: Optional[int] = None,
    invoiced_amount_cents: Optional[int] = None,
    tax_amount_cents: Optional[int] = None,
    tax_rate_declared: float = 0.13,
    quote_specs: Optional[List[Tuple[int, float]]] = None,
    payment_terms_type: str = "ON_DELIVERY",
) -> Dict[str, Any]:
    """Walk to PO FULFILLED with Receipt accepted; submit Invoice ready for
    /invoices/{id}/match (PRD §3.9). When tax_amount_cents is None, it is
    computed from invoiced_amount_cents and tax_rate_declared so the
    default invoice is tax-compliant (PRD §3.9 expected-tax formula)."""
    if quote_specs is None:
        quote_specs = [(100_000, 90.0), (110_000, 80.0), (120_000, 70.0)]
    setup = setup_receipts_for_invoice(
        quote_specs=quote_specs,
        quantity=quantity,
        accepted_full=True,
        payment_terms_type=payment_terms_type,
    )
    if invoiced_quantity is None:
        invoiced_quantity = quantity
    if invoiced_amount_cents is None:
        # Default to the PO total (matches expected pro-rata exactly).
        invoiced_amount_cents = setup["po"]["total_amount_cents"]
    invoice = submit_invoice(
        po=setup["po"],
        supplier_id=setup["po"]["supplier_id"],
        invoiced_quantity=invoiced_quantity,
        invoiced_amount_cents=invoiced_amount_cents,
        tax_amount_cents=tax_amount_cents,
        tax_rate_declared=tax_rate_declared,
    )
    setup["invoice"] = invoice
    return setup


def match_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.match_invoice(invoice_id, TEST_USERS["finance_headers"])
    )


def approve_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_invoice(invoice_id, TEST_USERS["finance_headers"])
    )


def setup_invoice_approved(
    *,
    payment_terms_type: str = "ON_DELIVERY",
    quantity: int = 10,
    invoiced_amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Walk Invoice SUBMITTED -> MATCHED -> APPROVED (PRD §3.9)."""
    setup = setup_invoice_match_ready(
        quantity=quantity,
        invoiced_amount_cents=invoiced_amount_cents,
        payment_terms_type=payment_terms_type,
    )
    match_invoice(setup["invoice"]["id"])
    approve_invoice(setup["invoice"]["id"])
    setup["invoice"] = get_success_data(
        api_client.get_invoice(
            setup["invoice"]["id"], TEST_USERS["finance_headers"]
        )
    )
    return setup


def setup_payment_applied(
    *,
    payment_terms_type: str = "ON_DELIVERY",
    quantity: int = 10,
) -> Dict[str, Any]:
    """Walk all the way to a Payment in APPLIED status against the first
    PaymentSchedule entry (PRD §3.10)."""
    setup = setup_invoice_approved(
        payment_terms_type=payment_terms_type, quantity=quantity
    )
    schedule = setup["payment_schedule"]
    assert len(schedule) >= 1, "Expected payment schedule with at least 1 entry"
    first = schedule[0]
    payment = get_success_data(
        api_client.apply_payment(
            apply_payment_payload(
                payment_schedule_id=first["id"], invoice_id=setup["invoice"]["id"]
            ),
            TEST_USERS["finance_headers"],
        )
    )
    setup["payment"] = payment
    setup["schedule_entry"] = first
    return setup


# ===========================================================================
# Tier 8: Difficulty-design recipe-specific fixtures (SCAFFOLD_DIFFICULTY_DESIGN.yaml)
# ===========================================================================
def setup_tier3_po_with_two_serial_steps(
    *,
    actor_suffix: str = "tier3-prio",
) -> Dict[str, Any]:
    """For priority-conflict tests on TIER_2 (DEPT_HEAD, FINANCE serial)
    or TIER_3 (DEPT_HEAD, parallel FIN/LEGAL, GM). Returns a TIER_2 setup
    where DEPT_HEAD step is APPROVED by an actor distinct from the FINANCE
    step's PENDING assignee (PRD §3.3 routing).

    PO total chosen so total ∈ [TIER1_MAX, TIER2_MAX) → TIER_2.
    """
    # TIER_2 PO: total in [500000, 5000000). 100 quantity * 10000 = 1,000,000.
    quote_specs = [(10_000, 90.0), (12_000, 80.0), (15_000, 70.0)]
    setup = setup_awarded_po(
        quote_specs=quote_specs,
        quantity=100,
        budget_total_cents=10_000_000,
        actor_suffix=actor_suffix,
    )
    return setup


def setup_tier4_parallel_pending(
    *,
    actor_suffix: str = "tier4-pp",
) -> Dict[str, Any]:
    """TIER_3 / TIER_4 PO with DEPT_HEAD already approved; returns the
    setup with FINANCE+LEGAL parallel steps still PENDING and GM step
    PENDING (PRD §3.3 TIER_3/4 shape)."""
    # Choose total in TIER_3 range: [5,000,000, 50,000,000). qty=100 * 100,000 = 10,000,000.
    quote_specs = [(100_000, 90.0), (110_000, 80.0), (120_000, 70.0)]
    setup = setup_awarded_po(
        quote_specs=quote_specs,
        quantity=100,
        budget_total_cents=50_000_000,
        actor_suffix=actor_suffix,
    )
    # Approve only the DEPARTMENT_HEAD serial step.
    approve_all_serial(
        setup,
        skip_stages=["FINANCE", "LEGAL", "GENERAL_MANAGER"],
        actor_suffix=actor_suffix,
    )
    setup["approval_steps"] = get_success_data(
        api_client.list_approval_steps(
            setup["po"]["id"], TEST_USERS["buyer_headers"]
        )
    )
    if isinstance(setup["approval_steps"], dict):
        setup["approval_steps"] = (
            setup["approval_steps"].get("approval_steps")
            or setup["approval_steps"].get("data")
            or []
        )
    return setup


def setup_invoice_in_exception(
    *,
    quantity: int = 100,
) -> Dict[str, Any]:
    """Walk to a SUBMITTED Invoice that fails the strict three-way match
    on quantity tolerance and lands in EXCEPTION (PRD §3.9).

    PRD §3.9 says a failed match transitions the invoice to EXCEPTION
    while returning ERR_THREE_WAY_MATCH_FAILED (or ERR_TAX_NONCOMPLIANT)
    HTTP 422 — both effects in the same transaction. The fixture issues
    the call directly via api_client (NOT through match_invoice, which
    would raise on the 4xx) and then refreshes the invoice resource."""
    # PO total 11_300, 100 units (per-unit 113 cents).
    setup = setup_invoice_match_ready(
        quantity=quantity,
        # Per-unit is 113 cents; we set invoiced_quantity 90 (delta 0.10 > 0.02).
        invoiced_quantity=90,
        invoiced_amount_cents=10_170,
        tax_amount_cents=1_170,  # exact expected tax for 0.13 rate on 10170
        tax_rate_declared=0.13,
        # Use specific quote prices that yield total 11_300.
        quote_specs=[(113, 90.0), (130, 80.0), (140, 70.0)],
    )
    # Issue the match call; expect a 422 with ERR_THREE_WAY_MATCH_FAILED.
    # The implementation flips the invoice to EXCEPTION as a side effect.
    api_client.match_invoice(
        setup["invoice"]["id"], TEST_USERS["finance_headers"]
    )
    invoice = get_success_data(
        api_client.get_invoice(
            setup["invoice"]["id"], TEST_USERS["finance_headers"]
        )
    )
    setup["invoice"] = invoice
    return setup


__all__ = [
    "iso_z",
    "parse_iso",
    "add_seconds",
    "add_minutes",
    "add_hours",
    "add_days",
    "advance_clock",
    "DEFAULT_DELIVERY_DATE",
    "DEFAULT_QUALIFICATION_EXPIRES",
    "create_budget_account",
    "create_provisional_supplier",
    "create_qualified_supplier",
    "create_qualified_suppliers",
    "create_draft_requirement",
    "submit_requirement",
    "add_quote",
    "shortlist_quotes",
    "award_requirement",
    "setup_requirement_with_quotes",
    "setup_shortlisted_requirement",
    "setup_awarded_po",
    "approve_step_as",
    "reject_step_as",
    "stage_actor",
    "approve_all_serial",
    "setup_approved_po",
    "create_clause_template",
    "create_contract_for",
    "submit_contract_review",
    "finalize_contract_review",
    "buyer_signs",
    "supplier_signs",
    "setup_executed_contract",
    "post_supplier_delivery",
    "setup_receipt_in_inspecting",
    "setup_receipts_for_invoice",
    "submit_invoice",
    "setup_invoice_match_ready",
    "match_invoice",
    "approve_invoice",
    "setup_invoice_approved",
    "setup_payment_applied",
    "setup_tier3_po_with_two_serial_steps",
    "setup_tier4_parallel_pending",
    "setup_invoice_in_exception",
]
