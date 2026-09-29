"""Error-trigger coverage for the mitigation banking API.

Each test drives one rejected request all the way through the PRD's validation
pipeline and then re-reads the affected rows to prove the refusal left the world
untouched: no state transition, no ledger append, no derived aggregate moved.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_cents,
    assert_credits,
    assert_ledger_shape,
    assert_score,
    build_user_headers,
    create_bank_payload,
    create_monitoring_report_payload,
    file_and_accept_monitoring_report,
    get_success_data,
    inspect_payload,
    make_sponsor_headers,
    register_sponsor,
    remedial_actions_for_report,
    review_report_payload,
    add_milestone,
    approve_release_payload,
    bank_state,
    bank_version,
    claim_milestone,
    quote_credits,
    reserve_sale,
    execute_sale,
    assign_sale,
    set_clock,
    setup_bank_under_review,
    setup_draft_bank,
    setup_executed_bank,
    setup_sellable_bank,
    validate_error,
    validate_paginated,
    validate_success,
)

# A year-3 monitoring year that misses three of the four effective standards:
# 96 of 120 hydroperiod days, 20.0 percent invasive cover against a 10.0 ceiling,
# 60.0 percent native cover against an 80.0 floor and exactly 400 stems per acre.
FAILING_YEAR3_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 96},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 20.0},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 60.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 400},
]


def _bank_with_open_remedial_action():
    """A sellable bank whose year-3 report is ACCEPTED with a compliance status
    of FAIL, so exactly one remedial action stands OPEN against it."""
    world = setup_sellable_bank()
    set_clock("2029-08-15T00:00:00Z")
    report = file_and_accept_monitoring_report(
        world,
        monitoring_year=3,
        window_start="2029-08-01T00:00:00Z",
        window_end="2029-09-01T00:00:00Z",
        measurements_array=FAILING_YEAR3_MEASUREMENTS,
    )
    assert report["compliance_status"] == "FAIL", (
        f"setup expected a FAIL year-3 report, got {report['compliance_status']}"
    )
    actions = remedial_actions_for_report(world, report["id"])
    assert len(actions) == 1, f"expected one remedial action, got {len(actions)}"
    return world, report, actions[0]


def test_unrecognised_role_name_is_rejected_as_unauthenticated():
    """A role string outside the five recognised names never reaches authorisation.

    PRD §2.1: "If either header is absent or empty, or if `X-User-Role` is not one of the five recognised role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "The five roles are `Sponsor`, `Permittee`, `IRTMember`, `IRTChair` and `ProgramAdmin`."

    Design: Corner/errors/unknown_actor_or_unknown_role_is_unauthenticated
    """
    world = setup_draft_bank()
    bank_id = world["bank"]["id"]

    unknown_role_headers = build_user_headers(world["sponsor"]["id"], "Auditor")
    resp = api_client.get_bank(bank_id, unknown_role_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    bank = get_success_data(api_client.get_bank(bank_id, world["sponsor_headers"]))
    assert bank["easement_recorded"] is False, (
        "the rejected request must not have recorded an easement"
    )
    assert bank["version"] == 1, (
        f"a freshly registered bank stays at version 1, got {bank['version']}"
    )


def test_resubmitting_an_approved_work_plan_is_a_work_plan_state_conflict():
    """The approved plan keeps the decision stamps its original approval wrote.

    PRD §3.4: "Deciding a plan that is not in `SUBMITTED` is rejected with `ERR_WORK_PLAN_STATE_INVALID`, as is submitting a plan that is already submitted or approved."
    PRD §3.4: "Approving advances `SUBMITTED → APPROVED`, stamps `decided_at`, and materialises exactly one performance-standard row per entry of the plan's standards array, each stamped with the plan's bank identifier; the bank's `version` increments by one."

    Design: Corner/errors/bank_and_work_plan_state_errors_are_triggerable
    """
    world = setup_executed_bank(record_easement=True)
    bank_id = world["bank"]["id"]
    plan = world["work_plan"]
    assert plan["status"] == "APPROVED", "setup expected an APPROVED work plan"

    resp = api_client.submit_work_plan(plan["id"], world["sponsor_headers"])
    validate_error(resp, ApiErrorId.ERR_WORK_PLAN_STATE_INVALID, 409)

    plans, meta = validate_paginated(
        api_client.list_bank_work_plans(
            bank_id, world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        f"the bank carries exactly one work plan, got {meta['total_count']}"
    )
    assert plans[0]["status"] == "APPROVED", "the refused submission must not move the plan"
    assert plans[0]["submitted_at"].startswith("2026-08-01T00:00:00"), (
        f"submitted_at must keep its original stamp, got {plans[0]['submitted_at']}"
    )
    assert plans[0]["decided_at"].startswith("2026-08-01T00:00:00"), (
        f"decided_at must keep the approval stamp, got {plans[0]['decided_at']}"
    )


def test_reviewing_a_draft_report_is_a_report_state_conflict():
    """Review exists only from SUBMITTED, and that gate outranks the measurement
    completeness rule the DRAFT year-4 report would also fail.

    PRD §3.7: "A seated member reviews a submitted report by supplying a `decision`."
    PRD §2.10: "After identity comes state: first whether the target row is in a state from which the requested transition exists at all, returning the entity-specific code (`ERR_BANK_STATE_INVALID`, `ERR_PROSPECTUS_STATE_INVALID`, `ERR_WORK_PLAN_STATE_INVALID`, `ERR_MILESTONE_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`, `ERR_REMEDIAL_STATE_INVALID` or `ERR_SALE_STATE_INVALID`); then the sales-posture gate of §2.8; then the optimistic-concurrency check (`ERR_STALE_BANK_VERSION`)."
    PRD §3.7: "A new report opens with its review status at `DRAFT`, its compliance status at `UNEVALUATED`, `return_count` at 0, `attainment_score` null, `failed_standard_codes` empty, and `reviewed_by_member_id`, `submitted_at` and `reviewed_at` all null."

    Design: Corner/errors/report_and_remedial_state_errors_are_triggerable
    """
    world, _failed_report, _action = _bank_with_open_remedial_action()

    draft = validate_success(
        api_client.create_monitoring_report(
            create_monitoring_report_payload(
                world["bank"]["id"],
                monitoring_year=4,
                window_start="2030-08-01T00:00:00Z",
                window_end="2030-09-01T00:00:00Z",
                measurements_array=[
                    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 130}
                ],
            ),
            world["sponsor_headers"],
        ),
        201,
    )

    resp = api_client.review_monitoring_report(
        draft["id"], review_report_payload("ACCEPT"), world["member_headers"][2]
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_STATE_INVALID, 409)

    after = get_success_data(
        api_client.get_monitoring_report(draft["id"], world["sponsor_headers"])
    )
    assert after["review_status"] == "DRAFT", "the refused review must not advance the report"
    assert after["compliance_status"] == "UNEVALUATED", (
        "no scoring happens on a refused review"
    )
    assert after["attainment_score"] is None, "an unscored report carries a null score"
    assert after["reviewed_at"] is None, "no reviewer stamp on a refused review"
    assert after["reviewed_by_member_id"] is None, (
        "no reviewer recorded on a refused review"
    )


def test_inspecting_an_open_remedial_action_is_a_remedial_state_conflict():
    """Inspection exists only from WORK_SUBMITTED, so an OPEN action refuses it.

    PRD §3.7: "The action passes through `REINSPECTION` within the same request and resolves immediately; the inspection is admissible only on an action standing in `WORK_SUBMITTED` when the request arrives, and anything else is `ERR_REMEDIAL_STATE_INVALID`."
    PRD §3.7: "An outcome of `CLEARED` advances the action `REINSPECTION → CLEARED`, records the acting member into `verified_by_member_id` and stamps `cleared_at`; that recorded member is precisely the person who may never afterwards approve the release of the milestone this action deferred."

    Design: Corner/errors/report_and_remedial_state_errors_are_triggerable
    """
    world, _report, action = _bank_with_open_remedial_action()
    assert action["status"] == "OPEN", "setup expected an OPEN remedial action"

    resp = api_client.inspect_remedial_action(
        action["id"], inspect_payload("CLEARED"), world["member_headers"][2]
    )
    validate_error(resp, ApiErrorId.ERR_REMEDIAL_STATE_INVALID, 409)

    after = get_success_data(
        api_client.get_remedial_action(action["id"], world["sponsor_headers"])
    )
    assert after["status"] == "OPEN", "the refused inspection must not move the action"
    assert after["round_number"] == 1, (
        f"the round number stays at 1, got {after['round_number']}"
    )
    assert after["cleared_at"] is None, "no clearing stamp on a refused inspection"
    assert after["verified_by_member_id"] is None, (
        "no verifier recorded on a refused inspection"
    )


def test_service_area_omitting_the_site_watershed_is_rejected():
    """A bank that cannot sell into its own watershed is refused, and the refusal
    leaves the sponsor's derived bank count untouched.

    PRD §3.2: "The service area is an explicit list of between one and eight eight-digit watershed codes with no duplicates, and it must contain the site's own watershed code — a service area that omits the site's watershed is rejected with `ERR_SERVICE_AREA_MISSING_SITE_HUC`, because a bank that cannot sell into its own watershed is a contradiction in terms."
    PRD §3.2: "Registration also raises the owning sponsor's bank count by one."

    Design: Corner/errors/service_area_must_contain_the_site_watershed
    """
    sponsor = register_sponsor()
    headers = make_sponsor_headers(sponsor["id"])

    resp = api_client.create_bank(
        create_bank_payload(
            sponsor["id"],
            site_huc8_code="03130002",
            service_area_huc8_codes=["03130003", "03130004"],
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_SERVICE_AREA_MISSING_SITE_HUC, 422)

    accepted = validate_success(
        api_client.create_bank(
            create_bank_payload(
                sponsor["id"],
                site_huc8_code="03130002",
                service_area_huc8_codes=["03130002", "03130003", "03130004"],
            ),
            headers,
        ),
        201,
    )

    after = get_success_data(api_client.get_sponsor(sponsor["id"], headers))
    assert after["banks_count"] == 1, (
        f"only the accepted registration counts, got banks_count {after['banks_count']}"
    )
    banks, meta = validate_paginated(
        api_client.list_banks(
            headers, params={"sponsor_id": sponsor["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused registration persisted nothing, got {meta['total_count']} banks"
    )
    assert banks[0]["id"] == accepted["id"], "the only bank is the accepted one"


def test_service_area_containing_the_site_watershed_is_accepted():
    """The control arm: the same payload with the site watershed added registers,
    quantifying the stewardship endowment from the single-pass capitalisation.

    PRD §3.2: "The calculation capitalises the annual stewardship cost at a non-wasting payout rate of 3.75 percent: the base endowment is the annual stewardship cost divided by 0.0375, rounded **up** to the next whole cent whatever the remainder."
    PRD §3.2: "An administrative fee of 1.50 percent of that base endowment is then computed and rounded half up to whole cents. The required endowment is the base endowment plus the administrative fee."

    Design: Corner/errors/service_area_must_contain_the_site_watershed
    """
    sponsor = register_sponsor()
    headers = make_sponsor_headers(sponsor["id"])

    bank = validate_success(
        api_client.create_bank(
            create_bank_payload(
                sponsor["id"],
                site_huc8_code="03130002",
                service_area_huc8_codes=["03130002", "03130003", "03130004"],
                annual_stewardship_cost_cents=4_200_000,
            ),
            headers,
        ),
        201,
    )

    assert bank["service_area_huc8_codes"] == ["03130002", "03130003", "03130004"], (
        f"the service area is echoed as supplied, got {bank['service_area_huc8_codes']}"
    )
    assert bank["status"] == "DRAFT", f"a new bank opens in DRAFT, got {bank['status']}"
    assert_cents(
        bank["stewardship_required_cents"], 113680000, "stewardship_required_cents"
    )


def test_execute_instrument_requires_an_approved_prospectus():
    """A prospectus merely UNDER_REVIEW is not an approved one: execution is
    refused and no authorised credit total or GENERATED entry appears.

    PRD §3.5: "The bank must have a prospectus in `APPROVED` status, and without one the request is rejected with `ERR_PROSPECTUS_NOT_APPROVED`; it must have a work plan in `APPROVED` status, and without one the request is rejected with `ERR_WORK_PLAN_MISSING`; and the owning sponsor's posted performance assurance must be at least 25,000,000 cents — a quarter of a million dollars — with a shortfall rejected as `ERR_PERFORMANCE_BOND_INSUFFICIENT`."
    PRD §3.5: "Execution advances the bank `PROSPECTUS_REVIEW → INSTRUMENT_EXECUTED` and performs five further effects."
    PRD §3.3: "Submission by the owning sponsor advances the prospectus `DRAFT → SUBMITTED`, stamps `submitted_at` with the current logical clock, and — this is the side effect that starts the regulatory machine — drags the bank from `DRAFT` to `PROSPECTUS_REVIEW`, recomputing the bank's posture (which remains `FROZEN`, since `PROSPECTUS_REVIEW` is not a sales-eligible status) and incrementing the bank's `version` by one."

    Design: Corner/errors/execute_instrument_without_an_approved_prospectus_is_rejected
    """
    world = setup_bank_under_review(
        work_plan_state="SUBMITTED", vote_positions=["CONCUR", "CONCUR", "CONCUR"]
    )
    bank_id = world["bank"]["id"]

    resp = api_client.execute_instrument(bank_id, world["chair_headers"])
    validate_error(resp, ApiErrorId.ERR_PROSPECTUS_NOT_APPROVED, 422)

    prospectus = get_success_data(
        api_client.get_prospectus(world["prospectus"]["id"], world["sponsor_headers"])
    )
    assert prospectus["status"] == "UNDER_REVIEW", (
        f"the prospectus stays under review, got {prospectus['status']}"
    )
    assert prospectus["concur_count"] == 3, (
        f"all three concurrences stand, got {prospectus['concur_count']}"
    )
    assert prospectus["decided_at"] is None, "no round was ever closed"

    bank = get_success_data(api_client.get_bank(bank_id, world["sponsor_headers"]))
    assert bank["status"] == "PROSPECTUS_REVIEW", (
        f"the refused execution must not move the bank, got {bank['status']}"
    )
    assert bank["version"] == 2, (
        f"only the prospectus submission mutated the bank, got version {bank['version']}"
    )
    assert bank["sales_posture"] == "FROZEN", (
        f"PROSPECTUS_REVIEW is not sales-eligible, got {bank['sales_posture']}"
    )
    assert_credits(bank["total_authorized_credits"], 0.00, "total_authorized_credits")
    assert bank["instrument_executed_at"] is None, "no execution stamp was written"

    _entries, meta = validate_paginated(
        api_client.list_bank_ledger(
            bank_id, world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"no GENERATED entry was appended, got {meta['total_count']} ledger rows"
    )


def test_monitoring_report_creation_without_effective_standards_is_rejected():
    """Performance standards exist only once a work plan is approved, so a report
    opened against a bank whose plan is still SUBMITTED has nothing to be scored
    against and is refused at creation time.

    PRD §3.7: "A report cannot be opened for a bank that has no performance standard effective in that year at all, which is rejected with `ERR_NO_EFFECTIVE_STANDARDS`."
    PRD §3.4: "Approving advances `SUBMITTED → APPROVED`, stamps `decided_at`, and materialises exactly one performance-standard row per entry of the plan's standards array, each stamped with the plan's bank identifier; the bank's `version` increments by one."
    PRD §3.4: "The return branch materialises no performance standard rows at all and leaves the bank entirely untouched."

    Design: Corner/errors/monitoring_report_creation_without_effective_standards_is_rejected
    """
    world = setup_bank_under_review(
        work_plan_state="SUBMITTED", vote_positions=["CONCUR", "CONCUR", "CONCUR"]
    )
    bank_id = world["bank"]["id"]

    resp = api_client.create_monitoring_report(
        create_monitoring_report_payload(
            bank_id,
            monitoring_year=1,
            window_start="2027-08-01T00:00:00Z",
            window_end="2027-09-01T00:00:00Z",
            measurements_array=[
                {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 130},
                {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
            ],
        ),
        world["sponsor_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_STANDARDS, 422)

    _standards, standards_meta = validate_paginated(
        api_client.list_bank_performance_standards(
            bank_id, world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert standards_meta["total_count"] == 0, (
        "a SUBMITTED work plan materialises no standards, got "
        f"{standards_meta['total_count']}"
    )
    _reports, reports_meta = validate_paginated(
        api_client.list_monitoring_reports(
            world["sponsor_headers"],
            params={"bank_id": bank_id, "limit": 10, "offset": 0},
        )
    )
    assert reports_meta["total_count"] == 0, (
        f"the refused creation persisted nothing, got {reports_meta['total_count']}"
    )

    plans, _meta = validate_paginated(
        api_client.list_bank_work_plans(
            bank_id, world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert plans[0]["status"] == "SUBMITTED", (
        f"the plan is still awaiting a decision, got {plans[0]['status']}"
    )
    assert plans[0]["decided_at"] is None, "an undecided plan carries no decision stamp"


def test_monitoring_report_submission_missing_a_year_three_measurement_is_rejected():
    """Completeness is enforced against the standards effective in the report's own
    monitoring year: three of the four year-3 standards is enough to open a report
    but not enough to submit it.

    PRD §3.7: "Submission is admissible while the bank is in `INSTRUMENT_EXECUTED`, `MONITORING` or `SUSPENDED` status — a suspended bank must still be able to file, since filing is how it recovers — and requires the measurements array to contain one entry for every performance standard of the bank whose `effective_from_year` is no greater than the report's monitoring year."
    PRD §3.7: "A standard effective in that year with no matching measurement is rejected with `ERR_MEASUREMENT_MISSING`."

    Design: Corner/errors/monitoring_report_submission_with_a_missing_measurement_is_rejected
    """
    world = setup_executed_bank(record_easement=True)
    bank_id = world["bank"]["id"]

    report = validate_success(
        api_client.create_monitoring_report(
            create_monitoring_report_payload(
                bank_id,
                monitoring_year=3,
                window_start="2029-08-01T00:00:00Z",
                window_end="2029-09-01T00:00:00Z",
                measurements_array=[
                    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 130},
                    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
                    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 88.0},
                ],
            ),
            world["sponsor_headers"],
        ),
        201,
    )

    resp = api_client.submit_monitoring_report(report["id"], world["sponsor_headers"])
    validate_error(resp, ApiErrorId.ERR_MEASUREMENT_MISSING, 422)

    after = get_success_data(
        api_client.get_monitoring_report(report["id"], world["sponsor_headers"])
    )
    assert after["review_status"] == "DRAFT", (
        f"the refused submission leaves the report in DRAFT, got {after['review_status']}"
    )
    assert after["submitted_at"] is None, "no submission stamp on a refused submission"
    assert after["return_count"] == 0, (
        f"a refusal is not a return, got return_count {after['return_count']}"
    )

    _standards, meta = validate_paginated(
        api_client.list_bank_performance_standards(
            bank_id, world["sponsor_headers"], params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 4, (
        f"the approved plan materialised four standards, got {meta['total_count']}"
    )


def test_performance_release_after_a_failed_report_is_refused_on_compliance():
    """A failing monitoring year blocks a performance release outright rather than
    scaling it down: the claimed milestone keeps its provisional quantity and
    nothing is released.

    PRD §3.6: "If the governing report's compliance status is `FAIL`, the approval is rejected with `ERR_COMPLIANCE_FAILED` — a failing year defers a release, it never scales one down."
    PRD §3.6: "For the three performance milestones, the server selects the governing monitoring report: among the bank's reports whose review status is `ACCEPTED`, the one with the highest monitoring year, and where two accepted reports share the highest monitoring year, the most recently created of them."
    PRD §3.6: "That provisional figure is the bank's authorised credit total multiplied by the milestone's release percentage, rounded half up to 2 decimal places."
    PRD §3.6: "A milestone opens in `PENDING` with `claimed_at`, `approved_at` and `deferred_at` null, `attainment_factor_applied` null, and `final_release_credits` at 0.00."

    Design: Corner/errors/perf_release_after_a_failed_report_is_rejected_on_compliance
    """
    world, _report, _action = _bank_with_open_remedial_action()
    predecessor = world["milestones"]["INSTRUMENT_EXECUTION"]

    perf = add_milestone(
        world,
        milestone_code="PERF_YEAR_3",
        release_pct=0.200,
        window_start="2029-08-01T00:00:00Z",
        window_end="2029-10-01T00:00:00Z",
        predecessor_milestone_id=predecessor["id"],
    )
    claim_milestone(world, perf["id"])
    version_before = bank_version(world)

    resp = api_client.approve_milestone_release(
        perf["id"],
        approve_release_payload(version_before),
        world["member_headers"][0],
    )
    validate_error(resp, ApiErrorId.ERR_COMPLIANCE_FAILED, 422)

    milestone = get_success_data(
        api_client.get_milestone(perf["id"], world["sponsor_headers"])
    )
    assert milestone["status"] == "CLAIMED", (
        f"the refused approval leaves the milestone CLAIMED, got {milestone['status']}"
    )
    assert_credits(
        milestone["provisional_release_credits"], 19.75, "provisional_release_credits"
    )
    assert_credits(milestone["final_release_credits"], 0.00, "final_release_credits")
    assert milestone["attainment_factor_applied"] is None, (
        "no attainment factor is stamped by a refused approval"
    )
    assert milestone["approved_at"] is None, "no approval stamp on a refused approval"

    bank = bank_state(world)
    assert_credits(bank["credits_released"], 14.82, "credits_released")
    assert bank["version"] == version_before, (
        f"the refused approval must not bump the bank version, got {bank['version']}"
    )


def test_closing_a_bank_with_a_pending_milestone_is_refused_before_the_endowment():
    """The release schedule is checked before the money: an unapproved milestone
    wins over an endowment funded only to the interim gate.

    PRD §3.9: "Every release milestone on the bank must stand in `APPROVED` and no remedial action of the bank may be in `OPEN`, `WORK_SUBMITTED`, `REINSPECTION` or `FAILED`; a breach of either is rejected with `ERR_MILESTONES_INCOMPLETE`."
    PRD §2.10: "The closure completeness rule (`ERR_MILESTONES_INCOMPLETE`) is evaluated after those."
    PRD §2.10: "Fiscal checks are evaluated last, in this order: credit availability (`ERR_INSUFFICIENT_CREDITS`), escrow sufficiency (`ERR_INSUFFICIENT_ESCROW`), stewardship funding (`ERR_STEWARDSHIP_UNDERFUNDED`) and the performance assurance bond (`ERR_PERFORMANCE_BOND_INSUFFICIENT`)."
    PRD §3.7: "The report's `attainment_score` is the sum of those already-rounded contributions divided by the sum of the effective standards' weights as supplied — the denominator uses the unrounded weights and covers only the standards effective in this year, so a report in an early monitoring year is scored against a denominator smaller than 1.000 — with the quotient rounded half up to 4 decimal places."

    Design: Corner/errors/closing_a_bank_with_a_pending_milestone_is_rejected
    """
    world = setup_sellable_bank()
    bank_id = world["bank"]["id"]

    set_clock("2027-08-15T00:00:00Z")
    year_one = file_and_accept_monitoring_report(
        world,
        monitoring_year=1,
        window_start="2027-08-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        measurements_array=[
            {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 120},
            {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 8.0},
        ],
    )
    assert_score(year_one["attainment_score"], 1.0000, "year-1 attainment_score")
    assert year_one["compliance_status"] == "PASS", (
        f"both year-1 standards were met, got {year_one['compliance_status']}"
    )

    pending_milestone = add_milestone(
        world,
        milestone_code="PERF_YEAR_3",
        release_pct=0.200,
        window_start="2029-08-01T00:00:00Z",
        window_end="2029-10-01T00:00:00Z",
        predecessor_milestone_id=world["milestones"]["INSTRUMENT_EXECUTION"]["id"],
    )

    resp = api_client.close_bank(bank_id, world["chair_headers"])
    validate_error(resp, ApiErrorId.ERR_MILESTONES_INCOMPLETE, 409)

    bank = bank_state(world)
    assert bank["status"] == "MONITORING", (
        f"the refused closure leaves the bank in MONITORING, got {bank['status']}"
    )
    assert bank["closed_at"] is None, "no closure stamp on a refused closure"
    assert bank["sales_posture"] == "OPEN", (
        f"the bank still sells while closure is refused, got {bank['sales_posture']}"
    )
    assert_cents(bank["stewardship_funded_cents"], 28420000, "stewardship_funded_cents")
    assert_cents(
        bank["stewardship_required_cents"], 113680000, "stewardship_required_cents"
    )

    milestones, meta = validate_paginated(
        api_client.list_milestones(
            world["sponsor_headers"],
            params={
                "bank_id": bank_id,
                "status": "PENDING",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one milestone is still pending, got {meta['total_count']}"
    )
    assert milestones[0]["id"] == pending_milestone["id"], (
        "the pending milestone is the unapproved performance milestone"
    )


def test_assignment_beyond_the_unmet_permit_requirement_is_rejected():
    """The permit obligation ceiling is re-checked at assignment: a second sale that
    was inside the obligation when it was quoted is refused once the first sale has
    consumed most of the requirement.

    PRD §3.8: "That obligation ceiling is checked here at quote time and checked again at assignment, because the obligation can be consumed by another sale in between."
    PRD §3.8: "It advances the sale `EXECUTED → ASSIGNED`, requires the requested quantity not to exceed the buyer's remaining unmet obligation, stamps `assigned_at` with the clock, and generates an `assignment_reference` formed as the buyer's permit number, a forward slash, the bank's site watershed code, another forward slash, and the requested credit quantity."
    PRD §3.1: "`assigned_credits` is the total requested-credit quantity across this holder's sales standing in `ASSIGNED` status, starting at 0."
    PRD §3.1: "`unmet_requirement_credits` is the required credits minus the assigned credits, floored at zero so it can never go negative, carried to 2 decimal places, and therefore equal to the required credits at registration."
    PRD §3.1: "`escrow_balance_cents` is the deposited total minus the sum of the settled prices of all of this holder's sales standing in `EXECUTED` or `ASSIGNED` status, and likewise starts at 0."
    PRD §3.8: "A ledger entry of type `ASSIGNED` is appended for the audit trail carrying a delta of exactly 0.00, so the running balance is unchanged, and the buyer's assigned credits and unmet obligation are recomputed."

    Design: Corner/errors/assignment_beyond_the_unmet_permit_requirement_is_rejected
    """
    world = setup_sellable_bank(
        permittee_required_credits=5.00, permittee_deposit_cents=40_000_000
    )
    bank_id = world["bank"]["id"]
    permittee = world["permittee"]

    sale_a = quote_credits(world, credits_requested=3.00)
    sale_b = quote_credits(world, credits_requested=3.00)
    assert_cents(sale_a["quoted_price_cents"], 12312000, "sale A quoted_price_cents")
    assert_cents(sale_b["quoted_price_cents"], 12312000, "sale B quoted_price_cents")

    reserve_sale(world, sale_a["id"])
    executed_a = execute_sale(world, sale_a["id"])
    assert_cents(
        executed_a["executed_price_cents"], 12312000, "sale A executed_price_cents"
    )
    assigned_a = assign_sale(world, sale_a["id"])
    assert assigned_a["status"] == "ASSIGNED", (
        f"the first sale discharges part of the permit, got {assigned_a['status']}"
    )
    expected_reference = (
        f"{permittee['permit_number']}/{world['bank']['site_huc8_code']}/3.00"
    )
    assert assigned_a["assignment_reference"] == expected_reference, (
        f"expected assignment_reference {expected_reference}, "
        f"got {assigned_a['assignment_reference']}"
    )

    reserve_sale(world, sale_b["id"])
    executed_b = execute_sale(world, sale_b["id"])

    resp = api_client.assign_credit_sale(sale_b["id"], world["sponsor_headers"])
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT, 422)

    sale_b_after = get_success_data(
        api_client.get_credit_sale(sale_b["id"], world["sponsor_headers"])
    )
    assert sale_b_after["status"] == "EXECUTED", (
        f"the refused assignment leaves the sale EXECUTED, got {sale_b_after['status']}"
    )
    assert sale_b_after["assigned_at"] is None, (
        "no assignment stamp on a refused assignment"
    )
    assert sale_b_after["assignment_reference"] is None, (
        "no assignment reference on a refused assignment"
    )

    holder = get_success_data(
        api_client.get_permittee(permittee["id"], world["permittee_headers"])
    )
    assert_credits(holder["assigned_credits"], 3.00, "assigned_credits")
    assert_credits(holder["unmet_requirement_credits"], 2.00, "unmet_requirement_credits")
    assert_cents(holder["deposited_cents"], 40000000, "deposited_cents")
    assert_cents(
        holder["escrow_balance_cents"],
        40000000
        - executed_a["executed_price_cents"]
        - executed_b["executed_price_cents"],
        "escrow_balance_cents",
    )

    bank = bank_state(world)
    assert_credits(bank["credits_sold"], 6.00, "credits_sold")
    assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold")
    assert_credits(bank["credits_available"], 8.82, "credits_available")

    entries, meta = validate_paginated(
        api_client.list_bank_ledger(
            bank_id, world["sponsor_headers"], params={"limit": 50, "offset": 0}
        )
    )
    assert meta["total_count"] == 9, (
        f"the refused assignment appends nothing, expected 9 ledger rows, "
        f"got {meta['total_count']}"
    )
    assert_ledger_shape(
        entries,
        [
            ("GENERATED", 0.00, 0.00),
            ("RELEASED", 14.82, 14.82),
            ("HOLD_PLACED", -3.00, 11.82),
            ("HOLD_RELEASED", 3.00, 14.82),
            ("SOLD", -3.00, 11.82),
            ("ASSIGNED", 0.00, 11.82),
            ("HOLD_PLACED", -3.00, 8.82),
            ("HOLD_RELEASED", 3.00, 11.82),
            ("SOLD", -3.00, 8.82),
        ],
    )
