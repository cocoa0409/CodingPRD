"""Household lifecycle: the suspend / reinstate cycle, the depth-3 cascade
into PurchaseTransactions, terminal-state lockdown, and conserved-quantity
roundtrip invariants.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_household, add_member,
    create_and_submit_application, approve_application,
    setup_household_with_active_card,
    setup_household_active_with_substantiated_flag,
    setup_substantiated_fraud_flag,
    create_eligible_category, create_purchase,
)

CW = TEST_USERS["caseworker_headers"]
MER = TEST_USERS["merchant_headers"]


# ─── Difficulty / non_linear_state_machine / household_suspend_reinstate_cycle ──

def test_household_suspend_then_reinstate_returns_to_active(api):
    """Household has a non-linear ACTIVE→SUSPENDED→ACTIVE cycle. A /suspend
    followed by /reinstate returns it to ACTIVE and the cascade flips the
    one ACTIVE EBTCard down to SUSPENDED and then back to ACTIVE.

    PRD §3.7: "Suspension transitions the household from `ACTIVE` to
    `SUSPENDED` and requires that at least one `FraudFlag` for the household
    has `status` of `SUBSTANTIATED`. The cascade fans out as follows: every
    `EBTCard` for the household with `status` of `ACTIVE` transitions to
    `SUSPENDED` (cascade link 2 of the fraud-driven household-suspend
    cascade), and every `MonthlyAllotment` for the household with `status`
    of `DRAFT` whose `benefit_month` equals the current month transitions
    to `EXPUNGED` (cascade link 3). The household's `version` increments
    by 1."
    PRD §3.7: "Reinstatement transitions the household from `SUSPENDED`
    back to `ACTIVE`. Every `EBTCard` for the household with `status` of
    `SUSPENDED` transitions back to `ACTIVE`, and the household's `version`
    increments by 1."

    Design: Difficulty/non_linear_state_machine/household_suspend_reinstate_cycle
    """
    hh, card, _ff = setup_household_active_with_substantiated_flag(
        case_number="GA-500001", state_code="GA",
        clock_iso="2026-08-01T00:00:00Z",
    )
    suspended = validate_success(api.suspend_household(hh["id"], CW), 200)
    assert suspended["status"] == "SUSPENDED"
    card_susp = validate_success(api.get_ebt_card(card["id"], CW), 200)
    assert card_susp["status"] == "SUSPENDED", \
        f"ACTIVE card must cascade to SUSPENDED when household is suspended, got {card_susp['status']!r}"

    reinstated = validate_success(api.reinstate_household(hh["id"], CW), 200)
    assert reinstated["status"] == "ACTIVE", \
        f"reinstate must return household to ACTIVE, got {reinstated['status']!r}"
    card_back = validate_success(api.get_ebt_card(card["id"], CW), 200)
    assert card_back["status"] == "ACTIVE", \
        f"SUSPENDED card must cascade back to ACTIVE on reinstate, got {card_back['status']!r}"


def test_household_version_increments_through_suspend_reinstate_cycle(api):
    """The non-linear cycle bumps Household.version on both edges. PRD §3.7
    states the increment on suspend and the increment on reinstate as
    separate side-effects, so version must strictly grow across the cycle.

    PRD §3.7: "Suspension transitions the household from `ACTIVE` to
    `SUSPENDED` and requires that at least one `FraudFlag` for the household
    has `status` of `SUBSTANTIATED`. The cascade fans out as follows: every
    `EBTCard` for the household with `status` of `ACTIVE` transitions to
    `SUSPENDED` (cascade link 2 of the fraud-driven household-suspend
    cascade), and every `MonthlyAllotment` for the household with `status`
    of `DRAFT` whose `benefit_month` equals the current month transitions
    to `EXPUNGED` (cascade link 3). The household's `version` increments
    by 1."
    PRD §3.7: "Reinstatement transitions the household from `SUSPENDED`
    back to `ACTIVE`. Every `EBTCard` for the household with `status` of
    `SUSPENDED` transitions back to `ACTIVE`, and the household's `version`
    increments by 1."

    Design: Difficulty/non_linear_state_machine/household_suspend_reinstate_cycle
    """
    hh, _card, _ff = setup_household_active_with_substantiated_flag(
        case_number="GA-500002", state_code="GA",
        clock_iso="2026-08-01T00:00:00Z",
    )
    v0 = hh["version"]
    suspended = validate_success(api.suspend_household(hh["id"], CW), 200)
    v1 = suspended["version"]
    assert v1 > v0, f"version must advance on suspend, v0={v0}, v1={v1}"
    reinstated = validate_success(api.reinstate_household(hh["id"], CW), 200)
    v2 = reinstated["version"]
    assert v2 > v1, f"version must advance on reinstate, v1={v1}, v2={v2}"


# ─── Difficulty / transitive_cascade / suspend_cascade_household_to_card_to_transaction ──

def test_suspend_household_cascades_to_card_then_to_authorized_txn(api):
    """A single /suspend call drives three observable state changes: HH
    becomes SUSPENDED (direct effect), every ACTIVE card becomes SUSPENDED
    (cascade link 2 from PRD §3.7), and every AUTHORIZED transaction on
    those cards becomes REVERSED (cascade link 2 from PRD §3.6,
    transitively triggered by the card-suspend the first cascade
    produced — not by /suspend directly).

    PRD §3.7: "Suspension transitions the household from `ACTIVE` to
    `SUSPENDED` and requires that at least one `FraudFlag` for the household
    has `status` of `SUBSTANTIATED`. The cascade fans out as follows: every
    `EBTCard` for the household with `status` of `ACTIVE` transitions to
    `SUSPENDED` (cascade link 2 of the fraud-driven household-suspend
    cascade), and every `MonthlyAllotment` for the household with `status`
    of `DRAFT` whose `benefit_month` equals the current month transitions
    to `EXPUNGED` (cascade link 3). The household's `version` increments
    by 1."
    PRD §3.6: "Suspension flips an `ACTIVE` card to `SUSPENDED`. It can be
    invoked directly by a `Caseworker` or a `FraudInvestigator`, and it
    also fires as cascade link 2 of the household-suspension cascade (see
    §3.7). The side effect of suspension is that every `AUTHORIZED`
    purchase transaction on the card is moved to `REVERSED` (cascade link
    2 of the card-suspend cascade)."

    Design: Difficulty/transitive_cascade/suspend_cascade_household_to_card_to_transaction
    """
    set_clock("2026-08-01T00:00:00Z")
    create_eligible_category("FRESH_PRODUCE", "Fresh Produce", True)
    hh, _app, card = setup_household_with_active_card(
        case_number="GA-700001", state_code="GA",
        clock_iso="2026-08-01T00:00:00Z",
    )
    # An AUTHORIZED transaction on the active card before suspension.
    tx = create_purchase(
        card["id"],
        line_items=[{"category_code": "FRESH_PRODUCE",
                     "amount_cents": 5000, "quantity": 1}],
    )
    assert tx["status"] == "AUTHORIZED"
    _ff = setup_substantiated_fraud_flag(hh["id"])

    suspended_hh = validate_success(api.suspend_household(hh["id"], CW), 200)
    assert suspended_hh["status"] == "SUSPENDED"
    card_after = validate_success(api.get_ebt_card(card["id"], CW), 200)
    assert card_after["status"] == "SUSPENDED", (
        f"link 2: ACTIVE EBTCards must cascade to SUSPENDED, "
        f"got {card_after['status']!r}"
    )
    tx_after = validate_success(api.get_purchase_transaction(tx["id"], CW), 200)
    assert tx_after["status"] == "REVERSED", (
        f"link 3: AUTHORIZED purchase transactions on a suspended card must "
        f"transition to REVERSED, got {tx_after['status']!r}"
    )


def test_suspend_cascade_does_not_touch_pending_issue_card(api):
    """PRD §3.7 limits cascade link 2 to "every EBTCard for the household
    with status of ACTIVE". A PENDING_ISSUE card (e.g., one whose holder has
    not yet activated) must NOT be flipped — it remains PENDING_ISSUE so the
    cardholder can still activate it once the household is reinstated.

    PRD §3.7: "Suspension transitions the household from `ACTIVE` to
    `SUSPENDED` and requires that at least one `FraudFlag` for the household
    has `status` of `SUBSTANTIATED`. The cascade fans out as follows: every
    `EBTCard` for the household with `status` of `ACTIVE` transitions to
    `SUSPENDED` (cascade link 2 of the fraud-driven household-suspend
    cascade), and every `MonthlyAllotment` for the household with `status`
    of `DRAFT` whose `benefit_month` equals the current month transitions
    to `EXPUNGED` (cascade link 3). The household's `version` increments
    by 1."

    Design: Difficulty/transitive_cascade/suspend_cascade_household_to_card_to_transaction
    """
    set_clock("2026-08-01T00:00:00Z")
    hh = create_household(case_number="GA-700002", state_code="GA",
                          address_line="X")
    add_member(hh["id"], full_name="Solo", date_of_birth="1970-01-01",
               relationship="HEAD", disabled=True)
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"])
    cards = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh["id"]}), 200)
    assert cards[0]["status"] == "PENDING_ISSUE"
    card_id = cards[0]["id"]
    # Do NOT activate the card; leave it in PENDING_ISSUE.
    setup_substantiated_fraud_flag(hh["id"])
    validate_success(api.suspend_household(hh["id"], CW), 200)
    card_after = validate_success(api.get_ebt_card(card_id, CW), 200)
    assert card_after["status"] == "PENDING_ISSUE", (
        f"PENDING_ISSUE card must NOT cascade on household suspend "
        f"(PRD §3.7 limits cascade to ACTIVE cards), got {card_after['status']!r}"
    )


# ─── Difficulty / compensating_invariant / suspend_reinstate_card_count_invariant ──

def test_card_count_unchanged_across_suspend_reinstate_roundtrip(api):
    """The number of EBTCards belonging to a household is unchanged by the
    suspend/reinstate roundtrip — the cards are moved between states, not
    destroyed or duplicated. PRD §3.7 describes both directions as state
    transitions on the SAME cards.

    PRD §3.7: "Suspension transitions the household from `ACTIVE` to
    `SUSPENDED` and requires that at least one `FraudFlag` for the household
    has `status` of `SUBSTANTIATED`. The cascade fans out as follows: every
    `EBTCard` for the household with `status` of `ACTIVE` transitions to
    `SUSPENDED` (cascade link 2 of the fraud-driven household-suspend
    cascade), and every `MonthlyAllotment` for the household with `status`
    of `DRAFT` whose `benefit_month` equals the current month transitions
    to `EXPUNGED` (cascade link 3). The household's `version` increments
    by 1."
    PRD §3.7: "Reinstatement transitions the household from `SUSPENDED`
    back to `ACTIVE`. Every `EBTCard` for the household with `status` of
    `SUSPENDED` transitions back to `ACTIVE`, and the household's `version`
    increments by 1."

    Design: Difficulty/compensating_invariant/suspend_reinstate_card_count_invariant
    """
    hh, _card, _ff = setup_household_active_with_substantiated_flag(
        case_number="TX-180001", state_code="TX",
        clock_iso="2026-09-01T00:00:00Z",
    )
    pre = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh["id"]}), 200)
    n_pre = len(pre)

    validate_success(api.suspend_household(hh["id"], CW), 200)
    mid = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh["id"]}), 200)
    assert len(mid) == n_pre, (
        f"card cardinality must be preserved on suspend cascade; "
        f"pre={n_pre}, mid={len(mid)}"
    )

    validate_success(api.reinstate_household(hh["id"], CW), 200)
    post = validate_success(
        api.list_ebt_cards(CW, params={"household_id": hh["id"]}), 200)
    assert len(post) == n_pre, (
        f"card cardinality must be preserved on reinstate cascade; "
        f"pre={n_pre}, post={len(post)}"
    )


def test_card_returns_to_active_after_suspend_reinstate(api):
    """The same card object that was ACTIVE before the suspend is again
    ACTIVE after reinstate — it was state-shuffled, not replaced.

    PRD §3.7: "Reinstatement transitions the household from `SUSPENDED`
    back to `ACTIVE`. Every `EBTCard` for the household with `status` of
    `SUSPENDED` transitions back to `ACTIVE`, and the household's `version`
    increments by 1."

    Design: Difficulty/compensating_invariant/suspend_reinstate_card_count_invariant
    """
    hh, card, _ff = setup_household_active_with_substantiated_flag(
        case_number="TX-180002", state_code="TX",
        clock_iso="2026-09-01T00:00:00Z",
    )
    pre_card_id = card["id"]
    validate_success(api.suspend_household(hh["id"], CW), 200)
    validate_success(api.reinstate_household(hh["id"], CW), 200)
    after = validate_success(api.get_ebt_card(pre_card_id, CW), 200)
    assert after["id"] == pre_card_id, "card identity must persist"
    assert after["status"] == "ACTIVE", \
        f"card must return to ACTIVE after reinstate, got {after['status']!r}"


# ─── Difficulty / compensating_invariant / member_remove_reactivate_gross_income_invariant ──

def test_member_remove_then_reactivate_restores_gross_income(api):
    """For a 2-member household with earned=100000 + 50000, removing the
    50000 member drops Household.gross_income_cents to 100000; flipping that
    member back to ACTIVE restores 150000. PRD §3.1 names the drop and the
    add as the same symmetric calculation step.

    PRD §3.1: "Every member-roster change is reflected on the parent
    household synchronously. Adding or removing a member, or flipping a
    member's `status` between `ACTIVE` and `REMOVED` via a member update,
    recomputes the household's `size`, `gross_income_cents`, and
    `net_income_cents` (the latter via the calculation described in §3.4)
    and increments the household's `version` by 1."
    PRD §3.1: "The household-level `gross_income_cents` is always the sum
    of the earned and unearned income figures of `ACTIVE` members; the
    `size` field is the count of `ACTIVE` members and is supported only
    up to 16."

    Design: Difficulty/compensating_invariant/member_remove_reactivate_gross_income_invariant
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="FL-190001", state_code="FL",
                          address_line="X")
    add_member(hh["id"], full_name="M1", date_of_birth="1970-01-01",
               relationship="HEAD", monthly_earned_income_cents=100000,
               disabled=True)
    m2 = add_member(hh["id"], full_name="M2", date_of_birth="1972-01-01",
                    relationship="SPOUSE",
                    monthly_earned_income_cents=50000, disabled=True)
    app = create_and_submit_application(hh["id"])
    approve_application(app["id"])

    hh0 = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh0["gross_income_cents"] == 150000, \
        f"pre-action gross must be 150000, got {hh0['gross_income_cents']}"

    validate_success(api.patch_household_member(
        m2["id"], {"status": "REMOVED"}, CW), 200)
    hh_mid = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_mid["gross_income_cents"] == 100000, (
        f"after removing 50000-earned member, gross must drop to 100000, "
        f"got {hh_mid['gross_income_cents']}"
    )

    validate_success(api.patch_household_member(
        m2["id"], {"status": "ACTIVE"}, CW), 200)
    hh_post = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_post["gross_income_cents"] == 150000, (
        f"after reactivating member, gross must return to 150000, "
        f"got {hh_post['gross_income_cents']}"
    )


def test_household_size_tracks_active_member_count_roundtrip(api):
    """Household.size is the count of ACTIVE members; remove M2 → size=1;
    reactivate → size=2. Same invariant family as gross income but on
    cardinality.

    PRD §3.1: "The household-level `gross_income_cents` is always the sum
    of the earned and unearned income figures of `ACTIVE` members; the
    `size` field is the count of `ACTIVE` members and is supported only
    up to 16."
    PRD §3.1: "Every member-roster change is reflected on the parent
    household synchronously. Adding or removing a member, or flipping a
    member's `status` between `ACTIVE` and `REMOVED` via a member update,
    recomputes the household's `size`, `gross_income_cents`, and
    `net_income_cents` (the latter via the calculation described in §3.4)
    and increments the household's `version` by 1."

    Design: Difficulty/compensating_invariant/member_remove_reactivate_gross_income_invariant
    """
    set_clock("2026-09-01T00:00:00Z")
    hh = create_household(case_number="FL-190002", state_code="FL",
                          address_line="X")
    add_member(hh["id"], full_name="M1", date_of_birth="1970-01-01",
               relationship="HEAD", disabled=True)
    m2 = add_member(hh["id"], full_name="M2", date_of_birth="1972-01-01",
                    relationship="SPOUSE", disabled=True)
    hh0 = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh0["size"] == 2

    validate_success(api.patch_household_member(
        m2["id"], {"status": "REMOVED"}, CW), 200)
    hh_mid = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_mid["size"] == 1, \
        f"REMOVED member must not count toward size, got {hh_mid['size']}"

    validate_success(api.patch_household_member(
        m2["id"], {"status": "ACTIVE"}, CW), 200)
    hh_post = validate_success(api.get_household(hh["id"], CW), 200)
    assert hh_post["size"] == 2, \
        f"reactivated member must rejoin size, got {hh_post['size']}"


# ─── Corner / state_machines / terminate_already_terminated_household_returns_invalid_state ──

def test_terminate_already_terminated_household_returns_invalid_state(api):
    """TERMINATED is terminal per PRD §3.7. A second /terminate call has no
    listed from-state and must be rejected as ERR_INVALID_STATE.

    PRD §3.7: "Termination is irreversible. From `ACTIVE` or `SUSPENDED`,
    the household lands in `TERMINATED`; the request must carry a
    `decision_reason`. Every `EBTCard` for the household transitions to
    `CANCELLED` regardless of its prior state, every `MonthlyAllotment`
    for the household whose `benefit_month` is later than the current
    month transitions to `EXPUNGED`, and the household's `version`
    increments by 1. `TERMINATED` is terminal."

    Design: Corner/state_machines/terminate_already_terminated_household_returns_invalid_state
    """
    hh, _app, _card = setup_household_with_active_card(
        case_number="CA-400001", state_code="CA",
        clock_iso="2026-09-01T00:00:00Z",
    )
    validate_success(api.terminate_household(
        hh["id"], {"decision_reason": "fraud confirmed"}, CW), 200)
    resp = api.terminate_household(hh["id"], {"decision_reason": "again"}, CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
