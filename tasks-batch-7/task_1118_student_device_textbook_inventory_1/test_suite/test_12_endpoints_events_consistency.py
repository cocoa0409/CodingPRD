"""Endpoint cross-references, lifecycle event trail, optimistic concurrency,
logical clock, auto-generated damage reports, loaner selector determinism,
and immediate consistency (PRD §2.4, §2.7, §2.8, §2.9, §3.4, §3.5, §3.8)."""

from test_helpers import (
    ApiErrorId,
    activate_program,
    create_assignment_for,
    create_assignment_payload,
    create_fleet,
    create_loaner_checkout_for,
    create_program,
    designate_loaner,
    enroll_signed_student,
    enroll_student,
    get_success_data,
    intake_asset,
    is_iso8601_timestamp,
    return_assignment_payload,
    set_clock,
    setup_program_fleet_assets,
    setup_student_with_assignment,
    sign_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
TECH = TEST_USERS["tech_headers"]


def test_assignments_reverse_reachable_from_student(api, registrar_headers):
    """PRD §3.4: "Assignment listing supports filters on `status`, `student_account_id`, and `asset_unit_id`; the units currently held by a student are readable as a student sub-resource, and the assignments referencing a given unit are readable as a unit sub-resource."

    Design: Corner/endpoints/assignment_reverse_reachable_from_student
    """
    ctx = setup_student_with_assignment()
    data, _ = validate_paginated(
        api.list_assignments(ctx["program"]["id"], ctx["student"]["id"],
                             registrar_headers)
    )
    assert len(data) == 1
    assert data[0]["id"] == ctx["assignment"]["id"]
    assert data[0]["student_account_id"] == ctx["student"]["id"]


def test_intake_and_deploy_events_on_lifecycle_trail(api, admin_headers):
    """PRD §3.1: "A freshly intaken unit begins life in `READY` status and an `INTAKE` event lands on its lifecycle trail."
    PRD §3.4: "The unit itself transitions `READY → DEPLOYED`, its `assigned_to_student_id` is set to the student, and a `DEPLOY` event is appended to its lifecycle trail."

    Design: Corner/endpoints/lifecycle_events_appended_on_intake_and_deploy
    """
    ctx = setup_student_with_assignment()
    events, _ = validate_paginated(
        api.list_lifecycle_events(ctx["program"]["id"], ctx["asset"]["id"],
                                  admin_headers)
    )
    event_types = {ev["event_type"] for ev in events}
    assert "INTAKE" in event_types, f"INTAKE missing from {event_types}"
    assert "DEPLOY" in event_types, f"DEPLOY missing from {event_types}"


def test_assignment_create_with_stale_student_version_rejected(api,
                                                               registrar_headers):
    """PRD §2.7: "Creating an assignment — `POST /api/programs/{progId}/students/{studentId}/assignments` — requires `expected_student_version` carrying the client's last observed `version` of the student account; if another writer has advanced the student's version since the client last read it (for example by settling a fee or signing the agreement), the create is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client cannot act on a posture it has not observed."

    The client observed the student's version at enrollment; signing the
    family agreement then advances that version, so the create with the
    pre-signing version is stale.

    Design: Corner/cross_cutting_layers/occ_stale_version_on_assignment_create
    """
    program, fleet, assets = setup_program_fleet_assets(n_assets=1)
    student = enroll_student(program["id"], "SIS-OCC-1", "Occ")
    stale_version = student["version"]
    sign_agreement(program["id"], student["id"])
    payload = create_assignment_payload(assets[0]["id"], stale_version)
    res = api.create_assignment(program["id"], student["id"], payload,
                                registrar_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_clock_boots_at_fixed_instant(api):
    """PRD §2.8: "The server runs on a deterministic logical clock: it boots with `current_utc` set to 2026-05-01T00:00:00Z and never reads the wall clock."

    The first resource created before any clock advance is stamped at the
    boot instant.

    Design: Corner/cross_cutting_layers/clock_default_at_startup
    """
    program = create_program()
    assert program["created_at"].startswith("2026-05-01T00:00:00"), (
        f"Expected boot-clock timestamp, got {program['created_at']}"
    )


def test_return_with_condition_downgrade_auto_files_system_report(
        api, tech_headers, admin_headers):
    """PRD §3.5: "Two inspections close out the return: if the `return_condition_grade` is worse than the `checkout_condition_grade`, the system files a damage report automatically with `reported_by_role` set to `SYSTEM`; and the unit's lifecycle moves to `READY`, or to `IN_REPAIR` when damage was observed."

    Checkout at grade A, return at grade C: a SYSTEM damage report recording
    the observed grade C is filed automatically.

    Design: Corner/cross_cutting_layers/return_with_condition_downgrade_auto_generates_damage_report
    """
    ctx = setup_student_with_assignment(asset_grade="A")
    assert ctx["assignment"]["checkout_condition_grade"] == "A"
    returned = validate_success(
        api.return_assignment(
            ctx["program"]["id"], ctx["student"]["id"], ctx["assignment"]["id"],
            return_assignment_payload(return_condition_grade="C"), tech_headers,
        ),
        200,
    )
    assert returned["status"] == "RETURNED"
    reports, _ = validate_paginated(
        api.list_damage_reports(ctx["program"]["id"], ctx["student"]["id"],
                                ctx["assignment"]["id"], admin_headers)
    )
    system_reports = [r for r in reports if r["reported_by_role"] == "SYSTEM"]
    assert len(system_reports) == 1, (
        f"Expected one auto-filed SYSTEM report, got {reports}"
    )
    assert system_reports[0]["observed_condition_grade"] == "C"


def test_loaner_selector_breaks_ties_by_created_at(api):
    """PRD §3.8: "Candidates are ranked by `condition_grade` ascending (`A` before `B` before `C`), then by `months_in_service` ascending so that younger units go out first, and finally by the unit's `created_at` ascending as the last tie-break."

    Two grade-B loaners from the same fleet tie on grade and months in
    service; the selector must pick the one created first (the logical clock
    is advanced between the two intakes so their created_at values differ).

    Design: Corner/cross_cutting_layers/selector_uses_created_at_not_id_for_tiebreak
    """
    program = create_program(loaner_pool_threshold_pct=0.0)
    fleet = create_fleet(program["id"])
    sel1 = intake_asset(program["id"], fleet["id"], "BC-SEL-1", "SN-SEL-1", "B")
    set_clock("2026-05-02T00:00:00Z")
    sel2 = intake_asset(program["id"], fleet["id"], "BC-SEL-2", "SN-SEL-2", "B")
    activate_program(program["id"])
    designate_loaner(program["id"], sel1["id"])
    designate_loaner(program["id"], sel2["id"])
    student = enroll_signed_student(program["id"], "SIS-SEL-1", "Sel")
    checkout = create_loaner_checkout_for(program["id"], student["id"])
    assert checkout["loaner_asset_unit_id"] == sel1["id"], (
        f"Expected first-created unit {sel1['id']} to win the tie, "
        f"got {checkout['loaner_asset_unit_id']}"
    )


def test_assignment_create_immediately_reflects_side_effects(api,
                                                             admin_headers):
    """PRD §3.4: "A successful checkout creates the assignment in `ACTIVE` status, stamps `checked_out_at` from the server clock, and snapshots the unit's current grade into `checkout_condition_grade` so that any damage delta can be measured at return. The unit itself transitions `READY → DEPLOYED`, its `assigned_to_student_id` is set to the student, and a `DEPLOY` event is appended to its lifecycle trail."

    The create response carries the final state, and the very next read of
    the unit shows the cascaded mutation — no eventual-consistency lag.

    Design: Corner/consistency_model/create_response_reflects_all_side_effects_immediately
    """
    program, fleet, assets = setup_program_fleet_assets(n_assets=1)
    student = enroll_signed_student(program["id"], "SIS-IMM-1", "Imm")
    assignment = create_assignment_for(program["id"], student["id"],
                                       assets[0]["id"])
    assert assignment["status"] == "ACTIVE"
    assert is_iso8601_timestamp(assignment["checked_out_at"])
    unit = get_success_data(
        api.get_asset_unit(program["id"], assets[0]["id"], admin_headers)
    )
    assert unit["lifecycle_status"] == "DEPLOYED"
    assert unit["assigned_to_student_id"] == student["id"]
