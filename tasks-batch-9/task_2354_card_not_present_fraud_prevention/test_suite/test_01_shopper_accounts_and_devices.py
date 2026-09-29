"""Registration of the three shopper-side entities and their derived defaults."""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    CHECKOUT,
    CLOCK_EPOCH,
    AccountStatus,
    AddressClassification,
    ApiClient,
    ApiErrorId,
    AtoPosture,
    CustomerTier,
    DeviceReputation,
    DropRiskState,
    NON_EXISTENT_UUID,
    assert_address,
    assert_cluster_root,
    assert_device,
    assert_new_customer_defaults,
    assert_score,
    create_address_payload,
    create_customer_payload,
    create_device_payload,
    parse_instant,
    read_address,
    read_device,
    set_clock,
    validate_error,
    validate_success,
)

#: A UUID the client asks the server to adopt as the new row's identity.
CLIENT_SUPPLIED_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_SUPPLIED_INSTANT = "2001-01-01T00:00:00Z"


class TestCustomerRegistrationDefaults:
    """A bare create materialises every declared default in the success envelope."""

    def test_a_bare_create_returns_201_and_every_declared_default(
        self, api: ApiClient
    ) -> None:
        """Two required inputs are enough; the server fills in the rest.

        PRD: "A new account starts with `account_status` `ACTIVE`, `ato_posture`
        `CLEAR`, `locked_reason` null, `good_customer_flag` false, and every derived
        counter — `lifetime_net_approved_cents`, `approved_count`, `declined_count`,
        `confirmed_fraud_count`, `failed_login_count` — at zero."
        PRD: "The `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/entities/customer_creation_applies_declared_defaults_and_envelope
        """
        set_clock(api)
        response = api.create_customer(
            create_customer_payload(email="bare@example.com", home_country="US"),
            CHECKOUT,
        )
        data = validate_success(response, 201)

        body = response.json()
        assert "meta" in body, "every success response carries a meta object"
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id is a server-generated identifier that starts with req_"
        )
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object", (
            "a single resource is returned as response_type object"
        )

        assert_new_customer_defaults(data)
        assert data["email"] == "bare@example.com"
        assert data["home_country"] == "US"
        assert data["tier"] == CustomerTier.STANDARD, (
            "a tier that is not supplied defaults to STANDARD"
        )
        assert parse_instant(data["created_at"]) == parse_instant(CLOCK_EPOCH), (
            "created_at is taken from the logical clock, not the host wall clock"
        )

    def test_client_supplied_counters_and_statuses_are_ignored(
        self, api: ApiClient
    ) -> None:
        """A create that seeds its own standing persists zeroes and ACTIVE anyway.

        PRD: "`good_customer_flag` is not an input. It is recomputed by the server
        after any write that changes `account_status`, `ato_posture`, `approved_count`,
        `confirmed_fraud_count` or `lifetime_net_approved_cents`, and it reads the
        customer row as it stands *after* that request's counter movements have
        landed."
        PRD: "A `tier` may be supplied and defaults to `STANDARD`; the accepted values
        are `STANDARD`, `HIGH_VALUE` and `BUSINESS`, and the tier gates both
        policy-exception eligibility and review priority."

        Design: Corner/entities/customer_ledger_counters_input_ignored
        """
        set_clock(api)
        data = validate_success(
            api.create_customer(
                create_customer_payload(
                    email="seed@example.com",
                    home_country="US",
                    tier=CustomerTier.BUSINESS,
                    approved_count=99,
                    lifetime_net_approved_cents=999999,
                    good_customer_flag=True,
                    confirmed_fraud_count=7,
                    account_status=AccountStatus.LOCKED,
                ),
                CHECKOUT,
            ),
            201,
        )

        assert data["tier"] == CustomerTier.BUSINESS, (
            "tier is a real client input and is honoured"
        )
        assert data["approved_count"] == 0
        assert data["lifetime_net_approved_cents"] == 0
        assert data["confirmed_fraud_count"] == 0
        assert data["good_customer_flag"] is False, (
            "a client cannot seed its own good-customer standing"
        )
        assert data["account_status"] == AccountStatus.ACTIVE
        assert data["ato_posture"] == AtoPosture.CLEAR


class TestDeviceRegistrationAndRetrieval:
    """A device profile reads back exactly as stored, with its signals at zero."""

    def test_a_fresh_device_reads_back_with_zeroed_derived_signals(
        self, api: ApiClient
    ) -> None:
        """No assessment and no auth event reference the device, so all three are 0.

        PRD: "Reputation is derived, never supplied: it starts at `NEW`, except that a
        fingerprint registered with `emulator_flag` true is recomputed to `SUSPECT` in
        the same request, because the emulator condition is one of the reputation
        triggers."
        PRD: "`distinct_customer_count` is the number of distinct customers appearing
        across two row sets combined: the assessments on this device whose `decision`
        is not null, and the authentication events on this device."

        Design: Corner/entities/device_retrieval_returns_stored_row_with_zeroed_counters
        """
        set_clock(api)
        created = validate_success(
            api.create_device(
                create_device_payload(
                    device_hash="dev-corner-001", tz_offset_minutes=-300
                ),
                CHECKOUT,
            ),
            201,
        )

        stored = read_device(api, created["id"], ADMIN)
        assert_device(stored)
        assert stored["device_hash"] == "dev-corner-001"
        assert stored["tz_offset_minutes"] == -300
        assert stored["emulator_flag"] is False, (
            "an omitted emulator_flag defaults to false"
        )
        assert stored["reputation"] == DeviceReputation.NEW
        assert stored["distinct_customer_count"] == 0
        assert stored["approved_use_count"] == 0
        assert stored["fraud_confirmed_count"] == 0

    def test_an_unknown_device_id_is_a_404_in_the_error_envelope(
        self, api: ApiClient
    ) -> None:
        """A well-formed but unknown UUID is a not-found, never an empty success.

        PRD: "The twelve not-found codes are `ERR_CUSTOMER_NOT_FOUND`,
        `ERR_ANALYST_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_ADDRESS_NOT_FOUND`,
        `ERR_RULE_PACK_NOT_FOUND`, `ERR_RULE_NOT_FOUND`, `ERR_RISK_MODEL_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_AUTH_EVENT_NOT_FOUND`,
        `ERR_CHARGEBACK_NOT_FOUND` and `ERR_EXCEPTION_NOT_FOUND`."
        PRD: "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/entities/device_lookup_with_unknown_uuid_returns_404
        """
        set_clock(api)
        response = api.get_device(NON_EXISTENT_UUID, ADMIN)
        validate_error(response, ApiErrorId.ERR_DEVICE_NOT_FOUND, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"] != "", (
            "the message provides a human-readable explanation"
        )
        assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}


class TestAddressRegistration:
    """Address classification defaults to a real value, and identity is server-owned."""

    def test_classification_defaults_to_residential_and_the_row_is_its_own_root(
        self, api: ApiClient
    ) -> None:
        """An omitted classification yields RESIDENTIAL, and PO_BOX is kept verbatim.

        PRD: "An address is registered by the checkout service, a risk analyst or an
        administrator with `line1`, `postal_code` and a `country_code` of exactly two
        uppercase letters, plus an optional `classification` defaulting to
        `RESIDENTIAL` (the alternatives are `COMMERCIAL`, `FREIGHT_FORWARDER` and
        `PO_BOX`) and an optional `canonical_parent_address_id` linking it as a variant
        of an existing root, per §2.10."
        PRD: "A fresh row starts with all four cluster counters at zero,
        `drop_risk_state` `CLEAN` and `reshipper_confidence` 0.00; when the new row
        joins an existing cluster, the cluster **root** is recomputed immediately."

        Design: Corner/entities/address_classification_defaults_to_residential_when_omitted
        """
        set_clock(api)
        defaulted = validate_success(
            api.create_address(
                create_address_payload(
                    line1="1 Default Way", postal_code="94105", country_code="US"
                ),
                CHECKOUT,
            ),
            201,
        )
        assert_address(defaulted)
        assert_cluster_root(defaulted)
        assert defaulted["classification"] == AddressClassification.RESIDENTIAL, (
            "the default is a real value, not null"
        )
        assert defaulted["distinct_customer_count"] == 0
        assert defaulted["approved_use_count"] == 0
        assert defaulted["fraud_confirmed_count"] == 0
        assert defaulted["promo_redemption_count"] == 0
        assert defaulted["drop_risk_state"] == DropRiskState.CLEAN
        assert_score(
            defaulted["reshipper_confidence"], 0.00, "address.reshipper_confidence"
        )

        po_box = validate_success(
            api.create_address(
                create_address_payload(
                    line1="PO Box 9",
                    postal_code="94105",
                    country_code="US",
                    classification=AddressClassification.PO_BOX,
                ),
                CHECKOUT,
            ),
            201,
        )
        assert po_box["classification"] == AddressClassification.PO_BOX, (
            "a supplied classification overrides the default"
        )
        assert po_box["id"] != defaulted["id"]

    def test_server_generated_identity_fields_ignore_client_input(
        self, api: ApiClient
    ) -> None:
        """A create that supplies id, stamps and version gets the server's own values.

        PRD: "**`id`** — a server-minted UUID, with no type prefix of any kind."
        PRD: "**`version`** — an integer that is 1 on creation and increments by
        exactly 1 on every mutation of that row, including mutations the server
        performs as a cascade rather than at the client's direct request."

        Design: Corner/entities/address_system_fields_generated_input_ignored
        """
        set_clock(api)
        created = validate_success(
            api.create_address(
                create_address_payload(
                    line1="2 System Way",
                    postal_code="94105",
                    country_code="US",
                    id=CLIENT_SUPPLIED_ID,
                    created_at=CLIENT_SUPPLIED_INSTANT,
                    updated_at=CLIENT_SUPPLIED_INSTANT,
                    version=42,
                ),
                ADMIN,
            ),
            201,
        )

        assert created["id"] != CLIENT_SUPPLIED_ID, (
            "the identifier is minted by the server, not adopted from the request"
        )
        assert created["version"] == 1, "a freshly created row is at version 1"
        assert parse_instant(created["created_at"]) == parse_instant(CLOCK_EPOCH)
        assert parse_instant(created["updated_at"]) == parse_instant(CLOCK_EPOCH)

        stored = read_address(api, created["id"], ADMIN)
        assert stored["id"] == created["id"]
        assert stored["version"] == 1
