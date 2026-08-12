"""Affidavit issuance: reprice-policy dual variants, supersede cascade, and
pinned per-line rounding order (PRD §3.2, §3.8)."""
from test_helpers import (
    BA,
    TD,
    ApiErrorId,
    book_spot_ok,
    create_active_order,
    create_locked_log,
    create_published_book,
    get_success_data,
    import_as_run_ok,
    make_billing_admin_headers,
    make_headers,
    reconcile_log_as,
    setup_bookable_station,
    validate_success,
)


# ---------------------------------------------------------------------------
# LOCKED_AT_BOOKING vs REPRICED_AT_AFFIDAVIT across a mid-flight book change
# ---------------------------------------------------------------------------

def _setup_locked_vs_repriced_env():
    """Winter book (share 3.0) PUBLISHED; two CASH FIXED orders (LOCKED vs
    REPRICED), one spot each at hour 6 on the 2026-05-04 log; Spring book
    (share 5.0) then published, superseding Winter; both spots imported AIRED;
    log RECONCILED by td-1."""
    env = setup_bookable_station(
        weekday="MON", daypart="MORNING_DRIVE", hour=6,
        base_rate_cents=10000, min_rate_cents=5000,
        share_value=3.0, book_period=("2026-01-01", "2026-06-30"),
    )
    station_id = env["station"]["id"]
    order_l = create_active_order(
        station_id, reprice_policy="LOCKED_AT_BOOKING",
        daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 2}],
    )
    order_r = create_active_order(
        station_id, reprice_policy="REPRICED_AT_AFFIDAVIT",
        daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 2}],
    )
    log = create_locked_log(station_id, log_date="2026-05-04")
    spot_l = book_spot_ok(order_l["id"], log["id"], headers=make_headers("SalesRep", "rep-1"))
    spot_r = book_spot_ok(order_r["id"], log["id"], headers=make_headers("SalesRep", "rep-1"))

    spring = create_published_book(
        station_id, survey_name="Spring",
        period_start="2026-05-01", period_end="2026-09-30", share_value=5.0,
    )
    import_as_run_ok(log["id"], aired_spot_ids=[spot_l["id"], spot_r["id"]])
    reconcile_log_as(log["id"], td_user_id="td-1")

    env.update({
        "order_l": order_l, "order_r": order_r, "log": log,
        "spot_l": spot_l, "spot_r": spot_r,
        "winter": env["book"], "spring": spring,
    })
    return env


def test_locked_spot_keeps_booked_rate_repriced_spot_follows_new_book(api):
    """PRD §3.2: "On a `LOCKED_AT_BOOKING` order, `billed_rate_cents` is pinned
    to `unit_rate_cents` at booking and never recomputed. On a
    `REPRICED_AT_AFFIDAVIT` order, `billed_rate_cents` is null at booking and
    recomputed at affidavit issuance with the then-current published ratings
    book and then-current demand utilization; a mid-flight ratings change
    therefore produces a different billed rate for otherwise identical booking
    inputs."

    Design: Difficulty/dual_variant_calc/locked_vs_repriced_spot_rate_on_ratings_publish
    """
    env = _setup_locked_vs_repriced_env()
    # At booking both priced at 10000 (share 3.0 -> x1.00, MON -> x1.00, low demand).
    assert env["spot_l"]["billed_rate_cents"] == 10000, "LOCKED pins billed at booking"
    assert env["spot_r"]["billed_rate_cents"] is None, "REPRICED leaves billed null at booking"

    issued = get_success_data(
        api.issue_affidavit(env["log"]["id"], make_billing_admin_headers("ba-1"))
    )
    assert issued["posture"] == "AFFIDAVIT_ISSUED"

    spot_l = get_success_data(api.get_spot(env["spot_l"]["id"], BA))
    spot_r = get_success_data(api.get_spot(env["spot_r"]["id"], BA))
    assert spot_l["billed_rate_cents"] == 10000, "LOCKED_AT_BOOKING: rate pinned at booking"
    assert spot_r["billed_rate_cents"] == 12500, (
        "REPRICED: 10000 x 1.25 (then-current share 5.0 tier) x 1.00 (MON) x 1.00 "
        "(demand 2/10 = 0.2 < 0.70)"
    )


def test_affidavit_total_and_supersede_cascade(api):
    """PRD §3.8: "the order's net is the sum over those spots of each spot's
    `billed_rate_cents` multiplied by one minus the agency commission of 0.15,
    with each per-spot line rounded half-up to integer cents **before**
    summing. The `affidavit_total_cents` is the sum of those per-order nets."
    PRD §3.2: "Publishing a book (a `DRAFT → PUBLISHED` transition by a
    `SalesManager`, requiring `period_end` at least `period_start`) triggers a
    supersede cascade: every other `PUBLISHED` book on the same station whose
    period intersects the new book's period transitions to `SUPERSEDED`."

    Design: Difficulty/dual_variant_calc/locked_vs_repriced_spot_rate_on_ratings_publish
    """
    env = _setup_locked_vs_repriced_env()
    winter = get_success_data(api.get_ratings_book(env["winter"]["id"], BA))
    spring = get_success_data(api.get_ratings_book(env["spring"]["id"], BA))
    assert winter["status"] == "SUPERSEDED"
    assert spring["status"] == "PUBLISHED"

    issued = get_success_data(
        api.issue_affidavit(env["log"]["id"], make_billing_admin_headers("ba-1"))
    )
    assert issued["affidavit_total_cents"] == 19125, (
        "round(10000*0.85)=8500 + round(12500*0.85)=10625"
    )


# ---------------------------------------------------------------------------
# Pinned rounding order: per spot line first, then sum
# ---------------------------------------------------------------------------

def _setup_two_1003_spots_env():
    """Two spots billing exactly 1003 each on a reconciled log."""
    env = setup_bookable_station(
        weekday="MON", daypart="MORNING_DRIVE", hour=6,
        base_rate_cents=1003, min_rate_cents=100,
        share_value=3.0, book_period=("2026-01-01", "2026-06-30"),
    )
    order = create_active_order(
        env["station"]["id"], reprice_policy="LOCKED_AT_BOOKING",
        daypart_targets=[{"daypart": "MORNING_DRIVE", "units": 2}],
    )
    log = create_locked_log(env["station"]["id"], log_date="2026-05-04")
    s1 = book_spot_ok(order["id"], log["id"], headers=make_headers("SalesRep", "rep-1"))
    s2 = book_spot_ok(order["id"], log["id"], headers=make_headers("SalesRep", "rep-1"))
    import_as_run_ok(log["id"], aired_spot_ids=[s1["id"], s2["id"]])
    reconcile_log_as(log["id"], td_user_id="td-1")
    env.update({"order": order, "log": log, "spots": (s1, s2)})
    return env


def test_affidavit_spot_lines_rounded_at_booking(api):
    """PRD §3.2: "the final `unit_rate_cents` is the greater of `min_rate_cents`
    and the raw product rounded half-up to integer cents." With share 3.0 and
    low demand every multiplier is 1.00, so both spots bill exactly the base.

    Design: Difficulty/combinatorial_formula/affidavit_net_per_line_rounding_beats_sum_then_round
    """
    env = _setup_two_1003_spots_env()
    s1, s2 = env["spots"]
    assert s1["unit_rate_cents"] == 1003 and s2["unit_rate_cents"] == 1003
    assert s1["billed_rate_cents"] == 1003, "LOCKED_AT_BOOKING pins billed at booking"


def test_affidavit_net_per_line_rounding_beats_sum_then_round(api):
    """PRD §3.8: "The pinned rounding order is load-bearing: summing first and
    rounding once is a different and forbidden variant, because two spots each
    billed 1003 cents yield 853 plus 853 equals 1706 cents under per-line
    rounding but 1705 cents under sum-then-round."

    Design: Difficulty/combinatorial_formula/affidavit_net_per_line_rounding_beats_sum_then_round
    """
    env = _setup_two_1003_spots_env()
    issued = get_success_data(
        api.issue_affidavit(env["log"]["id"], make_billing_admin_headers("ba-1"))
    )
    assert issued["affidavit_total_cents"] == 1706, (
        "per-line round_half_up(1003*0.85)=853 twice, then sum"
    )
    assert issued["affidavit_total_cents"] != 1705, (
        "1705 is the forbidden sum-then-round result round(2006*0.85)"
    )
