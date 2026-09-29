"""Entity-surface compliance: declared fields, derived defaults, immutable audit rows.

Every test here builds its own world from an empty database and reads the entity
back through the endpoints the PRD declares, checking that each field the
contract names is present, is of the declared kind, and carries the value the
contract derives for it.
"""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CARD_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STORE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_create_only_fields,
    assert_empty,
    assert_ordered_by,
    assert_signed_amount,
    assert_store_counters,
    assert_three_fraction_digits,
)
from test_helpers.constants import (
    ABSENT_UUID,
    CLOCK_ORIGIN,
    DEFAULT_LIMIT,
    POLICY_DEFAULTS,
)
from test_helpers.factories import (
    card_rack_payload,
    draining_alert_payload,
    gift_card_payload,
    omit,
    redemption_payload,
    reseller_listing_payload,
    store_payload,
)
from test_helpers.fixtures import (
    audit_rack,
    create_rack,
    create_store,
    funded_physical_card,
    parse_instant,
    read_card,
    read_rack,
    redeem,
    stock_card,
    total_count,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_liability_accountant_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_reseller_partner_headers,
    make_risk_manager_headers,
)


class TestRetailStoreCreation:
    """A registered store's declared fields, derived counters and stamped timestamps."""

    def test_store_create_returns_every_declared_field_with_the_counters_at_zero(self, client):
        """"A retail store is registered by a PlatformAdmin with a name of 1 to 120
        characters, a region_code of exactly two uppercase letters used for reporting
        rollups, and an address_line of 1 to 200 characters."
        "It is born with a floor_posture of OPEN and every derived counter —
        tampered_rack_count, suspect_rack_count, open_alert_count and
        declined_issuance_count — sitting at 0."
        "version, an integer that starts at 1 on creation and increases by exactly 1 on
        every mutation".

        Design: Corner/entities/store_create_returns_all_declared_fields_with_derived_counters_zeroed
        """
        admin = make_platform_admin_headers()
        assert total_count(client.list_stores(admin)) == 0

        response = client.create_store(
            store_payload(
                name="Grand Avenue Market",
                region_code="SE",
                address_line="800 Grand Ave",
            ),
            admin,
        )

        store = validate_success(response, 201)
        assert is_valid_uuid(store["id"]), store["id"]
        assert store["name"] == "Grand Avenue Market"
        assert store["region_code"] == "SE"
        assert store["address_line"] == "800 Grand Ave"
        assert_store_counters(
            store,
            floor_posture="OPEN",
            tampered_rack_count=0,
            suspect_rack_count=0,
            open_alert_count=0,
            declined_issuance_count=0,
        )
        assert store["version"] == 1, store["version"]

    def test_store_create_stamps_both_timestamps_from_the_logical_clock(self, client):
        """"Every resource exposes a server-minted id, which is a UUID with no type
        prefix, and a created_at timestamp in ISO 8601 UTC with three fractional digits."
        "At process start the clock reads exactly 2026-08-01T00:00:00Z, so a test that
        never moves it still observes a fixed, reproducible present."

        Design: Corner/entities/store_create_returns_all_declared_fields_with_derived_counters_zeroed
        """
        response = client.create_store(
            store_payload(
                name="Grand Avenue Market",
                region_code="SE",
                address_line="800 Grand Ave",
            ),
            make_platform_admin_headers(),
        )

        store = validate_success(response, 201)
        assert_three_fraction_digits(store["created_at"])
        assert_three_fraction_digits(store["updated_at"])
        assert parse_instant(store["created_at"]) == parse_instant(CLOCK_ORIGIN)
        assert parse_instant(store["updated_at"]) == parse_instant(CLOCK_ORIGIN)

    def test_store_create_without_region_code_is_rejected_and_writes_nothing(self, client):
        """"every field the endpoint declares as required is present and non-null; every
        enum-typed field carries one of its declared values; every datetime parses as ISO
        8601 UTC."
        "Any failure is ERR_INVALID_REQUEST (400)."

        Design: Corner/entities/store_create_without_region_code_is_invalid_request
        """
        admin = make_platform_admin_headers()
        assert total_count(client.list_stores(admin)) == 0

        response = client.create_store(
            store_payload(
                name="Nameless Region Store",
                address_line="1 Nowhere Ln",
                region_code=omit,
            ),
            admin,
        )

        validate_error(response, ERR_INVALID_REQUEST, 400)
        assert total_count(client.list_stores(admin)) == 0


class TestCardRackRetrieval:
    """A rack read back after an audit, and a rack created under an absent store."""

    def _audited_rack(self, client):
        """A store, a rack whose planogram slot count is 10, and one clean audit reporting
        ten cards observed and no broken seals."""
        store = create_store(
            client, name="Clearview Foods", region_code="MW", address_line="9 Clearview Dr"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-C1", expected_card_count=10)
        audited = audit_rack(
            client, rack["id"], observed_card_count=10, seal_breaks_observed=0
        )
        return {"store": store, "rack": rack, "audited": audited}

    def test_rack_read_returns_the_numbers_the_audit_persisted(self, client):
        """"Both figures are persisted verbatim so that the classification is reproducible
        from the stored row, and last_audit_at is stamped from the logical clock."
        "Shrink is then derived as the expected count minus the observed count, floored at
        zero and stored as missing_card_count".
        "Otherwise it is INTACT."

        Design: Corner/entities/card_rack_get_by_id_returns_the_row_written_by_the_last_audit
        """
        world = self._audited_rack(client)
        assert world["audited"]["tamper_state"] == "INTACT"

        response = client.get_card_rack(
            world["rack"]["id"], make_risk_manager_headers("risk-20")
        )

        rack = validate_success(response, 200)
        assert rack["tamper_state"] == "INTACT", rack["tamper_state"]
        assert rack["observed_card_count"] == 10
        assert rack["missing_card_count"] == 0
        assert rack["seal_breaks_observed"] == 0
        assert rack["store_id"] == world["store"]["id"]
        assert rack["rack_label"] == "RACK-C1"
        assert rack["expected_card_count"] == 10

    def test_rack_read_reports_last_audit_at_from_the_logical_clock(self, client):
        """"Both figures are persisted verbatim so that the classification is reproducible
        from the stored row, and last_audit_at is stamped from the logical clock."
        "At process start the clock reads exactly 2026-08-01T00:00:00Z, so a test that
        never moves it still observes a fixed, reproducible present."

        Design: Corner/entities/card_rack_get_by_id_returns_the_row_written_by_the_last_audit
        """
        world = self._audited_rack(client)

        rack = read_rack(client, world["rack"]["id"], make_risk_manager_headers("risk-20"))

        assert_three_fraction_digits(rack["last_audit_at"])
        assert parse_instant(rack["last_audit_at"]) == parse_instant(CLOCK_ORIGIN)

    def test_card_rack_create_under_an_absent_store_is_not_found(self, client):
        """"store references first (a path store id, a store_id, or a merchant_store_id
        must resolve, otherwise ERR_STORE_NOT_FOUND, 404 — this applies to reading one
        store, creating a rack, stocking a card, opening an issuance request, opening a
        bulk order, redeeming against a card, and settling a hold)".

        Design: Corner/entities/card_rack_create_under_unknown_store_is_not_found
        """
        admin = make_platform_admin_headers()
        real_store = create_store(
            client, name="Real Store", region_code="NE", address_line="1 Real St"
        )

        response = client.create_card_rack(
            card_rack_payload(
                ABSENT_UUID, rack_label="RACK-GHOST", expected_card_count=4
            ),
            admin,
        )

        validate_error(response, ERR_STORE_NOT_FOUND, 404)
        assert total_count(client.list_card_racks(admin)) == 0
        store = validate_success(client.get_store(real_store["id"], admin), 200)
        assert_store_counters(store, tampered_rack_count=0, suspect_rack_count=0)


class TestGiftCardListing:
    """Twelve stocked cards read through the declared pagination envelope."""

    def _twelve_stocked_cards(self, client):
        """A store, a rack with twenty planogram slots, and twelve cards stocked onto it —
        each "created inactive with a zero balance"."""
        store = create_store(
            client, name="Bayview Superstore", region_code="NW", address_line="1200 Bayview Rd"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-BV", expected_card_count=20)
        cards = [
            stock_card(
                client,
                store["id"],
                rack["id"],
                card_number_masked=f"****-****-****-20{index:02d}",
            )
            for index in range(1, 13)
        ]
        return {"store": store, "rack": rack, "cards": cards}

    def test_gift_card_list_windows_at_the_default_limit_with_total_count_and_has_more(
        self, client
    ):
        """"limit defaults to 10, has a minimum of 1 and a maximum of 100."
        "List responses carry limit, offset, total_count and has_more in the meta block,
        where total_count is the number of records matching the filters before the window
        is applied and has_more indicates whether records remain beyond the current
        window."

        Design: Corner/entities/gift_card_list_paginates_with_total_count_and_has_more
        """
        world = self._twelve_stocked_cards(client)

        response = client.list_gift_cards(
            make_fraud_analyst_headers("analyst-20"), {"store_id": world["store"]["id"]}
        )

        rows, meta = validate_paginated(response)
        assert len(rows) == DEFAULT_LIMIT == 10, len(rows)
        assert meta["total_count"] == 12, meta
        assert meta["has_more"] is True, meta
        assert meta["limit"] == 10, meta
        assert meta["offset"] == 0, meta

    def test_gift_card_list_second_window_returns_the_remaining_two_rows(self, client):
        """"offset defaults to 0 and has a minimum of 0."
        "List responses carry limit, offset, total_count and has_more in the meta block,
        where total_count is the number of records matching the filters before the window
        is applied and has_more indicates whether records remain beyond the current
        window."

        Design: Corner/entities/gift_card_list_paginates_with_total_count_and_has_more
        """
        world = self._twelve_stocked_cards(client)

        response = client.list_gift_cards(
            make_fraud_analyst_headers("analyst-20"),
            {"store_id": world["store"]["id"], "limit": 10, "offset": 10},
        )

        rows, meta = validate_paginated(response)
        assert len(rows) == 2, len(rows)
        assert meta["total_count"] == 12, meta
        assert meta["has_more"] is False, meta

    def test_gift_card_list_filtered_on_the_funding_dimension_still_counts_all_twelve(
        self, client
    ):
        """"The card is created with channel PHYSICAL, a funding state of INACTIVE, a fraud
        posture of CLEAR, face_value_cents of 0 and every balance figure at 0."
        "Gift cards are the exception in form only — carrying two independent lifecycle
        dimensions, they are filtered by activation_state and risk_posture separately
        rather than by a single combined filter."

        Design: Corner/entities/gift_card_list_paginates_with_total_count_and_has_more
        """
        world = self._twelve_stocked_cards(client)
        for card in (world["cards"][0], world["cards"][-1]):
            assert card["activation_state"] == "INACTIVE", card["activation_state"]
            assert card["current_balance_cents"] == 0
            assert card["face_value_cents"] == 0

        response = client.list_gift_cards(
            make_fraud_analyst_headers("analyst-20"),
            {"activation_state": "INACTIVE", "limit": 5, "offset": 0},
        )

        rows, meta = validate_paginated(response)
        assert len(rows) == 5, len(rows)
        assert meta["total_count"] == 12, meta
        assert meta["has_more"] is True, meta

    def test_gift_card_list_above_the_maximum_limit_is_an_invalid_request(self, client):
        """"A limit outside 1 through 100, or a negative offset, is rejected with
        ERR_INVALID_REQUEST (HTTP 400)."

        Design: Corner/entities/gift_card_list_paginates_with_total_count_and_has_more
        """
        self._twelve_stocked_cards(client)

        response = client.list_gift_cards(
            make_fraud_analyst_headers("analyst-20"), {"limit": 101}
        )

        validate_error(response, ERR_INVALID_REQUEST, 400)

    def test_gift_card_read_with_an_absent_id_is_not_found(self, client):
        """"then gift-card references (a path card id, a card_id, or a
        reissued_from_card_id, otherwise ERR_CARD_NOT_FOUND, 404 — applying to reading one
        card, recording and listing balance inquiries on a card, redeeming, placing and
        listing holds on a card, listing a card's reseller listings, overriding a card's
        posture, opening an issuance request, raising a draining alert, filing a victim
        claim and submitting a reseller listing)".

        Design: Corner/entities/gift_card_get_with_unknown_id_is_not_found
        """
        analyst = make_fraud_analyst_headers("analyst-21")
        create_store(
            client, name="Elm Street Pharmacy", region_code="NE", address_line="5 Elm St"
        )

        response = client.get_gift_card(ABSENT_UUID, analyst)

        validate_error(response, ERR_CARD_NOT_FOUND, 404)
        assert total_count(client.list_gift_cards(analyst)) == 0


class TestRiskPolicyDefaults:
    """The always-present configuration row read against an untouched database."""

    def test_risk_policy_read_returns_all_eighteen_declared_defaults(self, client):
        """"A single, always-present configuration row supplies every threshold, limit and
        rate this system reasons about."
        "It is seeded at process start with all of the defaults below, so reading it
        succeeds against an empty database, and it is updated by partial write: only the
        keys supplied on the update are overwritten, and omitted keys retain their current
        values."

        Design: Corner/entities/risk_policy_get_on_empty_database_returns_the_declared_defaults
        """
        response = client.get_risk_policy(make_liability_accountant_headers("acct-20"))

        policy = validate_success(response, 200)
        assert len(POLICY_DEFAULTS) == 18
        for setting, default in POLICY_DEFAULTS.items():
            assert policy[setting] == default, (
                f"{setting}: expected the declared default {default}, got {policy.get(setting)}"
            )
        assert policy["inquiry_velocity_window_minutes"] == 60
        assert policy["inquiry_velocity_threshold"] == 5
        assert policy["redemption_window_minutes"] == 1440
        assert policy["drain_watch_score_threshold"] == 40
        assert policy["drain_restrict_score_threshold"] == 70
        assert policy["digital_hold_score_threshold"] == 45
        assert policy["digital_decline_score_threshold"] == 75
        assert policy["bulk_identity_threshold_cents"] == 50000
        assert policy["bulk_quantity_limit"] == 25
        assert policy["rack_shrink_threshold"] == 3
        assert policy["rack_seal_break_threshold"] == 3
        assert policy["floor_heightened_alert_threshold"] == 2
        assert policy["claim_window_days"] == 90
        assert policy["claim_evidence_round_limit"] == 3
        assert policy["reissue_cap_cents"] == 100000
        assert policy["recovery_factor_bps"] == 8500
        assert policy["provisional_reserve_rate_bps"] == 3500
        assert policy["final_reserve_rate_bps"] == 1000

    def test_risk_policy_read_reports_the_untouched_singleton_at_version_one(self, client):
        """"version, an integer that starts at 1 on creation and increases by exactly 1 on
        every mutation".
        "Updating the register increments its version by 1 and never retroactively
        recomputes anything already persisted — a screening score, an activation fee or a
        booked reserve stays on the constants that produced it."

        Design: Corner/entities/risk_policy_get_on_empty_database_returns_the_declared_defaults
        """
        response = client.get_risk_policy(make_liability_accountant_headers("acct-20"))

        policy = validate_success(response, 200)
        assert policy["version"] == 1, policy["version"]


class TestGiftCardCreationInputSurface:
    """What POST /gift-cards accepts, and what it refuses."""

    def _store_and_rack(self, client, store_name, rack_label):
        store = create_store(client, name=store_name, region_code="SW", address_line="77 Foothill Rd")
        rack = create_rack(client, store["id"], rack_label=rack_label, expected_card_count=5)
        return store, rack

    def test_gift_card_create_never_honours_a_client_supplied_balance(self, client):
        """"No endpoint accepts a derived field as input, and an attempt to supply one is
        simply ignored rather than honoured."
        "The card is created with channel PHYSICAL, a funding state of INACTIVE, a fraud
        posture of CLEAR, face_value_cents of 0 and every balance figure at 0."
        "A gift card's money is never stored as a number that anyone writes."

        Design: Corner/entities/gift_card_create_rejects_a_client_supplied_computed_balance
        """
        admin = make_platform_admin_headers()
        store, rack = self._store_and_rack(client, "Foothill Grocer", "RACK-F1")

        response = client.create_gift_card(
            gift_card_payload(
                store["id"],
                rack["id"],
                card_number_masked="****-****-****-3101",
                current_balance_cents=50000,
            ),
            make_pos_associate_headers(),
        )

        card = validate_success(response, 201)
        assert card["current_balance_cents"] == 0, card["current_balance_cents"]
        assert card["available_balance_cents"] == 0, card["available_balance_cents"]
        assert card["face_value_cents"] == 0, card["face_value_cents"]
        assert card["activation_state"] == "INACTIVE", card["activation_state"]
        assert total_count(client.list_ledger_events(admin)) == 0

    def test_gift_card_create_with_a_masked_number_off_pattern_is_an_invalid_request(
        self, client
    ):
        """"card_number_masked, when supplied, must match the masked-PAN pattern of four
        asterisks, a hyphen, four asterisks, a hyphen, four asterisks, a hyphen and then
        exactly four digits".
        "Any failure is ERR_INVALID_REQUEST (400)."

        Design: Corner/entities/gift_card_masked_number_violating_its_pattern_is_invalid_request
        """
        admin = make_platform_admin_headers()
        store, rack = self._store_and_rack(client, "Sandhill Market", "RACK-SH")

        response = client.create_gift_card(
            gift_card_payload(
                store["id"], rack["id"], card_number_masked="1234-5678-9012-3456"
            ),
            make_pos_associate_headers(),
        )

        validate_error(response, ERR_INVALID_REQUEST, 400)
        assert total_count(client.list_gift_cards(admin, {"rack_id": rack["id"]})) == 0


class TestLedgerEventSystemFields:
    """The append the register produces, stamped entirely by the server."""

    def _active_card(self, client, face_value_cents, store_name, rack_label):
        """A store, an INTACT rack, a stocked card and a screened physical issuance: an OPEN
        floor "drives the request straight to APPROVED", which funds the card."""
        store = create_store(
            client, name=store_name, region_code="MW", address_line="40 Copper Creek"
        )
        rack = create_rack(client, store["id"], rack_label=rack_label, expected_card_count=5)
        built = funded_physical_card(client, face_value_cents, store=store, rack=rack)
        assert built["card"]["activation_state"] == "ACTIVE", built["card"]["activation_state"]
        return built

    def test_redemption_event_is_stamped_with_the_clock_and_the_calling_identity(self, client):
        """"Each ledger event names the card_id whose balance it moves and carries an
        amount_cents that is always a positive magnitude of at least 1, together with a type
        fixed by the operation that produced it, an occurred_at stamped from the logical
        clock at append time, a created_by_user_id recording the caller's X-User-ID, and
        optionally the pos_terminal_id of the register or channel that produced the movement
        and a free-text memo."
        "The debit kinds, whose signed_amount_cents is the negated amount, are REDEMPTION,
        REISSUE_DEBIT and REISSUE_CREDIT_REVERSAL."

        Design: Corner/entities/ledger_event_stamps_occurred_at_and_created_by_user_id_server_side
        """
        built = self._active_card(client, 6000, "Copper Creek Store", "RACK-CC")

        response = client.create_redemption(
            built["card"]["id"],
            redemption_payload(
                2500,
                built["store"]["id"],
                pos_terminal_id="T-30",
                memo="coffee and pastry",
            ),
            make_pos_associate_headers("pos-30"),
        )

        event = validate_success(response, 201)
        assert parse_instant(event["occurred_at"]) == parse_instant(CLOCK_ORIGIN)
        assert_three_fraction_digits(event["occurred_at"])
        assert event["created_by_user_id"] == "pos-30", event["created_by_user_id"]
        assert event["type"] == "REDEMPTION", event["type"]
        assert event["amount_cents"] == 2500
        assert event["signed_amount_cents"] == -2500
        assert_signed_amount(event)
        assert event["memo"] == "coffee and pastry"
        assert_empty(event.get("reverses_event_id"), "reverses_event_id")

    def test_redemption_event_drives_the_card_projection_down_to_the_remainder(self, client):
        """"current_balance_cents is the sum of every event's signed amount."
        "A REDEMPTION event is appended with occurred_at at the logical now, every balance
        and pattern figure is re-derived, and the card's version increments."

        Design: Corner/entities/ledger_event_stamps_occurred_at_and_created_by_user_id_server_side
        """
        built = self._active_card(client, 6000, "Copper Creek Store", "RACK-CC")

        redeem(
            client,
            built["card"]["id"],
            2500,
            built["store"]["id"],
            headers=make_pos_associate_headers("pos-30"),
            pos_terminal_id="T-30",
            memo="coffee and pastry",
        )

        card = read_card(client, built["card"]["id"])
        assert card["current_balance_cents"] == 3500, card["current_balance_cents"]


class TestLedgerEventImmutability:
    """"A ledger event is corrected only by appending another ledger event"."""

    def _card_with_one_redemption(self, client):
        """A 6000-cent ACTIVE card and one 1000-cent redemption taken at its own store."""
        store = create_store(
            client, name="Ledger Lane Foods", region_code="MW", address_line="3 Ledger Ln"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-LL", expected_card_count=5)
        built = funded_physical_card(client, 6000, store=store, rack=rack)
        event = redeem(
            client,
            built["card"]["id"],
            1000,
            store["id"],
            pos_terminal_id="T-34",
        )
        return {"store": store, "card": built["card"], "event": event}

    def test_ledger_event_read_carries_no_version_and_no_updated_at(self, client):
        """"Ledger events, balance inquiries and law-enforcement referrals carry only id and
        created_at: they have no updated_at and no version at all, and no update, delete or
        state-transition endpoint exists for any of them."

        Design: Corner/entities/ledger_event_is_immutable_with_no_version_and_no_write_endpoint
        """
        world = self._card_with_one_redemption(client)

        response = client.get_ledger_event(
            world["event"]["id"], make_liability_accountant_headers("acct-34")
        )

        event = validate_success(response, 200)
        assert event["type"] == "REDEMPTION", event["type"]
        assert event["amount_cents"] == 1000
        assert_create_only_fields(event)
        assert "version" not in event, "a ledger event must expose no version"
        assert "updated_at" not in event, "a ledger event must expose no updated_at"
        assert parse_instant(event["created_at"]) == parse_instant(CLOCK_ORIGIN)
        assert parse_instant(event["occurred_at"]) == parse_instant(CLOCK_ORIGIN)

    def test_the_card_ledger_holds_both_appends_in_chronological_order(self, client):
        """"the global ledger-event list are ordered by occurred_at ascending with
        created_at ascending as tie-break".
        "That pair is a total order because created_at is unique per append, and the card's
        id is never consulted."

        Design: Corner/entities/ledger_event_is_immutable_with_no_version_and_no_write_endpoint
        """
        world = self._card_with_one_redemption(client)

        response = client.list_ledger_events(
            make_liability_accountant_headers("acct-34"), {"card_id": world["card"]["id"]}
        )

        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 2, meta
        assert [row["type"] for row in rows] == ["ACTIVATION_LOAD", "REDEMPTION"], rows
        assert_ordered_by(rows, "occurred_at")


class TestDrainingAlertEnumSurface:
    """The detection basis a manually raised alert may declare."""

    def test_draining_alert_with_an_undeclared_detection_basis_is_an_invalid_request(
        self, client
    ):
        """"a FraudAnalyst or a RiskManager may raise one manually against a card_id, stating
        the detection_basis — INQUIRY_VELOCITY, REDEMPTION_PATTERN, RESELLER_SIGNAL or
        MANUAL_REVIEW — and optionally a note explaining why."
        "every enum-typed field carries one of its declared values".
        "Any failure is ERR_INVALID_REQUEST (400)."

        Design: Corner/entities/draining_alert_with_undeclared_detection_basis_is_invalid_request
        """
        admin = make_platform_admin_headers()
        store = create_store(
            client, name="Pine Hollow Store", region_code="NE", address_line="2 Pine Hollow"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-PH", expected_card_count=5)
        built = funded_physical_card(client, 4000, store=store, rack=rack)
        card_id = built["card"]["id"]

        response = client.create_draining_alert(
            draining_alert_payload(
                card_id, detection_basis="GUT_FEELING", note="not a declared basis"
            ),
            make_fraud_analyst_headers("analyst-33"),
        )

        validate_error(response, ERR_INVALID_REQUEST, 400)
        assert total_count(client.list_draining_alerts(admin, {"card_id": card_id})) == 0
        card = read_card(client, card_id)
        assert card["risk_posture"] == "CLEAR", card["risk_posture"]


class TestResellerListingParentResolution:
    """Every cross-reference on a listing submission is resolved at write time."""

    def test_reseller_listing_under_an_absent_card_is_not_found(self, client):
        """"then gift-card references (a path card id, a card_id, or a
        reissued_from_card_id, otherwise ERR_CARD_NOT_FOUND, 404 — applying to reading one
        card, recording and listing balance inquiries on a card, redeeming, placing and
        listing holds on a card, listing a card's reseller listings, overriding a card's
        posture, opening an issuance request, raising a draining alert, filing a victim
        claim and submitting a reseller listing)".

        Design: Corner/entities/reseller_listing_under_unknown_card_is_not_found
        """
        partner = make_reseller_partner_headers("partner-35")
        store = create_store(
            client, name="Marketplace Depot", region_code="SW", address_line="14 Depot Rd"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-MD", expected_card_count=5)
        built = funded_physical_card(client, 3000, store=store, rack=rack)

        response = client.create_reseller_listing(
            reseller_listing_payload(
                ABSENT_UUID,
                3000,
                marketplace_name="GiftBay",
                asking_price_cents=2500,
            ),
            partner,
        )

        validate_error(response, ERR_CARD_NOT_FOUND, 404)
        assert total_count(client.list_reseller_listings(partner)) == 0
        assert (
            total_count(client.list_card_reseller_listings(built["card"]["id"], partner)) == 0
        )
