"""Role boundaries: peer exclusives, entity-backed ownership and separated duties."""

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_ALT_HEADERS,
    CONTROLLER_HEADERS,
    ApiErrorId,
    assert_cents,
    assert_invoice_dimensions,
    factories,
    fixtures,
    make_business_unit_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_analyst_cannot_publish_and_the_controller_cannot_compute(api):
    """Each peer role is denied the other's step and then succeeds at its own.

    PRD §2.1: "Analysts draft tagging policies, drive provisioning requests
    through retag, approval and provisioning, open allocation runs, attach and
    seal shared cost pools, absorb untagged spend, compute runs, run the
    idle-detection scan, the remediation-window sweep and the anomaly scan,
    notify resource owners, and acknowledge and attribute anomaly alerts."

    Design: Corner/rbac/analyst_cannot_publish_and_controller_cannot_compute
    """
    fixtures.set_clock(api)
    unit = fixtures.create_chargeback_unit(api)
    record = fixtures.create_untagged_record(api, 3000)
    built = fixtures.shared_pool_run(
        api, [unit["id"]], [record["id"]], mode="CHARGEBACK", do_compute=False
    )
    run_id = built["run"]["id"]

    controller_compute = api.compute_allocation_run(run_id, "FINAL", CONTROLLER_HEADERS)
    validate_error(controller_compute, ApiErrorId.UNAUTHORIZED.value, 403)
    still_draft = validate_success(api.get_allocation_run(run_id, ANALYST_HEADERS))
    assert still_draft["status"] == "DRAFT"

    computed = validate_success(api.compute_allocation_run(run_id, "FINAL", ANALYST_HEADERS))
    assert computed["status"] == "COMPUTED_FINAL"
    assert_cents(computed["total_allocated_cents"], 3000, "total_allocated_cents")

    analyst_publish = api.publish_allocation_run(run_id, ANALYST_HEADERS)
    validate_error(analyst_publish, ApiErrorId.UNAUTHORIZED.value, 403)
    unpublished = validate_success(api.get_allocation_run(run_id, ANALYST_HEADERS))
    assert unpublished["status"] == "COMPUTED_FINAL"
    _, no_invoices = validate_paginated(
        api.list_chargeback_invoices(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert no_invoices["total_count"] == 0

    published = validate_success(api.publish_allocation_run(run_id, CONTROLLER_HEADERS))
    assert published["status"] == "PUBLISHED"
    _, invoiced = validate_paginated(
        api.list_chargeback_invoices(CONTROLLER_HEADERS, {"allocation_run_id": run_id})
    )
    assert invoiced["total_count"] == 1


def test_a_unit_owner_may_not_settle_or_dispute_another_units_invoice(api):
    """A real owner identity bound to the wrong unit is refused on both actions.

    PRD §2.1: "Concretely, settling an invoice, filing a dispute, responding to
    an information request, withdrawing a dispute and recording a variance
    explanation all require `X-User-ID` to equal the `business_unit_id` of the
    invoice or budget being acted on, or the `filed_by_business_unit_id` of the
    dispute being acted on."

    Design: Corner/rbac/business_unit_owner_cannot_settle_another_units_invoice
    """
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    billed = fixtures.create_chargeback_unit(api)
    impostor_unit = fixtures.create_chargeback_unit(api, "Marketing", "CC-600", headcount=5)
    built = fixtures.issued_chargeback_invoice(api, billed["id"], 5000)
    invoice_id = built["invoice"]["id"]

    impostor = make_business_unit_owner_headers(impostor_unit["id"])
    wrong_settle = api.settle_invoice(invoice_id, 5000, impostor)
    validate_error(wrong_settle, ApiErrorId.NOT_RESOURCE_OWNER.value, 403)

    untouched = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_dimensions(untouched, settlement_status="ISSUED", dispute_status="NONE")
    assert_cents(untouched["paid_amount_cents"], 0, "paid_amount_cents")

    wrong_dispute = api.create_dispute(
        factories.dispute_payload(invoice_id, narrative="not ours"), impostor
    )
    validate_error(wrong_dispute, ApiErrorId.NOT_RESOURCE_OWNER.value, 403)

    undisputed = validate_success(api.get_chargeback_invoice(invoice_id, CONTROLLER_HEADERS))
    assert_invoice_dimensions(undisputed, settlement_status="ISSUED", dispute_status="NONE")

    settled = validate_success(
        api.settle_invoice(invoice_id, 5000, make_business_unit_owner_headers(billed["id"]))
    )
    assert settled["settlement_status"] == "SETTLED"

    impostor_read = validate_success(api.get_business_unit(impostor_unit["id"], ADMIN_HEADERS))
    assert_cents(impostor_read["chargeback_balance_cents"], 0, "chargeback_balance_cents")


def test_the_analyst_shares_budget_drafting_but_not_budget_activation(api):
    """Two shared operations succeed for the analyst; the adjacent exclusive one does not.

    PRD §2.1: "Both roles share the ability to draft a tagging policy, open an
    allocation run, create, revise and evaluate budgets, register and compute
    unit economics drivers, and read every resource in the system."

    Design: Corner/rbac/budget_create_and_revise_are_shared_but_the_analyst_cannot_activate
    """
    fixtures.set_clock(api)
    unit = fixtures.create_business_unit(api)

    budget = validate_success(
        api.create_budget(
            factories.budget_payload(unit["id"], amount_cents=10000, forecast_cents=9000),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert budget["status"] == "DRAFT"
    assert_cents(budget["forecast_cents"], 9000, "forecast_cents")
    assert budget["revision_count"] == 0
    assert budget["forecast_history"] == []

    revised = validate_success(
        api.revise_budget(
            budget["id"],
            {"expected_budget_version": budget["version"], "forecast_cents": 9500},
            ANALYST_HEADERS,
        )
    )
    assert_cents(revised["forecast_cents"], 9500, "forecast_cents")
    assert revised["forecast_history"] == [9000]
    assert revised["revision_count"] == 1
    assert revised["version"] == budget["version"] + 1

    analyst_activate = api.activate_budget(budget["id"], ANALYST_HEADERS)
    validate_error(analyst_activate, ApiErrorId.UNAUTHORIZED.value, 403)
    still_draft = validate_success(api.get_budget(budget["id"], ANALYST_HEADERS))
    assert still_draft["status"] == "DRAFT"

    activated = validate_success(api.activate_budget(budget["id"], CONTROLLER_HEADERS))
    assert activated["status"] == "ACTIVE"


def test_the_controller_who_drafted_a_policy_may_not_activate_it_himself(api):
    """The refusal keys on the acting user id, so a second controller succeeds.

    PRD §2.9: "The activating user of a tagging policy must differ from the
    policy's `created_by_user_id`."

    Design: Corner/rbac/the_controller_who_drafted_a_policy_cannot_activate_it
    """
    drafted = validate_success(
        api.create_tagging_policy(factories.tagging_policy_payload(), CONTROLLER_HEADERS),
        201,
    )
    assert drafted["created_by_user_id"] == "controller-1"
    assert drafted["status"] == "DRAFT"
    assert drafted["activated_by_user_id"] is None

    self_activation = api.activate_tagging_policy(drafted["id"], CONTROLLER_HEADERS)
    validate_error(self_activation, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

    unchanged = validate_success(api.get_tagging_policy(drafted["id"], CONTROLLER_HEADERS))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["version"] == drafted["version"]

    activated = validate_success(
        api.activate_tagging_policy(drafted["id"], CONTROLLER_ALT_HEADERS)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["activated_by_user_id"] == "controller-2"
