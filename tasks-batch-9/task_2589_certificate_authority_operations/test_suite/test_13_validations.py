"""Input and policy validations the PRD states as named rejections.

Every check here is a gate the PRD spells out: which validation techniques a
profile tolerates, when organizational vetting is required and how long it stays
usable, how the key-strength minimum is read from the tier, which uniqueness
constraints are enforced, and the order in which competing gates fire.
"""

from test_helpers import (
    AUTH_PENDING,
    AUTH_VALIDATED,
    CLOCK_EPOCH,
    DCV_METHOD_DNS_TXT,
    DCV_METHOD_HTTP_TOKEN,
    DCV_METHOD_TLS_ALPN,
    ERR_CEREMONY_NOT_ATTESTED_FOR_ISSUANCE,
    ERR_CEREMONY_NOT_FOUND,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_CSR_KEY_TOO_WEAK,
    ERR_DCV_METHOD_NOT_ALLOWED,
    ERR_ORG_VETTING_LEVEL_INSUFFICIENT,
    ERR_ORG_VETTING_REQUIRED,
    ERR_ORG_VETTING_REUSE_EXPIRED,
    ERR_PARTITION_SERIAL_DUPLICATE,
    ERR_PROFILE_NAME_DUPLICATE,
    ERR_SUBSCRIBER_REGISTRY_DUPLICATE,
    LIFECYCLE_PREISSUANCE,
    NON_EXISTENT_UUID,
    REQUEST_READY_TO_ISSUE,
    REQUEST_SUBMITTED,
    VALIDATION_TYPE_EV,
    VETTING_APPROVED,
    VETTING_LEVEL_EV,
    VETTING_LEVEL_NONE,
    VETTING_LEVEL_OV,
    advance_clock,
    approve_vetting_file,
    assert_counters,
    assert_instant_equals,
    assert_nulls,
    authorization_payload,
    build_environment,
    cleared_request,
    create_authorization,
    create_partition,
    create_profile,
    create_subscriber,
    ev_profile_payload,
    get_success_data,
    issuance_charge_cents,
    issue_payload,
    ov_profile_payload,
    partition_payload,
    plus_days,
    profile_payload,
    read_authorization,
    read_ceremony,
    read_certificate,
    read_profile,
    read_request,
    read_subscriber,
    schedule_ceremony,
    submitted_request,
    subscriber_payload,
    users,
    validate_authorization,
    validate_error,
    validate_paginated,
    validate_success,
    validated_authorization,
)


class TestDcvMethodAllowList:
    def test_a_method_the_profile_never_approved_is_refused(self, client):
        """An HTTP token challenge cannot be opened under a DNS-only profile.

        PRD 3.4: "The method must be one of `DNS_TXT`, `HTTP_TOKEN`,
        `EMAIL_APPROVAL` or `TLS_ALPN`, and it must additionally appear in the
        named profile's `allowed_dcv_methods`; a technique the profile has not
        approved is rejected with `ERR_DCV_METHOD_NOT_ALLOWED`."

        Design: Corner/validations/dcv_method_outside_the_profile_allow_list_is_rejected
        """
        profile = create_profile(
            client, profile_payload(allowed_dcv_methods=[DCV_METHOD_DNS_TXT])
        )
        subscriber = create_subscriber(client)

        error = validate_error(
            client.create_authorization(
                authorization_payload(
                    subscriber["id"],
                    profile["id"],
                    "www.allowlist.example",
                    DCV_METHOD_HTTP_TOKEN,
                ),
                users.VALIDATION_OFFICER,
            ),
            ERR_DCV_METHOD_NOT_ALLOWED,
        )
        assert error["error_id"] == ERR_DCV_METHOD_NOT_ALLOWED, (
            "HTTP_TOKEN is a declared enum member, so the rejection is the "
            f"policy allow list and not a schema error, found {error['error_id']!r}"
        )

        rows, meta = validate_paginated(
            client.list_authorizations(
                users.VALIDATION_OFFICER, {"subscriber_id": subscriber["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"a refused challenge is never stored, found {meta['total_count']} rows"
        )
        assert rows == []

    def test_an_approved_method_opens_a_reuse_window_of_dcv_reuse_days(self, client):
        """A TLS_ALPN proof is accepted and expires thirty days after success.

        PRD 3.4: "Creation mints a `challenge_token` — a server-generated value,
        deterministic per authorization, which is returned in the response and
        which the applicant must echo back — and initialises `state` to `PENDING`
        with `attempt_count`, `reuse_count` and `invalidation_count` all at 0 and
        `validated_at`, `expires_at` and `invalidated_at` all null."
        PRD 3.4: "Success stamps `validated_at` with the logical clock and sets
        `expires_at` to `validated_at` plus the profile's `dcv_reuse_days` in
        days."

        Design: Corner/validations/an_allowed_dcv_method_is_accepted_and_opens_a_thirty_day_reuse_window
        """
        profile = create_profile(
            client,
            profile_payload(
                allowed_dcv_methods=[DCV_METHOD_DNS_TXT, DCV_METHOD_TLS_ALPN],
                dcv_reuse_days=30,
            ),
        )
        subscriber = create_subscriber(client)

        pending = create_authorization(
            client,
            subscriber["id"],
            profile["id"],
            "www.alpn.example",
            DCV_METHOD_TLS_ALPN,
        )
        assert pending["state"] == AUTH_PENDING, (
            f"a fresh challenge is pending, found {pending['state']!r}"
        )
        assert isinstance(pending["challenge_token"], str) and pending[
            "challenge_token"
        ].strip(), (
            f"challenge_token must be a non-empty string, found {pending['challenge_token']!r}"
        )
        assert_nulls(pending, "validated_at", "expires_at", "invalidated_at")
        assert_counters(
            pending, attempt_count=0, reuse_count=0, invalidation_count=0
        )

        validated = validate_authorization(client, pending)

        assert validated["state"] == AUTH_VALIDATED, (
            f"echoing the minted token validates the proof, found {validated['state']!r}"
        )
        assert validated["method"] == DCV_METHOD_TLS_ALPN
        assert_instant_equals(validated["validated_at"], CLOCK_EPOCH, "validated_at")
        assert_instant_equals(
            validated["expires_at"], plus_days(CLOCK_EPOCH, 30), "expires_at"
        )
        assert_instant_equals(
            validated["expires_at"], "2026-08-31T00:00:00Z", "expires_at"
        )
        assert_counters(validated, attempt_count=1, reuse_count=0)


class TestOrganizationalVettingGate:
    def test_a_dv_profile_clears_without_vetting_while_an_ov_profile_cannot(
        self, client
    ):
        """The same unvetted subscriber passes one tier and fails the other.

        PRD 3.5: "Organizational vetting is checked next, and only when the
        profile's `required_vetting_level` is not `NONE` — a `DV` profile skips
        this block entirely."
        PRD 3.5: "The subscriber must hold a vetting file in `vetting_state`
        `APPROVED`, or `ERR_ORG_VETTING_REQUIRED` is raised."
        PRD 3.1: "`required_vetting_level` is computed directly from the tier: a
        `DV` profile requires `NONE`, an `OV` profile requires `OV`, and an `EV`
        profile requires `EV`."

        Design: Corner/validations/organization_vetting_is_required_only_for_ov_and_ev_profiles
        """
        dv_profile = create_profile(client, profile_payload(base_fee_cents=20000))
        ov_profile = create_profile(client, ov_profile_payload(base_fee_cents=20000))
        subscriber = create_subscriber(client)

        assert dv_profile["required_vetting_level"] == VETTING_LEVEL_NONE, (
            "a DV profile requires no organizational vetting, found "
            f"{dv_profile['required_vetting_level']!r}"
        )
        assert ov_profile["required_vetting_level"] == VETTING_LEVEL_OV, (
            f"an OV profile requires OV, found {ov_profile['required_vetting_level']!r}"
        )

        validated_authorization(
            client, subscriber["id"], dv_profile["id"], "www.tiers.example"
        )
        validated_authorization(
            client, subscriber["id"], ov_profile["id"], "www.tiers.example"
        )
        dv_request = submitted_request(
            client, subscriber["id"], dv_profile["id"], ["www.tiers.example"]
        )
        ov_request = submitted_request(
            client, subscriber["id"], ov_profile["id"], ["www.tiers.example"]
        )

        cleared = validate_success(
            client.clear_validation(dv_request["id"], users.VALIDATION_OFFICER)
        )
        assert cleared["state"] == REQUEST_READY_TO_ISSUE, (
            "an unvetted subscriber may still clear a DV request, found "
            f"{cleared['state']!r}"
        )
        assert cleared["projected_charge_cents"] == 20000, (
            "one DV domain at 20000 cents stays in the no-discount band, found "
            f"{cleared['projected_charge_cents']}"
        )

        validate_error(
            client.clear_validation(ov_request["id"], users.VALIDATION_OFFICER),
            ERR_ORG_VETTING_REQUIRED,
        )
        blocked = read_request(client, ov_request["id"])
        assert blocked["state"] == REQUEST_SUBMITTED, (
            f"the OV request must stay submitted, found {blocked['state']!r}"
        )
        assert blocked["consumed_authorization_ids"] == []
        assert_nulls(blocked, "projected_charge_cents", "validation_cleared_at")


class TestKeyStrengthAndVettingPrecedence:
    def test_the_key_minimum_rises_with_the_ev_tier(self, client):
        """2048 bits clears a DV or OV profile but never an EV one.

        PRD 3.5: "Finally the request's `csr_key_bits` must meet the tier's
        key-strength minimum: `DV` and `OV` profiles require at least 2048 bits,
        while an `EV` profile requires at least 3072, so a 2048-bit key against an
        `EV` profile is rejected with `ERR_CSR_KEY_TOO_WEAK`."

        Design: Corner/validations/csr_key_minimum_is_read_from_the_profile_validation_type
        """
        profile = create_profile(client, ev_profile_payload(base_fee_cents=20000))
        subscriber = create_subscriber(client)
        approve_vetting_file(client, subscriber["id"], VETTING_LEVEL_EV)
        authorization = validated_authorization(
            client, subscriber["id"], profile["id"], "www.keybits.example"
        )

        weak_request = submitted_request(
            client, subscriber["id"], profile["id"], ["www.keybits.example"], 90, 2048
        )
        strong_request = submitted_request(
            client, subscriber["id"], profile["id"], ["www.keybits.example"], 90, 3072
        )

        validate_error(
            client.clear_validation(weak_request["id"], users.VALIDATION_OFFICER),
            ERR_CSR_KEY_TOO_WEAK,
        )
        assert read_request(client, weak_request["id"])["state"] == REQUEST_SUBMITTED, (
            "a rejected clearance leaves the request submitted"
        )
        assert_counters(read_authorization(client, authorization["id"]), reuse_count=0)

        cleared = validate_success(
            client.clear_validation(strong_request["id"], users.VALIDATION_OFFICER)
        )
        assert cleared["state"] == REQUEST_READY_TO_ISSUE, (
            f"3072 bits satisfies the EV minimum, found {cleared['state']!r}"
        )
        expected_charge = issuance_charge_cents(20000, VALIDATION_TYPE_EV, 1)
        assert expected_charge == 45000, (
            "the EV multiplier lifts the subtotal to 50000, which the ten "
            f"percent band discounts to 45000, computed {expected_charge}"
        )
        assert cleared["projected_charge_cents"] == expected_charge, (
            f"projected_charge_cents is {cleared['projected_charge_cents']}, "
            f"expected {expected_charge}"
        )
        assert_counters(read_authorization(client, authorization["id"]), reuse_count=1)

    def test_the_vetting_level_gate_fires_before_the_key_strength_gate(self, client):
        """An OV file against an EV profile masks a 2048-bit key entirely.

        PRD 3.5: "That file's `required_level` must cover the profile's
        `required_vetting_level` under the ordering where `NONE` is weaker than
        `OV`, which is weaker than `EV`; an `OV` vetting therefore never satisfies
        an `EV` profile, and the mismatch is
        `ERR_ORG_VETTING_LEVEL_INSUFFICIENT`."
        PRD 3.5: "These four gates are evaluated in exactly the order just given,
        after the three domain-authorization diagnoses."

        Design: Corner/validations/insufficient_vetting_level_outranks_the_weak_key_check
        """
        profile = create_profile(client, ev_profile_payload(base_fee_cents=20000))
        subscriber = create_subscriber(client)
        vetting = approve_vetting_file(client, subscriber["id"], VETTING_LEVEL_OV)
        validated_authorization(
            client, subscriber["id"], profile["id"], "www.outranked.example"
        )
        request = submitted_request(
            client,
            subscriber["id"],
            profile["id"],
            ["www.outranked.example"],
            90,
            2048,
        )

        error = validate_error(
            client.clear_validation(request["id"], users.VALIDATION_OFFICER),
            ERR_ORG_VETTING_LEVEL_INSUFFICIENT,
        )
        assert error["error_id"] != ERR_CSR_KEY_TOO_WEAK, (
            "the vetting-level gate precedes the key-strength gate, so the weak "
            f"key must stay hidden, found {error['error_id']!r}"
        )

        reread_vetting = get_success_data(
            client.get_vetting(vetting["id"], users.VALIDATION_OFFICER)
        )
        assert reread_vetting["vetting_state"] == VETTING_APPROVED, (
            "a refused clearance does not disturb the vetting file, found "
            f"{reread_vetting['vetting_state']!r}"
        )
        assert reread_vetting["required_level"] == VETTING_LEVEL_OV
        assert read_request(client, request["id"])["state"] == REQUEST_SUBMITTED

    def test_a_vetting_older_than_the_reuse_period_stops_clearing_requests(
        self, client
    ):
        """A one-day reuse period lapses two days after approval.

        PRD 3.5: "The file's `approved_at` must be strictly later than the
        logical clock minus the profile's `org_vetting_reuse_days` in days, so a
        vetting exactly at the edge of its reuse period has already lapsed; a
        stale vetting is `ERR_ORG_VETTING_REUSE_EXPIRED`."
        PRD 3.3: "That `approved_at` instant is what starts the organizational
        vetting reuse window, whose length each profile bounds independently with
        its own `org_vetting_reuse_days`."

        Design: Corner/validations/an_approved_vetting_outside_the_reuse_window_is_no_longer_usable
        """
        profile = create_profile(
            client, ov_profile_payload(base_fee_cents=20000, org_vetting_reuse_days=1)
        )
        subscriber = create_subscriber(client)
        vetting = approve_vetting_file(client, subscriber["id"], VETTING_LEVEL_OV)
        assert_instant_equals(vetting["approved_at"], CLOCK_EPOCH, "approved_at")
        authorization = validated_authorization(
            client, subscriber["id"], profile["id"], "www.stale.example"
        )
        request = submitted_request(
            client, subscriber["id"], profile["id"], ["www.stale.example"]
        )

        advance_clock(client, "2026-08-03T00:00:00Z")
        validate_error(
            client.clear_validation(request["id"], users.VALIDATION_OFFICER),
            ERR_ORG_VETTING_REUSE_EXPIRED,
        )

        reread_vetting = get_success_data(
            client.get_vetting(vetting["id"], users.VALIDATION_OFFICER)
        )
        assert reread_vetting["vetting_state"] == VETTING_APPROVED, (
            "the file is stale for this profile, not withdrawn, found "
            f"{reread_vetting['vetting_state']!r}"
        )
        reread_auth = read_authorization(client, authorization["id"])
        assert reread_auth["state"] == AUTH_VALIDATED, (
            "the domain proof has its own thirty-day window and is untouched, "
            f"found {reread_auth['state']!r}"
        )
        assert_instant_equals(
            reread_auth["expires_at"], "2026-08-31T00:00:00Z", "expires_at"
        )
        assert_counters(reread_auth, reuse_count=0)


class TestExistenceBeforeState:
    def test_an_unknown_ceremony_is_a_404_while_a_scheduled_one_is_a_409(self, client):
        """Resolving the named ceremony precedes judging its state.

        PRD 2.8: "Precedence is global across the whole API, not per endpoint, and
        it runs in the following bands from highest to lowest."
        PRD 2.8: "A profile referenced through `profile_id` or
        `scope_profile_id`, a subscriber referenced through `subscriber_id`, a
        certificate referenced through `certificate_id` or
        `supersedes_certificate_id`, a ceremony referenced through `ceremony_id`
        and an incident referenced through `incident_id` are all checked under
        this band exactly as if they had been path segments."
        PRD 3.7: "The named ceremony must be in state `ATTESTED`, or
        `ERR_CEREMONY_NOT_ATTESTED_FOR_ISSUANCE`; and its
        `attestation_expires_at` must be strictly after the logical clock, or
        `ERR_CEREMONY_ATTESTATION_EXPIRED`."

        Design: Corner/validations/ceremony_existence_is_checked_before_ceremony_state_on_issue
        """
        profile = create_profile(client, profile_payload(base_fee_cents=20000))
        subscriber = create_subscriber(client)
        validated_authorization(
            client, subscriber["id"], profile["id"], "www.ordering.example"
        )
        request = cleared_request(
            client, subscriber["id"], profile["id"], ["www.ordering.example"]
        )
        partition = create_partition(client)
        ceremony = schedule_ceremony(client, partition["id"])

        validate_error(
            client.issue_certificate(
                request["id"],
                issue_payload(NON_EXISTENT_UUID),
                users.ISSUANCE_OPERATOR_3,
            ),
            ERR_CEREMONY_NOT_FOUND,
        )
        validate_error(
            client.issue_certificate(
                request["id"],
                issue_payload(ceremony["id"]),
                users.ISSUANCE_OPERATOR_3,
            ),
            ERR_CEREMONY_NOT_ATTESTED_FOR_ISSUANCE,
        )

        reread = read_request(client, request["id"])
        assert reread["state"] == REQUEST_READY_TO_ISSUE, (
            f"neither refusal advances the request, found {reread['state']!r}"
        )
        assert_nulls(reread, "issued_certificate_id")

        _rows, meta = validate_paginated(
            client.list_certificates(
                users.ISSUANCE_OPERATOR_3, {"request_id": request["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"no certificate may exist yet, found {meta['total_count']}"
        )
        assert_counters(
            read_ceremony(client, ceremony["id"]), issued_certificate_count=0
        )


class TestClockMonotonicity:
    def test_a_backwards_advance_is_refused_and_an_equal_one_is_a_no_op(self, client):
        """The clock accepts the instant it already holds but nothing earlier.

        PRD 2.6: "The clock may only move forward: a submitted `current_utc`
        earlier than the server's current logical clock is rejected with
        `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while a `current_utc` exactly equal
        to the current clock is accepted and is a no-op advance."

        Design: Corner/validations/the_logical_clock_never_moves_backwards
        """
        advance_clock(client, "2026-08-05T00:00:00Z")

        validate_error(
            client.set_clock("2026-08-04T00:00:00Z", users.POLICY_ADMIN),
            ERR_CLOCK_NOT_MONOTONIC,
        )
        validate_success(
            client.set_clock("2026-08-05T00:00:00Z", users.POLICY_ADMIN)
        )

        profile = create_profile(client, profile_payload())
        assert_instant_equals(
            profile["created_at"], "2026-08-05T00:00:00Z", "created_at"
        )
        assert_instant_equals(
            read_profile(client, profile["id"])["activated_at"],
            "2026-08-05T00:00:00Z",
            "activated_at",
        )


class TestUniquenessConstraints:
    def test_profile_names_collide_after_case_folding(self, client):
        """Changing only the letter case does not make a new profile name.

        PRD 3.1: "A `POLICY_ADMIN` drafts a profile by supplying a `name` of
        between 1 and 80 characters that is unique across all profiles after
        case-folding — a second profile whose name differs only in letter case is
        rejected with `ERR_PROFILE_NAME_DUPLICATE` — together with a
        `validation_type` of `DV`, `OV` or `EV`, which is the validation tier the
        profile issues under and the single most consequential choice on the
        record."

        Design: Corner/validations/uniqueness_is_enforced_on_profile_name_registry_pair_and_partition_serial
        """
        create_profile(client, profile_payload(name="corner-uniq-a"))

        validate_error(
            client.create_profile(
                profile_payload(name="CORNER-UNIQ-A"), users.POLICY_ADMIN
            ),
            ERR_PROFILE_NAME_DUPLICATE,
        )

        _rows, meta = validate_paginated(client.list_profiles(users.POLICY_ADMIN))
        assert meta["total_count"] == 1, (
            f"the rejected draft must not be stored, found {meta['total_count']} profiles"
        )

    def test_the_registry_pair_is_unique_but_either_half_may_repeat(self, client):
        """Only the jurisdiction and registry identifier together must be unique.

        PRD 3.2: "The pair of `jurisdiction_code` and `registry_id` must be
        unique across all subscribers; a duplicate pair is rejected with
        `ERR_SUBSCRIBER_REGISTRY_DUPLICATE`."

        Design: Corner/validations/uniqueness_is_enforced_on_profile_name_registry_pair_and_partition_serial
        """
        first = create_subscriber(
            client,
            subscriber_payload(jurisdiction_code="USDE", registry_id="REG-2029"),
        )

        validate_error(
            client.create_subscriber(
                subscriber_payload(
                    jurisdiction_code="USDE", registry_id="REG-2029"
                ),
                users.POLICY_ADMIN,
            ),
            ERR_SUBSCRIBER_REGISTRY_DUPLICATE,
        )

        second = get_success_data(
            client.create_subscriber(
                subscriber_payload(
                    jurisdiction_code="USNY", registry_id="REG-2029"
                ),
                users.POLICY_ADMIN,
            ),
            201,
        )
        assert second["id"] != first["id"], (
            "the same registry identifier in another jurisdiction is a distinct "
            "applicant and must be accepted"
        )

        _rows, meta = validate_paginated(client.list_subscribers(users.POLICY_ADMIN))
        assert meta["total_count"] == 2, (
            f"exactly two subscribers may exist, found {meta['total_count']}"
        )

    def test_a_partition_serial_may_never_repeat(self, client):
        """Two partitions cannot claim the same piece of hardware.

        PRD 3.6: "A `POLICY_ADMIN` registers an **HSM partition** with an
        operator-facing `label` of 1 to 60 characters and a hardware `serial` of 1
        to 40 characters that must be unique across all partitions; a repeat
        serial is rejected with `ERR_PARTITION_SERIAL_DUPLICATE`."

        Design: Corner/validations/uniqueness_is_enforced_on_profile_name_registry_pair_and_partition_serial
        """
        create_partition(client, partition_payload(serial="HSM-2029"))

        validate_error(
            client.create_partition(
                partition_payload(label="part-duplicate", serial="HSM-2029"),
                users.POLICY_ADMIN,
            ),
            ERR_PARTITION_SERIAL_DUPLICATE,
        )

        _rows, meta = validate_paginated(client.list_partitions(users.POLICY_ADMIN))
        assert meta["total_count"] == 1, (
            f"the rejected registration must not be stored, found {meta['total_count']}"
        )


class TestCreditLimitGate:
    def test_two_affordable_issuances_together_exceed_the_limit(self, client):
        """The gate compares the running balance, not one charge in isolation.

        PRD 3.7: "Last of all comes the fiscal gate: the subscriber's
        `outstanding_balance_cents` plus the settlement total for this issuance
        must be at most `credit_limit_cents`, and exceeding it is
        `ERR_CREDIT_LIMIT_EXCEEDED` with HTTP 402."
        PRD 3.7: "Issuance then debits the subscriber: `outstanding_balance_cents`
        rises by `charged_amount_cents` and `issued_certificate_count` rises by
        one, with the subscriber's `version` incrementing."

        Design: Corner/validations/individually_affordable_issuances_can_breach_the_credit_limit_together
        """
        environment = build_environment(
            client,
            profile_payload(base_fee_cents=20000, max_dcv_reuse_count=5),
            subscriber_payload(credit_limit_cents=30000),
            domains=("a.credit.example", "b.credit.example"),
        )
        first_request = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ["a.credit.example"],
        )
        second_request = cleared_request(
            client,
            environment.subscriber_id,
            environment.profile_id,
            ["b.credit.example"],
        )
        assert first_request["projected_charge_cents"] == 20000
        assert second_request["projected_charge_cents"] == 20000

        certificate = get_success_data(
            client.issue_certificate(
                first_request["id"],
                issue_payload(environment.ceremony_id),
                users.ISSUANCE_OPERATOR_9,
            ),
            201,
        )
        assert certificate["charged_amount_cents"] == 20000, (
            "the first issuance settles at its projected charge, found "
            f"{certificate['charged_amount_cents']}"
        )
        after_first = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            after_first, outstanding_balance_cents=20000, issued_certificate_count=1
        )

        validate_error(
            client.issue_certificate(
                second_request["id"],
                issue_payload(environment.ceremony_id),
                users.ISSUANCE_OPERATOR_9,
            ),
            ERR_CREDIT_LIMIT_EXCEEDED,
        )

        after_second = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            after_second, outstanding_balance_cents=20000, issued_certificate_count=1
        )
        assert read_request(client, second_request["id"])["state"] == (
            REQUEST_READY_TO_ISSUE
        ), "the refused request stays ready to issue"
        assert_counters(
            read_ceremony(client, environment.ceremony_id), issued_certificate_count=1
        )
        assert (
            read_certificate(client, certificate["id"])["lifecycle_status"]
            == LIFECYCLE_PREISSUANCE
        )
