"""Requests that violate two ladder rungs at once, where the earlier rung must win.

"Every request is validated as an ordered ladder, and the first violation encountered
wins: the request is rejected with that rule's error and no later rule is evaluated."
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_CARD_FROZEN,
    ERR_IDENTITY_VERIFICATION_REQUIRED,
    ERR_INSUFFICIENT_BALANCE,
    ERR_STORE_FLOOR_SUSPENDED,
)
from test_helpers.factories import bulk_decision_payload, redemption_payload
from test_helpers.fixtures import (
    audit_rack,
    create_rack,
    create_store,
    funded_physical_card,
    open_bulk_order,
    override_posture,
    read_card,
    read_store,
    total_count,
)
from test_helpers.test_users import (
    make_platform_admin_headers,
    make_pos_associate_headers,
    make_risk_manager_headers,
)


class TestFrozenBeatsInsufficientBalance:
    """A state violation and a fiscal violation on one redemption."""

    def _frozen_card(self, client):
        """A 5000-cent ACTIVE card frozen by a RiskManager, so a 9000-cent redemption
        both hits the posture gate and exceeds the balance."""
        store = create_store(client, name="Summit Fuel", region_code="SW", address_line="12 Summit Rd")
        rack = create_rack(client, store["id"], rack_label="RACK-S1", expected_card_count=5)
        built = funded_physical_card(client, 5000, store=store, rack=rack)
        frozen = override_posture(
            client, built["card"]["id"], "FROZEN", reason="confirmed drain ring"
        )
        return {"store": store, "card_id": built["card"]["id"], "frozen": frozen}

    def test_both_violations_are_live_before_the_redemption_is_attempted(self, client):
        """The card is FROZEN and holds only 5000 cents, so the 9000-cent redemption
        genuinely breaches both the posture gate and the balance gate.

        Design: Difficulty/priority_pair_validation_conflict/frozen_card_state_error_beats_insufficient_balance_fiscal_error
        """
        world = self._frozen_card(client)

        assert world["frozen"]["risk_posture"] == "FROZEN"
        assert world["frozen"]["current_balance_cents"] == 5000
        assert world["frozen"]["activation_state"] == "ACTIVE"

    def test_the_frozen_state_error_is_the_one_the_caller_sees(self, client):
        """"A redemption is refused when the card is not ACTIVE (ERR_CARD_NOT_ACTIVE), when
        its posture is FROZEN (ERR_CARD_FROZEN), when the merchant store's floor is
        SUSPENDED (ERR_STORE_FLOOR_SUSPENDED), and when amount_cents exceeds the card's
        available_balance_cents (ERR_INSUFFICIENT_BALANCE) — in exactly that order of
        precedence."

        Design: Difficulty/priority_pair_validation_conflict/frozen_card_state_error_beats_insufficient_balance_fiscal_error
        """
        world = self._frozen_card(client)

        response = client.create_redemption(
            world["card_id"],
            redemption_payload(9000, world["store"]["id"], pos_terminal_id="T-71"),
            make_pos_associate_headers(),
        )

        assert response.status_code == 409, response.text
        body = validate_error(response, ERR_CARD_FROZEN, 409)
        assert body["error_id"] != ERR_INSUFFICIENT_BALANCE

    def test_the_rejected_redemption_moves_no_value_at_all(self, client):
        """A rejected write "is not a mutation", so the card's projection is untouched and
        its ledger still holds only the activation load.

        Design: Difficulty/priority_pair_validation_conflict/frozen_card_state_error_beats_insufficient_balance_fiscal_error
        """
        world = self._frozen_card(client)

        client.create_redemption(
            world["card_id"],
            redemption_payload(9000, world["store"]["id"], pos_terminal_id="T-71"),
            make_pos_associate_headers(),
        )

        card = read_card(client, world["card_id"])
        assert card["current_balance_cents"] == 5000
        assert card["total_redeemed_cents"] == 0
        events = client.list_ledger_events(
            make_platform_admin_headers(), {"card_id": world["card_id"]}
        )
        assert total_count(events) == 1


class TestSuspendedFloorBeatsMissingIdentity:
    """A safety violation and a referential violation on one bulk-order approval."""

    def _suspended_store_with_unverified_order(self, client):
        """A 60900-cent bulk order left in PENDING_IDENTITY with no identity recorded, at a
        store an unrelated rack audit has driven to SUSPENDED."""
        store = create_store(client, name="Junction Market", region_code="MW", address_line="8 Junction St")
        rack = create_rack(client, store["id"], rack_label="RACK-J1", expected_card_count=10)
        order = open_bulk_order(
            client,
            store["id"],
            card_quantity=5,
            face_value_cents_each=12000,
            purchaser_name="Vantage Logistics",
            payment_method="CREDIT",
        )
        audit_rack(client, rack["id"], observed_card_count=7, seal_breaks_observed=0)
        return {"store": store, "order": order}

    def test_both_violations_are_live_before_the_approval_is_attempted(self, client):
        """The order's total of 60900 cents is "at or above bulk_identity_threshold_cents",
        which is why it opened in PENDING_IDENTITY, and the store's floor is SUSPENDED.

        Design: Difficulty/priority_pair_validation_conflict/suspended_floor_safety_error_beats_missing_identity_referential_error
        """
        world = self._suspended_store_with_unverified_order(client)

        assert world["order"]["total_cents"] == 60900
        assert world["order"]["state"] == "PENDING_IDENTITY"
        assert read_store(client, world["store"]["id"])["floor_posture"] == "SUSPENDED"

    def test_the_suspended_floor_error_is_the_one_the_caller_sees(self, client):
        """"Because the floor check sits in an earlier validation tier than the identity
        check, a suspended floor masks a missing identity: the caller sees the floor
        error."

        Design: Difficulty/priority_pair_validation_conflict/suspended_floor_safety_error_beats_missing_identity_referential_error
        """
        world = self._suspended_store_with_unverified_order(client)

        response = client.decide_bulk_purchase_order(
            world["order"]["id"],
            bulk_decision_payload("APPROVE", decision_note="regular corporate customer"),
            make_risk_manager_headers("risk-4"),
        )

        assert response.status_code == 422, response.text
        body = validate_error(response, ERR_STORE_FLOOR_SUSPENDED, 422)
        assert body["error_id"] != ERR_IDENTITY_VERIFICATION_REQUIRED

    def test_the_rejected_decision_neither_advances_nor_versions_the_order(self, client):
        """A version "increases by exactly 1 on every mutation", and a rejected write is not
        one, so the order stays in PENDING_IDENTITY at its creation version with no
        decider recorded.

        Design: Difficulty/priority_pair_validation_conflict/suspended_floor_safety_error_beats_missing_identity_referential_error
        """
        world = self._suspended_store_with_unverified_order(client)
        version_before = world["order"]["version"]

        client.decide_bulk_purchase_order(
            world["order"]["id"],
            bulk_decision_payload("APPROVE", decision_note="regular corporate customer"),
            make_risk_manager_headers("risk-4"),
        )

        order = client.get_bulk_purchase_order(
            world["order"]["id"], make_platform_admin_headers()
        ).json()["data"]
        assert order["state"] == "PENDING_IDENTITY"
        assert order["version"] == version_before
        assert not order["decided_by_user_id"]
