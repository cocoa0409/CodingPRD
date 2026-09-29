"""Endpoint behaviour: the budget create/read/list triple, the precondition-gated advance
actions, the per-line-item edit check, the claim-to-site link, the reimbursement summary read,
the read sweep across the resource graph, and the sponsor-initiated void.

Every scenario is built from scratch against an empty database through PRD endpoints only.
"""

from test_helpers import (
    CLOCK_FIRST_WEEK_VISIT,
    CLOCK_JUNE_CLAIM_WINDOW,
    CLOCK_PROGRAM_INTAKE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line_item,
    assert_advance_payment,
    assert_append_only_row,
    assert_area_eligibility_record,
    assert_claim_line_item,
    assert_corrective_action,
    assert_holding_log_entry,
    assert_meal_claim,
    assert_meal_count_entry,
    assert_meal_service_day,
    assert_monitoring_visit,
    assert_pagination_meta,
    assert_site,
    assert_sponsor,
    assert_sponsor_budget,
    assert_status,
    close_day,
    create_approved_sponsor,
    create_budget,
    create_disbursed_advance,
    create_draft_claim,
    create_finalized_day,
    create_planned_day,
    create_reported_visit,
    create_satisfied_first_week_visit,
    create_sponsor_budget_payload,
    finalize_day,
    finding,
    is_iso8601_timestamp,
    make_field_monitor_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    open_day,
    record_holding_log,
    record_meal_count,
    request_advance,
    set_clock,
    setup_june_claim_scenario,
    setup_program_baseline,
    setup_validated_june_claim,
    sponsor_version,
    submit_budget,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

# One rural SELF_PREP site serving 47 LUNCH first meals at the RURAL_OR_SELF_PREP lunch rate of
# 470.50 fractional cents: 47 * 470.50 = 22113.50, rounded half-up to 22114 cents on that line.
LUNCH_47_LINE_VALUE_CENTS = 22_114
# A second site serving 30 LUNCH first meals: 30 * 470.50 = 14115 cents exactly.
LUNCH_30_LINE_VALUE_CENTS = 14_115

SECOND_SERVICE_DATE = "2026-06-09"
CLOCK_SECOND_SERVICE_DAY = "2026-06-09T08:00:00Z"
VOID_REASON = "Municipal water shutoff at the park pavilion"


# --- Corner/endpoints/sponsor_budget_create_read_and_filtered_list_round_trip -----------------


def test_sponsor_budget_create_and_read_agree_on_the_derived_admin_cost_ratio(api):
    """PRD §3.2: "On every write, the server derives `admin_cost_ratio`: the administrative line
    divided by the sum of the operating and administrative lines, carried to four decimal places
    using round-half-up."

    Design: Corner/endpoints/sponsor_budget_create_read_and_filtered_list_round_trip
    """
    set_clock(CLOCK_PROGRAM_INTAKE)
    sponsor = create_approved_sponsor()
    sponsor_headers = make_sponsor_admin_headers(sponsor["id"])

    created = validate_success(
        api.create_sponsor_budget(
            create_sponsor_budget_payload(
                sponsor["id"],
                operating_cost_budget_cents=5_000_000,
                admin_cost_budget_cents=1_000_000,
                projected_total_meals=20_000,
            ),
            sponsor_headers,
        ),
        201,
    )
    assert_sponsor_budget(created)
    assert_status(created, "DRAFT")
    assert created["revision_round"] == 0, (
        f"a newly opened budget must start at revision_round 0, got {created['revision_round']}"
    )
    assert abs(created["admin_cost_ratio"] - 0.1667) <= 1e-9, (
        "1000000 / (5000000 + 1000000) is 0.166666..., which must be carried to four decimal "
        f"places round-half-up as 0.1667, got {created['admin_cost_ratio']}"
    )

    fetched = validate_success(
        api.get_sponsor_budget(created["id"], make_state_agency_reviewer_headers())
    )
    assert_sponsor_budget(fetched)
    assert fetched["id"] == created["id"], (
        f"the single read must return the created budget, got {fetched['id']}"
    )
    assert fetched["admin_cost_ratio"] == created["admin_cost_ratio"], (
        "the single read must report the same derived admin_cost_ratio the create returned, "
        f"{created['admin_cost_ratio']} vs {fetched['admin_cost_ratio']}"
    )
    assert fetched["projected_total_meals"] == 20_000, (
        f"the read must echo the 20000 projected meals the create stored, got "
        f"{fetched['projected_total_meals']}"
    )


def test_sponsor_budget_list_status_filter_narrows_a_two_budget_program_year(api):
    """PRD §2.3: "Budgets may be narrowed by `sponsor_id`, `program_year` and `status`; advances by
    `sponsor_id`, `status` and `request_month`; sites by `sponsor_id`,
    `area_eligibility_record_id`, `approval_status`, `operating_status` and `site_type`; service
    days by `site_id`, `service_date` and `status`; meal count entries by `meal_service_day_id`,
    `reversal_of_entry_id`, `meal_type` and `entry_kind`; holding-log entries by
    `meal_service_day_id`, `meal_type` and `breach_flag`; monitoring visits by `site_id`,
    `monitor_user_id`, `status`, `visit_type` and `scheduled_date`; corrective actions by
    `site_id`, `monitoring_visit_id`, `follow_up_of_corrective_action_id`, `status`, `severity` and
    `origin`; claims by `sponsor_id`, `claim_month` and `status`; and claim line items by
    `meal_claim_id`, `site_id`, `edit_check_status` and `disallow_reason`."

    Design: Corner/endpoints/sponsor_budget_create_read_and_filtered_list_round_trip
    """
    set_clock(CLOCK_PROGRAM_INTAKE)
    sponsor_a = create_approved_sponsor()
    sponsor_b = create_approved_sponsor(
        legal_name="Lakeside Parks District", sponsor_type="GOVERNMENT", advance_eligible=False
    )
    reviewer = make_state_agency_reviewer_headers()

    budget_a = create_budget(
        sponsor_a["id"], operating_cost_budget_cents=5_000_000,
        admin_cost_budget_cents=1_000_000, projected_total_meals=20_000,
    )
    budget_b = create_budget(
        sponsor_b["id"], operating_cost_budget_cents=4_000_000,
        admin_cost_budget_cents=500_000, projected_total_meals=15_000,
    )
    submitted_b = submit_budget(budget_b)
    assert_status(submitted_b, "SUBMITTED")

    every_budget, every_meta = validate_paginated(
        api.list_sponsor_budgets(reviewer, params={"program_year": 2026, "limit": 10, "offset": 0})
    )
    assert_pagination_meta(every_meta, 2, False, expected_limit=10, expected_offset=0)
    assert {row["id"] for row in every_budget} == {budget_a["id"], budget_b["id"]}, (
        "the unfiltered program-year page must carry both budgets, got "
        f"{[row['id'] for row in every_budget]}"
    )

    drafts, draft_meta = validate_paginated(
        api.list_sponsor_budgets(
            reviewer, params={"program_year": 2026, "status": "DRAFT", "limit": 10, "offset": 0}
        )
    )
    assert_pagination_meta(draft_meta, 1, False)
    assert len(drafts) == 1, f"the DRAFT filter must return exactly one row, got {len(drafts)}"
    assert drafts[0]["id"] == budget_a["id"], (
        "only the budget still in DRAFT may survive the status filter, expected "
        f"{budget_a['id']}, got {drafts[0]['id']}"
    )
    assert_status(drafts[0], "DRAFT")


# --- Corner/endpoints/advance_disburse_action_requires_approved_state_first --------------------


def test_disburse_is_refused_while_the_advance_is_still_requested(api):
    """PRD §2.6: "7. Same-entity state legality, in this sequence: sponsor
    (`ERR_SPONSOR_STATE_INVALID`), budget (`ERR_BUDGET_STATE_INVALID`), advance
    (`ERR_ADVANCE_STATE_INVALID`), site (`ERR_SITE_STATE_INVALID`), service day
    (`ERR_SERVICE_DAY_STATE_INVALID`), monitoring visit (`ERR_VISIT_STATE_INVALID`), corrective
    action (`ERR_ACTION_STATE_INVALID`), meal claim (`ERR_CLAIM_STATE_INVALID`)."

    Design: Corner/endpoints/advance_disburse_action_requires_approved_state_first
    """
    scenario = setup_program_baseline()
    sponsor = scenario["sponsor"]
    reviewer = make_state_agency_reviewer_headers()
    advance = request_advance(sponsor["id"], request_month="2026-06", requested_amount_cents=30_000)
    assert_status(advance, "REQUESTED")

    validate_error(
        api.disburse_advance_payment(advance["id"], reviewer),
        ApiErrorId.ERR_ADVANCE_STATE_INVALID.value,
    )

    unchanged = validate_success(api.get_advance_payment(advance["id"], reviewer))
    assert_advance_payment(unchanged)
    assert_status(unchanged, "REQUESTED")
    assert unchanged["outstanding_cents"] == 0, (
        "a refused disbursement must leave the advance's outstanding balance at 0, got "
        f"{unchanged['outstanding_cents']}"
    )
    assert unchanged.get("disbursed_at") is None, (
        f"a refused disbursement must not stamp disbursed_at, got {unchanged.get('disbursed_at')}"
    )

    ledger = validate_success(
        api.get_sponsor(sponsor["id"], make_sponsor_admin_headers(sponsor["id"]))
    )
    assert_sponsor(ledger)
    assert ledger["advance_paid_cents"] == 0, (
        f"no money moved, so advance_paid_cents must stay 0, got {ledger['advance_paid_cents']}"
    )
    assert ledger["advance_outstanding_cents"] == 0, (
        "no money moved, so advance_outstanding_cents must stay 0, got "
        f"{ledger['advance_outstanding_cents']}"
    )


def test_disburse_from_approved_opens_the_outstanding_balance_and_the_sponsor_ledger(api):
    """PRD §3.3: "On success the advance's `disbursed_at` is stamped from the logical clock, its
    `outstanding_cents` is set equal to `approved_amount_cents`, the sponsor's
    `advance_paid_cents` grows by that same amount, the sponsor's `advance_outstanding_cents` is
    recomputed, and both the advance's `version` and the sponsor's `version` increment by 1."

    Design: Corner/endpoints/advance_disburse_action_requires_approved_state_first
    """
    scenario = setup_program_baseline()
    sponsor = scenario["sponsor"]
    sponsor_headers = make_sponsor_admin_headers(sponsor["id"])
    reviewer = make_state_agency_reviewer_headers()

    version_before_request = sponsor_version(sponsor["id"])
    advance = request_advance(sponsor["id"], request_month="2026-06", requested_amount_cents=30_000)
    validate_success(
        api.decide_advance_payment(
            advance["id"], {"decision": "APPROVED", "approved_amount_cents": 30_000}, reviewer
        )
    )

    disbursed = validate_success(api.disburse_advance_payment(advance["id"], reviewer))
    assert_advance_payment(disbursed)
    assert_status(disbursed, "DISBURSED")
    assert disbursed["outstanding_cents"] == 30_000, (
        "the outstanding balance must open at the 30000-cent approved amount, got "
        f"{disbursed['outstanding_cents']}"
    )
    assert is_iso8601_timestamp(disbursed.get("disbursed_at", "")), (
        f"disbursed_at must be stamped from the logical clock, got {disbursed.get('disbursed_at')}"
    )
    assert disbursed["disbursed_at"].startswith("2026-06-08"), (
        "the logical clock stands at 2026-06-08, so disbursed_at must carry that date, got "
        f"{disbursed['disbursed_at']}"
    )

    ledger = validate_success(api.get_sponsor(sponsor["id"], sponsor_headers))
    assert_sponsor(ledger)
    assert ledger["advance_paid_cents"] == 30_000, (
        f"advance_paid_cents must grow by the 30000 disbursed, got {ledger['advance_paid_cents']}"
    )
    assert ledger["advance_outstanding_cents"] == 30_000, (
        "advance_outstanding_cents must be recomputed to the full 30000 still owed, got "
        f"{ledger['advance_outstanding_cents']}"
    )
    assert ledger["version"] == version_before_request + 2, (
        "the advance create and the disbursement each advance the sponsor's version by 1, "
        f"expected {version_before_request + 2}, got {ledger['version']}"
    )


# --- Corner/endpoints/edit_check_reports_per_line_item_status_on_partial_failure ---------------


def _two_site_claim_with_one_unmonitored_site():
    """One sponsor with two approved operating sites, each carrying one finalized June day, but
    only the first site holding a satisfied first-week monitoring visit; the June claim is
    submitted with a line item per site, the monitored site's line first."""
    scenario = setup_program_baseline(site_count=2)
    sponsor_id = scenario["sponsor"]["id"]
    site_a, site_b = scenario["sites"]

    day_a = create_finalized_day(site_a["id"], sponsor_id, "2026-06-08", first_meals=47)
    set_clock(CLOCK_SECOND_SERVICE_DAY)
    day_b = create_finalized_day(site_b["id"], sponsor_id, SECOND_SERVICE_DATE, first_meals=30)
    create_satisfied_first_week_visit(
        site_a["id"], monitor_user_id="mon_1", conduct_clock=CLOCK_FIRST_WEEK_VISIT
    )

    set_clock(CLOCK_JUNE_CLAIM_WINDOW)
    claim = create_draft_claim(sponsor_id, "2026-06")
    line_a = add_line_item(claim, site_a["id"])
    line_b = add_line_item(claim, site_b["id"])
    claim = submit_claim(
        claim, claimed_operating_cost_cents=40_000, claimed_admin_cost_cents=5_000
    )
    scenario.update({
        "site_a": site_a, "site_b": site_b, "day_a": day_a, "day_b": day_b,
        "claim": claim, "line_a": line_a, "line_b": line_b,
    })
    return scenario


def test_edit_check_passes_the_monitored_line_and_fails_the_unmonitored_line(api):
    """PRD §3.8: "When no rule fires, the line's `disallow_reason` stays `NONE`. Each line's
    `edit_check_status` becomes `FAILED` when its reason is anything other than `NONE` and `PASSED`
    otherwise, its `disallowed_counts_by_type` holds the map the firing rule produced or an empty
    map when the reason is `NONE`, and its `disallowed_meal_count` is the total of that map's
    values."

    Design: Corner/endpoints/edit_check_reports_per_line_item_status_on_partial_failure
    """
    scenario = _two_site_claim_with_one_unmonitored_site()
    reviewer = make_state_agency_reviewer_headers()

    validate_success(api.edit_check_meal_claim(scenario["claim"]["id"], reviewer))

    passing = validate_success(api.get_claim_line_item(scenario["line_a"]["id"], reviewer))
    assert_claim_line_item(passing)
    assert passing["edit_check_status"] == "PASSED", (
        "the monitored site's line has no firing rule, so its edit_check_status must be PASSED, "
        f"got {passing['edit_check_status']}"
    )
    assert passing["disallow_reason"] == "NONE", (
        f"the monitored site's line must keep disallow_reason NONE, got {passing['disallow_reason']}"
    )
    assert passing["disallowed_counts_by_type"] == {}, (
        "a line whose reason is NONE must carry an empty disallowed_counts_by_type map, got "
        f"{passing['disallowed_counts_by_type']}"
    )
    assert passing["disallowed_meal_count"] == 0, (
        "the total of an empty disallowance map is 0, got "
        f"{passing['disallowed_meal_count']}"
    )

    failing = validate_success(api.get_claim_line_item(scenario["line_b"]["id"], reviewer))
    assert_claim_line_item(failing)
    assert failing["edit_check_status"] == "FAILED", (
        "the unmonitored site's line carries a firing rule, so its edit_check_status must be "
        f"FAILED, got {failing['edit_check_status']}"
    )
    assert failing["disallow_reason"] == "MISSING_MONITORING", (
        "a site with no conducted first-week visit must be disallowed for MISSING_MONITORING, got "
        f"{failing['disallow_reason']}"
    )
    assert failing["disallowed_counts_by_type"] == {"LUNCH": 30}, (
        "the whole line comes out, so all 30 claimed LUNCH meals must be disallowed, got "
        f"{failing['disallowed_counts_by_type']}"
    )
    assert failing["disallowed_meal_count"] == 30, (
        "disallowed_meal_count must total the disallowance map's 30 meals, got "
        f"{failing['disallowed_meal_count']}"
    )


def test_edit_check_fails_the_claim_while_the_passing_line_keeps_its_meal_value(api):
    """PRD §3.8: "On the **disallowance branch**, where at least one line failed, the claim moves
    from `SUBMITTED` to `EDIT_CHECK_FAILED`: each failing line records its `edit_check_status`,
    `disallow_reason`, `disallowed_counts_by_type` and `disallowed_meal_count` while the passing
    lines are set to `PASSED`, the claim's `edit_check_failure_codes` is set to the distinct
    failing reasons in sorted order, the claim's `disallowed_meal_count` is recomputed, and the
    final reimbursement variant runs on the surviving meals to write `final_reimbursement_cents`."

    Design: Corner/endpoints/edit_check_reports_per_line_item_status_on_partial_failure
    """
    scenario = _two_site_claim_with_one_unmonitored_site()
    reviewer = make_state_agency_reviewer_headers()

    assert scenario["claim"]["meals_rate_value_cents"] == (
        LUNCH_47_LINE_VALUE_CENTS + LUNCH_30_LINE_VALUE_CENTS
    ), (
        "before the edit check both lines count, so the claim must be worth 22114 + 14115 = "
        f"36229 cents, got {scenario['claim']['meals_rate_value_cents']}"
    )

    checked = validate_success(api.edit_check_meal_claim(scenario["claim"]["id"], reviewer))
    assert_meal_claim(checked)
    assert_status(checked, "EDIT_CHECK_FAILED")
    assert checked["edit_check_failure_codes"] == ["MISSING_MONITORING"], (
        "the only distinct failing reason is MISSING_MONITORING, got "
        f"{checked['edit_check_failure_codes']}"
    )
    assert checked["disallowed_meal_count"] == 30, (
        "the claim's recomputed disallowed_meal_count must be the failing line's 30 meals, got "
        f"{checked['disallowed_meal_count']}"
    )

    passing = validate_success(api.get_claim_line_item(scenario["line_a"]["id"], reviewer))
    assert passing["meals_rate_value_cents"] == LUNCH_47_LINE_VALUE_CENTS, (
        "the passing line's 47 undisallowed LUNCH meals must still be worth 22114 cents, got "
        f"{passing['meals_rate_value_cents']}"
    )
    failing = validate_success(api.get_claim_line_item(scenario["line_b"]["id"], reviewer))
    assert failing["meals_rate_value_cents"] == 0, (
        "all 30 of the failing line's meals were disallowed, so its net claimable meals are 0 and "
        f"its value must be 0 cents, got {failing['meals_rate_value_cents']}"
    )

    summary = validate_success(api.get_reimbursement_summary(scenario["claim"]["id"], reviewer))
    assert summary["meals_rate_value_cents"] == LUNCH_47_LINE_VALUE_CENTS, (
        "the surviving meals value must be the passing line's 22114 cents alone, got "
        f"{summary['meals_rate_value_cents']}"
    )


def test_edit_check_flags_only_the_site_behind_the_failed_line(api):
    """PRD §3.8: "First, for every line whose `disallow_reason` became `EXCEEDS_PRODUCTION` or
    `MISSING_MONITORING`, that line's site has `compliance_flag_count` increased by 1 — a
    `FOOD_SAFETY_BREACH` disallowance costs the claim its meals but does not add a compliance
    flag."

    Design: Corner/endpoints/edit_check_reports_per_line_item_status_on_partial_failure
    """
    scenario = _two_site_claim_with_one_unmonitored_site()
    reviewer = make_state_agency_reviewer_headers()

    validate_success(api.edit_check_meal_claim(scenario["claim"]["id"], reviewer))

    monitored = validate_success(api.get_site(scenario["site_a"]["id"], reviewer))
    assert_site(monitored)
    assert monitored["compliance_flag_count"] == 0, (
        "the site whose line passed must never be penalised, got "
        f"{monitored['compliance_flag_count']}"
    )
    unmonitored = validate_success(api.get_site(scenario["site_b"]["id"], reviewer))
    assert_site(unmonitored)
    assert unmonitored["compliance_flag_count"] == 1, (
        "the site behind the MISSING_MONITORING line must gain exactly one compliance flag, got "
        f"{unmonitored['compliance_flag_count']}"
    )


# --- Corner/endpoints/line_item_link_requires_an_existing_site --------------------------------


def test_line_item_for_an_unknown_site_is_rejected_and_creates_no_line(api):
    """PRD §2.6: "4. Existence of the referenced records, in this sequence: sponsor
    (`ERR_SPONSOR_NOT_FOUND`), area eligibility record (`ERR_AREA_RECORD_NOT_FOUND`), sponsor
    budget (`ERR_BUDGET_NOT_FOUND`), advance payment (`ERR_ADVANCE_NOT_FOUND`), site
    (`ERR_SITE_NOT_FOUND`), service day (`ERR_SERVICE_DAY_NOT_FOUND`), meal count entry
    (`ERR_COUNT_ENTRY_NOT_FOUND`), holding-log entry (`ERR_HOLDING_LOG_NOT_FOUND`), monitoring
    visit (`ERR_VISIT_NOT_FOUND`), corrective action (`ERR_CORRECTIVE_ACTION_NOT_FOUND`), meal
    claim (`ERR_CLAIM_NOT_FOUND`), claim line item (`ERR_CLAIM_LINE_ITEM_NOT_FOUND`)."

    Design: Corner/endpoints/line_item_link_requires_an_existing_site
    """
    scenario = setup_june_claim_scenario(add_line_items=False)
    claim = scenario["claim"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    validate_error(
        api.create_claim_line_item(claim["id"], {"site_id": NON_EXISTENT_UUID}, sponsor_headers),
        ApiErrorId.ERR_SITE_NOT_FOUND.value,
    )

    lines, meta = validate_paginated(
        api.list_claim_line_items(sponsor_headers, params={"meal_claim_id": claim["id"]})
    )
    assert_pagination_meta(meta, 0, False)
    assert lines == [], f"the rejected link must create no line item, got {lines}"


def test_line_item_for_a_real_site_derives_its_rate_class_and_hold_flag(api):
    """PRD §3.8: "The line's `rate_class` is `RURAL_OR_SELF_PREP` when the site's `is_rural` is
    true **or** its `production_mode` is `SELF_PREP`, and `OTHER` otherwise — either condition
    alone is enough to earn the higher rate. Its `finalized_day_count` counts the site's finalized
    days inside `claim_month`. Its `claimed_first_meals_by_type` maps each meal type to the sum,
    over those finalized days taken in ascending `service_date`, of the reimbursable first meals
    the classification of §3.6 produced for that meal type, and `claimed_second_meals_by_type`
    does the same for reimbursable second meals. Days in `VOIDED`, `CLOSED`, `OPEN` or `PLANNED`
    never contribute a meal, which is why finalization is the gate that matters. The new line
    starts with `edit_check_status` `PENDING`, `disallow_reason` `NONE`, `disallowed_counts_by_type`
    null, and `hold_flag` copied from the site's current `claim_hold`; adding it recomputes the
    claim's `meals_rate_value_cents` and its `blocking_hold_count`."

    Design: Corner/endpoints/line_item_link_requires_an_existing_site
    """
    scenario = setup_june_claim_scenario(add_line_items=False)
    claim = scenario["claim"]
    site = scenario["site"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    line = validate_success(
        api.create_claim_line_item(claim["id"], {"site_id": site["id"]}, sponsor_headers), 201
    )
    assert_claim_line_item(line)
    assert line["site_id"] == site["id"], (
        f"the line must reference the requested site, got {line['site_id']}"
    )
    assert line["meal_claim_id"] == claim["id"], (
        f"the line must belong to the claim it was added to, got {line['meal_claim_id']}"
    )
    assert line["rate_class"] == "RURAL_OR_SELF_PREP", (
        "a rural SELF_PREP site earns the higher rate class, got "
        f"{line['rate_class']}"
    )
    assert line["finalized_day_count"] == 1, (
        f"exactly one June day is finalized for this site, got {line['finalized_day_count']}"
    )
    assert line["claimed_first_meals_by_type"] == {"LUNCH": 47}, (
        "the single finalized day contributes 47 reimbursable LUNCH first meals, got "
        f"{line['claimed_first_meals_by_type']}"
    )
    assert line["hold_flag"] is False, (
        f"hold_flag is copied from the site's claim_hold, which is false, got {line['hold_flag']}"
    )

    recomputed = validate_success(api.get_meal_claim(claim["id"], sponsor_headers))
    assert_meal_claim(recomputed)
    assert recomputed["meals_rate_value_cents"] == LUNCH_47_LINE_VALUE_CENTS, (
        "adding the line must recompute the claim's meals value to 22114 cents, got "
        f"{recomputed['meals_rate_value_cents']}"
    )
    assert recomputed["blocking_hold_count"] == 0, (
        "no line item sits on hold, so blocking_hold_count must be 0, got "
        f"{recomputed['blocking_hold_count']}"
    )


# --- Corner/endpoints/reimbursement_summary_exposes_every_intermediate_step -------------------


def test_reimbursement_summary_returns_every_intermediate_field_it_promises(api):
    """PRD §3.8: "A computed read exposes every intermediate step of the reimbursement calculation
    for a claim as it currently stands, returning the `claim_id`, the claim's `status`, the
    `variant` that applies to that status, and then `meals_rate_value_cents`,
    `operating_reimbursement_cents`, `admin_cap_cents`, `admin_reimbursement_cents`,
    `preliminary_reimbursement_cents`, `final_reimbursement_cents`, `advance_offset_cents`,
    `net_payable_cents` and `disallowed_meal_count`."

    Design: Corner/endpoints/reimbursement_summary_exposes_every_intermediate_step
    """
    scenario = setup_validated_june_claim(
        claimed_operating_cost_cents=20_000, claimed_admin_cost_cents=5_000
    )
    claim = scenario["claim"]
    assert_status(claim, "VALIDATED")

    summary = validate_success(
        api.get_reimbursement_summary(claim["id"], make_state_agency_reviewer_headers())
    )
    for field in (
        "claim_id",
        "status",
        "variant",
        "meals_rate_value_cents",
        "operating_reimbursement_cents",
        "admin_cap_cents",
        "admin_reimbursement_cents",
        "preliminary_reimbursement_cents",
        "final_reimbursement_cents",
        "advance_offset_cents",
        "net_payable_cents",
        "disallowed_meal_count",
    ):
        assert field in summary, f"the reimbursement summary must expose {field}"
    assert summary["claim_id"] == claim["id"], (
        f"the summary must name the claim it describes, got {summary['claim_id']}"
    )
    assert summary["status"] == "VALIDATED", (
        f"the summary must report the claim's current status VALIDATED, got {summary['status']}"
    )
    assert summary["disallowed_meal_count"] == 0, (
        "no meal was disallowed on this clean claim, got "
        f"{summary['disallowed_meal_count']}"
    )


def test_reimbursement_summary_shows_the_operating_clamp_and_the_floored_admin_cap(api):
    """PRD §3.8: "Step one takes the claim's `meals_rate_value_cents`, recomputed with the
    disallowed counts subtracted. Step two produces the operating reimbursement as the lesser of
    that meals value and the claim's `claimed_operating_cost_cents`. Step three produces
    `admin_cap_cents` as 20 percent of **step two's output**, floored to whole cents. Step four
    produces the administrative reimbursement as the lesser of `claimed_admin_cost_cents` and that
    cap. Step five sums steps two and four into the gross figure that becomes
    `final_reimbursement_cents`."

    Design: Corner/endpoints/reimbursement_summary_exposes_every_intermediate_step
    """
    scenario = setup_validated_june_claim(
        claimed_operating_cost_cents=20_000, claimed_admin_cost_cents=5_000
    )

    summary = validate_success(
        api.get_reimbursement_summary(
            scenario["claim"]["id"], make_state_agency_reviewer_headers()
        )
    )
    assert summary["meals_rate_value_cents"] == LUNCH_47_LINE_VALUE_CENTS, (
        "step one must read the claim's 22114-cent meals value with nothing disallowed, got "
        f"{summary['meals_rate_value_cents']}"
    )
    assert summary["operating_reimbursement_cents"] == 20_000, (
        "step two must take the lesser of the 22114 meals value and the 20000 claimed operating "
        f"cost, expected 20000, got {summary['operating_reimbursement_cents']}"
    )
    assert summary["admin_cap_cents"] == 4_000, (
        "step three must floor 20 percent of the 20000 operating reimbursement to 4000, got "
        f"{summary['admin_cap_cents']}"
    )
    assert summary["admin_reimbursement_cents"] == 4_000, (
        "step four must clip the 5000 claimed admin cost to the 4000 cap, got "
        f"{summary['admin_reimbursement_cents']}"
    )
    assert summary["final_reimbursement_cents"] == 24_000, (
        "step five must sum 20000 operating and 4000 administrative into 24000, got "
        f"{summary['final_reimbursement_cents']}"
    )


def test_reimbursement_summary_shows_the_preliminary_figure_above_the_final_figure(api):
    """PRD §3.8: "For identical inputs the final figure is always less than or equal to the
    preliminary figure, and it is strictly smaller whenever `claimed_admin_cost_cents` exceeds the
    floored cap or any meal has been disallowed."

    Design: Corner/endpoints/reimbursement_summary_exposes_every_intermediate_step
    """
    scenario = setup_validated_june_claim(
        claimed_operating_cost_cents=20_000, claimed_admin_cost_cents=5_000
    )

    summary = validate_success(
        api.get_reimbursement_summary(
            scenario["claim"]["id"], make_state_agency_reviewer_headers()
        )
    )
    assert summary["preliminary_reimbursement_cents"] == 27_114, (
        "the uncapped preliminary figure must be the 22114 meals value plus the 5000 claimed "
        f"admin cost, expected 27114, got {summary['preliminary_reimbursement_cents']}"
    )
    assert summary["final_reimbursement_cents"] == 24_000, (
        f"the capped final figure must be 24000, got {summary['final_reimbursement_cents']}"
    )
    assert (
        summary["final_reimbursement_cents"] < summary["preliminary_reimbursement_cents"]
    ), (
        "the 5000 claimed admin cost exceeds the floored 4000 cap, so the final figure must sit "
        f"strictly below the preliminary one, got {summary['final_reimbursement_cents']} against "
        f"{summary['preliminary_reimbursement_cents']}"
    )


# --- Corner/endpoints/recovery_demand_allowed_only_after_the_month_following_request_month ----


def test_demand_is_too_early_on_the_last_day_of_the_month_after_the_request_month(api):
    """PRD §3.3: "A demand may be issued from `DISBURSED` or from `PARTIALLY_RECOVERED`, requires
    `outstanding_cents` strictly greater than 0, and requires the logical clock date to be strictly
    after the last calendar day of the month *following* the advance's `request_month` — for an
    advance covering July, a demand becomes available only from the first of September onward, and
    an attempt on or before 31 August is rejected with `ERR_DEMAND_TOO_EARLY`."

    Design: Corner/endpoints/recovery_demand_allowed_only_after_the_month_following_request_month
    """
    scenario = setup_program_baseline()
    reviewer = make_state_agency_reviewer_headers()
    advance = create_disbursed_advance(
        scenario["sponsor"]["id"], request_month="2026-06", requested_amount_cents=30_000
    )
    assert_status(advance, "DISBURSED")

    set_clock("2026-07-31T23:00:00Z")
    validate_error(
        api.demand_advance_payment(
            advance["id"], reviewer, {"reason": "June advance still outstanding."}
        ),
        ApiErrorId.ERR_DEMAND_TOO_EARLY.value,
    )

    unchanged = validate_success(api.get_advance_payment(advance["id"], reviewer))
    assert_advance_payment(unchanged)
    assert_status(unchanged, "DISBURSED")
    assert unchanged.get("demand_issued_at") is None, (
        "31 July is not strictly after the last day of July, so no demand may be stamped, got "
        f"{unchanged.get('demand_issued_at')}"
    )


def test_demand_is_accepted_once_the_month_following_the_request_month_has_passed(api):
    """PRD §3.3: "A demand requires a `reason`, stores it in `decision_reason`, stamps
    `demand_issued_at` from the logical clock, and moves the advance to `DEMAND_ISSUED`."

    Design: Corner/endpoints/recovery_demand_allowed_only_after_the_month_following_request_month
    """
    scenario = setup_program_baseline()
    sponsor = scenario["sponsor"]
    reviewer = make_state_agency_reviewer_headers()
    advance = create_disbursed_advance(
        sponsor["id"], request_month="2026-06", requested_amount_cents=30_000
    )

    set_clock("2026-08-01T00:00:00Z")
    demanded = validate_success(
        api.demand_advance_payment(
            advance["id"], reviewer, {"reason": "June advance still outstanding after July."}
        )
    )
    assert_advance_payment(demanded)
    assert_status(demanded, "DEMAND_ISSUED")
    assert demanded["decision_reason"] == "June advance still outstanding after July.", (
        f"the demand's reason must be stored in decision_reason, got {demanded['decision_reason']}"
    )
    assert is_iso8601_timestamp(demanded.get("demand_issued_at", "")), (
        "demand_issued_at must be stamped from the logical clock, got "
        f"{demanded.get('demand_issued_at')}"
    )
    assert demanded["demand_issued_at"].startswith("2026-08-01"), (
        "the logical clock stands at 2026-08-01, so demand_issued_at must carry that date, got "
        f"{demanded['demand_issued_at']}"
    )
    assert demanded["outstanding_cents"] == 30_000, (
        "issuing a demand moves no money, so the outstanding balance stays at 30000, got "
        f"{demanded['outstanding_cents']}"
    )

    ledger = validate_success(
        api.get_sponsor(sponsor["id"], make_sponsor_admin_headers(sponsor["id"]))
    )
    assert ledger["advance_outstanding_cents"] == 30_000, (
        "the sponsor's outstanding advance position is untouched by a demand, got "
        f"{ledger['advance_outstanding_cents']}"
    )


# --- Corner/endpoints/every_read_endpoint_returns_the_stored_row_or_a_filtered_page -----------


def _populated_program_graph():
    """One approved sponsor with an approved rural SELF_PREP LUNCH site, one finalized June day
    carrying a 47-meal LUNCH count and one compliant HOT holding reading, a first-week visit
    reported with a MINOR finding, one requested June advance, and a June claim with one line."""
    scenario = setup_program_baseline()
    sponsor_id = scenario["sponsor"]["id"]
    site = scenario["site"]

    day = create_planned_day(site["id"], "2026-06-08")
    day = open_day(day, {"LUNCH": 150}, "2026-06-08T10:30:00Z")
    holding_entry = record_holding_log(
        day, meal_type="LUNCH", temperature_class="HOT", temperature_f=140.0,
        measured_at="2026-06-08T11:00:00Z",
    )
    count_entry = record_meal_count(day, meal_type="LUNCH", first_meals=47)
    close_day(day)
    day = finalize_day(day, sponsor_id)

    visit = create_reported_visit(
        site["id"],
        findings=[finding(finding_code="SIGNAGE_MISSING", severity="MINOR")],
        conduct_clock=CLOCK_FIRST_WEEK_VISIT,
    )
    advance = request_advance(
        sponsor_id, request_month="2026-06", requested_amount_cents=500_000
    )

    set_clock(CLOCK_JUNE_CLAIM_WINDOW)
    claim = create_draft_claim(sponsor_id, "2026-06")
    line_item = add_line_item(claim, site["id"])

    scenario.update({
        "day": day, "holding_entry": holding_entry, "count_entry": count_entry,
        "visit": visit, "advance": advance, "claim": claim, "line_item": line_item,
    })
    return scenario


def test_single_resource_reads_return_the_row_the_write_stored(api):
    """PRD §2.5: "Every resource is addressed by an `id`, a server-minted UUID carrying no type
    prefix and never used in a business decision or as a sort key. Every resource also carries
    `created_at`, an ISO 8601 UTC timestamp with three fractional digits stamped from the logical
    clock at creation; `created_at` is the only sanctioned tie-break ordering key anywhere in this
    specification."

    Design: Corner/endpoints/every_read_endpoint_returns_the_stored_row_or_a_filtered_page
    """
    scenario = _populated_program_graph()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])
    reviewer = make_state_agency_reviewer_headers()
    monitor = make_field_monitor_headers("mon_1")

    area_record = validate_success(
        api.get_area_eligibility_record(scenario["area_record"]["id"], sponsor_headers)
    )
    assert_area_eligibility_record(area_record)
    assert_append_only_row(area_record)
    for field in ("id", "created_at", "area_code", "data_source", "free_reduced_pct"):
        assert area_record[field] == scenario["area_record"][field], (
            f"the area record read must echo the filed {field}, got {area_record[field]}"
        )

    site = validate_success(api.get_site(scenario["site"]["id"], monitor))
    assert_site(site)
    for field in ("id", "created_at", "approval_status", "operating_status", "eligibility_basis",
                  "claim_hold", "voided_day_count", "compliance_flag_count"):
        assert site[field] == scenario["site"][field], (
            f"the site read must echo the stored {field}, got {site[field]}"
        )

    holding_entry = validate_success(
        api.get_holding_log_entry(scenario["holding_entry"]["id"], reviewer)
    )
    assert_holding_log_entry(holding_entry)
    assert_append_only_row(holding_entry)
    for field in ("id", "created_at", "meal_service_day_id", "holding_minutes", "breach_flag",
                  "breach_reason"):
        assert holding_entry[field] == scenario["holding_entry"][field], (
            f"the holding log read must echo the stored {field}, got {holding_entry[field]}"
        )

    advance = validate_success(api.get_advance_payment(scenario["advance"]["id"], sponsor_headers))
    assert_advance_payment(advance)
    for field in ("id", "created_at", "status", "request_month", "requested_amount_cents",
                  "outstanding_cents"):
        assert advance[field] == scenario["advance"][field], (
            f"the advance read must echo the stored {field}, got {advance[field]}"
        )

    line_item = validate_success(
        api.get_claim_line_item(scenario["line_item"]["id"], sponsor_headers)
    )
    assert_claim_line_item(line_item)
    for field in ("id", "created_at", "rate_class", "finalized_day_count", "hold_flag",
                  "meals_rate_value_cents", "edit_check_status", "disallow_reason"):
        assert line_item[field] == scenario["line_item"][field], (
            f"the line item read must echo the stored {field}, got {line_item[field]}"
        )


def test_visit_and_corrective_action_reads_expose_the_single_action_the_report_opened(api):
    """PRD §3.7: "On the **deficiency branch**, `findings` arrives non-empty: the visit stores the
    array, sets `highest_severity` to the greatest severity present under the ordering `MINOR`
    below `MAJOR` below `CRITICAL`, moves from `CONDUCTED` to `REPORT_FILED`, and opens **exactly
    one** corrective action — not one per finding. That single action takes `origin`
    `VISIT_FINDING`, `status` `OPEN`, `site_id` copied from the visit, `monitoring_visit_id` set to
    the visit, `severity` equal to the visit's `highest_severity`, `finding_code` equal to the
    `finding_code` of the highest-severity finding with ties broken by choosing the alphabetically
    first `finding_code`, and `opened_by_user_id` set to the acting monitor, who is necessarily the
    visit's `monitor_user_id`."

    Design: Corner/endpoints/every_read_endpoint_returns_the_stored_row_or_a_filtered_page
    """
    scenario = _populated_program_graph()
    site = scenario["site"]
    visit_id = scenario["visit"]["id"]
    reviewer = make_state_agency_reviewer_headers()
    monitor = make_field_monitor_headers("mon_1")

    visit = validate_success(api.get_monitoring_visit(visit_id, monitor))
    assert_monitoring_visit(visit)
    assert_status(visit, "REPORT_FILED")
    assert visit["highest_severity"] == "MINOR", (
        f"the only finding is MINOR, so highest_severity must be MINOR, got "
        f"{visit['highest_severity']}"
    )

    actions, meta = validate_paginated(
        api.list_corrective_actions(reviewer, params={"site_id": site["id"]})
    )
    assert_pagination_meta(meta, 1, False)
    assert len(actions) == 1, (
        f"the report must open exactly one corrective action, got {len(actions)}"
    )

    action = validate_success(api.get_corrective_action(actions[0]["id"], reviewer))
    assert_corrective_action(action)
    assert_status(action, "OPEN")
    assert action["origin"] == "VISIT_FINDING", (
        f"an action opened by a visit report takes origin VISIT_FINDING, got {action['origin']}"
    )
    assert action["severity"] == "MINOR", (
        "the action's severity equals the visit's highest_severity MINOR, got "
        f"{action['severity']}"
    )
    assert action["site_id"] == site["id"], (
        f"site_id must be copied from the visit, got {action['site_id']}"
    )
    assert action["monitoring_visit_id"] == visit_id, (
        f"monitoring_visit_id must point at the reporting visit, got "
        f"{action['monitoring_visit_id']}"
    )
    assert action["finding_code"] == "SIGNAGE_MISSING", (
        "finding_code must be the highest-severity finding's code, got "
        f"{action['finding_code']}"
    )
    assert action["opened_by_user_id"] == "mon_1", (
        "opened_by_user_id must be the acting monitor mon_1, got "
        f"{action['opened_by_user_id']}"
    )


def test_collection_reads_count_only_the_records_matching_their_filters(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the
    envelope's `meta` object, where `total_count` is the number of records matching the filters
    before pagination is applied and `has_more` indicates whether records remain beyond the current
    page."

    Design: Corner/endpoints/every_read_endpoint_returns_the_stored_row_or_a_filtered_page
    """
    scenario = _populated_program_graph()
    site_id = scenario["site"]["id"]
    day_id = scenario["day"]["id"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])
    supervisor = make_site_supervisor_headers(site_id)
    reviewer = make_state_agency_reviewer_headers()

    days, days_meta = validate_paginated(
        api.list_meal_service_days(
            sponsor_headers, params={"site_id": site_id, "status": "FINALIZED"}
        )
    )
    assert_pagination_meta(days_meta, 1, False)
    assert_meal_service_day(days[0])
    assert days[0]["id"] == day_id, (
        f"the FINALIZED page must carry the finalized day, got {days[0]['id']}"
    )
    _, planned_meta = validate_paginated(
        api.list_meal_service_days(
            sponsor_headers, params={"site_id": site_id, "status": "PLANNED"}
        )
    )
    assert_pagination_meta(planned_meta, 0, False)

    entries, entries_meta = validate_paginated(
        api.list_meal_count_entries(
            supervisor, params={"meal_service_day_id": day_id, "entry_kind": "ORIGINAL"}
        )
    )
    assert_pagination_meta(entries_meta, 1, False)
    assert_meal_count_entry(entries[0])
    assert entries[0]["id"] == scenario["count_entry"]["id"], (
        f"the ORIGINAL page must carry the posted count entry, got {entries[0]['id']}"
    )
    _, reversal_meta = validate_paginated(
        api.list_meal_count_entries(
            supervisor, params={"meal_service_day_id": day_id, "entry_kind": "REVERSAL"}
        )
    )
    assert_pagination_meta(reversal_meta, 0, False)

    readings, readings_meta = validate_paginated(
        api.list_holding_log_entries(
            supervisor, params={"meal_service_day_id": day_id, "breach_flag": "false"}
        )
    )
    assert_pagination_meta(readings_meta, 1, False)
    assert readings[0]["id"] == scenario["holding_entry"]["id"], (
        f"the compliant reading must match the breach_flag=false filter, got {readings[0]['id']}"
    )
    _, breaching_meta = validate_paginated(
        api.list_holding_log_entries(
            supervisor, params={"meal_service_day_id": day_id, "breach_flag": "true"}
        )
    )
    assert_pagination_meta(breaching_meta, 0, False)

    visits, visits_meta = validate_paginated(
        api.list_monitoring_visits(reviewer, params={"site_id": site_id, "visit_type": "FIRST_WEEK"})
    )
    assert_pagination_meta(visits_meta, 1, False)
    assert visits[0]["id"] == scenario["visit"]["id"], (
        f"the FIRST_WEEK page must carry the reported visit, got {visits[0]['id']}"
    )
    _, review_meta = validate_paginated(
        api.list_monitoring_visits(
            reviewer, params={"site_id": site_id, "visit_type": "FULL_REVIEW"}
        )
    )
    assert_pagination_meta(review_meta, 0, False)

    advances, advances_meta = validate_paginated(
        api.list_advance_payments(
            reviewer, params={"sponsor_id": scenario["sponsor"]["id"], "status": "REQUESTED"}
        )
    )
    assert_pagination_meta(advances_meta, 1, False)
    assert advances[0]["requested_amount_cents"] == 500_000, (
        "the REQUESTED page must carry the 500000-cent request, got "
        f"{advances[0]['requested_amount_cents']}"
    )
    _, approved_meta = validate_paginated(
        api.list_advance_payments(
            reviewer, params={"sponsor_id": scenario["sponsor"]["id"], "status": "APPROVED"}
        )
    )
    assert_pagination_meta(approved_meta, 0, False)

    claims, claims_meta = validate_paginated(
        api.list_meal_claims(
            sponsor_headers,
            params={"sponsor_id": scenario["sponsor"]["id"], "claim_month": "2026-06"},
        )
    )
    assert_pagination_meta(claims_meta, 1, False)
    assert_meal_claim(claims[0])
    assert claims[0]["id"] == scenario["claim"]["id"], (
        f"the June page must carry the June claim, got {claims[0]['id']}"
    )
    _, july_meta = validate_paginated(
        api.list_meal_claims(
            sponsor_headers,
            params={"sponsor_id": scenario["sponsor"]["id"], "claim_month": "2026-07"},
        )
    )
    assert_pagination_meta(july_meta, 0, False)

    lines, lines_meta = validate_paginated(
        api.list_claim_line_items(reviewer, params={"meal_claim_id": scenario["claim"]["id"]})
    )
    assert_pagination_meta(lines_meta, 1, False)
    assert lines[0]["id"] == scenario["line_item"]["id"], (
        f"the claim's line-item page must carry its only line, got {lines[0]['id']}"
    )


def test_reads_never_advance_the_sponsor_or_site_version(api):
    """PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp
    refreshed on every mutation, and `version`, an integer that begins at 1 when the row is created
    and increments by exactly 1 on every mutation of that row — including mutations the server
    performs on its own initiative, such as a cascade that voids a service day or a recomputation
    that rewrites a derived counter."

    Design: Corner/endpoints/every_read_endpoint_returns_the_stored_row_or_a_filtered_page
    """
    scenario = _populated_program_graph()
    sponsor_id = scenario["sponsor"]["id"]
    site_id = scenario["site"]["id"]
    sponsor_headers = make_sponsor_admin_headers(sponsor_id)
    reviewer = make_state_agency_reviewer_headers()

    sponsor_before = validate_success(api.get_sponsor(sponsor_id, sponsor_headers))
    site_before = validate_success(api.get_site(site_id, reviewer))

    validate_success(api.get_area_eligibility_record(scenario["area_record"]["id"], reviewer))
    validate_success(api.get_meal_service_day(scenario["day"]["id"], sponsor_headers))
    validate_success(api.get_holding_log_entry(scenario["holding_entry"]["id"], reviewer))
    validate_success(api.get_meal_count_entry(scenario["count_entry"]["id"], reviewer))
    validate_success(api.get_monitoring_visit(scenario["visit"]["id"], reviewer))
    validate_success(api.get_advance_payment(scenario["advance"]["id"], reviewer))
    validate_success(api.get_meal_claim(scenario["claim"]["id"], sponsor_headers))
    validate_success(api.get_claim_line_item(scenario["line_item"]["id"], reviewer))
    validate_paginated(api.list_sites(reviewer, params={"sponsor_id": sponsor_id}))
    validate_paginated(api.list_meal_claims(sponsor_headers, params={"sponsor_id": sponsor_id}))

    sponsor_after = validate_success(api.get_sponsor(sponsor_id, sponsor_headers))
    assert_sponsor(sponsor_after)
    assert sponsor_after["version"] == sponsor_before["version"], (
        "a read is not a mutation, so the sponsor's version must not move, "
        f"{sponsor_before['version']} became {sponsor_after['version']}"
    )
    assert sponsor_after["updated_at"] == sponsor_before["updated_at"], (
        "a read must not refresh the sponsor's updated_at, "
        f"{sponsor_before['updated_at']} became {sponsor_after['updated_at']}"
    )

    site_after = validate_success(api.get_site(site_id, reviewer))
    assert_site(site_after)
    assert site_after["version"] == site_before["version"], (
        "a read is not a mutation, so the site's version must not move, "
        f"{site_before['version']} became {site_after['version']}"
    )


# --- Corner/endpoints/voiding_a_planned_day_zeroes_it_and_bumps_the_site_void_counter ---------


def _finalized_day_plus_planned_day():
    """One approved operating site with the 2026-06-08 day finalized at 47 LUNCH meals and a
    second day for 2026-06-09 still in PLANNED."""
    scenario = setup_program_baseline()
    sponsor_id = scenario["sponsor"]["id"]
    site_id = scenario["site"]["id"]
    finalized = create_finalized_day(site_id, sponsor_id, "2026-06-08", first_meals=47)
    planned = create_planned_day(site_id, SECOND_SERVICE_DATE)
    scenario.update({"finalized_day": finalized, "planned_day": planned})
    return scenario


def test_voiding_a_planned_day_zeroes_its_meals_and_bumps_the_void_counter(api):
    """PRD §3.6: "A day may instead be voided by the sponsor from `PLANNED`, `OPEN` or `CLOSED`,
    supplying a `reason` that is stored as `void_reason`; voiding sets `status` to `VOIDED`, forces
    `reimbursable_meals` to 0, and increments the site's `voided_day_count` by 1."

    Design: Corner/endpoints/voiding_a_planned_day_zeroes_it_and_bumps_the_site_void_counter
    """
    scenario = _finalized_day_plus_planned_day()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    voided = validate_success(
        api.void_meal_service_day(
            scenario["planned_day"]["id"], {"reason": VOID_REASON}, sponsor_headers
        )
    )
    assert_meal_service_day(voided)
    assert_status(voided, "VOIDED")
    assert voided["void_reason"] == VOID_REASON, (
        f"the caller's reason must be stored as void_reason, got {voided['void_reason']}"
    )
    assert voided["reimbursable_meals"] == 0, (
        f"voiding forces reimbursable_meals to 0, got {voided['reimbursable_meals']}"
    )

    site = validate_success(api.get_site(scenario["site"]["id"], sponsor_headers))
    assert_site(site)
    assert site["voided_day_count"] == 1, (
        f"exactly one day was voided, so voided_day_count must be 1, got "
        f"{site['voided_day_count']}"
    )
    assert site["claim_hold"] is False, (
        f"a sponsor-initiated void raises no claim hold, got {site['claim_hold']}"
    )

    untouched = validate_success(
        api.get_meal_service_day(scenario["finalized_day"]["id"], sponsor_headers)
    )
    assert_status(untouched, "FINALIZED")
    assert untouched["reimbursable_meals"] == 47, (
        "voiding the second day must leave the finalized day's 47 reimbursable meals alone, got "
        f"{untouched['reimbursable_meals']}"
    )


def test_voided_day_leaves_the_finalized_page_and_cannot_be_voided_again(api):
    """PRD §3.6: "`FINALIZED` and `VOIDED` are both terminal. Any operation attempted from a status
    that does not permit it — finalizing a `PLANNED` day, voiding a `FINALIZED` one, closing a day
    that was never opened — is rejected with `ERR_SERVICE_DAY_STATE_INVALID`."

    Design: Corner/endpoints/voiding_a_planned_day_zeroes_it_and_bumps_the_site_void_counter
    """
    scenario = _finalized_day_plus_planned_day()
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])
    voided_day_id = scenario["planned_day"]["id"]

    validate_success(
        api.void_meal_service_day(voided_day_id, {"reason": VOID_REASON}, sponsor_headers)
    )

    finalized_days, meta = validate_paginated(
        api.list_meal_service_days(
            sponsor_headers,
            params={"site_id": scenario["site"]["id"], "status": "FINALIZED"},
        )
    )
    assert_pagination_meta(meta, 1, False)
    assert [row["id"] for row in finalized_days] == [scenario["finalized_day"]["id"]], (
        "only the finalized day may appear on the FINALIZED page, got "
        f"{[row['id'] for row in finalized_days]}"
    )
    assert voided_day_id not in [row["id"] for row in finalized_days], (
        "the voided day must be invisible to the FINALIZED filter claims aggregate over"
    )

    validate_error(
        api.void_meal_service_day(voided_day_id, {"reason": "Second attempt"}, sponsor_headers),
        ApiErrorId.ERR_SERVICE_DAY_STATE_INVALID.value,
    )
