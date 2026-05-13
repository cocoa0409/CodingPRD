"""Live Stream Schedule — composite setup helpers.

Every fixture here encapsulates one or more multi-step preambles needed to put
the system into a specific state described by the PRD (e.g., 'Streamer at SILVER
tier with one APPROVED application about to start in 72 hours').

Identity threading rule (PRD §2.1): Streamer is the only entity_backed role. Any
ownership-gated call inside a fixture MUST use ``make_streamer_headers(s["id"])``
with the actual streamer's id; never fall back to a placeholder constant.

Fixtures use ``get_success_data()`` (lenient) so a failed setup surfaces as a
clear 'Setup failed' rather than a confusing assertion error.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_streamer_payload,
    create_studio_payload,
    create_time_slot_payload,
    create_product_payload,
    update_product_payload,
    update_studio_payload,
    create_application_payload,
    associate_product_payload,
    approve_decision_payload,
    cancel_payload,
    create_violation_payload,
    file_appeal_payload,
    decide_appeal_payload,
    emit_event_payload,
    advance_clock_payload,
    iso,
)
from .test_users import (
    ADMIN_HEADERS,
    OPS_HEADERS,
    COMPLIANCE_HEADERS,
    make_streamer_headers,
)


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------

# A fixed baseline so tests are reproducible (well before any application date)
DEFAULT_BASE_TIME = datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)


def set_clock(to: datetime) -> None:
    """Advance the simulated clock to a specific instant (PRD §2.5)."""
    resp = api_client.advance_clock(advance_clock_payload(to), ADMIN_HEADERS)
    get_success_data(resp)


def get_clock() -> datetime:
    """Return the simulated clock as a datetime.

    PRD §4: GET /live-schedule/_clock/now is a "Test-only — read current
    simulated clock" endpoint. The PRD does not pin the exact response shape,
    so we accept several common variants.
    """
    resp = api_client.get_clock(ADMIN_HEADERS)
    data = get_success_data(resp)
    if isinstance(data, str):
        return _parse_iso(data)
    if isinstance(data, dict):
        for key in ("now", "current_time", "clock", "logical_clock", "time"):
            if key in data and isinstance(data[key], str):
                return _parse_iso(data[key])
    # As a last resort, surface a clear setup failure
    raise RuntimeError(f"Could not parse clock response: {data!r}")


def _parse_iso(s: str) -> datetime:
    # Tolerate trailing 'Z'
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Tier 1: simple entity creation
# ---------------------------------------------------------------------------


def create_streamer(**overrides) -> Dict[str, Any]:
    """Create a Streamer via PlatformAdmin. Default values pass real-name and
    health-cert checks unless overridden.
    """
    payload = create_streamer_payload(**overrides)
    return get_success_data(api_client.create_streamer(payload, ADMIN_HEADERS))


def create_studio(**overrides) -> Dict[str, Any]:
    payload = create_studio_payload(**overrides)
    return get_success_data(api_client.create_studio(payload, ADMIN_HEADERS))


def add_time_slot(studio_id: str, **overrides) -> Dict[str, Any]:
    payload = create_time_slot_payload(**overrides)
    return get_success_data(api_client.create_time_slot(studio_id, payload, ADMIN_HEADERS))


def create_product(**overrides) -> Dict[str, Any]:
    payload = create_product_payload(**overrides)
    return get_success_data(api_client.create_product(payload, ADMIN_HEADERS))


def get_product(product_id: str) -> Dict[str, Any]:
    """Re-read a product. PRD §4 lists only POST and PATCH on /products — no
    GET. Per PRD §3.3 all three PATCH inputs (status, available_stock, version)
    are optional, so an empty PATCH body is a valid no-op that returns the
    current entity.
    """
    resp = api_client.update_product(product_id, {}, ADMIN_HEADERS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: pre-wired studio with permissive time slots
# ---------------------------------------------------------------------------


def setup_open_studio(**overrides) -> Dict[str, Any]:
    """Create an OPEN studio with a generous AVAILABLE window covering the next
    year. Returns the studio.
    """
    studio = create_studio(**overrides)
    now = datetime.now(timezone.utc)
    # Anchor available window far in the past and far in the future
    add_time_slot(
        studio["id"],
        kind="AVAILABLE",
        starts_at=iso(now - timedelta(days=30)),
        ends_at=iso(now + timedelta(days=400)),
        weekday_mask=0,
    )
    return studio


def setup_studio_with_window(
    available_start: datetime,
    available_end: datetime,
    maintenance: Optional[Tuple[datetime, datetime]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create an OPEN studio whose AVAILABLE window is exactly [available_start,
    available_end). Optionally add a MAINTENANCE sub-window.
    """
    studio = create_studio(**overrides)
    add_time_slot(
        studio["id"],
        kind="AVAILABLE",
        starts_at=iso(available_start),
        ends_at=iso(available_end),
        weekday_mask=0,
    )
    if maintenance is not None:
        m_start, m_end = maintenance
        add_time_slot(
            studio["id"],
            kind="MAINTENANCE",
            starts_at=iso(m_start),
            ends_at=iso(m_end),
            weekday_mask=0,
        )
    return studio


def setup_active_streamer(
    professional_cert_categories: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create an ACTIVE, real-name-verified streamer whose health cert is far in
    the future (so qualifications pass).
    """
    if professional_cert_categories is None:
        professional_cert_categories = ["FOOD", "FASHION", "COSMETICS", "ELECTRONICS", "KIDS", "FINANCIAL"]
    overrides.setdefault("real_name_verified", True)
    return create_streamer(
        professional_cert_categories=professional_cert_categories,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Tier 3: full draft application
# ---------------------------------------------------------------------------


def setup_draft_application(
    streamer: Optional[Dict[str, Any]] = None,
    studio: Optional[Dict[str, Any]] = None,
    starts_at: Optional[datetime] = None,
    ends_at: Optional[datetime] = None,
    package_code: str = "STANDARD",
    declared_product_categories: Optional[List[str]] = None,
    **app_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create (streamer, studio with windows, DRAFT application) in one call.

    Returns (streamer, studio, application).
    """
    if declared_product_categories is None:
        declared_product_categories = ["FOOD"]
    if starts_at is None:
        starts_at = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)  # 20:00 UTC
    if ends_at is None:
        ends_at = starts_at + timedelta(hours=2)

    if streamer is None:
        streamer = setup_active_streamer()
    if studio is None:
        # Available window covers the application window with a generous margin
        studio = setup_studio_with_window(
            available_start=starts_at - timedelta(days=30),
            available_end=ends_at + timedelta(days=30),
        )

    payload = create_application_payload(
        streamer_id=streamer["id"],
        studio_id=studio["id"],
        starts_at=starts_at,
        ends_at=ends_at,
        declared_product_categories=declared_product_categories,
        package_code=package_code,
        **app_overrides,
    )
    headers = make_streamer_headers(streamer["id"])
    app = get_success_data(api_client.create_application(payload, headers))
    return streamer, studio, app


def attach_compatible_product(
    application: Dict[str, Any],
    streamer: Dict[str, Any],
    category: str = "FOOD",
    requires_professional_cert: bool = False,
    available_stock: int = 100,
    reserved_quantity: int = 1,
    **product_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Product matching the application's declared category and stock,
    then associate it. Returns (product, association).
    """
    product = create_product(
        category=category,
        requires_professional_cert=requires_professional_cert,
        available_stock=available_stock,
        **product_overrides,
    )
    headers = make_streamer_headers(streamer["id"])
    payload = associate_product_payload(product_id=product["id"], reserved_quantity=reserved_quantity)
    association = get_success_data(api_client.associate_product(application["id"], payload, headers))
    return product, association


# ---------------------------------------------------------------------------
# Tier 3: progress an application through the workflow
# ---------------------------------------------------------------------------


def submit_application(streamer: Dict[str, Any], application: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_streamer_headers(streamer["id"])
    return get_success_data(api_client.submit_application(application["id"], headers))


def ops_approve(application_id: str, decision: str = "APPROVE", reason: Optional[str] = None) -> Dict[str, Any]:
    payload = approve_decision_payload(decision=decision, reason=reason)
    return get_success_data(api_client.ops_approve(application_id, payload, OPS_HEADERS))


def compliance_approve(application_id: str, decision: str = "APPROVE", reason: Optional[str] = None,
                       version: Optional[int] = None) -> Dict[str, Any]:
    payload = approve_decision_payload(decision=decision, reason=reason, version=version)
    return get_success_data(api_client.compliance_approve(application_id, payload, COMPLIANCE_HEADERS))


def pay_deposit(application: Dict[str, Any], invoice: Dict[str, Any],
                occurred_at: Optional[datetime] = None) -> None:
    """PRD §3.6 — DEPOSIT_PAID payment event with amount_cents == deposit_due_cents."""
    if occurred_at is None:
        occurred_at = DEFAULT_BASE_TIME + timedelta(days=1)
    payload = emit_event_payload(
        source="PAYMENT",
        kind="DEPOSIT_PAID",
        occurred_at=occurred_at,
        application_id=application["id"],
        amount_cents=invoice["deposit_due_cents"],
    )
    get_success_data(api_client.emit_event(payload, ADMIN_HEADERS))


def fetch_invoice(application_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_invoice(application_id, ADMIN_HEADERS))


def fetch_settlement(application_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_settlement(application_id, ADMIN_HEADERS))


def fetch_application(application_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_application(application_id, ADMIN_HEADERS))


def fetch_streamer(streamer_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_streamer(streamer_id, ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Tier 3: full SCHEDULED application (everything wired up & deposit paid)
# ---------------------------------------------------------------------------


def setup_scheduled_application(
    streamer: Optional[Dict[str, Any]] = None,
    studio: Optional[Dict[str, Any]] = None,
    starts_at: Optional[datetime] = None,
    ends_at: Optional[datetime] = None,
    package_code: str = "STANDARD",
    pay_deposit_event: bool = True,
    base_clock: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Walk DRAFT -> OPS_PENDING -> COMPLIANCE_PENDING -> APPROVED -> SCHEDULED,
    and optionally inject DEPOSIT_PAID so the invoice is in DEPOSIT_PAID state.

    Returns a dict {streamer, studio, application, product, association, invoice}.
    """
    if base_clock is None:
        base_clock = DEFAULT_BASE_TIME
    set_clock(base_clock)

    if starts_at is None:
        starts_at = base_clock + timedelta(days=10, hours=11)  # 20:00 UTC (within peak)
    if ends_at is None:
        ends_at = starts_at + timedelta(hours=2)

    streamer, studio, app = setup_draft_application(
        streamer=streamer,
        studio=studio,
        starts_at=starts_at,
        ends_at=ends_at,
        package_code=package_code,
    )
    product, association = attach_compatible_product(app, streamer)

    app = submit_application(streamer, app)
    app = ops_approve(app["id"], decision="APPROVE")
    app = compliance_approve(app["id"], decision="APPROVE")

    invoice = fetch_invoice(app["id"])
    if pay_deposit_event:
        pay_deposit(app, invoice)
        invoice = fetch_invoice(app["id"])

    return {
        "streamer": streamer,
        "studio": studio,
        "application": app,
        "product": product,
        "association": association,
        "invoice": invoice,
    }


def go_live(streamer: Dict[str, Any], application: Dict[str, Any],
            clock_at: Optional[datetime] = None) -> Dict[str, Any]:
    """Move SCHEDULED -> LIVE. Caller should ensure clock >= starts_at."""
    if clock_at is None:
        clock_at = _parse_iso(application["starts_at"])
    set_clock(clock_at)
    headers = make_streamer_headers(streamer["id"])
    return get_success_data(api_client.start_live(application["id"], headers))


def end_live(streamer: Dict[str, Any], application: Dict[str, Any],
             clock_at: Optional[datetime] = None) -> Dict[str, Any]:
    """Move LIVE -> COMPLETED."""
    if clock_at is None:
        clock_at = _parse_iso(application["ends_at"])
    set_clock(clock_at)
    headers = make_streamer_headers(streamer["id"])
    return get_success_data(api_client.end_live(application["id"], headers))


# ---------------------------------------------------------------------------
# Tier 4: settlement-ready, return-window-closed, paid-out variants
# ---------------------------------------------------------------------------


def run_live_broadcast(
    package_code: str = "STANDARD",
    base_clock: Optional[datetime] = None,
    gmv_cents: int = 0,
    streamer_overrides: Optional[Dict[str, Any]] = None,
    studio_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Walk an application through a complete broadcast: SCHEDULED -> LIVE ->
    COMPLETED, optionally pushing a BROADCAST_GMV event before ending.

    Returns {streamer, studio, application, invoice, settlement}.
    """
    if base_clock is None:
        base_clock = DEFAULT_BASE_TIME

    streamer_overrides = streamer_overrides or {}
    studio_overrides = studio_overrides or {}
    streamer = setup_active_streamer(**streamer_overrides)
    # Wide AVAILABLE window
    starts_at = base_clock + timedelta(days=10, hours=11)
    ends_at = starts_at + timedelta(hours=2)
    studio = setup_studio_with_window(
        available_start=starts_at - timedelta(days=30),
        available_end=ends_at + timedelta(days=30),
        **studio_overrides,
    )

    bundle = setup_scheduled_application(
        streamer=streamer,
        studio=studio,
        starts_at=starts_at,
        ends_at=ends_at,
        package_code=package_code,
        base_clock=base_clock,
    )
    app = bundle["application"]

    # Go live at starts_at
    app = go_live(streamer, app, clock_at=starts_at)

    # Optionally emit BROADCAST_GMV during the broadcast
    if gmv_cents > 0:
        mid = starts_at + timedelta(minutes=30)
        payload = emit_event_payload(
            source="ECOMMERCE",
            kind="BROADCAST_GMV",
            occurred_at=mid,
            application_id=app["id"],
            amount_cents=gmv_cents,
        )
        get_success_data(api_client.emit_event(payload, ADMIN_HEADERS))

    # End the broadcast — arms settlement window
    app = end_live(streamer, app, clock_at=ends_at)

    invoice = fetch_invoice(app["id"])
    settlement = fetch_settlement(app["id"])
    return {
        "streamer": streamer,
        "studio": studio,
        "application": app,
        "invoice": invoice,
        "settlement": settlement,
    }


def close_return_window(application_ends_at: datetime) -> None:
    """Advance the clock past return_window_ends_at (= ends_at + 7 days) and run
    the periodic sweep, which moves any WINDOW_OPEN settlements to
    READY_FOR_PAYOUT or REVERSED.
    """
    set_clock(application_ends_at + timedelta(days=7, minutes=1))
    get_success_data(api_client.run_sweep(ADMIN_HEADERS))


def emit_return(application_id: str, amount_cents: int, occurred_at: datetime) -> None:
    payload = emit_event_payload(
        source="ECOMMERCE",
        kind="RETURN_REPORTED",
        occurred_at=occurred_at,
        application_id=application_id,
        amount_cents=amount_cents,
    )
    get_success_data(api_client.emit_event(payload, ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Tier 4: Streamer tier shaping
# ---------------------------------------------------------------------------


def boost_streamer_to_tier(
    streamer: Dict[str, Any],
    target_tier: str,
    base_clock: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Drive a streamer's lifetime_gmv_cents past the tier threshold by running
    enough completed broadcasts and paying out their settlements.

    Per PRD §3.1 thresholds:
        SILVER: >= 1,000,000 cents and violation_score <= 20
        GOLD:   >= 10,000,000 cents and violation_score <= 10
        PLATINUM: >= 50,000,000 cents and violation_score <= 5

    For each broadcast we inject a BROADCAST_GMV event of ``per_broadcast_gmv``
    cents; we then close the return window via sweep and pay out. Each payout
    adds effective_sales to lifetime_gmv_cents and re-triggers tier recompute.
    """
    if base_clock is None:
        base_clock = DEFAULT_BASE_TIME

    thresholds_cents = {
        "SILVER": 1_000_000,
        "GOLD": 10_000_000,
        "PLATINUM": 50_000_000,
    }
    if target_tier == "BRONZE":
        return fetch_streamer(streamer["id"])
    target = thresholds_cents[target_tier]
    per_broadcast_gmv = max(target, 1_000_000)

    # We'll do one broadcast that pushes lifetime_gmv past the threshold
    clock = base_clock
    while True:
        s = fetch_streamer(streamer["id"])
        if s["lifetime_gmv_cents"] >= target:
            return s
        # Build a fresh studio (back-to-back intervals on a new studio are easy).
        # Snap to 20:00 UTC so the 2-hour booking sits inside the peak window
        # (this matters only for cost projections; the fixture itself is
        # tier-only and doesn't assert specific fee values).
        base_day = clock + timedelta(days=2)
        starts = base_day.replace(hour=20, minute=0, second=0, microsecond=0)
        ends = starts + timedelta(hours=2)
        studio = setup_studio_with_window(
            available_start=starts - timedelta(days=10),
            available_end=ends + timedelta(days=30),
        )
        bundle = setup_scheduled_application(
            streamer=streamer,
            studio=studio,
            starts_at=starts,
            ends_at=ends,
            base_clock=clock,
        )
        app = bundle["application"]
        # Go LIVE, emit GMV, end LIVE
        app = go_live(streamer, app, clock_at=starts)
        gmv_payload = emit_event_payload(
            source="ECOMMERCE",
            kind="BROADCAST_GMV",
            occurred_at=starts + timedelta(minutes=15),
            application_id=app["id"],
            amount_cents=per_broadcast_gmv,
        )
        get_success_data(api_client.emit_event(gmv_payload, ADMIN_HEADERS))
        app = end_live(streamer, app, clock_at=ends)
        # Close the return window and pay out
        close_return_window(ends)
        settlement = fetch_settlement(app["id"])
        if settlement["status"] == "READY_FOR_PAYOUT":
            get_success_data(api_client.payout_settlement(settlement["id"], ADMIN_HEADERS))
        clock = ends + timedelta(days=8)
        set_clock(clock)


# ---------------------------------------------------------------------------
# Tier 4: Violation/Appeal setups
# ---------------------------------------------------------------------------


def create_violation(streamer_id: str, **overrides) -> Dict[str, Any]:
    """Reviewer (OPS by default) records a violation against a streamer."""
    payload = create_violation_payload(streamer_id=streamer_id, **overrides)
    return get_success_data(api_client.create_violation(payload, OPS_HEADERS))


def file_appeal(streamer: Dict[str, Any], violation_id: str, argument: str = "I appeal."):
    payload = file_appeal_payload(argument=argument)
    return get_success_data(
        api_client.file_appeal(violation_id, payload, make_streamer_headers(streamer["id"]))
    )


def decide_appeal(appeal_id: str, decision: str = "OVERTURN") -> Dict[str, Any]:
    payload = decide_appeal_payload(decision=decision)
    return get_success_data(api_client.decide_appeal(appeal_id, payload, COMPLIANCE_HEADERS))


def enforce_violation_via_sweep(violation: Dict[str, Any]) -> None:
    """Per PRD §3.10: advance clock past created_at + 7 days, then run sweep."""
    created = _parse_iso(violation["created_at"])
    set_clock(created + timedelta(days=7, minutes=1))
    get_success_data(api_client.run_sweep(ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Difficulty-design-specific fixtures
# ---------------------------------------------------------------------------


def setup_silver_streamer_for_pricing_divergence(
    base_clock: Optional[datetime] = None,
) -> Dict[str, Any]:
    """For dual_variant_calc/slot_fee_provisional_vs_final_on_application:

    Build a BRONZE streamer who *escalates* to SILVER between submit and
    compliance approve, so the provisional fee (uses BRONZE) and the final fee
    (uses pinned SILVER) diverge for identical base inputs.

    The escalation runs a separate completed-and-paid-out broadcast to push
    lifetime_gmv past 1,000,000 cents, then a fresh application is created and
    SUBMITTED while still BRONZE, the streamer is escalated by paying out the
    settlement, and finally compliance-approve pins SILVER.

    Returns a dict with:
      - streamer (now SILVER)
      - studio
      - application (review_status=APPROVED, pinned SILVER)
      - invoice
      - clock instants used
    """
    if base_clock is None:
        base_clock = DEFAULT_BASE_TIME
    set_clock(base_clock)

    streamer = setup_active_streamer()

    # Step 1: pre-load a "side" broadcast to bring lifetime_gmv close to 1,000,000
    # but NOT cross the threshold yet (so submit happens while still BRONZE).
    side_starts = base_clock + timedelta(days=1, hours=11)
    side_ends = side_starts + timedelta(hours=2)
    side_studio = setup_studio_with_window(
        available_start=side_starts - timedelta(days=10),
        available_end=side_ends + timedelta(days=30),
    )
    bundle = setup_scheduled_application(
        streamer=streamer,
        studio=side_studio,
        starts_at=side_starts,
        ends_at=side_ends,
        base_clock=base_clock,
    )
    side_app = bundle["application"]
    side_app = go_live(streamer, side_app, clock_at=side_starts)
    # 1,000,000 cents GMV — pushes the streamer exactly to the SILVER threshold
    # after payout
    gmv = emit_event_payload(
        source="ECOMMERCE", kind="BROADCAST_GMV",
        occurred_at=side_starts + timedelta(minutes=15),
        application_id=side_app["id"], amount_cents=1_000_000,
    )
    get_success_data(api_client.emit_event(gmv, ADMIN_HEADERS))
    side_app = end_live(streamer, side_app, clock_at=side_ends)

    # Step 2: create the target application while streamer is still BRONZE
    set_clock(side_ends + timedelta(hours=1))
    target_starts = base_clock + timedelta(days=17, hours=11)  # 20:00 UTC
    target_ends = target_starts + timedelta(hours=2)
    target_studio = setup_studio_with_window(
        available_start=target_starts - timedelta(days=10),
        available_end=target_ends + timedelta(days=30),
        slot_tier="A",
        base_hour_price_cents=10_000,
    )
    _, _, target_app = setup_draft_application(
        streamer=streamer,
        studio=target_studio,
        starts_at=target_starts,
        ends_at=target_ends,
        package_code="STANDARD",
    )
    attach_compatible_product(target_app, streamer)
    target_app = submit_application(streamer, target_app)
    # provisional_fee_cents was just computed under BRONZE

    # Step 3: ops-approve, then close the side broadcast's return window and pay
    # out — this escalates streamer.tier to SILVER
    target_app = ops_approve(target_app["id"], decision="APPROVE")
    close_return_window(side_ends)
    side_settlement = fetch_settlement(side_app["id"])
    if side_settlement["status"] == "READY_FOR_PAYOUT":
        get_success_data(api_client.payout_settlement(side_settlement["id"], ADMIN_HEADERS))

    # Step 4: compliance-approve — pins SILVER tier and computes final fee
    set_clock(side_ends + timedelta(days=8))
    target_app = compliance_approve(target_app["id"], decision="APPROVE")
    invoice = fetch_invoice(target_app["id"])
    streamer = fetch_streamer(streamer["id"])

    return {
        "streamer": streamer,
        "studio": target_studio,
        "application": target_app,
        "invoice": invoice,
        "side_application": side_app,
        "starts_at": target_starts,
        "ends_at": target_ends,
    }


def setup_gold_streamer_for_commission(
    base_clock: Optional[datetime] = None,
) -> Dict[str, Any]:
    """For dual_variant_calc/commission_provisional_vs_final_on_settlement and
    combinatorial_formula/commission_circular_dependency_mode_c.

    Build a streamer whose lifetime_gmv_cents is >= 10,000,000 so the pinned
    tier is GOLD; then start a fresh broadcast that we will end and emit events
    against.

    Returns {streamer (GOLD), studio, application (SCHEDULED, deposit_paid)}.
    """
    if base_clock is None:
        base_clock = DEFAULT_BASE_TIME
    set_clock(base_clock)
    streamer = setup_active_streamer()
    streamer = boost_streamer_to_tier(streamer, "GOLD", base_clock=base_clock)
    assert streamer["tier"] == "GOLD", f"Setup failed: streamer is {streamer['tier']}, not GOLD"

    # Now create a fresh, future broadcast — clock has moved forward inside boost
    clock = get_clock()
    base_day = clock + timedelta(days=2)
    # Snap to 20:00 UTC so the booking falls inside the peak window
    starts = base_day.replace(hour=20, minute=0, second=0, microsecond=0)
    ends = starts + timedelta(hours=2)
    studio = setup_studio_with_window(
        available_start=starts - timedelta(days=10),
        available_end=ends + timedelta(days=30),
        slot_tier="A",
        base_hour_price_cents=10_000,
    )
    bundle = setup_scheduled_application(
        streamer=streamer,
        studio=studio,
        starts_at=starts,
        ends_at=ends,
        package_code="STANDARD",
        base_clock=clock,
    )
    return {
        "streamer": streamer,
        "studio": studio,
        "application": bundle["application"],
        "invoice": bundle["invoice"],
        "starts_at": starts,
        "ends_at": ends,
    }


def setup_silver_streamer_for_combo_discount(
    base_clock: Optional[datetime] = None,
) -> Dict[str, Any]:
    """For combinatorial_formula/slot_fee_pinned_rounding_order_mode_b.

    Build a SILVER streamer pinned at compliance-approve, with a 2-hour booking
    20:00–22:00 UTC (entirely within the peak window), package COMBO_HALF_DAY
    (8% discount), studio base_hour_price_cents=10_000.

    Returns the bundle dict; application is fully APPROVED with pinned SILVER.
    """
    if base_clock is None:
        base_clock = DEFAULT_BASE_TIME
    set_clock(base_clock)

    streamer = setup_active_streamer()
    streamer = boost_streamer_to_tier(streamer, "SILVER", base_clock=base_clock)
    assert streamer["tier"] == "SILVER", f"Setup failed: streamer is {streamer['tier']}"

    clock = get_clock()
    # Snap starts to a future date at 20:00 UTC (squarely inside peak window
    # 19:00–23:00 UTC so the 2-hour booking is fully peak)
    base_day = clock + timedelta(days=2)
    starts = base_day.replace(hour=20, minute=0, second=0, microsecond=0)
    ends = starts + timedelta(hours=2)
    studio = setup_studio_with_window(
        available_start=starts - timedelta(days=10),
        available_end=ends + timedelta(days=30),
        slot_tier="A",
        base_hour_price_cents=10_000,
    )

    _, _, app = setup_draft_application(
        streamer=streamer,
        studio=studio,
        starts_at=starts,
        ends_at=ends,
        package_code="COMBO_HALF_DAY",
    )
    attach_compatible_product(app, streamer)
    app = submit_application(streamer, app)
    app = ops_approve(app["id"], decision="APPROVE")
    app = compliance_approve(app["id"], decision="APPROVE")
    invoice = fetch_invoice(app["id"])
    return {
        "streamer": streamer,
        "studio": studio,
        "application": app,
        "invoice": invoice,
        "starts_at": starts,
        "ends_at": ends,
    }


def setup_application_with_reservations(
    initial_available_stock: int = 100,
    reserved_quantity: int = 25,
) -> Dict[str, Any]:
    """For compensating_invariant/product_stock_conserved_on_release.

    Create a fresh streamer, studio, application in DRAFT, and one
    ProductAssociation reserving ``reserved_quantity`` from a fresh Product with
    ``initial_available_stock``.

    Returns {streamer, studio, application, product (post-reservation),
              association, product_initial}.
    """
    set_clock(DEFAULT_BASE_TIME)
    streamer, studio, app = setup_draft_application()
    product_initial = create_product(available_stock=initial_available_stock)
    headers = make_streamer_headers(streamer["id"])
    payload = associate_product_payload(product_id=product_initial["id"], reserved_quantity=reserved_quantity)
    association = get_success_data(api_client.associate_product(app["id"], payload, headers))
    # Refresh product to get post-reservation stock figures
    product_after = get_product(product_initial["id"])
    return {
        "streamer": streamer,
        "studio": studio,
        "application": app,
        "product_initial": product_initial,
        "product": product_after,
        "association": association,
    }
