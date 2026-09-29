"""Endpoint surface, uniform failure envelope and immediate cascade visibility.

Facility create/read/amend/list, the reporting-sweep action endpoint, the
self-referential appeal escalation link, the applicant grant ledger read, the
closeout certification gate, the shape of every rejection body, the fixed
evaluation order between path identifiers and body shape, and the synchronous
visibility of the obligation cascade.
"""
import pytest

from test_helpers import (
    ADJUDICATOR_USER_ID,
    GRANTS_OFFICER_USER_ID,
    NON_EXISTENT_UUID,
    SECOND_GRANTS_OFFICER_USER_ID,
    ApiErrorId,
    appeal_payload,
    applicant_payload,
    cost_line_item_payload,
    create_applicant,
    create_facility,
    decide_appeal,
    determine_eligibility,
    disaster_payload,
    facility_payload,
    file_appeal,
    is_iso8601_timestamp,
    make_admin_headers,
    make_applicant_agent_headers,
    make_auditor_headers,
    make_grants_officer_headers,
    make_specialist_headers,
    setup_declaration,
    setup_finalized_deobligation,
    setup_obligated_project,
    setup_paid_drawdown,
    setup_validated_project,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Facility create / read / amend / list
# ---------------------------------------------------------------------------
def test_facility_create_then_read_returns_the_row_with_its_documentation_defaults(api):
    """PRD §3.2: "Facilities are the physical unit of eligibility, and an
    `ApplicantAgent` registers each one against its own `applicant_id` with a
    non-empty `name`, a `facility_type` from `ROAD_BRIDGE`, `WATER_CONTROL`,
    `BUILDING_EQUIPMENT`, `UTILITY`, `PARK_RECREATION` and
    `EMERGENCY_PROTECTIVE`, and an `ownership` form of `PUBLIC`, `PNP_OWNED` or
    `LEASED`."
    PRD §3.2: "Four documentation flags are optional and default in the
    applicant's favour except where noted: `in_active_use` defaults to true,
    `legal_responsibility_documented` defaults to true, `flood_zone` defaults to
    false, and `prior_disaster_flood_damage` defaults to false."
    PRD §3.2: "A newly registered facility sits in `eligibility_status`
    `PENDING` with `screening_failure_reason` null and `screened_at` null."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and
    increments by exactly 1 on every mutation of the row."
    PRD §4: "Endpoints that bring a new resource row into existence answer with
    HTTP 201 and the created resource in `data`; every other successful
    operation — reads, lists, state transitions, amendments and the
    logical-clock capability — answers with HTTP 200."

    Design: Corner/endpoints/facility_crud_lifecycle_create_read_update_and_list
    """
    scenario = setup_declaration("2026-07-01T00:00:00Z", declaration_number="DR-4984")
    applicant = create_applicant(scenario["disaster"]["id"])
    agent = make_applicant_agent_headers(applicant["id"])

    created = validate_success(
        api.create_facility(
            facility_payload(
                applicant["id"],
                name="Riverside Pump Station",
                facility_type="WATER_CONTROL",
                ownership="PUBLIC",
            ),
            agent,
        ),
        expected_status=201,
    )

    assert created["eligibility_status"] == "PENDING", (
        f"Expected PENDING on a newly registered facility, got {created['eligibility_status']}"
    )
    assert created["in_active_use"] is True, (
        f"Expected in_active_use to default true, got {created['in_active_use']}"
    )
    assert created["legal_responsibility_documented"] is True, (
        "Expected legal_responsibility_documented to default true, got "
        f"{created['legal_responsibility_documented']}"
    )
    assert created["flood_zone"] is False, (
        f"Expected flood_zone to default false, got {created['flood_zone']}"
    )
    assert created["prior_disaster_flood_damage"] is False, (
        "Expected prior_disaster_flood_damage to default false, got "
        f"{created['prior_disaster_flood_damage']}"
    )
    assert created["screening_failure_reason"] is None, (
        f"Expected null screening_failure_reason, got {created['screening_failure_reason']}"
    )
    assert created["screened_at"] is None, (
        f"Expected null screened_at before screening, got {created['screened_at']}"
    )
    assert created["version"] == 1, f"Expected version 1 on creation, got {created['version']}"

    read = validate_success(api.get_facility(created["id"], make_specialist_headers()))
    assert read["id"] == created["id"], (
        f"Expected the read to return id {created['id']}, got {read['id']}"
    )
    assert read["name"] == "Riverside Pump Station", (
        f"Expected name 'Riverside Pump Station', got {read['name']}"
    )
    assert read["facility_type"] == "WATER_CONTROL", (
        f"Expected facility_type WATER_CONTROL, got {read['facility_type']}"
    )
    assert read["ownership"] == "PUBLIC", (
        f"Expected ownership PUBLIC, got {read['ownership']}"
    )


def test_facility_amendment_writes_only_the_supplied_flag_and_stays_listable(api):
    """PRD §3.2: "An `ApplicantAgent` may amend its own facility's
    `in_active_use`, `legal_responsibility_documented`, `ownership`,
    `flood_zone` and `prior_disaster_flood_damage`, and any such amendment —
    from `ELIGIBLE` or from `INELIGIBLE` alike — writes the supplied
    attributes, forces `eligibility_status` back to `PENDING`, clears
    `screening_failure_reason` to null and `screened_at` to null, and
    increments `version` by 1."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows
    matching the filters before the page window is applied and `has_more` is
    true when rows remain beyond the current window."
    PRD §2.3: "Filters combine conjunctively: supplying both `applicant_id` and
    `status` returns only rows matching both."

    Design: Corner/endpoints/facility_crud_lifecycle_create_read_update_and_list
    """
    scenario = setup_declaration("2026-07-01T00:00:00Z", declaration_number="DR-4984")
    applicant = create_applicant(scenario["disaster"]["id"])
    agent = make_applicant_agent_headers(applicant["id"])
    facility = create_facility(applicant["id"], name="Riverside Pump Station")

    patched = validate_success(api.amend_facility(facility["id"], {"flood_zone": True}, agent))

    assert patched["flood_zone"] is True, (
        f"Expected flood_zone true after the amendment, got {patched['flood_zone']}"
    )
    assert patched["in_active_use"] is True, (
        "Expected in_active_use untouched by an amendment that did not supply it, got "
        f"{patched['in_active_use']}"
    )
    assert patched["legal_responsibility_documented"] is True, (
        "Expected legal_responsibility_documented untouched by the amendment, got "
        f"{patched['legal_responsibility_documented']}"
    )
    assert patched["eligibility_status"] == "PENDING", (
        f"Expected PENDING after the amendment, got {patched['eligibility_status']}"
    )
    assert patched["screening_failure_reason"] is None, (
        f"Expected screening_failure_reason cleared, got {patched['screening_failure_reason']}"
    )
    assert patched["screened_at"] is None, (
        f"Expected screened_at cleared, got {patched['screened_at']}"
    )
    assert patched["version"] == 2, (
        f"Expected version 2 after one amendment, got {patched['version']}"
    )

    rows, meta = validate_paginated(
        api.list_facilities(make_auditor_headers(), params={"applicant_id": applicant["id"]})
    )
    assert meta["total_count"] == 1, (
        f"Expected total_count 1 for the applicant's facilities, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more false with one row inside the window, got {meta['has_more']}"
    )
    assert len(rows) == 1, f"Expected exactly one listed facility, got {len(rows)}"
    assert rows[0]["id"] == facility["id"], (
        f"Expected the listed row to be {facility['id']}, got {rows[0]['id']}"
    )


# ---------------------------------------------------------------------------
# The reporting-sweep action endpoint
# ---------------------------------------------------------------------------
def test_reporting_sweep_scores_the_monitoring_variant_and_takes_over_the_tier(api):
    """PRD §3.1: "Three point components are weighted and summed: the
    applicant-type component at 30 percent, a second component at 30 percent,
    and a third component at 40 percent, with the weighted sum rounded half up
    to two decimal places."
    PRD §3.1: "The applicant-type component is a fixed point value read from
    the `applicant_type`: 20 points for `LOCAL_GOVERNMENT`, 30 for `TRIBE`, 10
    for `STATE_AGENCY` and 60 for `PRIVATE_NONPROFIT`."
    PRD §3.1: "The second component awards 10 points for every facility
    registered to the applicant, counted regardless of each facility's own
    `eligibility_status`, and is then capped at 100 points — so an applicant
    with ten or more facilities scores the maximum."
    PRD §3.1: "The resulting score maps to a tier: at least 60 points is
    `HIGH`, at least 30 but below 60 is `MEDIUM`, and anything below 30 is
    `LOW`."
    PRD §3.8: "The sweep also re-scores the applicant on the `MONITORING`
    variant, whatever it found: `risk_score_monitoring` is rewritten,
    `monitoring_scored_at` is stamped from the clock, and `risk_tier` is
    refreshed — and because `monitoring_scored_at` is now non-null, `risk_tier`
    follows the monitoring score from here on rather than the screening score."
    PRD §3.8: "The second component awards 25 points for each of the
    applicant's `DELINQUENT` reports, capped at 100 points, so four delinquent
    reports max it out."
    PRD §3.8: "The third component measures how much cash the applicant is
    sitting on relative to what it has been awarded: when `total_obligated_cents`
    is exactly 0 while `cash_on_hand_cents` is above 0 — cash held against no
    live obligation at all, the worst possible signal — the component is a flat
    100 points; otherwise it is one hundred multiplied by `cash_on_hand_cents`,
    divided by `total_obligated_cents` (treating a zero denominator as 1),
    truncated downward, and then capped at 100."

    Design: Corner/endpoints/reporting_sweep_action_endpoint_scores_the_monitoring_variant
    """
    scenario = setup_declaration("2026-07-01T00:00:00Z", declaration_number="DR-4985")
    applicant = create_applicant(
        scenario["disaster"]["id"], applicant_type="LOCAL_GOVERNMENT"
    )
    create_facility(
        applicant["id"], name="Riverside Pump Station", facility_type="WATER_CONTROL"
    )
    create_facility(applicant["id"], name="Main Street Bridge", facility_type="ROAD_BRIDGE")
    determined = determine_eligibility(applicant["id"])
    assert determined["risk_score_screening"] == 12.00, (
        "Expected 12.00 screening score for a LOCAL_GOVERNMENT with two unflooded "
        f"facilities, got {determined['risk_score_screening']}"
    )

    swept = validate_success(api.reporting_sweep(applicant["id"], make_admin_headers()))

    assert swept["risk_score_screening"] == 12.00, (
        "Expected risk_score_screening left at 12.00 by the sweep, got "
        f"{swept['risk_score_screening']}"
    )
    assert swept["risk_score_monitoring"] == 6.00, (
        "Expected 6.00 monitoring score with no delinquency and a zero cash ratio, got "
        f"{swept['risk_score_monitoring']}"
    )
    assert swept["monitoring_scored_at"] is not None, (
        "Expected monitoring_scored_at stamped from the clock, got null"
    )
    assert is_iso8601_timestamp(swept["monitoring_scored_at"]), (
        f"Expected an ISO 8601 monitoring_scored_at, got {swept['monitoring_scored_at']!r}"
    )
    assert swept["monitoring_scored_at"].startswith("2026-07-01T00:00:00"), (
        "Expected monitoring_scored_at at the logical clock 2026-07-01T00:00:00Z, got "
        f"{swept['monitoring_scored_at']}"
    )
    assert swept["risk_tier"] == "LOW", (
        f"Expected LOW from the 6.00 monitoring score, got {swept['risk_tier']}"
    )


def test_reporting_sweep_creates_no_progress_report_row(api):
    """PRD §3.8: "Delinquency itself is declared by a `PlatformAdmin`
    capability that advances the reporting epoch for one applicant."
    PRD §3.8: "Every progress report of that applicant whose `status` is `DUE`
    and whose `due_at` is now behind the logical clock is driven `DUE →
    DELINQUENT`."
    PRD §3.7: "Because `monitoring_status` became `ENHANCED`, the system
    creates one progress report row for this applicant in status `DUE`, for the
    quarter containing the current logical clock, with `quarter_label`,
    `period_start_at`, `period_end_at` and `due_at` all derived by the quarter
    rules of §3.8."
    PRD §3.8: "After **every** recomputation, `drawdown_status` is set to
    `SUSPENDED` whenever `delinquent_report_count` is greater than 0 or
    `pending_deobligation_cents` is greater than 0, and to `ACTIVE` whenever
    both are exactly 0."

    Design: Corner/endpoints/reporting_sweep_action_endpoint_scores_the_monitoring_variant
    """
    scenario = setup_declaration("2026-07-01T00:00:00Z", declaration_number="DR-4985")
    applicant = create_applicant(scenario["disaster"]["id"])
    create_facility(applicant["id"], name="Riverside Pump Station")
    create_facility(applicant["id"], name="Main Street Bridge", facility_type="ROAD_BRIDGE")
    determine_eligibility(applicant["id"])

    swept = validate_success(api.reporting_sweep(applicant["id"], make_admin_headers()))

    assert swept["id"] == applicant["id"], (
        f"Expected the swept Applicant row in data, got id {swept['id']}"
    )
    assert swept["delinquent_report_count"] == 0, (
        f"Expected 0 delinquent reports, got {swept['delinquent_report_count']}"
    )
    assert swept["drawdown_status"] == "ACTIVE", (
        "Expected ACTIVE with delinquent_report_count and pending_deobligation_cents both 0, "
        f"got {swept['drawdown_status']}"
    )

    rows, meta = validate_paginated(api.list_progress_reports(make_admin_headers()))
    assert meta["total_count"] == 0, (
        f"Expected no progress report rows after a sweep, got total_count {meta['total_count']}"
    )
    assert rows == [], f"Expected an empty progress report page, got {rows}"


# ---------------------------------------------------------------------------
# The self-referential appeal escalation link
# ---------------------------------------------------------------------------
def _setup_denied_first_level_appeal():
    """A FINAL determination of 500000 whose first-level appeal was denied."""
    scenario = setup_finalized_deobligation(
        500_000,
        reason="SCOPE_REDUCTION",
        headers=make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID),
        officer_user_id=SECOND_GRANTS_OFFICER_USER_ID,
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4986"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    first_appeal = file_appeal(
        scenario["deobligation"]["id"],
        scenario["applicant"]["id"],
        200_000,
        grounds="The reduced scope was eligible work",
    )
    scenario["first_appeal"] = decide_appeal(
        first_appeal["id"],
        "DENY",
        decision_rationale="The scope reduction stands",
        adjudicator_user_id=ADJUDICATOR_USER_ID,
    )
    return scenario


def test_appeal_escalation_with_an_unknown_prior_appeal_id_is_a_404(api):
    """PRD §2.7: "Resolution of every foreign key supplied in the body —
    `disaster_id`, `applicant_id`, `facility_id`, `project_id`,
    `force_account_resource_id`, `contract_id`, `deobligation_id` and
    `prior_appeal_id` — with the same 404 error identifiers as rung 4."
    PRD §2.7: "The first identifier that does not resolve decides the error:
    `ERR_DISASTER_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_FACILITY_NOT_FOUND`, `ERR_DAMAGE_SITE_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND`, `ERR_COST_LINE_ITEM_NOT_FOUND`,
    `ERR_RESOURCE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
    `ERR_DRAWDOWN_NOT_FOUND`, `ERR_PROGRESS_REPORT_NOT_FOUND`,
    `ERR_DEOBLIGATION_NOT_FOUND` or `ERR_APPEAL_NOT_FOUND` (all 404)."

    Design: Corner/endpoints/appeal_escalation_links_to_its_prior_appeal
    """
    scenario = _setup_denied_first_level_appeal()

    response = api.create_appeal(
        appeal_payload(
            scenario["deobligation"]["id"],
            200_000,
            grounds="Escalating from an appeal that does not exist",
            prior_appeal_id=NON_EXISTENT_UUID,
        ),
        make_applicant_agent_headers(scenario["applicant"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_APPEAL_NOT_FOUND)

    rows, meta = validate_paginated(api.list_appeals(make_admin_headers()))
    assert meta["total_count"] == 1, (
        "Expected only the first-level appeal to exist after the rejected escalation, got "
        f"total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == scenario["first_appeal"]["id"], (
        f"Expected the surviving row to be {scenario['first_appeal']['id']}, got {rows[0]['id']}"
    )


def test_appeal_escalation_stores_the_prior_appeal_and_derives_level_second(api):
    """PRD §3.9: "The `level` is derived, not supplied: it is `FIRST` when
    `prior_appeal_id` is null and `SECOND` otherwise."
    PRD §3.9: "A `SECOND`-level appeal's `prior_appeal_id` must reference an
    appeal on the *same* determination whose `status` is `DENIED` or
    `PARTIALLY_GRANTED`, since only a loss at the first level opens the second
    (`ERR_SECOND_APPEAL_REQUIRES_FIRST_DENIED`)."
    PRD §3.9: "A filed appeal sits in `SUBMITTED` with `relief_granted_cents`
    0, `decided_at` null, `decided_by_user_id` null and `decision_rationale`
    null."
    PRD §2.5: "Every instant the server writes for itself reads this clock:
    `screened_at` and `reviewed_at` on screening and cost review, `submitted_at`
    on report filing, `finalized_at` and the derived `appeal_deadline_at` on
    finalization, `filed_at` on appeal filing, `decided_at` on appeal decision,
    `monitoring_scored_at` on monitoring scoring, and the quarter boundaries of
    a progress report."

    Design: Corner/endpoints/appeal_escalation_links_to_its_prior_appeal
    """
    scenario = _setup_denied_first_level_appeal()
    first_appeal = scenario["first_appeal"]

    second_appeal = validate_success(
        api.create_appeal(
            appeal_payload(
                scenario["deobligation"]["id"],
                200_000,
                grounds="Escalating the denied first-level appeal",
                prior_appeal_id=first_appeal["id"],
            ),
            make_applicant_agent_headers(scenario["applicant"]["id"]),
        ),
        expected_status=201,
    )

    assert second_appeal["prior_appeal_id"] == first_appeal["id"], (
        f"Expected prior_appeal_id {first_appeal['id']}, got {second_appeal['prior_appeal_id']}"
    )
    assert second_appeal["level"] == "SECOND", (
        f"Expected level SECOND with a prior_appeal_id supplied, got {second_appeal['level']}"
    )
    assert second_appeal["status"] == "SUBMITTED", (
        f"Expected status SUBMITTED on a freshly filed appeal, got {second_appeal['status']}"
    )
    assert second_appeal["relief_granted_cents"] == 0, (
        f"Expected relief_granted_cents 0 on filing, got {second_appeal['relief_granted_cents']}"
    )
    assert second_appeal["decided_at"] is None, (
        f"Expected decided_at null on filing, got {second_appeal['decided_at']}"
    )
    assert second_appeal["decided_by_user_id"] is None, (
        f"Expected decided_by_user_id null on filing, got {second_appeal['decided_by_user_id']}"
    )
    assert second_appeal["filed_at"].startswith("2026-07-01T00:00:00"), (
        "Expected filed_at at the logical clock 2026-07-01T00:00:00Z, got "
        f"{second_appeal['filed_at']}"
    )

    read = validate_success(api.get_appeal(second_appeal["id"], make_admin_headers()))
    assert read["prior_appeal_id"] == first_appeal["id"], (
        f"Expected the stored association to survive a read, got {read['prior_appeal_id']}"
    )

    rows, meta = validate_paginated(api.list_appeals(make_admin_headers()))
    assert meta["total_count"] == 2, (
        f"Expected both appeals on the determination, got total_count {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {first_appeal["id"], second_appeal["id"]}, (
        f"Expected exactly the two filed appeals, got {[row['id'] for row in rows]}"
    )
    listed_first = next(row for row in rows if row["id"] == first_appeal["id"])
    assert listed_first["level"] == "FIRST", (
        f"Expected the parent appeal to stay FIRST, got {listed_first['level']}"
    )
    assert listed_first["prior_appeal_id"] is None, (
        f"Expected the parent appeal to carry no prior_appeal_id, got "
        f"{listed_first['prior_appeal_id']}"
    )


# ---------------------------------------------------------------------------
# The applicant grant ledger, readable on GET
# ---------------------------------------------------------------------------
def test_applicant_ledger_read_matches_the_ledger_formula_after_an_obligation_and_a_payment(api):
    """PRD §3.8: "`total_obligated_cents` is the sum, over the applicant's
    projects in status `OBLIGATED`, `CLOSEOUT_REQUESTED` or `CLOSED`, of
    `federal_share_obligated_cents` less `deobligated_cents`; projects in
    `DRAFT`, `UNDER_REVIEW`, `RFI_ISSUED`, `VALIDATED` or `DENIED` contribute
    nothing."
    PRD §3.8: "`total_drawn_cents` is the sum of `approved_cents` over the
    applicant's drawdowns in status `PAID` or `REFUNDED`."
    PRD §3.8: "`cash_on_hand_cents` is `total_drawn_cents` less
    `total_refunded_cents`, and `available_drawdown_cents` is
    `total_obligated_cents` less `cash_on_hand_cents`."
    PRD §3.8: "Paying sets `approved_cents` to the full `requested_cents`, sets
    `status` to `PAID`, and records `disbursed_by_user_id`; because
    `approved_cents` moved, the applicant's `total_drawn_cents`,
    `cash_on_hand_cents` and `available_drawdown_cents` are recomputed, and
    because `cash_on_hand_cents` moved, the declaration's `total_drawn_cents` is
    recomputed; the drawdown's, the applicant's and the declaration's `version`
    each increment by 1."

    Design: Corner/endpoints/applicant_ledger_computed_read_matches_the_ledger_formula
    """
    scenario = setup_paid_drawdown(
        400_000,
        officer_user_id=SECOND_GRANTS_OFFICER_USER_ID,
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4987"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )

    applicant = validate_success(
        api.get_applicant(scenario["applicant"]["id"], make_auditor_headers())
    )
    assert applicant["total_obligated_cents"] == 1_500_000, (
        f"Expected total_obligated_cents 1500000, got {applicant['total_obligated_cents']}"
    )
    assert applicant["total_drawn_cents"] == 400_000, (
        f"Expected total_drawn_cents 400000, got {applicant['total_drawn_cents']}"
    )
    assert applicant["total_refunded_cents"] == 0, (
        f"Expected total_refunded_cents 0, got {applicant['total_refunded_cents']}"
    )
    assert applicant["cash_on_hand_cents"] == 400_000, (
        f"Expected cash_on_hand_cents 400000, got {applicant['cash_on_hand_cents']}"
    )
    assert applicant["available_drawdown_cents"] == 1_100_000, (
        f"Expected available_drawdown_cents 1100000, got "
        f"{applicant['available_drawdown_cents']}"
    )
    assert applicant["pending_deobligation_cents"] == 0, (
        f"Expected pending_deobligation_cents 0, got {applicant['pending_deobligation_cents']}"
    )
    assert applicant["drawdown_status"] == "ACTIVE", (
        f"Expected drawdown_status ACTIVE, got {applicant['drawdown_status']}"
    )
    assert applicant["audit_requirement"] == "NONE", (
        "Expected audit_requirement NONE below the single-audit threshold, got "
        f"{applicant['audit_requirement']}"
    )

    disaster = validate_success(
        api.get_disaster(scenario["disaster"]["id"], make_auditor_headers())
    )
    assert disaster["total_obligated_cents"] == 1_500_000, (
        "Expected the declaration to roll up total_obligated_cents 1500000, got "
        f"{disaster['total_obligated_cents']}"
    )
    assert disaster["total_drawn_cents"] == 400_000, (
        "Expected the declaration to roll up total_drawn_cents 400000, got "
        f"{disaster['total_drawn_cents']}"
    )
    assert disaster["suspended_applicant_count"] == 0, (
        f"Expected suspended_applicant_count 0, got {disaster['suspended_applicant_count']}"
    )
    assert disaster["enhanced_monitoring_applicant_count"] == 0, (
        "Expected enhanced_monitoring_applicant_count 0, got "
        f"{disaster['enhanced_monitoring_applicant_count']}"
    )


# ---------------------------------------------------------------------------
# Closeout certification is conditional on a closeout request
# ---------------------------------------------------------------------------
def _setup_obligated_project_with_one_allowed_materials_line():
    """A SMALL project obligated at 750000 on one ALLOWED materials line."""
    return setup_obligated_project(
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4988"},
        project_overrides={
            "title": "Pump house repair",
            "scope_of_work": "Replace the pump house roof deck",
            "estimated_repair_cost_cents": 1_000_000,
        },
        line_items=[
            {
                "cost_type": "MATERIALS",
                "claimed_cents": 1_000_000,
                "work_start_at": "2026-06-12T08:00:00Z",
                "work_end_at": "2026-06-12T17:00:00Z",
            }
        ],
    )


def test_closeout_certify_on_an_obligated_project_is_a_state_error(api):
    """PRD §3.9: "Certification belongs to the `StateAuditor`, who supplies an
    `audit_finding` and drives `CLOSEOUT_REQUESTED → CLOSED`."
    PRD §2.7: "State admissibility of the target row, and — for drawdown
    creation and deobligation creation — of the referenced project:
    `ERR_PROJECT_INVALID_STATE`, `ERR_DISASTER_INVALID_STATE`,
    `ERR_DAMAGE_SITE_ALREADY_ADJUDICATED`, `ERR_CONTRACT_ALREADY_REVIEWED`,
    `ERR_COST_LINE_ITEM_LOCKED`, `ERR_FACILITY_AMENDMENT_LOCKED`,
    `ERR_DRAWDOWN_INVALID_STATE`, `ERR_DEOBLIGATION_NOT_FINAL`,
    `ERR_APPEAL_ALREADY_DECIDED` or `ERR_REPORT_ALREADY_SUBMITTED` (all 409)."

    Design: Corner/endpoints/closeout_certify_is_conditional_on_a_closeout_request
    """
    scenario = _setup_obligated_project_with_one_allowed_materials_line()

    response = api.certify_closeout(
        scenario["project"]["id"],
        {"audit_finding": "Certifying before the applicant asked"},
        make_auditor_headers(),
    )

    validate_error(response, ApiErrorId.ERR_PROJECT_INVALID_STATE)

    project = validate_success(
        api.get_project(scenario["project"]["id"], make_auditor_headers())
    )
    assert project["status"] == "OBLIGATED", (
        f"Expected the project to stay OBLIGATED after the refusal, got {project['status']}"
    )
    assert project["federal_share_final_cents"] is None, (
        "Expected federal_share_final_cents still null after the refusal, got "
        f"{project['federal_share_final_cents']}"
    )


def test_closeout_certify_succeeds_once_closeout_has_been_requested(api):
    """PRD §3.9: "When the work is done and the receipts are in, the
    `ApplicantAgent` requests closeout, driving the project `OBLIGATED →
    CLOSEOUT_REQUESTED`."
    PRD §3.9: "Its repair basis is the sum of `eligible_cents` over the
    project's `ALLOWED` and `PARTIALLY_ALLOWED` lines, with **no** estimate
    fallback — the empty case cannot arise because it was rejected upstream."
    PRD §3.9: "`eligible_cost_final_cents` is therefore the documented repair
    basis less the actual settlement allocation, floored at 0, plus the frozen
    mitigation component."
    PRD §3.9: "A **`SMALL`** project is funded on its estimate and is never
    reconciled against actuals: `federal_share_final_cents` is set equal to
    `federal_share_obligated_cents`, `closeout_variance_cents` is set to 0, and
    **no** determination is created no matter how far the documented actuals
    fell below the estimate."

    Design: Corner/endpoints/closeout_certify_is_conditional_on_a_closeout_request
    """
    scenario = _setup_obligated_project_with_one_allowed_materials_line()
    project_id = scenario["project"]["id"]
    agent = make_applicant_agent_headers(scenario["applicant"]["id"])
    assert scenario["project"]["size_class"] == "SMALL", (
        "Expected a SMALL project below the 4000000 threshold, got "
        f"{scenario['project']['size_class']}"
    )

    requested = validate_success(api.request_closeout(project_id, agent))
    assert requested["status"] == "CLOSEOUT_REQUESTED", (
        f"Expected CLOSEOUT_REQUESTED, got {requested['status']}"
    )
    assert requested["eligible_cost_final_cents"] == 1_000_000, (
        "Expected eligible_cost_final_cents 1000000 from the documented line, got "
        f"{requested['eligible_cost_final_cents']}"
    )

    certified = validate_success(
        api.certify_closeout(
            project_id,
            {"audit_finding": "Documented costs agree with the approved scope"},
            make_auditor_headers(),
        )
    )
    assert certified["status"] == "CLOSED", (
        f"Expected CLOSED after certification, got {certified['status']}"
    )
    assert certified["federal_share_final_cents"] == 750_000, (
        "Expected federal_share_final_cents equal to the obligated 750000 on a SMALL "
        f"project, got {certified['federal_share_final_cents']}"
    )
    assert certified["closeout_variance_cents"] == 0, (
        f"Expected closeout_variance_cents 0 on a SMALL project, got "
        f"{certified['closeout_variance_cents']}"
    )

    rows, meta = validate_paginated(api.list_deobligations(make_auditor_headers()))
    assert meta["total_count"] == 0, (
        "Expected no determination from a SMALL-project certification, got total_count "
        f"{meta['total_count']}"
    )
    assert rows == [], f"Expected an empty determination page, got {rows}"


# ---------------------------------------------------------------------------
# The uniform failure envelope
# ---------------------------------------------------------------------------
ENVELOPE_CASES = [
    ("missing_headers", 401, ApiErrorId.ERR_UNAUTHENTICATED),
    ("unauthorized_role", 403, ApiErrorId.ERR_FORBIDDEN_ROLE),
    ("unknown_path_identifier", 404, ApiErrorId.ERR_DISASTER_NOT_FOUND),
    ("missing_required_body_field", 422, ApiErrorId.ERR_INVALID_REQUEST),
]


@pytest.mark.parametrize(
    "case,expected_status,expected_error_id",
    ENVELOPE_CASES,
    ids=[case[0] for case in ENVELOPE_CASES],
)
def test_error_response_envelope_is_uniform_across_status_codes(
    api, case, expected_status, expected_error_id
):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format:"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.1: "If either header is absent, or if the value in `X-User-Role` is
    not one of the six roles defined below, the request is rejected with
    `ERR_UNAUTHENTICATED` (401)."
    PRD §2.1: "If the headers are well formed but the declared role is not
    among the roles authorized for the target endpoint in §4, the request is
    rejected with `ERR_FORBIDDEN_ROLE` (403)."
    PRD §2.7: "The first identifier that does not resolve decides the error:
    `ERR_DISASTER_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_FACILITY_NOT_FOUND`, `ERR_DAMAGE_SITE_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND`, `ERR_COST_LINE_ITEM_NOT_FOUND`,
    `ERR_RESOURCE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
    `ERR_DRAWDOWN_NOT_FOUND`, `ERR_PROGRESS_REPORT_NOT_FOUND`,
    `ERR_DEOBLIGATION_NOT_FOUND` or `ERR_APPEAL_NOT_FOUND` (all 404)."
    PRD §2.7: "Failures here yield `ERR_INVALID_REQUEST` (422); a malformed
    page window yields `ERR_INVALID_PAGINATION` (422)."

    Design: Corner/errors/error_response_envelope_is_uniform_across_status_codes
    """
    scenario = setup_declaration("2026-07-01T00:00:00Z", declaration_number="DR-4989")
    disaster = scenario["disaster"]

    if case == "missing_headers":
        response = api.get_disaster(disaster["id"], {})
    elif case == "unauthorized_role":
        response = api.create_disaster(
            disaster_payload(
                declaration_number="DR-4989-B",
                state_code="OK",
                incident_start_at="2026-08-01T00:00:00Z",
                incident_end_at="2026-08-10T00:00:00Z",
                population=400_000,
            ),
            make_specialist_headers(),
        )
    elif case == "unknown_path_identifier":
        response = api.get_disaster(NON_EXISTENT_UUID, make_admin_headers())
    else:
        payload = applicant_payload(disaster["id"])
        del payload["applicant_type"]
        response = api.create_applicant(payload, make_admin_headers())

    error = validate_error(response, expected_error_id, expected_status=expected_status)
    assert set(error.keys()) == {"error_id", "message"}, (
        f"Expected exactly error_id and message under data, got {sorted(error.keys())}"
    )
    assert error["message"].strip(), "Expected a non-empty human-readable message"

    body = response.json()
    assert body["response_type"] == "error", (
        f"Expected response_type 'error', got {body['response_type']!r}"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "Expected the error meta to carry only api_request_id and api_request_timestamp, got "
        f"{sorted(body['meta'].keys())}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"Expected api_request_id to start with req_, got {body['meta']['api_request_id']}"
    )

    _, disaster_meta = validate_paginated(api.list_disasters(make_admin_headers()))
    assert disaster_meta["total_count"] == 1, (
        "Expected the rejection to create no declaration, got total_count "
        f"{disaster_meta['total_count']}"
    )
    _, applicant_meta = validate_paginated(api.list_applicants(make_admin_headers()))
    assert applicant_meta["total_count"] == 0, (
        "Expected the rejection to create no applicant, got total_count "
        f"{applicant_meta['total_count']}"
    )
    unchanged = validate_success(api.get_disaster(disaster["id"], make_admin_headers()))
    assert unchanged["version"] == disaster["version"], (
        "Expected the rejection to mutate no row, but the declaration version moved from "
        f"{disaster['version']} to {unchanged['version']}"
    )


# ---------------------------------------------------------------------------
# The fixed evaluation order: path identifiers, then body shape, then body FKs
# ---------------------------------------------------------------------------
def test_unknown_path_identifier_is_reported_before_an_invalid_body_enum(api):
    """PRD §2.7: "Checks are therefore evaluated in the following fixed order,
    and the **first** failing rung decides the response."
    PRD §2.7: "A later rung never masks an earlier one, and an earlier rung
    never runs after a later one has already passed."
    PRD §2.7: "Resolution of every identifier embedded in the URL path,
    validated left to right."
    PRD §2.7: "The first identifier that does not resolve decides the error:
    `ERR_DISASTER_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`,
    `ERR_FACILITY_NOT_FOUND`, `ERR_DAMAGE_SITE_NOT_FOUND`,
    `ERR_PROJECT_NOT_FOUND`, `ERR_COST_LINE_ITEM_NOT_FOUND`,
    `ERR_RESOURCE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`,
    `ERR_DRAWDOWN_NOT_FOUND`, `ERR_PROGRESS_REPORT_NOT_FOUND`,
    `ERR_DEOBLIGATION_NOT_FOUND` or `ERR_APPEAL_NOT_FOUND` (all 404)."
    PRD §2.7: "Failures here yield `ERR_INVALID_REQUEST` (422); a malformed
    page window yields `ERR_INVALID_PAGINATION` (422)."

    Design: Corner/errors/path_id_resolution_precedes_body_shape_validation
    """
    scenario = setup_declaration("2026-07-01T00:00:00Z", declaration_number="DR-4990")
    create_applicant(scenario["disaster"]["id"])

    response = api.cost_review(
        NON_EXISTENT_UUID, {"decision": "MAYBE"}, make_specialist_headers()
    )

    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND)


def test_invalid_body_enum_is_reported_before_an_unresolvable_body_foreign_key(api):
    """PRD §2.7: "Checks are therefore evaluated in the following fixed order,
    and the **first** failing rung decides the response."
    PRD §2.7: "A later rung never masks an earlier one, and an earlier rung
    never runs after a later one has already passed."
    PRD §2.7: "Failures here yield `ERR_INVALID_REQUEST` (422); a malformed
    page window yields `ERR_INVALID_PAGINATION` (422)."
    PRD §2.7: "Resolution of every foreign key supplied in the body —
    `disaster_id`, `applicant_id`, `facility_id`, `project_id`,
    `force_account_resource_id`, `contract_id`, `deobligation_id` and
    `prior_appeal_id` — with the same 404 error identifiers as rung 4."

    Design: Corner/errors/path_id_resolution_precedes_body_shape_validation
    """
    scenario = setup_declaration("2026-07-01T00:00:00Z", declaration_number="DR-4990")
    applicant = create_applicant(scenario["disaster"]["id"])

    response = api.create_cost_line_item(
        cost_line_item_payload(
            NON_EXISTENT_UUID,
            cost_type="GRAVEL",
            claimed_cents=1_000,
            work_start_at="2026-06-12T08:00:00Z",
            work_end_at="2026-06-12T17:00:00Z",
        ),
        make_applicant_agent_headers(applicant["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(api.list_cost_line_items(make_admin_headers()))
    assert meta["total_count"] == 0, (
        f"Expected the rejection to create no cost line item, got total_count "
        f"{meta['total_count']}"
    )
    assert rows == [], f"Expected an empty cost line item page, got {rows}"


# ---------------------------------------------------------------------------
# Immediate cascade consistency on obligation
# ---------------------------------------------------------------------------
def test_obligation_cascade_is_fully_visible_in_the_same_request(api):
    """PRD §2.9: "Cascades in this system are **immediate**: the full chain of
    consequences of an operation is applied inside the triggering request and is
    observable in that request's response."
    PRD §3.7: "Then the repair share is that net repair figure multiplied by
    the declaration's `federal_cost_share_pct` and rounded half up to whole
    cents, **and separately** the mitigation share is `mitigation_approved_cents`
    multiplied by the same `federal_cost_share_pct` and rounded half up to whole
    cents."
    PRD §3.7: "The project's `status` becomes `OBLIGATED` and
    `obligated_by_user_id` records the acting officer's `X-User-ID`, which
    permanently bars that officer from disbursing this project's drawdowns."
    PRD §3.7: "Because `total_obligated_cents` moved, the single-audit test
    runs: when it now stands at or above 75,000,000 cents — seven hundred fifty
    thousand dollars of federal award — and the applicant's `monitoring_status`
    is still `STANDARD`, `audit_requirement` becomes `SINGLE_AUDIT` and
    `monitoring_status` escalates `MONITORING:STANDARD → MONITORING:ENHANCED`."
    PRD §3.7: "Because `monitoring_status` became `ENHANCED`, the system
    creates one progress report row for this applicant in status `DUE`, for the
    quarter containing the current logical clock, with `quarter_label`,
    `period_start_at`, `period_end_at` and `due_at` all derived by the quarter
    rules of §3.8."
    PRD §3.7: "Because that report row now exists, the declaration's
    `enhanced_monitoring_applicant_count` is recomputed; the declaration's
    `total_obligated_cents` is likewise recomputed from its applicants'
    ledgers."

    Design: Corner/consistency_model/obligation_cascade_is_fully_visible_in_the_same_request
    """
    scenario = setup_validated_project(
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-5000"},
        project_overrides={
            "title": "Pump station rebuild",
            "scope_of_work": "Rebuild the pump station",
            "estimated_repair_cost_cents": 100_000_000,
        },
    )
    officer = make_grants_officer_headers(GRANTS_OFFICER_USER_ID)

    obligated = validate_success(api.obligate_project(scenario["project"]["id"], officer))

    assert obligated["status"] == "OBLIGATED", (
        f"Expected OBLIGATED in the obligate response body, got {obligated['status']}"
    )
    assert obligated["federal_share_obligated_cents"] == 75_000_000, (
        "Expected federal_share_obligated_cents 75000000 in the obligate response body, got "
        f"{obligated['federal_share_obligated_cents']}"
    )
    assert obligated["obligated_by_user_id"] == GRANTS_OFFICER_USER_ID, (
        f"Expected obligated_by_user_id {GRANTS_OFFICER_USER_ID}, got "
        f"{obligated['obligated_by_user_id']}"
    )

    applicant = validate_success(api.get_applicant(scenario["applicant"]["id"], officer))
    assert applicant["total_obligated_cents"] == 75_000_000, (
        f"Expected total_obligated_cents 75000000 on the very next read, got "
        f"{applicant['total_obligated_cents']}"
    )
    assert applicant["available_drawdown_cents"] == 75_000_000, (
        f"Expected available_drawdown_cents 75000000, got "
        f"{applicant['available_drawdown_cents']}"
    )
    assert applicant["audit_requirement"] == "SINGLE_AUDIT", (
        "Expected SINGLE_AUDIT at the 75000000 threshold, got "
        f"{applicant['audit_requirement']}"
    )
    assert applicant["monitoring_status"] == "ENHANCED", (
        f"Expected ENHANCED monitoring after the escalation, got "
        f"{applicant['monitoring_status']}"
    )

    reports, report_meta = validate_paginated(api.list_progress_reports(officer))
    assert report_meta["total_count"] == 1, (
        "Expected one auto-created progress report on the very next read, got total_count "
        f"{report_meta['total_count']}"
    )
    assert reports[0]["status"] == "DUE", (
        f"Expected the auto-created report in DUE, got {reports[0]['status']}"
    )
    assert reports[0]["quarter_label"] == "2026-Q3", (
        "Expected quarter_label 2026-Q3 for the quarter containing 2026-07-01T00:00:00Z, got "
        f"{reports[0]['quarter_label']}"
    )

    disaster = validate_success(api.get_disaster(scenario["disaster"]["id"], officer))
    assert disaster["total_obligated_cents"] == 75_000_000, (
        f"Expected the declaration to roll up 75000000, got "
        f"{disaster['total_obligated_cents']}"
    )
    assert disaster["enhanced_monitoring_applicant_count"] == 1, (
        f"Expected enhanced_monitoring_applicant_count 1, got "
        f"{disaster['enhanced_monitoring_applicant_count']}"
    )

    applicant_again = validate_success(api.get_applicant(scenario["applicant"]["id"], officer))
    assert applicant_again == applicant, (
        "Expected a repeated applicant read to be identical, so nothing in the cascade is "
        f"deferred; got {applicant_again} vs {applicant}"
    )
    disaster_again = validate_success(api.get_disaster(scenario["disaster"]["id"], officer))
    assert disaster_again == disaster, (
        "Expected a repeated declaration read to be identical, so nothing in the cascade is "
        f"deferred; got {disaster_again} vs {disaster}"
    )
