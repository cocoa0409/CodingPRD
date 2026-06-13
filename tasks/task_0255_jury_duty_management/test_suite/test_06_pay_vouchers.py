"""Pay vouchers: the dual ESTIMATED-vs-FINAL variant, per-day mileage rounding,
and the opposite sum-then-round order of the pool projection.

Translates difficulty-design instances `dual_variant_calc /
pay_estimated_vs_final_on_summons`, `combinatorial_formula /
pay_mileage_round_per_day_then_sum`, and `combinatorial_formula /
pool_projection_sum_then_round` (queue A).
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    set_clock, create_term, add_juror, admin_qualify, open_term, draw,
    submit_qualifying_questionnaire, check_in, create_ready_trial, create_panel,
    seat, get_panel,
)

_ADMIN = TEST_USERS["jury_administrator_headers"]
_CLERK = TEST_USERS["court_clerk_headers"]


def _qualified_reporting_summons(term, juror, report_open_version):
    summons = draw(term["id"], report_open_version, count=1)[0]
    submit_qualifying_questionnaire(summons["id"], juror["id"])
    return summons


def _vouchers(api, summons_id):
    return validate_success(api.list_pay_vouchers(summons_id, _CLERK))


# ─── Difficulty: ESTIMATED vs FINAL ────────────────────────────────────

def _build_estimated_then_final(api, term_name):
    set_clock("2026-07-01T08:00:00Z")
    term = create_term(name=term_name, report_date="2026-07-01T00:00:00Z",
                       daily_pay_cents=4000, half_day_pay_cents=2000, full_day_hours=6.0,
                       mileage_rate_cents=25, pay_day_cap=3)
    juror = add_juror(term["id"], full_name="Ada J", birth_year=1980, round_trip_miles=2.50)
    admin_qualify(juror["id"])
    open_v = open_term(term["id"])["version"]
    summons = _qualified_reporting_summons(term, juror, open_v)
    # Two check-ins before seating (FULL 8.0, HALF 5.0).
    check_in(summons["id"], "2026-07-01T00:00:00Z", 8.0)
    check_in(summons["id"], "2026-07-02T00:00:00Z", 5.0)
    trial = create_ready_trial(term["id"], required_jurors=1, caption="State v. X")
    panel = create_panel(trial["id"], target_size=1)
    seat(panel["id"], summons["id"], panel["version"])  # 1-seat panel fills → ESTIMATED voucher
    # Two more check-ins after seating.
    check_in(summons["id"], "2026-07-03T00:00:00Z", 7.0)
    check_in(summons["id"], "2026-07-04T00:00:00Z", 9.0)
    return term, juror, summons


def test_estimated_voucher_counts_only_pre_seating_checkins(api):
    """PRD §3.8: "The `ESTIMATED` voucher is issued when a panel fills (the
    `FORMING` to `SEATED` transition). Its eligible check-ins are all those recorded
    up to the seating instant; because the venire has not finished serving, any days
    accrued after seating are not in this voucher."

    Design: Difficulty/dual_variant_calc/pay_estimated_vs_final_on_summons
    """
    term, juror, summons = _build_estimated_then_final(api, "T1")
    api.release_summons(summons["id"], _CLERK)  # issues FINAL alongside the existing ESTIMATED
    vouchers = _vouchers(api, summons["id"])
    estimated = [v for v in vouchers if v["variant"] == "ESTIMATED"]
    assert len(estimated) == 1, f"exactly one ESTIMATED voucher expected, got {len(estimated)}"
    assert estimated[0]["total_cents"] == 6126, (
        f"ESTIMATED total must be 6126 (attendance 6000 + mileage 126), got {estimated[0]['total_cents']}"
    )


def test_final_voucher_recounts_all_checkins_and_exceeds_estimated(api):
    """PRD §3.8: "The `FINAL` voucher is issued at release. Its eligible check-ins
    are all check-ins on the summons through release, so `paid_days` is recounted
    and recapped over the full set. Whenever post-seating service days exist, the
    final total is at least as large as the estimated total."

    Design: Difficulty/dual_variant_calc/pay_estimated_vs_final_on_summons
    """
    term, juror, summons = _build_estimated_then_final(api, "T1b")
    api.release_summons(summons["id"], _CLERK)
    vouchers = _vouchers(api, summons["id"])
    final = [v for v in vouchers if v["variant"] == "FINAL"]
    estimated = [v for v in vouchers if v["variant"] == "ESTIMATED"]
    assert len(final) == 1, f"exactly one FINAL voucher expected, got {len(final)}"
    assert final[0]["total_cents"] == 10189, (
        f"FINAL total must be 10189 (attendance 10000 + mileage 189), got {final[0]['total_cents']}"
    )
    assert final[0]["total_cents"] > estimated[0]["total_cents"], (
        "FINAL must exceed ESTIMATED when post-seating service days exist"
    )
    assert final[0]["total_cents"] - estimated[0]["total_cents"] == 4063


# ─── Difficulty: per-day mileage rounding (round-per-day-then-sum) ─────

def _build_three_full_days(api, term_name):
    set_clock("2026-08-01T08:00:00Z")
    term = create_term(name=term_name, report_date="2026-08-01T00:00:00Z",
                       daily_pay_cents=4000, half_day_pay_cents=2000, full_day_hours=6.0,
                       mileage_rate_cents=25, pay_day_cap=3)
    juror = add_juror(term["id"], full_name="Cyd J", birth_year=1979, round_trip_miles=2.50)
    admin_qualify(juror["id"])
    open_v = open_term(term["id"])["version"]
    summons = _qualified_reporting_summons(term, juror, open_v)
    check_in(summons["id"], "2026-08-01T00:00:00Z", 8.0)
    check_in(summons["id"], "2026-08-02T00:00:00Z", 8.0)
    check_in(summons["id"], "2026-08-03T00:00:00Z", 8.0)
    return summons


def test_final_mileage_rounds_per_day_then_sums(api):
    """PRD §3.8: "Mileage follows a pinned rounding order: the per-day mileage is the
    juror's `round_trip_miles` multiplied by the term's `mileage_rate_cents`, rounded
    half-up to whole cents once per day; the `mileage_cents` is that per-day mileage
    multiplied by `paid_days`. Mileage is rounded per counted day and then summed —
    never summed first and rounded once."

    Design: Difficulty/combinatorial_formula/pay_mileage_round_per_day_then_sum
    """
    summons = _build_three_full_days(api, "T3")
    api.release_summons(summons["id"], _CLERK)
    final = [v for v in _vouchers(api, summons["id"]) if v["variant"] == "FINAL"][0]
    # round_half_up(2.50*25)=63 per day * 3 days = 189 (NOT round(2.50*3*25)=188).
    assert final["mileage_cents"] == 189, (
        f"per-day rounding must yield 189, got {final['mileage_cents']}"
    )


def test_final_attendance_and_total_for_three_full_days(api):
    """PRD §3.8: "Each counted check-in contributes day pay according to its
    `day_kind`: a `FULL` day contributes the term's `daily_pay_cents` and a `HALF`
    day contributes the term's `half_day_pay_cents`. The `attendance_cents` is the
    sum of day pay over the counted check-ins ... Finally, `total_cents` is
    `attendance_cents` plus `mileage_cents`."

    Design: Difficulty/combinatorial_formula/pay_mileage_round_per_day_then_sum
    """
    summons = _build_three_full_days(api, "T3b")
    api.release_summons(summons["id"], _CLERK)
    final = [v for v in _vouchers(api, summons["id"]) if v["variant"] == "FINAL"][0]
    assert final["attendance_cents"] == 12000, (
        f"3 full days * 4000 must be 12000, got {final['attendance_cents']}"
    )
    assert final["total_cents"] == 12189, f"total must be 12189, got {final['total_cents']}"


# ─── Difficulty: pool projection (sum-then-round, opposite order) ──────

def _build_pool_for_projection(api, term_name):
    term = create_term(name=term_name, report_date="2026-09-01T00:00:00Z",
                       daily_pay_cents=4000, half_day_pay_cents=2000, full_day_hours=6.0,
                       mileage_rate_cents=25, pay_day_cap=3)
    j1 = add_juror(term["id"], full_name="D1", birth_year=1980, round_trip_miles=2.50)
    j2 = add_juror(term["id"], full_name="D2", birth_year=1981, round_trip_miles=2.50)
    j3 = add_juror(term["id"], full_name="D3", birth_year=1982, round_trip_miles=1.50)
    for j in (j1, j2, j3):
        admin_qualify(j["id"])
    return term


def test_pool_projection_sums_miles_then_rounds_once(api):
    """PRD §3.2: "the server first sums the raw `round_trip_miles` across the
    eligible pool ... multiplies that pooled mileage total by `pay_day_cap`,
    multiplies the result by `mileage_rate_cents`, and only then rounds the single
    product half-up to whole cents."

    Design: Difficulty/combinatorial_formula/pool_projection_sum_then_round
    """
    term = _build_pool_for_projection(api, "T4")
    data = validate_success(api.pool_projection(term["id"], _ADMIN))
    # round_half_up((2.50+2.50+1.50)*3*25) = round(6.50*3*25) = round(487.5) = 488
    # (per-juror-then-sum would give 492 — the single terminal rounding is observable).
    assert data["projected_mileage_cents"] == 488, (
        f"sum-then-round must yield 488, got {data['projected_mileage_cents']}"
    )


def test_pool_projection_reports_pool_size(api):
    """PRD §3.2: "The response reports this `projected_mileage_cents` alongside the
    current `pool_size`."

    Design: Difficulty/combinatorial_formula/pool_projection_sum_then_round
    """
    term = _build_pool_for_projection(api, "T4b")
    data = validate_success(api.pool_projection(term["id"], _ADMIN))
    assert data["pool_size"] == 3, f"three qualified jurors must report pool_size 3, got {data['pool_size']}"
