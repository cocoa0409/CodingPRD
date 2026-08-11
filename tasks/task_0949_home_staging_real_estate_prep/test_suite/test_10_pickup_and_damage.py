"""De-staging: the pickup at the door, damage pricing and the closeout cascade."""

from test_helpers import (
    ADMIN,
    CLERK,
    COORD,
    WAREHOUSE,
    ApiErrorId,
    assert_damage_assessment,
    assert_deposit_conservation,
    assert_money,
    assert_pickup,
    assert_same_instant,
    end_term_and_get_pickup,
    make_listing_agent_headers,
    pickup_version,
    set_clock,
    setup_vacant_mixed_pool_pickup_in_progress,
    setup_vacant_project_staged,
    start_pickup_in_progress,
    validate_error,
    validate_success,
)


def _window_cleared_and_reset(api, ctx):
    """Drive the escrow round trip so the auto-created pickup is cancelled, then end
    the term again to re-derive the closed pickup window."""
    agent = make_listing_agent_headers(ctx["agent_id"])
    set_clock("2026-10-08T09:00:00Z")
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))
    validate_success(api.listing_fall_out_of_escrow(ctx["listing_id"], agent))
    validate_success(api.mark_term_complete(ctx["lease_id"], COORD))


def test_completing_a_scheduled_pickup_is_an_invalid_pickup_state(api):
    """PRD §2.7: "Rung 28: the pickup's `state` is a legal origin for the requested
    transition; otherwise `ERR_PICKUP_INVALID_STATE`, HTTP 409."
    PRD §3.6: "Starting it requires the logical clock to have reached its `scheduled_at` and
    moves it `SCHEDULED → IN_PROGRESS`; **assessments may only be raised while the pickup is
    in progress**."

    Design: Corner/state_machines/pickup_complete_before_start_rejected_as_pickup_invalid_state
    """
    ctx = setup_vacant_project_staged()
    pickup_id = end_term_and_get_pickup(ctx)

    resp = api.complete_pickup(pickup_id, COORD)

    validate_error(resp, ApiErrorId.ERR_PICKUP_INVALID_STATE.value, 409)
    pickup = validate_success(api.get_pickup(pickup_id, COORD))
    assert_pickup(pickup)
    assert pickup["state"] == "SCHEDULED"
    assert validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))["state"] == "COMMITTED"
    assert validate_success(api.get_lease(ctx["lease_id"], COORD))["state"] == "ENDING"


def test_a_pickup_far_outside_the_window_is_refused(api):
    """PRD §2.7: "Rung 60: the pickup's `scheduled_at` falls inside the closed interval that
    runs from the lease's `pickup_window_start` through its `pickup_window_end`, both
    endpoints included; otherwise `ERR_PICKUP_OUTSIDE_WINDOW`, HTTP 422."
    PRD §3.5: "A pickup may be scheduled anywhere in that closed interval, endpoints
    included, and outside it the scheduling is refused with `ERR_PICKUP_OUTSIDE_WINDOW`."

    Design: Corner/validations/pickup_scheduled_outside_the_window_rejected
    """
    ctx = setup_vacant_project_staged()
    _window_cleared_and_reset(api, ctx)

    resp = api.schedule_pickup(
        ctx["proj_id"],
        {"lease_id": ctx["lease_id"], "scheduled_at": "2026-11-01T09:00:00Z"}, COORD)

    validate_error(resp, ApiErrorId.ERR_PICKUP_OUTSIDE_WINDOW.value, 422)
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert_same_instant(lease["pickup_window_end"], "2026-10-20T09:00:00Z",
                        "lease.pickup_window_end")


def test_a_pickup_exactly_on_the_window_end_instant_is_accepted(api):
    """PRD §3.5: "`pickup_window_start` is the anchor plus 5 days; `pickup_window_end` is
    `pickup_window_start` plus 7 days."
    PRD §3.5: "A pickup may be scheduled anywhere in that closed interval, endpoints
    included, and outside it the scheduling is refused with `ERR_PICKUP_OUTSIDE_WINDOW`."

    Design: Difficulty/boundary_precision_check/pickup_window_end_instant_is_inside_the_closed_interval
    """
    ctx = setup_vacant_project_staged()
    _window_cleared_and_reset(api, ctx)

    resp = api.schedule_pickup(
        ctx["proj_id"],
        {"lease_id": ctx["lease_id"], "scheduled_at": "2026-10-20T09:00:00Z"}, COORD)

    pickup = validate_success(resp, 201)
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert_same_instant(lease["pickup_window_start"], "2026-10-13T09:00:00Z",
                        "lease.pickup_window_start")
    assert_same_instant(lease["pickup_window_end"], "2026-10-20T09:00:00Z",
                        "lease.pickup_window_end")
    assert pickup["state"] == "SCHEDULED"
    assert_same_instant(pickup["scheduled_at"], "2026-10-20T09:00:00Z",
                        "pickup.scheduled_at")


def test_a_pickup_one_second_past_the_window_end_is_refused(api):
    """PRD §2.7: "Rung 60: the pickup's `scheduled_at` falls inside the closed interval that
    runs from the lease's `pickup_window_start` through its `pickup_window_end`, both
    endpoints included; otherwise `ERR_PICKUP_OUTSIDE_WINDOW`, HTTP 422."
    PRD §3.5: "`pickup_window_start` is the anchor plus 5 days; `pickup_window_end` is
    `pickup_window_start` plus 7 days."

    Design: Difficulty/boundary_precision_check/pickup_window_end_instant_is_inside_the_closed_interval
    """
    ctx = setup_vacant_project_staged()
    _window_cleared_and_reset(api, ctx)

    resp = api.schedule_pickup(
        ctx["proj_id"],
        {"lease_id": ctx["lease_id"], "scheduled_at": "2026-10-20T09:00:01Z"}, COORD)

    validate_error(resp, ApiErrorId.ERR_PICKUP_OUTSIDE_WINDOW.value, 422)


def test_the_fourth_pickup_reschedule_hits_the_attempt_limit(api):
    """PRD §2.7: "Rung 58: the pickup's `attempt_count` is strictly less than 3 before a
    `NO_ACCESS` or `REFUSED` pickup may be rescheduled; otherwise
    `ERR_PICKUP_ATTEMPT_LIMIT`, HTTP 409."
    PRD §3.6: "Both require the clock to have reached the scheduled instant, and both may be
    re-booked to a new `scheduled_at`, moving back to `SCHEDULED`, so long as
    `attempt_count` is strictly below 3 and the new instant is still inside the lease's
    pickup window."
    PRD §3.6: "`SCHEDULED → NO_ACCESS` means nobody was there; it increments
    `attempt_count` and leaves the holdover grace period intact."
    PRD §3.6: "`SCHEDULED → REFUSED` means the occupant turned the crew away; it also
    increments `attempt_count`, but it makes the lease eligible for holdover accrual
    immediately and **forfeits the two grace days entirely**, so every day past the window
    is chargeable from the first."

    The counter is advanced by the door event, not by the re-booking (unlike the install
    and the visit, whose §3.4/§3.7 sentences put the increment on the reschedule), so the
    third failed attempt is the one that closes the door on re-booking.

    Design: Corner/errors/fourth_pickup_reschedule_hits_the_attempt_limit
    """
    ctx = setup_vacant_project_staged()
    pickup_id = end_term_and_get_pickup(ctx)
    set_clock("2026-10-13T09:00:00Z")
    validate_success(api.pickup_no_access(pickup_id, COORD))
    validate_success(api.reschedule_pickup(pickup_id, "2026-10-15T09:00:00Z", COORD))
    set_clock("2026-10-15T09:00:00Z")
    validate_success(api.pickup_refuse(pickup_id, COORD))
    validate_success(api.reschedule_pickup(pickup_id, "2026-10-17T09:00:00Z", COORD))
    set_clock("2026-10-17T09:00:00Z")
    validate_success(api.pickup_no_access(pickup_id, COORD))

    resp = api.reschedule_pickup(pickup_id, "2026-10-19T09:00:00Z", COORD)

    validate_error(resp, ApiErrorId.ERR_PICKUP_ATTEMPT_LIMIT.value, 409)
    pickup = validate_success(api.get_pickup(pickup_id, COORD))
    assert pickup["attempt_count"] == 3
    assert pickup["state"] == "NO_ACCESS"


def test_an_item_older_than_seventy_two_months_takes_the_depreciation_floor(api):
    """PRD §3.6: "For an owned line the service computes the unit's age in whole months as
    the elapsed time from the item's `acquired_at` to the logical clock divided by 30-day
    months and floored, then selects a factor: an age of at most 12 months takes a factor of
    1.00, at most 36 months takes 0.70, at most 72 months takes 0.45, and anything older
    takes a floor factor of 0.25."
    PRD §3.6: "A `MISSING` finding charges the full depreciated replacement value with
    disposition `REPLACE`, because there is nothing left to salvage."

    Design: Corner/calculations/depreciation_floor_applies_beyond_seventy_two_months
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_c"], "condition_at_pickup": "MISSING",
                    "repair_cost_estimate": 0.00}, WAREHOUSE), 201)

    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))

    stored = validate_success(api.get_damage_assessment(assessment["id"], WAREHOUSE))
    assert_damage_assessment(stored)
    assert_money(stored["depreciated_replacement_value"], 375.00,
                 "assessment.depreciated_replacement_value")
    assert stored["disposition"] == "REPLACE"
    assert_money(stored["charge_amount"], 375.00, "assessment.charge_amount")


def test_an_owned_line_is_depreciated_by_its_own_age_band(api):
    """PRD §3.6: "The item's `replacement_value` is multiplied by that factor and rounded
    half-up to two decimal places — which means an identical sofa costs different money
    depending only on when the warehouse bought it."
    PRD §3.6: "**The band boundaries are inclusive at the top**, so exactly 12 months is the
    first band and 13 months is the second."

    Design: Difficulty/dual_variant_calc/depreciated_replacement_value_diverges_by_stock_pool_on_item_valuation
    """
    ctx = setup_vacant_mixed_pool_pickup_in_progress()
    assessment = validate_success(api.raise_damage_assessment(
        ctx["pickup_id"], {"pull_line_id": ctx["line_a"],
                           "condition_at_pickup": "MISSING"}, WAREHOUSE), 201)

    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))

    stored = validate_success(api.get_damage_assessment(assessment["id"], WAREHOUSE))
    assert_money(stored["depreciated_replacement_value"], 840.00,
                 "assessment.depreciated_replacement_value")
    assert_money(stored["charge_amount"], 840.00, "assessment.charge_amount")


def test_a_vendor_line_is_valued_on_the_vendors_flat_schedule_instead(api):
    """PRD §3.6: "For a vendor line age is ignored entirely: the value is a flat vendor unit
    replacement value of 900.00 multiplied by the line's `quantity` multiplied by one plus a
    15 percent vendor damage surcharge, rounded half-up to two decimal places."
    PRD §3.6: "That is the vendor's schedule, not the operator's."

    Design: Difficulty/dual_variant_calc/depreciated_replacement_value_diverges_by_stock_pool_on_item_valuation
    """
    ctx = setup_vacant_mixed_pool_pickup_in_progress()
    owned = validate_success(api.raise_damage_assessment(
        ctx["pickup_id"], {"pull_line_id": ctx["line_a"],
                           "condition_at_pickup": "MISSING"}, WAREHOUSE), 201)
    vendor = validate_success(api.raise_damage_assessment(
        ctx["pickup_id"], {"pull_line_id": ctx["line_v"],
                           "condition_at_pickup": "MISSING"}, WAREHOUSE), 201)
    validate_success(api.assess_damage(owned["id"], WAREHOUSE))

    validate_success(api.assess_damage(vendor["id"], WAREHOUSE))

    owned_row = validate_success(api.get_damage_assessment(owned["id"], WAREHOUSE))
    vendor_row = validate_success(api.get_damage_assessment(vendor["id"], WAREHOUSE))
    assert_money(vendor_row["depreciated_replacement_value"], 10350.00,
                 "vendor assessment.depreciated_replacement_value")
    assert float(owned_row["depreciated_replacement_value"]) != float(
        vendor_row["depreciated_replacement_value"]
    ), "the two stock pools must not be valued the same way"


def test_a_missing_finding_charges_the_whole_depreciated_value(api):
    """PRD §3.6: "A `MISSING` finding charges the full depreciated replacement value with
    disposition `REPLACE`, because there is nothing left to salvage."
    PRD §3.6: "Assessing the finding moves it `DRAFT → ASSESSED` and prices it in two steps."

    Design: Difficulty/combinatorial_formula/damage_charge_nested_branch_over_three_inputs
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_a"], "condition_at_pickup": "MISSING",
                    "repair_cost_estimate": 0.00}, WAREHOUSE), 201)

    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))

    stored = validate_success(api.get_damage_assessment(assessment["id"], WAREHOUSE))
    assert_money(stored["depreciated_replacement_value"], 840.00,
                 "assessment.depreciated_replacement_value")
    assert stored["disposition"] == "REPLACE"
    assert_money(stored["charge_amount"], 840.00, "assessment.charge_amount")


def test_a_major_finding_over_the_threshold_recovers_only_the_salvage_half(api):
    """PRD §3.6: "If the estimate is strictly greater, the disposition is `REPLACE` and the
    charge is 50 percent of the depreciated replacement value — the salvage recovery rate —
    rounded half-up to two decimal places."
    PRD §3.6: "This pricing is **non-monotone by construction**: because a written-off unit
    is broken for parts and recovers half its depreciated value, crossing the threshold from
    below *drops* the customer's bill — sixty percent of the value on the last repair cent,
    fifty percent on the first replace cent — so a higher repair estimate can produce a
    lower charge."

    Design: Difficulty/combinatorial_formula/damage_charge_nested_branch_over_three_inputs
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_b"], "condition_at_pickup": "MAJOR",
                    "repair_cost_estimate": 700.00}, WAREHOUSE), 201)

    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))

    stored = validate_success(api.get_damage_assessment(assessment["id"], WAREHOUSE))
    assert_money(stored["depreciated_replacement_value"], 630.00,
                 "assessment.depreciated_replacement_value")
    assert stored["disposition"] == "REPLACE"
    assert_money(stored["charge_amount"], 315.00, "assessment.charge_amount")


def test_an_estimate_exactly_at_sixty_percent_stays_on_the_repair_arm(api):
    """PRD §3.6: "A `MINOR` or `MAJOR` finding compares the `repair_cost_estimate` against 60
    percent of the depreciated replacement value, and the comparison is **strict**: an
    estimate exactly equal to sixty percent stays on the repair arm."
    PRD §3.6: "Otherwise the disposition is `REPAIR` and the charge is the smaller of the
    `repair_cost_estimate` and the depreciated replacement value."

    Design: Difficulty/boundary_precision_check/damage_threshold_is_strict_at_sixty_percent_of_drv
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_a"], "condition_at_pickup": "MAJOR",
                    "repair_cost_estimate": 504.00}, WAREHOUSE), 201)

    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))

    stored = validate_success(api.get_damage_assessment(assessment["id"], WAREHOUSE))
    assert_money(stored["depreciated_replacement_value"], 840.00,
                 "assessment.depreciated_replacement_value")
    assert stored["disposition"] == "REPAIR"
    assert_money(stored["charge_amount"], 504.00, "assessment.charge_amount")


def test_one_cent_over_the_threshold_flips_to_replace_and_lowers_the_charge(api):
    """PRD §3.6: "Revising moves it `DISPUTED → REVISED`, replaces the `repair_cost_estimate`
    with the supplied `revised_repair_cost`, and recomputes both `charge_amount` and
    `disposition` from that new estimate."
    PRD §3.6: "If the estimate is strictly greater, the disposition is `REPLACE` and the
    charge is 50 percent of the depreciated replacement value — the salvage recovery rate —
    rounded half-up to two decimal places."

    Design: Difficulty/boundary_precision_check/damage_threshold_is_strict_at_sixty_percent_of_drv
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_a"], "condition_at_pickup": "MAJOR",
                    "repair_cost_estimate": 504.00}, WAREHOUSE), 201)
    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))
    validate_success(api.dispute_damage(
        assessment["id"], {"dispute_note": "Quote was understated"},
        make_listing_agent_headers(ctx["agent_id"])))

    validate_success(api.adjudicate_damage(
        assessment["id"], {"decision": "REVISE", "revised_repair_cost": 504.01}, ADMIN))

    stored = validate_success(api.get_damage_assessment(assessment["id"], WAREHOUSE))
    assert_money(stored["depreciated_replacement_value"], 840.00,
                 "assessment.depreciated_replacement_value")
    assert_money(stored["repair_cost_estimate"], 504.01, "assessment.repair_cost_estimate")
    assert stored["disposition"] == "REPLACE"
    assert_money(stored["charge_amount"], 420.00, "assessment.charge_amount")
    assert stored["appeal_count"] == 1
    assert stored["state"] == "REVISED"


def test_a_second_dispute_on_the_same_finding_is_refused(api):
    """PRD §2.7: "Rung 59: the assessment's `appeal_count` is strictly less than 1 before an
    `ASSESSED` assessment may be disputed; otherwise `ERR_APPEAL_LIMIT_REACHED`, HTTP 409."
    PRD §3.6: "The listing agent or the seller disputes an `ASSESSED` finding, optionally
    carrying a `dispute_note`, which moves it `ASSESSED → DISPUTED` and increments
    `appeal_count`; a second dispute is refused with `ERR_APPEAL_LIMIT_REACHED` because the
    cap is one appeal."

    Design: Corner/errors/second_damage_dispute_hits_the_appeal_limit
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    agent = make_listing_agent_headers(ctx["agent_id"])
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_c"], "condition_at_pickup": "MINOR",
                    "repair_cost_estimate": 40.00}, WAREHOUSE), 201)
    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))
    validate_success(api.dispute_damage(
        assessment["id"], {"dispute_note": "Scratch predates the install"}, agent))
    validate_success(api.adjudicate_damage(
        assessment["id"], {"decision": "REVISE", "revised_repair_cost": 90.00}, ADMIN))
    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))

    resp = api.dispute_damage(assessment["id"], {"dispute_note": "Still disputed"}, agent)

    validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value, 409)
    stored = validate_success(api.get_damage_assessment(assessment["id"], WAREHOUSE))
    assert stored["appeal_count"] == 1
    assert stored["state"] == "ASSESSED"
    assert_money(stored["repair_cost_estimate"], 90.00, "assessment.repair_cost_estimate")
    assert_money(stored["charge_amount"], 90.00, "assessment.charge_amount")
    assert stored["disposition"] == "REPAIR"


def test_a_pickup_cannot_complete_while_an_assessment_is_short_of_final(api):
    """PRD §2.7: "Rung 29: the damage assessment's `state` is a legal origin for the
    requested transition, and every assessment on a pickup is `FINAL` before that pickup may
    complete; otherwise `ERR_ASSESSMENT_INVALID_STATE`, HTTP 409."
    PRD §3.6: "**Completing the pickup fires the seven-hop closeout cascade**, and it is
    refused unless every assessment on that pickup has reached `FINAL`."

    Design: Difficulty/cross_entity_state_dependency/pickup_cannot_complete_while_an_assessment_is_not_final
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_c"], "condition_at_pickup": "MINOR",
                    "repair_cost_estimate": 40.00}, WAREHOUSE), 201)
    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))

    resp = api.complete_pickup(pickup_id, COORD)

    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE.value, 409)
    assert validate_success(api.get_pickup(pickup_id, COORD))["state"] == "IN_PROGRESS"
    assert validate_success(
        api.get_damage_assessment(assessment["id"], WAREHOUSE))["state"] == "ASSESSED"


def test_the_blocking_assessment_carries_its_repair_arm_pricing(api):
    """PRD §3.6: "Otherwise the disposition is `REPAIR` and the charge is the smaller of the
    `repair_cost_estimate` and the depreciated replacement value."
    PRD §3.6: "For an owned line the service computes the unit's age in whole months as the
    elapsed time from the item's `acquired_at` to the logical clock divided by 30-day months
    and floored, then selects a factor: an age of at most 12 months takes a factor of 1.00,
    at most 36 months takes 0.70, at most 72 months takes 0.45, and anything older takes a
    floor factor of 0.25."

    Design: Difficulty/cross_entity_state_dependency/pickup_cannot_complete_while_an_assessment_is_not_final
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_c"], "condition_at_pickup": "MINOR",
                    "repair_cost_estimate": 40.00}, WAREHOUSE), 201)

    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))

    stored = validate_success(api.get_damage_assessment(assessment["id"], WAREHOUSE))
    assert_money(stored["depreciated_replacement_value"], 375.00,
                 "assessment.depreciated_replacement_value")
    assert stored["disposition"] == "REPAIR"
    assert_money(stored["charge_amount"], 40.00, "assessment.charge_amount")


def test_a_second_finalize_carrying_the_pre_first_pickup_version_is_stale(api):
    """PRD §2.9: "Finalizing a damage assessment requires `expected_pickup_version` carrying
    the client's last observed `version` of the parent `Pickup`. A mismatch is rejected with
    `ERR_STALE_PICKUP_VERSION` (HTTP 412)."
    PRD §3.6: "It adds the assessment's `charge_amount` to the pickup's `damage_total`,
    increments the pickup's `assessed_line_count`, bumps the pickup's `version` by 1, and
    sends the unit down the arc its disposition demands: a repair disposition moves the
    owned item `DEPLOYED → IN_REPAIR` and degrades its `condition_grade` one step, while a
    replace disposition moves it `DEPLOYED → WRITTEN_OFF` and marks the line returned."

    Design: Corner/cross_cutting_complexity_layers/stale_pickup_version_on_damage_finalize_returns_412
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    first = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_a"], "condition_at_pickup": "MISSING",
                    "repair_cost_estimate": 0.00}, WAREHOUSE), 201)
    second = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_c"], "condition_at_pickup": "MINOR",
                    "repair_cost_estimate": 40.00}, WAREHOUSE), 201)
    validate_success(api.assess_damage(first["id"], WAREHOUSE))
    validate_success(api.assess_damage(second["id"], WAREHOUSE))
    observed = pickup_version(pickup_id)
    validate_success(api.finalize_damage(first["id"], observed, WAREHOUSE))

    resp = api.finalize_damage(second["id"], observed, WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_STALE_PICKUP_VERSION.value, 412)
    assert validate_success(
        api.get_damage_assessment(first["id"], WAREHOUSE))["state"] == "FINAL"
    assert validate_success(
        api.get_damage_assessment(second["id"], WAREHOUSE))["state"] == "ASSESSED"
    pickup = validate_success(api.get_pickup(pickup_id, COORD))
    assert_money(pickup["damage_total"], 840.00, "pickup.damage_total")
    assert pickup["assessed_line_count"] == 1


def test_pickup_completion_releases_the_pull_and_returns_every_unit(api):
    """PRD §3.6: "The pickup's `completed_at` is stamped from the logical clock, and then,
    in order: hop one moves the inventory pull `COMMITTED → RELEASED`; hop two, because the
    pull released, moves every `DEPLOYED` pull line to `RETURNED`; hop three, because those
    lines returned, moves every owned item `DEPLOYED → AVAILABLE` — except those an
    assessment already sent to `IN_REPAIR` or `WRITTEN_OFF`, which stay where they are — and
    moves every `DELIVERED` rental order to `RETURNED`; hop four, because the vendor orders
    returned, moves the lease from `ENDING` or `HOLDOVER` to `ENDED`; hop five, because the
    lease ended, materialises a `DRAFT` invoice on the project with its `line_summary`
    populated from the lease, extension, holdover and damage components; hop six, because
    the invoice was materialised, runs the deposit waterfall and moves the deposit `HELD →
    PARTIALLY_APPLIED` or `HELD → APPLIED`; and hop seven, because the deposit was applied,
    moves the project `DESTAGE_PENDING → PICKED_UP` and the property `STAGED → DESTAGED`."

    Design: Difficulty/transitive_cascade/pickup_complete_seven_hop_closeout_cascade
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)

    validate_success(api.complete_pickup(pickup_id, COORD))

    assert validate_success(api.get_pickup(pickup_id, COORD))["state"] == "COMPLETED"
    assert validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))["state"] == "RELEASED"
    assert validate_success(
        api.get_pull_line(ctx["line_a"], WAREHOUSE))["state"] == "RETURNED"
    assert validate_success(
        api.get_inventory_item(ctx["item_a"], WAREHOUSE))["status"] == "AVAILABLE"
    assert validate_success(
        api.get_rental_order(ctx["ro_id"], WAREHOUSE))["state"] == "RETURNED"
    assert validate_success(api.get_lease(ctx["lease_id"], COORD))["state"] == "ENDED"


def test_pickup_completion_settles_the_deposit_and_advances_project_and_property(api):
    """PRD §3.6: "The pickup's `completed_at` is stamped from the logical clock, and then,
    in order: hop one moves the inventory pull `COMMITTED → RELEASED`; hop two, because the
    pull released, moves every `DEPLOYED` pull line to `RETURNED`; hop three, because those
    lines returned, moves every owned item `DEPLOYED → AVAILABLE` — except those an
    assessment already sent to `IN_REPAIR` or `WRITTEN_OFF`, which stay where they are — and
    moves every `DELIVERED` rental order to `RETURNED`; hop four, because the vendor orders
    returned, moves the lease from `ENDING` or `HOLDOVER` to `ENDED`; hop five, because the
    lease ended, materialises a `DRAFT` invoice on the project with its `line_summary`
    populated from the lease, extension, holdover and damage components; hop six, because
    the invoice was materialised, runs the deposit waterfall and moves the deposit `HELD →
    PARTIALLY_APPLIED` or `HELD → APPLIED`; and hop seven, because the deposit was applied,
    moves the project `DESTAGE_PENDING → PICKED_UP` and the property `STAGED → DESTAGED`."

    Design: Difficulty/transitive_cascade/pickup_complete_seven_hop_closeout_cascade
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)

    validate_success(api.complete_pickup(pickup_id, COORD))

    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert deposit["state"] == "APPLIED"
    assert_deposit_conservation(deposit)
    assert validate_success(
        api.get_project(ctx["proj_id"], COORD))["workflow_state"] == "PICKED_UP"
    assert validate_success(
        api.get_property(ctx["prop_id"], COORD))["prep_state"] == "DESTAGED"


def test_the_waterfall_fills_damage_before_it_touches_the_balance(api):
    """PRD §3.3: "Starting from the current `held_remaining`, the first bucket takes the
    smaller of what remains and the pickup's `damage_total` and adds it to
    `applied_to_damage`. What survives that then meets the second bucket, which takes the
    smaller of the remainder and the lease's `holdover_charge` and adds it to
    `applied_to_holdover`. What survives *that* meets the third bucket, which takes the
    smaller of the remainder and the invoice's `subtotal` plus its `tax_amount` and adds it
    to `applied_to_balance`."
    PRD §3.3: "Each bucket's contribution is rounded half-up to two decimal places as it is
    accumulated, and `held_remaining` is set to the rounded residue."

    Design: Difficulty/combinatorial_formula/deposit_waterfall_fills_damage_then_holdover_then_balance
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_a"], "condition_at_pickup": "MISSING",
                    "repair_cost_estimate": 0.00}, WAREHOUSE), 201)
    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))
    validate_success(api.finalize_damage(
        assessment["id"], pickup_version(pickup_id), WAREHOUSE))

    validate_success(api.complete_pickup(pickup_id, COORD))

    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert_money(deposit["amount"], 2307.00, "deposit.amount")
    assert_money(deposit["applied_to_damage"], 840.00, "deposit.applied_to_damage")
    assert_money(deposit["applied_to_holdover"], 0.00, "deposit.applied_to_holdover")
    assert_money(deposit["applied_to_balance"], 1467.00, "deposit.applied_to_balance")


def test_a_fully_consumed_deposit_reaches_applied_with_no_residue(api):
    """PRD §3.3: "When a run consumes the entire remainder, `held_remaining` becomes 0.00,
    `invoice_id` is set to the invoice consumed against, and the deposit reaches `APPLIED`."
    PRD §3.6: "It adds the assessment's `charge_amount` to the pickup's `damage_total`,
    increments the pickup's `assessed_line_count`, bumps the pickup's `version` by 1, and
    sends the unit down the arc its disposition demands: a repair disposition moves the
    owned item `DEPLOYED → IN_REPAIR` and degrades its `condition_grade` one step, while a
    replace disposition moves it `DEPLOYED → WRITTEN_OFF` and marks the line returned."

    Design: Difficulty/combinatorial_formula/deposit_waterfall_fills_damage_then_holdover_then_balance
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    assessment = validate_success(api.raise_damage_assessment(
        pickup_id, {"pull_line_id": ctx["line_a"], "condition_at_pickup": "MISSING",
                    "repair_cost_estimate": 0.00}, WAREHOUSE), 201)
    validate_success(api.assess_damage(assessment["id"], WAREHOUSE))
    validate_success(api.finalize_damage(
        assessment["id"], pickup_version(pickup_id), WAREHOUSE))

    validate_success(api.complete_pickup(pickup_id, COORD))

    pickup = validate_success(api.get_pickup(pickup_id, COORD))
    assert_money(pickup["damage_total"], 840.00, "pickup.damage_total")
    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))
    assert_money(deposit["held_remaining"], 0.00, "deposit.held_remaining")
    assert deposit["state"] == "APPLIED"
    assert_deposit_conservation(deposit)
    assert validate_success(
        api.get_inventory_item(ctx["item_a"], WAREHOUSE))["status"] == "WRITTEN_OFF"


def test_the_pickup_completion_response_already_shows_the_settled_deposit(api):
    """PRD §2.4: "The same applies to every computed attribute — a response body reflects
    post-write state, never a snapshot taken before the handler's own effects landed."
    PRD §3.3: "When a run consumes the entire remainder, `held_remaining` becomes 0.00,
    `invoice_id` is set to the invoice consumed against, and the deposit reaches `APPLIED`."

    Design: Corner/consistency_model/pickup_complete_response_reflects_the_whole_cascade_immediately
    """
    ctx = setup_vacant_project_staged()
    pickup_id = start_pickup_in_progress(ctx)
    validate_success(api.complete_pickup(pickup_id, COORD))

    deposit = validate_success(api.get_deposit(ctx["dep_id"], CLERK))

    assert_money(deposit["applied_to_balance"], 2307.00, "deposit.applied_to_balance")
    assert_money(deposit["held_remaining"], 0.00, "deposit.held_remaining")
    assert deposit["state"] == "APPLIED"
    assert validate_success(
        api.get_project(ctx["proj_id"], COORD))["workflow_state"] == "PICKED_UP"
