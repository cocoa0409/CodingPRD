"""Per-diem policies, rounding order, ranges, uniqueness, payment (PRD §2.8, §3.6)."""
from test_helpers import (
    ApiErrorId,
    COMPANY_MANAGER,
    create_contracted_member,
    create_tour,
    issue_per_diem,
    pay_per_diem,
    setup_ready_stop,
    validate_error,
    validate_success,
)


def test_per_diem_full_week_variant(api):
    """PRD §3.6: "Under `FULL_WEEK`, the statement pays seven times the daily
    rate regardless of `days_present` or `travel_days`."
    PRD §3.6: "At creation the statement snapshots the tour’s policy into `policy_snapshot` and the tour’s daily rate into `daily_rate_cents`, so later changes to tour configuration never rewrite issued statements."

    Design: Difficulty/dual_variant_calc/per_diem_full_week_vs_actual_days
    """
    ctx = setup_ready_stop(tour_overrides={"per_diem_policy": "FULL_WEEK",
                                           "per_diem_daily_cents": 20_000})
    member = create_contracted_member(ctx["tour"]["id"], name="Pat Principal")

    pd = issue_per_diem(ctx["stop"]["id"], member["id"], days_present=5,
                        travel_days=2)
    assert pd["policy_snapshot"] == "FULL_WEEK"
    assert pd["daily_rate_cents"] == 20_000
    # FULL_WEEK ignores days/travel entirely: 7 x 20,000.
    assert pd["total_cents"] == 140_000


def test_per_diem_actual_days_variant(api):
    """PRD §3.6: "Under `ACTUAL_DAYS`, the half-day rate is computed first — the
    daily rate divided by two, rounded half-up to whole cents — and the statement
    pays the non-travel days (`days_present` minus `travel_days`) at the full
    daily rate plus the `travel_days` at that rounded half rate."
    PRD §3.6: "The two variants agree only when the member was present all seven
    days with no travel days."

    Design: Difficulty/dual_variant_calc/per_diem_full_week_vs_actual_days
    """
    ctx = setup_ready_stop(tour_overrides={"per_diem_policy": "ACTUAL_DAYS",
                                           "per_diem_daily_cents": 20_000})
    member = create_contracted_member(ctx["tour"]["id"], name="Alex Actor")

    pd = issue_per_diem(ctx["stop"]["id"], member["id"], days_present=5,
                        travel_days=2)
    assert pd["policy_snapshot"] == "ACTUAL_DAYS"
    assert pd["daily_rate_cents"] == 20_000
    # 3 full days x 20,000 + 2 travel days x 10,000.
    assert pd["total_cents"] == 80_000


def test_per_diem_half_day_rounding_pinned(api):
    """PRD §3.6: "Under `ACTUAL_DAYS`, the half-day rate is computed first — the
    daily rate divided by two, rounded half-up to whole cents — and the statement
    pays the non-travel days (`days_present` minus `travel_days`) at the full
    daily rate plus the `travel_days` at that rounded half rate."

    Design: Difficulty/combinatorial_formula/per_diem_half_day_rounding_order_mode_b
    """
    ctx = setup_ready_stop(tour_overrides={"per_diem_policy": "ACTUAL_DAYS",
                                           "per_diem_daily_cents": 20_115})
    member = create_contracted_member(ctx["tour"]["id"], name="Sam Swing",
                                      contract_type="SWING", weekly_salary_cents=400_000)

    pd = issue_per_diem(ctx["stop"]["id"], member["id"], days_present=7,
                        travel_days=2)
    # Half rate rounded FIRST: round_half_up(20,115 / 2) = 10,058.
    # 5 x 20,115 + 2 x 10,058 = 100,575 + 20,116 = 120,691.
    # The sum-then-round reading (round(2 x 20,115 / 2) = 20,115) yields 120,690.
    assert pd["total_cents"] == 120_691
    assert pd["total_cents"] != 120_690


def test_per_diem_half_day_rounding_single_travel_day(api):
    """PRD §3.6: "Under `ACTUAL_DAYS`, the half-day rate is computed first — the
    daily rate divided by two, rounded half-up to whole cents — and the statement
    pays the non-travel days (`days_present` minus `travel_days`) at the full
    daily rate plus the `travel_days` at that rounded half rate."

    Design: Difficulty/combinatorial_formula/per_diem_half_day_rounding_order_mode_b
    """
    ctx = setup_ready_stop(tour_overrides={"per_diem_policy": "ACTUAL_DAYS",
                                           "per_diem_daily_cents": 20_115})
    member = create_contracted_member(ctx["tour"]["id"], name="Sam Swing",
                                      contract_type="SWING", weekly_salary_cents=400_000)

    pd = issue_per_diem(ctx["stop"]["id"], member["id"], days_present=7,
                        travel_days=1)
    # 6 x 20,115 + 1 x 10,058 = 120,690 + 10,058 = 130,748.
    assert pd["total_cents"] == 130_748


def test_per_diem_range_returns_per_diem_invalid(api):
    """PRD §2.8: "a per-diem statement whose `days_present` falls outside 1 to 7
    or whose `travel_days` exceeds the smaller of 2 and `days_present` is
    rejected with `ERR_PER_DIEM_INVALID` (HTTP 400)"

    Design: Corner/validations/per_diem_range_returns_per_diem_invalid
    """
    ctx = setup_ready_stop()
    member = create_contracted_member(ctx["tour"]["id"], name="Pat P")

    resp1 = api.create_per_diem(ctx["stop"]["id"],
                                {"cast_member_id": member["id"], "days_present": 8,
                                 "travel_days": 0}, COMPANY_MANAGER)
    validate_error(resp1, ApiErrorId.ERR_PER_DIEM_INVALID)

    resp2 = api.create_per_diem(ctx["stop"]["id"],
                                {"cast_member_id": member["id"], "days_present": 5,
                                 "travel_days": 3}, COMPANY_MANAGER)
    validate_error(resp2, ApiErrorId.ERR_PER_DIEM_INVALID)


def test_duplicate_per_diem_returns_duplicate_record(api):
    """PRD §3.6: "At most one statement may exist per stop and cast member; a
    second issue for the same pair is `ERR_DUPLICATE_RECORD`."

    Design: Corner/validations/duplicate_per_diem_returns_duplicate_record
    """
    ctx = setup_ready_stop()
    member = create_contracted_member(ctx["tour"]["id"], name="Pat P")
    issue_per_diem(ctx["stop"]["id"], member["id"], days_present=7, travel_days=0)

    resp = api.create_per_diem(ctx["stop"]["id"],
                               {"cast_member_id": member["id"], "days_present": 5,
                                "travel_days": 1}, COMPANY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECORD)


def test_perdiem_double_pay_returns_invalid_state(api):
    """PRD §3.6: "A statement is `ISSUED` on creation; the `CompanyManager` later
    marks it `PAID`, a transition legal only from `ISSUED` — paying a statement
    not in `ISSUED` is `ERR_PER_DIEM_INVALID_STATE`."

    Design: Corner/state_machines/perdiem_double_pay_returns_invalid_state
    """
    ctx = setup_ready_stop()
    member = create_contracted_member(ctx["tour"]["id"], name="Pat P")
    pd = issue_per_diem(ctx["stop"]["id"], member["id"], days_present=7,
                        travel_days=0)
    assert pd["status"] == "ISSUED"
    pay_per_diem(pd["id"])

    resp = api.put_per_diem(pd["id"], {"status": "PAID"}, COMPANY_MANAGER)
    validate_error(resp, ApiErrorId.ERR_PER_DIEM_INVALID_STATE)
