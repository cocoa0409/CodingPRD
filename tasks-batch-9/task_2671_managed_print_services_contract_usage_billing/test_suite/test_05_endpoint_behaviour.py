"""Endpoint behaviour: computed reads, cross-reference writes, bulk runs, actions and CRUD.

Each suite exercises one endpoint shape end to end — what it computes, what it
refuses, and what the neighbouring read endpoints then report.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_fields,
    assert_lines_sum_to_usage_subtotal,
    assert_version_incremented,
    create_contract,
    create_device,
    create_quarterly_review,
    create_site,
    create_technician,
    fetch_billing_period,
    fetch_device,
    fetch_part_stock,
    fetch_statement_lines,
    get_success_data,
    list_reads_for_device,
    make_account_manager_headers,
    quarterly_review_payload,
    refresh_replacement_payload,
    run_sweep,
    set_clock,
    setup_closed_period_with_final_statement,
    setup_print_environment,
    spare_part_stock_payload,
    submit_automated_read,
    technician_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A single unbounded monochrome band, so the selected rate never depends on volume.
FLAT_MONO_TIERS = ((1, 1, None, 9_375),)

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
MID_PERIOD_CLOCK = "2026-08-20T00:00:00Z"
COVERAGE_END = "2026-08-20T00:00:00Z"

# Duty cycle and assessment chosen so realized utilization lands exactly on the
# inclusive 90 percent upgrade boundary: 4,500 pages against a 5,000 page cycle.
UPGRADE_DEVICE = {
    "model_code": "XR-M2100",
    "rated_monthly_duty_cycle": 5_000,
    "assessed_monthly_mono_pages": 4_500,
    "assessed_monthly_color_pages": 0,
    "baseline_cost_micro_dollars_per_page": 21_000,
    "baseline_overhead_cents_per_month": 4_500,
}


def _two_device_fleet_with_a_closed_period():
    """Two monochrome devices, one accepted reading each, then a swept and closed period."""
    return setup_closed_period_with_final_statement(
        mono_tiers=FLAT_MONO_TIERS,
        devices=2,
        period=(PERIOD_START, PERIOD_END),
        read_clock=MID_PERIOD_CLOCK,
        close_clock=PERIOD_END,
        reads=(
            {"device_index": 0, "mono_meter": 4_000, "coverage_end": COVERAGE_END},
            {"device_index": 1, "mono_meter": 2_000, "coverage_end": COVERAGE_END},
        ),
    )


class TestStatementLinesReconcileToTheStatementTotals:
    """The lines sub-resource is a computed read that must add back up to its parent."""

    def test_each_priced_meter_emits_one_line_that_sums_to_the_usage_subtotal(self):
        """Two monochrome lines, each rounded to whole cents, summing to the subtotal.

        PRD: "Each `StatementLine` records its parent `statement_id`, the
        `device_id` it prices, the `page_class`, the `pages` it covers, the
        `rate_micro_dollars_per_page` copied from the statement's selected rate for
        that class, and an `amount_cents` computed as the pages multiplied by that
        rate, divided by 10,000, and rounded half up to a whole cent."
        PRD: "The statement's `usage_subtotal_cents` is then the sum of the emitted
        lines' `amount_cents`."
        PRD: "The order is pinned: **round each line to whole cents first, then sum
        the lines**."
        PRD: "`total_cents` is the `usage_subtotal_cents` plus `shortfall_cents`
        plus `service_labor_cents` plus `waste_penalty_cents`, **minus**
        `sla_credit_cents`."

        Design: Corner/endpoints/computed_read_statement_lines_reconcile_to_the_statement_totals
        """
        env = _two_device_fleet_with_a_closed_period()
        statement = env["statement"]
        d1, d2 = env["device_ids"]

        lines = fetch_statement_lines(statement["id"])

        assert len(lines) == 2, f"expected 2 statement lines, got {len(lines)}: {lines}"
        expected = [(d1, 4_000, 3_750), (d2, 2_000, 1_875)]
        for line, (device_id, pages, amount_cents) in zip(lines, expected):
            assert_fields(
                line,
                statement_id=statement["id"],
                device_id=device_id,
                page_class="MONO",
                pages=pages,
                rate_micro_dollars_per_page=9_375,
                amount_cents=amount_cents,
            )
        assert_fields(
            statement,
            mono_pages_billed=6_000,
            color_pages_billed=0,
            usage_subtotal_cents=5_625,
            shortfall_cents=0,
            waste_penalty_cents=0,
            sla_credit_cents=0,
            total_cents=5_625,
        )
        assert_lines_sum_to_usage_subtotal(lines, statement)

    def test_the_line_views_filter_by_page_class_and_never_leave_their_parent(self, api,
                                                                             billing_analyst_headers):
        """A colour filter empties the listing; the per-device view returns only that device's line.

        PRD: "A line is emitted only when the device's billable pages for that
        meter are greater than zero; a zero-page meter produces no line at all."
        PRD: "Statement listings accept `billing_period_id` and `variant`;
        statement-line listings and the per-device statement-line listing accept
        `page_class`."
        PRD: "They read the child collection filtered to the parent named in the
        path and never create or modify anything."

        Design: Corner/endpoints/computed_read_statement_lines_reconcile_to_the_statement_totals
        """
        env = _two_device_fleet_with_a_closed_period()
        statement_id = env["statement"]["id"]
        d1, d2 = env["device_ids"]

        mono_lines, mono_meta = validate_paginated(
            api.list_statement_lines(statement_id, billing_analyst_headers,
                                     params={"page_class": "MONO"})
        )
        color_lines, color_meta = validate_paginated(
            api.list_statement_lines(statement_id, billing_analyst_headers,
                                     params={"page_class": "COLOR"})
        )
        device_lines, device_meta = validate_paginated(
            api.list_device_statement_lines(d2, billing_analyst_headers)
        )

        assert mono_meta["total_count"] == 2, f"expected 2 MONO lines, meta was {mono_meta}"
        assert len(mono_lines) == 2, f"expected 2 MONO lines, got {mono_lines}"
        assert color_meta["total_count"] == 0, f"expected no COLOR lines, meta was {color_meta}"
        assert color_lines == [], f"expected no COLOR lines, got {color_lines}"
        assert device_meta["total_count"] == 1, f"expected 1 line for {d2}, meta was {device_meta}"
        assert_fields(device_lines[0], device_id=d2, pages=2_000, amount_cents=1_875)
        assert [line["device_id"] for line in fetch_statement_lines(statement_id)] == [d1, d2]


def _site_with_an_empty_parts_locker():
    """A contract and one site, with nothing yet in the site's parts locker."""
    contract = create_contract()
    site = create_site(contract["id"])
    return contract["id"], site["id"]


class TestSparePartStockUpsertsThenRefusesToGoNegative:
    """The locker endpoint is an upsert keyed on site and SKU, floored at zero."""

    def test_adjusting_an_existing_row_moves_the_quantity_and_bumps_the_version(self, api,
                                                                               fleet_ops_headers):
        """A second call on the same SKU shifts the same row rather than making another.

        PRD: "A `FleetOpsController` creates or adjusts a locker row by naming a
        `part_sku` and a signed `qty_delta`; the row for that site and SKU is
        created when it does not yet exist, and `on_hand_qty` moves by the supplied
        delta."
        PRD: "On success the locker row's `version` increases by 1."
        PRD: "Alongside `on_hand_qty`, each locker row exposes a derived
        `reserved_qty`: the number of service tickets that name the same `part_sku`,
        target a device at the same `site_id`, and are still in flight with a
        `status` of `DISPATCHED`, `PARTS_HOLD` or `ONSITE`."

        Design: Corner/endpoints/cross_reference_link_spare_part_stock_upserts_then_refuses_to_go_negative
        """
        _, site_id = _site_with_an_empty_parts_locker()
        created = get_success_data(
            api.adjust_spare_part_stock(site_id, spare_part_stock_payload("FUSER-9", 2),
                                        fleet_ops_headers)
        )
        assert_fields(created, site_id=site_id, part_sku="FUSER-9", on_hand_qty=2,
                      reserved_qty=0, version=1)

        adjusted = validate_success(
            api.adjust_spare_part_stock(site_id, spare_part_stock_payload("FUSER-9", -1),
                                        fleet_ops_headers),
            200,
        )

        assert adjusted["id"] == created["id"], (
            "the second adjustment must reuse the existing locker row: "
            f"{adjusted['id']} vs {created['id']}"
        )
        assert_fields(adjusted, part_sku="FUSER-9", on_hand_qty=1, reserved_qty=0, version=2)
        assert_fields(fetch_part_stock(site_id, "FUSER-9"), on_hand_qty=1, version=2)

    @pytest.mark.parametrize("qty_delta", [0, -2])
    def test_a_zero_or_overdrawing_delta_leaves_the_row_untouched(self, api, fleet_ops_headers,
                                                                 qty_delta):
        """A meaningless zero and an overdraw both report the same underflow code.

        PRD: "A `qty_delta` of exactly zero is meaningless and is rejected, as is
        any negative delta that would drive `on_hand_qty` below zero — an absent row
        counts as a current quantity of zero — and both cases report
        `ERR_PART_STOCK_UNDERFLOW`."
        PRD: "A stock adjustment must supply a non-zero `qty_delta`, and the
        resulting `on_hand_qty` for that site and SKU must be at least zero,
        treating an absent row as a current quantity of zero — otherwise
        `ERR_PART_STOCK_UNDERFLOW` (409)."

        Design: Corner/endpoints/cross_reference_link_spare_part_stock_upserts_then_refuses_to_go_negative
        """
        _, site_id = _site_with_an_empty_parts_locker()
        get_success_data(
            api.adjust_spare_part_stock(site_id, spare_part_stock_payload("FUSER-9", 1),
                                        fleet_ops_headers)
        )

        response = api.adjust_spare_part_stock(
            site_id, spare_part_stock_payload("FUSER-9", qty_delta), fleet_ops_headers
        )

        validate_error(response, ApiErrorId.ERR_PART_STOCK_UNDERFLOW.value, 409)
        assert_fields(fetch_part_stock(site_id, "FUSER-9"), on_hand_qty=1, version=1)

    def test_a_negative_delta_against_an_absent_row_creates_nothing(self, api, fleet_ops_headers):
        """An absent row counts as zero, so a debit against it never brings a row into being.

        PRD: "A `qty_delta` of exactly zero is meaningless and is rejected, as is
        any negative delta that would drive `on_hand_qty` below zero — an absent row
        counts as a current quantity of zero — and both cases report
        `ERR_PART_STOCK_UNDERFLOW`."

        Design: Corner/endpoints/cross_reference_link_spare_part_stock_upserts_then_refuses_to_go_negative
        """
        _, site_id = _site_with_an_empty_parts_locker()

        response = api.adjust_spare_part_stock(
            site_id, spare_part_stock_payload("DRUM-4", -1), fleet_ops_headers
        )

        validate_error(response, ApiErrorId.ERR_PART_STOCK_UNDERFLOW.value, 409)
        assert fetch_part_stock(site_id, "DRUM-4") is None, (
            "a refused adjustment must not leave a locker row behind"
        )

    def test_an_unknown_site_in_the_path_reports_site_not_found(self, api, fleet_ops_headers):
        """The parent identifier is resolved before the adjustment is considered at all.

        PRD: "Every failure of this kind carries HTTP 404 with the code specific to
        the missing resource type: `ERR_CONTRACT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
        `ERR_DEVICE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
        `ERR_METER_READ_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
        `ERR_STATEMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND` or `ERR_REMOVAL_ORDER_NOT_FOUND`."

        Design: Corner/endpoints/cross_reference_link_spare_part_stock_upserts_then_refuses_to_go_negative
        """
        _site_with_an_empty_parts_locker()

        response = api.adjust_spare_part_stock(
            NON_EXISTENT_UUID, spare_part_stock_payload("FUSER-9", 5), fleet_ops_headers
        )

        validate_error(response, ApiErrorId.ERR_SITE_NOT_FOUND.value, 404)

    def test_the_locker_listing_reads_only_its_own_site_and_honours_the_sku_filter(
        self, api, fleet_ops_headers
    ):
        """Two SKUs in one locker, and a SKU filter that narrows the reverse lookup to one.

        PRD: "They read the child collection filtered to the parent named in the
        path and never create or modify anything."
        PRD: "Every one of these filters is optional; when omitted, no restriction
        is applied on that dimension."

        Design: Corner/endpoints/cross_reference_link_spare_part_stock_upserts_then_refuses_to_go_negative
        """
        contract_id, site_id = _site_with_an_empty_parts_locker()
        other_site = create_site(contract_id, name="Plant 2")
        for part_sku in ("FUSER-9", "DRUM-4"):
            get_success_data(
                api.adjust_spare_part_stock(site_id, spare_part_stock_payload(part_sku, 3),
                                            fleet_ops_headers)
            )
        get_success_data(
            api.adjust_spare_part_stock(other_site["id"], spare_part_stock_payload("FUSER-9", 7),
                                        fleet_ops_headers)
        )

        all_rows, all_meta = validate_paginated(
            api.list_spare_part_stocks(site_id, fleet_ops_headers)
        )
        filtered_rows, filtered_meta = validate_paginated(
            api.list_spare_part_stocks(site_id, fleet_ops_headers, params={"part_sku": "DRUM-4"})
        )

        assert all_meta["total_count"] == 2, f"expected 2 locker rows, meta was {all_meta}"
        assert {row["part_sku"] for row in all_rows} == {"FUSER-9", "DRUM-4"}, all_rows
        assert all(row["site_id"] == site_id for row in all_rows), all_rows
        assert filtered_meta["total_count"] == 1, f"expected 1 filtered row, meta was {filtered_meta}"
        assert_fields(filtered_rows[0], part_sku="DRUM-4", on_hand_qty=3)


SWEEP_CLOCK = "2026-08-25T00:00:00Z"


def _assert_instant(actual, expected_prefix, field):
    """A timestamp field must carry the given instant, whatever its fractional form."""
    assert isinstance(actual, str) and actual.startswith(expected_prefix), (
        f"expected {field} at {expected_prefix}, got {actual!r}"
    )


def _fleet_with_one_silent_device():
    """Two active devices; only the first has reported a reading for the period."""
    env = setup_print_environment(
        mono_tiers=FLAT_MONO_TIERS,
        devices=2,
        period=(PERIOD_START, PERIOD_END),
        clock=MID_PERIOD_CLOCK,
    )
    env["read"] = submit_automated_read(
        env["device_ids"][0],
        env["period_id"],
        mono_meter=3_000,
        coverage_start=PERIOD_START,
        coverage_end=COVERAGE_END,
    )
    set_clock(SWEEP_CLOCK)
    return env


class TestMeterSweepSkipsReadDevicesAndNeverDuplicatesEstimates:
    """The bulk sweep run: one placeholder per silent device, and idempotent per device."""

    def test_the_sweep_manufactures_a_placeholder_only_for_the_silent_device(self, api,
                                                                            fleet_ops_headers):
        """The reporting device is left alone; the silent one gets one offline exception.

        PRD: "The sweep walks every device of the contract whose `lifecycle_state`
        is `ACTIVE` or `SERVICE_HOLD` and which has no `ACCEPTED` reading whose
        `coverage_end` falls inside the period window, and manufactures one
        placeholder reading per such device: `source` `SWEEP_ESTIMATE`, `status`
        `EXCEPTION`, `exception_reason` `DEVICE_OFFLINE`, `mono_meter` and
        `color_meter` copied from the device's current watermarks, `toner_level_pct`
        copied from the device's current level, `coverage_start` set to the period's
        `period_start` and `coverage_end` set to the logical clock value at sweep
        time."
        PRD: "Each such placeholder pushes the device's derived
        `offline_exception_count` up and the period's `exception_open_count` up."
        PRD: "The period then moves `OPEN → SWEPT` (or `SWEPT → SWEPT` on a
        re-run), its `sweep_run_count` increases by 1 and its `version` increments."
        PRD: "A reading that is not `ACCEPTED` carries a `mono_delta` and a
        `color_delta` of exactly 0 and moves no device counter whatsoever."

        Design: Corner/endpoints/bulk_action_meter_sweep_skips_read_devices_and_never_duplicates_estimates
        """
        env = _fleet_with_one_silent_device()
        reporting_device, silent_device = env["device_ids"]
        version_before_sweep = fetch_billing_period(env["period_id"])["version"]

        period = validate_success(api.run_meter_sweep(env["period_id"], fleet_ops_headers), 200)

        assert_fields(period, status="SWEPT", sweep_run_count=1, exception_open_count=1)
        assert_version_incremented(period["version"], version_before_sweep)
        placeholders = list_reads_for_device(silent_device)
        assert len(placeholders) == 1, f"expected one placeholder read, got {placeholders}"
        assert_fields(
            placeholders[0],
            device_id=silent_device,
            billing_period_id=env["period_id"],
            source="SWEEP_ESTIMATE",
            status="EXCEPTION",
            exception_reason="DEVICE_OFFLINE",
            mono_meter=0,
            color_meter=0,
            toner_level_pct=100,
            mono_delta=0,
            color_delta=0,
        )
        _assert_instant(placeholders[0]["coverage_start"], "2026-08-01T00:00:00", "coverage_start")
        _assert_instant(placeholders[0]["coverage_end"], "2026-08-25T00:00:00", "coverage_end")
        assert_fields(
            fetch_device(silent_device),
            offline_exception_count=1,
            last_accepted_mono_meter=0,
            lifetime_mono_pages=0,
            toner_level_pct=100,
        )
        reporting_reads = list_reads_for_device(reporting_device)
        assert len(reporting_reads) == 1, f"the reporting device must be skipped: {reporting_reads}"
        assert_fields(reporting_reads[0], source="AUTOMATED", status="ACCEPTED", mono_delta=3_000)
        assert_fields(fetch_device(reporting_device), offline_exception_count=0,
                      lifetime_mono_pages=3_000)

    def test_a_second_sweep_run_counts_again_without_duplicating_the_placeholder(
        self, api, fleet_ops_headers
    ):
        """Re-running the sweep advances the counter but leaves the estimate set alone.

        PRD: "Two edges matter: when every eligible device already has an accepted
        reading the sweep creates zero placeholders yet **still** advances the period
        to `SWEPT` and **still** increments `sweep_run_count`; and on a re-run,
        devices that already hold a `SWEEP_ESTIMATE` reading in `EXCEPTION` for that
        period are skipped rather than given a duplicate."
        PRD: "Each such placeholder pushes the device's derived
        `offline_exception_count` up and the period's `exception_open_count` up."

        Design: Corner/endpoints/bulk_action_meter_sweep_skips_read_devices_and_never_duplicates_estimates
        """
        env = _fleet_with_one_silent_device()
        silent_device = env["device_ids"][1]
        run_sweep(env["period_id"])

        period = validate_success(api.run_meter_sweep(env["period_id"], fleet_ops_headers), 200)

        assert_fields(period, status="SWEPT", sweep_run_count=2, exception_open_count=1)
        period_reads, period_meta = validate_paginated(
            api.list_meter_reads(fleet_ops_headers, params={"billing_period_id": env["period_id"]})
        )
        assert period_meta["total_count"] == 2, (
            f"the re-run must not add a reading, meta was {period_meta}"
        )
        assert len(period_reads) == 2, period_reads
        estimates, estimate_meta = validate_paginated(
            api.list_meter_reads(
                fleet_ops_headers,
                params={"device_id": silent_device, "source": "SWEEP_ESTIMATE"},
            )
        )
        assert estimate_meta["total_count"] == 1, (
            f"the silent device must hold exactly one estimate, meta was {estimate_meta}"
        )
        assert len(estimates) == 1, estimates
        assert_fields(fetch_device(silent_device), offline_exception_count=1)


def _closed_period_fleet_at_the_upgrade_boundary():
    """One device whose realized pages sit exactly on the 90 percent upgrade boundary."""
    return setup_closed_period_with_final_statement(
        mono_tiers=FLAT_MONO_TIERS,
        devices=[dict(UPGRADE_DEVICE)],
        period=(PERIOD_START, PERIOD_END),
        read_clock=MID_PERIOD_CLOCK,
        close_clock=PERIOD_END,
        reads=({"mono_meter": 4_500, "coverage_end": COVERAGE_END},),
    )


class TestReviewApprovalPublishesRefreshDueOntoTheFleet:
    """The approve action is what turns a computed recommendation into a fleet flag."""

    def test_creation_computes_the_upgrade_recommendation_without_publishing_it(self, api):
        """The draft already knows the device should be upgraded, but the device does not.

        PRD: "The classification writes `right_sizing_action` on the device and is
        evaluated in this order: utilization at or below 15 percent yields
        `CONSOLIDATE`; otherwise utilization at or below 40 percent yields
        `DOWNGRADE`; otherwise utilization at or above 90 percent yields `UPGRADE`;
        otherwise the device yields `RETAIN`."
        PRD: "The review then records the four tallies across the fleet in
        `retain_count`, `downgrade_count`, `upgrade_count` and `consolidate_count`,
        and records `refresh_due_device_count` as the sum of `upgrade_count` and
        `consolidate_count` — the devices a refresh plan should touch."
        PRD: "The new review has `status` `DRAFT`, an `authored_by_user_id` stamped
        from the caller's `X-User-ID`, and a null `approved_by_user_id`."

        Design: Corner/endpoints/action_endpoint_review_approval_publishes_refresh_due_onto_the_fleet
        """
        env = _closed_period_fleet_at_the_upgrade_boundary()
        assert env["statement"]["total_cents"] == 4_219, env["statement"]

        review = validate_success(
            api.create_quarterly_review(
                quarterly_review_payload(env["contract_id"], "2026-Q3"),
                make_account_manager_headers("am-1"),
            ),
            201,
        )

        assert_fields(
            review,
            status="DRAFT",
            authored_by_user_id="am-1",
            approved_by_user_id=None,
            upgrade_count=1,
            retain_count=0,
            downgrade_count=0,
            consolidate_count=0,
            refresh_due_device_count=1,
            baseline_savings_cents=9_731,
            realized_savings_cents=9_731,
            version=1,
        )
        assert_fields(fetch_device(env["device_id"]), right_sizing_action="UPGRADE",
                      refresh_due=False, replaced_by_device_id=None)

    def test_approval_stamps_the_second_manager_and_flips_refresh_due_on_the_fleet(self, api,
                                                                                  account_manager_headers):
        """A different account manager approves, and the upgrade device becomes refresh due.

        PRD: "A second `AccountManager` — necessarily a different `X-User-ID` from
        the review's `authored_by_user_id`, or the request is rejected with
        `ERR_SEGREGATION_OF_DUTIES` — approves the review, driving `DRAFT →
        APPROVED`, stamping `approved_by_user_id` with the acting `X-User-ID`, and
        incrementing the review's `version`."
        PRD: "Approval cascades onto the fleet: every device of the contract whose
        `right_sizing_action` is `UPGRADE` or `CONSOLIDATE` has `refresh_due` set to
        true and its own `version` incremented."
        PRD: "Creating a new resource returns HTTP 201; every other successful
        operation, including all state transitions, all reads and all list queries,
        returns HTTP 200."

        Design: Corner/endpoints/action_endpoint_review_approval_publishes_refresh_due_onto_the_fleet
        """
        env = _closed_period_fleet_at_the_upgrade_boundary()
        review = create_quarterly_review(env["contract_id"], user_id="am-1")
        device_version_before = fetch_device(env["device_id"])["version"]

        approved = validate_success(
            api.approve_quarterly_review(review["id"], make_account_manager_headers("am-2")), 200
        )

        assert_fields(
            approved,
            status="APPROVED",
            authored_by_user_id="am-1",
            approved_by_user_id="am-2",
            version=2,
        )
        device = fetch_device(env["device_id"])
        assert_fields(device, right_sizing_action="UPGRADE", refresh_due=True)
        assert_version_incremented(device["version"], device_version_before)
        approved_reviews, meta = validate_paginated(
            api.list_contract_quarterly_reviews(
                env["contract_id"], account_manager_headers, params={"status": "APPROVED"}
            )
        )
        assert meta["total_count"] == 1, f"expected one approved review, meta was {meta}"
        assert_fields(approved_reviews[0], id=review["id"], status="APPROVED")


def _published_refresh_flag_with_a_successor_asset():
    """An approved review has flagged the fleet device, and a spare asset stands ready."""
    env = _closed_period_fleet_at_the_upgrade_boundary()
    review = create_quarterly_review(env["contract_id"], user_id="am-1")
    get_success_data(
        api_client.approve_quarterly_review(review["id"], make_account_manager_headers("am-2"))
    )
    successor = create_device(env["contract_id"], env["site_id"], asset_tag="MPS-0002")
    env["review"] = review
    env["successor_id"] = successor["id"]
    return env


class TestRefreshLinkageRequiresAnApprovedRefreshDueFlag:
    """The conditional linkage action, allowed exactly once and only on a flagged asset."""

    def test_linkage_writes_the_successor_onto_the_flagged_asset(self, api,
                                                                account_manager_headers):
        """The superseded asset records its replacement; the successor is not disturbed.

        PRD: "Later in the contract's life, once a quarterly review has flagged an
        asset as due for refresh, an `AccountManager` links it to its replacement by
        supplying a `successor_device_id`, which is written onto the superseded asset
        as `replaced_by_device_id` and increments its `version`."
        PRD: "A freshly recorded asset lands at `lifecycle_state` `ASSESSED` and
        `supply_state` `SUPPLY_OK`, with `toner_level_pct` at 100."
        PRD: "Device listings accept `contract_id`, `site_id`,
        `replaced_by_device_id`, `removal_order_id`, `lifecycle_state` and
        `supply_state`."

        Design: Corner/endpoints/conditional_action_refresh_linkage_requires_an_approved_refresh_due_flag
        """
        env = _published_refresh_flag_with_a_successor_asset()
        superseded_id, successor_id = env["device_id"], env["successor_id"]
        version_before = fetch_device(superseded_id)["version"]

        linked = validate_success(
            api.link_refresh_replacement(
                superseded_id, refresh_replacement_payload(successor_id), account_manager_headers
            ),
            200,
        )

        assert_fields(linked, id=superseded_id, replaced_by_device_id=successor_id,
                      refresh_due=True, right_sizing_action="UPGRADE")
        assert_version_incremented(linked["version"], version_before)
        assert_fields(fetch_device(successor_id), lifecycle_state="ASSESSED",
                      supply_state="SUPPLY_OK", toner_level_pct=100,
                      right_sizing_action="NONE", refresh_due=False,
                      replaced_by_device_id=None)
        linked_devices, meta = validate_paginated(
            api.list_devices(account_manager_headers,
                             params={"replaced_by_device_id": successor_id})
        )
        assert meta["total_count"] == 1, f"expected one superseded device, meta was {meta}"
        assert_fields(linked_devices[0], id=superseded_id)

    def test_a_second_linkage_on_the_same_asset_is_refused(self, api, account_manager_headers):
        """Once `replaced_by_device_id` is set, the asset can never be relinked.

        PRD: "The linkage is tightly guarded: the asset named in the path must carry
        `refresh_due` true and must not already carry a non-null
        `replaced_by_device_id`, and the successor must belong to the same contract,
        must have a `lifecycle_state` of `ASSESSED`, `PLACED`, `NETWORKED` or
        `ACTIVE`, and must not be the same asset as the one being replaced."
        PRD: "Any of those failures reports `ERR_DEVICE_NOT_REFRESH_DUE`; a
        `successor_device_id` naming nothing at all reports `ERR_DEVICE_NOT_FOUND`
        instead."

        Design: Corner/endpoints/conditional_action_refresh_linkage_requires_an_approved_refresh_due_flag
        """
        env = _published_refresh_flag_with_a_successor_asset()
        superseded_id, successor_id = env["device_id"], env["successor_id"]
        get_success_data(
            api_client.link_refresh_replacement(
                superseded_id, refresh_replacement_payload(successor_id), account_manager_headers
            )
        )
        spare = create_device(env["contract_id"], env["site_id"], asset_tag="MPS-0003")

        response = api.link_refresh_replacement(
            superseded_id, refresh_replacement_payload(spare["id"]), account_manager_headers
        )

        validate_error(response, ApiErrorId.ERR_DEVICE_NOT_REFRESH_DUE.value, 409)
        assert_fields(fetch_device(superseded_id), replaced_by_device_id=successor_id)

    @pytest.mark.parametrize("case", ["path_asset_not_flagged", "successor_is_the_path_asset"])
    def test_the_guard_rejects_an_unflagged_path_asset_and_a_self_link(
        self, api, account_manager_headers, case
    ):
        """An unflagged asset and a device pointed at itself both report the same code.

        PRD: "The device named in the path must carry `refresh_due` true and a null
        `replaced_by_device_id`, and the successor device must belong to the same
        contract, have a `lifecycle_state` of `ASSESSED`, `PLACED`, `NETWORKED` or
        `ACTIVE`, and not be the path device itself — otherwise
        `ERR_DEVICE_NOT_REFRESH_DUE` (409)."

        Design: Corner/endpoints/conditional_action_refresh_linkage_requires_an_approved_refresh_due_flag
        """
        env = _published_refresh_flag_with_a_successor_asset()
        flagged_id, successor_id = env["device_id"], env["successor_id"]
        if case == "path_asset_not_flagged":
            path_id, payload_id = successor_id, flagged_id
        else:
            path_id, payload_id = flagged_id, flagged_id

        response = api.link_refresh_replacement(
            path_id, refresh_replacement_payload(payload_id), account_manager_headers
        )

        validate_error(response, ApiErrorId.ERR_DEVICE_NOT_REFRESH_DUE.value, 409)
        assert_fields(fetch_device(flagged_id), replaced_by_device_id=None, refresh_due=True)
        assert_fields(fetch_device(successor_id), replaced_by_device_id=None, refresh_due=False)

    def test_a_successor_naming_nothing_reports_device_not_found(self, api,
                                                                account_manager_headers):
        """An unresolvable body identifier outranks the refresh-due eligibility guard.

        PRD: "Any of those failures reports `ERR_DEVICE_NOT_REFRESH_DUE`; a
        `successor_device_id` naming nothing at all reports `ERR_DEVICE_NOT_FOUND`
        instead."
        PRD: "This applies to site creation, device creation, both meter-reading
        intake endpoints (`POST /_agent/meter-reads` and `POST /meter-reads`),
        billing-period creation, consumable-order creation, ticket creation, ticket
        dispatch, quarterly-review creation, removal-order creation, and
        refresh-replacement linkage (where an unknown `successor_device_id` reports
        `ERR_DEVICE_NOT_FOUND`)."

        Design: Corner/endpoints/conditional_action_refresh_linkage_requires_an_approved_refresh_due_flag
        """
        env = _published_refresh_flag_with_a_successor_asset()

        response = api.link_refresh_replacement(
            env["device_id"], refresh_replacement_payload(NON_EXISTENT_UUID),
            account_manager_headers,
        )

        validate_error(response, ApiErrorId.ERR_DEVICE_NOT_FOUND.value, 404)
        assert_fields(fetch_device(env["device_id"]), replaced_by_device_id=None, refresh_due=True)


def _three_technicians_across_two_regions():
    """Three registered technicians, created in a known order."""
    return [
        create_technician(full_name="Tess Rowan", home_region="NE-01", skill_level="L3",
                          travel_buffer_minutes=45),
        create_technician(full_name="Ivan Petrov", home_region="NE-02", skill_level="L1",
                          travel_buffer_minutes=10),
        create_technician(full_name="Mona Diaz", home_region="NE-02", skill_level="L2",
                          travel_buffer_minutes=0),
    ]


class TestTechnicianCreateReadAndFilteredList:
    """Plain create, read and list behaviour on the technician resource."""

    def test_creation_returns_201_and_defaults_the_travel_buffer_to_thirty_minutes(self, api,
                                                                                  account_manager_headers,
                                                                                  fleet_ops_headers):
        """A supplied buffer is kept; an omitted one lands on the declared default.

        PRD: "Field service is delivered by technicians the `AccountManager`
        registers with a `full_name` (non-empty), a `home_region` (non-empty,
        upper-case) that must match a site's `address_region` for that technician to
        be dispatchable there, a `skill_level` of `L1`, `L2` or `L3`, and optionally a
        `travel_buffer_minutes` that defaults to 30 and must lie between 0 and 120."
        PRD: "Each technician exposes a derived `open_dispatch_count`: the number of
        tickets assigned to them whose `status` is `DISPATCHED`, `PARTS_HOLD` or
        `ONSITE`."
        PRD: "Creating a new resource returns HTTP 201; every other successful
        operation, including all state transitions, all reads and all list queries,
        returns HTTP 200."

        Design: Corner/endpoints/standard_crud_technician_create_read_and_filtered_list
        """
        buffered = validate_success(
            api.create_technician(
                technician_payload(full_name="Tess Rowan", home_region="NE-01", skill_level="L3",
                                   travel_buffer_minutes=45),
                account_manager_headers,
            ),
            201,
        )
        defaulted = validate_success(
            api.create_technician(
                {"full_name": "Ivan Petrov", "home_region": "NE-02", "skill_level": "L1"},
                account_manager_headers,
            ),
            201,
        )

        assert_fields(buffered, full_name="Tess Rowan", home_region="NE-01", skill_level="L3",
                      travel_buffer_minutes=45, open_dispatch_count=0, version=1)
        assert_fields(defaulted, full_name="Ivan Petrov", home_region="NE-02", skill_level="L1",
                      travel_buffer_minutes=30, open_dispatch_count=0, version=1)
        read_back = validate_success(api.get_technician(buffered["id"], fleet_ops_headers), 200)
        assert_fields(read_back, id=buffered["id"], full_name="Tess Rowan", home_region="NE-01",
                      skill_level="L3", travel_buffer_minutes=45, open_dispatch_count=0)

    def test_the_listing_filters_independently_on_region_and_skill_level(self, api,
                                                                        fleet_ops_headers):
        """Each filter narrows one dimension, and an omitted filter restricts nothing.

        PRD: "Every one of these filters is optional; when omitted, no restriction
        is applied on that dimension."
        PRD: "Unless a specific endpoint states otherwise, list results are ordered
        by `created_at` ascending."

        Design: Corner/endpoints/standard_crud_technician_create_read_and_filtered_list
        """
        tess, ivan, mona = _three_technicians_across_two_regions()

        everyone, everyone_meta = validate_paginated(api.list_technicians(fleet_ops_headers))
        region_rows, region_meta = validate_paginated(
            api.list_technicians(fleet_ops_headers, params={"home_region": "NE-02"})
        )
        skill_rows, skill_meta = validate_paginated(
            api.list_technicians(fleet_ops_headers, params={"skill_level": "L3"})
        )

        assert everyone_meta["total_count"] == 3, f"expected 3 technicians, meta {everyone_meta}"
        assert [row["id"] for row in everyone] == [tess["id"], ivan["id"], mona["id"]], everyone
        assert region_meta["total_count"] == 2, f"expected 2 NE-02 technicians, {region_meta}"
        assert [row["id"] for row in region_rows] == [ivan["id"], mona["id"]], region_rows
        assert skill_meta["total_count"] == 1, f"expected 1 L3 technician, {skill_meta}"
        assert_fields(skill_rows[0], id=tess["id"], skill_level="L3")

    def test_the_listing_paginates_with_limit_and_offset(self, api, fleet_ops_headers):
        """`total_count` counts the matches before pagination and `has_more` tracks the tail.

        PRD: "`limit` controls page size: it defaults to 10, may be no smaller than
        1 and no larger than 100."
        PRD: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` (the number of rows matching the filters before pagination) and
        `has_more` (true when more rows remain beyond the returned page)."

        Design: Corner/endpoints/standard_crud_technician_create_read_and_filtered_list
        """
        tess, ivan, mona = _three_technicians_across_two_regions()

        first_page, first_meta = validate_paginated(
            api.list_technicians(fleet_ops_headers, params={"limit": 1})
        )
        last_page, last_meta = validate_paginated(
            api.list_technicians(fleet_ops_headers, params={"limit": 1, "offset": 2})
        )
        empty_page, empty_meta = validate_paginated(
            api.list_technicians(fleet_ops_headers, params={"offset": 5})
        )

        assert [row["id"] for row in first_page] == [tess["id"]], first_page
        assert first_meta["total_count"] == 3 and first_meta["has_more"] is True, first_meta
        assert first_meta["limit"] == 1 and first_meta["offset"] == 0, first_meta
        assert [row["id"] for row in last_page] == [mona["id"]], last_page
        assert last_meta["total_count"] == 3 and last_meta["has_more"] is False, last_meta
        assert empty_page == [], f"an offset past the end returns no rows: {empty_page}"
        assert empty_meta["total_count"] == 3 and empty_meta["has_more"] is False, empty_meta
        assert ivan["id"] not in [row["id"] for row in first_page + last_page], "wrong page window"

    def test_reading_an_unknown_technician_reports_technician_not_found(self, api,
                                                                       fleet_ops_headers):
        """An unresolvable path identifier carries the code for the missing resource type.

        PRD: "Every failure of this kind carries HTTP 404 with the code specific to
        the missing resource type: `ERR_CONTRACT_NOT_FOUND`, `ERR_SITE_NOT_FOUND`,
        `ERR_DEVICE_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
        `ERR_METER_READ_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`,
        `ERR_STATEMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND` or `ERR_REMOVAL_ORDER_NOT_FOUND`."

        Design: Corner/endpoints/standard_crud_technician_create_read_and_filtered_list
        """
        _three_technicians_across_two_regions()

        response = api.get_technician(NON_EXISTENT_UUID, fleet_ops_headers)

        validate_error(response, ApiErrorId.ERR_TECHNICIAN_NOT_FOUND.value, 404)
