"""Gift-subscription entitlements and the multi-entity cancellation cascade."""
from test_helpers import (
    api_client,
    validate_success,
    ApiErrorId,
    TEST_USERS,
    assert_digital_entitlement,
    get_first_term,
    list_term_revenue_entries,
    setup_gift_subscription_with_entitlement,
    CM,
)

CM_H = TEST_USERS["circulation_manager_headers"]


class TestCancelCascade:
    def test_cancel_expires_pending_renewal_events(self, api):
        """Cancelling the gift subscription moves it to CANCELLED and expires
        its PENDING renewal event.

        PRD §3.6: "Cancellation also expires every `PENDING` renewal event on the subscription, revokes all of its DigitalEntitlements with `revocation_reason` `REFUND`, and recomputes the subscriber's `circulation_class` — a subscriber left with no other active subscriptions falls back to `NON_QUALIFIED`."
        PRD §3.6: "Cancellation, by contrast, is a `CirculationManager` action on an `ACTIVE` subscription that moves it to the terminal `CANCELLED` state and unwinds the money."

        Design: Difficulty/transitive_cascade/subscription_cancel_cascades_depth2
        """
        ctx = setup_gift_subscription_with_entitlement()
        pub_id = ctx["publication"]["id"]
        gift = ctx["gift_subscription"]
        event = ctx["renewal_event"]
        assert gift["status"] == "ACTIVE" and event["response"] == "PENDING"

        cancelled = validate_success(api.cancel_subscription(pub_id, gift["id"], CM_H))
        assert cancelled["status"] == "CANCELLED"

        current_event = validate_success(
            api.get_renewal_event(pub_id, gift["id"], event["id"], CM_H)
        )
        assert current_event["response"] == "EXPIRED", (
            f"pending renewal event must expire on cancellation, got {current_event['response']}"
        )

    def test_cancel_revokes_digital_entitlements_with_refund_reason(self, api):
        """The gift subscription's mailing-time entitlement is active before
        cancellation and stamped revoked with reason REFUND after it.

        PRD §3.5: "For every served subscription with `is_gift` true, mailing additionally creates a **DigitalEntitlement** for the recipient with `access_level` `FULL` and `granted_at` set at that moment; `revoked_at` and `revocation_reason` stay unset while the entitlement is active."
        PRD §3.6: "Cancellation also expires every `PENDING` renewal event on the subscription, revokes all of its DigitalEntitlements with `revocation_reason` `REFUND`, and recomputes the subscriber's `circulation_class` — a subscriber left with no other active subscriptions falls back to `NON_QUALIFIED`."

        Design: Difficulty/transitive_cascade/subscription_cancel_cascades_depth2
        """
        ctx = setup_gift_subscription_with_entitlement()
        pub_id = ctx["publication"]["id"]
        gift = ctx["gift_subscription"]

        before = validate_success(api.list_digital_entitlements(pub_id, gift["id"], CM_H))
        assert len(before) == 1, f"gift subscription served at mailing holds one entitlement, got {len(before)}"
        entitlement = before[0]
        assert_digital_entitlement(entitlement)
        assert entitlement["access_level"] == "FULL"
        assert entitlement.get("revoked_at") is None
        assert entitlement.get("revocation_reason") is None

        validate_success(api.cancel_subscription(pub_id, gift["id"], CM_H))

        after = validate_success(api.list_digital_entitlements(pub_id, gift["id"], CM_H))
        assert len(after) == 1
        revoked = after[0]
        assert revoked["id"] == entitlement["id"]
        assert revoked.get("revoked_at") is not None, "revoked_at must be stamped on cancellation"
        assert revoked.get("revocation_reason") == "REFUND", (
            f"revocation_reason must be REFUND, got {revoked.get('revocation_reason')}"
        )


class TestCancelMultiEntityCascade:
    def test_cancel_posts_refund_liquidation_and_marks_term(self, api):
        """Cancellation after one served issue unwinds the money across every
        affected resource: subscription CANCELLED, renewal event EXPIRED, the
        term PARTIALLY_REFUNDED with its liability zeroed by a
        REFUND_LIQUIDATION entry for the negative of the remaining deferred
        balance, and the unrefunded remainder recognized.

        PRD §3.6: "The refund is computed from the cancelled term's remaining `deferred_balance_cents`: when no issues have been served, the entire balance is refunded; when one, two, or three issues have been served, ninety percent of the balance; when more than three have been served, fifty percent. The refunded amount is the balance multiplied by the applicable rate, rounded down to whole cents. The unrefunded remainder is recognized immediately as a `RECOGNITION` entry, and a second entry of type `REFUND_LIQUIDATION` for the negative of the entire remaining deferred balance zeroes out the liability. The term is then marked `REFUNDED` when the full balance was refunded, or `PARTIALLY_REFUNDED` otherwise."
        PRD §3.6: "Cancellation also expires every `PENDING` renewal event on the subscription, revokes all of its DigitalEntitlements with `revocation_reason` `REFUND`, and recomputes the subscriber's `circulation_class` — a subscriber left with no other active subscriptions falls back to `NON_QUALIFIED`."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_subscription_cancel_multi_entity
        """
        ctx = setup_gift_subscription_with_entitlement(gift_price_paid_cents=1200)
        pub_id = ctx["publication"]["id"]
        gift = ctx["gift_subscription"]
        event = ctx["renewal_event"]
        term_before = get_first_term(pub_id, gift["id"])
        # One issue was mailed: 100 recognized of the 1200 gross, 1100 deferred.
        assert term_before["recognized_balance_cents"] == 100
        assert term_before["deferred_balance_cents"] == 1100

        cancelled = validate_success(api.cancel_subscription(pub_id, gift["id"], CM_H))
        assert cancelled["status"] == "CANCELLED"

        current_event = validate_success(
            api.get_renewal_event(pub_id, gift["id"], event["id"], CM_H)
        )
        assert current_event["response"] == "EXPIRED"

        term = get_first_term(pub_id, gift["id"])
        assert term["status"] == "PARTIALLY_REFUNDED", (
            f"one issue served -> ninety percent refund -> PARTIALLY_REFUNDED, got {term['status']}"
        )
        assert term["deferred_balance_cents"] == 0

        entries = list_term_revenue_entries(pub_id, gift["id"], term_before["id"])
        liquidations = [e for e in entries if e["entry_type"] == "REFUND_LIQUIDATION"]
        assert len(liquidations) == 1
        assert liquidations[0]["amount_cents"] == -1100, (
            f"liquidation must be the negative of the remaining deferred balance, got "
            f"{liquidations[0]['amount_cents']}"
        )
        recognitions = [e for e in entries if e["entry_type"] == "RECOGNITION"]
        # 100 recognized at mailing + the unrefunded remainder: 1100 - floor(1100*0.9) = 110.
        top_ups = [e for e in recognitions if e["amount_cents"] == 110]
        assert len(top_ups) == 1, (
            f"the unrefunded remainder of 110 cents must be recognized immediately, got {recognitions}"
        )
