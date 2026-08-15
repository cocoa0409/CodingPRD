"""Intraday liquidity monitoring: chronological ordering, net position,
breach detection pipeline.

Corner instance: intraday_out_of_order_and_breach_detection.
"""
from test_helpers import (
    ApiErrorId,
    assert_intraday_snapshot,
    assert_limit_breach,
    assert_net_position_invariant,
    create_intraday_snapshot_payload,
    make_board_limit,
    make_officer_headers,
    make_ops_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = make_ops_headers("to_1")
OFFICER = make_officer_headers("ro_1")


class TestIntradaySnapshots:
    def test_intraday_out_of_order_and_breach_detection(self, api, ops_headers, officer_headers):
        """PRD §3.7: "The derived `net_position_cents` is the opening balance
        plus payments received minus payments sent. Ordering within a
        `business_date` bucket is strict: `snapshot_at` must be greater than
        every existing snapshot in that bucket, or the post is rejected with
        `ERR_SNAPSHOT_OUT_OF_ORDER`. Each accepted snapshot immediately runs
        detection against `INTRADAY_NET_POSITION` limits with `source_type`
        `INTRADAY_SNAPSHOT` and itself as `source_id`."

        Design: Corner/calculations/intraday_out_of_order_and_breach_detection
        """
        limit = make_board_limit(subject="INTRADAY_NET_POSITION",
                                 direction="BELOW_BREACHES",
                                 limit_value=-50_000_000, severity="BOARD")

        first = validate_success(api.post_intraday_snapshot(
            create_intraday_snapshot_payload(
                business_date="2026-08-01", snapshot_at="2026-08-01T09:00:00Z",
                opening_balance_cents=100_000_000, payments_received_cents=0,
                payments_sent_cents=20_000_000,
            ),
            ops_headers,
        ), expected_status=201)
        assert_intraday_snapshot(first)
        assert_net_position_invariant(first)
        assert first["net_position_cents"] == 80_000_000, (
            f"100000000 + 0 - 20000000 = 80000000, got {first['net_position_cents']}"
        )

        # 08:30 is earlier than the day's existing 09:00 snapshot.
        resp = api.post_intraday_snapshot(
            create_intraday_snapshot_payload(
                business_date="2026-08-01", snapshot_at="2026-08-01T08:30:00Z",
                opening_balance_cents=100_000_000, payments_received_cents=0,
                payments_sent_cents=10_000_000,
            ),
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_OUT_OF_ORDER)

        third = validate_success(api.post_intraday_snapshot(
            create_intraday_snapshot_payload(
                business_date="2026-08-01", snapshot_at="2026-08-01T12:00:00Z",
                opening_balance_cents=100_000_000, payments_received_cents=0,
                payments_sent_cents=200_000_000,
            ),
            ops_headers,
        ), expected_status=201)
        assert third["net_position_cents"] == -100_000_000

        # -100000000 < -50000000 breaches the BELOW limit.
        breaches, _meta = validate_paginated(api.list_limit_breaches(limit["id"], officer_headers))
        assert len(breaches) == 1, f"exactly one breach must be raised, got {len(breaches)}"
        breach = breaches[0]
        assert_limit_breach(breach)
        assert breach["detected_value"] == -100_000_000
        assert breach["source_type"] == "INTRADAY_SNAPSHOT"
        assert breach["source_id"] == third["id"], "source_id names the detecting snapshot"

        # The rejected 08:30 snapshot was not persisted.
        snapshots, meta = validate_paginated(
            api.list_intraday_snapshots(ops_headers, params={"business_date": "2026-08-01"})
        )
        assert len(snapshots) == 2, (
            f"only the two accepted snapshots persist, got {len(snapshots)}"
        )
        assert meta["total_count"] == 2
