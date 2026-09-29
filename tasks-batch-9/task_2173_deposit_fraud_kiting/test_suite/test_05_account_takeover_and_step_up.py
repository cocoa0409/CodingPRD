"""Account-takeover indicators, the posture ladder, and step-up verification."""

from test_helpers import (
    ApiErrorId,
    create_active_account,
    make_account_holder_headers,
    open_case,
    read_account,
    read_case,
    record_access_review,
    validate_error,
    validate_success,
)


# ===========================================================================
# The two state dimensions advance independently
# ===========================================================================
def test_posture_moves_to_step_up_while_the_lifecycle_dimension_moves_separately(
    api, analyst_headers
):
    """PRD §3.1: "An account may perfectly well be `RESTRICTED` and `NORMAL`, or
    `ACTIVE` and `LOCKED`; no lifecycle transition ever touches the posture and no
    posture transition ever touches the lifecycle."
    PRD §3.5: "- Otherwise, an `ato_score` of at least 40 but below 75 sets the
    posture to `STEP_UP_REQUIRED`, which from `NORMAL` is the transition
    `NORMAL → STEP_UP_REQUIRED`."
    PRD §3.5: "`ato_score` is the sum of the weights of the distinct codes
    currently stored, capped at 100. `NEW_DEVICE` weighs 15, `GEO_VELOCITY` 25,
    `CREDENTIAL_STUFFING` 30, `PROFILE_CHANGE` 20, `DORMANT_REACTIVATION` 18, and
    `PAYEE_ADDED` 12."
    PRD §3.7: "Its `exposure_at_risk_cents` is computed at once from the primary
    account's `held_amount_cents`, and the primary account transitions
    `ACTIVE → RESTRICTED`."

    Design: Difficulty/non_linear_state_machine/deposit_account_lifecycle_and_posture_dimensions_advance_independently
    """
    scenario = create_active_account(
        legal_name="Sena Okonkwo", tin_last4="4417", kyc_tier="TIER_2", watchlist_hit=False
    )

    reviewed = record_access_review(scenario["account_id"], ["NEW_DEVICE", "GEO_VELOCITY"])
    assert reviewed["ato_score"] == 40, "15 + 25 is exactly the step-up threshold"
    assert reviewed["access_posture"] == "STEP_UP_REQUIRED"
    assert reviewed["lifecycle_status"] == "ACTIVE", (
        "A posture transition never touches the lifecycle dimension"
    )

    open_case(scenario["account_id"], "MULE")

    after_case = read_account(scenario["account_id"], analyst_headers)
    assert after_case["lifecycle_status"] == "RESTRICTED"
    assert after_case["access_posture"] == "STEP_UP_REQUIRED", (
        "A lifecycle transition never touches the posture dimension"
    )


def test_three_failed_challenges_lock_the_posture_and_leave_the_lifecycle_alone(
    api, analyst_headers
):
    """PRD §3.5: "An **incorrect** answer increments `step_up_failure_count` by 1
    first, and then looks at the result. If the incremented count reaches three,
    the account transitions `STEP_UP_REQUIRED → LOCKED`. If it is still below
    three, the posture stays `STEP_UP_REQUIRED` on a self-loop and only the counter
    has moved. Either way the account's `version` advances by 1."
    PRD §3.5: "The correct `challenge_answer` is the owning depositor's
    `tin_last4`."
    PRD §3.1: "An account may perfectly well be `RESTRICTED` and `NORMAL`, or
    `ACTIVE` and `LOCKED`; no lifecycle transition ever touches the posture and no
    posture transition ever touches the lifecycle."

    Design: Difficulty/non_linear_state_machine/deposit_account_lifecycle_and_posture_dimensions_advance_independently
    """
    scenario = create_active_account(
        legal_name="Sena Okonkwo", tin_last4="4417", kyc_tier="TIER_2", watchlist_hit=False
    )
    record_access_review(scenario["account_id"], ["NEW_DEVICE", "GEO_VELOCITY"])
    case = open_case(scenario["account_id"], "MULE")

    holder = make_account_holder_headers(scenario["customer_id"])
    postures = []
    for _ in range(3):
        answered = validate_success(
            api.submit_step_up_response(
                scenario["account_id"], {"challenge_answer": "0000"}, holder
            )
        )
        postures.append((answered["access_posture"], answered["step_up_failure_count"]))

    assert postures[0] == ("STEP_UP_REQUIRED", 1), "One failure is still below three"
    assert postures[1] == ("STEP_UP_REQUIRED", 2), "Two failures are still below three"
    assert postures[2] == ("LOCKED", 3), "The third failure reaches three and locks the account"

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["access_posture"] == "LOCKED"
    assert account["lifecycle_status"] == "RESTRICTED", (
        "The failed challenges never touch the lifecycle dimension"
    )
    assert account["step_up_failure_count"] == 3
    assert account["ato_score"] == 40, "A failed challenge never rescores the indicator set"

    assert read_case(case["id"], analyst_headers)["status"] == "OPENED", (
        "Posture movement leaves the fraud case exactly where it was"
    )


# ===========================================================================
# The indicator set is a distinct set
# ===========================================================================
def test_repeating_an_indicator_code_adds_no_weight(api, analyst_headers):
    """PRD §3.5: "The submitted codes are merged into the account's
    `ato_indicator_codes`, which is maintained as a distinct set stored sorted
    ascending by code string. Submitting a code that is already present adds no
    second entry and, crucially, adds no weight — the score is a function of the
    distinct set, not of how many times a code was reported."
    PRD §3.5: "`ato_score` is the sum of the weights of the distinct codes
    currently stored, capped at 100. `NEW_DEVICE` weighs 15, `GEO_VELOCITY` 25,
    `CREDENTIAL_STUFFING` 30, `PROFILE_CHANGE` 20, `DORMANT_REACTIVATION` 18, and
    `PAYEE_ADDED` 12."
    PRD §3.5: "- Otherwise the posture is left exactly as it was. The score ladder
    never de-escalates a posture on its own; only a successful step-up answer or a
    supervisor reset moves a posture down."

    Design: Corner/calculations/ato_score_counts_each_indicator_code_once_however_often_it_is_posted
    """
    scenario = create_active_account(
        legal_name="Duplicate Indicator Depositor", tin_last4="0021"
    )

    first = record_access_review(scenario["account_id"], ["NEW_DEVICE", "NEW_DEVICE"])
    assert first["ato_score"] == 15, "Two copies of NEW_DEVICE score once"

    second = record_access_review(scenario["account_id"], ["NEW_DEVICE"])
    assert second["ato_score"] == 15, "Re-reporting the same code adds no weight"
    assert second["access_posture"] == "NORMAL", "15 is well below the step-up threshold of 40"

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["ato_indicator_codes"] == ["NEW_DEVICE"], (
        f"The stored set holds one entry, got {account['ato_indicator_codes']}"
    )


# ===========================================================================
# The lock threshold and the posture gates that follow from it
# ===========================================================================
def test_score_at_the_lock_threshold_locks_the_account_and_blocks_deposits(
    api, ops_admin_headers, analyst_headers
):
    """PRD §3.5: "- Otherwise, an `ato_score` of 75 or more sets the posture to
    `LOCKED`. From `NORMAL` this is the transition `NORMAL → LOCKED`; from
    `STEP_UP_REQUIRED` it is `STEP_UP_REQUIRED → LOCKED`."
    PRD §3.5: "An account whose `access_posture` is `LOCKED` is refused with
    `ERR_ACCOUNT_ACCESS_LOCKED` (HTTP 409); only then, an account whose posture is
    neither `LOCKED` nor `STEP_UP_REQUIRED` is refused with
    `ERR_STEP_UP_NOT_REQUIRED` (HTTP 409). Because of that ordering a locked
    account always reports the locked code and never the not-required one."
    PRD §3.3: "Immediately after that, the account's `access_posture` must not be
    `LOCKED`; a deposit into a locked account is refused with
    `ERR_ACCOUNT_ACCESS_LOCKED` (HTTP 409)."

    Design: Corner/calculations/ato_score_at_the_lock_threshold_locks_the_account_and_blocks_deposits
    """
    scenario = create_active_account(legal_name="Lock Threshold Depositor", tin_last4="0022")
    holder = make_account_holder_headers(scenario["customer_id"])

    validate_error(
        api.submit_step_up_response(
            scenario["account_id"], {"challenge_answer": "0022"}, holder
        ),
        ApiErrorId.ERR_STEP_UP_NOT_REQUIRED.value,
    )

    locked = record_access_review(
        scenario["account_id"], ["CREDENTIAL_STUFFING", "GEO_VELOCITY", "PROFILE_CHANGE"]
    )
    assert locked["ato_score"] == 75, "30 + 25 + 20 is exactly the lock threshold"
    assert locked["access_posture"] == "LOCKED"

    validate_error(
        api.create_deposit_item(
            scenario["account_id"], {"item_type": "CHECK", "amount_cents": 30000},
            ops_admin_headers,
        ),
        ApiErrorId.ERR_ACCOUNT_ACCESS_LOCKED.value,
    )

    validate_error(
        api.submit_step_up_response(
            scenario["account_id"], {"challenge_answer": "0022"}, holder
        ),
        ApiErrorId.ERR_ACCOUNT_ACCESS_LOCKED.value,
    )

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["lifecycle_status"] == "ACTIVE", (
        "A locked posture never moves the lifecycle dimension"
    )
    assert account["ledger_balance_cents"] == 0


def test_supervisor_reset_then_a_correct_answer_clears_the_indicator_history(
    api, supervisor_headers, analyst_headers
):
    """PRD §3.5: "- A supervisor reset wins over everything. When `reset_posture`
    is true and the account is currently `LOCKED`, the posture becomes
    `STEP_UP_REQUIRED` and `step_up_failure_count` is reset to 0, regardless of
    what the recomputed `ato_score` says. This override is honoured only for
    `FraudSupervisor`; from a `FraudAnalyst` it has no effect. Any submitted
    `indicator_codes` are still merged and the score still rewritten."
    PRD §3.5: "A **correct** answer transitions `STEP_UP_REQUIRED → NORMAL`, sets
    `step_up_failure_count` back to 0, clears `ato_indicator_codes` to the empty
    array, and rewrites `ato_score` to 0 — the account starts its indicator history
    over."
    PRD §3.5: "The correct `challenge_answer` is the owning depositor's
    `tin_last4`."

    Design: Corner/calculations/supervisor_reset_then_correct_answer_clears_indicators_and_zeroes_the_score
    """
    scenario = create_active_account(legal_name="Reset Posture Depositor", tin_last4="0023")
    locked = record_access_review(
        scenario["account_id"], ["CREDENTIAL_STUFFING", "GEO_VELOCITY", "PROFILE_CHANGE"]
    )
    assert locked["access_posture"] == "LOCKED"

    reset = validate_success(
        api.record_access_review(
            scenario["account_id"], {"indicator_codes": [], "reset_posture": True},
            supervisor_headers,
        )
    )
    assert reset["access_posture"] == "STEP_UP_REQUIRED", "The supervisor reset wins over the score"
    assert reset["ato_score"] == 75, "The reset lifts the posture without rescoring the set"
    assert reset["step_up_failure_count"] == 0

    holder = make_account_holder_headers(scenario["customer_id"])
    passed = validate_success(
        api.submit_step_up_response(
            scenario["account_id"], {"challenge_answer": "0023"}, holder
        )
    )
    assert passed["access_posture"] == "NORMAL"
    assert passed["ato_score"] == 0

    account = read_account(scenario["account_id"], analyst_headers)
    assert account["ato_indicator_codes"] == []
    assert account["step_up_failure_count"] == 0
