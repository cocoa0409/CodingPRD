"""The weigh tag's two parallel dimensions: a weight capture that terminates at
`NET_FINAL` and a receipt decision that cycles through a dispute and back."""
from test_helpers import (
    dispute_grading,
    list_gradings,
    list_settlement_lines,
    move_clock,
    read_contract,
    read_weigh_tag,
    record_grading,
    setup_single_load_on_pad,
    single_installment_plan,
)

ARRIVAL_AT = "2026-08-25T14:30:00Z"
DISPUTE_AT = "2026-08-26T10:00:00Z"
DISPUTE_DEADLINE_AT = "2026-08-28T14:30:00Z"


def _load_on_the_pad() -> dict:
    """One 22.000-ton load, weighed and tared, on a 40.000-ton TONNAGE contract."""
    return setup_single_load_on_pad(
        contract_overrides={
            "base_price_per_ton_cents": 450000,
            "committed_tons": 40.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "installment_plan": single_installment_plan(),
        },
        net_tons=22.000,
        tare_weight_lbs=17240,
        estimated_tons=40.000,
        arrival_at=ARRIVAL_AT,
    )


def _first_grading(ctx: dict) -> dict:
    return record_grading(ctx["tag"]["id"], brix=28.0, ta_gl=6.5, ph=3.60, rot_pct=1.0, mog_pct=0.5)


def test_tare_terminates_the_weight_dimension_and_leaves_the_decision_pending():
    """The outbound pass finishes the weighing for good, yet the receipt decision has
    not begun: an ungraded load is `NET_FINAL` and still `PENDING`.

    PRD: "The tare also recomputes the appointment's `captured_net_tons`, and it leaves
    the receipt-decision dimension untouched at `PENDING`. `NET_FINAL` is the terminal
    state of the weight dimension."

    Design: Difficulty/non_linear_state_machine/weigh_tag_parallel_weigh_and_disposition_dimensions_with_dispute_cycle
    """
    ctx = _load_on_the_pad()
    tag = read_weigh_tag(ctx["tag"]["id"])

    assert tag["weigh_status"] == "NET_FINAL"
    assert tag["disposition"] == "PENDING"
    assert float(tag["net_tons"]) == 22.000
    assert tag["grade_count"] == 0
    assert tag["active_adjustment_pct"] is None
    assert tag["dispute_deadline_at"] is None


def test_first_grading_decides_the_load_without_moving_the_weight_dimension():
    """A Brix 28.0 reading accepts the load and stamps the 72-hour dispute deadline,
    while the weight dimension stays exactly where the tare left it.

    PRD: "`dispute_deadline_at` is stamped only when it is still null, at the first
    grading instant plus 72 hours, and a re-grade never re-stamps it."

    Design: Difficulty/non_linear_state_machine/weigh_tag_parallel_weigh_and_disposition_dimensions_with_dispute_cycle
    """
    ctx = _load_on_the_pad()
    _first_grading(ctx)

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["disposition"] == "ACCEPTED"
    assert tag["weigh_status"] == "NET_FINAL"
    assert tag["grade_count"] == 1
    assert float(tag["active_adjustment_pct"]) == 8.0
    assert tag["dispute_deadline_at"] == DISPUTE_DEADLINE_AT


def test_dispute_unwinds_the_decision_and_voids_the_line():
    """Raising a dispute returns the tag to a contested state, resets its tonnage
    slices and voids the provisional money — but the tonnage on the scale is untouched.

    PRD: "Because the active grading was superseded, every settlement line of that tag
    in status `PROVISIONAL` transitions to `VOID` with `voided_at` stamped from the
    logical clock"

    Design: Difficulty/non_linear_state_machine/weigh_tag_parallel_weigh_and_disposition_dimensions_with_dispute_cycle
    """
    ctx = _load_on_the_pad()
    _first_grading(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(ctx["tag"]["id"], ctx["grower"]["id"], reason="grower contests the sampling probe location")

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["disposition"] == "DISPUTED"
    assert tag["weigh_status"] == "NET_FINAL"
    assert float(tag["net_tons"]) == 22.000
    assert float(tag["contract_slice_tons"]) == 0.000
    assert tag["active_adjustment_pct"] is None

    lines = list_settlement_lines(weigh_tag_id=tag["id"])
    assert len(lines) == 1
    assert lines[0]["status"] == "VOID"
    assert lines[0]["voided_at"] == DISPUTE_AT

    contract = read_contract(ctx["contract"]["id"])
    assert float(contract["delivered_contract_tons"]) == 0.000
    assert contract["tonnage_status"] == "OPEN"


def test_re_grade_returns_the_decision_to_a_state_it_already_occupied():
    """The disposition dimension cycles back to `ACCEPTED` with a second grading and a
    different active adjustment, while the weighed tonnage never changes.

    PRD: "The two edges worth naming explicitly are `DISPUTED → ACCEPTED`, when the
    reading accepts and the waterfall leaves both `over_rejected_tons` and
    `excess_rejected_tons` at 0.000"

    Design: Difficulty/non_linear_state_machine/weigh_tag_parallel_weigh_and_disposition_dimensions_with_dispute_cycle
    """
    ctx = _load_on_the_pad()
    _first_grading(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(ctx["tag"]["id"], ctx["grower"]["id"])
    record_grading(ctx["tag"]["id"], brix=25.0, ta_gl=6.5, ph=3.55, rot_pct=1.0, mog_pct=0.5)

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["disposition"] == "ACCEPTED"
    assert tag["weigh_status"] == "NET_FINAL"
    assert tag["grade_count"] == 2
    assert float(tag["active_adjustment_pct"]) == 3.0
    assert float(tag["net_tons"]) == 22.000
    assert float(tag["contract_slice_tons"]) == 22.000


def test_re_grade_never_re_stamps_the_dispute_deadline():
    """The deadline belongs to the first grading instant, so a second grading a day
    later does not buy the producer another 72 hours.

    PRD: "a re-grade never re-stamps it"

    Design: Difficulty/non_linear_state_machine/weigh_tag_parallel_weigh_and_disposition_dimensions_with_dispute_cycle
    """
    ctx = _load_on_the_pad()
    _first_grading(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(ctx["tag"]["id"], ctx["grower"]["id"])
    record_grading(ctx["tag"]["id"], brix=25.0, ta_gl=6.5, ph=3.55, rot_pct=1.0, mog_pct=0.5)

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["dispute_deadline_at"] == DISPUTE_DEADLINE_AT


def test_superseded_grading_history_is_append_only():
    """Both lab readings survive the cycle; only the newest one has a null
    `superseded_at`.

    PRD: "the newly written grading becomes the sole row with a null `superseded_at`"

    Design: Difficulty/non_linear_state_machine/weigh_tag_parallel_weigh_and_disposition_dimensions_with_dispute_cycle
    """
    ctx = _load_on_the_pad()
    first = _first_grading(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(ctx["tag"]["id"], ctx["grower"]["id"])
    second = record_grading(ctx["tag"]["id"], brix=25.0, ta_gl=6.5, ph=3.55, rot_pct=1.0, mog_pct=0.5)

    gradings = {row["id"]: row for row in list_gradings(weigh_tag_id=ctx["tag"]["id"])}
    assert len(gradings) == 2
    assert gradings[first["id"]]["superseded_at"] == DISPUTE_AT
    assert gradings[second["id"]]["superseded_at"] is None


def test_re_grade_prices_a_fresh_line_and_the_void_line_is_not_counted():
    """The second reading strikes its own price, and the contract's provisional money
    counts only the live line.

    PRD: "the third the sum of `provisional_amount_cents` over its `PROVISIONAL` lines"

    Design: Difficulty/non_linear_state_machine/weigh_tag_parallel_weigh_and_disposition_dimensions_with_dispute_cycle
    """
    ctx = _load_on_the_pad()
    _first_grading(ctx)
    move_clock(DISPUTE_AT)
    dispute_grading(ctx["tag"]["id"], ctx["grower"]["id"])
    record_grading(ctx["tag"]["id"], brix=25.0, ta_gl=6.5, ph=3.55, rot_pct=1.0, mog_pct=0.5)

    live = [line for line in list_settlement_lines(weigh_tag_id=ctx["tag"]["id"]) if line["status"] == "PROVISIONAL"]
    assert len(live) == 1
    assert live[0]["price_per_ton_cents"] == 463500
    assert live[0]["provisional_amount_cents"] == 6118200

    contract = read_contract(ctx["contract"]["id"])
    assert contract["provisional_settlement_cents"] == 6118200
