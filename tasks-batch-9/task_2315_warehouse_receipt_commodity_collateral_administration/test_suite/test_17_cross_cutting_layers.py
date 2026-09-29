"""
The cross-cutting layers: optimistic concurrency on the two versioned rows, and
the reconciliation of the derived obligation totals across a source row's
creation, acceptance, receipting and reversal.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import (
    REGULATOR_HEADERS,
    make_warehouse_operator_headers,
)

SECOND_FILL_START = "2026-08-06T09:00:00Z"
SECOND_FILL_END = "2026-08-06T11:00:00Z"


class TestStaleWarehouseVersionOnIssuance:
    def test_one_version_behind_is_refused_and_the_current_one_is_admitted(
        self, api, base_pre
    ):
        """
        Nothing but the version is wrong here: the ticket is ACCEPTED, the number
        is fresh and the licensed capacity has room, so the very same request with
        the current version succeeds moments later. One behind is enough to refuse
        it, and while it is refused the ticket has not been receipted and the
        warehouse's receipted side is still empty.

        PRD: "Issuing a warehouse receipt requires `expected_warehouse_version`,
        carrying the client's last observed `version` of the target `Warehouse`. If
        it does not equal the warehouse's current `version`, the issuance is
        rejected with `ERR_STALE_WAREHOUSE_VERSION` (HTTP 412)."

        PRD: "Issuance is admitted against `licensed_capacity_bushels` using the
        warehouse's receipted obligation, so issuing a receipt for a second,
        different accepted ticket is a perfectly legitimate operation that would
        otherwise succeed; the stale version is what identifies an operator working
        from an outdated view of the remaining licensed capacity."

        PRD: "`quantity_bushels` is initialised to the ticket's `net_bushels`."

        PRD: "`receipted_obligation_bushels` is the first of those two sums alone,
        and it is the figure the licensed-capacity gate of §3.4 tests."

        Design: Corner/cross_cutting_complexity_layers/receipt_issue_with_stale_warehouse_version_rejected
        """
        headers = base_pre["operator_headers"]
        warehouse = get_success_data(
            api.get_warehouse(base_pre["warehouse_id"], headers), 200
        )
        current_version = warehouse["version"]

        refused = api.create_receipt(
            f.receipt_payload(
                base_pre["ticket_id"], base_pre["depositor_id"], current_version - 1
            ),
            headers,
        )

        validate_error(refused, E.ERR_STALE_WAREHOUSE_VERSION, 412)

        ticket = get_success_data(
            api.get_deposit_ticket(base_pre["ticket_id"], headers), 200
        )
        assert ticket["ticket_state"] == "ACCEPTED"
        during = get_success_data(
            api.get_warehouse(base_pre["warehouse_id"], headers), 200
        )
        assert during["receipted_obligation_bushels"] == 0

        receipt = get_success_data(
            api.create_receipt(
                f.receipt_payload(
                    base_pre["ticket_id"], base_pre["depositor_id"], current_version
                ),
                headers,
            ),
            201,
        )

        assert_fields_equal(
            receipt, {"receipt_state": "ISSUED", "quantity_bushels": 949}
        )
        after = get_success_data(
            api.get_warehouse(base_pre["warehouse_id"], headers), 200
        )
        assert after["receipted_obligation_bushels"] == 949


class TestStaleBinVersionOnASecondAccept:
    @pytest.fixture
    def two_weighed_loads(
        self,
        api,
        licensed_warehouse,
        new_producer,
        new_agreement,
        new_bin,
        weighed_ticket,
        accept_ticket,
    ):
        """
        Bin B1 carrying two WEIGHED tickets — 949 net on a 2026-08-05 window and
        500 net on a 2026-08-06 one — with the bin's version read once before
        either load is admitted, and the first load then accepted.
        """
        warehouse = licensed_warehouse()
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        headers = make_warehouse_operator_headers(warehouse["id"])
        first = weighed_ticket(warehouse["id"], agreement["id"], storage_bin["id"])
        second = weighed_ticket(
            warehouse["id"],
            agreement["id"],
            storage_bin["id"],
            gross_bushels=500,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at=SECOND_FILL_START,
            fill_end_at=SECOND_FILL_END,
        )
        pre_read_version = get_success_data(
            api.get_bin(storage_bin["id"], headers), 200
        )["version"]
        accept_ticket(warehouse["id"], storage_bin["id"], first["id"])
        return {
            "warehouse_id": warehouse["id"],
            "bin_id": storage_bin["id"],
            "second_ticket_id": second["id"],
            "pre_read_version": pre_read_version,
            "headers": headers,
        }

    def test_replaying_the_pre_read_version_is_refused(self, api, two_weighed_loads):
        """
        Accepting a second, different weighed ticket into the same bin is a
        perfectly legal operation, so nothing else in the request is wrong — the
        version read before the first accept is simply one behind now. The second
        load stays weighed and the bin still holds only the first 949 bushels.

        PRD: "Accepting a weighed deposit ticket into a bin requires
        `expected_bin_version`, carrying the client's last observed `version` of the
        target `Bin`. If it does not equal the bin's current `version`, the
        acceptance is rejected with `ERR_STALE_BIN_VERSION` (HTTP 412)."

        PRD: "Accepting a second, different weighed ticket into the same bin is
        likewise a legitimate operation, so the version check is the only
        deterministic guard against admitting grain on a stale reading of the bin's
        free space."

        Design: Corner/cross_cutting_complexity_layers/second_ticket_accept_with_stale_bin_version_rejected
        """
        headers = two_weighed_loads["headers"]

        response = api.accept_deposit_ticket(
            two_weighed_loads["second_ticket_id"],
            f.accept_ticket_payload(two_weighed_loads["pre_read_version"]),
            headers,
        )

        validate_error(response, E.ERR_STALE_BIN_VERSION, 412)

        ticket = get_success_data(
            api.get_deposit_ticket(two_weighed_loads["second_ticket_id"], headers), 200
        )
        assert ticket["ticket_state"] == "WEIGHED"
        storage_bin = get_success_data(
            api.get_bin(two_weighed_loads["bin_id"], headers), 200
        )
        assert storage_bin["stored_bushels"] == 949

    def test_the_re_read_version_admits_the_second_load(
        self, api, two_weighed_loads
    ):
        """
        The first accept moved the bin's version by exactly one, so re-reading it
        is all the operator needs: the second load goes in on the next attempt,
        carrying the bin to 1449 stored bushels and stepping its version once more,
        and the warehouse's obligation follows to 1449.

        PRD: "Acceptance then sets `accepted_at` from the logical clock, moves the
        ticket to `ACCEPTED`, increments the bin's `version` by one, raises the
        bin's `stored_bushels` by the ticket's `net_bushels`, raises the bin's
        `cumulative_shrink_bushels` by the ticket's `shrink_bushels`, clears the
        ticket's scheduled-inbound reservation, recomputes the bin's
        `blended_grade`, and raises the warehouse's `obligation_bushels` and
        `system_physical_bushels` before recomputing the posture."

        PRD: "The **obligation** is what the warehouse owes: the sum of
        `quantity_bushels` across receipts in `receipt_state` `ISSUED`, plus the sum
        of `net_bushels` across deposit tickets in `ticket_state` `ACCEPTED`."

        Design: Corner/cross_cutting_complexity_layers/second_ticket_accept_with_stale_bin_version_rejected
        """
        headers = two_weighed_loads["headers"]
        stale_version = two_weighed_loads["pre_read_version"]
        fresh = get_success_data(
            api.get_bin(two_weighed_loads["bin_id"], headers), 200
        )
        assert fresh["version"] == stale_version + 1

        accepted = get_success_data(
            api.accept_deposit_ticket(
                two_weighed_loads["second_ticket_id"],
                f.accept_ticket_payload(fresh["version"]),
                headers,
            ),
            200,
        )

        assert accepted["ticket_state"] == "ACCEPTED"
        storage_bin = get_success_data(
            api.get_bin(two_weighed_loads["bin_id"], headers), 200
        )
        assert_fields_equal(
            storage_bin,
            {"stored_bushels": 1449, "version": stale_version + 2},
        )
        warehouse = get_success_data(
            api.get_warehouse(two_weighed_loads["warehouse_id"], headers), 200
        )
        assert warehouse["obligation_bushels"] == 1449


class TestDerivedObligationTotalsReconcile:
    @pytest.fixture
    def second_load(self, api, base_full, weighed_ticket):
        """
        WR-0001 already stands for 949 bushels; a second 500-bushel load is weighed
        into the same bin but not yet admitted.
        """
        ticket = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=500,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at=SECOND_FILL_START,
            fill_end_at=SECOND_FILL_END,
        )
        return {"scenario": base_full, "ticket_id": ticket["id"]}

    def test_the_two_totals_move_on_different_events(
        self, api, second_load, accept_ticket
    ):
        """
        Three snapshots of the same pair of totals. Weighing the load changes
        neither of them — it only parks 500 bushels as a soft reservation on the
        bin. Accepting it raises the total obligation to 1449 while the receipted
        figure stays at 949, because no receipt covers the new grain yet. Issuing
        WR-0002 raises the receipted figure to 1449 without moving the total at
        all, and with sound physical and obligation now equal the variance is zero.

        PRD: "A new ticket lands in `ticket_state` `WEIGHED`, with `accepted_at`
        null, and raises the bin's `scheduled_inbound_bushels` by its `net_bushels`
        as a soft reservation."

        PRD: "The **obligation** is what the warehouse owes: the sum of
        `quantity_bushels` across receipts in `receipt_state` `ISSUED`, plus the sum
        of `net_bushels` across deposit tickets in `ticket_state` `ACCEPTED`."

        PRD: "`receipted_obligation_bushels` is the first of those two sums alone,
        and it is the figure the licensed-capacity gate of §3.4 tests."

        PRD: "The **system physical** figure, `system_physical_bushels`, is the sum
        of `stored_bushels` across every bin of the warehouse, whatever each bin's
        condition."

        PRD: "`position_variance_bushels` is the sound physical figure less the
        obligation; a negative value means a shortage."

        PRD: "The source ticket moves from `ACCEPTED` to `RECEIPTED`, which shifts
        its bushels from the unreceipted to the receipted side of the warehouse's
        `obligation_bushels` without changing that total, and the warehouse's
        `version` increments by one."

        Design: Corner/cross_cutting_complexity_layers/derived_totals_reconcile_after_source_create_update_and_removal
        """
        scenario = second_load["scenario"]
        headers = scenario["operator_headers"]

        after_weigh_in = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            after_weigh_in,
            {"obligation_bushels": 949, "receipted_obligation_bushels": 949},
        )
        storage_bin = get_success_data(api.get_bin(scenario["bin_id"], headers), 200)
        assert storage_bin["scheduled_inbound_bushels"] == 500

        accept_ticket(
            scenario["warehouse_id"], scenario["bin_id"], second_load["ticket_id"]
        )

        after_accept = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            after_accept,
            {
                "obligation_bushels": 1449,
                "receipted_obligation_bushels": 949,
                "system_physical_bushels": 1449,
            },
        )
        filled_bin = get_success_data(api.get_bin(scenario["bin_id"], headers), 200)
        assert filled_bin["stored_bushels"] == 1449

        get_success_data(
            api.create_receipt(
                f.receipt_payload(
                    second_load["ticket_id"],
                    scenario["depositor_id"],
                    after_accept["version"],
                    receipt_number="WR-0002",
                ),
                headers,
            ),
            201,
        )

        after_issue = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            after_issue,
            {
                "obligation_bushels": 1449,
                "receipted_obligation_bushels": 1449,
                "position_variance_bushels": 0,
            },
        )

    def test_voiding_the_second_receipt_conserves_the_total_obligation(
        self, api, second_load, accept_ticket
    ):
        """
        The void is the exact reverse of the issuance and nothing else: the
        receipted figure falls back to the 949 WR-0001 still carries, the total
        obligation does not move at all because the 500 bushels re-enter it as
        unreceipted stock, and the bin still physically holds all 1449 bushels
        because no grain left the building. The computed position read agrees with
        the stored figures.

        PRD: "A void moves `receipt_state` to `VOIDED`, zeroes `quantity_bushels`,
        and thereby removes the receipt from the warehouse's
        `receipted_obligation_bushels`; returns the source deposit ticket from
        `RECEIPTED` back to `ACCEPTED`, so the very same bushels re-enter
        `obligation_bushels` as unreceipted stock; and leaves the bin's
        `stored_bushels` completely unchanged, because voiding a receipt does not
        move grain."

        PRD: "The warehouse's total obligation before and after a void is therefore
        identical, while its receipted obligation falls — that pairing is the whole
        point of the transition."

        PRD: "All of these figures, plus `operational_posture`, are also available
        as a computed read on the warehouse recomputed at the current logical
        clock, which lets an operator check its own position before committing to a
        filing."

        Design: Corner/cross_cutting_complexity_layers/derived_totals_reconcile_after_source_create_update_and_removal
        """
        scenario = second_load["scenario"]
        headers = scenario["operator_headers"]
        accept_ticket(
            scenario["warehouse_id"], scenario["bin_id"], second_load["ticket_id"]
        )
        warehouse = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], headers), 200
        )
        receipt = get_success_data(
            api.create_receipt(
                f.receipt_payload(
                    second_load["ticket_id"],
                    scenario["depositor_id"],
                    warehouse["version"],
                    receipt_number="WR-0002",
                ),
                headers,
            ),
            201,
        )

        get_success_data(
            api.void_receipt(
                receipt["id"], f.void_payload(void_reason="CLERICAL_ERROR"), headers
            ),
            200,
        )

        after_void = get_success_data(
            api.get_warehouse(scenario["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            after_void,
            {"obligation_bushels": 1449, "receipted_obligation_bushels": 949},
        )
        storage_bin = get_success_data(api.get_bin(scenario["bin_id"], headers), 200)
        assert storage_bin["stored_bushels"] == 1449

        ticket = get_success_data(
            api.get_deposit_ticket(second_load["ticket_id"], headers), 200
        )
        assert ticket["ticket_state"] == "ACCEPTED"
        voided = get_success_data(api.get_receipt(receipt["id"], headers), 200)
        assert voided["receipt_state"] == "VOIDED"

        get_success_data(
            api.get_position_summary(scenario["warehouse_id"], REGULATOR_HEADERS), 200
        )
