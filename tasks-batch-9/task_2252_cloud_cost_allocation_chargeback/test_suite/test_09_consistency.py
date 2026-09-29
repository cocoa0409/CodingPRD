"""Consistency model: the whole cascade is visible in the response that caused it."""

from test_helpers import (
    ADMIN_HEADERS,
    CONTROLLER_HEADERS,
    assert_cents,
    assert_invoice_dimensions,
    assert_invoice_ledger,
    fixtures,
    validate_paginated,
    validate_success,
)


def test_publishing_a_run_reports_its_whole_cascade_in_the_same_response(api):
    """No follow-up read is needed to see the invoice, the record and the balance.

    PRD §2.7: "Cascades therefore run to completion in a single request,
    immediately and synchronously."

    Design: Corner/consistency model/publish_cascade_is_fully_visible_in_the_publishing_response
    """
    fixtures.set_clock(api)
    unit = fixtures.create_chargeback_unit(api)
    record = fixtures.create_untagged_record(api, 7000)
    built = fixtures.shared_pool_run(
        api, [unit["id"]], [record["id"]], mode="CHARGEBACK"
    )
    pool_id = built["pool"]["id"]

    published = validate_success(
        api.publish_allocation_run(built["run"]["id"], CONTROLLER_HEADERS)
    )
    assert published["status"] == "PUBLISHED"
    assert_cents(published["total_allocated_cents"], 7000, "total_allocated_cents")
    assert published["line_count"] == 1
    assert published["published_by_user_id"] == "controller-1"

    invoices, meta = validate_paginated(
        api.list_chargeback_invoices(
            CONTROLLER_HEADERS, {"allocation_run_id": built["run"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert_invoice_ledger(invoices[0], 7000, 0, 0, 7000)
    assert_invoice_dimensions(
        invoices[0], settlement_status="UNBILLED", dispute_status="NONE"
    )

    allocated = validate_success(api.get_cost_record(record["id"], CONTROLLER_HEADERS))
    assert allocated["allocation_state"] == "ALLOCATED"
    assert allocated["allocated_by_run_id"] == built["run"]["id"]
    assert allocated["shared_cost_pool_id"] == pool_id

    charged = validate_success(api.get_business_unit(unit["id"], ADMIN_HEADERS))
    assert_cents(charged["chargeback_balance_cents"], 7000, "chargeback_balance_cents")
    assert_cents(charged["showback_total_cents"], 0, "showback_total_cents")
