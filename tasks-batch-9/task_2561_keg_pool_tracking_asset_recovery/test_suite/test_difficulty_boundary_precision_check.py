"""Values landing exactly on a declared threshold, and the empty-set edge.

Each scenario walks a figure onto the boundary the contract names, reads the
outcome there, and then moves one step past it so the inclusive side and the
exclusive side are both observed against the same fixture.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
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


def _order_attempt(agreement_id, requested_keg_count):
    return api_client.create_issuance_order(
        factories.create_issuance_order_payload(agreement_id, requested_keg_count),
        OPERATOR,
    )


def _pool_at_two_of_eight_kegs_available():
    """An eight-keg pool with six kegs drawn out, which leaves `available_pct`
    exactly on the pool's 25 percent restrict threshold."""
    ctx = fixtures.setup_active_float(
        float_size_kegs=10,
        keg_count=8,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    first_order = fixtures.create_order(ctx["agreement"]["id"], 6)
    fixtures.allocate_order(first_order["id"], ctx["agreement"]["id"])
    ctx["first_order"] = first_order
    ctx["pool_at_threshold"] = fixtures.read_pool(ctx["pool"]["id"])
    return ctx


def test_available_pct_exactly_at_the_restrict_threshold_reads_open():
    """Two kegs of eight on the floor is exactly 25.00 percent against a restrict
    threshold of 25, and the inclusive comparison keeps the pool `OPEN`.

    PRD: "Both comparisons are inclusive, so an `available_pct` exactly equal to
    `restrict_threshold_pct` reads `OPEN` and one exactly equal to
    `freeze_threshold_pct` reads `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/pool_available_pct_exactly_at_restrict_threshold_stays_open
    """
    ctx = _pool_at_two_of_eight_kegs_available()
    pool = ctx["pool_at_threshold"]

    assert pool["restrict_threshold_pct"] == 25
    assert pool["kegs_total"] == 8
    assert pool["kegs_available"] == 2
    assert pool["kegs_circulating"] == 6
    assert pool["available_pct"] == 25.00
    assert pool["posture"] == "OPEN"


def test_an_open_pool_at_the_threshold_does_not_cap_the_order_size():
    """The per-order ceiling belongs to the `RESTRICTED` posture alone, so at
    exactly 25.00 percent a three-keg request is accepted even though the pool's
    restricted ceiling is two, and cancelling it leaves the figure untouched.

    PRD: "While the pool's `posture` is `RESTRICTED`, `requested_keg_count` does
    not exceed the pool's `restricted_max_kegs_per_order` — `ERR_POOL_RESTRICTED`
    (409), on order creation and order allocation."

    Design: Difficulty/boundary_precision_check/pool_available_pct_exactly_at_restrict_threshold_stays_open
    """
    ctx = _pool_at_two_of_eight_kegs_available()
    assert ctx["pool"]["restricted_max_kegs_per_order"] == 2

    accepted = validate_success(_order_attempt(ctx["agreement"]["id"], 3), 201)
    assert accepted["requested_keg_count"] == 3
    assert accepted["status"] == "REQUESTED"

    at_threshold = fixtures.read_pool(ctx["pool"]["id"])
    assert at_threshold["available_pct"] == 25.00
    assert at_threshold["posture"] == "OPEN"

    cancelled = fixtures.cancel_order(
        accepted["id"], cancel_reason="boundary probe, releasing the request"
    )
    assert cancelled["status"] == "CANCELLED"

    after_cancel = fixtures.read_pool(ctx["pool"]["id"])
    assert after_cancel["kegs_available"] == 2
    assert after_cancel["available_pct"] == 25.00
    assert after_cancel["posture"] == "OPEN"


def test_one_keg_below_the_threshold_restricts_the_pool_and_caps_the_order():
    """Drawing a seventh keg puts the pool at 12.50 percent, under the restrict
    threshold and above the freeze threshold, and the identical three-keg request
    that was accepted at the boundary is now refused while two still fits.

    PRD: "When `kegs_total` is greater than zero and `available_pct` is below
    `restrict_threshold_pct` but greater than or equal to `freeze_threshold_pct`,
    the posture is `RESTRICTED`."

    PRD: "While the pool's `posture` is `RESTRICTED`, `requested_keg_count` does
    not exceed the pool's `restricted_max_kegs_per_order` — `ERR_POOL_RESTRICTED`
    (409), on order creation and order allocation."

    Design: Difficulty/boundary_precision_check/pool_available_pct_exactly_at_restrict_threshold_stays_open
    """
    ctx = _pool_at_two_of_eight_kegs_available()
    agreement_id = ctx["agreement"]["id"]

    seventh = fixtures.create_order(agreement_id, 1)
    fixtures.allocate_order(seventh["id"], agreement_id)

    restricted = fixtures.read_pool(ctx["pool"]["id"])
    assert restricted["kegs_available"] == 1
    assert restricted["kegs_circulating"] == 7
    assert restricted["available_pct"] == 12.50
    assert restricted["posture"] == "RESTRICTED"

    refused = _order_attempt(agreement_id, 3)
    validate_error(refused, ApiErrorId.ERR_POOL_RESTRICTED.value, 409)

    control = validate_success(_order_attempt(agreement_id, 2), 201)
    assert control["requested_keg_count"] == 2
    assert control["status"] == "REQUESTED"

    unchanged = fixtures.read_pool(ctx["pool"]["id"])
    assert unchanged["available_pct"] == 12.50
    assert unchanged["posture"] == "RESTRICTED"

    agreement = fixtures.read_agreement(agreement_id)
    assert agreement["kegs_at_brewer_count"] == 7
    assert agreement["float_posture"] == "HEALTHY"
    assert agreement["pending_replenishment_kegs"] == 0


def _upheld_loss_on_a_keg_that_was_never_filled():
    """One keg allocated to a brewer but never dispatched and never filled, then
    reported as a suspected theft and upheld.

    The brewer therefore carries one upheld loss against a fill history that is
    empty on both bases, which is the zero-denominator edge of the loss rate.
    """
    ctx = fixtures.setup_active_float(
        float_size_kegs=4,
        keg_count=4,
        brewer_overrides={"credit_limit_cents": 400000},
        pool_overrides=dict(POOL),
        agreement_overrides=dict(AGREEMENT),
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    order = fixtures.create_order(ctx["agreement"]["id"], 1)
    fixtures.allocate_order(order["id"], ctx["agreement"]["id"])
    keg_id = fixtures.read_order(order["id"])["allocated_keg_ids"][0]

    proposed = fixtures.open_loss_assessment(
        keg_id,
        "STOLEN_SUSPECTED",
        analyst_id=ANALYST_USER_ID,
        assessment_basis="REPLACEMENT_COST",
    )
    ctx["assessment"] = fixtures.resolve_assessment(
        proposed["id"],
        "UPHELD",
        analyst_id=SECOND_ANALYST_USER_ID,
        resolution_notes="Tag last read at the yard; no fills on this asset.",
    )
    ctx["order"] = order
    ctx["keg_id"] = keg_id
    return ctx


def _loss_rate(brewer_id, basis):
    return get_success_data(
        api_client.get_brewer_loss_rate(
            brewer_id,
            make_analyst_headers(ANALYST_USER_ID),
            params={"basis": basis},
        )
    )


def test_a_zero_fill_denominator_reports_no_rate_and_an_insufficient_basis():
    """One upheld loss over an empty fill set does not divide: the trailing read
    reports 0 basis points, flags the basis insufficient, and still names the
    inclusive ninety-day window it looked in.

    PRD: "In both cases, a zero denominator reports a rate of 0 and marks the
    basis insufficient; otherwise the rate is 10000 multiplied by the numerator,
    divided by the denominator, rounded half up — one upheld loss over three
    fills is 3333 basis points, not 3334."

    PRD: "The trailing variant counts, inside a window running from 90 days
    before the logical clock through the clock itself with both ends inclusive,
    the brewer's `UPHELD` assessments by `created_at` as the numerator and the
    brewer's fill scans by `scanned_at` as the denominator."

    Design: Difficulty/boundary_precision_check/loss_rate_zero_denominator_empty_fill_set
    """
    ctx = _upheld_loss_on_a_keg_that_was_never_filled()
    trailing = _loss_rate(ctx["brewer"]["id"], "TRAILING_90D")

    assert trailing["brewer_id"] == ctx["brewer"]["id"]
    assert trailing["basis"] == "TRAILING_90D"
    assert trailing["upheld_loss_count"] == 1
    assert trailing["fill_count"] == 0
    assert trailing["basis_insufficient"] is True
    assert trailing["loss_rate_bp"] == 0
    assert trailing["loss_rate_bp"] != 10000
    assert trailing["window_start"] == "2026-05-03T23:00:00Z"
    assert trailing["window_end"] == "2026-08-01T23:00:00Z"


def test_the_lifetime_basis_reports_no_window_and_persists_nothing():
    """Read on the lifetime basis the same empty denominator gives the same 0,
    the two window fields come back unset, and reading twice leaves the brewer's
    stored figures exactly where they were.

    PRD: "The loss rate is also readable on demand for one brewer under a `basis`
    query parameter that defaults to `TRAILING_90D` and also accepts `LIFETIME`;
    the read reports `brewer_id`, `basis`, `loss_rate_bp`, `upheld_loss_count`,
    `fill_count`, `window_start`, `window_end` and `basis_insufficient`, returns
    unset `window_start` and `window_end` for the lifetime basis, and persists
    nothing."

    PRD: "The lifetime variant uses the unwindowed `upheld_loss_count` over
    `lifetime_fill_count`."

    Design: Difficulty/boundary_precision_check/loss_rate_zero_denominator_empty_fill_set
    """
    ctx = _upheld_loss_on_a_keg_that_was_never_filled()
    before = fixtures.read_brewer(ctx["brewer"]["id"])

    lifetime = _loss_rate(ctx["brewer"]["id"], "LIFETIME")
    assert lifetime["basis"] == "LIFETIME"
    assert lifetime["fill_count"] == 0
    assert lifetime["basis_insufficient"] is True
    assert lifetime["loss_rate_bp"] == 0
    assert lifetime["loss_rate_bp"] != 10000
    assert lifetime["window_start"] is None
    assert lifetime["window_end"] is None

    repeated = _loss_rate(ctx["brewer"]["id"], "LIFETIME")
    assert repeated == lifetime

    after = fixtures.read_brewer(ctx["brewer"]["id"])
    assert after["lifetime_fill_count"] == 0
    assert after["loss_rate_bp_trailing_90d"] == 0
    assert after["loss_rate_bp_lifetime"] == 0
    assert after["version"] == before["version"]
    assert after["updated_at"] == before["updated_at"]


def test_a_suspected_theft_is_valued_in_full_but_charges_the_brewer_nothing():
    """The upheld assessment values the shell at the pool's replacement cost with
    no scrap credit, but a suspected theft carries no brewer liability, so the
    net is 0, no chargeback is issued, and the keg's custody is left alone.

    PRD: "`brewer_liability_pct_bp` is keyed off the cause alone: 6000 basis
    points for `LOST_IN_TRADE`, 10000 for `DAMAGED_BEYOND_REPAIR`, 10000 for
    `NOT_RETURNED_DWELL` and 0 for `STOLEN_SUSPECTED`."

    PRD: "The assessment moves to `UPHELD` and, when `net_chargeback_cents` is
    greater than zero, `chargeback_status` flips from `NONE` to `ISSUED` in the
    same request."

    PRD: "The keg is written off according to the cause: `DAMAGED_BEYOND_REPAIR`
    scraps it, `LOST_IN_TRADE` and `NOT_RETURNED_DWELL` mark it lost, and
    `STOLEN_SUSPECTED` leaves custody alone."

    Design: Difficulty/boundary_precision_check/loss_rate_zero_denominator_empty_fill_set
    """
    ctx = _upheld_loss_on_a_keg_that_was_never_filled()
    assessment = ctx["assessment"]

    assert assessment["assessment_status"] == "UPHELD"
    assert assessment["cause"] == "STOLEN_SUSPECTED"
    assert assessment["assessment_basis"] == "REPLACEMENT_COST"
    assert assessment["gross_value_cents"] == 23500
    assert assessment["scrap_credit_cents"] == 0
    assert assessment["assessed_value_cents"] == 23500
    assert assessment["brewer_liability_pct_bp"] == 0
    assert assessment["net_chargeback_cents"] == 0
    assert assessment["chargeback_status"] == "NONE"

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 0
    assert brewer["status"] == "ACTIVE"
    assert brewer["status_reason"] is None

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "ISSUED_TO_BREWER"
    assert keg["assessment_open"] is False

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert pool["kegs_written_off"] == 0
    assert pool["kegs_circulating"] == 1
    assert pool["kegs_available"] == 3
