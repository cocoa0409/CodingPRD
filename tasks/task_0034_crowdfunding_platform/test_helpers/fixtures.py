"""Composite setup helpers for the Crowdfunding Platform test suite.

The PRD's lifecycle has many interlocking phases — Initiator (KYC) →
Project (DRAFT → CONTENT_REVIEW → LEGAL_REVIEW → FINANCIAL_REVIEW → LIVE
→ SUCCEEDED|FAILED|CANCELLED), Reward, Order (AUTHORIZED → CHARGE_PENDING
→ CHARGED → PARTIALLY_REFUNDED|REFUNDED|VOIDED, fulfillment in parallel),
RefundRequest (PENDING_REVIEW → APPROVED → EXECUTED), SettlementBatch
(DRAFT → FINALIZED → PAID|FAILED). Most interesting tests need the system
in a non-initial state.

Identity threading (PRD §2.1):

- Initiator is entity-backed: ownership-gated calls on an initiator's
  project (PATCH /projects, /submit, /cancel, /rewards, /add-on-items,
  /progress-updates) MUST use make_initiator_headers(initiator['id']).

- Backer is entity-backed: ownership-gated calls on the backer's order
  (PATCH /orders, /cancel, POST /refund-requests for own order) MUST use
  make_backer_headers(backer['id']).

Setup calls use get_success_data (lenient validator) so broken
preconditions surface as obvious errors, not confusing assertion failures.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_on_line,
    create_add_on_item_payload,
    create_backer_payload,
    create_initiator_payload,
    create_order_payload,
    create_progress_update_payload,
    create_project_payload,
    create_refund_request_payload,
    create_reward_payload,
    create_settlement_batch_payload,
    default_shipping_address,
    review_payload,
    shipment_line,
    unique_email,
    unique_name,
    verify_kyc_payload,
)
from .test_users import (
    TEST_USERS,
    make_backer_headers,
    make_content_reviewer_headers,
    make_financial_reviewer_headers,
    make_initiator_headers,
    make_legal_reviewer_headers,
    make_platform_admin_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 — ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_seconds(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(seconds=n))


def add_minutes(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(minutes=n))


def add_hours(s: str, n: float) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


# Default base instant used unless a test pins something else. Each test
# session gets a fresh wall clock; tests that need to advance the clock
# pin their own `now`.
DEFAULT_NOW_ISO = "2026-06-01T00:00:00.000Z"


# ===========================================================================
# Test-driving wrappers (PRD §4)
# ===========================================================================
_last_known_clock_iso: Optional[str] = None


def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §4 mounts this as a PlatformAdmin-only
    test driver. The simulated clock is shared across tests in a session;
    if the requested time is at or before the last known clock, this
    helper silently NO-OPs (forward-only)."""
    global _last_known_clock_iso
    if (_last_known_clock_iso is not None
            and parse_iso(to_iso) <= parse_iso(_last_known_clock_iso)):
        return {}
    res = api_client.advance_clock(
        to_iso, headers or TEST_USERS["platform_admin_headers"]
    )
    data = get_success_data(res)
    _last_known_clock_iso = to_iso
    return data


def current_clock_iso() -> str:
    """Best-effort mirror of the most recent clock instant we've advanced
    to. Falls back to a stable floor if nothing has been advanced yet."""
    return _last_known_clock_iso or DEFAULT_NOW_ISO


def emit_payment(order_id: str, result: str,
                 external_ref: Optional[str] = None) -> Dict[str, Any]:
    """POST /_events/payment as PlatformAdmin (PRD §4)."""
    return get_success_data(
        api_client.emit_payment_event(
            order_id, result, TEST_USERS["platform_admin_headers"],
            external_ref=external_ref,
        )
    )


def emit_banking(subject_type: str, subject_id: str, result: str,
                 external_ref: Optional[str] = None) -> Dict[str, Any]:
    """POST /_events/banking as PlatformAdmin (PRD §4)."""
    return get_success_data(
        api_client.emit_banking_event(
            subject_type, subject_id, result,
            TEST_USERS["platform_admin_headers"],
            external_ref=external_ref,
        )
    )


def emit_logistics(order_id: str, lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """POST /_events/logistics as PlatformAdmin (PRD §4)."""
    return get_success_data(
        api_client.emit_logistics_event(
            order_id, lines, TEST_USERS["platform_admin_headers"]
        )
    )


# ===========================================================================
# Tier 1 — single-entity creation
# ===========================================================================
def create_initiator(*, with_tax_id: bool = True,
                     legal_name: Optional[str] = None,
                     **overrides: Any) -> Dict[str, Any]:
    """Register an Initiator. By default supplies a tax_id so downstream
    settlement uses the standard withholding rule (PRD §3.12)."""
    payload = create_initiator_payload(
        legal_name=legal_name or unique_name("Init"),
        tax_id=("TAX-" + unique_name("ID")[:10]) if with_tax_id else None,
        bank_account_id="BANK-" + unique_name("BA")[:10],
        **overrides,
    )
    res = api_client.create_initiator(
        payload, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def verify_kyc(initiator_id: str, *, decision: str = "VERIFIED") -> Dict[str, Any]:
    res = api_client.verify_kyc(
        initiator_id, verify_kyc_payload(decision=decision),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def create_verified_initiator(*, with_tax_id: bool = True,
                              **overrides: Any) -> Dict[str, Any]:
    """Initiator with kyc_status=VERIFIED — the precondition for project
    submit (PRD §3.3)."""
    initiator = create_initiator(with_tax_id=with_tax_id, **overrides)
    verified = verify_kyc(initiator["id"], decision="VERIFIED")
    # verify_kyc returns the updated Initiator; merge to keep any fields
    # the caller might inspect.
    return {**initiator, **verified}


def create_backer(*, display_name: Optional[str] = None,
                  email: Optional[str] = None,
                  default_shipping_address_value: Optional[Dict[str, Any]] = None,
                  **overrides: Any) -> Dict[str, Any]:
    payload = create_backer_payload(
        display_name=display_name or unique_name("Backer"),
        email=email or unique_email("backer"),
        default_shipping_address=default_shipping_address_value,
        **overrides,
    )
    res = api_client.create_backer(
        payload, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def create_draft_project(*, initiator: Dict[str, Any],
                         category: str = "TECH",
                         funding_model: str = "ALL_OR_NOTHING",
                         funding_target_cents: int = 1_000_000,
                         deadline: Optional[str] = None,
                         deadline_hours_from_now: float = 240.0,
                         **overrides: Any) -> Dict[str, Any]:
    """Create a Project in DRAFT for the given initiator.

    Default deadline is 240h (10 days) from the current server clock so
    the project comfortably satisfies the 'deadline must be more than 24
    hours after the current time' submit gate (PRD §3.3) without
    colliding with prior tests that may have advanced the simulated
    clock.
    """
    if deadline is None:
        deadline = add_hours(current_clock_iso(), deadline_hours_from_now)
    payload = create_project_payload(
        category=category,
        funding_model=funding_model,
        funding_target_cents=funding_target_cents,
        deadline=deadline,
        **overrides,
    )
    res = api_client.create_project(
        payload, make_initiator_headers(initiator["id"])
    )
    return get_success_data(res)


def create_reward(*, project: Dict[str, Any], initiator: Dict[str, Any],
                  pledge_amount_cents: int = 5_000,
                  reward_type: str = "PHYSICAL",
                  inventory_limit: Optional[int] = None,
                  tier_label: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    payload = create_reward_payload(
        tier_label=tier_label,
        pledge_amount_cents=pledge_amount_cents,
        reward_type=reward_type,
        inventory_limit=inventory_limit,
        **overrides,
    )
    res = api_client.create_reward(
        project["id"], payload, make_initiator_headers(initiator["id"])
    )
    return get_success_data(res)


def create_add_on_item(*, project: Dict[str, Any],
                       initiator: Dict[str, Any],
                       price_cents: int = 1_000,
                       requires_shipping: bool = False,
                       inventory_limit: Optional[int] = None,
                       name: Optional[str] = None,
                       **overrides: Any) -> Dict[str, Any]:
    payload = create_add_on_item_payload(
        name=name,
        price_cents=price_cents,
        requires_shipping=requires_shipping,
        inventory_limit=inventory_limit,
        **overrides,
    )
    res = api_client.create_add_on_item(
        project["id"], payload, make_initiator_headers(initiator["id"])
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2 — review pipeline progression
# ===========================================================================
def submit_project(*, project: Dict[str, Any],
                   initiator: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.submit_project(
        project["id"], make_initiator_headers(initiator["id"])
    )
    return get_success_data(res)


def review_content(*, project_id: str, decision: str = "APPROVE",
                   reviewer_id: str = "content-reviewer-001",
                   message: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.review_content(
        project_id,
        review_payload(decision=decision, message=message),
        make_content_reviewer_headers(reviewer_id),
    )
    return get_success_data(res)


def review_legal(*, project_id: str, decision: str = "APPROVE",
                 reviewer_id: str = "legal-reviewer-001",
                 message: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.review_legal(
        project_id,
        review_payload(decision=decision, message=message),
        make_legal_reviewer_headers(reviewer_id),
    )
    return get_success_data(res)


def review_financial(*, project_id: str, decision: str = "APPROVE",
                     reviewer_id: str = "financial-reviewer-001",
                     message: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.review_financial(
        project_id,
        review_payload(decision=decision, message=message),
        make_financial_reviewer_headers(reviewer_id),
    )
    return get_success_data(res)


def take_project_live(*, project: Dict[str, Any],
                      initiator: Dict[str, Any]) -> Dict[str, Any]:
    """Walk a DRAFT project through CONTENT_REVIEW → LEGAL_REVIEW →
    FINANCIAL_REVIEW → LIVE. Uses three distinct reviewer X-User-IDs so
    the segregation-of-duties rule (PRD §3.3) is satisfied.

    Returns the LIVE project snapshot.
    """
    submit_project(project=project, initiator=initiator)
    review_content(project_id=project["id"], decision="APPROVE",
                   reviewer_id="content-rev-" + unique_name("X")[:6])
    review_legal(project_id=project["id"], decision="APPROVE",
                 reviewer_id="legal-rev-" + unique_name("X")[:6])
    final = review_financial(
        project_id=project["id"], decision="APPROVE",
        reviewer_id="financial-rev-" + unique_name("X")[:6],
    )
    return final


# ===========================================================================
# Tier 2 — composite "ready to back" setup
# ===========================================================================
def setup_live_project(
    *,
    category: str = "TECH",
    funding_model: str = "ALL_OR_NOTHING",
    funding_target_cents: int = 1_000_000,
    deadline_hours_from_now: float = 240.0,
    reward_pledge_cents: int = 5_000,
    reward_type: str = "PHYSICAL",
    reward_inventory_limit: Optional[int] = None,
    with_tax_id: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build the most common starting state: a verified Initiator, a LIVE
    Project, and one Reward. Returns (initiator, project, reward).

    A LIVE project requires: KYC verified initiator, draft project with
    title/desc/risk/media, deadline > now + 24h, ≥1 reward, all three
    review stages approved by distinct reviewers (PRD §3.3).
    """
    initiator = create_verified_initiator(with_tax_id=with_tax_id)
    project = create_draft_project(
        initiator=initiator,
        category=category,
        funding_model=funding_model,
        funding_target_cents=funding_target_cents,
        deadline_hours_from_now=deadline_hours_from_now,
    )
    reward = create_reward(
        project=project, initiator=initiator,
        pledge_amount_cents=reward_pledge_cents,
        reward_type=reward_type,
        inventory_limit=reward_inventory_limit,
    )
    project = take_project_live(project=project, initiator=initiator)
    return initiator, project, reward


# ===========================================================================
# Tier 3 — order placement
# ===========================================================================
def place_order(
    *,
    project: Dict[str, Any],
    reward: Dict[str, Any],
    backer: Dict[str, Any],
    add_ons: Optional[List[Dict[str, Any]]] = None,
    shipping_address: Optional[Dict[str, Any]] = None,
    payment_method_token: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /orders for the given backer on the given project/reward.

    PRD §3.4: 'A shipping_address is mandatory whenever the selected
    reward's reward_type is PHYSICAL or any referenced add-on has
    requires_shipping true.' For convenience the helper auto-supplies the
    default shipping address if the reward is PHYSICAL and the caller did
    not pass one.
    """
    if shipping_address is None and reward.get("reward_type") == "PHYSICAL":
        shipping_address = default_shipping_address()
    payload = create_order_payload(
        project_id=project["id"],
        reward_id=reward["id"],
        add_ons=add_ons,
        shipping_address=shipping_address,
        payment_method_token=payment_method_token,
    )
    res = api_client.create_order(
        payload, make_backer_headers(backer["id"])
    )
    return get_success_data(res)


def setup_live_with_order(
    *,
    category: str = "TECH",
    funding_model: str = "ALL_OR_NOTHING",
    funding_target_cents: int = 1_000_000,
    reward_pledge_cents: int = 5_000,
    reward_type: str = "PHYSICAL",
    deadline_hours_from_now: float = 240.0,
    with_tax_id: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """LIVE project + Reward + a Backer who placed one AUTHORIZED Order.
    Returns (initiator, project, reward, backer, order)."""
    initiator, project, reward = setup_live_project(
        category=category,
        funding_model=funding_model,
        funding_target_cents=funding_target_cents,
        reward_pledge_cents=reward_pledge_cents,
        reward_type=reward_type,
        deadline_hours_from_now=deadline_hours_from_now,
        with_tax_id=with_tax_id,
    )
    backer = create_backer()
    order = place_order(project=project, reward=reward, backer=backer)
    return initiator, project, reward, backer, order


# ===========================================================================
# Tier 4 — charge wave drivers (drives Project SUCCEEDED + per-order CHARGE)
# ===========================================================================
def drive_clock_past_deadline(*, project: Dict[str, Any],
                              past_seconds: int = 1) -> str:
    """Advance the simulated clock to project.deadline + past_seconds.
    PRD §3.5: 'When the clock crosses a project's deadline while the
    project is in LIVE, exactly one of two transitions occurs.' Returns
    the new clock instant.
    """
    target = add_seconds(project["deadline"], past_seconds)
    advance_clock(target)
    return target


def charge_order_success(order_id: str) -> Dict[str, Any]:
    """Drive a CHARGE_PENDING order through SUCCESS → CHARGED."""
    return emit_payment(order_id, "SUCCESS")


def charge_order_failure_until_failed(order_id: str,
                                      max_attempts: int = 3) -> Dict[str, Any]:
    """Drive a CHARGE_PENDING order through max_attempts FAILUREs. PRD
    §3.6: order reverts to AUTHORIZED while charge_attempts < 3 and
    transitions to CHARGE_FAILED on the attempt where charge_attempts
    reaches 3. The first FAILURE is delivered while the order is in
    CHARGE_PENDING (charge_attempts==1), reverting to AUTHORIZED. To
    re-enter CHARGE_PENDING we re-emit a payment event in CHARGE_PENDING
    state — but since reentry into CHARGE_PENDING is automatic on
    Project.SUCCEEDED, this helper handles the case of a single retry
    cycle by sending FAILUREs in sequence until CHARGE_FAILED.

    NOTE: The PRD specifies retry semantics (cycle AUTHORIZED →
    CHARGE_PENDING → AUTHORIZED). This helper sends FAILUREs assuming
    that each FAILURE on AUTHORIZED triggers a re-enqueue to
    CHARGE_PENDING; if the reference implementation requires explicit
    re-trigger, individual tests may need to use emit_payment directly.
    """
    last: Dict[str, Any] = {}
    for _ in range(max_attempts):
        last = emit_payment(order_id, "FAILURE")
    return last


def succeed_project_and_charge_all(
    *,
    project: Dict[str, Any],
    orders: List[Dict[str, Any]],
    payment_results: Optional[List[str]] = None,
    past_seconds: int = 1,
) -> str:
    """Push project past deadline (triggering LIVE → SUCCEEDED), then
    drive each AUTHORIZED order through one payment event using the
    supplied results list (default: all SUCCESS).

    Returns the new clock instant.
    """
    new_now = drive_clock_past_deadline(project=project,
                                        past_seconds=past_seconds)
    if payment_results is None:
        payment_results = ["SUCCESS"] * len(orders)
    assert len(payment_results) == len(orders), (
        "payment_results length must match orders length"
    )
    for o, r in zip(orders, payment_results):
        emit_payment(o["id"], r)
    return new_now


# ===========================================================================
# Tier 5 — refund flow
# ===========================================================================
def create_refund_request(*, order: Dict[str, Any], backer: Dict[str, Any],
                          requested_amount_cents: int,
                          reason: str = "DISPUTE") -> Dict[str, Any]:
    payload = create_refund_request_payload(
        order_id=order["id"],
        reason=reason,
        requested_amount_cents=requested_amount_cents,
    )
    res = api_client.create_refund_request(
        payload, make_backer_headers(backer["id"])
    )
    return get_success_data(res)


def approve_refund(refund_id: str) -> Dict[str, Any]:
    res = api_client.approve_refund(
        refund_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def execute_refund(refund_id: str) -> Dict[str, Any]:
    res = api_client.execute_refund(
        refund_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def reject_refund(refund_id: str, *,
                  rejection_reason: str = "Not eligible") -> Dict[str, Any]:
    from .factories import reject_refund_payload
    res = api_client.reject_refund(
        refund_id, reject_refund_payload(rejection_reason=rejection_reason),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(res)


def setup_charged_order(
    *,
    category: str = "TECH",
    reward_pledge_cents: int = 10_000,
    funding_target_cents: int = 5_000,  # below pledge so funding_model met
    funding_model: str = "ALL_OR_NOTHING",
    with_tax_id: bool = True,
    deadline_hours_from_now: float = 240.0,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """LIVE → SUCCEEDED with one CHARGED order. Returns
    (initiator, project, reward, backer, charged_order)."""
    initiator, project, reward, backer, order = setup_live_with_order(
        category=category,
        funding_model=funding_model,
        funding_target_cents=funding_target_cents,
        reward_pledge_cents=reward_pledge_cents,
        with_tax_id=with_tax_id,
        deadline_hours_from_now=deadline_hours_from_now,
    )
    succeed_project_and_charge_all(project=project, orders=[order])
    charged = get_success_data(
        api_client.get_order(order["id"], TEST_USERS["platform_admin_headers"])
    )
    return initiator, project, reward, backer, charged


# ===========================================================================
# Tier 6 — settlement flow
# ===========================================================================
def create_draft_settlement_batch(*, project: Dict[str, Any],
                                  period_start: str,
                                  period_end: str) -> Dict[str, Any]:
    payload = create_settlement_batch_payload(
        period_start=period_start, period_end=period_end
    )
    res = api_client.create_settlement_batch(
        project["id"], payload, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def finalize_settlement_batch(*, project: Dict[str, Any],
                              batch: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.finalize_settlement_batch(
        project["id"], batch["id"], TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def publish_progress_update(*, project: Dict[str, Any],
                            initiator: Dict[str, Any],
                            visibility: str = "PUBLIC",
                            title: Optional[str] = None,
                            body_md: str = "Progress.") -> Dict[str, Any]:
    """Publish a ProgressUpdate. PRD §3.9: 'Publishing an update sets the
    project's last_update_published_at to the current time.' Used to
    satisfy the silence-window precondition on settlement finalize."""
    payload = create_progress_update_payload(
        title=title, body_md=body_md, visibility=visibility,
    )
    res = api_client.create_progress_update(
        project["id"], payload, make_initiator_headers(initiator["id"])
    )
    return get_success_data(res)


# ===========================================================================
# Difficulty-design composite fixtures
# ===========================================================================
def setup_provisional_vs_final_three_orders(
    *, deadline_hours_from_now: float = 72.0,
) -> Dict[str, Any]:
    """Difficulty Rule 1 / funding_progress_provisional_vs_final.

    Setup: TECH ALL_OR_NOTHING project with funding_target=20000, three
    backers each placing an AUTHORIZED order of 10000 cents. After
    advancing the clock past the deadline, two orders' charges succeed
    and one order's charge fails three times.

    Returns:
      {
        'initiator', 'project', 'reward',
        'backers': [b1, b2, b3],
        'orders': [o1, o2, o3],   # AUTHORIZED at fixture-return time
      }

    The test drives the actual charge wave so it can read provisional vs
    final at the right instants.
    """
    initiator, project, reward = setup_live_project(
        category="TECH",
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=20_000,
        reward_pledge_cents=10_000,
        reward_type="PHYSICAL",
        deadline_hours_from_now=deadline_hours_from_now,
        with_tax_id=True,
    )
    backers = [create_backer() for _ in range(3)]
    orders = [
        place_order(project=project, reward=reward, backer=b)
        for b in backers
    ]
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backers": backers,
        "orders": orders,
    }


def setup_charged_order_with_total(
    *,
    order_total_cents: int = 15_000,
    category: str = "TECH",
    with_tax_id: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Difficulty Rule 1 / order_refundable_remainder_pre_vs_post_shipment
    setup. Build a SUCCEEDED project with one CHARGED order whose
    order_total_cents equals the requested target.

    Returns (initiator, project, reward, backer, order_charged).
    """
    return setup_charged_order(
        category=category,
        reward_pledge_cents=order_total_cents,
        funding_target_cents=order_total_cents - 1,  # ensure SUCCESS branch
        funding_model="ALL_OR_NOTHING",
        with_tax_id=with_tax_id,
    )


def setup_three_charged_orders_for_commission(
    *, totals_cents: List[int],
    category: str = "TECH",
) -> Dict[str, Any]:
    """Difficulty Rule 2 / per_order_rounding_then_sum_for_batch_commission.

    Setup: SUCCEEDED TECH project (commission rate 500 bps), three CHARGED
    orders with the requested per-order totals. Returns dict with
    initiator, project, rewards, backers, orders.
    """
    assert len(totals_cents) >= 1
    initiator = create_verified_initiator(with_tax_id=True)
    project = create_draft_project(
        initiator=initiator, category=category,
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=1,  # trivially met
        deadline_hours_from_now=240.0,
    )
    rewards = [
        create_reward(
            project=project, initiator=initiator,
            pledge_amount_cents=t, reward_type="DIGITAL",
        )
        for t in totals_cents
    ]
    project = take_project_live(project=project, initiator=initiator)
    backers = [create_backer() for _ in totals_cents]
    orders = []
    for r, b in zip(rewards, backers):
        orders.append(place_order(project=project, reward=r, backer=b))
    succeed_project_and_charge_all(project=project, orders=orders)
    refreshed_orders = [
        get_success_data(api_client.get_order(
            o["id"], TEST_USERS["platform_admin_headers"]
        ))
        for o in orders
    ]
    return {
        "initiator": initiator,
        "project": project,
        "rewards": rewards,
        "backers": backers,
        "orders": refreshed_orders,
    }


def setup_revision_loop_project() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Difficulty Rule 3 / project_review_revision_loop_cycle.

    Setup: a Project in DRAFT with all submit-preconditions satisfied,
    plus a verified Initiator. Returns (initiator, project_in_draft).
    """
    initiator = create_verified_initiator(with_tax_id=True)
    project = create_draft_project(
        initiator=initiator,
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=10_000,
        deadline_hours_from_now=240.0,
    )
    create_reward(
        project=project, initiator=initiator,
        pledge_amount_cents=5_000, reward_type="DIGITAL",
    )
    return initiator, project


def setup_charged_order_for_partial_shipment() -> Dict[str, Any]:
    """Difficulty Rule 3 / order_parallel_payment_and_fulfillment_dimensions.

    Setup: SUCCEEDED project with one CHARGED order, order_total=10000.
    Returns dict with initiator, project, reward, backer, order_charged.
    """
    initiator, project, reward, backer, charged = setup_charged_order(
        category="TECH",
        reward_pledge_cents=10_000,
        funding_target_cents=1,
        with_tax_id=True,
    )
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backer": backer,
        "order": charged,
    }


def setup_succeeded_with_authorized_order(
    *, funding_target_cents: int = 5_000,
    reward_pledge_cents: int = 10_000,
    deadline_hours_from_now: float = 24.5,
    category: str = "TECH",
) -> Dict[str, Any]:
    """Difficulty Rule 4 / project_succeeded_charge_wave_cascade_depth3.

    Setup: LIVE ALL_OR_NOTHING project, one AUTHORIZED order whose
    order_total exceeds funding_target. Then advance clock past deadline
    in a separate call; this fixture stops at the AUTHORIZED state so the
    test can run its own clock advance and observe the cascade.

    Returns dict with initiator, project, reward, backer, order, deadline.
    """
    initiator, project, reward = setup_live_project(
        category=category,
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=funding_target_cents,
        reward_pledge_cents=reward_pledge_cents,
        reward_type="DIGITAL",
        deadline_hours_from_now=deadline_hours_from_now,
        with_tax_id=True,
    )
    backer = create_backer()
    order = place_order(project=project, reward=reward, backer=backer)
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backer": backer,
        "order": order,
    }


def setup_approved_refund_for_execute(
    *,
    category: str = "ART",
    reward_pledge_cents: int = 10_000,
    refund_amount_cents: int = 4_000,
) -> Dict[str, Any]:
    """Difficulty Rule 4 / refund_execute_cascade_depth3.

    Setup: SUCCEEDED Project (ART category → 700 BPS commission),
    CHARGED Order order_total=10000 (original_commission_cents=700),
    one DRAFT SettlementBatch B for the period, RefundRequest R with
    approved_amount_cents=4000.

    Returns dict including the APPROVED refund request and DRAFT batch.
    """
    initiator, project, reward, backer, charged = setup_charged_order(
        category=category,
        reward_pledge_cents=reward_pledge_cents,
        funding_target_cents=1,
        with_tax_id=True,
    )
    # DRAFT settlement batch covering the charge timestamp.
    # Period must straddle the order's charge timestamp. We don't know
    # whether the test runs against a wall-clock-based server or a
    # clock-advanced server, so set the period to span generously around
    # the current server clock instant.
    period_start = add_hours(current_clock_iso(), -24 * 365)
    period_end = add_hours(current_clock_iso(), 24)
    batch = create_draft_settlement_batch(
        project=project, period_start=period_start, period_end=period_end
    )
    refund = create_refund_request(
        order=charged, backer=backer,
        requested_amount_cents=refund_amount_cents,
        reason="DISPUTE",
    )
    refund = approve_refund(refund["id"])
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backer": backer,
        "order": charged,
        "batch": batch,
        "refund": refund,
    }


def setup_cancelled_project_with_order(
    *,
    funding_target_cents: int = 100_000,
    reward_pledge_cents: int = 5_000,
) -> Dict[str, Any]:
    """Difficulty Rule 5 / state_vs_business_temporal_on_order_modify.

    Setup: LIVE project with one AUTHORIZED order, then initiator cancels
    the project (order cascades to VOIDED). Returns dict containing the
    voided order and the initiator/backer/project for downstream PATCH.
    """
    initiator, project, reward, backer, order = setup_live_with_order(
        category="TECH",
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=funding_target_cents,
        reward_pledge_cents=reward_pledge_cents,
        reward_type="DIGITAL",
        deadline_hours_from_now=240.0,
        with_tax_id=True,
    )
    cancel_res = api_client.cancel_project(
        project["id"], make_initiator_headers(initiator["id"]),
        {"reason": "Test cancel"},
    )
    cancelled_project = get_success_data(cancel_res)
    voided = get_success_data(
        api_client.get_order(order["id"], TEST_USERS["platform_admin_headers"])
    )
    return {
        "initiator": initiator,
        "project": cancelled_project,
        "reward": reward,
        "backer": backer,
        "order": voided,
        "order_created_at": order["created_at"],
    }


def setup_pending_kyc_initiator_with_zero_rewards() -> Tuple[
    Dict[str, Any], Dict[str, Any]
]:
    """Difficulty Rule 5 / business_safety_vs_business_constraint_on_submit.

    Setup: Initiator with kyc_status=PENDING (no verify_kyc call), Project
    in DRAFT with all fields set, zero Rewards. Returns (initiator, project).
    """
    initiator = create_initiator(with_tax_id=True)  # PENDING by default
    project = create_draft_project(
        initiator=initiator,
        deadline_hours_from_now=72.0,
    )
    return initiator, project


def setup_charged_order_with_initiator_tax_id(
    *,
    order_total_cents: int,
    category: str = "TECH",
) -> Dict[str, Any]:
    """Difficulty Rule 6 / tax_withholding_threshold_strictly_greater.

    Setup: an Initiator with tax_id present, SUCCEEDED project, one CHARGED
    order at the requested order_total_cents. Returns dict with initiator,
    project, reward, backer, order, deadline (used to construct period).
    """
    initiator, project, reward, backer, charged = setup_charged_order(
        category=category,
        reward_pledge_cents=order_total_cents,
        funding_target_cents=1,
        with_tax_id=True,
    )
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backer": backer,
        "order": charged,
    }


def setup_zero_orders_at_deadline_aon() -> Dict[str, Any]:
    """Difficulty Rule 6 / empty_set_no_authorized_orders_at_deadline.

    Setup: LIVE ALL_OR_NOTHING project with funding_target_cents=100,
    deadline 1h ahead, ZERO orders. Returns dict with initiator, project,
    reward (so the project could be submitted), and the deadline ISO
    instant.
    """
    initiator, project, reward = setup_live_project(
        category="TECH",
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=100,
        reward_pledge_cents=10_000,  # arbitrary; won't be ordered
        reward_type="DIGITAL",
        deadline_hours_from_now=24.5,
        with_tax_id=True,
    )
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
    }


def setup_project_in_content_review() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any]
]:
    """Difficulty Rule 7 / order_create_requires_project_live.

    Setup: Project in CONTENT_REVIEW (submitted but not yet approved by
    content reviewer). Returns (initiator, project_in_content_review, reward).
    """
    initiator = create_verified_initiator(with_tax_id=True)
    project = create_draft_project(
        initiator=initiator,
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=10_000,
        deadline_hours_from_now=240.0,
    )
    reward = create_reward(
        project=project, initiator=initiator,
        pledge_amount_cents=5_000, reward_type="DIGITAL",
    )
    submitted = submit_project(project=project, initiator=initiator)
    return initiator, submitted, reward


def setup_succeeded_with_pending_refund_and_draft_batch() -> Dict[str, Any]:
    """Difficulty Rule 7 / settlement_finalize_requires_no_open_refunds...

    Setup: SUCCEEDED Project; one CHARGED Order O; a PENDING_REVIEW
    RefundRequest R against O; a DRAFT SettlementBatch B for the period.
    Returns dict with all entities.
    """
    initiator, project, reward, backer, charged = setup_charged_order(
        category="TECH",
        reward_pledge_cents=10_000,
        funding_target_cents=1,
        with_tax_id=True,
    )
    # PENDING refund still needs an update so silence-window doesn't bite.
    publish_progress_update(project=project, initiator=initiator,
                            visibility="PUBLIC")
    # Period must straddle the order's charge timestamp. We don't know
    # whether the test runs against a wall-clock-based server or a
    # clock-advanced server, so set the period to span generously around
    # the current server clock instant.
    period_start = add_hours(current_clock_iso(), -24 * 365)
    period_end = add_hours(current_clock_iso(), 24)
    batch = create_draft_settlement_batch(
        project=project, period_start=period_start, period_end=period_end
    )
    pending_refund = create_refund_request(
        order=charged, backer=backer,
        requested_amount_cents=2_000,
        reason="DISPUTE",
    )
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backer": backer,
        "order": charged,
        "batch": batch,
        "pending_refund": pending_refund,
    }


def setup_order_at_window_boundary(
    *,
    deadline_hours_from_now: float = 240.0,
) -> Dict[str, Any]:
    """Difficulty Rule 8 / order_modification_window_half_open_interval.

    Setup: LIVE Project; one AUTHORIZED Order O; the order's created_at +
    72h is well before deadline so the locked_at is exactly created_at +
    72h. Returns dict with order_created_at and locked_at for the test to
    advance the clock to the boundary.
    """
    initiator, project, reward, backer, order = setup_live_with_order(
        category="TECH",
        reward_pledge_cents=5_000,
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=1_000_000,
        reward_type="DIGITAL",
        deadline_hours_from_now=deadline_hours_from_now,
        with_tax_id=True,
    )
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backer": backer,
        "order": order,
    }


def setup_two_charged_orders_at_period_boundary(
    *,
    order1_total_cents: int = 10_000,
    order2_total_cents: int = 10_000,
) -> Dict[str, Any]:
    """Difficulty Rule 8 / settlement_period_half_open_interval.

    Setup: SUCCEEDED Project; two CHARGED orders A and B charged at
    distinct times. The test will create two settlement batches with
    period bounds chosen to test half-open semantics.

    Returns dict with project, both orders (each with its charge time
    accessible via their updated_at), backers, etc.
    """
    initiator = create_verified_initiator(with_tax_id=True)
    project = create_draft_project(
        initiator=initiator, category="TECH",
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=1,
        deadline_hours_from_now=24.5,
    )
    reward = create_reward(
        project=project, initiator=initiator,
        pledge_amount_cents=order1_total_cents,
        reward_type="DIGITAL",
    )
    project = take_project_live(project=project, initiator=initiator)
    backer_a = create_backer()
    backer_b = create_backer()
    order_a = place_order(project=project, reward=reward, backer=backer_a)
    order_b = place_order(project=project, reward=reward, backer=backer_b)
    succeed_project_and_charge_all(
        project=project, orders=[order_a, order_b],
        payment_results=["SUCCESS", "SUCCESS"],
    )
    order_a_charged = get_success_data(api_client.get_order(
        order_a["id"], TEST_USERS["platform_admin_headers"]
    ))
    order_b_charged = get_success_data(api_client.get_order(
        order_b["id"], TEST_USERS["platform_admin_headers"]
    ))
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backers": [backer_a, backer_b],
        "orders": [order_a_charged, order_b_charged],
    }


def setup_inventory_limited_reward(
    *, inventory_limit: int = 1,
) -> Dict[str, Any]:
    """Difficulty Rule 9 / reward_inventory_conservation_on_order_cancel.

    Setup: LIVE Project with a reward whose inventory_limit is small, and
    a Backer who can place an order against it. Returns dict with all
    entities, reward at inventory_claimed=0.
    """
    initiator, project, reward = setup_live_project(
        category="TECH",
        funding_model="ALL_OR_NOTHING",
        funding_target_cents=10_000,
        reward_pledge_cents=5_000,
        reward_type="DIGITAL",
        reward_inventory_limit=inventory_limit,
        deadline_hours_from_now=240.0,
        with_tax_id=True,
    )
    backer = create_backer()
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backer": backer,
    }


def setup_charged_order_for_full_refund(
    *,
    category: str = "ART",
    order_total_cents: int = 10_000,
) -> Dict[str, Any]:
    """Difficulty Rule 9 / escrow_balance_conservation_on_full_refund.

    Setup: ART category SUCCEEDED Project with one CHARGED Order whose
    order_total equals order_total_cents. Returns full context.
    """
    initiator, project, reward, backer, charged = setup_charged_order(
        category=category,
        reward_pledge_cents=order_total_cents,
        funding_target_cents=1,
        with_tax_id=True,
    )
    return {
        "initiator": initiator,
        "project": project,
        "reward": reward,
        "backer": backer,
        "order": charged,
    }


# ===========================================================================
# Convenience read helpers
# ===========================================================================
def list_audit_log(*, subject_type: Optional[str] = None,
                   subject_id: Optional[str] = None,
                   event_type: Optional[str] = None,
                   limit: int = 100,
                   offset: int = 0) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if subject_type is not None:
        params["subject_type"] = subject_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    if event_type is not None:
        params["event_type"] = event_type
    res = api_client.list_audit_log(
        TEST_USERS["platform_admin_headers"], params=params
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    # paginated envelope: framework returns the data list at top-level.
    return data if isinstance(data, list) else []


def list_escrow_ledger(project_id: str, *, limit: int = 100,
                       offset: int = 0) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    res = api_client.list_escrow_ledger(
        project_id, TEST_USERS["platform_admin_headers"], params=params
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return data if isinstance(data, list) else []


def get_project(project_id: str) -> Dict[str, Any]:
    res = api_client.get_project(
        project_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def get_order(order_id: str) -> Dict[str, Any]:
    res = api_client.get_order(
        order_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def get_refund(refund_id: str) -> Dict[str, Any]:
    res = api_client.get_refund_request(
        refund_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


def get_batch(project_id: str, batch_id: str) -> Dict[str, Any]:
    res = api_client.get_settlement_batch(
        project_id, batch_id, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(res)


__all__ = [
    # time
    "iso_z", "parse_iso", "add_seconds", "add_minutes", "add_hours",
    "add_days", "DEFAULT_NOW_ISO",
    # test drivers
    "advance_clock", "current_clock_iso",
    "emit_payment", "emit_banking", "emit_logistics",
    # tier 1
    "create_initiator", "verify_kyc", "create_verified_initiator",
    "create_backer",
    "create_draft_project", "create_reward", "create_add_on_item",
    # tier 2 - review
    "submit_project", "review_content", "review_legal", "review_financial",
    "take_project_live",
    # composite
    "setup_live_project", "place_order", "setup_live_with_order",
    # charge wave
    "drive_clock_past_deadline", "charge_order_success",
    "charge_order_failure_until_failed", "succeed_project_and_charge_all",
    # refund
    "create_refund_request", "approve_refund", "execute_refund",
    "reject_refund", "setup_charged_order",
    # settlement
    "create_draft_settlement_batch", "finalize_settlement_batch",
    "publish_progress_update",
    # difficulty design
    "setup_provisional_vs_final_three_orders",
    "setup_charged_order_with_total",
    "setup_three_charged_orders_for_commission",
    "setup_revision_loop_project",
    "setup_charged_order_for_partial_shipment",
    "setup_succeeded_with_authorized_order",
    "setup_approved_refund_for_execute",
    "setup_cancelled_project_with_order",
    "setup_pending_kyc_initiator_with_zero_rewards",
    "setup_charged_order_with_initiator_tax_id",
    "setup_zero_orders_at_deadline_aon",
    "setup_project_in_content_review",
    "setup_succeeded_with_pending_refund_and_draft_batch",
    "setup_order_at_window_boundary",
    "setup_two_charged_orders_at_period_boundary",
    "setup_inventory_limited_reward",
    "setup_charged_order_for_full_refund",
    # reads
    "list_audit_log", "list_escrow_ledger",
    "get_project", "get_order", "get_refund", "get_batch",
]
