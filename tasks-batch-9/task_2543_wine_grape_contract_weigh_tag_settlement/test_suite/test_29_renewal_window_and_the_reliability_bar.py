"""One rank guarding a renewal with two different error identifiers, and both are reachable on
the same agreement. Before the window opens the renewal dimension has not woken up; inside the
window the producer's lifetime standing decides; and once the window has closed the dimension
has moved to its terminal state and the window objection speaks again.
"""
from test_helpers import (
    MANAGER,
    ApiErrorId,
    accept_contract,
    book_sampling_visit,
    create_allocation,
    create_contract,
    create_crew,
    issue_pick_call,
    move_clock,
    offer_contract,
    read_contract,
    read_grower,
    read_pick_call,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
    validate_error,
)

ACCEPTED_AT = "2026-08-01T00:00:00Z"
FIELD_WINDOW = ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")

# The term ends with the 2026 vintage, so the window closes at midnight on the first of
# November 2026 and opens the contract's 90 notice days earlier.
RENEWAL_WINDOW_OPENS_AT = "2026-08-03T00:00:00Z"
RENEWAL_WINDOW_CLOSES_AT = "2026-11-01T00:00:00Z"

# Every call is issued at ACCEPTED_AT, so all five acknowledgement windows shut together.
SHARED_ACK_DEADLINE_AT = "2026-08-02T00:00:00Z"
ONE_SECOND_PAST_EVERY_ACK_DEADLINE = "2026-08-02T00:00:01Z"

CALLED_TARGETS = (
    "2026-08-03T12:00:00Z",
    "2026-08-04T12:00:00Z",
    "2026-08-05T12:00:00Z",
    "2026-08-06T12:00:00Z",
    "2026-08-07T12:00:00Z",
)
CALLED_TONS = 5.000

EXPIRED_CALLS = 5
FIVE_EXPIRIES_SCORE = 75.0
RENEWAL_BAR = 80.0

A_TWO_YEAR_EXTENSION = {"renewal_term_years": 2}

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
BLOCK = {
    "block_code": "B-12",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
}
SPEC = {
    "spec_code": "CAB-STD-2026",
    "min_brix_accept": 20.0,
    "brix_bonus_start": 24.0,
    "brix_penalty_start": 22.0,
    "rot_rejection_pct": 8.0,
    "min_brix_pick_call": 21.0,
}
RIPE_SAMPLE = {
    "measured_brix": 24.5,
    "measured_ta_gl": 6.5,
    "measured_ph": 3.40,
    "measured_rot_pct": 1.0,
}


def _a_producer_about_to_lose_its_standing() -> dict:
    """An ACTIVE single-vintage contract accepted at the pinned instant, with five pick calls
    issued and none of them answered — so the producer's standing is about to fall away."""
    move_clock(ACCEPTED_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides=dict(SPEC),
    )
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code="GC-RENEWAL-GATE",
        contract_basis="TONNAGE",
        committed_tons=80.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2026,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"], ctx["block"]["id"], ctx["crew"]["id"], FIELD_WINDOW[0], FIELD_WINDOW[1]
    )
    record_sampling_visit(visit["id"], **RIPE_SAMPLE)

    ctx["calls"] = [
        issue_pick_call(contract["id"], ctx["block"]["id"], target, CALLED_TONS)
        for target in CALLED_TARGETS
    ]
    return ctx


def _renew(api, contract_id: str):
    return api.renew_contract(contract_id, dict(A_TWO_YEAR_EXTENSION), MANAGER)


def _let_every_call_expire():
    move_clock(ONE_SECOND_PAST_EVERY_ACK_DEADLINE)


def test_the_window_is_derived_from_the_last_vintage_of_the_term(api):
    """Acceptance fixes both edges: the close is midnight on the first of November of the final
    vintage, and the open is that instant less the contract's notice period.

    PRD: "The renewal window is fixed: `renewal_window_closes_at` becomes midnight UTC on the
    first of November of the year given by `term_end_vintage` (the year, then
    `-11-01T00:00:00Z`), and `renewal_window_opens_at` becomes that closing instant less
    `termination_notice_days` days."

    Design: Corner/validations/renewal_is_gated_by_both_the_window_and_the_lifetime_reliability_score
    """
    ctx = _a_producer_about_to_lose_its_standing()

    assert ctx["contract"]["renewal_window_opens_at"] == RENEWAL_WINDOW_OPENS_AT
    assert ctx["contract"]["renewal_window_closes_at"] == RENEWAL_WINDOW_CLOSES_AT
    assert ctx["contract"]["renewal_status"] == "NOT_DUE"


def test_renewing_before_the_window_opens_is_refused_on_the_window(api):
    """Two days early the renewal dimension has not woken up, and a renewal from any state other
    than the open one is a window objection — the producer's standing is not even consulted.

    PRD: "A renewal attempted from any other renewal state, or after the window has closed, is
    refused with `ERR_RENEWAL_WINDOW_NOT_OPEN`; a renewal refused on reliability grounds is
    `ERR_RELIABILITY_BELOW_RENEWAL_THRESHOLD`."

    Design: Corner/validations/renewal_is_gated_by_both_the_window_and_the_lifetime_reliability_score
    """
    ctx = _a_producer_about_to_lose_its_standing()

    validate_error(
        _renew(api, ctx["contract"]["id"]),
        ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value,
        409,
    )


def test_five_unanswered_calls_cost_the_producer_twenty_five_units(api):
    """Five expiries at five units each land the producer on 75.0 — and since every call was
    created in the current vintage there is no prior history, so both scores read the same.

    PRD: "`reliability_score_vintage` is 100 less the current-vintage penalty, floored at 0.0,
    ignoring prior vintages entirely."

    Design: Corner/validations/renewal_is_gated_by_both_the_window_and_the_lifetime_reliability_score
    """
    ctx = _a_producer_about_to_lose_its_standing()
    assert ctx["calls"][0]["ack_deadline_at"] == SHARED_ACK_DEADLINE_AT

    _let_every_call_expire()
    grower = read_grower(ctx["grower"]["id"])
    assert grower["expired_pick_call_count_vintage"] == EXPIRED_CALLS
    assert float(grower["reliability_score_vintage"]) == FIVE_EXPIRIES_SCORE
    assert float(grower["reliability_score_lifetime"]) == FIVE_EXPIRIES_SCORE
    assert read_pick_call(ctx["calls"][4]["id"])["status"] == "EXPIRED"


def test_the_lower_edge_of_the_window_opens_the_dimension(api):
    """The interval is half-open at the bottom in the inclusive sense: at the opening instant
    exactly, the clock has moved the renewal dimension on without any client asking.

    PRD: "All three of those edges are fired by the logical clock, not by a client: they require
    the lifecycle to be `ACTIVE` and the clock to have moved into the half-open interval that
    begins at `renewal_window_opens_at` and ends strictly before `renewal_window_closes_at`."

    Design: Corner/validations/renewal_is_gated_by_both_the_window_and_the_lifetime_reliability_score
    """
    ctx = _a_producer_about_to_lose_its_standing()
    _let_every_call_expire()

    move_clock(RENEWAL_WINDOW_OPENS_AT)
    contract = read_contract(ctx["contract"]["id"])
    assert contract["renewal_status"] == "RENEWAL_WINDOW_OPEN"
    assert contract["lifecycle_status"] == "ACTIVE"


def test_inside_the_open_window_the_standing_decides_instead(api):
    """With the window genuinely open the other half of the rank takes over: 75.0 is under the
    bar of 80.0, and the error identifier changes accordingly.

    PRD: "Four conditions must hold: the lifecycle is `ACTIVE`; `renewal_status` is
    `RENEWAL_WINDOW_OPEN`; the clock is still strictly before `renewal_window_closes_at`; and
    the producer's **lifetime-scoped** reliability score is at least 80.0."

    Design: Corner/validations/renewal_is_gated_by_both_the_window_and_the_lifetime_reliability_score
    """
    ctx = _a_producer_about_to_lose_its_standing()
    _let_every_call_expire()
    move_clock(RENEWAL_WINDOW_OPENS_AT)
    assert float(read_grower(ctx["grower"]["id"])["reliability_score_lifetime"]) < RENEWAL_BAR

    validate_error(
        _renew(api, ctx["contract"]["id"]),
        ApiErrorId.ERR_RELIABILITY_BELOW_RENEWAL_THRESHOLD.value,
        409,
    )


def test_once_the_window_shuts_the_dimension_is_terminal_and_the_window_objects_again(api):
    """The agreement was not evergreen, so reaching the closing instant drives the renewal
    dimension to its only terminal state — and from there the objection is the window one again,
    even though the standing is still the same 75.0.

    PRD: "With the flag false, `RENEWAL_WINDOW_OPEN → NOT_RENEWING`, and the renewal dimension
    stops there for good."

    Design: Corner/validations/renewal_is_gated_by_both_the_window_and_the_lifetime_reliability_score
    """
    ctx = _a_producer_about_to_lose_its_standing()
    _let_every_call_expire()
    move_clock(RENEWAL_WINDOW_OPENS_AT)

    move_clock(RENEWAL_WINDOW_CLOSES_AT)
    assert read_contract(ctx["contract"]["id"])["renewal_status"] == "NOT_RENEWING"
    validate_error(
        _renew(api, ctx["contract"]["id"]),
        ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN.value,
        409,
    )


def test_no_refused_renewal_ever_touched_the_term(api):
    """Three refusals across three different moments, and the agreement still runs to the vintage
    it was signed for — the renewal dimension never reaches back into the lifecycle one.

    PRD: "A successful renewal increases `term_end_vintage` by `renewal_term_years`, replaces
    `base_price_per_ton_cents` with `renewed_base_price_per_ton_cents` when that optional input
    was supplied and leaves it untouched otherwise"

    Design: Corner/validations/renewal_is_gated_by_both_the_window_and_the_lifetime_reliability_score
    """
    ctx = _a_producer_about_to_lose_its_standing()
    _renew(api, ctx["contract"]["id"])
    _let_every_call_expire()
    move_clock(RENEWAL_WINDOW_OPENS_AT)
    _renew(api, ctx["contract"]["id"])
    move_clock(RENEWAL_WINDOW_CLOSES_AT)
    _renew(api, ctx["contract"]["id"])

    contract = read_contract(ctx["contract"]["id"])
    assert contract["renewal_status"] == "NOT_RENEWING"
    assert contract["term_end_vintage"] == 2026
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract["base_price_per_ton_cents"] == 450000
