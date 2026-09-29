"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only endpoints the PRD declares.  Setup calls
use the lenient ``get_success_data`` validator so a broken precondition reports
as a setup failure rather than as a confusing assertion failure inside a test.

Layering, from the bottom up:

* clock / single-resource creators (`set_clock`, `new_plan`, `new_subscriber`, ...)
* one-line lookups (`signup_invoice`, `latest_invoice`, `subscription_version`)
* Tier 1 state progression (`drive_to_past_due`, `pause_subscription`, ...)
* Tier 2 hierarchy (`setup_active_subscription`)
* Tier 3 lifecycle shortcuts (`setup_reason_captured_session`, `setup_presented_grant`)
* Tier 4 threshold targeting (`setup_subscription_with_tenure_days`,
  `setup_grant_at_margin`, `setup_dunning_chain`)
* Tier 5 terminal states (`setup_involuntarily_lapsed_subscriber`,
  `setup_voluntarily_lapsed_subscriber`, `setup_launched_campaign_with_target`)
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CORE_PLAN, DEFAULT_CLOCK_UTC, LITE_PLAN
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_retention_specialist_headers,
    make_subscriber_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]
RETENTION = TEST_USERS["retention_specialist_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Instant arithmetic (all logical-clock instants, PRD §2.4)
# ---------------------------------------------------------------------------

def instant(date_or_iso: str) -> str:
    """Normalise ``YYYY-MM-DD`` or a full ISO instant into an ISO 8601 Z string."""
    if len(date_or_iso) == 10:
        return f"{date_or_iso}T00:00:00Z"
    return date_or_iso


def parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_instant(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_days(value: str, days: int) -> str:
    return format_instant(parse_instant(instant(value)) + timedelta(days=days))


def plus_hours(value: str, hours: int) -> str:
    return format_instant(parse_instant(instant(value)) + timedelta(hours=hours))


def days_between(later: str, earlier: str) -> float:
    delta = parse_instant(instant(later)) - parse_instant(instant(earlier))
    return delta.total_seconds() / 86400.0


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> None:
    """Move the logical clock. Accepts ``YYYY-MM-DD`` for brevity."""
    get_success_data(api_client.set_clock(instant(to_iso8601), headers or ADMIN))


def reset_clock() -> None:
    set_clock(DEFAULT_CLOCK_UTC)


# ---------------------------------------------------------------------------
# Single-resource creators
# ---------------------------------------------------------------------------

def new_plan(**overrides) -> Dict[str, Any]:
    payload = f.create_plan_payload(**overrides)
    return get_success_data(api_client.create_plan(payload, ADMIN))


def new_core_plan(**overrides) -> Dict[str, Any]:
    """The canonical 4999/2100 negative-option plan with the MUG/TUMBLER catalogue."""
    payload = dict(CORE_PLAN)
    payload["code"] = f"CORE_{f.unique_suffix()}"
    payload.update(overrides)
    return get_success_data(api_client.create_plan(payload, ADMIN))


def new_lite_plan(**overrides) -> Dict[str, Any]:
    payload = dict(LITE_PLAN)
    payload["code"] = f"LITE_{f.unique_suffix()}"
    payload.update(overrides)
    return get_success_data(api_client.create_plan(payload, ADMIN))


def new_subscriber(**overrides) -> Dict[str, Any]:
    payload = f.create_subscriber_payload(**overrides)
    return get_success_data(api_client.create_subscriber(payload, ADMIN))


def new_payment_method(subscriber_id: str, **overrides) -> Dict[str, Any]:
    payload = f.create_payment_method_payload(subscriber_id, **overrides)
    return get_success_data(api_client.create_payment_method(payload, ADMIN))


def new_subscription(subscriber_id: str, plan_id: str, payment_method_id: str,
                     **overrides) -> Dict[str, Any]:
    payload = f.create_subscription_payload(subscriber_id, plan_id, payment_method_id,
                                            **overrides)
    return get_success_data(api_client.create_subscription(payload, ADMIN))


def new_template(**overrides) -> Dict[str, Any]:
    payload = f.create_save_offer_template_payload(**overrides)
    return get_success_data(api_client.create_save_offer_template(payload, ADMIN))


def new_campaign(**overrides) -> Dict[str, Any]:
    payload = f.create_winback_campaign_payload(**overrides)
    return get_success_data(api_client.create_winback_campaign(payload, RETENTION))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _list_data(response) -> List[Dict[str, Any]]:
    data = get_success_data(response)
    assert isinstance(data, list), f"expected an array payload, got {type(data)}"
    return data


def list_invoices_for(subscription_id: str, **params) -> List[Dict[str, Any]]:
    query = {"subscription_id": subscription_id, "limit": 100}
    query.update(params)
    return _list_data(api_client.list_invoices(ADMIN, params=query))


def signup_invoice(subscription_id: str) -> Dict[str, Any]:
    """The cycle_index 0 invoice created immediately at signup (PRD §3.2)."""
    for invoice in list_invoices_for(subscription_id):
        if invoice["cycle_index"] == 0:
            return invoice
    raise AssertionError(f"no signup invoice found for subscription {subscription_id}")


def invoice_at_cycle(subscription_id: str, cycle_index: int) -> Dict[str, Any]:
    for invoice in list_invoices_for(subscription_id):
        if invoice["cycle_index"] == cycle_index:
            return invoice
    raise AssertionError(
        f"no invoice with cycle_index {cycle_index} on subscription {subscription_id}")


def latest_invoice(subscription_id: str) -> Dict[str, Any]:
    invoices = list_invoices_for(subscription_id)
    assert invoices, f"no invoices on subscription {subscription_id}"
    return max(invoices, key=lambda inv: inv["cycle_index"])


def read_subscription(subscription_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_subscription(subscription_id, ADMIN))


def subscription_version(subscription_id: str) -> int:
    return read_subscription(subscription_id)["version"]


def read_subscriber(subscriber_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_subscriber(subscriber_id, ADMIN))


def read_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def read_grant(grant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_save_offer_grant(grant_id, ADMIN))


def read_session(session_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_cancellation_session(session_id, ADMIN))


def read_modification(modification_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_modification(modification_id, ADMIN))


def read_payment_method(payment_method_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_payment_method(payment_method_id, ADMIN))


def read_campaign(campaign_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_winback_campaign(campaign_id, RETENTION))


def read_target(target_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_winback_target(target_id, RETENTION))


def notices_for(subscription_id: str, **params) -> List[Dict[str, Any]]:
    query = {"limit": 100}
    query.update(params)
    return _list_data(
        api_client.list_subscription_compliance_notices(subscription_id, ADMIN, params=query))


def notice_of_type(subscription_id: str, notice_type: str,
                   renewal_cycle_index: Optional[int] = None) -> Dict[str, Any]:
    for notice in notices_for(subscription_id, notice_type=notice_type):
        if renewal_cycle_index is None or notice["renewal_cycle_index"] == renewal_cycle_index:
            return notice
    raise AssertionError(
        f"no {notice_type} notice on subscription {subscription_id} "
        f"(renewal_cycle_index={renewal_cycle_index})")


def modifications_for(subscription_id: str, **params) -> List[Dict[str, Any]]:
    query = {"subscription_id": subscription_id, "limit": 100}
    query.update(params)
    return _list_data(api_client.list_modifications(ADMIN, params=query))


def attempts_for(invoice_id: str, **params) -> List[Dict[str, Any]]:
    query = {"invoice_id": invoice_id, "limit": 100}
    query.update(params)
    return _list_data(api_client.list_dunning_attempts(ADMIN, params=query))


# ---------------------------------------------------------------------------
# Tier 2: hierarchy — the preamble almost every scenario needs
# ---------------------------------------------------------------------------

def setup_active_subscription(clock: Optional[str] = None,
                              plan: Optional[Dict[str, Any]] = None,
                              plan_overrides: Optional[Dict[str, Any]] = None,
                              subscriber_overrides: Optional[Dict[str, Any]] = None,
                              card_overrides: Optional[Dict[str, Any]] = None,
                              **subscription_overrides) -> Dict[str, Any]:
    """Clock → plan → subscriber → payment method → subscription → signup invoice.

    Returns a world dict with keys ``plan``, ``subscriber``, ``payment_method``,
    ``subscription``, ``invoice`` and ``subscriber_headers`` (identity-threaded
    for ownership-gated calls).
    """
    if clock is not None:
        set_clock(clock)
    if plan is None:
        plan = new_core_plan(**(plan_overrides or {}))
    subscriber = new_subscriber(**(subscriber_overrides or {}))
    payment_method = new_payment_method(subscriber["id"], **(card_overrides or {}))
    subscription = new_subscription(subscriber["id"], plan["id"], payment_method["id"],
                                    **subscription_overrides)
    return {
        "plan": plan,
        "subscriber": subscriber,
        "payment_method": payment_method,
        "subscription": subscription,
        "invoice": signup_invoice(subscription["id"]),
        "subscriber_headers": make_subscriber_headers(subscriber["id"]),
    }


def setup_subscription_with_tenure_days(tenure_days: int,
                                        signup_at: str = "2026-01-10",
                                        **kwargs) -> Dict[str, Any]:
    """Sign up at ``signup_at`` then advance the clock so `tenure_days` reads exactly.

    `tenure_days` is the floor of the elapsed days since `first_subscribed_at`,
    so moving the clock to signup + N days makes it read exactly N.
    """
    world = setup_active_subscription(clock=signup_at, **kwargs)
    set_clock(plus_days(signup_at, tenure_days))
    world["signup_at"] = instant(signup_at)
    world["subscription"] = read_subscription(world["subscription"]["id"])
    world["subscriber"] = read_subscriber(world["subscriber"]["id"])
    return world


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def request_modification(subscription_id: str, mod_type: str, headers: Dict[str, str],
                         expected_version: Optional[int] = None,
                         **payload_fields) -> Dict[str, Any]:
    version = (expected_version if expected_version is not None
               else subscription_version(subscription_id))
    payload = f.create_modification_payload(mod_type, version, **payload_fields)
    return get_success_data(api_client.create_modification(subscription_id, payload, headers))


def pause_subscription(world: Dict[str, Any], pause_start_at: str, pause_end_at: str,
                       **payload_fields) -> Dict[str, Any]:
    """Apply a PAUSE modification, driving lifecycle_state to PAUSED."""
    return request_modification(
        world["subscription"]["id"], "PAUSE", world["subscriber_headers"],
        pause_start_at=instant(pause_start_at), pause_end_at=instant(pause_end_at),
        **payload_fields)


def create_attempt(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.create_dunning_attempt(invoice_id, BILLING))


def settle_attempt(invoice_id: str, outcome: str,
                   decline_code: Optional[str] = None) -> Dict[str, Any]:
    payload = f.simulate_payment_payload(invoice_id, outcome)
    if decline_code is not None:
        payload["decline_code"] = decline_code
    return get_success_data(api_client.simulate_payment(payload, BILLING))


def charge_invoice(invoice_id: str, outcome: str,
                  decline_code: Optional[str] = None) -> Dict[str, Any]:
    """Create the next attempt on an invoice and immediately settle it."""
    create_attempt(invoice_id)
    return settle_attempt(invoice_id, outcome, decline_code)


def pay_invoice(invoice_id: str) -> Dict[str, Any]:
    """Drive an invoice to PAID, which returns billing_state to CURRENT."""
    return charge_invoice(invoice_id, "SUCCEEDED")


def drive_to_past_due(world: Dict[str, Any],
                      decline_code: str = "INSUFFICIENT_FUNDS") -> Dict[str, Any]:
    """One soft decline on the signup invoice: FAILED invoice, PAST_DUE billing axis."""
    attempt = charge_invoice(world["invoice"]["id"], "SOFT_DECLINE", decline_code)
    world["invoice"] = read_invoice(world["invoice"]["id"])
    world["subscription"] = read_subscription(world["subscription"]["id"])
    world["first_attempt"] = attempt
    return world


def submit_updater_result(payment_method_id: str, outcome: str,
                          **fields) -> Dict[str, Any]:
    payload = f.updater_result_payload(outcome, **fields)
    return get_success_data(
        api_client.submit_updater_result(payment_method_id, payload, BILLING))


def run_renewal(subscription_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.run_renewal(subscription_id, BILLING))


def send_notice(notice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.send_compliance_notice(notice_id, BILLING))


def schedule_notice(subscription_id: str, notice_type: str, scheduled_for: str,
                    headers: Optional[Dict[str, str]] = None, **fields) -> Dict[str, Any]:
    payload = f.schedule_notice_payload(notice_type, instant(scheduled_for), **fields)
    return get_success_data(api_client.schedule_compliance_notice(
        subscription_id, payload, headers or BILLING))


def send_renewal_reminder(world: Dict[str, Any], renewal_cycle_index: int = 1) -> Dict[str, Any]:
    """Send the auto-scheduled RENEWAL_REMINDER so the negative-option gate passes.

    The caller must have moved the clock inside the closed reminder window first.
    """
    notice = notice_of_type(world["subscription"]["id"], "RENEWAL_REMINDER",
                            renewal_cycle_index=renewal_cycle_index)
    return send_notice(notice["id"])


# ---------------------------------------------------------------------------
# Tier 3: cancellation-conversation lifecycle shortcuts
# ---------------------------------------------------------------------------

def open_session(world: Dict[str, Any], entry_channel: str = "WEB_SELF_SERVE",
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    payload = f.create_cancellation_session_payload(world["subscription"]["id"],
                                                    entry_channel=entry_channel)
    return get_success_data(api_client.create_cancellation_session(
        payload, headers or world["subscriber_headers"]))


def capture_reason(session_id: str, reason_code: str, headers: Dict[str, str],
                   **fields) -> Dict[str, Any]:
    payload = f.capture_reason_payload(reason_code, **fields)
    return get_success_data(api_client.capture_reason(session_id, payload, headers))


def setup_reason_captured_session(world: Dict[str, Any], reason_code: str = "PRICE",
                                  entry_channel: str = "WEB_SELF_SERVE") -> Dict[str, Any]:
    """Open a session and capture its reason: state REASON_CAPTURED, step_count 2."""
    session = open_session(world, entry_channel=entry_channel)
    session = capture_reason(session["id"], reason_code, world["subscriber_headers"])
    world["session"] = session
    return session


def present_offers(session_id: str, as_user_id: str = "rs_1") -> Dict[str, Any]:
    """Run the one offer-presentation round as a named RetentionSpecialist.

    The acting `X-User-ID` lands on the grant as `presented_by_user_id`, so tests
    that exercise segregation of duties must pass a value here that differs from
    the deciding ComplianceOfficer's identifier.
    """
    return get_success_data(api_client.present_offers(
        session_id, make_retention_specialist_headers(as_user_id)))


def setup_presented_grant(world: Dict[str, Any], reason_code: str = "PRICE",
                          as_user_id: str = "rs_1") -> Dict[str, Any]:
    """Session → reason → present-offers. Stores the session and grant on the world."""
    session = setup_reason_captured_session(world, reason_code=reason_code)
    grant = present_offers(session["id"], as_user_id=as_user_id)
    world["grant"] = grant
    world["session"] = read_session(session["id"])
    return grant


def complete_session(session_id: str, headers: Dict[str, str],
                     confirm: bool = True) -> Dict[str, Any]:
    payload = f.complete_cancellation_payload(confirm)
    return get_success_data(api_client.complete_cancellation(session_id, payload, headers))


def accept_grant(grant_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api_client.accept_grant(grant_id, headers))


def decide_margin_exception(grant_id: str, decision: str, as_user_id: str = "co_1",
                            **fields) -> Dict[str, Any]:
    payload = f.margin_exception_payload(decision, **fields)
    return get_success_data(api_client.decide_margin_exception(
        grant_id, payload, make_compliance_officer_headers(as_user_id)))


# ---------------------------------------------------------------------------
# Tier 4: threshold targeting
# ---------------------------------------------------------------------------

def setup_grant_at_margin(plan_overrides: Dict[str, Any],
                          template_overrides: Dict[str, Any],
                          reason_code: str = "PRICE",
                          clock: str = "2026-01-10",
                          tenure_days: int = 0,
                          as_user_id: str = "rs_1",
                          **subscription_overrides) -> Dict[str, Any]:
    """Build one grant on a plan with a chosen margin floor and one candidate template.

    The template is the only candidate, so the selector is forced onto it and the
    resulting grant's two margin readings are fully determined by the plan and
    template numbers the caller supplies.
    """
    signup_at = clock
    plan = new_core_plan(**plan_overrides)
    template = new_template(eligible_reason_codes=[reason_code], **template_overrides)
    world = setup_active_subscription(clock=signup_at, plan=plan, **subscription_overrides)
    if tenure_days:
        set_clock(plus_days(signup_at, tenure_days))
    world["template"] = template
    world["signup_at"] = instant(signup_at)
    setup_presented_grant(world, reason_code=reason_code, as_user_id=as_user_id)
    return world


def setup_dunning_chain(world: Dict[str, Any],
                        declines: List[str]) -> List[Dict[str, Any]]:
    """Charge the signup invoice once per entry of ``declines``, soft-declining each.

    Returns the settled attempts in order.  The caller controls the clock between
    calls, because the backoff and the grace clamp both read it.
    """
    attempts = []
    for decline_code in declines:
        attempts.append(charge_invoice(world["invoice"]["id"], "SOFT_DECLINE", decline_code))
    world["invoice"] = read_invoice(world["invoice"]["id"])
    world["subscription"] = read_subscription(world["subscription"]["id"])
    return attempts


# ---------------------------------------------------------------------------
# Tier 5: terminal states and win-back
# ---------------------------------------------------------------------------

def setup_involuntarily_lapsed_subscriber(clock: str = "2026-01-10",
                                          decline_code: str = "DO_NOT_HONOR",
                                          **kwargs) -> Dict[str, Any]:
    """Write off the signup invoice with a hard decline.

    The write-off cascade drives the invoice to WRITTEN_OFF, the billing axis to
    DELINQUENT, the lifecycle axis to CANCELLED, and marks the subscriber
    INVOLUNTARY with `lapsed_at` and `winback_suppressed_until` set.
    """
    world = setup_active_subscription(clock=clock, **kwargs)
    world["write_off_attempt"] = charge_invoice(world["invoice"]["id"], "HARD_DECLINE",
                                               decline_code)
    world["invoice"] = read_invoice(world["invoice"]["id"])
    world["subscription"] = read_subscription(world["subscription"]["id"])
    world["subscriber"] = read_subscriber(world["subscriber"]["id"])
    world["lapsed_at"] = world["subscriber"]["lapsed_at"]
    return world


def setup_voluntarily_lapsed_subscriber(clock: str = "2026-01-10",
                                        reason_code: str = "PRICE",
                                        **kwargs) -> Dict[str, Any]:
    """Complete a cancellation, then let the renewal run finalise it.

    Completion moves the subscription to PENDING_CANCEL with `cancel_effective_at`
    at `next_renewal_at`; the renewal run at that instant moves it to CANCELLED
    and stamps the subscriber VOLUNTARY.  The renewal reminder is sent first so
    the negative-option gate is not what the caller trips over.
    """
    world = setup_active_subscription(clock=clock, **kwargs)
    session = setup_reason_captured_session(world, reason_code=reason_code)
    completed = complete_session(session["id"], world["subscriber_headers"])
    world["session"] = completed
    subscription = read_subscription(world["subscription"]["id"])
    set_clock(subscription["cancel_effective_at"])
    run_renewal(subscription["id"])
    world["subscription"] = read_subscription(subscription["id"])
    world["subscriber"] = read_subscriber(world["subscriber"]["id"])
    world["lapsed_at"] = world["subscriber"]["lapsed_at"]
    return world


def setup_launched_campaign(**overrides) -> Dict[str, Any]:
    campaign = new_campaign(**overrides)
    return get_success_data(api_client.launch_winback_campaign(campaign["id"], RETENTION))


def add_target(campaign: Dict[str, Any], subscriber_id: str,
               expected_campaign_version: Optional[int] = None) -> Dict[str, Any]:
    version = (expected_campaign_version if expected_campaign_version is not None
               else read_campaign(campaign["id"])["version"])
    payload = f.create_winback_target_payload(subscriber_id, version)
    return get_success_data(api_client.create_winback_target(campaign["id"], payload, RETENTION))


def send_target(target_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.send_winback_target(target_id, RETENTION))


def reevaluate_target(target_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.reevaluate_winback_target(target_id, RETENTION))


def setup_launched_campaign_with_target(lapse_clock: str = "2026-01-10",
                                        target_clock: Optional[str] = None,
                                        campaign_overrides: Optional[Dict[str, Any]] = None,
                                        churn: str = "INVOLUNTARY",
                                        **kwargs) -> Dict[str, Any]:
    """Lapse one subscriber, launch a campaign, and target that subscriber.

    ``churn`` selects the lapse route: ``INVOLUNTARY`` writes the signup invoice
    off, ``VOLUNTARY`` runs the cancellation conversation to completion.
    """
    if churn == "VOLUNTARY":
        world = setup_voluntarily_lapsed_subscriber(clock=lapse_clock, **kwargs)
    else:
        world = setup_involuntarily_lapsed_subscriber(clock=lapse_clock, **kwargs)
    if target_clock is not None:
        set_clock(target_clock)
    campaign = setup_launched_campaign(**(campaign_overrides or {}))
    world["campaign"] = campaign
    world["target"] = add_target(campaign, world["subscriber"]["id"])
    world["campaign"] = read_campaign(campaign["id"])
    return world


def new_cohort_snapshot(cohort_month: str, ltv_variant: str = "REALIZED",
                        **fields) -> Dict[str, Any]:
    payload = f.create_cohort_snapshot_payload(cohort_month, ltv_variant, **fields)
    return get_success_data(api_client.create_cohort_snapshot(payload, RETENTION))
