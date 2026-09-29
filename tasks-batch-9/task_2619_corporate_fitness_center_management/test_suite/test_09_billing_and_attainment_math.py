"""Billing arithmetic and programme attainment arithmetic.

Four money-and-arithmetic behaviours the PRD pins to a single answer:

* the MANAGEMENT_FEE invoice variant — a flat retainer reduced by the coverage
  shortfall penalty, with no markup and no volume credit (PRD §3.9, §3.5);
* the two attainment figures — provisional (forward-looking, crediting the
  forecast of still-open sessions) against final (retrospective, counting only
  completed sessions) (PRD §3.4);
* labor cost rounded once per staffing assignment and only then summed, so the
  invoice's labor subtotal is 9791 and not 9792 (PRD §3.5, §3.9);
* the cost-plus ladder whose evaluation order is fixed — the markup tier is
  keyed on the labor-plus-supply base, the volume credit tier is keyed on the
  already-marked-up gross, and the per-asset downtime credit comes off last
  (PRD §3.9, §3.3).

Every expected figure below is the one the PRD states in prose.
"""
from test_helpers import TEST_DEFAULTS, THRESHOLDS
from test_helpers import fixtures as scenarios
from test_helpers.assertions import assert_monthly_invoice


# ==========================================================================
# Composite setups shared by the paired tests of one behaviour
# ==========================================================================
def _setup_management_fee_period_with_two_uncovered_sessions() -> tuple:
    """An ACTIVE MANAGEMENT_FEE site whose only two sessions were cancelled for
    want of cover, then one DRAFT invoice for 2026-08.

    Nothing is ever completed, so the labor and direct-supply components stay 0
    and no asset ever leaves service, so the downtime credit stays 0.  Returns
    (scenario, invoice).
    """
    scenario = scenarios.setup_active_program("MANAGEMENT_FEE")
    scenarios.setup_uncovered_sessions(scenario, 2)
    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")
    return scenario, invoice


def _setup_offering_with_one_completed_and_two_open_sessions() -> tuple:
    """One offering targeting 4 participations with three sessions: the first
    completed carrying two counted check-ins, the other two still SCHEDULED
    forecasting 3 and 2 attendees.

    Returns (scenario, completed_session, attainment_report).
    """
    scenario = scenarios.setup_active_program()
    completed = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
        direct_supply_cost_cents=23522,
    )
    scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-12T12:00:00Z",
        scheduled_end_utc="2026-08-12T12:55:00Z",
        forecast_attendance=3,
    )
    scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-19T12:00:00Z",
        scheduled_end_utc="2026-08-19T12:55:00Z",
        forecast_attendance=2,
    )
    lead = scenarios.assign_staff(scenario, completed["id"], role_on_session="LEAD")
    scenarios.confirm_assignment(scenario, lead["id"])
    first_member = scenarios.setup_ready_member(scenario, full_name="Ada Kim")
    second_member = scenarios.setup_ready_member(scenario, full_name="Ben Ortiz")
    scenarios.start_session(scenario, completed["id"], clock_at="2026-08-05T12:00:00Z")
    scenarios.check_in(scenario, first_member["id"], completed["id"])
    scenarios.check_in(scenario, second_member["id"], completed["id"])
    scenarios.complete_session(scenario, completed["id"])
    return (
        scenario,
        scenarios.read_session(completed["id"]),
        scenarios.read_attainment(scenario["offering_id"]),
    )


def _setup_billed_period_for_one_completed_session() -> tuple:
    """One 55-minute session worked by a LEAD and a SUPPORT worker, both paid
    4700 cents an hour, completed inside 2026-08 and then invoiced.

    Returns (scenario, invoice).
    """
    scenario = scenarios.setup_completed_session_for_billing()
    scenarios.set_clock("2026-08-31T00:00:00Z")
    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")
    return scenario, invoice


def _setup_billed_period_with_two_assets_out_of_service() -> tuple:
    """The same completed session, plus two outages inside the same period: the
    defibrillator is out 2026-08-06 -> 2026-08-12 and a cardio machine is out
    2026-08-06 -> 2026-08-10.

    Returns (scenario, cardio_asset, invoice).
    """
    scenario = scenarios.setup_completed_session_for_billing()
    cardio = scenarios.add_cardio_asset(scenario)
    scenarios.setup_asset_downtime(
        scenario, scenario["aed_id"], "2026-08-06T09:00:00Z", "2026-08-12T09:00:00Z"
    )
    scenarios.setup_asset_downtime(
        scenario, cardio["id"], "2026-08-06T09:00:00Z", "2026-08-10T09:00:00Z"
    )
    scenarios.set_clock("2026-08-31T00:00:00Z")
    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")
    return scenario, scenarios.read_asset(cardio["id"]), invoice


# ==========================================================================
# The MANAGEMENT_FEE invoice variant: flat fee minus the coverage penalty
# ==========================================================================
def test_management_fee_invoice_bills_flat_fee_less_coverage_penalty():
    """PRD §3.9: "`gross_amount_cents` is simply the contract's
    `management_fee_cents`."

    PRD §3.9: "`coverage_penalty_cents` is the coverage shortfall penalty from
    §3.5, computed from the contract's `uncovered_session_count` against its
    `management_fee_cents`."

    PRD §3.9: "`net_amount_cents` is that gross less `coverage_penalty_cents`
    less `downtime_credit_cents`."

    PRD §3.5: "On a `MANAGEMENT_FEE` contract, first take the contract's
    `uncovered_session_count`, subtract a one-session allowance, and floor the
    result at 0 to obtain the chargeable count."

    PRD §3.5: "On a monthly fee of 40000 cents that yields a per-session amount
    of 600 and a ceiling of 2000, so four uncovered sessions cost three
    chargeable sessions at 600 each, or 1800; six uncovered sessions would
    compute to 3000 and are therefore clipped to the ceiling of 2000."

    PRD §3.9: "The draft **pins** the contract's current `fee_structure` into
    `fee_structure_snapshot`, so that a contract amended mid-dispute is still
    rebilled under the terms that were in force when the period was first
    invoiced; every subsequent recomputation of that invoice reads the snapshot
    rather than the live contract."

    Design: Difficulty/dual_variant_calc/invoice_management_fee_variant_flat_fee_minus_coverage_penalty
    """
    _scenario, invoice = _setup_management_fee_period_with_two_uncovered_sessions()

    assert_monthly_invoice(invoice)
    assert invoice["fee_structure_snapshot"] == "MANAGEMENT_FEE", (
        "the draft must pin the contract's MANAGEMENT_FEE structure into "
        f"fee_structure_snapshot, got {invoice['fee_structure_snapshot']!r}"
    )
    assert invoice["gross_amount_cents"] == TEST_DEFAULTS["MANAGEMENT_FEE_CENTS"], (
        "gross_amount_cents on a management-fee invoice is simply the contracted "
        f"flat fee of {TEST_DEFAULTS['MANAGEMENT_FEE_CENTS']}, got "
        f"{invoice['gross_amount_cents']}"
    )
    assert invoice["coverage_penalty_cents"] == 600, (
        "two uncovered sessions less the one-session allowance leave one "
        "chargeable session at 1.5 percent of 40000, so the penalty is 600, got "
        f"{invoice['coverage_penalty_cents']}"
    )
    assert invoice["downtime_credit_cents"] == 0, (
        "no asset ever left service in the period, so downtime_credit_cents must "
        f"be 0, got {invoice['downtime_credit_cents']}"
    )
    assert invoice["net_amount_cents"] == 39400, (
        "the net is the 40000 gross less the 600 penalty less a 0 downtime "
        f"credit, so 39400, got {invoice['net_amount_cents']}"
    )
    assert invoice["status"] == "DRAFT", (
        f"a newly drafted invoice lands in DRAFT, got {invoice['status']!r}"
    )


def test_management_fee_invoice_carries_no_markup_and_no_volume_credit():
    """PRD §3.9: "`admin_markup_cents` is 0 and `volume_credit_cents` is 0 —
    neither concept applies."

    PRD §3.9: "And `nte_capped` is always false, because a management-fee
    contract carries no `not_to_exceed_cents`."

    PRD §3.9: "Note that `labor_subtotal_cents` and `program_direct_cost_cents`
    are still computed and stored for transparency; they simply do not enter the
    arithmetic."

    PRD §3.5: "Its side effects are: assignments in `ASSIGNED`, `CONFIRMED`,
    **or** `VACANT_NEEDS_COVER` status move to `RELEASED` with the same
    committed-minutes compensation (and, as always, no double subtraction for one
    already vacated); the contract's `uncovered_session_count` increments by 1;
    the contract's `pending_penalty_cents` is recomputed; and the offering's
    `provisional_attainment_pct` is recomputed."

    Design: Difficulty/dual_variant_calc/invoice_management_fee_variant_flat_fee_minus_coverage_penalty
    """
    scenario, invoice = _setup_management_fee_period_with_two_uncovered_sessions()

    assert invoice["admin_markup_cents"] == 0, (
        "the administrative markup is a cost-plus concept and must stay 0 on a "
        f"management-fee invoice, got {invoice['admin_markup_cents']}"
    )
    assert invoice["volume_credit_cents"] == 0, (
        "the volume credit is a cost-plus concept and must stay 0 on a "
        f"management-fee invoice, got {invoice['volume_credit_cents']}"
    )
    assert invoice["labor_subtotal_cents"] == 0, (
        "no assignment ever reached COMPLETED, so labor_subtotal_cents must be 0, "
        f"got {invoice['labor_subtotal_cents']}"
    )
    assert invoice["program_direct_cost_cents"] == 0, (
        "no session ever reached COMPLETED, so program_direct_cost_cents must be "
        f"0, got {invoice['program_direct_cost_cents']}"
    )
    assert invoice["nte_capped"] is False, (
        "a management-fee contract carries no not_to_exceed_cents, so nte_capped "
        f"is always false, got {invoice['nte_capped']!r}"
    )

    contract = scenarios.read_contract(scenario["contract_id"])
    assert contract["uncovered_session_count"] == 2, (
        "each NO_COVER cancellation increments uncovered_session_count, so two "
        f"cancellations leave 2, got {contract['uncovered_session_count']}"
    )
    assert contract["pending_penalty_cents"] == 600, (
        "pending_penalty_cents is recomputed on every NO_COVER cancellation and "
        f"must agree with the invoice's 600, got {contract['pending_penalty_cents']}"
    )


# ==========================================================================
# The two attainment figures: forward-looking against retrospective
# ==========================================================================
def test_provisional_attainment_credits_the_forecast_of_still_open_sessions():
    """PRD §3.4: "The **provisional** figure is forward-looking and answers "are
    we on track?"."

    PRD §3.4: "Its numerator is the count of participation records still in
    `COUNTED` status that belong to sessions of this offering whose status is
    `IN_PROGRESS` or `COMPLETED`, **plus** the sum of `forecast_attendance`
    across every session of this offering still open — that is, still in
    `SCHEDULED`, `STAFFED`, or `STAFFING_AT_RISK`."

    PRD §3.4: "Multiply that numerator by 100, divide by `participation_target`,
    round half up, and store the result in `provisional_attainment_pct`."

    PRD §3.4: "To make the divergence auditable, a dedicated computed read
    reports the two figures side by side along with the components each used:
    `offering_id`, `participation_target`, the `counted_done` count of
    participations on in-progress and completed sessions, the `forecast_open` sum
    across still-open sessions, the `counted_final` count on completed sessions
    only, both `provisional_attainment_pct` and `final_attainment_pct`, and
    `coverage_gap_count`."

    Design: Difficulty/dual_variant_calc/attainment_provisional_forward_looking_vs_final_retrospective
    """
    scenario, _completed, attainment = (
        _setup_offering_with_one_completed_and_two_open_sessions()
    )

    assert attainment["counted_done"] == 2, (
        "two members checked into the completed session, so counted_done is 2, "
        f"got {attainment['counted_done']}"
    )
    assert attainment["forecast_open"] == 5, (
        "the two still-SCHEDULED sessions forecast 3 and 2 attendees, so "
        f"forecast_open is 5, got {attainment['forecast_open']}"
    )
    assert attainment["participation_target"] == 4, (
        "the offering targets 4 counted participations over its whole life, got "
        f"{attainment['participation_target']}"
    )

    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["provisional_attainment_pct"] == 175, (
        "the provisional numerator is 2 counted plus 5 forecast against a target "
        f"of 4, so 175, got {offering['provisional_attainment_pct']}"
    )
    assert attainment["provisional_attainment_pct"] == 175, (
        "the computed read must report the same provisional figure as the "
        f"offering row, got {attainment['provisional_attainment_pct']}"
    )


def test_final_attainment_counts_only_completed_session_participations():
    """PRD §3.4: "The **final** figure is retrospective and answers "what did we
    actually deliver?"."

    PRD §3.4: "Its numerator is the count of participation records still in
    `COUNTED` status belonging to sessions of this offering in `COMPLETED` status
    only; forecasts and open sessions are ignored entirely."

    PRD §3.4: "Multiply by 100, divide by `participation_target`, round half up,
    and store the result in `final_attainment_pct`."

    PRD §3.5: "**Completing** moves the session `IN_PROGRESS → COMPLETED` (from
    any other status the request is refused with
    `ERR_INVALID_STATE_TRANSITION`), stamps `completed_at`, and sets
    `actual_attendance` to the number of that session's participation records
    still in `COUNTED` status."

    PRD §3.4: "`counted_participation_total` is the number of participation
    records in `COUNTED` status across all of the offering's sessions,
    incremented on every check-in and decremented on every void."

    Design: Difficulty/dual_variant_calc/attainment_provisional_forward_looking_vs_final_retrospective
    """
    scenario, completed, attainment = (
        _setup_offering_with_one_completed_and_two_open_sessions()
    )

    assert completed["actual_attendance"] == 2, (
        "completion sets actual_attendance to the session's COUNTED records, so 2, "
        f"got {completed['actual_attendance']}"
    )
    assert attainment["counted_final"] == 2, (
        "only the completed session's two counted check-ins feed the final "
        f"numerator, so counted_final is 2, got {attainment['counted_final']}"
    )

    offering = scenarios.read_offering(scenario["offering_id"])
    assert offering["counted_participation_total"] == 2, (
        "two check-ins across the offering's sessions leave "
        f"counted_participation_total at 2, got {offering['counted_participation_total']}"
    )
    assert offering["final_attainment_pct"] == 50, (
        "the final numerator is 2 counted on completed sessions against a target "
        f"of 4, so 50, got {offering['final_attainment_pct']}"
    )
    assert attainment["final_attainment_pct"] == 50, (
        "the computed read must report the same final figure as the offering row, "
        f"got {attainment['final_attainment_pct']}"
    )
    assert (
        offering["provisional_attainment_pct"] != offering["final_attainment_pct"]
    ), (
        "the two figures read different inputs on this data and must diverge: "
        f"provisional {offering['provisional_attainment_pct']} against final "
        f"{offering['final_attainment_pct']} — collapsing them to one number "
        "would mean the forecast of the still-open sessions was folded into the "
        "retrospective figure"
    )


# ==========================================================================
# Labor cost: round once per assignment, then sum
# ==========================================================================
def test_labor_cost_is_rounded_once_per_assignment_before_being_summed():
    """PRD §3.5: "Labor costing has one subtlety that an implementation must get
    exactly right: **each assignment is rounded on its own, and only the
    already-rounded amounts are summed.**"

    PRD §3.5: "Concretely, a 55-minute session staffed by a lead and a support
    worker both costing 4700 cents an hour books 70 paid minutes for the lead and
    55 for the support worker; the lead's cost is 5483 cents (from 5483.33 rounded
    down by half-up on a value below the half) and the support worker's is 4308
    cents (from 4308.33), for a session total of 9791 cents."

    PRD §3.5: "`paid_minutes` is computed as the session's `scheduled_minutes`
    plus a setup allowance of 15 minutes when the `role_on_session` is `LEAD`, and
    simply the session's `scheduled_minutes` when it is `SUPPORT`."

    PRD §3.5: "It then settles the labor: every assignment of the session in
    `CONFIRMED` status moves to `COMPLETED` and receives its `labor_cost_cents`."

    Design: Difficulty/combinatorial_formula/labor_cost_rounds_per_assignment_then_sums
    """
    scenario, _invoice = _setup_billed_period_for_one_completed_session()
    lead = scenarios.read_assignment(scenario["lead_assignment"]["id"])
    support = scenarios.read_assignment(scenario["support_assignment"]["id"])

    assert lead["paid_minutes"] == 55 + THRESHOLDS["LEAD_SETUP_MIN"], (
        "a LEAD is paid the session's 55 scheduled minutes plus the 15-minute "
        f"setup allowance, so 70, got {lead['paid_minutes']}"
    )
    assert support["paid_minutes"] == 55, (
        "a SUPPORT worker is paid the session's scheduled minutes alone, so 55, "
        f"got {support['paid_minutes']}"
    )
    assert lead["labor_cost_cents"] == 5483, (
        "4700 cents an hour over 70 paid minutes is 5483.33, which rounds half up "
        f"to 5483, got {lead['labor_cost_cents']}"
    )
    assert support["labor_cost_cents"] == 4308, (
        "4700 cents an hour over 55 paid minutes is 4308.33, which rounds half up "
        f"to 4308, got {support['labor_cost_cents']}"
    )
    assert lead["status"] == "COMPLETED", (
        "completing the session settles every CONFIRMED assignment into COMPLETED, "
        f"got {lead['status']!r} on the lead assignment"
    )
    assert support["status"] == "COMPLETED", (
        "completing the session settles every CONFIRMED assignment into COMPLETED, "
        f"got {support['status']!r} on the support assignment"
    )
    assert lead["labor_cost_cents"] + support["labor_cost_cents"] == 9791, (
        "the session total is the plain sum of the two already-rounded assignment "
        f"amounts, so 9791, got {lead['labor_cost_cents'] + support['labor_cost_cents']}"
    )


def test_invoice_labor_subtotal_sums_already_rounded_assignment_costs():
    """PRD §3.9: "`labor_subtotal_cents` is the sum of `labor_cost_cents` over
    every staffing assignment in `COMPLETED` status whose session's `completed_at`
    falls inside the billed `period_month` — assignments that were released,
    vacated, or are merely confirmed contribute nothing, and the session's
    completion date rather than its scheduled date decides which month it lands
    in."

    PRD §3.5: "Computing 4700 times 125 minutes over 60 and rounding once yields
    9792 — off by one, and not what this specification requires."

    PRD §3.9: "`program_direct_cost_cents` is the sum of
    `direct_supply_cost_cents` over every session of the contract in `COMPLETED`
    status inside the period."

    PRD §3.9: "A provisional net is the gross less `volume_credit_cents` less
    `downtime_credit_cents`."

    Design: Difficulty/combinatorial_formula/labor_cost_rounds_per_assignment_then_sums
    """
    _scenario, invoice = _setup_billed_period_for_one_completed_session()

    assert_monthly_invoice(invoice)
    assert invoice["labor_subtotal_cents"] == 9791, (
        "the invoice sums the two already-rounded assignment amounts 5483 and "
        f"4308, so 9791, got {invoice['labor_subtotal_cents']}"
    )
    assert invoice["labor_subtotal_cents"] != 9792, (
        "a labor subtotal of 9792 would mean the two assignments' 125 paid minutes "
        "were summed first and the aggregate rounded once, which is the order the "
        "specification rules out"
    )
    assert invoice["program_direct_cost_cents"] == 23522, (
        "the completed session carried 23522 cents of direct supply cost, got "
        f"{invoice['program_direct_cost_cents']}"
    )
    assert invoice["net_amount_cents"] == 35110, (
        "a base of 33313 marked up by 2332 gives a gross of 35645, less the 535 "
        "volume credit and a 0 downtime credit, so the net is 35110, got "
        f"{invoice['net_amount_cents']}"
    )
    assert invoice["net_amount_cents"] != 35111, (
        "a net of 35111 would mean the labor subtotal entered the ladder as 9792 — "
        "the off-by-one cent from rounding the aggregate minute count once"
    )


# ==========================================================================
# The cost-plus ladder: markup tier on the base, credit tier on the gross
# ==========================================================================
def test_cost_plus_markup_tier_reads_the_base_and_credit_tier_reads_the_gross():
    """PRD §3.9: "Start from a base equal to `labor_subtotal_cents` plus
    `program_direct_cost_cents`."

    PRD §3.9: "The markup rate steps down as that base grows: 12 percent when the
    base is 15000 cents or less, otherwise 9 percent when it is 30000 cents or
    less, otherwise 7 percent."

    PRD §3.9: "`admin_markup_cents` is the base multiplied by that rate, rounded
    half up to whole cents."

    PRD §3.9: "`gross_amount_cents` is the base plus `admin_markup_cents`."

    PRD §3.9: "The volume credit rate then steps **up** with the gross: 3 percent
    when the gross is 70000 cents or more, otherwise 1.5 percent when it is 35000
    cents or more, otherwise nothing at all."

    PRD §3.9: "`volume_credit_cents` is the gross multiplied by that rate, rounded
    half up to whole cents and independently of the markup rounding."

    PRD §3.9: "Worked through with the session from §3.5: a period whose completed
    assignments total 9791 cents of labor and whose completed sessions carried
    23522 cents of direct supply cost gives a base of 33313, which falls above
    30000 and therefore takes the 7 percent tier, producing an
    `admin_markup_cents` of 2332 and a `gross_amount_cents` of 35645."

    PRD §3.9: "That gross is at or above 35000, so the 1.5 percent credit applies,
    giving a `volume_credit_cents` of 535."

    Design: Difficulty/combinatorial_formula/invoice_markup_tier_keyed_on_base_then_credit_tier_on_marked_up_gross
    """
    _scenario, _cardio, invoice = _setup_billed_period_with_two_assets_out_of_service()

    assert_monthly_invoice(invoice)
    assert invoice["fee_structure_snapshot"] == "COST_PLUS", (
        "the draft must pin the contract's COST_PLUS structure into "
        f"fee_structure_snapshot, got {invoice['fee_structure_snapshot']!r}"
    )
    assert invoice["labor_subtotal_cents"] == 9791, (
        f"the period's completed labor is 9791, got {invoice['labor_subtotal_cents']}"
    )
    assert invoice["program_direct_cost_cents"] == 23522, (
        "the completed session carried 23522 cents of direct supply cost, got "
        f"{invoice['program_direct_cost_cents']}"
    )
    assert invoice["admin_markup_cents"] == 2332, (
        "the base of 9791 plus 23522 is 33313, which is above 30000 and so takes "
        f"the 7 percent tier for a markup of 2332, got {invoice['admin_markup_cents']}"
    )
    assert invoice["gross_amount_cents"] == 35645, (
        "the gross is the 33313 base plus the 2332 markup, so 35645, got "
        f"{invoice['gross_amount_cents']}"
    )
    assert invoice["volume_credit_cents"] == 535, (
        "the credit tier reads the marked-up gross of 35645, which is at or above "
        f"35000 and so earns 1.5 percent, or 535, got {invoice['volume_credit_cents']}"
    )
    assert invoice["net_amount_cents"] != 32901, (
        "a net of 32901 would mean the markup tier was selected from the "
        "labor subtotal of 9791 alone — the 12 percent band — instead of from the "
        "labor-plus-supply base of 33313"
    )
    assert invoice["net_amount_cents"] != 31795, (
        "a net of 31795 would mean the volume credit tier was selected from the "
        "pre-markup base of 33313, which sits below 35000 and would earn nothing, "
        "instead of from the marked-up gross of 35645"
    )


def test_cost_plus_net_applies_per_asset_downtime_grace_after_the_volume_credit():
    """PRD §3.3: "For each asset of the contract, subtract a grace allowance of 3
    days from that asset's `out_of_service_days_current_period` and floor the
    result at 0, then multiply the remaining chargeable days by a per-day rate
    that depends on the asset's type: 1200 cents per day for a defibrillator and
    250 cents per day for any other asset."

    PRD §3.3: "Because the grace is applied per asset and not once globally, an
    asset out of service for exactly 3 days credits nothing, and a site with one
    defibrillator out for 6 days and one cardio unit out for 4 days credits three
    days of defibrillator downtime and one day of general downtime — 3600 plus
    250, or 3850 cents."

    PRD §3.3: "A `REPAIR_COMPLETE` on an asset in `OUT_OF_SERVICE` returns it to
    `IN_SERVICE`, sets `last_service_on` to today, clears `out_of_service_since`
    back to null, recomputes `readiness_status` for defibrillators, and —
    importantly — accrues the outage: the number of days from the date the asset
    went out of service to today, rounded up to a whole day, is **added** to
    `out_of_service_days_current_period`."

    PRD §3.9: "`coverage_penalty_cents` is 0 — the client is already paying only
    for work actually delivered, so a missed session costs them nothing to
    penalise."

    PRD §3.9: "With a downtime credit of 3850 the net is 31260 cents, and against
    an annual ceiling of 5000000 with nothing billed year to date there is ample
    headroom, so `nte_capped` is false."

    Design: Difficulty/combinatorial_formula/invoice_markup_tier_keyed_on_base_then_credit_tier_on_marked_up_gross
    """
    scenario, cardio, invoice = _setup_billed_period_with_two_assets_out_of_service()
    aed = scenarios.read_asset(scenario["aed_id"])

    assert aed["out_of_service_days_current_period"] == 6, (
        "the defibrillator was out from 2026-08-06 to 2026-08-12, so 6 days accrue, "
        f"got {aed['out_of_service_days_current_period']}"
    )
    assert cardio["out_of_service_days_current_period"] == 4, (
        "the cardio machine was out from 2026-08-06 to 2026-08-10, so 4 days accrue, "
        f"got {cardio['out_of_service_days_current_period']}"
    )
    assert invoice["downtime_credit_cents"] == 3850, (
        "the 3-day grace is applied per asset, leaving 3 defibrillator days at 1200 "
        "and 1 general day at 250, so 3850, got "
        f"{invoice['downtime_credit_cents']}"
    )
    assert invoice["coverage_penalty_cents"] == 0, (
        "a cost-plus client is never charged a coverage shortfall penalty, got "
        f"{invoice['coverage_penalty_cents']}"
    )
    assert invoice["net_amount_cents"] == 31260, (
        "the 35645 gross less the 535 volume credit less the 3850 downtime credit "
        f"is 31260, got {invoice['net_amount_cents']}"
    )
    assert invoice["nte_capped"] is False, (
        "the annual ceiling of 5000000 with nothing billed year to date leaves "
        f"ample headroom, so nte_capped must stay false, got {invoice['nte_capped']!r}"
    )
