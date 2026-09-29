"""Validation rules: the bounds, uniqueness constraints and prerequisite gates
that decide whether a request is accepted or rejected.

Every test builds its own world from an empty database through the
`test_helpers` scenario helpers and then fires exactly one request whose
outcome the PRD pins.
"""
from datetime import datetime

from test_helpers import (
    AUDITOR_USER_ID,
    GRANTS_OFFICER_USER_ID,
    SECOND_GRANTS_OFFICER_USER_ID,
    ApiErrorId,
    cost_line_item_payload,
    create_applicant,
    create_contract,
    create_facility,
    create_insurance_policy,
    create_progress_report,
    create_project,
    decide_appeal,
    deobligation_payload,
    determine_eligibility,
    disaster_payload,
    file_appeal,
    get_applicant,
    get_deobligation,
    get_disaster,
    get_project,
    make_adjudicator_headers,
    make_admin_headers,
    make_applicant_agent_headers,
    make_auditor_headers,
    make_grants_officer_headers,
    make_specialist_headers,
    progress_report_payload,
    project_payload,
    review_procurement,
    screen_facility,
    set_clock,
    setup_appeal_under_review,
    setup_declaration,
    setup_drafted_project,
    setup_eligible_facility,
    setup_finalized_deobligation,
    setup_obligated_project,
    setup_paid_drawdown,
    setup_validated_project,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_admin_headers()
SPECIALIST = make_specialist_headers()
OFFICER_ONE = make_grants_officer_headers(GRANTS_OFFICER_USER_ID)
OFFICER_TWO = make_grants_officer_headers(SECOND_GRANTS_OFFICER_USER_ID)
AUDITOR = make_auditor_headers(AUDITOR_USER_ID)
ADJUDICATOR = make_adjudicator_headers()


def _instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of the same moment compare
    equal regardless of how many fractional digits the server writes."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Incident-period well-formedness and forward-only amendment
# ---------------------------------------------------------------------------
def test_incident_period_end_not_after_start_is_rejected(api):
    """PRD §3.1: "First, well-formedness: `incident_end_at` must be strictly later
    than `incident_start_at`, and a violation yields `ERR_INCIDENT_PERIOD_INVALID`."

    PRD §3.1: "The amendment moves the end **strictly forward only**: a value that
    is equal to or earlier than the current `incident_end_at` is rejected with
    `ERR_INCIDENT_PERIOD_INVALID`, and the half-open exclusivity check is re-run
    against every other declaration sharing the same `state_code` and
    `incident_type`, so a forward extension that would swallow a neighbouring
    declaration's start is refused with `ERR_INCIDENT_PERIOD_OVERLAP`."

    PRD §3.1: "A successful amendment increments the declaration's `version` by 1."

    Design: Corner/validations/incident_period_end_not_after_start_rejected
    """
    scenario = setup_declaration(
        clock="2026-07-01T00:00:00Z",
        declaration_number="DR-4969",
        state_code="TX",
        incident_type="FLOOD",
        incident_start_at="2026-06-10T00:00:00Z",
        incident_end_at="2026-06-25T00:00:00Z",
        population=2_000_000,
    )
    disaster_id = scenario["disaster"]["id"]

    # A declaration whose end instant equals its start instant is not well formed.
    resp = api.create_disaster(
        disaster_payload(
            declaration_number="DR-4969-B",
            state_code="OK",
            incident_type="FLOOD",
            incident_start_at="2026-06-10T00:00:00Z",
            incident_end_at="2026-06-10T00:00:00Z",
            population=500_000,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_PERIOD_INVALID)

    rows, meta = validate_paginated(api.list_disasters(ADMIN))
    assert meta["total_count"] == 1, (
        f"Expected 1 declaration after the rejected create, got {meta['total_count']}"
    )

    # An amendment that moves the end backwards is refused.
    resp = api.amend_incident_period(
        disaster_id, {"incident_end_at": "2026-06-20T00:00:00Z"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_PERIOD_INVALID)

    # An amendment that re-states the current end is not strictly forward either.
    resp = api.amend_incident_period(
        disaster_id, {"incident_end_at": "2026-06-25T00:00:00Z"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_PERIOD_INVALID)

    # A strictly later end is accepted.
    data = validate_success(
        api.amend_incident_period(
            disaster_id, {"incident_end_at": "2026-06-30T00:00:00Z"}, ADMIN
        )
    )
    assert _instant(data["incident_end_at"]) == _instant("2026-06-30T00:00:00Z"), (
        f"Expected incident_end_at 2026-06-30T00:00:00Z, got {data['incident_end_at']}"
    )
    assert data["version"] == 2, (
        f"Expected version 2 after exactly one accepted amendment, got {data['version']}"
    )


# ---------------------------------------------------------------------------
# Uniqueness of declaration_number and of (applicant_id, quarter_label)
# ---------------------------------------------------------------------------
def test_duplicate_declaration_number_is_rejected(api):
    """PRD §3.1: "The declaration carries a `declaration_number` (a non-empty
    string that must be globally unique across every declaration; a repeat is
    rejected with `ERR_DECLARATION_NUMBER_DUPLICATE`), a `state_code` of exactly
    two uppercase letters identifying the state or territory that owns the
    declaration, an `incident_type` from `SEVERE_STORM`, `FLOOD`, `WILDFIRE`,
    `HURRICANE` and `EARTHQUAKE`, the inclusive incident period bounds
    `incident_start_at` and `incident_end_at`, and a `population` of at least 1
    that serves as the denominator of the per-capita indicator."

    Design: Corner/validations/uniqueness_constraints_on_declaration_and_report_period_rejected
    """
    setup_declaration(
        clock="2026-07-31T00:00:00Z",
        declaration_number="DR-4970",
        state_code="TX",
        incident_type="FLOOD",
        incident_start_at="2026-06-10T00:00:00Z",
        incident_end_at="2026-06-25T00:00:00Z",
        population=2_000_000,
    )

    # A different state, a different incident type and a disjoint period do not
    # rescue a repeated declaration_number: the constraint is global.
    resp = api.create_disaster(
        disaster_payload(
            declaration_number="DR-4970",
            state_code="OK",
            incident_type="SEVERE_STORM",
            incident_start_at="2026-08-01T00:00:00Z",
            incident_end_at="2026-08-10T00:00:00Z",
            population=400_000,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DECLARATION_NUMBER_DUPLICATE)

    rows, meta = validate_paginated(api.list_disasters(ADMIN))
    assert meta["total_count"] == 1, (
        f"Expected 1 declaration after the rejected create, got {meta['total_count']}"
    )


def test_duplicate_report_period_for_one_applicant_is_rejected(api):
    """PRD §3.8: "Only one report may exist per applicant per quarter; a second
    attempt at the same pair of `applicant_id` and `quarter_label` is rejected
    with `ERR_DUPLICATE_REPORT_PERIOD`."

    PRD §3.8: "When an applicant files a report directly, its status is decided on
    the spot: `SUBMITTED` when the logical clock is at or before `due_at`, and
    `LATE` when the clock is past `due_at`, with `submitted_at` stamped from the
    clock either way."

    Design: Corner/validations/uniqueness_constraints_on_declaration_and_report_period_rejected
    """
    scenario = setup_declaration(
        clock="2026-07-31T00:00:00Z",
        declaration_number="DR-4970",
        incident_start_at="2026-06-10T00:00:00Z",
        incident_end_at="2026-06-25T00:00:00Z",
    )
    applicant_a = create_applicant(
        scenario["disaster"]["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    applicant_b = create_applicant(
        scenario["disaster"]["id"],
        name="Coastal Bend Tribe",
        applicant_type="TRIBE",
        population_served=9_000,
    )
    report_a = create_progress_report(
        applicant_a["id"],
        "2026-Q2",
        expenditures_to_date_cents=250_000,
        pct_complete=40,
    )

    # The same applicant filing the same quarter twice is refused.
    resp = api.create_progress_report(
        progress_report_payload(
            applicant_a["id"],
            "2026-Q2",
            expenditures_to_date_cents=300_000,
            pct_complete=50,
        ),
        make_applicant_agent_headers(applicant_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD)

    stored = validate_success(api.get_progress_report(report_a["id"], ADMIN))
    assert stored["expenditures_to_date_cents"] == 250_000, (
        "Expected 250000 expenditures_to_date_cents, got "
        f"{stored['expenditures_to_date_cents']} after the rejected re-filing"
    )

    # A second applicant may file the very same quarter: the pair is what is unique.
    data = validate_success(
        api.create_progress_report(
            progress_report_payload(
                applicant_b["id"],
                "2026-Q2",
                expenditures_to_date_cents=100_000,
                pct_complete=20,
            ),
            make_applicant_agent_headers(applicant_b["id"]),
        ),
        201,
    )
    assert data["status"] == "SUBMITTED", (
        f"Expected SUBMITTED at a clock exactly on due_at, got {data['status']}"
    )


# ---------------------------------------------------------------------------
# Pagination bounds
# ---------------------------------------------------------------------------
def test_pagination_limit_and_offset_out_of_range_are_rejected(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum
    accepted value is 1 and its maximum accepted value is 100."

    PRD §2.3: "`offset` controls the starting position: it defaults to 0 and its
    minimum accepted value is 0."

    PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected
    with `ERR_INVALID_PAGINATION` (422)."

    Design: Corner/validations/pagination_limit_and_offset_out_of_range_rejected
    """
    scenario = setup_declaration(
        clock="2026-07-01T00:00:00Z", declaration_number="DR-4971"
    )
    applicant = create_applicant(
        scenario["disaster"]["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )

    validate_error(
        api.list_applicants(ADMIN, params={"limit": 0}), ApiErrorId.ERR_INVALID_PAGINATION
    )
    validate_error(
        api.list_applicants(ADMIN, params={"limit": 101}),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )
    validate_error(
        api.list_applicants(ADMIN, params={"offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION,
    )

    # The closed upper bound itself is accepted.
    rows, meta = validate_paginated(
        api.list_applicants(ADMIN, params={"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1, (
        f"Expected total_count 1, got {meta['total_count']} at limit=100 offset=0"
    )
    assert meta["has_more"] is False, (
        f"Expected has_more False, got {meta['has_more']} with one row inside the window"
    )
    assert len(rows) == 1, f"Expected 1 row in the page, got {len(rows)}"
    assert rows[0]["id"] == applicant["id"], (
        f"Expected the registered applicant {applicant['id']}, got {rows[0]['id']}"
    )


# ---------------------------------------------------------------------------
# Mitigation request may not exceed the repair estimate
# ---------------------------------------------------------------------------
def test_mitigation_request_above_repair_estimate_is_rejected(api):
    """PRD §3.3: "Mitigation funding — measures that reduce the risk of the same
    damage recurring — is requested at formulation time through the optional
    `mitigation_requested_cents`, which defaults to 0, must be at least 0, and may
    not exceed `estimated_repair_cost_cents`; a larger request is rejected
    outright with `ERR_MITIGATION_EXCEEDS_REPAIR`."

    PRD §3.3: "The project is created in `DRAFT` with `size_class` null,
    `rfi_round_count` 0, `last_rfi_question` null, `work_type` not yet derived,
    and every basis and ledger field at its opening value:
    `repair_eligible_cents`, `anticipated_insurance_cents`,
    `settlement_allocated_cents`, `insurance_reduction_cents`,
    `mitigation_approved_cents`, `eligible_cost_provisional_cents`,
    `federal_share_obligated_cents`, `deobligated_cents` and
    `pending_deobligation_cents` at 0, and `eligible_cost_final_cents`,
    `federal_share_final_cents`, `closeout_variance_cents`,
    `cost_reviewed_by_user_id`, `obligated_by_user_id` and `denial_reason` all
    null."

    Design: Corner/validations/mitigation_request_above_repair_estimate_rejected
    """
    scenario = setup_eligible_facility(
        clock="2026-07-01T00:00:00Z", disaster_overrides={"declaration_number": "DR-4972"}
    )
    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)

    # One cent above the estimate is refused at formulation.
    resp = api.create_project(
        project_payload(
            applicant_id,
            scenario["facility"]["id"],
            category="C",
            title="Over-scoped mitigation",
            scope_of_work="Repair plus an oversized mitigation measure",
            estimated_repair_cost_cents=3_000_000,
            mitigation_requested_cents=3_000_001,
        ),
        agent,
    )
    validate_error(resp, ApiErrorId.ERR_MITIGATION_EXCEEDS_REPAIR)

    rows, meta = validate_paginated(api.list_projects(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected no Project row after the rejected create, got {meta['total_count']}"
    )

    # A request exactly equal to the estimate is inside the bar.
    data = validate_success(
        api.create_project(
            project_payload(
                applicant_id,
                scenario["facility"]["id"],
                category="C",
                title="Fully mitigated repair",
                scope_of_work="Repair plus a mitigation measure of equal value",
                estimated_repair_cost_cents=3_000_000,
                mitigation_requested_cents=3_000_000,
            ),
            agent,
        ),
        201,
    )
    assert data["mitigation_requested_cents"] == 3_000_000, (
        "Expected 3000000 mitigation_requested_cents, got "
        f"{data['mitigation_requested_cents']}"
    )
    assert data["mitigation_approved_cents"] == 0, (
        "Expected 0 mitigation_approved_cents on a DRAFT project, got "
        f"{data['mitigation_approved_cents']}"
    )
    assert data["status"] == "DRAFT", f"Expected DRAFT, got {data['status']}"


# ---------------------------------------------------------------------------
# The private-nonprofit SBA referral prerequisite
# ---------------------------------------------------------------------------
def test_pnp_essential_non_critical_eligibility_without_sba_referral_is_rejected(api):
    """PRD §3.1: "The `ELIGIBLE` branch carries one extra prerequisite: when the
    applicant's `applicant_type` is `PRIVATE_NONPROFIT` and its
    `pnp_service_type` is `ESSENTIAL_NON_CRITICAL`, its
    `pnp_sba_referral_completed` must be true, because an essential-but-non-critical
    nonprofit must be referred to the disaster-loan program before grant money is
    considered; a false flag yields `ERR_PNP_SBA_REFERRAL_REQUIRED`."

    PRD §3.1: "Nonprofits whose `pnp_service_type` is `CRITICAL` face no such
    prerequisite."

    PRD §3.1: "A new applicant starts with `eligibility_status` `PENDING`,
    `monitoring_status` `STANDARD`, `drawdown_status` `ACTIVE`,
    `audit_requirement` `NONE`, `eligibility_rationale` null,
    `risk_score_screening` 0, `risk_score_monitoring` null, `monitoring_scored_at`
    null, `risk_tier` `LOW`, and every ledger figure — `total_obligated_cents`,
    `total_drawn_cents`, `total_refunded_cents`, `cash_on_hand_cents`,
    `available_drawdown_cents`, `pending_deobligation_cents` and
    `delinquent_report_count` — at 0."

    Design: Corner/validations/pnp_essential_non_critical_eligibility_without_sba_referral_rejected
    """
    scenario = setup_declaration(
        clock="2026-07-01T00:00:00Z", declaration_number="DR-4973"
    )
    disaster_id = scenario["disaster"]["id"]

    pnp_a = create_applicant(
        disaster_id,
        name="Harborview Community Theatre",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=3_000,
        pnp_service_type="ESSENTIAL_NON_CRITICAL",
        pnp_sba_referral_completed=False,
        tax_exempt_letter_on_file=True,
    )
    pnp_b = create_applicant(
        disaster_id,
        name="Harborview Senior Center",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=4_000,
        pnp_service_type="ESSENTIAL_NON_CRITICAL",
        pnp_sba_referral_completed=True,
        tax_exempt_letter_on_file=True,
    )
    pnp_c = create_applicant(
        disaster_id,
        name="Harborview Volunteer Fire",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=12_000,
        pnp_service_type="CRITICAL",
        tax_exempt_letter_on_file=True,
    )

    resp = api.determine_eligibility(
        pnp_a["id"],
        {"decision": "ELIGIBLE", "rationale": "Essential non-critical service provider"},
        SPECIALIST,
    )
    validate_error(resp, ApiErrorId.ERR_PNP_SBA_REFERRAL_REQUIRED)

    blocked = validate_success(api.get_applicant(pnp_a["id"], ADMIN))
    assert blocked["eligibility_status"] == "PENDING", (
        f"Expected PENDING after the refused determination, got {blocked['eligibility_status']}"
    )
    assert blocked["eligibility_rationale"] is None, (
        f"Expected null eligibility_rationale, got {blocked['eligibility_rationale']!r}"
    )
    assert blocked["risk_score_screening"] == 0, (
        f"Expected risk_score_screening 0, got {blocked['risk_score_screening']}"
    )
    assert blocked["version"] == 1, (
        f"Expected version 1 because the refused determination wrote nothing, got {blocked['version']}"
    )

    # Supplying the referral clears the gate.
    data_b = validate_success(
        api.determine_eligibility(
            pnp_b["id"],
            {
                "decision": "ELIGIBLE",
                "rationale": "Essential non-critical service provider with SBA referral",
            },
            SPECIALIST,
        )
    )
    assert data_b["eligibility_status"] == "ELIGIBLE", (
        f"Expected ELIGIBLE once the referral is on file, got {data_b['eligibility_status']}"
    )

    # A CRITICAL nonprofit is not subject to the prerequisite at all.
    data_c = validate_success(
        api.determine_eligibility(
            pnp_c["id"],
            {"decision": "ELIGIBLE", "rationale": "Critical service provider"},
            SPECIALIST,
        )
    )
    assert data_c["eligibility_status"] == "ELIGIBLE", (
        f"Expected ELIGIBLE for a CRITICAL nonprofit, got {data_c['eligibility_status']}"
    )


# ---------------------------------------------------------------------------
# Project submission requires an ELIGIBLE applicant
# ---------------------------------------------------------------------------
def test_project_submit_by_ineligible_applicant_is_rejected(api):
    """PRD §3.3: "The acting agent must own the project, the project must actually
    be in `DRAFT`, the owning applicant's `eligibility_status` must be `ELIGIBLE`
    (otherwise `ERR_APPLICANT_NOT_ELIGIBLE`), the repaired facility's
    `eligibility_status` must be `ELIGIBLE` (otherwise `ERR_FACILITY_INELIGIBLE`),
    and the declaration must still be `DECLARED` (otherwise
    `ERR_DISASTER_NOT_OPEN`)."

    PRD §3.1: "What differs is only what happens afterwards — the `ELIGIBLE`
    branch opens project submission, cost claiming and cash drawdown, while the
    `INELIGIBLE` branch performs no ledger work at all and permanently blocks all
    three with `ERR_APPLICANT_NOT_ELIGIBLE`."

    Design: Corner/validations/project_submit_by_ineligible_applicant_rejected
    """
    scenario = setup_declaration(
        clock="2026-07-01T00:00:00Z", declaration_number="DR-4974"
    )
    disaster_id = scenario["disaster"]["id"]

    # Applicant P: left undetermined, so still PENDING.
    applicant_p = create_applicant(
        disaster_id,
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    facility_p = create_facility(
        applicant_p["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    screen_facility(facility_p["id"])
    project_p = create_project(
        applicant_p["id"],
        facility_p["id"],
        category="C",
        title="Pump house repair",
        scope_of_work="Repair the pump house",
        estimated_repair_cost_cents=500_000,
    )

    # Applicant Q: determined INELIGIBLE, but with an ELIGIBLE facility.
    applicant_q = create_applicant(
        disaster_id,
        name="Harborview Yacht Club",
        applicant_type="PRIVATE_NONPROFIT",
        population_served=900,
        pnp_service_type="CRITICAL",
        tax_exempt_letter_on_file=True,
    )
    determine_eligibility(
        applicant_q["id"],
        decision="INELIGIBLE",
        rationale="Facility use is not an eligible service",
    )
    facility_q = create_facility(
        applicant_q["id"],
        name="Club Boathouse",
        facility_type="BUILDING_EQUIPMENT",
        ownership="PNP_OWNED",
    )
    facility_q = screen_facility(facility_q["id"])
    project_q = create_project(
        applicant_q["id"],
        facility_q["id"],
        category="E",
        title="Boathouse repair",
        scope_of_work="Repair the boathouse deck",
        estimated_repair_cost_cents=500_000,
    )

    # A PENDING applicant cannot submit.
    resp = api.submit_project(
        project_p["id"], make_applicant_agent_headers(applicant_p["id"])
    )
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_ELIGIBLE)
    assert get_project(project_p["id"])["status"] == "DRAFT", (
        "Expected the project to stay in DRAFT after the refused submission"
    )

    # The facility gate is satisfied on Q, so only the applicant gate can bite.
    assert facility_q["eligibility_status"] == "ELIGIBLE", (
        f"Expected an ELIGIBLE facility on applicant Q, got {facility_q['eligibility_status']}"
    )
    resp = api.submit_project(
        project_q["id"], make_applicant_agent_headers(applicant_q["id"])
    )
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_ELIGIBLE)
    assert get_project(project_q["id"])["status"] == "DRAFT", (
        "Expected the project to stay in DRAFT after the refused submission"
    )

    # Determining the applicant ELIGIBLE opens submission on the same project.
    determine_eligibility(
        applicant_p["id"],
        decision="ELIGIBLE",
        rationale="Local government inside the declared area",
    )
    data = validate_success(
        api.submit_project(project_p["id"], make_applicant_agent_headers(applicant_p["id"]))
    )
    assert data["status"] == "UNDER_REVIEW", (
        f"Expected UNDER_REVIEW once the applicant is ELIGIBLE, got {data['status']}"
    )


# ---------------------------------------------------------------------------
# Insurance settlement: temporal effectiveness and the coverage bound
# ---------------------------------------------------------------------------
def test_settlement_on_policy_not_effective_at_incident_start_is_rejected(api):
    """PRD §3.6: "And the policy must actually have been in force when the
    disaster struck: its closed effective interval must contain the declaration's
    `incident_start_at`, or the request fails with
    `ERR_POLICY_NOT_EFFECTIVE_AT_INCIDENT`."

    PRD §2.7: "Checks are therefore evaluated in the following fixed order, and
    the **first** failing rung decides the response."

    PRD §3.6: "A new policy carries `settlement_amount_cents` 0, `settled_at`
    null, `allocated_cents` 0 and `unallocated_cents` 0."

    Design: Corner/validations/insurance_settlement_temporal_and_coverage_bounds_rejected
    """
    scenario = setup_declaration(
        clock="2026-07-01T00:00:00Z",
        declaration_number="DR-4975",
        incident_start_at="2026-06-10T00:00:00Z",
        incident_end_at="2026-06-25T00:00:00Z",
    )
    applicant = create_applicant(
        scenario["disaster"]["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    # Policy L binds after the incident started, and its limit is 100000.
    policy_l = create_insurance_policy(
        facility["id"],
        applicant["id"],
        insurer_name="Late Bind Mutual",
        policy_type="PROPERTY",
        coverage_limit_cents=100_000,
        deductible_cents=0,
        effective_start_at="2026-07-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
    )

    # 200000 also breaches the 100000 limit, but the temporal rung decides first.
    resp = api.record_settlement(
        policy_l["id"],
        {"settlement_amount_cents": 200_000, "settled_at": "2026-06-30T00:00:00Z"},
        OFFICER_TWO,
    )
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_EFFECTIVE_AT_INCIDENT)

    stored = validate_success(api.get_insurance_policy(policy_l["id"], ADMIN))
    assert stored["settlement_amount_cents"] == 0, (
        f"Expected 0 settlement_amount_cents, got {stored['settlement_amount_cents']}"
    )
    assert stored["settled_at"] is None, (
        f"Expected null settled_at after the refused settlement, got {stored['settled_at']!r}"
    )


def test_settlement_above_coverage_limit_is_rejected(api):
    """PRD §3.6: "The settlement may not exceed the policy's
    `coverage_limit_cents`, or the request fails with
    `ERR_SETTLEMENT_EXCEEDS_COVERAGE`."

    PRD §3.6: "When the walk is finished, the policy's `allocated_cents` is the
    settlement amount less whatever balance remains, and its `unallocated_cents`
    is that remaining balance — proceeds with nowhere to go simply stay on the
    policy."

    Design: Corner/validations/insurance_settlement_temporal_and_coverage_bounds_rejected
    """
    scenario = setup_declaration(
        clock="2026-07-01T00:00:00Z",
        declaration_number="DR-4975",
        incident_start_at="2026-06-10T00:00:00Z",
        incident_end_at="2026-06-25T00:00:00Z",
    )
    applicant = create_applicant(
        scenario["disaster"]["id"],
        name="City of Harborview",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=120_000,
    )
    facility = create_facility(
        applicant["id"],
        name="Riverside Pump Station",
        facility_type="WATER_CONTROL",
        ownership="PUBLIC",
    )
    policy_m = create_insurance_policy(
        facility["id"],
        applicant["id"],
        insurer_name="Gulf Mutual",
        policy_type="PROPERTY",
        coverage_limit_cents=1_000_000,
        deductible_cents=0,
        effective_start_at="2026-01-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
    )

    # One cent above the coverage limit is refused.
    resp = api.record_settlement(
        policy_m["id"],
        {"settlement_amount_cents": 1_000_001, "settled_at": "2026-06-30T00:00:00Z"},
        OFFICER_TWO,
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_COVERAGE)

    # The limit itself is accepted; with no candidate project the proceeds stay put.
    data = validate_success(
        api.record_settlement(
            policy_m["id"],
            {"settlement_amount_cents": 1_000_000, "settled_at": "2026-06-30T00:00:00Z"},
            OFFICER_TWO,
        )
    )
    assert data["settlement_amount_cents"] == 1_000_000, (
        f"Expected 1000000 settlement_amount_cents, got {data['settlement_amount_cents']}"
    )
    assert data["allocated_cents"] == 0, (
        f"Expected 0 allocated_cents with no candidate project, got {data['allocated_cents']}"
    )
    assert data["unallocated_cents"] == 1_000_000, (
        f"Expected 1000000 unallocated_cents, got {data['unallocated_cents']}"
    )
    assert _instant(data["settled_at"]) == _instant("2026-06-30T00:00:00Z"), (
        f"Expected settled_at 2026-06-30T00:00:00Z, got {data['settled_at']}"
    )


# ---------------------------------------------------------------------------
# The two procurement gates on a contracted cost line
# ---------------------------------------------------------------------------
def test_contract_cost_line_against_noncompliant_contract_is_rejected(api):
    """PRD §3.4: "A `contract_type` of `COST_PLUS_PERCENTAGE_OF_COST` is
    categorically forbidden: `NONCOMPLIANT` with reason
    `PROHIBITED_CONTRACT_TYPE`."

    PRD §3.4: "A `NONCOMPLIANT` finding has a forward-looking consequence: from
    that moment on, any attempt to claim a `CONTRACT` cost against that contract
    is refused at creation time with `ERR_PROCUREMENT_NONCOMPLIANT`."

    Design: Corner/validations/contract_cost_line_procurement_gates_rejected
    """
    scenario = setup_drafted_project(
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4976"},
        project_overrides={
            "category": "C",
            "title": "Contracted channel work",
            "scope_of_work": "Contractor clears and armours the channel",
            "estimated_repair_cost_cents": 1_000_000,
        },
    )
    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)

    contract = create_contract(
        applicant_id,
        vendor_name="Percent Plus LLC",
        contract_type="COST_PLUS_PERCENTAGE_OF_COST",
        award_amount_cents=1_000_000,
        awarded_at="2026-06-11T00:00:00Z",
        debarment_check_completed=True,
    )
    reviewed = review_procurement(contract["id"])
    assert reviewed["procurement_status"] == "NONCOMPLIANT", (
        f"Expected NONCOMPLIANT, got {reviewed['procurement_status']}"
    )
    assert reviewed["noncompliance_reason"] == "PROHIBITED_CONTRACT_TYPE", (
        f"Expected PROHIBITED_CONTRACT_TYPE, got {reviewed['noncompliance_reason']}"
    )

    resp = api.create_cost_line_item(
        cost_line_item_payload(
            scenario["project"]["id"],
            cost_type="CONTRACT",
            contract_id=contract["id"],
            claimed_cents=400_000,
            work_start_at="2026-06-12T08:00:00Z",
            work_end_at="2026-06-12T17:00:00Z",
        ),
        agent,
    )
    validate_error(resp, ApiErrorId.ERR_PROCUREMENT_NONCOMPLIANT)

    rows, meta = validate_paginated(api.list_cost_line_items(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected no CostLineItem row after the rejected claim, got {meta['total_count']}"
    )


def test_cost_line_review_while_contract_pending_review_is_rejected(api):
    """PRD §3.5: "A contracted line additionally may not be reviewed while its
    contract is still `PENDING_REVIEW`: the procurement question has to be settled
    first, and an attempt yields `ERR_PROCUREMENT_REVIEW_PENDING`."

    PRD §3.5: "The `review_status` is then `ALLOWED` when `eligible_cents` equals
    `claimed_cents`, `DISALLOWED` when `eligible_cents` is 0, and
    `PARTIALLY_ALLOWED` in between; the equality test comes first, so a line
    claiming nothing and computing nothing lands in `ALLOWED`."

    PRD §3.4: "A new contract sits in `procurement_status` `PENDING_REVIEW` with
    `noncompliance_reason` null and `allowed_cost_total_cents` 0, the last of
    which accumulates the `eligible_cents` of every cost line item on the contract
    whose `review_status` is `ALLOWED` or `PARTIALLY_ALLOWED`."

    Design: Corner/validations/contract_cost_line_procurement_gates_rejected
    """
    scenario = setup_drafted_project(
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4976"},
        project_overrides={
            "category": "C",
            "title": "Contracted channel work",
            "scope_of_work": "Contractor clears and armours the channel",
            "estimated_repair_cost_cents": 1_000_000,
        },
    )
    applicant_id = scenario["applicant"]["id"]

    contract = create_contract(
        applicant_id,
        vendor_name="Bayline Contractors",
        contract_type="SMALL_PURCHASE",
        award_amount_cents=1_000_000,
        awarded_at="2026-06-11T00:00:00Z",
        debarment_check_completed=True,
    )
    assert contract["procurement_status"] == "PENDING_REVIEW", (
        f"Expected PENDING_REVIEW on a fresh contract, got {contract['procurement_status']}"
    )

    # A PENDING_REVIEW contract still permits the claim itself.
    line = validate_success(
        api.create_cost_line_item(
            cost_line_item_payload(
                scenario["project"]["id"],
                cost_type="CONTRACT",
                contract_id=contract["id"],
                claimed_cents=400_000,
                work_start_at="2026-06-13T08:00:00Z",
                work_end_at="2026-06-13T17:00:00Z",
            ),
            make_applicant_agent_headers(applicant_id),
        ),
        201,
    )
    assert line["review_status"] == "SUBMITTED", (
        f"Expected SUBMITTED on a fresh cost line, got {line['review_status']}"
    )

    # ... but blocks the line's own review until procurement has been settled.
    resp = api.review_cost_line_item(line["id"], SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_PROCUREMENT_REVIEW_PENDING)
    still = validate_success(api.get_cost_line_item(line["id"], ADMIN))
    assert still["review_status"] == "SUBMITTED", (
        f"Expected the line to stay SUBMITTED, got {still['review_status']}"
    )

    reviewed_contract = review_procurement(contract["id"])
    assert reviewed_contract["procurement_status"] == "COMPLIANT", (
        f"Expected COMPLIANT, got {reviewed_contract['procurement_status']}"
    )

    data = validate_success(api.review_cost_line_item(line["id"], SPECIALIST))
    assert data["eligible_cents"] == 400_000, (
        f"Expected 400000 eligible_cents, got {data['eligible_cents']}"
    )
    assert data["review_status"] == "ALLOWED", (
        f"Expected ALLOWED, got {data['review_status']}"
    )
    contract_after = validate_success(api.get_contract(contract["id"], ADMIN))
    assert contract_after["allowed_cost_total_cents"] == 400_000, (
        "Expected 400000 allowed_cost_total_cents, got "
        f"{contract_after['allowed_cost_total_cents']}"
    )


# ---------------------------------------------------------------------------
# The obtain-and-maintain flood insurance bar at obligation
# ---------------------------------------------------------------------------
def test_obligation_without_covering_flood_policy_is_rejected(api):
    """PRD §3.6: "Such a facility may not have a project obligated unless at least
    one insurance policy on it has `policy_type` `FLOOD` and an effective interval
    whose closed bounds contain the declaration's `incident_start_at`."

    PRD §3.6: "A `PROPERTY` policy does not satisfy the bar however generous its
    limit, and `is_nfip` is recorded for reference but is not itself the test."

    PRD §3.6: "A project failing this bar is refused at obligation with
    `ERR_INSURANCE_REQUIREMENT_UNMET`."

    PRD §3.7: "The project's `status` becomes `OBLIGATED` and
    `obligated_by_user_id` records the acting officer's `X-User-ID`, which
    permanently bars that officer from disbursing this project's drawdowns."

    Design: Corner/validations/obligation_without_covering_flood_policy_rejected
    """
    scenario = setup_validated_project(
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4977"},
        facility_overrides={
            "name": "Riverfront Community Hall",
            "facility_type": "BUILDING_EQUIPMENT",
            "ownership": "PUBLIC",
            "flood_zone": True,
            "prior_disaster_flood_damage": True,
        },
        project_overrides={
            "category": "E",
            "title": "Community hall repair",
            "scope_of_work": "Replace flooded interior finishes",
            "estimated_repair_cost_cents": 2_000_000,
        },
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]
    facility_id = scenario["facility"]["id"]

    # No policy at all: the bar is unmet.
    validate_error(
        api.obligate_project(project_id, OFFICER_ONE),
        ApiErrorId.ERR_INSURANCE_REQUIREMENT_UNMET,
    )
    assert get_project(project_id)["status"] == "VALIDATED", (
        "Expected the project to stay VALIDATED after the refused obligation"
    )

    # A PROPERTY policy does not satisfy the bar.
    create_insurance_policy(
        facility_id,
        applicant_id,
        insurer_name="Gulf Mutual",
        policy_type="PROPERTY",
        coverage_limit_cents=1_000_000,
        deductible_cents=0,
        effective_start_at="2026-01-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
    )
    validate_error(
        api.obligate_project(project_id, OFFICER_ONE),
        ApiErrorId.ERR_INSURANCE_REQUIREMENT_UNMET,
    )

    # A FLOOD policy covering incident_start_at clears it.
    create_insurance_policy(
        facility_id,
        applicant_id,
        insurer_name="NFIP Gulf",
        policy_type="FLOOD",
        coverage_limit_cents=1_000_000,
        deductible_cents=0,
        effective_start_at="2026-01-01T00:00:00Z",
        effective_end_at="2026-12-31T00:00:00Z",
        is_nfip=True,
    )
    data = validate_success(api.obligate_project(project_id, OFFICER_ONE))
    assert data["status"] == "OBLIGATED", f"Expected OBLIGATED, got {data['status']}"
    assert data["obligated_by_user_id"] == GRANTS_OFFICER_USER_ID, (
        f"Expected obligated_by_user_id {GRANTS_OFFICER_USER_ID}, got {data['obligated_by_user_id']}"
    )
    assert data["federal_share_obligated_cents"] == 1_500_000, (
        "Expected 1500000 federal_share_obligated_cents, got "
        f"{data['federal_share_obligated_cents']}"
    )
    assert data["insurance_reduction_cents"] == 0, (
        "Expected 0 insurance_reduction_cents because the policies post-date cost "
        f"review, got {data['insurance_reduction_cents']}"
    )
    applicant = get_applicant(applicant_id)
    assert applicant["total_obligated_cents"] == 1_500_000, (
        f"Expected 1500000 total_obligated_cents, got {applicant['total_obligated_cents']}"
    )
    assert applicant["available_drawdown_cents"] == 1_500_000, (
        f"Expected 1500000 available_drawdown_cents, got {applicant['available_drawdown_cents']}"
    )


# ---------------------------------------------------------------------------
# The sixty-day appeal window
# ---------------------------------------------------------------------------
def test_appeal_filed_after_window_expiry_is_rejected(api):
    """PRD §3.9: "It stamps `finalized_at` from the logical clock and sets
    `appeal_deadline_at` to that instant plus the sixty-day appeal window."

    PRD §3.9: "Only a `FINAL` determination is appealable — a `PROPOSED` or
    `REVERSED` one yields `ERR_DEOBLIGATION_NOT_FINAL` — and `filed_at`, stamped
    from the logical clock, must be at or before the determination's
    `appeal_deadline_at`, with a clock instant exactly equal to the deadline still
    inside the window and anything later rejected as
    `ERR_APPEAL_WINDOW_EXPIRED`."

    PRD §3.9: "A filed appeal sits in `SUBMITTED` with `relief_granted_cents` 0,
    `decided_at` null, `decided_by_user_id` null and `decision_rationale` null."

    PRD §3.9: "The `level` is derived, not supplied: it is `FIRST` when
    `prior_appeal_id` is null and `SECOND` otherwise."

    Design: Corner/validations/appeal_filed_after_window_expiry_rejected
    """
    scenario = setup_finalized_deobligation(
        500_000,
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4978"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    deobligation = scenario["deobligation"]
    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)

    assert deobligation["status"] == "FINAL", (
        f"Expected FINAL, got {deobligation['status']}"
    )
    assert _instant(deobligation["finalized_at"]) == _instant("2026-07-01T00:00:00Z"), (
        f"Expected finalized_at 2026-07-01T00:00:00Z, got {deobligation['finalized_at']}"
    )
    assert _instant(deobligation["appeal_deadline_at"]) == _instant(
        "2026-08-30T00:00:00Z"
    ), (
        "Expected appeal_deadline_at 2026-08-30T00:00:00Z (sixty days on), got "
        f"{deobligation['appeal_deadline_at']}"
    )

    # One day past the deadline the window has closed.
    set_clock("2026-08-31T00:00:00Z")
    resp = api.create_appeal(
        {
            "deobligation_id": deobligation["id"],
            "grounds": "The reduced scope was still eligible work",
            "relief_requested_cents": 500_000,
        },
        agent,
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
    rows, meta = validate_paginated(api.list_appeals(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected no Appeal row after the rejected filing, got {meta['total_count']}"
    )

    # A clock instant exactly equal to the deadline is still inside the window.
    set_clock("2026-08-30T00:00:00Z")
    data = validate_success(
        api.create_appeal(
            {
                "deobligation_id": deobligation["id"],
                "grounds": "The reduced scope was still eligible work",
                "relief_requested_cents": 500_000,
            },
            agent,
        ),
        201,
    )
    assert data["status"] == "SUBMITTED", f"Expected SUBMITTED, got {data['status']}"
    assert data["level"] == "FIRST", f"Expected FIRST, got {data['level']}"
    assert _instant(data["filed_at"]) == _instant("2026-08-30T00:00:00Z"), (
        f"Expected filed_at 2026-08-30T00:00:00Z, got {data['filed_at']}"
    )
    assert data["relief_granted_cents"] == 0, (
        f"Expected 0 relief_granted_cents on filing, got {data['relief_granted_cents']}"
    )
    assert get_project(scenario["project"]["id"])["deobligated_cents"] == 500_000, (
        "Expected deobligated_cents to stay at 500000 because filing an appeal moves no money"
    )


# ---------------------------------------------------------------------------
# Appeal admissibility: duplication, exhaustion, escalation parent
# ---------------------------------------------------------------------------
def test_second_appeal_while_first_still_submitted_is_rejected(api):
    """PRD §3.9: "No other appeal on that determination may still be `SUBMITTED`,
    because one live case at a time is the rule (`ERR_DUPLICATE_APPEAL`)."

    Design: Corner/validations/appeal_admissibility_second_duplicate_and_exhaustion_rejected
    """
    scenario = setup_finalized_deobligation(
        500_000,
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4979"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    deobligation_id = scenario["deobligation"]["id"]
    applicant_id = scenario["applicant"]["id"]

    file_appeal(deobligation_id, applicant_id, 100_000, grounds="Scope reduction was unwarranted")

    resp = api.create_appeal(
        {
            "deobligation_id": deobligation_id,
            "grounds": "Refiling while the first appeal is pending",
            "relief_requested_cents": 200_000,
        },
        make_applicant_agent_headers(applicant_id),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_APPEAL)

    rows, meta = validate_paginated(api.list_appeals(ADMIN))
    on_determination = [row for row in rows if row["deobligation_id"] == deobligation_id]
    assert len(on_determination) == 1, (
        f"Expected exactly 1 appeal on the determination, got {len(on_determination)}"
    )


def test_third_appeal_after_decided_second_level_is_rejected(api):
    """PRD §3.9: "And once a `SECOND`-level appeal exists on a determination, no
    further appeal may be filed against it at all
    (`ERR_APPEAL_LEVEL_EXHAUSTED`)."

    PRD §3.9: "**`SUBMITTED → DENIED`** sets `relief_granted_cents` to 0 and moves
    **nothing** outside the appeal row — no determination, project, applicant or
    declaration field changes, and no version other than the appeal's increments."

    Design: Corner/validations/appeal_admissibility_second_duplicate_and_exhaustion_rejected
    """
    scenario = setup_finalized_deobligation(
        500_000,
        reason="DISALLOWED_COST",
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4979"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    deobligation_id = scenario["deobligation"]["id"]
    applicant_id = scenario["applicant"]["id"]

    first = file_appeal(
        deobligation_id, applicant_id, 100_000, grounds="The disallowed cost was documented"
    )
    decide_appeal(
        first["id"], "DENY", decision_rationale="Documentation remains insufficient"
    )
    second = file_appeal(
        deobligation_id,
        applicant_id,
        100_000,
        grounds="Escalating the denied first-level appeal",
        prior_appeal_id=first["id"],
    )
    second = decide_appeal(
        second["id"],
        "DENY",
        decision_rationale="Second-level review upholds the determination",
    )
    assert second["level"] == "SECOND", f"Expected SECOND, got {second['level']}"
    assert second["status"] == "DENIED", f"Expected DENIED, got {second['status']}"

    resp = api.create_appeal(
        {
            "deobligation_id": deobligation_id,
            "grounds": "Third-level escalation attempt",
            "relief_requested_cents": 100_000,
            "prior_appeal_id": second["id"],
        },
        make_applicant_agent_headers(applicant_id),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_LEVEL_EXHAUSTED)


def test_second_appeal_escalating_a_granted_first_appeal_is_rejected(api):
    """PRD §3.9: "A `SECOND`-level appeal's `prior_appeal_id` must reference an
    appeal on the *same* determination whose `status` is `DENIED` or
    `PARTIALLY_GRANTED`, since only a loss at the first level opens the second
    (`ERR_SECOND_APPEAL_REQUIRES_FIRST_DENIED`)."

    PRD §3.9: "`reversed_cents` is set to `relief_granted_cents`; the
    determination's `status` becomes `REVERSED` when `reversed_cents` equals the
    full `amount_cents`, and **stays `FINAL`** when the reversal is partial, that
    is when `reversed_cents` is above 0 but below `amount_cents`."

    Design: Corner/validations/appeal_admissibility_second_duplicate_and_exhaustion_rejected
    """
    scenario = setup_finalized_deobligation(
        500_000,
        reason="PROCUREMENT_NONCOMPLIANCE",
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4979"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    deobligation_id = scenario["deobligation"]["id"]
    applicant_id = scenario["applicant"]["id"]

    granted = file_appeal(
        deobligation_id,
        applicant_id,
        100_000,
        grounds="Procurement was in fact competitive",
    )
    granted = decide_appeal(
        granted["id"], "GRANT", decision_rationale="Competition documentation accepted"
    )
    assert granted["status"] == "GRANTED", f"Expected GRANTED, got {granted['status']}"

    determination = get_deobligation(deobligation_id)
    assert determination["status"] == "FINAL", (
        f"Expected the determination to stay FINAL on a partial reversal, got {determination['status']}"
    )
    assert determination["reversed_cents"] == 100_000, (
        f"Expected 100000 reversed_cents, got {determination['reversed_cents']}"
    )

    resp = api.create_appeal(
        {
            "deobligation_id": deobligation_id,
            "grounds": "Escalating a granted appeal",
            "relief_requested_cents": 100_000,
            "prior_appeal_id": granted["id"],
        },
        make_applicant_agent_headers(applicant_id),
    )
    validate_error(resp, ApiErrorId.ERR_SECOND_APPEAL_REQUIRES_FIRST_DENIED)

    rows, meta = validate_paginated(api.list_appeals(ADMIN))
    on_determination = [row for row in rows if row["deobligation_id"] == deobligation_id]
    assert len(on_determination) == 1, (
        f"Expected exactly 1 appeal on the determination, got {len(on_determination)}"
    )


# ---------------------------------------------------------------------------
# Relief bounds at filing and at a partial grant
# ---------------------------------------------------------------------------
def test_relief_requested_above_determination_amount_is_rejected(api):
    """PRD §3.9: "An applicant that disagrees files an appeal, supplying the
    `deobligation_id` under challenge, a non-empty `grounds` narrative, a
    `relief_requested_cents` of at least 1 that may not exceed the determination's
    `amount_cents` (`ERR_RELIEF_EXCEEDS_DEOBLIGATION`), and optionally a
    `prior_appeal_id`."

    Design: Corner/validations/relief_bounds_at_filing_and_at_partial_grant_rejected
    """
    scenario = setup_finalized_deobligation(
        500_000,
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4980"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    deobligation_id = scenario["deobligation"]["id"]
    agent = make_applicant_agent_headers(scenario["applicant"]["id"])

    resp = api.create_appeal(
        {
            "deobligation_id": deobligation_id,
            "grounds": "Asking for more than was withdrawn",
            "relief_requested_cents": 500_001,
        },
        agent,
    )
    validate_error(resp, ApiErrorId.ERR_RELIEF_EXCEEDS_DEOBLIGATION)

    rows, meta = validate_paginated(api.list_appeals(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected no Appeal row after the rejected filing, got {meta['total_count']}"
    )

    data = validate_success(
        api.create_appeal(
            {
                "deobligation_id": deobligation_id,
                "grounds": "Part of the reduced scope was eligible",
                "relief_requested_cents": 400_000,
            },
            agent,
        ),
        201,
    )
    assert data["status"] == "SUBMITTED", f"Expected SUBMITTED, got {data['status']}"


def test_partial_grant_outside_the_open_relief_interval_is_rejected(api):
    """PRD §3.9: "**`SUBMITTED → PARTIALLY_GRANTED`** requires a supplied
    `relief_granted_cents` strictly greater than 0 and strictly less than
    `relief_requested_cents`; a value outside that open interval is rejected with
    `ERR_RELIEF_EXCEEDS_DEOBLIGATION`."

    PRD §3.9: "Because `reversed_cents` moved, the project's `deobligated_cents`
    falls by `relief_granted_cents`, which puts the money back on the obligation
    ledger; because `deobligated_cents` moved, the applicant's
    `total_obligated_cents` and `available_drawdown_cents` are recomputed and the
    declaration's `total_obligated_cents` follows."

    Design: Corner/validations/relief_bounds_at_filing_and_at_partial_grant_rejected
    """
    scenario = setup_appeal_under_review(
        500_000,
        relief_requested_cents=400_000,
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4980"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    appeal_id = scenario["appeal"]["id"]

    # The upper end of the interval is open: the full request is not a partial.
    resp = api.decide_appeal(
        appeal_id,
        {
            "decision": "PARTIALLY_GRANT",
            "decision_rationale": "Granting the full request as a partial",
            "relief_granted_cents": 400_000,
        },
        ADJUDICATOR,
    )
    validate_error(resp, ApiErrorId.ERR_RELIEF_EXCEEDS_DEOBLIGATION)
    still = validate_success(api.get_appeal(appeal_id, ADMIN))
    assert still["status"] == "SUBMITTED", (
        f"Expected the appeal to stay SUBMITTED, got {still['status']}"
    )

    # The lower end is open too: granting nothing is not a partial grant.
    resp = api.decide_appeal(
        appeal_id,
        {
            "decision": "PARTIALLY_GRANT",
            "decision_rationale": "Granting nothing as a partial",
            "relief_granted_cents": 0,
        },
        ADJUDICATOR,
    )
    validate_error(resp, ApiErrorId.ERR_RELIEF_EXCEEDS_DEOBLIGATION)

    # A value strictly inside the interval is accepted.
    data = validate_success(
        api.decide_appeal(
            appeal_id,
            {
                "decision": "PARTIALLY_GRANT",
                "decision_rationale": "Partial relief for the documented portion",
                "relief_granted_cents": 150_000,
            },
            ADJUDICATOR,
        )
    )
    assert data["status"] == "PARTIALLY_GRANTED", (
        f"Expected PARTIALLY_GRANTED, got {data['status']}"
    )
    assert data["relief_granted_cents"] == 150_000, (
        f"Expected 150000 relief_granted_cents, got {data['relief_granted_cents']}"
    )

    determination = get_deobligation(scenario["deobligation"]["id"])
    assert determination["reversed_cents"] == 150_000, (
        f"Expected 150000 reversed_cents, got {determination['reversed_cents']}"
    )
    assert determination["status"] == "FINAL", (
        f"Expected the determination to stay FINAL on a partial reversal, got {determination['status']}"
    )
    project = get_project(scenario["project"]["id"])
    assert project["deobligated_cents"] == 350_000, (
        f"Expected 350000 deobligated_cents, got {project['deobligated_cents']}"
    )
    applicant = get_applicant(scenario["applicant"]["id"])
    assert applicant["total_obligated_cents"] == 1_150_000, (
        f"Expected 1150000 total_obligated_cents, got {applicant['total_obligated_cents']}"
    )


# ---------------------------------------------------------------------------
# Determination amount bounded by the remaining obligation
# ---------------------------------------------------------------------------
def test_deobligation_above_remaining_obligation_is_rejected(api):
    """PRD §3.9: "The amount is bounded by what is actually still reducible: it
    may not exceed `federal_share_obligated_cents` less `deobligated_cents` less
    `pending_deobligation_cents`, so two proposed determinations cannot between
    them exceed the obligation, and a breach yields
    `ERR_DEOBLIGATION_EXCEEDS_OBLIGATION`."

    PRD §3.9: "A new determination sits in `PROPOSED` with
    `determined_by_user_id` recording the acting user, `finalized_at` null,
    `appeal_deadline_at` null and `reversed_cents` 0."

    PRD §3.8: "After **every** recomputation, `drawdown_status` is set to
    `SUSPENDED` whenever `delinquent_report_count` is greater than 0 or
    `pending_deobligation_cents` is greater than 0, and to `ACTIVE` whenever both
    are exactly 0."

    Design: Corner/validations/deobligation_above_remaining_obligation_rejected
    """
    scenario = setup_obligated_project(
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4981"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]
    project_version = scenario["project"]["version"]

    assert scenario["project"]["federal_share_obligated_cents"] == 1_500_000, (
        "Expected 1500000 federal_share_obligated_cents, got "
        f"{scenario['project']['federal_share_obligated_cents']}"
    )

    # One cent above the whole obligation is refused.
    resp = api.create_deobligation(
        deobligation_payload(project_id, 1_500_001, project_version, "SCOPE_REDUCTION"),
        OFFICER_TWO,
    )
    validate_error(resp, ApiErrorId.ERR_DEOBLIGATION_EXCEEDS_OBLIGATION)
    rows, meta = validate_paginated(api.list_deobligations(ADMIN))
    assert meta["total_count"] == 0, (
        f"Expected no Deobligation row after the rejected create, got {meta['total_count']}"
    )

    # Exactly the whole obligation is inside the bound.
    data = validate_success(
        api.create_deobligation(
            deobligation_payload(project_id, 1_500_000, project_version, "SCOPE_REDUCTION"),
            OFFICER_TWO,
        ),
        201,
    )
    assert data["status"] == "PROPOSED", f"Expected PROPOSED, got {data['status']}"
    assert data["determined_by_user_id"] == SECOND_GRANTS_OFFICER_USER_ID, (
        f"Expected determined_by_user_id {SECOND_GRANTS_OFFICER_USER_ID}, got "
        f"{data['determined_by_user_id']}"
    )

    project = get_project(project_id)
    assert project["pending_deobligation_cents"] == 1_500_000, (
        f"Expected 1500000 pending_deobligation_cents, got {project['pending_deobligation_cents']}"
    )
    assert project["deobligated_cents"] == 0, (
        f"Expected 0 deobligated_cents while the determination is only PROPOSED, got {project['deobligated_cents']}"
    )
    applicant = get_applicant(applicant_id)
    assert applicant["drawdown_status"] == "SUSPENDED", (
        f"Expected SUSPENDED with a pending determination, got {applicant['drawdown_status']}"
    )
    assert applicant["total_obligated_cents"] == 1_500_000, (
        f"Expected 1500000 total_obligated_cents, got {applicant['total_obligated_cents']}"
    )

    # The PROPOSED determination already reserves the whole obligation, so the
    # headroom is 1500000 - 0 - 1500000 == 0 and a single further cent is refused.
    resp = api.create_deobligation(
        deobligation_payload(project_id, 1, project["version"], "DISALLOWED_COST"),
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_DEOBLIGATION_EXCEEDS_OBLIGATION)

    rows, meta = validate_paginated(api.list_deobligations(ADMIN))
    assert meta["total_count"] == 1, (
        f"Expected exactly 1 Deobligation row, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# Refund bounded by the drawdown's own approved amount
# ---------------------------------------------------------------------------
def test_refund_above_disbursed_amount_is_rejected(api):
    """PRD §3.8: "It carries a single `refund_cents` amount, which may not exceed
    the drawdown's `approved_cents` (`ERR_REFUND_EXCEEDS_DRAWDOWN`), and it is
    admissible only on a drawdown in `PAID`; a refund attempted against a
    `REQUESTED`, `REJECTED` or already-`REFUNDED` row yields
    `ERR_DRAWDOWN_INVALID_STATE`."

    PRD §2.9: "A paid drawdown of some amount followed by a full refund of that
    amount must leave `cash_on_hand_cents`, `available_drawdown_cents` and the
    declaration's `total_drawn_cents` exactly where they started, while
    `total_drawn_cents` and `total_refunded_cents` each rise by that amount."

    Design: Corner/validations/refund_above_disbursed_amount_rejected
    """
    scenario = setup_paid_drawdown(
        500_000,
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4982"},
        project_overrides={"estimated_repair_cost_cents": 2_000_000},
    )
    drawdown_id = scenario["drawdown"]["id"]
    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)

    # One cent above the disbursement is refused, even though the applicant still
    # has a larger obligation behind it.
    resp = api.refund_drawdown(drawdown_id, {"refund_cents": 500_001}, agent)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_DRAWDOWN)
    still = validate_success(api.get_drawdown(drawdown_id, ADMIN))
    assert still["status"] == "PAID", (
        f"Expected the drawdown to stay PAID, got {still['status']}"
    )
    assert still["refunded_cents"] == 0, (
        f"Expected 0 refunded_cents after the rejected refund, got {still['refunded_cents']}"
    )

    # A full refund is accepted and returns the cash ledger to where it started.
    data = validate_success(
        api.refund_drawdown(drawdown_id, {"refund_cents": 500_000}, agent)
    )
    assert data["status"] == "REFUNDED", f"Expected REFUNDED, got {data['status']}"
    assert data["refunded_cents"] == 500_000, (
        f"Expected 500000 refunded_cents, got {data['refunded_cents']}"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_drawn_cents"] == 500_000, (
        f"Expected 500000 total_drawn_cents, got {applicant['total_drawn_cents']}"
    )
    assert applicant["total_refunded_cents"] == 500_000, (
        f"Expected 500000 total_refunded_cents, got {applicant['total_refunded_cents']}"
    )
    assert applicant["cash_on_hand_cents"] == 0, (
        f"Expected 0 cash_on_hand_cents, got {applicant['cash_on_hand_cents']}"
    )
    assert applicant["available_drawdown_cents"] == 1_500_000, (
        "Expected available_drawdown_cents back at the full 1500000 obligation, got "
        f"{applicant['available_drawdown_cents']}"
    )
    disaster = get_disaster(scenario["disaster"]["id"])
    assert disaster["total_drawn_cents"] == 0, (
        f"Expected 0 total_drawn_cents on the declaration, got {disaster['total_drawn_cents']}"
    )


# ---------------------------------------------------------------------------
# Every gate satisfied: the full submit / review / obligate chain passes
# ---------------------------------------------------------------------------
def test_every_submit_gate_satisfied_project_reaches_obligation(api):
    """PRD §3.3: "Submission also derives `work_type` from the category once and
    for all: categories `A` and `B` are `EMERGENCY` work, and categories `C`, `D`,
    `E`, `F` and `G` are `PERMANENT` work."

    PRD §3.7: "The system totals the `eligible_cents` of every cost line item on
    the project whose `review_status` is `ALLOWED` or `PARTIALLY_ALLOWED`, and
    `repair_eligible_cents` becomes that total."

    PRD §3.7: "Finally `size_class` is re-derived: `SMALL` when
    `repair_eligible_cents` is strictly below the declaration's
    `small_project_threshold_cents`, and `LARGE` when it is at or above it."

    PRD §3.7: "Then the repair share is that net repair figure multiplied by the
    declaration's `federal_cost_share_pct` and rounded half up to whole cents,
    **and separately** the mitigation share is `mitigation_approved_cents`
    multiplied by the same `federal_cost_share_pct` and rounded half up to whole
    cents."

    PRD §3.7: "Because `total_obligated_cents` moved, the single-audit test runs:
    when it now stands at or above 75,000,000 cents — seven hundred fifty thousand
    dollars of federal award — and the applicant's `monitoring_status` is still
    `STANDARD`, `audit_requirement` becomes `SINGLE_AUDIT` and `monitoring_status`
    escalates `MONITORING:STANDARD → MONITORING:ENHANCED`."

    Design: Corner/validations/every_submit_gate_satisfied_project_reaches_obligation
    """
    scenario = setup_drafted_project(
        clock="2026-07-01T00:00:00Z",
        disaster_overrides={"declaration_number": "DR-4983"},
        project_overrides={
            "category": "C",
            "title": "Pump house repair",
            "scope_of_work": "Replace the pump house roof deck",
            "estimated_repair_cost_cents": 1_000_000,
        },
    )
    project_id = scenario["project"]["id"]
    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)

    submitted = validate_success(api.submit_project(project_id, agent))
    assert submitted["status"] == "UNDER_REVIEW", (
        f"Expected UNDER_REVIEW, got {submitted['status']}"
    )
    assert submitted["work_type"] == "PERMANENT", (
        f"Expected PERMANENT for category C, got {submitted['work_type']}"
    )

    line = validate_success(
        api.create_cost_line_item(
            cost_line_item_payload(
                project_id,
                cost_type="MATERIALS",
                claimed_cents=1_000_000,
                work_start_at="2026-06-12T08:00:00Z",
                work_end_at="2026-06-12T17:00:00Z",
            ),
            agent,
        ),
        201,
    )
    reviewed_line = validate_success(api.review_cost_line_item(line["id"], SPECIALIST))
    assert reviewed_line["eligible_cents"] == 1_000_000, (
        f"Expected 1000000 eligible_cents, got {reviewed_line['eligible_cents']}"
    )
    assert reviewed_line["review_status"] == "ALLOWED", (
        f"Expected ALLOWED, got {reviewed_line['review_status']}"
    )

    validated = validate_success(
        api.cost_review(project_id, {"decision": "VALIDATE"}, SPECIALIST)
    )
    assert validated["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {validated['status']}"
    )
    assert validated["repair_eligible_cents"] == 1_000_000, (
        f"Expected 1000000 repair_eligible_cents, got {validated['repair_eligible_cents']}"
    )
    assert validated["size_class"] == "SMALL", (
        f"Expected SMALL, got {validated['size_class']}"
    )
    assert validated["insurance_reduction_cents"] == 0, (
        f"Expected 0 insurance_reduction_cents, got {validated['insurance_reduction_cents']}"
    )

    obligated = validate_success(api.obligate_project(project_id, OFFICER_ONE))
    assert obligated["status"] == "OBLIGATED", (
        f"Expected OBLIGATED, got {obligated['status']}"
    )
    assert obligated["federal_share_obligated_cents"] == 750_000, (
        "Expected 750000 federal_share_obligated_cents, got "
        f"{obligated['federal_share_obligated_cents']}"
    )

    applicant = get_applicant(applicant_id)
    assert applicant["total_obligated_cents"] == 750_000, (
        f"Expected 750000 total_obligated_cents, got {applicant['total_obligated_cents']}"
    )
    assert applicant["drawdown_status"] == "ACTIVE", (
        f"Expected ACTIVE, got {applicant['drawdown_status']}"
    )
    assert applicant["audit_requirement"] == "NONE", (
        f"Expected NONE below the single-audit threshold, got {applicant['audit_requirement']}"
    )
    assert applicant["monitoring_status"] == "STANDARD", (
        f"Expected STANDARD below the single-audit threshold, got {applicant['monitoring_status']}"
    )
    disaster = get_disaster(scenario["disaster"]["id"])
    assert disaster["total_obligated_cents"] == 750_000, (
        f"Expected 750000 total_obligated_cents on the declaration, got {disaster['total_obligated_cents']}"
    )
    assert disaster["status"] == "DECLARED", (
        f"Expected DECLARED, got {disaster['status']}"
    )
