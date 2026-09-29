"""Writes whose only blocker lives on a sibling entity.

A session whose own axis is a perfectly legal SCHEDULED cannot start while the
laboratory it was booked at sits SUSPENDED, and a listing whose own axis permits
publication cannot publish while the submission behind it holds no attestation
credential. Both refusals must leave the blocked row exactly as it was, and the
identical request must succeed once the sibling moves to its permitting state.
"""

from test_helpers import (
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_NONCOMPLIANT,
    DAC_ISSUED,
    DAC_NOT_ISSUED,
    DAC_REVOKED,
    LAB_AUTHORIZED,
    LAB_SUSPENDED,
    MEMBER_TOOLS_GRANTED,
    PLAN_IN_EXECUTION,
    PLAN_ISSUED,
    PUB_PUBLISHED,
    PUB_UNPUBLISHED,
    PUB_WITHDRAWN,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    SUB_CERTIFIED,
    SUB_REVIEW_COMPLETE,
    accreditation_decision,
    build_program,
    issue_credential,
    new_listing,
    publish_listing,
    read_laboratory,
    read_listing,
    read_member,
    read_session,
    read_submission,
    same_instant,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_listing,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_INVALID_LABORATORY_STATE,
    ERR_INVALID_SUBMISSION_STATE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_credit_ledger_invariant,
    assert_reserved_bench_minutes,
    assert_states,
    assert_version,
)
from test_helpers.factories import test_session_payload
from test_helpers.fixtures import read_test_plan
from test_helpers.test_users import ADMIN_HEADERS, make_laboratory_headers

#: The instant the laboratory is suspended at, half an hour into the booked window.
SUSPENSION_CLOCK = "2026-09-02T09:30:00Z"

#: The booked window runs 09:00 to 13:00, so the session holds 240 minutes.
BOOKED_MINUTES = 240

#: The instant publication is attempted at, after both review axes are approved.
PUBLICATION_CLOCK = "2026-09-02T14:00:00Z"

#: The serial the programme operator burns into the attestation credential.
DAC_SERIAL = "DAC-0000077"


def _scheduled_session_at_a_suspended_laboratory():
    """One SCHEDULED session on bench 1 whose laboratory is suspended afterwards.

    The session's own axis stays legal and its plan stays ISSUED; the suspension
    is the only thing standing between it and execution.
    """
    ctx = build_program(stage="scheduled")
    set_clock(SUSPENSION_CLOCK)
    ctx.laboratory = accreditation_decision(ctx.laboratory_id, "SUSPEND")
    return ctx


class TestSessionStartGatedOnTheLaboratorysAccreditation:
    """One booked session, one laboratory walking AUTHORIZED to SUSPENDED and back."""

    def test_01_start_is_refused_while_the_sibling_laboratory_is_suspended(self):
        """The session is SCHEDULED and its plan is ISSUED, yet the start is refused
        because the laboratory that owns the bench is no longer AUTHORIZED.

        PRD (§3.6): "Starting a session is reserved to the laboratory that owns it —
        the acting `X-User-ID` must equal the session's `laboratory_id` — and requires
        `state` `SCHEDULED`, a laboratory that is currently `AUTHORIZED`, an
        `accreditation_expires_at` strictly after the logical clock's current instant,
        and a parent plan whose `state` is `ISSUED` or `IN_EXECUTION`."

        Design: Difficulty/cross_entity_state_dependency/session_start_refused_while_its_laboratory_sits_suspended
        """
        ctx = _scheduled_session_at_a_suspended_laboratory()
        before = read_session(ctx.session_id)
        plan_before = read_test_plan(ctx.plan_id)
        assert_states(before, state=SESSION_SCHEDULED)
        assert_states(plan_before, state=PLAN_ISSUED)

        response = api_client.start_test_session(
            ctx.session_id, headers=make_laboratory_headers(ctx.laboratory_id)
        )

        validate_error(response, ERR_INVALID_LABORATORY_STATE)
        after = read_session(ctx.session_id)
        assert_states(after, state=SESSION_SCHEDULED, started_at=None)
        assert_version(after, before["version"], "test session")
        plan_after = read_test_plan(ctx.plan_id)
        assert_states(plan_after, state=PLAN_ISSUED)
        assert_version(plan_after, plan_before["version"], "test plan")
        laboratory = read_laboratory(ctx.laboratory_id)
        assert_states(laboratory, accreditation_status=LAB_SUSPENDED)
        assert_reserved_bench_minutes(laboratory, BOOKED_MINUTES)

    def test_02_booking_a_further_window_at_the_suspended_laboratory_reserves_nothing(self):
        """A brand-new booking at the same suspended laboratory draws the identical
        laboratory-state refusal, and no minutes are reserved for it.

        PRD (§3.6): "The laboratory must be `AUTHORIZED`, and a laboratory that is
        `PROVISIONAL`, `SUSPENDED` or `REVOKED` is refused with
        `ERR_INVALID_LABORATORY_STATE`."

        Design: Difficulty/cross_entity_state_dependency/session_start_refused_while_its_laboratory_sits_suspended
        """
        ctx = _scheduled_session_at_a_suspended_laboratory()

        response = api_client.create_test_session(
            test_session_payload(
                ctx.plan_id,
                ctx.laboratory_id,
                bench_index=2,
                window_start="2026-09-03T09:00:00Z",
                window_end="2026-09-03T11:00:00Z",
                session_type="SECURITY",
            ),
            ADMIN_HEADERS,
        )

        validate_error(response, ERR_INVALID_LABORATORY_STATE)
        laboratory = read_laboratory(ctx.laboratory_id)
        assert_reserved_bench_minutes(laboratory, BOOKED_MINUTES)
        sessions, meta = validate_paginated(
            api_client.list_test_sessions(ADMIN_HEADERS, laboratory_id=ctx.laboratory_id)
        )
        assert meta["total_count"] == 1, (
            "the rejected booking must not have been stored, expected 1 session at "
            "the laboratory, got {}".format(meta["total_count"])
        )
        assert_states(sessions[0], state=SESSION_SCHEDULED)

    def test_03_reinstating_the_laboratory_unfreezes_the_very_same_session(self):
        """REINSTATE puts the laboratory back to AUTHORIZED and the identical start
        call on the same session row then succeeds, carrying the plan to
        IN_EXECUTION without any re-booking.

        PRD (§3.6): "The start moves `SCHEDULED → IN_PROGRESS` and stamps
        `started_at`, and where the parent plan was still `ISSUED` it also advances
        that plan to `IN_EXECUTION`."

        Design: Difficulty/cross_entity_state_dependency/session_start_refused_while_its_laboratory_sits_suspended
        """
        ctx = _scheduled_session_at_a_suspended_laboratory()
        refused = api_client.start_test_session(
            ctx.session_id, headers=make_laboratory_headers(ctx.laboratory_id)
        )
        validate_error(refused, ERR_INVALID_LABORATORY_STATE)

        reinstated = accreditation_decision(ctx.laboratory_id, "REINSTATE")
        assert_states(reinstated, accreditation_status=LAB_AUTHORIZED)

        response = api_client.start_test_session(
            ctx.session_id, headers=make_laboratory_headers(ctx.laboratory_id)
        )

        session = validate_success(response)
        assert_states(
            session, state=SESSION_IN_PROGRESS, reserved_minutes=BOOKED_MINUTES
        )
        assert same_instant(session["started_at"], SUSPENSION_CLOCK), (
            "started_at is stamped from the logical clock, expected {}, got {!r}".format(
                SUSPENSION_CLOCK, session["started_at"]
            )
        )
        assert_states(read_test_plan(ctx.plan_id), state=PLAN_IN_EXECUTION)

    def test_04_suspension_freezes_the_booking_without_touching_it(self):
        """Suspending the laboratory cancels nothing: the session stays SCHEDULED at
        version 1 and its 240 minutes stay on the laboratory's reserved total, and
        starting the session later neither reserves nor releases minutes.

        PRD (§3.3): "`SUSPEND` takes an `AUTHORIZED` laboratory to `SUSPENDED`, and
        it deliberately leaves that laboratory's test sessions exactly where they are
        — nothing is cancelled — but no session may be started while the laboratory
        is suspended."

        Design: Difficulty/cross_entity_state_dependency/session_start_refused_while_its_laboratory_sits_suspended
        """
        ctx = _scheduled_session_at_a_suspended_laboratory()

        frozen = read_session(ctx.session_id)
        assert_states(
            frozen,
            state=SESSION_SCHEDULED,
            started_at=None,
            reserved_minutes=BOOKED_MINUTES,
        )
        assert_version(frozen, 1, "test session")
        assert_reserved_bench_minutes(
            read_laboratory(ctx.laboratory_id), BOOKED_MINUTES
        )

        accreditation_decision(ctx.laboratory_id, "REINSTATE")
        validate_success(
            api_client.start_test_session(
                ctx.session_id, headers=make_laboratory_headers(ctx.laboratory_id)
            )
        )

        assert_reserved_bench_minutes(
            read_laboratory(ctx.laboratory_id), BOOKED_MINUTES
        )


def _listing_without_a_credential():
    """An UNPUBLISHED listing over a REVIEW_COMPLETE submission that holds no
    attestation credential.

    Both review axes are APPROVED, so the listing is legally created; the
    credential is deliberately left unissued, which is the only thing publication
    is still waiting on.
    """
    ctx = build_program(stage="review_complete")
    listing = new_listing(ctx.submission_id)
    ctx.listing = listing
    ctx.listing_id = listing["id"]
    set_clock(PUBLICATION_CLOCK)
    return ctx


class TestListingPublicationGatedOnTheSubmissionsCredential:
    """One listing row, published only once the submission behind it is credentialed."""

    def test_05_publication_is_refused_while_the_submission_holds_no_credential(self):
        """The listing is UNPUBLISHED and COMPLIANT, so its own two axes permit the
        move, yet publication is refused because the submission behind it still sits
        at dac_state NOT_ISSUED — and the refusal persists nothing.

        PRD (§3.9): "It requires the linked submission's `dac_state` to be `ISSUED`,
        with a `NOT_ISSUED` or `REVOKED` credential refused as
        `ERR_INVALID_SUBMISSION_STATE`; it requires `compliance_status` to be
        `COMPLIANT` or `REMEDIATED`, with an `UNDER_INVESTIGATION` or `NONCOMPLIANT`
        listing refused as `ERR_INVALID_LISTING_STATE`, as is a listing that is
        already `PUBLISHED` or `WITHDRAWN`; and it requires the listing's member to be
        in good standing."

        Design: Difficulty/cross_entity_state_dependency/listing_publish_refused_until_the_submission_holds_an_issued_credential
        """
        ctx = _listing_without_a_credential()
        before = read_listing(ctx.listing_id)
        assert_states(
            before,
            publication_status=PUB_UNPUBLISHED,
            compliance_status=COMPLIANCE_COMPLIANT,
            published_at=None,
        )
        assert_states(
            read_submission(ctx.submission_id),
            state=SUB_REVIEW_COMPLETE,
            dac_state=DAC_NOT_ISSUED,
        )

        response = api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS)

        validate_error(response, ERR_INVALID_SUBMISSION_STATE)
        after = read_listing(ctx.listing_id)
        assert_states(
            after,
            publication_status=PUB_UNPUBLISHED,
            compliance_status=COMPLIANCE_COMPLIANT,
            published_at=None,
        )
        assert_version(after, before["version"], "certification listing")
        assert_states(
            read_submission(ctx.submission_id), dac_state=DAC_NOT_ISSUED
        )

    def test_06_issuing_the_credential_lets_the_identical_publish_call_through(self):
        """Credential issuance flips the sibling submission to CERTIFIED with
        dac_state ISSUED, and the same publish call that was refused now returns 200,
        stamping published_at and the ordered feature declaration.

        PRD (§3.9): "Publication sets `publication_status` to `PUBLISHED`, stamps
        `published_at` from the logical clock, and recomputes `declared_features` from
        the submission's non-`VOIDED` test plan, so a plan that gained feature sets
        since the last publication refreshes the consumer-visible declaration."

        Design: Difficulty/cross_entity_state_dependency/listing_publish_refused_until_the_submission_holds_an_issued_credential
        """
        ctx = _listing_without_a_credential()
        validate_error(
            api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS),
            ERR_INVALID_SUBMISSION_STATE,
        )

        credentialed = issue_credential(ctx.submission_id, DAC_SERIAL)
        assert_states(
            credentialed,
            state=SUB_CERTIFIED,
            dac_state=DAC_ISSUED,
            dac_serial=DAC_SERIAL,
        )

        response = api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS)

        listing = validate_success(response)
        assert_states(listing, publication_status=PUB_PUBLISHED)
        assert same_instant(listing["published_at"], PUBLICATION_CLOCK), (
            "published_at is stamped from the logical clock, expected {}, got {!r}".format(
                PUBLICATION_CLOCK, listing["published_at"]
            )
        )
        assert listing["declared_features"] == ["CORE_DIM", "CORE_ONOFF"], (
            "declared_features is the plan's closure ordered by feature_code "
            "ascending, expected ['CORE_DIM', 'CORE_ONOFF'], got {!r}".format(
                listing["declared_features"]
            )
        )

    def test_07_the_gate_is_symmetric_once_the_withdrawal_revokes_the_credential(self):
        """Withdrawing the published listing revokes the submission's credential, and
        a further publish attempt is refused with the identical submission-state
        error the very first attempt drew.

        PRD (§3.9): "It sets `publication_status` to `WITHDRAWN`, sets
        `compliance_status` to `NONCOMPLIANT`, and, where the linked submission's
        `dac_state` is `ISSUED`, sets that `dac_state` to `REVOKED`."

        Design: Difficulty/cross_entity_state_dependency/listing_publish_refused_until_the_submission_holds_an_issued_credential
        """
        ctx = _listing_without_a_credential()
        issue_credential(ctx.submission_id, DAC_SERIAL)
        publish_listing(ctx.listing_id)

        withdrawn = withdraw_listing(ctx.listing_id)

        assert_states(
            withdrawn,
            publication_status=PUB_WITHDRAWN,
            compliance_status=COMPLIANCE_NONCOMPLIANT,
        )
        assert_states(read_submission(ctx.submission_id), dac_state=DAC_REVOKED)

        response = api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS)

        validate_error(response, ERR_INVALID_SUBMISSION_STATE)
        assert_states(
            read_listing(ctx.listing_id), publication_status=PUB_WITHDRAWN
        )

    def test_08_the_member_ledger_is_untouched_by_the_publication_gate(self):
        """None of the refusal, the issuance or the withdrawal disturbs the member's
        standing, and the only credit movement is the pinned fee consumed at
        issuance: 150000 cents for a LIGHTING device declaring two features on an SB1
        baseline at ADOPTER tier on the STANDARD track.

        PRD (§3.8): "Issuance moves `REVIEW_COMPLETE → CERTIFIED`, stamps
        `certified_at`, moves `dac_state` `NOT_ISSUED → ISSUED` with the supplied
        `dac_serial` stored, and *consumes* rather than releases the escrow: the
        member's `escrowed_credit_cents` falls by `fee_escrowed_cents`, its
        `credits_consumed_cents` rises by the same figure, and `fee_escrowed_cents`
        becomes 0."

        Design: Difficulty/cross_entity_state_dependency/listing_publish_refused_until_the_submission_holds_an_issued_credential
        """
        ctx = _listing_without_a_credential()
        assert_cents(ctx.certification_fee_cents, 150000, "certification_fee_cents")
        validate_error(
            api_client.publish_listing(ctx.listing_id, headers=ADMIN_HEADERS),
            ERR_INVALID_SUBMISSION_STATE,
        )
        issue_credential(ctx.submission_id, DAC_SERIAL)
        publish_listing(ctx.listing_id)
        withdraw_listing(ctx.listing_id)

        member = read_member(ctx.member_id)

        assert_states(
            member, good_standing=True, onboarding_state=MEMBER_TOOLS_GRANTED
        )
        assert_cents(member["credits_consumed_cents"], 150000, "credits_consumed_cents")
        assert_cents(member["escrowed_credit_cents"], 0, "escrowed_credit_cents")
        assert_cents(member["credit_balance_cents"], 850000, "credit_balance_cents")
        assert_credit_ledger_invariant(member)
