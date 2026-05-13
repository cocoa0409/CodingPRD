"""Composite setup helpers for the Domestic Service Dispatch API.

Most interesting test claims need the system in a state that takes 5-15 API
calls to reach (a verified active personnel with an approved cert, a customer
profile, an order through to IN_PROGRESS, a ledger entry past its 72h hold,
etc.). This module encapsulates those preambles so each test focuses on one
claim.

Identity threading (mandatory per PRD §2.1):
- entity_backed roles (Customer, ServicePersonnel) MUST pass the actual
  entity id into make_<role>_headers; the shared TEST_USERS constant is for
  ownership-irrelevant probes only.
- opaque roles (PlatformOperator, system) use the shared constant.

Fixtures use get_success_data (lenient validator) so a setup-call failure
surfaces as a clear "Setup failed: HTTP <code>" rather than an unrelated
assertion mismatch.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    abnormal_event_payload,
    advance_clock_payload,
    checkin_payload,
    claim_evidence_payload,
    create_certification_payload,
    create_customer_payload,
    create_order_payload,
    create_personnel_payload,
    create_recurring_order_payload,
    create_service_item_payload,
    insurance_decision_payload,
    iso_in,
    logical_clock,
    patch_execution_payload,
    rating_payload,
    settlement_sweep_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_personnel_headers,
)

# ─────────────────────────────────────────────────────────────
# Convenience header aliases — opaque roles, safe as shared constants.
# ─────────────────────────────────────────────────────────────

OPERATOR_HEADERS = TEST_USERS["operator_headers"]
OPERATOR_HEADERS_ALT = TEST_USERS["operator_headers_alt"]
SYSTEM_HEADERS = TEST_USERS["system_headers"]


# =============================================================================
# Tier 0 — time helpers and atomic single-entity creation
# =============================================================================


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: datetime) -> str:
    s = ts.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return s.replace("+00:00", "Z")


def advance_clock(seconds: int) -> Dict[str, Any]:
    """PRD §3.11: shift the logical clock forward by N seconds (system role).

    Also tracks the cumulative offset in test_helpers so `iso_in` produces
    timestamps relative to the server's current_time rather than wall time."""
    res = api_client.advance_clock(
        advance_clock_payload(seconds=seconds), SYSTEM_HEADERS
    )
    data = get_success_data(res)
    logical_clock.add(seconds)
    return data


def run_recert_sweep() -> Dict[str, Any]:
    """PRD §3.2: run the recertification sweep."""
    res = api_client.run_recertification_sweep(OPERATOR_HEADERS)
    return get_success_data(res)


def run_settlement_sweep(cycle_id: str) -> Dict[str, Any]:
    """PRD §3.10: run the settlement sweep for a cycle."""
    res = api_client.run_settlement_sweep(
        settlement_sweep_payload(cycle_id=cycle_id), OPERATOR_HEADERS
    )
    return get_success_data(res)


def create_personnel(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: create a ServicePersonnel profile (PENDING_VERIFICATION)."""
    res = api_client.create_personnel(
        create_personnel_payload(**overrides), OPERATOR_HEADERS
    )
    return get_success_data(res)


def verify_personnel_identity(personnel_id: str) -> Dict[str, Any]:
    res = api_client.verify_personnel_identity(personnel_id, OPERATOR_HEADERS)
    return get_success_data(res)


def create_certification(personnel_id: str, **overrides: Any) -> Dict[str, Any]:
    res = api_client.create_certification(
        create_certification_payload(personnel_id, **overrides), OPERATOR_HEADERS
    )
    return get_success_data(res)


def approve_certification(cert_id: str) -> Dict[str, Any]:
    res = api_client.approve_certification(cert_id, OPERATOR_HEADERS)
    return get_success_data(res)


def activate_personnel(personnel_id: str) -> Dict[str, Any]:
    res = api_client.activate_personnel(personnel_id, OPERATOR_HEADERS)
    return get_success_data(res)


def create_service_item(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: create an active ServiceItem."""
    res = api_client.create_service_item(
        create_service_item_payload(**overrides), OPERATOR_HEADERS
    )
    return get_success_data(res)


def create_customer(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: create a Customer profile."""
    res = api_client.create_customer(
        create_customer_payload(**overrides), OPERATOR_HEADERS
    )
    return get_success_data(res)


def get_personnel(personnel_id: str) -> Dict[str, Any]:
    res = api_client.get_personnel(personnel_id, OPERATOR_HEADERS)
    return get_success_data(res)


def get_order(order_id: str) -> Dict[str, Any]:
    res = api_client.get_order(order_id, OPERATOR_HEADERS)
    return get_success_data(res)


def get_customer(customer_id: str) -> Dict[str, Any]:
    res = api_client.get_customer(customer_id, OPERATOR_HEADERS)
    return get_success_data(res)


def get_claim(claim_id: str) -> Dict[str, Any]:
    res = api_client.get_claim(claim_id, OPERATOR_HEADERS)
    return get_success_data(res)


# =============================================================================
# Tier 1 — state progression for ServicePersonnel
# =============================================================================


def create_active_personnel(
    *,
    skill_tag: str = "CLEANING",
    cert_expires_in_days: int = 365,
    isolate_dispatch: bool = True,
    **personnel_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """PRD §3.1-§3.2: create personnel → verify identity → create+approve
    one SkillCertification → activate. Returns (personnel, certification).

    The returned personnel is observed AFTER activation, so its status is ACTIVE
    and skill_tags includes the approved skill_tag.

    isolate_dispatch=True (default) suspends every previously-active personnel
    that shares the same skill_tag so dispatch reliably lands on the new
    personnel (PRD §3.5 ranks higher-tier and higher-rating personnel ahead of
    BRONZE freshly-created personnel; leftover rivals from earlier tests would
    otherwise absorb the dispatch).
    """
    if isolate_dispatch:
        suspend_rivals_for_skill(skill_tag)
    p = create_personnel(**personnel_overrides)
    verify_personnel_identity(p["id"])
    cert = create_certification(
        p["id"],
        skill_tag=skill_tag,
        expires_at=iso_in(days=cert_expires_in_days),
    )
    cert = approve_certification(cert["id"])
    p = activate_personnel(p["id"])
    return p, cert


def create_pending_personnel(
    **personnel_overrides: Any,
) -> Dict[str, Any]:
    """Just the raw personnel in PENDING_VERIFICATION (no identity, no cert)."""
    return create_personnel(**personnel_overrides)


import uuid as _uuid


def _unique_iso_language() -> str:
    """Generate a language code unique to this call so customers can use it as
    a `pref_language` filter (PRD §3.5 dispatch eligibility) to isolate
    dispatch onto the test's freshly-created personnel. We use the full uuid
    hex so the 16^32 keyspace makes accidental collision negligible — short
    2-char markers caused intermittent rivals to share a language with a
    fresh personnel."""
    return _uuid.uuid4().hex


def _clear_active_assignments(personnel_id: str) -> None:
    """Best-effort clear of every DISPATCHED/ACCEPTED/IN_PROGRESS Order whose
    assigned_personnel_id is `personnel_id`, so the personnel can be suspended
    (PRD §3.1: suspend rejects with ERR_HAS_ACTIVE_ASSIGNMENTS when active
    assignments exist). DISPATCHED orders are rejected back to PENDING_DISPATCH
    via the personnel-driven reject endpoint; ACCEPTED/IN_PROGRESS orders are
    cancelled when the cancel window is still open."""
    list_res = api_client.list_orders(
        OPERATOR_HEADERS,
        params={"assigned_personnel_id": personnel_id, "limit": 200},
    )
    data = list_res.json().get("data", [])
    orders = data if isinstance(data, list) else data.get("entries", [])
    for o in orders:
        status = o.get("status")
        if status == "DISPATCHED":
            try:
                api_client.reject_order(
                    o["id"],
                    {"X-User-ID": personnel_id, "X-User-Role": "ServicePersonnel"},
                )
            except Exception:
                pass
        if status in {"DISPATCHED", "ACCEPTED"}:
            # Cancel via operator (no role guard against window when operator).
            try:
                api_client.cancel_order(o["id"], OPERATOR_HEADERS)
            except Exception:
                pass


def suspend_rivals_excluding(
    *, skill_tag: str, keep_personnel_ids: List[str]
) -> List[str]:
    """Suspend every ACTIVE personnel certified for `skill_tag` EXCEPT those
    whose id is in `keep_personnel_ids`. Returns the ids actually suspended.
    Uses `_clear_active_assignments` to clear ERR_HAS_ACTIVE_ASSIGNMENTS
    blockers when needed."""
    list_res = api_client.list_personnel(
        OPERATOR_HEADERS,
        params={"status": "ACTIVE", "skill_tag": skill_tag, "limit": 100},
    )
    list_body = list_res.json().get("data", [])
    rivals = list_body if isinstance(list_body, list) else list_body.get("entries", [])
    suspended: List[str] = []
    for r in rivals:
        if r["id"] in keep_personnel_ids:
            continue
        try:
            res = api_client.suspend_personnel(r["id"], OPERATOR_HEADERS)
            if 200 <= res.status_code < 300:
                suspended.append(r["id"])
                continue
            _clear_active_assignments(r["id"])
            res2 = api_client.suspend_personnel(r["id"], OPERATOR_HEADERS)
            if 200 <= res2.status_code < 300:
                suspended.append(r["id"])
        except Exception:
            pass
    return suspended


def suspend_rivals_for_skill(skill_tag: str = "CLEANING") -> List[str]:
    """Suspend every pre-existing ACTIVE personnel certified for `skill_tag` so
    dispatch reliably lands on freshly-created personnel. Returns the list of
    personnel ids that were actually suspended. Callers may reinstate them
    when they no longer need the isolation.

    Rivals whose suspend fails with ERR_HAS_ACTIVE_ASSIGNMENTS (PRD §3.1) have
    their lingering active orders cleared by `_clear_active_assignments` then
    the suspend is retried so isolation is reliable across test boundaries."""
    list_res = api_client.list_personnel(
        OPERATOR_HEADERS,
        params={"status": "ACTIVE", "skill_tag": skill_tag, "limit": 100},
    )
    list_body = list_res.json().get("data", [])
    rivals = list_body if isinstance(list_body, list) else list_body.get("entries", [])
    suspended: List[str] = []
    for r in rivals:
        try:
            res = api_client.suspend_personnel(r["id"], OPERATOR_HEADERS)
            if 200 <= res.status_code < 300:
                suspended.append(r["id"])
                continue
            # Fall through: probably ERR_HAS_ACTIVE_ASSIGNMENTS — clear and retry.
            _clear_active_assignments(r["id"])
            res2 = api_client.suspend_personnel(r["id"], OPERATOR_HEADERS)
            if 200 <= res2.status_code < 300:
                suspended.append(r["id"])
        except Exception:
            pass
    return suspended


# =============================================================================
# Tier 2 — entity hierarchy: customer + service item + active personnel
# =============================================================================


def setup_basic_scenario(
    *,
    skill_tag: str = "CLEANING",
    base_price_cents: int = 10000,
    customer_overrides: Optional[Dict[str, Any]] = None,
    service_item_overrides: Optional[Dict[str, Any]] = None,
    personnel_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One Customer + one ServiceItem + one ACTIVE personnel certified for the
    required skill. All geographically co-located. Returns dict with keys:
    customer, service_item, personnel, certification.

    This is the common ground for almost every Order-related test.

    Isolation: the dispatch selector (PRD §3.5) filters by the customer's
    `pref_language` — only personnel whose `languages` array contains that
    code are eligible. To keep `drive_order_to` and other downstream test
    logic deterministic, this fixture mints a unique language code per call,
    sets it on the customer's `pref_language`, and adds it to the freshly-
    built personnel's `languages` array. Leftover ACTIVE personnel from
    earlier tests (often promoted to GOLD/SILVER) lack the code and are
    excluded by the language filter, so the dispatch lands on the new
    personnel rather than the older, higher-tier rivals.
    """
    cust_overrides = dict(customer_overrides or {})
    pers_overrides = dict(personnel_overrides or {})
    # Mint a unique pref_language unless the caller already set one.
    if "pref_language" not in cust_overrides:
        marker = _unique_iso_language()
        cust_overrides["pref_language"] = marker
        # And add it to the personnel's languages array (don't lose any
        # caller-supplied entries).
        langs = list(pers_overrides.get("languages", ["zh", "en"]))
        if marker not in langs:
            langs.append(marker)
        pers_overrides["languages"] = langs
    customer = create_customer(**cust_overrides)
    service_item = create_service_item(
        required_skill_tag=skill_tag,
        base_price_cents=base_price_cents,
        **(service_item_overrides or {}),
    )
    personnel, cert = create_active_personnel(
        skill_tag=skill_tag,
        isolate_dispatch=False,
        **pers_overrides,
    )
    return {
        "customer": customer,
        "service_item": service_item,
        "personnel": personnel,
        "certification": cert,
    }


# =============================================================================
# Tier 3 — Full order lifecycle shortcuts
# =============================================================================


def create_draft_order(
    ctx: Dict[str, Any], **order_overrides: Any
) -> Dict[str, Any]:
    """PRD §3.4: create an Order (DRAFT) under the given basic scenario."""
    customer = ctx["customer"]
    item = ctx["service_item"]
    res = api_client.create_order(
        create_order_payload(
            customer_id=customer["id"],
            service_item_id=item["id"],
            **order_overrides,
        ),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def submit_order(ctx: Dict[str, Any], order_id: str) -> Dict[str, Any]:
    """PRD §3.4: DRAFT → PENDING_DISPATCH (customer-driven)."""
    customer = ctx["customer"]
    res = api_client.submit_order(order_id, make_customer_headers(customer["id"]))
    return get_success_data(res)


def submit_new_order(
    ctx: Dict[str, Any], **order_overrides: Any
) -> Dict[str, Any]:
    """PRD §3.4: create + submit. Returns the order in PENDING_DISPATCH."""
    order = create_draft_order(ctx, **order_overrides)
    return submit_order(ctx, order["id"])


def dispatch_order(ctx: Dict[str, Any], order_id: str) -> Dict[str, Any]:
    """PRD §3.5: PENDING_DISPATCH → DISPATCHED (operator-driven)."""
    res = api_client.dispatch_order(order_id, OPERATOR_HEADERS)
    return get_success_data(res)


def accept_order(
    order: Dict[str, Any]
) -> Dict[str, Any]:
    """PRD §3.5: DISPATCHED → ACCEPTED. Threads the assigned_personnel_id from
    the order dict into the headers — PRD §3.5 requires
    X-User-ID == Order.assigned_personnel_id."""
    assignee_id = order["assigned_personnel_id"]
    assert assignee_id, "Order has no assigned_personnel_id; cannot accept"
    res = api_client.accept_order(
        order["id"], make_personnel_headers(assignee_id)
    )
    return get_success_data(res)


def reject_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.5: DISPATCHED → PENDING_DISPATCH (personnel-driven)."""
    assignee_id = order["assigned_personnel_id"]
    assert assignee_id, "Order has no assigned_personnel_id; cannot reject"
    res = api_client.reject_order(
        order["id"], make_personnel_headers(assignee_id)
    )
    return get_success_data(res)


def checkin_order(
    order: Dict[str, Any],
    *,
    customer_lat: float,
    customer_lng: float,
    face_passed: bool = True,
) -> Dict[str, Any]:
    """PRD §3.6: ACCEPTED → IN_PROGRESS. Coordinates default to the customer
    location so haversine ≤ 0.2 km. The caller is responsible for ensuring
    current_time >= scheduled_start_at - 15 minutes (advance_clock if needed)."""
    assignee_id = order["assigned_personnel_id"]
    res = api_client.checkin_order(
        order["id"],
        checkin_payload(
            checkin_lat=customer_lat,
            checkin_lng=customer_lng,
            checkin_face_passed=face_passed,
        ),
        make_personnel_headers(assignee_id),
    )
    return get_success_data(res)


def patch_execution(
    order_id: str,
    assignee_id: str,
    *,
    checklist: Optional[List[bool]] = None,
    before_url: Optional[str] = None,
    after_url: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.6: patch the ServiceExecution row for an order."""
    payload = patch_execution_payload(
        procedure_checklist=checklist,
        before_photo_url=before_url,
        after_photo_url=after_url,
    )
    res = api_client.patch_execution(
        order_id, payload, make_personnel_headers(assignee_id)
    )
    return get_success_data(res)


def complete_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.6: IN_PROGRESS → COMPLETED. Caller must have filled checklist+photos."""
    assignee_id = order["assigned_personnel_id"]
    res = api_client.complete_order(
        order["id"], make_personnel_headers(assignee_id)
    )
    return get_success_data(res)


def customer_accept(ctx: Dict[str, Any], order_id: str) -> Dict[str, Any]:
    """PRD §3.6: COMPLETED → ACCEPTED_BY_CUSTOMER (customer-driven)."""
    customer = ctx["customer"]
    res = api_client.customer_accept_order(
        order_id, make_customer_headers(customer["id"])
    )
    return get_success_data(res)


# =============================================================================
# Tier 3.5 — composite shortcuts to reach each lifecycle stage
# =============================================================================


def drive_order_to(
    ctx: Dict[str, Any],
    target_state: str,
    *,
    scheduled_start_at: Optional[str] = None,
    duration_hours: float = 2.0,
) -> Dict[str, Any]:
    """Drive a fresh Order through to the named lifecycle state.

    PRD §3.4-§3.6 transitions are wired step by step. Caller can specify
    scheduled_start_at; default puts it 48h in the future (safely past every
    submit/modify/cancel window). For check-in we advance the logical clock so
    that current_time >= scheduled_start_at - 15 minutes, satisfying PRD §3.6.

    Valid `target_state` values: DRAFT, PENDING_DISPATCH, DISPATCHED, ACCEPTED,
    IN_PROGRESS, COMPLETED, ACCEPTED_BY_CUSTOMER.
    """
    states = [
        "DRAFT",
        "PENDING_DISPATCH",
        "DISPATCHED",
        "ACCEPTED",
        "IN_PROGRESS",
        "COMPLETED",
        "ACCEPTED_BY_CUSTOMER",
    ]
    assert target_state in states, f"Unknown target_state: {target_state}"
    stop_idx = states.index(target_state)

    overrides: Dict[str, Any] = {"duration_hours": duration_hours}
    if scheduled_start_at is not None:
        overrides["scheduled_start_at"] = scheduled_start_at
    order = create_draft_order(ctx, **overrides)
    if stop_idx == 0:
        return order

    order = submit_order(ctx, order["id"])
    if stop_idx == 1:
        return order

    order = dispatch_order(ctx, order["id"])
    if stop_idx == 2:
        return order

    order = accept_order(order)
    if stop_idx == 3:
        return order

    # PRD §3.6: check-in requires current_time >= scheduled_start_at - 15min.
    # Compute seconds to advance using the *logical* clock (wall + offset);
    # using wall clock alone would advance the server too far because the
    # offset is already baked into scheduled_start_at via iso_in().
    sched = datetime.fromisoformat(
        order["scheduled_start_at"].replace("Z", "+00:00")
    )
    # Server's current logical time = wall + cumulative offset already applied.
    from .factories import logical_clock as _lc
    logical_now = datetime.now(timezone.utc) + timedelta(
        seconds=_lc.offset_seconds
    )
    # Target moment: 14 minutes before scheduled_start_at (still inside the
    # inclusive 15-minute early window).
    target_moment = sched - timedelta(minutes=14)
    delta_seconds = max(0, int((target_moment - logical_now).total_seconds()))
    if delta_seconds > 0:
        advance_clock(delta_seconds)
    customer = ctx["customer"]
    order = checkin_order(
        order,
        customer_lat=customer["address_lat"],
        customer_lng=customer["address_lng"],
    )
    if stop_idx == 4:
        return order

    # Fill checklist with all True and both photos so COMPLETED can fire.
    patch_execution(
        order["id"],
        order["assigned_personnel_id"],
        checklist=[True, True, True],
        before_url="https://photos.example.com/before-1",
        after_url="https://photos.example.com/after-1",
    )
    order = complete_order(order)
    if stop_idx == 5:
        return order

    order = customer_accept(ctx, order["id"])
    return order


def setup_order_in_state(
    target_state: str, **scenario_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Convenience: build a scenario AND walk an order to `target_state`.

    Returns (ctx, order) where ctx has keys: customer, service_item, personnel,
    certification.
    """
    ctx = setup_basic_scenario(**scenario_overrides)
    order = drive_order_to(ctx, target_state)
    return ctx, order


# =============================================================================
# Tier 4 — Accumulation / threshold targeting (rating, tier boundaries)
# =============================================================================


def setup_personnel_with_rating_history(
    *,
    target_count: int,
    target_score: float,
    skill_tag: str = "CLEANING",
    isolate_via_suspend_ids: Optional[List[str]] = None,
    pref_language: Optional[str] = None,
    extra_languages: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive enough rated orders for `personnel.rating_count == target_count`
    and `personnel.rating_score == target_score` (4 dp).

    Strategy: each contributing rating posts the same composite_score; the
    helper looks up integer (quality, punctuality, attitude) for the target
    in `_scores_for_composite`.

    Isolation guarantee: the dispatch selector (PRD §3.5) picks the
    highest-tier eligible personnel. If callers have already built other
    rated personnel (with higher tiers) in the same test, those personnel
    must be excluded from the pool during this build or the rating orders
    will be routed elsewhere. Callers pass `isolate_via_suspend_ids` to have
    those personnel suspended before driving orders here and reinstated
    afterwards.

    Args:
        target_count: number of completed-and-rated orders.
        target_score: per-rating composite_score (4 dp).
        isolate_via_suspend_ids: ids of other personnel to temporarily
            suspend so that the dispatch selector cannot route this
            helper's orders to them. They are reinstated before this
            helper returns.

    Returns (personnel, certification).
    """
    q, pu, at = _scores_for_composite(target_score)
    # Stagger small enough that cumulative clock-advance across the iterations
    # stays bounded (14h × N), but large enough to clear the 12-hour modify
    # window plus the 1-hour lead-time floor on submit (PRD §3.4).
    base_offset_hours = 14
    per_order_step_hours = 14

    # Isolate dispatch onto `p` by minting (or accepting) a pref_language marker.
    # Each customer in the loop is created with this language; `p` is the only
    # ACTIVE personnel that speaks it. PRD §3.5 dispatch filter ensures only
    # personnel whose `languages` contains the customer's `pref_language`
    # remain eligible. This is more reliable than suspending rivals — suspend
    # is blocked by ERR_HAS_ACTIVE_ASSIGNMENTS when rivals retain in-flight
    # orders from earlier tests. Callers building multiple co-eligible
    # personnel can share a marker by passing `pref_language`.
    marker = pref_language or _unique_iso_language()
    langs = ["zh", "en", marker]
    for x in extra_languages or []:
        if x not in langs:
            langs.append(x)
    p, cert = create_active_personnel(
        skill_tag=skill_tag,
        isolate_dispatch=False,
        languages=langs,
    )
    for idx in range(target_count):
        ctx = {
            "customer": create_customer(pref_language=marker),
            "service_item": create_service_item(required_skill_tag=skill_tag),
            "personnel": p,
            "certification": cert,
        }
        sched = iso_in(hours=base_offset_hours + idx * per_order_step_hours)
        order = drive_order_to(
            ctx, "ACCEPTED_BY_CUSTOMER", scheduled_start_at=sched
        )
        rate_completed_order(ctx, order, q, pu, at)
    p = get_personnel(p["id"])
    return p, cert


def _scores_for_composite(composite: float) -> Tuple[int, int, int]:
    """Pick integer (quality, punctuality, attitude) such that
    0.5*q + 0.3*pu + 0.2*at == composite.

    Supports the specific composites used in difficulty-design recipes:
        5.0  → (5, 5, 5)
        4.5  → (5, 4, 4)
        4.3  → (5, 3, 5)   actually 0.5*5+0.3*3+0.2*5 = 4.4 — see below
        3.6  → (5, 3, 1)
    For 4.5 we use (5,4,4): 2.5 + 1.2 + 0.8 = 4.5 ✓
    For 4.0 we use (5,3,3): 2.5 + 0.9 + 0.6 = 4.0 ✓
    For 4.8 we use (5,5,4): 2.5 + 1.5 + 0.8 = 4.8 ✓
    For 5.0 we use (5,5,5): 2.5 + 1.5 + 1.0 = 5.0 ✓
    For 3.6 we use (5,3,1): 2.5 + 0.9 + 0.2 = 3.6 ✓
    """
    table = {
        5.0: (5, 5, 5),
        4.8: (5, 5, 4),
        4.5: (5, 4, 4),
        4.0: (5, 3, 3),
        3.6: (5, 3, 1),
        3.0: (3, 3, 3),
    }
    if composite in table:
        return table[composite]
    raise NotImplementedError(
        f"_scores_for_composite not configured for composite={composite}"
    )


def rate_completed_order(
    ctx: Dict[str, Any],
    order: Dict[str, Any],
    quality: int,
    punctuality: int,
    attitude: int,
) -> Dict[str, Any]:
    """PRD §3.9: submit a rating after Order is ACCEPTED_BY_CUSTOMER."""
    customer = ctx["customer"]
    res = api_client.rate_order(
        order["id"],
        rating_payload(
            quality_score=quality,
            punctuality_score=punctuality,
            attitude_score=attitude,
            text_review="ok",
            anonymous=False,
        ),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


# =============================================================================
# Tier 5 — Settlement / claims fixtures
# =============================================================================


def get_settlement_entries(
    personnel_id: str, cycle_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List a personnel's SettlementLedgerEntry rows; optionally filter cycle."""
    params: Dict[str, Any] = {"limit": 100}
    if cycle_id is not None:
        params["cycle_id"] = cycle_id
    res = api_client.list_personnel_settlement(
        personnel_id, OPERATOR_HEADERS, params=params
    )
    data = get_success_data(res)
    # data may be the array itself (response_type=array → data is a list).
    return data if isinstance(data, list) else data.get("entries", [])


def post_evidence(claim_id: str, n: int = 2) -> None:
    """Attach `n` evidence items to a claim (PRD §3.7)."""
    for i in range(n):
        res = api_client.attach_claim_evidence(
            claim_id,
            claim_evidence_payload(
                evidence_url=f"https://evidence.example.com/img-{i}",
                description=f"evidence #{i}",
            ),
            OPERATOR_HEADERS,
        )
        get_success_data(res)


def file_a_claim(
    claim_id: str, *, decision: str, amount_cents: int
) -> Dict[str, Any]:
    """PRD §3.7: request-evidence → attach 2 evidence → file → webhook decision.
    Returns the claim after the insurer decision is posted."""
    res = api_client.request_claim_evidence(claim_id, OPERATOR_HEADERS)
    get_success_data(res)
    post_evidence(claim_id, 2)
    res = api_client.file_claim(claim_id, OPERATOR_HEADERS)
    get_success_data(res)
    res = api_client.emit_insurance_decision(
        insurance_decision_payload(
            claim_id=claim_id,
            decision=decision,
            amount_cents=amount_cents,
        ),
        SYSTEM_HEADERS,
    )
    return get_success_data(res)


def report_abnormal(
    order_id: str,
    *,
    category: str,
    description: str = "Test report",
    reporter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.7: file an AbnormalEvent against an order."""
    res = api_client.report_abnormal_event(
        order_id,
        abnormal_event_payload(category=category, description=description),
        reporter_headers if reporter_headers is not None else OPERATOR_HEADERS,
    )
    return get_success_data(res)


# =============================================================================
# Tier 6 — Specialized fixtures for difficulty-design recipes
# =============================================================================


def setup_three_eligible_personnel_for_dispatch(
    *,
    skill_tag: str = "CLEANING",
    customer_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a customer + service item + three active personnel all eligible.

    The three personnel differ in (tier, rating_score, id) so the dispatch
    selector's ranking can be observed deterministically. The caller drives the
    tiers themselves; this helper only creates active+certified+co-located
    personnel without ratings (they all start at BRONZE because rating_count=0).

    Returns dict with keys: customer, service_item, p1, p2, p3.
    """
    customer = create_customer(**(customer_overrides or {}))
    item = create_service_item(required_skill_tag=skill_tag)
    # Only the first call isolates by suspending pre-existing rivals; the
    # remaining two personnel must coexist with p1 to populate the dispatch
    # eligibility pool.
    p1, _ = create_active_personnel(
        skill_tag=skill_tag, full_name="P1 (tag-a)"
    )
    p2, _ = create_active_personnel(
        skill_tag=skill_tag, full_name="P2 (tag-b)",
        isolate_dispatch=False,
    )
    p3, _ = create_active_personnel(
        skill_tag=skill_tag, full_name="P3 (tag-c)",
        isolate_dispatch=False,
    )
    return {
        "customer": customer,
        "service_item": item,
        "p1": p1,
        "p2": p2,
        "p3": p3,
    }


def setup_personnel_with_settled_commission_only(
    *,
    target_amounts_cents: List[int],
    cycle_id: str = "TEST-CYCLE-A",
) -> Dict[str, Any]:
    """Build personnel whose ledger contains the exact COMMISSION amounts
    requested, all released (withheld_until in the past), so a settlement
    sweep on this personnel + cycle_id processes exactly those entries.

    Strategy: each iteration drives a fresh order all the way through to
    COMPLETED. The check-in step in drive_order_to advances the server clock
    forward to satisfy `current_time >= scheduled_start_at - 15min` (PRD §3.6);
    so for subsequent orders we explicitly pass `scheduled_start_at` further
    into the future to keep submission's `>= current_time + 1 hour` (PRD §3.4)
    satisfied. After all orders are COMPLETED the clock is advanced another
    72 hours so every COMMISSION's withheld_until is in the past (PRD §3.10).

    Returns dict: personnel, certification, customer, orders, cycle_id.
    """
    # Provisional = round_half_up(gross * 0.70). For the Rule-2 mode-b recipe
    # (3333, 3334, 3333) we reverse-engineer:
    #   3333 = round_half_up(g * 0.70)  →  g=4761  (0.70*4761 = 3332.7 → 3333)
    #   3334 = round_half_up(g * 0.70)  →  g=4763  (0.70*4763 = 3334.1 → 3334)
    grosses_for_amount = {
        3333: 4761,
        3334: 4763,
    }

    # Isolate dispatch onto p via a unique pref_language; see
    # `setup_personnel_with_rating_history` for the rationale (PRD §3.5
    # eligibility uses customer.pref_language ∩ personnel.languages, which is
    # robust across leftover-state in a way that suspend is not).
    marker = _unique_iso_language()
    p, cert = create_active_personnel(
        skill_tag="CLEANING",
        isolate_dispatch=False,
        languages=["zh", "en", marker],
    )
    customer = create_customer(pref_language=marker)
    orders: List[Dict[str, Any]] = []

    base_offset_hours = 14
    per_order_step_hours = 14

    for idx, amt in enumerate(target_amounts_cents):
        if amt not in grosses_for_amount:
            raise NotImplementedError(
                f"setup_personnel_with_settled_commission_only does not have "
                f"a recipe for target_amount={amt}; extend grosses_for_amount."
            )
        gross = grosses_for_amount[amt]
        item = create_service_item(
            required_skill_tag="CLEANING", base_price_cents=gross
        )
        ctx = {
            "customer": customer,
            "service_item": item,
            "personnel": p,
            "certification": cert,
        }
        sched = iso_in(hours=base_offset_hours + idx * per_order_step_hours)
        order = drive_order_to(
            ctx,
            "COMPLETED",
            duration_hours=1.0,
            scheduled_start_at=sched,
        )
        orders.append(order)

    # Advance past the 72h complaint window so all commissions are eligible.
    advance_clock(int((72 * 3600) + 60))

    return {
        "personnel": p,
        "certification": cert,
        "customer": customer,
        "orders": orders,
        "cycle_id": cycle_id,
    }


def open_claim_via_injury(
    order_id: str,
    *,
    reporter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.7: report an INJURY abnormal event → server opens the
    InsuranceClaim with claim_type=ON_JOB_INJURY automatically as a side
    effect. Returns the opened claim (fetched via GET /dsd/claims/{id})."""
    report_abnormal(
        order_id,
        category="INJURY",
        description="Test injury",
        reporter_headers=reporter_headers,
    )
    # Find the claim by listing audit logs would be one way; here we instead
    # use the listing endpoint surfaced via the order — but the PRD's only
    # claim-fetch route is /dsd/claims/{id}. We assume implementations expose
    # the claim id through the AbnormalEvent response or via the audit log.
    # For robustness across implementations we list audit-logs filtered by
    # action_type=CLAIM_REPORTED (PRD §3.7 says request-evidence appends one).
    # Simpler: poll the audit log after request-evidence — but we have not
    # yet requested evidence. So we instead require callers that need the
    # claim id to use a different fixture path. This helper just reports.
    raise NotImplementedError(
        "Use report_abnormal + lookup-by-listing in tests that need the claim id"
    )


def find_claim_for_order(order_id: str) -> Optional[Dict[str, Any]]:
    """Locate the InsuranceClaim opened against an order, if any.

    PRD §4 surfaces GET /dsd/claims/{id} but no claim-list endpoint. The
    workaround used by tests is to walk audit logs filtered by subject_id =
    order_id and action_type = CLAIM_REPORTED to fetch the claim_id from the
    payload — except request-evidence is what writes that audit row, not the
    automatic open.

    Concretely: tests should call request_claim_evidence on the claim they
    just opened; the audit-log row written then includes subject_id = claim id.
    We expose this helper for the lookup pattern.
    """
    res = api_client.list_audit_logs(
        OPERATOR_HEADERS,
        params={
            "subject_type": "InsuranceClaim",
            "action_type": "CLAIM_REPORTED",
            "limit": 100,
        },
    )
    rows = get_success_data(res)
    rows = rows if isinstance(rows, list) else rows.get("entries", [])
    for row in rows:
        payload = row.get("payload") or {}
        if payload.get("order_id") == order_id:
            claim_id = row["subject_id"]
            return get_claim(claim_id)
    return None
