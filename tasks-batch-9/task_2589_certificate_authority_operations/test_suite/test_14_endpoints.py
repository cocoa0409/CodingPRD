"""Endpoint-shape behaviour: partial updates, action verbs and derived reads.

These tests exercise the contract of individual endpoints — which fields a PATCH
body may leave alone, what an action endpoint does with an identifier it cannot
resolve, which cross-reference bodies are refused, and what a read exposes once
the server has derived it.
"""

from test_helpers import (
    DCV_METHOD_DNS_TXT,
    DCV_METHOD_EMAIL_APPROVAL,
    DCV_METHOD_TLS_ALPN,
    ERR_INCIDENT_CERTIFICATE_MISMATCH,
    ERR_INCIDENT_REVOCATIONS_OUTSTANDING,
    ERR_PROFILE_NOT_FOUND,
    ERR_SUPERSEDES_SUBSCRIBER_MISMATCH,
    INCIDENT_CLOSED,
    INCIDENT_DISCLOSED,
    INCIDENT_PROCEDURAL,
    LIFECYCLE_PREISSUANCE,
    NON_EXISTENT_UUID,
    PROFILE_STATE_ACTIVE,
    PROFILE_STATE_DRAFT,
    REASON_UNSPECIFIED,
    REQUEST_READY_TO_ISSUE,
    REVOCATION_DENIED,
    REVOCATION_STATUS_NONE,
    SUBSCRIBER_ACTIVE,
    VALIDATION_TYPE_DV,
    VETTING_LEVEL_OV,
    assert_counters,
    assert_instant_equals,
    assert_modifiable_identity,
    assert_nulls,
    attested_ceremony,
    build_environment,
    cleared_request,
    create_partition,
    create_profile,
    create_subscriber,
    denial_payload,
    disclosed_incident,
    issuance_charge_cents,
    issue_certificate,
    issue_from_request,
    issue_payload,
    open_incident,
    ov_profile_payload,
    plus_days,
    profile_payload,
    raise_revocation,
    read_certificate,
    read_incident,
    read_request,
    read_revocation,
    read_subscriber,
    revocation_payload,
    subscriber_amendment_payload,
    subscriber_payload,
    users,
    validate_error,
    validate_paginated,
    validate_success,
    validated_authorization,
)

_ISSUANCE_CLOCK = "2026-08-01T00:30:00Z"


def _subscriber_with_known_contact(client):
    """A registered subscriber whose three amendable fields are all known."""
    return create_subscriber(
        client,
        subscriber_payload(
            legal_name="Patchwork Holdings GmbH",
            credit_limit_cents=500000,
            contact_email="before@patch.example",
            callback_phone="+493055501",
        ),
    )


class TestSubscriberPartialAmendment:
    def test_amending_only_the_contact_email_leaves_the_credit_limit_alone(
        self, client
    ):
        """A one-field body is a partial update, not a replacement.

        PRD 3.2: "A `POLICY_ADMIN` may later amend `credit_limit_cents`,
        `contact_email` and `callback_phone`, each optionally and independently;
        that amendment increments the subscriber's `version`."
        PRD 2.4: "`version` is an integer that begins at 1 when the resource is
        created and increases by exactly one on every mutation of that resource,
        whether the mutation was requested directly by a client or applied
        indirectly by a cascade."

        Design: Corner/endpoints/patching_a_subscriber_touches_only_the_supplied_fields
        """
        subscriber = _subscriber_with_known_contact(client)
        assert_modifiable_identity(subscriber, expected_version=1)
        assert subscriber["credit_limit_cents"] == 500000

        amended = validate_success(
            client.amend_subscriber(
                subscriber["id"],
                subscriber_amendment_payload(contact_email="after@patch.example"),
                users.POLICY_ADMIN,
            )
        )

        assert amended["contact_email"] == "after@patch.example", (
            f"contact_email is {amended['contact_email']!r}, expected the new address"
        )
        assert amended["credit_limit_cents"] == 500000, (
            "an omitted field keeps its stored value, found "
            f"{amended['credit_limit_cents']}"
        )
        assert amended["callback_phone"] == subscriber["callback_phone"], (
            f"callback_phone changed to {amended['callback_phone']!r}"
        )
        assert amended["legal_name"] == "Patchwork Holdings GmbH", (
            "legal_name is not amendable and must be untouched"
        )
        assert amended["version"] == 2, (
            f"one amendment is one version, found {amended['version']}"
        )
        assert amended["account_status"] == SUBSCRIBER_ACTIVE
        assert_counters(amended, outstanding_balance_cents=0)

    def test_a_second_amendment_of_the_credit_limit_preserves_the_new_email(
        self, client
    ):
        """Consecutive partial amendments accumulate rather than overwrite.

        PRD 3.2: "A `POLICY_ADMIN` may later amend `credit_limit_cents`,
        `contact_email` and `callback_phone`, each optionally and independently;
        that amendment increments the subscriber's `version`."

        Design: Corner/endpoints/patching_a_subscriber_touches_only_the_supplied_fields
        """
        subscriber = _subscriber_with_known_contact(client)
        validate_success(
            client.amend_subscriber(
                subscriber["id"],
                subscriber_amendment_payload(contact_email="after@patch.example"),
                users.POLICY_ADMIN,
            )
        )

        amended = validate_success(
            client.amend_subscriber(
                subscriber["id"],
                subscriber_amendment_payload(credit_limit_cents=750000),
                users.POLICY_ADMIN,
            )
        )

        assert amended["credit_limit_cents"] == 750000, (
            f"credit_limit_cents is {amended['credit_limit_cents']}, expected 750000"
        )
        assert amended["contact_email"] == "after@patch.example", (
            "the email set by the previous amendment survives, found "
            f"{amended['contact_email']!r}"
        )
        assert amended["version"] == 3, (
            f"two amendments make version 3, found {amended['version']}"
        )
        reread = read_subscriber(client, subscriber["id"])
        assert reread["credit_limit_cents"] == 750000
        assert reread["contact_email"] == "after@patch.example"


class TestProfileActivationAction:
    def test_activation_stamps_the_clock_and_bumps_the_version(self, client):
        """The action endpoint is the only way out of DRAFT.

        PRD 3.1: "A new profile is born in `status` `DRAFT` and is inert."
        PRD 3.1: "Activation stamps `activated_at` with the logical clock and
        increments the profile's `version`."
        PRD 3.1: "`required_vetting_level` is computed directly from the tier: a
        `DV` profile requires `NONE`, an `OV` profile requires `OV`, and an `EV`
        profile requires `EV`."

        Design: Corner/endpoints/profile_activation_is_an_action_endpoint_with_its_own_not_found_path
        """
        draft = create_profile(
            client,
            ov_profile_payload(
                name="corner-activation-1",
                org_vetting_reuse_days=825,
                allowed_dcv_methods=[DCV_METHOD_DNS_TXT, DCV_METHOD_EMAIL_APPROVAL],
                required_sct_count=2,
            ),
            activate=False,
        )
        assert draft["status"] == PROFILE_STATE_DRAFT, (
            f"a new profile is a draft, found {draft['status']!r}"
        )
        assert_modifiable_identity(draft, expected_version=1)
        assert_nulls(draft, "activated_at", "retired_at")

        activated = validate_success(
            client.activate_profile(draft["id"], users.POLICY_ADMIN)
        )

        assert activated["status"] == PROFILE_STATE_ACTIVE, (
            f"activation moves the profile to ACTIVE, found {activated['status']!r}"
        )
        assert_instant_equals(
            activated["activated_at"], "2026-08-01T00:00:00Z", "activated_at"
        )
        assert activated["version"] == 2, (
            f"activation is one mutation, so version 2, found {activated['version']}"
        )
        assert activated["required_vetting_level"] == VETTING_LEVEL_OV

        _rows, meta = validate_paginated(
            client.list_profiles(users.POLICY_ADMIN, {"status": PROFILE_STATE_ACTIVE})
        )
        assert meta["total_count"] == 1, (
            f"exactly one active profile exists, found {meta['total_count']}"
        )

    def test_activating_an_identifier_that_resolves_to_nothing_is_a_404(self, client):
        """The action endpoint carries its own existence path.

        PRD 2.8: "The catalogue is `ERR_PROFILE_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_VETTING_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CERTIFICATE_NOT_FOUND`, `ERR_PARTITION_NOT_FOUND`,
        `ERR_CEREMONY_NOT_FOUND`, `ERR_REVOCATION_REQUEST_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND` and `ERR_AUDIT_NOT_FOUND`, all HTTP 404, and that
        listed order is also their relative precedence when two of them could fire
        on the same request."

        Design: Corner/endpoints/profile_activation_is_an_action_endpoint_with_its_own_not_found_path
        """
        create_profile(client, profile_payload(name="corner-activation-2"))

        validate_error(
            client.activate_profile(NON_EXISTENT_UUID, users.POLICY_ADMIN),
            ERR_PROFILE_NOT_FOUND,
        )

        _rows, meta = validate_paginated(
            client.list_profiles(users.POLICY_ADMIN, {"status": PROFILE_STATE_ACTIVE})
        )
        assert meta["total_count"] == 1, (
            "the failed activation created nothing, found "
            f"{meta['total_count']} active profiles"
        )


def _two_subscriber_xref(client):
    """One certificate for subscriber one, one cleared request for subscriber two."""
    profile = create_profile(
        client, profile_payload(base_fee_cents=20000, max_dcv_reuse_count=5)
    )
    other_profile = create_profile(client, profile_payload())
    subscriber_one = create_subscriber(client)
    subscriber_two = create_subscriber(client)
    partition = create_partition(client)
    ceremony = attested_ceremony(client, partition["id"])
    validated_authorization(
        client, subscriber_one["id"], profile["id"], "one.xref.example"
    )
    validated_authorization(
        client, subscriber_two["id"], profile["id"], "two.xref.example"
    )
    request_one = cleared_request(
        client, subscriber_one["id"], profile["id"], ["one.xref.example"]
    )
    certificate_one = issue_from_request(client, request_one["id"], ceremony["id"])
    request_two = cleared_request(
        client, subscriber_two["id"], profile["id"], ["two.xref.example"]
    )
    return {
        "profile": profile,
        "other_profile": other_profile,
        "subscriber_one": subscriber_one,
        "subscriber_two": subscriber_two,
        "ceremony": ceremony,
        "certificate_one": certificate_one,
        "request_two": request_two,
    }


class TestCrossReferenceBodies:
    def test_superseding_another_subscribers_certificate_is_refused(self, client):
        """A supersedes link may not cross an account boundary.

        PRD 3.7: "When `supersedes_certificate_id` is supplied, the certificate it
        names must belong to the same `subscriber_id` as the issuing request, or
        `ERR_SUPERSEDES_SUBSCRIBER_MISMATCH`."

        Design: Corner/endpoints/cross_reference_bodies_must_point_at_the_same_subscriber_and_profile
        """
        setup = _two_subscriber_xref(client)

        validate_error(
            client.issue_certificate(
                setup["request_two"]["id"],
                issue_payload(
                    setup["ceremony"]["id"],
                    supersedes_certificate_id=setup["certificate_one"]["id"],
                ),
                users.ISSUANCE_OPERATOR_9,
            ),
            ERR_SUPERSEDES_SUBSCRIBER_MISMATCH,
        )

        reread = read_request(client, setup["request_two"]["id"])
        assert reread["state"] == REQUEST_READY_TO_ISSUE, (
            f"the refused issuance leaves the request ready, found {reread['state']!r}"
        )
        assert_nulls(reread, "issued_certificate_id")
        _rows, meta = validate_paginated(
            client.list_certificates(
                users.ISSUANCE_OPERATOR_9,
                {"subscriber_id": setup["subscriber_two"]["id"]},
            )
        )
        assert meta["total_count"] == 0, (
            "subscriber two must still hold no certificate, found "
            f"{meta['total_count']}"
        )

    def test_linking_a_revocation_to_an_incident_scoped_elsewhere_is_refused(
        self, client
    ):
        """The incident's scoped profile must be the certificate's own profile.

        PRD 3.8: "When `incident_id` is supplied, the target certificate's
        `profile_id` must equal that incident's `scope_profile_id`, or the link is
        rejected with `ERR_INCIDENT_CERTIFICATE_MISMATCH`."

        Design: Corner/endpoints/cross_reference_bodies_must_point_at_the_same_subscriber_and_profile
        """
        setup = _two_subscriber_xref(client)
        certificate = setup["certificate_one"]
        foreign_incident = open_incident(
            client,
            setup["other_profile"]["id"],
            category=INCIDENT_PROCEDURAL,
            title="unrelated procedural lapse",
        )

        validate_error(
            client.raise_revocation(
                revocation_payload(
                    certificate["id"],
                    REASON_UNSPECIFIED,
                    certificate["version"],
                    incident_id=foreign_incident["id"],
                    evidence_ref="https://bugs.example/xref-1",
                ),
                users.REVOCATION_OFFICER,
            ),
            ERR_INCIDENT_CERTIFICATE_MISMATCH,
        )

        reread = read_certificate(client, certificate["id"])
        assert reread["revocation_status"] == REVOCATION_STATUS_NONE, (
            "a refused link never marks the certificate, found "
            f"{reread['revocation_status']!r}"
        )
        assert reread["version"] == certificate["version"], (
            f"version moved from {certificate['version']} to {reread['version']}"
        )
        _rows, meta = validate_paginated(
            client.list_revocations(
                users.REVOCATION_OFFICER, {"certificate_id": certificate["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"no revocation request may exist, found {meta['total_count']}"
        )


class TestCertificateRead:
    def test_the_read_exposes_the_sorted_method_set_and_the_final_window(self, client):
        """Both derived fields are computed by the server, not echoed from input.

        PRD 3.7: "`dcv_methods_used` records the distinct `method` values of the
        authorizations the originating request consumed, sorted ascending
        alphabetically."
        PRD 3.7: "`not_after` is the earliest of those three."
        PRD 3.7: "`validity_days_final` is then the number of whole days in the
        final window: the total seconds from `not_before` to `not_after` divided
        by 86,400 seconds per day, with any fraction discarded downward."

        Design: Corner/endpoints/certificate_read_exposes_the_derived_method_set_and_final_validity
        """
        profile = create_profile(
            client,
            profile_payload(
                base_fee_cents=20000,
                max_dcv_reuse_count=5,
                dcv_reuse_days=30,
                allowed_dcv_methods=[DCV_METHOD_DNS_TXT, DCV_METHOD_TLS_ALPN],
            ),
        )
        subscriber = create_subscriber(client)
        # Both proofs are answered before the ceremony window closes, so both
        # expire 30 days after the default clock.
        auth_www = validated_authorization(
            client,
            subscriber["id"],
            profile["id"],
            "www.methods.example",
            DCV_METHOD_TLS_ALPN,
        )
        validated_authorization(
            client,
            subscriber["id"],
            profile["id"],
            "api.methods.example",
            DCV_METHOD_DNS_TXT,
        )
        assert_instant_equals(
            auth_www["expires_at"], "2026-08-31T00:00:00Z", "authorization expires_at"
        )

        partition = create_partition(client)
        ceremony = attested_ceremony(client, partition["id"])
        request = cleared_request(
            client,
            subscriber["id"],
            profile["id"],
            ["www.methods.example", "api.methods.example"],
        )
        assert_instant_equals(
            request["projected_not_after"],
            plus_days(_ISSUANCE_CLOCK, 90),
            "projected_not_after",
        )
        issued = issue_from_request(client, request["id"], ceremony["id"])

        certificate = read_certificate(client, issued["id"])

        assert certificate["dcv_methods_used"] == [
            DCV_METHOD_DNS_TXT,
            DCV_METHOD_TLS_ALPN,
        ], (
            "the method set is deduplicated and sorted alphabetically, not left "
            f"in requested_domains order, found {certificate['dcv_methods_used']}"
        )
        assert_instant_equals(certificate["not_before"], _ISSUANCE_CLOCK, "not_before")
        assert_instant_equals(
            certificate["not_after"], "2026-08-31T00:00:00Z", "not_after"
        )
        assert certificate["not_after"] != request["projected_not_after"], (
            "the authorization reuse floor must beat the ninety-day profile cap"
        )
        assert certificate["validity_days_final"] == 29, (
            "29 days and 23 hours 30 minutes truncates to 29 whole days, found "
            f"{certificate['validity_days_final']}"
        )
        expected_charge = issuance_charge_cents(20000, VALIDATION_TYPE_DV, 2)
        assert expected_charge == 40000
        assert certificate["charged_amount_cents"] == expected_charge, (
            f"charged_amount_cents is {certificate['charged_amount_cents']}, "
            f"expected {expected_charge}"
        )
        assert_counters(certificate, sct_count=0)
        assert certificate["lifecycle_status"] == LIFECYCLE_PREISSUANCE
        assert certificate["request_id"] == request["id"]


class TestIncidentClose:
    def test_an_unsettled_linked_revocation_blocks_the_close_until_it_is_denied(
        self, client
    ):
        """Closing waits for every linked revocation to reach a terminal state.

        PRD 3.9: "A `COMPLIANCE_AUDITOR` closes an incident whose `state` is
        `DISCLOSED`, `MASS_REVOCATION_IN_PROGRESS` or `REMEDIATED` — anything
        else, including an `OPEN` incident, is `ERR_INCIDENT_NOT_CLOSEABLE` — and
        whose `remaining_scope_count` is 0 with every revocation request carrying
        this `incident_id` resolved to `EXECUTED` or `DENIED`; an unfinished tail
        is `ERR_INCIDENT_REVOCATIONS_OUTSTANDING`."
        PRD 3.8: "The target certificate returns `REVOCATION_PENDING → NONE`, but
        only when no other revocation request for it remains in `REQUESTED`; the
        subscriber's `revocation_pending_count` decrements by one, un-suspending
        the account once it is below 2."

        Design: Corner/endpoints/closing_an_incident_is_conditional_on_every_linked_revocation_being_settled
        """
        environment = build_environment(client)
        certificate = issue_certificate(client, environment)
        incident = disclosed_incident(
            client,
            environment.profile_id,
            category=INCIDENT_PROCEDURAL,
            scope_issued_from="2026-07-01T00:00:00Z",
            scope_issued_to="2026-07-31T00:00:00Z",
        )
        revocation = raise_revocation(
            client,
            certificate,
            REASON_UNSPECIFIED,
            incident_id=incident["id"],
            evidence_ref="https://bugs.example/close-1",
        )
        assert revocation["incident_id"] == incident["id"]

        validate_error(
            client.close_incident(incident["id"], users.COMPLIANCE_AUDITOR),
            ERR_INCIDENT_REVOCATIONS_OUTSTANDING,
        )
        blocked = read_incident(client, incident["id"])
        assert blocked["state"] == INCIDENT_DISCLOSED, (
            f"the refused close leaves the incident disclosed, found {blocked['state']!r}"
        )
        assert_counters(blocked, remaining_scope_count=0)
        assert_nulls(blocked, "closed_at")

        denied = validate_success(
            client.deny_revocation(
                revocation["id"],
                denial_payload("the certificate is outside the incident scope"),
                users.REVOCATION_OFFICER,
            )
        )
        assert denied["state"] == REVOCATION_DENIED, (
            f"denial is terminal, found {denied['state']!r}"
        )
        assert read_revocation(client, revocation["id"])["state"] == REVOCATION_DENIED

        closed = validate_success(
            client.close_incident(incident["id"], users.COMPLIANCE_AUDITOR)
        )
        assert closed["state"] == INCIDENT_CLOSED, (
            f"a settled tail unblocks the close, found {closed['state']!r}"
        )
        assert_instant_equals(closed["closed_at"], _ISSUANCE_CLOCK, "closed_at")
        assert (
            read_certificate(client, certificate["id"])["revocation_status"]
            == REVOCATION_STATUS_NONE
        ), "the denial released the certificate back to NONE"
