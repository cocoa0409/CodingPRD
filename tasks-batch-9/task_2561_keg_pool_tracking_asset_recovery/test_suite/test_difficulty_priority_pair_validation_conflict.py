"""Requests that break two named rules at once, read for which one is reported.

Each scenario arranges a single call that is simultaneously refusable on two
different grounds, then removes the winning ground and repeats the identical
call so the losing ground surfaces on its own.  The pair therefore proves both
the precedence and the fact that the second failure was really there all along.
"""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ANALYST_USER_ID,
    SECOND_ANALYST_USER_ID,
    TEST_USERS,
    make_brewer_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]

CLOCK = "2026-08-01T23:00:00Z"

FIRST_POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
    "restrict_threshold_pct": 25,
    "freeze_threshold_pct": 10,
    "restricted_max_kegs_per_order": 2,
}

SECOND_POOL = {
    "pool_code": "HB-30L",
    "size_liters": 30,
    "stainless_weight_kg": 9.0,
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


def _orders_of(agreement_id):
    rows, _meta = validate_paginated(
        api_client.list_issuance_orders(OPERATOR, params={"agreement_id": agreement_id})
    )
    return rows


def _over_limit_brewer_holding_a_drafted_second_float():
    """A brewer whose credit limit is 5000 cents but whose chargeback ledger
    already carries a 28200-cent upheld loss, holding a second float agreement
    on a second pool that has never been activated.

    An order against that drafted agreement therefore breaks the agreement-state
    rule and the credit rule in the same request.
    """
    fixtures.pin_clock(CLOCK)
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer(credit_limit_cents=5000)
    first_pool = fixtures.create_pool(**dict(FIRST_POOL, replacement_cost_cents=28200))
    fixtures.import_kegs(first_pool["id"], [f"K-{n:04d}" for n in range(1, 5)])
    first_agreement = fixtures.create_and_activate_agreement(
        brewer["id"], first_pool["id"], 4, effective_date="2026-08-01", **AGREEMENT
    )
    order = fixtures.order_allocated_and_dispatched(
        first_agreement["id"], 1, "2026-08-01T01:00:00Z"
    )
    lost_keg_id = order["allocated_keg_ids"][0]
    fixtures.fill_scan(lost_keg_id, brewer["id"], "2026-08-01T02:00:00Z", "RDG")
    proposed = fixtures.open_loss_assessment(
        lost_keg_id,
        "NOT_RETURNED_DWELL",
        analyst_id=ANALYST_USER_ID,
        assessment_basis="REPLACEMENT_COST",
    )
    assessment = fixtures.resolve_assessment(
        proposed["id"], "UPHELD", analyst_id=SECOND_ANALYST_USER_ID
    )

    second_pool = fixtures.create_pool(**SECOND_POOL)
    second_kegs = fixtures.import_kegs(
        second_pool["id"], [f"K-{n:04d}" for n in range(101, 105)]
    )
    drafted = fixtures.create_agreement(
        brewer["id"], second_pool["id"], 4, **AGREEMENT
    )
    return {
        "index": index,
        "brewer": brewer,
        "first_pool": first_pool,
        "first_agreement": first_agreement,
        "assessment": assessment,
        "second_pool": second_pool,
        "second_kegs": second_kegs,
        "drafted_agreement": drafted,
    }


def _order_attempt(agreement_id, requested_keg_count=1):
    return api_client.create_issuance_order(
        factories.create_issuance_order_payload(agreement_id, requested_keg_count),
        OPERATOR,
    )


def test_the_drafted_agreement_is_reported_and_not_the_credit_failure():
    """The brewer is 28200 cents into a 5000-cent limit, so the order is fiscally
    impossible, yet the refusal names the drafted agreement because the state
    check is judged first.

    PRD: "On order creation against a drafted agreement held by an over-limit
    brewer, the agreement-status check at step 12 wins and the caller sees
    `ERR_AGREEMENT_NOT_ACTIVE` (409), not the credit failure at step 50."

    PRD: "Because the fiscal check is judged last, an over-limit brewer holding
    only a drafted agreement sees `ERR_AGREEMENT_NOT_ACTIVE` rather than the
    credit failure."

    Design: Difficulty/priority_pair_validation_conflict/order_creation_agreement_state_beats_fiscal_credit_limit
    """
    ctx = _over_limit_brewer_holding_a_drafted_second_float()

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 28200
    assert brewer["credit_limit_cents"] == 5000
    assert brewer["status"] == "PROBATION"

    drafted = fixtures.read_agreement(ctx["drafted_agreement"]["id"])
    assert drafted["status"] == "DRAFT"

    refused = _order_attempt(ctx["drafted_agreement"]["id"])
    validate_error(refused, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)

    assert _orders_of(ctx["drafted_agreement"]["id"]) == []


def test_activating_the_agreement_exposes_the_credit_limit_failure():
    """Once the only thing standing in the way is the money, the identical order
    is refused for the money: 28200 already owed plus 2200 for the requested keg
    is far past the 5000-cent limit.

    PRD: "That fiscal check adds the brewer's `chargeback_balance_cents` to the
    product of `requested_keg_count` and the agreement's `per_fill_rate_cents`,
    and refuses with `ERR_CREDIT_LIMIT_EXCEEDED` when the sum exceeds the
    brewer's `credit_limit_cents`."

    Design: Difficulty/priority_pair_validation_conflict/order_creation_agreement_state_beats_fiscal_credit_limit
    """
    ctx = _over_limit_brewer_holding_a_drafted_second_float()
    agreement_id = ctx["drafted_agreement"]["id"]

    first_refusal = _order_attempt(agreement_id)
    validate_error(first_refusal, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)

    activated = fixtures.activate_agreement(agreement_id, "2026-08-01")
    assert activated["status"] == "ACTIVE"
    assert activated["effective_date"] == "2026-08-01"

    second_refusal = _order_attempt(agreement_id)
    validate_error(second_refusal, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 402)


def test_neither_refusal_commits_an_order_or_draws_on_the_second_pool():
    """Two refused attempts leave no order row on the agreement and every keg of
    the second pool still on the floor, and the brewer's probation is not what
    blocked either call.

    PRD: "The brewer's `status` is not `SUSPENDED`; `PROBATION` is permitted here
    and is instead expressed through `float_posture`."

    PRD: "Because the balance was recomputed, the probation gate runs: when
    `chargeback_balance_cents` is at or above 25000 cents and the brewer's
    `status` is `ACTIVE`, the brewer moves to `PROBATION` with `status_reason`
    recorded as `CHARGEBACK_BALANCE_THRESHOLD`."

    Design: Difficulty/priority_pair_validation_conflict/order_creation_agreement_state_beats_fiscal_credit_limit
    """
    ctx = _over_limit_brewer_holding_a_drafted_second_float()
    agreement_id = ctx["drafted_agreement"]["id"]

    validate_error(
        _order_attempt(agreement_id), ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409
    )
    fixtures.activate_agreement(agreement_id, "2026-08-01")
    validate_error(
        _order_attempt(agreement_id), ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 402
    )

    assert _orders_of(agreement_id) == []

    pool = fixtures.read_pool(ctx["second_pool"]["id"])
    assert pool["kegs_total"] == 4
    assert pool["kegs_available"] == 4
    assert pool["kegs_circulating"] == 0
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["status"] == "PROBATION"
    assert brewer["status_reason"] == "CHARGEBACK_BALANCE_THRESHOLD"


def _two_kegs_presented_under_another_brewery_s_collar():
    """Two kegs dispatched to the same brewer from two different pools: the first
    imported with 30 lifetime fills against a zero test counter, so it opens
    uncertified, and the second imported fresh, so it opens certified.

    A second brewery owns the `OTH` collar, so scanning either keg under `OTH`
    is a genuine cross-brand fill rather than an unknown brand code.
    """
    fixtures.pin_clock(CLOCK)
    index = fixtures.post_index("2026-07-01", 480)
    brewer = fixtures.create_brewer(credit_limit_cents=400000)
    other_brewer = fixtures.create_brewer(
        name="Other Creek Brewing", brand_code="OTH", credit_limit_cents=400000
    )

    first_pool = fixtures.create_pool(**FIRST_POOL)
    fixtures.import_kegs(
        first_pool["id"],
        [f"K-{n:04d}" for n in range(1, 9)],
        fill_count=30,
        fills_at_last_pressure_test=0,
    )
    first_agreement = fixtures.create_and_activate_agreement(
        brewer["id"], first_pool["id"], 10, effective_date="2026-08-01", **AGREEMENT
    )
    first_order = fixtures.order_allocated_and_dispatched(
        first_agreement["id"], 1, "2026-08-01T01:00:00Z"
    )
    uncertified_keg_id = first_order["allocated_keg_ids"][0]

    second_pool = fixtures.create_pool(**SECOND_POOL)
    fixtures.import_kegs(second_pool["id"], [f"K-{n:04d}" for n in range(101, 105)])
    second_agreement = fixtures.create_and_activate_agreement(
        brewer["id"], second_pool["id"], 4, effective_date="2026-08-01", **AGREEMENT
    )
    second_order = fixtures.order_allocated_and_dispatched(
        second_agreement["id"], 1, "2026-08-01T03:00:00Z"
    )
    certified_keg_id = second_order["allocated_keg_ids"][0]

    return {
        "index": index,
        "brewer": brewer,
        "other_brewer": other_brewer,
        "first_pool": first_pool,
        "second_pool": second_pool,
        "first_agreement": first_agreement,
        "second_agreement": second_agreement,
        "uncertified_keg_id": uncertified_keg_id,
        "certified_keg_id": certified_keg_id,
    }


def _fill_attempt(keg_id, brewer_id, scanned_at, brand_code):
    return api_client.scan_keg(
        keg_id,
        factories.fill_scan_payload(brewer_id, scanned_at, brand_code),
        make_brewer_headers(brewer_id),
    )


def _scan_events_for(keg_id):
    rows, _meta = validate_paginated(
        api_client.list_scan_events(OPERATOR, params={"keg_id": keg_id})
    )
    return rows


def test_the_uncertified_keg_reports_the_safety_failure_not_the_brand_failure():
    """A keg that opened `SERVICE_DUE` on 30 lifetime fills is scanned under the
    other brewery's collar, so both the certification rule and the brand rule are
    broken, and the caller is told about the certification.

    PRD: "On a fill scan of an uncertified keg presented under the wrong collar,
    the safety check at step 20 wins and the caller sees
    `ERR_KEG_NOT_FIT_FOR_FILL` (422), not the brand failure at step 27."

    PRD: "Where an uncertified keg is also presented under the wrong collar, the
    certification failure is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/fill_scan_safety_beats_referential_brand_mismatch
    """
    ctx = _two_kegs_presented_under_another_brewery_s_collar()
    keg = fixtures.read_keg(ctx["uncertified_keg_id"])

    assert keg["fill_count"] == 30
    assert keg["fills_at_last_pressure_test"] == 0
    assert keg["service_state"] == "SERVICE_DUE"
    assert keg["custody_state"] == "ISSUED_TO_BREWER"

    refused = _fill_attempt(
        ctx["uncertified_keg_id"],
        ctx["brewer"]["id"],
        "2026-08-01T02:00:00Z",
        "OTH",
    )
    validate_error(refused, ApiErrorId.ERR_KEG_NOT_FIT_FOR_FILL.value, 422)


def test_the_certified_keg_under_the_wrong_collar_reports_the_brand_failure():
    """The identical wrong-collar scan on a keg that is certified has only one
    rule left to break, and that is the brand rule.

    PRD: "A fill scan's `brand_code_scanned` equals the filling brewer's
    `brand_code` — `ERR_BRAND_MISMATCH` (422)."

    Design: Difficulty/priority_pair_validation_conflict/fill_scan_safety_beats_referential_brand_mismatch
    """
    ctx = _two_kegs_presented_under_another_brewery_s_collar()
    keg = fixtures.read_keg(ctx["certified_keg_id"])

    assert keg["fill_count"] == 0
    assert keg["service_state"] == "SERVICE_OK"
    assert keg["custody_state"] == "ISSUED_TO_BREWER"
    assert ctx["other_brewer"]["brand_code"] == "OTH"
    assert ctx["brewer"]["brand_code"] == "RDG"

    refused = _fill_attempt(
        ctx["certified_keg_id"],
        ctx["brewer"]["id"],
        "2026-08-01T04:00:00Z",
        "OTH",
    )
    validate_error(refused, ApiErrorId.ERR_BRAND_MISMATCH.value, 422)


def test_neither_refused_fill_appends_a_scan_or_posts_any_money():
    """Both kegs stay exactly as they were dispatched, no scan is appended to
    either stream, and neither agreement has billed anything.

    PRD: "An accepted fill appends the scan, raises the keg's `fill_count` by
    one, records `filled_brand_code` from `brand_code_scanned` and
    `filling_brewer_id` from `brewer_id`, closes the open custody spell in the
    manner described above, resets `dwell_started_at` to `scanned_at`, and clears
    `misdelivery_open` — refilling a keg is what settles any unreconciled
    cross-brand history on it."

    PRD: "On the agreement's side, `billed_fills_count` rises by one,
    `billed_amount_cents` grows by the fill's net charge, and the agreement's
    `version` advances."

    Design: Difficulty/priority_pair_validation_conflict/fill_scan_safety_beats_referential_brand_mismatch
    """
    ctx = _two_kegs_presented_under_another_brewery_s_collar()

    validate_error(
        _fill_attempt(
            ctx["uncertified_keg_id"],
            ctx["brewer"]["id"],
            "2026-08-01T02:00:00Z",
            "OTH",
        ),
        ApiErrorId.ERR_KEG_NOT_FIT_FOR_FILL.value,
        422,
    )
    validate_error(
        _fill_attempt(
            ctx["certified_keg_id"],
            ctx["brewer"]["id"],
            "2026-08-01T04:00:00Z",
            "OTH",
        ),
        ApiErrorId.ERR_BRAND_MISMATCH.value,
        422,
    )

    assert _scan_events_for(ctx["uncertified_keg_id"]) == []
    assert _scan_events_for(ctx["certified_keg_id"]) == []

    uncertified = fixtures.read_keg(ctx["uncertified_keg_id"])
    certified = fixtures.read_keg(ctx["certified_keg_id"])
    assert uncertified["custody_state"] == "ISSUED_TO_BREWER"
    assert certified["custody_state"] == "ISSUED_TO_BREWER"
    assert uncertified["fill_count"] == 30
    assert certified["fill_count"] == 0
    assert uncertified["filled_brand_code"] is None
    assert certified["filled_brand_code"] is None

    for agreement_id in (ctx["first_agreement"]["id"], ctx["second_agreement"]["id"]):
        agreement = fixtures.read_agreement(agreement_id)
        assert agreement["billed_fills_count"] == 0
        assert agreement["billed_amount_cents"] == 0

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["lifetime_fill_count"] == 0
