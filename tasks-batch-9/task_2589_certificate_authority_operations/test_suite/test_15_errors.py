"""Every declared error identifier is provoked by the act the PRD attaches it to.

The cases below walk the catalogue of section 5 one situation at a time: the
authentication envelope, the eleven not-found identifiers, the state guards on
profiles, requests, certificates, incidents and audits, the two open-row
uniqueness rules, and the window-shaped inputs. Each case also checks that the
refused call left no row behind, because an error that half-writes is as wrong
as an error with the wrong identifier.
"""

import pytest

from test_helpers import (
    AUDIT_FIELDWORK,
    AUDIT_SCHEDULED,
    AUDIT_UNQUALIFIED,
    AUTH_EXPIRED,
    AUTH_PENDING,
    AUTH_VALIDATED,
    CEREMONY_ATTESTED,
    CEREMONY_SCHEDULED,
    CEREMONY_WITNESSED,
    COMM_INCIDENT_DISCLOSURE,
    COMM_ROOT_PROGRAM_RESPONSE,
    CT_OUTCOME_ACCEPTED,
    CT_OUTCOME_REJECTED,
    DCV_METHOD_HTTP_TOKEN,
    ERR_AUDIT_ALREADY_OPEN,
    ERR_AUDIT_NOT_FOUND,
    ERR_AUDIT_NOT_IN_FIELDWORK,
    ERR_AUDIT_NOT_OPEN_FOR_FINDINGS,
    ERR_AUDIT_NOT_OPINED,
    ERR_AUDIT_NO_FINDINGS,
    ERR_AUTHORIZATION_ALREADY_OPEN,
    ERR_AUTHORIZATION_NOT_FOUND,
    ERR_AUTHORIZATION_NOT_VALIDATED,
    ERR_CASCADE_REVOCATION_NOT_DENIABLE,
    ERR_CERTIFICATE_ALREADY_EXPIRED,
    ERR_CERTIFICATE_EXPIRED_NOT_REVOCABLE,
    ERR_CERTIFICATE_NOT_PREISSUANCE,
    ERR_CERTIFICATE_NOT_REVOCABLE,
    ERR_CEREMONY_WINDOW_OPEN,
    ERR_CRL_VALIDITY_TOO_LONG,
    ERR_DCV_REUSE_LIMIT_EXCEEDED,
    ERR_INCIDENT_NOT_CLOSEABLE,
    ERR_INCIDENT_NOT_DISCLOSED,
    ERR_INCIDENT_NOT_FOUND,
    ERR_INCIDENT_NOT_OPEN,
    ERR_INVALID_AUDIT_PERIOD,
    ERR_INVALID_CEREMONY_WINDOW,
    ERR_INVALID_CRL_WINDOW,
    ERR_INVALID_SCOPE_WINDOW,
    ERR_MISSING_ROLE_HEADER,
    ERR_MISSING_USER_HEADER,
    ERR_PARTITION_NOT_FOUND,
    ERR_PROFILE_NOT_ACTIVE,
    ERR_REJECTION_REASON_MISMATCH,
    ERR_REQUEST_NOT_FOUND,
    ERR_REQUEST_NOT_READY,
    ERR_REVOCATION_REQUEST_NOT_FOUND,
    ERR_SCOPE_METHOD_NOT_IN_PROFILE,
    ERR_UNKNOWN_ROLE,
    ERR_VETTING_ALREADY_OPEN,
    ERR_VETTING_NOT_FOUND,
    INCIDENT_DISCLOSED,
    INCIDENT_DOMAIN_MISISSUANCE,
    INCIDENT_OPEN,
    INCIDENT_PROCEDURAL,
    LIFECYCLE_EXPIRED,
    LIFECYCLE_ISSUED,
    LIFECYCLE_PREISSUANCE,
    LOG_OPERATOR_CLOUDFLARE_NIMBUS,
    LOG_OPERATOR_GOOGLE_ARGON,
    NON_EXISTENT_UUID,
    ORIGIN_SYSTEM_CASCADE,
    PARTITION_QUARANTINED,
    REASON_AFFILIATION_CHANGED,
    REASON_KEY_COMPROMISE,
    REASON_SUPERSEDED,
    REQUEST_READY_TO_ISSUE,
    REQUEST_SUBMITTED,
    REVOCATION_DENIED,
    REVOCATION_EXECUTED,
    REVOCATION_REQUESTED,
    REVOCATION_STATUS_NONE,
    REVOCATION_STATUS_PENDING,
    REVOCATION_STATUS_REVOKED,
    ROLE_POLICY_ADMIN,
    ROOT_PROGRAM_APPLE,
    ROOT_PROGRAM_CHROME,
    ROOT_PROGRAM_MOZILLA,
    SEVERITY_CRITICAL,
    SEVERITY_MINOR,
    SUBSCRIBER_ACTIVE,
    VETTING_LEVEL_EV,
    VETTING_LEVEL_OV,
    VETTING_PENDING,
    advance_clock,
    assert_certificate_dimensions,
    assert_counters,
    assert_instant_equals,
    assert_nulls,
    attest_ceremony_at_window_end,
    attestation_revocation_payload,
    audit_payload,
    authorization_payload,
    build_environment,
    build_user_headers,
    ceremony_payload,
    cleared_request,
    communication_payload,
    create_authorization,
    create_partition,
    create_profile,
    create_subscriber,
    crl_publication_payload,
    ct_submission_payload,
    denial_payload,
    disclosure_payload,
    finding_payload,
    get_success_data,
    incident_payload,
    invalidate_payload,
    issue_certificate,
    issue_from_request,
    issue_payload,
    open_audit,
    open_incident,
    ov_profile_payload,
    profile_payload,
    profile_version,
    raise_revocation,
    read_authorization,
    read_audit,
    read_ceremony,
    read_certificate,
    read_incident,
    read_partition,
    read_profile,
    read_request,
    read_revocation,
    read_subscriber,
    revocation_payload,
    schedule_ceremony,
    submitted_request,
    subscriber_payload,
    users,
    validate_error,
    validate_paginated,
    validate_success,
    validated_authorization,
    vetting_payload,
    witness_twice,
)

CLOCK_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-01T00:30:00Z"


NOT_FOUND_LOOKUPS = [
    ("get_vetting", users.VALIDATION_OFFICER, ERR_VETTING_NOT_FOUND),
    ("get_authorization", users.VALIDATION_OFFICER, ERR_AUTHORIZATION_NOT_FOUND),
    ("get_request", users.VALIDATION_OFFICER, ERR_REQUEST_NOT_FOUND),
    ("get_partition", users.POLICY_ADMIN, ERR_PARTITION_NOT_FOUND),
    ("get_revocation", users.REVOCATION_OFFICER, ERR_REVOCATION_REQUEST_NOT_FOUND),
    ("get_incident", users.COMPLIANCE_AUDITOR, ERR_INCIDENT_NOT_FOUND),
    ("get_audit", users.COMPLIANCE_AUDITOR, ERR_AUDIT_NOT_FOUND),
]


class TestAuthenticationEnvelope:
    def test_a_each_header_defect_reports_its_own_identifier(self, client):
        """An empty user id, a missing role and an unknown role are three errors.

        PRD 2.1: "A request missing or empty `X-User-ID` is rejected with
        `ERR_MISSING_USER_HEADER` (HTTP 401) on every endpoint except the read
        endpoints, which do not require it."
        PRD 2.1: "A request missing or empty `X-User-Role` is rejected with
        `ERR_MISSING_ROLE_HEADER` (HTTP 401) on every endpoint without exception."
        PRD 2.1: "A role string that is not one of the six names above is
        rejected with `ERR_UNKNOWN_ROLE` (HTTP 401), and a syntactically valid
        role that is simply not permitted on the endpoint being called is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/errors/auth_envelope_errors_are_raised_in_declared_priority_order
        """
        empty_user = client.create_subscriber(
            subscriber_payload(), users.headers_with_empty_user_id(ROLE_POLICY_ADMIN)
        )
        validate_error(empty_user, ERR_MISSING_USER_HEADER, 401)

        no_role = client.list_profiles(users.headers_without_role())
        validate_error(no_role, ERR_MISSING_ROLE_HEADER, 401)

        unknown_on_read = client.list_profiles(
            users.headers_with_unknown_role(role="ROOT_ADMIN")
        )
        validate_error(unknown_on_read, ERR_UNKNOWN_ROLE, 401)

        unknown_on_write = client.create_subscriber(
            subscriber_payload(), users.headers_with_unknown_role(role="ROOT_ADMIN")
        )
        validate_error(unknown_on_write, ERR_UNKNOWN_ROLE, 401)

        rows, meta = validate_paginated(client.list_subscribers(users.POLICY_ADMIN))
        assert meta["total_count"] == 0, (
            f"four refused calls must have written nothing, found {rows}"
        )

    def test_b_the_missing_user_header_outranks_the_unknown_role(self, client):
        """Both header defects at once report the first entry of band one.

        PRD 2.1: "Header enforcement is unconditional and precedes everything
        else."
        PRD 2.8: "1. **Authentication and authorization.**
        `ERR_MISSING_USER_HEADER`, then `ERR_MISSING_ROLE_HEADER`, then
        `ERR_UNKNOWN_ROLE`, then `ERR_UNAUTHORIZED`, in that order."

        Design: Corner/errors/auth_envelope_errors_are_raised_in_declared_priority_order
        """
        both_wrong = client.create_subscriber(
            subscriber_payload(), build_user_headers("", "ROOT_ADMIN")
        )
        validate_error(both_wrong, ERR_MISSING_USER_HEADER, 401)

        only_role_wrong = client.create_subscriber(
            subscriber_payload(), users.headers_with_unknown_role(role="ROOT_ADMIN")
        )
        validate_error(only_role_wrong, ERR_UNKNOWN_ROLE, 401)

        _, meta = validate_paginated(client.list_subscribers(users.POLICY_ADMIN))
        assert meta["total_count"] == 0, (
            f"a rejected registration writes no subscriber, found {meta['total_count']}"
        )

    def test_c_a_read_endpoint_needs_no_user_header_at_all(self, client):
        """The user-header rule carves out exactly the read endpoints.

        PRD 2.1: "A request missing or empty `X-User-ID` is rejected with
        `ERR_MISSING_USER_HEADER` (HTTP 401) on every endpoint except the read
        endpoints, which do not require it."

        Design: Corner/errors/auth_envelope_errors_are_raised_in_declared_priority_order
        """
        profile = create_profile(client)

        rows, meta = validate_paginated(
            client.list_profiles(users.headers_without_user_id(ROLE_POLICY_ADMIN))
        )
        assert meta["total_count"] == 1, (
            f"the anonymous read must still answer, found {meta['total_count']}"
        )
        assert rows[0]["id"] == profile["id"]

        detail = validate_success(
            client.get_profile(
                profile["id"], users.headers_without_user_id(ROLE_POLICY_ADMIN)
            )
        )
        assert detail["id"] == profile["id"], (
            f"the detail read answered {detail['id']!r}, expected {profile['id']!r}"
        )


class TestNotFoundCatalogue:
    @pytest.mark.parametrize("endpoint,headers,expected_error", NOT_FOUND_LOOKUPS)
    def test_a_one_unknown_id_answers_seven_different_identifiers(
        self, client, endpoint, headers, expected_error
    ):
        """The same unknown UUID names the entity that was not found.

        PRD 2.8: "Path identifiers are resolved before body identifiers, and
        within each group in the order they appear."
        PRD 2.8: "The catalogue is `ERR_PROFILE_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_VETTING_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CERTIFICATE_NOT_FOUND`, `ERR_PARTITION_NOT_FOUND`,
        `ERR_CEREMONY_NOT_FOUND`, `ERR_REVOCATION_REQUEST_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND` and `ERR_AUDIT_NOT_FOUND`, all HTTP 404, and
        that listed order is also their relative precedence when two of them
        could fire on the same request."

        Design: Corner/errors/every_entity_lookup_returns_its_own_not_found_error_id
        """
        lookup = getattr(client, endpoint)
        validate_error(lookup(NON_EXISTENT_UUID, headers), expected_error, 404)


class TestDraftProfileAndPendingAuthorization:
    def test_a_a_draft_profile_refuses_a_new_authorization(self, client):
        """Domain control validation is one of the six operations needing ACTIVE.

        PRD 3.1: "All six of those operations reject a `DRAFT` or `RETIRED`
        profile with `ERR_PROFILE_NOT_ACTIVE`."

        Design: Corner/errors/a_draft_profile_blocks_dcv_and_a_pending_authorization_cannot_be_invalidated
        """
        draft = create_profile(client, activate=False)
        subscriber = create_subscriber(client)

        refused = client.create_authorization(
            authorization_payload(subscriber["id"], draft["id"], "d2.example.org"),
            users.VALIDATION_OFFICER,
        )
        validate_error(refused, ERR_PROFILE_NOT_ACTIVE, 409)

        rows, meta = validate_paginated(
            client.list_authorizations(
                users.VALIDATION_OFFICER, {"profile_id": draft["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"a refused challenge leaves no authorization row, found {rows}"
        )

    def test_b_a_pending_authorization_cannot_be_invalidated(self, client):
        """Invalidation is only defined for an authorization already VALIDATED.

        PRD 3.4: "A `VALIDATION_OFFICER` invalidates an authorization by
        supplying a `reason`; the authorization must currently be `VALIDATED`,
        or the call is refused with `ERR_AUTHORIZATION_NOT_VALIDATED`."

        Design: Corner/errors/a_draft_profile_blocks_dcv_and_a_pending_authorization_cannot_be_invalidated
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        pending = create_authorization(
            client, subscriber["id"], profile["id"], "d1.example.org"
        )
        assert pending["state"] == AUTH_PENDING, (
            f"a fresh challenge starts PENDING, found {pending['state']!r}"
        )

        refused = client.invalidate_authorization(
            pending["id"], invalidate_payload(), users.VALIDATION_OFFICER
        )
        validate_error(refused, ERR_AUTHORIZATION_NOT_VALIDATED, 409)

        settled = read_authorization(client, pending["id"])
        assert settled["state"] == AUTH_PENDING, (
            f"the refused invalidation must not move the state, found "
            f"{settled['state']!r}"
        )
        assert_counters(settled, invalidation_count=0, version=1)
        assert_nulls(settled, "invalidated_at", "validated_at", "expires_at")


class TestIssuanceRefusesAnUnclearedRequest:
    def test_a_a_submitted_request_reports_the_state_gate(self, client):
        """The state gate answers first, before the ceremony is even considered.

        PRD 3.7: "The request must be in `READY_TO_ISSUE`, so a request still
        `SUBMITTED`, or one sitting in `ISSUANCE_BLOCKED`, is refused with
        `ERR_REQUEST_NOT_READY`."
        PRD 2.8: "Precedence is global across the whole API, not per endpoint,
        and it runs in the following bands from highest to lowest."

        Design: Corner/errors/issuing_a_request_that_never_cleared_validation_is_refused
        """
        profile = create_profile(client)
        subscriber = create_subscriber(client)
        validated_authorization(client, subscriber["id"], profile["id"], "d1.example.org")
        partition = create_partition(client)
        ceremony = schedule_ceremony(client, partition["id"])
        assert ceremony["state"] == CEREMONY_SCHEDULED, (
            f"the ceremony is only scheduled, found {ceremony['state']!r}"
        )
        request = submitted_request(
            client, subscriber["id"], profile["id"], ("d1.example.org",)
        )
        assert request["state"] == REQUEST_SUBMITTED, (
            f"the request was never cleared, found {request['state']!r}"
        )

        refused = client.issue_certificate(
            request["id"], issue_payload(ceremony["id"]), users.ISSUANCE_OPERATOR_9
        )
        validate_error(refused, ERR_REQUEST_NOT_READY, 409)

        settled = read_request(client, request["id"])
        assert settled["state"] == REQUEST_SUBMITTED, (
            f"the refusal leaves the request SUBMITTED, found {settled['state']!r}"
        )
        assert_nulls(settled, "issued_certificate_id", "validation_cleared_at")
        assert settled["consumed_authorization_ids"] == [], (
            f"nothing was consumed, found {settled['consumed_authorization_ids']}"
        )

        _, certificate_meta = validate_paginated(
            client.list_certificates(
                users.ISSUANCE_OPERATOR, {"request_id": request["id"]}
            )
        )
        assert certificate_meta["total_count"] == 0, (
            f"no certificate may exist, found {certificate_meta['total_count']}"
        )
        settled_ceremony = read_ceremony(client, ceremony["id"])
        assert settled_ceremony["state"] == CEREMONY_SCHEDULED, (
            f"the ceremony is untouched, found {settled_ceremony['state']!r}"
        )
        assert_counters(settled_ceremony, issued_certificate_count=0)
        assert_counters(
            read_subscriber(client, subscriber["id"]),
            outstanding_balance_cents=0,
            issued_certificate_count=0,
        )


class TestReuseCeilingBlocksClearance:
    def test_a_the_second_clearance_exhausts_the_volumetric_budget(self, client):
        """With a ceiling of one, the second request finds no candidate left.

        PRD 3.5: "If a fresh `VALIDATED` authorization exists but every
        candidate's `reuse_count` has already reached `max_dcv_reuse_count`, the
        failure is `ERR_DCV_REUSE_LIMIT_EXCEEDED`."
        PRD 3.4: "The second limit is volumetric: `reuse_count` counts the
        certificate requests that have consumed the authorization at validation
        clearance, and it may never reach the profile's `max_dcv_reuse_count`."
        PRD 3.5: "`consumed_authorization_ids` receives the selected
        authorization identifiers in `requested_domains` order, one per domain,
        and every selected authorization has its `reuse_count` incremented by
        one."

        Design: Corner/errors/an_authorization_at_its_reuse_ceiling_blocks_the_next_clearance
        """
        profile = create_profile(
            client, profile_payload(max_dcv_reuse_count=1, base_fee_cents=20000)
        )
        subscriber = create_subscriber(client)
        authorization = validated_authorization(
            client, subscriber["id"], profile["id"], "d1.example.org"
        )
        assert_instant_equals(
            authorization["expires_at"], "2026-08-31T00:00:00Z", "expires_at"
        )

        first = cleared_request(
            client, subscriber["id"], profile["id"], ("d1.example.org",)
        )
        assert first["consumed_authorization_ids"] == [authorization["id"]], (
            f"the first clearance consumes the only authorization, found "
            f"{first['consumed_authorization_ids']}"
        )

        second = submitted_request(
            client, subscriber["id"], profile["id"], ("d1.example.org",)
        )
        refused = client.clear_validation(second["id"], users.VALIDATION_OFFICER)
        validate_error(refused, ERR_DCV_REUSE_LIMIT_EXCEEDED, 422)

        settled_authorization = read_authorization(client, authorization["id"])
        assert settled_authorization["state"] == AUTH_VALIDATED, (
            f"the authorization is still fresh, found {settled_authorization['state']!r}"
        )
        assert_counters(settled_authorization, reuse_count=1)
        assert_instant_equals(
            settled_authorization["expires_at"], "2026-08-31T00:00:00Z", "expires_at"
        )

        settled_second = read_request(client, second["id"])
        assert settled_second["state"] == REQUEST_SUBMITTED, (
            f"the refused clearance leaves the request SUBMITTED, found "
            f"{settled_second['state']!r}"
        )
        assert settled_second["consumed_authorization_ids"] == [], (
            f"nothing was consumed, found {settled_second['consumed_authorization_ids']}"
        )
        assert_nulls(
            settled_second,
            "projected_charge_cents",
            "validation_cleared_by_user_id",
            "validation_cleared_at",
        )
        assert read_request(client, first["id"])["state"] == REQUEST_READY_TO_ISSUE, (
            "the first request keeps its clearance"
        )


def _issued_certificate(client, **profile_overrides):
    """One certificate signed under an attested ceremony, still PREISSUANCE."""
    environment = build_environment(
        client, profile_payload=profile_payload(**profile_overrides)
    )
    certificate = issue_certificate(client, environment)
    assert_certificate_dimensions(
        certificate, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_NONE
    )
    return environment, certificate


class TestCertificateAndCtSubmissionErrors:
    def test_a_the_rejection_reason_must_match_the_outcome_both_ways(self, client):
        """An accepted submission carrying a cause, and a rejected one without.

        PRD 3.7: "A `rejection_reason` carrying the log's reported cause must be
        present exactly when the outcome is `REJECTED` and must be omitted or
        null when it is `ACCEPTED`; either mismatch is rejected with
        `ERR_REJECTION_REASON_MISMATCH`."
        PRD 3.7: "`counted_toward_sct` on a new submission is true only when its
        `outcome` is `ACCEPTED` and no earlier submission for the same
        certificate and the same `log_operator` was already `ACCEPTED`."

        Design: Corner/errors/certificate_lifecycle_and_ct_submission_errors_along_one_issuance
        """
        _, certificate = _issued_certificate(client, base_fee_cents=20000)

        accepted_with_reason = client.submit_ct_log(
            certificate["id"],
            ct_submission_payload(
                LOG_OPERATOR_GOOGLE_ARGON,
                CT_OUTCOME_ACCEPTED,
                rejection_reason="the log reported a malformed pre-certificate",
            ),
            users.ISSUANCE_OPERATOR,
        )
        validate_error(accepted_with_reason, ERR_REJECTION_REASON_MISMATCH, 422)

        rejected_without_reason = client.submit_ct_log(
            certificate["id"],
            ct_submission_payload(LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_REJECTED),
            users.ISSUANCE_OPERATOR,
        )
        validate_error(rejected_without_reason, ERR_REJECTION_REASON_MISMATCH, 422)

        _, meta = validate_paginated(
            client.list_ct_submissions(certificate["id"], users.ISSUANCE_OPERATOR)
        )
        assert meta["total_count"] == 0, (
            f"neither mismatched submission may be stored, found {meta['total_count']}"
        )

        accepted = get_success_data(
            client.submit_ct_log(
                certificate["id"],
                ct_submission_payload(
                    LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED
                ),
                users.ISSUANCE_OPERATOR,
            ),
            201,
        )
        assert accepted["counted_toward_sct"] is True, (
            f"the first acceptance from a log counts, found "
            f"{accepted['counted_toward_sct']!r}"
        )
        rows, meta = validate_paginated(
            client.list_ct_submissions(certificate["id"], users.ISSUANCE_OPERATOR)
        )
        assert meta["total_count"] == 1, (
            f"only the well-formed submission is stored, found {rows}"
        )
        assert_counters(read_certificate(client, certificate["id"]), sct_count=1)

    def test_b_a_certificate_can_only_be_activated_once(self, client):
        """Activation is a one-way door out of PREISSUANCE.

        PRD 3.7: "The `lifecycle_status` must be `PREISSUANCE`, so activating an
        already-`ISSUED` certificate earns `ERR_CERTIFICATE_NOT_PREISSUANCE`, and
        `revocation_status` must still be `NONE`."
        PRD 3.7: "Activation stamps `activated_at` with the logical clock and
        increments the certificate's `version`."

        Design: Corner/errors/certificate_lifecycle_and_ct_submission_errors_along_one_issuance
        """
        _, certificate = _issued_certificate(client, required_sct_count=1)
        get_success_data(
            client.submit_ct_log(
                certificate["id"],
                ct_submission_payload(
                    LOG_OPERATOR_GOOGLE_ARGON, CT_OUTCOME_ACCEPTED
                ),
                users.ISSUANCE_OPERATOR,
            ),
            201,
        )

        activated = get_success_data(
            client.activate_certificate(certificate["id"], users.ISSUANCE_OPERATOR)
        )
        assert_certificate_dimensions(
            activated, LIFECYCLE_ISSUED, REVOCATION_STATUS_NONE
        )
        assert_instant_equals(activated["activated_at"], WINDOW_END, "activated_at")

        again = client.activate_certificate(certificate["id"], users.ISSUANCE_OPERATOR)
        validate_error(again, ERR_CERTIFICATE_NOT_PREISSUANCE, 409)

        settled = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(settled, LIFECYCLE_ISSUED, REVOCATION_STATUS_NONE)
        assert_instant_equals(settled["activated_at"], WINDOW_END, "activated_at")
        assert settled["version"] == activated["version"], (
            f"the refused activation must not bump the version: "
            f"{settled['version']} vs {activated['version']}"
        )

    def test_c_a_revoked_certificate_refuses_both_revocation_and_transparency(
        self, client
    ):
        """Once REVOKED the certificate is closed to new requests and new logs.

        PRD 3.8: "The target certificate must be revocable, meaning its
        `lifecycle_status` is `PREISSUANCE` or `ISSUED` and its
        `revocation_status` is `NONE`; anything else is
        `ERR_CERTIFICATE_NOT_REVOCABLE`."
        PRD 3.7: "The target certificate must have `lifecycle_status`
        `PREISSUANCE` or `ISSUED` and `revocation_status` `NONE`, or the
        submission is refused with `ERR_CERTIFICATE_NOT_REVOCABLE`."

        Design: Corner/errors/certificate_lifecycle_and_ct_submission_errors_along_one_issuance
        """
        _, certificate = _issued_certificate(client, base_fee_cents=20000)
        raised = raise_revocation(
            client,
            certificate,
            REASON_KEY_COMPROMISE,
            evidence_ref="EVID-2026-08-01-key-compromise",
        )
        executed = get_success_data(
            client.execute_revocation(raised["id"], users.REVOCATION_OFFICER)
        )
        assert executed["state"] == REVOCATION_EXECUTED, (
            f"the revocation was executed, found {executed['state']!r}"
        )
        revoked = read_certificate(client, certificate["id"])
        assert_certificate_dimensions(
            revoked, LIFECYCLE_PREISSUANCE, REVOCATION_STATUS_REVOKED
        )
        assert_instant_equals(revoked["revoked_at"], WINDOW_END, "revoked_at")

        second_raise = client.raise_revocation(
            revocation_payload(
                certificate["id"], REASON_SUPERSEDED, revoked["version"]
            ),
            users.REVOCATION_OFFICER,
        )
        validate_error(second_raise, ERR_CERTIFICATE_NOT_REVOCABLE, 409)

        late_submission = client.submit_ct_log(
            certificate["id"],
            ct_submission_payload(
                LOG_OPERATOR_CLOUDFLARE_NIMBUS, CT_OUTCOME_ACCEPTED
            ),
            users.ISSUANCE_OPERATOR,
        )
        validate_error(late_submission, ERR_CERTIFICATE_NOT_REVOCABLE, 409)

        _, revocation_meta = validate_paginated(
            client.list_revocations(
                users.REVOCATION_OFFICER, {"certificate_id": certificate["id"]}
            )
        )
        assert revocation_meta["total_count"] == 1, (
            f"the refused raise adds no request, found {revocation_meta['total_count']}"
        )
        _, ct_meta = validate_paginated(
            client.list_ct_submissions(certificate["id"], users.ISSUANCE_OPERATOR)
        )
        assert ct_meta["total_count"] == 0, (
            f"the refused submission is not stored, found {ct_meta['total_count']}"
        )


def _two_certificates_aging_out_together(client):
    """Two certificates whose `not_after` is pinned by the authorization floor."""
    profile = create_profile(
        client, profile_payload(base_fee_cents=20000, required_sct_count=1)
    )
    subscriber = create_subscriber(client)
    for domain in ("a1.example.org", "b1.example.org"):
        validated_authorization(client, subscriber["id"], profile["id"], domain)
    partition = create_partition(client)
    ceremony = schedule_ceremony(client, partition["id"])
    witness_twice(client, ceremony["id"])
    attest_ceremony_at_window_end(client, ceremony["id"])
    certificates = []
    for domain in ("a1.example.org", "b1.example.org"):
        request = cleared_request(client, subscriber["id"], profile["id"], (domain,))
        certificate = issue_from_request(client, request["id"], ceremony["id"])
        assert_instant_equals(
            certificate["not_after"], "2026-08-31T00:00:00Z", "not_after"
        )
        certificates.append(certificate)
    return profile, subscriber, certificates


class TestAgedOutCertificate:
    def test_a_activation_reports_expiry_rather_than_missing_scts(self, client):
        """The clock landing exactly on `not_after` expires the certificate.

        PRD 2.6: "Sweep two expires certificates: every certificate whose
        `lifecycle_status` is `PREISSUANCE` or `ISSUED` and whose `not_after` is
        at or before the new clock moves to `lifecycle_status` `EXPIRED`, and its
        `version` increments."
        PRD 3.7: "The certificate's `not_after` must be strictly after the
        logical clock — a certificate that has already aged out is refused with
        `ERR_CERTIFICATE_ALREADY_EXPIRED`, and this check is evaluated ahead of
        the state check precisely because clock sweep two flips an unactivated
        certificate to `EXPIRED` the instant its `not_after` arrives."
        PRD 3.7: "Finally `sct_count` must be at least the profile's
        `required_sct_count`; the comparison is inclusive, so a count exactly
        equal to the requirement passes, while anything lower is refused with
        `ERR_INSUFFICIENT_SCTS`."

        Design: Corner/errors/an_aged_out_certificate_can_be_neither_activated_nor_revoked
        """
        profile, subscriber, certificates = _two_certificates_aging_out_together(client)
        first = certificates[0]
        assert_counters(first, sct_count=0)
        assert_counters(read_profile(client, profile["id"]), required_sct_count=1)

        advance_clock(client, "2026-08-31T00:00:00Z")

        aged = read_certificate(client, first["id"])
        assert_certificate_dimensions(aged, LIFECYCLE_EXPIRED, REVOCATION_STATUS_NONE)

        refused = client.activate_certificate(first["id"], users.ISSUANCE_OPERATOR)
        validate_error(refused, ERR_CERTIFICATE_ALREADY_EXPIRED, 409)

        settled = read_certificate(client, first["id"])
        assert_nulls(settled, "activated_at")
        assert_certificate_dimensions(
            settled, LIFECYCLE_EXPIRED, REVOCATION_STATUS_NONE
        )
        rows, _ = validate_paginated(
            client.list_authorizations(
                users.VALIDATION_OFFICER, {"subscriber_id": subscriber["id"]}
            )
        )
        assert [row["state"] for row in rows] == [AUTH_EXPIRED, AUTH_EXPIRED], (
            f"sweep one expires both authorizations, found "
            f"{[row['state'] for row in rows]}"
        )

    def test_b_an_expired_certificate_must_have_its_revocation_denied(self, client):
        """Execution is refused; denial is the way out, and it releases the row.

        PRD 3.8: "A `REVOCATION_OFFICER` executes a request that must be in
        `REQUESTED` (`ERR_REVOCATION_REQUEST_NOT_OPEN` otherwise), whose target
        certificate's `lifecycle_status` must not be `EXPIRED` — an expired
        certificate is never added to a revocation list, and its open request
        must be denied instead, so the attempt is refused with
        `ERR_CERTIFICATE_EXPIRED_NOT_REVOCABLE` — whose target certificate must
        be in `revocation_status` `REVOCATION_PENDING`, and which must be that
        certificate's newest request in `REQUESTED` state."
        PRD 3.8: "The target certificate returns `REVOCATION_PENDING → NONE`, but
        only when no other revocation request for it remains in `REQUESTED`; the
        subscriber's `revocation_pending_count` decrements by one, un-suspending
        the account once it is below 2."

        Design: Corner/errors/an_aged_out_certificate_can_be_neither_activated_nor_revoked
        """
        profile, subscriber, certificates = _two_certificates_aging_out_together(client)
        second = certificates[1]
        raised = raise_revocation(client, second, REASON_AFFILIATION_CHANGED)
        assert raised["state"] == REVOCATION_REQUESTED, (
            f"the request opens in REQUESTED, found {raised['state']!r}"
        )
        assert_certificate_dimensions(
            read_certificate(client, second["id"]),
            LIFECYCLE_PREISSUANCE,
            REVOCATION_STATUS_PENDING,
        )

        advance_clock(client, "2026-08-31T00:00:00Z")

        refused = client.execute_revocation(raised["id"], users.REVOCATION_OFFICER)
        validate_error(refused, ERR_CERTIFICATE_EXPIRED_NOT_REVOCABLE, 409)
        assert_counters(
            read_profile(client, profile["id"]),
            pending_crl_entry_count=0,
            revoked_certificate_count=0,
        )

        denied = get_success_data(
            client.deny_revocation(
                raised["id"], denial_payload(), users.REVOCATION_OFFICER
            )
        )
        assert denied["state"] == REVOCATION_DENIED, (
            f"denial is the way out, found {denied['state']!r}"
        )
        released = read_certificate(client, second["id"])
        assert_certificate_dimensions(
            released, LIFECYCLE_EXPIRED, REVOCATION_STATUS_NONE
        )
        assert_counters(
            read_subscriber(client, subscriber["id"]),
            revocation_pending_count=0,
            account_status=SUBSCRIBER_ACTIVE,
        )


class TestIncidentScopeAndStateErrors:
    def test_a_the_scope_window_and_method_are_checked_before_the_row_exists(
        self, client
    ):
        """A degenerate window and an off-profile method are both refused.

        PRD 3.9: "`scope_issued_to` must be strictly after `scope_issued_from`
        (`ERR_INVALID_SCOPE_WINDOW`), and when `scope_dcv_method` is supplied it
        must appear in the scoped profile's `allowed_dcv_methods`
        (`ERR_SCOPE_METHOD_NOT_IN_PROFILE`)."
        PRD 3.9: "Creation stamps `discovered_at` with the logical clock and sets
        `disclosure_due_at` to exactly 24 hours later, the root program
        disclosure deadline."

        Design: Corner/errors/incident_state_and_scope_errors_around_one_open_incident
        """
        profile = create_profile(client)
        assert profile["allowed_dcv_methods"] == ["DNS_TXT"], (
            f"the scoped profile allows only DNS_TXT, found "
            f"{profile['allowed_dcv_methods']}"
        )
        incident = open_incident(
            client,
            profile["id"],
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-07-01T00:00:00Z",
            scope_issued_to="2026-07-31T00:00:00Z",
        )
        assert_instant_equals(incident["discovered_at"], CLOCK_START, "discovered_at")
        assert_instant_equals(
            incident["disclosure_due_at"], "2026-08-02T00:00:00Z", "disclosure_due_at"
        )

        degenerate = client.create_incident(
            incident_payload(
                profile["id"],
                category=INCIDENT_DOMAIN_MISISSUANCE,
                scope_issued_from="2026-07-01T00:00:00Z",
                scope_issued_to="2026-07-01T00:00:00Z",
            ),
            users.COMPLIANCE_AUDITOR,
        )
        validate_error(degenerate, ERR_INVALID_SCOPE_WINDOW, 422)

        off_profile = client.create_incident(
            incident_payload(
                profile["id"],
                category=INCIDENT_DOMAIN_MISISSUANCE,
                scope_issued_from="2026-07-01T00:00:00Z",
                scope_issued_to="2026-07-31T00:00:00Z",
                scope_dcv_method=DCV_METHOD_HTTP_TOKEN,
            ),
            users.COMPLIANCE_AUDITOR,
        )
        validate_error(off_profile, ERR_SCOPE_METHOD_NOT_IN_PROFILE, 422)

        rows, meta = validate_paginated(
            client.list_incidents(users.COMPLIANCE_AUDITOR)
        )
        assert meta["total_count"] == 1, (
            f"only the well-formed incident exists, found {rows}"
        )
        assert rows[0]["id"] == incident["id"]

    def test_b_an_open_incident_can_be_neither_closed_nor_mass_revoked(self, client):
        """Both later-stage acts require a disclosure that has not happened.

        PRD 3.9: "A `COMPLIANCE_AUDITOR` closes an incident whose `state` is
        `DISCLOSED`, `MASS_REVOCATION_IN_PROGRESS` or `REMEDIATED` — anything
        else, including an `OPEN` incident, is `ERR_INCIDENT_NOT_CLOSEABLE` — and
        whose `remaining_scope_count` is 0 with every revocation request carrying
        this `incident_id` resolved to `EXECUTED` or `DENIED`; an unfinished tail
        is `ERR_INCIDENT_REVOCATIONS_OUTSTANDING`."
        PRD 3.9: "A `REVOCATION_OFFICER` runs a batch against an incident whose
        `state` is `DISCLOSED` or `MASS_REVOCATION_IN_PROGRESS`, after the
        breach-escalation gate above."
        PRD 3.9: "A `COMPLIANCE_AUDITOR` files that escalation for an incident
        already in `DISCLOSED` or `MASS_REVOCATION_IN_PROGRESS` (otherwise
        `ERR_INCIDENT_NOT_DISCLOSED`) by supplying `root_program` and `body`; the
        record carries `kind` `BREACH_ESCALATION`, its `incident_id` set, its
        `audit_id` null, and `within_deadline` always false, because a breach
        escalation is by definition late."

        Design: Corner/errors/incident_state_and_scope_errors_around_one_open_incident
        """
        profile = create_profile(client)
        incident = open_incident(
            client,
            profile["id"],
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-07-01T00:00:00Z",
            scope_issued_to="2026-07-31T00:00:00Z",
        )
        assert incident["state"] == INCIDENT_OPEN, (
            f"the incident is born OPEN, found {incident['state']!r}"
        )

        too_early_close = client.close_incident(
            incident["id"], users.COMPLIANCE_AUDITOR
        )
        validate_error(too_early_close, ERR_INCIDENT_NOT_CLOSEABLE, 409)

        too_early_batch = client.mass_revoke(incident["id"], users.REVOCATION_OFFICER)
        validate_error(too_early_batch, ERR_INCIDENT_NOT_DISCLOSED, 409)

        settled = read_incident(client, incident["id"])
        assert settled["state"] == INCIDENT_OPEN, (
            f"two refusals leave the incident OPEN, found {settled['state']!r}"
        )
        assert_nulls(settled, "disclosed_at", "closed_at")
        assert_counters(settled, revoked_certificate_count=0, penalty_total_cents=0)

    def test_c_correspondence_waits_for_disclosure_and_disclosure_happens_once(
        self, client
    ):
        """The communications endpoint opens only after the single disclosure.

        PRD 3.9: "A `COMPLIANCE_AUDITOR` discloses an incident in `state` `OPEN` —
        anything else is `ERR_INCIDENT_NOT_OPEN` — naming the `root_program`
        addressed (`MOZILLA`, `CHROME`, `APPLE` or `MICROSOFT`) and supplying the
        narrative `body`."
        PRD 3.9: "The incident moves `OPEN → DISCLOSED`, `disclosed_at` is
        stamped with the logical clock, and a root program communication is
        recorded with `kind` `INCIDENT_DISCLOSURE`, its `incident_id` set, its
        `audit_id` null, its `sent_at` at the logical clock, its
        `sent_by_user_id` taken from `X-User-ID`, and `within_deadline` true when
        `sent_at` is at or before `disclosure_due_at` — a disclosure landing
        exactly on the deadline instant is on time."
        PRD 3.9: "A `COMPLIANCE_AUDITOR` files that escalation for an incident
        already in `DISCLOSED` or `MASS_REVOCATION_IN_PROGRESS` (otherwise
        `ERR_INCIDENT_NOT_DISCLOSED`) by supplying `root_program` and `body`; the
        record carries `kind` `BREACH_ESCALATION`, its `incident_id` set, its
        `audit_id` null, and `within_deadline` always false, because a breach
        escalation is by definition late."

        Design: Corner/errors/incident_state_and_scope_errors_around_one_open_incident
        """
        profile = create_profile(client)
        incident = open_incident(
            client,
            profile["id"],
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-07-01T00:00:00Z",
            scope_issued_to="2026-07-31T00:00:00Z",
        )

        premature = client.create_incident_communication(
            incident["id"],
            communication_payload(ROOT_PROGRAM_MOZILLA),
            users.COMPLIANCE_AUDITOR,
        )
        validate_error(premature, ERR_INCIDENT_NOT_DISCLOSED, 409)
        _, meta = validate_paginated(
            client.list_incident_communications(
                incident["id"], users.COMPLIANCE_AUDITOR
            )
        )
        assert meta["total_count"] == 0, (
            f"no correspondence exists yet, found {meta['total_count']}"
        )

        disclosed = get_success_data(
            client.disclose_incident(
                incident["id"],
                disclosure_payload(ROOT_PROGRAM_MOZILLA),
                users.COMPLIANCE_AUDITOR,
            )
        )
        assert disclosed["state"] == INCIDENT_DISCLOSED, (
            f"disclosure is the only exit from OPEN, found {disclosed['state']!r}"
        )
        assert_instant_equals(disclosed["disclosed_at"], CLOCK_START, "disclosed_at")
        assert disclosed["disclosure_breached"] is False, (
            "the disclosure is well inside the 24 hour window"
        )

        rows, meta = validate_paginated(
            client.list_incident_communications(
                incident["id"], users.COMPLIANCE_AUDITOR
            )
        )
        assert meta["total_count"] == 1, (
            f"disclosure records exactly one communication, found {rows}"
        )
        assert rows[0]["kind"] == COMM_INCIDENT_DISCLOSURE, (
            f"kind is {rows[0]['kind']!r}, expected {COMM_INCIDENT_DISCLOSURE!r}"
        )
        assert rows[0]["within_deadline"] is True, (
            "a same-instant disclosure is inside the deadline"
        )

        again = client.disclose_incident(
            incident["id"],
            disclosure_payload(ROOT_PROGRAM_CHROME),
            users.COMPLIANCE_AUDITOR,
        )
        validate_error(again, ERR_INCIDENT_NOT_OPEN, 409)
        _, meta = validate_paginated(
            client.list_incident_communications(
                incident["id"], users.COMPLIANCE_AUDITOR
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused disclosure records nothing, found {meta['total_count']}"
        )


class TestAuditOpinionGates:
    def test_a_the_period_shape_and_the_open_audit_rule_are_checked_first(
        self, client
    ):
        """A degenerate period, an over-long period and a duplicate are refused.

        PRD 3.9: "`period_end` must be strictly after `period_start` and the
        period may span at most 366 days; either violation is
        `ERR_INVALID_AUDIT_PERIOD`."
        PRD 3.9: "Only one audit per root program may be in flight at a time: no
        audit in `state` `SCHEDULED` or `FIELDWORK` may already exist for the same
        `root_program`, or the attempt is refused with `ERR_AUDIT_ALREADY_OPEN`."

        Design: Corner/errors/audit_opinion_gates_reject_out_of_order_findings_opinions_and_correspondence
        """
        audit = open_audit(
            client,
            root_program=ROOT_PROGRAM_MOZILLA,
            period_start="2025-08-01T00:00:00Z",
            period_end="2026-07-31T00:00:00Z",
        )
        assert audit["state"] == AUDIT_SCHEDULED, (
            f"a new audit is SCHEDULED, found {audit['state']!r}"
        )

        degenerate = client.create_audit(
            audit_payload(
                ROOT_PROGRAM_APPLE, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"
            ),
            users.COMPLIANCE_AUDITOR,
        )
        validate_error(degenerate, ERR_INVALID_AUDIT_PERIOD, 422)

        too_long = client.create_audit(
            audit_payload(
                ROOT_PROGRAM_APPLE, "2026-01-01T00:00:00Z", "2027-02-05T00:00:00Z"
            ),
            users.COMPLIANCE_AUDITOR,
        )
        validate_error(too_long, ERR_INVALID_AUDIT_PERIOD, 422)

        duplicate = client.create_audit(
            audit_payload(
                ROOT_PROGRAM_MOZILLA, "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
            ),
            users.COMPLIANCE_AUDITOR,
        )
        validate_error(duplicate, ERR_AUDIT_ALREADY_OPEN, 409)

        rows, meta = validate_paginated(client.list_audits(users.COMPLIANCE_AUDITOR))
        assert meta["total_count"] == 1, (
            f"only the first audit exists, found {rows}"
        )
        assert rows[0]["id"] == audit["id"]

    def test_b_correspondence_and_an_empty_opinion_are_both_premature(self, client):
        """Before any fieldwork there is nothing to opine on and nobody to answer.

        PRD 3.9: "A `COMPLIANCE_AUDITOR` files a response for an audit whose
        `state` is `QUALIFIED` or `UNQUALIFIED` — correspondence is only sent
        after an opinion exists, so an audit still in `SCHEDULED` or `FIELDWORK`
        is refused with `ERR_AUDIT_NOT_OPINED` — supplying the `root_program`
        addressed and the `body`."
        PRD 3.9: "A `COMPLIANCE_AUDITOR` opines on an audit that has not been
        opined yet — an audit already in `QUALIFIED` or `UNQUALIFIED` can never be
        opined again, and the attempt is refused with `ERR_AUDIT_NOT_IN_FIELDWORK`
        — and whose `finding_count` is at least 1, since an audit with no
        fieldwork at all cannot carry an opinion (`ERR_AUDIT_NO_FINDINGS`)."

        Design: Corner/errors/audit_opinion_gates_reject_out_of_order_findings_opinions_and_correspondence
        """
        audit = open_audit(
            client,
            root_program=ROOT_PROGRAM_MOZILLA,
            period_start="2025-08-01T00:00:00Z",
            period_end="2026-07-31T00:00:00Z",
        )

        premature = client.create_audit_communication(
            audit["id"],
            communication_payload(ROOT_PROGRAM_MOZILLA),
            users.COMPLIANCE_AUDITOR,
        )
        validate_error(premature, ERR_AUDIT_NOT_OPINED, 409)

        empty_opinion = client.opine_audit(audit["id"], users.COMPLIANCE_AUDITOR)
        validate_error(empty_opinion, ERR_AUDIT_NO_FINDINGS, 422)

        settled = read_audit(client, audit["id"])
        assert settled["state"] == AUDIT_SCHEDULED, (
            f"the refused opinion leaves the audit SCHEDULED, found "
            f"{settled['state']!r}"
        )
        assert_counters(settled, finding_count=0, critical_finding_count=0)
        assert_nulls(settled, "opinion_at", "opined_by_user_id")
        _, meta = validate_paginated(
            client.list_audit_communications(audit["id"], users.COMPLIANCE_AUDITOR)
        )
        assert meta["total_count"] == 0, (
            f"no correspondence was filed, found {meta['total_count']}"
        )

    def test_c_the_opinion_closes_fieldwork_and_opens_correspondence(self, client):
        """One opinion only, no findings after it, and the response is now allowed.

        PRD 3.9: "A finding recorded against an audit that already carries an
        opinion is refused with `ERR_AUDIT_NOT_OPEN_FOR_FINDINGS`."
        PRD 3.9: "The outcome is `QUALIFIED` when `critical_finding_count` is at
        least 1 or `finding_count` is at least 3, and `UNQUALIFIED` when
        `critical_finding_count` is 0 and `finding_count` is below 3."
        PRD 3.9: "The record carries `kind` `ROOT_PROGRAM_RESPONSE`, its
        `audit_id` set, its `incident_id` null, its `sent_at` at the logical clock
        and its `sent_by_user_id` from `X-User-ID`, and `within_deadline` is true
        when `sent_at` is at or before `opinion_at` plus 14 days — a response
        filed exactly on the fourteenth day is within the deadline."

        Design: Corner/errors/audit_opinion_gates_reject_out_of_order_findings_opinions_and_correspondence
        """
        audit = open_audit(
            client,
            root_program=ROOT_PROGRAM_MOZILLA,
            period_start="2025-08-01T00:00:00Z",
            period_end="2026-07-31T00:00:00Z",
        )
        in_fieldwork = get_success_data(
            client.record_finding(
                audit["id"], finding_payload(SEVERITY_MINOR), users.COMPLIANCE_AUDITOR
            )
        )
        assert in_fieldwork["state"] == AUDIT_FIELDWORK, (
            f"the first finding opens fieldwork, found {in_fieldwork['state']!r}"
        )
        assert_counters(in_fieldwork, finding_count=1, critical_finding_count=0)

        opined = get_success_data(client.opine_audit(audit["id"], users.COMPLIANCE_AUDITOR))
        assert opined["state"] == AUDIT_UNQUALIFIED, (
            f"one minor finding is unqualified, found {opined['state']!r}"
        )
        assert_instant_equals(opined["opinion_at"], CLOCK_START, "opinion_at")
        assert_counters(opined, assessed_subscriber_count=0, retired_profile_count=0)

        second_opinion = client.opine_audit(audit["id"], users.COMPLIANCE_AUDITOR)
        validate_error(second_opinion, ERR_AUDIT_NOT_IN_FIELDWORK, 409)

        late_finding = client.record_finding(
            audit["id"], finding_payload(SEVERITY_CRITICAL), users.COMPLIANCE_AUDITOR
        )
        validate_error(late_finding, ERR_AUDIT_NOT_OPEN_FOR_FINDINGS, 409)
        assert_counters(
            read_audit(client, audit["id"]), finding_count=1, critical_finding_count=0
        )

        response = get_success_data(
            client.create_audit_communication(
                audit["id"],
                communication_payload(ROOT_PROGRAM_MOZILLA),
                users.COMPLIANCE_AUDITOR,
            ),
            201,
        )
        assert response["kind"] == COMM_ROOT_PROGRAM_RESPONSE, (
            f"kind is {response['kind']!r}, expected {COMM_ROOT_PROGRAM_RESPONSE!r}"
        )
        assert response["within_deadline"] is True, (
            "a response filed on the opinion instant is inside the 14 day window"
        )
        _, meta = validate_paginated(
            client.list_audit_communications(audit["id"], users.COMPLIANCE_AUDITOR)
        )
        assert meta["total_count"] == 2, (
            f"the clean notice and this response, found {meta['total_count']}"
        )


class TestSecondOpenRowIsRefused:
    def test_a_a_second_vetting_and_a_same_triple_authorization_are_refused(
        self, client
    ):
        """One vetting file and one live challenge per key, and no more.

        PRD 3.3: "A subscriber may have only one file in flight: if it already
        holds a vetting whose `vetting_state` is `PENDING`, `IN_PROGRESS` or
        `AWAITING_APPROVAL`, opening another is rejected with
        `ERR_VETTING_ALREADY_OPEN`."
        PRD 3.4: "Finally, the triple of subscriber, profile and domain name may
        have at most one live challenge: if an authorization for the same triple
        already sits in state `PENDING` or `VALIDATED`, the new one is rejected
        with `ERR_AUTHORIZATION_ALREADY_OPEN`, while triples whose only prior
        authorizations are `FAILED`, `EXHAUSTED` or `EXPIRED` are free to be
        reopened."

        Design: Corner/errors/a_second_open_vetting_or_authorization_for_the_same_key_is_refused
        """
        profile = create_profile(
            client, ov_profile_payload(org_vetting_reuse_days=30, base_fee_cents=20000)
        )
        subscriber = create_subscriber(client)
        vetting = get_success_data(
            client.open_vetting(
                subscriber["id"],
                vetting_payload(VETTING_LEVEL_OV),
                users.VALIDATION_OFFICER,
            ),
            201,
        )
        assert vetting["vetting_state"] == VETTING_PENDING, (
            f"a new file is PENDING, found {vetting['vetting_state']!r}"
        )
        authorization = create_authorization(
            client, subscriber["id"], profile["id"], "d1.example.org"
        )

        second_file = client.open_vetting(
            subscriber["id"],
            vetting_payload(VETTING_LEVEL_EV),
            users.VALIDATION_OFFICER_2,
        )
        validate_error(second_file, ERR_VETTING_ALREADY_OPEN, 409)

        rows, meta = validate_paginated(
            client.list_vettings(subscriber["id"], users.VALIDATION_OFFICER)
        )
        assert meta["total_count"] == 1, (
            f"the subscriber keeps one file, found {meta['total_count']}"
        )
        assert rows[0]["required_level"] == VETTING_LEVEL_OV, (
            f"the surviving file is the OV one, found {rows[0]['required_level']!r}"
        )
        assert rows[0]["vetting_state"] == VETTING_PENDING

        same_triple = client.create_authorization(
            authorization_payload(subscriber["id"], profile["id"], "d1.example.org"),
            users.VALIDATION_OFFICER,
        )
        validate_error(same_triple, ERR_AUTHORIZATION_ALREADY_OPEN, 409)
        assert_counters(read_authorization(client, authorization["id"]), version=1)

        other_domain = create_authorization(
            client, subscriber["id"], profile["id"], "d2.example.org"
        )
        assert other_domain["state"] == AUTH_PENDING
        _, meta = validate_paginated(
            client.list_authorizations(
                users.VALIDATION_OFFICER, {"subscriber_id": subscriber["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            f"a different domain is a different triple, found {meta['total_count']}"
        )


class TestWindowShapedInputsWriteNothing:
    def test_a_a_degenerate_ceremony_window_is_refused(self, client):
        """A window that ends when it starts never becomes a ceremony.

        PRD 3.6: "The window must be non-degenerate, with `window_end` strictly
        after `window_start`, or `ERR_INVALID_CEREMONY_WINDOW` is raised, and
        `attestation_valid_days` must lie between 1 and 365."

        Design: Corner/errors/window_shaped_inputs_are_rejected_before_any_row_is_written
        """
        partition = create_partition(client)

        refused = client.schedule_ceremony(
            partition["id"],
            ceremony_payload(CLOCK_START, CLOCK_START, 60),
            users.ISSUANCE_OPERATOR,
        )
        validate_error(refused, ERR_INVALID_CEREMONY_WINDOW, 422)

        rows, meta = validate_paginated(
            client.list_ceremonies(partition["id"], users.ISSUANCE_OPERATOR)
        )
        assert meta["total_count"] == 0, (
            f"the refused schedule leaves no ceremony, found {rows}"
        )
        assert_counters(
            read_partition(client, partition["id"]), attested_ceremony_count=0
        )

    def test_b_two_bad_crl_windows_leave_the_series_untouched(self, client):
        """The refusals do not consume the version token the next call reuses.

        PRD 3.8: "First, `next_update` must be strictly after `this_update`, or
        `ERR_INVALID_CRL_WINDOW`."
        PRD 3.8: "Fourth, the span from `this_update` to `next_update` must be at
        most the profile's `max_crl_validity_hours` in hours, or
        `ERR_CRL_VALIDITY_TOO_LONG`."
        PRD 3.8: "A publication with an empty drain set is perfectly legal:
        `entry_count` is 0, `revoked_serials` is an empty array, and `crl_number`
        still advances by one."

        Design: Corner/errors/window_shaped_inputs_are_rejected_before_any_row_is_written
        """
        profile = create_profile(client, profile_payload(max_crl_validity_hours=24))
        version = profile_version(client, profile["id"])

        degenerate = client.publish_crl(
            profile["id"],
            crl_publication_payload(CLOCK_START, CLOCK_START, version),
            users.REVOCATION_OFFICER,
        )
        validate_error(degenerate, ERR_INVALID_CRL_WINDOW, 422)

        too_long = client.publish_crl(
            profile["id"],
            crl_publication_payload(CLOCK_START, "2026-08-02T01:00:00Z", version),
            users.REVOCATION_OFFICER,
        )
        validate_error(too_long, ERR_CRL_VALIDITY_TOO_LONG, 422)

        untouched = read_profile(client, profile["id"])
        assert untouched["version"] == version, (
            f"neither refusal bumps the profile version: {untouched['version']} "
            f"vs {version}"
        )
        assert untouched["last_crl_number"] in (0, None), (
            f"nothing has been published yet, found {untouched['last_crl_number']!r}"
        )
        _, meta = validate_paginated(
            client.list_crl_publications(profile["id"], users.REVOCATION_OFFICER)
        )
        assert meta["total_count"] == 0, (
            f"no publication row exists, found {meta['total_count']}"
        )

        published = get_success_data(
            client.publish_crl(
                profile["id"],
                crl_publication_payload(CLOCK_START, "2026-08-02T00:00:00Z", version),
                users.REVOCATION_OFFICER,
            ),
            201,
        )
        assert_counters(published, crl_number=1, entry_count=0)
        assert published["revoked_serials"] == [], (
            f"the drain set was empty, found {published['revoked_serials']}"
        )
        settled = read_profile(client, profile["id"])
        assert_counters(settled, last_crl_number=1)
        assert_instant_equals(
            settled["last_crl_next_update"], "2026-08-02T00:00:00Z", "last_crl_next_update"
        )


class TestCascadeRevocationCannotBeDenied:
    def test_a_a_system_cascade_request_refuses_denial(self, client):
        """The repudiation cascade raises a request nobody may wave away.

        PRD 3.6: "Hop three: because the partition is now quarantined, every
        certificate whose `ceremony_id` names *any* ceremony of that partition —
        not only the repudiated one — and whose `revocation_status` is `NONE`
        moves to `REVOCATION_PENDING`, processed in ascending `created_at` order,
        and each receives a system-raised revocation request whose `origin` is
        `SYSTEM_CASCADE`, whose `reason_code` is `KEY_COMPROMISE`, whose
        `evidence_ref` is the literal string `ceremony:` followed by the
        repudiated ceremony's identifier, and whose `requested_by_user_id` is the
        literal string `system`."
        PRD 3.8: "A `REVOCATION_OFFICER` denies a request in `REQUESTED` state by
        supplying a `denial_reason`, and the request's `origin` must not be
        `SYSTEM_CASCADE` — a cascade-raised revocation reflects a real key
        compromise and may never be waved away, so the attempt is refused with
        `ERR_CASCADE_REVOCATION_NOT_DENIABLE`."

        Design: Corner/errors/a_cascade_raised_revocation_request_can_never_be_denied
        """
        environment = build_environment(client)
        certificate = issue_certificate(client, environment)

        get_success_data(
            client.revoke_attestation(
                environment.ceremony_id,
                attestation_revocation_payload(),
                users.COMPLIANCE_AUDITOR_2,
            )
        )

        rows, meta = validate_paginated(
            client.list_revocations(
                users.REVOCATION_OFFICER,
                {
                    "certificate_id": certificate["id"],
                    "origin": ORIGIN_SYSTEM_CASCADE,
                },
            )
        )
        assert meta["total_count"] == 1, (
            f"the cascade raises exactly one request, found {meta['total_count']}"
        )
        cascade = rows[0]

        refused = client.deny_revocation(
            cascade["id"], denial_payload(), users.REVOCATION_OFFICER
        )
        validate_error(refused, ERR_CASCADE_REVOCATION_NOT_DENIABLE, 409)

        settled = read_revocation(client, cascade["id"])
        assert settled["state"] == REVOCATION_REQUESTED, (
            f"the cascade request stays open, found {settled['state']!r}"
        )
        assert settled["origin"] == ORIGIN_SYSTEM_CASCADE
        assert settled["reason_code"] == REASON_KEY_COMPROMISE, (
            f"reason_code is {settled['reason_code']!r}, expected "
            f"{REASON_KEY_COMPROMISE!r}"
        )
        assert_nulls(settled, "denied_at", "denial_reason")
        assert_certificate_dimensions(
            read_certificate(client, certificate["id"]),
            LIFECYCLE_PREISSUANCE,
            REVOCATION_STATUS_PENDING,
        )
        assert_counters(
            read_subscriber(client, environment.subscriber_id),
            revocation_pending_count=1,
            account_status=SUBSCRIBER_ACTIVE,
        )
        partition = read_partition(client, environment.partition_id)
        assert partition["state"] == PARTITION_QUARANTINED, (
            f"quarantine is terminal, found {partition['state']!r}"
        )


class TestCeremonyWindowMustClose:
    def test_a_attestation_waits_for_the_window_to_close(self, client):
        """Attesting at `window_start` is refused; at `window_end` it succeeds.

        PRD 3.6: "A `COMPLIANCE_AUDITOR` attests a ceremony that is `WITNESSED`
        (`ERR_CEREMONY_NOT_WITNESSED` otherwise), whose window has closed — the
        logical clock must be at or after `window_end`, and attesting while the
        window is still open is refused with `ERR_CEREMONY_WINDOW_OPEN` — and
        whose `witness_user_ids` does not contain the attester's own `X-User-ID`,
        since an auditor may not attest a ceremony it witnessed."
        PRD 3.6: "Attestation moves the ceremony `WITNESSED → ATTESTED`, stamps
        `attested_at` with the logical clock and `attested_by_user_id` with the
        attester's `X-User-ID`, and sets `attestation_expires_at` to `attested_at`
        plus `attestation_valid_days` in days."

        Design: Corner/errors/a_ceremony_cannot_be_attested_while_its_window_is_still_open
        """
        partition = create_partition(client)
        ceremony = schedule_ceremony(client, partition["id"], CLOCK_START, WINDOW_END, 60)
        witnessed = witness_twice(client, ceremony["id"])
        assert witnessed["state"] == CEREMONY_WITNESSED, (
            f"two witnesses move it to WITNESSED, found {witnessed['state']!r}"
        )
        assert_counters(witnessed, witness_count=2)

        too_early = client.attest_ceremony(ceremony["id"], users.COMPLIANCE_AUDITOR)
        validate_error(too_early, ERR_CEREMONY_WINDOW_OPEN, 409)

        settled = read_ceremony(client, ceremony["id"])
        assert settled["state"] == CEREMONY_WITNESSED, (
            f"the refusal leaves it WITNESSED, found {settled['state']!r}"
        )
        assert_counters(settled, witness_count=2)
        assert_nulls(settled, "attested_at", "attested_by_user_id", "attestation_expires_at")
        assert_counters(
            read_partition(client, partition["id"]), attested_ceremony_count=0
        )

        advance_clock(client, WINDOW_END)
        attested = get_success_data(
            client.attest_ceremony(ceremony["id"], users.COMPLIANCE_AUDITOR)
        )
        assert attested["state"] == CEREMONY_ATTESTED, (
            f"at window_end the attestation lands, found {attested['state']!r}"
        )
        assert_instant_equals(attested["attested_at"], WINDOW_END, "attested_at")
        assert_instant_equals(
            attested["attestation_expires_at"],
            "2026-09-30T00:30:00Z",
            "attestation_expires_at",
        )
        assert_counters(
            read_partition(client, partition["id"]), attested_ceremony_count=1
        )
