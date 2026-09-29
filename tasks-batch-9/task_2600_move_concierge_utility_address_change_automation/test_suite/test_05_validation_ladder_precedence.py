"""Precedence between two simultaneously broken rules.

Each scenario in this module arranges a request that violates two distinct
checks at once and pins which error the server must return, then removes the
higher-priority violation and shows the lower-priority one surfacing in its
place.  The winner is always the rule that sits earlier in the fixed
evaluation order, and the loser must leave no trace of having run.
"""

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_move_state,
    assert_ok,
    assert_order_dimensions,
    assert_readiness_breakdown,
    assert_window_released,
)
from test_helpers.test_users import make_move_ops_headers
from test_helpers.types import (
    BlockedReason,
    ConsentGate,
    ConsentScope,
    ConsentState,
    FilingStatus,
    MoveLifecycleStatus,
    ProvisionStatus,
    ReadinessVariant,
    UtilityType,
)


def _read_filing(api, filing_id):
    """Read one postal filing back."""
    return assert_ok(api.get_filing(filing_id, make_move_ops_headers()))


# ---------------------------------------------------------------------------
# Filing state (rung 9) versus a revoked consent gate (rung 21)
# ---------------------------------------------------------------------------
def _submitted_filing_behind_a_blocked_gate(api, compliance_headers):
    """A SUBMITTED filing on a VERIFIED move whose utility consent was revoked.

    The resident granted both gate scopes, so the filing itself was accepted;
    revoking the `UTILITY_SETUP` record afterwards blocks the move's consent
    gate while leaving the `USPS_FILING` record `GRANTED`.
    """
    network = fx.build_network(api)
    consents = fx.grant_consents(
        api,
        network["resident"]["id"],
        [ConsentScope.UTILITY_SETUP.value, ConsentScope.USPS_FILING.value],
    )
    move = fx.ingest_move(api, network, move_date="2026-08-20")
    fx.pass_identity_by_kba(api, move["id"])
    filing = fx.draft_filing(api, move["id"], forward_start_date="2026-08-20")
    filing = fx.submit_filing(api, filing["id"])

    assert_ok(
        api.revoke_consent(
            consents[ConsentScope.UTILITY_SETUP.value]["id"],
            f.revocation_payload(),
            compliance_headers,
        )
    )
    return {"network": network, "consents": consents, "move": move, "filing": filing}


def test_01_already_submitted_filing_beats_the_blocked_consent_gate(api, ops_headers, compliance_headers):
    """Resubmitting a SUBMITTED filing reports its state, not the blocked gate.

    PRD: "The server evaluates checks in the fixed order below and returns the error of the **first** rule that fails; later rules are not evaluated at all"
    PRD: "Submitting a filing that is already `SUBMITTED` or `CONFIRMED` — or posting a postal answer against one still in `DRAFT`, or trying to withdraw one already `CONFIRMED` — is refused with `ERR_FILING_NOT_SUBMITTABLE`"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_consent_revoked_on_filing_resubmission
    """
    built = _submitted_filing_behind_a_blocked_gate(api, compliance_headers)
    move = fx.read_move(api, built["move"]["id"])
    assert_move_state(
        move,
        consent_gate=ConsentGate.BLOCKED.value,
        blocked_reason=BlockedReason.CONSENT_REVOKED.value,
    )

    response = api.submit_filing(built["filing"]["id"], {}, ops_headers)

    assert_error(response, ApiErrorId.FILING_NOT_SUBMITTABLE)
    filing = _read_filing(api, built["filing"]["id"])
    assert filing["status"] == FilingStatus.SUBMITTED.value, (
        f"the filing must stay SUBMITTED, got {filing['status']}"
    )
    assert filing["resubmit_count"] == 0, (
        f"a refused submission never adds to resubmit_count, got {filing['resubmit_count']}"
    )
    assert_move_state(move, readiness_score=42)


def test_02_rejected_filing_surfaces_the_blocked_consent_gate(api, ops_headers, compliance_headers, gateway_headers):
    """With the state objection removed, the revoked gate becomes the answer.

    PRD: "A move whose gate is `BLOCKED` is refused on six operations — provider mapping, order scheduling, order activation, postal filing submission, placement acceptance and placement conversion — each time with `ERR_CONSENT_REVOKED`"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_consent_revoked_on_filing_resubmission
    """
    built = _submitted_filing_behind_a_blocked_gate(api, compliance_headers)

    rejected = assert_ok(
        api.post_usps_response(
            built["filing"]["id"], f.usps_rejection_payload(), gateway_headers
        )
    )
    assert rejected["status"] == FilingStatus.REJECTED.value, (
        f"the postal answer must reject the filing, got {rejected['status']}"
    )

    response = api.submit_filing(built["filing"]["id"], {}, ops_headers)

    assert_error(response, ApiErrorId.CONSENT_REVOKED)
    filing = _read_filing(api, built["filing"]["id"])
    assert filing["status"] == FilingStatus.REJECTED.value, (
        f"a refused resubmission leaves the filing REJECTED, got {filing['status']}"
    )
    assert filing["resubmit_count"] == 0, (
        f"a refused resubmission never adds to resubmit_count, got {filing['resubmit_count']}"
    )

    usps_consent = assert_ok(
        api.get_consent_record(
            built["consents"][ConsentScope.USPS_FILING.value]["id"], compliance_headers
        )
    )
    assert usps_consent["state"] == ConsentState.GRANTED.value, (
        "the postal consent is still granted, so the refusal is about the revoked one"
    )
    move = fx.read_move(api, built["move"]["id"])
    assert_move_state(move, readiness_score=30)


# ---------------------------------------------------------------------------
# Identity validity window (rung 17) versus the scheduling lead time (rung 31)
# ---------------------------------------------------------------------------
def _draft_electric_order(api):
    """A SCHEDULING move with one DRAFT electric order, verified on 2026-08-01.

    The electric provider carries a three-day scheduling lead, and the
    resident holds only the `UTILITY_SETUP` consent scope.
    """
    bundle = fx.mapped_move(
        api,
        utility_types=[UtilityType.ELECTRIC.value],
        scopes=[ConsentScope.UTILITY_SETUP.value],
    )
    return bundle, bundle["orders_by_type"][UtilityType.ELECTRIC.value]


def test_03_lead_time_floor_refuses_a_service_date_inside_the_notice_period(api, ops_headers):
    """While identity is still valid, the lead-time floor is the only objection.

    PRD: "`requested_service_date` must be at or after the logical clock's date plus the provider's `scheduling_lead_days`"

    Design: Difficulty/priority_pair_validation_conflict/identity_expiry_beats_lead_time_on_order_schedule
    """
    bundle, order = _draft_electric_order(api)

    response = api.schedule_order(
        order["id"], f.schedule_payload(requested_service_date="2026-08-02"), ops_headers
    )

    assert_error(response, ApiErrorId.LEAD_TIME_VIOLATION)
    after = fx.read_order(api, order["id"])
    assert_order_dimensions(after, provision_status=ProvisionStatus.DRAFT.value)
    assert after["requested_service_date"] is None, (
        f"a refused schedule writes no date, got {after['requested_service_date']}"
    )
    assert_window_released(after)

    breakdown = fx.read_readiness(api, bundle["move"]["id"])
    assert_readiness_breakdown(
        breakdown,
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=100,
        utility_component=0,
        filing_component=0,
        consent_component=50,
        readiness_score=40,
    )


def test_04_expired_identity_beats_the_lead_time_floor(api, ops_headers):
    """Once the 30-day validity window lapses, expiry answers ahead of lead time.

    PRD: "an operation guarded by the validity window succeeds while the logical clock is at or before `verified_at` plus 30 days and is refused with `ERR_IDENTITY_VERIFICATION_EXPIRED` after that"

    Design: Difficulty/priority_pair_validation_conflict/identity_expiry_beats_lead_time_on_order_schedule
    """
    bundle, order = _draft_electric_order(api)
    fx.set_clock(api, "2026-09-01T00:00:00Z")

    response = api.schedule_order(
        order["id"], f.schedule_payload(requested_service_date="2026-09-02"), ops_headers
    )

    assert_error(response, ApiErrorId.IDENTITY_VERIFICATION_EXPIRED)
    after = fx.read_order(api, order["id"])
    assert_order_dimensions(after, provision_status=ProvisionStatus.DRAFT.value)
    assert after["requested_service_date"] is None, (
        f"a refused schedule writes no date, got {after['requested_service_date']}"
    )
    assert_window_released(after)

    move = fx.read_move(api, bundle["move"]["id"])
    assert move["verified_at"] is not None, (
        "the move did clear identity; only its validity window has lapsed"
    )
    breakdown = fx.read_readiness(api, bundle["move"]["id"])
    assert_readiness_breakdown(
        breakdown,
        variant=ReadinessVariant.POST_VERIFICATION.value,
        identity_component=0,
        utility_component=0,
        filing_component=0,
        consent_component=50,
        readiness_score=10,
    )


# ---------------------------------------------------------------------------
# Forwarding-period conflict (rung 35) versus the resubmit limit (rung 42)
# ---------------------------------------------------------------------------
def _ingest_move_to(api, network, destination_address_id, move_date):
    """Ingest a move for the built network against a nominated destination."""
    payload = f.move_payload(
        network["resident"]["id"],
        network["feed_source"]["id"],
        network["origin_address"]["id"],
        destination_address_id,
        move_date=move_date,
    )
    return assert_created(api.create_move(payload, make_move_ops_headers()))


def _exhausted_retries_against_an_open_period(api, gateway_headers):
    """One resident, two moves: a twice-retried filing and a submitted sibling.

    The retried filing covers 2026-11-01 through 2027-10-31 and has already
    used both permitted retries.  The sibling filing on the earlier move is
    submitted afterwards and covers 2026-08-20 through 2027-08-19, so the two
    closed periods intersect.
    """
    network = fx.build_network(api)
    fx.grant_consents(api, network["resident"]["id"], [ConsentScope.USPS_FILING.value])
    macon = fx.create_address(api, f.third_address_payload())
    early_move = fx.ingest_move(api, network, move_date="2026-08-20")
    later_move = _ingest_move_to(api, network, macon["id"], "2026-11-01")
    fx.pass_identity_by_kba(api, early_move["id"])
    fx.pass_identity_by_kba(api, later_move["id"])

    retried = fx.draft_filing(api, later_move["id"], forward_start_date="2026-11-01")
    fx.submit_filing(api, retried["id"])
    for _ in range(2):
        assert_ok(
            api.post_usps_response(
                retried["id"], f.usps_rejection_payload(), gateway_headers
            )
        )
        fx.submit_filing(api, retried["id"])
    retried = assert_ok(
        api.post_usps_response(retried["id"], f.usps_rejection_payload(), gateway_headers)
    )

    sibling = fx.draft_filing(api, early_move["id"], forward_start_date="2026-08-20")
    sibling = fx.submit_filing(api, sibling["id"])
    return {
        "network": network,
        "early_move": early_move,
        "later_move": later_move,
        "retried": retried,
        "sibling": sibling,
    }


def test_05_forwarding_period_conflict_beats_the_exhausted_resubmit_limit(api, ops_headers, gateway_headers):
    """An overlapping open period answers ahead of the exhausted retry count.

    PRD: "the resident may have no other filing in `SUBMITTED` or `CONFIRMED` whose closed period from `forward_start_date` through `forward_end_date` intersects the period being submitted"

    Design: Difficulty/priority_pair_validation_conflict/forwarding_conflict_beats_resubmit_limit_on_filing
    """
    built = _exhausted_retries_against_an_open_period(api, gateway_headers)
    assert built["retried"]["resubmit_count"] == 2, (
        f"both retries must already be spent, got {built['retried']['resubmit_count']}"
    )
    assert built["sibling"]["status"] == FilingStatus.SUBMITTED.value, (
        f"the sibling filing must hold the period, got {built['sibling']['status']}"
    )
    assert built["sibling"]["forward_end_date"] == "2027-08-19", (
        f"expected forward_end_date 2027-08-19, got {built['sibling']['forward_end_date']}"
    )
    assert built["retried"]["forward_end_date"] == "2027-10-31", (
        f"expected forward_end_date 2027-10-31, got {built['retried']['forward_end_date']}"
    )

    before = _read_filing(api, built["retried"]["id"])
    response = api.submit_filing(built["retried"]["id"], {}, ops_headers)

    assert_error(response, ApiErrorId.FORWARDING_PERIOD_CONFLICT)
    after = _read_filing(api, built["retried"]["id"])
    assert after["status"] == FilingStatus.REJECTED.value, (
        f"the refused filing stays REJECTED, got {after['status']}"
    )
    assert after["resubmit_count"] == 2, (
        f"a refused resubmission adds nothing to resubmit_count, got {after['resubmit_count']}"
    )
    assert after["version"] == before["version"], (
        "a refused resubmission must not bump the filing's version"
    )
    early = fx.read_move(api, built["early_move"]["id"])
    assert_move_state(early, readiness_score=52)


def test_06_withdrawing_the_open_sibling_filing_surfaces_the_resubmit_limit(api, ops_headers, compliance_headers, gateway_headers):
    """With the period freed, the spent retry budget becomes the answer.

    PRD: "Resubmission additionally requires `resubmit_count` to be below the platform limit of 2, so a filing may be submitted once and retried at most twice; the third retry is refused with `ERR_RESUBMIT_LIMIT_REACHED`"
    PRD: "Cancellation moves `status` to `CANCELLED` and clears `mail_forwarding_confirmed_at`, which is what releases the resident's forwarding-period slot and lets a corrected filing be submitted for an overlapping period"

    Design: Difficulty/priority_pair_validation_conflict/forwarding_conflict_beats_resubmit_limit_on_filing
    """
    built = _exhausted_retries_against_an_open_period(api, gateway_headers)

    withdrawn = assert_ok(
        api.cancel_filing(
            built["sibling"]["id"], f.filing_cancellation_payload(), compliance_headers
        )
    )
    assert withdrawn["status"] == FilingStatus.CANCELLED.value, (
        f"expected status CANCELLED, got {withdrawn['status']}"
    )
    assert withdrawn["mail_forwarding_confirmed_at"] is None, (
        "withdrawal clears mail_forwarding_confirmed_at and releases the slot"
    )

    response = api.submit_filing(built["retried"]["id"], {}, ops_headers)

    assert_error(response, ApiErrorId.RESUBMIT_LIMIT_REACHED)
    after = _read_filing(api, built["retried"]["id"])
    assert after["status"] == FilingStatus.REJECTED.value, (
        f"the refused filing stays REJECTED, got {after['status']}"
    )
    assert after["resubmit_count"] == 2, (
        f"a refused resubmission adds nothing to resubmit_count, got {after['resubmit_count']}"
    )
    early = fx.read_move(api, built["early_move"]["id"])
    assert_move_state(
        early,
        lifecycle_status=MoveLifecycleStatus.VERIFIED.value,
        readiness_score=40,
    )
