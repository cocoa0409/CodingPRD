"""Clearing the subordinate debt: junior lien demands and responses, the conserved
contribution ledger, and the mortgage-insurance claim."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_junior_lien,
    assert_junior_ledger_matches,
    create_case,
    create_junior_lien_payload,
    create_lien,
    lien_demand_payload,
    lien_response_payload,
    make_junior_lien_holder_headers,
    mi_decision_payload,
    set_clock,
    setup_case_with_lien,
    setup_case_with_mi_claim,
    validate_error,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
HOLDER = TEST_USERS["junior_lien_holder_headers"]
OTHER_HOLDER = TEST_USERS["other_lien_holder_headers"]
UNDERWRITER = TEST_USERS["mi_underwriter_headers"]


def test_second_lien_at_a_taken_position_is_a_duplicate(api):
    """PRD §3.7: "Recording positions are unique per case: a second lien entered at a
    position already taken on that case is refused with `ERR_DUPLICATE_RESOURCE`."
    PRD §3.7: "Creation raises the case's `junior_lien_count` by one, starts the lien at
    `IDENTIFIED` with `demand_cents` null and `approved_contribution_cents` at 0."

    Design: Corner/validations/duplicate_junior_lien_position_rejected
    """
    set_clock("2026-08-05T00:00:00Z")
    case = create_case()
    first = create_lien(case["id"])
    assert first["status"] == "IDENTIFIED"

    validate_error(
        api.create_junior_lien(
            case["id"],
            create_junior_lien_payload(
                lien_position=2, holder_name="Second Holder",
                holder_user_id="jlh-701", balance_cents=900_000,
            ),
            NEG,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE.value,
    )

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["junior_lien_count"] == 1
    liens = validate_success(api.list_case_junior_liens(case["id"], NEG), 200)
    assert len(liens) == 1
    assert liens[0]["id"] == first["id"]


def test_demand_above_the_lien_balance_is_refused(api):
    """PRD §3.7: "The demanded payoff, supplied as `demand_cents`, may not exceed the
    lien's outstanding `balance_cents` — nobody demands that a holder accept more than it
    is owed — and a demand above the balance is refused with
    `ERR_LIEN_CONTRIBUTION_EXCEEDS_CAP`."

    Design: Corner/validations/lien_demand_above_balance_rejected
    """
    case, lien = setup_case_with_lien(stage="IDENTIFIED")

    validate_error(
        api.send_lien_demand(lien["id"], lien_demand_payload(3_600_000), NEG),
        ApiErrorId.ERR_LIEN_CONTRIBUTION_EXCEEDS_CAP.value,
    )

    liens = validate_success(api.list_case_junior_liens(case["id"], NEG), 200)
    assert liens[0]["status"] == "IDENTIFIED"
    assert liens[0]["demand_cents"] is None

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["junior_contribution_total_cents"] == 0


def test_only_the_recorded_holder_may_answer_a_demand(api):
    """PRD §2.1: "The one opaque identifier that is compared to a stored value is the
    junior lien holder's: a `JuniorLienHolder` may act on a lien only when its
    `X-User-ID` equals the `holder_user_id` the negotiator recorded on that lien when the
    lien was entered."
    PRD §2.1: "When an ownership binding fails — a `BpoVendor` whose `X-User-ID` does not
    match the addressed valuation's `vendor_id`, or a `JuniorLienHolder` whose
    `X-User-ID` does not match the addressed lien's `holder_user_id` — the request is
    refused with `ERR_ACTOR_NOT_OWNER` and HTTP 403."

    Design: Corner/rbac/non_holder_cannot_respond_to_junior_lien
    """
    case, lien = setup_case_with_lien(stage="DEMAND_SENT")

    validate_error(
        api.respond_to_lien(
            lien["id"],
            lien_response_payload("APPROVE", contribution_cents=600_000),
            make_junior_lien_holder_headers("jlh-999"),
        ),
        ApiErrorId.ERR_ACTOR_NOT_OWNER.value,
    )

    liens = validate_success(api.list_case_junior_liens(case["id"], NEG), 200)
    assert liens[0]["status"] == "DEMAND_SENT"
    assert liens[0]["approved_contribution_cents"] == 0

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["junior_contribution_total_cents"] == 0


def test_withdrawing_an_approval_returns_the_ledger_to_zero(api):
    """PRD §3.7: "`WITHDRAW_APPROVAL`, available only from `APPROVED`, is the
    compensating action for an approval: it zeroes `approved_contribution_cents`, returns
    the lien to `NEGOTIATING`, and demotes the final-variant current sheets to `STALE`."
    PRD §3.7: "Because a withdrawal zeroes the contribution and drops the lien out of the
    `APPROVED` set, the ledger returns to exactly the total it carried before the
    approval it undoes — not to a value that merely resembles it."

    Design: Difficulty/compensating_invariant/junior_contribution_ledger_restored_by_withdraw_approval
    """
    case, lien = setup_case_with_lien(stage="APPROVED")
    before = validate_success(api.get_case(case["id"], NEG), 200)
    assert before["junior_contribution_total_cents"] == 600_000

    withdrawn = validate_success(
        api.respond_to_lien(lien["id"], lien_response_payload("WITHDRAW_APPROVAL"), HOLDER),
        200,
    )

    assert withdrawn["status"] == "NEGOTIATING"
    assert withdrawn["approved_contribution_cents"] == 0

    after = validate_success(api.get_case(case["id"], NEG), 200)
    assert after["junior_contribution_total_cents"] == 0, (
        "the ledger returns to exactly the total it held before the approval"
    )


def test_withdrawal_compensates_the_approval_but_not_the_demand(api):
    """PRD §3.7: "`junior_contribution_total_cents` is always the sum of
    `approved_contribution_cents` over the liens on that case whose status is `APPROVED`;
    liens in any other status contribute nothing."
    PRD §3.7: "`WITHDRAW_APPROVAL`, available only from `APPROVED`, is the compensating
    action for an approval: it zeroes `approved_contribution_cents`, returns the lien to
    `NEGOTIATING`, and demotes the final-variant current sheets to `STALE`."

    Design: Difficulty/compensating_invariant/junior_contribution_ledger_restored_by_withdraw_approval
    """
    case, lien = setup_case_with_lien(stage="APPROVED")

    validate_success(
        api.respond_to_lien(lien["id"], lien_response_payload("WITHDRAW_APPROVAL"), HOLDER),
        200,
    )

    liens = validate_success(api.list_case_junior_liens(case["id"], NEG), 200)
    stored = liens[0]
    assert stored["demand_cents"] == 900_000, "the demand is not compensated away"
    assert stored["balance_cents"] == 3_500_000
    assert_junior_lien(stored)

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["junior_lien_count"] == 1
    assert_junior_ledger_matches(case_after, liens)


def test_state_admissibility_pre_empts_the_contribution_cap(api):
    """PRD §2.6: "Many operations in this system can fail for several reasons at once.
    Which reason the caller is told about is not a matter of taste; it is a fixed ladder,
    and a request is refused by the **first** rung it fails."
    PRD §3.7: "An outcome that is not declared from the lien's present status is refused
    with `ERR_LIEN_NOT_ACTIONABLE`."

    Design: Difficulty/priority_pair_validation_conflict/lien_state_check_beats_contribution_cap_check
    """
    case, lien = setup_case_with_lien(stage="IDENTIFIED")

    # APPROVE is not declared from IDENTIFIED, and 4_200_000 also breaches the
    # 3_500_000 balance cap. The state rung sits above the fiscal rung.
    validate_error(
        api.respond_to_lien(
            lien["id"],
            lien_response_payload("APPROVE", contribution_cents=4_200_000),
            HOLDER,
        ),
        ApiErrorId.ERR_LIEN_NOT_ACTIONABLE.value,
    )

    liens = validate_success(api.list_case_junior_liens(case["id"], NEG), 200)
    assert liens[0]["status"] == "IDENTIFIED"
    assert liens[0]["approved_contribution_cents"] == 0

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["junior_contribution_total_cents"] == 0


def test_the_contribution_cap_fires_once_the_state_check_passes(api):
    """PRD §3.7: "`APPROVE`, available from either `DEMAND_SENT` or `NEGOTIATING`,
    carries a `contribution_cents` figure that likewise may not exceed the lien's
    `balance_cents`, on pain of `ERR_LIEN_CONTRIBUTION_EXCEEDS_CAP`; it writes that
    figure into `approved_contribution_cents`, moves the lien to `APPROVED`, and demotes
    every **final**-variant sheet on any offer of the case that was `CURRENT` to
    `STALE`."
    PRD §3.7: "An outcome that is not declared from the lien's present status is refused
    with `ERR_LIEN_NOT_ACTIONABLE`."

    Design: Difficulty/priority_pair_validation_conflict/lien_state_check_beats_contribution_cap_check
    """
    case, lien = setup_case_with_lien(stage="DEMAND_SENT")

    # Identical over-cap contribution, but APPROVE is declared from DEMAND_SENT, so
    # the state rung passes and the fiscal rung is the one that refuses.
    validate_error(
        api.respond_to_lien(
            lien["id"],
            lien_response_payload("APPROVE", contribution_cents=4_200_000),
            HOLDER,
        ),
        ApiErrorId.ERR_LIEN_CONTRIBUTION_EXCEEDS_CAP.value,
    )

    liens = validate_success(api.list_case_junior_liens(case["id"], NEG), 200)
    assert liens[0]["status"] == "DEMAND_SENT"
    assert liens[0]["approved_contribution_cents"] == 0

    case_after = validate_success(api.get_case(case["id"], NEG), 200)
    assert case_after["junior_contribution_total_cents"] == 0


def test_deciding_an_already_declined_mi_claim_is_refused(api):
    """PRD §3.7: "Only the `MiUnderwriter` decides it, and only while it is `PENDING`; a
    decision on an already-decided claim is refused with `ERR_MI_CLAIM_NOT_DECIDABLE`."
    PRD §3.7: "`DECLINE` moves the claim to the terminal `DECLINED` and forces
    `required_contribution_cents` back to 0."

    Design: Corner/state_machines/decide_declined_mi_claim_returns_mi_claim_not_decidable
    """
    case, claim = setup_case_with_mi_claim(outcome="DECLINE")
    assert claim["status"] == "DECLINED"

    validate_error(
        api.decide_mi_claim(
            claim["id"],
            mi_decision_payload(
                "APPROVE", required_contribution_cents=750_000, contribution_form="CASH"
            ),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_MI_CLAIM_NOT_DECIDABLE.value,
    )

    claims = validate_success(api.list_case_mi_claims(case["id"], NEG), 200)
    stored = claims[0]
    assert stored["status"] == "DECLINED"
    assert stored["required_contribution_cents"] == 0
    assert stored["contribution_form"] == "NONE"
