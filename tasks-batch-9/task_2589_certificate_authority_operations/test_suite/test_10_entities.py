"""Resource shape, defaults and identity across the CA's aggregates.

These tests read the resources back the way a client sees them: what a creation
call returns, which fields the server derives rather than accepts, how a
collection paginates and filters, and which records are append-only audit
artifacts that carry neither `updated_at` nor `version`.
"""

from test_helpers import (
    DCV_METHOD_DNS_TXT,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    ERR_INVALID_ARRAY_CONTENT,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
    ERR_PROFILE_NOT_FOUND,
    ERR_SUBSCRIBER_NOT_FOUND,
    ERR_VALUE_OUT_OF_RANGE,
    CLOCK_EPOCH,
    COMM_INCIDENT_DISCLOSURE,
    FIRST_CRL_NUMBER,
    FIRST_SERIAL_NUMBER,
    INCIDENT_DISCLOSED,
    LIFECYCLE_PREISSUANCE,
    NON_EXISTENT_UUID,
    POSTURE_NOMINAL,
    PROFILE_STATE_ACTIVE,
    PROFILE_STATE_DRAFT,
    REQUEST_DRAFT,
    REQUEST_ISSUED,
    REQUEST_READY_TO_ISSUE,
    RESPONSE_TYPE_OBJECT,
    REVOCATION_STATUS_NONE,
    SUBSCRIBER_ACTIVE,
    VALIDATION_TYPE_DV,
    VETTING_LEVEL_EV,
    VETTING_LEVEL_NONE,
    VETTING_LEVEL_OV,
    assert_append_only_identity,
    assert_counters,
    assert_instant_equals,
    assert_modifiable_identity,
    assert_nulls,
    authorization_payload,
    certificate_request_payload,
    create_profile,
    create_subscriber,
    disclosure_payload,
    ev_profile_payload,
    factories,
    get_success_data,
    ids_of,
    issuance_charge_cents,
    issue_certificate,
    open_incident,
    ov_profile_payload,
    plus_days,
    plus_hours,
    profile_payload,
    publish_crl,
    read_authorization,
    read_ceremony,
    read_profile,
    read_request,
    read_subscriber,
    submitted_request,
    users,
    validate_error,
    validate_paginated,
    validated_authorization,
)


def _active_profile_and_subscriber(client, profile_body=None):
    """One ACTIVE certificate profile and one ACTIVE subscriber."""
    profile = create_profile(client, profile_body)
    subscriber = create_subscriber(client)
    return profile, subscriber


class TestCertificateProfileRepresentation:
    def test_creation_returns_the_derived_tier_fields_and_zeroed_ledger(self, client):
        """A drafted EV profile derives its vetting level and zeroes its counters.

        PRD 3.1: "A new profile is born in `status` `DRAFT` and is inert."
        PRD 3.1: "`required_vetting_level` is computed directly from the tier: a
        `DV` profile requires `NONE`, an `OV` profile requires `OV`, and an `EV`
        profile requires `EV`. `status_service_posture` starts at `NOMINAL`. The
        four ledger counters `pending_crl_entry_count`,
        `revoked_certificate_count`, `total_crl_entries_published` and
        `last_crl_number` all start at 0, while `last_crl_this_update` and
        `last_crl_next_update` start null because no list has been published;
        `activated_at` and `retired_at` are likewise null."
        PRD 2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/entities/certificate_profile_creation_returns_every_declared_field_with_derived_vetting_level
        """
        response = client.create_profile(ev_profile_payload(), users.POLICY_ADMIN)
        profile = get_success_data(response, 201)

        assert profile["status"] == PROFILE_STATE_DRAFT, (
            f"a fresh profile is DRAFT, found {profile['status']!r}"
        )
        assert profile["status_service_posture"] == POSTURE_NOMINAL, (
            f"posture starts NOMINAL, found {profile['status_service_posture']!r}"
        )
        assert profile["required_vetting_level"] == VETTING_LEVEL_EV, (
            "an EV profile requires EV vetting, found "
            f"{profile['required_vetting_level']!r}"
        )
        assert_counters(
            profile,
            pending_crl_entry_count=0,
            revoked_certificate_count=0,
            total_crl_entries_published=0,
            last_crl_number=0,
        )
        assert_nulls(
            profile,
            "last_crl_this_update",
            "last_crl_next_update",
            "activated_at",
            "retired_at",
        )
        assert response.json()["response_type"] == RESPONSE_TYPE_OBJECT, (
            "a single resource answers with response_type object, found "
            f"{response.json()['response_type']!r}"
        )

    def test_retrieval_returns_the_row_the_activation_wrote(self, client):
        """GET /{id} after activation hands back the activated row itself.

        PRD 3.1: "Activation stamps `activated_at` with the logical clock and
        increments the profile's `version`."
        PRD 3.1: "`required_vetting_level` is computed directly from the tier: a
        `DV` profile requires `NONE`, an `OV` profile requires `OV`, and an `EV`
        profile requires `EV`."

        Design: Corner/entities/certificate_profile_retrieval_returns_the_stored_row_unchanged
        """
        drafted = create_profile(
            client, profile_payload(name="dv-retrieval-probe"), activate=False
        )
        assert_modifiable_identity(drafted, expected_version=1)

        activated = get_success_data(
            client.activate_profile(drafted["id"], users.POLICY_ADMIN)
        )
        stored = read_profile(client, drafted["id"])

        assert stored["status"] == PROFILE_STATE_ACTIVE, (
            f"activation moves the profile to ACTIVE, found {stored['status']!r}"
        )
        assert_instant_equals(stored["activated_at"], CLOCK_EPOCH, "activated_at")
        assert stored["required_vetting_level"] == VETTING_LEVEL_NONE, (
            "a DV profile requires no organizational vetting, found "
            f"{stored['required_vetting_level']!r}"
        )
        assert stored["version"] == 2, (
            f"one activation lifts version 1 to 2, found {stored['version']}"
        )
        assert stored["name"] == "dv-retrieval-probe", (
            f"the stored name must survive the round trip, found {stored['name']!r}"
        )
        assert stored["version"] == activated["version"], (
            "the read must return the same row the activation returned, "
            f"found version {stored['version']} against {activated['version']}"
        )

    def test_listing_pages_filters_and_applies_the_declared_defaults(self, client):
        """Three stored profiles paginate, then a tier filter narrows to one.

        PRD 2.3: "`limit` controls page size: it defaults to 10, may not be
        smaller than 1, and may not be larger than 100. `offset` controls the
        starting position: it defaults to 0 and may not be negative."
        PRD 2.3: "When a list endpoint responds, the `meta` object carries
        `limit`, `offset`, `total_count` and `has_more` alongside
        `api_request_id` and `api_request_timestamp`; `total_count` reports the
        size of the filtered result set before the page window is applied, and
        `has_more` is true whenever unreturned rows remain after the current
        window."
        PRD 2.3: "Certificate profiles may be filtered by `status`,
        `validation_type` and `status_service_posture`."

        Design: Corner/entities/certificate_profile_listing_paginates_with_total_count_and_has_more
        """
        first = create_profile(
            client, profile_payload(name="list-probe-a"), activate=False
        )
        second = create_profile(
            client, ov_profile_payload(name="list-probe-b"), activate=False
        )
        third = create_profile(
            client, ev_profile_payload(name="list-probe-c"), activate=False
        )

        rows, meta = validate_paginated(
            client.list_profiles(users.POLICY_ADMIN, {"limit": 2, "offset": 0})
        )
        assert len(rows) == 2, f"limit 2 returns two rows, found {len(rows)}"
        assert meta["total_count"] == 3, (
            f"total_count counts the whole filtered set, found {meta['total_count']}"
        )
        assert meta["has_more"] is True, (
            "one row remains beyond the first window, so has_more must be true"
        )
        assert meta["limit"] == 2 and meta["offset"] == 0, (
            f"meta echoes the window, found limit {meta['limit']} offset {meta['offset']}"
        )

        rows, meta = validate_paginated(
            client.list_profiles(users.POLICY_ADMIN, {"limit": 2, "offset": 2})
        )
        assert len(rows) == 1, f"the tail window holds one row, found {len(rows)}"
        assert meta["total_count"] == 3, (
            f"total_count ignores the window, found {meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            "nothing remains after the tail window, so has_more must be false"
        )
        assert meta["offset"] == 2, f"meta echoes offset 2, found {meta['offset']}"

        rows, meta = validate_paginated(client.list_profiles(users.POLICY_ADMIN))
        assert meta["limit"] == DEFAULT_LIMIT, (
            f"limit defaults to {DEFAULT_LIMIT}, found {meta['limit']}"
        )
        assert meta["offset"] == DEFAULT_OFFSET, (
            f"offset defaults to {DEFAULT_OFFSET}, found {meta['offset']}"
        )
        assert len(rows) == 3, f"all three profiles fit one default page, got {len(rows)}"
        assert meta["has_more"] is False, "a complete page leaves has_more false"
        assert set(ids_of(rows)) == {first["id"], second["id"], third["id"]}, (
            "the default page must contain every stored profile"
        )

        rows, meta = validate_paginated(
            client.list_profiles(users.POLICY_ADMIN, {"validation_type": "EV"})
        )
        assert meta["total_count"] == 1, (
            f"only one EV profile exists, found total_count {meta['total_count']}"
        )
        assert ids_of(rows) == [third["id"]], (
            f"the EV filter must return only the EV profile, found {ids_of(rows)}"
        )


class TestMissingAndMalformedInput:
    def test_unknown_subscriber_id_is_a_not_found(self, client):
        """A syntactically valid UUID that names nothing answers 404.

        PRD 2.8: "**Existence, resolved left to right.** Path identifiers are
        resolved before body identifiers, and within each group in the order
        they appear."
        PRD 2.8: "The catalogue is `ERR_PROFILE_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_VETTING_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CERTIFICATE_NOT_FOUND`, `ERR_PARTITION_NOT_FOUND`,
        `ERR_CEREMONY_NOT_FOUND`, `ERR_REVOCATION_REQUEST_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND` and `ERR_AUDIT_NOT_FOUND`, all HTTP 404, and
        that listed order is also their relative precedence when two of them
        could fire on the same request."

        Design: Corner/entities/subscriber_get_with_unknown_uuid_returns_subscriber_not_found
        """
        create_subscriber(client)

        response = client.get_subscriber(NON_EXISTENT_UUID, users.POLICY_ADMIN)
        validate_error(response, ERR_SUBSCRIBER_NOT_FOUND)
        assert response.status_code == 404, (
            f"a missing subscriber is a 404, found {response.status_code}"
        )

    def test_a_profile_without_its_base_fee_is_an_invalid_request(self, client):
        """Dropping a required field is a 400, and nothing is stored.

        PRD 2.8: "First, every required input field must be present and of the
        declared JSON type, or `ERR_INVALID_REQUEST` (HTTP 400) — this applies
        to every creating and modifying endpoint."
        PRD 3.1: "`base_fee_cents`, between 1 and 10,000,000, is the per-domain
        base issuance fee before the tier multiplier."

        Design: Corner/entities/certificate_profile_creation_without_base_fee_is_rejected_as_invalid_request
        """
        payload = profile_payload(base_fee_cents=factories.OMIT)
        assert "base_fee_cents" not in payload, (
            "the probe must actually omit base_fee_cents"
        )

        response = client.create_profile(payload, users.POLICY_ADMIN)
        validate_error(response, ERR_INVALID_REQUEST)
        assert response.status_code == 400, (
            f"a missing required field is a 400, found {response.status_code}"
        )

        _rows, meta = validate_paginated(client.list_profiles(users.POLICY_ADMIN))
        assert meta["total_count"] == 0, (
            f"the rejected draft must not be stored, found {meta['total_count']} rows"
        )

    def test_a_tier_outside_the_enum_is_rejected(self, client):
        """`validation_type` accepts only the three declared tiers.

        PRD 2.8: "Then every enum-typed input must hold one of the declared
        values, or `ERR_INVALID_ENUM_VALUE` (HTTP 422)."
        PRD 3.1: "A `POLICY_ADMIN` drafts a profile by supplying a `name` of
        between 1 and 80 characters that is unique across all profiles after
        case-folding — a second profile whose name differs only in letter case
        is rejected with `ERR_PROFILE_NAME_DUPLICATE` — together with a
        `validation_type` of `DV`, `OV` or `EV`, which is the validation tier
        the profile issues under and the single most consequential choice on
        the record."

        Design: Corner/entities/profile_validation_type_rejects_a_value_outside_the_declared_enum
        """
        response = client.create_profile(
            profile_payload(validation_type="SV"), users.POLICY_ADMIN
        )
        validate_error(response, ERR_INVALID_ENUM_VALUE)
        assert response.status_code == 422, (
            f"an undeclared enum value is a 422, found {response.status_code}"
        )

        _rows, meta = validate_paginated(client.list_profiles(users.POLICY_ADMIN))
        assert meta["total_count"] == 0, (
            f"nothing may be stored for an undeclared tier, found {meta['total_count']}"
        )

    def test_integer_inputs_outside_their_declared_ranges_are_rejected(self, client):
        """Zero validity days and a 51st reuse both fall out of range.

        PRD 2.8: "Then integer inputs must lie inside their declared ranges, or
        `ERR_VALUE_OUT_OF_RANGE` (HTTP 422); this range check is exercised when
        creating a certificate profile, registering a subscriber, creating a
        certificate request, and scheduling a key ceremony."
        PRD 3.1: "`max_validity_days` is a hard cap on certificate lifetime,
        between 1 and 398 days."
        PRD 3.1: "`max_dcv_reuse_count`, between 1 and 50, is how many
        certificate requests a single validated domain authorization may be
        consumed by."

        Design: Corner/entities/profile_max_validity_days_below_the_declared_minimum_is_rejected
        """
        response = client.create_profile(
            profile_payload(max_validity_days=0), users.POLICY_ADMIN
        )
        validate_error(response, ERR_VALUE_OUT_OF_RANGE)
        assert response.status_code == 422, (
            f"0 is below the declared minimum of 1, found {response.status_code}"
        )

        response = client.create_profile(
            profile_payload(max_dcv_reuse_count=51), users.POLICY_ADMIN
        )
        validate_error(response, ERR_VALUE_OUT_OF_RANGE)

        _rows, meta = validate_paginated(client.list_profiles(users.POLICY_ADMIN))
        assert meta["total_count"] == 0, (
            f"neither out-of-range draft may be stored, found {meta['total_count']}"
        )

    def test_case_insensitive_duplicate_domains_are_rejected(self, client):
        """Two spellings of one name are one name, and that is a bad array.

        PRD 3.5: "`requested_domains` holds between 1 and 10 lowercase
        fully-qualified domain names with no duplicate after case-folding;
        violating either the count bounds or the duplicate rule is rejected with
        `ERR_INVALID_ARRAY_CONTENT`."
        PRD 2.8: "Finally array-valued inputs must satisfy their content rules,
        or `ERR_INVALID_ARRAY_CONTENT` (HTTP 422); this applies when creating a
        certificate request and when creating a certificate profile."

        Design: Corner/entities/certificate_request_with_case_insensitive_duplicate_domains_is_rejected
        """
        profile, subscriber = _active_profile_and_subscriber(client)

        response = client.create_request(
            certificate_request_payload(
                subscriber["id"],
                profile["id"],
                ["www.array.example", "WWW.ARRAY.EXAMPLE"],
            ),
            users.VALIDATION_OFFICER,
        )
        validate_error(response, ERR_INVALID_ARRAY_CONTENT)
        assert response.status_code == 422, (
            f"a duplicate after case-folding is a 422, found {response.status_code}"
        )

        _rows, meta = validate_paginated(client.list_requests(users.VALIDATION_OFFICER))
        assert meta["total_count"] == 0, (
            f"the rejected request must not exist, found {meta['total_count']} rows"
        )

    def test_authorization_foreign_keys_are_resolved_before_creation(self, client):
        """A body identifier naming nothing is a 404, not a stored orphan.

        PRD 2.8: "A profile referenced through `profile_id` or
        `scope_profile_id`, a subscriber referenced through `subscriber_id`, a
        certificate referenced through `certificate_id` or
        `supersedes_certificate_id`, a ceremony referenced through
        `ceremony_id` and an incident referenced through `incident_id` are all
        checked under this band exactly as if they had been path segments."
        PRD 3.4: "A `VALIDATION_OFFICER` opens a **domain authorization** by
        naming the `subscriber_id` it is for, the `profile_id` whose policy
        governs it, the `domain_name` under validation, and the `method` to be
        used."

        Design: Corner/entities/domain_authorization_foreign_keys_are_validated_before_creation
        """
        profile, subscriber = _active_profile_and_subscriber(client)

        response = client.create_authorization(
            authorization_payload(subscriber["id"], NON_EXISTENT_UUID, "fk.example.org"),
            users.VALIDATION_OFFICER,
        )
        validate_error(response, ERR_PROFILE_NOT_FOUND)

        response = client.create_authorization(
            authorization_payload(NON_EXISTENT_UUID, profile["id"], "fk.example.org"),
            users.VALIDATION_OFFICER,
        )
        validate_error(response, ERR_SUBSCRIBER_NOT_FOUND)

        _rows, meta = validate_paginated(
            client.list_authorizations(users.VALIDATION_OFFICER)
        )
        assert meta["total_count"] == 0, (
            f"no authorization may survive a dangling reference, found {meta['total_count']}"
        )

    def test_a_vetting_file_cannot_be_opened_under_a_missing_subscriber(self, client):
        """The path subscriber is resolved before the file is created.

        PRD 3.3: "A `VALIDATION_OFFICER` opens a vetting file against a
        subscriber — the file takes its `subscriber_id` from the subscriber it
        is opened under and never from the request body — and supplies exactly
        one input, `required_level`, which is either `OV` or `EV`."
        PRD 2.8: "The catalogue is `ERR_PROFILE_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_VETTING_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
        `ERR_CERTIFICATE_NOT_FOUND`, `ERR_PARTITION_NOT_FOUND`,
        `ERR_CEREMONY_NOT_FOUND`, `ERR_REVOCATION_REQUEST_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND` and `ERR_AUDIT_NOT_FOUND`, all HTTP 404, and
        that listed order is also their relative precedence when two of them
        could fire on the same request."

        Design: Corner/entities/organization_vetting_cannot_be_opened_under_a_non_existent_subscriber
        """
        subscriber = create_subscriber(client)

        response = client.open_vetting(
            NON_EXISTENT_UUID,
            {"required_level": VETTING_LEVEL_OV},
            users.VALIDATION_OFFICER,
        )
        validate_error(response, ERR_SUBSCRIBER_NOT_FOUND)
        assert response.status_code == 404, (
            f"an unknown path subscriber is a 404, found {response.status_code}"
        )

        _rows, meta = validate_paginated(
            client.list_vettings(subscriber["id"], users.VALIDATION_OFFICER)
        )
        assert meta["total_count"] == 0, (
            f"no vetting file may be created, found {meta['total_count']} rows"
        )


class TestServerOwnedFields:
    def test_a_new_request_defaults_expedited_to_false_and_zeroes_its_ledger(
        self, client
    ):
        """A DRAFT request omits `expedited` and the server fills in false.

        PRD 3.5: "`expedited` is a boolean that defaults to false when omitted
        and, when true, adds an expedite fee to the issuance charge."
        PRD 3.5: "The new request starts in `state` `DRAFT` with `return_count`
        at 0, `consumed_authorization_ids` an empty array, and `submitted_at`,
        `validation_cleared_by_user_id`, `validation_cleared_at`,
        `projected_not_before`, `projected_not_after`, `projected_charge_cents`,
        `issued_certificate_id`, `rejected_reason` and `blocked_reason` all
        null."
        PRD 3.2: "Registration puts the account in `account_status` `ACTIVE`
        with `outstanding_balance_cents`, `issued_certificate_count`,
        `revocation_pending_count` and `risk_score_operational` all at 0,
        `risk_score_audit_final` null until the first audit opinion covers the
        subscriber, and `suspended_at` null."

        Design: Corner/entities/certificate_request_expedited_defaults_to_false_and_counters_start_at_zero
        """
        profile, subscriber = _active_profile_and_subscriber(client)
        payload = certificate_request_payload(
            subscriber["id"], profile["id"], ["defaults.example.org"]
        )
        payload.pop("expedited")

        request = get_success_data(
            client.create_request(payload, users.VALIDATION_OFFICER), 201
        )

        assert request["expedited"] is False, (
            f"an omitted expedited defaults to false, found {request['expedited']!r}"
        )
        assert request["state"] == REQUEST_DRAFT, (
            f"a new request starts in DRAFT, found {request['state']!r}"
        )
        assert_counters(request, return_count=0)
        assert request["consumed_authorization_ids"] == [], (
            "consumed_authorization_ids starts empty, found "
            f"{request['consumed_authorization_ids']!r}"
        )
        assert_nulls(
            request,
            "submitted_at",
            "validation_cleared_by_user_id",
            "validation_cleared_at",
            "projected_not_before",
            "projected_not_after",
            "projected_charge_cents",
            "issued_certificate_id",
            "rejected_reason",
            "blocked_reason",
        )

        owner = read_subscriber(client, subscriber["id"])
        assert owner["account_status"] == SUBSCRIBER_ACTIVE, (
            f"a registered subscriber is ACTIVE, found {owner['account_status']!r}"
        )
        assert_counters(
            owner,
            outstanding_balance_cents=0,
            issued_certificate_count=0,
            revocation_pending_count=0,
            risk_score_operational=0,
        )
        assert_nulls(owner, "risk_score_audit_final", "suspended_at")

    def test_clearance_computes_the_projection_the_client_never_supplies(self, client):
        """Clearing validation writes the window, the charge and the SoD anchor.

        PRD 3.5: "The **projected validity window** is the anchored-at-clearance
        variant of the validity calculation: `projected_not_before` is the
        logical clock at clearance, and `projected_not_after` is that same
        instant plus the capped validity span, where the capped span in days is
        the lesser of the request's `requested_validity_days` and the profile's
        `max_validity_days`."
        PRD 3.5: "`validation_cleared_by_user_id` takes the acting `X-User-ID`
        and `validation_cleared_at` the logical clock — together these become
        the segregation-of-duties anchor for issuance.
        `consumed_authorization_ids` receives the selected authorization
        identifiers in `requested_domains` order, one per domain, and every
        selected authorization has its `reuse_count` incremented by one."
        PRD 3.5: "First, the per-domain unit price is the profile's
        `base_fee_cents` multiplied by the validation-tier multiplier — 1.0 for
        a `DV` profile, 1.5 for an `OV` profile and 2.5 for an `EV` profile —
        with the product rounded half up to a whole cent at this point, before
        any multiplication by the domain count."

        Design: Corner/entities/clearance_writes_the_computed_projection_fields_and_input_cannot_supply_them
        """
        profile = create_profile(
            client, profile_payload(base_fee_cents=20000, max_validity_days=90)
        )
        subscriber = create_subscriber(client)
        authorization = validated_authorization(
            client, subscriber["id"], profile["id"], "projection.example.org"
        )
        request = submitted_request(
            client, subscriber["id"], profile["id"], ("projection.example.org",), 90
        )
        assert_nulls(request, "projected_not_before", "projected_charge_cents")

        cleared = get_success_data(
            client.clear_validation(request["id"], users.VALIDATION_OFFICER)
        )

        assert cleared["state"] == REQUEST_READY_TO_ISSUE, (
            f"clearance moves the request to READY_TO_ISSUE, found {cleared['state']!r}"
        )
        assert_instant_equals(
            cleared["projected_not_before"], CLOCK_EPOCH, "projected_not_before"
        )
        assert_instant_equals(
            cleared["projected_not_after"],
            plus_days(CLOCK_EPOCH, 90),
            "projected_not_after",
        )
        expected_charge = issuance_charge_cents(20000, VALIDATION_TYPE_DV, 1)
        assert cleared["projected_charge_cents"] == expected_charge, (
            f"projected_charge_cents is {cleared['projected_charge_cents']}, "
            f"expected {expected_charge}"
        )
        assert cleared["consumed_authorization_ids"] == [authorization["id"]], (
            "the one validated authorization must be consumed, found "
            f"{cleared['consumed_authorization_ids']!r}"
        )
        assert cleared["validation_cleared_by_user_id"] == users.USER_VALIDATION_OFFICER, (
            "validation_cleared_by_user_id takes the acting X-User-ID, found "
            f"{cleared['validation_cleared_by_user_id']!r}"
        )
        assert_instant_equals(
            cleared["validation_cleared_at"], CLOCK_EPOCH, "validation_cleared_at"
        )
        consumed = read_authorization(client, authorization["id"])
        assert_counters(consumed, reuse_count=1)

    def test_issuance_mints_the_certificate_identity_and_debits_the_account(
        self, client, dv_environment
    ):
        """Serial, copied keys, zeroed SCT ledger, and the three counter hops.

        PRD 3.7: "The new record carries `lifecycle_status` `PREISSUANCE` and
        `revocation_status` `NONE`, a fresh `serial_number` taken as the previous
        serial plus one (the very first certificate the system ever issues being
        `"1000001"`), the `request_id` of the originating request, and
        `subscriber_id` and `profile_id` copied from it, along with the
        `ceremony_id` and any `supersedes_certificate_id` supplied in the body.
        `dcv_methods_used` records the distinct `method` values of the
        authorizations the originating request consumed, sorted ascending
        alphabetically. `sct_count` starts at 0, and `refunded_at`,
        `activated_at`, `revoked_at`, `revocation_reason_code`, `crl_number` and
        `crl_published_at` all start null."
        PRD 3.7: "Issuance then debits the subscriber:
        `outstanding_balance_cents` rises by `charged_amount_cents` and
        `issued_certificate_count` rises by one, with the subscriber's `version`
        incrementing. The originating request moves `READY_TO_ISSUE → ISSUED`,
        its `issued_certificate_id` is set to the new certificate, and its
        `version` increments. The signing ceremony's `issued_certificate_count`
        increments by one."
        PRD 2.4: "`version` is an integer that begins at 1 when the resource is
        created and increases by exactly one on every mutation of that resource,
        whether the mutation was requested directly by a client or applied
        indirectly by a cascade."

        Design: Corner/entities/certificate_system_fields_are_server_minted_at_issuance
        """
        environment = dv_environment
        certificate = issue_certificate(client, environment)

        assert certificate["serial_number"] == FIRST_SERIAL_NUMBER, (
            "the first certificate the system issues is serial "
            f"{FIRST_SERIAL_NUMBER}, found {certificate['serial_number']!r}"
        )
        assert certificate["lifecycle_status"] == LIFECYCLE_PREISSUANCE, (
            f"a new certificate is PREISSUANCE, found {certificate['lifecycle_status']!r}"
        )
        assert certificate["revocation_status"] == REVOCATION_STATUS_NONE, (
            "a new certificate is not under revocation, found "
            f"{certificate['revocation_status']!r}"
        )
        assert certificate["subscriber_id"] == environment.subscriber_id, (
            "subscriber_id is copied from the request, found "
            f"{certificate['subscriber_id']!r}"
        )
        assert certificate["profile_id"] == environment.profile_id, (
            f"profile_id is copied from the request, found {certificate['profile_id']!r}"
        )
        assert certificate["ceremony_id"] == environment.ceremony_id, (
            f"ceremony_id comes from the body, found {certificate['ceremony_id']!r}"
        )
        assert certificate["dcv_methods_used"] == [DCV_METHOD_DNS_TXT], (
            "dcv_methods_used lists the consumed methods, found "
            f"{certificate['dcv_methods_used']!r}"
        )
        assert_counters(certificate, sct_count=0)
        assert_nulls(
            certificate,
            "refunded_at",
            "activated_at",
            "revoked_at",
            "revocation_reason_code",
            "crl_number",
            "crl_published_at",
            "supersedes_certificate_id",
        )
        assert_modifiable_identity(certificate, expected_version=1)

        expected_charge = issuance_charge_cents(
            environment.profile["base_fee_cents"], VALIDATION_TYPE_DV, 1
        )
        assert certificate["charged_amount_cents"] == expected_charge, (
            f"charged_amount_cents is {certificate['charged_amount_cents']}, "
            f"expected {expected_charge}"
        )

        request = read_request(client, certificate["request_id"])
        assert request["state"] == REQUEST_ISSUED, (
            f"the originating request becomes ISSUED, found {request['state']!r}"
        )
        assert request["issued_certificate_id"] == certificate["id"], (
            "issued_certificate_id must point at the new certificate, found "
            f"{request['issued_certificate_id']!r}"
        )
        owner = read_subscriber(client, environment.subscriber_id)
        assert_counters(
            owner,
            issued_certificate_count=1,
            outstanding_balance_cents=expected_charge,
        )
        ceremony = read_ceremony(client, environment.ceremony_id)
        assert_counters(ceremony, issued_certificate_count=1)


class TestAppendOnlyRecords:
    def test_a_crl_publication_has_no_version_and_still_advances_the_number(
        self, client
    ):
        """An empty list is legal, numbered 1, and immutable once written.

        PRD 3.8: "`crl_number` on the new publication is the profile's
        `last_crl_number` plus one, `entry_count` is the size of the drain set,
        and `revoked_serials` is the list of those certificates' `serial_number`
        values in that same order."
        PRD 3.8: "A publication with an empty drain set is perfectly legal:
        `entry_count` is 0, `revoked_serials` is an empty array, and `crl_number`
        still advances by one. The publication record itself is immutable,
        carrying `id` and `created_at` and neither `updated_at` nor `version`,
        and the response is 201."
        PRD 2.4: "A transparency-log submission (`CtLogSubmission`), a
        revocation-list publication (`CrlPublication`) and a root program
        communication (`RootProgramCommunication`) therefore carry only `id` and
        `created_at`: both `updated_at` and `version` are absent from their
        representations entirely."

        Design: Corner/entities/crl_publication_is_append_only_and_carries_no_version_field
        """
        profile = create_profile(client)
        next_update = plus_hours(CLOCK_EPOCH, 12)

        publication = publish_crl(client, profile["id"], CLOCK_EPOCH, next_update)

        assert publication["crl_number"] == FIRST_CRL_NUMBER, (
            f"the first publication is number {FIRST_CRL_NUMBER}, "
            f"found {publication['crl_number']}"
        )
        assert publication["entry_count"] == 0, (
            f"nothing was pending, so entry_count is 0, found {publication['entry_count']}"
        )
        assert publication["revoked_serials"] == [], (
            f"an empty drain set lists no serials, found {publication['revoked_serials']!r}"
        )
        assert publication["published_by_user_id"] == users.USER_REVOCATION_OFFICER, (
            "published_by_user_id records the acting X-User-ID, found "
            f"{publication['published_by_user_id']!r}"
        )
        assert_append_only_identity(publication)

        stored = read_profile(client, profile["id"])
        assert_counters(
            stored,
            last_crl_number=FIRST_CRL_NUMBER,
            total_crl_entries_published=0,
            pending_crl_entry_count=0,
        )
        assert_instant_equals(
            stored["last_crl_this_update"], CLOCK_EPOCH, "last_crl_this_update"
        )
        assert_instant_equals(
            stored["last_crl_next_update"], next_update, "last_crl_next_update"
        )

        rows, meta = validate_paginated(
            client.list_crl_publications(profile["id"], users.REVOCATION_OFFICER)
        )
        assert meta["total_count"] == 1, (
            f"exactly one publication exists, found {meta['total_count']}"
        )
        assert ids_of(rows) == [publication["id"]], (
            f"the listing must return the publication just written, found {ids_of(rows)}"
        )
        assert_append_only_identity(rows[0])

    def test_a_disclosure_writes_an_immutable_system_typed_communication(self, client):
        """Disclosure records an INCIDENT_DISCLOSURE with no version at all.

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
        PRD 2.4: "A transparency-log submission (`CtLogSubmission`), a
        revocation-list publication (`CrlPublication`) and a root program
        communication (`RootProgramCommunication`) therefore carry only `id` and
        `created_at`: both `updated_at` and `version` are absent from their
        representations entirely."

        Design: Corner/entities/root_program_communication_is_immutable_and_system_typed
        """
        profile = create_profile(client)
        incident = open_incident(client, profile["id"])
        assert_instant_equals(
            incident["disclosure_due_at"], plus_hours(CLOCK_EPOCH, 24), "disclosure_due_at"
        )

        disclosed = get_success_data(
            client.disclose_incident(
                incident["id"], disclosure_payload(), users.COMPLIANCE_AUDITOR
            )
        )
        assert disclosed["state"] == INCIDENT_DISCLOSED, (
            f"disclosure moves the incident to DISCLOSED, found {disclosed['state']!r}"
        )
        assert_instant_equals(disclosed["disclosed_at"], CLOCK_EPOCH, "disclosed_at")

        rows, meta = validate_paginated(
            client.list_incident_communications(incident["id"], users.COMPLIANCE_AUDITOR)
        )
        assert meta["total_count"] == 1, (
            f"one disclosure writes one communication, found {meta['total_count']}"
        )
        communication = rows[0]
        assert communication["kind"] == COMM_INCIDENT_DISCLOSURE, (
            f"the kind is INCIDENT_DISCLOSURE, found {communication['kind']!r}"
        )
        assert communication["incident_id"] == incident["id"], (
            f"incident_id must point at the incident, found {communication['incident_id']!r}"
        )
        assert_nulls(communication, "audit_id")
        assert communication["within_deadline"] is True, (
            "a disclosure at the discovery instant is well inside the 24 hour "
            f"deadline, found within_deadline {communication['within_deadline']!r}"
        )
        assert communication["sent_by_user_id"] == users.USER_COMPLIANCE_AUDITOR, (
            "sent_by_user_id is taken from X-User-ID, found "
            f"{communication['sent_by_user_id']!r}"
        )
        assert_instant_equals(communication["sent_at"], CLOCK_EPOCH, "sent_at")
        assert_append_only_identity(communication)
