"""Composite state builders and pytest fixtures.

The harness restarts the API server before every individual test, so each test
starts against an empty database and every piece of state it needs must be
built through the public API. The builders below assemble the multi-step
chains the contract requires — an OPEN programme, a supplier that has passed
both onboarding axes, a LIVE auction session, an ingested invoice, a NAMED /
ACCEPTED offer, a RESERVED / DEPLOYED / RELEASED early payment and a funder
with a committed capital tranche — so individual tests only carry the state
that is actually under test.

All setup calls go through ``get_success_data``, which accepts any 2xx and
raises a readable AssertionError naming the failing step.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .test_users import (
    PLATFORM_OPS_HEADERS,
    make_buyer_admin_headers,
    make_buyer_treasury_headers,
    make_funder_headers,
    make_supplier_headers,
)


class Ctx:
    """Mutable bag of the rows a scenario has built so far."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        keys = sorted(k for k in self.__dict__ if not k.startswith("_"))
        return "Ctx({})".format(", ".join(keys))

    # Convenience header accessors -------------------------------------
    @property
    def admin(self) -> Dict[str, str]:
        return make_buyer_admin_headers(self.buyer_id)

    @property
    def treasury(self) -> Dict[str, str]:
        return make_buyer_treasury_headers(self.buyer_id)

    @property
    def supplier_headers(self) -> Dict[str, str]:
        return make_supplier_headers(self.supplier_id)

    @property
    def funder_headers(self) -> Dict[str, str]:
        return make_funder_headers(self.funder_id)

    @property
    def ops(self) -> Dict[str, str]:
        return PLATFORM_OPS_HEADERS


# ─── Logical clock ────────────────────────────────────
def set_clock(current_utc: str) -> None:
    """Move the server's logical clock, running the five-step sweep."""
    resp = api_client.set_clock(current_utc, PLATFORM_OPS_HEADERS)
    assert 200 <= resp.status_code < 300, (
        "Setting the logical clock to {} failed with HTTP {}: {}".format(
            current_utc, resp.status_code, resp.text
        )
    )


# ─── Buyer / programme ────────────────────────────────
def new_buyer(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_buyer(f.buyer_payload(**overrides), PLATFORM_OPS_HEADERS)
    )


def new_program(buyer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_program(
            f.program_payload(buyer_id, **overrides),
            make_buyer_admin_headers(buyer_id),
        )
    )


def open_program(program_id: str, buyer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.open_program(program_id, make_buyer_admin_headers(buyer_id))
    )


def new_open_program(buyer_id: str, **overrides: Any) -> Dict[str, Any]:
    program = new_program(buyer_id, **overrides)
    return open_program(program["id"], buyer_id)


def set_program_status(program_id: str, buyer_id: str, action: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_program_status(
            program_id,
            f.program_status_payload(action),
            make_buyer_admin_headers(buyer_id),
        )
    )


# ─── Supplier onboarding ──────────────────────────────
def new_supplier(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_supplier(f.supplier_payload(**overrides), PLATFORM_OPS_HEADERS)
    )


def submit_onboarding(supplier_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_onboarding(supplier_id, make_supplier_headers(supplier_id))
    )


def add_bank_account(
    supplier_id: str, routing_number: str = "021000021", account_last4: str = "4321"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_bank_account(
            supplier_id,
            f.bank_account_payload(routing_number, account_last4),
            make_supplier_headers(supplier_id),
        )
    )


def confirm_micro_deposit(
    bank_account_id: str, supplier_id: str, code: str
) -> Dict[str, Any]:
    return get_success_data(
        api_client.confirm_micro_deposit(
            bank_account_id,
            f.micro_deposit_payload(code),
            make_supplier_headers(supplier_id),
        )
    )


def adjudicate_idv(
    supplier_id: str, decision: str = "PASSED", identity_score: Optional[int] = 90
) -> Dict[str, Any]:
    return get_success_data(
        api_client.adjudicate_idv(
            supplier_id, f.idv_payload(decision, identity_score), PLATFORM_OPS_HEADERS
        )
    )


def set_sanctions_hold(supplier_id: str, hold: bool) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_sanctions_hold(
            supplier_id, f.sanctions_hold_payload(hold), PLATFORM_OPS_HEADERS
        )
    )


def onboard_supplier(
    routing_number: str = "021000021",
    account_last4: str = "4321",
    identity_score: int = 90,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a supplier and drive both onboarding axes to completion so the
    fork-join fires and ``payment_ready_at`` is stamped."""
    supplier = new_supplier(**overrides)
    supplier_id = supplier["id"]
    submit_onboarding(supplier_id)
    bank = add_bank_account(supplier_id, routing_number, account_last4)
    confirm_micro_deposit(bank["id"], supplier_id, bank["micro_deposit_code"])
    active = adjudicate_idv(supplier_id, "PASSED", identity_score)
    active["bank_account_id"] = bank["id"]
    active["micro_deposit_code"] = bank["micro_deposit_code"]
    return active


# ─── Auction sessions ─────────────────────────────────
def new_session(
    program_id: str,
    buyer_id: str,
    opens_at: str = "2026-08-02T00:00:00Z",
    closes_at: str = "2026-08-31T00:00:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_session(
            f.session_payload(program_id, opens_at, closes_at),
            make_buyer_admin_headers(buyer_id),
        )
    )


def close_session(session_id: str, buyer_id: str, mode: str = "SETTLE") -> Dict[str, Any]:
    return get_success_data(
        api_client.close_session(
            session_id, f.session_close_payload(mode), make_buyer_admin_headers(buyer_id)
        )
    )


# ─── Payable-file ingestion ───────────────────────────
def ingest_file(
    program_id: str,
    buyer_id: str,
    rows: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_payable_file(
            f.payable_file_payload(program_id, rows, **overrides),
            make_buyer_admin_headers(buyer_id),
        )
    )


def invoices_of_file(
    file_id: str, buyer_id: str, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    resp = api_client.list_invoices(
        make_buyer_admin_headers(buyer_id), file_id=file_id, status=status
    )
    return get_success_data(resp)


def read_invoice(invoice_id: str, buyer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_invoice(invoice_id, make_buyer_admin_headers(buyer_id))
    )


# ─── Funders ──────────────────────────────────────────
def new_funder(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_funder(f.funder_payload(**overrides), PLATFORM_OPS_HEADERS)
    )


def add_commitment(funder_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_commitment(
            funder_id, f.commitment_payload(**overrides), make_funder_headers(funder_id)
        )
    )


def active_funder(
    committed_amount_cents: int = 60_000_000,
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_to: str = "2026-12-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A funder with one ACTIVE capital tranche already committed."""
    funder = new_funder(**overrides)
    tranche = add_commitment(
        funder["id"],
        committed_amount_cents=committed_amount_cents,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    funder["commitment_id"] = tranche["id"]
    return funder


def read_funder(funder_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_funder(funder_id, PLATFORM_OPS_HEADERS))


# ─── Offers ───────────────────────────────────────────
def name_offer(
    invoice_id: str,
    session_id: str,
    supplier_id: str,
    expected_invoice_version: int,
    offered_apr_bps: int = 900,
    requested_pay_date: str = "2026-08-05T00:00:00Z",
    acceptance_deadline: str = "2026-08-20T00:00:00Z",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_offer(
            f.offer_payload(
                invoice_id,
                session_id,
                expected_invoice_version,
                offered_apr_bps=offered_apr_bps,
                requested_pay_date=requested_pay_date,
                acceptance_deadline=acceptance_deadline,
            ),
            make_supplier_headers(supplier_id),
        )
    )


def accept_offer_as_buyer(offer_id: str, buyer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.accept_offer(offer_id, make_buyer_admin_headers(buyer_id))
    )


def accept_offer_as_supplier(offer_id: str, supplier_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.accept_offer(offer_id, make_supplier_headers(supplier_id))
    )


def read_offer(offer_id: str, buyer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_offer(offer_id, make_buyer_admin_headers(buyer_id))
    )


# ─── Early payments ───────────────────────────────────
def reserve_payment(
    offer_id: str, expected_offer_version: int, buyer_id: str
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_early_payment(
            f.early_payment_payload(offer_id, expected_offer_version),
            make_buyer_treasury_headers(buyer_id),
        )
    )


def execute_payment(payment_id: str, buyer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.execute_early_payment(
            payment_id, make_buyer_treasury_headers(buyer_id)
        )
    )


def confirm_settlement(payment_id: str, buyer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.confirm_settlement(payment_id, make_buyer_treasury_headers(buyer_id))
    )


def fail_settlement(
    payment_id: str,
    buyer_id: str,
    failure_reason: str = "Beneficiary bank returned the credit transfer",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.fail_settlement(
            payment_id,
            f.settlement_failure_payload(failure_reason),
            make_buyer_treasury_headers(buyer_id),
        )
    )


def read_payment(payment_id: str, buyer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_early_payment(payment_id, make_buyer_treasury_headers(buyer_id))
    )


# ─── Disputes ─────────────────────────────────────────
def raise_dispute(
    invoice_id: str,
    buyer_id: str,
    disputed_amount_cents: int,
    reason_code: str = "SHORT_SHIPMENT",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_dispute(
            invoice_id,
            f.dispute_payload(disputed_amount_cents, reason_code),
            make_buyer_admin_headers(buyer_id),
        )
    )


def resolve_dispute(
    dispute_id: str,
    buyer_id: str,
    resolution: str,
    resolution_note: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.resolve_dispute(
            dispute_id,
            f.dispute_resolution_payload(resolution, resolution_note),
            make_buyer_admin_headers(buyer_id),
        )
    )


# ─── Tier 1–5 composite scenario builders ─────────────
def build_base(
    clock: str = DEFAULT_CLOCK_UTC,
    buyer_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    open_the_program: bool = True,
    supplier_overrides: Optional[Dict[str, Any]] = None,
    onboard: bool = True,
    session_window: Optional[tuple] = ("2026-08-02T00:00:00Z", "2026-08-31T00:00:00Z"),
    funders: Optional[List[Dict[str, Any]]] = None,
) -> Ctx:
    """Tier 2 / tier 3 state: logical clock parked, buyer registered, programme
    created and optionally OPEN, one supplier optionally onboarded to ACTIVE,
    one auction session optionally scheduled, and any requested funders
    registered with their capital tranches.

    ``funders`` is a list of dicts; each may carry funder registration fields
    plus ``committed_amount_cents`` / ``effective_from`` / ``effective_to``.
    """
    set_clock(clock)

    buyer = new_buyer(**(buyer_overrides or {}))
    program = new_program(buyer["id"], **(program_overrides or {}))
    if open_the_program:
        program = open_program(program["id"], buyer["id"])

    supplier: Optional[Dict[str, Any]] = None
    if supplier_overrides is not None or onboard:
        if onboard:
            supplier = onboard_supplier(**(supplier_overrides or {}))
        else:
            supplier = new_supplier(**(supplier_overrides or {}))

    session: Optional[Dict[str, Any]] = None
    if session_window is not None:
        session = new_session(
            program["id"], buyer["id"], session_window[0], session_window[1]
        )

    funder_rows: List[Dict[str, Any]] = []
    for spec in funders or []:
        spec = dict(spec)
        tranche_keys = ("committed_amount_cents", "effective_from", "effective_to")
        tranche_args = {k: spec.pop(k) for k in tranche_keys if k in spec}
        funder_rows.append(active_funder(**tranche_args, **spec))

    ctx = Ctx(
        clock=clock,
        buyer=buyer,
        buyer_id=buyer["id"],
        program=program,
        program_id=program["id"],
        supplier=supplier,
        supplier_id=supplier["id"] if supplier else None,
        session=session,
        session_id=session["id"] if session else None,
        funders=funder_rows,
    )
    if funder_rows:
        ctx.funder = funder_rows[0]
        ctx.funder_id = funder_rows[0]["id"]
    return ctx


def ingest_rows(ctx: Ctx, rows: List[Dict[str, Any]], **overrides: Any) -> Ctx:
    """Tier 3 state: ingest one payable file into the scenario's programme."""
    payable_file = ingest_file(ctx.program_id, ctx.buyer_id, rows, **overrides)
    ctx.payable_file = payable_file
    ctx.file_id = payable_file["id"]
    return ctx


def load_invoices(ctx: Ctx, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read back the invoices of the scenario's ingested file, created_at ASC."""
    ctx.invoices = invoices_of_file(ctx.file_id, ctx.buyer_id, status=status)
    if ctx.invoices:
        ctx.invoice = ctx.invoices[0]
        ctx.invoice_id = ctx.invoices[0]["id"]
        ctx.invoice_version = ctx.invoices[0]["version"]
    return ctx.invoices


def build_eligible_invoice(
    face_cents: int = 100_000,
    tax_rate_bps: int = 0,
    net_due_date: str = "2026-09-30T00:00:00Z",
    approval_date: str = "2026-07-22T00:00:00Z",
    advance_clock_to: str = "2026-08-02T00:00:00Z",
    **base_kwargs: Any,
) -> Ctx:
    """Tier 3 state: an OPEN programme, an onboarded supplier, a LIVE session
    and exactly one ELIGIBLE single-line invoice of the requested face."""
    ctx = build_base(**base_kwargs)
    ingest_rows(
        ctx,
        [
            f.payable_row(
                ctx.supplier_id,
                approval_date=approval_date,
                net_due_date=net_due_date,
                line_amount_cents=face_cents,
                tax_rate_bps=tax_rate_bps,
            )
        ],
    )
    if advance_clock_to is not None:
        set_clock(advance_clock_to)
        ctx.clock = advance_clock_to
    load_invoices(ctx)
    return ctx


def build_named_offer(
    offered_apr_bps: int = 900,
    requested_pay_date: str = "2026-08-05T00:00:00Z",
    acceptance_deadline: str = "2026-08-20T00:00:00Z",
    **invoice_kwargs: Any,
) -> Ctx:
    """Tier 4 state: the invoice above now carries a NAMED offer."""
    ctx = build_eligible_invoice(**invoice_kwargs)
    ctx.offer = name_offer(
        ctx.invoice_id,
        ctx.session_id,
        ctx.supplier_id,
        ctx.invoice_version,
        offered_apr_bps=offered_apr_bps,
        requested_pay_date=requested_pay_date,
        acceptance_deadline=acceptance_deadline,
    )
    ctx.offer_id = ctx.offer["id"]
    return ctx


def build_accepted_offer(**offer_kwargs: Any) -> Ctx:
    """Tier 4 state: the offer is ACCEPTED and the invoice is AWARDED."""
    ctx = build_named_offer(**offer_kwargs)
    ctx.offer = accept_offer_as_buyer(ctx.offer_id, ctx.buyer_id)
    ctx.offer_version = ctx.offer["version"]
    return ctx


def build_reserved_payment(**offer_kwargs: Any) -> Ctx:
    """Tier 5 state: an EarlyPayment in RESERVED / UNSENT / UNCLASSIFIED."""
    ctx = build_accepted_offer(**offer_kwargs)
    ctx.payment = reserve_payment(ctx.offer_id, ctx.offer_version, ctx.buyer_id)
    ctx.payment_id = ctx.payment["id"]
    return ctx


def build_deployed_payment(
    execute_at: str = "2026-08-05T00:00:00Z", **offer_kwargs: Any
) -> Ctx:
    """Tier 5 state: the payment has been executed, so the funding axis is
    DEPLOYED, the settlement axis is REMITTED and a remittance advice exists."""
    ctx = build_reserved_payment(**offer_kwargs)
    set_clock(execute_at)
    ctx.clock = execute_at
    ctx.payment = execute_payment(ctx.payment_id, ctx.buyer_id)
    return ctx


def build_released_payment(
    execute_at: str = "2026-08-05T00:00:00Z",
    confirm_at: str = "2026-08-07T00:00:00Z",
    **offer_kwargs: Any,
) -> Ctx:
    """Terminal tier 5 state: settlement CONFIRMED, funding RELEASED and the
    invoice EARLY_PAID with its true-up booked."""
    ctx = build_deployed_payment(execute_at=execute_at, **offer_kwargs)
    set_clock(confirm_at)
    ctx.clock = confirm_at
    ctx.payment = confirm_settlement(ctx.payment_id, ctx.buyer_id)
    return ctx


# ─── pytest fixtures over the canonical chains ────────
@pytest.fixture
def api():
    """The endpoint-per-method client (module singleton)."""
    return api_client


@pytest.fixture
def ops_headers():
    return PLATFORM_OPS_HEADERS


@pytest.fixture
def clock_at_default():
    """Park the logical clock on its documented startup default."""
    set_clock(DEFAULT_CLOCK_UTC)
    return DEFAULT_CLOCK_UTC


@pytest.fixture
def base_program():
    """An OPEN SELF_ONLY programme on a well-capitalised buyer, one ACTIVE
    supplier and one LIVE-capable session, clock still at the default."""
    return build_base()


@pytest.fixture
def eligible_invoice():
    """One ELIGIBLE invoice of face 100000 inside a LIVE session."""
    return build_eligible_invoice()


@pytest.fixture
def named_offer():
    """One NAMED offer at 900 bps on that invoice."""
    return build_named_offer()


@pytest.fixture
def accepted_offer():
    """That offer ACCEPTED, so the invoice is AWARDED."""
    return build_accepted_offer()


@pytest.fixture
def reserved_payment():
    """A RESERVED early payment on the accepted offer."""
    return build_reserved_payment()


@pytest.fixture
def deployed_payment():
    """A DEPLOYED / REMITTED early payment executed at 2026-08-05."""
    return build_deployed_payment()
