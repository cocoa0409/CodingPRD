"""One request violating two rules at once reports only the higher rule.

Each pair below is provoked together and then unmasked one rule at a time, so
the ordering itself is what is under test rather than a single dominant check.
"""

import pytest

from test_helpers import (
    ERR_CEREMONY_ATTESTATION_EXPIRED,
    ERR_CERTIFICATE_NOT_FOUND,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_INCIDENT_DISCLOSURE_BREACHED,
    ERR_NO_CERTIFICATES_IN_SCOPE,
    ERR_PROFILE_NOT_FOUND,
    ERR_REVOCATION_REQUEST_NOT_FOUND,
    ERR_UNAUTHORIZED,
    COMM_BREACH_ESCALATION,
    INCIDENT_DISCLOSED,
    INCIDENT_PROCEDURAL,
    LIFECYCLE_PREISSUANCE,
    NON_EXISTENT_UUID,
    ORIGIN_MASS_REVOCATION,
    POSTURE_NOMINAL,
    REASON_UNSPECIFIED,
    REQUEST_READY_TO_ISSUE,
    REVOCATION_STATUS_NONE,
    REVOCATION_EXECUTED,
    REVOCATION_STATUS_REVOKED,
    ROOT_PROGRAM_CHROME,
    SUBSCRIBER_ACTIVE,
    advance_clock,
    assert_certificate_dimensions,
    assert_counters,
    assert_instant_equals,
    assert_nulls,
    attested_ceremony,
    build_environment,
    create_profile,
    create_subscriber,
    cleared_request,
    communication_payload,
    disclosure_payload,
    get_success_data,
    incident_payload,
    issue_certificate,
    issue_payload,
    open_incident,
    read_certificate,
    read_incident,
    read_request,
    read_profile,
    read_subscriber,
    subscriber_payload,
    users,
    validate_error,
    validate_paginated,
    validate_success,
)


def _ready_request_with_stale_attestation(client, credit_limit_cents):
    """A request cleared for issuance whose ceremony attestation then lapses."""
    environment = build_environment(
        client,
        subscriber_payload=subscriber_payload(credit_limit_cents=credit_limit_cents),
        attestation_valid_days=1,
    )
    assert_instant_equals(
        environment.ceremony["attestation_expires_at"],
        "2026-08-02T00:30:00Z",
        "attestation_expires_at",
    )
    request = cleared_request(
        client,
        environment.subscriber_id,
        environment.profile_id,
        ("d1.example.org",),
    )
    advance_clock(client, "2026-08-03T00:00:00Z")
    return environment, request


def _fresh_ceremony(client, partition_id):
    """A second ceremony attested after the clock moved past the first expiry."""
    return attested_ceremony(
        client,
        partition_id,
        window_start="2026-08-03T00:00:00Z",
        window_end="2026-08-03T00:30:00Z",
        attestation_valid_days=1,
    )


class TestAttestationExpiryBeatsCreditLimit:
    def test_a_the_lapsed_attestation_masks_the_credit_breach(self, client):
        """Both defects are present; only the temporal one is reported.

        PRD 2.8: "When a single request violates several rules at once, the
        server reports exactly one error: the one belonging to the
        highest-precedence violated rule, and it stops there."
        PRD 3.7: "The named ceremony must be in state `ATTESTED`, or
        `ERR_CEREMONY_NOT_ATTESTED_FOR_ISSUANCE`; and its
        `attestation_expires_at` must be strictly after the logical clock, or
        `ERR_CEREMONY_ATTESTATION_EXPIRED`."
        PRD 3.7: "Last of all comes the fiscal gate: the subscriber's
        `outstanding_balance_cents` plus the settlement total for this issuance
        must be at most `credit_limit_cents`, and exceeding it is
        `ERR_CREDIT_LIMIT_EXCEEDED` with HTTP 402."

        Design: Difficulty/priority_pair_validation_conflict/attestation_expiry_beats_credit_limit_on_issue
        """
        environment, request = _ready_request_with_stale_attestation(
            client, credit_limit_cents=1
        )

        masked = client.issue_certificate(
            request["id"],
            issue_payload(environment.ceremony_id),
            users.ISSUANCE_OPERATOR_9,
        )
        validate_error(masked, ERR_CEREMONY_ATTESTATION_EXPIRED, 409)

        # Repair only the temporal defect: the fiscal one is still there.
        fresh = _fresh_ceremony(client, environment.partition_id)
        assert_instant_equals(
            fresh["attestation_expires_at"],
            "2026-08-04T00:30:00Z",
            "attestation_expires_at",
        )
        unmasked = client.issue_certificate(
            request["id"], issue_payload(fresh["id"]), users.ISSUANCE_OPERATOR_9
        )
        validate_error(unmasked, ERR_CREDIT_LIMIT_EXCEEDED, 402)

        settled = read_request(client, request["id"])
        assert settled["state"] == REQUEST_READY_TO_ISSUE, (
            f"a rejected issuance leaves the request ready, found {settled['state']!r}"
        )
        assert_nulls(settled, "issued_certificate_id")
        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber, outstanding_balance_cents=0, issued_certificate_count=0
        )
        rows, meta = validate_paginated(
            client.list_certificates(
                users.ISSUANCE_OPERATOR, {"request_id": request["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"no certificate may exist for a twice-rejected request, found {rows}"
        )

    def test_b_each_rule_fires_alone_when_it_is_the_only_defect(self, client):
        """With ample credit the lapse still refuses; repairing it then issues.

        PRD 3.7: "and its `attestation_expires_at` must be strictly after the
        logical clock, or `ERR_CEREMONY_ATTESTATION_EXPIRED`."
        PRD 3.7: "`charged_amount_cents` is the settlement total, computed at
        issuance by exactly the same six-step tiered calculation described in
        §3.5 that produced `projected_charge_cents`."

        Design: Difficulty/priority_pair_validation_conflict/attestation_expiry_beats_credit_limit_on_issue
        """
        environment, request = _ready_request_with_stale_attestation(
            client, credit_limit_cents=1_000_000
        )

        refused = client.issue_certificate(
            request["id"],
            issue_payload(environment.ceremony_id),
            users.ISSUANCE_OPERATOR_9,
        )
        validate_error(refused, ERR_CEREMONY_ATTESTATION_EXPIRED, 409)

        fresh = _fresh_ceremony(client, environment.partition_id)
        certificate = get_success_data(
            client.issue_certificate(
                request["id"], issue_payload(fresh["id"]), users.ISSUANCE_OPERATOR_9
            ),
            201,
        )
        assert_certificate_dimensions(
            certificate, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_NONE
        )
        assert_counters(certificate, charged_amount_cents=8000)
        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber,
            outstanding_balance_cents=8000,
            issued_certificate_count=1,
            account_status=SUBSCRIBER_ACTIVE,
        )


class TestDisclosureBreachBeatsEmptyScope:
    def test_a_the_breach_gate_masks_the_provably_empty_pool(self, client):
        """A late incident with nothing in scope reports the breach, not the pool.

        PRD 3.9: "before any mass revocation may run on an incident whose
        `disclosure_breached` is true, a communication with `kind`
        `BREACH_ESCALATION` must already exist for it, or the batch is refused
        with `ERR_INCIDENT_DISCLOSURE_BREACHED`."
        PRD 3.9: "An empty pool is refused with `ERR_NO_CERTIFICATES_IN_SCOPE`."

        Design: Difficulty/priority_pair_validation_conflict/disclosure_breach_beats_empty_mass_revocation_scope
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        incident = open_incident(
            client,
            profile["id"],
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-07-01T00:00:00Z",
            scope_issued_to="2026-07-31T00:00:00Z",
            subscriber_id=subscriber["id"],
        )
        assert_instant_equals(
            incident["disclosure_due_at"], "2026-08-02T00:00:00Z", "disclosure_due_at"
        )
        assert incident["disclosure_breached"] is False

        advance_clock(client, "2026-08-02T00:00:01Z")
        breached = read_incident(client, incident["id"])
        assert breached["disclosure_breached"] is True, (
            "one second past the deadline is strictly after it, so sweep three fires"
        )

        get_success_data(
            client.disclose_incident(
                incident["id"],
                disclosure_payload(
                    ROOT_PROGRAM_CHROME,
                    "late disclosure of a procedural misissuance",
                ),
                users.COMPLIANCE_AUDITOR,
            )
        )

        masked = client.mass_revoke(incident["id"], users.REVOCATION_OFFICER)
        validate_error(masked, ERR_INCIDENT_DISCLOSURE_BREACHED, 409)

        escalation = get_success_data(
            client.create_incident_communication(
                incident["id"],
                communication_payload(
                    ROOT_PROGRAM_CHROME,
                    "escalation: the 24 hour disclosure deadline was missed by one second",
                ),
                users.COMPLIANCE_AUDITOR,
            ),
            201,
        )
        assert escalation["kind"] == COMM_BREACH_ESCALATION, (
            f"kind is {escalation['kind']!r}, expected {COMM_BREACH_ESCALATION!r}"
        )
        assert escalation["within_deadline"] is False, (
            "a breach escalation is late by definition"
        )
        assert escalation["incident_id"] == incident["id"]
        assert_nulls(escalation, "audit_id")

        unmasked = client.mass_revoke(incident["id"], users.REVOCATION_OFFICER_2)
        validate_error(unmasked, ERR_NO_CERTIFICATES_IN_SCOPE, 422)

        settled = read_incident(client, incident["id"])
        assert settled["state"] == INCIDENT_DISCLOSED, (
            f"two refused batches leave the incident DISCLOSED, found {settled['state']!r}"
        )
        assert_counters(
            settled, revoked_certificate_count=0, penalty_total_cents=0
        )

    def test_b_the_breach_gate_fires_even_with_certificates_in_scope(self, client):
        """The gate is about the missed deadline, never about the pool size.

        PRD 3.9: "A `REVOCATION_OFFICER` runs a batch against an incident whose
        `state` is `DISCLOSED` or `MASS_REVOCATION_IN_PROGRESS`, after the
        breach-escalation gate above."
        PRD 3.9: "Each certificate in the batch is revoked in a single step that
        skips the pending state entirely: `revocation_status` moves `NONE →
        REVOKED` directly, `revoked_at` is stamped with the logical clock, and a
        revocation request is created already in `state` `EXECUTED` with `origin`
        `MASS_REVOCATION`, its `incident_id` pointing at the incident"

        Design: Difficulty/priority_pair_validation_conflict/disclosure_breach_beats_empty_mass_revocation_scope
        """
        environment = build_environment(client)
        certificate = issue_certificate(client, environment)
        incident = open_incident(
            client,
            environment.profile_id,
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-08-01T00:00:00Z",
            scope_issued_to="2026-08-02T00:00:00Z",
            subscriber_id=environment.subscriber_id,
        )
        assert_instant_equals(
            incident["disclosure_due_at"], "2026-08-02T00:30:00Z", "disclosure_due_at"
        )

        advance_clock(client, "2026-08-02T00:30:01Z")
        assert read_incident(client, incident["id"])["disclosure_breached"] is True
        get_success_data(
            client.disclose_incident(
                incident["id"],
                disclosure_payload(ROOT_PROGRAM_CHROME),
                users.COMPLIANCE_AUDITOR,
            )
        )

        refused = client.mass_revoke(incident["id"], users.REVOCATION_OFFICER)
        validate_error(refused, ERR_INCIDENT_DISCLOSURE_BREACHED, 409)
        assert_certificate_dimensions(
            read_certificate(client, certificate["id"]),
            LIFECYCLE_PREISSUANCE,
            REVOCATION_STATUS_NONE,
        )

        get_success_data(
            client.create_incident_communication(
                incident["id"],
                communication_payload(ROOT_PROGRAM_CHROME),
                users.COMPLIANCE_AUDITOR,
            ),
            201,
        )
        get_success_data(client.mass_revoke(incident["id"], users.REVOCATION_OFFICER))

        revoked = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            revoked, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_REVOKED
        )
        assert revoked["revocation_reason_code"] == REASON_UNSPECIFIED, (
            "a PROCEDURAL incident writes UNSPECIFIED onto each certificate"
        )
        assert_instant_equals(
            revoked["revoked_at"], "2026-08-02T00:30:01Z", "revoked_at"
        )

        rows, meta = validate_paginated(
            client.list_revocations(
                users.REVOCATION_OFFICER, {"incident_id": incident["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the batch raises one request per certificate, found {meta['total_count']}"
        )
        assert rows[0]["origin"] == ORIGIN_MASS_REVOCATION
        assert rows[0]["state"] == REVOCATION_EXECUTED, (
            "a batched revocation is born already executed"
        )
        subscriber = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            subscriber, revocation_pending_count=0, account_status=SUBSCRIBER_ACTIVE
        )
        profile = read_profile(client, environment.profile_id)
        assert profile["status_service_posture"] == POSTURE_NOMINAL


class TestUnauthorizedRoleBeatsNotFound:
    def test_a_the_same_missing_certificate_answers_403_then_404(self, client):
        """The role gate runs before any row is looked up.

        PRD 2.1: "Header enforcement is unconditional and precedes everything
        else."
        PRD 2.1: "a syntactically valid role that is simply not permitted on the
        endpoint being called is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD 2.8: "1. **Authentication and authorization.**
        `ERR_MISSING_USER_HEADER`, then `ERR_MISSING_ROLE_HEADER`, then
        `ERR_UNKNOWN_ROLE`, then `ERR_UNAUTHORIZED`, in that order."

        Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_beats_certificate_not_found
        """
        subscriber = create_subscriber(client)

        forbidden = client.activate_certificate(
            NON_EXISTENT_UUID, users.VALIDATION_OFFICER
        )
        validate_error(forbidden, ERR_UNAUTHORIZED, 403)

        missing = client.activate_certificate(
            NON_EXISTENT_UUID, users.ISSUANCE_OPERATOR
        )
        validate_error(missing, ERR_CERTIFICATE_NOT_FOUND, 404)

        untouched = read_subscriber(client, subscriber["id"])
        assert untouched["version"] == subscriber["version"], (
            "a rejected call must not bump any row's version"
        )

    @pytest.mark.parametrize(
        "endpoint,forbidden_role,permitted_role,not_found_error",
        [
            (
                "activate_certificate",
                users.REVOCATION_OFFICER,
                users.ISSUANCE_OPERATOR,
                ERR_CERTIFICATE_NOT_FOUND,
            ),
            (
                "activate_profile",
                users.ISSUANCE_OPERATOR,
                users.POLICY_ADMIN,
                ERR_PROFILE_NOT_FOUND,
            ),
            (
                "execute_revocation",
                users.COMPLIANCE_AUDITOR,
                users.REVOCATION_OFFICER,
                ERR_REVOCATION_REQUEST_NOT_FOUND,
            ),
        ],
    )
    def test_b_the_ordering_holds_on_every_role_guarded_endpoint(
        self, client, endpoint, forbidden_role, permitted_role, not_found_error
    ):
        """Precedence is global, so the same pattern repeats endpoint by endpoint.

        PRD 2.8: "Precedence is global across the whole API, not per endpoint,
        and it runs in the following bands from highest to lowest."
        PRD 2.8: "3. **Existence, resolved left to right.** Path identifiers are
        resolved before body identifiers, and within each group in the order they
        appear."

        Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_beats_certificate_not_found
        """
        call = getattr(client, endpoint)
        validate_error(call(NON_EXISTENT_UUID, forbidden_role), ERR_UNAUTHORIZED, 403)
        validate_error(call(NON_EXISTENT_UUID, permitted_role), not_found_error, 404)
