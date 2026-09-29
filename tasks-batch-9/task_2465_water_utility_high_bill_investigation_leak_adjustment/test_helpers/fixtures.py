"""Composite state builders.

The harness restarts the service before every individual test, so every test
begins against an empty database and each builder here creates everything it
needs from scratch. Builders are layered:

* primitives — one write each (clock, rate schedule, period, account, meter,
  reading, bill);
* hierarchy — a rate schedule, a period calendar, an account and its meters;
* lifecycle shortcuts — a settled baseline history plus a disputed bill, an
  investigation, verified evidence, a determination, a drafted / submitted /
  posted credit, a closed meter test, a filed or docketed appeal;
* accumulation targeting — balances above the past-due threshold, exhausted
  evidence rounds, defaulted instalment plans, full hearing dockets;
* terminal states — upheld bills, closed and locked periods, rebilled bills.

Every builder returns plain dictionaries so tests can read identifiers and
versions directly.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .constants import (
    DEFAULT_CLOCK,
    HISTORY_CONSUMPTION_GALLONS,
    HISTORY_READ_DATES,
    INITIAL_REGISTER_VALUE,
    STANDARD_PERIODS,
    TARGET_READ_DATE,
)
from .test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CSR_HEADERS,
    CSR_USER_ID,
    SUPERVISOR_HEADERS,
    TECHNICIAN_HEADERS,
    make_customer_headers,
)

Json = Dict[str, Any]


def _data(response) -> Json:
    """Unwrap a setup response, failing loudly when the setup step failed."""
    return get_success_data(response)


def round_half_up(value: Decimal, places: int = 0) -> int:
    """Round half up to a whole number, the discipline the service uses."""
    quantum = Decimal(1).scaleb(-places)
    return int(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def minimum_down_payment_cents(total_amount_cents: int) -> int:
    """Twenty percent of a financed total, rounded half up (PRD §3.8)."""
    return round_half_up(Decimal(total_amount_cents) * Decimal(2000) / Decimal(10000))


# ===========================================================================
# Tier 1 — primitives
# ===========================================================================
def set_clock(api, current_utc: str = DEFAULT_CLOCK) -> Json:
    """Move the logical clock and return the echoed payload."""
    return _data(api.set_clock(current_utc))


def create_rate_schedule(api, headers: Optional[Json] = None, **overrides: Any) -> Json:
    """Create a rate schedule, defaulting to the standard tariff."""
    return _data(
        api.create_rate_schedule(
            f.rate_schedule_payload(**overrides), headers or ADMIN_HEADERS
        )
    )


def create_billing_period(api, headers: Optional[Json] = None, **overrides: Any) -> Json:
    """Create one billing period."""
    return _data(
        api.create_billing_period(
            f.billing_period_payload(**overrides), headers or ADMIN_HEADERS
        )
    )


def close_period(api, period_id: str, headers: Optional[Json] = None) -> Json:
    """Move a period from OPEN to CLOSED."""
    return _data(api.close_billing_period(period_id, headers or ADMIN_HEADERS))


def lock_period(api, period_id: str, headers: Optional[Json] = None) -> Json:
    """Move a period all the way to LOCKED through CLOSED."""
    head = headers or ADMIN_HEADERS
    _data(api.close_billing_period(period_id, head))
    return _data(api.lock_billing_period(period_id, head))


def create_account(
    api, rate_schedule_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    """Register a service account on a rate schedule."""
    return _data(
        api.create_service_account(
            f.service_account_payload(rate_schedule_id, **overrides),
            headers or CSR_HEADERS,
        )
    )


def create_master_meter(
    api, account_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    """Register a billable POTABLE_MASTER meter."""
    return _data(
        api.create_meter(
            f.master_meter_payload(account_id, **overrides),
            headers or TECHNICIAN_HEADERS,
        )
    )


def create_submeter(
    api,
    account_id: str,
    parent_meter_id: str,
    meter_type: str = "IRRIGATION_SUBMETER",
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    """Register a submeter behind a master meter."""
    return _data(
        api.create_meter(
            f.submeter_payload(account_id, parent_meter_id, meter_type, **overrides),
            headers or TECHNICIAN_HEADERS,
        )
    )


def post_reading(
    api,
    meter_id: str,
    read_date: str,
    reading_value: int,
    read_type: str = "ACTUAL",
    headers: Optional[Json] = None,
) -> Json:
    """Post an ACTUAL or ESTIMATED cumulative read."""
    return _data(
        api.create_meter_reading(
            f.meter_reading_payload(
                meter_id, read_date, reading_value, read_type=read_type
            ),
            headers or TECHNICIAN_HEADERS,
        )
    )


def post_corrected_reading(
    api,
    meter_id: str,
    read_date: str,
    reading_value: int,
    corrects_reading_id: str,
    headers: Optional[Json] = None,
) -> Json:
    """Post a CORRECTED read superseding an earlier row."""
    return _data(
        api.create_meter_reading(
            f.corrected_reading_payload(
                meter_id, read_date, reading_value, corrects_reading_id
            ),
            headers or TECHNICIAN_HEADERS,
        )
    )


def generate_bill(
    api,
    account_id: str,
    period_id: str,
    meter_id: str,
    read_type: str = "ACTUAL",
    headers: Optional[Json] = None,
) -> Json:
    """Generate a DRAFT bill for one meter and one period."""
    return _data(
        api.create_bill(
            f.bill_payload(account_id, period_id, meter_id, read_type=read_type),
            headers or SUPERVISOR_HEADERS,
        )
    )


def issue_bill(api, bill_id: str, headers: Optional[Json] = None) -> Json:
    """Issue a DRAFT bill, posting its charge to the ledger."""
    return _data(api.issue_bill(bill_id, headers or SUPERVISOR_HEADERS))


def generate_and_issue_bill(
    api,
    account_id: str,
    period_id: str,
    meter_id: str,
    read_type: str = "ACTUAL",
    headers: Optional[Json] = None,
) -> Json:
    """Generate a bill and immediately issue it."""
    bill = generate_bill(api, account_id, period_id, meter_id, read_type, headers)
    return issue_bill(api, bill["id"], headers)


def fetch_account(api, account_id: str, headers: Optional[Json] = None) -> Json:
    """Read one service account with its live derived state."""
    return _data(api.get_service_account(account_id, headers or CSR_HEADERS))


def fetch_bill(api, bill_id: str, headers: Optional[Json] = None) -> Json:
    """Read one bill with every computed charge field."""
    return _data(api.get_bill(bill_id, headers or SUPERVISOR_HEADERS))


def fetch_investigation(api, investigation_id: str, headers: Optional[Json] = None) -> Json:
    """Read one investigation with its counters."""
    return _data(api.get_investigation(investigation_id, headers or CSR_HEADERS))


def fetch_meter(api, meter_id: str, headers: Optional[Json] = None) -> Json:
    """Read one meter with its accuracy fields."""
    return _data(api.get_meter(meter_id, headers or TECHNICIAN_HEADERS))


def fetch_adjustment(api, adjustment_id: str, headers: Optional[Json] = None) -> Json:
    """Read one leak adjustment with every computed credit field."""
    return _data(api.get_leak_adjustment(adjustment_id, headers or CSR_HEADERS))


def fetch_arrangement(api, arrangement_id: str, headers: Optional[Json] = None) -> Json:
    """Read one payment arrangement with its schedule."""
    return _data(api.get_payment_arrangement(arrangement_id, headers or CSR_HEADERS))


def fetch_appeal(api, appeal_id: str, headers: Optional[Json] = None) -> Json:
    """Read one board appeal."""
    return _data(api.get_board_appeal(appeal_id, headers or CLERK_HEADERS))


def account_version(api, account_id: str, headers: Optional[Json] = None) -> int:
    """Read an account's current optimistic-concurrency version."""
    return fetch_account(api, account_id, headers)["version"]


def investigation_version(
    api, investigation_id: str, headers: Optional[Json] = None
) -> int:
    """Read an investigation's current optimistic-concurrency version."""
    return fetch_investigation(api, investigation_id, headers)["version"]


def live_readings(api, meter_id: str, headers: Optional[Json] = None) -> List[Json]:
    """List the live reads of one meter, oldest first."""
    rows, _meta = validate_paginated(
        api.list_meter_readings(
            headers or TECHNICIAN_HEADERS,
            {"meter_id": meter_id, "live_only": True, "limit": 100},
        )
    )
    return rows


# ===========================================================================
# Tier 2 — entity hierarchy
# ===========================================================================
def period_calendar(
    api, season: str = "SUMMER", headers: Optional[Json] = None
) -> Json:
    """Create the four-period calendar every billing chain is built on.

    Three consecutive same-season history periods supply the baseline sample
    and a fourth same-season period carries the disputed bill.
    """
    periods = []
    for spec in STANDARD_PERIODS:
        periods.append(
            create_billing_period(api, headers=headers, **{**spec, "season": season})
        )
    return {
        "periods": periods,
        "ids": [p["id"] for p in periods],
        "history_ids": [p["id"] for p in periods[:3]],
        "target_id": periods[3]["id"],
        "target": periods[3],
    }


def metered_account(
    api,
    season: str = "SUMMER",
    size_inches: float = 1.0,
    rate_schedule_overrides: Optional[Json] = None,
    account_overrides: Optional[Json] = None,
) -> Json:
    """A rate schedule, a period calendar, an account and its master meter."""
    set_clock(api)
    schedule = create_rate_schedule(api, **(rate_schedule_overrides or {}))
    calendar = period_calendar(api, season=season)
    account = create_account(
        api, schedule["id"], **(account_overrides or {})
    )
    meter = create_master_meter(
        api,
        account["id"],
        size_inches=size_inches,
        initial_register_value=INITIAL_REGISTER_VALUE,
    )
    return {
        "rate_schedule": schedule,
        "rate_schedule_id": schedule["id"],
        "calendar": calendar,
        "account": account,
        "account_id": account["id"],
        "account_version": account["version"],
        "meter": meter,
        "meter_id": meter["id"],
        "customer_headers": make_customer_headers(account["id"]),
    }


def metered_account_with_submeter(
    api,
    season: str = "SUMMER",
    submeter_type: str = "IRRIGATION_SUBMETER",
    **kwargs: Any,
) -> Json:
    """A metered account that also carries one submeter behind the master."""
    base = metered_account(api, season=season, **kwargs)
    submeter = create_submeter(
        api, base["account_id"], base["meter_id"], submeter_type
    )
    base["submeter"] = submeter
    base["submeter_id"] = submeter["id"]
    return base


# ===========================================================================
# Tier 3 — lifecycle shortcuts
# ===========================================================================
def baselined_bill(
    api,
    target_gallons: int = 41000,
    season: str = "SUMMER",
    history_gallons: int = HISTORY_CONSUMPTION_GALLONS,
    target_read_type: str = "ACTUAL",
    issue_target: bool = True,
    size_inches: float = 1.0,
    rate_schedule_overrides: Optional[Json] = None,
    base: Optional[Json] = None,
) -> Json:
    """Three settled history bills plus one disputed bill on the same meter.

    The three history bills are ISSUED, non-estimated and non-anomalous, so the
    fourth bill's ``seasonal_baseline_gallons`` is the mean of their
    consumption and its ``anomaly_ratio`` follows from ``target_gallons``.
    """
    ctx = base or metered_account(
        api,
        season=season,
        size_inches=size_inches,
        rate_schedule_overrides=rate_schedule_overrides,
    )
    register = INITIAL_REGISTER_VALUE
    post_reading(api, ctx["meter_id"], HISTORY_READ_DATES[0], register)
    history_bills = []
    for index, period_id in enumerate(ctx["calendar"]["history_ids"]):
        register += history_gallons
        post_reading(api, ctx["meter_id"], HISTORY_READ_DATES[index + 1], register)
        history_bills.append(
            generate_and_issue_bill(api, ctx["account_id"], period_id, ctx["meter_id"])
        )

    target_read = post_reading(
        api,
        ctx["meter_id"],
        TARGET_READ_DATE,
        register + target_gallons,
        read_type=target_read_type,
    )
    bill = generate_bill(
        api,
        ctx["account_id"],
        ctx["calendar"]["target_id"],
        ctx["meter_id"],
        read_type=target_read_type,
    )
    if issue_target:
        bill = issue_bill(api, bill["id"])

    account = fetch_account(api, ctx["account_id"])
    ctx.update(
        {
            "history_bills": history_bills,
            "history_bill_ids": [b["id"] for b in history_bills],
            "bill": bill,
            "bill_id": bill["id"],
            "target_gallons": target_gallons,
            "target_read": target_read,
            "target_read_id": target_read["id"],
            "account": account,
            "account_version": account["version"],
        }
    )
    return ctx


def open_investigation(
    api,
    bill_id: str,
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    """Open a high-bill investigation on an issued bill."""
    return _data(
        api.create_investigation(
            f.investigation_payload(bill_id, **overrides), headers or CSR_HEADERS
        )
    )


def request_evidence(
    api, investigation_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    """Consume one bounded evidence round."""
    return _data(
        api.request_evidence(
            investigation_id,
            headers or CSR_HEADERS,
            f.evidence_request_payload(**overrides),
        )
    )


def investigation_case(
    api,
    target_gallons: int = 41000,
    rep_headers: Optional[Json] = None,
    request_first_round: bool = True,
    **kwargs: Any,
) -> Json:
    """A disputed bill carrying an open investigation.

    With ``request_first_round`` the investigation is already sitting in
    ``EVIDENCE_REQUESTED`` with one round consumed.
    """
    ctx = baselined_bill(api, target_gallons=target_gallons, **kwargs)
    head = rep_headers or CSR_HEADERS
    investigation = open_investigation(api, ctx["bill_id"], head)
    if request_first_round:
        investigation = request_evidence(api, investigation["id"], head)
    ctx.update(
        {
            "investigation": investigation,
            "investigation_id": investigation["id"],
            "investigation_version": investigation["version"],
            "rep_user_id": head["X-User-ID"],
            "rep_headers": head,
        }
    )
    return ctx


def submit_repair_proof(
    api,
    investigation_id: str,
    leak_type: str = "SERVICE_LINE",
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    """Submit plumber repair proof against an investigation."""
    return _data(
        api.create_repair_proof(
            f.repair_proof_payload(investigation_id, leak_type, **overrides),
            headers or CSR_HEADERS,
        )
    )


def verify_repair_proof(api, proof_id: str, headers: Optional[Json] = None) -> Json:
    """Verify a submitted repair proof."""
    return _data(api.verify_repair_proof(proof_id, headers or CSR_HEADERS))


def reject_repair_proof(
    api, proof_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    """Reject a submitted repair proof."""
    return _data(
        api.reject_repair_proof(
            proof_id, f.proof_rejection_payload(**overrides), headers or CSR_HEADERS
        )
    )


def proof_case(
    api,
    leak_type: str = "SERVICE_LINE",
    target_gallons: int = 41000,
    verify: bool = True,
    **kwargs: Any,
) -> Json:
    """An investigation in EVIDENCE_UNDER_REVIEW with (optionally) verified proof."""
    ctx = investigation_case(api, target_gallons=target_gallons, **kwargs)
    proof = submit_repair_proof(
        api, ctx["investigation_id"], leak_type, ctx["rep_headers"]
    )
    if verify:
        proof = verify_repair_proof(api, proof["id"], ctx["rep_headers"])
    ctx.update(
        {
            "proof": proof,
            "proof_id": proof["id"],
            "proof_leak_type": leak_type,
            "investigation_version": investigation_version(
                api, ctx["investigation_id"]
            ),
        }
    )
    return ctx


def determine(
    api,
    investigation_id: str,
    leak_determination: str = "CUSTOMER_SIDE_LEAK",
    headers: Optional[Json] = None,
) -> Json:
    """Record the leak determination."""
    return _data(
        api.determine_investigation(
            investigation_id,
            f.determination_payload(leak_determination),
            headers or CSR_HEADERS,
        )
    )


def determined_case(
    api,
    leak_type: str = "SERVICE_LINE",
    leak_determination: str = "CUSTOMER_SIDE_LEAK",
    target_gallons: int = 41000,
    **kwargs: Any,
) -> Json:
    """An investigation sitting in DETERMINED behind verified evidence."""
    ctx = proof_case(api, leak_type=leak_type, target_gallons=target_gallons, **kwargs)
    investigation = determine(
        api, ctx["investigation_id"], leak_determination, ctx["rep_headers"]
    )
    ctx.update(
        {
            "investigation": investigation,
            "investigation_version": investigation["version"],
            "determination": leak_determination,
            "determination_by_user_id": ctx["rep_headers"]["X-User-ID"],
        }
    )
    return ctx


def draft_adjustment(
    api,
    investigation_id: str,
    bill_id: str,
    leak_type: str,
    expected_investigation_version: int,
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    """Draft a leak adjustment under the optimistic-concurrency guard."""
    return _data(
        api.create_leak_adjustment(
            f.leak_adjustment_payload(
                investigation_id,
                bill_id,
                leak_type,
                expected_investigation_version,
                **overrides,
            ),
            headers or CSR_HEADERS,
        )
    )


def submit_adjustment(api, adjustment_id: str, headers: Optional[Json] = None) -> Json:
    """Submit a draft adjustment for supervisory approval."""
    return _data(api.submit_leak_adjustment(adjustment_id, headers or CSR_HEADERS))


def approve_adjustment(api, adjustment_id: str, headers: Optional[Json] = None) -> Json:
    """Approve and post an adjustment as a supervisor."""
    return _data(api.approve_leak_adjustment(adjustment_id, headers or SUPERVISOR_HEADERS))


def deny_adjustment(
    api, adjustment_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    """Deny a pending adjustment."""
    return _data(
        api.deny_leak_adjustment(
            adjustment_id, f.denial_payload(**overrides), headers or SUPERVISOR_HEADERS
        )
    )


def return_adjustment(
    api, adjustment_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    """Return a pending adjustment to its drafter."""
    return _data(
        api.return_leak_adjustment(
            adjustment_id, f.return_payload(**overrides), headers or SUPERVISOR_HEADERS
        )
    )


def reverse_adjustment(
    api, adjustment_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    """Reverse a posted adjustment with one compensating entry."""
    return _data(
        api.reverse_leak_adjustment(
            adjustment_id, f.reversal_payload(**overrides), headers or SUPERVISOR_HEADERS
        )
    )


def drafted_adjustment_case(
    api,
    leak_type: str = "SERVICE_LINE",
    leak_determination: str = "CUSTOMER_SIDE_LEAK",
    target_gallons: int = 41000,
    **kwargs: Any,
) -> Json:
    """A determined investigation with a DRAFT leak adjustment on it."""
    ctx = determined_case(
        api,
        leak_type=leak_type,
        leak_determination=leak_determination,
        target_gallons=target_gallons,
        **kwargs,
    )
    adjustment = draft_adjustment(
        api,
        ctx["investigation_id"],
        ctx["bill_id"],
        leak_type,
        ctx["investigation_version"],
        ctx["rep_headers"],
    )
    ctx.update(
        {
            "adjustment": adjustment,
            "adjustment_id": adjustment["id"],
            "adjustment_status": adjustment["status"],
            "investigation_version": investigation_version(api, ctx["investigation_id"]),
        }
    )
    return ctx


def pending_adjustment_case(api, **kwargs: Any) -> Json:
    """A leak adjustment sitting in PENDING_APPROVAL."""
    ctx = drafted_adjustment_case(api, **kwargs)
    adjustment = submit_adjustment(api, ctx["adjustment_id"], ctx["rep_headers"])
    ctx["adjustment"] = adjustment
    ctx["adjustment_status"] = adjustment["status"]
    return ctx


def posted_adjustment_case(
    api, approver_headers: Optional[Json] = None, **kwargs: Any
) -> Json:
    """A leak adjustment approved and posted by a supervisor.

    The approver differs from the determining representative, so segregation of
    duties is satisfied.
    """
    ctx = pending_adjustment_case(api, **kwargs)
    head = approver_headers or SUPERVISOR_HEADERS
    adjustment = approve_adjustment(api, ctx["adjustment_id"], head)
    ctx.update(
        {
            "adjustment": adjustment,
            "adjustment_status": adjustment["status"],
            "approver_headers": head,
            "approver_user_id": head["X-User-ID"],
            "account": fetch_account(api, ctx["account_id"]),
        }
    )
    ctx["account_version"] = ctx["account"]["version"]
    return ctx


def upheld_bill_case(api, **kwargs: Any) -> Json:
    """An investigation closed without any credit, settling the bill."""
    ctx = investigation_case(api, **kwargs)
    investigation = _data(
        api.close_investigation_no_adjustment(
            ctx["investigation_id"],
            ctx["rep_headers"],
            f.close_no_adjustment_payload(),
        )
    )
    ctx["investigation"] = investigation
    ctx["investigation_version"] = investigation["version"]
    return ctx


# ===========================================================================
# Tier 3b — meter accuracy testing
# ===========================================================================
def request_meter_test(
    api,
    investigation_id: str,
    meter_id: str,
    requested_test_type: str = "FIELD",
    requested_by_kind: str = "CUSTOMER",
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    """Request an accuracy test, taking the declared deposit."""
    return _data(
        api.create_meter_test_request(
            f.meter_test_request_payload(
                investigation_id,
                meter_id,
                requested_test_type,
                requested_by_kind,
                **overrides,
            ),
            headers or CSR_HEADERS,
        )
    )


def schedule_field_test(
    api,
    request_id: str,
    window_start: str = "2026-08-01T09:00:00Z",
    window_end: str = "2026-08-01T17:00:00Z",
    headers: Optional[Json] = None,
) -> Json:
    """Reserve a half-open field-test window on the meter."""
    return _data(
        api.schedule_field_test(
            request_id,
            f.field_test_window_payload(window_start, window_end),
            headers or TECHNICIAN_HEADERS,
        )
    )


def record_field_result(
    api,
    request_id: str,
    field_result: str = "PASS",
    tested_at: str = "2026-08-01T10:00:00Z",
    headers: Optional[Json] = None,
) -> Json:
    """Record a field-test outcome inside the reserved window."""
    return _data(
        api.record_field_result(
            request_id,
            f.field_result_payload(field_result, tested_at),
            headers or TECHNICIAN_HEADERS,
        )
    )


def record_bench_result(
    api,
    request_id: str,
    low_flow_pct: float,
    mid_flow_pct: float,
    high_flow_pct: float,
    tested_at: str = "2026-08-01T10:00:00Z",
    headers: Optional[Json] = None,
) -> Json:
    """Record the three bench flow points."""
    return _data(
        api.record_bench_result(
            request_id,
            f.bench_result_payload(
                low_flow_pct, mid_flow_pct, high_flow_pct, tested_at
            ),
            headers or TECHNICIAN_HEADERS,
        )
    )


def field_test_case(
    api,
    requested_by_kind: str = "CUSTOMER",
    scheduled: bool = True,
    target_gallons: int = 41000,
    **kwargs: Any,
) -> Json:
    """An investigation carrying a FIELD meter test request."""
    ctx = investigation_case(api, target_gallons=target_gallons, **kwargs)
    request = request_meter_test(
        api,
        ctx["investigation_id"],
        ctx["meter_id"],
        "FIELD",
        requested_by_kind,
        ctx["rep_headers"],
    )
    if scheduled:
        request = schedule_field_test(api, request["id"])
    ctx.update(
        {
            "test_request": request,
            "test_request_id": request["id"],
            "requested_by_kind": requested_by_kind,
        }
    )
    return ctx


def bench_pending_case(
    api,
    size_inches: float = 1.0,
    requested_by_kind: str = "CUSTOMER",
    target_gallons: int = 41000,
    **kwargs: Any,
) -> Json:
    """An investigation carrying a test request in BENCH_TEST_PENDING."""
    ctx = investigation_case(
        api, target_gallons=target_gallons, size_inches=size_inches, **kwargs
    )
    request = request_meter_test(
        api,
        ctx["investigation_id"],
        ctx["meter_id"],
        "BENCH",
        requested_by_kind,
        ctx["rep_headers"],
    )
    ctx.update(
        {
            "test_request": request,
            "test_request_id": request["id"],
            "requested_by_kind": requested_by_kind,
        }
    )
    return ctx


def bench_closed_case(
    api,
    low_flow_pct: float,
    mid_flow_pct: float,
    high_flow_pct: float,
    size_inches: float = 1.0,
    **kwargs: Any,
) -> Json:
    """A bench test recorded and closed on the given three flow points."""
    ctx = bench_pending_case(api, size_inches=size_inches, **kwargs)
    request = record_bench_result(
        api, ctx["test_request_id"], low_flow_pct, mid_flow_pct, high_flow_pct
    )
    ctx["test_request"] = request
    ctx["meter"] = fetch_meter(api, ctx["meter_id"])
    ctx["bill"] = fetch_bill(api, ctx["bill_id"])
    ctx["account"] = fetch_account(api, ctx["account_id"])
    ctx["account_version"] = ctx["account"]["version"]
    return ctx


# ===========================================================================
# Tier 4 — accumulation and threshold targeting
# ===========================================================================
def evidence_exhausted_case(api, **kwargs: Any) -> Json:
    """An investigation whose three evidence rounds are spent.

    Round one is opened when the investigation is created, and two
    rejection-driven re-requests carry the counter to the ceiling; the third
    rejection closes the loop at ``EVIDENCE_EXHAUSTED``.
    """
    ctx = investigation_case(api, **kwargs)
    head = ctx["rep_headers"]
    proof_ids = []
    for _ in range(3):
        proof = submit_repair_proof(api, ctx["investigation_id"], "SERVICE_LINE", head)
        proof_ids.append(proof["id"])
        reject_repair_proof(api, proof["id"], head)
    ctx["rejected_proof_ids"] = proof_ids
    ctx["investigation"] = fetch_investigation(api, ctx["investigation_id"])
    ctx["investigation_version"] = ctx["investigation"]["version"]
    return ctx


def past_due_account(api, **kwargs: Any) -> Json:
    """An account whose issued bills leave it above the past-due threshold."""
    ctx = baselined_bill(api, **kwargs)
    ctx["account"] = fetch_account(api, ctx["account_id"])
    ctx["account_version"] = ctx["account"]["version"]
    return ctx


def shutoff_scheduled_account(api, **kwargs: Any) -> Json:
    """A past-due account moved to SHUTOFF_SCHEDULED by a supervisor."""
    ctx = past_due_account(api, **kwargs)
    account = _data(api.schedule_shutoff(ctx["account_id"], SUPERVISOR_HEADERS))
    ctx["account"] = account
    ctx["account_version"] = account["version"]
    return ctx


def shutoff_held_account(api, **kwargs: Any) -> Json:
    """A scheduled shutoff stopped by an investigation hold."""
    ctx = shutoff_scheduled_account(api, **kwargs)
    investigation = open_investigation(api, ctx["bill_id"], CSR_HEADERS)
    ctx.update(
        {
            "investigation": investigation,
            "investigation_id": investigation["id"],
            "investigation_version": investigation["version"],
            "rep_headers": CSR_HEADERS,
            "rep_user_id": CSR_USER_ID,
        }
    )
    ctx["account"] = fetch_account(api, ctx["account_id"])
    ctx["account_version"] = ctx["account"]["version"]
    return ctx


def record_account_payment(
    api, account_id: str, amount_cents: int, headers: Optional[Json] = None
) -> Json:
    """Record an ad-hoc account payment."""
    return _data(
        api.record_account_payment(
            account_id,
            f.account_payment_payload(amount_cents),
            headers or make_customer_headers(account_id),
        )
    )


def propose_arrangement(
    api,
    account_id: str,
    bill_id: str,
    total_amount_cents: int,
    expected_account_version: int,
    installment_count: int = 4,
    down_payment_cents: Optional[int] = None,
    investigation_id: Optional[str] = None,
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    """Propose an instalment plan under the account version guard."""
    down = (
        down_payment_cents
        if down_payment_cents is not None
        else minimum_down_payment_cents(total_amount_cents)
    )
    return _data(
        api.create_payment_arrangement(
            f.payment_arrangement_payload(
                account_id,
                bill_id,
                total_amount_cents,
                down,
                installment_count,
                expected_account_version,
                investigation_id,
                **overrides,
            ),
            headers or CSR_HEADERS,
        )
    )


def arrangement_case(
    api,
    installment_count: int = 4,
    activate: bool = False,
    **kwargs: Any,
) -> Json:
    """A PROPOSED (optionally ACTIVE) instalment plan financing a disputed bill."""
    ctx = baselined_bill(api, **kwargs)
    bill = fetch_bill(api, ctx["bill_id"])
    total = bill["adjusted_total_cents"]
    arrangement = propose_arrangement(
        api,
        ctx["account_id"],
        ctx["bill_id"],
        total,
        account_version(api, ctx["account_id"]),
        installment_count=installment_count,
    )
    if activate:
        arrangement = _data(
            api.activate_payment_arrangement(arrangement["id"], CSR_HEADERS)
        )
    ctx.update(
        {
            "arrangement": arrangement,
            "arrangement_id": arrangement["id"],
            "financed_total_cents": total,
            "down_payment_cents": arrangement["down_payment_cents"],
        }
    )
    ctx["account"] = fetch_account(api, ctx["account_id"])
    ctx["account_version"] = ctx["account"]["version"]
    return ctx


def record_installment(
    api,
    arrangement_id: str,
    amount_cents: int,
    on_time: bool = True,
    headers: Optional[Json] = None,
) -> Json:
    """Record one instalment against an active plan."""
    return _data(
        api.record_installment_payment(
            arrangement_id,
            f.installment_payment_payload(amount_cents, on_time),
            headers or CSR_HEADERS,
        )
    )


def defaulted_arrangement_case(api, **kwargs: Any) -> Json:
    """An active plan driven to DEFAULTED by two late instalments."""
    ctx = arrangement_case(api, activate=True, **kwargs)
    amount = ctx["arrangement"]["installment_cents"]
    for _ in range(2):
        record_installment(api, ctx["arrangement_id"], amount, on_time=False)
    ctx["arrangement"] = fetch_arrangement(api, ctx["arrangement_id"])
    ctx["account"] = fetch_account(api, ctx["account_id"])
    ctx["account_version"] = ctx["account"]["version"]
    return ctx


# ===========================================================================
# Tier 5 — appeals and terminal states
# ===========================================================================
def file_appeal(
    api, investigation_id: str, headers: Optional[Json] = None, **overrides: Any
) -> Json:
    """File an appeal to the utility board."""
    return _data(
        api.create_board_appeal(
            f.board_appeal_payload(investigation_id, **overrides),
            headers or CSR_HEADERS,
        )
    )


def schedule_hearing(
    api, appeal_id: str, hearing_date: str, headers: Optional[Json] = None
) -> Json:
    """Docket a hearing on a filed appeal."""
    return _data(
        api.schedule_hearing(
            appeal_id, f.hearing_schedule_payload(hearing_date), headers or CLERK_HEADERS
        )
    )


def record_board_decision(
    api,
    appeal_id: str,
    decision: str = "UPHOLD",
    headers: Optional[Json] = None,
    **overrides: Any,
) -> Json:
    """Record the board's decision on a docketed appeal."""
    return _data(
        api.record_board_decision(
            appeal_id,
            f.board_decision_payload(decision, **overrides),
            headers or CLERK_HEADERS,
        )
    )


def appeal_case(
    api,
    filer_headers: Optional[Json] = None,
    hearing_date: Optional[str] = None,
    advance_to_hearing: bool = False,
    **kwargs: Any,
) -> Json:
    """A determined investigation carrying a filed — or docketed — appeal.

    With ``hearing_date`` the appeal is docketed; with ``advance_to_hearing``
    the logical clock is moved onto the hearing date so a decision may be
    recorded.
    """
    ctx = determined_case(api, **kwargs)
    head = filer_headers or ctx["customer_headers"]
    appeal = file_appeal(api, ctx["investigation_id"], head)
    ctx.update(
        {
            "appeal": appeal,
            "appeal_id": appeal["id"],
            "filed_by_user_id": head["X-User-ID"],
            "filer_headers": head,
            "hearing_date": None,
        }
    )
    if hearing_date:
        appeal = schedule_hearing(api, appeal["id"], hearing_date)
        ctx["appeal"] = appeal
        ctx["hearing_date"] = hearing_date
        if advance_to_hearing:
            set_clock(api, f"{hearing_date}T09:00:00Z")
    ctx["investigation"] = fetch_investigation(api, ctx["investigation_id"])
    ctx["investigation_version"] = ctx["investigation"]["version"]
    return ctx


def rebill_pending_case(
    api,
    corrected_gallons: int = 8000,
    target_gallons: int = 41000,
    **kwargs: Any,
) -> Json:
    """A charged bill pushed into REBILL_PENDING by a CORRECTED read."""
    ctx = baselined_bill(api, target_gallons=target_gallons, **kwargs)
    prior_register = INITIAL_REGISTER_VALUE + 3 * HISTORY_CONSUMPTION_GALLONS
    post_corrected_reading(
        api,
        ctx["meter_id"],
        TARGET_READ_DATE,
        prior_register + corrected_gallons,
        ctx["target_read_id"],
    )
    ctx["bill"] = fetch_bill(api, ctx["bill_id"])
    ctx["corrected_gallons"] = corrected_gallons
    ctx["account"] = fetch_account(api, ctx["account_id"])
    ctx["account_version"] = ctx["account"]["version"]
    return ctx


def rebilled_case(api, **kwargs: Any) -> Json:
    """A rebilled bill together with its already-issued replacement."""
    ctx = rebill_pending_case(api, **kwargs)
    replacement = _data(api.rebill_bill(ctx["bill_id"], SUPERVISOR_HEADERS))
    ctx.update(
        {
            "replacement_bill": replacement,
            "replacement_bill_id": replacement["id"],
            "superseded_bill": fetch_bill(api, ctx["bill_id"]),
        }
    )
    ctx["account"] = fetch_account(api, ctx["account_id"])
    ctx["account_version"] = ctx["account"]["version"]
    return ctx
