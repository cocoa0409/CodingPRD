"""The ordered ladder: which rung answers when a request breaks several at once."""
from test_helpers import (
    ADJUDICATOR_USER_ID,
    AGREEMENT_NOT_TO_EXCEED_CENTS,
    CANON_ESTIMATE_STATE_SHARE_CENTS,
    CANON_STATE_LIABILITY_CENTS,
    NO_AUTH_HEADERS,
    OFFICER_USER_ID,
    UNKNOWN_DOCUMENT_ID_ALT,
    add_second_relocate_chain,
    apply_permit,
    approve_plan,
    circulate_agreement,
    decide_permit,
    draft_agreement,
    draft_determination,
    identify_conflict,
    issue_determination,
    make_agreement_officer_headers,
    make_external_auditor_headers,
    make_right_of_way_adjudicator_headers,
    make_utility_coordinator_headers,
    make_utility_owner_rep_headers,
    plan_payload,
    read_conflict,
    read_determination,
    read_owner,
    read_plan,
    read_project,
    register_facility,
    register_owner,
    register_project,
    revise_project,
    select_resolution,
    start_plan_review,
    submit_plan,
    validate_error,
    validate_paginated,
    validate_success,
    world_agreement_circulated,
    world_registry,
)

SECOND_DUCT_BANK = {
    "facility_type": "BURIED_ELECTRIC",
    "station_begin": 300.0,
    "station_end": 340.0,
    "offset_ft": 11.0,
    "depth_in": 44,
    "material": "PVC duct bank",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}

SMALL_PLAN = {
    "estimated_cost_cents": 5_000_000,
    "replacement_in_kind_cost_cents": 5_000_000,
    "proposed_capacity_ratio": 1.0,
    "work_days": 4,
}

MALFORMED_FACILITY_BODY = {
    "station_begin": 100.0,
    "station_end": 140.0,
    "offset_ft": 12.5,
    "depth_in": 48,
    "material": "PVC duct bank",
    "installed_year": 1968,
    "occupancy_basis": "PRIVATE_EASEMENT",
    "record_source": "AS_BUILT",
}


def test_the_happy_path_clears_every_rung_including_those_sitting_on_a_boundary(api):
    """PRD 2.9: "Validation is a strictly ordered ladder, not a set of independent
    checks. Rungs are evaluated in the order below, and **the first violated rung
    decides the response; no later rung is evaluated.**"

    Design: Corner/validations/the_whole_happy_path_passes_every_rule_including_the_ones_sitting_on_their_boundary
    """
    project = register_project(api)
    owner = register_owner(api)
    facility = register_facility(api, owner["id"])
    conflict = identify_conflict(api, project["id"], facility["id"])
    select_resolution(api, conflict["id"], "RELOCATE")

    determination = draft_determination(api, conflict["id"])
    issued = issue_determination(api, determination["id"])
    assert issued["final_state_share_pct"] == 100

    plan = submit_plan(
        api, conflict["id"], headers=make_utility_owner_rep_headers(owner["id"])
    )
    permit = apply_permit(api, conflict["id"])
    decide_permit(api, permit["id"], "GRANT")
    approved = approve_plan(api, plan["id"])
    assert approved["status"] == "APPROVED"

    # Rung 22 is satisfied exactly on both of its bounds.
    commitment = validate_success(
        api.create_commitment(
            {
                "plan_id": plan["id"],
                "window_start": project["construction_start_date"],
                "window_end": project["construction_end_date"],
                "committed_work_days": 11,
                "phase_dependency": "BEFORE_PAVING",
            },
            make_utility_owner_rep_headers(owner["id"]),
        ),
        201,
    )
    assert commitment["status"] == "COMMITTED"

    # Rung 28 is satisfied exactly: 40,000,000 loaded at 12.5 percent is 45,000,000.
    agreement = draft_agreement(api, plan["id"], AGREEMENT_NOT_TO_EXCEED_CENTS)
    assert agreement["not_to_exceed_cents"] == 45_000_000
    assert read_project(api, project["id"])["clearance_posture"] == "CLEARANCE_PENDING"

    circulate_agreement(api, agreement["id"])
    executed = validate_success(
        api.execute_agreement(
            agreement["id"], make_agreement_officer_headers(OFFICER_USER_ID)
        )
    )
    assert executed["execution_status"] == "EXECUTED"
    assert executed["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS

    final = read_project(api, project["id"])
    assert final["total_committed_reimbursement_cents"] == (
        CANON_ESTIMATE_STATE_SHARE_CENTS
    )
    assert final["reimbursement_authority_cents"] == 100_000_000
    assert final["clearance_posture"] == "CLEARANCE_PENDING"


def test_the_role_check_answers_before_the_body_is_looked_at(api):
    """PRD 2.9: "`X-User-Role` appears in the target endpoint's authorised-role list —
    otherwise `ERR_UNAUTHORIZED`. Applies to every endpoint."

    Design: Corner/validations/priority_two_unauthorized_is_returned_before_the_body_is_even_parsed
    """
    world = world_registry(api)
    body = {**MALFORMED_FACILITY_BODY, "ownr_id": world["owner_id"]}

    validate_error(api.create_facility(body, NO_AUTH_HEADERS), "ERR_UNAUTHENTICATED", 401)
    validate_error(
        api.create_facility(body, make_external_auditor_headers()),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.create_facility(body, make_utility_coordinator_headers()),
        "ERR_INVALID_REQUEST",
        400,
    )

    rows, meta = validate_paginated(
        api.list_owner_facilities(world["owner_id"], make_utility_coordinator_headers())
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [world["facility_id"]]


def test_a_malformed_body_answers_before_the_unknown_path_id(api):
    """PRD 2.9: "The request body and query parameters are schema-valid — required
    fields present, types correct, enumerated values in range, integers non-negative
    where declared, and every declared interval and bound respected"

    Design: Corner/validations/malformed_body_at_priority_three_beats_the_unknown_path_id_at_priority_four
    """
    officer = make_agreement_officer_headers(OFFICER_USER_ID)

    validate_error(
        api.review_cost_document(
            UNKNOWN_DOCUMENT_ID_ALT, {"disposition": "MAYBE_LATER"}, officer
        ),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.review_cost_document(
            UNKNOWN_DOCUMENT_ID_ALT, {"disposition": "ACCEPT"}, officer
        ),
        "ERR_DOCUMENT_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_cost_document(UNKNOWN_DOCUMENT_ID_ALT, officer),
        "ERR_DOCUMENT_NOT_FOUND",
        404,
    )


def test_the_prior_rights_gap_answers_before_the_permit_gap(api):
    """PRD 2.9: "The conflict behind the plan has a determination in status `ISSUED`
    or `FINAL` and the conflict's `state_share_pct` is not null — otherwise
    `ERR_PRIOR_RIGHTS_NOT_ISSUED`. Applies to plan approval."

    Design: Corner/validations/prior_rights_gap_at_priority_sixteen_is_reported_before_the_permit_gap_at_priority_seventeen
    """
    world = world_registry(api)
    conflict = identify_conflict(api, world["project_id"], world["facility_id"])
    select_resolution(api, conflict["id"], "RELOCATE")

    adjudicator = make_right_of_way_adjudicator_headers(ADJUDICATOR_USER_ID)
    determination = draft_determination(api, conflict["id"])
    under_review = validate_success(
        api.submit_prior_rights_for_review(determination["id"], adjudicator)
    )
    assert under_review["status"] == "UNDER_REVIEW"

    plan = submit_plan(api, conflict["id"])
    permit = apply_permit(api, conflict["id"])
    assert permit["status"] == "APPLIED"
    coordinator = make_utility_coordinator_headers()
    assert start_plan_review(api, plan["id"])["status"] == "UNDER_REVIEW"

    validate_error(
        api.approve_plan(plan["id"], coordinator), "ERR_PRIOR_RIGHTS_NOT_ISSUED", 409
    )
    assert read_plan(api, plan["id"])["status"] == "UNDER_REVIEW"
    assert read_conflict(api, conflict["id"])["status"] == "RESOLUTION_SELECTED"

    validate_success(api.issue_prior_rights(determination["id"], adjudicator))
    validate_error(
        api.approve_plan(plan["id"], coordinator), "ERR_PERMIT_NOT_GRANTED", 409
    )
    assert read_plan(api, plan["id"])["status"] == "UNDER_REVIEW"

    decide_permit(api, permit["id"], "GRANT")
    approved = validate_success(api.approve_plan(plan["id"], coordinator))
    assert approved["status"] == "APPROVED"
    assert read_determination(api, determination["id"])["status"] == "ISSUED"


def test_the_owner_scope_rung_binds_only_the_entity_backed_role(api):
    """PRD 2.9: "When the acting role is `UtilityOwnerRep`, `X-User-ID` equals the
    owner of the target row as described in section 2.1 — otherwise
    `ERR_OWNER_SCOPE_VIOLATION`. Applies to every endpoint whose authorised-role list
    includes `UtilityOwnerRep`."

    Design: Corner/validations/owner_scope_rule_binds_only_the_entity_backed_role
    """
    project = register_project(api)
    owner_a = register_owner(api)
    owner_b = register_owner(
        api,
        legal_name="Basin Water District",
        utility_type="WATER",
        is_public_agency=True,
        indirect_cost_rate_pct=8.0,
    )
    facility = register_facility(api, owner_a["id"])
    conflict = identify_conflict(api, project["id"], facility["id"])
    select_resolution(api, conflict["id"], "RELOCATE")
    determination = draft_determination(api, conflict["id"])
    issue_determination(api, determination["id"])

    before = read_conflict(api, conflict["id"])
    body = plan_payload(conflict["id"], before["version"])

    validate_error(
        api.create_relocation_plan(body, make_utility_owner_rep_headers(owner_b["id"])),
        "ERR_OWNER_SCOPE_VIOLATION",
        403,
    )
    assert read_conflict(api, conflict["id"])["version"] == before["version"]
    _, meta = validate_paginated(
        api.list_conflict_relocation_plans(
            conflict["id"], make_utility_coordinator_headers()
        )
    )
    assert meta["total_count"] == 0

    by_coordinator = validate_success(
        api.create_relocation_plan(body, make_utility_coordinator_headers()), 201
    )
    assert by_coordinator["status"] == "SUBMITTED"

    by_owner = submit_plan(
        api, conflict["id"], headers=make_utility_owner_rep_headers(owner_a["id"])
    )
    assert by_owner["status"] == "SUBMITTED"
    assert read_plan(api, by_coordinator["id"])["status"] == "SUPERSEDED"


def test_two_individually_affordable_agreements_break_the_authority_together(api):
    """PRD 2.9: "The resulting committed ledger does not exceed the project's
    `reimbursement_authority_cents` — otherwise `ERR_AUTHORITY_EXCEEDED`. Applies to
    agreement execution and final settlement."

    Design: Corner/validations/two_individually_affordable_agreements_exceed_the_authority_collectively
    """
    world = world_agreement_circulated(
        api, project_overrides={"reimbursement_authority_cents": 31_000_000}
    )
    add_second_relocate_chain(
        api,
        world,
        facility_overrides=SECOND_DUCT_BANK,
        conflict_overrides={"conflict_station": 320.0, "clearance_deficiency_in": 14},
        plan_overrides=SMALL_PLAN,
    )
    second = draft_agreement(api, world["plan_b_id"], 5_625_000)
    assert second["state_share_cents"] == 5_343_750
    circulate_agreement(api, second["id"])

    blocked_by_neither = read_project(api, world["project_id"])
    assert blocked_by_neither["estimated_state_liability_cents"] == 30_600_000
    assert blocked_by_neither["clearance_posture"] == "CLEARANCE_PENDING"

    officer = make_agreement_officer_headers(OFFICER_USER_ID)
    first_executed = validate_success(api.execute_agreement(world["agreement_id"], officer))
    assert first_executed["execution_status"] == "EXECUTED"
    assert first_executed["state_share_cents"] == CANON_ESTIMATE_STATE_SHARE_CENTS

    validate_error(
        api.execute_agreement(second["id"], officer), "ERR_AUTHORITY_EXCEEDED", 409
    )
    assert read_plan(api, world["plan_b_id"])["status"] == "APPROVED"
    still_pending = validate_success(api.get_agreement(second["id"], officer))
    assert still_pending["execution_status"] == "PENDING_OWNER_SIGNATURE"
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == CANON_ESTIMATE_STATE_SHARE_CENTS

    revise_project(api, world["project_id"], reimbursement_authority_cents=40_000_000)
    now_affordable = validate_success(api.execute_agreement(second["id"], officer))
    assert now_affordable["execution_status"] == "EXECUTED"
    assert read_project(api, world["project_id"])[
        "total_committed_reimbursement_cents"
    ] == 34_413_750
    assert read_owner(api, world["owner_id"])["reimbursement_hold"] is False
    assert read_project(api, world["project_id"])[
        "estimated_state_liability_cents"
    ] == CANON_STATE_LIABILITY_CENTS + 5_000_000
