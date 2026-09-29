"""Derived-figure arithmetic: every number the server computes rather than stores.

Screening scores, bulk activation fees, hold capacity, rack classification, store
floor posture, the card balance projection, the funded-liability population and
the listing-validation decision are all derived: "No endpoint accepts a derived
field as input, and an attempt to supply one is simply ignored rather than
honoured."  Each test re-derives the expected figure from the stated formula
before comparing it to the service's answer.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CLOCK_ORIGIN,
    DIGITAL_DECLINE_SCORE_THRESHOLD,
    DIGITAL_HOLD_SCORE_THRESHOLD,
    DRAIN_WATCH_SCORE_THRESHOLD,
    FLOOR_HEIGHTENED_ALERT_THRESHOLD,
    PROVISIONAL_RESERVE_RATE_BPS,
    RACK_SEAL_BREAK_THRESHOLD,
    apply_bps,
    assert_bulk_pricing,
    assert_card_projection,
    assert_empty,
    assert_exposure_summary,
    assert_screening_components,
    assert_signed_amount,
    assert_store_counters,
    assert_unchanged_version,
    expected_bulk_pricing,
    expected_drawdown_ratio,
    expected_floor_posture,
    expected_inquiry_drain_score,
    expected_missing_card_count,
    expected_net_funded_liability,
    expected_reserve,
    expected_screening_components,
    expected_screening_score,
    expected_tamper_state,
)
from test_helpers.factories import redemption_hold_payload, reversal_payload
from test_helpers.fixtures import (
    audit_rack,
    close_period,
    create_rack,
    create_store,
    funded_physical_card,
    hold_on_card,
    inquire,
    list_data_and_meta,
    open_bulk_order,
    open_digital_issuance,
    open_period,
    open_alert,
    override_posture,
    read_card,
    read_exposure_summary,
    read_period,
    read_policy,
    read_store,
    redeem,
    resolve_alert,
    reverse,
    screen_issuance,
    set_policy,
    settle_hold,
    shift,
    stock_card,
    submit_listing,
    total_count,
    triage_alert,
    validate_listing,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_reseller_partner_headers,
    make_risk_manager_headers,
)

# The signal set whose blend lands exactly on 70.25 and therefore stores 70.
DECLINE_SIGNALS = {
    "device_reputation_score": 5,
    "email_age_days": 3,
    "payment_risk_band": "HIGH",
}
DECLINE_FACE_VALUE = 30000


class TestDigitalScreeningScoreBands:
    """The decline band is read from the policy register, and the blend rounds half up."""

    def test_score_exactly_at_the_configured_decline_threshold_declines(self, client):
        """"it is updated by partial write: only the keys supplied on the update are
        overwritten, and omitted keys retain their current values."
        "A score at or above digital_decline_score_threshold sends the request to
        DECLINED with decline_reason set to DIGITAL_RISK_SCORE."
        "Both boundaries bite on the threshold itself: a score exactly equal to the hold
        threshold is held rather than approved, and a score exactly equal to the decline
        threshold is declined rather than held."

        Design: Corner/calculations/digital_score_declines_exactly_at_the_configured_decline_threshold
        """
        policy = set_policy(client, digital_decline_score_threshold=70)
        assert policy["digital_decline_score_threshold"] == 70
        assert policy["digital_hold_score_threshold"] == DIGITAL_HOLD_SCORE_THRESHOLD == 45

        request = open_digital_issuance(
            client,
            face_value_cents=DECLINE_FACE_VALUE,
            recipient_email_hash="eh-decline-70",
            **DECLINE_SIGNALS,
        )
        screened = screen_issuance(client, request["id"])

        expected = expected_screening_components(5, 3, "HIGH", DECLINE_FACE_VALUE)
        assert expected == {
            "device": 95,
            "email": 70,
            "payment": 60,
            "amount": 30,
            "base": 70,
            "bulk_surcharge": 0,
        }
        assert_screening_components(screened, expected)
        assert screened["screening_score"] == 70
        assert screened["screening_score"] == expected_screening_score(expected)
        assert screened["state"] == "DECLINED"
        assert screened["decline_reason"] == "DIGITAL_RISK_SCORE"

    def test_the_declined_digital_branch_mints_no_card_and_moves_no_money(self, client):
        """"Reaching APPROVED is what funds a card. For a DIGITAL request the server first
        mints a brand-new card with channel DIGITAL, no store, no rack, a funding state of
        INACTIVE and a posture of CLEAR, and points the request's card_id at it."
        "A DIGITAL request must omit store_id, rack_id and card_id entirely (the server
        fills the card reference in itself when it mints one at approval)"

        Design: Corner/calculations/digital_score_declines_exactly_at_the_configured_decline_threshold
        """
        set_policy(client, digital_decline_score_threshold=70)
        request = open_digital_issuance(
            client,
            face_value_cents=DECLINE_FACE_VALUE,
            recipient_email_hash="eh-decline-70",
            **DECLINE_SIGNALS,
        )

        screened = screen_issuance(client, request["id"])

        assert screened["state"] == "DECLINED"
        assert_empty(screened["card_id"], "card_id")
        assert total_count(client.list_ledger_events(make_platform_admin_headers())) == 0
        assert total_count(client.list_gift_cards(make_platform_admin_headers())) == 0
        stored = validate_success(
            client.get_issuance_request(request["id"], make_platform_admin_headers())
        )
        assert stored["screening_score"] == 70
        assert stored["decline_reason"] == "DIGITAL_RISK_SCORE"
        assert_empty(stored["card_id"], "card_id")

    def test_the_same_score_is_only_held_under_the_shipped_decline_default(self, client):
        """"digital_decline_score_threshold — the screening score at or above which the
        request is automatically declined. Default 75."
        "Otherwise, a score at or above digital_hold_score_threshold sends it to
        HELD_FOR_REVIEW with no decline reason."

        Design: Corner/calculations/digital_score_declines_exactly_at_the_configured_decline_threshold
        """
        policy = read_policy(client)
        assert policy["digital_decline_score_threshold"] == DIGITAL_DECLINE_SCORE_THRESHOLD == 75
        assert policy["digital_hold_score_threshold"] == 45

        request = open_digital_issuance(
            client,
            face_value_cents=DECLINE_FACE_VALUE,
            recipient_email_hash="eh-hold-70",
            **DECLINE_SIGNALS,
        )
        screened = screen_issuance(client, request["id"])

        assert screened["screening_score"] == 70
        assert screened["state"] == "HELD_FOR_REVIEW"
        assert_empty(screened["decline_reason"], "decline_reason")
        assert_empty(screened["card_id"], "card_id")


class TestDigitalScreeningHalfUpRounding:
    """The weighted blend lands on an exact half and must round away from zero."""

    def test_a_blend_of_two_point_five_rounds_up_to_three(self, client):
        """"Those four transformed components are then blended with fixed weights and
        rounded, exactly once, half up to an integer: thirty-five hundredths of the device
        component, plus twenty-five hundredths of the email component, plus twenty-five
        hundredths of the payment component, plus fifteen hundredths of the amount
        component."
        "Wherever a division or a rate application does not land on a whole cent, the
        result is rounded half up — a value whose fractional part is exactly one half
        always rounds away from zero to the larger magnitude, never to the nearest even
        number."

        Design: Corner/calculations/digital_score_rounds_half_up_at_two_point_five
        """
        assert read_policy(client)["digital_hold_score_threshold"] == 45

        request = open_digital_issuance(
            client,
            face_value_cents=5000,
            device_reputation_score=95,
            email_age_days=900,
            payment_risk_band="LOW",
            recipient_email_hash="eh-round-half-up",
        )
        screened = screen_issuance(client, request["id"])

        expected = expected_screening_components(95, 900, "LOW", 5000)
        assert expected == {
            "device": 5,
            "email": 0,
            "payment": 0,
            "amount": 5,
            "base": 3,
            "bulk_surcharge": 0,
        }
        assert_screening_components(screened, expected)
        # 0.35*5 + 0.25*0 + 0.25*0 + 0.15*5 == 2.5; banker's rounding and truncation
        # would both store 2.
        assert screened["screening_components"]["base"] == 3
        assert screened["screening_score"] == 3
        assert screened["state"] == "APPROVED"

    def test_the_approved_digital_card_is_minted_with_no_store_and_no_rack(self, client):
        """"For a DIGITAL request the server first mints a brand-new card with channel
        DIGITAL, no store, no rack, a funding state of INACTIVE and a posture of CLEAR,
        and points the request's card_id at it."
        "Digital cards are never stocked this way; the server mints them itself when a
        digital issuance request is approved, and such a card carries no store and no rack
        at all."
        "drawdown_ratio is then derived: 0.00 when total_loaded_cents is zero, and
        otherwise total_redeemed_cents divided by total_loaded_cents, rounded half up to
        two decimal places and clamped into the closed range 0.00 through 1.00."

        Design: Corner/calculations/digital_score_rounds_half_up_at_two_point_five
        """
        request = open_digital_issuance(
            client,
            face_value_cents=5000,
            device_reputation_score=95,
            email_age_days=900,
            payment_risk_band="LOW",
            recipient_email_hash="eh-round-half-up",
        )

        screened = screen_issuance(client, request["id"])

        assert screened["screening_score"] == 3
        assert screened["state"] == "APPROVED"
        minted = read_card(client, screened["card_id"])
        assert minted["channel"] == "DIGITAL"
        assert_empty(minted["store_id"], "store_id")
        assert_empty(minted["rack_id"], "rack_id")
        assert minted["activation_state"] == "ACTIVE"
        assert minted["current_balance_cents"] == 5000
        assert minted["total_loaded_cents"] == 5000
        assert float(minted["drawdown_ratio"]) == pytest.approx(
            expected_drawdown_ratio(0, 5000), abs=0.01
        )
        assert minted["drain_risk_score_inquiry"] == 0


class TestBulkFeeTierBoundaries:
    """One cent decides the band, and the top band is inclusive at its floor."""

    @pytest.mark.parametrize(
        "card_quantity,face_value_cents_each,subtotal,rate_bps,fee,total,state",
        [
            (1, 24999, 24999, 0, 0, 24999, "IDENTITY_VERIFIED"),
            (1, 25000, 25000, 150, 375, 25375, "IDENTITY_VERIFIED"),
            (20, 25000, 500000, 300, 15000, 515000, "PENDING_IDENTITY"),
        ],
        ids=["just-below-25000", "exactly-25000", "exactly-500000"],
    )
    def test_each_band_is_inclusive_at_its_lower_edge(
        self,
        client,
        card_quantity,
        face_value_cents_each,
        subtotal,
        rate_bps,
        fee,
        total,
        state,
    ):
        """"a subtotal below 25000 cents attracts no fee at all; from 25000 up to but not
        including 100000 cents the rate is 150 basis points; from 100000 up to but not
        including 500000 cents it is 225 basis points; and at 500000 cents or above it is
        300 basis points."
        "A subtotal of exactly 25000 cents sits in the 150-basis-point band, since the
        lower edge of each band is inclusive; 24999 cents pays nothing."
        "When total_cents is at or above bulk_identity_threshold_cents the order is
        created in PENDING_IDENTITY, because government identity is mandatory before
        approval."

        Design: Corner/calculations/bulk_fee_tier_boundaries_straddle_24999_25000_and_500000
        """
        store = create_store(client, name="Tier Edge Store", region_code="MW")

        order = open_bulk_order(
            client,
            store["id"],
            card_quantity=card_quantity,
            face_value_cents_each=face_value_cents_each,
            purchaser_name="Edge Case LLC",
            payment_method="CORPORATE_ACH",
        )

        expected = expected_bulk_pricing(card_quantity, face_value_cents_each)
        assert expected == {
            "face_value_subtotal_cents": subtotal,
            "fee_rate_bps": rate_bps,
            "activation_fee_cents": fee,
            "total_cents": total,
        }
        assert_bulk_pricing(order, expected)
        assert order["state"] == state

    def test_one_cent_over_the_edge_is_rated_on_the_whole_subtotal(self, client):
        """"Second, fee_rate_bps is selected from that pre-fee subtotal, as a whole-order
        average-rate band rather than a marginal ladder, so exactly one rate applies to
        the entire subtotal"
        "Third, activation_fee_cents is the subtotal multiplied by that basis-point figure
        and divided by 10000, rounded half up exactly once over the whole order."

        Design: Corner/calculations/bulk_fee_tier_boundaries_straddle_24999_25000_and_500000
        """
        store = create_store(client, name="Tier Edge Store", region_code="MW")

        below = open_bulk_order(client, store["id"], card_quantity=1, face_value_cents_each=24999)
        at_edge = open_bulk_order(client, store["id"], card_quantity=1, face_value_cents_each=25000)

        assert at_edge["face_value_subtotal_cents"] - below["face_value_subtotal_cents"] == 1
        assert below["fee_rate_bps"] == 0
        assert at_edge["fee_rate_bps"] == 150
        # A marginal ladder would rate only the single cent above the edge, so the fee
        # would still round to 0 rather than jumping to 375.
        assert below["activation_fee_cents"] == 0
        assert at_edge["activation_fee_cents"] == 375
        assert at_edge["activation_fee_cents"] == apply_bps(25000, 150)
        assert at_edge["total_cents"] == 25000 + 375


class TestHoldCapacityExcludesReleasedHolds:
    """Capacity is summed over ACTIVE holds only, so a release frees its reservation."""

    def test_a_released_hold_frees_capacity_for_an_overlapping_candidate(self, client):
        """"sum the amounts of every ACTIVE hold on the card that intersects the
        candidate, add the candidate's own amount, and refuse the candidate with
        ERR_HOLD_CAPACITY_EXCEEDED when that sum exceeds the card's
        current_balance_cents."
        "Only ACTIVE holds bear capacity: released, captured and expired holds free their
        capacity immediately, which is why advancing the logical clock past a hold's
        expiry can turn a refused candidate into an accepted one with nothing else having
        changed."

        Design: Corner/calculations/hold_capacity_excludes_released_holds
        """
        world = funded_physical_card(client, face_value_cents=10000)
        card_id = world["card"]["id"]
        first = hold_on_card(client, card_id, 6000, minutes=360)
        released = settle_hold(
            client, first["id"], "RELEASE", settle_note="shopper changed their mind"
        )
        assert released["state"] == "RELEASED"
        freed = read_card(client, card_id)
        assert freed["held_amount_cents"] == 0

        response = client.create_redemption_hold(
            card_id,
            redemption_hold_payload(9000, CLOCK_ORIGIN, shift(hours=6), freed["version"]),
            make_pos_associate_headers(),
        )

        second = validate_success(response, 201)
        assert second["state"] == "ACTIVE"
        assert second["amount_cents"] == 9000
        # 6000 + 9000 would have breached the 10000 balance had the release still counted.
        assert first["amount_cents"] + second["amount_cents"] > freed["current_balance_cents"]

    def test_the_released_and_the_live_hold_sit_side_by_side_on_the_card(self, client):
        """"A release moves the hold to RELEASED, records the disposition and note, leaves
        captured_amount_cents at 0, appends no ledger event, and leaves
        current_balance_cents entirely unchanged while recomputing held_amount_cents and
        available_balance_cents."
        "held_amount_cents is the sum of the amounts of the counted holds, and
        available_balance_cents is the current balance minus the held amount, floored at
        zero."

        Design: Corner/calculations/hold_capacity_excludes_released_holds
        """
        world = funded_physical_card(client, face_value_cents=10000)
        card_id = world["card"]["id"]
        first = hold_on_card(client, card_id, 6000, minutes=360)
        settle_hold(client, first["id"], "RELEASE", settle_note="shopper changed their mind")
        current = read_card(client, card_id)
        second = hold_on_card(client, card_id, 9000, minutes=360)
        assert second["hold_start"] == first["hold_start"]

        card = read_card(client, card_id)

        assert_card_projection(
            card,
            current_balance_cents=10000,
            held_amount_cents=9000,
            available_balance_cents=1000,
        )
        assert current["current_balance_cents"] == 10000
        rows, meta = list_data_and_meta(
            client.list_card_redemption_holds(card_id, make_risk_manager_headers())
        )
        assert meta["total_count"] == 2
        assert sorted(row["state"] for row in rows) == ["ACTIVE", "RELEASED"]
        assert [row["captured_amount_cents"] for row in rows if row["state"] == "RELEASED"] == [0]


class TestRackSealBreakThreshold:
    """Broken seals alone classify a rack, with nothing missing from the fixture."""

    def test_two_breaks_suspect_and_three_breaks_tampered_on_a_full_rack(self, client):
        """"If missing_card_count is at least rack_shrink_threshold, or
        seal_breaks_observed is at least rack_seal_break_threshold, the rack is TAMPERED.
        Otherwise, if missing_card_count is at least 1 or seal_breaks_observed is at least
        1, the rack is SUSPECT. Otherwise it is INTACT."
        "The rule is a disjunction and not a sum, so either signal alone reaches TAMPERED:
        with the defaults in place, three missing cards and zero broken seals is TAMPERED,
        and so is zero missing cards with three broken seals."
        "Shrink is then derived as the expected count minus the observed count, floored at
        zero and stored as missing_card_count"

        Design: Corner/calculations/rack_classification_uses_the_seal_break_threshold_at_two_and_three
        """
        assert read_policy(client)["rack_seal_break_threshold"] == RACK_SEAL_BREAK_THRESHOLD == 3
        store = create_store(client, name="Seal Break Store", region_code="SW")
        rack = create_rack(client, store["id"], rack_label="RACK-SB", expected_card_count=10)

        first = audit_rack(client, rack["id"], observed_card_count=10, seal_breaks_observed=2)
        second = audit_rack(client, rack["id"], observed_card_count=10, seal_breaks_observed=3)

        assert expected_missing_card_count(10, 10) == 0
        assert first["missing_card_count"] == 0
        assert first["tamper_state"] == expected_tamper_state(0, 2) == "SUSPECT"
        assert second["missing_card_count"] == 0
        assert second["tamper_state"] == expected_tamper_state(0, 3) == "TAMPERED"
        # Persisted verbatim, so the classification is reproducible from the stored row.
        assert second["seal_breaks_observed"] == 3
        assert second["observed_card_count"] == 10

    def test_the_tampered_rack_suspends_the_floor_and_empties_the_suspect_count(self, client):
        """"if tampered_rack_count is at least 1 the floor is SUSPENDED; otherwise, if
        suspect_rack_count is at least 1 or open_alert_count is at least
        floor_heightened_alert_threshold, the floor is HEIGHTENED; otherwise it is OPEN."
        "A single tampered rack outranks any number of alerts."
        "Classification is fully re-derived on every audit and is deliberately not sticky,
        with one exception."

        Design: Corner/calculations/rack_classification_uses_the_seal_break_threshold_at_two_and_three
        """
        store = create_store(client, name="Seal Break Store", region_code="SW")
        rack = create_rack(client, store["id"], rack_label="RACK-SB", expected_card_count=10)
        audit_rack(client, rack["id"], observed_card_count=10, seal_breaks_observed=2)
        after_suspect = read_store(client, store["id"], make_risk_manager_headers())
        assert_store_counters(
            after_suspect, floor_posture="HEIGHTENED", suspect_rack_count=1, tampered_rack_count=0
        )

        audit_rack(client, rack["id"], observed_card_count=10, seal_breaks_observed=3)

        store_now = read_store(client, store["id"], make_risk_manager_headers())
        assert_store_counters(
            store_now,
            floor_posture="SUSPENDED",
            tampered_rack_count=1,
            suspect_rack_count=0,
            open_alert_count=0,
        )
        assert store_now["floor_posture"] == expected_floor_posture(1, 0, 0)


class TestStoreFloorAlertPressure:
    """The floor tracks the live alert count against the threshold in both directions."""

    def _world(self, client):
        """A store, one INTACT rack and two ACTIVE 9000-cent physical cards on it."""
        store = create_store(client, name="Alert Pressure Store", region_code="NE")
        rack = create_rack(client, store["id"], rack_label="RACK-AP", expected_card_count=6)
        first = funded_physical_card(client, face_value_cents=9000, store=store, rack=rack)
        second = funded_physical_card(client, face_value_cents=9000, store=store, rack=rack)
        return {"store": store, "rack": rack, "card_a": first["card"], "card_b": second["card"]}

    def test_the_second_live_alert_heightens_the_floor_and_the_first_does_not(self, client):
        """"counts into open_alert_count every draining alert in state OPEN or TRIAGED
        whose card belongs to this store."
        "An alert count landing exactly on the threshold heightens the floor while one
        below it does not."
        "floor_heightened_alert_threshold — the number of live draining alerts on a store's
        cards at or above which the store's floor posture becomes heightened. Default 2."

        Design: Corner/calculations/store_floor_heightens_at_exactly_two_open_alerts_and_relaxes_on_dismissal
        """
        world = self._world(client)
        assert (
            read_policy(client)["floor_heightened_alert_threshold"]
            == FLOOR_HEIGHTENED_ALERT_THRESHOLD
            == 2
        )

        open_alert(client, world["card_a"]["id"], note="first report")
        after_one = read_store(client, world["store"]["id"], make_risk_manager_headers())
        open_alert(client, world["card_b"]["id"], note="second report")
        after_two = read_store(client, world["store"]["id"], make_risk_manager_headers())

        assert_store_counters(after_one, floor_posture="OPEN", open_alert_count=1)
        assert after_one["floor_posture"] == expected_floor_posture(0, 0, 1)
        assert_store_counters(after_two, floor_posture="HEIGHTENED", open_alert_count=2)
        assert after_two["floor_posture"] == expected_floor_posture(0, 0, 2)

    def test_a_triaged_alert_still_counts_but_a_dismissed_one_stops_immediately(self, client):
        """"Note that both CONFIRMED and DISMISSED alerts stop counting toward
        open_alert_count, so confirming the last live alert can relax the floor even though
        the fraud turned out to be real"
        "For the purposes of the store floor, note that a dismissed alert stops counting
        immediately and a reopened one starts counting again."
        "The derivation reads only rack and alert state and never its own previous value,
        so it terminates in a single pass with no oscillation, and it is bidirectional over
        time: remediating the last tampered rack drops the floor straight back to
        HEIGHTENED or OPEN, and resolving alerts below the threshold does the same."

        Design: Corner/calculations/store_floor_heightens_at_exactly_two_open_alerts_and_relaxes_on_dismissal
        """
        world = self._world(client)
        alert_a = open_alert(client, world["card_a"]["id"], note="first report")
        alert_b = open_alert(client, world["card_b"]["id"], note="second report")

        triaged = triage_alert(client, alert_b["id"], triage_note="no draining pattern")
        after_triage = read_store(client, world["store"]["id"], make_risk_manager_headers())
        dismissed = resolve_alert(
            client, alert_b["id"], "DISMISS", resolution_note="legitimate spending"
        )
        after_dismiss = read_store(client, world["store"]["id"], make_risk_manager_headers())

        assert triaged["state"] == "TRIAGED"
        assert_store_counters(after_triage, floor_posture="HEIGHTENED", open_alert_count=2)
        assert dismissed["state"] == "DISMISSED"
        assert_store_counters(after_dismiss, floor_posture="OPEN", open_alert_count=1)
        assert validate_success(
            client.get_draining_alert(alert_a["id"], make_platform_admin_headers())
        )["state"] == "OPEN"

    def test_neither_raising_nor_dismissing_an_alert_escalates_card_posture(self, client):
        """"Raising an alert recomputes the store's open_alert_count and floor_posture —
        which can heighten a floor once the live alert count reaches
        floor_heightened_alert_threshold — and increments the store's version when a store
        was touched."
        "A manually raised alert starts in OPEN with basis_velocity_count and
        basis_drain_score both at 0."
        "The card's risk_posture is then set to that target only when the target sits
        strictly higher on the ladder than the card's current rung."

        Design: Corner/calculations/store_floor_heightens_at_exactly_two_open_alerts_and_relaxes_on_dismissal
        """
        world = self._world(client)
        alert_a = open_alert(client, world["card_a"]["id"], note="first report")
        alert_b = open_alert(client, world["card_b"]["id"], note="second report")
        assert alert_a["basis_velocity_count"] == 0
        assert alert_a["basis_drain_score"] == 0

        triage_alert(client, alert_b["id"], triage_note="no draining pattern")
        resolve_alert(client, alert_b["id"], "DISMISS", resolution_note="legitimate spending")

        assert read_card(client, world["card_a"]["id"])["risk_posture"] == "CLEAR"
        assert read_card(client, world["card_b"]["id"])["risk_posture"] == "CLEAR"
        store_now = read_store(client, world["store"]["id"], make_risk_manager_headers())
        assert_store_counters(store_now, suspect_rack_count=0, tampered_rack_count=0)


class TestCardProjectionAfterReversal:
    """Reversing the middle redemption re-derives every counter, two of them upward."""

    def _world(self, client):
        """A 20000-cent card with three redemptions: 3000 and 1000 at its own store and
        4000 at a second merchant."""
        home = create_store(client, name="Projection Home Store", region_code="MW")
        other = create_store(client, name="Projection Merchant Two", region_code="MW")
        world = funded_physical_card(client, face_value_cents=20000, store=home)
        card_id = world["card"]["id"]
        first = redeem(client, card_id, 3000, home["id"], pos_terminal_id="T-56")
        middle = redeem(client, card_id, 4000, other["id"], pos_terminal_id="T-99")
        last = redeem(client, card_id, 1000, home["id"], pos_terminal_id="T-56")
        return {
            "home": home,
            "other": other,
            "card_id": card_id,
            "first": first,
            "middle": middle,
            "last": last,
        }

    def test_the_reversal_credit_raises_total_loaded_and_lowers_the_drawdown_ratio(self, client):
        """"total_loaded_cents is the sum of the raw amounts over the credit kinds only."
        "The credit kinds, whose signed_amount_cents is the positive amount, are
        ACTIVATION_LOAD, REDEMPTION_REVERSAL, REISSUE_CREDIT and REISSUE_DEBIT_REVERSAL."
        "drawdown_ratio is then derived: 0.00 when total_loaded_cents is zero, and
        otherwise total_redeemed_cents divided by total_loaded_cents, rounded half up to
        two decimal places and clamped into the closed range 0.00 through 1.00."

        Design: Corner/calculations/card_projection_rederives_every_counter_after_a_reversal
        """
        world = self._world(client)
        before = read_card(client, world["card_id"])
        assert_card_projection(
            before,
            current_balance_cents=12000,
            total_loaded_cents=20000,
            total_redeemed_cents=8000,
            drawdown_ratio=0.40,
        )

        reverse(client, world["middle"]["id"], reversal_reason="merchant double-charged the shopper")

        after = read_card(client, world["card_id"])
        assert after["total_loaded_cents"] == 24000
        assert after["total_redeemed_cents"] == 4000
        assert float(after["drawdown_ratio"]) == pytest.approx(0.17, abs=0.01)
        assert float(after["drawdown_ratio"]) == pytest.approx(
            expected_drawdown_ratio(4000, 24000), abs=0.01
        )
        # 4000 / 20000 == 0.20 is the answer a projection that forgot the reversal credit
        # would report.
        assert float(after["drawdown_ratio"]) != pytest.approx(0.20, abs=0.001)
        assert_card_projection(
            after,
            current_balance_cents=16000,
            available_balance_cents=16000,
        )
        assert after["activation_state"] == "ACTIVE"

    def test_the_reversed_line_drops_out_of_both_pattern_counters(self, client):
        """"Two redemption-pattern counters are restricted to the recent window running
        from the current logical instant back by redemption_window_minutes, with both ends
        of that window inclusive, and consider only unreversed redemptions"
        "An event counts as reversed precisely when some other event exists whose
        reverses_event_id points at it; there is no mutable flag on the parent event, and
        the question is always answered by looking for the child."

        Design: Corner/calculations/card_projection_rederives_every_counter_after_a_reversal
        """
        world = self._world(client)
        before = read_card(client, world["card_id"])
        assert_card_projection(before, distinct_merchant_count=2, recent_redemption_count=3)

        reverse(client, world["middle"]["id"], reversal_reason="merchant double-charged the shopper")

        after = read_card(client, world["card_id"])
        # The second store's only redemption is reversed, so it leaves the merchant set.
        assert_card_projection(after, distinct_merchant_count=1, recent_redemption_count=2)

    def test_the_original_row_is_untouched_and_the_compensating_row_points_back(self, client):
        """"A new REDEMPTION_REVERSAL event is appended, carrying the original's amount as
        a positive movement, with reverses_event_id pointing at the original, the supplied
        reason recorded as the new event's memo, and occurred_at at the logical now."
        "The original event is never mutated — history is append-only."

        Design: Corner/calculations/card_projection_rederives_every_counter_after_a_reversal
        """
        world = self._world(client)
        target = world["middle"]

        response = client.reverse_ledger_event(
            target["id"],
            reversal_payload(reversal_reason="merchant double-charged the shopper"),
            make_risk_manager_headers(),
        )

        reversal = validate_success(response, 201)
        assert reversal["type"] == "REDEMPTION_REVERSAL"
        assert reversal["amount_cents"] == 4000
        assert reversal["signed_amount_cents"] == 4000
        assert reversal["reverses_event_id"] == target["id"]
        assert_signed_amount(reversal)
        original = validate_success(
            client.get_ledger_event(target["id"], make_platform_admin_headers())
        )
        assert original["amount_cents"] == 4000
        assert original["signed_amount_cents"] == -4000
        assert_signed_amount(original)
        assert (
            total_count(
                client.list_ledger_events(
                    make_platform_admin_headers(), {"card_id": world["card_id"]}
                )
            )
            == 5
        )
        assert (
            total_count(
                client.list_ledger_events(
                    make_platform_admin_headers(), {"reverses_event_id": target["id"]}
                )
            )
            == 1
        )


class TestNetFundedLiabilityPopulation:
    """Three activation states, one funded population of two."""

    def _world(self, client):
        """An ACTIVE 8000 card, a DEPLETED card at zero, an INACTIVE card never screened,
        and a closed August period."""
        store = create_store(client, name="Liability Filter Store", region_code="SE")
        rack = create_rack(client, store["id"], rack_label="RACK-LF", expected_card_count=6)
        active = funded_physical_card(client, face_value_cents=8000, store=store, rack=rack)
        depleted = funded_physical_card(client, face_value_cents=3000, store=store, rack=rack)
        redeem(client, depleted["card"]["id"], 3000, store["id"], pos_terminal_id="T-57")
        inactive = stock_card(client, store["id"], rack["id"])
        period = open_period(client, label="2026-08 filter")
        closed = close_period(client, period["id"], close_note="month end with three card states")
        return {
            "store": store,
            "card_active": active["card"],
            "card_depleted": depleted["card"],
            "card_inactive": inactive,
            "period": closed,
        }

    def test_the_depleted_card_is_counted_while_the_inactive_card_is_excluded(self, client):
        """"It reports net_funded_liability_cents, computed live as the sum of
        current_balance_cents over cards whose activation_state is ACTIVE or DEPLETED,
        minus that period's unauthorized_writeoff_cents; funded_card_count, the number of
        cards in that same funded population; in_period_alert_count, the number of alerts
        created inside the period's half-open span in any state; and confirmed_alert_count,
        how many of those are CONFIRMED."
        "With no cards and no periods the summary reports 0; a voided replacement card
        contributes 0 because voided is outside the funded set; an inactive card
        contributes 0 despite carrying a face value, because it was never funded; and a
        depleted card contributes 0 to the sum yet is still counted as funded, since its
        balance is genuinely zero rather than excluded."

        Design: Corner/calculations/net_funded_liability_counts_only_active_and_depleted_cards
        """
        world = self._world(client)
        assert read_card(client, world["card_active"]["id"])["activation_state"] == "ACTIVE"
        depleted = read_card(client, world["card_depleted"]["id"])
        assert depleted["activation_state"] == "DEPLETED"
        assert depleted["current_balance_cents"] == 0
        inactive = read_card(client, world["card_inactive"]["id"])
        assert inactive["activation_state"] == "INACTIVE"
        assert inactive["current_balance_cents"] == 0

        summary = read_exposure_summary(client, world["period"]["id"])

        assert summary["net_funded_liability_cents"] == expected_net_funded_liability([8000, 0], 0)
        assert_exposure_summary(
            summary,
            net_funded_liability_cents=8000,
            funded_card_count=2,
            in_period_alert_count=0,
            confirmed_alert_count=0,
        )

    def test_the_summary_echoes_the_stored_reserve_fields_and_stores_nothing(self, client):
        """"Alongside these it echoes the period's stored unauthorized_writeoff_cents,
        outstanding_liability_cents, gross_exposure_cents, provisional_reserve_cents and
        final_reserve_cents. The read stores nothing and increments no version."
        "A period with no in-period alerts closes with a gross exposure of 0, a basis count
        of 0 and a reserve of 0 — zero, not empty, and certainly not an error."
        "Closing also refreshes outstanding_liability_cents, which is alert-independent:
        the sum of current_balance_cents over every gift card whose activation_state is
        ACTIVE or DEPLETED."

        Design: Corner/calculations/net_funded_liability_counts_only_active_and_depleted_cards
        """
        world = self._world(client)
        period = world["period"]
        assert period["state"] == "CLOSED"
        assert period["outstanding_liability_cents"] == 8000
        assert period["gross_exposure_cents"] == 0
        assert period["reserve_basis_alert_count"] == 0
        assert period["provisional_reserve_cents"] == expected_reserve(0, PROVISIONAL_RESERVE_RATE_BPS)

        summary = read_exposure_summary(client, period["id"])

        assert_exposure_summary(
            summary,
            unauthorized_writeoff_cents=0,
            outstanding_liability_cents=8000,
            gross_exposure_cents=0,
            provisional_reserve_cents=0,
        )
        after = read_period(client, period["id"])
        assert after["state"] == "CLOSED"
        assert_unchanged_version(period, after)


class TestListingCheckOrder:
    """Check 1 decides before check 3, so the two rejections carry different reasons."""

    def _world(self, client):
        """A DEPLETED 6000 card listed at a truthful 0, and an ACTIVE 6000 card listed
        1000 cents light."""
        store = create_store(client, name="Listing Order Store", region_code="NW")
        rack = create_rack(client, store["id"], rack_label="RACK-LO", expected_card_count=6)
        drained = funded_physical_card(client, face_value_cents=6000, store=store, rack=rack)
        redeem(client, drained["card"]["id"], 6000, store["id"], pos_terminal_id="T-58")
        live = funded_physical_card(client, face_value_cents=6000, store=store, rack=rack)
        partner = make_reseller_partner_headers("partner-58")
        listing_a = submit_listing(
            client,
            drained["card"]["id"],
            listed_balance_cents=0,
            headers=partner,
            asking_price_cents=100,
        )
        listing_b = submit_listing(
            client,
            live["card"]["id"],
            listed_balance_cents=5000,
            headers=partner,
            asking_price_cents=4500,
        )
        return {
            "card_depleted": drained["card"],
            "card_active": live["card"],
            "listing_a": listing_a,
            "listing_b": listing_b,
        }

    def test_a_depleted_card_listed_at_a_truthful_zero_still_rejects_on_check_one(self, client):
        """"If the card's funding state is anything other than ACTIVE, the listing becomes
        REJECTED with block_reason CARD_NOT_ACTIVE."
        "That is precisely why the ordering matters — a frozen card quoted at a stale
        balance reports CARD_RISK_POSTURE from check two, not BALANCE_MISMATCH from check
        three, and a DEPLETED card honestly listed at a zero balance still reports
        CARD_NOT_ACTIVE from check one."
        "Validation is exclusively a FraudAnalyst operation, is admitted only from
        SUBMITTED, accepts an optional validation_note, and records validated_by_user_id
        from the caller."

        Design: Corner/calculations/listing_validation_orders_card_state_ahead_of_balance_mismatch
        """
        world = self._world(client)
        card = read_card(client, world["card_depleted"]["id"])
        assert card["activation_state"] == "DEPLETED"
        assert card["current_balance_cents"] == 0
        assert world["listing_a"]["listed_balance_cents"] == card["current_balance_cents"]

        decided = validate_listing(
            client,
            world["listing_a"]["id"],
            headers=make_fraud_analyst_headers("analyst-58"),
            validation_note="depleted card at a truthful zero balance",
        )

        assert decided["state"] == "REJECTED"
        assert decided["block_reason"] == "CARD_NOT_ACTIVE"
        assert decided["validated_by_user_id"] == "analyst-58"
        assert read_card(client, world["card_depleted"]["id"])["risk_posture"] == "CLEAR"

    def test_an_active_card_listed_light_rejects_on_the_exact_balance_comparison(self, client):
        """"Otherwise, if the listing's listed_balance_cents is not exactly equal to the
        card's current_balance_cents, the listing becomes REJECTED with block_reason
        BALANCE_MISMATCH."
        "The balance comparison is exact with no tolerance whatsoever — a card whose
        balance moved by a single cent since the listing was drafted rejects."

        Design: Corner/calculations/listing_validation_orders_card_state_ahead_of_balance_mismatch
        """
        world = self._world(client)
        card = read_card(client, world["card_active"]["id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 6000

        decided = validate_listing(
            client,
            world["listing_b"]["id"],
            headers=make_fraud_analyst_headers("analyst-58"),
            validation_note="active card with a stale balance",
        )

        assert decided["state"] == "REJECTED"
        assert decided["block_reason"] == "BALANCE_MISMATCH"
        assert decided["listed_balance_cents"] == 5000
        assert decided["validated_by_user_id"] == "analyst-58"
        assert read_card(client, world["card_active"]["id"])["risk_posture"] == "CLEAR"


class TestDrainScoreListingBlock:
    """Check 4 is reachable only on a WATCH card whose score sits on the threshold."""

    def _scored_card(self, client, store, rack):
        """A 10000-cent card drawn down to 3000 at one merchant and probed four times,
        which raws to 12 * 4 + 30 * 0.70 + 5 * 1 == 74."""
        world = funded_physical_card(client, face_value_cents=10000, store=store, rack=rack)
        card_id = world["card"]["id"]
        redeem(client, card_id, 7000, store["id"], pos_terminal_id="T-59")
        partner = make_reseller_partner_headers("partner-59")
        last = None
        for index in range(4):
            last = inquire(
                client, card_id, channel="WEB", headers=partner, requester_ip_hash=f"iph-{index}"
            )
        return {"card_id": card_id, "last_inquiry": last}

    def test_a_score_one_below_the_threshold_leaves_the_card_watched_and_validates(self, client):
        """"Its raw figure is 12 points per inquiry in the current velocity count, plus 30
        multiplied by the card's drawdown_ratio, plus 5 points per entry in
        distinct_merchant_count."
        "A posture of CLEAR or WATCH passes check two, so a watched card with a matching
        balance and a sub-threshold inquiry score validates — WATCH is informational, not
        blocking."
        "The score comparison is inclusive: an inquiry score exactly equal to the restrict
        threshold blocks, one point below it validates."

        Design: Corner/calculations/listing_blocks_on_drain_score_only_after_a_manual_posture_override
        """
        policy = set_policy(client, drain_restrict_score_threshold=75)
        assert policy["drain_restrict_score_threshold"] == 75
        assert policy["drain_watch_score_threshold"] == DRAIN_WATCH_SCORE_THRESHOLD == 40
        assert policy["inquiry_velocity_threshold"] == 5
        store = create_store(client, name="Drain Score Store", region_code="SW")
        rack = create_rack(client, store["id"], rack_label="RACK-DS", expected_card_count=6)
        built = self._scored_card(client, store, rack)
        assert built["last_inquiry"]["velocity_count_at_inquiry"] == 4
        assert built["last_inquiry"]["drain_score_at_inquiry"] == 74
        card = read_card(client, built["card_id"])
        assert float(card["drawdown_ratio"]) == pytest.approx(0.70, abs=0.01)
        assert_card_projection(card, current_balance_cents=3000, distinct_merchant_count=1)
        assert card["drain_risk_score_inquiry"] == expected_inquiry_drain_score(4, 0.70, 1) == 74
        assert card["risk_posture"] == "WATCH"
        listing = submit_listing(
            client,
            built["card_id"],
            listed_balance_cents=3000,
            headers=make_reseller_partner_headers("partner-59"),
            asking_price_cents=2500,
        )

        decided = validate_listing(
            client,
            listing["id"],
            headers=make_fraud_analyst_headers("analyst-59"),
            validation_note="score 74 under a threshold of 75",
        )

        assert decided["state"] == "VALIDATED"
        assert_empty(decided["block_reason"], "block_reason")
        assert total_count(client.list_draining_alerts(make_platform_admin_headers())) == 0

    def test_the_same_score_blocks_once_the_threshold_drops_and_the_posture_is_walked_back(
        self, client
    ):
        """"Otherwise, if the card's drain_risk_score_inquiry is at or above
        drain_restrict_score_threshold, the listing becomes BLOCKED with block_reason
        DRAIN_SCORE."
        "The second is a manual override, which is the exclusive province of a RiskManager
        and the only unconstrained write to this dimension: the manager supplies the desired
        risk_posture — CLEAR, WATCH, RESTRICTED or FROZEN — together with a reason, and the
        card's posture is set to exactly that value, upward or downward, with the monotone
        escalation rule not applying."
        "An override leaves the funding state and every balance figure completely untouched,
        which is the plainest demonstration that the two dimensions are independent."

        Design: Corner/calculations/listing_blocks_on_drain_score_only_after_a_manual_posture_override
        """
        policy = set_policy(client, drain_restrict_score_threshold=74)
        assert policy["drain_restrict_score_threshold"] == 74
        store = create_store(client, name="Drain Score Store", region_code="SW")
        rack = create_rack(client, store["id"], rack_label="RACK-DS", expected_card_count=6)
        built = self._scored_card(client, store, rack)
        assert built["last_inquiry"]["velocity_count_at_inquiry"] == 4
        assert built["last_inquiry"]["drain_score_at_inquiry"] == 74
        before = read_card(client, built["card_id"])
        assert before["risk_posture"] == "RESTRICTED"
        assert before["drain_risk_score_inquiry"] == 74

        walked_back = override_posture(
            client,
            built["card_id"],
            "WATCH",
            reason="investigation cleared the shopper; keep watching",
        )

        assert walked_back["risk_posture"] == "WATCH"
        # The override lowers the posture and deliberately does not erase the score.
        assert walked_back["drain_risk_score_inquiry"] == 74
        assert_card_projection(walked_back, current_balance_cents=3000, distinct_merchant_count=1)
        assert walked_back["activation_state"] == "ACTIVE"
        listing = submit_listing(
            client,
            built["card_id"],
            listed_balance_cents=3000,
            headers=make_reseller_partner_headers("partner-59"),
            asking_price_cents=2500,
        )

        decided = validate_listing(
            client,
            listing["id"],
            headers=make_fraud_analyst_headers("analyst-59"),
            validation_note="score 74 at a threshold of 74",
        )

        assert decided["state"] == "BLOCKED"
        assert decided["block_reason"] == "DRAIN_SCORE"
        assert total_count(client.list_draining_alerts(make_platform_admin_headers())) == 0
