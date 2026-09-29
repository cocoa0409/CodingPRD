"""Multi-hop cascades on the Move Concierge API.

A cascade is an ordered sequence of hops in which the first hop mutates the
addressed resource and each subsequent hop is caused by the hop above it.
The three roots exercised here are consent revocation (which cascades down
from a consent record to a credit-check handoff), duplicate resolution by
merge (which cascades down from a move driven terminal), and a declined
bureau response (which bubbles up from a handoff to its parent move).
"""

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_duplicate_score,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_readiness_breakdown,
    assert_version_bumped,
    assert_window_released,
)
from test_helpers.test_users import make_move_ops_headers
from test_helpers.types import (
    BlockedReason,
    ConsentGate,
    ConsentScope,
    ConsentState,
    CreditResult,
    CreditStatus,
    DuplicateFlag,
    HandoffStatus,
    MoveLifecycleStatus,
    OrderCancellationReason,
    OrderFailureReason,
    ProvisionStatus,
    ReadinessVariant,
    UtilityType,
)


# ---------------------------------------------------------------------------
# Shared preconditions, built only through declared endpoints
# ---------------------------------------------------------------------------
def _move_with_open_credit_handoff(api):
    """A SCHEDULING move with one DRAFT/PENDING_CHECK order and an open handoff.

    The resident holds a single GRANTED UTILITY_SETUP consent, so the consent
    component of readiness covers exactly one of the two gate scopes.
    """
    network = fx.build_network(api)
    consent = fx.grant_consent(
        api, network["resident"]["id"], ConsentScope.UTILITY_SETUP.value, 1
    )
    move = fx.ingest_move(api, network, move_date="2026-08-20")
    fx.pass_identity_by_kba(api, move["id"])
    move = fx.run_mapping(api, move["id"], utility_types=[UtilityType.ELECTRIC.value])
    order = fx.order_of_type(api, move["id"], UtilityType.ELECTRIC.value)
    handoff = fx.dispatch_credit_check(api, order["id"])
    return {
        "network": network,
        "consent": consent,
        "move": move,
        "order": order,
        "handoff": handoff,
    }


# ---------------------------------------------------------------------------
# Consent revocation: a four-hop chain from consent record to handoff
# ---------------------------------------------------------------------------
def test_01_consent_revocation_flips_the_gate_and_parks_the_move(api, compliance_headers):
    """Revoking a UTILITY_SETUP consent blocks the gate and parks the move.

    PRD: "The first hop writes `revoked_at` with the logical-clock instant and stores `revocation_reason`, moving `state` from `GRANTED` to `REVOKED`"

    Design: Difficulty/transitive_cascade/consent_revocation_four_hop_cascade
    """
    built = _move_with_open_credit_handoff(api)
    assert_move_state(built["move"], lifecycle_status=MoveLifecycleStatus.SCHEDULING.value)

    revoked = assert_ok(
        api.revoke_consent(
            built["consent"]["id"],
            f.revocation_payload("Resident withdrew utility data sharing"),
            compliance_headers,
        )
    )

    assert revoked["state"] == ConsentState.REVOKED.value, (
        f"expected state REVOKED, got {revoked['state']}"
    )
    assert revoked["revoked_at"] is not None, "revoked_at must carry the logical-clock instant"
    assert revoked["revoked_at"].startswith("2026-08-01T00:00:00"), (
        f"revoked_at must be the logical-clock instant, got {revoked['revoked_at']}"
    )
    assert revoked["revocation_reason"] == "Resident withdrew utility data sharing", (
        "the revocation reason must be stored on the consent record"
    )

    move = fx.read_move(api, built["move"]["id"])
    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.ATTENTION_REQUIRED.value,
        consent_gate=ConsentGate.BLOCKED.value,
        blocked_reason=BlockedReason.CONSENT_REVOKED.value,
    )


def test_02_consent_revocation_suspends_the_open_service_order(api, compliance_headers):
    """The gate flip suspends the move's open service order and frees its window.

    PRD: "moves every service order of those moves whose `provision_status` is `DRAFT`, `SCHEDULED` or `ACTIVE_SERVICE` to `SUSPENDED`"

    Design: Difficulty/transitive_cascade/consent_revocation_four_hop_cascade
    """
    built = _move_with_open_credit_handoff(api)
    assert_order_dimensions(
        built["order"],
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.PENDING_CHECK.value,
    )

    assert_ok(
        api.revoke_consent(
            built["consent"]["id"], f.revocation_payload(), compliance_headers
        )
    )

    order = fx.read_order(api, built["order"]["id"])
    assert_order_dimensions(order, provision_status=ProvisionStatus.SUSPENDED.value)
    assert_window_released(order)


def test_03_consent_revocation_voids_the_credit_exposure_and_the_handoff(api, compliance_headers):
    """Each suspension voids the order's credit dimension and its open handoff.

    PRD: "moves that order's `credit_status` from `PENDING_CHECK` or `DEPOSIT_DUE` to `VOIDED` and moves its credit-check handoff to `VOIDED` as well"

    Design: Difficulty/transitive_cascade/consent_revocation_four_hop_cascade
    """
    built = _move_with_open_credit_handoff(api)
    assert built["handoff"]["handoff_status"] == HandoffStatus.SUBMITTED.value, (
        "the handoff must start out open for the fourth hop to have anything to void"
    )

    assert_ok(
        api.revoke_consent(
            built["consent"]["id"], f.revocation_payload(), compliance_headers
        )
    )

    order = fx.read_order(api, built["order"]["id"])
    assert_order_dimensions(order, credit_status=CreditStatus.VOIDED.value)

    handoff = assert_ok(
        api.get_credit_check_handoff(built["handoff"]["id"], compliance_headers)
    )
    assert handoff["handoff_status"] == HandoffStatus.VOIDED.value, (
        f"expected handoff_status VOIDED, got {handoff['handoff_status']}"
    )
    assert handoff["score"] is None, "a voided handoff never received a bureau score"


def test_04_consent_revocation_zeroes_the_consent_component_of_readiness(api, compliance_headers):
    """A blocked gate drives the consent component, and the score, straight to zero.

    PRD: "The `consent_component` is 0 outright whenever `consent_gate` is `BLOCKED`"

    Design: Difficulty/transitive_cascade/consent_revocation_four_hop_cascade
    """
    built = _move_with_open_credit_handoff(api)

    assert_ok(
        api.revoke_consent(
            built["consent"]["id"], f.revocation_payload(), compliance_headers
        )
    )

    move = fx.read_move(api, built["move"]["id"])
    assert_move_state(move, readiness_score=30)

    breakdown = fx.read_readiness(api, built["move"]["id"])
    assert_readiness_breakdown(
        breakdown,
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=0,
        filing_component=0,
        consent_component=0,
        readiness_score=30,
    )


# ---------------------------------------------------------------------------
# Duplicate merge: a three-hop chain from a terminal move down to its handoff
# ---------------------------------------------------------------------------
def _ingest_move_to(api, network, destination_address_id, move_date, resident_id=None):
    """Ingest a move for the built network against a nominated destination."""
    payload = f.move_payload(
        resident_id or network["resident"]["id"],
        network["feed_source"]["id"],
        network["origin_address"]["id"],
        destination_address_id,
        move_date=move_date,
    )
    return assert_created(api.create_move(payload, make_move_ops_headers()))


def _duplicate_ready_to_merge(api):
    """A dismissed near-duplicate carrying one open order and one open handoff.

    The second move shares the resident and the destination postal code of the
    first, 15 days apart inside the feed's 30-day dedupe window, so it is
    ingested as a suspected duplicate; the suspicion is dismissed so the move
    can accumulate the children a later merge has to unwind.  The clock is
    advanced between the two ingestions because a candidate's `created_at`
    must be strictly earlier than the new move's.
    """
    network = fx.build_network(api)
    consent = fx.grant_consent(
        api, network["resident"]["id"], ConsentScope.UTILITY_SETUP.value, 1
    )
    survivor = fx.ingest_move(api, network, move_date="2026-08-20")
    near_destination = fx.create_destination_address(api, line1="915 Juniper St")
    fx.set_clock(api, "2026-08-01T01:00:00Z")
    duplicate = _ingest_move_to(api, network, near_destination["id"], "2026-09-04")

    assert_ok(
        api.resolve_duplicate(
            duplicate["id"],
            f.dismiss_payload(duplicate["version"]),
            make_move_ops_headers(),
        )
    )
    fx.pass_identity_by_kba(api, duplicate["id"])
    fx.run_mapping(api, duplicate["id"], utility_types=[UtilityType.ELECTRIC.value])
    order = fx.order_of_type(api, duplicate["id"], UtilityType.ELECTRIC.value)
    handoff = fx.dispatch_credit_check(api, order["id"])
    return {
        "network": network,
        "consent": consent,
        "survivor": survivor,
        "as_ingested": duplicate,
        "order": order,
        "handoff": handoff,
    }


def test_05_merge_drives_the_duplicate_move_into_the_terminal_state(api, ops_headers):
    """A MERGE_INTO resolution folds the move into its survivor and ends its life.

    PRD: "the first hop sets `duplicate_flag` to `CONFIRMED_DUPLICATE`, writes `duplicate_of_move_id` with the survivor's identifier, drives `lifecycle_status` to the terminal `DUPLICATE_MERGED`, and increments `version` by one"

    Design: Difficulty/transitive_cascade/duplicate_merge_three_hop_cascade
    """
    built = _duplicate_ready_to_merge(api)
    assert_duplicate_score(built["as_ingested"], 0.80)
    assert_move_state(
        built["as_ingested"],
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.SUSPECTED.value,
        blocked_reason=BlockedReason.DUPLICATE_SUSPECTED.value,
    )
    assert built["as_ingested"]["duplicate_candidate_move_id"] == built["survivor"]["id"], (
        "the near-miss pointer must name the earlier move that was scored"
    )

    before = fx.read_move(api, built["as_ingested"]["id"])
    merged = assert_ok(
        api.resolve_duplicate(
            before["id"],
            f.merge_payload(before["version"], built["survivor"]["id"]),
            ops_headers,
        )
    )

    assert_move_state(
        merged,
        lifecycle_status=MoveLifecycleStatus.DUPLICATE_MERGED.value,
        duplicate_flag=DuplicateFlag.CONFIRMED_DUPLICATE.value,
    )
    assert merged["duplicate_of_move_id"] == built["survivor"]["id"], (
        f"expected duplicate_of_move_id {built['survivor']['id']}, "
        f"got {merged['duplicate_of_move_id']}"
    )
    assert_version_bumped(before, merged, by=1)


def test_06_merge_cancels_the_duplicate_orders_and_releases_their_windows(api, ops_headers):
    """The terminal move's open service order is cancelled and its window freed.

    PRD: "moves to `CANCELLED` with `cancellation_reason` set to `DUPLICATE_MERGED` and both `scheduled_window_start` and `scheduled_window_end` cleared, releasing any occupancy window it held"

    Design: Difficulty/transitive_cascade/duplicate_merge_three_hop_cascade
    """
    built = _duplicate_ready_to_merge(api)
    move = fx.read_move(api, built["as_ingested"]["id"])

    assert_ok(
        api.resolve_duplicate(
            move["id"],
            f.merge_payload(move["version"], built["survivor"]["id"]),
            ops_headers,
        )
    )

    order = fx.read_order(api, built["order"]["id"])
    assert_order_dimensions(order, provision_status=ProvisionStatus.CANCELLED.value)
    assert order["cancellation_reason"] == OrderCancellationReason.DUPLICATE_MERGED.value, (
        f"expected cancellation_reason DUPLICATE_MERGED, got {order['cancellation_reason']}"
    )
    assert_window_released(order)


def test_07_merge_voids_the_credit_exposure_and_spares_the_survivor(api, ops_headers, compliance_headers):
    """Cancelling the order voids its credit exposure and handoff; the survivor lives on.

    PRD: "Each such cancelled order whose `credit_status` was `PENDING_CHECK` or `DEPOSIT_DUE` then moves to `VOIDED`, and that order's credit-check handoff in `SUBMITTED` or `RESPONDED` moves to `VOIDED` alongside it"

    Design: Difficulty/transitive_cascade/duplicate_merge_three_hop_cascade
    """
    built = _duplicate_ready_to_merge(api)
    move = fx.read_move(api, built["as_ingested"]["id"])

    assert_ok(
        api.resolve_duplicate(
            move["id"],
            f.merge_payload(move["version"], built["survivor"]["id"]),
            ops_headers,
        )
    )

    order = fx.read_order(api, built["order"]["id"])
    assert_order_dimensions(order, credit_status=CreditStatus.VOIDED.value)

    handoff = assert_ok(
        api.get_credit_check_handoff(built["handoff"]["id"], compliance_headers)
    )
    assert handoff["handoff_status"] == HandoffStatus.VOIDED.value, (
        f"expected handoff_status VOIDED, got {handoff['handoff_status']}"
    )

    survivor = fx.read_move(api, built["survivor"]["id"])
    assert_move_state(
        survivor,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
    )


# ---------------------------------------------------------------------------
# Declined bureau score: a three-hop chain bubbling up from handoff to move
# ---------------------------------------------------------------------------
def test_08_declined_bureau_response_is_recorded_on_the_handoff(api, compliance_headers):
    """The bureau's answer closes the handoff and derives a DECLINED result.

    PRD: "The response writes `score`, sets `responded_at` to the current instant, moves `handoff_status` from `SUBMITTED` to `RESPONDED`, and derives `result` from the score using two thresholds"

    Design: Difficulty/transitive_cascade/credit_declined_three_hop_bubble_up
    """
    built = _move_with_open_credit_handoff(api)

    answered = fx.answer_bureau(api, built["handoff"]["id"], 550)

    assert answered["handoff_status"] == HandoffStatus.RESPONDED.value, (
        f"expected handoff_status RESPONDED, got {answered['handoff_status']}"
    )
    assert answered["score"] == 550, f"expected score 550, got {answered['score']}"
    assert answered["result"] == CreditResult.DECLINED.value, (
        f"a score of 579 or below is a DECLINED result, got {answered['result']}"
    )
    assert answered["responded_at"] is not None, "responded_at must carry the answer instant"


def test_09_declined_score_fails_the_order_and_parks_the_parent_move(api):
    """The declined result fails the order and bubbles the parking up to the move.

    PRD: "A `DECLINED` result moves `credit_status` to `DECLINED`, leaves `deposit_amount_cents` at 0, and triggers a two-hop cascade: the order's `provision_status` moves from `DRAFT` to `PROVISION_FAILED` with `failure_reason` recorded as `CREDIT_DECLINED`, and then the parent move moves from `SCHEDULING` to `ATTENTION_REQUIRED` with `blocked_reason` set to `CREDIT_DECLINED`"

    Design: Difficulty/transitive_cascade/credit_declined_three_hop_bubble_up
    """
    built = _move_with_open_credit_handoff(api)

    fx.answer_bureau(api, built["handoff"]["id"], 550)

    order = fx.read_order(api, built["order"]["id"])
    assert_order_dimensions(
        order,
        provision_status=ProvisionStatus.PROVISION_FAILED.value,
        credit_status=CreditStatus.DECLINED.value,
    )
    assert order["failure_reason"] == OrderFailureReason.CREDIT_DECLINED.value, (
        f"expected failure_reason CREDIT_DECLINED, got {order['failure_reason']}"
    )
    assert_cents(order, "deposit_amount_cents", 0)

    move = fx.read_move(api, built["move"]["id"])
    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.ATTENTION_REQUIRED.value,
        consent_gate=ConsentGate.OPEN.value,
        blocked_reason=BlockedReason.CREDIT_DECLINED.value,
        readiness_score=40,
    )


def test_10_parking_cannot_be_cleared_while_the_declined_order_has_no_replacement(api, ops_headers):
    """The bubbled-up parking survives a clearance that has no remedy to show.

    PRD: "A clearance attempted while a failed or declined order still has no replacement is refused with `ERR_UNRESOLVED_PROVISION_FAILURE`"

    Design: Difficulty/transitive_cascade/credit_declined_three_hop_bubble_up
    """
    built = _move_with_open_credit_handoff(api)
    fx.answer_bureau(api, built["handoff"]["id"], 550)

    response = api.clear_attention(built["move"]["id"], f.clearance_payload(), ops_headers)

    assert_error(response, ApiErrorId.UNRESOLVED_PROVISION_FAILURE)
    move = fx.read_move(api, built["move"]["id"])
    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.ATTENTION_REQUIRED.value,
        blocked_reason=BlockedReason.CREDIT_DECLINED.value,
    )
