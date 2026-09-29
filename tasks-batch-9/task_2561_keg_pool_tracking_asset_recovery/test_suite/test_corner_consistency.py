"""Read-your-write: every cascade of a write is final in that write's response.

The consistency model of this specification is immediate.  There is no sweep,
no job and no clock advance between a write and the reads that observe it, so
the scenarios here take one uphold — the longest cascade in the system, five
rows across four aggregates — and check that its own response body, the first
read of every touched row, and a repeat of those reads all agree exactly.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_census, assert_same_record
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


# ==========================================================================
# Design: Corner/Consistency Model/every_cascade_of_a_write_is_readable_in_that_same_response
# ==========================================================================


def _a_proposed_depreciated_book_loss_on_a_once_filled_keg():
    """A four-keg pool with one keg allocated, dispatched and filled once, and a
    `LOST_IN_TRADE` assessment proposed on it under `DEPRECIATED_BOOK`: one fill
    depreciates the 23500 cent replacement cost by 45 basis points to a book
    value of 23394, well above the 7050 floor, and 6000 basis points of that is
    14036 cents — below the 25000 balance gate.
    """
    ctx = fixtures.setup_filled_keg(
        scanned_at="2026-08-01T12:00:00Z",
        dispatched_at="2026-08-01T00:00:00Z",
        requested_keg_count=1,
        float_size_kegs=4,
        keg_count=4,
        pool_overrides=POOL,
        effective_date=EFFECTIVE_DATE,
        clock=CLOCK,
    )
    ctx["assessment"] = fixtures.open_loss_assessment(
        ctx["keg_id"], "LOST_IN_TRADE", ANALYST_USER_ID, "DEPRECIATED_BOOK"
    )
    return ctx


def _uphold(assessment_id):
    return validate_success(
        api_client.resolve_loss_assessment(
            assessment_id,
            factories.resolve_assessment_payload(
                "UPHELD", resolution_notes="Account confirms the keg was scrapped locally."
            ),
            SECOND_ANALYST,
        ),
        200,
    )


def test_the_uphold_response_is_already_final_and_the_first_read_confirms_it():
    """The resolve response carries the whole adjudication and the whole money
    move, and the first read of each of the four other rows — brewer, pool, keg,
    agreement — already shows every cascade link: the recomputed ledger, the
    loss-rate probation the balance gate did not claim, the written-off census,
    the retained chargeable party and the suspended float.

    PRD: "First, every derived quantity — pool census, pool posture, agreement
    posture, brewer chargeback balance, distributor incentive ledger — is
    recomputed inside the mutating request rather than by a background job, so a
    caller who reads immediately after writing sees the settled truth."

    PRD: "Derived state propagates in a fixed chain, and every link fires inside
    the same request."

    PRD: "Either resolution records `resolved_by_user_id` and `resolution_notes`
    and advances the assessment's `version`."

    PRD: "The assessment moves to `UPHELD` and, when `net_chargeback_cents` is
    greater than zero, `chargeback_status` flips from `NONE` to `ISSUED` in the
    same request."

    PRD: "A candidate book value is the `replacement_cost_cents` multiplied by
    10000 less that depreciation, divided by 10000, rounded half up; a floor
    value is 30 percent of `replacement_cost_cents`, rounded half up; and
    `gross_value_cents` is the greater of the two."

    PRD: "And `net_chargeback_cents` is the assessed value multiplied by that
    liability share as a proportion of 10000, rounded half up."

    PRD: "If one uphold would trip both gates at once, the balance gate claims
    the transition first, and the loss-rate gate then finds the status is no
    longer `ACTIVE` and does not overwrite the reason; `LOSS_RATE_THRESHOLD`
    therefore appears only when the recomputed balance is strictly below 25000
    cents while the trailing rate is at or above 1500 basis points."

    PRD: "4. Because the brewer entered probation, every `ACTIVE` float agreement
    of that brewer recomputes `float_posture` to `SUSPENDED`, which blocks that
    brewer's later allocations and fill scans."

    PRD: "After those four links, the pool census, `posture` and each `ACTIVE`
    agreement's `float_posture` are recomputed for the written-off keg."

    Design: Corner/Consistency Model/every_cascade_of_a_write_is_readable_in_that_same_response
    """
    ctx = _a_proposed_depreciated_book_loss_on_a_once_filled_keg()

    upheld = _uphold(ctx["assessment"]["id"])
    assert upheld["assessment_status"] == "UPHELD"
    assert upheld["resolved_by_user_id"] == SECOND_ANALYST_USER_ID
    assert upheld["chargeback_status"] == "ISSUED"
    assert upheld["assessment_basis"] == "DEPRECIATED_BOOK"
    assert upheld["gross_value_cents"] == 23394
    assert upheld["scrap_credit_cents"] == 0
    assert upheld["assessed_value_cents"] == 23394
    assert upheld["brewer_liability_pct_bp"] == 6000
    assert upheld["net_chargeback_cents"] == 14036

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 14036
    assert brewer["upheld_loss_count"] == 1
    assert brewer["loss_rate_bp_trailing_90d"] == 10000
    assert brewer["loss_rate_bp_lifetime"] == 10000
    assert brewer["status"] == "PROBATION"
    assert brewer["status_reason"] == "LOSS_RATE_THRESHOLD"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 3,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 1,
        },
    )
    assert pool["available_pct"] == 75.00
    assert pool["posture"] == "OPEN"

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "LOST"
    assert keg["assessment_open"] is False
    assert keg["current_brewer_id"] == ctx["brewer"]["id"]

    agreement = fixtures.read_agreement(ctx["agreement"]["id"])
    assert agreement["float_posture"] == "SUSPENDED"
    assert agreement["pending_replenishment_kegs"] == 0


def test_both_conserved_quantities_hold_on_that_read_and_repeating_it_changes_nothing():
    """The five-bucket census sums to `kegs_total` and the ledger equals the sum
    over the brewer's `ISSUED` and `SETTLED` rows on the very first read after
    the uphold, not after some later reconciliation — and reading the brewer and
    the pool a second time, with no request in between, returns identical bodies
    down to the version counters.

    PRD: "At the end of every request that changes any keg's `custody_state`, a
    pool's `kegs_total` must equal the sum of `kegs_available`,
    `kegs_circulating`, `kegs_servicing`, `kegs_held` and `kegs_written_off`, as
    exact integer equality with no tolerance."

    PRD: "Every custody movement is a transfer between two of those five buckets;
    only importing a keg raises `kegs_total`, and writing a keg off moves it into
    `kegs_written_off` rather than removing it from `kegs_total`."

    PRD: "A brewer's `chargeback_balance_cents` is at all times the sum of
    `net_chargeback_cents` over that brewer's loss assessments whose
    `chargeback_status` is `ISSUED` or `SETTLED`."

    PRD: "Reads never advance a `version`."

    PRD: "The loss rate is also readable on demand for one brewer under a `basis`
    query parameter that defaults to `TRAILING_90D` and also accepts `LIFETIME`;
    the read reports `brewer_id`, `basis`, `loss_rate_bp`, `upheld_loss_count`,
    `fill_count`, `window_start`, `window_end` and `basis_insufficient`, returns
    unset `window_start` and `window_end` for the lifetime basis, and persists
    nothing."

    Design: Corner/Consistency Model/every_cascade_of_a_write_is_readable_in_that_same_response
    """
    ctx = _a_proposed_depreciated_book_loss_on_a_once_filled_keg()
    brewer_id = ctx["brewer"]["id"]

    _uphold(ctx["assessment"]["id"])

    first_pool = fixtures.read_pool(ctx["pool"]["id"])
    assert first_pool["kegs_total"] == (
        first_pool["kegs_available"]
        + first_pool["kegs_circulating"]
        + first_pool["kegs_servicing"]
        + first_pool["kegs_held"]
        + first_pool["kegs_written_off"]
    )
    assert first_pool["kegs_total"] == 4

    first_brewer = fixtures.read_brewer(brewer_id)
    issued, _ = validate_paginated(
        api_client.list_loss_assessments(
            ANALYST, params={"brewer_id": brewer_id, "chargeback_status": "ISSUED"}
        )
    )
    settled, _ = validate_paginated(
        api_client.list_loss_assessments(
            ANALYST, params={"brewer_id": brewer_id, "chargeback_status": "SETTLED"}
        )
    )
    assert len(issued) == 1
    assert len(settled) == 0
    assert first_brewer["chargeback_balance_cents"] == sum(
        row["net_chargeback_cents"] for row in issued + settled
    )
    assert first_brewer["chargeback_balance_cents"] == 14036

    second_brewer = fixtures.read_brewer(brewer_id)
    second_pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_same_record(first_brewer, second_brewer, "brewer after the uphold")
    assert_same_record(first_pool, second_pool, "pool after the uphold")

    computed = get_success_data(
        api_client.get_brewer_loss_rate(
            brewer_id, OPERATOR, params={"basis": "TRAILING_90D"}
        )
    )
    assert computed["loss_rate_bp"] == 10000
    assert computed["upheld_loss_count"] == 1
    assert computed["fill_count"] == 1
    assert_same_record(
        first_brewer, fixtures.read_brewer(brewer_id), "brewer after the computed read"
    )
