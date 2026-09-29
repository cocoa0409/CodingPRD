"""Authentication, role authorization, ownership and segregation of duties.

Every request to this API declares an acting principal and the capacity it acts in, and the API
rejects in a fixed order: an unrecognised or missing role first, then a role that the target
endpoint does not authorize, then a caller acting on a resource it does not own, then a monitor
reviewing the corrective action it opened itself. The tests below drive each of those gates from
both sides — the refusal and the matching permitted call — and check that a refused write leaves
every row it touched exactly as it was.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    close_day,
    conduct_visit,
    create_approved_site,
    create_approved_sponsor,
    create_area_record,
    create_budget,
    create_meal_count_payload,
    create_meal_service_day_payload,
    create_monitoring_visit_payload,
    create_open_day,
    create_planned_day,
    create_reported_visit,
    create_site,
    create_site_payload,
    create_sponsor,
    create_sponsor_payload,
    finding,
    get_success_data,
    list_actions_for_site,
    make_field_monitor_headers,
    make_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    meal_service,
    open_day_payload,
    schedule_visit,
    set_clock,
    setup_program_baseline,
    submit_sponsor_application,
    validate_error,
    validate_paginated,
    validate_success,
    visit_report_payload,
)

REVIEWER_HEADERS = make_state_agency_reviewer_headers()

# A request carrying neither X-User-ID nor X-User-Role.
NO_AUTH_HEADERS: dict = {}

INTAKE_CLOCK = "2026-06-01T00:00:00Z"
FIRST_SERVICE_CLOCK = "2026-06-08T08:00:00Z"
VISIT_CLOCK = "2026-06-10T09:00:00Z"
FIRST_SERVICE_DATE = "2026-06-08"
VISIT_DATE = "2026-06-10"
FIRST_WEEK_DUE_DATE = "2026-06-12"
MONITOR_ONE = "mon_1"
MONITOR_TWO = "mon_2"


# --- Shared scenario builders (compositions of the granular helpers) ---------


def _second_sponsor() -> dict:
    """A second approved sponsor, so a foreign SponsorAdmin identity genuinely exists."""
    return create_approved_sponsor(
        legal_name="Lakeside Parks District", sponsor_type="GOVERNMENT"
    )


def _operating_site_scenario() -> dict:
    """Approved sponsor with one approved, operating rural self-prep site, clock on the first
    service date."""
    return setup_program_baseline(include_budget=False)


def _closed_day_scenario() -> dict:
    """The operating-site scenario carried through a day that has been opened and closed, so it
    sits in CLOSED awaiting the sponsor's finalization."""
    scenario = _operating_site_scenario()
    day = create_open_day(scenario["site"]["id"], FIRST_SERVICE_DATE)
    scenario["day"] = close_day(day)
    return scenario


def _conducted_visit_scenario() -> dict:
    """The operating-site scenario with one FIRST_WEEK visit already conducted by mon_1."""
    scenario = _operating_site_scenario()
    visit = schedule_visit(
        scenario["site"]["id"], monitor_user_id=MONITOR_ONE, scheduled_date=VISIT_DATE
    )
    set_clock(VISIT_CLOCK)
    scenario["visit"] = conduct_visit(visit)
    return scenario


# --- Each role is refused an operation another role owns exclusively ---------


def test_sponsor_admin_cannot_decide_a_sponsor_application(api):
    """PRD §2.1: "A well-authenticated request whose role is not among the roles authorized for the endpoint it targets is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/each_role_cannot_invoke_another_roles_exclusive_operation
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_sponsor(
        legal_name="Pending Review Sponsor", experience_status="NEW", advance_eligible=False
    )
    submit_sponsor_application(sponsor)

    response = api.decide_sponsor_application(
        sponsor["id"], {"decision": "APPROVED"}, make_sponsor_admin_headers(sponsor["id"])
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    after = validate_success(api.get_sponsor(sponsor["id"], REVIEWER_HEADERS))
    assert after["application_status"] == "SUBMITTED", (
        "a SponsorAdmin's rejected review decision must leave the application in SUBMITTED, got "
        f"{after['application_status']}"
    )


def test_site_supervisor_cannot_finalize_a_closed_service_day(api):
    """PRD §2.10: "A `SiteSupervisor` records point-of-service counts and closes a day's counting but cannot finalize the day for claiming; finalization belongs to the `SponsorAdmin`."

    Design: Corner/rbac/each_role_cannot_invoke_another_roles_exclusive_operation
    """
    scenario = _closed_day_scenario()
    day = scenario["day"]

    response = api.finalize_meal_service_day(
        day["id"], make_site_supervisor_headers(scenario["site"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    after = validate_success(api.get_meal_service_day(day["id"], REVIEWER_HEADERS))
    assert after["status"] == "CLOSED", (
        f"the day must stay CLOSED rather than reach FINALIZED, got {after['status']}"
    )


def test_field_monitor_cannot_open_a_planned_service_day(api):
    """PRD §2.1: "A well-authenticated request whose role is not among the roles authorized for the endpoint it targets is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/each_role_cannot_invoke_another_roles_exclusive_operation
    """
    scenario = _operating_site_scenario()
    day = create_planned_day(scenario["site"]["id"], FIRST_SERVICE_DATE)

    response = api.open_meal_service_day(
        day["id"],
        open_day_payload(production_counts={"LUNCH": 150},
                         food_received_at=f"{FIRST_SERVICE_DATE}T10:30:00Z"),
        make_field_monitor_headers(MONITOR_ONE),
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    after = validate_success(api.get_meal_service_day(day["id"], REVIEWER_HEADERS))
    assert after["status"] == "PLANNED", (
        f"the day must stay PLANNED after a monitor's rejected open, got {after['status']}"
    )
    assert after.get("food_received_at") is None, (
        "a rejected open must not record food_received_at, got "
        f"{after.get('food_received_at')!r}"
    )


def test_state_agency_reviewer_cannot_file_a_visit_report(api):
    """PRD §2.1: "A well-authenticated request whose role is not among the roles authorized for the endpoint it targets is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/each_role_cannot_invoke_another_roles_exclusive_operation
    """
    scenario = _conducted_visit_scenario()
    visit = scenario["visit"]

    response = api.report_monitoring_visit(
        visit["id"], visit_report_payload([]), REVIEWER_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    after = validate_success(api.get_monitoring_visit(visit["id"], REVIEWER_HEADERS))
    assert after["status"] == "CONDUCTED", (
        "the reviewer's rejected report must leave the visit in CONDUCTED, got "
        f"{after['status']}"
    )


# --- Ownership is resolved on the resource, directly and transitively --------


def test_sponsor_admin_cannot_submit_another_sponsors_budget(api):
    """PRD §2.1: "A mismatch on any `SponsorAdmin` or `SiteSupervisor` write endpoint is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/sponsor_admin_cannot_act_on_another_sponsors_resources
    """
    set_clock(INTAKE_CLOCK)
    sponsor_a = create_approved_sponsor()
    sponsor_b = _second_sponsor()
    budget = create_budget(sponsor_a["id"])

    response = api.submit_sponsor_budget(
        budget["id"], make_sponsor_admin_headers(sponsor_b["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    after = validate_success(api.get_sponsor_budget(budget["id"], REVIEWER_HEADERS))
    assert after["status"] == "DRAFT", (
        f"sponsor A's budget must stay DRAFT after B's rejected submission, got {after['status']}"
    )
    assert after["version"] == budget["version"], (
        "a rejected submission must not mutate the budget row, version moved from "
        f"{budget['version']} to {after['version']}"
    )


def test_sponsor_admin_cannot_finalize_a_day_of_another_sponsors_site(api):
    """PRD §2.1: "A mismatch on any `SponsorAdmin` or `SiteSupervisor` write endpoint is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/sponsor_admin_cannot_act_on_another_sponsors_resources
    """
    scenario = _closed_day_scenario()
    sponsor_b = _second_sponsor()
    day = scenario["day"]

    response = api.finalize_meal_service_day(
        day["id"], make_sponsor_admin_headers(sponsor_b["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    after = validate_success(api.get_meal_service_day(day["id"], REVIEWER_HEADERS))
    assert after["status"] == "CLOSED", (
        "the day of sponsor A's site must stay CLOSED after sponsor B's rejected finalize, got "
        f"{after['status']}"
    )


def test_site_supervisor_cannot_post_counts_on_another_sites_day(api):
    """PRD §2.1: "When `X-User-Role` is `SiteSupervisor`, `X-User-ID` is the `id` of the acting `Site`; ownership checks compare the resource's site reference to `X-User-ID` — directly on a site, or through `MealServiceDay.site_id`."

    Design: Corner/rbac/sponsor_admin_cannot_act_on_another_sponsors_resources
    """
    scenario = _operating_site_scenario()
    sponsor_b = _second_sponsor()
    area_record_b = create_area_record(area_code="CT-0044")
    site_b1 = create_approved_site(
        sponsor_b["id"], area_record_b["id"], name="Lakeside Beach House"
    )
    day = create_open_day(scenario["site"]["id"], FIRST_SERVICE_DATE)

    response = api.create_meal_count(
        day["id"],
        create_meal_count_payload(meal_type="LUNCH", first_meals=12),
        make_site_supervisor_headers(site_b1["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    after = validate_success(api.get_meal_service_day(day["id"], REVIEWER_HEADERS))
    assert after["counted_first_meals"] == 0, (
        "a foreign supervisor's rejected count must leave counted_first_meals at 0, got "
        f"{after['counted_first_meals']}"
    )
    _, meta = validate_paginated(
        api.list_meal_count_entries(
            REVIEWER_HEADERS, params={"meal_service_day_id": day["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the rejected count must not persist an entry row, got total_count {meta['total_count']}"
    )


# --- Segregation of duties on corrective-action review -----------------------


def test_monitor_who_opened_the_action_cannot_review_it_but_another_monitor_can(api):
    """PRD §3.7: "A monitor then reviews the submitted response with a `decision` of either `CLOSED` or `REJECTED`, and the reviewer may not be the person who opened the action: when the acting `X-User-ID` equals the action's `opened_by_user_id` the review is refused with `ERR_SEGREGATION_OF_DUTIES`, which is the enforcement point for the principle stated in §2.10."

    PRD §3.7: "Accepting the response moves the action to `CLOSED` and stamps `closed_by_user_id` with the reviewing monitor, and two things may follow from that closure."

    PRD §3.7: "And if every action sharing the same `monitoring_visit_id` is now `CLOSED`, the originating visit bubbles up on its own from `REPORT_FILED` to `CLOSED`."

    Design: Corner/rbac/field_monitor_cannot_review_an_action_it_opened
    """
    scenario = _operating_site_scenario()
    site_id = scenario["site"]["id"]
    visit = create_reported_visit(
        site_id,
        findings=[finding(finding_code="SIGNAGE_MISSING", severity="MINOR")],
        monitor_user_id=MONITOR_ONE,
        scheduled_date=VISIT_DATE,
    )

    actions = list_actions_for_site(site_id)
    assert len(actions) == 1, (
        f"the MINOR finding must open exactly one corrective action, got {len(actions)}"
    )
    action = actions[0]
    assert action["opened_by_user_id"] == MONITOR_ONE, (
        "the action must record the reporting monitor as opened_by_user_id, got "
        f"{action['opened_by_user_id']}"
    )

    responded = get_success_data(
        api.respond_corrective_action(
            action["id"],
            {"response_note": "Signage installed at both entrances."},
            make_sponsor_admin_headers(scenario["sponsor"]["id"]),
        )
    )
    assert responded["status"] == "RESPONSE_SUBMITTED", (
        f"the sponsor's response must move the action to RESPONSE_SUBMITTED, got {responded['status']}"
    )

    refused = api.review_corrective_action(
        action["id"], {"decision": "CLOSED"}, make_field_monitor_headers(MONITOR_ONE)
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    still_open = validate_success(api.get_corrective_action(action["id"], REVIEWER_HEADERS))
    assert still_open["status"] == "RESPONSE_SUBMITTED", (
        "the refused review must leave the action in RESPONSE_SUBMITTED, got "
        f"{still_open['status']}"
    )
    assert still_open.get("closed_by_user_id") is None, (
        "the refused review must not stamp closed_by_user_id, got "
        f"{still_open.get('closed_by_user_id')!r}"
    )
    unbubbled = validate_success(api.get_monitoring_visit(visit["id"], REVIEWER_HEADERS))
    assert unbubbled["status"] == "REPORT_FILED", (
        f"no bubble-up may happen while the action is open, got visit status {unbubbled['status']}"
    )

    closed = validate_success(
        api.review_corrective_action(
            action["id"], {"decision": "CLOSED"}, make_field_monitor_headers(MONITOR_TWO)
        )
    )
    assert closed["status"] == "CLOSED", (
        f"a different monitor must be able to close the action, got {closed['status']}"
    )
    assert closed["closed_by_user_id"] == MONITOR_TWO, (
        "closed_by_user_id must be the reviewing monitor, got "
        f"{closed['closed_by_user_id']}"
    )

    bubbled = validate_success(api.get_monitoring_visit(visit["id"], REVIEWER_HEADERS))
    assert bubbled["status"] == "CLOSED", (
        "the visit must bubble up from REPORT_FILED to CLOSED once its only action closed, got "
        f"{bubbled['status']}"
    )


# --- Authentication precedes every other check ------------------------------


def test_request_without_role_headers_is_rejected_as_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not one of those four strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.6: "More generally, a request passes through a fixed gauntlet, and the *first* check that fails determines the response."

    Design: Corner/rbac/request_without_a_declared_role_header_is_rejected_with_401
    """
    set_clock(INTAKE_CLOCK)

    write = api.create_sponsor(
        create_sponsor_payload(legal_name="Anonymous Attempt", experience_status="NEW",
                               advance_eligible=False),
        NO_AUTH_HEADERS,
    )
    validate_error(write, ApiErrorId.ERR_UNAUTHENTICATED.value)

    read = api.get_sponsor(NON_EXISTENT_UUID, NO_AUTH_HEADERS)
    validate_error(read, ApiErrorId.ERR_UNAUTHENTICATED.value)

    _, meta = validate_paginated(
        api.list_sites(REVIEWER_HEADERS, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"the unauthenticated write must have persisted nothing, got total_count {meta['total_count']}"
    )


def test_request_with_an_undeclared_role_is_rejected_as_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or whose `X-User-Role` is not one of those four strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_without_a_declared_role_header_is_rejected_with_401
    """
    set_clock(INTAKE_CLOCK)

    write = api.create_sponsor(
        create_sponsor_payload(legal_name="Undeclared Role Attempt"),
        make_headers("aud_1", "ProgramAuditor"),
    )
    validate_error(write, ApiErrorId.ERR_UNAUTHENTICATED.value)

    read = api.get_sponsor(NON_EXISTENT_UUID, make_headers("aud_1", "ProgramAuditor"))
    validate_error(read, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --- Every role performs the operation it owns exclusively -------------------


def test_state_agency_reviewer_registers_a_sponsor_in_draft(api):
    """PRD §3.1: "The new record begins in `application_status` `DRAFT` with `version` 1, and its four ledger counters — `advance_paid_cents`, `advance_recovered_cents`, `advance_outstanding_cents` and `reimbursement_paid_cents` — all begin at 0."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_operation
    """
    set_clock(INTAKE_CLOCK)

    sponsor = validate_success(api.create_sponsor(create_sponsor_payload(), REVIEWER_HEADERS), 201)

    assert sponsor["application_status"] == "DRAFT", (
        f"a registered sponsor must open in DRAFT, got {sponsor['application_status']}"
    )
    assert sponsor["version"] == 1, (
        f"a registered sponsor must open at version 1, got {sponsor['version']}"
    )
    for ledger_field in ("advance_paid_cents", "advance_recovered_cents",
                         "advance_outstanding_cents", "reimbursement_paid_cents"):
        assert sponsor[ledger_field] == 0, (
            f"{ledger_field} must begin at 0, got {sponsor[ledger_field]}"
        )


def test_sponsor_admin_registers_a_site_under_its_own_sponsor(api):
    """PRD §3.4: "A new site opens with `approval_status` `PENDING_REVIEW`, `operating_status` `NOT_STARTED`, `eligibility_basis` `UNDETERMINED`, `claim_hold` false, and `compliance_flag_count` and `voided_day_count` both at 0."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_operation
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    area_record = create_area_record()

    site = validate_success(
        api.create_site(
            create_site_payload(sponsor["id"], area_record["id"]),
            make_sponsor_admin_headers(sponsor["id"]),
        ),
        201,
    )

    assert site["sponsor_id"] == sponsor["id"], (
        f"the site must be registered under the acting sponsor, got {site['sponsor_id']}"
    )
    assert site["approval_status"] == "PENDING_REVIEW", (
        f"a new site must open in PENDING_REVIEW, got {site['approval_status']}"
    )
    assert site["operating_status"] == "NOT_STARTED", (
        f"a new site must open in NOT_STARTED, got {site['operating_status']}"
    )
    assert site["eligibility_basis"] == "UNDETERMINED", (
        f"a new site must open UNDETERMINED, got {site['eligibility_basis']}"
    )
    assert site["claim_hold"] is False, (
        f"a new site must open with claim_hold false, got {site['claim_hold']}"
    )
    assert site["compliance_flag_count"] == 0, (
        f"compliance_flag_count must begin at 0, got {site['compliance_flag_count']}"
    )
    assert site["voided_day_count"] == 0, (
        f"voided_day_count must begin at 0, got {site['voided_day_count']}"
    )


def test_state_agency_reviewer_determines_eligibility_and_approves_the_site(api):
    """PRD §3.4: "Otherwise, if the record's `data_source` is `SCHOOL_DATA`, the basis is `AREA_ELIGIBLE` when the percentage is at least 50.00 and `NOT_ELIGIBLE` otherwise."

    PRD §3.5: "The approval axis is driven by the state agency through a single decision that carries a `decision` value and an optional `reason`, and it never touches `operating_status`."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_operation
    """
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    area_record = create_area_record()
    site = create_site(sponsor["id"], area_record["id"])

    determined = validate_success(
        api.determine_site_eligibility(site["id"], REVIEWER_HEADERS)
    )
    assert determined["eligibility_basis"] == "AREA_ELIGIBLE", (
        "62.50 percent school data must yield AREA_ELIGIBLE, got "
        f"{determined['eligibility_basis']}"
    )
    assert float(determined["eligibility_pct_used"]) == 62.50, (
        "eligibility_pct_used must take the area record's percentage, got "
        f"{determined['eligibility_pct_used']}"
    )

    approved = validate_success(
        api.decide_site_approval(site["id"], {"decision": "APPROVED"}, REVIEWER_HEADERS)
    )
    assert approved["approval_status"] == "APPROVED", (
        f"the reviewer's decision must approve the site, got {approved['approval_status']}"
    )
    assert approved["operating_status"] == "NOT_STARTED", (
        "the approval axis must leave the operating axis untouched, got "
        f"{approved['operating_status']}"
    )


def test_site_supervisor_plans_a_service_day_for_its_own_site(api):
    """PRD §3.6: "A newly planned day opens in `status` `PLANNED` with `food_safety_status` `OK`, `production_counts` and `food_received_at` both null, every counted and derived meal counter at 0, and its own `production_mode` copied from the site's `production_mode` at that moment and frozen thereafter — later changes at the site level never reach a day already planned."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_operation
    """
    scenario = _operating_site_scenario()
    site = scenario["site"]

    day = validate_success(
        api.create_meal_service_day(
            create_meal_service_day_payload(
                site["id"], FIRST_SERVICE_DATE,
                [meal_service(meal_type="LUNCH", planned_meals=150,
                              service_start="11:30", service_end="12:30")],
            ),
            make_site_supervisor_headers(site["id"]),
        ),
        201,
    )

    assert day["site_id"] == site["id"], (
        f"the day must belong to the acting supervisor's site, got {day['site_id']}"
    )
    assert day["status"] == "PLANNED", (
        f"a newly planned day must open in PLANNED, got {day['status']}"
    )
    assert day["food_safety_status"] == "OK", (
        f"a newly planned day must open with food_safety_status OK, got {day['food_safety_status']}"
    )
    assert day.get("production_counts") is None, (
        f"production_counts must be null before the day opens, got {day.get('production_counts')!r}"
    )
    assert day.get("food_received_at") is None, (
        f"food_received_at must be null before the day opens, got {day.get('food_received_at')!r}"
    )
    assert day["production_mode"] == "SELF_PREP", (
        "the day must freeze the site's production_mode at planning time, got "
        f"{day['production_mode']}"
    )
    for counter in ("counted_first_meals", "counted_second_meals", "counted_adult_meals",
                    "reimbursable_meals", "non_reimbursable_meals"):
        assert day[counter] == 0, f"{counter} must begin at 0, got {day[counter]}"


def test_field_monitor_schedules_a_first_week_visit_with_its_derived_due_date(api):
    """PRD §3.7: "A new visit begins in `status` `SCHEDULED` with `is_late` false."

    PRD §3.7: "Otherwise, a `FIRST_WEEK` visit is due 4 days after `first_operating_date`, a `FULL_REVIEW` visit is due 28 days after `first_operating_date`, and a `FOLLOW_UP` visit is simply due on its own `scheduled_date`."

    PRD §3.5: "`first_operating_date` is not written when the operating axis moves; it is written when service actually begins, and it holds the earliest `service_date` among the site's service days that have ever reached `OPEN`."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_operation
    """
    scenario = _operating_site_scenario()
    site = scenario["site"]
    create_open_day(site["id"], FIRST_SERVICE_DATE)

    serving_site = validate_success(api.get_site(site["id"], REVIEWER_HEADERS))
    assert serving_site["first_operating_date"] == FIRST_SERVICE_DATE, (
        "first_operating_date must hold the earliest service date that reached OPEN, got "
        f"{serving_site['first_operating_date']}"
    )

    visit = validate_success(
        api.create_monitoring_visit(
            create_monitoring_visit_payload(
                site["id"], MONITOR_ONE, visit_type="FIRST_WEEK",
                scheduled_date=VISIT_DATE, window_start="09:00", window_end="11:00",
            ),
            make_field_monitor_headers(MONITOR_ONE),
        ),
        201,
    )

    assert visit["site_id"] == site["id"], (
        f"the visit must target the requested site, got {visit['site_id']}"
    )
    assert visit["monitor_user_id"] == MONITOR_ONE, (
        f"the visit must record the named monitor, got {visit['monitor_user_id']}"
    )
    assert visit["status"] == "SCHEDULED", (
        f"a new visit must begin in SCHEDULED, got {visit['status']}"
    )
    assert visit["is_late"] is False, (
        f"a new visit must begin with is_late false, got {visit['is_late']}"
    )
    assert visit["due_date"] == FIRST_WEEK_DUE_DATE, (
        "a FIRST_WEEK visit is due four days after first_operating_date 2026-06-08, expected "
        f"{FIRST_WEEK_DUE_DATE}, got {visit['due_date']}"
    )
