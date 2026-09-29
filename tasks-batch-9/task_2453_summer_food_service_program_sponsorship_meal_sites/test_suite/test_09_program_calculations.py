"""Program calculations end to end: the camp second-meal allowance floor, the finalized-day
filter behind a claim line item, the vended delivered-quantity reconciliation, the first-week
monitoring deadline, and the corrective-action severity ladder.

Every scenario is built from scratch against an empty database through PRD endpoints only.
"""

from test_helpers import (
    FIRST_WEEK_VISIT_DAYS,
    RATE_CENTS,
    RESPONSE_DAYS_BY_SEVERITY,
    SECOND_MEAL_ALLOWANCE_PCT,
    assert_claim_line_item,
    assert_corrective_action,
    assert_meal_claim,
    assert_meal_count_entry,
    assert_meal_service_day,
    assert_monitoring_visit,
    assert_site,
    assert_status,
    add_line_item,
    close_day,
    create_approved_site,
    create_approved_sponsor,
    create_draft_claim,
    create_finalized_day,
    create_meal_count_payload,
    create_open_day,
    create_satisfied_first_week_visit,
    create_reported_visit,
    finding,
    is_iso8601_timestamp,
    list_actions_for_site,
    make_field_monitor_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    meal_service,
    record_meal_count,
    schedule_visit,
    set_clock,
    setup_program_baseline,
    start_operating,
    submit_claim,
    validate_paginated,
    validate_success,
)

REVIEWER = make_state_agency_reviewer_headers()

# The rural/self-prep lunch rate of 470.50 fractional cents applied to 47 claimed lunches gives
# 22113.50, which the pinned half-up rounding turns into a single per-line value of 22114 cents.
LUNCH_LINE_VALUE_CENTS = 22_114

# The same rate against a vended site's 50 counted lunches (23525) and against the 40 that
# survive the delivered-quantity reconciliation (18820).
VENDED_UNCHECKED_MEALS_VALUE_CENTS = 23_525
VENDED_SURVIVING_MEALS_VALUE_CENTS = 18_820


# --- The camp second-meal allowance ------------------------------------------------------------


def _operating_camp_site():
    """An approved, operating CAMP site serving lunch: camps cite no area income record at all."""
    set_clock("2026-06-01T00:00:00Z")
    sponsor = create_approved_sponsor()
    site = create_approved_site(
        sponsor["id"],
        None,
        name="Camp Windridge",
        site_type="CAMP",
        production_mode="SELF_PREP",
        approved_meal_types=["LUNCH"],
        approved_max_attendance=200,
        is_rural=True,
    )
    set_clock("2026-06-08T08:00:00Z")
    return sponsor, site, start_operating(site)


def _camp_day_with_fifty_first_and_five_second_meals(site_id: str):
    """An OPEN camp day with 200 lunches produced, ready for the point-of-service count."""
    return create_open_day(
        site_id, "2026-06-08",
        meal_services=[meal_service(meal_type="LUNCH", planned_meals=200)],
        production_counts={"LUNCH": 200},
        food_received_at="2026-06-08T10:30:00Z",
    )


def test_camp_second_meal_entry_floors_the_two_percent_allowance_to_one_meal(api):
    """PRD §3.6: "Second, the second-meal rule: at a site whose `site_type` is `CAMP`,
    reimbursable second meals for that type are the lesser of the net second meals and 2 percent of
    the reimbursable first meals just computed, with that allowance floored to a whole meal; at
    every other site type, reimbursable second meals are zero, because second meals are never
    reimbursable off camp."

    Design: Corner/calculations/camp_second_meal_allowance_uses_two_percent_floor
    """
    _sponsor, approved_site, site = _operating_camp_site()
    assert_site(approved_site)
    assert approved_site["eligibility_basis"] == "CAMP_INDIVIDUAL", (
        "a CAMP site establishes eligibility child by child, so its basis must be CAMP_INDIVIDUAL, "
        f"got {approved_site['eligibility_basis']}"
    )
    assert approved_site.get("eligibility_pct_used") is None, (
        "the camp branch leaves eligibility_pct_used null, got "
        f"{approved_site.get('eligibility_pct_used')!r}"
    )

    day = _camp_day_with_fifty_first_and_five_second_meals(site["id"])

    entry = validate_success(
        api.create_meal_count(
            day["id"],
            create_meal_count_payload(
                meal_type="LUNCH", first_meals=50, second_meals=5, adult_meals=0
            ),
            make_site_supervisor_headers(site["id"]),
        ),
        201,
    )

    assert_meal_count_entry(entry)
    assert entry["reimbursable_first_meals"] == 50, (
        "all 50 first meals sit under the 200-meal attendance ceiling and the 200 meals produced, "
        f"so the entry must attribute 50 reimbursable first meals, got "
        f"{entry['reimbursable_first_meals']}"
    )
    assert entry["reimbursable_second_meals"] == 1, (
        f"the camp allowance of {SECOND_MEAL_ALLOWANCE_PCT} of 50 reimbursable first meals floors "
        f"to exactly 1 second meal, got {entry['reimbursable_second_meals']}"
    )
    assert entry["non_reimbursable_meals"] == 4, (
        "the entry's 55 counted meals less its 50 reimbursable first and 1 reimbursable second "
        f"meal leave 4 non-reimbursable, got {entry['non_reimbursable_meals']}"
    )


def test_camp_day_totals_conserve_the_floored_second_meal_allowance(api):
    """PRD §3.6: "The day's `reimbursable_meals` is the sum, across all meal types, of the
    reimbursable first meals plus the reimbursable second meals. Its `non_reimbursable_meals` is
    the conserved complement: the day's `counted_first_meals` plus `counted_second_meals` plus
    `counted_adult_meals`, less `reimbursable_meals`. And its `leftover_meals` is the total of all
    values in `production_counts`, less `counted_first_meals`, less `counted_second_meals`, less
    `counted_adult_meals`, less `discarded_meals`, with any negative result floored at 0."

    Design: Corner/calculations/camp_second_meal_allowance_uses_two_percent_floor
    """
    _sponsor, _approved_site, site = _operating_camp_site()
    day = _camp_day_with_fifty_first_and_five_second_meals(site["id"])
    record_meal_count(day, meal_type="LUNCH", first_meals=50, second_meals=5, adult_meals=0)

    day = validate_success(
        api.get_meal_service_day(day["id"], make_site_supervisor_headers(site["id"]))
    )

    assert_meal_service_day(day)
    assert day["counted_first_meals"] == 50, (
        f"the day publishes its net first meals, expected 50, got {day['counted_first_meals']}"
    )
    assert day["counted_second_meals"] == 5, (
        f"the day publishes its net second meals, expected 5, got {day['counted_second_meals']}"
    )
    assert day["counted_adult_meals"] == 0, (
        f"no adult meals were served, got {day['counted_adult_meals']}"
    )
    assert day["reimbursable_meals"] == 51, (
        "50 reimbursable first meals plus the single second meal the floored camp allowance "
        f"permits must publish 51 reimbursable meals, got {day['reimbursable_meals']}"
    )
    assert day["non_reimbursable_meals"] == 4, (
        "the conserved complement of 55 counted meals less 51 reimbursable must be 4, got "
        f"{day['non_reimbursable_meals']}"
    )
    assert day["leftover_meals"] == 145, (
        "200 meals produced less the 55 counted and nothing discarded must leave 145 leftover, "
        f"got {day['leftover_meals']}"
    )


# --- The finalized-day filter behind a claim line item -----------------------------------------


def _june_site_with_one_finalized_and_one_closed_day():
    """A rural SELF_PREP site with 47 finalized LUNCH first meals on 8 June and 20 merely closed
    LUNCH first meals on 9 June."""
    scenario = setup_program_baseline()
    site = scenario["site"]
    sponsor = scenario["sponsor"]

    create_finalized_day(site["id"], sponsor["id"], "2026-06-08", first_meals=47)

    set_clock("2026-06-09T08:00:00Z")
    closed_day = create_open_day(
        site["id"], "2026-06-09",
        meal_services=[meal_service(meal_type="LUNCH", planned_meals=150)],
        production_counts={"LUNCH": 150},
    )
    record_meal_count(closed_day, meal_type="LUNCH", first_meals=20)
    close_day(closed_day)

    set_clock("2026-07-06T09:00:00Z")
    claim = create_draft_claim(sponsor["id"], "2026-06")
    return scenario, claim


def test_line_item_aggregates_only_the_finalized_june_day(api):
    """PRD §3.8: "Its `claimed_first_meals_by_type` maps each meal type to the sum, over those
    finalized days taken in ascending `service_date`, of the reimbursable first meals the
    classification of §3.6 produced for that meal type, and `claimed_second_meals_by_type` does the
    same for reimbursable second meals. Days in `VOIDED`, `CLOSED`, `OPEN` or `PLANNED` never
    contribute a meal, which is why finalization is the gate that matters."

    Design: Corner/calculations/line_item_aggregates_only_finalized_days_in_claim_month
    """
    scenario, claim = _june_site_with_one_finalized_and_one_closed_day()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    line_item = validate_success(
        api.create_claim_line_item(
            claim["id"], {"site_id": scenario["site"]["id"]}, sponsor_headers
        ),
        201,
    )

    assert_claim_line_item(line_item)
    assert line_item["finalized_day_count"] == 1, (
        "only the 8 June day reached FINALIZED inside the claim month, so finalized_day_count must "
        f"be 1, got {line_item['finalized_day_count']}"
    )
    assert line_item["claimed_first_meals_by_type"].get("LUNCH") == 47, (
        "the finalized day's 47 reimbursable LUNCH first meals must be the whole LUNCH figure, got "
        f"{line_item['claimed_first_meals_by_type'].get('LUNCH')!r}"
    )
    assert sum(line_item["claimed_first_meals_by_type"].values()) == 47, (
        "the merely CLOSED day's 20 first meals must never enter the aggregate, so the total "
        f"claimed first meals must stay 47, got {line_item['claimed_first_meals_by_type']}"
    )
    assert sum(line_item["claimed_second_meals_by_type"].values()) == 0, (
        "second meals are not reimbursable at this OPEN site, so no second meals may be claimed, "
        f"got {line_item['claimed_second_meals_by_type']}"
    )


def test_new_line_item_opens_pending_at_the_rural_self_prep_lunch_rate(api):
    """PRD §3.8: "The new line starts with `edit_check_status` `PENDING`, `disallow_reason` `NONE`,
    `disallowed_counts_by_type` null, and `hold_flag` copied from the site's current `claim_hold`;
    adding it recomputes the claim's `meals_rate_value_cents` and its `blocking_hold_count`."

    Design: Corner/calculations/line_item_aggregates_only_finalized_days_in_claim_month
    """
    scenario, claim = _june_site_with_one_finalized_and_one_closed_day()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    line_item = validate_success(
        api.create_claim_line_item(
            claim["id"], {"site_id": scenario["site"]["id"]}, sponsor_headers
        ),
        201,
    )

    assert_claim_line_item(line_item)
    assert_status(line_item, "PENDING", field="edit_check_status")
    assert line_item["disallow_reason"] == "NONE", (
        f"a freshly added line carries no disallowance, got {line_item['disallow_reason']}"
    )
    assert line_item.get("disallowed_counts_by_type") is None, (
        "disallowed_counts_by_type opens null before any edit check has run, got "
        f"{line_item.get('disallowed_counts_by_type')!r}"
    )
    assert line_item["hold_flag"] is False, (
        "the site carries no claim hold, so the line's hold_flag must copy false, got "
        f"{line_item['hold_flag']}"
    )
    assert line_item["rate_class"] == "RURAL_OR_SELF_PREP", (
        "a rural SELF_PREP site earns the higher rate class, got " f"{line_item['rate_class']}"
    )
    assert line_item["meals_rate_value_cents"] == LUNCH_LINE_VALUE_CENTS, (
        f"47 claimed lunches at the {RATE_CENTS['RURAL_OR_SELF_PREP']['LUNCH']}-cent rural lunch "
        f"rate must round half-up to {LUNCH_LINE_VALUE_CENTS} cents on this line, got "
        f"{line_item['meals_rate_value_cents']}"
    )


# --- The vended delivered-quantity reconciliation -----------------------------------------------


def _submitted_vended_june_claim():
    """A rural VENDED site that counted 50 LUNCH first meals against 40 delivered, with a timely
    first-week visit, carried through to a SUBMITTED June claim."""
    scenario = setup_program_baseline(
        site_overrides={"production_mode": "VENDED", "name": "Riverbend Vended Park"}
    )
    site = scenario["site"]
    sponsor = scenario["sponsor"]

    day = create_finalized_day(
        site["id"], sponsor["id"], "2026-06-08", first_meals=50, planned_meals=40
    )
    visit = create_satisfied_first_week_visit(site["id"])

    set_clock("2026-07-06T09:00:00Z")
    claim = create_draft_claim(sponsor["id"], "2026-06")
    line_item = add_line_item(claim, site["id"])
    claim = submit_claim(
        claim, claimed_operating_cost_cents=30_000, claimed_admin_cost_cents=1_000
    )
    scenario.update({"day": day, "visit": visit, "claim": claim, "line_item": line_item})
    return scenario


def test_vended_line_item_disallows_meals_exceeding_delivered_production(api):
    """PRD §3.8: "This is where the delivered-quantity reconciliation deferred from §3.6 finally
    happens: for each finalized day and each meal type declared in that day's `meal_services`, the
    excess is the reimbursable first plus second meals of that type on that day, less the day's
    `production_counts` value for that type, with negatives floored at 0; those excesses accumulate
    into the disallowed count per meal type and into a running total."

    Design: Corner/calculations/vended_line_item_disallows_meals_exceeding_delivered_production
    """
    scenario = _submitted_vended_june_claim()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    checked = validate_success(api.edit_check_meal_claim(scenario["claim"]["id"], REVIEWER))

    assert_meal_claim(checked)
    assert_status(checked, "EDIT_CHECK_FAILED")
    assert checked["edit_check_failure_codes"] == ["EXCEEDS_PRODUCTION"], (
        "the only rule that fired is the vended production reconciliation, so the distinct failure "
        f"codes must read [\"EXCEEDS_PRODUCTION\"], got {checked['edit_check_failure_codes']}"
    )

    line_item = validate_success(
        api.get_claim_line_item(scenario["line_item"]["id"], sponsor_headers)
    )
    assert_claim_line_item(line_item)
    assert_status(line_item, "FAILED", field="edit_check_status")
    assert line_item["disallow_reason"] == "EXCEEDS_PRODUCTION", (
        "a vended line claiming more meals than were delivered must carry EXCEEDS_PRODUCTION, got "
        f"{line_item['disallow_reason']}"
    )
    assert sum(line_item["claimed_first_meals_by_type"].values()) == 50, (
        "the vended day applied no production cap when the meals were counted, so all 50 first "
        f"meals reached the line, got {line_item['claimed_first_meals_by_type']}"
    )
    assert line_item["disallowed_counts_by_type"] == {"LUNCH": 10}, (
        "50 reimbursable lunches less the 40 delivered leave an excess of 10 LUNCH meals, got "
        f"{line_item['disallowed_counts_by_type']}"
    )
    assert line_item["disallowed_meal_count"] == 10, (
        "the disallowed meal count totals the map's values, expected 10, got "
        f"{line_item['disallowed_meal_count']}"
    )
    assert line_item["meals_rate_value_cents"] == VENDED_SURVIVING_MEALS_VALUE_CENTS, (
        f"only 40 net meals survive at the {RATE_CENTS['RURAL_OR_SELF_PREP']['LUNCH']}-cent lunch "
        f"rate, expected {VENDED_SURVIVING_MEALS_VALUE_CENTS} cents, got "
        f"{line_item['meals_rate_value_cents']}"
    )


def test_vended_disallowance_reduces_final_reimbursement_but_not_the_preliminary_figure(api):
    """PRD §3.8: "Step one takes the claim's `meals_rate_value_cents`, recomputed with the
    disallowed counts subtracted. Step two produces the operating reimbursement as the lesser of
    that meals value and the claim's `claimed_operating_cost_cents`. Step three produces
    `admin_cap_cents` as 20 percent of **step two's output**, floored to whole cents. Step four
    produces the administrative reimbursement as the lesser of `claimed_admin_cost_cents` and that
    cap. Step five sums steps two and four into the gross figure that becomes
    `final_reimbursement_cents`."

    Design: Corner/calculations/vended_line_item_disallows_meals_exceeding_delivered_production
    """
    scenario = _submitted_vended_june_claim()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    assert scenario["claim"]["preliminary_reimbursement_cents"] == 24_525, (
        "the preliminary variant values all 50 counted lunches at 23525 cents and adds the 1000 "
        "asserted admin cost with no cap, expected 24525, got "
        f"{scenario['claim']['preliminary_reimbursement_cents']}"
    )

    checked = validate_success(api.edit_check_meal_claim(scenario["claim"]["id"], REVIEWER))

    assert_meal_claim(checked)
    assert checked["meals_rate_value_cents"] == VENDED_SURVIVING_MEALS_VALUE_CENTS, (
        "the claim's meals value must be recomputed from the 40 surviving meals, expected "
        f"{VENDED_SURVIVING_MEALS_VALUE_CENTS}, got {checked['meals_rate_value_cents']}"
    )
    assert checked["disallowed_meal_count"] == 10, (
        f"the claim must total the 10 disallowed meals, got {checked['disallowed_meal_count']}"
    )
    assert checked["final_reimbursement_cents"] == 19_820, (
        "step two clamps to the 18820 meals value and step four takes the 1000 claimed admin cost "
        "under its floored 3764-cent cap, expected 19820, got "
        f"{checked['final_reimbursement_cents']}"
    )
    assert checked["preliminary_reimbursement_cents"] == 24_525, (
        "the preliminary figure recorded at submission is not rewritten by the edit check, got "
        f"{checked['preliminary_reimbursement_cents']}"
    )

    summary = validate_success(api.get_reimbursement_summary(checked["id"], sponsor_headers))
    assert summary["meals_rate_value_cents"] == VENDED_SURVIVING_MEALS_VALUE_CENTS, (
        "the reimbursement summary must expose the same surviving meals value, expected "
        f"{VENDED_SURVIVING_MEALS_VALUE_CENTS}, got {summary['meals_rate_value_cents']}"
    )
    assert summary["operating_reimbursement_cents"] == VENDED_SURVIVING_MEALS_VALUE_CENTS, (
        "step two is the lesser of the 18820 meals value and the 30000 claimed operating cost, got "
        f"{summary['operating_reimbursement_cents']}"
    )
    assert summary["admin_cap_cents"] == 3_764, (
        "step three floors 20 percent of the 18820 operating reimbursement to 3764 cents, got "
        f"{summary['admin_cap_cents']}"
    )
    assert summary["admin_reimbursement_cents"] == 1_000, (
        "step four takes the lesser of the 1000 claimed admin cost and the 3764-cent cap, got "
        f"{summary['admin_reimbursement_cents']}"
    )
    assert VENDED_UNCHECKED_MEALS_VALUE_CENTS != checked["meals_rate_value_cents"], (
        "the unreconciled 23525-cent value of all 50 counted meals must not survive the vended "
        "delivered-quantity check"
    )


# --- The first-week monitoring deadline ---------------------------------------------------------


def test_first_week_visit_conducted_on_its_due_date_is_not_late(api):
    """PRD §3.7: "Otherwise, a `FIRST_WEEK` visit is due 4 days after `first_operating_date`, a
    `FULL_REVIEW` visit is due 28 days after `first_operating_date`, and a `FOLLOW_UP` visit is
    simply due on its own `scheduled_date`. Lateness is then read one of two ways depending on
    where the visit stands: a visit whose `status` is `CONDUCTED`, `REPORT_FILED` or `CLOSED` is
    late when the UTC calendar date of its `conducted_at` falls after its `due_date`, while a visit
    still `SCHEDULED` is late when the logical clock's current date has already passed its
    `due_date`. Both comparisons are inclusive of the deadline itself, so a visit conducted on the
    `due_date` is on time and only the following day makes it late."

    Design: Corner/calculations/first_week_visit_due_date_uses_four_day_constant_inclusively
    """
    scenario = setup_program_baseline()
    site = scenario["site"]

    create_open_day(site["id"], "2026-06-08")

    site_now = validate_success(api.get_site(site["id"], REVIEWER))
    assert_site(site_now)
    assert site_now["first_operating_date"] == "2026-06-08", (
        "the earliest service date ever opened anchors the monitoring clock, expected 2026-06-08, "
        f"got {site_now['first_operating_date']!r}"
    )

    visit = schedule_visit(
        site["id"], visit_type="FIRST_WEEK", scheduled_date="2026-06-12",
        window_start="09:00", window_end="11:00",
    )
    assert visit["due_date"] == "2026-06-12", (
        f"a FIRST_WEEK visit falls due {FIRST_WEEK_VISIT_DAYS} days after the 2026-06-08 first "
        f"operating date, expected 2026-06-12, got {visit['due_date']!r}"
    )

    set_clock("2026-06-12T09:00:00Z")
    conducted = validate_success(
        api.conduct_monitoring_visit(
            visit["id"], make_field_monitor_headers(visit["monitor_user_id"])
        )
    )

    assert_monitoring_visit(conducted)
    assert_status(conducted, "CONDUCTED")
    assert is_iso8601_timestamp(conducted["conducted_at"]), (
        f"conducted_at must be an ISO 8601 UTC timestamp, got {conducted['conducted_at']!r}"
    )
    assert conducted["conducted_at"].startswith("2026-06-12"), (
        "conducting stamps the logical clock's current instant of 2026-06-12T09:00:00Z, got "
        f"{conducted['conducted_at']!r}"
    )
    assert conducted["due_date"] == "2026-06-12", (
        f"the due date stays 2026-06-12, got {conducted['due_date']!r}"
    )
    assert conducted["is_late"] is False, (
        "a visit conducted on its own due date is on time because the comparison is inclusive, got "
        f"is_late {conducted['is_late']}"
    )


# --- The corrective-action severity ladder ------------------------------------------------------


def _site_with_one_minor_corrective_action():
    """A rural SELF_PREP site whose first-week visit, conducted 2026-06-10, reported one MINOR
    finding and thereby opened a single corrective action."""
    scenario = setup_program_baseline()
    site = scenario["site"]
    sponsor = scenario["sponsor"]

    visit = create_reported_visit(
        site["id"],
        findings=[finding(finding_code="SIGNAGE_MISSING", severity="MINOR")],
        scheduled_date="2026-06-10",
        conduct_clock="2026-06-10T09:00:00Z",
    )
    actions = list_actions_for_site(site["id"])
    assert len(actions) == 1, (
        f"the deficiency branch opens exactly one corrective action, got {len(actions)}"
    )
    scenario.update({"visit": visit, "action": actions[0]})
    return scenario


def test_minor_corrective_action_due_date_uses_the_thirty_day_ladder(api):
    """PRD §3.7: "An action's `due_date` is set from the logical clock's current date at the moment
    the action is created, and the interval depends on severity: 5 days for `CRITICAL`, 15 days for
    `MAJOR`, and 30 days for `MINOR`."

    Design: Corner/calculations/rejected_action_follow_up_escalates_severity_and_uses_severity_due_days
    """
    scenario = _site_with_one_minor_corrective_action()
    action = scenario["action"]

    assert_corrective_action(action)
    assert action["severity"] == "MINOR", (
        f"the single MINOR finding sets the action's severity, got {action['severity']}"
    )
    assert action["due_date"] == "2026-07-10", (
        "an action opened on 2026-06-10 at MINOR severity falls due "
        f"{RESPONSE_DAYS_BY_SEVERITY['MINOR']} days later on 2026-07-10, got "
        f"{action['due_date']!r}"
    )


def test_rejected_response_spawns_major_follow_up_due_fifteen_days_out(api):
    """PRD §3.7: "The reviewed action moves to `REJECTED` and its `rejection_count` increases by 1;
    simultaneously, exactly one follow-up action is created with
    `follow_up_of_corrective_action_id` pointing at the rejected action, with `site_id`,
    `monitoring_visit_id` and `finding_code` all copied across, `origin` `VISIT_FINDING`, `status`
    `OPEN`, `opened_by_user_id` set to the reviewing monitor, a fresh `due_date` from the severity
    ladder, and a `severity` one level above the rejected action's — `MINOR` becomes `MAJOR`,
    `MAJOR` becomes `CRITICAL`, and `CRITICAL` saturates at `CRITICAL` rather than overflowing."

    Design: Corner/calculations/rejected_action_follow_up_escalates_severity_and_uses_severity_due_days
    """
    scenario = _site_with_one_minor_corrective_action()
    action = scenario["action"]
    visit = scenario["visit"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    validate_success(
        api.respond_corrective_action(
            action["id"], {"response_note": "Signage installed at both entrances."}, sponsor_headers
        )
    )

    set_clock("2026-06-12T09:00:00Z")
    reviewed = validate_success(
        api.review_corrective_action(
            action["id"],
            {"decision": "REJECTED", "reason": "Photo evidence shows only one entrance."},
            make_field_monitor_headers("mon_2"),
        )
    )

    assert_corrective_action(reviewed)
    assert_status(reviewed, "REJECTED")
    assert reviewed["rejection_count"] == 1, (
        f"the rejected action's rejection_count must rise to 1, got {reviewed['rejection_count']}"
    )
    assert reviewed["severity"] == "MINOR", (
        "the ladder climbs on the follow-up, not on the reviewed action, whose severity must stay "
        f"MINOR, got {reviewed['severity']}"
    )

    follow_ups, meta = validate_paginated(
        api.list_corrective_actions(
            REVIEWER, params={"follow_up_of_corrective_action_id": action["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"a rejection spawns exactly one follow-up action, got {meta['total_count']}"
    )
    follow_up = follow_ups[0]
    assert_corrective_action(follow_up)
    assert follow_up["severity"] == "MAJOR", (
        f"a rejected MINOR action escalates one level to MAJOR, got {follow_up['severity']}"
    )
    assert_status(follow_up, "OPEN")
    assert follow_up["due_date"] == "2026-06-27", (
        "the MAJOR follow-up created on 2026-06-12 falls due "
        f"{RESPONSE_DAYS_BY_SEVERITY['MAJOR']} days later on 2026-06-27, got "
        f"{follow_up['due_date']!r}"
    )
    assert follow_up["origin"] == "VISIT_FINDING", (
        f"the follow-up keeps the visit-finding origin, got {follow_up['origin']}"
    )
    assert follow_up["monitoring_visit_id"] == visit["id"], (
        "the follow-up copies the originating visit across, expected "
        f"{visit['id']}, got {follow_up['monitoring_visit_id']!r}"
    )

    visit_now = validate_success(
        api.get_monitoring_visit(visit["id"], make_field_monitor_headers("mon_1"))
    )
    assert_monitoring_visit(visit_now)
    assert_status(visit_now, "REPORT_FILED")
