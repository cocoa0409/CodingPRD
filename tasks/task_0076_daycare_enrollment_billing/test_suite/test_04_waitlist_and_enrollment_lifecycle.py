"""Waitlist promotion/expiry/conversion and the enrollment offer->accept/decline
->activate branching lifecycle.

Translates queue-A difficulty instances (non_linear_state_machine for Enrollment
and WaitlistEntry, boundary empty-waitlist, cross_entity capacity gate,
resource_temporal duplicate-waitlist) and queue-B corner state-machine instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_director_headers, make_parent_headers, ApiErrorId,
)
import test_helpers.fixtures as fx

DIRECTOR = make_director_headers()


# --- Enrollment branching ---

def test_enrollment_decline_is_terminal_no_capacity_consumed(api):
    """PRD §3.4: "Declining moves it from OFFERED to DECLINED and increments its
    version".
    PRD §3.4: "The terminal enrollment states are DECLINED, WITHDRAWN, and
    GRADUATED."

    Design: Difficulty/non_linear_state_machine/enrollment_branching_offered_to_accepted_or_declined
    """
    center, classroom, family = fx.setup_center_classroom_family()
    child, enrollment = fx.create_offered_enrollment(classroom, family)
    parent = make_parent_headers(family["id"])
    resp = api.decline_enrollment(enrollment["id"], parent)
    data = validate_success(resp, 200)
    assert data["status"] == "DECLINED"
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    assert room["active_enrollment_count"] == 0


def test_enrollment_accept_moves_offered_to_accepted(api):
    """PRD §3.4: "Accepting moves the enrollment from OFFERED to ACCEPTED and
    increments its version."

    Design: Difficulty/non_linear_state_machine/enrollment_branching_offered_to_accepted_or_declined
    """
    center, classroom, family = fx.setup_center_classroom_family()
    child, enrollment = fx.create_offered_enrollment(classroom, family)
    parent = make_parent_headers(family["id"])
    resp = api.accept_enrollment(enrollment["id"], parent)
    data = validate_success(resp, 200)
    assert data["status"] == "ACCEPTED"


def test_enrollment_initial_state_offered_unpriced(api):
    """PRD §3.4: "The new Enrollment begins in the OFFERED state".
    PRD §3.4: "The starting defaults before activation are a sibling_discount_pct
    of 0, a locked_base_tuition_cents of 0, a locked_parent_share_pct of 100, and a
    monthly_net_tuition_cents of 0."

    Design: Corner/state_machines/enrollment_initial_state_is_offered
    """
    center, classroom, family = fx.setup_center_classroom_family()
    child, enrollment = fx.create_offered_enrollment(classroom, family)
    assert enrollment["status"] == "OFFERED"
    assert enrollment["monthly_net_tuition_cents"] == 0


def test_accept_already_active_enrollment_invalid_state(api):
    """PRD §2.6: "an operation whose transition is not defined from the resource's
    current state fails with ERR_INVALID_STATE."
    PRD §3.4: "Accepting moves the enrollment from OFFERED to ACCEPTED".

    Design: Corner/state_machines/accept_enrollment_from_active_invalid_state
    """
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment()
    parent = make_parent_headers(family["id"])
    resp = api.accept_enrollment(enrollment["id"], parent)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_graduated_enrollment_is_locked_down(api):
    """PRD §3.4: "graduate it, moving it to the terminal GRADUATED state".
    PRD §2.6: "an operation whose transition is not defined from the resource's
    current state fails with ERR_INVALID_STATE."

    Design: Corner/state_machines/terminal_graduated_locked_down
    """
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment()
    get_success_data(api.graduate_enrollment(enrollment["id"], DIRECTOR))
    resp = api.withdraw_enrollment(enrollment["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_graduate_decrements_capacity_and_reopens_classroom(api):
    """PRD §3.4: "Both decrement the classroom's active_enrollment_count by one,
    recompute the classroom's status".
    PRD §2.9: "a classroom is OPEN while its active count is below its licensed
    capacity".

    Design: Corner/state_machines/graduate_bubbles_capacity_decrement_and_status_reopen
    """
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment(
        classroom_overrides={"licensed_capacity": 1})
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    assert room["status"] == "FULL"
    get_success_data(api.graduate_enrollment(enrollment["id"], DIRECTOR))
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    assert room["active_enrollment_count"] == 0
    assert room["status"] == "OPEN"


def test_activate_blocked_when_classroom_full(api):
    """PRD §3.4: "Activation re-checks capacity at this moment rather than relying
    on the offer-time view: if the classroom's active_enrollment_count has reached
    its licensed_capacity, activation is rejected with ERR_CLASSROOM_FULL."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_depends_on_classroom_capacity_state
    """
    center, classroom, family, child_a, enr_a = fx.setup_single_active_enrollment(
        classroom_overrides={"licensed_capacity": 1})
    child_b, enr_b = fx.create_offered_enrollment(classroom, family)
    fx.accept_enrollment(enr_b, family)
    resp = api.activate_enrollment(enr_b["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_CLASSROOM_FULL.value)
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    assert room["active_enrollment_count"] == 1


def test_activate_at_capacity_keeps_count_unchanged(api):
    """PRD §3.4: "if the classroom's active_enrollment_count has reached its
    licensed_capacity, activation is rejected with ERR_CLASSROOM_FULL."
    PRD §2.9: "FULL once the active count reaches the licensed capacity."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_depends_on_classroom_capacity_state
    """
    center, classroom, family, child_a, enr_a = fx.setup_single_active_enrollment(
        classroom_overrides={"licensed_capacity": 1})
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    assert room["status"] == "FULL"
    child_b, enr_b = fx.create_offered_enrollment(classroom, family)
    fx.accept_enrollment(enr_b, family)
    api.activate_enrollment(enr_b["id"], DIRECTOR)
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    assert room["active_enrollment_count"] == 1


# --- Waitlist branching ---

def test_waitlist_offer_expires_via_sweep(api):
    """PRD §3.3: "A center director runs the stale-offer sweep on a classroom; it
    selects every OFFERED entry on that classroom whose offer_expires_at is earlier
    than the current UTC instant and moves each from OFFERED to EXPIRED".

    Design: Difficulty/non_linear_state_machine/waitlist_branching_waiting_to_offered_converted_or_expired
    """
    center, classroom, family, child, entry = fx.setup_offered_waitlist_entry(
        promote_clock="2026-03-01T08:00:00Z")
    assert entry["status"] == "OFFERED"
    fx.set_clock("2026-03-05T08:00:00Z")
    get_success_data(api.expire_stale_waitlist(classroom["id"], DIRECTOR))
    swept = get_success_data(api.get_waitlist_entry(entry["id"], DIRECTOR))
    assert swept["status"] == "EXPIRED"


def test_waitlist_offer_converts_on_enrollment(api):
    """PRD §3.4: "On a successful conversion the linked waitlist entry transitions
    from OFFERED to CONVERTED and its version is incremented".

    Design: Difficulty/non_linear_state_machine/waitlist_branching_waiting_to_offered_converted_or_expired
    """
    center, classroom, family, child, entry = fx.setup_offered_waitlist_entry(
        promote_clock="2026-03-01T08:00:00Z")
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    resp = api.create_enrollment(
        {"child_id": child["id"], "classroom_id": classroom["id"],
         "expected_classroom_version": room["version"],
         "waitlist_entry_id": entry["id"]}, DIRECTOR)
    validate_success(resp, 201)
    converted = get_success_data(api.get_waitlist_entry(entry["id"], DIRECTOR))
    assert converted["status"] == "CONVERTED"


def test_waitlist_convert_offer_creates_offered_enrollment(api):
    """PRD §3.3: "Adding a child creates a WaitlistEntry ... entering in the WAITING
    state."
    PRD §3.4: "On a successful conversion the linked waitlist entry transitions from
    OFFERED to CONVERTED ... the consumed offer is recorded on the enrollment
    through waitlist_entry_id."

    Design: Corner/state_machines/waitlist_convert_consumes_offer_to_converted
    """
    center, classroom, family, child, entry = fx.setup_offered_waitlist_entry(
        promote_clock="2026-03-01T08:00:00Z")
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    resp = api.create_enrollment(
        {"child_id": child["id"], "classroom_id": classroom["id"],
         "expected_classroom_version": room["version"],
         "waitlist_entry_id": entry["id"]}, DIRECTOR)
    enr = validate_success(resp, 201)
    assert enr["status"] == "OFFERED"
    converted = get_success_data(api.get_waitlist_entry(entry["id"], DIRECTOR))
    assert converted["status"] == "CONVERTED"


def test_parent_withdraws_waiting_entry(api):
    """PRD §3.3: "A parent may withdraw their own child's waitlist entry at any time
    while it is WAITING or OFFERED, moving it to the terminal WITHDRAWN state and
    incrementing its version".

    Design: Corner/state_machines/waitlist_withdraw_by_parent_valid
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    classroom = fx.create_classroom(center["id"], licensed_capacity=1)
    family = fx.create_family(center["id"])
    parent = make_parent_headers(family["id"])
    child = get_success_data(api.create_child(
        {"family_id": family["id"], "full_name": "K", "birthdate": "2024-01-10"},
        parent))
    entry = get_success_data(api.add_to_waitlist(
        classroom["id"], {"child_id": child["id"]}, parent))
    resp = api.withdraw_waitlist_entry(entry["id"], parent)
    data = validate_success(resp, 200)
    assert data["status"] == "WITHDRAWN"


def test_convert_expired_offer_rejected(api):
    """PRD §3.4: "the named entry must currently be OFFERED and its offer must not
    have lapsed; if the current UTC instant is past that entry's offer_expires_at,
    the conversion is rejected with ERR_OFFER_EXPIRED."

    Design: Corner/state_machines/convert_expired_offer_returns_offer_expired
    """
    center, classroom, family, child, entry = fx.setup_offered_waitlist_entry(
        promote_clock="2026-03-01T08:00:00Z")
    room = get_success_data(api.get_classroom(classroom["id"], DIRECTOR))
    fx.set_clock("2026-03-10T08:00:00Z")
    resp = api.create_enrollment(
        {"child_id": child["id"], "classroom_id": classroom["id"],
         "expected_classroom_version": room["version"],
         "waitlist_entry_id": entry["id"]}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)


def test_empty_waitlist_promote_rejected(api):
    """PRD §3.3: "If there are no WAITING entries to choose from, the promotion is
    rejected with ERR_WAITLIST_EMPTY."

    Design: Difficulty/boundary_precision_check/empty_waitlist_promote_returns_error_zero_count_boundary
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    classroom = fx.create_classroom(center["id"])
    resp = api.promote_waitlist(classroom["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_WAITLIST_EMPTY.value)


def test_promote_on_classroom_with_entries_succeeds(api):
    """PRD §3.3: "Promotion selects exactly one WAITING entry deterministically ...
    and moves it from WAITING to OFFERED."

    A non-empty WAITING set is the boundary partner of the empty-set rejection.

    Design: Difficulty/boundary_precision_check/empty_waitlist_promote_returns_error_zero_count_boundary
    """
    fx.set_clock("2026-03-01T08:00:00Z")
    center = fx.create_center(cacfp_tier="TIER_I")
    classroom = fx.create_classroom(center["id"], licensed_capacity=1)
    family = fx.create_family(center["id"])
    child = fx.create_child(family["id"])
    fx.add_to_waitlist(classroom["id"], child["id"])
    resp = api.promote_waitlist(classroom["id"], DIRECTOR)
    data = validate_success(resp, 200)
    assert data["status"] == "OFFERED"


def test_duplicate_waitlist_entry_same_classroom_rejected(api):
    """PRD §3.3: "A child may not hold two entries in WAITING or OFFERED status on
    the same classroom — a duplicate attempt is rejected with
    ERR_DUPLICATE_WAITLIST."

    Design: Difficulty/resource_temporal_overlap/duplicate_waitlist_entry_same_classroom_rejected
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    classroom = fx.create_classroom(center["id"], licensed_capacity=1)
    family = fx.create_family(center["id"])
    child = fx.create_child(family["id"])
    fx.add_to_waitlist(classroom["id"], child["id"])
    resp = api.add_to_waitlist(classroom["id"], {"child_id": child["id"]}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_WAITLIST.value)


def test_duplicate_waitlist_first_entry_stays_waiting(api):
    """PRD §3.3: "A child may not hold two entries in WAITING or OFFERED status on
    the same classroom — a duplicate attempt is rejected with
    ERR_DUPLICATE_WAITLIST."
    PRD §3.3: "Adding a child creates a WaitlistEntry linking the classroom
    (classroom_id) and the child (child_id), entering in the WAITING state."

    The first (WAITING) entry is unaffected by the rejected duplicate.

    Design: Difficulty/resource_temporal_overlap/duplicate_waitlist_entry_same_classroom_rejected
    """
    center = fx.create_center(cacfp_tier="TIER_I")
    classroom = fx.create_classroom(center["id"], licensed_capacity=1)
    family = fx.create_family(center["id"])
    child = fx.create_child(family["id"])
    first = fx.add_to_waitlist(classroom["id"], child["id"])
    api.add_to_waitlist(classroom["id"], {"child_id": child["id"]}, DIRECTOR)
    still = get_success_data(api.get_waitlist_entry(first["id"], DIRECTOR))
    assert still["status"] == "WAITING"


def test_waitlist_promote_picks_sibling_priority_first(api):
    """PRD §3.3: "entries whose `has_active_sibling` is true form the leading
    priority class, and within a single priority class entries are ordered by
    `created_at` ascending. The entry's own id never breaks ties."
    PRD §3.3: "Promotion selects exactly one WAITING entry deterministically — the
    entry with the minimum priority_rank (sibling-priority class first, then
    earliest created_at)".

    Design: Corner/endpoints/waitlist_promote_picks_sibling_priority_first
    """
    fx.set_clock("2026-03-01T08:00:00Z")
    center = fx.create_center(cacfp_tier="TIER_I")
    classroom = fx.create_classroom(
        center["id"], licensed_capacity=2, base_monthly_tuition_cents=120000)
    fam = fx.create_family(center["id"], household_size=4)
    s1 = fx.create_child(fam["id"], full_name="S1", birthdate="2024-01-10")
    s2 = fx.create_child(
        fam["id"], full_name="S2", birthdate="2024-02-10", sibling_group_id=s1["id"])
    fam2 = fx.create_family(center["id"], primary_contact_name="Q")
    nosib = fx.create_child(fam2["id"], full_name="NoSib", birthdate="2024-01-10")
    # S1 becomes ACTIVE so S2 has an active sibling
    fx.create_active_enrollment(classroom, fam, child=s1)
    wl_nosib = fx.add_to_waitlist(classroom["id"], nosib["id"])  # added first
    wl_s2 = fx.add_to_waitlist(classroom["id"], s2["id"])        # added second
    api.promote_waitlist(classroom["id"], DIRECTOR)
    e_s2 = get_success_data(api.get_waitlist_entry(wl_s2["id"], DIRECTOR))
    e_nosib = get_success_data(api.get_waitlist_entry(wl_nosib["id"], DIRECTOR))
    assert e_s2["status"] == "OFFERED"
    assert e_nosib["status"] == "WAITING"
