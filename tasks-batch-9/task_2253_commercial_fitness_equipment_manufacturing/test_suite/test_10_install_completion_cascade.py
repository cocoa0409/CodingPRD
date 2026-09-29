"""Install completion: the five-level cascade, its punch-list fork and its undo."""
from test_helpers import (
    assert_instant,
    abort_install_payload,
    arrive_ctx,
    arrive_on_site,
    complete_install_job,
    complete_production,
    confirm_order,
    list_all,
    new_facility,
    new_install_job,
    new_order,
    new_order_line,
    new_pm_program,
    new_service_partner,
    quote_order,
    read_facility,
    read_install_job,
    read_order,
    read_pm_program,
    read_price_breakdown,
    read_serialized_asset,
    read_service_partner,
    resolve_punch_list,
    setup_active_pm_program,
    setup_released_revision,
    setup_scheduled_install,
    validate_error,
    validate_success,
)

FIRST_WINDOW = ("2026-09-10T08:00:00Z", "2026-09-10T11:00:00Z")
SECOND_WINDOW = ("2026-09-15T08:00:00Z", "2026-09-15T11:00:00Z")


def _order_through_arrival(facility_id, revision_id, partner_id, window, hours,
                          quantity=1):
    """Quote, confirm, build and put a crew on site for one fresh order."""
    order = new_order(facility_id)
    new_order_line(order["id"], revision_id, quantity=quantity)
    quoted = quote_order(order["id"])
    confirm_order(order["id"])
    complete_production(order["id"])
    job = new_install_job(order["id"], partner_id, *window,
                         estimated_labor_hours=hours)
    arrive_on_site(job["id"], partner_id)
    return {"order": quoted, "job": job}


def _tight_capacity_estate():
    """A ten-hour partner, one asset already in service and a live programme."""
    revision = setup_released_revision("T900")["revision"]
    facility = new_facility(account_name="Ridgeline Fitness Group", freight_zone="Z3")
    partner = new_service_partner(name="Ridgeline Service Co",
                                  certified_categories=["CARDIO"],
                                  certified_hours_capacity=10.0,
                                  training_current_until="2027-12-31T00:00:00Z")
    first = _order_through_arrival(facility["id"], revision["id"], partner["id"],
                                   FIRST_WINDOW, hours=1.5)
    complete_install_job(first["job"]["id"], partner["id"], actual_labor_hours=1.5,
                         punch_list_open_count=0)
    program = setup_active_pm_program(facility["id"], partner["id"], tier="PRO",
                                      visit_interval_days=90)
    second = _order_through_arrival(facility["id"], revision["id"], partner["id"],
                                    SECOND_WINDOW, hours=1.5)
    return {"revision": revision, "facility": facility, "partner": partner,
            "program": program, "first": first, "second": second}


def test_the_completion_cascade_can_push_a_partner_over_its_certified_capacity(api):
    """The recomputed programme hours land above the capacity the crew signed for.

    The PRD states that `coverage_status` "is `OVER_COMMITTED` exactly when
    `committed_hours` is strictly greater than `certified_hours_capacity`, and
    `ACTIVE` otherwise. Equality is not over-commitment."

    Design: Difficulty/transitive_cascade/install_completion_cascade_flips_partner_to_over_committed
    """
    estate = _tight_capacity_estate()
    assert estate["program"]["annual_labor_hours_committed"] == 6.25
    assert estate["program"]["covered_asset_count"] == 1
    assert read_service_partner(estate["partner"]["id"])["committed_hours"] == 7.75

    job = complete_install_job(estate["second"]["job"]["id"], estate["partner"]["id"],
                               actual_labor_hours=1.5, punch_list_open_count=0)

    assert job["status"] == "COMPLETED"
    assert_instant(job["completed_at"], "2026-08-01T00:00:00Z", "completed_at")
    program = read_pm_program(estate["program"]["id"])
    assert program["covered_asset_count"] == 2
    assert program["annual_labor_hours_committed"] == 12.50
    assert program["status"] == "ACTIVE", (
        "the cascade only recomputes hours, it never flags the programme"
    )
    partner = read_service_partner(estate["partner"]["id"])
    assert partner["committed_hours"] == 12.50
    assert partner["certified_hours_capacity"] == 10.0
    assert partner["coverage_status"] == "OVER_COMMITTED"
    order = read_order(estate["second"]["order"]["id"])
    assert order["fulfillment_status"] == "INSTALLED"
    assert order["billing_status"] == "INVOICED"
    assert order["price_variant_applied"] == "FINAL"
    assert order["final_total_cents"] == 594_310
    assert order["amount_due_cents"] == 594_310
    assert order["freight_cents"] == 72_250
    for asset in list_all(api.list_serialized_assets,
                          {"facility_id": estate["facility"]["id"]}):
        assert asset["status"] == "IN_SERVICE"
        assert_instant(asset["warranty_starts_at"], "2026-08-01T00:00:00Z", "warranty_starts_at")
        assert_instant(asset["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")


def test_the_guarded_activation_path_refuses_the_same_over_commitment(
    api, service_ops_admin_headers
):
    """Requesting 12.50 hours from a ten-hour crew is refused up front.

    The PRD states that activation requires "the partner's existing
    `committed_hours` plus this program's `annual_labor_hours_committed` must be
    less than or equal to its `certified_hours_capacity`, equality allowed
    (`ERR_PARTNER_CAPACITY_EXCEEDED`)."

    Design: Difficulty/transitive_cascade/install_completion_cascade_flips_partner_to_over_committed
    """
    revision = setup_released_revision("T900")["revision"]
    facility = new_facility(account_name="Crestwood Fitness Group", freight_zone="Z1")
    partner = new_service_partner(name="Crestwood Service Co",
                                  certified_categories=["CARDIO"],
                                  certified_hours_capacity=10.0)
    staged = _order_through_arrival(facility["id"], revision["id"], partner["id"],
                                    FIRST_WINDOW, hours=3.0, quantity=2)
    complete_install_job(staged["job"]["id"], partner["id"], actual_labor_hours=3.0,
                         punch_list_open_count=0)
    assert read_service_partner(partner["id"])["committed_hours"] == 0.0
    program = new_pm_program(facility["id"], partner["id"], tier="PRO",
                             visit_interval_days=90)
    assert program["status"] == "DRAFT"
    assert program["annual_labor_hours_committed"] == 0

    response = api.activate_pm_program(program["id"], service_ops_admin_headers)

    validate_error(response, "ERR_PARTNER_CAPACITY_EXCEEDED", 409)
    unchanged = read_pm_program(program["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["covered_asset_count"] == 0
    assert unchanged["annual_labor_hours_committed"] == 0
    partner_after = read_service_partner(partner["id"])
    assert partner_after["committed_hours"] == 0.0
    assert partner_after["coverage_status"] == "ACTIVE"


def test_one_completion_propagates_through_all_five_levels(api):
    """Job, order, asset, programme and partner all move on the single call.

    The PRD states that on the zero-punch-list branch "the job moves `ON_SITE →
    COMPLETED` and the full five-level cascade runs" and that "every `ACTIVE`
    maintenance program at the order's facility has its `covered_asset_count` and
    `annual_labor_hours_committed` recomputed, because the facility just acquired
    in-service assets".

    Design: Corner/complexity_layers/install_completion_cascade_is_verified_across_five_levels
    """
    ctx = setup_scheduled_install(preset="T900", quantity=1)
    program = setup_active_pm_program(ctx["facility"]["id"], ctx["partner"]["id"],
                                      tier="PRO", visit_interval_days=90)
    assert program["covered_asset_count"] == 0
    assert program["annual_labor_hours_committed"] == 0
    arrive_ctx(ctx)
    asset_id = ctx["asset"]["id"]

    job = complete_install_job(ctx["install_job"]["id"], ctx["partner"]["id"],
                               actual_labor_hours=3.0, punch_list_open_count=0)

    assert job["status"] == "COMPLETED"
    assert job["actual_labor_hours"] == 3.0
    assert job["punch_list_open_count"] == 0
    order = read_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "INSTALLED"
    assert order["billing_status"] == "INVOICED"
    assert order["price_variant_applied"] == "FINAL"
    assert order["final_total_cents"] == 573_622
    assert order["amount_due_cents"] == 573_622
    asset = read_serialized_asset(asset_id)
    assert asset["status"] == "IN_SERVICE"
    assert_instant(asset["warranty_starts_at"], "2026-08-01T00:00:00Z", "warranty_starts_at")
    assert_instant(asset["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")
    assert asset["connectivity_support_status"] == "NOT_APPLICABLE"
    assert asset["support_gap_days"] == 0
    revised = read_pm_program(program["id"])
    assert revised["covered_asset_count"] == 1
    assert revised["annual_labor_hours_committed"] == 6.25
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["committed_hours"] == 6.25
    assert partner["coverage_status"] == "ACTIVE"
    assert read_facility(ctx["facility"]["id"])["open_order_exposure_cents"] == 560_310
    breakdown = read_price_breakdown(ctx["order"]["id"])
    assert breakdown["install_amount_cents"] == 26_625
    assert breakdown["punch_list_credit_cents"] == 0


def test_the_punch_list_branch_defers_the_whole_cascade_until_resolution(api):
    """Two open items freeze everything, and resolution then fires it all at once.

    The PRD states that with a count of one or more "the job moves `ON_SITE →
    PUNCH_LIST` and nothing else happens at all: the order is neither installed nor
    invoiced, the assets stay `BUILT`, no warranty starts and no rollup is
    recomputed", while resolution runs "exactly the same cascade as the direct
    `ON_SITE → COMPLETED` branch".

    Design: Corner/state_machines/punch_list_branch_defers_the_installation_cascade_until_resolution
    """
    ctx = setup_scheduled_install(preset="T900", quantity=1)
    arrive_ctx(ctx)
    asset_id = ctx["asset"]["id"]
    assert read_order(ctx["order"]["id"])["quoted_total_cents"] == 560_310

    deferred = complete_install_job(ctx["install_job"]["id"], ctx["partner"]["id"],
                                    actual_labor_hours=4.5, punch_list_open_count=2)

    assert deferred["status"] == "PUNCH_LIST"
    assert deferred["actual_labor_hours"] == 4.5
    assert deferred["punch_list_open_count"] == 2
    held = read_order(ctx["order"]["id"])
    assert held["fulfillment_status"] == "INSTALLING"
    assert held["billing_status"] == "QUOTED"
    assert held["final_total_cents"] is None
    held_asset = read_serialized_asset(asset_id)
    assert held_asset["status"] == "BUILT"
    assert held_asset["warranty_starts_at"] is None

    resolved = resolve_punch_list(ctx["install_job"]["id"], ctx["partner"]["id"],
                                  resolution_note="remaining console brackets fitted")

    assert resolved["status"] == "COMPLETED"
    assert resolved["punch_list_open_count"] == 2, "the recorded count is retained"
    order = read_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "INSTALLED"
    assert order["billing_status"] == "INVOICED"
    assert order["install_amount_cents"] == 39_938
    assert order["punch_list_credit_cents"] == 50_000
    assert order["final_total_cents"] == 536_935
    assert order["price_variant_applied"] == "FINAL"
    assert order["amount_due_cents"] == 536_935
    assert order["quoted_total_cents"] == 560_310
    asset = read_serialized_asset(asset_id)
    assert asset["status"] == "IN_SERVICE"
    assert_instant(asset["warranty_starts_at"], "2026-08-01T00:00:00Z", "warranty_starts_at")
    assert_instant(asset["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")


def test_aborting_from_on_site_reverts_the_order_and_releases_the_hours(
    api, order_planner_headers
):
    """The abort undoes arrival exactly, and does nothing completion would have done.

    The PRD states that both abort branches "release the calendar window and
    recompute the partner's `committed_hours` and `coverage_status`" and that "The
    `ON_SITE` branch additionally reverts the order's `fulfillment_status`
    `INSTALLING → STAGED`, so the order can be rescheduled with a fresh install
    job".

    Design: Corner/state_machines/install_job_abort_from_on_site_reverts_the_order_and_releases_hours
    """
    ctx = setup_scheduled_install(preset="T900", quantity=1)
    arrive_ctx(ctx)
    asset_id = ctx["asset"]["id"]
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "INSTALLING"
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 3.0

    response = api.abort_install_job(
        ctx["install_job"]["id"],
        abort_install_payload(abort_reason="crew reassigned to a storm callout"),
        order_planner_headers,
    )

    job = validate_success(response)
    assert job["status"] == "ABORTED"
    assert job["actual_labor_hours"] is None
    assert job["completed_at"] is None
    order = read_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "STAGED"
    assert order["config_status"] == "CONFIRMED"
    assert order["billing_status"] == "QUOTED"
    assert order["final_total_cents"] is None
    assert order["price_variant_applied"] == "PROVISIONAL"
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["committed_hours"] == 0.0
    assert partner["coverage_status"] == "ACTIVE"
    asset = read_serialized_asset(asset_id)
    assert asset["status"] == "BUILT"
    assert asset["warranty_starts_at"] is None
    assert asset["warranty_expires_at"] is None
    assert read_facility(ctx["facility"]["id"])[
        "open_order_exposure_cents"
    ] == 560_310, "the abort does not clear the credit exposure"
    assert read_install_job(ctx["install_job"]["id"])["status"] == "ABORTED"


def test_every_derived_field_is_readable_in_the_write_response_itself(
    api, order_planner_headers
):
    """No rollup lags behind its write: each response already carries the new values.

    The PRD states that "cascades are immediate and complete within the request that
    triggers them. There is no deferred queue, no eventual reconciliation and no
    background sweep" and that "those child rows are moved before the response is
    written, and the response reflects the post-cascade world."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_write_response_itself
    """
    ctx = setup_scheduled_install(preset="T900", quantity=1)
    program = setup_active_pm_program(ctx["facility"]["id"], ctx["partner"]["id"],
                                      tier="PRO", visit_interval_days=90)
    assert ctx["order"]["quoted_total_cents"] == 560_310
    assert ctx["order"]["billing_status"] == "QUOTED"
    assert ctx["order"]["price_variant_applied"] == "PROVISIONAL"
    assert read_facility(ctx["facility"]["id"])["open_order_exposure_cents"] == 560_310
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 3.0
    arrive_ctx(ctx)

    job = complete_install_job(ctx["install_job"]["id"], ctx["partner"]["id"],
                               actual_labor_hours=3.0, punch_list_open_count=0)

    assert job["status"] == "COMPLETED"
    first_read = validate_success(api.get_order(ctx["order"]["id"],
                                                order_planner_headers))
    assert first_read["fulfillment_status"] == "INSTALLED"
    assert first_read["billing_status"] == "INVOICED"
    assert first_read["final_total_cents"] == 573_622
    assert first_read["amount_due_cents"] == 573_622
    second_read = validate_success(api.get_order(ctx["order"]["id"],
                                                 order_planner_headers))
    assert second_read == first_read, "reads are stable, not converging"
    assert read_pm_program(program["id"])["annual_labor_hours_committed"] == 6.25
    assert read_pm_program(program["id"])["covered_asset_count"] == 1
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 6.25
    asset = read_serialized_asset(ctx["asset"]["id"])
    assert asset["status"] == "IN_SERVICE"
    assert_instant(asset["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")
