"""Append-only records, market intelligence ordering, and the fixed startup
logical clock."""
import pytest
from test_helpers import (
    validate_success, validate_paginated,
    place_order,
    setup_listed_broker_owned_scenario,
    create_market_price_snapshot_payload,
    set_clock, post_snapshot,
    make_customer_headers,
    assert_escrow_entry, assert_instant_equals,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


class TestEscrowEntryShape:
    def test_deposit_entry_is_append_only_without_version(self, api):
        """PRD section 2.5: "Two resources deliberately break this pattern. A
        market price snapshot and an escrow entry are immutable records written
        once and never modified: each carries `id` and `created_at` only, and
        both `updated_at` and `version` are absent from their
        representations."
        PRD section 2.8: "`DEPOSIT` entries are positive and accumulate
        customer funds into escrow."

        Design: Corner/entities/escrow_entry_is_immutable_append_only
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="BC547", quantity=5, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=100000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        validate_success(
            api.deposit_escrow(
                order["id"], {"amount_cents": 2500},
                make_customer_headers(sc["customer"]["id"]),
            ),
            200,
        )
        entries, _ = validate_paginated(
            api.list_escrow_entries(order["id"], FINANCE)
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == "DEPOSIT"
        assert entry["amount_cents"] == 2500
        assert_escrow_entry(entry)


class TestSnapshotOrdering:
    def test_snapshots_returned_newest_first(self, api):
        """PRD section 3.4: "Snapshot history is queryable with an optional
        `mpn` filter and — as the platform's deliberate exception to the
        default sort — is returned newest first, ordered by `observed_at`
        descending with `created_at` descending as the tie-breaker."

        Design: Corner/endpoints/snapshot_list_sorted_observed_at_desc
        """
        set_clock("2026-08-02T00:00:00Z")
        post_snapshot("LM317T", 9000, source="TRADE_DESK")
        set_clock("2026-08-05T00:00:00Z")
        post_snapshot("LM317T", 9500, source="TRADE_DESK")

        data, _ = validate_paginated(
            api.list_market_price_snapshots(BROKER, params={"mpn": "LM317T"})
        )
        assert len(data) == 2
        assert data[0]["spot_price_cents"] == 9500, (
            "newest observation (2026-08-05) must come first"
        )
        # PRD pins the stamped instant (logical clock at record time), not the
        # string representation of the timestamp.
        assert_instant_equals(data[0]["observed_at"], "2026-08-05T00:00:00Z")
        assert data[1]["spot_price_cents"] == 9000
        assert_instant_equals(data[1]["observed_at"], "2026-08-02T00:00:00Z")


class TestLogicalClockDefault:
    def test_snapshot_observed_at_reads_startup_clock(self, api):
        """PRD section 2.4: "Every timestamp the server stamps onto a resource
        — `created_at`, `updated_at`, a lot's `received_at`, a snapshot's
        `observed_at` — reads a logical clock, never the wall clock. At
        startup, before any clock-control call has been made, the logical clock
        reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/cross_cutting_layers/default_clock_is_fixed_start_time
        """
        # No set_clock call: the clock must still read the startup instant.
        snapshot = validate_success(
            api.create_market_price_snapshot(
                create_market_price_snapshot_payload(
                    mpn="LM317T", spot_price_cents=9000, source="TRADE_DESK"
                ),
                BROKER,
            ),
            201,
        )
        # PRD 2.4 pins the startup instant exactly; the string representation
        # (fractional digits or not) is an implementation choice.
        assert_instant_equals(snapshot["observed_at"], "2026-08-01T00:00:00Z")
