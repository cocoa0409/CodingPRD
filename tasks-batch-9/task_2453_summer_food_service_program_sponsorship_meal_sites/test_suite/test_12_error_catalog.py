"""Reachability of the SFSP error catalog: one offending condition per test.

Each test drives a single rule violation and pins the error identifier the PRD names for that exact
condition. The HTTP status is cross-checked automatically from the PRD's error table, so no status
argument is passed to ``validate_error``.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line_item,
    create_approved_budget,
    create_approved_site,
    create_approved_sponsor,
    create_area_record,
    create_budget,
    create_draft_claim,
    create_meal_claim_payload,
    create_meal_service_day_payload,
    create_open_day,
    create_planned_day,
    create_reported_visit,
    create_site,
    create_site_payload,
    create_sponsor,
    determine_eligibility,
    finding,
    list_actions_for_site,
    make_field_monitor_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    meal_service,
    open_day_payload,
    request_advance,
    schedule_visit,
    set_clock,
    setup_june_claim_scenario,
    setup_program_baseline,
    sponsor_version,
    submit_budget,
    submit_sponsor_application,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER_HEADERS = make_state_agency_reviewer_headers()

INTAKE_CLOCK = "2026-06-01T00:00:00Z"
FIRST_SERVICE_CLOCK = "2026-06-08T08:00:00Z"
FIRST_SERVICE_DATE = "2026-06-08"
FOOD_RECEIVED_AT = "2026-06-08T10:30:00Z"
JUNE_CLAIM_CLOCK = "2026-07-06T09:00:00Z"
VISIT_DATE = "2026-06-10"
VISIT_CLOCK = "2026-06-10T09:00:00Z"

SEASON_START_DATE = "2026-06-08"
SEASON_END_DATE = "2026-08-14"


# --- Unknown identifiers: each read answers with its own not-found code -------


def test_unknown_budget_and_advance_ids_report_their_own_not_found_codes(api):
    """PRD §2.6: "Existence of the referenced records, in this sequence: sponsor (`ERR_SPONSOR_NOT_FOUND`), area eligibility record (`ERR_AREA_RECORD_NOT_FOUND`), sponsor budget (`ERR_BUDGET_NOT_FOUND`), advance payment (`ERR_ADVANCE_NOT_FOUND`), site (`ERR_SITE_NOT_FOUND`), service day (`ERR_SERVICE_DAY_NOT_FOUND`), meal count entry (`ERR_COUNT_ENTRY_NOT_FOUND`), holding-log entry (`ERR_HOLDING_LOG_NOT_FOUND`), monitoring visit (`ERR_VISIT_NOT_FOUND`), corrective action (`ERR_CORRECTIVE_ACTION_NOT_FOUND`), meal claim (`ERR_CLAIM_NOT_FOUND`), claim line item (`ERR_CLAIM_LINE_ITEM_NOT_FOUND`)."

    Design: Corner/errors/unknown_id_sweep_returns_the_resource_specific_not_found_code
    """
    validate_error(
        api.get_sponsor_budget(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_BUDGET_NOT_FOUND.value,
    )
    validate_error(
        api.get_advance_payment(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_ADVANCE_NOT_FOUND.value,
    )


def test_unknown_service_day_count_and_holding_log_ids_report_their_own_not_found_codes(api):
    """PRD §2.6: "Existence of the referenced records, in this sequence: sponsor (`ERR_SPONSOR_NOT_FOUND`), area eligibility record (`ERR_AREA_RECORD_NOT_FOUND`), sponsor budget (`ERR_BUDGET_NOT_FOUND`), advance payment (`ERR_ADVANCE_NOT_FOUND`), site (`ERR_SITE_NOT_FOUND`), service day (`ERR_SERVICE_DAY_NOT_FOUND`), meal count entry (`ERR_COUNT_ENTRY_NOT_FOUND`), holding-log entry (`ERR_HOLDING_LOG_NOT_FOUND`), monitoring visit (`ERR_VISIT_NOT_FOUND`), corrective action (`ERR_CORRECTIVE_ACTION_NOT_FOUND`), meal claim (`ERR_CLAIM_NOT_FOUND`), claim line item (`ERR_CLAIM_LINE_ITEM_NOT_FOUND`)."

    Design: Corner/errors/unknown_id_sweep_returns_the_resource_specific_not_found_code
    """
    validate_error(
        api.get_meal_service_day(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_SERVICE_DAY_NOT_FOUND.value,
    )
    validate_error(
        api.get_meal_count_entry(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_COUNT_ENTRY_NOT_FOUND.value,
    )
    validate_error(
        api.get_holding_log_entry(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_HOLDING_LOG_NOT_FOUND.value,
    )


def test_unknown_visit_and_corrective_action_ids_report_their_own_not_found_codes(api):
    """PRD §2.6: "Existence of the referenced records, in this sequence: sponsor (`ERR_SPONSOR_NOT_FOUND`), area eligibility record (`ERR_AREA_RECORD_NOT_FOUND`), sponsor budget (`ERR_BUDGET_NOT_FOUND`), advance payment (`ERR_ADVANCE_NOT_FOUND`), site (`ERR_SITE_NOT_FOUND`), service day (`ERR_SERVICE_DAY_NOT_FOUND`), meal count entry (`ERR_COUNT_ENTRY_NOT_FOUND`), holding-log entry (`ERR_HOLDING_LOG_NOT_FOUND`), monitoring visit (`ERR_VISIT_NOT_FOUND`), corrective action (`ERR_CORRECTIVE_ACTION_NOT_FOUND`), meal claim (`ERR_CLAIM_NOT_FOUND`), claim line item (`ERR_CLAIM_LINE_ITEM_NOT_FOUND`)."

    Design: Corner/errors/unknown_id_sweep_returns_the_resource_specific_not_found_code
    """
    validate_error(
        api.get_monitoring_visit(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_VISIT_NOT_FOUND.value,
    )
    validate_error(
        api.get_corrective_action(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_FOUND.value,
    )


def test_unknown_claim_and_line_item_ids_report_their_own_not_found_codes(api):
    """PRD §2.6: "Existence of the referenced records, in this sequence: sponsor (`ERR_SPONSOR_NOT_FOUND`), area eligibility record (`ERR_AREA_RECORD_NOT_FOUND`), sponsor budget (`ERR_BUDGET_NOT_FOUND`), advance payment (`ERR_ADVANCE_NOT_FOUND`), site (`ERR_SITE_NOT_FOUND`), service day (`ERR_SERVICE_DAY_NOT_FOUND`), meal count entry (`ERR_COUNT_ENTRY_NOT_FOUND`), holding-log entry (`ERR_HOLDING_LOG_NOT_FOUND`), monitoring visit (`ERR_VISIT_NOT_FOUND`), corrective action (`ERR_CORRECTIVE_ACTION_NOT_FOUND`), meal claim (`ERR_CLAIM_NOT_FOUND`), claim line item (`ERR_CLAIM_LINE_ITEM_NOT_FOUND`)."

    Design: Corner/errors/unknown_id_sweep_returns_the_resource_specific_not_found_code
    """
    validate_error(
        api.get_meal_claim(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_CLAIM_NOT_FOUND.value,
    )
    validate_error(
        api.get_claim_line_item(NON_EXISTENT_UUID, REVIEWER_HEADERS),
        ApiErrorId.ERR_CLAIM_LINE_ITEM_NOT_FOUND.value,
    )


# --- Site intake payload requirements and the meal-type cap ------------------


def _approved_sponsor_with_area_record() -> dict:
    """An APPROVED sponsor and one 62.50 percent SCHOOL_DATA area record."""
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    return {"sponsor": sponsor, "area_record": create_area_record()}


def _site_total_count(api, sponsor_id: str) -> int:
    _data, meta = validate_paginated(
        api.list_sites(REVIEWER_HEADERS, params={"sponsor_id": sponsor_id})
    )
    return meta["total_count"]


def test_open_site_without_an_area_record_reports_area_record_required(api):
    """PRD §3.4: "A site whose `site_type` is `OPEN`, `RESTRICTED_OPEN` or `MIGRANT` must name an `area_eligibility_record_id`; omitting it is rejected with `ERR_AREA_RECORD_REQUIRED`, and naming a record that does not exist is rejected with `ERR_AREA_RECORD_NOT_FOUND`."

    Design: Corner/errors/site_intake_input_requirement_and_cap_errors_are_all_reachable
    """
    context = _approved_sponsor_with_area_record()
    sponsor_id = context["sponsor"]["id"]

    payload = create_site_payload(
        sponsor_id,
        None,
        name="No Area Record Park",
        site_type="OPEN",
        approved_meal_types=["LUNCH"],
    )
    response = api.create_site(payload, make_sponsor_admin_headers(sponsor_id))
    validate_error(response, ApiErrorId.ERR_AREA_RECORD_REQUIRED.value)

    assert _site_total_count(api, sponsor_id) == 0, (
        "an OPEN site registered without an area eligibility record must not persist"
    )


def test_closed_enrolled_site_without_enrolled_pct_reports_enrolled_pct_required(api):
    """PRD §3.4: "A site whose `site_type` is `CLOSED_ENROLLED` must supply `enrolled_free_reduced_pct`, the documented share of its enrolled children who are free or reduced eligible, running from 0 to 100 inclusive; omitting it is rejected with `ERR_ENROLLED_PCT_REQUIRED`."

    Design: Corner/errors/site_intake_input_requirement_and_cap_errors_are_all_reachable
    """
    context = _approved_sponsor_with_area_record()
    sponsor_id = context["sponsor"]["id"]

    payload = create_site_payload(
        sponsor_id,
        None,
        name="Enrolled Camp Without Pct",
        site_type="CLOSED_ENROLLED",
        approved_meal_types=["LUNCH"],
    )
    response = api.create_site(payload, make_sponsor_admin_headers(sponsor_id))
    validate_error(response, ApiErrorId.ERR_ENROLLED_PCT_REQUIRED.value)

    assert _site_total_count(api, sponsor_id) == 0, (
        "a CLOSED_ENROLLED site registered without enrolled_free_reduced_pct must not persist"
    )


def test_ordinary_site_listing_five_meal_types_reports_meal_type_count_exceeded(api):
    """PRD §3.4: "Its size is capped by site type: an ordinary site may list at most two meal types, while a site whose `site_type` is `CAMP` or `MIGRANT` may list at most three provided that at least one of the three is `AM_SNACK` or `PM_SNACK`."

    PRD §3.4: "A list that breaks either bound — three types at a non-camp non-migrant site, or three types at a camp with no snack among them — is rejected with `ERR_MEAL_TYPE_COUNT_EXCEEDED`."

    Design: Corner/errors/site_intake_input_requirement_and_cap_errors_are_all_reachable
    """
    context = _approved_sponsor_with_area_record()
    sponsor_id = context["sponsor"]["id"]

    payload = create_site_payload(
        sponsor_id,
        context["area_record"]["id"],
        name="Five Meal Types Park",
        site_type="OPEN",
        approved_meal_types=["BREAKFAST", "AM_SNACK", "LUNCH", "PM_SNACK", "SUPPER"],
    )
    response = api.create_site(payload, make_sponsor_admin_headers(sponsor_id))
    validate_error(response, ApiErrorId.ERR_MEAL_TYPE_COUNT_EXCEEDED.value)

    assert _site_total_count(api, sponsor_id) == 0, (
        "an OPEN site listing five approved meal types must not persist"
    )


# --- Uniqueness keys ---------------------------------------------------------


def test_second_service_day_on_the_same_date_reports_duplicate_service_day(api):
    """PRD §3.6: "A site may hold only one live record per date: the pair of `site_id` and `service_date` must be unique across all service days whose `status` is anything other than `VOIDED`, so a repeat is rejected with `ERR_DUPLICATE_SERVICE_DAY` while a date whose earlier record was voided may be planned afresh."

    Design: Corner/errors/duplicate_key_errors_are_each_reachable
    """
    scenario = setup_program_baseline(include_budget=False)
    site_id = scenario["site"]["id"]
    create_planned_day(site_id, FIRST_SERVICE_DATE)

    payload = create_meal_service_day_payload(
        site_id,
        FIRST_SERVICE_DATE,
        [meal_service(meal_type="LUNCH", planned_meals=120,
                      service_start="14:00", service_end="15:00")],
    )
    response = api.create_meal_service_day(payload, make_site_supervisor_headers(site_id))
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SERVICE_DAY.value)

    _days, meta = validate_paginated(
        api.list_meal_service_days(REVIEWER_HEADERS, params={"site_id": site_id})
    )
    assert meta["total_count"] == 1, (
        f"the rejected repeat must leave one live service day, got {meta['total_count']}"
    )


def test_second_claim_for_the_same_month_reports_duplicate_claim_month(api):
    """PRD §3.8: "The sponsor's `application_status` must be `APPROVED`, or the create is refused with `ERR_SPONSOR_NOT_APPROVED`, and a sponsor may hold only one claim per month, so a repeat of the same `sponsor_id` and `claim_month` pair is rejected with `ERR_DUPLICATE_CLAIM_MONTH`."

    Design: Corner/errors/duplicate_key_errors_are_each_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    sponsor_id = sponsor["id"]
    set_clock(JUNE_CLAIM_CLOCK)
    create_draft_claim(sponsor_id, "2026-06")

    # The sponsor version guard is satisfied from a fresh read, so the duplicate month is the only
    # rule the second create breaks.
    payload = create_meal_claim_payload(sponsor_id, sponsor_version(sponsor_id), "2026-06")
    response = api.create_meal_claim(payload, make_sponsor_admin_headers(sponsor_id))
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM_MONTH.value)

    _claims, meta = validate_paginated(
        api.list_meal_claims(REVIEWER_HEADERS, params={"sponsor_id": sponsor_id})
    )
    assert meta["total_count"] == 1, (
        f"the sponsor must still hold exactly one June claim, got {meta['total_count']}"
    )


def test_adding_the_same_site_twice_reports_duplicate_claim_line_item(api):
    """PRD §3.8: "The claim must be in `DRAFT` or `REVISION_OPENED`, or the addition reports `ERR_CLAIM_STATE_INVALID`; the pair of `meal_claim_id` and `site_id` must be unique, so adding the same site twice reports `ERR_DUPLICATE_CLAIM_LINE_ITEM`; and the site must have at least one service day in `status` `FINALIZED` whose `service_date` falls inside `claim_month`, with an empty month rejected as `ERR_NO_FINALIZED_DAYS`."

    Design: Corner/errors/duplicate_key_errors_are_each_reachable
    """
    scenario = setup_june_claim_scenario(include_monitoring_visit=False)
    claim = scenario["claim"]
    site_id = scenario["site"]["id"]

    response = api.create_claim_line_item(
        claim["id"], {"site_id": site_id},
        make_sponsor_admin_headers(scenario["sponsor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CLAIM_LINE_ITEM.value)

    _lines, meta = validate_paginated(
        api.list_claim_line_items(REVIEWER_HEADERS, params={"meal_claim_id": claim["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the claim must still carry exactly one line item, got {meta['total_count']}"
    )


# --- Budget and advance decisions along the money path ----------------------


def test_deciding_a_draft_budget_reports_budget_state_invalid(api):
    """PRD §3.2: "Approving a `SUBMITTED` budget writes both approved ceilings from the request onto `approved_operating_cost_cents` and `approved_admin_cost_cents`, records the decision instant, and moves the budget to `APPROVED`."

    PRD §2.6: "Same-entity state legality, in this sequence: sponsor (`ERR_SPONSOR_STATE_INVALID`), budget (`ERR_BUDGET_STATE_INVALID`), advance (`ERR_ADVANCE_STATE_INVALID`), site (`ERR_SITE_STATE_INVALID`), service day (`ERR_SERVICE_DAY_STATE_INVALID`), monitoring visit (`ERR_VISIT_STATE_INVALID`), corrective action (`ERR_ACTION_STATE_INVALID`), meal claim (`ERR_CLAIM_STATE_INVALID`)."

    Design: Corner/errors/budget_and_advance_decision_fiscal_errors_are_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    budget = create_budget(sponsor["id"])

    response = api.decide_sponsor_budget(
        budget["id"],
        {
            "decision": "APPROVED",
            "approved_operating_cost_cents": 4_500_000,
            "approved_admin_cost_cents": 700_000,
        },
        REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_BUDGET_STATE_INVALID.value)

    stored = validate_success(api.get_sponsor_budget(budget["id"], REVIEWER_HEADERS))
    assert stored["status"] == "DRAFT", (
        f"the refused decision must leave the budget in DRAFT, got {stored['status']}"
    )
    assert stored.get("approved_operating_cost_cents") is None, (
        "no approved operating ceiling may be written by a refused decision"
    )


def test_approving_a_ceiling_above_the_requested_line_reports_ceiling_exceeds_request(api):
    """PRD §3.2: "Both ceiling fields are mandatory on an approval, and each must be no greater than the corresponding requested line — an approved operating ceiling above `operating_cost_budget_cents`, or an approved administrative ceiling above `admin_cost_budget_cents`, is rejected with `ERR_APPROVED_CEILING_EXCEEDS_REQUEST`."

    Design: Corner/errors/budget_and_advance_decision_fiscal_errors_are_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    budget = create_budget(
        sponsor["id"], operating_cost_budget_cents=5_000_000, admin_cost_budget_cents=800_000
    )
    submit_budget(budget)

    response = api.decide_sponsor_budget(
        budget["id"],
        {
            "decision": "APPROVED",
            "approved_operating_cost_cents": 6_000_000,
            "approved_admin_cost_cents": 700_000,
        },
        REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_APPROVED_CEILING_EXCEEDS_REQUEST.value)

    stored = validate_success(api.get_sponsor_budget(budget["id"], REVIEWER_HEADERS))
    assert stored["status"] == "SUBMITTED", (
        f"the refused approval must leave the budget SUBMITTED, got {stored['status']}"
    )


def test_approving_an_advance_above_the_requested_amount_reports_approved_exceeds_requested(api):
    """PRD §3.3: "The approved amount must not exceed `requested_amount_cents`, or the request is rejected with `ERR_APPROVED_EXCEEDS_REQUESTED`."

    Design: Corner/errors/budget_and_advance_decision_fiscal_errors_are_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    create_approved_budget(sponsor["id"])
    advance = request_advance(
        sponsor["id"], request_month="2026-06", requested_amount_cents=30_000
    )

    response = api.decide_advance_payment(
        advance["id"], {"decision": "APPROVED", "approved_amount_cents": 40_000}, REVIEWER_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_APPROVED_EXCEEDS_REQUESTED.value)

    stored = validate_success(api.get_advance_payment(advance["id"], REVIEWER_HEADERS))
    assert stored["status"] == "REQUESTED", (
        f"the refused approval must leave the advance REQUESTED, got {stored['status']}"
    )


def test_disbursing_for_a_sponsor_without_an_approved_site_reports_no_approved_site(api):
    """PRD §3.3: "It is refused unless the sponsor has at least one site whose `approval_status` is `APPROVED`, which is reported as `ERR_NO_APPROVED_SITE` — a sponsor cannot draw money before it has anywhere to serve meals."

    Design: Corner/errors/budget_and_advance_decision_fiscal_errors_are_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    create_approved_budget(sponsor["id"])
    advance = request_advance(
        sponsor["id"], request_month="2026-06", requested_amount_cents=30_000
    )
    validate_success(
        api.decide_advance_payment(
            advance["id"], {"decision": "APPROVED", "approved_amount_cents": 30_000},
            REVIEWER_HEADERS,
        )
    )

    response = api.disburse_advance_payment(advance["id"], REVIEWER_HEADERS)
    validate_error(response, ApiErrorId.ERR_NO_APPROVED_SITE.value)

    stored = validate_success(api.get_advance_payment(advance["id"], REVIEWER_HEADERS))
    assert stored["status"] == "APPROVED", (
        f"the blocked disbursement must leave the advance APPROVED, got {stored['status']}"
    )
    stored_sponsor = validate_success(
        api.get_sponsor(sponsor["id"], make_sponsor_admin_headers(sponsor["id"]))
    )
    assert stored_sponsor["advance_paid_cents"] == 0, (
        "the blocked disbursement must move no money onto the sponsor's ledger"
    )


# --- Site lifecycle gates ----------------------------------------------------


def test_registering_a_site_under_a_submitted_sponsor_reports_sponsor_not_approved(api):
    """PRD §3.4: "The sponsor must be in `application_status` `APPROVED`, or the registration is refused with `ERR_SPONSOR_NOT_APPROVED`."

    Design: Corner/errors/site_lifecycle_gating_errors_are_each_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_sponsor()
    submit_sponsor_application(sponsor)
    area_record = create_area_record()

    payload = create_site_payload(sponsor["id"], area_record["id"], name="Too Early Park")
    response = api.create_site(payload, make_sponsor_admin_headers(sponsor["id"]))
    validate_error(response, ApiErrorId.ERR_SPONSOR_NOT_APPROVED.value)

    assert _site_total_count(api, sponsor["id"]) == 0, (
        "no site may persist for a sponsor whose application is still SUBMITTED"
    )


def test_approving_a_site_whose_basis_is_not_eligible_reports_site_not_eligible(api):
    """PRD §3.5: "From `PENDING_REVIEW`, a decision of `APPROVED` moves the site to `APPROVED`; this requires that the site's `eligibility_basis` is not `UNDETERMINED`, reported as `ERR_ELIGIBILITY_NOT_DETERMINED` when the determination step was skipped, that the basis is not `NOT_ELIGIBLE`, reported as `ERR_SITE_NOT_ELIGIBLE`, and that the owning sponsor is itself in `application_status` `APPROVED`, reported as `ERR_SPONSOR_NOT_APPROVED`."

    Design: Corner/errors/site_lifecycle_gating_errors_are_each_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    low_area_record = create_area_record(
        area_code="CT-0099", data_source="SCHOOL_DATA", free_reduced_pct=30.00
    )
    site = create_site(sponsor["id"], low_area_record["id"], name="Low Income Data Park")
    determined = determine_eligibility(site["id"])
    assert determined["eligibility_basis"] == "NOT_ELIGIBLE", (
        "30.00 percent from school data must determine a NOT_ELIGIBLE basis"
    )

    response = api.decide_site_approval(site["id"], {"decision": "APPROVED"}, REVIEWER_HEADERS)
    validate_error(response, ApiErrorId.ERR_SITE_NOT_ELIGIBLE.value)

    stored = validate_success(api.get_site(site["id"], REVIEWER_HEADERS))
    assert stored["approval_status"] == "PENDING_REVIEW", (
        f"the refused approval must leave the site PENDING_REVIEW, got {stored['approval_status']}"
    )


def test_determining_eligibility_after_site_approval_reports_site_state_invalid(api):
    """PRD §3.4: "Eligibility itself is determined by the state agency in a separate step, and it is available only while the site's `approval_status` is still `PENDING_REVIEW`; attempting it later is rejected with `ERR_SITE_STATE_INVALID`."

    Design: Corner/errors/site_lifecycle_gating_errors_are_each_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    area_record = create_area_record()
    site = create_approved_site(sponsor["id"], area_record["id"])
    assert site["approval_status"] == "APPROVED", "the site must be APPROVED before the trigger"

    response = api.determine_site_eligibility(site["id"], REVIEWER_HEADERS)
    validate_error(response, ApiErrorId.ERR_SITE_STATE_INVALID.value)


def test_moving_a_denied_site_to_operating_reports_site_not_approved(api):
    """PRD §3.5: "Moving from `NOT_STARTED` to `OPERATING` requires that the acting `SponsorAdmin` owns the site and that the site's `approval_status` is `APPROVED`: a site still in `PENDING_REVIEW` or already `DENIED` is rejected with `ERR_SITE_NOT_APPROVED`, and a site in `SUSPENDED` is rejected with `ERR_SITE_SUSPENDED`."

    Design: Corner/errors/site_lifecycle_gating_errors_are_each_reachable
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    low_area_record = create_area_record(
        area_code="CT-0099", data_source="SCHOOL_DATA", free_reduced_pct=30.00
    )
    site = create_site(sponsor["id"], low_area_record["id"], name="Low Income Data Park")
    determine_eligibility(site["id"])
    denied = validate_success(
        api.decide_site_approval(
            site["id"],
            {"decision": "DENIED", "reason": "Area income data below the school-data threshold."},
            REVIEWER_HEADERS,
        )
    )
    assert denied["approval_status"] == "DENIED", "the site must be DENIED before the trigger"

    response = api.set_site_operating_status(
        site["id"], {"to_status": "OPERATING"}, make_sponsor_admin_headers(sponsor["id"])
    )
    validate_error(response, ApiErrorId.ERR_SITE_NOT_APPROVED.value)

    stored = validate_success(api.get_site(site["id"], REVIEWER_HEADERS))
    assert stored["operating_status"] == "NOT_STARTED", (
        f"the refused move must leave operating_status NOT_STARTED, got {stored['operating_status']}"
    )
    assert stored.get("first_operating_date") is None, (
        "a site that never served a meal must keep a null first_operating_date"
    )


def test_opening_a_day_at_a_non_operating_site_reports_site_not_operating(api):
    """PRD §3.6: "The site must have cleared review, so a site in `PENDING_REVIEW` or `DENIED` produces `ERR_SITE_NOT_APPROVED` and a site in `SUSPENDED` produces `ERR_SITE_SUSPENDED`; the site's `operating_status` must be `OPERATING`, or the attempt reports `ERR_SITE_NOT_OPERATING`."

    Design: Corner/errors/site_lifecycle_gating_errors_are_each_reachable
    """
    scenario = setup_program_baseline(include_budget=False, operating=False)
    site_id = scenario["site"]["id"]
    set_clock(FIRST_SERVICE_CLOCK)
    day = create_planned_day(site_id, FIRST_SERVICE_DATE)

    response = api.open_meal_service_day(
        day["id"],
        open_day_payload(production_counts={"LUNCH": 150}, food_received_at=FOOD_RECEIVED_AT),
        make_site_supervisor_headers(site_id),
    )
    validate_error(response, ApiErrorId.ERR_SITE_NOT_OPERATING.value)

    stored = validate_success(api.get_meal_service_day(day["id"], REVIEWER_HEADERS))
    assert stored["status"] == "PLANNED", (
        f"the refused open must leave the day PLANNED, got {stored['status']}"
    )
    assert stored.get("food_received_at") is None, (
        "a refused open must not store food_received_at"
    )


# --- Ordering rules on holding logs, visits and corrective actions -----------


def test_holding_log_measured_before_food_received_reports_measured_before_food_received(api):
    """PRD §3.6: "The reading's `meal_type` must be among the site's `approved_meal_types`, or the log is rejected with `ERR_MEAL_TYPE_NOT_APPROVED`, and `measured_at` must be at or after the day's `food_received_at`, with an earlier instant rejected as `ERR_MEASURED_BEFORE_FOOD_RECEIVED`."

    Design: Corner/errors/holding_log_visit_and_action_timing_errors_are_reachable
    """
    scenario = setup_program_baseline(include_budget=False)
    site_id = scenario["site"]["id"]
    day = create_open_day(
        site_id, FIRST_SERVICE_DATE,
        production_counts={"LUNCH": 150}, food_received_at=FOOD_RECEIVED_AT,
    )

    response = api.create_holding_log(
        day["id"],
        {
            "meal_type": "LUNCH",
            "temperature_class": "COLD",
            "temperature_f": 39.0,
            "measured_at": "2026-06-08T10:00:00Z",
        },
        make_site_supervisor_headers(site_id),
    )
    validate_error(response, ApiErrorId.ERR_MEASURED_BEFORE_FOOD_RECEIVED.value)

    _entries, meta = validate_paginated(
        api.list_holding_log_entries(REVIEWER_HEADERS, params={"meal_service_day_id": day["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the rejected reading must not be stored, got {meta['total_count']} entries"
    )
    stored_day = validate_success(api.get_meal_service_day(day["id"], REVIEWER_HEADERS))
    assert stored_day["food_safety_status"] == "OK", (
        "a rejected reading must never evaluate the holding band"
    )


def test_conducting_a_visit_before_its_scheduled_date_reports_visit_date_not_reached(api):
    """PRD §3.7: "The visit must still be `SCHEDULED`, or the attempt reports `ERR_VISIT_STATE_INVALID`, and the logical clock's current date must have reached the `scheduled_date`; an attempt to conduct a visit before its scheduled day arrives is rejected with `ERR_VISIT_DATE_NOT_REACHED`, while conducting it on that exact date is permitted."

    Design: Corner/errors/holding_log_visit_and_action_timing_errors_are_reachable
    """
    scenario = setup_program_baseline(include_budget=False)
    visit = schedule_visit(
        scenario["site"]["id"], monitor_user_id="mon_1", visit_type="FIRST_WEEK",
        scheduled_date=VISIT_DATE, window_start="09:00", window_end="11:00",
    )

    # The clock still reads 2026-06-08, two days before the visit's scheduled date.
    response = api.conduct_monitoring_visit(visit["id"], make_field_monitor_headers("mon_1"))
    validate_error(response, ApiErrorId.ERR_VISIT_DATE_NOT_REACHED.value)

    stored = validate_success(api.get_monitoring_visit(visit["id"], REVIEWER_HEADERS))
    assert stored["status"] == "SCHEDULED", (
        f"the premature attempt must leave the visit SCHEDULED, got {stored['status']}"
    )
    assert stored.get("conducted_at") is None, (
        "a refused conduct must not stamp conducted_at"
    )


def test_responding_to_a_closed_corrective_action_reports_action_state_invalid(api):
    """PRD §3.7: "Only the `SponsorAdmin` who owns the site behind the action's `site_id` may respond, so a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`, and an action in any other status reports `ERR_ACTION_STATE_INVALID`."

    PRD §3.7: "A response is accepted from `OPEN` or from `REJECTED` — the second case is the rejection loop, and it simply overwrites the previously stored `response_note` and `evidence_ref` — and either way the action moves to `RESPONSE_SUBMITTED`."

    Design: Corner/errors/holding_log_visit_and_action_timing_errors_are_reachable
    """
    scenario = setup_program_baseline(include_budget=False)
    site_id = scenario["site"]["id"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])
    create_reported_visit(
        site_id,
        findings=[finding(finding_code="SIGNAGE_MISSING", severity="MINOR")],
        scheduled_date=VISIT_DATE,
        conduct_clock=VISIT_CLOCK,
        monitor_user_id="mon_1",
    )
    action = list_actions_for_site(site_id)[0]

    responded = validate_success(
        api.respond_corrective_action(
            action["id"],
            {
                "response_note": "Permanent SFSP signage installed at both entrances.",
                "evidence_ref": "photo-2026-06-10-01",
            },
            sponsor_headers,
        )
    )
    assert responded["status"] == "RESPONSE_SUBMITTED", (
        f"the response must move the action to RESPONSE_SUBMITTED, got {responded['status']}"
    )
    # A monitor other than the one who opened the action may review it.
    reviewed = validate_success(
        api.review_corrective_action(
            action["id"], {"decision": "CLOSED"}, make_field_monitor_headers("mon_2")
        )
    )
    assert reviewed["status"] == "CLOSED", (
        f"accepting the response must close the action, got {reviewed['status']}"
    )

    response = api.respond_corrective_action(
        action["id"], {"response_note": "Duplicate response after closure."}, sponsor_headers
    )
    validate_error(response, ApiErrorId.ERR_ACTION_STATE_INVALID.value)

    stored = validate_success(api.get_corrective_action(action["id"], REVIEWER_HEADERS))
    assert stored["status"] == "CLOSED", (
        f"the refused response must leave the action CLOSED, got {stored['status']}"
    )
    assert stored["response_note"] == "Permanent SFSP signage installed at both entrances.", (
        "the refused response must not overwrite the stored response_note"
    )


# --- Assembling and submitting a monthly claim ------------------------------


def test_line_item_for_a_site_with_no_finalized_day_reports_no_finalized_days(api):
    """PRD §3.8: "The claim must be in `DRAFT` or `REVISION_OPENED`, or the addition reports `ERR_CLAIM_STATE_INVALID`; the pair of `meal_claim_id` and `site_id` must be unique, so adding the same site twice reports `ERR_DUPLICATE_CLAIM_LINE_ITEM`; and the site must have at least one service day in `status` `FINALIZED` whose `service_date` falls inside `claim_month`, with an empty month rejected as `ERR_NO_FINALIZED_DAYS`."

    Design: Corner/errors/claim_assembly_errors_for_empty_site_admin_ceiling_and_hold
    """
    scenario = setup_program_baseline()
    sponsor_id = scenario["sponsor"]["id"]
    empty_site_id = scenario["site"]["id"]
    set_clock(JUNE_CLAIM_CLOCK)
    claim = create_draft_claim(sponsor_id, "2026-06")

    response = api.create_claim_line_item(
        claim["id"], {"site_id": empty_site_id}, make_sponsor_admin_headers(sponsor_id)
    )
    validate_error(response, ApiErrorId.ERR_NO_FINALIZED_DAYS.value)

    _lines, meta = validate_paginated(
        api.list_claim_line_items(REVIEWER_HEADERS, params={"meal_claim_id": claim["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a site with no finalized June day must add no line, got {meta['total_count']}"
    )


def test_submitting_admin_costs_above_the_approved_ceiling_reports_admin_cost_exceeds_budget(api):
    """PRD §3.8: "Finally the asserted costs are tested against the approved ceilings: `claimed_operating_cost_cents` above `approved_operating_cost_cents` is rejected with `ERR_OPERATING_COST_EXCEEDS_BUDGET`, and `claimed_admin_cost_cents` above `approved_admin_cost_cents` with `ERR_ADMIN_COST_EXCEEDS_BUDGET`, each ceiling permitting equality."

    Design: Corner/errors/claim_assembly_errors_for_empty_site_admin_ceiling_and_hold
    """
    scenario = setup_june_claim_scenario(include_monitoring_visit=False)
    claim = scenario["claim"]

    # The approved administrative ceiling is 700000 cents; the operating figure stays well inside
    # its own ceiling so the administrative line is the only offending value.
    response = api.submit_meal_claim(
        claim["id"],
        {"claimed_operating_cost_cents": 20_000, "claimed_admin_cost_cents": 800_000},
        make_sponsor_admin_headers(scenario["sponsor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ADMIN_COST_EXCEEDS_BUDGET.value)

    stored = validate_success(api.get_meal_claim(claim["id"], REVIEWER_HEADERS))
    assert stored["status"] == "DRAFT", (
        f"the refused submission must leave the claim DRAFT, got {stored['status']}"
    )
    assert stored.get("submitted_at") is None, (
        "a refused submission must not stamp submitted_at"
    )


def test_submitting_a_claim_holding_a_suspended_site_reports_claim_hold_blocking(api):
    """PRD §3.8: "Its `blocking_hold_count` must be 0, meaning no line item's site sits on claim hold; a claim with any held site is refused with `ERR_CLAIM_HOLD_BLOCKING`."

    Design: Corner/errors/claim_assembly_errors_for_empty_site_admin_ceiling_and_hold
    """
    scenario = setup_june_claim_scenario(
        include_monitoring_visit=False, add_line_items=False
    )
    claim = scenario["claim"]
    site_id = scenario["site"]["id"]
    sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])

    suspended = validate_success(
        api.decide_site_approval(
            site_id,
            {"decision": "SUSPENDED", "reason": "Unannounced review found meals served offsite."},
            REVIEWER_HEADERS,
        )
    )
    assert suspended["claim_hold"] is True, "suspension must raise the site's claim_hold"

    line_item = add_line_item(claim, site_id)
    assert line_item["hold_flag"] is True, (
        "a new line item copies hold_flag from the site's current claim_hold"
    )

    # Both asserted costs sit inside their approved ceilings, so the hold is the only rule broken.
    response = api.submit_meal_claim(
        claim["id"],
        {"claimed_operating_cost_cents": 20_000, "claimed_admin_cost_cents": 5_000},
        sponsor_headers,
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_HOLD_BLOCKING.value)

    stored = validate_success(api.get_meal_claim(claim["id"], REVIEWER_HEADERS))
    assert stored["status"] == "DRAFT", (
        f"the refused submission must leave the claim DRAFT, got {stored['status']}"
    )
    assert stored.get("submitted_at") is None, (
        "a refused submission must not stamp submitted_at"
    )
    assert stored.get("preliminary_reimbursement_cents") is None, (
        "a refused submission must not compute the preliminary reimbursement"
    )
