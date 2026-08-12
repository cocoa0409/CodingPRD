"""Paired calculation variants: crew hours, room capacity and the billing fork."""

from test_helpers import (
    BILLING_ADMIN,
    MOVE_MANAGER,
    MOVE_START,
    PACKER_CHECK_IN,
    api_client,
    approve_sort_plan,
    assert_exactly_one_line,
    assert_hours,
    assert_money,
    assert_no_line_of_type,
    assert_two_dp,
    check_in,
    check_out,
    coordination_fee_cents,
    designate,
    drive_sort_plan_to_approved,
    freeze_and_start,
    get_success_data,
    invoice_lines,
    invoice_of,
    labor_cents,
    long_carry_surcharge_cents,
    new_crew_member,
    new_item,
    new_move_day_plan,
    new_time_entry,
    package_overage_cents,
    read_crew_assignment,
    read_engagement,
    read_invoice,
    read_move_day_plan,
    read_residence,
    read_room,
    room_effective_capacity,
    setup_completed_move_day,
    setup_engagement,
    setup_move_day_plan_confirmed,
    stairs_surcharge_cents,
    staff_lead_and_packer,
    travel_surcharge_cents,
    validate_success,
    PACKAGE_BASE_CENTS,
    CREW_MIN_REQUIRED,
    confirm_assignment,
)

ADDENDUM_ROOM = {"approved_addendum_linear_inches": 36}
TWO_KEEP_ITEMS = [
    {"label": "Walnut sideboard", "footprint_linear_inches": 96, "volume_cft": 40},
    {"label": "Reading chair", "footprint_linear_inches": 90, "volume_cft": 35},
]


def _packer_with_two_travel_entries():
    """A PACKER checked in at 14:00Z carrying two TRAVEL entries of exactly 1.1 h."""
    world = setup_move_day_plan_confirmed(
        room_kwargs=ADDENDUM_ROOM, keep_items=list(TWO_KEEP_ITEMS)
    )
    freeze_and_start(world)
    packer = world["packer_assignment"]["id"]
    check_in(packer, MOVE_START)
    new_time_entry(packer, "TRAVEL", "2026-06-15T12:00:00.000Z", "2026-06-15T13:06:00.000Z")
    new_time_entry(packer, "TRAVEL", "2026-06-15T20:00:00.000Z", "2026-06-15T21:06:00.000Z")
    return world


def test_portal_hours_round_each_entry_while_billing_hours_round_the_sum():
    """PRD §3.7: "The portal view, stored as `portal_hours` and shown to the family,
    rounds each entry to the quarter hour first and then sums the rounded parts,
    with the total rounded half-up to two decimal places. The billing view, stored
    as `billing_hours` and used for every monetary computation, sums the raw hours
    first and then rounds that single total to the quarter hour."
    PRD §3.7: "Both draw on the same eligible set: the assignment's entries whose
    `voided` is false and whose `entry_kind` is `LABOR` or `TRAVEL`; break entries
    are computed the same way as any other but are excluded from both representations."

    Design: Difficulty/dual_variant_calc/crew_hours_portal_vs_billing_rounding_order
    """
    world = _packer_with_two_travel_entries()
    packer = world["packer_assignment"]["id"]

    validate_success(
        api_client.check_out_crew_assignment(packer, {"at_utc": "2026-06-15T20:00:00.000Z"}, MOVE_MANAGER)
    )
    assignment = read_crew_assignment(packer)

    # Two 1.1 h TRAVEL entries plus the 6.00 h LABOR entry the check-out creates.
    assert_hours(assignment["portal_hours"], 8.00, "portal_hours")
    assert_hours(assignment["billing_hours"], 8.25, "billing_hours")
    assert assignment["portal_hours"] != assignment["billing_hours"], (
        "the two representations must diverge when per-entry rounding residues accumulate"
    )


def test_billing_view_divergence_carries_the_assignment_into_overtime():
    """PRD §3.7: "Then `overtime_hours` is whatever part of `applied_hours` exceeds
    eight hours, and zero when it does not; the boundary is strict, so
    `applied_hours` of exactly 8.00 yields `overtime_hours` of 0.00."
    PRD §3.7: "Finally `labor_cents` is the regular hours multiplied by the crew
    member's `hourly_rate_cents` and rounded half-up to whole cents, plus the
    overtime hours multiplied by that same rate and by an overtime multiplier of
    1.5 and rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/crew_hours_portal_vs_billing_rounding_order
    """
    world = _packer_with_two_travel_entries()
    packer = world["packer_assignment"]["id"]

    validate_success(
        api_client.check_out_crew_assignment(packer, {"at_utc": "2026-06-15T20:00:00.000Z"}, MOVE_MANAGER)
    )
    assignment = read_crew_assignment(packer)

    assert_hours(assignment["applied_hours"], 8.25, "applied_hours")
    assert_hours(assignment["overtime_hours"], 0.25, "overtime_hours")
    assert_money(assignment["labor_cents"], labor_cents(8.25, 6800), "labor_cents")
    assert assignment["status"] == "COMPLETED", (
        "clocking out recomputes the engagement rollups, which take only COMPLETED "
        f"assignments; got {assignment['status']}"
    )


def _residence_proposed_with_two_keep_items():
    """A PROPOSED placement whose LIVING room carries 186.00 inches of KEEP load."""
    world = setup_engagement(with_residence=True, room_kwargs=ADDENDUM_ROOM)
    room_id = world["room"]["id"]
    for spec in TWO_KEEP_ITEMS:
        item = new_item(world["engagement_id"], **spec)
        designate(item["id"], "KEEP", room_id)
    get_success_data(api_client.propose_placement(world["residence"]["id"], MOVE_MANAGER))
    return world


def test_room_capacity_uses_the_provisional_variant_before_approval():
    """PRD §3.3: "While the parent residence is `DRAFT` or `PROPOSED`, the
    provisional variant applies: `effective_capacity_linear_inches` is the room's
    `nominal_linear_inches` multiplied by a derate of 0.80, rounded half-up to two
    decimal places, and the addendum is ignored completely."
    PRD §3.3: "`headroom_linear_inches` is the room's
    `effective_capacity_linear_inches` less its `keep_load_linear_inches`."

    Design: Difficulty/dual_variant_calc/room_capacity_provisional_vs_approved
    """
    world = _residence_proposed_with_two_keep_items()
    room = read_room(world["room"]["id"])

    assert_two_dp(
        room["effective_capacity_linear_inches"],
        room_effective_capacity(240, 36, approved=False),
        "effective_capacity_linear_inches under the provisional variant",
    )
    assert_two_dp(room["keep_load_linear_inches"], 186.00, "keep_load_linear_inches")
    assert_two_dp(room["headroom_linear_inches"], 6.00, "headroom_linear_inches")


def test_room_capacity_switches_to_the_approved_variant_with_its_addendum():
    """PRD §3.3: "Once the parent is `APPROVED`, the approved variant applies: the
    nominal run is taken at full value — a factor of 1.00 — and the
    `approved_addendum_linear_inches` is added on top, again rounded half-up to two
    decimal places."
    PRD §3.3: "Approval stamps `approved_by_party_id` and `approved_at_utc`,
    recomputes every child room's `effective_capacity_linear_inches` under the
    approved variant, which admits the room's `approved_addendum_linear_inches`,
    and refreshes each room's `headroom_linear_inches` against its current keep load."

    Design: Difficulty/dual_variant_calc/room_capacity_provisional_vs_approved
    """
    world = _residence_proposed_with_two_keep_items()
    party_id = world["client_party"]["id"]

    validate_success(
        api_client.approve_placement(
            world["residence"]["id"], {"approved_by_party_id": party_id}, MOVE_MANAGER
        )
    )
    residence = read_residence(world["residence"]["id"])
    room = read_room(world["room"]["id"])

    assert residence["placement_status"] == "APPROVED"
    assert residence["approved_by_party_id"] == party_id
    assert_two_dp(
        room["effective_capacity_linear_inches"],
        room_effective_capacity(240, 36, approved=True),
        "effective_capacity_linear_inches under the approved variant",
    )
    assert_two_dp(room["keep_load_linear_inches"], 186.00, "keep_load_linear_inches")
    assert_two_dp(room["headroom_linear_inches"], 90.00, "headroom_linear_inches")


def _completed_move_day(billing_mode, package_tier=None):
    """Identical crew hours on either pipeline: a 9.50 h LEAD and a 9.00 h PACKER."""
    return setup_completed_move_day(
        billing_mode=billing_mode,
        package_tier=package_tier,
        lead_in=MOVE_START,
        packer_in=MOVE_START,
        packer_out="2026-06-15T23:00:00.000Z",
        lead_out="2026-06-15T23:30:00.000Z",
        complete_at="2026-06-15T23:30:00.000Z",
        actual_loaded_volume_cft=900,
    )


def test_identical_crew_hours_produce_an_hourly_labor_line_only_under_hourly():
    """PRD §3.11: "Under `HOURLY` exactly one `HOURLY_LABOR` line is appended, and
    its `amount_cents` is the engagement's `accrued_labor_cents` — crew hours times
    role rates, with the minimum call-out floor and the overtime multiplier already
    baked in by §3.7, and with no base line and no included allowance anywhere in
    the picture."

    Design: Difficulty/dual_variant_calc/billing_fork_identical_inputs_diverge_across_the_two_pipelines
    """
    world = _completed_move_day("HOURLY")
    engagement = read_engagement(world["engagement_id"])
    expected_labour = labor_cents(9.50, 9500) + labor_cents(9.00, 6800)

    assert_money(engagement["accrued_labor_cents"], expected_labour, "accrued_labor_cents")
    assert_hours(engagement["billing_hours_total"], 18.50, "billing_hours_total")

    lines = invoice_lines(world["invoice"]["id"])
    assert_exactly_one_line(lines, "HOURLY_LABOR", expected_labour)
    assert_no_line_of_type(lines, "PACKAGE_BASE")
    assert_no_line_of_type(lines, "OVERAGE_LABOR")


def test_identical_crew_hours_produce_base_plus_overage_lines_under_package():
    """PRD §3.11: "Under `PACKAGE` the fixed tier price was already billed at
    engagement creation, and only the hours beyond the tier's allowance are billed,
    at a different rate and with no minimum call-out floor: the allowance is 18
    hours for `STUDIO`, 26 for `ONE_BED`, 40 for `TWO_BED` and 64 for `HOUSE`, the
    overage is the engagement's `billing_hours_total` less that allowance, floored
    at zero, and the charge is that overage multiplied by 8900 cents per hour and
    rounded half-up to whole cents."
    PRD §3.11: "Two aggregates partition the ledger. `subtotal_cents` sums
    `amount_cents` over every line whose `line_type` is **not** `COORDINATION_FEE`,
    `CONSIGNMENT_CREDIT` or `CONSIGNMENT_REVERSAL`."

    Design: Difficulty/dual_variant_calc/billing_fork_identical_inputs_diverge_across_the_two_pipelines
    """
    world = _completed_move_day("PACKAGE", package_tier="STUDIO")
    engagement = read_engagement(world["engagement_id"])
    expected_labour = labor_cents(9.50, 9500) + labor_cents(9.00, 6800)

    # The same crew hours accrue on both pipelines; only the ledger differs.
    assert_money(engagement["accrued_labor_cents"], expected_labour, "accrued_labor_cents")
    assert_hours(engagement["billing_hours_total"], 18.50, "billing_hours_total")

    lines = invoice_lines(world["invoice"]["id"])
    assert_exactly_one_line(lines, "PACKAGE_BASE", PACKAGE_BASE_CENTS["STUDIO"])
    assert_exactly_one_line(
        lines, "OVERAGE_LABOR", package_overage_cents(18.50, "STUDIO")
    )
    assert_no_line_of_type(lines, "HOURLY_LABOR")

    invoice = read_invoice(world["invoice"]["id"])
    assert_money(
        invoice["subtotal_cents"],
        PACKAGE_BASE_CENTS["STUDIO"] + package_overage_cents(18.50, "STUDIO"),
        "subtotal_cents before issue",
    )


def _package_engagement_with_house_home_tier():
    """package_tier STUDIO but home_tier HOUSE: two maps keyed on different fields."""
    world = setup_engagement(
        billing_mode="PACKAGE",
        home_tier="HOUSE",
        package_tier="STUDIO",
        with_residence=True,
    )
    item = new_item(world["engagement_id"], label="Walnut sideboard", footprint_linear_inches=96, volume_cft=40)
    designate(item["id"], "KEEP", world["room"]["id"])
    world["sort_plan"] = drive_sort_plan_to_approved(
        world["engagement_id"], world["client_party"]["id"]
    )
    return world


def test_package_base_line_is_keyed_on_the_package_tier_not_the_home_tier():
    """PRD §3.1: "Under the package pipeline a `PACKAGE_BASE` ledger line is
    appended immediately, priced from the package tier alone: 185000 cents for
    `STUDIO`, 265000 for `ONE_BED`, 395000 for `TWO_BED` and 620000 for `HOUSE`."
    PRD §3.1: "Both `home_tier` and `package_tier` are drawn from `STUDIO`,
    `ONE_BED`, `TWO_BED` and `HOUSE`, but they are independent choices: the home
    tier describes the house being emptied and drives crew minimums and the volume
    heuristic, while the package tier is the product the family bought."

    Design: Difficulty/dual_variant_calc/package_base_keys_on_package_tier_while_crew_minimum_keys_on_home_tier
    """
    world = _package_engagement_with_house_home_tier()
    engagement = read_engagement(world["engagement_id"])
    assert engagement["home_tier"] == "HOUSE"
    assert engagement["package_tier"] == "STUDIO"

    invoice = invoice_of(world["engagement_id"])
    lines = invoice_lines(invoice["id"])
    assert_exactly_one_line(lines, "PACKAGE_BASE", PACKAGE_BASE_CENTS["STUDIO"])
    assert_money(
        read_invoice(invoice["id"])["subtotal_cents"],
        PACKAGE_BASE_CENTS["STUDIO"],
        "subtotal_cents",
    )


def test_crew_minimum_is_keyed_on_the_home_tier_so_two_confirms_leave_the_plan_draft():
    """PRD §3.7: "`crew_min_required` is read from the engagement's `home_tier` and
    never from its `package_tier`: two crew for a `STUDIO`, three for `ONE_BED`,
    four for `TWO_BED` and six for a `HOUSE`."
    PRD §3.7: "It recomputes the plan's `crew_confirmed_count` — the number of the
    plan's assignments in status `CONFIRMED`, `CHECKED_IN` or `COMPLETED` — and then
    bubbles upward: when that count has reached `crew_min_required` and at least one
    of the confirmed assignments belongs to a crew member whose `crew_role` is
    `LEAD`, the plan itself transitions from `DRAFT` to `CREWED`, which recomputes
    `planned_trip_count` from the engagement's `keep_volume_cft`."

    Design: Difficulty/dual_variant_calc/package_base_keys_on_package_tier_while_crew_minimum_keys_on_home_tier
    """
    world = _package_engagement_with_house_home_tier()
    plan = new_move_day_plan(world["engagement_id"])
    roster = staff_lead_and_packer(plan["id"])
    confirm_assignment(roster["lead_assignment"]["id"])
    confirm_assignment(roster["packer_assignment"]["id"])

    plan = read_move_day_plan(plan["id"])
    assert plan["crew_min_required"] == CREW_MIN_REQUIRED["HOUSE"], (
        "crew_min_required must follow home_tier HOUSE, not package_tier STUDIO"
    )
    assert plan["crew_confirmed_count"] == 2
    assert plan["status"] == "DRAFT", (
        "two confirmed crew are below the HOUSE minimum of six, so the plan stays DRAFT"
    )
    assert read_crew_assignment(roster["lead_assignment"]["id"])["status"] == "CONFIRMED"
    assert read_crew_assignment(roster["packer_assignment"]["id"])["status"] == "CONFIRMED"
