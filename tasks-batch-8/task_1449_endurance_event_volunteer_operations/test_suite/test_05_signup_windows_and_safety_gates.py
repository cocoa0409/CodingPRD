"""Signup creation gates: windows, safety gauntlet, duplication, overlap,
and the fixed validation priority order (PRD §3.5, §2.10, §2.1).
"""
import pytest

from test_helpers import (
    api_client, ApiErrorId, C, TEST_USERS,
    make_volunteer_headers,
    validate_success, validate_error, validate_paginated,
    set_clock,
    setup_event_with_shift, add_segment, add_shift, add_role,
    register_volunteer, register_eligible_volunteer,
    request_signup, approve_signup, create_confirmed_signup,
    create_signup_payload, create_shift_payload,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Signup window phases (PRD §3.5)
# ---------------------------------------------------------------------------

def test_early_access_window_restricts_non_returning(api):
    """PRD §3.5: "During the early-access window — from `early_access_opens_at`
    inclusive to `signup_opens_at` exclusive — only returning volunteers,
    those with `is_returning` true, may create signups; anyone else is
    rejected with `ERR_EARLY_ACCESS_RESTRICTED`."

    Design: Corner/validations/early_access_window_restricts_non_returning
    """
    ctx = setup_event_with_shift(clock=C.IN_EARLY_ACCESS_WINDOW, publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    v_new = register_eligible_volunteer(ev, full_name="V New", date_of_birth="2000-01-01")
    v_ret = register_eligible_volunteer(ev, full_name="V Ret", date_of_birth="2000-01-02",
                                        is_returning=True)
    blocked = api_client.create_signup(
        create_signup_payload(v_new["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_EARLY_ACCESS_RESTRICTED)
    allowed = api_client.create_signup(
        create_signup_payload(v_ret["id"], ctx["shift"]["id"]), COORDINATOR)
    sg = validate_success(allowed, expected_status=201)
    assert sg["status"] == "REQUESTED"


def test_signup_window_closed_after_closes(api):
    """PRD §3.5: "Before `early_access_opens_at`, and from `signup_closes_at`
    onward, creation is rejected with `ERR_SIGNUP_WINDOW_CLOSED`."

    Design: Corner/validations/signup_window_closed_after_closes
    """
    ctx = setup_event_with_shift(publish=True)
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    set_clock(C.AFTER_SIGNUP_CLOSES)
    resp = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SIGNUP_WINDOW_CLOSED)


# ---------------------------------------------------------------------------
# Safety gauntlet gates in isolation (PRD §3.5)
# ---------------------------------------------------------------------------

def test_signup_safety_gates_rejected(api):
    """PRD §3.5: "the role's `required_skill`, when not `NONE`, must appear in
    the volunteer's `skill_tags` (`ERR_REQUIRED_SKILL_MISSING`); and the
    role's training gate must be current per §3.4 (`ERR_TRAINING_NOT_CURRENT`)."

    Design: Corner/errors/signup_safety_gates_rejected
    """
    ctx = setup_event_with_shift(publish=True, role_overrides={
        "role_code": "MED", "title": "Medical Aid", "min_age_years": 18,
        "required_skill": "MEDICAL"})
    ev, seg = ctx["event"]["id"], ctx["segment"]
    role_trg = add_role(ev, role_code="TRG", title="Safety Marshal",
                        min_age_years=16, required_training_module="SAFETY_BRIEFING")
    shift_trg = add_shift(ev, role_trg["id"], seg["id"],
                          start_at="2026-10-04T12:00:00Z",
                          end_at="2026-10-04T15:00:00Z",
                          required_headcount=1)
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    missing_skill = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(missing_skill, ApiErrorId.ERR_REQUIRED_SKILL_MISSING)
    missing_training = api_client.create_signup(
        create_signup_payload(vol["id"], shift_trg["id"]), COORDINATOR)
    validate_error(missing_training, ApiErrorId.ERR_TRAINING_NOT_CURRENT)


# ---------------------------------------------------------------------------
# Duplicate rule (PRD §3.5)
# ---------------------------------------------------------------------------

def test_duplicate_signup_same_shift_rejected(api):
    """PRD §3.5: "a volunteer may hold at most one signup in `REQUESTED`,
    `WAITLISTED`, `APPROVED`, `CONFIRMED`, or `CHECKED_IN` status on the same
    shift; a second active signup is rejected with `ERR_DUPLICATE_SIGNUP`."

    Design: Corner/validations/duplicate_signup_same_shift_rejected
    """
    ctx = setup_event_with_shift(publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg1 = request_signup(vol["id"], ctx["shift"]["id"])
    dup = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_SIGNUP)
    validate_success(api_client.cancel_signup(sg1["id"], make_volunteer_headers(vol["id"])))
    fresh = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["shift"]["id"]), COORDINATOR)
    sg2 = validate_success(fresh, expected_status=201)
    assert sg2["status"] == "REQUESTED", "a CANCELLED signup is terminal and must not block"


# ---------------------------------------------------------------------------
# Volunteer overlap geometry (PRD §3.5)
# ---------------------------------------------------------------------------

def _setup_overlap_course(api):
    """Two segments and four shifts: S1 07:00-11:00 (A), S2 11:00-13:00 (A,
    adjacent to S1), S3 12:45-14:00 (B, 15-minute gap after S2), S4
    13:30-15:00 (B, exactly a 30-minute gap after S2)."""
    ctx = setup_event_with_shift(
        publish=True,
        segment_overrides={"segment_code": "SEG-A", "mile_start": 5, "mile_end": 10},
        shift_overrides={"start_at": "2026-10-04T07:00:00Z",
                         "end_at": "2026-10-04T11:00:00Z",
                         "required_headcount": 1})
    ev = ctx["event"]["id"]
    seg_b = add_segment(ev, segment_code="SEG-B", mile_start=10, mile_end=15,
                        terrain_type="TRAIL")
    s2 = add_shift(ev, ctx["role"]["id"], ctx["segment"]["id"],
                   start_at="2026-10-04T11:00:00Z", end_at="2026-10-04T13:00:00Z",
                   required_headcount=1)
    s3 = add_shift(ev, ctx["role"]["id"], seg_b["id"],
                   start_at="2026-10-04T12:45:00Z", end_at="2026-10-04T14:00:00Z",
                   required_headcount=1)
    s4 = add_shift(ev, ctx["role"]["id"], seg_b["id"],
                   start_at="2026-10-04T13:30:00Z", end_at="2026-10-04T15:00:00Z",
                   required_headcount=1)
    ctx.update({"seg_b": seg_b, "s2": s2, "s3": s3, "s4": s4})
    return ctx


def test_overlap_same_segment_adjacency_and_exact_buffer_pass(api):
    """PRD §3.5: "When the two shifts cover different segments, a thirty-minute
    transition buffer applies; on the same segment the buffer is zero."
    PRD §3.5: "Back-to-back shifts on the same segment are allowed — an
    existing shift ending exactly when the candidate begins is not an overlap —
    while changing segments always demands a strict thirty-minute gap."

    Design: Difficulty/resource_temporal_overlap/volunteer_shift_buffer_overlap
    """
    ctx = _setup_overlap_course(api)
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg1 = request_signup(vol["id"], ctx["shift"]["id"])
    approve_signup(sg1["id"])
    sg2 = request_signup(vol["id"], ctx["s2"]["id"])
    assert sg2["status"] == "REQUESTED", "same-segment back-to-back adjacency is legal"
    approve_signup(sg2["id"])
    resp = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["s4"]["id"]), COORDINATOR)
    sg4 = validate_success(resp, expected_status=201)
    assert sg4["status"] == "REQUESTED", \
        "an exact thirty-minute cross-segment gap passes at the boundary"


def test_overlap_cross_segment_inside_buffer_rejected(api):
    """PRD §3.5: "An overlap exists when the candidate's `start_at` falls
    before the existing shift's `end_at` plus the buffer and, symmetrically,
    the existing shift's `start_at` falls before the candidate's `end_at` plus
    the buffer; a violation is rejected with `ERR_SHIFT_TIME_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/volunteer_shift_buffer_overlap
    """
    ctx = _setup_overlap_course(api)
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg1 = request_signup(vol["id"], ctx["shift"]["id"])
    approve_signup(sg1["id"])
    sg2 = request_signup(vol["id"], ctx["s2"]["id"])
    approve_signup(sg2["id"])
    resp = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["s3"]["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SHIFT_TIME_OVERLAP)


# ---------------------------------------------------------------------------
# Validation priority pairs (PRD §2.10)
# ---------------------------------------------------------------------------

def test_priority_min_age_beats_window_closed(api):
    """PRD §2.10: "The server evaluates checks in the following fixed order,
    returning the first failure and never evaluating later gates for that
    request:"
    PRD §2.10: "5. Minimum age (`ERR_MIN_AGE_NOT_MET`)."
    PRD §2.10: "8. Temporal windows: the signup window
    (`ERR_SIGNUP_WINDOW_CLOSED`, `ERR_EARLY_ACCESS_RESTRICTED`), the check-in
    window (`ERR_CHECKIN_WINDOW_INVALID`), the confirmation deadline
    (`ERR_CONFIRM_DEADLINE_PASSED`), and the no-show grace period
    (`ERR_NO_SHOW_GRACE_NOT_PASSED`)."

    Design: Difficulty/priority_pair_validation_conflict/create_safety_beats_temporal_underage_before_window
    """
    ctx = setup_event_with_shift(clock=C.CLOCK_STARTUP_DEFAULT, publish=True,
                                 role_overrides={"min_age_years": 18})
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V Young", date_of_birth="2008-10-05")
    assert vol["age_years_on_event"] == 17, "one day short of the 18th birthday on race day"
    resp = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_MIN_AGE_NOT_MET)


def test_priority_min_age_beats_window_closed_no_row_created(api):
    """PRD §3.5: "the volunteer's `age_years_on_event` must be at least the
    role's `min_age_years` (`ERR_MIN_AGE_NOT_MET`)"
    PRD §2.10: "5. Minimum age (`ERR_MIN_AGE_NOT_MET`)."

    Design: Difficulty/priority_pair_validation_conflict/create_safety_beats_temporal_underage_before_window
    """
    ctx = setup_event_with_shift(clock=C.CLOCK_STARTUP_DEFAULT, publish=True,
                                 role_overrides={"min_age_years": 18})
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V Young", date_of_birth="2008-10-05")
    resp = api_client.create_signup(
        create_signup_payload(vol["id"], ctx["shift"]["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_MIN_AGE_NOT_MET)
    listed, meta = validate_paginated(api_client.list_signups(
        COORDINATOR, params={"volunteer_id": vol["id"]}))
    assert listed == [] and meta["total_count"] == 0, \
        "the rejected create must not persist a signup row"


def test_priority_window_closed_beats_overlap(api):
    """PRD §2.10: "8. Temporal windows: the signup window
    (`ERR_SIGNUP_WINDOW_CLOSED`, `ERR_EARLY_ACCESS_RESTRICTED`), the check-in
    window (`ERR_CHECKIN_WINDOW_INVALID`), the confirmation deadline
    (`ERR_CONFIRM_DEADLINE_PASSED`), and the no-show grace period
    (`ERR_NO_SHOW_GRACE_NOT_PASSED`)."
    PRD §2.10: "9. Constraint satisfaction: volunteer shift-time overlap
    (`ERR_SHIFT_TIME_OVERLAP`), segment mile overlap
    (`ERR_SEGMENT_MILE_OVERLAP`), per-event code uniqueness, one active signup
    per volunteer per shift (`ERR_DUPLICATE_SIGNUP`), one training record per
    volunteer per module (`ERR_DUPLICATE_TRAINING_RECORD`), one captain per
    shift (`ERR_CAPTAIN_SLOT_TAKEN`), one issued credential per signup
    (`ERR_CREDENTIAL_ALREADY_ISSUED`), the `inventory_id`-versus-`kind`
    requirement, and datetime ordering (all remaining cases as
    `ERR_INVALID_REQUEST`)."

    Design: Difficulty/priority_pair_validation_conflict/create_temporal_beats_constraint_window_vs_overlap
    """
    ctx = setup_event_with_shift(
        publish=True,
        segment_overrides={"segment_code": "SEG-A", "mile_start": 5, "mile_end": 10},
        shift_overrides={"start_at": "2026-10-04T07:00:00Z",
                         "end_at": "2026-10-04T11:00:00Z",
                         "required_headcount": 1})
    ev = ctx["event"]["id"]
    seg_b = add_segment(ev, segment_code="SEG-B", mile_start=10, mile_end=15,
                        terrain_type="TRAIL")
    s2 = add_shift(ev, ctx["role"]["id"], seg_b["id"],
                   start_at="2026-10-04T10:00:00Z", end_at="2026-10-04T12:00:00Z",
                   required_headcount=1)
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg1 = request_signup(vol["id"], ctx["shift"]["id"])
    approve_signup(sg1["id"])
    set_clock(C.AFTER_SIGNUP_CLOSES)
    resp = api_client.create_signup(
        create_signup_payload(vol["id"], s2["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SIGNUP_WINDOW_CLOSED)


def test_priority_window_closed_beats_overlap_no_row_created(api):
    """PRD §3.5: "Before `early_access_opens_at`, and from `signup_closes_at`
    onward, creation is rejected with `ERR_SIGNUP_WINDOW_CLOSED`."
    PRD §2.10: "8. Temporal windows: the signup window
    (`ERR_SIGNUP_WINDOW_CLOSED`, `ERR_EARLY_ACCESS_RESTRICTED`), the check-in
    window (`ERR_CHECKIN_WINDOW_INVALID`), the confirmation deadline
    (`ERR_CONFIRM_DEADLINE_PASSED`), and the no-show grace period
    (`ERR_NO_SHOW_GRACE_NOT_PASSED`)."

    Design: Difficulty/priority_pair_validation_conflict/create_temporal_beats_constraint_window_vs_overlap
    """
    ctx = setup_event_with_shift(
        publish=True,
        segment_overrides={"segment_code": "SEG-A", "mile_start": 5, "mile_end": 10},
        shift_overrides={"start_at": "2026-10-04T07:00:00Z",
                         "end_at": "2026-10-04T11:00:00Z",
                         "required_headcount": 1})
    ev = ctx["event"]["id"]
    seg_b = add_segment(ev, segment_code="SEG-B", mile_start=10, mile_end=15,
                        terrain_type="TRAIL")
    s2 = add_shift(ev, ctx["role"]["id"], seg_b["id"],
                   start_at="2026-10-04T10:00:00Z", end_at="2026-10-04T12:00:00Z",
                   required_headcount=1)
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg1 = request_signup(vol["id"], ctx["shift"]["id"])
    approve_signup(sg1["id"])
    set_clock(C.AFTER_SIGNUP_CLOSES)
    resp = api_client.create_signup(
        create_signup_payload(vol["id"], s2["id"]), COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SIGNUP_WINDOW_CLOSED)
    listed, meta = validate_paginated(api_client.list_signups(
        COORDINATOR, params={"volunteer_id": vol["id"], "shift_id": s2["id"]}))
    assert listed == [] and meta["total_count"] == 0, \
        "the rejected create must not persist a signup row for (volunteer, S2)"


# ---------------------------------------------------------------------------
# Role and ownership checks (PRD §2.1)
# ---------------------------------------------------------------------------

def test_volunteer_cannot_approve_signup_forbidden(api):
    """PRD §2.1: "Each endpoint admits a fixed set of roles (enumerated in
    §4); a caller whose role is not in the endpoint's set is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/volunteer_cannot_approve_signup_forbidden
    """
    ctx = setup_event_with_shift(publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg = request_signup(vol["id"], ctx["shift"]["id"])
    resp = api_client.approve_signup(sg["id"], make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = validate_success(api_client.get_signup(sg["id"], COORDINATOR))
    assert after["status"] == "REQUESTED"


def test_volunteer_cannot_confirm_others_signup(api):
    """PRD §3.5: "Confirmation is personal: only the volunteer themselves may
    confirm, so `X-User-ID` must equal the signup's `volunteer_id`
    (`ERR_NOT_RESOURCE_OWNER`), the signup must be `APPROVED`
    (`ERR_SIGNUP_NOT_CONFIRMABLE`), and the logical clock must not have passed
    `confirm_by_at` (`ERR_CONFIRM_DEADLINE_PASSED`)."

    Design: Corner/rbac/volunteer_cannot_confirm_others_signup
    """
    ctx = setup_event_with_shift(publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    v1 = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    v2 = register_eligible_volunteer(ev, full_name="V Two", date_of_birth="2000-01-02")
    sg = request_signup(v1["id"], ctx["shift"]["id"])
    approve_signup(sg["id"])
    resp = api_client.confirm_signup(sg["id"], make_volunteer_headers(v2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    after = validate_success(api_client.get_signup(sg["id"], COORDINATOR))
    assert after["status"] == "APPROVED"
