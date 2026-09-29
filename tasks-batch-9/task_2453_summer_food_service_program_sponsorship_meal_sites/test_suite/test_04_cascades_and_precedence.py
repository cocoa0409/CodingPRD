"""Transitive cascades and rejection precedence for the SFSP Sponsorship & Meal Sites API.

The tests here follow a single trigger through the chain of rows it legitimately changes, and they
pin which error a request that violates two rules at once must report.
"""

from test_helpers import (
    ApiErrorId,
    add_line_item,
    conduct_visit,
    create_draft_claim,
    create_finalized_day,
    create_open_day,
    create_planned_day,
    create_critical_finding_visit,
    finding,
    list_actions_for_site,
    make_field_monitor_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    record_holding_log,
    run_edit_check,
    schedule_visit,
    set_clock,
    setup_june_claim_scenario,
    setup_program_baseline,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

MONITOR_USER_ID = "mon_1"
VISIT_SCHEDULED_DATE = "2026-06-10"
VISIT_CLOCK = "2026-06-10T09:00:00Z"
LATER_PLANNED_DATE = "2026-06-15"
JULY_SERVICE_DATE = "2026-07-06"
JULY_CLAIM_CLOCK = "2026-08-05T09:00:00Z"

REVIEWER_HEADERS = make_state_agency_reviewer_headers()


# --- Shared scenario builders (compositions of the granular helpers) ---------


def _scenario_with_planned_day_and_draft_claim() -> dict:
    """Approved, operating site with a finalized 2026-06-08 day, a still-planned 2026-06-15 day and
    a DRAFT June claim carrying one unheld line item, with the clock inside the visit's window."""
    scenario = setup_june_claim_scenario(
        include_monitoring_visit=False,
        first_meals=47,
        claim_clock=VISIT_CLOCK,
    )
    scenario["planned_day"] = create_planned_day(
        scenario["site"]["id"], LATER_PLANNED_DATE
    )
    return scenario


def _scenario_with_one_compliance_flag() -> dict:
    """A site that has already lost one claim line to MISSING_MONITORING, so its
    compliance_flag_count stands at 1, plus a SUBMITTED July claim for the same site."""
    scenario = setup_june_claim_scenario(include_monitoring_visit=False, first_meals=47)
    sponsor_id = scenario["sponsor"]["id"]
    site_id = scenario["site"]["id"]

    scenario["july_day"] = create_finalized_day(
        site_id, sponsor_id, JULY_SERVICE_DATE, first_meals=47
    )

    june_claim = submit_claim(
        scenario["claim"], claimed_operating_cost_cents=20_000, claimed_admin_cost_cents=1_000
    )
    scenario["june_claim"] = run_edit_check(june_claim)

    set_clock(JULY_CLAIM_CLOCK)
    july_claim = create_draft_claim(sponsor_id, "2026-07")
    scenario["july_line_item"] = add_line_item(july_claim, site_id)
    scenario["july_claim"] = submit_claim(
        july_claim, claimed_operating_cost_cents=20_000, claimed_admin_cost_cents=1_000
    )
    return scenario


def _scenario_with_open_air_open_day() -> dict:
    """An open-air site approved for LUNCH only, with its 2026-06-08 day OPEN and food received."""
    scenario = setup_program_baseline(site_overrides={"is_open_air": True})
    scenario["day"] = create_open_day(
        scenario["site"]["id"],
        "2026-06-08",
        production_counts={"LUNCH": 150},
        food_received_at="2026-06-08T10:30:00Z",
    )
    return scenario


# --- A critical visit finding and the chain it sets off ----------------------


def test_critical_visit_finding_files_report_and_opens_one_critical_action(api):
    """PRD §3.7: "On the **deficiency branch**, `findings` arrives non-empty: the visit stores the array, sets `highest_severity` to the greatest severity present under the ordering `MINOR` below `MAJOR` below `CRITICAL`, moves from `CONDUCTED` to `REPORT_FILED`, and opens **exactly one** corrective action — not one per finding."

    PRD §3.7: "An action's `due_date` is set from the logical clock's current date at the moment the action is created, and the interval depends on severity: 5 days for `CRITICAL`, 15 days for `MAJOR`, and 30 days for `MINOR`."

    Design: Difficulty/transitive_cascade/critical_finding_suspends_site_voids_days_and_holds_claim_line
    """
    scenario = _scenario_with_planned_day_and_draft_claim()
    site_id = scenario["site"]["id"]

    visit = schedule_visit(
        site_id,
        monitor_user_id=MONITOR_USER_ID,
        visit_type="FULL_REVIEW",
        scheduled_date=VISIT_SCHEDULED_DATE,
        window_start="09:00",
        window_end="11:00",
    )
    conduct_visit(visit)

    reported = validate_success(
        api.report_monitoring_visit(
            visit["id"],
            {"findings": [finding(finding_code="MEALS_SERVED_OFFSITE", severity="CRITICAL")]},
            make_field_monitor_headers(MONITOR_USER_ID),
        )
    )

    assert reported["status"] == "REPORT_FILED", (
        f"a report carrying findings must move the visit to REPORT_FILED, got {reported['status']}"
    )
    assert reported["highest_severity"] == "CRITICAL", (
        "highest_severity must be the greatest severity present in the findings array, got "
        f"{reported['highest_severity']}"
    )

    actions = list_actions_for_site(site_id)
    assert len(actions) == 1, (
        f"a deficiency report opens exactly one corrective action, got {len(actions)}"
    )
    action = actions[0]
    assert action["origin"] == "VISIT_FINDING", (
        f"an action opened by a visit report carries origin VISIT_FINDING, got {action['origin']}"
    )
    assert action["severity"] == "CRITICAL", (
        f"the action's severity equals the visit's highest_severity, got {action['severity']}"
    )
    assert action["status"] == "OPEN", (
        f"a newly opened corrective action stands in OPEN, got {action['status']}"
    )
    assert action["monitoring_visit_id"] == visit["id"], (
        "the action must reference the visit that opened it, got "
        f"{action['monitoring_visit_id']}"
    )
    assert action["site_id"] == site_id, (
        f"the action's site_id is copied from the visit, got {action['site_id']}"
    )
    assert action["finding_code"] == "MEALS_SERVED_OFFSITE", (
        "the action's finding_code is that of the highest-severity finding, got "
        f"{action['finding_code']}"
    )
    assert action["opened_by_user_id"] == MONITOR_USER_ID, (
        f"opened_by_user_id must be the acting monitor, got {action['opened_by_user_id']}"
    )
    assert action["due_date"] == LATER_PLANNED_DATE, (
        "a CRITICAL action opened on 2026-06-10 is due 5 days later on 2026-06-15, got "
        f"{action['due_date']}"
    )


def test_critical_action_cascade_suspends_site_voids_planned_day_and_holds_claim_line(api):
    """PRD §3.7: "When that action's `severity` is `CRITICAL`, its creation immediately fires the site suspension cascade of §3.5 in full: the site moves from `APPROVED` to `SUSPENDED`, `claim_hold` is raised, the site's planned and open service days are voided, and every draft line item of that site is flagged."

    PRD §3.5: "Then every service day of the site whose `status` is `PLANNED` and whose `service_date` is on or after the current logical clock date moves to `VOIDED` with `void_reason` set to the literal string `SITE_SUSPENDED`, along with every service day currently in `OPEN` regardless of its date, and `voided_day_count` grows by one for each day voided."

    PRD §3.5: "Finally, every claim line item that references this site and whose parent claim is in `DRAFT` or `REVISION_OPENED` has its `hold_flag` raised to true, and each of those claims has its `blocking_hold_count` recomputed as the number of its line items with `hold_flag` true."

    Design: Difficulty/transitive_cascade/critical_finding_suspends_site_voids_days_and_holds_claim_line
    """
    scenario = _scenario_with_planned_day_and_draft_claim()
    site_id = scenario["site"]["id"]
    sponsor_id = scenario["sponsor"]["id"]
    sponsor_headers = make_sponsor_admin_headers(sponsor_id)

    before = validate_success(api.get_site(site_id, sponsor_headers))
    assert before["approval_status"] == "APPROVED", (
        f"the site must start the cascade in APPROVED, got {before['approval_status']}"
    )
    assert before["claim_hold"] is False, "the site must start the cascade with no claim hold"

    create_critical_finding_visit(
        site_id,
        visit_type="FULL_REVIEW",
        scheduled_date=VISIT_SCHEDULED_DATE,
        conduct_clock=None,
        monitor_user_id=MONITOR_USER_ID,
    )

    site = validate_success(api.get_site(site_id, sponsor_headers))
    assert site["approval_status"] == "SUSPENDED", (
        "the CRITICAL action's creation must drive the site to SUSPENDED, got "
        f"{site['approval_status']}"
    )
    assert site["claim_hold"] is True, "the suspension cascade must raise the site's claim_hold"

    voided_day = validate_success(
        api.get_meal_service_day(scenario["planned_day"]["id"], sponsor_headers)
    )
    assert voided_day["status"] == "VOIDED", (
        "the planned 2026-06-15 day must be voided by the suspension, got "
        f"{voided_day['status']}"
    )
    assert voided_day["void_reason"] == "SITE_SUSPENDED", (
        f"the void_reason must be the literal SITE_SUSPENDED, got {voided_day['void_reason']}"
    )
    assert site["voided_day_count"] == 1, (
        f"voided_day_count grows by one per day voided, got {site['voided_day_count']}"
    )

    finalized_day = validate_success(
        api.get_meal_service_day(scenario["day"]["id"], sponsor_headers)
    )
    assert finalized_day["status"] == "FINALIZED", (
        "the already finalized day is neither planned nor open, so the cascade leaves it alone, "
        f"got {finalized_day['status']}"
    )

    line_item = validate_success(
        api.get_claim_line_item(scenario["line_item"]["id"], sponsor_headers)
    )
    assert line_item["hold_flag"] is True, (
        "the draft claim's line item for the suspended site must be flagged"
    )

    claim = validate_success(api.get_meal_claim(scenario["claim"]["id"], sponsor_headers))
    assert claim["blocking_hold_count"] == 1, (
        "blocking_hold_count is recomputed as the number of held line items, got "
        f"{claim['blocking_hold_count']}"
    )
    assert claim["status"] == "DRAFT", (
        f"the claim itself is only flagged, not transitioned, got {claim['status']}"
    )


# --- An edit-check disallowance and the compliance chain it sets off ---------


def test_edit_check_disallowance_fails_line_for_missing_first_week_monitoring(api):
    """PRD §3.8: "It fires when the site's first-week monitoring obligation is not satisfied, meaning there exists no monitoring visit for that site with `visit_type` `FIRST_WEEK` whose `status` is `CONDUCTED`, `REPORT_FILED` or `CLOSED` and whose `conducted_at` UTC date falls on or before its own `due_date`; a late-conducted or `CANCELLED` first-week visit does not satisfy the obligation."

    PRD §3.8: "On the **disallowance branch**, where at least one line failed, the claim moves from `SUBMITTED` to `EDIT_CHECK_FAILED`: each failing line records its `edit_check_status`, `disallow_reason`, `disallowed_counts_by_type` and `disallowed_meal_count` while the passing lines are set to `PASSED`, the claim's `edit_check_failure_codes` is set to the distinct failing reasons in sorted order, the claim's `disallowed_meal_count` is recomputed, and the final reimbursement variant runs on the surviving meals to write `final_reimbursement_cents`."

    Design: Difficulty/transitive_cascade/edit_check_disallowance_flags_site_and_opens_compliance_action
    """
    scenario = _scenario_with_one_compliance_flag()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    claim = validate_success(
        api.edit_check_meal_claim(scenario["july_claim"]["id"], REVIEWER_HEADERS)
    )

    assert claim["status"] == "EDIT_CHECK_FAILED", (
        f"a claim with a failing line moves to EDIT_CHECK_FAILED, got {claim['status']}"
    )
    assert claim["edit_check_failure_codes"] == ["MISSING_MONITORING"], (
        "edit_check_failure_codes holds the distinct failing reasons, got "
        f"{claim['edit_check_failure_codes']}"
    )
    assert claim["disallowed_meal_count"] == 47, (
        f"the claim's disallowed meals total the failing line's 47, got "
        f"{claim['disallowed_meal_count']}"
    )

    line_item = validate_success(
        api.get_claim_line_item(scenario["july_line_item"]["id"], sponsor_headers)
    )
    assert line_item["edit_check_status"] == "FAILED", (
        f"a line carrying a disallow reason is FAILED, got {line_item['edit_check_status']}"
    )
    assert line_item["disallow_reason"] == "MISSING_MONITORING", (
        "a site with no timely FIRST_WEEK visit loses the line to MISSING_MONITORING, got "
        f"{line_item['disallow_reason']}"
    )
    assert line_item["disallowed_meal_count"] == 47, (
        "MISSING_MONITORING disallows the whole line's 47 claimed meals, got "
        f"{line_item['disallowed_meal_count']}"
    )
    assert line_item["disallowed_counts_by_type"].get("LUNCH") == 47, (
        "the disallowed count for the claimed meal type is its claimed first plus second meals, "
        f"got {line_item['disallowed_counts_by_type']}"
    )


def test_second_disallowance_trips_compliance_threshold_and_opens_system_action(api):
    """PRD §3.8: "First, for every line whose `disallow_reason` became `EXCEEDS_PRODUCTION` or `MISSING_MONITORING`, that line's site has `compliance_flag_count` increased by 1 — a `FOOD_SAFETY_BREACH` disallowance costs the claim its meals but does not add a compliance flag."

    PRD §3.8: "Second, a site whose `compliance_flag_count` reaches the threshold of 2 has one corrective action opened against it with `origin` `COMPLIANCE_FLAG`, `severity` `MAJOR`, `status` `OPEN`, `monitoring_visit_id` null, `finding_code` `COMPLIANCE_FLAG_THRESHOLD`, `opened_by_user_id` the literal value `SYSTEM`, and a `due_date` 15 days out per the severity ladder; the same site has `claim_hold` set to true."

    Design: Difficulty/transitive_cascade/edit_check_disallowance_flags_site_and_opens_compliance_action
    """
    scenario = _scenario_with_one_compliance_flag()
    site_id = scenario["site"]["id"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    before = validate_success(api.get_site(site_id, sponsor_headers))
    assert before["compliance_flag_count"] == 1, (
        "one earlier disallowed line leaves the site on a single compliance flag, got "
        f"{before['compliance_flag_count']}"
    )
    assert before["claim_hold"] is False, (
        "a single compliance flag is below the threshold, so no claim hold is raised yet"
    )
    _, before_meta = validate_paginated(
        api.list_corrective_actions(REVIEWER_HEADERS, params={"site_id": site_id})
    )
    assert before_meta["total_count"] == 0, (
        "the first flag must not open an action, got "
        f"{before_meta['total_count']} corrective actions"
    )

    validate_success(api.edit_check_meal_claim(scenario["july_claim"]["id"], REVIEWER_HEADERS))

    site = validate_success(api.get_site(site_id, sponsor_headers))
    assert site["compliance_flag_count"] == 2, (
        "a second MISSING_MONITORING disallowance increases compliance_flag_count to 2, got "
        f"{site['compliance_flag_count']}"
    )
    assert site["claim_hold"] is True, (
        "reaching the compliance threshold sets the site's claim_hold"
    )

    actions = list_actions_for_site(site_id)
    assert len(actions) == 1, (
        f"reaching the threshold opens exactly one corrective action, got {len(actions)}"
    )
    action = actions[0]
    assert action["origin"] == "COMPLIANCE_FLAG", (
        f"a threshold action carries origin COMPLIANCE_FLAG, got {action['origin']}"
    )
    assert action["severity"] == "MAJOR", (
        f"a threshold action is opened at MAJOR severity, got {action['severity']}"
    )
    assert action["status"] == "OPEN", (
        f"a threshold action is opened in OPEN, got {action['status']}"
    )
    assert action["monitoring_visit_id"] is None, (
        "a claim-side action belongs to no visit, got "
        f"{action['monitoring_visit_id']}"
    )
    assert action["finding_code"] == "COMPLIANCE_FLAG_THRESHOLD", (
        f"the finding_code is the literal COMPLIANCE_FLAG_THRESHOLD, got {action['finding_code']}"
    )
    assert action["opened_by_user_id"] == "SYSTEM", (
        f"the system itself opens the action, got {action['opened_by_user_id']}"
    )
    assert action["due_date"] == "2026-08-20", (
        "a MAJOR action opened on 2026-08-05 is due 15 days later on 2026-08-20, got "
        f"{action['due_date']}"
    )


# --- Claim state legality outranks the operating cost ceiling ----------------


def test_resubmitting_submitted_claim_reports_state_error_not_cost_overrun(api):
    """PRD §3.8: "Submission is accepted from `DRAFT` and from `REVISION_OPENED` — the second being the post-payment revision loop — and from any other status reports `ERR_CLAIM_STATE_INVALID`."

    PRD §5: "The table lists every error identifier the API may return, in the priority order established in §2.6: when a single request violates several rules at once, the one appearing earlier in this table is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_error_precedes_operating_budget_overrun
    """
    scenario = setup_june_claim_scenario(include_monitoring_visit=False, first_meals=47)
    sponsor_id = scenario["sponsor"]["id"]
    sponsor_headers = make_sponsor_admin_headers(sponsor_id)

    submitted = submit_claim(
        scenario["claim"], claimed_operating_cost_cents=20_000, claimed_admin_cost_cents=1_000
    )
    assert submitted["status"] == "SUBMITTED", (
        f"the claim under test must already be SUBMITTED, got {submitted['status']}"
    )

    response = api.submit_meal_claim(
        submitted["id"],
        {"claimed_operating_cost_cents": 9_000_000, "claimed_admin_cost_cents": 1_000},
        sponsor_headers,
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_STATE_INVALID.value)

    claim = validate_success(api.get_meal_claim(submitted["id"], sponsor_headers))
    assert claim["status"] == "SUBMITTED", (
        f"the rejected resubmission must leave the claim in SUBMITTED, got {claim['status']}"
    )
    assert claim["claimed_operating_cost_cents"] == 20_000, (
        "a rejected submission must not store its asserted operating cost, got "
        f"{claim['claimed_operating_cost_cents']}"
    )


def test_draft_claim_submission_above_operating_ceiling_reports_cost_overrun(api):
    """PRD §3.8: "Finally the asserted costs are tested against the approved ceilings: `claimed_operating_cost_cents` above `approved_operating_cost_cents` is rejected with `ERR_OPERATING_COST_EXCEEDS_BUDGET`, and `claimed_admin_cost_cents` above `approved_admin_cost_cents` with `ERR_ADMIN_COST_EXCEEDS_BUDGET`, each ceiling permitting equality."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_error_precedes_operating_budget_overrun
    """
    scenario = setup_june_claim_scenario(include_monitoring_visit=False, first_meals=47)
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])
    claim = scenario["claim"]

    assert claim["status"] == "DRAFT", (
        f"the claim must be DRAFT so the state gate cannot fire, got {claim['status']}"
    )

    response = api.submit_meal_claim(
        claim["id"],
        {"claimed_operating_cost_cents": 9_000_000, "claimed_admin_cost_cents": 1_000},
        sponsor_headers,
    )
    validate_error(response, ApiErrorId.ERR_OPERATING_COST_EXCEEDS_BUDGET.value)

    unchanged = validate_success(api.get_meal_claim(claim["id"], sponsor_headers))
    assert unchanged["status"] == "DRAFT", (
        f"a claim refused for a cost overrun stays in DRAFT, got {unchanged['status']}"
    )


# --- The food-safety gate outranks the approved-meal-type check -------------


def test_meal_count_on_breached_day_reports_food_safety_before_meal_type(api):
    """PRD §3.6: "Posting is refused unless the day's `status` is `OPEN`, reported as `ERR_SERVICE_DAY_STATE_INVALID`; unless the day's `food_safety_status` is still `OK`, reported as `ERR_FOOD_SAFETY_BREACH`; and unless the `meal_type` is among the site's `approved_meal_types`, reported as `ERR_MEAL_TYPE_NOT_APPROVED`."

    PRD §5: "The table lists every error identifier the API may return, in the priority order established in §2.6: when a single request violates several rules at once, the one appearing earlier in this table is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/food_safety_breach_precedes_unapproved_meal_type
    """
    scenario = _scenario_with_open_air_open_day()
    day = scenario["day"]
    site_id = scenario["site"]["id"]
    supervisor_headers = make_site_supervisor_headers(site_id)

    reading = record_holding_log(
        day,
        meal_type="LUNCH",
        temperature_class="HOT",
        temperature_f=120.0,
        measured_at="2026-06-08T11:45:00Z",
    )
    assert reading["breach_flag"] is True, (
        "a HOT reading below 135.0 at an open-air site must breach"
    )

    breached_day = validate_success(api.get_meal_service_day(day["id"], supervisor_headers))
    assert breached_day["food_safety_status"] == "BREACH", (
        "the first breaching reading must flip the day to BREACH, got "
        f"{breached_day['food_safety_status']}"
    )

    response = api.create_meal_count(
        day["id"],
        {"meal_type": "SUPPER", "first_meals": 10, "second_meals": 0, "adult_meals": 0},
        supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_FOOD_SAFETY_BREACH.value)

    _, meta = validate_paginated(
        api.list_meal_count_entries(
            supervisor_headers, params={"meal_service_day_id": day["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the rejected posting must record no count entry, got {meta['total_count']}"
    )


def test_meal_count_of_unapproved_type_on_safe_day_reports_meal_type_not_approved(api):
    """PRD §3.6: "Posting is refused unless the day's `status` is `OPEN`, reported as `ERR_SERVICE_DAY_STATE_INVALID`; unless the day's `food_safety_status` is still `OK`, reported as `ERR_FOOD_SAFETY_BREACH`; and unless the `meal_type` is among the site's `approved_meal_types`, reported as `ERR_MEAL_TYPE_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/food_safety_breach_precedes_unapproved_meal_type
    """
    scenario = _scenario_with_open_air_open_day()
    day = scenario["day"]
    supervisor_headers = make_site_supervisor_headers(scenario["site"]["id"])

    safe_day = validate_success(api.get_meal_service_day(day["id"], supervisor_headers))
    assert safe_day["food_safety_status"] == "OK", (
        "no breaching reading has arrived, so the food-safety gate cannot fire, got "
        f"{safe_day['food_safety_status']}"
    )
    assert scenario["site"]["approved_meal_types"] == ["LUNCH"], (
        "the site must be approved for LUNCH only, got "
        f"{scenario['site']['approved_meal_types']}"
    )

    response = api.create_meal_count(
        day["id"],
        {"meal_type": "SUPPER", "first_meals": 10, "second_meals": 0, "adult_meals": 0},
        supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_MEAL_TYPE_NOT_APPROVED.value)

    _, meta = validate_paginated(
        api.list_meal_count_entries(
            supervisor_headers, params={"meal_service_day_id": day["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the rejected posting must record no count entry, got {meta['total_count']}"
    )
