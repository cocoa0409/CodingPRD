"""Multi-hop cascades where every link is caused by the link before it.

A member's intellectual-property withdrawal walks good standing into listing
suppression into credential revocation into an auto-opened noncompliance case; a
specification demotion walks an in-flight submission into a voided test plan into
cancelled bench windows and the minutes they were holding.
"""

from test_helpers import (
    AUTO_OPENED_EVIDENCE_SUMMARY,
    CASE_OPEN,
    COMPLIANCE_UNDER_INVESTIGATION,
    DAC_ISSUED,
    DAC_NOT_ISSUED,
    DAC_REVOKED,
    MEMBER_IP_WITHDRAWN,
    PLAN_IN_EXECUTION,
    PLAN_VOIDED,
    PUB_SUPPRESSED,
    REVIEW_RETURNED,
    SESSION_CANCELLED,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    SPEC_DEPRECATED,
    SUB_CERTIFIED,
    SUB_DRAFT,
    SUB_IN_REVIEW,
    SUB_RETURNED_FOR_INFO,
    SYSTEM_USER_ID,
    VOIDED_SPEC_DEPRECATED,
    build_program,
    deprecate_specification,
    new_session,
    new_submission,
    read_laboratory,
    read_listing,
    read_member,
    read_session,
    read_specification,
    read_submission,
    read_test_plan,
    same_instant,
    set_clock,
    start_session,
    validate_paginated,
    withdraw_ip_commitment,
)
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_cents,
    assert_credit_ledger_invariant,
    assert_penalty,
    assert_reserved_bench_minutes,
    assert_states,
)
from test_helpers.test_users import ADMIN_HEADERS, COMPLIANCE_HEADERS, COMPLIANCE_OFFICER_1

#: The instant the withdrawal is requested at, one day after the bench work.
WITHDRAWAL_CLOCK = "2026-09-04T00:00:00Z"

#: The instant the whole demotion scenario is driven at.
DEPRECATION_CLOCK = "2026-09-01T00:00:00Z"

#: 120000 base for LIGHTING plus 15000 for each of the two declared codes, at
#: SB1 and ADOPTER on the STANDARD track.
PINNED_FEE_CENTS = 150000
PURCHASED_CENTS = 1000000


def _withdrawal_cascade_program():
    """The canonical certified chain with a PUBLISHED listing and an ISSUED
    credential, plus a control submission left in DRAFT, then the withdrawal."""
    ctx = build_program(stage="published", dac_serial="DAC-0000001")
    control = new_submission(ctx.member_id, ctx.specification_id, ctx.declared_codes)
    ctx.control_submission_id = control["id"]
    set_clock(WITHDRAWAL_CLOCK)
    ctx.member_after = withdraw_ip_commitment(ctx.member_id)
    return ctx


def _cases_for_listing(listing_id):
    """Every noncompliance case filed against one listing, newest last."""
    return validate_paginated(
        api_client.list_noncompliance_cases(COMPLIANCE_HEADERS, listing_id=listing_id)
    )


def _all_cases():
    """Every noncompliance case in the service."""
    return validate_paginated(
        api_client.list_noncompliance_cases(COMPLIANCE_HEADERS)
    )


def _listings_for_submission(submission_id):
    return validate_paginated(
        api_client.list_listings(ADMIN_HEADERS, submission_id=submission_id)
    )


class TestIpWithdrawalCascadesFourHops:
    """One withdrawal request, four chained hops, and a DRAFT control that the
    chain never reaches."""

    def test_01_the_withdrawal_lands_on_ip_withdrawn_and_stamps_the_clock(self):
        """The request itself moves the member from TOOLS_GRANTED to the terminal
        IP_WITHDRAWN and stamps `ip_withdrawn_at` from the logical clock, leaving
        the executed commitment's own stamp in place.

        PRD (§3.2): "It is available from `IP_EXECUTED`, from `TOOLS_GRANTED` and
        from `TOOLS_REVOKED`, always landing on `IP_WITHDRAWN`, and it stamps
        `ip_withdrawn_at`."

        Design: Difficulty/transitive_cascade/ip_withdrawal_cascades_four_hops_into_an_auto_opened_case
        """
        ctx = _withdrawal_cascade_program()

        member = read_member(ctx.member_id)

        assert member["onboarding_state"] == MEMBER_IP_WITHDRAWN, (
            "the withdrawal lands on IP_WITHDRAWN, expected {}, got {}".format(
                MEMBER_IP_WITHDRAWN, member["onboarding_state"]
            )
        )
        assert member["ip_withdrawn_at"] is not None, (
            "ip_withdrawn_at must be stamped by the withdrawal, got None"
        )
        assert same_instant(member["ip_withdrawn_at"], WITHDRAWAL_CLOCK), (
            "ip_withdrawn_at must be the logical clock's instant {}, got {!r}".format(
                WITHDRAWAL_CLOCK, member["ip_withdrawn_at"]
            )
        )
        assert member["ip_executed_at"] is not None, (
            "the earlier ip_executed_at stamp survives the withdrawal, got None"
        )
        assert member["ip_commitment_type"] == "RAND_ROYALTY_FREE", (
            "the withdrawal does not erase the recorded commitment type, expected "
            "RAND_ROYALTY_FREE, got {!r}".format(member["ip_commitment_type"])
        )

    def test_02_hop_one_loses_good_standing_and_hop_two_suppresses_the_listing(self):
        """Good standing is recomputed to false, and because it was lost the
        member's PUBLISHED listing is suppressed and put under investigation.

        PRD (§3.2): "**Hop two**, caused by that loss of standing, takes every
        listing of this member whose `publication_status` is `PUBLISHED` and sets
        `publication_status` to `SUPPRESSED` and `compliance_status` to
        `UNDER_INVESTIGATION`."

        Design: Difficulty/transitive_cascade/ip_withdrawal_cascades_four_hops_into_an_auto_opened_case
        """
        ctx = _withdrawal_cascade_program()

        member = read_member(ctx.member_id)
        listing = read_listing(ctx.listing_id)

        assert member["good_standing"] is False, (
            "hop one recomputes good_standing to false, got {!r}".format(
                member["good_standing"]
            )
        )
        assert listing["publication_status"] == PUB_SUPPRESSED, (
            "hop two suppresses the published listing, expected {}, got {}".format(
                PUB_SUPPRESSED, listing["publication_status"]
            )
        )
        assert listing["compliance_status"] == COMPLIANCE_UNDER_INVESTIGATION, (
            "hop two puts the listing under investigation, expected {}, got {}".format(
                COMPLIANCE_UNDER_INVESTIGATION, listing["compliance_status"]
            )
        )
        assert listing["published_at"] is not None, (
            "the earlier published_at stamp is not cleared by the suppression, got None"
        )

    def test_03_hop_three_revokes_the_credential_and_leaves_the_serial_standing(self):
        """Because its listing was suppressed the submission's ISSUED device
        attestation credential is revoked, while the issued serial and the
        CERTIFIED primary state both survive.

        PRD (§3.2): "**Hop three**, caused by the suppression, takes every
        submission behind a listing suppressed in hop two whose `dac_state` is
        `ISSUED` and sets `dac_state` to `REVOKED`."

        Design: Difficulty/transitive_cascade/ip_withdrawal_cascades_four_hops_into_an_auto_opened_case
        """
        ctx = _withdrawal_cascade_program()

        assert ctx.submission["dac_state"] == DAC_ISSUED, (
            "the credential must have been ISSUED before the withdrawal, got {}".format(
                ctx.submission["dac_state"]
            )
        )

        submission = read_submission(ctx.submission_id)

        assert submission["dac_state"] == DAC_REVOKED, (
            "hop three revokes the attestation credential, expected {}, got {}".format(
                DAC_REVOKED, submission["dac_state"]
            )
        )
        assert submission["dac_serial"] == "DAC-0000001", (
            "the issued serial is not cleared by the revocation, expected "
            "DAC-0000001, got {!r}".format(submission["dac_serial"])
        )
        assert submission["state"] == SUB_CERTIFIED, (
            "the primary axis stays terminal at CERTIFIED, expected {}, got {}".format(
                SUB_CERTIFIED, submission["state"]
            )
        )

    def test_04_hop_four_auto_opens_exactly_one_case_and_the_chain_ends_there(self):
        """The revoked credential auto-opens one IP_WITHDRAWAL case for the
        suppressed listing, priced at zero on zero claimed units, and the chain
        stops there: the DRAFT control submission has no listing and no case.

        PRD (§3.2): "**Hop four**, caused by that credential revocation, creates
        one noncompliance case per listing whose submission lost its credential in
        hop three, with `category` `IP_WITHDRAWAL`, `state` `OPEN`, `auto_opened`
        true, `opened_by_user_id` the literal `SYSTEM`, `claimed_impact_units` 0,
        `evidence_summary` set to the fixed text `Auto-opened: IP commitment
        withdrawn by member`, and its three penalty amounts computed exactly as for
        an operator-filed case."

        Design: Difficulty/transitive_cascade/ip_withdrawal_cascades_four_hops_into_an_auto_opened_case
        """
        ctx = _withdrawal_cascade_program()

        cases, meta = _cases_for_listing(ctx.listing_id)

        assert meta["total_count"] == 1, (
            "hop four opens exactly one case per affected listing, expected "
            "total_count 1, got {}".format(meta["total_count"])
        )
        case = cases[0]
        assert_states(
            case,
            category="IP_WITHDRAWAL",
            state=CASE_OPEN,
            auto_opened=True,
            claimed_impact_units=0,
            evidence_summary=AUTO_OPENED_EVIDENCE_SUMMARY,
        )
        assert_penalty(case, 0, "IP_WITHDRAWAL")

        _, all_meta = _all_cases()
        assert all_meta["total_count"] == 1, (
            "the chain reaches only the one suppressed listing, so the service holds "
            "exactly 1 case, got {}".format(all_meta["total_count"])
        )
        _, control_listings = _listings_for_submission(ctx.control_submission_id)
        assert control_listings["total_count"] == 0, (
            "the DRAFT control submission has no listing for hop two to suppress, "
            "expected 0, got {}".format(control_listings["total_count"])
        )

    def test_05_the_cascade_records_system_rather_than_an_operator_identity(self):
        """The case hop four opens is a write the server performs for itself, so
        `opened_by_user_id` carries the literal SYSTEM and never a compliance
        officer's identifier, and no closing identity is recorded.

        PRD (§2.1): "Where the server itself performs one of those writes as part
        of a cascade rather than on an operator's behalf, it records the literal
        string `SYSTEM` in place of a user identifier."

        Design: Difficulty/transitive_cascade/ip_withdrawal_cascades_four_hops_into_an_auto_opened_case
        """
        ctx = _withdrawal_cascade_program()

        cases, _ = _cases_for_listing(ctx.listing_id)
        case = cases[0]

        assert case["opened_by_user_id"] == SYSTEM_USER_ID, (
            "a cascade-opened case records the literal {!r} as its opener, got "
            "{!r}".format(SYSTEM_USER_ID, case["opened_by_user_id"])
        )
        assert case["opened_by_user_id"] != COMPLIANCE_OFFICER_1, (
            "no operator identifier may appear on a cascade-opened case, got "
            "{!r}".format(case["opened_by_user_id"])
        )
        assert case["auto_opened"] is True, (
            "the case was opened by the system, so auto_opened must be true, got "
            "{!r}".format(case["auto_opened"])
        )
        assert case["closed_by_user_id"] is None, (
            "the freshly opened case has no closing identity yet, got {!r}".format(
                case["closed_by_user_id"]
            )
        )

    def test_06_the_cascade_moves_no_credit_and_never_touches_the_draft_control(self):
        """None of the four hops moves money: the fee consumed at issuance stays
        consumed, the balance stays put, and the DRAFT control submission — which
        never escrowed and never earned a credential — is left exactly as it was.

        PRD (§3.2): "The invariant that must hold after every single write, with no
        drift ever, is that `credits_purchased_cents` equals `credit_balance_cents`
        plus `credits_consumed_cents` plus `escrowed_credit_cents`."

        Design: Difficulty/transitive_cascade/ip_withdrawal_cascades_four_hops_into_an_auto_opened_case
        """
        ctx = _withdrawal_cascade_program()

        member = read_member(ctx.member_id)

        assert_cents(member["credits_purchased_cents"], PURCHASED_CENTS, "credits_purchased_cents")
        assert_cents(
            member["credits_consumed_cents"], PINNED_FEE_CENTS, "credits_consumed_cents"
        )
        assert_cents(member["escrowed_credit_cents"], 0, "escrowed_credit_cents")
        assert_cents(
            member["credit_balance_cents"],
            PURCHASED_CENTS - PINNED_FEE_CENTS,
            "credit_balance_cents",
        )
        assert_credit_ledger_invariant(member)

        control = read_submission(ctx.control_submission_id)
        assert_states(control, state=SUB_DRAFT, dac_state=DAC_NOT_ISSUED)
        assert_cents(control["fee_escrowed_cents"], 0, "control fee_escrowed_cents")


#: Session A occupies bench 1 for four hours; session B occupies bench 2 for two.
SESSION_A_MINUTES = 240
SESSION_B_MINUTES = 120


def _deprecation_cascade_program():
    """An IN_EXECUTION plan holding one SCHEDULED and one IN_PROGRESS bench
    window, then the RATIFIED to DEPRECATED demotion of its specification."""
    ctx = build_program(stage="issued")
    ctx.session_a = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T13:00:00Z",
        session_type="INTEROP",
    )
    ctx.session_b = new_session(
        ctx.plan_id,
        ctx.laboratory_id,
        bench_index=2,
        window_start="2026-09-03T09:00:00Z",
        window_end="2026-09-03T11:00:00Z",
        session_type="SECURITY",
    )
    ctx.session_b = start_session(ctx.session_b["id"], ctx.laboratory_id)
    ctx.laboratory_before = read_laboratory(ctx.laboratory_id)
    ctx.plan_before = read_test_plan(ctx.plan_id)
    ctx.specification_after = deprecate_specification(ctx.specification_id)
    return ctx


class TestSpecificationDeprecationCascadesThreeHops:
    """One demotion request, three chained hops, and the bench minutes the last
    hop hands back to the laboratory."""

    def test_07_the_demotion_moves_ratified_to_deprecated_and_stamps_the_clock(self):
        """The demotion step taken from RATIFIED lands on DEPRECATED and stamps
        `deprecated_at` from the logical clock, leaving `ratified_at` in place.

        PRD (§3.1): "From `RATIFIED` the version moves to `DEPRECATED`, stamping
        `deprecated_at`."

        Design: Difficulty/transitive_cascade/specification_deprecation_cascades_three_hops_into_bench_minutes
        """
        ctx = _deprecation_cascade_program()

        specification = read_specification(ctx.specification_id)

        assert specification["status"] == SPEC_DEPRECATED, (
            "the first demotion step lands on DEPRECATED, expected {}, got {}".format(
                SPEC_DEPRECATED, specification["status"]
            )
        )
        assert specification["deprecated_at"] is not None, (
            "deprecated_at must be stamped by the demotion, got None"
        )
        assert same_instant(specification["deprecated_at"], DEPRECATION_CLOCK), (
            "deprecated_at must be the logical clock's instant {}, got {!r}".format(
                DEPRECATION_CLOCK, specification["deprecated_at"]
            )
        )
        assert specification["ratified_at"] is not None, (
            "the earlier ratified_at stamp survives the demotion, got None"
        )

    def test_08_hop_one_returns_the_in_flight_submission_for_information(self):
        """The IN_REVIEW submission pinned to the demoted version is returned for
        information with its conformance axis at RETURNED, its revision round
        raised to 1 and SYSTEM recorded as the reviewer.

        PRD (§3.1): "**Hop one** takes every submission pinned to this version whose
        `state` is `SUBMITTED`, `IN_REVIEW` or `RETURNED_FOR_INFO` and sets
        `conformance_review_state` to `RETURNED`, `state` to `RETURNED_FOR_INFO`,
        and `conformance_reviewer_user_id` to the literal `SYSTEM`; each such
        submission's `revision_round` is raised by one but never past the ceiling of
        2, so a submission already at 2 stays at 2 rather than overflowing."

        Design: Difficulty/transitive_cascade/specification_deprecation_cascades_three_hops_into_bench_minutes
        """
        ctx = _deprecation_cascade_program()

        assert ctx.submission["state"] == SUB_IN_REVIEW, (
            "the submission must have been IN_REVIEW before the demotion, got "
            "{}".format(ctx.submission["state"])
        )

        submission = read_submission(ctx.submission_id)

        assert_states(
            submission,
            state=SUB_RETURNED_FOR_INFO,
            conformance_review_state=REVIEW_RETURNED,
            revision_round=1,
            conformance_reviewer_user_id=SYSTEM_USER_ID,
        )
        assert submission["conformance_reviewer_user_id"] == SYSTEM_USER_ID, (
            "the cascade returns the submission on its own behalf, so the recorded "
            "reviewer is {!r}, got {!r}".format(
                SYSTEM_USER_ID, submission["conformance_reviewer_user_id"]
            )
        )

    def test_09_hop_two_voids_the_plan_because_its_submission_was_returned(self):
        """The IN_EXECUTION test plan of the returned submission is voided, and the
        reason recorded names the demotion rather than a superseding plan.

        PRD (§3.1): "**Hop two**, caused by hop one rather than by the demotion
        itself, takes every test plan belonging to a submission that hop one touched
        and whose `state` is `DRAFT`, `ISSUED`, `IN_EXECUTION` or `COMPLETE`, and
        sets `state` to `VOIDED` with `voided_reason` `SPECIFICATION_DEPRECATED`."

        Design: Difficulty/transitive_cascade/specification_deprecation_cascades_three_hops_into_bench_minutes
        """
        ctx = _deprecation_cascade_program()

        assert ctx.plan_before["state"] == PLAN_IN_EXECUTION, (
            "starting session B must have advanced the plan to IN_EXECUTION before "
            "the demotion, got {}".format(ctx.plan_before["state"])
        )

        plan = read_test_plan(ctx.plan_id)

        assert plan["state"] == PLAN_VOIDED, (
            "hop two voids the plan, expected {}, got {}".format(
                PLAN_VOIDED, plan["state"]
            )
        )
        assert plan["voided_reason"] == VOIDED_SPEC_DEPRECATED, (
            "the voiding was triggered by the demotion, expected voided_reason {}, "
            "got {!r}".format(VOIDED_SPEC_DEPRECATED, plan["voided_reason"])
        )
        assert plan["specification_id"] == ctx.specification_id, (
            "the voided plan stays pinned to the demoted version, expected {}, got "
            "{}".format(ctx.specification_id, plan["specification_id"])
        )

    def test_10_hop_three_cancels_both_live_sessions_and_releases_the_minutes(self):
        """The voided plan's SCHEDULED and IN_PROGRESS sessions are both cancelled
        and the laboratory's reserved aggregate falls from 360 to 0, while each
        session keeps the `reserved_minutes` it was holding.

        PRD (§3.1): "**Hop three**, caused by hop two, takes every test session of a
        plan voided in hop two whose `state` is `SCHEDULED` or `IN_PROGRESS`, sets
        `state` to `CANCELLED`, and decrements the owning laboratory's
        `reserved_bench_minutes` by exactly that session's `reserved_minutes`."

        Design: Difficulty/transitive_cascade/specification_deprecation_cascades_three_hops_into_bench_minutes
        """
        ctx = _deprecation_cascade_program()

        assert_reserved_bench_minutes(
            ctx.laboratory_before, SESSION_A_MINUTES + SESSION_B_MINUTES
        )
        assert ctx.session_a["state"] == SESSION_SCHEDULED, (
            "session A must still have been SCHEDULED before the demotion, got "
            "{}".format(ctx.session_a["state"])
        )
        assert ctx.session_b["state"] == SESSION_IN_PROGRESS, (
            "session B must have been IN_PROGRESS before the demotion, got {}".format(
                ctx.session_b["state"]
            )
        )

        session_a = read_session(ctx.session_a["id"])
        session_b = read_session(ctx.session_b["id"])
        laboratory = read_laboratory(ctx.laboratory_id)

        assert session_a["state"] == SESSION_CANCELLED, (
            "hop three cancels the SCHEDULED session, expected {}, got {}".format(
                SESSION_CANCELLED, session_a["state"]
            )
        )
        assert session_b["state"] == SESSION_CANCELLED, (
            "hop three cancels the IN_PROGRESS session, expected {}, got {}".format(
                SESSION_CANCELLED, session_b["state"]
            )
        )
        assert session_a["reserved_minutes"] == SESSION_A_MINUTES, (
            "the cancelled session keeps its stored reserved_minutes, expected {}, "
            "got {}".format(SESSION_A_MINUTES, session_a["reserved_minutes"])
        )
        assert session_b["reserved_minutes"] == SESSION_B_MINUTES, (
            "the cancelled session keeps its stored reserved_minutes, expected {}, "
            "got {}".format(SESSION_B_MINUTES, session_b["reserved_minutes"])
        )
        assert_reserved_bench_minutes(laboratory, 0)

        cancelled, meta = validate_paginated(
            api_client.list_test_sessions(
                ADMIN_HEADERS, test_plan_id=ctx.plan_id, state=SESSION_CANCELLED
            )
        )
        assert meta["total_count"] == 2, (
            "both of the plan's live sessions were cancelled by hop three, expected "
            "total_count 2, got {}".format(meta["total_count"])
        )
        assert len(cancelled) == 2, (
            "the CANCELLED filter returns both sessions, expected 2 rows, got "
            "{}".format(len(cancelled))
        )

    def test_11_the_cascade_stops_at_hop_three_and_leaves_the_escrow_held(self):
        """The chain ends with the bench minutes: RETURNED_FOR_INFO still holds the
        escrowed fee, so neither the submission's `fee_escrowed_cents` nor the
        member's spendable balance moves.

        PRD (§3.2): "A submission's `fee_escrowed_cents` is non-zero exactly while
        its `state` is `SUBMITTED`, `IN_REVIEW` or `RETURNED_FOR_INFO`."

        Design: Difficulty/transitive_cascade/specification_deprecation_cascades_three_hops_into_bench_minutes
        """
        ctx = _deprecation_cascade_program()

        submission = read_submission(ctx.submission_id)
        member = read_member(ctx.member_id)

        assert submission["state"] == SUB_RETURNED_FOR_INFO, (
            "the cascade left the submission at RETURNED_FOR_INFO, got {}".format(
                submission["state"]
            )
        )
        assert_cents(
            submission["fee_escrowed_cents"], PINNED_FEE_CENTS, "fee_escrowed_cents"
        )
        assert_cents(member["escrowed_credit_cents"], PINNED_FEE_CENTS, "escrowed_credit_cents")
        assert_cents(
            member["credit_balance_cents"],
            PURCHASED_CENTS - PINNED_FEE_CENTS,
            "credit_balance_cents",
        )
        assert_cents(member["credits_consumed_cents"], 0, "credits_consumed_cents")
        assert_credit_ledger_invariant(member)
