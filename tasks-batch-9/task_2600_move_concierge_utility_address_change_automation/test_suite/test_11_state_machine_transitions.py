"""Lifecycle transitions: initial states, legal hops, refused hops and side effects.

Each test drives one resource from a known state through exactly one
transition and then re-reads every row the transition was supposed to touch —
the move, its verification, its service order, its handoff, its filing or its
consent record — so that a hop which fires the wrong side effect, or which
fires none at all, is visible.  The logical clock is set explicitly whenever a
transition is gated on a date or an instant.
"""

import pytest

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_created,
    assert_duplicate_score,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_page,
    assert_versioned_resource,
    assert_window_retained,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.test_users import make_provider_agent_headers
from test_helpers.types import (
    BlockedReason,
    BureauName,
    ConsentGate,
    ConsentScope,
    ConsentSourceChannel,
    ConsentState,
    CreditResult,
    CreditStatus,
    DuplicateFlag,
    FilingStatus,
    HandoffStatus,
    KbaOutcome,
    MoveLifecycleStatus,
    ProvisionStatus,
    UtilityType,
    VerificationMethod,
    VerificationStatus,
)


@pytest.fixture()
def in_service_move(api, ops_headers):
    """A move whose single water order is live and whose postal filing is confirmed.

    Built entirely through declared endpoints: consents, a KBA pass, provider
    mapping restricted to water, a committed service window, a confirmed
    postal filing and finally the provider's activation, which is the last
    qualifying child mutation and bubbles the move up to `IN_SERVICE`.
    """
    bundle = fixtures.mapped_move(
        api,
        move_date="2026-08-10",
        utility_types=[UtilityType.WATER.value],
        scopes=[ConsentScope.UTILITY_SETUP.value, ConsentScope.USPS_FILING.value],
    )
    order = bundle["orders_by_type"][UtilityType.WATER.value]
    fixtures.schedule_order(api, order["id"], requested_service_date="2026-08-05")
    bundle = fixtures.confirmed_filing(api, bundle=bundle, forward_start_date="2026-08-10")

    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    activated = assert_ok(
        api.activate_order(
            order["id"],
            factories.activation_payload(confirmation_code="AWB-77120"),
            make_provider_agent_headers(order["provider_id"]),
        )
    )
    return {**bundle, "order": activated, "move": fixtures.read_move(api, bundle["move"]["id"])}


def test_01_fresh_move_starts_in_intake_with_zero_counters(api, ops_headers):
    """Ingestion lands in the initial state with every counter and derived field at rest.

    PRD: "`consent_gate` is `BLOCKED` when any consent record linked to that move
    whose `scope` is `UTILITY_SETUP` or `USPS_FILING` is in `state` `REVOKED` or
    `EXPIRED`, and `OPEN` otherwise"

    Design: Corner/state_machines/initial_state_move_starts_in_intake_with_zero_counters
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)

    move = assert_created(
        api.create_move(
            factories.move_payload(
                network["resident"]["id"],
                network["feed_source"]["id"],
                network["origin_address"]["id"],
                network["destination_address"]["id"],
                move_date="2026-08-20",
            ),
            ops_headers,
        )
    )

    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.INTAKE.value,
        duplicate_flag=DuplicateFlag.NONE.value,
        consent_gate=ConsentGate.OPEN.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=0,
    )
    assert move["identity_attempt_count"] == 0, "no identity attempt exists yet"
    assert move["mapped_order_count"] == 0, "no service order exists yet"
    assert move["verified_at"] is None, "identity has not been cleared"
    assert move["duplicate_of_move_id"] is None, "the move is nobody's duplicate"
    assert_duplicate_score(move, 0.00)
    assert_versioned_resource(move, expected_version=1)

    assert_page(
        api.list_consent_records(ops_headers, resident_id=network["resident"]["id"]),
        total_count=0,
        has_more=False,
    )


def test_02_kba_attempt_opens_pending_and_moves_the_move_to_identity_pending(
    api, ops_headers
):
    """Opening the vendor attempt numbers it 1, gives it 72 hours, and advances the move.

    PRD: "The new row lands in `status` `PENDING` with `expires_at` set to the
    creation instant plus 72 hours"

    Design: Corner/state_machines/valid_transition_kba_pass_moves_verification_and_move_forward
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    move = fixtures.ingest_move(api, network, move_date="2026-08-20")

    verification = assert_created(
        api.create_identity_verification(move["id"], factories.kba_attempt_payload(), ops_headers)
    )

    assert verification["move_id"] == move["id"], "move_id is copied down from the move"
    assert verification["resident_id"] == network["resident"]["id"], "resident_id is copied down"
    assert verification["method"] == VerificationMethod.KBA.value, "the method must be KBA"
    assert verification["status"] == VerificationStatus.PENDING.value, (
        f"a fresh KBA attempt is PENDING, got {verification['status']}"
    )
    assert verification["attempt_no"] == 1, f"the first attempt is number 1, got {verification['attempt_no']}"
    assert verification["expires_at"].startswith("2026-08-04T00:00:00"), (
        f"72 hours after 2026-08-01T00:00:00Z is 2026-08-04T00:00:00Z, got {verification['expires_at']}"
    )
    assert verification["kba_score"] is None, "no score has arrived yet"
    assert verification["decided_at"] is None, "nothing has been decided yet"
    assert verification["reviewer_user_id"] is None, "a KBA attempt carries no reviewer"

    after = fixtures.read_move(api, move["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.IDENTITY_PENDING.value,
        readiness_score=0,
    )
    assert after["identity_attempt_count"] == 1, "opening an attempt increments the counter by one"
    assert after["verified_at"] is None, "a pending attempt verifies nothing"


def test_03_kba_pass_verifies_the_move_and_stamps_verified_at(api, ops_headers, gateway_headers):
    """A vendor answer of PASSED at 720 decides the row and carries the move to VERIFIED.

    PRD: "A pass sets the move's `verified_at` to that same instant and advances
    `lifecycle_status` from `IDENTITY_PENDING` to `VERIFIED`"

    Design: Corner/state_machines/valid_transition_kba_pass_moves_verification_and_move_forward
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    move = fixtures.ingest_move(api, network, move_date="2026-08-20")
    verification = assert_created(
        api.create_identity_verification(move["id"], factories.kba_attempt_payload(), ops_headers)
    )

    decided = assert_ok(
        api.post_kba_result(
            verification["id"],
            factories.kba_result_payload(outcome=KbaOutcome.PASSED.value, score=720),
            gateway_headers,
        )
    )

    assert decided["status"] == VerificationStatus.PASSED.value, (
        f"an outcome of PASSED at 720 clears the bar of 700, got {decided['status']}"
    )
    assert decided["kba_score"] == 720, f"the supplied score is written, got {decided['kba_score']}"
    assert decided["decided_at"].startswith("2026-08-01T00:00:00"), (
        f"decided_at is the logical-clock instant, got {decided['decided_at']}"
    )

    after = fixtures.read_move(api, move["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        readiness_score=30,
    )
    assert after["verified_at"].startswith("2026-08-01T00:00:00"), (
        f"verified_at is stamped with the same instant, got {after['verified_at']}"
    )
    assert after["identity_attempt_count"] == 1, "deciding an attempt does not open another"


def test_04_replayed_kba_result_on_decided_verification_is_rejected(
    api, ops_headers, gateway_headers
):
    """A second vendor callback against an already-passed row is refused and changes nothing.

    PRD: "a `PASSED`, `FAILED` or `EXPIRED` row cannot receive a result and the
    callback is refused with `ERR_VERIFICATION_ALREADY_DECIDED`"

    Design: Corner/state_machines/invalid_transitions_kba_result_on_decided_verification_rejected
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    move = fixtures.ingest_move(api, network, move_date="2026-08-20")
    decided = fixtures.pass_identity_by_kba(api, move["id"], score=720)

    replay = api.post_kba_result(
        decided["id"],
        factories.kba_result_payload(outcome=KbaOutcome.FAILED.value, score=310),
        gateway_headers,
    )
    assert_error(replay, ApiErrorId.VERIFICATION_ALREADY_DECIDED)

    reread = assert_ok(api.get_identity_verification(decided["id"], ops_headers))
    assert reread["status"] == VerificationStatus.PASSED.value, (
        "the refused replay must not undo the pass"
    )
    assert reread["kba_score"] == 720, "the refused replay must not overwrite the score"
    assert reread["decided_at"] == decided["decided_at"], (
        "the refused replay must not re-stamp decided_at"
    )

    after = fixtures.read_move(api, move["id"])
    assert_move_state(after, lifecycle_status=MoveLifecycleStatus.VERIFIED.value)
    assert after["identity_attempt_count"] == 1, "a refused callback opens no new attempt"


def test_05_second_revocation_of_a_revoked_consent_is_rejected(api, compliance_headers):
    """Replaying the withdrawal a day later is refused and the first revocation stands.

    PRD: "Only a `GRANTED` record may be revoked; a `SUPERSEDED`, `REVOKED` or
    `EXPIRED` record is refused with `ERR_CONSENT_ALREADY_TERMINAL`."

    Design: Corner/state_machines/idempotency_second_revocation_of_revoked_consent_rejected
    """
    fixtures.set_clock(api, CLOCK_STARTUP_DEFAULT)
    resident = fixtures.create_resident(api)
    consent = fixtures.grant_consent(
        api,
        resident["id"],
        ConsentScope.UTILITY_SETUP.value,
        1,
        source_channel=ConsentSourceChannel.WEB_PORTAL.value,
        consent_text_version="v3",
    )
    assert consent["state"] == ConsentState.GRANTED.value, "a fresh consent is GRANTED"

    fixtures.set_clock(api, "2026-08-02T00:00:00Z")
    revoked = assert_ok(
        api.revoke_consent(
            consent["id"],
            factories.revocation_payload(revocation_reason="Resident phoned to withdraw"),
            compliance_headers,
        )
    )
    assert revoked["state"] == ConsentState.REVOKED.value, (
        f"the first hop moves the record to REVOKED, got {revoked['state']}"
    )
    assert revoked["revoked_at"].startswith("2026-08-02T00:00:00"), (
        f"revoked_at is the logical-clock instant, got {revoked['revoked_at']}"
    )
    assert revoked["revocation_reason"] == "Resident phoned to withdraw", "the reason must be stored"

    fixtures.set_clock(api, "2026-08-03T00:00:00Z")
    replay = api.revoke_consent(
        consent["id"],
        factories.revocation_payload(revocation_reason="Duplicate withdrawal request"),
        compliance_headers,
    )
    assert_error(replay, ApiErrorId.CONSENT_ALREADY_TERMINAL)

    reread = assert_ok(api.get_consent_record(consent["id"], compliance_headers))
    assert reread["state"] == ConsentState.REVOKED.value, "the record stays REVOKED"
    assert reread["revoked_at"].startswith("2026-08-02T00:00:00"), (
        "the refused replay must not re-stamp revoked_at to the later instant"
    )
    assert reread["revocation_reason"] == "Resident phoned to withdraw", (
        "the refused replay must not overwrite the original reason"
    )


def test_06_third_identity_attempt_exhausts_the_cap(api, ops_headers, gateway_headers):
    """Three failed vendor attempts number 1, 2 and 3, and the fourth is refused outright.

    PRD: "Before a new attempt is opened the move's `identity_attempt_count` must
    be strictly below 3, and a fourth attempt is refused with
    `ERR_VERIFICATION_ATTEMPTS_EXHAUSTED`."

    Design: Corner/state_machines/side_effect_execution_third_identity_attempt_exhausts_the_cap
    """
    network = fixtures.build_network(api, clock=CLOCK_STARTUP_DEFAULT)
    move = fixtures.ingest_move(api, network, move_date="2026-08-20")

    for expected_attempt, score in ((1, 310), (2, 320), (3, 330)):
        attempt = assert_created(
            api.create_identity_verification(
                move["id"], factories.kba_attempt_payload(), ops_headers
            )
        )
        assert attempt["attempt_no"] == expected_attempt, (
            f"expected attempt_no {expected_attempt}, got {attempt['attempt_no']}"
        )
        decided = assert_ok(
            api.post_kba_result(
                attempt["id"],
                factories.kba_result_payload(outcome=KbaOutcome.FAILED.value, score=score),
                gateway_headers,
            )
        )
        assert decided["status"] == VerificationStatus.FAILED.value, (
            f"a FAILED outcome decides the row as FAILED, got {decided['status']}"
        )
        assert decided["kba_score"] == score, "the supplied score is written even on a failure"
        interim = fixtures.read_move(api, move["id"])
        assert interim["identity_attempt_count"] == expected_attempt, (
            "every opened attempt increments the counter by exactly one"
        )

    exhausted = fixtures.read_move(api, move["id"])
    assert_move_state(
        exhausted,
        lifecycle_status=MoveLifecycleStatus.IDENTITY_FAILED.value,
        readiness_score=0,
    )

    fourth = api.create_identity_verification(
        move["id"], factories.kba_attempt_payload(), ops_headers
    )
    assert_error(fourth, ApiErrorId.VERIFICATION_ATTEMPTS_EXHAUSTED)

    after = fixtures.read_move(api, move["id"])
    assert after["identity_attempt_count"] == 3, "a refused attempt consumes nothing"
    assert_move_state(after, lifecycle_status=MoveLifecycleStatus.IDENTITY_FAILED.value)
    assert_page(
        api.list_identity_verifications(ops_headers, move_id=move["id"]),
        total_count=3,
        has_more=False,
    )


def test_07_cancelled_move_rejects_every_further_write(api, ops_headers):
    """Once cancelled, filing, verification, mapping and a repeat cancellation are all refused.

    PRD: "The addressed move's `lifecycle_status` permits the requested operation
    — otherwise `ERR_MOVE_NOT_ACTIONABLE` (409)."

    Design: Corner/state_machines/terminal_state_lockdown_cancelled_move_rejects_further_writes
    """
    bundle = fixtures.verified_move(api, move_date="2026-08-20")
    move_id = bundle["move"]["id"]

    cancelled = assert_ok(
        api.cancel_move(
            move_id, factories.cancellation_payload(cancellation_reason="Lease fell through"), ops_headers
        )
    )
    assert cancelled["lifecycle_status"] == MoveLifecycleStatus.CANCELLED.value, (
        f"cancellation is available from VERIFIED, got {cancelled['lifecycle_status']}"
    )

    assert_error(
        api.create_filing(
            move_id, factories.filing_payload(forward_start_date="2026-08-20"), ops_headers
        ),
        ApiErrorId.MOVE_NOT_ACTIONABLE,
    )
    assert_error(
        api.create_identity_verification(move_id, factories.kba_attempt_payload(), ops_headers),
        ApiErrorId.MOVE_NOT_ACTIONABLE,
    )
    assert_error(
        api.run_provider_mapping(
            move_id,
            factories.mapping_payload([UtilityType.ELECTRIC.value, UtilityType.WATER.value]),
            ops_headers,
        ),
        ApiErrorId.MOVE_NOT_ACTIONABLE,
    )
    assert_error(
        api.cancel_move(
            move_id, factories.cancellation_payload(cancellation_reason="Cancelled again"), ops_headers
        ),
        ApiErrorId.MOVE_NOT_ACTIONABLE,
    )

    after = fixtures.read_move(api, move_id)
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.CANCELLED.value,
        blocked_reason=BlockedReason.NONE.value,
    )
    assert after["identity_attempt_count"] == 1, "the refused verification opened no attempt"
    assert after["mapped_order_count"] == 0, "the refused mapping created no service order"
    assert_page(api.list_filings(ops_headers, move_id=move_id), total_count=0, has_more=False)


def test_08_activation_before_the_window_opens_is_rejected(api, ops_headers):
    """The provider cannot declare service live before the committed window starts.

    PRD: "the logical clock must have reached or passed `scheduled_window_start`,
    an earlier attempt being refused with `ERR_ACTIVATION_TOO_EARLY`"

    Design: Corner/state_machines/precondition_enforcement_activation_before_window_start_rejected
    """
    bundle = fixtures.mapped_move(
        api,
        utility_types=[UtilityType.WATER.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.WATER.value]
    scheduled = fixtures.schedule_order(api, order["id"], requested_service_date="2026-08-05")
    assert scheduled["scheduled_window_start"].startswith("2026-08-05T09:00:00"), (
        f"the window opens at 09:00 on the service date, got {scheduled['scheduled_window_start']}"
    )
    provider_headers = make_provider_agent_headers(order["provider_id"])

    assert_error(
        api.activate_order(
            order["id"],
            factories.activation_payload(confirmation_code="AWB-77120"),
            provider_headers,
        ),
        ApiErrorId.ACTIVATION_TOO_EARLY,
    )

    fixtures.set_clock(api, "2026-08-05T08:59:59Z")
    assert_error(
        api.activate_order(
            order["id"],
            factories.activation_payload(confirmation_code="AWB-77120"),
            provider_headers,
        ),
        ApiErrorId.ACTIVATION_TOO_EARLY,
    )

    still_scheduled = fixtures.read_order(api, order["id"])
    assert_order_dimensions(
        still_scheduled,
        provision_status=ProvisionStatus.SCHEDULED.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )
    assert still_scheduled["confirmation_code"] is None, (
        "a refused activation must not record a confirmation code"
    )


def test_09_activation_exactly_at_window_start_goes_live(api, ops_headers):
    """One second later, at the window start itself, the same activation succeeds.

    PRD: "the logical clock must have reached or passed `scheduled_window_start`,
    an earlier attempt being refused with `ERR_ACTIVATION_TOO_EARLY`"

    Design: Corner/state_machines/precondition_enforcement_activation_before_window_start_rejected
    """
    bundle = fixtures.mapped_move(
        api,
        utility_types=[UtilityType.WATER.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.WATER.value]
    fixtures.schedule_order(api, order["id"], requested_service_date="2026-08-05")
    provider_headers = make_provider_agent_headers(order["provider_id"])

    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    activated = assert_ok(
        api.activate_order(
            order["id"],
            factories.activation_payload(confirmation_code="AWB-77120"),
            provider_headers,
        )
    )

    assert_order_dimensions(
        activated,
        provision_status=ProvisionStatus.ACTIVE_SERVICE.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )
    assert activated["confirmation_code"] == "AWB-77120", (
        f"the provider's confirmation code is stored, got {activated['confirmation_code']}"
    )
    assert_window_retained(activated)
    assert activated["scheduled_window_start"].startswith("2026-08-05T09:00:00"), (
        "the committed window is unchanged by activation"
    )


def test_10_replayed_bureau_response_on_a_responded_handoff_is_rejected(
    api, ops_headers, gateway_headers
):
    """A second bureau answer against an answered handoff is refused and the score stands.

    PRD: "The addressed credit-check handoff is still `SUBMITTED` when a bureau
    response arrives — otherwise `ERR_HANDOFF_NOT_OPEN` (409)."

    Design: Corner/state_machines/invalid_transitions_bureau_response_on_responded_handoff_rejected
    """
    bundle = fixtures.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    handoff = fixtures.dispatch_credit_check(api, order["id"], bureau=BureauName.EQUIFAX.value)

    answered = assert_ok(
        api.post_bureau_response(
            handoff["id"], factories.bureau_response_payload(700), gateway_headers
        )
    )
    assert answered["handoff_status"] == HandoffStatus.RESPONDED.value, (
        f"an answered handoff is RESPONDED, got {answered['handoff_status']}"
    )
    assert answered["score"] == 700, f"the bureau score is stored, got {answered['score']}"
    assert answered["result"] == CreditResult.CLEAR.value, (
        f"a score of 640 or above is a CLEAR result, got {answered['result']}"
    )
    assert answered["responded_at"].startswith("2026-08-01T00:00:00"), (
        f"responded_at is the logical-clock instant, got {answered['responded_at']}"
    )

    replay = api.post_bureau_response(
        handoff["id"], factories.bureau_response_payload(500), gateway_headers
    )
    assert_error(replay, ApiErrorId.HANDOFF_NOT_OPEN)

    reread = assert_ok(api.get_credit_check_handoff(handoff["id"], ops_headers))
    assert reread["handoff_status"] == HandoffStatus.RESPONDED.value, "the handoff stays RESPONDED"
    assert reread["score"] == 700, "the refused replay must not overwrite the score"
    assert reread["result"] == CreditResult.CLEAR.value, "the refused replay must not re-grade"
    assert reread["responded_at"] == answered["responded_at"], (
        "the refused replay must not re-stamp responded_at"
    )

    after = fixtures.read_order(api, order["id"])
    assert_order_dimensions(
        after,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.CLEARED.value,
    )
    assert_cents(after, "deposit_amount_cents", 0)


def test_11_waiver_voids_the_credit_dimension_and_lifts_readiness(api, ops_headers):
    """Waiving a credit-checked draft order marks it not applicable, voids the credit leg and counts as progress.

    PRD: "A waived order whose `credit_status` was `PENDING_CHECK` or
    `DEPOSIT_DUE` moves to `VOIDED`, and any credit-check handoff attached to it
    moves to `VOIDED` as well"

    Design: Corner/state_machines/side_effect_execution_waiver_voids_the_credit_dimension_and_lifts_readiness
    """
    bundle = fixtures.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    handoff = fixtures.dispatch_credit_check(api, order["id"], bureau=BureauName.EXPERIAN.value)

    before = fixtures.read_order(api, order["id"])
    assert_order_dimensions(
        before,
        provision_status=ProvisionStatus.DRAFT.value,
        credit_status=CreditStatus.PENDING_CHECK.value,
    )
    assert_cents(before, "deposit_estimate_cents", 22500)
    assert_cents(before, "deposit_amount_cents", 0)
    assert before["readiness_snapshot"] == 40, (
        f"dispatch freezes the move's readiness at 40, got {before['readiness_snapshot']}"
    )

    waived = assert_ok(
        api.waive_order(
            order["id"],
            factories.waiver_payload(waiver_reason="Landlord retains the electric account"),
            ops_headers,
        )
    )
    assert_order_dimensions(
        waived,
        provision_status=ProvisionStatus.NOT_APPLICABLE.value,
        credit_status=CreditStatus.VOIDED.value,
    )
    assert waived["waiver_reason"] == "Landlord retains the electric account", (
        "the waiver reason must be recorded on the order"
    )

    voided = assert_ok(api.get_credit_check_handoff(handoff["id"], ops_headers))
    assert voided["handoff_status"] == HandoffStatus.VOIDED.value, (
        f"the attached handoff is voided with the credit dimension, got {voided['handoff_status']}"
    )
    assert voided["score"] is None, "voiding writes no bureau score"
    assert voided["result"] is None, "voiding grades nothing"

    after = fixtures.read_move(api, bundle["move"]["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        readiness_score=70,
    )
    assert after["mapped_order_count"] == 1, "a waiver does not unmap the order"


def test_12_late_bureau_answer_on_a_voided_handoff_is_rejected(api, ops_headers, gateway_headers):
    """After the waiver has voided the handoff, the bureau's answer arrives too late.

    PRD: "Once a handoff has reached `VOIDED`, no bureau response is accepted
    against it — a late answer is refused with `ERR_HANDOFF_NOT_OPEN`"

    Design: Corner/state_machines/side_effect_execution_waiver_voids_the_credit_dimension_and_lifts_readiness
    """
    bundle = fixtures.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.ELECTRIC.value]
    handoff = fixtures.dispatch_credit_check(api, order["id"], bureau=BureauName.EXPERIAN.value)
    assert_ok(
        api.waive_order(
            order["id"],
            factories.waiver_payload(waiver_reason="Landlord retains the electric account"),
            ops_headers,
        )
    )

    late = api.post_bureau_response(
        handoff["id"], factories.bureau_response_payload(700), gateway_headers
    )
    assert_error(late, ApiErrorId.HANDOFF_NOT_OPEN)

    reread = assert_ok(api.get_credit_check_handoff(handoff["id"], ops_headers))
    assert reread["handoff_status"] == HandoffStatus.VOIDED.value, "the handoff stays VOIDED"
    assert reread["score"] is None, "a refused answer writes no score"
    assert reread["result"] is None, "a refused answer grades nothing"

    after = fixtures.read_order(api, order["id"])
    assert_order_dimensions(
        after,
        provision_status=ProvisionStatus.NOT_APPLICABLE.value,
        credit_status=CreditStatus.VOIDED.value,
    )
    assert_cents(after, "deposit_amount_cents", 0)


def test_13_closure_after_the_window_end_retains_the_audit_fields(api, ops_headers):
    """A live order closes only once the window has ended, and both window fields survive.

    PRD: "Closure moves `provision_status` to `CLOSED`, releases the occupancy
    window so the count for that address and utility type drops by one, and keeps
    both window fields populated for audit."

    Design: Corner/state_machines/valid_transition_order_closure_after_window_end_keeps_audit_fields
    """
    bundle = fixtures.mapped_move(
        api,
        utility_types=[UtilityType.WATER.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    order = bundle["orders_by_type"][UtilityType.WATER.value]
    fixtures.schedule_order(api, order["id"], requested_service_date="2026-08-05")
    provider_headers = make_provider_agent_headers(order["provider_id"])
    fixtures.set_clock(api, "2026-08-05T09:00:00Z")
    assert_ok(
        api.activate_order(
            order["id"],
            factories.activation_payload(confirmation_code="AWB-77120"),
            provider_headers,
        )
    )

    fixtures.set_clock(api, "2026-08-05T13:00:00Z")
    closed = assert_ok(
        api.close_order(
            order["id"],
            factories.closure_payload(final_read_note="Final read 41255 kWh"),
            ops_headers,
        )
    )

    assert_order_dimensions(
        closed,
        provision_status=ProvisionStatus.CLOSED.value,
        credit_status=CreditStatus.NOT_REQUIRED.value,
    )
    assert_window_retained(closed)
    assert closed["scheduled_window_start"].startswith("2026-08-05T09:00:00"), (
        f"the window start survives closure, got {closed['scheduled_window_start']}"
    )
    assert closed["scheduled_window_end"].startswith("2026-08-05T13:00:00"), (
        f"the window end survives closure, got {closed['scheduled_window_end']}"
    )
    assert closed["confirmation_code"] == "AWB-77120", "the activation code survives closure"

    after = fixtures.read_move(api, bundle["move"]["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.SCHEDULING.value,
        readiness_score=70,
    )


def test_14_completion_before_the_move_date_is_rejected(api, ops_headers, in_service_move):
    """A live move cannot be declared finished five days before the household moves.

    PRD: "a move cannot be declared finished before the household has actually
    moved, an early attempt being refused with `ERR_MOVE_DATE_NOT_REACHED`"

    Design: Corner/state_machines/precondition_enforcement_completion_before_move_date_rejected
    """
    move = in_service_move["move"]
    assert_move_state(
        move,
        lifecycle_status=MoveLifecycleStatus.IN_SERVICE.value,
        consent_gate=ConsentGate.OPEN.value,
        readiness_score=100,
    )
    assert move["move_date"] == "2026-08-10", f"unexpected move_date {move['move_date']}"

    early = api.complete_move(move["id"], {}, ops_headers)
    assert_error(early, ApiErrorId.MOVE_DATE_NOT_REACHED)

    after = fixtures.read_move(api, move["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.IN_SERVICE.value,
        readiness_score=100,
    )


def test_15_completion_on_the_move_date_locks_the_move_down(api, ops_headers, in_service_move):
    """Once the clock reaches the move date the same call completes the move and seals it.

    PRD: "Completion moves `lifecycle_status` to `COMPLETED`, recomputes
    `readiness_score` a final time, and locks the move down"

    Design: Corner/state_machines/precondition_enforcement_completion_before_move_date_rejected
    """
    move = in_service_move["move"]
    filing = in_service_move["filing"]

    assert filing["status"] == FilingStatus.CONFIRMED.value, (
        f"the postal filing must be CONFIRMED for the bubble-up, got {filing['status']}"
    )
    assert filing["forward_end_date"] == "2027-08-09", (
        "a forward_start_date of 2026-08-10 plus the 365-day term minus one day is 2027-08-09, "
        f"got {filing['forward_end_date']}"
    )
    assert filing["mail_forwarding_confirmed_at"].startswith("2026-08-01T00:00:00"), (
        f"the confirmation instant is the logical clock, got {filing['mail_forwarding_confirmed_at']}"
    )

    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    completed = assert_ok(api.complete_move(move["id"], {}, ops_headers))

    assert_move_state(
        completed,
        lifecycle_status=MoveLifecycleStatus.COMPLETED.value,
        blocked_reason=BlockedReason.NONE.value,
        readiness_score=100,
    )

    assert_error(
        api.create_filing(
            move["id"], factories.filing_payload(forward_start_date="2027-09-01"), ops_headers
        ),
        ApiErrorId.MOVE_NOT_ACTIONABLE,
    )
    assert_error(api.complete_move(move["id"], {}, ops_headers), ApiErrorId.MOVE_NOT_ACTIONABLE)

    after = fixtures.read_move(api, move["id"])
    assert_move_state(
        after,
        lifecycle_status=MoveLifecycleStatus.COMPLETED.value,
        readiness_score=100,
    )
