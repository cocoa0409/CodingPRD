"""Removal deadlines, the late-removal penalty and the two placement dimensions."""

from test_helpers import (
    ApiErrorId,
    charge_action,
    create_listing,
    intake_lockbox,
    only_charge,
    place_lockbox,
    placement_payload,
    read_lockbox,
    read_member,
    read_placement,
    remove_placement,
    run_checkpoint,
    setup_delinquent_placement,
    setup_placed_box,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    assign_lockbox,
    close_listing,
    list_charges,
    make_member_headers,
    set_clock,
    setup_association_with_agent,
)


def test_placement_removal_leaves_the_accrued_penalty_standing(api, admin_headers):
    """PRD §3.4: "Removing from `DELINQUENT` is never on time, lowers
    `delinquent_placement_count` by one, and leaves `billing_status` at `ACCRUED`: the
    penalty stands."
    PRD §3.4: "Removal writes `removed_at` at the current logical clock and drives the box
    `PLACED → ASSIGNED` with `current_listing_id` cleared, returning one unit to
    `unplaced_inventory_count` and lowering `active_placement_count` by one;
    `delinquent_placement_count`, `recovery_rate_pct` and `posture` are all recomputed."

    Design: Difficulty/non_linear_state_machine/placement_removal_and_billing_dimensions_evolve_independently
    """
    ctx = setup_delinquent_placement(
        serial="LB-0001", model="LB_STD", replacement_cost_cents=9000
    )
    remove_placement(ctx["placement_id"], ctx["agent_id"])

    placement = read_placement(ctx["placement_id"])
    assert placement["placement_status"] == "REMOVED"
    assert placement["billing_status"] == "ACCRUED"
    assert placement["on_time"] is False

    lockbox = read_lockbox(ctx["lockbox_id"])
    assert lockbox["status"] == "ASSIGNED"
    assert lockbox.get("current_listing_id") is None


def test_paying_the_late_charge_settles_billing_without_moving_the_placement(api, admin_headers):
    """PRD §3.4: "Later, when an administrator pays or waives that charge, the placement's
    `billing_status` moves `ACCRUED → SETTLED` without touching `placement_status`; when an
    administrator voids it, `billing_status` returns `ACCRUED → NONE` and the member's
    balance is recomputed."
    PRD §2.7: "Only charges in `PENDING` or `INVOICED` are in the open set; `PAID`, `WAIVED`
    and `VOID` lines leave the open set immediately and stop contributing."

    Design: Difficulty/non_linear_state_machine/placement_removal_and_billing_dimensions_evolve_independently
    """
    ctx = setup_delinquent_placement(
        serial="LB-0001", model="LB_STD", replacement_cost_cents=9000
    )
    remove_placement(ctx["placement_id"], ctx["agent_id"])

    charge = only_charge(charge_type="LATE_REMOVAL", placement_id=ctx["placement_id"])
    paid = charge_action(charge["id"], "PAY")

    assert paid["status"] == "PAID"
    assert paid["amount_cents"] == 1500

    placement = read_placement(ctx["placement_id"])
    assert placement["placement_status"] == "REMOVED"
    assert placement["billing_status"] == "SETTLED"

    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 0


def _two_late_placements(api):
    """Two boxes, two listings, both closed on 2026-08-10, clock moved one day past the
    shared removal deadline of 2026-08-13T00:00:00.000Z."""
    ctx = setup_association_with_agent()
    placements = []
    for index, (serial, mls, address) in enumerate(
        [("LB-0001", "MLS-1001", "12 Pine St"), ("LB-0002", "MLS-1002", "34 Cedar Ave")]
    ):
        box = intake_lockbox(
            ctx["association_id"],
            serial_number=serial,
            model="LB_STD",
            replacement_cost_cents=9000,
        )
        assign_lockbox(box["id"], ctx["agent_id"])
        listing = create_listing(
            ctx["association_id"], ctx["agent_id"], mls_number=mls, address_line=address
        )
        placements.append(
            (place_lockbox(box["id"], listing["id"], ctx["agent_id"]), listing)
        )
    set_clock("2026-08-10T00:00:00Z")
    for _, listing in placements:
        close_listing(listing["id"], ctx["agent_id"], "2026-08-10")
    set_clock("2026-08-14T00:00:00Z")
    ctx["placements"] = [placement for placement, _ in placements]
    return ctx


def test_two_late_placements_each_accrue_their_own_tier_one_charge(api, admin_headers):
    """PRD §3.4: "The base component is the number of late days multiplied by the
    association's `late_removal_daily_fee_cents`, capped at the association's
    `late_removal_cap_cents` — whichever is smaller."
    PRD §3.4: "The administration fee percentage attached to those tiers is zero percent for
    `T1`, five percent for `T2` and ten percent for `T3`."
    PRD §3.4: "The derivation is recorded in the charge's `basis` as a string of the form
    `base=7500 tier=T2 admin_fee=375`."

    Design: Difficulty/combinatorial_formula/member_balance_per_line_surcharge_rounding_mode_b
    """
    ctx = _two_late_placements(api)

    report = run_checkpoint(ctx["association_id"])
    assert report["delinquent_placement_count"] == 2
    assert report["accrued_charge_count"] == 2

    charges = list_charges(charge_type="LATE_REMOVAL", member_id=ctx["agent_id"])
    assert len(charges) == 2
    for charge in charges:
        assert charge["amount_cents"] == 1500
        assert charge["basis"] == "base=1500 tier=T1 admin_fee=0"

    for placement in ctx["placements"]:
        stored = read_placement(placement["id"])
        assert stored["billing_status"] == "ACCRUED"
        assert stored["late_days"] == 1


def test_member_balance_rounds_each_open_line_before_summing(api, admin_headers):
    """PRD §2.7: "Each open line is grossed up by an administration surcharge of 2.5 percent
    of its `amount_cents`, and **the rounding order is pinned: the grossed-up figure is
    rounded half up to a whole cent for each line individually, and only then are the rounded
    line totals added together.**"
    PRD §2.7: "Summing the raw grossed-up amounts and rounding once at the end is explicitly
    the wrong reading — two open lines of 1500 cents each yield 3076 under the rule as
    written and 3075 under the wrong one."

    Design: Difficulty/combinatorial_formula/member_balance_per_line_surcharge_rounding_mode_b
    """
    ctx = _two_late_placements(api)
    run_checkpoint(ctx["association_id"])

    member = read_member(ctx["agent_id"])
    assert member["outstanding_balance_cents"] == 3076
    assert member["outstanding_balance_cents"] != 3075, (
        "3075 is the sum-then-round reading the PRD rules out"
    )


def test_late_removal_tier_is_keyed_on_the_base_component_alone(api, admin_headers):
    """PRD §3.4: "A tier is then selected **from the base component alone**: base amounts of
    4500 cents or less are tier `T1`, base amounts above 4500 cents and up to 10500 cents are
    tier `T2`, and base amounts above 10500 cents are tier `T3`."
    PRD §3.4: "The administration fee in cents is the base component multiplied by that
    percentage, rounded half up to a whole cent. The charge total is the base component plus
    the administration fee. Keying the tier on the total rather than on the base is the wrong
    reading and produces different money."

    Design: Difficulty/combinatorial_formula/late_removal_tier_keyed_on_base_not_total_mode_c
    """
    ctx = setup_delinquent_placement(
        serial="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
        run_clock="2026-08-20T00:00:00Z",
    )

    charge = only_charge(charge_type="LATE_REMOVAL", placement_id=ctx["placement_id"])
    assert charge["amount_cents"] == 11025
    assert charge["basis"] == "base=10500 tier=T2 admin_fee=525"
    assert charge["amount_cents"] != 11550, (
        "11550 is the tier-from-total reading the PRD rules out"
    )


def test_late_removal_freezes_late_days_and_recomputes_the_balance(api, admin_headers):
    """PRD §3.4: "The count of late days is the elapsed time from `removal_deadline` to the
    current logical clock expressed in days with any partial day rounded **up** to a whole
    day, floored at zero; that count is stored in `late_days`."
    PRD §3.4: "Alongside the delinquency the checkpoint moves the placement's
    `billing_status` from `NONE` to `ACCRUED` and writes a charge of `charge_type`
    `LATE_REMOVAL`, linked by `placement_id`, `lockbox_id` and the `member_id` taken from
    `placed_by_member_id`, in `PENDING`; the member's `outstanding_balance_cents` is
    recomputed."

    Design: Difficulty/combinatorial_formula/late_removal_tier_keyed_on_base_not_total_mode_c
    """
    ctx = setup_delinquent_placement(
        serial="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
        run_clock="2026-08-20T00:00:00Z",
    )

    placement = read_placement(ctx["placement_id"])
    assert placement["late_days"] == 7
    assert placement["placement_status"] == "DELINQUENT"
    assert placement["billing_status"] == "ACCRUED"

    charge = only_charge(charge_type="LATE_REMOVAL", placement_id=ctx["placement_id"])
    assert charge["status"] == "PENDING"
    assert charge["lockbox_id"] == ctx["lockbox_id"]
    assert charge["member_id"] == ctx["agent_id"]

    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 11301


def test_late_removal_penalty_saturates_at_the_cap_and_enters_tier_three(api, admin_headers):
    """PRD §3.4: "The base component is the number of late days multiplied by the
    association's `late_removal_daily_fee_cents`, capped at the association's
    `late_removal_cap_cents` — whichever is smaller."
    PRD §3.4: "A tier is then selected **from the base component alone**: base amounts of
    4500 cents or less are tier `T1`, base amounts above 4500 cents and up to 10500 cents are
    tier `T2`, and base amounts above 10500 cents are tier `T3`."

    Design: Corner/calculations/late_removal_penalty_saturates_at_cap_and_enters_tier_three
    """
    ctx = setup_delinquent_placement(
        serial="LB-0001",
        model="LB_STD",
        replacement_cost_cents=9000,
        run_clock="2026-09-02T00:00:00Z",
    )

    placement = read_placement(ctx["placement_id"])
    assert placement["late_days"] == 20
    assert placement["placement_status"] == "DELINQUENT"

    charge = only_charge(placement_id=ctx["placement_id"])
    assert charge["charge_type"] == "LATE_REMOVAL"
    assert charge["amount_cents"] == 16500
    assert charge["basis"] == "base=15000 tier=T3 admin_fee=1500"

    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 16913


def test_second_compliance_run_does_not_double_charge_a_delinquent_placement(api, admin_headers):
    """PRD §3.4: "Once frozen, `late_days` does not drift with the clock, and a placement
    already `DELINQUENT` is skipped by later checkpoints."
    PRD §3.9: "**Accrue delinquencies.** Every placement in `REMOVAL_DUE` whose
    `removal_deadline` is strictly before the current logical clock moves to `DELINQUENT`,
    freezing `late_days`, moving `billing_status` from `NONE` to `ACCRUED`, and raising the
    `LATE_REMOVAL` charge described in §3.4."

    Design: Corner/cross_cutting_complexity_layers/second_compliance_run_does_not_double_charge_a_delinquent_placement
    """
    ctx = setup_delinquent_placement(
        serial="LB-0001", model="LB_STD", replacement_cost_cents=9000
    )

    second_run = run_checkpoint(ctx["association_id"])
    assert second_run["accrued_charge_count"] == 0

    charges = list_charges(placement_id=ctx["placement_id"])
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 1500

    placement = read_placement(ctx["placement_id"])
    assert placement["late_days"] == 1
    assert placement["placement_status"] == "DELINQUENT"
    assert placement["billing_status"] == "ACCRUED"

    assert read_member(ctx["agent_id"])["outstanding_balance_cents"] == 1538


def test_second_placement_on_an_already_placed_lockbox_conflicts(api, admin_headers):
    """PRD §3.4: "A box that already carries a placement in `PLACED`, `REMOVAL_DUE` or
    `DELINQUENT` is rejected with `ERR_PLACEMENT_ALREADY_ACTIVE`."
    PRD §2.6: "First, when a placement is being created the *addressed* entity for the
    transition check at step 9 is the lockbox, not the listing: a unit sitting in `IN_STOCK`,
    `MISSING`, `QUARANTINE` or `RETIRED` fails there with `ERR_INVALID_STATE`, whereas a unit
    that is already `PLACED` passes step 9 and is instead caught later at step 16 with
    `ERR_PLACEMENT_ALREADY_ACTIVE`."

    Design: Corner/validations/second_placement_on_an_already_placed_lockbox_conflicts
    """
    ctx = setup_placed_box(serial="LB-0001", model="LB_STD", replacement_cost_cents=9000)
    second_listing = create_listing(
        ctx["association_id"],
        ctx["agent_id"],
        mls_number="MLS-1002",
        address_line="34 Cedar Ave",
    )

    response = api.create_placement(
        placement_payload(ctx["lockbox_id"], second_listing["id"]),
        make_member_headers(ctx["agent_id"]),
    )
    validate_error(response, ApiErrorId.ERR_PLACEMENT_ALREADY_ACTIVE.value)

    rows, _ = validate_paginated(
        api.list_placements(admin_headers, params={"lockbox_id": ctx["lockbox_id"]})
    )
    assert len(rows) == 1
    assert read_lockbox(ctx["lockbox_id"])["current_listing_id"] == ctx["listing_id"]
