"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    Claimant: entity-backed. "Ownership checks on any resource that
    references a Claimant ... compare the resource's owning claimant_id
    ... to X-User-ID. A mismatch yields ERR_NOT_OWNER."

    EmployerAgent: entity-backed. "Ownership checks on any resource
    that references an Employer (notably EmployerCharge lists and the
    relief endpoint) compare the resource's employer_id to X-User-ID."

After a Claimant is created, fixtures MUST use
make_claimant_headers(claimant["id"]) when issuing claimant-scoped
calls. After an Employer is created, EmployerAgent calls against that
employer MUST use make_employer_agent_headers(employer["id"]).
Never fall back to the shared TEST_USERS["claimant_headers"] or
TEST_USERS["employer_agent_headers"] constants for ownership-gated
operations.

CLOCK ANCHORING — PRD §2.9:

    "Every time-sensitive decision in the system ... reads from
    SystemClock.now. An admin-only test-driving capability advances the
    clock by a supplied number of seconds."

The logical clock is shared across all tests within the process. Each
fixture anchors timing to the current clock value.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_days,
    add_quarters,
    adjudicate_claim_payload,
    apply_extension_payload,
    audit_weekly_certification_payload,
    clock_advance_payload,
    create_appeal_payload,
    create_claim_payload,
    create_claimant_payload,
    create_employer_payload,
    create_pandemic_extension_payload,
    create_wage_record_payload,
    create_weekly_certification_payload,
    date_to_iso,
    decide_appeal_payload,
    iso_utc,
    n_work_search_entries,
    next_saturday_strictly_after,
    parse_iso,
    previous_saturday_on_or_before,
    quarter_of,
    relieve_charge_payload,
    repay_overpayment_payload,
    utcnow,
    waive_overpayment_payload,
    work_search_entry,
    write_off_payload,
)
from .test_users import (
    TEST_USERS,
    make_adjudicator_headers,
    make_appeal_officer_headers,
    make_claimant_headers,
    make_employer_agent_headers,
    make_system_admin_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.9
# ===========================================================================
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: Optional[datetime] = None


def _seed_clock_from_server() -> datetime:
    """Read the server's current clock and cache it. Used the first time
    a fixture touches the clock so the test process is in sync."""
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK is None:
            try:
                resp = api_client.get_clock(
                    TEST_USERS["system_admin_headers"],
                )
                body = resp.json()
                data = body.get("data") if isinstance(body, dict) else None
                if isinstance(data, dict) and data.get("now"):
                    _CURRENT_CLOCK = parse_iso(data["now"])
                else:
                    _CURRENT_CLOCK = utcnow()
            except Exception:
                _CURRENT_CLOCK = utcnow()
        return _CURRENT_CLOCK


def current_clock() -> datetime:
    return _seed_clock_from_server()


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def advance_clock_by_seconds(seconds: int) -> str:
    """PRD §2.9: 'An admin-only test-driving capability advances the
    clock by a supplied number of seconds.'"""
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        base = _CURRENT_CLOCK if _CURRENT_CLOCK is not None else utcnow()
        resp = api_client.advance_clock(
            clock_advance_payload(seconds),
            TEST_USERS["system_admin_headers"],
        )
        get_success_data(resp)
        _CURRENT_CLOCK = base + timedelta(seconds=seconds)
        return iso_utc(_CURRENT_CLOCK)


def advance_clock_by_days(days: int) -> str:
    return advance_clock_by_seconds(days * 86400)


def advance_clock_by_hours(hours: float) -> str:
    return advance_clock_by_seconds(int(hours * 3600))


def reset_clock_tracker_to(dt: datetime) -> None:
    """Force the test-process's clock tracker to dt (called by conftest)."""
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt


# ===========================================================================
# Claimant primitives — PRD §3.1
# ===========================================================================
def create_claimant(**overrides) -> Dict[str, Any]:
    """PRD §3.1: 'A claimant identity is created with a payload supplying
    ssn_last4 ... full_name, state_residence ... and date_of_birth.'

    Self-registration is permitted to the Claimant role. We use
    SystemAdmin here (also permitted by §3.1) so the created Claimant
    has a well-known opaque creator — the resulting Claimant.id is then
    used to mint claimant-scoped headers via make_claimant_headers().
    """
    payload = create_claimant_payload(**overrides)
    resp = api_client.create_claimant(
        payload, TEST_USERS["system_admin_headers"],
    )
    return get_success_data(resp)


def get_claimant(claimant_id: str) -> Dict[str, Any]:
    """Read a Claimant as SystemAdmin (no ownership check)."""
    resp = api_client.get_claimant(
        claimant_id, TEST_USERS["system_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Employer primitives — PRD §3.1
# ===========================================================================
def create_employer(
    reserve_ratio_basis_cents: int = 1_000_000,
    taxable_payroll_cents: int = 10_000_000,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'Employer registration is admin-only.'"""
    payload = create_employer_payload(
        reserve_ratio_basis_cents=reserve_ratio_basis_cents,
        taxable_payroll_cents=taxable_payroll_cents,
        **overrides,
    )
    resp = api_client.create_employer(
        payload, TEST_USERS["system_admin_headers"],
    )
    return get_success_data(resp)


def get_employer(employer_id: str) -> Dict[str, Any]:
    """Read an Employer as SystemAdmin."""
    resp = api_client.get_employer(
        employer_id, TEST_USERS["system_admin_headers"],
    )
    return get_success_data(resp)


def list_employer_charges(
    employer_id: str,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    resp = api_client.list_employer_charges(
        employer_id, TEST_USERS["system_admin_headers"], params=params,
    )
    body = resp.json()
    return list(body.get("data") or [])


# ===========================================================================
# WageRecord primitives — PRD §3.1
# ===========================================================================
def post_wage_record(
    claimant_id: str,
    employer_id: str,
    quarter_year: int,
    quarter_index: int,
    wages_cents: int,
) -> Dict[str, Any]:
    """PRD §3.1: 'Quarterly wage records are admin-filed and immutable
    once written.'"""
    resp = api_client.create_wage_record(
        claimant_id,
        create_wage_record_payload(
            employer_id=employer_id,
            quarter_year=quarter_year,
            quarter_index=quarter_index,
            wages_cents=wages_cents,
        ),
        TEST_USERS["system_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Claim primitives — PRD §3.2
# ===========================================================================
def create_claim(claimant: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.2: 'A claimant opens a new claim by posting under their own
    claimant resource.'

    Identity threading: this call records claimant_id and is subject to
    the ownership check on subsequent claim operations. We mint headers
    via make_claimant_headers(claimant["id"]) so X-User-ID matches the
    Claimant.id about to be recorded on the new Claim.
    """
    headers = make_claimant_headers(claimant["id"])
    resp = api_client.create_claim(
        claimant["id"], create_claim_payload(), headers,
    )
    return get_success_data(resp)


def submit_claim(claim: Dict[str, Any], claimant_id: str) -> Dict[str, Any]:
    """PRD §3.2: 'The next action is to submit the draft for
    adjudication, transitioning DRAFT → PENDING_ADJUDICATION.'"""
    headers = make_claimant_headers(claimant_id)
    resp = api_client.submit_claim(claim["id"], headers)
    return get_success_data(resp)


def adjudicate_claim(
    claim_id: str,
    decision: str,
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    """PRD §3.2: 'A PENDING_ADJUDICATION claim is decided by an
    Adjudicator.'"""
    headers = make_adjudicator_headers(adjudicator_id)
    resp = api_client.adjudicate_claim(
        claim_id, adjudicate_claim_payload(decision), headers,
    )
    return get_success_data(resp)


def get_claim(claim_id: str) -> Dict[str, Any]:
    """Read a claim as SystemAdmin."""
    resp = api_client.get_claim(
        claim_id, TEST_USERS["system_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Wage staging — PRD §3.2 base-period selection
# ===========================================================================
def base_period_quarters_at(now: datetime) -> Dict[str, List[Tuple[int, int]]]:
    """Compute the STANDARD and ALTERNATE base-period quarter tuples
    relative to the filing quarter implied by `now`.

    PRD §3.2: 'STANDARD base period = quarters [filing_quarter-5,
    filing_quarter-4, filing_quarter-3, filing_quarter-2]. ALTERNATE
    base period = quarters [filing_quarter-4, filing_quarter-3,
    filing_quarter-2, filing_quarter-1].'
    """
    filing_q = (now.year, quarter_of(now.date()))
    standard = [
        add_quarters(*filing_q, -5),
        add_quarters(*filing_q, -4),
        add_quarters(*filing_q, -3),
        add_quarters(*filing_q, -2),
    ]
    alternate = [
        add_quarters(*filing_q, -4),
        add_quarters(*filing_q, -3),
        add_quarters(*filing_q, -2),
        add_quarters(*filing_q, -1),
    ]
    return {"STANDARD": standard, "ALTERNATE": alternate, "FILING": filing_q}


def stage_eligible_wages(
    claimant_id: str,
    employer_id: str,
    high_quarter_cents: int = 260_000,
    other_quarter_cents: int = 100_000,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Post 4 wage records into the STANDARD base period such that:
        * STANDARD total >= MIN_BASE_PERIOD_WAGES_CENTS (so STANDARD wins)
        * high_quarter_wages_cents == high_quarter_cents

    Returns {"quarters": [...], "total_cents": int, "high_cents": int}.
    """
    if now is None:
        now = current_clock()
    quarters = base_period_quarters_at(now)["STANDARD"]
    # Stage: [high, other, other, other]
    wage_pattern = [
        high_quarter_cents, other_quarter_cents,
        other_quarter_cents, other_quarter_cents,
    ]
    for (qy, qi), w in zip(quarters, wage_pattern):
        post_wage_record(claimant_id, employer_id, qy, qi, w)
    total = sum(wage_pattern)
    return {
        "quarters": quarters,
        "total_cents": total,
        "high_cents": high_quarter_cents,
    }


def stage_wages_concentrated_in_lag(
    claimant_id: str,
    employer_id: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Stage wages so that STANDARD total < MIN_BASE_PERIOD_WAGES_CENTS
    but ALTERNATE total >= MIN_BASE_PERIOD_WAGES_CENTS, forcing the
    base-period selection rule to pick ALTERNATE.

    Difficulty-design instance: claim_base_period_standard_vs_alternate.

    PRD §3.2 selection rule (pin order):
        1. If STANDARD >= 150_000, pick STANDARD.
        2. Else if ALTERNATE >= 150_000, pick ALTERNATE.
        3. Else pick STANDARD.

    The STANDARD quarters are [-5..-2] from filing_quarter, ALTERNATE
    is [-4..-1]. So the lag quarter (-1) is in ALTERNATE only.
    Layout:
        STANDARD q -5: 0
        STANDARD q -4: 0           (== ALTERNATE q -4)
        STANDARD q -3: 0           (== ALTERNATE q -3)
        STANDARD q -2: 100_000     (== ALTERNATE q -2; below floor)
        ALTERNATE q -1: 400_000    (only counted by ALTERNATE)

    STANDARD total = 100_000 < 150_000.
    ALTERNATE total = 0+0+100_000+400_000 = 500_000 >= 150_000.
    """
    if now is None:
        now = current_clock()
    quarters = base_period_quarters_at(now)
    standard = quarters["STANDARD"]   # 4 quarters
    alternate = quarters["ALTERNATE"]
    # standard quarters wages
    wages_by_quarter: Dict[Tuple[int, int], int] = {}
    wages_by_quarter[standard[0]] = 0
    wages_by_quarter[standard[1]] = 0
    wages_by_quarter[standard[2]] = 0
    wages_by_quarter[standard[3]] = 100_000  # standard q-2 == alt q-2
    wages_by_quarter[alternate[3]] = 400_000  # lag quarter (alt q-1)
    for (qy, qi), w in wages_by_quarter.items():
        post_wage_record(claimant_id, employer_id, qy, qi, w)
    return {
        "standard_quarters": standard,
        "alternate_quarters": alternate,
        "standard_total": 100_000,
        "alternate_total": 500_000,
        "alternate_high_cents": 400_000,
    }


def stage_low_wages_below_floors(
    claimant_id: str,
    employer_id: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Stage wages so BOTH STANDARD and ALTERNATE totals fall below the
    base-period floor — Claim will fail monetary eligibility.

    PRD §3.2 selection rule fallback: 'otherwise STANDARD is chosen by
    default (in which case the claim will fail monetary eligibility).'
    """
    if now is None:
        now = current_clock()
    standard = base_period_quarters_at(now)["STANDARD"]
    # 4 quarters at 10_000 cents each = 40_000 total (below 150_000 floor)
    for (qy, qi) in standard:
        post_wage_record(claimant_id, employer_id, qy, qi, 10_000)
    return {"standard_total": 40_000, "standard_quarters": standard}


def stage_two_employer_equal_wages(
    claimant_id: str,
    employer_a_id: str,
    employer_b_id: str,
    wages_each_cents: int = 1_000_000,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Stage equal base-period wages for two employers in the STANDARD
    base period: one quarter each, same amount. Used for charge
    allocation tie-break tests.

    PRD §3.3: charge allocation weights employers by `wages_E`, the sum
    of that employer's WageRecord.wages_cents inside the chosen base
    period. To make `wages_E` truly EQUAL between A and B, any wages
    added beyond `wages_each_cents` (e.g., to clear monetary floors)
    must be added symmetrically to both employers.

    Difficulty-design instance:
        employer_charge_allocation_mode_b_rounding_order.
    """
    if now is None:
        now = current_clock()
    standard = base_period_quarters_at(now)["STANDARD"]
    # Each employer takes equal wages in standard q[2].
    qy, qi = standard[2]
    post_wage_record(claimant_id, employer_a_id, qy, qi, wages_each_cents)
    post_wage_record(claimant_id, employer_b_id, qy, qi, wages_each_cents)
    # `wages_each_cents=1_000_000` ($10,000) already clears the
    # base-period wages floor (150_000) and high-quarter floor (90_000),
    # so no padding is required. We intentionally do NOT pad with extra
    # wages in other quarters because asymmetric padding would break
    # the equal-wages invariant the tie-break test relies on.
    return {
        "standard_quarters": standard,
        "wages_each": wages_each_cents,
    }


# ===========================================================================
# Composite: Claimant + Claim driven to a given state
# ===========================================================================
def create_eligible_claim(
    high_quarter_cents: int = 260_000,
    other_quarter_cents: int = 100_000,
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    """Create Claimant + Employer + 4 wage records + Claim driven to
    MONETARILY_ELIGIBLE.

    Returns:
        {
            "claimant": Claimant,
            "employer": Employer,
            "claim": Claim,
            "adjudicator_id": str,
        }
    """
    claimant = create_claimant()
    employer = create_employer()
    stage_eligible_wages(
        claimant["id"], employer["id"],
        high_quarter_cents=high_quarter_cents,
        other_quarter_cents=other_quarter_cents,
    )
    claim = create_claim(claimant)
    claim = submit_claim(claim, claimant["id"])
    claim = adjudicate_claim(claim["id"], "ELIGIBLE", adjudicator_id)
    return {
        "claimant": claimant,
        "employer": employer,
        "claim": claim,
        "adjudicator_id": adjudicator_id,
    }


def create_denied_claim(
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    """Create a claim that fails the wage floors and DENY it.

    PRD §3.2: 'A decision of ELIGIBLE is rejected with
    ERR_INSUFFICIENT_BASE_PERIOD_WAGES unless both wage floors are met.'
    """
    claimant = create_claimant()
    employer = create_employer()
    stage_low_wages_below_floors(claimant["id"], employer["id"])
    claim = create_claim(claimant)
    claim = submit_claim(claim, claimant["id"])
    claim = adjudicate_claim(claim["id"], "DENIED", adjudicator_id)
    return {
        "claimant": claimant,
        "employer": employer,
        "claim": claim,
        "adjudicator_id": adjudicator_id,
    }


# ===========================================================================
# WeeklyCertification helpers — PRD §3.3
# ===========================================================================
def benefit_year_start_date(claim: Dict[str, Any]) -> Optional[date]:
    """Return Claim.benefit_year_start as a date, if present."""
    bys = claim.get("benefit_year_start")
    if not bys:
        return None
    return datetime.fromisoformat(bys).date()


def next_certifiable_saturday(
    claim: Dict[str, Any],
    after: Optional[date] = None,
) -> date:
    """Choose a Saturday strictly inside Claim.benefit_year_start (or
    after `after` if supplied) that is suitable for the next weekly
    certification."""
    base = after if after is not None else benefit_year_start_date(claim)
    if base is None:
        base = current_clock().date()
    return next_saturday_strictly_after(base)


def submit_weekly_certification(
    claim_id: str,
    claimant_id: str,
    week_ending_date: date,
    earnings_reported_cents: int = 0,
    able_and_available: bool = True,
    work_search_count: int = 3,
) -> Dict[str, Any]:
    """Submit a weekly certification under ownership-correct headers."""
    headers = make_claimant_headers(claimant_id)
    entries = n_work_search_entries(work_search_count, base_date=week_ending_date)
    payload = create_weekly_certification_payload(
        week_ending_date=date_to_iso(week_ending_date),
        earnings_reported_cents=earnings_reported_cents,
        able_and_available=able_and_available,
        work_search_entries=entries,
    )
    resp = api_client.create_weekly_certification(
        claim_id, payload, headers,
    )
    return get_success_data(resp)


def approve_one_weekly_certification(
    bundle: Dict[str, Any],
    week_ending: Optional[date] = None,
    earnings_reported_cents: int = 0,
) -> Dict[str, Any]:
    """Submit & approve one weekly certification on the given eligible
    claim bundle (from create_eligible_claim)."""
    claim = bundle["claim"]
    claimant = bundle["claimant"]
    if week_ending is None:
        week_ending = next_certifiable_saturday(claim)
    cert = submit_weekly_certification(
        claim_id=claim["id"],
        claimant_id=claimant["id"],
        week_ending_date=week_ending,
        earnings_reported_cents=earnings_reported_cents,
    )
    return cert


def audit_certification(
    cert_id: str,
    classification: str = "NON_FRAUD",
    reason: str = "audit reason",
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    """PRD §3.5: 'An Adjudicator initiates an audit against an APPROVED
    certification.'"""
    resp = api_client.audit_weekly_certification(
        cert_id,
        audit_weekly_certification_payload(classification, reason),
        make_adjudicator_headers(adjudicator_id),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: Threshold/accumulation fixtures
# ===========================================================================
def setup_claim_with_n_approved_certs(
    n_approvals: int,
    max_weeks_target: int,
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    """Create a claim with max_weeks_of_eligibility close to a target
    value, then approve `n_approvals` certifications.

    Used for EXHAUSTED-cycle tests (e.g.,
    claim_exhausted_cycle_via_audit_revert with
    max_weeks_of_eligibility=2 and n_approvals=2).

    PRD §3.2 max-weeks formula:
        max_weeks = clamp(floor(base_period_total / (WBA * 3)), 13, 26)

    PRD §3.2 monetary-eligibility floors (enforced at adjudicate):
        base_period_total_wages_cents >= 150_000 AND
        high_quarter_wages_cents >= 90_000

    So we must satisfy BOTH the floors AND drive the raw max-weeks
    quotient down toward the min clamp of 13. With high_quarter = 90_000
    (the floor exactly), WBA = floor(90_000/26) = 3_461, then clamped
    to MIN_WBA = 4_000. With base_period_total = 150_000 (the floor),
    raw max-weeks = floor(150_000 / (4_000 * 3)) = floor(12.5) = 12,
    which clamps up to 13.

    Callers asking for max_weeks_target < 13 must understand that the
    min clamp pins the result at 13 regardless.
    """
    # PRD §3.2 min clamp == 13, so honor that floor.
    target = max(13, max_weeks_target)
    # Wages tuned so the base-period floors are met (so adjudicate
    # accepts the ELIGIBLE decision) AND the raw max-weeks quotient is
    # below 13 (so the min clamp pins the result at 13).
    # high_quarter = 90_000 (exactly the floor), each other quarter
    # = 20_000 -> total = 90_000 + 3*20_000 = 150_000 (exactly the floor)
    bundle = create_eligible_claim(
        high_quarter_cents=90_000,
        other_quarter_cents=20_000,
        adjudicator_id=adjudicator_id,
    )
    claim = bundle["claim"]
    # Now approve n certifications, walking saturdays forward.
    week = next_certifiable_saturday(claim)
    approved_certs: List[Dict[str, Any]] = []
    for _ in range(n_approvals):
        cert = submit_weekly_certification(
            claim_id=claim["id"],
            claimant_id=bundle["claimant"]["id"],
            week_ending_date=week,
        )
        approved_certs.append(cert)
        week = week + timedelta(days=7)
    bundle["approved_certs"] = approved_certs
    bundle["claim"] = get_claim(claim["id"])
    return bundle


def setup_employer_with_active_charge(
    reserve_basis_cents: int = 1_000_000,
    taxable_payroll_cents: int = 10_000_000,
    charge_amount_cents: int = 300_000,
) -> Dict[str, Any]:
    """Create an Employer + Claimant whose first approved cert produces
    one EmployerCharge of charge_cents == charge_amount_cents against
    the Employer.

    Used for: employer_rate_charge_active_vs_relieved and the depth-4
    audit cascade.

    Approach: single-employer base period (so the entire charge goes to
    that Employer), then submit one approved certification whose
    payable_amount_cents == charge_amount_cents.

    payable_amount_cents = WBA - max(0, earnings - floor(WBA*0.25))
    With earnings = 0, payable_amount == WBA. So pick WBA equal to
    charge_amount_cents, and set high_quarter = WBA*26 to drive that.
    """
    claimant = create_claimant()
    employer = create_employer(
        reserve_ratio_basis_cents=reserve_basis_cents,
        taxable_payroll_cents=taxable_payroll_cents,
    )
    # Pick wage values so WBA == charge_amount_cents.
    # WBA = floor(high_quarter / 26) clamped to [4000, 60000].
    # high_quarter = charge_amount_cents * 26
    wba_target = max(4_000, min(60_000, charge_amount_cents))
    high_q = wba_target * 26
    # total wages must clear floor + give max_weeks >= 1 (clamped to 13).
    other = max(50_000, (wba_target * 3 * 13) // 4 + 1)
    stage_eligible_wages(
        claimant["id"], employer["id"],
        high_quarter_cents=high_q,
        other_quarter_cents=other,
    )
    claim = create_claim(claimant)
    claim = submit_claim(claim, claimant["id"])
    claim = adjudicate_claim(claim["id"], "ELIGIBLE")
    # Approve one weekly cert with earnings=0 so payable_amount == WBA.
    week = next_certifiable_saturday(claim)
    cert = submit_weekly_certification(
        claim_id=claim["id"], claimant_id=claimant["id"],
        week_ending_date=week, earnings_reported_cents=0,
    )
    # Look up the EmployerCharge that was just created.
    charges = list_employer_charges(employer["id"])
    return {
        "claimant": claimant,
        "employer": employer,
        "claim": get_claim(claim["id"]),
        "certification": cert,
        "charges": charges,
        "wba": wba_target,
        "high_quarter_wages_cents": high_q,
    }


def setup_two_employer_charge_split(
    payable_amount_cents: int = 10_001,
) -> Dict[str, Any]:
    """Create two Employers with equal base-period wages so a
    BenefitPayment of `payable_amount_cents` produces an
    allocation requiring residual reconciliation.

    Used for employer_charge_allocation_mode_b_rounding_order.

    To get an odd-cent payment we set earnings such that
    payable = WBA - offset = payable_amount_cents.
    """
    claimant = create_claimant()
    # Two employers, A.id < B.id lexically: we cannot directly control
    # the server-generated UUIDs, so we sort after creation and assign
    # 'A' to the lexically smaller id.
    emp1 = create_employer()
    emp2 = create_employer()
    if emp1["id"] < emp2["id"]:
        emp_a, emp_b = emp1, emp2
    else:
        emp_a, emp_b = emp2, emp1

    # Use the two-employer wage stager (equal wages -> equal shares,
    # tie-break by Employer.id ASC).
    stage_two_employer_equal_wages(
        claimant["id"], emp_a["id"], emp_b["id"],
        wages_each_cents=1_000_000,
    )

    claim = create_claim(claimant)
    claim = submit_claim(claim, claimant["id"])
    claim = adjudicate_claim(claim["id"], "ELIGIBLE")

    # WBA must be high enough that `payable_amount_cents` is reachable.
    # Then choose earnings_reported so payable_amount == target.
    # payable = WBA - max(0, earnings - floor(WBA*0.25))
    wba = claim["weekly_benefit_amount_cents"]
    # We want payable == payable_amount_cents.
    # offset = WBA - payable_amount_cents
    offset = wba - payable_amount_cents
    disregard = (wba * 25) // 100
    if offset > 0:
        earnings = offset + disregard
    else:
        earnings = 0
        # payable could exceed payable_amount_cents — we accept the
        # actual payable.
    week = next_certifiable_saturday(claim)
    cert = submit_weekly_certification(
        claim_id=claim["id"], claimant_id=claimant["id"],
        week_ending_date=week, earnings_reported_cents=max(0, earnings),
    )

    return {
        "claimant": claimant,
        "employer_a": emp_a,
        "employer_b": emp_b,
        "claim": get_claim(claim["id"]),
        "certification": cert,
        "wba": wba,
    }


# ===========================================================================
# Pandemic extension fixtures — PRD §3.4
# ===========================================================================
def create_pandemic_extension(
    program_name: Optional[str] = None,
    effective_start: Optional[str] = None,
    effective_end: Optional[str] = None,
    extra_weeks: int = 13,
) -> Dict[str, Any]:
    """PRD §3.4: 'A SystemAdmin can provision a pandemic emergency
    extension program.'"""
    resp = api_client.create_pandemic_extension(
        create_pandemic_extension_payload(
            program_name=program_name,
            effective_start=effective_start,
            effective_end=effective_end,
            extra_weeks=extra_weeks,
        ),
        TEST_USERS["system_admin_headers"],
    )
    return get_success_data(resp)


def setup_active_pandemic_extension(
    extra_weeks: int = 13,
) -> Dict[str, Any]:
    """Create a PandemicExtension whose window contains the current
    clock value, returning it after at least one /_clock/advance has
    triggered the SCHEDULED -> ACTIVE transition.

    PRD §3.4: 'When SystemClock.now reaches or passes the program's
    effective_start (and is still within the window), the system
    transitions the program SCHEDULED -> ACTIVE.'
    """
    now = current_clock()
    start_date = now.date()
    end_date = start_date + timedelta(days=90)
    program = create_pandemic_extension(
        effective_start=date_to_iso(start_date),
        effective_end=date_to_iso(end_date),
        extra_weeks=extra_weeks,
    )
    # Nudge the clock by 1 second so the SCHEDULED -> ACTIVE transition
    # fires deterministically.
    advance_clock_by_seconds(1)
    # Re-read to confirm ACTIVE state.
    resp = api_client.list_pandemic_extensions(
        TEST_USERS["system_admin_headers"],
    )
    body = resp.json()
    items = list(body.get("data") or [])
    active = next(
        (p for p in items if p.get("id") == program["id"]),
        program,
    )
    return active


def apply_extension_to_claim(
    claim: Dict[str, Any],
    claimant_id: str,
    extension_id: str,
) -> Dict[str, Any]:
    """PRD §3.4: 'A claimant whose claim has reached EXHAUSTED may
    request application of an active extension by posting an
    apply-extension action.'"""
    headers = make_claimant_headers(claimant_id)
    resp = api_client.apply_extension(
        claim["id"],
        apply_extension_payload(extension_id=extension_id),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Appeal fixtures — PRD §3.6
# ===========================================================================
def file_appeal(
    claim_id: str,
    claimant_id: str,
    subject_type: str,
    subject_id: str,
    assigned_appeal_officer_id: str = "appeal-officer-0001",
) -> Dict[str, Any]:
    """PRD §3.6: 'A claimant files an appeal with a claim_id, a
    subject_type ... a subject_id ... and an
    assigned_appeal_officer_id.'"""
    headers = make_claimant_headers(claimant_id)
    resp = api_client.create_appeal(
        create_appeal_payload(
            claim_id=claim_id,
            subject_type=subject_type,
            subject_id=subject_id,
            assigned_appeal_officer_id=assigned_appeal_officer_id,
        ),
        headers,
    )
    return get_success_data(resp)


def start_appeal_hearing(
    appeal_id: str,
    officer_id: str = "appeal-officer-0001",
) -> Dict[str, Any]:
    """PRD §3.6: 'the assigned appeal officer opens it.'"""
    headers = make_appeal_officer_headers(officer_id)
    resp = api_client.start_hearing(appeal_id, headers)
    return get_success_data(resp)


def decide_appeal(
    appeal_id: str,
    decision: str,
    officer_id: str = "appeal-officer-0001",
) -> Dict[str, Any]:
    """PRD §3.6: 'An IN_HEARING appeal is decided by the same officer
    with a decision of either SUSTAINED or REVERSED.'"""
    headers = make_appeal_officer_headers(officer_id)
    resp = api_client.decide_appeal(
        appeal_id, decide_appeal_payload(decision), headers,
    )
    return get_success_data(resp)


def withdraw_appeal(
    appeal_id: str,
    claimant_id: str,
) -> Dict[str, Any]:
    """PRD §3.6: 'A claimant may withdraw a FILED appeal at any time.'"""
    headers = make_claimant_headers(claimant_id)
    resp = api_client.withdraw_appeal(appeal_id, headers)
    return get_success_data(resp)


def setup_filed_appeal_on_denied_claim(
    adjudicator_id: str = "adjudicator-0001",
    officer_id: str = "appeal-officer-0001",
) -> Dict[str, Any]:
    """Create a DENIED claim, then file an appeal on its
    MONETARY_DETERMINATION subject.

    Returns the bundle plus the filed appeal.
    """
    bundle = create_denied_claim(adjudicator_id=adjudicator_id)
    claim = bundle["claim"]
    appeal = file_appeal(
        claim_id=claim["id"],
        claimant_id=bundle["claimant"]["id"],
        subject_type="MONETARY_DETERMINATION",
        subject_id=claim["id"],
        assigned_appeal_officer_id=officer_id,
    )
    bundle["appeal"] = appeal
    bundle["officer_id"] = officer_id
    return bundle


def setup_in_hearing_appeal_on_denied_claim(
    adjudicator_id: str = "adjudicator-0001",
    officer_id: str = "appeal-officer-0001",
) -> Dict[str, Any]:
    """Create a DENIED claim, file an appeal, then start the hearing."""
    bundle = setup_filed_appeal_on_denied_claim(
        adjudicator_id=adjudicator_id, officer_id=officer_id,
    )
    appeal = start_appeal_hearing(
        bundle["appeal"]["id"], officer_id=officer_id,
    )
    bundle["appeal"] = appeal
    return bundle


# ===========================================================================
# Overpayment helpers — PRD §3.5
# ===========================================================================
def get_overpayment(overpayment_id: str) -> Dict[str, Any]:
    resp = api_client.get_overpayment(
        overpayment_id, TEST_USERS["system_admin_headers"],
    )
    return get_success_data(resp)


def list_claim_overpayments(claim_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_claim_overpayments(
        claim_id, TEST_USERS["system_admin_headers"],
    )
    body = resp.json()
    return list(body.get("data") or [])


def setup_outstanding_overpayment(
    classification: str = "NON_FRAUD",
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    """Approve one weekly cert, then audit it to produce an Outstanding
    Overpayment of the given classification."""
    bundle = create_eligible_claim(adjudicator_id=adjudicator_id)
    cert = approve_one_weekly_certification(bundle)
    audited = audit_certification(
        cert["id"],
        classification=classification,
        adjudicator_id=adjudicator_id,
    )
    ops = list_claim_overpayments(bundle["claim"]["id"])
    overpayment = ops[0] if ops else None
    bundle["certification"] = audited
    bundle["overpayment"] = overpayment
    bundle["claim"] = get_claim(bundle["claim"]["id"])
    return bundle


def repay_overpayment(
    overpayment_id: str,
    claimant_id: str,
    amount_cents: int,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    headers = make_claimant_headers(claimant_id)
    resp = api_client.repay_overpayment(
        overpayment_id,
        repay_overpayment_payload(amount_cents, version=version),
        headers,
    )
    return get_success_data(resp)


def waive_overpayment(
    overpayment_id: str,
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    headers = make_adjudicator_headers(adjudicator_id)
    resp = api_client.waive_overpayment(
        overpayment_id, waive_overpayment_payload(), headers,
    )
    return get_success_data(resp)


def write_off_overpayment(
    overpayment_id: str,
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    headers = make_adjudicator_headers(adjudicator_id)
    resp = api_client.write_off_overpayment(
        overpayment_id, headers, write_off_payload(),
    )
    return get_success_data(resp)


# ===========================================================================
# Charge relief helper — PRD §3.7
# ===========================================================================
def relieve_charge(
    employer_id: str,
    charge_id: str,
    *,
    via: str = "agent",
    employer_agent_id: Optional[str] = None,
    adjudicator_id: str = "adjudicator-0001",
) -> Dict[str, Any]:
    """PRD §3.7: 'the agent submits a charge-relief request ... The
    handling role may also be an Adjudicator reviewing the relief
    request directly.'

    Identity threading:
      * via='agent' -> EmployerAgent headers with X-User-ID == employer_id.
      * via='adjudicator' -> opaque Adjudicator headers.
    """
    if via == "agent":
        headers = make_employer_agent_headers(
            employer_agent_id if employer_agent_id is not None
            else employer_id
        )
    elif via == "adjudicator":
        headers = make_adjudicator_headers(adjudicator_id)
    else:
        raise ValueError(f"unknown via: {via!r}")
    resp = api_client.relieve_employer_charge(
        employer_id, charge_id, relieve_charge_payload(), headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Difficulty-design composite fixtures
# ===========================================================================
def setup_dual_variant_alternate_scenario() -> Dict[str, Any]:
    """Setup for difficulty instance
    claim_base_period_standard_vs_alternate: wages such that STANDARD
    fails the floor, ALTERNATE meets it. Returns the bundle pre-submit
    so the test can drive the submit transition itself."""
    claimant = create_claimant()
    employer = create_employer()
    info = stage_wages_concentrated_in_lag(claimant["id"], employer["id"])
    claim = create_claim(claimant)  # DRAFT
    return {
        "claimant": claimant,
        "employer": employer,
        "wage_info": info,
        "claim": claim,
    }


def setup_appeal_segregation_collision(
    shared_user_id: str = "user-collide-0001",
) -> Dict[str, Any]:
    """Setup for difficulty instance state_vs_business_safety_segregation:
    create a DENIED claim adjudicated by user_a, then file an appeal
    assigning the appeal officer to the SAME user_a. Then withdraw the
    appeal so it sits in WITHDRAWN. The collision test will then call
    start-hearing with X-User-Role=AppealOfficer, X-User-ID=user_a.
    """
    bundle = create_denied_claim(adjudicator_id=shared_user_id)
    claim = bundle["claim"]
    appeal = file_appeal(
        claim_id=claim["id"],
        claimant_id=bundle["claimant"]["id"],
        subject_type="MONETARY_DETERMINATION",
        subject_id=claim["id"],
        assigned_appeal_officer_id=shared_user_id,  # collision
    )
    appeal = withdraw_appeal(appeal["id"], bundle["claimant"]["id"])
    bundle["appeal"] = appeal
    bundle["shared_user_id"] = shared_user_id
    return bundle


__all__ = [
    # Clock
    "current_clock", "current_clock_iso",
    "advance_clock_by_seconds", "advance_clock_by_days",
    "advance_clock_by_hours", "reset_clock_tracker_to",
    # Claimant
    "create_claimant", "get_claimant",
    # Employer
    "create_employer", "get_employer", "list_employer_charges",
    # Wage records
    "post_wage_record",
    "base_period_quarters_at",
    "stage_eligible_wages",
    "stage_wages_concentrated_in_lag",
    "stage_low_wages_below_floors",
    "stage_two_employer_equal_wages",
    # Claims
    "create_claim", "submit_claim", "adjudicate_claim", "get_claim",
    "create_eligible_claim", "create_denied_claim",
    # Weekly certifications
    "benefit_year_start_date", "next_certifiable_saturday",
    "submit_weekly_certification",
    "approve_one_weekly_certification",
    "audit_certification",
    "setup_claim_with_n_approved_certs",
    # Employer charges
    "setup_employer_with_active_charge",
    "setup_two_employer_charge_split",
    "relieve_charge",
    # Pandemic extension
    "create_pandemic_extension",
    "setup_active_pandemic_extension",
    "apply_extension_to_claim",
    # Appeals
    "file_appeal", "start_appeal_hearing", "decide_appeal",
    "withdraw_appeal",
    "setup_filed_appeal_on_denied_claim",
    "setup_in_hearing_appeal_on_denied_claim",
    # Overpayments
    "get_overpayment", "list_claim_overpayments",
    "setup_outstanding_overpayment",
    "repay_overpayment", "waive_overpayment", "write_off_overpayment",
    # Difficulty-design composites
    "setup_dual_variant_alternate_scenario",
    "setup_appeal_segregation_collision",
]
