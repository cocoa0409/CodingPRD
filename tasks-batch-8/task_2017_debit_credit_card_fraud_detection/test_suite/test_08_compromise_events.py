"""Compromised-card events: intake uniqueness, depth-4 confirm cascade, exposure
threshold on decline."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    create_active_ruleset,
    create_compromised_event_payload,
    parse_iso8601,
    post_txn,
    set_clock,
    get_success_data,
    get_decision_for_card,
    create_manual_alert,
    make_analyst_headers,
    make_manager_headers,
)

MANAGER = TEST_USERS["manager_headers"]


def test_duplicate_event_reference_rejected(api):
    """PRD §3.6: "a network-supplied `event_reference` (globally unique — a
    duplicate intake is rejected with `ERR_DUPLICATE_EVENT`)".

    Design: Corner/validations/duplicate_event_reference_rejected
    """
    payload = create_compromised_event_payload(
        network_source="CAMS",
        event_reference="CAMS-DUP1",
        merchant_id="M-DUP",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )
    get_success_data(api.create_compromised_card_event(payload, MANAGER), expected_status=201)
    dup = api.create_compromised_card_event(payload, MANAGER)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_EVENT, expected_status=409)

    other = create_compromised_event_payload(
        network_source="ADC",
        event_reference="ADC-DUP2",
        merchant_id="M-DUP",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-03T00:00:00Z",
    )
    created = validate_success(api.create_compromised_card_event(other, MANAGER), expected_status=201)
    assert created["event_status"] == "RECEIVED"


class TestCompromisedEventConfirmDepth4Cascade:
    def _setup_cascade(self, api):
        """Three accounts; C1/C2 have in-window txns at M-777, C3's is outside;
        A1 has a pre-existing open manual alert (priority 25)."""
        set_clock("2026-08-01T00:00:00Z")
        a1 = create_account("ACCT-TC1", cardholder_name="A One")
        a2 = create_account("ACCT-TC2", cardholder_name="A Two")
        a3 = create_account("ACCT-TC3", cardholder_name="A Three")
        c1 = create_card(a1["id"], "PT-TC1", product_type="CREDIT", network="VISA")
        c2 = create_card(a2["id"], "PT-TC2", product_type="DEBIT", network="MASTERCARD")
        c3 = create_card(a3["id"], "PT-TC3", product_type="CREDIT", network="VISA")
        create_active_ruleset()
        set_clock("2026-08-02T00:00:00Z")
        post_txn(c1["id"], 40000, "M-777", channel="CNP", origin_country="US", mcc="5942")
        post_txn(c2["id"], 30000, "M-777", channel="CHIP", origin_country="US", mcc="5942")
        set_clock("2026-08-10T00:00:00Z")
        post_txn(c3["id"], 20000, "M-777", channel="CHIP", origin_country="US", mcc="5942")
        event = get_success_data(
            api.create_compromised_card_event(
                {
                    "network_source": "CAMS",
                    "event_reference": "CAMS-9001",
                    "merchant_id": "M-777",
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-03T00:00:00Z",
                },
                MANAGER,
            ),
            expected_status=201,
        )
        # Return the clock to the intended confirmation instant. The manual alert
        # is created only now: had it been created at 08-01, the 08-10 excursion
        # above would already have tripped its 72h SLA (§2.5 applies lazy expiry
        # on every clock advance) and EXPIRED is terminal.
        set_clock("2026-08-02T12:00:00Z")
        m1 = create_manual_alert(a1["id"], c1["id"])
        return (a1, a2, a3), (c1, c2, c3), m1, event

    def test_confirm_flags_in_window_cards_and_spawns_decisions(self, api):
        """PRD §3.6: "every card with at least one transaction at the event's
        `merchant_id` whose `scored_at` falls inside the half-open window —
        transactions with any decision, `APPROVE`, `REVIEW`, or `DECLINE`, all
        count as exposure — has its `fraud_flag` set from `CLEAN` or `WATCH` to
        `COMPROMISED`, and `affected_card_count` records how many distinct cards
        matched. Second, each newly compromised card spawns a `ReissueDecision` in
        `PENDING` with `due_at` set to `confirmed_at` plus 5 days and
        `exposure_cents` computed as the sum of `amount_cents` over that card's
        matching transactions at the event merchant inside the window".

        Design: Difficulty/transitive_cascade/compromised_event_confirm_depth4_cascade
        """
        (_a1, _a2, _a3), (c1, c2, c3), _m1, event = self._setup_cascade(api)
        confirmed = validate_success(api.confirm_compromised_card_event(event["id"], MANAGER))
        assert confirmed["affected_card_count"] == 2

        card1 = validate_success(api.get_card(c1["id"], MANAGER))
        card2 = validate_success(api.get_card(c2["id"], MANAGER))
        card3 = validate_success(api.get_card(c3["id"], MANAGER))
        assert card1["fraud_flag"] == "COMPROMISED"
        assert card2["fraud_flag"] == "COMPROMISED"
        assert card3["fraud_flag"] == "CLEAN", "out-of-window transaction must not expose the card"

        decision = get_decision_for_card(c1["id"])
        assert decision["decision"] == "PENDING"
        assert decision["exposure_cents"] == 40000
        # PRD pins the due_at *value* ("confirmed_at plus 5 days"); the
        # fractional-digit format of computed timestamps is not pinned (§2.4
        # scopes "three fractional digits" to created_at/updated_at), so compare
        # instants.
        assert parse_iso8601(decision["due_at"]) == parse_iso8601("2026-08-07T12:00:00Z"), (
            f"due_at must be confirmed_at + 5 days, got {decision['due_at']}"
        )

    def test_confirm_escalates_open_alerts_of_high_tier_accounts(self, api):
        """PRD §3.6: "Third, every owning account's `risk_tier` is recomputed (any
        `COMPROMISED` card forces `HIGH`). Fourth, every account whose tier rose to
        `HIGH` escalates its open alerts' priorities per §3.4."; §3.4: "each of
        that account's open alerts has its `priority` raised to the maximum of its
        current value and 200 plus its own `band_points`."

        Design: Difficulty/transitive_cascade/compromised_event_confirm_depth4_cascade
        """
        (a1, _a2, _a3), (c1, _c2, _c3), m1, event = self._setup_cascade(api)
        before = validate_success(api.get_fraud_alert(m1["id"], MANAGER))
        assert before["priority"] == 25
        validate_success(api.confirm_compromised_card_event(event["id"], MANAGER))
        account = validate_success(api.get_account(a1["id"], MANAGER))
        assert account["risk_tier"] == "HIGH"
        after = validate_success(api.get_fraud_alert(m1["id"], MANAGER))
        assert after["priority"] == 225, (
            f"escalation max(25, 200+25) expected 225, got {after['priority']}"
        )


class TestHighExposureReissueDeclineRequiresManager:
    def _setup_high_exposure(self, api):
        set_clock("2026-08-02T00:00:00Z")
        acct = create_account("ACCT-V9", cardholder_name="Val Nine")
        card = create_card(acct["id"], "PT-V9", product_type="DEBIT", network="MASTERCARD")
        create_active_ruleset()
        post_txn(card["id"], 60000, "M-V9", channel="CNP", origin_country="US")
        event = get_success_data(
            api.create_compromised_card_event(
                {
                    "network_source": "ADC",
                    "event_reference": "ADC-V9",
                    "merchant_id": "M-V9",
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-03T00:00:00Z",
                },
                MANAGER,
            ),
            expected_status=201,
        )
        get_success_data(api.confirm_compromised_card_event(event["id"], MANAGER))
        decision = get_decision_for_card(card["id"])
        return acct, card, decision

    def test_analyst_decline_over_threshold_rejected(self, api):
        """PRD §3.6: "when `exposure_cents` exceeds 50000 cents the decline is
        restricted to a `FraudOpsManager` — an analyst attempting it is rejected
        with `ERR_DECISION_EXPOSURE_REQUIRES_MANAGER` (HTTP 403)".

        Design: Corner/validations/high_exposure_reissue_decline_requires_manager
        """
        _acct, _card, decision = self._setup_high_exposure(api)
        assert decision["exposure_cents"] == 60000
        resp = api.decide_reissue_decision(
            decision["id"],
            {"decision": "DECLINE", "rationale": "risk accepted"},
            make_analyst_headers("analyst-1"),
        )
        validate_error(resp, ApiErrorId.ERR_DECISION_EXPOSURE_REQUIRES_MANAGER, expected_status=403)
        current = validate_success(api.get_reissue_decision(decision["id"], MANAGER))
        assert current["decision"] == "PENDING"

    def test_manager_decline_over_threshold_succeeds(self, api):
        """PRD §3.6: "when `exposure_cents` exceeds 50000 cents the decline is
        restricted to a `FraudOpsManager`"; "a decline downgrades the card's
        `fraud_flag` from `COMPROMISED` to `WATCH`".

        Design: Corner/validations/high_exposure_reissue_decline_requires_manager
        """
        _acct, card, decision = self._setup_high_exposure(api)
        decided = validate_success(
            api.decide_reissue_decision(
                decision["id"],
                {"decision": "DECLINE", "rationale": "risk accepted"},
                make_manager_headers("mgr-1"),
            )
        )
        assert decided["decision"] == "DECLINED"
        flagged = validate_success(api.get_card(card["id"], MANAGER))
        assert flagged["fraud_flag"] == "WATCH"


def _event_id(api, event_reference):
    """Look up an event's id by its unique event_reference."""
    from test_helpers import validate_paginated
    data, _meta = validate_paginated(api.list_compromised_card_events(MANAGER))
    matches = [e for e in data if e["event_reference"] == event_reference]
    assert len(matches) == 1, f"expected exactly one event {event_reference}, got {len(matches)}"
    return matches[0]["id"]
