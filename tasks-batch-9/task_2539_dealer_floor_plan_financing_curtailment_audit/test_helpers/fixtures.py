"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares.  The logical
clock reads 2026-08-01T00:00:00Z until a SystemOperator moves it, and every
chain pins it explicitly so date arithmetic is deterministic.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    aging_exception_decision_payload,
    aging_exception_payload,
    covenant_test_payload,
    create_credit_line_payload,
    create_curtailment_tier_payload,
    create_dealer_payload,
    create_unit_payload,
    fund_advance_payload,
    make_vin,
    observation_payload,
    remedy_action_payload,
    remittance_payload,
    request_advance_payload,
    schedule_audit_payload,
    title_custody_payload,
)
from .test_users import TEST_USERS, make_dealer_principal_headers

CO = TEST_USERS["credit_officer_headers"]
CRM = TEST_USERS["credit_risk_manager_headers"]
CRM2 = TEST_USERS["credit_risk_manager_2_headers"]
FA = TEST_USERS["field_auditor_headers"]
FA2 = TEST_USERS["field_auditor_2_headers"]
AM = TEST_USERS["audit_manager_headers"]
AM2 = TEST_USERS["audit_manager_2_headers"]
SYS = TEST_USERS["system_operator_headers"]

# A single unbounded ladder rung per class is enough for most chains.
NEW_TIER = {"inventory_class": "NEW", "age_days_from": 90, "age_days_to": None,
            "cumulative_paydown_bps": 1000}
USED_TIER = {"inventory_class": "USED", "age_days_from": 90, "age_days_to": None,
             "cumulative_paydown_bps": 1500}
DEMO_TIER = {"inventory_class": "DEMONSTRATOR", "age_days_from": 90, "age_days_to": None,
             "cumulative_paydown_bps": 1000}


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    """Pin the logical clock. Mutates no entity."""
    return get_success_data(api_client.set_current_utc(to_iso8601, SYS))


def create_dealer(**overrides) -> Dict[str, Any]:
    """Onboard a dealer. Returns the created Dealer in PROSPECT."""
    return get_success_data(
        api_client.create_dealer(create_dealer_payload(**overrides), CO)
    )


def create_credit_line(dealer_id: str, **overrides) -> Dict[str, Any]:
    """Create a PENDING credit line for a dealer."""
    return get_success_data(
        api_client.create_credit_line(
            create_credit_line_payload(dealer_id, **overrides), CO
        )
    )


def add_tier(credit_line_id: str, **tier) -> Dict[str, Any]:
    """Load one curtailment ladder rung onto a line."""
    return get_success_data(
        api_client.create_curtailment_tier(
            credit_line_id, create_curtailment_tier_payload(**tier), CO
        )
    )


def activate_credit_line(credit_line_id: str) -> Dict[str, Any]:
    """Activate a PENDING line, which also moves a PROSPECT dealer to ACTIVE."""
    return get_success_data(api_client.activate_credit_line(credit_line_id, CO))


def read_credit_line(credit_line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_credit_line(credit_line_id, CO))


def read_dealer(dealer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_dealer(dealer_id, CO))


def read_unit(unit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_unit(unit_id, CO))


def credit_line_version(credit_line_id: str) -> int:
    return read_credit_line(credit_line_id)["version"]


def dealer_version(dealer_id: str) -> int:
    return read_dealer(dealer_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: an active dealer sitting behind an active credit line
# ---------------------------------------------------------------------------
def setup_active_line(
    tiers: Optional[List[Dict[str, Any]]] = None,
    clock: str = DEFAULT_CLOCK_UTC,
    dealer_overrides: Optional[Dict[str, Any]] = None,
    **line_overrides,
) -> Dict[str, Any]:
    """Clock + dealer + credit line + ladder rungs + activation.

    Returns {"dealer", "credit_line", "tiers", "dealer_headers"} where the
    dealer and line reflect their post-activation state.
    """
    set_clock(clock)
    dealer = create_dealer(**(dealer_overrides or {}))
    line = create_credit_line(dealer["id"], **line_overrides)
    created_tiers = [add_tier(line["id"], **t) for t in (tiers or [NEW_TIER])]
    activate_credit_line(line["id"])
    return {
        "dealer": read_dealer(dealer["id"]),
        "credit_line": read_credit_line(line["id"]),
        "tiers": created_tiers,
        "dealer_headers": make_dealer_principal_headers(dealer["id"]),
    }


def setup_pending_line(
    tiers: Optional[List[Dict[str, Any]]] = None,
    clock: str = DEFAULT_CLOCK_UTC,
    **line_overrides,
) -> Dict[str, Any]:
    """Clock + dealer + credit line + ladder rungs, deliberately NOT activated."""
    set_clock(clock)
    dealer = create_dealer(**line_overrides.pop("dealer_overrides", {}))
    line = create_credit_line(dealer["id"], **line_overrides)
    created_tiers = [add_tier(line["id"], **t) for t in (tiers or [NEW_TIER])]
    return {
        "dealer": read_dealer(dealer["id"]),
        "credit_line": read_credit_line(line["id"]),
        "tiers": created_tiers,
        "dealer_headers": make_dealer_principal_headers(dealer["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 2: inventory units and their funding lifecycle
# ---------------------------------------------------------------------------
def register_unit(
    dealer_id: str,
    credit_line_id: str,
    vin_seed: str,
    dealer_headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Register one inventory unit as the owning DealerPrincipal."""
    headers = dealer_headers or make_dealer_principal_headers(dealer_id)
    payload = create_unit_payload(
        dealer_id, credit_line_id, make_vin(vin_seed), **overrides
    )
    return get_success_data(api_client.create_unit(payload, headers))


def move_title_custody(
    unit_id: str, new_custody_status: str, document_reference: Optional[str] = None
) -> Dict[str, Any]:
    """Move the unit's title custody dimension as CreditOfficer."""
    payload = title_custody_payload(new_custody_status)
    if document_reference is not None:
        payload["document_reference"] = document_reference
    return get_success_data(api_client.change_title_custody(unit_id, payload, CO))


def request_advance(
    unit_id: str,
    dealer_headers: Dict[str, str],
    requested_amount_cents: int,
    dealer_invoice_reference: str = "INV-FIXTURE-0001",
) -> Dict[str, Any]:
    """File a funding request as the owning DealerPrincipal."""
    return get_success_data(
        api_client.request_funding_advance(
            unit_id,
            request_advance_payload(requested_amount_cents, dealer_invoice_reference),
            dealer_headers,
        )
    )


def fund_advance(
    advance_id: str,
    credit_line_id: str,
    disbursement_reference: str = "WIRE-FIXTURE-0001",
) -> Dict[str, Any]:
    """Read the live line version, then disburse the advance as CreditOfficer."""
    version = credit_line_version(credit_line_id)
    return get_success_data(
        api_client.fund_advance(
            advance_id, fund_advance_payload(version, disbursement_reference), CO
        )
    )


def floor_unit(
    dealer_id: str,
    credit_line_id: str,
    vin_seed: str,
    dealer_headers: Optional[Dict[str, str]] = None,
    requested_amount_cents: Optional[int] = None,
    document_reference: str = "MSO-FIXTURE",
    disbursement_reference: str = "WIRE-FIXTURE",
    **unit_overrides,
) -> Dict[str, Any]:
    """Register a unit, hand the title to the lender, request and disburse.

    Returns {"unit", "advance"} with both re-read after the disbursement.
    """
    headers = dealer_headers or make_dealer_principal_headers(dealer_id)
    unit = register_unit(
        dealer_id, credit_line_id, vin_seed, dealer_headers=headers, **unit_overrides
    )
    move_title_custody(unit["id"], "LENDER_HELD", document_reference)
    amount = (
        requested_amount_cents
        if requested_amount_cents is not None
        else unit["invoice_amount_cents"]
    )
    advance = request_advance(
        unit["id"], headers, amount, f"INV-{vin_seed.upper()}"
    )
    funded = fund_advance(advance["id"], credit_line_id, disbursement_reference)
    return {"unit": read_unit(unit["id"]), "advance": funded}


def setup_floored_unit(
    tiers: Optional[List[Dict[str, Any]]] = None,
    clock: str = DEFAULT_CLOCK_UTC,
    vin_seed: str = "FLOORUNIT0000001",
    unit_overrides: Optional[Dict[str, Any]] = None,
    **line_overrides,
) -> Dict[str, Any]:
    """Active line plus exactly one FLOORED unit.

    Returns {"dealer", "credit_line", "dealer_headers", "unit", "advance"}.
    """
    ctx = setup_active_line(tiers=tiers, clock=clock, **line_overrides)
    floored = floor_unit(
        ctx["dealer"]["id"],
        ctx["credit_line"]["id"],
        vin_seed,
        dealer_headers=ctx["dealer_headers"],
        **(unit_overrides or {}),
    )
    ctx.update(floored)
    ctx["dealer"] = read_dealer(ctx["dealer"]["id"])
    ctx["credit_line"] = read_credit_line(ctx["credit_line"]["id"])
    return ctx


def list_unit_obligations(
    unit_id: str, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Every curtailment obligation of a unit, default sorted created_at ASC."""
    params: Dict[str, Any] = {"unit_id": unit_id, "limit": 100}
    if status is not None:
        params["status"] = status
    body = api_client.list_curtailment_obligations(CO, params=params).json()
    return body["data"]


def unit_schedule(unit_id: str) -> Dict[str, Any]:
    """The unit's FORWARD_PROJECTED curtailment ladder."""
    return get_success_data(api_client.get_curtailment_schedule(unit_id, CO))


# ---------------------------------------------------------------------------
# Tier 3: curtailment runs, obligations and aging exceptions
# ---------------------------------------------------------------------------
def run_curtailment(
    dealer_id: Optional[str] = None, as_of_date: Optional[str] = None
) -> Dict[str, Any]:
    """Sweep the curtailment ladder as SystemOperator."""
    payload: Dict[str, Any] = {}
    if dealer_id is not None:
        payload["dealer_id"] = dealer_id
    if as_of_date is not None:
        payload["as_of_date"] = as_of_date
    return get_success_data(api_client.run_curtailment(payload, SYS))


def file_aging_exception(
    obligation_id: str,
    dealer_headers: Dict[str, str],
    requested_extension_days: int = 15,
    justification_code: str = "RETAIL_DEAL_PENDING",
) -> Dict[str, Any]:
    """File an aging exception request as the owning DealerPrincipal."""
    return get_success_data(
        api_client.file_aging_exception(
            obligation_id,
            aging_exception_payload(requested_extension_days, justification_code),
            dealer_headers,
        )
    )


def decide_aging_exception(
    exception_id: str,
    decision: str,
    reason_code: str,
    decided_extension_days: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Approve or deny an aging exception as a CreditRiskManager."""
    payload = aging_exception_decision_payload(decision, reason_code)
    if decided_extension_days is not None:
        payload["decided_extension_days"] = decided_extension_days
    return get_success_data(
        api_client.decide_aging_exception(exception_id, payload, headers or CRM)
    )


def setup_unit_with_due_obligation(
    paydown_bps: int = 1000,
    age_days_from: int = 90,
    invoice_amount_cents: int = TEST_DEFAULTS["UNIT_INVOICE_AMOUNT_CENTS"],
    grace_days: int = 5,
    vin_seed: str = "DUEUNIT000000001",
) -> Dict[str, Any]:
    """A FLOORED unit whose single obligation has been driven to DUE.

    The unit is floored on 2026-08-01, the clock advances to floored_at plus
    age_days_from, and a curtailment run marks the obligation DUE.
    """
    tier = {
        "inventory_class": "NEW",
        "age_days_from": age_days_from,
        "age_days_to": None,
        "cumulative_paydown_bps": paydown_bps,
    }
    ctx = setup_floored_unit(
        tiers=[tier],
        vin_seed=vin_seed,
        unit_overrides={"invoice_amount_cents": invoice_amount_cents},
        curtailment_grace_days=grace_days,
    )
    due_date = _add_days(DEFAULT_CLOCK_UTC, age_days_from)
    set_clock(due_date)
    ctx["run"] = run_curtailment(dealer_id=ctx["dealer"]["id"])
    ctx["obligations"] = list_unit_obligations(ctx["unit"]["id"])
    ctx["unit"] = read_unit(ctx["unit"]["id"])
    ctx["credit_line"] = read_credit_line(ctx["credit_line"]["id"])
    ctx["dealer"] = read_dealer(ctx["dealer"]["id"])
    ctx["due_date"] = due_date
    return ctx


def setup_unit_with_delinquent_obligation(
    paydown_bps: int = 1000,
    age_days_from: int = 90,
    invoice_amount_cents: int = TEST_DEFAULTS["UNIT_INVOICE_AMOUNT_CENTS"],
    grace_days: int = 5,
    vin_seed: str = "LATEUNIT00000001",
) -> Dict[str, Any]:
    """A unit whose obligation has gone DELINQUENT past its grace period."""
    ctx = setup_unit_with_due_obligation(
        paydown_bps=paydown_bps,
        age_days_from=age_days_from,
        invoice_amount_cents=invoice_amount_cents,
        grace_days=grace_days,
        vin_seed=vin_seed,
    )
    delinquent_date = _add_days(DEFAULT_CLOCK_UTC, age_days_from + grace_days + 1)
    set_clock(delinquent_date)
    ctx["delinquency_run"] = run_curtailment(dealer_id=ctx["dealer"]["id"])
    ctx["obligations"] = list_unit_obligations(ctx["unit"]["id"])
    ctx["unit"] = read_unit(ctx["unit"]["id"])
    ctx["credit_line"] = read_credit_line(ctx["credit_line"]["id"])
    ctx["dealer"] = read_dealer(ctx["dealer"]["id"])
    ctx["delinquent_date"] = delinquent_date
    return ctx


def _add_days(iso_utc: str, days: int) -> str:
    """Add whole days to an ISO 8601 UTC instant, preserving the Z suffix."""
    from datetime import datetime, timedelta, timezone

    cleaned = iso_utc.replace("Z", "+00:00")
    moment = datetime.fromisoformat(cleaned).astimezone(timezone.utc)
    moved = moment + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def date_only(iso_utc: str) -> str:
    """The calendar-date prefix of an ISO 8601 instant."""
    return iso_utc[:10]


# ---------------------------------------------------------------------------
# Tier 4: floor plan audits
# ---------------------------------------------------------------------------
def schedule_audit(
    dealer_id: str,
    window_start_date: str,
    window_end_date: str,
    audit_type: str = "ANNOUNCED",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Book an audit window as AuditManager."""
    return get_success_data(
        api_client.schedule_audit(
            schedule_audit_payload(
                dealer_id, window_start_date, window_end_date, audit_type
            ),
            headers or AM,
        )
    )


def start_audit(audit_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Open the count as FieldAuditor, freezing the audit scope."""
    return get_success_data(api_client.start_audit(audit_id, headers or FA))


def record_observation(
    audit_id: str,
    unit_id: str,
    observed_condition: str = "PRESENT",
    title_verified: bool = True,
    headers: Optional[Dict[str, str]] = None,
    **extra,
) -> Dict[str, Any]:
    """Record one immutable audit reading as FieldAuditor."""
    payload = observation_payload(unit_id, observed_condition, title_verified, **extra)
    return get_success_data(
        api_client.record_observation(audit_id, payload, headers or FA)
    )


def reconcile_audit(
    audit_id: str, notes: str = "Fixture sign-off", headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Sign the audit off as AuditManager."""
    return get_success_data(
        api_client.reconcile_audit(audit_id, {"notes": notes}, headers or AM)
    )


def abort_audit(
    audit_id: str,
    abort_reason_code: str = "AUDITOR_REASSIGNED",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Abandon the audit as AuditManager, freeing its window."""
    return get_success_data(
        api_client.abort_audit(
            audit_id, {"abort_reason_code": abort_reason_code}, headers or AM
        )
    )


def setup_audit_in_progress(
    dealer_id: str,
    window_start_date: str = "2026-08-10",
    window_end_date: str = "2026-08-12",
    audit_type: str = "ANNOUNCED",
    start_clock: str = "2026-08-10T00:00:00Z",
    auditor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Book an audit, advance the clock into its window and open the count."""
    audit = schedule_audit(dealer_id, window_start_date, window_end_date, audit_type)
    set_clock(start_clock)
    started = start_audit(audit["id"], headers=auditor_headers)
    return {"audit": started, "audit_id": audit["id"]}


def setup_floored_unit_with_open_audit(
    vin_seed: str = "AUDITUNIT0000001",
    tiers: Optional[List[Dict[str, Any]]] = None,
    unit_overrides: Optional[Dict[str, Any]] = None,
    window_start_date: str = "2026-08-10",
    window_end_date: str = "2026-08-12",
    start_clock: str = "2026-08-10T00:00:00Z",
    **line_overrides,
) -> Dict[str, Any]:
    """One FLOORED unit belonging to a dealer whose audit is IN_PROGRESS."""
    ctx = setup_floored_unit(
        tiers=tiers, vin_seed=vin_seed, unit_overrides=unit_overrides, **line_overrides
    )
    ctx.update(
        setup_audit_in_progress(
            ctx["dealer"]["id"],
            window_start_date=window_start_date,
            window_end_date=window_end_date,
            start_clock=start_clock,
        )
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: remittances, covenants and remedies
# ---------------------------------------------------------------------------
def remit(
    dealer_id: str,
    intent: str,
    amount_cents: int,
    dealer_headers: Optional[Dict[str, str]] = None,
    payment_reference: str = "PAY-FIXTURE-0001",
    target_unit_id: Optional[str] = None,
    target_obligation_id: Optional[str] = None,
    expected_dealer_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Post a remittance as the owning DealerPrincipal, reading the live version."""
    headers = dealer_headers or make_dealer_principal_headers(dealer_id)
    version = (
        expected_dealer_version
        if expected_dealer_version is not None
        else dealer_version(dealer_id)
    )
    payload = remittance_payload(
        dealer_id, intent, amount_cents, version, payment_reference
    )
    if target_unit_id is not None:
        payload["target_unit_id"] = target_unit_id
    if target_obligation_id is not None:
        payload["target_obligation_id"] = target_obligation_id
    return get_success_data(api_client.create_remittance(payload, headers))


def file_covenant_test(
    dealer_id: str,
    period_end_date: str,
    reported_tangible_net_worth_cents: int,
    reported_ebitda_cents: int,
    reported_interest_expense_cents: int,
    reported_curtailment_paid_cents: int,
    reported_unrestricted_cash_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """File a covenant certificate as CreditRiskManager."""
    payload = covenant_test_payload(
        period_end_date,
        reported_tangible_net_worth_cents,
        reported_ebitda_cents,
        reported_interest_expense_cents,
        reported_curtailment_paid_cents,
        reported_unrestricted_cash_cents,
    )
    return get_success_data(
        api_client.file_covenant_test(dealer_id, payload, headers or CRM)
    )


def issue_remedy(
    dealer_id: str,
    action_type: str,
    reason_code: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Issue a remedy action as CreditRiskManager."""
    return get_success_data(
        api_client.issue_remedy_action(
            dealer_id, remedy_action_payload(action_type, reason_code), headers or CRM
        )
    )


def execute_remedy(
    remedy_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Execute a remedy action as a CreditRiskManager other than the issuer."""
    return get_success_data(api_client.execute_remedy_action(remedy_id, headers or CRM2))


def suspend_line_via_remedy(dealer_id: str, reason_code: str = "COVENANT_BREACH") -> Dict[str, Any]:
    """Drive the dealer's credit line into SUSPENDED through a remedy action."""
    remedy = issue_remedy(dealer_id, "LINE_SUSPENSION", reason_code)
    return execute_remedy(remedy["id"])
