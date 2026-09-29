"""What each endpoint shape owes its caller: intersected collection filters, an action
that rewrites its children, a bulk action that respects its scope, a body-borne foreign
key, a computed read that persists nothing, and one action with two terminal outcomes.
"""
import pytest

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    NON_EXISTENT_UUID,
    api_client,
    assert_common_fields,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def _obligation(obligation_id):
    return get_success_data(
        api_client.get_compliance_obligation(obligation_id, COMPLIANCE)
    )


def _forecast(part_id, params):
    return api_client.get_demand_forecast(part_id, ADMIN, params=params)


def test_the_catalog_collection_intersects_its_filters_and_pages_the_filtered_set():
    """PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's
    `meta` object alongside `total_count` and `has_more`."
    PRD §2.3: "Catalog listings filter on `part_class`, `safety_class`, `status`, and
    `supersedes_part_id` — that last filter is the flat reverse lookup across the
    self-referential supersession edge, and a dedicated successors read returns the parts
    that name a given part as their predecessor."
    PRD §3.3: "A new catalog item is born in `DRAFT` with `restriction_reason` null and
    all four core-ledger aggregates — `core_face_value_committed_cents`,
    `core_liability_outstanding_cents`, `core_credit_settled_cents`, and
    `core_credit_forfeited_cents` — at zero."
    PRD §2.4: "Almost every resource additionally carries `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increments by one on every mutation — including mutations the server
    performs on its own initiative as part of a cascade, and including mutations that only
    change a computed field."

    Design: Corner/endpoints/part_catalog_crud_pair_creates_then_filters_the_collection_by_class_and_status
    """
    component = fixtures.create_part(
        sku="SKU-E1-COMP", part_class="COMPONENT", list_price_cents=1000
    )
    tool = fixtures.create_part(
        sku="SKU-E1-TOOL", part_class="TOOL", list_price_cents=500
    )
    consumable = fixtures.create_part(
        sku="SKU-E1-CONS", part_class="CONSUMABLE", list_price_cents=200
    )
    fixtures.publish_part(component["id"])
    fixtures.publish_part(consumable["id"])

    fetched = validate_success(
        api_client.get_part_catalog_item(tool["id"], CUSTOMER), 200
    )
    assert fetched["sku"] == "SKU-E1-TOOL", fetched["sku"]
    assert fetched["status"] == "DRAFT", (
        f"publish was never called on the tool, got {fetched['status']}"
    )

    intersected, intersected_meta = validate_paginated(
        api_client.list_part_catalog_items(
            CUSTOMER, params={"part_class": "COMPONENT", "status": "PUBLISHED"}
        )
    )
    assert intersected_meta["total_count"] == 1, (
        f"both filters must apply, excluding the draft tool and the published "
        f"consumable; got {intersected_meta['total_count']}"
    )
    assert intersected[0]["id"] == component["id"], intersected[0]["id"]

    page_one, meta_one = validate_paginated(
        api_client.list_part_catalog_items(
            CUSTOMER, params={"status": "PUBLISHED", "limit": 1, "offset": 0}
        )
    )
    assert meta_one["total_count"] == 2, (
        f"the count reports the filtered set, not the page, got "
        f"{meta_one['total_count']}"
    )
    assert len(page_one) == 1, len(page_one)
    assert meta_one["has_more"] is True, meta_one["has_more"]
    assert meta_one["limit"] == 1 and meta_one["offset"] == 0, meta_one

    page_two, meta_two = validate_paginated(
        api_client.list_part_catalog_items(
            CUSTOMER, params={"status": "PUBLISHED", "limit": 1, "offset": 1}
        )
    )
    assert meta_two["has_more"] is False, (
        "the second page of one row exhausts the two published parts"
    )
    assert {row["id"] for row in page_one + page_two} == {
        component["id"],
        consumable["id"],
    }, "the two pages together are exactly the published parts"
    for row in page_one + page_two:
        assert_common_fields(row)


def test_stamping_end_of_production_rewrites_its_obligations_and_refuses_a_second_call():
    """PRD §3.1: "Beyond storing that date, the action re-derives the mandated support
    window on every compliance obligation of the model, flipping each obligation's
    `deadline_basis` from `PRODUCTION_ACTIVE` to `END_OF_PRODUCTION` and filling in the
    two deadline dates that were null until now; it then re-evaluates each of those
    obligations' `status`; and it then recomputes the model's `compliance_posture` from
    the resulting statuses."
    PRD §3.2: "If the model has no `end_of_production_date`, the obligation's
    `deadline_basis` is `PRODUCTION_ACTIVE` and both `parts_available_until` and
    `documentation_available_until` are null — the clock has not started."
    PRD §3.1: "Stamping end of production advances the model from `ACTIVE_PRODUCTION` to
    `LEGACY_SUPPORT`. The action requires the model to actually be in
    `ACTIVE_PRODUCTION`, and requires the body's `end_of_production_date` to fall on or
    after the model's `market_release_date`."

    Design: Corner/endpoints/end_production_action_re_derives_the_mandated_deadlines_and_a_second_call_is_rejected
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-E2",
        product_family="CRX",
        market_release_date="2015-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-E2-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2016-01-01T00:00:00Z",
        install_minutes=20,
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-E2-A"], safety_warning_count=2
    )
    obligation = fixtures.create_obligation(model["id"], "US-CA", COMPLIANCE)

    assert obligation["deadline_basis"] == "PRODUCTION_ACTIVE", (
        obligation["deadline_basis"]
    )
    assert obligation["parts_available_until"] is None, (
        obligation["parts_available_until"]
    )
    assert obligation["documentation_available_until"] is None, (
        obligation["documentation_available_until"]
    )
    assert obligation["status"] == "OPEN", (
        f"a model still in production breaches nothing, got {obligation['status']}"
    )

    ended = validate_success(
        api_client.end_production(
            model["id"],
            factories.end_production_payload(
                end_of_production_date="2021-06-15T00:00:00Z"
            ),
            ADMIN,
        ),
        200,
    )
    assert ended["support_state"] == "LEGACY_SUPPORT", ended["support_state"]

    rewritten = _obligation(obligation["id"])
    assert rewritten["deadline_basis"] == "END_OF_PRODUCTION", (
        rewritten["deadline_basis"]
    )
    assert rewritten["parts_available_until"].startswith("2028-06-15T23:59:59.999"), (
        f"Expected seven whole years past the stamped date, at the end of that day, got "
        f"{rewritten['parts_available_until']}"
    )
    assert rewritten["documentation_available_until"].startswith(
        "2028-06-15T23:59:59.999"
    ), rewritten["documentation_available_until"]
    assert rewritten["status"] == "OPEN", (
        f"the clock is far more than ninety days short of the new deadline, got "
        f"{rewritten['status']}"
    )

    repeat = api_client.end_production(
        model["id"],
        factories.end_production_payload(end_of_production_date="2022-01-01T00:00:00Z"),
        ADMIN,
    )
    validate_error(repeat, "ERR_INVALID_STATE_TRANSITION", 409)
    assert fixtures.read_model(model["id"])["end_of_production_date"].startswith(
        "2021-06-15T00:00:00"
    ), "the refused second stamp did not overwrite the stored date"


def test_a_scoped_sweep_leaves_the_other_models_obligation_counter_alone():
    """PRD §3.2: "The **compliance sweep** is the batch counterpart, available to a
    `ComplianceOfficer` or `ProgramAdmin`, optionally narrowed to a single `model_id` and
    otherwise covering every obligation in the system."
    PRD §3.2: "Every evaluation that lands on either breached value increments
    `breach_count` by one, and it does so again on each repeated sweep — the counter is
    cumulative and is never decremented, not even when the obligation recovers to `OPEN`,
    because the provider compliance score keeps reading it."
    PRD §3.2: "The sweep answers with `swept_obligation_count`, a
    `breached_obligation_ids` list, an `expired_assessment_ids` list, and a
    `restricted_model_ids` list naming the models now sitting at `ORDER_RESTRICTED`."
    PRD §3.2: "Alongside the posture, `open_obligation_count` is set to the number of the
    model's obligations whose status is `OPEN`, `AT_RISK`, or `ATTESTED`."

    Design: Corner/endpoints/scoped_compliance_sweep_touches_only_the_named_models_obligations
    """
    fixtures.create_region(region_code="US-CA")
    healthy = fixtures.create_model(
        model_code="CRX-E3A",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-E3-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"],
        healthy["id"],
        effective_from="2024-02-01T00:00:00Z",
        install_minutes=20,
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        healthy["id"], ["SKU-E3-A"], safety_warning_count=2
    )
    bare = fixtures.create_model(
        model_code="CRX-E3B",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )

    healthy_obligation = fixtures.create_obligation(healthy["id"], "US-CA", COMPLIANCE)
    bare_obligation = fixtures.create_obligation(bare["id"], "US-CA", COMPLIANCE)
    assert healthy_obligation["status"] == "OPEN", healthy_obligation["status"]
    assert bare_obligation["status"] == "BREACHED_PARTS", (
        f"the bare model has no published part at all, got {bare_obligation['status']}"
    )
    assert bare_obligation["breach_count"] == 1, bare_obligation["breach_count"]

    scoped = fixtures.run_sweep(model_id=healthy["id"])
    assert scoped["swept_obligation_count"] == 1, (
        f"only the named model's obligation was in scope, got "
        f"{scoped['swept_obligation_count']}"
    )
    assert _obligation(bare_obligation["id"])["breach_count"] == 1, (
        "the scoped sweep never re-evaluated the out-of-scope obligation"
    )

    whole = fixtures.run_sweep()
    assert whole["swept_obligation_count"] == 2, whole["swept_obligation_count"]
    assert bare_obligation["id"] in whole["breached_obligation_ids"], (
        whole["breached_obligation_ids"]
    )
    assert healthy_obligation["id"] not in whole["breached_obligation_ids"], (
        whole["breached_obligation_ids"]
    )
    assert bare["id"] in whole["restricted_model_ids"], whole["restricted_model_ids"]

    swept_bare = _obligation(bare_obligation["id"])
    assert swept_bare["breach_count"] == 2, (
        f"a repeated breach verdict increments the cumulative counter again, got "
        f"{swept_bare['breach_count']}"
    )
    assert swept_bare["status"] == "BREACHED_PARTS", swept_bare["status"]

    swept_healthy = _obligation(healthy_obligation["id"])
    assert swept_healthy["status"] == "OPEN", swept_healthy["status"]
    assert swept_healthy["breach_count"] == 0, (
        f"two sweeps found nothing to hold against it, got "
        f"{swept_healthy['breach_count']}"
    )

    restricted = fixtures.read_model(bare["id"])
    assert restricted["compliance_posture"] == "ORDER_RESTRICTED", (
        restricted["compliance_posture"]
    )
    assert restricted["open_obligation_count"] == 0, (
        f"a breached obligation is not an open one, got "
        f"{restricted['open_obligation_count']}"
    )


def test_the_fitment_rows_tool_reference_is_validated_and_reverse_searchable():
    """PRD §2.8: "The same codes apply when the identifier arrives in a request body
    rather than in the path — an unknown `supersedes_part_id` or `required_tool_part_id`
    is an `ERR_PART_NOT_FOUND`, an unknown `order_line_id` on a defective-return filing is
    an `ERR_ORDER_LINE_NOT_FOUND`, and an unknown `provider_id` in a body is an
    `ERR_PROVIDER_NOT_FOUND`."
    PRD §3.3: "It carries a `part_id`, a `model_id`, an `effective_from` giving the
    inclusive start of the compatibility window, an optional `effective_until` giving the
    exclusive end — null means open-ended — a `self_service_eligible` flag saying whether
    an unassisted consumer may install this part on this model, an `install_minutes`
    figure between 1 and 600 giving documented bench time for the replacement, and an
    optional `required_tool_part_id` naming the tool or rental kit needed to install it,
    null when no tool is needed."
    PRD §2.3: "Compatibility listings filter on `part_id`, `model_id`,
    `required_tool_part_id`, `self_service_eligible`, and `as_of_date`; the model-scoped
    and part-scoped compatibility reads accept the same `as_of_date` filter to ask which
    fitment row was in force at a chosen instant."

    Design: Corner/endpoints/compatibility_tool_reference_links_a_third_part_and_an_unknown_tool_is_rejected
    """
    model = fixtures.create_model(
        model_code="CRX-E4",
        product_family="CRX",
        market_release_date="2023-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    component = fixtures.create_part(sku="SKU-E4-P", list_price_cents=1000)
    tool = fixtures.create_part(
        sku="SKU-E4-T", part_class="TOOL", list_price_cents=2500
    )
    fixtures.publish_part(component["id"])
    fixtures.publish_part(tool["id"])

    unknown_tool = api_client.create_part_compatibility(
        factories.part_compatibility_payload(
            component["id"],
            model["id"],
            effective_from="2023-02-01T00:00:00Z",
            install_minutes=40,
            required_tool_part_id=NON_EXISTENT_UUID,
        ),
        ADMIN,
    )
    validate_error(unknown_tool, "ERR_PART_NOT_FOUND", 404)
    _, empty_meta = validate_paginated(
        api_client.list_part_compatibilities(ADMIN, params={"limit": 100})
    )
    assert empty_meta["total_count"] == 0, (
        f"the refused write left no junction row behind, got "
        f"{empty_meta['total_count']}"
    )

    row = validate_success(
        api_client.create_part_compatibility(
            factories.part_compatibility_payload(
                component["id"],
                model["id"],
                effective_from="2023-02-01T00:00:00Z",
                install_minutes=40,
                required_tool_part_id=tool["id"],
            ),
            ADMIN,
        ),
        201,
    )
    assert row["required_tool_part_id"] == tool["id"], row["required_tool_part_id"]
    assert row["superseded_by_safety_restriction"] is False, (
        row["superseded_by_safety_restriction"]
    )

    by_tool, by_tool_meta = validate_paginated(
        api_client.list_part_compatibilities(
            CUSTOMER, params={"required_tool_part_id": tool["id"], "limit": 100}
        )
    )
    assert by_tool_meta["total_count"] == 1, (
        f"the tool reference is searchable in its own right, got "
        f"{by_tool_meta['total_count']}"
    )
    assert by_tool[0]["id"] == row["id"], by_tool[0]["id"]

    by_model, by_model_meta = validate_paginated(
        api_client.list_model_part_compatibilities(
            model["id"], CUSTOMER, params={"limit": 100}
        )
    )
    assert by_model_meta["total_count"] == 1, by_model_meta["total_count"]
    assert by_model[0]["required_tool_part_id"] == tool["id"], (
        by_model[0]["required_tool_part_id"]
    )

    by_part, by_part_meta = validate_paginated(
        api_client.list_compatibilities_for_part(
            component["id"], CUSTOMER, params={"limit": 100}
        )
    )
    assert by_part_meta["total_count"] == 1, by_part_meta["total_count"]
    assert by_part[0]["id"] == row["id"], by_part[0]["id"]


def test_two_identical_forecast_reads_agree_and_persist_nothing():
    """PRD §3.9: "Nothing is persisted. The response reports the `variant` used,
    `trailing_units`, `pipeline_units`, `base_monthly_units`, `obsolescence_band`,
    `band_multiplier`, `projected_units`, `safety_stock_pct`, `mandated_buffer_units`,
    and `recommended_stock_units`."
    PRD §3.9: "Fourth, the age of the *model* — never of the units — sets the
    obsolescence band: count the whole months between the model's
    `end_of_production_date` and the logical clock, taking zero when that date is null;
    the `obsolescence_band` is `CURRENT` when that count is below 12, `LEGACY` when it is
    at least 12 and at most 60, and `LONG_TAIL` when it exceeds 60; the corresponding
    `band_multiplier` is 1.00, 1.35, and 1.80."
    PRD §3.9: "Eighth, `mandated_buffer_units` is the monthly demand figure multiplied by
    the number of mandated support months remaining and then by a mandate buffer ratio of
    one quarter, rounded up to a whole unit; the mandated months remaining are the whole
    months from the logical clock to the latest `parts_available_until` across this
    model's compliance obligations whose `status` is not `CLOSED`, taken as zero when
    there is no such obligation or when that deadline already lies in the past."
    PRD §3.9: "A `ProgramAdmin` or `ComplianceOfficer` may ask for a **long-tail demand
    forecast** for one part on one model, supplying the `model_id`, a `horizon_months`
    between 1 and 60, and an optional `variant`; a horizon outside that range is refused
    with `ERR_INVALID_RANGE`."

    Design: Corner/endpoints/demand_forecast_computed_read_persists_nothing_and_rejects_a_missing_horizon
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-E5",
            "product_family": "CRX",
            "market_release_date": "2015-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
            "end_of_production_date": "2019-11-01T00:00:00Z",
        },
        part_overrides={"sku": "SKU-E5-A", "list_price_cents": 1000},
        compatibility_overrides={
            "effective_from": "2016-01-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    part_id = setup["part"]["id"]
    model_id = setup["model"]["id"]
    obligation = fixtures.create_obligation(model_id, "US-CA", COMPLIANCE)
    assert obligation["status"] == "OPEN", obligation["status"]
    assert obligation["parts_available_until"].startswith("2026-11-01T23:59:59.999"), (
        obligation["parts_available_until"]
    )

    delivered = fixtures.build_delivered_order(setup, 4, CUSTOMER)
    assert delivered["order"]["fulfillment_status"] == "CLOSED", (
        f"a line needing no service step and no core return closes on delivery, got "
        f"{delivered['order']['fulfillment_status']}"
    )

    fixtures.move_clock("2026-08-15T00:00:00Z")
    version_before = fixtures.read_part(part_id)["version"]

    params = {
        "model_id": model_id,
        "horizon_months": 12,
        "variant": "TRAILING_ONLY",
    }
    first = validate_success(_forecast(part_id, params), 200)
    assert first["variant"] == "TRAILING_ONLY", first["variant"]
    assert first["trailing_units"] == 4, (
        f"the closed order was confirmed inside the trailing window, got "
        f"{first['trailing_units']}"
    )
    assert first["pipeline_units"] == 0, first["pipeline_units"]
    assert first["base_monthly_units"] == pytest.approx(4 / 6, abs=0.01), (
        first["base_monthly_units"]
    )
    assert first["obsolescence_band"] == "LONG_TAIL", (
        f"eighty-one whole months since end of production exceeds sixty, got "
        f"{first['obsolescence_band']}"
    )
    assert first["band_multiplier"] == pytest.approx(1.80, abs=0.01), (
        first["band_multiplier"]
    )
    assert first["projected_units"] == pytest.approx(14.40, abs=0.01), (
        f"Expected two thirds of a unit a month over twelve months at the long-tail "
        f"multiplier, got {first['projected_units']}"
    )
    assert first["safety_stock_pct"] == pytest.approx(0.30, abs=0.01), (
        f"the unrounded projection is below fifty, got {first['safety_stock_pct']}"
    )
    assert first["mandated_buffer_units"] == 1, (
        f"Expected the fractional two-month mandate buffer rounded up to one whole "
        f"unit, got {first['mandated_buffer_units']}"
    )
    assert first["recommended_stock_units"] == 20, (
        f"Expected the padded projection rounded up to nineteen plus the one buffer "
        f"unit, got {first['recommended_stock_units']}"
    )

    second = validate_success(_forecast(part_id, params), 200)
    assert second["projected_units"] == pytest.approx(
        first["projected_units"], abs=0.01
    ), second["projected_units"]
    assert second["recommended_stock_units"] == first["recommended_stock_units"], (
        second["recommended_stock_units"]
    )
    assert fixtures.read_part(part_id)["version"] == version_before, (
        "two computed reads mutated nothing on the part row"
    )

    missing_horizon = _forecast(part_id, {"model_id": model_id})
    validate_error(missing_horizon, "ERR_INVALID_REQUEST", 400)


def test_delivery_closes_a_plain_order_outright_and_holds_a_service_bearing_one_open():
    """PRD §3.7: "Delivery is a `ProgramAdmin` action that advances the order from
    `CONFIRMED` to `DELIVERED`. It accepts an optional `delivered_at` and otherwise
    stamps the logical clock."
    PRD §3.7: "Every line whose part has `requires_authentication` true moves its
    `authentication_status` from `NOT_REQUIRED` to `PENDING_AUTHENTICATION` and has a
    `pairing_token` minted onto it — the token is readable through the order's line
    listing."
    PRD §3.7: "Where no line needs either step and the core dimension is `NOT_REQUIRED`,
    the order continues straight through to `CLOSED`."
    PRD §3.6: "A successful append captures the part's authentication and calibration
    requirements onto the line — `authentication_status` and `calibration_status` both
    start at `NOT_REQUIRED` and stay there for a part that needs neither step — and
    re-runs the whole order's pricing."

    Design: Corner/endpoints/deliver_closes_a_plain_order_outright_but_holds_a_service_bearing_order_open
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-E6",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={"sku": "SKU-E6-PLAIN", "list_price_cents": 1000},
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 20,
        },
        safety_warning_count=2,
    )
    authenticated_part = fixtures.add_published_part(
        setup,
        part_overrides={
            "sku": "SKU-E6-AUTH",
            "list_price_cents": 1500,
            "requires_authentication": True,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 25,
        },
    )

    plain = fixtures.build_confirmed_order(setup, 1, CUSTOMER)
    serviced = fixtures.build_confirmed_order(
        setup, 1, CUSTOMER, line_part_id=authenticated_part["part"]["id"]
    )
    for label, bundle in (("plain", plain), ("serviced", serviced)):
        assert bundle["line"]["authentication_status"] == "NOT_REQUIRED", (
            f"{label}: the append starts both dimensions at not required, got "
            f"{bundle['line']['authentication_status']}"
        )
        assert bundle["line"]["calibration_status"] == "NOT_REQUIRED", (
            f"{label}: {bundle['line']['calibration_status']}"
        )
        assert bundle["line"]["pairing_token"] is None, (
            f"{label}: no token exists before delivery"
        )
        assert bundle["order"]["core_return_status"] == "NOT_REQUIRED", (
            f"{label}: neither part carries a core return, got "
            f"{bundle['order']['core_return_status']}"
        )

    closed = validate_success(
        api_client.deliver_order(plain["order"]["id"], ADMIN), 200
    )
    assert closed["fulfillment_status"] == "CLOSED", (
        f"an order with nothing left to service runs straight through, got "
        f"{closed['fulfillment_status']}"
    )
    assert closed["delivered_at"].startswith("2026-08-01T00:00:00"), (
        f"the action stamped the logical clock, got {closed['delivered_at']}"
    )

    held = validate_success(
        api_client.deliver_order(
            serviced["order"]["id"], ADMIN, {"delivered_at": "2026-08-01T00:00:00Z"}
        ),
        200,
    )
    assert held["fulfillment_status"] == "DELIVERED", (
        f"the authentication dimension keeps the order open, got "
        f"{held['fulfillment_status']}"
    )

    plain_line = get_success_data(
        api_client.get_order_line(plain["line"]["id"], ADMIN)
    )
    assert plain_line["authentication_status"] == "NOT_REQUIRED", (
        plain_line["authentication_status"]
    )
    assert plain_line["calibration_status"] == "NOT_REQUIRED", (
        plain_line["calibration_status"]
    )

    serviced_line = get_success_data(
        api_client.get_order_line(serviced["line"]["id"], ADMIN)
    )
    assert serviced_line["authentication_status"] == "PENDING_AUTHENTICATION", (
        serviced_line["authentication_status"]
    )
    assert isinstance(serviced_line["pairing_token"], str), (
        f"delivery minted a readable token, got {serviced_line['pairing_token']}"
    )
    assert serviced_line["pairing_token"], "the minted token is not an empty string"
