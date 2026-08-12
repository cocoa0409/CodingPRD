"""The minimum call-out floor, the overtime edge, the two trip-count variants,
the commission band-three edge and the overage allowance boundary."""

from test_helpers import (
    BILLING_ADMIN,
    FREEZE_INSTANT,
    MOVE_MANAGER,
    MOVE_START,
    PACKAGE_BASE_CENTS,
    api_client,
    assert_exactly_one_line,
    assert_hours,
    assert_money,
    assert_no_line_of_type,
    assert_two_dp,
    commission_cents,
    confirm_assignment,
    consignment_fees_cents,
    designate,
    drive_sort_plan_to_approved,
    get_success_data,
    invoice_lines,
    labor_cents,
    net_proceeds_cents,
    new_consignment_lot,
    new_item,
    new_move_day_plan,
    new_vendor,
    read_crew_assignment,
    read_engagement,
    read_invoice,
    read_lot,
    read_move_day_plan,
    set_clock,
    setup_completed_move_day,
    setup_engagement,
    staff_lead_and_packer,
    trip_count,
    validate_paginated,
    validate_success,
    package_overage_cents,
)

DONATE_SPEC = {
    "label": "Old linens",
    "category": "LINENS",
    "footprint_linear_inches": 10,
    "volume_cft": 5,
}


def _two_hour_move_day(billing_mode, package_tier=None):
    return setup_completed_move_day(
        billing_mode=billing_mode,
        package_tier=package_tier,
        keep_items=[],
        other_items=[dict(DONATE_SPEC)],
        lead_in=MOVE_START,
        packer_in=MOVE_START,
        packer_out="2026-06-15T16:00:00.000Z",
        lead_out="2026-06-15T16:00:00.000Z",
        complete_at="2026-06-15T16:00:00.000Z",
        actual_loaded_volume_cft=5,
    )


def test_the_hourly_pipeline_lifts_a_two_hour_shift_to_the_call_out_floor():
    """PRD §3.7: "`applied_hours` applies the minimum call-out floor, and this is the
    first place the two pipelines part company: under `HOURLY` it is the greater of
    `billing_hours` and three hours, while under `PACKAGE` there is no floor at all
    and `applied_hours` simply equals `billing_hours`."

    Design: Corner/calculations/hourly_pipeline_applies_the_minimum_call_out_floor_to_a_short_shift
    """
    world = _two_hour_move_day("HOURLY")
    lead = read_crew_assignment(world["lead_assignment"]["id"])
    packer = read_crew_assignment(world["packer_assignment"]["id"])

    assert_hours(lead["billing_hours"], 2.00, "lead billing_hours")
    assert_hours(lead["applied_hours"], 3.00, "lead applied_hours")
    assert_hours(lead["overtime_hours"], 0.00, "lead overtime_hours")
    assert_money(lead["labor_cents"], labor_cents(3.00, 9500), "lead labor_cents")
    assert_hours(packer["applied_hours"], 3.00, "packer applied_hours")
    assert_money(packer["labor_cents"], labor_cents(3.00, 6800), "packer labor_cents")

    expected = labor_cents(3.00, 9500) + labor_cents(3.00, 6800)
    engagement = read_engagement(world["engagement_id"])
    assert_money(engagement["accrued_labor_cents"], expected, "accrued_labor_cents")
    assert_hours(engagement["billing_hours_total"], 6.00, "billing_hours_total")

    lines, meta = validate_paginated(
        api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": world["invoice"]["id"]})
    )
    assert meta["total_count"] == 1
    assert lines[0]["line_type"] == "HOURLY_LABOR"
    assert_money(lines[0]["amount_cents"], expected, "HOURLY_LABOR amount_cents")


def test_the_package_pipeline_keeps_the_same_two_hours_at_their_face_value():
    """PRD §3.11: "Under `PACKAGE` the fixed tier price was already billed at
    engagement creation, and only the hours beyond the tier's allowance are billed, at
    a different rate and with no minimum call-out floor: the allowance is 18 hours for
    `STUDIO`, 26 for `ONE_BED`, 40 for `TWO_BED` and 64 for `HOUSE`, the overage is
    the engagement's `billing_hours_total` less that allowance, floored at zero, and
    the charge is that overage multiplied by 8900 cents per hour and rounded half-up
    to whole cents."

    Design: Corner/calculations/package_pipeline_has_no_minimum_call_out_floor_on_the_same_two_hours
    """
    world = _two_hour_move_day("PACKAGE", package_tier="STUDIO")
    lead = read_crew_assignment(world["lead_assignment"]["id"])
    packer = read_crew_assignment(world["packer_assignment"]["id"])

    assert_hours(lead["applied_hours"], 2.00, "lead applied_hours")
    assert_money(lead["labor_cents"], labor_cents(2.00, 9500), "lead labor_cents")
    assert_hours(packer["applied_hours"], 2.00, "packer applied_hours")
    assert_money(packer["labor_cents"], labor_cents(2.00, 6800), "packer labor_cents")

    engagement = read_engagement(world["engagement_id"])
    assert_money(
        engagement["accrued_labor_cents"],
        labor_cents(2.00, 9500) + labor_cents(2.00, 6800),
        "accrued_labor_cents",
    )
    assert_hours(engagement["billing_hours_total"], 4.00, "billing_hours_total")

    lines, meta = validate_paginated(
        api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": world["invoice"]["id"]})
    )
    assert meta["total_count"] == 1
    assert lines[0]["line_type"] == "PACKAGE_BASE"
    assert_money(lines[0]["amount_cents"], PACKAGE_BASE_CENTS["STUDIO"], "PACKAGE_BASE amount_cents")
    assert_no_line_of_type(lines, "HOURLY_LABOR")
    assert_no_line_of_type(lines, "OVERAGE_LABOR")


def _hourly_move_day_finishing_at(out_instant):
    return setup_completed_move_day(
        keep_items=[],
        other_items=[dict(DONATE_SPEC)],
        lead_in=MOVE_START,
        packer_in=MOVE_START,
        packer_out=out_instant,
        lead_out=out_instant,
        complete_at=out_instant,
        actual_loaded_volume_cft=5,
    )


def test_exactly_eight_applied_hours_yields_no_overtime_at_all():
    """PRD §3.7: "Then `overtime_hours` is whatever part of `applied_hours` exceeds
    eight hours, and zero when it does not; the boundary is strict, so `applied_hours`
    of exactly 8.00 yields `overtime_hours` of 0.00. The remainder is the regular
    portion."

    Design: Corner/calculations/overtime_split_at_exactly_eight_applied_hours_yields_zero_overtime
    """
    world = _hourly_move_day_finishing_at("2026-06-15T22:00:00.000Z")
    lead = read_crew_assignment(world["lead_assignment"]["id"])
    packer = read_crew_assignment(world["packer_assignment"]["id"])

    assert_hours(lead["billing_hours"], 8.00, "lead billing_hours")
    assert_hours(lead["applied_hours"], 8.00, "lead applied_hours")
    assert_hours(lead["overtime_hours"], 0.00, "lead overtime_hours")
    assert_money(lead["labor_cents"], labor_cents(8.00, 9500), "lead labor_cents")
    assert_hours(packer["overtime_hours"], 0.00, "packer overtime_hours")
    assert_money(packer["labor_cents"], labor_cents(8.00, 6800), "packer labor_cents")

    expected = labor_cents(8.00, 9500) + labor_cents(8.00, 6800)
    engagement = read_engagement(world["engagement_id"])
    assert_money(engagement["accrued_labor_cents"], expected, "accrued_labor_cents")
    assert_hours(engagement["billing_hours_total"], 16.00, "billing_hours_total")
    assert_exactly_one_line(invoice_lines(world["invoice"]["id"]), "HOURLY_LABOR", expected)


def test_one_quarter_hour_past_eight_bills_a_separately_rounded_multiplier():
    """PRD §3.7: "Finally `labor_cents` is the regular hours multiplied by the crew
    member's `hourly_rate_cents` and rounded half-up to whole cents, plus the overtime
    hours multiplied by that same rate and by an overtime multiplier of 1.5 and
    rounded half-up to whole cents. The two components are rounded separately and then
    added; they are never summed as fractional amounts and rounded once."

    Design: Corner/calculations/overtime_split_one_quarter_hour_above_eight_bills_the_multiplier
    """
    world = _hourly_move_day_finishing_at("2026-06-15T22:15:00.000Z")
    lead = read_crew_assignment(world["lead_assignment"]["id"])
    packer = read_crew_assignment(world["packer_assignment"]["id"])

    assert_hours(lead["billing_hours"], 8.25, "lead billing_hours")
    assert_hours(lead["applied_hours"], 8.25, "lead applied_hours")
    assert_hours(lead["overtime_hours"], 0.25, "lead overtime_hours")
    assert_money(lead["labor_cents"], labor_cents(8.25, 9500), "lead labor_cents")
    assert_hours(packer["overtime_hours"], 0.25, "packer overtime_hours")
    assert_money(packer["labor_cents"], labor_cents(8.25, 6800), "packer labor_cents")

    expected = labor_cents(8.25, 9500) + labor_cents(8.25, 6800)
    engagement = read_engagement(world["engagement_id"])
    assert_money(engagement["accrued_labor_cents"], expected, "accrued_labor_cents")
    assert_hours(engagement["billing_hours_total"], 16.50, "billing_hours_total")
    assert_exactly_one_line(invoice_lines(world["invoice"]["id"]), "HOURLY_LABOR", expected)


BIG_KEEP_ITEMS = [
    {"label": "Crated library", "footprint_linear_inches": 90, "volume_cft": 600},
    {"label": "Crated studio", "footprint_linear_inches": 90, "volume_cft": 600},
]
BIG_ROOM = {"nominal_linear_inches": 240, "nominal_volume_cft": 2000}


def test_the_planned_trip_count_reads_only_the_keep_volume():
    """PRD §3.7: "The planned variant, stored in `planned_trip_count`, is computed
    when the plan reaches `CREWED` and again at `CONFIRMED`, and uses the engagement's
    `keep_volume_cft`, that is only the items designated `KEEP`."
    PRD §3.7: "`actual_trip_count` is null until completion."

    Design: Corner/calculations/truck_trip_count_planned_variant_counts_only_the_keep_volume
    """
    world = setup_engagement(with_residence=True, room_kwargs=BIG_ROOM)
    eng_id = world["engagement_id"]
    for spec in BIG_KEEP_ITEMS:
        item = new_item(eng_id, **spec)
        designate(item["id"], "KEEP", world["room"]["id"])
    drive_sort_plan_to_approved(eng_id, world["client_party"]["id"])

    plan = new_move_day_plan(eng_id)
    roster = staff_lead_and_packer(plan["id"])
    confirm_assignment(roster["lead_assignment"]["id"])
    confirm_assignment(roster["packer_assignment"]["id"])

    crewed = read_move_day_plan(plan["id"])
    assert crewed["status"] == "CREWED"
    assert crewed["crew_confirmed_count"] == 2
    assert crewed["crew_min_required"] == 2
    assert_two_dp(read_engagement(eng_id)["keep_volume_cft"], 1200.00, "keep_volume_cft")
    assert crewed["planned_trip_count"] == trip_count(1200, 1000, 1)
    assert crewed["actual_trip_count"] is None


def test_the_actual_trip_count_reads_the_crew_reported_loaded_volume():
    """PRD §3.7: "The actual variant, stored in `actual_trip_count`, is computed at
    completion and uses `actual_loaded_volume_cft`, which includes packing-material
    displacement and therefore usually exceeds the keep volume."
    PRD §3.7: "The combined capacity is `truck_capacity_cft` multiplied by
    `truck_count`. The number of full trips is the volume divided by that combined
    capacity, taken as a whole number rounded down."

    Design: Corner/calculations/truck_trip_count_actual_variant_counts_the_loaded_volume
    """
    world = setup_completed_move_day(
        room_kwargs=BIG_ROOM,
        keep_items=[dict(spec) for spec in BIG_KEEP_ITEMS],
        lead_in=MOVE_START,
        packer_in=MOVE_START,
        packer_out="2026-06-15T16:00:00.000Z",
        lead_out="2026-06-15T16:00:00.000Z",
        complete_at="2026-06-15T16:00:00.000Z",
        actual_loaded_volume_cft=2600,
    )
    plan = read_move_day_plan(world["plan"]["id"])
    assert plan["status"] == "COMPLETED"
    assert_two_dp(plan["actual_loaded_volume_cft"], 2600.00, "actual_loaded_volume_cft")
    assert plan["actual_trip_count"] == trip_count(2600, 1000, 1)
    assert plan["planned_trip_count"] == trip_count(1200, 1000, 1)
    engagement = read_engagement(world["engagement_id"])
    assert_two_dp(engagement["keep_volume_cft"], 1200.00, "keep_volume_cft")
    assert engagement["phase"] == "SETTLE_IN"


def test_one_cent_above_the_band_two_ceiling_uses_the_band_three_rate():
    """PRD §3.8: "The commission is a banded **average** rate applied to the whole
    gross, not a marginal one: a gross of at most 50000 cents pays fifty percent, a
    gross above that but at most 250000 cents pays forty percent, and anything above
    250000 pays thirty percent — so a lot selling for exactly 50000 pays half, while
    one selling for 50001 pays forty percent of the whole."

    Design: Corner/calculations/consignment_commission_one_cent_above_the_band_two_edge_uses_the_band_three_rate
    """
    world = setup_engagement(with_client_party=False)
    eng_id = world["engagement_id"]
    vendor = new_vendor("Harbour Consignment", "CONSIGNMENT", "2026-12-31")
    ids = []
    for label in ("Estate necklace", "Estate bracelet"):
        item = new_item(
            eng_id,
            label=label,
            category="JEWELRY",
            footprint_linear_inches=4,
            volume_cft=1,
            appraised_value_cents=150000,
            appraisal_source="APPRAISED",
        )
        designate(item["id"], "SELL")
        ids.append(item["id"])
    lot = new_consignment_lot(eng_id, vendor["id"], 300000, "2026-05-02", ids)
    set_clock("2026-05-03T09:00:00.000Z")

    validate_success(
        api_client.record_lot_sale(
            lot["id"], {"gross_sale_price_cents": 250001, "sold_on": "2026-05-03"}, MOVE_MANAGER
        )
    )
    stored = read_lot(lot["id"])
    assert stored["status"] == "SOLD"
    assert_money(stored["commission_cents"], commission_cents(250001), "commission_cents")
    assert_money(stored["fees_cents"], consignment_fees_cents(2), "fees_cents")
    assert_money(stored["net_proceeds_cents"], net_proceeds_cents(250001, 2), "net_proceeds_cents")
    assert stored["item_count"] == 2
    assert_money(stored["current_price_cents"], 300000, "current_price_cents")
    assert stored["markdown_round"] == 0
    assert stored["credited"] is False
    assert stored["reversed"] is False


def test_landing_exactly_on_the_tier_allowance_writes_no_overage_line():
    """PRD §3.11: "The boundary is strict in an unusual way: a `billing_hours_total`
    exactly equal to the allowance produces **no** `OVERAGE_LABOR` line at all, not a
    line of amount zero, and an `OVERAGE_LABOR` line is appended only when the
    computed overage charge is greater than zero."

    Design: Corner/calculations/package_overage_at_exactly_the_tier_allowance_writes_no_line
    """
    world = setup_completed_move_day(
        billing_mode="PACKAGE",
        package_tier="STUDIO",
        keep_items=[],
        other_items=[dict(DONATE_SPEC)],
        lead_in=MOVE_START,
        packer_in=MOVE_START,
        packer_out="2026-06-15T23:00:00.000Z",
        lead_out="2026-06-15T23:00:00.000Z",
        complete_at="2026-06-15T23:00:00.000Z",
        actual_loaded_volume_cft=5,
    )
    lead = read_crew_assignment(world["lead_assignment"]["id"])
    packer = read_crew_assignment(world["packer_assignment"]["id"])
    assert_hours(lead["applied_hours"], 9.00, "lead applied_hours")
    assert_hours(lead["overtime_hours"], 1.00, "lead overtime_hours")
    assert_money(lead["labor_cents"], labor_cents(9.00, 9500), "lead labor_cents")
    assert_hours(packer["applied_hours"], 9.00, "packer applied_hours")
    assert_money(packer["labor_cents"], labor_cents(9.00, 6800), "packer labor_cents")

    engagement = read_engagement(world["engagement_id"])
    assert_hours(engagement["billing_hours_total"], 18.00, "billing_hours_total")
    assert_money(
        engagement["accrued_labor_cents"],
        labor_cents(9.00, 9500) + labor_cents(9.00, 6800),
        "accrued_labor_cents",
    )
    assert package_overage_cents(18.00, "STUDIO") == 0

    lines, meta = validate_paginated(
        api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": world["invoice"]["id"]})
    )
    assert meta["total_count"] == 1
    assert lines[0]["line_type"] == "PACKAGE_BASE"
    assert_money(lines[0]["amount_cents"], PACKAGE_BASE_CENTS["STUDIO"], "PACKAGE_BASE amount_cents")
    assert_no_line_of_type(lines, "OVERAGE_LABOR")
    assert_money(
        read_invoice(world["invoice"]["id"])["subtotal_cents"],
        PACKAGE_BASE_CENTS["STUDIO"],
        "subtotal_cents",
    )
