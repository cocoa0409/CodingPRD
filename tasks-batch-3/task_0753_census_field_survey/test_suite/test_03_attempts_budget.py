"""Attempt pay commitment, area budget ledger, frozen-area gating, and the
state-vs-fiscal validation priority.

Translates queue-A combinatorial_formula (attempt-pay leg), cross_entity_state_dependency
(frozen leg), priority_pair_validation_conflict (attempt leg), compensating_invariant
(budget leg); and queue-B validations / cross_cutting budget instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    make_enumerator_headers,
    TEST_USERS,
    create_attempt_payload,
    setup_assigned_case,
    log_attempt,
)

ADMIN = TEST_USERS["survey_admin_headers"]
SUPERVISOR = TEST_USERS["field_supervisor_headers"]


# ── combinatorial_formula: attempt_pay_rounding_order ─────────────────────────

def test_attempt_pay_rounds_each_component_independently(api):
    """PRD §3.6: "The attempt's `pay_committed_cents` is the sum of the whole-cent
    stipend and the whole-cent mileage — each rounded first, then added; the two
    are never summed as fractions and rounded once."

    hourly 1533, 90-minute window: stipend = round_half_up(1533*90/60) = 2300;
    mileage = round_half_up(1.5*67) = 101; total = 2401 (never 2400).

    Design: Difficulty/combinatorial_formula/attempt_pay_rounding_order
    """
    ctx = setup_assigned_case(hourly_rate_cents=1533, budget_cents=1_000_000)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="IN_PERSON", window_start="2026-03-01T10:00:00Z",
                               window_end="2026-03-01T11:30:00Z", disposition="NO_ONE_HOME",
                               mileage_miles=1.5),
        en_headers)
    attempt = validate_success(res, 201)
    assert attempt["pay_committed_cents"] == 2401

    area = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert area["budget_committed_cents"] == 2401


def test_attempt_phone_mileage_component_is_zero(api):
    """PRD §3.6: "The mileage component applies only to in-person attempts: when
    `mode` is `IN_PERSON`, it is the attempt's `mileage_miles` (a non-negative
    distance, defaulting to 0) multiplied by the project's
    `mileage_rate_cents_per_mile`, rounded half up to whole cents; when `mode` is
    `PHONE`, the mileage component is zero regardless of any mileage value."

    hourly 1533, 90-minute PHONE window with mileage 1.5: stipend = 2300, mileage
    = 0, total = 2300.

    Design: Difficulty/combinatorial_formula/attempt_pay_rounding_order
    """
    ctx = setup_assigned_case(hourly_rate_cents=1533, budget_cents=1_000_000)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="PHONE", window_start="2026-03-01T10:00:00Z",
                               window_end="2026-03-01T11:30:00Z", disposition="NO_ONE_HOME",
                               mileage_miles=1.5),
        en_headers)
    attempt = validate_success(res, 201)
    assert attempt["pay_committed_cents"] == 2300


# ── cross_entity_state_dependency: attempt_blocked_by_area_frozen ─────────────

def test_attempt_blocked_when_area_frozen(api):
    """PRD §3.5: "Attempts may be logged only while the parent area is `IN_FIELD`
    and not frozen; a frozen area rejects them with `ERR_AREA_FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/attempt_blocked_by_area_frozen
    """
    ctx = setup_assigned_case(budget_cents=1_000_000, hourly_rate_cents=3000)
    validate_success(api.freeze_area(ctx["area"]["id"], ADMIN), 200)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="PHONE", window_start="2026-03-01T10:00:00Z",
                               window_end="2026-03-01T10:30:00Z", disposition="NO_ONE_HOME"),
        en_headers)
    validate_error(res, "ERR_AREA_FROZEN", expected_status=409)


def test_attempt_permitted_after_area_unfrozen(api):
    """PRD §3.5: "Attempts may be logged only while the parent area is `IN_FIELD`
    and not frozen; a frozen area rejects them with `ERR_AREA_FROZEN`."
    PRD §3.5: "The first logged attempt on an `ASSIGNED` case, carrying a
    non-terminal disposition, moves the case to `IN_PROGRESS`".

    Once the area is unfrozen back to IN_FIELD the same attempt is permitted,
    showing the gate is the area's IN_FIELD status.

    Design: Difficulty/cross_entity_state_dependency/attempt_blocked_by_area_frozen
    """
    ctx = setup_assigned_case(budget_cents=1_000_000, hourly_rate_cents=3000)
    validate_success(api.freeze_area(ctx["area"]["id"], ADMIN), 200)
    validate_success(api.unfreeze_area(ctx["area"]["id"], ADMIN), 200)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="PHONE", window_start="2026-03-01T10:00:00Z",
                               window_end="2026-03-01T10:30:00Z", disposition="NO_ONE_HOME"),
        en_headers)
    validate_success(res, 201)
    case = validate_success(api.get_case(ctx["case"]["id"], ADMIN), 200)
    assert case["status"] == "IN_PROGRESS"


# ── priority_pair_validation_conflict: state_beats_fiscal_on_attempt ──────────

def test_frozen_area_beats_budget_on_attempt(api):
    """PRD §2.11: "then the legal-source-state check for the transition (...for
    attempts and responses, the requirement that the parent area is `IN_FIELD` and
    not frozen via `ERR_AREA_NOT_IN_FIELD` and `ERR_AREA_FROZEN`); ... and finally
    the area budget check (`ERR_AREA_BUDGET_EXCEEDED`)."

    With a tiny (10-cent) budget AND a frozen area, the higher-priority state check
    wins: ERR_AREA_FROZEN, not ERR_AREA_BUDGET_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_attempt
    """
    ctx = setup_assigned_case(budget_cents=10, hourly_rate_cents=3000)
    validate_success(api.freeze_area(ctx["area"]["id"], ADMIN), 200)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="IN_PERSON", window_start="2026-03-01T10:00:00Z",
                               window_end="2026-03-01T11:00:00Z", disposition="NO_ONE_HOME",
                               mileage_miles=0),
        en_headers)
    validate_error(res, "ERR_AREA_FROZEN", expected_status=409)


def test_budget_check_surfaces_when_state_check_passes(api):
    """PRD §2.11: "then the legal-source-state check for the transition (...for
    attempts and responses, the requirement that the parent area is `IN_FIELD` and
    not frozen via `ERR_AREA_NOT_IN_FIELD` and `ERR_AREA_FROZEN`); ... and finally
    the area budget check (`ERR_AREA_BUDGET_EXCEEDED`)."

    Same tiny budget but the area left IN_FIELD (state check passes): the
    lower-priority fiscal check now fires with ERR_AREA_BUDGET_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_attempt
    """
    ctx = setup_assigned_case(budget_cents=10, hourly_rate_cents=3000)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="IN_PERSON", window_start="2026-03-01T10:00:00Z",
                               window_end="2026-03-01T11:00:00Z", disposition="NO_ONE_HOME",
                               mileage_miles=0),
        en_headers)
    validate_error(res, "ERR_AREA_BUDGET_EXCEEDED", expected_status=402)


# ── compensating_invariant: budget_conservation_on_attempt_cancel ─────────────

def test_cancel_attempt_releases_committed_budget(api):
    """PRD §3.6: "When a `FieldSupervisor` cancels a logged attempt (§3.5), the
    area's `budget_committed_cents` is reduced by that attempt's
    `pay_committed_cents` and `budget_remaining_cents` is recomputed, releasing the
    commitment."

    An in-person 60-minute attempt at hourly 3000 with 10 miles commits 3670;
    cancelling returns committed to 0 and remaining to the full 500000 budget.

    Design: Difficulty/compensating_invariant/budget_conservation_on_attempt_cancel
    """
    ctx = setup_assigned_case(budget_cents=500_000, hourly_rate_cents=3000)
    attempt = log_attempt(
        ctx["case"]["id"], ctx["enumerator"]["id"],
        mode="IN_PERSON", window_start="2026-03-01T10:00:00Z",
        window_end="2026-03-01T11:00:00Z", disposition="NO_ONE_HOME", mileage_miles=10)
    assert attempt["pay_committed_cents"] == 3670

    validate_success(api.cancel_attempt(attempt["id"], SUPERVISOR), 200)
    area = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert area["budget_committed_cents"] == 0
    assert area["budget_remaining_cents"] == 500_000


def test_budget_committed_plus_remaining_conserved_across_cancel(api):
    """PRD §2.9: "The area maintains two derived figures: `budget_committed_cents`,
    the sum of `pay_committed_cents` across the area's LOGGED (non-cancelled)
    attempts, and `budget_remaining_cents`, which equals `budget_cents` minus
    `budget_committed_cents`."

    committed + remaining == budget_cents both before and after the cancellation.

    Design: Difficulty/compensating_invariant/budget_conservation_on_attempt_cancel
    """
    ctx = setup_assigned_case(budget_cents=500_000, hourly_rate_cents=3000)
    attempt = log_attempt(
        ctx["case"]["id"], ctx["enumerator"]["id"],
        mode="IN_PERSON", window_start="2026-03-01T10:00:00Z",
        window_end="2026-03-01T11:00:00Z", disposition="NO_ONE_HOME", mileage_miles=10)

    before = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert before["budget_committed_cents"] + before["budget_remaining_cents"] == 500_000
    assert before["budget_committed_cents"] == 3670

    validate_success(api.cancel_attempt(attempt["id"], SUPERVISOR), 200)
    after = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert after["budget_committed_cents"] + after["budget_remaining_cents"] == 500_000
    assert after["budget_committed_cents"] == 0


# ── queue-B: validation + budget reconciliation ───────────────────────────────

def test_attempt_invalid_time_window_returns_validation(api):
    """PRD §3.5: "a planned contact window given by `window_start` and `window_end`
    (both ISO 8601 UTC, with `window_end` required to be strictly after
    `window_start`, else `ERR_VALIDATION`)".

    Design: Corner/validations/attempt_invalid_time_window_returns_validation
    """
    ctx = setup_assigned_case()
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="PHONE", window_start="2026-03-01T11:00:00Z",
                               window_end="2026-03-01T10:00:00Z", disposition="NO_ONE_HOME"),
        en_headers)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_budget_committed_reconciles_after_attempt(api):
    """PRD §3.6: "When the attempt is accepted, the area's `budget_committed_cents`
    increases by `pay_committed_cents`, and `budget_remaining_cents` is recomputed
    as `budget_cents` minus `budget_committed_cents`."

    A 60-minute in-person attempt at hourly 3000 commits 3000 against a 100000
    budget, leaving 97000 remaining.

    Design: Corner/cross_cutting/budget_committed_reconciles_after_attempt
    """
    ctx = setup_assigned_case(budget_cents=100_000, hourly_rate_cents=3000)
    log_attempt(
        ctx["case"]["id"], ctx["enumerator"]["id"],
        mode="IN_PERSON", window_start="2026-03-01T10:00:00Z",
        window_end="2026-03-01T11:00:00Z", disposition="NO_ONE_HOME", mileage_miles=0)
    area = validate_success(api.get_area(ctx["area"]["id"], ADMIN), 200)
    assert area["budget_committed_cents"] == 3000
    assert area["budget_remaining_cents"] == 97_000


def test_attempt_budget_exceeded_returns_402(api):
    """PRD §3.6: "the area's `budget_remaining_cents` must be at least the
    attempt's `pay_committed_cents`, or the attempt is rejected with
    `ERR_AREA_BUDGET_EXCEEDED`."

    A 60-minute in-person attempt commits 3000, exceeding a 100-cent budget.

    Design: Corner/cross_cutting/attempt_budget_exceeded_returns_402
    """
    ctx = setup_assigned_case(budget_cents=100, hourly_rate_cents=3000)
    en_headers = make_enumerator_headers(ctx["enumerator"]["id"])
    res = api.create_attempt(
        ctx["case"]["id"],
        create_attempt_payload(mode="IN_PERSON", window_start="2026-03-01T10:00:00Z",
                               window_end="2026-03-01T11:00:00Z", disposition="NO_ONE_HOME",
                               mileage_miles=0),
        en_headers)
    validate_error(res, "ERR_AREA_BUDGET_EXCEEDED", expected_status=402)
