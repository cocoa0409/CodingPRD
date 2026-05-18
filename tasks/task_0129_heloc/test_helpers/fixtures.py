"""Composite setup helpers — multi-step preambles tests can reuse.

The HELOC pipeline is long: borrower create -> property create ->
senior-lien create -> heloc create (PENDING) -> activate (DRAW) ->
optional draws/payments/rate-resets/clock-advance/sweeps to land at a
specific posture (DRAW, REPAY, DEFAULT, or CLOSED).

IDENTITY THREADING — PRD §2.1:

- Originator / Servicer / PlatformAdmin are OPAQUE. Shared TEST_USERS
  constants are canonical for every operator-only call.

- Borrower is ENTITY-BACKED. Every Borrower-driven call whose success
  depends on owning the targeted resource MUST mint headers via
  make_borrower_headers(borrower["id"]) — never via the shared
  BORROWER_FALLBACK_ID. The fixtures here return the actual Borrower
  row so consumer tests / consumer fixtures can route borrower-acting
  calls through this header builder.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DRAW_PERIOD_DAYS,
    EARLY_CLOSURE_WINDOW_DAYS,
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
)
from .factories import (
    activate_heloc_payload,
    clock_advance_payload,
    close_heloc_payload,
    create_borrower_payload,
    create_draw_payload,
    create_heloc_payload,
    create_insurance_event_payload,
    create_payment_payload,
    create_property_payload,
    create_rate_reset_payload,
    create_senior_lien_payload,
)
from .test_users import TEST_USERS, make_borrower_headers


# ===========================================================================
# Tier 0 — primitive creation helpers
# ===========================================================================
def create_borrower(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    originator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /borrowers — PRD §3.1, §4 (Originator / PlatformAdmin)."""
    headers = originator_headers or TEST_USERS["originator_headers"]
    resp = api_client.create_borrower(
        create_borrower_payload(full_name=full_name, email=email),
        headers,
    )
    return get_success_data(resp)


def create_property(
    *,
    borrower_id: str,
    address: Optional[str] = None,
    appraised_value_cents: int = TEST_DEFAULTS["APPRAISED_VALUE_CENTS"],
    occupancy: Optional[str] = None,
    originator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties — PRD §3.1, §4."""
    headers = originator_headers or TEST_USERS["originator_headers"]
    resp = api_client.create_property(
        create_property_payload(
            borrower_id=borrower_id,
            address=address,
            appraised_value_cents=appraised_value_cents,
            occupancy=occupancy,
        ),
        headers,
    )
    return get_success_data(resp)


def create_senior_lien(
    *,
    property_id: str,
    holder_name: Optional[str] = None,
    principal_balance_cents: int = TEST_DEFAULTS[
        "SENIOR_LIEN_PRINCIPAL_CENTS"
    ],
    originator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /senior-liens — PRD §3.1, §4."""
    headers = originator_headers or TEST_USERS["originator_headers"]
    resp = api_client.create_senior_lien(
        create_senior_lien_payload(
            property_id=property_id,
            holder_name=holder_name,
            principal_balance_cents=principal_balance_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def create_heloc(
    *,
    borrower_id: str,
    property_id: str,
    credit_limit_cents: int = TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    margin_bps: int = TEST_DEFAULTS["MARGIN_BPS"],
    periodic_cap_bps: int = TEST_DEFAULTS["PERIODIC_CAP_BPS"],
    lifetime_cap_bps: int = TEST_DEFAULTS["LIFETIME_CAP_BPS"],
    lifetime_floor_bps: int = TEST_DEFAULTS["LIFETIME_FLOOR_BPS"],
    repayment_term_years: int = TEST_DEFAULTS["REPAYMENT_TERM_YEARS"],
    annual_fee_cents: int = TEST_DEFAULTS["ANNUAL_FEE_CENTS"],
    annual_fee_waived_first_year: Optional[bool] = None,
    early_closure_fee_cents: int = TEST_DEFAULTS[
        "EARLY_CLOSURE_FEE_CENTS"
    ],
    originator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /helocs — PRD §3.2, §4 (Originator / PlatformAdmin)."""
    headers = originator_headers or TEST_USERS["originator_headers"]
    resp = api_client.create_heloc(
        create_heloc_payload(
            borrower_id=borrower_id,
            property_id=property_id,
            credit_limit_cents=credit_limit_cents,
            margin_bps=margin_bps,
            periodic_cap_bps=periodic_cap_bps,
            lifetime_cap_bps=lifetime_cap_bps,
            lifetime_floor_bps=lifetime_floor_bps,
            repayment_term_years=repayment_term_years,
            annual_fee_cents=annual_fee_cents,
            annual_fee_waived_first_year=annual_fee_waived_first_year,
            early_closure_fee_cents=early_closure_fee_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def activate_heloc(
    heloc_id: str,
    *,
    prime_rate_bps: int = TEST_DEFAULTS[
        "PRIME_RATE_BPS_AT_ORIGINATION"
    ],
    version: Optional[int] = None,
    originator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /helocs/{id}/activate — PRD §3.2, §4."""
    headers = originator_headers or TEST_USERS["originator_headers"]
    resp = api_client.activate_heloc(
        heloc_id,
        activate_heloc_payload(
            prime_rate_bps=prime_rate_bps, version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def get_heloc(
    heloc_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["servicer_headers"]
    return get_success_data(api_client.get_heloc(heloc_id, headers))


# ===========================================================================
# Tier 0.5 — clock + sweeps (PlatformAdmin only — PRD §2.11)
# ===========================================================================
def advance_clock(
    *,
    seconds: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance — PRD §2.11.

    Advancing the clock alone does NOT trigger any sweep; tests must
    also call run_billing_cycle_sweep / run_annual_fees_sweep to
    materialize time-driven effects.
    """
    headers = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(
        api_client.clock_advance(
            clock_advance_payload(seconds=seconds), headers,
        ),
    )


def advance_clock_days(
    *,
    days: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return advance_clock(seconds=days * SECONDS_PER_DAY, headers=headers)


def run_billing_cycle_sweep(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_sweep/billing-cycle — PRD §3.7."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(
        api_client.sweep_billing_cycle(headers),
    )


def run_annual_fees_sweep(
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_sweep/annual-fees — PRD §3.8."""
    headers = headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(
        api_client.sweep_annual_fees(headers),
    )


# ===========================================================================
# Tier 0.5 — primitive Heloc actions (draw, payment, rate-reset, close)
# ===========================================================================
def post_draw(
    heloc_id: str,
    *,
    amount_cents: int,
    borrower_headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /helocs/{id}/draws — PRD §3.3 (Borrower / PlatformAdmin).

    `borrower_headers` MUST be minted via
    make_borrower_headers(actual_borrower_id). Defaults to
    PlatformAdmin (opaque) so setup-style calls work without a borrower
    id; tests of ownership MUST pass an explicit borrower header.
    """
    headers = borrower_headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(
        api_client.create_draw(
            heloc_id,
            create_draw_payload(
                amount_cents=amount_cents, version=version,
            ),
            headers,
        ),
    )


def post_payment(
    heloc_id: str,
    *,
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /helocs/{id}/payments — PRD §3.4 (Borrower / Servicer /
    PlatformAdmin)."""
    headers = headers or TEST_USERS["servicer_headers"]
    return get_success_data(
        api_client.create_payment(
            heloc_id,
            create_payment_payload(
                amount_cents=amount_cents, version=version,
            ),
            headers,
        ),
    )


def post_rate_reset(
    heloc_id: str,
    *,
    prime_rate_bps: int,
    servicer_headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /helocs/{id}/rate-resets — PRD §3.5 (Servicer /
    PlatformAdmin)."""
    headers = servicer_headers or TEST_USERS["servicer_headers"]
    return get_success_data(
        api_client.create_rate_reset(
            heloc_id,
            create_rate_reset_payload(
                prime_rate_bps=prime_rate_bps, version=version,
            ),
            headers,
        ),
    )


def close_heloc(
    heloc_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /helocs/{id}/close — PRD §3.9 (Servicer / Borrower /
    PlatformAdmin)."""
    headers = headers or TEST_USERS["servicer_headers"]
    return get_success_data(
        api_client.close_heloc(
            heloc_id, headers, close_heloc_payload(version=version),
        ),
    )


# ===========================================================================
# Tier 0.5 — cross-entity event helpers
# ===========================================================================
def post_bankruptcy_event(
    borrower_id: str,
    *,
    servicer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /borrowers/{id}/bankruptcy-events — PRD §3.6."""
    headers = servicer_headers or TEST_USERS["servicer_headers"]
    return get_success_data(
        api_client.create_bankruptcy_event(borrower_id, headers),
    )


def post_insurance_event(
    property_id: str,
    *,
    event_type: str,
    servicer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /properties/{id}/insurance-events — PRD §3.6."""
    headers = servicer_headers or TEST_USERS["servicer_headers"]
    return get_success_data(
        api_client.create_insurance_event(
            property_id,
            create_insurance_event_payload(event_type=event_type),
            headers,
        ),
    )


def post_senior_lien_default_event(
    senior_lien_id: str,
    *,
    servicer_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /senior-liens/{id}/default-events — PRD §3.6."""
    headers = servicer_headers or TEST_USERS["servicer_headers"]
    return get_success_data(
        api_client.create_senior_lien_default_event(
            senior_lien_id, headers,
        ),
    )


# ===========================================================================
# Tier 1 — onboarding bundles
# ===========================================================================
def setup_borrower_property_lien(
    *,
    appraised_value_cents: int = TEST_DEFAULTS["APPRAISED_VALUE_CENTS"],
    senior_lien_principal_cents: int = TEST_DEFAULTS[
        "SENIOR_LIEN_PRINCIPAL_CENTS"
    ],
    occupancy: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create Borrower + Property (PRIMARY by default) + SeniorLien.

    Returns (borrower, property, senior_lien) — the standard 3-tuple
    every HELOC test starts from.
    """
    borrower = create_borrower()
    prop = create_property(
        borrower_id=borrower["id"],
        appraised_value_cents=appraised_value_cents,
        occupancy=occupancy,
    )
    sl = create_senior_lien(
        property_id=prop["id"],
        principal_balance_cents=senior_lien_principal_cents,
    )
    return borrower, prop, sl


def setup_pending_heloc(
    *,
    credit_limit_cents: int = TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    margin_bps: int = TEST_DEFAULTS["MARGIN_BPS"],
    periodic_cap_bps: int = TEST_DEFAULTS["PERIODIC_CAP_BPS"],
    lifetime_cap_bps: int = TEST_DEFAULTS["LIFETIME_CAP_BPS"],
    lifetime_floor_bps: int = TEST_DEFAULTS["LIFETIME_FLOOR_BPS"],
    repayment_term_years: int = TEST_DEFAULTS["REPAYMENT_TERM_YEARS"],
    annual_fee_cents: int = TEST_DEFAULTS["ANNUAL_FEE_CENTS"],
    annual_fee_waived_first_year: Optional[bool] = None,
    early_closure_fee_cents: int = TEST_DEFAULTS[
        "EARLY_CLOSURE_FEE_CENTS"
    ],
    appraised_value_cents: int = TEST_DEFAULTS["APPRAISED_VALUE_CENTS"],
    senior_lien_principal_cents: int = TEST_DEFAULTS[
        "SENIOR_LIEN_PRINCIPAL_CENTS"
    ],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Borrower + Property + SeniorLien + PENDING Heloc.

    Returns (borrower, property, senior_lien, heloc).
    """
    borrower, prop, sl = setup_borrower_property_lien(
        appraised_value_cents=appraised_value_cents,
        senior_lien_principal_cents=senior_lien_principal_cents,
    )
    heloc = create_heloc(
        borrower_id=borrower["id"],
        property_id=prop["id"],
        credit_limit_cents=credit_limit_cents,
        margin_bps=margin_bps,
        periodic_cap_bps=periodic_cap_bps,
        lifetime_cap_bps=lifetime_cap_bps,
        lifetime_floor_bps=lifetime_floor_bps,
        repayment_term_years=repayment_term_years,
        annual_fee_cents=annual_fee_cents,
        annual_fee_waived_first_year=annual_fee_waived_first_year,
        early_closure_fee_cents=early_closure_fee_cents,
    )
    return borrower, prop, sl, heloc


# ===========================================================================
# Tier 2 — activated HELOC in DRAW
# ===========================================================================
def setup_active_heloc(
    *,
    prime_rate_bps_at_origination: int = TEST_DEFAULTS[
        "PRIME_RATE_BPS_AT_ORIGINATION"
    ],
    **heloc_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Standard 4-step setup → DRAW. Returns
    (borrower, property, senior_lien, heloc_in_DRAW).
    """
    borrower, prop, sl, heloc = setup_pending_heloc(**heloc_overrides)
    activated = activate_heloc(
        heloc["id"], prime_rate_bps=prime_rate_bps_at_origination,
    )
    return borrower, prop, sl, activated


def setup_active_heloc_with_balance(
    *,
    draw_amount_cents: int,
    prime_rate_bps_at_origination: int = TEST_DEFAULTS[
        "PRIME_RATE_BPS_AT_ORIGINATION"
    ],
    **heloc_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """Standard setup → DRAW → take one draw of `draw_amount_cents`.

    Returns (borrower, property, senior_lien, heloc, draw).
    The draw is posted under the actual Borrower's headers (entity-
    backed identity, PRD §2.1) so ownership checks succeed.
    """
    borrower, prop, sl, heloc = setup_active_heloc(
        prime_rate_bps_at_origination=prime_rate_bps_at_origination,
        **heloc_overrides,
    )
    draw = post_draw(
        heloc["id"],
        amount_cents=draw_amount_cents,
        borrower_headers=make_borrower_headers(borrower["id"]),
    )
    return borrower, prop, sl, heloc, draw


# ===========================================================================
# Tier 3 — REPAY-phase setup (DRAW → REPAY via clock + sweep)
# ===========================================================================
def setup_heloc_in_repay(
    *,
    draw_amount_cents: int = 1_000_000,
    prime_rate_bps_at_origination: int = TEST_DEFAULTS[
        "PRIME_RATE_BPS_AT_ORIGINATION"
    ],
    **heloc_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Active HELOC + one draw + cross draw_period_end_date + sweep.

    PRD §3.7: 'if the HELOC's status is still DRAW and the current
    clock time has reached or passed draw_period_end_date, the HELOC
    transitions from DRAW to REPAY.'

    Returns (borrower, property, senior_lien, heloc_in_REPAY).
    """
    borrower, prop, sl, heloc, _draw = (
        setup_active_heloc_with_balance(
            draw_amount_cents=draw_amount_cents,
            prime_rate_bps_at_origination=(
                prime_rate_bps_at_origination
            ),
            **heloc_overrides,
        )
    )
    # PRD §3.2: 'draw_period_end_date as exactly 3650 days'. Advance
    # by 3650 days then sweep to fire the rollover.
    advance_clock_days(days=DRAW_PERIOD_DAYS)
    run_billing_cycle_sweep()
    return borrower, prop, sl, get_heloc(heloc["id"])


# ===========================================================================
# Tier 4 — DEFAULT-phase setup via each of the four triggers
# ===========================================================================
def setup_heloc_default_via_bankruptcy(
    **active_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """PRD §3.6: borrower bankruptcy cascades active HELOC to DEFAULT
    with default_trigger=BANKRUPTCY.

    Returns (borrower, property, senior_lien, heloc_in_DEFAULT, event).
    """
    borrower, prop, sl, heloc = setup_active_heloc(**active_overrides)
    event = post_bankruptcy_event(borrower["id"])
    return borrower, prop, sl, get_heloc(heloc["id"]), event


def setup_heloc_default_via_insurance_lapse(
    **active_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """PRD §3.6: insurance LAPSE cascades active HELOC to DEFAULT
    with default_trigger=INSURANCE_LAPSE.

    Returns (borrower, property, senior_lien, heloc_in_DEFAULT, event).
    """
    borrower, prop, sl, heloc = setup_active_heloc(**active_overrides)
    event = post_insurance_event(prop["id"], event_type="LAPSE")
    return borrower, prop, sl, get_heloc(heloc["id"]), event


def setup_heloc_default_via_senior_lien(
    **active_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any],
]:
    """PRD §3.6: senior-lien default cascades active HELOC to DEFAULT
    with default_trigger=SENIOR_LIEN_DEFAULT.

    Returns (borrower, property, senior_lien, heloc_in_DEFAULT, event).
    """
    borrower, prop, sl, heloc = setup_active_heloc(**active_overrides)
    event = post_senior_lien_default_event(sl["id"])
    return borrower, prop, sl, get_heloc(heloc["id"]), event


def setup_heloc_at_delinquency_days(
    *,
    target_days: int,
    draw_amount_cents: int = 1_000_000,
    max_cycles: int = 8,
    **active_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Active HELOC with a draw, swept (target_days // 30)+1 times at
    most, without payment, so delinquency_days converges toward
    target_days.

    PRD §3.7: "If that sum is at least the prior cycle's
    minimum_payment_due_cents, the HELOC's delinquency_days is reset
    to zero; otherwise, delinquency_days is incremented by 30."

    PRD does not explicitly state what the "prior cycle's minimum"
    is for the very first cycle (when no prior cycle has run). To
    avoid relying on an under-specified detail, this fixture sweeps
    in a loop and stops once delinquency_days >= target_days OR the
    HELOC has transitioned to DEFAULT OR max_cycles has been reached.

    `target_days` must be a non-negative multiple of 30. Caller is
    responsible for choosing a value below the 90-day default trigger
    if they want the HELOC to stay in DRAW. Returns
    (borrower, property, senior_lien, heloc).
    """
    assert target_days >= 0, "target_days must be non-negative"
    assert target_days % 30 == 0, (
        "target_days must be a multiple of 30 (PRD §3.7 cycle length)"
    )
    borrower, prop, sl, heloc, _draw = (
        setup_active_heloc_with_balance(
            draw_amount_cents=draw_amount_cents,
            **active_overrides,
        )
    )
    current = heloc
    for _ in range(max_cycles):
        if current.get("delinquency_days", 0) >= target_days:
            break
        if current.get("status") == "DEFAULT":
            break
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        current = get_heloc(heloc["id"])
    return borrower, prop, sl, current


# ===========================================================================
# Tier 5 — CLOSED-phase setup
# ===========================================================================
def setup_heloc_closed_no_balance(
    *,
    days_to_advance_before_close: int = 0,
    prime_rate_bps_at_origination: int = TEST_DEFAULTS[
        "PRIME_RATE_BPS_AT_ORIGINATION"
    ],
    early_closure_fee_cents: int = TEST_DEFAULTS[
        "EARLY_CLOSURE_FEE_CENTS"
    ],
    **heloc_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Active HELOC with NO draw → advance clock → close.

    Useful for testing the early-closure-fee window boundary. By
    default tenure==0 (no clock advance) so EARLY_CLOSURE fee fires
    iff early_closure_fee_cents > 0.

    Returns (borrower, property, senior_lien, heloc_in_CLOSED).
    """
    borrower, prop, sl, heloc = setup_active_heloc(
        prime_rate_bps_at_origination=prime_rate_bps_at_origination,
        early_closure_fee_cents=early_closure_fee_cents,
        **heloc_overrides,
    )
    if days_to_advance_before_close > 0:
        advance_clock_days(days=days_to_advance_before_close)
    closed = close_heloc(heloc["id"])
    return borrower, prop, sl, closed


# ===========================================================================
# Tier 6 — Multi-Heloc per-borrower / per-property setup for cascade tests
# ===========================================================================
def setup_borrower_with_two_helocs(
    **heloc_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """One borrower, TWO properties + senior liens, TWO active HELOCs.

    For PRD §3.6 cascade tests: a single bankruptcy event must cascade
    to BOTH HELOCs owned by the borrower.

    Returns (borrower, prop_a, lien_a, heloc_a, prop_b, lien_b, heloc_b).
    """
    borrower = create_borrower()

    prop_a = create_property(borrower_id=borrower["id"])
    lien_a = create_senior_lien(property_id=prop_a["id"])
    heloc_a_pending = create_heloc(
        borrower_id=borrower["id"],
        property_id=prop_a["id"],
        **heloc_overrides,
    )
    heloc_a = activate_heloc(heloc_a_pending["id"])

    prop_b = create_property(borrower_id=borrower["id"])
    lien_b = create_senior_lien(property_id=prop_b["id"])
    heloc_b_pending = create_heloc(
        borrower_id=borrower["id"],
        property_id=prop_b["id"],
        **heloc_overrides,
    )
    heloc_b = activate_heloc(heloc_b_pending["id"])

    return borrower, prop_a, lien_a, heloc_a, prop_b, lien_b, heloc_b


# ===========================================================================
# Tier 7 — Cumulative-state setup helpers (for difficulty-design recipes)
# ===========================================================================
def setup_heloc_with_accrued_interest(
    *,
    draw_amount_cents: int = 1_000_000,
    cycles_to_accrue: int = 1,
    prime_rate_bps_at_origination: int = TEST_DEFAULTS[
        "PRIME_RATE_BPS_AT_ORIGINATION"
    ],
    **heloc_overrides: Any,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Active HELOC + one draw + N billing cycles (clock-advanced per
    cycle so cycles aren't deduped by the idempotency key).

    PRD §3.7: 'On each invocation, for every HELOC whose status is in
    DRAW or REPAY, the sweep ... It first computes the interest
    accrual for the cycle as ... rounded half-up to whole cents
    before being added into accrued_interest_cents.'

    Returns (borrower, property, senior_lien, heloc).
    """
    borrower, prop, sl, heloc, _draw = (
        setup_active_heloc_with_balance(
            draw_amount_cents=draw_amount_cents,
            prime_rate_bps_at_origination=(
                prime_rate_bps_at_origination
            ),
            **heloc_overrides,
        )
    )
    for _ in range(cycles_to_accrue):
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
    return borrower, prop, sl, get_heloc(heloc["id"])


def setup_two_helocs_for_close_branch_outcomes(
) -> Dict[str, Dict[str, Any]]:
    """For the three-terminal-path branching test in difficulty index
    rule 3 (heloc_branching_three_terminal_paths_to_closed): three
    independent activated HELOCs each ready for a different
    close-trajectory test.

    Returns dict { 'h_a': heloc_a, 'h_b': heloc_b, 'h_c': heloc_c,
                   'borrower_a': ..., 'borrower_b': ...,
                   'borrower_c': ... }.
    Each Heloc is freshly activated and in DRAW with zero balance,
    so the consumer can drive each one to CLOSED via a different path.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for tag in ("a", "b", "c"):
        borrower, _prop, _sl, heloc = setup_active_heloc()
        out[f"borrower_{tag}"] = borrower
        out[f"h_{tag}"] = heloc
    return out


__all__ = [
    # primitives
    "create_borrower",
    "create_property",
    "create_senior_lien",
    "create_heloc",
    "activate_heloc",
    "get_heloc",
    # clock + sweeps
    "advance_clock",
    "advance_clock_days",
    "run_billing_cycle_sweep",
    "run_annual_fees_sweep",
    # actions
    "post_draw",
    "post_payment",
    "post_rate_reset",
    "close_heloc",
    "post_bankruptcy_event",
    "post_insurance_event",
    "post_senior_lien_default_event",
    # tier-1 onboarding
    "setup_borrower_property_lien",
    "setup_pending_heloc",
    # tier-2 active
    "setup_active_heloc",
    "setup_active_heloc_with_balance",
    # tier-3 REPAY
    "setup_heloc_in_repay",
    # tier-4 DEFAULT triggers
    "setup_heloc_default_via_bankruptcy",
    "setup_heloc_default_via_insurance_lapse",
    "setup_heloc_default_via_senior_lien",
    "setup_heloc_at_delinquency_days",
    # tier-5 CLOSED
    "setup_heloc_closed_no_balance",
    # tier-6 multi-Heloc per borrower
    "setup_borrower_with_two_helocs",
    # tier-7 cumulative
    "setup_heloc_with_accrued_interest",
    "setup_two_helocs_for_close_branch_outcomes",
]
