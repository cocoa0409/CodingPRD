"""Computed figures and the read models built on top of them.

Defibrillator readiness at registration, per-assignment labor costing feeding a
cost-plus invoice, the privacy floor on the utilization report, the wellness
incentive streak threshold, and the immediacy of contract approval and its
rollups.
"""
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as scenarios
from test_helpers.assertions import (
    assert_facility_asset,
    assert_monthly_invoice,
    assert_participation_record,
)
from test_helpers.constants import THRESHOLDS

CLASS_ORDER = ("EMPLOYEE", "DEPENDENT", "RETIREE")


# ==========================================================================
# Private composite setups (no shared helper covers these exact shapes)
# ==========================================================================
def _setup_completed_session_with_unconfirmed_support() -> dict:
    """One 55-minute session with a CONFIRMED LEAD and an ASSIGNED SUPPORT row
    that never confirmed, started and completed so labor settles.

    Both instructors cost 4700 cents an hour; the session carries no direct
    supply spend, so the period's only money is labor.
    """
    scenario = scenarios.setup_active_program()
    support = scenarios.add_instructor(scenario, with_drill=False, full_name="Mia Chen")
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=3,
        direct_supply_cost_cents=0,
    )
    lead = scenarios.assign_staff(scenario, session["id"], role_on_session="LEAD")
    unconfirmed = scenarios.assign_staff(
        scenario, session["id"], support["staff"]["id"], role_on_session="SUPPORT"
    )
    scenarios.confirm_assignment(scenario, lead["id"])
    scenarios.start_session(scenario, session["id"], clock_at="2026-08-05T12:00:00Z")
    scenarios.complete_session(scenario, session["id"])
    scenario["session"] = scenarios.read_session(session["id"])
    scenario["lead_assignment"] = scenarios.read_assignment(lead["id"])
    scenario["support_assignment"] = scenarios.read_assignment(unconfirmed["id"])
    scenario["support_staff"] = support["staff"]
    return scenario


def _setup_daily_check_ins(days: list) -> tuple:
    """One eligible, waivered, badged member checking in once a day.

    Every session is scheduled and its LEAD confirmed up front, so each one is
    STAFFED before its day arrives; the clock is then advanced to each start
    instant in turn, the session started and the member checked in.

    Returns (scenario, member, records) with records in day order.
    """
    scenario = scenarios.setup_active_program()
    member = scenarios.setup_ready_member(scenario)
    sessions = []
    for day in days:
        session = scenarios.schedule_session(
            scenario,
            scheduled_start_utc=f"2026-08-{day:02d}T12:00:00Z",
            scheduled_end_utc=f"2026-08-{day:02d}T12:55:00Z",
            forecast_attendance=1,
        )
        scenarios.staff_session(scenario, session["id"])
        sessions.append(session)
    records = []
    for day, session in zip(days, sessions):
        scenarios.start_session(
            scenario, session["id"], clock_at=f"2026-08-{day:02d}T12:00:00Z"
        )
        records.append(scenarios.check_in(scenario, member["id"], session["id"]))
    return scenario, member, records


def _setup_cohort_of_check_ins(member_count: int) -> dict:
    """`member_count` EMPLOYEE members, all eligible/waivered/badged, all checked
    into one completed session on 2026-08-05."""
    scenario = scenarios.setup_active_program()
    members = [scenarios.setup_ready_member(scenario) for _ in range(member_count)]
    session = scenarios.schedule_session(
        scenario,
        scheduled_start_utc="2026-08-05T12:00:00Z",
        scheduled_end_utc="2026-08-05T12:55:00Z",
        forecast_attendance=member_count,
    )
    scenarios.staff_session(scenario, session["id"])
    scenarios.start_session(scenario, session["id"], clock_at="2026-08-05T12:00:00Z")
    for member in members:
        scenarios.check_in(scenario, member["id"], session["id"])
    scenarios.complete_session(scenario, session["id"])
    scenario["members"] = members
    scenario["session"] = scenarios.read_session(session["id"])
    return scenario


def _breakdown_row(class_breakdown: list, member_class: str) -> dict:
    for row in class_breakdown:
        if row.get("member_class") == member_class:
            return row
    raise AssertionError(
        f"class_breakdown carries no row for {member_class}: {class_breakdown}"
    )


def _keys_anywhere(payload) -> set:
    """Every key name appearing anywhere inside a nested payload."""
    found = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            found |= _keys_anywhere(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _keys_anywhere(item)
    return found


# ==========================================================================
# Defibrillator readiness at registration
# ==========================================================================
def test_aed_registration_computes_ready_and_pads_expiring_shapes(
    api, operator_admin_headers
):
    """PRD §3.3: "A newly registered asset is `IN_SERVICE` with
    `out_of_service_since` null and `out_of_service_days_current_period` at 0,
    and its `readiness_status` is computed on the spot."

    PRD §3.3: "Otherwise, if the earlier of `pad_expiry_on` and
    `battery_expiry_on` falls at or before 30 days from today, it is
    `PADS_EXPIRING`. Otherwise it is `READY`."

    PRD §3.3: "Asset listings can be filtered by `contract_id`, by `room_id`, by
    `asset_type`, by `status`, and by `readiness_status`."

    Design: Corner/calculations/aed_readiness_evaluated_at_asset_creation_for_each_shape
    """
    scenario = scenarios.setup_active_site()

    ready = scenario["aed"]
    assert_facility_asset(ready)
    assert ready["readiness_status"] == "READY", (
        "a defibrillator whose consumables expire 2027-03-31 and which was "
        f"inspected 2026-07-20 is READY on 2026-08-01, got {ready['readiness_status']}"
    )
    assert ready["status"] == "IN_SERVICE", (
        f"a newly registered asset is IN_SERVICE, got {ready['status']}"
    )
    assert ready["out_of_service_days_current_period"] == 0, (
        "a newly registered asset has accrued no downtime, got "
        f"{ready['out_of_service_days_current_period']}"
    )
    assert ready["out_of_service_since"] is None, (
        f"out_of_service_since must start null, got {ready['out_of_service_since']!r}"
    )

    warning = scenarios.add_ready_aed(
        scenario, asset_tag="AED-02", pad_expiry_on="2026-08-20"
    )
    assert_facility_asset(warning)
    assert warning["readiness_status"] == "PADS_EXPIRING", (
        "a pad expiring 2026-08-20 falls inside the "
        f"{THRESHOLDS['AED_PADS_WARNING_DAYS']}-day window from 2026-08-01, so the "
        f"unit is PADS_EXPIRING, got {warning['readiness_status']}"
    )
    assert warning["status"] == "IN_SERVICE", (
        f"a PADS_EXPIRING unit is still IN_SERVICE, got {warning['status']}"
    )

    items, meta = validate_paginated(
        api.list_facility_assets(
            operator_admin_headers,
            params={
                "contract_id": scenario["contract_id"],
                "readiness_status": "READY",
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"expected 1 READY defibrillator on the site, got {meta['total_count']}"
    )
    assert [item["id"] for item in items] == [ready["id"]], (
        f"the READY filter must return only {ready['id']}, got {items}"
    )


def test_non_aed_asset_registration_is_readiness_not_applicable(api):
    """PRD §3.3: "On any asset whose `asset_type` is not `AED`,
    `readiness_status` is always `NOT_APPLICABLE`."

    PRD §3.3: "Defibrillators additionally require `pad_expiry_on` and
    `battery_expiry_on`, the electrode-pad and battery expiry dates; on any
    non-defibrillator asset both must be null."

    PRD §3.3: "Each asset carries an `asset_type` of `AED`, `CARDIO`, or
    `STRENGTH`, an operator `asset_tag` that must be unique within the contract
    — a collision is refused with `ERR_ASSET_TAG_CONFLICT`, and because the
    scope is per-contract, two different sites may both carry a tag of AED-01 —
    and a `service_interval_days` preventive-maintenance interval that defaults
    to 90 and must fall between 1 and 365 inclusive."

    Design: Corner/calculations/aed_readiness_evaluated_at_asset_creation_for_each_shape
    """
    scenario = scenarios.setup_active_site()

    cardio = validate_success(
        api.create_facility_asset(
            {
                "contract_id": scenario["contract_id"],
                "room_id": scenario["room_id"],
                "asset_type": "CARDIO",
                "asset_tag": "CARDIO-01",
                "last_inspection_on": "2026-07-20",
            },
            scenario["manager_headers"],
        ),
        201,
    )

    assert_facility_asset(cardio)
    assert cardio["readiness_status"] == "NOT_APPLICABLE", (
        "a CARDIO asset carries no defibrillator readiness judgement, got "
        f"{cardio['readiness_status']}"
    )
    assert cardio["pad_expiry_on"] is None and cardio["battery_expiry_on"] is None, (
        "consumable expiries must be null on a non-defibrillator asset, got "
        f"{cardio['pad_expiry_on']!r} / {cardio['battery_expiry_on']!r}"
    )
    assert cardio["service_interval_days"] == 90, (
        "service_interval_days defaults to 90 when the payload omits it, got "
        f"{cardio['service_interval_days']}"
    )
    assert cardio["status"] == "IN_SERVICE", (
        f"a newly registered asset is IN_SERVICE, got {cardio['status']}"
    )
    assert cardio["out_of_service_days_current_period"] == 0, (
        "a newly registered asset has accrued no downtime, got "
        f"{cardio['out_of_service_days_current_period']}"
    )


# ==========================================================================
# Labor costing and the cost-plus invoice built on it
# ==========================================================================
def test_session_labor_excludes_unconfirmed_support_assignment(api):
    """PRD §3.5: "It then settles the labor: every assignment of the session in
    `CONFIRMED` status moves to `COMPLETED` and receives its `labor_cost_cents`."

    PRD §3.5: "For each participating assignment — those in `CONFIRMED` status at
    completion time, and thereafter in `COMPLETED` — multiply the staff member's
    `hourly_cost_cents` by the assignment's `paid_minutes`, divide by 60, and
    round half up to a whole number of cents; store that as the assignment's
    `labor_cost_cents`."

    PRD §3.5: "The session's labor total is the plain sum of those per-assignment
    values."

    PRD §3.5: "`paid_minutes` is computed as the session's `scheduled_minutes`
    plus a setup allowance of 15 minutes when the `role_on_session` is `LEAD`,
    and simply the session's `scheduled_minutes` when it is `SUPPORT`."

    PRD §3.5: "The assignment starts in `ASSIGNED` with `confirmed_at` null and
    `labor_cost_cents` at 0 — labor cost stays 0 until the assignment actually
    reaches `COMPLETED`."

    Design: Corner/calculations/invoice_labor_excludes_unconfirmed_assignments
    """
    scenario = _setup_completed_session_with_unconfirmed_support()
    lead = scenario["lead_assignment"]
    support = scenario["support_assignment"]

    assert lead["status"] == "COMPLETED", (
        f"the CONFIRMED LEAD settles on completion, got {lead['status']}"
    )
    assert lead["paid_minutes"] == 70, (
        f"a LEAD on a 55-minute session is paid 70 minutes, got {lead['paid_minutes']}"
    )
    assert lead["labor_cost_cents"] == 5483, (
        f"expected 5483 cents for 70 paid minutes at 4700/h, got {lead['labor_cost_cents']}"
    )

    assert support["status"] == "ASSIGNED", (
        "an assignment that never confirmed is untouched by completion, got "
        f"{support['status']}"
    )
    assert support["paid_minutes"] == 55, (
        "a SUPPORT row on a 55-minute session is paid 55 minutes, got "
        f"{support['paid_minutes']}"
    )
    assert support["labor_cost_cents"] == 0, (
        "an unconfirmed assignment never receives a labor cost, got "
        f"{support['labor_cost_cents']}"
    )

    items, _ = validate_paginated(
        api.list_staff_assignments(
            scenario["manager_headers"],
            params={"session_id": scenario["session"]["id"]},
        )
    )
    settled = sum(
        item["labor_cost_cents"] for item in items if item["status"] == "COMPLETED"
    )
    assert settled == 5483, (
        "the session's labor total is the sum over its settled assignments and "
        f"must be 5483, not 9791 with the unconfirmed SUPPORT row included; got {settled}"
    )


def test_cost_plus_invoice_labor_subtotal_excludes_unconfirmed_assignment():
    """PRD §3.9: "`labor_subtotal_cents` is the sum of `labor_cost_cents` over
    every staffing assignment in `COMPLETED` status whose session's
    `completed_at` falls inside the billed `period_month` — assignments that were
    released, vacated, or are merely confirmed contribute nothing, and the
    session's completion date rather than its scheduled date decides which month
    it lands in."

    PRD §3.9: "The markup rate steps down as that base grows: 12 percent when
    the base is 15000 cents or less, otherwise 9 percent when it is 30000 cents
    or less, otherwise 7 percent."

    PRD §3.9: "`admin_markup_cents` is the base multiplied by that rate, rounded
    half up to whole cents."

    PRD §3.9: "`gross_amount_cents` is the base plus `admin_markup_cents`."

    PRD §3.9: "`volume_credit_cents` is the gross multiplied by that rate,
    rounded half up to whole cents and independently of the markup rounding."

    PRD §3.9: "`coverage_penalty_cents` is 0 — the client is already paying only
    for work actually delivered, so a missed session costs them nothing to
    penalise."

    Design: Corner/calculations/invoice_labor_excludes_unconfirmed_assignments
    """
    scenario = _setup_completed_session_with_unconfirmed_support()

    invoice = scenarios.draft_invoice(scenario, period_month="2026-08")

    assert_monthly_invoice(invoice)
    assert invoice["fee_structure_snapshot"] == "COST_PLUS", (
        "the draft pins the contract's fee structure, got "
        f"{invoice['fee_structure_snapshot']}"
    )
    assert invoice["labor_subtotal_cents"] == 5483, (
        "only the COMPLETED assignment is billed, so the labor subtotal is 5483, "
        f"got {invoice['labor_subtotal_cents']}"
    )
    assert invoice["program_direct_cost_cents"] == 0, (
        "the session carried no direct supply spend, got "
        f"{invoice['program_direct_cost_cents']}"
    )
    assert invoice["admin_markup_cents"] == 658, (
        "a base of 5483 takes the 12 percent tier and rounds half up to 658, got "
        f"{invoice['admin_markup_cents']}"
    )
    assert invoice["gross_amount_cents"] == 6141, (
        f"expected a gross of 5483 + 658 = 6141, got {invoice['gross_amount_cents']}"
    )
    assert invoice["volume_credit_cents"] == 0, (
        "a gross of 6141 earns no volume credit, got "
        f"{invoice['volume_credit_cents']}"
    )
    assert invoice["downtime_credit_cents"] == 0, (
        f"no asset went out of service, got {invoice['downtime_credit_cents']}"
    )
    assert invoice["coverage_penalty_cents"] == 0, (
        "a cost-plus contract never accrues a coverage penalty, got "
        f"{invoice['coverage_penalty_cents']}"
    )
    assert invoice["net_amount_cents"] == 6141, (
        f"expected a net of 6141 with no credits, got {invoice['net_amount_cents']}"
    )
    assert invoice["nte_capped"] is False, (
        "the annual ceiling of 5000000 leaves ample headroom, got "
        f"{invoice['nte_capped']!r}"
    )


# ==========================================================================
# The utilization report's privacy floor
# ==========================================================================
def test_utilization_report_suppresses_every_cohort_below_the_privacy_floor(api):
    """PRD §2.10: "The contract utilization report breaks participation down by
    member class, and any class cohort whose distinct-participant count falls
    below the privacy floor of 5 is reported as suppressed with null counts
    rather than with real numbers, so that a cohort of one or two people cannot
    be re-identified from the aggregate."

    PRD §3.9: "When the number of distinct participants in that class is fewer
    than 5, the entry reports `suppressed` as true with `participant_count` and
    `check_in_count` both null, because with so few people in a cohort the
    aggregate would be re-identifiable."

    PRD §3.9: "`suppressed_cohort_count` reports how many of the three entries
    were suppressed, so the reader knows the breakdown is incomplete without
    being able to reconstruct what was hidden."

    PRD §3.9: "From those it derives `participation_rate_pct`, which is 0 when
    `eligible_member_count` is 0 and otherwise the distinct participant count
    multiplied by 100, divided by the eligible member count, and rounded half up
    to a whole percent."

    PRD §3.9: "It restates the contract's `participation_target_pct` and reports
    `target_variance_pct` as the achieved rate minus the target, which may
    legitimately be negative when the programme is underperforming."

    PRD §3.9: "And `health_metrics_note` is never projected into this report for
    any role whatsoever: the aggregate view exists to measure programme reach,
    never to expose an individual's health data."

    Design: Corner/calculations/utilization_report_suppresses_cohorts_below_privacy_minimum
    """
    scenario = _setup_cohort_of_check_ins(2)

    report = validate_success(
        api.get_utilization_report(
            scenario["contract_id"],
            scenario["sponsor_headers"],
            params={"period_month": "2026-08"},
        )
    )

    assert report["period_month"] == "2026-08", (
        f"the report restates the period requested, got {report['period_month']!r}"
    )
    assert report["eligible_member_count"] == 2, (
        f"two members were verified, got {report['eligible_member_count']}"
    )
    assert report["distinct_participants"] == 2, (
        f"both members checked in, got {report['distinct_participants']}"
    )
    assert report["participation_rate_pct"] == 100, (
        "2 distinct participants against 2 eligible members is 100 percent, got "
        f"{report['participation_rate_pct']}"
    )
    assert report["participation_target_pct"] == 35, (
        f"the contract's target is 35, got {report['participation_target_pct']}"
    )
    assert report["target_variance_pct"] == 65, (
        f"100 achieved less a target of 35 is +65, got {report['target_variance_pct']}"
    )

    breakdown = report["class_breakdown"]
    assert [row["member_class"] for row in breakdown] == list(CLASS_ORDER), (
        "class_breakdown carries EMPLOYEE, DEPENDENT and RETIREE in that order, got "
        f"{[row.get('member_class') for row in breakdown]}"
    )
    for row in breakdown:
        assert row["suppressed"] is True, (
            f"{row['member_class']} has fewer than "
            f"{THRESHOLDS['PRIVACY_MIN_COHORT']} distinct participants and must be "
            f"suppressed, got {row['suppressed']!r}"
        )
        assert row["participant_count"] is None, (
            f"a suppressed {row['member_class']} cohort reports a null "
            f"participant_count, got {row['participant_count']!r}"
        )
        assert row["check_in_count"] is None, (
            f"a suppressed {row['member_class']} cohort reports a null "
            f"check_in_count, got {row['check_in_count']!r}"
        )
    assert report["suppressed_cohort_count"] == 3, (
        "all three cohorts sit below the floor, got "
        f"{report['suppressed_cohort_count']}"
    )

    assert "health_metrics_note" not in _keys_anywhere(report), (
        "health_metrics_note must never be projected into the utilization report"
    )


def test_utilization_report_reports_cohort_of_exactly_five_with_real_counts(api):
    """PRD §3.9: "A cohort of exactly 5 is reported with real counts — the floor
    excludes only cohorts strictly below it."

    PRD §3.9: "Otherwise the entry reports `suppressed` as false with the real
    `participant_count` and `check_in_count` values."

    PRD §3.9: "`class_breakdown` contains one entry for each of `EMPLOYEE`,
    `DEPENDENT`, and `RETIREE`, in that order, and every entry always names its
    `member_class`."

    PRD §3.9: "`suppressed_cohort_count` reports how many of the three entries
    were suppressed, so the reader knows the breakdown is incomplete without
    being able to reconstruct what was hidden."

    Design: Corner/calculations/utilization_report_suppresses_cohorts_below_privacy_minimum
    """
    scenario = _setup_cohort_of_check_ins(5)

    report = validate_success(
        api.get_utilization_report(
            scenario["contract_id"],
            scenario["sponsor_headers"],
            params={"period_month": "2026-08"},
        )
    )

    assert report["eligible_member_count"] == 5, (
        f"five members were verified, got {report['eligible_member_count']}"
    )
    assert report["distinct_participants"] == 5, (
        f"all five members checked in, got {report['distinct_participants']}"
    )
    assert report["participation_rate_pct"] == 100, (
        "5 distinct participants against 5 eligible members is 100 percent, got "
        f"{report['participation_rate_pct']}"
    )
    assert report["target_variance_pct"] == 65, (
        f"100 achieved less a target of 35 is +65, got {report['target_variance_pct']}"
    )

    breakdown = report["class_breakdown"]
    assert [row["member_class"] for row in breakdown] == list(CLASS_ORDER), (
        "class_breakdown carries EMPLOYEE, DEPENDENT and RETIREE in that order, got "
        f"{[row.get('member_class') for row in breakdown]}"
    )

    employees = _breakdown_row(breakdown, "EMPLOYEE")
    assert employees["suppressed"] is False, (
        "a cohort of exactly 5 is at the floor and is reported with real counts, "
        f"got suppressed {employees['suppressed']!r}"
    )
    assert employees["participant_count"] == 5, (
        f"expected 5 distinct EMPLOYEE participants, got {employees['participant_count']}"
    )
    assert employees["check_in_count"] == 5, (
        f"expected 5 EMPLOYEE check-ins in the period, got {employees['check_in_count']}"
    )

    for member_class in ("DEPENDENT", "RETIREE"):
        row = _breakdown_row(breakdown, member_class)
        assert row["suppressed"] is True, (
            f"the empty {member_class} cohort is below the floor and must be "
            f"suppressed, got {row['suppressed']!r}"
        )
        assert row["participant_count"] is None and row["check_in_count"] is None, (
            f"a suppressed {member_class} cohort reports null counts, got "
            f"{row['participant_count']!r} / {row['check_in_count']!r}"
        )

    assert report["suppressed_cohort_count"] == 2, (
        "only DEPENDENT and RETIREE are suppressed, got "
        f"{report['suppressed_cohort_count']}"
    )
    assert "health_metrics_note" not in _keys_anywhere(report), (
        "health_metrics_note must never be projected into the utilization report"
    )


# ==========================================================================
# The wellness incentive streak threshold
# ==========================================================================
def test_incentive_award_has_no_streak_bonus_before_the_fourth_distinct_day(api):
    """PRD §3.7: "Separately, count the number of **distinct calendar dates** on
    which the member has a `COUNTED` record whose `check_in_utc` falls within the
    trailing seven days, **excluding today's date** — repeat visits on one day
    count once, and today's own visits do not feed the streak."

    PRD §3.7: "The uncapped candidate award is 10 points, plus a further 5 points
    when that distinct-prior-day count is 3 or more."

    PRD §3.7: "Then `points_awarded` is the smaller of the candidate and the
    headroom; `points_capped` is true exactly when the candidate exceeded the
    headroom; and `streak_bonus_applied` is true exactly when the
    distinct-prior-day count was 3 or more — note that the streak flag records
    whether the bonus was *earned*, so it stays true even on a record whose award
    was clipped to zero by the cap."

    PRD §3.7: "Finally the member's `incentive_points_balance` is increased by
    `points_awarded`."

    Design: Corner/calculations/incentive_streak_bonus_lands_on_the_fourth_distinct_day
    """
    scenario, member, records = _setup_daily_check_ins([5, 6, 7])

    prior_days = (0, 1, 2)
    for index, record in enumerate(records):
        assert_participation_record(record)
        assert record["points_awarded"] == 10, (
            f"the check-in on 2026-08-{5 + index:02d} sees {prior_days[index]} distinct "
            f"prior days and awards the base 10, got {record['points_awarded']}"
        )
        assert record["streak_bonus_applied"] is False, (
            f"{prior_days[index]} distinct prior days is below the "
            f"{THRESHOLDS['STREAK_MIN_PRIOR_DAYS']}-day streak threshold, got "
            f"streak_bonus_applied {record['streak_bonus_applied']!r}"
        )
        assert record["points_capped"] is False, (
            "the weekly ceiling is untouched by a running total of at most 30, got "
            f"points_capped {record['points_capped']!r}"
        )

    refreshed = scenarios.read_member(member["id"])
    assert refreshed["incentive_points_balance"] == 30, (
        "three bare base awards leave a balance of 30, got "
        f"{refreshed['incentive_points_balance']}"
    )

    items, _ = validate_paginated(
        api.list_participation_records(
            scenario["manager_headers"], params={"member_id": member["id"]}
        )
    )
    counted = sum(
        item["points_awarded"] for item in items if item["status"] == "COUNTED"
    )
    assert counted == 30, (
        "the balance always equals the sum of points_awarded over surviving "
        f"COUNTED records, got {counted}"
    )


def test_incentive_streak_bonus_lands_on_the_fourth_distinct_day(api):
    """PRD §3.7: "Separately, count the number of **distinct calendar dates** on
    which the member has a `COUNTED` record whose `check_in_utc` falls within the
    trailing seven days, **excluding today's date** — repeat visits on one day
    count once, and today's own visits do not feed the streak."

    PRD §3.7: "The uncapped candidate award is 10 points, plus a further 5 points
    when that distinct-prior-day count is 3 or more."

    PRD §3.7: "The remaining headroom is 60 points minus the points already
    earned this week, floored at 0."

    PRD §3.7: "Finally the member's `incentive_points_balance` is increased by
    `points_awarded`."

    Design: Corner/calculations/incentive_streak_bonus_lands_on_the_fourth_distinct_day
    """
    scenario, member, records = _setup_daily_check_ins([5, 6, 7, 8])

    for index, record in enumerate(records[:3]):
        assert record["points_awarded"] == 10, (
            f"the check-in on 2026-08-{5 + index:02d} awards the base 10, got "
            f"{record['points_awarded']}"
        )
        assert record["streak_bonus_applied"] is False, (
            f"the check-in on 2026-08-{5 + index:02d} sees fewer than "
            f"{THRESHOLDS['STREAK_MIN_PRIOR_DAYS']} distinct prior days, got "
            f"streak_bonus_applied {record['streak_bonus_applied']!r}"
        )

    fourth = records[3]
    assert_participation_record(fourth)
    assert fourth["points_awarded"] == 15, (
        "the 2026-08-08 check-in sees 3 distinct prior days and earns the streak "
        f"bonus for 15 points, got {fourth['points_awarded']}"
    )
    assert fourth["streak_bonus_applied"] is True, (
        "3 distinct prior days meets the streak threshold, got "
        f"{fourth['streak_bonus_applied']!r}"
    )
    assert fourth["points_capped"] is False, (
        "45 points inside the ISO week beginning Monday 2026-08-03 is below the "
        f"{THRESHOLDS['WEEKLY_POINTS_CAP']}-point weekly ceiling, got points_capped "
        f"{fourth['points_capped']!r}"
    )

    refreshed = scenarios.read_member(member["id"])
    assert refreshed["incentive_points_balance"] == 45, (
        "10 + 10 + 10 + 15 leaves a balance of 45, got "
        f"{refreshed['incentive_points_balance']}"
    )

    items, _ = validate_paginated(
        api.list_participation_records(
            scenario["manager_headers"], params={"member_id": member["id"]}
        )
    )
    counted = sum(
        item["points_awarded"] for item in items if item["status"] == "COUNTED"
    )
    assert counted == 45, (
        "the balance always equals the sum of points_awarded over surviving "
        f"COUNTED records, got {counted}"
    )


# ==========================================================================
# Nothing here is eventually consistent
# ==========================================================================
def test_contract_approval_is_readable_in_the_same_instant(api, operator_admin_headers):
    """PRD §3.1: "A `decision` of `APPROVE` moves the contract
    `PENDING_CLIENT_APPROVAL → ACTIVE`, stamps `approved_at` with the logical
    clock instant, and — because approval is the moment the site becomes operable
    — reopens every room of the contract that currently sits in `CLOSED` with
    `open_deficiency_count` equal to 0, moving each such room `CLOSED → OPEN`."

    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`, and
    it never falls back to real time."

    Design: Corner/consistency_model/contract_approval_and_rollups_are_readable_immediately
    """
    scenario = scenarios.setup_draft_contract()
    validate_success(
        api.submit_client_contract(scenario["contract_id"], operator_admin_headers)
    )

    approved = validate_success(
        api.client_decision(
            scenario["contract_id"], {"decision": "APPROVE"}, scenario["sponsor_headers"]
        )
    )

    assert approved["status"] == "ACTIVE", (
        f"the APPROVE response itself must already be ACTIVE, got {approved['status']}"
    )
    assert approved["approved_at"] is not None, (
        "approved_at is stamped by the approval itself, got None"
    )
    assert approved["approved_at"].startswith("2026-08-01T00:00:00"), (
        "approved_at carries the logical clock instant 2026-08-01T00:00:00Z, got "
        f"{approved['approved_at']!r}"
    )

    fetched = validate_success(
        api.get_client_contract(scenario["contract_id"], operator_admin_headers)
    )
    assert fetched["status"] == "ACTIVE", (
        "the very next read agrees with the approval response, got "
        f"{fetched['status']}"
    )
    assert fetched["approved_at"] == approved["approved_at"], (
        f"expected approved_at {approved['approved_at']!r} on the following read, got "
        f"{fetched['approved_at']!r}"
    )
    assert fetched["version"] == approved["version"], (
        f"expected version {approved['version']} on the following read, got "
        f"{fetched['version']} — no second request may be needed to see the effect"
    )


def test_member_verification_rollup_is_readable_on_the_next_contract_read(
    api, operator_admin_headers
):
    """PRD §3.6: "It increments the contract's `eligible_member_count` by 1 and
    leaves `access_status` completely untouched — verifying eligibility does not
    hand out a badge."

    PRD §2.9: "A contract's `eligible_member_count` always equals the number of
    that contract's members whose `eligibility_status` is `ELIGIBLE`."

    PRD §2.4: "Most records additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of the record — and `version`, an
    integer that starts at 1 when the record is created and increments by exactly
    1 on every mutation of that record, including mutations caused by a cascade
    originating elsewhere."

    PRD §2.3: "`total_count` is the number of rows matching the filters before
    pagination is applied, and `has_more` is true exactly when rows remain beyond
    the current page."

    Design: Corner/consistency_model/contract_approval_and_rollups_are_readable_immediately
    """
    scenario = scenarios.setup_active_contract()
    before = scenarios.read_contract(scenario["contract_id"])
    assert before["eligible_member_count"] == 0, (
        "no member exists yet, so the rollup reads 0, got "
        f"{before['eligible_member_count']}"
    )

    member = scenarios.enrol_member(scenario)
    verified = scenarios.verify_member(scenario, member["id"])
    assert verified["eligibility_status"] == "ELIGIBLE", (
        f"VERIFY makes the member ELIGIBLE, got {verified['eligibility_status']}"
    )
    assert verified["access_status"] == "NO_BADGE", (
        "verifying eligibility hands out no badge, got "
        f"{verified['access_status']}"
    )

    after = validate_success(
        api.get_client_contract(scenario["contract_id"], operator_admin_headers)
    )
    assert after["eligible_member_count"] == 1, (
        "the verification is reflected in the parent contract on the very next "
        f"read, got {after['eligible_member_count']}"
    )
    assert after["version"] > before["version"], (
        f"the rollup movement is a mutation of the contract, so its version must "
        f"advance past {before['version']}, got {after['version']}"
    )

    _, meta = validate_paginated(
        api.list_members(
            operator_admin_headers,
            params={
                "contract_id": scenario["contract_id"],
                "eligibility_status": "ELIGIBLE",
            },
        )
    )
    assert meta["total_count"] == 1, (
        "the eligible population is visible in the same instant, got "
        f"{meta['total_count']}"
    )
