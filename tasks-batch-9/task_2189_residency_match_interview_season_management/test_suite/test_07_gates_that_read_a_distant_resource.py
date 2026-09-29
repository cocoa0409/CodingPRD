"""Transitions whose preconditions live on resources the request never names.

Sending a rank list to committee reads the rubric cards of every ranked
application, and activating a contract reads every item of its credential packet.
"""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    ContractStatus,
    CredentialItemStatus,
    CredentialType,
    RankListStatus,
    ScoreCardStatus,
    assert_credential_counters,
    get_success_data,
    setup_rank_list_with_entry,
    setup_signed_contract,
    validate_error,
    validate_success,
)

STATE_LICENSE_REFERENCE = "LIC-778812"
BLS_REFERENCE = "BLS-4471"
DEA_REFERENCE = "DEA-BX9910"


def _two_mandatory_items_verified():
    """A signed contract whose licence and life-support items are verified."""
    builder = setup_signed_contract(quota_positions=1)
    builder.submit_credential(CredentialType.STATE_LICENSE, STATE_LICENSE_REFERENCE)
    builder.verify_credential(CredentialType.STATE_LICENSE)
    builder.submit_credential(CredentialType.BLS, BLS_REFERENCE)
    builder.verify_credential(CredentialType.BLS)
    return builder


def test_a_draft_rubric_card_two_entities_away_blocks_the_submission(api):
    """The ranked application carries one submitted card and one draft card.

    The request names only the list, but the gate reaches through the entry to
    the application and on to its cards.

    PRD 3.7: "Seven conditions must hold: the acting faculty member's `is_program_director` is true; that member's `program_id` equals the list's `program_id`; the owning program is in `RANKING`; `entry_count` is at least 1; `entry_count` is at or below `quota_positions` multiplied by 10; the set of `rank_position` values across the list's entries is exactly the whole numbers from 1 through `entry_count` with no gap and no repeat; and every ranked application carries at least 2 `ScoreCard` rows whose `status` is `SUBMITTED` or `LOCKED`."
    PRD 2.12: "On `POST /rank-lists/{id}/submit-to-committee`, every ranked application carries at least 2 `ScoreCard` rows whose `status` is `SUBMITTED` or `LOCKED`."

    Design: Difficulty/cross_entity_state_dependency/rank_list_submit_gated_by_scorecard_states_two_entities_away
    """
    builder = setup_rank_list_with_entry(submit_both=False)

    response = api.submit_rank_list_to_committee(
        builder.id("rank_list"), builder.director("pd")
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_EVALUATIONS)

    rank_list = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert rank_list["status"] == RankListStatus.DRAFT, (
        f"the refused list should still be DRAFT, got {rank_list['status']}"
    )
    assert rank_list["review_round"] == 0, (
        "a refused submission must not open a round, got "
        f"{rank_list['review_round']}"
    )


def test_submitting_the_second_card_unblocks_the_same_list(api):
    """Nothing about the list changes, yet the same request now succeeds.

    The second card leaving DRAFT is the only difference, which is exactly the
    distant state the gate was reading.

    PRD 3.7: "Two side effects follow: `RankList.review_round` increments by one, and `RankList.version` increments by one."
    PRD 3.7: "`review_round` is by definition the number of times the list has entered committee review, which is why it starts at 0 and is 1 during the first deliberation."

    Design: Difficulty/cross_entity_state_dependency/rank_list_submit_gated_by_scorecard_states_two_entities_away
    """
    builder = setup_rank_list_with_entry(submit_both=False)

    api.submit_score_card(builder.id("sc2"), builder.interviewer("f2"))

    submitted = validate_success(
        api.submit_rank_list_to_committee(builder.id("rank_list"), builder.director("pd"))
    )
    assert submitted["status"] == RankListStatus.COMMITTEE_REVIEW, (
        f"the list should now reach committee, got {submitted['status']}"
    )
    assert submitted["review_round"] == 1, (
        f"the first deliberation is round one, got {submitted['review_round']}"
    )

    for key, faculty_key in (("sc1", "f1"), ("sc2", "f2")):
        card = get_success_data(
            api.get_score_card(builder.id(key), builder.interviewer(faculty_key))
        )
        assert card["status"] == ScoreCardStatus.SUBMITTED, (
            f"both cards should be SUBMITTED, got {card['status']} for {key}"
        )


def test_each_verified_mandatory_item_advances_the_packet_counter(api):
    """Two of the three mandatory items are verified, so the counter reads two.

    The packet of an internal-medicine citizen holds three mandatory items, and
    each verification moves the counter by one.

    PRD 3.9: "A `STATE_LICENSE` item is always created with `is_mandatory` true."
    PRD 3.9: "Verifying drives `SUBMITTED → VERIFIED` with no preconditions beyond the state itself; it stamps `verified_at` with the current logical clock instant and increments `Contract.verified_credential_count` by one **only when that item's `is_mandatory` is true** — verifying a non-mandatory pathology `DEA` item advances no counter."

    Design: Difficulty/cross_entity_state_dependency/contract_activation_gated_by_every_mandatory_credential_item
    """
    builder = _two_mandatory_items_verified()

    contract = get_success_data(
        api.get_contract(builder.id("contract"), builder.coordinator)
    )
    assert_credential_counters(contract, expected_mandatory=3, expected_verified=2)
    assert contract["status"] == ContractStatus.SIGNED


def test_activation_is_refused_while_one_mandatory_item_is_unverified(api):
    """The third mandatory item is still pending, so the packet is incomplete.

    The contract stays signed and its counters are untouched by the refusal.

    PRD 3.9: "**Activation** drives `SIGNED → ACTIVE` and is refused until the packet is complete: `Contract.verified_credential_count` must equal `Contract.mandatory_credential_count`, otherwise `ERR_CREDENTIALS_INCOMPLETE`."
    PRD 2.12: "**Priority 11 — complete onboarding packet.** On `POST /contracts/{id}/activate`, the contract's `verified_credential_count` equals its `mandatory_credential_count`."

    Design: Difficulty/cross_entity_state_dependency/contract_activation_gated_by_every_mandatory_credential_item
    """
    builder = _two_mandatory_items_verified()

    response = api.activate_contract(builder.id("contract"), builder.coordinator)
    validate_error(response, ApiErrorId.ERR_CREDENTIALS_INCOMPLETE)

    contract = get_success_data(
        api.get_contract(builder.id("contract"), builder.coordinator)
    )
    assert contract["status"] == ContractStatus.SIGNED, (
        f"the refused contract should still be SIGNED, got {contract['status']}"
    )
    assert_credential_counters(contract, expected_mandatory=3, expected_verified=2)


def test_verifying_the_last_mandatory_item_lifts_the_activation_gate(api):
    """The final item is submitted and verified, and the same request succeeds.

    The counters meet, the contract activates, and the last item carries its own
    verification timestamp.

    PRD 3.9: "That drives `PENDING → SUBMITTED`, and the same operation drives `REJECTED → SUBMITTED` on a second attempt, overwriting the earlier `reference_number`; both edges require that the acting applicant is the `Applicant` behind the owning contract's `MatchResult` application and that the owning contract's `status` is `ISSUED` or `SIGNED`."
    PRD 3.9: "The transition has no side effects of its own."

    Design: Difficulty/cross_entity_state_dependency/contract_activation_gated_by_every_mandatory_credential_item
    """
    builder = _two_mandatory_items_verified()

    builder.submit_credential(CredentialType.DEA, DEA_REFERENCE)
    builder.verify_credential(CredentialType.DEA)

    activated = validate_success(
        api.activate_contract(builder.id("contract"), builder.coordinator)
    )
    assert activated["status"] == ContractStatus.ACTIVE, (
        f"a complete packet should activate the contract, got {activated['status']}"
    )
    assert_credential_counters(activated, expected_mandatory=3, expected_verified=3)

    dea_item = get_success_data(
        api.get_credential_item(
            builder.id(f"cred_{CredentialType.DEA}"), builder.coordinator
        )
    )
    assert dea_item["status"] == CredentialItemStatus.VERIFIED, (
        f"the last item should be VERIFIED, got {dea_item['status']}"
    )
    assert dea_item["verified_at"] is not None, "verification stamps verified_at"
    assert dea_item["reference_number"] == DEA_REFERENCE
