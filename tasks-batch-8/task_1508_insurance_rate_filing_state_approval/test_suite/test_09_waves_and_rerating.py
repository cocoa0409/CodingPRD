"""Implementation waves: scheduling rules, re-rating, capping, and book-level
balancing (PRD §2.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_pct,
    create_wave,
    create_wave_payload,
    find_calendar_entry,
    get_success_data,
    set_clock,
    setup_approved_filing,
    setup_effective_filing,
    setup_released_wave,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

ROUNDING_POLICIES = [
    ("CA-5001", 50_001, 1.0, "2026-11-20"),
    ("CA-5002", 50_001, 2.0, "2026-11-25"),
    ("CA-5003", 150_000, 1.5, "2026-11-30"),
]
BALANCE_POLICIES = [
    ("CA-1001", 100_000, 1.0, "2026-11-20"),
    ("CA-1002", 200_000, 2.0, "2026-11-25"),
]
CAP_BOUNDARY_POLICIES = [
    ("CA-2001", 100_000, 1.5, "2026-11-20"),
    ("CA-2002", 100_000, 1.51, "2026-11-25"),
]


# ─── Per-policy re-rate rounding (renewal_re_rate) ──────────────────

def test_per_policy_premium_rounding_half_up(api):
    """PRD §2.6: "Rounding order is pinned throughout the renewal pipeline:
    every per-policy premium is rounded to whole cents before any book-level
    aggregation, and the system never aggregates first and rounds afterward."
    PRD §3.7: "the uncapped new premium `raw_new_premium_cents` is
    `current_premium_cents` multiplied by one plus `raw_change_pct`, rounded
    half up to a whole cent."

    Design: Difficulty/combinatorial_formula/renewal_re_rate_per_policy_rounding_order
    """
    scenario = setup_released_wave(policies=ROUNDING_POLICIES[:2])
    pa, pb = (fx.refresh_policy(p["id"]) for p in scenario["policies"])

    # 50001 * 1.10 = 55001.1 -> 55001 at the policy row (round half up).
    assert_pct(pa["raw_change_pct"], 0.1)
    assert pa["raw_new_premium_cents"] == 55001
    # 50001 * 1.20 = 60001.2 -> 60001.
    assert_pct(pb["raw_change_pct"], 0.2)
    assert pb["raw_new_premium_cents"] == 60001


def test_exact_product_rounding_and_wave_assignment(api):
    """PRD §3.7: "Each remaining in-scope policy moves to `RATED` in one
    motion: `baseline_premium_cents` snapshots the `current_premium_cents`,
    the policy is re-rated (below), its `wave_id` is set".

    Design: Difficulty/combinatorial_formula/renewal_re_rate_per_policy_rounding_order
    """
    scenario = setup_released_wave(policies=[ROUNDING_POLICIES[2]])
    wave = scenario["wave"]
    pc = fx.refresh_policy(scenario["policies"][0]["id"])

    # 150000 * 1.15 = 172500 exactly.
    assert_pct(pc["raw_change_pct"], 0.15)
    assert pc["raw_new_premium_cents"] == 172500
    assert pc["status"] == "RATED"
    assert pc["wave_id"] == wave["id"]
    assert pc["baseline_premium_cents"] == 150_000


# ─── Book-level balancing (wave_balance_factor) ─────────────────────

def test_wave_balance_factor_pinned_evaluation_order(api):
    """PRD §3.7: "With every capped premium known, the wave's
    `target_book_delta_cents` is computed as `approved_change_pct` multiplied
    by the sum of `baseline_premium_cents` across the rated set, rounded half
    up to a whole cent. The capped book total is formed as the sum of baselines
    plus the sum of each policy's capped premium minus its baseline. The
    `balance_factor` is then the sum of baselines plus
    `target_book_delta_cents`, divided by that capped book total, stored at
    eight decimal places rounded half up."

    Design: Difficulty/combinatorial_formula/wave_balance_factor_pinned_evaluation_order
    """
    scenario = setup_released_wave(policies=BALANCE_POLICIES)
    wave = scenario["wave"]

    # target = 0.10 * 300000 = 30000; capped total = 110000 + 230000 = 340000.
    assert wave["target_book_delta_cents"] == 30000
    # balance_factor = 330000 / 340000 = 0.9705882352... -> 0.97058824 (8dp)
    assert wave["balance_factor"] == 0.97058824
    assert wave["final_book_delta_cents"] == 30000


def test_balanced_final_premiums_per_policy(api):
    """PRD §3.7: "Each policy's `final_premium_cents` is its capped premium
    multiplied by `balance_factor`, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/wave_balance_factor_pinned_evaluation_order
    """
    scenario = setup_released_wave(policies=BALANCE_POLICIES)
    p1, p2 = (fx.refresh_policy(p["id"]) for p in scenario["policies"])

    # 110000 * 0.97058824 = 106764.7064 -> 106765
    assert p1["was_capped"] is False
    assert p1["final_premium_cents"] == 106765
    # 200000 * 1.2 = raw 0.2 > cap 0.15 -> capped to 230000;
    # 230000 * 0.97058824 = 223235.2952 -> 223235
    assert p2["was_capped"] is True
    assert p2["final_premium_cents"] == 223235


# ─── Disruption cap boundary ────────────────────────────────────────

def test_raw_change_equal_to_cap_is_not_capped(api):
    """PRD §3.7: "Capping triggers only on strict inequality: when
    `raw_change_pct` is strictly greater than the wave's `cap_pct`, the capped
    premium becomes `current_premium_cents` multiplied by one plus `cap_pct`,
    rounded half up to a whole cent, and `was_capped` is set true".
    PRD §3.7: "A raw change exactly equal to the cap, in either direction, is
    not capped."

    Design: Difficulty/boundary_precision_check/cap_boundary_raw_equals_cap_not_capped
    """
    scenario = setup_released_wave(policies=[CAP_BOUNDARY_POLICIES[0]])
    p_at = fx.refresh_policy(scenario["policies"][0]["id"])

    # raw 0.10 * 1.5 = 0.1500 == cap 0.15: not capped.
    assert_pct(p_at["raw_change_pct"], 0.15)
    assert p_at["was_capped"] is False
    assert p_at["raw_new_premium_cents"] == 115000


def test_raw_change_one_tick_above_cap_is_capped(api):
    """PRD §3.7: "when `raw_change_pct` is strictly greater than the wave's
    `cap_pct`, the capped premium becomes `current_premium_cents` multiplied by
    one plus `cap_pct`, rounded half up to a whole cent, and `was_capped` is
    set true".

    Design: Difficulty/boundary_precision_check/cap_boundary_raw_equals_cap_not_capped
    """
    scenario = setup_released_wave(policies=CAP_BOUNDARY_POLICIES)
    p_at, p_over = (fx.refresh_policy(p["id"]) for p in scenario["policies"])

    # raw 0.1510 > cap 0.15: capped to 100000 * 1.15 = 115000.
    assert_pct(p_over["raw_change_pct"], 0.151)
    assert p_over["was_capped"] is True
    assert p_over["raw_new_premium_cents"] == 115100

    # Book balancing over {115000, 115000}: target 20000, capped total 230000.
    wave = scenario["wave"]
    assert wave["balance_factor"] == 0.95652174  # 220000 / 230000
    assert p_at["final_premium_cents"] == 110000
    assert p_over["final_premium_cents"] == 110000


# ─── Book premium conservation (compensating invariant) ─────────────

def test_conservation_book_delta_equals_target(api):
    """PRD §3.7: "after this allocation the sum of per-policy deltas equals
    `target_book_delta_cents` exactly, and that realized sum is recorded as
    `final_book_delta_cents`."

    Design: Difficulty/compensating_invariant/capped_book_premium_conservation
    """
    scenario = setup_released_wave(policies=ROUNDING_POLICIES)
    wave = scenario["wave"]

    # target = round(0.10 * 250002) = 25000; bf = 275002/285002 -> 0.96491253
    assert wave["target_book_delta_cents"] == 25000
    assert wave["balance_factor"] == 0.96491253
    assert wave["final_book_delta_cents"] == 25000
    assert wave["final_book_delta_cents"] == wave["target_book_delta_cents"]


def test_residual_penny_allocated_to_largest_baseline(api):
    """PRD §3.7: "Finally, the residual — `target_book_delta_cents` minus the
    sum over the rated set of each policy's `final_premium_cents` minus its
    baseline — is allocated in full, sign included, to the single policy
    holding the largest `baseline_premium_cents`, with ties broken in favor of
    the policy created earliest".

    Design: Difficulty/compensating_invariant/capped_book_premium_conservation
    """
    scenario = setup_released_wave(policies=ROUNDING_POLICIES)
    pa, pb, pc = (fx.refresh_policy(p["id"]) for p in scenario["policies"])

    assert pa["final_premium_cents"] == 53071   # 55001 * 0.96491253 -> 53071
    assert pb["final_premium_cents"] == 55483   # 57501 * 0.96491253 -> 55483
    # Largest baseline (150000) absorbs the +1 cent residual: 166447 + 1.
    assert pc["final_premium_cents"] == 166448
    deltas = (
        (53071 - 50001) + (55483 - 50001) + (166448 - 150000)
    )
    assert deltas == 25000


# ─── Release gating on filing state ─────────────────────────────────

def test_wave_release_blocked_until_filing_effective(api):
    """PRD §3.7: "Release is the atomic heart of implementation and is
    permitted only once the parent filing is `EFFECTIVE` — an attempt against
    a filing in any other state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/wave_release_blocked_until_filing_effective
    """
    scenario = setup_approved_filing(approve_at="2026-09-01T00:00:00Z")
    wave = create_wave(scenario["filing"]["id"])
    assert wave["status"] == "SCHEDULED"

    res = api.release_wave(wave["id"], fx.LEAD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert fx.refresh_wave(wave["id"])["status"] == "SCHEDULED"


def test_wave_release_succeeds_once_filing_effective(api):
    """PRD §3.7: "Release is the atomic heart of implementation and is
    permitted only once the parent filing is `EFFECTIVE`".
    PRD §3.7: "Should a release find no in-scope policies at all, the
    `balance_factor` stays null and both book deltas record zero; the release
    still succeeds and the wave stands `RELEASED`."

    Design: Difficulty/cross_entity_state_dependency/wave_release_blocked_until_filing_effective
    """
    scenario = setup_approved_filing(approve_at="2026-09-01T00:00:00Z")
    wave = create_wave(scenario["filing"]["id"])

    blocked = api.release_wave(wave["id"], fx.LEAD)
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

    set_clock("2026-10-16T00:00:00Z")
    get_success_data(api.mark_filing_effective(scenario["filing"]["id"], fx.OFFICER))
    released = validate_success(api.release_wave(wave["id"], fx.LEAD), 200)
    assert released["status"] == "RELEASED"
    assert released["rated_policy_count"] == 0
    assert released["balance_factor"] is None
    assert released["target_book_delta_cents"] == 0
    assert released["final_book_delta_cents"] == 0


# ─── Wave window gap rule ───────────────────────────────────────────

def test_wave_gap_of_exactly_seven_days_violates(api):
    """PRD §3.7: "considering only existing waves of the same product and state
    in `SCHEDULED`, `RELEASED`, or `COMPLETED` — `CANCELLED` and `REVERSED`
    waves impose no constraint — the new window must either begin more than
    seven days after the existing wave's end or end more than seven days before
    the existing wave's start; a separation of exactly seven days is a
    violation, while eight days is acceptable, and a breach is rejected with
    `ERR_WAVE_GAP_VIOLATION` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/wave_window_gap_buffer_boundary
    """
    scenario = setup_effective_filing()
    create_wave(scenario["filing"]["id"])  # [2026-11-16, 2026-12-15]

    # Start 2026-12-22 is exactly 7 days after 2026-12-15: violation.
    res = api.create_wave(
        create_wave_payload(
            scenario["filing"]["id"],
            wave_start_date="2026-12-22",
            wave_end_date="2027-01-10",
        ),
        fx.LEAD,
    )
    validate_error(res, ApiErrorId.ERR_WAVE_GAP_VIOLATION)


def test_wave_gap_of_eight_days_allowed(api):
    """PRD §3.7: "a separation of exactly seven days is a violation, while
    eight days is acceptable".

    Design: Difficulty/resource_temporal_overlap/wave_window_gap_buffer_boundary
    """
    scenario = setup_effective_filing()
    create_wave(scenario["filing"]["id"])  # [2026-11-16, 2026-12-15]

    wave = validate_success(
        api.create_wave(
            create_wave_payload(
                scenario["filing"]["id"],
                wave_start_date="2026-12-23",
                wave_end_date="2027-01-10",
            ),
            fx.LEAD,
        ),
        201,
    )
    assert wave["status"] == "SCHEDULED"


# ─── Release input-set filtering ────────────────────────────────────

def test_release_rates_only_in_window_policies(api):
    """PRD §3.7: "On release, the wave claims its scope: every `PENDING` policy
    of the same product and state whose `renewal_effective_date` falls within
    the wave window, both bounds inclusive, comes in scope."

    Design: Corner/calculations/release_input_set_filtering
    """
    scenario = setup_released_wave(
        policies=[
            ("CA-7001", 100_000, 1.0, "2026-11-20"),
            ("CA-7002", 100_000, 1.0, "2027-01-05"),
        ]
    )
    p_in, p_out = (fx.refresh_policy(p["id"]) for p in scenario["policies"])

    assert p_in["status"] == "RATED"
    assert p_in["wave_id"] == scenario["wave"]["id"]

    # 2027-01-05 lies outside the inclusive [2026-11-16, 2026-12-15] window.
    assert p_out["status"] == "PENDING"
    assert p_out["wave_id"] is None
    assert p_out["raw_change_pct"] is None
    assert scenario["wave"]["rated_policy_count"] == 1


def test_release_excludes_policy_past_notice_due(api):
    """PRD §3.7: "if the release date is already past a policy's
    `notice_due_date`, timely notice is impossible by construction, so the
    policy stays `PENDING`, its `exclusion_reason` is set to
    `LATE_NOTICE_BY_CONSTRUCTION`, and the wave's `excluded_late_notice_count`
    increments."
    PRD §3.7: "Should a release find no in-scope policies at all, the
    `balance_factor` stays null and both book deltas record zero; the release
    still succeeds and the wave stands `RELEASED`."

    Design: Corner/calculations/release_excludes_late_notice_by_construction
    """
    # Renewal 2026-11-10 with 30 notice days -> notice_due 2026-10-11, already
    # past when the wave releases at the 2026-10-16 effectiveness clock.
    scenario = setup_released_wave(
        policies=[("CA-7003", 100_000, 1.0, "2026-11-10")],
        wave_start_date="2026-11-01",
        wave_end_date="2026-11-30",
    )
    wave = scenario["wave"]
    policy = fx.refresh_policy(scenario["policies"][0]["id"])

    assert wave["status"] == "RELEASED"
    assert wave["rated_policy_count"] == 0
    assert wave["excluded_late_notice_count"] == 1
    assert wave["balance_factor"] is None
    assert policy["status"] == "PENDING"
    assert policy["exclusion_reason"] == "LATE_NOTICE_BY_CONSTRUCTION"


def test_disruption_analysis_empty_wave(api):
    """PRD §3.7: "A wave with no rated policies reports zero counts and null
    averages and extrema."

    Design: Corner/calculations/disruption_analysis_empty_wave
    """
    scenario = setup_approved_filing(approve_at="2026-09-01T00:00:00Z")
    wave = create_wave(scenario["filing"]["id"])

    summary = validate_success(
        api.get_disruption_analysis(wave["id"], fx.LEAD), 200
    )
    assert summary["total_policies"] == 0
    assert summary["capped_policy_count"] == 0
    assert summary["max_raw_change_pct"] is None
    assert summary["min_raw_change_pct"] is None
    assert summary["book_avg_raw_change_pct"] is None
    assert summary["book_avg_final_change_pct"] is None
    assert summary["balance_factor"] is None


# ─── Wave scheduling validations ────────────────────────────────────

def test_wave_cap_above_regulatory_max_rejected(api):
    """PRD §3.7: "The disruption cap faces the state's ceiling: a `cap_pct`
    above the profile's `max_single_change_pct` is refused with
    `ERR_CAP_ABOVE_REGULATORY_MAX` (HTTP 422)."

    Design: Corner/validations/cap_above_regulatory_max_rejected
    """
    scenario = setup_effective_filing()
    res = api.create_wave(
        create_wave_payload(scenario["filing"]["id"], cap_pct=0.30), fx.LEAD
    )
    validate_error(res, ApiErrorId.ERR_CAP_ABOVE_REGULATORY_MAX)


def test_wave_window_end_before_start_rejected(api):
    """PRD §3.7: "Scheduling validates the window's shape (an end before the
    start is rejected with `ERR_WAVE_WINDOW_INVALID`, HTTP 422)".

    Design: Corner/validations/wave_window_end_before_start_rejected
    """
    scenario = setup_effective_filing()
    res = api.create_wave(
        create_wave_payload(
            scenario["filing"]["id"],
            wave_start_date="2026-11-16",
            wave_end_date="2026-11-01",
        ),
        fx.LEAD,
    )
    validate_error(res, ApiErrorId.ERR_WAVE_WINDOW_INVALID)


def test_wave_cancel_frees_window(api):
    """PRD §3.7: "The lead may cancel a scheduled wave, moving it to
    `CANCELLED` and waiving its window entry."
    PRD §3.7: "considering only existing waves of the same product and state in
    `SCHEDULED`, `RELEASED`, or `COMPLETED` — `CANCELLED` and `REVERSED` waves
    impose no constraint".

    Design: Corner/state_machines/wave_cancel_releases_window
    """
    scenario = setup_effective_filing()
    wave = create_wave(scenario["filing"]["id"])  # [2026-11-16, 2026-12-15]

    cancelled = validate_success(api.cancel_wave(wave["id"], fx.LEAD), 200)
    assert cancelled["status"] == "CANCELLED"
    entry = find_calendar_entry(wave_id=wave["id"], entry_type="WAVE_WINDOW")
    assert entry["status"] == "WAIVED"

    # A new wave fully inside the cancelled window is accepted.
    successor = validate_success(
        api.create_wave(
            create_wave_payload(
                scenario["filing"]["id"],
                wave_start_date="2026-11-20",
                wave_end_date="2026-12-10",
            ),
            fx.LEAD,
        ),
        201,
    )
    assert successor["status"] == "SCHEDULED"
