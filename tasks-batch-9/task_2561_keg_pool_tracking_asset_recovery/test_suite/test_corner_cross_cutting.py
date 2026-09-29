"""Cross-cutting layers: version arithmetic, cascade depth and coercion.

The scenarios here are deliberately the ones where several independent layers
of the specification meet inside a single request — a version counter that must
move exactly once however many cascade links name the row, an import that
reaches four rows deep and flips a later verdict, a valuation input the server
silently overrules, and two threshold gates arming in the same uphold.  Every
scenario reads back both the rows the request was meant to move and the rows it
was meant to leave alone.
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
from test_helpers.assertions import assert_census
from test_helpers.test_users import (
    ANALYST_USER_ID,
    SECOND_ANALYST_USER_ID,
    TEST_USERS,
    make_analyst_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
ANALYST = make_analyst_headers(ANALYST_USER_ID)
SECOND_ANALYST = make_analyst_headers(SECOND_ANALYST_USER_ID)

CLOCK = "2026-08-01T23:00:00Z"
EFFECTIVE_DATE = "2026-08-01"

POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
}
BIG_POOL = {
    "pool_code": "HB-BIG",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 50000,
    "region_code": "CO",
}
RATE = 2200


def _census(pool, available, circulating, servicing, held, written_off, total):
    assert_census(
        pool,
        {
            "kegs_total": total,
            "kegs_available": available,
            "kegs_circulating": circulating,
            "kegs_servicing": servicing,
            "kegs_held": held,
            "kegs_written_off": written_off,
        },
    )


# ==========================================================================
# Design: Corner/Cross-Cutting Complexity Layers/one_request_bumps_each_touched_row_exactly_once_however_many_cascade_links_hit_it
# ==========================================================================


def _a_four_keg_pool_with_an_activated_float_and_an_order_for_two():
    """One brewer, one pool stocked with four kegs by four separate imports, one
    agreement drafted and activated over them, and one `REQUESTED` order asking
    for two kegs — so the allocate to come moves two kegs in one request.
    """
    fixtures.pin_clock(CLOCK)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    kegs = fixtures.import_kegs(
        pool["id"], ["K-0001", "K-0002", "K-0003", "K-0004"]
    )
    drafted = fixtures.create_agreement(
        brewer["id"], pool["id"], 4, per_fill_rate_cents=RATE
    )
    agreement = fixtures.activate_agreement(drafted["id"], EFFECTIVE_DATE)
    order = fixtures.create_order(agreement["id"], 2)
    return {
        "brewer": brewer,
        "pool": pool,
        "kegs": kegs,
        "drafted": drafted,
        "agreement": agreement,
        "order": order,
        "pool_version_before": fixtures.read_pool(pool["id"])["version"],
    }


def test_one_allocate_bumps_the_agreement_once_although_two_links_name_it():
    """The allocate writes the agreement's own counters and also re-evaluates
    every active agreement on the pool, moves two kegs through one census
    recompute, and still advances the agreement 2 to 3, the pool by one and each
    moved keg by one — while the brewer, which the request never touched, stays
    at the version it was created with.

    PRD: "Most resources additionally carry `updated_at`, refreshed on every
    mutation, and `version`, an integer that starts at 1 and increments as
    described below."

    PRD: "A single request advances each affected row's `version` by exactly
    one, no matter how many cascade links inside that request touch that row."

    PRD: "Allocating an issuance order, for example, both writes the agreement's
    own counters and re-evaluates the posture of every active agreement on the
    pool; for the allocating agreement those are the same bump, so its `version`
    moves from 2 to 3, never from 2 to 4."

    PRD: "A pool maintains a five-bucket census plus a total, all recomputed at
    the end of any request that changes a keg's `custody_state` in that pool and
    also at each keg import."

    PRD: "On success the agreement moves `DRAFT → ACTIVE`, records the
    `effective_date`, computes `float_posture` for the first time, and advances
    its `version`."

    PRD: "Each allocated keg moves `IN_FLOAT → ISSUED_TO_BREWER`, records
    `current_brewer_id` from the agreement and `issuance_order_id` from the
    order, sets `dwell_started_at` to the logical clock, sets `dwell_flag` to
    `WITHIN_LIMIT`, and advances its own `version`."

    PRD: "The cascade then fires once, after all kegs have moved: the pool's
    `kegs_available` falls and `kegs_circulating` rises by the number allocated,
    `available_pct` and `posture` are recomputed and the pool's `version`
    advances, and every `ACTIVE` agreement on that pool recomputes
    `float_posture`, each advancing its own `version`."

    PRD: "Otherwise the leading kegs in rank order are taken:
    `allocated_keg_ids` records their ids in rank order as a reporting
    convenience that is never an input to any later decision,
    `allocated_keg_count` records how many were taken, `allocation_shortfall`
    records `requested_keg_count` minus that number, and
    `per_fill_price_cents_pinned` copies the agreement's `per_fill_rate_cents`
    at this moment, so later edits to the agreement do not retro-price this
    order's fills."

    Design: Corner/Cross-Cutting Complexity Layers/one_request_bumps_each_touched_row_exactly_once_however_many_cascade_links_hit_it
    """
    ctx = _a_four_keg_pool_with_an_activated_float_and_an_order_for_two()
    agreement_id = ctx["agreement"]["id"]

    assert ctx["drafted"]["version"] == 1
    assert ctx["agreement"]["version"] == 2
    assert ctx["pool"]["version"] == 1
    assert ctx["pool_version_before"] == 5
    assert ctx["order"]["version"] == 1

    allocated = validate_success(
        api_client.allocate_issuance_order(
            ctx["order"]["id"],
            {"expected_agreement_version": ctx["agreement"]["version"]},
            OPERATOR,
        ),
        200,
    )

    assert fixtures.read_agreement(agreement_id)["version"] == 3
    assert fixtures.read_pool(ctx["pool"]["id"])["version"] == 6

    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_keg_count"] == 2
    assert allocated["allocation_shortfall"] == 0
    assert allocated["per_fill_price_cents_pinned"] == RATE
    assert allocated["version"] == 2

    moved_ids = allocated["allocated_keg_ids"]
    assert len(moved_ids) == 2
    for keg_id in moved_ids:
        moved = fixtures.read_keg(keg_id)
        assert moved["custody_state"] == "ISSUED_TO_BREWER"
        assert moved["version"] == 2

    untouched = [keg["id"] for keg in ctx["kegs"] if keg["id"] not in moved_ids]
    for keg_id in untouched:
        still_in_float = fixtures.read_keg(keg_id)
        assert still_in_float["custody_state"] == "IN_FLOAT"
        assert still_in_float["version"] == 1

    assert fixtures.read_brewer(ctx["brewer"]["id"])["version"] == 1


def test_reads_never_advance_a_version_and_the_counters_move_once_together():
    """Six reads taken after the allocate report the same version numbers as the
    first read of each row, and the agreement's four allocation-driven fields
    all reflect the single bump: two kegs issued, two at the brewer, a float
    that is no longer thin at the floored 20 percent ceiling of a four-keg
    float, and therefore no replenishment signal.

    PRD: "Reads never advance a `version`."

    PRD: "The allocating agreement additionally refreshes `kegs_issued_count`,
    `kegs_at_brewer_count` and `pending_replenishment_kegs` — all inside the
    same single version bump."

    PRD: "Two optional terms may be supplied: `replenishment_threshold_pct`, an
    integer from 0 to 100 defaulting to 20, which is the percentage of the float
    size at or below which the float counts as thin; and `min_fills_per_month`,
    at least 0 and defaulting to 0, which is recorded for reporting and is
    enforced by no transition anywhere in the system."

    PRD: "`kegs_at_brewer_count` counts the kegs whose `current_brewer_id` is
    this agreement's brewer, whose `pool_id` is this agreement's pool, and whose
    `custody_state` is `ISSUED_TO_BREWER` or `FILLED`."

    PRD: "`kegs_issued_count` counts the kegs whose governing order belongs to
    this agreement and whose order `status` is `ALLOCATED`,
    `PARTIALLY_ALLOCATED` or `DISPATCHED`."

    PRD: "Otherwise, letting the thin-float ceiling be `float_size_kegs`
    multiplied by `replenishment_threshold_pct`, divided by 100 and floored to a
    whole number of kegs, the agreement is `TIGHT` when `kegs_at_brewer_count`
    is less than or equal to that ceiling, and `HEALTHY` otherwise."

    PRD: "While the posture is `HEALTHY` or `SUSPENDED` it is 0."

    Design: Corner/Cross-Cutting Complexity Layers/one_request_bumps_each_touched_row_exactly_once_however_many_cascade_links_hit_it
    """
    ctx = _a_four_keg_pool_with_an_activated_float_and_an_order_for_two()
    agreement_id = ctx["agreement"]["id"]
    pool_id = ctx["pool"]["id"]
    order_id = ctx["order"]["id"]

    assert ctx["agreement"]["float_posture"] == "TIGHT"
    assert ctx["agreement"]["pending_replenishment_kegs"] == 4
    assert ctx["agreement"]["kegs_at_brewer_count"] == 0
    assert ctx["agreement"]["kegs_issued_count"] == 0

    fixtures.allocate_order(order_id, agreement_id)

    first = {
        "agreement": fixtures.read_agreement(agreement_id)["version"],
        "pool": fixtures.read_pool(pool_id)["version"],
        "order": fixtures.read_order(order_id)["version"],
        "brewer": fixtures.read_brewer(ctx["brewer"]["id"])["version"],
    }
    assert first == {"agreement": 3, "pool": 6, "order": 2, "brewer": 1}

    second = {
        "agreement": fixtures.read_agreement(agreement_id)["version"],
        "pool": fixtures.read_pool(pool_id)["version"],
        "order": fixtures.read_order(order_id)["version"],
        "brewer": fixtures.read_brewer(ctx["brewer"]["id"])["version"],
    }
    assert second == first

    stored = fixtures.read_agreement(agreement_id)
    assert stored["kegs_issued_count"] == 2
    assert stored["kegs_at_brewer_count"] == 2
    assert stored["float_posture"] == "HEALTHY"
    assert stored["pending_replenishment_kegs"] == 0


# ==========================================================================
# Design: Corner/Cross-Cutting Complexity Layers/fleet_imports_walk_the_pool_from_open_through_restricted_to_frozen_and_back
# ==========================================================================


def _a_one_keg_float_and_nine_quarantined_imports():
    """A pool holding one `IN_FLOAT` keg — 100.00 percent available and `OPEN` —
    with a one-keg float activated over it and one `REQUESTED` order taken out
    while the pool was still open, then nine `QUARANTINED` imports that drive
    availability down to exactly the freeze threshold.
    """
    fixtures.pin_clock(CLOCK)
    brewer = fixtures.create_brewer()
    pool = fixtures.create_pool(**POOL)
    fixtures.import_keg(pool["id"], "K-0001")
    agreement = fixtures.create_and_activate_agreement(
        brewer["id"], pool["id"], 1, EFFECTIVE_DATE, per_fill_rate_cents=RATE
    )
    order = fixtures.create_order(agreement["id"], 1)
    for position in range(1, 10):
        fixtures.import_keg(
            pool["id"], f"Q-{position:04d}", initial_custody_state="QUARANTINED"
        )
    return {
        "brewer": brewer,
        "pool": pool,
        "agreement": agreement,
        "order": order,
    }


def test_nine_no_op_recomputes_leave_the_agreement_exactly_where_it_was():
    """Nine quarantined imports each recompute the census, the posture and every
    active agreement's posture, and take the pool from `OPEN` to exactly the
    freeze threshold, which is still `RESTRICTED` — yet because all three
    agreement fields re-derive to the values already stored, the agreement never
    leaves the version its activation gave it, while the pool, whose
    `kegs_total` really did change, bumps once per import.

    PRD: "`initial_custody_state` seeds `custody_state`; only `IN_FLOAT`,
    `IN_SERVICE` and `QUARANTINED` may be seeded, and when the field is omitted
    the keg opens in `IN_FLOAT`."

    PRD: "The import finishes by recomputing the pool census, `available_pct`
    and `posture`, and then every `ACTIVE` agreement's `float_posture`."

    PRD: "`kegs_available` counts the kegs whose `custody_state` is `IN_FLOAT`."

    PRD: "`kegs_servicing` counts the kegs in `IN_SERVICE` or `QUARANTINED`."

    PRD: "`kegs_total` counts every keg row of the pool, written-off kegs
    included."

    PRD: "`available_pct` is 0.00 when `kegs_total` is zero, and otherwise
    `kegs_available` divided by `kegs_total`, multiplied by 100, rounded half up
    to exactly two decimal places."

    PRD: "When `kegs_total` is greater than zero and `available_pct` is below
    `restrict_threshold_pct` but greater than or equal to `freeze_threshold_pct`,
    the posture is `RESTRICTED`."

    PRD: "Both comparisons are inclusive, so an `available_pct` exactly equal to
    `restrict_threshold_pct` reads `OPEN` and one exactly equal to
    `freeze_threshold_pct` reads `RESTRICTED`."

    PRD: "`freeze_threshold_pct`, an integer from 0 to 100 defaulting to 10, is
    the availability percentage below which the pool freezes; it must be strictly
    less than `restrict_threshold_pct`, and a creation that violates that
    relationship is refused as an invalid request."

    PRD: "A recompute bumps the recomputed row's `version` only if it actually
    alters at least one stored field of that row."

    PRD: "Importing a keg into a pool that already has an active agreement
    re-evaluates that agreement's `float_posture`, `kegs_at_brewer_count` and
    `pending_replenishment_kegs`; if all three come out identical to their stored
    values, the agreement's `version` stays exactly where it was and its
    `updated_at` is not refreshed."

    PRD: "While the posture is `TIGHT` it is the float size minus
    `kegs_at_brewer_count`, or 0 if that difference would be negative."

    Design: Corner/Cross-Cutting Complexity Layers/fleet_imports_walk_the_pool_from_open_through_restricted_to_frozen_and_back
    """
    ctx = _a_one_keg_float_and_nine_quarantined_imports()

    assert ctx["agreement"]["version"] == 2
    assert ctx["agreement"]["float_posture"] == "TIGHT"
    assert ctx["agreement"]["pending_replenishment_kegs"] == 1
    assert ctx["order"]["status"] == "REQUESTED"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    _census(pool, available=1, circulating=0, servicing=9, held=0, written_off=0, total=10)
    assert pool["available_pct"] == 10.00
    assert pool["posture"] == "RESTRICTED"
    assert pool["version"] == 11

    stored = fixtures.read_agreement(ctx["agreement"]["id"])
    assert stored["version"] == 2
    assert stored["float_posture"] == "TIGHT"
    assert stored["kegs_at_brewer_count"] == 0
    assert stored["pending_replenishment_kegs"] == 1


def test_the_frozen_pool_outranks_the_suspended_float_and_the_thaw_reverses_it():
    """The tenth quarantined import takes availability below the freeze
    threshold, and that single import reaches four rows deep: keg, census,
    posture, then the agreement, which lands on `SUSPENDED`.  The allocate now
    fails two ladder rungs at once and reports the earlier one, writing nothing.
    Three `IN_FLOAT` imports then walk the pool back to `OPEN`, bumping the
    agreement exactly once — on the import that actually changed it — and the
    identical allocate succeeds and immediately re-restricts the pool.

    PRD: "A pool can also move straight from `FROZEN` to `OPEN` when a fleet
    import or a replenishment sweep lifts availability past
    `restrict_threshold_pct` in one step."

    PRD: "The agreement is `SUSPENDED` whenever the pool's `posture` is `FROZEN`
    **or** the brewer's `status` is `PROBATION` or `SUSPENDED`."

    PRD: "While the posture is `HEALTHY` or `SUSPENDED` it is 0."

    PRD: "Checks are evaluated in a fixed precedence order, and the first check
    that fails determines the response; no later check may mask an earlier one."

    PRD: "13. The pool's `posture` is not `FROZEN` — `ERR_POOL_FROZEN` (409), on
    order creation and order allocation."

    PRD: "15. The governing agreement's `float_posture` is not `SUSPENDED` —
    `ERR_FLOAT_SUSPENDED` (409), on order allocation and a fill scan."

    PRD: "The suspension lifts by recompute as soon as the suspending condition
    clears — the pool leaves `FROZEN` or the brewer returns to `ACTIVE` — at
    which point the agreement lands on `TIGHT` or `HEALTHY` according to the same
    ceiling comparison."

    PRD: "Otherwise — including whenever `kegs_total` is zero — the posture is
    `FROZEN`."

    Design: Corner/Cross-Cutting Complexity Layers/fleet_imports_walk_the_pool_from_open_through_restricted_to_frozen_and_back
    """
    ctx = _a_one_keg_float_and_nine_quarantined_imports()
    pool_id = ctx["pool"]["id"]
    agreement_id = ctx["agreement"]["id"]
    order_id = ctx["order"]["id"]

    fixtures.import_keg(pool_id, "Q-0010", initial_custody_state="QUARANTINED")

    frozen_pool = fixtures.read_pool(pool_id)
    _census(frozen_pool, available=1, circulating=0, servicing=10, held=0, written_off=0, total=11)
    assert frozen_pool["available_pct"] == 9.09
    assert frozen_pool["posture"] == "FROZEN"
    assert frozen_pool["version"] == 12

    suspended = fixtures.read_agreement(agreement_id)
    assert suspended["float_posture"] == "SUSPENDED"
    assert suspended["pending_replenishment_kegs"] == 0
    assert suspended["version"] == 3

    validate_error(
        api_client.allocate_issuance_order(
            order_id, {"expected_agreement_version": 3}, OPERATOR
        ),
        ApiErrorId.ERR_POOL_FROZEN,
        409,
    )
    assert fixtures.read_order(order_id)["status"] == "REQUESTED"
    assert fixtures.read_order(order_id)["allocated_keg_count"] == 0
    assert fixtures.read_agreement(agreement_id)["version"] == 3

    for tag in ["K-0002", "K-0003", "K-0004"]:
        fixtures.import_keg(pool_id, tag)

    thawed_pool = fixtures.read_pool(pool_id)
    _census(thawed_pool, available=4, circulating=0, servicing=10, held=0, written_off=0, total=14)
    assert thawed_pool["available_pct"] == 28.57
    assert thawed_pool["posture"] == "OPEN"

    thawed = fixtures.read_agreement(agreement_id)
    assert thawed["version"] == 4
    assert thawed["float_posture"] == "TIGHT"
    assert thawed["pending_replenishment_kegs"] == 1

    allocated = validate_success(
        api_client.allocate_issuance_order(
            order_id, {"expected_agreement_version": 4}, OPERATOR
        ),
        200,
    )
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_keg_count"] == 1

    retightened = fixtures.read_pool(pool_id)
    _census(retightened, available=3, circulating=1, servicing=10, held=0, written_off=0, total=14)
    assert retightened["available_pct"] == 21.43
    assert retightened["posture"] == "RESTRICTED"

    after = fixtures.read_agreement(agreement_id)
    assert after["version"] == 5
    assert after["kegs_at_brewer_count"] == 1
    assert after["float_posture"] == "HEALTHY"
    assert after["pending_replenishment_kegs"] == 0


# ==========================================================================
# Design: Corner/Cross-Cutting Complexity Layers/an_unusable_depreciated_book_basis_is_silently_coerced_to_replacement_cost
# ==========================================================================


def _two_dispatched_kegs_one_fresh_and_one_with_eight_fills():
    """A two-keg float at the brewer: `K-0001` imported fresh, so its
    `fill_count` is 0, and `K-0002` imported with eight fills already on it and
    its certification counter level with them, so it still reads `SERVICE_OK`.
    Both are dispatched, so each has a chargeable `current_brewer_id`.
    """
    ctx = fixtures.setup_dispatched_float(
        requested_keg_count=2,
        dispatched_at="2026-08-01T00:00:00Z",
        float_size_kegs=2,
        keg_count=2,
        pool_overrides=POOL,
        keg_specs=[
            {"asset_tag": "K-0001"},
            {"asset_tag": "K-0002", "fill_count": 8, "fills_at_last_pressure_test": 8},
        ],
        effective_date=EFFECTIVE_DATE,
        clock=CLOCK,
    )
    by_tag = {
        fixtures.read_keg(keg_id)["asset_tag"]: keg_id
        for keg_id in ctx["allocated_keg_ids"]
    }
    ctx["fresh_keg_id"] = by_tag["K-0001"]
    ctx["worn_keg_id"] = by_tag["K-0002"]
    return ctx


def _open_assessment(keg_id, cause, basis, headers=ANALYST):
    """Open one assessment against the keg's current version and assert the
    create was accepted, returning the stored row."""
    payload = factories.create_loss_assessment_payload(
        keg_id, cause, fixtures.keg_version(keg_id), assessment_basis=basis
    )
    return validate_success(api_client.create_loss_assessment(payload, headers), 201)


def test_an_unusable_depreciated_book_basis_is_accepted_and_silently_rewritten():
    """`DEPRECIATED_BOOK` on a keg that has never been filled, and
    `DEPRECIATED_BOOK` under a suspected theft, are both accepted with HTTP 201
    and both stored as `REPLACEMENT_COST`: an unusable basis is a coercion, never
    an invalid request.  The zero-liability variant issues no money at all, and a
    waive leaves it exactly as it stood.

    PRD: "Basis selection is coerced silently and is never an error."

    PRD: "When `assessment_basis` is omitted, or is supplied as
    `DEPRECIATED_BOOK` on a keg whose `fill_count` is 0, or is supplied as
    `DEPRECIATED_BOOK` together with a `cause` of `STOLEN_SUSPECTED`, the stored
    `assessment_basis` becomes `REPLACEMENT_COST` and the gross value follows
    that variant."

    PRD: "Under **`REPLACEMENT_COST`**, `gross_value_cents` is simply the pool's
    `replacement_cost_cents`, and `fill_count` is ignored entirely."

    PRD: "`scrap_credit_cents` takes the keg's `stainless_scrap_value_cents` only
    when the `cause` is `DAMAGED_BEYOND_REPAIR`, because only then is the shell
    physically in hand; `LOST_IN_TRADE`, `NOT_RETURNED_DWELL` and
    `STOLEN_SUSPECTED` all credit 0 even though the keg has a scrap value on
    paper, since nobody can weigh in a keg they cannot find."

    PRD: "`assessed_value_cents` is the gross value less the scrap credit,
    floored at 0."

    PRD: "`brewer_liability_pct_bp` is keyed off the cause alone: 6000 basis
    points for `LOST_IN_TRADE`, 10000 for `DAMAGED_BEYOND_REPAIR`, 10000 for
    `NOT_RETURNED_DWELL` and 0 for `STOLEN_SUSPECTED`."

    PRD: "And `net_chargeback_cents` is the assessed value multiplied by that
    liability share as a proportion of 10000, rounded half up."

    PRD: "Because `STOLEN_SUSPECTED` carries a liability of 0 basis points, its
    `net_chargeback_cents` is always 0 and its `chargeback_status` stays `NONE`
    forever: a suspected theft is booked against the pool, not against the
    brewer, and recovery runs through a theft investigation instead."

    PRD: "A **waive** is deliberately inert: `chargeback_status` stays `NONE`, no
    money moves, the keg's `custody_state` and every pool census counter are left
    exactly as they were, `chargeback_balance_cents` is untouched, and only
    `assessment_open` is lowered."

    Design: Corner/Cross-Cutting Complexity Layers/an_unusable_depreciated_book_basis_is_silently_coerced_to_replacement_cost
    """
    ctx = _two_dispatched_kegs_one_fresh_and_one_with_eight_fills()

    assert fixtures.read_keg(ctx["fresh_keg_id"])["fill_count"] == 0
    assert fixtures.read_keg(ctx["worn_keg_id"])["fill_count"] == 8

    coerced_by_fill_count = _open_assessment(
        ctx["fresh_keg_id"], "LOST_IN_TRADE", "DEPRECIATED_BOOK"
    )
    assert coerced_by_fill_count["assessment_basis"] == "REPLACEMENT_COST"
    assert coerced_by_fill_count["gross_value_cents"] == 23500
    assert coerced_by_fill_count["scrap_credit_cents"] == 0
    assert coerced_by_fill_count["assessed_value_cents"] == 23500
    assert coerced_by_fill_count["brewer_liability_pct_bp"] == 6000
    assert coerced_by_fill_count["net_chargeback_cents"] == 14100

    coerced_by_cause = _open_assessment(
        ctx["worn_keg_id"], "STOLEN_SUSPECTED", "DEPRECIATED_BOOK"
    )
    assert coerced_by_cause["assessment_basis"] == "REPLACEMENT_COST"
    assert coerced_by_cause["gross_value_cents"] == 23500
    assert coerced_by_cause["scrap_credit_cents"] == 0
    assert coerced_by_cause["assessed_value_cents"] == 23500
    assert coerced_by_cause["brewer_liability_pct_bp"] == 0
    assert coerced_by_cause["net_chargeback_cents"] == 0
    assert coerced_by_cause["chargeback_status"] == "NONE"

    waived = fixtures.resolve_assessment(
        coerced_by_cause["id"], "WAIVED", SECOND_ANALYST_USER_ID
    )
    assert waived["assessment_status"] == "WAIVED"
    assert waived["chargeback_status"] == "NONE"
    assert waived["net_chargeback_cents"] == 0

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 0
    assert brewer["upheld_loss_count"] == 0


def test_the_same_basis_key_is_honoured_once_the_fill_count_and_the_cause_allow_it():
    """The identical `DEPRECIATED_BOOK` request key that was overruled twice is
    honoured on the third create, because the keg has eight fills and the cause
    is not a theft — and the money differs: 13592 cents on the honoured variant
    against 14100 on the coerced one, out of the very same pool.

    PRD: "Under **`DEPRECIATED_BOOK`**, the replacement cost is written down 45
    basis points for every lifetime fill, with total depreciation capped at 7000
    basis points."

    PRD: "A candidate book value is the `replacement_cost_cents` multiplied by
    10000 less that depreciation, divided by 10000, rounded half up; a floor
    value is 30 percent of `replacement_cost_cents`, rounded half up; and
    `gross_value_cents` is the greater of the two."

    PRD: "Once `fill_count` is at least 1 and the cause permits it,
    `DEPRECIATED_BOOK` always yields a strictly lower gross value than
    `REPLACEMENT_COST`, so reading the wrong basis is observable in the money."

    PRD: "Rounding is applied separately to the candidate book value, to the
    floor value and to the net chargeback; basis points are always integers."

    PRD: "The valuation is **pinned at creation and never recomputed**, which is
    why the `commodity_index_id` in force is stored on the row: a later index
    posting cannot re-price a standing assessment, and resolving one does not
    re-run the arithmetic."

    PRD: "It is the pool's `stainless_weight_kg` multiplied by the stainless
    price in force, multiplied by a recovery factor of 65 percent, rounded half
    up to whole cents."

    PRD: "The `created_by_user_id` is stamped with the acting `X-User-ID`, the
    assessment opens in `assessment_status` `PROPOSED` with `chargeback_status`
    `NONE`, the keg's `assessment_open` flag is raised, and
    `dwell_days_at_assessment` records the keg's dwell at creation, taken from
    whichever clock is open — the brewer clock when both are."

    Design: Corner/Cross-Cutting Complexity Layers/an_unusable_depreciated_book_basis_is_silently_coerced_to_replacement_cost
    """
    ctx = _two_dispatched_kegs_one_fresh_and_one_with_eight_fills()
    index_id = ctx["index"]["id"]

    coerced = _open_assessment(
        ctx["fresh_keg_id"], "LOST_IN_TRADE", "DEPRECIATED_BOOK"
    )
    stolen = _open_assessment(
        ctx["worn_keg_id"], "STOLEN_SUSPECTED", "DEPRECIATED_BOOK"
    )
    fixtures.resolve_assessment(stolen["id"], "WAIVED", SECOND_ANALYST_USER_ID)

    honoured = _open_assessment(
        ctx["worn_keg_id"], "LOST_IN_TRADE", "DEPRECIATED_BOOK"
    )
    assert honoured["assessment_basis"] == "DEPRECIATED_BOOK"
    assert honoured["gross_value_cents"] == 22654
    assert honoured["scrap_credit_cents"] == 0
    assert honoured["assessed_value_cents"] == 22654
    assert honoured["brewer_liability_pct_bp"] == 6000
    assert honoured["net_chargeback_cents"] == 13592
    assert honoured["assessment_status"] == "PROPOSED"
    assert honoured["chargeback_status"] == "NONE"

    assert honoured["net_chargeback_cents"] != coerced["net_chargeback_cents"]
    assert honoured["gross_value_cents"] < coerced["gross_value_cents"]

    for row in (coerced, stolen, honoured):
        assert row["commodity_index_id"] == index_id

    for keg_id in (ctx["fresh_keg_id"], ctx["worn_keg_id"]):
        assert fixtures.read_keg(keg_id)["stainless_scrap_value_cents"] == 3900
    assert fixtures.read_keg(ctx["worn_keg_id"])["assessment_open"] is True

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 0
    assert brewer["upheld_loss_count"] == 0


# ==========================================================================
# Design: Corner/Cross-Cutting Complexity Layers/both_probation_gates_arm_together_and_only_the_recorded_reason_can_be_undone
# ==========================================================================


def _a_proposed_fifty_thousand_cent_non_return_on_a_filled_keg():
    """A four-keg pool whose replacement cost is 50000 cents, a four-keg float
    with two kegs dispatched, one of them filled at 10:00Z — the only fill in the
    trailing window — and a `NOT_RETURNED_DWELL` assessment proposed on it at
    replacement cost, so its net chargeback is twice the balance gate.
    """
    ctx = fixtures.setup_filled_keg(
        scanned_at="2026-08-01T10:00:00Z",
        dispatched_at="2026-08-01T00:00:00Z",
        requested_keg_count=2,
        float_size_kegs=4,
        keg_count=4,
        pool_overrides=BIG_POOL,
        keg_specs=[
            {"asset_tag": "B-0001"},
            {"asset_tag": "B-0002"},
            {"asset_tag": "B-0003"},
            {"asset_tag": "B-0004"},
        ],
        effective_date=EFFECTIVE_DATE,
        clock=CLOCK,
    )
    ctx["spare_keg_id"] = ctx["allocated_keg_ids"][1]
    ctx["assessment"] = _open_assessment(
        ctx["keg_id"], "NOT_RETURNED_DWELL", "REPLACEMENT_COST"
    )
    return ctx


def _loss_rate(brewer_id, basis):
    return get_success_data(
        api_client.get_brewer_loss_rate(brewer_id, OPERATOR, params={"basis": basis})
    )


def test_the_balance_gate_claims_the_transition_and_the_rate_gate_does_not_overwrite_it():
    """One uphold arms both probation gates at once — a 50000 cent balance twice
    the 25000 threshold and a trailing rate of 10000 basis points on one loss
    over one fill — and the recorded `status_reason` is the balance one, because
    cascade link 3 moves the brewer out of `ACTIVE` before the loss-rate gate is
    consulted.  The suspension reaches the agreement, and the write-off reaches
    the census.

    PRD: "The assessment moves to `UPHELD` and, when `net_chargeback_cents` is
    greater than zero, `chargeback_status` flips from `NONE` to `ISSUED` in the
    same request."

    PRD: "The keg is written off according to the cause:
    `DAMAGED_BEYOND_REPAIR` scraps it, `LOST_IN_TRADE` and `NOT_RETURNED_DWELL`
    mark it lost, and `STOLEN_SUSPECTED` leaves custody alone."

    PRD: "The custody move is *scoped*: it happens only when the keg-custody
    machine declares that edge from the keg's current bucket, meaning a keg
    becomes lost only from `FILLED`, `IN_TRADE` or `AT_RETAIL`, and scrapped only
    from `QUARANTINED`."

    PRD: "2. Because the chargeback became `ISSUED`, the brewer's
    `chargeback_balance_cents` is recomputed, `upheld_loss_count` increases by
    one, both `loss_rate_bp_trailing_90d` and `loss_rate_bp_lifetime` are
    recomputed, and the brewer's `version` advances."

    PRD: "3. Because the balance was recomputed, the probation gate runs: when
    `chargeback_balance_cents` is at or above 25000 cents and the brewer's
    `status` is `ACTIVE`, the brewer moves to `PROBATION` with `status_reason`
    recorded as `CHARGEBACK_BALANCE_THRESHOLD`."

    PRD: "4. Because the brewer entered probation, every `ACTIVE` float agreement
    of that brewer recomputes `float_posture` to `SUSPENDED`, which blocks that
    brewer's later allocations and fill scans."

    PRD: "If one uphold would trip both gates at once, the balance gate claims
    the transition first, and the loss-rate gate then finds the status is no
    longer `ACTIVE` and does not overwrite the reason; `LOSS_RATE_THRESHOLD`
    therefore appears only when the recomputed balance is strictly below 25000
    cents while the trailing rate is at or above 1500 basis points."

    PRD: "The trailing variant counts, inside a window running from 90 days
    before the logical clock through the clock itself with both ends inclusive,
    the brewer's `UPHELD` assessments by `created_at` as the numerator and the
    brewer's fill scans by `scanned_at` as the denominator."

    PRD: "The loss rate is also readable on demand for one brewer under a `basis`
    query parameter that defaults to `TRAILING_90D` and also accepts `LIFETIME`;
    the read reports `brewer_id`, `basis`, `loss_rate_bp`, `upheld_loss_count`,
    `fill_count`, `window_start`, `window_end` and `basis_insufficient`, returns
    unset `window_start` and `window_end` for the lifetime basis, and persists
    nothing."

    PRD: "After those four links, the pool census, `posture` and each `ACTIVE`
    agreement's `float_posture` are recomputed for the written-off keg."

    PRD: "`kegs_written_off` counts the kegs in `LOST`, `STOLEN` or `SCRAPPED`."

    Design: Corner/Cross-Cutting Complexity Layers/both_probation_gates_arm_together_and_only_the_recorded_reason_can_be_undone
    """
    ctx = _a_proposed_fifty_thousand_cent_non_return_on_a_filled_keg()
    brewer_id = ctx["brewer"]["id"]

    upheld = validate_success(
        api_client.resolve_loss_assessment(
            ctx["assessment"]["id"],
            factories.resolve_assessment_payload("UPHELD"),
            SECOND_ANALYST,
        ),
        200,
    )
    assert upheld["assessment_status"] == "UPHELD"
    assert upheld["chargeback_status"] == "ISSUED"
    assert upheld["gross_value_cents"] == 50000
    assert upheld["scrap_credit_cents"] == 0
    assert upheld["brewer_liability_pct_bp"] == 10000
    assert upheld["net_chargeback_cents"] == 50000

    brewer = fixtures.read_brewer(brewer_id)
    assert brewer["chargeback_balance_cents"] == 50000
    assert brewer["upheld_loss_count"] == 1
    assert brewer["loss_rate_bp_trailing_90d"] == 10000
    assert brewer["loss_rate_bp_lifetime"] == 10000
    assert brewer["status"] == "PROBATION"
    assert brewer["status_reason"] == "CHARGEBACK_BALANCE_THRESHOLD"

    trailing = _loss_rate(brewer_id, "TRAILING_90D")
    assert trailing["brewer_id"] == brewer_id
    assert trailing["basis"] == "TRAILING_90D"
    assert trailing["loss_rate_bp"] == 10000
    assert trailing["upheld_loss_count"] == 1
    assert trailing["fill_count"] == 1
    assert trailing["basis_insufficient"] is False
    assert trailing["window_start"] == "2026-05-03T23:00:00Z"
    assert trailing["window_end"] == "2026-08-01T23:00:00Z"

    lifetime = _loss_rate(brewer_id, "LIFETIME")
    assert lifetime["basis"] == "LIFETIME"
    assert lifetime["loss_rate_bp"] == 10000
    assert lifetime["window_start"] is None
    assert lifetime["window_end"] is None

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["float_posture"] == "SUSPENDED"
    assert agreement["pending_replenishment_kegs"] == 0

    lost = fixtures.read_keg(ctx["keg_id"])
    assert lost["custody_state"] == "LOST"
    assert lost["assessment_open"] is False

    pool = fixtures.read_pool(ctx["pool"]["id"])
    _census(pool, available=2, circulating=1, servicing=0, held=0, written_off=1, total=4)
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"


def test_the_reversal_lifts_the_probation_it_can_name_and_leaves_the_rate_standing():
    """A reversal empties the ledger and lifts exactly the probation whose reason
    it can name, releasing the float posture, while the loss counters stay
    where they were and the assessment stays `UPHELD`.  The released float then
    accepts a second fill, whose recomputed trailing rate — one loss over two
    fills — is still above the gate, so the rate the reversal refused to touch is
    still the rate on file.

    PRD: "They are decoupled on purpose — `chargeback_status` can travel from
    `ISSUED` to `REVERSED` while `assessment_status` stays `UPHELD`, and
    `assessment_status` can reach `WAIVED` while `chargeback_status` never leaves
    `NONE`."

    PRD: "The **chargeback ledger** is a conserved quantity: a brewer's
    `chargeback_balance_cents` is always the sum of `net_chargeback_cents` across
    that brewer's assessments whose `chargeback_status` is `ISSUED` or `SETTLED`."

    PRD: "A `REVERSE` also requires `ISSUED` and moves the status to `REVERSED`,
    which drops the row out of the sum and restores the balance to exactly its
    pre-uphold value — bit for bit, with no drift."

    PRD: "A reversal that drops the balance back below 25000 cents lifts the
    probation it caused, but only that one: the brewer returns to `ACTIVE` with
    `status_reason` cleared **only** when the current `status` is `PROBATION`
    *and* the current `status_reason` is `CHARGEBACK_BALANCE_THRESHOLD`, which in
    turn releases the `SUSPENDED` float posture on that brewer's `ACTIVE`
    agreements."

    PRD: "And the loss counters are money-independent — `upheld_loss_count` and
    both loss-rate figures are never recomputed by a reversal — so the trailing
    rate that forced probation still stands afterwards."

    PRD: "The suspension lifts by recompute as soon as the suspending condition
    clears — the pool leaves `FROZEN` or the brewer returns to `ACTIVE` — at
    which point the agreement lands on `TIGHT` or `HEALTHY` according to the same
    ceiling comparison."

    PRD: "On the brewer's side, `lifetime_fill_count` rises by one and both
    `loss_rate_bp_trailing_90d` and `loss_rate_bp_lifetime` are recomputed."

    PRD: "In both cases, a zero denominator reports a rate of 0 and marks the
    basis insufficient; otherwise the rate is 10000 multiplied by the numerator,
    divided by the denominator, rounded half up — one upheld loss over three
    fills is 3333 basis points, not 3334."

    Design: Corner/Cross-Cutting Complexity Layers/both_probation_gates_arm_together_and_only_the_recorded_reason_can_be_undone
    """
    ctx = _a_proposed_fifty_thousand_cent_non_return_on_a_filled_keg()
    brewer_id = ctx["brewer"]["id"]
    assessment_id = ctx["assessment"]["id"]

    fixtures.resolve_assessment(assessment_id, "UPHELD", SECOND_ANALYST_USER_ID)

    reversed_row = validate_success(
        api_client.chargeback_resolution(
            assessment_id,
            factories.chargeback_resolution_payload("REVERSE"),
            ANALYST,
        ),
        200,
    )
    assert reversed_row["chargeback_status"] == "REVERSED"
    assert reversed_row["assessment_status"] == "UPHELD"
    assert reversed_row["net_chargeback_cents"] == 50000

    brewer = fixtures.read_brewer(brewer_id)
    assert brewer["chargeback_balance_cents"] == 0
    assert brewer["status"] == "ACTIVE"
    assert brewer["status_reason"] is None
    assert brewer["upheld_loss_count"] == 1
    assert brewer["loss_rate_bp_trailing_90d"] == 10000

    released = fixtures.read_agreement(ctx["agreement"]["id"])
    assert released["float_posture"] == "HEALTHY"
    assert released["kegs_at_brewer_count"] == 1
    assert released["pending_replenishment_kegs"] == 0

    second_fill = validate_success(
        api_client.scan_keg(
            ctx["spare_keg_id"],
            factories.fill_scan_payload(
                brewer_id, "2026-08-01T20:00:00Z", ctx["brewer"]["brand_code"]
            ),
            OPERATOR,
        ),
        201,
    )
    assert second_fill["fill_charge_net_cents"] == RATE

    filled = fixtures.read_keg(ctx["spare_keg_id"])
    assert filled["custody_state"] == "FILLED"
    assert filled["fill_count"] == 1

    after_fill = _loss_rate(brewer_id, "TRAILING_90D")
    assert after_fill["upheld_loss_count"] == 1
    assert after_fill["fill_count"] == 2
    assert after_fill["loss_rate_bp"] == 5000
    assert after_fill["basis_insufficient"] is False
    assert fixtures.read_brewer(brewer_id)["chargeback_balance_cents"] == 0

    pool = fixtures.read_pool(ctx["pool"]["id"])
    _census(pool, available=2, circulating=1, servicing=0, held=0, written_off=1, total=4)
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"
