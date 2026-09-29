"""Composite setup helpers.

Every helper builds its preconditions from scratch through published endpoints,
because each test starts against an empty database whose logical clock still
reads its initial value.

Two conventions run through this file and must not be relaxed:

- **Identity threading.** A ``Reader`` acts with its own row id in
  ``X-User-ID``; a ``GroupAdmin`` acts with the ``GroupAccount`` id. Helpers
  therefore build headers from the created entity, never from a shared constant,
  whenever the downstream call is ownership-gated.
- **Fresh parent version before every guarded write.** Opening a subscription
  and inviting a seat both carry an expected-version guard, and derived-field
  maintenance moves those versions, so helpers re-read the parent immediately
  before the guarded write.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK_DATE, BASE_CLOCK_INSTANT
from . import factories as f
from .test_users import (
    OPS_AGENT_HEADERS,
    REVENUE_MANAGER_HEADERS,
    make_group_admin_headers,
    make_reader_headers,
)


# --------------------------------------------------------------------------
# Date arithmetic on the logical clock (all whole days, never fractional)
# --------------------------------------------------------------------------


def add_days(iso_date: str, days: int) -> str:
    """Advance an ISO calendar date by a whole number of days."""
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def as_instant(iso_date: str) -> str:
    """Midnight UTC on the given calendar date, in RFC 3339 form."""
    return f"{iso_date}T00:00:00Z"


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------


def set_clock(instant: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Set the monotonic logical clock to an RFC 3339 instant."""
    return get_success_data(
        api_client.set_clock(instant, headers or OPS_AGENT_HEADERS)
    )


def set_clock_date(iso_date: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Set the logical clock to midnight UTC on the given calendar date."""
    return set_clock(as_instant(iso_date), headers)


def use_base_clock(headers: Optional[Dict[str, str]] = None) -> str:
    """Move the clock to the suite's base instant and return its calendar date."""
    set_clock(BASE_CLOCK_INSTANT, headers)
    return BASE_CLOCK_DATE


# --------------------------------------------------------------------------
# Tier 1 — offer plans: state progression and fresh-version reads
# --------------------------------------------------------------------------


def create_plan(payload: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    """Author a DRAFT offer plan as the commercial desk."""
    body = payload if payload is not None else f.create_offer_plan_payload(**overrides)
    return get_success_data(api_client.create_offer_plan(body, REVENUE_MANAGER_HEADERS))


def activate_plan(plan_id: str) -> Dict[str, Any]:
    """Walk the plan DRAFT -> ACTIVE."""
    return get_success_data(api_client.activate_offer_plan(plan_id, REVENUE_MANAGER_HEADERS))


def create_active_plan(payload: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    """Author a plan and open the one-way door to ACTIVE. Returns the ACTIVE plan."""
    plan = create_plan(payload, **overrides)
    return activate_plan(plan["id"])


def create_active_print_plan(**overrides) -> Dict[str, Any]:
    return create_active_plan(f.create_print_digital_plan_payload(**overrides))


def create_active_institutional_plan(**overrides) -> Dict[str, Any]:
    return create_active_plan(f.create_institutional_plan_payload(**overrides))


def read_plan(plan_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Re-read a plan. Reading never mutates, so the version is untouched."""
    return get_success_data(
        api_client.get_offer_plan(plan_id, headers or REVENUE_MANAGER_HEADERS)
    )


def fresh_plan_version(plan_id: str) -> int:
    """The plan's current version, read immediately before a guarded write."""
    return read_plan(plan_id)["version"]


# --------------------------------------------------------------------------
# Tier 1 — readers
# --------------------------------------------------------------------------


def create_reader(payload: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    body = payload if payload is not None else f.create_reader_payload(**overrides)
    return get_success_data(api_client.create_reader(body, OPS_AGENT_HEADERS))


def create_registered_reader(
    email: str = "reader@example.test", **overrides
) -> Dict[str, Any]:
    """A reader who may pay: is_registered true with an email on file."""
    return create_reader(f.create_registered_reader_payload(email=email, **overrides))


def read_reader(reader_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_reader(reader_id, headers or OPS_AGENT_HEADERS)
    )


def log_event(
    reader_id: str, event_type: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    """Record an engagement signal for a reader."""
    return get_success_data(
        api_client.create_reader_event(
            reader_id,
            f.create_reader_event_payload(event_type, **overrides),
            headers or OPS_AGENT_HEADERS,
        )
    )


def create_article(payload: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    body = payload if payload is not None else f.create_article_payload(**overrides)
    return get_success_data(api_client.create_article(body, REVENUE_MANAGER_HEADERS))


def create_paywall_rule(payload: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    body = payload if payload is not None else f.create_paywall_rule_payload(**overrides)
    return get_success_data(api_client.create_paywall_rule(body, REVENUE_MANAGER_HEADERS))


def decide_access(
    reader_id: str, article_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Evaluate the paywall for one reader/article pair; returns the reader event."""
    return get_success_data(
        api_client.create_access_decision(
            f.access_decision_payload(reader_id, article_id),
            headers or OPS_AGENT_HEADERS,
        )
    )


# --------------------------------------------------------------------------
# Tier 2 — subscriptions, invoices and payment attempts
# --------------------------------------------------------------------------


def open_subscription(
    reader_id: str,
    offer_plan_id: str,
    group_account_id: Optional[str] = None,
    expected_offer_plan_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a subscription, re-reading the plan for a fresh guard value."""
    version = (
        expected_offer_plan_version
        if expected_offer_plan_version is not None
        else fresh_plan_version(offer_plan_id)
    )
    payload = f.create_subscription_payload(
        reader_id, offer_plan_id, version, group_account_id
    )
    return get_success_data(api_client.create_subscription(payload, OPS_AGENT_HEADERS))


def read_subscription(
    subscription_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_subscription(subscription_id, headers or OPS_AGENT_HEADERS)
    )


def list_invoices(
    subscription_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    body = api_client.list_subscription_invoices(
        subscription_id, headers or OPS_AGENT_HEADERS, params
    ).json()
    return body["data"]


def invoice_for_cycle(subscription_id: str, cycle_index: int) -> Dict[str, Any]:
    """The invoice billing a given cycle of a subscription."""
    for invoice in list_invoices(subscription_id):
        if invoice["cycle_index"] == cycle_index:
            return invoice
    raise AssertionError(
        f"Setup step failed: no invoice for cycle {cycle_index} on {subscription_id}"
    )


def read_invoice(invoice_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_invoice(invoice_id, headers or OPS_AGENT_HEADERS)
    )


def record_payment(
    invoice: Dict[str, Any],
    outcome: str = "SUCCEEDED",
    amount_cents: Optional[int] = None,
    decline_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a processor result; the tendered amount must equal total_cents."""
    payload = f.create_payment_attempt_payload(
        outcome,
        invoice["total_cents"] if amount_cents is None else amount_cents,
        decline_code,
    )
    return get_success_data(
        api_client.create_payment_attempt(invoice["id"], payload, OPS_AGENT_HEADERS)
    )


def run_billing(scope: str = "FULL") -> Dict[str, Any]:
    """Trigger the nightly batch at the current logical clock."""
    return get_success_data(api_client.create_billing_run(scope, OPS_AGENT_HEADERS))


# --------------------------------------------------------------------------
# Tier 3 — full-lifecycle shortcuts
# --------------------------------------------------------------------------


def setup_digital_subscription(
    paid: bool = True,
    reader_email: str = "reader@example.test",
    reader_overrides: Optional[Dict[str, Any]] = None,
    clock_date: str = BASE_CLOCK_DATE,
    **plan_overrides,
) -> Dict[str, Any]:
    """Active reader on a DIGITAL_ONLY plan, optionally paid into ACTIVE.

    Returns plan, reader, reader_headers, subscription, cycle-1 invoice and the
    activating payment attempt (when ``paid``).
    """
    set_clock_date(clock_date)
    plan = create_active_plan(**plan_overrides)
    reader = create_registered_reader(reader_email, **(reader_overrides or {}))
    subscription = open_subscription(reader["id"], plan["id"])
    invoice = invoice_for_cycle(subscription["id"], 1)
    attempt = None
    if paid:
        attempt = record_payment(invoice, "SUCCEEDED")
        invoice = read_invoice(invoice["id"])
        subscription = read_subscription(subscription["id"])
    return {
        "clock_date": clock_date,
        "plan": plan,
        "reader": reader,
        "reader_headers": make_reader_headers(reader["id"]),
        "subscription": subscription,
        "invoice": invoice,
        "attempt": attempt,
    }


def setup_print_digital_subscription(
    paid: bool = True,
    reader_email: str = "printreader@example.test",
    clock_date: str = BASE_CLOCK_DATE,
    **plan_overrides,
) -> Dict[str, Any]:
    """Paid reader on a PRINT_DIGITAL plan, so print fulfilment is SCHEDULED."""
    set_clock_date(clock_date)
    plan = create_active_print_plan(**plan_overrides)
    reader = create_registered_reader(reader_email)
    subscription = open_subscription(reader["id"], plan["id"])
    invoice = invoice_for_cycle(subscription["id"], 1)
    attempt = None
    if paid:
        attempt = record_payment(invoice, "SUCCEEDED")
        invoice = read_invoice(invoice["id"])
        subscription = read_subscription(subscription["id"])
    return {
        "clock_date": clock_date,
        "plan": plan,
        "reader": reader,
        "reader_headers": make_reader_headers(reader["id"]),
        "subscription": subscription,
        "invoice": invoice,
        "attempt": attempt,
    }


def setup_institutional_group(
    seat_capacity: int = 3,
    paid: bool = True,
    group_name: str = "Univ Library",
    allowed_email_domain: str = "campus.test",
    funding_reader_email: str = "bursar@campus.test",
    clock_date: str = BASE_CLOCK_DATE,
    **plan_overrides,
) -> Dict[str, Any]:
    """Institutional plan, group account and its funding subscription.

    When ``paid`` the funding subscription is ACTIVE, which is the precondition
    every seat invitation and every seat claim checks.
    """
    set_clock_date(clock_date)
    plan = create_active_institutional_plan(**plan_overrides)
    group = get_success_data(
        api_client.create_group_account(
            f.create_group_account_payload(
                plan["id"],
                seat_capacity=seat_capacity,
                name=group_name,
                allowed_email_domain=allowed_email_domain,
                admin_email=f"admin@{allowed_email_domain}",
            ),
            OPS_AGENT_HEADERS,
        )
    )
    funding_reader = create_registered_reader(funding_reader_email)
    subscription = open_subscription(funding_reader["id"], plan["id"], group["id"])
    invoice = invoice_for_cycle(subscription["id"], 1)
    attempt = None
    if paid:
        attempt = record_payment(invoice, "SUCCEEDED")
        invoice = read_invoice(invoice["id"])
        subscription = read_subscription(subscription["id"])
    return {
        "clock_date": clock_date,
        "plan": plan,
        "group": group,
        "group_headers": make_group_admin_headers(group["id"]),
        "funding_reader": funding_reader,
        "subscription": subscription,
        "invoice": invoice,
        "attempt": attempt,
    }


def read_group(group_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_group_account(group_id, headers or OPS_AGENT_HEADERS)
    )


def fresh_group_version(group_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """The group's current version, read immediately before a guarded invite."""
    return read_group(group_id, headers)["version"]


def invite_seat(
    group_id: str,
    reader_id: str,
    starts_on: str,
    ends_on: Optional[str] = None,
    admin_headers: Optional[Dict[str, str]] = None,
    expected_group_account_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Invite a reader to a seat, re-reading the group for a fresh guard value."""
    headers = admin_headers or make_group_admin_headers(group_id)
    version = (
        expected_group_account_version
        if expected_group_account_version is not None
        else fresh_group_version(group_id, headers)
    )
    payload = f.create_seat_payload(reader_id, starts_on, version, ends_on)
    return get_success_data(api_client.create_seat(group_id, payload, headers))


def read_seat(seat_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_seat(seat_id, headers or OPS_AGENT_HEADERS))


def list_seats(params: Optional[Dict] = None, headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    return api_client.list_seats(headers or OPS_AGENT_HEADERS, params).json()["data"]


# --------------------------------------------------------------------------
# Tier 4 — accumulation and threshold targeting
# --------------------------------------------------------------------------


def advance_to_next_cycle(scenario: Dict[str, Any], scope: str = "BILLING_ONLY") -> Dict[str, Any]:
    """Move the clock to paid_through_on and bill the next cycle.

    Returns the refreshed subscription, the newly billed invoice and the run
    report, so threshold tests can start from the second cycle.
    """
    subscription = read_subscription(scenario["subscription"]["id"])
    next_cycle_start = subscription["paid_through_on"]
    set_clock_date(next_cycle_start)
    report = run_billing(scope)
    subscription = read_subscription(subscription["id"])
    invoice = invoice_for_cycle(subscription["id"], subscription["cycle_index"])
    return {
        "clock_date": next_cycle_start,
        "report": report,
        "subscription": subscription,
        "invoice": invoice,
    }


def setup_retrying_subscription(
    card_last4: str = "4242",
    card_exp_month: int = 11,
    card_exp_year: int = 2027,
    card_updater_registered: bool = False,
    reader_email: str = "dunning@example.test",
    decline_code: str = "do_not_honor",
    clock_date: str = BASE_CLOCK_DATE,
    **plan_overrides,
) -> Dict[str, Any]:
    """A subscription in the middle of an open dunning episode.

    Cycle 1 is paid, the clock advances to the next cycle, the BILLING pass
    raises the cycle-2 invoice, and one non-final SOFT_DECLINE drives the
    dunning dimension into RETRYING.
    """
    set_clock_date(clock_date)
    plan = create_active_plan(**plan_overrides)
    reader = create_registered_reader(
        reader_email,
        card_last4=card_last4,
        card_exp_month=card_exp_month,
        card_exp_year=card_exp_year,
        card_updater_registered=card_updater_registered,
    )
    subscription = open_subscription(reader["id"], plan["id"])
    cycle1 = invoice_for_cycle(subscription["id"], 1)
    record_payment(cycle1, "SUCCEEDED")
    cycle = advance_to_next_cycle({"subscription": subscription})
    attempt = record_payment(cycle["invoice"], "SOFT_DECLINE", decline_code=decline_code)
    return {
        "clock_date": cycle["clock_date"],
        "plan": plan,
        "reader": read_reader(reader["id"]),
        "reader_headers": make_reader_headers(reader["id"]),
        "subscription": read_subscription(subscription["id"]),
        "cycle1_invoice": read_invoice(cycle1["id"]),
        "invoice": read_invoice(cycle["invoice"]["id"]),
        "attempt": attempt,
    }


# --------------------------------------------------------------------------
# Tier 5 — the regulated cancellation flow and terminal states
# --------------------------------------------------------------------------


def create_hold(
    subscription_id: str,
    hold_type: str,
    start_date: str,
    end_date: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_hold(
            subscription_id,
            f.create_hold_payload(hold_type, start_date, end_date),
            headers or OPS_AGENT_HEADERS,
        )
    )


def read_hold(hold_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_hold(hold_id, headers or OPS_AGENT_HEADERS))


def list_holds(
    subscription_id: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    return api_client.list_holds(
        subscription_id, headers or OPS_AGENT_HEADERS, params
    ).json()["data"]


def start_cancellation(
    subscription_id: str,
    reason_code: str = "PRICE",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_cancellation_request(
            subscription_id,
            f.create_cancellation_request_payload(reason_code),
            headers or OPS_AGENT_HEADERS,
        )
    )


def read_cancellation_request(
    request_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_cancellation_request(request_id, headers or OPS_AGENT_HEADERS)
    )


def present_save_offer(
    request_id: str, offer_type: str = "RETENTION_DISCOUNT", **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_save_offer(
            request_id,
            f.create_save_offer_payload(offer_type, **overrides),
            OPS_AGENT_HEADERS,
        )
    )


def read_save_offer(offer_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_save_offer(offer_id, headers or OPS_AGENT_HEADERS)
    )


def setup_cancellation_flow(
    reason_code: str = "PRICE", scenario: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """A paid subscription with an open cancellation request in INITIATED."""
    base = scenario or setup_digital_subscription(**kwargs)
    request = start_cancellation(
        base["subscription"]["id"], reason_code, base["reader_headers"]
    )
    return {**base, "cancellation_request": request}


def setup_presented_save_offer(
    offer_type: str = "RETENTION_DISCOUNT",
    scenario: Optional[Dict[str, Any]] = None,
    offer_overrides: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """The single permitted save offer, presented inside an open flow."""
    base = scenario or setup_cancellation_flow(**kwargs)
    offer = present_save_offer(
        base["cancellation_request"]["id"], offer_type, **(offer_overrides or {})
    )
    return {
        **base,
        "save_offer": offer,
        "cancellation_request": read_cancellation_request(
            base["cancellation_request"]["id"]
        ),
    }


def setup_confirmed_cancellation(
    scenario: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """A confirmed cancellation: the subscription is CANCEL_SCHEDULED."""
    base = scenario or setup_cancellation_flow(**kwargs)
    request = get_success_data(
        api_client.confirm_cancellation(
            base["cancellation_request"]["id"], base["reader_headers"]
        )
    )
    return {
        **base,
        "cancellation_request": request,
        "subscription": read_subscription(base["subscription"]["id"]),
    }


def setup_cancelled_subscription(
    scenario: Optional[Dict[str, Any]] = None, **kwargs
) -> Dict[str, Any]:
    """A subscription driven all the way to CANCELLED by the EXPIRY pass."""
    base = setup_confirmed_cancellation(scenario, **kwargs)
    effective_on = base["cancellation_request"]["effective_on"]
    set_clock_date(add_days(effective_on, 1))
    report = run_billing("EXPIRY_ONLY")
    return {
        **base,
        "clock_date": add_days(effective_on, 1),
        "report": report,
        "cancellation_request": read_cancellation_request(
            base["cancellation_request"]["id"]
        ),
        "subscription": read_subscription(base["subscription"]["id"]),
    }


# --------------------------------------------------------------------------
# The regulated price-increase pipeline
# --------------------------------------------------------------------------


def schedule_price_change(
    plan_id: str,
    pending_price_cents: int = 1799,
    pending_effective_on: str = "2026-10-15",
    grandfather_policy: str = "NONE",
) -> Dict[str, Any]:
    """Move the pipeline NONE -> SCHEDULED with a fresh version guard."""
    payload = f.schedule_price_change_payload(
        fresh_plan_version(plan_id),
        pending_price_cents,
        pending_effective_on,
        grandfather_policy,
    )
    return get_success_data(
        api_client.schedule_price_change(plan_id, payload, REVENUE_MANAGER_HEADERS)
    )


def dispatch_notices(plan_id: str, officer_headers: Dict[str, str]) -> Dict[str, Any]:
    """Move the pipeline SCHEDULED -> NOTICE_SENT as a named compliance officer."""
    return get_success_data(
        api_client.dispatch_price_change_notices(plan_id, officer_headers)
    )


def setup_scheduled_price_change(
    pending_price_cents: int = 1799,
    pending_effective_on: str = "2026-10-15",
    grandfather_policy: str = "NONE",
    clock_date: str = BASE_CLOCK_DATE,
    **plan_overrides,
) -> Dict[str, Any]:
    """An ACTIVE plan whose price-change pipeline sits at SCHEDULED."""
    set_clock_date(clock_date)
    plan = create_active_plan(**plan_overrides)
    plan = schedule_price_change(
        plan["id"], pending_price_cents, pending_effective_on, grandfather_policy
    )
    return {"clock_date": clock_date, "plan": plan}


def setup_noticed_price_change(
    officer_headers: Dict[str, str],
    pending_price_cents: int = 1799,
    pending_effective_on: str = "2026-10-15",
    grandfather_policy: str = "NONE",
    clock_date: str = BASE_CLOCK_DATE,
    **plan_overrides,
) -> Dict[str, Any]:
    """An ACTIVE plan whose pipeline sits at NOTICE_SENT, noticed by one officer."""
    base = setup_scheduled_price_change(
        pending_price_cents, pending_effective_on, grandfather_policy, clock_date,
        **plan_overrides,
    )
    plan = dispatch_notices(base["plan"]["id"], officer_headers)
    return {**base, "plan": plan}
