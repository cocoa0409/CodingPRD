"""Paying the artist: the two independent review tracks, the compensating void,
and which linkage rule speaks first when a voucher is opened."""
from test_helpers import (
    ApiErrorId,
    FISCAL_OFFICER_USER_ID,
    OBSERVER_USER_ID,
    PROGRAM_DIRECTOR_USER_ID,
    TEST_USERS,
    api_client,
    attach_observation_rubric,
    create_delivered_session,
    create_payment_voucher_payload,
    create_void_payload,
    make_fiscal_officer_headers,
    open_voucher,
    read_residency,
    read_session,
    review_voucher_track,
    set_clock_to_default,
    setup_active_residency,
    setup_two_delivered_evaluated_sessions,
    submit_voucher,
    validate_error,
    validate_success,
)

RC = TEST_USERS["roster_coordinator_headers"]


def _submitted_voucher_over_two_deliveries() -> dict:
    """Two evaluated deliveries claimed by a submitted voucher of 31454 cents."""
    set_clock_to_default()
    scenario = setup_two_delivered_evaluated_sessions()
    voucher = open_voucher(
        scenario["artist"]["id"],
        scenario["residency"]["id"],
        [scenario["session_one"]["id"], scenario["session_two"]["id"]],
        period_start="2026-09-01",
        period_end="2026-09-30",
    )
    scenario["voucher"] = submit_voucher(voucher["id"], scenario["artist"]["id"])
    return scenario


# ==========================================================================
# The fork: two review tracks that close one at a time
# ==========================================================================
def test_passing_only_the_fiscal_track_leaves_the_voucher_submitted(api):
    """PRD §3.8: "Alongside `status`, two **independent review axes** run in
    parallel once the voucher is submitted: `fiscal_review_status` and
    `program_review_status`, each of which reads `PENDING`, `PASSED`, or `FAILED`,
    with `fiscal_reviewed_by` and `program_reviewed_by` recording who closed
    each."
    PRD §3.8: "A `PASS` that closes only the first of the two tracks leaves the
    voucher in `SUBMITTED`: the addressed track becomes `PASSED`, its reviewer
    field records the acting operator, and the voucher's `version` increments."
    PRD §3.8: "Nothing moves on the money ledger yet."

    Design: Difficulty/non_linear_state_machine/voucher_fork_join_program_fail_branch_and_resubmit_cycle
    """
    scenario = _submitted_voucher_over_two_deliveries()
    voucher = scenario["voucher"]
    assert voucher["status"] == "SUBMITTED"
    assert voucher["total_cents"] == 31454

    after_fiscal = review_voucher_track(
        voucher["id"],
        "FISCAL",
        "PASS",
        reviewer_user_id=FISCAL_OFFICER_USER_ID,
        expected_payment_voucher_version=voucher["version"],
    )
    assert after_fiscal["status"] == "SUBMITTED", (
        f"one closed track is not the join, got {after_fiscal['status']}"
    )
    assert after_fiscal["fiscal_review_status"] == "PASSED"
    assert after_fiscal["program_review_status"] == "PENDING"
    assert after_fiscal["fiscal_reviewed_by"] == FISCAL_OFFICER_USER_ID

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 31454
    assert residency["disbursed_cents"] == 0


def test_program_failure_rejects_the_voucher_and_a_resubmission_resets_both_tracks(
    api,
):
    """PRD §3.8: "A `FAIL` on either track sends the voucher to `REJECTED`, and
    its side effects deliberately differ from the pass branch."
    PRD §3.8: "The addressed track becomes `FAILED` with its reviewer field
    recorded, while the other track keeps whatever value it already had."
    PRD §3.8: "Crucially, the encumbrances are **not** released: the work was
    still delivered and is still owed, so the money stays committed."
    PRD §3.8: "Resubmission resets both tracks to `PENDING` **and** clears both
    `fiscal_reviewed_by` and `program_reviewed_by` back to null, and re-points
    every claimed session's `payment_voucher_id` at this voucher."

    Design: Difficulty/non_linear_state_machine/voucher_fork_join_program_fail_branch_and_resubmit_cycle
    """
    scenario = _submitted_voucher_over_two_deliveries()
    voucher_id = scenario["voucher"]["id"]
    after_fiscal = review_voucher_track(
        voucher_id,
        "FISCAL",
        "PASS",
        reviewer_user_id=FISCAL_OFFICER_USER_ID,
        expected_payment_voucher_version=scenario["voucher"]["version"],
    )

    after_program = review_voucher_track(
        voucher_id,
        "PROGRAM",
        "FAIL",
        reviewer_user_id=PROGRAM_DIRECTOR_USER_ID,
        expected_payment_voucher_version=after_fiscal["version"],
    )
    assert after_program["status"] == "REJECTED"
    assert after_program["fiscal_review_status"] == "PASSED", (
        "the failed track must not disturb the other one, got "
        f"{after_program['fiscal_review_status']}"
    )
    assert after_program["program_review_status"] == "FAILED"

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 31454, (
        f"a rejection releases no money, got {residency['encumbered_cents']}"
    )
    assert residency["disbursed_cents"] == 0

    resubmitted = submit_voucher(voucher_id, scenario["artist"]["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["fiscal_review_status"] == "PENDING", (
        "resubmission reopens the track that had already passed, got "
        f"{resubmitted['fiscal_review_status']}"
    )
    assert resubmitted["program_review_status"] == "PENDING"
    assert resubmitted["fiscal_reviewed_by"] is None
    assert resubmitted["total_cents"] == 31454


# ==========================================================================
# The compensating void
# ==========================================================================
def test_the_join_moves_the_total_from_encumbered_to_disbursed(api):
    """PRD §3.8: "When a `PASS` closes the **second** track, so that both
    `fiscal_review_status` and `program_review_status` read `PASSED`, the join
    fires automatically and the voucher becomes `APPROVED`."
    PRD §3.8: "Approval moves money: the residency's `disbursed_cents` gains
    `total_cents`, its `encumbered_cents` loses the sum of the held amounts of
    the claimed sessions, each of those sessions has its held amount zeroed, and
    `available_cents` is recomputed — leaving the money identity of §2.12
    intact."
    PRD §2.12: "Available plus encumbered plus disbursed always equals
    `budget_cents`."

    Design: Difficulty/compensating_invariant/voucher_void_restores_money_invariant_exactly
    """
    scenario = _submitted_voucher_over_two_deliveries()
    voucher_id = scenario["voucher"]["id"]
    before = read_residency(scenario["residency"]["id"])
    assert before["encumbered_cents"] == 31454
    assert before["disbursed_cents"] == 0
    assert before["available_cents"] == 168546

    after_fiscal = review_voucher_track(
        voucher_id,
        "FISCAL",
        "PASS",
        reviewer_user_id=FISCAL_OFFICER_USER_ID,
        expected_payment_voucher_version=scenario["voucher"]["version"],
    )
    approved = review_voucher_track(
        voucher_id,
        "PROGRAM",
        "PASS",
        reviewer_user_id=PROGRAM_DIRECTOR_USER_ID,
        expected_payment_voucher_version=after_fiscal["version"],
    )
    assert approved["status"] == "APPROVED", (
        f"the second pass fires the join, got {approved['status']}"
    )

    mid = read_residency(scenario["residency"]["id"])
    assert mid["encumbered_cents"] == 0
    assert mid["disbursed_cents"] == 31454
    assert mid["available_cents"] == 168546
    assert (
        mid["available_cents"] + mid["encumbered_cents"] + mid["disbursed_cents"]
        == 200000
    )


def test_voiding_an_approved_voucher_restores_the_money_ledger_exactly(api):
    """PRD §3.8: "`APPROVED → VOIDED` requires the residency not to be `CLOSED`,
    or the void is refused with `ERR_INVALID_STATE_TRANSITION`, and it is a true
    compensating action: the residency's `disbursed_cents` loses `total_cents`,
    its `encumbered_cents` gains exactly that same `total_cents`, each claimed
    session's held amount is restored to its `payable_cents`, and
    `available_cents` is recomputed, so that the money identity holds with
    precisely the values it had before approval."
    PRD §3.8: "Each claimed session's `payment_voucher_id` is cleared to null."
    PRD §2.12: "Neither leg ever changes `budget_cents`."

    Design: Difficulty/compensating_invariant/voucher_void_restores_money_invariant_exactly
    """
    scenario = _submitted_voucher_over_two_deliveries()
    voucher_id = scenario["voucher"]["id"]
    after_fiscal = review_voucher_track(
        voucher_id,
        "FISCAL",
        "PASS",
        reviewer_user_id=FISCAL_OFFICER_USER_ID,
        expected_payment_voucher_version=scenario["voucher"]["version"],
    )
    review_voucher_track(
        voucher_id,
        "PROGRAM",
        "PASS",
        reviewer_user_id=PROGRAM_DIRECTOR_USER_ID,
        expected_payment_voucher_version=after_fiscal["version"],
    )

    voided = validate_success(
        api_client.void_payment_voucher(
            voucher_id,
            create_void_payload("duplicate submission discovered in the pay run"),
            make_fiscal_officer_headers(FISCAL_OFFICER_USER_ID),
        )
    )
    assert voided["status"] == "VOIDED"

    post = read_residency(scenario["residency"]["id"])
    assert post["encumbered_cents"] == 31454, (
        f"the void must recommit the money, got {post['encumbered_cents']}"
    )
    assert post["disbursed_cents"] == 0
    assert post["available_cents"] == 168546
    assert (
        post["available_cents"] + post["encumbered_cents"] + post["disbursed_cents"]
        == 200000
    )
    assert post["budget_cents"] == 200000
    assert post["earned_to_date_cents"] == 31454

    one = read_session(scenario["session_one"]["id"])
    two = read_session(scenario["session_two"]["id"])
    assert one["encumbered_cents"] == 17178, (
        f"each session's hold returns to its payable, got {one['encumbered_cents']}"
    )
    assert two["encumbered_cents"] == 14276
    assert one["payment_voucher_id"] is None
    assert two["payment_voucher_id"] is None


# ==========================================================================
# Which linkage rule speaks first when the voucher is opened
# ==========================================================================
def _one_unevaluated_delivery() -> dict:
    """A single delivered session of 2026-09-15 carrying no evaluation at all."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = create_delivered_session(
        scenario,
        session_date="2026-09-15",
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=20.5,
        materials_spend_cents=3000,
    )
    return scenario


def test_missing_evaluation_outranks_the_pay_period_mismatch(api):
    """PRD §2.9: "Checks are therefore evaluated in a fixed global order, and the
    **first** violated check decides the response."
    PRD §2.9: "14. Evaluation and voucher-claim linkage — `ERR_EVALUATION_MISSING`
    or `ERR_SESSION_ALREADY_VOUCHERED`."
    PRD §2.9: "22. Term and period containment —
    `ERR_SESSION_OUTSIDE_RESIDENCY_TERM` or `ERR_VOUCHER_PERIOD_MISMATCH`."
    PRD §3.8: "Creation already applies three of the linkage rules that
    submission will re-apply: a session already claimed by a different voucher is
    refused with `ERR_SESSION_ALREADY_VOUCHERED`; a claimed session lacking an
    `OBSERVATION_RUBRIC` evaluation with all three rubric scores is refused with
    `ERR_EVALUATION_MISSING`; and a claimed session whose `session_date` falls
    outside the closed period from `period_start` to `period_end` is refused with
    `ERR_VOUCHER_PERIOD_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/business_referential_precedes_business_temporal_on_voucher_open
    """
    scenario = _one_unevaluated_delivery()
    assert scenario["session"]["payable_cents"] == 17178

    payload = create_payment_voucher_payload(
        scenario["artist"]["id"],
        scenario["residency"]["id"],
        [scenario["session"]["id"]],
        period_start="2026-10-01",
        period_end="2026-10-31",
    )
    res = api_client.create_payment_voucher(payload, RC)
    validate_error(res, ApiErrorId.ERR_EVALUATION_MISSING.value, expected_status=409)

    session = read_session(scenario["session"]["id"])
    assert session["payment_voucher_id"] is None
    assert session["status"] == "DELIVERED"
    assert read_residency(scenario["residency"]["id"])["encumbered_cents"] == 17178


def test_the_masked_period_mismatch_surfaces_once_the_rubric_is_on_file(api):
    """PRD §2.9: "A single request can violate many rules at once, and the
    response must be deterministic."
    PRD §2.9: "22. Term and period containment —
    `ERR_SESSION_OUTSIDE_RESIDENCY_TERM` or `ERR_VOUCHER_PERIOD_MISMATCH`."
    PRD §3.8: "It also fixes the pay period with a `period_start` and a
    `period_end` no earlier than the start, both inclusive."

    Design: Difficulty/priority_pair_validation_conflict/business_referential_precedes_business_temporal_on_voucher_open
    """
    scenario = _one_unevaluated_delivery()
    session_id = scenario["session"]["id"]
    payload = create_payment_voucher_payload(
        scenario["artist"]["id"],
        scenario["residency"]["id"],
        [session_id],
        period_start="2026-10-01",
        period_end="2026-10-31",
    )
    validate_error(
        api_client.create_payment_voucher(payload, RC),
        ApiErrorId.ERR_EVALUATION_MISSING.value,
        expected_status=409,
    )

    attach_observation_rubric(session_id, OBSERVER_USER_ID, 4, 3, 4)
    validate_error(
        api_client.create_payment_voucher(payload, RC),
        ApiErrorId.ERR_VOUCHER_PERIOD_MISMATCH.value,
        expected_status=422,
    )

    session = read_session(session_id)
    assert session["payment_voucher_id"] is None
    assert session["status"] == "DELIVERED"
