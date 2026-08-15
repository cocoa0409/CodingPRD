"""RBAC and entity-backed ownership checks (PRD §2.1)."""
from test_helpers import (
    ApiErrorId,
    create_participant,
    create_registration,
    create_registration_payload,
    create_workshop_payload,
    make_coach_headers,
    make_participant_headers,
    set_clock,
    setup_workshop_scenario,
    validate_error,
    validate_success,
)


def test_participant_cannot_create_workshop_returns_403(api, admin_headers):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    — or that fails an entity-backed ownership check — is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." PRD §2.1: "it alone may create and retire
    curriculum modules, create coaches and drive certification, suspension,
    and reinstatement, create participants and clear restrictions or exit them,
    schedule, reschedule, and cancel workshops".

    Design: Corner/rbac/participant_cannot_create_workshop_returns_403
    """
    participant = create_participant(admin_headers, full_name="PRB", email="prb@test.org")
    ctx = setup_workshop_scenario(
        admin_headers,
        module_overrides=dict(module_code="RB-100", session_count=1,
                              completion_threshold=1),
    )
    resp = api.create_workshop(
        create_workshop_payload(ctx["module"]["id"], ctx["coach"]["id"]),
        make_participant_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_unassigned_coach_cannot_mark_attendance_returns_403(api, admin_headers):
    """PRD §2.1: "A coach may mark attendance only on workshops assigned to
    them (the workshop's `coach_id` must equal `X-User-ID`)".

    Design: Corner/rbac/unassigned_coach_cannot_mark_attendance_returns_403
    """
    module_ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="OW-100", session_count=1,
                              completion_threshold=1),
    )
    from test_helpers import create_certified_coach

    owner_coach = module_ctx["coach"]
    other_coach = create_certified_coach(admin_headers, full_name="CO2",
                                         email="co2@test.org")
    participant = create_participant(admin_headers, full_name="POW", email="pow@test.org")
    reg = create_registration(
        module_ctx["workshop"]["id"], participant["id"], admin_headers
    )
    # Advance past the workshop start so only ownership can fail.
    set_clock("2026-08-11T00:00:00Z", admin_headers)
    resp = api.mark_attendance(
        reg["id"], {"outcome": "ATTENDED"}, make_coach_headers(other_coach["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_participant_cannot_cancel_others_registration_returns_403(api, admin_headers):
    """PRD §2.1: "A participant may register only for themselves (the
    `participant_id` in the registration payload must equal `X-User-ID`), may
    cancel only their own registrations".

    Design: Corner/rbac/participant_cannot_cancel_others_registration_returns_403
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="OC-100", session_count=1,
                              completion_threshold=1),
    )
    p1 = create_participant(admin_headers, full_name="POC1", email="poc1@test.org")
    p2 = create_participant(admin_headers, full_name="POC2", email="poc2@test.org")
    reg = create_registration(ctx["workshop"]["id"], p1["id"], admin_headers)
    resp = api.cancel_registration(reg["id"], make_participant_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_participant_self_registration_allowed(api, admin_headers):
    """PRD §2.1: "A participant may register only for themselves (the
    `participant_id` in the registration payload must equal `X-User-ID`)".

    Design: Corner/rbac/participant_self_registration_allowed
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        module_overrides=dict(module_code="SR-100", session_count=1,
                              completion_threshold=1),
    )
    participant = create_participant(admin_headers, full_name="PSR", email="psr@test.org")
    registration = validate_success(
        api.create_registration(
            create_registration_payload(ctx["workshop"]["id"], participant["id"]),
            make_participant_headers(participant["id"]),
        ),
        expected_status=201,
    )
    assert registration["status"] == "REGISTERED"
