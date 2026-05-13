"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup
failures produce clear "Setup failed" errors instead of confusing
assertion failures.

All fixtures honor PRD §2.1 identity rules:

- Grantee headers are minted per-Grantee via make_grantee_headers(
  hr_employee_id) — never the shared TEST_USERS["grantee_headers"]
  fallback, which would fail every ownership check.

- Segregation-of-duties (PRD §3.4): the draft submitter, board
  approver, and shareholder approver each use a DISTINCT opaque
  X-User-ID drawn from the *_alt variants in TEST_USERS.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
)
from .factories import (
    activate_option_plan_payload,
    clock_advance_payload,
    create_blackout_event_payload,
    create_change_of_control_payload,
    create_departure_record_payload,
    create_exercise_application_payload,
    create_exercise_window_payload,
    create_grant_batch_payload,
    create_grant_payload,
    create_grantee_payload,
    create_ipo_payload,
    create_option_plan_payload,
    create_restructuring_payload,
    create_stock_split_payload,
    pay_application_payload,
    settle_application_cash_payload,
    settle_application_share_payload,
    sign_agreement_payload,
)
from .test_users import (
    TEST_USERS,
    make_grantee_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: State Progression — single-entity walk to a target state
# ---------------------------------------------------------------------------
def create_and_activate_plan(
    *,
    pool_total_options: int = TEST_DEFAULTS["POOL_TOTAL"],
    jurisdiction_code: str = TEST_DEFAULTS["JURISDICTION_US"],
    now_iso: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create OptionPlan + activate. Returns the ACTIVE plan.

    PRD §3.1: 'Activation by the same administrator transitions the
    plan from DRAFT to ACTIVE.'
    """
    payload = create_option_plan_payload(
        pool_total_options=pool_total_options,
        jurisdiction_code=jurisdiction_code,
    )
    if name is not None:
        payload["name"] = name
    create_res = api_client.create_option_plan(
        payload, TEST_USERS["plan_admin_headers"],
    )
    plan = get_success_data(create_res)
    activate_res = api_client.activate_option_plan(
        plan["id"],
        TEST_USERS["plan_admin_headers"],
        activate_option_plan_payload(now_iso=now_iso),
    )
    return get_success_data(activate_res)


def create_and_open_batch(
    plan_id: str,
    *,
    cliff_months: int = TEST_DEFAULTS["CLIFF_MONTHS"],
    vesting_total_months: int = TEST_DEFAULTS["VESTING_TOTAL_MONTHS"],
    vesting_period_months: int = TEST_DEFAULTS["VESTING_PERIOD_MONTHS"],
    vesting_algorithm: str = TEST_DEFAULTS["VESTING_ALGORITHM_ANNIVERSARY"],
    performance_condition_required: bool = False,
    initial_price_per_option_cents: int = TEST_DEFAULTS["INITIAL_PRICE_CENTS"],
    batch_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Create GrantBatch + open. Returns the OPEN_FOR_GRANTS batch.

    PRD §3.2: 'Opening the batch transitions it from DRAFT to
    OPEN_FOR_GRANTS' and auto-creates v1 price version.
    """
    payload = create_grant_batch_payload(
        cliff_months=cliff_months,
        vesting_total_months=vesting_total_months,
        vesting_period_months=vesting_period_months,
        vesting_algorithm=vesting_algorithm,
        performance_condition_required=performance_condition_required,
        initial_price_per_option_cents=initial_price_per_option_cents,
    )
    if batch_label is not None:
        payload["batch_label"] = batch_label
    create_res = api_client.create_grant_batch(
        plan_id, payload, TEST_USERS["plan_admin_headers"],
    )
    batch = get_success_data(create_res)
    open_res = api_client.open_grant_batch(
        plan_id, batch["id"], TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(open_res)


def register_grantee(
    plan_id: str,
    *,
    tax_residency: str = TEST_DEFAULTS["JURISDICTION_US"],
    full_name: str = "Grantee Alpha",
    hr_employee_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a Grantee. Returns the ELIGIBLE grantee row."""
    if hr_employee_id is None:
        hr_employee_id = f"hr-{uuid.uuid4().hex[:10]}"
    payload = create_grantee_payload(
        hr_employee_id=hr_employee_id,
        full_name=full_name,
        tax_residency=tax_residency,
    )
    res = api_client.create_grantee(
        plan_id, payload, TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: Entity Hierarchy — plan + batch + grantee in one call
# ---------------------------------------------------------------------------
def setup_plan_batch_grantee(
    *,
    pool_total_options: int = TEST_DEFAULTS["POOL_TOTAL"],
    jurisdiction_code: str = TEST_DEFAULTS["JURISDICTION_US"],
    tax_residency: Optional[str] = None,
    vesting_algorithm: str = TEST_DEFAULTS["VESTING_ALGORITHM_ANNIVERSARY"],
    cliff_months: int = TEST_DEFAULTS["CLIFF_MONTHS"],
    vesting_total_months: int = TEST_DEFAULTS["VESTING_TOTAL_MONTHS"],
    vesting_period_months: int = TEST_DEFAULTS["VESTING_PERIOD_MONTHS"],
    performance_condition_required: bool = False,
    initial_price_per_option_cents: int = TEST_DEFAULTS["INITIAL_PRICE_CENTS"],
    now_iso: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """ACTIVE plan + OPEN_FOR_GRANTS batch + ELIGIBLE grantee.

    Returns (plan, batch, grantee).
    """
    plan = create_and_activate_plan(
        pool_total_options=pool_total_options,
        jurisdiction_code=jurisdiction_code,
        now_iso=now_iso,
    )
    batch = create_and_open_batch(
        plan["id"],
        cliff_months=cliff_months,
        vesting_total_months=vesting_total_months,
        vesting_period_months=vesting_period_months,
        vesting_algorithm=vesting_algorithm,
        performance_condition_required=performance_condition_required,
        initial_price_per_option_cents=initial_price_per_option_cents,
    )
    grantee = register_grantee(
        plan["id"],
        tax_residency=tax_residency or jurisdiction_code,
    )
    return plan, batch, grantee


# ---------------------------------------------------------------------------
# Tier 3: Full lifecycle — Grant through DRAFT → LIVE/FROZEN
# ---------------------------------------------------------------------------
def _draft_grant(
    plan_id: str,
    batch_id: str,
    grantee_id: str,
    *,
    quantity: int = TEST_DEFAULTS["GRANT_QUANTITY"],
    grant_date_fair_value_cents: int = TEST_DEFAULTS["GRANT_FAIR_VALUE_CENTS"],
    submitter_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = create_grant_payload(
        grantee_id,
        quantity=quantity,
        grant_date_fair_value_cents=grant_date_fair_value_cents,
    )
    res = api_client.create_grant(
        plan_id, batch_id, payload,
        submitter_headers or TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def _drive_grant_to_shareholder_approved(
    grant_id: str,
    *,
    submitter_headers: Optional[Dict[str, str]] = None,
    board_headers: Optional[Dict[str, str]] = None,
    shareholder_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Drive a DRAFT grant through board + shareholder approvals.

    PRD §3.4 segregation-of-duties: the three actors must each have
    distinct X-User-IDs. Defaults use the three opaque headers in
    TEST_USERS that already differ.
    """
    board = board_headers or TEST_USERS["board_secretary_headers"]
    sr = shareholder_headers or TEST_USERS["shareholder_registrar_headers"]

    board_res = api_client.board_approve_grant(grant_id, board)
    get_success_data(board_res)
    sh_res = api_client.shareholder_approve_grant(grant_id, sr)
    return get_success_data(sh_res)


def create_grant_and_drive_to_live(
    plan: Dict[str, Any],
    batch: Dict[str, Any],
    grantee: Dict[str, Any],
    *,
    quantity: int = TEST_DEFAULTS["GRANT_QUANTITY"],
    grant_date_fair_value_cents: int = TEST_DEFAULTS["GRANT_FAIR_VALUE_CENTS"],
) -> Dict[str, Any]:
    """Take Grant from DRAFT → BOARD_APPROVED → SHAREHOLDER_APPROVED →
    AGREEMENT_SIGNED → LIVE.

    PRD §3.4: the grantee signs themselves, using
    X-User-ID == Grantee.hr_employee_id.
    """
    draft = _draft_grant(
        plan["id"], batch["id"], grantee["id"],
        quantity=quantity,
        grant_date_fair_value_cents=grant_date_fair_value_cents,
        submitter_headers=TEST_USERS["plan_admin_headers"],
    )
    _drive_grant_to_shareholder_approved(draft["id"])

    # PRD §3.4: signing uses the grantee's own X-User-ID
    # (hr_employee_id). Per-instance builder is mandatory here.
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    sign_res = api_client.sign_agreement(
        draft["id"], grantee_hdrs, sign_agreement_payload(),
    )
    return get_success_data(sign_res)


def create_grant_in_state(
    plan: Dict[str, Any],
    batch: Dict[str, Any],
    grantee: Dict[str, Any],
    target_state: str,
    *,
    quantity: int = TEST_DEFAULTS["GRANT_QUANTITY"],
    grant_date_fair_value_cents: int = TEST_DEFAULTS["GRANT_FAIR_VALUE_CENTS"],
) -> Dict[str, Any]:
    """Walk Grant up to `target_state`. Useful for parametrized
    state-precondition tests."""
    draft = _draft_grant(
        plan["id"], batch["id"], grantee["id"],
        quantity=quantity,
        grant_date_fair_value_cents=grant_date_fair_value_cents,
    )
    if target_state == "DRAFT":
        return draft
    board_res = api_client.board_approve_grant(
        draft["id"], TEST_USERS["board_secretary_headers"],
    )
    after_board = get_success_data(board_res)
    if target_state == "BOARD_APPROVED":
        return after_board
    sh_res = api_client.shareholder_approve_grant(
        draft["id"], TEST_USERS["shareholder_registrar_headers"],
    )
    after_sh = get_success_data(sh_res)
    if target_state == "SHAREHOLDER_APPROVED":
        return after_sh
    grantee_hdrs = make_grantee_headers(grantee["hr_employee_id"])
    sign_res = api_client.sign_agreement(
        draft["id"], grantee_hdrs, sign_agreement_payload(),
    )
    after_sign = get_success_data(sign_res)
    # AGREEMENT_SIGNED routes to LIVE (no blackout) or FROZEN (blackout
    # active). Either is acceptable; the caller can refresh as needed.
    return after_sign


# ---------------------------------------------------------------------------
# Tier 4: Time / clock manipulation
# ---------------------------------------------------------------------------
def advance_clock_by_seconds(plan_id: str, by_seconds: int) -> Dict[str, Any]:
    """Advance plan clock by the supplied seconds. PRD §2.4."""
    res = api_client.advance_clock(
        plan_id,
        clock_advance_payload(by_seconds),
        TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def advance_clock_by_months(plan_id: str, months: int) -> Dict[str, Any]:
    """Advance plan clock by `months * 30 days` of seconds.

    PRD §3.5 vesting constant: DAYS_PER_MONTH = 30. The CONTINUOUS_DAILY
    branch and the cliff-months calculation both use 30 days per month.
    """
    return advance_clock_by_seconds(
        plan_id, months * 30 * SECONDS_PER_DAY,
    )


def advance_clock_by_days(plan_id: str, days: int) -> Dict[str, Any]:
    """Advance plan clock by `days` of seconds."""
    return advance_clock_by_seconds(plan_id, days * SECONDS_PER_DAY)


# ---------------------------------------------------------------------------
# Tier 4: Exercise window setup
# ---------------------------------------------------------------------------
def create_window(
    plan_id: str,
    open_ts: str,
    close_ts: str,
    *,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an exercise window. PRD §3.6."""
    payload = create_exercise_window_payload(open_ts, close_ts)
    if label is not None:
        payload["label"] = label
    res = api_client.create_exercise_window(
        plan_id, payload, TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def create_window_and_open(
    plan_id: str,
    open_ts: str,
    close_ts: str,
    *,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Create window, then run /sweep so SCHEDULED → OPEN if clock has
    crossed open_ts. PRD §3.6."""
    window = create_window(plan_id, open_ts, close_ts, label=label)
    sweep_res = api_client.sweep_exercise_windows(
        plan_id, TEST_USERS["plan_admin_headers"],
    )
    get_success_data(sweep_res)
    # Refresh the window we created to capture its new state.
    list_res = api_client.list_exercise_windows(
        plan_id, TEST_USERS["plan_admin_headers"],
    )
    items, _ = _split_paginated(list_res)
    for w in items:
        if w["id"] == window["id"]:
            return w
    return window


def _split_paginated(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Lenient paginated split for fixture-time reads. Returns (data, meta)."""
    body = response.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 4: Corporate event creation
# ---------------------------------------------------------------------------
def create_blackout(
    plan_id: str,
    effective_ts: str,
    blackout_end_ts: str,
    *,
    event_type: str = "EARNINGS_BLACKOUT",
) -> Dict[str, Any]:
    """Create a *_BLACKOUT CorporateEvent. PRD §3.6."""
    payload = create_blackout_event_payload(
        event_type, effective_ts, blackout_end_ts,
    )
    res = api_client.create_corporate_event(
        plan_id, payload, TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def create_stock_split(
    plan_id: str,
    effective_ts: str,
    numerator: int = 2,
    denominator: int = 1,
) -> Dict[str, Any]:
    """Create a STOCK_SPLIT CorporateEvent. PRD §3.7."""
    payload = create_stock_split_payload(
        effective_ts, numerator, denominator,
    )
    res = api_client.create_corporate_event(
        plan_id, payload, TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def create_restructuring(
    plan_id: str,
    effective_ts: str,
    restructure_factor_bps: int,
) -> Dict[str, Any]:
    """Create a RESTRUCTURING CorporateEvent. PRD §3.7."""
    payload = create_restructuring_payload(
        effective_ts, restructure_factor_bps,
    )
    res = api_client.create_corporate_event(
        plan_id, payload, TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def create_change_of_control(plan_id: str,
                             effective_ts: str) -> Dict[str, Any]:
    """Create a CHANGE_OF_CONTROL CorporateEvent. PRD §3.7."""
    payload = create_change_of_control_payload(effective_ts)
    res = api_client.create_corporate_event(
        plan_id, payload, TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def create_ipo(plan_id: str, effective_ts: str) -> Dict[str, Any]:
    """Create an IPO CorporateEvent. PRD §3.7."""
    payload = create_ipo_payload(effective_ts)
    res = api_client.create_corporate_event(
        plan_id, payload, TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 4: Price version helpers
# ---------------------------------------------------------------------------
def get_tip_price_version(batch_id: str) -> Dict[str, Any]:
    """Return the highest-version_index ExercisePriceVersion for the
    batch. PRD §3.7: 'parent_version_id set to the previous tip.'"""
    res = api_client.list_exercise_price_versions(
        batch_id, TEST_USERS["plan_admin_headers"],
    )
    items, _ = _split_paginated(res)
    if not items:
        raise RuntimeError(
            f"Setup failed: no ExercisePriceVersion rows for batch "
            f"{batch_id}"
        )
    return max(items, key=lambda v: v["version_index"])


# ---------------------------------------------------------------------------
# Tier 5: Exercise-application lifecycle shortcuts
# ---------------------------------------------------------------------------
def submit_exercise_application(
    grant: Dict[str, Any],
    window: Dict[str, Any],
    grantee: Dict[str, Any],
    *,
    requested_quantity: int,
    settlement_mode: str,
    pinned_price_version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit an ExerciseApplication on behalf of the owning grantee.

    PRD §3.8: 'A grantee submits an exercise application against an
    OPEN window.' The grantee acts under their own hr_employee_id
    (entity_backed identity).
    """
    pinned = (
        pinned_price_version_id
        or grant.get("pinned_price_version_id")
    )
    if pinned is None:
        raise RuntimeError(
            "Setup failed: Grant has no pinned_price_version_id; "
            "drive grant to AGREEMENT_SIGNED first."
        )
    payload = create_exercise_application_payload(
        window_id=window["id"],
        pinned_price_version_id=pinned,
        requested_quantity=requested_quantity,
        settlement_mode=settlement_mode,
    )
    res = api_client.create_exercise_application(
        grant["id"], payload,
        make_grantee_headers(grantee["hr_employee_id"]),
    )
    return get_success_data(res)


def drive_app_to_tax_withheld_cash(
    app: Dict[str, Any],
) -> Dict[str, Any]:
    """CASH_SETTLEMENT path: /verify cascades to TAX_WITHHELD.
    PRD §3.8."""
    res = api_client.verify_exercise_application(
        app["id"], TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def drive_app_to_tax_withheld_share(
    app: Dict[str, Any],
    *,
    payment_reference: str = "BK-TEST",
) -> Dict[str, Any]:
    """SHARE_ISSUANCE path: /verify → /pay → TAX_WITHHELD. PRD §3.8."""
    verify_res = api_client.verify_exercise_application(
        app["id"], TEST_USERS["plan_admin_headers"],
    )
    get_success_data(verify_res)
    pay_res = api_client.pay_exercise_application(
        app["id"],
        pay_application_payload(payment_reference),
        TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(pay_res)


def settle_app_share(
    app_id: str,
    share_registry_reference: str = "SR-TEST",
) -> Dict[str, Any]:
    """SHARE_ISSUANCE settle. PRD §3.8."""
    res = api_client.settle_exercise_application(
        app_id,
        settle_application_share_payload(share_registry_reference),
        TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def settle_app_cash(
    app_id: str,
    payment_reference: str = "BK-CASH",
) -> Dict[str, Any]:
    """CASH_SETTLEMENT settle. PRD §3.8."""
    res = api_client.settle_exercise_application(
        app_id,
        settle_application_cash_payload(payment_reference),
        TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 5: Departure workflow shortcuts
# ---------------------------------------------------------------------------
def create_departure_draft(
    plan_id: str,
    grantee_id: str,
    *,
    departure_type: str,
    departed_ts: str,
    leaver_class: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a DepartureRecord in DRAFT. PRD §3.10."""
    payload = create_departure_record_payload(
        departure_type, departed_ts, leaver_class=leaver_class,
    )
    res = api_client.create_departure_record(
        plan_id, grantee_id, payload,
        TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


def settle_departure(
    grantee_id: str,
    dep_id: str,
) -> Dict[str, Any]:
    """Finalize the departure cascade. PRD §3.10."""
    res = api_client.settle_departure_record(
        grantee_id, dep_id, TEST_USERS["plan_admin_headers"],
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# High-level composite fixtures for difficulty-design instances
# ---------------------------------------------------------------------------
def setup_two_batches_anniversary_and_continuous(
    *,
    now_iso: Optional[str] = None,
    cliff_months: int = 12,
    vesting_total_months: int = 48,
    vesting_period_months: int = 3,
    initial_price_per_option_cents: int = 5000,
    quantity: int = 1200,
) -> Dict[str, Any]:
    """Build the dual-variant vested_quantity fixture (Rule 1 / inst 1).

    Produces:
      plan (ACTIVE, US),
      batch_anniversary (OPEN, vesting_algorithm=ANNIVERSARY_BATCH),
      batch_continuous (OPEN, vesting_algorithm=CONTINUOUS_DAILY),
      grantee (ELIGIBLE),
      grant_anniversary (LIVE on batch_anniversary, quantity),
      grant_continuous (LIVE on batch_continuous, quantity).
    """
    plan = create_and_activate_plan(now_iso=now_iso)
    batch_anniversary = create_and_open_batch(
        plan["id"],
        cliff_months=cliff_months,
        vesting_total_months=vesting_total_months,
        vesting_period_months=vesting_period_months,
        vesting_algorithm="ANNIVERSARY_BATCH",
        initial_price_per_option_cents=initial_price_per_option_cents,
        batch_label="Anniv-Batch",
    )
    batch_continuous = create_and_open_batch(
        plan["id"],
        cliff_months=cliff_months,
        vesting_total_months=vesting_total_months,
        vesting_period_months=vesting_period_months,
        vesting_algorithm="CONTINUOUS_DAILY",
        initial_price_per_option_cents=initial_price_per_option_cents,
        batch_label="Cont-Batch",
    )
    grantee = register_grantee(plan["id"])

    grant_a = create_grant_and_drive_to_live(
        plan, batch_anniversary, grantee,
        quantity=quantity,
        grant_date_fair_value_cents=initial_price_per_option_cents,
    )
    grant_c = create_grant_and_drive_to_live(
        plan, batch_continuous, grantee,
        quantity=quantity,
        grant_date_fair_value_cents=initial_price_per_option_cents,
    )
    return {
        "plan": plan,
        "batch_anniversary": batch_anniversary,
        "batch_continuous": batch_continuous,
        "grantee": grantee,
        "grant_anniversary": grant_a,
        "grant_continuous": grant_c,
    }


def setup_live_grant_with_open_window(
    *,
    jurisdiction_code: str = "US",
    tax_residency: Optional[str] = None,
    pool_total_options: int = 10_000,
    quantity: int = 1200,
    vesting_algorithm: str = "ANNIVERSARY_BATCH",
    cliff_months: int = 12,
    vesting_total_months: int = 48,
    vesting_period_months: int = 3,
    initial_price_per_option_cents: int = 5000,
    window_open_offset_seconds: int = 0,
    window_close_offset_seconds: int = 30 * SECONDS_PER_DAY,
    advance_clock_months_after_grant: Optional[int] = None,
) -> Dict[str, Any]:
    """Build plan + open batch + grantee + LIVE grant + OPEN window.

    Most-used fixture across the exercise-application test family.
    Optionally advance the plan clock by `advance_clock_months_after_grant`
    so the grant has vested some quantity by the time the window opens.
    """
    plan = create_and_activate_plan(
        pool_total_options=pool_total_options,
        jurisdiction_code=jurisdiction_code,
    )
    batch = create_and_open_batch(
        plan["id"],
        cliff_months=cliff_months,
        vesting_total_months=vesting_total_months,
        vesting_period_months=vesting_period_months,
        vesting_algorithm=vesting_algorithm,
        initial_price_per_option_cents=initial_price_per_option_cents,
    )
    grantee = register_grantee(
        plan["id"], tax_residency=tax_residency or jurisdiction_code,
    )
    grant = create_grant_and_drive_to_live(
        plan, batch, grantee,
        quantity=quantity,
        grant_date_fair_value_cents=initial_price_per_option_cents,
    )
    if advance_clock_months_after_grant is not None:
        advance_clock_by_months(
            plan["id"], advance_clock_months_after_grant,
        )

    # Refresh the plan clock and read its current value.
    plan_now = get_success_data(
        api_client.get_option_plan(
            plan["id"], TEST_USERS["plan_admin_headers"],
        )
    )
    clock_ts = plan_now["current_clock_ts"]
    window = _create_window_relative(
        plan["id"],
        anchor_ts=clock_ts,
        open_offset_seconds=window_open_offset_seconds,
        close_offset_seconds=window_close_offset_seconds,
    )
    return {
        "plan": plan_now,
        "batch": batch,
        "grantee": grantee,
        "grant": grant,
        "window": window,
    }


def _create_window_relative(
    plan_id: str,
    anchor_ts: str,
    open_offset_seconds: int,
    close_offset_seconds: int,
) -> Dict[str, Any]:
    """Helper: create a window whose open_ts/close_ts are anchor +
    offsets. Then sweep to push it to OPEN if the clock has reached
    open_ts."""
    import datetime as _dt

    base = _dt.datetime.fromisoformat(anchor_ts.replace("Z", "+00:00"))
    open_ts = (
        base + _dt.timedelta(seconds=open_offset_seconds)
    ).isoformat().replace("+00:00", "Z")
    close_ts = (
        base + _dt.timedelta(seconds=close_offset_seconds)
    ).isoformat().replace("+00:00", "Z")
    return create_window_and_open(plan_id, open_ts, close_ts)


def setup_plan_with_blackout(
    *,
    blackout_start_offset_seconds: int = 0,
    blackout_duration_seconds: int = 7 * SECONDS_PER_DAY,
    event_type: str = "EARNINGS_BLACKOUT",
) -> Dict[str, Any]:
    """ACTIVE plan + active *_BLACKOUT CorporateEvent at clock=now.

    Used by sign-agreement → FROZEN branch tests (Rule 3 / inst 1)
    and window-overlap tests (Rule 8).
    """
    plan = create_and_activate_plan()
    import datetime as _dt
    base = _dt.datetime.fromisoformat(
        plan["current_clock_ts"].replace("Z", "+00:00")
    )
    effective_ts = (
        base + _dt.timedelta(seconds=blackout_start_offset_seconds)
    ).isoformat().replace("+00:00", "Z")
    blackout_end_ts = (
        base + _dt.timedelta(
            seconds=blackout_start_offset_seconds + blackout_duration_seconds,
        )
    ).isoformat().replace("+00:00", "Z")
    blackout = create_blackout(
        plan["id"], effective_ts, blackout_end_ts,
        event_type=event_type,
    )
    return {"plan": plan, "blackout": blackout}


def setup_grant_ready_to_sign(
    *,
    pool_total_options: int = 10_000,
    quantity: int = 1200,
    initial_price_per_option_cents: int = 5000,
    plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan ACTIVE + Grant in SHAREHOLDER_APPROVED, ready to /sign-agreement.

    Used by Rule 3 inst 1 (sign-agreement branching to LIVE vs FROZEN).
    Accepts a pre-built plan (used by tests that create a blackout
    BEFORE driving the grant to sign-agreement).
    """
    if plan is None:
        plan = create_and_activate_plan(
            pool_total_options=pool_total_options,
        )
    batch = create_and_open_batch(
        plan["id"],
        initial_price_per_option_cents=initial_price_per_option_cents,
    )
    grantee = register_grantee(plan["id"])
    draft = _draft_grant(
        plan["id"], batch["id"], grantee["id"],
        quantity=quantity,
        grant_date_fair_value_cents=initial_price_per_option_cents,
    )
    grant = _drive_grant_to_shareholder_approved(draft["id"])
    return {
        "plan": plan,
        "batch": batch,
        "grantee": grantee,
        "grant": grant,
    }


def setup_pool_boundary(
    *,
    pool_total_options: int = 10_000,
    first_grant_qty: int = 6000,
) -> Dict[str, Any]:
    """Plan ACTIVE + batch OPEN + grantee + one Grant already
    board-approved at `first_grant_qty`.

    Used by Rule 6 inst 1: pool_remaining boundary at /board-approve.
    Returns helpers to draft additional grants of arbitrary size against
    the same plan/batch/grantee.
    """
    plan = create_and_activate_plan(pool_total_options=pool_total_options)
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    first_draft = _draft_grant(
        plan["id"], batch["id"], grantee["id"],
        quantity=first_grant_qty,
        submitter_headers=TEST_USERS["plan_admin_headers"],
    )
    get_success_data(api_client.board_approve_grant(
        first_draft["id"], TEST_USERS["board_secretary_headers"],
    ))
    return {
        "plan": plan,
        "batch": batch,
        "grantee": grantee,
        "first_grant": first_draft,
    }


def setup_three_grants_for_pool_invariant(
    *,
    pool_total_options: int = 10_000,
    per_grant_quantity: int = 1200,
    initial_price_per_option_cents: int = 5000,
) -> Dict[str, Any]:
    """Plan ACTIVE + batch OPEN + grantee + three Grants driven to LIVE
    of `per_grant_quantity` each. Used by Rule 9 inst 1 — option pool
    conservation."""
    plan = create_and_activate_plan(pool_total_options=pool_total_options)
    batch = create_and_open_batch(
        plan["id"],
        initial_price_per_option_cents=initial_price_per_option_cents,
    )
    grantee = register_grantee(plan["id"])
    grants = []
    for _ in range(3):
        g = create_grant_and_drive_to_live(
            plan, batch, grantee,
            quantity=per_grant_quantity,
            grant_date_fair_value_cents=initial_price_per_option_cents,
        )
        grants.append(g)
    return {
        "plan": plan,
        "batch": batch,
        "grantee": grantee,
        "grants": grants,
    }


# ---------------------------------------------------------------------------
# Audit log query helper
# ---------------------------------------------------------------------------
def list_audit_for_target(
    plan_id: str,
    target_id: str,
    *,
    action_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convenience: filter audit log by target_id (and optionally
    action_code). PRD §3.11."""
    params: Dict[str, Any] = {"target_id": target_id, "limit": 100}
    if action_code is not None:
        params["action_code"] = action_code
    res = api_client.list_audit_log(
        plan_id, TEST_USERS["plan_admin_headers"], params=params,
    )
    items, _ = _split_paginated(res)
    return items


def list_tax_events_for_grant(
    grant_id: str,
    *,
    event_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convenience: GET /grants/{grantId}/tax-events. PRD §3.9."""
    params: Dict[str, Any] = {}
    if event_type is not None:
        params["event_type"] = event_type
    res = api_client.list_tax_events(
        grant_id, TEST_USERS["plan_admin_headers"], params=params,
    )
    items, _ = _split_paginated(res)
    return items


__all__ = [
    # Tier 1
    "create_and_activate_plan",
    "create_and_open_batch",
    "register_grantee",
    # Tier 2
    "setup_plan_batch_grantee",
    # Tier 3
    "create_grant_and_drive_to_live",
    "create_grant_in_state",
    # Tier 4
    "advance_clock_by_seconds",
    "advance_clock_by_months",
    "advance_clock_by_days",
    "create_window",
    "create_window_and_open",
    "create_blackout",
    "create_stock_split",
    "create_restructuring",
    "create_change_of_control",
    "create_ipo",
    "get_tip_price_version",
    # Tier 5
    "submit_exercise_application",
    "drive_app_to_tax_withheld_cash",
    "drive_app_to_tax_withheld_share",
    "settle_app_share",
    "settle_app_cash",
    "create_departure_draft",
    "settle_departure",
    # Difficulty-design composite fixtures
    "setup_two_batches_anniversary_and_continuous",
    "setup_live_grant_with_open_window",
    "setup_plan_with_blackout",
    "setup_grant_ready_to_sign",
    "setup_pool_boundary",
    "setup_three_grants_for_pool_invariant",
    # Query helpers
    "list_audit_for_target",
    "list_tax_events_for_grant",
]
