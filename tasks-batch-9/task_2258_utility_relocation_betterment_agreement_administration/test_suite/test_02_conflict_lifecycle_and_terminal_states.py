"""Initial states, terminal-state lockdown and the certification edges."""
from test_helpers import (
    CANON_STATE_LIABILITY_CENTS,
    CERTIFICATION_NOTE,
    agreement_payload,
    audit_finding_payload,
    commitment_payload,
    conflict_payload,
    cost_document_payload,
    delay_claim_payload,
    facility_payload,
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
    project_payload,
    raise_audit_finding,
    read_agreement,
    read_determination,
    read_permit_record,
    read_project,
    report_complete,
    resolve_audit_finding,
    select_resolution,
    validate_error,
    validate_success,
    world_commitment,
    world_final_billing_open,
    world_plan_approved,
    world_resolution_selected,
)


def test_every_created_row_starts_in_its_declared_initial_state(api):
    """PRD 3.8: "A drafted agreement opens with `execution_status` `DRAFT`,
    `settlement_status` `NOT_STARTED` and `cost_basis` `ESTIMATE_BASIS`; its
    `project_id` and `owner_id` are denormalised from the plan's conflict exactly
    as a commitment's are; `as_built_reference` and `executed_by_user_id` are
    null; and all nine settlement figures are computed immediately on the estimate
    basis."

    Design: Corner/state_machines/every_created_row_starts_in_its_declared_initial_state
    """
    admin = make_program_admin_headers()
    coordinator = make_utility_coordinator_headers()
    adjudicator = make_right_of_way_adjudicator_headers()
    engineer = make_construction_engineer_headers()
    officer = make_agreement_officer_headers()
    auditor = make_external_auditor_headers()

    project = validate_success(api.create_project(project_payload(), admin), 201)
    assert project["status"] == "PLANNING"
    owner = validate_success(api.create_utility_owner(owner_payload(), admin), 201)
    rep = make_utility_owner_rep_headers(owner["id"])
    facility = validate_success(
        api.create_facility(facility_payload(owner["id"]), coordinator), 201
    )

    conflict = validate_success(
        api.create_conflict(conflict_payload(project["id"], facility["id"]), coordinator),
        201,
    )
    assert conflict["status"] == "IDENTIFIED"
    assert conflict["state_share_pct"] is None
    assert read_project(api, project["id"])["status"] == "CLEARANCE_ACTIVE"

    validate_success(
        api.create_investigation(
            investigation_payload(project["id"], facility["id"]), coordinator
        ),
        201,
    )

    determination = validate_success(
        api.create_prior_rights(
            {
                "conflict_id": conflict["id"],
                "claimed_basis": "PRIVATE_EASEMENT",
                "narrative": "Recorded private easement predating right-of-way acquisition.",
            },
            adjudicator,
        ),
        201,
    )
    assert determination["status"] == "DRAFT"
    assert determination["appeal_round"] == 0
    assert determination["final_state_share_pct"] is None
    assert determination["first_issued_by_user_id"] is None

    permit = validate_success(
        api.create_permit(permit_payload(conflict["id"]), coordinator), 201
    )
    assert permit["status"] == "APPLIED"
    assert permit["granted_on"] is None

    slot = validate_success(
        api.create_joint_trench_slot(joint_trench_slot_payload(project["id"]), engineer),
        201,
    )
    assert slot["status"] == "OPEN"
    assert slot["occupant_count"] == 0

    select_resolution(api, conflict["id"], "RELOCATE")
    validate_success(api.submit_prior_rights_for_review(determination["id"], adjudicator))
    validate_success(api.issue_prior_rights(determination["id"], adjudicator))

    conflict_version = validate_success(api.get_conflict(conflict["id"], coordinator))[
        "version"
    ]
    plan = validate_success(
        api.create_relocation_plan(
            plan_payload(conflict["id"], conflict_version), rep
        ),
        201,
    )
    assert plan["status"] == "SUBMITTED"
    assert plan["revision_round"] == 0

    validate_success(api.decide_permit(permit["id"], {"decision": "GRANT"}, coordinator))
    validate_success(api.start_plan_review(plan["id"], coordinator))
    validate_success(api.approve_plan(plan["id"], coordinator))

    commitment = validate_success(
        api.create_commitment(commitment_payload(plan["id"]), rep), 201
    )
    assert commitment["status"] == "COMMITTED"
    assert commitment["actual_complete_at"] is None
    assert commitment["late_days"] == 0

    plan_version = validate_success(api.get_relocation_plan(plan["id"], officer))["version"]
    agreement = validate_success(
        api.create_agreement(agreement_payload(plan["id"], plan_version), officer), 201
    )
    assert agreement["execution_status"] == "DRAFT"
    assert agreement["settlement_status"] == "NOT_STARTED"
    assert agreement["cost_basis"] == "ESTIMATE_BASIS"
    assert agreement["as_built_reference"] is None
    assert agreement["executed_by_user_id"] is None

    validate_success(api.circulate_agreement(agreement["id"], officer))
    validate_success(api.execute_agreement(agreement["id"], officer))
    validate_success(api.open_final_billing(agreement["id"], officer))

    document = validate_success(
        api.create_cost_document(cost_document_payload(agreement["id"]), rep), 201
    )
    assert document["review_status"] == "SUBMITTED"
    assert document["disallowed_amount_cents"] == 0
    assert document["exclusion_reason"] is None

    finding = validate_success(
        api.create_audit_finding(audit_finding_payload(agreement["id"]), auditor), 201
    )
    assert finding["status"] == "OPEN"
    assert finding["disposition"] is None

    claim = validate_success(
        api.create_delay_claim(
            delay_claim_payload(commitment["id"], project["id"]), engineer
        ),
        201,
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["delay_cause"] is None
    assert claim["compensable_days"] == 0
    assert claim["daily_rate_cents"] == 0
    assert claim["allocated_to_owner_cents"] == 0
    assert claim["allocated_to_state_cents"] == 0


def test_granted_permit_and_resolved_finding_accept_no_further_transition(api):
    """PRD 3.6: "Both branches increment the record's `version`, and both target
    states are terminal, so a second decision on the same record is refused with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/granted_permit_and_resolved_finding_accept_no_further_transition
    """
    world = world_final_billing_open(api)
    finding = raise_audit_finding(api, world["agreement_id"])
    finding = resolve_audit_finding(api, finding["id"], "WITHDRAWN")
    assert finding["status"] == "RESOLVED"
    assert finding["disposition"] == "WITHDRAWN"
    permit_before = read_permit_record(api, world["permit_id"])
    assert permit_before["status"] == "GRANTED"

    validate_error(
        api.decide_permit(
            world["permit_id"], {"decision": "DENY"}, make_utility_coordinator_headers()
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )
    validate_error(
        api.resolve_audit_finding(
            finding["id"], {"disposition": "SUSTAINED"}, make_external_auditor_headers()
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )

    permit_after = read_permit_record(api, world["permit_id"])
    assert permit_after["status"] == "GRANTED"
    assert permit_after["granted_on"] == permit_before["granted_on"]
    assert permit_after["version"] == permit_before["version"]

    finding_after = validate_success(
        api.get_audit_finding(finding["id"], make_external_auditor_headers())
    )
    assert finding_after["status"] == "RESOLVED"
    assert finding_after["disposition"] == "WITHDRAWN"
    assert finding_after["version"] == finding["version"]

    assert read_agreement(api, world["agreement_id"])["settlement_status"] == (
        "PENDING_FINAL_INVOICE"
    )


def test_certify_cleared_twice_is_rejected_on_the_second_call(api):
    """PRD 3.3: "Certification from any other state, or a second certification of an
    already-`CLEARED` conflict, is refused with `ERR_INVALID_STATE_TRANSITION`;
    `CLEARED` is terminal."

    Design: Corner/state_machines/certify_cleared_twice_is_rejected_on_the_second_call
    """
    world = world_resolution_selected(
        api,
        resolution_type="PROTECT_IN_PLACE",
        conflict_overrides={"clearance_deficiency_in": 4},
    )
    coordinator = make_utility_coordinator_headers()
    first = validate_success(
        api.certify_conflict_cleared(
            world["conflict_id"], {"certification_note": CERTIFICATION_NOTE}, coordinator
        )
    )
    assert first["status"] == "CLEARED"
    project_after_first = read_project(api, world["project_id"])

    validate_error(
        api.certify_conflict_cleared(
            world["conflict_id"],
            {"certification_note": "Replay of the same certification."},
            coordinator,
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )

    conflict_after = validate_success(api.get_conflict(world["conflict_id"], coordinator))
    assert conflict_after["status"] == "CLEARED"
    assert conflict_after["version"] == first["version"]

    project_after = read_project(api, world["project_id"])
    assert project_after["version"] == project_after_first["version"]
    assert project_after["open_conflict_count"] == 0
    assert project_after["clearance_posture"] == "CLEAR"
    assert project_after["status"] == "LETTING_READY"


def test_certify_cleared_from_relocation_planned_is_not_a_declared_transition(api):
    """PRD 3.3: "Certification from `RELOCATION_SCHEDULED` requires all of: the
    conflict's `resolution_type` is `RELOCATE`; at least one schedule commitment of
    the conflict has reached `COMPLETE`; and either `depends_on_conflict_id` is
    null or the conflict it references is already `CLEARED`, failing which the
    request is refused with `ERR_DEPENDENCY_NOT_CLEARED`."

    Design: Corner/state_machines/certify_cleared_from_relocation_planned_is_not_a_declared_transition
    """
    world = world_plan_approved(api)
    assert world["conflict"]["status"] == "RELOCATION_PLANNED"

    validate_error(
        api.certify_conflict_cleared(
            world["conflict_id"], {}, make_utility_coordinator_headers()
        ),
        "ERR_INVALID_STATE_TRANSITION",
    )

    conflict = validate_success(
        api.get_conflict(world["conflict_id"], make_utility_coordinator_headers())
    )
    assert conflict["status"] == "RELOCATION_PLANNED"
    assert read_determination(api, world["determination_id"])["status"] == "ISSUED"

    project = read_project(api, world["project_id"])
    assert project["open_conflict_count"] == 1
    assert project["clearance_posture"] == "CLEARANCE_PENDING"


def test_certifying_the_last_conflict_locks_the_determination_and_lets_the_project(api):
    """PRD 3.3: "On success the conflict moves `RELOCATION_SCHEDULED → CLEARED`, the
    conflict's prior-rights determination is locked from `ISSUED` to `FINAL`, the
    project's `open_conflict_count` and `estimated_state_liability_cents` are
    recomputed (this conflict's contribution drops out of the estimate), the
    posture is re-evaluated, a resulting `CLEAR` posture bubbles the project
    `CLEARANCE_ACTIVE → LETTING_READY`, and the conflict's `version` increments."

    Design: Corner/state_machines/certifying_the_last_conflict_bubbles_the_project_to_letting_ready_and_locks_the_determination
    """
    world = world_commitment(api)
    completed = report_complete(api, world["commitment_id"], world["owner_id"])
    assert completed["status"] == "COMPLETE"
    assert completed["late_days"] == 0

    before = read_project(api, world["project_id"])
    assert before["estimated_state_liability_cents"] == CANON_STATE_LIABILITY_CENTS
    assert before["status"] == "CLEARANCE_ACTIVE"

    cleared = validate_success(
        api.certify_conflict_cleared(
            world["conflict_id"],
            {"certification_note": "Relocation complete, clearance verified in the field."},
            make_utility_coordinator_headers(),
        )
    )
    assert cleared["status"] == "CLEARED"

    determination = read_determination(api, world["determination_id"])
    assert determination["status"] == "FINAL"
    assert determination["final_state_share_pct"] == 100

    after = read_project(api, world["project_id"])
    assert after["open_conflict_count"] == 0
    assert after["estimated_state_liability_cents"] == 0
    assert after["clearance_posture"] == "CLEAR"
    assert after["status"] == "LETTING_READY"
