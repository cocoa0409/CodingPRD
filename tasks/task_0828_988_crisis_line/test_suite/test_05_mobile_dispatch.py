"""Mobile dispatch: dual-variant priority scoring, preconditions, window buffer, OCC."""
from test_helpers import (
    api_client as api,
    validate_success, validate_error,
    create_dispatch_payload, TEST_USERS,
    create_dispatch_pending_contact, create_screened_contact, create_team,
    set_clock, setup_dispatch, drive_dispatch_to_completed, current_team_version,
)

SUP = TEST_USERS["supervisor_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── dual_variant_calc / dispatch_priority_estimated_vs_reassessed_diverge ─────

def test_priority_estimated_pinned_at_creation():
    """PRD §3.5: "take the elapsed time from the contact's `created_at` to the applicable clock reading expressed as whole minutes (discarding any fractional minute), divide that by 10 taking only the whole-number quotient (discarding the remainder), cap that quotient at 5, and multiply by 4."
    PRD §3.5: "The `ESTIMATED` variant, pinned into `priority_score_estimated` at dispatch creation, uses the contact's `risk_band` (its disposition-time band) as the band and measures the wait at the creation-time clock."

    HIGH band weight 60 + wait floor(25/10)=2 capped -> 2*4=8 + repeat 0 = 68.

    Design: Difficulty/dual_variant_calc/dispatch_priority_estimated_vs_reassessed_diverge
    """
    contact = create_dispatch_pending_contact("dpr-01")  # created at clock 00:00, band HIGH
    team = create_team(name="Team A")
    set_clock("2026-03-01T00:25:00Z")
    res = api.create_dispatch(create_dispatch_payload(
        contact["id"], team["id"], team["version"],
        window_start="2026-03-01T00:30:00Z", window_end="2026-03-01T01:00:00Z",
        requested_acuity="HIGH"), DISPATCHER)
    d = validate_success(res, 201)
    assert d["priority_score_estimated"] == 68, (
        f"expected ESTIMATED 68, got {d['priority_score_estimated']}"
    )


def test_priority_reassessed_recomputed_on_scene():
    """PRD §3.5: "The `REASSESSED` variant, computed when the team arrives on scene and stored into `priority_score_reassessed`, uses the `on_scene_acuity` reported on arrival as the band and measures the wait at the later on-scene clock reading; before the on-scene arrival, `priority_score_reassessed` is null."

    HIGH band weight 60 + wait floor(55/10)=5 capped -> 5*4=20 + repeat 0 = 80.

    Design: Difficulty/dual_variant_calc/dispatch_priority_estimated_vs_reassessed_diverge
    """
    contact = create_dispatch_pending_contact("dpr-02")  # created at clock 00:00, band HIGH
    team = create_team(name="Team A")
    set_clock("2026-03-01T00:25:00Z")
    d = validate_success(api.create_dispatch(create_dispatch_payload(
        contact["id"], team["id"], team["version"],
        window_start="2026-03-01T00:30:00Z", window_end="2026-03-01T01:00:00Z",
        requested_acuity="HIGH"), DISPATCHER), 201)
    validate_success(api.dispatch_state(d["id"], {"to_status": "EN_ROUTE"}, DISPATCHER), 200)
    set_clock("2026-03-01T00:55:00Z")
    res = api.dispatch_state(d["id"], {"to_status": "ON_SCENE", "on_scene_acuity": "HIGH"}, DISPATCHER)
    on_scene = validate_success(res, 200)
    assert on_scene["priority_score_reassessed"] == 80, (
        f"expected REASSESSED 80, got {on_scene['priority_score_reassessed']}"
    )


# ─── cross_entity_state_dependency / dispatch_create_requires_contact_dispatch_pending ─

def test_dispatch_create_requires_contact_dispatch_pending():
    """PRD §3.5: "Dispatch creation is subject to a cascade of preconditions beyond the OCC check: the contact must be in `DISPATCH_PENDING`, else `ERR_CONTACT_NOT_DISPATCH_PENDING`"

    Design: Difficulty/cross_entity_state_dependency/dispatch_create_requires_contact_dispatch_pending
    """
    contact = create_screened_contact("ce-a-01", band="HIGH")  # SCREENED, never disposed
    team = create_team(name="Team E")
    res = api.create_dispatch(create_dispatch_payload(
        contact["id"], team["id"], team["version"], requested_acuity="HIGH"), DISPATCHER)
    validate_error(res, "ERR_CONTACT_NOT_DISPATCH_PENDING", expected_status=409)


def test_dispatch_create_succeeds_when_contact_dispatch_pending():
    """PRD §3.5: "When a contact sits in `DISPATCH_PENDING`, a dispatcher requests a mobile dispatch, naming the `contact_id`, the `team_id`, the requested on-scene window via `window_start` and `window_end`, a `requested_acuity` of `LOW`, `MODERATE`, `HIGH`, or `IMMINENT`, and the OCC guard `expected_team_version`."
    PRD §3.5: "The dispatch is created in `REQUESTED`; the owning team's `active_dispatch_count` is incremented and its `version` is incremented; and the dispatch's `priority_score_estimated` is pinned at creation."

    Positive control for the DISPATCH_PENDING precondition.

    Design: Difficulty/cross_entity_state_dependency/dispatch_create_requires_contact_dispatch_pending
    """
    contact = create_dispatch_pending_contact("ce-a-02")
    team = create_team(name="Team E2")
    res = api.create_dispatch(create_dispatch_payload(
        contact["id"], team["id"], team["version"], requested_acuity="HIGH"), DISPATCHER)
    d = validate_success(res, 201)
    assert d["status"] == "REQUESTED", f"expected REQUESTED, got {d['status']}"


# ─── resource_temporal_overlap / team_dispatch_window_buffer_conflict ──────────

def test_dispatch_within_turnaround_buffer_conflicts():
    """PRD §3.5: "the new dispatch conflicts with any other dispatch for the same team whose status is `REQUESTED`, `EN_ROUTE`, `ON_SCENE`, or `COMPLETED` when the new window's start is earlier than that other window's end plus 15 minutes and, at the same time, that other window's start is earlier than the new window's end plus 15 minutes; such a collision is rejected with `ERR_TEAM_WINDOW_CONFLICT`."

    New start 01:10 < COMPLETED window end 01:00 + 15min = 01:15 -> conflict.

    Design: Difficulty/resource_temporal_overlap/team_dispatch_window_buffer_conflict
    """
    _, team, d1 = setup_dispatch("to-a-1")  # D1 window [00:30, 01:00)
    drive_dispatch_to_completed(d1["id"])
    contact2 = create_dispatch_pending_contact("to-a-2")
    set_clock("2026-03-01T01:05:00Z")
    tv = current_team_version(team["id"])
    res = api.create_dispatch(create_dispatch_payload(
        contact2["id"], team["id"], tv,
        window_start="2026-03-01T01:10:00Z", window_end="2026-03-01T01:30:00Z",
        requested_acuity="HIGH"), DISPATCHER)
    validate_error(res, "ERR_TEAM_WINDOW_CONFLICT", expected_status=409)


def test_dispatch_exactly_at_turnaround_buffer_boundary_allowed():
    """PRD §3.5: "the new dispatch conflicts with any other dispatch for the same team whose status is `REQUESTED`, `EN_ROUTE`, `ON_SCENE`, or `COMPLETED` when the new window's start is earlier than that other window's end plus 15 minutes and, at the same time, that other window's start is earlier than the new window's end plus 15 minutes; such a collision is rejected with `ERR_TEAM_WINDOW_CONFLICT`."

    New start 01:15 is NOT earlier than end 01:00 + 15min = 01:15, so no collision -> allowed.

    Design: Difficulty/resource_temporal_overlap/team_dispatch_window_buffer_conflict
    """
    _, team, d1 = setup_dispatch("to-a-3")  # D1 window [00:30, 01:00)
    drive_dispatch_to_completed(d1["id"])
    contact2 = create_dispatch_pending_contact("to-a-4")
    tv = current_team_version(team["id"])
    res = api.create_dispatch(create_dispatch_payload(
        contact2["id"], team["id"], tv,
        window_start="2026-03-01T01:15:00Z", window_end="2026-03-01T01:35:00Z",
        requested_acuity="HIGH"), DISPATCHER)
    d = validate_success(res, 201)
    assert d["status"] == "REQUESTED", f"expected REQUESTED, got {d['status']}"


# ─── Corner / dispatch_off_shift_team_returns_error ────────────────────────────

def test_dispatch_off_shift_team_rejected():
    """PRD §3.5: "a team that is `OFF_SHIFT`, or a request whose window is not contained within `[shift_start, shift_end)`, is rejected with `ERR_TEAM_OFF_SHIFT`."

    Design: Corner/validations/dispatch_off_shift_team_returns_error
    """
    contact = create_dispatch_pending_contact("vd-c-01")
    team = create_team(name="Team Off", status="OFF_SHIFT")
    res = api.create_dispatch(create_dispatch_payload(
        contact["id"], team["id"], team["version"], requested_acuity="HIGH"), DISPATCHER)
    validate_error(res, "ERR_TEAM_OFF_SHIFT", expected_status=409)


# ─── Corner / dispatch_team_at_capacity_returns_error ──────────────────────────

def test_dispatch_team_at_capacity_rejected():
    """PRD §3.5: "Separately, the team must have a free concurrent slot — that is, its `active_dispatch_count` must be below its `capacity`; a team already carrying `capacity` active dispatches is rejected with `ERR_TEAM_AT_CAPACITY`."

    Design: Corner/validations/dispatch_team_at_capacity_returns_error
    """
    _, team, _ = setup_dispatch("vd-d-1")  # capacity 1, one REQUESTED dispatch active
    contact2 = create_dispatch_pending_contact("vd-d-2")
    tv = current_team_version(team["id"])
    res = api.create_dispatch(create_dispatch_payload(
        contact2["id"], team["id"], tv,
        window_start="2026-03-01T05:00:00Z", window_end="2026-03-01T05:30:00Z",
        requested_acuity="HIGH"), DISPATCHER)
    validate_error(res, "ERR_TEAM_AT_CAPACITY", expected_status=409)


# ─── Corner / dispatch_create_unknown_contact_returns_not_found ────────────────

def test_dispatch_unknown_contact_returns_not_found():
    """PRD §2.8: "existence of every referenced resource — each path id and each foreign key in the body, checked left to right, yielding the matching not-found error"

    Design: Corner/validations/dispatch_create_unknown_contact_returns_not_found
    """
    team = create_team(name="Team NF")
    res = api.create_dispatch(create_dispatch_payload(
        "00000000-0000-0000-0000-000000000000", team["id"], team["version"],
        requested_acuity="HIGH"), DISPATCHER)
    validate_error(res, "ERR_CONTACT_NOT_FOUND", expected_status=404)


# ─── Corner / dispatch_stale_team_version_returns_412 ──────────────────────────

def test_dispatch_stale_team_version_returns_412():
    """PRD §2.7: "Likewise, creating a mobile dispatch must carry `expected_team_version`, set to the `version` of the target `MobileCrisisTeam` the client last read; if it does not equal the team's current `version` — because another writer has reserved or released a slot on that team and advanced its version, leaving the current writer's view of remaining capacity stale — the create is rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting/dispatch_stale_team_version_returns_412
    """
    team = create_team(name="Team OCC", capacity=2)
    stale_version = team["version"]
    c1 = create_dispatch_pending_contact("occ-t-1")
    validate_success(api.create_dispatch(create_dispatch_payload(
        c1["id"], team["id"], stale_version,
        window_start="2026-03-01T00:30:00Z", window_end="2026-03-01T01:00:00Z",
        requested_acuity="HIGH"), DISPATCHER), 201)  # advances team.version 1 -> 2
    c2 = create_dispatch_pending_contact("occ-t-2")
    res = api.create_dispatch(create_dispatch_payload(
        c2["id"], team["id"], stale_version,
        window_start="2026-03-01T03:00:00Z", window_end="2026-03-01T03:30:00Z",
        requested_acuity="HIGH"), DISPATCHER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
