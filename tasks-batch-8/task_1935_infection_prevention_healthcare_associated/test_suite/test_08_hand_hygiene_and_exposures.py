"""Hand-hygiene program (dual-variant rates, reportability floor, pagination,
immutability) and the employee-exposure follow-up protocol (PRD §2.3, §2.6,
§3.10, §3.11)."""
from test_helpers import (
    ApiErrorId,
    assert_approx_equal,
    assert_instant_equal,
    assert_observation,
    create_employee,
    create_exposure,
    get_hh_rate,
    record_draw,
    record_observation,
    record_observation_batch,
    record_source_serologies,
    set_clock,
    setup_exposure_through_baseline,
    setup_facility_unit,
    setup_unit_with_skewed_observation_weeks,
    setup_unit_with_weighted_observations,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Hand hygiene dual variant (simple vs opportunity-weighted)
# ---------------------------------------------------------------------------

def test_hand_hygiene_simple_rate_over_mixed_observations(api, nurse_manager_headers):
    """PRD §3.10: "The simple rate, `simple_rate_pct`, is one hundred times
    `compliant_count` divided by `total_count`, rounded to one decimal place
    half-up."
    PRD §3.10: "The month is **reportable** — the response's `reportable`
    flag — only when `total_count` reaches the facility's
    `hh_min_opportunities`; below that floor both rates come back null."

    Design: Difficulty/dual_variant_calc/hand_hygiene_simple_vs_weighted_on_unit
    """
    ctx = setup_unit_with_weighted_observations()
    rate = get_hh_rate(ctx["unit"]["id"], "2026-08")
    assert rate["total_count"] == 40
    assert rate["compliant_count"] == 30
    assert rate["reportable"] is True, "40 >= the default 30-opportunity floor"
    assert_approx_equal(rate["simple_rate_pct"], 75.0, "simple_rate_pct")


def test_hand_hygiene_weighted_rate_differs_from_simple(api, nurse_manager_headers):
    """PRD §3.10: "The opportunity-weighted rate, `weighted_rate_pct`, weights
    each observation by type — 2.0 for `ASEPTIC_TASK`, 1.5 for
    `BODY_FLUID_RISK`, and 1.0 for `BEFORE_PATIENT_CONTACT`,
    `AFTER_PATIENT_CONTACT`, and `AFTER_SURROUNDINGS` — and divides the weighted
    sum over compliant observations by the weighted sum over all observations,
    multiplies by one hundred, and rounds once to one decimal half-up."

    Design: Difficulty/dual_variant_calc/hand_hygiene_simple_vs_weighted_on_unit
    """
    ctx = setup_unit_with_weighted_observations()
    rate = get_hh_rate(ctx["unit"]["id"], "2026-08")
    # compliant weight 15*1.0 + 8*2.0 + 7*1.5 = 41.5; total weight 55.0
    assert_approx_equal(rate["weighted_rate_pct"], 75.5, "weighted_rate_pct")
    assert rate["weighted_rate_pct"] != rate["simple_rate_pct"], (
        "the risk-adjusted variant must differ from the unweighted one here"
    )


# ---------------------------------------------------------------------------
# Aggregate-then-round ordering
# ---------------------------------------------------------------------------

def test_hand_hygiene_aggregates_month_then_rounds(api, ip_headers):
    """PRD §3.10: "Two variants are computed, always as month-level aggregates
    rounded once."
    PRD §3.10: "Computing per-week rounded rates and averaging them is not
    permitted; the aggregate-then-round order is pinned because the two orders
    yield different numbers."

    Design: Difficulty/combinatorial_formula/hand_hygiene_aggregate_then_round_beats_weekly_average
    """
    ctx = setup_unit_with_skewed_observation_weeks()
    rate = get_hh_rate(ctx["unit"]["id"], "2026-08", headers=ip_headers)
    assert rate["total_count"] == 36
    assert rate["compliant_count"] == 12
    # Aggregate-then-round: 100 * 12 / 36 = 33.33... -> 33.3
    assert_approx_equal(rate["simple_rate_pct"], 33.3, "simple_rate_pct")


def test_hand_hygiene_does_not_average_weekly_rounded_rates(api, ip_headers):
    """PRD §3.10: "Computing per-week rounded rates and averaging them is not
    permitted; the aggregate-then-round order is pinned because the two orders
    yield different numbers."
    PRD §3.10: "The simple rate, `simple_rate_pct`, is one hundred times
    `compliant_count` divided by `total_count`, rounded to one decimal place
    half-up."

    Design: Difficulty/combinatorial_formula/hand_hygiene_aggregate_then_round_beats_weekly_average
    """
    ctx = setup_unit_with_skewed_observation_weeks()
    rate = get_hh_rate(ctx["unit"]["id"], "2026-08", headers=ip_headers)
    # The forbidden weekly-rounded average: (round1(66.67) + round1(16.67)) / 2
    # = (66.7 + 16.7) / 2 = 41.7 — must NOT be what the endpoint returns.
    assert rate["simple_rate_pct"] != 41.7, (
        "per-week rounding then averaging is not permitted"
    )
    assert rate["reportable"] is True
    # With only BEFORE_PATIENT_CONTACT observations the weighted variant equals
    # the simple one, isolating the rounding order as the only variable.
    assert_approx_equal(rate["weighted_rate_pct"], rate["simple_rate_pct"],
                        "weighted_rate_pct")


# ---------------------------------------------------------------------------
# Reportability floor, pagination, immutability
# ---------------------------------------------------------------------------

def test_hand_hygiene_below_min_opportunities_not_reportable(
    api, director_headers, nurse_manager_headers
):
    """PRD §3.10: "The month is **reportable** — the response's `reportable`
    flag — only when `total_count` reaches the facility's
    `hh_min_opportunities`; below that floor both rates come back null."

    Design: Corner/calculations/hand_hygiene_below_min_opportunities_not_reportable
    """
    facility, unit = setup_facility_unit(unit_type="WARD")
    record_observation_batch(unit["id"], "2026-08-03", "08:00", 15,
                             "BEFORE_PATIENT_CONTACT", "COMPLIANT", step_minutes=10)
    record_observation_batch(unit["id"], "2026-08-03", "10:30", 14,
                             "BEFORE_PATIENT_CONTACT", "MISSED", step_minutes=10)
    rate = get_hh_rate(unit["id"], "2026-08", headers=director_headers)
    assert rate["total_count"] == 29
    assert rate["compliant_count"] == 15
    assert rate["reportable"] is False, "29 < the default floor of 30"
    assert rate["simple_rate_pct"] is None
    assert rate["weighted_rate_pct"] is None


def test_list_endpoints_paginate_with_defaults(api, nurse_manager_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_endpoints_paginate_with_defaults
    """
    facility, unit = setup_facility_unit(unit_type="WARD")
    record_observation_batch(unit["id"], "2026-08-03", "08:01", 12,
                             "BEFORE_PATIENT_CONTACT", "COMPLIANT", step_minutes=1)

    data, meta = validate_paginated(
        api.list_hand_hygiene_observations(
            nurse_manager_headers, params={"unit_id": unit["id"]}
        )
    )
    assert len(data) == 10, f"default page size must be 10, got {len(data)}"
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(
        api.list_hand_hygiene_observations(
            nurse_manager_headers,
            params={"unit_id": unit["id"], "limit": 5, "offset": 10},
        )
    )
    assert len(data2) == 2, f"limit=5&offset=10 over 12 rows yields 2, got {len(data2)}"
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False


def test_hand_hygiene_observation_is_immutable_event(api, nurse_manager_headers):
    """PRD §3.10: "Observations are immutable once recorded — no update or
    delete exists — and may be listed with `unit_id` or `month` filters, where
    month membership is by the UTC calendar date of `observed_at`."
    PRD §3.10: "The system stamps `observer_user_id` from the acting user."

    Design: Corner/entities/hand_hygiene_observation_is_immutable_event
    """
    facility, unit = setup_facility_unit(unit_type="WARD")
    observation = record_observation(
        unit["id"], "2026-08-03T08:00:00Z",
        opportunity_type="ASEPTIC_TASK", action="COMPLIANT",
    )
    assert_observation(observation)
    assert observation["unit_id"] == unit["id"]
    assert observation["opportunity_type"] == "ASEPTIC_TASK"
    assert observation["action"] == "COMPLIANT"
    assert_instant_equal(observation["observed_at"], "2026-08-03T08:00:00Z",
                         "observed_at")
    assert observation["observer_user_id"] == nurse_manager_headers["X-User-ID"]

    # No update endpoint exists for the resource; a write attempt cannot succeed.
    resp = api.put(
        f"/api/hand-hygiene-observations/{observation['id']}",
        json={"action": "MISSED"},
        headers=nurse_manager_headers,
    )
    assert resp.status_code in (404, 405), (
        f"no update endpoint may exist for observations, got {resp.status_code}"
    )
    reread = validate_success(
        api.get_hand_hygiene_observation(observation["id"], nurse_manager_headers)
    )
    assert reread["action"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# Employee exposure follow-up
# ---------------------------------------------------------------------------

def test_exposure_creation_seeds_baseline_due(api, health_nurse_headers):
    """PRD §3.11: "The new exposure starts in `REPORTED` with `recorded_stages`
    empty and `next_draw_due_at` set to `occurred_at` plus seventy-two hours —
    the baseline draw's due instant."
    PRD §2.6: "At startup, before any operator action, the logical clock reads
    exactly `2026-08-01T00:00:00Z`."
    PRD §3.11: "At read time, every exposure exposes `current_stage_overdue`:
    true exactly when the logical clock is later than `next_draw_due_at` and the
    exposure's status is one of `REPORTED`, `SOURCE_EVALUATED`,
    `BASELINE_COMPLETE`, or `FOLLOWUP_IN_PROGRESS`."

    Design: Corner/entities/exposure_creation_seeds_baseline_due
    """
    facility, unit = setup_facility_unit(unit_type="WARD")
    employee = create_employee(unit["id"])
    exposure = create_exposure(
        employee["id"],
        exposure_type="PERCUTANEOUS",
        occurred_at="2026-08-01T10:00:00Z",
        source_hbv_status="UNKNOWN",
        source_hcv_status="UNKNOWN",
        source_hiv_status="UNKNOWN",
    )
    assert exposure["status"] == "REPORTED"
    assert_instant_equal(
        exposure["next_draw_due_at"], "2026-08-04T10:00:00Z", "next_draw_due_at"
    )
    assert exposure["current_stage_overdue"] is False, (
        "the startup clock (2026-08-01T00:00:00Z) precedes the baseline due"
    )
    assert exposure["recorded_stages"] == []


def test_exposure_stage_order_enforced_and_baseline_window(api, health_nurse_headers):
    """PRD §3.11: "Recording the source serologies moves a `REPORTED` exposure
    to `SOURCE_EVALUATED`, updating the three source status fields from the
    payload; acting on an exposure in any other state is rejected with
    `ERR_EXPOSURE_INVALID_STAGE`."
    PRD §3.11: "The baseline draw requires `SOURCE_EVALUATED` status and must be
    drawn no later than seventy-two hours after `occurred_at`; a later baseline
    is `ERR_BASELINE_WINDOW_MISSED`."
    PRD §3.11: "Recording the baseline appends `{stage: BASELINE, drawn_at,
    result}` to `recorded_stages`, moves the exposure through
    `BASELINE_COMPLETE` and on into `FOLLOWUP_IN_PROGRESS` automatically, and
    sets `next_draw_due_at` to the week-six due instant, `occurred_at` plus
    forty-two days."

    Design: Corner/state_machines/exposure_stage_order_enforced_and_baseline_window
    """
    facility, unit = setup_facility_unit(unit_type="WARD")
    employee = create_employee(unit["id"])
    exposure = create_exposure(
        employee["id"], exposure_type="MUCOUS_MEMBRANE",
        occurred_at="2026-08-01T10:00:00Z",
    )

    resp_early_draw = api.record_draw(
        exposure["id"],
        {"stage": "BASELINE", "drawn_at": "2026-08-02T10:00:00Z", "result": "NEGATIVE"},
        health_nurse_headers,
    )
    validate_error(resp_early_draw, ApiErrorId.ERR_EXPOSURE_INVALID_STAGE)

    evaluated = record_source_serologies(
        exposure["id"], hbv="NEGATIVE", hcv="NEGATIVE", hiv="POSITIVE"
    )
    assert evaluated["status"] == "SOURCE_EVALUATED"
    assert evaluated["source_hiv_status"] == "POSITIVE"

    resp_skip = api.record_draw(
        exposure["id"],
        {"stage": "WEEK_6", "drawn_at": "2026-09-12T10:00:00Z", "result": "NEGATIVE"},
        health_nurse_headers,
    )
    validate_error(resp_skip, ApiErrorId.ERR_EXPOSURE_INVALID_STAGE)

    resp_late = api.record_draw(
        exposure["id"],
        {"stage": "BASELINE", "drawn_at": "2026-08-05T10:00:01Z", "result": "NEGATIVE"},
        health_nurse_headers,
    )
    validate_error(resp_late, ApiErrorId.ERR_BASELINE_WINDOW_MISSED)
    assert resp_late.status_code == 422

    accepted = record_draw(exposure["id"], "BASELINE", "2026-08-04T10:00:00Z")
    assert accepted["status"] == "FOLLOWUP_IN_PROGRESS", (
        "BASELINE_COMPLETE auto-advances to FOLLOWUP_IN_PROGRESS"
    )
    assert accepted["recorded_stages"][0]["stage"] == "BASELINE"
    assert_instant_equal(
        accepted["next_draw_due_at"], "2026-09-12T10:00:00Z", "next_draw_due_at"
    )


def test_exposure_lost_to_followup_overdue_threshold(api, health_nurse_headers,
                                                     admin_headers):
    """PRD §3.11: "When a follow-up stage has gone more than twenty-eight days
    past its due instant — the logical clock later than `next_draw_due_at` plus
    twenty-eight days — the nurse may mark the exposure lost to follow-up;
    attempting it earlier is `ERR_EXPOSURE_NOT_OVERDUE`, and attempting it from
    any status other than `FOLLOWUP_IN_PROGRESS` is `ERR_EXPOSURE_INVALID_STAGE`."
    PRD §3.11: "Marking lost lands the exposure in terminal `LOST_TO_FOLLOWUP`
    with `next_draw_due_at` null."

    Design: Corner/state_machines/exposure_lost_to_followup_overdue_threshold
    """
    ctx = setup_exposure_through_baseline()
    exposure_id = ctx["exposure"]["id"]
    # WEEK_6 due is 2026-09-12T10:00:00Z (occurred 2026-08-01T10:00 + 42d).
    set_clock("2026-10-10T10:00:00Z")  # exactly due + 28d
    resp_exact = api.mark_lost_to_followup(exposure_id, health_nurse_headers)
    validate_error(resp_exact, ApiErrorId.ERR_EXPOSURE_NOT_OVERDUE)

    set_clock("2026-10-10T10:00:01Z")  # due + 28d + 1s
    resp_late = api.mark_lost_to_followup(exposure_id, health_nurse_headers)
    lost = validate_success(resp_late)
    assert lost["status"] == "LOST_TO_FOLLOWUP"
    assert lost["next_draw_due_at"] is None


def test_exposure_draw_window_early_and_late(api, health_nurse_headers):
    """PRD §3.11: "Each follow-up stage has a due offset and an acceptance
    window: `WEEK_6` is due at forty-two days after `occurred_at`, `WEEK_12` at
    eighty-four days, and `WEEK_24` at one hundred sixty-eight days; a draw is
    accepted only when `drawn_at` falls no earlier than seven days before its
    due instant and no later than twenty-eight days after it, otherwise
    `ERR_DRAW_OUTSIDE_WINDOW`."
    PRD §3.11: "Recording `WEEK_6` or `WEEK_12` appends to `recorded_stages` and
    advances `next_draw_due_at` to the next stage's due instant; recording
    `WEEK_24` completes the protocol, landing the exposure in terminal
    `COMPLETED` with `next_draw_due_at` null."

    Design: Corner/validations/exposure_draw_window_early_and_late
    """
    ctx = setup_exposure_through_baseline(baseline_drawn_at="2026-08-02T10:00:00Z")
    exposure_id = ctx["exposure"]["id"]
    # WEEK_6 due 2026-09-12T10:00:00Z; window [2026-09-05T10:00, 2026-10-10T10:00].
    resp_early = api.record_draw(
        exposure_id,
        {"stage": "WEEK_6", "drawn_at": "2026-09-05T09:59:59Z", "result": "NEGATIVE"},
        health_nurse_headers,
    )
    validate_error(resp_early, ApiErrorId.ERR_DRAW_OUTSIDE_WINDOW)
    assert resp_early.status_code == 422

    accepted = record_draw(exposure_id, "WEEK_6", "2026-09-05T10:00:00Z")
    assert accepted["status"] == "FOLLOWUP_IN_PROGRESS"
    assert_instant_equal(
        accepted["next_draw_due_at"], "2026-10-24T10:00:00Z",
        "WEEK_12 due (occurred + 84d)",
    )
    assert len(accepted["recorded_stages"]) == 2
