"""Role membership decides who may write; identity decides who may not.

Every write in this API belongs to exactly one role, with witnessing as the
single shared exception, while the three duty pairs are enforced against the
acting `X-User-ID` rather than against the role it presents.
"""

import pytest

from test_helpers import (
    ERR_ATTESTER_WAS_WITNESS,
    ERR_ISSUANCE_SOD_VIOLATION,
    ERR_UNAUTHORIZED,
    ERR_VETTING_SOD_VIOLATION,
    ALL_ROLES,
    CEREMONY_ATTESTED,
    CEREMONY_SCHEDULED,
    CEREMONY_WITNESSED,
    CHECK_NOT_STARTED,
    CHECK_PASSED,
    DIMENSION_CALLBACK,
    DIMENSION_REGISTRY,
    FIRST_SERIAL_NUMBER,
    PROFILE_STATE_DRAFT,
    REQUEST_ISSUED,
    REQUEST_READY_TO_ISSUE,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_ISSUANCE_OPERATOR,
    ROLE_POLICY_ADMIN,
    ROLE_REVOCATION_OFFICER,
    ROLE_VALIDATION_OFFICER,
    ROLE_VETTING_APPROVER,
    SUBSCRIBER_ACTIVE,
    VALIDATION_TYPE_DV,
    VETTING_APPROVED,
    VETTING_AWAITING_APPROVAL,
    VETTING_LEVEL_OV,
    VETTING_PENDING,
    advance_clock,
    assert_counters,
    assert_instant_equals,
    assert_nulls,
    audit_payload,
    build_environment,
    ceremony_payload,
    check_payload,
    cleared_request,
    create_partition,
    create_profile,
    create_subscriber,
    crl_publication_payload,
    get_success_data,
    incident_payload,
    issuance_charge_cents,
    issue_payload,
    profile_payload,
    read_authorization,
    read_ceremony,
    read_partition,
    read_profile,
    read_request,
    read_subscriber,
    schedule_ceremony,
    subscriber_amendment_payload,
    subscriber_payload,
    users,
    validate_error,
    validate_paginated,
    validate_success,
    vetting_payload,
    witness_twice,
)

CLOCK_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-01T00:30:00Z"


def _other_roles(*owners):
    """Every declared role except the ones that own the capability."""
    return [role for role in ALL_ROLES if role not in owners]


def _read_vetting(client, vetting_id):
    return get_success_data(client.get_vetting(vetting_id, users.VETTING_APPROVER))


def _draft_policy_estate(client):
    """A DRAFT profile, a subscriber, one open vetting file and a partition."""
    profile = create_profile(client, profile_payload(), activate=False)
    subscriber = create_subscriber(
        client, subscriber_payload(credit_limit_cents=500000)
    )
    vetting = get_success_data(
        client.open_vetting(
            subscriber["id"],
            vetting_payload(VETTING_LEVEL_OV),
            users.VALIDATION_OFFICER,
        ),
        201,
    )
    partition = create_partition(client)
    return profile, subscriber, vetting, partition


def _awaiting_approval_vetting(client):
    """An OV file whose two required checks were recorded by two officers."""
    subscriber = create_subscriber(client)
    vetting = get_success_data(
        client.open_vetting(
            subscriber["id"],
            vetting_payload(VETTING_LEVEL_OV),
            users.VALIDATION_OFFICER,
        ),
        201,
    )
    validate_success(
        client.record_check(
            vetting["id"],
            check_payload(DIMENSION_REGISTRY, CHECK_PASSED, "registry-extract"),
            users.VALIDATION_OFFICER,
        )
    )
    recorded = validate_success(
        client.record_check(
            vetting["id"],
            check_payload(DIMENSION_CALLBACK, CHECK_PASSED, "callback-log"),
            users.VALIDATION_OFFICER_2,
        )
    )
    assert recorded["vetting_state"] == VETTING_AWAITING_APPROVAL, (
        "two passed OV dimensions leave the file awaiting approval, found "
        f"{recorded['vetting_state']!r}"
    )
    assert_counters(
        recorded,
        registry_checked_by_user_id=users.USER_VALIDATION_OFFICER,
        callback_checked_by_user_id=users.USER_VALIDATION_OFFICER_2,
    )
    return vetting["id"]


def _witnessed_ceremony_at_window_end(client):
    """A ceremony witnessed by u_iss_1 and u_aud_1, its window already closed."""
    partition = create_partition(client)
    ceremony = schedule_ceremony(client, partition["id"], CLOCK_START, WINDOW_END, 60)
    witnessed = witness_twice(
        client,
        ceremony["id"],
        first=users.ISSUANCE_OPERATOR,
        second=users.COMPLIANCE_AUDITOR,
    )
    assert witnessed["witness_user_ids"] == [
        users.USER_ISSUANCE_OPERATOR,
        users.USER_COMPLIANCE_AUDITOR,
    ], f"witness_user_ids is {witnessed['witness_user_ids']!r}"
    advance_clock(client, WINDOW_END)
    return partition["id"], ceremony["id"]


class TestExclusiveWrites:
    def test_a_the_policy_writes_are_denied_to_the_other_five_roles(self, client):
        """Creating a profile and amending a subscriber belong to one role only.

        PRD 2.1: "`POLICY_ADMIN` owns the CA's policy objects — certificate
        profiles, subscriber accounts, and the hardware-security-module partition
        inventory — and never touches an individual issuance, revocation or
        audit."
        PRD 2.1: "A role string that is not one of the six names above is
        rejected with `ERR_UNKNOWN_ROLE` (HTTP 401), and a syntactically valid
        role that is simply not permitted on the endpoint being called is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/every_roles_exclusive_write_is_denied_to_the_other_five_roles
        """
        profile, subscriber, _vetting, _partition = _draft_policy_estate(client)

        for role in _other_roles(ROLE_POLICY_ADMIN):
            headers = users.headers_for(role)
            validate_error(
                client.create_profile(profile_payload(), headers),
                ERR_UNAUTHORIZED,
                403,
            )
            validate_error(
                client.amend_subscriber(
                    subscriber["id"],
                    subscriber_amendment_payload(credit_limit_cents=900000),
                    headers,
                ),
                ERR_UNAUTHORIZED,
                403,
            )

        rows, meta = validate_paginated(client.list_profiles(users.POLICY_ADMIN))
        assert meta["total_count"] == 1, (
            f"five refused creations must add no profile, found {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [profile["id"]]
        untouched = read_profile(client, profile["id"])
        assert_counters(
            untouched, version=profile["version"], status=PROFILE_STATE_DRAFT
        )
        settled = read_subscriber(client, subscriber["id"])
        assert_counters(
            settled,
            credit_limit_cents=500000,
            version=1,
            account_status=SUBSCRIBER_ACTIVE,
        )

    def test_b_the_vetting_writes_are_denied_to_the_other_five_roles(self, client):
        """Opening a vetting file and approving it are two different monopolies.

        PRD 2.1: "`VALIDATION_OFFICER` performs domain control validation and the
        three organizational vetting checks, and drives a certificate request
        from creation through validation clearance; it may never approve the
        vetting file it checked nor issue the certificate it cleared."
        PRD 2.1: "`VETTING_APPROVER` is the sole approver of organizational
        vetting files and holds no other write capability, which is precisely
        what makes the vetting segregation-of-duties rule enforceable by user
        identity rather than by role."
        PRD 2.1: "A role string that is not one of the six names above is
        rejected with `ERR_UNKNOWN_ROLE` (HTTP 401), and a syntactically valid
        role that is simply not permitted on the endpoint being called is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/every_roles_exclusive_write_is_denied_to_the_other_five_roles
        """
        _profile, subscriber, vetting, _partition = _draft_policy_estate(client)

        for role in _other_roles(ROLE_VALIDATION_OFFICER):
            validate_error(
                client.open_vetting(
                    subscriber["id"],
                    vetting_payload(VETTING_LEVEL_OV),
                    users.headers_for(role),
                ),
                ERR_UNAUTHORIZED,
                403,
            )
        for role in _other_roles(ROLE_VETTING_APPROVER):
            validate_error(
                client.approve_vetting(vetting["id"], users.headers_for(role)),
                ERR_UNAUTHORIZED,
                403,
            )

        rows, meta = validate_paginated(
            client.list_vettings(subscriber["id"], users.VALIDATION_OFFICER)
        )
        assert meta["total_count"] == 1, (
            f"the subscriber still holds one file, found {meta['total_count']}"
        )
        assert rows[0]["id"] == vetting["id"]
        settled = _read_vetting(client, vetting["id"])
        assert settled["vetting_state"] == VETTING_PENDING, (
            f"a refused approval leaves the file pending, found "
            f"{settled['vetting_state']!r}"
        )
        assert_counters(settled, version=vetting["version"])
        assert_nulls(settled, "approved_at", "approved_by_user_id", "rejected_at")

    def test_c_the_signing_and_status_writes_are_denied_to_the_other_five_roles(
        self, client
    ):
        """Scheduling a ceremony and publishing a list are separate monopolies.

        PRD 2.1: "`ISSUANCE_OPERATOR` runs the issuance systems: it schedules and
        aborts key ceremony windows, issues certificates under an attested
        ceremony, submits pre-certificates to transparency logs, and activates
        certificates."
        PRD 2.1: "`REVOCATION_OFFICER` owns revocation and the status services:
        it raises, executes and denies revocation requests, publishes revocation
        lists, and runs mass-revocation batches for disclosed incidents."
        PRD 2.1: "A role string that is not one of the six names above is
        rejected with `ERR_UNKNOWN_ROLE` (HTTP 401), and a syntactically valid
        role that is simply not permitted on the endpoint being called is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/every_roles_exclusive_write_is_denied_to_the_other_five_roles
        """
        profile, _subscriber, _vetting, partition = _draft_policy_estate(client)

        for role in _other_roles(ROLE_ISSUANCE_OPERATOR):
            validate_error(
                client.schedule_ceremony(
                    partition["id"],
                    ceremony_payload(CLOCK_START, WINDOW_END, 60),
                    users.headers_for(role),
                ),
                ERR_UNAUTHORIZED,
                403,
            )
        for role in _other_roles(ROLE_REVOCATION_OFFICER):
            validate_error(
                client.publish_crl(
                    profile["id"],
                    crl_publication_payload(
                        CLOCK_START, "2026-08-01T12:00:00Z", profile["version"]
                    ),
                    users.headers_for(role),
                ),
                ERR_UNAUTHORIZED,
                403,
            )

        _, ceremony_meta = validate_paginated(
            client.list_ceremonies(partition["id"], users.ISSUANCE_OPERATOR)
        )
        assert ceremony_meta["total_count"] == 0, (
            f"no ceremony may exist, found {ceremony_meta['total_count']}"
        )
        _, crl_meta = validate_paginated(
            client.list_crl_publications(profile["id"], users.REVOCATION_OFFICER)
        )
        assert crl_meta["total_count"] == 0, (
            f"no publication may exist, found {crl_meta['total_count']}"
        )
        assert_counters(
            read_partition(client, partition["id"]),
            version=partition["version"],
            attested_ceremony_count=0,
        )
        assert_counters(read_profile(client, profile["id"]), version=profile["version"])

    def test_d_the_compliance_writes_are_denied_to_the_other_five_roles(self, client):
        """Incidents and the annual audit answer to the auditor alone.

        PRD 2.1: "`COMPLIANCE_AUDITOR` attests key ceremonies and repudiates
        attestations, manages misissuance incidents and root program
        correspondence, and runs the annual root program audit; it may not attest
        a ceremony it witnessed."
        PRD 2.1: "A role string that is not one of the six names above is
        rejected with `ERR_UNKNOWN_ROLE` (HTTP 401), and a syntactically valid
        role that is simply not permitted on the endpoint being called is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/every_roles_exclusive_write_is_denied_to_the_other_five_roles
        """
        profile, _subscriber, _vetting, _partition = _draft_policy_estate(client)

        for role in _other_roles(ROLE_COMPLIANCE_AUDITOR):
            headers = users.headers_for(role)
            validate_error(
                client.create_incident(incident_payload(profile["id"]), headers),
                ERR_UNAUTHORIZED,
                403,
            )
            validate_error(
                client.create_audit(audit_payload(), headers),
                ERR_UNAUTHORIZED,
                403,
            )

        _, incident_meta = validate_paginated(
            client.list_incidents(users.COMPLIANCE_AUDITOR)
        )
        assert incident_meta["total_count"] == 0, (
            f"no incident may exist, found {incident_meta['total_count']}"
        )
        _, audit_meta = validate_paginated(client.list_audits(users.COMPLIANCE_AUDITOR))
        assert audit_meta["total_count"] == 0, (
            f"no audit may exist, found {audit_meta['total_count']}"
        )


class TestWitnessingIsTheSharedWrite:
    def test_a_the_four_roles_that_do_not_witness_are_refused(self, client):
        """Only two roles may sign the register; the other four are turned away.

        PRD 2.1: "Witnessing a key ceremony is the one write capability shared
        between two roles: both `ISSUANCE_OPERATOR` and `COMPLIANCE_AUDITOR` may
        record themselves as a witness."
        PRD 2.1: "A role string that is not one of the six names above is
        rejected with `ERR_UNKNOWN_ROLE` (HTTP 401), and a syntactically valid
        role that is simply not permitted on the endpoint being called is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/witnessing_is_the_only_write_shared_between_two_roles
        """
        partition = create_partition(client)
        ceremony = schedule_ceremony(
            client, partition["id"], CLOCK_START, WINDOW_END, 60
        )

        for role in _other_roles(ROLE_ISSUANCE_OPERATOR, ROLE_COMPLIANCE_AUDITOR):
            validate_error(
                client.witness_ceremony(ceremony["id"], users.headers_for(role)),
                ERR_UNAUTHORIZED,
                403,
            )

        settled = read_ceremony(client, ceremony["id"])
        assert settled["state"] == CEREMONY_SCHEDULED, (
            f"a refused witnessing leaves the ceremony scheduled, found "
            f"{settled['state']!r}"
        )
        assert_counters(settled, witness_count=0, version=ceremony["version"])
        assert settled["witness_user_ids"] == [], (
            f"witness_user_ids is {settled['witness_user_ids']!r}, expected empty"
        )

    def test_b_an_operator_and_an_auditor_together_form_the_quorum(self, client):
        """The two permitted roles join one quorum, in the order they signed.

        PRD 3.6: "Witnessing is a two-person join, and it is the one act both
        `ISSUANCE_OPERATOR` and `COMPLIANCE_AUDITOR` may perform."
        PRD 3.6: "The first witness appends its `X-User-ID` to
        `witness_user_ids`, sets `witness_count` to 1, and deliberately leaves the
        ceremony in `SCHEDULED` — one signature is not a quorum."
        PRD 3.6: "The second, distinct witness appends its `X-User-ID`, sets
        `witness_count` to 2, and moves the ceremony `SCHEDULED → WITNESSED`."

        Design: Corner/rbac/witnessing_is_the_only_write_shared_between_two_roles
        """
        partition = create_partition(client)
        ceremony = schedule_ceremony(
            client, partition["id"], CLOCK_START, WINDOW_END, 60
        )

        first = validate_success(
            client.witness_ceremony(ceremony["id"], users.ISSUANCE_OPERATOR)
        )
        assert first["state"] == CEREMONY_SCHEDULED, (
            f"one signature is not a quorum, found {first['state']!r}"
        )
        assert_counters(first, witness_count=1)
        assert first["witness_user_ids"] == [users.USER_ISSUANCE_OPERATOR]

        second = validate_success(
            client.witness_ceremony(ceremony["id"], users.COMPLIANCE_AUDITOR_2)
        )
        assert second["state"] == CEREMONY_WITNESSED, (
            f"the second distinct witness closes the quorum, found "
            f"{second['state']!r}"
        )
        assert_counters(second, witness_count=2)
        assert second["witness_user_ids"] == [
            users.USER_ISSUANCE_OPERATOR,
            users.USER_COMPLIANCE_AUDITOR_2,
        ], (
            "witness_user_ids records the operator then the auditor, found "
            f"{second['witness_user_ids']!r}"
        )
        assert_nulls(second, "attested_at", "attested_by_user_id")


class TestTheClockAndEveryReadAreShared:
    def test_a_all_six_roles_may_advance_the_logical_clock(self, client):
        """Five successive advances, one per non-admin role, all take effect.

        PRD 2.6: "Advancing the clock is available to all six roles."
        PRD 2.6: "Every timestamp the server writes, and every deadline
        comparison it makes, reads that clock."

        Design: Corner/rbac/the_clock_and_every_read_are_shared_by_all_six_roles
        """
        create_profile(client, profile_payload(), activate=False)
        create_subscriber(client)

        schedule = [
            ("2026-08-01T01:00:00Z", users.VALIDATION_OFFICER),
            ("2026-08-01T02:00:00Z", users.VETTING_APPROVER),
            ("2026-08-01T03:00:00Z", users.ISSUANCE_OPERATOR),
            ("2026-08-01T04:00:00Z", users.REVOCATION_OFFICER),
            ("2026-08-01T05:00:00Z", users.COMPLIANCE_AUDITOR),
        ]
        for instant, headers in schedule:
            advance_clock(client, instant, headers)

        probe = create_subscriber(client)
        assert_instant_equals(
            probe["created_at"], "2026-08-01T05:00:00Z", "created_at"
        )

    @pytest.mark.parametrize("role", ALL_ROLES)
    def test_b_every_read_endpoint_answers_any_role(self, client, role):
        """A read is never refused for the capacity the caller is acting in.

        PRD 2.1: "Advancing the logical clock and every read (`GET`) endpoint are
        available to all six roles, so that a client may read back any state
        regardless of the capacity it is acting in."
        PRD 2.1: "There is no ownership filtering in this API: a
        `VALIDATION_OFFICER` may act on any subscriber's request, and role
        membership alone determines authorization."

        Design: Corner/rbac/the_clock_and_every_read_are_shared_by_all_six_roles
        """
        profile = create_profile(client, profile_payload(), activate=False)
        subscriber = create_subscriber(client)
        headers = users.headers_for(role)

        seen_subscriber = get_success_data(
            client.get_subscriber(subscriber["id"], headers)
        )
        assert_counters(seen_subscriber, account_status=SUBSCRIBER_ACTIVE)
        assert seen_subscriber["id"] == subscriber["id"]

        seen_profile = get_success_data(client.get_profile(profile["id"], headers))
        assert seen_profile["status"] == PROFILE_STATE_DRAFT, (
            f"status is {seen_profile['status']!r}, expected {PROFILE_STATE_DRAFT!r}"
        )

        _, meta = validate_paginated(client.list_revocations(headers))
        assert meta["total_count"] == 0, (
            "an empty revocation list is a 200 with no rows for every role, found "
            f"{meta['total_count']}"
        )


class TestTheApproverMayNotBeAChecker:
    def test_a_both_officers_who_recorded_a_check_are_refused(self, client):
        """Either recorder, presenting the approver role, is turned away.

        PRD 2.7: "This CA operates under mandatory segregation of duties,
        enforced by `X-User-ID` rather than by role, so that a single person
        holding two roles cannot self-approve."
        PRD 2.7: "At approval time the acting `X-User-ID` is compared against
        every non-null value among `registry_checked_by_user_id`,
        `callback_checked_by_user_id` and `authority_checked_by_user_id`; a match
        on any one of them is rejected with `ERR_VETTING_SOD_VIOLATION` (HTTP
        409)."

        Design: Corner/rbac/the_vetting_approver_may_not_be_any_of_the_users_who_recorded_the_checks
        """
        vetting_id = _awaiting_approval_vetting(client)

        for recorder in (
            users.USER_VALIDATION_OFFICER,
            users.USER_VALIDATION_OFFICER_2,
        ):
            refused = client.approve_vetting(
                vetting_id, users.headers_for(ROLE_VETTING_APPROVER, recorder)
            )
            validate_error(refused, ERR_VETTING_SOD_VIOLATION, 409)

        settled = _read_vetting(client, vetting_id)
        assert settled["vetting_state"] == VETTING_AWAITING_APPROVAL, (
            f"two refused approvals leave the file awaiting approval, found "
            f"{settled['vetting_state']!r}"
        )
        assert_nulls(settled, "approved_at", "approved_by_user_id", "rejected_at")

    def test_b_only_a_third_identity_may_approve_the_file(self, client):
        """The approval succeeds as soon as the acting identity is a new one.

        PRD 2.7: "At approval time the acting `X-User-ID` is compared against
        every non-null value among `registry_checked_by_user_id`,
        `callback_checked_by_user_id` and `authority_checked_by_user_id`; a match
        on any one of them is rejected with `ERR_VETTING_SOD_VIOLATION` (HTTP
        409)."
        PRD 3.3: "Approval moves the file `AWAITING_APPROVAL → APPROVED`, stamps
        `approved_at` with the logical clock and `approved_by_user_id` with the
        approver's `X-User-ID`, and increments `version`."
        PRD 3.3: "A `PASSED` result that leaves every dimension required by
        `required_level` at `PASSED` moves the file `IN_PROGRESS →
        AWAITING_APPROVAL`; for an `OV` file this fires as soon as the registry
        and callback dimensions are both `PASSED`, even while
        `authority_check_status` is still `NOT_STARTED`."

        Design: Corner/rbac/the_vetting_approver_may_not_be_any_of_the_users_who_recorded_the_checks
        """
        vetting_id = _awaiting_approval_vetting(client)

        validate_error(
            client.approve_vetting(
                vetting_id,
                users.headers_for(
                    ROLE_VETTING_APPROVER, users.USER_VALIDATION_OFFICER
                ),
            ),
            ERR_VETTING_SOD_VIOLATION,
            409,
        )

        approved = validate_success(
            client.approve_vetting(vetting_id, users.VETTING_APPROVER)
        )
        assert approved["vetting_state"] == VETTING_APPROVED, (
            f"vetting_state is {approved['vetting_state']!r}, expected "
            f"{VETTING_APPROVED!r}"
        )
        assert_counters(
            approved,
            approved_by_user_id=users.USER_VETTING_APPROVER,
            authority_check_status=CHECK_NOT_STARTED,
        )
        assert_instant_equals(approved["approved_at"], CLOCK_START, "approved_at")


class TestTheAttesterMayNotBeAWitness:
    def test_a_the_auditor_who_witnessed_cannot_attest(self, client):
        """The same auditor identity may witness, and then loses the sign-off.

        PRD 2.7: "Third, an operator who witnessed a key ceremony may not attest
        it: if the acting `X-User-ID` appears anywhere in that ceremony's
        `witness_user_ids`, attestation is refused with
        `ERR_ATTESTER_WAS_WITNESS` (HTTP 409)."
        PRD 3.6: "A `COMPLIANCE_AUDITOR` attests a ceremony that is `WITNESSED`
        (`ERR_CEREMONY_NOT_WITNESSED` otherwise), whose window has closed — the
        logical clock must be at or after `window_end`, and attesting while the
        window is still open is refused with `ERR_CEREMONY_WINDOW_OPEN` — and
        whose `witness_user_ids` does not contain the attester's own
        `X-User-ID`, since an auditor may not attest a ceremony it witnessed."

        Design: Corner/rbac/an_auditor_who_witnessed_the_ceremony_may_not_attest_it
        """
        partition_id, ceremony_id = _witnessed_ceremony_at_window_end(client)

        refused = client.attest_ceremony(ceremony_id, users.COMPLIANCE_AUDITOR)
        validate_error(refused, ERR_ATTESTER_WAS_WITNESS, 409)

        settled = read_ceremony(client, ceremony_id)
        assert settled["state"] == CEREMONY_WITNESSED, (
            f"a refused attestation leaves the ceremony witnessed, found "
            f"{settled['state']!r}"
        )
        assert_nulls(
            settled, "attested_at", "attested_by_user_id", "attestation_expires_at"
        )
        assert_counters(read_partition(client, partition_id), attested_ceremony_count=0)

    def test_b_a_second_auditor_who_did_not_witness_attests(self, client):
        """A different auditor identity signs off and the expiry is stamped.

        PRD 2.7: "Third, an operator who witnessed a key ceremony may not attest
        it: if the acting `X-User-ID` appears anywhere in that ceremony's
        `witness_user_ids`, attestation is refused with
        `ERR_ATTESTER_WAS_WITNESS` (HTTP 409)."
        PRD 3.6: "Attestation moves the ceremony `WITNESSED → ATTESTED`, stamps
        `attested_at` with the logical clock and `attested_by_user_id` with the
        attester's `X-User-ID`, and sets `attestation_expires_at` to
        `attested_at` plus `attestation_valid_days` in days."
        PRD 3.6: "The partition's `attested_ceremony_count` and `version` both
        increment, as does the ceremony's `version`."

        Design: Corner/rbac/an_auditor_who_witnessed_the_ceremony_may_not_attest_it
        """
        partition_id, ceremony_id = _witnessed_ceremony_at_window_end(client)

        validate_error(
            client.attest_ceremony(ceremony_id, users.COMPLIANCE_AUDITOR),
            ERR_ATTESTER_WAS_WITNESS,
            409,
        )

        attested = validate_success(
            client.attest_ceremony(ceremony_id, users.COMPLIANCE_AUDITOR_2)
        )
        assert attested["state"] == CEREMONY_ATTESTED, (
            f"state is {attested['state']!r}, expected {CEREMONY_ATTESTED!r}"
        )
        assert_counters(
            attested, attested_by_user_id=users.USER_COMPLIANCE_AUDITOR_2
        )
        assert_instant_equals(attested["attested_at"], WINDOW_END, "attested_at")
        assert_instant_equals(
            attested["attestation_expires_at"],
            "2026-09-30T00:30:00Z",
            "attestation_expires_at",
        )
        assert_counters(read_partition(client, partition_id), attested_ceremony_count=1)


class TestTheIssuerMayNotHaveClearedValidation:
    def test_a_the_clearing_officer_is_refused_and_nothing_is_minted(self, client):
        """The refusal leaves the request ready and the ledger untouched.

        PRD 2.7: "Second, the operator who cleared validation on a certificate
        request may not issue the resulting certificate: if the acting
        `X-User-ID` equals the request's `validation_cleared_by_user_id`,
        issuance is refused with `ERR_ISSUANCE_SOD_VIOLATION` (HTTP 409)."
        PRD 3.7: "The acting `X-User-ID` must differ from the request's
        `validation_cleared_by_user_id`, or `ERR_ISSUANCE_SOD_VIOLATION`."
        PRD 3.5: "`consumed_authorization_ids` receives the selected
        authorization identifiers in `requested_domains` order, one per domain,
        and every selected authorization has its `reuse_count` incremented by
        one."

        Design: Corner/rbac/the_officer_who_cleared_validation_may_not_issue_the_certificate
        """
        environment = build_environment(
            client,
            profile_payload=profile_payload(
                max_dcv_reuse_count=5, base_fee_cents=20000
            ),
            subscriber_payload=subscriber_payload(credit_limit_cents=500000),
        )
        request = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ("d1.example.org",),
        )
        assert_counters(
            request, validation_cleared_by_user_id=users.USER_VALIDATION_OFFICER
        )

        refused = client.issue_certificate(
            request["id"],
            issue_payload(environment.ceremony_id),
            users.headers_for(ROLE_ISSUANCE_OPERATOR, users.USER_VALIDATION_OFFICER),
        )
        validate_error(refused, ERR_ISSUANCE_SOD_VIOLATION, 409)

        settled = read_request(client, request["id"])
        assert settled["state"] == REQUEST_READY_TO_ISSUE, (
            f"a refused issuance leaves the request ready, found "
            f"{settled['state']!r}"
        )
        assert_nulls(settled, "issued_certificate_id")
        authorization = read_authorization(
            client, environment.authorization("d1.example.org")["id"]
        )
        assert_counters(authorization, reuse_count=1)
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            outstanding_balance_cents=0,
            issued_certificate_count=0,
        )
        assert_counters(
            read_ceremony(client, environment.ceremony_id), issued_certificate_count=0
        )

    def test_b_a_different_operator_identity_issues_the_same_request(self, client):
        """The role is identical; only the identity changes the outcome.

        PRD 2.7: "Second, the operator who cleared validation on a certificate
        request may not issue the resulting certificate: if the acting
        `X-User-ID` equals the request's `validation_cleared_by_user_id`,
        issuance is refused with `ERR_ISSUANCE_SOD_VIOLATION` (HTTP 409)."
        PRD 3.7: "The originating request moves `READY_TO_ISSUE → ISSUED`, its
        `issued_certificate_id` is set to the new certificate, and its `version`
        increments."
        PRD 3.7: "Issuance then debits the subscriber:
        `outstanding_balance_cents` rises by `charged_amount_cents` and
        `issued_certificate_count` rises by one, with the subscriber's `version`
        incrementing."

        Design: Corner/rbac/the_officer_who_cleared_validation_may_not_issue_the_certificate
        """
        environment = build_environment(
            client,
            profile_payload=profile_payload(
                max_dcv_reuse_count=5, base_fee_cents=20000
            ),
            subscriber_payload=subscriber_payload(credit_limit_cents=500000),
        )
        request = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ("d1.example.org",),
        )

        validate_error(
            client.issue_certificate(
                request["id"],
                issue_payload(environment.ceremony_id),
                users.headers_for(
                    ROLE_ISSUANCE_OPERATOR, users.USER_VALIDATION_OFFICER
                ),
            ),
            ERR_ISSUANCE_SOD_VIOLATION,
            409,
        )

        expected_charge = issuance_charge_cents(20000, VALIDATION_TYPE_DV, 1)
        certificate = get_success_data(
            client.issue_certificate(
                request["id"],
                issue_payload(environment.ceremony_id),
                users.ISSUANCE_OPERATOR_3,
            ),
            201,
        )
        assert certificate["serial_number"] == FIRST_SERIAL_NUMBER, (
            f"serial_number is {certificate['serial_number']!r}, expected "
            f"{FIRST_SERIAL_NUMBER!r}"
        )
        assert_counters(certificate, charged_amount_cents=expected_charge)

        issued = read_request(client, request["id"])
        assert issued["state"] == REQUEST_ISSUED, (
            f"state is {issued['state']!r}, expected {REQUEST_ISSUED!r}"
        )
        assert issued["issued_certificate_id"] == certificate["id"], (
            "issued_certificate_id must name the new certificate, found "
            f"{issued['issued_certificate_id']!r}"
        )
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            outstanding_balance_cents=expected_charge,
            issued_certificate_count=1,
        )
        assert_counters(
            read_ceremony(client, environment.ceremony_id), issued_certificate_count=1
        )
