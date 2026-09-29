"""Endpoint-level behaviour across the declared surface.

The partial write on the policy singleton, the four things one triage call does, the
state gate on filing a law-enforcement packet, the reversal edge of the bulk-order
lifecycle, a computed read that persists nothing, a sub-collection keyed on its parent
alert, and list filters composing with the pagination window.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assert_bulk_pricing, expected_bulk_pricing, expected_redemption_drain_score
from test_helpers.api_errors import (
    ERR_ALERT_NOT_CONFIRMED,
    ERR_IDENTITY_VERIFICATION_REQUIRED,
)
from test_helpers.constants import CLOCK_ORIGIN
from test_helpers.factories import bulk_decision_payload, referral_payload
from test_helpers.fixtures import (
    audit_rack,
    capture_identity,
    close_period,
    create_rack,
    create_store,
    decide_bulk_order,
    funded_physical_card,
    open_alert,
    open_bulk_order,
    open_period,
    parse_instant,
    read_alert,
    read_card,
    read_exposure_summary,
    read_period,
    read_store,
    redeem,
    resolve_alert,
    triage_alert,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_liability_accountant_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_risk_manager_headers,
)


class TestRiskPolicyPartialWrite:
    """The singleton register "is updated by partial write"."""

    def test_the_seeded_defaults_are_readable_against_an_empty_database(self, client):
        """"A single, always-present configuration row supplies every threshold, limit and
        rate this system reasons about. It is seeded at process start with all of the
        defaults below, so reading it succeeds against an empty database."
        "inquiry_velocity_threshold — the inquiry count inside that trailing window at or
        above which a draining alert fires. Default 5."
        "claim_window_days — the number of days after purchase during which a victim claim
        may be filed. Default 90."

        Design: Corner/endpoints/risk_policy_put_merges_only_the_supplied_thresholds
        """
        policy = validate_success(client.get_risk_policy(make_platform_admin_headers()))

        assert policy["inquiry_velocity_threshold"] == 5
        assert policy["claim_window_days"] == 90

    def test_a_two_field_write_leaves_every_other_threshold_at_its_default(self, client):
        """"it is updated by partial write: only the keys supplied on the update are
        overwritten, and omitted keys retain their current values."
        "drain_watch_score_threshold — the drain risk score at or above which a card's
        fraud posture escalates to WATCH. Default 40."
        "reissue_cap_cents — a hard ceiling on the gross recovery computed for a claim; an
        approval whose gross exceeds this cap is refused outright. Default 100000, one
        thousand dollars."

        Design: Corner/endpoints/risk_policy_put_merges_only_the_supplied_thresholds
        """
        admin = make_platform_admin_headers()

        response = client.update_risk_policy(
            {"inquiry_velocity_threshold": 3, "claim_window_days": 30}, admin
        )

        written = validate_success(response, 200)
        assert written["inquiry_velocity_threshold"] == 3
        assert written["claim_window_days"] == 30
        assert written["drain_watch_score_threshold"] == 40
        assert written["reissue_cap_cents"] == 100000

    def test_a_second_partial_write_does_not_reset_the_first_one(self, client):
        """"only the keys supplied on the update are overwritten, and omitted keys retain
        their current values."
        "drain_restrict_score_threshold — the drain risk score at or above which the posture
        escalates to RESTRICTED. Default 70."
        "recovery_factor_bps — the basis points of each unauthorized redemption line that
        the reissue policy restores to the victim. Default 8500, which is eighty-five
        percent."

        Design: Corner/endpoints/risk_policy_put_merges_only_the_supplied_thresholds
        """
        admin = make_platform_admin_headers()
        validate_success(
            client.update_risk_policy(
                {"inquiry_velocity_threshold": 3, "claim_window_days": 30}, admin
            )
        )

        second = validate_success(client.update_risk_policy({"inquiry_velocity_threshold": 4}, admin))

        assert second["inquiry_velocity_threshold"] == 4
        assert second["claim_window_days"] == 30
        read_back = validate_success(client.get_risk_policy(make_fraud_analyst_headers("analyst-68")))
        assert read_back["inquiry_velocity_threshold"] == 4
        assert read_back["claim_window_days"] == 30
        assert read_back["drain_restrict_score_threshold"] == 70
        assert read_back["recovery_factor_bps"] == 8500

    def test_every_accepted_write_bumps_the_singleton_version_by_exactly_one(self, client):
        """"Updating the register increments its version by 1 and never retroactively
        recomputes anything already persisted."

        Design: Corner/endpoints/risk_policy_put_merges_only_the_supplied_thresholds
        """
        admin = make_platform_admin_headers()
        before = validate_success(client.get_risk_policy(admin))

        first = validate_success(
            client.update_risk_policy(
                {"inquiry_velocity_threshold": 3, "claim_window_days": 30}, admin
            )
        )
        second = validate_success(client.update_risk_policy({"inquiry_velocity_threshold": 4}, admin))

        assert first["version"] == before["version"] + 1
        assert second["version"] == first["version"] + 1


class TestAlertTriageAction:
    """One triage call moves the alert, stamps its actor, re-scores the card and
    re-derives the store's floor — while leaving the alert's exposure snapshot alone."""

    def _world(self, client):
        """A 10000-cent card drawn down by a single 4000-cent redemption at its own store,
        carrying one OPEN alert raised by analyst-69."""
        store = create_store(
            client, name="Triage Action Store", region_code="NE", address_line="40 Triage Ter"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-TA", expected_card_count=6)
        built = funded_physical_card(client, 10000, store=store, rack=rack)
        card_id = built["card"]["id"]
        redeem(
            client,
            card_id,
            4000,
            store["id"],
            headers=make_pos_associate_headers("pos-69"),
            pos_terminal_id="T-69",
        )
        alert = open_alert(
            client,
            card_id,
            "MANUAL_REVIEW",
            headers=make_fraud_analyst_headers("analyst-69"),
            note="walk-in complaint",
        )
        return store, card_id, alert

    def test_triage_moves_the_alert_and_stamps_the_acting_analyst(self, client):
        """"A manually raised alert starts in OPEN with basis_velocity_count and
        basis_drain_score both at 0."
        "The alert moves OPEN → TRIAGED, triaged_by_user_id is recorded from the caller's
        X-User-ID, the card's redemption-weighted drain score is recomputed as described in
        §3.6 and copied into the alert's basis_drain_score, the card's posture escalates
        upward only under the same ladder — reaching RESTRICTED when the recomputed score is
        at or above drain_restrict_score_threshold and the card's current rung is lower — and
        the store's open_alert_count and floor_posture are recomputed."

        Design: Corner/endpoints/alert_triage_action_records_the_actor_and_scores_the_card
        """
        _, _, alert = self._world(client)
        assert alert["state"] == "OPEN"
        assert alert["basis_drain_score"] == 0
        assert alert["basis_velocity_count"] == 0

        response = client.triage_draining_alert(
            alert["id"],
            {
                "triage_note": "reviewed the single 4000 redemption",
                "redemption_pattern_reviewed": True,
            },
            make_fraud_analyst_headers("analyst-69"),
        )

        triaged = validate_success(response, 200)
        assert triaged["state"] == "TRIAGED"
        assert triaged["triaged_by_user_id"] == "analyst-69"

    def test_triage_writes_the_redemption_weighted_score_without_escalating_the_posture(
        self, client
    ):
        """"The redemption-weighted score is recomputed when an alert on the card is triaged,
        written to the card's drain_risk_score_redemption and copied into the alert's
        basis_drain_score. Its raw figure is 45 multiplied by the card's drawdown_ratio, plus
        14 points per entry in distinct_merchant_count, plus 6 points per event in
        recent_redemption_count."
        "Otherwise, if the score is at or above drain_watch_score_threshold, the target is
        WATCH. Otherwise the target is CLEAR."

        Design: Corner/endpoints/alert_triage_action_records_the_actor_and_scores_the_card
        """
        _, card_id, alert = self._world(client)
        assert float(read_card(client, card_id)["drawdown_ratio"]) == pytest.approx(0.40, abs=0.01)

        triaged = triage_alert(
            client,
            alert["id"],
            headers=make_fraud_analyst_headers("analyst-69"),
            triage_note="reviewed the single 4000 redemption",
        )

        assert triaged["basis_drain_score"] == 38
        assert triaged["basis_drain_score"] == expected_redemption_drain_score(0.40, 1, 1)
        card = read_card(client, card_id)
        assert card["drain_risk_score_redemption"] == 38
        assert card["risk_posture"] == "CLEAR"

    def test_triage_never_recomputes_the_exposure_snapshot_and_leaves_the_floor_open(
        self, client
    ):
        """"Every alert captures exposure_cents at the instant it is created, and that figure
        is a frozen snapshot that is never recomputed. It is the card's current_balance_cents
        plus its total_redeemed_cents — that is, the total funds the alert puts at risk: what
        is still redeemable plus what has already been drained away. Later redemptions,
        reversals, triage and resolution all leave it untouched."
        "An alert count landing exactly on the threshold heightens the floor while one below
        it does not."

        Design: Corner/endpoints/alert_triage_action_records_the_actor_and_scores_the_card
        """
        store, _, alert = self._world(client)
        assert alert["exposure_cents"] == 10000

        triage_alert(
            client,
            alert["id"],
            headers=make_fraud_analyst_headers("analyst-69"),
            triage_note="reviewed the single 4000 redemption",
        )

        assert read_alert(client, alert["id"])["exposure_cents"] == 10000
        refreshed = read_store(client, store["id"])
        assert refreshed["open_alert_count"] == 1
        assert refreshed["floor_posture"] == "OPEN"


class TestReferralRequiresAConfirmedAlert:
    """A law-enforcement packet may be filed only once the alert is CONFIRMED."""

    def _world(self, client):
        """A 10000-cent card drawn down by 4000, carrying one OPEN alert raised on a
        clustered redemption pattern by analyst-70."""
        store = create_store(
            client, name="Referral Gate Store", region_code="MW", address_line="41 Referral Row"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-RG", expected_card_count=6)
        built = funded_physical_card(client, 10000, store=store, rack=rack)
        card_id = built["card"]["id"]
        redeem(
            client,
            card_id,
            4000,
            store["id"],
            headers=make_pos_associate_headers("pos-70"),
            pos_terminal_id="T-70",
        )
        alert = open_alert(
            client,
            card_id,
            "REDEMPTION_PATTERN",
            headers=make_fraud_analyst_headers("analyst-70"),
            note="clustered redemptions",
        )
        return store, card_id, alert

    def test_filing_is_refused_while_the_alert_is_open_and_again_while_it_is_triaged(
        self, client
    ):
        """"Filing against an alert in any state other than CONFIRMED is refused with
        ERR_ALERT_NOT_CONFIRMED."
        "a law-enforcement referral may only be filed against a CONFIRMED alert, otherwise
        ERR_ALERT_NOT_CONFIRMED (422)."

        Design: Corner/endpoints/referral_requires_a_confirmed_alert
        """
        _, _, alert = self._world(client)
        manager = make_risk_manager_headers("risk-70")

        while_open = client.create_law_enforcement_referral(
            referral_payload(
                alert["id"],
                agency_name="State Retail Crime Unit",
                packet_summary="filed while still open",
            ),
            manager,
        )

        validate_error(while_open, ERR_ALERT_NOT_CONFIRMED, 422)
        triaged = triage_alert(
            client,
            alert["id"],
            headers=make_fraud_analyst_headers("analyst-70"),
            triage_note="pattern confirmed against POS logs",
        )
        assert triaged["state"] == "TRIAGED"
        while_triaged = client.create_law_enforcement_referral(
            referral_payload(
                alert["id"],
                agency_name="State Retail Crime Unit",
                packet_summary="filed while only triaged",
            ),
            manager,
        )
        validate_error(while_triaged, ERR_ALERT_NOT_CONFIRMED, 422)

    def test_the_accepted_packet_copies_the_exposure_snapshot_and_its_filing_identity(
        self, client
    ):
        """"The referral records referred_by_user_id from the caller's X-User-ID, stamps
        referred_at from the logical clock, and takes exposure_snapshot_cents as a second,
        independent copy of the alert's exposure_cents — copied rather than joined, so that
        the packet remains a standalone immutable record even if anything about the alert
        were later to change."
        "Endpoints that create a new resource respond with 201 Created."

        Design: Corner/endpoints/referral_requires_a_confirmed_alert
        """
        _, _, alert = self._world(client)
        triage_alert(client, alert["id"], headers=make_fraud_analyst_headers("analyst-70"))
        confirmed = resolve_alert(
            client, alert["id"], "CONFIRM", headers=make_risk_manager_headers("risk-70")
        )
        assert confirmed["state"] == "CONFIRMED"

        response = client.create_law_enforcement_referral(
            referral_payload(
                alert["id"],
                agency_name="State Retail Crime Unit",
                packet_summary="confirmed drain of a physical rack card",
                case_reference="SRCU-7001",
            ),
            make_risk_manager_headers("risk-70"),
        )

        referral = validate_success(response, 201)
        assert referral["exposure_snapshot_cents"] == read_alert(client, alert["id"])["exposure_cents"]
        assert referral["exposure_snapshot_cents"] == 10000
        assert referral["referred_by_user_id"] == "risk-70"
        assert parse_instant(referral["referred_at"]) == parse_instant(CLOCK_ORIGIN)
        assert referral["agency_name"] == "State Retail Crime Unit"
        assert referral["case_reference"] == "SRCU-7001"

    def test_the_confirm_that_unlocks_filing_also_freezes_the_card_and_the_packet_is_immutable(
        self, client
    ):
        """"Hop two follows from the alert being confirmed: the card's risk_posture is forced
        to FROZEN, from whatever rung it was on — CLEAR → FROZEN, WATCH → FROZEN or
        RESTRICTED → FROZEN."
        "Referrals carry only id and created_at; they have no updated_at, no version, and no
        update, delete or state-transition operation exists for them anywhere."

        Design: Corner/endpoints/referral_requires_a_confirmed_alert
        """
        _, card_id, alert = self._world(client)
        triage_alert(client, alert["id"], headers=make_fraud_analyst_headers("analyst-70"))
        resolve_alert(client, alert["id"], "CONFIRM", headers=make_risk_manager_headers("risk-70"))

        referral = validate_success(
            client.create_law_enforcement_referral(
                referral_payload(alert["id"], packet_summary="confirmed drain, packet filed"),
                make_risk_manager_headers("risk-70"),
            ),
            201,
        )

        assert read_card(client, card_id)["risk_posture"] == "FROZEN"
        assert "version" not in referral
        assert "updated_at" not in referral
        rows, meta = validate_paginated(
            client.list_alert_referrals(alert["id"], make_fraud_analyst_headers("analyst-70"))
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [referral["id"]]


class TestExposureSummaryIsAPureRead:
    """The conserved-quantity read is derived on every call and persists nothing."""

    def _world(self, client):
        """One 5000-cent funded card with no redemptions, and one period over
        2026-08-01..2026-09-01 closed on an empty alert set."""
        store = create_store(
            client, name="Pure Read Store", region_code="SE", address_line="42 Read Rd"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-PR", expected_card_count=6)
        funded_physical_card(client, 5000, store=store, rack=rack)
        period = open_period(
            client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", label="2026-08 pure read"
        )
        closed = close_period(
            client,
            period["id"],
            headers=make_liability_accountant_headers("acct-71"),
            close_note="clean month",
        )
        return closed

    def test_the_summary_reports_the_live_funded_population_and_a_zero_alert_basis(self, client):
        """"It reports net_funded_liability_cents, computed live as the sum of
        current_balance_cents over cards whose activation_state is ACTIVE or DEPLETED, minus
        that period's unauthorized_writeoff_cents; funded_card_count, the number of cards in
        that same funded population; in_period_alert_count, the number of alerts created
        inside the period's half-open span in any state; and confirmed_alert_count, how many
        of those are CONFIRMED."
        "A period with no in-period alerts closes with a gross exposure of 0, a basis count of
        0 and a reserve of 0 — zero, not empty, and certainly not an error."

        Design: Corner/endpoints/exposure_summary_is_a_pure_read_that_stores_nothing
        """
        closed = self._world(client)
        assert closed["state"] == "CLOSED"

        response = client.get_exposure_summary(
            closed["id"], make_risk_manager_headers("risk-71")
        )

        summary = validate_success(response, 200)
        assert summary["net_funded_liability_cents"] == 5000
        assert summary["funded_card_count"] == 1
        assert summary["outstanding_liability_cents"] == 5000
        assert summary["unauthorized_writeoff_cents"] == 0
        assert summary["gross_exposure_cents"] == 0
        assert summary["in_period_alert_count"] == 0
        assert summary["confirmed_alert_count"] == 0
        assert summary["provisional_reserve_cents"] == 0

    def test_the_final_reserve_stays_empty_because_only_a_restatement_writes_it(self, client):
        """"A new period is created in OPEN with unauthorized_writeoff_cents at 0,
        restatement_count at 0, and outstanding_liability_cents, gross_exposure_cents,
        reserve_basis_alert_count, provisional_reserve_cents, final_reserve_cents, closed_at,
        restated_at, close_note and restatement_note all empty."
        "It requires a restatement_note, stamps restated_at, and increments restatement_count
        by 1. It books the final reserve on the settled basis that only proven fraud is
        reservable: the basis narrows to in-period alerts whose state is exactly CONFIRMED,
        and final_reserve_cents is final_reserve_rate_bps applied to the recomputed
        gross_exposure_cents, rounded half-up once over the aggregate."

        Design: Corner/endpoints/exposure_summary_is_a_pure_read_that_stores_nothing
        """
        closed = self._world(client)

        summary = read_exposure_summary(
            client, closed["id"], headers=make_liability_accountant_headers("acct-71")
        )

        assert not summary["final_reserve_cents"]
        assert read_period(client, closed["id"])["restatement_count"] == 0

    def test_two_consecutive_reads_return_the_same_body_and_move_no_version(self, client):
        """"The read stores nothing and increments no version."
        "Derived values are recomputed eagerly, inside the request that disturbs their inputs
        — this system is immediately consistent and has no background recomputation, no
        lazy-on-read refresh and no eventual convergence."

        Design: Corner/endpoints/exposure_summary_is_a_pure_read_that_stores_nothing
        """
        closed = self._world(client)

        first = read_exposure_summary(
            client, closed["id"], headers=make_risk_manager_headers("risk-71")
        )
        second = read_exposure_summary(
            client, closed["id"], headers=make_liability_accountant_headers("acct-71")
        )

        assert first == second
        after = read_period(client, closed["id"])
        assert after["version"] == closed["version"]
        assert after["restatement_count"] == 0


class TestBulkRequestInfoReturnsTheOrderToPending:
    """The reversal edge of the bulk-order lifecycle, and what it costs the next approval."""

    def _order(self, client):
        """20 cards at 5000 each: a subtotal of 100000 in the 225-basis-point band, a fee of
        2250 and a total of 102250, which is above bulk_identity_threshold_cents, so the
        order opens in PENDING_IDENTITY and one capture moves it to IDENTITY_VERIFIED."""
        store = create_store(
            client, name="Request Info Store", region_code="NW", address_line="43 Info Ln"
        )
        opened = open_bulk_order(
            client,
            store["id"],
            card_quantity=20,
            face_value_cents_each=5000,
            purchaser_name="Northwind Rewards Co",
            payment_method="CORPORATE_ACH",
        )
        verified = capture_identity(
            client,
            opened["id"],
            id_type="PASSPORT",
            id_number_hash="idh-72-a",
            id_expiry_date="2031-01-31",
        )
        return opened, verified

    def _read_order(self, client, order_id):
        return validate_success(
            client.get_bulk_purchase_order(order_id, make_risk_manager_headers("risk-72")), 200
        )

    def test_request_info_reverses_the_identity_step_and_counts_the_round_trip(self, client):
        """"The request-more-information decision is the cyclic edge of this lifecycle and is
        admitted only from IDENTITY_VERIFIED: it returns the order to PENDING_IDENTITY, clears
        identity_id_type, identity_id_number_hash and identity_id_expiry_date all back to
        empty, and increments info_request_count by 1."

        Design: Corner/endpoints/bulk_request_info_clears_identity_and_returns_the_order_to_pending
        """
        opened, verified = self._order(client)
        assert opened["state"] == "PENDING_IDENTITY"
        assert verified["state"] == "IDENTITY_VERIFIED"
        assert verified["identity_id_number_hash"] == "idh-72-a"

        bounced = decide_bulk_order(
            client,
            opened["id"],
            "REQUEST_INFO",
            headers=make_risk_manager_headers("risk-72"),
            decision_note="passport image unreadable",
        )

        assert bounced["state"] == "PENDING_IDENTITY"
        assert not bounced["identity_id_type"]
        assert not bounced["identity_id_number_hash"]
        assert not bounced["identity_id_expiry_date"]
        assert bounced["info_request_count"] == 1
        assert bounced["version"] == verified["version"] + 1

    def test_the_cleared_hash_makes_the_next_approval_fail_until_a_new_id_lands(self, client):
        """"on an order whose total is at or above bulk_identity_threshold_cents,
        identity_id_number_hash must not be empty, otherwise the approval is refused with
        ERR_IDENTITY_VERIFICATION_REQUIRED."
        "Either terminal decision records decided_by_user_id from the caller's X-User-ID
        along with the decision_note, and increments the order's version."

        Design: Corner/endpoints/bulk_request_info_clears_identity_and_returns_the_order_to_pending
        """
        opened, _ = self._order(client)
        risk = make_risk_manager_headers("risk-72")
        bounced = decide_bulk_order(
            client, opened["id"], "REQUEST_INFO", headers=risk, decision_note="unreadable"
        )

        refused = client.decide_bulk_purchase_order(
            opened["id"],
            bulk_decision_payload("APPROVE", decision_note="approving without the replacement ID"),
            risk,
        )

        validate_error(refused, ERR_IDENTITY_VERIFICATION_REQUIRED, 422)
        still = self._read_order(client, opened["id"])
        assert still["state"] == "PENDING_IDENTITY"
        assert still["version"] == bounced["version"]
        recaptured = capture_identity(
            client,
            opened["id"],
            id_type="PASSPORT",
            id_number_hash="idh-72-b",
            id_expiry_date="2031-01-31",
        )
        assert recaptured["state"] == "IDENTITY_VERIFIED"
        assert recaptured["identity_id_number_hash"] == "idh-72-b"
        approved = decide_bulk_order(
            client, opened["id"], "APPROVE", headers=risk, decision_note="replacement ID accepted"
        )
        assert approved["state"] == "APPROVED"
        assert approved["decided_by_user_id"] == "risk-72"
        assert approved["version"] == recaptured["version"] + 1

    def test_the_loop_leaves_the_money_frozen_and_never_clears_the_counter(self, client):
        """"An order may loop between PENDING_IDENTITY and IDENTITY_VERIFIED any number of
        times, and each loop leaves the money fields alone — the subtotal, the fee rate, the
        activation fee and the total are frozen at creation and are never recomputed by a
        decision of any kind."

        Design: Corner/endpoints/bulk_request_info_clears_identity_and_returns_the_order_to_pending
        """
        opened, _ = self._order(client)
        pricing = expected_bulk_pricing(20, 5000)
        assert pricing["total_cents"] == 102250
        assert_bulk_pricing(opened, pricing)
        risk = make_risk_manager_headers("risk-72")

        decide_bulk_order(
            client, opened["id"], "REQUEST_INFO", headers=risk, decision_note="unreadable"
        )
        capture_identity(
            client,
            opened["id"],
            id_type="PASSPORT",
            id_number_hash="idh-72-b",
            id_expiry_date="2031-01-31",
        )
        approved = decide_bulk_order(
            client, opened["id"], "APPROVE", headers=risk, decision_note="replacement ID accepted"
        )

        assert_bulk_pricing(approved, pricing)
        assert approved["info_request_count"] == 1
        assert self._read_order(client, opened["id"])["info_request_count"] == 1


class TestReferralsAreScopedToTheirAlert:
    """The packet sub-collection hangs off one alert, not off the card or the store."""

    def _world(self, client):
        """Two 5000-cent cards on the same INTACT rack in the same store: alertA on cardA is
        driven to CONFIRMED, while alertB on cardB is left OPEN."""
        store = create_store(
            client, name="Referral Scope Store", region_code="SW", address_line="44 Scope St"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-RS", expected_card_count=6)
        card_a = funded_physical_card(client, 5000, store=store, rack=rack)["card"]["id"]
        card_b = funded_physical_card(client, 5000, store=store, rack=rack)["card"]["id"]
        analyst = make_fraud_analyst_headers("analyst-73")
        alert_a = open_alert(client, card_a, "MANUAL_REVIEW", headers=analyst, note="cardA")
        alert_b = open_alert(client, card_b, "MANUAL_REVIEW", headers=analyst, note="cardB")
        triage_alert(client, alert_a["id"], headers=analyst, triage_note="cardA reviewed")
        confirmed = resolve_alert(
            client,
            alert_a["id"],
            "CONFIRM",
            headers=make_risk_manager_headers("risk-73"),
            resolution_note="cardA confirmed",
        )
        assert confirmed["state"] == "CONFIRMED"
        assert read_alert(client, alert_b["id"])["state"] == "OPEN"
        return card_b, alert_a["id"], alert_b["id"]

    def test_each_filed_packet_names_the_alert_it_documents(self, client):
        """"Once an alert is CONFIRMED, a FraudAnalyst or a RiskManager may package it for law
        enforcement, naming the alert_id, the receiving agency_name (1 to 120 characters), a
        packet_summary narrative of 1 to 2000 characters transmitted with the packet, and
        optionally a case_reference when the agency has already assigned a case number."
        "The referral records referred_by_user_id from the caller's X-User-ID."

        Design: Corner/endpoints/referrals_are_scoped_to_the_alert_they_were_filed_against
        """
        _, alert_a, _ = self._world(client)

        first = client.create_law_enforcement_referral(
            referral_payload(
                alert_a, agency_name="City Police Retail Detail", packet_summary="initial packet"
            ),
            make_risk_manager_headers("risk-73"),
        )
        second = client.create_law_enforcement_referral(
            referral_payload(
                alert_a, agency_name="County Prosecutor", packet_summary="supplemental packet"
            ),
            make_fraud_analyst_headers("analyst-73"),
        )

        packet_one = validate_success(first, 201)
        packet_two = validate_success(second, 201)
        assert packet_one["alert_id"] == alert_a
        assert packet_two["alert_id"] == alert_a
        assert packet_two["agency_name"] == "County Prosecutor"
        assert packet_two["referred_by_user_id"] == "analyst-73"

    def test_the_sub_collection_is_keyed_on_the_alert_and_not_on_the_card_or_store(self, client):
        """"A card's balance-inquiry log, a card's competing holds, a card's
        secondary-marketplace listings, and an alert's law-enforcement referral packets are
        each reachable only through the owning resource's path."
        "a referral is discovered either by reading it directly by its own id or through the
        referral list on the alert it documents."

        Design: Corner/endpoints/referrals_are_scoped_to_the_alert_they_were_filed_against
        """
        _, alert_a, alert_b = self._world(client)
        risk = make_risk_manager_headers("risk-73")
        one = validate_success(
            client.create_law_enforcement_referral(
                referral_payload(
                    alert_a, agency_name="City Police Retail Detail", packet_summary="initial packet"
                ),
                risk,
            ),
            201,
        )
        two = validate_success(
            client.create_law_enforcement_referral(
                referral_payload(
                    alert_a, agency_name="County Prosecutor", packet_summary="supplemental packet"
                ),
                make_fraud_analyst_headers("analyst-73"),
            ),
            201,
        )

        on_a, meta_a = validate_paginated(client.list_alert_referrals(alert_a, risk))
        on_b, meta_b = validate_paginated(client.list_alert_referrals(alert_b, risk))

        assert meta_a["total_count"] == 2
        assert {row["id"] for row in on_a} == {one["id"], two["id"]}
        assert meta_b["total_count"] == 0
        assert on_b == []

    def test_confirming_one_alert_left_the_sibling_card_and_alert_alone(self, client):
        """"Referrals carry only id and created_at; they have no updated_at, no version, and
        no update, delete or state-transition operation exists for them anywhere."
        "A manually raised alert starts in OPEN with basis_velocity_count and
        basis_drain_score both at 0."

        Design: Corner/endpoints/referrals_are_scoped_to_the_alert_they_were_filed_against
        """
        card_b, alert_a, alert_b = self._world(client)

        packet = validate_success(
            client.create_law_enforcement_referral(
                referral_payload(
                    alert_a, agency_name="City Police Retail Detail", packet_summary="initial packet"
                ),
                make_risk_manager_headers("risk-73"),
            ),
            201,
        )

        assert "version" not in packet
        assert "updated_at" not in packet
        assert read_alert(client, alert_b)["state"] == "OPEN"
        assert read_card(client, card_b)["risk_posture"] == "CLEAR"


class TestStoreListFiltersComposeWithPagination:
    """Both filters narrow the set before the window is applied, and they intersect."""

    def _stores(self, client):
        """Three stores, of which the first is driven to SUSPENDED by an audit reporting
        three broken seals and no missing cards; the other two are left OPEN with no racks."""
        store_one = create_store(
            client, name="Alpha Northeast", region_code="NE", address_line="45 Alpha Ave"
        )
        store_two = create_store(
            client, name="Bravo Northeast", region_code="NE", address_line="46 Bravo Blvd"
        )
        store_three = create_store(
            client, name="Charlie Midwest", region_code="MW", address_line="47 Charlie Ct"
        )
        rack = create_rack(client, store_one["id"], rack_label="RACK-SL", expected_card_count=8)
        audited = audit_rack(client, rack["id"], 8, seal_breaks_observed=3)
        assert audited["tamper_state"] == "TAMPERED"
        return store_one["id"], store_two["id"], store_three["id"]

    def test_the_posture_filter_sees_the_derived_suspension_and_not_the_birth_value(self, client):
        """"If missing_card_count is at least rack_shrink_threshold, or seal_breaks_observed is
        at least rack_seal_break_threshold, the rack is TAMPERED."
        "The derivation first counts the store's racks classified TAMPERED into
        tampered_rack_count and those classified SUSPECT into suspect_rack_count ... Then,
        first match winning: if tampered_rack_count is at least 1 the floor is SUSPENDED."

        Design: Corner/endpoints/store_list_filters_compose_with_pagination_and_total_count
        """
        store_one, store_two, store_three = self._stores(client)
        suspended = read_store(client, store_one)
        assert suspended["floor_posture"] == "SUSPENDED"
        assert suspended["tampered_rack_count"] == 1

        rows, meta = validate_paginated(
            client.list_stores(make_fraud_analyst_headers("analyst-74"), {"floor_posture": "OPEN"})
        )

        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert {row["id"] for row in rows} == {store_two, store_three}

    def test_the_two_filters_intersect_rather_than_union(self, client):
        """"Most list collections accept a state query parameter that filters on the
        resource's lifecycle state field exactly, alongside whatever foreign-key filters that
        collection offers; an unrecognised value for such a filter is an invalid request
        rather than an empty result."
        "a region_code of exactly two uppercase letters used for reporting rollups."

        Design: Corner/endpoints/store_list_filters_compose_with_pagination_and_total_count
        """
        store_one, store_two, _ = self._stores(client)
        analyst = make_fraud_analyst_headers("analyst-74")

        by_region, region_meta = validate_paginated(
            client.list_stores(analyst, {"region_code": "NE"})
        )
        both, both_meta = validate_paginated(
            client.list_stores(analyst, {"region_code": "NE", "floor_posture": "OPEN"})
        )

        assert region_meta["total_count"] == 2
        assert {row["id"] for row in by_region} == {store_one, store_two}
        assert both_meta["total_count"] == 1
        assert [row["id"] for row in both] == [store_two]

    def test_total_count_describes_the_filtered_set_and_not_the_returned_page(self, client):
        """"List responses carry limit, offset, total_count and has_more in the meta block,
        where total_count is the number of records matching the filters before the window is
        applied and has_more indicates whether records remain beyond the current window."

        Design: Corner/endpoints/store_list_filters_compose_with_pagination_and_total_count
        """
        store_one, store_two, _ = self._stores(client)

        rows, meta = validate_paginated(
            client.list_stores(
                make_fraud_analyst_headers("analyst-74"),
                {"region_code": "NE", "limit": 1, "offset": 1},
            )
        )

        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] in {store_one, store_two}
