"""The two administrative routes: closing a project and moving the logical clock."""
from test_helpers import (
    CLOSURE_NOTE,
    DEFAULT_CLOCK,
    OFFICER_USER_ID,
    accept_cost_document,
    certify_cleared,
    circulate_agreement,
    commit_window,
    conflict_payload,
    delay_claim_payload,
    draft_agreement,
    investigation_payload,
    joint_trench_slot_payload,
    make_agreement_officer_headers,
    make_construction_engineer_headers,
    make_program_admin_headers,
    make_utility_coordinator_headers,
    open_final_billing,
    owner_payload,
    project_payload,
    read_clearance_summary,
    read_commitment,
    read_project,
    report_complete,
    start_work,
    submit_cost_document,
    validate_error,
    validate_success,
    world_plan_approved,
)

SETTLEMENT_DOCUMENT = {
    "doc_type": "LABOR",
    "amount_cents": 12_345_678,
    "incurred_on": "2027-05-10T00:00:00Z",
    "support_reference": "Certified payroll 2027-05-10",
}


def test_closing_a_project_shuts_every_domain_write_except_the_registry_routes(api):
    """PRD 3.1: "`CLOSED` is terminal, and thereafter every write that resolves to this
    project is refused with `ERR_PROJECT_CLOSED` — with the three exemptions named in
    rung 12, since registering a project or an owner, and relieving an owner's
    delinquency, are not project-scoped acts."

    Design: Corner/endpoints/closing_a_project_shuts_every_domain_write_except_the_two_registry_routes
    """
    world = world_plan_approved(api)
    admin = make_program_admin_headers()
    officer = make_agreement_officer_headers(OFFICER_USER_ID)

    commitment = commit_window(api, world["plan_id"], world["owner_id"])
    start_work(api, commitment["id"], world["owner_id"])
    assert report_complete(
        api,
        commitment["id"],
        world["owner_id"],
        "Relocation complete inside the committed window.",
    )["status"] == "COMPLETE"
    assert certify_cleared(api, world["conflict_id"])["status"] == "CLEARED"

    agreement = draft_agreement(api, world["plan_id"])
    circulate_agreement(api, agreement["id"])
    validate_success(api.execute_agreement(agreement["id"], officer))
    open_final_billing(api, agreement["id"])
    document = submit_cost_document(
        api, agreement["id"], world["owner_id"], **SETTLEMENT_DOCUMENT
    )
    accept_cost_document(api, document["id"])
    settled = validate_success(
        api.final_settlement(
            agreement["id"],
            {"as_built_reference": "AB-SR14-003-REV-C"},
            officer,
        )
    )
    assert settled["settlement_status"] == "SETTLED"
    assert settled["state_share_cents"] == 8_972_222

    before_close = read_project(api, world["project_id"])
    assert before_close["status"] == "UNDER_CONSTRUCTION"
    assert before_close["clearance_posture"] == "CLEAR"

    closed = validate_success(
        api.close_project(world["project_id"], {"closure_note": CLOSURE_NOTE}, admin)
    )
    assert closed["status"] == "CLOSED"

    coordinator = make_utility_coordinator_headers()
    validate_error(
        api.create_conflict(
            conflict_payload(
                world["project_id"], world["facility_id"], conflict_station=180.0
            ),
            coordinator,
        ),
        "ERR_PROJECT_CLOSED",
        409,
    )
    validate_error(
        api.create_investigation(
            investigation_payload(world["project_id"], world["facility_id"]), coordinator
        ),
        "ERR_PROJECT_CLOSED",
        409,
    )
    engineer = make_construction_engineer_headers()
    validate_error(
        api.create_joint_trench_slot(
            joint_trench_slot_payload(world["project_id"]), engineer
        ),
        "ERR_PROJECT_CLOSED",
        409,
    )
    validate_error(
        api.create_delay_claim(
            delay_claim_payload(commitment["id"], world["project_id"]), engineer
        ),
        "ERR_PROJECT_CLOSED",
        409,
    )

    released = validate_success(
        api.release_hold(
            world["owner_id"],
            {"release_note": "Administrative release recorded after project closure."},
            admin,
        )
    )
    assert released["reimbursement_hold"] is False
    assert released["delinquency_strikes"] == 0

    validate_success(api.create_utility_owner(owner_payload(legal_name="Basin Water District"), admin), 201)
    validate_success(api.create_project(project_payload(name="SR-14 Section 4"), admin), 201)

    validate_error(
        api.close_project(world["project_id"], {"closure_note": CLOSURE_NOTE}, admin),
        "ERR_INVALID_STATE_TRANSITION",
        409,
    )


def test_the_clock_endpoint_is_program_admin_only_and_moves_the_derived_reads(api):
    """PRD 2.5: "A `ProgramAdmin` may move the clock with an administrative
    test-driving endpoint (`POST /_clock/set_current_utc`) that takes a single
    `current_utc` instant and echoes it back. Setting the clock changes no stored row,
    but every subsequent request that re-evaluates a clearance posture does so against
    the new instant."

    Design: Corner/endpoints/the_logical_clock_endpoint_is_program_admin_only_and_changes_derived_reads
    """
    world = world_plan_approved(api)
    commitment = commit_window(api, world["plan_id"], world["owner_id"])
    assert commitment["status"] == "COMMITTED"

    before = read_clearance_summary(api, world["project_id"])
    assert before["overdue_commitment_count"] == 0

    moved_forward = {"current_utc": "2027-05-01T00:00:00Z"}
    validate_error(
        api.set_clock(moved_forward, make_utility_coordinator_headers()),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.set_clock(moved_forward, make_construction_engineer_headers()),
        "ERR_UNAUTHORIZED",
        403,
    )
    assert read_clearance_summary(api, world["project_id"])[
        "overdue_commitment_count"
    ] == 0

    echoed = validate_success(api.set_clock(moved_forward, make_program_admin_headers()))
    assert echoed["current_utc"] == "2027-05-01T00:00:00Z"
    assert echoed["current_utc"] != DEFAULT_CLOCK

    after = read_clearance_summary(api, world["project_id"])
    assert after["overdue_commitment_count"] == 1
    assert after["clearance_posture"] == "AT_RISK"

    untouched = read_commitment(api, commitment["id"])
    assert untouched["status"] == "COMMITTED"
    assert untouched["late_days"] == 0
    assert untouched["version"] == commitment["version"]
