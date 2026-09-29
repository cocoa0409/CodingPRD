"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only — the suite runs against an empty database for each test. All
setup calls go through ``get_success_data()`` so a broken precondition reports
as a setup failure rather than an obscure assertion.

The helpers are organised in five tiers:

  1. State progression   — one call each: clock, program, term, registry rows.
  2. Entity hierarchy    — open program, taxpayer, drafted/executed agreement,
                           accepted pre-clearance.
  3. Lifecycle shortcuts — filed return, down payment, approved installment
                           plan, waterfall payment, breached agreement.
  4. Threshold targeting — accumulations aimed at a named boundary.
  5. Finalization        — closed and reconciled programs.

Every helper accepts ``**overrides`` for the values a test needs to control and
returns a mutable ``ctx`` dict so later tiers can extend an earlier one.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .constants import (
    CANONICAL_CLOCK,
    CANONICAL_DOWN_PAYMENT_CENTS,
    CANONICAL_INSTALLMENT_COUNT,
    CANONICAL_WATERFALL_PAYMENT_CENTS,
    CANONICAL_WINDOW_CLOSE_AT,
)
from .test_users import (
    ADMIN_HEADERS,
    AUDITOR_ONE_HEADERS,
    OFFICER_ALPHA_HEADERS,
    OFFICER_BETA_HEADERS,
    make_representative_headers,
    make_taxpayer_headers,
)

# ===========================================================================
# Tier 1 — state progression primitives
# ===========================================================================


def set_clock(api, to_iso8601: str) -> str:
    """Set the logical clock every temporal rule reads (PRD §2.4)."""
    data = get_success_data(api.set_clock(to_iso8601, ADMIN_HEADERS))
    return data["current_utc"]


def create_program(api, **overrides: Any) -> Dict[str, Any]:
    """Design a `DRAFT` amnesty program (PRD §3.1)."""
    return get_success_data(
        api.create_program(f.program_payload(**overrides), ADMIN_HEADERS)
    )


def add_tax_type_term(api, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """Attach one eligible tax type term to a `DRAFT` program (PRD §3.1)."""
    return get_success_data(
        api.create_tax_type_term(
            program_id, f.tax_type_term_payload(**overrides), ADMIN_HEADERS
        )
    )


def open_window(api, program_id: str) -> Dict[str, Any]:
    """Advance the program `DRAFT → OPEN` (PRD §3.1)."""
    return get_success_data(api.open_program(program_id, ADMIN_HEADERS))


def register_taxpayer(api, **overrides: Any) -> Dict[str, Any]:
    """Register a taxpayer in the amnesty registry (PRD §3.2)."""
    return get_success_data(
        api.create_taxpayer(f.taxpayer_payload(**overrides), ADMIN_HEADERS)
    )


def register_representative(api, **overrides: Any) -> Dict[str, Any]:
    """Register a representative who may mediate pre-clearance (PRD §3.2)."""
    return get_success_data(
        api.create_representative(f.representative_payload(**overrides), ADMIN_HEADERS)
    )


def open_enforcement_case(api, taxpayer_id: str, **overrides: Any) -> Dict[str, Any]:
    """Open an enforcement case that gates program eligibility (PRD §3.2)."""
    return get_success_data(
        api.create_enforcement_case(
            f.enforcement_case_payload(taxpayer_id, **overrides), AUDITOR_ONE_HEADERS
        )
    )


# --- Read-back helpers -----------------------------------------------------


def read_program(api, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_program(program_id, ADMIN_HEADERS))


def read_taxpayer(api, taxpayer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_taxpayer(taxpayer_id, ADMIN_HEADERS))


def read_compliance_behavior(api, taxpayer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_compliance_behavior(taxpayer_id, ADMIN_HEADERS))


def read_agreement(api, agreement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_agreement(agreement_id, ADMIN_HEADERS))


def read_return(api, return_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_return(return_id, ADMIN_HEADERS))


def read_plan(api, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_payment_plan(plan_id, ADMIN_HEADERS))


def read_payment(api, payment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_payment(payment_id, ADMIN_HEADERS))


def read_pre_clearance(api, pre_clearance_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_pre_clearance(pre_clearance_id, ADMIN_HEADERS))


def read_enforcement_action(api, action_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_enforcement_action(action_id, ADMIN_HEADERS))


def read_revenue_summary(api, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_revenue_summary(program_id, ADMIN_HEADERS))


def list_rows(response) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(response)
    return rows


def installments_of(api, plan_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_rows(
        api.list_plan_installments(plan_id, ADMIN_HEADERS, params or {"limit": 100})
    )


def returns_of(api, agreement_id: str, **params: Any) -> List[Dict[str, Any]]:
    return list_rows(
        api.list_agreement_returns(agreement_id, ADMIN_HEADERS, params or {"limit": 100})
    )


# ===========================================================================
# Tier 2 — entity hierarchy
# ===========================================================================


def setup_open_program(
    api,
    clock: Optional[str] = CANONICAL_CLOCK,
    program_overrides: Optional[Dict[str, Any]] = None,
    term_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clock, program, one SALES_USE term, window opened (PRD §3.1)."""
    if clock:
        set_clock(api, clock)
    program = create_program(api, **(program_overrides or {}))
    term = add_tax_type_term(api, program["id"], **(term_overrides or {}))
    program = open_window(api, program["id"])
    return {"program": program, "term": term, "terms": [term]}


def setup_program_with_taxpayer(
    api,
    clock: Optional[str] = CANONICAL_CLOCK,
    program_overrides: Optional[Dict[str, Any]] = None,
    term_overrides: Optional[Dict[str, Any]] = None,
    taxpayer_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An open program plus one registered taxpayer and its bound headers."""
    ctx = setup_open_program(api, clock, program_overrides, term_overrides)
    taxpayer = register_taxpayer(api, **(taxpayer_overrides or {}))
    ctx["taxpayer"] = taxpayer
    ctx["taxpayer_headers"] = make_taxpayer_headers(taxpayer["id"])
    return ctx


def add_taxpayer(api, ctx: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Register an additional taxpayer without disturbing ``ctx``'s primary one."""
    taxpayer = register_taxpayer(api, **overrides)
    ctx.setdefault("extra_taxpayers", []).append(taxpayer)
    return taxpayer


def draft_agreement(
    api,
    ctx: Dict[str, Any],
    taxpayer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft a voluntary disclosure agreement (PRD §3.4)."""
    payload = f.agreement_payload(
        ctx["program"]["id"], taxpayer_id or ctx["taxpayer"]["id"], **overrides
    )
    return get_success_data(
        api.create_agreement(payload, headers or OFFICER_ALPHA_HEADERS)
    )


def setup_drafted_agreement(
    api,
    clock: Optional[str] = CANONICAL_CLOCK,
    program_overrides: Optional[Dict[str, Any]] = None,
    term_overrides: Optional[Dict[str, Any]] = None,
    taxpayer_overrides: Optional[Dict[str, Any]] = None,
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """Open program + taxpayer + a `DRAFTED` walk-in agreement drafted by the
    first officer, so the second officer can sign it (PRD §2.1, §3.4)."""
    ctx = setup_program_with_taxpayer(
        api, clock, program_overrides, term_overrides, taxpayer_overrides
    )
    ctx["agreement"] = draft_agreement(api, ctx, **agreement_overrides)
    return ctx


def execute_agreement(
    api, ctx: Dict[str, Any], headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Advance the agreement `DRAFTED → EXECUTED` with a second signature."""
    ctx["agreement"] = get_success_data(
        api.execute_agreement(ctx["agreement"]["id"], headers or OFFICER_BETA_HEADERS)
    )
    return ctx["agreement"]


def setup_executed_agreement(api, **kwargs: Any) -> Dict[str, Any]:
    """The canonical walk-in `AMNESTY_STATUTORY` agreement, executed."""
    ctx = setup_drafted_agreement(api, **kwargs)
    execute_agreement(api, ctx)
    return ctx


def setup_accepted_pre_clearance(
    api,
    ctx: Dict[str, Any],
    taxpayer_id: Optional[str] = None,
    pre_clearance_overrides: Optional[Dict[str, Any]] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Submit, screen, offer terms, disclose identity and accept — the full
    anonymous negotiation arc of PRD §3.3, ending in `ACCEPTED`."""
    representative = ctx.get("representative") or register_representative(api)
    rep_headers = make_representative_headers(representative["id"])
    ctx["representative"] = representative
    ctx["representative_headers"] = rep_headers

    pre_clearance = get_success_data(
        api.create_pre_clearance(
            f.pre_clearance_payload(
                ctx["program"]["id"], **(pre_clearance_overrides or {})
            ),
            rep_headers,
        )
    )
    pre_clearance = get_success_data(
        api.begin_pre_clearance_review(pre_clearance["id"], OFFICER_ALPHA_HEADERS)
    )
    pre_clearance = get_success_data(
        api.offer_terms(
            pre_clearance["id"],
            f.offer_terms_payload(pre_clearance["version"], **(offer_overrides or {})),
            OFFICER_ALPHA_HEADERS,
        )
    )
    pre_clearance = get_success_data(
        api.disclose_identity(
            pre_clearance["id"],
            f.disclose_identity_payload(taxpayer_id or ctx["taxpayer"]["id"]),
            rep_headers,
        )
    )
    pre_clearance = get_success_data(
        api.accept_pre_clearance(pre_clearance["id"], rep_headers)
    )
    ctx["pre_clearance"] = pre_clearance
    return pre_clearance


def setup_negotiated_agreement(
    api,
    clock: Optional[str] = CANONICAL_CLOCK,
    program_overrides: Optional[Dict[str, Any]] = None,
    term_overrides: Optional[Dict[str, Any]] = None,
    taxpayer_overrides: Optional[Dict[str, Any]] = None,
    pre_clearance_overrides: Optional[Dict[str, Any]] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
    execute: bool = True,
    execute_at: Optional[str] = None,
    **agreement_overrides: Any,
) -> Dict[str, Any]:
    """The `VDA_NEGOTIATED` arc: an accepted pre-clearance threaded into the
    agreement draft, which is what selects that variant (PRD §3.4)."""
    ctx = setup_program_with_taxpayer(
        api, clock, program_overrides, term_overrides, taxpayer_overrides
    )
    pre_clearance = setup_accepted_pre_clearance(
        api,
        ctx,
        pre_clearance_overrides=pre_clearance_overrides,
        offer_overrides=offer_overrides,
    )
    ctx["agreement"] = draft_agreement(
        api, ctx, pre_clearance_id=pre_clearance["id"], **agreement_overrides
    )
    if execute:
        if execute_at:
            set_clock(api, execute_at)
        execute_agreement(api, ctx)
    return ctx


# ===========================================================================
# Tier 3 — lifecycle shortcuts
# ===========================================================================


def draft_return(
    api,
    ctx: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    agreement_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft one disclosure return on the agreement (PRD §3.5)."""
    return get_success_data(
        api.create_return(
            agreement_id or ctx["agreement"]["id"],
            f.disclosure_return_payload(**overrides),
            headers or ctx["taxpayer_headers"],
        )
    )


def file_return(
    api,
    ctx: Dict[str, Any],
    return_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """File the return, accruing statutory penalty and interest (PRD §3.5)."""
    return get_success_data(
        api.file_return(return_id, headers or ctx["taxpayer_headers"])
    )


def draft_and_file_return(
    api, ctx: Dict[str, Any], headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    drafted = draft_return(api, ctx, headers=headers, **overrides)
    filed = file_return(api, ctx, drafted["id"], headers=headers)
    ctx.setdefault("returns", []).append(filed)
    return filed


def setup_filed_return(api, **kwargs: Any) -> Dict[str, Any]:
    """The canonical worked example: an executed walk-in agreement carrying one
    filed SALES_USE return for Q1 2025 that missed a 2025-10-27 due date."""
    return_overrides = kwargs.pop("return_overrides", None) or {}
    ctx = setup_executed_agreement(api, **kwargs)
    ctx["disclosure_return"] = draft_and_file_return(api, ctx, **return_overrides)
    ctx["agreement"] = read_agreement(api, ctx["agreement"]["id"])
    return ctx


def remit_payment(
    api,
    ctx: Dict[str, Any],
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Remit cents against the agreement; the waterfall applies them (PRD §3.6)."""
    payment = get_success_data(
        api.create_payment(
            f.payment_payload(ctx["agreement"]["id"], amount_cents, **overrides),
            headers or ctx["taxpayer_headers"],
        )
    )
    ctx.setdefault("payments", []).append(payment)
    return payment


def propose_payment_plan(
    api,
    ctx: Dict[str, Any],
    installment_count: int = CANONICAL_INSTALLMENT_COUNT,
    down_payment_cents: int = CANONICAL_DOWN_PAYMENT_CENTS,
    expected_agreement_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Propose a plan, declaring the agreement version last observed (PRD §2.8)."""
    if expected_agreement_version is None:
        expected_agreement_version = read_agreement(api, ctx["agreement"]["id"])[
            "version"
        ]
    plan = get_success_data(
        api.create_payment_plan(
            f.payment_plan_payload(
                ctx["agreement"]["id"],
                expected_agreement_version,
                installment_count,
                down_payment_cents,
                **overrides,
            ),
            headers or ctx["taxpayer_headers"],
        )
    )
    ctx["payment_plan"] = plan
    return plan


def setup_agreement_with_down_payment(
    api,
    down_payment_cents: int = CANONICAL_DOWN_PAYMENT_CENTS,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Canonical filed return plus the ten-percent down payment in float."""
    ctx = setup_filed_return(api, **kwargs)
    ctx["down_payment"] = remit_payment(api, ctx, down_payment_cents)
    ctx["agreement"] = read_agreement(api, ctx["agreement"]["id"])
    return ctx


def setup_approved_installment_plan(
    api,
    installment_count: int = CANONICAL_INSTALLMENT_COUNT,
    down_payment_cents: int = CANONICAL_DOWN_PAYMENT_CENTS,
    approve_at: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Canonical filed return, down payment received, plan proposed and approved
    so the installment schedule exists (PRD §3.6)."""
    ctx = setup_agreement_with_down_payment(
        api, down_payment_cents=down_payment_cents, **kwargs
    )
    propose_payment_plan(
        api,
        ctx,
        installment_count=installment_count,
        down_payment_cents=down_payment_cents,
    )
    if approve_at:
        set_clock(api, approve_at)
    ctx["payment_plan"] = get_success_data(
        api.approve_payment_plan(ctx["payment_plan"]["id"], OFFICER_ALPHA_HEADERS)
    )
    ctx["installments"] = installments_of(api, ctx["payment_plan"]["id"])
    ctx["agreement"] = read_agreement(api, ctx["agreement"]["id"])
    return ctx


def setup_plan_with_waterfall_payment(
    api, payment_cents: int = CANONICAL_WATERFALL_PAYMENT_CENTS, **kwargs: Any
) -> Dict[str, Any]:
    """Approved schedule plus one payment large enough to fill the first two
    installments completely and part-fill the third (PRD §3.6)."""
    ctx = setup_approved_installment_plan(api, **kwargs)
    ctx["payment"] = remit_payment(api, ctx, payment_cents)
    ctx["agreement"] = read_agreement(api, ctx["agreement"]["id"])
    ctx["installments"] = installments_of(api, ctx["payment_plan"]["id"])
    return ctx


def declare_breach(
    api, ctx: Dict[str, Any], headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    """Declare breach and fire the five-hop cascade of PRD §3.7."""
    ctx["agreement"] = get_success_data(
        api.declare_breach(
            ctx["agreement"]["id"],
            f.declare_breach_payload(**overrides),
            headers or AUDITOR_ONE_HEADERS,
        )
    )
    return ctx["agreement"]


def setup_breached_agreement(api, **kwargs: Any) -> Dict[str, Any]:
    """Approved plan, one waterfall payment, then a declared breach."""
    ctx = setup_plan_with_waterfall_payment(api, **kwargs)
    declare_breach(api, ctx)
    ctx["installments"] = installments_of(api, ctx["payment_plan"]["id"])
    return ctx


def settle_agreement_in_full(api, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Assess every filed return and pay the agreement off, driving each
    `ASSESSED` return to `SETTLED` (PRD §3.5, §3.6)."""
    for row in returns_of(api, ctx["agreement"]["id"]):
        if row["status"] == "FILED":
            get_success_data(api.assess_return(row["id"], OFFICER_BETA_HEADERS))
    agreement = read_agreement(api, ctx["agreement"]["id"])
    outstanding = agreement["total_due_cents"] - agreement["paid_total_cents"]
    if outstanding > 0:
        remit_payment(api, ctx, outstanding)
    ctx["agreement"] = read_agreement(api, ctx["agreement"]["id"])
    return ctx["agreement"]


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================


def setup_returns_to_haircut_threshold(
    api, reported_tax_amounts: List[int], periods: List[Dict[str, str]], **kwargs: Any
) -> Dict[str, Any]:
    """File a series of returns whose aggregate gross liability walks the
    agreement up to a stated haircut boundary (PRD §3.5 step three)."""
    ctx = setup_executed_agreement(api, **kwargs)
    ctx["returns"] = []
    for amount, period in zip(reported_tax_amounts, periods):
        ctx["returns"].append(
            draft_and_file_return(api, ctx, reported_tax_cents=amount, **period)
        )
    ctx["agreement"] = read_agreement(api, ctx["agreement"]["id"])
    return ctx


# ===========================================================================
# Tier 5 — finalization and terminal state
# ===========================================================================


def close_window(
    api,
    program_id: str,
    at: str = CANONICAL_WINDOW_CLOSE_AT,
) -> Dict[str, Any]:
    """Advance the clock to the close instant and shut the program (PRD §3.8)."""
    if at:
        set_clock(api, at)
    return get_success_data(api.close_program(program_id, ADMIN_HEADERS))


def reconcile(api, program_id: str) -> Dict[str, Any]:
    """Freeze the program's realization and advance `CLOSED → RECONCILED`."""
    return get_success_data(api.reconcile_program(program_id, ADMIN_HEADERS))


def setup_closed_program(
    api, close_at: str = CANONICAL_WINDOW_CLOSE_AT, **kwargs: Any
) -> Dict[str, Any]:
    """An open program with nothing participating, then closed."""
    ctx = setup_open_program(api, **kwargs)
    ctx["program"] = close_window(api, ctx["program"]["id"], at=close_at)
    return ctx


def setup_reconciled_program(api, **kwargs: Any) -> Dict[str, Any]:
    ctx = setup_closed_program(api, **kwargs)
    ctx["program"] = reconcile(api, ctx["program"]["id"])
    return ctx


def setup_flagged_nonparticipant(
    api,
    clock: Optional[str] = CANONICAL_CLOCK,
    close_at: str = CANONICAL_WINDOW_CLOSE_AT,
    program_overrides: Optional[Dict[str, Any]] = None,
    term_overrides: Optional[Dict[str, Any]] = None,
    taxpayer_overrides: Optional[Dict[str, Any]] = None,
    pre_clearance_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A taxpayer who negotiated and disclosed its identity but never accepted,
    then had its pre-clearance expired by the closing cascade — which is the
    only producer of a raised non-participant flag (PRD §3.8)."""
    ctx = setup_program_with_taxpayer(
        api, clock, program_overrides, term_overrides, taxpayer_overrides
    )
    representative = register_representative(api)
    rep_headers = make_representative_headers(representative["id"])
    ctx["representative"] = representative
    ctx["representative_headers"] = rep_headers

    pre_clearance = get_success_data(
        api.create_pre_clearance(
            f.pre_clearance_payload(
                ctx["program"]["id"], **(pre_clearance_overrides or {})
            ),
            rep_headers,
        )
    )
    pre_clearance = get_success_data(
        api.begin_pre_clearance_review(pre_clearance["id"], OFFICER_ALPHA_HEADERS)
    )
    pre_clearance = get_success_data(
        api.offer_terms(
            pre_clearance["id"],
            f.offer_terms_payload(pre_clearance["version"]),
            OFFICER_ALPHA_HEADERS,
        )
    )
    pre_clearance = get_success_data(
        api.disclose_identity(
            pre_clearance["id"],
            f.disclose_identity_payload(ctx["taxpayer"]["id"]),
            rep_headers,
        )
    )
    ctx["pre_clearance"] = pre_clearance
    ctx["program"] = close_window(api, ctx["program"]["id"], at=close_at)
    ctx["pre_clearance"] = read_pre_clearance(api, pre_clearance["id"])
    ctx["taxpayer"] = read_taxpayer(api, ctx["taxpayer"]["id"])
    return ctx
