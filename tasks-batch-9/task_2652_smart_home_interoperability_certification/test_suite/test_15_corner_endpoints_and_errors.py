"""Endpoint side effects and the top of the rejection ladder, end to end.

A second test plan supersedes the first and unwinds its bench booking; a
credential issuance, a public directory read and a compliance withdrawal walk one
device from review to revocation; and one unchanged submit request line, then a
handful of near-identical writes, are refused with a different error id at every
rung they reach.
"""

from test_helpers import (
    CLOCK_PROGRAMME_START,
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_NONCOMPLIANT,
    DAC_ISSUED,
    DAC_NOT_ISSUED,
    DAC_REVOKED,
    PLAN_DRAFT,
    PLAN_ISSUED,
    PLAN_VOIDED,
    PUB_PUBLISHED,
    PUB_UNPUBLISHED,
    PUB_WITHDRAWN,
    REVIEW_APPROVED,
    SESSION_CANCELLED,
    SUB_CERTIFIED,
    SUB_DRAFT,
    SUB_IN_REVIEW,
    SUB_REVIEW_COMPLETE,
    SUB_SUBMITTED,
    VOIDED_SUPERSEDED,
    append_results,
    build_laboratory,
    build_member,
    build_specification,
    complete_session,
    conformance_decision,
    execute_ip_commitment,
    feature,
    grant_tool_access,
    issue_credential,
    issue_test_plan,
    new_listing,
    new_member,
    new_plugfest,
    new_session,
    new_submission,
    new_test_plan,
    publish_listing,
    purchase_credits,
    ratify_specification,
    read_laboratory,
    read_ledger,
    read_listing,
    read_plugfest,
    read_session,
    read_submission,
    read_test_plan,
    result_line,
    same_instant,
    security_decision,
    set_clock,
    start_review,
    start_session,
    submit_submission,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_DEVICE_TYPE_MISMATCH,
    ERR_DUPLICATE_DAC_SERIAL,
    ERR_DUPLICATE_FEATURE_CODE,
    ERR_INVALID_LISTING_STATE,
    ERR_INVALID_SUBMISSION_STATE,
    ERR_INVALID_TEST_PLAN_STATE,
    ERR_IP_COMMITMENT_REQUIRED,
    ERR_LISTING_ALREADY_EXISTS,
    ERR_MEMBER_NOT_IN_GOOD_STANDING,
    ERR_MISSING_AUTH_HEADERS,
    ERR_REVIEW_ALREADY_DECIDED,
    ERR_UNAUTHORIZED,
    ERR_UNKNOWN_FEATURE_CODE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_credit_ledger_invariant,
    assert_listing_reference,
    assert_reserved_bench_minutes,
    assert_score,
    assert_states,
)
from test_helpers.factories import (
    feature_set_payload,
    firmware_revision_payload,
    issue_credential_payload,
    listing_payload,
    listing_withdraw_payload,
    participation_payload,
    security_decision_payload,
    submission_payload,
    test_plan_payload,
)
from test_helpers.fixtures import Ctx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    PUBLIC_HEADERS,
    SECURITY_HEADERS,
    headers_with_no_identity,
    make_headers,
    make_member_headers,
)

ONE_MANDATORY_LIGHTING_FEATURE = [feature("CORE_ONOFF", "MANDATORY", 20)]
ONOFF_AND_OPTIONAL_DIM = [
    feature("CORE_ONOFF", "MANDATORY", 20),
    feature("CORE_DIM", "OPTIONAL", 10),
]


def _plan_supersession_program():
    """One IN_REVIEW submission whose first plan is ISSUED and carries a single
    240-minute booking, with the submission's version recorded after every write."""
    set_clock(CLOCK_PROGRAMME_START)
    ctx = Ctx()
    ctx.update(build_specification(features=ONE_MANDATORY_LIGHTING_FEATURE))
    ctx.update(build_laboratory())
    ctx.update(build_member(scope_specification_id=ctx.specification_id))

    submission = new_submission(ctx.member_id, ctx.specification_id, ["CORE_ONOFF"])
    ctx.submission_id = submission["id"]
    ctx.v_created = submission["version"]
    ctx.v_submitted = submit_submission(ctx.submission_id, ctx.member_id)["version"]
    ctx.v_in_review = start_review(ctx.submission_id)["version"]

    plan_one = new_test_plan(ctx.submission_id, ctx.v_in_review)
    ctx.plan_one_id = plan_one["id"]
    issue_test_plan(ctx.plan_one_id)
    session = new_session(
        ctx.plan_one_id,
        ctx.laboratory_id,
        bench_index=1,
        window_start="2026-09-02T09:00:00Z",
        window_end="2026-09-02T13:00:00Z",
    )
    ctx.session_id = session["id"]
    ctx.v_after_plan_one = read_submission(ctx.submission_id)["version"]
    return ctx


class TestSecondPlanSupersedesTheFirst:
    """A second POST to the plan collection is a supersede, not a conflict."""

    def test_01_the_second_plan_voids_the_first_and_returns_its_reserved_minutes(self):
        """Creating a second plan voids the first with reason
        SUPERSEDED_BY_NEW_PLAN, cancels its SCHEDULED session, hands the
        laboratory's 240 reserved minutes back and bumps the submission again.

        PRD (§3.5): "Creating a plan for a submission that already has a live one is
        therefore not an error but a deliberate supersede: the prior plan is set to
        `VOIDED` with `voided_reason` `SUPERSEDED_BY_NEW_PLAN`, every session of that
        prior plan whose `state` is `SCHEDULED` or `IN_PROGRESS` is set to
        `CANCELLED`, and each such cancellation decrements the owning laboratory's
        `reserved_bench_minutes` by exactly that session's `reserved_minutes`."

        Design: Corner/endpoints/a_second_test_plan_supersedes_the_first_and_cancels_its_live_sessions
        """
        ctx = _plan_supersession_program()

        assert [ctx.v_created, ctx.v_submitted, ctx.v_in_review, ctx.v_after_plan_one] == [
            1,
            2,
            3,
            4,
        ], (
            "each accepted write bumps the submission's version by exactly one, "
            "expected [1, 2, 3, 4], got {}".format(
                [ctx.v_created, ctx.v_submitted, ctx.v_in_review, ctx.v_after_plan_one]
            )
        )
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 240)

        response = api_client.create_test_plan(
            test_plan_payload(ctx.submission_id, ctx.v_after_plan_one), ADMIN_HEADERS
        )
        plan_two = validate_success(response, 201)

        assert_states(plan_two, state=PLAN_DRAFT)
        superseded = read_test_plan(ctx.plan_one_id)
        assert_states(
            superseded, state=PLAN_VOIDED, voided_reason=VOIDED_SUPERSEDED
        )
        assert_states(read_session(ctx.session_id), state=SESSION_CANCELLED)
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 0)
        submission = read_submission(ctx.submission_id)
        assert submission["version"] == 5, (
            "the second plan create bumps the parent submission a fifth time, "
            "expected version 5, got {}".format(submission["version"])
        )
        assert_states(submission, state=SUB_IN_REVIEW)

    def test_02_both_plans_carry_the_same_closure_and_the_voided_plan_stays_listed(self):
        """The superseding plan resolves its own closure from the same declaration,
        so both plans hold an identical scope, and the collection read still returns
        the voided plan alongside the live one in creation order.

        PRD (§3.5): "The plan's scope is resolved once, at creation, by a **closure
        computation** over the specification's feature graph, and it is never
        recomputed."

        Design: Corner/endpoints/a_second_test_plan_supersedes_the_first_and_cancels_its_live_sessions
        """
        ctx = _plan_supersession_program()
        onoff_feature_set_id = ctx.feature_set_ids["CORE_ONOFF"]

        plan_two = validate_success(
            api_client.create_test_plan(
                test_plan_payload(ctx.submission_id, ctx.v_after_plan_one), ADMIN_HEADERS
            ),
            201,
        )

        for label, plan in (
            ("the superseded plan", read_test_plan(ctx.plan_one_id)),
            ("the superseding plan", read_test_plan(plan_two["id"])),
        ):
            assert plan["included_feature_set_ids"] == [onoff_feature_set_id], (
                "{} includes only the single mandatory feature set, expected [{}], "
                "got {}".format(label, onoff_feature_set_id, plan["included_feature_set_ids"])
            )
            assert plan["required_case_count"] == 20, (
                "{} requires the feature set's 20 cases, got {}".format(
                    label, plan["required_case_count"]
                )
            )
            assert plan["mandatory_case_count"] == 20, (
                "{} carries 20 mandatory cases, got {}".format(
                    label, plan["mandatory_case_count"]
                )
            )
            assert plan["optional_case_count"] == 0, (
                "{} declares no optional feature set, expected 0 optional cases, "
                "got {}".format(label, plan["optional_case_count"])
            )

        plans, meta = validate_paginated(
            api_client.list_test_plans(
                ADMIN_HEADERS, submission_id=ctx.submission_id, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 2, (
            "the voided plan stays in the collection, expected total_count 2, "
            "got {}".format(meta["total_count"])
        )
        assert [row["id"] for row in plans] == [ctx.plan_one_id, plan_two["id"]], (
            "plans are listed created_at ascending, expected [{}, {}], got {}".format(
                ctx.plan_one_id, plan_two["id"], [row["id"] for row in plans]
            )
        )


def _carry_to_review_complete(ctx, declared_codes, day):
    """Walk one submission from DRAFT to REVIEW_COMPLETE inside a single day."""
    submission = new_submission(ctx.member_id, ctx.specification_id, declared_codes)
    submission_id = submission["id"]
    fee_cents = submission["certification_fee_cents"]
    submit_submission(submission_id, ctx.member_id)
    in_review = start_review(submission_id)
    plan = new_test_plan(submission_id, in_review["version"])
    issue_test_plan(plan["id"])
    session = new_session(
        plan["id"],
        ctx.laboratory_id,
        bench_index=1,
        window_start="{}T09:00:00Z".format(day),
        window_end="{}T13:00:00Z".format(day),
    )
    set_clock("{}T09:00:00Z".format(day))
    start_session(session["id"], ctx.laboratory_id)
    append_results(
        session["id"],
        ctx.laboratory_id,
        [result_line(ctx.feature_set_ids[code], "PASS") for code in declared_codes],
    )
    set_clock("{}T12:00:00Z".format(day))
    complete_session(session["id"], ctx.laboratory_id)
    security_decision(submission_id, "APPROVE")
    decided = conformance_decision(submission_id, "APPROVE")
    return Ctx(
        submission_id=submission_id,
        fee_cents=fee_cents,
        plan_id=plan["id"],
        session_id=session["id"],
        final_score=decided["final_readiness_score"],
    )


def _two_review_complete_submissions():
    """One member, two lighting devices carried to REVIEW_COMPLETE on consecutive
    days: the first declares one feature code, the second declares both."""
    set_clock(CLOCK_PROGRAMME_START)
    ctx = Ctx()
    ctx.update(build_specification(features=ONOFF_AND_OPTIONAL_DIM))
    ctx.update(build_laboratory())
    ctx.update(build_member(scope_specification_id=ctx.specification_id))
    ctx.first = _carry_to_review_complete(ctx, ["CORE_ONOFF"], "2026-09-02")
    ctx.second = _carry_to_review_complete(ctx, ["CORE_ONOFF", "CORE_DIM"], "2026-09-03")
    return ctx


class TestCredentialIssuanceDirectoryAndWithdrawal:
    """Issuance, the consumer directory and a compliance withdrawal in sequence."""

    def test_03_a_listing_opens_unpublished_and_a_second_one_is_refused(self):
        """The first listing for a REVIEW_COMPLETE submission opens UNPUBLISHED and
        COMPLIANT as LST-000001, and a second listing for the same submission is
        refused outright.

        PRD (§3.9): "The submission must have cleared both review axes — its `state`
        must be `REVIEW_COMPLETE` or `CERTIFIED`, and anything earlier is refused with
        `ERR_INVALID_SUBMISSION_STATE` — and it must not already have a listing, a
        second attempt being refused with `ERR_LISTING_ALREADY_EXISTS`."

        Design: Corner/endpoints/credential_issuance_then_the_public_directory_and_a_withdrawal
        """
        ctx = _two_review_complete_submissions()

        listing = validate_success(
            api_client.create_listing(
                listing_payload(ctx.first.submission_id), ADMIN_HEADERS
            ),
            201,
        )

        assert_listing_reference(listing["listing_reference"], 1)
        assert_states(
            listing,
            member_id=ctx.member_id,
            publication_status=PUB_UNPUBLISHED,
            compliance_status=COMPLIANCE_COMPLIANT,
            published_at=None,
            recert_classification=None,
            firmware_revision_count=0,
        )
        assert listing["declared_features"] == ["CORE_ONOFF"], (
            "the listing declares the one feature code of the submission's plan, "
            "expected ['CORE_ONOFF'], got {}".format(listing["declared_features"])
        )

        repeat = api_client.create_listing(
            listing_payload(ctx.first.submission_id), ADMIN_HEADERS
        )
        validate_error(repeat, ERR_LISTING_ALREADY_EXISTS)

    def test_04_issuance_consumes_the_escrow_rather_than_releasing_it(self):
        """Issuing the credential certifies the device, stamps the clock's instant and
        moves the escrowed fee into consumed credit, leaving the balance short by both
        the consumed fee and the second submission's still-escrowed fee.

        PRD (§3.8): "Issuance moves `REVIEW_COMPLETE → CERTIFIED`, stamps
        `certified_at`, moves `dac_state` `NOT_ISSUED → ISSUED` with the supplied
        `dac_serial` stored, and *consumes* rather than releases the escrow: the
        member's `escrowed_credit_cents` falls by `fee_escrowed_cents`, its
        `credits_consumed_cents` rises by the same figure, and `fee_escrowed_cents`
        becomes 0."

        Design: Corner/endpoints/credential_issuance_then_the_public_directory_and_a_withdrawal
        """
        ctx = _two_review_complete_submissions()

        assert_cents(ctx.first.fee_cents, 135000, "the first submission's pinned fee")
        assert_cents(ctx.second.fee_cents, 150000, "the second submission's pinned fee")
        assert_score(ctx.first.final_score, "85.00", "the first FINAL readiness score")
        assert_score(ctx.second.final_score, "85.00", "the second FINAL readiness score")

        certified = validate_success(
            api_client.issue_credential(
                ctx.first.submission_id,
                issue_credential_payload("DAC-000001"),
                ADMIN_HEADERS,
            )
        )

        assert_states(
            certified,
            state=SUB_CERTIFIED,
            dac_state=DAC_ISSUED,
            dac_serial="DAC-000001",
            fee_escrowed_cents=0,
        )
        assert same_instant(certified["certified_at"], "2026-09-03T12:00:00Z"), (
            "certified_at is stamped from the logical clock, expected "
            "2026-09-03T12:00:00Z, got {!r}".format(certified["certified_at"])
        )
        ledger = read_ledger(ctx.member_id, variant="AVAILABLE")
        assert_cents(ledger["credits_consumed_cents"], 135000, "credits_consumed_cents")
        assert_cents(ledger["escrowed_credit_cents"], 150000, "escrowed_credit_cents")
        assert_cents(ledger["balance_cents"], 715000, "AVAILABLE balance_cents")
        assert_credit_ledger_invariant(ledger)

    def test_05_a_taken_serial_is_refused_without_touching_the_second_escrow(self):
        """The serial the first device took makes the second device's issuance fail,
        the already certified device cannot take a second serial, and only the accepted
        issuances move money.

        PRD (§3.8): "The administrator supplies a `dac_serial` of 1 to 64 characters
        which must not already be held by any other submission, a collision being
        refused with `ERR_DUPLICATE_DAC_SERIAL`."

        Design: Corner/endpoints/credential_issuance_then_the_public_directory_and_a_withdrawal
        """
        ctx = _two_review_complete_submissions()
        issue_credential(ctx.first.submission_id, "DAC-000001")

        collision = api_client.issue_credential(
            ctx.second.submission_id,
            issue_credential_payload("DAC-000001"),
            ADMIN_HEADERS,
        )
        validate_error(collision, ERR_DUPLICATE_DAC_SERIAL)

        untouched = read_submission(ctx.second.submission_id)
        assert_states(
            untouched,
            state=SUB_REVIEW_COMPLETE,
            dac_state=DAC_NOT_ISSUED,
            dac_serial=None,
            fee_escrowed_cents=150000,
        )

        reissue = api_client.issue_credential(
            ctx.first.submission_id,
            issue_credential_payload("DAC-000002"),
            ADMIN_HEADERS,
        )
        validate_error(reissue, ERR_INVALID_SUBMISSION_STATE)
        assert_states(
            read_submission(ctx.first.submission_id),
            state=SUB_CERTIFIED,
            dac_serial="DAC-000001",
        )

        issue_credential(ctx.second.submission_id, "DAC-000002")
        ledger = read_ledger(ctx.member_id, variant="AVAILABLE")
        assert_cents(ledger["credits_purchased_cents"], 1000000, "credits_purchased_cents")
        assert_cents(ledger["credits_consumed_cents"], 285000, "credits_consumed_cents")
        assert_cents(ledger["escrowed_credit_cents"], 0, "escrowed_credit_cents")
        assert_cents(ledger["balance_cents"], 715000, "AVAILABLE balance_cents")
        assert_credit_ledger_invariant(ledger)

    def test_06_publication_stamps_the_clock_and_the_directory_pages_both_listings(self):
        """Publishing the first listing stamps published_at from the clock, the second
        listing takes the next ordinal with its feature codes sorted ascending, and the
        public directory pages and filters the pair.

        PRD (§3.9): "Publication sets `publication_status` to `PUBLISHED`, stamps
        `published_at` from the logical clock, and recomputes `declared_features` from
        the submission's non-`VOIDED` test plan, so a plan that gained feature sets
        since the last publication refreshes the consumer-visible declaration."

        Design: Corner/endpoints/credential_issuance_then_the_public_directory_and_a_withdrawal
        """
        ctx = _two_review_complete_submissions()
        issue_credential(ctx.first.submission_id, "DAC-000001")
        first_listing = new_listing(ctx.first.submission_id)

        published = validate_success(
            api_client.publish_listing(first_listing["id"], headers=ADMIN_HEADERS)
        )

        assert_states(published, publication_status=PUB_PUBLISHED)
        assert same_instant(published["published_at"], "2026-09-03T12:00:00Z"), (
            "published_at is stamped from the logical clock, expected "
            "2026-09-03T12:00:00Z, got {!r}".format(published["published_at"])
        )

        second_listing = validate_success(
            api_client.create_listing(
                listing_payload(ctx.second.submission_id), ADMIN_HEADERS
            ),
            201,
        )
        assert_listing_reference(second_listing["listing_reference"], 2)
        assert second_listing["declared_features"] == ["CORE_DIM", "CORE_ONOFF"], (
            "declared_features are ordered by feature_code ascending rather than by "
            "declaration order, expected ['CORE_DIM', 'CORE_ONOFF'], got {}".format(
                second_listing["declared_features"]
            )
        )

        page_one, meta_one = validate_paginated(
            api_client.list_listings(PUBLIC_HEADERS, limit=1, offset=0)
        )
        assert meta_one["total_count"] == 2, (
            "the directory holds both listings, expected total_count 2, got {}".format(
                meta_one["total_count"]
            )
        )
        assert meta_one["has_more"] is True, (
            "a second row remains beyond the first page, expected has_more true, "
            "got {!r}".format(meta_one["has_more"])
        )
        assert page_one[0]["id"] == first_listing["id"], (
            "the oldest listing heads the first page, expected {}, got {}".format(
                first_listing["id"], page_one[0]["id"]
            )
        )
        page_two, meta_two = validate_paginated(
            api_client.list_listings(PUBLIC_HEADERS, limit=1, offset=1)
        )
        assert meta_two["has_more"] is False, (
            "nothing remains beyond the second page, expected has_more false, "
            "got {!r}".format(meta_two["has_more"])
        )
        assert page_two[0]["id"] == second_listing["id"], (
            "the newer listing follows in created_at order, expected {}, got {}".format(
                second_listing["id"], page_two[0]["id"]
            )
        )

        by_status, status_meta = validate_paginated(
            api_client.list_listings(
                PUBLIC_HEADERS, publication_status=PUB_PUBLISHED, limit=10, offset=0
            )
        )
        assert status_meta["total_count"] == 1, (
            "only the first listing is PUBLISHED, expected total_count 1, got {}".format(
                status_meta["total_count"]
            )
        )
        assert by_status[0]["id"] == first_listing["id"], (
            "the PUBLISHED filter returns the first listing, expected {}, got {}".format(
                first_listing["id"], by_status[0]["id"]
            )
        )
        _, member_meta = validate_paginated(
            api_client.list_listings(
                PUBLIC_HEADERS, member_id=ctx.member_id, limit=10, offset=0
            )
        )
        assert member_meta["total_count"] == 2, (
            "both listings belong to the one member, expected total_count 2, "
            "got {}".format(member_meta["total_count"])
        )
        by_submission, submission_meta = validate_paginated(
            api_client.list_listings(
                PUBLIC_HEADERS,
                submission_id=ctx.second.submission_id,
                limit=10,
                offset=0,
            )
        )
        assert submission_meta["total_count"] == 1, (
            "one listing publishes the second submission, expected total_count 1, "
            "got {}".format(submission_meta["total_count"])
        )
        assert by_submission[0]["id"] == second_listing["id"], (
            "the submission filter returns the second listing, expected {}, "
            "got {}".format(second_listing["id"], by_submission[0]["id"])
        )

    def test_07_withdrawal_moves_both_axes_revokes_the_credential_and_locks_revisions(self):
        """A compliance withdrawal flips the published listing to WITHDRAWN and
        NONCOMPLIANT and revokes the linked credential while the submission stays
        CERTIFIED, after which no firmware revision can be reported against it.

        PRD (§3.9): "It sets `publication_status` to `WITHDRAWN`, sets
        `compliance_status` to `NONCOMPLIANT`, and, where the linked submission's
        `dac_state` is `ISSUED`, sets that `dac_state` to `REVOKED`."

        Design: Corner/endpoints/credential_issuance_then_the_public_directory_and_a_withdrawal
        """
        ctx = _two_review_complete_submissions()
        issue_credential(ctx.first.submission_id, "DAC-000001")
        listing = new_listing(ctx.first.submission_id)
        published = publish_listing(listing["id"])
        assert_states(published, compliance_status=COMPLIANCE_COMPLIANT)

        withdrawn = validate_success(
            api_client.withdraw_listing(
                listing["id"],
                listing_withdraw_payload("counterfeit attestation key reported"),
                COMPLIANCE_HEADERS,
            )
        )

        assert_states(
            withdrawn,
            publication_status=PUB_WITHDRAWN,
            compliance_status=COMPLIANCE_NONCOMPLIANT,
        )
        assert_states(
            read_submission(ctx.first.submission_id),
            state=SUB_CERTIFIED,
            dac_state=DAC_REVOKED,
            dac_serial="DAC-000001",
        )

        refused = api_client.report_firmware_revision(
            listing["id"],
            firmware_revision_payload(withdrawn["version"], firmware_version="1.1.0"),
            ADMIN_HEADERS,
        )
        validate_error(refused, ERR_INVALID_LISTING_STATE)
        assert_states(read_listing(listing["id"]), firmware_revision_count=0)

        rows, meta = validate_paginated(
            api_client.list_listings(
                PUBLIC_HEADERS, publication_status=PUB_WITHDRAWN, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 1, (
            "the withdrawn listing stays in the directory, expected total_count 1, "
            "got {}".format(meta["total_count"])
        )
        assert rows[0]["id"] == listing["id"], (
            "the WITHDRAWN filter returns the withdrawn listing, expected {}, "
            "got {}".format(listing["id"], rows[0]["id"])
        )


def _submit_ladder_program():
    """Two ratified versions, a bare member owning a DRAFT submission pinned to the
    first, and a second member fully onboarded and funded against that same version."""
    set_clock(CLOCK_PROGRAMME_START)
    ctx = Ctx()
    ctx.first_specification_id = build_specification(
        features=ONE_MANDATORY_LIGHTING_FEATURE
    ).specification_id
    ctx.second_specification_id = build_specification(
        features=ONE_MANDATORY_LIGHTING_FEATURE
    ).specification_id

    owner = new_member()
    ctx.owner_id = owner["id"]
    ctx.owner_headers = make_member_headers(ctx.owner_id)
    other = build_member(scope_specification_id=ctx.first_specification_id)
    ctx.other_id = other.member_id
    ctx.other_headers = other.member_headers

    submission = new_submission(
        ctx.owner_id, ctx.first_specification_id, ["CORE_ONOFF"]
    )
    ctx.submission_id = submission["id"]
    return ctx


class TestSubmitLadderFromHeadersToStanding:
    """One unchanged submit request line, refused a rung at a time."""

    def test_08_an_absent_and_an_unrecognised_role_header_both_fail_authentication(self):
        """Submitting with no identity headers at all, and submitting with a role
        string outside the seven declared roles, are both authentication failures
        rather than authorization failures.

        PRD (§2.1): "If either header is absent, or if `X-User-Role` carries a string
        that is not one of those seven, the request is rejected with
        `ERR_MISSING_AUTH_HEADERS` and HTTP 401."

        Design: Corner/errors/missing_headers_then_role_then_ownership_then_standing_on_one_submit
        """
        ctx = _submit_ladder_program()

        bare = api_client.submit_submission(
            ctx.submission_id, headers=headers_with_no_identity()
        )
        validate_error(bare, ERR_MISSING_AUTH_HEADERS)
        assert bare.status_code == 401, (
            "a request carrying neither identity header is refused with 401, got "
            "{}".format(bare.status_code)
        )

        unknown_role = api_client.submit_submission(
            ctx.submission_id, headers=make_headers("Auditor", "AUD1")
        )
        validate_error(unknown_role, ERR_MISSING_AUTH_HEADERS)
        assert unknown_role.status_code == 401, (
            "an X-User-Role of 'Auditor' fails authentication with 401 rather than "
            "authorization with 403, got {}".format(unknown_role.status_code)
        )

    def test_09_an_unlisted_role_and_the_wrong_owner_are_both_refused_with_403(self):
        """A ProgramAdmin cannot submit on a member's behalf, and a fully onboarded
        member that does not own the submission is refused on ownership alone.

        PRD (§2.1): "Ownership enforcement is not global — it applies to a fixed set
        of twelve write operations, and on any of them a mismatch also yields
        `ERR_UNAUTHORIZED` with HTTP 403."

        Design: Corner/errors/missing_headers_then_role_then_ownership_then_standing_on_one_submit
        """
        ctx = _submit_ladder_program()

        as_admin = api_client.submit_submission(ctx.submission_id, headers=ADMIN_HEADERS)
        validate_error(as_admin, ERR_UNAUTHORIZED)
        assert as_admin.status_code == 403, (
            "submit lists only the Member role, so a ProgramAdmin is refused with "
            "403, got {}".format(as_admin.status_code)
        )

        as_other_member = api_client.submit_submission(
            ctx.submission_id, headers=ctx.other_headers
        )
        validate_error(as_other_member, ERR_UNAUTHORIZED)
        assert as_other_member.status_code == 403, (
            "a member that would pass every business rule is still refused on "
            "ownership with 403, got {}".format(as_other_member.status_code)
        )
        assert_states(read_submission(ctx.submission_id), state=SUB_DRAFT)

    def test_10_lost_standing_is_reported_before_the_empty_credit_account(self):
        """The owning member has neither commitment, nor tool access, nor a single
        cent of credit, and the refusal names its standing rather than its money while
        the submission stays exactly as it was.

        PRD (§2.8): "A submit request from a member who has both lost good standing
        *and* lacks the credit to cover the pinned fee is rejected with
        `ERR_MEMBER_NOT_IN_GOOD_STANDING` and HTTP 409 — never with
        `ERR_INSUFFICIENT_CREDIT`."

        Design: Corner/errors/missing_headers_then_role_then_ownership_then_standing_on_one_submit
        """
        ctx = _submit_ladder_program()

        refused = api_client.submit_submission(
            ctx.submission_id, headers=ctx.owner_headers
        )

        validate_error(refused, ERR_MEMBER_NOT_IN_GOOD_STANDING)
        assert refused.status_code == 409, (
            "a member out of good standing is refused with 409, got {}".format(
                refused.status_code
            )
        )
        assert_states(
            read_submission(ctx.submission_id),
            state=SUB_DRAFT,
            submitted_at=None,
            fee_escrowed_cents=0,
        )

    def test_11_a_commitment_on_the_wrong_version_fails_where_the_right_one_passes(self):
        """Once the owner is funded and in good standing the refusal moves to the
        scope of its commitment, and the identical request on a submission pinned to
        the committed version escrows the fee and succeeds.

        PRD (§2.8): "**IP scope.** `ERR_IP_COMMITMENT_REQUIRED` (409) when the
        member's `ip_scope_specification_id` does not equal the submission's pinned
        `specification_id`."

        Design: Corner/errors/missing_headers_then_role_then_ownership_then_standing_on_one_submit
        """
        ctx = _submit_ladder_program()
        execute_ip_commitment(ctx.owner_id, ctx.second_specification_id)
        grant_tool_access(ctx.owner_id)
        purchase_credits(ctx.owner_id, 1000000)

        out_of_scope = api_client.submit_submission(
            ctx.submission_id, headers=ctx.owner_headers
        )
        validate_error(out_of_scope, ERR_IP_COMMITMENT_REQUIRED)
        assert_states(
            read_submission(ctx.submission_id),
            state=SUB_DRAFT,
            submitted_at=None,
            fee_escrowed_cents=0,
        )

        twin = new_submission(
            ctx.owner_id, ctx.second_specification_id, ["CORE_ONOFF"]
        )
        accepted = validate_success(
            api_client.submit_submission(twin["id"], headers=ctx.owner_headers)
        )

        assert_states(accepted, state=SUB_SUBMITTED)
        assert_cents(accepted["fee_escrowed_cents"], 135000, "fee_escrowed_cents")
        ledger = read_ledger(ctx.owner_id, variant="AVAILABLE")
        assert_cents(ledger["balance_cents"], 865000, "AVAILABLE balance_cents")
        assert_credit_ledger_invariant(ledger)


def _mismatch_program():
    """A DRAFT version carrying one lighting feature set, a separate RATIFIED version,
    and a plugfest pinned to that separate version with registration still open."""
    set_clock(CLOCK_PROGRAMME_START)
    ctx = Ctx()
    device_spec = build_specification(
        features=ONE_MANDATORY_LIGHTING_FEATURE, ratify=False
    )
    ctx.device_specification_id = device_spec.specification_id
    ctx.onoff_feature_set_id = device_spec.feature_set_ids["CORE_ONOFF"]
    ctx.event_specification_id = build_specification(
        features=ONE_MANDATORY_LIGHTING_FEATURE
    ).specification_id
    ctx.update(build_laboratory())
    plugfest = new_plugfest(
        ctx.laboratory_id,
        ctx.event_specification_id,
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T17:00:00Z",
        registration_deadline="2026-09-08T00:00:00Z",
        min_distinct_vendors=2,
    )
    ctx.plugfest_id = plugfest["id"]
    return ctx


def _with_a_funded_owner(ctx):
    """Ratify the device's own version and onboard a funded member scoped to it."""
    ratify_specification(ctx.device_specification_id)
    ctx.update(build_member(scope_specification_id=ctx.device_specification_id))
    return ctx


def _submission_in_review(ctx):
    """One submitted device picked up for review by the conformance reviewer."""
    submission = new_submission(
        ctx.member_id, ctx.device_specification_id, ["CORE_ONOFF"]
    )
    ctx.submission_id = submission["id"]
    submit_submission(ctx.submission_id, ctx.member_id)
    ctx.submission = start_review(ctx.submission_id)
    return ctx


class TestFeatureCodePlanStateAndCrossSpecificationMismatches:
    """Five refusals, each shown beside the nearly identical request that passes."""

    def test_12_a_feature_code_repeats_across_device_classes_but_not_within_one(self):
        """Re-declaring CORE_ONOFF for the same version and device class is refused
        whatever obligation or case count it carries, while the same code on a second
        device class of that version is accepted.

        PRD (§3.1): "Its `feature_code` — a stable machine-readable identifier such as
        `CORE_ONOFF`, between 1 and 48 characters and composed of uppercase letters,
        digits and underscores — must be unique within its own `specification_id` and
        `device_type` pair; the same code may therefore legitimately appear on a
        lighting feature set and on a thermostat feature set of the same version, but a
        repeat within one pair is rejected with `ERR_DUPLICATE_FEATURE_CODE`."

        Design: Corner/errors/feature_code_plan_state_and_cross_specification_mismatches_each_have_a_trigger
        """
        ctx = _mismatch_program()

        repeat = api_client.create_feature_set(
            feature_set_payload(
                ctx.device_specification_id,
                device_type="LIGHTING",
                feature_code="CORE_ONOFF",
                obligation="OPTIONAL",
                test_case_count=5,
            ),
            ADMIN_HEADERS,
        )
        validate_error(repeat, ERR_DUPLICATE_FEATURE_CODE)

        other_class = validate_success(
            api_client.create_feature_set(
                feature_set_payload(
                    ctx.device_specification_id,
                    device_type="THERMOSTAT",
                    feature_code="CORE_ONOFF",
                    obligation="MANDATORY",
                    test_case_count=12,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api_client.list_feature_sets(
                ADMIN_HEADERS,
                specification_id=ctx.device_specification_id,
                limit=10,
                offset=0,
            )
        )
        assert meta["total_count"] == 2, (
            "the version holds the lighting and the thermostat feature set and "
            "nothing else, expected total_count 2, got {}".format(meta["total_count"])
        )
        assert [row["id"] for row in rows] == [
            ctx.onoff_feature_set_id,
            other_class["id"],
        ], (
            "feature sets are listed created_at ascending, expected [{}, {}], "
            "got {}".format(
                ctx.onoff_feature_set_id,
                other_class["id"],
                [row["id"] for row in rows],
            )
        )

    def test_13_a_declared_code_that_resolves_to_nothing_is_refused_with_422(self):
        """A declaration naming a code that no feature set of the pinned version
        carries is refused, and the identical request with that one code removed opens
        the submission.

        PRD (§3.4): "The array may be empty but must contain no duplicates, and every
        entry must resolve to a feature set of the pinned specification whose
        `device_type` equals the submission's own — a code belonging to another device
        class, or to no feature set at all, is rejected with
        `ERR_UNKNOWN_FEATURE_CODE`."

        Design: Corner/errors/feature_code_plan_state_and_cross_specification_mismatches_each_have_a_trigger
        """
        ctx = _with_a_funded_owner(_mismatch_program())
        payload = submission_payload(
            ctx.member_id,
            ctx.device_specification_id,
            ["CORE_ONOFF", "CORE_SCENE"],
            device_model="AL-100",
            attestation_key_fingerprint="AA:00:00:01",
        )

        refused = api_client.create_submission(payload, ctx.member_headers)
        validate_error(refused, ERR_UNKNOWN_FEATURE_CODE)
        assert refused.status_code == 422, (
            "an unresolvable declared code is a payload-resolution failure carrying "
            "422, got {}".format(refused.status_code)
        )

        payload["declared_feature_codes"] = ["CORE_ONOFF"]
        accepted = validate_success(
            api_client.create_submission(payload, ctx.member_headers), 201
        )
        assert_states(accepted, state=SUB_DRAFT)
        assert_cents(
            accepted["certification_fee_cents"], 135000, "certification_fee_cents"
        )

    def test_14_a_device_pinned_to_another_version_cannot_register_for_the_event(self):
        """The plugfest and the submission both exist, the member is in good standing
        and registration is still open, yet the baselines disagree, so the refusal is a
        coherence failure and no junction row is written.

        PRD (§3.7): "The `member_id` must equal the submission's own `member_id` as
        well as the acting `X-User-ID`, and the submission's pinned `specification_id`
        must equal the plugfest's `specification_id` — a device certified against one
        baseline cannot be exercised at an event running another, and the mismatch is
        rejected with `ERR_DEVICE_TYPE_MISMATCH`."

        Design: Corner/errors/feature_code_plan_state_and_cross_specification_mismatches_each_have_a_trigger
        """
        ctx = _with_a_funded_owner(_mismatch_program())
        submission = new_submission(
            ctx.member_id, ctx.device_specification_id, ["CORE_ONOFF"]
        )
        submit_submission(submission["id"], ctx.member_id)

        refused = api_client.create_participation(
            participation_payload(ctx.plugfest_id, ctx.member_id, submission["id"]),
            ctx.member_headers,
        )

        validate_error(refused, ERR_DEVICE_TYPE_MISMATCH)
        assert refused.status_code == 422, (
            "a cross-reference coherence failure carries 422 rather than a 404, "
            "got {}".format(refused.status_code)
        )
        plugfest = read_plugfest(ctx.plugfest_id)
        assert plugfest["distinct_vendor_count"] == 0, (
            "the refused registration counts no vendor, expected "
            "distinct_vendor_count 0, got {}".format(plugfest["distinct_vendor_count"])
        )
        _, meta = validate_paginated(
            api_client.list_participations(
                ADMIN_HEADERS, plugfest_id=ctx.plugfest_id, limit=10, offset=0
            )
        )
        assert meta["total_count"] == 0, (
            "the refused registration created no participation row, expected "
            "total_count 0, got {}".format(meta["total_count"])
        )

    def test_15_a_plan_can_only_be_issued_once(self):
        """The first issue releases the plan to the laboratory network; a second issue
        of the same plan is refused and leaves the plan exactly as the first one left
        it.

        PRD (§3.5): "Issuing a plan that is not `DRAFT` draws
        `ERR_INVALID_TEST_PLAN_STATE`."

        Design: Corner/errors/feature_code_plan_state_and_cross_specification_mismatches_each_have_a_trigger
        """
        ctx = _submission_in_review(_with_a_funded_owner(_mismatch_program()))
        plan = new_test_plan(ctx.submission_id, ctx.submission["version"])
        issued = validate_success(
            api_client.issue_test_plan(plan["id"], headers=ADMIN_HEADERS)
        )
        assert_states(issued, state=PLAN_ISSUED)

        repeat = api_client.issue_test_plan(plan["id"], headers=ADMIN_HEADERS)

        validate_error(repeat, ERR_INVALID_TEST_PLAN_STATE)
        unchanged = read_test_plan(plan["id"])
        assert_states(unchanged, state=PLAN_ISSUED)
        assert unchanged["version"] == issued["version"], (
            "the refused second issue mutates nothing, so the plan's version stays "
            "at {}, got {}".format(issued["version"], unchanged["version"])
        )

    def test_16_a_review_axis_accepts_exactly_one_decision(self):
        """The security axis is APPROVED by the first decision, and the reviewer's
        attempted reversal is refused without overwriting any of the axis fields it
        carried.

        PRD (§2.8): "**Review already decided.** `ERR_REVIEW_ALREADY_DECIDED` (409)
        when the addressed review axis has already left `PENDING` — a conformance
        decision or a security decision cannot be recorded twice, and a
        return-for-info requires `conformance_review_state` to still be `PENDING`."

        Design: Corner/errors/feature_code_plan_state_and_cross_specification_mismatches_each_have_a_trigger
        """
        ctx = _submission_in_review(_with_a_funded_owner(_mismatch_program()))
        security_decision(ctx.submission_id, "APPROVE")

        reversal = api_client.security_decision(
            ctx.submission_id,
            security_decision_payload(
                "REJECT",
                secure_boot_verified=False,
                verified_firmware_update_capability="NONE",
            ),
            SECURITY_HEADERS,
        )

        validate_error(reversal, ERR_REVIEW_ALREADY_DECIDED)
        assert reversal.status_code == 409, (
            "a second decision on a settled axis is refused with 409, got {}".format(
                reversal.status_code
            )
        )
        submission = read_submission(ctx.submission_id)
        assert_states(
            submission,
            state=SUB_IN_REVIEW,
            security_review_state=REVIEW_APPROVED,
            secure_boot_verified=True,
            verified_firmware_update_capability="OTA_SIGNED",
        )
