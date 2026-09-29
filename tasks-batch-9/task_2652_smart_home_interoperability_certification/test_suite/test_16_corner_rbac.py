"""Role authorization, entity-backed ownership and the segregation-of-duties gate.

Three concerns share this file because all three are decided on the identity
headers alone: the endpoint's authorized-role list, the ownership comparison that
ties a Member or TestLaboratory principal to its own row, and the recorded
conformance identifier that locks its holder out of the security decision.
"""

from test_helpers import (
    MEMBER_REGISTERED,
    REVIEW_APPROVED,
    REVIEW_PENDING,
    REVIEW_RETURNED,
    SESSION_CANCELLED,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    SUB_IN_REVIEW,
    SUB_RETURNED_FOR_INFO,
    SUB_WITHDRAWN,
    UNKNOWN_UUID,
    assert_cents,
    assert_reserved_bench_minutes,
    assert_states,
    build_laboratory,
    build_member,
    build_program,
    feature,
    new_laboratory,
    new_member,
    read_laboratory,
    read_ledger,
    read_member,
    read_session,
    read_submission,
    result_line,
    set_clock,
    start_review,
    submit_submission,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_LISTING_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SUBMISSION_NOT_FOUND,
    ERR_TEST_SESSION_NOT_FOUND,
    ERR_UNAUTHORIZED,
)
from test_helpers.factories import (
    accreditation_payload,
    cancel_session_payload,
    credit_purchase_payload,
    feature_set_payload,
    issue_credential_payload,
    listing_payload,
    listing_withdraw_payload,
    member_payload,
    noncompliance_case_payload,
    participation_payload,
    results_payload,
    return_for_info_payload,
    security_decision_payload,
    specification_payload,
    submission_payload,
    tool_access_payload,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    CONFORMANCE_HEADERS,
    CONFORMANCE_HEADERS_2,
    CONFORMANCE_REVIEWER_1,
    CONFORMANCE_REVIEWER_2,
    PUBLIC_HEADERS,
    SECURITY_HEADERS,
    make_laboratory_headers,
    make_member_headers,
    make_security_headers,
)

#: One lighting feature set worth 20 test cases, which pins a 135000-cent fee on
#: an ADOPTER's STANDARD lighting submission declaring exactly that one code.
ONE_LIGHTING_FEATURE = [feature("CORE_ONOFF", "MANDATORY", 20)]
LIGHTING_FEE_CENTS = 135000
FUNDED_CENTS = 1000000


def _identity_only_program():
    """One member row and one laboratory row, so that the entity-backed
    identities resolve, and nothing else at all."""
    set_clock()
    member = new_member(legal_name="Acme Devices", contact_email="ops@acme.test")
    laboratory = new_laboratory(name="Northbridge Lab")
    return member["id"], laboratory["id"]


def _refused(label, response):
    """Assert one call was turned away on role grounds."""
    assert response.status_code == 403, (
        "{} must be refused with HTTP 403, got {}".format(label, response.status_code)
    )
    validate_error(response, ERR_UNAUTHORIZED)


def _total_count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


class TestExclusiveOperationsAreRefusedToTheOtherRoles:
    """Each endpoint's authorized-role list, exercised from an almost empty
    database against a member row and a laboratory row that exist only so the
    entity-backed identities resolve."""

    def test_01_every_exclusive_write_is_refused_to_a_role_outside_its_list(self):
        """Fourteen writes, each addressed by a role the endpoint does not list,
        are all refused with ERR_UNAUTHORIZED and HTTP 403, and none of them
        stores a row.

        PRD (§4): "The Authorized Role(s) column lists the roles permitted to call
        the endpoint; any other role is refused with `ERR_UNAUTHORIZED` and HTTP
        403, as is an ownership mismatch by a `Member` or `TestLaboratory` actor
        within a permitted role."

        Design: Corner/rbac/every_roles_exclusive_operations_are_refused_to_the_other_six_roles
        """
        member_id, laboratory_id = _identity_only_program()
        member_headers = make_member_headers(member_id)
        laboratory_headers = make_laboratory_headers(laboratory_id)

        _refused(
            "POST /specifications as Member",
            api_client.create_specification(
                specification_payload(version_label="SHIC-9.9"), member_headers
            ),
        )
        _refused(
            "POST /feature-sets as ConformanceReviewer",
            api_client.create_feature_set(
                feature_set_payload(UNKNOWN_UUID, feature_code="CORE_ONOFF"),
                CONFORMANCE_HEADERS,
            ),
        )
        _refused(
            "POST /members as ComplianceOfficer",
            api_client.create_member(
                member_payload(legal_name="Ghost Devices"), COMPLIANCE_HEADERS
            ),
        )
        _refused(
            "POST /test-laboratories/{id}/accreditation-decision as TestLaboratory",
            api_client.accreditation_decision(
                UNKNOWN_UUID, accreditation_payload("AUTHORIZE"), laboratory_headers
            ),
        )
        _refused(
            "POST /test-plans/{id}/issue as ConformanceReviewer",
            api_client.issue_test_plan(UNKNOWN_UUID, headers=CONFORMANCE_HEADERS),
        )
        _refused(
            "POST /submissions as ProgramAdmin",
            api_client.create_submission(
                submission_payload(member_id, UNKNOWN_UUID, []), ADMIN_HEADERS
            ),
        )
        _refused(
            "POST /submissions/{id}/start-review as SecurityReviewer",
            api_client.start_review(UNKNOWN_UUID, headers=SECURITY_HEADERS),
        )
        _refused(
            "POST /submissions/{id}/security-decision as ConformanceReviewer",
            api_client.security_decision(
                UNKNOWN_UUID, security_decision_payload("APPROVE"), CONFORMANCE_HEADERS
            ),
        )
        _refused(
            "POST /submissions/{id}/issue-credential as ComplianceOfficer",
            api_client.issue_credential(
                UNKNOWN_UUID, issue_credential_payload("DAC-999999"), COMPLIANCE_HEADERS
            ),
        )
        _refused(
            "POST /listings as ComplianceOfficer",
            api_client.create_listing(listing_payload(UNKNOWN_UUID), COMPLIANCE_HEADERS),
        )
        _refused(
            "POST /noncompliance-cases as ProgramAdmin",
            api_client.create_noncompliance_case(
                noncompliance_case_payload(
                    UNKNOWN_UUID, evidence_summary="administrative", claimed_impact_units=5
                ),
                ADMIN_HEADERS,
            ),
        )
        _refused(
            "POST /test-sessions/{id}/start as ProgramAdmin",
            api_client.start_test_session(UNKNOWN_UUID, headers=ADMIN_HEADERS),
        )
        _refused(
            "POST /test-sessions/{id}/results as ConformanceReviewer",
            api_client.append_results(
                UNKNOWN_UUID,
                results_payload([result_line(UNKNOWN_UUID, "PASS", "e1")]),
                CONFORMANCE_HEADERS,
            ),
        )
        _refused(
            "POST /plugfest-participations as ProgramAdmin",
            api_client.create_participation(
                participation_payload(UNKNOWN_UUID, member_id, UNKNOWN_UUID),
                ADMIN_HEADERS,
            ),
        )

        specifications = _total_count(
            api_client.list_specifications(ADMIN_HEADERS, limit=10, offset=0)
        )
        members = _total_count(api_client.list_members(ADMIN_HEADERS, limit=10, offset=0))
        assert specifications == 0, (
            "no refused call may store a specification, expected total_count 0, "
            "got {}".format(specifications)
        )
        assert members == 1, (
            "only the setup member exists, expected total_count 1, got {}".format(members)
        )

    def test_02_a_role_failure_answers_403_rather_than_leaking_path_existence(self):
        """A wrong-role request against an identifier that resolves to nothing
        answers ERR_UNAUTHORIZED, while the same absent identifier answers the
        404 not-found identifier once the acting role is authorized.

        PRD (§2.8): "Requests are therefore validated in one fixed, strictly
        ordered ladder, and the **first** rung whose condition is violated decides
        the response: no later rung is evaluated, and no later rung's error
        identifier can appear in its place."

        Design: Corner/rbac/every_roles_exclusive_operations_are_refused_to_the_other_six_roles
        """
        _identity_only_program()

        _refused(
            "POST /test-sessions/{absent}/start as ProgramAdmin",
            api_client.start_test_session(UNKNOWN_UUID, headers=ADMIN_HEADERS),
        )

        authorized = api_client.cancel_test_session(
            UNKNOWN_UUID, cancel_session_payload("bench fault"), ADMIN_HEADERS
        )
        assert authorized.status_code == 404, (
            "ProgramAdmin is on the cancel role list, so the absent session must "
            "reach path resolution and answer HTTP 404, got {}".format(
                authorized.status_code
            )
        )
        validate_error(authorized, ERR_TEST_SESSION_NOT_FOUND)

        _refused(
            "POST /listings/{absent}/withdraw as ProgramAdmin",
            api_client.withdraw_listing(
                UNKNOWN_UUID, listing_withdraw_payload("administrative"), ADMIN_HEADERS
            ),
        )
        officer = api_client.withdraw_listing(
            UNKNOWN_UUID, listing_withdraw_payload("administrative"), COMPLIANCE_HEADERS
        )
        assert officer.status_code == 404, (
            "the ComplianceOfficer clears the role rung, so the absent listing must "
            "answer HTTP 404, got {}".format(officer.status_code)
        )
        validate_error(officer, ERR_LISTING_NOT_FOUND)

    def test_03_ownership_of_the_addressed_row_never_widens_a_role_list(self):
        """The member named in the path is refused its own tool-access decision,
        because testing-tool entitlement is the programme operator's to move.

        PRD (§2.1): "`ProgramAdmin` is the programme operator: it alone creates and
        demotes specification versions, adds feature sets, registers members and
        laboratories, moves testing-tool entitlement, decides accreditation, runs
        competency reviews, creates and issues test plans, schedules and locks and
        closes plugfests, issues attestation credentials, creates and publishes
        listings, and repositions the logical clock."

        Design: Corner/rbac/every_roles_exclusive_operations_are_refused_to_the_other_six_roles
        """
        member_id, _ = _identity_only_program()

        _refused(
            "POST /members/{own_id}/tool-access as that Member",
            api_client.set_tool_access(
                member_id, tool_access_payload("GRANT"), make_member_headers(member_id)
            ),
        )

        member = read_member(member_id)
        assert_states(member, onboarding_state=MEMBER_REGISTERED, good_standing=False)

    def test_04_publication_belongs_to_the_operator_and_withdrawal_to_the_officer(self):
        """The programme operator creates and publishes listings and is still
        refused their withdrawal, which the compliance officer alone drives.

        PRD (§2.1): "`ComplianceOfficer` reads members, credit ledgers, laboratory
        competency, submissions, plugfests, listings and cases, and exclusively
        drives the noncompliance workflow and listing withdrawal."

        Design: Corner/rbac/every_roles_exclusive_operations_are_refused_to_the_other_six_roles
        """
        _identity_only_program()

        _refused(
            "POST /listings/{absent}/withdraw as ProgramAdmin",
            api_client.withdraw_listing(
                UNKNOWN_UUID, listing_withdraw_payload("administrative"), ADMIN_HEADERS
            ),
        )

        created = api_client.create_listing(listing_payload(UNKNOWN_UUID), ADMIN_HEADERS)
        assert created.status_code == 404, (
            "ProgramAdmin owns POST /listings, so the absent submission_id must be "
            "reported as a missing body reference with HTTP 404, got {}".format(
                created.status_code
            )
        )
        validate_error(created, ERR_SUBMISSION_NOT_FOUND)

        published = api_client.publish_listing(UNKNOWN_UUID, headers=ADMIN_HEADERS)
        assert published.status_code == 404, (
            "ProgramAdmin owns the publish endpoint, so the absent listing must "
            "answer HTTP 404, got {}".format(published.status_code)
        )
        validate_error(published, ERR_LISTING_NOT_FOUND)

    def test_05_the_clock_endpoint_is_still_restricted_to_the_programme_operator(self):
        """A Member repositioning the logical clock is refused with
        ERR_UNAUTHORIZED and HTTP 403 rather than an authentication failure, and
        the clock does not move.

        PRD (§2.8): "The acting `X-User-Role` appears in the endpoint's
        authorized-role list — otherwise `ERR_UNAUTHORIZED` (403). Applies to every
        endpoint."

        Design: Corner/rbac/every_roles_exclusive_operations_are_refused_to_the_other_six_roles
        """
        member_id, _ = _identity_only_program()

        _refused(
            "POST /_clock/set_current_utc as Member",
            api_client.set_clock(
                "2027-01-01T00:00:00Z", headers=make_member_headers(member_id)
            ),
        )

        stamped = new_member(legal_name="Clock Witness Devices")
        assert stamped["created_at"].startswith("2026-09-01T00:00:00"), (
            "the refused call must leave the logical clock at 2026-09-01T00:00:00Z, "
            "so the next row is stamped there, got {}".format(stamped["created_at"])
        )

    def test_06_the_consumer_surface_is_reachable_while_the_rest_is_refused(self):
        """PublicViewer is refused the submission collection and TestLaboratory the
        credit ledger and the case collection, while the two consumer-facing reads
        answer 200 for the very same PublicViewer identity.

        PRD (§2.1): "`PublicViewer` is the consumer-facing role and is read-only: it
        may read specifications, feature sets, laboratories, plugfests and listings,
        and nothing else — it can see neither member records, submissions, test
        plans, sessions, participations, credit ledgers nor noncompliance cases."

        Design: Corner/rbac/every_roles_exclusive_operations_are_refused_to_the_other_six_roles
        """
        member_id, laboratory_id = _identity_only_program()
        laboratory_headers = make_laboratory_headers(laboratory_id)

        _refused(
            "GET /submissions as PublicViewer",
            api_client.list_submissions(PUBLIC_HEADERS, limit=10, offset=0),
        )
        _refused(
            "GET /members/{id}/credit-ledger as TestLaboratory",
            api_client.get_credit_ledger(
                member_id, laboratory_headers, variant="AVAILABLE"
            ),
        )
        _refused(
            "GET /noncompliance-cases as TestLaboratory",
            api_client.list_noncompliance_cases(laboratory_headers, limit=10, offset=0),
        )

        listings = _total_count(
            api_client.list_listings(PUBLIC_HEADERS, limit=10, offset=0)
        )
        laboratories = _total_count(
            api_client.list_test_laboratories(PUBLIC_HEADERS, limit=10, offset=0)
        )
        assert listings == 0, (
            "the consumer directory is reachable and empty, expected total_count 0, "
            "got {}".format(listings)
        )
        assert laboratories == 1, (
            "PublicViewer reads the laboratory register, expected total_count 1, "
            "got {}".format(laboratories)
        )


def _two_laboratories_and_two_members():
    """Submission S1 of member M1, IN_REVIEW with an ISSUED plan and a SCHEDULED
    240-minute window at laboratory L1, alongside an equally authorized L2 and an
    equally funded M2."""
    ctx = build_program(
        stage="scheduled",
        features=ONE_LIGHTING_FEATURE,
        declared_codes=["CORE_ONOFF"],
    )
    second_laboratory = build_laboratory(name="Southgate Lab")
    ctx.laboratory2_id = second_laboratory.laboratory_id
    second_member = build_member(
        scope_specification_id=ctx.specification_id,
        legal_name="Borealis Home",
        contact_email="ops@borealis.test",
    )
    ctx.member2_id = second_member.member_id
    return ctx


class TestEntityBackedIdentitiesAreScopedToTheirOwnRow:
    """A Member or TestLaboratory principal holding the right role but the wrong
    row id is a stranger to the addressed resource."""

    def test_07_a_peer_laboratory_cannot_touch_another_laboratorys_session(self):
        """L2 is refused the start, the result append and the cancellation of a
        session booked at L1, even though L2 holds the same role and is equally
        AUTHORIZED.

        PRD (§2.1): "Session ownership compares the target `TestSession`'s
        `laboratory_id` to `X-User-ID`, and plugfest hosting compares the target
        `Plugfest`'s `host_laboratory_id` to `X-User-ID`."

        Design: Corner/rbac/entity_backed_identities_are_scoped_to_their_own_row
        """
        ctx = _two_laboratories_and_two_members()
        stranger = make_laboratory_headers(ctx.laboratory2_id)

        _refused(
            "POST /test-sessions/{id}/start as the stranger laboratory",
            api_client.start_test_session(ctx.session_id, headers=stranger),
        )
        _refused(
            "POST /test-sessions/{id}/results as the stranger laboratory",
            api_client.append_results(
                ctx.session_id,
                results_payload(
                    [result_line(ctx.feature_set_ids["CORE_ONOFF"], "PASS", "e1")]
                ),
                stranger,
            ),
        )
        _refused(
            "POST /test-sessions/{id}/cancel as the stranger laboratory",
            api_client.cancel_test_session(
                ctx.session_id, cancel_session_payload("not our bench"), stranger
            ),
        )

        session = read_session(ctx.session_id)
        assert_states(session, state=SESSION_SCHEDULED)
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 240)
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory2_id), 0)

    def test_08_a_peer_member_cannot_withdraw_another_members_submission(self):
        """M2, in good standing and funded exactly as M1 is, is refused the
        withdrawal of M1's submission, and the submission keeps its escrow.

        PRD (§2.1): "Ownership enforcement is not global — it applies to a fixed set
        of twelve write operations, and on any of them a mismatch also yields
        `ERR_UNAUTHORIZED` with HTTP 403."

        Design: Corner/rbac/entity_backed_identities_are_scoped_to_their_own_row
        """
        ctx = _two_laboratories_and_two_members()

        _refused(
            "POST /submissions/{id}/withdraw as the stranger member",
            api_client.withdraw_submission(
                ctx.submission_id, headers=make_member_headers(ctx.member2_id)
            ),
        )

        submission = read_submission(ctx.submission_id)
        assert_states(submission, state=SUB_IN_REVIEW)
        assert_cents(
            submission["fee_escrowed_cents"], LIGHTING_FEE_CENTS, "fee_escrowed_cents"
        )

    def test_09_ownership_is_checked_against_the_member_id_in_the_request_body(self):
        """M1 can neither open a submission under M2's member_id nor buy credit for
        M2, and M2's account and submission collection are untouched by either
        attempt.

        PRD (§3.4): "A `Member` opens one against its own record — the `member_id`
        in the payload must match the acting `X-User-ID` — naming the
        `specification_id` to certify against, a `device_model` designation of
        between 1 and 80 characters, and the `device_type` under certification."

        Design: Corner/rbac/entity_backed_identities_are_scoped_to_their_own_row
        """
        ctx = _two_laboratories_and_two_members()
        acting = make_member_headers(ctx.member_id)

        _refused(
            "POST /submissions naming another member_id",
            api_client.create_submission(
                submission_payload(
                    ctx.member2_id,
                    ctx.specification_id,
                    ["CORE_ONOFF"],
                    device_model="BH-1",
                ),
                acting,
            ),
        )
        _refused(
            "POST /members/{other_id}/credits as a stranger member",
            api_client.purchase_credits(
                ctx.member2_id, credit_purchase_payload(5000), acting
            ),
        )

        other = read_member(ctx.member2_id)
        assert_cents(
            other["credits_purchased_cents"], FUNDED_CENTS, "credits_purchased_cents"
        )
        under_other = _total_count(
            api_client.list_submissions(
                ADMIN_HEADERS, member_id=ctx.member2_id, limit=10, offset=0
            )
        )
        assert under_other == 0, (
            "no refused call may open a submission under the stranger member, "
            "expected total_count 0, got {}".format(under_other)
        )

    def test_10_the_owning_laboratory_starts_it_and_the_opaque_operator_cancels_it(self):
        """The identical start request from L1 is accepted, and the ProgramAdmin —
        whose identity is opaque and never ownership-scoped — cancels the session
        and restores L1's reserved minutes exactly.

        PRD (§3.6): "Cancellation is available to the `ProgramAdmin` or to the owning
        laboratory, from `SCHEDULED` or from `IN_PROGRESS`, with an identical body
        from either, and it accepts an optional `reason`."

        Design: Corner/rbac/entity_backed_identities_are_scoped_to_their_own_row
        """
        ctx = _two_laboratories_and_two_members()

        started = validate_success(
            api_client.start_test_session(
                ctx.session_id, headers=make_laboratory_headers(ctx.laboratory_id)
            )
        )
        assert_states(started, state=SESSION_IN_PROGRESS)

        cancelled = validate_success(
            api_client.cancel_test_session(
                ctx.session_id, cancel_session_payload("bench fault"), ADMIN_HEADERS
            )
        )
        assert_states(cancelled, state=SESSION_CANCELLED)
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory_id), 0)
        assert_reserved_bench_minutes(read_laboratory(ctx.laboratory2_id), 0)

    def test_11_the_owners_own_withdrawal_returns_the_escrowed_fee(self):
        """The withdrawal M2 was refused is accepted from M1, moving the submission
        to WITHDRAWN and returning the escrowed 135000 cents in full.

        PRD (§2.11): "Escrow is compensating: the cents a submission escrows at
        submit are returned to `credit_balance_cents` in full on rejection or
        withdrawal, or moved in full into `credits_consumed_cents` at credential
        issuance, and in every one of those three outcomes `fee_escrowed_cents`
        returns to 0."

        Design: Corner/rbac/entity_backed_identities_are_scoped_to_their_own_row
        """
        ctx = _two_laboratories_and_two_members()

        withdrawn = validate_success(
            api_client.withdraw_submission(
                ctx.submission_id, headers=make_member_headers(ctx.member_id)
            )
        )
        assert_states(withdrawn, state=SUB_WITHDRAWN)
        assert_cents(withdrawn["fee_escrowed_cents"], 0, "fee_escrowed_cents")

        ledger = read_ledger(ctx.member_id, variant="AVAILABLE")
        assert_cents(ledger["balance_cents"], FUNDED_CENTS, "AVAILABLE balance_cents")


def _returned_then_picked_up_again():
    """One submission carried through the full conformance cycle: picked up by
    CONF1, returned for information by CONF2, resubmitted by the member and picked
    up a second time by CONF1."""
    ctx = build_program(
        stage="submitted",
        features=ONE_LIGHTING_FEATURE,
        declared_codes=["CORE_ONOFF"],
    )
    start_review(ctx.submission_id, CONFORMANCE_REVIEWER_1)
    validate_success(
        api_client.return_for_info(
            ctx.submission_id,
            return_for_info_payload("Attach the interoperability log"),
            CONFORMANCE_HEADERS_2,
        )
    )
    ctx.returned = read_submission(ctx.submission_id)
    submit_submission(ctx.submission_id, ctx.member_id)
    start_review(ctx.submission_id, CONFORMANCE_REVIEWER_1)
    return ctx


class TestTheSecurityLockoutFollowsTheRecordedDecider:
    """Who is locked out of the security verdict is decided by the identifier the
    submission carries, not by who happens to be holding the review."""

    def test_12_a_return_for_info_records_the_returning_reviewer(self):
        """CONF1 opened the review but CONF2 returned the submission, so it is CONF2
        the submission records, alongside the returned states and the raised round.

        PRD (§3.8): "The return moves `IN_REVIEW → RETURNED_FOR_INFO` on the primary
        axis and `PENDING → RETURNED` on the conformance axis, increments
        `revision_round` by one, and records `conformance_reviewer_user_id` as the
        acting `X-User-ID`."

        Design: Corner/rbac/the_security_lockout_follows_the_recorded_conformance_decider_not_the_starter
        """
        ctx = _returned_then_picked_up_again()

        assert_states(
            ctx.returned,
            state=SUB_RETURNED_FOR_INFO,
            conformance_review_state=REVIEW_RETURNED,
            conformance_reviewer_user_id=CONFORMANCE_REVIEWER_2,
        )
        assert ctx.returned["revision_round"] == 1, (
            "one return raises revision_round to 1, got {}".format(
                ctx.returned["revision_round"]
            )
        )

    def test_13_a_second_pick_up_does_not_overwrite_the_recorded_identifier(self):
        """After the resubmission CONF1 picks the submission up again, which reopens
        the conformance axis without touching the recorded identifier — it is still
        CONF2.

        PRD (§2.10): "Note that `conformance_reviewer_user_id` is written both by a
        conformance decision and by a return-for-info, so an operator who merely
        returned a submission for more information has already disqualified
        themselves from its security decision."

        Design: Corner/rbac/the_security_lockout_follows_the_recorded_conformance_decider_not_the_starter
        """
        ctx = _returned_then_picked_up_again()

        submission = read_submission(ctx.submission_id)

        assert_states(
            submission,
            state=SUB_IN_REVIEW,
            conformance_review_state=REVIEW_PENDING,
            conformance_reviewer_user_id=CONFORMANCE_REVIEWER_2,
        )
        assert submission["security_reviewer_user_id"] is None, (
            "no security verdict has been recorded yet, so "
            "security_reviewer_user_id must be null, got {!r}".format(
                submission["security_reviewer_user_id"]
            )
        )

    def test_14_the_recorded_returner_is_locked_out_of_the_security_verdict(self):
        """CONF2, acting as a SecurityReviewer, is refused the security decision
        because the submission already records CONF2 as its conformance identifier,
        and the refused call writes nothing at all.

        PRD (§3.8): "The security verdict is recorded by a `SecurityReviewer`, and it
        is the segregation-of-duties gate of §2.10: the acting `X-User-ID` must differ
        from any `conformance_reviewer_user_id` already recorded on the submission, or
        the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_security_lockout_follows_the_recorded_conformance_decider_not_the_starter
        """
        ctx = _returned_then_picked_up_again()

        response = api_client.security_decision(
            ctx.submission_id,
            security_decision_payload("APPROVE"),
            make_security_headers(CONFORMANCE_REVIEWER_2),
        )
        assert response.status_code == 409, (
            "the disqualified reviewer must be refused with HTTP 409, got {}".format(
                response.status_code
            )
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)

        submission = read_submission(ctx.submission_id)
        assert_states(
            submission,
            state=SUB_IN_REVIEW,
            security_review_state=REVIEW_PENDING,
            security_reviewer_user_id=None,
        )
        assert_cents(
            submission["fee_escrowed_cents"], LIGHTING_FEE_CENTS, "fee_escrowed_cents"
        )

    def test_15_the_reviewer_who_only_started_the_review_is_still_eligible(self):
        """The identical request from CONF1 — who opened both rounds of the
        conformance review but was never recorded on the submission — is accepted and
        records CONF1 as the security reviewer.

        PRD (§3.8): "An accepted `APPROVE` sets `security_review_state` to `APPROVED`
        and records `security_reviewer_user_id`."

        Design: Corner/rbac/the_security_lockout_follows_the_recorded_conformance_decider_not_the_starter
        """
        ctx = _returned_then_picked_up_again()

        decided = validate_success(
            api_client.security_decision(
                ctx.submission_id,
                security_decision_payload("APPROVE"),
                make_security_headers(CONFORMANCE_REVIEWER_1),
            )
        )

        assert_states(
            decided,
            state=SUB_IN_REVIEW,
            security_review_state=REVIEW_APPROVED,
            security_reviewer_user_id=CONFORMANCE_REVIEWER_1,
            conformance_reviewer_user_id=CONFORMANCE_REVIEWER_2,
        )
        ledger = read_ledger(ctx.member_id, variant="AVAILABLE")
        assert_cents(
            ledger["balance_cents"],
            FUNDED_CENTS - LIGHTING_FEE_CENTS,
            "AVAILABLE balance_cents",
        )
