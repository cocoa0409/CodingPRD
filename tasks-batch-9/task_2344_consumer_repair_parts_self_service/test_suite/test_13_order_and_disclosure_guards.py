"""Guards along the buyer flow: the disclosure signature, the consumer deposit ceiling
read off the recomputed order, the compliance restriction that only the disclosure hop
can see, and the two-sided fence around a core receipt.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    CUSTOMER_ALT,
    api_client,
    assert_core_ledger_aggregates,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _acknowledgment(order_id, warranty_class, warning_version, scope, headers=CUSTOMER):
    return api_client.create_acknowledgment(
        order_id,
        factories.acknowledgment_payload(warranty_class, warning_version, scope),
        headers,
    )


def test_the_disclosure_signature_is_gated_by_class_then_version_then_ownership():
    """PRD §3.6: "A warranty class that does not match, or a `TOOL_RENTAL_ONLY` scope on
    an order that holds a component line, is refused with `ERR_DISCLOSURE_MISMATCH`."
    PRD §3.6: "A `liability_warning_version` other than the pinned one is refused with
    `ERR_LIABILITY_WARNING_STALE` — the model's published documentation has moved on
    since the ruling was issued, and the buyer would be signing the wrong warning text."
    PRD §2.1: "A `SelfRepairCustomer` acting on an order or an assessment whose recorded
    owner differs from the caller is rejected with `ERR_ORDER_NOT_OWNED` (403)."
    PRD §3.6: "Its `disclosure_acknowledged_at` must not be null, and there must exist an
    acknowledgment whose `acknowledged_scope` actually covers the order's contents —
    `FULL_SELF_REPAIR` for a consumer order containing components, `PROVIDER_MANAGED` for
    a provider order, and `TOOL_RENTAL_ONLY` only for an order limited to rentals and
    tools; a failure here is refused with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."

    Design: Corner/validations/disclosure_guards_reject_a_mismatched_class_a_stale_warning_and_a_foreign_customer
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-V04",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={"sku": "SKU-V04-A", "list_price_cents": 1000},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    bundle = fixtures.build_pending_disclosure_order(setup, 1, CUSTOMER)
    order_id = bundle["order"]["id"]

    assert bundle["order"]["warranty_impact_class"] == "WARRANTY_PRESERVED_WITH_LOG", (
        bundle["order"]["warranty_impact_class"]
    )
    assert bundle["assessment"]["liability_warning_version"] == "LW-CRX-V04-R1", (
        bundle["assessment"]["liability_warning_version"]
    )

    unsigned_confirm = api_client.confirm_order(order_id, CUSTOMER)
    validate_error(unsigned_confirm, "ERR_DISCLOSURE_NOT_ACKNOWLEDGED", 422)
    assert fixtures.read_order(order_id)["fulfillment_status"] == "PENDING_DISCLOSURE", (
        "an unsigned order may not advance"
    )

    both_wrong = _acknowledgment(
        order_id,
        "WARRANTY_VOID_AFFECTED_SUBSYSTEM",
        "LW-CRX-V04-R9",
        "FULL_SELF_REPAIR",
    )
    validate_error(both_wrong, "ERR_DISCLOSURE_MISMATCH", 422)

    stale_version = _acknowledgment(
        order_id, "WARRANTY_PRESERVED_WITH_LOG", "LW-CRX-V04-R9", "FULL_SELF_REPAIR"
    )
    validate_error(stale_version, "ERR_LIABILITY_WARNING_STALE", 409)

    rental_scope = _acknowledgment(
        order_id, "WARRANTY_PRESERVED_WITH_LOG", "LW-CRX-V04-R1", "TOOL_RENTAL_ONLY"
    )
    validate_error(rental_scope, "ERR_DISCLOSURE_MISMATCH", 422)

    foreign_signer = _acknowledgment(
        order_id,
        "WARRANTY_PRESERVED_WITH_LOG",
        "LW-CRX-V04-R1",
        "FULL_SELF_REPAIR",
        CUSTOMER_ALT,
    )
    validate_error(foreign_signer, "ERR_ORDER_NOT_OWNED", 403)

    signed = validate_success(
        _acknowledgment(
            order_id, "WARRANTY_PRESERVED_WITH_LOG", "LW-CRX-V04-R1", "FULL_SELF_REPAIR"
        ),
        201,
    )
    assert signed["manual_revision_number"] == 1, signed["manual_revision_number"]

    confirmed = validate_success(api_client.confirm_order(order_id, CUSTOMER), 200)
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        f"the satisfied signature clears every disclosure gate, got "
        f"{confirmed['fulfillment_status']}"
    )

    rows, page_meta = validate_paginated(
        api_client.list_acknowledgments_for_order(order_id, CUSTOMER)
    )
    assert page_meta["total_count"] == 1, (
        f"the five refused attempts persisted nothing, got {page_meta['total_count']}"
    )
    assert rows[0]["id"] == signed["id"], rows[0]["id"]


def test_the_consumer_deposit_ceiling_reads_the_recomputed_order_not_the_new_line():
    """PRD §3.6: "One consumer protection sits on top of the core deposit. A consumer
    order whose recomputed `core_deposit_cents` would exceed five hundred dollars —
    50000 cents — is refused with `ERR_CORE_DEPOSIT_CAP_EXCEEDED`, and that ceiling is
    checked both when a line is appended and when disclosure is requested."
    PRD §3.6: "`core_deposit_cents` is the sum, across lines whose part has
    `core_return_required` true, of that part's `core_credit_cents` multiplied by the
    line's `quantity`."

    Design: Corner/validations/consumer_core_deposit_cap_rejects_the_aggregate_of_two_individually_valid_lines
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-V05",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={
            "sku": "SKU-V05-CORE",
            "list_price_cents": 40000,
            "core_return_required": True,
            "core_credit_cents": 26000,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    part_id = setup["part"]["id"]
    assessment = fixtures.create_assessment(
        setup["model"]["id"], part_id, "US-CA", CUSTOMER
    )
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    first_version = order["version"]

    two_units = api_client.append_order_line(
        order["id"],
        factories.order_line_payload(part_id, first_version, 2),
        CUSTOMER,
    )
    validate_error(two_units, "ERR_CORE_DEPOSIT_CAP_EXCEEDED", 422)

    accepted = validate_success(
        api_client.append_order_line(
            order["id"],
            factories.order_line_payload(part_id, first_version, 1),
            CUSTOMER,
        ),
        201,
    )
    assert accepted["quantity"] == 1, accepted["quantity"]

    after_first = fixtures.read_order(order["id"], CUSTOMER)
    assert after_first["core_deposit_cents"] == 26000, (
        f"one unit sits under the ceiling, got {after_first['core_deposit_cents']}"
    )
    assert after_first["version"] == first_version + 1, (
        f"exactly one append succeeded, got version {after_first['version']}"
    )

    second_unit = api_client.append_order_line(
        order["id"],
        factories.order_line_payload(part_id, after_first["version"], 1),
        CUSTOMER,
    )
    validate_error(second_unit, "ERR_CORE_DEPOSIT_CAP_EXCEEDED", 422)

    lines = fixtures.list_lines(order["id"], CUSTOMER)
    assert len(lines) == 1, (
        f"the individually legal second unit was refused on the order total, got "
        f"{len(lines)} lines"
    )
    assert fixtures.read_order(order["id"], CUSTOMER)["version"] == first_version + 1, (
        "a refused append leaves the version alone"
    )

    disclosed = fixtures.request_disclosure(order["id"], CUSTOMER)
    assert disclosed["core_deposit_cents"] == 26000, disclosed["core_deposit_cents"]
    assert disclosed["documentation_fee_cents"] == 740, (
        f"Expected the 500-cent base plus 120 per warning on two warnings, got "
        f"{disclosed['documentation_fee_cents']}"
    )
    assert disclosed["total_due_cents"] == 66740, (
        f"Expected 40000 parts plus 740 documentation plus 26000 deposit, got "
        f"{disclosed['total_due_cents']}"
    )


def test_an_order_restricted_model_is_only_observable_on_the_disclosure_hop():
    """PRD §3.6: "The referenced part must be in `PUBLISHED` status and must hold a
    compatibility row for this order's model whose half-open window contains the logical
    clock; a part in `DRAFT`, `RESTRICTED`, or `SUPERSEDED` status, or one with no
    in-window fitment, is refused with `ERR_PART_NOT_PUBLISHED`."
    PRD §3.2: "Second: when no catalog part in `PUBLISHED` status holds a compatibility
    row for this model whose window contains the logical clock, the status is
    `BREACHED_PARTS`."
    PRD §3.2: "When any obligation of the model sits in `BREACHED_PARTS` or
    `BREACHED_DOCUMENTATION`, the model's `compliance_posture` becomes
    `ORDER_RESTRICTED`."
    PRD §3.6: "The model's `compliance_posture` must not be `ORDER_RESTRICTED`, otherwise
    `ERR_MODEL_ORDER_RESTRICTED`."

    Design: Corner/validations/model_order_restriction_is_rejected_on_the_disclosure_hop_that_carries_no_part
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-V10",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part_a = fixtures.create_part(sku="SKU-V10-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part_a["id"],
        model["id"],
        effective_from="2026-02-01T00:00:00Z",
        effective_until="2026-08-10T00:00:00Z",
        install_minutes=20,
    )
    fixtures.publish_part(part_a["id"])
    part_b = fixtures.create_part(sku="SKU-V10-B", list_price_cents=1500)
    fixtures.create_compatibility(
        part_b["id"],
        model["id"],
        effective_from="2026-02-01T00:00:00Z",
        install_minutes=25,
    )
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-V10-A"], safety_warning_count=2
    )

    assessment = fixtures.create_assessment(
        model["id"], part_a["id"], "US-CA", CUSTOMER
    )
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    fixtures.append_line(order["id"], part_a["id"], 1, CUSTOMER)
    priced = fixtures.read_order(order["id"], CUSTOMER)

    draft_part = api_client.append_order_line(
        order["id"],
        factories.order_line_payload(part_b["id"], priced["version"], 1),
        CUSTOMER,
    )
    validate_error(draft_part, "ERR_PART_NOT_PUBLISHED", 422)

    fixtures.move_clock("2026-08-11T00:00:00Z")

    lapsed_window = api_client.append_order_line(
        order["id"],
        factories.order_line_payload(
            part_a["id"], fixtures.order_version(order["id"], CUSTOMER), 1
        ),
        CUSTOMER,
    )
    validate_error(lapsed_window, "ERR_PART_NOT_PUBLISHED", 422)

    obligation = fixtures.create_obligation(model["id"], "US-CA", COMPLIANCE)
    assert obligation["status"] == "BREACHED_PARTS", (
        f"no published part holds an in-window row at the new clock, got "
        f"{obligation['status']}"
    )
    assert obligation["breach_count"] == 1, obligation["breach_count"]

    refreshed = fixtures.read_model(model["id"])
    assert refreshed["compliance_posture"] == "ORDER_RESTRICTED", (
        refreshed["compliance_posture"]
    )
    assert refreshed["documentation_posture"] == "CURRENT", (
        f"the guide is not retroactively stale, got {refreshed['documentation_posture']}"
    )

    restricted = api_client.request_disclosure(order["id"], CUSTOMER)
    validate_error(restricted, "ERR_MODEL_ORDER_RESTRICTED", 422)

    still_draft = fixtures.read_order(order["id"], CUSTOMER)
    assert still_draft["fulfillment_status"] == "DRAFT", (
        f"the refused hop leaves the order in draft, got "
        f"{still_draft['fulfillment_status']}"
    )
    assert still_draft["total_due_cents"] == priced["total_due_cents"], (
        f"the money is untouched by the refusal, got {still_draft['total_due_cents']}"
    )


def test_a_core_receipt_is_fenced_on_both_sides_and_a_kit_needs_a_declared_window():
    """PRD §3.6: "First, a `RENTAL_KIT` line may only be appended to an order that
    actually declares a rental window: a null `rental_window_start` or
    `rental_window_end`, or a `rental_window_start` that falls strictly before the
    logical clock's calendar date, is refused with `ERR_RENTAL_WINDOW_REQUIRED`."
    PRD §3.7: "The `received_at` must fall on or after the order's `confirmed_at` and
    must not fall after the logical clock; a receipt dated before confirmation or in the
    future is refused with `ERR_CORE_RECEIPT_BEFORE_CONFIRM`."
    PRD §3.7: "First, `core_days_late` is the number of whole days from the order's
    `core_return_due_at` to the recorded `received_at`, floored at zero."

    Design: Corner/validations/core_receipt_outside_the_confirmation_window_and_a_rental_line_without_a_window_are_rejected
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-V14",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={
            "sku": "SKU-V14-CORE",
            "list_price_cents": 2000,
            "core_return_required": True,
            "core_credit_cents": 1000,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    kit = fixtures.add_published_part(
        setup,
        part_overrides={
            "sku": "SKU-V14-KIT",
            "part_class": "RENTAL_KIT",
            "list_price_cents": 0,
            "rental_deposit_cents": 3000,
            "concurrent_rental_capacity": 2,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
    )
    core_part_id = setup["part"]["id"]
    assessment = fixtures.create_assessment(
        setup["model"]["id"], core_part_id, "US-CA", CUSTOMER
    )
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)

    windowless_kit = api_client.append_order_line(
        order["id"],
        factories.order_line_payload(kit["part"]["id"], order["version"], 1),
        CUSTOMER,
    )
    validate_error(windowless_kit, "ERR_RENTAL_WINDOW_REQUIRED", 422)

    fixtures.append_line(order["id"], core_part_id, 1, CUSTOMER)
    assert fixtures.read_order(order["id"], CUSTOMER)["rental_deposit_cents"] == 0, (
        "the refused kit line left no deposit behind"
    )

    fixtures.request_disclosure(order["id"], CUSTOMER)
    fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
    confirmed = fixtures.confirm_order(order["id"], CUSTOMER)
    assert confirmed["core_return_due_at"].startswith("2026-08-31T00:00:00"), (
        f"Expected thirty days after confirmation, got {confirmed['core_return_due_at']}"
    )
    assert confirmed["core_credit_provisional_cents"] == 1000, (
        confirmed["core_credit_provisional_cents"]
    )
    fixtures.deliver_order(order["id"], ADMIN)

    before_confirmation = api_client.book_core_return(
        order["id"], factories.core_return_payload("2026-07-31T00:00:00Z"), ADMIN
    )
    validate_error(before_confirmation, "ERR_CORE_RECEIPT_BEFORE_CONFIRM", 422)

    in_the_future = api_client.book_core_return(
        order["id"], factories.core_return_payload("2026-09-01T00:00:00Z"), ADMIN
    )
    validate_error(in_the_future, "ERR_CORE_RECEIPT_BEFORE_CONFIRM", 422)

    settled = fixtures.book_core_return(order["id"], "2026-08-01T00:00:00Z", "INTACT")
    assert settled["core_return_status"] == "CORE_CREDIT_ISSUED", (
        settled["core_return_status"]
    )
    assert settled["core_days_late"] == 0, (
        f"an early receipt floors the lateness at zero, got {settled['core_days_late']}"
    )
    assert settled["core_credit_final_cents"] == 1000, (
        f"an intact core on time keeps the whole face value, got "
        f"{settled['core_credit_final_cents']}"
    )
    assert_core_ledger_aggregates(fixtures.read_part(core_part_id), 1000, 0, 1000, 0)
