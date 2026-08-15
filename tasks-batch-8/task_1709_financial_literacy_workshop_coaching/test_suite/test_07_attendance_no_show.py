"""No-show strike boundary and attendance temporal guard (PRD §3.3, §3.2)."""
from test_helpers import (
    ApiErrorId,
    create_participant,
    create_registration,
    create_registration_payload,
    create_workshop,
    set_clock,
    setup_workshop_scenario,
    validate_error,
    validate_success,
)


def _three_workshop_no_show_setup(api, admin_headers):
    """Participant REGISTERED on three workshops (2026-08-02/03/04) plus a
    fourth future workshop (2026-08-06) for the post-restriction probe."""
    ctx = setup_workshop_scenario(
        admin_headers, capacity=10,
        start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z",
        module_overrides=dict(module_code="BX-601", session_count=3,
                              completion_threshold=1),
    )
    module, coach = ctx["module"], ctx["coach"]
    participant = create_participant(admin_headers, full_name="P NS",
                                     email="pns@test.org")
    w2 = create_workshop(module["id"], coach["id"], admin_headers,
                         start_at="2026-08-03T10:00:00Z",
                         end_at="2026-08-03T11:00:00Z")
    w3 = create_workshop(module["id"], coach["id"], admin_headers,
                         start_at="2026-08-04T10:00:00Z",
                         end_at="2026-08-04T11:00:00Z")
    w4 = create_workshop(module["id"], coach["id"], admin_headers,
                         start_at="2026-08-06T10:00:00Z",
                         end_at="2026-08-06T11:00:00Z")
    regs = [
        create_registration(ctx["workshop"]["id"], participant["id"], admin_headers),
        create_registration(w2["id"], participant["id"], admin_headers),
        create_registration(w3["id"], participant["id"], admin_headers),
    ]
    set_clock("2026-08-05T00:00:00Z", admin_headers)
    return participant, regs, w4


def test_two_no_shows_leave_participant_active(api, admin_headers):
    """PRD §3.3: "Every `NO_SHOW` attendance mark increments the participant's
    `no_show_count` by 1, and the moment that count reaches 3 the participant
    flips from `ACTIVE` to `RESTRICTED`; the boundary is exact, so two strikes
    do nothing and the third strikes."

    Design: Difficulty/boundary_precision_check/no_show_restriction_at_exactly_three
    """
    participant, regs, _w4 = _three_workshop_no_show_setup(api, admin_headers)
    for reg in regs[:2]:
        validate_success(
            api.mark_attendance(reg["id"], {"outcome": "NO_SHOW"}, admin_headers)
        )
    mid = validate_success(api.get_participant(participant["id"], admin_headers))
    assert mid["no_show_count"] == 2
    assert mid["status"] == "ACTIVE", "two strikes must not flip the participant"


def test_third_no_show_flips_participant_restricted_and_blocks_registration(
    api, admin_headers
):
    """PRD §3.3: "the moment that count reaches 3 the participant flips from
    `ACTIVE` to `RESTRICTED`". PRD §3.3: "A `RESTRICTED` participant is blocked
    from new registrations with `ERR_PARTICIPANT_RESTRICTED`".

    Design: Difficulty/boundary_precision_check/no_show_restriction_at_exactly_three
    """
    participant, regs, w4 = _three_workshop_no_show_setup(api, admin_headers)
    for reg in regs:
        validate_success(
            api.mark_attendance(reg["id"], {"outcome": "NO_SHOW"}, admin_headers)
        )
    end = validate_success(api.get_participant(participant["id"], admin_headers))
    assert end["no_show_count"] == 3
    assert end["status"] == "RESTRICTED", "exactly three strikes (>=) must flip"

    resp = api.create_registration(
        create_registration_payload(w4["id"], participant["id"]), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_RESTRICTED)


def test_mark_attendance_before_workshop_start_returns_409(api, admin_headers):
    """PRD §3.2: "Marking before the start is rejected with
    `ERR_WORKSHOP_NOT_STARTED`".

    Design: Corner/validations/mark_attendance_before_workshop_start_returns_409
    """
    ctx = setup_workshop_scenario(
        admin_headers, capacity=5,
        start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T11:00:00Z",
        module_overrides=dict(module_code="NS-100", session_count=1,
                              completion_threshold=1),
    )
    participant = create_participant(admin_headers, full_name="PNS",
                                     email="pns2@test.org")
    reg = create_registration(ctx["workshop"]["id"], participant["id"], admin_headers)
    # Logical clock is still the default 2026-08-01, before the 2026-08-10 start.
    resp = api.mark_attendance(reg["id"], {"outcome": "ATTENDED"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_WORKSHOP_NOT_STARTED)
