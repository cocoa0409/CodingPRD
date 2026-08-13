"""Deposit accounts, walkthrough reports, and the settlement waterfall."""
from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    assert_deposit_account,
    assert_deposit_money_partition,
    create_deposit_account_payload,
    create_walkthrough_report_payload,
    get_success_data,
    make_owner_rep_headers,
    setup_basic_scenario,
    setup_funded_deposit,
    setup_production_with_executed_agreement,
    setup_signed_pre_walkthrough,
    validate_error,
    validate_paginated,
    validate_success,
)


def _get_report(api, production_id, report_id, kind=None):
    params = {"kind": kind} if kind else None
    rows, _ = validate_paginated(api.list_walkthrough_reports(production_id, LM, params=params))
    matches = [r for r in rows if r["id"] == report_id]
    assert matches, f"WalkthroughReport {report_id} not found in list"
    return matches[0]


def _get_account(api, production_id, account_id):
    return get_success_data(api.get_deposit_account(production_id, account_id, LM))


def _setup_settling_scenario(api, damage_claim_cents=100_000):
    """EXECUTED agreement (rate 150000 x 3 days -> required 225000), deposit funded
    at 225000, PRE signed, POST report created; returns the scenario dict."""
    scenario = setup_production_with_executed_agreement()
    account = setup_funded_deposit(scenario)
    assert account["status"] == "FUNDED" and account["required_amount_cents"] == 225_000
    scenario["deposit_account"] = account
    scenario["pre_walkthrough"] = setup_signed_pre_walkthrough(scenario)
    production_id = scenario["production"]["id"]
    post = get_success_data(api.create_walkthrough_report(
        production_id,
        create_walkthrough_report_payload(
            scenario["location"]["id"], "POST",
            damage_item_count=2, damage_claim_cents=damage_claim_cents,
        ),
        LM,
    ))
    scenario["post_walkthrough"] = post
    return scenario


# ---------------------------------------------------------------------------
# Difficulty: deposit required amount with pinned rounding order
# ---------------------------------------------------------------------------

def test_deposit_required_pinned_rounding_order_odd_rate(api):
    """PRD §3.7: "specifically, multiply `agreed_day_rate_cents` by the shoot-day
    count, multiply that product by 50, and divide by 100 with a single floor
    applied at that final division — the rounding order is pinned, and reordering
    it changes the answer whenever the rate is odd."
    PRD §3.7: "A rate of 99999 cents over 3 days illustrates the point: the pinned
    order yields 149998 cents (299997 times 50, divided by 100 and floored),
    whereas flooring the half-rate first would yield 149997."
    PRD §3.7: "The account is born `OPEN` with `held_amount_cents`,
    `claimed_amount_cents`, and `released_amount_cents` all at 0."

    Design: Difficulty/combinatorial_formula/deposit_required_pinned_rounding_order_odd_rate
    """
    scenario = setup_production_with_executed_agreement(
        location_overrides={"deposit_floor_cents": 100_000},
        rate=99_999,
    )
    production_id = scenario["production"]["id"]
    account = get_success_data(api.create_deposit_account(
        production_id, create_deposit_account_payload(scenario["location"]["id"]), LM,
    ))
    assert_deposit_account(account)
    assert account["required_amount_cents"] == 149_998, (
        f"Pinned order floor(99999*3*50/100) = 149998, got {account['required_amount_cents']}"
    )
    assert account["required_amount_cents"] != 149_997, (
        "Counterfactual floor(99999*50/100)*3 = 149997 must NOT be produced"
    )
    assert account["status"] == "OPEN"
    assert account["held_amount_cents"] == 0
    assert account["claimed_amount_cents"] == 0
    assert account["released_amount_cents"] == 0


def test_deposit_required_takes_max_with_location_floor(api):
    """PRD §3.7: "The required amount is the larger of the location's
    `deposit_floor_cents` and this risk amount"

    Design: Difficulty/combinatorial_formula/deposit_required_pinned_rounding_order_odd_rate
    """
    # Same 149998 risk amount as the odd-rate case, but the floor is 200000.
    scenario = setup_production_with_executed_agreement(
        location_overrides={"deposit_floor_cents": 200_000},
        rate=99_999,
    )
    production_id = scenario["production"]["id"]
    account = get_success_data(api.create_deposit_account(
        production_id, create_deposit_account_payload(scenario["location"]["id"]), LM,
    ))
    assert account["required_amount_cents"] == 200_000, (
        f"max(floor 200000, risk 149998) must be 200000, got {account['required_amount_cents']}"
    )
    assert account["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Deposit account lifecycle: uniqueness and funding threshold
# ---------------------------------------------------------------------------

def test_deposit_account_second_account_same_pair_rejected(api):
    """PRD §3.7: "there is exactly one account per production-location pair, so
    opening a second for the same pair is refused."
    PRD §2.7: "finally payload well-formedness — required fields present and
    well-typed, enum values valid, dates parseable — as `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/deposit_account_second_account_same_pair_rejected
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    first = get_success_data(api.create_deposit_account(
        production_id, create_deposit_account_payload(scenario["location"]["id"]), LM,
    ))
    assert first["status"] == "OPEN"

    resp = api.create_deposit_account(
        production_id, create_deposit_account_payload(scenario["location"]["id"]), LM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_deposit_accounts(production_id, LM))
    assert meta["total_count"] == 1


def test_deposit_reaching_exact_required_transitions_funded(api):
    """PRD §3.7: "The manager pays into the account with an `amount_cents` that is
    added to `held_amount_cents`; the moment the held amount reaches or exceeds
    the required amount, the account moves automatically to `FUNDED`."

    Design: Corner/state_machines/deposit_reaching_exact_required_transitions_funded
    """
    scenario = setup_production_with_executed_agreement(
        location_overrides={"deposit_floor_cents": 100_000},
        rate=99_999,
    )
    production_id = scenario["production"]["id"]
    account = get_success_data(api.create_deposit_account(
        production_id, create_deposit_account_payload(scenario["location"]["id"]), LM,
    ))
    assert account["required_amount_cents"] == 149_998

    # 149997 < 149998: still OPEN.
    account = get_success_data(
        api.deposit_into_account(production_id, account["id"], 149_997, LM)
    )
    assert account["held_amount_cents"] == 149_997
    assert account["status"] == "OPEN"

    # One more cent reaches the required amount exactly: FUNDED.
    account = get_success_data(
        api.deposit_into_account(production_id, account["id"], 1, LM)
    )
    assert account["held_amount_cents"] == 149_998
    assert account["status"] == "FUNDED"


# ---------------------------------------------------------------------------
# Walkthrough signing gates
# ---------------------------------------------------------------------------

def test_walkthrough_sign_without_both_signatures_rejected(api):
    """PRD §3.7: "A draft report becomes `SIGNED` only when both signature flags
    are true, otherwise the signing is rejected with `ERR_SIGNATURE_MISSING`."

    Design: Corner/state_machines/walkthrough_sign_without_both_signatures_rejected
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    report = get_success_data(api.create_walkthrough_report(
        production_id,
        create_walkthrough_report_payload(
            scenario["location"]["id"], "PRE",
            signed_by_owner=True, signed_by_manager=False,
        ),
        LM,
    ))

    resp = api.sign_walkthrough_report(production_id, report["id"], LM)
    validate_error(resp, ApiErrorId.ERR_SIGNATURE_MISSING)
    assert _get_report(api, production_id, report["id"])["status"] == "DRAFT"


def test_second_signed_pre_walkthrough_rejected(api):
    """PRD §3.7: "For a `PRE` report there is an additional uniqueness rule: no
    other `SIGNED` `PRE` report may already exist for the location, or the signing
    fails with `ERR_DUPLICATE_PRE_WALKTHROUGH`."

    Design: Corner/state_machines/second_signed_pre_walkthrough_rejected
    """
    scenario = setup_basic_scenario()
    production_id = scenario["production"]["id"]
    first = setup_signed_pre_walkthrough(scenario)
    assert first["status"] == "SIGNED"

    second = get_success_data(api.create_walkthrough_report(
        production_id,
        create_walkthrough_report_payload(scenario["location"]["id"], "PRE"),
        LM,
    ))
    resp = api.sign_walkthrough_report(production_id, second["id"], LM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PRE_WALKTHROUGH)
    assert _get_report(api, production_id, second["id"])["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty: POST sign -> SETTLING -> settle -> CLOSED -> report FINAL
# ---------------------------------------------------------------------------

def test_post_sign_settles_account_and_close_finalizes_report(api):
    """PRD §3.7: "When a POST report is signed, the deposit account for the
    production and location moves to `SETTLING`."
    PRD §3.7: "The account closes to `CLOSED`, the POST walkthrough report moves
    automatically to `FINAL`"

    Design: Difficulty/transitive_cascade/post_walkthrough_sign_depth2_deposit_settling_then_close_finalizes_report
    """
    scenario = _setup_settling_scenario(api, damage_claim_cents=100_000)
    production_id = scenario["production"]["id"]
    account = scenario["deposit_account"]
    post = scenario["post_walkthrough"]

    signed_post = validate_success(api.sign_walkthrough_report(production_id, post["id"], LM))
    assert signed_post["status"] == "SIGNED"
    settling = _get_account(api, production_id, account["id"])
    assert settling["status"] == "SETTLING", "POST sign must push the account to SETTLING"

    closed = validate_success(
        api.settle_deposit_account(production_id, account["id"], 100_000, FO)
    )
    assert closed["status"] == "CLOSED"
    assert closed["claimed_amount_cents"] == 100_000
    assert closed["released_amount_cents"] == 125_000

    # The report is finalized by the account close, not by the sign call.
    assert _get_report(api, production_id, post["id"], kind="POST")["status"] == "FINAL"


def test_dispute_then_resign_then_settle_also_finalizes_and_finalizes_pre(api):
    """PRD §3.7: "The owner representative may instead dispute a POST report —
    only POST reports are disputable — moving it to `DISPUTED`, which likewise
    pushes the deposit account to `SETTLING`; a disputed report can be re-signed
    by the manager once both signature flags are again true, returning it to
    `SIGNED`."
    PRD §3.7: "the location's `PRE` report — if not already final — moves to
    `FINAL` when the POST report becomes signed."

    Design: Difficulty/transitive_cascade/post_walkthrough_sign_depth2_deposit_settling_then_close_finalizes_report
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    owner = scenario["owner"]
    account = setup_funded_deposit(scenario)
    pre = setup_signed_pre_walkthrough(scenario)
    post = get_success_data(api.create_walkthrough_report(
        production_id,
        create_walkthrough_report_payload(
            scenario["location"]["id"], "POST",
            damage_item_count=1, damage_claim_cents=50_000,
        ),
        LM,
    ))

    disputed = validate_success(api.dispute_walkthrough_report(
        production_id, post["id"], make_owner_rep_headers(owner["id"]),
    ))
    assert disputed["status"] == "DISPUTED"
    assert _get_account(api, production_id, account["id"])["status"] == "SETTLING", (
        "The dispute likewise pushes the account to SETTLING"
    )

    re_signed = validate_success(api.sign_walkthrough_report(production_id, post["id"], LM))
    assert re_signed["status"] == "SIGNED"
    # PRE report becomes FINAL when the POST report becomes signed.
    assert _get_report(api, production_id, pre["id"], kind="PRE")["status"] == "FINAL"

    closed = validate_success(api.settle_deposit_account(production_id, account["id"], 0, FO))
    assert closed["status"] == "CLOSED"
    assert _get_report(api, production_id, post["id"], kind="POST")["status"] == "FINAL"


# ---------------------------------------------------------------------------
# Difficulty: settle money-partition invariant
# ---------------------------------------------------------------------------

def test_settle_partitions_held_into_claimed_and_released_exactly(api):
    """PRD §3.7: "On a passing settle, claims are paid first and the remainder
    released: `claimed_amount_cents` increases by the award, and
    `released_amount_cents` increases by whatever of the held balance remains
    after the award, so that afterward the held amount equals the claimed amount
    plus the released amount exactly."

    Design: Difficulty/compensating_invariant/deposit_settle_money_partition_invariant
    """
    scenario = _setup_settling_scenario(api, damage_claim_cents=100_000)
    production_id = scenario["production"]["id"]
    account = scenario["deposit_account"]
    get_success_data(api.sign_walkthrough_report(production_id, scenario["post_walkthrough"]["id"], LM))

    closed = validate_success(
        api.settle_deposit_account(production_id, account["id"], 100_000, FO)
    )
    assert closed["held_amount_cents"] == 225_000, "Settle must not change held"
    assert closed["claimed_amount_cents"] == 100_000
    assert closed["released_amount_cents"] == 125_000
    assert closed["status"] == "CLOSED"
    assert_deposit_money_partition(closed)


def test_settle_with_zero_award_releases_everything(api):
    """PRD §3.7: "On a passing settle, claims are paid first and the remainder
    released: `claimed_amount_cents` increases by the award, and
    `released_amount_cents` increases by whatever of the held balance remains
    after the award, so that afterward the held amount equals the claimed amount
    plus the released amount exactly."

    Design: Difficulty/compensating_invariant/deposit_settle_money_partition_invariant
    """
    scenario = _setup_settling_scenario(api, damage_claim_cents=0)
    production_id = scenario["production"]["id"]
    account = scenario["deposit_account"]
    get_success_data(api.sign_walkthrough_report(production_id, scenario["post_walkthrough"]["id"], LM))

    closed = validate_success(api.settle_deposit_account(production_id, account["id"], 0, FO))
    assert closed["held_amount_cents"] == 225_000
    assert closed["claimed_amount_cents"] == 0
    assert closed["released_amount_cents"] == 225_000
    assert closed["status"] == "CLOSED"
    assert_deposit_money_partition(closed)


# ---------------------------------------------------------------------------
# Settlement rejections
# ---------------------------------------------------------------------------

def test_deposit_settle_while_post_report_disputed_rejected(api):
    """PRD §3.7: "Settlement is blocked while the location's POST report stands
    `DISPUTED` (the attempt fails with `ERR_WALKTHROUGH_DISPUTED`)"
    PRD §3.7: "The owner representative may instead dispute a POST report — only
    POST reports are disputable — moving it to `DISPUTED`, which likewise pushes
    the deposit account to `SETTLING`"

    Design: Corner/state_machines/deposit_settle_while_post_report_disputed_rejected
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    account = setup_funded_deposit(scenario)
    post = get_success_data(api.create_walkthrough_report(
        production_id,
        create_walkthrough_report_payload(
            scenario["location"]["id"], "POST",
            damage_item_count=2, damage_claim_cents=100_000,
            signed_by_owner=False, signed_by_manager=True,
        ),
        LM,
    ))
    disputed = validate_success(api.dispute_walkthrough_report(
        production_id, post["id"], make_owner_rep_headers(scenario["owner"]["id"]),
    ))
    assert disputed["status"] == "DISPUTED"
    assert _get_account(api, production_id, account["id"])["status"] == "SETTLING"

    resp = api.settle_deposit_account(production_id, account["id"], 100_000, FO)
    validate_error(resp, ApiErrorId.ERR_WALKTHROUGH_DISPUTED)
    current = _get_account(api, production_id, account["id"])
    assert current["status"] == "SETTLING"
    assert current["claimed_amount_cents"] == 0
    assert current["released_amount_cents"] == 0


def test_settle_award_above_unreleased_balance_rejected(api):
    """PRD §3.7: "an award larger than the account's un-released balance —
    `held_amount_cents` minus `released_amount_cents` — is rejected with
    `ERR_CLAIM_EXCEEDS_DEPOSIT`."

    Design: Corner/state_machines/settle_award_above_unreleased_balance_rejected
    """
    scenario = _setup_settling_scenario(api, damage_claim_cents=300_000)
    production_id = scenario["production"]["id"]
    account = scenario["deposit_account"]
    get_success_data(api.sign_walkthrough_report(production_id, scenario["post_walkthrough"]["id"], LM))
    assert _get_account(api, production_id, account["id"])["status"] == "SETTLING"

    resp = api.settle_deposit_account(production_id, account["id"], 300_000, FO)
    validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_DEPOSIT)
    current = _get_account(api, production_id, account["id"])
    assert current["status"] == "SETTLING"
    assert current["held_amount_cents"] == 225_000
