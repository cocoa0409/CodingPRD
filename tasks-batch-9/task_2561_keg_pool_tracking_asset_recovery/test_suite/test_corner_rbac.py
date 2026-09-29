"""Role-based access corners: who may reach an operation, and which 403 it is.

Three different 403s live in this specification — `ERR_FORBIDDEN_ROLE`,
`ERR_UNKNOWN_ACTOR` and `ERR_SEGREGATION_OF_DUTIES` — and the ladder of §2.8
orders them against the actor lookup, the path 404 and the payload checks.  The
scenarios below pair every refusal with the identical accepted call, so a
refusal can never be confused with an unreachable endpoint or an illegal state.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_census, assert_same_record
from test_helpers.test_users import (
    ANALYST_USER_ID,
    POOL_OPERATOR_USER_ID,
    SECOND_ANALYST_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    all_role_headers,
    make_analyst_headers,
    make_brewer_headers,
    make_distributor_headers,
    make_technician_headers,
)

OPERATOR = TEST_USERS["pool_operator_headers"]
TECH = TEST_USERS["technician_headers"]
ANALYST = make_analyst_headers(ANALYST_USER_ID)
SECOND_ANALYST = make_analyst_headers(SECOND_ANALYST_USER_ID)
UNKNOWN_BREWER = TEST_USERS["unknown_brewer_headers"]
UNKNOWN_DISTRIBUTOR = TEST_USERS["unknown_distributor_headers"]

CLOCK = "2026-08-01T23:00:00Z"
POOL = {
    "pool_code": "HB-50L",
    "size_liters": 50,
    "stainless_weight_kg": 12.5,
    "replacement_cost_cents": 23500,
    "region_code": "CO",
}
CHEAP_POOL = {
    "pool_code": "HB-CHEAP",
    "size_liters": 20,
    "stainless_weight_kg": 6.0,
    "replacement_cost_cents": 10000,
    "region_code": "CO",
}
KEG_SPECS_THREE = [
    {"asset_tag": "K-0001"},
    {"asset_tag": "K-0002", "fill_count": 5, "fills_at_last_pressure_test": 5},
    {"asset_tag": "K-0003", "fill_count": 6, "fills_at_last_pressure_test": 6},
]


# ==========================================================================
# Design: Corner/rbac/pool_operator_exclusive_writes_are_closed_to_the_other_four_roles
# ==========================================================================


def _an_empty_pool():
    fixtures.pin_clock(CLOCK)
    return fixtures.create_pool(**POOL)


def _four_roles_that_may_not_register_a_brewer():
    return [
        ("a Brewer header naming no stored brewer", UNKNOWN_BREWER),
        ("a Distributor header naming no stored distributor", UNKNOWN_DISTRIBUTOR),
        ("the wash-line crew", TECH),
        ("the recovery desk", ANALYST),
    ]


def test_brewer_registration_is_closed_to_the_other_four_roles():
    """Four well-formed identities are refused the operator's own registration
    verb, and the control create proves none of them wrote a row.

    PRD: "If the headers are well-formed but the named role is not authorised
    for the target operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD: "| POST | `/brewers` | Register a brewer as a lessee of pool kegs. | PoolOperator |"

    PRD: "Uniqueness of a brewer's `brand_code`, a pool's `pool_code`, a keg's
    `asset_tag` (globally, across every pool) and a commodity index row's
    `effective_date` — `ERR_DUPLICATE_BRAND_CODE`, `ERR_DUPLICATE_POOL_CODE`,
    `ERR_DUPLICATE_ASSET_TAG` or `ERR_DUPLICATE_INDEX_DATE` (all 409), on
    brewer creation, pool creation, keg import and index posting
    respectively."

    Design: Corner/rbac/pool_operator_exclusive_writes_are_closed_to_the_other_four_roles
    """
    _an_empty_pool()
    payload = factories.create_brewer_payload()

    for label, headers in _four_roles_that_may_not_register_a_brewer():
        error_data = validate_error(
            api_client.create_brewer(payload, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
        assert error_data["error_id"] == "ERR_FORBIDDEN_ROLE", label

    created = validate_success(api_client.create_brewer(payload, OPERATOR), 201)
    assert created["brand_code"] == payload["brand_code"]
    assert created["chargeback_balance_cents"] == 0


def test_the_role_gate_outranks_both_the_actor_lookup_and_the_path_lookup():
    """The role list is consulted before the entity-backed actor is resolved and
    before the path identifier is looked up, so neither an unknown actor nor a
    missing pool can mask the 403.

    PRD: "For both entity-backed roles, if `X-User-ID` does not match any
    existing row of the corresponding entity the request is rejected with
    `ERR_UNKNOWN_ACTOR` (HTTP 403); if it matches an existing row but not the
    row the target resource points at, the rejection is
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD: "For the entity-backed roles `Brewer` and `Distributor`, `X-User-ID`
    names an existing row of that entity — `ERR_UNKNOWN_ACTOR` (403)."

    PRD: "Every path identifier resolves, left to right — the 404 catalogue
    above."

    PRD: "| POST | `/pools/{pool_id}/replenishment-sweep` | Reclassify every dwell flag in a pool and report the replenishment triggers it raised. | PoolOperator |"

    Design: Corner/rbac/pool_operator_exclusive_writes_are_closed_to_the_other_four_roles
    """
    pool = _an_empty_pool()

    for headers in (UNKNOWN_BREWER, UNKNOWN_DISTRIBUTOR):
        validate_error(
            api_client.create_brewer(factories.create_brewer_payload(), headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )

    validate_error(
        api_client.replenishment_sweep(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.replenishment_sweep(NON_EXISTENT_UUID, OPERATOR),
        ApiErrorId.ERR_POOL_NOT_FOUND,
        404,
    )

    stored = fixtures.read_pool(pool["id"])
    assert_census(
        stored,
        {
            "kegs_total": 0,
            "kegs_available": 0,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert stored["available_pct"] == 0.00
    assert stored["posture"] == "FROZEN"


# ==========================================================================
# Design: Corner/rbac/analyst_only_verbs_are_closed_to_the_operator_and_the_brewer
# ==========================================================================


def _a_dispatched_keg_under_a_proposed_non_return_assessment():
    """One dispatched keg — chargeable through `current_brewer_id` and never
    filled — carrying a single PROPOSED assessment opened by analyst-1."""
    ctx = fixtures.setup_dispatched_float(
        requested_keg_count=1,
        dispatched_at="2026-08-01T00:00:00Z",
        float_size_kegs=3,
        keg_count=3,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_THREE,
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    ctx["keg_id"] = ctx["allocated_keg_ids"][0]
    ctx["assessment"] = fixtures.open_loss_assessment(
        ctx["keg_id"], "NOT_RETURNED_DWELL", ANALYST_USER_ID, "REPLACEMENT_COST"
    )
    return ctx


def test_the_loss_desk_verbs_are_closed_to_the_operator_and_to_the_brewer():
    """Opening, resolving and investigating are the analyst's alone, disputing is
    the brewer's alone, and all four refusals leave the desk exactly as it was.

    PRD: "If the headers are well-formed but the named role is not authorised
    for the target operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD: "| POST | `/loss-assessments` | Open a loss, damage or non-return assessment on a keg and pin its valuation. | AssetRecoveryAnalyst |"

    PRD: "| POST | `/loss-assessments/{assessment_id}/dispute` | Brewer disputes a proposed assessment, freezing supersession until it is adjudicated. | Brewer |"

    PRD: "| POST | `/loss-assessments/{assessment_id}/resolve` | Uphold or waive an assessment, segregated from the analyst who opened it. | AssetRecoveryAnalyst |"

    PRD: "| POST | `/theft-investigations` | Open a stainless-theft investigation over a set of kegs in one pool. | AssetRecoveryAnalyst |"

    Design: Corner/rbac/analyst_only_verbs_are_closed_to_the_operator_and_the_brewer
    """
    ctx = _a_dispatched_keg_under_a_proposed_non_return_assessment()
    keg_id = ctx["keg_id"]
    assessment_id = ctx["assessment"]["id"]

    validate_error(
        api_client.create_loss_assessment(
            factories.create_loss_assessment_payload(
                keg_id, "LOST_IN_TRADE", fixtures.keg_version(keg_id)
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.create_theft_investigation(
            factories.create_theft_investigation_payload(ctx["pool"]["id"], [keg_id]),
            OPERATOR,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.resolve_loss_assessment(
            assessment_id, factories.resolve_assessment_payload("WAIVED"), OPERATOR
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    validate_error(
        api_client.dispute_loss_assessment(
            assessment_id,
            {"dispute_reason": "An analyst reaching for the brewer's verb."},
            ANALYST,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )

    _, assessment_meta = validate_paginated(
        api_client.list_loss_assessments(ANALYST, params={"keg_id": keg_id})
    )
    assert assessment_meta["total_count"] == 1
    _, investigation_meta = validate_paginated(
        api_client.list_theft_investigations(ANALYST)
    )
    assert investigation_meta["total_count"] == 0
    stored = fixtures.read_assessment(assessment_id)
    assert stored["assessment_status"] == "PROPOSED"
    assert stored["dispute_reason"] is None
    assert stored["resolved_by_user_id"] is None


def test_a_second_analyst_reaches_the_very_endpoints_the_operator_could_not():
    """The waive by a second analyst succeeds on the same row, which proves the
    endpoint was reachable all along, and it is inert on money and custody.

    PRD: "An analyst **resolves** an assessment from either `PROPOSED` or
    `DISPUTED` by supplying a `resolution` of `UPHELD` or `WAIVED` and optional
    `resolution_notes`."

    PRD: "Either resolution records `resolved_by_user_id` and
    `resolution_notes` and advances the assessment's `version`."

    PRD: "A **waive** is deliberately inert: `chargeback_status` stays `NONE`,
    no money moves, the keg's `custody_state` and every pool census counter are
    left exactly as they were, `chargeback_balance_cents` is untouched, and only
    `assessment_open` is lowered."

    PRD: "Because the chargeback became `ISSUED`, the brewer's
    `chargeback_balance_cents` is recomputed, `upheld_loss_count` increases by
    one, both `loss_rate_bp_trailing_90d` and `loss_rate_bp_lifetime` are
    recomputed, and the brewer's `version` advances."

    Design: Corner/rbac/analyst_only_verbs_are_closed_to_the_operator_and_the_brewer
    """
    ctx = _a_dispatched_keg_under_a_proposed_non_return_assessment()
    assessment_id = ctx["assessment"]["id"]

    resolved = validate_success(
        api_client.resolve_loss_assessment(
            assessment_id,
            factories.resolve_assessment_payload(
                "WAIVED", resolution_notes="Keg was found in the taproom cellar."
            ),
            SECOND_ANALYST,
        )
    )
    assert resolved["assessment_status"] == "WAIVED"
    assert resolved["resolved_by_user_id"] == SECOND_ANALYST_USER_ID
    assert resolved["chargeback_status"] == "NONE"

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["assessment_open"] is False
    assert keg["custody_state"] == "ISSUED_TO_BREWER"
    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 0
    assert brewer["upheld_loss_count"] == 0
    assert brewer["status"] == "ACTIVE"


# ==========================================================================
# Design: Corner/rbac/assessment_creator_cannot_resolve_the_assessment_they_opened
# ==========================================================================


def _a_disputed_assessment_opened_by_the_first_analyst():
    """A filled keg — so an uphold has a declared LOST edge — under an
    assessment opened by analyst-1 and then disputed by the brewer."""
    ctx = fixtures.setup_filled_keg(
        scanned_at="2026-08-01T12:00:00Z",
        dispatched_at="2026-08-01T00:00:00Z",
        requested_keg_count=1,
        float_size_kegs=3,
        keg_count=3,
        pool_overrides=POOL,
        keg_specs=KEG_SPECS_THREE,
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    ctx["assessment"] = fixtures.open_loss_assessment(
        ctx["keg_id"], "LOST_IN_TRADE", ANALYST_USER_ID, "REPLACEMENT_COST"
    )
    fixtures.dispute_assessment(
        ctx["assessment"]["id"],
        ctx["brewer"]["id"],
        "The distributor signed for this keg.",
    )
    return ctx


def test_the_analyst_who_opened_the_loss_may_neither_uphold_nor_waive_it():
    """Both resolutions by the creating analyst are refused on segregation
    grounds — not on role and not on state — and neither writes.

    PRD: "The acting `X-User-ID` must differ from the assessment's
    `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`: the analyst who
    raised the loss may not be the one who confirms it."

    PRD: "Money segregation of duties, in two clauses, both
    `ERR_SEGREGATION_OF_DUTIES` (403). On resolution, the identifier resolving
    an assessment differs from its `created_by_user_id`."

    PRD: "An analyst **resolves** an assessment from either `PROPOSED` or
    `DISPUTED` by supplying a `resolution` of `UPHELD` or `WAIVED` and optional
    `resolution_notes`."

    Design: Corner/rbac/assessment_creator_cannot_resolve_the_assessment_they_opened
    """
    ctx = _a_disputed_assessment_opened_by_the_first_analyst()
    assessment_id = ctx["assessment"]["id"]
    version_before = fixtures.read_assessment(assessment_id)["version"]

    for resolution in ("UPHELD", "WAIVED"):
        validate_error(
            api_client.resolve_loss_assessment(
                assessment_id,
                factories.resolve_assessment_payload(
                    resolution, resolution_notes="Own work, own verdict."
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

    stored = fixtures.read_assessment(assessment_id)
    assert stored["assessment_status"] == "DISPUTED"
    assert stored["created_by_user_id"] == ANALYST_USER_ID
    assert stored["resolved_by_user_id"] is None
    assert stored["chargeback_status"] == "NONE"
    assert stored["version"] == version_before
    assert fixtures.read_brewer(ctx["brewer"]["id"])["chargeback_balance_cents"] == 0


def test_a_second_analyst_upholds_the_very_same_disputed_row():
    """The rule compares the actor with the creator and not with the last actor,
    so the analyst who never touched the row carries the whole uphold cascade.

    PRD: "The assessment moves to `UPHELD` and, when `net_chargeback_cents` is
    greater than zero, `chargeback_status` flips from `NONE` to `ISSUED` in the
    same request."

    PRD: "The keg is written off according to the cause:
    `DAMAGED_BEYOND_REPAIR` scraps it, `LOST_IN_TRADE` and `NOT_RETURNED_DWELL`
    mark it lost, and `STOLEN_SUSPECTED` leaves custody alone."

    PRD: "Under **`REPLACEMENT_COST`**, `gross_value_cents` is simply the pool's
    `replacement_cost_cents`, and `fill_count` is ignored entirely."

    PRD: "And `net_chargeback_cents` is the assessed value multiplied by that
    liability share as a proportion of 10000, rounded half up."

    PRD: "`LOSS_RATE_THRESHOLD` therefore appears only when the recomputed
    balance is strictly below 25000 cents while the trailing rate is at or above
    1500 basis points."

    Design: Corner/rbac/assessment_creator_cannot_resolve_the_assessment_they_opened
    """
    ctx = _a_disputed_assessment_opened_by_the_first_analyst()

    resolved = validate_success(
        api_client.resolve_loss_assessment(
            ctx["assessment"]["id"],
            factories.resolve_assessment_payload(
                "UPHELD", resolution_notes="Independent review confirms the loss."
            ),
            SECOND_ANALYST,
        )
    )
    assert resolved["assessment_status"] == "UPHELD"
    assert resolved["resolved_by_user_id"] == SECOND_ANALYST_USER_ID
    assert resolved["chargeback_status"] == "ISSUED"
    assert resolved["gross_value_cents"] == 23500
    assert resolved["net_chargeback_cents"] == 14100

    assert fixtures.read_keg(ctx["keg_id"])["custody_state"] == "LOST"
    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 14100
    assert brewer["upheld_loss_count"] == 1
    assert brewer["loss_rate_bp_trailing_90d"] == 10000
    assert brewer["status"] == "PROBATION"
    assert brewer["status_reason"] == "LOSS_RATE_THRESHOLD"


# ==========================================================================
# Design: Corner/rbac/the_two_money_verbs_are_split_across_the_two_roles_that_reach_the_endpoint
# ==========================================================================

CHEAP_KEG_SPECS = [
    {"asset_tag": "C-0001"},
    {"asset_tag": "C-0002"},
    {"asset_tag": "C-0003"},
    {"asset_tag": "C-0004"},
]


def _two_issued_chargebacks_of_six_thousand():
    """Two filled kegs in a cheap pool, each written off under an assessment the
    *other* analyst upheld, so the ledger stands at 12000 with both rows
    ISSUED and the brewer on loss-rate probation."""
    ctx = fixtures.setup_dispatched_float(
        requested_keg_count=2,
        dispatched_at="2026-08-01T00:00:00Z",
        float_size_kegs=4,
        keg_count=4,
        pool_overrides=CHEAP_POOL,
        keg_specs=CHEAP_KEG_SPECS,
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    brewer_id = ctx["brewer"]["id"]
    brand_code = ctx["brewer"]["brand_code"]
    first_keg, second_keg = ctx["allocated_keg_ids"][0], ctx["allocated_keg_ids"][1]
    fixtures.fill_scan(first_keg, brewer_id, "2026-08-01T12:00:00Z", brand_code)
    fixtures.fill_scan(second_keg, brewer_id, "2026-08-01T13:00:00Z", brand_code)

    first = fixtures.open_loss_assessment(
        first_keg, "LOST_IN_TRADE", ANALYST_USER_ID, "REPLACEMENT_COST"
    )
    fixtures.resolve_assessment(first["id"], "UPHELD", SECOND_ANALYST_USER_ID)
    second = fixtures.open_loss_assessment(
        second_keg, "LOST_IN_TRADE", SECOND_ANALYST_USER_ID, "REPLACEMENT_COST"
    )
    fixtures.resolve_assessment(second["id"], "UPHELD", ANALYST_USER_ID)

    ctx["first_keg"] = first_keg
    ctx["second_keg"] = second_keg
    ctx["first_assessment"] = fixtures.read_assessment(first["id"])
    ctx["second_assessment"] = fixtures.read_assessment(second["id"])
    return ctx


def test_settling_is_the_operators_verb_and_it_outranks_the_amount_check():
    """An analyst reaching the shared endpoint with a `SETTLE` is refused on
    segregation grounds even when the amount is also wrong, and the operator's
    settlement leaves the ledger where it was.

    PRD: "Both `PoolOperator` and `AssetRecoveryAnalyst` reach this operation,
    but the acting role must match the requested action: `SETTLE` requires
    `PoolOperator` and `REVERSE` requires `AssetRecoveryAnalyst`, so no single
    role can both raise and erase a chargeback."

    PRD: "A mismatch is `ERR_SEGREGATION_OF_DUTIES`, and it is judged *before*
    the settlement amount is compared — an analyst attempting a settlement with
    the wrong amount sees the segregation failure, not the amount failure."

    PRD: "A `SETTLE` requires `chargeback_status` `ISSUED` and an `amount_cents`
    exactly equal to `net_chargeback_cents`; partial settlement is not supported
    and any other figure is `ERR_SETTLEMENT_AMOUNT_MISMATCH`."

    PRD: "It moves the status to `SETTLED`, records `settled_amount_cents`, and
    leaves `chargeback_balance_cents` unchanged."

    Design: Corner/rbac/the_two_money_verbs_are_split_across_the_two_roles_that_reach_the_endpoint
    """
    ctx = _two_issued_chargebacks_of_six_thousand()
    assessment_id = ctx["first_assessment"]["id"]
    assert ctx["first_assessment"]["net_chargeback_cents"] == 6000
    assert fixtures.read_brewer(ctx["brewer"]["id"])["chargeback_balance_cents"] == 12000

    for amount in (6000, 1):
        validate_error(
            api_client.chargeback_resolution(
                assessment_id,
                factories.chargeback_resolution_payload("SETTLE", amount_cents=amount),
                SECOND_ANALYST,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
    assert fixtures.read_assessment(assessment_id)["chargeback_status"] == "ISSUED"

    settled = validate_success(
        api_client.chargeback_resolution(
            assessment_id,
            factories.chargeback_resolution_payload("SETTLE", amount_cents=6000),
            OPERATOR,
        )
    )
    assert settled["chargeback_status"] == "SETTLED"
    assert settled["settled_amount_cents"] == 6000
    assert settled["assessment_status"] == "UPHELD"
    assert fixtures.read_brewer(ctx["brewer"]["id"])["chargeback_balance_cents"] == 12000


def test_reversing_is_the_analysts_verb_and_it_leaves_the_probation_standing():
    """The operator cannot reverse what it may settle; the analyst's reversal
    drops its row out of the ledger without resurrecting the keg, without
    touching the loss counters and without lifting a loss-rate probation.

    PRD: "The **chargeback ledger** is a conserved quantity: a brewer's
    `chargeback_balance_cents` is always the sum of `net_chargeback_cents` across
    that brewer's assessments whose `chargeback_status` is `ISSUED` or
    `SETTLED`."

    PRD: "A `REVERSE` also requires `ISSUED` and moves the status to `REVERSED`,
    which drops the row out of the sum and restores the balance to exactly its
    pre-uphold value — bit for bit, with no drift."

    PRD: "A probation whose reason is `LOSS_RATE_THRESHOLD`, or any free text an
    operator set through the brewer-status override, is not lifted by a reversal
    even though the balance falls: a reversal only undoes the gate it tripped."

    PRD: "And the loss counters are money-independent — `upheld_loss_count` and
    both loss-rate figures are never recomputed by a reversal — so the trailing
    rate that forced probation still stands afterwards."

    PRD: "The target resource sits in a state from which the requested transition
    is declared: order `status` for allocate, dispatch and cancel; cycle `stage`
    for step recording and release; `assessment_status` for dispute and resolve;
    `chargeback_status` for chargeback resolution; claim `status` for a response;
    investigation `status` for a status change; keg `custody_state` being
    `IN_FLOAT` or `IN_SERVICE` for a service-cycle booking; and, on a fill scan,
    the keg's governing issuance order being `DISPATCHED`. Failure is
    `ERR_INVALID_STATE` (409)."

    Design: Corner/rbac/the_two_money_verbs_are_split_across_the_two_roles_that_reach_the_endpoint
    """
    ctx = _two_issued_chargebacks_of_six_thousand()
    first_id = ctx["first_assessment"]["id"]
    second_id = ctx["second_assessment"]["id"]
    fixtures.settle_chargeback(first_id, 6000)

    validate_error(
        api_client.chargeback_resolution(
            second_id,
            factories.chargeback_resolution_payload(
                "REVERSE", resolution_notes="Operator erasing its own liability."
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert fixtures.read_assessment(second_id)["chargeback_status"] == "ISSUED"

    reversed_row = validate_success(
        api_client.chargeback_resolution(
            second_id,
            factories.chargeback_resolution_payload(
                "REVERSE", resolution_notes="Shell recovered from the yard."
            ),
            ANALYST,
        )
    )
    assert reversed_row["chargeback_status"] == "REVERSED"
    assert reversed_row["assessment_status"] == "UPHELD"

    brewer = fixtures.read_brewer(ctx["brewer"]["id"])
    assert brewer["chargeback_balance_cents"] == 6000
    assert brewer["upheld_loss_count"] == 2
    assert brewer["loss_rate_bp_trailing_90d"] == 10000
    assert brewer["status"] == "PROBATION"
    assert brewer["status_reason"] == "LOSS_RATE_THRESHOLD"
    assert fixtures.read_agreement(ctx["agreement"]["id"])["float_posture"] == "SUSPENDED"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 2,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 2,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"

    validate_error(
        api_client.chargeback_resolution(
            first_id,
            factories.chargeback_resolution_payload(
                "REVERSE", resolution_notes="Too late, that one is settled."
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    assert fixtures.read_assessment(first_id)["chargeback_status"] == "SETTLED"


# ==========================================================================
# Design: Corner/rbac/the_scan_endpoint_is_shared_by_three_roles_and_closed_to_two
# ==========================================================================


def _two_dispatched_kegs_and_a_wholesaler():
    ctx = fixtures.setup_dispatched_float(
        requested_keg_count=2,
        dispatched_at="2026-08-01T00:00:00Z",
        float_size_kegs=4,
        keg_count=4,
        pool_overrides=POOL,
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    ctx["distributor"] = fixtures.create_distributor()
    ctx["first_keg"] = ctx["allocated_keg_ids"][0]
    ctx["second_keg"] = ctx["allocated_keg_ids"][1]
    return ctx


def _fill_one_keg_as_the_operator_and_one_as_the_brewer(ctx):
    brewer_id = ctx["brewer"]["id"]
    brand_code = ctx["brewer"]["brand_code"]
    by_operator = validate_success(
        api_client.scan_keg(
            ctx["first_keg"],
            factories.fill_scan_payload(brewer_id, "2026-08-01T10:00:00Z", brand_code),
            OPERATOR,
        ),
        201,
    )
    by_brewer = validate_success(
        api_client.scan_keg(
            ctx["second_keg"],
            factories.fill_scan_payload(brewer_id, "2026-08-01T11:00:00Z", brand_code),
            make_brewer_headers(brewer_id),
        ),
        201,
    )
    return by_operator, by_brewer


def test_an_operator_may_scan_on_a_brewers_behalf_without_being_that_brewer():
    """The ownership binding at step 8 reaches only the entity-backed roles, so
    the operator's opaque identifier never has to match the body's `brewer_id`.

    PRD: "| POST | `/kegs/{keg_id}/scan` | Append a custody scan to a keg, projecting its custody state and, for a fill, billing the fill. | PoolOperator, Brewer, Distributor |"

    PRD: "When `X-User-Role` is `PoolOperator`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity; the server may record it (for
    example as `released_by_user_id` on a service cycle) but never compares it to
    any entity's `id`."

    PRD: "When `X-User-Role` is `Brewer`, `X-User-ID` is the `id` of the acting
    `Brewer` row; ownership checks on any resource that references a brewer
    compare the resource's brewer-side foreign key to `X-User-ID` — specifically
    the `brewer_id` of a loss assessment being disputed, the
    `misdelivered_to_brewer_id` of a reconciliation claim being answered, and the
    `brewer_id` supplied on a fill scan."

    PRD: "Entity-backed ownership of the now-known target resource —
    `ERR_NOT_RESOURCE_OWNER` (403), on every operation whose authorised roles
    include `Brewer` or `Distributor` and that names an existing resource."

    Design: Corner/rbac/the_scan_endpoint_is_shared_by_three_roles_and_closed_to_two
    """
    ctx = _two_dispatched_kegs_and_a_wholesaler()
    by_operator, by_brewer = _fill_one_keg_as_the_operator_and_one_as_the_brewer(ctx)

    brewer_id = ctx["brewer"]["id"]
    assert by_operator["brewer_id"] == brewer_id
    assert by_brewer["brewer_id"] == brewer_id
    assert by_operator["scan_point"] == "FILL"
    assert fixtures.read_keg(ctx["first_keg"])["filling_brewer_id"] == brewer_id
    assert fixtures.read_keg(ctx["second_keg"])["fill_count"] == 1


def test_the_technician_and_the_analyst_are_refused_a_scan_the_wholesaler_makes():
    """Two roles are outside the scan's role list, and the identical body sent by
    the distributor immediately afterwards proves the keg was scannable
    throughout.

    PRD: "If the headers are well-formed but the named role is not authorised
    for the target operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    PRD: "A **distribution** scan is recorded by the wholesaler taking custody:
    the `party_type` is `DISTRIBUTOR` and the `distributor_id` identifies the
    wholesaler, whose `status` must not be `SUSPENDED` — otherwise
    `ERR_DISTRIBUTOR_SUSPENDED` — and which, when the caller acts as
    `Distributor`, must match `X-User-ID`."

    PRD: "The keg moves `FILLED → IN_TRADE`, records `current_distributor_id`,
    and opens a fresh distributor accountability spell by setting
    `distributor_custody_started_at` to the scan's `scanned_at`."

    Design: Corner/rbac/the_scan_endpoint_is_shared_by_three_roles_and_closed_to_two
    """
    ctx = _two_dispatched_kegs_and_a_wholesaler()
    _fill_one_keg_as_the_operator_and_one_as_the_brewer(ctx)
    distributor_id = ctx["distributor"]["id"]
    payload = factories.distribution_scan_payload(
        distributor_id, "2026-08-01T12:00:00Z", ctx["brewer"]["brand_code"]
    )

    for headers in (TECH, ANALYST):
        validate_error(
            api_client.scan_keg(ctx["first_keg"], payload, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )

    validate_success(
        api_client.scan_keg(
            ctx["first_keg"], payload, make_distributor_headers(distributor_id)
        ),
        201,
    )

    _, first_meta = validate_paginated(
        api_client.list_scan_events(OPERATOR, params={"keg_id": ctx["first_keg"]})
    )
    assert first_meta["total_count"] == 2
    _, second_meta = validate_paginated(
        api_client.list_scan_events(OPERATOR, params={"keg_id": ctx["second_keg"]})
    )
    assert second_meta["total_count"] == 1

    first_keg = fixtures.read_keg(ctx["first_keg"])
    assert first_keg["custody_state"] == "IN_TRADE"
    assert first_keg["current_brewer_id"] == ctx["brewer"]["id"]
    assert first_keg["current_distributor_id"] == distributor_id
    assert fixtures.read_keg(ctx["second_keg"])["custody_state"] == "FILLED"

    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 4,
            "kegs_available": 2,
            "kegs_circulating": 2,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 50.00
    assert pool["posture"] == "OPEN"


# ==========================================================================
# Design: Corner/rbac/service_cycle_create_and_release_are_shared_but_the_steps_are_technician_only
# ==========================================================================


def _a_cycle_the_operator_booked_itself():
    """A recertification pull booked by the operator — the shared create verb —
    on a two-keg pool with a two-slot wash line."""
    stock = fixtures.setup_pool_with_kegs(
        keg_count=2, pool_overrides=POOL, clock=CLOCK
    )
    center = fixtures.create_service_center(
        concurrent_cycle_capacity=2, name="Denver Wash Bay", intake_buffer_hours=4
    )
    keg_id = stock["kegs"][0]["id"]
    cycle = fixtures.create_service_cycle(keg_id, center["id"], "2026-08-01T09:00:00Z")
    return {
        "pool": stock["pool"],
        "center": center,
        "keg_id": keg_id,
        "cycle": cycle,
    }


def test_recording_a_step_is_closed_even_to_the_operator_that_booked_the_cycle():
    """The middle verb of the service workflow is the technician's exclusive one,
    so the operator is refused inside a cycle it opened one call earlier.

    PRD: "| POST | `/service-cycles` | Book a keg onto a service line, consuming an intake window and an occupancy slot. | PoolOperator, ServiceTechnician |"

    PRD: "| POST | `/service-cycles/{cycle_id}/record-step` | Record the cleaning, inspection or pressure-test step of a service cycle. | ServiceTechnician |"

    PRD: "A `ServiceTechnician` records each step by naming a `step` of `CLEAN`,
    `INSPECT` or `PRESSURE_TEST` together with an `occurred_at` and the fields
    that step produces."

    PRD: "It records `caustic_cycle_minutes`, which must be at least 12 — a
    shorter caustic wash is refused with `ERR_CAUSTIC_CYCLE_TOO_SHORT` — sets
    `cleaned_at` and advances the stage to `CLEANED`."

    Design: Corner/rbac/service_cycle_create_and_release_are_shared_but_the_steps_are_technician_only
    """
    ctx = _a_cycle_the_operator_booked_itself()
    cycle_id = ctx["cycle"]["id"]
    assert ctx["cycle"]["stage"] == "RECEIVED"
    payload = factories.clean_step_payload("2026-08-01T10:00:00Z", 15)

    for headers in (OPERATOR, ANALYST):
        validate_error(
            api_client.record_service_step(cycle_id, payload, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
    assert fixtures.read_cycle(cycle_id)["stage"] == "RECEIVED"

    cleaned = validate_success(
        api_client.record_service_step(cycle_id, payload, TECH)
    )
    assert cleaned["stage"] == "CLEANED"
    assert cleaned["caustic_cycle_minutes"] == 15
    assert cleaned["cleaned_at"] == "2026-08-01T10:00:00Z"


def test_the_release_carries_two_different_403s_before_the_operator_signs_it_off():
    """On one endpoint the certifying technician is refused for segregation and a
    brewer is refused for role, and the shared release is what lets the operator
    close the cycle.

    PRD: "| POST | `/service-cycles/{cycle_id}/release` | Release a pressure-tested keg back into pool float, segregated from the certifying technician. | PoolOperator, ServiceTechnician |"

    PRD: "With an adequate pressure, a `pressure_test_result` of `PASS` advances
    the stage to `PRESSURE_TESTED`, records `pressure_tested_at` and stamps
    `pressure_test_performed_by_user_id` with the acting `X-User-ID`, while a
    `FAIL` diverts to `QUARANTINED` with `quarantine_reason`
    `PRESSURE_TEST_FAIL` and sets the keg's `service_state` to
    `SERVICE_FAILED`."

    PRD: "The caller supplies a `released_at`; the cycle must be in
    `PRESSURE_TESTED` with `pressure_test_result` `PASS`, and the acting
    `X-User-ID` must differ from the cycle's
    `pressure_test_performed_by_user_id`, otherwise the release is refused with
    `ERR_SEGREGATION_OF_DUTIES` — the technician who certified the keg may not
    also be the one who signs it back into service."

    PRD: "Release sets `stage` to `RELEASED`, records `released_at` and
    `released_by_user_id`, and decrements the centre's `open_cycle_count`."

    PRD: "On the keg it is a full reset: custody returns to `IN_FLOAT`,
    `service_state` becomes `SERVICE_OK`, `fills_at_last_pressure_test` is set to
    the current `fill_count`, `last_pressure_test_at` is set to the cycle's
    `pressure_tested_at` rather than to `released_at`, `current_brewer_id`,
    `current_distributor_id`, `issuance_order_id` and
    `distributor_custody_started_at` are all cleared, `dwell_started_at` is set
    to `released_at`, `dwell_flag` returns to `WITHIN_LIMIT`, and the keg's
    `version` advances."

    Design: Corner/rbac/service_cycle_create_and_release_are_shared_but_the_steps_are_technician_only
    """
    ctx = _a_cycle_the_operator_booked_itself()
    cycle_id = ctx["cycle"]["id"]
    fixtures.record_clean(cycle_id, "2026-08-01T10:00:00Z", 15, TECHNICIAN_USER_ID)
    fixtures.record_inspect(cycle_id, "2026-08-01T11:00:00Z", "PASS", TECHNICIAN_USER_ID)
    tested = fixtures.record_pressure_test(
        cycle_id, "2026-08-01T12:00:00Z", 34, "PASS", TECHNICIAN_USER_ID
    )
    assert tested["stage"] == "PRESSURE_TESTED"
    assert tested["pressure_test_performed_by_user_id"] == TECHNICIAN_USER_ID

    release_body = {"released_at": "2026-08-01T13:00:00Z"}
    validate_error(
        api_client.release_service_cycle(
            cycle_id, release_body, make_technician_headers(TECHNICIAN_USER_ID)
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    validate_error(
        api_client.release_service_cycle(cycle_id, release_body, UNKNOWN_BREWER),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
        403,
    )
    assert fixtures.read_cycle(cycle_id)["stage"] == "PRESSURE_TESTED"

    released = validate_success(
        api_client.release_service_cycle(cycle_id, release_body, OPERATOR)
    )
    assert released["stage"] == "RELEASED"
    assert released["released_by_user_id"] == POOL_OPERATOR_USER_ID
    assert released["released_at"] == "2026-08-01T13:00:00Z"

    keg = fixtures.read_keg(ctx["keg_id"])
    assert keg["custody_state"] == "IN_FLOAT"
    assert keg["service_state"] == "SERVICE_OK"
    assert keg["last_pressure_test_at"] == "2026-08-01T12:00:00Z"
    assert keg["fills_at_last_pressure_test"] == 0
    assert keg["dwell_started_at"] == "2026-08-01T13:00:00Z"

    center = validate_success(
        api_client.get_service_center(ctx["center"]["id"], OPERATOR)
    )
    assert center["open_cycle_count"] == 0
    pool = fixtures.read_pool(ctx["pool"]["id"])
    assert_census(
        pool,
        {
            "kegs_total": 2,
            "kegs_available": 2,
            "kegs_circulating": 0,
            "kegs_servicing": 0,
            "kegs_held": 0,
            "kegs_written_off": 0,
        },
    )
    assert pool["available_pct"] == 100.00
    assert pool["posture"] == "OPEN"


# ==========================================================================
# Design: Corner/rbac/read_endpoints_carry_their_own_role_lists_and_a_refusal_is_403_not_404
# ==========================================================================


def _a_keg_in_trade_and_an_investigation_over_a_second_keg():
    """One keg carrying both party foreign keys, so neither entity-backed role
    can fail the ownership binding on it, plus an investigation over a keg that
    never left float."""
    ctx = fixtures.setup_keg_in_trade(
        fill_scanned_at="2026-08-01T10:00:00Z",
        distribution_scanned_at="2026-08-01T11:00:00Z",
        requested_keg_count=1,
        float_size_kegs=4,
        keg_count=4,
        pool_overrides=POOL,
        effective_date="2026-08-01",
        clock=CLOCK,
    )
    other_keg = [
        keg["id"] for keg in ctx["kegs"] if keg["id"] not in ctx["allocated_keg_ids"]
    ][0]
    ctx["investigation"] = fixtures.open_investigation(
        ctx["pool"]["id"], [other_keg], ANALYST_USER_ID
    )
    return ctx


def test_the_keg_read_is_open_to_all_five_roles_and_is_not_projected_per_role():
    """Every declared role gets the same row back, byte for byte, and no read
    advances a version.

    PRD: "| GET | `/kegs/{keg_id}` | Read one keg with both state dimensions, its dwell position and a freshly recomputed scrap value. | PoolOperator, Brewer, Distributor, ServiceTechnician, AssetRecoveryAnalyst |"

    PRD: "The five roles are `PoolOperator`, `Brewer`, `Distributor`,
    `ServiceTechnician` and `AssetRecoveryAnalyst`."

    PRD: "Reads never advance a `version`."

    Design: Corner/rbac/read_endpoints_carry_their_own_role_lists_and_a_refusal_is_403_not_404
    """
    ctx = _a_keg_in_trade_and_an_investigation_over_a_second_keg()
    keg_id = ctx["keg_id"]
    headers_by_role = all_role_headers(ctx["brewer"]["id"], ctx["distributor"]["id"])

    reads = {}
    for role, headers in headers_by_role.items():
        reads[role] = validate_success(api_client.get_keg(keg_id, headers))

    baseline = reads["PoolOperator"]
    assert baseline["custody_state"] == "IN_TRADE"
    assert baseline["current_brewer_id"] == ctx["brewer"]["id"]
    assert baseline["current_distributor_id"] == ctx["distributor"]["id"]
    for role, data in reads.items():
        assert_same_record(baseline, data, f"keg read as {role}")
    assert fixtures.read_keg(keg_id)["version"] == baseline["version"]


def test_two_other_reads_exclude_different_roles_and_never_answer_with_a_404():
    """The agreement read excludes the distributor and the technician while the
    investigation read excludes the brewer and the technician, and every refusal
    is a 403 on a row the same request would have found.

    PRD: "| GET | `/float-agreements/{agreement_id}` | Read one agreement with its float posture and billing tallies. | PoolOperator, Brewer, AssetRecoveryAnalyst |"

    PRD: "| GET | `/theft-investigations/{investigation_id}` | Read one investigation with its held and attached counts and stainless exposure. | PoolOperator, AssetRecoveryAnalyst |"

    PRD: "The authorised roles for each operation are listed in the endpoint
    table in §4."

    PRD: "`attached_keg_count` records how many kegs are attached,
    `held_keg_count` starts at 0, and `stainless_value_at_risk_cents` is computed
    as the aggregate scrap exposure of the attached kegs: for each attached keg,
    its pool's `stainless_weight_kg` multiplied by the stainless price in force
    multiplied by the 65 percent recovery factor, rounded half up **per keg**,
    and only then summed."

    Design: Corner/rbac/read_endpoints_carry_their_own_role_lists_and_a_refusal_is_403_not_404
    """
    ctx = _a_keg_in_trade_and_an_investigation_over_a_second_keg()
    agreement_id = ctx["agreement"]["id"]
    investigation_id = ctx["investigation"]["id"]
    brewer_headers = make_brewer_headers(ctx["brewer"]["id"])
    distributor_headers = make_distributor_headers(ctx["distributor"]["id"])

    for headers in (distributor_headers, TECH):
        validate_error(
            api_client.get_float_agreement(agreement_id, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
    agreement = validate_success(
        api_client.get_float_agreement(agreement_id, brewer_headers)
    )
    assert agreement["status"] == "ACTIVE"

    for headers in (brewer_headers, TECH):
        validate_error(
            api_client.get_theft_investigation(investigation_id, headers),
            ApiErrorId.ERR_FORBIDDEN_ROLE,
            403,
        )
    investigation = validate_success(
        api_client.get_theft_investigation(investigation_id, ANALYST)
    )
    assert investigation["status"] == "OPEN"
    assert investigation["attached_keg_count"] == 1
    assert investigation["held_keg_count"] == 0
    assert investigation["stainless_value_at_risk_cents"] == 3900

    assert fixtures.read_agreement(agreement_id)["version"] == agreement["version"]
    assert (
        fixtures.read_investigation(investigation_id)["version"]
        == investigation["version"]
    )
