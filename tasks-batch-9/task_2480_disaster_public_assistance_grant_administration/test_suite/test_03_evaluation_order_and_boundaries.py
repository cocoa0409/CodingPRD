"""Which error wins when two guards fail at once, and what happens exactly at a
threshold, on an empty collection, and at the last available cent."""
from test_helpers import (
    SPECIALIST_USER_ID,
    ApiErrorId,
    cost_line_item_payload,
    create_applicant,
    create_contract,
    create_cost_line_item,
    create_disaster,
    create_facility,
    create_project,
    drawdown_payload,
    get_applicant,
    get_project,
    make_applicant_agent_headers,
    make_specialist_headers,
    review_cost_line_item,
    review_procurement,
    screen_facility,
    set_clock,
    setup_obligated_project,
    setup_submitted_project,
    setup_validated_project,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# Shared declaration bodies. Each test declares its own disaster so that no
# test depends on another having run.
# --------------------------------------------------------------------------
DR_4911 = {
    "declaration_number": "DR-4911",
    "state_code": "TX",
    "incident_type": "FLOOD",
    "incident_start_at": "2026-06-10T00:00:00Z",
    "incident_end_at": "2026-06-25T00:00:00Z",
    "population": 900_000,
    "federal_cost_share_pct": 0.75,
    "small_project_threshold_cents": 4_000_000,
}

DR_4912 = {
    "declaration_number": "DR-4912",
    "state_code": "TX",
    "incident_type": "FLOOD",
    "incident_start_at": "2026-06-10T00:00:00Z",
    "incident_end_at": "2026-06-25T00:00:00Z",
    "population": 900_000,
    "federal_cost_share_pct": 0.75,
    "small_project_threshold_cents": 4_000_000,
}

DR_4914 = {
    "declaration_number": "DR-4914",
    "state_code": "TX",
    "incident_type": "FLOOD",
    "incident_start_at": "2026-06-10T00:00:00Z",
    "incident_end_at": "2026-06-25T00:00:00Z",
    "population": 900_000,
    "federal_cost_share_pct": 0.75,
    "small_project_threshold_cents": 4_000_000,
}

DR_4915 = {
    "declaration_number": "DR-4915",
    "state_code": "TX",
    "incident_type": "FLOOD",
    "incident_start_at": "2026-06-10T00:00:00Z",
    "incident_end_at": "2026-06-25T00:00:00Z",
    "population": 900_000,
    "federal_cost_share_pct": 0.75,
    "small_project_threshold_cents": 4_000_000,
}

DR_4916 = {
    "declaration_number": "DR-4916",
    "state_code": "TX",
    "incident_type": "FLOOD",
    "incident_start_at": "2026-06-10T00:00:00Z",
    "incident_end_at": "2026-06-25T00:00:00Z",
    "population": 900_000,
    "federal_cost_share_pct": 0.75,
    "small_project_threshold_cents": 4_000_000,
}

NONCOMPETITIVE_UNJUSTIFIED_CONTRACT = {
    "vendor_name": "Gulf Marine Constructors",
    "contract_type": "NONCOMPETITIVE",
    "award_amount_cents": 30_000_000,
    "awarded_at": "2026-06-15T00:00:00Z",
    "bids_received": 1,
    "advertised": False,
    "sole_source_justification_on_file": False,
    "debarment_check_completed": True,
}


# ==========================================================================
# Drawdown creation: the project-state guard versus the cash-availability
# guard.
# ==========================================================================
def test_drawdown_state_guard_pre_empts_availability_guard(api):
    """PRD §2.7: "Checks are therefore evaluated in the following fixed order, and the
    **first** failing rung decides the response."

    PRD §2.7: "A later rung never masks an earlier one, and an earlier rung never runs
    after a later one has already passed."

    PRD §2.7: "State admissibility of the target row, and — for drawdown creation and
    deobligation creation — of the referenced project: `ERR_PROJECT_INVALID_STATE`,
    `ERR_DISASTER_INVALID_STATE`, `ERR_DAMAGE_SITE_ALREADY_ADJUDICATED`,
    `ERR_CONTRACT_ALREADY_REVIEWED`, `ERR_COST_LINE_ITEM_LOCKED`,
    `ERR_FACILITY_AMENDMENT_LOCKED`, `ERR_DRAWDOWN_INVALID_STATE`,
    `ERR_DEOBLIGATION_NOT_FINAL`, `ERR_APPEAL_ALREADY_DECIDED` or
    `ERR_REPORT_ALREADY_SUBMITTED` (all 409)."

    PRD §2.7: "Drawdown availability — `ERR_DRAWDOWN_EXCEEDS_AVAILABLE` (402)."

    PRD §3.8: "The applicant must be `ELIGIBLE` (`ERR_APPLICANT_NOT_ELIGIBLE`); the
    referenced project must be `OBLIGATED` (`ERR_PROJECT_INVALID_STATE`); the project
    must belong to the same applicant as the drawdown
    (`ERR_CROSS_APPLICANT_REFERENCE`); the applicant's `drawdown_status` must be
    `ACTIVE` (`ERR_DRAWDOWN_SUSPENDED`); and `requested_cents` must not exceed
    `available_drawdown_cents`, where equality is expressly allowed — drawing the last
    available cent is legitimate — with an excess rejected as
    `ERR_DRAWDOWN_EXCEEDS_AVAILABLE` and the payment-required status 402."

    Design: Difficulty/priority_pair_validation_conflict/drawdown_state_priority_beats_fiscal_priority
    """
    scenario = setup_validated_project(
        disaster_overrides=DR_4911,
        project_overrides={
            "estimated_repair_cost_cents": 5_000_000,
            "mitigation_requested_cents": 0,
        },
    )
    project = scenario["project"]
    assert project["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {project['status']} — the project must not be obligated"
    )
    assert project["federal_share_obligated_cents"] == 0, (
        f"Expected 0, got {project['federal_share_obligated_cents']} before obligation"
    )

    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)
    applicant = get_applicant(applicant_id)
    assert applicant["available_drawdown_cents"] == 0, (
        f"Expected 0, got {applicant['available_drawdown_cents']} with nothing obligated"
    )

    # 1000000 exceeds the available 0 AND the project is not OBLIGATED.
    response = api.create_drawdown(
        drawdown_payload(applicant_id, project["id"], 1_000_000, applicant["version"]),
        agent,
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_INVALID_STATE)

    _, meta = validate_paginated(api.list_drawdowns(agent))
    assert meta["total_count"] == 0, (
        f"Expected 0 drawdown rows, got {meta['total_count']} after a rejected request"
    )

    after = get_applicant(applicant_id)
    assert after["available_drawdown_cents"] == 0, (
        f"Expected 0, got {after['available_drawdown_cents']} after the rejected request"
    )
    assert after["total_drawn_cents"] == 0, (
        f"Expected 0, got {after['total_drawn_cents']} after the rejected request"
    )


def test_drawdown_availability_guard_fires_alone_on_an_obligated_project(api):
    """PRD §3.8: "The applicant must be `ELIGIBLE` (`ERR_APPLICANT_NOT_ELIGIBLE`); the
    referenced project must be `OBLIGATED` (`ERR_PROJECT_INVALID_STATE`); the project
    must belong to the same applicant as the drawdown
    (`ERR_CROSS_APPLICANT_REFERENCE`); the applicant's `drawdown_status` must be
    `ACTIVE` (`ERR_DRAWDOWN_SUSPENDED`); and `requested_cents` must not exceed
    `available_drawdown_cents`, where equality is expressly allowed — drawing the last
    available cent is legitimate — with an excess rejected as
    `ERR_DRAWDOWN_EXCEEDS_AVAILABLE` and the payment-required status 402."

    PRD §2.7: "Drawdown availability — `ERR_DRAWDOWN_EXCEEDS_AVAILABLE` (402)."

    Design: Difficulty/priority_pair_validation_conflict/drawdown_state_priority_beats_fiscal_priority
    """
    scenario = setup_obligated_project(
        disaster_overrides=DR_4911,
        project_overrides={
            "estimated_repair_cost_cents": 5_000_000,
            "mitigation_requested_cents": 0,
        },
    )
    project = scenario["project"]
    assert project["status"] == "OBLIGATED", (
        f"Expected OBLIGATED, got {project['status']} — the state guard must pass here"
    )

    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)
    applicant = get_applicant(applicant_id)
    available = applicant["available_drawdown_cents"]
    assert available > 0, f"Expected positive availability, got {available} after obligation"

    response = api.create_drawdown(
        drawdown_payload(applicant_id, project["id"], available + 1, applicant["version"]),
        agent,
    )
    validate_error(response, ApiErrorId.ERR_DRAWDOWN_EXCEEDS_AVAILABLE)


# ==========================================================================
# Cost line item creation: the incident-period guard versus the procurement
# guard.
# ==========================================================================
def test_cost_line_item_incident_period_guard_pre_empts_procurement_guard(api):
    """PRD §2.7: "Checks are therefore evaluated in the following fixed order, and the
    **first** failing rung decides the response."

    PRD §2.7: "A later rung never masks an earlier one, and an earlier rung never runs
    after a later one has already passed."

    PRD §2.7: "Incident-period containment of `damage_observed_at` on damage site
    collection, and of the whole charged interval on cost line item creation —
    `ERR_OUTSIDE_INCIDENT_PERIOD` (422)."

    PRD §2.7: "Contract compliance at cost line item creation —
    `ERR_PROCUREMENT_NONCOMPLIANT` (409)."

    PRD §3.4: "The entire charged interval must lie inside the declaration's inclusive
    incident period — both endpoints included — and any part of it falling outside
    yields `ERR_OUTSIDE_INCIDENT_PERIOD`."

    PRD §3.4: "A contracted claim against a `NONCOMPLIANT` contract fails with
    `ERR_PROCUREMENT_NONCOMPLIANT`."

    PRD §3.4: "A `NONCOMPETITIVE` award whose `sole_source_justification_on_file` is
    false is `NONCOMPLIANT` with reason `SOLE_SOURCE_UNJUSTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/cost_line_item_temporal_priority_beats_safety_priority
    """
    scenario = setup_submitted_project(
        clock="2026-07-10T00:00:00Z",
        disaster_overrides=DR_4912,
        project_overrides={
            "estimated_repair_cost_cents": 40_000_000,
            "mitigation_requested_cents": 0,
        },
    )
    applicant_id = scenario["applicant"]["id"]
    project = scenario["project"]
    assert project["status"] == "UNDER_REVIEW", (
        f"Expected UNDER_REVIEW, got {project['status']} — the project must stay open to costs"
    )

    contract = create_contract(applicant_id, **NONCOMPETITIVE_UNJUSTIFIED_CONTRACT)
    contract = review_procurement(contract["id"])
    assert contract["procurement_status"] == "NONCOMPLIANT", (
        f"Expected NONCOMPLIANT, got {contract['procurement_status']} after procurement review"
    )
    assert contract["noncompliance_reason"] == "SOLE_SOURCE_UNJUSTIFIED", (
        f"Expected SOLE_SOURCE_UNJUSTIFIED, got {contract['noncompliance_reason']}"
    )

    agent = make_applicant_agent_headers(applicant_id)
    # The charged interval sits wholly after 2026-06-25T00:00:00Z AND the contract is
    # NONCOMPLIANT.
    response = api.create_cost_line_item(
        cost_line_item_payload(
            project["id"],
            cost_type="CONTRACT",
            contract_id=contract["id"],
            claimed_cents=1_000_000,
            work_start_at="2026-07-05T08:00:00Z",
            work_end_at="2026-07-05T17:00:00Z",
        ),
        agent,
    )
    validate_error(response, ApiErrorId.ERR_OUTSIDE_INCIDENT_PERIOD)

    _, meta = validate_paginated(api.list_cost_line_items(agent))
    assert meta["total_count"] == 0, (
        f"Expected 0 cost line item rows, got {meta['total_count']} after a rejected claim"
    )


def test_cost_line_item_procurement_guard_fires_alone_inside_the_incident_period(api):
    """PRD §3.4: "A contracted claim against a `NONCOMPLIANT` contract fails with
    `ERR_PROCUREMENT_NONCOMPLIANT`."

    PRD §2.7: "Contract compliance at cost line item creation —
    `ERR_PROCUREMENT_NONCOMPLIANT` (409)."

    Design: Difficulty/priority_pair_validation_conflict/cost_line_item_temporal_priority_beats_safety_priority
    """
    scenario = setup_submitted_project(
        clock="2026-07-10T00:00:00Z",
        disaster_overrides=DR_4912,
        project_overrides={
            "estimated_repair_cost_cents": 40_000_000,
            "mitigation_requested_cents": 0,
        },
    )
    applicant_id = scenario["applicant"]["id"]
    contract = create_contract(applicant_id, **NONCOMPETITIVE_UNJUSTIFIED_CONTRACT)
    contract = review_procurement(contract["id"])
    assert contract["procurement_status"] == "NONCOMPLIANT", (
        f"Expected NONCOMPLIANT, got {contract['procurement_status']} after procurement review"
    )

    agent = make_applicant_agent_headers(applicant_id)
    # Same claim, but the charged interval now lies inside 2026-06-10 .. 2026-06-25,
    # so only the procurement guard can fire.
    response = api.create_cost_line_item(
        cost_line_item_payload(
            scenario["project"]["id"],
            cost_type="CONTRACT",
            contract_id=contract["id"],
            claimed_cents=1_000_000,
            work_start_at="2026-06-12T08:00:00Z",
            work_end_at="2026-06-12T17:00:00Z",
        ),
        agent,
    )
    validate_error(response, ApiErrorId.ERR_PROCUREMENT_NONCOMPLIANT)


# ==========================================================================
# Project submission: the facility guard versus the applicant guard.
# ==========================================================================
def _register_unscreened_fire_district():
    """DR-4913 with a never-determined applicant and a never-screened facility."""
    set_clock("2026-07-01T00:00:00Z")
    disaster = create_disaster(
        declaration_number="DR-4913",
        state_code="TX",
        incident_type="WILDFIRE",
        incident_start_at="2026-06-10T00:00:00Z",
        incident_end_at="2026-06-25T00:00:00Z",
        population=900_000,
        federal_cost_share_pct=0.75,
        small_project_threshold_cents=4_000_000,
    )
    applicant = create_applicant(
        disaster["id"],
        name="Pine Ridge Fire District",
        applicant_type="LOCAL_GOVERNMENT",
        population_served=22_000,
    )
    facility = create_facility(
        applicant["id"],
        name="Station 4",
        facility_type="BUILDING_EQUIPMENT",
        ownership="PUBLIC",
        flood_zone=False,
    )
    return disaster, applicant, facility


def _formulate_station_4_project(applicant_id, facility_id):
    return create_project(
        applicant_id,
        facility_id,
        category="E",
        title="Station 4 roof and bay doors",
        scope_of_work="Replace roof deck and two apparatus bay doors",
        estimated_repair_cost_cents=2_500_000,
        mitigation_requested_cents=0,
    )


def test_project_submit_facility_guard_pre_empts_applicant_guard(api):
    """PRD §2.7: "Checks are therefore evaluated in the following fixed order, and the
    **first** failing rung decides the response."

    PRD §2.7: "A later rung never masks an earlier one, and an earlier rung never runs
    after a later one has already passed."

    PRD §2.7: "Facility eligibility on project submission and on cost review —
    `ERR_FACILITY_INELIGIBLE` (409)."

    PRD §2.7: "Applicant eligibility on project submission, cost line item creation and
    drawdown creation — `ERR_APPLICANT_NOT_ELIGIBLE` (409)."

    PRD §3.3: "The acting agent must own the project, the project must actually be in
    `DRAFT`, the owning applicant's `eligibility_status` must be `ELIGIBLE` (otherwise
    `ERR_APPLICANT_NOT_ELIGIBLE`), the repaired facility's `eligibility_status` must be
    `ELIGIBLE` (otherwise `ERR_FACILITY_INELIGIBLE`), and the declaration must still be
    `DECLARED` (otherwise `ERR_DISASTER_NOT_OPEN`)."

    PRD §3.3: "The project is created in `DRAFT` with `size_class` null,
    `rfi_round_count` 0, `last_rfi_question` null, `work_type` not yet derived, and
    every basis and ledger field at its opening value: `repair_eligible_cents`,
    `anticipated_insurance_cents`, `settlement_allocated_cents`,
    `insurance_reduction_cents`, `mitigation_approved_cents`,
    `eligible_cost_provisional_cents`, `federal_share_obligated_cents`,
    `deobligated_cents` and `pending_deobligation_cents` at 0, and
    `eligible_cost_final_cents`, `federal_share_final_cents`,
    `closeout_variance_cents`, `cost_reviewed_by_user_id`, `obligated_by_user_id` and
    `denial_reason` all null."

    Design: Difficulty/priority_pair_validation_conflict/project_submit_safety_priority_beats_referential_priority
    """
    _disaster, applicant, facility = _register_unscreened_fire_district()
    assert applicant["eligibility_status"] == "PENDING", (
        f"Expected PENDING, got {applicant['eligibility_status']} — never determined"
    )
    assert facility["eligibility_status"] == "PENDING", (
        f"Expected PENDING, got {facility['eligibility_status']} — never screened"
    )

    project = _formulate_station_4_project(applicant["id"], facility["id"])

    response = api.submit_project(project["id"], make_applicant_agent_headers(applicant["id"]))
    validate_error(response, ApiErrorId.ERR_FACILITY_INELIGIBLE)

    after = get_project(project["id"])
    assert after["status"] == "DRAFT", (
        f"Expected DRAFT, got {after['status']} after a rejected submission"
    )
    assert after["size_class"] is None, (
        f"Expected None, got {after['size_class']} after a rejected submission"
    )
    assert after["eligible_cost_provisional_cents"] == 0, (
        f"Expected 0, got {after['eligible_cost_provisional_cents']} after a rejected submission"
    )


def test_project_submit_applicant_guard_fires_alone_when_the_facility_is_eligible(api):
    """PRD §3.3: "The acting agent must own the project, the project must actually be in
    `DRAFT`, the owning applicant's `eligibility_status` must be `ELIGIBLE` (otherwise
    `ERR_APPLICANT_NOT_ELIGIBLE`), the repaired facility's `eligibility_status` must be
    `ELIGIBLE` (otherwise `ERR_FACILITY_INELIGIBLE`), and the declaration must still be
    `DECLARED` (otherwise `ERR_DISASTER_NOT_OPEN`)."

    PRD §2.7: "Applicant eligibility on project submission, cost line item creation and
    drawdown creation — `ERR_APPLICANT_NOT_ELIGIBLE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/project_submit_safety_priority_beats_referential_priority
    """
    _disaster, applicant, facility = _register_unscreened_fire_district()
    facility = screen_facility(facility["id"])
    assert facility["eligibility_status"] == "ELIGIBLE", (
        f"Expected ELIGIBLE, got {facility['eligibility_status']} after screening"
    )
    assert get_applicant(applicant["id"])["eligibility_status"] == "PENDING", (
        "Screening a facility must not determine the applicant"
    )

    project = _formulate_station_4_project(applicant["id"], facility["id"])

    response = api.submit_project(project["id"], make_applicant_agent_headers(applicant["id"]))
    validate_error(response, ApiErrorId.ERR_APPLICANT_NOT_ELIGIBLE)

    after = get_project(project["id"])
    assert after["status"] == "DRAFT", (
        f"Expected DRAFT, got {after['status']} after a rejected submission"
    )


# ==========================================================================
# Cost review: the small/large threshold at exactly the boundary.
# ==========================================================================
def _validate_project_on_one_materials_line(estimated_cents, claimed_cents, api):
    """Submit a project, document exactly one MATERIALS line, then cost-review it."""
    scenario = setup_submitted_project(
        disaster_overrides=DR_4914,
        project_overrides={
            "estimated_repair_cost_cents": estimated_cents,
            "mitigation_requested_cents": 900_000,
        },
    )
    line = create_cost_line_item(
        scenario["project"]["id"],
        scenario["applicant"]["id"],
        cost_type="MATERIALS",
        claimed_cents=claimed_cents,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T17:00:00Z",
    )
    review_cost_line_item(line["id"])
    return validate_success(
        api.cost_review(
            scenario["project"]["id"],
            {"decision": "VALIDATE"},
            make_specialist_headers(SPECIALIST_USER_ID),
        )
    )


def test_repair_basis_exactly_at_small_project_threshold_is_large(api):
    """PRD §3.7: "Finally `size_class` is re-derived: `SMALL` when
    `repair_eligible_cents` is strictly below the declaration's
    `small_project_threshold_cents`, and `LARGE` when it is at or above it."

    PRD §3.7: "The order is: take `repair_eligible_cents` as step one fixed it; classify
    `size_class` from that repair basis **with mitigation excluded**; read the cap
    percentage from the class, which is 20 percent for `SMALL` and 15 percent for
    `LARGE`; and set `mitigation_approved_cents` to the lesser of the project's
    `mitigation_requested_cents` and the repair basis multiplied by the cap percentage,
    truncated downward to whole cents."

    PRD §3.7: "The system totals the `eligible_cents` of every cost line item on the
    project whose `review_status` is `ALLOWED` or `PARTIALLY_ALLOWED`, and
    `repair_eligible_cents` becomes that total."

    Design: Difficulty/boundary_precision_check/repair_basis_exactly_at_small_project_threshold_is_large
    """
    project = _validate_project_on_one_materials_line(4_000_000, 4_000_000, api)

    assert project["repair_eligible_cents"] == 4_000_000, (
        f"Expected 4000000, got {project['repair_eligible_cents']} as the reviewed repair basis"
    )
    assert project["size_class"] == "LARGE", (
        f"Expected LARGE, got {project['size_class']} at a basis exactly equal to the threshold"
    )
    assert project["mitigation_approved_cents"] == 600_000, (
        f"Expected 600000, got {project['mitigation_approved_cents']} under the LARGE cap"
    )
    assert project["mitigation_approved_cents"] != 800_000, (
        "The SMALL cap must not apply at exact equality with the threshold"
    )
    assert project["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {project['status']} after cost review"
    )


def test_repair_basis_one_cent_below_small_project_threshold_is_small(api):
    """PRD §3.7: "Finally `size_class` is re-derived: `SMALL` when
    `repair_eligible_cents` is strictly below the declaration's
    `small_project_threshold_cents`, and `LARGE` when it is at or above it."

    Design: Difficulty/boundary_precision_check/repair_basis_exactly_at_small_project_threshold_is_large
    """
    project = _validate_project_on_one_materials_line(3_999_999, 3_999_999, api)

    assert project["repair_eligible_cents"] == 3_999_999, (
        f"Expected 3999999, got {project['repair_eligible_cents']} as the reviewed repair basis"
    )
    assert project["size_class"] == "SMALL", (
        f"Expected SMALL, got {project['size_class']} one cent below the threshold"
    )
    assert project["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {project['status']} after cost review"
    )


def test_repair_basis_one_cent_above_small_project_threshold_is_large(api):
    """PRD §3.7: "Finally `size_class` is re-derived: `SMALL` when
    `repair_eligible_cents` is strictly below the declaration's
    `small_project_threshold_cents`, and `LARGE` when it is at or above it."

    Design: Difficulty/boundary_precision_check/repair_basis_exactly_at_small_project_threshold_is_large
    """
    project = _validate_project_on_one_materials_line(4_000_001, 4_000_001, api)

    assert project["repair_eligible_cents"] == 4_000_001, (
        f"Expected 4000001, got {project['repair_eligible_cents']} as the reviewed repair basis"
    )
    assert project["size_class"] == "LARGE", (
        f"Expected LARGE, got {project['size_class']} one cent above the threshold"
    )
    assert project["status"] == "VALIDATED", (
        f"Expected VALIDATED, got {project['status']} after cost review"
    )


# ==========================================================================
# Closeout request: the empty documented-cost set.
# ==========================================================================
def test_closeout_request_on_empty_documented_cost_set_rejected(api):
    """PRD §3.9: "At least one cost line item on the project must carry a
    `review_status` of `ALLOWED` or `PARTIALLY_ALLOWED`, because closeout is an
    accounting against documented actuals and there is nothing to account for
    otherwise; an undocumented project is refused with `ERR_NO_DOCUMENTED_COSTS`."

    PRD §2.7: "Documented costs at closeout request — `ERR_NO_DOCUMENTED_COSTS` (409)."

    PRD §3.7: "If that reviewed set is empty — a project validated on its estimate
    alone, with no documented costs yet — `repair_eligible_cents` falls back to the
    project's `estimated_repair_cost_cents`; this fallback is the pinned behaviour, not
    an error condition."

    PRD §3.7: "First, the net repair figure is `repair_eligible_cents` less
    `insurance_reduction_cents`, floored at 0 so a fully insured repair contributes
    nothing rather than a negative."

    PRD §3.3: "The project is created in `DRAFT` with `size_class` null,
    `rfi_round_count` 0, `last_rfi_question` null, `work_type` not yet derived, and
    every basis and ledger field at its opening value: `repair_eligible_cents`,
    `anticipated_insurance_cents`, `settlement_allocated_cents`,
    `insurance_reduction_cents`, `mitigation_approved_cents`,
    `eligible_cost_provisional_cents`, `federal_share_obligated_cents`,
    `deobligated_cents` and `pending_deobligation_cents` at 0, and
    `eligible_cost_final_cents`, `federal_share_final_cents`,
    `closeout_variance_cents`, `cost_reviewed_by_user_id`, `obligated_by_user_id` and
    `denial_reason` all null."

    Design: Difficulty/boundary_precision_check/closeout_request_on_empty_documented_cost_set_rejected
    """
    scenario = setup_obligated_project(
        disaster_overrides=DR_4915,
        project_overrides={
            "estimated_repair_cost_cents": 5_000_000,
            "mitigation_requested_cents": 0,
        },
    )
    project = scenario["project"]
    assert project["repair_eligible_cents"] == 5_000_000, (
        f"Expected 5000000, got {project['repair_eligible_cents']} from the empty-set fallback"
    )
    assert project["federal_share_obligated_cents"] == 3_750_000, (
        f"Expected 3750000, got {project['federal_share_obligated_cents']} after obligation"
    )

    applicant_id = scenario["applicant"]["id"]
    response = api.request_closeout(project["id"], make_applicant_agent_headers(applicant_id))
    validate_error(response, ApiErrorId.ERR_NO_DOCUMENTED_COSTS)

    after = get_project(project["id"])
    assert after["status"] == "OBLIGATED", (
        f"Expected OBLIGATED, got {after['status']} after a rejected closeout request"
    )
    assert after["eligible_cost_final_cents"] is None, (
        f"Expected None, got {after['eligible_cost_final_cents']} after a rejected closeout request"
    )


def test_closeout_request_with_exactly_one_documented_line_is_accepted(api):
    """PRD §3.9: "At least one cost line item on the project must carry a
    `review_status` of `ALLOWED` or `PARTIALLY_ALLOWED`, because closeout is an
    accounting against documented actuals and there is nothing to account for
    otherwise; an undocumented project is refused with `ERR_NO_DOCUMENTED_COSTS`."

    PRD §3.9: "Its repair basis is the sum of `eligible_cents` over the project's
    `ALLOWED` and `PARTIALLY_ALLOWED` lines, with **no** estimate fallback — the empty
    case cannot arise because it was rejected upstream."

    PRD §3.9: "`eligible_cost_final_cents` is therefore the documented repair basis less
    the actual settlement allocation, floored at 0, plus the frozen mitigation
    component."

    Design: Difficulty/boundary_precision_check/closeout_request_on_empty_documented_cost_set_rejected
    """
    scenario = setup_obligated_project(
        disaster_overrides=DR_4915,
        project_overrides={
            "estimated_repair_cost_cents": 5_000_000,
            "mitigation_requested_cents": 0,
        },
    )
    project = scenario["project"]
    applicant_id = scenario["applicant"]["id"]

    # One documented actual takes the reviewed set from empty to exactly one member.
    line = create_cost_line_item(
        project["id"],
        applicant_id,
        cost_type="MATERIALS",
        claimed_cents=5_000_000,
        work_start_at="2026-06-12T08:00:00Z",
        work_end_at="2026-06-12T17:00:00Z",
    )
    line = review_cost_line_item(line["id"])
    assert line["review_status"] == "ALLOWED", (
        f"Expected ALLOWED, got {line['review_status']} for a materials line at face value"
    )

    closed_out = validate_success(
        api.request_closeout(project["id"], make_applicant_agent_headers(applicant_id))
    )
    assert closed_out["status"] == "CLOSEOUT_REQUESTED", (
        f"Expected CLOSEOUT_REQUESTED, got {closed_out['status']} with one documented line"
    )
    assert closed_out["eligible_cost_final_cents"] == 5_000_000, (
        f"Expected 5000000, got {closed_out['eligible_cost_final_cents']} as the FINAL variant"
    )


# ==========================================================================
# Drawdown creation: the last available cent.
# ==========================================================================
def _obligate_3420000_cents():
    """A project obligated at exactly 3420000 cents on a 3800000 cent reviewed basis."""
    return setup_obligated_project(
        disaster_overrides=DR_4916,
        project_overrides={
            "estimated_repair_cost_cents": 5_000_000,
            "mitigation_requested_cents": 900_000,
        },
        line_items=[
            {
                "cost_type": "MATERIALS",
                "claimed_cents": 3_800_000,
                "work_start_at": "2026-06-12T08:00:00Z",
                "work_end_at": "2026-06-12T17:00:00Z",
            }
        ],
    )


def test_drawdown_request_exactly_equal_to_available_is_accepted(api):
    """PRD §3.8: "The applicant must be `ELIGIBLE` (`ERR_APPLICANT_NOT_ELIGIBLE`); the
    referenced project must be `OBLIGATED` (`ERR_PROJECT_INVALID_STATE`); the project
    must belong to the same applicant as the drawdown
    (`ERR_CROSS_APPLICANT_REFERENCE`); the applicant's `drawdown_status` must be
    `ACTIVE` (`ERR_DRAWDOWN_SUSPENDED`); and `requested_cents` must not exceed
    `available_drawdown_cents`, where equality is expressly allowed — drawing the last
    available cent is legitimate — with an excess rejected as
    `ERR_DRAWDOWN_EXCEEDS_AVAILABLE` and the payment-required status 402."

    PRD §3.8: "A created drawdown sits in `REQUESTED` with `approved_cents` 0,
    `refunded_cents` 0, `disbursed_by_user_id` null and `rejection_reason` null, and the
    create increments the applicant's `version` by 1 — which is why a client intending
    to file two drawdowns in a row must re-read the applicant between them."

    PRD §3.8: "`REQUESTED` and `REJECTED` drawdowns contribute nothing anywhere."

    PRD §3.8: "`cash_on_hand_cents` is `total_drawn_cents` less `total_refunded_cents`,
    and `available_drawdown_cents` is `total_obligated_cents` less
    `cash_on_hand_cents`."

    Design: Difficulty/boundary_precision_check/drawdown_request_exactly_equal_to_available_is_accepted
    """
    scenario = _obligate_3420000_cents()
    project = scenario["project"]
    assert project["repair_eligible_cents"] == 3_800_000, (
        f"Expected 3800000, got {project['repair_eligible_cents']} as the reviewed repair basis"
    )
    assert project["mitigation_approved_cents"] == 760_000, (
        f"Expected 760000, got {project['mitigation_approved_cents']} under the SMALL cap"
    )
    assert project["federal_share_obligated_cents"] == 3_420_000, (
        f"Expected 3420000, got {project['federal_share_obligated_cents']} after obligation"
    )

    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)
    applicant = get_applicant(applicant_id)
    assert applicant["available_drawdown_cents"] == 3_420_000, (
        f"Expected 3420000, got {applicant['available_drawdown_cents']} after obligation"
    )
    assert applicant["cash_on_hand_cents"] == 0, (
        f"Expected 0, got {applicant['cash_on_hand_cents']} before any cash moves"
    )

    # Exactly equal to the available balance.
    drawdown = validate_success(
        api.create_drawdown(
            drawdown_payload(applicant_id, project["id"], 3_420_000, applicant["version"]),
            agent,
        ),
        201,
    )
    assert drawdown["requested_cents"] == 3_420_000, (
        f"Expected 3420000, got {drawdown['requested_cents']} on the created drawdown"
    )
    assert drawdown["status"] == "REQUESTED", (
        f"Expected REQUESTED, got {drawdown['status']} on the created drawdown"
    )
    assert drawdown["approved_cents"] == 0, (
        f"Expected 0, got {drawdown['approved_cents']} on a drawdown that is only requested"
    )

    after = get_applicant(applicant_id)
    assert after["available_drawdown_cents"] == 3_420_000, (
        f"Expected 3420000, got {after['available_drawdown_cents']} — a REQUESTED drawdown "
        "reserves nothing"
    )

    # One cent above the same available balance.
    response = api.create_drawdown(
        drawdown_payload(applicant_id, project["id"], 3_420_001, after["version"]),
        agent,
    )
    validate_error(response, ApiErrorId.ERR_DRAWDOWN_EXCEEDS_AVAILABLE)

    _, meta = validate_paginated(api.list_drawdowns(agent))
    assert meta["total_count"] == 1, (
        f"Expected exactly 1 drawdown row, got {meta['total_count']}"
    )


def test_drawdown_request_one_cent_below_available_is_accepted(api):
    """PRD §3.8: "The applicant must be `ELIGIBLE` (`ERR_APPLICANT_NOT_ELIGIBLE`); the
    referenced project must be `OBLIGATED` (`ERR_PROJECT_INVALID_STATE`); the project
    must belong to the same applicant as the drawdown
    (`ERR_CROSS_APPLICANT_REFERENCE`); the applicant's `drawdown_status` must be
    `ACTIVE` (`ERR_DRAWDOWN_SUSPENDED`); and `requested_cents` must not exceed
    `available_drawdown_cents`, where equality is expressly allowed — drawing the last
    available cent is legitimate — with an excess rejected as
    `ERR_DRAWDOWN_EXCEEDS_AVAILABLE` and the payment-required status 402."

    PRD §3.8: "`REQUESTED` and `REJECTED` drawdowns contribute nothing anywhere."

    Design: Difficulty/boundary_precision_check/drawdown_request_exactly_equal_to_available_is_accepted
    """
    scenario = _obligate_3420000_cents()
    project = scenario["project"]
    applicant_id = scenario["applicant"]["id"]
    agent = make_applicant_agent_headers(applicant_id)
    applicant = get_applicant(applicant_id)
    assert applicant["available_drawdown_cents"] == 3_420_000, (
        f"Expected 3420000, got {applicant['available_drawdown_cents']} after obligation"
    )

    drawdown = validate_success(
        api.create_drawdown(
            drawdown_payload(applicant_id, project["id"], 3_419_999, applicant["version"]),
            agent,
        ),
        201,
    )
    assert drawdown["requested_cents"] == 3_419_999, (
        f"Expected 3419999, got {drawdown['requested_cents']} on the created drawdown"
    )
    assert drawdown["status"] == "REQUESTED", (
        f"Expected REQUESTED, got {drawdown['status']} on the created drawdown"
    )

    after = get_applicant(applicant_id)
    assert after["available_drawdown_cents"] == 3_420_000, (
        f"Expected 3420000, got {after['available_drawdown_cents']} — a REQUESTED drawdown "
        "reserves nothing"
    )
