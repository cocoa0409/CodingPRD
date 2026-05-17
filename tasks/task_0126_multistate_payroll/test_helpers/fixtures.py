"""Composite setup helpers — multi-step preambles tests can reuse.

The payroll pipeline is long: seed tax brackets -> create employee +
W-4 profile -> create pay period -> add payroll item (implicit
DRAFT paycheck) -> calculate -> approve (different specialist vs
manager X-User-ID) -> mark-paid (third treasurer X-User-ID) -> close
period -> create / finalize / remit monthly remittance period.

IDENTITY THREADING — PRD §2.1 + §2.6:

All four roles are opaque (PRD §2.1 explicit), but PRD §2.6 segregation
of duties requires distinct X-User-IDs across consecutive control
steps on the same artifact. Fixtures default to:

  specialist_headers   (SPECIALIST_ID = 'specialist-001') for calculate
  manager_headers      (MANAGER_ID    = 'manager-001')    for approve
  treasurer_headers    (TREASURER_ID  = 'treasurer-001')  for mark-paid
  manager_headers      (finalize remittance)
  treasurer_headers    (remit remittance)
  manager_headers_alt  (amend remittance)

These three ids are distinct, so the default flow never trips
ERR_SEGREGATION_OF_DUTIES. Tests that want to deliberately trip SOD
pass make_*_headers(user_id) explicitly to align actor ids.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_TAX_YEAR,
    FED_BRACKETS_HEAD_OF_HOUSEHOLD,
    FED_BRACKETS_MARRIED_JOINT,
    FED_BRACKETS_SINGLE,
    LOCAL_FLAT_RATE_BPS_NYC,
    LOCAL_FLAT_RATE_BPS_PHL,
    STATE_BRACKETS_CA_SINGLE,
    STATE_BRACKETS_IL_ANY,
    STATE_BRACKETS_NY_SINGLE,
    STATE_BRACKETS_PA_ANY,
    STATE_BRACKETS_TX_ANY,
)
from .factories import (
    biweekly_pay_period_payload,
    clock_advance_payload,
    create_employee_payload,
    create_garnishment_order_payload,
    create_pay_period_payload,
    create_payroll_item_payload,
    create_remittance_payload,
    create_tax_bracket_table_payload,
    create_w4_profile_payload,
    iso_date_str,
    iso_datetime_str,
    issue_correction_payload,
)
from .test_users import (
    TEST_USERS,
    make_manager_headers,
    make_specialist_headers,
    make_treasurer_headers,
)


# ===========================================================================
# Tier 0: Clock (PRD §3.9)
# ===========================================================================
def advance_clock_to(iso_instant: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Optional[Dict[str, Any]]:
    """POST /_clock/advance to_iso=<instant>. PRD §3.9 restricts to
    PayrollManager."""
    headers = headers or TEST_USERS["manager_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to_iso=iso_instant), headers,
    )
    try:
        return get_success_data(resp)
    except Exception:
        return None


def advance_clock_days(days: int,
                       *,
                       base: date = date(2024, 6, 1),
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Optional[Dict[str, Any]]:
    """Convenience wrapper that advances the server clock to
    base + days at 12:00:00 UTC. Used for termination-window tests."""
    from datetime import datetime, time, timezone

    when = datetime.combine(base + timedelta(days=days),
                            time(12, 0, 0), tzinfo=timezone.utc)
    return advance_clock_to(iso_datetime_str(when), headers=headers)


# ===========================================================================
# Tier 1: Tax bracket seeding (PRD §3.9)
# ===========================================================================
def seed_tax_bracket(
    *,
    jurisdiction: str,
    filing_status: str,
    tax_year: int,
    brackets: List[Dict[str, Any]],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tax-bracket-tables, by PayrollManager (PRD §3.9)."""
    headers = headers or TEST_USERS["manager_headers"]
    payload = create_tax_bracket_table_payload(
        jurisdiction=jurisdiction,
        filing_status=filing_status,
        tax_year=tax_year,
        brackets=brackets,
    )
    resp = api_client.create_tax_bracket_table(payload, headers)
    return get_success_data(resp)


def seed_all_tax_brackets(tax_year: int = DEFAULT_TAX_YEAR) -> List[Dict[str, Any]]:
    """Idempotent-style seed for every bracket combination needed by
    tests: FEDERAL × {SINGLE, MARRIED_JOINT, HEAD_OF_HOUSEHOLD},
    CA SINGLE, NY SINGLE, IL ANY, PA ANY, TX ANY, NYC ANY, PHL ANY.

    Subsequent calls in the same test session may produce duplicate
    seed rows but the implementation MAY tolerate that; this fixture
    swallows individual failures so a re-seed in a later test does
    not blow up. Returns the list of successful seed responses.
    """
    headers = TEST_USERS["manager_headers"]
    seeds: List[Dict[str, Any]] = []

    pairs = [
        ("FEDERAL", "SINGLE", FED_BRACKETS_SINGLE),
        ("FEDERAL", "MARRIED_JOINT", FED_BRACKETS_MARRIED_JOINT),
        ("FEDERAL", "HEAD_OF_HOUSEHOLD", FED_BRACKETS_HEAD_OF_HOUSEHOLD),
        ("CA", "SINGLE", STATE_BRACKETS_CA_SINGLE),
        ("NY", "SINGLE", STATE_BRACKETS_NY_SINGLE),
        ("IL", "ANY", STATE_BRACKETS_IL_ANY),
        ("PA", "ANY", STATE_BRACKETS_PA_ANY),
        ("TX", "ANY", STATE_BRACKETS_TX_ANY),
        (
            "NYC",
            "ANY",
            [
                {
                    "lower_cents": 0,
                    "upper_cents_or_null": None,
                    "rate_bps": LOCAL_FLAT_RATE_BPS_NYC,
                },
            ],
        ),
        (
            "PHL",
            "ANY",
            [
                {
                    "lower_cents": 0,
                    "upper_cents_or_null": None,
                    "rate_bps": LOCAL_FLAT_RATE_BPS_PHL,
                },
            ],
        ),
    ]
    for jurisdiction, filing_status, brackets in pairs:
        try:
            seeds.append(seed_tax_bracket(
                jurisdiction=jurisdiction,
                filing_status=filing_status,
                tax_year=tax_year,
                brackets=brackets,
                headers=headers,
            ))
        except Exception:
            # Best-effort: a duplicate or rejection on re-seed is okay.
            pass
    return seeds


# ===========================================================================
# Tier 2: Employee + W-4 (PRD §3.1)
# ===========================================================================
def create_employee(
    *,
    full_name: Optional[str] = None,
    hire_date: Optional[str] = None,
    work_state: str = "TX",
    work_locality: Optional[str] = None,
    hourly_rate_cents: int = 12_500,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /employees, by PayrollSpecialist or PayrollManager."""
    headers = headers or TEST_USERS["specialist_headers"]
    payload = create_employee_payload(
        full_name=full_name,
        hire_date=hire_date,
        work_state=work_state,
        work_locality=work_locality,
        hourly_rate_cents=hourly_rate_cents,
    )
    resp = api_client.create_employee(payload, headers)
    return get_success_data(resp)


def terminate_employee(
    employee_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /employees/{id}/terminate, by PayrollManager (PRD §3.1)."""
    headers = headers or TEST_USERS["manager_headers"]
    body: Dict[str, Any] = {}
    if version is not None:
        body["version"] = version
    resp = api_client.terminate_employee(employee_id, headers, body)
    return get_success_data(resp)


def create_w4_profile(
    employee_id: str,
    effective_pay_period_id: str,
    *,
    filing_status: str = "SINGLE",
    dependents_amount_cents: Optional[int] = None,
    other_income_cents: Optional[int] = None,
    additional_withholding_cents: Optional[int] = None,
    state_allowances: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /employees/{id}/w4-profiles, by PayrollSpecialist."""
    headers = headers or TEST_USERS["specialist_headers"]
    payload = create_w4_profile_payload(
        effective_pay_period_id=effective_pay_period_id,
        filing_status=filing_status,
        dependents_amount_cents=dependents_amount_cents,
        other_income_cents=other_income_cents,
        additional_withholding_cents=additional_withholding_cents,
        state_allowances=state_allowances,
    )
    resp = api_client.create_w4_profile(employee_id, payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Pay period + payroll item (PRD §3.2, §3.3)
# ===========================================================================
def create_pay_period(
    *,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    pay_date: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pay-periods, by PayrollSpecialist (PRD §3.2)."""
    headers = headers or TEST_USERS["specialist_headers"]
    payload = create_pay_period_payload(
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
    )
    resp = api_client.create_pay_period(payload, headers)
    return get_success_data(resp)


def create_biweekly_pay_period(
    start: date,
    *,
    pay_offset_days: int = 5,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Convenience: create a 14-day biweekly pay period starting at
    `start`. The standard PRD §3.4 PAY_PERIODS_PER_YEAR (26) assumes
    biweekly cycles; tests use this shape almost universally.
    """
    headers = headers or TEST_USERS["specialist_headers"]
    payload = biweekly_pay_period_payload(
        start, pay_offset_days=pay_offset_days,
    )
    resp = api_client.create_pay_period(payload, headers)
    return get_success_data(resp)


def create_payroll_item(
    period_id: str,
    employee_id: str,
    *,
    regular_hours: Optional[float] = None,
    overtime_hours: Optional[float] = None,
    double_hours: Optional[float] = None,
    retro_adjustment_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pay-periods/{periodId}/payroll-items. Also creates the
    implicit DRAFT Paycheck per PRD §3.3."""
    headers = headers or TEST_USERS["specialist_headers"]
    payload = create_payroll_item_payload(
        employee_id=employee_id,
        regular_hours=regular_hours,
        overtime_hours=overtime_hours,
        double_hours=double_hours,
        retro_adjustment_cents=retro_adjustment_cents,
    )
    resp = api_client.create_payroll_item(period_id, payload, headers)
    return get_success_data(resp)


def lock_pay_period(period_id: str,
                     *,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """POST /pay-periods/{id}/lock, by PayrollSpecialist (PRD §3.2)."""
    headers = headers or TEST_USERS["specialist_headers"]
    resp = api_client.lock_pay_period(period_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 4: Paycheck retrieval (the PayrollItem creation also returns it)
# ===========================================================================
def get_paycheck_for_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Locate the DRAFT Paycheck that was implicitly created when a
    PayrollItem was attached. The PayrollItem response carries
    pay_period_id and employee_id; we then list /paychecks filtered by
    those two fields.
    """
    headers = TEST_USERS["specialist_headers"]
    resp = api_client.list_paychecks(headers, params={
        "pay_period_id": item["pay_period_id"],
        "employee_id": item["employee_id"],
    })
    data = get_success_data(resp)
    # Listings return arrays; pick the non-correction draft.
    if isinstance(data, list):
        for pc in data:
            if pc.get("payroll_item_id") == item["id"]:
                return pc
        if data:
            return data[0]
    raise AssertionError(
        f"could not resolve paycheck for payroll item {item['id']!r}; "
        f"list returned: {data!r}",
    )


def get_paycheck(paycheck_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["specialist_headers"]
    resp = api_client.get_paycheck(paycheck_id, headers)
    return get_success_data(resp)


def get_employee(employee_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["specialist_headers"]
    resp = api_client.get_employee(employee_id, headers)
    return get_success_data(resp)


def get_pay_period(period_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["specialist_headers"]
    resp = api_client.get_pay_period(period_id, headers)
    return get_success_data(resp)


def get_garnishment_order(order_id: str,
                            headers: Optional[Dict[str, str]] = None,
                            ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["specialist_headers"]
    resp = api_client.get_garnishment_order(order_id, headers)
    return get_success_data(resp)


def get_remittance_period(remit_id: str,
                            headers: Optional[Dict[str, str]] = None,
                            ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["specialist_headers"]
    resp = api_client.get_remittance_period(remit_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 5: Paycheck lifecycle shortcuts (PRD §3.4, §3.6, §3.7)
# ===========================================================================
def calculate_paycheck(paycheck_id: str,
                       *,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """POST /paychecks/{id}/calculate — default specialist."""
    headers = headers or TEST_USERS["specialist_headers"]
    resp = api_client.calculate_paycheck(paycheck_id, headers)
    return get_success_data(resp)


def approve_paycheck(paycheck_id: str,
                     *,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """POST /paychecks/{id}/approve — default manager whose X-User-ID
    differs from the default specialist used by calculate."""
    headers = headers or TEST_USERS["manager_headers"]
    resp = api_client.approve_paycheck(paycheck_id, headers)
    return get_success_data(resp)


def mark_paid_paycheck(paycheck_id: str,
                       *,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """POST /paychecks/{id}/mark-paid — default treasurer whose
    X-User-ID differs from both default specialist and default
    manager."""
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.mark_paid_paycheck(paycheck_id, headers)
    return get_success_data(resp)


def issue_correction(paycheck_id: str,
                     target_pay_period_id: str,
                     *,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """POST /paychecks/{id}/issue-correction. Returns the response
    data — implementations may return the source paycheck, the new
    draft, or a wrapper. The list /paychecks endpoint lets callers
    re-discover whichever they need."""
    headers = headers or TEST_USERS["specialist_headers"]
    resp = api_client.issue_correction_paycheck(
        paycheck_id,
        issue_correction_payload(target_pay_period_id=target_pay_period_id),
        headers,
    )
    return get_success_data(resp)


def find_correction_paycheck(*, source_paycheck_id: str,
                              target_pay_period_id: str,
                              ) -> Dict[str, Any]:
    """After /issue-correction the new DRAFT correction Paycheck is
    attached to target_pay_period_id with is_retro_correction=true and
    correction_of_paycheck_id pointing at the source. Look it up.
    """
    headers = TEST_USERS["specialist_headers"]
    resp = api_client.list_paychecks(headers, params={
        "pay_period_id": target_pay_period_id,
    })
    data = get_success_data(resp)
    if not isinstance(data, list):
        raise AssertionError(
            f"expected list of paychecks, got {type(data).__name__}"
        )
    candidates = [
        pc for pc in data
        if pc.get("correction_of_paycheck_id") == source_paycheck_id
    ]
    if not candidates:
        # Implementations might not echo correction_of_paycheck_id in
        # list listings — fall back to is_retro_correction marker.
        candidates = [
            pc for pc in data if pc.get("is_retro_correction") is True
        ]
    assert candidates, (
        f"no correction paycheck found for source "
        f"{source_paycheck_id!r} in target period "
        f"{target_pay_period_id!r}"
    )
    return candidates[0]


# ===========================================================================
# Tier 6: Garnishment orders (PRD §3.5)
# ===========================================================================
def create_garnishment_order(
    employee_id: str,
    *,
    order_type: str = "CREDITOR",
    total_owed_cents: int = 500_000,
    cap_pct_of_disposable: int = 15,
    effective_pay_date: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /garnishment-orders, by PayrollManager (PRD §3.5)."""
    headers = headers or TEST_USERS["manager_headers"]
    payload = create_garnishment_order_payload(
        employee_id=employee_id,
        order_type=order_type,
        total_owed_cents=total_owed_cents,
        cap_pct_of_disposable=cap_pct_of_disposable,
        effective_pay_date=effective_pay_date,
    )
    resp = api_client.create_garnishment_order(payload, headers)
    return get_success_data(resp)


def release_garnishment_order(order_id: str,
                                *,
                                headers: Optional[Dict[str, str]] = None,
                                ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["manager_headers"]
    resp = api_client.release_garnishment_order(order_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 7: Remittance periods (PRD §3.10)
# ===========================================================================
def create_remittance_period(
    *,
    tax_year: int = DEFAULT_TAX_YEAR,
    tax_month: int = 6,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["manager_headers"]
    resp = api_client.create_remittance_period(
        create_remittance_payload(
            tax_year=tax_year, tax_month=tax_month,
        ),
        headers,
    )
    return get_success_data(resp)


def finalize_remittance(remit_id: str,
                         *,
                         headers: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["manager_headers"]
    resp = api_client.finalize_remittance(remit_id, headers)
    return get_success_data(resp)


def remit_remittance(remit_id: str,
                       *,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["treasurer_headers"]
    resp = api_client.remit_remittance(remit_id, headers)
    return get_success_data(resp)


def amend_remittance(remit_id: str,
                       *,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """POST /remittance-periods/{id}/amend. PRD §2.6: SOD says the
    amender's X-User-ID must differ from the original finalizer; the
    post-amend remit must differ from both. We default to
    manager_headers_alt so a fixture that finalizes with the primary
    manager and amends afterwards stays SOD-clean."""
    headers = headers or TEST_USERS["manager_headers_alt"]
    resp = api_client.amend_remittance(remit_id, headers)
    return get_success_data(resp)


def reopen_remittance(remit_id: str,
                        *,
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["manager_headers"]
    resp = api_client.reopen_remittance(remit_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 8: COMPOSITE setups — multi-step preambles
# ===========================================================================

def setup_world(tax_year: int = DEFAULT_TAX_YEAR) -> None:
    """One-shot global tax-bracket seed at the start of a test."""
    seed_all_tax_brackets(tax_year=tax_year)


def setup_employee_with_w4(
    *,
    work_state: str = "TX",
    work_locality: Optional[str] = None,
    hourly_rate_cents: int = 12_500,
    hire_date: Optional[str] = None,
    period_start: date = date(2024, 6, 3),
    pay_offset_days: int = 5,
    filing_status: str = "SINGLE",
    w4_overrides: Optional[Dict[str, Any]] = None,
    seed_brackets: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create:
        - one employee (default TX/NONE locality)
        - one biweekly pay period starting at `period_start`
        - one W-4 effective at that pay period (SINGLE by default)

    Returns (employee, pay_period, w4_profile).
    """
    if seed_brackets:
        setup_world()
    employee = create_employee(
        work_state=work_state,
        work_locality=work_locality,
        hourly_rate_cents=hourly_rate_cents,
        hire_date=hire_date or iso_date_str(date(2024, 1, 1)),
    )
    pay_period = create_biweekly_pay_period(
        period_start, pay_offset_days=pay_offset_days,
    )
    extras = dict(w4_overrides or {})
    w4 = create_w4_profile(
        employee["id"], pay_period["id"],
        filing_status=filing_status,
        **extras,
    )
    return employee, pay_period, w4


def setup_draft_paycheck(
    *,
    employee: Optional[Dict[str, Any]] = None,
    pay_period: Optional[Dict[str, Any]] = None,
    regular_hours: float = 16.0,
    overtime_hours: Optional[float] = None,
    double_hours: Optional[float] = None,
    retro_adjustment_cents: Optional[int] = None,
    work_state: str = "TX",
    work_locality: Optional[str] = None,
    hourly_rate_cents: int = 12_500,
    filing_status: str = "SINGLE",
    period_start: date = date(2024, 6, 3),
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Create employee + pay period + W-4 + payroll item (which also
    spawns the implicit DRAFT Paycheck).

    Returns (employee, pay_period, w4_profile, payroll_item, paycheck).
    """
    if employee is None or pay_period is None:
        employee, pay_period, w4 = setup_employee_with_w4(
            work_state=work_state,
            work_locality=work_locality,
            hourly_rate_cents=hourly_rate_cents,
            filing_status=filing_status,
            period_start=period_start,
        )
    else:
        # Re-resolve a W-4: assume tests pass an existing W-4 by
        # creating one against the supplied pay_period.
        w4 = create_w4_profile(
            employee["id"], pay_period["id"],
            filing_status=filing_status,
        )
    item = create_payroll_item(
        pay_period["id"], employee["id"],
        regular_hours=regular_hours,
        overtime_hours=overtime_hours,
        double_hours=double_hours,
        retro_adjustment_cents=retro_adjustment_cents,
    )
    paycheck = get_paycheck_for_item(item)
    return employee, pay_period, w4, item, paycheck


def setup_calculated_paycheck(**kwargs) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """setup_draft_paycheck then /calculate. Returns
    (employee, pay_period, w4_profile, payroll_item, paycheck_after_calc).
    """
    emp, pp, w4, item, pc = setup_draft_paycheck(**kwargs)
    pc = calculate_paycheck(pc["id"])
    return emp, pp, w4, item, pc


def setup_approved_paycheck(**kwargs) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """setup_calculated_paycheck then /approve. Calculator and approver
    use distinct default X-User-IDs to satisfy PRD §2.6 SOD."""
    emp, pp, w4, item, pc = setup_calculated_paycheck(**kwargs)
    pc = approve_paycheck(pc["id"])
    return emp, pp, w4, item, pc


def setup_paid_paycheck(**kwargs) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """setup_approved_paycheck then /mark-paid. All three actors are
    distinct.

    NOTE: PRD §3.6 requires the owning PayPeriod to transition LOCKED
    before marking-paid is allowed to auto-close it. This fixture
    locks the period AFTER calculate but BEFORE mark-paid.
    """
    emp, pp, w4, item, pc = setup_calculated_paycheck(**kwargs)
    pc = approve_paycheck(pc["id"])
    # Lock now while the period is still OPEN; lock requires every
    # paycheck to be CALCULATED or later — APPROVED qualifies.
    lock_pay_period(pp["id"])
    pc = mark_paid_paycheck(pc["id"])
    pp = get_pay_period(pp["id"])
    return emp, pp, w4, item, pc


def setup_paid_paycheck_with_period_closed(**kwargs) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """Same as setup_paid_paycheck, but post-condition asserts the
    PayPeriod has auto-transitioned to CLOSED."""
    return setup_paid_paycheck(**kwargs)


# ---------------------------------------------------------------------------
# Composite recipes from SCAFFOLD_DIFFICULTY_DESIGN.yaml
# ---------------------------------------------------------------------------
def setup_retro_pay_paycheck() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """Difficulty recipe: dual_variant_calc /
    paycheck_withholding_supplemental_vs_aggregate_on_retro_pay.

    Employee TX/NONE, hourly 12500, hire 2024-01-01. W-4 SINGLE all
    zeros. PayPeriod 2024-06-03..2024-06-16 paid 2024-06-21. PayrollItem
    regular_hours=16, retro_adjustment_cents=100000 (so gross = 16*12500
    + 100000 = 300000).
    """
    return setup_draft_paycheck(
        work_state="TX",
        hourly_rate_cents=12_500,
        filing_status="SINGLE",
        period_start=date(2024, 6, 3),
        regular_hours=16.0,
        retro_adjustment_cents=100_000,
    )


def setup_ytd_at_ss_cap_minus(*, room: int) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """Difficulty recipe: boundary_precision_check /
    ss_wage_base_equality_zero_room_at_calculate (and the dual-
    variant FICA test).

    Drive Employee.ytd_social_security_wages_cents to (SS_WAGE_BASE -
    room) by approving a synthetic prior paycheck whose gross equals
    (SS_WAGE_BASE - room). Then start a fresh PayPeriod for the
    follow-up test paycheck whose calculate is the trigger under
    assertion.

    Returns (employee, second_pay_period, second_w4, second_item,
    second_paycheck_draft).
    """
    seed_target = 16_830_000 - room  # SS_WAGE_BASE - room
    # First period — biweekly starting Jan 1 2024.
    employee, first_pp, first_w4 = setup_employee_with_w4(
        work_state="TX",
        hourly_rate_cents=seed_target,
        filing_status="SINGLE",
        period_start=date(2024, 1, 1),
        pay_offset_days=5,
    )
    # Single hour of work at the synthetic hourly rate produces a gross
    # equal to seed_target. (16 hours × 1 cent doesn't reach the cap.)
    first_item = create_payroll_item(
        first_pp["id"], employee["id"], regular_hours=1.0,
    )
    first_pc = get_paycheck_for_item(first_item)
    first_pc = calculate_paycheck(first_pc["id"])
    first_pc = approve_paycheck(first_pc["id"])
    # No need to mark-paid for ytd updates: approval already wrote the
    # ledger entry per PRD §2.9.
    # Second period — same employee, new period, new W-4 still active.
    second_pp = create_biweekly_pay_period(date(2024, 11, 25))
    # Existing W-4 already covers this pay_date.
    second_item = create_payroll_item(
        second_pp["id"], employee["id"], regular_hours=16.0,
    )
    second_pc = get_paycheck_for_item(second_item)
    return employee, second_pp, first_w4, second_item, second_pc


def setup_two_garnishments_for_employee(
    employee_id: str,
    *,
    g1_type: str = "CHILD_SUPPORT",
    g1_cap_pct: int = 20,
    g1_owed: int = 500_000,
    g1_effective: str = "2024-01-01",
    g2_type: str = "CREDITOR",
    g2_cap_pct: int = 15,
    g2_owed: int = 500_000,
    g2_effective: str = "2024-01-01",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Difficulty recipe: combinatorial_formula /
    garnishment_waterfall_three_input_nonlinear_min_chain.

    Returns (g1, g2)."""
    g1 = create_garnishment_order(
        employee_id,
        order_type=g1_type,
        total_owed_cents=g1_owed,
        cap_pct_of_disposable=g1_cap_pct,
        effective_pay_date=g1_effective,
    )
    g2 = create_garnishment_order(
        employee_id,
        order_type=g2_type,
        total_owed_cents=g2_owed,
        cap_pct_of_disposable=g2_cap_pct,
        effective_pay_date=g2_effective,
    )
    return g1, g2


def setup_remittance_finalized_then_remitted(
    *,
    tax_year: int = DEFAULT_TAX_YEAR,
    tax_month: int = 6,
    headers_finalize: Optional[Dict[str, str]] = None,
    headers_remit: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Walk a RemittancePeriod from DRAFT → FINALIZED → REMITTED.

    Caller is responsible for having every PayPeriod in (tax_year,
    tax_month) in CLOSED and every Paycheck in APPROVED/PAID/VOIDED
    BEFORE invoking this helper, or finalize will reject with
    ERR_OPEN_PAY_PERIODS_IN_MONTH / ERR_UNAPPROVED_PAYCHECKS_IN_MONTH.

    Returns the RemittancePeriod after the /remit transition.
    """
    remit = create_remittance_period(
        tax_year=tax_year, tax_month=tax_month,
    )
    remit = finalize_remittance(remit["id"], headers=headers_finalize)
    remit = remit_remittance(remit["id"], headers=headers_remit)
    return remit


def setup_full_paid_cycle_for_month(
    *,
    work_state: str = "TX",
    work_locality: Optional[str] = None,
    hourly_rate_cents: int = 12_500,
    period_start: date = date(2024, 6, 3),
    regular_hours: float = 16.0,
    filing_status: str = "SINGLE",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Run the full lifecycle for one employee through one biweekly
    pay period: create employee + W-4 + period + item + calculate +
    approve + lock + mark-paid. The pay period auto-closes when the
    last paycheck is paid.

    Returns (employee, pay_period_after_close, paycheck_after_paid).
    """
    emp, pp, w4, item, pc = setup_paid_paycheck(
        work_state=work_state,
        work_locality=work_locality,
        hourly_rate_cents=hourly_rate_cents,
        period_start=period_start,
        regular_hours=regular_hours,
        filing_status=filing_status,
    )
    return emp, pp, pc


__all__ = [
    # Tier 0
    "advance_clock_to",
    "advance_clock_days",
    # Tier 1
    "seed_tax_bracket",
    "seed_all_tax_brackets",
    # Tier 2
    "create_employee",
    "terminate_employee",
    "create_w4_profile",
    # Tier 3
    "create_pay_period",
    "create_biweekly_pay_period",
    "create_payroll_item",
    "lock_pay_period",
    # Tier 4
    "get_paycheck_for_item",
    "get_paycheck",
    "get_employee",
    "get_pay_period",
    "get_garnishment_order",
    "get_remittance_period",
    # Tier 5
    "calculate_paycheck",
    "approve_paycheck",
    "mark_paid_paycheck",
    "issue_correction",
    "find_correction_paycheck",
    # Tier 6
    "create_garnishment_order",
    "release_garnishment_order",
    # Tier 7
    "create_remittance_period",
    "finalize_remittance",
    "remit_remittance",
    "amend_remittance",
    "reopen_remittance",
    # Tier 8 composite
    "setup_world",
    "setup_employee_with_w4",
    "setup_draft_paycheck",
    "setup_calculated_paycheck",
    "setup_approved_paycheck",
    "setup_paid_paycheck",
    "setup_paid_paycheck_with_period_closed",
    "setup_retro_pay_paycheck",
    "setup_ytd_at_ss_cap_minus",
    "setup_two_garnishments_for_employee",
    "setup_remittance_finalized_then_remitted",
    "setup_full_paid_cycle_for_month",
]
