"""Who may act: the positive matrix, the negative matrix and the two narrow pairs."""
from test_helpers import (
    ADJUDICATOR_USER_ID,
    AUDITOR_USER_ID,
    OFFICER_USER_ID,
    agreement_payload,
    audit_finding_payload,
    commit_window,
    commitment_payload,
    conflict_payload,
    cost_document_payload,
    delay_claim_payload,
    facility_payload,
    identify_conflict,
    investigation_payload,
    joint_trench_slot_payload,
    make_agreement_officer_headers,
    make_construction_engineer_headers,
    make_external_auditor_headers,
    make_program_admin_headers,
    make_right_of_way_adjudicator_headers,
    make_utility_coordinator_headers,
    make_utility_owner_rep_headers,
    owner_payload,
    permit_payload,
    plan_payload,
    plan_resubmit_payload,
    prior_rights_payload,
    project_payload,
    read_agreement,
    read_clearance_summary,
    read_conflict,
    read_cost_document,
    read_determination,
    read_project,
    record_investigation,
    register_facility,
    register_owner,
    register_project,
    submit_cost_document,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
    world_agreement_drafted,
    world_final_billing_open,
)

REVISED_TERMS = {
    "estimated_cost_cents": 39_000_000,
    "replacement_in_kind_cost_cents": 32_000_000,
    "proposed_capacity_ratio": 1.20,
    "work_days": 10,
}


def test_each_role_acts_only_on_the_operations_its_own_row_claims(api):
    """PRD 4: "All authorised-role lists below are exhaustive: a role absent from a row
    cannot invoke that endpoint, and the attempt returns `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/each_role_exercises_its_own_exclusive_operations_along_one_chain
    """
    admin = make_program_admin_headers()
    coordinator = make_utility_coordinator_headers()
    adjudicator = make_right_of_way_adjudicator_headers(ADJUDICATOR_USER_ID)
    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    auditor = make_external_auditor_headers(AUDITOR_USER_ID)
    engineer = make_construction_engineer_headers()

    project = validate_success(api.create_project(project_payload(), admin), 201)
    owner = validate_success(api.create_utility_owner(owner_payload(), admin), 201)
    rep = make_utility_owner_rep_headers(owner["id"])

    facility = validate_success(
        api.create_facility(facility_payload(owner["id"]), coordinator), 201
    )
    validate_success(
        api.create_investigation(
            investigation_payload(project["id"], facility["id"]), coordinator
        ),
        201,
    )
    conflict = validate_success(
        api.create_conflict(conflict_payload(project["id"], facility["id"]), coordinator),
        201,
    )
    validate_success(
        api.set_conflict_resolution(
            conflict["id"], {"resolution_type": "RELOCATE"}, coordinator
        )
    )

    determination = validate_success(
        api.create_prior_rights(prior_rights_payload(conflict["id"]), adjudicator), 201
    )
    validate_success(api.submit_prior_rights_for_review(determination["id"], adjudicator))
    issued = validate_success(api.issue_prior_rights(determination["id"], adjudicator))
    assert issued["final_state_share_pct"] == 100
    assert issued["first_issued_by_user_id"] == ADJUDICATOR_USER_ID

    slot = validate_success(
        api.create_joint_trench_slot(joint_trench_slot_payload(project["id"]), engineer),
        201,
    )

    conflict_row = validate_success(api.get_conflict(conflict["id"], coordinator))
    plan = validate_success(
        api.create_relocation_plan(
            plan_payload(conflict["id"], conflict_row["version"]), rep
        ),
        201,
    )
    permit = validate_success(
        api.create_permit(permit_payload(conflict["id"]), coordinator), 201
    )
    validate_success(api.decide_permit(permit["id"], {"decision": "GRANT"}, coordinator))
    validate_success(api.start_plan_review(plan["id"], coordinator))
    validate_success(api.approve_plan(plan["id"], coordinator))

    commitment = validate_success(
        api.create_commitment(
            commitment_payload(plan["id"], joint_trench_slot_id=slot["id"]), rep
        ),
        201,
    )

    plan_row = validate_success(api.get_relocation_plan(plan["id"], officer))
    agreement = validate_success(
        api.create_agreement(agreement_payload(plan["id"], plan_row["version"]), officer),
        201,
    )
    validate_success(api.circulate_agreement(agreement["id"], officer))
    executed = validate_success(api.execute_agreement(agreement["id"], officer))
    assert executed["executed_by_user_id"] == OFFICER_USER_ID
    validate_success(api.open_final_billing(agreement["id"], officer))

    document = validate_success(
        api.create_cost_document(cost_document_payload(agreement["id"]), rep), 201
    )
    validate_success(
        api.review_cost_document(document["id"], {"disposition": "ACCEPT"}, officer)
    )

    finding = validate_success(
        api.create_audit_finding(
            audit_finding_payload(agreement["id"], questioned_cost_cents=100_000), auditor
        ),
        201,
    )
    validate_success(
        api.resolve_audit_finding(finding["id"], {"disposition": "WITHDRAWN"}, auditor)
    )

    validate_success(api.start_commitment_work(commitment["id"], rep))
    completed = validate_success(
        api.report_commitment_complete(
            commitment["id"],
            {"completion_note": "Relocation complete inside the committed window."},
            rep,
        )
    )
    assert completed["status"] == "COMPLETE"
    cleared = validate_success(
        api.certify_conflict_cleared(
            conflict["id"],
            {"certification_note": "Facility relocated clear of the template."},
            coordinator,
        )
    )
    assert cleared["status"] == "CLEARED"

    claim = validate_success(
        api.create_delay_claim(
            delay_claim_payload(
                commitment["id"],
                project["id"],
                claimed_days=2,
                claimed_amount_cents=400_000,
            ),
            engineer,
        ),
        201,
    )
    validate_success(
        api.deny_delay_claim(
            claim["id"],
            {"denial_reason": "Relocation finished inside the committed window."},
            engineer,
        )
    )

    revised = validate_success(
        api.update_project(
            project["id"], {"reimbursement_authority_cents": 120_000_000}, admin
        )
    )
    assert revised["reimbursement_authority_cents"] == 120_000_000

    clock = validate_success(
        api.set_clock({"current_utc": "2027-05-01T00:00:00Z"}, admin)
    )
    assert clock["current_utc"] == "2027-05-01T00:00:00Z"

    settled = validate_success(
        api.final_settlement(
            agreement["id"], {"as_built_reference": "AB-SR14-003-REV-C"}, officer
        )
    )
    assert settled["settlement_status"] == "SETTLED"
    assert settled["cost_basis"] == "ACTUAL_BASIS"
    assert settled["eligible_cost_cents"] == 12_345_678
    assert settled["indirect_cost_cents"] == 1_543_210
    assert settled["betterment_credit_cents"] == 4_444_444
    assert settled["net_allowable_cents"] == 9_444_444
    assert settled["participation_tier_pct"] == 95
    assert settled["state_share_cents"] == 8_972_222
    assert settled["owner_share_cents"] == 472_222


def test_the_revision_loops_are_reachable_by_their_owning_and_shared_roles(api):
    """PRD 3.5: "Resubmission — open to the owner's representative and to a coordinator
    — moves it `REVISION_REQUESTED → SUBMITTED`, increments `revision_round` by 1, and
    overwrites all four substantive numbers"

    Design: Corner/rbac/the_revision_operations_are_reachable_by_their_owning_and_shared_roles
    """
    project = register_project(api)
    owner = register_owner(api)
    facility = register_facility(api, owner["id"])
    conflict = identify_conflict(api, project["id"], facility["id"])
    coordinator = make_utility_coordinator_headers()
    validate_success(
        api.set_conflict_resolution(
            conflict["id"], {"resolution_type": "RELOCATE"}, coordinator
        )
    )

    adjudicator = make_right_of_way_adjudicator_headers(ADJUDICATOR_USER_ID)
    determination = validate_success(
        api.create_prior_rights(prior_rights_payload(conflict["id"]), adjudicator), 201
    )
    validate_success(api.submit_prior_rights_for_review(determination["id"], adjudicator))

    plan = submit_plan(
        api, conflict["id"], headers=make_utility_owner_rep_headers(owner["id"])
    )
    validate_success(api.start_plan_review(plan["id"], coordinator))

    returned = validate_success(
        api.request_plan_revision(
            plan["id"],
            {"revision_note": "Break out the betterment portion of the duct bank."},
            coordinator,
        )
    )
    assert returned["status"] == "REVISION_REQUESTED"

    resubmitted = validate_success(
        api.resubmit_plan(plan["id"], plan_resubmit_payload(**REVISED_TERMS), coordinator)
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["estimated_cost_cents"] == 39_000_000
    assert resubmitted["proposed_capacity_ratio"] == 1.20
    assert resubmitted["betterment_ratio"] == 0.316239
    assert resubmitted["betterment_amount_cents"] == 12_333_321

    sent_back = validate_success(
        api.return_prior_rights_for_revision(
            determination["id"],
            {"revision_note": "Attach the recorded easement instrument."},
            adjudicator,
        )
    )
    assert sent_back["status"] == "RETURNED_FOR_REVISION"

    reworked = validate_success(
        api.revise_prior_rights(
            determination["id"],
            {
                "claimed_basis": "FEE_SIMPLE",
                "narrative": "Recorded deed conveying fee title ahead of acquisition.",
            },
            adjudicator,
        )
    )
    assert reworked["status"] == "DRAFT"
    assert reworked["claimed_basis"] == "FEE_SIMPLE"


def test_no_role_can_reach_another_roles_exclusive_operation(api):
    """PRD 2.9: "`X-User-Role` appears in the target endpoint's authorised-role list —
    otherwise `ERR_UNAUTHORIZED`. Applies to every endpoint."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation_and_each_attempt_is_unauthorized
    """
    world = world_final_billing_open(api)
    commit_window(api, world["plan_id"], world["owner_id"])
    document = submit_cost_document(api, world["agreement_id"], world["owner_id"])
    before_project = read_project(api, world["project_id"])
    before_summary = read_clearance_summary(api, world["project_id"])

    validate_error(
        api.review_cost_document(
            document["id"], {"disposition": "ACCEPT"}, make_external_auditor_headers()
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.final_settlement(
            world["agreement_id"],
            {"as_built_reference": "AB-SR14-003-REV-C"},
            make_utility_coordinator_headers(),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.certify_conflict_cleared(
            world["conflict_id"],
            {"certification_note": "Certified by the wrong desk."},
            make_agreement_officer_headers(),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.create_prior_rights(
            prior_rights_payload(world["conflict_id"]),
            make_construction_engineer_headers(),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.create_joint_trench_slot(
            joint_trench_slot_payload(world["project_id"]),
            make_right_of_way_adjudicator_headers(),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.create_audit_finding(
            audit_finding_payload(world["agreement_id"]), make_program_admin_headers()
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.update_project(
            world["project_id"],
            {"reimbursement_authority_cents": 200_000_000},
            make_utility_owner_rep_headers(world["owner_id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.set_clock(
            {"current_utc": "2027-05-01T00:00:00Z"}, make_construction_engineer_headers()
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    assert read_cost_document(api, document["id"])["review_status"] == "SUBMITTED"
    agreement = read_agreement(api, world["agreement_id"])
    assert agreement["settlement_status"] == "PENDING_FINAL_INVOICE"
    assert agreement["cost_basis"] == "ESTIMATE_BASIS"
    assert read_conflict(api, world["conflict_id"])["status"] == "RELOCATION_SCHEDULED"
    assert read_determination(api, world["determination_id"])["status"] == "ISSUED"

    _, determinations = validate_paginated(
        api.list_conflict_prior_rights(
            world["conflict_id"], make_right_of_way_adjudicator_headers()
        )
    )
    assert determinations["total_count"] == 1
    _, slots = validate_paginated(
        api.list_project_joint_trench_slots(
            world["project_id"], make_construction_engineer_headers()
        )
    )
    assert slots["total_count"] == 0
    _, findings = validate_paginated(
        api.list_agreement_audit_findings(
            world["agreement_id"], make_external_auditor_headers()
        )
    )
    assert findings["total_count"] == 0

    after_project = read_project(api, world["project_id"])
    assert after_project["reimbursement_authority_cents"] == 100_000_000
    assert after_project["version"] == before_project["version"]

    after_summary = read_clearance_summary(api, world["project_id"])
    assert after_summary["overdue_commitment_count"] == 0
    assert after_summary["at_risk_commitment_count"] == (
        before_summary["at_risk_commitment_count"]
    )
    assert after_summary["clearance_posture"] == before_summary["clearance_posture"]


def test_the_two_declared_user_pairs_are_the_only_segregated_ones(api):
    """PRD 2.9: "Segregation of duties on the acting `X-User-ID` — otherwise
    `ERR_SEGREGATION_OF_DUTIES`. Applies to exactly two operations: raising an audit
    finding, and issuing a determination that has been through an appeal."

    Design: Corner/rbac/segregation_of_duties_binds_only_the_two_declared_user_pairs
    """
    world = world_agreement_drafted(api)
    officer = make_agreement_officer_headers(OFFICER_USER_ID)

    circulated = validate_success(api.circulate_agreement(world["agreement_id"], officer))
    assert circulated["execution_status"] == "PENDING_OWNER_SIGNATURE"
    executed = validate_success(api.execute_agreement(world["agreement_id"], officer))
    assert executed["execution_status"] == "EXECUTED"
    assert executed["executed_by_user_id"] == OFFICER_USER_ID
    billing = validate_success(api.open_final_billing(world["agreement_id"], officer))
    assert billing["settlement_status"] == "PENDING_FINAL_INVOICE"

    determination = read_determination(api, world["determination_id"])
    assert determination["first_issued_by_user_id"] == ADJUDICATOR_USER_ID
    assert determination["status"] == "ISSUED"

    finding = validate_success(
        api.create_audit_finding(
            audit_finding_payload(world["agreement_id"]),
            make_external_auditor_headers(AUDITOR_USER_ID),
        ),
        201,
    )
    assert finding["status"] == "OPEN"
    assert finding["auditor_user_id"] == AUDITOR_USER_ID
    assert read_agreement(api, world["agreement_id"])["settlement_status"] == (
        "AUDIT_IN_PROGRESS"
    )


def test_every_role_the_endpoint_lists_can_read_it_including_the_owner_rep(api):
    """PRD 2.1: "This scoping applies to every operation whose authorised-role list
    includes `UtilityOwnerRep`, reads included."

    Design: Corner/rbac/every_role_the_endpoint_lists_can_read_it_including_the_entity_backed_one
    """
    project = register_project(api)
    owner = register_owner(api)
    facility = register_facility(api, owner["id"])
    conflict = identify_conflict(api, project["id"], facility["id"])
    assert conflict["status"] == "IDENTIFIED"
    investigation = record_investigation(api, project["id"], facility["id"])

    rep_read = validate_success(
        api.get_project(project["id"], make_utility_owner_rep_headers(owner["id"]))
    )
    auditor_read = validate_success(
        api.get_project(project["id"], make_external_auditor_headers())
    )
    assert rep_read["status"] == "CLEARANCE_ACTIVE"
    assert auditor_read["status"] == rep_read["status"]

    engineer_summary = validate_success(
        api.get_clearance_summary(project["id"], make_construction_engineer_headers())
    )
    assert engineer_summary["clearance_posture"] == "AT_RISK"
    assert engineer_summary["open_conflict_count"] == 1

    rows, _ = validate_paginated(
        api.list_investigations(
            make_right_of_way_adjudicator_headers(), {"project_id": project["id"]}
        )
    )
    assert [row["id"] for row in rows] == [investigation["id"]]

    _, agreements = validate_paginated(
        api.list_agreements(make_utility_owner_rep_headers(owner["id"]))
    )
    assert agreements["total_count"] == 0

    validate_error(
        api.get_clearance_summary(project["id"], make_external_auditor_headers()),
        "ERR_UNAUTHORIZED",
        403,
    )
