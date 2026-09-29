"""Order configuration: lines, line pricing and the quote-invalidation back edge."""
from test_helpers import (
    assert_instant,
    add_order_line,
    add_partner_ctx,
    arrive_ctx,
    complete_install_ctx,
    complete_production_ctx,
    confirm_ctx,
    new_facility,
    new_model_revision,
    new_order,
    order_line_payload,
    quote_payload,
    read_facility,
    read_model_revision,
    read_order,
    read_order_line,
    schedule_install_ctx,
    setup_configured_order,
    setup_released_revision,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_adding_a_line_to_a_quoted_order_drives_billing_back_to_unquoted(
    api, order_planner_headers
):
    """The QUOTED order falls back to UNQUOTED and every quoted figure is zeroed.

    The PRD states that "Adding a line or voiding a line while the order is still
    `CONFIGURING` invalidates any quote already taken. The order's
    `billing_status` moves `QUOTED → UNQUOTED` automatically, and in doing so
    `quoted_total_cents`, `install_amount_cents`, `volume_discount_cents`,
    `freight_cents` and `punch_list_credit_cents` are all reset to 0,
    `price_variant_applied` is reset to `NONE`, and `quoted_at` is reset to null."

    Design: Difficulty/non_linear_state_machine/order_quote_invalidated_by_line_addition_backedge
    """
    ctx = setup_configured_order(preset="T900", quantity=2)
    version = read_order(ctx["order"]["id"])["version"]
    quoted = validate_success(
        api.quote_order(ctx["order"]["id"], quote_payload(version), order_planner_headers)
    )
    assert quoted["billing_status"] == "QUOTED"
    assert quoted["quoted_total_cents"] == 1_120_619

    response = api.create_order_line(
        ctx["order"]["id"],
        order_line_payload(ctx["revision"]["id"], quantity=1, finish_codes=["GRAPHITE"],
                           layout_zone_label="ZONE-B"),
        order_planner_headers,
    )

    validate_success(response, 201)
    order = read_order(ctx["order"]["id"])
    assert order["billing_status"] == "UNQUOTED"
    assert order["quoted_total_cents"] == 0
    assert order["install_amount_cents"] == 0
    assert order["volume_discount_cents"] == 0
    assert order["freight_cents"] == 0
    assert order["punch_list_credit_cents"] == 0
    assert order["price_variant_applied"] == "NONE"
    assert order["quoted_at"] is None
    assert order["line_subtotal_cents"] == 1_526_241, (
        "the recomputed subtotal describes the new three-unit configuration"
    )
    assert float(order["chargeable_weight_kg"]) == 637.5
    assert order["config_status"] == "CONFIGURING"


def test_confirm_is_refused_until_the_enlarged_configuration_is_requoted(
    api, order_planner_headers
):
    """Confirmation only becomes reachable once the invalidated quote is retaken.

    The PRD states that "A planner who changes the floor plan must therefore
    re-quote before the order can be confirmed; confirming a configuration whose
    quote has been invalidated surfaces `ERR_ORDER_NOT_QUOTED`."

    Design: Difficulty/non_linear_state_machine/order_quote_invalidated_by_line_addition_backedge
    """
    ctx = setup_configured_order(preset="T900", quantity=2)
    validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )
    add_order_line(ctx, quantity=1, finish_codes=["GRAPHITE"], layout_zone_label="ZONE-B")

    validate_error(api.confirm_order(ctx["order"]["id"], order_planner_headers),
                   "ERR_ORDER_NOT_QUOTED", 409)

    requoted = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )
    assert requoted["line_subtotal_cents"] == 1_526_241
    assert requoted["install_amount_cents"] == 39_938
    assert requoted["freight_cents"] == 114_750
    assert requoted["quoted_total_cents"] == 1_680_929

    confirmed = validate_success(api.confirm_order(ctx["order"]["id"],
                                                    order_planner_headers))
    assert confirmed["config_status"] == "CONFIRMED"
    assert confirmed["fulfillment_status"] == "IN_PRODUCTION"
    assert confirmed["billing_status"] == "QUOTED"
    assert confirmed["price_variant_applied"] == "PROVISIONAL"
    facility = read_facility(ctx["facility"]["id"], order_planner_headers)
    assert facility["open_order_exposure_cents"] == 1_680_929


def test_every_successful_quote_increments_the_order_version_by_one(
    api, order_planner_headers
):
    """Two quotes across a configuration change advance the version once each.

    The PRD states that quoting "is version-pinned: the request body carries only
    `expected_order_version`, which must match the order's current `version` per
    §2.7" and that "Both branches increment the order's `version` by one on
    success, which is what makes a second quote issued against a stale pin fail
    with `ERR_STALE_VERSION`."

    Design: Difficulty/non_linear_state_machine/order_quote_invalidated_by_line_addition_backedge
    """
    ctx = setup_configured_order(preset="T900", quantity=2)
    before_first = read_order(ctx["order"]["id"])["version"]

    first = validate_success(
        api.quote_order(ctx["order"]["id"], quote_payload(before_first),
                        order_planner_headers)
    )

    assert first["version"] == before_first + 1
    add_order_line(ctx, quantity=1, finish_codes=["GRAPHITE"], layout_zone_label="ZONE-B")
    before_second = read_order(ctx["order"]["id"])["version"]
    assert before_second > before_first + 1, "the line addition advanced the order too"

    second = validate_success(
        api.quote_order(ctx["order"]["id"], quote_payload(before_second),
                        order_planner_headers)
    )

    assert second["version"] == before_second + 1
    assert second["quoted_total_cents"] == 1_680_929
    assert_instant(second["quoted_at"], "2026-08-01T00:00:00Z", "quoted_at")


def test_each_line_create_violation_reports_its_own_error_in_isolation(
    api, order_planner_headers
):
    """A disallowed finish alone is 422; an unreleased revision alone is 409.

    The PRD states that "The referenced revision must have `status` `RELEASED`,
    otherwise `ERR_REVISION_NOT_RELEASED`: a facility may only buy equipment that
    has actually been signed off" and that "every code in it must be a member of
    the owning model's `allowed_finish_codes`; a code outside that set is
    `ERR_FINISH_NOT_ALLOWED`."

    Design: Difficulty/priority_pair_validation_conflict/revision_release_gate_outranks_finish_referential_check_on_line_create
    """
    ctx = setup_configured_order(
        revision_ctx=setup_released_revision("T900"), quantity=3,
        finish_codes=["ARCTIC_WHITE"], layout_zone_label="CARDIO-DECK",
    )
    draft = new_model_revision(ctx["model"], "T900", revision_code="T900-R2",
                              target_cycle_count=600_000)
    assert draft["status"] == "DRAFT"

    validate_error(
        api.create_order_line(
            ctx["order"]["id"],
            order_line_payload(ctx["revision"]["id"], quantity=1,
                               finish_codes=["PREMIUM_UPHOLSTERY"],
                               layout_zone_label="CARDIO-DECK"),
            order_planner_headers,
        ),
        "ERR_FINISH_NOT_ALLOWED", 422,
    )
    validate_error(
        api.create_order_line(
            ctx["order"]["id"],
            order_line_payload(draft["id"], quantity=1, finish_codes=["GRAPHITE"],
                               layout_zone_label="CARDIO-DECK"),
            order_planner_headers,
        ),
        "ERR_REVISION_NOT_RELEASED", 409,
    )
    _, meta = validate_paginated(
        api.list_order_lines(order_planner_headers,
                             params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 1, "neither control call wrote a line"


def test_unreleased_revision_outranks_the_disallowed_finish_on_a_line_create(
    api, order_planner_headers
):
    """A request breaking both rules reports the revision gate, not the finish set.

    The PRD ladder places the release gate — "A new order line's referenced
    revision has `status` `RELEASED`, otherwise `ERR_REVISION_NOT_RELEASED` (409)"
    — above the later finish-availability rung, where "Every requested finish code
    is a member of the model's `allowed_finish_codes`, otherwise
    `ERR_FINISH_NOT_ALLOWED` (422)".

    Design: Difficulty/priority_pair_validation_conflict/revision_release_gate_outranks_finish_referential_check_on_line_create
    """
    ctx = setup_configured_order(
        revision_ctx=setup_released_revision("T900"), quantity=3,
        finish_codes=["ARCTIC_WHITE"], layout_zone_label="CARDIO-DECK",
    )
    draft = new_model_revision(ctx["model"], "T900", revision_code="T900-R2",
                              target_cycle_count=600_000)

    response = api.create_order_line(
        ctx["order"]["id"],
        order_line_payload(draft["id"], quantity=1,
                           finish_codes=["PREMIUM_UPHOLSTERY"],
                           layout_zone_label="CARDIO-DECK"),
        order_planner_headers,
    )

    error = validate_error(response, "ERR_REVISION_NOT_RELEASED", 409)
    assert error["error_id"] != "ERR_FINISH_NOT_ALLOWED"
    assert response.status_code != 422
    rows, meta = validate_paginated(
        api.list_order_lines(order_planner_headers,
                             params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["line"]["id"]
    assert rows[0]["status"] == "ACTIVE"
    assert rows[0]["unit_price_cents"] == 484_450
    assert rows[0]["extended_price_cents"] == 1_540_551
    order = read_order(ctx["order"]["id"])
    assert order["line_subtotal_cents"] == 1_540_551
    assert order["billing_status"] == "UNQUOTED"
    assert read_model_revision(draft["id"])["status"] == "DRAFT"


def test_order_line_unit_and_extended_price_are_computed_from_finish_and_duty(
    api, order_planner_headers
):
    """Two finish surcharges stack on the list price before the duty uplift.

    The PRD states that a line's "`unit_price_cents` is the model's
    `unit_list_price_cents` plus the surcharges for the selected finishes, added
    together" and that "Its `extended_price_cents` is that unit price multiplied
    by the `quantity` and then multiplied by one plus the duty uplift for the
    model's `duty_class`".

    Design: Corner/entities/order_line_unit_and_extended_price_are_computed_from_finish_and_duty
    """
    released = setup_released_revision("T900")
    facility = new_facility()
    empty_order = new_order(facility["id"])

    response = api.create_order_line(
        empty_order["id"],
        order_line_payload(released["revision"]["id"], quantity=3,
                           finish_codes=["ARCTIC_WHITE", "CLUB_RED"],
                           layout_zone_label="ZONE-A"),
        order_planner_headers,
    )

    line = validate_success(response, 201)
    assert line["unit_price_cents"] == 491_950
    assert line["extended_price_cents"] == 1_564_401
    assert line["status"] == "ACTIVE"
    assert line["assets_minted_count"] == 0
    order = read_order(empty_order["id"])
    assert order["line_subtotal_cents"] == 1_564_401
    assert float(order["chargeable_weight_kg"]) == 637.5
    assert order["billing_status"] == "UNQUOTED"
    assert order["quoted_total_cents"] == 0
    assert order["install_amount_cents"] == 0


def test_order_three_status_dimensions_advance_independently(api, order_planner_headers):
    """Each trigger moves only the dimensions the PRD assigns to it.

    The PRD states that an order "carries three *independent* status dimensions
    rather than one lifecycle. `config_status` starts at `CONFIGURING` and reaches
    the terminal `CONFIRMED`. `fulfillment_status` starts at `PENDING` and walks
    `IN_PRODUCTION`, `STAGED`, `INSTALLING` to the terminal `INSTALLED`.
    `billing_status` starts at `UNQUOTED` and walks `QUOTED`, `INVOICED` to the
    terminal `SETTLED`."

    Design: Corner/state_machines/order_three_status_dimensions_advance_independently
    """
    ctx = setup_configured_order(preset="T900", quantity=1)

    def triple():
        order = read_order(ctx["order"]["id"])
        return (order["config_status"], order["fulfillment_status"],
                order["billing_status"])

    assert triple() == ("CONFIGURING", "PENDING", "UNQUOTED")
    quoted = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )
    assert triple() == ("CONFIGURING", "PENDING", "QUOTED")
    assert quoted["quoted_total_cents"] == 560_310

    confirm_ctx(ctx)
    assert triple() == ("CONFIRMED", "IN_PRODUCTION", "QUOTED")
    complete_production_ctx(ctx)
    assert triple() == ("CONFIRMED", "STAGED", "QUOTED")
    add_partner_ctx(ctx)
    schedule_install_ctx(ctx)
    arrive_ctx(ctx)
    assert triple() == ("CONFIRMED", "INSTALLING", "QUOTED")
    complete_install_ctx(ctx, actual_labor_hours=3.0, punch_list_open_count=0)

    assert triple() == ("CONFIRMED", "INSTALLED", "INVOICED")
    order = read_order(ctx["order"]["id"])
    assert order["price_variant_applied"] == "FINAL"
    assert order["final_total_cents"] == 573_622
    assert order["quoted_total_cents"] == 560_310, (
        "the provisional figure is retained beside the final one"
    )


def test_voiding_the_last_active_line_blocks_quoting_but_confirm_fails_earlier(
    api, order_planner_headers
):
    """An empty configuration answers quote and confirm with different codes.

    The PRD states that the first-quote branch "additionally requires the order to
    have at least one `ACTIVE` line, otherwise `ERR_ORDER_HAS_NO_LINES`", while
    confirmation's four preconditions begin with "the `billing_status` must be
    `QUOTED` (`ERR_ORDER_NOT_QUOTED`)".

    Design: Corner/validations/voiding_the_last_active_line_blocks_quoting_but_confirm_fails_earlier
    """
    ctx = setup_configured_order(preset="T900", quantity=1)
    validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )
    validate_success(api.void_order_line(ctx["line"]["id"], order_planner_headers))
    voided = read_order(ctx["order"]["id"])
    assert voided["billing_status"] == "UNQUOTED"
    assert voided["price_variant_applied"] == "NONE"
    assert voided["quoted_total_cents"] == 0
    assert voided["line_subtotal_cents"] == 0
    assert voided["quoted_at"] is None
    assert read_order_line(ctx["line"]["id"], order_planner_headers)["status"] == "VOIDED"

    validate_error(
        api.quote_order(ctx["order"]["id"], quote_payload(voided["version"]),
                        order_planner_headers),
        "ERR_ORDER_HAS_NO_LINES", 422,
    )
    validate_error(api.confirm_order(ctx["order"]["id"], order_planner_headers),
                   "ERR_ORDER_NOT_QUOTED", 409)

    add_order_line(ctx, quantity=1, finish_codes=["GRAPHITE"], layout_zone_label="ZONE-B")
    requoted = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )
    assert requoted["quoted_total_cents"] == 560_310
    assert float(requoted["chargeable_weight_kg"]) == 212.5
    assert requoted["line_subtotal_cents"] == 508_747
    assert requoted["config_status"] == "CONFIGURING"


def test_requote_rejects_a_version_that_a_line_addition_invalidated(
    api, order_planner_headers
):
    """The version held from before the line addition is refused as stale.

    The PRD states that quoting "is permitted twice: `UNQUOTED → QUOTED` for a
    first quote, and `QUOTED → QUOTED` for a re-quote after a configuration
    change, which recomputes and overwrites every provisional pricing field."
    A pin that no longer matches the row's `version` is `ERR_STALE_VERSION` (412).

    Design: Corner/complexity_layers/requote_rejects_a_version_that_a_line_addition_invalidated
    """
    ctx = setup_configured_order(preset="T900", quantity=1)
    first_pin = read_order(ctx["order"]["id"])["version"]
    validate_success(
        api.quote_order(ctx["order"]["id"], quote_payload(first_pin),
                        order_planner_headers)
    )
    stale_pin = read_order(ctx["order"]["id"])["version"]
    add_order_line(ctx, quantity=1, finish_codes=["GRAPHITE"], layout_zone_label="ZONE-B")
    after_add = read_order(ctx["order"]["id"])
    assert after_add["billing_status"] == "UNQUOTED"
    assert after_add["quoted_total_cents"] == 0
    assert after_add["price_variant_applied"] == "NONE"
    assert after_add["line_subtotal_cents"] == 1_017_494
    assert float(after_add["chargeable_weight_kg"]) == 425.0

    validate_error(
        api.quote_order(ctx["order"]["id"], quote_payload(stale_pin),
                        order_planner_headers),
        "ERR_STALE_VERSION", 412,
    )

    unchanged = read_order(ctx["order"]["id"])
    assert unchanged["billing_status"] == "UNQUOTED"
    assert unchanged["quoted_total_cents"] == 0

    requoted = validate_success(
        api.quote_order(ctx["order"]["id"], quote_payload(unchanged["version"]),
                        order_planner_headers)
    )
    assert requoted["quoted_total_cents"] == 1_120_619
    assert requoted["quoted_total_cents"] == (
        requoted["line_subtotal_cents"] + requoted["install_amount_cents"]
        + requoted["freight_cents"]
    )
    assert requoted["billing_status"] == "QUOTED"
    assert requoted["price_variant_applied"] == "PROVISIONAL"
    assert_instant(requoted["quoted_at"], "2026-08-01T00:00:00Z", "quoted_at")
    assert read_facility(ctx["facility"]["id"], order_planner_headers)[
        "open_order_exposure_cents"
    ] == 0, "a quote alone creates no exposure until the order is confirmed"


def test_order_derived_totals_reconcile_after_an_add_and_a_void(
    api, order_planner_headers
):
    """Adding then voiding a line returns every derived figure to its prior value.

    The PRD states that "The order's `line_subtotal_cents` is then the sum of
    `extended_price_cents` over its lines whose `status` is `ACTIVE`" and that the
    order's "`chargeable_weight_kg` is computed in the same spirit, as the sum over
    active lines of the line's `quantity` multiplied by its model's
    `shipping_weight_kg`."

    Design: Corner/complexity_layers/order_derived_totals_reconcile_after_an_add_and_a_void
    """
    ctx = setup_configured_order(preset="T900", quantity=2)
    baseline = validate_success(
        api.quote_order(ctx["order"]["id"],
                        quote_payload(read_order(ctx["order"]["id"])["version"]),
                        order_planner_headers)
    )
    assert baseline["line_subtotal_cents"] == 1_017_494
    assert float(baseline["chargeable_weight_kg"]) == 425.0
    assert baseline["quoted_total_cents"] == 1_120_619

    added = add_order_line(ctx, quantity=1, finish_codes=["ARCTIC_WHITE"],
                           layout_zone_label="ZONE-B")
    enlarged = read_order(ctx["order"]["id"])
    assert added["extended_price_cents"] == 513_517
    assert enlarged["line_subtotal_cents"] == 1_531_011
    assert float(enlarged["chargeable_weight_kg"]) == 637.5
    assert enlarged["billing_status"] == "UNQUOTED"
    assert enlarged["quoted_total_cents"] == 0
    enlarged_quote = validate_success(
        api.quote_order(ctx["order"]["id"], quote_payload(enlarged["version"]),
                        order_planner_headers)
    )
    assert enlarged_quote["quoted_total_cents"] == 1_685_699
    assert enlarged_quote["install_amount_cents"] == 39_938
    assert enlarged_quote["freight_cents"] == 114_750

    validate_success(api.void_order_line(added["id"], order_planner_headers))

    reverted = read_order(ctx["order"]["id"])
    assert reverted["line_subtotal_cents"] == 1_017_494
    assert float(reverted["chargeable_weight_kg"]) == 425.0
    assert reverted["billing_status"] == "UNQUOTED"
    assert reverted["quoted_total_cents"] == 0
    final_quote = validate_success(
        api.quote_order(ctx["order"]["id"], quote_payload(reverted["version"]),
                        order_planner_headers)
    )
    assert final_quote["quoted_total_cents"] == 1_120_619, "no drift from the 4.5-hour run"
    assert final_quote["install_amount_cents"] == 26_625
    assert final_quote["freight_cents"] == 76_500
    rows, meta = validate_paginated(
        api.list_order_lines(order_planner_headers,
                             params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[ctx["line"]["id"]]["status"] == "ACTIVE"
    assert by_id[added["id"]]["status"] == "VOIDED"
    assert by_id[added["id"]]["extended_price_cents"] == 513_517
