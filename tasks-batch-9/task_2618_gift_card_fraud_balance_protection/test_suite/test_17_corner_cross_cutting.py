"""Cross-cutting layers: the two stale-version guards, the logical clock's effect on a
sliding window, the confirmation cascade's ordered reach, and the version counter itself.

Every scenario here builds its own world from scratch, moves it with ordinary endpoints,
and then re-reads the affected records to check what did — and did not — change.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_INVALID_ALERT_STATE,
    ERR_STALE_CARD_VERSION,
    ERR_STALE_PERIOD_VERSION,
)
from test_helpers.factories import (
    period_restate_payload,
    redemption_hold_payload,
    reopen_payload,
)
from test_helpers.assertions import (
    assert_empty,
    assert_id_sequence,
    assert_unchanged_version,
    assert_version_bumped_by,
)
from test_helpers.fixtures import (
    advance_clock,
    close_period,
    create_rack,
    create_store,
    funded_physical_card,
    inquire,
    list_data_and_meta,
    open_alert,
    open_period,
    parse_instant,
    place_hold,
    read_alert,
    read_card,
    read_period,
    read_store,
    resolve_alert,
    restate_period,
    submit_listing,
    total_count,
    triage_alert,
    validate_listing,
    validated_listing,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_liability_accountant_headers,
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_risk_manager_headers,
)

HOLD_START = "2026-08-01T00:00:00Z"
HOLD_EXPIRES = "2026-08-01T06:00:00Z"


class TestHoldCreateStaleCardVersion:
    """"Placing a redemption hold on a gift card requires the request to carry
    expected_gift_card_version"."""

    def _card_with_ten_thousand(self, client):
        """A store, an INTACT rack and one ACTIVE PHYSICAL card funded at 10000 cents,
        carrying no holds and no redemptions."""
        store = create_store(client, name="OCC Card Store", region_code="NE", address_line="64 OCC Ave")
        rack = create_rack(client, store["id"], rack_label="RACK-OC", expected_card_count=5)
        world = funded_physical_card(client, 10000, store=store, rack=rack)
        return read_card(client, world["card"]["id"], make_risk_manager_headers("risk-94"))

    def test_replaying_the_pre_hold_card_version_is_refused_and_reserves_nothing(self, client):
        """"If that value does not equal the card's current version, the request is rejected
        with ERR_STALE_CARD_VERSION (HTTP 412)."
        "A gift card's version is bumped by every hold, every redemption, every reversal,
        every posture change and every cascade that touches it, so a client that has not
        re-read the card since any of those events will be turned away and must re-read and
        resubmit."
        "held_amount_cents is the sum of the amounts of the counted holds, and
        available_balance_cents is the current balance minus the held amount, floored at
        zero."

        Design: Corner/cross_cutting_complexity_layers/hold_create_with_stale_card_version_conflicts
        """
        card = self._card_with_ten_thousand(client)
        assert card["available_balance_cents"] == 10000
        version_before = card["version"]

        first = client.create_redemption_hold(
            card["id"],
            redemption_hold_payload(3000, HOLD_START, HOLD_EXPIRES, version_before),
            make_pos_associate_headers(),
        )
        accepted = validate_success(first, 201)
        assert accepted["state"] == "ACTIVE", accepted

        replay = client.create_redemption_hold(
            card["id"],
            redemption_hold_payload(2000, HOLD_START, HOLD_EXPIRES, version_before),
            make_pos_associate_headers(),
        )
        assert replay.status_code == 412, replay.text
        validate_error(replay, ERR_STALE_CARD_VERSION, 412)

        after = read_card(client, card["id"], make_risk_manager_headers("risk-94"))
        assert_version_bumped_by(card, after, 1)
        assert after["held_amount_cents"] == 3000, "the stale attempt reserved nothing"
        assert after["available_balance_cents"] == 7000
        assert after["current_balance_cents"] == 10000
        assert total_count(
            client.list_card_redemption_holds(card["id"], make_platform_admin_headers(), {"state": "ACTIVE"})
        ) == 1

    def test_the_same_amount_is_accepted_once_the_version_is_re_read(self, client):
        """"a client that has not re-read the card since any of those events will be turned
        away and must re-read and resubmit."
        "Overlapping holds on one card are perfectly legal; what is capped is their sum."
        "held_amount_cents is the sum of the amounts of the counted holds, and
        available_balance_cents is the current balance minus the held amount, floored at
        zero."

        Design: Corner/cross_cutting_complexity_layers/hold_create_with_stale_card_version_conflicts
        """
        card = self._card_with_ten_thousand(client)
        first = place_hold(client, card["id"], 3000, HOLD_START, HOLD_EXPIRES, card["version"])

        stale = client.create_redemption_hold(
            card["id"],
            redemption_hold_payload(2000, HOLD_START, HOLD_EXPIRES, card["version"]),
            make_pos_associate_headers(),
        )
        validate_error(stale, ERR_STALE_CARD_VERSION, 412)

        current = read_card(client, card["id"], make_risk_manager_headers("risk-94"))
        retried = client.create_redemption_hold(
            card["id"],
            redemption_hold_payload(2000, HOLD_START, HOLD_EXPIRES, current["version"]),
            make_pos_associate_headers(),
        )
        second = validate_success(retried, 201)
        assert second["state"] == "ACTIVE", second

        final = read_card(client, card["id"], make_risk_manager_headers("risk-94"))
        assert final["held_amount_cents"] == 5000
        assert final["available_balance_cents"] == 5000
        assert final["current_balance_cents"] == 10000, "a hold reserves value, it does not spend it"

        rows, meta = list_data_and_meta(
            client.list_card_redemption_holds(
                card["id"], make_platform_admin_headers(), {"state": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


class TestPeriodRestateStalePeriodVersion:
    """"Restatement is deliberately repeatable — a period may be restated any number of
    times — so no state precondition would catch a client working from a superseded view of
    the period's exposure basis"."""

    ACCOUNTANT = "acct-95"

    def _closed_period(self, client):
        """One accounting period over 2026-08-01..2026-09-01, created and then closed
        against an empty card and alert population.  Returns the creation body and the
        close body so both observed versions are available."""
        created = open_period(
            client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", label="2026-08 occ period"
        )
        closed = close_period(
            client,
            created["id"],
            headers=make_liability_accountant_headers(self.ACCOUNTANT),
            close_note="month closed",
        )
        return created, closed

    def test_restating_from_the_pre_close_view_is_refused_and_writes_nothing(self, client):
        """"Restating an accounting period requires the request to carry
        expected_liability_period_version, a non-optional field holding the version of the
        period the client last observed. If it does not equal the period's current version,
        the request is rejected with ERR_STALE_PERIOD_VERSION (HTTP 412)."
        "A period with no in-period alerts closes with a gross exposure of 0, a basis count
        of 0 and a reserve of 0 — zero, not empty, and certainly not an error."

        Design: Corner/cross_cutting_complexity_layers/period_restate_with_stale_period_version_conflicts
        """
        created, closed = self._closed_period(client)
        assert created["state"] == "OPEN"
        assert closed["state"] == "CLOSED"
        assert closed["provisional_reserve_cents"] == 0
        assert_version_bumped_by(created, closed, 1)

        response = client.restate_liability_period(
            created["id"],
            period_restate_payload(
                created["version"], restatement_note="restating from a pre-close view"
            ),
            make_liability_accountant_headers(self.ACCOUNTANT),
        )
        assert response.status_code == 412, response.text
        validate_error(response, ERR_STALE_PERIOD_VERSION, 412)

        after = read_period(client, created["id"])
        assert after["state"] == "CLOSED", "the refused restatement left the lifecycle alone"
        assert after["restatement_count"] == 0
        assert_unchanged_version(closed, after)

    def test_the_post_close_version_restates_the_period_once(self, client):
        """"It requires a restatement_note, stamps restated_at, and increments
        restatement_count by 1."
        "the basis narrows to in-period alerts whose state is exactly CONFIRMED, and
        final_reserve_cents is final_reserve_rate_bps applied to the recomputed
        gross_exposure_cents, rounded half-up once over the aggregate."
        "Every restatement increments version by 1, which means a client intending two
        restatements in a row must re-read the period between them."

        Design: Corner/cross_cutting_complexity_layers/period_restate_with_stale_period_version_conflicts
        """
        created, closed = self._closed_period(client)

        restated = restate_period(
            client,
            created["id"],
            closed["version"],
            headers=make_liability_accountant_headers(self.ACCOUNTANT),
            restatement_note="restating from the post-close view",
        )

        assert restated["state"] == "RESTATED"
        assert restated["restatement_count"] == 1
        assert restated["final_reserve_cents"] == 0
        assert_version_bumped_by(closed, restated, 1)
        assert restated["provisional_reserve_cents"] == 0, (
            "a restatement never overwrites the provisional figure"
        )

    def test_the_version_that_just_worked_is_superseded_for_the_next_restatement(self, client):
        """"Every restatement increments version by 1, which means a client intending two
        restatements in a row must re-read the period between them."
        "If it does not equal the period's current version, the request is rejected with
        ERR_STALE_PERIOD_VERSION (HTTP 412)."
        "Restating is the same role's operation, admitted from CLOSED and again from
        RESTATED as a self-loop, and it is the second place a stale-version guard applies:
        the supplied expected_liability_period_version must equal the period's current
        version or the restatement is refused with ERR_STALE_PERIOD_VERSION, as described in
        §2.7."

        Design: Corner/cross_cutting_complexity_layers/period_restate_with_stale_period_version_conflicts
        """
        created, closed = self._closed_period(client)
        accountant = make_liability_accountant_headers(self.ACCOUNTANT)
        first = restate_period(
            client,
            created["id"],
            closed["version"],
            headers=accountant,
            restatement_note="restating from the post-close view",
        )

        replay = client.restate_liability_period(
            created["id"],
            period_restate_payload(
                closed["version"], restatement_note="replaying the superseded view"
            ),
            accountant,
        )
        assert replay.status_code == 412, replay.text
        validate_error(replay, ERR_STALE_PERIOD_VERSION, 412)
        assert read_period(client, created["id"])["restatement_count"] == 1

        second = restate_period(
            client,
            created["id"],
            first["version"],
            headers=accountant,
            restatement_note="second restatement from the current view",
        )
        assert second["state"] == "RESTATED", "the self-loop is legal, the stale read was not"
        assert second["restatement_count"] == 2
        assert_version_bumped_by(first, second, 1)
        assert second["provisional_reserve_cents"] == 0


class TestInquiryVelocityWindowReset:
    """"Because advancing the logical clock ages older inquiries out of the window, the
    count can decrease between consecutive inquiries"."""

    def _clear_card(self, client):
        """A store, an INTACT rack and one ACTIVE PHYSICAL card funded at 10000 cents with
        no redemptions, so its drawdown_ratio is 0.00 and distinct_merchant_count is 0."""
        store = create_store(
            client, name="Window Reset Store", region_code="MW", address_line="65 Reset Rd"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-WR", expected_card_count=5)
        world = funded_physical_card(client, 10000, store=store, rack=rack)
        return world["card"]

    def test_four_inquiries_inside_one_window_count_themselves_and_score_twelve_each(self, client):
        """"Velocity is evaluated after the new row has been appended, so the triggering
        inquiry counts itself."
        "The number of that card's inquiries inside the window is stored on the new row as
        velocity_count_at_inquiry. The very first inquiry on a card therefore records a count
        of 1, never 0."
        "Its raw figure is 12 points per inquiry in the current velocity count, plus 30
        multiplied by the card's drawdown_ratio, plus 5 points per entry in
        distinct_merchant_count."
        "The inquiry is appended with occurred_at at the logical now and
        balance_disclosed_cents recording the card's current_balance_cents at that instant."

        Design: Corner/cross_cutting_complexity_layers/inquiry_velocity_window_resets_once_the_clock_slides_past_it
        """
        card = self._clear_card(client)

        first = inquire(client, card["id"], "IVR", requester_ip_hash="iph-96-1")
        second = inquire(client, card["id"], "IVR", requester_ip_hash="iph-96-2")
        third = inquire(client, card["id"], "WEB", requester_ip_hash="iph-96-3")
        fourth = inquire(client, card["id"], "WEB", requester_ip_hash="iph-96-4")

        assert first["velocity_count_at_inquiry"] == 1
        assert first["drain_score_at_inquiry"] == 12
        assert second["velocity_count_at_inquiry"] == 2
        assert second["drain_score_at_inquiry"] == 24
        assert third["velocity_count_at_inquiry"] == 3
        assert third["drain_score_at_inquiry"] == 36
        assert fourth["velocity_count_at_inquiry"] == 4
        assert fourth["drain_score_at_inquiry"] == 48
        assert fourth["balance_disclosed_cents"] == 10000

    def test_a_count_one_below_the_threshold_watches_the_card_without_alerting(self, client):
        """"A breach occurs when that count is at or above inquiry_velocity_threshold — at
        exactly the threshold, never one below it."
        "inquiry_velocity_threshold — the inquiry count inside that trailing window at or
        above which a draining alert fires. Default 5."
        "The inquiry-weighted score is recomputed on every balance inquiry, written to the
        card's drain_risk_score_inquiry and copied onto the inquiry row as
        drain_score_at_inquiry."
        "Otherwise, if the score is at or above drain_watch_score_threshold, the target is
        WATCH."

        Design: Corner/cross_cutting_complexity_layers/inquiry_velocity_window_resets_once_the_clock_slides_past_it
        """
        card = self._clear_card(client)
        for index, channel in enumerate(("IVR", "IVR", "WEB", "WEB"), start=1):
            inquire(client, card["id"], channel, requester_ip_hash=f"iph-96-{index}")

        after = read_card(client, card["id"], make_risk_manager_headers("risk-96"))
        assert after["drain_risk_score_inquiry"] == 48
        assert after["risk_posture"] == "WATCH", "48 crosses 40 but not 70"
        assert total_count(
            client.list_draining_alerts(make_platform_admin_headers(), {"card_id": card["id"]})
        ) == 0

    def test_sliding_the_clock_past_the_window_resets_the_count_without_de_escalating(self, client):
        """"The window runs from the current logical instant back by
        inquiry_velocity_window_minutes, with both ends inclusive, so an inquiry sitting
        exactly on the window's opening edge is inside it."
        "Because advancing the logical clock ages older inquiries out of the window, the
        count can decrease between consecutive inquiries, and a later inquiry may fail to
        breach even though an earlier one did."
        "The card's risk_posture is then set to that target only when the target sits
        strictly higher on the ladder than the card's current rung. Scoring therefore never
        lowers a posture"
        "A PlatformAdmin moves the clock by supplying a to_iso8601 instant; the response
        reports the new setting as current_utc and the number of holds the move expired as
        expired_hold_count."

        Design: Corner/cross_cutting_complexity_layers/inquiry_velocity_window_resets_once_the_clock_slides_past_it
        """
        card = self._clear_card(client)
        for index, channel in enumerate(("IVR", "IVR", "WEB", "WEB"), start=1):
            inquire(client, card["id"], channel, requester_ip_hash=f"iph-96-{index}")
        assert read_card(client, card["id"])["risk_posture"] == "WATCH"

        moved = advance_clock(client, "2026-08-01T02:00:00Z")
        assert parse_instant(moved["current_utc"]) == parse_instant("2026-08-01T02:00:00Z")
        assert moved["expired_hold_count"] == 0

        fifth = inquire(client, card["id"], "MOBILE", requester_ip_hash="iph-96-5")
        assert fifth["velocity_count_at_inquiry"] == 1, "the window holds only the fifth inquiry"
        assert fifth["drain_score_at_inquiry"] == 12

        after = read_card(client, card["id"], make_risk_manager_headers("risk-96"))
        assert after["drain_risk_score_inquiry"] == 12, "the stored score follows the reset downward"
        assert after["risk_posture"] == "WATCH", "the recomputed target CLEAR is not an escalation"
        assert total_count(
            client.list_draining_alerts(make_platform_admin_headers(), {"card_id": card["id"]})
        ) == 0
        assert total_count(
            client.list_balance_inquiries(card["id"], make_platform_admin_headers())
        ) == 5


class TestConfirmCascadeBlocksValidatedListings:
    """"Hop three follows from the card being frozen: every reseller listing on that card in
    state VALIDATED transitions to BLOCKED"."""

    TRIAGER = "analyst-97"
    RESOLVER = "risk-97"

    def _card_with_three_listings_and_a_triaged_alert(self, client):
        """One ACTIVE PHYSICAL card at 5000 cents carrying two VALIDATED listings created in
        order plus one already-REJECTED listing, and one alert triaged on it."""
        store = create_store(
            client, name="Cascade Order Listings Store", region_code="SE", address_line="66 Cascade Ct"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-CO", expected_card_count=5)
        card = funded_physical_card(client, 5000, store=store, rack=rack)["card"]

        listing_a = validated_listing(client, card["id"], 5000, "GiftBay")
        listing_b = validated_listing(client, card["id"], 5000, "CardVault")
        submitted_c = submit_listing(client, card["id"], 4000, "SwapDeck", asking_price_cents=3900)
        listing_c = validate_listing(client, submitted_c["id"], validation_note="C mismatched")

        alert = open_alert(
            client,
            card["id"],
            "RESELLER_SIGNAL",
            headers=make_fraud_analyst_headers(self.TRIAGER),
            note="listings appeared on three marketplaces",
        )
        alert = triage_alert(
            client,
            alert["id"],
            headers=make_fraud_analyst_headers(self.TRIAGER),
            triage_note="confirmed with the partner",
            redemption_pattern_reviewed=True,
        )
        return {
            "store": store,
            "card": card,
            "listing_a": listing_a,
            "listing_b": listing_b,
            "listing_c": listing_c,
            "alert": alert,
        }

    def test_confirming_freezes_the_card_and_blocks_both_validated_listings_in_order(self, client):
        """"Hop one moves the alert TRIAGED → CONFIRMED and records the resolution. Hop two
        follows from the alert being confirmed: the card's risk_posture is forced to FROZEN,
        from whatever rung it was on — CLEAR → FROZEN, WATCH → FROZEN or RESTRICTED → FROZEN.
        Hop three follows from the card being frozen: every reseller listing on that card in
        state VALIDATED transitions to BLOCKED with a block_reason of CARD_RISK_POSTURE,
        processed in created_at ascending order, and each such listing's version increments."
        "Unless a specific endpoint states otherwise, list results are ordered by created_at
        ascending."

        Design: Corner/cross_cutting_complexity_layers/confirm_cascade_blocks_validated_listings_in_creation_order
        """
        world = self._card_with_three_listings_and_a_triaged_alert(client)
        assert world["listing_a"]["state"] == "VALIDATED"
        assert world["listing_b"]["state"] == "VALIDATED"
        assert world["alert"]["state"] == "TRIAGED"

        resolved = resolve_alert(
            client,
            world["alert"]["id"],
            "CONFIRM",
            headers=make_risk_manager_headers(self.RESOLVER),
            resolution_note="card is compromised",
        )
        assert resolved["state"] == "CONFIRMED"
        assert resolved["resolution"] == "CONFIRM"

        card = read_card(client, world["card"]["id"], make_risk_manager_headers(self.RESOLVER))
        assert card["risk_posture"] == "FROZEN"

        for listing in (world["listing_a"], world["listing_b"]):
            blocked = validate_success(
                client.get_reseller_listing(listing["id"], make_platform_admin_headers())
            )
            assert blocked["state"] == "BLOCKED", listing["marketplace_name"]
            assert blocked["block_reason"] == "CARD_RISK_POSTURE", listing["marketplace_name"]
            assert_version_bumped_by(listing, blocked, 1)

        rows, _ = list_data_and_meta(
            client.list_card_reseller_listings(world["card"]["id"], make_platform_admin_headers())
        )
        assert_id_sequence(
            rows, [world["listing_a"]["id"], world["listing_b"]["id"], world["listing_c"]["id"]]
        )

    def test_a_listing_that_is_not_validated_is_left_entirely_alone(self, client):
        """"Otherwise, if the listing's listed_balance_cents is not exactly equal to the
        card's current_balance_cents, the listing becomes REJECTED with block_reason
        BALANCE_MISMATCH."
        "every reseller listing on that card in state VALIDATED transitions to BLOCKED with a
        block_reason of CARD_RISK_POSTURE"
        "version, an integer that starts at 1 on creation and increases by exactly 1 on every
        mutation — including mutations that arrive as a cascaded side effect of an operation
        on a different resource."

        Design: Corner/cross_cutting_complexity_layers/confirm_cascade_blocks_validated_listings_in_creation_order
        """
        world = self._card_with_three_listings_and_a_triaged_alert(client)
        assert world["listing_c"]["state"] == "REJECTED"
        assert world["listing_c"]["block_reason"] == "BALANCE_MISMATCH"

        resolve_alert(
            client,
            world["alert"]["id"],
            "CONFIRM",
            headers=make_risk_manager_headers(self.RESOLVER),
            resolution_note="card is compromised",
        )

        after = validate_success(
            client.get_reseller_listing(world["listing_c"]["id"], make_platform_admin_headers())
        )
        assert after["state"] == "REJECTED"
        assert after["block_reason"] == "BALANCE_MISMATCH"
        assert_unchanged_version(world["listing_c"], after)

    def test_the_freeze_touches_only_the_posture_and_the_floor_relaxes(self, client):
        """"risk and funding are independent axes: a card's funding lifecycle and its fraud
        posture evolve on separate dimensions of the same record, so a fully funded card can
        be frozen and a depleted card can still be under investigation."
        "counts into open_alert_count every draining alert in state OPEN or TRIAGED whose
        card belongs to this store."
        "Note that both CONFIRMED and DISMISSED alerts stop counting toward open_alert_count,
        so confirming the last live alert can relax the floor even though the fraud turned out
        to be real"

        Design: Corner/cross_cutting_complexity_layers/confirm_cascade_blocks_validated_listings_in_creation_order
        """
        world = self._card_with_three_listings_and_a_triaged_alert(client)
        assert world["alert"]["basis_drain_score"] == 0, "no redemptions exist on the card"

        resolve_alert(
            client,
            world["alert"]["id"],
            "CONFIRM",
            headers=make_risk_manager_headers(self.RESOLVER),
            resolution_note="card is compromised",
        )

        card = read_card(client, world["card"]["id"])
        assert card["activation_state"] == "ACTIVE"
        assert card["current_balance_cents"] == 5000
        assert card["risk_posture"] == "FROZEN"

        store = read_store(client, world["store"]["id"])
        assert store["open_alert_count"] == 0, "a CONFIRMED alert is no longer open"
        assert store["floor_posture"] == "OPEN"


class TestVersionCounterTracksAcceptedWritesOnly:
    """"version, an integer that starts at 1 on creation and increases by exactly 1 on every
    mutation"."""

    TRIAGER = "analyst-98"
    RESOLVER = "risk-98"

    def _open_alert_on_a_funded_card(self, client):
        """One ACTIVE PHYSICAL card at 5000 cents carrying one manually raised alert."""
        store = create_store(
            client, name="Version Counter Store", region_code="NW", address_line="67 Version Way"
        )
        rack = create_rack(client, store["id"], rack_label="RACK-VC", expected_card_count=5)
        card = funded_physical_card(client, 5000, store=store, rack=rack)["card"]
        alert = open_alert(
            client,
            card["id"],
            "MANUAL_REVIEW",
            headers=make_fraud_analyst_headers(self.TRIAGER),
            note="version counter probe",
        )
        return card, alert

    def test_two_consecutive_reads_leave_the_version_where_it_was(self, client):
        """"version, an integer that starts at 1 on creation and increases by exactly 1 on
        every mutation — including mutations that arrive as a cascaded side effect of an
        operation on a different resource."
        "A manually raised alert starts in OPEN with basis_velocity_count and
        basis_drain_score both at 0."

        Design: Corner/cross_cutting_complexity_layers/version_increments_by_one_on_every_accepted_write_and_never_on_reads
        """
        _card, alert = self._open_alert_on_a_funded_card(client)
        assert alert["state"] == "OPEN"

        first_read = read_alert(client, alert["id"], make_fraud_analyst_headers(self.TRIAGER))
        second_read = read_alert(client, alert["id"], make_risk_manager_headers(self.RESOLVER))

        assert_unchanged_version(alert, first_read)
        assert_unchanged_version(alert, second_read)
        assert first_read["state"] == "OPEN"
        assert second_read["state"] == "OPEN"

    def test_each_accepted_transition_advances_the_version_by_exactly_one(self, client):
        """"The alert moves OPEN → TRIAGED, triaged_by_user_id is recorded from the caller's
        X-User-ID"
        "Either resolution records resolved_by_user_id from the caller and the supplied note,
        recomputes the store's open_alert_count and floor_posture, and increments the alert's,
        the card's and the store's version."
        "The alert returns DISMISSED → OPEN, its resolution, resolved_by_user_id and
        resolution_note are all cleared back to empty, and reopen_count increments by 1."

        Design: Corner/cross_cutting_complexity_layers/version_increments_by_one_on_every_accepted_write_and_never_on_reads
        """
        _card, alert = self._open_alert_on_a_funded_card(client)

        triaged = triage_alert(
            client,
            alert["id"],
            headers=make_fraud_analyst_headers(self.TRIAGER),
            triage_note="probe triage",
            redemption_pattern_reviewed=False,
        )
        dismissed = resolve_alert(
            client,
            alert["id"],
            "DISMISS",
            headers=make_risk_manager_headers(self.RESOLVER),
            resolution_note="probe dismiss",
        )
        reopened = validate_success(
            client.reopen_draining_alert(
                alert["id"],
                reopen_payload(reopen_reason="new evidence"),
                make_risk_manager_headers(self.RESOLVER),
            )
        )

        assert triaged["state"] == "TRIAGED"
        assert dismissed["state"] == "DISMISSED"
        assert reopened["state"] == "OPEN"
        assert_version_bumped_by(alert, triaged, 1)
        assert_version_bumped_by(triaged, dismissed, 1)
        assert_version_bumped_by(dismissed, reopened, 1)
        assert reopened["reopen_count"] == 1

    def test_a_reopen_refused_on_an_open_alert_bumps_neither_counter(self, client):
        """"a draining alert must be OPEN to be triaged, TRIAGED to be resolved and DISMISSED
        to be reopened, otherwise ERR_INVALID_ALERT_STATE"
        "version, an integer that starts at 1 on creation and increases by exactly 1 on every
        mutation"
        "The alert returns DISMISSED → OPEN, its resolution, resolved_by_user_id and
        resolution_note are all cleared back to empty, and reopen_count increments by 1."

        Design: Corner/cross_cutting_complexity_layers/version_increments_by_one_on_every_accepted_write_and_never_on_reads
        """
        _card, alert = self._open_alert_on_a_funded_card(client)
        triage_alert(
            client,
            alert["id"],
            headers=make_fraud_analyst_headers(self.TRIAGER),
            triage_note="probe triage",
            redemption_pattern_reviewed=False,
        )
        resolve_alert(
            client,
            alert["id"],
            "DISMISS",
            headers=make_risk_manager_headers(self.RESOLVER),
            resolution_note="probe dismiss",
        )
        reopened = validate_success(
            client.reopen_draining_alert(
                alert["id"],
                reopen_payload(reopen_reason="new evidence"),
                make_risk_manager_headers(self.RESOLVER),
            )
        )
        assert reopened["state"] == "OPEN"
        assert reopened["reopen_count"] == 1

        replay = client.reopen_draining_alert(
            alert["id"],
            reopen_payload(reopen_reason="reopening an already open alert"),
            make_risk_manager_headers(self.RESOLVER),
        )
        assert replay.status_code == 409, replay.text
        validate_error(replay, ERR_INVALID_ALERT_STATE, 409)

        after = read_alert(client, alert["id"], make_risk_manager_headers(self.RESOLVER))
        assert after["state"] == "OPEN"
        assert_unchanged_version(reopened, after)
        assert after["reopen_count"] == reopened["reopen_count"]

    def test_reopen_clears_the_resolution_but_preserves_the_triager(self, client):
        """"Crucially, triaged_by_user_id is preserved across the reopen, so segregation of
        duties still binds the same original triager on the next resolution attempt."
        "The alert returns DISMISSED → OPEN, its resolution, resolved_by_user_id and
        resolution_note are all cleared back to empty, and reopen_count increments by 1."

        Design: Corner/cross_cutting_complexity_layers/version_increments_by_one_on_every_accepted_write_and_never_on_reads
        """
        _card, alert = self._open_alert_on_a_funded_card(client)
        triage_alert(
            client,
            alert["id"],
            headers=make_fraud_analyst_headers(self.TRIAGER),
            triage_note="probe triage",
            redemption_pattern_reviewed=False,
        )
        resolve_alert(
            client,
            alert["id"],
            "DISMISS",
            headers=make_risk_manager_headers(self.RESOLVER),
            resolution_note="probe dismiss",
        )
        validate_success(
            client.reopen_draining_alert(
                alert["id"],
                reopen_payload(reopen_reason="new evidence"),
                make_risk_manager_headers(self.RESOLVER),
            )
        )

        after = read_alert(client, alert["id"], make_risk_manager_headers(self.RESOLVER))
        assert after["triaged_by_user_id"] == self.TRIAGER
        assert_empty(after["resolution"], "resolution")
        assert_empty(after["resolved_by_user_id"], "resolved_by_user_id")
        assert_empty(after["resolution_note"], "resolution_note")
