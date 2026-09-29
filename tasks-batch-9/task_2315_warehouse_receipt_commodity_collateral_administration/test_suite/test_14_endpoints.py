"""
Endpoint-surface behaviour: what a single-resource read, an action route, a
computed read and each list family actually return.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_fields_equal,
    assert_instant_equals,
    assert_pagination_meta,
)
from test_helpers.constants import (
    BASE_STATE_CODE,
    CLOCK_BASE_UTC,
    CLOCK_STARTUP_UTC,
)
from test_helpers.test_users import (
    REGULATOR_HEADERS,
    REGULATOR_USER_ID,
    SECOND_REGULATOR_HEADERS,
    make_depositor_headers,
    make_warehouse_operator_headers,
)

CLOCK_DAY_16 = "2026-08-20T09:00:00Z"
CLOCK_INSOLVENCY_DAY = "2026-09-01T08:00:00Z"
APPOINTMENT_START = "2026-08-20T09:00:00Z"
APPOINTMENT_END = "2026-08-20T11:00:00Z"


class TestBinCollectionAndSingleReads:
    @pytest.fixture
    def two_bin_warehouse(self, licensed_warehouse, new_bin):
        """A licensed warehouse holding B1 (40000, commingling) and B8 (10000, not)."""
        warehouse = licensed_warehouse()
        first = new_bin(warehouse["id"])
        second = new_bin(
            warehouse["id"],
            bin_code="B8",
            capacity_bushels=10_000,
            commingling_allowed=False,
        )
        return {
            "warehouse_id": warehouse["id"],
            "bin_id": first["id"],
            "bin8_id": second["id"],
            "headers": make_warehouse_operator_headers(warehouse["id"]),
        }

    def test_the_second_bin_reads_back_with_its_own_configuration(
        self, api, two_bin_warehouse
    ):
        """
        B8 was created with half the declared capacity of B1 and with commingling
        switched off, and the single-resource read gives those two choices back
        untouched alongside the standard empty-bin opening position: sound, nothing
        stored, nothing available, and no dedication to any agreement.

        PRD: "An operator adds a bin to its own warehouse with a `bin_code` label
        unique within that warehouse, a `capacity_bushels` of at least one, the
        `commodity` the bin holds, a `commingling_allowed` flag marking it as a
        common-mass bin, and optionally a `dedicated_agreement_id`."

        PRD: "A new bin starts in `condition_state` `SOUND` with `stored_bushels`,
        `held_bushels`, `scheduled_inbound_bushels` and `cumulative_shrink_bushels`
        all at zero, `blended_grade` null, and `last_moisture_pct`,
        `last_temperature_f` and `last_assessed_at` all null until its first
        condition assessment."

        PRD: "Four derived quantities describe a bin's position at any instant:
        `stored_bushels` is the physical inventory actually on hand; `held_bushels`
        is the sum of `requested_bushels` across delivery orders drawn from this bin
        whose `delivery_state` is `REQUESTED` or `LOADED`; `available_bushels` is
        stored less held; and `scheduled_inbound_bushels` is the sum of
        `net_bushels` across tickets destined for this bin that are still merely
        `WEIGHED`."

        Design: Corner/endpoints/bin_crud_create_read_and_filtered_list
        """
        scenario = two_bin_warehouse

        storage_bin = get_success_data(
            api.get_bin(scenario["bin8_id"], scenario["headers"]), 200
        )

        assert_fields_equal(
            storage_bin,
            {
                "bin_code": "B8",
                "capacity_bushels": 10000,
                "commingling_allowed": False,
                "condition_state": "SOUND",
                "stored_bushels": 0,
                "available_bushels": 0,
                "dedicated_agreement_id": None,
            },
        )

        sibling = get_success_data(
            api.get_bin(scenario["bin_id"], scenario["headers"]), 200
        )
        assert sibling["dedicated_agreement_id"] is None

    def test_the_bin_list_answers_a_warehouse_and_condition_filter(
        self, api, two_bin_warehouse
    ):
        """
        Both bins of the warehouse are sound, so the collection read filtered on
        that warehouse and on condition_state SOUND returns the pair — a filter the
        list route is required to accept, answered with the standard paged envelope.

        PRD: "List endpoints accept the filters named in §2.3 and, where the
        resource supports them, the following optional query parameters: warehouses
        accept `state_code`, `license_program`, `license_state` and
        `insolvency_state`; parties accept `party_kind` and `state_code`; storage
        agreements accept `warehouse_id`, `depositor_party_id`, `agreement_state`
        and `storage_kind`; bins accept `warehouse_id`, `dedicated_agreement_id`,
        `condition_state` and `commodity`; deposit tickets accept
        `storage_agreement_id`, `bin_id` and `ticket_state`; receipts accept
        `warehouse_id`, `deposit_ticket_id`, `storage_agreement_id`, `bin_id`,
        `holder_party_id`, `registry_control_party_id`, `receipt_state`,
        `encumbrance_state`, `form` and `medium`; collateral liens accept
        `receipt_id`, `lender_party_id`, `pledgor_party_id`, `lien_state`,
        `valuation_basis` and `margin_status`; position reports accept
        `warehouse_id`, `report_state` and `examination_result`; delivery orders
        accept `receipt_id`, `requester_party_id` and `delivery_state`; and
        indemnity claims accept `warehouse_id`, `receipt_id`, `claimant_party_id`
        and `claim_state`."

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope described in §2.2."

        Design: Corner/endpoints/bin_crud_create_read_and_filtered_list
        """
        scenario = two_bin_warehouse

        rows, meta = validate_paginated(
            api.list_bins(
                {
                    "warehouse_id": scenario["warehouse_id"],
                    "condition_state": "SOUND",
                    "limit": 10,
                    "offset": 0,
                },
                REGULATOR_HEADERS,
            )
        )

        assert len(rows) == 2
        assert_pagination_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
        assert {row["id"] for row in rows} == {
            scenario["bin_id"],
            scenario["bin8_id"],
        }


class TestAcceptActionRoute:
    def test_one_accept_call_performs_the_whole_documented_side_effect_set(
        self, api, licensed_warehouse, new_producer, new_agreement, new_bin, weighed_ticket
    ):
        """
        A single call to the accept route moves four rows at once: the ticket is
        stamped and settled, the bin takes the 949 net bushels and the 11 shrink
        bushels while its soft reservation drops away,
        and the warehouse now owes 949 bushels — none of them receipted, because no
        receipt has been written.

        PRD: "Acceptance then sets `accepted_at` from the logical clock, moves the
        ticket to `ACCEPTED`, increments the bin's `version` by one, raises the
        bin's `stored_bushels` by the ticket's `net_bushels`, raises the bin's
        `cumulative_shrink_bushels` by the ticket's `shrink_bushels`, clears the
        ticket's scheduled-inbound reservation, recomputes the bin's
        `blended_grade`, and raises the warehouse's `obligation_bushels` and
        `system_physical_bushels` before recomputing the posture."

        PRD: "`receipted_obligation_bushels` is the first of those two sums alone,
        and it is the figure the licensed-capacity gate of §3.4 tests."

        Design: Corner/endpoints/accept_action_endpoint_transitions_ticket_and_bumps_bin_version
        """
        warehouse = licensed_warehouse()
        headers = make_warehouse_operator_headers(warehouse["id"])
        producer = new_producer()
        agreement = new_agreement(warehouse["id"], producer["id"])
        storage_bin = new_bin(warehouse["id"])
        ticket = weighed_ticket(warehouse["id"], agreement["id"], storage_bin["id"])
        before = get_success_data(api.get_bin(storage_bin["id"], headers), 200)

        accepted = get_success_data(
            api.accept_deposit_ticket(
                ticket["id"], f.accept_ticket_payload(before["version"]), headers
            ),
            200,
        )

        assert accepted["ticket_state"] == "ACCEPTED"
        assert_instant_equals(accepted["accepted_at"], CLOCK_BASE_UTC, "accepted_at")

        current_bin = get_success_data(api.get_bin(storage_bin["id"], headers), 200)
        assert_fields_equal(
            current_bin,
            {
                "stored_bushels": 949,
                "cumulative_shrink_bushels": 11,
                "scheduled_inbound_bushels": 0,
            },
        )

        current_warehouse = get_success_data(
            api.get_warehouse(warehouse["id"], headers), 200
        )
        assert_fields_equal(
            current_warehouse,
            {"obligation_bushels": 949, "receipted_obligation_bushels": 0},
        )


class TestPositionSummaryComputedRead:
    def test_unreceipted_stored_grain_counts_as_an_obligation(
        self, api, base_full, weighed_ticket, accept_ticket
    ):
        """
        Two lots sit in the same bin: 949 bushels behind receipt WR-0001 and a
        further 500 accepted but never receipted. The computed read is available on
        demand, and it separates the two ideas cleanly — all 1449 bushels are owed,
        only 949 of them are receipted, and since the physical count matches the
        obligation exactly the variance is nil against the 500-bushel floor.

        PRD: "All of these figures, plus `operational_posture`, are also available
        as a computed read on the warehouse recomputed at the current logical clock,
        which lets an operator check its own position before committing to a
        filing."

        PRD: "The **obligation** is what the warehouse owes: the sum of
        `quantity_bushels` across receipts in `receipt_state` `ISSUED`, plus the sum
        of `net_bushels` across deposit tickets in `ticket_state` `ACCEPTED`."

        PRD: "The **system physical** figure, `system_physical_bushels`, is the sum
        of `stored_bushels` across every bin of the warehouse, whatever each bin's
        condition."

        PRD: "The **sound physical** figure, `sound_physical_bushels`, is the same
        sum restricted to bins whose `condition_state` is `SOUND` or `WATCH`,
        excluding out-of-condition bins entirely."

        PRD: "`position_variance_bushels` is the sound physical figure less the
        obligation; a negative value means a shortage."

        PRD: "The tolerance against which all three are judged is
        `examination_tolerance_bushels`: the greater of a 500-bushel floor and 50
        basis points — one half of one percent — of the obligation, rounded half up
        to a whole bushel."

        PRD: "Otherwise the posture is `OPEN`."

        Design: Corner/endpoints/position_summary_computed_read_counts_accepted_ticket_and_issued_receipt
        """
        headers = base_full["operator_headers"]
        second = weighed_ticket(
            base_full["warehouse_id"],
            base_full["agreement_id"],
            base_full["bin_id"],
            gross_bushels=500,
            moisture_pct=13.0,
            dockage_pct=0.0,
            fill_start_at="2026-08-06T09:00:00Z",
            fill_end_at="2026-08-06T11:00:00Z",
        )
        assert second["net_bushels"] == 500
        accept_ticket(base_full["warehouse_id"], base_full["bin_id"], second["id"])

        get_success_data(
            api.get_position_summary(base_full["warehouse_id"], headers), 200
        )

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], headers), 200
        )
        assert_fields_equal(
            warehouse,
            {
                "obligation_bushels": 1449,
                "receipted_obligation_bushels": 949,
                "system_physical_bushels": 1449,
                "sound_physical_bushels": 1449,
                "position_variance_bushels": 0,
                "examination_tolerance_bushels": 500,
                "operational_posture": "OPEN",
            },
        )


class TestPossessionPerfectionOnAPaperReceipt:
    @pytest.fixture
    def paper_lien(self, api, base_pre, issue_receipt, set_clock, request_lien):
        """A POSSESSION advance requested against PAPER receipt WR-0004 on day 16."""
        receipt = issue_receipt(
            base_pre["warehouse_id"],
            base_pre["ticket_id"],
            base_pre["depositor_id"],
            receipt_number="WR-0004",
            medium="PAPER",
        )
        set_clock(CLOCK_DAY_16)
        lien = request_lien(
            receipt["id"],
            base_pre["lender_id"],
            perfection_method="POSSESSION",
        )
        return {"receipt_id": receipt["id"], "lien_id": lien["id"]}

    def test_possession_moves_the_holder_and_leaves_registry_control_null(
        self, api, base_pre, paper_lien
    ):
        """
        A paper receipt is perfected by handing it over, so the lender becomes the
        holder outright while the registry field — which only an electronic control
        arrangement touches — stays empty. The lifecycle dimension is untouched: the
        receipt is pledged, not spent.

        PRD: "Perfection re-runs the whole seven-step valuation at the current
        logical clock — which matters, because the provisional storage charge inside
        the warehouseman lien has grown since the request was recorded — then sets
        `perfected_at`, moves `lien_state` to `PERFECTED`, drives the receipt's
        `encumbrance_state` to `PLEDGED`, and raises the lender's
        `committed_advance_cents` by `advance_limit_cents`."

        PRD: "The two perfection methods differ in exactly which possession field
        moves: `POSSESSION` moves the receipt's `holder_party_id` to the lender and
        leaves `registry_control_party_id` null, while `ELECTRONIC_CONTROL` sets
        `registry_control_party_id` to the lender and leaves `holder_party_id`
        exactly where it was."

        Design: Corner/endpoints/possession_perfection_on_paper_receipt_moves_holder_to_lender
        """
        lien = get_success_data(
            api.perfect_lien(
                paper_lien["lien_id"], f.perfect_payload(), base_pre["lender_headers"]
            ),
            200,
        )

        assert lien["lien_state"] == "PERFECTED"
        assert_instant_equals(lien["perfected_at"], CLOCK_DAY_16, "perfected_at")

        receipt = get_success_data(
            api.get_receipt(paper_lien["receipt_id"], base_pre["operator_headers"]), 200
        )
        assert_fields_equal(
            receipt,
            {
                "encumbrance_state": "PLEDGED",
                "holder_party_id": base_pre["lender_id"],
                "registry_control_party_id": None,
                "receipt_state": "ISSUED",
            },
        )

    def test_the_advance_limit_is_charged_against_the_lenders_line(
        self, api, base_pre, paper_lien
    ):
        """
        Re-valued on day 16 the collateral supports 290482 cents at the
        seventy-percent tier, the principal of 250000 sits under that, and exactly
        the limit — not the principal — is what the lender's 50000000-cent line
        gives up.

        PRD: "`advance_rate_bps` is 8000 basis points (eighty percent) when
        `net_collateral_cents` is at least 10,000,000 cents — one hundred thousand
        dollars — and 7000 basis points (seventy percent) otherwise."

        PRD: "`advance_limit_cents` is `net_collateral_cents` multiplied by
        `advance_rate_bps` and divided by ten thousand, rounded half up to whole
        cents."

        PRD: "`margin_deficiency_cents` is the amount by which `principal_cents`
        exceeds that limit, floored at zero, and `margin_status` is `SUFFICIENT`
        when the deficiency is exactly zero and `DEFICIENT` otherwise."

        PRD: "`available_credit_cents` is `credit_line_cents` less that committed
        advance — the conserved quantity of the perfect-and-release pair described
        in §3.6."

        Design: Corner/endpoints/possession_perfection_on_paper_receipt_moves_holder_to_lender
        """
        lien = get_success_data(
            api.perfect_lien(
                paper_lien["lien_id"], f.perfect_payload(), base_pre["lender_headers"]
            ),
            200,
        )
        assert_fields_equal(
            lien, {"advance_limit_cents": 290482, "margin_status": "SUFFICIENT"}
        )

        lender = get_success_data(
            api.get_party(base_pre["lender_id"], base_pre["lender_headers"]), 200
        )
        assert_fields_equal(
            lender,
            {"committed_advance_cents": 290482, "available_credit_cents": 49709518},
        )


class TestPaperEndorsementTransfer:
    def test_an_endorsement_relinks_the_holder_and_appends_one_log_record(
        self, api, base_pre, issue_receipt, new_producer
    ):
        """
        The paper receipt is endorsed over by the party currently holding it, which
        is the only channel a paper receipt has. Afterwards the new producer is the
        holder and the log carries exactly one record naming the channel and both
        ends of the move — and because an endorsement is not a pledge, the
        collateral dimension has not budged.

        PRD: "A `PAPER` receipt is transferred by its current holder — acting as
        `Depositor` or `Lender` — with `transfer_channel` `ENDORSEMENT`."

        PRD: "A successful transfer moves `holder_party_id` to `to_party_id` and
        appends one record to `transfer_log` — an append-only, chronologically
        ordered array of objects each carrying `transfer_channel`, `from_party_id`,
        `to_party_id` and `effective_at`."

        Design: Corner/endpoints/paper_receipt_endorsement_appends_to_transfer_log
        """
        receipt = issue_receipt(
            base_pre["warehouse_id"],
            base_pre["ticket_id"],
            base_pre["depositor_id"],
            receipt_number="WR-0004",
            medium="PAPER",
        )
        transferee = new_producer(name="Bo Farms")

        transferred = get_success_data(
            api.transfer_receipt(
                receipt["id"],
                f.transfer_payload(transferee["id"], "ENDORSEMENT"),
                base_pre["depositor_headers"],
            ),
            200,
        )

        assert transferred["holder_party_id"] == transferee["id"]
        assert transferred["encumbrance_state"] == "UNENCUMBERED"
        assert len(transferred["transfer_log"]) == 1
        assert_fields_equal(
            transferred["transfer_log"][0],
            {
                "transfer_channel": "ENDORSEMENT",
                "from_party_id": base_pre["depositor_id"],
                "to_party_id": transferee["id"],
            },
        )


class TestLogicalClockDefault:
    def test_the_first_write_is_stamped_with_the_startup_default(self, api):
        """
        No clock call has been made at all, and the server must not reach for wall
        time to fill in the gap: the row it writes is stamped at the mandated
        startup instant on both of its system timestamps. Setting the clock
        afterwards moves where the next write lands, which is how every other
        scenario in this suite pins its instants.

        PRD: "Before the clock has ever been set it reads exactly
        `2026-08-01T00:00:00Z`; it must never fall back to real time."

        PRD: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional
        digits, recording when the row was first written."

        PRD: "`updated_at` (string): an ISO 8601 UTC timestamp in the same format,
        refreshed on every mutation of the row, including mutations caused by
        cascade rather than by a direct request against that row."

        Design: Corner/endpoints/logical_clock_defaults_to_startup_value_before_any_set_call
        """
        warehouse = get_success_data(
            api.create_warehouse(
                f.warehouse_payload(
                    name="Default Clock Elevator", operator_name="Default Grain Co"
                ),
                REGULATOR_HEADERS,
            ),
            201,
        )

        assert_instant_equals(warehouse["created_at"], CLOCK_STARTUP_UTC, "created_at")
        assert_instant_equals(warehouse["updated_at"], CLOCK_STARTUP_UTC, "updated_at")

        get_success_data(
            api.set_clock(f.clock_payload(CLOCK_BASE_UTC), REGULATOR_HEADERS), 200
        )
        party = get_success_data(
            api.create_party(f.producer_payload(), REGULATOR_HEADERS), 201
        )

        assert_instant_equals(party["created_at"], CLOCK_BASE_UTC, "created_at")


class TestDeliveryCancellation:
    def test_cancelling_returns_the_lane_for_the_very_next_booking(
        self, api, base_full, booked_delivery_order
    ):
        """
        The cancelled order gives up lane zero, and the proof that the lane was
        returned rather than leaked is that the next order for the identical
        appointment window is handed the same lane instead of being turned away for
        want of capacity.

        PRD: "An unloaded order may be cancelled by the depositor or the lender with
        an optional `cancellation_reason`, which moves it to `CANCELLED`, releases
        the held bushels back into the bin's `available_bushels`, frees its
        `lane_index`, and sets `cancelled_at`."

        PRD: "`lane_index` is assigned as the lowest integer from zero up to but
        excluding the warehouse's `loadout_lane_count` that no overlapping order
        already occupies; when every lane is taken, the booking is refused with
        `ERR_LOADOUT_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Corner/endpoints/delivery_cancel_frees_the_hold_and_the_loadout_lane
        """
        first = booked_delivery_order(
            base_full["depositor_id"],
            base_full["receipt_id"],
            400,
            APPOINTMENT_START,
            APPOINTMENT_END,
        )

        cancelled = get_success_data(
            api.cancel_delivery_order(
                first["id"],
                f.cancel_delivery_payload(cancellation_reason="DEPOSITOR_REQUEST"),
                base_full["depositor_headers"],
            ),
            200,
        )
        assert_fields_equal(
            cancelled,
            {
                "delivery_state": "CANCELLED",
                "cancellation_reason": "DEPOSITOR_REQUEST",
            },
        )
        assert_instant_equals(cancelled["cancelled_at"], CLOCK_BASE_UTC, "cancelled_at")

        replacement = booked_delivery_order(
            base_full["depositor_id"],
            base_full["receipt_id"],
            400,
            APPOINTMENT_START,
            APPOINTMENT_END,
        )
        assert_fields_equal(
            replacement, {"lane_index": 0, "delivery_state": "REQUESTED"}
        )

    def test_the_replacement_hold_is_the_only_one_the_bin_carries(
        self, api, base_full, booked_delivery_order
    ):
        """
        Only one of the two orders is live at the end, so the bin holds 400 bushels
        once — not twice — and 549 of its 949 remain available to promise to
        somebody else.

        PRD: "Booking raises the bin's `held_bushels` by `requested_bushels`, which
        is what keeps the same grain from being promised twice, and the order starts
        in `REQUESTED` with `delivered_bushels`, `delivered_grade`,
        `settlement_price_cents_per_bushel`, `loaded_at`, `settled_at`,
        `cancelled_at` and `cancellation_reason` all null."

        PRD: "`held_bushels` is the sum of `requested_bushels` across delivery
        orders drawn from this bin whose `delivery_state` is `REQUESTED` or
        `LOADED`; `available_bushels` is stored less held; and
        `scheduled_inbound_bushels` is the sum of `net_bushels` across tickets
        destined for this bin that are still merely `WEIGHED`."

        Design: Corner/endpoints/delivery_cancel_frees_the_hold_and_the_loadout_lane
        """
        first = booked_delivery_order(
            base_full["depositor_id"],
            base_full["receipt_id"],
            400,
            APPOINTMENT_START,
            APPOINTMENT_END,
        )
        get_success_data(
            api.cancel_delivery_order(
                first["id"],
                f.cancel_delivery_payload(cancellation_reason="DEPOSITOR_REQUEST"),
                base_full["depositor_headers"],
            ),
            200,
        )
        booked_delivery_order(
            base_full["depositor_id"],
            base_full["receipt_id"],
            400,
            APPOINTMENT_START,
            APPOINTMENT_END,
        )

        storage_bin = get_success_data(
            api.get_bin(base_full["bin_id"], base_full["operator_headers"]), 200
        )
        assert_fields_equal(
            storage_bin, {"held_bushels": 400, "available_bushels": 549}
        )


class TestCrossFamilyListReads:
    @pytest.fixture
    def populated_ledger(self, api, base_full, booked_delivery_order, request_lien):
        """One live row in each of the report, delivery-order and lien families."""
        report = get_success_data(
            api.create_position_report(
                f.position_report_payload(base_full["warehouse_id"]),
                base_full["operator_headers"],
            ),
            201,
        )
        order = booked_delivery_order(
            base_full["depositor_id"],
            base_full["receipt_id"],
            400,
            APPOINTMENT_START,
            APPOINTMENT_END,
        )
        lien = request_lien(base_full["receipt_id"], base_full["lender_id"])
        scenario = dict(base_full)
        scenario["report_id"] = report["id"]
        scenario["order_id"] = order["id"]
        scenario["lien_id"] = lien["id"]
        return scenario

    def test_each_list_family_answers_its_own_declared_filter_set(
        self, api, populated_ledger
    ):
        """
        Seven different collections, seven different filter vocabularies, one
        envelope: each read narrows to the single row that matches and reports it
        with the same limit, offset, total_count and has_more fields.

        PRD: "List endpoints accept the filters named in §2.3 and, where the
        resource supports them, the following optional query parameters: warehouses
        accept `state_code`, `license_program`, `license_state` and
        `insolvency_state`; parties accept `party_kind` and `state_code`; storage
        agreements accept `warehouse_id`, `depositor_party_id`, `agreement_state`
        and `storage_kind`; bins accept `warehouse_id`, `dedicated_agreement_id`,
        `condition_state` and `commodity`; deposit tickets accept
        `storage_agreement_id`, `bin_id` and `ticket_state`; receipts accept
        `warehouse_id`, `deposit_ticket_id`, `storage_agreement_id`, `bin_id`,
        `holder_party_id`, `registry_control_party_id`, `receipt_state`,
        `encumbrance_state`, `form` and `medium`; collateral liens accept
        `receipt_id`, `lender_party_id`, `pledgor_party_id`, `lien_state`,
        `valuation_basis` and `margin_status`; position reports accept
        `warehouse_id`, `report_state` and `examination_result`; delivery orders
        accept `receipt_id`, `requester_party_id` and `delivery_state`; and
        indemnity claims accept `warehouse_id`, `receipt_id`, `claimant_party_id`
        and `claim_state`."

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope described in §2.2."

        PRD: "`limit` caps the number of items returned; when omitted it defaults
        to 10, and a supplied value must be at least 1 and at most 100."

        Design: Corner/endpoints/cross_family_list_reads_filter_and_paginate_consistently
        """
        scenario = populated_ledger
        operator = scenario["operator_headers"]
        depositor = scenario["depositor_headers"]
        lender = scenario["lender_headers"]

        expectations = [
            (
                api.list_warehouses(
                    {
                        "state_code": BASE_STATE_CODE,
                        "license_state": "LICENSED",
                        "limit": 10,
                        "offset": 0,
                    },
                    REGULATOR_HEADERS,
                ),
                scenario["warehouse_id"],
                {"license_state": "LICENSED"},
            ),
            (
                api.list_parties({"party_kind": "LENDER"}, REGULATOR_HEADERS),
                scenario["lender_id"],
                {"party_kind": "LENDER"},
            ),
            (
                api.list_storage_agreements(
                    {
                        "warehouse_id": scenario["warehouse_id"],
                        "agreement_state": "ACTIVE",
                    },
                    operator,
                ),
                scenario["agreement_id"],
                {"agreement_state": "ACTIVE"},
            ),
            (
                api.list_receipts(
                    {
                        "holder_party_id": scenario["depositor_id"],
                        "receipt_state": "ISSUED",
                        "medium": "ELECTRONIC",
                    },
                    depositor,
                ),
                scenario["receipt_id"],
                {"receipt_number": "WR-0001"},
            ),
            (
                api.list_collateral_liens(
                    {
                        "lender_party_id": scenario["lender_id"],
                        "lien_state": "REQUESTED",
                    },
                    lender,
                ),
                scenario["lien_id"],
                {"lien_state": "REQUESTED"},
            ),
            (
                api.list_position_reports(
                    {
                        "warehouse_id": scenario["warehouse_id"],
                        "report_state": "DRAFT",
                    },
                    operator,
                ),
                scenario["report_id"],
                {"report_state": "DRAFT"},
            ),
            (
                api.list_delivery_orders(
                    {
                        "receipt_id": scenario["receipt_id"],
                        "delivery_state": "REQUESTED",
                    },
                    depositor,
                ),
                scenario["order_id"],
                {"requested_bushels": 400},
            ),
        ]

        for response, expected_id, expected_fields in expectations:
            rows, meta = validate_paginated(response)
            assert len(rows) == 1, f"Expected exactly one row, got {rows}"
            assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)
            assert rows[0]["id"] == expected_id
            assert_fields_equal(rows[0], expected_fields)

    def test_the_single_report_route_returns_one_object_rather_than_a_page(
        self, api, populated_ledger
    ):
        """
        The single-resource route is a different shape from its collection: it hands
        back the report itself, freshly opened in draft with no revisions recorded
        against it yet.

        PRD: "A new report starts in `DRAFT` with `revision_count` zero,
        `reported_physical_bushels` and `reported_obligation_bushels` null, every
        snapshot figure null, and `examination_result`, `examined_by_user_id`,
        `findings_note` and `submitted_at` all null."

        Design: Corner/endpoints/cross_family_list_reads_filter_and_paginate_consistently
        """
        report = get_success_data(
            api.get_position_report(
                populated_ledger["report_id"], SECOND_REGULATOR_HEADERS
            ),
            200,
        )

        assert_fields_equal(
            report,
            {
                "id": populated_ledger["report_id"],
                "report_state": "DRAFT",
                "revision_count": 0,
            },
        )

    def test_a_filter_that_matches_nothing_is_an_empty_page_not_a_not_found(
        self, api, populated_ledger
    ):
        """
        The one receipt in the system is issued, not voided, so filtering for voided
        receipts is a well-formed question with no answers — and a collection with
        no answers is an empty page, not a missing resource.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope described in §2.2."

        PRD: "The lifecycle dimension, `receipt_state`, starts at `ISSUED` and has
        two terminal states, `CANCELLED` and `VOIDED`."

        Design: Corner/endpoints/cross_family_list_reads_filter_and_paginate_consistently
        """
        rows, meta = validate_paginated(
            api.list_receipts(
                {
                    "holder_party_id": populated_ledger["depositor_id"],
                    "receipt_state": "VOIDED",
                },
                populated_ledger["depositor_headers"],
            )
        )

        assert rows == []
        assert_pagination_meta(meta, total_count=0, has_more=False)


class TestIndemnityClaimReads:
    @pytest.fixture
    def allowed_claim(
        self, api, base_full, set_clock, claims_open_warehouse, filed_claim
    ):
        """A producer's 400000-cent claim on WR-0001, allowed but not yet allocated."""
        set_clock(CLOCK_INSOLVENCY_DAY)
        claims_open_warehouse(base_full["warehouse_id"], 400)
        claim = filed_claim(
            base_full["warehouse_id"],
            base_full["receipt_id"],
            base_full["depositor_id"],
            400_000,
        )
        get_success_data(
            api.adjudicate_indemnity_claim(
                claim["id"],
                f.adjudicate_payload("ALLOW", adjudication_note="receipt verified"),
                REGULATOR_HEADERS,
            ),
            200,
        )
        return claim["id"]

    def test_the_allowed_claim_is_reachable_through_its_collection_filter(
        self, api, base_full, allowed_claim
    ):
        """
        Adjudication moved the claim out of FILED, so the claim-state filter on the
        collection finds it under ALLOWED — while the proceeding it belongs to is
        still taking claims.

        PRD: "It is admissible only while the claim is `FILED` and the warehouse is
        `CLAIMS_OPEN`, and it records `adjudicated_by_user_id`."

        PRD: "`OPEN_CLAIMS` then makes claim filing permitted for this warehouse and
        does nothing else."

        PRD: "List endpoints accept the filters named in §2.3 and, where the
        resource supports them, the following optional query parameters: warehouses
        accept `state_code`, `license_program`, `license_state` and
        `insolvency_state`; parties accept `party_kind` and `state_code`; storage
        agreements accept `warehouse_id`, `depositor_party_id`, `agreement_state`
        and `storage_kind`; bins accept `warehouse_id`, `dedicated_agreement_id`,
        `condition_state` and `commodity`; deposit tickets accept
        `storage_agreement_id`, `bin_id` and `ticket_state`; receipts accept
        `warehouse_id`, `deposit_ticket_id`, `storage_agreement_id`, `bin_id`,
        `holder_party_id`, `registry_control_party_id`, `receipt_state`,
        `encumbrance_state`, `form` and `medium`; collateral liens accept
        `receipt_id`, `lender_party_id`, `pledgor_party_id`, `lien_state`,
        `valuation_basis` and `margin_status`; position reports accept
        `warehouse_id`, `report_state` and `examination_result`; delivery orders
        accept `receipt_id`, `requester_party_id` and `delivery_state`; and
        indemnity claims accept `warehouse_id`, `receipt_id`, `claimant_party_id`
        and `claim_state`."

        Design: Corner/endpoints/indemnity_claim_reads_expose_the_adjudicated_entitlement
        """
        rows, meta = validate_paginated(
            api.list_indemnity_claims(
                {
                    "warehouse_id": base_full["warehouse_id"],
                    "claim_state": "ALLOWED",
                },
                REGULATOR_HEADERS,
            )
        )

        assert len(rows) == 1
        assert_pagination_meta(meta, total_count=1, has_more=False)
        assert rows[0]["id"] == allowed_claim
        assert rows[0]["claim_state"] == "ALLOWED"

        warehouse = get_success_data(
            api.get_warehouse(base_full["warehouse_id"], REGULATOR_HEADERS), 200
        )
        assert warehouse["insolvency_state"] == "CLAIMS_OPEN"

    def test_the_detail_read_shows_the_entitlement_with_no_shares_paid_yet(
        self, api, base_full, allowed_claim
    ):
        """
        The entitlement was fixed the moment the claim was allowed: 949 bushels at
        400 cents is 379600, less 9300 of provisional storage over the 28 inclusive
        days to the declaration and less the 5694 receiving charge, leaving 364606 —
        below the 400000 asserted, so that is what is allowed. The producer is fund
        eligible, but nothing has been distributed because allocation has not run.

        PRD: "`entitlement_cents` is the receipt's outstanding `quantity_bushels`
        valued at the warehouse's `insolvency_price_cents_per_bushel`, less the
        warehouseman's prior claim — which here is the `PROVISIONAL` storage accrual
        of §2.10 computed on that same outstanding quantity as of the date of
        `insolvency_declared_at`, plus the receipt's `receiving_charge_cents` — with
        the whole result floored at zero."

        PRD: "`allowed_cents` is the lesser of `claimed_cents` and
        `entitlement_cents`: a claimant can never recover more than it asserted, nor
        more than the grain was worth net of storage."

        PRD: "`fund_eligible` is set true only when the claimant party's
        `party_kind` is `PRODUCER_DEPOSITOR`; commercial depositors and lenders are
        not fund-eligible, which is the depositor-protection restriction at the
        heart of the scheme."

        PRD: "A new claim starts `FILED` with `entitlement_cents`, `allowed_cents`,
        `bond_share_cents`, `fund_share_cents` and `unpaid_cents` all zero or unset
        and `adjudicated_by_user_id` and `adjudication_note` null."

        Design: Corner/endpoints/indemnity_claim_reads_expose_the_adjudicated_entitlement
        """
        claim = get_success_data(
            api.get_indemnity_claim(
                allowed_claim, make_depositor_headers(base_full["depositor_id"])
            ),
            200,
        )

        assert_fields_equal(
            claim,
            {
                "id": allowed_claim,
                "entitlement_cents": 364606,
                "allowed_cents": 364606,
                "fund_eligible": True,
                "adjudicated_by_user_id": REGULATOR_USER_ID,
                "bond_share_cents": 0,
                "fund_share_cents": 0,
                "unpaid_cents": 0,
            },
        )
