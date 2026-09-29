"""
The consistency model: cascades land inside the triggering request, so the
declaring response and the reads that follow it agree completely.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal, assert_instant_equals
from test_helpers.constants import CLOCK_BASE_UTC
from test_helpers.test_users import REGULATOR_HEADERS

APPOINTMENT_START = "2026-08-20T09:00:00Z"
APPOINTMENT_END = "2026-08-20T11:00:00Z"


class TestInsolvencyDeclarationIsImmediatelyVisible:
    @pytest.fixture
    def warehouse_with_a_booked_loadout(self, base_full, booked_delivery_order):
        """
        The whole base chain plus a REQUESTED delivery order for all 949 receipted
        bushels, holding those bushels in bin B1 against a 2026-08-20 appointment.
        """
        order = booked_delivery_order(
            base_full["depositor_id"],
            base_full["receipt_id"],
            949,
            APPOINTMENT_START,
            APPOINTMENT_END,
        )
        return {"scenario": base_full, "order_id": order["id"]}

    def test_the_declaring_response_already_carries_the_new_posture(
        self, api, warehouse_with_a_booked_loadout
    ):
        """
        The regulator does not have to read the warehouse back to learn where it
        now stands: the DECLARE response itself reports the insolvency state, the
        posted price, the declaration instant taken from the logical clock, and the
        posture already recomputed to CLOSED — while the licence, which lives on an
        entirely separate dimension, still reads LICENSED.

        PRD: "The insolvency dimension is entirely independent of the licensing
        dimension."

        PRD: "A `LICENSED` warehouse can be declared insolvent, and a `SUSPENDED`
        warehouse can remain `SOLVENT`."

        PRD: "It sets `insolvency_declared_at` to the current logical clock and
        fixes `insolvency_price_cents_per_bushel` from the request — one posted
        commodity price that will govern every entitlement in the proceeding."

        PRD: "Declaration drives `operational_posture` to `CLOSED` regardless of
        `license_state`, cancels every delivery order in `delivery_state`
        `REQUESTED` with `cancellation_reason` `INSOLVENCY_DECLARED` and releases
        their held bushels, and moves every deposit ticket in `ticket_state`
        `WEIGHED` to `REJECTED` with `rejection_reason` `INSOLVENCY_DECLARED`."

        PRD: "If `license_state` is anything other than `LICENSED`, or
        `insolvency_state` is anything other than `SOLVENT`, the posture is
        `CLOSED`."

        Design: Corner/consistency_model/insolvency_declaration_effects_are_visible_in_the_same_response
        """
        scenario = warehouse_with_a_booked_loadout["scenario"]

        declared = get_success_data(
            api.insolvency_action(
                scenario["warehouse_id"],
                f.insolvency_payload(
                    "DECLARE",
                    insolvency_price_cents_per_bushel=400,
                    note="receivership",
                ),
                REGULATOR_HEADERS,
            ),
            200,
        )

        assert_fields_equal(
            declared,
            {
                "insolvency_state": "DECLARED",
                "operational_posture": "CLOSED",
                "insolvency_price_cents_per_bushel": 400,
                "license_state": "LICENSED",
            },
        )
        assert_instant_equals(
            declared["insolvency_declared_at"], CLOCK_BASE_UTC, "insolvency_declared_at"
        )

    def test_the_cascade_is_settled_before_the_next_read_returns(
        self, api, warehouse_with_a_booked_loadout
    ):
        """
        The declaration touched two rows the regulator never named, and neither one
        lags: the delivery order read straight afterwards is already CANCELLED for
        insolvency, and the bin has already given its 949 held bushels back — they
        are stored and available again, because releasing a hold moves no grain.
        The computed position read agrees that the facility is closed.

        PRD: "Every cascade is applied immediately and synchronously within the
        triggering request, so a read issued straight afterwards observes the fully
        settled result."

        PRD: "Declaration drives `operational_posture` to `CLOSED` regardless of
        `license_state`, cancels every delivery order in `delivery_state`
        `REQUESTED` with `cancellation_reason` `INSOLVENCY_DECLARED` and releases
        their held bushels, and moves every deposit ticket in `ticket_state`
        `WEIGHED` to `REJECTED` with `rejection_reason` `INSOLVENCY_DECLARED`."

        PRD: "Four derived quantities describe a bin's position at any instant:
        `stored_bushels` is the physical inventory actually on hand; `held_bushels`
        is the sum of `requested_bushels` across delivery orders drawn from this bin
        whose `delivery_state` is `REQUESTED` or `LOADED`; `available_bushels` is
        stored less held; and `scheduled_inbound_bushels` is the sum of
        `net_bushels` across tickets destined for this bin that are still merely
        `WEIGHED`."

        Design: Corner/consistency_model/insolvency_declaration_effects_are_visible_in_the_same_response
        """
        scenario = warehouse_with_a_booked_loadout["scenario"]

        get_success_data(
            api.insolvency_action(
                scenario["warehouse_id"],
                f.insolvency_payload(
                    "DECLARE",
                    insolvency_price_cents_per_bushel=400,
                    note="receivership",
                ),
                REGULATOR_HEADERS,
            ),
            200,
        )

        order = get_success_data(
            api.get_delivery_order(
                warehouse_with_a_booked_loadout["order_id"], REGULATOR_HEADERS
            ),
            200,
        )
        assert_fields_equal(
            order,
            {
                "delivery_state": "CANCELLED",
                "cancellation_reason": "INSOLVENCY_DECLARED",
            },
        )

        storage_bin = get_success_data(
            api.get_bin(scenario["bin_id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            storage_bin,
            {
                "held_bushels": 0,
                "stored_bushels": 949,
                "available_bushels": 949,
            },
        )

        get_success_data(
            api.get_position_summary(scenario["warehouse_id"], REGULATOR_HEADERS), 200
        )
        warehouse = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], REGULATOR_HEADERS), 200
        )
        assert warehouse["operational_posture"] == "CLOSED"
