"""Conserved quantities, taken away and then given back.

Each scenario reads the quantity three times — before the move, after the move
and after the compensating move — and requires the third reading to equal the
first exactly rather than approximately, while the history the pair of requests
wrote stays on the record.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_census,
    assert_chargeback_ledger_matches,
    assert_pool_census_conserved,
)
from test_helpers.test_users import (
    ANALYST_USER_ID,
    SECOND_ANALYST_USER_ID,
    TEST_USERS,
    make_analyst_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]

CLOCK = "2026-08-01T23:00:00Z"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
    "restrict_threshold_pct": 25,
    "freeze_threshold_pct": 10,
    "restricted_max_kegs_per_order": 2,
}

AGREEMENT = {
    "per_fill_rate_cents": 2200,
    "replenishment_threshold_pct": 20,
}

CENSUS_FIELDS = (
    "kegs_total",
    "kegs_available",
    "kegs_circulating",
    "kegs_servicing",
    "kegs_held",
    "kegs_written_off",
)


def _census_vector(pool):
    """The five occupancy buckets plus the total, as one comparable tuple."""
    return tuple(pool[field] for field in CENSUS_FIELDS)


def _five_kegs_drawn_from_eight_and_then_handed_back():
    """An eight-keg pool, a ten-keg float, and one five-keg order that is
    allocated and then cancelled.

    The pool, the agreement, the order and every keg are read at all three
    points in the round trip, so the vector after the cancellation can be
    compared against the vector before the allocation field by field.
    """
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=8,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    agreement_id = ctx["agreement"]["id"]
    keg_ids = [keg["id"] for keg in ctx["kegs"]]
    order = fixtures.create_order(agreement_id, 5)

    ctx["before_pool"] = fixtures.read_pool(ctx["pool"]["id"])
    ctx["before_agreement"] = fixtures.read_agreement(agreement_id)
    ctx["before_kegs"] = {keg_id: fixtures.read_keg(keg_id) for keg_id in keg_ids}

    ctx["allocated_order"] = fixtures.allocate_order(order["id"], agreement_id)
    ctx["during_pool"] = fixtures.read_pool(ctx["pool"]["id"])
    ctx["during_agreement"] = fixtures.read_agreement(agreement_id)

    ctx["cancelled_order"] = fixtures.cancel_order(
        order["id"], cancel_reason="Brewer deferred the delivery window"
    )
    ctx["after_pool"] = fixtures.read_pool(ctx["pool"]["id"])
    ctx["after_agreement"] = fixtures.read_agreement(agreement_id)
    ctx["after_kegs"] = {keg_id: fixtures.read_keg(keg_id) for keg_id in keg_ids}

    ctx["keg_ids"] = keg_ids
    ctx["order"] = order
    return ctx


def test_the_allocation_transfers_five_kegs_between_two_buckets():
    """Before the draw the pool holds all eight kegs on the floor at 100.00
    percent; after it, five have moved from `kegs_available` into
    `kegs_circulating` and nowhere else, leaving 37.50 percent available and the
    pool still `OPEN`.

    PRD: "At the end of every request that changes any keg's `custody_state`, a
    pool's `kegs_total` must equal the sum of `kegs_available`,
    `kegs_circulating`, `kegs_servicing`, `kegs_held` and `kegs_written_off`, as
    exact integer equality with no tolerance."

    PRD: "Every custody movement is a transfer between two of those five
    buckets; only importing a keg raises `kegs_total`, and writing a keg off
    moves it into `kegs_written_off` rather than removing it from `kegs_total`."

    PRD: "The cascade then fires once, after all kegs have moved: the pool's
    `kegs_available` falls and `kegs_circulating` rises by the number allocated,
    `available_pct` and `posture` are recomputed and the pool's `version`
    advances, and every `ACTIVE` agreement on that pool recomputes
    `float_posture`, each advancing its own `version`."

    Design: Difficulty/compensating_invariant/pool_census_conserved_across_allocate_then_cancel
    """
    ctx = _five_kegs_drawn_from_eight_and_then_handed_back()

    before = ctx["before_pool"]
    assert_census(
        before,
        {
            "kegs_total": 8,
            "kegs_available": 8,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert before["available_pct"] == 100.00
    assert before["posture"] == "OPEN"

    during = ctx["during_pool"]
    assert_census(
        during,
        {
            "kegs_total": 8,
            "kegs_available": 3,
            "kegs_circulating": 5,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert during["available_pct"] == 37.50
    assert during["posture"] == "OPEN"

    order = ctx["allocated_order"]
    assert order["status"] == "ALLOCATED"
    assert order["allocated_keg_count"] == 5
    assert len(set(order["allocated_keg_ids"])) == 5
    assert order["allocation_shortfall"] == 0


def test_the_cancellation_restores_the_five_counter_vector_bit_for_bit():
    """The cancelled order gives back exactly the five kegs it named, and the
    pool's six-figure census reading, its availability percentage and its posture
    all return to the values they held before the draw.

    PRD: "Two compensating pairs must restore the five-counter vector bit for
    bit: allocating an order and then cancelling it moves kegs out of `IN_FLOAT`
    and back, leaving only each keg's `version` and `updated_at` changed; and
    placing kegs on evidence hold and then resuming the investigation moves them
    out of their buckets and back through each keg's `pre_hold_custody_state`,
    and does so correctly even when the held kegs were drawn from three
    different buckets."

    PRD: "The pool census, `available_pct` and `posture` are then recomputed
    back to exactly their pre-allocation values, and the agreement's counters and
    `float_posture` are recomputed, with the agreement's `version` advancing."

    Design: Difficulty/compensating_invariant/pool_census_conserved_across_allocate_then_cancel
    """
    ctx = _five_kegs_drawn_from_eight_and_then_handed_back()

    before = ctx["before_pool"]
    after = ctx["after_pool"]
    assert _census_vector(after) == _census_vector(before)
    assert _census_vector(after) == (8, 8, 0, 0, 0, 0)
    assert after["available_pct"] == before["available_pct"] == 100.00
    assert after["posture"] == before["posture"] == "OPEN"

    for pool in (before, ctx["during_pool"], after):
        assert_pool_census_conserved(pool)
        assert (
            pool["kegs_available"]
            + pool["kegs_circulating"]
            + pool["kegs_servicing"]
            + pool["kegs_held"]
            + pool["kegs_written_off"]
            == pool["kegs_total"]
            == 8
        )

    cancelled = ctx["cancelled_order"]
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "Brewer deferred the delivery window"
    assert cancelled["allocated_keg_ids"] == ctx["allocated_order"]["allocated_keg_ids"]


def test_every_returned_keg_is_stripped_of_its_brewer_and_its_dwell():
    """Each of the five kegs the order named is back in float with its brewer,
    its order and its dwell clock all cleared, while the three kegs the selector
    never touched are untouched down to their `version`.

    PRD: "Cancelling an allocated or partially allocated order returns exactly
    the kegs named in `allocated_keg_ids` — that is, `allocated_keg_count` kegs,
    not `requested_keg_count` — each moving `ISSUED_TO_BREWER → IN_FLOAT` while
    clearing `current_brewer_id`, `issuance_order_id` and `dwell_started_at`,
    resetting `dwell_flag` to `WITHIN_LIMIT`, and advancing its own `version`."

    PRD: "`allocated_keg_ids` is left in place as a historical record."

    Design: Difficulty/compensating_invariant/pool_census_conserved_across_allocate_then_cancel
    """
    ctx = _five_kegs_drawn_from_eight_and_then_handed_back()
    drawn = ctx["allocated_order"]["allocated_keg_ids"]
    untouched = [keg_id for keg_id in ctx["keg_ids"] if keg_id not in drawn]
    assert len(drawn) == 5
    assert len(untouched) == 3

    for keg_id in drawn:
        before = ctx["before_kegs"][keg_id]
        after = ctx["after_kegs"][keg_id]
        assert before["custody_state"] == "IN_FLOAT"
        assert after["custody_state"] == "IN_FLOAT"
        assert after["current_brewer_id"] is None
        assert after["issuance_order_id"] is None
        assert after["dwell_started_at"] is None
        assert after["dwell_flag"] == "WITHIN_LIMIT"
        assert after["fill_count"] == before["fill_count"]
        assert after["version"] > before["version"]

    for keg_id in untouched:
        before = ctx["before_kegs"][keg_id]
        after = ctx["after_kegs"][keg_id]
        assert after["custody_state"] == "IN_FLOAT"
        assert after["version"] == before["version"]
        assert after["updated_at"] == before["updated_at"]

    assert ctx["after_pool"]["version"] > ctx["before_pool"]["version"]


def test_the_agreement_counters_travel_out_and_back_with_the_kegs():
    """Five kegs at the brewer is well past the two-keg thin-float ceiling, so the
    float reads `HEALTHY` and signals no replenishment; once they are handed back
    the float is `TIGHT` again and the signal returns to the full ten kegs, with
    nothing billed either way.

    PRD: "`kegs_at_brewer_count` counts the kegs whose `current_brewer_id` is
    this agreement's brewer, whose `pool_id` is this agreement's pool, and whose
    `custody_state` is `ISSUED_TO_BREWER` or `FILLED`."

    PRD: "`kegs_issued_count` counts the kegs whose governing order belongs to
    this agreement and whose order `status` is `ALLOCATED`,
    `PARTIALLY_ALLOCATED` or `DISPATCHED`."

    PRD: "Flooring matters: a float of 10 kegs with a 20 percent threshold gives
    a ceiling of 2, so 2 kegs at the brewer reads `TIGHT` while 3 reads
    `HEALTHY`."

    PRD: "While the posture is `TIGHT` it is the float size minus
    `kegs_at_brewer_count`, or 0 if that difference would be negative."

    PRD: "While the posture is `HEALTHY` or `SUSPENDED` it is 0."

    Design: Difficulty/compensating_invariant/pool_census_conserved_across_allocate_then_cancel
    """
    ctx = _five_kegs_drawn_from_eight_and_then_handed_back()

    before = ctx["before_agreement"]
    assert before["float_size_kegs"] == 10
    assert before["kegs_at_brewer_count"] == 0
    assert before["kegs_issued_count"] == 0
    assert before["pending_replenishment_kegs"] == 10
    assert before["float_posture"] == "TIGHT"

    during = ctx["during_agreement"]
    assert during["kegs_at_brewer_count"] == 5
    assert during["kegs_issued_count"] == 5
    assert during["pending_replenishment_kegs"] == 0
    assert during["float_posture"] == "HEALTHY"

    after = ctx["after_agreement"]
    assert after["kegs_at_brewer_count"] == 0
    assert after["kegs_issued_count"] == 0
    assert after["pending_replenishment_kegs"] == 10
    assert after["float_posture"] == "TIGHT"

    for agreement in (before, during, after):
        assert agreement["status"] == "ACTIVE"
        assert agreement["billed_fills_count"] == 0
        assert agreement["billed_amount_cents"] == 0


def _a_full_replacement_loss_upheld_against_a_seven_fill_brewer():
    """Seven kegs of a ten-keg pool filled at 2200 cents apiece, then one of them
    written off at the pool's full 28200-cent replacement cost.

    The single uphold carries the brewer's ledger from zero past the 25000-cent
    probation line in one request, so the compensating reversal has a probation
    and a suspended float to undo as well as the money.
    """
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=10,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL, replacement_cost_cents=28200),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    agreement_id = ctx["agreement"]["id"]
    order = fixtures.order_allocated_and_dispatched(
        agreement_id, 7, "2026-08-01T01:00:00Z"
    )
    issued = order["allocated_keg_ids"]
    for keg_id in issued:
        fixtures.fill_scan(keg_id, ctx["brewer"]["id"], "2026-08-01T02:00:00Z", "RDG")

    ctx["before_brewer"] = fixtures.read_brewer(ctx["brewer"]["id"])
    ctx["before_agreement"] = fixtures.read_agreement(agreement_id)
    ctx["before_pool"] = fixtures.read_pool(ctx["pool"]["id"])

    proposed = fixtures.open_loss_assessment(
        issued[0],
        "NOT_RETURNED_DWELL",
        analyst_id=ANALYST_USER_ID,
        assessment_basis="REPLACEMENT_COST",
    )
    ctx["assessment"] = fixtures.resolve_assessment(
        proposed["id"],
        "UPHELD",
        analyst_id=SECOND_ANALYST_USER_ID,
        resolution_notes="Dwell exhausted; asset written off.",
    )
    ctx["during_brewer"] = fixtures.read_brewer(ctx["brewer"]["id"])
    ctx["during_agreement"] = fixtures.read_agreement(agreement_id)
    ctx["during_pool"] = fixtures.read_pool(ctx["pool"]["id"])

    ctx["order"] = order
    ctx["issued_keg_ids"] = issued
    ctx["lost_keg_id"] = issued[0]
    return ctx


def _reverse_the_chargeback(ctx):
    """Withdraw the issued chargeback and read every affected row back."""
    ctx["reversed_assessment"] = fixtures.reverse_chargeback(
        ctx["assessment"]["id"],
        analyst_id=SECOND_ANALYST_USER_ID,
        resolution_notes="Keg recovered by the distributor; charge withdrawn.",
    )
    ctx["after_brewer"] = fixtures.read_brewer(ctx["brewer"]["id"])
    ctx["after_agreement"] = fixtures.read_agreement(ctx["agreement"]["id"])
    ctx["after_pool"] = fixtures.read_pool(ctx["pool"]["id"])
    return ctx


def test_the_uphold_adds_the_net_amount_and_the_reversal_takes_it_back_exactly():
    """The ledger reads 0, then 28200, then 0 again — not 1, not -28200, and not
    28199 — because the reversal drops the row out of the sum rather than posting
    a compensating amount of its own.

    PRD: "The **chargeback ledger** is a conserved quantity: a brewer's
    `chargeback_balance_cents` is always the sum of `net_chargeback_cents` across
    that brewer's assessments whose `chargeback_status` is `ISSUED` or
    `SETTLED`."

    PRD: "A `REVERSE` also requires `ISSUED` and moves the status to `REVERSED`,
    which drops the row out of the sum and restores the balance to exactly its
    pre-uphold value — bit for bit, with no drift."

    Design: Difficulty/compensating_invariant/chargeback_ledger_conserved_across_uphold_then_reverse
    """
    ctx = _a_full_replacement_loss_upheld_against_a_seven_fill_brewer()

    assert ctx["before_brewer"]["chargeback_balance_cents"] == 0
    assert ctx["before_agreement"]["billed_amount_cents"] == 15136
    assert ctx["before_agreement"]["billed_fills_count"] == 7

    upheld = ctx["assessment"]
    assert upheld["net_chargeback_cents"] == 28200
    assert upheld["chargeback_status"] == "ISSUED"
    assert ctx["during_brewer"]["chargeback_balance_cents"] == 28200
    assert_chargeback_ledger_matches(ctx["during_brewer"], [upheld])

    _reverse_the_chargeback(ctx)

    reversed_row = ctx["reversed_assessment"]
    assert reversed_row["chargeback_status"] == "REVERSED"
    assert ctx["after_brewer"]["chargeback_balance_cents"] == 0
    assert (
        ctx["after_brewer"]["chargeback_balance_cents"]
        == ctx["before_brewer"]["chargeback_balance_cents"]
    )
    assert_chargeback_ledger_matches(ctx["after_brewer"], [reversed_row])


def test_the_reversal_keeps_the_valuation_and_the_written_off_shell():
    """Only the money is conserved: the assessment still reads `UPHELD` at the
    same 28200-cent valuation, the keg is still `LOST`, the pool still counts it
    written off at 30.00 percent availability, and the seven fills are still
    billed.

    PRD: "The assessment carries two entirely independent status dimensions:
    `assessment_status`, which records the adjudication, and `chargeback_status`,
    which records the money."

    PRD: "And the loss counters are money-independent — `upheld_loss_count` and
    both loss-rate figures are never recomputed by a reversal — so the trailing
    rate that forced probation still stands afterwards."

    Design: Difficulty/compensating_invariant/chargeback_ledger_conserved_across_uphold_then_reverse
    """
    ctx = _a_full_replacement_loss_upheld_against_a_seven_fill_brewer()
    _reverse_the_chargeback(ctx)

    reversed_row = ctx["reversed_assessment"]
    assert reversed_row["assessment_status"] == "UPHELD"
    assert reversed_row["net_chargeback_cents"] == 28200
    assert reversed_row["gross_value_cents"] == 28200
    assert reversed_row["scrap_credit_cents"] == 0
    assert reversed_row["settled_amount_cents"] is None

    after_brewer = ctx["after_brewer"]
    assert after_brewer["upheld_loss_count"] == 1
    assert (
        after_brewer["upheld_loss_count"]
        == ctx["during_brewer"]["upheld_loss_count"]
    )
    assert (
        after_brewer["loss_rate_bp_trailing_90d"]
        == ctx["during_brewer"]["loss_rate_bp_trailing_90d"]
    )
    assert (
        after_brewer["loss_rate_bp_lifetime"]
        == ctx["during_brewer"]["loss_rate_bp_lifetime"]
    )
    assert after_brewer["lifetime_fill_count"] == 7

    lost_keg = fixtures.read_keg(ctx["lost_keg_id"])
    assert lost_keg["custody_state"] == "LOST"
    assert lost_keg["assessment_open"] is False

    after_pool = ctx["after_pool"]
    assert after_pool["kegs_written_off"] == 1
    assert after_pool["kegs_circulating"] == 6
    assert after_pool["available_pct"] == 30.00
    assert_pool_census_conserved(after_pool)

    after_agreement = ctx["after_agreement"]
    assert after_agreement["billed_amount_cents"] == 15136
    assert after_agreement["billed_fills_count"] == 7


def test_the_reversal_lifts_the_probation_it_caused_and_frees_the_float():
    """The uphold put the brewer on probation for the balance and suspended a
    float whose pool never left `OPEN`; dropping the balance back under the line
    returns the brewer to `ACTIVE` with a cleared reason and lets the agreement
    recompute back to `HEALTHY`.

    PRD: "Because the balance was recomputed, the probation gate runs: when
    `chargeback_balance_cents` is at or above 25000 cents and the brewer's
    `status` is `ACTIVE`, the brewer moves to `PROBATION` with `status_reason`
    recorded as `CHARGEBACK_BALANCE_THRESHOLD`."

    PRD: "Because the brewer entered probation, every `ACTIVE` float agreement of
    that brewer recomputes `float_posture` to `SUSPENDED`, which blocks that
    brewer's later allocations and fill scans."

    PRD: "A reversal that drops the balance back below 25000 cents lifts the
    probation it caused, but only that one: the brewer returns to `ACTIVE` with
    `status_reason` cleared **only** when the current `status` is `PROBATION`
    *and* the current `status_reason` is `CHARGEBACK_BALANCE_THRESHOLD`, which in
    turn releases the `SUSPENDED` float posture on that brewer's `ACTIVE`
    agreements."

    Design: Difficulty/compensating_invariant/chargeback_ledger_conserved_across_uphold_then_reverse
    """
    ctx = _a_full_replacement_loss_upheld_against_a_seven_fill_brewer()

    assert ctx["before_brewer"]["status"] == "ACTIVE"
    assert ctx["before_brewer"]["status_reason"] is None
    assert ctx["before_agreement"]["float_posture"] == "HEALTHY"

    assert ctx["during_brewer"]["status"] == "PROBATION"
    assert ctx["during_brewer"]["status_reason"] == "CHARGEBACK_BALANCE_THRESHOLD"
    assert ctx["during_agreement"]["float_posture"] == "SUSPENDED"
    assert ctx["during_pool"]["posture"] == "OPEN"
    assert ctx["during_pool"]["available_pct"] == 30.00

    _reverse_the_chargeback(ctx)

    assert ctx["after_brewer"]["status"] == "ACTIVE"
    assert ctx["after_brewer"]["status_reason"] is None
    assert ctx["after_agreement"]["status"] == "ACTIVE"
    assert ctx["after_agreement"]["float_posture"] == "HEALTHY"
    assert ctx["after_pool"]["posture"] == "OPEN"
    assert ctx["after_pool"]["available_pct"] == 30.00


def test_no_single_role_can_both_raise_and_erase_the_charge():
    """The desk that benefits from the charge cannot withdraw it and the desk that
    raised it cannot mark it paid, and the role check bites before the settlement
    amount is even looked at.

    PRD: "Both `PoolOperator` and `AssetRecoveryAnalyst` reach this operation, but
    the acting role must match the requested action: `SETTLE` requires
    `PoolOperator` and `REVERSE` requires `AssetRecoveryAnalyst`, so no single
    role can both raise and erase a chargeback."

    PRD: "A mismatch is `ERR_SEGREGATION_OF_DUTIES`, and it is judged *before* the
    settlement amount is compared — an analyst attempting a settlement with the
    wrong amount sees the segregation failure, not the amount failure."

    Design: Difficulty/compensating_invariant/chargeback_ledger_conserved_across_uphold_then_reverse
    """
    ctx = _a_full_replacement_loss_upheld_against_a_seven_fill_brewer()
    assessment_id = ctx["assessment"]["id"]

    refused_reversal = api_client.chargeback_resolution(
        assessment_id,
        factories.chargeback_resolution_payload(
            "REVERSE", resolution_notes="Keg recovered by the distributor."
        ),
        OPERATOR,
    )
    validate_error(refused_reversal, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    refused_settlement = api_client.chargeback_resolution(
        assessment_id,
        factories.chargeback_resolution_payload("SETTLE", amount_cents=27000),
        make_analyst_headers(SECOND_ANALYST_USER_ID),
    )
    validate_error(refused_settlement, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    unmoved = fixtures.read_assessment(assessment_id)
    assert unmoved["chargeback_status"] == "ISSUED"
    assert unmoved["settled_amount_cents"] is None
    assert fixtures.read_brewer(ctx["brewer"]["id"])["chargeback_balance_cents"] == 28200

    _reverse_the_chargeback(ctx)
    assert ctx["reversed_assessment"]["chargeback_status"] == "REVERSED"
    assert ctx["after_brewer"]["chargeback_balance_cents"] == 0
