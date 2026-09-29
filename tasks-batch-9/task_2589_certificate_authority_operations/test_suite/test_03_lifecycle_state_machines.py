"""Two state machines that are not simple forward marches.

A certificate carries two dimensions that advance on unrelated triggers, and a
domain authorization revisits its own states in a cycle whose outcome depends on
how many attempts have already been spent.
"""

from test_helpers import (
    AUTH_EXHAUSTED,
    AUTH_FAILED,
    AUTH_PENDING,
    AUTH_VALIDATED,
    ERR_AUTHORIZATION_NOT_VALIDATABLE,
    LIFECYCLE_EXPIRED,
    LIFECYCLE_ISSUED,
    LIFECYCLE_PREISSUANCE,
    ORIGIN_SUBSCRIBER,
    POSTURE_NOMINAL,
    REASON_AFFILIATION_CHANGED,
    REASON_KEY_COMPROMISE,
    REVOCATION_REQUESTED,
    REVOCATION_STATUS_NONE,
    REVOCATION_STATUS_PENDING,
    REVOCATION_STATUS_REVOKED,
    SUBSCRIBER_ACTIVE,
    activate_certificate,
    advance_clock,
    assert_certificate_dimensions,
    assert_counters,
    assert_instant_equals,
    assert_nulls,
    create_authorization,
    create_profile,
    create_subscriber,
    get_success_data,
    invalidate_payload,
    issue_certificate,
    raise_revocation,
    read_authorization,
    read_certificate,
    read_profile,
    read_subscriber,
    users,
    validate_error,
    validate_payload,
)


def _pending_authorization(client):
    """An ACTIVE DV profile, an ACTIVE subscriber and one unproven domain."""
    profile = create_profile(client)
    subscriber = create_subscriber(client)
    authorization = create_authorization(
        client, subscriber["id"], profile["id"], "d1.example.org"
    )
    return profile, subscriber, authorization


def _attempt(client, authorization_id, token):
    """One validation attempt, which the PRD answers 200 either way."""
    return get_success_data(
        client.validate_authorization(
            authorization_id, validate_payload(token), users.VALIDATION_OFFICER
        )
    )


class TestCertificateParallelDimensions:
    def test_a_preissuance_revocation_survives_the_expiry_sweep(
        self, client, dv_environment
    ):
        """A never-activated certificate is revoked and then ages out anyway.

        PRD 3.7: "The two status dimensions on a certificate evolve
        independently for the rest of its life."
        PRD 2.6: "This sweep is entirely independent of the certificate's
        `revocation_status`; an already `REVOKED` certificate still ages into
        `EXPIRED`, and a certificate that was never activated ages out of
        `PREISSUANCE` directly."

        Design: Difficulty/non_linear_state_machine/certificate_parallel_lifecycle_and_revocation_dimensions
        """
        environment = dv_environment
        certificate = issue_certificate(client, environment)
        assert_certificate_dimensions(
            certificate, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_NONE
        )
        assert_instant_equals(
            certificate["not_before"], "2026-08-01T00:30:00Z", "not_before"
        )
        assert_instant_equals(
            certificate["not_after"], "2026-08-31T00:30:00Z", "not_after"
        )
        assert_nulls(certificate, "activated_at", "revoked_at", "revocation_reason_code")

        request = raise_revocation(
            client,
            certificate,
            REASON_AFFILIATION_CHANGED,
            evidence_ref="registrant-letter-4412",
        )
        assert request["origin"] == ORIGIN_SUBSCRIBER, (
            "a revocation raised without an incident_id has SUBSCRIBER origin"
        )
        assert request["state"] == REVOCATION_REQUESTED, (
            f"a fresh revocation request is REQUESTED, found {request['state']!r}"
        )
        assert_instant_equals(
            request["deadline_at"], "2026-08-06T00:30:00Z", "deadline_at"
        )
        pending = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            pending, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_PENDING
        )

        get_success_data(
            client.execute_revocation(request["id"], users.REVOCATION_OFFICER)
        )
        revoked = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            revoked, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_REVOKED
        )
        assert revoked["revocation_reason_code"] == REASON_AFFILIATION_CHANGED, (
            "the request's reason_code is copied onto the certificate"
        )
        assert_nulls(revoked, "refunded_at")
        assert_instant_equals(
            revoked["revoked_at"], "2026-08-01T00:30:00Z", "revoked_at"
        )
        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber, revocation_pending_count=0, account_status=SUBSCRIBER_ACTIVE
        )

        advance_clock(client, "2026-09-01T00:00:00Z")
        aged = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            aged, LIFECYCLE_EXPIRED, REVOCATION_STATUS_REVOKED
        )
        assert_nulls(aged, "activated_at")
        profile = read_profile(client, environment.profile_id)
        assert profile["status_service_posture"] == POSTURE_NOMINAL, (
            "one unpublished entry is far below a crl_trigger_threshold of 100"
        )

    def test_b_activation_and_revocation_each_move_only_their_own_dimension(
        self, client, dv_environment
    ):
        """Activation touches the lifecycle only; revocation the other only.

        PRD 3.7: "Activation is the final step: an `ISSUANCE_OPERATOR` moves the
        certificate `PREISSUANCE → ISSUED`, which is what makes it publicly
        usable."
        PRD 3.7: "Any combination is reachable, including a pre-issuance
        revocation sitting at `PREISSUANCE` with `REVOKED`, and a certificate
        revoked before it aged out sitting at `EXPIRED` with `REVOKED`."

        Design: Difficulty/non_linear_state_machine/certificate_parallel_lifecycle_and_revocation_dimensions
        """
        environment = dv_environment
        certificate = issue_certificate(client, environment)
        activated = activate_certificate(client, certificate, required_sct_count=1)
        assert_certificate_dimensions(
            activated, LIFECYCLE_ISSUED, REVOCATION_STATUS_NONE
        )
        assert_counters(activated, sct_count=1)
        assert_instant_equals(
            activated["activated_at"], "2026-08-01T00:30:00Z", "activated_at"
        )

        request = raise_revocation(
            client,
            activated,
            REASON_KEY_COMPROMISE,
            evidence_ref="evidence/key-compromise-report-1",
        )
        assert_instant_equals(
            request["deadline_at"], "2026-08-02T00:30:00Z", "deadline_at"
        )
        pending = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            pending, LIFECYCLE_ISSUED, REVOCATION_STATUS_PENDING
        )

        executed = get_success_data(
            client.execute_revocation(request["id"], users.REVOCATION_OFFICER)
        )
        assert executed["deadline_breached"] is False, (
            "the execution happened well before deadline_at"
        )
        revoked = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            revoked, LIFECYCLE_ISSUED, REVOCATION_STATUS_REVOKED
        )
        assert revoked["revocation_reason_code"] == REASON_KEY_COMPROMISE

        advance_clock(client, "2026-09-01T00:00:00Z")
        aged = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            aged, LIFECYCLE_EXPIRED, REVOCATION_STATUS_REVOKED
        )
        assert_instant_equals(
            aged["activated_at"], "2026-08-01T00:30:00Z", "activated_at"
        )


class TestAuthorizationRevalidationCycle:
    def test_a_invalidation_reopens_the_proof_and_a_later_success_re_dates_it(
        self, client
    ):
        """VALIDATED to PENDING to FAILED to VALIDATED on one authorization.

        PRD 3.4: "Invalidation returns it `VALIDATED → PENDING` and reopens it
        for a fresh proof: `invalidated_at` is stamped with the logical clock,
        `invalidation_count` increments, `attempt_count` resets to 0,
        `validated_at` and `expires_at` are cleared to null, and a new
        `challenge_token` is minted."
        PRD 3.4: "Success stamps `validated_at` with the logical clock and sets
        `expires_at` to `validated_at` plus the profile's `dcv_reuse_days` in
        days."
        PRD 3.4: "A success does **not** reset `attempt_count`."

        Design: Difficulty/non_linear_state_machine/domain_authorization_validated_pending_failed_revalidation_cycle
        """
        _profile, _subscriber, authorization = _pending_authorization(client)
        first_token = authorization["challenge_token"]
        versions = [authorization["version"]]

        first = _attempt(client, authorization["id"], first_token)
        assert first["state"] == AUTH_VALIDATED, (
            f"the minted token must validate, found state {first['state']!r}"
        )
        assert_counters(first, attempt_count=1, invalidation_count=0, reuse_count=0)
        assert_instant_equals(
            first["expires_at"], "2026-08-31T00:00:00Z", "expires_at"
        )
        versions.append(first["version"])

        reopened = get_success_data(
            client.invalidate_authorization(
                authorization["id"],
                invalidate_payload("registrant repudiated the DNS TXT record"),
                users.VALIDATION_OFFICER,
            )
        )
        assert reopened["state"] == AUTH_PENDING, (
            f"invalidation returns the proof to PENDING, found {reopened['state']!r}"
        )
        assert_counters(reopened, attempt_count=0, invalidation_count=1, reuse_count=0)
        assert_nulls(reopened, "validated_at", "expires_at")
        assert_instant_equals(
            reopened["invalidated_at"], "2026-08-01T00:00:00Z", "invalidated_at"
        )
        second_token = reopened["challenge_token"]
        assert second_token != first_token, (
            "invalidation mints a new challenge_token, it must not repeat the old one"
        )
        versions.append(reopened["version"])

        advance_clock(client, "2026-08-03T00:00:00Z")
        missed = _attempt(client, authorization["id"], "definitely-not-the-minted-token")
        assert missed["state"] == AUTH_FAILED, (
            f"a first miss lands in FAILED, found {missed['state']!r}"
        )
        assert_counters(missed, attempt_count=1, invalidation_count=1, reuse_count=0)
        assert_nulls(missed, "validated_at", "expires_at")
        versions.append(missed["version"])

        revalidated = _attempt(client, authorization["id"], second_token)
        assert revalidated["state"] == AUTH_VALIDATED, (
            "a correct token validates from FAILED as readily as from PENDING, "
            f"found {revalidated['state']!r}"
        )
        assert_counters(
            revalidated, attempt_count=2, invalidation_count=1, reuse_count=0
        )
        assert_instant_equals(
            revalidated["validated_at"], "2026-08-03T00:00:00Z", "validated_at"
        )
        assert_instant_equals(
            revalidated["expires_at"], "2026-09-02T00:00:00Z", "expires_at"
        )
        versions.append(revalidated["version"])

        assert versions == sorted(set(versions)), (
            f"every write must increment version, saw the sequence {versions}"
        )

    def test_b_the_third_miss_exhausts_the_proof_for_good(self, client):
        """Three misses reach EXHAUSTED and the right token no longer helps.

        PRD 3.4: "If the incremented `attempt_count` reaches exactly 3, the
        authorization moves `FAILED → EXHAUSTED`, which is terminal: an
        exhausted authorization can never be validated, and the operator must
        open a fresh one."
        PRD 3.4: "the authorization must be in `PENDING` or `FAILED` (anything
        else, including an already `VALIDATED`, `EXHAUSTED` or `EXPIRED`
        authorization, is refused with `ERR_AUTHORIZATION_NOT_VALIDATABLE`)"

        Design: Difficulty/non_linear_state_machine/domain_authorization_validated_pending_failed_revalidation_cycle
        """
        _profile, _subscriber, authorization = _pending_authorization(client)
        good_token = authorization["challenge_token"]

        first = _attempt(client, authorization["id"], "wrong-token-1")
        assert first["state"] == AUTH_FAILED, "PENDING to FAILED on the first miss"
        assert_counters(first, attempt_count=1)

        second = _attempt(client, authorization["id"], "wrong-token-2")
        assert second["state"] == AUTH_FAILED, "FAILED to FAILED on the second miss"
        assert_counters(second, attempt_count=2)

        third = _attempt(client, authorization["id"], "wrong-token-3")
        assert third["state"] == AUTH_EXHAUSTED, (
            f"the third miss exhausts the proof, found {third['state']!r}"
        )
        assert_counters(third, attempt_count=3, invalidation_count=0, reuse_count=0)
        assert_nulls(third, "validated_at", "expires_at")

        response = client.validate_authorization(
            authorization["id"],
            validate_payload(good_token),
            users.VALIDATION_OFFICER,
        )
        validate_error(response, ERR_AUTHORIZATION_NOT_VALIDATABLE)
        settled = read_authorization(client, authorization["id"])
        assert settled["state"] == AUTH_EXHAUSTED, "EXHAUSTED is terminal"
        assert_counters(settled, attempt_count=3)
