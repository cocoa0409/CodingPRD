"""What a row looks like the moment it is minted, and who decides each field.

Declared inputs come back as sent; computed fields stay empty until the step
that mints them; system fields are the server's alone even when the client
supplies them; and the three journal types carry no version at all.
"""

import pytest

from test_helpers import (
    CANONICAL_DEPRECIABLE_BASIS_CENTS,
    COMPLIANCE,
    INVESTOR_A,
    INVESTOR_B,
    QI,
    SPONSOR,
    TENANT,
    TRUSTEE,
    api_client,
    create_exchange_file,
    create_exchange_file_payload,
    create_exit_consent_payload,
    create_investor,
    create_offering_payload,
    create_property_payload,
    create_subscription_payload,
    create_trust_payload,
    find_ledger_entry,
    is_valid_uuid,
    make_investor_headers,
    read_exit_event,
    read_trust,
    set_clock,
    setup_funding_with_investor_a,
    setup_proposed_exit,
    setup_trust_forming,
    setup_trust_funding,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-00000000dead"


class TestPropertyRegistrationAndRetrieval:
    def test_registration_echoes_the_declared_inputs_and_mints_nothing_else(self):
        """The computed fields are still empty at registration.

        PRD: "A `SponsorPrincipal` registers one by supplying its marketing
        `name`, the `state_code` where it sits (exactly two uppercase letters),
        its `asset_type` — one of `INDUSTRIAL`, `MULTIFAMILY`, `RETAIL` or
        `OFFICE` — the contract `purchase_price_cents` and the third-party
        `appraised_value_cents` (each at least 1 cent), the underwritten
        `annual_noi_cents` (zero or more), the `occupancy_rate` at underwriting
        as a fraction between 0.0000 and 1.0000 inclusive, and the
        `contract_close_deadline`, which is the outside date on the purchase
        contract."

        Design: Corner/entities/property_creation_returns_declared_fields
        """
        response = api_client.create_property(create_property_payload(), SPONSOR)
        prop = validate_success(response, 201)

        assert is_valid_uuid(prop["id"])
        assert prop["status"] == "UNDER_CONTRACT"
        assert prop["version"] == 1
        assert prop["name"] == "Cypress Logistics Center"
        assert prop["state_code"] == "TX"
        assert prop["asset_type"] == "INDUSTRIAL"
        assert prop["purchase_price_cents"] == 1_200_000_000
        assert prop["appraised_value_cents"] == 1_200_000_000
        assert prop["annual_noi_cents"] == 97_000_000
        assert prop["occupancy_rate"] == pytest.approx(0.95, abs=0.0001)
        assert prop["contract_close_deadline"] == "2026-09-30T23:59:59.999Z"
        assert prop["depreciable_basis_cents"] is None
        assert prop["acquired_at"] is None
        assert prop["created_at"] == "2026-08-01T00:00:00.000Z"

    def test_the_single_resource_read_returns_the_unmutated_stored_row(self):
        """A read is not a mutation, so the version stands still.

        PRD: "Endpoints that modify an existing resource, drive a state
        transition or perform a read return HTTP 200 and the affected or
        requested resource in `data`."

        Design: Corner/entities/property_retrieval_returns_stored_row
        """
        created = validate_success(
            api_client.create_property(create_property_payload(), SPONSOR), 201
        )

        fetched = validate_success(api_client.get_property(created["id"], QI))

        assert fetched["id"] == created["id"]
        assert fetched["name"] == "Cypress Logistics Center"
        assert fetched["state_code"] == "TX"
        assert fetched["asset_type"] == "INDUSTRIAL"
        assert fetched["status"] == "UNDER_CONTRACT"
        assert fetched["version"] == 1
        assert fetched["updated_at"] == "2026-08-01T00:00:00.000Z"

    def test_the_basis_is_minted_at_acquisition_and_client_input_is_discarded(self):
        """Eighty percent of the price, and not one cent of it from the client.

        PRD: "On success the server stamps `acquired_at` with the current
        logical instant and computes the property's `depreciable_basis_cents`,
        which is the improvement portion of the price: eighty percent of
        `purchase_price_cents`, land being excluded as the remaining twenty
        percent, rounded half up to whole cents."

        Design: Corner/entities/property_depreciable_basis_computed_on_acquire_client_input_ignored
        """
        created = validate_success(
            api_client.create_property(
                create_property_payload(depreciable_basis_cents=1), SPONSOR
            ),
            201,
        )
        assert created["depreciable_basis_cents"] is None

        set_clock("2026-08-20T00:00:00Z")
        acquired = validate_success(
            api_client.acquire_property(created["id"], SPONSOR)
        )

        assert acquired["status"] == "ACQUIRED"
        assert acquired["depreciable_basis_cents"] == CANONICAL_DEPRECIABLE_BASIS_CENTS
        assert acquired["acquired_at"] == "2026-08-20T00:00:00.000Z"
        assert acquired["version"] == 2

    def test_an_undeclared_enum_member_and_an_out_of_range_rate_are_both_malformed(self):
        """Shape is checked before any price field is read.

        PRD: "Request shape — body parses, required fields present, enum
        members declared, integers within their constraints, the five
        fractional rates inside their declared ranges, a distribution period
        whose start is strictly before its end, a lease term whose start is at
        or before its end, and pagination within bounds: `ERR_INVALID_REQUEST`."

        Design: Corner/entities/property_invalid_asset_type_enum_rejected
        """
        bad_enum = api_client.create_property(
            create_property_payload(asset_type="SELF_STORAGE"), SPONSOR
        )
        validate_error(bad_enum, "ERR_INVALID_REQUEST", 400)

        bad_rate = api_client.create_property(
            create_property_payload(occupancy_rate=1.4), SPONSOR
        )
        validate_error(bad_rate, "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(api_client.list_properties(SPONSOR))
        assert meta["total_count"] == 0


class TestExchangeFileDefaultsAndListing:
    def test_the_investor_filter_composes_with_limit_and_offset(self):
        """Two pages cover the filtered set and nobody else's file appears.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count`
        is the number of rows matching the filters before pagination is applied
        and `has_more` indicates whether rows remain beyond the returned
        window."

        Design: Corner/entities/exchange_files_listing_filtered_by_investor_paginates
        """
        set_clock("2026-08-20T00:00:00Z")
        investor_a = create_investor(**INVESTOR_A)
        investor_b = create_investor(**INVESTOR_B)
        files_a = [
            create_exchange_file(
                investor_a["id"],
                qi_reference=reference,
                relinquished_closed_on="2026-08-05",
            )["id"]
            for reference in ("QI-A-1", "QI-A-2", "QI-A-3")
        ]
        file_b = create_exchange_file(investor_b["id"], qi_reference="QI-B-2026")

        page_one = api_client.list_exchange_files(
            COMPLIANCE,
            params={"investor_id": investor_a["id"], "limit": 2, "offset": 0},
        )
        rows_one, meta_one = validate_paginated(page_one)
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert len(rows_one) == 2

        page_two = api_client.list_exchange_files(
            COMPLIANCE,
            params={"investor_id": investor_a["id"], "limit": 2, "offset": 2},
        )
        rows_two, meta_two = validate_paginated(page_two)
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert len(rows_two) == 1

        seen = [row["id"] for row in rows_one + rows_two]
        assert set(seen) == set(files_a)
        assert file_b["id"] not in seen
        for row in rows_one + rows_two:
            assert row["investor_id"] == investor_a["id"]

        _, meta_b = validate_paginated(
            api_client.list_exchange_files(
                COMPLIANCE, params={"investor_id": investor_b["id"]}
            )
        )
        assert meta_b["total_count"] == 1

    def test_an_omitted_boot_tolerance_is_stored_as_zero(self):
        """The one optional input in the surface has a declared default.

        PRD: "A `QualifiedIntermediary` opens an exchange file for a taxpayer by
        naming the `investor_id` running the exchange, its own `qi_reference`
        string, the `relinquished_closed_on` instant at which the relinquished
        sale closed, the gross `relinquished_sale_price_cents` (at least 1), the
        `net_proceeds_cents` it now holds (zero or more), the
        `debt_retired_cents` discharged on the relinquished property (zero or
        more), the `identification_rule` elected for the file — either
        `THREE_PROPERTY` or `TWO_HUNDRED_PCT` — and optionally the
        `boot_tolerance_cents` the investor will accept, which defaults to zero
        when omitted."

        Design: Corner/entities/exchange_file_boot_tolerance_defaults_to_zero
        """
        set_clock("2026-08-20T00:00:00Z")
        investor = create_investor(**INVESTOR_A)
        payload = create_exchange_file_payload(
            investor["id"],
            qi_reference="QI-DEF-2026",
            relinquished_closed_on="2026-08-05",
        )
        del payload["boot_tolerance_cents"]

        exchange_file = validate_success(
            api_client.create_exchange_file(payload, QI), 201
        )

        assert exchange_file["boot_tolerance_cents"] == 0
        assert exchange_file["status"] == "OPEN"
        assert exchange_file["identification_deadline"] == "2026-09-19T23:59:59.999Z"
        assert exchange_file["exchange_deadline"] == "2027-02-01T23:59:59.999Z"


class TestUnresolvedReferences:
    def test_a_well_formed_but_unknown_trust_id_is_a_not_found(self):
        """The unresolved identifier picks the code, not the request shape.

        PRD: "Path identifiers are resolved strictly left to right, and the
        first identifier that does not resolve determines the 404 that comes
        back."

        Design: Corner/entities/trust_lookup_with_unknown_id_returns_not_found
        """
        response = api_client.get_trust(UNKNOWN_UUID, TRUSTEE)

        error = validate_error(response, "ERR_TRUST_NOT_FOUND", 404)
        assert error["message"]

    def test_an_unknown_property_reference_in_the_body_is_a_not_found(self):
        """A payload foreign key is resolved with the same fixed mapping.

        PRD: "Payload-reference resolution applies to trust formation, offering
        drafting, exchange-file opening, identification filing, subscription
        creation, loan commitment, lease drafting, capital-need recording,
        distribution declaration, tax-statement preparation, exit proposal,
        consent recording and suitability review; the codes it can raise are
        the property, trust, offering, investor, exchange-file, subscription and
        exit-event 404s above."

        Design: Corner/entities/trust_creation_with_unknown_property_returns_not_found
        """
        response = api_client.create_trust(
            create_trust_payload(UNKNOWN_UUID), TRUSTEE
        )
        validate_error(response, "ERR_PROPERTY_NOT_FOUND", 404)

        _, meta = validate_paginated(api_client.list_trusts(TRUSTEE))
        assert meta["total_count"] == 0


class TestRequiredInputsHaveNoSilentDefault:
    def test_an_offering_drafted_without_a_load_percentage_is_refused(self):
        """No substituted zero, and no row.

        PRD: "The draft fixes the `exemption_rule` the offering relies on —
        either `RULE_506B` or `RULE_506C` — the `unit_price_cents` for one unit
        of beneficial interest (at least 1), the `min_units_per_investor` any
        single subscription must reach (at least 1), the sponsor's `load_pct` as
        a fraction of gross equity (at least 0.0000 and strictly below 1.0000),
        the third-party `closing_costs_cents` of the acquisition (zero or more),
        the `reserve_funding_pct` of the purchase price to be funded into
        reserve at closing (between 0.0000 and 1.0000 inclusive), and the
        `rescission_window_days` during which an investor may still unwind a
        closed subscription (zero or more)."

        Design: Corner/entities/offering_creation_missing_load_pct_rejected
        """
        deal = setup_trust_forming()
        payload = create_offering_payload(deal["trust"]["id"])
        del payload["load_pct"]

        response = api_client.create_offering(payload, SPONSOR)
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _, meta = validate_paginated(
            api_client.list_offerings(SPONSOR, params={"trust_id": deal["trust"]["id"]})
        )
        assert meta["total_count"] == 0

        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "FORMING"
        assert trust["version"] == 1


class TestSystemFieldsAreTheServersAlone:
    def test_a_subscription_ignores_client_supplied_identity_and_status(self):
        """Five declared inputs are read and the rest of the body is discarded.

        PRD: "Every resource the API mints carries an `id`, which is a
        server-minted UUID with no type prefix and is never supplied by the
        client."

        Design: Corner/entities/subscription_system_fields_server_minted_client_input_ignored
        """
        deal = setup_funding_with_investor_a()
        payload = create_subscription_payload(
            deal["offering"]["id"],
            deal["investor_a"]["id"],
            deal["exchange_file_a"]["id"],
            300,
            deal["offering_version"],
            id="11111111-1111-4111-8111-111111111111",
            created_at="2020-01-01T00:00:00Z",
            version=99,
            status="CLOSED",
        )

        subscription = validate_success(
            api_client.create_subscription(payload, SPONSOR), 201
        )

        assert subscription["id"] != "11111111-1111-4111-8111-111111111111"
        assert is_valid_uuid(subscription["id"])
        assert subscription["created_at"] == "2026-08-20T00:00:00.000Z"
        assert subscription["version"] == 1
        assert subscription["status"] == "RESERVED"
        assert subscription["investment_amount_cents"] == 300_000_000
        assert subscription["boot_cents"] == 0
        assert subscription["closing_sequence_no"] is None


class TestJournalRowsCarryNoVersion:
    def test_a_ledger_entry_read_exposes_only_the_journal_fields(self):
        """An append-only row has nothing to version.

        PRD: "Three record types are append-only journal rows rather than
        mutable resources, and they carry only `id` and `created_at`:
        `TrustLedgerEntry`, `DistributionAllocation` and `ExitConsent`."

        Design: Corner/entities/ledger_entry_is_immutable_and_carries_no_version
        """
        deal = setup_trust_funding()
        entry = find_ledger_entry(deal["trust"]["id"], "LOAN_PROCEEDS", "OPERATING")

        fetched = validate_success(api_client.get_ledger_entry(entry["id"], TENANT))

        assert fetched["id"] == entry["id"]
        assert fetched["created_at"] == "2026-08-20T00:00:00.000Z"
        assert "version" not in fetched
        assert "updated_at" not in fetched
        assert fetched["entry_type"] == "LOAN_PROCEEDS"
        assert fetched["bucket"] == "OPERATING"
        assert fetched["amount_cents"] == 720_000_000
        assert fetched["source_kind"] == "LOAN_FUNDING"
        assert fetched["reversal_of_entry_id"] is None


class TestExitConsentJunction:
    def test_the_consent_row_joins_the_event_to_the_subscription_it_snapshots(self):
        """The vote's weight is copied from the subscription, not the request.

        PRD: "The row snapshots the subscription's `units_requested` into
        `units_at_consent` and stamps `recorded_at` from the logical clock; a
        later rescission therefore cannot retroactively change a vote's weight."

        Design: Corner/entities/exit_consent_junction_links_subscription_and_exit_event
        """
        deal = setup_proposed_exit()

        consent = validate_success(
            api_client.create_exit_consent(
                create_exit_consent_payload(
                    deal["exit_event"]["id"], deal["subscription_a"]["id"]
                ),
                make_investor_headers(deal["investor_a"]["id"]),
            ),
            201,
        )

        assert consent["exit_event_id"] == deal["exit_event"]["id"]
        assert consent["subscription_id"] == deal["subscription_a"]["id"]
        assert consent["units_at_consent"] == 300
        assert consent["recorded_at"] == "2027-02-01T00:00:00.000Z"
        assert "version" not in consent

        event = read_exit_event(deal["exit_event"]["id"])
        assert event["consented_units"] == 0
        assert event["consent_pct"] is None

        _, meta = validate_paginated(
            api_client.list_exit_consents(
                SPONSOR, params={"exit_event_id": deal["exit_event"]["id"]}
            )
        )
        assert meta["total_count"] == 1
