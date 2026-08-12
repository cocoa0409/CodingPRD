"""Re-screening, the three-rung substitution ladder, the attempt cap and short fill."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_substitution_event,
    list_credits_of,
    list_substitution_events,
    read_account,
    read_cycle,
    read_cycle_line,
    setup_allocated_cycle,
    unique_code,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_allergen_flag,
    setup_cycle_line_pending_by_allergen,
    substitute_line,
)

OPS = TEST_USERS["ops_admin_headers"]

# SKU A is the cheapest and carries FRAGRANCE; B is the rung-one winner once A
# is disqualified; C is the winner once B is disqualified too.
LADDER_SKUS = [
    {"code": "S2-A", "name": "Stage 2 A", "pack_price_cents": 1200,
     "pack_size_units": 60, "allergen_tags": ["FRAGRANCE"]},
    {"code": "S2-B", "name": "Stage 2 B", "pack_price_cents": 1500,
     "pack_size_units": 80, "allergen_tags": ["DYE"]},
    {"code": "S2-C", "name": "Stage 2 C", "pack_price_cents": 1800,
     "pack_size_units": 90, "allergen_tags": []},
]


def _uniqued(specs):
    return [dict(spec, code=unique_code(spec["code"])) for spec in specs]


# ==========================================================================
# The re-screen cascade
# ==========================================================================
def test_a_new_severe_flag_pushes_the_allocated_line_into_the_queue(api):
    """PRD §3.6: "Hop two: because that flag now exists, every cycle line whose SKU no
    longer passes the allergen screen moves `ALLOCATED → SUBSTITUTION_PENDING` — but only on
    cycles whose `status` is `PLANNED` or `ALLOCATED`."
    PRD §3.6: "A successful run creates a `SubstitutionEvent` recording the `cycle_line_id`
    it ran for, the `from_sku_id` that became unusable, the `to_sku_id` selected, the
    `ladder_rung` that produced the winner as 1, 2 or 3, an `outcome` of `SUBSTITUTED`, a
    `price_delta_cents` equal to the incoming SKU's effective per-pack price minus the
    outgoing SKU's effective per-pack price (a signed figure, computed on the same
    surcharge-inclusive basis as any other pack price), and a `reason` of either
    `OUT_OF_STOCK` or `ALLERGEN_RESCREEN` depending on what pushed the line into the queue."

    Design: Difficulty/transitive_cascade/allergen_flag_cascade_rescreen_substitute_reprice
    """
    specs = _uniqued([
        {"code": "S2-A", "name": "Stage 2 A", "pack_price_cents": 1200,
         "pack_size_units": 60, "allergen_tags": ["FRAGRANCE"]},
        {"code": "S2-B", "name": "Stage 2 B", "pack_price_cents": 1500,
         "pack_size_units": 80, "allergen_tags": []},
    ])
    ctx, cycle, line, skus = setup_cycle_line_pending_by_allergen(api, sku_specs=specs)
    assert line["status"] == "SUBSTITUTION_PENDING"

    substituted = substitute_line(api, line["id"])
    assert substituted["sku_id"] == skus[1]["id"], "rung one picks the same-size, same-line SKU"
    assert substituted["line_total_cents"] == 3000
    assert substituted["status"] == "SUBSTITUTED"

    events = list_substitution_events(api, line["id"])
    assert len(events) == 1
    assert_substitution_event(events[0])
    assert events[0]["ladder_rung"] == 1
    assert events[0]["price_delta_cents"] == 300
    assert events[0]["reason"] == "ALLERGEN_RESCREEN"


def test_the_substitution_reprices_the_cycle_and_the_household_estimate(api):
    """PRD §3.6: "That is hop three of the cascade. Hop four follows because the line total
    changed: the cycle's `subtotal_cents`, `shipping_cents` and `total_due_cents` are
    recomputed. Hop five follows because the total changed: the household's
    `next_charge_estimate_cents` is recomputed."
    PRD §3.1: "`next_charge_estimate_cents` looks forward instead: it finds the earliest
    cycle across all of the household's non-cancelled subscriptions whose `status` is
    `PLANNED` or `ALLOCATED`, ordering candidates by `window_start` ascending and breaking
    ties by `created_at` ascending, and reports that cycle's `total_due_cents`."

    Design: Difficulty/transitive_cascade/allergen_flag_cascade_rescreen_substitute_reprice
    """
    specs = _uniqued([
        {"code": "S2-A", "name": "Stage 2 A", "pack_price_cents": 1200,
         "pack_size_units": 60, "allergen_tags": ["FRAGRANCE"]},
        {"code": "S2-B", "name": "Stage 2 B", "pack_price_cents": 1500,
         "pack_size_units": 80, "allergen_tags": []},
    ])
    ctx, cycle, line, _skus = setup_cycle_line_pending_by_allergen(api, sku_specs=specs)
    substitute_line(api, line["id"])

    repriced = read_cycle(api, cycle["id"])
    assert repriced["subtotal_cents"] == 3000
    assert repriced["shipping_cents"] == 599
    assert repriced["total_due_cents"] == 3599

    account = read_account(api, ctx["account_id"])
    assert account["next_charge_estimate_cents"] == 3599


# ==========================================================================
# The re-entrant SUBSTITUTED -> SUBSTITUTION_PENDING loop
# ==========================================================================
def test_a_substituted_line_re_enters_the_queue_and_runs_the_ladder_again(api):
    """PRD §3.6: "A line that was previously substituted can be caught by a later flag too,
    moving `SUBSTITUTED → SUBSTITUTION_PENDING`, and that transition does not consult the
    attempt cap — a line can always be re-flagged."
    PRD §3.6: "The line itself is repointed at the winning `sku_id`, its
    `substitution_attempts` is incremented, and its `unit_price_cents` and
    `line_total_cents` are recomputed."

    Design: Difficulty/non_linear_state_machine/cycle_line_substitution_loop_reenters_pending
    """
    ctx, cycle, line, skus = setup_cycle_line_pending_by_allergen(
        api, sku_specs=_uniqued(LADDER_SKUS)
    )
    substitute_line(api, line["id"])

    add_allergen_flag(api, ctx, "DYE", "SEVERE")
    reflagged = read_cycle_line(api, line["id"])
    assert reflagged["status"] == "SUBSTITUTION_PENDING"

    final = substitute_line(api, line["id"])
    assert final["sku_id"] == skus[2]["id"]
    assert final["substitution_attempts"] == 2
    assert final["status"] == "SUBSTITUTED"
    assert final["line_total_cents"] == 3600


def test_the_re_entrant_loop_writes_one_rung_one_event_per_run(api):
    """PRD §3.6: "Rung one looks for the same size in the same product line at a different
    pack size: an `ACTIVE` SKU whose `stage` equals the outgoing SKU's stage, whose `line`
    equals the outgoing SKU's line, whose `pack_size_units` differs from the outgoing SKU's,
    whose `stock_packs` is at least the line's `quantity_packs`, and which passes the
    allergen screen for the child."
    PRD §3.6: "The `SUBSTITUTED → SUBSTITUTION_PENDING → SUBSTITUTED` loop is therefore a
    capped retry loop in which the third run is the last permitted one."

    Design: Difficulty/non_linear_state_machine/cycle_line_substitution_loop_reenters_pending
    """
    ctx, cycle, line, _skus = setup_cycle_line_pending_by_allergen(
        api, sku_specs=_uniqued(LADDER_SKUS)
    )
    substitute_line(api, line["id"])
    add_allergen_flag(api, ctx, "DYE", "SEVERE")
    substitute_line(api, line["id"])

    events = list_substitution_events(api, line["id"])
    assert len(events) == 2, f"one event per ladder run, got {len(events)}"
    assert [e["ladder_rung"] for e in events] == [1, 1]
    for event in events:
        assert event["outcome"] == "SUBSTITUTED"


# ==========================================================================
# The attempt cap
# ==========================================================================
def test_a_fourth_substitution_attempt_hits_the_cap(api):
    """PRD §3.6: "A line may run the ladder at most three times. The cap is checked when the
    substitution is attempted, not when the line is flagged: a line whose
    `substitution_attempts` has reached 3 simply sits in `SUBSTITUTION_PENDING`, and every
    further substitution attempt is refused with `ERR_SUBSTITUTION_CAP_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/corner_fourth_substitution_attempt_hits_cap
    """
    specs = _uniqued([
        {"code": "S2-A", "name": "Stage 2 A", "pack_price_cents": 1200,
         "pack_size_units": 60, "allergen_tags": ["FRAGRANCE"]},
        {"code": "S2-B", "name": "Stage 2 B", "pack_price_cents": 1300,
         "pack_size_units": 70, "allergen_tags": ["DYE"]},
        {"code": "S2-C", "name": "Stage 2 C", "pack_price_cents": 1400,
         "pack_size_units": 80, "allergen_tags": ["LOTION"]},
        {"code": "S2-D", "name": "Stage 2 D", "pack_price_cents": 1500,
         "pack_size_units": 90, "allergen_tags": ["ALOE"]},
        {"code": "S2-E", "name": "Stage 2 E", "pack_price_cents": 1600,
         "pack_size_units": 100, "allergen_tags": []},
    ])
    ctx, cycle, line, skus = setup_cycle_line_pending_by_allergen(api, sku_specs=specs)
    substitute_line(api, line["id"])
    add_allergen_flag(api, ctx, "DYE", "SEVERE")
    substitute_line(api, line["id"])
    add_allergen_flag(api, ctx, "LOTION", "SEVERE")
    substitute_line(api, line["id"])
    add_allergen_flag(api, ctx, "ALOE", "SEVERE")

    resp = api.substitute_cycle_line(line["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_CAP_EXCEEDED.value, 409)

    capped = read_cycle_line(api, line["id"])
    assert capped["substitution_attempts"] == 3
    assert capped["sku_id"] == skus[3]["id"]
    assert capped["status"] == "SUBSTITUTION_PENDING"
    assert len(list_substitution_events(api, line["id"])) == 3


def test_substituting_a_line_that_is_still_allocated_is_refused(api):
    """PRD §3.6: "A cycle line therefore has its own axis — `ALLOCATED`,
    `SUBSTITUTION_PENDING`, `SUBSTITUTED` and `SHORT_FILLED`, the last of which is terminal —
    and any operation whose from-state does not match is refused with
    `ERR_LINE_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/corner_substitute_on_allocated_line_rejected
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="linestate")
    lines, _meta = validate_paginated(api.list_cycle_lines(OPS, {"cycle_id": cycle["id"]}))
    line = lines[0]
    assert line["status"] == "ALLOCATED"

    resp = api.substitute_cycle_line(line["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_LINE_STATE_INVALID.value, 409)

    after = read_cycle_line(api, line["id"])
    assert after["status"] == "ALLOCATED"
    assert after["substitution_attempts"] == 0
    assert not list_substitution_events(api, line["id"])


# ==========================================================================
# Short fill
# ==========================================================================
def test_an_exhausted_ladder_short_fills_and_compensates_in_full(api):
    """PRD §3.6: "When all three rungs come back empty, the line is short-filled — and this
    is a successful 200 OK outcome, not an error. A `SubstitutionEvent` is written with
    `outcome` `SHORT_FILLED`, `ladder_rung` 0, a null `to_sku_id` and a `price_delta_cents`
    of 0."
    PRD §3.6: "The line's `short_filled_units` is set to the units the household will not
    receive, namely its `quantity_packs` multiplied by the outgoing SKU's `pack_size_units`;
    its `quantity_packs` is then set to 0 and its `line_total_cents` to 0."
    PRD §3.6: "The household is compensated in full: a `Credit` of `credit_type`
    `SHORT_FILL` is issued for 100 percent of the line's pre-zeroing value — its
    `quantity_packs` multiplied by its `unit_price_cents`, rounded half up to whole cents —
    with `remaining_cents` equal to that face value, `refundable` true and `expires_at` 365
    days after the logical clock."

    Design: Corner/calculations/corner_short_fill_issues_full_value_credit_when_ladder_exhausts
    """
    specs = _uniqued([
        {"code": "S2-ONLY", "name": "Stage 2 Only", "pack_price_cents": 1200,
         "pack_size_units": 60, "allergen_tags": ["FRAGRANCE"]},
    ])
    ctx, cycle, line, _skus = setup_cycle_line_pending_by_allergen(api, sku_specs=specs)

    resp = api.substitute_cycle_line(line["id"], OPS)
    short_filled = validate_success(resp, 200)
    assert short_filled["status"] == "SHORT_FILLED"
    assert short_filled["short_filled_units"] == 120, "2 packs of 60 units never arrive"

    after_line = read_cycle_line(api, line["id"])
    assert after_line["quantity_packs"] == 0
    assert after_line["line_total_cents"] == 0

    after_cycle = read_cycle(api, cycle["id"])
    assert after_cycle["subtotal_cents"] == 0
    assert after_cycle["shipping_cents"] == 599
    assert after_cycle["total_due_cents"] == 599

    credits = list_credits_of(api, ctx["account_id"], credit_type="SHORT_FILL")
    assert len(credits) == 1
    assert credits[0]["issued_cents"] == 2400
    assert credits[0]["refundable"] is True

    events = list_substitution_events(api, line["id"])
    assert len(events) == 1
    assert events[0]["ladder_rung"] == 0
    assert events[0]["to_sku_id"] is None
    assert events[0]["reason"] == "ALLERGEN_RESCREEN"


# ==========================================================================
# Stock adjustments feeding the queue
# ==========================================================================
def test_a_stock_drop_below_the_line_quantity_queues_the_line(api):
    """PRD §3.3: "A negative adjustment has a consequence beyond the catalog: any cycle line
    sitting on a cycle whose `status` is `PLANNED` or `ALLOCATED` that can no longer be
    filled from the remaining stock is pushed from `ALLOCATED` into `SUBSTITUTION_PENDING`,
    joining the substitution queue described in section 3.6."

    Design: Difficulty/cross_entity_state_dependency/sku_stock_drop_forces_allocated_line_into_substitution_pending
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="stock")
    lines, _meta = validate_paginated(api.list_cycle_lines(OPS, {"cycle_id": cycle["id"]}))
    line = lines[0]

    adjusted = validate_success(api.adjust_sku_stock(ctx["sku"]["id"], -48, OPS))
    assert adjusted["stock_packs"] == 0

    after = read_cycle_line(api, line["id"])
    assert after["status"] == "SUBSTITUTION_PENDING"
    assert after["sku_id"] == ctx["sku"]["id"], "the line still points at the failed SKU"
    assert read_cycle(api, cycle["id"])["status"] == "ALLOCATED"


def test_an_over_subtraction_floors_the_stock_at_zero_and_still_queues_the_line(api):
    """PRD §3.3: "Operators move stock by submitting a signed `delta_packs`. The SKU's
    `stock_packs` becomes the old value plus the delta, floored at 0 — a negative adjustment
    larger than the stock on hand leaves 0 rather than a negative number."

    Design: Difficulty/cross_entity_state_dependency/sku_stock_drop_forces_allocated_line_into_substitution_pending
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="stock2")
    lines, _meta = validate_paginated(api.list_cycle_lines(OPS, {"cycle_id": cycle["id"]}))
    line = lines[0]

    adjusted = validate_success(api.adjust_sku_stock(ctx["sku"]["id"], -100, OPS))
    assert adjusted["stock_packs"] == 0, "stock never goes negative"

    assert read_cycle_line(api, line["id"])["status"] == "SUBSTITUTION_PENDING"


def test_the_stock_adjustment_response_and_the_line_read_agree_immediately(api):
    """PRD §3.3: "A negative adjustment has a consequence beyond the catalog: any cycle line
    sitting on a cycle whose `status` is `PLANNED` or `ALLOCATED` that can no longer be
    filled from the remaining stock is pushed from `ALLOCATED` into `SUBSTITUTION_PENDING`,
    joining the substitution queue described in section 3.6."
    PRD §3.6: "Hop four follows because the line total changed: the cycle's
    `subtotal_cents`, `shipping_cents` and `total_due_cents` are recomputed."

    Design: Corner/consistency_model/corner_stock_adjustment_reconciles_the_line_in_the_same_request
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="recon")
    lines, _meta = validate_paginated(api.list_cycle_lines(OPS, {"cycle_id": cycle["id"]}))
    line = lines[0]

    adjusted = validate_success(api.adjust_sku_stock(ctx["sku"]["id"], -48, OPS))
    assert adjusted["stock_packs"] == 0
    assert read_cycle_line(api, line["id"])["status"] == "SUBSTITUTION_PENDING"
    assert read_cycle(api, cycle["id"])["subtotal_cents"] == 2400, (
        "no substitution has run yet, so no repricing hop has fired"
    )
