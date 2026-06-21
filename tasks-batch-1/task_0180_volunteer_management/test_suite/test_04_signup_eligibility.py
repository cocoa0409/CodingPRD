"""Shift-signup eligibility chain and seat capacity: the fixed-order eligibility
checks (temporal/bg-tier beat capacity), the last-seat boundary, suspended-volunteer
ineligibility, half-open interval overlap vs adjacency, seat-conservation under
cancel, and the gate rejections (waiver/skill/training/duplicate/fk/full).

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
Queue B (Corner): validations.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_signup_payload, create_waiver_template_payload, create_skill_payload,
    create_training_module_payload,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    create_organization, create_volunteer, create_opportunity, create_shift,
    publish_opportunity, set_clock, get_shift, get_volunteer,
    create_signup, create_confirmed_signup,
    create_cleared_background_check, setup_signup_ready, COMPLIANCE,
)
from test_helpers.test_users import TEST_USERS, make_volunteer_headers

COORD = TEST_USERS["shift_coordinator_headers"]


def _signup_resp(api, shift_id, volunteer_id, expected_version):
    return api.create_signup(
        shift_id, create_signup_payload(volunteer_id, expected_version),
        make_volunteer_headers(volunteer_id))


# ─── Priority-pair conflicts (eligibility chain order) ─────────────────────

def test_temporal_conflict_beats_capacity(api):
    """PRD §3.4: "an earlier obstacle masks a later one."
    PRD §3.4: "A genuine overlap is rejected with `ERR_SHIFT_TIME_CONFLICT`."
    PRD §3.4: "A full shift is rejected with `ERR_SHIFT_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_capacity_on_signup
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    other = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 1, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-01T10:00:00Z", "2026-07-01T11:00:00Z", 1, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    # V holds a CONFIRMED signup on A (overlaps B).
    create_confirmed_signup(sa, vol["id"])
    # B is filled by another volunteer (capacity 1 -> FULL).
    sb_fresh = get_shift(sb["id"], headers=COORD)
    create_signup(sb_fresh["id"], other["id"], sb_fresh["version"])
    sb_full = get_shift(sb["id"], headers=COORD)

    # V tries B: both temporal-overlap and capacity are violated; temporal wins.
    resp = _signup_resp(api, sb["id"], vol["id"], sb_full["version"])
    validate_error(resp, ApiErrorId.ERR_SHIFT_TIME_CONFLICT.value)


def test_bg_tier_gate_beats_capacity(api):
    """PRD §3.4: "an earlier obstacle masks a later one."
    PRD §3.4: "A shortfall is rejected with `ERR_BG_TIER_INSUFFICIENT`."
    PRD §3.4: "A full shift is rejected with `ERR_SHIFT_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/bg_tier_safety_beats_capacity_fiscal_on_signup
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    cleared = create_volunteer(org["id"], headers=COMPLIANCE, full_name="Cleared V")
    vol = create_volunteer(org["id"], headers=COMPLIANCE, full_name="Vic V")
    create_cleared_background_check(org, cleared, "ENHANCED", admin=COMPLIANCE)

    opp = create_opportunity(org["id"], headers=COORD, required_bg_tier="ENHANCED")
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 1, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    # The cleared volunteer fills the only seat (shift FULL).
    sh = get_shift(shift["id"], headers=COORD)
    create_signup(sh["id"], cleared["id"], sh["version"])
    sh_full = get_shift(shift["id"], headers=COORD)

    # vol has NONE tier and the shift is full; bg-tier check (earlier) wins.
    resp = _signup_resp(api, shift["id"], vol["id"], sh_full["version"])
    validate_error(resp, ApiErrorId.ERR_BG_TIER_INSUFFICIENT.value)


def test_capacity_alone_rejects_full_shift_no_conflict(api):
    """PRD §3.4: "A seat must be available: the shift's `reserved_count` must be
    strictly less than its `capacity`. A full shift is rejected with `ERR_SHIFT_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_capacity_on_signup
    """
    # Capacity is the ONLY violated rule (no time conflict, eligible volunteer): the
    # loser error surfaces in isolation, confirming it is genuinely masked above.
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    holder = create_volunteer(org["id"], headers=COORD, full_name="Holder V")
    vol = create_volunteer(org["id"], headers=COORD, full_name="Late V")
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 1, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    sh = get_shift(shift["id"], headers=COORD)
    create_signup(sh["id"], holder["id"], sh["version"])  # shift now FULL
    sh_full = get_shift(shift["id"], headers=COORD)
    resp = _signup_resp(api, shift["id"], vol["id"], sh_full["version"])
    validate_error(resp, ApiErrorId.ERR_SHIFT_FULL.value)


def test_bg_tier_alone_rejects_on_open_shift(api):
    """PRD §3.4: "The rank of the volunteer's `bg_check_tier` must be greater than or
    equal to the rank of the opportunity's `required_bg_tier`, with lazy expiry applied
    against the current clock before the comparison. A shortfall is rejected with
    `ERR_BG_TIER_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/bg_tier_safety_beats_capacity_fiscal_on_signup
    """
    # The bg-tier shortfall is the ONLY violated rule (shift has free capacity).
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD, required_bg_tier="ENHANCED")
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    sh = get_shift(shift["id"], headers=COORD)
    resp = _signup_resp(api, shift["id"], vol["id"], sh["version"])
    validate_error(resp, ApiErrorId.ERR_BG_TIER_INSUFFICIENT.value)


# ─── Capacity boundary ─────────────────────────────────────────────────────

def test_last_seat_fills_then_next_signup_rejected_full(api):
    """PRD §3.4: "if that occupancy brings `reserved_count` to `capacity`, the shift
    moves from `OPEN` to `FULL` and the parent opportunity's `staffing_status` is
    re-evaluated."
    PRD §3.4: "A seat must be available: the shift's `reserved_count` must be strictly
    less than its `capacity`. A full shift is rejected with `ERR_SHIFT_FULL`."

    Design: Difficulty/boundary_precision_check/shift_capacity_last_seat_full_at_equality
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    first = create_volunteer(org["id"], headers=COORD, full_name="First V")
    second = create_volunteer(org["id"], headers=COORD, full_name="Second V")
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 1, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    sh0 = get_shift(shift["id"], headers=COORD)
    create_signup(sh0["id"], first["id"], sh0["version"])
    sh1 = get_shift(shift["id"], headers=COORD)
    assert sh1["reserved_count"] == 1, f"expected reserved_count 1, got {sh1['reserved_count']}"
    assert sh1["status"] == "FULL", f"expected FULL at capacity, got {sh1['status']}"

    resp = _signup_resp(api, shift["id"], second["id"], sh1["version"])
    validate_error(resp, ApiErrorId.ERR_SHIFT_FULL.value)


def test_below_capacity_signup_keeps_shift_open(api):
    """PRD §3.4: "A seat must be available: the shift's `reserved_count` must be
    strictly less than its `capacity`."
    PRD §3.4: "if that occupancy brings `reserved_count` to `capacity`, the shift moves
    from `OPEN` to `FULL`."

    Design: Difficulty/boundary_precision_check/shift_capacity_last_seat_full_at_equality
    """
    # Capacity 2, one seat taken: reserved_count 1 < 2, shift stays OPEN, next succeeds.
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    first = create_volunteer(org["id"], headers=COORD, full_name="First V")
    second = create_volunteer(org["id"], headers=COORD, full_name="Second V")
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 2, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    sh0 = get_shift(shift["id"], headers=COORD)
    create_signup(sh0["id"], first["id"], sh0["version"])
    sh1 = get_shift(shift["id"], headers=COORD)
    assert sh1["reserved_count"] == 1 and sh1["status"] == "OPEN", \
        f"one of two seats filled should stay OPEN, got {sh1['status']} rc={sh1['reserved_count']}"
    data = validate_success(_signup_resp(api, shift["id"], second["id"], sh1["version"]),
                            expected_status=201)
    assert data["status"] == "RESERVED"


# ─── Cross-entity volunteer state dependency ───────────────────────────────

def test_suspended_volunteer_cannot_sign_up(api):
    """PRD §3.4: "The acting volunteer's `status` must be `ACTIVE`. A `SUSPENDED` or
    `WITHDRAWN` volunteer is rejected with `ERR_VOLUNTEER_NOT_ELIGIBLE`."
    PRD §3.5: "the volunteer's `lifetime_no_show_count` is greater than or equal to the
    organization's `no_show_strike_limit`, the volunteer's `status` is transitioned to
    `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/signup_requires_volunteer_active_not_suspended
    """
    org = create_organization(headers=COORD, no_show_strike_limit=1, reliability_suspension_threshold=0)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-08T09:00:00Z", "2026-07-08T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    # One no-show suspends the volunteer (strike limit 1).
    su_a = create_confirmed_signup(sa, vol["id"])
    validate_success(api.mark_no_show_signup(su_a["id"], COORD))
    suspended = get_volunteer(vol["id"], headers=COORD)
    assert suspended["status"] == "SUSPENDED", \
        f"expected SUSPENDED after strike-limit no-show, got {suspended['status']}"

    sb_fresh = get_shift(sb["id"], headers=COORD)
    resp = _signup_resp(api, sb["id"], vol["id"], sb_fresh["version"])
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ELIGIBLE.value)


def test_withdrawn_volunteer_cannot_sign_up(api):
    """PRD §3.4: "The acting volunteer's `status` must be `ACTIVE`. A `SUSPENDED` or
    `WITHDRAWN` volunteer is rejected with `ERR_VOLUNTEER_NOT_ELIGIBLE`."
    PRD §3.1: "Withdrawal is a version-guarded administrative action that sets `status`
    to `WITHDRAWN` and increments the volunteer's `version`."

    Design: Difficulty/cross_entity_state_dependency/signup_requires_volunteer_active_not_suspended
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    withdrawn = validate_success(
        api.withdraw_volunteer(vol["id"], {"expected_volunteer_version": vol["version"]}, COMPLIANCE))
    assert withdrawn["status"] == "WITHDRAWN"

    sh = get_shift(shift["id"], headers=COORD)
    resp = _signup_resp(api, shift["id"], vol["id"], sh["version"])
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ELIGIBLE.value)


# ─── Half-open interval semantics ──────────────────────────────────────────

def test_overlapping_shift_signup_rejected(api):
    """PRD §3.4: "Intervals are half-open over `[starts_at, ends_at)`: two shifts
    conflict when their intervals overlap, but shifts that merely touch at an endpoint
    — one ending exactly when the other begins — do not conflict. A genuine overlap is
    rejected with `ERR_SHIFT_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/individual_signup_half_open_overlap_rejected
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-01T11:00:00Z", "2026-07-01T13:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    create_confirmed_signup(sa, vol["id"])

    sb_fresh = get_shift(sb["id"], headers=COORD)
    resp = _signup_resp(api, sb["id"], vol["id"], sb_fresh["version"])
    validate_error(resp, ApiErrorId.ERR_SHIFT_TIME_CONFLICT.value)


def test_contained_shift_signup_rejected(api):
    """PRD §3.4: "two shifts conflict when their intervals overlap, but shifts that
    merely touch at an endpoint — one ending exactly when the other begins — do not
    conflict. A genuine overlap is rejected with `ERR_SHIFT_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/individual_signup_half_open_overlap_rejected
    """
    # Shift B (10:30-11:30) is fully contained within held shift A (10:00-12:00).
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-01T10:30:00Z", "2026-07-01T11:30:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    create_confirmed_signup(sa, vol["id"])

    sb_fresh = get_shift(sb["id"], headers=COORD)
    resp = _signup_resp(api, sb["id"], vol["id"], sb_fresh["version"])
    validate_error(resp, ApiErrorId.ERR_SHIFT_TIME_CONFLICT.value)


def test_adjacent_shifts_touching_endpoints_allowed(api):
    """PRD §3.4: "shifts that merely touch at an endpoint — one ending exactly when the
    other begins — do not conflict."
    PRD §3.4: "A successful signup creates a `Signup` in `RESERVED` status."

    Design: Difficulty/resource_temporal_overlap/adjacent_shifts_touching_endpoints_allowed
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-01T12:00:00Z", "2026-07-01T14:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    create_confirmed_signup(sa, vol["id"])

    sb_fresh = get_shift(sb["id"], headers=COORD)
    resp = _signup_resp(api, sb["id"], vol["id"], sb_fresh["version"])
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "RESERVED", \
        f"back-to-back (touching) signup should succeed RESERVED, got {data['status']}"


def test_adjacent_shift_ending_at_held_start_allowed(api):
    """PRD §3.4: "shifts that merely touch at an endpoint — one ending exactly when the
    other begins — do not conflict."
    PRD §3.4: "A successful signup creates a `Signup` in `RESERVED` status."

    Design: Difficulty/resource_temporal_overlap/adjacent_shifts_touching_endpoints_allowed
    """
    # Reverse adjacency: shift B (08:00-10:00) ends exactly when held shift A (10:00-12:00) starts.
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T10:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-01T08:00:00Z", "2026-07-01T10:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    create_confirmed_signup(sa, vol["id"])

    sb_fresh = get_shift(sb["id"], headers=COORD)
    data = validate_success(_signup_resp(api, sb["id"], vol["id"], sb_fresh["version"]),
                            expected_status=201)
    assert data["status"] == "RESERVED", \
        f"touching-endpoint signup should succeed RESERVED, got {data['status']}"


# ─── Compensating invariant: cancel restores reserved_count ────────────────

def test_signup_cancel_restores_reserved_count(api):
    """PRD §3.4: "Cancellation moves the signup to `CANCELLED`, releases the seat by
    decrementing the parent shift's `reserved_count` by one, increments the shift's
    `version`."

    Design: Difficulty/compensating_invariant/signup_cancel_restores_shift_reserved_count
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    base = create_volunteer(org["id"], headers=COORD, full_name="Base V")
    vol = create_volunteer(org["id"], headers=COORD, full_name="Comp V")
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 3, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    sh0 = get_shift(shift["id"], headers=COORD)
    create_signup(sh0["id"], base["id"], sh0["version"])
    sh1 = get_shift(shift["id"], headers=COORD)
    assert sh1["reserved_count"] == 1, f"expected reserved_count 1 before, got {sh1['reserved_count']}"

    comp = create_signup(sh1["id"], vol["id"], sh1["version"])
    validate_success(api.cancel_signup(comp["id"], make_volunteer_headers(vol["id"])))
    sh2 = get_shift(shift["id"], headers=COORD)
    assert sh2["reserved_count"] == 1, \
        f"create+cancel must conserve reserved_count at 1, got {sh2['reserved_count']}"


def test_cancel_returns_full_shift_to_open(api):
    """PRD §3.4: "if the shift had been `FULL` and is now below capacity — returns it to
    `OPEN` and re-evaluates the parent opportunity's `staffing_status`."

    Design: Difficulty/compensating_invariant/signup_cancel_restores_shift_reserved_count
    """
    # Capacity-1 shift filled (FULL), then the seat is cancelled -> back to OPEN, rc 0.
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 1, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    sh0 = get_shift(shift["id"], headers=COORD)
    su = create_signup(sh0["id"], vol["id"], sh0["version"])
    sh_full = get_shift(shift["id"], headers=COORD)
    assert sh_full["status"] == "FULL", f"expected FULL, got {sh_full['status']}"

    validate_success(api.cancel_signup(su["id"], make_volunteer_headers(vol["id"])))
    sh_open = get_shift(shift["id"], headers=COORD)
    assert sh_open["status"] == "OPEN", f"cancel must return FULL shift to OPEN, got {sh_open['status']}"
    assert sh_open["reserved_count"] == 0, \
        f"reserved_count must drop to 0 after cancel, got {sh_open['reserved_count']}"


# ─── Corner: eligibility-gate rejections ───────────────────────────────────

def test_signup_missing_required_waiver_rejected(api):
    """PRD §3.4: "If the opportunity sets a `required_waiver_template_id`, the volunteer
    must have a `WaiverAcceptance` for that template whose `accepted_revision` equals
    the template's current `revision`. Otherwise the signup is rejected with
    `ERR_WAIVER_NOT_ACCEPTED`."

    Design: Corner/validations/signup_missing_required_waiver_rejected
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    wt = validate_success(
        api.create_waiver_template(create_waiver_template_payload(org["id"], code="LIABILITY_2026"),
                                   COMPLIANCE), expected_status=201)
    opp = create_opportunity(org["id"], headers=COORD, required_waiver_template_id=wt["id"])
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    sh = get_shift(shift["id"], headers=COORD)
    resp = _signup_resp(api, shift["id"], vol["id"], sh["version"])
    validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ACCEPTED.value)


def test_signup_missing_required_skill_rejected(api):
    """PRD §3.4: "For every `Skill.id` listed in the opportunity's `required_skill_ids`,
    the volunteer must hold a `VolunteerSkill` for that skill with `proficiency` equal
    to `VERIFIED`. Any missing verified skill is rejected with
    `ERR_SKILL_REQUIREMENT_NOT_MET`."

    Design: Corner/validations/signup_missing_required_skill_rejected
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    skill = validate_success(
        api.create_skill(create_skill_payload(org["id"], code="FIRST_AID", label="First Aid"), COORD),
        expected_status=201)
    opp = create_opportunity(org["id"], headers=COORD, required_skill_ids=[skill["id"]])
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    sh = get_shift(shift["id"], headers=COORD)
    resp = _signup_resp(api, shift["id"], vol["id"], sh["version"])
    validate_error(resp, ApiErrorId.ERR_SKILL_REQUIREMENT_NOT_MET.value)


def test_signup_lapsed_training_rejected(api):
    """PRD §3.4: "If the opportunity sets a `required_training_module_id`, the volunteer
    must have a `TrainingCompletion` for that module that has not lapsed — that is,
    whose `expires_at` is at or after the current clock. Otherwise the signup is
    rejected with `ERR_TRAINING_NOT_COMPLETED`."

    Design: Corner/validations/signup_lapsed_training_rejected
    """
    org = create_organization(headers=COMPLIANCE)
    set_clock("2026-06-15T00:00:00Z", headers=COMPLIANCE)
    vol = create_volunteer(org["id"], headers=COMPLIANCE)
    tm = validate_success(
        api.create_training_module(
            create_training_module_payload(org["id"], code="SAFETY_101", valid_days=1), COMPLIANCE),
        expected_status=201)
    validate_success(api.create_training_completion(
        {"volunteer_id": vol["id"], "training_module_id": tm["id"],
         "completed_at": "2026-06-15T00:00:00Z"}, COMPLIANCE), expected_status=201)
    opp = create_opportunity(org["id"], headers=COORD, required_training_module_id=tm["id"])
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    # Advance the clock past the 1-day validity so the completion has lapsed.
    set_clock("2026-06-20T00:00:00Z", headers=COORD)

    sh = get_shift(shift["id"], headers=COORD)
    resp = _signup_resp(api, shift["id"], vol["id"], sh["version"])
    validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_COMPLETED.value)


def test_duplicate_signup_same_shift_rejected(api):
    """PRD §3.4: "The volunteer must not already hold a seat-occupying signup — one in
    `RESERVED`, `CONFIRMED`, `ATTENDED`, `HOURS_LOGGED`, or `HOURS_VERIFIED` — on this
    same shift. A duplicate is rejected with `ERR_DUPLICATE_SIGNUP`."

    Design: Corner/validations/duplicate_signup_same_shift_rejected
    """
    org, vol, opp, shift = setup_signup_ready(capacity=5)
    sh0 = get_shift(shift["id"], headers=COORD)
    create_signup(sh0["id"], vol["id"], sh0["version"])
    sh1 = get_shift(shift["id"], headers=COORD)
    resp = _signup_resp(api, shift["id"], vol["id"], sh1["version"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIGNUP.value)


def test_signup_body_volunteer_not_found(api):
    """PRD §2.7: "Foreign-key body fields — among them `organization_id`,
    `volunteer_id`, ... — must each resolve to an existing entity within the same
    organization; an unresolved reference yields the same resource-specific not-found
    error listed above."

    Design: Corner/validations/body_fk_volunteer_not_found_on_signup
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    sh = get_shift(shift["id"], headers=COORD)
    resp = api.create_signup(
        shift["id"],
        create_signup_payload(NON_EXISTENT_UUID, sh["version"]),
        make_volunteer_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_FOUND.value)
