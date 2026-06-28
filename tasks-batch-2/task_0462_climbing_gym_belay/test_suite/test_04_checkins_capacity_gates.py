"""Check-in gates (waiver / belay / membership-active), capacity boundary,
facility OCC, live-occupancy overlap, and the safety-beats-fiscal priority pair.

Covers difficulty instances on the capacity boundary, validation-priority
conflict, cross-entity access dependency, and live-count overlap semantics, plus
corner instances on the gate errors and OCC outcomes.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_member, create_waiver, create_member_with_waiver, create_membership,
    create_frozen_membership, create_facility, create_passed_belay_cert,
    check_in, set_clock, fill_facility_to_capacity, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── Difficulty: capacity full at exactly floor_capacity ──────────────────
def test_checkin_rejected_at_exact_floor_capacity(api):
    """PRD §3.6: "capacity is checked: a check-in is admitted only while the
    facility's occupancy is strictly below its floor_capacity; when occupancy has
    reached or exceeded floor capacity the check-in is rejected with
    ERR_CAPACITY_FULL (HTTP 422)."

    Design: Difficulty/boundary_precision_check/facility_capacity_full_at_exact_floor_capacity
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="Two Slot", floor_capacity=2)
    version = fill_facility_to_capacity(facility, 2)  # occupancy now 2 of 2
    fac = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac["occupancy"] == 2

    member, _ = create_member_with_waiver()
    res = api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": version,
    }, FD)
    validate_error(res, "ERR_CAPACITY_FULL")
    fac_after = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac_after["occupancy"] == 2, "rejected check-in did not increment"


def test_checkin_succeeds_below_floor_capacity(api):
    """PRD §3.6: "a check-in is admitted only while the facility's occupancy is
    strictly below its floor_capacity"
    PRD §3.6: "A successful check-in sets status to ON_FLOOR ... increments the
    facility's occupancy by one, and bumps the facility's version."

    Design: Difficulty/boundary_precision_check/facility_capacity_full_at_exact_floor_capacity
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="Two Slot Ok", floor_capacity=2)
    version = fill_facility_to_capacity(facility, 1)  # occupancy now 1 of 2
    member, _ = create_member_with_waiver()
    ci = validate_success(api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": version,
    }, FD), 201)
    assert ci["status"] == "ON_FLOOR"
    fac_after = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac_after["occupancy"] == 2


# ─── Difficulty: waiver (safety) beats capacity (fiscal) ──────────────────
def test_waiver_gate_beats_capacity_gate(api):
    """PRD §2.9: "the check-in waiver gate, yielding ERR_WAIVER_INVALID ... which
    is checked before the version match, which is checked before capacity."
    PRD §3.6: "First, the climber must hold a currently valid waiver ... absent
    that, the check-in is rejected with ERR_WAIVER_INVALID (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/waiver_safety_beats_capacity_fiscal_on_checkin
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="Tiny Wall", floor_capacity=1)
    version = fill_facility_to_capacity(facility, 1)  # full
    member_no_waiver = create_member()  # NO waiver
    res = api.create_checkin({
        "member_id": member_no_waiver["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": version,
    }, FD)
    validate_error(res, "ERR_WAIVER_INVALID")
    fac_after = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac_after["occupancy"] == 1, "rejected check-in did not increment"


def test_capacity_gate_fires_when_waiver_valid(api):
    """PRD §2.9: "within the safety gates the waiver is checked before the belay
    certification ... which is checked before the version match, which is checked
    before capacity."
    PRD §3.6: "when occupancy has reached or exceeded floor capacity the check-in
    is rejected with ERR_CAPACITY_FULL (HTTP 422)."

    With the waiver gate satisfied, the lower-priority capacity gate is the
    one that fires — confirming the precedence test genuinely demonstrates the
    ordering rather than a constant outcome.

    Design: Difficulty/priority_pair_validation_conflict/waiver_safety_beats_capacity_fiscal_on_checkin
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="Tiny Wall 2", floor_capacity=1)
    version = fill_facility_to_capacity(facility, 1)  # full
    member, _ = create_member_with_waiver()  # waiver IS valid
    res = api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": version,
    }, FD)
    validate_error(res, "ERR_CAPACITY_FULL")


# ─── Difficulty: membership check-in requires ACTIVE access ───────────────
def test_membership_checkin_blocked_when_frozen(api):
    """PRD §3.6: "For a MEMBERSHIP entry, the member must additionally hold a
    membership whose access_status is ACTIVE (not FROZEN, SUSPENDED, or
    TERMINATED); if no active membership exists the check-in is rejected with
    ERR_MEMBERSHIP_NOT_ACTIVE (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/membership_checkin_requires_active_access_status
    """
    set_clock("2026-06-01T00:00:00Z")
    member, frozen = create_frozen_membership()
    create_waiver(member["id"])
    facility = create_facility(name="Open Wall", floor_capacity=10)
    res = api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "MEMBERSHIP", "expected_facility_version": facility["version"],
    }, FD)
    validate_error(res, "ERR_MEMBERSHIP_NOT_ACTIVE")
    fac_after = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac_after["occupancy"] == 0


def test_membership_checkin_succeeds_when_active(api):
    """PRD §3.6: "the member must additionally hold a membership whose
    access_status is ACTIVE (not FROZEN, SUSPENDED, or TERMINATED)"
    PRD §3.6: "A successful check-in sets status to ON_FLOOR, computes price_cents
    (0 for a membership entry, or the day-pass price for a day-pass entry)"

    Design: Difficulty/cross_entity_state_dependency/membership_checkin_requires_active_access_status
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver()
    create_membership(member["id"], plan_tier="BASIC")
    facility = create_facility(name="Active Wall", floor_capacity=10)
    ci = validate_success(api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "MEMBERSHIP", "expected_facility_version": facility["version"],
    }, FD), 201)
    assert ci["status"] == "ON_FLOOR"
    assert ci["price_cents"] == 0


# ─── Difficulty: live-occupancy overlap (check-out frees the slot) ────────
def test_checkout_frees_floor_slot_immediately(api):
    """PRD §3.5: "The occupancy is always the live count of check-ins on that
    facility whose status is ON_FLOOR."
    PRD §3.6: "Checking out is a front-desk operation that moves a check-in from
    ON_FLOOR to CHECKED_OUT, stamps checked_out_at from the clock, recomputes the
    facility's occupancy, and bumps the facility's version."

    Design: Difficulty/resource_temporal_overlap/facility_floor_live_occupancy_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="Single", floor_capacity=1)
    member_a, _ = create_member_with_waiver()
    ci_a = check_in(member_a["id"], facility["id"], facility["version"])
    after_in = validate_success(api.get_facility(facility["id"], FD), 200)
    assert after_in["occupancy"] == 1
    # Check out the first member; the single slot frees immediately.
    validate_success(api.check_out(ci_a["id"], FD), 200)
    freed = validate_success(api.get_facility(facility["id"], FD), 200)
    assert freed["occupancy"] == 0

    member_b, _ = create_member_with_waiver()
    ci_b = validate_success(api.create_checkin({
        "member_id": member_b["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": freed["version"],
    }, FD), 201)
    assert ci_b["status"] == "ON_FLOOR"
    final = validate_success(api.get_facility(facility["id"], FD), 200)
    assert final["occupancy"] == 1


def test_concurrent_on_floor_climbers_blocked_by_live_count(api):
    """PRD §3.5: "The occupancy is always the live count of check-ins on that
    facility whose status is ON_FLOOR."
    PRD §3.6: "a check-in is admitted only while the facility's occupancy is
    strictly below its floor_capacity; when occupancy has reached or exceeded
    floor capacity the check-in is rejected with ERR_CAPACITY_FULL (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/facility_floor_live_occupancy_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    facility = create_facility(name="Single Live", floor_capacity=1)
    member_a, _ = create_member_with_waiver()
    check_in(member_a["id"], facility["id"], facility["version"])  # occupies the slot
    fac = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac["occupancy"] == 1
    # Second climber while the first is still ON_FLOOR → blocked by live count.
    member_b, _ = create_member_with_waiver()
    res = api.create_checkin({
        "member_id": member_b["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": fac["version"],
    }, FD)
    validate_error(res, "ERR_CAPACITY_FULL")


# ─── Corner: belay-cert gate ──────────────────────────────────────────────
def test_belay_required_facility_without_cert_rejected(api):
    """PRD §3.6: "if the target facility's requires_belay_cert is true, the member
    must hold a certification — in either the BELAY or LEAD discipline — whose
    status is PASSED and which is not expired; absent that, the check-in is
    rejected with ERR_BELAY_CERT_REQUIRED (HTTP 422)."

    Design: Corner/validations/checkin_belay_required_facility_without_cert_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver()
    facility = create_facility(name="Belay Wall", floor_capacity=10, requires_belay_cert=True)
    res = api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": facility["version"],
    }, FD)
    validate_error(res, "ERR_BELAY_CERT_REQUIRED")


# ─── Corner: invalid entry_kind enum ──────────────────────────────────────
def test_checkin_bad_entry_kind_enum_rejected(api):
    """PRD §2.9: "well-formedness of the request body — required fields present,
    enum values valid, and numeric ranges respected — yielding ERR_INVALID_REQUEST"
    PRD §3.6: "The entry_kind is either MEMBERSHIP, which draws on an active
    membership at no per-visit charge, or DAY_PASS, which pays a one-off fee."

    Design: Corner/validations/checkin_invalid_request_bad_entry_kind_enum
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver()
    facility = create_facility(name="Enum Wall", floor_capacity=10)
    res = api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "SEASON", "expected_facility_version": facility["version"],
    }, FD)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner: expired waiver blocks check-in ───────────────────────────────
def test_expired_waiver_blocks_checkin(api):
    """PRD §3.1: "it reads VALID while the clock is strictly before expires_at, and
    EXPIRED once the clock reaches or passes expires_at."
    PRD §3.6: "the climber must hold a currently valid waiver — a waiver whose
    status is VALID because the clock is before its expires_at; absent that, the
    check-in is rejected with ERR_WAIVER_INVALID (HTTP 422)."

    Design: Corner/validations/waiver_invalid_after_expiry_blocks_checkin
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver()  # signed 2026-06-01 → expires 2027-06-01
    facility = create_facility(name="Stale Wall", floor_capacity=10)
    set_clock("2027-06-02T00:00:00Z")  # past waiver expiry
    res = api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": facility["version"],
    }, FD)
    validate_error(res, "ERR_WAIVER_INVALID")


# ─── Corner: facility OCC happy path + stale ──────────────────────────────
def test_checkin_with_matching_facility_version_succeeds(api):
    """PRD §2.6: "When `expected_facility_version` does not equal the facility's
    current `version`, the create is rejected with `ERR_STALE_FACILITY_VERSION`
    (HTTP 412)."
    PRD §3.6: "increments the facility's `occupancy` by one, and bumps the
    facility's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_facility_correct_version_checkin_succeeds
    """
    set_clock("2026-06-01T00:00:00Z")
    member, _ = create_member_with_waiver()
    facility = create_facility(name="OCC Wall", floor_capacity=10)
    ci = validate_success(api.create_checkin({
        "member_id": member["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": facility["version"],
    }, FD), 201)
    fac_after = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac_after["occupancy"] == 1
    assert fac_after["version"] == 2


def test_checkin_with_stale_facility_version_rejected(api):
    """PRD §2.6: "if another writer has advanced the facility's version since the
    client last read it, the client is operating on a stale view of remaining
    capacity. When expected_facility_version does not equal the facility's current
    version, the create is rejected with ERR_STALE_FACILITY_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_facility_stale_version_checkin_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    member_a, _ = create_member_with_waiver()
    member_b, _ = create_member_with_waiver()
    facility = create_facility(name="Stale Wall2", floor_capacity=10)
    stale_version = facility["version"]
    # First check-in advances the facility version to 2.
    check_in(member_a["id"], facility["id"], stale_version)
    res = api.create_checkin({
        "member_id": member_b["id"], "facility_id": facility["id"],
        "entry_kind": "DAY_PASS", "expected_facility_version": stale_version,
    }, FD)
    validate_error(res, "ERR_STALE_FACILITY_VERSION")
    fac_after = validate_success(api.get_facility(facility["id"], FD), 200)
    assert fac_after["occupancy"] == 1, "stale check-in did not increment"
