"""Seating: the cross-entity cascade that claims a chair + technician, the chair
sanitation window, technician single-occupancy, optimistic concurrency on the salon
version, the complete-frees-resources cascade, and seating-time validation precedence.

Covers difficulty queue A rules `transitive_cascade` (complete frees chair/tech),
`cross_entity_state_dependency` (seat needs chair OPEN / package needs member ACTIVE),
`resource_temporal_overlap` (sanitation window, tech double-booking), and
`priority_pair_validation_conflict` (license vs chair-not-sanitized); plus corner
queue B instances under `state_machines` (take-out-of-service occupied),
`endpoints` (tech cert expired), and `cross_cutting_complexity_layers` (OCC stale).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    same_instant,
)
import test_helpers as th

FRONT_DESK = TEST_USERS["front_desk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ===========================================================================
# Difficulty A: transitive_cascade / complete_visit_frees_chair_and_tech_depth2
# ===========================================================================
def test_complete_visit_sanitizes_chair_and_decrements_occupancy(api):
    """PRD §3.6: "It also performs the resource release: the chair moves from
    `OCCUPIED` to `SANITIZING` with its `sanitation_ready_at` set to `ended_at` plus
    the chair's `sanitation_minutes`; the technician moves from `BUSY` back to
    `AVAILABLE`; and the salon's `active_occupancy_count` drops by one."

    Design: Difficulty/transitive_cascade/complete_visit_frees_chair_and_tech_depth2
    """
    th.set_clock("2026-02-01T10:00:00Z")
    salon = th.create_and_open_salon(set_default_clock=False)
    chair = th.add_chair(salon["id"], sanitation_minutes=5)
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    visit = th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"])
    th.complete_visit(visit["id"], tech["id"])
    chair_after = validate_success(api.get_chair(chair["id"], MANAGER))
    assert chair_after["status"] == "SANITIZING"
    tech_after = validate_success(api.get_technician(tech["id"], MANAGER))
    assert tech_after["status"] == "AVAILABLE"
    salon_after = validate_success(api.get_salon(salon["id"], MANAGER))
    assert salon_after["active_occupancy_count"] == 0


def test_complete_visit_sets_sanitation_ready_at(api):
    """PRD §3.9: "The window's end is `sanitation_ready_at`, computed as the visit's
    end instant plus the chair's `sanitation_minutes`."

    Design: Difficulty/transitive_cascade/complete_visit_frees_chair_and_tech_depth2
    """
    th.set_clock("2026-02-01T10:00:00Z")
    salon = th.create_and_open_salon(set_default_clock=False)
    chair = th.add_chair(salon["id"], sanitation_minutes=5)
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    visit = th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"])
    th.complete_visit(visit["id"], tech["id"])
    chair_after = validate_success(api.get_chair(chair["id"], MANAGER))
    assert chair_after["status"] == "SANITIZING"
    assert same_instant(chair_after["sanitation_ready_at"], "2026-02-01T10:05:00Z"), (
        f"expected 10:05, got {chair_after['sanitation_ready_at']}"
    )


# ===========================================================================
# Difficulty A: cross_entity_state_dependency / seat_requires_chair_open_*
# ===========================================================================
def test_seat_onto_out_of_service_chair_rejected(api):
    """PRD §3.4: "The chosen chair must be `OPEN`, else `ERR_CHAIR_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/seat_requires_chair_open_pair_visit_chair
    """
    salon = th.create_and_open_salon()
    chair = th.add_chair(salon["id"])
    validate_success(api.take_chair_out_of_service(chair["id"], MANAGER))
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    resp = api.create_service_visit(
        th.create_service_visit_payload(
            salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"]
        ),
        FRONT_DESK,
    )
    validate_error(resp, ApiErrorId.ERR_CHAIR_NOT_OPEN.value, expected_status=409)
    chair_after = validate_success(api.get_chair(chair["id"], MANAGER))
    assert chair_after["status"] == "OUT_OF_SERVICE"


def test_chair_status_open_required_is_a_seating_precondition(api):
    """PRD §3.4: "The chosen chair must be `OPEN`, else `ERR_CHAIR_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/seat_requires_chair_open_pair_visit_chair
    """
    salon = th.create_and_open_salon()
    chair = th.add_chair(salon["id"])
    # Drive chair to SANITIZING by completing a prior visit, then a fresh ticket
    # cannot be seated onto it while it is not OPEN.
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    m1 = th.add_member(salon["id"])
    t1 = th.join_and_call(salon["id"], m1["id"], svc["id"])
    live = validate_success(api.get_salon(salon["id"], MANAGER))
    v1 = th.seat_visit(salon["id"], t1["id"], chair["id"], tech["id"], live["version"])
    th.complete_visit(v1["id"], tech["id"])  # chair now SANITIZING
    m2 = th.add_member(salon["id"])
    t2 = th.join_and_call(salon["id"], m2["id"], svc["id"])
    live2 = validate_success(api.get_salon(salon["id"], MANAGER))
    resp = api.create_service_visit(
        th.create_service_visit_payload(
            salon["id"], t2["id"], chair["id"], tech["id"], live2["version"]
        ),
        FRONT_DESK,
    )
    # Chair is SANITIZING (not OPEN): seating is refused.
    validate_error(resp, ApiErrorId.ERR_CHAIR_NOT_OPEN.value, expected_status=409)


def test_package_activate_requires_member_active(api):
    """PRD §3.6: "activation requires the member to be `ACTIVE`, else
    `ERR_MEMBER_NOT_ACTIVE`, and stamps `discount_bps`, `total_credits`, and
    `credits_remaining` from the tier."

    Design: Difficulty/cross_entity_state_dependency/package_activate_requires_member_active_pair_package_member
    """
    salon = th.create_and_open_salon()
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    pkg = validate_success(
        api.create_package(th.create_package_payload(member["id"], "SILVER"), FRONT_DESK),
        201,
    )
    # Suspend the package owner directly with two no-shows.
    for _ in range(2):
        t = th.join_queue(salon["id"], member["id"], svc["id"])
        th.call_ticket(t["id"])
        validate_success(api.no_show_queue_ticket(t["id"], FRONT_DESK))
    reread_member = validate_success(api.get_member(member["id"], FRONT_DESK))
    assert reread_member["status"] == "SUSPENDED"
    resp = api.activate_package(pkg["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value, expected_status=409)
    reread_pkg = validate_success(api.get_package(pkg["id"], make_member_headers(member["id"])))
    assert reread_pkg["status"] == "PENDING"


def test_package_activates_when_member_active(api):
    """PRD §3.6: "The package moves `PENDING` to `ACTIVE` when the owning `Member` (or a
    `FrontDeskAgent` on their behalf) activates it on first payment; activation requires
    the member to be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/package_activate_requires_member_active_pair_package_member
    """
    # Complement: an ACTIVE member's package activates successfully, confirming the gate
    # is the member's status (Package -> Member dependency), not something else.
    salon = th.create_and_open_salon()
    member = th.add_member(salon["id"])  # starts ACTIVE
    pkg = validate_success(
        api.create_package(th.create_package_payload(member["id"], "SILVER"), FRONT_DESK),
        201,
    )
    activated = validate_success(
        api.activate_package(pkg["id"], make_member_headers(member["id"]))
    )
    assert activated["status"] == "ACTIVE"


# ===========================================================================
# Difficulty A: resource_temporal_overlap / chair_sanitation_window_blocks_early_mark
# ===========================================================================
def test_mark_sanitized_before_window_elapses_rejected(api):
    """PRD §3.9: "A `FrontDeskAgent` or `SalonManager` marks the chair back to `OPEN`
    once the window has elapsed — the logical clock must be at or after
    `sanitation_ready_at` — and a mark-sanitized attempted before that instant is
    refused with `ERR_SANITATION_WINDOW_OPEN`."

    Design: Difficulty/resource_temporal_overlap/chair_sanitation_window_blocks_early_mark
    """
    th.set_clock("2026-02-01T10:00:00Z")
    salon = th.create_and_open_salon(set_default_clock=False)
    chair = th.add_chair(salon["id"], sanitation_minutes=5)
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    visit = th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"])
    th.complete_visit(visit["id"], tech["id"])  # sanitation_ready_at = 10:05
    th.set_clock("2026-02-01T10:02:00Z")  # inside the window
    resp = api.mark_chair_sanitized(chair["id"], FRONT_DESK)
    validate_error(resp, ApiErrorId.ERR_SANITATION_WINDOW_OPEN.value, expected_status=409)
    chair_after = validate_success(api.get_chair(chair["id"], MANAGER))
    assert chair_after["status"] == "SANITIZING"
    assert same_instant(chair_after["sanitation_ready_at"], "2026-02-01T10:05:00Z")


def test_mark_sanitized_at_window_end_succeeds(api):
    """PRD §3.9: "A `FrontDeskAgent` or `SalonManager` marks the chair back to `OPEN`
    once the window has elapsed — the logical clock must be at or after
    `sanitation_ready_at`."

    Design: Difficulty/resource_temporal_overlap/chair_sanitation_window_blocks_early_mark
    """
    # Boundary: at exactly sanitation_ready_at (10:05) the mark succeeds (clock >= ready).
    th.set_clock("2026-02-01T10:00:00Z")
    salon = th.create_and_open_salon(set_default_clock=False)
    chair = th.add_chair(salon["id"], sanitation_minutes=5)
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    visit = th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"])
    th.complete_visit(visit["id"], tech["id"])  # sanitation_ready_at = 10:05
    th.set_clock("2026-02-01T10:05:00Z")  # exactly at the window end
    opened = validate_success(api.mark_chair_sanitized(chair["id"], FRONT_DESK))
    assert opened["status"] == "OPEN"


# ===========================================================================
# Difficulty A: resource_temporal_overlap / technician_double_booking_busy_block
# ===========================================================================
def test_seat_second_visit_onto_busy_technician_rejected(api):
    """PRD §3.4: "The chosen technician must be `AVAILABLE`, else
    `ERR_TECHNICIAN_NOT_AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/technician_double_booking_busy_block
    """
    salon = th.create_and_open_salon()
    chair1 = th.add_chair(salon["id"])
    chair2 = th.add_chair(salon["id"])
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    m_a = th.add_member(salon["id"])
    m_b = th.add_member(salon["id"])
    t_a = th.join_and_call(salon["id"], m_a["id"], svc["id"])
    live = validate_success(api.get_salon(salon["id"], MANAGER))
    th.seat_visit(salon["id"], t_a["id"], chair1["id"], tech["id"], live["version"])
    # B joins, called with allow_skip; seating onto the now-BUSY tech must fail.
    t_b = th.join_and_call(salon["id"], m_b["id"], svc["id"], allow_skip=True)
    live2 = validate_success(api.get_salon(salon["id"], MANAGER))
    resp = api.create_service_visit(
        th.create_service_visit_payload(
            salon["id"], t_b["id"], chair2["id"], tech["id"], live2["version"]
        ),
        FRONT_DESK,
    )
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_AVAILABLE.value, expected_status=409)
    tech_after = validate_success(api.get_technician(tech["id"], MANAGER))
    assert tech_after["status"] == "BUSY"


def test_seating_flips_technician_available_to_busy(api):
    """PRD §3.4: "the technician flips `AVAILABLE` to `BUSY`."

    Design: Difficulty/resource_temporal_overlap/technician_double_booking_busy_block
    """
    # The single-occupancy invariant's precondition: a seated tech is BUSY (so the next
    # seating onto it is blocked). Confirm the AVAILABLE->BUSY flip directly.
    base = th.setup_open_salon_basic()
    salon, chair, tech, svc, member = (
        base["salon"], base["chair"], base["tech"], base["svc"], base["member"]
    )
    before = validate_success(api.get_technician(tech["id"], MANAGER))
    assert before["status"] == "AVAILABLE"
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    th.seat_visit(salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"])
    after = validate_success(api.get_technician(tech["id"], MANAGER))
    assert after["status"] == "BUSY"


# ===========================================================================
# Difficulty A: priority_pair_validation_conflict / license_lapsed_beats_chair_not_sanitized
# ===========================================================================
def test_license_lapsed_beats_chair_not_sanitized_at_seating(api):
    """PRD §3.4: "The license must still be `ACTIVE` at the moment of seating, else
    `ERR_LICENSE_LAPSED`. The chosen chair must be `OPEN`, else `ERR_CHAIR_NOT_OPEN`;
    and if the chair carries a `sanitation_ready_at`, the logical clock must have
    reached or passed it ... else the chair is still cooling down and the seating is
    refused with `ERR_CHAIR_NOT_SANITIZED`."

    Design: Difficulty/priority_pair_validation_conflict/license_lapsed_beats_chair_not_sanitized
    """
    th.set_clock("2026-02-01T09:00:00Z")
    salon = th.create_and_open_salon(
        set_default_clock=False, license_expiry="2026-03-01T00:00:00Z"
    )
    chair = th.add_chair(salon["id"], sanitation_minutes=5)
    tech = th.add_technician(salon["id"])
    svc = th.add_service_item(salon["id"])
    m1 = th.add_member(salon["id"])
    t1 = th.join_and_call(salon["id"], m1["id"], svc["id"])
    live = validate_success(api.get_salon(salon["id"], MANAGER))
    v1 = th.seat_visit(salon["id"], t1["id"], chair["id"], tech["id"], live["version"])
    th.complete_visit(v1["id"], tech["id"])  # chair now SANITIZING, not yet OPEN
    m2 = th.add_member(salon["id"])
    t2 = th.join_and_call(salon["id"], m2["id"], svc["id"])
    live2 = validate_success(api.get_salon(salon["id"], MANAGER))
    # Advance clock past license_expiry (and chair is still SANITIZING).
    th.set_clock("2026-04-01T00:00:00Z")
    resp = api.create_service_visit(
        th.create_service_visit_payload(
            salon["id"], t2["id"], chair["id"], tech["id"], live2["version"]
        ),
        FRONT_DESK,
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_LAPSED.value, expected_status=403)


# NOTE: A companion test asserting ERR_CHAIR_NOT_SANITIZED at seating was removed.
# PRD §3.4 orders the seating chair gates OPEN-first: "The chosen chair must be
# `OPEN`, else `ERR_CHAIR_NOT_OPEN`; and if the chair carries a `sanitation_ready_at`,
# the logical clock must have reached or passed it ... else ... `ERR_CHAIR_NOT_SANITIZED`."
# A SANITIZING chair is not OPEN, so it fails the OPEN gate first and yields
# ERR_CHAIR_NOT_OPEN (as the kept test_chair_status_open_required_is_a_seating_precondition
# asserts). Under this PRD-stated precedence, plus a forward-only logical clock and a
# mark-sanitized that requires clock>=sanitation_ready_at, no PRD-faithful state reaches
# ERR_CHAIR_NOT_SANITIZED at seating (it would need an OPEN chair carrying a *future*
# sanitation_ready_at, which is unreachable). The deleted assertion therefore contradicted
# the PRD's own OPEN-first precedence and is not uniquely derivable (ERROR PRECEDENCE).


# ===========================================================================
# Corner B: state_machines / take_occupied_chair_out_of_service_rejected
# ===========================================================================
def test_take_occupied_chair_out_of_service_rejected(api):
    """PRD §3.9: "a `SalonManager` may take a chair out of service, but only when it is
    not `OCCUPIED`; taking an occupied chair out of service is rejected with
    `ERR_CHAIR_OCCUPIED`."

    Design: Corner/state_machines/take_occupied_chair_out_of_service_rejected
    """
    s = th.setup_seated_visit()
    chair = s["chair"]
    resp = api.take_chair_out_of_service(chair["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_CHAIR_OCCUPIED.value, expected_status=409)
    chair_after = validate_success(api.get_chair(chair["id"], MANAGER))
    assert chair_after["status"] == "OCCUPIED"


# ===========================================================================
# Corner B: endpoints / technician_cert_expired_at_seating_rejected
# ===========================================================================
def test_technician_cert_expired_at_seating_rejected(api):
    """PRD §3.4: "the technician's `sanitation_cert_expiry` must lie in the future (the
    logical clock is strictly before it), else `ERR_TECH_CERT_EXPIRED`."

    Design: Corner/endpoints/technician_cert_expired_at_seating_rejected
    """
    th.set_clock("2026-01-05T00:00:00Z")
    salon = th.create_and_open_salon(set_default_clock=False)
    chair = th.add_chair(salon["id"])
    tech = th.add_technician(salon["id"], sanitation_cert_expiry="2026-01-10T00:00:00Z")
    svc = th.add_service_item(salon["id"])
    member = th.add_member(salon["id"])
    ticket = th.join_and_call(salon["id"], member["id"], svc["id"])
    th.set_clock("2026-01-20T00:00:00Z")  # past cert expiry, before license expiry
    resp = api.create_service_visit(
        th.create_service_visit_payload(
            salon["id"], ticket["id"], chair["id"], tech["id"], salon["version"]
        ),
        FRONT_DESK,
    )
    validate_error(resp, ApiErrorId.ERR_TECH_CERT_EXPIRED.value, expected_status=403)


# ===========================================================================
# Corner B: cross_cutting / occ_stale_salon_version_on_seating
# ===========================================================================
def test_occ_stale_salon_version_on_seating_rejected(api):
    """PRD §2.9: "If that value does not equal the salon's current `version` — because
    another writer has seated or freed a chair, or opened or closed the salon, since
    the client last read it — the seating is rejected with `ERR_STALE_SALON_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_salon_version_on_seating
    """
    salon = th.create_and_open_salon()
    stale_version = salon["version"]
    chair1 = th.add_chair(salon["id"])
    chair2 = th.add_chair(salon["id"])
    tech1 = th.add_technician(salon["id"], display_name="T1")
    tech2 = th.add_technician(salon["id"], display_name="T2")
    svc = th.add_service_item(salon["id"])
    m_a = th.add_member(salon["id"])
    m_b = th.add_member(salon["id"])
    t_a = th.join_and_call(salon["id"], m_a["id"], svc["id"])
    t_b = th.join_and_call(salon["id"], m_b["id"], svc["id"], allow_skip=True)
    # First seating consumes a version bump (now stale_version is one behind).
    th.seat_visit(salon["id"], t_a["id"], chair1["id"], tech1["id"], stale_version)
    resp = api.create_service_visit(
        th.create_service_visit_payload(
            salon["id"], t_b["id"], chair2["id"], tech2["id"], stale_version
        ),
        FRONT_DESK,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SALON_VERSION.value, expected_status=412)
