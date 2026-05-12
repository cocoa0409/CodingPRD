"""Composite setup helpers for multi-step test prerequisites.

The cross-border customs PRD requires 5–15 API calls to reach most
testable states (e.g., a Declaration in RELEASED requires reference data
+ counterparties + order + draft + line + submit + start_review + approve
+ confirm_payment). The helpers below encapsulate those preambles.

Identity threading rule (PRD §2.1):
- Declarant is entity-backed: ownership-gated calls (declaration create/
  submit/amend, line add, query respond, refund create/submit, order
  create) MUST use make_declarant_headers(declarant['id']).
- Importer is entity-backed: ownership-gated calls (cancel order, return
  order) MUST use make_importer_headers(importer['id']).

Setup helpers therefore mint the entity, then carry its id forward in
the headers used for subsequent ownership-gated calls. They use
get_success_data() (lenient validator) so a setup miss surfaces as
"setup failed" rather than masquerading as an assertion failure inside
the test.
"""
from __future__ import annotations
import itertools
import uuid
from typing import Any, Dict, List, Optional, Tuple


# Per-setup unique currency code generator. PRD §3.1 declares
# (from_currency, to_currency, effective_date) unique across the rate
# table. Test setups repeatedly need fresh USD->CNY rates with the same
# effective_date; without per-setup uniqueness, the second create
# correctly trips ERR_INVALID_REQUEST. We therefore mint a fresh
# 3-char "currency" code per setup so each setup's rate row is unique.
# The PRD does not constrain currency to ISO 4217 specifically (it says
# "ISO 4217" descriptively but the API accepts any 3-char code).
_currency_counter = itertools.count(start=1)


def _fresh_currency_code() -> str:
    """Return a fresh 3-char currency code for a single test setup."""
    n = next(_currency_counter)
    # Map n to a 3-char alphabetic code, e.g., 1 -> "AAA", 2 -> "AAB" ...
    # 26^3 = 17576 codes, enough for any test session.
    a = (n - 1) % 26
    b = ((n - 1) // 26) % 26
    c = ((n - 1) // (26 * 26)) % 26
    return chr(ord("A") + c) + chr(ord("A") + b) + chr(ord("A") + a)

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_declarant_payload,
    create_declaration_line_payload,
    create_declaration_payload,
    create_exchange_rate_payload,
    create_hs_code_payload,
    create_importer_payload,
    create_order_payload,
    create_refund_payload,
    create_tariff_rule_payload,
    confirm_payment_payload,
    make_line_item,
    open_query_payload,
    reject_declaration_payload,
    reject_refund_payload,
    respond_query_payload,
    reverse_payment_payload,
    schedule_inspection_payload,
)
from .test_users import (
    TEST_USERS,
    make_customs_officer_headers,
    make_declarant_headers,
    make_finance_officer_headers,
    make_importer_headers,
)


# ---------------------------------------------------------------------------
# Idempotency-key helper.
# ---------------------------------------------------------------------------
def fresh_idempotency_key(prefix: str = "k") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Reference-data fixtures.
# ---------------------------------------------------------------------------
def create_hs_code(
    *,
    tariff_rate_bps: int = 500,
    vat_rate_bps: int = 1300,
    consumption_tax_rate_bps: int = 0,
    postal_tax_rate_bps: int = 1000,
    keywords: Optional[List[str]] = None,
    description: str = "test commodity",
    **overrides,
) -> Dict[str, Any]:
    payload = create_hs_code_payload(
        tariff_rate_bps=tariff_rate_bps,
        vat_rate_bps=vat_rate_bps,
        consumption_tax_rate_bps=consumption_tax_rate_bps,
        postal_tax_rate_bps=postal_tax_rate_bps,
        description=description,
        **({"keywords": keywords} if keywords is not None else {}),
        **overrides,
    )
    res = api_client.create_hs_code(
        payload, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def deprecate_hs_code(hs_code_id: str) -> Dict[str, Any]:
    res = api_client.deprecate_hs_code(
        hs_code_id, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def create_tariff_rule(
    hs_code_id: str,
    *,
    origin_country: str = "US",
    destination_country: str = "CN",
    tariff_rate_bps: int = 500,
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_to: Optional[str] = "2026-12-31T23:59:59Z",
) -> Dict[str, Any]:
    payload = create_tariff_rule_payload(
        hs_code_id,
        origin_country=origin_country,
        destination_country=destination_country,
        tariff_rate_bps=tariff_rate_bps,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    res = api_client.create_tariff_rule(
        payload, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def create_exchange_rate(
    *,
    from_currency: str = "USD",
    to_currency: str = "CNY",
    rate_micros: int = 7_000_000,
    effective_date: str = "2026-01-01",
) -> Dict[str, Any]:
    payload = create_exchange_rate_payload(
        from_currency=from_currency,
        to_currency=to_currency,
        rate_micros=rate_micros,
        effective_date=effective_date,
    )
    res = api_client.create_exchange_rate(
        payload, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Counterparty fixtures.
# ---------------------------------------------------------------------------
def create_importer(**overrides) -> Dict[str, Any]:
    payload = create_importer_payload(**overrides)
    res = api_client.create_importer(
        payload, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def suspend_importer(importer_id: str) -> Dict[str, Any]:
    res = api_client.suspend_importer(
        importer_id, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def create_declarant(**overrides) -> Dict[str, Any]:
    payload = create_declarant_payload(**overrides)
    res = api_client.create_declarant(
        payload, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Reference-data bundle: rate + currency + (optionally) tariff rule on a
# brand-new HsCode. Used as the foundation for declaration scenarios.
# ---------------------------------------------------------------------------
def setup_reference_data(
    *,
    rate_micros: int = 7_000_000,
    rate_effective_date: str = "2026-01-01",
    from_currency: str = "USD",
    to_currency: str = "CNY",
    hs_code_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Mint exchange rate + one HsCode. Returns
    {'exchange_rate', 'hs_code'} so callers can reference each part.

    No tariff rule is published by default — the HsCode's own
    tariff_rate_bps is the fallback per PRD §3.1.
    """
    rate = create_exchange_rate(
        from_currency=from_currency,
        to_currency=to_currency,
        rate_micros=rate_micros,
        effective_date=rate_effective_date,
    )
    hs_kwargs = hs_code_overrides or {}
    hs = create_hs_code(**hs_kwargs)
    return {"exchange_rate": rate, "hs_code": hs}


# ---------------------------------------------------------------------------
# Order / Declaration drafting fixtures.
# ---------------------------------------------------------------------------
def create_party_pair() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Convenience: an active Importer + an active Declarant."""
    importer = create_importer()
    declarant = create_declarant()
    return importer, declarant


def create_order(
    importer: Dict[str, Any],
    declarant: Dict[str, Any],
    *,
    trade_mode: str = "GENERAL_TRADE",
    line_items: Optional[List[Dict[str, Any]]] = None,
    currency: str = "USD",
    origin_country: str = "US",
    destination_country: str = "CN",
    **overrides,
) -> Dict[str, Any]:
    """Create an Order on behalf of `importer`, by `declarant`.

    Identity threading: order creation is exclusive to the Declarant role
    (PRD §4 / §1.7). We use make_declarant_headers(declarant['id']) so the
    server's RBAC can resolve the acting Declarant.
    """
    payload = create_order_payload(
        importer["id"],
        declarant["id"],
        trade_mode=trade_mode,
        line_items=line_items,
        currency=currency,
        origin_country=origin_country,
        destination_country=destination_country,
        **overrides,
    )
    res = api_client.create_order(
        payload, make_declarant_headers(declarant["id"])
    )
    return get_success_data(res)


def create_draft_declaration(
    order: Dict[str, Any],
    declarant: Dict[str, Any],
    *,
    dutiable_value_method: str = "TRANSACTION_VALUE",
    importer_id_card_number: Optional[str] = None,
    bonded_zone_code: Optional[str] = None,
    contract_number: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_declaration_payload(
        order["id"],
        dutiable_value_method=dutiable_value_method,
        trade_mode=order["trade_mode"],
        importer_id_card_number=importer_id_card_number,
        bonded_zone_code=bonded_zone_code,
        contract_number=contract_number,
    )
    res = api_client.create_declaration(
        payload, make_declarant_headers(declarant["id"])
    )
    return get_success_data(res)


def add_line(
    declaration: Dict[str, Any],
    declarant: Dict[str, Any],
    *,
    order_line_index: int = 0,
    hs_code_id: str,
    classification_source: str = "AUTO_SUGGESTED",
) -> Dict[str, Any]:
    payload = create_declaration_line_payload(
        order_line_index=order_line_index,
        hs_code_id=hs_code_id,
        classification_source=classification_source,
    )
    res = api_client.add_declaration_line(
        declaration["id"],
        payload,
        make_declarant_headers(declarant["id"]),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# State-machine progression helpers.
# ---------------------------------------------------------------------------
def submit_declaration(
    declaration: Dict[str, Any], declarant: Dict[str, Any]
) -> Dict[str, Any]:
    res = api_client.submit_declaration(
        declaration["id"], make_declarant_headers(declarant["id"])
    )
    return get_success_data(res)


def start_review(declaration: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.start_review_declaration(
        declaration["id"], TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def approve_declaration(declaration: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.approve_declaration(
        declaration["id"], TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def reject_declaration(
    declaration: Dict[str, Any], reason: str = "documentation incomplete"
) -> Dict[str, Any]:
    payload = reject_declaration_payload(reason)
    res = api_client.reject_declaration(
        declaration["id"], payload, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def get_declaration(declaration_id: str) -> Dict[str, Any]:
    res = api_client.get_declaration(
        declaration_id, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def get_payment_notice(notice_id: str) -> Dict[str, Any]:
    res = api_client.get_payment_notice(
        notice_id, TEST_USERS["finance_officer_headers"]
    )
    return get_success_data(res)


def get_order(order_id: str) -> Dict[str, Any]:
    res = api_client.get_order(
        order_id, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def get_refund(refund_id: str) -> Dict[str, Any]:
    res = api_client.get_refund(
        refund_id, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Payment helpers.
# ---------------------------------------------------------------------------
def find_payment_notice_for_declaration(
    declaration_id: str,
) -> Optional[Dict[str, Any]]:
    """The PRD does not define a list endpoint for payment notices; on
    declaration approval the notice is auto-created. The simplest way to
    discover its id is to inspect the declaration response or to look up
    via audit events. We rely on tests that call approve_declaration and
    capture the returned declaration's payment_notice_id (when exposed) —
    if not, callers must pass the notice id forward explicitly. To keep
    the helper robust we let callers pass the notice id directly.
    """
    return None


def confirm_payment(
    notice_id: str,
    *,
    payment_channel: str = "ELECTRONIC_PAYMENT",
    voucher_url: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Confirm the payment notice. PRD §2.8 requires the Idempotency-Key
    HTTP header AND a matching idempotency_key body field; we set both
    here from a single value.
    """
    if idempotency_key is None:
        idempotency_key = fresh_idempotency_key()
    body = confirm_payment_payload(
        payment_channel=payment_channel,
        voucher_url=voucher_url,
        idempotency_key=idempotency_key,
    )
    base_headers = (
        dict(headers) if headers is not None
        else dict(TEST_USERS["finance_officer_headers"])
    )
    base_headers["Idempotency-Key"] = idempotency_key
    res = api_client.confirm_payment(notice_id, body, base_headers)
    return get_success_data(res)


def reverse_payment(
    notice_id: str, reason: str = "bank_dispute"
) -> Dict[str, Any]:
    res = api_client.reverse_payment(
        notice_id,
        reverse_payment_payload(reason),
        TEST_USERS["finance_officer_headers"],
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Inspection helpers.
# ---------------------------------------------------------------------------
def schedule_inspection(
    declaration_id: str,
    *,
    scheduled_at: str = "2026-02-01T10:00:00Z",
    bay_code: str = "BAY-A1",
) -> Dict[str, Any]:
    res = api_client.schedule_inspection(
        declaration_id,
        schedule_inspection_payload(
            scheduled_at=scheduled_at, bay_code=bay_code
        ),
        TEST_USERS["customs_officer_headers"],
    )
    return get_success_data(res)


def complete_inspection(appointment_id: str) -> Dict[str, Any]:
    res = api_client.complete_inspection(
        appointment_id, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Query helpers.
# ---------------------------------------------------------------------------
def open_query(
    declaration_id: str,
    *,
    question: str = "Please provide additional documents.",
    required_documents: Optional[List[str]] = None,
) -> Dict[str, Any]:
    res = api_client.open_query(
        declaration_id,
        open_query_payload(
            question=question, required_documents=required_documents
        ),
        TEST_USERS["customs_officer_headers"],
    )
    return get_success_data(res)


def respond_to_query(
    query_id: str,
    declarant: Dict[str, Any],
    *,
    response_text: str = "See attached.",
    response_documents: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    res = api_client.respond_query(
        query_id,
        respond_query_payload(
            response_text=response_text,
            response_documents=response_documents,
        ),
        make_declarant_headers(declarant["id"]),
    )
    return get_success_data(res)


def resolve_query(query_id: str) -> Dict[str, Any]:
    res = api_client.resolve_query(
        query_id, TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Refund helpers.
# ---------------------------------------------------------------------------
def create_refund(
    declaration: Dict[str, Any],
    declarant: Dict[str, Any],
    *,
    refund_reason: str,
    supporting_documents: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    payload = create_refund_payload(
        declaration["id"],
        refund_reason=refund_reason,
        supporting_documents=supporting_documents,
    )
    res = api_client.create_refund(
        payload, make_declarant_headers(declarant["id"])
    )
    return get_success_data(res)


def submit_refund(
    refund: Dict[str, Any], declarant: Dict[str, Any]
) -> Dict[str, Any]:
    res = api_client.submit_refund(
        refund["id"], make_declarant_headers(declarant["id"])
    )
    return get_success_data(res)


def approve_refund(refund: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.approve_refund(
        refund["id"], TEST_USERS["customs_officer_headers"]
    )
    return get_success_data(res)


def reject_refund(
    refund: Dict[str, Any], reason: str = "insufficient evidence"
) -> Dict[str, Any]:
    res = api_client.reject_refund(
        refund["id"],
        reject_refund_payload(reason),
        TEST_USERS["customs_officer_headers"],
    )
    return get_success_data(res)


def execute_refund(refund: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.execute_refund(
        refund["id"], TEST_USERS["finance_officer_headers"]
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Composite multi-step setups (Tier 2-5).
# ---------------------------------------------------------------------------
class DeclarationContext:
    """Bundle of objects that downstream tests need to act on a declaration.

    Attributes:
      importer, declarant: counterparty entities
      ref: reference-data dict {'exchange_rate', 'hs_code'}
      order: the parent order
      declaration: the declaration in its current state
      lines: list of DeclarationLine dicts that have been added
      payment_notice: set after approve(); None before
    """

    def __init__(
        self,
        importer: Dict[str, Any],
        declarant: Dict[str, Any],
        ref: Dict[str, Any],
        order: Dict[str, Any],
        declaration: Dict[str, Any],
        lines: Optional[List[Dict[str, Any]]] = None,
    ):
        self.importer = importer
        self.declarant = declarant
        self.ref = ref
        self.order = order
        self.declaration = declaration
        self.lines = lines if lines is not None else []
        self.payment_notice: Optional[Dict[str, Any]] = None

    @property
    def declarant_headers(self) -> Dict[str, str]:
        return make_declarant_headers(self.declarant["id"])

    @property
    def importer_headers(self) -> Dict[str, str]:
        return make_importer_headers(self.importer["id"])

    def refresh_declaration(self) -> Dict[str, Any]:
        self.declaration = get_declaration(self.declaration["id"])
        return self.declaration

    def refresh_order(self) -> Dict[str, Any]:
        self.order = get_order(self.order["id"])
        return self.order

    def refresh_payment_notice(self) -> Optional[Dict[str, Any]]:
        if self.payment_notice is None:
            return None
        self.payment_notice = get_payment_notice(self.payment_notice["id"])
        return self.payment_notice


def setup_draft_declaration(
    *,
    trade_mode: str = "GENERAL_TRADE",
    dutiable_value_method: str = "TRANSACTION_VALUE",
    line_items: Optional[List[Dict[str, Any]]] = None,
    currency: str = "USD",
    origin_country: str = "US",
    destination_country: str = "CN",
    rate_micros: int = 7_000_000,
    rate_effective_date: str = "2026-01-01",
    hs_code_overrides: Optional[Dict[str, Any]] = None,
    add_lines: bool = True,
    classification_source: str = "AUTO_SUGGESTED",
) -> DeclarationContext:
    """Reference data + counterparties + Order + DRAFT Declaration with
    one HsCode-pointed line per order line.

    The Order has `line_items` (default: a single 1-quantity 10000-cent
    line at 1.0 kg) and the Declaration has matching DeclarationLines
    targeting the freshly created HsCode. Exchange rate is published for
    the order currency so submission can pin a date.

    Currency-isolation note: PRD §3.1 declares (from_currency,
    to_currency, effective_date) unique across the rate table. So that
    parallel test setups don't collide on that uniqueness, we mint a
    fresh 3-char currency code per setup and use it for both the
    exchange rate and the order currency. The caller-supplied
    `currency` argument is accepted for API symmetry but ignored —
    tests that need a specific currency-pinning rate publish their own
    rate via `create_exchange_rate(...)` directly.
    """
    importer, declarant = create_party_pair()
    fresh_currency = _fresh_currency_code()
    ref = setup_reference_data(
        rate_micros=rate_micros,
        rate_effective_date=rate_effective_date,
        from_currency=fresh_currency,
        to_currency="CNY",
        hs_code_overrides=hs_code_overrides,
    )
    if line_items is None:
        line_items = [make_line_item()]
    order = create_order(
        importer,
        declarant,
        trade_mode=trade_mode,
        line_items=line_items,
        currency=fresh_currency,
        origin_country=origin_country,
        destination_country=destination_country,
    )
    declaration = create_draft_declaration(
        order, declarant, dutiable_value_method=dutiable_value_method
    )
    lines: List[Dict[str, Any]] = []
    if add_lines:
        for idx, _ in enumerate(line_items):
            line = add_line(
                declaration,
                declarant,
                order_line_index=idx,
                hs_code_id=ref["hs_code"]["id"],
                classification_source=classification_source,
            )
            lines.append(line)
    ctx = DeclarationContext(
        importer, declarant, ref, order, declaration, lines
    )
    return ctx


def setup_under_review_declaration(**kwargs) -> DeclarationContext:
    """Drafted → submitted → start_review."""
    ctx = setup_draft_declaration(**kwargs)
    ctx.declaration = submit_declaration(ctx.declaration, ctx.declarant)
    ctx.declaration = start_review(ctx.declaration)
    return ctx


def setup_approved_declaration(**kwargs) -> DeclarationContext:
    """Drafted → submitted → start_review → approved.

    On approval the server auto-creates a PaymentNotice. We discover the
    notice id by scanning audit events filtered by
    subject_type=PAYMENT_NOTICE.
    """
    ctx = setup_under_review_declaration(**kwargs)
    ctx.declaration = approve_declaration(ctx.declaration)
    # Some implementations expose payment_notice_id directly on the
    # declaration response after approval; honor it if present.
    notice_id = ctx.declaration.get("payment_notice_id")
    notice: Optional[Dict[str, Any]] = None
    if isinstance(notice_id, str):
        notice_res = api_client.get_payment_notice(
            notice_id, TEST_USERS["finance_officer_headers"]
        )
        if notice_res.status_code < 400:
            notice = get_success_data(notice_res)
    if notice is None:
        notice = _discover_notice_for_declaration(ctx.declaration["id"])
    ctx.payment_notice = notice
    return ctx


def _discover_notice_for_declaration(
    declaration_id: str,
) -> Optional[Dict[str, Any]]:
    """Pull the auto-generated PaymentNotice id from audit events.

    PRD §3.8 says approval auto-creates the PaymentNotice and §3.7
    requires a `DECLARATION_STATUS_CHANGE` audit event on approval.
    The PRD does not commit to a separate PAYMENT_NOTICE-subject
    audit event at creation, so we look at the declaration's own
    audit events and scan their `after_value` payload for any field
    that names the notice id (commonly `payment_notice_id`). As a
    last resort we scan PAYMENT_NOTICE-subject events and walk each
    candidate via GET /payment_notices/{id} confirming
    declaration_id == ours.
    """
    fin_hdr = TEST_USERS["finance_officer_headers"]
    co_hdr = TEST_USERS["customs_officer_headers"]

    # 1) Look at the declaration's own audit trail for any field that
    #    names the payment notice id.
    res = api_client.list_audit_events(
        co_hdr,
        params={
            "subject_type": "DECLARATION",
            "subject_id": declaration_id,
            "limit": 100,
        },
    )
    if res.status_code < 400:
        body = res.json() if hasattr(res, "json") else {}
        events = body.get("data", []) if isinstance(body, dict) else []
        if isinstance(events, list):
            for ev in events:
                for k in ("after_value", "before_value"):
                    v = ev.get(k) or {}
                    if not isinstance(v, dict):
                        continue
                    for key, val in v.items():
                        if "payment_notice" in key.lower() and isinstance(val, str):
                            notice_res = api_client.get_payment_notice(val, fin_hdr)
                            if notice_res.status_code < 400:
                                notice = get_success_data(notice_res)
                                if notice.get("declaration_id") == declaration_id:
                                    return notice

    # 2) Fall back: scan PAYMENT_NOTICE-subject audit events and
    #    confirm via GET /payment_notices/{id}.
    res = api_client.list_audit_events(
        co_hdr,
        params={"subject_type": "PAYMENT_NOTICE", "limit": 100},
    )
    if res.status_code >= 400:
        return None
    body = res.json() if hasattr(res, "json") else {}
    events = body.get("data", []) if isinstance(body, dict) else []
    if not isinstance(events, list):
        return None
    seen: List[str] = []
    for ev in events:
        sid = ev.get("subject_id")
        if isinstance(sid, str) and sid not in seen:
            seen.append(sid)
    direct_link: List[str] = []
    for ev in events:
        for k in ("after_value", "before_value"):
            v = ev.get(k) or {}
            if isinstance(v, dict) and v.get("declaration_id") == declaration_id:
                sid = ev.get("subject_id")
                if isinstance(sid, str) and sid not in direct_link:
                    direct_link.append(sid)
    candidates = direct_link or seen
    for sid in reversed(candidates):
        notice_res = api_client.get_payment_notice(sid, fin_hdr)
        if notice_res.status_code >= 400:
            continue
        notice = get_success_data(notice_res)
        if notice.get("declaration_id") == declaration_id:
            return notice
    return None


def setup_released_declaration(
    *,
    payment_channel: str = "ELECTRONIC_PAYMENT",
    voucher_url: Optional[str] = None,
    **kwargs,
) -> DeclarationContext:
    """Drafted → submitted → start_review → approved → confirm_payment →
    declaration RELEASED, order RELEASED.
    """
    ctx = setup_approved_declaration(**kwargs)
    assert ctx.payment_notice is not None, (
        "setup_released_declaration: failed to discover PaymentNotice "
        "auto-created on approval"
    )
    ctx.payment_notice = confirm_payment(
        ctx.payment_notice["id"],
        payment_channel=payment_channel,
        voucher_url=voucher_url,
    )
    ctx.refresh_declaration()
    ctx.refresh_order()
    return ctx


def setup_amended_declaration(**kwargs) -> DeclarationContext:
    """Reach RELEASED, then file an amendment so declaration is AMENDED.

    Amendment leaves the line set unchanged (empty `lines: []`) so taxes
    recompute identically; tests can override by re-amending themselves.
    """
    ctx = setup_released_declaration(**kwargs)
    res = api_client.amend_declaration(
        ctx.declaration["id"],
        {"lines": []},
        make_declarant_headers(ctx.declarant["id"]),
    )
    ctx.declaration = get_success_data(res)
    return ctx


def setup_returned_order_with_paid_declaration(
    **kwargs,
) -> DeclarationContext:
    """Released declaration whose Order has been transitioned to RETURNED.

    Used as the precondition for RETURN-reason refund tests
    (cross-entity guard, ERR_ORDER_NOT_ELIGIBLE).
    """
    ctx = setup_released_declaration(**kwargs)
    res = api_client.return_order(
        ctx.order["id"], make_importer_headers(ctx.importer["id"])
    )
    ctx.order = get_success_data(res)
    return ctx


# ---------------------------------------------------------------------------
# Calibrated tax-fixture: build an order whose post-submit
# dutiable_value_cny_minor and total_tax_cny_minor we can predict at the
# fen, suitable for boundary tests.
# ---------------------------------------------------------------------------
def setup_personal_postal_at_dutiable(
    target_dutiable_cny_minor: int,
    *,
    postal_tax_rate_bps: int = 1000,
) -> DeclarationContext:
    """Build a B2C_DIRECT_MAIL declaration whose post-submit
    dutiable_value_cny_minor equals exactly `target_dutiable_cny_minor`.

    Achieved by:
      - Setting the exchange rate to 1:1 (rate_micros=1_000_000) so the
        per-line CNY contribution equals line_value_minor in transaction
        method;
      - One line, quantity=1, unit_price=target_dutiable_cny_minor,
        weight_kg=1.0;
      - HsCode with given postal_tax_rate_bps; tariff/vat/consumption=0
        (PERSONAL_POSTAL mode zeroes those anyway).
    Boundaries:
      - target == 500000 → tax_mode=PERSONAL_POSTAL (inclusive).
      - target == 500001 → tax_mode=STANDARD.
    """
    return setup_draft_declaration(
        trade_mode="B2C_DIRECT_MAIL",
        dutiable_value_method="TRANSACTION_VALUE",
        line_items=[
            make_line_item(
                quantity=1,
                unit_price=target_dutiable_cny_minor,
                weight_kg=1.0,
            )
        ],
        currency="USD",
        rate_micros=1_000_000,
        rate_effective_date="2026-01-01",
        hs_code_overrides={
            "tariff_rate_bps": 1000,
            "vat_rate_bps": 0,
            "consumption_tax_rate_bps": 0,
            "postal_tax_rate_bps": postal_tax_rate_bps,
        },
    )


def setup_two_inspection_appointments_ready() -> Tuple[
    DeclarationContext, DeclarationContext
]:
    """Two distinct UNDER_REVIEW declarations (each with their own
    importer + declarant + order) so tests can schedule appointments on
    the same bay across them.
    """
    ctx_a = setup_under_review_declaration()
    ctx_b = setup_under_review_declaration()
    return ctx_a, ctx_b


# ---------------------------------------------------------------------------
# Cascade-sentinel: declaration in APPROVED with a known PaymentNotice
# id, ready for confirm/reverse cascade tests.
# ---------------------------------------------------------------------------
def setup_paid_then_reversed(
    **kwargs,
) -> DeclarationContext:
    """RELEASED via confirm_payment, then reverse → notice REVERSED,
    declaration reverts to APPROVED, order back to DECLARED.
    """
    ctx = setup_released_declaration(**kwargs)
    ctx.payment_notice = reverse_payment(ctx.payment_notice["id"])
    ctx.refresh_declaration()
    ctx.refresh_order()
    return ctx


__all__ = [
    "fresh_idempotency_key",
    # Reference data
    "create_hs_code",
    "deprecate_hs_code",
    "create_tariff_rule",
    "create_exchange_rate",
    "setup_reference_data",
    # Counterparties
    "create_importer",
    "suspend_importer",
    "create_declarant",
    "create_party_pair",
    # Orders / declarations
    "create_order",
    "create_draft_declaration",
    "add_line",
    "submit_declaration",
    "start_review",
    "approve_declaration",
    "reject_declaration",
    "get_declaration",
    "get_order",
    "get_payment_notice",
    "get_refund",
    # Payment
    "confirm_payment",
    "reverse_payment",
    # Inspection
    "schedule_inspection",
    "complete_inspection",
    # Query
    "open_query",
    "respond_to_query",
    "resolve_query",
    # Refund
    "create_refund",
    "submit_refund",
    "approve_refund",
    "reject_refund",
    "execute_refund",
    # Composite
    "DeclarationContext",
    "setup_draft_declaration",
    "setup_under_review_declaration",
    "setup_approved_declaration",
    "setup_released_declaration",
    "setup_amended_declaration",
    "setup_returned_order_with_paid_declaration",
    "setup_personal_postal_at_dutiable",
    "setup_two_inspection_appointments_ready",
    "setup_paid_then_reversed",
]
