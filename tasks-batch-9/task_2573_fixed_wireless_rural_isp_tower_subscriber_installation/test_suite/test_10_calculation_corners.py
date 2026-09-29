"""Corner cases of the pinned calculations: path geometry, lease escalation,
sector ranking, metered cycles, equipment settlement and service-level credits.

Every expectation below is derived from PRD.md alone. Money is compared as whole
integer cents (PRD 2.9), percentages and ratios as three-decimal values, heights
and traffic volumes as one-decimal values.

The harness restarts the server and empties the database before every test, so
each test builds the whole plant it needs from scratch and the logical clock
starts at its documented reading of 2026-08-01T00:00:00Z (PRD 2.4).
"""

import pytest

from test_helpers import (
    CREDIT_PREPARER_HEADERS,
    FIELD_TECH,
    FINANCE_APPROVER,
    SURVEY_PRESETS,
    activate_sector,
    api_client,
    assert_equipment_assignment,
    assert_outage_credit,
    assert_serviceability_request,
    assert_usage_record,
    cancel_subscriber,
    close_outage,
    complete_work_order,
    create_outage,
    create_outage_credit_payload,
    create_sector,
    create_serviceability_request,
    create_tower,
    get_assignment_for_subscriber,
    get_credit,
    get_outage,
    get_sector,
    get_subscriber,
    get_success_data,
    hold_for_request,
    ingest_usage,
    iso_shift,
    prepare_credit,
    set_clock,
    setup_active_plant,
    setup_scheduled_work_order,
    survey_work_order,
    validate_success,
)

# --------------------------------------------------------------------------
# Local composites. These build only from the shared Tier-0 helpers.
# --------------------------------------------------------------------------


def _instant(value):
    """The instant of a timestamp, without pinning a fractional-second form."""
    return value.replace("Z", "").split(".")[0]


def _setup_installed_account(
    installed_at="2026-08-02T00:00:00Z", plan_overrides=None, equipment_mode="RENTAL"
):
    """Drive one account all the way to ACTIVE with the install completed at a
    chosen logical instant.

    PRD 3.7 sets `cycle_start_date` "to the calendar date of that same instant",
    so completing at 2026-08-02T00:00:00Z opens the first cycle on 2026-08-02.
    """
    scenario = setup_scheduled_work_order(
        equipment_mode=equipment_mode, plan_overrides=plan_overrides or {}
    )
    survey_work_order(
        scenario["work_order"]["id"], **SURVEY_PRESETS["NON_PEN_ROOF_TRIPOD"]
    )
    set_clock(installed_at)
    scenario["work_order"] = complete_work_order(
        scenario["work_order"]["id"], installed_mast_height_m=2.5
    )
    scenario["subscriber"] = get_subscriber(scenario["subscriber"]["id"])
    scenario["assignment"] = get_assignment_for_subscriber(scenario["subscriber"]["id"])
    return scenario


def _closed_outage(
    tower_id,
    started_at,
    minutes,
    cause="POWER",
    peak_wind_mph=None,
    planned_notice_days=None,
):
    """Open an outage and close it exactly `minutes` later on the same tower."""
    overrides = {"cause": cause, "started_at": started_at}
    if planned_notice_days is not None:
        overrides["planned_notice_days"] = planned_notice_days
    outage = create_outage(tower_id, **overrides)
    return close_outage(
        outage["id"],
        ended_at=iso_shift(started_at, minutes=minutes),
        peak_wind_mph=peak_wind_mph,
    )


# --------------------------------------------------------------------------
# Desktop path study: the far, partially obstructed premise
# --------------------------------------------------------------------------


def test_partial_obstruction_at_nine_km_still_qualifies_on_the_ground_pole_band():
    """PRD 3.5: "A Fresnel clearance requirement is then read off the link length.
    The band boundaries are half-open on the lower side and inclusive on the
    upper: a `path_distance_km` at or below 3.0 requires 1.5 metres of clearance;
    strictly above 3.0 and at or below 8.0 requires 3.0 metres; strictly above 8.0
    and at or below 15.0 requires 4.5 metres. A partially obstructed path buys an
    extra allowance: when the enquiry's `obstruction_class` is `PARTIAL`, a further
    1.0 metre is added."
    PRD 3.5: "On top of the clearance and the partial-path allowance, a
    fixed safety margin of 0.5 metres is always added."

    PRD 3.5: "The rounded mast requirement selects a mounting band, with every
    upper bound inclusive: at or below 1.0 metre a `WALL_BRACKET`; above that and
    at or below 3.0 metres a `NON_PEN_ROOF_TRIPOD`; above that and at or below 6.0
    metres a `ROOF_MAST_GUYED`; above that and at or below 12.0 metres a
    `GROUND_POLE_MAST`."

    PRD 3.5: "When at least one sector is eligible, the top-ranked one becomes the
    enquiry's `qualified_sector_id`, the enquiry moves `EVALUATING → QUALIFIED`,
    and `qualification_expires_at` is set to the current logical clock advanced by
    the qualification validity of 30 days."

    Design: Corner/calculations/partial_obstruction_at_nine_km_qualifies_on_the_ground_pole_band
    """
    plant = setup_active_plant()

    request = create_serviceability_request(
        plant["tower"]["id"],
        plant["plan"]["id"],
        contact_name="Ike Farrow",
        premise_latitude=41.31,
        premise_longitude=-104.71,
        premise_ground_elevation_m=1180.0,
        roof_height_m=5.0,
        declared_tree_line_height_m=8.0,
        obstruction_class="PARTIAL",
        path_distance_km=9.0,
    )

    assert_serviceability_request(request)
    # Obstruction top 1180.0 + 8.0 = 1188.0; required antenna height above mean
    # sea level 1188.0 + 4.5 + 1.0 + 0.5 = 1194.0; tower antenna 1200.0 + 45.0.
    assert request["desktop_los_margin_m"] == 51.0
    # Mounting surface 1180.0 + 5.0 = 1185.0, so the raw mast requirement is
    # 1194.0 - 1185.0 = 9.0, already an exact multiple of half a metre.
    assert request["desktop_required_mast_height_m"] == 9.0
    assert request["desktop_mounting_type"] == "GROUND_POLE_MAST"
    assert request["status"] == "QUALIFIED"
    assert request.get("denial_reason") is None
    assert request["qualified_sector_id"] == plant["sector"]["id"]
    assert _instant(request["qualification_expires_at"]) == "2026-08-31T00:00:00"


# --------------------------------------------------------------------------
# Sector ranking: ratio first, azimuth second, creation order last
# --------------------------------------------------------------------------


def _setup_two_active_sectors():
    """One ACTIVE tower carrying two ACTIVE sectors, the azimuth 210.0 sector
    created first and the azimuth 90.0 sector created second."""
    plant = setup_active_plant(sector_overrides={"azimuth_deg": 210.0, "channel_center_mhz": 3575.0})
    second = create_sector(
        plant["tower"]["id"],
        plant["license"]["id"],
        azimuth_deg=90.0,
        channel_center_mhz=3555.0,
    )
    plant["sector_z"] = plant["sector"]
    plant["sector_y"] = activate_sector(second["id"])
    return plant


def test_sector_ranking_breaks_an_equal_ratio_tie_on_azimuth_not_creation_order():
    """PRD 3.5: "Eligible sectors are ranked by `oversubscription_ratio`
    ascending — the emptiest sector wins — then by `azimuth_deg` ascending, then by
    `created_at` ascending. The sector's `id` is **never** consulted as a
    tie-break, so two sectors identical on all three keys must still be separated
    by the declared ordering and not by identifier order."

    PRD 3.3: "`committed_mbps` is simply `sold_mbps` plus `held_mbps`, and
    `oversubscription_ratio` is `committed_mbps` divided by `capacity_mbps`,
    rounded half up to three decimal places."

    Design: Corner/calculations/sector_selection_ranks_by_ratio_then_azimuth_and_never_by_creation_order
    """
    plant = _setup_two_active_sectors()

    assert get_sector(plant["sector_z"]["id"])["oversubscription_ratio"] == 0.0
    assert get_sector(plant["sector_y"]["id"])["oversubscription_ratio"] == 0.0

    request = create_serviceability_request(plant["tower"]["id"], plant["plan"]["id"])

    assert request["status"] == "QUALIFIED"
    assert request["qualified_sector_id"] == plant["sector_y"]["id"]


def test_sector_ranking_puts_the_emptier_ratio_ahead_of_the_lower_azimuth():
    """PRD 3.5: "Eligible sectors are ranked by `oversubscription_ratio`
    ascending — the emptiest sector wins — then by `azimuth_deg` ascending, then by
    `created_at` ascending."

    PRD 3.6: "A successful reservation opens in `HELD` `status` with `origin`
    `DIRECT`, no `release_reason`, and an `expires_at` set to the current logical
    clock advanced by `hold_days` days. Its side effects on the sector are
    immediate: `held_mbps` rises by the reserved amount, `committed_mbps`,
    `oversubscription_ratio`, `remaining_allowance_mbps` and `capacity_posture` are
    all recomputed, and the sector's `version` is incremented — which invalidates any
    other caller's `expected_sector_version` and forces them to re-read."

    Design: Corner/calculations/sector_selection_ranks_by_ratio_then_azimuth_and_never_by_creation_order
    """
    plant = _setup_two_active_sectors()

    first = create_serviceability_request(plant["tower"]["id"], plant["plan"]["id"])
    assert first["qualified_sector_id"] == plant["sector_y"]["id"]
    hold_for_request(first["id"])

    loaded = get_sector(plant["sector_y"]["id"])
    assert loaded["held_mbps"] == 50
    assert loaded["sold_mbps"] == 0
    assert loaded["committed_mbps"] == 50
    assert loaded["oversubscription_ratio"] == 2.0
    assert loaded["capacity_posture"] == "OPEN"

    second = create_serviceability_request(
        plant["tower"]["id"],
        plant["plan"]["id"],
        contact_name="Omar Vance",
        premise_latitude=41.245,
        premise_longitude=-104.79,
    )

    assert second["status"] == "QUALIFIED"
    assert second["qualified_sector_id"] == plant["sector_z"]["id"]


# --------------------------------------------------------------------------
# Ground lease: the committed total is a whole-lease figure
# --------------------------------------------------------------------------


def test_lease_schedule_projects_the_whole_term_before_any_anniversary_has_passed():
    """PRD 3.1: "It reports the `tower_id` it describes, `years_elapsed` as the
    count of anniversaries at or before the clock, `current_monthly_rent_cents`,
    `next_anniversary_date` as `lease_start_date` advanced by one more year than
    have elapsed, and `total_committed_cents`. The committed total sums, over every
    lease year from year zero through the final year of the term — that is, over
    `lease_term_months` divided by twelve years — that year's escalated monthly
    rent multiplied by twelve. Note that the total is a whole-lease figure and does
    not depend on where the clock sits, whereas `current_monthly_rent_cents` and
    `next_anniversary_date` do."

    PRD 3.1: "The rent for lease year zero is `lease_monthly_base_rent_cents`
    exactly. The rent for each subsequent lease year is the previous year's rent
    multiplied by one plus `lease_escalator_pct`, rounded half up to whole cents.
    Crucially, each year compounds on the **already-rounded** rent of the year
    before, not on a full-precision running value."

    Design: Corner/calculations/lease_projection_is_independent_of_how_many_anniversaries_have_passed
    """
    tower = create_tower(
        lease_landowner_name="Kestrel Land Co",
        lease_monthly_base_rent_cents=45000,
        lease_escalator_pct=0.0275,
        lease_start_date="2026-07-01",
        lease_term_months=60,
    )

    schedule = get_success_data(
        api_client.get_lease_schedule(tower["id"], FINANCE_APPROVER)
    )

    assert schedule["tower_id"] == tower["id"]
    assert schedule["years_elapsed"] == 0
    assert schedule["current_monthly_rent_cents"] == 45000
    assert schedule["next_anniversary_date"] == "2027-07-01"
    # 12 * (45000 + 46238 + 47510 + 48817 + 50159), each year compounding on the
    # already-rounded rent of the year before.
    assert schedule["total_committed_cents"] == 2852688


# --------------------------------------------------------------------------
# Metered cycles: the replay is ordered by usage_date, not by arrival
# --------------------------------------------------------------------------


def test_out_of_order_ingest_deprioritizes_on_the_day_that_crosses_the_soft_cap():
    """PRD 3.8: "Take every metered day of the account whose `usage_date` lies in
    the half-open window running from `cycle_start_date` up to but not including
    `cycle_start_date` plus 30 days, and process them in order of `usage_date`
    ascending and then `ingest_sequence` ascending. Starting from zero, for each
    record in turn add that record's `downstream_gb` and `upstream_gb` to the
    running total and round the running total half up to one decimal place
    **before moving to the next record**."

    PRD 3.8: "Each record is stamped with an `ingest_sequence` from a system
    counter that increases by one per record ingested, which fixes the processing
    order when two records share a `usage_date`, and its `total_gb` is derived as
    `downstream_gb` plus `upstream_gb` to one decimal place."

    PRD 3.8: "The cycle is breached when `cycle_usage_gb` is **strictly greater**
    than the plan's `soft_cap_gb`; usage landing exactly on the cap is not a
    breach."

    PRD 3.8: "The transition stamps `deprioritized_at` with the current logical
    clock and recomputes `effective_downstream_mbps`."

    Design: Corner/calculations/usage_replay_deprioritizes_on_the_ingest_that_crosses_the_cap_even_out_of_order
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]
    assert scenario["subscriber"]["cycle_start_date"] == "2026-08-02"

    set_clock("2026-08-06T00:00:00Z")

    later_day = ingest_usage(subscriber_id, "2026-08-05", 400.0, upstream_gb=0.0)
    assert_usage_record(later_day)
    assert later_day["ingest_sequence"] == 1
    assert later_day["in_current_cycle"] is True
    assert later_day["total_gb"] == 400.0

    after_first = get_subscriber(subscriber_id)
    assert after_first["cycle_usage_gb"] == 400.0
    assert after_first["usage_priority"] == "STANDARD"
    assert after_first["effective_downstream_mbps"] == 50
    assert after_first.get("deprioritized_at") is None

    earlier_day = ingest_usage(subscriber_id, "2026-08-03", 250.0, upstream_gb=0.0)
    assert earlier_day["ingest_sequence"] == 2

    after_second = get_subscriber(subscriber_id)
    # Replayed as 2026-08-03 (250.0) then 2026-08-05 (400.0) whatever the arrival
    # order, so the running total is 650.0 and strictly above the 600.0 cap.
    assert after_second["cycle_usage_gb"] == 650.0
    assert after_second["usage_priority"] == "DEPRIORITIZED"
    assert after_second["effective_downstream_mbps"] == 12.5
    assert _instant(after_second["deprioritized_at"]) == "2026-08-06T00:00:00"
    assert after_second["consecutive_breach_cycles"] == 0
    assert after_second["sticky_deprioritization_active"] is False


# --------------------------------------------------------------------------
# Service-level credits: the SLA_SHORTFALL arithmetic
# --------------------------------------------------------------------------


def test_shortfall_credit_rounds_uptime_and_shortfall_half_up_to_three_decimals():
    """PRD 3.9: "`measured_uptime_pct` is 100 multiplied by the shortfall-free
    share of the month — that is, the standard monthly allowance of 43200 minutes
    less `cycle_outage_minutes`, divided by 43200 — rounded half up to three
    decimal places. `shortfall_pct` is the plan's `sla_uptime_pct` less
    `measured_uptime_pct`, floored at zero, rounded half up to three decimal
    places. The cycle's gross entitlement is the plan's `monthly_price_cents`
    multiplied by `shortfall_pct`, divided by 100, multiplied by the shortfall
    multiplier of 10, rounded half up to whole cents, and then limited to the
    monthly cap."

    PRD 3.9: "A monthly cap is also formed: 50 percent of the plan's
    `monthly_price_cents` with any fractional cent discarded downward, so a
    6999-cent plan caps at 3499 rather than 3500."

    PRD 3.9: "Only when none of the three holds is the credit created `PENDING`
    with `credit_cents` strictly above zero, `approved_by_user_id` and
    `reversal_reason` absent."

    PRD 3.9: "`credit_balance_cents` is at all times the sum of `credit_cents`
    over the account's credits in `APPLIED` status, and an outage's
    `total_credited_cents` is the sum over its own `APPLIED` credits; both
    therefore exclude `PENDING`, `DENIED` and `REVERSED` rows."

    Design: Corner/calculations/outage_credit_rounds_uptime_and_shortfall_to_three_decimals
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]

    set_clock("2026-08-06T00:00:00Z")
    outage = _closed_outage(
        scenario["tower"]["id"], "2026-08-05T00:00:00Z", 1269, cause="POWER"
    )
    assert outage["duration_minutes"] == 1269
    assert outage["sla_excluded"] is False

    response = api_client.create_outage_credit(
        create_outage_credit_payload(outage["id"], subscriber_id),
        CREDIT_PREPARER_HEADERS,
    )
    credit = validate_success(response, 201)

    assert_outage_credit(credit)
    assert credit["method"] == "SLA_SHORTFALL"
    assert credit["cycle_outage_minutes"] == 1269
    # 100 * (43200 - 1269) / 43200 = 97.0625, which rounds HALF UP to 97.063.
    assert credit["measured_uptime_pct"] == 97.063
    assert credit["shortfall_pct"] == 2.437
    assert credit["prior_cycle_credited_cents"] == 0
    # round_half_up(6999 * 2.437 / 100 * 10) = 1706, well under the 3499 cap.
    assert credit["credit_cents"] == 1706
    assert credit["status"] == "PENDING"
    assert credit.get("denial_reason") is None
    assert credit.get("approved_by_user_id") is None

    assert get_subscriber(subscriber_id)["credit_balance_cents"] == 0
    assert get_outage(outage["id"])["total_credited_cents"] == 0


def test_second_shortfall_credit_in_one_cycle_nets_out_the_prior_credit():
    """PRD 3.9: "`cycle_outage_minutes` is the sum of creditable minutes over
    **every** `CLOSED` outage on the account's tower, not merely the one named in
    the request."

    PRD 3.9: "Because the account may already have been credited for other
    outages in the same cycle, `prior_cycle_credited_cents` is the sum of
    `credit_cents` over every **other** credit for the same account whose `status`
    is `PENDING` or `APPLIED` and whose outage intersects the same cycle window;
    credits in `DENIED` or `REVERSED` status never count. `credit_cents` is the
    gross entitlement less that prior total, floored at zero. Note the precision
    discipline: all the cycle's minutes are aggregated first and the money is
    rounded **once** at the end, before the prior total is subtracted — rounding
    each outage's contribution separately would give a different answer."

    PRD 3.9: "Because `credit_cents` is fixed at preparation and is **never**
    recomputed afterwards — not by a later cycle close, not by a further outage,
    not by a plan change — a reversal returns `credit_balance_cents` and
    `total_credited_cents` to exactly the values they held before the application,
    to the cent."

    Design: Corner/calculations/second_credit_in_one_cycle_nets_out_the_prior_credit
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]
    tower_id = scenario["tower"]["id"]

    set_clock("2026-08-06T00:00:00Z")
    first_outage = _closed_outage(tower_id, "2026-08-05T00:00:00Z", 1269, cause="POWER")
    first_credit = prepare_credit(first_outage["id"], subscriber_id)
    assert first_credit["credit_cents"] == 1706
    assert first_credit["status"] == "PENDING"

    set_clock("2026-08-11T00:00:00Z")
    second_outage = _closed_outage(
        tower_id, "2026-08-10T00:00:00Z", 600, cause="BACKHAUL"
    )

    response = api_client.create_outage_credit(
        create_outage_credit_payload(second_outage["id"], subscriber_id),
        CREDIT_PREPARER_HEADERS,
    )
    second_credit = validate_success(response, 201)

    assert_outage_credit(second_credit)
    # 1269 + 600 minutes are aggregated first: uptime 95.674, shortfall 3.826 and
    # a cycle-wide gross of 2678 cents.
    assert second_credit["cycle_outage_minutes"] == 1869
    assert second_credit["measured_uptime_pct"] == 95.674
    assert second_credit["shortfall_pct"] == 3.826
    assert second_credit["prior_cycle_credited_cents"] == 1706
    assert second_credit["credit_cents"] == 972
    assert second_credit["status"] == "PENDING"
    assert second_credit.get("denial_reason") is None

    # The first credit is never recomputed by the second preparation.
    assert get_credit(first_credit["id"])["credit_cents"] == 1706
    assert first_credit["credit_cents"] + second_credit["credit_cents"] == 2678


def test_per_incident_plan_prices_the_named_outage_pro_rata_with_no_uptime_target():
    """PRD 3.9: "**The `PER_INCIDENT` method** compensates strictly for the outage
    named in the request. `cycle_outage_minutes` is that single outage's creditable
    minutes. `measured_uptime_pct` and `shortfall_pct` are both recorded as 0.0 and
    `prior_cycle_credited_cents` as zero, because none of the three has any meaning
    under this method — they are reported for structural uniformity, not as
    measurements. `credit_cents` is the plan's `monthly_price_cents` multiplied by
    those creditable minutes, divided by the monthly allowance of 43200 minutes,
    rounded half up to whole cents, and then limited to the same monthly cap."

    PRD 3.9: "The credit records `prepared_by_user_id` as the preparing
    administrator's identifier and copies its `method` from the plan's
    `sla_credit_method`, which selects between the two computations below."

    Design: Corner/calculations/per_incident_plan_selects_the_pro_rata_variant_with_no_uptime_target
    """
    scenario = _setup_installed_account(
        plan_overrides={"tier_code": "PIN50", "sla_credit_method": "PER_INCIDENT"}
    )
    subscriber_id = scenario["subscriber"]["id"]

    set_clock("2026-08-06T00:00:00Z")
    outage = _closed_outage(
        scenario["tower"]["id"], "2026-08-05T00:00:00Z", 1269, cause="POWER"
    )

    response = api_client.create_outage_credit(
        create_outage_credit_payload(outage["id"], subscriber_id),
        CREDIT_PREPARER_HEADERS,
    )
    credit = validate_success(response, 201)

    assert_outage_credit(credit)
    assert credit["method"] == "PER_INCIDENT"
    assert credit["cycle_outage_minutes"] == 1269
    assert credit["measured_uptime_pct"] == 0.0
    assert credit["shortfall_pct"] == 0.0
    assert credit["prior_cycle_credited_cents"] == 0
    # round_half_up(6999 * 1269 / 43200) = 206, far below the floor(6999 * 0.5)
    # monthly cap of 3499.
    assert credit["credit_cents"] == 206
    assert credit["status"] == "PENDING"
    assert credit.get("denial_reason") is None


# --------------------------------------------------------------------------
# Service-level exclusions: every constant is inclusive at its boundary
# --------------------------------------------------------------------------


def test_wind_outage_at_exactly_fifty_eight_mph_is_excluded_and_the_credit_is_denied():
    """PRD 3.9: "A `WEATHER_WIND` outage is excluded when `peak_wind_mph` — treated
    as 0.0 when it was never supplied — is at or above 58.0 miles per hour."

    PRD 3.9: "**Denial is decided in a pinned order** and, unlike everything else
    in this product, a denial is not an error: the credit record is created
    successfully with `credit_cents` at zero and a `denial_reason`. The first
    condition that holds wins: 1. the outage named in the request is `sla_excluded`
    — `denial_reason` is `SLA_EXCLUDED`;"

    PRD 3.9: "A denied credit is created directly in `DENIED` status, which is
    terminal; `PENDING` is never observable for it."

    Design: Corner/calculations/sla_exception_constants_are_applied_at_their_exact_boundaries
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]

    set_clock("2026-08-06T00:00:00Z")
    outage = _closed_outage(
        scenario["tower"]["id"],
        "2026-08-03T00:00:00Z",
        300,
        cause="WEATHER_WIND",
        peak_wind_mph=58.0,
    )
    assert outage["duration_minutes"] == 300
    assert outage["sla_excluded"] is True

    response = api_client.create_outage_credit(
        create_outage_credit_payload(outage["id"], subscriber_id),
        CREDIT_PREPARER_HEADERS,
    )
    credit = validate_success(response, 201)

    assert_outage_credit(credit)
    assert credit["status"] == "DENIED"
    assert credit["denial_reason"] == "SLA_EXCLUDED"
    assert credit["credit_cents"] == 0
    assert get_subscriber(subscriber_id)["credit_balance_cents"] == 0
    assert get_outage(outage["id"])["total_credited_cents"] == 0


def test_planned_maintenance_with_exactly_seven_days_notice_is_excluded():
    """PRD 3.9: "A `PLANNED_MAINTENANCE` outage is excluded when
    `planned_notice_days` — treated as zero when it was never supplied — is at or
    above 7 days, so short-notice maintenance is **not** excluded and does attract
    credits."

    PRD 3.9: "**Denial is decided in a pinned order** and, unlike everything else
    in this product, a denial is not an error: the credit record is created
    successfully with `credit_cents` at zero and a `denial_reason`. The first
    condition that holds wins: 1. the outage named in the request is `sla_excluded`
    — `denial_reason` is `SLA_EXCLUDED`;"

    Design: Corner/calculations/sla_exception_constants_are_applied_at_their_exact_boundaries
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]

    set_clock("2026-08-06T00:00:00Z")
    outage = _closed_outage(
        scenario["tower"]["id"],
        "2026-08-04T00:00:00Z",
        180,
        cause="PLANNED_MAINTENANCE",
        planned_notice_days=7,
    )
    assert outage["duration_minutes"] == 180
    assert outage["sla_excluded"] is True

    response = api_client.create_outage_credit(
        create_outage_credit_payload(outage["id"], subscriber_id),
        CREDIT_PREPARER_HEADERS,
    )
    credit = validate_success(response, 201)

    assert_outage_credit(credit)
    assert credit["status"] == "DENIED"
    assert credit["denial_reason"] == "SLA_EXCLUDED"
    assert credit["credit_cents"] == 0


@pytest.mark.parametrize(
    "minutes,expected_denial_reason,expected_cycle_minutes",
    [
        (59, "BELOW_MINIMUM_DURATION", 0),
        (60, "NO_SHORTFALL", 60),
    ],
)
def test_sixty_minute_minimum_is_inclusive_and_decides_which_denial_rung_fires(
    minutes, expected_denial_reason, expected_cycle_minutes
):
    """PRD 3.9: "Its creditable minutes are zero when the outage is `sla_excluded`,
    or when its `status` is not `CLOSED`, or when its clipped minutes fall short of
    the 60-minute minimum; otherwise its creditable minutes equal its clipped
    minutes."

    PRD 3.9: "A `POWER`, `BACKHAUL` or `EQUIPMENT` outage is never excluded; those
    are the operator's own plant."

    PRD 3.9: "The first condition that holds wins: 1. the outage named in the
    request is `sla_excluded` — `denial_reason` is `SLA_EXCLUDED`; 2. that outage's
    clipped minutes fall short of the 60-minute minimum — `denial_reason` is
    `BELOW_MINIMUM_DURATION`; 3. the computed `credit_cents` is zero —
    `denial_reason` is `NO_SHORTFALL`."

    PRD 3.9: "`shortfall_pct` is the plan's `sla_uptime_pct` less
    `measured_uptime_pct`, floored at zero, rounded half up to three decimal
    places."

    Design: Corner/calculations/sla_exception_constants_are_applied_at_their_exact_boundaries
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]

    set_clock("2026-08-06T00:00:00Z")
    outage = _closed_outage(
        scenario["tower"]["id"], "2026-08-05T00:00:00Z", minutes, cause="POWER"
    )
    assert outage["duration_minutes"] == minutes
    assert outage["sla_excluded"] is False

    response = api_client.create_outage_credit(
        create_outage_credit_payload(outage["id"], subscriber_id),
        CREDIT_PREPARER_HEADERS,
    )
    credit = validate_success(response, 201)

    assert_outage_credit(credit)
    assert credit["status"] == "DENIED"
    assert credit["denial_reason"] == expected_denial_reason
    assert credit["credit_cents"] == 0
    assert credit["cycle_outage_minutes"] == expected_cycle_minutes
    assert get_subscriber(subscriber_id)["credit_balance_cents"] == 0


# --------------------------------------------------------------------------
# Service-level credits: what the cycle window admits
# --------------------------------------------------------------------------


def test_cycle_credit_clips_a_straddling_outage_and_ignores_an_open_one():
    """PRD 3.9: "The measurement window is the account's own current cycle: from
    `cycle_start_date` inclusive to `cycle_start_date` plus 30 days exclusive. For
    any outage, its clipped minutes are the whole minutes of its half-open interval
    that fall inside that window, with any fractional minute discarded — an outage
    straddling a cycle boundary contributes only the part inside. Its creditable
    minutes are zero when the outage is `sla_excluded`, or when its `status` is not
    `CLOSED`, or when its clipped minutes fall short of the 60-minute minimum;
    otherwise its creditable minutes equal its clipped minutes."

    PRD 3.9: "`cycle_outage_minutes` is the sum of creditable minutes over
    **every** `CLOSED` outage on the account's tower, not merely the one named in
    the request."

    PRD 3.9: "The outage opens in `OPEN` `status` with `ended_at`,
    `peak_wind_mph` and `duration_minutes` all absent, `sla_excluded` false and
    `total_credited_cents` zero."

    Design: Corner/calculations/cycle_credit_counts_only_closed_events_and_clips_them_to_the_cycle_window
    """
    scenario = _setup_installed_account()
    subscriber_id = scenario["subscriber"]["id"]
    tower_id = scenario["tower"]["id"]
    assert scenario["subscriber"]["cycle_start_date"] == "2026-08-02"

    set_clock("2026-08-08T00:00:00Z")

    # Straddles the cycle start: 240 real minutes, only the 120 from 2026-08-02T00:00
    # onwards fall inside the window.
    straddling = _closed_outage(tower_id, "2026-08-01T22:00:00Z", 240, cause="POWER")
    assert straddling["duration_minutes"] == 240

    credited = _closed_outage(tower_id, "2026-08-05T00:00:00Z", 1269, cause="POWER")
    assert credited["duration_minutes"] == 1269

    still_open = create_outage(
        tower_id, cause="EQUIPMENT", started_at="2026-08-07T00:00:00Z"
    )
    assert still_open["status"] == "OPEN"
    assert still_open.get("duration_minutes") is None

    response = api_client.create_outage_credit(
        create_outage_credit_payload(credited["id"], subscriber_id),
        CREDIT_PREPARER_HEADERS,
    )
    credit = validate_success(response, 201)

    assert_outage_credit(credit)
    # 120 clipped minutes plus 1269 in full; the OPEN event contributes nothing.
    assert credit["cycle_outage_minutes"] == 1389
    assert credit["measured_uptime_pct"] == 96.785
    assert credit["shortfall_pct"] == 2.715
    assert credit["credit_cents"] == 1900
    assert credit["status"] == "PENDING"
    assert credit.get("denial_reason") is None


# --------------------------------------------------------------------------
# Equipment settlement: the rental damage charge
# --------------------------------------------------------------------------


def test_damaged_rental_return_charges_half_the_replacement_cost():
    """PRD 3.8: "When the record is being returned with a `return_condition` of
    `DAMAGED`, `settlement_cents` is 50 percent of `replacement_cost_cents` rounded
    half up to whole cents, and `settlement_basis` is `RENTAL_DAMAGE`; the tenure is
    irrelevant to a damage charge."

    PRD 3.8: "On success it moves `RETURN_PENDING → RETURNED`, which is terminal,
    stamping `returned_at` from the logical clock and storing `return_condition`."

    PRD 3.8: "The account's `settlement_balance_cents` is the sum of
    `settlement_cents` over its equipment records whose `status` is `RETURNED`,
    `UNRETURNED_BILLED` or `VOIDED`. Records still in `ASSIGNED`, `DEPLOYED` or
    `RETURN_PENDING` contribute nothing, so the balance only ever reflects concluded
    hardware."

    PRD 3.8: "Cancelling from `ACTIVE` or `SUSPENDED` means the radio is on the
    customer's wall, so the equipment record moves `DEPLOYED → RETURN_PENDING`, its
    `return_due_at` is set to the logical clock advanced by the return window of 21
    days, and the account's `equipment_monthly_charge_cents` drops to zero because
    the rental has stopped accruing."

    Design: Corner/calculations/damaged_rental_return_charges_half_replacement_and_ignores_months_in_service
    """
    scenario = _setup_installed_account(equipment_mode="RENTAL")
    subscriber_id = scenario["subscriber"]["id"]
    assert scenario["assignment"]["status"] == "DEPLOYED"
    assert _instant(scenario["assignment"]["deployed_at"]) == "2026-08-02T00:00:00"
    assert scenario["assignment"]["replacement_cost_cents"] == 34900

    # Eight days on the wall, then the account is cancelled.
    set_clock("2026-08-10T00:00:00Z")
    cancel_subscriber(subscriber_id, reason="Customer moved out of the coverage area")
    pending = get_assignment_for_subscriber(subscriber_id)
    assert pending["status"] == "RETURN_PENDING"

    response = api_client.return_equipment(
        pending["id"], {"return_condition": "DAMAGED"}, FIELD_TECH
    )
    settled = validate_success(response, 200)

    assert_equipment_assignment(settled)
    assert settled["status"] == "RETURNED"
    assert _instant(settled["returned_at"]) == "2026-08-10T00:00:00"
    assert settled["return_condition"] == "DAMAGED"
    # 50 percent of the 34900-cent replacement cost, whatever the tenure.
    assert settled["settlement_cents"] == 17450
    assert settled["settlement_basis"] == "RENTAL_DAMAGE"

    account = get_subscriber(subscriber_id)
    assert account["settlement_balance_cents"] == 17450
    assert account["equipment_monthly_charge_cents"] == 0
