"""Injury reports: severity-conditional holds, clearance aggregate gate, the
registration-cancellation/waitlist cascade, and clearance RBAC (PRD §3.7,
§3.8, §2.1)."""
from test_helpers import (
    FACILITY_MANAGER,
    REC_ADMIN,
    ApiErrorId,
    api_client,
    class_context,
    create_eligible_member,
    create_member,
    file_injury,
    register_for_class,
    season_game_context,
    set_clock,
    validate_error,
    validate_success,
)


def test_severe_report_suspends_and_cancels_future_registration():
    """PRD §3.7: "Severity `MODERATE` or `SEVERE` is a **hold report**: filing
    one moves the member `ACTIVE → SUSPENDED`, and the cascade continues —
    every class registration of the member in `REGISTERED` status whose class
    is `SCHEDULED` and starts after the logical now is cancelled, and each
    such cancellation runs the waitlist promotion of §3.8 on its class."

    Design: Difficulty/transitive_cascade/injury_hold_registration_promotion_cascade
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context(capacity=1)
    member_m = create_eligible_member("mm@x.edu", full_name="Mem M")
    reg_m = register_for_class(ctx["class"]["id"], member_m)
    assert reg_m["status"] == "REGISTERED"
    member_w = create_eligible_member("ww@x.edu", full_name="Mem W")
    reg_w = register_for_class(ctx["class"]["id"], member_w)
    assert reg_w["status"] == "WAITLISTED"  # capacity 1 overflowed

    set_clock("2026-09-01T09:00:00Z")  # before the 2026-09-08 class start
    file_injury(member_m["id"], severity="SEVERE", description="ACL tear")
    member_after = validate_success(api_client.get_member(
        member_m["id"], FACILITY_MANAGER))
    assert member_after["status"] == "SUSPENDED"
    reg_m_after = validate_success(api_client.get_class_registration(
        reg_m["id"], REC_ADMIN))
    assert reg_m_after["status"] == "CANCELLED"


def test_injury_cascade_promotes_waitlist_head_and_conserves_seat():
    """PRD §3.7: "Severity `MODERATE` or `SEVERE` is a **hold report**: filing
    one moves the member `ACTIVE → SUSPENDED`, and the cascade continues —
    every class registration of the member in `REGISTERED` status whose class
    is `SCHEDULED` and starts after the logical now is cancelled, and each
    such cancellation runs the waitlist promotion of §3.8 on its class."
    PRD §3.8: "Cancelling a `REGISTERED` entry decrements `registered_count`
    and then runs **waitlist promotion**: among the class's `WAITLISTED`
    registrations, the head is the one with the earliest registration
    `created_at`, ties broken by the candidate member's earlier `created_at`;
    the head is promoted to `REGISTERED`, decrementing `waitlist_count` by 1
    while `registered_count` returns to its prior value — the seat is handed
    off, and the two counts are conserved."

    Design: Difficulty/transitive_cascade/injury_hold_registration_promotion_cascade
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = class_context(capacity=1)
    member_m = create_eligible_member("mm@x.edu", full_name="Mem M")
    reg_m = register_for_class(ctx["class"]["id"], member_m)
    member_w = create_eligible_member("ww@x.edu", full_name="Mem W")
    reg_w = register_for_class(ctx["class"]["id"], member_w)
    assert reg_m["status"] == "REGISTERED"
    assert reg_w["status"] == "WAITLISTED"

    set_clock("2026-09-01T09:00:00Z")
    file_injury(member_m["id"], severity="SEVERE", description="ACL tear")
    reg_w_after = validate_success(api_client.get_class_registration(
        reg_w["id"], REC_ADMIN))
    assert reg_w_after["status"] == "REGISTERED", (
        "the waitlist head is promoted into the freed seat"
    )
    fclass = validate_success(api_client.get_fitness_class(
        ctx["class"]["id"], REC_ADMIN))
    assert fclass["registered_count"] == 1
    assert fclass["waitlist_count"] == 0


def test_injury_minor_does_not_suspend():
    """PRD §3.7: "Severity `MODERATE` or `SEVERE` is a **hold report**: filing
    one moves the member `ACTIVE → SUSPENDED`... A `MINOR` report imposes no
    hold."

    Design: Corner/state_machines/injury_minor_does_not_suspend
    """
    set_clock("2026-08-24T00:00:00Z")
    member = create_member("mm@x.edu", full_name="Mem M")
    report = file_injury(member["id"], severity="MINOR", description="bruise")
    assert report["status"] == "REPORTED"
    member_after = validate_success(api_client.get_member(
        member["id"], FACILITY_MANAGER))
    assert member_after["status"] == "ACTIVE"


def test_injury_partial_clear_keeps_suspension():
    """PRD §3.7: "A `RecAdmin` clears a `REPORTED` report, addressed by its
    `injury_report_id`, supplying a `clearance_note` that is recorded on the
    report as it moves to `CLEARED`; clearing a non-`REPORTED` report is
    `ERR_INVALID_STATE`. If, after clearing, no other report of the member
    remains `REPORTED` with hold severity, the member moves `SUSPENDED →
    ACTIVE`."

    Design: Corner/state_machines/injury_partial_clear_keeps_suspension
    """
    set_clock("2026-08-24T00:00:00Z")
    member = create_member("mm@x.edu", full_name="Mem M")
    report_1 = file_injury(member["id"], severity="SEVERE", description="acl")
    report_2 = file_injury(member["id"], severity="MODERATE",
                           description="concussion protocol")
    # Clearing the first of two hold reports leaves the hold in place.
    validate_success(api_client.clear_injury_report(
        report_1["id"], {"clearance_note": "pt done"}, REC_ADMIN))
    member_mid = validate_success(api_client.get_member(
        member["id"], REC_ADMIN))
    assert member_mid["status"] == "SUSPENDED"
    # Clearing the last hold report reinstates the member.
    cleared = validate_success(api_client.clear_injury_report(
        report_2["id"], {"clearance_note": "cleared"}, REC_ADMIN))
    assert cleared["status"] == "CLEARED"
    member_end = validate_success(api_client.get_member(
        member["id"], REC_ADMIN))
    assert member_end["status"] == "ACTIVE"
    # CLEARED is terminal for the report.
    resp = api_client.clear_injury_report(
        report_2["id"], {"clearance_note": "again"}, REC_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_error_injury_game_mismatch():
    """PRD §3.7: "A member or a `FacilityManager` files an `InjuryReport` with
    `member_id`, a `severity` of `MINOR`, `MODERATE`, or `SEVERE`, and a
    free-text `description`; an optional `game_id` gives game context, in
    which case the member must hold an `ACTIVE` roster entry on the home or
    away team of that game (otherwise `ERR_INJURY_GAME_MISMATCH`)."

    Design: Corner/errors/error_injury_game_mismatch
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_game_context()
    outsider = create_member("mx@x.edu", full_name="Mem X")
    resp = api_client.create_injury_report(
        {"member_id": outsider["id"], "severity": "MINOR",
         "description": "spectator trip", "game_id": ctx["game"]["id"]},
        FACILITY_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INJURY_GAME_MISMATCH)


def test_facility_manager_cannot_clear_injury():
    """PRD §2.1: "`RecAdmin` is the campus recreation department administrator
    and owns configuration entities (member creation, leagues, facilities,
    staff, equipment pools, lockers, fitness classes), authoritative score and
    dispute resolution, medical clearance of injury reports, and control of
    the logical clock."
    PRD §2.1: "If the role is valid but not permitted for the endpoint — or an
    entity-backed ownership check fails — the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/facility_manager_cannot_clear_injury
    """
    member = create_member("mm@x.edu", full_name="Mem M")
    report = file_injury(member["id"], severity="MINOR", description="bruise")
    resp = api_client.clear_injury_report(
        report["id"], {"clearance_note": "self-clear attempt"},
        FACILITY_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    report_after = validate_success(api_client.get_injury_report(
        report["id"], REC_ADMIN))
    assert report_after["status"] == "REPORTED"
