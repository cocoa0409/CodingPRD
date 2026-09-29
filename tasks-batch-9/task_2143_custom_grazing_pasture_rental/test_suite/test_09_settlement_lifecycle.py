"""Issuing, disputing, adjudicating, reissuing, finalizing and voiding."""

from test_helpers import (
    ApiErrorId,
    adjudicate_settlement,
    assert_same_instant,
    dispute_settlement,
    draft_settlement,
    finalize_settlement_as_owner,
    issue_settlement,
    make_cattle_owner_headers,
    make_grazier_headers,
    make_range_consultant_headers,
    read_contract,
    read_lot,
    read_owner,
    read_pasture,
    read_settlement,
    reissue_settlement,
    set_logical_clock,
    setup_delinquency_world,
    setup_north_bench_settlement_disputed,
    setup_north_bench_settlement_draft,
    setup_north_bench_settlement_issued,
    validate_error,
    validate_success,
    void_settlement,
)


# ===========================================================================
# The negotiation cycle ISSUED -> DISPUTED -> ADJUDICATED -> ISSUED
# ===========================================================================

def test_an_upheld_grazier_ruling_leaves_the_provisional_price_and_reissue_reopens_it(api):
    """PRD 3.9: "The resolution maps directly onto the gain method: `UPHELD_GRAZIER`
    sets `gain_method` to `PROVISIONAL_PRORATED`, `UPHELD_OWNER` sets it to
    `FINAL_ADJUDICATED`, and `SPLIT_MIDPOINT` sets it to `SPLIT_MIDPOINT`."
    PRD 3.9: "The grazier may reissue an adjudicated settlement, moving it
    `ADJUDICATED → ISSUED` and restamping `issued_at` from the logical clock, which
    restarts the dispute window from scratch."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_adjudicate_reissue_cycle_on_settlement
    """
    world = setup_north_bench_settlement_issued(second_consultant=True)

    disputed = dispute_settlement(
        world.settlement_id, world.owner_id,
        claimed_shrunk_gain_lbs=14000, note="Round one",
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_round"] == 1

    ruled = adjudicate_settlement(
        world.settlement_id, world.consultant2_id, "UPHELD_GRAZIER",
        note="Scale tickets support the grazier's figure",
    )
    assert ruled["gain_method"] == "PROVISIONAL_PRORATED"
    assert ruled["total_due_cents"] == 1132322
    assert ruled["status"] == "ADJUDICATED"

    reissued = reissue_settlement(world.settlement_id, world.grazier_id)
    assert reissued["status"] == "ISSUED"
    assert reissued["dispute_round"] == 1, "Reissue does not touch the round counter"


def test_a_third_dispute_is_refused_once_both_rounds_are_spent(api):
    """PRD 3.9: "Rounds are finite: `dispute_round` must be below 2 to open another, so
    a settlement that has already been through two rounds is refused with
    `ERR_DISPUTE_ROUNDS_EXHAUSTED`."
    PRD 3.9: "Under `SPLIT_MIDPOINT`, `shrunk_gain_lbs` is the average of the
    provisional gain and the owner's own claimed figure — the two added together,
    divided by two, rounded half up to a whole pound — and `adjusted_in_weight_lbs` is
    back-solved as the shrunk out-weight less that gain."
    PRD 3.9: "This is what closes the negotiation cycle
    `ISSUED → DISPUTED → ADJUDICATED → ISSUED`, and it is bounded only by the round cap:
    reissue does not touch `dispute_round`, which is incremented solely by opening a
    dispute, so an owner gets at most two bites regardless of how many times the grazier
    reissues."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_adjudicate_reissue_cycle_on_settlement
    """
    world = setup_north_bench_settlement_issued(second_consultant=True)

    dispute_settlement(
        world.settlement_id, world.owner_id,
        claimed_shrunk_gain_lbs=14000, note="Round one",
    )
    adjudicate_settlement(
        world.settlement_id, world.consultant2_id, "UPHELD_GRAZIER",
        note="Scale tickets support the grazier's figure",
    )
    reissue_settlement(world.settlement_id, world.grazier_id)

    set_logical_clock("2026-11-14T00:00:00Z")
    dispute_settlement(
        world.settlement_id, world.owner_id,
        claimed_shrunk_gain_lbs=14000, note="Round two",
    )
    ruled = adjudicate_settlement(
        world.settlement_id, world.consultant2_id, "SPLIT_MIDPOINT",
        note="Split the difference",
    )
    assert ruled["gain_method"] == "SPLIT_MIDPOINT"
    assert ruled["shrunk_gain_lbs"] == 13728, "The midpoint of 13456 and 14000"
    assert ruled["base_charge_cents"] == 1166880
    assert ruled["subtotal_cents"] == 1166880
    assert ruled["volume_rebate_cents"] == 11669
    assert ruled["total_due_cents"] == 1155211

    reissue_settlement(world.settlement_id, world.grazier_id)

    resp = api.dispute_settlement(
        world.settlement_id,
        {"disputed_field": "SHRUNK_GAIN_LBS", "claimed_shrunk_gain_lbs": 14000,
         "note": "Round three"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ROUNDS_EXHAUSTED.value, 409)

    final_state = read_settlement(world.settlement_id, world.grazier_id)
    assert final_state["dispute_round"] == 2
    assert final_state["status"] == "ISSUED"


# ===========================================================================
# The two contract dimensions move independently
# ===========================================================================

def test_voiding_an_issued_settlement_rewinds_billing_but_not_the_lifecycle(api):
    """PRD 3.3: "Those two status fields are separate dimensions and they move
    independently."
    PRD 3.9: "The contract's `billing_status` returns `SETTLEMENT_ISSUED → UNBILLED`,
    freeing the contract for a fresh draft — which is precisely why that fresh draft is
    guarded by the contract's `version`."

    Design: Difficulty/non_linear_state_machine/contract_lifecycle_and_billing_dimensions_move_independently
    """
    world = setup_north_bench_settlement_issued()

    issued_contract = read_contract(world.contract_id, world.grazier_id)
    assert issued_contract["lifecycle_status"] == "ACTIVE"
    assert issued_contract["billing_status"] == "SETTLEMENT_ISSUED"

    voided = void_settlement(
        world.settlement_id, world.grazier_id, "Wrong scale ticket attached"
    )
    assert voided["status"] == "VOID"

    after_void = read_contract(world.contract_id, world.grazier_id)
    assert after_void["lifecycle_status"] == "ACTIVE", (
        "The lifecycle dimension is untouched by the billing rewind"
    )
    assert after_void["billing_status"] == "UNBILLED"


def test_only_a_final_settlement_moves_the_lifecycle_dimension_to_completed(api):
    """PRD 3.9: "Reaching `FINAL` closes the whole file: the contract's `billing_status`
    moves `SETTLEMENT_ISSUED → SETTLED` and its `lifecycle_status` moves from `ACTIVE`
    or `EARLY_REMOVAL_PENDING` to `COMPLETED`; the settled lot moves
    `WEIGHED_OUT → CLOSED`; the pasture's `committed_head_days`,
    `capacity_utilization_pct`, `stocked_head_count` and `grazing_posture` are all
    recomputed now that the contract has left the booked set and the cattle have left
    the grass; the owner's `open_settlement_balance_cents` and `credit_status` are
    recomputed; and each affected record's `version` increments."
    PRD 3.9: "A `CattleOwner` accepting an `ISSUED` settlement may do so at any time
    inside the window — acceptance ends the argument early."

    Design: Difficulty/non_linear_state_machine/contract_lifecycle_and_billing_dimensions_move_independently
    """
    world = setup_north_bench_settlement_issued()
    void_settlement(world.settlement_id, world.grazier_id, "Wrong scale ticket attached")

    replacement = draft_settlement(world.contract_id, world.lot_id, world.grazier_id)
    issue_settlement(replacement["id"], world.grazier_id)
    finalized = finalize_settlement_as_owner(replacement["id"], world.owner_id)

    assert finalized["status"] == "FINAL"
    assert finalized["total_due_cents"] == 1132322

    contract = read_contract(world.contract_id, world.grazier_id)
    assert contract["billing_status"] == "SETTLED"
    assert contract["lifecycle_status"] == "COMPLETED"
    assert read_lot(world.lot_id, world.grazier_id)["status"] == "CLOSED"
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 0


# ===========================================================================
# Issuing drives the owner's ledger and the delinquency cascade
# ===========================================================================

def test_issuing_posts_the_charge_and_flips_the_owner_to_delinquent(api):
    """PRD 3.9: "The grazier issues the draft, moving it `DRAFT → ISSUED`."
    PRD 3.9: "The owner's `open_settlement_balance_cents` and `credit_status` are
    recomputed, since an issued settlement is now open exposure; if that recomputation
    flips the owner to `DELINQUENT`, every contract of theirs in `PENDING_SIGNATURE` is
    suspended as described in §3.3."
    PRD 3.1: "From those two numbers the system derives `credit_status`, which is
    `DELINQUENT` when the open balance is strictly greater than the credit limit and
    `GOOD_STANDING` otherwise; a balance exactly equal to the limit leaves the owner in
    `GOOD_STANDING`."

    Design: Difficulty/transitive_cascade/settlement_issue_delinquency_cascade_settlement_to_owner_to_contract
    """
    world = setup_delinquency_world(issue=False)
    assert world.settlement["total_due_cents"] == 184000
    assert world.settlement["billable_head_days"] == 1840

    resp = api.issue_settlement(
        world.settlement_id, make_grazier_headers(world.grazier_id)
    )
    issued = validate_success(resp, 200)
    assert issued["status"] == "ISSUED"

    owner = read_owner(world.owner_id, world.grazier_id)
    assert owner["open_settlement_balance_cents"] == 184000
    assert owner["credit_status"] == "DELINQUENT"


def test_the_delinquency_suspends_only_the_pending_contract(api):
    """PRD 3.3: "When an owner's `credit_status` flips from `GOOD_STANDING` to
    `DELINQUENT`, every contract of that owner sitting in `PENDING_SIGNATURE` is moved
    by the system to `SUSPENDED`, each such move incrementing that contract's `version`."
    PRD 3.3: "Contracts already `ACTIVE` are deliberately left alone — cattle on the
    ground do not come off over a credit balance."
    PRD 3.9: "The contract's `billing_status` moves `UNBILLED → SETTLEMENT_ISSUED`."

    Design: Difficulty/transitive_cascade/settlement_issue_delinquency_cascade_settlement_to_owner_to_contract
    """
    world = setup_delinquency_world(issue=False)
    issue_settlement(world.settlement_id, world.grazier_id)

    pending = read_contract(world.contract_k7["id"], world.grazier_id)
    assert pending["lifecycle_status"] == "SUSPENDED"

    active = read_contract(world.contract_k6["id"], world.grazier_id)
    assert active["lifecycle_status"] == "ACTIVE", "Cattle on the ground are left alone"
    assert active["billing_status"] == "SETTLEMENT_ISSUED"


# ===========================================================================
# The owner's open balance is conserved across issue and void
# ===========================================================================

def test_voiding_the_issued_settlement_returns_the_balance_to_zero(api):
    """PRD 3.1: "Against that limit sits `open_settlement_balance_cents`, which the
    owner never sets and which begins life at 0: it is the sum of the amount due across
    every settlement belonging to that owner whose `status` is `ISSUED`, `DISPUTED`,
    `ADJUDICATED` or `FINAL`. Settlements still in `DRAFT`, and settlements that have
    been voided, contribute nothing to it."
    PRD 3.9: "Voiding backs the charge out of the ledger: the owner's
    `open_settlement_balance_cents` and `credit_status` are recomputed without it, and
    if that returns the owner to `GOOD_STANDING`, every contract of theirs in
    `SUSPENDED` moves back to `PENDING_SIGNATURE`."

    Design: Difficulty/compensating_invariant/owner_open_balance_conserved_across_settlement_issue_and_void
    """
    world = setup_delinquency_world(issue=False)
    assert read_owner(world.owner_id, world.grazier_id)["open_settlement_balance_cents"] == 0

    issue_settlement(world.settlement_id, world.grazier_id)
    issued_owner = read_owner(world.owner_id, world.grazier_id)
    assert issued_owner["open_settlement_balance_cents"] == 184000
    assert issued_owner["credit_status"] == "DELINQUENT"

    voided = void_settlement(
        world.settlement_id, world.grazier_id,
        "Owner supplied a corrected certified scale ticket",
    )
    assert voided["status"] == "VOID"

    restored = read_owner(world.owner_id, world.grazier_id)
    assert restored["open_settlement_balance_cents"] == 0
    assert restored["credit_status"] == "GOOD_STANDING"


def test_the_void_reinstates_the_contract_the_issue_had_suspended(api):
    """PRD 3.3: "The cascade is compensating: when the same owner's `credit_status`
    returns to `GOOD_STANDING`, every contract of theirs in `SUSPENDED` moves back to
    `PENDING_SIGNATURE`, again incrementing `version`."
    PRD 3.9: "The contract's `billing_status` returns `SETTLEMENT_ISSUED → UNBILLED`,
    freeing the contract for a fresh draft — which is precisely why that fresh draft is
    guarded by the contract's `version`."

    Design: Difficulty/compensating_invariant/owner_open_balance_conserved_across_settlement_issue_and_void
    """
    world = setup_delinquency_world(issue=True)
    assert read_contract(world.contract_k7["id"], world.grazier_id)["lifecycle_status"] == (
        "SUSPENDED"
    )

    void_settlement(
        world.settlement_id, world.grazier_id,
        "Owner supplied a corrected certified scale ticket",
    )

    assert read_contract(world.contract_k7["id"], world.grazier_id)["lifecycle_status"] == (
        "PENDING_SIGNATURE"
    )
    settled_contract = read_contract(world.contract_k6["id"], world.grazier_id)
    assert settled_contract["billing_status"] == "UNBILLED"
    assert settled_contract["lifecycle_status"] == "ACTIVE"


# ===========================================================================
# Timing gates on the dispute window
# ===========================================================================

def test_a_grazier_may_not_finalize_inside_the_dispute_window_but_the_owner_may(api):
    """PRD 3.9: "A `Grazier` finalizing an `ISSUED` settlement must wait the window out:
    the current logical clock must be at or past `issued_at` plus ten days, or the
    attempt is refused with `ERR_DISPUTE_WINDOW_OPEN`."
    PRD 3.9: "A `CattleOwner` accepting an `ISSUED` settlement may do so at any time
    inside the window — acceptance ends the argument early."

    Design: Corner/state_machines/grazier_finalize_inside_the_dispute_window_returns_dispute_window_open
    """
    world = setup_north_bench_settlement_issued(clock="2026-11-11T00:00:00Z")
    set_logical_clock("2026-11-12T00:00:00Z")

    resp = api.finalize_settlement(
        world.settlement_id, make_grazier_headers(world.grazier_id)
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_OPEN.value, 409)

    accepted = finalize_settlement_as_owner(world.settlement_id, world.owner_id)
    assert accepted["status"] == "FINAL"
    assert accepted["total_due_cents"] == 1132322

    contract = read_contract(world.contract_id, world.grazier_id)
    assert contract["billing_status"] == "SETTLED"
    assert contract["lifecycle_status"] == "COMPLETED"
    assert read_lot(world.lot_id, world.grazier_id)["status"] == "CLOSED"


def test_a_dispute_opened_after_ten_days_is_refused(api):
    """PRD 3.9: "The window is real: the current logical clock must be no later than
    `issued_at` plus ten days, or the dispute is refused with
    `ERR_DISPUTE_WINDOW_CLOSED`."
    PRD 2.7: "Every window this document measures against the clock is measured in whole
    days from the stamp that opened it; the settlement dispute window, the only such
    window in the system, runs for ten days from `issued_at`."

    Design: Corner/state_machines/dispute_after_the_ten_day_window_returns_dispute_window_closed
    """
    world = setup_north_bench_settlement_issued(clock="2026-11-11T00:00:00Z")
    set_logical_clock("2026-11-22T00:00:00Z")

    resp = api.dispute_settlement(
        world.settlement_id,
        {"disputed_field": "SHRUNK_GAIN_LBS", "claimed_shrunk_gain_lbs": 14000,
         "note": "Too late"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value, 409)

    unchanged = read_settlement(world.settlement_id, world.grazier_id)
    assert unchanged["status"] == "ISSUED"
    assert unchanged["dispute_round"] == 0
    assert_same_instant(
        unchanged["issued_at"], "2026-11-11T00:00:00Z", "Settlement.issued_at"
    )


# ===========================================================================
# The ledger's input filter and the terminal lock
# ===========================================================================

def test_a_draft_settlement_contributes_nothing_to_the_owners_open_balance(api):
    """PRD 3.1: "Against that limit sits `open_settlement_balance_cents`, which the
    owner never sets and which begins life at 0: it is the sum of the amount due across
    every settlement belonging to that owner whose `status` is `ISSUED`, `DISPUTED`,
    `ADJUDICATED` or `FINAL`. Settlements still in `DRAFT`, and settlements that have
    been voided, contribute nothing to it."

    Design: Corner/calculations/owner_open_balance_ignores_draft_settlements
    """
    world = setup_delinquency_world(issue=False)
    assert world.settlement["total_due_cents"] == 184000
    assert world.settlement["status"] == "DRAFT"

    while_draft = read_owner(world.owner_id, world.grazier_id)
    assert while_draft["open_settlement_balance_cents"] == 0
    assert while_draft["credit_status"] == "GOOD_STANDING"

    issue_settlement(world.settlement_id, world.grazier_id)

    after_issue = read_owner(world.owner_id, world.grazier_id)
    assert after_issue["open_settlement_balance_cents"] == 184000
    assert after_issue["credit_status"] == "DELINQUENT"


def test_voiding_a_final_settlement_is_refused(api):
    """PRD 3.9: "`FINAL` and `VOID` are both terminal; a transition the settlement's
    current `status` does not declare is rejected with `ERR_SETTLEMENT_INVALID_STATE`."
    PRD 3.9: "The grazier may void a settlement that is still `DRAFT` or already
    `ISSUED`, supplying a `reason` stored as `void_reason`."

    Design: Corner/errors/voiding_a_final_settlement_returns_settlement_invalid_state
    """
    world = setup_north_bench_settlement_issued()
    finalize_settlement_as_owner(world.settlement_id, world.owner_id)

    resp = api.void_settlement(
        world.settlement_id, {"reason": "Changed my mind"},
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_INVALID_STATE.value, 409)

    assert read_settlement(world.settlement_id, world.grazier_id)["status"] == "FINAL"
    assert read_owner(world.owner_id, world.grazier_id)["open_settlement_balance_cents"] == (
        1132322
    )
    assert read_contract(world.contract_id, world.grazier_id)["billing_status"] == "SETTLED"


# ===========================================================================
# The logical clock and the segregation of duties
# ===========================================================================

def test_the_logical_clock_starts_at_its_fixed_default(api):
    """PRD 2.7: "Before any operator has set it, the clock reads exactly
    `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time."
    PRD 2.7: "A `PlatformAdmin` moves it — forward or backward — by supplying a
    `to_iso8601` instant; the response reports the resulting `current_utc`, and no
    entity is mutated by the move."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set_call
    """
    world = setup_north_bench_settlement_draft(clock=None)

    issued = issue_settlement(world.settlement_id, world.grazier_id)
    assert_same_instant(
        issued["issued_at"], "2026-08-01T00:00:00Z", "Settlement.issued_at"
    )

    moved = set_logical_clock("2026-08-20T00:00:00Z")
    assert_same_instant(
        moved["current_utc"], "2026-08-20T00:00:00Z", "the logical clock"
    )


def test_the_author_of_the_effective_assessment_may_not_adjudicate(api):
    """PRD 3.9: "A `RangeConsultant` rules on a disputed settlement, moving it
    `DISPUTED → ADJUDICATED`, and the platform enforces a segregation of duties here: a
    consultant who authored the effective capacity assessment on the pasture underneath
    the contract may not rule on that contract's gain, and their attempt is refused with
    `ERR_ADJUDICATOR_CONFLICT`."
    PRD 3.9: "The consultant supplies a `resolution` — `UPHELD_GRAZIER`, `UPHELD_OWNER`
    or `SPLIT_MIDPOINT` — and an optional `note` stored as `adjudication_note`; their
    own identifier is recorded as `adjudicator_id`."

    Design: Corner/rbac/assessor_of_the_effective_assessment_cannot_adjudicate_the_dispute
    """
    world = setup_north_bench_settlement_disputed(second_consultant=True)

    resp = api.adjudicate_settlement(
        world.settlement_id,
        {"resolution": "UPHELD_GRAZIER", "note": "Self-review attempt"},
        make_range_consultant_headers(world.consultant_id),
    )
    validate_error(resp, ApiErrorId.ERR_ADJUDICATOR_CONFLICT.value, 403)

    ruled = adjudicate_settlement(
        world.settlement_id, world.consultant2_id, "UPHELD_GRAZIER",
        note="Independent review",
    )
    assert ruled["status"] == "ADJUDICATED"
    assert ruled["adjudicator_id"] == world.consultant2_id
    assert ruled["gain_method"] == "PROVISIONAL_PRORATED"
    assert ruled["total_due_cents"] == 1132322
