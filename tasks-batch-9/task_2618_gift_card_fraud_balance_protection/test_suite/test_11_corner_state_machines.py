"""Lifecycle machines: declared initial states, legal edges, and the doors that stay shut.

Every entity in this service carries a lifecycle, and the PRD pins each one from three
sides: the state a record is born in, the transitions that are legal out of it, and the
conflict code a caller sees when they aim at an edge that does not exist.  This file
walks those three sides one machine at a time — retail floors and racks, gift cards and
issuance requests, redemption holds, draining alerts, victim claims and accounting
periods — and checks that a refused transition moves no money and bumps no version.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_CARD_NOT_ACTIVE,
    ERR_INVALID_ALERT_STATE,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_HOLD_STATE,
    ERR_INVALID_ISSUANCE_STATE,
    ERR_INVALID_PERIOD_STATE,
)
from test_helpers.assertions import assert_card_projection, assert_empty, assert_store_counters
from test_helpers.constants import CLOCK_ORIGIN
from test_helpers.factories import (
    claim_decision_payload,
    evidence_resubmit_payload,
    hold_settlement_payload,
    period_close_payload,
    physical_issuance_payload,
    redemption_hold_payload,
    redemption_payload,
    rescind_payload,
    resolution_payload,
)
from test_helpers.fixtures import (
    audit_rack,
    close_period,
    create_rack,
    create_store,
    decide_bulk_order,
    decide_claim,
    file_claim,
    funded_physical_card,
    hold_on_card,
    open_alert,
    open_bulk_order,
    open_period,
    parse_instant,
    read_alert,
    read_card,
    read_claim,
    read_period,
    read_rack,
    read_store,
    redeem,
    reopen_alert,
    resolve_alert,
    settle_hold,
    shift,
    stock_card,
    total_count,
    triage_alert,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_liability_accountant_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_risk_manager_headers,
)


class TestDeclaredInitialStates:
    """Four machines, four declared birth states — none of them defaulted."""

    def _fresh_floor(self, client):
        """A brand-new store, a never-audited rack on it, and one card stocked onto that
        rack.  Nothing has been screened, audited or redeemed."""
        store = create_store(
            client, name="Initial State Foods", region_code="NE", address_line="1 Init Way"
        )
        rack = create_rack(
            client, store["id"], rack_label="RACK-I1", expected_card_count=6
        )
        card = stock_card(
            client, store["id"], rack["id"], card_number_masked="****-****-****-4001"
        )
        return {"store": store, "rack": rack, "card": card}

    def test_a_new_store_is_open_and_a_new_rack_is_intact(self, client):
        """"It is born with a floor_posture of OPEN and every derived counter —
        tampered_rack_count, suspect_rack_count, open_alert_count and
        declined_issuance_count — sitting at 0."
        "A newly registered rack is INTACT, with missing_card_count 0,
        seal_breaks_observed 0, and both observed_card_count and last_audit_at still empty
        because no audit has run."

        Design: Corner/state_machines/new_card_and_new_issuance_request_start_in_their_declared_initial_states
        """
        world = self._fresh_floor(client)

        assert_store_counters(
            world["store"],
            floor_posture="OPEN",
            tampered_rack_count=0,
            suspect_rack_count=0,
            open_alert_count=0,
            declined_issuance_count=0,
        )
        assert world["rack"]["tamper_state"] == "INTACT"
        assert world["rack"]["missing_card_count"] == 0
        assert world["rack"]["seal_breaks_observed"] == 0
        assert_empty(world["rack"]["observed_card_count"], "observed_card_count")
        assert_empty(world["rack"]["last_audit_at"], "last_audit_at")

    def test_a_stocked_card_is_inactive_and_clear_on_both_dimensions(self, client):
        """"The card is created with channel PHYSICAL, a funding state of INACTIVE, a fraud
        posture of CLEAR, face_value_cents of 0 and every balance figure at 0."
        "A card with no ledger events at all reports every figure as 0 and a
        drawdown_ratio of 0.00 — not empty, and not an error."

        Design: Corner/state_machines/new_card_and_new_issuance_request_start_in_their_declared_initial_states
        """
        world = self._fresh_floor(client)
        card = read_card(client, world["card"]["id"])

        assert card["channel"] == "PHYSICAL"
        assert card["activation_state"] == "INACTIVE"
        assert card["risk_posture"] == "CLEAR"
        assert card["face_value_cents"] == 0
        assert_card_projection(
            card,
            current_balance_cents=0,
            total_loaded_cents=0,
            total_redeemed_cents=0,
            held_amount_cents=0,
            available_balance_cents=0,
            drawdown_ratio=0.00,
        )

    def test_a_new_issuance_request_is_submitted_with_no_screening_trail(self, client):
        """"A request that survives all three is created in state SUBMITTED, with
        screening_score, screening_components and decline_reason all empty and screened_at
        not yet stamped."
        Creating a resource responds with "201 Created".

        Design: Corner/state_machines/new_card_and_new_issuance_request_start_in_their_declared_initial_states
        """
        world = self._fresh_floor(client)

        response = client.create_issuance_request(
            physical_issuance_payload(
                world["store"]["id"],
                world["rack"]["id"],
                world["card"]["id"],
                5000,
                pos_terminal_id="T-40",
            ),
            make_pos_associate_headers(),
        )

        request = validate_success(response, 201)
        assert request["state"] == "SUBMITTED"
        assert_empty(request["screening_score"], "screening_score")
        assert_empty(request["screening_components"], "screening_components")
        assert_empty(request["decline_reason"], "decline_reason")
        assert_empty(request["screened_at"], "screened_at")

    def test_opening_a_request_moves_no_value_onto_the_card(self, client):
        """"Reaching APPROVED is what funds a card ... a credit event of kind
        ACTIVATION_LOAD for that amount is appended to the card's ledger, all of its
        balance figures are re-derived, activated_at is stamped from the logical clock."
        "The card is created with channel PHYSICAL, a funding state of INACTIVE, a fraud
        posture of CLEAR, face_value_cents of 0 and every balance figure at 0."

        Design: Corner/state_machines/new_card_and_new_issuance_request_start_in_their_declared_initial_states
        """
        world = self._fresh_floor(client)

        validate_success(
            client.create_issuance_request(
                physical_issuance_payload(
                    world["store"]["id"],
                    world["rack"]["id"],
                    world["card"]["id"],
                    5000,
                    pos_terminal_id="T-40",
                ),
                make_pos_associate_headers(),
            ),
            201,
        )

        card = read_card(client, world["card"]["id"])
        assert card["activation_state"] == "INACTIVE"
        assert card["current_balance_cents"] == 0
        assert card["face_value_cents"] == 0
        events = client.list_ledger_events(
            make_liability_accountant_headers("acct-40"), {"card_id": world["card"]["id"]}
        )
        assert total_count(events) == 0


class TestScreeningActivatesTheCard:
    """One screen call drives two machines and appends exactly one credit event."""

    def _submitted_request(self, client):
        """A store with an OPEN floor, an INTACT rack, an INACTIVE card and a SUBMITTED
        PHYSICAL request for 7500 cents attesting an unbroken packaging seal."""
        store = create_store(
            client, name="Activation Test Store", region_code="MW", address_line="2 Activate Ave"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-A1", expected_card_count=6)
        card = stock_card(
            client, store["id"], rack["id"], card_number_masked="****-****-****-4101"
        )
        request = validate_success(
            client.create_issuance_request(
                physical_issuance_payload(
                    store["id"], rack["id"], card["id"], 7500, pos_terminal_id="T-41"
                ),
                make_pos_associate_headers(),
            ),
            201,
        )
        return {"store": store, "rack": rack, "card": card, "request": request}

    def test_an_open_floor_screens_the_request_straight_to_approved(self, client):
        """"For a PHYSICAL request, the fork reads the referenced store's floor posture: an
        OPEN floor drives the request straight to APPROVED, a HEIGHTENED floor drives it to
        HELD_FOR_REVIEW, and a SUSPENDED floor refuses the screening entirely with
        ERR_STORE_FLOOR_SUSPENDED."
        "Either way screened_at is stamped from the logical clock and the request's version
        is incremented."

        Design: Corner/state_machines/issuance_screen_activates_the_card_and_appends_the_activation_load
        """
        world = self._submitted_request(client)
        assert world["store"]["floor_posture"] == "OPEN"

        response = client.screen_issuance_request(
            world["request"]["id"], make_pos_associate_headers()
        )

        screened = validate_success(response, 200)
        assert screened["state"] == "APPROVED"
        assert parse_instant(screened["screened_at"]) == parse_instant(CLOCK_ORIGIN)

    def test_approval_activates_the_card_and_funds_every_balance_figure(self, client):
        """"Then, on either channel, the referenced card moves from INACTIVE to ACTIVE: its
        face_value_cents is copied from the request, a credit event of kind ACTIVATION_LOAD
        for that amount is appended to the card's ledger, all of its balance figures are
        re-derived, activated_at is stamped from the logical clock, and its rack_id is
        cleared to nothing because the card has left the fixture."

        Design: Corner/state_machines/issuance_screen_activates_the_card_and_appends_the_activation_load
        """
        world = self._submitted_request(client)

        validate_success(
            client.screen_issuance_request(world["request"]["id"], make_pos_associate_headers())
        )

        card = read_card(client, world["card"]["id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["channel"] == "PHYSICAL"
        assert card["face_value_cents"] == 7500
        assert_card_projection(
            card,
            current_balance_cents=7500,
            total_loaded_cents=7500,
            total_redeemed_cents=0,
            held_amount_cents=0,
            available_balance_cents=7500,
        )
        assert parse_instant(card["activated_at"]) == parse_instant(CLOCK_ORIGIN)
        assert card["risk_posture"] == "CLEAR"

    def test_exactly_one_activation_load_is_appended_as_a_positive_movement(self, client):
        """"The credit kinds, whose signed_amount_cents is the positive amount, are
        ACTIVATION_LOAD, REDEMPTION_REVERSAL, REISSUE_CREDIT and REISSUE_DEBIT_REVERSAL."
        "a credit event of kind ACTIVATION_LOAD for that amount is appended to the card's
        ledger"

        Design: Corner/state_machines/issuance_screen_activates_the_card_and_appends_the_activation_load
        """
        world = self._submitted_request(client)

        validate_success(
            client.screen_issuance_request(world["request"]["id"], make_pos_associate_headers())
        )

        response = client.list_ledger_events(
            make_liability_accountant_headers("acct-41"),
            {"card_id": world["card"]["id"], "type": "ACTIVATION_LOAD"},
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["amount_cents"] == 7500
        assert rows[0]["signed_amount_cents"] == 7500


class TestRedemptionNeedsAnActiveCard:
    """A never-screened card holds nothing, so it cannot be drawn down."""

    def _never_screened_card(self, client):
        """A store, an INTACT rack and a card stocked but never carried through an
        issuance screening, so it is still INACTIVE with a zero balance."""
        store = create_store(
            client, name="Never Screened Store", region_code="SE", address_line="3 Idle Rd"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-N1", expected_card_count=6)
        card = stock_card(
            client, store["id"], rack["id"], card_number_masked="****-****-****-4201"
        )
        return {"store": store, "rack": rack, "card": card}

    def test_redeeming_an_inactive_card_is_refused_with_the_funding_state_error(self, client):
        """"A redemption is refused when the card is not ACTIVE (ERR_CARD_NOT_ACTIVE), when
        its posture is FROZEN (ERR_CARD_FROZEN), when the merchant store's floor is
        SUSPENDED (ERR_STORE_FLOOR_SUSPENDED), and when amount_cents exceeds the card's
        available_balance_cents (ERR_INSUFFICIENT_BALANCE) — in exactly that order of
        precedence."

        Design: Corner/state_machines/redemption_on_inactive_card_is_rejected
        """
        world = self._never_screened_card(client)

        response = client.create_redemption(
            world["card"]["id"],
            redemption_payload(100, world["store"]["id"], pos_terminal_id="T-42"),
            make_pos_associate_headers(),
        )

        validate_error(response, ERR_CARD_NOT_ACTIVE, 409)
        card = read_card(client, world["card"]["id"])
        assert card["activation_state"] == "INACTIVE"

    def test_the_refused_redemption_writes_neither_ledger_nor_version(self, client):
        """"version, an integer that starts at 1 on creation and increases by exactly 1 on
        every mutation — including mutations that arrive as a cascaded side effect of an
        operation on a different resource."
        "A REDEMPTION event is appended with occurred_at at the logical now, every balance
        and pattern figure is re-derived, and the card's version increments."

        Design: Corner/state_machines/redemption_on_inactive_card_is_rejected
        """
        world = self._never_screened_card(client)
        before = read_card(client, world["card"]["id"])

        response = client.create_redemption(
            world["card"]["id"],
            redemption_payload(100, world["store"]["id"], pos_terminal_id="T-42"),
            make_pos_associate_headers(),
        )
        validate_error(response, ERR_CARD_NOT_ACTIVE, 409)

        after = read_card(client, world["card"]["id"])
        assert after["version"] == before["version"]
        assert after["current_balance_cents"] == 0
        assert after["total_redeemed_cents"] == 0
        events = client.list_ledger_events(
            make_platform_admin_headers(), {"card_id": world["card"]["id"]}
        )
        assert total_count(events) == 0


class TestApprovedIssuanceCannotBeScreenedTwice:
    """A replayed screening must not double-fund a card."""

    def _approved_request(self, client):
        """A store, an INTACT rack, a card and a PHYSICAL request for 7500 cents already
        screened through to APPROVED against an OPEN floor."""
        store = create_store(
            client, name="Replay Screen Store", region_code="NW", address_line="4 Replay Ln"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-R1", expected_card_count=6)
        built = funded_physical_card(client, 7500, store=store, rack=rack)
        return built

    def test_screening_an_approved_request_again_is_refused(self, client):
        """"an issuance request must be SUBMITTED to be screened and SUBMITTED or
        HELD_FOR_REVIEW to be decided, otherwise ERR_INVALID_ISSUANCE_STATE"
        "APPROVED and DECLINED are both terminal — no further transition leaves either."

        Design: Corner/state_machines/second_screen_on_approved_issuance_request_is_rejected
        """
        world = self._approved_request(client)
        assert world["request"]["state"] == "APPROVED"

        response = client.screen_issuance_request(
            world["request"]["id"], make_pos_associate_headers()
        )

        validate_error(response, ERR_INVALID_ISSUANCE_STATE, 409)
        again = validate_success(
            client.get_issuance_request(world["request"]["id"], make_platform_admin_headers())
        )
        assert again["state"] == "APPROVED"

    def test_the_replayed_screen_does_not_load_the_card_a_second_time(self, client):
        """"total_loaded_cents is the sum of the raw amounts over the credit kinds only."
        "Every request is validated as an ordered ladder, and the first violation
        encountered wins: the request is rejected with that rule's error and no later rule
        is evaluated."

        Design: Corner/state_machines/second_screen_on_approved_issuance_request_is_rejected
        """
        world = self._approved_request(client)
        before = read_card(client, world["card"]["id"])

        response = client.screen_issuance_request(
            world["request"]["id"], make_pos_associate_headers()
        )
        validate_error(response, ERR_INVALID_ISSUANCE_STATE, 409)

        after = read_card(client, world["card"]["id"])
        assert after["current_balance_cents"] == 7500
        assert after["total_loaded_cents"] == 7500
        assert after["version"] == before["version"]
        loads = client.list_ledger_events(
            make_liability_accountant_headers("acct-43"),
            {"card_id": world["card"]["id"], "type": "ACTIVATION_LOAD"},
        )
        assert total_count(loads) == 1


class TestAlertResolutionRequiresTriageFirst:
    """The alert machine has no edge from OPEN straight to a resolution."""

    def _open_alert(self, client):
        """A 9000-cent ACTIVE card carrying one manually raised MANUAL_REVIEW alert, still
        OPEN because nobody has triaged it."""
        store = create_store(
            client, name="Skip Triage Store", region_code="MW", address_line="5 Skip St"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-S1", expected_card_count=6)
        built = funded_physical_card(client, 9000, store=store, rack=rack)
        alert = open_alert(
            client,
            built["card"]["id"],
            "MANUAL_REVIEW",
            headers=make_fraud_analyst_headers("analyst-44"),
            note="clerk flagged an unusual purchase",
        )
        return {"store": store, "card_id": built["card"]["id"], "alert": alert}

    def test_the_open_alert_snapshots_the_whole_exposure_of_the_card(self, client):
        """"A manually raised alert starts in OPEN with basis_velocity_count and
        basis_drain_score both at 0."
        "It is the card's current_balance_cents plus its total_redeemed_cents — that is,
        the total funds the alert puts at risk: what is still redeemable plus what has
        already been drained away."

        Design: Corner/state_machines/alert_resolve_before_triage_is_rejected
        """
        world = self._open_alert(client)

        assert world["alert"]["state"] == "OPEN"
        assert world["alert"]["exposure_cents"] == 9000
        assert world["alert"]["basis_velocity_count"] == 0
        assert world["alert"]["basis_drain_score"] == 0

    def test_resolving_an_untriaged_alert_is_refused_and_records_nothing(self, client):
        """"a draining alert must be OPEN to be triaged, TRIAGED to be resolved and
        DISMISSED to be reopened, otherwise ERR_INVALID_ALERT_STATE"
        "Either resolution records resolved_by_user_id from the caller and the supplied
        note, recomputes the store's open_alert_count and floor_posture, and increments the
        alert's, the card's and the store's version."

        Design: Corner/state_machines/alert_resolve_before_triage_is_rejected
        """
        world = self._open_alert(client)

        response = client.resolve_draining_alert(
            world["alert"]["id"],
            resolution_payload("CONFIRM", resolution_note="trying to confirm without triage"),
            make_risk_manager_headers("risk-44"),
        )

        validate_error(response, ERR_INVALID_ALERT_STATE, 409)
        alert = read_alert(client, world["alert"]["id"])
        assert alert["state"] == "OPEN"
        assert_empty(alert["triaged_by_user_id"], "triaged_by_user_id")
        assert_empty(alert["resolution"], "resolution")
        assert_empty(alert["resolved_by_user_id"], "resolved_by_user_id")

    def test_no_freeze_leaks_out_of_the_rejected_resolution(self, client):
        """"Hop two follows from the alert being confirmed: the card's risk_posture is
        forced to FROZEN, from whatever rung it was on — CLEAR → FROZEN, WATCH → FROZEN or
        RESTRICTED → FROZEN."
        "The card is created with channel PHYSICAL, a funding state of INACTIVE, a fraud
        posture of CLEAR, face_value_cents of 0 and every balance figure at 0."

        Design: Corner/state_machines/alert_resolve_before_triage_is_rejected
        """
        world = self._open_alert(client)

        response = client.resolve_draining_alert(
            world["alert"]["id"],
            resolution_payload("CONFIRM", resolution_note="trying to confirm without triage"),
            make_risk_manager_headers("risk-44"),
        )
        validate_error(response, ERR_INVALID_ALERT_STATE, 409)

        card = read_card(client, world["card_id"])
        assert card["risk_posture"] == "CLEAR"
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 9000


class TestEvidenceResubmissionNeedsARequestFirst:
    """A claim only opens its evidence door after an analyst asks for something."""

    def _submitted_claim(self, client):
        """A 9000-cent ACTIVE card with one freshly intaken claim, still SUBMITTED because
        no analyst has requested anything yet."""
        store = create_store(
            client, name="Claim State Store", region_code="NE", address_line="6 Claim Ct"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-CS", expected_card_count=6)
        built = funded_physical_card(client, 9000, store=store, rack=rack)
        claim = file_claim(
            client,
            built["card"]["id"],
            disputed_amount_cents=4000,
            purchased_at=CLOCK_ORIGIN,
            claimant_name="Dana Whitfield",
            claimant_contact="dana@example.test",
            purchase_receipt_ref="RCPT-4501",
        )
        return {"card_id": built["card"]["id"], "claim": claim}

    def test_a_new_claim_sits_at_evidence_round_zero(self, client):
        """"The claim is created in state SUBMITTED with evidence_round at 0 and
        missing_evidence_kinds, decision_note, rescind_reason and every money field empty."

        Design: Corner/state_machines/resubmit_evidence_on_submitted_claim_is_rejected
        """
        world = self._submitted_claim(client)

        assert world["claim"]["state"] == "SUBMITTED"
        assert world["claim"]["evidence_round"] == 0
        assert_empty(world["claim"]["missing_evidence_kinds"], "missing_evidence_kinds")
        assert_empty(world["claim"]["decision_note"], "decision_note")
        assert_empty(world["claim"]["rescind_reason"], "rescind_reason")

    def test_resubmitting_evidence_on_a_submitted_claim_is_refused(self, client):
        """"a victim claim must be SUBMITTED for an evidence request or a decision,
        EVIDENCE_REQUESTED for an evidence resubmission and APPROVED for a rescission,
        otherwise ERR_INVALID_CLAIM_STATE"

        Design: Corner/state_machines/resubmit_evidence_on_submitted_claim_is_rejected
        """
        world = self._submitted_claim(client)

        response = client.resubmit_claim_evidence(
            world["claim"]["id"],
            evidence_resubmit_payload(packaging_photo_ref="PHOTO-4501"),
            make_fraud_analyst_headers("analyst-45"),
        )

        validate_error(response, ERR_INVALID_CLAIM_STATE, 409)

    def test_the_refused_resubmission_neither_counts_a_round_nor_stores_the_reference(
        self, client
    ):
        """"Each resubmission increments evidence_round by 1 and returns the claim to
        SUBMITTED"; a rejected call must leave the counter and the stored references
        exactly where they were.

        Design: Corner/state_machines/resubmit_evidence_on_submitted_claim_is_rejected
        """
        world = self._submitted_claim(client)

        response = client.resubmit_claim_evidence(
            world["claim"]["id"],
            evidence_resubmit_payload(packaging_photo_ref="PHOTO-4501"),
            make_fraud_analyst_headers("analyst-45"),
        )
        validate_error(response, ERR_INVALID_CLAIM_STATE, 409)

        claim = read_claim(client, world["claim"]["id"])
        assert claim["state"] == "SUBMITTED"
        assert claim["evidence_round"] == 0
        assert_empty(claim["packaging_photo_ref"], "packaging_photo_ref")
        assert_empty(claim["missing_evidence_kinds"], "missing_evidence_kinds")
        assert claim["purchase_receipt_ref"] == "RCPT-4501"


class TestPeriodCloseHappensExactlyOnce:
    """Closing is admitted from OPEN only, so a replayed close changes nothing."""

    def _closed_period(self, client):
        """An August period with no alerts inside it, closed once by acct-46."""
        period = open_period(
            client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", label="2026-08 idempotency"
        )
        closed = close_period(
            client,
            period["id"],
            headers=make_liability_accountant_headers("acct-46"),
            close_note="first and only close",
        )
        return {"period": period, "closed": closed}

    def test_an_alert_free_period_closes_with_zeros_rather_than_blanks(self, client):
        """"A period with no in-period alerts closes with a gross exposure of 0, a basis
        count of 0 and a reserve of 0 — zero, not empty, and certainly not an error."
        "It stamps closed_at from the logical clock and books the provisional reserve on a
        prudent basis."

        Design: Corner/state_machines/second_close_on_closed_period_is_rejected
        """
        world = self._closed_period(client)
        closed = world["closed"]

        assert closed["state"] == "CLOSED"
        assert closed["gross_exposure_cents"] == 0
        assert closed["reserve_basis_alert_count"] == 0
        assert closed["provisional_reserve_cents"] == 0
        assert parse_instant(closed["closed_at"]) == parse_instant(CLOCK_ORIGIN)
        assert closed["close_note"] == "first and only close"
        assert closed["restatement_count"] == 0
        assert_empty(closed["restated_at"], "restated_at")

    def test_closing_a_closed_period_a_second_time_is_refused(self, client):
        """"an accounting period must be OPEN to be closed and CLOSED or RESTATED to be
        restated, otherwise ERR_INVALID_PERIOD_STATE"

        Design: Corner/state_machines/second_close_on_closed_period_is_rejected
        """
        world = self._closed_period(client)

        response = client.close_liability_period(
            world["period"]["id"],
            period_close_payload(close_note="accidental replay"),
            make_liability_accountant_headers("acct-46"),
        )

        validate_error(response, ERR_INVALID_PERIOD_STATE, 409)

    def test_the_replayed_close_moves_neither_the_stamp_nor_the_version(self, client):
        """"Closing is a LiabilityAccountant operation admitted only from OPEN"; a refused
        close must leave the booked reserve, the stored note and the version untouched.

        Design: Corner/state_machines/second_close_on_closed_period_is_rejected
        """
        world = self._closed_period(client)
        before = world["closed"]

        response = client.close_liability_period(
            world["period"]["id"],
            period_close_payload(close_note="accidental replay"),
            make_liability_accountant_headers("acct-46"),
        )
        validate_error(response, ERR_INVALID_PERIOD_STATE, 409)

        after = read_period(client, world["period"]["id"])
        assert after["state"] == "CLOSED"
        assert after["version"] == before["version"]
        assert parse_instant(after["closed_at"]) == parse_instant(before["closed_at"])
        assert after["provisional_reserve_cents"] == 0
        assert after["close_note"] == "first and only close"


class TestReleasedHoldRefusesASecondSettlement:
    """Settlement is a one-way door out of ACTIVE, in either direction."""

    def _released_hold(self, client):
        """A 10000-cent card carrying a 4000-cent hold over the first six hours, already
        settled with RELEASE."""
        store = create_store(
            client, name="Hold Lockdown Store", region_code="SW", address_line="7 Hold Hwy"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-HL", expected_card_count=6)
        built = funded_physical_card(client, 10000, store=store, rack=rack)
        hold = hold_on_card(client, built["card"]["id"], 4000, minutes=360)
        released = settle_hold(
            client,
            hold["id"],
            "RELEASE",
            settle_note="customer abandoned the basket",
        )
        return {"card_id": built["card"]["id"], "hold": hold, "released": released}

    def test_a_release_returns_the_capacity_and_captures_nothing(self, client):
        """"A release moves the hold to RELEASED, records the disposition and note, leaves
        captured_amount_cents at 0, appends no ledger event, and leaves
        current_balance_cents entirely unchanged while recomputing held_amount_cents and
        available_balance_cents."

        Design: Corner/state_machines/settle_on_released_hold_is_rejected
        """
        world = self._released_hold(client)
        released = world["released"]

        assert released["state"] == "RELEASED"
        assert released["disposition"] == "RELEASE"
        assert released["captured_amount_cents"] == 0
        assert released["settle_note"] == "customer abandoned the basket"

    def test_capturing_an_already_released_hold_is_refused(self, client):
        """"a redemption hold must be ACTIVE to be settled, otherwise
        ERR_INVALID_HOLD_STATE"

        Design: Corner/state_machines/settle_on_released_hold_is_rejected
        """
        world = self._released_hold(client)

        response = client.settle_redemption_hold(
            world["hold"]["id"],
            hold_settlement_payload("CAPTURE", settle_note="late capture attempt"),
            make_pos_associate_headers(),
        )

        validate_error(response, ERR_INVALID_HOLD_STATE, 409)
        hold = validate_success(
            client.get_redemption_hold(world["hold"]["id"], make_platform_admin_headers())
        )
        assert hold["state"] == "RELEASED"
        assert hold["disposition"] == "RELEASE"
        assert hold["captured_amount_cents"] == 0

    def test_the_refused_capture_debits_nothing_from_the_card(self, client):
        """"A capture moves the hold to CAPTURED, sets captured_amount_cents to the hold's
        own amount, and appends a REDEMPTION event for that amount at the supplied merchant
        store."
        "released, captured and expired holds free their capacity immediately."

        Design: Corner/state_machines/settle_on_released_hold_is_rejected
        """
        world = self._released_hold(client)

        response = client.settle_redemption_hold(
            world["hold"]["id"],
            hold_settlement_payload("CAPTURE", settle_note="late capture attempt"),
            make_pos_associate_headers(),
        )
        validate_error(response, ERR_INVALID_HOLD_STATE, 409)

        card = read_card(client, world["card_id"])
        assert_card_projection(
            card,
            current_balance_cents=10000,
            total_redeemed_cents=0,
            held_amount_cents=0,
            available_balance_cents=10000,
        )
        redemptions = client.list_ledger_events(
            make_liability_accountant_headers("acct-46"),
            {"card_id": world["card_id"], "type": "REDEMPTION"},
        )
        assert total_count(redemptions) == 0


class TestHoldExpiryIsDrivenByTheClock:
    """The fourth hold state has no endpoint — only the clock reaches it."""

    def _held_card(self, client):
        """A 10000-cent card with a 4000-cent hold covering midnight to six in the
        morning."""
        store = create_store(
            client, name="Expiry Store", region_code="NW", address_line="8 Expiry Esp"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-EX", expected_card_count=6)
        built = funded_physical_card(client, 10000, store=store, rack=rack)
        hold = hold_on_card(client, built["card"]["id"], 4000, minutes=360)
        return {"card_id": built["card"]["id"], "hold": hold}

    def test_moving_the_clock_past_the_window_sweeps_the_hold_and_counts_it(self, client):
        """"When a PlatformAdmin advances the logical clock, every ACTIVE hold whose
        hold_expires_at falls strictly before the new clock reading is swept to EXPIRED."
        "the count of holds swept is reported back as expired_hold_count."

        Design: Corner/state_machines/hold_expires_when_the_clock_passes_its_window_and_frees_capacity
        """
        world = self._held_card(client)
        assert world["hold"]["state"] == "ACTIVE"
        seven = shift(CLOCK_ORIGIN, hours=7)

        moved = validate_success(
            client.set_clock({"to_iso8601": seven}, make_platform_admin_headers())
        )

        assert parse_instant(moved["current_utc"]) == parse_instant(seven)
        assert moved["expired_hold_count"] == 1
        hold = validate_success(
            client.get_redemption_hold(world["hold"]["id"], make_platform_admin_headers())
        )
        assert hold["state"] == "EXPIRED"
        assert_empty(hold["disposition"], "disposition")
        assert hold["captured_amount_cents"] == 0

    def test_the_expired_hold_gives_the_reservation_back_to_the_card(self, client):
        """"Each swept hold has its version incremented, each affected card has
        held_amount_cents and available_balance_cents recomputed and its version
        incremented."
        "a hold reserves value, it does not spend it."

        Design: Corner/state_machines/hold_expires_when_the_clock_passes_its_window_and_frees_capacity
        """
        world = self._held_card(client)
        held = read_card(client, world["card_id"])
        assert held["held_amount_cents"] == 4000
        assert held["available_balance_cents"] == 6000

        validate_success(
            client.set_clock(
                {"to_iso8601": shift(CLOCK_ORIGIN, hours=7)}, make_platform_admin_headers()
            )
        )

        freed = read_card(client, world["card_id"])
        assert_card_projection(
            freed,
            current_balance_cents=10000,
            total_redeemed_cents=0,
            held_amount_cents=0,
            available_balance_cents=10000,
        )

    def test_the_freed_capacity_lets_a_full_balance_hold_through(self, client):
        """"Only ACTIVE holds bear capacity: released, captured and expired holds free
        their capacity immediately, which is why advancing the logical clock past a hold's
        expiry can turn a refused candidate into an accepted one with nothing else having
        changed."
        "a candidate that exactly exhausts the balance is accepted and drives
        available_balance_cents to exactly 0"

        Design: Corner/state_machines/hold_expires_when_the_clock_passes_its_window_and_frees_capacity
        """
        world = self._held_card(client)
        validate_success(
            client.set_clock(
                {"to_iso8601": shift(CLOCK_ORIGIN, hours=7)}, make_platform_admin_headers()
            )
        )
        card = read_card(client, world["card_id"])

        response = client.create_redemption_hold(
            world["card_id"],
            redemption_hold_payload(
                10000,
                shift(CLOCK_ORIGIN, hours=8),
                shift(CLOCK_ORIGIN, hours=12),
                card["version"],
            ),
            make_pos_associate_headers(),
        )

        second = validate_success(response, 201)
        assert second["state"] == "ACTIVE"
        assert second["amount_cents"] == 10000
        after = read_card(client, world["card_id"])
        assert after["held_amount_cents"] == 10000
        assert after["available_balance_cents"] == 0
        assert after["current_balance_cents"] == 10000


class TestSuspectRackWalksBackToIntact:
    """SUSPECT is the one classification a clean audit can undo without remediation."""

    def _suspect_rack(self, client):
        """A rack expecting ten cards audited once at nine, which lands it on SUSPECT and
        heightens its store's floor."""
        store = create_store(
            client, name="Shrink Watch Store", region_code="MW", address_line="9 Shrink Sq"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-SW", expected_card_count=10)
        audited = audit_rack(client, rack["id"], observed_card_count=9, seal_breaks_observed=0)
        return {"store": store, "rack": rack, "audited": audited}

    def test_one_missing_card_is_enough_for_suspect(self, client):
        """"Otherwise, if missing_card_count is at least 1 or seal_breaks_observed is at
        least 1, the rack is SUSPECT."
        "otherwise, if suspect_rack_count is at least 1 or open_alert_count is at least
        floor_heightened_alert_threshold, the floor is HEIGHTENED"

        Design: Corner/state_machines/rack_returns_from_suspect_to_intact_on_a_clean_audit
        """
        world = self._suspect_rack(client)

        assert world["audited"]["tamper_state"] == "SUSPECT"
        assert world["audited"]["missing_card_count"] == 1
        store = read_store(client, world["store"]["id"], headers=make_risk_manager_headers("risk-48"))
        assert_store_counters(
            store, floor_posture="HEIGHTENED", suspect_rack_count=1, tampered_rack_count=0
        )

    def test_a_clean_re_audit_returns_the_rack_to_intact(self, client):
        """"A SUSPECT rack audited again with clean numbers returns to INTACT, and a
        SUSPECT rack audited again with dirty-but-sub-threshold numbers stays SUSPECT while
        refreshing its observation fields."
        "Classification is fully re-derived on every audit and is deliberately not sticky."

        Design: Corner/state_machines/rack_returns_from_suspect_to_intact_on_a_clean_audit
        """
        world = self._suspect_rack(client)

        cleaned = audit_rack(client, world["rack"]["id"], observed_card_count=10, seal_breaks_observed=0)

        assert cleaned["tamper_state"] == "INTACT"
        assert cleaned["missing_card_count"] == 0
        assert cleaned["observed_card_count"] == 10
        assert cleaned["seal_breaks_observed"] == 0
        assert_empty(cleaned["remediation_note"], "remediation_note")
        assert read_rack(client, world["rack"]["id"])["tamper_state"] == "INTACT"

    def test_the_floor_relaxes_back_to_open_behind_the_clean_rack(self, client):
        """"The derivation reads only rack and alert state and never its own previous
        value, so it terminates in a single pass with no oscillation, and it is
        bidirectional over time."
        "otherwise it is OPEN."

        Design: Corner/state_machines/rack_returns_from_suspect_to_intact_on_a_clean_audit
        """
        world = self._suspect_rack(client)

        audit_rack(client, world["rack"]["id"], observed_card_count=10, seal_breaks_observed=0)

        store = read_store(client, world["store"]["id"], headers=make_risk_manager_headers("risk-48"))
        assert_store_counters(
            store, floor_posture="OPEN", suspect_rack_count=0, tampered_rack_count=0
        )


class TestDismissedAlertCanComeBack:
    """The alert lifecycle is the one cycle in this service."""

    def _dismissed_alert(self, client):
        """A 9000-cent card whose manually raised alert was triaged by analyst-49 and then
        dismissed by risk-49."""
        store = create_store(
            client, name="Reopen Store", region_code="SE", address_line="10 Reopen Row"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-RO", expected_card_count=6)
        built = funded_physical_card(client, 9000, store=store, rack=rack)
        alert = open_alert(
            client,
            built["card"]["id"],
            "MANUAL_REVIEW",
            headers=make_fraud_analyst_headers("analyst-49"),
            note="shopper reported a suspicious rack",
        )
        triage_alert(
            client,
            alert["id"],
            headers=make_fraud_analyst_headers("analyst-49"),
            triage_note="no draining pattern found",
        )
        dismissed = resolve_alert(
            client,
            alert["id"],
            "DISMISS",
            headers=make_risk_manager_headers("risk-49"),
            resolution_note="single legitimate purchase",
        )
        return {"card_id": built["card"]["id"], "alert": alert, "dismissed": dismissed}

    def test_a_dismissal_leaves_the_card_exactly_where_it_was(self, client):
        """"Dismissing touches no listing whatsoever. It moves the alert TRIAGED →
        DISMISSED, and it lowers the card's risk_posture to CLEAR — from WATCH, RESTRICTED
        or FROZEN alike — but only when no other alert on that same card remains in state
        OPEN or TRIAGED."

        Design: Corner/state_machines/alert_reopen_returns_a_dismissed_alert_to_open
        """
        world = self._dismissed_alert(client)

        assert world["dismissed"]["state"] == "DISMISSED"
        assert world["dismissed"]["resolution"] == "DISMISS"
        card = read_card(client, world["card_id"])
        assert card["risk_posture"] == "CLEAR"
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 9000

    def test_reopening_clears_the_resolution_and_counts_the_cycle(self, client):
        """"The alert returns DISMISSED → OPEN, its resolution, resolved_by_user_id and
        resolution_note are all cleared back to empty, and reopen_count increments by 1."

        Design: Corner/state_machines/alert_reopen_returns_a_dismissed_alert_to_open
        """
        world = self._dismissed_alert(client)

        reopened = reopen_alert(
            client,
            world["alert"]["id"],
            headers=make_risk_manager_headers("risk-49"),
            reopen_reason="second victim report names the same card",
        )

        assert reopened["state"] == "OPEN"
        assert reopened["reopen_count"] == 1
        assert_empty(reopened["resolution"], "resolution")
        assert_empty(reopened["resolved_by_user_id"], "resolved_by_user_id")
        assert_empty(reopened["resolution_note"], "resolution_note")

    def test_the_original_triager_survives_the_reopen(self, client):
        """"Crucially, triaged_by_user_id is preserved across the reopen, so segregation of
        duties still binds the same original triager on the next resolution attempt."

        Design: Corner/state_machines/alert_reopen_returns_a_dismissed_alert_to_open
        """
        world = self._dismissed_alert(client)

        reopen_alert(
            client,
            world["alert"]["id"],
            headers=make_risk_manager_headers("risk-49"),
            reopen_reason="second victim report names the same card",
        )

        alert = read_alert(client, world["alert"]["id"])
        assert alert["state"] == "OPEN"
        assert alert["triaged_by_user_id"] == "analyst-49"
        assert alert["reopen_count"] == 1


class TestDeniedClaimIsATerminalDeadEnd:
    """A denial closes the file: no second decision, no rescission."""

    def _denied_claim(self, client):
        """A 9000-cent card drained by one 3000-cent redemption, with a fully evidenced
        claim that risk-50 denied."""
        store = create_store(
            client, name="Denied Claim Store", region_code="NE", address_line="11 Denied Dr"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-DC", expected_card_count=6)
        built = funded_physical_card(client, 9000, store=store, rack=rack)
        card_id = built["card"]["id"]
        redeem(client, card_id, 3000, store["id"], memo="disputed line")
        claim = file_claim(
            client,
            card_id,
            disputed_amount_cents=3000,
            purchased_at=CLOCK_ORIGIN,
            headers=make_fraud_analyst_headers("analyst-50"),
            claimant_name="Ravi Anand",
            claimant_contact="ravi@example.test",
            purchase_receipt_ref="RCPT-5001",
            packaging_photo_ref="PHOTO-5001",
        )
        denied = decide_claim(
            client,
            claim["id"],
            "DENY",
            headers=make_risk_manager_headers("risk-50"),
            decision_note="the redemption was made on the claimant's own device",
        )
        return {"store": store, "card_id": card_id, "claim": claim, "denied": denied}

    def test_a_denial_records_the_decision_and_no_money_at_all(self, client):
        """"The claim moves SUBMITTED → DENIED, decided_by_user_id and decision_note are
        recorded, every money field stays empty, no replacement card is minted, no ledger
        event is appended, and no liability period is touched."

        Design: Corner/state_machines/denied_claim_is_terminal_and_rejects_further_decisions
        """
        world = self._denied_claim(client)
        denied = world["denied"]

        assert denied["state"] == "DENIED"
        assert denied["decided_by_user_id"] == "risk-50"
        assert denied["decision_note"] == "the redemption was made on the claimant's own device"
        assert_empty(denied["reissue_amount_cents"], "reissue_amount_cents")
        assert_empty(denied["gross_reissue_cents"], "gross_reissue_cents")
        assert_empty(denied["residual_transfer_cents"], "residual_transfer_cents")
        assert_empty(denied["reissued_card_id"], "reissued_card_id")

    def test_a_denied_claim_refuses_a_second_decision(self, client):
        """"DENIED is terminal."
        "a victim claim must be SUBMITTED for an evidence request or a decision,
        EVIDENCE_REQUESTED for an evidence resubmission and APPROVED for a rescission,
        otherwise ERR_INVALID_CLAIM_STATE"

        Design: Corner/state_machines/denied_claim_is_terminal_and_rejects_further_decisions
        """
        world = self._denied_claim(client)

        response = client.decide_victim_claim(
            world["claim"]["id"],
            claim_decision_payload("APPROVE", decision_note="second bite at the apple"),
            make_risk_manager_headers("risk-50"),
        )

        validate_error(response, ERR_INVALID_CLAIM_STATE, 409)
        claim = read_claim(client, world["claim"]["id"])
        assert claim["state"] == "DENIED"
        assert claim["decided_by_user_id"] == "risk-50"

    def test_a_denial_cannot_be_rescinded_because_only_approvals_can(self, client):
        """"A RiskManager or a LiabilityAccountant may rescind an APPROVED claim with a
        mandatory rescind_reason."
        "a victim claim must be SUBMITTED for an evidence request or a decision,
        EVIDENCE_REQUESTED for an evidence resubmission and APPROVED for a rescission,
        otherwise ERR_INVALID_CLAIM_STATE"

        Design: Corner/state_machines/denied_claim_is_terminal_and_rejects_further_decisions
        """
        world = self._denied_claim(client)

        response = client.rescind_victim_claim(
            world["claim"]["id"],
            rescind_payload(rescind_reason="trying to rescind a denial"),
            make_risk_manager_headers("risk-50"),
        )

        validate_error(response, ERR_INVALID_CLAIM_STATE, 409)
        claim = read_claim(client, world["claim"]["id"])
        assert claim["state"] == "DENIED"
        assert_empty(claim["rescind_reason"], "rescind_reason")

    def test_no_replacement_card_exists_anywhere_behind_a_denial(self, client):
        """"no replacement card is minted"; the original card is left funded and redeemable,
        and cards remain "filterable by store, rack, funding state, risk posture, channel or
        reissue origin".

        Design: Corner/state_machines/denied_claim_is_terminal_and_rejects_further_decisions
        """
        world = self._denied_claim(client)

        card = read_card(client, world["card_id"])

        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 6000
        assert card["total_redeemed_cents"] == 3000
        replacements = client.list_gift_cards(
            make_platform_admin_headers(), {"reissued_from_card_id": world["card_id"]}
        )
        assert total_count(replacements) == 0


class TestBulkOrderBelowTheIdentityThreshold:
    """An order that needs no identity is born one state further along."""

    def _below_threshold_order(self, client):
        """Twenty-five cards at 1000 cents each on a fresh store — a 25000-cent subtotal,
        which is exactly the first fee band and still under the identity threshold."""
        store = create_store(
            client,
            name="Bulk Below Threshold Store",
            region_code="SW",
            address_line="12 Bulk Blvd",
        )
        order = open_bulk_order(
            client,
            store["id"],
            card_quantity=25,
            face_value_cents_each=1000,
            purchaser_name="Northline Staffing LLC",
            payment_method="CORPORATE_ACH",
        )
        return {"store": store, "order": order}

    def test_the_order_is_created_already_identity_verified_with_no_documents(self, client):
        """"When the total is strictly below the threshold the order is already
        IDENTITY_VERIFIED in the creation response, with all three identity fields left
        empty because none is required."
        "A quantity exactly equal to the limit is accepted; one more than the limit is not."

        Design: Corner/state_machines/bulk_order_below_the_identity_threshold_starts_identity_verified
        """
        world = self._below_threshold_order(client)
        order = world["order"]

        assert order["state"] == "IDENTITY_VERIFIED"
        assert order["card_quantity"] == 25
        assert_empty(order["identity_id_type"], "identity_id_type")
        assert_empty(order["identity_id_number_hash"], "identity_id_number_hash")
        assert_empty(order["identity_id_expiry_date"], "identity_id_expiry_date")

    def test_the_frozen_pricing_puts_the_subtotal_on_the_first_fee_band(self, client):
        """"A subtotal of exactly 25000 cents sits in the 150-basis-point band, since the
        lower edge of each band is inclusive."
        "activation_fee_cents is the subtotal multiplied by that basis-point figure and
        divided by 10000, rounded half up exactly once over the whole order. Fourth,
        total_cents is the subtotal plus the activation fee."

        Design: Corner/state_machines/bulk_order_below_the_identity_threshold_starts_identity_verified
        """
        world = self._below_threshold_order(client)
        order = world["order"]

        assert order["face_value_subtotal_cents"] == 25000
        assert order["fee_rate_bps"] == 150
        assert order["activation_fee_cents"] == 375
        assert order["total_cents"] == 25375

    def test_approval_is_reachable_straight_from_identity_verified(self, client):
        """"Approval from PENDING_IDENTITY is therefore only ever reachable on an order
        below the identity threshold, where no identity was required in the first place."
        "Either terminal decision records decided_by_user_id from the caller's X-User-ID
        along with the decision_note, and increments the order's version."

        Design: Corner/state_machines/bulk_order_below_the_identity_threshold_starts_identity_verified
        """
        world = self._below_threshold_order(client)

        approved = decide_bulk_order(
            client,
            world["order"]["id"],
            "APPROVE",
            headers=make_risk_manager_headers("risk-51"),
            decision_note="under the identity threshold",
        )

        assert approved["state"] == "APPROVED"
        assert approved["decided_by_user_id"] == "risk-51"
        assert approved["decision_note"] == "under the identity threshold"
        assert approved["total_cents"] == 25375
        assert approved["version"] == world["order"]["version"] + 1
