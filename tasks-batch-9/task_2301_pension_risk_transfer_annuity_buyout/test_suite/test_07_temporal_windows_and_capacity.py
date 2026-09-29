"""Temporal geometry: the quiet period between windows, closed lock intervals measured
against carrier capacity, and the reservation abandonment gives back.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import administrator_headers, api_errors, factories, fiduciary_headers
from test_helpers.constants import (
    QUIET_PERIOD_DAYS,
    accounting_liability,
    days_after,
    funded_status_bp,
)
from test_helpers.fixtures import (
    ParticipantSpec,
    QuoteSpec,
    abandon_tranche,
    build_authorized_plan,
    build_locked_tranche,
    build_quoting_tranche,
    create_insurer,
    create_window,
    list_settlement_entries,
    list_windows,
    lock_pricing,
    read_funded_status,
    read_insurer,
    read_participant,
    read_plan,
    read_quote,
    read_tranche,
    request_and_submit_quote,
    request_quote,
    rescind_amendment,
    select_insurer,
    set_clock,
    submit_quote,
)

DEFERRED = "DEFERRED_VESTED"


# ---------------------------------------------------------------------------
# Design: Difficulty/resource_temporal_overlap/window_quiet_period_admits_exactly_the_ninetieth_day
# ---------------------------------------------------------------------------

QUIET_PLAN = {
    "sponsor_name": "Larkspur Ceramics",
    "plan_name": "Larkspur Union Plan",
    "plan_ein": "270991456",
    "total_liability_cents": 60000000,
    "plan_assets_cents": 55000000,
    "service_cost_cents": 1800000,
    "interest_cost_cents": 5200000,
    "unrecognized_actuarial_loss_cents": 2400000,
    "discount_rate_bps": 470,
}
W1_OPENS_AT = "2026-08-15T00:00:00.000Z"
W1_CLOSES_AT = "2026-10-31T00:00:00.000Z"
#: The first instant that clears a 90-day quiet period measured after W1's close.
FIRST_CLEAR_OPENING = days_after(W1_CLOSES_AT, QUIET_PERIOD_DAYS)
ONE_DAY_SHORT = days_after(W1_CLOSES_AT, QUIET_PERIOD_DAYS - 1)
LATE_CLOSES_AT = "2027-03-01T00:00:00Z"
CONTAINED_OPENS_AT = "2026-09-15T00:00:00.000Z"
CONTAINED_CLOSES_AT = "2026-09-30T00:00:00.000Z"
SMALL_CAP_CENTS = 10000000
ELIGIBILITY_CEILING_CENTS = 15000000


def _plan_with_one_planned_window(api):
    authorized = build_authorized_plan(
        api,
        participants=[],
        strategy_type="LUMP_SUM_WINDOW",
        amendment_scope="LUMP_SUM_ONLY",
        amendment_effective_date="2026-08-10T00:00:00Z",
        **QUIET_PLAN
    )
    first = create_window(
        api,
        authorized.plan_id,
        window_name="Larkspur Autumn Window",
        opens_at=W1_OPENS_AT,
        closes_at=W1_CLOSES_AT,
        lump_sum_cap_cents=30000000,
        eligibility_max_lump_sum_cents=ELIGIBILITY_CEILING_CENTS,
    )
    return authorized, first


def _propose_window(api, plan_id, name, opens_at, closes_at):
    payload = factories.window_payload(
        opens_at=opens_at,
        closes_at=closes_at,
        window_name=name,
        lump_sum_cap_cents=SMALL_CAP_CENTS,
        eligibility_max_lump_sum_cents=ELIGIBILITY_CEILING_CENTS,
    )
    return api.create_window(plan_id, payload, administrator_headers())


def _accept_window(api, plan_id, name, opens_at, closes_at):
    """A window proposal that the schedule admits, minting a new resource."""
    return validate_success(_propose_window(api, plan_id, name, opens_at, closes_at), 201)


def test_an_overlapping_window_and_an_abutting_one_are_refused_alike(api):
    """Half-open adjacency escapes the overlap test but never escapes the buffer.

    PRD: "A lump-sum election window is **half-open**: the interval runs from `opens_at`
    inclusive to `closes_at` exclusive, so the window is live while the clock is at or
    after `opens_at` and strictly before `closes_at`."

    PRD: "A proposed window's half-open interval must not overlap the interval of any
    other window of the same plan that is not `VOIDED`, and it must additionally clear a
    quiet period of 90 days measured after the `closes_at` of every such window — three
    months of silence between offers, so that participants are not pressured by
    back-to-back deadlines. Either failure is rejected with
    `ERR_WINDOW_QUIET_PERIOD_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/window_quiet_period_admits_exactly_the_ninetieth_day
    """
    authorized, first = _plan_with_one_planned_window(api)

    assert first["window_status"] == "PLANNED"

    contained = _propose_window(
        api, authorized.plan_id, "Contained Candidate", CONTAINED_OPENS_AT, CONTAINED_CLOSES_AT
    )
    validate_error(contained, api_errors.ERR_WINDOW_QUIET_PERIOD_CONFLICT)

    # Opening exactly at W1's exclusive end overlaps nothing, yet opens the buffer's day 0.
    abutting = _propose_window(
        api, authorized.plan_id, "Abutting Candidate", W1_CLOSES_AT, "2026-11-30T00:00:00Z"
    )
    validate_error(abutting, api_errors.ERR_WINDOW_QUIET_PERIOD_CONFLICT)

    assert [row["id"] for row in list_windows(api, authorized.plan_id)] == [first["id"]]


def test_the_ninetieth_day_after_the_close_is_the_first_admissible_opening(api):
    """One day short of the buffer is refused; the ninetieth day is admitted.

    PRD: "A proposed window's half-open interval must not overlap the interval of any
    other window of the same plan that is not `VOIDED`, and it must additionally clear a
    quiet period of 90 days measured after the `closes_at` of every such window — three
    months of silence between offers, so that participants are not pressured by
    back-to-back deadlines. Either failure is rejected with
    `ERR_WINDOW_QUIET_PERIOD_CONFLICT`."

    PRD: "A window starts in `PLANNED` with `notice_count` at 0,
    `approved_lump_sum_total_cents` and `paid_lump_sum_total_cents` at 0, and
    `opened_at`, `closed_at`, and `settled_at` all null."

    Design: Difficulty/resource_temporal_overlap/window_quiet_period_admits_exactly_the_ninetieth_day
    """
    authorized, first = _plan_with_one_planned_window(api)

    assert ONE_DAY_SHORT == "2027-01-28T00:00:00.000Z"
    assert FIRST_CLEAR_OPENING == "2027-01-29T00:00:00.000Z"

    short_of_buffer = _propose_window(
        api, authorized.plan_id, "Eighty Nine Day Candidate", ONE_DAY_SHORT, LATE_CLOSES_AT
    )
    validate_error(short_of_buffer, api_errors.ERR_WINDOW_QUIET_PERIOD_CONFLICT)

    admitted = _accept_window(
        api, authorized.plan_id, "Ninetieth Day Candidate", FIRST_CLEAR_OPENING, LATE_CLOSES_AT
    )
    assert admitted["window_status"] == "PLANNED"
    assert admitted["opens_at"] == FIRST_CLEAR_OPENING
    assert admitted["notice_count"] == 0
    assert admitted["approved_lump_sum_total_cents"] == 0
    assert admitted["paid_lump_sum_total_cents"] == 0
    assert admitted["opened_at"] is None
    assert admitted["closed_at"] is None
    assert admitted["settled_at"] is None

    assert sorted(row["id"] for row in list_windows(api, authorized.plan_id)) == sorted(
        [first["id"], admitted["id"]]
    )


def test_a_degenerate_interval_is_malformed_before_the_buffer_is_consulted(api):
    """An empty interval sitting inside W1 answers 422, not the scheduling conflict.

    PRD: "Both amounts must be at least 1, and `closes_at` must be strictly after
    `opens_at`."

    PRD: "The families below are evaluated in the order listed; the first family that
    finds a violation decides the response, and later families are not consulted."

    PRD: "**Interval well-formedness** — a lump-sum window requires `opens_at` strictly
    before `closes_at`, a quote submission requires `lock_days` of at least 1, and an
    amendment's `amendment_effective_date` must not precede the logical clock; else
    `ERR_INVALID_INTERVAL` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/window_quiet_period_admits_exactly_the_ninetieth_day
    """
    authorized, first = _plan_with_one_planned_window(api)

    degenerate = _propose_window(
        api, authorized.plan_id, "Degenerate Candidate", CONTAINED_OPENS_AT, CONTAINED_OPENS_AT
    )
    validate_error(degenerate, api_errors.ERR_INVALID_INTERVAL)

    # The same instant inside W1 is what the scheduling family would have caught.
    conflicting = _propose_window(
        api, authorized.plan_id, "Contained Candidate", CONTAINED_OPENS_AT, CONTAINED_CLOSES_AT
    )
    validate_error(conflicting, api_errors.ERR_WINDOW_QUIET_PERIOD_CONFLICT)

    assert [row["id"] for row in list_windows(api, authorized.plan_id)] == [first["id"]]


def test_voided_windows_leave_the_buffer_and_free_the_refused_interval(api):
    """Rescission voids the schedule, and the byte-identical proposal is then accepted.

    PRD: "When it succeeds, `amendment_scope`, `amendment_adopted_at`, and
    `amendment_effective_date` are all cleared, and two cascades fire: every window of
    the plan still in `PLANNED` transitions to `VOIDED`, and every tranche of the plan
    still in `DRAFT` transitions to `ABANDONED` — which in turn returns each of that
    tranche's assigned participants from `ASSIGNED` to `IN_PLAN` with `tranche_id`
    cleared and each such participant's `data_confidence_score` recomputed."

    PRD: "A proposed window's half-open interval must not overlap the interval of any
    other window of the same plan that is not `VOIDED`, and it must additionally clear a
    quiet period of 90 days measured after the `closes_at` of every such window — three
    months of silence between offers, so that participants are not pressured by
    back-to-back deadlines."

    Design: Difficulty/resource_temporal_overlap/window_quiet_period_admits_exactly_the_ninetieth_day
    """
    authorized, first = _plan_with_one_planned_window(api)
    second = _accept_window(
        api, authorized.plan_id, "Ninetieth Day Candidate", FIRST_CLEAR_OPENING, LATE_CLOSES_AT
    )

    refused = _propose_window(
        api, authorized.plan_id, "Contained Candidate", CONTAINED_OPENS_AT, CONTAINED_CLOSES_AT
    )
    validate_error(refused, api_errors.ERR_WINDOW_QUIET_PERIOD_CONFLICT)

    rescinded = rescind_amendment(api, authorized.plan_id)
    assert rescinded["plan_status"] == "ONGOING"
    assert rescinded["amendment_scope"] is None
    assert rescinded["amendment_adopted_at"] is None
    assert rescinded["amendment_effective_date"] is None

    voided = list_windows(api, authorized.plan_id, window_status="VOIDED")
    assert sorted(row["id"] for row in voided) == sorted([first["id"], second["id"]])

    retried = _accept_window(
        api,
        authorized.plan_id,
        "Contained Candidate Retry",
        CONTAINED_OPENS_AT,
        CONTAINED_CLOSES_AT,
    )
    assert retried["window_status"] == "PLANNED"
    assert retried["opens_at"] == CONTAINED_OPENS_AT
    assert retried["closes_at"] == CONTAINED_CLOSES_AT
    assert retried["notice_count"] == 0
    assert retried["approved_lump_sum_total_cents"] == 0


# ---------------------------------------------------------------------------
# Design: Difficulty/resource_temporal_overlap/insurer_capacity_closed_lock_intervals_touch_but_expiry_frees
# ---------------------------------------------------------------------------

CAPACITY_CENTS = 20000000
FIRST_PREMIUM_CENTS = 12000000
SECOND_PREMIUM_CENTS = 11800000
LOCK_DAYS = 90
BENEFIT_CENTS = 100000
FIRST_LOCK_AT = "2026-09-01T00:00:00.000Z"
FIRST_LOCK_EXPIRES_AT = days_after(FIRST_LOCK_AT, LOCK_DAYS)
SECOND_SUBMISSION_AT = "2026-11-25T00:00:00Z"
DAY_AFTER_FIRST_LOCK_ENDS = days_after(FIRST_LOCK_EXPIRES_AT, 1)
STAGED_PLAN = {
    "sponsor_name": "Ironbridge Foundry",
    "plan_name": "Ironbridge Hourly Plan",
    "plan_ein": "391204778",
    "total_liability_cents": 100000000,
    "plan_assets_cents": 92000000,
    "service_cost_cents": 3000000,
    "interest_cost_cents": 9000000,
    "unrecognized_actuarial_loss_cents": 4000000,
    "discount_rate_bps": 500,
}


def _two_stage_buyout(api):
    """Lock stage one, then bring stage two to the brink of its own lock."""
    authorized = build_authorized_plan(
        api,
        participants=[
            ParticipantSpec(BENEFIT_CENTS, cohort=DEFERRED, credited_service_months=320),
            ParticipantSpec(BENEFIT_CENTS, cohort=DEFERRED, credited_service_months=320),
        ],
        amendment_effective_date="2026-08-10T00:00:00Z",
        **STAGED_PLAN
    )
    insurer = create_insurer(
        api,
        insurer_name="Beacon National Life",
        rating_grade="AA_MINUS",
        capital_ratio_bp=3800,
        capacity_cents=CAPACITY_CENTS,
    )
    first_participant, second_participant = authorized.participants

    stage_one = build_quoting_tranche(
        api,
        authorized.plan_id,
        [first_participant],
        target_cohort=DEFERRED,
        tranche_name="Ironbridge Stage One",
    )
    request_and_submit_quote(
        api, stage_one.tranche_id, insurer["id"], FIRST_PREMIUM_CENTS, LOCK_DAYS, 90
    )
    stage_two = build_quoting_tranche(
        api,
        authorized.plan_id,
        [second_participant],
        target_cohort=DEFERRED,
        tranche_name="Ironbridge Stage Two",
    )
    second_quote = request_quote(api, stage_two.tranche_id, insurer["id"])

    set_clock(api, FIRST_LOCK_AT)
    select_insurer(api, stage_one.tranche_id, "SAFETY_WEIGHTED")
    first_lock = lock_pricing(api, stage_one.tranche_id)

    set_clock(api, SECOND_SUBMISSION_AT)
    second_quote = submit_quote(
        api, second_quote["id"], insurer["id"], SECOND_PREMIUM_CENTS, LOCK_DAYS, 30
    )
    select_insurer(api, stage_two.tranche_id, "SAFETY_WEIGHTED")
    second_quote = read_quote(api, second_quote["id"])
    return authorized, insurer, first_lock, stage_two, second_quote


def test_a_lock_reserves_its_premium_across_the_whole_closed_interval(api):
    """The lock stamps a closed interval and consumes the carrier's capacity at once.

    PRD: "A pricing lock is **closed**: it runs from `lock_start_at` inclusive to
    `lock_expires_at` inclusive, so two locks that touch at a single instant do overlap."

    PRD: "A successful lock sets the tranche's `locked_premium_cents` to the selected
    quote's `premium_cents`, sets `lock_start_at` to the logical clock and
    `lock_expires_at` to `lock_start_at` plus the quote's `lock_days` days, moves the
    selected quote `SHORTLISTED → LOCKED`, recomputes the carrier's
    `committed_capacity_cents` and `available_capacity_cents`, and bumps the tranche's,
    the quote's, and the carrier's `version`."

    Design: Difficulty/resource_temporal_overlap/insurer_capacity_closed_lock_intervals_touch_but_expiry_frees
    """
    _authorized, insurer, first_lock, _stage_two, _second_quote = _two_stage_buyout(api)

    assert first_lock["tranche_status"] == "PRICING_LOCKED"
    assert first_lock["locked_premium_cents"] == FIRST_PREMIUM_CENTS
    assert first_lock["lock_start_at"] == FIRST_LOCK_AT
    assert first_lock["lock_expires_at"] == FIRST_LOCK_EXPIRES_AT
    assert FIRST_LOCK_EXPIRES_AT == "2026-11-30T00:00:00.000Z"

    carrier = read_insurer(api, insurer["id"])
    assert carrier["capacity_cents"] == CAPACITY_CENTS
    assert carrier["committed_capacity_cents"] == FIRST_PREMIUM_CENTS
    assert carrier["available_capacity_cents"] == CAPACITY_CENTS - FIRST_PREMIUM_CENTS
    assert (
        carrier["committed_capacity_cents"] + carrier["available_capacity_cents"]
        == carrier["capacity_cents"]
    )


def test_two_lock_intervals_touching_at_one_instant_exceed_the_capacity(api):
    """A candidate interval starting on the day the first lock ends still intersects it.

    PRD: "For a candidate interval, the carrier's `committed_capacity_cents` is the sum
    of `locked_premium_cents` across every tranche whose `selected_insurer_id` is this
    carrier, whose `tranche_status` is `PRICING_LOCKED`, `ASSETS_TRANSFERRED`, or
    `SETTLED`, and whose own closed lock interval intersects the candidate interval —
    that is, whose `lock_start_at` is at or before the candidate interval's end and
    whose `lock_expires_at` is at or after the candidate interval's start."

    PRD: "Because both intervals are closed, two locks that touch at a single instant do
    intersect and their premiums are added together."

    PRD: "The premium is admitted only when it is at most `available_capacity_cents`;
    otherwise the lock is rejected with `ERR_INSURER_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/insurer_capacity_closed_lock_intervals_touch_but_expiry_frees
    """
    _authorized, insurer, _first_lock, stage_two, second_quote = _two_stage_buyout(api)

    # The quote outlives both attempts, so no expiry check can pre-empt the capacity one.
    assert second_quote["expires_at"] == days_after(SECOND_SUBMISSION_AT, 30)
    assert second_quote["quote_status"] == "SHORTLISTED"

    set_clock(api, FIRST_LOCK_EXPIRES_AT)
    carrier = read_insurer(api, insurer["id"])
    assert carrier["committed_capacity_cents"] == FIRST_PREMIUM_CENTS
    assert carrier["available_capacity_cents"] == CAPACITY_CENTS - FIRST_PREMIUM_CENTS
    assert SECOND_PREMIUM_CENTS > carrier["available_capacity_cents"]

    rejected = api.post_pricing_lock(stage_two.tranche_id, {}, fiduciary_headers())
    validate_error(rejected, api_errors.ERR_INSURER_CAPACITY_EXCEEDED)

    untouched = read_tranche(api, stage_two.tranche_id)
    assert untouched["tranche_status"] == "INSURER_SELECTED"
    assert untouched["locked_premium_cents"] is None
    assert untouched["lock_start_at"] is None
    assert untouched["lock_expires_at"] is None
    assert read_quote(api, second_quote["id"])["quote_status"] == "SHORTLISTED"


def test_one_day_later_the_disjoint_interval_admits_the_same_premium(api):
    """Two premiums totalling more than the capacity fit once the intervals part.

    PRD: "Finally the premium must fit inside the carrier's remaining capacity over the
    candidate lock interval, which runs as a closed interval from the logical clock
    through the logical clock plus the quote's `lock_days` days."

    PRD: "The carrier's `available_capacity_cents` is its `capacity_cents` minus that
    committed sum, and it equals the full `capacity_cents` when no lock intersects."

    Design: Difficulty/resource_temporal_overlap/insurer_capacity_closed_lock_intervals_touch_but_expiry_frees
    """
    _authorized, insurer, first_lock, stage_two, second_quote = _two_stage_buyout(api)

    set_clock(api, FIRST_LOCK_EXPIRES_AT)
    validate_error(
        api.post_pricing_lock(stage_two.tranche_id, {}, fiduciary_headers()),
        api_errors.ERR_INSURER_CAPACITY_EXCEEDED,
    )

    set_clock(api, DAY_AFTER_FIRST_LOCK_ENDS)
    assert DAY_AFTER_FIRST_LOCK_ENDS == "2026-12-01T00:00:00.000Z"

    second_lock = lock_pricing(api, stage_two.tranche_id)
    assert second_lock["tranche_status"] == "PRICING_LOCKED"
    assert second_lock["locked_premium_cents"] == SECOND_PREMIUM_CENTS
    assert second_lock["lock_start_at"] == DAY_AFTER_FIRST_LOCK_ENDS
    assert second_lock["lock_expires_at"] == days_after(DAY_AFTER_FIRST_LOCK_ENDS, LOCK_DAYS)
    assert second_lock["lock_expires_at"] == "2027-03-01T00:00:00.000Z"

    carrier = read_insurer(api, insurer["id"])
    assert carrier["committed_capacity_cents"] == SECOND_PREMIUM_CENTS
    assert carrier["available_capacity_cents"] == CAPACITY_CENTS - SECOND_PREMIUM_CENTS

    # More premium has been locked in total than the carrier could ever hold at once.
    assert FIRST_PREMIUM_CENTS + SECOND_PREMIUM_CENTS > CAPACITY_CENTS
    still_locked = read_tranche(api, first_lock["id"])
    assert still_locked["tranche_status"] == "PRICING_LOCKED"
    assert still_locked["locked_premium_cents"] == FIRST_PREMIUM_CENTS

    locked_quote = read_quote(api, second_quote["id"])
    assert locked_quote["quote_status"] == "LOCKED"
    assert locked_quote["rating_at_submission"] == "AA_MINUS"


# ---------------------------------------------------------------------------
# Design: Difficulty/compensating_invariant/abandonment_conserves_insurer_capacity_and_never_touches_plan_liability
# ---------------------------------------------------------------------------

ABANDON_PLAN = {
    "sponsor_name": "Bellweather Optics",
    "plan_name": "Bellweather Salaried Plan",
    "plan_ein": "480113772",
    "total_liability_cents": 100000000,
    "plan_assets_cents": 92000000,
    "service_cost_cents": 3000000,
    "interest_cost_cents": 9000000,
    "unrecognized_actuarial_loss_cents": 4000000,
    "discount_rate_bps": 500,
}
ABANDONMENT_REASON = "Sponsor deferred the transaction to the next fiscal year."


def _locked_then_abandoned(api):
    authorized = build_authorized_plan(
        api,
        participants=[ParticipantSpec(BENEFIT_CENTS, cohort=DEFERRED, credited_service_months=320)],
        amendment_effective_date="2026-08-10T00:00:00Z",
        **ABANDON_PLAN
    )
    insurer = create_insurer(
        api,
        insurer_name="Solstice Assurance",
        rating_grade="AA",
        capital_ratio_bp=4600,
        capacity_cents=CAPACITY_CENTS,
    )
    tranche = build_locked_tranche(
        api,
        authorized.plan_id,
        authorized.participants,
        [QuoteSpec(insurer["id"], FIRST_PREMIUM_CENTS, LOCK_DAYS, 60)],
        target_cohort=DEFERRED,
        tranche_name="Bellweather Tranche A",
    )
    return authorized, insurer, tranche


def test_abandoning_a_locked_tranche_returns_the_whole_reservation(api):
    """Capacity, the quote and the participant all go back where they came from.

    PRD: "Abandonment reverses every reservation the tranche made, and each reversal is
    stated in full. If `locked_premium_cents` was set, the selected quote transitions
    `LOCKED → EXPIRED` and the carrier's `committed_capacity_cents` and
    `available_capacity_cents` are recomputed, restoring the invariant that the
    carrier's `capacity_cents` equals its committed plus available capacity at the
    pre-lock values."

    PRD: "The tranche clears `selected_quote_id`, `selected_insurer_id`,
    `selection_score_bp`, `locked_premium_cents`, `lock_start_at`, and
    `lock_expires_at`, stamps `abandoned_at` and `abandonment_reason`, and bumps its
    `version` — as does every quote, participant, and carrier the reversal touched."

    Design: Difficulty/compensating_invariant/abandonment_conserves_insurer_capacity_and_never_touches_plan_liability
    """
    authorized, insurer, tranche = _locked_then_abandoned(api)
    participant_id = authorized.participants[0]["id"]
    quote_id = tranche["selected_quote_id"]

    while_locked = read_insurer(api, insurer["id"])
    assert while_locked["committed_capacity_cents"] == FIRST_PREMIUM_CENTS
    assert while_locked["available_capacity_cents"] == CAPACITY_CENTS - FIRST_PREMIUM_CENTS
    assert (
        while_locked["committed_capacity_cents"] + while_locked["available_capacity_cents"]
        == while_locked["capacity_cents"]
    )

    abandoned = abandon_tranche(api, tranche["id"], abandonment_reason=ABANDONMENT_REASON)
    assert abandoned["tranche_status"] == "ABANDONED"
    assert abandoned["locked_premium_cents"] is None
    assert abandoned["lock_start_at"] is None
    assert abandoned["lock_expires_at"] is None
    assert abandoned["selected_quote_id"] is None
    assert abandoned["selected_insurer_id"] is None
    assert abandoned["selection_score_bp"] is None
    assert abandoned["abandonment_reason"] == ABANDONMENT_REASON
    assert abandoned["abandoned_at"] is not None

    restored = read_insurer(api, insurer["id"])
    assert restored["committed_capacity_cents"] == 0
    assert restored["available_capacity_cents"] == CAPACITY_CENTS
    assert (
        restored["committed_capacity_cents"] + restored["available_capacity_cents"]
        == restored["capacity_cents"]
    )

    assert read_quote(api, quote_id)["quote_status"] == "EXPIRED"

    released = read_participant(api, participant_id)
    assert released["participant_status"] == "IN_PLAN"
    assert released["tranche_id"] is None
    assert released["accounting_liability_cents"] == accounting_liability(BENEFIT_CENTS, DEFERRED)


def test_abandonment_recognises_nothing_on_the_plan_balance_sheet(api):
    """The plan's measurement is byte-identical to its pre-lock state.

    PRD: "Note what abandonment does *not* touch: the plan's `total_liability_cents` is
    never adjusted, because liability is only reduced at settlement."

    PRD: "Its accounting figure, `accounting_funded_status_bp`, is 0 whenever
    `total_liability_cents` is 0; otherwise it is `plan_assets_cents` multiplied by
    10,000 and rounded half up over `total_liability_cents`, so a fully funded plan
    reads 10000 basis points."

    Design: Difficulty/compensating_invariant/abandonment_conserves_insurer_capacity_and_never_touches_plan_liability
    """
    authorized, _insurer, tranche = _locked_then_abandoned(api)

    before = read_plan(api, authorized.plan_id)
    abandon_tranche(api, tranche["id"], abandonment_reason=ABANDONMENT_REASON)

    after = read_plan(api, authorized.plan_id)
    assert after["total_liability_cents"] == before["total_liability_cents"]
    assert after["total_liability_cents"] == ABANDON_PLAN["total_liability_cents"]
    assert after["plan_assets_cents"] == before["plan_assets_cents"]
    assert after["plan_assets_cents"] == ABANDON_PLAN["plan_assets_cents"]

    funded = read_funded_status(api, authorized.plan_id)
    assert funded["accounting_funded_status_bp"] == funded_status_bp(
        ABANDON_PLAN["plan_assets_cents"], ABANDON_PLAN["total_liability_cents"]
    )
    assert funded["accounting_funded_status_bp"] == 9200
    assert funded["cumulative_settlement_charge_cents"] == 0
    assert funded["deferred_settlement_charge_cents"] == 0

    assert list_settlement_entries(api, plan_id=authorized.plan_id) == []


def test_a_rebuilt_tranche_re_locks_the_identical_premium(api):
    """Nothing leaked: the same carrier writes the same premium a second time.

    PRD: "Abandonment reverses every reservation the tranche made, and each reversal is
    stated in full. If `locked_premium_cents` was set, the selected quote transitions
    `LOCKED → EXPIRED` and the carrier's `committed_capacity_cents` and
    `available_capacity_cents` are recomputed, restoring the invariant that the
    carrier's `capacity_cents` equals its committed plus available capacity at the
    pre-lock values."

    PRD: "Every assigned participant transitions `ASSIGNED → IN_PLAN` with `tranche_id`
    cleared."

    Design: Difficulty/compensating_invariant/abandonment_conserves_insurer_capacity_and_never_touches_plan_liability
    """
    authorized, insurer, tranche = _locked_then_abandoned(api)

    abandon_tranche(api, tranche["id"], abandonment_reason=ABANDONMENT_REASON)
    released = read_participant(api, authorized.participants[0]["id"])
    assert released["participant_status"] == "IN_PLAN"

    rebuilt = build_locked_tranche(
        api,
        authorized.plan_id,
        [released],
        [QuoteSpec(insurer["id"], FIRST_PREMIUM_CENTS, LOCK_DAYS, 60)],
        target_cohort=DEFERRED,
        tranche_name="Bellweather Tranche A Rebuilt",
    )
    assert rebuilt["tranche_status"] == "PRICING_LOCKED"
    assert rebuilt["locked_premium_cents"] == FIRST_PREMIUM_CENTS
    assert rebuilt["selected_insurer_id"] == insurer["id"]

    carrier = read_insurer(api, insurer["id"])
    assert carrier["committed_capacity_cents"] == FIRST_PREMIUM_CENTS
    assert carrier["available_capacity_cents"] == CAPACITY_CENTS - FIRST_PREMIUM_CENTS
