"""Composite setup helpers — multi-step preambles tests can reuse.

ESPP lifecycle moves through many states before interesting claims can
be tested: plan in DRAFT, plan ACTIVE with op1 OPEN, op1 with grant FMV
recorded, an enrollment in ACTIVE, contributions POSTED, clock advanced
past op end, purchase-date FMV recorded, sweep run (op CLOSED), purchase
batch run (op PURCHASED, enrollment COMPLETED, Purchase row + Form3922
materialized, op2 created). Each fixture composes the appropriate
subset; tests focus on assertions, not plumbing.

IDENTITY THREADING — PRD §2.1:

    "When `X-User-Role` is `Participant`, `X-User-ID` is the
    participant's own identifier; the `Participant` entity is
    materialized implicitly, meaning any value supplied via `X-User-ID`
    for this role is treated as an existing participant id. Ownership
    checks on any resource that references a participant ... compare
    that foreign-key value to `X-User-ID` and reject mismatches with
    `ERR_NOT_OWNER`."

Every fixture that creates an Enrollment, Disposition, etc. mints
participant headers via `make_participant_headers(participant_id)` so
the value flows through to the row's `participant_id` and ownership
checks succeed downstream.

SEGREGATION OF DUTIES — PRD §2.4:

    "The `X-User-ID` invoking the run-purchase operation on an offering
    period MUST NOT appear as the poster of any `Contribution` whose
    `enrollment_id` points at an `Enrollment` belonging to that period."

Lifecycle fixtures default to DISTINCT shared ids for the PayrollAgent
(posting contributions) and the PlanAdministrator (running the batch)
so the SoD check is satisfied along the happy path. Tests that probe
SoD failure deliberately collide the two ids.

CLOCK ANCHORING — PRD §2.9:

    "A `SystemClock` singleton with two fields: `current_time` ... and
    `last_sweep_at` ... The clock is read through a dedicated capability
    and is advanced by a `PlanAdministrator`-only capability that
    accepts a `to_timestamp` field; the supplied timestamp must be
    strictly greater than the current value."

Fixtures advance the clock deterministically using PlanAdministrator
headers; they NEVER rely on wall-clock time. Tests that need a
specific moment pass the iso timestamp.

Setup calls use `get_success_data` (lenient 2xx validator) so setup
failures surface as 'Setup failed' rather than confusing assertion
failures downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_days,
    add_seconds,
    add_months,
    add_years,
    clock_advance_payload,
    create_contribution_payload,
    create_disposition_payload,
    create_enrollment_payload,
    create_plan_payload,
    grant_fmv_payload,
    purchase_fmv_payload,
    unique_plan_name,
    unique_operator_id,
)
from .test_users import (
    PLAN_ADMIN_SHARED_ID,
    PAYROLL_AGENT_SHARED_ID,
    TEST_USERS,
    make_participant_headers,
    make_payroll_agent_headers,
    make_plan_admin_headers,
    new_participant_id,
)


# ===========================================================================
# Clock + sweep helpers — PRD §2.9
# ===========================================================================
def get_current_clock() -> Dict[str, Any]:
    """Return the current SystemClock dict."""
    return get_success_data(
        api_client.get_clock(TEST_USERS["plan_admin_headers"]),
    )


def advance_clock_to(target_iso: str,
                     headers: Optional[Dict[str, str]] = None) -> None:
    """Advance the logical clock to `target_iso`.

    PRD §2.9: "the supplied timestamp must be strictly greater than the
    current value". If the clock is already at or beyond target, this
    helper is a no-op (which preserves fixture idempotency across reset).
    """
    clk = get_current_clock()
    if clk.get("current_time", "") >= target_iso:
        return
    h = headers or TEST_USERS["plan_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to_timestamp=target_iso), h,
    )
    get_success_data(resp)


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run the maturation sweep (PRD §2.9)."""
    h = headers or TEST_USERS["plan_admin_headers"]
    return get_success_data(api_client.run_sweep(h))


# ===========================================================================
# Plan lifecycle helpers
# ===========================================================================
def create_plan(
    *,
    name: Optional[str] = None,
    offering_period_months: int = 6,
    effective_date: Optional[str] = None,
    max_contribution_rate_bp: Optional[int] = None,
    annual_accrual_cap_cents: Optional[int] = None,
    lookback_enabled: Optional[bool] = None,
    discount_bp: Optional[int] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a Plan in DRAFT."""
    h = admin_headers or TEST_USERS["plan_admin_headers"]
    payload = create_plan_payload(
        name=name,
        offering_period_months=offering_period_months,
        effective_date=effective_date,
        max_contribution_rate_bp=max_contribution_rate_bp,
        annual_accrual_cap_cents=annual_accrual_cap_cents,
        lookback_enabled=lookback_enabled,
        discount_bp=discount_bp,
    )
    return get_success_data(api_client.create_plan(payload, h))


def activate_plan(plan_id: str,
                  admin_headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    """Transition the plan DRAFT -> ACTIVE.

    PRD §3.1: "Activation transitions the plan from `DRAFT` to `ACTIVE`
    ... As a side effect, the system creates the first offering period
    under the plan: `sequence_number` is set to 1, `start_date` is set
    to the plan's `effective_date`, `end_date` is computed as
    `start_date` plus `offering_period_months` months, and `status` is
    set to `OPEN`."
    """
    h = admin_headers or TEST_USERS["plan_admin_headers"]
    return get_success_data(api_client.activate_plan(plan_id, h))


def list_offering_periods(plan_id: str,
                          headers: Optional[Dict[str, str]] = None,
                          ) -> List[Dict[str, Any]]:
    h = headers or TEST_USERS["plan_admin_headers"]
    resp = api_client.list_offering_periods(plan_id, h)
    data = get_success_data(resp)
    if isinstance(data, dict) and "items" in data:
        return data["items"]
    if isinstance(data, list):
        return data
    # framework's paginated envelope returns `data` as the list directly
    return data


def get_first_open_offering_period(plan_id: str) -> Dict[str, Any]:
    """Find the OPEN OfferingPeriod under a plan. There is at most one."""
    periods = list_offering_periods(plan_id)
    for p in periods:
        if p.get("status") == "OPEN":
            return p
    raise AssertionError(
        f"Setup failed: no OPEN OfferingPeriod under plan {plan_id}"
    )


def create_and_activate_plan(
    *,
    name: Optional[str] = None,
    offering_period_months: int = 6,
    effective_date: Optional[str] = None,
    max_contribution_rate_bp: Optional[int] = None,
    annual_accrual_cap_cents: Optional[int] = None,
    lookback_enabled: Optional[bool] = None,
    discount_bp: Optional[int] = None,
    grant_date_fmv_cents: Optional[int] = None,
    initial_clock_iso: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a plan, activate it, and (optionally) record grant FMV on op1.

    Returns (plan, op1). The clock is advanced to `initial_clock_iso`
    BEFORE plan activation if supplied — PRD §3.1 requires
    `effective_date >= SystemClock.current_time` at activation.

    Because the SystemClock is process-wide and is only allowed to move
    forward (PRD §2.9), fixtures default to deriving `effective_date`
    from the CURRENT clock value rather than from a hardcoded date.
    Otherwise a prior test that advanced the clock past the hardcoded
    effective_date would invalidate every subsequent fixture call.

    PRD §3.2: "the operation accepts a `grant_date_fmv_cents` value and
    is allowed only when the system clock's `current_time` falls on the
    period's `start_date` and `grant_date_fmv_cents` is still null."
    The fixture therefore advances the clock to `start_date` before
    recording grant FMV.
    """
    if initial_clock_iso is not None:
        advance_clock_to(initial_clock_iso, admin_headers)

    # Read the current clock once. PRD §3.1 requires effective_date >=
    # current_time at activation, and PRD §2.9 forbids rewinding the
    # clock. If a previous test advanced the clock past a hardcoded
    # effective_date passed to this fixture, the hardcoded value is no
    # longer usable — fall back to the current clock value. This keeps
    # fixture preconditions valid regardless of test ordering.
    clk = get_current_clock()
    if effective_date is None or effective_date < clk["current_time"]:
        effective_date = clk["current_time"]

    plan = create_plan(
        name=name,
        offering_period_months=offering_period_months,
        effective_date=effective_date,
        max_contribution_rate_bp=max_contribution_rate_bp,
        annual_accrual_cap_cents=annual_accrual_cap_cents,
        lookback_enabled=lookback_enabled,
        discount_bp=discount_bp,
        admin_headers=admin_headers,
    )
    activate_plan(plan["id"], admin_headers)
    op1 = get_first_open_offering_period(plan["id"])

    if grant_date_fmv_cents is not None:
        # Clock must equal start_date for grant-FMV recording.
        advance_clock_to(op1["start_date"], admin_headers)
        op1 = get_success_data(
            api_client.record_grant_fmv(
                plan["id"], op1["id"],
                grant_fmv_payload(grant_date_fmv_cents=grant_date_fmv_cents),
                admin_headers or TEST_USERS["plan_admin_headers"],
            )
        )
    return plan, op1


# ===========================================================================
# Enrollment + contribution helpers
# ===========================================================================
def enroll_participant(
    *,
    offering_period_id: str,
    participant_id: Optional[str] = None,
    contribution_rate_bp: int = 1500,
) -> Tuple[str, Dict[str, Any]]:
    """Create an enrollment for a fresh participant.

    PRD §3.3: "The system records the enrollment with `offering_period_id`
    set to the period in the URL, `participant_id` set to the caller's
    `X-User-ID` ..."

    Returns (participant_id, enrollment).
    """
    pid = participant_id or new_participant_id()
    resp = api_client.create_enrollment(
        offering_period_id,
        create_enrollment_payload(contribution_rate_bp=contribution_rate_bp),
        make_participant_headers(pid),
    )
    return pid, get_success_data(resp)


def post_contribution(
    *,
    enrollment_id: str,
    pay_period_end: str,
    gross_pay_cents: int,
    payroll_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PayrollAgent posts a single contribution. Default payroll id
    differs from the default plan-admin id — segregation of duties
    (PRD §2.4) holds for the lifecycle happy path."""
    h = payroll_headers or TEST_USERS["payroll_agent_headers"]
    resp = api_client.create_contribution(
        enrollment_id,
        create_contribution_payload(
            pay_period_end=pay_period_end,
            gross_pay_cents=gross_pay_cents,
        ),
        h,
    )
    return get_success_data(resp)


def post_contributions_totaling(
    *,
    enrollment_id: str,
    target_amount_cents: int,
    contribution_rate_bp: int,
    base_pay_period_end: str,
    payroll_headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Post a single contribution sized so its `amount_cents` equals the
    target. Picks `gross_pay_cents` from `target_amount * 10000 /
    contribution_rate_bp`. Callers that need multiple rows can call
    `post_contribution` directly.
    """
    gross = target_amount_cents * 10_000 // contribution_rate_bp
    # Sanity: integer division -> the rounded contribution amount equals
    # target only when target * 10000 % rate_bp == 0; callers in our
    # fixtures pick targets that divide evenly.
    return [post_contribution(
        enrollment_id=enrollment_id,
        pay_period_end=base_pay_period_end,
        gross_pay_cents=gross,
        payroll_headers=payroll_headers,
    )]


# ===========================================================================
# Period close + purchase batch — PRD §3.5
# ===========================================================================
def close_period_and_run_purchase(
    *,
    plan_id: str,
    op_id: str,
    purchase_date_fmv_cents: int,
    op_end_date_iso: str,
    payroll_admin_headers: Optional[Dict[str, str]] = None,
    op_version: Optional[int] = None,
    plan_admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Drive op from OPEN through CLOSED to PURCHASED.

    Steps:
      1. Advance the clock to one second AFTER `op_end_date_iso` so the
         FMV-after-end constraint (PRD §3.2) holds.
      2. PATCH purchase-date FMV.
      3. Run the sweep so the period transitions OPEN -> CLOSED
         (PRD §3.2: "when the system clock reaches or passes `end_date`
         and `purchase_date_fmv_cents` has been recorded ... the next
         sweep invocation flips the period to `CLOSED`.").
      4. POST run-purchase as PlanAdministrator with a DIFFERENT id from
         any PayrollAgent that has posted on this op (PRD §2.4 SoD).

    Returns the run-purchase response body. The new op2 is auto-created
    as a side effect (PRD §3.5).
    """
    pa = payroll_admin_headers or TEST_USERS["plan_admin_headers"]
    plan_admin = plan_admin_headers or TEST_USERS["plan_admin_headers"]

    # Step 1 — advance just past end_date so PATCH FMV is allowed.
    # Use +1 second (not +1 day) so the clock lands on the SAME calendar
    # day as op_end_date, which is also the next period's start_date.
    # That keeps grant-FMV recording on the auto-created op2 feasible
    # without rewinding the clock (PRD §2.9 forbids rewind).
    advance_clock_to(add_seconds(op_end_date_iso, 1), plan_admin)
    # Step 2 — PATCH purchase FMV.
    op = get_success_data(
        api_client.get_offering_period(op_id, plan_admin)
    )
    version = op_version if op_version is not None else op.get("version", 1)
    get_success_data(
        api_client.record_purchase_fmv(
            op_id,
            purchase_fmv_payload(
                purchase_date_fmv_cents=purchase_date_fmv_cents,
                version=version,
            ),
            plan_admin,
        )
    )
    # Step 3 — sweep flips OPEN -> CLOSED.
    run_sweep(plan_admin)
    # Step 4 — run purchase batch.
    return get_success_data(
        api_client.run_purchase(op_id, pa)
    )


# ===========================================================================
# Composite fixtures
# ===========================================================================
def setup_active_plan_with_open_period(
    *,
    offering_period_months: int = 6,
    discount_bp: Optional[int] = None,
    lookback_enabled: Optional[bool] = None,
    annual_accrual_cap_cents: Optional[int] = None,
    max_contribution_rate_bp: Optional[int] = None,
    grant_date_fmv_cents: int = 1000,
    effective_date: Optional[str] = None,
    initial_clock_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Plan ACTIVE + op1 OPEN with grant FMV recorded.

    Defaults: 6-month period, default discount/lookback/cap, grant FMV
    = 1000 cents. When `initial_clock_iso`/`effective_date` are not
    supplied, the fixture defers to `create_and_activate_plan` which
    derives `effective_date` from the current clock — making the
    fixture robust to prior tests that advanced the clock forward
    (PRD §2.9 forbids rewinding the clock).
    Returns (plan, op1) with op1 reflecting the grant FMV write.
    """
    return create_and_activate_plan(
        offering_period_months=offering_period_months,
        effective_date=effective_date,
        max_contribution_rate_bp=max_contribution_rate_bp,
        annual_accrual_cap_cents=annual_accrual_cap_cents,
        lookback_enabled=lookback_enabled,
        discount_bp=discount_bp,
        grant_date_fmv_cents=grant_date_fmv_cents,
        initial_clock_iso=initial_clock_iso,
    )


def setup_enrollment_with_contributions(
    *,
    offering_period_months: int = 6,
    discount_bp: Optional[int] = None,
    lookback_enabled: Optional[bool] = None,
    annual_accrual_cap_cents: Optional[int] = None,
    max_contribution_rate_bp: Optional[int] = None,
    grant_date_fmv_cents: int = 1000,
    contribution_rate_bp: int = 1500,
    contribution_amount_cents: int = 17_000,
    effective_date: Optional[str] = None,
    initial_clock_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any]]:
    """Active plan + op1 OPEN with grant FMV + one enrolled participant +
    one POSTED contribution sized so amount_cents == contribution_amount_cents.

    Returns (plan, op1, participant_id, enrollment).
    """
    plan, op1 = setup_active_plan_with_open_period(
        offering_period_months=offering_period_months,
        discount_bp=discount_bp,
        lookback_enabled=lookback_enabled,
        annual_accrual_cap_cents=annual_accrual_cap_cents,
        max_contribution_rate_bp=max_contribution_rate_bp,
        grant_date_fmv_cents=grant_date_fmv_cents,
        effective_date=effective_date,
        initial_clock_iso=initial_clock_iso,
    )
    pid, enrollment = enroll_participant(
        offering_period_id=op1["id"],
        contribution_rate_bp=contribution_rate_bp,
    )
    post_contributions_totaling(
        enrollment_id=enrollment["id"],
        target_amount_cents=contribution_amount_cents,
        contribution_rate_bp=contribution_rate_bp,
        base_pay_period_end=op1["start_date"],
    )
    # Refresh enrollment to pick up version etc.
    enrollment = get_success_data(
        api_client.get_enrollment(enrollment["id"],
                                  TEST_USERS["plan_admin_headers"])
    )
    return plan, op1, pid, enrollment


def setup_purchase_after_run(
    *,
    offering_period_months: int = 6,
    discount_bp: int = 1500,
    lookback_enabled: bool = True,
    annual_accrual_cap_cents: Optional[int] = None,
    grant_date_fmv_cents: int = 1000,
    purchase_date_fmv_cents: int = 2000,
    contribution_rate_bp: int = 1500,
    contribution_amount_cents: int = 8500,
    effective_date: Optional[str] = None,
    initial_clock_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any]]:
    """Drive a complete period through to PURCHASED with one participant.

    Returns (plan, op1_after_purchase, participant_id, purchase_row).
    `op1_after_purchase` is the now-terminal OfferingPeriod (status
    PURCHASED). The purchase row is fetched after the batch.
    """
    plan, op1, pid, enrollment = setup_enrollment_with_contributions(
        offering_period_months=offering_period_months,
        discount_bp=discount_bp,
        lookback_enabled=lookback_enabled,
        annual_accrual_cap_cents=annual_accrual_cap_cents,
        grant_date_fmv_cents=grant_date_fmv_cents,
        contribution_rate_bp=contribution_rate_bp,
        contribution_amount_cents=contribution_amount_cents,
        effective_date=effective_date,
        initial_clock_iso=initial_clock_iso,
    )
    # Run the period through to PURCHASED. Default payroll vs admin ids
    # are distinct (test_users.py); SoD holds.
    close_period_and_run_purchase(
        plan_id=plan["id"],
        op_id=op1["id"],
        purchase_date_fmv_cents=purchase_date_fmv_cents,
        op_end_date_iso=op1["end_date"],
    )
    # Re-fetch terminal op + the purchase row via participant list.
    op_after = get_success_data(
        api_client.get_offering_period(op1["id"],
                                       TEST_USERS["plan_admin_headers"])
    )
    purchases = _list_all_purchases(pid)
    purchase = next(
        (p for p in purchases if p.get("enrollment_id") == enrollment["id"]),
        None,
    )
    if purchase is None:
        raise AssertionError(
            f"Setup failed: no Purchase row found for enrollment "
            f"{enrollment['id']} after run-purchase."
        )
    return plan, op_after, pid, purchase


def _list_all_purchases(participant_id: str) -> List[Dict[str, Any]]:
    """List a participant's purchases, walking pagination."""
    h = make_participant_headers(participant_id)
    out: List[Dict[str, Any]] = []
    offset = 0
    while True:
        resp = api_client.list_purchases(
            participant_id, h, params={"limit": 100, "offset": offset},
        )
        data = get_success_data(resp)
        items = data if isinstance(data, list) else data.get("items", [])
        out.extend(items)
        if len(items) < 100:
            break
        offset += 100
    return out


# ===========================================================================
# Difficulty-design composite fixtures
# ===========================================================================
def setup_two_plans_lookback_vs_no_lookback(
    *,
    grant_date_fmv_cents: int = 1000,
    purchase_date_fmv_cents: int = 2000,
    discount_bp: int = 1500,
    contribution_amount_cents: int = 17_000,
    contribution_rate_bp: int = 1500,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Two parallel plans (P1 lookback_enabled=true, P2 false) with one
    enrollment each, identical contributions, both driven to PURCHASED.
    Used by the purchase_settlement variant difficulty-design instance.

    Returns ({"plan", "op", "participant_id", "purchase"} for each).
    """
    p1_plan, p1_op, p1_pid, p1_purchase = setup_purchase_after_run(
        lookback_enabled=True,
        discount_bp=discount_bp,
        grant_date_fmv_cents=grant_date_fmv_cents,
        purchase_date_fmv_cents=purchase_date_fmv_cents,
        contribution_rate_bp=contribution_rate_bp,
        contribution_amount_cents=contribution_amount_cents,
    )
    p2_plan, p2_op, p2_pid, p2_purchase = setup_purchase_after_run(
        lookback_enabled=False,
        discount_bp=discount_bp,
        grant_date_fmv_cents=grant_date_fmv_cents,
        purchase_date_fmv_cents=purchase_date_fmv_cents,
        contribution_rate_bp=contribution_rate_bp,
        contribution_amount_cents=contribution_amount_cents,
    )
    return (
        {"plan": p1_plan, "op": p1_op,
         "participant_id": p1_pid, "purchase": p1_purchase},
        {"plan": p2_plan, "op": p2_op,
         "participant_id": p2_pid, "purchase": p2_purchase},
    )


def setup_purchase_for_disposition(
    *,
    grant_date_fmv_cents: int = 1000,
    purchase_date_fmv_cents: int = 2000,
    discount_bp: int = 1500,
    contribution_amount_cents: int = 8500,
    contribution_rate_bp: int = 1500,
    lookback_enabled: bool = True,
    effective_date: Optional[str] = None,
    initial_clock_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any]]:
    """A Purchase ready to be disposed against — same return shape as
    setup_purchase_after_run; provided as a named alias for tests.
    """
    return setup_purchase_after_run(
        grant_date_fmv_cents=grant_date_fmv_cents,
        purchase_date_fmv_cents=purchase_date_fmv_cents,
        discount_bp=discount_bp,
        contribution_rate_bp=contribution_rate_bp,
        contribution_amount_cents=contribution_amount_cents,
        lookback_enabled=lookback_enabled,
        effective_date=effective_date,
        initial_clock_iso=initial_clock_iso,
    )


def setup_purchase_with_disposition(
    *,
    disposition_date_iso: Optional[str] = None,
    disposition_regime: Optional[str] = None,
    shares_disposed: int = 10,
    sale_price_per_share_cents: int = 2500,
    purchase_kwargs: Optional[Dict[str, Any]] = None,
    advance_clock_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any],
           Dict[str, Any]]:
    """Create a Purchase then a Disposition against it.

    `advance_clock_iso` (if given) is the clock target BEFORE the
    disposition POST. This lets tests place the disposition in
    QUALIFYING / DISQUALIFYING regimes deterministically.

    Because the SystemClock is monotonic and process-wide (PRD §2.9),
    tests cannot pin absolute grant/purchase dates: a hardcoded
    `effective_date` in `purchase_kwargs` is silently bumped forward
    by the fixture if the clock has already advanced past it. To keep
    the test's INTENT, this fixture interprets the supplied dates as
    relative offsets from the REQUESTED grant date (effective_date in
    purchase_kwargs) and re-projects them onto the ACTUAL grant date
    using the same CALENDAR arithmetic that the implementation uses
    for grant+2y and purchase+1y (so we stay on the same side of the
    classification boundary regardless of leap-year accidents).

    Returns (plan, op_after, participant_id, purchase, disposition).
    """
    pk = dict(purchase_kwargs or {})
    requested_effective = pk.get("effective_date")
    plan, op_after, pid, purchase = setup_purchase_after_run(**pk)

    actual_grant_date = op_after["start_date"]

    # ------------------------------------------------------------------
    # Disposition-date resolution strategy:
    #   (a) `disposition_regime` (preferred): a semantic token
    #       ("qualifying" or "disqualifying") that yields a date computed
    #       directly from `actual_grant_date` using calendar arithmetic
    #       — robust to clock drift.
    #   (b) `disposition_date_iso` (legacy): an absolute date. If the
    #       fixture had to slide `effective_date` forward to satisfy
    #       PRD §3.1 (effective_date >= current_time), the supplied
    #       absolute date is reinterpreted via CALENDAR offset from the
    #       requested grant date so the classification boundary at
    #       grant+2y is preserved across leap years.
    # ------------------------------------------------------------------
    if disposition_regime is not None:
        from .factories import add_days as _add_days
        from .factories import add_years as _add_years
        if disposition_regime == "qualifying":
            # disp >= grant + 2y AND disp >= purchase + 1y (impl evaluates
            # both inclusively via add_years). Land exactly on grant+2y.
            disposition_date_iso = _add_years(actual_grant_date, 2)
        elif disposition_regime == "disqualifying":
            # disp < grant + 2y. Land 1 day before grant+2y (still after
            # purchase_date == grant + offering_period_months).
            disposition_date_iso = _add_days(
                _add_years(actual_grant_date, 2), -1
            )
        else:
            raise ValueError(
                f"Unknown disposition_regime: {disposition_regime}"
            )
        # advance the clock to at-or-after disposition_date.
        if advance_clock_iso is None:
            advance_clock_iso = _add_days(disposition_date_iso, 1)
    elif (
        disposition_date_iso is not None
        and requested_effective is not None
        and actual_grant_date != requested_effective
    ):
        # Pick the calendar anchor closest to the requested target —
        # one of {requested_effective, +6mo, +1y, +18mo, +2y} — and
        # express the supplied date as `anchor + residual_seconds`.
        # Then re-anchor on the corresponding actual-frame anchor.
        # This preserves the test's intent across leap-year accidents
        # while keeping the classification boundary (grant+2y) intact.
        from .factories import (
            add_months as _add_months,
            iso_utc,
            parse_iso as _parse,
        )

        def _project(iso_str: str) -> str:
            req_target = _parse(iso_str)
            best_total_months = 0
            best_residual_abs = None
            best_residual = None
            for total_months in range(0, 36 + 1):  # cover up to 3 years
                req_anchor_iso = _add_months(
                    requested_effective, total_months
                )
                residual = req_target - _parse(req_anchor_iso)
                if (
                    best_residual_abs is None
                    or abs(residual.total_seconds())
                    < best_residual_abs
                ):
                    best_residual_abs = abs(residual.total_seconds())
                    best_residual = residual
                    best_total_months = total_months
            act_anchor_iso = _add_months(
                actual_grant_date, best_total_months
            )
            projected = _parse(act_anchor_iso) + best_residual
            return iso_utc(projected)

        if advance_clock_iso is not None:
            advance_clock_iso = _project(advance_clock_iso)
        disposition_date_iso = _project(disposition_date_iso)

    assert disposition_date_iso is not None, (
        "Either disposition_date_iso or disposition_regime is required."
    )

    if advance_clock_iso is not None:
        advance_clock_to(advance_clock_iso)
    disp = get_success_data(
        api_client.create_disposition(
            create_disposition_payload(
                purchase_id=purchase["id"],
                disposition_date=disposition_date_iso,
                shares_disposed=shares_disposed,
                sale_price_per_share_cents=sale_price_per_share_cents,
            ),
            make_participant_headers(pid),
        )
    )
    return plan, op_after, pid, purchase, disp


def setup_purchase_at_holding_boundary(
    *,
    grant_start_date_iso: str = "2024-01-01T00:00:00.000Z",
    grant_date_fmv_cents: int = 1000,
    purchase_date_fmv_cents: int = 2000,
    discount_bp: int = 1500,
    contribution_amount_cents: int = 8500,
) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any]]:
    """Anchored fixture for boundary-precision tests: grant date is
    exactly `grant_start_date_iso`, purchase date is grant + 6 months.
    Caller advances the clock to the disposition_date itself.
    """
    initial_clock = add_days(grant_start_date_iso, -7)
    return setup_purchase_after_run(
        offering_period_months=6,
        discount_bp=discount_bp,
        lookback_enabled=True,
        grant_date_fmv_cents=grant_date_fmv_cents,
        purchase_date_fmv_cents=purchase_date_fmv_cents,
        contribution_amount_cents=contribution_amount_cents,
        effective_date=grant_start_date_iso,
        initial_clock_iso=initial_clock,
    )


def setup_plan_with_active_enrollments_for_dilution(
    *,
    n_enrollments: int = 5,
    max_contribution_rate_bp: int = 1500,
    annual_accrual_cap_cents: int = 2_500_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """Plan ACTIVE + op1 OPEN with N ACTIVE Enrollments.

    Used by the dilution-preview difficulty-design instance.
    Returns (plan, op1, participant_ids).
    """
    plan, op1 = setup_active_plan_with_open_period(
        offering_period_months=6,
        max_contribution_rate_bp=max_contribution_rate_bp,
        annual_accrual_cap_cents=annual_accrual_cap_cents,
        grant_date_fmv_cents=1000,
    )
    pids: List[str] = []
    for _ in range(n_enrollments):
        pid, _enr = enroll_participant(
            offering_period_id=op1["id"],
            contribution_rate_bp=1000,
        )
        pids.append(pid)
    return plan, op1, pids


def setup_period_at_closed_state(
    *,
    purchase_date_fmv_cents: int = 2000,
    grant_date_fmv_cents: int = 1000,
    contribution_amount_cents: int = 8500,
    contribution_rate_bp: int = 1500,
    discount_bp: int = 1500,
    lookback_enabled: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], str, Dict[str, Any]]:
    """Plan ACTIVE + op1 in CLOSED state (purchase FMV recorded, sweep
    run) with one ACTIVE enrollment + one POSTED contribution. The
    purchase batch has NOT yet been invoked.

    Returns (plan, op1, participant_id, enrollment) with op1 reflecting
    its CLOSED status.
    """
    plan, op1, pid, enrollment = setup_enrollment_with_contributions(
        offering_period_months=6,
        discount_bp=discount_bp,
        lookback_enabled=lookback_enabled,
        grant_date_fmv_cents=grant_date_fmv_cents,
        contribution_rate_bp=contribution_rate_bp,
        contribution_amount_cents=contribution_amount_cents,
    )
    # Advance the clock past end_date so PATCH FMV is allowed.
    advance_clock_to(add_seconds(op1["end_date"], 1))
    op1 = get_success_data(
        api_client.record_purchase_fmv(
            op1["id"],
            purchase_fmv_payload(
                purchase_date_fmv_cents=purchase_date_fmv_cents,
                version=op1.get("version", 1),
            ),
            TEST_USERS["plan_admin_headers"],
        )
    )
    run_sweep()
    op1 = get_success_data(
        api_client.get_offering_period(op1["id"],
                                       TEST_USERS["plan_admin_headers"])
    )
    return plan, op1, pid, enrollment


__all__ = [
    # Clock + sweep
    "get_current_clock",
    "advance_clock_to",
    "run_sweep",
    # Atomic helpers
    "create_plan",
    "activate_plan",
    "list_offering_periods",
    "get_first_open_offering_period",
    "create_and_activate_plan",
    "enroll_participant",
    "post_contribution",
    "post_contributions_totaling",
    "close_period_and_run_purchase",
    # Composite fixtures
    "setup_active_plan_with_open_period",
    "setup_enrollment_with_contributions",
    "setup_purchase_after_run",
    "setup_two_plans_lookback_vs_no_lookback",
    "setup_purchase_for_disposition",
    "setup_purchase_with_disposition",
    "setup_purchase_at_holding_boundary",
    "setup_plan_with_active_enrollments_for_dilution",
    "setup_period_at_closed_state",
]
