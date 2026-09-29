"""Two multi-hop cascades, each fired by a single call.

Repudiating a ceremony attestation walks ceremony, partition, certificates and
subscriber; executing a revocation walks certificate, profile ledger and every
other request waiting on that profile.
"""

from test_helpers import (
    BLOCKED_REASON_STATUS_SERVICE_OVERDUE,
    CEREMONY_ATTESTATION_REVOKED,
    CEREMONY_ATTESTED,
    LIFECYCLE_PREISSUANCE,
    ORIGIN_SYSTEM_CASCADE,
    PARTITION_OPERATIONAL,
    PARTITION_QUARANTINED,
    POSTURE_CRL_OVERDUE,
    POSTURE_NOMINAL,
    REASON_CESSATION_OF_OPERATION,
    REASON_KEY_COMPROMISE,
    REASON_UNSPECIFIED,
    REQUEST_ISSUANCE_BLOCKED,
    REQUEST_ISSUED,
    REQUEST_READY_TO_ISSUE,
    REVOCATION_EXECUTED,
    REVOCATION_REQUESTED,
    REVOCATION_STATUS_NONE,
    REVOCATION_STATUS_PENDING,
    REVOCATION_STATUS_REVOKED,
    SUBSCRIBER_ACTIVE,
    SUBSCRIBER_SUSPENDED,
    SYSTEM_USER_ID,
    advance_clock,
    assert_certificate_dimensions,
    assert_counters,
    assert_crl_ledger_conserved,
    assert_instant_equals,
    assert_nulls,
    attestation_revocation_payload,
    attested_ceremony,
    build_environment,
    cleared_request,
    create_profile,
    get_success_data,
    ids_of,
    issue_certificate,
    issue_from_request,
    profile_payload,
    publish_crl,
    raise_revocation,
    read_ceremony,
    read_certificate,
    read_partition,
    read_profile,
    read_request,
    read_subscriber,
    users,
    validate_paginated,
)


def _system_cascade_requests(client):
    """Every revocation request the system raised for itself, oldest first."""
    response = client.list_revocations(
        users.REVOCATION_OFFICER, {"origin": ORIGIN_SYSTEM_CASCADE}
    )
    rows, meta = validate_paginated(response)
    return rows, meta


class TestAttestationRepudiationCascade:
    def test_a_repudiation_quarantines_the_partition_and_suspends_the_subscriber(
        self, client
    ):
        """One call walks ceremony, partition, two certificates and the subscriber.

        PRD 3.6: "Hop one: the ceremony moves `ATTESTED → ATTESTATION_REVOKED`,
        `attestation_revoked_at` is stamped with the logical clock, and the
        partition's `attested_ceremony_count` decrements by one."
        PRD 3.6: "each receives a system-raised revocation request whose `origin`
        is `SYSTEM_CASCADE`, whose `reason_code` is `KEY_COMPROMISE`, whose
        `evidence_ref` is the literal string `ceremony:` followed by the
        repudiated ceremony's identifier, and whose `requested_by_user_id` is the
        literal string `system`."
        PRD 3.6: "Hop four: because those certificates entered
        `REVOCATION_PENDING`, each affected subscriber's
        `revocation_pending_count` rises, and any subscriber whose count reaches
        2 moves `ACTIVE → SUSPENDED`."

        Design: Difficulty/transitive_cascade/attestation_repudiation_four_hop_cascade
        """
        environment = build_environment(
            client, domains=("d1.example.org", "d2.example.org")
        )
        first = issue_certificate(client, environment, domains=("d1.example.org",))
        second = issue_certificate(client, environment, domains=("d2.example.org",))
        partition_before = read_partition(client, environment.partition_id)
        assert partition_before["state"] == PARTITION_OPERATIONAL
        assert_counters(partition_before, attested_ceremony_count=1)

        get_success_data(
            client.revoke_attestation(
                environment.ceremony_id,
                attestation_revocation_payload(
                    "witness later repudiated the ceremony transcript"
                ),
                users.COMPLIANCE_AUDITOR_2,
            )
        )

        ceremony = read_ceremony(client, environment.ceremony_id)
        assert ceremony["state"] == CEREMONY_ATTESTATION_REVOKED, (
            f"hop one leaves the ceremony repudiated, found {ceremony['state']!r}"
        )
        assert_instant_equals(
            ceremony["attestation_revoked_at"],
            "2026-08-01T00:30:00Z",
            "attestation_revoked_at",
        )

        partition = read_partition(client, environment.partition_id)
        assert partition["state"] == PARTITION_QUARANTINED, (
            f"hop two quarantines the partition, found {partition['state']!r}"
        )
        assert_counters(partition, attested_ceremony_count=0)
        assert_instant_equals(
            partition["quarantined_at"], "2026-08-01T00:30:00Z", "quarantined_at"
        )

        for certificate in (first, second):
            reloaded = read_certificate(client, certificate["id"])
            assert_certificate_dimensions(
                reloaded, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_PENDING
            )
            assert_nulls(reloaded, "revoked_at", "revocation_reason_code")

        rows, meta = _system_cascade_requests(client)
        assert meta["total_count"] == 2, (
            f"one cascade request per affected certificate, found {meta['total_count']}"
        )
        assert [row["certificate_id"] for row in rows] == [
            first["id"],
            second["id"],
        ], "the cascade processes certificates in ascending created_at order"
        for row in rows:
            assert row["origin"] == ORIGIN_SYSTEM_CASCADE
            assert row["reason_code"] == REASON_KEY_COMPROMISE, (
                f"a cascade revocation cites KEY_COMPROMISE, found {row['reason_code']!r}"
            )
            assert row["state"] == REVOCATION_REQUESTED
            assert row["evidence_ref"] == f"ceremony:{environment.ceremony_id}", (
                f"evidence_ref is {row['evidence_ref']!r}, expected the ceremony marker"
            )
            assert row["requested_by_user_id"] == SYSTEM_USER_ID, (
                f"requested_by_user_id is {row['requested_by_user_id']!r}, "
                f"expected {SYSTEM_USER_ID!r}"
            )
            assert_instant_equals(
                row["deadline_at"], "2026-08-02T00:30:00Z", "deadline_at"
            )

        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber,
            revocation_pending_count=2,
            account_status=SUBSCRIBER_SUSPENDED,
        )
        profile = read_profile(client, environment.profile_id)
        assert_counters(
            profile, revoked_certificate_count=0, pending_crl_entry_count=0
        )
        assert_crl_ledger_conserved(profile)

    def test_b_the_cascade_reaches_sibling_ceremonies_and_skips_pending_certificates(
        self, client
    ):
        """Quarantine sweeps the whole partition, but only untouched certificates.

        PRD 3.6: "Hop three: because the partition is now quarantined, every
        certificate whose `ceremony_id` names *any* ceremony of that partition —
        not only the repudiated one — and whose `revocation_status` is `NONE`
        moves to `REVOCATION_PENDING`, processed in ascending `created_at`
        order"

        Design: Difficulty/transitive_cascade/attestation_repudiation_four_hop_cascade
        """
        environment = build_environment(
            client, domains=("d1.example.org", "d2.example.org")
        )
        first = issue_certificate(client, environment, domains=("d1.example.org",))

        # A second ceremony on the same partition, kept a full hour and one
        # second clear of the first window so it does not conflict.
        sibling = attested_ceremony(
            client,
            environment.partition_id,
            window_start="2026-08-01T01:30:01Z",
            window_end="2026-08-01T02:00:00Z",
        )
        request = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ("d2.example.org",),
        )
        second = issue_from_request(client, request["id"], sibling["id"])

        # The first certificate is already spoken for by an operator request, so
        # the cascade must leave it alone.
        manual = raise_revocation(client, first, REASON_UNSPECIFIED)

        get_success_data(
            client.revoke_attestation(
                environment.ceremony_id,
                attestation_revocation_payload(),
                users.COMPLIANCE_AUDITOR_2,
            )
        )

        assert read_ceremony(client, sibling["id"])["state"] == CEREMONY_ATTESTED, (
            "only the named ceremony is repudiated"
        )
        assert (
            read_partition(client, environment.partition_id)["state"]
            == PARTITION_QUARANTINED
        )

        reloaded_second = read_certificate(client, second["id"])
        assert_certificate_dimensions(
            reloaded_second, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_PENDING
        )

        rows, meta = _system_cascade_requests(client)
        assert meta["total_count"] == 1, (
            "a certificate already in REVOCATION_PENDING earns no cascade request, "
            f"found {meta['total_count']} cascade rows"
        )
        assert rows[0]["certificate_id"] == second["id"], (
            "the cascade covers the certificate signed by the sibling ceremony"
        )
        assert rows[0]["evidence_ref"] == f"ceremony:{environment.ceremony_id}"
        assert_instant_equals(
            rows[0]["deadline_at"], "2026-08-02T02:00:00Z", "deadline_at"
        )
        assert manual["id"] not in ids_of(rows), (
            "the operator's own request is not a SYSTEM_CASCADE request"
        )

        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber,
            revocation_pending_count=2,
            account_status=SUBSCRIBER_SUSPENDED,
        )


def _profile_at_threshold_one(client):
    """A DV profile whose CRL queue overflows on its very first entry."""
    return build_environment(
        client,
        profile_payload=profile_payload(crl_trigger_threshold=1),
        domains=("d1.example.org", "d2.example.org"),
    )


class TestRevocationExecutionPostureCascade:
    def test_a_execution_flips_the_posture_and_blocks_the_waiting_request(
        self, client
    ):
        """Certificate, then the profile ledger, then a sibling request.

        PRD 3.8: "Hop two: because the certificate became `REVOKED`, the
        governing profile's `revoked_certificate_count` and
        `pending_crl_entry_count` each rise by one."
        PRD 3.8: "Hop three: because `pending_crl_entry_count` has now reached
        `crl_trigger_threshold`, the profile's `status_service_posture` moves
        `NOMINAL → CRL_OVERDUE`, which in turn moves every `READY_TO_ISSUE`
        request of that profile to `ISSUANCE_BLOCKED` with `blocked_reason`
        `PROFILE_STATUS_SERVICE_OVERDUE`, in ascending `created_at` order."

        Design: Difficulty/transitive_cascade/revocation_execution_three_hop_posture_cascade
        """
        environment = _profile_at_threshold_one(client)
        first_request = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ("d1.example.org",),
        )
        certificate = issue_from_request(
            client, first_request["id"], environment.ceremony_id
        )
        waiting = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ("d2.example.org",),
        )
        assert waiting["state"] == REQUEST_READY_TO_ISSUE, (
            f"the second request waits in READY_TO_ISSUE, found {waiting['state']!r}"
        )

        request = raise_revocation(
            client,
            certificate,
            REASON_CESSATION_OF_OPERATION,
            evidence_ref="subscriber-ticket-991",
        )
        executed = get_success_data(
            client.execute_revocation(request["id"], users.REVOCATION_OFFICER)
        )
        assert executed["state"] == REVOCATION_EXECUTED, (
            f"execution closes the request, found {executed['state']!r}"
        )
        assert executed["deadline_breached"] is False, (
            "the execution is well inside the 120-hour allowance"
        )
        assert_instant_equals(
            executed["executed_at"], "2026-08-01T00:30:00Z", "executed_at"
        )

        revoked = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            revoked, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_REVOKED
        )
        assert revoked["revocation_reason_code"] == REASON_CESSATION_OF_OPERATION
        assert_nulls(revoked, "refunded_at", "crl_published_at", "crl_number")

        profile = read_profile(client, environment.profile_id)
        assert_counters(
            profile,
            revoked_certificate_count=1,
            pending_crl_entry_count=1,
            total_crl_entries_published=0,
        )
        assert profile["status_service_posture"] == POSTURE_CRL_OVERDUE, (
            "an unpublished entry at the threshold flips the posture, found "
            f"{profile['status_service_posture']!r}"
        )
        assert_crl_ledger_conserved(profile)

        blocked = read_request(client, waiting["id"])
        assert blocked["state"] == REQUEST_ISSUANCE_BLOCKED, (
            f"the waiting request is blocked, found {blocked['state']!r}"
        )
        assert blocked["blocked_reason"] == BLOCKED_REASON_STATUS_SERVICE_OVERDUE, (
            f"blocked_reason is {blocked['blocked_reason']!r}, expected the posture cause"
        )
        assert read_request(client, first_request["id"])["state"] == REQUEST_ISSUED, (
            "a request that already issued is never dragged into ISSUANCE_BLOCKED"
        )

        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber, revocation_pending_count=0, account_status=SUBSCRIBER_ACTIVE
        )

    def test_b_publishing_the_list_unblocks_the_request_the_cascade_blocked(
        self, client
    ):
        """Draining the queue reverses hop three and issuance resumes.

        PRD 2.10: "When a publication drains the queue so that
        `pending_crl_entry_count` is zero, the posture returns to `NOMINAL` and
        every `ISSUANCE_BLOCKED` request of that profile returns to
        `READY_TO_ISSUE` with `blocked_reason` cleared to null."
        PRD 3.8: "`crl_number` on the new publication is the profile's
        `last_crl_number` plus one, `entry_count` is the size of the drain set,
        and `revoked_serials` is the list of those certificates' `serial_number`
        values in that same order."

        Design: Difficulty/transitive_cascade/revocation_execution_three_hop_posture_cascade
        """
        environment = _profile_at_threshold_one(client)
        first_request = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ("d1.example.org",),
        )
        certificate = issue_from_request(
            client, first_request["id"], environment.ceremony_id
        )
        waiting = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ("d2.example.org",),
        )
        request = raise_revocation(client, certificate, REASON_CESSATION_OF_OPERATION)
        get_success_data(
            client.execute_revocation(request["id"], users.REVOCATION_OFFICER)
        )
        assert (
            read_request(client, waiting["id"])["state"] == REQUEST_ISSUANCE_BLOCKED
        ), "the cascade must block the waiting request before it can be unblocked"

        publication = publish_crl(
            client,
            environment.profile_id,
            "2026-08-01T00:00:00Z",
            "2026-08-01T12:00:00Z",
        )
        assert_counters(publication, crl_number=1, entry_count=1)
        assert publication["revoked_serials"] == [certificate["serial_number"]], (
            f"revoked_serials is {publication['revoked_serials']!r}, expected the one "
            "drained serial"
        )

        profile = read_profile(client, environment.profile_id)
        assert profile["status_service_posture"] == POSTURE_NOMINAL, (
            "an empty queue returns the posture to NOMINAL, found "
            f"{profile['status_service_posture']!r}"
        )
        assert_counters(
            profile,
            pending_crl_entry_count=0,
            total_crl_entries_published=1,
            revoked_certificate_count=1,
            last_crl_number=1,
        )
        assert_crl_ledger_conserved(profile)

        unblocked = read_request(client, waiting["id"])
        assert unblocked["state"] == REQUEST_READY_TO_ISSUE, (
            f"the request returns to READY_TO_ISSUE, found {unblocked['state']!r}"
        )
        assert_nulls(unblocked, "blocked_reason")

        second = issue_from_request(client, waiting["id"], environment.ceremony_id)
        assert_certificate_dimensions(
            second, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_NONE
        )
        assert second["serial_number"] != certificate["serial_number"], (
            "each issuance takes the next serial in the series"
        )
        drained = read_certificate(client, certificate["id"])
        assert_counters(drained, crl_number=1)
        assert_instant_equals(
            drained["crl_published_at"], "2026-08-01T00:30:00Z", "crl_published_at"
        )
