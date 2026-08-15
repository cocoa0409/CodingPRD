"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server with an empty database).
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

All dates below are pinned against the test-driving logical clock
(PRD §2.5); helpers that need a specific "today" set the clock explicitly.
"""
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_audit_report_payload,
    create_carrier_payload,
    create_complaint_payload,
    create_credit_memo_payload,
    create_payment_payload,
    create_rack_location_payload,
    create_rack_sales_report_payload,
    create_route_assignment_payload,
    create_route_payload,
    create_subscriber_payload,
    create_subscription_payload,
    create_subscription_plan_payload,
    create_vacation_hold_payload,
)
from .test_users import TEST_USERS

DIRECTOR = TEST_USERS["circulation_director_headers"]
REP = TEST_USERS["service_rep_headers"]
MGR = TEST_USERS["district_manager_headers"]


# ---------------------------------------------------------------------------
# Clock / batch cycle
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.5). Does not run the batch."""
    return get_success_data(api_client.set_clock(to_iso8601, DIRECTOR))


def run_daily_cycle() -> dict:
    """Run the nightly batch at the current logical date (PRD §2.5)."""
    return get_success_data(api_client.run_daily_cycle(DIRECTOR))


def set_clock_and_cycle(to_iso8601: str) -> dict:
    set_clock(to_iso8601)
    return run_daily_cycle()


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------

def create_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_subscription_plan(create_subscription_plan_payload(**overrides), DIRECTOR)
    )


def create_subscriber(**overrides) -> dict:
    return get_success_data(
        api_client.create_subscriber(create_subscriber_payload(**overrides), REP)
    )


def create_carrier(**overrides) -> dict:
    return get_success_data(
        api_client.create_carrier(create_carrier_payload(**overrides), MGR)
    )


def create_route(**overrides) -> dict:
    return get_success_data(
        api_client.create_route(create_route_payload(**overrides), MGR)
    )


def create_rack_location(**overrides) -> dict:
    return get_success_data(
        api_client.create_rack_location(create_rack_location_payload(**overrides), MGR)
    )


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------

def create_subscription(subscriber_id: str, plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_subscription(
            create_subscription_payload(subscriber_id, plan_id, **overrides), REP
        )
    )


def get_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, REP))


def get_subscriber(subscriber_id: str) -> dict:
    return get_success_data(api_client.get_subscriber(subscriber_id, REP))


def list_charges_for_subscription(subscription_id: str) -> List[dict]:
    """All billing charges for a subscription (single page, generous limit)."""
    data, _meta = validate_paginated(
        api_client.list_billing_charges(REP, params={"subscription_id": subscription_id, "limit": 100})
    )
    return data


def create_active_subscription(
    start_date: str = "2026-08-03",
    clock: str = "2026-08-03T00:00:00Z",
    plan_overrides: Optional[dict] = None,
    subscriber_overrides: Optional[dict] = None,
) -> dict:
    """Plan + subscriber + subscription, activated by a daily cycle whose
    logical date equals start_date. Returns
    {"plan", "subscriber", "subscription"} with the post-cycle subscription."""
    set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    sub_overrides = dict(subscriber_overrides or {})
    if (plan.get("plan_type") in ("PRINT", "BUNDLE")) and "service_address" not in sub_overrides:
        sub_overrides["service_address"] = "1 Main St"
    subscriber = create_subscriber(**sub_overrides)
    subscription = create_subscription(subscriber["id"], plan["id"], start_date=start_date)
    run_daily_cycle()
    return {
        "plan": plan,
        "subscriber": subscriber,
        "subscription": get_subscription(subscription["id"]),
    }


def pay_and_clear(subscriber_id: str, amount_cents: int, method: str = "CARD") -> dict:
    """Record a payment and immediately clear it (waterfall runs at clearing)."""
    payment = get_success_data(
        api_client.create_payment(
            create_payment_payload(subscriber_id, amount_cents=amount_cents, method=method), REP
        )
    )
    return get_success_data(api_client.mark_payment_cleared(payment["id"], REP))


# ---------------------------------------------------------------------------
# Vacation holds
# ---------------------------------------------------------------------------

def create_hold(subscription_id: str, start_date: str, end_date: str,
                resolution: str = "CREDIT") -> dict:
    return get_success_data(
        api_client.create_vacation_hold(
            subscription_id,
            create_vacation_hold_payload(
                start_date=start_date, end_date=end_date, resolution=resolution
            ),
            REP,
        )
    )


def get_hold(hold_id: str) -> dict:
    return get_success_data(api_client.get_vacation_hold(hold_id, REP))


def setup_completed_hold(
    start_date: str = "2026-08-03",
    hold_window: tuple = ("2026-08-10", "2026-08-14"),
    resolution: str = "CREDIT",
    plan_overrides: Optional[dict] = None,
) -> dict:
    """Active print subscription with a hold driven to COMPLETED by the batch.
    Returns {"plan", "subscriber", "subscription", "hold", "credit_memos"}."""
    ctx = create_active_subscription(
        start_date=start_date,
        clock=f"{start_date}T00:00:00Z",
        plan_overrides=plan_overrides,
    )
    hold = create_hold(
        ctx["subscription"]["id"], hold_window[0], hold_window[1], resolution=resolution
    )
    set_clock_and_cycle(f"{hold_window[0]}T00:00:00Z")  # activate hold
    set_clock_and_cycle(f"{hold_window[1]}T00:00:00Z")  # complete hold
    memos, _meta = validate_paginated(
        api_client.list_credit_memos(REP, params={"hold_id": hold["id"], "limit": 100})
    )
    return {
        "plan": ctx["plan"],
        "subscriber": ctx["subscriber"],
        "subscription": get_subscription(ctx["subscription"]["id"]),
        "hold": get_hold(hold["id"]),
        "credit_memos": memos,
    }


# ---------------------------------------------------------------------------
# Complaints / credit memos
# ---------------------------------------------------------------------------

def create_complaint(subscription_id: str, service_date: str,
                     complaint_type: str = "MISSED") -> dict:
    return get_success_data(
        api_client.create_complaint(
            create_complaint_payload(
                subscription_id, service_date=service_date, complaint_type=complaint_type
            ),
            REP,
        )
    )


def create_goodwill_memo(subscriber_id: str, amount_cents: int, reason: str = "goodwill") -> dict:
    return get_success_data(
        api_client.create_credit_memo(
            create_credit_memo_payload(subscriber_id, amount_cents=amount_cents, reason=reason),
            REP,
        )
    )


# ---------------------------------------------------------------------------
# Cancel / save offers
# ---------------------------------------------------------------------------

def cancel_and_get_offer(subscription_id: str, reason: str = "too expensive") -> dict:
    """Cancel an ACTIVE/GRACE subscription and return the auto-created offer."""
    get_success_data(api_client.cancel_subscription(subscription_id, {"reason": reason}, REP))
    offers, _meta = validate_paginated(
        api_client.list_save_offers(REP, params={"subscription_id": subscription_id, "limit": 100})
    )
    assert len(offers) >= 1, "Setup failed: cancel must auto-create a save offer"
    return offers[0]


def setup_cancel_pending(
    start_date: str = "2026-08-03",
    clock: str = "2026-08-03T00:00:00Z",
    plan_overrides: Optional[dict] = None,
    subscriber_overrides: Optional[dict] = None,
) -> dict:
    """ACTIVE subscription driven to CANCEL_PENDING with an OFFERED cancel-flow
    save offer. Returns {"plan", "subscriber", "subscription", "offer"}."""
    ctx = create_active_subscription(
        start_date=start_date,
        clock=clock,
        plan_overrides=plan_overrides,
        subscriber_overrides=subscriber_overrides,
    )
    offer = cancel_and_get_offer(ctx["subscription"]["id"])
    return {
        "plan": ctx["plan"],
        "subscriber": ctx["subscriber"],
        "subscription": get_subscription(ctx["subscription"]["id"]),
        "offer": offer,
    }


# ---------------------------------------------------------------------------
# Distribution: routes / assignments / carriers
# ---------------------------------------------------------------------------

def create_assignment(subscription_id: str, route_id: str,
                      start_date: str, end_date: Optional[str] = None) -> dict:
    return get_success_data(
        api_client.create_route_assignment(
            create_route_assignment_payload(
                subscription_id, route_id, start_date=start_date, end_date=end_date
            ),
            MGR,
        )
    )


def get_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, MGR))


def setup_carrier_with_delivery(
    compensation_model: str = "PER_COPY_GROSS",
    per_copy_rate_cents: int = 50,
    start_date: str = "2026-07-27",
    clock: str = "2026-07-27T00:00:00Z",
) -> dict:
    """Carrier + route + ACTIVE print subscription assigned to the route
    open-ended from start_date. Returns
    {"plan", "carrier", "route", "subscriber", "subscription"}."""
    set_clock(clock)
    plan = create_plan()
    carrier = create_carrier(
        compensation_model=compensation_model, per_copy_rate_cents=per_copy_rate_cents
    )
    route = create_route(carrier_id=carrier["id"])
    subscriber = create_subscriber(service_address="1 Main St")
    subscription = create_subscription(subscriber["id"], plan["id"], start_date=start_date)
    run_daily_cycle()
    create_assignment(subscription["id"], route["id"], start_date)
    return {
        "plan": plan,
        "carrier": carrier,
        "route": route,
        "subscriber": subscriber,
        "subscription": get_subscription(subscription["id"]),
    }


def get_settlement(carrier_id: str, week_start_date: str) -> dict:
    return get_success_data(api_client.get_carrier_settlement(carrier_id, week_start_date, MGR))


# ---------------------------------------------------------------------------
# Rack sales
# ---------------------------------------------------------------------------

def create_rack_report(rack_location_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rack_sales_report(
            create_rack_sales_report_payload(rack_location_id, **overrides), MGR
        )
    )


def setup_submitted_rack_report(**report_overrides) -> dict:
    """Rack + DRAFT report -> SUBMITTED. Returns {"rack", "report"}."""
    rack = create_rack_location()
    report = create_rack_report(rack["id"], **report_overrides)
    submitted = get_success_data(api_client.submit_rack_sales_report(report["id"], MGR))
    return {"rack": rack, "report": submitted}


# ---------------------------------------------------------------------------
# Audit reports
# ---------------------------------------------------------------------------

def create_audit(period_start: str = "2026-08-01", period_end: str = "2026-08-31") -> dict:
    return get_success_data(
        api_client.create_audit_report(
            create_audit_report_payload(period_start=period_start, period_end=period_end),
            DIRECTOR,
        )
    )


# ---------------------------------------------------------------------------
# Two-charge ledger scenario (shared by waterfall / reversal tests)
# ---------------------------------------------------------------------------

def setup_two_charge_subscription(
    weekly_rate_cents: int = 600,
    plan_overrides: Optional[dict] = None,
) -> dict:
    """ACTIVE subscription with exactly two unpaid weekly charges.

    Clock starts at 2026-08-03 (first charge, due 2026-08-17), then advances
    to 2026-08-10 for the second charge (due 2026-08-24).
    Returns {"plan", "subscriber", "subscription", "charges"}.
    """
    overrides = {"base_weekly_rate_cents": weekly_rate_cents}
    overrides.update(plan_overrides or {})
    ctx = create_active_subscription(
        start_date="2026-08-03",
        clock="2026-08-03T00:00:00Z",
        plan_overrides=overrides,
    )
    set_clock_and_cycle("2026-08-10T00:00:00Z")
    charges = list_charges_for_subscription(ctx["subscription"]["id"])
    assert len(charges) == 2, f"Setup failed: expected 2 charges, got {len(charges)}"
    return {
        "plan": ctx["plan"],
        "subscriber": ctx["subscriber"],
        "subscription": get_subscription(ctx["subscription"]["id"]),
        "charges": charges,
    }
