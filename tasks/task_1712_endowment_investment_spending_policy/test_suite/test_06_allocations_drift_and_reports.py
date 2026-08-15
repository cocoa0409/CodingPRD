"""Target allocation replacement, drift bands, and annual-report publication gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_distribution,
    cancel_distribution,
    create_allocation_item,
    create_annual_report,
    create_distribution,
    create_engaged_manager,
    create_pool,
    file_manager_report,
    finalize_open_quarter,
    get_success_data,
    make_board_member_headers,
    propose_distribution,
    set_target_allocations,
    setup_funded_world,
    submit_report_review,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import bulk_upsert_allocations_payload


def test_allocation_targets_must_sum_to_exactly_10000(api):
    """PRD §3.9: 'Each `target_pct_bps` lies between 0 and 10000 inclusive, each
    `rebalance_band_bps` between 1 and 5000 inclusive, and the targets must sum to
    exactly 10000 basis points — both at replacement time and again at every
    finalize, failing as `ERR_ALLOCATION_SUM_INVALID`.'
    PRD §3.9: 'duplicates within `items` are rejected'
    PRD §2.9: 'the pair of `pool_id` and `asset_class` for allocations'

    Design: Corner/validations/allocation_targets_must_sum_to_exactly_10000
    """
    pool = create_pool(pool_name="Pool AS", inception_fiscal_year=2026)

    res1 = api.bulk_upsert_allocations(
        bulk_upsert_allocations_payload(pool["id"], [
            create_allocation_item("US_EQUITY", 5999, 500),
            create_allocation_item("CASH", 4000, 500),
        ]),
        TEST_USERS["admin_headers"],
    )
    validate_error(res1, ApiErrorId.ERR_ALLOCATION_SUM_INVALID, 422)

    rows, _ = validate_paginated(api.list_allocations(
        TEST_USERS["admin_headers"], params={"pool_id": pool["id"]},
    ))
    assert rows == [], "failed upsert must write nothing (atomic replacement)"

    res2 = api.bulk_upsert_allocations(
        bulk_upsert_allocations_payload(pool["id"], [
            create_allocation_item("US_EQUITY", 5000, 500),
            create_allocation_item("US_EQUITY", 5000, 500),
        ]),
        TEST_USERS["admin_headers"],
    )
    validate_error(res2, ApiErrorId.ERR_DUPLICATE_RECORD, 409)

    validate_success(api.bulk_upsert_allocations(
        bulk_upsert_allocations_payload(pool["id"], [
            create_allocation_item("US_EQUITY", 6000, 500),
            create_allocation_item("CASH", 4000, 500),
        ]),
        TEST_USERS["admin_headers"],
    ), 200)
    rows, meta = validate_paginated(api.list_allocations(
        TEST_USERS["admin_headers"], params={"pool_id": pool["id"]},
    ))
    assert len(rows) == 2


def test_bulk_upsert_replaces_the_allocation_set_atomically(api):
    """PRD §3.9: 'An `EndowmentAdmin` replaces the entire target set atomically by
    submitting `pool_id` and an `items` array whose elements each carry
    `asset_class`, `target_pct_bps`, and `rebalance_band_bps`.'
    PRD §3.9: 'rows absent from `items` are deleted, and matching rows are updated.'

    Design: Corner/endpoints/bulk_upsert_replaces_the_allocation_set_atomically
    """
    pool = create_pool(pool_name="Pool BU", inception_fiscal_year=2026)
    set_target_allocations(pool["id"], [
        create_allocation_item("US_EQUITY", 6000, 500),
        create_allocation_item("CASH", 4000, 500),
    ])

    validate_success(api.bulk_upsert_allocations(
        bulk_upsert_allocations_payload(pool["id"], [
            create_allocation_item("US_EQUITY", 10_000, 250),
        ]),
        TEST_USERS["admin_headers"],
    ), 200)

    rows, _ = validate_paginated(api.list_allocations(
        TEST_USERS["admin_headers"], params={"pool_id": pool["id"]},
    ))
    assert len(rows) == 1
    assert rows[0]["asset_class"] == "US_EQUITY"
    assert rows[0]["target_pct_bps"] == 10_000
    assert rows[0]["rebalance_band_bps"] == 250


def _allocation_for(api, pool_id, asset_class):
    rows, _ = validate_paginated(api.list_allocations(
        TEST_USERS["io_headers"],
        params={"pool_id": pool_id, "asset_class": asset_class},
    ))
    assert len(rows) == 1
    return rows[0]


def test_allocation_drift_equality_at_band_stays_in_band(api):
    """PRD §3.9: 'A row's `drift_status` becomes `BREACHED` when the absolute
    difference between `actual_pct_bps` and `target_pct_bps` is strictly greater than
    `rebalance_band_bps` — equality stays in band — and returns to `IN_BAND` when the
    difference is no greater than the band. Either flip resets `drift_acknowledged`
    to false.'

    Design: Corner/calculations/allocation_drift_equality_at_band_stays_in_band
    """
    pool = create_pool(pool_name="Pool DR", inception_fiscal_year=2026)
    set_target_allocations(pool["id"], [
        create_allocation_item("US_EQUITY", 5000, 500),
        create_allocation_item("FIXED_INCOME", 3000, 500),
        create_allocation_item("CASH", 2000, 500),
    ])
    mgr_us = create_engaged_manager(pool["id"], manager_name="M US", asset_class="US_EQUITY")
    mgr_fi = create_engaged_manager(pool["id"], manager_name="M FI", asset_class="FIXED_INCOME",
                                    benchmark_code="AGG")
    mgr_ca = create_engaged_manager(pool["id"], manager_name="M CA", asset_class="CASH",
                                    benchmark_code="T-BILL")

    # Q1: classes at exactly target +/- band -> equality stays in band.
    finalize_open_quarter(pool["id"], 10_000_000, reports=[
        {"manager_id": mgr_us["id"], "beginning_mv_cents": 0, "ending_mv_cents": 5_500_000,
         "flows": [{"day_offset": 0, "amount_cents": 5_500_000}]},
        {"manager_id": mgr_fi["id"], "beginning_mv_cents": 0, "ending_mv_cents": 3_000_000,
         "flows": [{"day_offset": 0, "amount_cents": 3_000_000}]},
        {"manager_id": mgr_ca["id"], "beginning_mv_cents": 0, "ending_mv_cents": 1_500_000,
         "flows": [{"day_offset": 0, "amount_cents": 1_500_000}]},
    ])

    us1 = _allocation_for(api, pool["id"], "US_EQUITY")
    assert us1["actual_pct_bps"] == 5500
    assert us1["drift_status"] == "IN_BAND"
    ca1 = _allocation_for(api, pool["id"], "CASH")
    assert ca1["actual_pct_bps"] == 1500
    assert ca1["drift_status"] == "IN_BAND"

    # Q2: US_EQUITY crosses the band (600 > 500); FIXED_INCOME pinned at target.
    finalize_open_quarter(pool["id"], 10_000_000, reports=[
        {"manager_id": mgr_us["id"], "beginning_mv_cents": 5_500_000, "ending_mv_cents": 5_600_000},
        {"manager_id": mgr_fi["id"], "beginning_mv_cents": 3_000_000, "ending_mv_cents": 3_000_000},
        {"manager_id": mgr_ca["id"], "beginning_mv_cents": 1_500_000, "ending_mv_cents": 1_400_000},
    ])

    us2 = _allocation_for(api, pool["id"], "US_EQUITY")
    assert us2["actual_pct_bps"] == 5600
    assert us2["drift_status"] == "BREACHED"
    assert us2["drift_acknowledged"] is False
    fi2 = _allocation_for(api, pool["id"], "FIXED_INCOME")
    assert fi2["actual_pct_bps"] == 3000
    assert fi2["drift_status"] == "IN_BAND"


def test_board_report_publish_blocked_until_drift_acknowledged(api):
    """PRD §3.11: 'for `BOARD_INVESTMENT` reports only, every allocation of the pool
    must be `IN_BAND` or have `drift_acknowledged` true, else
    `ERR_DRIFT_NOT_ACKNOWLEDGED`'
    PRD §3.9: 'A `BoardMember` may acknowledge a breached allocation, setting
    `drift_acknowledged` true, which is valid only while the row is `BREACHED`'

    Design: Corner/validations/board_report_publish_blocked_until_drift_acknowledged
    """
    pool = create_pool(pool_name="Pool DG", inception_fiscal_year=2026)
    set_target_allocations(pool["id"], [
        create_allocation_item("US_EQUITY", 5000, 500),
        create_allocation_item("CASH", 5000, 500),
    ])
    mgr_us = create_engaged_manager(pool["id"], manager_name="M US", asset_class="US_EQUITY")
    mgr_ca = create_engaged_manager(pool["id"], manager_name="M CA", asset_class="CASH",
                                    benchmark_code="T-BILL")

    def _quarter(quarter, us_begin, us_end, ca_begin, ca_end):
        reports = [
            {"manager_id": mgr_us["id"], "beginning_mv_cents": us_begin,
             "ending_mv_cents": us_end},
            {"manager_id": mgr_ca["id"], "beginning_mv_cents": ca_begin,
             "ending_mv_cents": ca_end},
        ]
        if quarter == 1:
            for r, amount in zip(reports, (us_end, ca_end)):
                r["flows"] = [{"day_offset": 0, "amount_cents": amount}]
        finalize_open_quarter(pool["id"], us_end + ca_end, reports=reports)

    _quarter(1, 0, 5_000_000, 0, 5_000_000)
    _quarter(2, 5_000_000, 5_000_000, 5_000_000, 5_000_000)
    _quarter(3, 5_000_000, 5_000_000, 5_000_000, 5_000_000)
    _quarter(4, 5_000_000, 6_000_000, 5_000_000, 4_000_000)

    us = _allocation_for(api, pool["id"], "US_EQUITY")
    assert us["drift_status"] == "BREACHED"
    ca = _allocation_for(api, pool["id"], "CASH")
    assert ca["drift_status"] == "BREACHED"

    report = create_annual_report(pool["id"], "BOARD_INVESTMENT", 2026,
                                  author_user_id="io-1", author_role="InvestmentOfficer")
    submit_report_review(report["id"], user_id="io-1", role="InvestmentOfficer")

    res1 = api.publish_report(report["id"], make_board_member_headers("bm-1"))
    validate_error(res1, ApiErrorId.ERR_DRIFT_NOT_ACKNOWLEDGED, 422)

    # Acknowledging only one of two breached rows does not clear the gate.
    validate_success(api.acknowledge_drift(us["id"], make_board_member_headers("bm-1")), 200)
    res2 = api.publish_report(report["id"], make_board_member_headers("bm-1"))
    validate_error(res2, ApiErrorId.ERR_DRIFT_NOT_ACKNOWLEDGED, 422)

    validate_success(api.acknowledge_drift(ca["id"], make_board_member_headers("bm-1")), 200)
    published = validate_success(api.publish_report(
        report["id"], make_board_member_headers("bm-1"),
    ), 200)
    assert published["report_status"] == "PUBLISHED"


def _setup_report_gated_world():
    """FY2026 complete (Q1-Q4 flat); the fund's FY2026 distribution left PROPOSED."""
    ctx = setup_funded_world(corpus_cents=10_000_000, pool_name="Pool RD",
                             with_policy=True)
    pool_id = ctx["pool"]["id"]
    manager_id = ctx["manager"]["id"]
    for quarter in (2, 3, 4):
        finalize_open_quarter(pool_id, 10_000_000, reports=[{
            "manager_id": manager_id, "beginning_mv_cents": 10_000_000,
            "ending_mv_cents": 10_000_000,
        }])
    distribution = create_distribution(ctx["fund"]["id"], 2026)
    ctx["distribution"] = propose_distribution(distribution["id"])
    report = create_annual_report(pool_id, "SPENDING_COMPLIANCE", 2026,
                                  author_user_id="dev-1")
    ctx["report"] = submit_report_review(report["id"], user_id="dev-1")
    return ctx


def test_report_publish_blocked_by_non_terminal_distribution(api):
    """PRD §3.11: 'every distribution in the report's scope for that fiscal year —
    the fund's distributions for `DONOR_FUND`, the whole pool's otherwise — must be
    in a terminal state, `DISTRIBUTED` or `CANCELLED`, else
    `ERR_INCOMPLETE_FISCAL_YEAR`'

    Design: Difficulty/cross_entity_state_dependency/report_publish_gated_by_distribution_terminality_report_distribution_pair
    """
    ctx = _setup_report_gated_world()

    res = api.publish_report(ctx["report"]["id"], make_board_member_headers("bm-1"))
    validate_error(res, ApiErrorId.ERR_INCOMPLETE_FISCAL_YEAR, 422)

    report = get_success_data(api.get_report(ctx["report"]["id"], TEST_USERS["io_headers"]))
    assert report["report_status"] == "UNDER_REVIEW"


def test_report_publish_unblocked_once_distribution_terminal(api):
    """PRD §3.11: 'every distribution in the report's scope for that fiscal year —
    the fund's distributions for `DONOR_FUND`, the whole pool's otherwise — must be
    in a terminal state, `DISTRIBUTED` or `CANCELLED`, else
    `ERR_INCOMPLETE_FISCAL_YEAR`'
    PRD §3.5: 'A `DevelopmentOfficer` may cancel a distribution in `PROJECTED`,
    `PROPOSED`, or `REVISION_REQUESTED`.'

    Design: Difficulty/cross_entity_state_dependency/report_publish_gated_by_distribution_terminality_report_distribution_pair
    """
    ctx = _setup_report_gated_world()

    res = api.publish_report(ctx["report"]["id"], make_board_member_headers("bm-1"))
    validate_error(res, ApiErrorId.ERR_INCOMPLETE_FISCAL_YEAR, 422)

    cancel_res = api.cancel_distribution(ctx["distribution"]["id"], TEST_USERS["dev_headers"])
    cancelled = validate_success(cancel_res, 200)
    assert cancelled["distribution_status"] == "CANCELLED"

    published = validate_success(api.publish_report(
        ctx["report"]["id"], make_board_member_headers("bm-1"),
    ), 200)
    assert published["report_status"] == "PUBLISHED"
