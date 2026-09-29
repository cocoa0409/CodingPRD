"""Three quantities the PRD promises are conserved, each against a different undo.

CRL entries hand off between two buckets on the profile, money is credited back
by a compensating refund, and domain-authorization reuse credits are released by
a rollback that must return exactly what it took.
"""

from test_helpers import (
    AUTH_PENDING,
    AUTH_VALIDATED,
    ERR_DCV_REUSE_LIMIT_EXCEEDED,
    ERR_REVOCATION_REQUEST_NOT_OPEN,
    LIFECYCLE_ISSUED,
    LIFECYCLE_PREISSUANCE,
    POSTURE_NOMINAL,
    REASON_KEY_COMPROMISE,
    REASON_SUPERSEDED,
    REASON_UNSPECIFIED,
    REQUEST_READY_TO_ISSUE,
    REQUEST_SUBMITTED,
    REVOCATION_DENIED,
    REVOCATION_STATUS_REVOKED,
    activate_certificate,
    advance_clock,
    assert_balance_matches_unrefunded,
    assert_certificate_dimensions,
    assert_counters,
    assert_crl_ledger_conserved,
    assert_instant_equals,
    assert_nulls,
    build_environment,
    create_authorization,
    create_profile,
    create_subscriber,
    denial_payload,
    get_success_data,
    invalidate_payload,
    issue_certificate,
    publish_crl,
    raise_revocation,
    read_authorization,
    read_certificate,
    read_profile,
    read_request,
    read_subscriber,
    revoke_certificate,
    submitted_request,
    users,
    validate_authorization,
    validate_error,
    validate_payload,
)


def _profile_counters(client, profile_id):
    """The three revocation counters, checked against their invariant."""
    profile = read_profile(client, profile_id)
    assert_crl_ledger_conserved(profile)
    return (
        profile["total_crl_entries_published"],
        profile["pending_crl_entry_count"],
        profile["revoked_certificate_count"],
    )


class TestCrlEntryLedgerConservation:
    def test_a_a_publication_hands_the_pending_entries_over_without_drift(
        self, client
    ):
        """Two revoked certificates move from pending to published, once.

        PRD 2.10: "Each certificate profile maintains three counters over its
        own revocations, and they are bound by an invariant that must hold before
        and after every publication: `total_crl_entries_published` plus
        `pending_crl_entry_count` always equals `revoked_certificate_count`."
        PRD 3.8: "A publication with an empty drain set is perfectly legal:
        `entry_count` is 0, `revoked_serials` is an empty array, and `crl_number`
        still advances by one."

        Design: Difficulty/compensating_invariant/crl_entry_ledger_conservation_across_publications
        """
        environment = build_environment(
            client, domains=("d1.example.org", "d2.example.org")
        )
        first = issue_certificate(client, environment, domains=("d1.example.org",))
        second = issue_certificate(client, environment, domains=("d2.example.org",))
        assert _profile_counters(client, environment.profile_id) == (0, 0, 0)

        revoke_certificate(client, first, REASON_UNSPECIFIED)
        assert _profile_counters(client, environment.profile_id) == (0, 1, 1)
        revoke_certificate(client, second, REASON_UNSPECIFIED)
        assert _profile_counters(client, environment.profile_id) == (0, 2, 2), (
            "two executed revocations sit in the pending bucket with nothing "
            "published yet"
        )

        publication = publish_crl(
            client,
            environment.profile_id,
            "2026-08-01T00:00:00Z",
            "2026-08-01T12:00:00Z",
        )
        assert_counters(publication, crl_number=1, entry_count=2)
        assert publication["revoked_serials"] == [
            first["serial_number"],
            second["serial_number"],
        ], (
            "the drain set is ordered by ascending revoked_at then serial_number, "
            f"found {publication['revoked_serials']}"
        )
        assert _profile_counters(client, environment.profile_id) == (2, 0, 2), (
            "the publication moves both entries across without creating or "
            "dropping one"
        )

        for certificate in (first, second):
            drained = read_certificate(client, certificate["id"])
            assert_counters(drained, crl_number=1)
            assert_instant_equals(
                drained["crl_published_at"], "2026-08-01T00:30:00Z", "crl_published_at"
            )

        # An empty second publication still advances the series and must leave
        # the ledger exactly where it was.
        advance_clock(client, "2026-08-01T06:00:00Z")
        empty = publish_crl(
            client,
            environment.profile_id,
            "2026-08-01T11:30:00Z",
            "2026-08-01T23:30:00Z",
        )
        assert_counters(empty, crl_number=2, entry_count=0)
        assert empty["revoked_serials"] == [], (
            f"nothing is left to drain, found {empty['revoked_serials']}"
        )
        assert _profile_counters(client, environment.profile_id) == (2, 0, 2), (
            "the empty publication must not double-count the drained entries"
        )
        for certificate in (first, second):
            untouched = read_certificate(client, certificate["id"])
            assert_counters(untouched, crl_number=1)
            assert_instant_equals(
                untouched["crl_published_at"],
                "2026-08-01T00:30:00Z",
                "crl_published_at after a second publication",
            )
        assert read_profile(client, environment.profile_id)[
            "status_service_posture"
        ] == POSTURE_NOMINAL, "two entries are far below a threshold of 100"

    def test_b_partial_drains_and_a_denial_leave_the_identity_standing(self, client):
        """One entry per publication, and a denied revocation that moves nothing.

        PRD 2.10: "A revocation raises `revoked_certificate_count` and
        `pending_crl_entry_count` together by one; a publication moves whatever
        is pending into `total_crl_entries_published` and resets
        `pending_crl_entry_count` to zero."
        PRD 2.10: "No path in the system may drop a revocation from the queue
        without publishing it, and no publication may carry the same certificate
        twice — a certificate's `crl_published_at` and `crl_number` are stamped
        by the first list that carries its serial and are never rewritten."

        Design: Difficulty/compensating_invariant/crl_entry_ledger_conservation_across_publications
        """
        environment = build_environment(
            client,
            domains=("d1.example.org", "d2.example.org", "d3.example.org"),
        )
        first = issue_certificate(client, environment, domains=("d1.example.org",))
        second = issue_certificate(client, environment, domains=("d2.example.org",))
        third = issue_certificate(client, environment, domains=("d3.example.org",))

        revoke_certificate(client, first, REASON_UNSPECIFIED)
        assert _profile_counters(client, environment.profile_id) == (0, 1, 1)
        publication_one = publish_crl(
            client,
            environment.profile_id,
            "2026-08-01T00:00:00Z",
            "2026-08-01T12:00:00Z",
        )
        assert_counters(publication_one, crl_number=1, entry_count=1)
        assert publication_one["revoked_serials"] == [first["serial_number"]]
        assert _profile_counters(client, environment.profile_id) == (1, 0, 1)

        advance_clock(client, "2026-08-01T06:00:00Z")
        revoke_certificate(client, second, REASON_UNSPECIFIED)
        # A denied revocation never reaches the queue at all.
        denied_request = raise_revocation(client, third, REASON_UNSPECIFIED)
        denied = get_success_data(
            client.deny_revocation(
                denied_request["id"],
                denial_payload("the registrant retracted the report"),
                users.REVOCATION_OFFICER,
            )
        )
        assert denied["state"] == REVOCATION_DENIED
        assert _profile_counters(client, environment.profile_id) == (1, 1, 2), (
            "only the executed revocation charges the ledger"
        )

        publication_two = publish_crl(
            client,
            environment.profile_id,
            "2026-08-01T11:30:00Z",
            "2026-08-01T23:30:00Z",
        )
        assert_counters(publication_two, crl_number=2, entry_count=1)
        assert publication_two["revoked_serials"] == [second["serial_number"]], (
            "the first certificate was already published and must not appear "
            f"twice, found {publication_two['revoked_serials']}"
        )
        assert _profile_counters(client, environment.profile_id) == (2, 0, 2)

        stamped_first = read_certificate(client, first["id"])
        assert_counters(stamped_first, crl_number=1)
        assert_instant_equals(
            stamped_first["crl_published_at"],
            "2026-08-01T00:30:00Z",
            "the first certificate's crl_published_at",
        )
        stamped_second = read_certificate(client, second["id"])
        assert_counters(stamped_second, crl_number=2)
        assert_instant_equals(
            stamped_second["crl_published_at"],
            "2026-08-01T06:00:00Z",
            "the second certificate's crl_published_at",
        )
        assert_nulls(read_certificate(client, third["id"]), "crl_published_at", "crl_number")


class TestSubscriberBalanceConservation:
    def test_c_a_superseded_preissuance_refund_credits_the_charge_exactly_once(
        self, client
    ):
        """The ledger empties, the history does not, and the credit cannot repeat.

        PRD 2.9: "It is defined at all times as the sum of
        `charged_amount_cents` over that subscriber's certificates whose
        `refunded_at` is null."
        PRD 3.8: "One compensating effect rides along: when the revoked
        certificate was still `PREISSUANCE` and the `reason_code` is
        `SUPERSEDED`, the issuance charge is credited back — `refunded_at` is
        stamped with the logical clock and the subscriber's
        `outstanding_balance_cents` is reduced by that certificate's
        `charged_amount_cents`."

        Design: Difficulty/compensating_invariant/subscriber_balance_conservation_on_superseded_preissuance_refund
        """
        environment = build_environment(client)
        certificate = issue_certificate(client, environment)
        assert_counters(certificate, charged_amount_cents=8000)
        assert_nulls(certificate, "refunded_at")

        charged = read_subscriber(client, environment.subscriber_id)
        assert_counters(charged, outstanding_balance_cents=8000)
        assert_balance_matches_unrefunded(charged, [certificate])

        request = raise_revocation(
            client,
            certificate,
            REASON_SUPERSEDED,
            evidence_ref="replacement-order-7781",
        )
        executed = get_success_data(
            client.execute_revocation(request["id"], users.REVOCATION_OFFICER)
        )
        assert executed["deadline_breached"] is False

        refunded = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            refunded, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_REVOKED
        )
        assert_instant_equals(
            refunded["refunded_at"], "2026-08-01T00:30:00Z", "refunded_at"
        )
        assert refunded["charged_amount_cents"] == 8000, (
            "the compensation records a refund, it does not rewrite the charge: "
            f"found charged_amount_cents {refunded['charged_amount_cents']}"
        )

        credited = read_subscriber(client, environment.subscriber_id)
        assert_counters(credited, outstanding_balance_cents=0)
        assert_balance_matches_unrefunded(credited, [refunded])
        assert credited["issued_certificate_count"] == 1, (
            "the lifetime tally is never decremented by a refund"
        )

        replay = client.execute_revocation(request["id"], users.REVOCATION_OFFICER)
        validate_error(replay, ERR_REVOCATION_REQUEST_NOT_OPEN)
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            outstanding_balance_cents=0,
        )
        assert_instant_equals(
            read_certificate(client, certificate["id"])["refunded_at"],
            "2026-08-01T00:30:00Z",
            "refunded_at after the replay attempt",
        )

        # The money compensation leaves the CRL ledger alone.
        assert _profile_counters(client, environment.profile_id) == (0, 1, 1)

    def test_d_the_refund_needs_both_preissuance_and_the_superseded_reason(
        self, client
    ):
        """Two revocations move no money; only the third one does.

        PRD 2.9: "Issuance adds a charge to it; the one compensating event in
        the system removes a charge from it."
        PRD 3.8: "Hop one: the certificate moves `REVOCATION_PENDING →
        REVOKED`, `revoked_at` is stamped with the logical clock, and the
        request's `reason_code` is copied onto the certificate's
        `revocation_reason_code`."

        Design: Difficulty/compensating_invariant/subscriber_balance_conservation_on_superseded_preissuance_refund
        """
        environment = build_environment(
            client,
            domains=("d1.example.org", "d2.example.org", "d3.example.org"),
        )
        activated = activate_certificate(
            client,
            issue_certificate(client, environment, domains=("d1.example.org",)),
            required_sct_count=1,
        )
        preissuance = issue_certificate(client, environment, domains=("d2.example.org",))
        superseded = issue_certificate(client, environment, domains=("d3.example.org",))
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            outstanding_balance_cents=24000,
            issued_certificate_count=3,
        )

        # SUPERSEDED, but the certificate is already ISSUED: no refund.
        revoke_certificate(client, activated, REASON_SUPERSEDED)
        after_first = read_certificate(client, activated["id"])
        assert_certificate_dimensions(
            after_first, LIFECYCLE_ISSUED, REVOCATION_STATUS_REVOKED
        )
        assert_nulls(after_first, "refunded_at")
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            outstanding_balance_cents=24000,
        )

        # PREISSUANCE, but the reason is not SUPERSEDED: no refund either.
        revoke_certificate(
            client,
            preissuance,
            REASON_KEY_COMPROMISE,
            evidence_ref="evidence/key-compromise-report-2",
        )
        after_second = read_certificate(client, preissuance["id"])
        assert_certificate_dimensions(
            after_second, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_REVOKED
        )
        assert after_second["revocation_reason_code"] == REASON_KEY_COMPROMISE
        assert_nulls(after_second, "refunded_at")
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            outstanding_balance_cents=24000,
        )

        # Both conditions together, and only then, credit the charge back.
        revoke_certificate(client, superseded, REASON_SUPERSEDED)
        after_third = read_certificate(client, superseded["id"])
        assert_instant_equals(
            after_third["refunded_at"], "2026-08-01T00:30:00Z", "refunded_at"
        )
        settled = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            settled, outstanding_balance_cents=16000, issued_certificate_count=3
        )
        assert_balance_matches_unrefunded(
            settled, [after_first, after_second, after_third]
        )
        assert _profile_counters(client, environment.profile_id) == (0, 3, 3), (
            "all three revocations charge the CRL ledger regardless of the money"
        )


def _validated_proof(client):
    """One ACTIVE DV profile, one subscriber and one proof answered at 00:00."""
    profile = create_profile(client)
    subscriber = create_subscriber(client)
    authorization = create_authorization(
        client, subscriber["id"], profile["id"], "d1.example.org"
    )
    validated = validate_authorization(client, authorization)
    assert validated["state"] == AUTH_VALIDATED
    assert_counters(validated, reuse_count=0)
    return profile, subscriber, authorization


def _clear(client, request_id):
    return client.clear_validation(request_id, users.VALIDATION_OFFICER)


class TestDcvReuseCreditConservation:
    def test_e_invalidation_returns_the_credit_and_re_clearance_takes_it_back(
        self, client
    ):
        """One credit out, one credit back, and never two.

        PRD 3.5: "`consumed_authorization_ids` receives the selected
        authorization identifiers in `requested_domains` order, one per domain,
        and every selected authorization has its `reuse_count` incremented by
        one."
        PRD 3.4: "Every authorization that those rolled-back requests were
        holding — the invalidated one included — has its `reuse_count`
        decremented by one, so the volumetric budget is genuinely returned rather
        than leaked."

        Design: Difficulty/compensating_invariant/dcv_reuse_count_conservation_on_authorization_invalidation
        """
        profile, subscriber, authorization = _validated_proof(client)
        request = submitted_request(
            client, subscriber["id"], profile["id"], ("d1.example.org",)
        )
        cleared = get_success_data(_clear(client, request["id"]))
        assert cleared["state"] == REQUEST_READY_TO_ISSUE
        assert cleared["consumed_authorization_ids"] == [authorization["id"]], (
            "the one selected proof is recorded as consumed, found "
            f"{cleared['consumed_authorization_ids']}"
        )
        assert_counters(read_authorization(client, authorization["id"]), reuse_count=1)
        assert_instant_equals(
            cleared["projected_not_after"], "2026-10-30T00:00:00Z", "projected_not_after"
        )

        reopened = get_success_data(
            client.invalidate_authorization(
                authorization["id"],
                invalidate_payload("the DNS TXT record was removed by the registrant"),
                users.VALIDATION_OFFICER,
            )
        )
        assert reopened["state"] == AUTH_PENDING
        assert_counters(reopened, reuse_count=0, invalidation_count=1, attempt_count=0)
        new_token = reopened["challenge_token"]

        rolled_back = read_request(client, request["id"])
        assert rolled_back["state"] == REQUEST_SUBMITTED, (
            "the consuming request is walked back to SUBMITTED, found "
            f"{rolled_back['state']!r}"
        )
        assert rolled_back["consumed_authorization_ids"] == [], (
            "the rolled-back request releases what it held, found "
            f"{rolled_back['consumed_authorization_ids']}"
        )
        assert_nulls(
            rolled_back,
            "projected_not_before",
            "projected_not_after",
            "projected_charge_cents",
            "validation_cleared_by_user_id",
            "validation_cleared_at",
            "blocked_reason",
        )

        advance_clock(client, "2026-08-02T00:00:00Z")
        revalidated = get_success_data(
            client.validate_authorization(
                authorization["id"],
                validate_payload(new_token),
                users.VALIDATION_OFFICER,
            )
        )
        assert revalidated["state"] == AUTH_VALIDATED
        # Validating does not consume a credit; only clearance does.
        assert_counters(revalidated, reuse_count=0, attempt_count=1)
        assert_instant_equals(
            revalidated["expires_at"], "2026-09-01T00:00:00Z", "expires_at"
        )

        recleared = get_success_data(_clear(client, request["id"]))
        assert recleared["state"] == REQUEST_READY_TO_ISSUE
        assert recleared["consumed_authorization_ids"] == [authorization["id"]]
        settled = read_authorization(client, authorization["id"])
        assert_counters(settled, reuse_count=1, invalidation_count=1)
        assert settled["reuse_count"] == 1, (
            "the credit is restored exactly once, never twice: found "
            f"reuse_count {settled['reuse_count']}"
        )
        # The second clearance re-derives the projection from its own clock.
        assert_instant_equals(
            recleared["projected_not_before"],
            "2026-08-02T00:00:00Z",
            "projected_not_before",
        )
        assert_instant_equals(
            recleared["projected_not_after"],
            "2026-10-31T00:00:00Z",
            "projected_not_after",
        )

    def test_f_two_holders_release_exactly_two_credits(self, client):
        """The whole budget comes back, and the exhausted budget is what blocked.

        PRD 3.5: "If a fresh `VALIDATED` authorization exists but every
        candidate's `reuse_count` has already reached `max_dcv_reuse_count`, the
        failure is `ERR_DCV_REUSE_LIMIT_EXCEEDED`."
        PRD 3.4: "Because a repudiated domain proof cannot underwrite a pending
        issuance, the invalidation cascades: every certificate request whose
        `consumed_authorization_ids` contains this authorization and whose `state`
        is `READY_TO_ISSUE` or `ISSUANCE_BLOCKED` is walked back to `SUBMITTED`
        in ascending `created_at` order, with `validation_cleared_by_user_id`,
        `validation_cleared_at`, `projected_not_before`, `projected_not_after`,
        `projected_charge_cents` and `blocked_reason` all cleared to null and
        `consumed_authorization_ids` emptied to an empty array."

        Design: Difficulty/compensating_invariant/dcv_reuse_count_conservation_on_authorization_invalidation
        """
        profile, subscriber, authorization = _validated_proof(client)
        requests = [
            submitted_request(
                client, subscriber["id"], profile["id"], ("d1.example.org",)
            )
            for _ in range(3)
        ]

        get_success_data(_clear(client, requests[0]["id"]))
        assert_counters(read_authorization(client, authorization["id"]), reuse_count=1)
        get_success_data(_clear(client, requests[1]["id"]))
        assert_counters(read_authorization(client, authorization["id"]), reuse_count=2)

        # The budget of two is spent, so the third clearance has no candidate.
        validate_error(_clear(client, requests[2]["id"]), ERR_DCV_REUSE_LIMIT_EXCEEDED)
        assert read_request(client, requests[2]["id"])["state"] == REQUEST_SUBMITTED
        assert_counters(read_authorization(client, authorization["id"]), reuse_count=2)

        reopened = get_success_data(
            client.invalidate_authorization(
                authorization["id"],
                invalidate_payload("the registrant repudiated the proof"),
                users.VALIDATION_OFFICER,
            )
        )
        # Two holders released two credits, so the budget is whole again.
        assert_counters(reopened, reuse_count=0)
        for held in requests[:2]:
            rolled_back = read_request(client, held["id"])
            assert rolled_back["state"] == REQUEST_SUBMITTED
            assert rolled_back["consumed_authorization_ids"] == []

        revalidated = get_success_data(
            client.validate_authorization(
                authorization["id"],
                validate_payload(reopened["challenge_token"]),
                users.VALIDATION_OFFICER,
            )
        )
        assert_counters(revalidated, reuse_count=0, state=AUTH_VALIDATED)

        # The credit that the limit error refused is now available again.
        third = get_success_data(_clear(client, requests[2]["id"]))
        assert third["state"] == REQUEST_READY_TO_ISSUE
        assert third["consumed_authorization_ids"] == [authorization["id"]]
        assert_counters(read_authorization(client, authorization["id"]), reuse_count=1)
        get_success_data(_clear(client, requests[0]["id"]))
        assert_counters(read_authorization(client, authorization["id"]), reuse_count=2)
