"""Version tokens and cumulative thresholds, observed across whole chains.

Each scenario spends a token or crosses a counter boundary and then reads back
every row the write was supposed to touch, so a guard that fires late or a
counter that latches instead of counting is visible.
"""

from test_helpers import (
    ERR_STALE_CERTIFICATE_VERSION,
    ERR_STALE_PROFILE_VERSION,
    BLOCKED_REASON_STATUS_SERVICE_OVERDUE,
    LIFECYCLE_ISSUED,
    LIFECYCLE_PREISSUANCE,
    ORIGIN_SUBSCRIBER,
    POSTURE_CRL_OVERDUE,
    POSTURE_NOMINAL,
    REASON_CESSATION_OF_OPERATION,
    REASON_PRIVILEGE_WITHDRAWN,
    REASON_SUPERSEDED,
    REQUEST_ISSUANCE_BLOCKED,
    REQUEST_READY_TO_ISSUE,
    REVOCATION_REQUESTED,
    REVOCATION_STATUS_NONE,
    REVOCATION_STATUS_PENDING,
    REVOCATION_STATUS_REVOKED,
    SUBSCRIBER_ACTIVE,
    SUBSCRIBER_SUSPENDED,
    activate_certificate,
    assert_certificate_dimensions,
    assert_counters,
    assert_crl_ledger_conserved,
    assert_instant_equals,
    assert_nulls,
    build_environment,
    cleared_request,
    create_profile,
    crl_publication_payload,
    denial_payload,
    get_success_data,
    issue_certificate,
    profile_payload,
    profile_version,
    publish_crl,
    raise_revocation,
    read_certificate,
    read_profile,
    read_request,
    read_subscriber,
    revocation_payload,
    subscriber_payload,
    users,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-01T00:30:00Z"


def _dv_profile(**overrides):
    """A DV profile that needs no SCTs and charges 20000 cents per domain."""
    return profile_payload(
        required_sct_count=0,
        max_dcv_reuse_count=5,
        base_fee_cents=20000,
        **overrides,
    )


def _activated_certificate(client):
    """One certificate carried to ISSUED, keeping the version seen at issuance."""
    environment = build_environment(
        client,
        profile_payload=_dv_profile(),
        subscriber_payload=subscriber_payload(credit_limit_cents=500000),
    )
    issued = issue_certificate(client, environment)
    activated = activate_certificate(client, issued, 0)
    assert activated["lifecycle_status"] == LIFECYCLE_ISSUED, (
        f"lifecycle_status is {activated['lifecycle_status']!r}, expected "
        f"{LIFECYCLE_ISSUED!r}"
    )
    return environment, issued, activated


def _two_pending_certificates(client, **profile_overrides):
    """Two PREISSUANCE certificates, one per domain, on a single subscriber."""
    environment = build_environment(
        client,
        profile_payload=_dv_profile(**profile_overrides),
        subscriber_payload=subscriber_payload(credit_limit_cents=500000),
        domains=("a.example.org", "b.example.org", "c.example.org"),
    )
    first = issue_certificate(client, environment, domains=("a.example.org",))
    second = issue_certificate(client, environment, domains=("b.example.org",))
    return environment, first, second


def _profile_at_the_crl_threshold(client):
    """Two revocations queued on a profile whose threshold is two, plus a
    request left waiting in `READY_TO_ISSUE`."""
    environment, first, second = _two_pending_certificates(
        client, crl_trigger_threshold=2
    )
    queued = cleared_request(
        client,
        environment.subscriber_id,
        environment.profile_id,
        ("c.example.org",),
    )
    request_one = raise_revocation(client, first, REASON_SUPERSEDED)
    request_two = raise_revocation(client, second, REASON_SUPERSEDED)
    return environment, first, second, queued, request_one, request_two


class TestAStaleCertificateVersionBlocksTheRevocation:
    def test_a_the_version_captured_at_issuance_is_spent_by_the_activation(
        self, client
    ):
        """An unrelated write on the same row invalidates the revocation client.

        PRD 2.5: "The first is raising a revocation request. That operation
        requires the non-optional input field `expected_certificate_version`,
        carrying the `version` of the target certificate as the client last
        observed it."
        PRD 2.5: "If the value does not equal the certificate's current
        `version`, the request is rejected with `ERR_STALE_CERTIFICATE_VERSION`
        (HTTP 412)."
        PRD 2.4: "`version` is an integer that begins at 1 when the resource is
        created and increases by exactly one on every mutation of that resource,
        whether the mutation was requested directly by a client or applied
        indirectly by a cascade."

        Design: Corner/cross_cutting_complexity_layers/a_stale_certificate_version_token_blocks_the_revocation_request
        """
        environment, issued, activated = _activated_certificate(client)
        stale_version = issued["version"]

        refused = client.raise_revocation(
            revocation_payload(
                issued["id"], REASON_PRIVILEGE_WITHDRAWN, stale_version
            ),
            users.REVOCATION_OFFICER,
        )
        validate_error(refused, ERR_STALE_CERTIFICATE_VERSION, 412)

        settled = read_certificate(client, issued["id"])
        assert_certificate_dimensions(
            settled, LIFECYCLE_ISSUED, REVOCATION_STATUS_NONE
        )
        assert settled["version"] == stale_version + 1, (
            "the activation was the only intervening write, so the fresh version "
            f"is {stale_version + 1}, found {settled['version']}"
        )
        assert activated["version"] == settled["version"]
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            revocation_pending_count=0,
            account_status=SUBSCRIBER_ACTIVE,
        )
        _, meta = validate_paginated(
            client.list_revocations(
                users.REVOCATION_OFFICER, {"certificate_id": issued["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"a refused guard writes no request, found {meta['total_count']}"
        )

    def test_b_the_re_read_version_is_accepted_and_moves_the_certificate(
        self, client
    ):
        """Only the current version opens the revocation, and it cascades at once.

        PRD 2.5: "If the value does not equal the certificate's current
        `version`, the request is rejected with `ERR_STALE_CERTIFICATE_VERSION`
        (HTTP 412)."
        PRD 3.8: "The presence of the link also decides provenance: `origin` is
        set to `SUBSCRIBER` when `incident_id` is absent and to `COMPLIANCE` when
        it is present."
        PRD 3.8: "Its `revocation_status` goes `NONE → REVOCATION_PENDING`, its
        `version` increments, and the owning subscriber's
        `revocation_pending_count` rises by one — which suspends the account the
        moment that count reaches 2, as described in §3.2."

        Design: Corner/cross_cutting_complexity_layers/a_stale_certificate_version_token_blocks_the_revocation_request
        """
        environment, issued, _activated = _activated_certificate(client)

        validate_error(
            client.raise_revocation(
                revocation_payload(
                    issued["id"], REASON_PRIVILEGE_WITHDRAWN, issued["version"]
                ),
                users.REVOCATION_OFFICER,
            ),
            ERR_STALE_CERTIFICATE_VERSION,
            412,
        )

        fresh = read_certificate(client, issued["id"])
        request = get_success_data(
            client.raise_revocation(
                revocation_payload(
                    fresh["id"], REASON_PRIVILEGE_WITHDRAWN, fresh["version"]
                ),
                users.REVOCATION_OFFICER,
            ),
            201,
        )
        assert request["state"] == REVOCATION_REQUESTED, (
            f"state is {request['state']!r}, expected {REVOCATION_REQUESTED!r}"
        )
        assert request["origin"] == ORIGIN_SUBSCRIBER, (
            "no incident_id was supplied, so origin is "
            f"{ORIGIN_SUBSCRIBER!r}, found {request['origin']!r}"
        )
        assert_nulls(request, "incident_id", "executed_at", "denied_at")

        assert_certificate_dimensions(
            read_certificate(client, issued["id"]),
            LIFECYCLE_ISSUED,
            REVOCATION_STATUS_PENDING,
        )
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            revocation_pending_count=1,
            account_status=SUBSCRIBER_ACTIVE,
        )
        assert_nulls(read_subscriber(client, environment.subscriber_id), "suspended_at")


class TestOneProfileVersionTokenPublishesOnce:
    def test_a_replaying_the_spent_token_is_refused_and_consumes_no_crl_number(
        self, client
    ):
        """The first publication spends the token by writing the profile row.

        PRD 2.5: "The second is publishing a revocation list for a profile. That
        operation requires the non-optional input field
        `expected_profile_version`, carrying the `version` of the target
        certificate profile as the client last observed it."
        PRD 2.5: "A mismatch against the profile's current `version` is rejected
        with `ERR_STALE_PROFILE_VERSION` (HTTP 412)."
        PRD 3.8: "A publication with an empty drain set is perfectly legal:
        `entry_count` is 0, `revoked_serials` is an empty array, and `crl_number`
        still advances by one."

        Design: Corner/cross_cutting_complexity_layers/the_same_profile_version_token_publishes_once_and_is_then_stale
        """
        profile = create_profile(client, profile_payload(base_fee_cents=20000))
        token = profile["version"]

        first = get_success_data(
            client.publish_crl(
                profile["id"],
                crl_publication_payload(
                    CLOCK_START, "2026-08-02T00:00:00Z", token
                ),
                users.REVOCATION_OFFICER,
            ),
            201,
        )
        assert_counters(first, crl_number=1, entry_count=0)
        assert first["revoked_serials"] == [], (
            f"revoked_serials is {first['revoked_serials']!r}, expected empty"
        )

        replay = client.publish_crl(
            profile["id"],
            crl_publication_payload(
                "2026-08-01T23:00:00Z", "2026-08-02T22:00:00Z", token
            ),
            users.REVOCATION_OFFICER,
        )
        validate_error(replay, ERR_STALE_PROFILE_VERSION, 412)

        settled = read_profile(client, profile["id"])
        assert_counters(settled, last_crl_number=1, version=token + 1)
        assert_instant_equals(
            settled["last_crl_next_update"],
            "2026-08-02T00:00:00Z",
            "last_crl_next_update",
        )
        _, meta = validate_paginated(
            client.list_crl_publications(profile["id"], users.REVOCATION_OFFICER)
        )
        assert meta["total_count"] == 1, (
            f"the refused replay adds no publication, found {meta['total_count']}"
        )

    def test_b_the_re_read_token_mints_the_next_crl_number(self, client):
        """With the current version the same window publishes as list number two.

        PRD 2.5: "A mismatch against the profile's current `version` is rejected
        with `ERR_STALE_PROFILE_VERSION` (HTTP 412)."
        PRD 3.8: "`crl_number` on the new publication is the profile's
        `last_crl_number` plus one, `entry_count` is the size of the drain set,
        and `revoked_serials` is the list of those certificates' `serial_number`
        values in that same order."
        PRD 3.8: "On the profile, `total_crl_entries_published` grows by
        `entry_count`, `pending_crl_entry_count` is reset to 0, `last_crl_number`
        becomes the new number, and `last_crl_this_update` and
        `last_crl_next_update` take the submitted `this_update` and
        `next_update`."

        Design: Corner/cross_cutting_complexity_layers/the_same_profile_version_token_publishes_once_and_is_then_stale
        """
        profile = create_profile(client, profile_payload(base_fee_cents=20000))
        token = profile["version"]
        get_success_data(
            client.publish_crl(
                profile["id"],
                crl_publication_payload(
                    CLOCK_START, "2026-08-02T00:00:00Z", token
                ),
                users.REVOCATION_OFFICER,
            ),
            201,
        )
        validate_error(
            client.publish_crl(
                profile["id"],
                crl_publication_payload(
                    "2026-08-01T23:00:00Z", "2026-08-02T22:00:00Z", token
                ),
                users.REVOCATION_OFFICER,
            ),
            ERR_STALE_PROFILE_VERSION,
            412,
        )

        fresh_token = profile_version(client, profile["id"])
        assert fresh_token == token + 1, (
            f"the publication was the only write, so the version is {token + 1}, "
            f"found {fresh_token}"
        )
        second = get_success_data(
            client.publish_crl(
                profile["id"],
                crl_publication_payload(
                    "2026-08-01T23:00:00Z", "2026-08-02T22:00:00Z", fresh_token
                ),
                users.REVOCATION_OFFICER,
            ),
            201,
        )
        assert_counters(second, crl_number=2, entry_count=0)
        assert_instant_equals(
            second["this_update"], "2026-08-01T23:00:00Z", "this_update"
        )
        assert_instant_equals(
            second["next_update"], "2026-08-02T22:00:00Z", "next_update"
        )

        settled = read_profile(client, profile["id"])
        assert_counters(
            settled,
            last_crl_number=2,
            total_crl_entries_published=0,
            pending_crl_entry_count=0,
        )
        assert_instant_equals(
            settled["last_crl_this_update"],
            "2026-08-01T23:00:00Z",
            "last_crl_this_update",
        )


class TestSuspensionTripsAtExactlyTwoPendingRevocations:
    def test_a_one_pending_revocation_is_below_the_threshold(self, client):
        """The first pending revocation leaves the account active.

        PRD 3.2: "When `revocation_pending_count` reaches 2 or more while the
        account is `ACTIVE`, the account moves `ACTIVE → SUSPENDED`,
        `suspended_at` is stamped with the logical clock, and `version`
        increments."
        PRD 3.8: "Its `revocation_status` goes `NONE → REVOCATION_PENDING`, its
        `version` increments, and the owning subscriber's
        `revocation_pending_count` rises by one — which suspends the account the
        moment that count reaches 2, as described in §3.2."

        Design: Corner/cross_cutting_complexity_layers/subscriber_suspension_trips_at_exactly_two_pending_revocations_and_resets
        """
        environment, first, _second = _two_pending_certificates(client)

        raise_revocation(client, first, REASON_CESSATION_OF_OPERATION)

        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber, revocation_pending_count=1, account_status=SUBSCRIBER_ACTIVE
        )
        assert_nulls(subscriber, "suspended_at")
        assert_certificate_dimensions(
            read_certificate(client, first["id"]),
            LIFECYCLE_PREISSUANCE,
            REVOCATION_STATUS_PENDING,
        )

    def test_b_the_second_pending_revocation_suspends_the_account(self, client):
        """Crossing to two flips the account and stamps the logical clock.

        PRD 3.2: "When `revocation_pending_count` reaches 2 or more while the
        account is `ACTIVE`, the account moves `ACTIVE → SUSPENDED`,
        `suspended_at` is stamped with the logical clock, and `version`
        increments."
        PRD 3.8: "Its `revocation_status` goes `NONE → REVOCATION_PENDING`, its
        `version` increments, and the owning subscriber's
        `revocation_pending_count` rises by one — which suspends the account the
        moment that count reaches 2, as described in §3.2."

        Design: Corner/cross_cutting_complexity_layers/subscriber_suspension_trips_at_exactly_two_pending_revocations_and_resets
        """
        environment, first, second = _two_pending_certificates(client)

        raise_revocation(client, first, REASON_CESSATION_OF_OPERATION)
        raise_revocation(client, second, REASON_CESSATION_OF_OPERATION)

        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber,
            revocation_pending_count=2,
            account_status=SUBSCRIBER_SUSPENDED,
        )
        assert_instant_equals(subscriber["suspended_at"], WINDOW_END, "suspended_at")

    def test_c_denying_one_request_un_suspends_and_the_other_executes(self, client):
        """The counter is a counter: it falls back and the account follows it.

        PRD 3.2: "Suspension is reversible: when pending revocations are executed
        or denied and `revocation_pending_count` falls below 2, a `SUSPENDED`
        account returns to `ACTIVE`, `suspended_at` is cleared back to null, and
        `version` increments again."
        PRD 3.8: "The target certificate returns `REVOCATION_PENDING → NONE`, but
        only when no other revocation request for it remains in `REQUESTED`; the
        subscriber's `revocation_pending_count` decrements by one, un-suspending
        the account once it is below 2."
        PRD 3.8: "Hop two: because the certificate became `REVOKED`, the
        governing profile's `revoked_certificate_count` and
        `pending_crl_entry_count` each rise by one."

        Design: Corner/cross_cutting_complexity_layers/subscriber_suspension_trips_at_exactly_two_pending_revocations_and_resets
        """
        environment, first, second = _two_pending_certificates(client)
        request_one = raise_revocation(client, first, REASON_CESSATION_OF_OPERATION)
        request_two = raise_revocation(client, second, REASON_CESSATION_OF_OPERATION)

        validate_success(
            client.deny_revocation(
                request_one["id"],
                denial_payload(
                    "Subscriber withdrew the cessation notice for the first host"
                ),
                users.REVOCATION_OFFICER,
            )
        )
        released = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            released, revocation_pending_count=1, account_status=SUBSCRIBER_ACTIVE
        )
        assert_nulls(released, "suspended_at")
        assert_certificate_dimensions(
            read_certificate(client, first["id"]),
            LIFECYCLE_PREISSUANCE,
            REVOCATION_STATUS_NONE,
        )
        assert_certificate_dimensions(
            read_certificate(client, second["id"]),
            LIFECYCLE_PREISSUANCE,
            REVOCATION_STATUS_PENDING,
        )

        validate_success(
            client.execute_revocation(request_two["id"], users.REVOCATION_OFFICER)
        )
        drained = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            drained, revocation_pending_count=0, account_status=SUBSCRIBER_ACTIVE
        )
        revoked = read_certificate(client, second["id"])
        assert_certificate_dimensions(
            revoked, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_REVOKED
        )
        assert_instant_equals(revoked["revoked_at"], WINDOW_END, "revoked_at")
        profile = read_profile(client, environment.profile_id)
        assert_counters(
            profile,
            pending_crl_entry_count=1,
            revoked_certificate_count=1,
            status_service_posture=POSTURE_NOMINAL,
        )
        assert_crl_ledger_conserved(profile)


class TestCrlOverduePostureTripsAtTheThreshold:
    def test_a_the_second_queued_entry_trips_the_posture_and_blocks_the_queue(
        self, client
    ):
        """One entry is below the threshold; the second crosses it and cascades.

        PRD 3.8: "Hop two: because the certificate became `REVOKED`, the
        governing profile's `revoked_certificate_count` and
        `pending_crl_entry_count` each rise by one."
        PRD 3.8: "Hop three: because `pending_crl_entry_count` has now reached
        `crl_trigger_threshold`, the profile's `status_service_posture` moves
        `NOMINAL → CRL_OVERDUE`, which in turn moves every `READY_TO_ISSUE`
        request of that profile to `ISSUANCE_BLOCKED` with `blocked_reason`
        `PROFILE_STATUS_SERVICE_OVERDUE`, in ascending `created_at` order."

        Design: Corner/cross_cutting_complexity_layers/crl_overdue_posture_trips_at_the_threshold_and_unblocks_on_publication
        """
        (
            environment,
            _first,
            _second,
            queued,
            request_one,
            request_two,
        ) = _profile_at_the_crl_threshold(client)

        validate_success(
            client.execute_revocation(request_one["id"], users.REVOCATION_OFFICER)
        )
        at_one = read_profile(client, environment.profile_id)
        assert_counters(
            at_one,
            pending_crl_entry_count=1,
            revoked_certificate_count=1,
            status_service_posture=POSTURE_NOMINAL,
        )
        still_ready = read_request(client, queued["id"])
        assert still_ready["state"] == REQUEST_READY_TO_ISSUE, (
            "one entry is strictly below the threshold of two, so the queued "
            f"request stays ready, found {still_ready['state']!r}"
        )
        assert_nulls(still_ready, "blocked_reason")

        validate_success(
            client.execute_revocation(request_two["id"], users.REVOCATION_OFFICER)
        )
        at_two = read_profile(client, environment.profile_id)
        assert_counters(
            at_two,
            pending_crl_entry_count=2,
            revoked_certificate_count=2,
            status_service_posture=POSTURE_CRL_OVERDUE,
        )
        blocked = read_request(client, queued["id"])
        assert blocked["state"] == REQUEST_ISSUANCE_BLOCKED, (
            f"state is {blocked['state']!r}, expected {REQUEST_ISSUANCE_BLOCKED!r}"
        )
        assert blocked["blocked_reason"] == BLOCKED_REASON_STATUS_SERVICE_OVERDUE, (
            f"blocked_reason is {blocked['blocked_reason']!r}, expected "
            f"{BLOCKED_REASON_STATUS_SERVICE_OVERDUE!r}"
        )

    def test_b_one_publication_drains_both_entries_and_unblocks_the_queue(
        self, client
    ):
        """The reset is complete: posture, queue counter and blocked reason.

        PRD 3.8: "The drain set is every certificate of that profile whose
        `revocation_status` is `REVOKED` and whose `crl_published_at` is still
        null, ordered by ascending `revoked_at` with ties broken by ascending
        `serial_number`."
        PRD 3.8: "On the profile, `total_crl_entries_published` grows by
        `entry_count`, `pending_crl_entry_count` is reset to 0, `last_crl_number`
        becomes the new number, and `last_crl_this_update` and
        `last_crl_next_update` take the submitted `this_update` and
        `next_update`."
        PRD 3.8: "Because the queue is now empty, the profile's posture returns
        `CRL_OVERDUE → NOMINAL` and every `ISSUANCE_BLOCKED` request of the
        profile returns to `READY_TO_ISSUE` with `blocked_reason` cleared,
        processed in ascending `created_at` order, and the profile's `version`
        increments."

        Design: Corner/cross_cutting_complexity_layers/crl_overdue_posture_trips_at_the_threshold_and_unblocks_on_publication
        """
        (
            environment,
            first,
            second,
            queued,
            request_one,
            request_two,
        ) = _profile_at_the_crl_threshold(client)
        validate_success(
            client.execute_revocation(request_one["id"], users.REVOCATION_OFFICER)
        )
        validate_success(
            client.execute_revocation(request_two["id"], users.REVOCATION_OFFICER)
        )
        assert (
            read_profile(client, environment.profile_id)["status_service_posture"]
            == POSTURE_CRL_OVERDUE
        )

        publication = publish_crl(
            client, environment.profile_id, WINDOW_END, "2026-08-02T00:30:00Z"
        )
        assert_counters(publication, entry_count=2, crl_number=1)
        assert publication["revoked_serials"] == [
            first["serial_number"],
            second["serial_number"],
        ], (
            "the drain set is ordered by ascending revoked_at then serial_number, "
            f"found {publication['revoked_serials']!r}"
        )

        settled = read_profile(client, environment.profile_id)
        assert_counters(
            settled,
            pending_crl_entry_count=0,
            total_crl_entries_published=2,
            revoked_certificate_count=2,
            status_service_posture=POSTURE_NOMINAL,
        )
        assert_crl_ledger_conserved(settled)
        unblocked = read_request(client, queued["id"])
        assert unblocked["state"] == REQUEST_READY_TO_ISSUE, (
            f"state is {unblocked['state']!r}, expected {REQUEST_READY_TO_ISSUE!r}"
        )
        assert_nulls(unblocked, "blocked_reason")
        for certificate_id in (first["id"], second["id"]):
            drained = read_certificate(client, certificate_id)
            assert_counters(drained, crl_number=1)
            assert_instant_equals(
                drained["crl_published_at"], WINDOW_END, "crl_published_at"
            )
