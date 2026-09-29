"""The first three bands of the global ladder read against one endpoint at a time:
header layers before structure, structure before references, and references resolved
entity-first with the region profile joined as a natural key last.
"""
from test_helpers import (
    ADMIN,
    CUSTOMER,
    NON_EXISTENT_UUID,
    api_client,
    factories,
    fixtures,
    headers_without_user_id,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_each_broken_header_layer_masks_the_structural_check_below_it():
    """PRD §2.9: "Checks are evaluated in one global order, and the first check whose
    condition holds returns immediately — no later check is evaluated, so the earlier
    code always masks the later one."
    PRD §2.1: "A request whose role header is absent, empty, or not one of those seven
    strings is rejected with `ERR_UNAUTHORIZED` (401). A request whose role is one of
    the seven but is not among the roles the target endpoint authorises is rejected with
    `ERR_FORBIDDEN_ROLE` (403)."
    PRD §2.1: "That user-id requirement covers every write endpoint except the
    logical-clock endpoint and the compliance-sweep endpoint, both of which are operator
    utilities that record no actor."
    PRD §2.9: "**Structural validity** — malformed body, missing required field, wrong
    JSON type, out-of-set enum value, or an unknown field (`ERR_INVALID_REQUEST`); then
    numeric range (`ERR_INVALID_RANGE`); then inverted intervals
    (`ERR_INVALID_DATE_RANGE`); then natural-key uniqueness
    (`ERR_DUPLICATE_NATURAL_KEY`)."

    Design: Corner/validations/authorization_layer_returns_forbidden_role_before_invalid_request
    """
    fixtures.create_region(region_code="US-CA")
    malformed = {"part_class": "COMPONENT"}

    unknown_role = api_client.create_part_catalog_item(
        malformed, make_headers("user_admin_001", "Auditor")
    )
    validate_error(unknown_role, "ERR_UNAUTHORIZED", 401)

    missing_user_id = api_client.create_part_catalog_item(
        malformed, headers_without_user_id("SelfRepairCustomer")
    )
    validate_error(missing_user_id, "ERR_MISSING_USER_ID", 400)

    forbidden_role = api_client.create_part_catalog_item(malformed, CUSTOMER)
    validate_error(forbidden_role, "ERR_FORBIDDEN_ROLE", 403)

    unknown_field = api_client.create_part_catalog_item(
        factories.part_catalog_item_payload(sku="SKU-V01-A", unit_price_cents=10), ADMIN
    )
    validate_error(unknown_field, "ERR_INVALID_REQUEST", 400)

    _, meta = validate_paginated(api_client.list_part_catalog_items(ADMIN))
    assert meta["total_count"] == 0, (
        f"none of the four refused creates may persist a part, got "
        f"{meta['total_count']} rows"
    )


def test_a_broken_entity_reference_is_reported_before_the_region_profile_lookup():
    """PRD §2.8: "Each identifier has its own not-found code: `model_id` yields
    `ERR_MODEL_NOT_FOUND`, `part_id` yields `ERR_PART_NOT_FOUND`, `compatibility_id`
    yields `ERR_COMPATIBILITY_NOT_FOUND`, `revision_id` yields
    `ERR_MANUAL_REVISION_NOT_FOUND`, `assessment_id` yields `ERR_ASSESSMENT_NOT_FOUND`,
    `order_id` yields `ERR_ORDER_NOT_FOUND`, `line_id` yields
    `ERR_ORDER_LINE_NOT_FOUND`, `provider_id` yields `ERR_PROVIDER_NOT_FOUND`,
    `certification_id` yields `ERR_CERTIFICATION_NOT_FOUND`, `case_id` yields
    `ERR_RETURN_CASE_NOT_FOUND`, `obligation_id` yields `ERR_OBLIGATION_NOT_FOUND`, and
    `acknowledgment_id` yields `ERR_ACKNOWLEDGMENT_NOT_FOUND`."
    PRD §2.8: "Region codes are resolved as a natural key rather than by identifier: any
    `region_code` supplied when creating an obligation, an eligibility assessment, an
    order, or a provider must match an existing regional profile, otherwise the request
    is rejected with `ERR_REGION_PROFILE_NOT_FOUND` (404)."
    PRD §2.9: "**Referential resolution** — the twelve not-found codes of §2.8, then
    `ERR_REGION_PROFILE_NOT_FOUND`, then nested-ownership not-found, then
    supersession-graph refusals (`ERR_SUPERSESSION_CYCLE`, then
    `ERR_SUPERSESSION_CLASS_MISMATCH`)."

    Design: Corner/validations/assessment_with_two_broken_references_returns_model_not_found_before_region_profile
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-V02",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-V02-A", list_price_cents=1000)

    broken_model = api_client.create_eligibility_assessment(
        factories.eligibility_assessment_payload(
            NON_EXISTENT_UUID, part["id"], "US-ZZ"
        ),
        CUSTOMER,
    )
    validate_error(broken_model, "ERR_MODEL_NOT_FOUND", 404)

    broken_part = api_client.create_eligibility_assessment(
        factories.eligibility_assessment_payload(
            model["id"], NON_EXISTENT_UUID, "US-ZZ"
        ),
        CUSTOMER,
    )
    validate_error(broken_part, "ERR_PART_NOT_FOUND", 404)

    broken_region = api_client.create_eligibility_assessment(
        factories.eligibility_assessment_payload(model["id"], part["id"], "US-ZZ"),
        CUSTOMER,
    )
    validate_error(broken_region, "ERR_REGION_PROFILE_NOT_FOUND", 404)

    _, meta = validate_paginated(api_client.list_eligibility_assessments(ADMIN))
    assert meta["total_count"] == 0, (
        f"a ruling is never stored behind a broken reference, got "
        f"{meta['total_count']} rows"
    )


def test_a_blocked_ruling_and_a_consumed_ruling_are_refused_by_different_gates():
    """PRD §3.6: "The referenced assessment must still be in `VALID` status: an
    assessment that is `EXPIRED`, `REVOKED_BY_SAFETY`, or already `CONSUMED` by another
    order is refused with `ERR_ASSESSMENT_NOT_VALID`, and an assessment whose `decision`
    is any of the blocked values is refused with `ERR_ASSESSMENT_BLOCKED`."
    PRD §3.5: "An assessment is always created successfully, with a 201 response: a
    blocked ruling is a successful assessment, not an error."

    Design: Corner/validations/order_creation_rejects_a_blocked_assessment_and_an_already_consumed_one
    """
    fixtures.create_region(region_code="US-CA")
    serviceable = fixtures.create_model(
        model_code="CRX-V03A",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    non_serviceable = fixtures.create_model(
        model_code="CRX-V03D",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_D_NON_SERVICEABLE",
    )
    part = fixtures.create_part(sku="SKU-V03-A", list_price_cents=1000)
    for model_id in (serviceable["id"], non_serviceable["id"]):
        fixtures.create_compatibility(
            part["id"],
            model_id,
            effective_from="2024-02-01T00:00:00Z",
            install_minutes=20,
        )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        serviceable["id"], ["SKU-V03-A"], safety_warning_count=2
    )

    blocked = fixtures.create_assessment(
        non_serviceable["id"], part["id"], "US-CA", CUSTOMER
    )
    assert blocked["decision"] == "BLOCKED_TIER", blocked["decision"]
    assert blocked["status"] == "VALID", (
        f"a blocked ruling is still a valid row, got {blocked['status']}"
    )

    eligible = fixtures.create_assessment(
        serviceable["id"], part["id"], "US-CA", CUSTOMER
    )
    assert eligible["decision"] == "ELIGIBLE", eligible["decision"]
    first_order = fixtures.create_order(eligible["id"], "US-CA", CUSTOMER)

    on_blocked = api_client.create_parts_order(
        factories.parts_order_payload(blocked["id"], "US-CA"), CUSTOMER
    )
    validate_error(on_blocked, "ERR_ASSESSMENT_BLOCKED", 422)

    on_consumed = api_client.create_parts_order(
        factories.parts_order_payload(eligible["id"], "US-CA"), CUSTOMER
    )
    validate_error(on_consumed, "ERR_ASSESSMENT_NOT_VALID", 409)

    rows, meta = validate_paginated(
        api_client.list_parts_orders(ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"only the first order against the eligible ruling may exist, got "
        f"{meta['total_count']}"
    )
    assert rows[0]["id"] == first_order["id"], rows[0]["id"]


def test_each_structural_family_reports_its_own_code_and_the_clock_refuses_an_equal_instant():
    """PRD §3.9: "A `ProgramAdmin` or `ComplianceOfficer` may ask for a **long-tail
    demand forecast** for one part on one model, supplying the `model_id`, a
    `horizon_months` between 1 and 60, and an optional `variant`; a horizon outside that
    range is refused with `ERR_INVALID_RANGE`."
    PRD §3.3: "An `effective_until` that is at or before the `effective_from` is refused
    with `ERR_INVALID_DATE_RANGE`, since the window is half-open and must be non-empty."
    PRD §3.1: "Re-using an existing `model_code` is refused with
    `ERR_DUPLICATE_NATURAL_KEY`; an `end_of_production_date` earlier than the
    `market_release_date` is refused with `ERR_INVALID_DATE_RANGE`."
    PRD §3.3: "A duplicate `sku` is refused with `ERR_DUPLICATE_NATURAL_KEY`."
    PRD §2.4: "Movement must be strictly forward: an instant equal to or earlier than
    the current logical clock is rejected with `ERR_CLOCK_MONOTONICITY` (422)."

    Design: Corner/validations/structural_guards_reject_bad_ranges_inverted_windows_duplicates_and_backward_clocks
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-V13",
        product_family="CRX",
        market_release_date="2025-01-01T00:00:00Z",
        repairability_tier="TIER_B_GUIDED",
    )
    part = fixtures.create_part(sku="SKU-V13-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2026-03-01T00:00:00Z", install_minutes=20
    )
    fixtures.publish_part(part["id"])

    bad_horizon = api_client.get_demand_forecast(
        part["id"],
        ADMIN,
        params={"model_id": model["id"], "horizon_months": 0, "variant": "TRAILING_ONLY"},
    )
    validate_error(bad_horizon, "ERR_INVALID_RANGE", 422)

    empty_window = api_client.create_part_compatibility(
        factories.part_compatibility_payload(
            part["id"],
            model["id"],
            effective_from="2027-01-01T00:00:00Z",
            effective_until="2027-01-01T00:00:00Z",
            install_minutes=20,
        ),
        ADMIN,
    )
    validate_error(empty_window, "ERR_INVALID_DATE_RANGE", 422)

    duplicate_model = api_client.create_product_model(
        factories.product_model_payload(
            model_code="CRX-V13",
            product_family="CRX",
            market_release_date="2025-01-01T00:00:00Z",
            repairability_tier="TIER_B_GUIDED",
        ),
        ADMIN,
    )
    validate_error(duplicate_model, "ERR_DUPLICATE_NATURAL_KEY", 409)

    duplicate_sku = api_client.create_part_catalog_item(
        factories.part_catalog_item_payload(
            sku="SKU-V13-A", part_class="TOOL", list_price_cents=500
        ),
        ADMIN,
    )
    validate_error(duplicate_sku, "ERR_DUPLICATE_NATURAL_KEY", 409)

    equal_instant = api_client.set_clock(
        factories.clock_payload("2026-08-01T00:00:00Z"), ADMIN
    )
    validate_error(equal_instant, "ERR_CLOCK_MONOTONICITY", 422)

    earlier_instant = api_client.set_clock(
        factories.clock_payload("2026-07-31T00:00:00Z"), ADMIN
    )
    validate_error(earlier_instant, "ERR_CLOCK_MONOTONICITY", 422)

    witness = validate_success(
        api_client.create_product_model(
            factories.product_model_payload(
                model_code="CRX-V13B",
                product_family="CRX",
                market_release_date="2025-01-01T00:00:00Z",
                repairability_tier="TIER_B_GUIDED",
            ),
            ADMIN,
        ),
        201,
    )
    assert witness["created_at"].startswith("2026-08-01T00:00:00"), (
        "the two refused moves left the logical clock where it started, so a fresh row "
        f"is still stamped at the start instant; got {witness['created_at']}"
    )

    _, meta = validate_paginated(
        api_client.list_compatibilities_for_part(part["id"], ADMIN, params={"limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"the refused empty window stored nothing, got {meta['total_count']} rows"
    )
