"""One error id per guard: the not-found catalogue and the cross-entity refusals."""
from test_helpers import (
    AUDITOR_USER_ID,
    CANON_ESTIMATE_STATE_SHARE_CENTS,
    CANON_STATE_LIABILITY_CENTS,
    CLOSURE_NOTE,
    OFFICER_USER_ID,
    UNKNOWN_AGREEMENT_ID,
    UNKNOWN_CLAIM_ID,
    UNKNOWN_COMMITMENT_ID,
    UNKNOWN_CONFLICT_ID,
    UNKNOWN_DETERMINATION_ID,
    UNKNOWN_DOCUMENT_ID,
    UNKNOWN_FACILITY_ID,
    UNKNOWN_FINDING_ID,
    UNKNOWN_INVESTIGATION_ID,
    UNKNOWN_OWNER_ID,
    UNKNOWN_PERMIT_ID,
    UNKNOWN_PLAN_ID,
    UNKNOWN_PROJECT_ID,
    UNKNOWN_SLOT_ID,
    VOID_REASON,
    accept_cost_document,
    agreement_payload,
    audit_finding_payload,
    cancel_commitment,
    certify_cleared,
    commit_window,
    delay_claim_payload,
    facility_payload,
    identify_conflict,
    lodge_delay_claim,
    make_agreement_officer_headers,
    make_construction_engineer_headers,
    make_external_auditor_headers,
    make_program_admin_headers,
    make_right_of_way_adjudicator_headers,
    make_utility_coordinator_headers,
    make_utility_owner_rep_headers,
    open_final_billing,
    plan_payload,
    prior_rights_payload,
    raise_audit_finding,
    read_agreement,
    read_conflict,
    read_delay_claim,
    read_owner,
    read_plan,
    read_project,
    register_facility,
    register_project,
    report_complete,
    resolve_audit_finding,
    revise_project,
    select_resolution,
    set_clock,
    start_work,
    submit_cost_document,
    validate_error,
    validate_paginated,
    validate_success,
    void_agreement,
    world_agreement_circulated,
    world_agreement_executed,
    world_commitment,
    world_plan_approved,
    world_registry,
)

SECOND_FACILITY = {
    "facility_type": "WATER_MAIN",
    "station_begin": 300.0,
    "station_end": 340.0,
    "offset_ft": 11.0,
    "depth_in": 60,
    "material": "Ductile iron",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

SALVAGE_DOCUMENT = {
    "doc_type": "CREDIT_SALVAGE",
    "amount_cents": 1_000_000,
    "incurred_on": "2027-04-01T00:00:00Z",
    "support_reference": "SALV-2027-04-01",
}

LABOUR_DOCUMENT = {
    "doc_type": "LABOR",
    "amount_cents": 12_345_678,
    "incurred_on": "2027-04-02T00:00:00Z",
    "support_reference": "PR-1001",
}


def test_every_unknown_identifier_answers_with_its_own_not_found_error(api):
    """PRD 2.9: "Every identifier in the URL path resolves to an existing row, checked
    left to right, with the leftmost unresolved segment deciding the error."

    Design: Corner/errors/every_unknown_path_id_maps_to_its_own_not_found_error_and_never_a_generic_one
    """
    admin = make_program_admin_headers()

    validate_error(api.get_project(UNKNOWN_PROJECT_ID, admin), "ERR_PROJECT_NOT_FOUND", 404)
    validate_error(api.get_utility_owner(UNKNOWN_OWNER_ID, admin), "ERR_OWNER_NOT_FOUND", 404)
    validate_error(api.get_facility(UNKNOWN_FACILITY_ID, admin), "ERR_FACILITY_NOT_FOUND", 404)
    validate_error(
        api.get_investigation(UNKNOWN_INVESTIGATION_ID, admin),
        "ERR_INVESTIGATION_NOT_FOUND",
        404,
    )
    validate_error(api.get_conflict(UNKNOWN_CONFLICT_ID, admin), "ERR_CONFLICT_NOT_FOUND", 404)
    validate_error(
        api.get_prior_rights(UNKNOWN_DETERMINATION_ID, admin),
        "ERR_DETERMINATION_NOT_FOUND",
        404,
    )
    validate_error(api.get_relocation_plan(UNKNOWN_PLAN_ID, admin), "ERR_PLAN_NOT_FOUND", 404)
    validate_error(api.get_permit(UNKNOWN_PERMIT_ID, admin), "ERR_PERMIT_NOT_FOUND", 404)
    validate_error(
        api.get_joint_trench_slot(UNKNOWN_SLOT_ID, admin), "ERR_SLOT_NOT_FOUND", 404
    )
    validate_error(
        api.get_commitment(UNKNOWN_COMMITMENT_ID, admin), "ERR_COMMITMENT_NOT_FOUND", 404
    )
    validate_error(
        api.get_agreement(UNKNOWN_AGREEMENT_ID, admin), "ERR_AGREEMENT_NOT_FOUND", 404
    )
    validate_error(
        api.get_cost_document(UNKNOWN_DOCUMENT_ID, admin), "ERR_DOCUMENT_NOT_FOUND", 404
    )
    validate_error(
        api.get_audit_finding(UNKNOWN_FINDING_ID, admin), "ERR_FINDING_NOT_FOUND", 404
    )
    validate_error(api.get_delay_claim(UNKNOWN_CLAIM_ID, admin), "ERR_CLAIM_NOT_FOUND", 404)

    # Nested listings resolve their parent rather than returning an empty page.
    validate_error(
        api.list_conflict_relocation_plans(UNKNOWN_CONFLICT_ID, admin),
        "ERR_CONFLICT_NOT_FOUND",
        404,
    )
    validate_error(
        api.list_agreement_cost_documents(UNKNOWN_AGREEMENT_ID, admin),
        "ERR_AGREEMENT_NOT_FOUND",
        404,
    )

    # Body foreign keys name the missing referent, not the row being created.
    project = register_project(api)
    validate_error(
        api.create_prior_rights(
            prior_rights_payload(UNKNOWN_CONFLICT_ID),
            make_right_of_way_adjudicator_headers(),
        ),
        "ERR_CONFLICT_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_facility(
            facility_payload(UNKNOWN_OWNER_ID), make_utility_coordinator_headers()
        ),
        "ERR_OWNER_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_agreement(
            agreement_payload(UNKNOWN_PLAN_ID, 1), make_agreement_officer_headers()
        ),
        "ERR_PLAN_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_delay_claim(
            delay_claim_payload(UNKNOWN_COMMITMENT_ID, project["id"]),
            make_construction_engineer_headers(),
        ),
        "ERR_COMMITMENT_NOT_FOUND",
        404,
    )

    _, meta = validate_paginated(api.list_conflicts(admin))
    assert meta["total_count"] == 0


def test_the_officer_who_executed_an_agreement_may_not_audit_it(api):
    """PRD 3.8: "An auditor whose `X-User-ID` matches the agreement's
    `executed_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` — the officer who
    executed an agreement may not audit it."

    Design: Corner/errors/an_auditor_reusing_the_executing_officers_user_id_is_refused
    """
    world = world_agreement_executed(api)
    assert world["agreement"]["executed_by_user_id"] == OFFICER_USER_ID

    body = audit_finding_payload(world["agreement_id"], questioned_cost_cents=500_000)
    validate_error(
        api.create_audit_finding(body, make_external_auditor_headers(OFFICER_USER_ID)),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )
    _, meta = validate_paginated(
        api.list_agreement_audit_findings(
            world["agreement_id"], make_external_auditor_headers()
        )
    )
    assert meta["total_count"] == 0

    allowed = validate_success(
        api.create_audit_finding(body, make_external_auditor_headers(AUDITOR_USER_ID)), 201
    )
    assert allowed["status"] == "OPEN"
    assert allowed["auditor_user_id"] == AUDITOR_USER_ID
    assert allowed["disposition"] is None
    assert read_agreement(api, world["agreement_id"])["settlement_status"] == "NOT_STARTED"


def test_a_claim_against_a_still_open_commitment_cannot_be_analysed(api):
    """PRD 3.9: "Analysis moves the claim `SUBMITTED → UNDER_ANALYSIS` and requires the
    referenced commitment to have reached `COMPLETE` or `BREACHED`; a claim against a
    commitment still in `COMMITTED` or `IN_PROGRESS` is refused with
    `ERR_COMMITMENT_STATE_INVALID`."

    Design: Corner/errors/analyzing_a_claim_against_a_still_open_commitment_is_refused
    """
    world = world_commitment(api)
    engineer = make_construction_engineer_headers()
    claim = lodge_delay_claim(api, world["commitment_id"], world["project_id"])
    assert claim["status"] == "SUBMITTED"

    validate_error(
        api.analyze_delay_claim(claim["id"], {"delay_cause": "UTILITY_OWNER"}, engineer),
        "ERR_COMMITMENT_STATE_INVALID",
        409,
    )
    unchanged = read_delay_claim(api, claim["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["compensable_days"] == 0
    assert unchanged["daily_rate_cents"] == 0
    assert unchanged["delay_cause"] is None

    cancelled = cancel_commitment(
        api,
        world["commitment_id"],
        world["owner_id"],
        "Window released while the delay claim is adjudicated.",
    )
    assert cancelled["status"] == "CANCELLED"
    validate_error(
        api.report_commitment_complete(
            world["commitment_id"],
            {"completion_note": "Reported after cancellation."},
            make_utility_owner_rep_headers(world["owner_id"]),
        ),
        "ERR_COMMITMENT_STATE_INVALID",
        409,
    )


def test_execution_is_refused_while_the_posture_is_funding_blocked(api):
    """PRD 2.9: "The owning project's `clearance_posture` is not `FUNDING_BLOCKED` —
    otherwise `ERR_CLEARANCE_POSTURE_BLOCKED`. Applies to three operations: agreement
    execution, commitment creation and project closure."

    Design: Corner/errors/execution_is_refused_while_the_project_posture_is_funding_blocked
    """
    world = world_agreement_circulated(
        api, project_overrides={"reimbursement_authority_cents": 20_000_000}
    )
    blocked = read_project(api, world["project_id"])
    assert blocked["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS
    assert blocked["clearance_posture"] == "FUNDING_BLOCKED"
    assert world["agreement"]["execution_status"] == "PENDING_OWNER_SIGNATURE"

    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    validate_error(
        api.execute_agreement(world["agreement_id"], officer),
        "ERR_CLEARANCE_POSTURE_BLOCKED",
        409,
    )
    assert read_agreement(api, world["agreement_id"])["execution_status"] == (
        "PENDING_OWNER_SIGNATURE"
    )
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 0

    validate_error(
        api.create_commitment(
            {
                "plan_id": world["plan_id"],
                "window_start": "2027-04-05T00:00:00Z",
                "window_end": "2027-04-20T00:00:00Z",
                "committed_work_days": 11,
                "phase_dependency": "BEFORE_PAVING",
            },
            make_utility_owner_rep_headers(world["owner_id"]),
        ),
        "ERR_CLEARANCE_POSTURE_BLOCKED",
        409,
    )

    revise_project(api, world["project_id"], reimbursement_authority_cents=100_000_000)
    executed = validate_success(api.execute_agreement(world["agreement_id"], officer))
    assert executed["execution_status"] == "EXECUTED"
    assert executed["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS


def test_a_conflict_sequenced_behind_an_open_predecessor_cannot_be_certified(api):
    """PRD 3.3: "the same dependency rule applies: a non-null `depends_on_conflict_id`
    whose target is not `CLEARED` refuses the certification with
    `ERR_DEPENDENCY_NOT_CLEARED`."

    Design: Corner/errors/certifying_a_conflict_whose_predecessor_is_still_open_is_refused
    """
    world = world_registry(api)
    facility_b = register_facility(api, world["owner_id"], **SECOND_FACILITY)

    predecessor = identify_conflict(api, world["project_id"], world["facility_id"])
    select_resolution(api, predecessor["id"], "ABANDON")
    successor = identify_conflict(
        api,
        world["project_id"],
        facility_b["id"],
        conflict_station=320.0,
        clearance_deficiency_in=6,
        depends_on_conflict_id=predecessor["id"],
    )
    assert successor["depends_on_conflict_id"] == predecessor["id"]
    successor = select_resolution(api, successor["id"], "PROTECT_IN_PLACE")

    coordinator = make_utility_coordinator_headers()
    validate_error(
        api.certify_conflict_cleared(
            successor["id"],
            {"certification_note": "Encasement complete on the water main."},
            coordinator,
        ),
        "ERR_DEPENDENCY_NOT_CLEARED",
        409,
    )
    still_open = read_conflict(api, successor["id"])
    assert still_open["status"] == "RESOLUTION_SELECTED"
    assert still_open["version"] == successor["version"]
    assert read_project(api, world["project_id"])["open_conflict_count"] == 2

    assert certify_cleared(api, predecessor["id"], "Facility abandoned in place.")[
        "status"
    ] == "CLEARED"
    now_allowed = certify_cleared(
        api, successor["id"], "Encasement complete on the water main."
    )
    assert now_allowed["status"] == "CLEARED"
    assert read_project(api, world["project_id"])["open_conflict_count"] == 0

    rows, meta = validate_paginated(
        api.list_conflicts(coordinator, {"depends_on_conflict_id": predecessor["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == successor["id"]


def test_a_plan_behind_an_executed_agreement_cannot_be_superseded(api):
    """PRD 2.9: "No agreement of the plan that the submittal would supersede is in
    `execution_status` `EXECUTED` — otherwise
    `ERR_EXECUTED_AGREEMENT_BLOCKS_SUPERSEDE`. Applies to plan submittal."

    Design: Corner/errors/a_new_plan_cannot_supersede_a_plan_whose_agreement_is_already_executed
    """
    world = world_agreement_executed(api)
    before = read_conflict(api, world["conflict_id"])
    body = plan_payload(
        world["conflict_id"],
        before["version"],
        estimated_cost_cents=39_000_000,
        replacement_in_kind_cost_cents=32_000_000,
        proposed_capacity_ratio=1.2,
        work_days=10,
    )

    validate_error(
        api.create_relocation_plan(
            body, make_utility_owner_rep_headers(world["owner_id"])
        ),
        "ERR_EXECUTED_AGREEMENT_BLOCKS_SUPERSEDE",
        409,
    )
    rows, meta = validate_paginated(
        api.list_conflict_relocation_plans(
            world["conflict_id"], make_utility_coordinator_headers()
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world["plan_id"]
    assert rows[0]["status"] == "APPROVED"

    agreement = read_agreement(api, world["agreement_id"])
    assert agreement["execution_status"] == "EXECUTED"
    assert agreement["settlement_status"] == "NOT_STARTED"

    project = read_project(api, world["project_id"])
    assert project["total_committed_reimbursement_cents"] == (
        CANON_ESTIMATE_STATE_SHARE_CENTS
    )
    assert project["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS
    assert read_conflict(api, world["conflict_id"])["version"] == before["version"]

    void_agreement(api, world["agreement_id"], VOID_REASON)
    replacement = validate_success(
        api.create_relocation_plan(
            plan_payload(
                world["conflict_id"],
                read_conflict(api, world["conflict_id"])["version"],
                estimated_cost_cents=39_000_000,
                replacement_in_kind_cost_cents=32_000_000,
                proposed_capacity_ratio=1.2,
                work_days=10,
            ),
            make_utility_owner_rep_headers(world["owner_id"]),
        ),
        201,
    )
    assert replacement["status"] == "SUBMITTED"
    assert read_plan(api, world["plan_id"])["status"] == "SUPERSEDED"


def test_an_open_audit_finding_holds_settlement_until_it_is_resolved(api):
    """PRD 2.9: "No audit finding of the agreement remains in status `OPEN` — otherwise
    `ERR_OPEN_AUDIT_FINDING`. Applies to final settlement."

    Design: Corner/errors/an_open_audit_finding_stops_final_settlement_until_it_is_resolved
    """
    world = world_agreement_executed(api)
    finding = raise_audit_finding(api, world["agreement_id"], AUDITOR_USER_ID)
    assert finding["status"] == "OPEN"
    assert read_agreement(api, world["agreement_id"])["settlement_status"] == "NOT_STARTED"

    billing = open_final_billing(api, world["agreement_id"])
    assert billing["settlement_status"] == "PENDING_FINAL_INVOICE"

    salvage = submit_cost_document(
        api, world["agreement_id"], world["owner_id"], **SALVAGE_DOCUMENT
    )
    assert accept_cost_document(api, salvage["id"])["review_status"] == "ACCEPTED"

    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    settlement_body = {"as_built_reference": "AB-SR14-003-REV-C"}
    validate_error(
        api.final_settlement(world["agreement_id"], settlement_body, officer),
        "ERR_OPEN_AUDIT_FINDING",
        409,
    )
    held = read_agreement(api, world["agreement_id"])
    assert held["settlement_status"] == "PENDING_FINAL_INVOICE"
    assert held["cost_basis"] == "ESTIMATE_BASIS"

    resolve_audit_finding(api, finding["id"], "WITHDRAWN", AUDITOR_USER_ID)
    validate_error(
        api.final_settlement(world["agreement_id"], settlement_body, officer),
        "ERR_NO_ELIGIBLE_COST_DOCUMENTATION",
        422,
    )

    labour = submit_cost_document(
        api, world["agreement_id"], world["owner_id"], **LABOUR_DOCUMENT
    )
    accept_cost_document(api, labour["id"])
    settled = validate_success(
        api.final_settlement(world["agreement_id"], settlement_body, officer)
    )
    assert settled["settlement_status"] == "SETTLED"
    assert settled["cost_basis"] == "ACTUAL_BASIS"
    assert settled["eligible_cost_cents"] == 11_345_678
    assert settled["participation_tier_pct"] == 95
    assert settled["state_share_cents"] + settled["owner_share_cents"] == (
        settled["net_allowable_cents"]
    )

    _, meta = validate_paginated(
        api.list_agreement_audit_findings(
            world["agreement_id"], make_external_auditor_headers(), {"status": "OPEN"}
        )
    )
    assert meta["total_count"] == 0


def test_a_ceiling_one_cent_under_the_loaded_estimate_is_refused(api):
    """PRD 3.8: "it must be at least the plan's `estimated_cost_cents` loaded with the
    owner's audited indirect rate, that is, at least the estimate multiplied by 1 plus
    `indirect_cost_rate_pct` divided by 100, rounded half up to whole cents. A lower
    ceiling is refused with `ERR_NOT_TO_EXCEED_TOO_LOW`."

    Design: Corner/errors/a_not_to_exceed_one_cent_below_the_loaded_estimate_is_rejected
    """
    world = world_plan_approved(api)
    before = read_plan(api, world["plan_id"])
    officer = make_agreement_officer_headers(OFFICER_USER_ID)

    validate_error(
        api.create_agreement(
            agreement_payload(world["plan_id"], before["version"], 44_999_999), officer
        ),
        "ERR_NOT_TO_EXCEED_TOO_LOW",
        422,
    )
    assert read_plan(api, world["plan_id"])["version"] == before["version"]
    _, meta = validate_paginated(api.list_agreements(officer, {"plan_id": world["plan_id"]}))
    assert meta["total_count"] == 0

    drafted = validate_success(
        api.create_agreement(
            agreement_payload(world["plan_id"], before["version"], 45_000_000), officer
        ),
        201,
    )
    assert drafted["not_to_exceed_cents"] == 45_000_000
    assert drafted["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS
    assert drafted["execution_status"] == "DRAFT"


def test_a_claim_with_nothing_beyond_the_float_cannot_be_allocated(api):
    """PRD 3.9: "Allocation moves the claim `UNDER_ANALYSIS → ALLOCATED` and requires
    `compensable_days` to be greater than 0; a claim with nothing compensable is
    refused with `ERR_DELAY_NOT_COMPENSABLE`."

    Design: Corner/errors/allocating_a_claim_with_no_days_beyond_the_float_is_rejected
    """
    world = world_commitment(api)
    set_clock(api, "2027-04-25T00:00:00Z")
    breached = report_complete(
        api,
        world["commitment_id"],
        world["owner_id"],
        "Backfill finished exactly five days late.",
    )
    assert breached["status"] == "BREACHED"
    assert breached["late_days"] == 5

    engineer = make_construction_engineer_headers()
    claim = lodge_delay_claim(
        api,
        world["commitment_id"],
        world["project_id"],
        claimed_days=12,
        claimed_amount_cents=3_600_000,
    )
    analysed = validate_success(
        api.analyze_delay_claim(claim["id"], {"delay_cause": "UTILITY_OWNER"}, engineer)
    )
    assert analysed["status"] == "UNDER_ANALYSIS"
    assert analysed["compensable_days"] == 0
    assert analysed["daily_rate_cents"] == 250_000

    validate_error(
        api.allocate_delay_claim(claim["id"], engineer), "ERR_DELAY_NOT_COMPENSABLE", 422
    )
    stuck = read_delay_claim(api, claim["id"])
    assert stuck["status"] == "UNDER_ANALYSIS"
    assert stuck["allocated_to_owner_cents"] == 0
    assert stuck["allocated_to_state_cents"] == 0
    assert read_project(api, world["project_id"])["aggregate_compensable_delay_days"] == 0
    assert read_owner(api, world["owner_id"])["assessed_delay_liability_cents"] == 0

    denied = validate_success(
        api.deny_delay_claim(
            claim["id"],
            {"denial_reason": "Lateness fell entirely inside the contractual float."},
            engineer,
        )
    )
    assert denied["status"] == "DENIED"


def test_an_unsettled_agreement_and_an_open_claim_each_block_project_closure(api):
    """PRD 2.9: "Every conflict of the project is `CLEARED`, every agreement of the
    project is in `settlement_status` `SETTLED` or `VOIDED_OUT`, and no delay claim of
    the project remains in status `SUBMITTED` or `UNDER_ANALYSIS` — otherwise
    `ERR_PROJECT_CLOSE_BLOCKED`. Applies to project closure."

    Design: Corner/errors/an_unsettled_agreement_blocks_project_close_until_it_is_voided
    """
    world = world_agreement_executed(api)
    commitment = commit_window(api, world["plan_id"], world["owner_id"])
    start_work(api, commitment["id"], world["owner_id"])
    completed = report_complete(
        api,
        commitment["id"],
        world["owner_id"],
        "Relocation finished inside the committed window.",
    )
    assert completed["status"] == "COMPLETE"
    assert certify_cleared(api, world["conflict_id"])["status"] == "CLEARED"

    admin = make_program_admin_headers()
    before = read_project(api, world["project_id"])
    assert before["status"] == "UNDER_CONSTRUCTION"
    assert before["open_conflict_count"] == 0
    assert read_agreement(api, world["agreement_id"])["settlement_status"] == "NOT_STARTED"

    validate_error(
        api.close_project(
            world["project_id"],
            {"closure_note": "Attempting closure with an unsettled agreement."},
            admin,
        ),
        "ERR_PROJECT_CLOSE_BLOCKED",
        409,
    )
    unchanged = read_project(api, world["project_id"])
    assert unchanged["status"] == "UNDER_CONSTRUCTION"
    assert unchanged["version"] == before["version"]

    voided = void_agreement(api, world["agreement_id"], VOID_REASON)
    assert voided["settlement_status"] == "VOIDED_OUT"

    claim = lodge_delay_claim(api, commitment["id"], world["project_id"])
    assert claim["status"] == "SUBMITTED"
    validate_error(
        api.close_project(
            world["project_id"], {"closure_note": "Attempting closure with an open claim."}, admin
        ),
        "ERR_PROJECT_CLOSE_BLOCKED",
        409,
    )

    validate_success(
        api.deny_delay_claim(
            claim["id"],
            {"denial_reason": "No compensable delay was established."},
            make_construction_engineer_headers(),
        )
    )
    closed = validate_success(
        api.close_project(world["project_id"], {"closure_note": CLOSURE_NOTE}, admin)
    )
    assert closed["status"] == "CLOSED"
