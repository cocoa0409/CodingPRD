"""
Guards that depend on a neighbouring row's configuration, on an aggregate, on
the logical clock, or on where they sit in the failure ladder.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal, assert_instant_equals
from test_helpers.constants import CLOCK_BASE_UTC
from test_helpers.test_users import (
    REGULATOR_HEADERS,
    make_warehouse_operator_headers,
)


@pytest.fixture
def elevator(licensed_warehouse, new_producer, new_agreement, new_bin):
    """A licensed warehouse with one producer, a COMMINGLED agreement and bin B1."""

    def _build(**warehouse_overrides):
        warehouse = licensed_warehouse(**warehouse_overrides)
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        return {
            "warehouse_id": warehouse["id"],
            "producer_id": producer["id"],
            "agreement_id": agreement["id"],
            "bin_id": storage_bin["id"],
            "headers": make_warehouse_operator_headers(warehouse["id"]),
        }

    return _build


class TestComminglingConfiguration:
    def test_an_identity_preserved_lot_cannot_go_into_a_common_mass_bin(
        self, api, elevator, weighed_ticket
    ):
        """
        Bin B1 is demonstrably usable — a commingled load is already booked on it
        — but the very same bin is illegal for an identity-preserved agreement,
        because keeping a lot identified means keeping it out of the common mass.
        No ticket is written for that agreement at all.

        PRD: "Any violation — an identity-preserved lot into a commingling bin, a
        commingled lot into a non-commingling bin, or use of a bin already
        dedicated to a different agreement — is rejected with
        `ERR_COMMINGLING_NOT_PERMITTED`."

        Design: Corner/validations/commingling_rule_blocks_identity_preserved_lot_in_commingling_bin
        """
        scenario = elevator()
        commingled_ticket = weighed_ticket(
            scenario["warehouse_id"], scenario["agreement_id"], scenario["bin_id"]
        )
        preserved_agreement = get_success_data(
            api.create_storage_agreement(
                f.storage_agreement_payload(
                    scenario["warehouse_id"],
                    scenario["producer_id"],
                    storage_kind="IDENTITY_PRESERVED",
                ),
                scenario["headers"],
            ),
            201,
        )

        response = api.create_deposit_ticket(
            f.deposit_ticket_payload(
                preserved_agreement["id"],
                scenario["bin_id"],
                gross_bushels=400,
                moisture_pct=13.0,
                dockage_pct=0.0,
                fill_start_at="2026-08-09T09:00:00Z",
                fill_end_at="2026-08-09T11:00:00Z",
            ),
            scenario["headers"],
        )

        validate_error(response, E.ERR_COMMINGLING_NOT_PERMITTED, 422)

        rows, meta = validate_paginated(
            api.list_deposit_tickets(
                {"storage_agreement_id": preserved_agreement["id"]},
                scenario["headers"],
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        standing = get_success_data(
            api.get_deposit_ticket(commingled_ticket["id"], scenario["headers"]), 200
        )
        assert standing["ticket_state"] == "WEIGHED"


class TestBinHeadroomAggregate:
    def test_an_unaccepted_reservation_still_consumes_the_bins_headroom(
        self, api, elevator, weighed_ticket
    ):
        """
        Nothing is stored in the 40000-bushel bin yet, so 15000 bushels look like
        an easy fit — but a 30000-bushel load is already booked in, and the
        headroom test nets that soft reservation out: 40000 less 30000 leaves
        10000, which is short.

        PRD: "The room test is the bin's remaining headroom — its
        `capacity_bushels` less `stored_bushels` less `held_bushels` less
        `scheduled_inbound_bushels`, with the accepting ticket's own reservation
        excluded from that last term since it is the very load being admitted —
        measured against the ticket's `net_bushels`, and a shortfall is rejected
        with `ERR_BIN_CAPACITY_EXCEEDED`."

        PRD: "The same headroom test also runs at weigh-in, where the new ticket
        has no reservation yet to exclude."

        Design: Corner/validations/bin_headroom_aggregate_of_scheduled_inbound_blocks_second_ticket
        """
        scenario = elevator()
        first = weighed_ticket(
            scenario["warehouse_id"],
            scenario["agreement_id"],
            scenario["bin_id"],
            gross_bushels=30_000,
            moisture_pct=13.0,
            dockage_pct=0.0,
        )

        response = api.create_deposit_ticket(
            f.deposit_ticket_payload(
                scenario["agreement_id"],
                scenario["bin_id"],
                gross_bushels=15_000,
                moisture_pct=13.0,
                dockage_pct=0.0,
                fill_start_at="2026-08-09T09:00:00Z",
                fill_end_at="2026-08-09T11:00:00Z",
            ),
            scenario["headers"],
        )

        validate_error(response, E.ERR_BIN_CAPACITY_EXCEEDED, 422)

        assert first["net_bushels"] == 30000
        storage_bin = get_success_data(
            api.get_bin(scenario["bin_id"], scenario["headers"]), 200
        )
        assert_fields_equal(
            storage_bin, {"scheduled_inbound_bushels": 30000, "stored_bushels": 0}
        )


class TestRegistryParticipationGate:
    def test_an_electronic_receipt_is_refused_at_a_paper_only_facility(
        self, api, elevator, accepted_ticket
    ):
        """
        Everything else about the issuance is in order — the ticket is accepted,
        the form is negotiable, the number is fresh — but this facility declared
        itself out of the electronic registry, so an electronic receipt cannot
        exist here and the ticket stays accepted with nothing receipted.

        PRD: "An `ELECTRONIC` receipt may only be issued at a warehouse whose
        `registry_participant` is true; otherwise the issuance is refused with
        `ERR_REGISTRY_NOT_PARTICIPANT`."

        Design: Corner/validations/electronic_receipt_requires_registry_participation
        """
        scenario = elevator(
            name="Paper Only Elevator",
            operator_name="Paper Grain Co",
            registry_participant=False,
        )
        ticket = accepted_ticket(
            scenario["warehouse_id"], scenario["agreement_id"], scenario["bin_id"]
        )
        warehouse = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], scenario["headers"]), 200
        )

        response = api.create_receipt(
            f.receipt_payload(
                ticket["id"],
                scenario["producer_id"],
                warehouse["version"],
                receipt_number="WR-9001",
                medium="ELECTRONIC",
            ),
            scenario["headers"],
        )

        validate_error(response, E.ERR_REGISTRY_NOT_PARTICIPANT, 422)

        current_ticket = get_success_data(
            api.get_deposit_ticket(ticket["id"], scenario["headers"]), 200
        )
        assert current_ticket["ticket_state"] == "ACCEPTED"

        current = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], scenario["headers"]), 200
        )
        assert current["receipted_obligation_bushels"] == 0


class TestVoidWindow:
    def test_a_void_ninety_six_hours_after_issuance_is_out_of_time(
        self, api, base_full, set_clock
    ):
        """
        The window is measured on the logical clock, not on wall time: four days
        after the 2026-08-05T08:00:00Z issuance the receipt is 96 hours old, past
        the 72-hour limit, so the correction is refused and the whole issuance
        stands — receipt, obligation and source ticket alike.

        PRD: "It requires that the receipt still be `ISSUED`, that its
        `encumbrance_state` not be `PLEDGED`, that no delivery order on the receipt
        be in `delivery_state` `REQUESTED` or `LOADED`, and that the current
        logical clock be within 72 hours of `issued_at` — a later attempt is
        refused with `ERR_VOID_WINDOW_EXPIRED`."

        Design: Corner/validations/receipt_void_after_seventy_two_hours_rejected
        """
        set_clock("2026-08-09T08:00:00Z")

        response = api.void_receipt(
            base_full["receipt_id"],
            f.void_payload(void_reason="CLERICAL_ERROR"),
            base_full["operator_headers"],
        )

        validate_error(response, E.ERR_VOID_WINDOW_EXPIRED, 422)

        headers = base_full["operator_headers"]
        receipt = get_success_data(
            api.get_receipt(base_full["receipt_id"], headers), 200
        )
        assert receipt["receipt_state"] == "ISSUED"

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], headers), 200
        )
        assert warehouse["receipted_obligation_bushels"] == 949

        ticket = get_success_data(
            api.get_deposit_ticket(base_full["ticket_id"], headers), 200
        )
        assert ticket["ticket_state"] == "RECEIPTED"


class TestLadderPrecedenceOnASecondAccept:
    def test_the_stale_version_is_reported_rather_than_the_settled_state(
        self, api, elevator, weighed_ticket, accept_ticket
    ):
        """
        Replaying the accept violates two rules at once: the ticket has already
        left WEIGHED, and the version captured before the first accept is now one
        behind. The concurrency check sits above state admissibility, so the caller
        is told its write is stale rather than that the transition is impossible —
        and the grain is not credited to the bin twice.

        PRD: "Checks are evaluated in the following fixed order, and the **first**
        rule violated determines the response; later rules are not evaluated and
        their errors are not reported."

        PRD: "Optimistic-concurrency version match per §2.7 —
        `ERR_STALE_WAREHOUSE_VERSION` and `ERR_STALE_BIN_VERSION`."

        Design: Corner/validations/stale_bin_version_outranks_invalid_state_on_second_accept
        """
        scenario = elevator()
        ticket = weighed_ticket(
            scenario["warehouse_id"], scenario["agreement_id"], scenario["bin_id"]
        )
        before = get_success_data(
            api.get_bin(scenario["bin_id"], scenario["headers"]), 200
        )
        accept_ticket(scenario["warehouse_id"], scenario["bin_id"], ticket["id"])

        response = api.accept_deposit_ticket(
            ticket["id"],
            f.accept_ticket_payload(before["version"]),
            scenario["headers"],
        )

        validate_error(response, E.ERR_STALE_BIN_VERSION, 412)

        current_ticket = get_success_data(
            api.get_deposit_ticket(ticket["id"], scenario["headers"]), 200
        )
        assert current_ticket["ticket_state"] == "ACCEPTED"

        storage_bin = get_success_data(
            api.get_bin(scenario["bin_id"], scenario["headers"]), 200
        )
        assert storage_bin["stored_bushels"] == 949


class TestGradeExactlyAtTheAgreementMinimum:
    def test_a_lot_grading_exactly_the_minimum_is_admitted(
        self, api, elevator, weighed_ticket, accept_ticket
    ):
        """
        The agreement's floor is US_NO_3 and the load grades US_NO_3, which is a
        rank equal to — not below — the minimum, so the at-or-above test is
        satisfied and the grain goes in, stamped with the current logical clock.

        PRD: "Beyond the version match of §2.7, the ticket must still be
        `WEIGHED`; the warehouse's `license_state` must be `LICENSED` and its
        `insolvency_state` `SOLVENT`; the posture must not be `RESTRICTED`; the
        bin's `condition_state` must not be `OUT_OF_CONDITION`, or the request is
        rejected with `ERR_BIN_OUT_OF_CONDITION`; the ticket's `assigned_grade`
        must rank at or above the agreement's `min_grade`, or the request is
        rejected with `ERR_GRADE_BELOW_MINIMUM`; and the bin must have room."

        PRD: "Grades also carry a rank used whenever two grades are compared:
        `US_NO_1` ranks 1, `US_NO_2` ranks 2, `US_NO_3` ranks 3 and `SAMPLE_GRADE`
        ranks 4."

        Design: Corner/validations/grade_exactly_at_agreement_minimum_is_accepted
        """
        scenario = elevator()
        ticket = weighed_ticket(
            scenario["warehouse_id"],
            scenario["agreement_id"],
            scenario["bin_id"],
            damage_pct=6.0,
        )
        assert ticket["assigned_grade"] == "US_NO_3"

        accepted = accept_ticket(
            scenario["warehouse_id"], scenario["bin_id"], ticket["id"]
        )

        assert accepted["ticket_state"] == "ACCEPTED"
        assert_instant_equals(accepted["accepted_at"], CLOCK_BASE_UTC, "accepted_at")

    def test_the_admitted_lot_sets_the_bins_inventory_and_blended_grade(
        self, api, elevator, weighed_ticket, accept_ticket
    ):
        """
        Acceptance is what moves the bin: its inventory rises by the load's 949
        net bushels, and the only accepted lot in it fixes the blended grade at
        US_NO_3.

        PRD: "Acceptance then sets `accepted_at` from the logical clock, moves the
        ticket to `ACCEPTED`, increments the bin's `version` by one, raises the
        bin's `stored_bushels` by the ticket's `net_bushels`, raises the bin's
        `cumulative_shrink_bushels` by the ticket's `shrink_bushels`, clears the
        ticket's scheduled-inbound reservation, recomputes the bin's
        `blended_grade`, and raises the warehouse's `obligation_bushels` and
        `system_physical_bushels` before recomputing the posture."

        PRD: "`blended_grade` is the worst — highest-ranked — `assigned_grade`
        among the accepted tickets in the bin, and is null while the bin is empty."

        Design: Corner/validations/grade_exactly_at_agreement_minimum_is_accepted
        """
        scenario = elevator()
        ticket = weighed_ticket(
            scenario["warehouse_id"],
            scenario["agreement_id"],
            scenario["bin_id"],
            damage_pct=6.0,
        )
        accept_ticket(scenario["warehouse_id"], scenario["bin_id"], ticket["id"])

        storage_bin = get_success_data(
            api.get_bin(scenario["bin_id"], REGULATOR_HEADERS), 200
        )
        assert_fields_equal(
            storage_bin,
            {"stored_bushels": 949, "blended_grade": "US_NO_3"},
        )
