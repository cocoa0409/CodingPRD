"""Service tickets: coverage fork, dispatch selector, resolution costs, reopen compensation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_practice,
    create_product,
    create_technician,
    create_service_ticket_payload,
    create_dispatch_payload,
    create_resolve_payload,
    setup_accepted_sale,
    setup_ticket_assessed,
    setup_ticket_dispatched,
    setup_ticket_resolved,
    drive_sale_to_accepted,
    load_van_stock,
    create_service_plan,
    open_and_assess_ticket,
    set_clock,
    van_stock_quantity,
    make_practice_manager_headers,
    make_field_technician_headers,
    TEST_USERS,
    ApiErrorId,
)

ADMIN = TEST_USERS["admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]


def test_service_ticket_dispatch_from_open_rejected(api):
    """PRD §3.7: "A successful dispatch moves `COVERAGE_ASSESSED` → `DISPATCHED` and
    creates a DispatchJob in `SCHEDULED`" — dispatch is undefined from OPEN.
    PRD §2.8: "the requested transition must exist from the resource's current state,
    terminal states reject every transition, and violations yield `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/service_ticket_dispatch_from_open_rejected
    """
    ctx = setup_accepted_sale()
    ticket = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(ctx["practice"]["id"], ctx["sale"]["id"],
                                          issue_description="hum"),
            DISPATCH,
        ),
        201,
    )
    assert ticket["status"] == "OPEN"
    res = api.dispatch_ticket(
        ticket["id"],
        create_dispatch_payload(
            scheduled_start="2026-08-05T09:00:00Z", scheduled_end="2026-08-05T10:00:00Z"
        ),
        DISPATCH,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_resolve_rejected_when_parts_not_on_van(api):
    """PRD §3.7: "Every part line must be sufficiently stocked on that technician's van: a
    line whose quantity exceeds the van entry's `quantity_on_van` rejects the whole
    resolution with `ERR_PARTS_NOT_ON_VAN`."

    Design: Corner/validations/resolve_rejected_when_parts_not_on_van
    """
    ctx = setup_accepted_sale()
    part = create_product(sku="PT-17", name="Valve", kind="PART", unit_price_cents=15000)
    load_van_stock(ctx["technician"]["id"], part["id"], quantity_on_van=2)
    ctx = setup_ticket_dispatched(accepted=ctx)

    res = api.resolve_ticket(
        ctx["ticket"]["id"],
        create_resolve_payload(
            parts_used=[{"product_id": part["id"], "quantity": 5}], labor_minutes=30
        ),
        make_field_technician_headers(ctx["job_technician_id"]),
    )
    validate_error(res, ApiErrorId.ERR_PARTS_NOT_ON_VAN)
    after = validate_success(api.get_service_ticket(ctx["ticket"]["id"], DISPATCH), 200)
    assert after["status"] == "DISPATCHED"
    tech = validate_success(api.get_technician(ctx["technician"]["id"], ADMIN), 200)
    assert van_stock_quantity(tech, part["id"]) == 2, "Rejected resolve must not debit the van"


def test_service_ticket_billable_fork_and_approval(api):
    """PRD §3.7: "When no active agreement covers the equipment at all, the ticket forks
    instead to `AWAITING_APPROVAL`: `coverage_determination` becomes `BILLABLE`,
    `coverage_agreement_id` stays null, and the practice is shown a flat diagnostic
    `estimate_cents` of 7,500 cents. The billable branch rejoins the main line when a
    `PracticeManager` acting as the ticket's practice (else `ERR_FORBIDDEN`) approves the
    estimate, moving `AWAITING_APPROVAL` → `COVERAGE_ASSESSED`."
    PRD §3.7: "Under `BILLABLE` the practice owes the full gross cost."

    Design: Difficulty/non_linear_state_machine/service_ticket_billable_fork_and_reopen_cycle
    """
    # warranty_months 0 -> warranty spans only the acceptance instant.
    ctx = setup_accepted_sale(
        warranty_months=0, install_window=("2026-08-01T09:00:00Z", "2026-08-01T12:00:00Z")
    )
    set_clock("2026-08-02T00:00:00Z")  # now > warranty end_date -> lazily EXPIRED
    ticket = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(ctx["practice"]["id"], ctx["sale"]["id"],
                                          issue_description="noise"),
            DISPATCH,
        ),
        201,
    )

    assessed = validate_success(api.assess_coverage(ticket["id"], DISPATCH), 200)
    assert assessed["status"] == "AWAITING_APPROVAL"
    assert assessed["coverage_determination"] == "BILLABLE"
    assert assessed["estimate_cents"] == 7500
    assert assessed.get("coverage_agreement_id") is None

    joined = validate_success(
        api.approve_estimate(ticket["id"], make_practice_manager_headers(ctx["practice"]["id"])),
        200,
    )
    assert joined["status"] == "COVERAGE_ASSESSED"

    job = validate_success(
        api.dispatch_ticket(
            ticket["id"],
            create_dispatch_payload(
                scheduled_start="2026-08-03T09:00:00Z", scheduled_end="2026-08-03T10:00:00Z"
            ),
            DISPATCH,
        ),
        200,
    )
    resolved = validate_success(
        api.resolve_ticket(
            ticket["id"],
            create_resolve_payload(parts_used=[], labor_minutes=45),
            make_field_technician_headers(job["technician_id"]),
        ),
        200,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["customer_due_cents"] == 9000, "45 minutes x 200 cents/minute, BILLABLE"


def test_service_ticket_reopen_cycle_to_closed(api):
    """PRD §3.7: "Reopening it, by the same two roles, returns `RESOLVED` → `OPEN` for
    rework" and "the ticket's coverage fields — `coverage_determination`,
    `coverage_agreement_id`, `customer_due_cents`, `parts_used`, `labor_minutes`, and
    `resolved_at` — are all cleared to null, ready for a fresh assessment." and "Closing
    it — by the practice or the dispatcher — moves `RESOLVED` → `CLOSED`, terminal."

    Design: Difficulty/non_linear_state_machine/service_ticket_billable_fork_and_reopen_cycle
    """
    ctx = setup_accepted_sale(
        warranty_months=0, install_window=("2026-08-01T09:00:00Z", "2026-08-01T12:00:00Z")
    )
    set_clock("2026-08-02T00:00:00Z")
    pm = make_practice_manager_headers(ctx["practice"]["id"])
    ticket = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(ctx["practice"]["id"], ctx["sale"]["id"],
                                          issue_description="noise"),
            DISPATCH,
        ),
        201,
    )
    validate_success(api.assess_coverage(ticket["id"], DISPATCH), 200)
    validate_success(api.approve_estimate(ticket["id"], pm), 200)
    job = validate_success(
        api.dispatch_ticket(
            ticket["id"],
            create_dispatch_payload(
                scheduled_start="2026-08-03T09:00:00Z", scheduled_end="2026-08-03T10:00:00Z"
            ),
            DISPATCH,
        ),
        200,
    )
    validate_success(
        api.resolve_ticket(
            ticket["id"], create_resolve_payload(parts_used=[], labor_minutes=45),
            make_field_technician_headers(job["technician_id"]),
        ),
        200,
    )

    reopened = validate_success(api.reopen_ticket(ticket["id"], pm), 200)
    assert reopened["status"] == "OPEN"
    for field in ("coverage_determination", "coverage_agreement_id", "customer_due_cents",
                  "parts_used", "labor_minutes", "resolved_at"):
        assert reopened.get(field) is None, f"{field} must be cleared to null on reopen"

    # Re-traverse the pipeline to CLOSED.
    validate_success(api.assess_coverage(ticket["id"], DISPATCH), 200)
    validate_success(api.approve_estimate(ticket["id"], pm), 200)
    job2 = validate_success(
        api.dispatch_ticket(
            ticket["id"],
            create_dispatch_payload(
                scheduled_start="2026-08-05T09:00:00Z", scheduled_end="2026-08-05T10:00:00Z"
            ),
            DISPATCH,
        ),
        200,
    )
    resolved2 = validate_success(
        api.resolve_ticket(
            ticket["id"], create_resolve_payload(parts_used=[], labor_minutes=15),
            make_field_technician_headers(job2["technician_id"]),
        ),
        200,
    )
    assert resolved2["customer_due_cents"] == 3000, "15 minutes x 200 cents/minute"
    closed = validate_success(api.close_ticket(ticket["id"], DISPATCH), 200)
    assert closed["status"] == "CLOSED"


def test_repair_cost_billable_uses_labor_rate_and_part_snapshot(api):
    """PRD §3.7: "the parts cost is the sum, over the `parts_used` entries, of each
    quantity multiplied by that product's `unit_price_cents` at resolve time; the gross
    cost is the parts cost plus `labor_minutes` at a labor rate of 200 cents per minute."
    and "Under `BILLABLE` the practice owes the full gross cost."

    Design: Corner/calculations/repair_cost_billable_uses_labor_rate_and_part_snapshot
    """
    ctx = setup_accepted_sale(
        warranty_months=0, install_window=("2026-08-01T09:00:00Z", "2026-08-01T12:00:00Z")
    )
    part = create_product(sku="PT-13", name="Valve", kind="PART", unit_price_cents=15000)
    load_van_stock(ctx["technician"]["id"], part["id"], quantity_on_van=5)
    set_clock("2026-08-02T00:00:00Z")  # warranty (0 months) now lazily EXPIRED

    ticket = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(ctx["practice"]["id"], ctx["sale"]["id"],
                                          issue_description="clank"),
            DISPATCH,
        ),
        201,
    )
    assessed = validate_success(api.assess_coverage(ticket["id"], DISPATCH), 200)
    assert assessed["coverage_determination"] == "BILLABLE"
    validate_success(
        api.approve_estimate(ticket["id"], make_practice_manager_headers(ctx["practice"]["id"])),
        200,
    )
    job = validate_success(
        api.dispatch_ticket(
            ticket["id"],
            create_dispatch_payload(
                scheduled_start="2026-08-03T09:00:00Z", scheduled_end="2026-08-03T10:00:00Z"
            ),
            DISPATCH,
        ),
        200,
    )
    resolved = validate_success(
        api.resolve_ticket(
            ticket["id"],
            create_resolve_payload(
                parts_used=[{"product_id": part["id"], "quantity": 2}], labor_minutes=30
            ),
            make_field_technician_headers(job["technician_id"]),
        ),
        200,
    )
    assert resolved["customer_due_cents"] == 36000, "2 x 15000 parts + 30 x 200 labor"


def test_repair_cost_warranty_vs_service_plan_divergence(api):
    """PRD §3.7: "Under `WARRANTY` the practice owes nothing — `customer_due_cents` is zero
    and the warranty's `used_cents` is untouched. Under `SERVICE_PLAN`, the remaining cap
    is the agreement's `coverage_cap_cents` minus its `used_cents` (treated as unlimited
    when the cap is null); the plan's share is the smaller of two floors — the gross cost
    minus the `deductible_cents`, never below zero, and the remaining cap, never below zero
    — the practice owes the gross cost minus that plan share, and the agreement's
    `used_cents` is debited by the plan share."

    Design: Difficulty/dual_variant_calc/repair_cost_warranty_vs_service_plan_divergence
    """
    practice = create_practice(
        name="P Repair", credit_limit_cents=10000000,
        regulated_license_expiry="2030-01-01T00:00:00Z", sterilization_compliant=True,
    )
    eq1 = create_product(sku="EQ-1", name="Chair", kind="EQUIPMENT",
                         unit_price_cents=500000, warranty_months=12)
    eq2 = create_product(sku="EQ-2", name="XRay", kind="EQUIPMENT",
                         unit_price_cents=500000, warranty_months=1)
    part = create_product(sku="PT-1", name="Valve", kind="PART", unit_price_cents=15000)
    tech = create_technician(name="T1", certifications=["INSTALL", "REPAIR"])
    load_van_stock(tech["id"], part["id"], quantity_on_van=10)

    s1 = drive_sale_to_accepted(
        practice, eq1, tech, install_window=("2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")
    )
    s2 = drive_sale_to_accepted(
        practice, eq2, tech, install_window=("2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z")
    )
    plan2 = create_service_plan(
        practice["id"], s2["id"], deductible_cents=5000, coverage_cap_cents=100000,
        start_date="2026-08-01T00:00:00Z", end_date="2028-08-01T00:00:00Z",
    )
    set_clock("2026-10-01T00:00:00Z")  # S2's 1-month warranty lazily EXPIRED; plan ACTIVE

    results = {}
    for key, sale, window in (
        ("k1", s1, ("2026-10-02T09:00:00Z", "2026-10-02T10:00:00Z")),
        ("k2", s2, ("2026-10-02T10:00:00Z", "2026-10-02T11:00:00Z")),
    ):
        ticket = open_and_assess_ticket(practice["id"], sale["id"], "leak")
        job = validate_success(
            api.dispatch_ticket(
                ticket["id"],
                create_dispatch_payload(scheduled_start=window[0], scheduled_end=window[1]),
                DISPATCH,
            ),
            200,
        )
        assert job["technician_id"] == tech["id"]
        resolved = validate_success(
            api.resolve_ticket(
                ticket["id"],
                create_resolve_payload(
                    parts_used=[{"product_id": part["id"], "quantity": 1}], labor_minutes=60
                ),
                make_field_technician_headers(job["technician_id"]),
            ),
            200,
        )
        results[key] = (ticket, resolved)

    k1_ticket, k1_resolved = results["k1"]
    k2_ticket, k2_resolved = results["k2"]
    assert k1_ticket["coverage_determination"] == "WARRANTY"
    assert k1_resolved["customer_due_cents"] == 0, "WARRANTY: practice owes nothing"
    assert k2_ticket["coverage_determination"] == "SERVICE_PLAN"
    # Identical inputs: 1 x 15000 part + 60 x 200 labor = 27000 gross.
    # plan_share = min(27000 - 5000 deductible, 100000 cap) = 22000; due = 5000.
    assert k2_resolved["customer_due_cents"] == 5000

    plan_after = validate_success(api.get_coverage_agreement(plan2["id"], ADMIN), 200)
    assert plan_after["used_cents"] == 22000


def test_repair_cost_service_plan_cap_binds_and_exhausts(api):
    """PRD §3.7: "the plan's share is the smaller of two floors — the gross cost minus the
    `deductible_cents`, never below zero, and the remaining cap, never below zero" and
    "a capped plan whose `used_cents` now reaches or exceeds its `coverage_cap_cents`
    flips `ACTIVE` → `EXHAUSTED`."

    Design: Difficulty/dual_variant_calc/repair_cost_warranty_vs_service_plan_divergence
    """
    practice = create_practice(name="P Cap", credit_limit_cents=10000000)
    eq = create_product(sku="EQ-2C", name="XRay", kind="EQUIPMENT",
                        unit_price_cents=500000, warranty_months=1)
    part = create_product(sku="PT-1C", name="Valve", kind="PART", unit_price_cents=15000)
    tech = create_technician(name="T1C", certifications=["INSTALL", "REPAIR"])
    load_van_stock(tech["id"], part["id"], quantity_on_van=10)
    sale = drive_sale_to_accepted(practice, eq, tech)
    plan = create_service_plan(
        practice["id"], sale["id"], deductible_cents=5000, coverage_cap_cents=10000
    )
    set_clock("2026-10-01T00:00:00Z")  # warranty expired; plan ACTIVE

    ticket = open_and_assess_ticket(practice["id"], sale["id"], "leak")
    assert ticket["coverage_determination"] == "SERVICE_PLAN"
    job = validate_success(
        api.dispatch_ticket(
            ticket["id"],
            create_dispatch_payload(
                scheduled_start="2026-10-02T09:00:00Z", scheduled_end="2026-10-02T10:00:00Z"
            ),
            DISPATCH,
        ),
        200,
    )
    resolved = validate_success(
        api.resolve_ticket(
            ticket["id"],
            create_resolve_payload(
                parts_used=[{"product_id": part["id"], "quantity": 1}], labor_minutes=60
            ),
            make_field_technician_headers(job["technician_id"]),
        ),
        200,
    )
    # gross 27000; plan_share = min(27000 - 5000, 10000 remaining cap) = 10000.
    assert resolved["customer_due_cents"] == 17000
    plan_after = validate_success(api.get_coverage_agreement(plan["id"], ADMIN), 200)
    assert plan_after["used_cents"] == 10000
    assert plan_after["status"] == "EXHAUSTED", "used_cents reached the coverage cap"


def test_coverage_determination_prefers_warranty_over_plan(api):
    """PRD §3.7: "If any candidate is a `WARRANTY`, it wins outright:
    `coverage_determination` becomes `WARRANTY` and the ticket moves `OPEN` →
    `COVERAGE_ASSESSED` with `coverage_agreement_id` pointing at that warranty."

    Design: Corner/calculations/coverage_determination_prefers_warranty_over_plan
    """
    ctx = setup_accepted_sale(warranty_months=12)
    create_service_plan(
        ctx["practice"]["id"], ctx["sale"]["id"],
        deductible_cents=5000, coverage_cap_cents=100000,
        start_date="2026-08-01T00:00:00Z", end_date="2028-08-01T00:00:00Z",
    )
    ticket = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(ctx["practice"]["id"], ctx["sale"]["id"],
                                          issue_description="hum"),
            DISPATCH,
        ),
        201,
    )
    assessed = validate_success(api.assess_coverage(ticket["id"], DISPATCH), 200)
    assert assessed["coverage_determination"] == "WARRANTY"
    assert assessed["coverage_agreement_id"] == ctx["warranty_agreement_id"]
    assert assessed["status"] == "COVERAGE_ASSESSED"


def test_coverage_lazy_expiry_end_date_inclusive(api):
    """PRD §2.5: "A CoverageAgreement whose `status` is still `ACTIVE` flips to `EXPIRED` —
    persisted, not just displayed — whenever the agreement is read or used and the logical
    now is strictly after its `end_date`; its coverage window is inclusive on both ends, so
    coverage applies while now is on or after `start_date` and on or before `end_date`."

    Design: Corner/calculations/coverage_lazy_expiry_end_date_inclusive
    """
    ctx = setup_accepted_sale(warranty_months=1)  # end_date == 2026-09-01T00:00:00Z

    set_clock("2026-09-01T00:00:00Z")  # exactly end_date: still covered
    k1 = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(ctx["practice"]["id"], ctx["sale"]["id"],
                                          issue_description="at boundary"),
            DISPATCH,
        ),
        201,
    )
    a1 = validate_success(api.assess_coverage(k1["id"], DISPATCH), 200)
    assert a1["coverage_determination"] == "WARRANTY", "end_date is inclusive"

    set_clock("2026-09-01T00:00:01Z")  # one second past: strictly after end_date
    k2 = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(ctx["practice"]["id"], ctx["sale"]["id"],
                                          issue_description="one second past"),
            DISPATCH,
        ),
        201,
    )
    a2 = validate_success(api.assess_coverage(k2["id"], DISPATCH), 200)
    assert a2["coverage_determination"] == "BILLABLE"
    assert a2["status"] == "AWAITING_APPROVAL"


def test_reopen_window_boundary_30_days(api):
    """PRD §3.7: "Reopening it, by the same two roles, returns `RESOLVED` → `OPEN` for
    rework, but only while the logical now is within thirty days of `resolved_at`; later
    attempts are rejected with `ERR_REOPEN_WINDOW_EXPIRED`."

    Design: Corner/validations/reopen_window_boundary_30_days
    """
    ctx = setup_accepted_sale(
        warranty_months=12, install_window=("2026-08-01T06:00:00Z", "2026-08-01T08:00:00Z")
    )
    tickets = []
    for issue, window in (
        ("k1", ("2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z")),
        ("k2", ("2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")),
    ):
        ticket = open_and_assess_ticket(ctx["practice"]["id"], ctx["sale"]["id"], issue)
        job = validate_success(
            api.dispatch_ticket(
                ticket["id"],
                create_dispatch_payload(scheduled_start=window[0], scheduled_end=window[1]),
                DISPATCH,
            ),
            200,
        )
        resolved = validate_success(
            api.resolve_ticket(
                ticket["id"], create_resolve_payload(parts_used=[], labor_minutes=10),
                make_field_technician_headers(job["technician_id"]),
            ),
            200,
        )
        tickets.append(resolved)
    # Both resolved at the default logical clock 2026-08-01T00:00:00Z.
    k1, k2 = tickets

    set_clock("2026-08-31T00:00:00Z")  # exactly 30 days later
    reopened = validate_success(api.reopen_ticket(k1["id"], DISPATCH), 200)
    assert reopened["status"] == "OPEN", "Reopen at exactly 30 days is within the window"

    set_clock("2026-09-01T00:00:00Z")  # 31 days later
    res = api.reopen_ticket(k2["id"], DISPATCH)
    validate_error(res, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)
    after = validate_success(api.get_service_ticket(k2["id"], DISPATCH), 200)
    assert after["status"] == "RESOLVED"


def test_van_stock_resolve_reopen_conservation(api):
    """PRD §3.7: "First, each reported part is debited from the resolving technician's
    `van_stock`." and "Reopening is a full compensation of resolution: the reported parts
    are credited back onto the resolving technician's van".

    Design: Difficulty/compensating_invariant/van_stock_resolve_reopen_conservation
    """
    ctx = setup_accepted_sale(warranty_months=12)
    part = create_product(sku="PT-9", name="Valve", kind="PART", unit_price_cents=15000)
    load_van_stock(ctx["technician"]["id"], part["id"], quantity_on_van=10)
    tech = validate_success(api.get_technician(ctx["technician"]["id"], ADMIN), 200)
    assert van_stock_quantity(tech, part["id"]) == 10

    ctx = setup_ticket_dispatched(
        accepted=ctx, dispatch_window=("2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z")
    )
    resolved = validate_success(
        api.resolve_ticket(
            ctx["ticket"]["id"],
            create_resolve_payload(
                parts_used=[{"product_id": part["id"], "quantity": 2}], labor_minutes=10
            ),
            make_field_technician_headers(ctx["job_technician_id"]),
        ),
        200,
    )
    tech = validate_success(api.get_technician(ctx["technician"]["id"], ADMIN), 200)
    assert van_stock_quantity(tech, part["id"]) == 8, "Resolve debits 2 units"

    reopened = validate_success(
        api.reopen_ticket(
            ctx["ticket"]["id"], make_practice_manager_headers(ctx["practice"]["id"])
        ),
        200,
    )
    assert reopened["status"] == "OPEN"
    assert reopened.get("customer_due_cents") is None
    tech = validate_success(api.get_technician(ctx["technician"]["id"], ADMIN), 200)
    assert van_stock_quantity(tech, part["id"]) == 10, "Reopen restores the van exactly"


def test_van_stock_stays_debited_after_close(api):
    """PRD §3.7: "Closing it — by the practice or the dispatcher — moves `RESOLVED` →
    `CLOSED`, terminal." — the parts compensation belongs to reopen alone ("Reopening is a
    full compensation of resolution: the reported parts are credited back onto the
    resolving technician's van").
    PRD §2.8: "terminal states reject every transition, and violations yield
    `ERR_INVALID_STATE` (409)."

    Design: Difficulty/compensating_invariant/van_stock_resolve_reopen_conservation
    """
    ctx = setup_accepted_sale(warranty_months=12)
    part = create_product(sku="PT-9C", name="Valve", kind="PART", unit_price_cents=15000)
    load_van_stock(ctx["technician"]["id"], part["id"], quantity_on_van=10)
    ctx = setup_ticket_dispatched(accepted=ctx)
    validate_success(
        api.resolve_ticket(
            ctx["ticket"]["id"],
            create_resolve_payload(
                parts_used=[{"product_id": part["id"], "quantity": 2}], labor_minutes=10
            ),
            make_field_technician_headers(ctx["job_technician_id"]),
        ),
        200,
    )
    closed = validate_success(api.close_ticket(ctx["ticket"]["id"], DISPATCH), 200)
    assert closed["status"] == "CLOSED"

    tech = validate_success(api.get_technician(ctx["technician"]["id"], ADMIN), 200)
    assert van_stock_quantity(tech, part["id"]) == 8, "Close performs no compensation"

    res = api.reopen_ticket(ctx["ticket"]["id"], DISPATCH)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    tech = validate_success(api.get_technician(ctx["technician"]["id"], ADMIN), 200)
    assert van_stock_quantity(tech, part["id"]) == 8


def test_dispatch_with_no_eligible_technician_rejected(api):
    """PRD §3.7: "The selector then builds its candidate pool: technicians who are
    `ACTIVE`, hold `REPAIR` certification, share the ticket practice's `region`, and whose
    calendars show no half-open overlap" and "An empty pool rejects the dispatch with
    `ERR_TECHNICIAN_UNAVAILABLE`."

    Design: Corner/validations/dispatch_with_no_eligible_technician_rejected
    """
    # The only technician lives in region R2 while the practice is in R1.
    ctx = setup_accepted_sale(region="R2", practice_overrides={"region": "R1"})
    ticket = open_and_assess_ticket(ctx["practice"]["id"], ctx["sale"]["id"], "rattle")
    assert ticket["status"] == "COVERAGE_ASSESSED"
    res = api.dispatch_ticket(
        ticket["id"],
        create_dispatch_payload(
            scheduled_start="2026-08-05T09:00:00Z", scheduled_end="2026-08-05T10:00:00Z"
        ),
        DISPATCH,
    )
    validate_error(res, ApiErrorId.ERR_TECHNICIAN_UNAVAILABLE)
    after = validate_success(api.get_service_ticket(ticket["id"], DISPATCH), 200)
    assert after["status"] == "COVERAGE_ASSESSED"


def test_dispatch_selector_tie_break_by_created_at(api):
    """PRD §3.7: "The pool is ranked by each candidate's total already-scheduled minutes
    intersecting the requested calendar day — midnight of that day to midnight of the next —
    ascending, so the least-loaded eligible technician wins; ties break by the technician's
    `created_at`, earliest first."

    Design: Corner/cross_cutting_complexity_layers/dispatch_selector_tie_break_by_created_at
    """
    practice = create_practice(name="P Sel", credit_limit_cents=10000000)
    product = create_product(sku="EQ-24", kind="EQUIPMENT", unit_price_cents=500000,
                             warranty_months=12)
    t1 = create_technician(name="T1", certifications=["INSTALL", "REPAIR"])
    t2 = create_technician(name="T2", certifications=["INSTALL", "REPAIR"])
    sale = drive_sale_to_accepted(practice, product, t1)

    k1 = open_and_assess_ticket(practice["id"], sale["id"], "k1")
    k2 = open_and_assess_ticket(practice["id"], sale["id"], "k2")
    window = create_dispatch_payload(
        scheduled_start="2026-08-05T09:00:00Z", scheduled_end="2026-08-05T10:00:00Z"
    )
    j1 = validate_success(api.dispatch_ticket(k1["id"], window, DISPATCH), 200)
    assert j1["technician_id"] == t1["id"], (
        "Both candidates tie on 0 scheduled minutes; earliest created_at wins"
    )
    j2 = validate_success(api.dispatch_ticket(k2["id"], window, DISPATCH), 200)
    assert j2["technician_id"] == t2["id"], (
        "T1 now overlaps the window, so the pool holds only T2"
    )


def test_field_technician_cannot_dispatch_tickets(api):
    """PRD §2.1: "A request whose role is not permitted on the targeted endpoint, or that
    fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/service-tickets/{id}/dispatch is authorized for ServiceDispatcher only.

    Design: Corner/rbac/field_technician_cannot_dispatch_tickets
    """
    ctx = setup_ticket_assessed()
    res = api.dispatch_ticket(
        ctx["ticket"]["id"],
        create_dispatch_payload(
            scheduled_start="2026-08-05T09:00:00Z", scheduled_end="2026-08-05T10:00:00Z"
        ),
        make_field_technician_headers(ctx["technician"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
