"""Monthly rate-readiness audits and annual volume rebate (PRD §3.1)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_released_po,
    create_work_order,
    create_accepted_cert,
    set_clock,
    setup_wo_in_production,
    get_success_data,
    validate_success,
)

CM = TEST_USERS["contracts_manager"]
MP = TEST_USERS["manufacturing_planner"]
QM = TEST_USERS["quality_manager"]


def test_rate_readiness_auto_suspend_at_two(api):
    """PRD §3.1: "A percentage of at least 100 records a `READY` result in
    `last_audit_result`; at least 80 but below 100 records `MARGINAL`; below 80
    records `NOT_READY`."
    PRD §3.1: "A `NOT_READY` outcome increments `consecutive_not_ready_count`
    by one; any `READY` or `MARGINAL` outcome resets it to zero."
    PRD §3.1: "When `consecutive_not_ready_count` reaches 2, the agreement
    transitions `ACTIVE → SUSPENDED` automatically, with no human in the loop."

    Design: Corner/calculations/rate_readiness_auto_suspend_at_two
    """
    bundle = setup_wo_in_production(
        wo_quantity=75,
        lta_overrides={
            "committed_monthly_rate_units": 100,
            "escalation_pct_per_year": 0.0,
        },
        quantity=75,
    )
    lta_id = bundle["lta"]["id"]
    # Complete the 75-unit work order in the default-clock month (August 2026).
    get_success_data(api_client.complete_work_order(bundle["wo"]["id"], MP))
    get_success_data(api_client.accept_work_order(bundle["wo"]["id"], TEST_USERS["customer_quality_rep"]))

    # August audit: 75/100 = 75% -> NOT_READY, count 1, still ACTIVE.
    audit1 = validate_success(api_client.run_rate_audit(lta_id, QM), expected_status=200)
    assert audit1["last_audit_result"] == "NOT_READY", (
        f"75 < 80 must record NOT_READY, got {audit1['last_audit_result']}"
    )
    assert audit1["consecutive_not_ready_count"] == 1
    assert audit1["status"] == "ACTIVE"
    assert audit1["last_audit_month"] == "2026-08"

    # September audit: nothing completed this month -> 0% -> second consecutive
    # NOT_READY -> automatic suspension.
    set_clock("2026-09-01T00:00:00Z")
    audit2 = validate_success(api_client.run_rate_audit(lta_id, QM), expected_status=200)
    assert audit2["last_audit_result"] == "NOT_READY"
    assert audit2["consecutive_not_ready_count"] == 2
    assert audit2["status"] == "SUSPENDED", (
        f"two consecutive NOT_READY audits must auto-suspend, got {audit2['status']}"
    )


def test_rate_readiness_rerun_replaces_and_resets(api):
    """PRD §3.1: "Re-running the audit within the same calendar month replaces
    the stored result rather than double-counting: the consecutive count is
    adjusted to exactly what it would be if this rerun were the month's only
    audit."
    PRD §3.1: "A percentage of at least 100 records a `READY` result in
    `last_audit_result`; at least 80 but below 100 records `MARGINAL`; below 80
    records `NOT_READY`."

    Design: Corner/calculations/rate_readiness_rerun_replaces_and_resets
    """
    bundle = setup_wo_in_production(
        wo_quantity=80,
        lta_overrides={
            "committed_monthly_rate_units": 100,
            "escalation_pct_per_year": 0.0,
        },
        quantity=80,
    )
    lta_id = bundle["lta"]["id"]
    # First August audit with nothing completed yet: 0% -> NOT_READY, count 1.
    audit1 = validate_success(api_client.run_rate_audit(lta_id, QM), expected_status=200)
    assert audit1["last_audit_result"] == "NOT_READY"
    assert audit1["consecutive_not_ready_count"] == 1

    # Complete 80 units within the same logical month, then re-audit.
    get_success_data(api_client.complete_work_order(bundle["wo"]["id"], MP))
    get_success_data(api_client.accept_work_order(bundle["wo"]["id"], TEST_USERS["customer_quality_rep"]))
    audit2 = validate_success(api_client.run_rate_audit(lta_id, QM), expected_status=200)
    assert audit2["last_audit_result"] == "MARGINAL", (
        f"80/100 = 80% is at least 80 but below 100 -> MARGINAL, got "
        f"{audit2['last_audit_result']}"
    )
    assert audit2["consecutive_not_ready_count"] == 0, (
        f"the same-month rerun replaces the earlier NOT_READY and resets the "
        f"consecutive count, got {audit2['consecutive_not_ready_count']}"
    )
    assert audit2["status"] == "ACTIVE"


def test_rebate_gross_keyed_tier_boundary(api):
    """PRD §3.1: "First, `gross_invoiced_cents` is the sum of `total_cents`
    over the agreement's purchase orders that reached `CLOSED` during the
    requested year — closure being the moment the final serial shipment pushed
    `delivered_quantity` to the ordered quantity, attributed by the logical
    timestamp of that shipment. Second, the selected tier is the rebate-tier
    element with the largest `min_invoiced_cents` that the gross meets or
    exceeds, the boundary being inclusive. Third, `rebate_cents` is the gross
    multiplied by the tier's `rebate_pct`, rounded half up to integer cents.
    Fourth, `net_cents` is the gross minus the rebate."

    Design: Corner/calculations/rebate_gross_keyed_tier_boundary
    """
    bundle = create_released_po(
        lta_overrides={
            "pricing_tiers": [
                {"min_qty": 1, "unit_price_cents": 5000},
                {"min_qty": 100, "unit_price_cents": 4500},
                {"min_qty": 500, "unit_price_cents": 4000},
            ],
            "committed_monthly_rate_units": 3000,
            "escalation_pct_per_year": 0.0,
            "rebate_tiers": [
                {"min_invoiced_cents": 0, "rebate_pct": 0},
                {"min_invoiced_cents": 10000000, "rebate_pct": 0.02},
            ],
        },
        quantity=2500,
    )
    po = bundle["po"]
    assert po["total_cents"] == 2500 * 4000 == 10000000

    wo = create_work_order(po["id"], quantity=2500)
    get_success_data(api_client.release_work_order(wo["id"], MP))
    cert = create_accepted_cert(quantity_received=3000)
    get_success_data(
        api_client.create_serial_batch(
            wo["id"], {"material_cert_id": cert["id"], "count": 2500}, MP
        )
    )
    get_success_data(api_client.complete_work_order(wo["id"], MP))
    get_success_data(api_client.accept_work_order(wo["id"], TEST_USERS["customer_quality_rep"]))
    get_success_data(api_client.ship_all_work_order(wo["id"], MP))

    po_after = get_success_data(api_client.get_purchase_order(po["id"], CM))
    assert po_after["status"] == "CLOSED", (
        f"shipping every unit must close the PO, got {po_after['status']}"
    )

    resp = api_client.get_rebate_preview(bundle["lta"]["id"], CM, params={"year": 2026})
    rebate = validate_success(resp, expected_status=200)
    assert rebate["gross_invoiced_cents"] == 10000000, (
        f"gross keyed on the CLOSED PO total, got {rebate['gross_invoiced_cents']}"
    )
    assert rebate["rebate_pct"] == 0.02, (
        f"gross exactly == min_invoiced_cents selects the 2% tier (inclusive "
        f"boundary), got {rebate['rebate_pct']}"
    )
    assert rebate["rebate_cents"] == 200000
    assert rebate["net_cents"] == 9800000
