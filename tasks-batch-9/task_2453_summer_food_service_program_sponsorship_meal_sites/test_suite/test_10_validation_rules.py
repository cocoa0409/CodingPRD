"""Rejection rules: each test builds a legitimate state and then makes the one offending call.

Every scenario here is minimal on purpose — the record under test is valid in every respect except
the single condition the rule names, so the error identifier the API returns can only come from that
rule. Each test also proves the refused call left its target unmutated, and, where the rule carries
an inclusive boundary or a per-entity scope, exercises the neighbouring accepted case in the same
test so the threshold itself is pinned rather than merely approached.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    close_day,
    create_approved_budget,
    create_approved_sponsor,
    create_area_eligibility_record_payload,
    create_area_record,
    create_budget,
    create_draft_claim,
    create_meal_count_payload,
    create_meal_service_day_payload,
    create_monitoring_visit_payload,
    create_open_day,
    create_reported_visit,
    create_site,
    determine_eligibility,
    finding,
    list_actions_for_site,
    make_field_monitor_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    meal_service,
    record_meal_count,
    request_advance,
    schedule_visit,
    set_clock,
    setup_program_baseline,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_INTAKE = "2026-06-01T00:00:00Z"
CLOCK_LATE_SEASON = "2026-08-13T08:00:00Z"
CLOCK_JUNE_CLAIM_WINDOW = "2026-07-06T09:00:00Z"

VISIT_DATE = "2026-06-10"
SERVICE_DATE = "2026-06-08"


# --- Fiscal ceilings ---------------------------------------------------------------------------


def test_budget_submit_rejects_admin_ratio_above_twenty_percent(api):
    """PRD §3.2: "A budget may be submitted only while the sponsor's `application_status` is `APPROVED` — otherwise `ERR_SPONSOR_NOT_APPROVED` — and only when `admin_cost_ratio` is at most 0.2000; a ratio above that threshold is rejected with `ERR_ADMIN_RATIO_EXCEEDED`."

    Design: Corner/validations/budget_admin_ratio_above_twenty_percent_rejected_at_submit
    """
    set_clock(CLOCK_INTAKE)
    sponsor = create_approved_sponsor()
    over_budget = create_budget(
        sponsor["id"],
        operating_cost_budget_cents=5_000_000,
        admin_cost_budget_cents=1_500_000,
    )

    assert float(over_budget["admin_cost_ratio"]) == pytest.approx(0.2308, abs=0.00005), (
        "1500000 divided by 6500000 carried to four decimal places round-half-up is 0.2308, got "
        f"{over_budget['admin_cost_ratio']}"
    )

    response = api.submit_sponsor_budget(
        over_budget["id"], make_sponsor_admin_headers(sponsor["id"])
    )

    validate_error(response, ApiErrorId.ERR_ADMIN_RATIO_EXCEEDED.value)

    unchanged = validate_success(
        api.get_sponsor_budget(over_budget["id"], make_sponsor_admin_headers(sponsor["id"]))
    )
    assert unchanged["status"] == "DRAFT", (
        f"the refused submission must leave the budget in DRAFT, got {unchanged['status']}"
    )
    assert unchanged["revision_round"] == 0, (
        f"a refused submission is not a revision round, got {unchanged['revision_round']}"
    )

    # A ratio of exactly 0.2000 passes: 1000000 over 5000000 sits on the threshold.
    at_threshold_sponsor = create_approved_sponsor(legal_name="Hilltop Youth Services")
    at_threshold_budget = create_budget(
        at_threshold_sponsor["id"],
        operating_cost_budget_cents=4_000_000,
        admin_cost_budget_cents=1_000_000,
    )
    assert float(at_threshold_budget["admin_cost_ratio"]) == pytest.approx(0.2000, abs=0.00005), (
        "1000000 divided by 5000000 is exactly 0.2000, got "
        f"{at_threshold_budget['admin_cost_ratio']}"
    )

    accepted = validate_success(
        api.submit_sponsor_budget(
            at_threshold_budget["id"], make_sponsor_admin_headers(at_threshold_sponsor["id"])
        )
    )
    assert accepted["status"] == "SUBMITTED", (
        "a ratio of exactly 0.2000 is at most 0.2000 and must be accepted, got status "
        f"{accepted['status']}"
    )


def test_advance_approval_above_twenty_five_percent_cap_rejected(api, reviewer_headers):
    """PRD §3.3: "And the approved amount must not exceed one quarter of the total approved budget: take the sum of `approved_operating_cost_cents` and `approved_admin_cost_cents`, multiply by 0.25, discard any fractional cent by flooring, and reject an `approved_amount_cents` above that figure with `ERR_ADVANCE_EXCEEDS_CAP`."

    Design: Corner/validations/advance_above_twenty_five_percent_of_approved_budget_rejected
    """
    set_clock(CLOCK_INTAKE)
    sponsor = create_approved_sponsor()
    create_approved_budget(
        sponsor["id"],
        approved_operating_cost_cents=4_500_000,
        approved_admin_cost_cents=700_000,
    )
    # Approved ceilings of 4500000 plus 700000 put the floored quarter-of-budget cap at 1300000.
    advance_at_cap = request_advance(
        sponsor["id"], request_month="2026-06", requested_amount_cents=2_000_000
    )
    advance_over_cap = request_advance(
        sponsor["id"], request_month="2026-07", requested_amount_cents=2_000_000
    )

    approved = validate_success(
        api.decide_advance_payment(
            advance_at_cap["id"],
            {"decision": "APPROVED", "approved_amount_cents": 1_300_000},
            reviewer_headers,
        )
    )
    assert approved["status"] == "APPROVED", (
        f"an amount exactly equal to the floored cap is accepted, got status {approved['status']}"
    )
    assert approved["approved_amount_cents"] == 1_300_000, (
        f"expected approved_amount_cents 1300000, got {approved['approved_amount_cents']}"
    )
    assert approved["outstanding_cents"] == 0, (
        "outstanding_cents is 0 in every status other than DISBURSED, PARTIALLY_RECOVERED and "
        f"DEMAND_ISSUED, got {approved['outstanding_cents']}"
    )
    assert approved["recovered_amount_cents"] == 0, (
        f"nothing has been recovered yet, got {approved['recovered_amount_cents']}"
    )

    response = api.decide_advance_payment(
        advance_over_cap["id"],
        {"decision": "APPROVED", "approved_amount_cents": 1_300_001},
        reviewer_headers,
    )

    validate_error(response, ApiErrorId.ERR_ADVANCE_EXCEEDS_CAP.value)

    unchanged = validate_success(
        api.get_advance_payment(advance_over_cap["id"], reviewer_headers)
    )
    assert unchanged["status"] == "REQUESTED", (
        f"the refused approval must leave the advance in REQUESTED, got {unchanged['status']}"
    )
    assert unchanged.get("approved_amount_cents") is None, (
        "a refused approval must not write approved_amount_cents, got "
        f"{unchanged.get('approved_amount_cents')}"
    )

    ledger = validate_success(
        api.get_sponsor(sponsor["id"], make_sponsor_admin_headers(sponsor["id"]))
    )
    assert ledger["advance_outstanding_cents"] == 0, (
        "no advance has been disbursed, so the sponsor's outstanding balance stays 0, got "
        f"{ledger['advance_outstanding_cents']}"
    )


def test_advance_approval_for_a_new_sponsor_rejected(api, reviewer_headers):
    """PRD §3.3: "The sponsor must be permitted advances at all — `advance_eligible` true *and* `experience_status` equal to `EXPERIENCED`, and a sponsor failing either half is rejected with `ERR_SPONSOR_NOT_ADVANCE_ELIGIBLE`."

    Design: Corner/validations/advance_decision_for_a_new_sponsor_rejected
    """
    set_clock(CLOCK_INTAKE)
    new_sponsor = create_approved_sponsor(
        legal_name="Newcomer Youth Coalition", experience_status="NEW", advance_eligible=True
    )
    create_approved_budget(
        new_sponsor["id"],
        approved_operating_cost_cents=4_500_000,
        approved_admin_cost_cents=700_000,
    )
    experienced_sponsor = create_approved_sponsor(experience_status="EXPERIENCED")
    create_approved_budget(
        experienced_sponsor["id"],
        approved_operating_cost_cents=4_500_000,
        approved_admin_cost_cents=700_000,
    )

    # The eligibility gate lives on the decision, not on the request: both requests are accepted.
    new_advance = request_advance(
        new_sponsor["id"], request_month="2026-06", requested_amount_cents=30_000
    )
    experienced_advance = request_advance(
        experienced_sponsor["id"], request_month="2026-06", requested_amount_cents=30_000
    )
    assert new_advance["status"] == "REQUESTED", (
        f"a new advance opens in REQUESTED, got {new_advance['status']}"
    )
    assert experienced_advance["status"] == "REQUESTED", (
        f"a new advance opens in REQUESTED, got {experienced_advance['status']}"
    )

    response = api.decide_advance_payment(
        new_advance["id"],
        {"decision": "APPROVED", "approved_amount_cents": 30_000},
        reviewer_headers,
    )

    validate_error(response, ApiErrorId.ERR_SPONSOR_NOT_ADVANCE_ELIGIBLE.value)

    unchanged = validate_success(api.get_advance_payment(new_advance["id"], reviewer_headers))
    assert unchanged["status"] == "REQUESTED", (
        f"the refused approval must leave the advance in REQUESTED, got {unchanged['status']}"
    )
    assert unchanged.get("approved_amount_cents") is None, (
        "a refused approval must not write approved_amount_cents, got "
        f"{unchanged.get('approved_amount_cents')}"
    )

    accepted = validate_success(
        api.decide_advance_payment(
            experienced_advance["id"],
            {"decision": "APPROVED", "approved_amount_cents": 30_000},
            reviewer_headers,
        )
    )
    assert accepted["status"] == "APPROVED", (
        "the otherwise identical EXPERIENCED sponsor satisfies both halves of the gate, got status "
        f"{accepted['status']}"
    )
    assert accepted["approved_amount_cents"] == 30_000, (
        f"expected approved_amount_cents 30000, got {accepted['approved_amount_cents']}"
    )


# --- Uniqueness and structural constraints ------------------------------------------------------


def test_duplicate_area_code_and_data_source_rejected(api, reviewer_headers):
    """PRD §3.4: "The pair of `area_code` and `data_source` must be unique across all records; a repeat is rejected with `ERR_DUPLICATE_AREA_RECORD`."

    Design: Corner/validations/duplicate_area_code_and_data_source_rejected
    """
    set_clock(CLOCK_INTAKE)
    original = create_area_record(
        area_code="CT-0031", data_source="SCHOOL_DATA", free_reduced_pct=62.50
    )

    response = api.create_area_eligibility_record(
        create_area_eligibility_record_payload(
            area_code="CT-0031",
            data_source="SCHOOL_DATA",
            free_reduced_pct=70.00,
            determination_date="2026-04-01",
        ),
        reviewer_headers,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_AREA_RECORD.value)

    unchanged = validate_success(
        api.get_area_eligibility_record(original["id"], reviewer_headers)
    )
    assert float(unchanged["free_reduced_pct"]) == pytest.approx(62.50, abs=0.005), (
        "the rejected duplicate must not touch the record already on file, got free_reduced_pct "
        f"{unchanged['free_reduced_pct']}"
    )

    # The uniqueness constraint is on the pair, so the same area code under the other dataset is new.
    census = validate_success(
        api.create_area_eligibility_record(
            create_area_eligibility_record_payload(
                area_code="CT-0031",
                data_source="CENSUS_ACS",
                free_reduced_pct=70.00,
                determination_date="2026-04-01",
            ),
            reviewer_headers,
        ),
        201,
    )
    assert census["data_source"] == "CENSUS_ACS", (
        f"expected the second record to carry data_source CENSUS_ACS, got {census['data_source']}"
    )
    stored = validate_success(api.get_area_eligibility_record(census["id"], reviewer_headers))
    assert float(stored["free_reduced_pct"]) == pytest.approx(70.00, abs=0.005), (
        f"expected the CENSUS_ACS record to hold 70.00, got {stored['free_reduced_pct']}"
    )


def test_claim_submit_without_line_items_rejected(api):
    """PRD §3.8: "The claim must carry at least one line item, or the attempt reports `ERR_CLAIM_HAS_NO_LINE_ITEMS`."

    Design: Corner/validations/claim_submit_with_no_line_items_rejected
    """
    set_clock(CLOCK_INTAKE)
    sponsor = create_approved_sponsor()
    create_approved_budget(
        sponsor["id"],
        approved_operating_cost_cents=4_500_000,
        approved_admin_cost_cents=700_000,
    )
    set_clock(CLOCK_JUNE_CLAIM_WINDOW)
    claim = create_draft_claim(sponsor["id"], "2026-06")
    sponsor_headers = make_sponsor_admin_headers(sponsor["id"])

    response = api.submit_meal_claim(
        claim["id"],
        {"claimed_operating_cost_cents": 20_000, "claimed_admin_cost_cents": 1_000},
        sponsor_headers,
    )

    validate_error(response, ApiErrorId.ERR_CLAIM_HAS_NO_LINE_ITEMS.value)

    unchanged = validate_success(api.get_meal_claim(claim["id"], sponsor_headers))
    assert unchanged["status"] == "DRAFT", (
        f"the refused submission must leave the claim in DRAFT, got {unchanged['status']}"
    )
    assert unchanged.get("submitted_at") is None, (
        f"a refused submission must not stamp submitted_at, got {unchanged.get('submitted_at')}"
    )
    assert unchanged.get("preliminary_reimbursement_cents") is None, (
        "the preliminary figure is written by submission alone, so it must still be unset, got "
        f"{unchanged.get('preliminary_reimbursement_cents')}"
    )
    assert unchanged.get("claimed_operating_cost_cents") is None, (
        "a refused submission must not write the asserted costs, got "
        f"{unchanged.get('claimed_operating_cost_cents')}"
    )


def test_attendance_forecast_without_finalized_history_rejected(api):
    """PRD §3.9: "When the window is empty, the read is refused with `ERR_INSUFFICIENT_FORECAST_HISTORY` rather than returning a guess."

    Design: Corner/validations/forecast_without_finalized_history_rejected
    """
    scenario = setup_program_baseline(include_budget=False)
    day = create_open_day(
        scenario["site"]["id"], SERVICE_DATE, [meal_service(planned_meals=150)], {"LUNCH": 150}
    )
    record_meal_count(day, meal_type="LUNCH", first_meals=47)
    close_day(day)
    set_clock("2026-06-09T08:00:00Z")

    response = api.get_attendance_forecast(
        scenario["site"]["id"],
        scenario["sponsor_headers"],
        params={"service_date": "2026-06-09", "method": "DECAY_WEIGHTED"},
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_FORECAST_HISTORY.value)

    stored_day = validate_success(
        api.get_meal_service_day(day["id"], scenario["reviewer_headers"])
    )
    assert stored_day["status"] == "CLOSED", (
        "the site's only day is CLOSED and never FINALIZED, which is why the window is empty, got "
        f"{stored_day['status']}"
    )


# --- Temporal constraints ----------------------------------------------------------------------


def test_service_day_outside_operating_season_rejected(api):
    """PRD §3.6: "The `service_date` must fall inside the site's season, on or after `operating_start_date` and on or before `operating_end_date`; a date outside that inclusive range is rejected with `ERR_SERVICE_DATE_OUTSIDE_SEASON`."

    Design: Corner/validations/service_day_outside_operating_season_rejected
    """
    scenario = setup_program_baseline(
        include_budget=False, operating_clock=CLOCK_LATE_SEASON
    )
    site = scenario["site"]
    supervisor_headers = make_site_supervisor_headers(site["id"])
    # The site's season runs 2026-06-08 through 2026-08-14, so 2026-08-15 is one day past its end.
    response = api.create_meal_service_day(
        create_meal_service_day_payload(
            site["id"], "2026-08-15", [meal_service(planned_meals=100)]
        ),
        supervisor_headers,
    )

    validate_error(response, ApiErrorId.ERR_SERVICE_DATE_OUTSIDE_SEASON.value)

    # The range is inclusive at both ends, so the last day of the season is still plannable.
    last_day = validate_success(
        api.create_meal_service_day(
            create_meal_service_day_payload(
                site["id"], "2026-08-14", [meal_service(planned_meals=100)]
            ),
            supervisor_headers,
        ),
        201,
    )
    assert last_day["service_date"] == "2026-08-14", (
        f"expected the accepted day to carry service_date 2026-08-14, got {last_day['service_date']}"
    )
    assert last_day["status"] == "PLANNED", (
        f"a newly planned day opens in PLANNED, got {last_day['status']}"
    )

    days, meta = validate_paginated(
        api.list_meal_service_days(scenario["reviewer_headers"], params={"site_id": site["id"]})
    )
    assert meta["total_count"] == 1, (
        "only the in-season day may have been persisted, so the site must hold exactly one service "
        f"day, got {meta['total_count']}"
    )
    assert [record["service_date"] for record in days] == ["2026-08-14"], (
        f"the out-of-season date must not have been stored, got {[d['service_date'] for d in days]}"
    )


def test_fourth_visit_for_one_monitor_on_one_date_rejected(api):
    """PRD §3.7: "Separately, a monitor may hold at most 3 visits with a `status` other than `CANCELLED` on any single `scheduled_date`; a fourth is rejected with `ERR_MONITOR_DAILY_CAP_EXCEEDED`."

    Design: Corner/validations/fourth_visit_for_one_monitor_on_one_day_rejected
    """
    scenario = setup_program_baseline(include_budget=False, site_count=4)
    sites = scenario["sites"]
    monitor_headers = make_field_monitor_headers("mon_1")

    # A monitor's windows are closed intervals, so these three are separated by a clear half hour.
    for site, window in zip(sites[:3], [("08:00", "08:30"), ("09:00", "09:30"), ("10:00", "10:30")]):
        scheduled = schedule_visit(
            site["id"],
            monitor_user_id="mon_1",
            visit_type="FIRST_WEEK",
            scheduled_date=VISIT_DATE,
            window_start=window[0],
            window_end=window[1],
        )
        assert scheduled["status"] == "SCHEDULED", (
            f"each of the three legitimate visits begins in SCHEDULED, got {scheduled['status']}"
        )

    response = api.create_monitoring_visit(
        create_monitoring_visit_payload(
            sites[3]["id"], "mon_1", scheduled_date=VISIT_DATE,
            window_start="11:00", window_end="11:30",
        ),
        monitor_headers,
    )

    validate_error(response, ApiErrorId.ERR_MONITOR_DAILY_CAP_EXCEEDED.value)

    _, meta = validate_paginated(
        api.list_monitoring_visits(
            scenario["reviewer_headers"],
            params={"monitor_user_id": "mon_1", "scheduled_date": VISIT_DATE},
        )
    )
    assert meta["total_count"] == 3, (
        "the rejected fourth visit must not have been persisted, so mon_1 still holds three visits "
        f"on {VISIT_DATE}, got {meta['total_count']}"
    )

    # The cap counts one monitor's own day, so a second monitor may take the very same window.
    second_monitor_visit = validate_success(
        api.create_monitoring_visit(
            create_monitoring_visit_payload(
                sites[3]["id"], "mon_2", scheduled_date=VISIT_DATE,
                window_start="11:00", window_end="11:30",
            ),
            make_field_monitor_headers("mon_2"),
        ),
        201,
    )
    assert second_monitor_visit["monitor_user_id"] == "mon_2", (
        f"expected the accepted visit to belong to mon_2, got {second_monitor_visit['monitor_user_id']}"
    )


def test_escalating_a_corrective_action_before_its_due_date_rejected(api, reviewer_headers):
    """PRD §3.7: "Failing both tests is reported as `ERR_ESCALATION_NOT_DUE`, and escalating from any other status reports `ERR_ACTION_STATE_INVALID`."

    Design: Corner/validations/escalating_an_action_before_its_due_date_rejected
    """
    scenario = setup_program_baseline(include_budget=False)
    site = scenario["site"]
    create_reported_visit(
        site["id"],
        findings=[finding(finding_code="MEAL_PATTERN_INCOMPLETE", severity="MAJOR")],
        scheduled_date=VISIT_DATE,
    )
    actions = list_actions_for_site(site["id"])
    assert len(actions) == 1, (
        f"one MAJOR finding opens exactly one corrective action, got {len(actions)}"
    )
    action = actions[0]
    assert action["due_date"] == "2026-06-25", (
        "a MAJOR action created on 2026-06-10 is due 15 days later on 2026-06-25, got "
        f"{action['due_date']}"
    )

    set_clock("2026-06-20T09:00:00Z")
    response = api.escalate_corrective_action(
        action["id"], reviewer_headers, {"reason": "No response received."}
    )

    validate_error(response, ApiErrorId.ERR_ESCALATION_NOT_DUE.value)

    unchanged = validate_success(api.get_corrective_action(action["id"], reviewer_headers))
    assert unchanged["status"] == "OPEN", (
        f"the premature escalation must leave the action in OPEN, got {unchanged['status']}"
    )
    assert unchanged["rejection_count"] == 0, (
        f"no response has been rejected, so rejection_count stays 0, got {unchanged['rejection_count']}"
    )
    site_before = validate_success(api.get_site(site["id"], reviewer_headers))
    assert site_before["claim_hold"] is False, (
        "a refused escalation must not raise the site's claim hold, got claim_hold "
        f"{site_before['claim_hold']}"
    )

    # One day past the due date the same call is due, and escalation raises the site's claim hold.
    set_clock("2026-06-26T09:00:00Z")
    escalated = validate_success(
        api.escalate_corrective_action(
            action["id"], reviewer_headers, {"reason": "Response overdue past due date."}
        )
    )
    assert escalated["status"] == "ESCALATED", (
        f"expected the overdue action to move to ESCALATED, got {escalated['status']}"
    )
    site_after = validate_success(api.get_site(site["id"], reviewer_headers))
    assert site_after["claim_hold"] is True, (
        f"escalation raises the site's claim_hold, got {site_after['claim_hold']}"
    )


# --- Referential and cross-entity gates ---------------------------------------------------------


def test_second_reversal_of_the_same_count_entry_rejected(api):
    """PRD §3.6: "A target that exists but is unsuitable reports `ERR_REVERSAL_TARGET_INVALID`, and it is unsuitable when it sits on a different service day, when its own `entry_kind` is not `ORIGINAL`, when its `meal_type` differs from the reversing entry's, when another reversal already points at it, or when the reversing entry's `first_meals`, `second_meals` and `adult_meals` do not exactly equal the target's."

    Design: Corner/validations/second_reversal_of_the_same_entry_rejected
    """
    scenario = setup_program_baseline(include_budget=False)
    site = scenario["site"]
    supervisor_headers = make_site_supervisor_headers(site["id"])
    day = create_open_day(
        site["id"], SERVICE_DATE, [meal_service(planned_meals=150)], {"LUNCH": 150}
    )
    original = record_meal_count(day, meal_type="LUNCH", first_meals=30)
    reversal = record_meal_count(
        day, meal_type="LUNCH", first_meals=30, reversal_of_entry_id=original["id"]
    )

    assert reversal["entry_kind"] == "REVERSAL", (
        f"supplying reversal_of_entry_id sets entry_kind to REVERSAL, got {reversal['entry_kind']}"
    )
    assert reversal["reimbursable_first_meals"] == -30, (
        "the reversal's marginal delta undoes the 30 reimbursable first meals the original earned, "
        f"got {reversal['reimbursable_first_meals']}"
    )
    day_before = validate_success(
        api.get_meal_service_day(day["id"], scenario["reviewer_headers"])
    )
    assert day_before["counted_first_meals"] == 0, (
        "30 original first meals less 30 reversed leaves a net of 0, got "
        f"{day_before['counted_first_meals']}"
    )

    response = api.create_meal_count(
        day["id"],
        create_meal_count_payload(
            meal_type="LUNCH", first_meals=30, reversal_of_entry_id=original["id"]
        ),
        supervisor_headers,
    )

    validate_error(response, ApiErrorId.ERR_REVERSAL_TARGET_INVALID.value)

    _, meta = validate_paginated(
        api.list_meal_count_entries(
            scenario["reviewer_headers"], params={"meal_service_day_id": day["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "the second reversal must not have been persisted, so the day still holds the original and "
        f"its one reversal, got {meta['total_count']}"
    )
    day_after = validate_success(
        api.get_meal_service_day(day["id"], scenario["reviewer_headers"])
    )
    assert day_after["counted_first_meals"] == 0, (
        "the refused second reversal cannot drive the day's counted first meals negative, got "
        f"{day_after['counted_first_meals']}"
    )


def test_approving_a_site_before_eligibility_determination_rejected(api, reviewer_headers):
    """PRD §3.5: "From `PENDING_REVIEW`, a decision of `APPROVED` moves the site to `APPROVED`; this requires that the site's `eligibility_basis` is not `UNDETERMINED`, reported as `ERR_ELIGIBILITY_NOT_DETERMINED` when the determination step was skipped, that the basis is not `NOT_ELIGIBLE`, reported as `ERR_SITE_NOT_ELIGIBLE`, and that the owning sponsor is itself in `application_status` `APPROVED`, reported as `ERR_SPONSOR_NOT_APPROVED`."

    Design: Corner/validations/approving_a_site_before_eligibility_determination_rejected
    """
    set_clock(CLOCK_INTAKE)
    sponsor = create_approved_sponsor()
    area_record = create_area_record(
        area_code="CT-0031", data_source="SCHOOL_DATA", free_reduced_pct=62.50
    )
    site = create_site(sponsor["id"], area_record["id"])
    assert site["eligibility_basis"] == "UNDETERMINED", (
        f"a new site opens with eligibility_basis UNDETERMINED, got {site['eligibility_basis']}"
    )

    response = api.decide_site_approval(site["id"], {"decision": "APPROVED"}, reviewer_headers)

    validate_error(response, ApiErrorId.ERR_ELIGIBILITY_NOT_DETERMINED.value)

    unchanged = validate_success(api.get_site(site["id"], reviewer_headers))
    assert unchanged["approval_status"] == "PENDING_REVIEW", (
        f"the refused approval must leave the site in PENDING_REVIEW, got {unchanged['approval_status']}"
    )
    assert unchanged["eligibility_basis"] == "UNDETERMINED", (
        "a refused approval must not determine eligibility as a side effect, got "
        f"{unchanged['eligibility_basis']}"
    )

    # Running the determination first supplies the affirmative basis the approval demands.
    determined = determine_eligibility(site["id"])
    assert determined["eligibility_basis"] == "AREA_ELIGIBLE", (
        "62.50 percent from school data is at least 50.00, so the basis is AREA_ELIGIBLE, got "
        f"{determined['eligibility_basis']}"
    )
    assert float(determined["eligibility_pct_used"]) == pytest.approx(62.50, abs=0.005), (
        f"eligibility_pct_used takes the record's 62.50 percent, got {determined['eligibility_pct_used']}"
    )

    approved = validate_success(
        api.decide_site_approval(site["id"], {"decision": "APPROVED"}, reviewer_headers)
    )
    assert approved["approval_status"] == "APPROVED", (
        f"the identical call now succeeds, got approval_status {approved['approval_status']}"
    )


def test_closing_the_season_while_a_day_is_open_rejected(api, reviewer_headers):
    """PRD §3.5: "Moving from `OPERATING` to `CLOSED_FOR_SEASON` requires that no service day of the site is currently in `OPEN` — an unclosed day blocks the season close and is reported as `ERR_DAY_HAS_OPEN_SERVICE` — and it voids every remaining `PLANNED` day whose `service_date` is on or after the current logical clock date, with `void_reason` set to the literal string `SEASON_CLOSED` and `voided_day_count` incremented per voided day."

    Design: Corner/validations/closing_season_while_a_day_is_open_rejected
    """
    scenario = setup_program_baseline(include_budget=False)
    site = scenario["site"]
    sponsor_headers = scenario["sponsor_headers"]
    day = create_open_day(
        site["id"], SERVICE_DATE, [meal_service(planned_meals=150)], {"LUNCH": 150}
    )
    record_meal_count(day, meal_type="LUNCH", first_meals=47)

    response = api.set_site_operating_status(
        site["id"], {"to_status": "CLOSED_FOR_SEASON"}, sponsor_headers
    )

    validate_error(response, ApiErrorId.ERR_DAY_HAS_OPEN_SERVICE.value)

    unchanged = validate_success(api.get_site(site["id"], reviewer_headers))
    assert unchanged["operating_status"] == "OPERATING", (
        f"the blocked season close must leave the site OPERATING, got {unchanged['operating_status']}"
    )

    # Closing the day removes the block, and the same call then carries the season close through.
    close_day(day)
    closed_site = validate_success(
        api.set_site_operating_status(
            site["id"], {"to_status": "CLOSED_FOR_SEASON"}, sponsor_headers
        )
    )
    assert closed_site["operating_status"] == "CLOSED_FOR_SEASON", (
        f"expected operating_status CLOSED_FOR_SEASON, got {closed_site['operating_status']}"
    )
    assert closed_site["voided_day_count"] == 0, (
        "the site's only day was CLOSED rather than PLANNED, so the close voids nothing, got "
        f"{closed_site['voided_day_count']}"
    )
    stored_day = validate_success(api.get_meal_service_day(day["id"], reviewer_headers))
    assert stored_day["status"] == "CLOSED", (
        f"the day the supervisor closed stays CLOSED, got {stored_day['status']}"
    )
