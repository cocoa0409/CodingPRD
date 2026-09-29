"""Expected-version guards on the two writes that move a ledger.

Filing a claim by hand and raising an upgrade order by hand are the only two
operations that accept an expected parent version, and in both cases a version
read one write too early must leave the ledger exactly where it was.
"""

from test_helpers import (
    CAPACITY_PLANNER_HEADERS,
    CAPACITY_PLANNER_USER_ID,
    VENDOR_MANAGER_HEADERS,
    ApiErrorId,
    assert_carrier_ledger,
    assert_credit_arithmetic,
    assert_page,
    assert_restoration_clocks,
    assert_upgrade_cost,
    build_nlc_single_gold,
    build_pft_capacity_circuit,
    count_claims_for_ticket,
    read_carrier,
    read_circuit,
    read_ticket,
    record_reading,
    restore_and_confirm,
    sla_credit_claim_payload,
    upgrade_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaleCarrierTicketVersionOnManualClaim:
    """A ticket closed without a breach still accepts a hand-filed NOC-clock claim."""

    def _closed_ticket_with_no_breach(self, api) -> dict:
        """Restore exactly on target, so the carrier clock produces no auto draft."""
        state = build_nlc_single_gold(
            api,
            "2026-09-02T00:00:00Z",
            ticket_reference="NLC-TT-90003",
            ticket_opened_at="2026-09-02T00:30:00Z",
        )
        confirmed = restore_and_confirm(
            api,
            state["ticket_id"],
            state["carrier_id"],
            state["alarm_id"],
            "2026-09-02T04:30:00Z",
            "2026-09-02T05:00:00Z",
        )
        state["ticket_version"] = confirmed["version"]
        assert_restoration_clocks(confirmed, carrier_clock=240.00, noc_clock=270.00)
        assert count_claims_for_ticket(api, state["ticket_id"]) == 0, (
            "the carrier met its target on its own clock, so nothing was drafted"
        )
        return state

    def _file_claim(self, api, ticket_id: str, expected_version: int):
        return api.create_sla_credit_claim(
            sla_credit_claim_payload(ticket_id, expected_version, basis="NOC_CLOCK"),
            VENDOR_MANAGER_HEADERS,
        )

    def test_a_version_one_behind_is_refused_and_moves_no_money(self, api):
        """Nothing about the ticket's state forbids the claim; only the version does.

        PRD 2.6: "A manual credit-claim create must carry `expected_carrier_ticket_version` holding the `version` of the carrier ticket the client last read. If that value does not equal the ticket's current `version` — because a carrier update, a restoration confirmation, a test result or an earlier claim create has advanced it since the client's read — the create is rejected with `ERR_STALE_CARRIER_TICKET_VERSION` (HTTP 412). The check is not a state guard: a manual claim legitimately supersedes a withdrawn automatic draft on the same ticket, so no ticket state forbids the operation, and the stale expected version is the only thing the server refuses. On success the ticket's `version` advances by 1."
        PRD 3.6: "When the computed amount is exactly zero — the carrier beat its target — no claim row is created at all."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_carrier_ticket_version_rejected_on_manual_claim
        """
        state = self._closed_ticket_with_no_breach(api)

        validate_error(
            self._file_claim(
                api, state["ticket_id"], state["ticket_version"] - 1
            ),
            ApiErrorId.ERR_STALE_CARRIER_TICKET_VERSION,
            412,
        )

        assert count_claims_for_ticket(api, state["ticket_id"]) == 0, (
            "the refused create left no claim row behind"
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=0,
            watchlist_state="ACTIVE",
        )
        assert read_ticket(api, state["ticket_id"])["version"] == state[
            "ticket_version"
        ], "a refused create must not advance the ticket's version"

    def test_the_current_version_files_the_noc_clock_claim(self, api):
        """Thirty minutes past target on the NOC clock is one breach hour and five percent.

        PRD 3.6: "Then the restoration figure is taken from the ticket according to the claim's `basis` — `restoration_minutes_carrier_clock` for `CARRIER_CLOCK`, `restoration_minutes_noc_clock` for `NOC_CLOCK`."
        PRD 3.6: "`breach_hours` is zero when `breach_minutes` is zero, and otherwise `breach_minutes` divided by 60 and rounded **up** to the next whole hour, so a breach of 61 minutes is two breach hours."
        PRD 3.6: "Such a claim is created with `origin` `MANUAL` in `DRAFT`, with `carrier_id` copied from the ticket, `submitted_by_user_id` and `submitted_at` null, `paid_amount_cents` and `rejection_reason` null, and `revision_count` 0."
        PRD 3.6: "Creation raises the carrier's exposure and re-evaluates `watchlist_state` exactly as the automatic draft does, and advances the ticket's `version` and the carrier's `version` by 1 each."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_carrier_ticket_version_rejected_on_manual_claim
        """
        state = self._closed_ticket_with_no_breach(api)
        validate_error(
            self._file_claim(api, state["ticket_id"], state["ticket_version"] - 1),
            ApiErrorId.ERR_STALE_CARRIER_TICKET_VERSION,
            412,
        )

        claim = validate_success(
            self._file_claim(api, state["ticket_id"], state["ticket_version"]), 201
        )["data"]

        assert claim["origin"] == "MANUAL", (
            f"a hand-filed claim is MANUAL, got {claim['origin']}"
        )
        assert claim["state"] == "DRAFT", (
            f"a hand-filed claim opens in DRAFT, got {claim['state']}"
        )
        assert claim["carrier_id"] == state["carrier_id"], (
            "the claim's carrier is copied from the ticket"
        )
        assert claim["revision_count"] == 0, "a fresh claim has never been revised"
        assert_credit_arithmetic(
            claim,
            basis="NOC_CLOCK",
            sla_target_minutes=240,
            breach_minutes=30.00,
            breach_hours=1,
            credit_amount_cents=46000,
        )

        assert read_ticket(api, state["ticket_id"])["version"] == state[
            "ticket_version"
        ] + 1, "the successful create advanced the ticket's expected-version field"
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]),
            exposure_cents=46000,
            watchlist_state="ACTIVE",
        )


class TestStaleCircuitVersionOnUpgradeOrder:
    """A telemetry sample arriving between the read and the write invalidates the read."""

    def _circuit_with_an_intervening_reading(self, api) -> dict:
        """Capture the version at registration, then let one reading move it."""
        state = build_pft_capacity_circuit(api, "2026-09-02T00:00:00Z")
        record_reading(api, state["circuit_id"], "2026-09-02T00:05:00Z", 60.00)
        return state

    def _raise_order(self, api, circuit_id: str, expected_version: int):
        return api.create_upgrade_order(
            upgrade_order_payload(circuit_id, 200, expected_version),
            CAPACITY_PLANNER_HEADERS,
        )

    def test_the_version_read_before_the_reading_is_refused(self, api):
        """No megabits are committed while the planner is working from a stale read.

        PRD 2.6: "An upgrade-order create must likewise carry `expected_circuit_version` holding the `version` of the target circuit as the client last read it, and a mismatch against the circuit's current `version` is rejected with `ERR_STALE_CIRCUIT_VERSION` (HTTP 412)."
        PRD 3.8: "Every reading advances the circuit's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_circuit_version_rejected_on_upgrade_order
        """
        state = self._circuit_with_an_intervening_reading(api)

        validate_error(
            self._raise_order(
                api, state["circuit_id"], state["circuit_version"]
            ),
            ApiErrorId.ERR_STALE_CIRCUIT_VERSION,
            412,
        )

        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), committed_mbps=0
        )
        _, meta = validate_paginated(
            api.list_circuit_upgrade_orders(
                state["circuit_id"], CAPACITY_PLANNER_HEADERS
            )
        )
        assert_page(meta, total_count=0)

        circuit = read_circuit(api, state["circuit_id"])
        assert circuit["version"] == state["circuit_version"] + 1, (
            f"the reading alone moved the version to "
            f"{state['circuit_version'] + 1}, got {circuit['version']}"
        )
        assert circuit["bandwidth_mbps"] == 100, (
            "the refused order changed no provisioned capacity"
        )

    def test_re_reading_the_circuit_lets_the_identical_order_through(self, api):
        """The retried create commits its megabits and moves the version once more.

        PRD 2.6: "Again the operation itself is not state-guarded — a manual order legitimately supersedes a cancelled automatic order on the same circuit — and on success the circuit's `version` advances by 1."
        PRD 3.8: "A manual order is created in `DRAFT` with `origin` `MANUAL` and `created_by_user_id` holding the acting `X-User-ID`, adds its `delta_mbps` to the carrier's `committed_upgrade_mbps`, and advances the circuit's `version` and the carrier's `version` by 1 each."
        PRD 3.8: "Second, `subtotal_cents` is 250000 plus `delta_mbps` multiplied by 900."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_circuit_version_rejected_on_upgrade_order
        """
        state = self._circuit_with_an_intervening_reading(api)
        validate_error(
            self._raise_order(api, state["circuit_id"], state["circuit_version"]),
            ApiErrorId.ERR_STALE_CIRCUIT_VERSION,
            412,
        )

        fresh_version = read_circuit(api, state["circuit_id"])["version"]
        order = validate_success(
            self._raise_order(api, state["circuit_id"], fresh_version), 201
        )["data"]

        assert order["state"] == "DRAFT", (
            f"a hand-raised order opens in DRAFT, got {order['state']}"
        )
        assert order["origin"] == "MANUAL", (
            f"a hand-raised order is MANUAL, got {order['origin']}"
        )
        assert order["created_by_user_id"] == CAPACITY_PLANNER_USER_ID, (
            "the raising planner is recorded on the order"
        )
        assert_upgrade_cost(
            order,
            delta_mbps=100,
            subtotal_cents=340000,
            expedite_fee_cents=0,
            total_cost_cents=340000,
        )

        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), committed_mbps=100
        )
        assert read_circuit(api, state["circuit_id"])["version"] == fresh_version + 1, (
            "the accepted create advanced the circuit's version one further"
        )
