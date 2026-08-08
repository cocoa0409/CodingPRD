"""Placement, transport-start, and viewing-confirm guards: capacity boundary,
cross-entity availability, safety-vs-temporal precedence, and single-error cases."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_client, make_vault, make_artwork, make_placement, make_crate, make_crew,
    make_viewing_room,
    setup_ready_transport, setup_two_bookings,
    placement_payload, transport_job_payload, viewing_booking_payload,
    condition_report_payload,
    REG, COORD,
    api_client as api,
)


# ==========================================================================
# Boundary: vault capacity full (>= boundary)
# ==========================================================================
def test_second_placement_at_capacity_rejected():
    """PRD §3.2: "and when the vault is already full, meaning its `occupied_slots`
    is greater than or equal to its `capacity_slots` (`ERR_VAULT_FULL`)."

    Design: Difficulty/boundary_precision_check/vault_capacity_full_boundary
    """
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=1)
    a1 = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    a2 = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    make_placement(a1["id"], v["id"])
    resp = api.create_placement(placement_payload(a2["id"], v["id"]), REG)
    validate_error(resp, ApiErrorId.ERR_VAULT_FULL.value, 409)


def test_full_vault_occupied_slots_unchanged():
    """PRD §2.8: "a vault's `occupied_slots` always equals the count of that
    vault's placements currently in `ACTIVE` status".

    Design: Difficulty/boundary_precision_check/vault_capacity_full_boundary
    """
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=1)
    a1 = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    a2 = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    make_placement(a1["id"], v["id"])
    api.create_placement(placement_payload(a2["id"], v["id"]), REG)
    vault = validate_success(api.get_vault(v["id"], REG))
    assert vault["occupied_slots"] == 1, vault


# ==========================================================================
# Cross-entity: transport start requires artwork IN_STORAGE
# ==========================================================================
def test_start_transport_intake_artwork_rejected():
    """PRD §3.4: "Starting the job advances it from `SCHEDULED` to `IN_PROGRESS`,
    but only when three conditions hold, evaluated in this order: the artwork's
    `condition_status` must not be `MAJOR_DAMAGE` (else
    `ERR_ARTWORK_CONDITION_UNSAFE`); the artwork's `custody_status` must be
    `IN_STORAGE` (else `ERR_ARTWORK_NOT_AVAILABLE`); and the named crate must be
    `READY` and built for that same artwork — its `crate_id` must reference a crate
    whose own artwork matches the job's `artwork_id` (else `ERR_CRATE_NOT_READY`)."

    Design: Difficulty/cross_entity_state_dependency/transport_requires_artwork_in_storage
    """
    s = setup_ready_transport(place_artwork=False, requires_rigging=True, estimated_hours=2)
    resp = api.transition_transport_job(s["job"]["id"], {"to_status": "IN_PROGRESS"}, COORD)
    validate_error(resp, ApiErrorId.ERR_ARTWORK_NOT_AVAILABLE.value, 409)


def test_start_transport_blocked_leaves_job_scheduled():
    """PRD §3.4: "the artwork's `custody_status` must be `IN_STORAGE` (else
    `ERR_ARTWORK_NOT_AVAILABLE`); and the named crate must be `READY` and built for
    that same artwork — its `crate_id` must reference a crate whose own artwork
    matches the job's `artwork_id` (else `ERR_CRATE_NOT_READY`)."

    Design: Difficulty/cross_entity_state_dependency/transport_requires_artwork_in_storage
    """
    s = setup_ready_transport(place_artwork=False, requires_rigging=True, estimated_hours=2)
    api.transition_transport_job(s["job"]["id"], {"to_status": "IN_PROGRESS"}, COORD)
    job = validate_success(api.get_transport_job(s["job"]["id"], COORD))
    assert job["status"] == "SCHEDULED", job


# ==========================================================================
# Priority pair: safety (condition) beats temporal (room overlap) on confirm
# ==========================================================================
def test_viewing_confirm_returns_condition_unsafe_over_temporal():
    """PRD §3.7: "A coordinator confirms a booking, moving it from `REQUESTED` to
    `CONFIRMED`, subject to three checks in order: the artwork's `condition_status`
    must not be `MAJOR_DAMAGE` (else `ERR_ARTWORK_CONDITION_UNSAFE`); the room must
    be `OPERATIONAL` (else `ERR_ROOM_NOT_OPERATIONAL`); and the requested window
    must not half-open overlap any other `CONFIRMED` booking on the same room, per
    the no-buffer rule of Section 2.9 (else `ERR_ROOM_UNAVAILABLE`)."

    Design: Difficulty/priority_pair_validation_conflict/viewing_confirm_safety_beats_temporal
    """
    s = setup_two_bookings("2026-05-02T14:30:00Z", "2026-05-02T15:30:00Z", damage_second=True)
    resp = api.transition_viewing_booking(s["b2"]["id"], {"to_status": "CONFIRMED"}, COORD)
    validate_error(resp, ApiErrorId.ERR_ARTWORK_CONDITION_UNSAFE.value, 422)


def test_viewing_confirm_safety_block_leaves_booking_requested():
    """PRD §3.7: "the artwork's `condition_status` must not be `MAJOR_DAMAGE` (else
    `ERR_ARTWORK_CONDITION_UNSAFE`); the room must be `OPERATIONAL` (else
    `ERR_ROOM_NOT_OPERATIONAL`); and the requested window must not half-open
    overlap any other `CONFIRMED` booking on the same room, per the no-buffer rule
    of Section 2.9 (else `ERR_ROOM_UNAVAILABLE`)."

    Design: Difficulty/priority_pair_validation_conflict/viewing_confirm_safety_beats_temporal
    """
    s = setup_two_bookings("2026-05-02T14:30:00Z", "2026-05-02T15:30:00Z", damage_second=True)
    api.transition_viewing_booking(s["b2"]["id"], {"to_status": "CONFIRMED"}, COORD)
    booking = validate_success(api.get_viewing_booking(s["b2"]["id"], COORD))
    assert booking["status"] == "REQUESTED", booking


# ==========================================================================
# Corner: single-error placement validations
# ==========================================================================
def test_placement_climate_mismatch_returns_error():
    """PRD §3.2: "when the artwork's required `climate_class` does not equal the
    vault's `climate_class` (`ERR_CLIMATE_MISMATCH`)".

    Design: Corner/validations/placement_climate_mismatch_returns_error
    """
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=3)
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="HIGH", climate_class="COLD")
    resp = api.create_placement(placement_payload(a["id"], v["id"]), REG)
    validate_error(resp, ApiErrorId.ERR_CLIMATE_MISMATCH.value, 422)


def test_placement_on_maintenance_vault_returns_unavailable():
    """PRD §3.2: "when the vault is not `OPERATIONAL` (`ERR_VAULT_UNAVAILABLE`)".

    Design: Corner/validations/placement_on_maintenance_vault_returns_unavailable
    """
    c = make_client()
    v = make_vault(climate_class="AMBIENT", capacity_slots=3)
    get_success_data(api.transition_vault(v["id"], {"to_status": "MAINTENANCE"}, REG))
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW", climate_class="AMBIENT")
    resp = api.create_placement(placement_payload(a["id"], v["id"]), REG)
    validate_error(resp, ApiErrorId.ERR_VAULT_UNAVAILABLE.value, 409)


# ==========================================================================
# Corner: single-error transport validations
# ==========================================================================
def test_transport_inverted_window_returns_time_window_invalid():
    """PRD §2.9: "For every interval-bearing request — transport jobs, storage
    placements, insurance policies, viewing bookings, loans, and carnets — the end
    instant must be strictly after the start instant (a transport or booking's
    `scheduled_end` after its `scheduled_start`, a policy's `effective_end` after
    its `effective_start`, a placement's `scheduled_end_at` after its `start_at`),
    or the request is rejected with `ERR_TIME_WINDOW_INVALID`."

    Design: Corner/validations/transport_inverted_window_returns_time_window_invalid
    """
    c = make_client(client_type="DEALER")
    a = make_artwork(c["id"])
    crate = make_crate(a["id"])
    crew = make_crew(certification_level="STANDARD", crew_size=2)
    resp = api.create_transport_job(
        transport_job_payload(a["id"], crate["id"], crew["id"],
                              scheduled_start="2026-06-01T11:00:00Z",
                              scheduled_end="2026-06-01T09:00:00Z",
                              requires_rigging=False, estimated_hours=2), COORD)
    validate_error(resp, ApiErrorId.ERR_TIME_WINDOW_INVALID.value, 422)


def test_transport_start_with_building_crate_returns_crate_not_ready():
    """PRD §3.4: "the named crate must be `READY` and built for that same artwork —
    its `crate_id` must reference a crate whose own artwork matches the job's
    `artwork_id` (else `ERR_CRATE_NOT_READY`)."

    Design: Corner/validations/transport_start_with_building_crate_returns_crate_not_ready
    """
    c = make_client(client_type="DEALER")
    v = make_vault(climate_class="AMBIENT", capacity_slots=3)
    a = make_artwork(c["id"], climate_class="AMBIENT")
    make_placement(a["id"], v["id"])
    crate = make_crate(a["id"], ready=False)  # still BUILDING
    crew = make_crew(certification_level="STANDARD", crew_size=2)
    job = get_success_data(api.create_transport_job(
        transport_job_payload(a["id"], crate["id"], crew["id"],
                              requires_rigging=False, estimated_hours=2), COORD))
    resp = api.transition_transport_job(job["id"], {"to_status": "IN_PROGRESS"}, COORD)
    validate_error(resp, ApiErrorId.ERR_CRATE_NOT_READY.value, 409)


# ==========================================================================
# Corner: single-error viewing-confirm validations
# ==========================================================================
def test_viewing_confirm_on_closed_room_returns_not_operational():
    """PRD §3.7: "subject to three checks in order: the artwork's
    `condition_status` must not be `MAJOR_DAMAGE` (else
    `ERR_ARTWORK_CONDITION_UNSAFE`); the room must be `OPERATIONAL` (else
    `ERR_ROOM_NOT_OPERATIONAL`); and the requested window must not half-open
    overlap any other `CONFIRMED` booking on the same room, per the no-buffer rule
    of Section 2.9 (else `ERR_ROOM_UNAVAILABLE`)."

    Design: Corner/validations/viewing_confirm_on_closed_room_returns_not_operational
    """
    c = make_client()
    room = make_viewing_room()
    get_success_data(api.transition_viewing_room(room["id"], {"to_status": "CLOSED"}, COORD))
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    b = get_success_data(api.create_viewing_booking(
        viewing_booking_payload(a["id"], room["id"], c["id"],
                                scheduled_start="2026-05-02T10:00:00Z",
                                scheduled_end="2026-05-02T11:00:00Z"), COORD))
    resp = api.transition_viewing_booking(b["id"], {"to_status": "CONFIRMED"}, COORD)
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_OPERATIONAL.value, 409)


def test_viewing_confirm_overlap_returns_room_unavailable():
    """PRD §3.7: "the requested window must not half-open overlap any other
    `CONFIRMED` booking on the same room, per the no-buffer rule of Section 2.9
    (else `ERR_ROOM_UNAVAILABLE`)."

    Design: Corner/validations/viewing_confirm_overlap_returns_room_unavailable
    """
    s = setup_two_bookings("2026-05-02T14:30:00Z", "2026-05-02T15:30:00Z", damage_second=False)
    resp = api.transition_viewing_booking(s["b2"]["id"], {"to_status": "CONFIRMED"}, COORD)
    validate_error(resp, ApiErrorId.ERR_ROOM_UNAVAILABLE.value, 409)
