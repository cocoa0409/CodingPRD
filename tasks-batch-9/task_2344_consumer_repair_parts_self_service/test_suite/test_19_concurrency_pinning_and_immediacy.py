"""The cross-cutting layers, observed from the outside: the two version guards and the
recovery each one prescribes, the revision an order keeps after the model has moved on,
and the two rollups that must already be correct in the response that caused them.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    CUSTOMER_ALT,
    DOCS,
    DOCS_ALT,
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def _revision(revision_id, headers=DOCS):
    return get_success_data(api_client.get_manual_revision(revision_id, headers))


def test_a_second_line_against_the_spent_order_version_is_refused_then_retried():
    """PRD §2.6: "`POST /repair-program/parts-orders/{order_id}/lines` requires a
    non-optional `expected_order_version` field carrying the client's last observed
    `version` of the target `PartsOrder`."
    PRD §2.6: "If it does not equal the order's current `version`, the append is rejected
    with `ERR_STALE_ORDER_VERSION` (412)."
    PRD §2.6: "Multiple lines per order are entirely legitimate and no state precondition
    blocks a second append; the guard exists so that a buyer cannot append against a
    pricing snapshot that an earlier append or a disclosure request has already moved."
    PRD §2.6: "Because a successful append increments the order's `version`, the order must
    be re-read before each further append."
    PRD §3.6: "`parts_subtotal_cents` is the sum of `line_total_cents` across lines whose
    part's `part_class` is `COMPONENT` or `CONSUMABLE`."

    Design: Corner/cross_cutting_layers/line_append_against_a_spent_order_version_is_rejected_with_a_stale_conflict
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-C1",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={"sku": "SKU-C1-A", "list_price_cents": 1000},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    second = fixtures.add_published_part(
        setup,
        part_overrides={"sku": "SKU-C1-B", "list_price_cents": 2000},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 25,
        },
    )
    part_a = setup["part"]["id"]
    part_b = second["part"]["id"]

    assessment = fixtures.create_assessment(
        setup["model"]["id"], part_a, "US-CA", CUSTOMER
    )
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    first_version = order["version"]

    first_line = validate_success(
        api_client.append_order_line(
            order["id"],
            factories.order_line_payload(part_a, first_version, 1),
            CUSTOMER,
        ),
        201,
    )
    assert first_line["line_total_cents"] == 1000, first_line["line_total_cents"]

    replayed = api_client.append_order_line(
        order["id"], factories.order_line_payload(part_b, first_version, 1), CUSTOMER
    )
    validate_error(replayed, "ERR_STALE_ORDER_VERSION", 412)

    lines, page_meta = validate_paginated(
        api_client.list_lines_for_order(order["id"], CUSTOMER, params={"limit": 50})
    )
    assert page_meta["total_count"] == 1, (
        f"the rejected append changed nothing, got {page_meta['total_count']} lines"
    )
    assert lines[0]["id"] == first_line["id"], lines[0]["id"]

    re_read = fixtures.read_order(order["id"], CUSTOMER)
    assert re_read["parts_subtotal_cents"] == 1000, re_read["parts_subtotal_cents"]
    assert re_read["version"] == first_version + 1, (
        f"exactly one append succeeded, got version {re_read['version']}"
    )

    second_line = validate_success(
        api_client.append_order_line(
            order["id"],
            factories.order_line_payload(part_b, re_read["version"], 1),
            CUSTOMER,
        ),
        201,
    )
    assert second_line["line_total_cents"] == 2000, (
        f"the same body succeeds once the fresh version is supplied, got "
        f"{second_line['line_total_cents']}"
    )

    after = fixtures.read_order(order["id"], CUSTOMER)
    assert after["version"] == re_read["version"] + 1, (
        f"the version advances on every successful write, got {after['version']}"
    )
    assert after["parts_subtotal_cents"] == 3000, (
        f"Expected the two component lines summed, got {after['parts_subtotal_cents']}"
    )


def test_a_second_revision_against_the_spent_model_version_is_refused_then_retried():
    """PRD §2.6: "`POST /repair-program/manual-revisions` requires a non-optional
    `expected_model_version` field carrying the client's last observed `version` of the
    target `ProductModel`."
    PRD §2.6: "If that value does not equal the model's current `version`, the create is
    rejected with `ERR_STALE_MODEL_VERSION` (412)."
    PRD §2.6: "This guard is the whole point of the field: the product deliberately permits
    more than one `DRAFT` revision for the same model and document type, so a second create
    against unchanged state would legitimately succeed."
    PRD §2.6: "On success, the model's `version` also increments."
    PRD §3.4: "The server assigns `revision_number` itself, as one more than the highest
    existing revision number for the same model and document type, starting at 1."

    Design: Corner/cross_cutting_layers/revision_create_against_a_spent_model_version_is_rejected_with_a_stale_conflict
    """
    model = fixtures.create_model(
        model_code="CRX-C2",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    first_version = fixtures.model_version(model["id"], DOCS_ALT)

    def _payload(expected_version):
        return factories.manual_revision_payload(
            model["id"],
            expected_version,
            doc_type="DISASSEMBLY_GUIDE",
            covered_part_skus=["SKU-C2-A", "SKU-C2-B"],
            safety_warning_count=2,
        )

    first_revision = validate_success(
        api_client.create_manual_revision(_payload(first_version), DOCS_ALT), 201
    )
    assert first_revision["revision_number"] == 1, first_revision["revision_number"]
    assert first_revision["coverage_gap_sku_count"] == 0, (
        "the model has no published parts, so nothing is required of the coverage list"
    )

    replayed = api_client.create_manual_revision(_payload(first_version), DOCS_ALT)
    validate_error(replayed, "ERR_STALE_MODEL_VERSION", 412)

    rows, page_meta = validate_paginated(
        api_client.list_manual_revisions(
            DOCS_ALT,
            params={
                "model_id": model["id"],
                "doc_type": "DISASSEMBLY_GUIDE",
                "limit": 50,
            },
        )
    )
    assert page_meta["total_count"] == 1, (
        f"the rejected create left no row behind, got {page_meta['total_count']}"
    )
    assert rows[0]["id"] == first_revision["id"], rows[0]["id"]

    second_version = fixtures.model_version(model["id"], DOCS_ALT)
    assert second_version == first_version + 1, (
        f"the successful create advanced the parent version, got {second_version}"
    )

    second_revision = validate_success(
        api_client.create_manual_revision(_payload(second_version), DOCS_ALT), 201
    )
    assert second_revision["revision_number"] == 2, (
        f"two draft revisions of the same document type coexist, got "
        f"{second_revision['revision_number']}"
    )
    assert second_revision["status"] == "DRAFT", second_revision["status"]
    assert second_revision["authored_by_user_id"] == "user_docs_002", (
        second_revision["authored_by_user_id"]
    )

    third_version = fixtures.model_version(model["id"], DOCS_ALT)
    assert third_version == second_version + 1, (
        f"the second create advanced the parent version again, got {third_version}"
    )


def test_the_order_keeps_its_pinned_revision_after_a_newer_guide_is_published():
    """PRD §3.5: "`liability_warning_version` is the warning-text version string the later
    acknowledgment must echo back verbatim; it is formed as the literal `LW-`, then the
    model's `model_code`, then the literal `-R`, then the model's
    `published_disassembly_revision_number`, and it is null whenever
    `pinned_manual_revision_id` is null."
    PRD §3.4: "The second hop, caused by the first, moves the previously published revision
    of the same model and document type — if there was one — to the terminal `SUPERSEDED`;
    that row is then frozen, and orders that pinned it keep their pinned revision number
    unchanged."
    PRD §3.6: "The action re-runs the full pricing pass described above, writing every
    per-line and order-level money field, and copies `warranty_impact_class` across from
    the assessment."
    PRD §3.6: "Then `documentation_fee_cents`: when the region's `requires_public_manual`
    is true the fee is zero, because the statutory free-documentation override wins before
    anything else is considered; otherwise the fee is the smaller of the region's
    `max_documentation_fee_cents` and a computed figure of five dollars — 500 cents — plus
    one dollar twenty — 120 cents — for each liability warning counted in the model's
    published `DISASSEMBLY_GUIDE` revision's `safety_warning_count`."
    PRD §3.6: "A `liability_warning_version` other than the pinned one is refused with
    `ERR_LIABILITY_WARNING_STALE` — the model's published documentation has moved on since
    the ruling was issued, and the buyer would be signing the wrong warning text."
    PRD §3.6: "The stored record captures `acknowledged_by_user_id` from the caller's
    `X-User-ID`, which must equal the order's `customer_user_id`; `manual_revision_number`,
    copied from the order's pinned revision number at signature time; and `acknowledged_at`,
    the logical-clock instant of signature."
    PRD §3.6: "It deliberately leaves `pinned_manual_revision_id` and
    `pinned_manual_revision_number` exactly as the assessment pinned them: a publication
    that happened between the ruling and the confirmation never moves those fields, and the
    acknowledgment check on the liability warning version is evaluated against the pinned
    values rather than against the model's currently published revision."

    Design: Corner/cross_cutting_layers/the_order_keeps_its_pinned_revision_after_a_newer_guide_is_published
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-C3",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={"sku": "SKU-C3-A", "list_price_cents": 1000},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    model_id = setup["model"]["id"]
    first_guide = setup["guide"]

    assessment = fixtures.create_assessment(
        model_id, setup["part"]["id"], "US-CA", CUSTOMER
    )
    assert assessment["liability_warning_version"] == "LW-CRX-C3-R1", (
        assessment["liability_warning_version"]
    )
    assert assessment["pinned_manual_revision_id"] == first_guide["id"], (
        assessment["pinned_manual_revision_id"]
    )

    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    assert order["pinned_manual_revision_number"] == 1, (
        order["pinned_manual_revision_number"]
    )
    fixtures.append_line(order["id"], setup["part"]["id"], 1, CUSTOMER)

    second_guide = fixtures.publish_disassembly_guide(
        model_id, ["SKU-C3-A"], safety_warning_count=5
    )
    assert second_guide["revision_number"] == 2, second_guide["revision_number"]
    assert _revision(first_guide["id"])["status"] == "SUPERSEDED", (
        "publication moves the previously published revision to the terminal state"
    )
    assert fixtures.read_model(model_id)["published_disassembly_revision_number"] == 2, (
        "the model now points at the newer guide"
    )

    disclosed = fixtures.request_disclosure(order["id"], CUSTOMER)
    assert disclosed["pinned_manual_revision_number"] == 1, (
        f"requesting disclosure never re-pins the order, got "
        f"{disclosed['pinned_manual_revision_number']}"
    )
    assert disclosed["pinned_manual_revision_id"] == first_guide["id"], (
        disclosed["pinned_manual_revision_id"]
    )
    assert disclosed["documentation_fee_cents"] == 1100, (
        f"Expected the 500-cent base plus 120 per warning counted in the model's "
        f"currently published guide, whose five warnings the re-run pricing pass reads, "
        f"got {disclosed['documentation_fee_cents']}"
    )
    assert disclosed["warranty_impact_class"] == assessment["warranty_impact_class"], (
        "the warranty class is copied across from the assessment"
    )

    stale_signature = api_client.create_acknowledgment(
        order["id"],
        factories.acknowledgment_payload(
            disclosed["warranty_impact_class"], "LW-CRX-C3-R2", "FULL_SELF_REPAIR"
        ),
        CUSTOMER,
    )
    validate_error(stale_signature, "ERR_LIABILITY_WARNING_STALE", 409)

    signed = validate_success(
        api_client.create_acknowledgment(
            order["id"],
            factories.acknowledgment_payload(
                disclosed["warranty_impact_class"], "LW-CRX-C3-R1", "FULL_SELF_REPAIR"
            ),
            CUSTOMER,
        ),
        201,
    )
    assert signed["manual_revision_number"] == 1, (
        f"the signature records the pinned revision number, got "
        f"{signed['manual_revision_number']}"
    )

    confirmed = fixtures.confirm_order(order["id"], CUSTOMER)
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        confirmed["fulfillment_status"]
    )
    assert confirmed["pinned_manual_revision_number"] == 1, (
        f"confirmation leaves the pinned revision exactly as the ruling pinned it, got "
        f"{confirmed['pinned_manual_revision_number']}"
    )

    later_assessment = fixtures.create_assessment(
        model_id, setup["part"]["id"], "US-CA", CUSTOMER_ALT
    )
    assert later_assessment["liability_warning_version"] == "LW-CRX-C3-R2", (
        f"a fresh ruling pins the revision that is current now, got "
        f"{later_assessment['liability_warning_version']}"
    )
    assert later_assessment["pinned_manual_revision_id"] == second_guide["id"], (
        later_assessment["pinned_manual_revision_id"]
    )


def test_the_order_money_is_current_in_the_response_that_appended_the_line():
    """PRD §3.6: "**Pricing** is re-run in full over every line of the order — there is no
    status filter on lines, because a line has no lifecycle of its own before delivery —
    both on each append while the order is still in `DRAFT` and again when disclosure is
    requested."
    PRD §3.6: "`line_total_cents` is then the effective unit value multiplied by the line's
    `quantity`, rounded half up to whole cents — and that is the one and only rounding for
    the line."
    PRD §3.6: "`unit_price_cents` is separately the effective unit value rounded half up,
    and it exists purely for display: it is never multiplied by quantity and never summed
    into any total."
    PRD §3.6: "Finally `total_due_cents` is the sum of `parts_subtotal_cents`,
    `tool_purchase_cents`, `rental_deposit_cents`, `documentation_fee_cents`, and
    `core_deposit_cents`."
    PRD §3.6: "The action re-runs the full pricing pass described above, writing every
    per-line and order-level money field, and copies `warranty_impact_class` across from
    the assessment."

    Design: Corner/consistency_model/order_money_fields_are_current_in_the_same_response_that_appends_the_line
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={
            "region_code": "US-CA",
            "max_documentation_fee_cents": 2000,
            "requires_public_manual": False,
        },
        model_overrides={
            "model_code": "CRX-C8",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={"sku": "SKU-C8-A", "list_price_cents": 1000},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    assessment = fixtures.create_assessment(
        setup["model"]["id"], setup["part"]["id"], "US-CA", CUSTOMER
    )
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    assert order["parts_subtotal_cents"] == 0, order["parts_subtotal_cents"]
    assert order["total_due_cents"] == 0, (
        f"an order with no lines carries no money, got {order['total_due_cents']}"
    )

    line = validate_success(
        api_client.append_order_line(
            order["id"],
            factories.order_line_payload(setup["part"]["id"], order["version"], 3),
            CUSTOMER,
        ),
        201,
    )
    assert line["unit_price_cents"] == 1000, (
        f"a consumer buying three units gets no multiplier at all, got "
        f"{line['unit_price_cents']}"
    )
    assert line["line_total_cents"] == 3000, (
        f"the append's own response already carries the priced line, got "
        f"{line['line_total_cents']}"
    )

    priced = fixtures.read_order(order["id"], CUSTOMER)
    assert priced["parts_subtotal_cents"] == 3000, priced["parts_subtotal_cents"]
    assert priced["documentation_fee_cents"] == 740, (
        f"Expected the 500-cent base plus 120 per warning on two warnings, present "
        f"before disclosure was ever requested, got {priced['documentation_fee_cents']}"
    )
    assert priced["total_due_cents"] == 3740, (
        f"Expected 3000 parts plus 740 documentation, got {priced['total_due_cents']}"
    )

    repeated = fixtures.read_order(order["id"], CUSTOMER)
    assert repeated["parts_subtotal_cents"] == priced["parts_subtotal_cents"], (
        repeated["parts_subtotal_cents"]
    )
    assert repeated["total_due_cents"] == priced["total_due_cents"], (
        repeated["total_due_cents"]
    )
    assert repeated["version"] == priced["version"], (
        f"reads are stable and do not mutate the order, got version "
        f"{repeated['version']}"
    )

    disclosed = fixtures.request_disclosure(order["id"], CUSTOMER)
    assert disclosed["parts_subtotal_cents"] == 3000, (
        disclosed["parts_subtotal_cents"]
    )
    assert disclosed["total_due_cents"] == 3740, (
        f"the disclosure hop freezes figures that were already correct, got "
        f"{disclosed['total_due_cents']}"
    )


def test_the_parent_rollup_is_current_in_the_response_that_created_the_child():
    """PRD §2.7: "Three derived rollups are recomputed rather than stored by clients: a
    model's `documentation_posture` together with its two published-revision numbers, a
    model's `compliance_posture` together with its `open_obligation_count`, and an
    obligation's `status`."
    PRD §3.2: "On creation the obligation's mandated window is computed, its initial
    `status` is derived, the parent model's posture is rolled up, `breach_count` starts at
    zero, `documentation_verified` starts false, and `last_attested_at` and
    `last_attested_by_user_id` start null."
    PRD §3.2: "Second: when no catalog part in `PUBLISHED` status holds a compatibility row
    for this model whose window contains the logical clock, the status is `BREACHED_PARTS`."
    PRD §3.2: "Every evaluation that lands on either breached value increments
    `breach_count` by one, and it does so again on each repeated sweep — the counter is
    cumulative and is never decremented, not even when the obligation recovers to `OPEN`,
    because the provider compliance score keeps reading it."
    PRD §3.2: "When any obligation of the model sits in `BREACHED_PARTS` or
    `BREACHED_DOCUMENTATION`, the model's `compliance_posture` becomes `ORDER_RESTRICTED`."
    PRD §3.2: "Alongside the posture, `open_obligation_count` is set to the number of the
    model's obligations whose status is `OPEN`, `AT_RISK`, or `ATTESTED`."

    Design: Corner/consistency_model/parent_rollups_are_current_in_the_same_response_as_the_child_write
    """
    fixtures.create_region(region_code="US-CA")
    fixtures.create_region(region_code="EU-DE")
    model = fixtures.create_model(
        model_code="CRX-C9",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    assert model["compliance_posture"] == "OPEN", model["compliance_posture"]
    assert model["open_obligation_count"] == 0, (
        f"a childless model counts no obligations, got {model['open_obligation_count']}"
    )

    first = fixtures.create_obligation(model["id"], "US-CA", COMPLIANCE)
    assert first["status"] == "BREACHED_PARTS", (
        f"no published part holds an in-window row for this model, and the create "
        f"response says so itself, got {first['status']}"
    )
    assert first["breach_count"] == 1, (
        f"the initial derivation already landed on a breached value, got "
        f"{first['breach_count']}"
    )

    rolled_up = fixtures.read_model(model["id"], ADMIN)
    assert rolled_up["compliance_posture"] == "ORDER_RESTRICTED", (
        f"the parent posture is current on the immediately following read, with no sweep "
        f"in between, got {rolled_up['compliance_posture']}"
    )
    assert rolled_up["open_obligation_count"] == 0, (
        f"a breached obligation is not an open one, got "
        f"{rolled_up['open_obligation_count']}"
    )

    second = fixtures.create_obligation(model["id"], "EU-DE", COMPLIANCE)
    assert second["status"] == "BREACHED_PARTS", second["status"]

    children, page_meta = validate_paginated(
        api_client.list_model_compliance_obligations(
            model["id"], COMPLIANCE, params={"limit": 50}
        )
    )
    assert page_meta["total_count"] == 2, (
        f"both children are visible at once, got {page_meta['total_count']}"
    )
    assert {row["region_code"] for row in children} == {"US-CA", "EU-DE"}, (
        [row["region_code"] for row in children]
    )

    after = fixtures.read_model(model["id"], ADMIN)
    assert after["compliance_posture"] == "ORDER_RESTRICTED", (
        after["compliance_posture"]
    )
    assert after["open_obligation_count"] == 0, (
        f"neither obligation counts as open, got {after['open_obligation_count']}"
    )
