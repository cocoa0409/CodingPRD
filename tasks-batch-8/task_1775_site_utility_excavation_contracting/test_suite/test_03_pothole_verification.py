"""Pothole verification: cross-project ticket scope, station uniqueness,
tolerance boundaries, supersede, and validation priority."""

from test_helpers import (
    FOREMAN,
    PROJECT_MANAGER,
    ApiErrorId,
    advance_clock,
    create_locate_ticket,
    create_project,
    get_pothole,
    get_ticket,
    pothole_payload,
    setup_project_with_active_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

LEGAL_START = "2026-08-03T00:00:00Z"


def test_pothole_rejects_ticket_from_another_project(api):
    """PRD §3.2: "A `ProjectManager` plans a verification at a survey station
    by providing the `project_id`, the `locate_ticket_id` of the ticket
    covering the dig area — which must belong to the same project or the
    create fails with `ERR_CROSS_PROJECT_REFERENCE`"

    Design: Corner/entities/pothole_cross_project_ticket_rejected
    """
    p1 = create_project(name="P1-XREF", contract_ref="C-105")
    p2 = create_project(name="P2-XREF", contract_ref="C-106")
    ticket_p2 = create_locate_ticket(
        p2["id"], ticket_number="T-P2", legal_start_at=LEGAL_START
    )

    response = api.create_pothole_verification(
        pothole_payload(
            p1["id"], ticket_p2["id"], station_label="STA 1+00",
            expected_utility_type="GAS", method="HAND_DIG",
            design_depth_in=40, design_offset_in=5,
        ),
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CROSS_PROJECT_REFERENCE, 422)

    _, meta = validate_paginated(
        api.list_pothole_verifications(
            PROJECT_MANAGER, params={"project_id": p1["id"]}
        )
    )
    assert meta["total_count"] == 0, "rejected create must not persist"


def test_duplicate_station_rejected_while_live(api):
    """PRD §3.2: "Only one live verification may exist per station within a
    project: if a verification for the same `station_label` already exists in
    `PLANNED`, `PERFORMED`, or `VERIFIED`, the create is rejected with
    `ERR_DUPLICATE_STATION`."

    Design: Corner/validations/duplicate_station_rejected
    """
    project = create_project(name="P-DUP", contract_ref="C-409")
    ticket = create_locate_ticket(
        project["id"], ticket_number="T-1", legal_start_at=LEGAL_START
    )
    first = validate_success(
        api.create_pothole_verification(
            pothole_payload(
                project["id"], ticket["id"], station_label="STA 3+00",
                expected_utility_type="GAS", method="HAND_DIG",
                design_depth_in=40, design_offset_in=5,
            ),
            PROJECT_MANAGER,
        ),
        201,
    )

    response = api.create_pothole_verification(
        pothole_payload(
            project["id"], ticket["id"], station_label="STA 3+00",
            expected_utility_type="GAS", method="VACUUM",
            design_depth_in=40, design_offset_in=5,
        ),
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_STATION, 409)
    assert get_pothole(first["id"])["status"] == "PLANNED"


def test_pothole_tolerance_boundary_and_conflict_supersede(api):
    """PRD §3.2: "verification succeeds, moving `PERFORMED → VERIFIED`, when
    the measured depth differs from the design depth by at most 6 inches and
    the measured offset differs from the design offset by at most 12 inches —
    both boundaries inclusive — and is rejected with
    `ERR_POTHOLE_TOLERANCE_EXCEEDED` otherwise."
    PRD §3.2: "If the existing one is in `CONFLICT`, however, the new plan
    supersedes it, pushing the old record into `SUPERSEDED` — conflict is the
    only state from which a station may be re-planned."

    Design: Corner/errors/pothole_tolerance_boundary_and_supersede
    """
    ctx = setup_project_with_active_ticket(with_verified_pothole=False)
    project, ticket = ctx["project"], ctx["ticket"]

    # PH1: depth delta exactly 6 inches — the inclusive boundary passes.
    ph1 = validate_success(
        api.create_pothole_verification(
            pothole_payload(project["id"], ticket["id"], station_label="STA 1+00"),
            PROJECT_MANAGER,
        ),
        201,
    )
    validate_success(
        api.perform_pothole(
            ph1["id"], {"measured_depth_in": 66, "measured_offset_in": 12}, FOREMAN
        )
    )
    verified = validate_success(api.verify_pothole(ph1["id"], PROJECT_MANAGER))
    assert verified["status"] == "VERIFIED"

    # PH2: depth delta 7 inches — one inch beyond the boundary.
    ph2 = validate_success(
        api.create_pothole_verification(
            pothole_payload(
                project["id"], ticket["id"], station_label="STA 2+00",
                expected_utility_type="GAS",
            ),
            PROJECT_MANAGER,
        ),
        201,
    )
    validate_success(
        api.perform_pothole(
            ph2["id"], {"measured_depth_in": 67, "measured_offset_in": 12}, FOREMAN
        )
    )
    response = api.verify_pothole(ph2["id"], PROJECT_MANAGER)
    validate_error(response, ApiErrorId.ERR_POTHOLE_TOLERANCE_EXCEEDED, 422)

    # Mark the finding CONFLICT; a replacement at the same station supersedes.
    conflict = validate_success(api.mark_pothole_conflict(ph2["id"], PROJECT_MANAGER))
    assert conflict["status"] == "CONFLICT"

    ph3 = validate_success(
        api.create_pothole_verification(
            pothole_payload(
                project["id"], ticket["id"], station_label="STA 2+00",
                expected_utility_type="GAS", method="HAND_DIG",
            ),
            PROJECT_MANAGER,
        ),
        201,
    )
    assert ph3["status"] == "PLANNED"
    assert get_pothole(ph2["id"])["status"] == "SUPERSEDED"


def test_perform_on_verified_pothole_reports_state_before_safety(api):
    """PRD §2.10: "Sixth, the target resource must be in a valid from-state
    for the requested transition, and a resource in a terminal state rejects
    every action, else `ERR_INVALID_STATE`. Seventh come the safety and
    compliance gates, and they are sub-ordered: a stopped project surfaces
    `ERR_PROJECT_STOPPED` before any locate-ticket check; a missing or
    inactive locate surfaces `ERR_LOCATE_NOT_ACTIVE`"
    PRD §3.2: "Performing requires the ticket referenced by the verification
    to be `ACTIVE` (`ERR_LOCATE_NOT_ACTIVE`) and the project's posture to be
    `CLEAR` (`ERR_PROJECT_STOPPED`), and it moves the verification
    `PLANNED → PERFORMED`."

    Design: Difficulty/priority_pair_validation_conflict/pothole_perform_state_beats_safety
    """
    ctx = setup_project_with_active_ticket()
    pothole, ticket = ctx["pothole"], ctx["ticket"]
    assert pothole["status"] == "VERIFIED"

    # Expire the ticket (valid_until == 2026-08-31T00:00:00Z) so the safety
    # gate is also violated — the state violation must still win.
    advance_clock("2026-09-01T00:00:00Z")
    assert get_ticket(ticket["id"])["status"] == "EXPIRED"

    response = api.perform_pothole(
        pothole["id"], {"measured_depth_in": 60, "measured_offset_in": 12}, FOREMAN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_pothole(pothole["id"])["status"] == "VERIFIED"


def test_perform_with_expired_ticket_fires_safety_gate(api):
    """PRD §2.10: "Sixth, the target resource must be in a valid from-state
    for the requested transition, and a resource in a terminal state rejects
    every action, else `ERR_INVALID_STATE`. Seventh come the safety and
    compliance gates, and they are sub-ordered: a stopped project surfaces
    `ERR_PROJECT_STOPPED` before any locate-ticket check; a missing or
    inactive locate surfaces `ERR_LOCATE_NOT_ACTIVE`"
    PRD §3.2: "Performing requires the ticket referenced by the verification
    to be `ACTIVE` (`ERR_LOCATE_NOT_ACTIVE`) and the project's posture to be
    `CLEAR` (`ERR_PROJECT_STOPPED`), and it moves the verification
    `PLANNED → PERFORMED`."

    Design: Difficulty/priority_pair_validation_conflict/pothole_perform_state_beats_safety
    """
    ctx = setup_project_with_active_ticket()
    project, ticket = ctx["project"], ctx["ticket"]

    # A fresh PLANNED pothole (valid from-state for perform) after the ticket
    # has expired isolates the priority-7 safety gate.
    advance_clock("2026-09-01T00:00:00Z")
    assert get_ticket(ticket["id"])["status"] == "EXPIRED"
    pothole = validate_success(
        api.create_pothole_verification(
            pothole_payload(
                project["id"], ticket["id"], station_label="STA 9+00",
                expected_utility_type="GAS",
            ),
            PROJECT_MANAGER,
        ),
        201,
    )

    response = api.perform_pothole(
        pothole["id"], {"measured_depth_in": 60, "measured_offset_in": 12}, FOREMAN
    )
    validate_error(response, ApiErrorId.ERR_LOCATE_NOT_ACTIVE, 409)
    assert get_pothole(pothole["id"])["status"] == "PLANNED"
