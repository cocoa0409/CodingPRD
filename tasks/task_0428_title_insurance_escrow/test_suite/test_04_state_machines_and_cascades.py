"""Non-linear state machines, the Cascade A unwind, and premium conservation on reversal.

Covers queue A: non_linear_state_machine (commitment revision loop, claim curative loop),
transitive_cascade (order-cancel depth-3), compensating_invariant (premium conservation),
plus queue B state_machines / cross_cutting_complexity_layers corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_order_with_issued_commitment,
    setup_issued_owner_policy,
    create_issued_commitment,
    create_pending_policy,
    issue_policy,
    get_policy_remittance,
    add_title_search,
    transition_order,
    file_claim,
    get_order,
    assert_premium_split_conserves,
    TO,
    UW,
)


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine: commitment revision loop
# ---------------------------------------------------------------------------
def test_commitment_revision_loop_issued_updated_issued(api):
    """PRD §3.4: "Creating a new commitment under an order that already has an `ISSUED`
    commitment supersedes the prior one: the prior `ISSUED` commitment flips to `UPDATED`,
    its `revision_no` is incremented by 1, and the order's `version` is incremented by 1".
    PRD §3.4: "A superseded commitment in `UPDATED` can later be re-issued back to
    `ISSUED` — again only when no other commitment on the same order is currently `ISSUED`,
    else `ERR_INVALID_STATE` — closing the loop."

    Design: Difficulty/non_linear_state_machine/commitment_issued_updated_revision_loop
    """
    _agency, order, c1 = setup_order_with_issued_commitment()
    # Re-issue create supersedes C1 -> UPDATED (revision_no 1); creates C2 in DRAFT.
    fresh = get_order(order["id"])
    c2 = validate_success(
        api.create_commitment(
            order["id"],
            {
                "effective_date": "2026-02-05T00:00:00Z", "expiry_date": "2026-08-05T00:00:00Z",
                "schedule_a_estate": "FEE_SIMPLE", "insured_amount_cents": 25_000_000,
                "expected_order_version": fresh["version"],
            },
            TO,
        ),
        expected_status=201,
    )
    c1_mid = validate_success(api.get_commitment(c1["id"], TO))
    assert c1_mid["status"] == "UPDATED", "prior ISSUED commitment flips to UPDATED on re-issue create"
    assert c1_mid["revision_no"] == 1, "revision_no incremented to 1"
    # Close the loop: re-issue C1 (UPDATED) back to ISSUED — C2 is DRAFT so no other ISSUED.
    data = validate_success(api.transition_commitment(c1["id"], {"to_status": "ISSUED"}, TO))
    assert data["status"] == "ISSUED", "UPDATED commitment can re-issue back to ISSUED"
    assert c2["status"] == "DRAFT"


def test_commitment_reissue_create_bumps_order_version(api):
    """PRD §3.4: "the prior `ISSUED` commitment flips to `UPDATED`, its `revision_no` is
    incremented by 1, and the order's `version` is incremented by 1 (the parent bump that
    backs the optimistic-concurrency rule of §2.7)."

    Design: Difficulty/non_linear_state_machine/commitment_issued_updated_revision_loop
    """
    _agency, order, _c1 = setup_order_with_issued_commitment()
    before = get_order(order["id"])["version"]
    validate_success(
        api.create_commitment(
            order["id"],
            {
                "effective_date": "2026-02-05T00:00:00Z", "expiry_date": "2026-08-05T00:00:00Z",
                "schedule_a_estate": "FEE_SIMPLE", "insured_amount_cents": 25_000_000,
                "expected_order_version": before,
            },
            TO,
        ),
        expected_status=201,
    )
    after = get_order(order["id"])["version"]
    assert after == before + 1, f"order version must bump by 1 on re-issue create ({before} -> {after})"


def test_claim_curative_loop_back_to_investigating(api):
    """PRD §3.9: "From `INVESTIGATING` the claim can move to `CURATIVE` to pursue a cure
    and can loop back from `CURATIVE` to `INVESTIGATING` when curative is inconclusive, as
    many times as needed."

    Design: Difficulty/non_linear_state_machine/claim_investigating_curative_loop
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy()
    claim = file_claim(policy, claim_type="BOUNDARY_DISPUTE", estimated_loss_cents=40_000)
    validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
    validate_success(api.transition_claim(claim["id"], {"to_status": "CURATIVE"}, UW))
    data = validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
    assert data["status"] == "INVESTIGATING", "claim must loop CURATIVE -> INVESTIGATING"


def test_claim_curative_loop_runs_twice(api):
    """PRD §3.9: "From `INVESTIGATING` the claim can move to `CURATIVE` to pursue a cure
    and can loop back from `CURATIVE` to `INVESTIGATING` when curative is inconclusive, as
    many times as needed."
    Two full INVESTIGATING -> CURATIVE -> INVESTIGATING cycles confirm the non-linear loop
    is re-entrant.

    Design: Difficulty/non_linear_state_machine/claim_investigating_curative_loop
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy()
    claim = file_claim(policy, claim_type="BOUNDARY_DISPUTE", estimated_loss_cents=40_000)
    validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
    for _ in range(2):
        validate_success(api.transition_claim(claim["id"], {"to_status": "CURATIVE"}, UW))
        data = validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
        assert data["status"] == "INVESTIGATING"


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade: order cancel depth-3 (commitment -> policy -> remittance)
# ---------------------------------------------------------------------------
def test_order_cancel_cascade_voids_commitment_policy_and_reverses_remittance(api):
    """PRD §2.5: "In the first link, every `Commitment` of the order that is in `ISSUED`,
    `UPDATED`, or `DRAFT` moves to `CANCELLED`. In the second link, each commitment that
    cancels drives every `Policy` it owns that is in `PENDING` or `ISSUED` to `VOID`. In
    the third link, each policy that voids reverses its `PremiumRemittance` if that
    remittance is in `PENDING` or `REMITTED` (moving it to `REVERSED`)".

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth3_commitment_policy_remittance
    """
    agency, order, commitment = setup_order_with_issued_commitment()
    add_title_search(order)
    transition_order(order["id"], "IN_TITLE")
    policy = create_pending_policy(order, commitment, coverage_amount_cents=25_000_000)
    policy = issue_policy(policy)
    remittance = get_policy_remittance(policy)
    # Escrow balance is 0 (no deposits) so cancel from IN_TITLE is permitted.
    cancelled = transition_order(order["id"], "CANCELLED", agency=agency)
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_commitment(commitment["id"], TO))["status"] == "CANCELLED"
    assert validate_success(api.get_policy(policy["id"], UW))["status"] == "VOID"
    assert validate_success(api.get_remittance(remittance["id"], UW))["status"] == "REVERSED"


def test_order_cancel_cascade_voids_commitment_open_exceptions(api):
    """PRD §2.5: "Cancelling a commitment also voids its open exceptions: every child
    `Exception` in `RAISED` or `CURATIVE_PENDING` moves to `VOID`, after which the
    commitment's `open_exception_count` is recomputed."
    The depth-1 link (Order CANCEL -> Commitment CANCELLED) also voids the commitment's
    open exception.

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth3_commitment_policy_remittance
    """
    from test_helpers import add_exception
    agency, order, commitment = setup_order_with_issued_commitment()
    add_title_search(order)
    transition_order(order["id"], "IN_TITLE")
    exception = add_exception(commitment, exception_type="STANDARD", description="Survey exception")
    cancelled = transition_order(order["id"], "CANCELLED", agency=agency)
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_commitment(commitment["id"], TO))["status"] == "CANCELLED"
    assert validate_success(api.get_exception(exception["id"], TO))["status"] == "VOID", (
        "open exception must be voided when its commitment is cancelled in the cascade"
    )


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant: premium conservation on policy void
# ---------------------------------------------------------------------------
def test_premium_conservation_preserved_when_policy_voided(api):
    """PRD §3.8: "A remittance in `PENDING` or `REMITTED` is reversed to `REVERSED` only as
    a system step in the third link of Cascade A when its policy voids; the conservation
    identity that the agency-retained and underwriter-remitted amounts sum to the gross is
    unwound atomically on reversal, so the split never drifts."

    Design: Difficulty/compensating_invariant/premium_conservation_split_then_reverse
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy(
        coverage_amount_cents=25_000_000, remit_split_pct=0.82
    )
    remittance = get_policy_remittance(policy)
    validate_success(api.transition_remittance(remittance["id"], {"to_status": "REMITTED"}, UW))
    validate_success(api.transition_policy(policy["id"], {"to_status": "VOID"}, UW))
    after = validate_success(api.get_remittance(remittance["id"], UW))
    assert after["status"] == "REVERSED", "remittance reverses when policy voids"
    assert after["gross_premium_cents"] == 110000, "gross snapshot unchanged through reversal"
    assert_premium_split_conserves(after)
    assert validate_success(api.get_policy(policy["id"], UW))["status"] == "VOID"


def test_premium_split_halves_unchanged_after_reversal(api):
    """PRD §3.8: "the conservation identity that the agency-retained and underwriter-
    remitted amounts sum to the gross is unwound atomically on reversal, so the split never
    drifts."
    After the policy voids and the remittance reverses, the snapshot halves (90200 / 19800)
    are preserved and still sum to the gross 110000.

    Design: Difficulty/compensating_invariant/premium_conservation_split_then_reverse
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy(
        coverage_amount_cents=25_000_000, remit_split_pct=0.82
    )
    remittance = get_policy_remittance(policy)
    validate_success(api.transition_remittance(remittance["id"], {"to_status": "REMITTED"}, UW))
    validate_success(api.transition_policy(policy["id"], {"to_status": "VOID"}, UW))
    after = validate_success(api.get_remittance(remittance["id"], UW))
    assert after["agency_retained_cents"] == 90200, "agency share preserved through reversal"
    assert after["underwriter_remit_cents"] == 19800, "underwriter share preserved through reversal"


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_complexity_layers: endorsement removed on policy void
# ---------------------------------------------------------------------------
def test_attached_endorsement_removed_on_policy_void(api):
    """PRD §3.6: "When a policy voids, the third link of Cascade A runs: its
    `PremiumRemittance` in `PENDING` or `REMITTED` is reversed to `REVERSED`, and every
    `Endorsement` in `REQUESTED` or `ATTACHED` is removed."

    Design: Corner/cross_cutting_complexity_layers/cascade_endorsement_removed_on_policy_void
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy()
    endorsement = validate_success(
        api.create_endorsement(policy["id"], {"form_code": "SURVEY", "charge_pct": 0.05}, UW),
        expected_status=201,
    )
    validate_success(api.transition_endorsement(endorsement["id"], {"to_status": "ATTACHED"}, UW))
    validate_success(api.transition_policy(policy["id"], {"to_status": "VOID"}, UW))
    after = validate_success(api.get_endorsement(endorsement["id"], UW))
    assert after["status"] == "REMOVED", "attached endorsement must be removed on policy void"


# ---------------------------------------------------------------------------
# Queue B — state_machines: terminal/invalid transitions and reverts
# ---------------------------------------------------------------------------
def test_cancel_completed_title_search_rejected(api):
    """PRD §3.3: "From either `ORDERED` or `IN_EXAM` the search may instead be cancelled to
    `CANCELLED`, which is terminal alongside `COMPLETED`."
    A COMPLETED search has no COMPLETED -> CANCELLED transition.

    Design: Corner/state_machines/cancel_titlesearch_completed_returns_invalid_state
    """
    from test_helpers import create_agency_and_order, complete_title_search
    _agency, order = create_agency_and_order(parcel_id="APN-TSC")
    search = add_title_search(order, searched_parcel_id="APN-TSC")
    search = complete_title_search(search)
    validate_error(
        api.transition_title_search(search["id"], {"to_status": "CANCELLED"}, TO),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert validate_success(api.get_title_search(search["id"], TO))["status"] == "COMPLETED"


def test_reissue_voided_policy_rejected(api):
    """PRD §3.6: "`VOID` is terminal."
    A VOID policy has no VOID -> ISSUED transition.

    Design: Corner/state_machines/void_policy_terminal_lockdown
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy()
    validate_success(api.transition_policy(policy["id"], {"to_status": "VOID"}, UW))
    validate_error(
        api.transition_policy(policy["id"], {"to_status": "ISSUED"}, UW),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    assert validate_success(api.get_policy(policy["id"], UW))["status"] == "VOID"


def test_exception_reverts_from_curative_pending_to_raised(api):
    """PRD §3.5: "If curative fails, the exception reverts from `CURATIVE_PENDING` back to
    `RAISED`."

    Design: Corner/state_machines/exception_curative_pending_revert_to_raised
    """
    _agency, _order, commitment = setup_order_with_issued_commitment()
    exception = validate_success(
        api.create_exception(commitment["id"], {"exception_type": "SPECIAL", "description": "Lis pendens", "curative_required": True}, TO),
        expected_status=201,
    )
    validate_success(api.transition_exception(exception["id"], {"to_status": "CURATIVE_PENDING"}, TO))
    data = validate_success(api.transition_exception(exception["id"], {"to_status": "RAISED"}, TO))
    assert data["status"] == "RAISED", "exception must revert CURATIVE_PENDING -> RAISED"


def test_clear_exception_without_resolved_curative_rejected(api):
    """PRD §3.5: "From `CURATIVE_PENDING` it can be **cleared** to `CLEARED`, but only once
    a `CurativeAction` whose `subject_type` is `EXCEPTION` and whose `subject_id` is this
    exception exists in `RESOLVED` status (otherwise `ERR_NO_RESOLVED_CURATIVE`)."

    Design: Corner/state_machines/exception_clear_without_resolved_curative_rejected
    """
    _agency, _order, commitment = setup_order_with_issued_commitment()
    exception = validate_success(
        api.create_exception(commitment["id"], {"exception_type": "SPECIAL", "description": "Tax lien", "curative_required": True}, TO),
        expected_status=201,
    )
    validate_success(api.transition_exception(exception["id"], {"to_status": "CURATIVE_PENDING"}, TO))
    validate_error(
        api.transition_exception(exception["id"], {"to_status": "CLEARED"}, TO),
        ApiErrorId.ERR_NO_RESOLVED_CURATIVE.value,
    )
    assert validate_success(api.get_exception(exception["id"], TO))["status"] == "CURATIVE_PENDING"


def test_waive_curative_required_exception_rejected(api):
    """PRD §3.5: "It may be **waived** straight to `WAIVED`, but only if `curative_required`
    is false; a curative-required exception cannot be waived and the attempt is rejected
    with `ERR_CURATIVE_REQUIRED`."

    Design: Corner/state_machines/exception_waive_curative_required_rejected
    """
    _agency, _order, commitment = setup_order_with_issued_commitment()
    exception = validate_success(
        api.create_exception(commitment["id"], {"exception_type": "SUBORDINATE_LIEN", "description": "HOA lien", "curative_required": True}, TO),
        expected_status=201,
    )
    validate_error(
        api.transition_exception(exception["id"], {"to_status": "WAIVED"}, TO),
        ApiErrorId.ERR_CURATIVE_REQUIRED.value,
    )
    assert validate_success(api.get_exception(exception["id"], TO))["status"] == "RAISED"


def test_expire_commitment_before_clock_rejected(api):
    """PRD §3.4: "The transition to `EXPIRED` is permitted only once the logical clock has
    reached or passed the commitment's `expiry_date` (otherwise
    `ERR_COMMITMENT_NOT_EXPIRABLE`)."
    Default clock 2026-01-01 is before expiry_date 2026-07-05.

    Design: Corner/state_machines/commitment_expire_before_clock_rejected
    """
    _agency, _order, commitment = setup_order_with_issued_commitment()
    validate_error(
        api.transition_commitment(commitment["id"], {"to_status": "EXPIRED"}, TO),
        ApiErrorId.ERR_COMMITMENT_NOT_EXPIRABLE.value,
    )
    assert validate_success(api.get_commitment(commitment["id"], TO))["status"] == "ISSUED"


def test_expire_commitment_after_clock_voids_open_exceptions(api):
    """PRD §3.4: "on expiry, every child `Exception` in `RAISED` or `CURATIVE_PENDING` is
    voided."
    PRD §3.10: "A title officer or underwriter advances the clock by supplying a
    `to_iso8601` instant."

    Design: Corner/state_machines/commitment_expire_after_clock_voids_open_exceptions
    """
    _agency, _order, commitment = setup_order_with_issued_commitment()
    exception = validate_success(
        api.create_exception(commitment["id"], {"exception_type": "STANDARD", "description": "Mechanics lien possibility"}, TO),
        expected_status=201,
    )
    validate_success(api.set_clock({"to_iso8601": "2026-08-01T00:00:00Z"}, TO))
    data = validate_success(api.transition_commitment(commitment["id"], {"to_status": "EXPIRED"}, TO))
    assert data["status"] == "EXPIRED"
    assert validate_success(api.get_exception(exception["id"], TO))["status"] == "VOID", (
        "open exception must be voided on commitment expiry"
    )


def test_void_policy_with_open_claim_rejected(api):
    """PRD §3.6: "A direct void is blocked while any claim under the policy is in
    `INVESTIGATING` or `CURATIVE` (otherwise `ERR_POLICY_HAS_OPEN_CLAIM`)."

    Design: Corner/state_machines/policy_void_blocked_by_open_claim
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy()
    claim = file_claim(policy, claim_type="ACCESS_DEFECT", estimated_loss_cents=50_000)
    validate_success(api.transition_claim(claim["id"], {"to_status": "INVESTIGATING"}, UW))
    validate_error(
        api.transition_policy(policy["id"], {"to_status": "VOID"}, UW),
        ApiErrorId.ERR_POLICY_HAS_OPEN_CLAIM.value,
    )
    assert validate_success(api.get_policy(policy["id"], UW))["status"] == "ISSUED"


def test_order_committed_requires_chain_verified_search(api):
    """PRD §3.2: "the order must have a `Commitment` in `ISSUED` (otherwise
    `ERR_NO_ISSUED_COMMITMENT`), and it must have a `TitleSearch` in `COMPLETED` whose
    `chain_verified` is true (otherwise `ERR_CHAIN_NOT_VERIFIED`)."
    Commitment is ISSUED but the search is still ORDERED.

    Design: Corner/state_machines/order_committed_requires_chain_verified
    """
    _agency, order, _commitment = setup_order_with_issued_commitment()
    add_title_search(order)
    transition_order(order["id"], "IN_TITLE")
    validate_error(
        api.transition_order(order["id"], {"to_status": "COMMITTED"}, TO),
        ApiErrorId.ERR_CHAIN_NOT_VERIFIED.value,
    )
    assert get_order(order["id"])["status"] == "IN_TITLE"


def test_reissue_create_flips_prior_to_updated_new_in_draft(api):
    """PRD §3.4: "the prior `ISSUED` commitment flips to `UPDATED`, its `revision_no` is
    incremented by 1, and the order's `version` is incremented by 1".
    PRD §3.4: "A commitment is born in `DRAFT`".

    Design: Corner/state_machines/reissue_create_flips_prior_to_updated_and_increments_revision
    """
    _agency, order, c1 = setup_order_with_issued_commitment()
    fresh = get_order(order["id"])
    c2 = validate_success(
        api.create_commitment(
            order["id"],
            {
                "effective_date": "2026-02-05T00:00:00Z", "expiry_date": "2026-08-05T00:00:00Z",
                "schedule_a_estate": "FEE_SIMPLE", "insured_amount_cents": 25_000_000,
                "expected_order_version": fresh["version"],
            },
            TO,
        ),
        expected_status=201,
    )
    assert c2["status"] == "DRAFT", "new re-issue commitment is created in DRAFT"
    c1_after = validate_success(api.get_commitment(c1["id"], TO))
    assert c1_after["status"] == "UPDATED"
    assert c1_after["revision_no"] == 1


def test_filed_claim_starts_in_fnol(api):
    """PRD §3.9: "A claim opens in `FNOL` with `version` 1, and exposes a computed
    `reserve_cents`, a `settled_loss_cents` that defaults to 0 until settlement, and a
    computed `paid_cents`."

    Design: Corner/state_machines/claim_initial_state_is_fnol
    """
    _agency, _order, _commitment, policy = setup_issued_owner_policy()
    data = validate_success(
        api.create_claim(policy["id"], {"claim_type": "UNDISCLOSED_LIEN", "estimated_loss_cents": 30_000}, UW),
        expected_status=201,
    )
    assert data["status"] == "FNOL", "newly filed claim must start in FNOL"
    assert data["version"] == 1, "claim version starts at 1"
