"""Queue B — §1.3 calculation corners: a WAGES service charge squeezing the credit,
the pool's input-set filter, the California configuration, and the notice gate."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    PREPARER,
    api_client,
    close_shift,
    compute_period,
    create_role_assignment_payload,
    declare_shift_tips,
    distribute_pool,
    get_success_data,
    list_allocations_of,
    list_pay_lines_of,
    new_active_policy,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_pool,
    new_role_assignment,
    new_service_charge,
    new_shift,
    read_employee,
    read_location,
    read_pay_period,
    read_service_charge,
    read_shift,
    set_logical_clock,
    void_shift,
)

CLOCK = "2026-08-10T12:00:00Z"
DATE_1 = "2026-08-04T00:00:00Z"
DATE_2 = "2026-08-05T00:00:00Z"


def _line_of(pay_period_id: str, employee_id: str) -> dict:
    """The one live pay line the period holds for this employee."""
    rows = [
        row
        for row in list_pay_lines_of(pay_period_id)
        if row["employee_id"] == employee_id and row["status"] != "SUPERSEDED"
    ]
    assert len(rows) == 1, f"expected one live pay line, got {len(rows)}"
    return rows[0]


def _assignment_without_notice(employee_id: str, job_role_id: str) -> dict:
    """Grant a role with `tip_credit_notice_acknowledged_at` absent from the payload."""
    payload = create_role_assignment_payload(employee_id, job_role_id)
    del payload["tip_credit_notice_acknowledged_at"]
    return get_success_data(api_client.create_role_assignment(payload, ADMIN))


def _wages_charge_world() -> dict:
    """A Texas unit treating charges as WAGES, no ACTIVE policy: Ana's CLOSED
    480-minute SERVER shift declaring 4000 cash beside Bo's CLOSED 300-minute
    MANAGER shift declaring nothing, and one RECORDED 6001-cent charge on
    2026-08-04, with the week computed."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    role_manager = new_job_role(
        code="MANAGER",
        title="Shift Manager",
        tip_status="NON_TIPPED",
        is_management=True,
        pool_contribution_pct_bps=0,
        pool_share_points=0,
        side_work_eligible=False,
    )
    server = new_employee(location["id"])
    manager = new_employee(location["id"], full_name="Bo Nkemdi", external_payroll_ref="E2")
    new_role_assignment(server["id"], role_server["id"])
    _assignment_without_notice(manager["id"], role_manager["id"])
    pay_period = new_pay_period(location["id"])

    shift_server = new_shift(
        server["id"], location["id"], role_server["id"], pay_period["id"]
    )
    close_shift(shift_server["id"])
    declare_shift_tips(shift_server["id"], server["id"], 4000, 0)

    shift_manager = new_shift(
        manager["id"],
        location["id"],
        role_manager["id"],
        pay_period["id"],
        start_at="2026-08-04T12:00:00Z",
        end_at="2026-08-04T17:00:00Z",
    )
    close_shift(shift_manager["id"])
    declare_shift_tips(shift_manager["id"], manager["id"], 0, 0)

    charge = new_service_charge(
        location["id"], amount_cents=6001, description="Banquet 14 gratuity"
    )
    compute_period(pay_period["id"])
    return {
        "location": location,
        "server": server,
        "manager": manager,
        "shift_server": shift_server,
        "shift_manager": shift_manager,
        "charge": charge,
        "pay_period": pay_period,
    }


# ---------------------------------------------------------------------------
# calculations / service_charge_as_wages_lifts_the_regular_rate...
# ---------------------------------------------------------------------------
def test_a_wages_charge_lifts_the_regular_rate_and_leaves_only_403_of_credit(api):
    """The charge share raises the rate to 675 and eats the residual leg of the cap.

    PRD §3.6: "A `WAGES` amount is employer revenue paid out to staff as ordinary
    compensation, and it therefore enters the overtime regular rate, raising the
    overtime premium."
    PRD §3.8: "`regular_rate_cents_per_hour` is `straight_cash_cents` plus
    `service_charge_wages_cents`, divided by the number of hours worked — that is, by
    `total_minutes` divided by sixty — rounded half up."
    PRD §3.8: "The residual is `minimum_wage_obligation_cents` less
    `straight_cash_cents`, less `service_charge_wages_cents`, less
    `overtime_premium_cents`."
    PRD §3.8: "`tip_credit_cents` is then the smallest of those three figures — the
    per-hour ceiling, the tips actually available, and the residual — floored at 0 so
    it can never be negative."
    PRD §3.8: "`total_gross_cents` is `straight_cash_cents` plus
    `service_charge_wages_cents` plus `overtime_premium_cents` plus `topup_cents` plus
    `correction_applied_cents`."

    Design: Corner/calculations/service_charge_as_wages_lifts_the_regular_rate_and_squeezes_the_tip_credit
    """
    world = _wages_charge_world()

    charge = read_service_charge(world["charge"]["id"])
    assert charge["treatment"] == "WAGES", "inherited from the unit, no override supplied"
    assert charge["treatment_override"] is None
    assert charge["status"] == "ALLOCATED"
    assert charge["allocated_pay_period_id"] == world["pay_period"]["id"]
    assert charge["allocated_pool_id"] is None, "a WAGES charge never joins a pool"

    line = _line_of(world["pay_period"]["id"], world["server"]["id"])
    assert line["total_minutes"] == 480
    assert line["tip_credit_eligible_minutes"] == 480
    assert line["overtime_minutes"] == 0
    assert line["straight_cash_cents"] == 1704, "213 cents over 8 eligible hours"
    assert line["service_charge_wages_cents"] == 3693
    assert line["regular_rate_cents_per_hour"] == 675, (
        "(1704 + 3693) / 8 hours = 674.625, rounded half up — not the 213 cash wage"
    )
    assert line["minimum_wage_obligation_cents"] == 5800
    assert line["retained_tips_cents"] == 4000
    assert line["pool_tips_cents"] == 0
    assert line["tips_available_cents"] == 4000
    assert line["tipped_employee_qualified"] is True
    assert line["tip_credit_cents"] == 403, (
        "5800 - 1704 - 3693 - 0: the residual binds, not the 4096 per-hour ceiling "
        "and not the 4000 of tips available"
    )
    assert line["topup_cents"] == 0
    assert line["total_gross_cents"] == 5397
    assert line["reported_tips_cents"] == 4000


def test_the_manager_shares_the_charge_and_the_6001_cents_land_exactly(api):
    """Management is inside the wages split, and the odd cent goes to the longer shift.

    PRD §3.6: "For each such event, taken on its own: each `CLOSED` shift on that
    event's `business_date` carries a weight equal to that shift's
    `scheduled_minutes`; the total weight is the sum of those weights; each shift's
    base share is the event's `amount_cents` multiplied by that shift's weight,
    divided by the total weight, with any fraction discarded; the leftover is
    `amount_cents` less the sum of the base shares; and one extra cent goes to each of
    the first however-many shifts the leftover permits, taken in descending order of
    weight and, where two shifts carry the same weight, in ascending order of their
    employees' `created_at`."
    PRD §3.6: "Management shifts **are** included in this split, in deliberate
    contrast to the tip-pool split of §3.7: a service charge treated as wages is
    ordinary compensation and a manager may lawfully receive it."
    PRD §3.8: "`straight_cash_cents` is built from two rate bands, each rounded half
    up on its own and then added: the unit's `cash_wage_cents` applied to
    `tip_credit_eligible_minutes` converted to hours by dividing by sixty, plus the
    unit's `applicable_min_wage_cents` applied to `non_tip_credit_minutes` likewise
    converted to hours."
    PRD §3.4: "`total_credited_minutes` is the sum of `scheduled_minutes` over the
    period's shifts whose `time_status` is `CLOSED`."

    Design: Corner/calculations/service_charge_as_wages_lifts_the_regular_rate_and_squeezes_the_tip_credit
    """
    world = _wages_charge_world()

    server_line = _line_of(world["pay_period"]["id"], world["server"]["id"])
    manager_line = _line_of(world["pay_period"]["id"], world["manager"]["id"])

    assert manager_line["total_minutes"] == 300
    assert manager_line["tip_credit_eligible_minutes"] == 0
    assert manager_line["non_tip_credit_minutes"] == 300
    assert manager_line["straight_cash_cents"] == 3625, "725 cents over 5 hours"
    assert manager_line["service_charge_wages_cents"] == 2308
    assert manager_line["regular_rate_cents_per_hour"] == 1187, (
        "(3625 + 2308) / 5 hours = 1186.6, rounded half up"
    )
    assert manager_line["minimum_wage_obligation_cents"] == 3625
    assert manager_line["tipped_employee_qualified"] is False
    assert manager_line["tip_credit_cents"] == 0
    assert manager_line["topup_cents"] == 0
    assert manager_line["total_gross_cents"] == 5933
    assert manager_line["reported_tips_cents"] == 0

    assert (
        server_line["service_charge_wages_cents"]
        + manager_line["service_charge_wages_cents"]
        == 6001
    ), (
        "3693 + 2308: the floors were 3692 and 2308 and the single leftover cent went "
        "to the 480-minute shift, so the charge is neither over- nor under-distributed"
    )

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_credited_minutes"] == 780
    assert period["total_tip_credit_cents"] == 403
    assert period["total_topup_cents"] == 0
    assert period["gross_receipts_cents"] == 0, "neither shift rang any sales"
    assert period["reported_tips_cents"] == 4000


# ---------------------------------------------------------------------------
# calculations / pool_computation_includes_only_same_unit_same_date_non_voided_shifts
# ---------------------------------------------------------------------------
def test_the_pool_sweeps_in_neither_the_void_the_next_night_nor_the_other_unit(api):
    """One qualifying shift among three decoys, and the arithmetic names any intruder.

    PRD §3.7: "The shifts that feed the pool are those at the requested unit and
    `business_date` whose `time_status` is `CLOSED`, whose `declaration_status` is
    `DECLARED` or `AMENDED`, and whose `shift_tip_pool_id` is still null, and whose job
    role is not a management role and carries either a `pool_contribution_pct_bps`
    greater than 0 or a `pool_share_points` greater than 0; and additionally, where the
    pinned policy's `pool_type` is `TIPPED_ONLY`, whose job role's `tip_status` is
    `TIPPED`."
    PRD §3.7: "On the pool itself, `total_contributed_cents` becomes the sum of the
    contributions across the contributing shifts and `contributing_shift_count`
    becomes the number of those shifts whose contribution came out greater than 0 — a
    stamped-in busser with a contribution of 0 is therefore not counted there."
    PRD §3.4: "Voiding zeroes the shift's `non_tip_credit_minutes`,
    `tip_credit_eligible_minutes` and `retained_tips_cents`, then recomputes the owning
    period's `total_credited_minutes` and `gross_receipts_cents` from whichever shifts
    survive as `CLOSED`."
    PRD §3.7: "The pool's `distributed_cents` becomes the sum of the rows'
    `allocated_cents`, which must equal `net_pool_cents` exactly."

    Design: Corner/calculations/pool_computation_includes_only_same_unit_same_date_non_voided_shifts
    """
    set_logical_clock()
    dallas = new_location()
    plano = new_location(name="Plano Unit")
    role_server = new_job_role()
    ana = new_employee(dallas["id"])
    bea = new_employee(dallas["id"], full_name="Bea Olsen", external_payroll_ref="E2")
    cal = new_employee(plano["id"], full_name="Cal Ruiz", external_payroll_ref="E3")
    for employee in (ana, bea, cal):
        new_role_assignment(employee["id"], role_server["id"])
    new_active_policy(
        dallas["id"], dallas["version"], share_basis="POINTS_ONLY", cc_fee_pass_through=False
    )
    dallas_period = new_pay_period(dallas["id"])
    plano_period = new_pay_period(plano["id"])

    keep = new_shift(ana["id"], dallas["id"], role_server["id"], dallas_period["id"])
    close_shift(keep["id"])
    declare_shift_tips(keep["id"], ana["id"], 4000, 0)

    nextday = new_shift(
        ana["id"],
        dallas["id"],
        role_server["id"],
        dallas_period["id"],
        business_date=DATE_2,
        start_at="2026-08-05T16:00:00Z",
        end_at="2026-08-06T00:00:00Z",
    )
    close_shift(nextday["id"])
    declare_shift_tips(nextday["id"], ana["id"], 6000, 0)

    voided = new_shift(bea["id"], dallas["id"], role_server["id"], dallas_period["id"])
    close_shift(voided["id"])
    declare_shift_tips(voided["id"], bea["id"], 5000, 0)
    void_shift(voided["id"], reason="logged against the wrong employee")

    other_unit = new_shift(cal["id"], plano["id"], role_server["id"], plano_period["id"])
    close_shift(other_unit["id"])
    declare_shift_tips(other_unit["id"], cal["id"], 7000, 0)

    pool = new_pool(dallas["id"])
    assert pool["contributing_shift_count"] == 1
    assert pool["participant_count"] == 0, "participants are counted at distribution"
    assert pool["total_contributed_cents"] == 600, (
        "1500 bps of Ana's 4000 alone — not 900, 1350 or 1650, so none of the three "
        "decoy shifts entered the input set"
    )
    assert pool["service_charge_tips_cents"] == 0
    assert pool["cc_fee_deducted_cents"] == 0

    assert read_shift(keep["id"])["shift_tip_pool_id"] == pool["id"]
    assert read_shift(keep["id"])["pool_contribution_cents"] == 600
    assert read_shift(keep["id"])["retained_tips_cents"] == 3400

    untouched = read_shift(nextday["id"])
    assert untouched["shift_tip_pool_id"] is None, (
        "a wrong business_date is not a near miss, it is simply out"
    )
    assert untouched["pool_contribution_cents"] == 0
    assert untouched["retained_tips_cents"] == 6000

    dead = read_shift(voided["id"])
    assert dead["time_status"] == "VOIDED"
    assert dead["shift_tip_pool_id"] is None
    assert dead["retained_tips_cents"] == 0, "the void already zeroed its tip figures"

    across_town = read_shift(other_unit["id"])
    assert across_town["shift_tip_pool_id"] is None
    assert across_town["retained_tips_cents"] == 7000

    distributed = distribute_pool(pool["id"])
    assert distributed["distribution_status"] == "DISTRIBUTED"
    assert distributed["participant_count"] == 1
    assert distributed["total_share_weight"] == 10
    assert distributed["net_pool_cents"] == 600
    assert distributed["distributed_cents"] == 600

    rows = list_allocations_of(pool["id"])
    assert len(rows) == 1
    row = rows[0]
    assert row["employee_id"] == ana["id"]
    assert row["shift_id"] == keep["id"]
    assert row["entry_type"] == "DISTRIBUTION"
    assert row["share_weight"] == 10
    assert row["allocated_cents"] == 600
    assert row["remainder_cent_awarded"] is False, "a sole participant leaves no leftover"

    assert read_location(dallas["id"])["pending_pool_cents"] == 0
    assert read_employee(ana["id"])["trailing_pool_receipts_cents"] == 600
    assert read_employee(bea["id"])["trailing_pool_receipts_cents"] == 0
    assert read_employee(cal["id"])["trailing_pool_receipts_cents"] == 0


def _california_world(compute: bool = False) -> dict:
    """An Oakland unit that takes no tip credit, forbids card-fee deductions and
    treats charges as TIPS, under an ACTIVE ALL_NON_MANAGEMENT / GROSS_SALES_PCT /
    POINTS_ONLY policy: Dee's selling SERVER shift and Eli's back-of-house COOK
    shift on 2026-08-04, one 8000-cent charge, and the pool built and paid out."""
    set_logical_clock()
    location = new_location(
        name="Oakland Unit",
        state_code="CA",
        state_min_wage_cents=1650,
        cash_wage_cents=1650,
        tip_credit_enabled=False,
        cc_fee_policy="PROHIBITED",
        service_charge_treatment="TIPS",
    )
    role_server = new_job_role()
    role_cook = new_job_role(
        code="COOK",
        title="Line Cook",
        tip_status="NON_TIPPED",
        is_management=False,
        pool_contribution_pct_bps=0,
        pool_share_points=4,
        side_work_eligible=False,
    )
    dee = new_employee(location["id"], full_name="Dee Marino", external_payroll_ref="E1")
    eli = new_employee(location["id"], full_name="Eli Osei", external_payroll_ref="E2")
    new_role_assignment(dee["id"], role_server["id"])
    new_role_assignment(eli["id"], role_cook["id"])
    new_active_policy(
        location["id"],
        location["version"],
        pool_type="ALL_NON_MANAGEMENT",
        contribution_basis="GROSS_SALES_PCT",
        share_basis="POINTS_ONLY",
        cc_fee_pass_through=False,
    )
    pay_period = new_pay_period(location["id"])

    shift_dee = new_shift(
        dee["id"],
        location["id"],
        role_server["id"],
        pay_period["id"],
        gross_sales_cents=100000,
        charged_sales_cents=50000,
        cc_processing_fee_bps=300,
    )
    close_shift(shift_dee["id"])
    declare_shift_tips(shift_dee["id"], dee["id"], 8000, 12000)

    shift_eli = new_shift(
        eli["id"],
        location["id"],
        role_cook["id"],
        pay_period["id"],
        start_at="2026-08-04T08:00:00Z",
        end_at="2026-08-04T16:00:00Z",
    )
    close_shift(shift_eli["id"])
    declare_shift_tips(shift_eli["id"], eli["id"], 0, 0)

    charge = new_service_charge(
        location["id"], amount_cents=8000, description="20 percent party charge"
    )
    pool = new_pool(location["id"])
    distributed = distribute_pool(pool["id"])
    if compute:
        compute_period(pay_period["id"])
    return {
        "location": location,
        "dee": dee,
        "eli": eli,
        "shift_dee": shift_dee,
        "shift_eli": shift_eli,
        "charge": charge,
        "pool": distributed,
        "pay_period": pay_period,
    }


# ---------------------------------------------------------------------------
# calculations / california_configuration_zeroes_the_card_fee...
# ---------------------------------------------------------------------------
def test_california_takes_no_fee_pools_the_charge_and_pays_the_cook(api):
    """Gross sales set the contribution, the 300-bps fee takes nothing, and a
    back-of-house role lawfully shares.

    PRD §2.4: "Where `tip_credit_enabled` is false, `max_tip_credit_per_hour_cents` is
    0 and no tip credit is ever available at that unit, whatever its cash wage happens
    to be."
    PRD §3.7: "The basis the contribution rate applies to depends on the pinned
    policy's `contribution_basis`: under `TIPS_RECEIVED_PCT` the basis is those tips
    received; under `GROSS_SALES_PCT` the basis is the shift's `gross_sales_cents`
    instead."
    PRD §3.7: "If the pinned policy's `cc_fee_pass_through` is false, or the unit's
    `cc_fee_policy` is `PROHIBITED`, then `cc_fee_deducted_cents` is 0 and the fee
    calculation stops there."
    PRD §3.6: "A `TIPS` amount instead joins the shift tip pool for its operating date
    and is excluded from the regular rate altogether."
    PRD §3.7: "Each participant's base share is `net_pool_cents` multiplied by that
    participant's `share_weight`, divided by `total_share_weight`, with any fraction
    discarded."
    PRD §3.7: "Exactly one extra cent goes to each of the first however-many
    participants the leftover permits, taken in descending order of `share_weight` and,
    where two participants tie on weight, in ascending order of their shifts'
    `created_at`."

    Design: Corner/calculations/california_configuration_zeroes_the_card_fee_and_routes_charges_into_the_pool
    """
    world = _california_world()

    unit = read_location(world["location"]["id"])
    assert unit["applicable_min_wage_cents"] == 1650, (
        "the 1650-cent state wage beats the 725 federal constant"
    )
    assert unit["max_tip_credit_per_hour_cents"] == 0

    pool = world["pool"]
    assert pool["contributing_shift_count"] == 1, "only Dee's role carries a rate"
    assert pool["participant_count"] == 2, "ALL_NON_MANAGEMENT admits the cook too"
    assert pool["total_contributed_cents"] == 15000, (
        "1500 bps of the 100000 gross sales, not the 3000 that 15% of the 20000 "
        "declared tips would give: GROSS_SALES_PCT selects the other basis"
    )
    assert pool["service_charge_tips_cents"] == 8000
    assert pool["cc_fee_deducted_cents"] == 0, (
        "not the 360 that 300 bps of the 12000 charged tips would imply — PROHIBITED "
        "and cc_fee_pass_through false each independently zero the deduction"
    )
    assert pool["net_pool_cents"] == 23000
    assert pool["total_share_weight"] == 14
    assert pool["distributed_cents"] == 23000

    charge = read_service_charge(world["charge"]["id"])
    assert charge["treatment"] == "TIPS"
    assert charge["status"] == "ALLOCATED"
    assert charge["allocated_pool_id"] == pool["id"]
    assert charge["allocated_pay_period_id"] is None

    rows = list_allocations_of(pool["id"])
    assert len(rows) == 2
    by_employee = {row["employee_id"]: row for row in rows}
    dee_row = by_employee[world["dee"]["id"]]
    eli_row = by_employee[world["eli"]["id"]]
    assert dee_row["share_weight"] == 10
    assert dee_row["allocated_cents"] == 16429
    assert dee_row["remainder_cent_awarded"] is True
    assert eli_row["share_weight"] == 4
    assert eli_row["allocated_cents"] == 6571
    assert eli_row["remainder_cent_awarded"] is False
    assert dee_row["allocated_cents"] + eli_row["allocated_cents"] == 23000, (
        "the floors were 16428 and 6571 and the single leftover cent went to the "
        "higher weight"
    )


def test_a_tips_treated_charge_stays_out_of_both_regular_rates(api):
    """No credit is available and no charge money reaches either line's wages.

    PRD §3.8: "`tipped_employee_qualified` is true only if all three of the following
    hold: the unit's `tip_credit_enabled` is true; at least one `CLOSED` shift of the
    period has a `tip_credit_eligible_minutes` greater than 0, which is the evidence
    that a valid pre-shift notice was on file; and the employee's
    `monthly_tip_baseline_cents`, plus the sum over the period's `CLOSED` shifts of
    `declared_cash_tips_cents` plus `declared_charged_tips_cents`, reaches at least the
    monthly threshold of 3000 cents."
    PRD §3.8: "`service_charge_wages_cents` is taken as already written by the
    allocation of §3.6."
    PRD §3.8: "Tips and `TIPS`-treated service charges never enter it."
    PRD §3.8: "`reported_tips_cents` is `retained_tips_cents` plus `pool_tips_cents`,
    and is the figure the reporting test measures."
    PRD §3.4: "`gross_receipts_cents` is the sum of `gross_sales_cents` over the same
    set of shifts — the establishment's food and beverage receipts for the week, which
    is what the reporting test of §3.8 measures tips against."

    Design: Corner/calculations/california_configuration_zeroes_the_card_fee_and_routes_charges_into_the_pool
    """
    world = _california_world(compute=True)

    dee_line = _line_of(world["pay_period"]["id"], world["dee"]["id"])
    assert dee_line["tip_credit_eligible_minutes"] == 0
    assert dee_line["non_tip_credit_minutes"] == 480
    assert dee_line["straight_cash_cents"] == 13200, "1650 cents over 8 hours"
    assert dee_line["service_charge_wages_cents"] == 0
    assert dee_line["regular_rate_cents_per_hour"] == 1650
    assert dee_line["minimum_wage_obligation_cents"] == 13200
    assert dee_line["retained_tips_cents"] == 5000, "20000 declared less the 15000 pooled"
    assert dee_line["pool_tips_cents"] == 16429
    assert dee_line["tipped_employee_qualified"] is False
    assert dee_line["tip_credit_cents"] == 0
    assert dee_line["topup_cents"] == 0
    assert dee_line["total_gross_cents"] == 13200
    assert dee_line["reported_tips_cents"] == 21429

    eli_line = _line_of(world["pay_period"]["id"], world["eli"]["id"])
    assert eli_line["straight_cash_cents"] == 13200
    assert eli_line["service_charge_wages_cents"] == 0, (
        "a TIPS-treated charge never enters the regular rate, it goes to the pool"
    )
    assert eli_line["retained_tips_cents"] == 0
    assert eli_line["pool_tips_cents"] == 6571
    assert eli_line["tip_credit_cents"] == 0
    assert eli_line["total_gross_cents"] == 13200
    assert eli_line["reported_tips_cents"] == 6571

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_credited_minutes"] == 960
    assert period["total_tip_credit_cents"] == 0
    assert period["total_topup_cents"] == 0
    assert period["gross_receipts_cents"] == 100000
    assert period["reported_tips_cents"] == 28000
    assert period["allocation_shortfall_cents"] == 0, (
        "the reporting test runs at approval, and this week was only computed"
    )


# ---------------------------------------------------------------------------
# calculations / no_written_notice_before_the_shift_forces_the_full_minimum_wage
# ---------------------------------------------------------------------------
def test_a_notice_acknowledged_after_the_shift_began_buys_no_tip_credit(api):
    """Three identical shifts, three notices: absent, four hours late, and in July.

    PRD §3.2: "It defaults to null, and null means no notice is on file, which forbids
    any tip credit whatsoever on shifts worked in that role."
    PRD §3.2: "The notice must also predate the work: an acknowledgement recorded
    strictly after a shift began does not cover that shift, so a shift is treated as
    having no notice unless its authorising assignment carries an acknowledgement
    instant at or before the shift's `start_at`."
    PRD §3.5: "The shift earns no tip-credit-eligible time at all — meaning
    `non_tip_credit_minutes` is set equal to `scheduled_minutes` — if any one of three
    conditions holds: the unit's `tip_credit_enabled` is false; or the job role's
    `tip_status` is `NON_TIPPED`; or the authorising assignment's
    `tip_credit_notice_acknowledged_at` is null, or is an instant strictly after the
    shift's `start_at`, meaning no written tip-credit notice was on file before the
    shift began."
    PRD §3.8: "If `tipped_employee_qualified` comes out false, `tip_credit_cents` is 0
    for the whole line."
    PRD §3.8: "`topup_cents` is `minimum_wage_obligation_cents` less
    `straight_cash_cents`, less `service_charge_wages_cents`, less
    `overtime_premium_cents`, less `tip_credit_cents`, floored at 0."

    Design: Corner/calculations/no_written_notice_before_the_shift_forces_the_full_minimum_wage
    """
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    ana = new_employee(location["id"])
    bea = new_employee(location["id"], full_name="Bea Olsen", external_payroll_ref="E2")
    cam = new_employee(location["id"], full_name="Cam Vega", external_payroll_ref="E3")
    _assignment_without_notice(ana["id"], role_server["id"])
    new_role_assignment(
        bea["id"], role_server["id"],
        tip_credit_notice_acknowledged_at="2026-08-04T20:00:00Z",
    )
    new_role_assignment(cam["id"], role_server["id"])
    pay_period = new_pay_period(location["id"])

    shifts = {}
    for employee in (ana, bea, cam):
        shift = new_shift(
            employee["id"], location["id"], role_server["id"], pay_period["id"]
        )
        close_shift(shift["id"])
        declare_shift_tips(shift["id"], employee["id"], 5000, 0)
        shifts[employee["id"]] = shift

    for gated in (ana, bea):
        shift = read_shift(shifts[gated["id"]]["id"])
        assert shift["non_tip_credit_minutes"] == 480, (
            "the gate fired at close time, not any side-work overage"
        )
        assert shift["tip_credit_eligible_minutes"] == 0

    covered = read_shift(shifts[cam["id"]]["id"])
    assert covered["non_tip_credit_minutes"] == 0
    assert covered["tip_credit_eligible_minutes"] == 480

    compute_period(pay_period["id"])

    for gated in (ana, bea):
        line = _line_of(pay_period["id"], gated["id"])
        assert line["tipped_employee_qualified"] is False
        assert line["straight_cash_cents"] == 5800, "725 cents over all 8 hours"
        assert line["regular_rate_cents_per_hour"] == 725
        assert line["minimum_wage_obligation_cents"] == 5800
        assert line["tips_available_cents"] == 5000
        assert line["tip_credit_cents"] == 0
        assert line["topup_cents"] == 0
        assert line["total_gross_cents"] == 5800

    cam_line = _line_of(pay_period["id"], cam["id"])
    assert cam_line["tipped_employee_qualified"] is True
    assert cam_line["straight_cash_cents"] == 1704
    assert cam_line["minimum_wage_obligation_cents"] == 5800
    assert cam_line["tip_credit_cents"] == 4096, (
        "the tip credit is worth exactly the 4096 the waterfall could not fill from "
        "the 213-cent cash wage"
    )
    assert cam_line["topup_cents"] == 0
    assert cam_line["total_gross_cents"] == 1704, (
        "1704 against 5800 each for the two gated employees"
    )

    period = read_pay_period(pay_period["id"])
    assert period["total_credited_minutes"] == 1440
    assert period["total_tip_credit_cents"] == 4096
    assert period["total_topup_cents"] == 0
    assert period["reported_tips_cents"] == 15000
