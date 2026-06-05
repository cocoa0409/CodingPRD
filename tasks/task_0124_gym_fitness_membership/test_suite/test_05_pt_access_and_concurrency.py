"""Personal training, attendance, guest passes, check-ins, occupancy, and OCC.

Difficulty design index:
  transitive_cascade / pt_session_cancel_reinstates_then_revives_package_depth2
  resource_temporal_overlap / pt_session_fixed_60min_busy_block_rejected
  compensating_invariant / pt_session_count_conserved_under_schedule_then_cancel
  cross_entity_state_dependency / booking_attend_gated_by_session_status_and_checkin
  boundary_precision_check / occupancy_exactly_at_cap_rejects_checkin
Corner design index:
  state_machines / pt_session_complete_keeps_deduction
  state_machines / guest_pass_revoke_restores_member_guest_pass
  calculations / pt_package_price_zero_discount_basic_plan
  validations / issue_guest_pass_no_passes_returns_402
  validations / pt_late_cancel_within_cutoff_returns_conflict
  validations / checkin_blocked_when_member_suspended
  validations / guest_pass_expired_redemption_rejected
  errors / error_no_pt_sessions_when_package_exhausted
  endpoints / checkout_decrements_occupancy
  entities / checkin_is_immutable_event_member_actor_kind
  cross_cutting_complexity_layers / occ_correct_package_version_succeeds
  cross_cutting_complexity_layers / occ_stale_package_version_returns_412
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    setup_active_member, setup_suspended_member, setup_pt_package_with_session,
    create_plan, create_location, create_session, book, set_clock, run_sweep,
    create_pt_package, schedule_pt_session, get_pt_package, issue_guest_pass,
    check_in_member, get_location,
    PLAN_PLUS, PLAN_BASIC, PLAN_ELITE,
    ApiErrorId, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ===========================================================================
# transitive_cascade / pt_session_cancel_reinstates_then_revives_package_depth2
# ===========================================================================
def test_pt_cancel_reinstates_and_revives_exhausted_package(api):
    """PRD §3.6: "On a successful cancel the session moves to CANCELLED, deducted is set to
    false, and one session is reinstated to the package (sessions_remaining increases by one);
    if that package had been EXHAUSTED it returns to ACTIVE."

    Design: Difficulty/transitive_cascade/pt_session_cancel_reinstates_then_revives_package_depth2
    """
    # 1-session package: scheduling its only session makes it EXHAUSTED.
    setup = setup_pt_package_with_session(plan_shape=PLAN_BASIC, sessions_purchased=1,
                                          list_price_cents=12000)
    package, pt_session = setup["package"], setup["pt_session"]
    assert package["status"] == "EXHAUSTED"
    data = validate_success(
        api.cancel_pt_session(pt_session["id"], {"expected_package_version": package["version"]}, STAFF), 200
    )
    assert data["status"] == "CANCELLED"
    pkg = validate_success(api.get_pt_package(package["id"], STAFF), 200)
    assert pkg["sessions_remaining"] == 1
    assert pkg["status"] == "ACTIVE"


def test_pt_schedule_exhausts_single_session_package(api):
    """PRD §3.6: "if the deduction brings sessions_remaining to zero the package transitions
    from ACTIVE to EXHAUSTED, a further version increment."

    Design: Difficulty/transitive_cascade/pt_session_cancel_reinstates_then_revives_package_depth2
    """
    setup = setup_pt_package_with_session(plan_shape=PLAN_BASIC, sessions_purchased=1,
                                          list_price_cents=12000)
    assert setup["package"]["status"] == "EXHAUSTED"
    assert setup["package"]["sessions_remaining"] == 0


# ===========================================================================
# compensating_invariant / pt_session_count_conserved_under_schedule_then_cancel
# ===========================================================================
def test_pt_session_count_conserved_under_schedule_then_cancel(api):
    """PRD §3.6: "On a successful cancel the session moves to CANCELLED, deducted is set to
    false, and one session is reinstated to the package (sessions_remaining increases by one)"

    Design: Difficulty/compensating_invariant/pt_session_count_conserved_under_schedule_then_cancel
    """
    setup = setup_pt_package_with_session(plan_shape=PLAN_ELITE, sessions_purchased=5,
                                          list_price_cents=50000)
    package, pt_session = setup["package"], setup["pt_session"]
    assert package["sessions_remaining"] == 4
    data = validate_success(
        api.cancel_pt_session(pt_session["id"], {"expected_package_version": package["version"]}, STAFF), 200
    )
    assert data["status"] == "CANCELLED"
    assert data["deducted"] is False
    pkg = validate_success(api.get_pt_package(package["id"], STAFF), 200)
    assert pkg["sessions_remaining"] == 5, "schedule (deduct 1) then cancel (reinstate 1) -> back to 5"


def test_pt_schedule_deducts_one_from_pool(api):
    """PRD §3.6: "one session is deducted from the package (sessions_remaining decreases by
    one), and the package's version increments"

    Design: Difficulty/compensating_invariant/pt_session_count_conserved_under_schedule_then_cancel
    """
    setup = setup_pt_package_with_session(plan_shape=PLAN_ELITE, sessions_purchased=5,
                                          list_price_cents=50000)
    assert setup["package"]["sessions_remaining"] == 4
    assert setup["pt_session"]["deducted"] is True


# ===========================================================================
# resource_temporal_overlap / pt_session_fixed_60min_busy_block_rejected
# ===========================================================================
def test_pt_session_within_60min_busy_block_rejected(api):
    """PRD §3.6: "a new session's starts_at may not fall within the half-open block of any
    existing SCHEDULED PT session for the same member — that is, within the interval from an
    existing session's starts_at up to but not including the instant sixty minutes after it. A
    clash is rejected with ERR_PT_TIME_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/pt_session_fixed_60min_busy_block_rejected
    """
    setup = setup_pt_package_with_session(plan_shape=PLAN_ELITE, sessions_purchased=5,
                                          list_price_cents=50000, pt_starts_at="2026-06-25T15:00:00Z")
    package = setup["package"]
    # 15:30 falls inside [15:00, 16:00).
    resp = api.create_pt_session(
        {"package_id": package["id"], "trainer_name": "Tia",
         "starts_at": "2026-06-25T15:30:00Z", "expected_package_version": package["version"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_PT_TIME_OVERLAP.value)


def test_pt_session_outside_60min_block_succeeds(api):
    """PRD §3.6: "On success the session is created SCHEDULED with deducted true, one session is
    deducted from the package (sessions_remaining decreases by one), and the package's version
    increments"

    Design: Difficulty/resource_temporal_overlap/pt_session_fixed_60min_busy_block_rejected
    """
    setup = setup_pt_package_with_session(plan_shape=PLAN_ELITE, sessions_purchased=5,
                                          list_price_cents=50000, pt_starts_at="2026-06-25T15:00:00Z")
    package = setup["package"]
    # 16:00 is exactly at the end of the half-open block -> not inside, allowed.
    resp = api.create_pt_session(
        {"package_id": package["id"], "trainer_name": "Tia",
         "starts_at": "2026-06-25T16:00:00Z", "expected_package_version": package["version"]}, STAFF
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


# ===========================================================================
# cross_entity_state_dependency / booking_attend_gated_by_session_status_and_checkin
# ===========================================================================
def test_attend_with_open_checkin_and_scheduled_session_succeeds(api):
    """PRD §3.5: "Marking attendance is a StaffManager action that moves a BOOKED booking to
    ATTENDED. It is permitted only while the booking is BOOKED, the owning session is still
    SCHEDULED, and the member currently holds an OPEN check-in at that session's location."

    Design: Difficulty/cross_entity_state_dependency/booking_attend_gated_by_session_status_and_checkin
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    loc = setup["location"]
    session = create_session(loc["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-06-12T09:00:00Z", ends_at="2026-06-12T10:00:00Z")
    booking = book(session["id"], member["id"], session["version"])
    check_in_member(member["id"], loc["id"])
    data = validate_success(api.attend_booking(booking["id"], STAFF), 200)
    assert data["status"] == "ATTENDED"


def test_attend_keeps_session_scheduled(api):
    """PRD §3.5: "It is permitted only while the booking is BOOKED, the owning session is still
    SCHEDULED, and the member currently holds an OPEN check-in at that session's location."

    Design: Difficulty/cross_entity_state_dependency/booking_attend_gated_by_session_status_and_checkin
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    loc = setup["location"]
    session = create_session(loc["id"], capacity=5, waitlist_cap=5,
                             starts_at="2026-06-12T09:00:00Z", ends_at="2026-06-12T10:00:00Z")
    booking = book(session["id"], member["id"], session["version"])
    check_in_member(member["id"], loc["id"])
    validate_success(api.attend_booking(booking["id"], STAFF), 200)
    sess = validate_success(api.get_class_session(session["id"], STAFF), 200)
    assert sess["status"] == "SCHEDULED"


# ===========================================================================
# boundary_precision_check / occupancy_exactly_at_cap_rejects_checkin
# ===========================================================================
def test_checkin_at_exactly_cap_rejected(api):
    """PRD §2.8: "an attempt to enter when current_occupancy is at least equal to occupancy_cap
    is rejected with ERR_OCCUPANCY_FULL (HTTP 409). Concretely, when the cap is reached the next
    entry is refused, and an entry while occupancy is one below the cap succeeds and raises
    occupancy to exactly the cap."

    Design: Difficulty/boundary_precision_check/occupancy_exactly_at_cap_rejects_checkin
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location(name="TinyStudio", occupancy_cap=1)
    setup_a = setup_active_member(plan=plan, location=location)
    setup_b = setup_active_member(plan=plan, location=location)
    check_in_member(setup_a["member"]["id"], location["id"])  # occupancy -> 1 == cap
    resp = api.create_check_in(
        {"member_id": setup_b["member"]["id"], "location_id": location["id"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_OCCUPANCY_FULL.value)
    loc = validate_success(api.get_location(location["id"], STAFF), 200)
    assert loc["current_occupancy"] == 1


def test_checkin_one_below_cap_succeeds_to_cap(api):
    """PRD §2.8: "an entry while occupancy is one below the cap succeeds and raises occupancy to
    exactly the cap. Each successful entry adds one to current_occupancy"

    Design: Difficulty/boundary_precision_check/occupancy_exactly_at_cap_rejects_checkin
    """
    plan = create_plan(PLAN_PLUS)
    location = create_location(name="TinyStudio", occupancy_cap=1)
    setup_a = setup_active_member(plan=plan, location=location)
    data = validate_success(
        api.create_check_in(
            {"member_id": setup_a["member"]["id"], "location_id": location["id"]}, STAFF
        ), 201
    )
    assert data["status"] == "OPEN"
    loc = validate_success(api.get_location(location["id"], STAFF), 200)
    assert loc["current_occupancy"] == 1


# ===========================================================================
# state_machines / pt_session_complete_keeps_deduction
# ===========================================================================
def test_pt_session_complete_keeps_deduction(api):
    """PRD §3.6: "completion is permitted only while the session is SCHEDULED and the current
    clock has reached starts_at (at or past it), sets the session to COMPLETED, leaves the
    deduction standing with deducted remaining true, and increments the session's version."

    Design: Corner/state_machines/pt_session_complete_keeps_deduction
    """
    setup = setup_pt_package_with_session(plan_shape=PLAN_ELITE, sessions_purchased=5,
                                          list_price_cents=50000, pt_starts_at="2026-06-13T15:00:00Z")
    package, pt_session = setup["package"], setup["pt_session"]
    set_clock("2026-06-13T16:00:00Z")  # past starts_at
    data = validate_success(api.complete_pt_session(pt_session["id"], STAFF), 200)
    assert data["status"] == "COMPLETED"
    assert data["deducted"] is True
    pkg = validate_success(api.get_pt_package(package["id"], STAFF), 200)
    assert pkg["sessions_remaining"] == 4, "completion does not reinstate the session"


# ===========================================================================
# calculations / pt_package_price_zero_discount_basic_plan
# ===========================================================================
def test_pt_package_zero_discount_price_unchanged(api):
    """PRD §3.9: "The discount fraction is the plan's pt_discount_pct, a value from 0.0 up to
    and including 0.5. The evaluation order is pinned: the discount is applied to the whole
    list_price_cents — the package's list price is multiplied by one minus the discount fraction
    — and the result is rounded half-up to whole cents exactly once."

    Design: Corner/calculations/pt_package_price_zero_discount_basic_plan
    """
    plan = create_plan(PLAN_BASIC)  # pt_discount_pct 0.0
    setup = setup_active_member(plan=plan, clock="2026-06-12T00:00:00Z",
                                period_start="2026-06-12T00:00:00Z",
                                period_end="2026-07-01T00:00:00Z", due_date="2026-06-12T00:00:00Z")
    member = setup["member"]
    data = validate_success(
        api.create_pt_package(
            {"member_id": member["id"], "sessions_purchased": 5, "list_price_cents": 30000}, STAFF
        ), 201
    )
    assert data["price_paid_cents"] == 30000
    assert data["sessions_remaining"] == 5


# ===========================================================================
# state_machines / guest_pass_revoke_restores_member_guest_pass
# ===========================================================================
def test_guest_pass_revoke_restores_member_guest_pass(api):
    """PRD §3.10: "A StaffManager may instead revoke an ISSUED pass; revocation moves it to
    REVOKED and restores one guest_passes_remaining to the sponsoring member."

    Design: Corner/state_machines/guest_pass_revoke_restores_member_guest_pass
    """
    plan = create_plan(PLAN_PLUS)  # 2 guest passes/cycle
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    gp = issue_guest_pass(member["id"], setup["location"]["id"])  # remaining -> 1
    data = validate_success(api.revoke_guest_pass(gp["id"], STAFF), 200)
    assert data["status"] == "REVOKED"
    member_data = validate_success(api.get_member(member["id"], STAFF), 200)
    assert member_data["guest_passes_remaining"] == 2


# ===========================================================================
# validations / issue_guest_pass_no_passes_returns_402
# ===========================================================================
def test_issue_guest_pass_with_none_remaining_returns_402(api):
    """PRD §3.10: "Issuing requires the sponsor to hold at least one guest_passes_remaining; with
    none left the request is rejected with ERR_NO_GUEST_PASSES (HTTP 402)."

    Design: Corner/validations/issue_guest_pass_no_passes_returns_402
    """
    plan = create_plan(PLAN_BASIC)  # 1 guest pass/cycle
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    issue_guest_pass(member["id"], setup["location"]["id"])  # remaining -> 0
    resp = api.create_guest_pass(
        {"member_id": member["id"], "guest_name": "G2", "location_id": setup["location"]["id"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_NO_GUEST_PASSES.value)


# ===========================================================================
# validations / pt_late_cancel_within_cutoff_returns_conflict
# ===========================================================================
def test_pt_late_cancel_within_cutoff_returns_conflict(api):
    """PRD §3.6: "Cancellation is permitted only while the session is SCHEDULED, only when the
    current clock is strictly earlier than twenty-four hours before the session's starts_at ... A
    cancel attempted within twenty-four hours of starts_at is rejected with ERR_PT_LATE_CANCEL
    (HTTP 409)."

    Design: Corner/validations/pt_late_cancel_within_cutoff_returns_conflict
    """
    setup = setup_pt_package_with_session(plan_shape=PLAN_ELITE, sessions_purchased=5,
                                          list_price_cents=50000, pt_starts_at="2026-06-25T15:00:00Z")
    package, pt_session = setup["package"], setup["pt_session"]
    set_clock("2026-06-25T00:00:00Z")  # 15h before starts_at -> inside the 24h cutoff
    resp = api.cancel_pt_session(pt_session["id"], {"expected_package_version": package["version"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_PT_LATE_CANCEL.value)
    pkg = validate_success(api.get_pt_package(package["id"], STAFF), 200)
    assert pkg["sessions_remaining"] == 4, "deduction stands on a rejected late cancel"


# ===========================================================================
# validations / checkin_blocked_when_member_suspended
# ===========================================================================
def test_checkin_blocked_when_member_suspended(api):
    """PRD §2.8: "A member may not enter while their dues axis is SUSPENDED or while their
    membership lifecycle is anything other than ACTIVE; such an attempt is rejected with
    ERR_ACCESS_DENIED_SUSPENDED (HTTP 403)."

    Design: Corner/validations/checkin_blocked_when_member_suspended
    """
    setup = setup_suspended_member(plan_shape=PLAN_PLUS)
    member = setup["member"]
    resp = api.create_check_in({"member_id": member["id"], "location_id": setup["location"]["id"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_ACCESS_DENIED_SUSPENDED.value)
    loc = validate_success(api.get_location(setup["location"]["id"], STAFF), 200)
    assert loc["current_occupancy"] == 0


# ===========================================================================
# validations / guest_pass_expired_redemption_rejected
# ===========================================================================
def test_expired_guest_pass_redemption_rejected(api):
    """PRD §3.10: "A redemption attempted after expires_at is rejected with
    ERR_GUEST_PASS_EXPIRED (HTTP 409)."
    PRD §3.10: "when the sweep observes the current clock past expires_at, an ISSUED pass moves
    to EXPIRED."

    Note: this scenario runs the sweep before the redemption attempt, so per §3.10 the pass has
    already moved ISSUED->EXPIRED. PRD §2.10 fixes the validation order as state-validity
    (ERR_INVALID_STATE) *before* operation-specific business rules from §3 (the expires_at check
    that yields ERR_GUEST_PASS_EXPIRED). A faithful PRD-only reader therefore reaches the
    state-validity check first (pass not ISSUED) and reports ERR_INVALID_STATE, while a reader who
    checks expires_at before pass-state reports ERR_GUEST_PASS_EXPIRED. PRD does not state which
    pre-empts when the sweep has already expired the pass, so both error_ids are admissible
    (both HTTP 409).

    Design: Corner/validations/guest_pass_expired_redemption_rejected
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan, clock="2026-06-10T00:00:00Z")
    member = setup["member"]
    loc = setup["location"]
    gp = issue_guest_pass(member["id"], loc["id"])  # issued 2026-06-10, expires 2026-06-24
    set_clock("2026-06-26T00:00:00Z")
    run_sweep()
    resp = api.create_check_in({"guest_pass_id": gp["id"], "location_id": loc["id"]}, STAFF)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_GUEST_PASS_EXPIRED.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


# ===========================================================================
# errors / error_no_pt_sessions_when_package_exhausted
# ===========================================================================
def test_schedule_against_exhausted_package_returns_402(api):
    """PRD §3.6: "Scheduling requires the package to be ACTIVE with sessions_remaining of at
    least one; a package that is not active or has no sessions left is rejected with
    ERR_NO_PT_SESSIONS (HTTP 402)."

    Design: Corner/errors/error_no_pt_sessions_when_package_exhausted
    """
    setup = setup_pt_package_with_session(plan_shape=PLAN_ELITE, sessions_purchased=1,
                                          list_price_cents=12000, pt_starts_at="2026-06-25T15:00:00Z")
    package = setup["package"]
    assert package["status"] == "EXHAUSTED"
    resp = api.create_pt_session(
        {"package_id": package["id"], "trainer_name": "Ann",
         "starts_at": "2026-06-26T15:00:00Z", "expected_package_version": package["version"]}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_NO_PT_SESSIONS.value)


# ===========================================================================
# endpoints / checkout_decrements_occupancy
# ===========================================================================
def test_checkout_decrements_occupancy(api):
    """PRD §3.11: "Checking out closes an entry: a StaffManager closes an OPEN check-in, moving
    its status to CLOSED and lowering the location's current_occupancy by one, never below zero."

    Design: Corner/endpoints/checkout_decrements_occupancy
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    loc = setup["location"]
    ci = check_in_member(member["id"], loc["id"])
    data = validate_success(api.checkout_check_in(ci["id"], STAFF), 200)
    assert data["status"] == "CLOSED"
    loc_data = validate_success(api.get_location(loc["id"], STAFF), 200)
    assert loc_data["current_occupancy"] == 0


# ===========================================================================
# entities / checkin_is_immutable_event_member_actor_kind
# ===========================================================================
def test_member_checkin_derives_actor_kind_member(api):
    """PRD §3.11: "The resulting CheckIn derives its actor_kind from which identifier was
    supplied — MEMBER when the member identifier was given, GUEST when the guest pass was given —
    and starts in OPEN status with its created_at set to the entry instant."

    Design: Corner/entities/checkin_is_immutable_event_member_actor_kind
    """
    plan = create_plan(PLAN_PLUS)
    setup = setup_active_member(plan=plan)
    member = setup["member"]
    loc = setup["location"]
    data = validate_success(
        api.create_check_in({"member_id": member["id"], "location_id": loc["id"]}, STAFF), 201
    )
    assert data["status"] == "OPEN"
    assert data["actor_kind"] == "MEMBER"
    loc_data = validate_success(api.get_location(loc["id"], STAFF), 200)
    assert loc_data["current_occupancy"] == 1


# ===========================================================================
# cross_cutting / occ_correct_package_version_succeeds
# ===========================================================================
def test_schedule_pt_with_current_package_version_succeeds(api):
    """PRD §2.7: "A PT-session-create request must carry `expected_package_version`, the
    `version` of the target package the client last observed."
    PRD §3.6: "On success the session is created `SCHEDULED` with `deducted` true, one session
    is deducted from the package (`sessions_remaining` decreases by one)"

    Design: Corner/cross_cutting_complexity_layers/occ_correct_package_version_succeeds
    """
    plan = create_plan(PLAN_ELITE)
    setup = setup_active_member(plan=plan, clock="2026-06-12T00:00:00Z",
                                period_start="2026-06-12T00:00:00Z",
                                period_end="2026-07-01T00:00:00Z", due_date="2026-06-12T00:00:00Z")
    package = create_pt_package(setup["member"]["id"], sessions_purchased=5, list_price_cents=50000)
    data = validate_success(
        api.create_pt_session(
            {"package_id": package["id"], "trainer_name": "Jo",
             "starts_at": "2026-06-25T15:00:00Z", "expected_package_version": package["version"]}, STAFF
        ), 201
    )
    assert data["status"] == "SCHEDULED"
    pkg = validate_success(api.get_pt_package(package["id"], STAFF), 200)
    assert pkg["sessions_remaining"] == 4


# ===========================================================================
# cross_cutting / occ_stale_package_version_returns_412
# ===========================================================================
def test_schedule_pt_with_stale_package_version_returns_412(api):
    """PRD §2.7: "If that value does not equal the package's current version, the request is
    rejected with ERR_STALE_PACKAGE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_package_version_returns_412
    """
    plan = create_plan(PLAN_ELITE)
    setup = setup_active_member(plan=plan, clock="2026-06-12T00:00:00Z",
                                period_start="2026-06-12T00:00:00Z",
                                period_end="2026-07-01T00:00:00Z", due_date="2026-06-12T00:00:00Z")
    package = create_pt_package(setup["member"]["id"], sessions_purchased=5, list_price_cents=50000)
    stale_v = package["version"]
    schedule_pt_session(package["id"], stale_v, starts_at="2026-06-25T15:00:00Z")  # advances version
    resp = api.create_pt_session(
        {"package_id": package["id"], "trainer_name": "Jo",
         "starts_at": "2026-06-26T15:00:00Z", "expected_package_version": stale_v}, STAFF
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PACKAGE_VERSION.value, expected_status=412)
