"""Credits: raising them by hand, capping them, and reversing them."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_single_departure_route,
    assert_credit_balance_matches_issued_memos,
    assert_credit_memo,
    create_active_contract,
    list_credit_memos,
    set_clock,
    setup_missed_trip_with_memo,
    validate_error,
    validate_paginated,
    validate_success,
    void_credit_memo,
)

ADMIN = TEST_USERS["contract_admin_headers"]
LIAISON = TEST_USERS["client_liaison_headers"]
PLANNER = TEST_USERS["ops_planner_headers"]


def _two_contract_scenario():
    """Contract Alpha with no routes, and Contract Beta owning a single SCHEDULED
    trip on 2026-09-02. Both carry a 4500-cent per-missed-trip penalty, so the
    per-memo ceiling is 13500."""
    set_clock("2026-09-01T06:00:00Z")
    alpha = create_active_contract(client_name="Contract Alpha", site_type="HOTEL")
    beta = create_active_contract(client_name="Contract Beta", site_type="CAMPUS")
    built = add_single_departure_route(beta["id"], 420, loop_minutes=48, name="Beta Loop")
    return {"alpha": alpha, "beta": beta, "beta_trip": built["trip"]}


# ─── Ladder precedence: referential before fiscal ─────────────────────────────

def test_trip_contract_mismatch_is_reported_before_the_memo_cap(api):
    """PRD §2.6: "Every request is screened through the same ordered ladder of
    checks, and the ladder is evaluated strictly in the order given below. The first
    check that fails determines the response, and no later check is evaluated."
    PRD §2.6: "29. **Trip contract match**, on credit memo creation and on an
    on-demand match that names an explicit `trip_id`: `ERR_TRIP_CONTRACT_MISMATCH`
    (422)."
    PRD §3.7: "Where `trip_id` is supplied, that trip's `contract_id` must equal the
    `contract_id` in the body, failing which the memo is rejected with
    `ERR_TRIP_CONTRACT_MISMATCH` and HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/memo_referential_beats_fiscal_cap
    """
    scenario = _two_contract_scenario()

    response = api.create_credit_memo(
        {
            "contract_id": scenario["alpha"]["id"],
            "trip_id": scenario["beta_trip"]["id"],
            "amount_cents": 20_000,
            "reason": "GOODWILL",
        },
        LIAISON,
    )
    validate_error(response, ApiErrorId.ERR_TRIP_CONTRACT_MISMATCH.value, 422)

    alpha = validate_success(api.get_contract(scenario["alpha"]["id"], ADMIN))
    assert alpha["credit_balance_cents"] == 0
    assert list_credit_memos(contract_id=scenario["alpha"]["id"]) == []


def test_memo_above_three_times_the_penalty_rate_is_rejected(api):
    """PRD §3.7: "The amount is capped commercially: `amount_cents` must be at least
    1 and at most three times the contract's `penalty_rate_cents_per_missed_trip`,
    and an amount below 1 or above that ceiling is rejected with
    `ERR_MEMO_AMOUNT_EXCEEDS_CAP` and HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/memo_referential_beats_fiscal_cap
    """
    scenario = _two_contract_scenario()

    response = api.create_credit_memo(
        {
            "contract_id": scenario["beta"]["id"],
            "trip_id": scenario["beta_trip"]["id"],
            "amount_cents": 20_000,
            "reason": "GOODWILL",
        },
        LIAISON,
    )
    validate_error(response, ApiErrorId.ERR_MEMO_AMOUNT_EXCEEDS_CAP.value, 422)

    beta = validate_success(api.get_contract(scenario["beta"]["id"], ADMIN))
    assert beta["credit_balance_cents"] == 0

    accepted = validate_success(
        api.create_credit_memo(
            {
                "contract_id": scenario["beta"]["id"],
                "trip_id": scenario["beta_trip"]["id"],
                "amount_cents": 13_500,
                "reason": "GOODWILL",
            },
            LIAISON,
        ),
        expected_status=201,
    )
    assert accepted["amount_cents"] == 13_500, "exactly three times the penalty rate passes"


# ─── The compensating pair on money ───────────────────────────────────────────

def test_void_restores_the_contract_balance_to_its_pre_issue_value(api):
    """PRD §3.7: "The memo moves to `VOIDED`, the contract's `credit_balance_cents`
    is recomputed — returning, because it is a full recomputation, to exactly its
    pre-issue value — and the contract's `version` increments by one."

    Design: Difficulty/compensating_invariant/credit_memo_void_restores_contract_balance
    """
    scenario = setup_missed_trip_with_memo(
        contract_overrides={"client_name": "Ledger Hotel"}
    )
    mid = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert mid["credit_balance_cents"] == 4_500

    voided = validate_success(
        api.void_credit_memo(
            scenario["memo"]["id"],
            {"voided_reason": "trip was operated after all"},
            ADMIN,
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["amount_cents"] == 4_500
    assert_credit_memo(voided)

    after = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert after["credit_balance_cents"] == 0, (
        "the balance returns to exactly its pre-issue value of 0, got "
        f"{after['credit_balance_cents']}"
    )

    trip = validate_success(api.get_trip(scenario["trip"]["id"], PLANNER))
    assert trip["settlement_status"] == "UNBILLED"
    assert trip["dispatch_status"] == "MISSED"


def test_voided_memo_keeps_the_issued_sum_invariant(api):
    """PRD §3.1: "That figure is the sum of `amount_cents` over every credit memo of
    this contract whose `status` is `ISSUED`; memos that have been applied to a
    report or voided are excluded, so the balance always reads as outstanding,
    not-yet-settled credit. It is recomputed in full — never adjusted by a delta —
    every time a memo is minted, voided, or applied."

    Design: Difficulty/compensating_invariant/credit_memo_void_restores_contract_balance
    """
    scenario = setup_missed_trip_with_memo(
        contract_overrides={"client_name": "Ledger Hotel"}
    )
    contract_id = scenario["contract"]["id"]

    before = validate_success(api.get_contract(contract_id, ADMIN))
    assert_credit_balance_matches_issued_memos(before, list_credit_memos(contract_id=contract_id))

    void_credit_memo(scenario["memo"]["id"], "trip was operated after all")

    after = validate_success(api.get_contract(contract_id, ADMIN))
    memos = list_credit_memos(contract_id=contract_id)
    assert_credit_balance_matches_issued_memos(after, memos)
    assert after["credit_balance_cents"] == 0
    assert all(m["status"] == "VOIDED" for m in memos)


def test_voiding_a_voided_memo_is_rejected(api):
    """PRD §3.7: "A `ContractAdmin` supplies a `voided_reason`; the memo must
    currently be `ISSUED`, and a memo that is already `APPLIED` or `VOIDED` is
    rejected with `ERR_MEMO_NOT_ISSUED`."

    Design: Corner/state_machines/void_a_voided_memo_returns_memo_not_issued
    """
    scenario = setup_missed_trip_with_memo(
        contract_overrides={"client_name": "Void Guard"}
    )
    void_credit_memo(scenario["memo"]["id"], "first void")

    response = api.void_credit_memo(
        scenario["memo"]["id"], {"voided_reason": "second void"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_MEMO_NOT_ISSUED.value, 409)

    memo = validate_success(api.get_credit_memo(scenario["memo"]["id"], ADMIN))
    assert memo["status"] == "VOIDED"

    contract = validate_success(api.get_contract(scenario["contract"]["id"], ADMIN))
    assert contract["credit_balance_cents"] == 0, "the balance never goes negative"


# ─── Immediate consistency ────────────────────────────────────────────────────

def test_manual_goodwill_memo_moves_the_balance_immediately(api):
    """PRD §3.7: "A newly raised memo has `status` `ISSUED`, `applied_report_id`
    null and `voided_reason` null, recomputes the contract's `credit_balance_cents`,
    and increments the contract's `version` by one."
    PRD §3.7: "a memo without a trip is a `GOODWILL` gesture that belongs to no
    service period."

    Design: Corner/consistency_model/manual_credit_memo_moves_the_balance_within_the_same_request
    """
    contract = create_active_contract(client_name="Immediate Corp", site_type="CORPORATE")
    version_before = contract["version"]

    memo = validate_success(
        api.create_credit_memo(
            {"contract_id": contract["id"], "amount_cents": 1_000, "reason": "GOODWILL"},
            LIAISON,
        ),
        expected_status=201,
    )
    assert memo["status"] == "ISSUED"
    assert memo.get("trip_id") is None
    assert memo.get("applied_report_id") is None
    assert memo["reason"] == "GOODWILL"

    reread = validate_success(api.get_contract(contract["id"], ADMIN))
    assert reread["credit_balance_cents"] == 1_000
    assert reread["version"] == version_before + 1, (
        f"the contract's version moves by exactly one, from {version_before} to "
        f"{reread['version']}"
    )

    _, meta = validate_paginated(
        api.list_credit_memos(ADMIN, params={"contract_id": contract["id"], "status": "ISSUED"})
    )
    assert meta["total_count"] == 1
