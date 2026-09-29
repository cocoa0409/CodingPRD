"""Immediate consistency: nothing in this system is ever stale on the next read.

Every derived figure — a card's whole ledger projection, a rack's classification, a
store's floor posture and the cards the suspension reaches — is already current in the
response of the very request that disturbed its inputs, with no clock advance, no retry
and no second read.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.constants import CLOCK_ORIGIN
from test_helpers.fixtures import (
    audit_rack,
    create_rack,
    create_store,
    funded_physical_card,
    parse_instant,
    read_card,
    read_rack,
    read_store,
    redeem,
    stock_card,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_pos_associate_headers,
    make_risk_manager_headers,
)


class TestEveryDerivedFieldIsCurrentInTheSameResponse:
    """"Derived values are recomputed eagerly, inside the request that disturbs their
    inputs"."""

    def _world(self, client):
        """One store, one rack expecting 6 cards, an ACTIVE 5000-cent card and a second card
        that was stocked but never screened, so it is still INACTIVE."""
        store = create_store(
            client,
            name="Immediate Consistency Store",
            region_code="SW",
            address_line="68 Immediate Way",
        )
        rack = create_rack(client, store["id"], rack_label="RACK-IC", expected_card_count=6)
        built = funded_physical_card(client, 5000, store=store, rack=rack)
        assert built["request"]["state"] == "APPROVED"
        idle = stock_card(client, store["id"], rack["id"])
        return store["id"], rack["id"], built["card"]["id"], idle["id"]

    def test_the_whole_projection_is_current_on_the_first_read_after_the_redemption(self, client):
        """"current_balance_cents is the sum of every event's signed amount."
        "drawdown_ratio is then derived: 0.00 when total_loaded_cents is zero, and otherwise
        total_redeemed_cents divided by total_loaded_cents, rounded half up to two decimal
        places and clamped into the closed range 0.00 through 1.00."
        "distinct_merchant_count counts the distinct non-empty merchant_store_id values among
        them ... and recent_redemption_count counts those events themselves."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
        """
        store_id, _, active_id, _ = self._world(client)

        event = redeem(
            client,
            active_id,
            1000,
            store_id,
            headers=make_pos_associate_headers("pos-99"),
            pos_terminal_id="T-99",
        )

        assert event["signed_amount_cents"] == -1000
        card = read_card(client, active_id, headers=make_risk_manager_headers("risk-99"))
        assert card["current_balance_cents"] == 4000
        assert card["total_loaded_cents"] == 5000
        assert card["total_redeemed_cents"] == 1000
        assert float(card["drawdown_ratio"]) == pytest.approx(0.20, abs=0.01)
        assert card["distinct_merchant_count"] == 1
        assert card["recent_redemption_count"] == 1

    def test_the_audit_response_itself_already_carries_the_classification_and_the_floor_follows(
        self, client
    ):
        """"Both figures are persisted verbatim so that the classification is reproducible from
        the stored row, and last_audit_at is stamped from the logical clock."
        "If missing_card_count is at least rack_shrink_threshold, or seal_breaks_observed is at
        least rack_seal_break_threshold, the rack is TAMPERED."
        "Hop two is the store's recomputation, which — because tampered_rack_count is now at
        least 1 — drives floor_posture to SUSPENDED from either OPEN or HEIGHTENED."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
        """
        store_id, rack_id, active_id, _ = self._world(client)
        redeem(client, active_id, 1000, store_id, pos_terminal_id="T-99")

        audited = audit_rack(client, rack_id, 3, seal_breaks_observed=0)

        assert audited["tamper_state"] == "TAMPERED"
        assert audited["missing_card_count"] == 3
        assert audited["observed_card_count"] == 3
        assert parse_instant(audited["last_audit_at"]) == parse_instant(CLOCK_ORIGIN)
        store = read_store(client, store_id, headers=make_fraud_analyst_headers("analyst-99"))
        assert store["floor_posture"] == "SUSPENDED"
        assert store["tampered_rack_count"] == 1
        assert store["suspect_rack_count"] == 0

    def test_the_suspension_reached_the_inactive_card_inside_the_audit_request(self, client):
        """"Hop three follows from the store now being suspended: every gift card belonging to
        that store whose funding state is still INACTIVE transitions to VOIDED, has its fraud
        posture forced to FROZEN, and has its closed_at stamped from the logical clock."
        "Cards that are ACTIVE, DEPLETED or CLOSED are left completely untouched, because
        their value is already funded and belongs to a customer."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
        """
        store_id, rack_id, active_id, idle_id = self._world(client)
        redeem(client, active_id, 1000, store_id, pos_terminal_id="T-99")
        analyst = make_fraud_analyst_headers("analyst-99")

        audit_rack(client, rack_id, 3, seal_breaks_observed=0)

        voided = read_card(client, idle_id, headers=analyst)
        assert voided["activation_state"] == "VOIDED"
        assert voided["risk_posture"] == "FROZEN"
        assert parse_instant(voided["closed_at"]) == parse_instant(CLOCK_ORIGIN)
        survivor = read_card(client, active_id, headers=analyst)
        assert survivor["activation_state"] == "ACTIVE"
        assert survivor["current_balance_cents"] == 4000

    def test_repeating_every_read_returns_identical_data_with_no_refresh_step(self, client):
        """"Derived values are recomputed eagerly, inside the request that disturbs their
        inputs — this system is immediately consistent and has no background recomputation, no
        lazy-on-read refresh and no eventual convergence."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
        """
        store_id, rack_id, active_id, idle_id = self._world(client)
        redeem(client, active_id, 1000, store_id, pos_terminal_id="T-99")
        audit_rack(client, rack_id, 3, seal_breaks_observed=0)
        analyst = make_fraud_analyst_headers("analyst-99")

        first = [
            read_card(client, active_id, headers=analyst),
            read_card(client, idle_id, headers=analyst),
            read_rack(client, rack_id, headers=analyst),
            read_store(client, store_id, headers=analyst),
        ]
        second = [
            read_card(client, active_id, headers=analyst),
            read_card(client, idle_id, headers=analyst),
            read_rack(client, rack_id, headers=analyst),
            read_store(client, store_id, headers=analyst),
        ]

        assert first == second
        assert validate_success(client.get_gift_card(active_id, analyst), 200) == first[0]
