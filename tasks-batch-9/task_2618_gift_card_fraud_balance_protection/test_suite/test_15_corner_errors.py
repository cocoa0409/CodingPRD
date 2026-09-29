"""Referenced-resource existence and transition-legality refusals.

Two families of refusal live here.  The first probes each action endpoint with a
well-formed but absent path identifier, because "Referenced-resource existence"
is its own rung of the validation ladder and every unresolvable reference has
its own 404 code.  The second replays an operation whose target has already
left the only state that admits it, which "Per-entity transition legality"
rejects "with its own conflict code (409)".

Every probe uses one well-formed identifier that no resource in the database
carries, so a 404 can never be confused with a 400 well-formedness rejection.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ALERT_NOT_FOUND,
    ERR_BULK_ORDER_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_HOLD_NOT_FOUND,
    ERR_INVALID_BULK_ORDER_STATE,
    ERR_INVALID_LISTING_STATE,
    ERR_ISSUANCE_REQUEST_NOT_FOUND,
    ERR_LEDGER_EVENT_ALREADY_REVERSED,
    ERR_LEDGER_EVENT_NOT_FOUND,
    ERR_LISTING_NOT_FOUND,
    ERR_PERIOD_NOT_FOUND,
    ERR_RACK_NOT_FOUND,
)
from test_helpers.constants import ABSENT_UUID, CLOCK_ORIGIN
from test_helpers.factories import (
    bulk_decision_payload,
    claim_decision_payload,
    hold_settlement_payload,
    identity_payload,
    listing_validation_payload,
    period_close_payload,
    rack_audit_payload,
    reversal_payload,
    triage_payload,
)
from test_helpers.fixtures import (
    create_rack,
    create_store,
    funded_physical_card,
    open_bulk_order,
    open_period,
    parse_instant,
    read_card,
    read_period,
    read_rack,
    read_store,
    redeem,
    submit_listing,
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


class TestAuditOnUnknownRack:
    """A rack audit posted at an identifier no rack carries."""

    def _one_intact_rack(self, client):
        """One store and one rack that has never been audited, neither of which is the
        target of the probe."""
        store = create_store(
            client, name="Rack 404 Store", region_code="NE", address_line="48 Rack Rd"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-404", expected_card_count=5
        )
        return {"store": store, "rack": rack}

    def test_audit_at_an_absent_rack_id_is_rack_not_found(self, client):
        """"then rack references (a path rack id or a `rack_id`, otherwise
        `ERR_RACK_NOT_FOUND`, 404 — applying to reading one rack, auditing a rack,
        clearing a rack's tamper flag, stocking a card, and opening an issuance
        request)"
        "The `error_id` is a unique, machine-readable string that identifies the
        specific error."
        "The `meta` object for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/rack_audit_on_unknown_rack_is_not_found
        """
        self._one_intact_rack(client)

        response = client.audit_card_rack(
            ABSENT_UUID,
            rack_audit_payload(observed_card_count=5, seal_breaks_observed=0),
            make_pos_associate_headers(),
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_RACK_NOT_FOUND, 404)
        body = response.json()
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
            f"error meta must carry only the two request keys, got {body['meta']}"
        )

    def test_the_real_rack_and_its_store_are_left_untouched(self, client):
        """"A newly registered rack is `INTACT`, with `missing_card_count` 0,
        `seal_breaks_observed` 0, and both `observed_card_count` and `last_audit_at`
        still empty because no audit has run."
        "It is born with a `floor_posture` of `OPEN` and every derived counter —
        `tampered_rack_count`, `suspect_rack_count`, `open_alert_count` and
        `declined_issuance_count` — sitting at 0."

        Design: Corner/errors/rack_audit_on_unknown_rack_is_not_found
        """
        world = self._one_intact_rack(client)

        client.audit_card_rack(
            ABSENT_UUID,
            rack_audit_payload(observed_card_count=5, seal_breaks_observed=0),
            make_pos_associate_headers(),
        )

        rack = read_rack(client, world["rack"]["id"])
        assert rack["tamper_state"] == "INTACT"
        assert not rack.get("last_audit_at"), (
            f"last_audit_at must stay empty, got {rack.get('last_audit_at')!r}"
        )
        assert read_store(client, world["store"]["id"])["floor_posture"] == "OPEN"


class TestScreenOnUnknownIssuanceRequest:
    """Screening an issuance request that was never opened."""

    def test_screening_an_absent_request_is_issuance_request_not_found(self, client):
        """"then the issuance request named by the path
        (`ERR_ISSUANCE_REQUEST_NOT_FOUND`, 404 — reading, screening and deciding an
        issuance request)"

        Design: Corner/errors/issuance_screen_on_unknown_request_is_not_found
        """
        create_store(
            client, name="Issuance 404 Store", region_code="MW", address_line="49 Issue Ln"
        )

        response = client.screen_issuance_request(
            ABSENT_UUID, make_pos_associate_headers()
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_ISSUANCE_REQUEST_NOT_FOUND, 404)

    def test_the_refused_screening_creates_no_issuance_request(self, client):
        """"List responses carry `limit`, `offset`, `total_count` and `has_more` in the
        `meta` block, where `total_count` is the number of records matching the filters
        before the window is applied and `has_more` indicates whether records remain
        beyond the current window."

        Design: Corner/errors/issuance_screen_on_unknown_request_is_not_found
        """
        create_store(
            client, name="Issuance 404 Store", region_code="MW", address_line="49 Issue Ln"
        )

        client.screen_issuance_request(ABSENT_UUID, make_pos_associate_headers())

        listed = client.list_issuance_requests(make_platform_admin_headers())
        assert total_count(listed) == 0


class TestDecideOnUnknownBulkOrder:
    """A decline decision aimed at an identifier no bulk order carries."""

    def test_deciding_an_absent_order_is_bulk_order_not_found(self, client):
        """"then bulk-order references by path or `bulk_order_id`
        (`ERR_BULK_ORDER_NOT_FOUND`, 404 — reading a bulk order, verifying its identity,
        deciding it, and opening an issuance request that links to it)"

        Design: Corner/errors/bulk_order_decide_on_unknown_order_is_not_found
        """
        create_store(
            client, name="Bulk 404 Store", region_code="SE", address_line="50 Bulk Blvd"
        )

        response = client.decide_bulk_purchase_order(
            ABSENT_UUID,
            bulk_decision_payload("DECLINE", decision_note="no such order"),
            make_risk_manager_headers("risk-75"),
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_BULK_ORDER_NOT_FOUND, 404)
        listed = client.list_bulk_purchase_orders(make_platform_admin_headers())
        assert total_count(listed) == 0


class TestTriageOnUnknownAlert:
    """Triaging a draining alert that does not exist."""

    def test_triaging_an_absent_alert_is_alert_not_found(self, client):
        """"then draining-alert references by path or `alert_id` (`ERR_ALERT_NOT_FOUND`,
        404 — reading, triaging, resolving and reopening an alert, listing its referrals,
        filing a referral, and filing a victim claim that links to it)"

        Design: Corner/errors/alert_triage_on_unknown_alert_is_not_found
        """
        response = client.triage_draining_alert(
            ABSENT_UUID,
            triage_payload(triage_note="no such alert", redemption_pattern_reviewed=True),
            make_fraud_analyst_headers("analyst-76"),
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_ALERT_NOT_FOUND, 404)
        listed = client.list_draining_alerts(make_platform_admin_headers())
        assert total_count(listed) == 0


class TestDecideOnUnknownClaim:
    """An approval decision aimed at an identifier no victim claim carries."""

    def _one_open_period(self, client):
        """One OPEN accounting period covering the logical now, so a stray write-off from
        the reissue cascade would be visible on it."""
        return open_period(
            client,
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            label="2026-08 claim 404",
        )

    def test_deciding_an_absent_claim_is_claim_not_found(self, client):
        """"then the victim claim named by the path (`ERR_CLAIM_NOT_FOUND`, 404 — reading
        a claim, requesting and resubmitting evidence, deciding and rescinding it)"

        Design: Corner/errors/claim_decide_on_unknown_claim_is_not_found
        """
        self._one_open_period(client)

        response = client.decide_victim_claim(
            ABSENT_UUID,
            claim_decision_payload("APPROVE", decision_note="no such claim"),
            make_risk_manager_headers("risk-77"),
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_CLAIM_NOT_FOUND, 404)
        listed = client.list_victim_claims(make_platform_admin_headers())
        assert total_count(listed) == 0

    def test_no_liability_period_is_written_off(self, client):
        """"A new period is created in `OPEN` with `unauthorized_writeoff_cents` at 0,
        `restatement_count` at 0, and `outstanding_liability_cents`,
        `gross_exposure_cents`, `reserve_basis_alert_count`, `provisional_reserve_cents`,
        `final_reserve_cents`, `closed_at`, `restated_at`, `close_note` and
        `restatement_note` all empty."

        Design: Corner/errors/claim_decide_on_unknown_claim_is_not_found
        """
        period = self._one_open_period(client)

        client.decide_victim_claim(
            ABSENT_UUID,
            claim_decision_payload("APPROVE", decision_note="no such claim"),
            make_risk_manager_headers("risk-77"),
        )

        after = read_period(client, period["id"])
        assert after["unauthorized_writeoff_cents"] == 0
        assert after["state"] == "OPEN"


class TestValidateOnUnknownListing:
    """Validating a reseller listing that was never submitted."""

    def test_validating_an_absent_listing_is_listing_not_found(self, client):
        """"then the reseller listing named by the path (`ERR_LISTING_NOT_FOUND`, 404 —
        validating a listing)"

        Design: Corner/errors/listing_validate_on_unknown_listing_is_not_found
        """
        response = client.validate_reseller_listing(
            ABSENT_UUID,
            listing_validation_payload(validation_note="no such listing"),
            make_fraud_analyst_headers("analyst-78"),
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_LISTING_NOT_FOUND, 404)
        listed = client.list_reseller_listings(make_platform_admin_headers())
        assert total_count(listed) == 0


class TestCloseOnUnknownPeriod:
    """Closing an accounting period at an identifier no period carries."""

    def _one_open_period(self, client):
        """One OPEN period that is not the target of the probe."""
        return open_period(
            client,
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            label="2026-08 period 404",
        )

    def test_closing_an_absent_period_is_period_not_found(self, client):
        """"then the accounting period named by the path (`ERR_PERIOD_NOT_FOUND`, 404 —
        reading a period, closing it, restating it, and reading its exposure summary)"

        Design: Corner/errors/period_close_on_unknown_period_is_not_found
        """
        self._one_open_period(client)

        response = client.close_liability_period(
            ABSENT_UUID,
            period_close_payload(close_note="no such period"),
            make_liability_accountant_headers("acct-79"),
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_PERIOD_NOT_FOUND, 404)

    def test_the_real_open_period_is_not_closed_as_a_side_effect(self, client):
        """"A new period is created in `OPEN` with `unauthorized_writeoff_cents` at 0,
        `restatement_count` at 0, and `outstanding_liability_cents`,
        `gross_exposure_cents`, `reserve_basis_alert_count`, `provisional_reserve_cents`,
        `final_reserve_cents`, `closed_at`, `restated_at`, `close_note` and
        `restatement_note` all empty."
        "Most resources additionally expose `updated_at`, formatted identically, and
        `version`, an integer that starts at 1 on creation and increases by exactly 1 on
        every mutation — including mutations that arrive as a cascaded side effect of an
        operation on a different resource."

        Design: Corner/errors/period_close_on_unknown_period_is_not_found
        """
        period = self._one_open_period(client)

        client.close_liability_period(
            ABSENT_UUID,
            period_close_payload(close_note="no such period"),
            make_liability_accountant_headers("acct-79"),
        )

        after = read_period(client, period["id"])
        assert after["state"] == "OPEN"
        assert not after.get("closed_at"), (
            f"closed_at must stay empty, got {after.get('closed_at')!r}"
        )
        assert after["version"] == period["version"]


class TestReverseOnUnknownLedgerEvent:
    """Reversing a ledger event that does not exist."""

    def test_reversing_an_absent_event_is_ledger_event_not_found(self, client):
        """"then ledger-event references by path or `reverses_event_id`, which must
        resolve to an existing event on the same card (`ERR_LEDGER_EVENT_NOT_FOUND`, 404 —
        reading one event and reversing one)"

        Design: Corner/errors/ledger_reverse_on_unknown_event_is_not_found
        """
        response = client.reverse_ledger_event(
            ABSENT_UUID,
            reversal_payload(reversal_reason="no such event"),
            make_risk_manager_headers("risk-80"),
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_LEDGER_EVENT_NOT_FOUND, 404)
        listed = client.list_ledger_events(make_platform_admin_headers())
        assert total_count(listed) == 0


class TestSettleOnUnknownHold:
    """Settling a redemption hold that does not exist."""

    def test_settling_an_absent_hold_is_hold_not_found(self, client):
        """"and finally the redemption hold named by the path (`ERR_HOLD_NOT_FOUND`, 404 —
        settling a hold)"

        Design: Corner/errors/hold_settle_on_unknown_hold_is_not_found
        """
        response = client.settle_redemption_hold(
            ABSENT_UUID,
            hold_settlement_payload("RELEASE", settle_note="no such hold"),
            make_risk_manager_headers("risk-81"),
        )

        assert response.status_code == 404, response.text
        validate_error(response, ERR_HOLD_NOT_FOUND, 404)
        listed = client.list_ledger_events(make_platform_admin_headers())
        assert total_count(listed) == 0


class TestIdentityCaptureOnAnAlreadyVerifiedOrder:
    """An order priced below the identity threshold never admits an identity capture."""

    def _small_order(self, client):
        """One store, and one bulk order of a single 2000-cent card: a subtotal of 2000
        cents attracts no fee, so the total of 2000 cents sits below the identity
        threshold."""
        store = create_store(
            client, name="Auto Verified Store", region_code="NW", address_line="51 Auto Ave"
        )
        order = open_bulk_order(
            client,
            store["id"],
            card_quantity=1,
            face_value_cents_each=2000,
            purchaser_name="Small Office Gifts",
            payment_method="CASH",
        )
        return {"store": store, "order": order}

    def test_a_sub_threshold_total_is_identity_verified_at_creation(self, client):
        """"First, `face_value_subtotal_cents` is the card quantity multiplied by the
        per-card face value — exact, with no rounding required."
        "Second, `fee_rate_bps` is selected **from that pre-fee subtotal**, as a
        whole-order average-rate band rather than a marginal ladder, so exactly one rate
        applies to the entire subtotal: a subtotal below 25000 cents attracts no fee at
        all; from 25000 up to but not including 100000 cents the rate is 150 basis points;
        from 100000 up to but not including 500000 cents it is 225 basis points; and at
        500000 cents or above it is 300 basis points."
        "Fourth, `total_cents` is the subtotal plus the activation fee."
        "When the total is strictly below the threshold the order is already
        `IDENTITY_VERIFIED` in the creation response, with all three identity fields left
        empty because none is required."

        Design: Corner/errors/bulk_identity_verification_twice_is_invalid_bulk_order_state
        """
        order = self._small_order(client)["order"]

        assert order["face_value_subtotal_cents"] == 2000
        assert order["activation_fee_cents"] == 0
        assert order["total_cents"] == 2000
        assert order["state"] == "IDENTITY_VERIFIED"

    def test_capturing_identity_on_that_order_is_invalid_bulk_order_state(self, client):
        """"Identity capture is performed by a `PosAssociate` or a `StoreManager` on an
        order in `PENDING_IDENTITY`, supplying `id_type`, `id_number_hash` and
        `id_expiry_date`."
        "a bulk order must be `PENDING_IDENTITY` for identity verification and
        `PENDING_IDENTITY` or `IDENTITY_VERIFIED` to be decided, with the
        request-more-information decision admitted only from `IDENTITY_VERIFIED`, otherwise
        `ERR_INVALID_BULK_ORDER_STATE`"

        Design: Corner/errors/bulk_identity_verification_twice_is_invalid_bulk_order_state
        """
        order = self._small_order(client)["order"]

        response = client.verify_bulk_order_identity(
            order["id"],
            identity_payload(
                id_type="DRIVERS_LICENSE",
                id_number_hash="idh-82",
                id_expiry_date="2029-06-30",
            ),
            make_pos_associate_headers(),
        )

        assert response.status_code == 409, response.text
        validate_error(response, ERR_INVALID_BULK_ORDER_STATE, 409)

    def test_the_refused_capture_writes_nothing_on_the_order(self, client):
        """"When the total is strictly below the threshold the order is already
        `IDENTITY_VERIFIED` in the creation response, with all three identity fields left
        empty because none is required."
        "Most resources additionally expose `updated_at`, formatted identically, and
        `version`, an integer that starts at 1 on creation and increases by exactly 1 on
        every mutation — including mutations that arrive as a cascaded side effect of an
        operation on a different resource."

        Design: Corner/errors/bulk_identity_verification_twice_is_invalid_bulk_order_state
        """
        order = self._small_order(client)["order"]

        client.verify_bulk_order_identity(
            order["id"],
            identity_payload(
                id_type="DRIVERS_LICENSE",
                id_number_hash="idh-82",
                id_expiry_date="2029-06-30",
            ),
            make_pos_associate_headers(),
        )

        after = validate_success(
            client.get_bulk_purchase_order(order["id"], make_platform_admin_headers())
        )
        assert not after.get("identity_id_number_hash"), (
            "the refused capture must write no identity hash, got "
            f"{after.get('identity_id_number_hash')!r}"
        )
        assert after["state"] == "IDENTITY_VERIFIED"
        assert after["version"] == order["version"]


class TestSecondValidationOfAValidatedListing:
    """Validation is admitted only from SUBMITTED, so it never runs twice."""

    def _submitted_listing(self, client):
        """One store, one INTACT rack, one ACTIVE 5000-cent PHYSICAL card whose posture is
        CLEAR, and one SUBMITTED listing quoting exactly that balance."""
        store = create_store(
            client, name="Revalidate Store", region_code="SW", address_line="52 Revalidate Rd"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-RV", expected_card_count=5
        )
        built = funded_physical_card(client, 5000, store=store, rack=rack)
        listing = submit_listing(
            client,
            built["card"]["id"],
            5000,
            "GiftBay",
            headers=make_reseller_partner_headers("partner-83"),
            asking_price_cents=4800,
        )
        return {"card": built["card"], "listing": listing}

    def test_the_first_validation_passes_every_check_and_reaches_validated(self, client):
        """"The listing is created in state `SUBMITTED`, with `reseller_partner_id`
        recorded from the submitting partner's `X-User-ID` — an opaque operator identifier
        and explicitly not a foreign key to any entity — and with `block_reason` empty."
        "Otherwise the listing becomes `VALIDATED` and `block_reason` stays empty."

        Design: Corner/errors/listing_validate_twice_is_invalid_listing_state
        """
        world = self._submitted_listing(client)
        assert world["listing"]["state"] == "SUBMITTED"
        assert world["card"]["current_balance_cents"] == 5000
        assert world["card"]["risk_posture"] == "CLEAR"

        response = client.validate_reseller_listing(
            world["listing"]["id"],
            listing_validation_payload(validation_note="first pass"),
            make_fraud_analyst_headers("analyst-83"),
        )

        assert response.status_code == 200, response.text
        first = validate_success(response, 200)
        assert first["state"] == "VALIDATED"
        assert not first.get("block_reason"), (
            f"block_reason must stay empty, got {first.get('block_reason')!r}"
        )

    def test_the_second_identical_validation_is_invalid_listing_state(self, client):
        """"Validation is exclusively a `FraudAnalyst` operation, is admitted only from
        `SUBMITTED`, accepts an optional `validation_note`, and records
        `validated_by_user_id` from the caller."
        "a reseller listing must be `SUBMITTED` to be validated, otherwise
        `ERR_INVALID_LISTING_STATE`"
        "Every validation increments the listing's `version`."

        Design: Corner/errors/listing_validate_twice_is_invalid_listing_state
        """
        world = self._submitted_listing(client)
        first = validate_success(
            client.validate_reseller_listing(
                world["listing"]["id"],
                listing_validation_payload(validation_note="first pass"),
                make_fraud_analyst_headers("analyst-83"),
            ),
            200,
        )

        response = client.validate_reseller_listing(
            world["listing"]["id"],
            listing_validation_payload(validation_note="second pass"),
            make_fraud_analyst_headers("analyst-83"),
        )

        assert response.status_code == 409, response.text
        validate_error(response, ERR_INVALID_LISTING_STATE, 409)
        after = validate_success(
            client.get_reseller_listing(world["listing"]["id"], make_platform_admin_headers())
        )
        assert after["state"] == "VALIDATED"
        assert not after.get("block_reason"), (
            f"block_reason must stay empty, got {after.get('block_reason')!r}"
        )
        assert after["version"] == first["version"]


class TestDoubleReversalOfOneRedemption:
    """A redemption may be compensated once, and only once."""

    def _fully_drained_card(self, client):
        """One store, one INTACT rack and one ACTIVE 10000-cent PHYSICAL card, redeemed
        for its whole balance at that same store."""
        store = create_store(
            client, name="Double Reversal Store", region_code="NE", address_line="53 Reverse Row"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-DR", expected_card_count=5
        )
        built = funded_physical_card(client, 10000, store=store, rack=rack)
        event = redeem(
            client,
            built["card"]["id"],
            10000,
            store["id"],
            pos_terminal_id="T-84",
        )
        return {"store": store, "card_id": built["card"]["id"], "event": event}

    def test_the_full_redemption_signs_negative_and_depletes_the_card(self, client):
        """"The debit kinds, whose `signed_amount_cents` is the negated amount, are
        `REDEMPTION`, `REISSUE_DEBIT` and `REISSUE_CREDIT_REVERSAL`."
        "Whenever an append or a reversal leaves an `ACTIVE` card's re-derived
        `current_balance_cents` at exactly zero, the card transitions `ACTIVE → DEPLETED`
        and its `version` increments."

        Design: Corner/errors/double_reversal_of_the_same_redemption_is_rejected
        """
        world = self._fully_drained_card(client)

        assert world["event"]["signed_amount_cents"] == -10000
        card = read_card(client, world["card_id"])
        assert card["activation_state"] == "DEPLETED"
        assert card["current_balance_cents"] == 0

    def test_the_first_reversal_appends_a_credit_and_lifts_the_card_back(self, client):
        """"A new `REDEMPTION_REVERSAL` event is appended, carrying the original's amount
        as a positive movement, with `reverses_event_id` pointing at the original, the
        supplied reason recorded as the new event's `memo`, and `occurred_at` at the logical
        now."
        "The credit kinds, whose `signed_amount_cents` is the positive amount, are
        `ACTIVATION_LOAD`, `REDEMPTION_REVERSAL`, `REISSUE_CREDIT` and
        `REISSUE_DEBIT_REVERSAL`."
        "Whenever an append or a reversal leaves a `DEPLETED` card's re-derived balance
        above zero, it transitions `DEPLETED → ACTIVE` and its `version` increments."
        "`total_loaded_cents` is the sum of the raw amounts over the credit kinds only."
        "`total_redeemed_cents` is the sum of `REDEMPTION` amounts minus the sum of
        `REDEMPTION_REVERSAL` amounts — equivalently, the sum of the amounts of the
        *unreversed* redemptions."
        "At process start the clock reads exactly `2026-08-01T00:00:00Z`, so a test that
        never moves it still observes a fixed, reproducible present."

        Design: Corner/errors/double_reversal_of_the_same_redemption_is_rejected
        """
        world = self._fully_drained_card(client)

        response = client.reverse_ledger_event(
            world["event"]["id"],
            reversal_payload(reversal_reason="terminal double-charged the customer"),
            make_risk_manager_headers("risk-84"),
        )

        assert response.status_code == 201, response.text
        reversal = validate_success(response, 201)
        assert reversal["type"] == "REDEMPTION_REVERSAL"
        assert reversal["reverses_event_id"] == world["event"]["id"]
        assert reversal["amount_cents"] == 10000
        assert reversal["signed_amount_cents"] == 10000
        assert parse_instant(reversal["occurred_at"]) == parse_instant(CLOCK_ORIGIN)

        card = read_card(client, world["card_id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 10000
        assert card["total_loaded_cents"] == 20000
        assert card["total_redeemed_cents"] == 0
        assert card["drawdown_ratio"] == 0.00

    def test_the_second_reversal_of_the_same_event_is_rejected(self, client):
        """"Only `REDEMPTION` events are reversible, and an event that some existing event
        already reverses cannot be reversed again; either violation is
        `ERR_LEDGER_EVENT_ALREADY_REVERSED`."
        "The original event is never mutated — history is append-only."

        Design: Corner/errors/double_reversal_of_the_same_redemption_is_rejected
        """
        world = self._fully_drained_card(client)
        validate_success(
            client.reverse_ledger_event(
                world["event"]["id"],
                reversal_payload(reversal_reason="terminal double-charged the customer"),
                make_risk_manager_headers("risk-84"),
            ),
            201,
        )

        response = client.reverse_ledger_event(
            world["event"]["id"],
            reversal_payload(reversal_reason="accidental replay of the reversal"),
            make_risk_manager_headers("risk-84"),
        )

        assert response.status_code == 409, response.text
        validate_error(response, ERR_LEDGER_EVENT_ALREADY_REVERSED, 409)

        reversals = client.list_ledger_events(
            make_platform_admin_headers(), {"reverses_event_id": world["event"]["id"]}
        )
        assert total_count(reversals) == 1, "exactly one reversal row may exist"
        all_events = client.list_ledger_events(
            make_platform_admin_headers(), {"card_id": world["card_id"]}
        )
        assert total_count(all_events) == 3, (
            "the card's ledger holds the activation load, the redemption and one reversal"
        )
