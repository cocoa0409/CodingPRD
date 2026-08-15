"""Weekly wrap, recoupment flip, budget identity, cancellation tiers (PRD §3.1, §3.8)."""
from test_helpers import (
    ApiErrorId,
    PRODUCER,
    S1_FIGURES,
    add_passing_check,
    add_stop,
    advance_stop,
    approve_settlement,
    assert_budget_identity,
    cancel_stop,
    certify_stop,
    contract_stop,
    create_contracted_member,
    create_crew_call,
    create_tour,
    create_venue,
    dispute_settlement,
    get_stop,
    get_stop_settlement,
    get_tour,
    issue_per_diem,
    make_treasurer_headers,
    pay_settlement,
    play_performance,
    schedule_performance,
    set_settlement_figures,
    settle_crew_call,
    setup_closed_stop_with_settlement,
    setup_paid_settlement,
    setup_ready_stop,
    setup_submitted_settlement,
    setup_wrapped_stop,
    submit_settlement,
    validate_error,
    validate_success,
    wrap_stop,
)

ZERO_GUARANTEE_STOP = {"guarantee_cents": 0, "split_pct": 70}
CLEAN_FIGURES = {"audited_gross_cents": 1_000_000, "taxes_cents": 0, "levies_cents": 0}


def _wrap_first_stop_for_recoup(api, capitalization=282_000):
    """Build a tour whose first stop (share 300,000, royalty 18,000 pre-recoup)
    wraps and flips recouped at exactly the capitalization boundary."""
    ctx = setup_closed_stop_with_settlement(
        tour_overrides={"capitalization_cents": capitalization},
        stop_overrides=ZERO_GUARANTEE_STOP, played_gross=1_000_000)
    s = ctx["settlement"]
    set_settlement_figures(s["id"], CLEAN_FIGURES["audited_gross_cents"], 0, 0)
    submit_settlement(s["id"], "trs-1")
    approved = approve_settlement(s["id"], "prod-1")
    pay_settlement(s["id"], "trs-1")
    wrapped = wrap_stop(ctx["stop"]["id"])
    return ctx, approved, wrapped


def test_wrap_recoup_order_stop1_pre_recoup_royalty(api):
    """PRD §3.8: "Only after those totals post does the tour re-evaluate its
    recoupment: `recouped` becomes true once `cumulative_producer_net_cents` is
    at least `capitalization_cents` — the boundary itself counts — and the flag
    flips only here, at wrap."
    PRD §3.8: "The ordering is deliberate and load-bearing: this stop’s royalty was fixed at approve time against the recoupment flag of that instant, so a wrap that crosses the capitalization line affects only settlements approved afterwards."

    Design: Difficulty/combinatorial_formula/wrap_recoup_evaluation_order_mode_c
    """
    ctx, approved, wrapped = _wrap_first_stop_for_recoup(api)

    # Fixed at approve with the pre-recoup card: 6% x 300,000.
    assert approved["royalty_cents"] == 18_000
    assert wrapped["booking_status"] == "WRAPPED"

    tour = get_tour(ctx["tour"]["id"])
    # producer net = 300,000 - 18,000 - 0 stop costs = 282,000 >= 282,000.
    assert tour["cumulative_producer_net_cents"] == 282_000
    assert tour["recouped"] is True, "Boundary is inclusive: == capitalization flips"


def test_wrap_recoup_order_stop2_post_recoup_royalty(api):
    """PRD §3.7: "Approving — by a `Producer` or `Treasurer` other than the recorded `submitted_by`, per the segregation rule of §2.11 — records the caller as `approved_by` and computes `royalty_cents` as a marginal two-bracket royalty over `producer_share_cents`, using the tour’s `royalty_tier_threshold_cents` as the bracket boundary and the tour’s `recouped` flag at the instant of approval as the rate selector."
    PRD §3.7: "Before recoupment, the portion of the share up to the threshold
    is charged at 6 percent and any portion above the threshold at 9 percent;
    after recoupment, the portions are charged at 8 percent and 11 percent
    respectively."

    Design: Difficulty/combinatorial_formula/wrap_recoup_evaluation_order_mode_c
    """
    ctx, _, _ = _wrap_first_stop_for_recoup(api)

    # Identical figures on a second stop, approved AFTER the flip.
    stop2 = add_stop(ctx["tour"]["id"], ctx["venue"]["id"],
                     play_week_start="2026-09-15", play_week_end="2026-09-20",
                     load_in_date="2026-09-14", travel_in_days=1,
                     **ZERO_GUARANTEE_STOP)
    contract_stop(stop2["id"])
    advance_stop(stop2["id"])
    add_passing_check(stop2["id"])
    certify_stop(stop2["id"])
    perf = schedule_performance(stop2["id"], perf_date="2026-09-16")
    play_performance(perf["id"], 1_000_000)
    s2 = get_stop_settlement(stop2["id"])
    set_settlement_figures(s2["id"], CLEAN_FIGURES["audited_gross_cents"], 0, 0)
    submit_settlement(s2["id"], "trs-1")
    approved2 = approve_settlement(s2["id"], "prod-1")

    # Same 300,000 share at post-recoup rates: 8% x 300,000.
    assert approved2["producer_share_cents"] == 300_000
    assert approved2["royalty_cents"] == 24_000


def test_budget_contract_cancel_counters_move(api):
    """PRD §3.2: "On success the guarantee moves into the committed bucket — the tour’s `budget_committed_cents` rises by `guarantee_cents` and `budget_available_cents` recomputes."
    PRD §3.1: "The `budget_available_cents` of a tour is always its
    `budget_total_cents` minus `budget_committed_cents` minus
    `budget_spent_cents`; this identity holds after every mutation, and every
    mutation that moves money between the committed and spent buckets preserves
    it."

    Design: Difficulty/compensating_invariant/budget_contract_cancel_identity
    """
    tour = create_tour()
    venue = create_venue()
    assert_budget_identity(get_tour(tour["id"]))

    # Play week starts 2026-10-01; the default logical clock is 2026-08-01.
    stop = add_stop(tour["id"], venue["id"], play_week_start="2026-10-01",
                    play_week_end="2026-10-04", load_in_date="2026-09-29",
                    travel_in_days=1)
    contract_stop(stop["id"])

    mid = get_tour(tour["id"])
    assert mid["budget_committed_cents"] == 4_000_000
    assert mid["budget_available_cents"] == 46_000_000
    assert mid["budget_spent_cents"] == 0
    assert_budget_identity(mid)


def test_budget_contract_cancel_identity_restored(api):
    """PRD §3.8: "From `CONTRACTED`, `ADVANCED`, or `READY`: more than 60 days
    out, the penalty is zero; 31 to 60 days out inclusive, it is a quarter of
    `guarantee_cents` rounded half-up; 30 days out or fewer, it is half of
    `guarantee_cents` rounded half-up."
    PRD §3.8: "The 60-day boundary pays the quarter rate; day 61 pays nothing."
    PRD §3.8: "If the cancelled stop had been committed, its guarantee leaves
    `budget_committed_cents` and the penalty lands in `budget_spent_cents`."

    Design: Difficulty/compensating_invariant/budget_contract_cancel_identity
    """
    tour = create_tour()
    venue = create_venue()
    stop = add_stop(tour["id"], venue["id"], play_week_start="2026-10-01",
                    play_week_end="2026-10-04", load_in_date="2026-09-29",
                    travel_in_days=1)
    contract_stop(stop["id"])

    # Default clock 2026-08-01 -> 61 whole days out -> penalty 0.
    cancelled = cancel_stop(stop["id"])
    assert cancelled["cancellation_penalty_cents"] == 0

    end = get_tour(tour["id"])
    assert end["budget_committed_cents"] == 0
    assert end["budget_spent_cents"] == 0
    assert end["budget_available_cents"] == 50_000_000
    assert_budget_identity(end)


def test_royalty_accrual_zero_through_dispute_cycle(api):
    """PRD §3.7: "The computed `royalty_cents` is added into the tour’s `royalty_accrued_cents`, which at all times equals the sum of royalties over settlements in `APPROVED` or `PAID`."

    Design: Difficulty/compensating_invariant/royalty_accrual_dispute_cycle_identity
    """
    ctx = setup_submitted_settlement()
    s = ctx["settlement"]

    acc_submitted = get_tour(ctx["tour"]["id"])["royalty_accrued_cents"]
    assert acc_submitted == 0, "SUBMITTED is outside the invariant's input set"

    dispute_settlement(s["id"], "audit query")
    submit_settlement(s["id"], "trs-1")
    acc_after_cycle = get_tour(ctx["tour"]["id"])["royalty_accrued_cents"]
    assert acc_after_cycle == 0, (
        "The DISPUTED->SUBMITTED compensating pair leaves the accrual unchanged"
    )


def test_royalty_accrual_constant_after_pay(api):
    """PRD §3.7: "The computed `royalty_cents` is added into the tour’s `royalty_accrued_cents`, which at all times equals the sum of royalties over settlements in `APPROVED` or `PAID`."

    Design: Difficulty/compensating_invariant/royalty_accrual_dispute_cycle_identity
    """
    ctx = setup_submitted_settlement()
    s = ctx["settlement"]
    dispute_settlement(s["id"], "audit query")
    submit_settlement(s["id"], "trs-1")
    approve_settlement(s["id"], "prod-1")

    acc_approved = get_tour(ctx["tour"]["id"])["royalty_accrued_cents"]
    assert acc_approved == 105_000

    pay_settlement(s["id"], "trs-1")
    acc_paid = get_tour(ctx["tour"]["id"])["royalty_accrued_cents"]
    assert acc_paid == 105_000, "PAID stays inside the invariant's input set"


def test_wrap_input_set_filtering(api):
    """PRD §3.8: "Stop costs are the sum of `total_pay_cents` over the stop’s crew calls in `SETTLED`, plus the sum of `cancellation_penalty_cents` over its crew calls in `CANCELLED`, plus the sum of `total_cents` over its per-diem statements in `ISSUED` or `PAID` — anything outside those named states is excluded."
    PRD §3.8: "The stop’s `wrapped_total_cents` — the total money out booked at wrap — is the settlement’s `venue_payment_cents` plus `royalty_cents` plus stop costs."

    Design: Corner/calculations/wrap_input_set_filtering
    """
    ctx = setup_ready_stop(tour_overrides={"per_diem_policy": "ACTUAL_DAYS"})
    stop_id = ctx["stop"]["id"]
    tour_id = ctx["tour"]["id"]

    # One crew call SETTLED at 22,000 (8h straight + 2h at 1.5x, rate 2000);
    # a second call left POSTED must contribute nothing.
    cc1 = create_crew_call(stop_id)
    settle_crew_call(cc1["id"], ("carpenter", 10))
    create_crew_call(stop_id, call_type="SHOW_RUN",
                     scheduled_start="2026-09-08T17:00:00Z",
                     lines=[{"position": "rigger", "rate_cents_per_hour": 2050}])

    member = create_contracted_member(tour_id, name="Pat P")
    # ACTUAL_DAYS, rate 20,000, days 5 / travel 2 -> 3x20,000 + 2x10,000 = 80,000.
    issue_per_diem(stop_id, member["id"], days_present=5, travel_days=2)

    perf = schedule_performance(stop_id)
    play_performance(perf["id"], 750_000)
    s = get_stop_settlement(stop_id)
    set_settlement_figures(s["id"], S1_FIGURES["audited_gross_cents"],
                           S1_FIGURES["taxes_cents"], S1_FIGURES["levies_cents"])
    submit_settlement(s["id"], "trs-1")
    approve_settlement(s["id"], "prod-1")
    pay_settlement(s["id"], "trs-1")

    wrapped = wrap_stop(stop_id)
    # wrapped_total = venue 4,000,000 + royalty 105,000 + (22,000 + 80,000).
    assert wrapped["wrapped_total_cents"] == 4_207_000

    tour = get_tour(tour_id)
    assert tour["budget_spent_cents"] == 4_207_000
    assert tour["budget_committed_cents"] == 0
    assert_budget_identity(tour)


def test_wrap_before_pay_returns_not_ready(api):
    """PRD §3.8: "A `CLOSED` stop is wrapped by a `Producer`, and only once its
    settlement stands at `PAID` — wrapping earlier is rejected with
    `ERR_WRAP_NOT_READY`."

    Design: Corner/errors/wrap_before_pay_returns_not_ready
    """
    ctx = setup_closed_stop_with_settlement()
    s = ctx["settlement"]
    set_settlement_figures(s["id"], S1_FIGURES["audited_gross_cents"],
                           S1_FIGURES["taxes_cents"], S1_FIGURES["levies_cents"])
    submit_settlement(s["id"], "trs-1")
    approve_settlement(s["id"], "prod-1")

    spent_pre = get_tour(ctx["tour"]["id"])["budget_spent_cents"]
    resp = api.put_stop(ctx["stop"]["id"], {"status": "WRAPPED"}, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_WRAP_NOT_READY)
    spent_post = get_tour(ctx["tour"]["id"])["budget_spent_cents"]
    assert spent_post == spent_pre, "Rejected wrap must not move budget counters"


def test_cancellation_penalty_tier_boundaries(api):
    """PRD §3.8: "From `CONTRACTED`, `ADVANCED`, or `READY`: more than 60 days
    out, the penalty is zero; 31 to 60 days out inclusive, it is a quarter of
    `guarantee_cents` rounded half-up; 30 days out or fewer, it is half of
    `guarantee_cents` rounded half-up."
    PRD §3.8: "The 60-day boundary pays the quarter rate; day 61 pays nothing."

    Design: Corner/calculations/cancellation_penalty_tier_boundaries
    """
    tour = create_tour()
    venue = create_venue()
    # Default clock 2026-08-01: stop B starts 2026-08-31 (30 days out),
    # stop A starts 2026-09-30 (60 days out).
    stop_b = add_stop(tour["id"], venue["id"], play_week_start="2026-08-31",
                      play_week_end="2026-09-02", load_in_date="2026-08-30",
                      travel_in_days=0)
    stop_a = add_stop(tour["id"], venue["id"], play_week_start="2026-09-30",
                      play_week_end="2026-10-04", load_in_date="2026-09-28",
                      travel_in_days=0)
    contract_stop(stop_a["id"])
    contract_stop(stop_b["id"])

    cancelled_a = cancel_stop(stop_a["id"])
    cancelled_b = cancel_stop(stop_b["id"])
    assert cancelled_a["cancellation_penalty_cents"] == 1_000_000, (
        "60 days out sits in the 31..60 tier: 25% of 4,000,000"
    )
    assert cancelled_b["cancellation_penalty_cents"] == 2_000_000, (
        "30 days out sits in the <=30 tier: 50% of 4,000,000"
    )


def test_stop_cancel_cascades_to_children(api):
    """PRD §3.8: "Cancellation cascades: every `SCHEDULED` performance of the stop becomes `CANCELLED`, and every `POSTED` crew call becomes `CANCELLED`, each accruing its own cancellation penalty per §3.5 — and those crew penalties add into the tour’s `budget_spent_cents` as well."
    PRD §3.8: "From `CONTRACTED`, `ADVANCED`, or `READY`: more than 60 days out,
    the penalty is zero; 31 to 60 days out inclusive, it is a quarter of
    `guarantee_cents` rounded half-up; 30 days out or fewer, it is half of
    `guarantee_cents` rounded half-up."

    Design: Corner/state_machines/stop_cancel_cascades_to_children
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    perf = schedule_performance(stop_id)
    crew = create_crew_call(stop_id)  # starts 2026-09-05T08:00Z, weeks away

    # Default clock 2026-08-01 -> 37 days out -> 25% tier on the guarantee.
    cancelled = cancel_stop(stop_id)
    assert cancelled["cancellation_penalty_cents"] == 1_000_000

    perfs = api.list_performances(stop_id, PRODUCER).json()["data"]
    assert perfs[0]["status"] == "CANCELLED", "SCHEDULED performance cascades"

    crews = api.list_crew_calls(stop_id, PRODUCER).json()["data"]
    assert crews[0]["status"] == "CANCELLED", "POSTED crew call cascades"
    assert crews[0]["cancellation_penalty_cents"] == 0, (
        "The call is more than 24 hours away, so its show-up penalty is zero"
    )

    tour = get_tour(ctx["tour"]["id"])
    assert tour["budget_spent_cents"] == 1_000_000
    assert tour["budget_committed_cents"] == 0
    assert_budget_identity(tour)


def test_stop_wrapped_terminal_lockdown(api):
    """PRD §3.2: "Stop transitions are strict about their sources: contracting
    only from `TENTATIVE`, advancing only from `CONTRACTED`, certifying only from
    `ADVANCED`, wrapping only from `CLOSED`, and cancellation only from
    `TENTATIVE`, `CONTRACTED`, `ADVANCED`, or `READY`; any other source state
    draws `ERR_STOP_INVALID_STATE`."

    Design: Corner/state_machines/stop_wrapped_terminal_lockdown
    """
    ctx = setup_wrapped_stop()
    spent_pre = get_tour(ctx["tour"]["id"])["budget_spent_cents"]

    resp = api.put_stop(ctx["stop"]["id"], {"status": "CANCELLED"}, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_STOP_INVALID_STATE)

    spent_post = get_tour(ctx["tour"]["id"])["budget_spent_cents"]
    assert spent_post == spent_pre, "Rejected cancel on a terminal stop moves nothing"


def test_stop_cancel_from_playing_rejected(api):
    """PRD §3.2: "Stop transitions are strict about their sources: contracting
    only from `TENTATIVE`, advancing only from `CONTRACTED`, certifying only from
    `ADVANCED`, wrapping only from `CLOSED`, and cancellation only from
    `TENTATIVE`, `CONTRACTED`, `ADVANCED`, or `READY`; any other source state
    draws `ERR_STOP_INVALID_STATE`."

    Design: Corner/state_machines/stop_cancel_from_playing_rejected
    """
    ctx = setup_ready_stop()
    stop_id = ctx["stop"]["id"]
    perf1 = schedule_performance(stop_id, perf_date="2026-09-08")
    schedule_performance(stop_id, perf_date="2026-09-09")
    play_performance(perf1["id"], 750_000)
    assert get_stop(stop_id)["booking_status"] == "PLAYING"

    resp = api.put_stop(stop_id, {"status": "CANCELLED"}, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_STOP_INVALID_STATE)


def test_tour_complete_with_open_stops_rejected(api):
    """PRD §3.1: "Moving from `ON_TOUR` to `COMPLETED` requires that every stop
    of the tour be terminal — each in `WRAPPED` or `CANCELLED`."
    PRD §3.1: "An out-of-order or premature transition is rejected with
    `ERR_TOUR_INVALID_STATE`."

    Design: Corner/state_machines/tour_complete_with_open_stops_rejected
    """
    ctx = setup_ready_stop()
    tour_id = ctx["tour"]["id"]
    validate_success(api.patch_tour(tour_id, {"status": "ON_TOUR"}, PRODUCER))

    # The READY stop is not terminal, so COMPLETED is premature.
    resp = api.patch_tour(tour_id, {"status": "COMPLETED"}, PRODUCER)
    validate_error(resp, ApiErrorId.ERR_TOUR_INVALID_STATE)
