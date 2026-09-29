"""Requests that break two rules at once, where only the higher rule may answer.

Each scenario is arranged so that a single call violates a pair of numbered
validation rules; the specification's ladder decides which error identifier comes
back, and the loser must not surface.
"""
from test_helpers import (
    ADMIN,
    BASKET_SPLIT,
    ApiErrorId,
    active_equipment,
    advance_clock,
    api_client,
    assert_fields,
    assert_instant,
    assert_no_rows,
    authorized_store,
    cmp_election_payload,
    file_reply,
    finalize_case,
    issue_charge_letter,
    issue_determination,
    open_case,
    ok,
    pos_transaction_payload,
    refresh_case,
    refresh_store,
    store_patch_payload,
    substantiated_ineligible_investigation,
    validate_error,
)


def _suspended_store_with_active_terminal():
    context = authorized_store()
    equipment = active_equipment(context.store)
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    file_reply(case["id"], context.owner)
    issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")
    advance_clock("2026-08-12T00:00:00Z")
    finalize_case(case["id"])
    return context, equipment, case


def _unaffordable_basket(context, equipment):
    """A basket needing 3,107c of other tender, offered none of it."""
    return api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=BASKET_SPLIT,
            snap_benefit_available_cents=1000,
            other_tender_offered_cents=0,
            household_ebt_card_last4="8821",
        ),
        context.clerk_h,
    )


def test_store_authorization_gate_answers_before_the_tender_feasibility_gate():
    """A sale on a suspended store with an impossible tender split is refused for
    the suspension, not for the shortfall.

    The specification's ladder puts the store eligibility and authorization gate
    at rule 10 and the point-of-sale tender feasibility gate at rule 19, and
    lower-numbered rules answer first. Returning ERR_SPLIT_TENDER_SHORTFALL would
    reveal that the tender arithmetic ran at all on a store that may not trade.

    Design: Difficulty/priority_pair_validation_conflict/pos_authorization_gate_priority_10_beats_tender_feasibility_priority_19
    """
    context, equipment, _case = _suspended_store_with_active_terminal()

    response = _unaffordable_basket(context, equipment)

    body = validate_error(response, ApiErrorId.ERR_STORE_NOT_AUTHORIZED.value, 403)
    assert body["error_id"] != ApiErrorId.ERR_SPLIT_TENDER_SHORTFALL.value


def test_authorization_refusal_writes_no_transaction_row_at_all():
    """The refused sale leaves the transaction collection empty, unlike a decline,
    which persists.

    The specification records declined baskets as rows in their terminal state,
    but a request refused by a validation rule is not a decline: nothing is
    written. The store meanwhile carries both halves of its finalized sanction.

    Design: Difficulty/priority_pair_validation_conflict/pos_authorization_gate_priority_10_beats_tender_feasibility_priority_19
    """
    context, equipment, _case = _suspended_store_with_active_terminal()

    _unaffordable_basket(context, equipment)

    assert_no_rows(
        api_client.list_pos_transactions(ADMIN, {"store_id": context.store_id})
    )
    assert_fields(
        refresh_store(context.store_id),
        {"authorization_status": "SUSPENDED", "sanction_status": "SANCTION_FINAL"},
        "suspended store",
    )


def _finalized_case_past_its_review_deadline():
    context = authorized_store()
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    file_reply(case["id"], context.owner)
    issue_determination(case["id"], "TEMPORARY_DISQUALIFICATION")
    advance_clock("2026-08-12T00:00:00Z")
    finalize_case(case["id"])
    advance_clock("2026-08-20T00:00:00Z")
    return context, case


def test_declared_transition_gate_answers_before_the_review_deadline_gate():
    """Requesting administrative review on a case that is already final is
    refused as an invalid state, not as a missed deadline.

    Both gates answer 409, so only the identifier distinguishes them: the
    declared-transition check sits at rule 9 and the deadline family at rule 12,
    and no administrative-review request is declared from SANCTION_FINAL. The
    clock is nine days past `admin_review_due_at`, so a deadline-first
    implementation would answer ERR_ADMIN_REVIEW_WINDOW_CLOSED.

    Design: Difficulty/priority_pair_validation_conflict/admin_review_state_gate_priority_9_beats_deadline_gate_priority_12
    """
    context, case = _finalized_case_past_its_review_deadline()

    response = api_client.request_administrative_review(
        case["id"],
        {"grounds_text": "The determination misread the household interview evidence."},
        context.owner_h,
    )

    body = validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_ADMIN_REVIEW_WINDOW_CLOSED.value


def test_refused_review_request_leaves_the_final_case_untouched():
    """The rejected request records no review: the case stays final with its
    original deadline and an empty request timestamp.

    A ten-day administrative-review window opens at the determination, so the
    deadline stamped on the case remains 2026-08-11 whatever the clock later
    reads, and the store's sanction dimension stays where finalization left it.

    Design: Difficulty/priority_pair_validation_conflict/admin_review_state_gate_priority_9_beats_deadline_gate_priority_12
    """
    context, case = _finalized_case_past_its_review_deadline()

    api_client.request_administrative_review(
        case["id"],
        {"grounds_text": "The determination misread the household interview evidence."},
        context.owner_h,
    )

    assert_fields(
        refresh_case(case["id"]),
        {
            "status": "SANCTION_FINAL",
            "admin_review_requested_at": None,
            "admin_review_due_at": "2026-08-11T00:00:00Z",
        },
        "untouched final case",
    )
    assert refresh_store(context.store_id)["sanction_status"] == "SANCTION_FINAL"


def _late_election_on_a_non_hardship_store():
    context = authorized_store()
    store = refresh_store(context.store_id)
    ok(
        api_client.update_store(
            store["id"],
            store_patch_payload(store["version"], hardship_designated=False),
            ADMIN,
        )
    )
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    advance_clock("2026-08-15T00:00:00Z")
    return context, case


def test_election_deadline_gate_answers_before_the_substantive_cmp_gate():
    """An election filed four days late on a store that has lost its hardship
    designation is refused for lateness, not for ineligibility.

    The deadline family sits at rule 12 and the civil-money-penalty availability
    gates at rule 18, so the temporal gate outranks the substantive one. The
    supplied case version is the current one, so the optimistic-concurrency check
    at rule 8 has nothing to complain about either.

    Design: Difficulty/priority_pair_validation_conflict/cmp_election_deadline_priority_12_beats_hardship_gate_priority_18
    """
    context, case = _late_election_on_a_non_hardship_store()

    response = api_client.create_cmp_election(
        case["id"], cmp_election_payload(case["version"]), context.owner_h
    )

    body = validate_error(
        response, ApiErrorId.ERR_CMP_ELECTION_WINDOW_CLOSED.value, 409
    )
    assert body["error_id"] != ApiErrorId.ERR_CMP_NOT_AVAILABLE.value
    assert body["error_id"] != ApiErrorId.ERR_STALE_SANCTION_CASE_VERSION.value


def test_late_election_is_not_recorded_and_the_deadline_stands():
    """No election row survives the refusal, and the ten-day election deadline is
    still the one the charge letter fixed.

    The specification fixes both windows at the charge letter -- "A charge letter
    fixes `reply_due_at` and `cmp_election_due_at` at ten days after
    `charge_letter_sent_at`." -- and the store's hardship designation is genuinely
    off, which is the rule that must stay silent.

    Design: Difficulty/priority_pair_validation_conflict/cmp_election_deadline_priority_12_beats_hardship_gate_priority_18
    """
    context, case = _late_election_on_a_non_hardship_store()

    api_client.create_cmp_election(
        case["id"], cmp_election_payload(case["version"]), context.owner_h
    )

    assert_instant(
        refresh_case(case["id"])["cmp_election_due_at"],
        "2026-08-11T00:00:00Z",
        "cmp_election_due_at",
    )
    assert_no_rows(api_client.list_cmp_elections(case["id"], ADMIN))
    assert refresh_store(context.store_id)["hardship_designated"] is False
