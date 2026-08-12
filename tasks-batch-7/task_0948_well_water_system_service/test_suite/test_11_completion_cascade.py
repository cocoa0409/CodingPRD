"""Work-order completion: the labour ladder, the invoice variant and the cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_money,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def _quoted_pinned_world():
    """A quote priced at 25001 a unit, then a catalog drop to 5001 before consumption."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Ridgeline Farm LLC",
        email="ap@ridgeline.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_ALPHA",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="18 Ridgeline Rd",
        distance_miles=20.0,
        household_size=4,
        has_vulnerable_occupant=False,
        depth_feet=240.0,
        drawdown=6.0,
        technician_name="Dana Reyes",
    )
    part = fixtures.new_part("CTL-9000", "CONTROL", 25001, on_hand_qty=10)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 15.0, 40.0, 6.0
    )
    staged = fixtures.priced_and_sent_quote(
        world["property_id"], world["well_id"], inspection["id"], part["id"], 2,
        "REPAIR", 100, "2026-06-03T18:00:00Z", "JOURNEYMAN",
    )
    fixtures.approve_quote(staged["quote_id"], world["account_id"])
    fixtures._ok(
        fixtures.api_client.patch_part_catalog_item(
            part["id"], {"unit_cost_cents": 5001}, ADMIN
        )
    )
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        quote_id=staged["quote_id"],
    )
    fixtures.schedule_work_order(
        work_order["id"], "2026-06-03T18:00:00Z", "2026-06-03T20:00:00Z"
    )
    fixtures.set_clock("2026-06-03T18:00:00Z")
    fixtures.start_work_order(work_order["id"], world["technician_id"])
    fixtures.post_parts(work_order["id"], world["technician_id"], part["id"], 2)
    world.update(
        {
            "part_id": part["id"],
            "line_id": staged["line_id"],
            "work_order_id": work_order["id"],
        }
    )
    return world


def test_a_pinned_quote_line_survives_a_later_catalog_move(api):
    """PRD 3.6: "From `DRAFT`, every `ACTIVE` line has the catalog's *current*
    `unit_cost_cents` copied onto it as `unit_cost_cents_pinned` and frozen there — later
    catalog moves never disturb a pinned line — and then `markup_pct_applied`,
    `unit_price_cents` and `extended_price_cents` are computed per line by the parts
    ladder of Section 3.5."
    PRD 3.1: "A `PlatformAdmin` may later change `unit_cost_cents`, `on_hand_qty` or
    `status`, bumping `version` by 1 — and a cost change deliberately does **not** disturb
    a quote line whose cost has already been pinned."

    Design: Difficulty/dual_variant_calc/invoice_costing_quoted_pinned_diverges_from_catalog_current_cost
    """
    world = _quoted_pinned_world()
    assert_money(
        fixtures.get_part(world["part_id"])["unit_cost_cents"],
        5001,
        "PartCatalogItem.unit_cost_cents",
    )
    line = fixtures.get_quote_line(world["line_id"])
    assert_money(
        line["unit_cost_cents_pinned"], 25001, "QuoteLine.unit_cost_cents_pinned"
    )
    assert_money(line["unit_price_cents"], 32001, "QuoteLine.unit_price_cents")


def test_the_quoted_pinned_invoice_prices_the_part_at_the_pinned_cost(api):
    """PRD 3.9: "Because the work order became billable, an `Invoice` is created in
    `DRAFT` with `variant` `QUOTED_PINNED` when `quote_id` is set and `ACTUAL_FINAL`
    otherwise, and its lines are constructed in the pinned order set out in Section 3.11."
    PRD 3.9: "on a work order founded on a quote, the snapshot is taken from the
    `unit_cost_cents_pinned` of the quote's `ACTIVE` line for the **same**
    `part_catalog_item_id`, choosing the earliest such line by `created_at`, and the
    catalog's current cost is used only for parts the quote never listed"
    PRD 3.11: "The dispatch figure is 0 when the pipeline is `SCHEDULED`."

    Design: Difficulty/dual_variant_calc/invoice_costing_quoted_pinned_diverges_from_catalog_current_cost
    """
    world = _quoted_pinned_world()
    validate_success(
        api.complete_work_order(
            world["work_order_id"], {"actual_labor_minutes": 100}, world["technician_headers"]
        )
    )
    invoice = fixtures.first_invoice_of(world["work_order_id"])
    assert invoice["variant"] == "QUOTED_PINNED"
    assert_money(invoice["parts_subtotal_cents"], 64002, "Invoice.parts_subtotal_cents")
    assert_money(invoice["labor_subtotal_cents"], 22444, "Invoice.labor_subtotal_cents")
    assert_money(invoice["dispatch_subtotal_cents"], 0, "Invoice.dispatch_subtotal_cents")
    assert_money(
        invoice["taxable_subtotal_cents"], 64002, "Invoice.taxable_subtotal_cents"
    )
    assert_money(invoice["tax_cents"], 4640, "Invoice.tax_cents")
    assert_money(invoice["total_cents"], 91086, "Invoice.total_cents")


def test_the_weekend_band_beats_the_hour_band_on_the_actual_start(api):
    """PRD 3.5: "If its ISO weekday is Saturday or Sunday — weekday 6 or 7 — the band is
    `WEEKEND`, and weekend beats every hour band regardless of the hour."
    PRD 3.5: "A `JOURNEYMAN` in the evening is therefore 12825 cents an hour; a `MASTER`
    at the weekend is 20250; an `APPRENTICE` at night is 11375."
    PRD 3.5: "**Billable minutes** are the raw minutes rounded *up* to the next whole
    multiple of `BILLING_INCREMENT_MINUTES` (15), then floored at `MIN_BILLABLE_MINUTES`
    (60) — that is, the larger of the rounded figure and 60."

    Design: Corner/calculations/corner_labor_weekend_band_overrides_the_hour_band
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Weekend Co",
        email="wk@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="6 Weekend",
        technician_tier="MASTER",
        technician_name="Weekend Tech",
    )
    part = fixtures.new_part("CTL-3000-G", "CONTROL", 3000, on_hand_qty=20)
    stage = fixtures.completed_emergency_work_order(
        world,
        part_id=part["id"],
        quantity=1,
        actual_labor_minutes=46,
        cause_class="CONTROL_FAILURE",
        onsite_estimate_cents=30000,
        scheduled_start_at="2026-06-06T20:00:00Z",
        scheduled_end_at="2026-06-06T22:00:00Z",
        start_clock_at="2026-06-06T20:00:00Z",
    )
    work_order = stage["work_order"]
    assert work_order["billable_minutes"] == 60
    assert_money(
        work_order["labor_rate_cents_per_hour"], 20250, "WorkOrder.labor_rate_cents_per_hour"
    )
    assert_money(work_order["labor_charge_cents"], 20250, "WorkOrder.labor_charge_cents")
    assert_money(work_order["parts_charge_cents"], 4800, "WorkOrder.parts_charge_cents")


def test_a_non_well_cause_caps_the_labour_and_zeroes_the_surcharge(api):
    """PRD 3.5: "One further step applies **only** on the emergency pipeline and **only**
    when the ticket's `cause_class` is `NON_WELL_CAUSE`: the result is then capped at
    `NON_WELL_CAUSE_LABOR_CAP_MINUTES` (60), so raw 200 minutes rounds to 210, floors at
    210 and caps back down to 60."
    PRD 3.8: "The **net dispatch charge** is the surcharge less the credit, floored at
    zero — except that a `NON_WELL_CAUSE` diagnosis zeroes it outright, because a tripped
    breaker or a municipal outage is not a well service and the billing basis collapses to
    the trip fee alone."
    PRD 3.11: "On the emergency pipeline it is the ticket's `net_dispatch_charge_cents`
    plus the property's trip fee from its `service_zone` band."

    Design: Corner/calculations/corner_non_well_cause_caps_labor_and_zeroes_the_surcharge
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Breaker Co",
        email="bk@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="20 Breaker",
        distance_miles=20.0,
        technician_name="Breaker Tech",
    )
    stage = fixtures.completed_emergency_work_order(
        world,
        part_id=None,
        actual_labor_minutes=200,
        cause_class="NON_WELL_CAUSE",
        onsite_estimate_cents=10000,
        scheduled_start_at="2026-06-01T12:00:00Z",
        scheduled_end_at="2026-06-01T18:00:00Z",
    )
    ticket = fixtures.get_ticket(stage["ticket_id"])
    assert ticket["severity_score"] == 20
    assert_money(
        ticket["dispatch_surcharge_cents"], 7000, "EmergencyTicket.dispatch_surcharge_cents"
    )
    assert_money(
        ticket["net_dispatch_charge_cents"],
        0,
        "EmergencyTicket.net_dispatch_charge_cents",
    )

    work_order = stage["work_order"]
    assert work_order["billable_minutes"] == 60
    assert_money(work_order["labor_charge_cents"], 9500, "WorkOrder.labor_charge_cents")

    invoice = fixtures.first_invoice_of(stage["work_order_id"])
    assert_money(
        invoice["dispatch_subtotal_cents"], 12500, "Invoice.dispatch_subtotal_cents"
    )
    assert_money(invoice["parts_subtotal_cents"], 0, "Invoice.parts_subtotal_cents")
    assert_money(invoice["tax_cents"], 0, "Invoice.tax_cents")
    assert_money(invoice["total_cents"], 22000, "Invoice.total_cents")


def test_billable_minutes_round_up_to_the_increment_then_floor_at_an_hour(api):
    """PRD 3.5: "**Billable minutes** are the raw minutes rounded *up* to the next whole
    multiple of `BILLING_INCREMENT_MINUTES` (15), then floored at `MIN_BILLABLE_MINUTES`
    (60) — that is, the larger of the rounded figure and 60. Raw 0 becomes 60; raw 46
    rounds to 60 and stays 60; raw 61 rounds to 75."
    PRD 3.9: "`actual_end_at` is stamped from the logical clock, and `billable_minutes`,
    `labor_rate_cents_per_hour` and `labor_charge_cents` are computed by the labour ladder
    of Section 3.5 using `actual_start_at` for the band and the assigned technician's
    `tier` for the rate."

    Design: Corner/calculations/corner_calc_billable_minutes_increment_and_floor_on_completion
    """
    fixtures.set_clock("2026-06-03T09:00:00Z")
    account = fixtures.new_account(
        "Billable Minutes Co", "JUR_ALPHA", "bm@corner.example", "NONE"
    )
    prop = fixtures.new_property(account["id"], "46 Minutes", "JUR_ALPHA", 10.0, 3)
    well_a = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    well_b = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    technician = fixtures.new_technician("Minutes Tech", "MASTER", "JUR_ALPHA")

    ticket_a = fixtures.diagnosed_ticket(
        prop["id"], well_a["id"], account["id"], technician["id"], "PUMP_FAILURE", 20000
    )
    ticket_b = fixtures.diagnosed_ticket(
        prop["id"], well_b["id"], account["id"], technician["id"], "PUMP_FAILURE", 20000
    )
    work_order_a = fixtures.new_work_order(
        prop["id"], well_a["id"], technician["id"], "REPAIR",
        emergency_ticket_id=ticket_a["id"],
    )
    fixtures.schedule_work_order(
        work_order_a["id"], "2026-06-03T12:00:00Z", "2026-06-03T14:00:00Z"
    )
    work_order_b = fixtures.new_work_order(
        prop["id"], well_b["id"], technician["id"], "REPAIR",
        emergency_ticket_id=ticket_b["id"],
    )
    fixtures.schedule_work_order(
        work_order_b["id"], "2026-06-04T12:00:00Z", "2026-06-04T14:00:00Z"
    )

    fixtures.set_clock("2026-06-03T12:00:00Z")
    fixtures.start_work_order(work_order_a["id"], technician["id"])
    fixtures.set_clock("2026-06-04T12:00:00Z")
    fixtures.start_work_order(work_order_b["id"], technician["id"])

    completed_a = validate_success(
        api.complete_work_order(
            work_order_a["id"],
            {"actual_labor_minutes": 46},
            fixtures.make_technician_headers(technician["id"]),
        )
    )
    completed_b = validate_success(
        api.complete_work_order(
            work_order_b["id"],
            {"actual_labor_minutes": 61},
            fixtures.make_technician_headers(technician["id"]),
        )
    )

    assert completed_a["billable_minutes"] == 60
    assert_money(
        completed_a["labor_rate_cents_per_hour"], 13500, "WorkOrder.labor_rate_cents_per_hour"
    )
    assert_money(completed_a["labor_charge_cents"], 13500, "WorkOrder.labor_charge_cents")
    assert_money(completed_a["parts_charge_cents"], 0, "WorkOrder.parts_charge_cents")
    assert_instant_equals(
        completed_a["actual_start_at"],
        "2026-06-03T12:00:00Z",
        "WorkOrder.actual_start_at",
    )

    assert completed_b["billable_minutes"] == 75
    assert_money(
        completed_b["labor_rate_cents_per_hour"], 13500, "WorkOrder.labor_rate_cents_per_hour"
    )
    assert_money(completed_b["labor_charge_cents"], 16875, "WorkOrder.labor_charge_cents")
    assert completed_b["fulfillment_status"] == "COMPLETED"
    assert completed_b["billing_status"] == "PENDING_INVOICE"


def test_the_completion_cascade_is_visible_in_the_same_request(api):
    """PRD 3.9: "Because the work order became billable, an `Invoice` is created in
    `DRAFT` with `variant` `QUOTED_PINNED` when `quote_id` is set and `ACTUAL_FINAL`
    otherwise, and its lines are constructed in the pinned order set out in Section 3.11."
    PRD 3.9: "Because parts and labour were finalised, every `ACTIVE` maintenance plan on
    this well is refreshed: exactly one `MaintenanceVisit` row is created per `ACTIVE`
    plan, with `visit_kind` chosen from the finalised part categories"
    PRD 3.9: "Because an invoice exists, the work order's billing axis moves
    `NOT_BILLABLE → PENDING_INVOICE`; and when the pipeline is `EMERGENCY`, the ticket's
    dispatch axis moves `DIAGNOSED → RESOLVED`. The account's `balance_cents` is **not**
    touched at `DRAFT`."
    PRD 3.10: "Both touched gives `SALT_AND_FILTER`; filter only gives `FILTER_ONLY`;
    salt only gives `SALT_ONLY`; neither gives `SERVICE_ONLY`."

    Design: Corner/consistency_model/corner_consistency_completion_cascade_is_visible_in_the_same_request
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Immediate Cascade Co",
        email="ic@corner.example",
        address_line="1 Immediate",
        technician_name="Immediate Tech",
    )
    plan = fixtures.new_maintenance_plan(world["well_id"], world["account_id"])
    part = fixtures.new_part("CTL-5000-I", "CONTROL", 5000, on_hand_qty=10)
    stage = fixtures.emergency_work_order_in_progress(world)
    fixtures.post_parts(stage["work_order_id"], world["technician_id"], part["id"], 2)

    completed = validate_success(
        api.complete_work_order(
            stage["work_order_id"],
            {"actual_labor_minutes": 60},
            world["technician_headers"],
        )
    )
    assert completed["fulfillment_status"] == "COMPLETED"
    assert completed["billing_status"] == "PENDING_INVOICE"
    assert completed["billable_minutes"] == 60
    assert_money(completed["labor_charge_cents"], 9500, "WorkOrder.labor_charge_cents")
    assert_money(completed["parts_charge_cents"], 16000, "WorkOrder.parts_charge_cents")

    invoices = fixtures.invoices_of(stage["work_order_id"])
    assert len(invoices) == 1
    assert invoices[0]["status"] == "DRAFT"
    assert_money(invoices[0]["total_cents"], 49160, "Invoice.total_cents")

    assert len(fixtures.coverages_of(stage["work_order_id"])) == 2

    visits = fixtures.visits_of_work_order(stage["work_order_id"])
    assert len(visits) == 1
    assert visits[0]["visit_kind"] == "SERVICE_ONLY"

    refreshed = fixtures.get_plan(plan["id"])
    assert_instant_equals(
        refreshed["last_service_date"],
        "2026-06-01T12:00:00Z",
        "MaintenancePlan.last_service_date",
    )
    assert_instant_equals(
        refreshed["next_due_at"], "2027-02-26T12:00:00Z", "MaintenancePlan.next_due_at"
    )
    assert refreshed["compliance_state"] == "COMPLIANT"
    assert fixtures.get_ticket(stage["ticket_id"])["dispatch_status"] == "RESOLVED"
    assert_money(
        fixtures.get_account(world["account_id"])["balance_cents"],
        0,
        "Account.balance_cents",
    )


def test_write_off_checks_the_billing_axis_first_then_the_fulfilment_axis(api):
    """PRD 3.9: "**Write-off** is the `BillingClerk`'s act on the billing axis. It requires
    `billing_status` `NOT_BILLABLE` — checked first — and `fulfillment_status`
    `CANCELLED`, and moves the billing axis `NOT_BILLABLE → WRITTEN_OFF` with `version`
    up by 1."
    PRD 2.6: "On write-off, the **billing** axis is checked *before* the fulfilment axis:
    a work order whose billing axis is not `NOT_BILLABLE` is refused with
    `ERR_WORK_ORDER_INVALID_BILLING_STATE` even if its fulfilment axis is also wrong, and
    only once the billing axis passes is `ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE` raised
    for a fulfilment axis that is not `CANCELLED`."

    Design: Corner/state_machines/corner_work_order_write_off_requires_cancelled_fulfillment
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Writeoff Co",
        email="wo@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="13 Writeoff",
        technician_name="WO Tech",
    )
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
    )
    work_order = fixtures.new_work_order(
        world["property_id"], world["well_id"], world["technician_id"], "REPAIR",
        emergency_ticket_id=ticket["id"],
    )
    validate_error(
        api.write_off_work_order(work_order["id"], BILLING),
        ApiErrorId.ERR_WORK_ORDER_INVALID_FULFILLMENT_STATE.value,
        409,
    )
    validate_success(api.cancel_work_order(work_order["id"], DISPATCHER))
    written_off = validate_success(api.write_off_work_order(work_order["id"], BILLING))
    assert written_off["fulfillment_status"] == "CANCELLED"
    assert written_off["billing_status"] == "WRITTEN_OFF"


def test_the_work_order_origin_and_billing_gates_each_own_their_error(api):
    """PRD 3.9: "The body names `property_id`, `well_profile_id`,
    `assigned_technician_id`, a `scope` — the five quote scopes plus `MAINTENANCE` — and
    exactly one of `quote_id` or `emergency_ticket_id`. Supplying both, or neither, is
    refused with `ERR_WORK_ORDER_ORIGIN_CONFLICT`. A quote-founded work order requires
    that quote to be `APPROVED`, or the answer is `ERR_QUOTE_NOT_APPROVED`, and the quote
    then moves `APPROVED → CONSUMED` with its `version` up by 1. An emergency ticket may
    found **at most one** work order; a second attempt is refused with
    `ERR_EMERGENCY_TICKET_ALREADY_LINKED`."
    PRD 3.8: "A movement attempted from the wrong dispatch state is
    `ERR_EMERGENCY_DISPATCH_INVALID_STATE`; one attempted on the authorisation axis when
    it is not `PENDING` is `ERR_EMERGENCY_AUTH_INVALID_STATE`."

    Design: Corner/errors/corner_work_order_origin_and_billing_gates_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Origin Co",
        email="or@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="10 Origin",
        technician_name="Origin Tech",
    )
    part = fixtures.new_part("CTL-3000-I", "CONTROL", 3000, on_hand_qty=20)
    inspection = fixtures.completed_inspection(
        world["well_id"], world["technician_id"], "2026-06-01T10:00:00Z", 12.0, 30.0, 8.0
    )
    quote = fixtures.new_quote(
        world["property_id"], world["well_id"], inspection["id"], "REPAIR", 60,
        "2026-06-03T12:00:00Z", "JOURNEYMAN",
    )
    stage = fixtures.completed_emergency_work_order(world, part_id=part["id"], quantity=1)

    base = {
        "property_id": world["property_id"],
        "well_profile_id": world["well_id"],
        "assigned_technician_id": world["technician_id"],
        "scope": "REPAIR",
    }
    validate_error(
        api.create_work_order(
            dict(base, quote_id=quote["id"], emergency_ticket_id=stage["ticket_id"]),
            DISPATCHER,
        ),
        ApiErrorId.ERR_WORK_ORDER_ORIGIN_CONFLICT.value,
        422,
    )
    validate_error(
        api.create_work_order(dict(base, quote_id=quote["id"]), DISPATCHER),
        ApiErrorId.ERR_QUOTE_NOT_APPROVED.value,
        422,
    )
    validate_error(
        api.create_work_order(
            dict(base, emergency_ticket_id=stage["ticket_id"]), DISPATCHER
        ),
        ApiErrorId.ERR_EMERGENCY_TICKET_ALREADY_LINKED.value,
        409,
    )
    validate_error(
        api.write_off_work_order(stage["work_order_id"], BILLING),
        ApiErrorId.ERR_WORK_ORDER_INVALID_BILLING_STATE.value,
        409,
    )
    validate_error(
        api.authorize_ticket(stage["ticket_id"], world["customer_headers"]),
        ApiErrorId.ERR_EMERGENCY_AUTH_INVALID_STATE.value,
        409,
    )
    assert (
        fixtures.get_work_order(stage["work_order_id"])["billing_status"]
        == "PENDING_INVOICE"
    )
    assert fixtures.get_ticket(stage["ticket_id"])["dispatch_status"] == "RESOLVED"


def test_invoice_lines_are_built_in_the_pinned_line_type_order(api):
    """PRD 3.11: "**Invoice lines** are constructed in this pinned order and numbered with
    `sequence_no` starting at 1 in that same order: every `PARTS` line first, one per
    `POSTED` consumption entry in the step-1 ordering, each naming its
    `parts_consumption_entry_id`; then the single `LABOR` line; then, on the emergency
    pipeline only, a `DISPATCH_SURCHARGE` line and a `TRIP_FEE` line; then a `PERMIT_FEE`
    line when a permit fee applies; then a `WARRANTY_CREDIT` line when the credit is
    greater than zero; then a `LOYALTY_DISCOUNT` line when the discount is greater than
    zero; then the `TAX` line."
    PRD 3.11: "`tax_cents` is `TAX_RATE_PCT` (7.25 percent) of `taxable_subtotal_cents`,
    rounded half up. **Nothing else is taxable** — not labour, not dispatch, not the trip
    fee, not the permit fee."

    Design: Corner/endpoints/corner_endpoint_invoice_lines_built_in_the_pinned_line_type_order
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Invoice Lines Co",
        email="il@corner.example",
        address_line="5 Lines",
        technician_name="Lines Tech",
    )
    part = fixtures.new_part("CTL-5000-L", "CONTROL", 5000, on_hand_qty=10)
    stage = fixtures.completed_emergency_work_order(
        world, part_id=part["id"], quantity=2, actual_labor_minutes=60
    )

    invoices = fixtures.invoices_of(stage["work_order_id"])
    assert len(invoices) == 1
    invoice = invoices[0]
    assert invoice["variant"] == "ACTUAL_FINAL"
    assert invoice["status"] == "DRAFT"
    assert_money(invoice["parts_subtotal_cents"], 16000, "Invoice.parts_subtotal_cents")
    assert_money(invoice["labor_subtotal_cents"], 9500, "Invoice.labor_subtotal_cents")
    assert_money(
        invoice["dispatch_subtotal_cents"], 22500, "Invoice.dispatch_subtotal_cents"
    )
    assert_money(invoice["warranty_credit_cents"], 0, "Invoice.warranty_credit_cents")
    assert_money(invoice["loyalty_discount_cents"], 0, "Invoice.loyalty_discount_cents")
    assert_money(
        invoice["taxable_subtotal_cents"], 16000, "Invoice.taxable_subtotal_cents"
    )
    assert_money(invoice["tax_cents"], 1160, "Invoice.tax_cents")
    assert_money(invoice["total_cents"], 49160, "Invoice.total_cents")

    lines, _ = validate_paginated(api.list_invoice_lines_of(invoice["id"], BILLING))
    assert [line["sequence_no"] for line in lines] == [1, 2, 3, 4, 5]
    assert [line["line_type"] for line in lines] == [
        "PARTS",
        "LABOR",
        "DISPATCH_SURCHARGE",
        "TRIP_FEE",
        "TAX",
    ]
    assert [line["amount_cents"] for line in lines] == [16000, 9500, 14000, 8500, 1160]
