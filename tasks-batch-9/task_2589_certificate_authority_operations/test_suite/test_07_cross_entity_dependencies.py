"""Operations blocked by the state of an entity they never name directly.

Issuance names a ceremony but is gated on that ceremony's partition, and a
domain validation names an authorization but is gated on the account posture of
the subscriber behind it - a posture that is itself only a derived count.
"""

from test_helpers import (
    AUTH_PENDING,
    AUTH_VALIDATED,
    CEREMONY_ATTESTATION_REVOKED,
    CEREMONY_ATTESTED,
    ERR_PARTITION_QUARANTINED,
    ERR_SUBSCRIBER_NOT_ACTIVE,
    LIFECYCLE_PREISSUANCE,
    PARTITION_OPERATIONAL,
    PARTITION_QUARANTINED,
    POSTURE_NOMINAL,
    REASON_PRIVILEGE_WITHDRAWN,
    REQUEST_READY_TO_ISSUE,
    REVOCATION_DENIED,
    REVOCATION_EXECUTED,
    REVOCATION_STATUS_NONE,
    REVOCATION_STATUS_PENDING,
    REVOCATION_STATUS_REVOKED,
    SUBSCRIBER_ACTIVE,
    SUBSCRIBER_SUSPENDED,
    advance_clock,
    assert_certificate_dimensions,
    assert_counters,
    assert_instant_equals,
    assert_nulls,
    attestation_revocation_payload,
    authorization_payload,
    build_environment,
    ceremony_payload,
    cleared_request,
    create_authorization,
    create_partition,
    create_profile,
    create_subscriber,
    denial_payload,
    get_success_data,
    ids_of,
    issue_certificate,
    issue_payload,
    raise_revocation,
    read_authorization,
    read_certificate,
    read_ceremony,
    read_partition,
    read_profile,
    read_request,
    read_subscriber,
    schedule_ceremony,
    users,
    validate_error,
    validate_paginated,
    validate_payload,
    witness_twice,
)


def _partition_with_two_attested_ceremonies(client):
    """One partition, two non-overlapping ceremonies, both attested at 02:30."""
    partition = create_partition(client)
    first = schedule_ceremony(
        client,
        partition["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T00:30:00Z",
        attestation_valid_days=60,
    )
    second = schedule_ceremony(
        client,
        partition["id"],
        window_start="2026-08-01T02:00:00Z",
        window_end="2026-08-01T02:30:00Z",
        attestation_valid_days=60,
    )
    witness_twice(client, first["id"])
    witness_twice(
        client, second["id"], first=users.ISSUANCE_OPERATOR, second=users.ISSUANCE_OPERATOR_3
    )
    advance_clock(client, "2026-08-01T02:30:00Z")
    first = get_success_data(
        client.attest_ceremony(first["id"], users.COMPLIANCE_AUDITOR)
    )
    second = get_success_data(
        client.attest_ceremony(second["id"], users.COMPLIANCE_AUDITOR)
    )
    partition = read_partition(client, partition["id"])
    assert_counters(
        partition, state=PARTITION_OPERATIONAL, attested_ceremony_count=2
    )
    return partition, first, second


def _ready_request(client):
    """An activated DV profile, a subscriber and one request in READY_TO_ISSUE."""
    profile = create_profile(client)
    subscriber = create_subscriber(client)
    authorization = create_authorization(
        client, subscriber["id"], profile["id"], "d1.example.org"
    )
    get_success_data(
        client.validate_authorization(
            authorization["id"],
            validate_payload(authorization["challenge_token"]),
            users.VALIDATION_OFFICER,
        )
    )
    request = cleared_request(
        client, subscriber["id"], profile["id"], ("d1.example.org",)
    )
    assert request["state"] == REQUEST_READY_TO_ISSUE, (
        f"the request must be ready to issue, found {request['state']!r}"
    )
    return profile, subscriber, request


def _repudiate(client, ceremony_id, reason):
    return get_success_data(
        client.revoke_attestation(
            ceremony_id,
            attestation_revocation_payload(reason),
            users.COMPLIANCE_AUDITOR_2,
        )
    )


class TestIssuanceGatedOnThePartitionBehindTheCeremony:
    def test_a_a_sibling_repudiation_blocks_a_perfectly_attested_ceremony(self, client):
        """The named ceremony is flawless; its partition is not.

        PRD 3.7: "The named ceremony's partition must be `OPERATIONAL`, or
        `ERR_PARTITION_QUARANTINED`."
        PRD 3.6: "Hop two: because that ceremony lost its attestation, its
        partition moves `OPERATIONAL → QUARANTINED`, `quarantined_at` is
        stamped, `attested_ceremony_count` is recomputed, and the partition's
        `version` increments; quarantine is terminal, and a quarantined
        partition can never sign again."

        Design: Difficulty/cross_entity_state_dependency/issuance_gated_on_hsm_partition_state_not_on_the_ceremony
        """
        partition, first_ceremony, second_ceremony = (
            _partition_with_two_attested_ceremonies(client)
        )
        profile, subscriber, request = _ready_request(client)

        _repudiate(client, first_ceremony["id"], "K1 transcript signature could not be verified")

        response = client.issue_certificate(
            request["id"],
            issue_payload(second_ceremony["id"]),
            users.ISSUANCE_OPERATOR_9,
        )
        validate_error(response, ERR_PARTITION_QUARANTINED)

        # Every ceremony-side gate on the ceremony actually named is satisfied.
        signing = read_ceremony(client, second_ceremony["id"])
        assert signing["state"] == CEREMONY_ATTESTED, (
            "the ceremony named in the body is untouched by its sibling's "
            f"repudiation, found state {signing['state']!r}"
        )
        assert_instant_equals(
            signing["attestation_expires_at"],
            "2026-09-30T02:30:00Z",
            "attestation_expires_at",
        )

        quarantined = read_partition(client, partition["id"])
        assert quarantined["state"] == PARTITION_QUARANTINED
        assert_instant_equals(
            quarantined["quarantined_at"], "2026-08-01T02:30:00Z", "quarantined_at"
        )
        assert quarantined["attested_ceremony_count"] == 1, (
            "one ceremony is still attested, so the guard cannot be reading the "
            f"count, found attested_ceremony_count "
            f"{quarantined['attested_ceremony_count']}"
        )
        assert quarantined["version"] > partition["version"], (
            "quarantine increments the partition's version"
        )

        unchanged = read_request(client, request["id"])
        assert unchanged["state"] == REQUEST_READY_TO_ISSUE, (
            f"the refused issuance leaves the request ready, found "
            f"{unchanged['state']!r}"
        )
        assert_nulls(unchanged, "issued_certificate_id")

        rows, _meta = validate_paginated(
            client.list_certificates(users.ISSUANCE_OPERATOR)
        )
        assert rows == [], f"no certificate may exist, found {ids_of(rows)}"
        settled = read_subscriber(client, subscriber["id"])
        assert_counters(
            settled,
            outstanding_balance_cents=0,
            issued_certificate_count=0,
            account_status=SUBSCRIBER_ACTIVE,
        )
        assert read_profile(client, profile["id"])["status_service_posture"] == (
            POSTURE_NOMINAL
        )

    def test_b_quarantine_outranks_the_ceremony_state_gate_and_is_terminal(
        self, client
    ):
        """Naming the repudiated ceremony still reports the partition first.

        PRD 3.7: "The gates, in the order they are evaluated, are these. The
        request must be in `READY_TO_ISSUE`, so a request still `SUBMITTED`, or
        one sitting in `ISSUANCE_BLOCKED`, is refused with
        `ERR_REQUEST_NOT_READY`. The named ceremony's partition must be
        `OPERATIONAL`, or `ERR_PARTITION_QUARANTINED`."
        PRD 3.6: "The partition must be `OPERATIONAL`; scheduling on a
        quarantined partition is refused with `ERR_PARTITION_QUARANTINED`."

        Design: Difficulty/cross_entity_state_dependency/issuance_gated_on_hsm_partition_state_not_on_the_ceremony
        """
        partition, first_ceremony, _second = _partition_with_two_attested_ceremonies(
            client
        )
        _profile, _subscriber, request = _ready_request(client)

        repudiated = _repudiate(
            client, first_ceremony["id"], "the second custodian's signature was forged"
        )
        assert repudiated["state"] == CEREMONY_ATTESTATION_REVOKED

        # This ceremony fails the ATTESTED gate too, but the partition gate is
        # evaluated first, so the partition's error is the one reported.
        response = client.issue_certificate(
            request["id"],
            issue_payload(first_ceremony["id"]),
            users.ISSUANCE_OPERATOR_9,
        )
        validate_error(response, ERR_PARTITION_QUARANTINED)

        # Quarantine is terminal: the partition can never host a replacement.
        replacement = client.schedule_ceremony(
            partition["id"],
            ceremony_payload("2026-08-01T04:00:00Z", "2026-08-01T04:30:00Z", 60),
            users.ISSUANCE_OPERATOR,
        )
        validate_error(replacement, ERR_PARTITION_QUARANTINED)

        assert read_partition(client, partition["id"])["state"] == (
            PARTITION_QUARANTINED
        )
        assert read_request(client, request["id"])["state"] == REQUEST_READY_TO_ISSUE


def _suspended_by_two_pending_revocations(client):
    """Two issued certificates, each with an open revocation, suspend the account."""
    environment = build_environment(
        client, domains=("d1.example.org", "d2.example.org")
    )
    first = issue_certificate(client, environment, domains=("d1.example.org",))
    second = issue_certificate(client, environment, domains=("d2.example.org",))
    third = create_authorization(
        client, environment.subscriber_id, environment.profile_id, "d3.example.org"
    )
    assert third["state"] == AUTH_PENDING, (
        "the third proof is opened while the account is still ACTIVE"
    )

    first_revocation = raise_revocation(client, first, REASON_PRIVILEGE_WITHDRAWN)
    second_revocation = raise_revocation(client, second, REASON_PRIVILEGE_WITHDRAWN)
    suspended = read_subscriber(client, environment.subscriber_id)
    assert_counters(
        suspended, revocation_pending_count=2, account_status=SUBSCRIBER_SUSPENDED
    )
    assert_instant_equals(
        suspended["suspended_at"], "2026-08-01T00:30:00Z", "suspended_at"
    )
    return environment, third, first, second, first_revocation, second_revocation


class TestValidationGatedOnTheSubscriberBehindTheAuthorization:
    def test_c_denying_one_revocation_readmits_the_identical_validate_call(
        self, client
    ):
        """The same token and the same authorization, refused then accepted.

        PRD 3.4: "A `VALIDATION_OFFICER` submits a `challenge_token`; the
        authorization must be in `PENDING` or `FAILED` (anything else, including
        an already `VALIDATED`, `EXHAUSTED` or `EXPIRED` authorization, is
        refused with `ERR_AUTHORIZATION_NOT_VALIDATABLE`), and both the
        subscriber and the profile must still be `ACTIVE`."
        PRD 3.8: "The target certificate returns `REVOCATION_PENDING → NONE`,
        but only when no other revocation request for it remains in `REQUESTED`;
        the subscriber's `revocation_pending_count` decrements by one,
        un-suspending the account once it is below 2."

        Design: Difficulty/cross_entity_state_dependency/dcv_validation_gated_on_subscriber_account_status
        """
        (
            environment,
            third,
            first_certificate,
            second_certificate,
            _first_revocation,
            second_revocation,
        ) = _suspended_by_two_pending_revocations(client)
        token = third["challenge_token"]

        refused = client.validate_authorization(
            third["id"], validate_payload(token), users.VALIDATION_OFFICER
        )
        validate_error(refused, ERR_SUBSCRIBER_NOT_ACTIVE)
        untouched = read_authorization(client, third["id"])
        assert untouched["state"] == AUTH_PENDING, (
            f"a refused call must not move the proof, found {untouched['state']!r}"
        )
        assert_counters(untouched, attempt_count=0, invalidation_count=0)
        assert untouched["version"] == third["version"], (
            "a refused call spends no attempt, so the version cannot move: "
            f"{untouched['version']} != {third['version']}"
        )
        assert untouched["challenge_token"] == token, (
            "the stored challenge token is unchanged by the refusal"
        )

        denied = get_success_data(
            client.deny_revocation(
                second_revocation["id"],
                denial_payload("the subscriber withdrew the revocation request"),
                users.REVOCATION_OFFICER,
            )
        )
        assert denied["state"] == REVOCATION_DENIED, (
            f"denial is terminal, found state {denied['state']!r}"
        )
        assert denied["denial_reason"] == (
            "the subscriber withdrew the revocation request"
        )
        assert_instant_equals(
            denied["denied_at"], "2026-08-01T00:30:00Z", "denied_at"
        )
        released = read_certificate(client, second_certificate["id"])
        assert_certificate_dimensions(
            released, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_NONE
        )
        readmitted = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            readmitted, revocation_pending_count=1, account_status=SUBSCRIBER_ACTIVE
        )
        assert_nulls(readmitted, "suspended_at")

        accepted = get_success_data(
            client.validate_authorization(
                third["id"], validate_payload(token), users.VALIDATION_OFFICER
            )
        )
        assert accepted["state"] == AUTH_VALIDATED, (
            "the identical call now succeeds, found state "
            f"{accepted['state']!r}"
        )
        assert_counters(accepted, attempt_count=1, invalidation_count=0, reuse_count=0)
        assert_instant_equals(
            accepted["validated_at"], "2026-08-01T00:30:00Z", "validated_at"
        )
        assert_instant_equals(
            accepted["expires_at"], "2026-08-31T00:30:00Z", "expires_at"
        )

        # Only one of the two pending revocations was resolved.
        still_pending = read_certificate(client, first_certificate["id"])
        assert_certificate_dimensions(
            still_pending, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_PENDING
        )

    def test_d_executing_one_revocation_reopens_the_creation_gate_as_well(
        self, client
    ):
        """Suspension blocks opening a proof, and execution lifts the block.

        PRD 3.2: "What it blocks is participation: an account that is not
        `ACTIVE` cannot have a vetting file opened for it, cannot have a domain
        authorization created or validated, cannot have a certificate request
        created or submitted, cannot have a request's validation cleared, and
        cannot have a certificate issued."
        PRD 3.2: "Suspension is reversible: when pending revocations are
        executed or denied and `revocation_pending_count` falls below 2, a
        `SUSPENDED` account returns to `ACTIVE`, `suspended_at` is cleared back
        to null, and `version` increments again."

        Design: Difficulty/cross_entity_state_dependency/dcv_validation_gated_on_subscriber_account_status
        """
        (
            environment,
            _third,
            first_certificate,
            second_certificate,
            first_revocation,
            _second_revocation,
        ) = _suspended_by_two_pending_revocations(client)

        blocked = client.create_authorization(
            authorization_payload(
                environment.subscriber_id, environment.profile_id, "d4.example.org"
            ),
            users.VALIDATION_OFFICER,
        )
        validate_error(blocked, ERR_SUBSCRIBER_NOT_ACTIVE)

        executed = get_success_data(
            client.execute_revocation(
                first_revocation["id"], users.REVOCATION_OFFICER
            )
        )
        assert executed["state"] == REVOCATION_EXECUTED, (
            f"execution is terminal, found state {executed['state']!r}"
        )
        revoked = read_certificate(client, first_certificate["id"])
        assert_certificate_dimensions(
            revoked, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_REVOKED
        )
        assert_certificate_dimensions(
            read_certificate(client, second_certificate["id"]),
            LIFECYCLE_PREISSUANCE,
            REVOCATION_STATUS_PENDING,
        )
        restored = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            restored, revocation_pending_count=1, account_status=SUBSCRIBER_ACTIVE
        )
        assert_nulls(restored, "suspended_at")

        # The very same creation the suspended account was refused now works.
        reopened = create_authorization(
            client, environment.subscriber_id, environment.profile_id, "d4.example.org"
        )
        assert reopened["state"] == AUTH_PENDING
        proven = get_success_data(
            client.validate_authorization(
                reopened["id"],
                validate_payload(reopened["challenge_token"]),
                users.VALIDATION_OFFICER,
            )
        )
        assert proven["state"] == AUTH_VALIDATED, (
            f"validation is open again, found state {proven['state']!r}"
        )
        assert_counters(proven, attempt_count=1)
