"""Mortality reporting: append-only event shape, sub-resource listing,
report gates, head reconciliation, and the auto-close cascade.
"""
from test_helpers import (
    ApiErrorId,
    assert_head_reconciliation_post_close,
    assert_head_reconciliation_pre_close,
    assert_mortality_report,
    assert_settlement_pay_invariants,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import create_mortality_report_payload
from test_helpers.fixtures import (
    FIELDTECH,
    create_barn,
    create_scheduled_group,
    get_barn,
    get_group,
    get_settlement_for_group,
    report_mortality,
    set_clock,
    setup_contract_with_barn,
    setup_placed_group,
)
from test_helpers.test_users import make_grower_headers


class TestReportShape:
    def test_mortality_report_append_only_shape(self, api):
        """PRD §2.5: "One entity is deliberately lighter: a mortality report is
        an immutable, append-only event and carries only `id` and `created_at`.
        Both `updated_at` and `version` are absent from mortality reports,
        because a report is never modified after creation."
        PRD §3.4: "Reports are immutable once filed and are listed, paginated,
        under their group."

        Design: Corner/entities/mortality_report_append_only_shape
        """
        ctx = setup_placed_group(head_placed=500)
        group_id = ctx["group"]["id"]
        report = report_mortality(
            group_id, ctx["grower"]["id"], "2026-03-05", 3, cull_count=1,
            reason_code="INJURY", clock="2026-03-05T00:00:00Z",
        )
        assert_mortality_report(report)
        assert report["report_date"] == "2026-03-05"
        assert report["mortality_count"] == 3
        assert report["cull_count"] == 1
        assert report["reason_code"] == "INJURY"

        data, meta = validate_paginated(
            api.list_mortality_reports(group_id, FIELDTECH)
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == report["id"]
        assert "updated_at" not in data[0]
        assert "version" not in data[0]

    def test_mortality_reports_subresource_listing(self, api):
        """PRD §3.4: "Reports are immutable once filed and are listed,
        paginated, under their group."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its
        resources sorted by creation timestamp in ascending order — oldest
        first."
        PRD §3.4: "The components are aggregations: `mortality_total` and
        `cull_total` sum the corresponding counts across all of the group's
        reports".

        Design: Corner/endpoints/mortality_reports_subresource_listing
        """
        ctx = setup_contract_with_barn(barn_code="B1")
        barn2 = create_barn(ctx["site"]["id"], barn_code="B2")
        g1 = create_scheduled_group(
            ctx["barn"]["id"], ctx["contract"]["id"], head_placed=500
        )
        g2 = create_scheduled_group(
            barn2["id"], ctx["contract"]["id"], head_placed=500
        )
        set_clock("2026-03-02T00:00:00Z")
        get_success_data(api.confirm_placement(g1["id"], {}, FIELDTECH))
        get_success_data(api.confirm_placement(g2["id"], {}, FIELDTECH))

        set_clock("2026-03-06T00:00:00Z")
        grower_id = ctx["grower"]["id"]
        report_mortality(g1["id"], grower_id, "2026-03-05", 2,
                         reason_code="OTHER")
        report_mortality(g1["id"], grower_id, "2026-03-06", 1, cull_count=2,
                         reason_code="OTHER")
        report_mortality(g2["id"], grower_id, "2026-03-06", 7,
                         reason_code="DISEASE")

        data, meta = validate_paginated(
            api.list_mortality_reports(g1["id"], FIELDTECH)
        )
        assert meta["total_count"] == 2
        assert data[0]["mortality_count"] == 2  # oldest first
        assert data[1]["mortality_count"] == 1
        assert all(r["group_id"] == g1["id"] for r in data)

        group1 = get_group(g1["id"])
        assert group1["mortality_total"] == 3
        assert group1["cull_total"] == 2
        assert group1["head_current"] == 495
        assert_head_reconciliation_pre_close(group1)


class TestReportGates:
    def test_empty_and_future_report_rejected(self, api):
        """PRD §3.4: "Each count must be zero or greater, and a report carrying
        zero deaths and zero culls is rejected with `ERR_EMPTY_REPORT`."
        PRD §3.4: "the `report_date` must fall within the group's life so far —
        on or after its `placement_date` and on or before the clock date
        (`ERR_REPORT_DATE_OUT_OF_RANGE`)."

        Design: Corner/errors/empty_and_future_report_rejected
        """
        ctx = setup_placed_group(head_placed=500)
        group_id = ctx["group"]["id"]
        grower_id = ctx["grower"]["id"]
        set_clock("2026-03-10T00:00:00Z")
        headers = make_grower_headers(grower_id)

        res = api.create_mortality_report(
            group_id,
            create_mortality_report_payload(
                report_date="2026-03-10", mortality_count=0, cull_count=0,
                reason_code="OTHER",
            ),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_EMPTY_REPORT, expected_status=409)

        # Dated after the clock (2026-03-11 > 2026-03-10).
        res = api.create_mortality_report(
            group_id,
            create_mortality_report_payload(
                report_date="2026-03-11", mortality_count=2, cull_count=0,
                reason_code="OTHER",
            ),
            headers,
        )
        validate_error(
            res, ApiErrorId.ERR_REPORT_DATE_OUT_OF_RANGE, expected_status=409
        )

        group = get_group(group_id)
        assert group["mortality_total"] == 0
        assert group["head_current"] == 500

    def test_head_count_exceeded_rejected(self, api):
        """PRD §3.4: "Any report whose new deaths and culls would push the
        accounted total — existing mortality, culls, and marketed head plus the
        report's `mortality_count` and `cull_count` — beyond `head_placed` is
        rejected with `ERR_HEAD_COUNT_EXCEEDED`."

        480 already dead + 30 new = 510 beyond 500 placed; the group is
        unchanged.

        Design: Corner/errors/head_count_exceeded_rejected
        """
        ctx = setup_placed_group(head_placed=500)
        group_id = ctx["group"]["id"]
        grower_id = ctx["grower"]["id"]
        report_mortality(group_id, grower_id, "2026-03-05", 480,
                         clock="2026-03-05T00:00:00Z")

        # Advance the clock to the report date so the temporal gate (§2.6
        # item 9) passes and the head-count quota gate (item 11) is the
        # first — and only — failing check.
        set_clock("2026-03-06T00:00:00Z")
        res = api.create_mortality_report(
            group_id,
            create_mortality_report_payload(
                report_date="2026-03-06", mortality_count=30, cull_count=0,
                reason_code="DISEASE",
            ),
            make_grower_headers(grower_id),
        )
        validate_error(res, ApiErrorId.ERR_HEAD_COUNT_EXCEEDED, expected_status=409)

        group = get_group(group_id)
        assert group["mortality_total"] == 480
        assert group["head_current"] == 20


class TestMortalityWipeoutCascade:
    def test_mortality_report_reaching_zero_head_auto_closes(self, api):
        """PRD §3.4: "Head accounting can close a group by itself. When
        applying a mortality report drives `head_current` to zero, the group
        closes automatically — see §3.8 for the full close-out cascade."
        PRD §3.4: "Any report whose new deaths and culls would push the
        accounted total — existing mortality, culls, and marketed head plus the
        report's `mortality_count` and `cull_count` — beyond `head_placed` is
        rejected with `ERR_HEAD_COUNT_EXCEEDED`." (beyond: equality survives)
        PRD §3.8: "Otherwise, if the group's `mortality_pct` is strictly
        greater than the contract's `mortality_threshold_pct`, the bonus is
        likewise zero; a mortality percentage exactly equal to the threshold
        survives the gate."
        PRD §3.8: "The `base_pay_cents` is `head_placed` times the contract's
        `base_pay_cents_per_head`."

        120 + 80 == 200 == head_placed is accepted and closes the group; the
        minted settlement carries the gated zero bonus.

        Design: Difficulty/transitive_cascade/cascade_mortality_wipeout_to_settlement
        """
        ctx = setup_placed_group(head_placed=200)
        group_id = ctx["group"]["id"]
        grower_id = ctx["grower"]["id"]
        report_mortality(group_id, grower_id, "2026-03-10", 120,
                         clock="2026-03-10T00:00:00Z")

        report_mortality(group_id, grower_id, "2026-03-20", 80,
                         clock="2026-03-20T00:00:00Z")

        group = get_group(group_id)
        assert group["mortality_total"] == 200
        assert group["mortality_pct"] == 100.0
        assert group["head_current"] == 0
        assert group["group_status"] == "CLOSED"
        assert_head_reconciliation_post_close(group)

        barn = get_barn(ctx["barn"]["id"])
        assert barn["barn_status"] == "WASH_REQUIRED"

        settlement = get_settlement_for_group(group_id)
        assert settlement["settlement_status"] == "FINALIZED"
        assert settlement["head_marketed"] == 0
        assert settlement["mortality_pct"] == 100.0
        assert settlement["bonus_cents"] == 0  # 100.0 strictly > 5.00 gate
        assert settlement["base_pay_cents"] == 200 * 4000
        assert settlement["total_pay_cents"] == 800000
        assert_settlement_pay_invariants(settlement)

    def test_report_one_over_head_placed_rejected_then_exact_close(self, api):
        """PRD §3.4: "Any report whose new deaths and culls would push the
        accounted total — existing mortality, culls, and marketed head plus the
        report's `mortality_count` and `cull_count` — beyond `head_placed` is
        rejected with `ERR_HEAD_COUNT_EXCEEDED`."

        The > (not >=) boundary: 120 + 81 = 201 beyond 200 is rejected; the
        group still accepts the exact 80 afterwards and closes.

        Design: Difficulty/transitive_cascade/cascade_mortality_wipeout_to_settlement
        """
        ctx = setup_placed_group(head_placed=200)
        group_id = ctx["group"]["id"]
        grower_id = ctx["grower"]["id"]
        report_mortality(group_id, grower_id, "2026-03-10", 120,
                         clock="2026-03-10T00:00:00Z")

        # Advance the clock to the report date so the temporal gate (§2.6
        # item 9) passes and the head-count quota gate (item 11) is the
        # first — and only — failing check.
        set_clock("2026-03-11T00:00:00Z")
        res = api.create_mortality_report(
            group_id,
            create_mortality_report_payload(
                report_date="2026-03-11", mortality_count=81, cull_count=0,
                reason_code="DISEASE",
            ),
            make_grower_headers(grower_id),
        )
        validate_error(res, ApiErrorId.ERR_HEAD_COUNT_EXCEEDED, expected_status=409)
        group = get_group(group_id)
        assert group["group_status"] == "PLACED"
        assert group["mortality_total"] == 120
        assert group["head_current"] == 80

        report_mortality(group_id, grower_id, "2026-03-12", 80,
                         clock="2026-03-12T00:00:00Z")
        group = get_group(group_id)
        assert group["group_status"] == "CLOSED"
        assert group["head_current"] == 0
