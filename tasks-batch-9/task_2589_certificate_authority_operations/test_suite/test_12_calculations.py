"""Arithmetic and selection formulas the PRD pins to the cent and the instant.

The issuance charge, the domain-authorization selection order, the incident
disclosure deadline, the revocation deadline caps and the half-open mass
revocation scope are all computed here from the PRD's own formulas and compared
against what the service reports.
"""

from test_helpers import (
    AUTH_EXHAUSTED,
    AUTH_VALIDATED,
    CLOCK_EPOCH,
    COMM_INCIDENT_DISCLOSURE,
    ERR_DOMAIN_AUTHORIZATION_EXPIRED,
    ERR_DOMAIN_AUTHORIZATION_MISSING,
    ERR_NO_CERTIFICATES_IN_SCOPE,
    INCIDENT_DISCLOSED,
    INCIDENT_DOMAIN_MISISSUANCE,
    INCIDENT_PROCEDURAL,
    INCIDENT_REMEDIATED,
    ORIGIN_COMPLIANCE,
    ORIGIN_MASS_REVOCATION,
    REASON_AFFILIATION_CHANGED,
    REQUEST_READY_TO_ISSUE,
    REQUEST_SUBMITTED,
    REVOCATION_EXECUTED,
    REVOCATION_REQUESTED,
    REVOCATION_STATUS_PENDING,
    REVOCATION_STATUS_REVOKED,
    ROOT_PROGRAM_MOZILLA,
    SUBSCRIBER_ACTIVE,
    VALIDATION_TYPE_DV,
    VALIDATION_TYPE_OV,
    VETTING_LEVEL_OV,
    advance_clock,
    approve_vetting_file,
    assert_counters,
    assert_instant_equals,
    assert_nulls,
    build_environment,
    cleared_request,
    create_authorization,
    create_profile,
    create_subscriber,
    disclosed_incident,
    disclosure_payload,
    get_success_data,
    issuance_charge_breakdown,
    issue_certificate,
    open_incident,
    ov_profile_payload,
    plus_hours,
    profile_payload,
    raise_revocation,
    read_authorization,
    read_certificate,
    read_incident,
    read_request,
    read_subscriber,
    remediation_penalty_for_certificate,
    revocation_deadline_at,
    submitted_request,
    users,
    validate_authorization,
    validate_error,
    validate_paginated,
    validate_payload,
    validate_success,
    validated_authorization,
)

# The recurring instant at which an attested ceremony's window closes, and so
# the clock at which the certificates below are cleared and issued.
_ISSUANCE_CLOCK = "2026-08-01T00:30:00Z"


class TestIssuanceChargeSteps:
    def test_volume_band_is_read_from_the_pre_discount_subtotal(self, client):
        """A subtotal of 49999 pays in full while 50000 earns ten percent.

        PRD 3.5: "Third, a volume discount percentage is read from the subtotal:
        a subtotal from 0 through 49,999 cents earns no discount, a subtotal
        from 50,000 through 149,999 cents earns 10 percent, and a subtotal of
        150,000 cents or more earns 20 percent."
        PRD 3.5: "The band is keyed on this pre-discount, pre-expedite subtotal
        and is never re-derived afterwards, even when the discounted subtotal or
        the final total would fall in a different band."

        Design: Corner/calculations/charge_volume_band_is_keyed_on_the_pre_discount_subtotal_at_the_49999_50000_edge
        """
        low_profile = create_profile(client, profile_payload(base_fee_cents=49999))
        high_profile = create_profile(client, profile_payload(base_fee_cents=25000))
        subscriber = create_subscriber(client)

        validated_authorization(
            client, subscriber["id"], low_profile["id"], "www.band.example"
        )
        validated_authorization(
            client, subscriber["id"], high_profile["id"], "www.band.example"
        )
        validated_authorization(
            client, subscriber["id"], high_profile["id"], "api.band.example"
        )

        low_request = cleared_request(
            client, subscriber["id"], low_profile["id"], ["www.band.example"]
        )
        high_request = cleared_request(
            client,
            subscriber["id"],
            high_profile["id"],
            ["www.band.example", "api.band.example"],
        )

        assert low_request["projected_charge_cents"] == 49999, (
            "a subtotal of 49999 sits in the no-discount band and must be "
            f"charged in full, found {low_request['projected_charge_cents']}"
        )
        high_breakdown = issuance_charge_breakdown(25000, VALIDATION_TYPE_DV, 2, False)
        assert high_breakdown["subtotal_cents"] == 50000
        assert high_breakdown["discount_percent"] == 10
        assert high_request["projected_charge_cents"] == 45000, (
            "a subtotal of exactly 50000 enters the ten percent band, so 45000, "
            f"found {high_request['projected_charge_cents']}"
        )
        assert high_request["projected_charge_cents"] == high_breakdown["total_cents"]
        assert low_request["state"] == REQUEST_READY_TO_ISSUE
        assert high_request["state"] == REQUEST_READY_TO_ISSUE

    def test_the_per_domain_unit_is_rounded_before_the_domain_count_multiplies_it(
        self, client
    ):
        """An OV unit of 15001.5 cents rounds to 15002 and then doubles.

        PRD 3.5: "First, the per-domain unit price is the profile's
        `base_fee_cents` multiplied by the validation-tier multiplier — 1.0 for a
        `DV` profile, 1.5 for an `OV` profile and 2.5 for an `EV` profile — with
        the product rounded half up to a whole cent at this point, before any
        multiplication by the domain count."
        PRD 3.5: "Rounding happens at the first, fourth and fifth steps only —
        rounding the base-fee-times-multiplier-times-domains product in one shot
        instead yields a different and incorrect subtotal whenever the unit price
        has a fractional part."

        Design: Corner/calculations/charge_rounds_the_per_domain_unit_before_multiplying_by_the_domain_count
        """
        profile = create_profile(client, ov_profile_payload(base_fee_cents=10001))
        subscriber = create_subscriber(client)
        approve_vetting_file(client, subscriber["id"], VETTING_LEVEL_OV)
        validated_authorization(
            client, subscriber["id"], profile["id"], "www.precision.example"
        )
        validated_authorization(
            client, subscriber["id"], profile["id"], "api.precision.example"
        )

        request = cleared_request(
            client,
            subscriber["id"],
            profile["id"],
            ["www.precision.example", "api.precision.example"],
        )

        breakdown = issuance_charge_breakdown(10001, VALIDATION_TYPE_OV, 2, False)
        assert breakdown["unit_cents"] == 15002, (
            f"the OV unit is round_half_up(15001.5) = 15002, not {breakdown['unit_cents']}"
        )
        assert breakdown["discount_percent"] == 0, (
            "the 30004 subtotal stays in the no-discount band"
        )
        assert request["projected_charge_cents"] == 30004, (
            "rounding the unit first gives 15002 x 2 = 30004, found "
            f"{request['projected_charge_cents']}"
        )
        assert request["projected_charge_cents"] != 30003, (
            "30003 is the total produced by rounding the whole product instead "
            "of the per-domain unit"
        )
        assert request["state"] == REQUEST_READY_TO_ISSUE


class TestAuthorizationSelection:
    def test_consumed_ids_follow_the_requested_domains_order_not_the_creation_order(
        self, client
    ):
        """Selection is indexed by the request array, not by proof age.

        PRD 3.5: "`consumed_authorization_ids` receives the selected
        authorization identifiers in `requested_domains` order, one per domain,
        and every selected authorization has its `reuse_count` incremented by
        one."

        Design: Corner/calculations/authorization_selection_follows_the_requested_domains_array_order
        """
        profile = create_profile(client, profile_payload(base_fee_cents=20000))
        subscriber = create_subscriber(client)

        # Created api-first, then www; answered in the opposite order.
        auth_api = create_authorization(
            client, subscriber["id"], profile["id"], "api.order.example"
        )
        auth_www = create_authorization(
            client, subscriber["id"], profile["id"], "www.order.example"
        )
        validate_authorization(client, auth_www)
        validate_authorization(client, auth_api)

        request = cleared_request(
            client,
            subscriber["id"],
            profile["id"],
            ["www.order.example", "api.order.example"],
        )

        assert request["consumed_authorization_ids"] == [
            auth_www["id"],
            auth_api["id"],
        ], (
            "consumed_authorization_ids must mirror requested_domains order, "
            f"found {request['consumed_authorization_ids']}"
        )
        for authorization in (auth_www, auth_api):
            reread = read_authorization(client, authorization["id"])
            assert_counters(reread, reuse_count=1)
            assert reread["state"] == AUTH_VALIDATED
        assert request["projected_charge_cents"] == 40000, (
            "two DV domains at 20000 cents each stay in the no-discount band, "
            f"so 40000, found {request['projected_charge_cents']}"
        )

    def test_an_exhausted_authorization_is_diagnosed_as_missing_not_expired(
        self, client
    ):
        """Three wrong tokens remove the proof from the candidate pool entirely.

        PRD 3.4: "If the incremented `attempt_count` reaches exactly 3, the
        authorization moves `FAILED → EXHAUSTED`, which is terminal: an exhausted
        authorization can never be validated, and the operator must open a fresh
        one."
        PRD 3.5: "If no authorization exists for that triple in either
        `VALIDATED` or `EXPIRED` state at all, the failure is
        `ERR_DOMAIN_AUTHORIZATION_MISSING`."

        Design: Corner/calculations/an_exhausted_authorization_is_never_a_selection_candidate
        """
        profile = create_profile(client, profile_payload(base_fee_cents=20000))
        subscriber = create_subscriber(client)
        authorization = create_authorization(
            client, subscriber["id"], profile["id"], "www.spent.example"
        )

        for attempt in (1, 2, 3):
            attempted = validate_success(
                client.validate_authorization(
                    authorization["id"],
                    validate_payload(f"definitely-not-the-token-{attempt}"),
                    users.VALIDATION_OFFICER,
                )
            )
            assert attempted["attempt_count"] == attempt, (
                "every attempt increments attempt_count, expected "
                f"{attempt}, found {attempted['attempt_count']}"
            )

        spent = read_authorization(client, authorization["id"])
        assert spent["state"] == AUTH_EXHAUSTED, (
            f"three misses must exhaust the authorization, found {spent['state']!r}"
        )
        assert_counters(spent, attempt_count=3, reuse_count=0)

        request = submitted_request(
            client, subscriber["id"], profile["id"], ["www.spent.example"]
        )
        error = validate_error(
            client.clear_validation(request["id"], users.VALIDATION_OFFICER),
            ERR_DOMAIN_AUTHORIZATION_MISSING,
        )
        assert error["error_id"] != ERR_DOMAIN_AUTHORIZATION_EXPIRED, (
            "an exhausted proof never counted as a lapsed proof, so the "
            f"diagnosis is missing, found {error['error_id']!r}"
        )

        reread = read_request(client, request["id"])
        assert reread["state"] == REQUEST_SUBMITTED, (
            f"the request must stay submitted, found {reread['state']!r}"
        )
        assert reread["consumed_authorization_ids"] == [], (
            "a failed clearance consumes nothing, found "
            f"{reread['consumed_authorization_ids']}"
        )
        assert_nulls(reread, "projected_charge_cents", "validation_cleared_at")


class TestDeadlineArithmetic:
    def test_disclosure_due_at_is_exactly_twenty_four_hours_after_discovery(
        self, client
    ):
        """The disclosure deadline is a fixed 24-hour offset from discovery.

        PRD 3.9: "Creation stamps `discovered_at` with the logical clock and sets
        `disclosure_due_at` to exactly 24 hours later, the root program
        disclosure deadline."
        PRD 3.9: "The incident moves `OPEN → DISCLOSED`, `disclosed_at` is
        stamped with the logical clock, and a root program communication is
        recorded with `kind` `INCIDENT_DISCLOSURE`, its `incident_id` set, its
        `audit_id` null, its `sent_at` at the logical clock, its
        `sent_by_user_id` taken from `X-User-ID`, and `within_deadline` true when
        `sent_at` is at or before `disclosure_due_at` — a disclosure landing
        exactly on the deadline instant is on time."

        Design: Corner/calculations/incident_disclosure_due_at_is_discovered_at_plus_twenty_four_hours
        """
        profile = create_profile(client)
        incident = open_incident(
            client, profile["id"], category=INCIDENT_PROCEDURAL, title="late CRL refresh"
        )

        assert_instant_equals(incident["discovered_at"], CLOCK_EPOCH, "discovered_at")
        assert_instant_equals(
            incident["disclosure_due_at"],
            plus_hours(CLOCK_EPOCH, 24),
            "disclosure_due_at",
        )
        assert_instant_equals(
            incident["disclosure_due_at"], "2026-08-02T00:00:00Z", "disclosure_due_at"
        )

        advance_clock(client, "2026-08-01T12:00:00Z")
        disclosed = get_success_data(
            client.disclose_incident(
                incident["id"],
                disclosure_payload(root_program=ROOT_PROGRAM_MOZILLA),
                users.COMPLIANCE_AUDITOR,
            )
        )

        assert disclosed["state"] == INCIDENT_DISCLOSED, (
            f"disclosure moves the incident to DISCLOSED, found {disclosed['state']!r}"
        )
        assert disclosed["disclosure_breached"] is False, (
            "a disclosure 12 hours into a 24-hour window is not a breach"
        )
        assert_instant_equals(
            disclosed["disclosed_at"], "2026-08-01T12:00:00Z", "disclosed_at"
        )

        rows, meta = validate_paginated(
            client.list_incident_communications(
                incident["id"], users.COMPLIANCE_AUDITOR
            )
        )
        assert meta["total_count"] == 1, (
            f"one disclosure records one communication, found {meta['total_count']}"
        )
        communication = rows[0]
        assert communication["kind"] == COMM_INCIDENT_DISCLOSURE
        assert communication["root_program"] == ROOT_PROGRAM_MOZILLA
        assert communication["incident_id"] == incident["id"]
        assert_nulls(communication, "audit_id")
        assert communication["within_deadline"] is True, (
            "sent_at 12 hours before disclosure_due_at is within the deadline"
        )
        assert_instant_equals(
            communication["sent_at"], "2026-08-01T12:00:00Z", "sent_at"
        )
        assert (
            communication["sent_by_user_id"]
            == users.COMPLIANCE_AUDITOR["X-User-ID"]
        )

    def test_an_incident_link_caps_a_120_hour_reason_at_24_hours(self, client):
        """AFFILIATION_CHANGED buys 120 hours until an incident is named.

        PRD 3.8: "The base allowance comes from the reason code: 24 hours for
        `KEY_COMPROMISE` and for `PRIVILEGE_WITHDRAWN`, and 120 hours for
        `AFFILIATION_CHANGED`, `SUPERSEDED`, `CESSATION_OF_OPERATION` and
        `UNSPECIFIED`."
        PRD 3.8: "An incident-linked cap of 24 hours applies when the request
        carries an `incident_id`; when it does not, the incident cap contributes
        the base allowance itself and so never binds."
        PRD 3.8: "The presence of the link also decides provenance: `origin` is
        set to `SUBSCRIBER` when `incident_id` is absent and to `COMPLIANCE` when
        it is present."

        Design: Corner/calculations/linking_a_revocation_to_an_incident_caps_the_deadline_at_twenty_four_hours
        """
        environment = build_environment(client)
        certificate = issue_certificate(client, environment)
        assert_instant_equals(
            certificate["not_before"], _ISSUANCE_CLOCK, "certificate not_before"
        )

        incident = open_incident(
            client,
            environment.profile_id,
            category=INCIDENT_DOMAIN_MISISSUANCE,
            title="name issued outside the validated scope",
        )
        revocation = raise_revocation(
            client,
            certificate,
            REASON_AFFILIATION_CHANGED,
            incident_id=incident["id"],
            evidence_ref="https://bugs.example/incident-cap-1",
        )

        expected = revocation_deadline_at(
            _ISSUANCE_CLOCK, REASON_AFFILIATION_CHANGED, linked_to_incident=True
        )
        assert_instant_equals(expected, "2026-08-02T00:30:00Z", "expected deadline")
        assert_instant_equals(revocation["deadline_at"], expected, "deadline_at")
        assert revocation["deadline_at"] != plus_hours(_ISSUANCE_CLOCK, 120), (
            "the incident cap must beat the 120-hour base allowance, found "
            f"{revocation['deadline_at']}"
        )
        assert revocation["origin"] == ORIGIN_COMPLIANCE, (
            f"a linked request originates with compliance, found {revocation['origin']!r}"
        )
        assert revocation["deadline_breached"] is False
        assert revocation["state"] == REVOCATION_REQUESTED
        assert revocation["incident_id"] == incident["id"]

        reread = read_certificate(client, certificate["id"])
        assert reread["revocation_status"] == REVOCATION_STATUS_PENDING, (
            "raising a request marks the certificate pending, found "
            f"{reread['revocation_status']!r}"
        )


class TestMassRevocationScope:
    def test_the_scope_window_excludes_its_upper_bound_and_includes_its_lower(
        self, client
    ):
        """A certificate at the boundary belongs to the batch that starts on it.

        PRD 3.9: "The candidate pool is every certificate whose `profile_id`
        equals the incident's `scope_profile_id`, whose `revocation_status` is
        `NONE`, whose `lifecycle_status` is `PREISSUANCE` or `ISSUED`, whose
        `not_before` falls in the half-open window from `scope_issued_from`
        inclusive to `scope_issued_to` exclusive, and — when `scope_dcv_method` is
        set — whose `dcv_methods_used` contains that method."
        PRD 3.9: "An empty pool is refused with `ERR_NO_CERTIFICATES_IN_SCOPE`."
        PRD 3.9: "The per-certificate penalty is 1000 cents multiplied by the
        category penalty weight — 3.0 for `KEY_COMPROMISE`, 2.0 for
        `DOMAIN_MISISSUANCE`, 1.5 for `ORG_MISISSUANCE`, 0.5 for `PROCEDURAL` —
        multiplied by that residual fraction."

        Design: Corner/calculations/mass_revocation_scope_is_half_open_at_the_upper_bound
        """
        environment = build_environment(client)
        certificate = issue_certificate(client, environment)
        assert_instant_equals(
            certificate["not_before"], _ISSUANCE_CLOCK, "certificate not_before"
        )

        # The certificate's not_before is this window's excluded upper bound.
        excluding = disclosed_incident(
            client,
            environment.profile_id,
            category=INCIDENT_DOMAIN_MISISSUANCE,
            scope_issued_from=CLOCK_EPOCH,
            scope_issued_to=_ISSUANCE_CLOCK,
        )
        validate_error(
            client.mass_revoke(excluding["id"], users.REVOCATION_OFFICER),
            ERR_NO_CERTIFICATES_IN_SCOPE,
        )
        untouched = read_incident(client, excluding["id"])
        assert untouched["state"] == INCIDENT_DISCLOSED, (
            "a refused batch leaves the incident disclosed, found "
            f"{untouched['state']!r}"
        )
        assert_counters(
            untouched, revoked_certificate_count=0, penalty_total_cents=0
        )

        # The same instant is the included lower bound of this window.
        including = disclosed_incident(
            client,
            environment.profile_id,
            category=INCIDENT_DOMAIN_MISISSUANCE,
            scope_issued_from=_ISSUANCE_CLOCK,
            scope_issued_to="2026-08-01T00:31:00Z",
        )
        remediated = get_success_data(
            client.mass_revoke(including["id"], users.REVOCATION_OFFICER)
        )

        assert remediated["state"] == INCIDENT_REMEDIATED, (
            "draining the pool in one batch remediates the incident, found "
            f"{remediated['state']!r}"
        )
        expected_penalty = remediation_penalty_for_certificate(
            INCIDENT_DOMAIN_MISISSUANCE,
            _ISSUANCE_CLOCK,
            certificate["not_before"],
            certificate["not_after"],
        )
        assert expected_penalty == 2000, (
            "a full residual fraction on a domain-misissuance incident is "
            f"1000 x 2.0 = 2000 cents, computed {expected_penalty}"
        )
        assert_counters(
            remediated,
            revoked_certificate_count=1,
            remaining_scope_count=0,
            penalty_total_cents=expected_penalty,
        )

        revoked = read_certificate(client, certificate["id"])
        assert revoked["revocation_status"] == REVOCATION_STATUS_REVOKED, (
            f"the scoped certificate is revoked, found {revoked['revocation_status']!r}"
        )
        assert_instant_equals(revoked["revoked_at"], _ISSUANCE_CLOCK, "revoked_at")

        rows, meta = validate_paginated(
            client.list_revocations(
                users.COMPLIANCE_AUDITOR, {"incident_id": including["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the batch raises one revocation request, found {meta['total_count']}"
        )
        assert rows[0]["origin"] == ORIGIN_MASS_REVOCATION
        assert rows[0]["state"] == REVOCATION_EXECUTED
        assert rows[0]["certificate_id"] == certificate["id"], (
            "the batch targets the scoped certificate, found "
            f"{rows[0]['certificate_id']}"
        )

        subscriber = read_subscriber(client, environment.subscriber_id)
        assert subscriber["account_status"] == SUBSCRIBER_ACTIVE, (
            "a batch that settles immediately never suspends the account, found "
            f"{subscriber['account_status']!r}"
        )
        assert_counters(subscriber, revocation_pending_count=0)
