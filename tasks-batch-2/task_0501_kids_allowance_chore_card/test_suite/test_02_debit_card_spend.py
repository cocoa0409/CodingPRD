"""Debit card, controls, and the spend lifecycle: holds, settle/reverse, locks, OCC, alerts.

Covers difficulty queue (dual_variant_calc spend, transitive_cascade settle,
non_linear_state_machine parallel dimensions, priority_pair card-locked,
boundary_precision control-limit, cross_entity authorization, compensating_invariant reverse)
and corner queue (calculations, validations, rbac, optimistic_concurrency) instances rooted
in PRD Sections 3.5, 3.6, 2.6, 2.9.
"""
from test_helpers import (
    validate_success, validate_error,
    make_child_headers, make_admin_headers,
    setup_child_with_funded_spend_jar, setup_locked_card, setup_pending_authorization,
    setup_family_with_child, get_card,
    create_limit_control, create_block_control,
)
from test_helpers.factories import (
    authorize_payload, settle_payload, lock_payload, create_control_payload,
    fund_jar_payload, alert_thresholds_payload,
)

ADMIN = make_admin_headers()


# ─── non_linear_state_machine: parallel lock x funding dimensions ───────────
def test_locked_card_still_flips_funded_when_spend_jar_funded(api):
    """PRD 3.5: "The `funding_state` dimension is `FUNDED` or `DRAINED` and is purely system-driven, flipping to `FUNDED` whenever the linked `SPEND` jar's `balance_cents` is greater than zero and to `DRAINED` whenever that balance becomes zero; it is recomputed on every spend-jar balance change and evolves independently of the lock, so even a locked card may flip between `FUNDED` and `DRAINED`."

    Design: Difficulty/non_linear_state_machine/debit_card_parallel_lock_funding_independent
    """
    fam, child, card, spend_jar_id, ph = setup_locked_card(deposit_cents=10_000)
    assert card["lock_state"] == "LOCKED"
    assert card["funding_state"] == "DRAINED"

    validate_success(api.fund_jar(child["id"], fund_jar_payload("SPEND", 4000), ph), 200)
    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)

    assert card_after["lock_state"] == "LOCKED"
    assert card_after["funding_state"] == "FUNDED"
    assert card_after["available_cents"] == 4000


def test_locking_does_not_change_funding_state(api):
    """PRD 3.5: "The `lock_state` dimension is `UNLOCKED` or `LOCKED` and gates spending outright: a locked card rejects every authorization regardless of funding."

    Locking a DRAINED card leaves funding_state DRAINED — the two dimensions evolve separately.

    Design: Difficulty/non_linear_state_machine/debit_card_parallel_lock_funding_independent
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=10_000)
    card = get_card(child["id"], parent_headers)
    assert card["funding_state"] == "DRAINED"

    locked = validate_success(api.lock_card(card["id"], lock_payload(card["version"]), parent_headers), 200)
    assert locked["lock_state"] == "LOCKED"
    assert locked["funding_state"] == "DRAINED"


# ─── dual_variant_calc: provisional hold vs final settle ────────────────────
def test_provisional_hold_then_final_settle_diverge(api):
    """PRD 3.5: "When all checks pass, the authorization creates a `Transaction` in `PENDING` status and places a hold: the hold reserves the full `amount_cents`, so the card's `held_cents` is increased by `amount_cents`, the spend jar's `balance_cents` is not yet touched, and `available_cents` drops by `amount_cents`."
    PRD 3.5: "Settlement cascades in three steps: first the hold is released, reducing the card's `held_cents` by the original `amount_cents`; second the spend jar's `balance_cents` is debited by the `settled_amount_cents`, which may be less than the original authorization; and third the resulting spend-jar balance change recomputes the card's `funding_state` and `available_cents"

    Design: Difficulty/dual_variant_calc/spend_provisional_hold_vs_final_settle_diverge
    """
    fam, child, card, spend_jar_id, txn, ph = setup_pending_authorization(
        spend_cents=5000, auth_cents=3000)
    # Provisional reservation: held 3000, available 2000, jar untouched at 5000.
    assert card["held_cents"] == 3000
    assert card["available_cents"] == 2000

    settled = validate_success(api.settle_transaction(txn["id"], settle_payload(2500), ADMIN), 200)
    assert settled["status"] == "SETTLED"

    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)
    assert card_after["held_cents"] == 0
    assert card_after["available_cents"] == 2500


def test_provisional_hold_reserves_full_amount(api):
    """PRD 3.5: "the hold reserves the full `amount_cents`, so the card's `held_cents` is increased by `amount_cents`, the spend jar's `balance_cents` is not yet touched, and `available_cents` drops by `amount_cents`."

    Design: Difficulty/dual_variant_calc/spend_provisional_hold_vs_final_settle_diverge
    """
    fam, child, card, spend_jar_id, txn, ph = setup_pending_authorization(
        spend_cents=5000, auth_cents=3000)
    jar = validate_success(api.get_jar(spend_jar_id, ph), 200)
    assert jar["balance_cents"] == 5000  # not yet debited
    assert card["held_cents"] == 3000
    assert card["available_cents"] == 2000


# ─── transitive_cascade: settle -> hold release -> jar debit -> card drained ─
def test_settle_cascade_releases_hold_debits_jar_drains_card(api):
    """PRD 3.5: "Settlement cascades in three steps: first the hold is released, reducing the card's `held_cents` by the original `amount_cents`; second the spend jar's `balance_cents` is debited by the `settled_amount_cents`, which may be less than the original authorization; and third the resulting spend-jar balance change recomputes the card's `funding_state` and `available_cents`, possibly flipping `FUNDED` to `DRAINED`."

    Design: Difficulty/transitive_cascade/settle_cascade_hold_jar_card_depth3
    """
    fam, child, card, spend_jar_id, txn, ph = setup_pending_authorization(
        spend_cents=4000, auth_cents=4000, merchant_id="M9", category="BOOKS")

    validate_success(api.settle_transaction(txn["id"], settle_payload(4000), ADMIN), 200)

    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)
    jar_after = validate_success(api.get_jar(spend_jar_id, ph), 200)
    assert card_after["held_cents"] == 0
    assert jar_after["balance_cents"] == 0
    assert card_after["funding_state"] == "DRAINED"


def test_settle_marks_transaction_settled(api):
    """PRD 3.5: "The transaction's `status` becomes `SETTLED` and the card's `version` increments by one."

    Design: Difficulty/transitive_cascade/settle_cascade_hold_jar_card_depth3
    """
    fam, child, card, spend_jar_id, txn, ph = setup_pending_authorization(
        spend_cents=4000, auth_cents=4000, merchant_id="M9", category="BOOKS")
    settled = validate_success(api.settle_transaction(txn["id"], settle_payload(4000), ADMIN), 200)
    assert settled["status"] == "SETTLED"


# ─── compensating_invariant: reverse restores jar + held ────────────────────
def test_reverse_restores_spend_jar_and_held(api):
    """PRD 3.5: "Reversal is a true compensation: authorizing then reversing must leave the spend jar's `balance_cents` exactly as it was before the authorization and must leave the card's `held_cents` exactly as it was before the authorization, with no drift in either quantity."

    Design: Difficulty/compensating_invariant/reverse_restores_spend_jar_and_held
    """
    fam, child, card, spend_jar_id, txn, ph = setup_pending_authorization(
        spend_cents=5000, auth_cents=3000)

    reversed_txn = validate_success(api.reverse_transaction(txn["id"], ADMIN), 200)
    assert reversed_txn["status"] == "REVERSED"

    jar_after = validate_success(api.get_jar(spend_jar_id, ph), 200)
    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)
    assert jar_after["balance_cents"] == 5000
    assert card_after["held_cents"] == 0
    assert card_after["available_cents"] == 5000


def test_reverse_leaves_jar_untouched_no_debit(api):
    """PRD 3.5: "Reversing a pending transaction instead releases the hold — reducing `held_cents` by the original `amount_cents` — without ever debiting the spend jar, recomputes the card's `funding_state` and `available_cents`, sets `status` to `REVERSED`, and increments the card's `version` by one."

    Design: Difficulty/compensating_invariant/reverse_restores_spend_jar_and_held
    """
    fam, child, card, spend_jar_id, txn, ph = setup_pending_authorization(
        spend_cents=5000, auth_cents=3000)
    validate_success(api.reverse_transaction(txn["id"], ADMIN), 200)
    jar_after = validate_success(api.get_jar(spend_jar_id, ph), 200)
    assert jar_after["balance_cents"] == 5000  # never debited


# ─── priority_pair: card locked beats insufficient card funds ───────────────
def test_card_locked_beats_insufficient_card_funds(api):
    """PRD 3.5: "The card must be `UNLOCKED`, or the authorization is rejected with `ERR_CARD_LOCKED`."
    PRD 2.9: "The card-safety checks run in the order card-locked (`ERR_CARD_LOCKED`), then a matching block control (`ERR_CONTROL_BLOCKED`), then a matching limit control's cap (`ERR_CONTROL_LIMIT_EXCEEDED`)."

    A LOCKED card with available 0 authorizing 5000 violates both lock (safety) and funds (fiscal);
    the earlier card-locked check wins.

    Design: Difficulty/priority_pair_validation_conflict/card_locked_beats_insufficient_funds
    """
    fam, child, card, spend_jar_id, ph = setup_locked_card(deposit_cents=0)
    child_h = make_child_headers(child["id"])

    res = api.authorize(card["id"], authorize_payload("MX", "FOOD", 5000), child_h)
    validate_error(res, "ERR_CARD_LOCKED")


def test_unlocked_card_insufficient_funds_surfaces_funds_error(api):
    """PRD 3.5: "Finally the card's `available_cents` must be at least the `amount_cents`, or the authorization is rejected with `ERR_INSUFFICIENT_CARD_FUNDS`."

    With the card UNLOCKED, the lock check passes and the lower-priority funds arm is reachable in
    isolation, confirming the pair's loser.

    Design: Difficulty/priority_pair_validation_conflict/card_locked_beats_insufficient_funds
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=10_000)
    card = get_card(child["id"], parent_headers)  # UNLOCKED, spend jar empty -> available 0
    child_h = make_child_headers(child["id"])

    res = api.authorize(card["id"], authorize_payload("MX", "FOOD", 5000), child_h)
    validate_error(res, "ERR_INSUFFICIENT_CARD_FUNDS")


# ─── cross_entity_state_dependency: authorization requires card UNLOCKED ────
def test_authorization_blocked_on_locked_card_even_when_funded(api):
    """PRD 3.5: "The card must be `UNLOCKED`, or the authorization is rejected with `ERR_CARD_LOCKED`."
    PRD 3.5: "When all checks pass, the authorization creates a `Transaction` in `PENDING` status and places a hold"

    Design: Difficulty/cross_entity_state_dependency/authorization_requires_card_unlocked
    """
    fam, child, card, spend_jar_id, ph = setup_locked_card(spend_cents=8000, deposit_cents=20_000)
    assert card["funding_state"] == "FUNDED"
    assert card["available_cents"] == 8000
    child_h = make_child_headers(child["id"])

    res = api.authorize(card["id"], authorize_payload("M2", "FOOD", 3000), child_h)
    validate_error(res, "ERR_CARD_LOCKED")

    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)
    assert card_after["held_cents"] == 0
    assert card_after["available_cents"] == 8000


def test_authorization_succeeds_on_unlocked_funded_card(api):
    """PRD 3.5: "When all checks pass, the authorization creates a `Transaction` in `PENDING` status and places a hold: the hold reserves the full `amount_cents`, so the card's `held_cents` is increased by `amount_cents"

    Design: Difficulty/cross_entity_state_dependency/authorization_requires_card_unlocked
    """
    fam, child, card, spend_jar_id, ph = setup_child_with_funded_spend_jar(8000)
    child_h = make_child_headers(child["id"])

    txn = validate_success(api.authorize(card["id"], authorize_payload("M2", "FOOD", 3000), child_h), 201)
    assert txn["status"] == "PENDING"
    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)
    assert card_after["held_cents"] == 3000


# ─── boundary_precision: control LIMIT cap exact equality ───────────────────
def test_control_limit_cap_exact_equality_passes(api):
    """PRD 3.5: "For every active `LIMIT` control that matches, the cumulative spend already committed plus this `amount_cents` must not exceed that control's `per_period_cap_cents`, or it is rejected with `ERR_CONTROL_LIMIT_EXCEEDED`."
    PRD 3.5: "The cumulative spend for a limit is the sum of `amount_cents` across all transactions on the card whose `status` is either `PENDING` or `SETTLED` and that match the control's dimension"

    Cumulative 3000 + a 2000 authorization reaches exactly the 5000 cap (5000 does not exceed 5000).

    Design: Difficulty/boundary_precision_check/control_limit_cap_exact_equality_passes
    """
    fam, child, card, spend_jar_id, ph = setup_child_with_funded_spend_jar(20_000, deposit_cents=50_000)
    ctl, card = create_limit_control(card, "GAMESTORE", "STORE", 5000, ph)
    child_h = make_child_headers(child["id"])

    validate_success(api.authorize(card["id"], authorize_payload("GAMESTORE", "GAMING", 3000), child_h), 201)
    txn2 = validate_success(api.authorize(card["id"], authorize_payload("GAMESTORE", "GAMING", 2000), child_h), 201)

    assert txn2["status"] == "PENDING"
    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)
    assert card_after["held_cents"] == 5000


def test_control_limit_one_over_cap_rejected(api):
    """PRD 3.5: "For every active `LIMIT` control that matches, the cumulative spend already committed plus this `amount_cents` must not exceed that control's `per_period_cap_cents`, or it is rejected with `ERR_CONTROL_LIMIT_EXCEEDED`."

    Cumulative 3000 + 2001 = 5001 exceeds the 5000 cap by one cent.

    Design: Difficulty/boundary_precision_check/control_limit_cap_exact_equality_passes
    """
    fam, child, card, spend_jar_id, ph = setup_child_with_funded_spend_jar(20_000, deposit_cents=50_000)
    ctl, card = create_limit_control(card, "GAMESTORE", "STORE", 5000, ph)
    child_h = make_child_headers(child["id"])

    validate_success(api.authorize(card["id"], authorize_payload("GAMESTORE", "GAMING", 3000), child_h), 201)
    res = api.authorize(card["id"], authorize_payload("GAMESTORE", "GAMING", 2001), child_h)
    validate_error(res, "ERR_CONTROL_LIMIT_EXCEEDED")


# ─── combinatorial_formula: CATEGORY limit at cap then 1-cent over ──────────
def test_category_limit_cumulative_reaches_cap_then_rejects(api):
    """PRD 3.5: "For every active `LIMIT` control that matches, the cumulative spend already committed plus this `amount_cents` must not exceed that control's `per_period_cap_cents`, or it is rejected with `ERR_CONTROL_LIMIT_EXCEEDED`."
    PRD 3.5: "a `CATEGORY` control sums transactions whose `category` equals its `match_value`."

    Cumulative GAMING spend 3000 + 2000 reaches the 5000 cap; a further 1-cent GAMING authorization
    (5001) is rejected.

    Design: Difficulty/combinatorial_formula/card_control_limit_three_input_conditional_branches
    """
    fam, child, card, spend_jar_id, ph = setup_child_with_funded_spend_jar(20_000, deposit_cents=50_000)
    ctl, card = create_limit_control(card, "GAMING", "CATEGORY", 5000, ph)
    child_h = make_child_headers(child["id"])

    validate_success(api.authorize(card["id"], authorize_payload("MG", "GAMING", 3000), child_h), 201)
    validate_success(api.authorize(card["id"], authorize_payload("MG", "GAMING", 2000), child_h), 201)
    res = api.authorize(card["id"], authorize_payload("MG", "GAMING", 1), child_h)
    validate_error(res, "ERR_CONTROL_LIMIT_EXCEEDED")


def test_category_limit_matches_on_category_not_store(api):
    """PRD 3.5: "A `STORE` control matches a specific `merchant_id` and a `CATEGORY` control matches a merchant category code such as `GAMING` or `FOOD`, with the matched merchant or category supplied in `match_value`."

    The CATEGORY GAMING limit sums by category; a FOOD authorization at the same merchant does not
    count toward the GAMING cap, so a GAMING spend already at cap still rejects while the limit is
    keyed off category equality.

    Design: Difficulty/combinatorial_formula/card_control_limit_three_input_conditional_branches
    """
    fam, child, card, spend_jar_id, ph = setup_child_with_funded_spend_jar(20_000, deposit_cents=50_000)
    ctl, card = create_limit_control(card, "GAMING", "CATEGORY", 5000, ph)
    child_h = make_child_headers(child["id"])

    # A FOOD spend at merchant MG does not count toward the GAMING category cap.
    validate_success(api.authorize(card["id"], authorize_payload("MG", "FOOD", 4000), child_h), 201)
    # GAMING up to the cap still passes; cumulative GAMING is 5000.
    validate_success(api.authorize(card["id"], authorize_payload("MG", "GAMING", 5000), child_h), 201)
    res = api.authorize(card["id"], authorize_payload("MG", "GAMING", 1), child_h)
    validate_error(res, "ERR_CONTROL_LIMIT_EXCEEDED")


# ─── corner calculations: partial settle ────────────────────────────────────
def test_partial_settle_returns_difference_to_spendable(api):
    """PRD 3.5: "second the spend jar's `balance_cents` is debited by the `settled_amount_cents`, which may be less than the original authorization"
    PRD 3.5: "The net effect on `available_cents` differs from the original reservation by exactly the gap between the authorized `amount_cents` and the settled `settled_amount_cents`."

    Design: Corner/calculations/partial_settle_leaves_residual_jar_balance
    """
    fam, child, card, spend_jar_id, txn, ph = setup_pending_authorization(
        spend_cents=5000, auth_cents=4000, merchant_id="M7", category="FOOD")

    validate_success(api.settle_transaction(txn["id"], settle_payload(1500), ADMIN), 200)

    jar_after = validate_success(api.get_jar(spend_jar_id, ph), 200)
    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)
    assert jar_after["balance_cents"] == 3500
    assert card_after["held_cents"] == 0
    assert card_after["available_cents"] == 3500


# ─── corner validations: settle amount over authorization ───────────────────
def test_settle_amount_over_authorization_rejected(api):
    """PRD 3.5: "Settling a pending transaction supplies a final `settled_amount_cents` that must be greater than zero and at most the original `amount_cents`; a value outside that range is rejected with `ERR_INVALID_SETTLE_AMOUNT`."

    Design: Corner/validations/settle_amount_over_authorization_returns_invalid_settle_amount
    """
    fam, child, card, spend_jar_id, txn, ph = setup_pending_authorization(
        spend_cents=10_000, auth_cents=3000, merchant_id="M8", category="FOOD")

    res = api.settle_transaction(txn["id"], settle_payload(4000), ADMIN)
    validate_error(res, "ERR_INVALID_SETTLE_AMOUNT")
    txn_after = validate_success(api.get_transaction(txn["id"], ph), 200)
    assert txn_after["status"] == "PENDING"


# ─── corner validations: BLOCK control denies matching authorization ────────
def test_block_control_denies_matching_authorization(api):
    """PRD 3.5: "A `BLOCK` rule denies any matching authorization outright."
    PRD 3.5: "No active `BLOCK` control may match the transaction's `merchant_id` (for a `STORE` control) or `category` (for a `CATEGORY` control), or it is rejected with `ERR_CONTROL_BLOCKED`."

    Design: Corner/validations/control_block_denies_matching_authorization
    """
    fam, child, card, spend_jar_id, ph = setup_child_with_funded_spend_jar(10_000, deposit_cents=20_000)
    ctl, card = create_block_control(card, "GAMING", "CATEGORY", ph)
    child_h = make_child_headers(child["id"])

    res = api.authorize(card["id"], authorize_payload("MG", "GAMING", 1000), child_h)
    validate_error(res, "ERR_CONTROL_BLOCKED")


def test_deactivated_block_control_no_longer_blocks(api):
    """PRD 3.5: "Controls can be listed with an optional `is_active` filter and soft-deactivated by deletion, which sets `is_active` to false; inactive controls are skipped at authorization time."

    Design: Corner/validations/deactivated_control_no_longer_blocks
    """
    fam, child, card, spend_jar_id, ph = setup_child_with_funded_spend_jar(10_000, deposit_cents=20_000)
    ctl, card = create_block_control(card, "GAMING", "CATEGORY", ph)
    validate_success(api.delete_control(ctl["id"], ph), 200)
    child_h = make_child_headers(child["id"])

    txn = validate_success(api.authorize(card["id"], authorize_payload("MG", "GAMING", 1000), child_h), 201)
    assert txn["status"] == "PENDING"
    card_after = validate_success(api.get_debit_card(card["id"], ph), 200)
    assert card_after["held_cents"] == 1000


# ─── corner rbac: child cannot unlock ───────────────────────────────────────
def test_child_cannot_unlock_card(api):
    """PRD 3.5: "Locking moves `lock_state` from `UNLOCKED` to `LOCKED` and may be performed by the owning parent or the child; unlocking moves it from `LOCKED` back to `UNLOCKED` and is reserved to the parent."
    PRD 2.1: "When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/child_cannot_unlock_card
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=0)
    card = get_card(child["id"], parent_headers)
    child_h = make_child_headers(child["id"])
    locked = validate_success(api.lock_card(card["id"], lock_payload(card["version"]), child_h), 200)

    res = api.unlock_card(card["id"], lock_payload(locked["version"]), child_h)
    validate_error(res, "ERR_FORBIDDEN_ROLE")
    card_after = validate_success(api.get_debit_card(card["id"], parent_headers), 200)
    assert card_after["lock_state"] == "LOCKED"


# ─── corner optimistic_concurrency: OCC on lock / control-create ────────────
def test_lock_with_current_version_succeeds_and_increments(api):
    """PRD 3.5: "Both require `expected_debit_card_version` to match the card's current `version`, both reject a mismatch with `ERR_STALE_CARD_VERSION`, and both increment the card's `version` by one on success."

    Design: Corner/cross_cutting_complexity_layers/occ_lock_correct_version_succeeds_and_increments
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=0)
    card = get_card(child["id"], parent_headers)
    v0 = card["version"]

    locked = validate_success(api.lock_card(card["id"], lock_payload(v0), parent_headers), 200)
    assert locked["lock_state"] == "LOCKED"
    assert locked["version"] == v0 + 1


def test_lock_with_stale_version_after_authorization_rejected(api):
    """PRD 2.6: "locking a card whose `version` has advanced since the client read it is rejected with `ERR_STALE_CARD_VERSION`: this captures the case where an authorization has already placed a hold on the card — advancing its `version` and `held_cents` — after the client read the card"
    PRD 3.5: "Each authorization increments the card's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_lock_stale_version_after_authorization_conflict
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=20_000)
    card = get_card(child["id"], parent_headers)
    stale_v = card["version"]
    validate_success(api.fund_jar(child["id"], fund_jar_payload("SPEND", 5000), parent_headers), 200)
    child_h = make_child_headers(child["id"])
    validate_success(api.authorize(card["id"], authorize_payload("M3", "FOOD", 1000), child_h), 201)

    res = api.lock_card(card["id"], lock_payload(stale_v), parent_headers)
    validate_error(res, "ERR_STALE_CARD_VERSION")
    card_after = validate_success(api.get_debit_card(card["id"], parent_headers), 200)
    assert card_after["lock_state"] == "UNLOCKED"


def test_control_create_with_stale_version_rejected(api):
    """PRD 2.6: "Creating a `CardControl` against a stale card view is likewise rejected with `ERR_STALE_CARD_VERSION`, because a control added against a card whose `version` has already moved could silently miss authorizations that advanced it; the writer must re-read the card and re-issue against the current `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_control_create_stale_version_conflict
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=20_000)
    card = get_card(child["id"], parent_headers)
    stale_v = card["version"]
    validate_success(api.fund_jar(child["id"], fund_jar_payload("SPEND", 5000), parent_headers), 200)
    child_h = make_child_headers(child["id"])
    validate_success(api.authorize(card["id"], authorize_payload("M4", "FOOD", 1000), child_h), 201)

    res = api.create_control(
        card["id"], create_control_payload("CATEGORY", "GAMING", "BLOCK", stale_v), parent_headers)
    validate_error(res, "ERR_STALE_CARD_VERSION")
    controls = validate_success(api.list_controls(card["id"], parent_headers), 200)
    assert len(controls) == 0


# ─── corner entities: spend alert immutable / large spend ───────────────────
def test_large_spend_alert_emitted_and_immutable(api):
    """PRD 3.6: "If the `amount_cents` is at least the family's `large_spend_threshold_cents`, a spend alert of `alert_kind` `LARGE_SPEND` is emitted."
    PRD 2.4: "the `SpendAlert` is an immutable audit record and therefore carries only `id` and `created_at`; it has neither an `updated_at` nor a `version`."

    Design: Corner/entities/spend_alert_immutable_no_version_field
    """
    fam, child, parent_headers = setup_family_with_child(deposit_cents=20_000)
    validate_success(api.set_alert_thresholds(
        fam["id"], alert_thresholds_payload(3000, 1000), parent_headers), 200)
    validate_success(api.fund_jar(child["id"], fund_jar_payload("SPEND", 10_000), parent_headers), 200)
    card = get_card(child["id"], parent_headers)
    child_h = make_child_headers(child["id"])

    txn = validate_success(api.authorize(card["id"], authorize_payload("MB", "FOOD", 5000), child_h), 201)
    alerts = validate_success(api.list_alerts(txn["id"], parent_headers), 200)

    large = [a for a in alerts if a["alert_kind"] == "LARGE_SPEND"]
    assert len(large) >= 1
    alert = large[0]
    assert alert["amount_cents"] == 5000
    assert "version" not in alert
    assert "updated_at" not in alert

