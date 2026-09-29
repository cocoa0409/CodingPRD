"""
Requests that violate two guards at once, where the contract fixes which error
the caller is entitled to see.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.test_users import REGULATOR_HEADERS, make_warehouse_operator_headers


class TestLicensingGateBeatsLicensedCapacity:
    @pytest.fixture
    def suspended_small_crib(
        self,
        api,
        licensed_warehouse,
        new_producer,
        new_agreement,
        new_bin,
        accepted_ticket,
    ):
        """
        A licensed 500-bushel facility holding an accepted 949-bushel load, then
        suspended, so an issuance would breach both the licensing gate and the
        licensed-capacity gate.
        """
        warehouse = licensed_warehouse(name="Small Crib", licensed_capacity_bushels=500)
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        ticket = accepted_ticket(warehouse["id"], agreement["id"], storage_bin["id"])
        get_success_data(
            api.license_decision(
                warehouse["id"],
                f.license_decision_payload("SUSPEND", note="records violation"),
                REGULATOR_HEADERS,
            ),
            200,
        )
        headers = make_warehouse_operator_headers(warehouse["id"])
        current = get_success_data(api.get_warehouse(warehouse["id"], headers), 200)
        return {
            "warehouse_id": warehouse["id"],
            "warehouse_version": current["version"],
            "depositor_id": producer["id"],
            "ticket_id": ticket["id"],
            "headers": headers,
        }

    def test_suspended_licence_is_reported_ahead_of_the_capacity_overrun(
        self, api, suspended_small_crib
    ):
        """
        Issuing 949 bushels against a 500-bushel licence at a suspended facility
        breaks the rank-11 licensing gate and the rank-27 licensed-capacity gate
        at once; the caller must be told the licence is not in force.

        PRD: "The placement of the three regulatory gates (ranks 11 through 13)
        **above** the safety, constraint and fiscal checks is deliberate policy,
        not an accident of ordering: an unlicensed, insolvent or
        position-restricted facility is not permitted to explain itself with a
        capacity or bond error."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_capacity_fiscal_on_receipt_issuance
        """
        response = api.create_receipt(
            f.receipt_payload(
                suspended_small_crib["ticket_id"],
                suspended_small_crib["depositor_id"],
                suspended_small_crib["warehouse_version"],
            ),
            suspended_small_crib["headers"],
        )

        error = validate_error(response, E.ERR_WAREHOUSE_NOT_LICENSED, 422)
        assert error["error_id"] != E.ERR_LICENSED_CAPACITY_EXCEEDED

    def test_the_refused_issuance_leaves_the_ticket_and_the_obligation_untouched(
        self, api, suspended_small_crib
    ):
        """
        Nothing is written when the licensing gate refuses: the source ticket is
        still ACCEPTED and no bushels have reached the receipted side of the
        obligation.

        PRD: "Only receipted obligation counts here — accepted but unreceipted
        grain does not consume licensed capacity."

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_capacity_fiscal_on_receipt_issuance
        """
        api.create_receipt(
            f.receipt_payload(
                suspended_small_crib["ticket_id"],
                suspended_small_crib["depositor_id"],
                suspended_small_crib["warehouse_version"],
            ),
            suspended_small_crib["headers"],
        )

        ticket = get_success_data(
            api.get_deposit_ticket(
                suspended_small_crib["ticket_id"], suspended_small_crib["headers"]
            ),
            200,
        )
        assert ticket["ticket_state"] == "ACCEPTED"

        warehouse = get_success_data(
            api.get_warehouse(
                suspended_small_crib["warehouse_id"], suspended_small_crib["headers"]
            ),
            200,
        )
        assert warehouse["receipted_obligation_bushels"] == 0


class TestBinConditionBeatsFillWindowConflict:
    @pytest.fixture
    def out_of_condition_bin_with_weighed_load(
        self,
        licensed_warehouse,
        new_producer,
        new_agreement,
        new_bin,
        weighed_ticket,
        assess_bin,
    ):
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        ticket = weighed_ticket(warehouse["id"], agreement["id"], storage_bin["id"])
        assess_bin(warehouse["id"], storage_bin["id"], 16.0, 70)
        return {
            "agreement_id": agreement["id"],
            "bin_id": storage_bin["id"],
            "ticket_id": ticket["id"],
            "headers": make_warehouse_operator_headers(warehouse["id"]),
        }

    def test_bin_condition_is_reported_ahead_of_the_fill_window_conflict(
        self, api, out_of_condition_bin_with_weighed_load
    ):
        """
        A weigh-in aimed at an out-of-condition bin whose requested 10:00-12:00
        window also collides with the standing 09:00-11:00 reservation breaks
        rank 14 and rank 20 together; the safety refusal wins.

        PRD: "While a bin is `OUT_OF_CONDITION` it is frozen for grain movement
        in both directions: grain may not be weighed in against it, accepted into
        it, receipted out of it, made the subject of a new delivery order, or
        loaded out of it."

        Design: Difficulty/priority_pair_validation_conflict/bin_condition_safety_beats_fill_window_constraint_on_deposit_ticket
        """
        scenario = out_of_condition_bin_with_weighed_load
        response = api.create_deposit_ticket(
            f.deposit_ticket_payload(
                scenario["agreement_id"],
                scenario["bin_id"],
                gross_bushels=800,
                moisture_pct=13.0,
                dockage_pct=0.0,
                fill_start_at="2026-08-05T10:00:00Z",
                fill_end_at="2026-08-05T12:00:00Z",
            ),
            scenario["headers"],
        )

        error = validate_error(response, E.ERR_BIN_OUT_OF_CONDITION, 422)
        assert error["error_id"] != E.ERR_BIN_WINDOW_CONFLICT

    def test_the_refused_weigh_in_leaves_one_ticket_and_one_reservation(
        self, api, out_of_condition_bin_with_weighed_load
    ):
        """
        The refusal writes nothing, so only the original 949-bushel soft
        reservation stands on the bin and the bin still has exactly one ticket.

        PRD: "`scheduled_inbound_bushels` is the sum of `net_bushels` across
        tickets destined for this bin that are still merely `WEIGHED`."

        Design: Difficulty/priority_pair_validation_conflict/bin_condition_safety_beats_fill_window_constraint_on_deposit_ticket
        """
        scenario = out_of_condition_bin_with_weighed_load
        api.create_deposit_ticket(
            f.deposit_ticket_payload(
                scenario["agreement_id"],
                scenario["bin_id"],
                gross_bushels=800,
                moisture_pct=13.0,
                dockage_pct=0.0,
                fill_start_at="2026-08-05T10:00:00Z",
                fill_end_at="2026-08-05T12:00:00Z",
            ),
            scenario["headers"],
        )

        storage_bin = get_success_data(
            api.get_bin(scenario["bin_id"], scenario["headers"]), 200
        )
        assert storage_bin["scheduled_inbound_bushels"] == 949

        tickets, _meta = validate_paginated(
            api.list_deposit_tickets({"bin_id": scenario["bin_id"]}, scenario["headers"])
        )
        assert len(tickets) == 1
        assert tickets[0]["id"] == scenario["ticket_id"]
